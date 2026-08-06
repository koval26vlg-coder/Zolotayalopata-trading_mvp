from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

import gate_historical_membership_v1 as lifecycle_v1


SCHEMA = "trading_mvp_gate_historical_membership_plan_v2"
PROBE_SCHEMA = "trading_mvp_gate_historical_membership_probe_v2"
PLAN_DECISION = "GATE_HISTORICAL_MEMBERSHIP_V2_PLAN_READY_AWAITING_EXPLICIT_PUBLIC_PROBE_APPROVAL"
ACCEPTED_PROBE_DECISION = "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_ACCEPTED_READY_FOR_BACKFILL_PLANONLY"
REJECTED_PROBE_DECISION = "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED"
STOPPED_INCOMPLETE_DECISION = "GATE_HISTORICAL_MEMBERSHIP_V2_PROBE_STOPPED_INCOMPLETE"
MAX_RUNTIME_SEC = 600
MIN_MULTIPLIER_COVERAGE = 0.98
MIN_DELISTED_MULTIPLIER_COVERAGE = 0.90


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
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
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


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _positive_int(value: Any) -> int | None:
    number = _positive_float(value)
    return int(number) if number is not None else None


def _validate_daily_manifest(path: Path) -> dict[str, Any]:
    payload = _read_json_object(path)
    if payload.get("schema") != "daily_collect_v1":
        raise ValueError("daily manifest schema must be daily_collect_v1")
    params = payload.get("params")
    if not isinstance(params, Mapping):
        raise ValueError("daily manifest params are missing")
    exchanges = {str(value).strip().lower() for value in params.get("exchanges") or []}
    if "gateio" not in exchanges and "gate" not in exchanges:
        raise ValueError("daily manifest must include Gate")
    return payload


def _plan_contract(
    *,
    daily_manifest_path: Path,
    daily_manifest_sha256: str,
    daily_run_id: str,
    run_id: str,
    max_runtime_sec: int,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "data_type": "GATE_FUTURES_HISTORICAL_MEMBERSHIP_V2",
        "stage": "source_availability_and_contract_economics_probe",
        "repair_target": "cross_sectional_momentum_daily_lookback30_survivorship_and_volume_repair",
        "venue_scope": ["gateio"],
        "source_contract": {
            "gate_contracts_all_endpoint": lifecycle_v1.GATE_CONTRACTS_ALL_ENDPOINT,
            "gate_archive_base_url": lifecycle_v1.GATE_ARCHIVE_BASE_URL,
            "settle": "usdt",
            "public_api_only": True,
            "pagination": {
                "limit": lifecycle_v1.DEFAULT_PAGE_LIMIT,
                "max_pages": lifecycle_v1.DEFAULT_MAX_PAGES,
                "stop_on_short_page": True,
                "duplicate_page_is_error": True,
            },
            "required_contract_fields": [
                "name",
                "type",
                "status",
                "create_time_or_launch_time",
                "in_delisting",
                "delisting_time",
                "delisted_time",
                "quanto_multiplier",
                "funding_interval",
                "order_size_min",
                "order_size_max",
            ],
            "required_archive_series_for_later_backfill": [
                "futures_usdt/candlesticks_1h",
                "futures_usdt/funding_applies",
            ],
            "quote_volume_formula": "volume_contracts * close_price * contract_multiplier",
        },
        "input_provenance": {
            "daily_manifest_path": str(daily_manifest_path),
            "daily_manifest_sha256": daily_manifest_sha256,
            "daily_run_id": daily_run_id,
            "known_bias": "current_top_volume_universe_survivorship",
            "returns_files_are_not_inputs": True,
        },
        "code_provenance": {
            "module": "gate_historical_membership_v2.py",
            "module_sha256": sha256_file(Path(__file__).resolve()),
            "lifecycle_helper": str(Path(lifecycle_v1.__file__).resolve()),
            "lifecycle_helper_sha256": sha256_file(Path(lifecycle_v1.__file__).resolve()),
            "hash_bound_execution_required": True,
        },
        "quality_gates": {
            "minimum_contracts": lifecycle_v1.MIN_CONTRACTS,
            "minimum_delisted_contracts": lifecycle_v1.MIN_DELISTED_CONTRACTS,
            "minimum_lifecycle_start_coverage": lifecycle_v1.MIN_LIFECYCLE_START_COVERAGE,
            "minimum_delisted_end_coverage": lifecycle_v1.MIN_DELISTED_END_COVERAGE,
            "minimum_multiplier_coverage": MIN_MULTIPLIER_COVERAGE,
            "minimum_delisted_multiplier_coverage": MIN_DELISTED_MULTIPLIER_COVERAGE,
            "duplicate_symbols_allowed": 0,
            "invalid_lifecycle_intervals_allowed": 0,
        },
        "runtime_contract": {
            "max_runtime_sec": max_runtime_sec,
            "visible_terminal_required": True,
            "cache_ttl_sec": 86_400,
            "same_plan_hash_cache_reuse_required": True,
        },
        "research_contract": {
            "plan_only": True,
            "network_calls_during_plan": 0,
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_read": False,
            "grid_search": False,
            "retune": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
        "scope_limitations": {
            "mexc_historical_membership_resolved": False,
            "gate_only_retest_is_weaker_evidence": True,
            "historical_binance_membership_resolved": False,
            "archive_availability_requires_separate_hash_bound_collect": True,
        },
    }


def build_plan(
    *,
    daily_manifest_path: str | Path,
    output_path: str | Path | None,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    manifest_path = Path(daily_manifest_path).expanduser().resolve()
    manifest = _validate_daily_manifest(manifest_path)
    contract = _plan_contract(
        daily_manifest_path=manifest_path,
        daily_manifest_sha256=sha256_file(manifest_path),
        daily_run_id=str(manifest.get("run_id") or ""),
        run_id=normalized_run_id,
        max_runtime_sec=runtime,
    )
    plan_hash = sha256_json(contract)
    result: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "decision": PLAN_DECISION,
        "final": True,
        "plan_hash": plan_hash,
        "frozen_contract": contract,
        "network_calls_now": False,
        "collect_allowed_now": False,
        "probe_allowed_now": False,
        "requires_explicit_hash_bound_approval": True,
        "approval_phrase": (
            "Подтверждаю visible Gate historical-membership v2 public probe "
            f"plan_hash={plan_hash}, run_id={normalized_run_id}, MaxRuntimeSec={runtime}, "
            "public API only, без returns/OOS/grid/live/private API keys."
        ),
        "next_allowed_command": "fast-edge-membership-v2-probe",
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_read": False,
            "oos_metrics_read": False,
        },
        "blocked_actions": [
            "history_collect_before_v2_probe_accept",
            "momentum_retest_before_survivorship_and_volume_repair",
            "grid_search",
            "retune",
            "oos_read",
            "execution_probe",
            "paper_forward",
            "live_orders",
            "private_api_keys",
        ],
    }
    if output_path is not None:
        _atomic_write_json(Path(output_path).expanduser().resolve(), result)
    return result


