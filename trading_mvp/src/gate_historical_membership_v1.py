from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests


SCHEMA = "trading_mvp_gate_historical_membership_plan_v1"
PROBE_SCHEMA = "trading_mvp_gate_historical_membership_probe_v1"
PLAN_DECISION = "GATE_HISTORICAL_MEMBERSHIP_PLAN_READY_AWAITING_EXPLICIT_PUBLIC_PROBE_APPROVAL"
ACCEPTED_PROBE_DECISION = "GATE_HISTORICAL_MEMBERSHIP_SOURCE_ACCEPTED_READY_FOR_BACKFILL_PLANONLY"
REJECTED_PROBE_DECISION = "GATE_HISTORICAL_MEMBERSHIP_SOURCE_REJECTED"
STOPPED_INCOMPLETE_DECISION = "GATE_HISTORICAL_MEMBERSHIP_PROBE_STOPPED_INCOMPLETE"
GATE_CONTRACTS_ALL_ENDPOINT = "https://api.gateio.ws/api/v4/futures/usdt/contracts_all"
GATE_ARCHIVE_BASE_URL = "https://download.gatedata.org"
MAX_RUNTIME_SEC = 600
DEFAULT_PAGE_LIMIT = 100
DEFAULT_MAX_PAGES = 20
MIN_CONTRACTS = 100
MIN_DELISTED_CONTRACTS = 1
MIN_LIFECYCLE_START_COVERAGE = 0.95
MIN_DELISTED_END_COVERAGE = 0.90
EXCLUDED_CONTRACT_TYPES = frozenset(
    {
        "commodity",
        "commodities",
        "forex",
        "index",
        "indices",
        "metal",
        "metals",
        "stock",
        "stocks",
    }
)


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


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return int(parsed)


