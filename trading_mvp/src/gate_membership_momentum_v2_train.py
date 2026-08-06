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

import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_historical_membership_v3_history_quality as v3_quality
from gate_membership_momentum import (
    DAY_SEC,
    FrozenMomentumConfig,
    MarketSeries,
    RebalanceEvent,
    adjusted_event_funding,
    cost_contract,
    evaluate_rebalance,
    portfolio_metrics,
)


PLAN_SCHEMA = "trading_mvp_gate_membership_momentum_v2_train_plan_v2"
RESULT_SCHEMA = "trading_mvp_gate_membership_momentum_v2_train_evaluation_v2"
PLAN_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_TRAIN_PLAN_READY"
FEASIBLE_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_FEASIBLE_FOR_OOS_PLANONLY"
INFEASIBLE_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_INFEASIBLE_ON_CURRENT_DATA"
INSUFFICIENT_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_INSUFFICIENT_TRAIN_DATA"
STOPPED_INCOMPLETE_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_TRAIN_STOPPED_INCOMPLETE"
MAX_RUNTIME_SEC = 1_800
MINIMUM_REBALANCE_COVERAGE = 0.80
MINIMUM_UNIQUE_ASSETS = 10
HYPOTHESIS_ID = "cross_sectional_momentum_daily_survivorship_repair_v2"
REBALANCE_SCHEDULE_SEMANTICS = "global_train_anchor_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        if _read_json_object(target) != dict(payload):
            raise FileExistsError(f"refusing to overwrite immutable momentum-v2 PlanOnly: {target}")
        return
    _atomic_write_json(target, payload)


def _validate_hash(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"invalid {label}")
    return digest


def train_plan_hash(payload: Mapping[str, Any]) -> str:
    frozen = payload.get("frozen_contract")
    if isinstance(frozen, Mapping):
        return v3_history_plan.sha256_json(frozen)
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "plan_hash"}
        }
    )


def _deterministic_result_hash(payload: Mapping[str, Any]) -> str:
    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: clean(item)
                for key, item in value.items()
                if key
                not in {
                    "generated_at_utc",
                    "runtime_sec",
                    "deterministic_result_hash",
                    "cache_reused",
                }
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return _sha256_json(clean(payload))


def _contains_oos_artifact_path(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if "oos" in normalized and normalized.endswith("_path"):
                return True
            if _contains_oos_artifact_path(item):
                return True
    if isinstance(value, list):
        return any(_contains_oos_artifact_path(item) for item in value)
    return False


def _validate_quality_report(
    path: str | Path,
    *,
    expected_artifact_hash: str,
) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).expanduser().resolve()
    quality = _read_json_object(resolved)
    expected = _validate_hash(expected_artifact_hash, label="quality artifact hash")
    if (
        quality.get("schema") != v3_quality.REPORT_SCHEMA
        or quality.get("final") is not True
        or quality.get("accepted") is not True
        or quality.get("decision") != v3_quality.ACCEPTED_DECISION
        or str(quality.get("artifact_hash") or "") != v3_quality._artifact_hash(quality)
        or str(quality.get("artifact_hash") or "") != expected
    ):
        raise ValueError("membership-v3 history quality report is not hash-valid and accepted")
    if (
        quality.get("next_allowed_command")
        != "create_hash_bound_gate_membership_momentum_v2_train_planonly"
    ):
        raise ValueError("membership-v3 history quality next transition is not momentum-v2 train")
    audit = quality.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(
        audit.get(key) is not False
        for key in ("returns_computed", "pnl_read", "signals_read", "oos_evaluated")
    ):
        raise ValueError("membership-v3 history quality data-access audit is unsafe")
    if any(
        quality.get(key) is not False
        for key in (
            "oos_allowed",
            "grid_allowed",
            "paper_forward_allowed",
            "live_orders",
            "private_api_keys",
            "leverage_or_margin",
        )
    ):
        raise ValueError("membership-v3 history quality permissions are unsafe")
    return quality, resolved


