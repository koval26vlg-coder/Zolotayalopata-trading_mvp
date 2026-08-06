from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_membership_momentum as momentum
import gate_membership_momentum_v2_execution_probe as probe
import gate_membership_momentum_v2_train as v2_train
from gate_membership_momentum import DAY_SEC


MARKET_SNAPSHOT_SCHEMA = (
    "trading_mvp_gate_membership_momentum_v2_execution_market_snapshot_v1"
)
MARKET_SNAPSHOT_READY_DECISION = (
    "GATE_MEMBERSHIP_MOMENTUM_V2_EXECUTION_MARKET_SNAPSHOT_READY"
)
SELECTION_SCHEMA = "trading_mvp_gate_membership_momentum_v2_execution_selection_v1"
SELECTION_READY_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_EXECUTION_SELECTION_READY"
INSUFFICIENT_UNIVERSE_DECISION = "INSUFFICIENT_EXECUTABLE_UNIVERSE"
READY_NEXT_COMMAND = "fast-edge-membership-momentum-v2-execution-probe-window-plan"
CLOSED_NEXT_COMMAND = "none_membership_momentum_v2_branch_closed_no_retune"


def market_snapshot_hash(payload: Mapping[str, Any]) -> str:
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_hash", "generated_at_utc"}
        }
    )


def selection_artifact_hash(payload: Mapping[str, Any]) -> str:
    frozen = payload.get("frozen_contract")
    if isinstance(frozen, Mapping):
        return v3_history_plan.sha256_json(frozen)
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_hash", "generated_at_utc"}
        }
    )


def _parse_utc(value: str, *, label: str) -> float:
    raw = str(value).strip()
    if not raw:
        raise ValueError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.timestamp()


def _validate_market_snapshot(
    path: str | Path,
    expected_hash: str,
) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).expanduser().resolve()
    payload = v2_train._read_json_object(resolved)
    normalized_hash = v2_train._validate_hash(expected_hash, label="market snapshot hash")
    if (
        payload.get("schema") != MARKET_SNAPSHOT_SCHEMA
        or payload.get("final") is not True
        or payload.get("decision") != MARKET_SNAPSHOT_READY_DECISION
        or payload.get("exchange") != "gateio"
        or payload.get("market_type") != "usdt_linear_perpetual"
        or payload.get("public_data_only") is not True
        or payload.get("private_api_keys") is not False
        or payload.get("live_orders") is not False
        or payload.get("artifact_hash") != normalized_hash
        or market_snapshot_hash(payload) != normalized_hash
    ):
        raise ValueError("market snapshot is not a hash-valid public Gate daily manifest")
    rows = payload.get("rows")
    audit = payload.get("data_access_audit")
    if not isinstance(rows, list) or not isinstance(audit, Mapping):
        raise ValueError("market snapshot rows/data-access audit is missing")
    if (
        audit.get("oos_events_used_for_selection") is not False
        or audit.get("future_bars_read") is not False
        or audit.get("manual_shortlist") is not False
    ):
        raise ValueError("market snapshot violates the causal selection contract")
    as_of_ts = int(payload.get("as_of_ts") or 0)
    if as_of_ts <= 0 or int(_parse_utc(str(payload.get("as_of_utc") or ""), label="as_of_utc")) != as_of_ts:
        raise ValueError("market snapshot as-of timestamp mismatch")
    return payload, resolved


