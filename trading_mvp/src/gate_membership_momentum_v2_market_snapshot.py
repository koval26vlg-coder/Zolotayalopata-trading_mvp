from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from daily_collector import GateDailyClient
from funding import FundingContract
import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_membership_momentum_v2_execution_probe as probe
import gate_membership_momentum_v2_execution_selection as selection
import gate_membership_momentum_v2_oos as v2_oos
import gate_membership_momentum_v2_train as v2_train
from gate_membership_momentum import DAY_SEC


PLAN_SCHEMA = "trading_mvp_gate_membership_momentum_v2_market_snapshot_plan_v1"
PLAN_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_MARKET_SNAPSHOT_PLAN_READY"
MAX_RUNTIME_SEC = 600
MAX_WORKERS = 4
GATE_CANDLES_ENDPOINT = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"


ContractFetcher = Callable[[], Iterable[FundingContract]]
CandleFetcher = Callable[[str, int, int], list[dict[str, Any]]]


def market_snapshot_plan_hash(payload: Mapping[str, Any]) -> str:
    frozen = payload.get("frozen_contract")
    if isinstance(frozen, Mapping):
        return v3_history_plan.sha256_json(frozen)
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "plan_hash", "approval_phrase"}
        }
    )


def _utc_iso(timestamp: int | float) -> str:
    return datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _read_bound_oos_universe(
    probe_plan: Mapping[str, Any],
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    authorization = probe_plan.get("historical_authorization")
    if not isinstance(authorization, Mapping):
        raise ValueError("execution-probe historical authorization is missing")
    oos_plan_path = Path(str(authorization.get("oos_plan_path") or "")).expanduser().resolve()
    oos_plan = v2_oos.authorize_oos_evaluation(
        oos_plan_path,
        str(authorization.get("oos_plan_hash") or ""),
    )
    if v3_history_plan.sha256_file(oos_plan_path) != str(
        authorization.get("oos_plan_sha256") or ""
    ):
        raise ValueError("execution-probe OOS plan file hash mismatch")
    oos_input = oos_plan.get("oos_input")
    if not isinstance(oos_input, Mapping):
        raise ValueError("momentum-v2 OOS input is missing")
    manifest_path = Path(str(oos_input.get("manifest_path") or "")).expanduser().resolve()
    if v3_history_plan.sha256_file(manifest_path) != str(
        oos_input.get("manifest_sha256") or ""
    ):
        raise ValueError("sealed OOS manifest file hash mismatch")
    manifest = v2_oos._validate_oos_manifest(  # noqa: SLF001 - shared frozen contract validator.
        manifest_path,
        expected_hash=str(oos_input.get("manifest_hash") or ""),
    )
    return oos_plan, oos_plan_path, manifest, manifest_path


def _candidate_universe(
    manifest: Mapping[str, Any],
    *,
    signal_close_ts: int,
) -> list[dict[str, Any]]:
    raw_universe = manifest.get("universe")
    if not isinstance(raw_universe, list):
        raise ValueError("sealed OOS universe is missing")
    candidates: list[dict[str, Any]] = []
    identities: set[str] = set()
    symbols: set[str] = set()
    bases: set[str] = set()
    for raw in raw_universe:
        if not isinstance(raw, Mapping):
            raise ValueError("sealed OOS universe row must be an object")
        if str(raw.get("exchange") or "") != "gateio":
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()
        base = str(raw.get("base") or "").strip().upper()
        quote = str(raw.get("quote") or "USDT").strip().upper()
        canonical_id = str(raw.get("canonical_asset_id") or "").strip()
        if not symbol or not base or quote != "USDT" or not canonical_id:
            raise ValueError("sealed OOS universe identity is incomplete")
        if canonical_id in identities or symbol in symbols or base in bases:
            raise ValueError("sealed OOS universe canonical identity is duplicated")
        identities.add(canonical_id)
        symbols.add(symbol)
        bases.add(base)
        if raw.get("non_binance_baseline") is not True:
            continue
        listed_from = int(raw.get("listed_from_ts") or 0)
        listed_to_raw = raw.get("listed_to_ts")
        listed_to = int(listed_to_raw) if listed_to_raw is not None else None
        if listed_from > signal_close_ts:
            continue
        if listed_to is not None and listed_to <= signal_close_ts:
            continue
        candidates.append(
            {
                "exchange": "gateio",
                "market_type": "usdt_linear_perpetual",
                "canonical_asset_id": canonical_id,
                "coin_id": str(raw.get("coin_id") or ""),
                "symbol": symbol,
                "base": base,
                "quote": quote,
                "non_binance_baseline": True,
                "non_binance_evidence": str(raw.get("non_binance_evidence") or ""),
                "listed_from_ts": listed_from,
                "listed_to_ts": listed_to,
            }
        )
    candidates.sort(key=lambda row: (row["canonical_asset_id"], row["symbol"]))
    return candidates


def build_market_snapshot_plan(
    *,
    probe_plan_path: str | Path,
    expected_probe_plan_hash: str,
    output_path: str | Path | None,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be between 1 and {MAX_RUNTIME_SEC}")
    resolved_probe = Path(probe_plan_path).expanduser().resolve()
    probe_plan = probe.validate_execution_probe_plan(
        resolved_probe,
        v2_train._validate_hash(expected_probe_plan_hash, label="execution probe plan hash"),
    )
    oos_plan, oos_plan_path, oos_manifest, oos_manifest_path = _read_bound_oos_universe(
        probe_plan
    )
    target = probe_plan["target_event_contract"]
    execution = probe_plan["execution_contract"]
    signal_day = int(target["target_signal_day"])
    signal_close_ts = int(target["target_signal_close_ts"])
    first_window_ts = int(execution["windows"][0]["start_ts"])
    if first_window_ts - signal_close_ts < probe.WINDOW_PREP_BUFFER_SEC:
        raise ValueError("execution probe does not reserve the frozen snapshot prep buffer")
    strategy = probe_plan["strategy"]
    lookback_days = int(strategy["lookback_days"])
    liquidity_days = int(strategy["liquidity_lookback_days"])
    history_days = max(lookback_days, liquidity_days) + 1
    candidates = _candidate_universe(oos_manifest, signal_close_ts=signal_close_ts)
    minimum_markets = int(strategy["minimum_scored_markets"])
    if len(candidates) < minimum_markets:
        raise ValueError("insufficient hash-bound non-Binance Gate universe for market snapshot")

    module_paths = {
        "module": Path(__file__).resolve(),
        "probe_module": Path(probe.__file__).resolve(),
        "selection_module": Path(selection.__file__).resolve(),
        "oos_module": Path(v2_oos.__file__).resolve(),
        "daily_client_module": Path(__import__("daily_collector").__file__).resolve(),
    }
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    contract: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": "gate_membership_momentum_v2_market_snapshot_planonly",
        "stage": "causal_forward_market_snapshot",
        "decision": PLAN_DECISION,
        "hypothesis_id": probe_plan["hypothesis_id"],
        "research_only": True,
        "network_access": False,
        "public_api_only": True,
        "oos_returns_read": False,
        "grid_search": False,
        "retune": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "probe_plan_authorization": {
            "path": str(resolved_probe),
            "file_sha256": v3_history_plan.sha256_file(resolved_probe),
            "plan_hash": probe_plan["plan_hash"],
            "decision": probe.PLAN_DECISION,
        },
        "oos_universe_authorization": {
            "oos_plan_path": str(oos_plan_path),
            "oos_plan_sha256": v3_history_plan.sha256_file(oos_plan_path),
            "oos_plan_hash": oos_plan["plan_hash"],
            "oos_manifest_path": str(oos_manifest_path),
            "oos_manifest_sha256": v3_history_plan.sha256_file(oos_manifest_path),
            "oos_manifest_hash": oos_manifest["artifact_hash"],
        },
        "target_event_contract": dict(target),
        "execution_contract": dict(execution),
        "candidate_universe": candidates,
        "snapshot_contract": {
            "exchange": "gateio",
            "market_type": "usdt_linear_perpetual",
            "endpoint": GATE_CANDLES_ENDPOINT,
            "interval": "1d",
            "start_day": signal_day - history_days + 1,
            "end_day": signal_day,
            "from_sec": (signal_day - history_days + 1) * DAY_SEC,
            "to_sec": signal_close_ts,
            "expected_closed_days": history_days,
            "not_before_ts": signal_close_ts,
            "hard_deadline_ts": first_window_ts,
            "maximum_runtime_sec": runtime,
            "maximum_workers": MAX_WORKERS,
            "manual_shortlist": False,
            "future_bars_allowed": False,
        },
        "code_provenance": code_provenance,
        "data_access_audit": {
            "sealed_oos_manifest_metadata_read": True,
            "oos_return_rows_read": False,
            "oos_events_used_for_selection": False,
            "future_bars_read": False,
            "manual_shortlist": False,
        },
        "maximum_authority": "PUBLIC_MARKET_SNAPSHOT_COLLECT",
        "next_allowed_command": "fast-edge-membership-momentum-v2-market-snapshot-collect",
        "blocked_actions": [
            "grid_search",
            "retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
    }
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "probe_plan_hash": probe_plan["plan_hash"],
            "probe_plan_sha256": contract["probe_plan_authorization"]["file_sha256"],
            "oos_plan_hash": oos_plan["plan_hash"],
            "oos_manifest_hash": oos_manifest["artifact_hash"],
            "candidate_universe": candidates,
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = v3_history_plan.sha256_json(contract)
    approval_phrase = (
        "Подтверждаю visible Gate momentum-v2 market-snapshot collect "
        f"plan_hash={plan_hash}, run_id={normalized_run_id}, MaxRuntimeSec={runtime}, "
        "public contracts/closed daily candles only, без OOS events/grid/live/private API keys."
    )
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": plan_hash,
        "approval_phrase": approval_phrase,
        "frozen_contract": contract,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, payload)
    return payload


def validate_market_snapshot_plan(
    path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    plan = v2_train._read_json_object(resolved)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected momentum-v2 market snapshot PlanOnly")
    if not isinstance(frozen, Mapping):
        raise ValueError("market snapshot frozen contract is missing")
    computed = v3_history_plan.sha256_json(frozen)
    if (
        plan.get("plan_hash") != computed
        or (expected_plan_hash is not None and str(expected_plan_hash) != computed)
        or not all(plan.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("market snapshot PlanOnly hash mismatch")
    probe_auth = plan.get("probe_plan_authorization")
    if not isinstance(probe_auth, Mapping):
        raise ValueError("market snapshot probe authorization is missing")
    probe_path = Path(str(probe_auth.get("path") or "")).expanduser().resolve()
    probe_plan = probe.validate_execution_probe_plan(
        probe_path,
        str(probe_auth.get("plan_hash") or ""),
    )
    if v3_history_plan.sha256_file(probe_path) != probe_auth.get("file_sha256"):
        raise ValueError("market snapshot probe file hash mismatch")
    rebuilt = build_market_snapshot_plan(
        probe_plan_path=probe_path,
        expected_probe_plan_hash=probe_plan["plan_hash"],
        output_path=None,
        run_id=str(plan.get("run_id") or ""),
        max_runtime_sec=int(plan["snapshot_contract"]["maximum_runtime_sec"]),
        generated_at_utc=str(plan.get("generated_at_utc") or ""),
    )
    if rebuilt["plan_hash"] != computed or rebuilt["frozen_contract"] != frozen:
        raise ValueError("market snapshot PlanOnly no longer matches source provenance")
    return plan


def _normalize_closed_bars(
    rows: Iterable[Mapping[str, Any]],
    *,
    start_day: int,
    signal_day: int,
) -> list[dict[str, Any]]:
    by_ts: dict[int, dict[str, Any]] = {}
    for raw in rows:
        timestamp = int(float(raw.get("ts") or -1))
        if timestamp < start_day * DAY_SEC or timestamp > signal_day * DAY_SEC:
            continue
        if timestamp % DAY_SEC or timestamp in by_ts:
            raise ValueError("Gate daily candles contain duplicate or non-UTC timestamps")
        close = float(raw.get("close") or 0.0)
        volume_quote = float(raw.get("volume_quote") or 0.0)
        if not math.isfinite(close) or not math.isfinite(volume_quote) or close <= 0 or volume_quote < 0:
            raise ValueError("Gate daily candle contains invalid close/quote volume")
        by_ts[timestamp] = {
            "ts": timestamp,
            "close": close,
            "volume_quote": volume_quote,
            "closed": True,
        }
    return [by_ts[key] for key in sorted(by_ts)]


def collect_market_snapshot(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path,
    max_runtime_sec: int | None = None,
    workers: int = MAX_WORKERS,
    contract_fetcher: ContractFetcher | None = None,
    candle_fetcher: CandleFetcher | None = None,
    now_fn: Callable[[], float] = time.time,
    monotonic_fn: Callable[[], float] = time.monotonic,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"market snapshot output already exists: {output}")
    plan = validate_market_snapshot_plan(resolved_plan, expected_plan_hash)
    contract = plan["snapshot_contract"]
    runtime = int(max_runtime_sec or contract["maximum_runtime_sec"])
    if runtime < 1 or runtime > int(contract["maximum_runtime_sec"]):
        raise ValueError("market snapshot runtime exceeds frozen contract")
    worker_count = int(workers)
    if worker_count < 1 or worker_count > int(contract["maximum_workers"]):
        raise ValueError("market snapshot workers exceed frozen contract")
    now_ts = int(now_fn())
    not_before_ts = int(contract["not_before_ts"])
    hard_deadline_ts = int(contract["hard_deadline_ts"])
    if now_ts < not_before_ts:
        raise RuntimeError("market snapshot is not due yet")
    if now_ts >= hard_deadline_ts:
        raise RuntimeError("market snapshot window missed")
    if now_ts + runtime > hard_deadline_ts:
        runtime = hard_deadline_ts - now_ts
    if runtime < 1:
        raise RuntimeError("market snapshot window missed")

    client: GateDailyClient | None = None
    if contract_fetcher is None or candle_fetcher is None:
        client = GateDailyClient(timeout_sec=10)
        if contract_fetcher is None:
            contract_fetcher = client.fetch_contracts
        if candle_fetcher is None:
            candle_fetcher = client.fetch_daily_klines
    assert contract_fetcher is not None and candle_fetcher is not None
    started = monotonic_fn()
    contracts = list(contract_fetcher())
    contracts_by_symbol = {
        item.symbol: item
        for item in contracts
        if isinstance(item, FundingContract) and item.exchange == "gateio"
    }
    rows_by_symbol: dict[str, dict[str, Any]] = {}
    futures: dict[Any, tuple[dict[str, Any], FundingContract]] = {}
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="gate-daily-snapshot") as pool:
        for candidate in plan["candidate_universe"]:
            symbol = str(candidate["symbol"])
            current = contracts_by_symbol.get(symbol)
            if current is None:
                rows_by_symbol[symbol] = _market_row(candidate, bars=[], current=None, error="contract_not_trading")
                continue
            futures[
                pool.submit(
                    candle_fetcher,
                    symbol,
                    int(contract["from_sec"]),
                    int(contract["to_sec"]),
                )
            ] = (candidate, current)
        for future in as_completed(futures):
            candidate, current = futures[future]
            symbol = str(candidate["symbol"])
            try:
                if monotonic_fn() - started >= runtime:
                    raise TimeoutError("market snapshot runtime exhausted")
                bars = _normalize_closed_bars(
                    future.result(),
                    start_day=int(contract["start_day"]),
                    signal_day=int(contract["end_day"]),
                )
                rows_by_symbol[symbol] = _market_row(candidate, bars=bars, current=current, error=None)
            except Exception as exc:  # Public data failures are quality evidence.
                rows_by_symbol[symbol] = _market_row(
                    candidate,
                    bars=[],
                    current=current,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )

    as_of_ts = int(now_fn())
    if as_of_ts >= hard_deadline_ts:
        raise RuntimeError("market snapshot window missed during collection")
    rows = [rows_by_symbol[str(item["symbol"])] for item in plan["candidate_universe"]]
    successful = sum(row["collection_error"] is None for row in rows)
    generated = generated_at_utc or _utc_iso(as_of_ts)
    payload: dict[str, Any] = {
        "schema": selection.MARKET_SNAPSHOT_SCHEMA,
        "final": True,
        "decision": selection.MARKET_SNAPSHOT_READY_DECISION,
        "exchange": "gateio",
        "market_type": "usdt_linear_perpetual",
        "public_data_only": True,
        "private_api_keys": False,
        "live_orders": False,
        "target_signal_day": int(plan["target_event_contract"]["target_signal_day"]),
        "as_of_ts": as_of_ts,
        "as_of_utc": _utc_iso(as_of_ts),
        "generated_at_utc": generated,
        "plan_authorization": {
            "path": str(resolved_plan),
            "file_sha256": v3_history_plan.sha256_file(resolved_plan),
            "plan_hash": plan["plan_hash"],
        },
        "rows": rows,
        "collection_summary": {
            "planned_markets": len(rows),
            "successful_markets": successful,
            "failed_markets": len(rows) - successful,
            "runtime_sec": max(0.0, monotonic_fn() - started),
            "workers": worker_count,
        },
        "data_access_audit": {
            "public_gate_contracts_read": True,
            "closed_daily_prices_read": True,
            "oos_events_used_for_selection": False,
            "future_bars_read": False,
            "manual_shortlist": False,
            "network_access": contract_fetcher is not None,
        },
        "research_only": True,
        "grid_search": False,
        "retune": False,
        "paper_forward_allowed": False,
        "leverage_or_margin": False,
        "next_allowed_command": "fast-edge-membership-momentum-v2-execution-selection",
    }
    payload["artifact_hash"] = selection.market_snapshot_hash(payload)
    v2_train._write_json_immutable(output, payload)
    return payload


def _market_row(
    candidate: Mapping[str, Any],
    *,
    bars: list[dict[str, Any]],
    current: FundingContract | None,
    error: str | None,
) -> dict[str, Any]:
    identity_confirmed = bool(
        current is not None
        and current.symbol == candidate["symbol"]
        and current.base == candidate["base"]
        and current.quote == "USDT"
    )
    return {
        "exchange": "gateio",
        "market_type": "usdt_linear_perpetual",
        "canonical_asset_id": candidate["canonical_asset_id"],
        "symbol": candidate["symbol"],
        "base": candidate["base"],
        "identity_confirmed": identity_confirmed,
        "binance_spot_excluded": candidate.get("non_binance_baseline") is True,
        "prohibited_asset_class": False,
        "lifecycle_valid_at_signal": identity_confirmed,
        "status": "tradable" if identity_confirmed and error is None else "unavailable",
        "bars": bars,
        "collection_error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate membership momentum-v2 causal market snapshot"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--probe-plan", required=True)
    plan_parser.add_argument("--expected-probe-plan-hash", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash", required=True)
    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--plan", required=True)
    collect_parser.add_argument("--expected-plan-hash", required=True)
    collect_parser.add_argument("--output", required=True)
    collect_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    collect_parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    if args.command == "plan":
        result = build_market_snapshot_plan(
            probe_plan_path=args.probe_plan,
            expected_probe_plan_hash=args.expected_probe_plan_hash,
            output_path=args.output,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    elif args.command == "validate":
        plan = validate_market_snapshot_plan(args.plan, args.expected_plan_hash)
        result = {
            "schema": "trading_mvp_gate_membership_momentum_v2_market_snapshot_plan_validation_v1",
            "valid": True,
            "plan_hash": plan["plan_hash"],
            "run_id": plan["run_id"],
            "decision": plan["decision"],
            "next_allowed_command": plan["next_allowed_command"],
        }
    else:
        result = collect_market_snapshot(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
            max_runtime_sec=args.max_runtime_sec,
            workers=args.workers,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