def _validate_train_manifest(path: str | Path, *, expected_hash: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    manifest = _read_json_object(resolved)
    stored = str(manifest.get("artifact_hash") or "")
    if (
        manifest.get("schema") != v3_quality.SPLIT_MANIFEST_SCHEMA
        or manifest.get("stage") != "train_view"
        or manifest.get("sealed") is not False
        or manifest.get("oos_paths_present") is not False
        or manifest.get("point_in_time_universe") is not True
        or manifest.get("historical_universe") is not True
        or manifest.get("lifecycle_mask_applied") is not True
        or manifest.get("no_interpolation") is not True
        or stored != v3_quality._normalized_manifest_hash(manifest)
        or stored != _validate_hash(expected_hash, label="train manifest hash")
    ):
        raise ValueError("unexpected or hash-invalid membership-v3 train manifest")
    range_payload = manifest.get("range")
    if not isinstance(range_payload, Mapping):
        raise ValueError("train manifest range is missing")
    start_sec = int(range_payload.get("start_sec") or 0)
    end_sec = int(range_payload.get("end_sec") or 0)
    expected_days = v3_history_plan.WARMUP_DAYS + v3_history_plan.TRAIN_DAYS
    if (
        start_sec < 0
        or end_sec <= start_sec
        or start_sec % DAY_SEC
        or end_sec % DAY_SEC
        or end_sec - start_sec != expected_days * DAY_SEC
    ):
        raise ValueError("train manifest range does not match frozen membership-v3 train view")

    universe = manifest.get("universe")
    files = manifest.get("normalized_files")
    if not isinstance(universe, list) or not isinstance(files, list):
        raise ValueError("train manifest universe or normalized files are missing")
    if len(universe) < v3_history_plan.MINIMUM_CANONICAL_ASSETS:
        raise ValueError("train manifest has fewer than the frozen minimum canonical assets")
    symbols: set[str] = set()
    asset_ids: set[str] = set()
    for raw in universe:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid train universe row")
        symbol = str(raw.get("symbol") or "")
        asset_id = str(raw.get("canonical_asset_id") or "")
        if not symbol or symbol in symbols or not asset_id or asset_id in asset_ids:
            raise ValueError("train universe identity is missing or duplicated")
        symbols.add(symbol)
        asset_ids.add(asset_id)
        listed_to = raw.get("listed_to_ts")
        resolved_end = raw.get("resolved_lifecycle_end_sec")
        if listed_to is not None and int(listed_to) > end_sec:
            raise ValueError("train manifest exposes a future lifecycle end")
        if resolved_end is not None and int(resolved_end) > end_sec:
            raise ValueError("train manifest exposes a future lifecycle resolution")
        if listed_to is None and raw.get("is_delisted") is True:
            raise ValueError("train lifecycle mask is internally inconsistent")

    root = resolved.parent
    file_symbols: set[str] = set()
    for raw in files:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid train normalized file record")
        symbol = str(raw.get("symbol") or "")
        if not symbol or symbol in file_symbols:
            raise ValueError("train normalized file symbol is missing or duplicated")
        file_symbols.add(symbol)
        for path_key, hash_key in (
            ("kline_path", "kline_sha256"),
            ("funding_path", "funding_sha256"),
        ):
            target = Path(str(raw.get(path_key) or "")).expanduser().resolve()
            if not target.is_file() or not target.is_relative_to(root):
                raise ValueError(f"train artifact escapes train root: {path_key}")
            if v3_history_plan.sha256_file(target) != _validate_hash(
                raw.get(hash_key), label=hash_key
            ):
                raise ValueError(f"train artifact hash mismatch: {path_key}")
    if file_symbols != symbols:
        raise ValueError("train universe and normalized file inventories differ")
    return manifest


def _first_scheduled_day_at_or_after(
    *,
    anchor_day: int,
    lower_bound_day: int,
    cadence_days: int,
) -> int:
    anchor = int(anchor_day)
    lower = int(lower_bound_day)
    cadence = int(cadence_days)
    if cadence < 1:
        raise ValueError("rebalance cadence must be positive")
    if lower <= anchor:
        return anchor
    return anchor + ((lower - anchor + cadence - 1) // cadence) * cadence


def _scheduled_signal_days(
    *,
    anchor_day: int,
    start_day: int,
    end_day: int,
    cadence_days: int,
) -> list[int]:
    start = int(start_day)
    end = int(end_day)
    if end <= start:
        return []
    first = _first_scheduled_day_at_or_after(
        anchor_day=anchor_day,
        lower_bound_day=start,
        cadence_days=cadence_days,
    )
    return list(range(first, end, int(cadence_days))) if first < end else []


def _build_rebalance_schedule_contract(
    *,
    start_sec: int,
    end_sec: int,
    config: FrozenMomentumConfig,
) -> dict[str, Any]:
    if (
        int(start_sec) < 0
        or int(end_sec) <= int(start_sec)
        or int(start_sec) % DAY_SEC
        or int(end_sec) % DAY_SEC
    ):
        raise ValueError("rebalance schedule requires a positive UTC-aligned range")
    start_day = int(start_sec) // DAY_SEC
    end_day = int(end_sec) // DAY_SEC
    anchor_day = start_day + config.lookback_days
    last_signal = end_day - config.hold_days - 2
    all_view_signals = _scheduled_signal_days(
        anchor_day=anchor_day,
        start_day=anchor_day,
        end_day=end_day,
        cadence_days=config.rebalance_every_days,
    )
    eligible_signal_days = _scheduled_signal_days(
        anchor_day=anchor_day,
        start_day=anchor_day,
        end_day=last_signal + 1,
        cadence_days=config.rebalance_every_days,
    )
    eligible_set = set(eligible_signal_days)
    boundary_excluded = [day for day in all_view_signals if day not in eligible_set]
    return {
        "semantics": REBALANCE_SCHEDULE_SEMANTICS,
        "anchor_source": "train_manifest_start_day_plus_strategy_lookback_days",
        "anchor_day": anchor_day,
        "anchor_ts": anchor_day * DAY_SEC,
        "cadence_days": config.rebalance_every_days,
        "eligible_signal_days": eligible_signal_days,
        "boundary_excluded_signal_days": boundary_excluded,
        "next_scheduled_signal_day_at_or_after_view_end": _first_scheduled_day_at_or_after(
            anchor_day=anchor_day,
            lower_bound_day=end_day,
            cadence_days=config.rebalance_every_days,
        ),
    }


def _theoretical_rebalance_count(
    *,
    start_sec: int,
    end_sec: int,
    config: FrozenMomentumConfig,
) -> int:
    return len(
        _build_rebalance_schedule_contract(
            start_sec=start_sec,
            end_sec=end_sec,
            config=config,
        )["eligible_signal_days"]
    )


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
    quality, quality_path = _validate_quality_report(
        quality_report_path,
        expected_artifact_hash=expected_quality_hash,
    )
    train_manifest_path = Path(str(quality.get("train_manifest_path") or "")).expanduser().resolve()
    train_manifest_hash = _validate_hash(
        quality.get("train_manifest_hash"), label="train manifest hash"
    )
    train_manifest = _validate_train_manifest(
        train_manifest_path,
        expected_hash=train_manifest_hash,
    )
    config = FrozenMomentumConfig()
    strategy = config.as_dict()
    if (
        config.lookback_days != 30
        or config.hold_days != 7
        or config.rebalance_every_days != 7
    ):
        raise ValueError("momentum core no longer matches frozen weekly 30/7/7 hypothesis")
    start_sec = int(train_manifest["range"]["start_sec"])
    end_sec = int(train_manifest["range"]["end_sec"])
    schedule = _build_rebalance_schedule_contract(
        start_sec=start_sec,
        end_sec=end_sec,
        config=config,
    )
    theoretical = len(schedule["eligible_signal_days"])
    minimum_rebalances = math.ceil(theoretical * MINIMUM_REBALANCE_COVERAGE)
    if theoretical < 1 or minimum_rebalances < 1:
        raise ValueError("frozen train view cannot produce any independent rebalances")
    costs = cost_contract()
    module_paths = {
        "module": Path(__file__).resolve(),
        "core_module": Path(__import__("gate_membership_momentum").__file__).resolve(),
        "quality_module": Path(v3_quality.__file__).resolve(),
        "history_plan_module": Path(v3_history_plan.__file__).resolve(),
    }
    quality_hash = _validate_hash(expected_quality_hash, label="quality artifact hash")
    oos_commitment = _validate_hash(
        quality.get("oos_commitment_hash"), label="OOS commitment hash"
    )
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    contract: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": "gate_membership_momentum_v2_train_planonly",
        "stage": "train_feasibility",
        "decision": PLAN_DECISION,
        "hypothesis_id": HYPOTHESIS_ID,
        "research_only": True,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "oos_allowed_now": False,
        "oos_read": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "strategy": strategy,
        "rebalance_schedule_contract": schedule,
        "strategy_provenance": {
            "setup_id": "cross_sectional_momentum_daily",
            "parameter_source": "preexisting_hypothesis_bank_and_legacy_frozen_contract",
            "parameters_changed_for_v2": False,
            "data_contract_change_only": True,
        },
        "cost_contract": costs,
        "train_input": {
            "manifest_path": str(train_manifest_path),
            "manifest_sha256": v3_history_plan.sha256_file(train_manifest_path),
            "manifest_hash": train_manifest_hash,
            "range": {"start_sec": start_sec, "end_sec": end_sec},
            "quality_report_sha256": v3_history_plan.sha256_file(quality_path),
            "quality_artifact_hash": quality_hash,
            "quality_plan_hash": _validate_hash(
                quality.get("plan_hash"), label="quality plan hash"
            ),
            "history_plan_hash": _validate_hash(
                quality.get("history_plan_hash"), label="history plan hash"
            ),
            "collect_artifact_hash": _validate_hash(
                quality.get("collect_artifact_hash"), label="collect artifact hash"
            ),
            "normalized_manifest_hash": _validate_hash(
                quality.get("normalized_manifest_hash"), label="normalized manifest hash"
            ),
        },
        "oos_commitment_hash": oos_commitment,
        "sample_capacity": {
            "train_view_days": (end_sec - start_sec) // DAY_SEC,
            "contract_warmup_days": v3_history_plan.WARMUP_DAYS,
            "contract_train_days": v3_history_plan.TRAIN_DAYS,
            "strategy_lookback_days": config.lookback_days,
            "effective_signal_span_days": (end_sec - start_sec) // DAY_SEC
            - config.lookback_days,
            "theoretical_max_independent_rebalances": theoretical,
            "minimum_rebalance_coverage": MINIMUM_REBALANCE_COVERAGE,
            "minimum_independent_rebalances": minimum_rebalances,
            "limited_statistical_power": theoretical < 20,
        },
        "train_gates": {
            "minimum_independent_rebalances": minimum_rebalances,
            "minimum_unique_assets_traded": MINIMUM_UNIQUE_ASSETS,
            "price_only_net_expectancy_bps_gt": 0.0,
            "total_net_expectancy_bps_gt": 0.0,
            "profit_factor_gte": 1.1,
            "stress_total_net_expectancy_bps_gte": 0.0,
            "maximum_drawdown_pct": 15.0,
            "maximum_top_base_positive_share": 0.35,
            "maximum_top_rebalance_positive_share": 0.35,
        },
        "code_provenance": code_provenance,
        "runtime_contract": {
            "max_runtime_sec": runtime,
            "visible_terminal_required": True,
            "local_immutable_inputs_only": True,
            "timeout_verdict": STOPPED_INCOMPLETE_DECISION,
        },
        "data_access_audit": {
            "quality_report_opened": True,
            "train_manifest_opened_for_metadata": True,
            "train_returns_read": False,
            "oos_paths_available": False,
            "oos_files_opened": False,
        },
        "next_allowed_command": "fast-edge-membership-momentum-v2-train",
        "blocked_actions": [
            "oos_before_train_feasibility",
            "grid_search",
            "retune",
            "execution_probe",
            "paper_forward",
            "live_orders",
            "private_api_keys",
        ],
        "limitations": [
            f"The frozen 120-day train view can produce at most {theoretical} globally anchored non-overlapping weekly rebalances.",
            "Train feasibility is necessary but cannot establish historical acceptance.",
            "Gate-only history does not establish MEXC portability or executable capacity.",
        ],
    }
    if _contains_oos_artifact_path(contract):
        raise ValueError("momentum-v2 train PlanOnly exposes an OOS artifact path")
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "quality_artifact_hash": quality_hash,
            "quality_report_sha256": contract["train_input"]["quality_report_sha256"],
            "train_manifest_hash": train_manifest_hash,
            "train_manifest_sha256": contract["train_input"]["manifest_sha256"],
            "oos_commitment_hash": oos_commitment,
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = v3_history_plan.sha256_json(contract)
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": plan_hash,
        "frozen_contract": contract,
    }
    if output_path is not None:
        _write_json_immutable(output_path, payload)
    return payload


