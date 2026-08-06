from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import gate_historical_archive as gate_archive
import gate_historical_membership_history_collector as archive_io
import gate_historical_membership_v3 as membership_v3


SCHEMA = "trading_mvp_gate_historical_membership_archive_history_plan_v3"
HISTORY_PLAN_DECISION = (
    "GATE_MEMBERSHIP_V3_HISTORY_PLAN_READY_AWAITING_EXPLICIT_VISIBLE_COLLECT_APPROVAL"
)
INSUFFICIENT_UNIVERSE_DECISION = "GATE_MEMBERSHIP_V3_HISTORY_PLAN_INSUFFICIENT_UNIVERSE"
MAX_RUNTIME_SEC = 7200
MINIMUM_CANONICAL_ASSETS = 20
ARCHIVE_TYPES = ("candlesticks_1h", "funding_applies")
DAY_SEC = 86_400
WARMUP_DAYS = 20
TRAIN_DAYS = 100
OOS_DAYS = 100
OOS_FOLDS = 5
OOS_FOLD_DAYS = 20
HISTORY_DAYS = WARMUP_DAYS + TRAIN_DAYS + OOS_DAYS


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
            raise FileExistsError(f"refusing to overwrite immutable history PlanOnly: {path}")
        return
    _atomic_write_json(path, payload)


def _probe_payload_for_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
    }


