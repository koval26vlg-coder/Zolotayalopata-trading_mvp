from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from gate_historical_membership_history_plan import sha256_file, sha256_json
from gate_historical_membership_history_quality import (
    ACCEPTED_DECISION as QUALITY_ACCEPTED_DECISION,
    SCHEMA as QUALITY_SCHEMA,
    _quality_hash,
)
from gate_membership_momentum import (
    DAY_SEC,
    FrozenMomentumConfig,
    MarketSeries,
    cost_contract,
    evaluate_rebalance,
    portfolio_metrics,
)


PLAN_SCHEMA = "trading_mvp_gate_membership_momentum_train_plan_v1"
RESULT_SCHEMA = "trading_mvp_gate_membership_momentum_train_evaluation_v1"
TRAIN_MANIFEST_SCHEMA = "trading_mvp_gate_membership_daily_history_split_v1"
PLAN_DECISION = "GATE_MEMBERSHIP_MOMENTUM_TRAIN_PLAN_READY"
FEASIBLE_DECISION = "GATE_MEMBERSHIP_MOMENTUM_FEASIBLE_FOR_OOS_PLANONLY"
INFEASIBLE_DECISION = "GATE_MEMBERSHIP_MOMENTUM_INFEASIBLE_ON_CURRENT_DATA"
INSUFFICIENT_DECISION = "GATE_MEMBERSHIP_MOMENTUM_INSUFFICIENT_TRAIN_DATA"
MAX_RUNTIME_SEC = 1_800
MIN_TRAIN_REBALANCES = 18
MIN_UNIQUE_ASSETS = 10


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {resolved}")
    return payload


def _atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _manifest_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json({key: value for key, value in payload.items() if key not in {"generated_at_utc", "artifact_hash"}})


def train_plan_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"schema", "generated_at_utc", "plan_hash"}
        }
    )


def _deterministic_result_hash(payload: Mapping[str, Any]) -> str:
    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: clean(item)
                for key, item in value.items()
                if key not in {"generated_at_utc", "runtime_sec", "deterministic_result_hash"}
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return _sha256_json(clean(payload))


def _validate_hash(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"invalid {label}")
    return digest


def _validate_train_manifest(path: Path, expected_hash: str) -> dict[str, Any]:
    manifest = _read_json_object(path)
    if manifest.get("schema") != TRAIN_MANIFEST_SCHEMA or manifest.get("stage") != "train_view":
        raise ValueError("unexpected train manifest schema or stage")
    if manifest.get("oos_paths_present") is not False:
        raise ValueError("train manifest must not expose OOS paths")
    stored = str(manifest.get("artifact_hash") or "")
    if stored != _manifest_hash(manifest) or stored != expected_hash:
        raise ValueError("train manifest hash mismatch")
    range_payload = manifest.get("range")
    if not isinstance(range_payload, Mapping):
        raise ValueError("train manifest range is missing")
    start = int(range_payload.get("start_sec") or 0)
    end = int(range_payload.get("end_sec") or 0)
    if start < 0 or end <= start or start % DAY_SEC or end % DAY_SEC:
        raise ValueError("train manifest range must be positive and UTC-day aligned")
    root = path.parent.resolve()
    files = manifest.get("normalized_files")
    if not isinstance(files, list) or not files:
        raise ValueError("train manifest normalized files are missing")
    symbols: set[str] = set()
    for raw in files:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid train file record")
        symbol = str(raw.get("symbol") or "")
        if not symbol or symbol in symbols:
            raise ValueError("duplicate or missing train symbol")
        symbols.add(symbol)
        for path_key, hash_key in (("kline_path", "kline_sha256"), ("funding_path", "funding_sha256")):
            target = Path(str(raw.get(path_key) or "")).expanduser().resolve()
            if not target.is_file() or not target.is_relative_to(root):
                raise ValueError(f"train artifact escapes train root: {path_key}")
            if sha256_file(target) != _validate_hash(raw.get(hash_key), label=hash_key):
                raise ValueError(f"train artifact hash mismatch: {path_key}")
    return manifest