def authorize_probe(plan_path: str | Path, expected_plan_hash: str) -> dict[str, Any]:
    plan = _read_json_object(plan_path)
    if plan.get("schema") != SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected membership v2 PlanOnly artifact")
    contract = plan.get("frozen_contract")
    if not isinstance(contract, Mapping):
        raise ValueError("frozen_contract is missing")
    computed_hash = sha256_json(contract)
    mirrored_contract_matches = all(plan.get(key) == value for key, value in contract.items())
    if (
        str(plan.get("plan_hash") or "") != computed_hash
        or str(expected_plan_hash or "") != computed_hash
        or not mirrored_contract_matches
    ):
        raise ValueError("plan hash mismatch")
    code = contract.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("code_provenance is missing")
    if str(code.get("module_sha256") or "") != sha256_file(Path(__file__).resolve()):
        raise ValueError("membership v2 module hash mismatch")
    if str(code.get("lifecycle_helper_sha256") or "") != sha256_file(Path(lifecycle_v1.__file__).resolve()):
        raise ValueError("membership lifecycle helper hash mismatch")
    if plan.get("next_allowed_command") != "fast-edge-membership-v2-probe":
        raise ValueError("membership v2 probe is not the next allowed command")
    return plan


def parse_contracts_all(payload: Any, *, snapshot_ts: int) -> list[dict[str, Any]]:
    lifecycle_rows = lifecycle_v1.parse_contracts_all(payload, snapshot_ts=snapshot_ts)
    raw_by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    if isinstance(payload, list):
        for raw in payload:
            if not isinstance(raw, Mapping):
                continue
            symbol = str(raw.get("name") or "").strip().upper()
            raw_by_symbol.setdefault(symbol, []).append(raw)
    rows: list[dict[str, Any]] = []
    for lifecycle in lifecycle_rows:
        candidates = raw_by_symbol.get(str(lifecycle["symbol"]), [])
        raw = candidates[0] if len(candidates) == 1 else {}
        rows.append(
            {
                **lifecycle,
                "contract_multiplier": _positive_float(raw.get("quanto_multiplier")),
                "funding_interval_sec": _positive_int(raw.get("funding_interval")),
                "order_size_min_contracts": _positive_float(raw.get("order_size_min")),
                "order_size_max_contracts": _positive_float(raw.get("order_size_max")),
                "quote_volume_formula": "volume_contracts * close_price * contract_multiplier",
            }
        )
    return rows


