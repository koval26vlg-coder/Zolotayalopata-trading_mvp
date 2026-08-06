from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

import gate_historical_archive as gate_archive
import gate_historical_membership_history_plan as history_plan
import gate_historical_membership_v2_closure as membership_v2_closure


SCHEMA = "trading_mvp_gate_historical_membership_archive_source_plan_v3"
PROBE_SCHEMA = "trading_mvp_gate_historical_membership_archive_source_probe_v3"
PLAN_DECISION = "GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_PLAN_READY_AWAITING_EXPLICIT_PUBLIC_PROBE_APPROVAL"
PLAN_INSUFFICIENT_DECISION = "GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_PLAN_INSUFFICIENT_CANDIDATES"
ACCEPTED_PROBE_DECISION = "GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_ACCEPTED_READY_FOR_HISTORY_PLANONLY"
REJECTED_PROBE_DECISION = "GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_REJECTED"
STOPPED_INCOMPLETE_DECISION = "GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_PROBE_STOPPED_INCOMPLETE"
MAX_RUNTIME_SEC = 600
DAY_SEC = 86_400
HISTORY_DAYS = 220
ACTIVE_SAMPLE_SIZE = 10
MISSING_END_SAMPLE_SIZE = 10
KNOWN_END_SAMPLE_SIZE = 5
MIN_CANDIDATES = 8
MIN_COHORT_SYMBOL_AVAILABILITY = 0.80
MAX_REQUEST_ERROR_RATE = 0.05
DEFAULT_WORKERS = 8
FetchOverride = Callable[[Mapping[str, Any], float], tuple[int, Mapping[str, str]]]
_thread_state = threading.local()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {resolved}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _write_json_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        if _read_json_object(path) != dict(payload):
            raise FileExistsError(f"refusing to overwrite immutable PlanOnly artifact: {path}")
        return
    _atomic_write_json(path, payload)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _history_window(daily_manifest: Mapping[str, Any]) -> tuple[int, int]:
    if daily_manifest.get("schema") != "daily_collect_v1":
        raise ValueError("unexpected daily manifest schema")
    params = daily_manifest.get("params")
    if not isinstance(params, Mapping):
        raise ValueError("daily manifest params are missing")
    end_raw = _as_int(params.get("end_sec"))
    if end_raw is None:
        raise ValueError("daily manifest end_sec is missing")
    end_sec = (end_raw // DAY_SEC) * DAY_SEC
    return end_sec - HISTORY_DAYS * DAY_SEC, end_sec


def _validate_closure_inputs(
    closure_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validated = membership_v2_closure.validate_closure_manifest(closure_manifest_path)
    if validated.get("next_allowed_action") != "select_new_materially_distinct_planonly_hypothesis":
        raise ValueError("membership-v2 closure does not permit a new PlanOnly source contract")
    closure = _read_json_object(validated["closure_path"])
    probe_ref = closure.get("probe_provenance")
    plan_ref = closure.get("plan_provenance")
    if not isinstance(probe_ref, Mapping) or not isinstance(plan_ref, Mapping):
        raise ValueError("membership-v2 closure provenance is incomplete")
    probe_path = Path(str(probe_ref.get("path") or "")).expanduser().resolve()
    plan_path = Path(str(plan_ref.get("path") or "")).expanduser().resolve()
    if sha256_file(probe_path) != probe_ref.get("file_sha256"):
        raise ValueError("membership-v2 source probe file hash mismatch")
    if sha256_file(plan_path) != plan_ref.get("file_sha256"):
        raise ValueError("membership-v2 source plan file hash mismatch")
    probe = _read_json_object(probe_path)
    source_plan = _read_json_object(plan_path)
    if probe.get("artifact_hash") != probe_ref.get("artifact_hash"):
        raise ValueError("membership-v2 source probe artifact hash mismatch")
    if source_plan.get("plan_hash") != plan_ref.get("plan_hash"):
        raise ValueError("membership-v2 source plan semantic hash mismatch")
    return closure, probe, source_plan


def select_candidates(
    probe_rows: list[Any],
    registry: Mapping[str, Mapping[str, str]],
    registry_exclusions: Mapping[str, str],
    *,
    window_start_sec: int,
    window_end_sec: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in probe_rows:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()
        if symbol:
            grouped[symbol].append(dict(raw))
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for symbol in sorted(grouped):
        rows = grouped[symbol]
        row = rows[0]
        base = str(row.get("base") or "").strip().upper()
        if len(rows) != 1:
            excluded.append({"symbol": symbol, "base": base, "reason": "duplicate_source_symbol"})
            continue
        if row.get("quote") != "USDT" or row.get("instrument_type") != "linear_perpetual":
            excluded.append({"symbol": symbol, "base": base, "reason": "unsupported_instrument"})
            continue
        if _positive_float(row.get("contract_multiplier")) is None:
            excluded.append({"symbol": symbol, "base": base, "reason": "missing_contract_multiplier"})
            continue
        identity = registry.get(base)
        if identity is None:
            excluded.append(
                {
                    "symbol": symbol,
                    "base": base,
                    "reason": registry_exclusions.get(base, "not_in_frozen_non_binance_registry"),
                }
            )
            continue
        listed_from = _as_int(row.get("listed_from_ts"))
        if listed_from is None or listed_from >= window_end_sec:
            excluded.append({"symbol": symbol, "base": base, "reason": "outside_or_missing_lifecycle_start"})
            continue
        listed_to = _as_int(row.get("listed_to_ts"))
        candidates.append(
            {
                "exchange": "gateio",
                "symbol": symbol,
                "base": base,
                "canonical_asset_id": identity["canonical_asset_id"],
                "coin_id": identity["coin_id"],
                "listed_from_ts": listed_from,
                "listed_to_ts": listed_to,
                "active_at_snapshot": row.get("active_at_snapshot") is True,
                "lifecycle_status": str(row.get("lifecycle_status") or "unknown"),
                "contract_multiplier": float(row["contract_multiplier"]),
                "window_overlap_start_sec": max(window_start_sec, listed_from),
                "window_overlap_end_sec": min(window_end_sec, listed_to) if listed_to else window_end_sec,
            }
        )
    candidates.sort(key=lambda row: (row["canonical_asset_id"], row["symbol"]))
    excluded.sort(key=lambda row: (row["reason"], row["symbol"]))
    return candidates, excluded


def _stable_hash_order(rows: list[dict[str, Any]], cohort: str) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: sha256_json(
            {"cohort": cohort, "canonical_asset_id": row["canonical_asset_id"], "symbol": row["symbol"]}
        ),
    )


def select_probe_sample(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    active = [row for row in candidates if row["active_at_snapshot"] is True]
    missing_end = [
        row
        for row in candidates
        if row["active_at_snapshot"] is False
        and row["lifecycle_status"] in {"delisted", "delisting"}
        and row["listed_to_ts"] is None
    ]
    known_end = [
        row
        for row in candidates
        if row["active_at_snapshot"] is False
        and row["lifecycle_status"] in {"delisted", "delisting"}
        and row["listed_to_ts"] is not None
    ]
    missing_end.sort(key=lambda row: (-int(row["listed_from_ts"]), row["canonical_asset_id"]))
    known_end.sort(key=lambda row: (-int(row["listed_to_ts"]), row["canonical_asset_id"]))
    return {
        "active_control": _stable_hash_order(active, "active_control")[:ACTIVE_SAMPLE_SIZE],
        "missing_end_delisted": missing_end[:MISSING_END_SAMPLE_SIZE],
        "known_end_delisted_control": known_end[:KNOWN_END_SAMPLE_SIZE],
    }


def build_probe_tasks(
    sample: Mapping[str, list[dict[str, Any]]],
    *,
    window_start_sec: int,
    window_end_sec: int,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for cohort in sorted(sample):
        for row in sample[cohort]:
            start = max(window_start_sec, int(row["listed_from_ts"]))
            explicit_end = _as_int(row.get("listed_to_ts"))
            end = min(window_end_sec, explicit_end) if explicit_end else window_end_sec
            if end <= start:
                continue
            for year_month in gate_archive.month_keys_for_range(start, end):
                task = {
                    "cohort": cohort,
                    "symbol": row["symbol"],
                    "canonical_asset_id": row["canonical_asset_id"],
                    "year_month": year_month,
                    "archive_type": "candlesticks_1h",
                    "url": gate_archive.build_gate_archive_url(
                        "candlesticks_1h", row["symbol"], year_month
                    ),
                }
                task["task_hash"] = sha256_json(task)
                tasks.append(task)
    return sorted(tasks, key=lambda row: (row["cohort"], row["symbol"], row["year_month"]))


def _plan_contract(
    *,
    run_id: str,
    max_runtime_sec: int,
    closure_manifest_path: Path,
    closure_validation: Mapping[str, Any],
    probe: Mapping[str, Any],
    daily_manifest_path: Path,
    coin_registry_path: Path,
    window_start_sec: int,
    window_end_sec: int,
    candidates: list[dict[str, Any]],
    excluded: list[dict[str, str]],
    sample: Mapping[str, list[dict[str, Any]]],
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    module_path = Path(__file__).resolve()
    closure_module_path = Path(membership_v2_closure.__file__).resolve()
    archive_module_path = Path(gate_archive.__file__).resolve()
    history_plan_module_path = Path(history_plan.__file__).resolve()
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "data_type": "GATE_ARCHIVE_OBSERVED_MEMBERSHIP_SOURCE_V3",
        "stage": "source_availability_probe_planonly",
        "repair_target": "historical_delisted_end_coverage_without_signal_retune",
        "venue_scope": ["gateio"],
        "history_window": {
            "start_sec": window_start_sec,
            "end_sec": window_end_sec,
            "days": HISTORY_DAYS,
        },
        "source_contract": {
            "endpoint_family": "https://download.gatedata.org/futures_usdt/candlesticks_1h",
            "request_method": "HEAD_with_GET_range_fallback_only_on_405",
            "archive_type": "candlesticks_1h",
            "public_api_only": True,
            "full_archive_download": False,
            "archive_payload_read": False,
            "returns_read": False,
            "lifecycle_end_candidate_for_later_quality": "last_valid_closed_hour_plus_one_hour",
            "metadata_end_precedence": ["delisted_time", "delisting_time", "archive_observed_end"],
            "no_interpolation": True,
            "missing_archive_is_not_an_inferred_delisting_date": True,
        },
        "candidate_universe": {
            "minimum_candidates": MIN_CANDIDATES,
            "candidate_count": len(candidates),
            "excluded_count": len(excluded),
            "candidates": candidates,
            "exclusions": excluded,
        },
        "probe_sample": {cohort: list(rows) for cohort, rows in sample.items()},
        "probe_tasks": tasks,
        "probe_task_summary": {
            "tasks": len(tasks),
            "symbols": len({task["symbol"] for task in tasks}),
            "months": sorted({task["year_month"] for task in tasks}),
            "cohort_symbol_counts": {cohort: len(rows) for cohort, rows in sample.items()},
        },
        "quality_gates": {
            "minimum_candidates": MIN_CANDIDATES,
            "minimum_cohort_symbol_availability": MIN_COHORT_SYMBOL_AVAILABILITY,
            "maximum_request_error_rate": MAX_REQUEST_ERROR_RATE,
            "minimum_missing_end_sample_symbols": MISSING_END_SAMPLE_SIZE,
            "future_full_history_minimum_delisted_end_coverage": 0.90,
            "future_full_history_minimum_series_coverage": 0.98,
        },
        "runtime_contract": {
            "max_runtime_sec": max_runtime_sec,
            "absolute_cap_sec": MAX_RUNTIME_SEC,
            "workers": DEFAULT_WORKERS,
            "visible_terminal_required": True,
            "same_plan_hash_cache_reuse_required": True,
            "timeout_verdict": STOPPED_INCOMPLETE_DECISION,
        },
        "input_provenance": {
            "membership_v2_closure_manifest_path": str(closure_manifest_path),
            "membership_v2_closure_manifest_sha256": sha256_file(closure_manifest_path),
            "membership_v2_closure_artifact_hash": closure_validation["closure_artifact_hash"],
            "membership_v2_probe_artifact_hash": probe["artifact_hash"],
            "daily_manifest_path": str(daily_manifest_path),
            "daily_manifest_sha256": sha256_file(daily_manifest_path),
            "coin_registry_path": str(coin_registry_path),
            "coin_registry_sha256": sha256_file(coin_registry_path),
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
            "closure_module_path": str(closure_module_path),
            "closure_module_sha256": sha256_file(closure_module_path),
            "archive_module_path": str(archive_module_path),
            "archive_module_sha256": sha256_file(archive_module_path),
            "history_plan_module_path": str(history_plan_module_path),
            "history_plan_module_sha256": sha256_file(history_plan_module_path),
            "hash_bound_execution_required": True,
        },
        "research_contract": {
            "plan_only": True,
            "network_calls_during_plan": 0,
            "signal_changed": False,
            "thresholds_changed": False,
            "grid_search": False,
            "retune": False,
            "returns_read": False,
            "pnl_read": False,
            "oos_read": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
        "stop_rules": [
            "one_archive_source_probe_only_for_this_plan_hash",
            "probe_reject_closes_membership_momentum_without_history_or_oos",
            "probe_accept_only_allows_a_separate_full_history_planonly",
            "future_delisted_end_coverage_below_0_90_closes_the_branch",
        ],
    }


def build_plan(
    *,
    closure_manifest_path: str | Path,
    daily_manifest_path: str | Path,
    coin_registry_path: str | Path,
    output_path: str | Path | None,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"MaxRuntimeSec must be in [1, {MAX_RUNTIME_SEC}]")
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    closure_path = Path(closure_manifest_path).expanduser().resolve()
    daily_path = Path(daily_manifest_path).expanduser().resolve()
    registry_path = Path(coin_registry_path).expanduser().resolve()
    closure_validation = membership_v2_closure.validate_closure_manifest(closure_path)
    _closure, probe, source_plan = _validate_closure_inputs(closure_path)
    daily = _read_json_object(daily_path)
    source_daily_ref = source_plan.get("input_provenance")
    if not isinstance(source_daily_ref, Mapping):
        raise ValueError("membership-v2 source plan input provenance is missing")
    if str(Path(str(source_daily_ref.get("daily_manifest_path") or "")).resolve()) != str(daily_path):
        raise ValueError("daily manifest path differs from membership-v2 frozen source")
    if sha256_file(daily_path) != source_daily_ref.get("daily_manifest_sha256"):
        raise ValueError("daily manifest hash differs from membership-v2 frozen source")
    window_start, window_end = _history_window(daily)
    registry, registry_exclusions = history_plan.load_unique_coin_registry(registry_path)
    candidates, excluded = select_candidates(
        list(probe.get("rows") or []),
        registry,
        registry_exclusions,
        window_start_sec=window_start,
        window_end_sec=window_end,
    )
    sample = select_probe_sample(candidates)
    tasks = build_probe_tasks(sample, window_start_sec=window_start, window_end_sec=window_end)
    contract = _plan_contract(
        run_id=normalized_run_id,
        max_runtime_sec=runtime,
        closure_manifest_path=closure_path,
        closure_validation=closure_validation,
        probe=probe,
        daily_manifest_path=daily_path,
        coin_registry_path=registry_path,
        window_start_sec=window_start,
        window_end_sec=window_end,
        candidates=candidates,
        excluded=excluded,
        sample=sample,
        tasks=tasks,
    )
    plan_hash = sha256_json(contract)
    cohort_counts = contract["probe_task_summary"]["cohort_symbol_counts"]
    sufficient = (
        len(candidates) >= MIN_CANDIDATES
        and cohort_counts.get("active_control", 0) >= ACTIVE_SAMPLE_SIZE
        and cohort_counts.get("missing_end_delisted", 0) >= MISSING_END_SAMPLE_SIZE
        and cohort_counts.get("known_end_delisted_control", 0) >= KNOWN_END_SAMPLE_SIZE
        and bool(tasks)
    )
    decision = PLAN_DECISION if sufficient else PLAN_INSUFFICIENT_DECISION
    approval_phrase = (
        "Подтверждаю visible Gate archive-membership v3 public probe "
        f"plan_hash={plan_hash}, run_id={normalized_run_id}, MaxRuntimeSec={runtime}, "
        "public archive metadata only, без archive payload/returns/OOS/grid/live/private API keys."
    )
    result: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "decision": decision,
        "final": True,
        "plan_hash": plan_hash,
        "frozen_contract": contract,
        "network_calls_now": False,
        "probe_allowed_now": False,
        "requires_explicit_hash_bound_approval": sufficient,
        "approval_phrase": approval_phrase if sufficient else None,
        "next_allowed_command": "fast-edge-membership-v3-source-probe" if sufficient else "none",
        "blocked_actions": [
            "full_archive_download",
            "history_quality",
            "signal_evaluation",
            "oos",
            "grid_search",
            "retune",
            "execution_probe",
            "paper_forward",
            "live_orders",
            "private_api_keys",
        ],
    }
    if output_path is not None:
        _write_json_immutable(Path(output_path).expanduser().resolve(), result)
    return result


def authorize_probe(plan_path: str | Path, expected_plan_hash: str) -> dict[str, Any]:
    plan = _read_json_object(plan_path)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected membership-v3 PlanOnly artifact")
    if not isinstance(frozen, Mapping):
        raise ValueError("membership-v3 frozen contract is missing")
    computed = sha256_json(frozen)
    mirrored_contract_matches = all(plan.get(key) == value for key, value in frozen.items())
    if (
        plan.get("plan_hash") != computed
        or str(expected_plan_hash or "") != computed
        or not mirrored_contract_matches
    ):
        raise ValueError("membership-v3 plan hash mismatch")
    code = frozen.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("membership-v3 code provenance is missing")
    if code.get("module_sha256") != sha256_file(Path(__file__).resolve()):
        raise ValueError("membership-v3 module hash mismatch")
    if code.get("closure_module_sha256") != sha256_file(Path(membership_v2_closure.__file__).resolve()):
        raise ValueError("membership-v3 closure module hash mismatch")
    if code.get("archive_module_sha256") != sha256_file(Path(gate_archive.__file__).resolve()):
        raise ValueError("membership-v3 archive module hash mismatch")
    if code.get("history_plan_module_sha256") != sha256_file(Path(history_plan.__file__).resolve()):
        raise ValueError("membership-v3 history-plan module hash mismatch")
    if plan.get("next_allowed_command") != "fast-edge-membership-v3-source-probe":
        raise ValueError("membership-v3 public source probe is not the next allowed command")
    return plan


def _session() -> requests.Session:
    session = getattr(_thread_state, "session", None)
    if session is None:
        session = requests.Session()
        session.trust_env = False
        _thread_state.session = session
    return session


def _network_check(task: Mapping[str, Any], timeout_sec: float) -> tuple[int, Mapping[str, str]]:
    session = _session()
    response = session.head(str(task["url"]), allow_redirects=True, timeout=max(1.0, timeout_sec))
    try:
        if response.status_code != 405:
            return int(response.status_code), dict(response.headers)
    finally:
        response.close()
    response = session.get(
        str(task["url"]),
        headers={"Range": "bytes=0-0"},
        stream=True,
        allow_redirects=True,
        timeout=max(1.0, timeout_sec),
    )
    try:
        return int(response.status_code), dict(response.headers)
    finally:
        response.close()


def summarize_probe_results(
    plan: Mapping[str, Any], results: list[Mapping[str, Any]]
) -> dict[str, Any]:
    sample = plan["probe_sample"]
    available_statuses = {200, 206}
    by_cohort_symbol: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in results:
        by_cohort_symbol[(str(row["cohort"]), str(row["symbol"]))].append(row)
    cohorts: dict[str, Any] = {}
    cohort_pass = True
    for cohort, rows in sample.items():
        symbols = [str(row["symbol"]) for row in rows]
        available_symbols = sorted(
            symbol
            for symbol in symbols
            if any(
                int(result.get("http_status") or 0) in available_statuses
                for result in by_cohort_symbol.get((cohort, symbol), [])
            )
        )
        coverage = len(available_symbols) / len(symbols) if symbols else 0.0
        passed = coverage >= MIN_COHORT_SYMBOL_AVAILABILITY
        cohort_pass = cohort_pass and passed
        cohorts[cohort] = {
            "sample_symbols": len(symbols),
            "available_symbols": len(available_symbols),
            "symbol_availability": coverage,
            "passed": passed,
            "available_symbol_list": available_symbols,
        }
    errors = sum(str(row.get("status")) == "error" for row in results)
    error_rate = errors / len(results) if results else 1.0
    accepted = (
        int(plan["candidate_universe"]["candidate_count"]) >= MIN_CANDIDATES
        and cohort_pass
        and error_rate <= MAX_REQUEST_ERROR_RATE
        and len(results) == len(plan["probe_tasks"])
    )
    return {
        "accepted": accepted,
        "decision": ACCEPTED_PROBE_DECISION if accepted else REJECTED_PROBE_DECISION,
        "tasks_expected": len(plan["probe_tasks"]),
        "tasks_completed": len(results),
        "http_200_or_206": sum(int(row.get("http_status") or 0) in available_statuses for row in results),
        "http_404": sum(int(row.get("http_status") or 0) == 404 for row in results),
        "errors": errors,
        "request_error_rate": error_rate,
        "cohorts": cohorts,
        "quality_gates": dict(plan["quality_gates"]),
        "limitations": [
            "This probe proves only archive-object availability, not row coverage or lifecycle timestamps.",
            "A pass permits only a separate full-history PlanOnly and cannot authorize signal evaluation or OOS.",
        ],
    }


def _probe_payload_for_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
    }


def run_probe(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path,
    max_runtime_sec: int,
    timeout_sec: int = 10,
    workers: int = DEFAULT_WORKERS,
    fetch_override: FetchOverride | None = None,
) -> dict[str, Any]:
    plan = authorize_probe(plan_path, expected_plan_hash)
    runtime = int(max_runtime_sec)
    planned_runtime = int(plan["runtime_contract"]["max_runtime_sec"])
    if runtime < 1 or runtime > MAX_RUNTIME_SEC or runtime > planned_runtime:
        raise ValueError(f"MaxRuntimeSec must be in [1, {planned_runtime}]")
    worker_count = int(workers)
    if worker_count < 1 or worker_count > int(plan["runtime_contract"]["workers"]):
        raise ValueError("workers exceed the frozen membership-v3 contract")
    resolved_output = Path(output_path).expanduser().resolve()
    if resolved_output.is_file():
        cached = _read_json_object(resolved_output)
        if (
            cached.get("schema") == PROBE_SCHEMA
            and cached.get("plan_hash") == plan["plan_hash"]
            and cached.get("final") is True
            and cached.get("artifact_hash") == sha256_json(_probe_payload_for_hash(cached))
        ):
            cached["cache_reused"] = True
            return cached
    started = time.monotonic()
    deadline = started + runtime
    results: list[dict[str, Any]] = []
    try:
        def check(task: Mapping[str, Any]) -> dict[str, Any]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("membership-v3 public source probe runtime exhausted")
            try:
                if fetch_override is None:
                    status, headers = _network_check(task, min(float(timeout_sec), remaining))
                else:
                    status, headers = fetch_override(task, min(float(timeout_sec), remaining))
                return {
                    **dict(task),
                    "status": "available" if int(status) in {200, 206} else "missing" if int(status) == 404 else "http_error",
                    "http_status": int(status),
                    "content_length": str(headers.get("Content-Length") or headers.get("content-length") or ""),
                }
            except Exception as exc:  # noqa: BLE001 - errors are quality evidence.
                return {**dict(task), "status": "error", "http_status": None, "error": f"{type(exc).__name__}: {exc}"}

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="gate-membership-v3") as executor:
            futures = [executor.submit(check, task) for task in plan["probe_tasks"]]
            for future in as_completed(futures, timeout=max(1.0, deadline - time.monotonic())):
                results.append(future.result())
        if time.monotonic() > deadline:
            raise TimeoutError("membership-v3 public source probe runtime exhausted")
        results.sort(key=lambda row: (row["cohort"], row["symbol"], row["year_month"]))
        quality = summarize_probe_results(plan, results)
        report: dict[str, Any] = {
            "schema": PROBE_SCHEMA,
            "generated_at_utc": _utc_now(),
            "run_id": plan["run_id"],
            "plan_path": str(Path(plan_path).expanduser().resolve()),
            "plan_hash": plan["plan_hash"],
            "final": True,
            "decision": quality["decision"],
            "accepted": quality["accepted"],
            "cache_reused": False,
            "runtime_sec": time.monotonic() - started,
            "quality": quality,
            "results": results,
            "data_access_audit": {
                "archive_payload_read": False,
                "returns_read": False,
                "signals_read": False,
                "pnl_read": False,
                "oos_read": False,
            },
            "next_allowed_command": (
                "fast-edge-membership-v3-history-plan"
                if quality["accepted"]
                else "none_membership_v3_archive_source_rejected"
            ),
            "blocked_actions": [
                "history_collect_without_new_hash_bound_plan",
                "signal_evaluation",
                "oos",
                "grid_search",
                "retune",
                "execution_probe",
                "paper_forward",
                "live_orders",
                "private_api_keys",
            ],
        }
    except Exception as exc:  # noqa: BLE001 - persist resumable bounded failure.
        report = {
            "schema": PROBE_SCHEMA,
            "generated_at_utc": _utc_now(),
            "run_id": plan["run_id"],
            "plan_path": str(Path(plan_path).expanduser().resolve()),
            "plan_hash": plan["plan_hash"],
            "final": False,
            "decision": STOPPED_INCOMPLETE_DECISION,
            "accepted": False,
            "cache_reused": False,
            "runtime_sec": time.monotonic() - started,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "partial_results": sorted(
                results, key=lambda row: (row["cohort"], row["symbol"], row["year_month"])
            ),
            "data_access_audit": {
                "archive_payload_read": False,
                "returns_read": False,
                "signals_read": False,
                "pnl_read": False,
                "oos_read": False,
            },
            "next_allowed_command": "fast-edge-membership-v3-source-probe",
        }
    report["artifact_hash"] = sha256_json(_probe_payload_for_hash(report))
    _atomic_write_json(resolved_output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate archive-observed membership source v3 PlanOnly/probe")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--closure-manifest", required=True)
    plan.add_argument("--daily-manifest", required=True)
    plan.add_argument("--coin-registry", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--plan", required=True)
    probe.add_argument("--expected-plan-hash", required=True)
    probe.add_argument("--output", required=True)
    probe.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    probe.add_argument("--timeout-sec", type=int, default=10)
    probe.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()
    if args.command == "plan":
        result = build_plan(
            closure_manifest_path=args.closure_manifest,
            daily_manifest_path=args.daily_manifest,
            coin_registry_path=args.coin_registry,
            output_path=args.output,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = run_probe(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
            max_runtime_sec=args.max_runtime_sec,
            timeout_sec=args.timeout_sec,
            workers=args.workers,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