def _read_json_object(path: str | Path) -> dict[str, Any]:
    artifact_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {artifact_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {artifact_path}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


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
    module_sha256: str,
    run_id: str,
    max_runtime_sec: int,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "data_type": "GATE_FUTURES_HISTORICAL_MEMBERSHIP_V1",
        "stage": "source_availability_probe",
        "repair_target": "cross_sectional_momentum_daily_lookback30_survivorship_repair",
        "venue_scope": ["gateio"],
        "source_contract": {
            "gate_contracts_all_endpoint": GATE_CONTRACTS_ALL_ENDPOINT,
            "gate_archive_base_url": GATE_ARCHIVE_BASE_URL,
            "settle": "usdt",
            "public_api_only": True,
            "pagination": {
                "limit": DEFAULT_PAGE_LIMIT,
                "max_pages": DEFAULT_MAX_PAGES,
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
            ],
            "required_archive_series_for_later_backfill": [
                "futures_usdt/candlesticks_1h",
                "futures_usdt/funding_applies",
            ],
        },
        "input_provenance": {
            "daily_manifest_path": str(daily_manifest_path),
            "daily_manifest_sha256": daily_manifest_sha256,
            "daily_run_id": daily_run_id,
            "known_bias": "current_top_volume_universe_survivorship",
            "returns_files_are_not_inputs": True,
        },
        "code_provenance": {
            "module": "gate_historical_membership_v1.py",
            "module_sha256": module_sha256,
            "hash_bound_execution_required": True,
        },
        "quality_gates": {
            "minimum_contracts": MIN_CONTRACTS,
            "minimum_delisted_contracts": MIN_DELISTED_CONTRACTS,
            "minimum_lifecycle_start_coverage": MIN_LIFECYCLE_START_COVERAGE,
            "minimum_delisted_end_coverage": MIN_DELISTED_END_COVERAGE,
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
            "membership_lifecycle_alone_does_not_prove_historical_liquidity": True,
            "history_backfill_requires_a_separate_hash_bound_plan": True,
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
    frozen_contract = _plan_contract(
        daily_manifest_path=manifest_path,
        daily_manifest_sha256=sha256_file(manifest_path),
        daily_run_id=str(manifest.get("run_id") or ""),
        module_sha256=sha256_file(Path(__file__).resolve()),
        run_id=normalized_run_id,
        max_runtime_sec=runtime,
    )
    plan_hash = sha256_json(frozen_contract)
    approval_phrase = (
        "Подтверждаю visible Gate historical-membership public probe "
        f"plan_hash={plan_hash}, run_id={normalized_run_id}, MaxRuntimeSec={runtime}, "
        "public API only, без returns/OOS/grid/live/private API keys."
    )
    result: dict[str, Any] = {
        **frozen_contract,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "decision": PLAN_DECISION,
        "final": True,
        "plan_hash": plan_hash,
        "frozen_contract": frozen_contract,
        "network_calls_now": False,
        "collect_allowed_now": False,
        "probe_allowed_now": False,
        "requires_explicit_hash_bound_approval": True,
        "approval_phrase": approval_phrase,
        "next_allowed_command": "fast-edge-membership-probe",
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_read": False,
            "oos_metrics_read": False,
        },
        "blocked_actions": [
            "history_collect_before_probe_accept",
            "momentum_retest_before_survivorship_repair",
            "grid_search",
            "retune",
            "oos_read",
            "execution_probe",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "leverage_or_margin",
        ],
    }
    if output_path is not None:
        _atomic_write_json(Path(output_path).expanduser().resolve(), result)
    return result


def authorize_probe(plan_path: str | Path, expected_plan_hash: str) -> dict[str, Any]:
    plan = _read_json_object(plan_path)
    if plan.get("schema") != SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected membership PlanOnly artifact")
    frozen_contract = plan.get("frozen_contract")
    if not isinstance(frozen_contract, Mapping):
        raise ValueError("frozen_contract is missing")
    computed_hash = sha256_json(frozen_contract)
    recorded_hash = str(plan.get("plan_hash") or "")
    expected_hash = str(expected_plan_hash or "")
    if not expected_hash or recorded_hash != computed_hash or expected_hash != computed_hash:
        raise ValueError("plan hash mismatch")
    code_provenance = frozen_contract.get("code_provenance")
    if not isinstance(code_provenance, Mapping):
        raise ValueError("code_provenance is missing")
    if str(code_provenance.get("module_sha256") or "") != sha256_file(Path(__file__).resolve()):
        raise ValueError("membership evaluator code hash mismatch")
    if plan.get("next_allowed_command") != "fast-edge-membership-probe":
        raise ValueError("membership probe is not the next allowed command")
    return plan


def parse_contracts_all(payload: Any, *, snapshot_ts: int) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("Gate contracts_all payload must be a list")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("name") or "").strip().upper()
        if not symbol.endswith("_USDT"):
            continue
        instrument_type = str(item.get("type") or "direct").strip().lower()
        contract_type = str(item.get("contract_type") or "crypto").strip().lower()
        if instrument_type not in {"", "direct"} or contract_type in EXCLUDED_CONTRACT_TYPES:
            continue
        status = str(item.get("status") or "unknown").strip().lower()
        create_time = _as_int(item.get("create_time"))
        launch_time = _as_int(item.get("launch_time"))
        delisting_time = _as_int(item.get("delisting_time"))
        delisted_time = _as_int(item.get("delisted_time"))
        listed_from_ts = launch_time or create_time
        delisted_by_position = bool(item.get("in_delisting")) and str(item.get("position_size") or "") == "0"
        inactive = status in {"delisted", "delisting"} or delisted_by_position
        lifecycle_status = "delisted" if delisted_by_position and status not in {"delisted", "delisting"} else status
        listed_to_ts = (delisted_time or delisting_time) if inactive else None
        active_at_snapshot = status == "trading" and not bool(item.get("in_delisting"))
        rows.append(
            {
                "exchange": "gateio",
                "symbol": symbol,
                "base": symbol.rsplit("_", 1)[0],
                "quote": "USDT",
                "instrument_type": "linear_perpetual",
                "contract_type": contract_type or "crypto",
                "lifecycle_status": lifecycle_status,
                "create_time": create_time,
                "launch_time": launch_time,
                "delisting_time": delisting_time,
                "delisted_time": delisted_time,
                "listed_from_ts": listed_from_ts,
                "listed_to_ts": listed_to_ts,
                "active_at_snapshot": active_at_snapshot,
                "in_delisting": bool(item.get("in_delisting")),
                "snapshot_ts": int(snapshot_ts),
                "source_endpoint": GATE_CONTRACTS_ALL_ENDPOINT,
            }
        )
    return sorted(rows, key=lambda row: row["symbol"])