def build_train_plan(
    *,
    quality_report_path: str | Path,
    expected_quality_hash: str,
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
    quality_path = Path(quality_report_path).expanduser().resolve()
    quality = _read_json_object(quality_path)
    if (
        quality.get("schema") != QUALITY_SCHEMA
        or quality.get("final") is not True
        or quality.get("accepted") is not True
        or quality.get("decision") != QUALITY_ACCEPTED_DECISION
    ):
        raise ValueError("history quality report is not accepted and final")
    quality_hash = _validate_hash(expected_quality_hash, label="quality artifact hash")
    if str(quality.get("artifact_hash") or "") != _quality_hash(quality) or quality["artifact_hash"] != quality_hash:
        raise ValueError("history quality artifact hash mismatch")
    audit = quality.get("data_access_audit")
    if not isinstance(audit, Mapping) or audit.get("returns_computed") is not False or audit.get("oos_read") is not False:
        raise ValueError("history quality data-access audit is unsafe")
    train_manifest_path = Path(str(quality.get("train_manifest_path") or "")).expanduser().resolve()
    train_manifest_hash = _validate_hash(quality.get("train_manifest_hash"), label="train manifest hash")
    train_manifest = _validate_train_manifest(train_manifest_path, train_manifest_hash)
    oos_commitment = _validate_hash(quality.get("oos_commitment_hash"), label="OOS commitment hash")
    config = FrozenMomentumConfig()
    costs = cost_contract()
    module_path = Path(__file__).resolve()
    core_path = Path(__import__("gate_membership_momentum").__file__).resolve()
    start_sec = int(train_manifest["range"]["start_sec"])
    end_sec = int(train_manifest["range"]["end_sec"])
    contract: dict[str, Any] = {
        "run_id": normalized_run_id,
        "mode": "gate_membership_momentum_train_planonly",
        "stage": "train_feasibility",
        "decision": PLAN_DECISION,
        "hypothesis_id": "cross_sectional_momentum_daily_survivorship_repair_v1",
        "research_only": True,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "oos_allowed_now": False,
        "oos_read": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "strategy": config.as_dict(),
        "cost_contract": costs,
        "train_input": {
            "manifest_path": str(train_manifest_path),
            "manifest_sha256": sha256_file(train_manifest_path),
            "manifest_hash": train_manifest_hash,
            "range": {"start_sec": start_sec, "end_sec": end_sec},
            "quality_report_sha256": sha256_file(quality_path),
            "quality_artifact_hash": quality_hash,
            "normalized_manifest_hash": _validate_hash(
                quality.get("normalized_manifest_hash"), label="normalized manifest hash"
            ),
        },
        "oos_commitment_hash": oos_commitment,
        "train_gates": {
            "minimum_independent_rebalances": MIN_TRAIN_REBALANCES,
            "minimum_unique_assets_traded": MIN_UNIQUE_ASSETS,
            "price_only_net_expectancy_bps_gt": 0.0,
            "total_net_expectancy_bps_gt": 0.0,
            "profit_factor_gte": 1.1,
            "stress_total_net_expectancy_bps_gte": 0.0,
            "maximum_drawdown_pct": 15.0,
            "maximum_top_base_positive_share": 0.35,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
            "core_module_path": str(core_path),
            "core_module_sha256": sha256_file(core_path),
        },
        "runtime_contract": {
            "max_runtime_sec": runtime,
            "visible_terminal_required": True,
            "local_immutable_inputs_only": True,
        },
        "data_access_audit": {
            "train_manifest_opened": True,
            "train_returns_read": False,
            "oos_paths_available": False,
            "oos_files_opened": False,
        },
        "next_allowed_command": "fast-edge-membership-momentum-train",
        "blocked_actions": ["oos_before_train_feasibility", "grid_search", "retune", "paper_forward", "live_orders"],
    }
    contract["input_merkle_sha256"] = sha256_json(
        {
            "quality_artifact_hash": quality_hash,
            "train_manifest_hash": train_manifest_hash,
            "oos_commitment_hash": oos_commitment,
            "module_sha256": contract["code_provenance"]["module_sha256"],
            "core_module_sha256": contract["code_provenance"]["core_module_sha256"],
        }
    )
    payload = {
        "schema": PLAN_SCHEMA,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        **contract,
    }
    payload["plan_hash"] = train_plan_hash(payload)
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def _validate_plan(path: Path, expected_plan_hash: str) -> dict[str, Any]:
    plan = _read_json_object(path)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected train plan schema or decision")
    stored = str(plan.get("plan_hash") or "")
    if stored != train_plan_hash(plan) or stored != expected_plan_hash:
        raise ValueError("train plan hash mismatch")
    if plan.get("oos_allowed_now") is not False or plan.get("oos_read") is not False:
        raise ValueError("train plan violates OOS embargo")
    code = plan.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("train plan code provenance is missing")
    if str(code.get("module_sha256") or "") != sha256_file(Path(__file__).resolve()):
        raise ValueError("train evaluator module hash mismatch")
    core_path = Path(str(code.get("core_module_path") or "")).expanduser().resolve()
    if str(code.get("core_module_sha256") or "") != sha256_file(core_path):
        raise ValueError("momentum core module hash mismatch")
    return plan


def _load_markets(manifest: Mapping[str, Any], manifest_path: Path) -> list[MarketSeries]:
    by_symbol = {
        str(item["symbol"]): item
        for item in manifest.get("universe") or []
        if isinstance(item, Mapping) and item.get("symbol")
    }
    markets: list[MarketSeries] = []
    for record in manifest.get("normalized_files") or []:
        if not isinstance(record, Mapping):
            raise ValueError("invalid train file record")
        symbol = str(record.get("symbol") or "")
        item = by_symbol.get(symbol)
        if item is None:
            raise ValueError(f"train universe/file mismatch: {symbol}")
        kline_path = Path(str(record["kline_path"])).expanduser().resolve()
        funding_path = Path(str(record["funding_path"])).expanduser().resolve()
        if not kline_path.is_relative_to(manifest_path.parent) or not funding_path.is_relative_to(manifest_path.parent):
            raise ValueError("train evaluator refuses artifacts outside train root")
        kline = _read_json_object(kline_path)
        funding = _read_json_object(funding_path)
        if kline.get("schema") != "trading_mvp_daily_ohlcv_v1":
            raise ValueError(f"unexpected kline schema: {symbol}")
        if funding.get("schema") != "trading_mvp_funding_settlements_v1":
            raise ValueError(f"unexpected funding schema: {symbol}")
        market = MarketSeries(
            exchange="gateio",
            symbol=symbol,
            base=str(item.get("base") or "").upper(),
            canonical_asset_id=str(item.get("canonical_asset_id") or ""),
        )
        seen_days: set[int] = set()
        for row in kline.get("rows") or []:
            timestamp = int(row["ts"])
            if timestamp % DAY_SEC:
                raise ValueError(f"non-day-aligned kline: {symbol}")
            day = timestamp // DAY_SEC
            if day in seen_days:
                raise ValueError(f"duplicate train day: {symbol}")
            seen_days.add(day)
            open_price = float(row["open"])
            close_price = float(row["close"])
            quote_volume = float(row.get("volume_quote") or 0.0)
            if not all(math.isfinite(value) for value in (open_price, close_price, quote_volume)):
                raise ValueError(f"non-finite train kline: {symbol}")
            if min(open_price, close_price) <= 0.0 or quote_volume < 0.0:
                raise ValueError(f"invalid train kline values: {symbol}")
            market.opens[day] = open_price
            market.closes[day] = close_price
            market.quote_volumes[day] = quote_volume
        previous_funding_ts: int | None = None
        for row in funding.get("rows") or []:
            timestamp = int(row["ts"])
            rate = float(row["funding_rate"])
            if previous_funding_ts is not None and timestamp <= previous_funding_ts:
                raise ValueError(f"funding rows are not strictly ordered: {symbol}")
            if not math.isfinite(rate):
                raise ValueError(f"non-finite funding rate: {symbol}")
            previous_funding_ts = timestamp
            market.funding.append((timestamp, rate))
        markets.append(market)
    return markets


def _profit_factor_pass(metrics: Mapping[str, Any], minimum: float) -> bool:
    value = metrics.get("profit_factor")
    if value is None:
        return float(metrics.get("total_net_expectancy_bps") or 0.0) > 0.0
    return float(value) >= minimum


def evaluate_train_plan(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    started = time.monotonic()
    plan_resolved = Path(plan_path).expanduser().resolve()
    plan = _validate_plan(plan_resolved, expected_plan_hash)
    train_input = plan["train_input"]
    manifest_path = Path(str(train_input["manifest_path"])).expanduser().resolve()
    if sha256_file(manifest_path) != str(train_input["manifest_sha256"]):
        raise ValueError("train manifest file hash mismatch")
    manifest = _validate_train_manifest(manifest_path, str(train_input["manifest_hash"]))
    markets = _load_markets(manifest, manifest_path)
    config = FrozenMomentumConfig(
        lookback_days=int(plan["strategy"]["lookback_days"]),
        hold_days=int(plan["strategy"]["hold_days"]),
        rebalance_every_days=int(plan["strategy"]["rebalance_every_days"]),
        min_per_side=int(plan["strategy"]["min_per_side"]),
        minimum_scored_markets=int(plan["strategy"]["minimum_scored_markets"]),
        liquidity_lookback_days=int(plan["strategy"]["liquidity_lookback_days"]),
        minimum_median_quote_volume=float(plan["strategy"]["minimum_median_quote_volume"]),
    )
    start_day = int(manifest["range"]["start_sec"]) // DAY_SEC
    end_day = int(manifest["range"]["end_sec"]) // DAY_SEC
    first_signal = start_day + config.lookback_days
    last_signal = end_day - config.hold_days - 2
    events = []
    for signal_day in range(first_signal, last_signal + 1, config.rebalance_every_days):
        if time.monotonic() - started >= runtime:
            raise TimeoutError("membership momentum train evaluation runtime exhausted")
        event = evaluate_rebalance(markets, signal_day=signal_day, config=config)
        if event is not None:
            events.append(event)
    costs = plan["cost_contract"]
    normal = portfolio_metrics(
        events,
        cost_bps=float(costs["normal"]["total_bps"]),
        favorable_funding_multiplier=1.0,
    )
    stress = portfolio_metrics(
        events,
        cost_bps=float(costs["stress"]["total_bps"]),
        favorable_funding_multiplier=0.0,
    )
    gates = plan["train_gates"]
    sample_reasons: list[str] = []
    if int(normal.get("independent_rebalances") or 0) < int(gates["minimum_independent_rebalances"]):
        sample_reasons.append("insufficient_independent_rebalances")
    if int(normal.get("unique_assets_traded") or 0) < int(gates["minimum_unique_assets_traded"]):
        sample_reasons.append("insufficient_unique_assets_traded")
    economic_reasons: list[str] = []
    if float(normal.get("price_only_net_expectancy_bps") or 0.0) <= float(gates["price_only_net_expectancy_bps_gt"]):
        economic_reasons.append("price_only_net_expectancy_not_positive")
    if float(normal.get("total_net_expectancy_bps") or 0.0) <= float(gates["total_net_expectancy_bps_gt"]):
        economic_reasons.append("total_net_expectancy_not_positive")
    if not _profit_factor_pass(normal, float(gates["profit_factor_gte"])):
        economic_reasons.append("profit_factor_below_minimum")
    if float(stress.get("total_net_expectancy_bps") or 0.0) < float(gates["stress_total_net_expectancy_bps_gte"]):
        economic_reasons.append("stress_net_expectancy_negative")
    if float(normal.get("max_drawdown_pct") or 0.0) > float(gates["maximum_drawdown_pct"]):
        economic_reasons.append("max_drawdown_above_limit")
    if float(normal.get("top_base_positive_share") or 0.0) > float(gates["maximum_top_base_positive_share"]):
        economic_reasons.append("top_base_concentration_above_limit")
    if sample_reasons:
        decision = INSUFFICIENT_DECISION
        reasons = sample_reasons
        next_command = "none_membership_momentum_branch_closed_insufficient_data"
    elif economic_reasons:
        decision = INFEASIBLE_DECISION
        reasons = economic_reasons
        next_command = "none_membership_momentum_branch_closed_no_retune"
    else:
        decision = FEASIBLE_DECISION
        reasons = []
        next_command = "create_hash_bound_gate_membership_momentum_oos_planonly"
    event_rows = [
        {
            "signal_day": event.signal_day,
            "entry_day": event.entry_day,
            "exit_day": event.exit_day,
            "long_bases": list(event.long_bases),
            "short_bases": list(event.short_bases),
            "price_return": event.price_return,
            "funding_return": event.funding_return,
        }
        for event in events
    ]
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": plan["run_id"],
        "plan_hash": expected_plan_hash,
        "stage": "train_feasibility",
        "final": True,
        "decision": decision,
        "rejection_reasons": reasons,
        "normal_metrics": normal,
        "stress_metrics": stress,
        "events": event_rows,
        "oos_read": False,
        "data_access_audit": {
            "network_access": False,
            "train_manifest_opened": True,
            "train_return_rows_read": True,
            "oos_paths_available": False,
            "oos_files_opened": False,
            "grid_search": False,
            "retune": False,
        },
        "code_provenance": plan["code_provenance"],
        "input_merkle_sha256": plan["input_merkle_sha256"],
        "runtime_sec": time.monotonic() - started,
        "research_only": True,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "next_allowed_command": next_command,
    }
    result["deterministic_result_hash"] = _deterministic_result_hash(result)
    _atomic_write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate membership momentum train PlanOnly/evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--quality-report", required=True)
    plan_parser.add_argument("--expected-quality-hash", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--plan", required=True)
    eval_parser.add_argument("--expected-plan-hash", required=True)
    eval_parser.add_argument("--output", required=True)
    eval_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    args = parser.parse_args()
    if args.command == "plan":
        result = build_train_plan(
            quality_report_path=args.quality_report,
            expected_quality_hash=args.expected_quality_hash,
            output_path=args.output,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = evaluate_train_plan(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
            max_runtime_sec=args.max_runtime_sec,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