def summarize_membership_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lifecycle = lifecycle_v1.summarize_membership_rows(rows)
    delisted = [
        row
        for row in rows
        if row.get("active_at_snapshot") is False
        and str(row.get("lifecycle_status") or "") in {"delisted", "delisting"}
    ]
    multiplier_rows = [row for row in rows if _positive_float(row.get("contract_multiplier")) is not None]
    delisted_multiplier_rows = [
        row for row in delisted if _positive_float(row.get("contract_multiplier")) is not None
    ]
    multiplier_coverage = len(multiplier_rows) / len(rows) if rows else 0.0
    delisted_coverage = len(delisted_multiplier_rows) / len(delisted) if delisted else 0.0
    missing = sorted(
        str(row.get("symbol") or "")
        for row in rows
        if _positive_float(row.get("contract_multiplier")) is None
    )
    accepted = (
        bool(lifecycle["accepted"])
        and multiplier_coverage >= MIN_MULTIPLIER_COVERAGE
        and delisted_coverage >= MIN_DELISTED_MULTIPLIER_COVERAGE
    )
    return {
        **lifecycle,
        "accepted": accepted,
        "decision": ACCEPTED_PROBE_DECISION if accepted else REJECTED_PROBE_DECISION,
        "multiplier_coverage": multiplier_coverage,
        "delisted_multiplier_coverage": delisted_coverage,
        "missing_contract_multiplier": missing,
        "quality_gates": {
            **dict(lifecycle["quality_gates"]),
            "minimum_multiplier_coverage": MIN_MULTIPLIER_COVERAGE,
            "minimum_delisted_multiplier_coverage": MIN_DELISTED_MULTIPLIER_COVERAGE,
        },
    }


def _probe_payload_for_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
    }


def run_probe(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path,
    max_runtime_sec: int,
    timeout_sec: int = 15,
    fetch_page_override: Callable[[int, int], Any] | None = None,
) -> dict[str, Any]:
    plan = authorize_probe(plan_path, expected_plan_hash)
    runtime = int(max_runtime_sec)
    planned_runtime = int(plan["runtime_contract"]["max_runtime_sec"])
    if runtime < 1 or runtime > MAX_RUNTIME_SEC or runtime > planned_runtime:
        raise ValueError(f"max_runtime_sec must be in [1, {planned_runtime}]")
    resolved_output = Path(output_path).expanduser().resolve()
    if resolved_output.is_file():
        cached = _read_json_object(resolved_output)
        if (
            cached.get("schema") == PROBE_SCHEMA
            and cached.get("plan_hash") == plan["plan_hash"]
            and cached.get("final") is True
        ):
            cached["cache_reused"] = True
            return cached

    started = time.monotonic()
    deadline = started + runtime
    try:
        if fetch_page_override is None:
            session = requests.Session()
            session.trust_env = False

            def fetch_page(limit: int, offset: int) -> Any:
                response = session.get(
                    lifecycle_v1.GATE_CONTRACTS_ALL_ENDPOINT,
                    params={"limit": limit, "offset": offset},
                    timeout=min(timeout_sec, max(1.0, deadline - time.monotonic())),
                )
                response.raise_for_status()
                return response.json()
        else:
            session = None
            fetch_page = fetch_page_override

        try:
            pagination = plan["source_contract"]["pagination"]
            raw_rows, request_summary = lifecycle_v1.fetch_contracts_all(
                fetch_page,
                page_limit=int(pagination["limit"]),
                max_pages=int(pagination["max_pages"]),
                deadline_monotonic=deadline,
            )
        finally:
            if session is not None:
                session.close()
        rows = parse_contracts_all(raw_rows, snapshot_ts=int(time.time()))
        quality = summarize_membership_rows(rows)
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
            "request_summary": request_summary,
            "quality": quality,
            "rows": rows,
            "data_access_audit": {
                "returns_read": False,
                "pnl_read": False,
                "signals_read": False,
                "oos_read": False,
            },
            "next_allowed_command": (
                "fast-edge-membership-history-plan"
                if quality["accepted"]
                else "none_membership_v2_source_rejected"
            ),
            "blocked_actions": [
                "history_collect_without_new_hash_bound_plan",
                "momentum_retest_before_history_quality",
                "grid_search",
                "retune",
                "live_orders",
                "private_api_keys",
            ],
        }
    except Exception as exc:  # noqa: BLE001 - persist a resumable public-probe failure.
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
            "next_allowed_command": "fast-edge-membership-v2-probe",
            "resume_contract": {
                "same_run_id": plan["run_id"],
                "same_plan_hash": plan["plan_hash"],
                "visible_terminal_required": True,
            },
            "data_access_audit": {
                "returns_read": False,
                "pnl_read": False,
                "signals_read": False,
                "oos_read": False,
            },
        }
    report["artifact_hash"] = sha256_json(_probe_payload_for_hash(report))
    _atomic_write_json(resolved_output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate historical futures membership v2 PlanOnly/probe")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--daily-manifest", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument("--plan", required=True)
    probe_parser.add_argument("--expected-plan-hash", required=True)
    probe_parser.add_argument("--output", required=True)
    probe_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    probe_parser.add_argument("--timeout-sec", type=int, default=15)
    args = parser.parse_args()
    if args.command == "plan":
        result = build_plan(
            daily_manifest_path=args.daily_manifest,
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
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