def summarize_membership_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row.get("symbol") or "") for row in rows)
    duplicate_symbols = sorted(symbol for symbol, count in counts.items() if symbol and count > 1)
    delisted = [
        row
        for row in rows
        if row.get("active_at_snapshot") is False
        and str(row.get("lifecycle_status") or "") in {"delisted", "delisting"}
    ]
    start_complete = sum(_as_int(row.get("listed_from_ts")) is not None for row in rows)
    end_complete = sum(_as_int(row.get("listed_to_ts")) is not None for row in delisted)
    invalid_intervals = sorted(
        str(row.get("symbol") or "")
        for row in rows
        if _as_int(row.get("listed_from_ts")) is not None
        and _as_int(row.get("listed_to_ts")) is not None
        and int(row["listed_to_ts"]) <= int(row["listed_from_ts"])
    )
    total = len(rows)
    start_coverage = start_complete / total if total else 0.0
    delisted_end_coverage = end_complete / len(delisted) if delisted else 0.0
    accepted = (
        total >= MIN_CONTRACTS
        and len(delisted) >= MIN_DELISTED_CONTRACTS
        and start_coverage >= MIN_LIFECYCLE_START_COVERAGE
        and delisted_end_coverage >= MIN_DELISTED_END_COVERAGE
        and not duplicate_symbols
        and not invalid_intervals
    )
    return {
        "accepted": accepted,
        "decision": ACCEPTED_PROBE_DECISION if accepted else REJECTED_PROBE_DECISION,
        "contracts": total,
        "active_contracts": sum(row.get("active_at_snapshot") is True for row in rows),
        "delisted_contracts": len(delisted),
        "lifecycle_start_coverage": start_coverage,
        "delisted_end_coverage": delisted_end_coverage,
        "duplicate_symbols": duplicate_symbols,
        "invalid_lifecycle_intervals": invalid_intervals,
        "quality_gates": {
            "minimum_contracts": MIN_CONTRACTS,
            "minimum_delisted_contracts": MIN_DELISTED_CONTRACTS,
            "minimum_lifecycle_start_coverage": MIN_LIFECYCLE_START_COVERAGE,
            "minimum_delisted_end_coverage": MIN_DELISTED_END_COVERAGE,
        },
    }


def fetch_contracts_all(
    fetch_page: Callable[[int, int], Any],
    *,
    page_limit: int,
    max_pages: int,
    deadline_monotonic: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if page_limit < 1 or max_pages < 1:
        raise ValueError("pagination limits must be positive")
    rows: list[dict[str, Any]] = []
    page_hashes: set[str] = set()
    requests_made = 0
    for page_index in range(max_pages):
        if time.monotonic() >= deadline_monotonic:
            raise TimeoutError("membership probe runtime exhausted")
        offset = page_index * page_limit
        payload = fetch_page(page_limit, offset)
        requests_made += 1
        if not isinstance(payload, list):
            raise ValueError("Gate contracts_all page must be a list")
        page_hash = sha256_json(payload)
        if page_hash in page_hashes and payload:
            raise ValueError("duplicate contracts_all page")
        page_hashes.add(page_hash)
        rows.extend(dict(item) for item in payload if isinstance(item, Mapping))
        if len(payload) < page_limit:
            break
    else:
        raise ValueError("contracts_all pagination exceeded max_pages")
    return rows, {"requests_made": requests_made, "pages": requests_made, "raw_rows": len(rows)}


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

    started_monotonic = time.monotonic()
    deadline = started_monotonic + runtime
    try:
        if fetch_page_override is None:
            session = requests.Session()
            session.trust_env = False

            def fetch_page(limit: int, offset: int) -> Any:
                response = session.get(
                    GATE_CONTRACTS_ALL_ENDPOINT,
                    params={"limit": limit, "offset": offset},
                    timeout=min(timeout_sec, max(1.0, deadline - time.monotonic())),
                )
                response.raise_for_status()
                return response.json()
        else:
            fetch_page = fetch_page_override

        pagination = plan["source_contract"]["pagination"]
        raw_rows, request_summary = fetch_contracts_all(
            fetch_page,
            page_limit=int(pagination["limit"]),
            max_pages=int(pagination["max_pages"]),
            deadline_monotonic=deadline,
        )
        snapshot_ts = int(time.time())
        rows = parse_contracts_all(raw_rows, snapshot_ts=snapshot_ts)
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
            "runtime_sec": time.monotonic() - started_monotonic,
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
                else "none_membership_source_rejected"
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
    except Exception as exc:  # noqa: BLE001 - preserve a resumable public-probe failure artifact.
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
            "runtime_sec": time.monotonic() - started_monotonic,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "data_access_audit": {
                "returns_read": False,
                "pnl_read": False,
                "signals_read": False,
                "oos_read": False,
            },
            "next_allowed_command": "fast-edge-membership-probe",
            "resume_contract": {
                "same_run_id": plan["run_id"],
                "same_plan_hash": plan["plan_hash"],
                "visible_terminal_required": True,
            },
            "blocked_actions": [
                "history_collect",
                "momentum_retest",
                "grid_search",
                "retune",
                "live_orders",
                "private_api_keys",
            ],
        }
    report["artifact_hash"] = sha256_json(
        {key: value for key, value in report.items() if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}}
    )
    _atomic_write_json(resolved_output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate historical futures membership PlanOnly/probe")
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