def _score_snapshot_rows(
    rows: list[Any],
    *,
    signal_day: int,
    strategy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lookback_days = int(strategy["lookback_days"])
    liquidity_days = int(strategy["liquidity_lookback_days"])
    minimum_volume = float(strategy["minimum_median_quote_volume"])
    seen_assets: set[str] = set()
    seen_symbols: set[str] = set()
    seen_bases: set[str] = set()
    scored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("market snapshot row must be a JSON object")
        canonical_id = str(raw.get("canonical_asset_id") or "").strip()
        symbol = str(raw.get("symbol") or "").strip().upper()
        base = str(raw.get("base") or "").strip().upper()
        if not canonical_id or not symbol or not base:
            raise ValueError("market snapshot row identity is incomplete")
        if canonical_id in seen_assets or symbol in seen_symbols or base in seen_bases:
            raise ValueError("market snapshot contains duplicate canonical identity")
        seen_assets.add(canonical_id)
        seen_symbols.add(symbol)
        seen_bases.add(base)
        if raw.get("exchange") != "gateio" or raw.get("market_type") != "usdt_linear_perpetual":
            raise ValueError("market snapshot row venue/instrument mismatch")

        eligibility_reasons: list[str] = []
        if raw.get("identity_confirmed") is not True:
            eligibility_reasons.append("canonical_identity_not_confirmed")
        if raw.get("binance_spot_excluded") is not True:
            eligibility_reasons.append("binance_spot_exclusion_failed")
        if raw.get("prohibited_asset_class") is not False:
            eligibility_reasons.append("prohibited_asset_class")
        if raw.get("lifecycle_valid_at_signal") is not True:
            eligibility_reasons.append("lifecycle_invalid_at_signal")
        if raw.get("status") != "tradable":
            eligibility_reasons.append("not_tradable_at_signal")

        bars = raw.get("bars")
        if not isinstance(bars, list):
            raise ValueError("market snapshot bars must be a list")
        by_day: dict[int, tuple[float, float]] = {}
        previous_ts: int | None = None
        for bar in bars:
            if not isinstance(bar, Mapping):
                raise ValueError("market snapshot daily bar must be a JSON object")
            timestamp = int(bar.get("ts") or -1)
            if (
                timestamp < 0
                or timestamp % DAY_SEC
                or (previous_ts is not None and timestamp <= previous_ts)
            ):
                raise ValueError("market snapshot daily bars are not strictly UTC ordered")
            if timestamp > signal_day * DAY_SEC or bar.get("closed") is not True:
                raise ValueError("market snapshot contains a future or open daily bar")
            previous_ts = timestamp
            day = timestamp // DAY_SEC
            close = float(bar.get("close") or 0.0)
            volume = float(bar.get("volume_quote") or 0.0)
            if not math.isfinite(close) or not math.isfinite(volume) or close <= 0.0 or volume < 0.0:
                raise ValueError("market snapshot contains an invalid daily value")
            by_day[day] = (close, volume)

        lookback = by_day.get(signal_day - lookback_days)
        current = by_day.get(signal_day)
        volumes = [
            by_day.get(day, (0.0, 0.0))[1]
            for day in range(signal_day - liquidity_days + 1, signal_day + 1)
        ]
        if lookback is None or current is None or any(value <= 0.0 for value in volumes):
            eligibility_reasons.append("insufficient_closed_daily_history")
        median_volume = float(statistics.median(volumes)) if volumes else 0.0
        if median_volume < minimum_volume:
            eligibility_reasons.append("minimum_median_quote_volume_failed")
        if eligibility_reasons:
            rejected.append(
                {
                    "canonical_asset_id": canonical_id,
                    "symbol": symbol,
                    "base": base,
                    "reasons": sorted(set(eligibility_reasons)),
                }
            )
            continue
        assert lookback is not None and current is not None
        score = current[0] / lookback[0] - 1.0
        if not math.isfinite(score):
            raise ValueError("market snapshot produced a non-finite momentum score")
        scored.append(
            {
                "canonical_asset_id": canonical_id,
                "symbol": symbol,
                "base": base,
                "momentum_score": score,
                "lookback_close": lookback[0],
                "signal_close": current[0],
                "median_quote_volume": median_volume,
            }
        )

    scored.sort(
        key=lambda row: (
            float(row["momentum_score"]),
            str(row["canonical_asset_id"]),
            str(row["symbol"]),
        )
    )
    rejected.sort(key=lambda row: (row["canonical_asset_id"], row["symbol"]))
    return scored, rejected


def _selected_positions(
    scored: list[dict[str, Any]],
    *,
    minimum_scored_markets: int,
    minimum_assets_per_side: int,
) -> tuple[list[dict[str, Any]], int]:
    if len(scored) < minimum_scored_markets:
        return [], 0
    bucket = max(minimum_assets_per_side, len(scored) // 10)
    short_rows = scored[:bucket]
    long_rows = scored[-bucket:]
    if {row["canonical_asset_id"] for row in short_rows} & {
        row["canonical_asset_id"] for row in long_rows
    }:
        raise ValueError("causal momentum long/short buckets overlap")
    return (
        [dict(row, side="short") for row in short_rows]
        + [dict(row, side="long") for row in long_rows],
        bucket,
    )


def build_selection_artifact(
    *,
    probe_plan_path: str | Path,
    expected_probe_plan_hash: str,
    market_snapshot_manifest_path: str | Path,
    expected_market_snapshot_hash: str,
    output_path: str | Path | None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    resolved_probe = Path(probe_plan_path).expanduser().resolve()
    probe_plan = probe.validate_execution_probe_plan(
        resolved_probe,
        v2_train._validate_hash(expected_probe_plan_hash, label="execution probe plan hash"),
    )
    if probe_plan.get("next_allowed_command") != "fast-edge-membership-momentum-v2-execution-selection":
        raise ValueError("execution probe PlanOnly does not authorize causal selection")
    snapshot, resolved_snapshot = _validate_market_snapshot(
        market_snapshot_manifest_path,
        expected_market_snapshot_hash,
    )
    target = probe_plan["target_event_contract"]
    execution = probe_plan["execution_contract"]
    signal_day = int(target["target_signal_day"])
    signal_close_ts = int(target["target_signal_close_ts"])
    first_window_ts = int(execution["windows"][0]["start_ts"])
    as_of_ts = int(snapshot["as_of_ts"])
    if int(snapshot.get("target_signal_day") or -1) != signal_day:
        raise ValueError("market snapshot target signal day mismatch")
    if as_of_ts < signal_close_ts:
        raise ValueError("market snapshot predates the target signal close")
    if as_of_ts >= first_window_ts:
        raise ValueError("market snapshot was not frozen before the first execution window")

    generated = generated_at_utc or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    generated_ts = _parse_utc(generated, label="generated_at_utc")
    if generated_ts < signal_close_ts:
        raise ValueError("selection cannot be created before the target signal close")
    if generated_ts >= first_window_ts:
        raise ValueError("selection must be frozen before the first execution window")
    if generated_ts < as_of_ts:
        raise ValueError("selection timestamp predates its market snapshot")

    strategy = probe_plan["strategy"]
    scored, rejected = _score_snapshot_rows(
        snapshot["rows"],
        signal_day=signal_day,
        strategy=strategy,
    )
    minimum_markets = int(strategy["minimum_scored_markets"])
    minimum_per_side = int(strategy["min_per_side"])
    selected, bucket = _selected_positions(
        scored,
        minimum_scored_markets=minimum_markets,
        minimum_assets_per_side=minimum_per_side,
    )
    ready = len(scored) >= minimum_markets
    decision = SELECTION_READY_DECISION if ready else INSUFFICIENT_UNIVERSE_DECISION
    next_command = READY_NEXT_COMMAND if ready else CLOSED_NEXT_COMMAND

    module_paths = {
        "module": Path(__file__).resolve(),
        "probe_module": Path(probe.__file__).resolve(),
        "momentum_module": Path(momentum.__file__).resolve(),
        "train_module": Path(v2_train.__file__).resolve(),
    }
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    probe_file_hash = v3_history_plan.sha256_file(resolved_probe)
    snapshot_file_hash = v3_history_plan.sha256_file(resolved_snapshot)
    selection_contract = {
        **dict(probe_plan["selection_contract"]),
        "target_signal_day": signal_day,
        "target_signal_close_ts": signal_close_ts,
        "snapshot_as_of_ts": as_of_ts,
        "selection_generated_ts": int(generated_ts),
        "selection_frozen_before_first_snapshot": generated_ts < first_window_ts,
        "ranking": "momentum_ascending_then_canonical_asset_id_then_symbol",
        "short_bucket": "lowest_momentum",
        "long_bucket": "highest_momentum",
        "threshold_weakening_allowed": False,
    }
    contract: dict[str, Any] = {
        "schema": SELECTION_SCHEMA,
        "final": True,
        "stage": "execution_probe_causal_selection",
        "decision": decision,
        "hypothesis_id": probe_plan["hypothesis_id"],
        "research_only": True,
        "network_access": False,
        "public_data_only": True,
        "grid_search": False,
        "retune": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "probe_plan_authorization": {
            "path": str(resolved_probe),
            "file_sha256": probe_file_hash,
            "plan_hash": probe_plan["plan_hash"],
            "decision": probe.PLAN_DECISION,
        },
        "market_snapshot_authorization": {
            "path": str(resolved_snapshot),
            "file_sha256": snapshot_file_hash,
            "artifact_hash": snapshot["artifact_hash"],
            "as_of_ts": as_of_ts,
            "decision": MARKET_SNAPSHOT_READY_DECISION,
        },
        "target_event_contract": dict(target),
        "selection_contract": selection_contract,
        "execution_contract": dict(execution),
        "selection_summary": {
            "input_markets": len(snapshot["rows"]),
            "scored_markets": len(scored),
            "rejected_markets": len(rejected),
            "minimum_scored_markets": minimum_markets,
            "assets_per_side": bucket,
        },
        "scored_universe": scored,
        "rejected_universe": rejected,
        "selected_positions": selected,
        "execution_probe_collect_allowed": ready,
        "data_access_audit": {
            "market_snapshot_read": True,
            "closed_daily_prices_read": True,
            "oos_events_used_for_selection": False,
            "oos_event_asset_names_used": False,
            "future_bars_read": False,
            "manual_shortlist": False,
            "network_access": False,
        },
        "code_provenance": code_provenance,
        "maximum_authority": (
            "EXECUTION_PROBE_COLLECT" if ready else "BRANCH_CLOSED_INSUFFICIENT_UNIVERSE"
        ),
        "next_allowed_command": next_command,
        "blocked_actions": [
            "manual_shortlist",
            "threshold_weakening",
            "grid_search",
            "retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
        "limitations": [
            "Selection is based only on closed point-in-time Gate daily data.",
            "Selection does not prove executable fill, impact, or capacity.",
            "This artifact grants no paper-forward or live authority.",
        ],
    }
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "probe_plan_hash": probe_plan["plan_hash"],
            "probe_plan_file_sha256": probe_file_hash,
            "market_snapshot_hash": snapshot["artifact_hash"],
            "market_snapshot_file_sha256": snapshot_file_hash,
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    artifact_hash = v3_history_plan.sha256_json(contract)
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated,
        "artifact_hash": artifact_hash,
        "frozen_contract": contract,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, payload)
    return payload


def validate_selection_artifact(
    path: str | Path,
    expected_artifact_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    payload = v2_train._read_json_object(resolved)
    frozen = payload.get("frozen_contract")
    if payload.get("schema") != SELECTION_SCHEMA or not isinstance(frozen, Mapping):
        raise ValueError("unexpected momentum-v2 execution selection artifact")
    computed_hash = v3_history_plan.sha256_json(frozen)
    if (
        payload.get("artifact_hash") != computed_hash
        or (expected_artifact_hash is not None and str(expected_artifact_hash) != computed_hash)
        or not all(payload.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 execution selection artifact hash mismatch")
    probe_auth = payload.get("probe_plan_authorization")
    snapshot_auth = payload.get("market_snapshot_authorization")
    if not isinstance(probe_auth, Mapping) or not isinstance(snapshot_auth, Mapping):
        raise ValueError("momentum-v2 execution selection authorization is missing")
    probe_path = Path(str(probe_auth.get("path") or "")).expanduser().resolve()
    snapshot_path = Path(str(snapshot_auth.get("path") or "")).expanduser().resolve()
    if (
        v3_history_plan.sha256_file(probe_path) != probe_auth.get("file_sha256")
        or v3_history_plan.sha256_file(snapshot_path) != snapshot_auth.get("file_sha256")
    ):
        raise ValueError("momentum-v2 execution selection source file hash mismatch")
    rebuilt = build_selection_artifact(
        probe_plan_path=probe_path,
        expected_probe_plan_hash=str(probe_auth.get("plan_hash") or ""),
        market_snapshot_manifest_path=snapshot_path,
        expected_market_snapshot_hash=str(snapshot_auth.get("artifact_hash") or ""),
        output_path=None,
        generated_at_utc=str(payload.get("generated_at_utc") or ""),
    )
    if (
        rebuilt["artifact_hash"] != computed_hash
        or rebuilt["frozen_contract"] != frozen
        or rebuilt["selected_positions"] != payload.get("selected_positions")
    ):
        raise ValueError("momentum-v2 execution selection does not match deterministic source selection")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate membership momentum-v2 causal execution selection"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--probe-plan", required=True)
    select_parser.add_argument("--expected-probe-plan-hash", required=True)
    select_parser.add_argument("--market-snapshot-manifest", required=True)
    select_parser.add_argument("--expected-market-snapshot-hash", required=True)
    select_parser.add_argument("--output", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--selection", required=True)
    validate_parser.add_argument("--expected-artifact-hash")
    args = parser.parse_args()

    if args.command == "select":
        result = build_selection_artifact(
            probe_plan_path=args.probe_plan,
            expected_probe_plan_hash=args.expected_probe_plan_hash,
            market_snapshot_manifest_path=args.market_snapshot_manifest,
            expected_market_snapshot_hash=args.expected_market_snapshot_hash,
            output_path=args.output,
        )
    else:
        artifact = validate_selection_artifact(
            args.selection,
            args.expected_artifact_hash,
        )
        result = {
            "schema": "trading_mvp_gate_membership_momentum_v2_execution_selection_validation_v1",
            "valid": True,
            "selection_path": str(Path(args.selection).expanduser().resolve()),
            "artifact_hash": artifact["artifact_hash"],
            "decision": artifact["decision"],
            "next_allowed_command": artifact["next_allowed_command"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