def validate_source_probe(
    source_probe_report_path: str | Path,
    *,
    expected_source_plan_hash: str,
    expected_source_artifact_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    report_path = Path(source_probe_report_path).expanduser().resolve()
    report = _read_json_object(report_path)
    if report.get("schema") != membership_v3.PROBE_SCHEMA:
        raise ValueError("unexpected membership-v3 source probe schema")
    if str(report.get("plan_hash") or "") != str(expected_source_plan_hash):
        raise ValueError("source probe plan hash mismatch")
    stored_hash = str(report.get("artifact_hash") or "")
    computed_hash = sha256_json(_probe_payload_for_hash(report))
    if stored_hash != computed_hash or stored_hash != str(expected_source_artifact_hash):
        raise ValueError("source probe artifact hash mismatch")
    if (
        report.get("final") is not True
        or report.get("accepted") is not True
        or report.get("decision") != membership_v3.ACCEPTED_PROBE_DECISION
        or report.get("next_allowed_command") != "fast-edge-membership-v3-history-plan"
    ):
        raise ValueError("source probe is not accepted and final")
    quality = report.get("quality")
    if not isinstance(quality, Mapping) or quality.get("accepted") is not True:
        raise ValueError("source probe quality payload is not accepted")
    audit = report.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(
        audit.get(key) is not False
        for key in ("archive_payload_read", "returns_read", "signals_read", "pnl_read", "oos_read")
    ):
        raise ValueError("source probe data-access audit is unsafe")
    source_plan_path = Path(str(report.get("plan_path") or "")).expanduser().resolve()
    source_plan = membership_v3.authorize_probe(source_plan_path, expected_source_plan_hash)
    if report.get("run_id") != source_plan.get("run_id"):
        raise ValueError("source probe run_id differs from the frozen source plan")
    source_tasks = source_plan.get("probe_tasks")
    if not isinstance(source_tasks, list) or not source_tasks:
        raise ValueError("source probe frozen task list is empty")
    expected_tasks = int(quality.get("tasks_expected") or 0)
    completed_tasks = int(quality.get("tasks_completed") or 0)
    if expected_tasks != len(source_tasks) or completed_tasks != expected_tasks:
        raise ValueError("source probe task coverage is incomplete")
    cohorts = quality.get("cohorts")
    if not isinstance(cohorts, Mapping) or not cohorts or any(
        not isinstance(value, Mapping) or value.get("passed") is not True
        for value in cohorts.values()
    ):
        raise ValueError("source probe cohort quality is incomplete")
    return source_plan, report, report_path


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def select_history_universe(
    source_plan: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    window = source_plan.get("history_window")
    universe = source_plan.get("candidate_universe")
    if not isinstance(window, Mapping) or not isinstance(universe, Mapping):
        raise ValueError("membership-v3 source universe or history window is missing")
    start = int(window["start_sec"])
    end = int(window["end_sec"])
    if start < 0 or end <= start:
        raise ValueError("invalid membership-v3 history window")
    candidates = universe.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("membership-v3 source candidates are missing")
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    seen_symbols: set[str] = set()
    seen_assets: set[str] = set()
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()
        base = str(raw.get("base") or "").strip().upper()
        canonical_id = str(raw.get("canonical_asset_id") or "").strip()
        if not symbol or not base or not canonical_id:
            excluded.append({"symbol": symbol, "base": base, "reason": "missing_identity"})
            continue
        if symbol in seen_symbols or canonical_id in seen_assets:
            excluded.append({"symbol": symbol, "base": base, "reason": "duplicate_identity"})
            continue
        seen_symbols.add(symbol)
        seen_assets.add(canonical_id)
        multiplier = _positive_float(raw.get("contract_multiplier"))
        listed_from = _as_int(raw.get("listed_from_ts"))
        listed_to = _as_int(raw.get("listed_to_ts"))
        if multiplier is None or listed_from is None:
            excluded.append({"symbol": symbol, "base": base, "reason": "invalid_contract_metadata"})
            continue
        acquisition_start = max(start, listed_from)
        acquisition_end = min(end, listed_to) if listed_to is not None else end
        if acquisition_end <= acquisition_start:
            excluded.append({"symbol": symbol, "base": base, "reason": "empty_history_overlap"})
            continue
        active = raw.get("active_at_snapshot") is True
        status = str(raw.get("lifecycle_status") or "unknown")
        if listed_to is not None:
            end_resolution = "contract_metadata"
            resolved_end = acquisition_end
        elif active and status not in {"delisted", "delisting"}:
            end_resolution = "open_at_frozen_snapshot"
            resolved_end = None
        elif not active and status in {"delisted", "delisting"}:
            end_resolution = "archive_observed_pending"
            resolved_end = None
        else:
            excluded.append(
                {"symbol": symbol, "base": base, "reason": "unresolved_lifecycle_status"}
            )
            continue
        eligible.append(
            {
                "exchange": "gateio",
                "symbol": symbol,
                "base": base,
                "quote": "USDT",
                "canonical_asset_id": canonical_id,
                "coin_id": str(raw.get("coin_id") or ""),
                "listed_from_ts": listed_from,
                "listed_to_ts": listed_to,
                "active_at_snapshot": active,
                "lifecycle_status": status,
                "contract_multiplier": multiplier,
                "acquisition_start_sec": acquisition_start,
                "acquisition_end_sec": acquisition_end,
                "lifecycle_end_resolution": end_resolution,
                "resolved_lifecycle_end_sec": resolved_end,
                "funding_interval_resolution": "archive_observed_pending",
                "non_binance_evidence": "frozen_v3_current_registry_reference_only",
            }
        )
    eligible.sort(key=lambda row: (row["canonical_asset_id"], row["symbol"]))
    excluded.sort(key=lambda row: (row["reason"], row["symbol"]))
    return eligible, excluded


def build_archive_tasks(universe: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for asset in universe:
        for year_month in gate_archive.month_keys_for_range(
            int(asset["acquisition_start_sec"]), int(asset["acquisition_end_sec"])
        ):
            for archive_type in ARCHIVE_TYPES:
                identity = {
                    "exchange": "gateio",
                    "symbol": asset["symbol"],
                    "archive_type": archive_type,
                    "year_month": year_month,
                }
                tasks.append(
                    {
                        **identity,
                        "canonical_asset_id": asset["canonical_asset_id"],
                        "url": gate_archive.build_gate_archive_url(
                            archive_type, str(asset["symbol"]), year_month
                        ),
                        "cache_key": sha256_json(identity),
                    }
                )
    return sorted(tasks, key=lambda row: (row["symbol"], row["year_month"], row["archive_type"]))


def _split_contract(start_sec: int, end_sec: int) -> dict[str, Any]:
    start = int(start_sec)
    end = int(end_sec)
    if end - start != HISTORY_DAYS * DAY_SEC:
        raise ValueError("membership-v3 history window does not match the frozen 220-day split")
    warmup_end = start + WARMUP_DAYS * DAY_SEC
    train_end = warmup_end + TRAIN_DAYS * DAY_SEC
    if train_end + OOS_DAYS * DAY_SEC != end:
        raise ValueError("membership-v3 history split does not cover the history window")
    return {
        "warmup": {"start_sec": start, "end_sec": warmup_end, "days": WARMUP_DAYS},
        "train": {"start_sec": warmup_end, "end_sec": train_end, "days": TRAIN_DAYS},
        "oos": {
            "start_sec": train_end,
            "end_sec": end,
            "days": OOS_DAYS,
            "folds": OOS_FOLDS,
            "fold_days": OOS_FOLD_DAYS,
        },
    }


def history_plan_payload_for_hash(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {"generated_at_utc", "plan_hash", "approval_phrase"}
    }


def build_history_plan(
    *,
    source_probe_report_path: str | Path,
    expected_source_plan_hash: str,
    expected_source_artifact_hash: str,
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
    source_plan, source_report, report_path = validate_source_probe(
        source_probe_report_path,
        expected_source_plan_hash=expected_source_plan_hash,
        expected_source_artifact_hash=expected_source_artifact_hash,
    )
    eligible, excluded = select_history_universe(source_plan)
    tasks = build_archive_tasks(eligible)
    ready = len(eligible) >= MINIMUM_CANONICAL_ASSETS and bool(tasks)
    decision = HISTORY_PLAN_DECISION if ready else INSUFFICIENT_UNIVERSE_DECISION
    next_command = "fast-edge-membership-v3-history-collect" if ready else "none"
    module_path = Path(__file__).resolve()
    collector_path = module_path.with_name("gate_historical_membership_v3_history_collector.py")
    quality_path = module_path.with_name("gate_historical_membership_v3_history_quality.py")
    archive_io_path = Path(archive_io.__file__).resolve()
    if not collector_path.is_file() or not quality_path.is_file():
        raise ValueError("membership-v3 history collector and quality modules must exist before freezing")
    window = source_plan["history_window"]
    split_contract = _split_contract(int(window["start_sec"]), int(window["end_sec"]))
    contract: dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": normalized_run_id,
        "data_type": "GATE_ARCHIVE_MEMBERSHIP_HISTORY_V3",
        "stage": "full_history_acquisition_planonly",
        "decision": decision,
        "network_calls_now": False,
        "collect_allowed_now": False,
        "public_data_only": True,
        "history_window": dict(window),
        "split_contract": split_contract,
        "source_contract": {
            "exchange": "gateio",
            "archive_base_url": gate_archive.ARCHIVE_BASE_URL,
            "archive_types": list(ARCHIVE_TYPES),
            "full_archive_payload_required_later": True,
            "no_interpolation": True,
            "missing_archive_policy": "record_missing_never_infer_exact_delisting",
            "archive_observed_end_rule": "last_valid_closed_hour_plus_one_hour",
            "metadata_end_precedence": [
                "delisted_time",
                "delisting_time",
                "archive_observed_end",
            ],
        },
        "universe": {
            "minimum_canonical_assets": MINIMUM_CANONICAL_ASSETS,
            "eligible_count": len(eligible),
            "excluded_count": len(excluded),
            "eligible": eligible,
            "excluded": excluded,
        },
        "archive_tasks": tasks,
        "archive_task_summary": {
            "tasks": len(tasks),
            "symbols": len({task["symbol"] for task in tasks}),
            "months": sorted({task["year_month"] for task in tasks}),
            "types": list(ARCHIVE_TYPES),
        },
        "runtime_contract": {
            "max_runtime_sec": runtime,
            "absolute_cap_sec": MAX_RUNTIME_SEC,
            "visible_terminal_required": True,
            "single_market_data_writer": True,
            "same_plan_hash_cache_reuse_required": True,
            "timeout_verdict": "STOPPED_INCOMPLETE",
        },
        "future_quality_gates": {
            "minimum_canonical_assets": MINIMUM_CANONICAL_ASSETS,
            "minimum_series_coverage": 0.98,
            "minimum_delisted_end_coverage": 0.90,
            "minimum_funding_interval_confidence": 0.80,
            "no_interpolation": True,
            "no_duplicate_timestamps": True,
            "point_in_time_membership_required": True,
            "returns_forbidden_until_separate_train_planonly": True,
        },
        "input_provenance": {
            "source_probe_report_path": str(report_path),
            "source_probe_report_sha256": sha256_file(report_path),
            "source_probe_artifact_hash": expected_source_artifact_hash,
            "source_plan_path": str(Path(str(source_report["plan_path"])).resolve()),
            "source_plan_sha256": sha256_file(Path(str(source_report["plan_path"])).resolve()),
            "source_plan_hash": expected_source_plan_hash,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
            "source_module_path": str(Path(membership_v3.__file__).resolve()),
            "source_module_sha256": sha256_file(Path(membership_v3.__file__).resolve()),
            "archive_module_path": str(Path(gate_archive.__file__).resolve()),
            "archive_module_sha256": sha256_file(Path(gate_archive.__file__).resolve()),
            "collector_module_path": str(collector_path),
            "collector_module_sha256": sha256_file(collector_path),
            "quality_module_path": str(quality_path),
            "quality_module_sha256": sha256_file(quality_path),
            "archive_io_module_path": str(archive_io_path),
            "archive_io_module_sha256": sha256_file(archive_io_path),
        },
        "data_access_audit": {
            "archive_payload_read": False,
            "prices_read": False,
            "returns_read": False,
            "signals_read": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "next_allowed_command": next_command,
        "blocked_actions": [
            "history_collect_without_exact_hash_bound_approval",
            "history_quality_without_separate_hash_bound_plan",
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
    contract["input_merkle_sha256"] = sha256_json(
        {
            "source_probe_artifact_hash": expected_source_artifact_hash,
            "source_plan_hash": expected_source_plan_hash,
            "source_probe_report_sha256": contract["input_provenance"]["source_probe_report_sha256"],
            "source_plan_sha256": contract["input_provenance"]["source_plan_sha256"],
            "module_sha256": contract["code_provenance"]["module_sha256"],
            "collector_module_sha256": contract["code_provenance"]["collector_module_sha256"],
            "quality_module_sha256": contract["code_provenance"]["quality_module_sha256"],
            "archive_io_module_sha256": contract["code_provenance"]["archive_io_module_sha256"],
        }
    )
    plan_hash = sha256_json(contract)
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "plan_hash": plan_hash,
        "frozen_contract": contract,
    }
    if ready:
        payload["approval_phrase"] = (
            "Подтверждаю visible Gate membership-v3 full-history collect "
            f"plan_hash={plan_hash}, run_id={normalized_run_id}, MaxRuntimeSec={runtime}, "
            "public archive payload only, без returns/OOS/grid/live/private API keys."
        )
    if output_path is not None:
        _write_json_immutable(Path(output_path).expanduser().resolve(), payload)
    return payload


def authorize_history_collect(
    plan_path: str | Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    plan = _read_json_object(plan_path)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != SCHEMA or plan.get("decision") != HISTORY_PLAN_DECISION:
        raise ValueError("unexpected membership-v3 history PlanOnly artifact")
    if not isinstance(frozen, Mapping):
        raise ValueError("membership-v3 history frozen contract is missing")
    computed = sha256_json(frozen)
    mirrored = all(plan.get(key) == value for key, value in frozen.items())
    if plan.get("plan_hash") != computed or str(expected_plan_hash) != computed or not mirrored:
        raise ValueError("history plan hash mismatch")
    if plan.get("next_allowed_command") != "fast-edge-membership-v3-history-collect":
        raise ValueError("history collect is not the next allowed command")
    code = frozen.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("history plan code provenance is missing")
    for path_key, hash_key, expected in (
        ("module_path", "module_sha256", Path(__file__).resolve()),
        ("source_module_path", "source_module_sha256", Path(membership_v3.__file__).resolve()),
        ("archive_module_path", "archive_module_sha256", Path(gate_archive.__file__).resolve()),
        (
            "collector_module_path",
            "collector_module_sha256",
            Path(__file__).resolve().with_name("gate_historical_membership_v3_history_collector.py"),
        ),
        (
            "quality_module_path",
            "quality_module_sha256",
            Path(__file__).resolve().with_name("gate_historical_membership_v3_history_quality.py"),
        ),
        (
            "archive_io_module_path",
            "archive_io_module_sha256",
            Path(archive_io.__file__).resolve(),
        ),
    ):
        actual = Path(str(code.get(path_key) or "")).expanduser().resolve()
        if actual != expected or not actual.is_file() or code.get(hash_key) != sha256_file(actual):
            raise ValueError(f"history pipeline module hash mismatch: {expected.name}")
    tasks = plan.get("archive_tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("history archive tasks are missing")
    cache_keys: set[str] = set()
    for raw in tasks:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid history archive task")
        identity = {
            "exchange": "gateio",
            "symbol": str(raw.get("symbol") or ""),
            "archive_type": str(raw.get("archive_type") or ""),
            "year_month": str(raw.get("year_month") or ""),
        }
        expected_url = gate_archive.build_gate_archive_url(
            identity["archive_type"], identity["symbol"], identity["year_month"]
        )
        cache_key = str(raw.get("cache_key") or "")
        if raw.get("url") != expected_url or cache_key != sha256_json(identity) or cache_key in cache_keys:
            raise ValueError("history archive task is tampered or duplicated")
        cache_keys.add(cache_key)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate membership-v3 full-history PlanOnly")
    parser.add_argument("--source-probe-report", required=True)
    parser.add_argument("--expected-source-plan-hash", required=True)
    parser.add_argument("--expected-source-artifact-hash", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    args = parser.parse_args()
    result = build_history_plan(
        source_probe_report_path=args.source_probe_report,
        expected_source_plan_hash=args.expected_source_plan_hash,
        expected_source_artifact_hash=args.expected_source_artifact_hash,
        output_path=args.output,
        run_id=args.run_id,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