def authorize_train_evaluation(
    plan_path: str | Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    resolved = Path(plan_path).expanduser().resolve()
    plan = _read_json_object(resolved)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected momentum-v2 train PlanOnly artifact")
    if not isinstance(frozen, Mapping):
        raise ValueError("momentum-v2 train frozen contract is missing")
    computed = v3_history_plan.sha256_json(frozen)
    if (
        str(plan.get("plan_hash") or "") != computed
        or str(expected_plan_hash) != computed
        or not all(plan.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 train plan hash mismatch")
    if plan.get("next_allowed_command") != "fast-edge-membership-momentum-v2-train":
        raise ValueError("momentum-v2 train evaluation is not the next allowed command")
    if (
        plan.get("oos_allowed_now") is not False
        or plan.get("oos_read") is not False
        or _contains_oos_artifact_path(plan)
    ):
        raise ValueError("momentum-v2 train PlanOnly violates the OOS embargo")
    code = plan.get("code_provenance")
    expected_paths = {
        "module": Path(__file__).resolve(),
        "core_module": Path(__import__("gate_membership_momentum").__file__).resolve(),
        "quality_module": Path(v3_quality.__file__).resolve(),
        "history_plan_module": Path(v3_history_plan.__file__).resolve(),
    }
    if not isinstance(code, Mapping):
        raise ValueError("momentum-v2 train code provenance is missing")
    for name, expected_path in expected_paths.items():
        actual = Path(str(code.get(f"{name}_path") or "")).expanduser().resolve()
        if (
            actual != expected_path
            or not actual.is_file()
            or code.get(f"{name}_sha256") != v3_history_plan.sha256_file(actual)
        ):
            raise ValueError(f"momentum-v2 train module hash mismatch: {expected_path.name}")
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
            raise ValueError("invalid train normalized file record")
        symbol = str(record.get("symbol") or "")
        item = by_symbol.get(symbol)
        if item is None:
            raise ValueError(f"train universe/file mismatch: {symbol}")
        kline_path = Path(str(record.get("kline_path") or "")).expanduser().resolve()
        funding_path = Path(str(record.get("funding_path") or "")).expanduser().resolve()
        if not kline_path.is_relative_to(manifest_path.parent) or not funding_path.is_relative_to(
            manifest_path.parent
        ):
            raise ValueError("train evaluator refuses artifacts outside train root")
        kline = _read_json_object(kline_path)
        funding = _read_json_object(funding_path)
        if (
            kline.get("schema") != "trading_mvp_daily_ohlcv_v1"
            or kline.get("exchange") != "gateio"
            or kline.get("symbol") != symbol
        ):
            raise ValueError(f"unexpected train kline identity: {symbol}")
        if (
            funding.get("schema") != "trading_mvp_funding_settlements_v1"
            or funding.get("exchange") != "gateio"
            or funding.get("symbol") != symbol
        ):
            raise ValueError(f"unexpected train funding identity: {symbol}")
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
                raise ValueError(f"non-day-aligned train kline: {symbol}")
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


def _event_net_return(
    event: RebalanceEvent,
    *,
    cost_bps: float,
    favorable_multiplier: float,
) -> float:
    return (
        event.price_return
        + adjusted_event_funding(event, favorable_multiplier)
        - float(cost_bps) / 10_000.0
    )


def _top_positive_share(values: list[float]) -> float:
    positive = [value for value in values if value > 0.0]
    total = sum(positive)
    return max(positive) / total if total > 0.0 else 1.0


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
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = authorize_train_evaluation(resolved_plan, expected_plan_hash)
    train_input = plan["train_input"]
    manifest_path = Path(str(train_input["manifest_path"])).expanduser().resolve()
    if v3_history_plan.sha256_file(manifest_path) != str(train_input["manifest_sha256"]):
        raise ValueError("momentum-v2 train manifest file hash mismatch")
    manifest = _validate_train_manifest(
        manifest_path,
        expected_hash=str(train_input["manifest_hash"]),
    )
    markets = _load_markets(manifest, manifest_path)
    config = FrozenMomentumConfig(
        lookback_days=int(plan["strategy"]["lookback_days"]),
        hold_days=int(plan["strategy"]["hold_days"]),
        rebalance_every_days=int(plan["strategy"]["rebalance_every_days"]),
        min_per_side=int(plan["strategy"]["min_per_side"]),
        minimum_scored_markets=int(plan["strategy"]["minimum_scored_markets"]),
        liquidity_lookback_days=int(plan["strategy"]["liquidity_lookback_days"]),
        minimum_median_quote_volume=float(
            plan["strategy"]["minimum_median_quote_volume"]
        ),
    )
    expected_schedule = _build_rebalance_schedule_contract(
        start_sec=int(manifest["range"]["start_sec"]),
        end_sec=int(manifest["range"]["end_sec"]),
        config=config,
    )
    if plan.get("rebalance_schedule_contract") != expected_schedule:
        raise ValueError("momentum-v2 train rebalance schedule contract mismatch")
    events: list[RebalanceEvent] = []
    try:
        for signal_day in expected_schedule["eligible_signal_days"]:
            if time.monotonic() - started >= runtime:
                raise TimeoutError("membership momentum-v2 train runtime exhausted")
            event = evaluate_rebalance(markets, signal_day=signal_day, config=config)
            if event is not None:
                events.append(event)
    except Exception as exc:
        stopped: dict[str, Any] = {
            "schema": RESULT_SCHEMA,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "run_id": plan["run_id"],
            "plan_hash": expected_plan_hash,
            "stage": "train_feasibility",
            "final": False,
            "decision": STOPPED_INCOMPLETE_DECISION,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "runtime_sec": time.monotonic() - started,
            "research_only": True,
            "oos_read": False,
            "live_orders": False,
            "private_api_keys": False,
            "next_allowed_command": "fast-edge-membership-momentum-v2-train",
        }
        stopped["deterministic_result_hash"] = _deterministic_result_hash(stopped)
        _atomic_write_json(output_path, stopped)
        raise

    costs = plan["cost_contract"]
    normal_cost = float(costs["normal"]["total_bps"])
    stress_cost = float(costs["stress"]["total_bps"])
    normal = portfolio_metrics(
        events,
        cost_bps=normal_cost,
        favorable_funding_multiplier=1.0,
    )
    stress = portfolio_metrics(
        events,
        cost_bps=stress_cost,
        favorable_funding_multiplier=0.0,
    )
    normal_returns = [
        _event_net_return(event, cost_bps=normal_cost, favorable_multiplier=1.0)
        for event in events
    ]
    top_rebalance_share = _top_positive_share(normal_returns)
    gates = plan["train_gates"]
    sample_reasons: list[str] = []
    if int(normal.get("independent_rebalances") or 0) < int(
        gates["minimum_independent_rebalances"]
    ):
        sample_reasons.append("insufficient_independent_rebalances")
    if int(normal.get("unique_assets_traded") or 0) < int(
        gates["minimum_unique_assets_traded"]
    ):
        sample_reasons.append("insufficient_unique_assets_traded")
    economic_reasons: list[str] = []
    if float(normal.get("price_only_net_expectancy_bps") or 0.0) <= float(
        gates["price_only_net_expectancy_bps_gt"]
    ):
        economic_reasons.append("price_only_net_expectancy_not_positive")
    if float(normal.get("total_net_expectancy_bps") or 0.0) <= float(
        gates["total_net_expectancy_bps_gt"]
    ):
        economic_reasons.append("total_net_expectancy_not_positive")
    if not _profit_factor_pass(normal, float(gates["profit_factor_gte"])):
        economic_reasons.append("profit_factor_below_minimum")
    if float(stress.get("total_net_expectancy_bps") or 0.0) < float(
        gates["stress_total_net_expectancy_bps_gte"]
    ):
        economic_reasons.append("stress_net_expectancy_negative")
    if float(normal.get("max_drawdown_pct") or 0.0) > float(
        gates["maximum_drawdown_pct"]
    ):
        economic_reasons.append("max_drawdown_above_limit")
    if float(normal.get("top_base_positive_share") or 0.0) > float(
        gates["maximum_top_base_positive_share"]
    ):
        economic_reasons.append("top_base_concentration_above_limit")
    if top_rebalance_share > float(gates["maximum_top_rebalance_positive_share"]):
        economic_reasons.append("top_rebalance_concentration_above_limit")

    if sample_reasons:
        decision = INSUFFICIENT_DECISION
        reasons = sample_reasons
        next_command = "none_membership_momentum_v2_branch_closed_insufficient_data"
    elif economic_reasons:
        decision = INFEASIBLE_DECISION
        reasons = economic_reasons
        next_command = "none_membership_momentum_v2_branch_closed_no_retune"
    else:
        decision = FEASIBLE_DECISION
        reasons = []
        next_command = "create_hash_bound_gate_membership_momentum_v2_oos_planonly"
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": plan["run_id"],
        "plan_hash": expected_plan_hash,
        "stage": "train_feasibility",
        "final": True,
        "decision": decision,
        "rejection_reasons": reasons,
        "normal_metrics": normal,
        "stress_metrics": stress,
        "rebalance_schedule_contract": expected_schedule,
        "top_rebalance_positive_share": round(top_rebalance_share, 8),
        "sample_capacity": plan["sample_capacity"],
        "events": [
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
        ],
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
        "limitations": plan["limitations"],
    }
    if _contains_oos_artifact_path(result):
        raise ValueError("momentum-v2 train result exposes an OOS artifact path")
    result["deterministic_result_hash"] = _deterministic_result_hash(result)
    _atomic_write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate membership-v3 momentum-v2 train PlanOnly/evaluator"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--quality-report", required=True)
    plan_parser.add_argument("--expected-quality-hash", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--expected-plan-hash", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
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
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
