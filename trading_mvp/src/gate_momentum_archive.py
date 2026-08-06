from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from gate_futures_archive import (
    ARCHIVE_PLAN_SCHEMA,
    DATASET_TYPES,
    DEFAULT_CREDENTIAL_ENV,
    MAX_HEADER_BYTES,
    MAX_HEADER_DOWNLOAD_BYTES,
    build_schema_probe_descriptor,
    sha256_file,
    validate_dataset_header,
    validate_archive_source_plan,
)


PLAN_SCHEMA = "trading_mvp_gate_momentum_tardis_archive_plan_v1"
ACTIONABILITY_SCHEMA = "trading_mvp_gate_momentum_tardis_actionability_v1"
PROBE_DESCRIPTOR_SCHEMA = "trading_mvp_gate_momentum_tardis_probe_descriptor_v1"
PROBE_RESULT_SCHEMA = "trading_mvp_gate_momentum_tardis_public_schema_probe_v1"
SOURCE_CLOSURE_SCHEMA = (
    "trading_mvp_gate_historical_membership_v3_archive_source_closure_v1"
)
HYPOTHESIS_ID = "cross_sectional_momentum_daily_survivorship_repair_v3_tardis"
PARENT_HYPOTHESIS_ID = "cross_sectional_momentum_daily_survivorship_repair_v2"
SOURCE_FAILURE_REASON = "MISSING_END_DELISTED_ARCHIVE_AVAILABILITY_BELOW_FROZEN_GATE"
MAX_SCHEMA_PROBE_RUNTIME_SEC = 300
MAX_HISTORY_RUNTIME_SEC = 7_200
MAX_OFFLINE_RUNTIME_SEC = 1_800
HISTORY_DAYS = 220
WARMUP_DAYS = 20
TRAIN_DAYS = 100
OOS_DAYS = 100
OOS_FOLDS = 5
OOS_FOLD_DAYS = 20
MINIMUM_CANONICAL_ASSETS = 20
MAX_METADATA_DOWNLOAD_BYTES = 16 * 1024 * 1024
HASH_KEYS = "0123456789abcdef"


class ProbeSchemaError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {source}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {source}")
    return value


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        existing = _read_json(target)
        if existing != dict(payload):
            raise FileExistsError(f"refusing to overwrite immutable artifact: {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _validate_hash(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(character not in HASH_KEYS for character in digest):
        raise ValueError(f"invalid {label}")
    return digest


def _validate_source_closure(
    closure: Mapping[str, Any],
    *,
    require_expected_verdict: bool = True,
) -> dict[str, Any]:
    if closure.get("schema") != SOURCE_CLOSURE_SCHEMA or closure.get("final") is not True:
        raise ValueError("unexpected or non-final source-quality closure")
    if closure.get("branch_status") != "CLOSED_WITHOUT_HISTORY_OR_OOS":
        raise ValueError("source-quality closure branch status mismatch")
    if require_expected_verdict and closure.get("verdict") != "INSUFFICIENT_SOURCE_QUALITY":
        raise ValueError("source-quality closure did not fail only at source quality")
    reason_codes = set(closure.get("reason_codes") or ())
    if SOURCE_FAILURE_REASON not in reason_codes:
        raise ValueError("source-quality closure reason does not match the recoverable gap")
    diagnosis = closure.get("source_diagnosis")
    if not isinstance(diagnosis, Mapping):
        raise ValueError("source-quality closure diagnosis is missing")
    if diagnosis.get("active_control_passed") is not True:
        raise ValueError("source-quality closure active control did not pass")
    if diagnosis.get("known_end_delisted_control_passed") is not True:
        raise ValueError("source-quality closure known-end control did not pass")
    audit = closure.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("source-quality closure data-access audit is missing")
    for key in (
        "archive_payload_read",
        "history_read",
        "oos_read",
        "pnl_read",
        "returns_read",
        "signals_read",
        "train_read",
    ):
        if audit.get(key) is not False:
            raise ValueError(f"source-quality closure unexpectedly accessed {key}")
    return dict(closure)


def _strategy_contract() -> dict[str, Any]:
    return {
        "market": "gateio_usdt_linear_perpetual",
        "signal_family": "cross_sectional_momentum",
        "lookback_days": 30,
        "hold_days": 7,
        "rebalance_every_days": 7,
        "min_per_side": 5,
        "minimum_scored_markets": 20,
        "bucket_rule": "max(min_per_side,floor(scored_markets/10))",
        "liquidity_lookback_days": 7,
        "minimum_median_quote_volume": 1_000_000.0,
        "signal_price": "closed_daily_close",
        "entry_price": "next_closed_daily_open",
        "exit_price": "daily_open_after_hold_days",
        "long_leg": "highest_30d_return_bucket",
        "short_leg": "lowest_30d_return_bucket",
        "one_position_per_canonical_asset": True,
        "overlapping_rebalances": False,
        "parameter_selection": "forbidden",
        "grid_search": False,
        "retune": False,
    }


def _cost_contract() -> dict[str, Any]:
    return {
        "name": "gate_perp_cross_sectional_base_vip0_ohlcv_conservative_v1",
        "maker_fill_probability": 0.0,
        "per_operation_taker_bps": 10.0,
        "normal_cycle_bps": 46.0,
        "stress_cycle_bps": 72.0,
        "normal_components_bps": {
            "fees": 20.0,
            "spread": 10.0,
            "impact": 4.0,
            "slippage": 2.0,
            "rebalance_buffer": 10.0,
        },
        "stress_components_bps": {
            "fees": 20.0,
            "spread": 20.0,
            "impact": 8.0,
            "slippage": 4.0,
            "rebalance_buffer": 20.0,
        },
        "funding_policy": {
            "normal": "actual_cashflows_each_leg",
            "stress": "zero_favorable_preserve_adverse_per_asset",
            "funding_cannot_rescue_negative_price_only_expectancy": True,
        },
        "vip_or_rebate_assumption": False,
    }


def _sample_contract() -> dict[str, Any]:
    return {
        "history_days": HISTORY_DAYS,
        "warmup_days": WARMUP_DAYS,
        "train_days": TRAIN_DAYS,
        "oos_days": OOS_DAYS,
        "oos_folds": OOS_FOLDS,
        "oos_fold_days": OOS_FOLD_DAYS,
        "chronological_split": True,
        "global_rebalance_anchor": "history_start_plus_30_closed_days",
        "train_may_not_read_oos_paths": True,
        "oos_requires_hash_valid_train_feasible": True,
    }


def _source_contract() -> dict[str, Any]:
    return {
        "provider": "Tardis.dev",
        "gate_exchange_id": "gate-io-futures",
        "binance_reference_exchange_id": "binance",
        "gate_dataset_types": ["trades", "derivative_ticker"],
        "gate_symbol_inventory_required": True,
        "gate_symbol_available_since_required": True,
        "gate_symbol_available_to_required_for_delisted": True,
        "point_in_time_gate_membership_required": True,
        "point_in_time_binance_spot_membership_required": True,
        "binance_market_values_required": False,
        "binance_role": "reference_exclusion_only",
        "non_binance_at_signal_date_required": True,
        "canonical_asset_id_required": True,
        "ticker_only_join_forbidden": True,
        "history_days": HISTORY_DAYS,
        "minimum_canonical_assets": MINIMUM_CANONICAL_ASSETS,
        "daily_trade_aggregation": {
            "timezone": "UTC",
            "open": "first_trade_price",
            "close": "last_trade_price",
            "quote_volume": "sum(price*amount)",
            "closed_days_only": True,
        },
        "funding_aggregation": {
            "timestamp": "funding_timestamp",
            "rate": "funding_rate",
            "actual_settlements_only": True,
        },
    }


def _quality_contract() -> dict[str, Any]:
    return {
        "fail_closed": True,
        "minimum_gate_lifecycle_coverage": 0.90,
        "minimum_binance_reference_lifecycle_coverage": 0.90,
        "minimum_daily_series_coverage": 0.98,
        "minimum_funding_settlement_coverage": 0.98,
        "minimum_canonical_assets": MINIMUM_CANONICAL_ASSETS,
        "duplicate_timestamps_allowed": 0,
        "open_daily_bars_allowed": 0,
        "ambiguous_identity_allowed": 0,
        "interpolation_allowed": False,
        "survivorship_only_current_universe_allowed": False,
        "manual_shortlist_allowed": False,
        "reserve_replacement_after_oos_open_allowed": False,
    }


def _acceptance_contract() -> dict[str, Any]:
    return {
        "train": {
            "minimum_independent_rebalances": 10,
            "minimum_unique_assets": 10,
            "price_only_expectancy_positive": True,
            "total_expectancy_positive": True,
            "minimum_profit_factor": 1.1,
            "stress_expectancy_nonnegative": True,
            "maximum_drawdown_fraction": 0.15,
            "maximum_single_base_positive_pnl_share": 0.35,
            "maximum_single_rebalance_positive_pnl_share": 0.35,
        },
        "oos": {
            "exact_folds": OOS_FOLDS,
            "minimum_independent_rebalances": 8,
            "minimum_unique_assets": 10,
            "price_only_expectancy_positive": True,
            "total_expectancy_positive": True,
            "minimum_profit_factor": 1.2,
            "minimum_positive_folds": 4,
            "stress_expectancy_nonnegative": True,
            "cluster_bootstrap_expectancy_lower_95_positive": True,
            "maximum_drawdown_fraction": 0.10,
            "maximum_single_base_positive_pnl_share": 0.25,
            "maximum_single_rebalance_positive_pnl_share": 0.25,
            "maximum_historical_verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        },
        "deterministic_repeats": 2,
        "matching_result_hash_required": True,
    }


def _sealed_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "hypothesis": plan.get("hypothesis"),
        "archive_source": plan.get("archive_source"),
        "prior_source_closure": plan.get("prior_source_closure"),
        "strategy": plan.get("strategy"),
        "costs": plan.get("costs"),
        "sample": plan.get("sample"),
        "source_contract": plan.get("source_contract"),
        "quality_contract": plan.get("quality_contract"),
        "acceptance": plan.get("acceptance"),
        "runtime": plan.get("runtime"),
        "safety": plan.get("safety"),
        "code_provenance": plan.get("code_provenance"),
    }


def build_momentum_archive_plan(
    archive_source_plan_path: str | Path,
    source_closure_path: str | Path,
    output_path: str | Path | None = None,
    *,
    frozen_at_utc: str | None = None,
) -> dict[str, Any]:
    archive_path = Path(archive_source_plan_path).expanduser().resolve()
    closure_path = Path(source_closure_path).expanduser().resolve()
    archive_plan = _read_json(archive_path)
    if archive_plan.get("schema") != ARCHIVE_PLAN_SCHEMA:
        raise ValueError("unexpected archive source plan schema")
    source_route = archive_plan.get("source_route")
    route_path = (
        Path(str(source_route.get("path"))).expanduser().resolve()
        if isinstance(source_route, Mapping) and source_route.get("path")
        else None
    )
    validate_archive_source_plan(
        archive_plan,
        source_route_path=route_path,
    )
    closure = _validate_source_closure(_read_json(closure_path))
    archive_plan_hash = _validate_hash(
        archive_plan.get("plan_hash"),
        label="archive source plan hash",
    )
    module_path = Path(__file__).resolve()
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "status": "MOMENTUM_ARCHIVE_SOURCE_REPAIR_FROZEN_AWAITING_ACTIONABILITY_AUDIT",
        "generated_at_utc": frozen_at_utc or datetime.now(timezone.utc).isoformat(),
        "hypothesis": {
            "id": HYPOTHESIS_ID,
            "parent_hypothesis_id": PARENT_HYPOTHESIS_ID,
            "materially_new_dimension": "point_in_time_archive_source_repair",
            "old_contaminated_returns_reused": False,
            "old_thresholds_retuned": False,
            "old_source_branch_reopened": False,
            "research_only": True,
        },
        "archive_source": {
            "path": str(archive_path),
            "file_sha256": sha256_file(archive_path),
            "plan_hash": archive_plan_hash,
            "provider": "Tardis.dev",
            "exchange_id": "gate-io-futures",
        },
        "prior_source_closure": {
            "path": str(closure_path),
            "file_sha256": sha256_file(closure_path),
            "artifact_hash": closure.get("artifact_hash"),
            "verdict": closure["verdict"],
            "reason_codes": list(closure.get("reason_codes") or ()),
            "missing_end_delisted_symbol_availability": float(
                (closure["source_diagnosis"] or {}).get(
                    "missing_end_delisted_symbol_availability", 0.0
                )
            ),
        },
        "strategy": _strategy_contract(),
        "costs": _cost_contract(),
        "sample": _sample_contract(),
        "source_contract": _source_contract(),
        "quality_contract": _quality_contract(),
        "acceptance": _acceptance_contract(),
        "runtime": {
            "schema_probe_max_runtime_sec": MAX_SCHEMA_PROBE_RUNTIME_SEC,
            "history_collect_max_runtime_sec": MAX_HISTORY_RUNTIME_SEC,
            "quality_max_runtime_sec": MAX_OFFLINE_RUNTIME_SEC,
            "train_max_runtime_sec": MAX_OFFLINE_RUNTIME_SEC,
            "oos_max_runtime_sec": MAX_OFFLINE_RUNTIME_SEC,
        },
        "safety": {
            "research_only": True,
            "network_access_current_stage": False,
            "public_sample_schema_probe_only_next": True,
            "history_collect_currently_allowed": False,
            "strategy_evaluation_currently_allowed": False,
            "oos_currently_allowed": False,
            "grid_search": False,
            "retune": False,
            "execution_probe": False,
            "paper_forward": False,
            "live_orders": False,
            "private_exchange_api_keys": False,
            "leverage_or_margin": False,
            "automatic_transition": False,
        },
        "code_provenance": {
            "module_sha256": sha256_file(module_path),
            "archive_module_sha256": str(
                (archive_plan.get("code_provenance") or {}).get("module_sha256") or ""
            ),
        },
        "data_access_audit": {
            "network_access": False,
            "provider_account_accessed": False,
            "archive_market_rows_read": False,
            "market_rows_read": False,
            "returns_read": False,
            "signals_computed": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "next_allowed_command": "gate_momentum_archive_actionability_audit",
        "output_path": (
            str(Path(output_path).expanduser().resolve())
            if output_path is not None
            else None
        ),
    }
    plan["plan_hash"] = sha256_json(_sealed_plan(plan))
    if output_path is not None:
        _write_json_immutable(output_path, plan)
    return plan


def validate_momentum_archive_plan(
    plan: Mapping[str, Any],
    *,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError("unexpected momentum archive PlanOnly")
    observed_hash = _validate_hash(plan.get("plan_hash"), label="plan hash")
    if sha256_json(_sealed_plan(plan)) != observed_hash:
        raise ValueError("plan hash mismatch")
    if expected_plan_hash and observed_hash != _validate_hash(
        expected_plan_hash,
        label="expected plan hash",
    ):
        raise ValueError("plan hash differs from expected")
    hypothesis = plan.get("hypothesis")
    if not isinstance(hypothesis, Mapping) or hypothesis.get("id") != HYPOTHESIS_ID:
        raise ValueError("momentum archive hypothesis mismatch")
    if hypothesis.get("old_contaminated_returns_reused") is not False:
        raise ValueError("contaminated historical result reuse is forbidden")
    if plan.get("strategy") != _strategy_contract():
        raise ValueError("frozen strategy contract mismatch")
    if plan.get("costs") != _cost_contract():
        raise ValueError("frozen cost contract mismatch")
    if plan.get("sample") != _sample_contract():
        raise ValueError("frozen sample contract mismatch")
    if plan.get("source_contract") != _source_contract():
        raise ValueError("frozen source contract mismatch")
    if plan.get("quality_contract") != _quality_contract():
        raise ValueError("frozen quality contract mismatch")
    if plan.get("acceptance") != _acceptance_contract():
        raise ValueError("frozen acceptance contract mismatch")
    safety = plan.get("safety")
    if not isinstance(safety, Mapping):
        raise ValueError("momentum archive safety contract is missing")
    for key in (
        "grid_search",
        "retune",
        "execution_probe",
        "paper_forward",
        "live_orders",
        "private_exchange_api_keys",
        "leverage_or_margin",
        "automatic_transition",
    ):
        if safety.get(key) is not False:
            raise ValueError(f"momentum archive safety mismatch: {key}")
    audit = plan.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(value is not False for value in audit.values()):
        raise ValueError("momentum archive data-access audit mismatch")
    code = plan.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("momentum archive code provenance is missing")
    if code.get("module_sha256") != sha256_file(Path(__file__).resolve()):
        raise ValueError("momentum archive module hash mismatch")

    archive_ref = plan.get("archive_source")
    if not isinstance(archive_ref, Mapping):
        raise ValueError("archive source reference is missing")
    archive_path = Path(str(archive_ref.get("path") or "")).expanduser().resolve()
    if not archive_path.is_file():
        raise ValueError("archive source plan is missing")
    if sha256_file(archive_path) != archive_ref.get("file_sha256"):
        raise ValueError("archive source plan file hash mismatch")
    archive_plan = _read_json(archive_path)
    route = archive_plan.get("source_route")
    route_path = (
        Path(str(route.get("path"))).expanduser().resolve()
        if isinstance(route, Mapping) and route.get("path")
        else None
    )
    validate_archive_source_plan(
        archive_plan,
        expected_plan_hash=str(archive_ref.get("plan_hash") or ""),
        source_route_path=route_path,
    )
    archive_module_hash = str(
        (archive_plan.get("code_provenance") or {}).get("module_sha256") or ""
    )
    if code.get("archive_module_sha256") != archive_module_hash:
        raise ValueError("archive module provenance mismatch")

    closure_ref = plan.get("prior_source_closure")
    if not isinstance(closure_ref, Mapping):
        raise ValueError("prior source closure reference is missing")
    closure_path = Path(str(closure_ref.get("path") or "")).expanduser().resolve()
    if not closure_path.is_file():
        raise ValueError("prior source closure is missing")
    if sha256_file(closure_path) != closure_ref.get("file_sha256"):
        raise ValueError("source closure file hash mismatch")
    _validate_source_closure(_read_json(closure_path))
    return dict(plan)


def assess_momentum_archive_actionability(
    plan: Mapping[str, Any],
    output_path: str | Path | None = None,
    *,
    expected_plan_hash: str | None = None,
    entitlement_present: bool | None = None,
) -> dict[str, Any]:
    validated = validate_momentum_archive_plan(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    present = (
        bool(os.environ.get(DEFAULT_CREDENTIAL_ENV))
        if entitlement_present is None
        else bool(entitlement_present)
    )
    verdict = (
        "PUBLIC_SCHEMA_PROBE_ALLOWED_ENTITLEMENT_PRESENT"
        if present
        else "PUBLIC_SCHEMA_PROBE_ALLOWED_ENTITLEMENT_REQUIRED_FOR_HISTORY"
    )
    body: dict[str, Any] = {
        "schema": ACTIONABILITY_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final": True,
        "hypothesis_id": HYPOTHESIS_ID,
        "plan_hash": validated["plan_hash"],
        "verdict": verdict,
        "reason_code": (
            "ARCHIVE_SOURCE_CANDIDATE_CAN_ADDRESS_GATE_MEMBERSHIP_GAP_"
            "PENDING_SCHEMA_AND_IDENTITY"
        ),
        "archive_entitlement_present": present,
        "credential_environment_variable": DEFAULT_CREDENTIAL_ENV,
        "credential_value_persisted": False,
        "public_schema_probe_allowed": True,
        "history_collect_allowed": False,
        "mexc_history_required": False,
        "point_in_time_gate_membership_required": True,
        "point_in_time_binance_reference_required": True,
        "network_requests": 0,
        "data_access_audit": {
            "archive_market_rows_read": False,
            "market_rows_read": False,
            "returns_read": False,
            "signals_computed": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "safety": dict(validated["safety"]),
        "next_allowed_command": "visible_gate_momentum_archive_public_schema_probe",
        "output_path": (
            str(Path(output_path).expanduser().resolve())
            if output_path is not None
            else None
        ),
    }
    body["artifact_hash"] = sha256_json(
        {key: value for key, value in body.items() if key != "generated_at_utc"}
    )
    if output_path is not None:
        _write_json_immutable(output_path, body)
    return body


def build_momentum_public_probe_descriptor(
    plan: Mapping[str, Any],
    *,
    sample_date: str = "2020-07-01",
    max_runtime_sec: int = 120,
) -> dict[str, Any]:
    validated = validate_momentum_archive_plan(plan)
    archive_ref = validated["archive_source"]
    archive_plan = _read_json(archive_ref["path"])
    parent = build_schema_probe_descriptor(
        archive_plan,
        symbol="BTC_USDT",
        sample_date=sample_date,
        max_runtime_sec=max_runtime_sec,
    )
    requests = list(parent.get("requests") or ())
    requests.append(
        {
            "kind": "binance_reference_exchange_metadata",
            "url": "https://api.tardis.dev/v1/exchanges/binance",
            "value_access": "schema_and_symbol_lifecycle_only",
        }
    )
    descriptor = {
        "schema": PROBE_DESCRIPTOR_SCHEMA,
        "mode": "PlanOnly",
        "hypothesis_id": HYPOTHESIS_ID,
        "plan_hash": validated["plan_hash"],
        "archive_source_plan_hash": archive_ref["plan_hash"],
        "parent_descriptor": parent,
        "request_count": len(requests),
        "requests": requests,
        "gate_symbol_inventory_metadata_required": True,
        "binance_reference_symbol_inventory_metadata_required": True,
        "credential_reference": {
            "source": "environment_only",
            "environment_variable": DEFAULT_CREDENTIAL_ENV,
            "secret_persisted": False,
        },
        "data_access_audit": {
            "network_access": False,
            "market_values_read": False,
            "returns_read": False,
            "pnl_read": False,
        },
        "history_collect_allowed": False,
    }
    descriptor["descriptor_hash"] = sha256_json(descriptor)
    return descriptor


def validate_momentum_public_probe_descriptor(
    plan: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    *,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    validated_plan = validate_momentum_archive_plan(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    observed_hash = _validate_hash(
        descriptor.get("descriptor_hash"),
        label="descriptor hash",
    )
    semantic = {
        key: value
        for key, value in descriptor.items()
        if key != "descriptor_hash"
    }
    if sha256_json(semantic) != observed_hash:
        raise ValueError("descriptor hash mismatch")
    if (
        descriptor.get("schema") != PROBE_DESCRIPTOR_SCHEMA
        or descriptor.get("mode") != "PlanOnly"
        or descriptor.get("hypothesis_id") != HYPOTHESIS_ID
    ):
        raise ValueError("unexpected momentum public probe descriptor")
    if descriptor.get("plan_hash") != validated_plan["plan_hash"]:
        raise ValueError("probe descriptor plan hash mismatch")
    parent = descriptor.get("parent_descriptor")
    if not isinstance(parent, Mapping):
        raise ValueError("parent archive probe descriptor is missing")
    runtime = parent.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("parent archive probe runtime is missing")
    sample_date = str(parent.get("sample_date") or "")
    max_runtime_sec = int(runtime.get("max_runtime_sec") or 0)
    expected = build_momentum_public_probe_descriptor(
        validated_plan,
        sample_date=sample_date,
        max_runtime_sec=max_runtime_sec,
    )
    if dict(descriptor) != expected:
        raise ValueError("probe descriptor differs from frozen request contract")
    if int(descriptor.get("request_count") or 0) != 4:
        raise ValueError("probe descriptor must contain exactly four requests")
    serialized = _canonical_json(descriptor)
    if "Authorization" in serialized or "Bearer " in serialized:
        raise ValueError("probe descriptor must not persist authorization material")
    return dict(descriptor)


def _remaining_timeout(deadline: float, configured_timeout_sec: int) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("public schema probe exceeded frozen runtime")
    return max(0.1, min(float(configured_timeout_sec), remaining))


def _read_bounded_body(
    response: Any,
    *,
    max_download_bytes: int,
) -> bytes:
    output = bytearray()
    for raw_chunk in response.iter_content(chunk_size=8192):
        chunk = bytes(raw_chunk or b"")
        if not chunk:
            continue
        output.extend(chunk)
        if len(output) > int(max_download_bytes):
            raise ValueError("public schema response exceeded byte limit")
    return bytes(output)


def _fetch_json_object(
    session: Any,
    url: str,
    *,
    timeout_sec: float,
    max_download_bytes: int = MAX_METADATA_DOWNLOAD_BYTES,
) -> dict[str, Any]:
    try:
        response = session.get(
            url,
            headers={},
            timeout=timeout_sec,
            stream=True,
        )
        with response:
            response.raise_for_status()
            body = _read_bounded_body(
                response,
                max_download_bytes=max_download_bytes,
            )
    except Exception as exc:
        raise RuntimeError(
            f"public metadata request failed: {type(exc).__name__}"
        ) from None
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeSchemaError(
            "METADATA_JSON_SCHEMA_INVALID",
            "public metadata response is not a UTF-8 JSON object",
        ) from exc
    if not isinstance(payload, Mapping):
        raise ProbeSchemaError(
            "METADATA_JSON_SCHEMA_INVALID",
            "public metadata response must be an object",
        )
    return dict(payload)


def _fetch_dataset_header(
    session: Any,
    url: str,
    data_type: str,
    *,
    timeout_sec: float,
) -> list[str]:
    try:
        response = session.get(
            url,
            headers={},
            timeout=timeout_sec,
            stream=True,
        )
        with response:
            response.raise_for_status()
            downloaded = 0
            output = bytearray()
            prefix = bytearray()
            decompressor: zlib.Decompress | None = None
            gzip_body: bool | None = None
            for raw_chunk in response.iter_content(chunk_size=8192):
                chunk = bytes(raw_chunk or b"")
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_HEADER_DOWNLOAD_BYTES:
                    raise ValueError("dataset header exceeded download byte limit")
                if gzip_body is None:
                    prefix.extend(chunk)
                    if len(prefix) < 2:
                        continue
                    gzip_body = prefix[:2] == b"\x1f\x8b"
                    chunk = bytes(prefix)
                    prefix.clear()
                    if gzip_body:
                        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
                if gzip_body:
                    assert decompressor is not None
                    remaining = MAX_HEADER_BYTES + 1 - len(output)
                    decoded = decompressor.decompress(chunk, max(1, remaining))
                else:
                    decoded = chunk
                output.extend(decoded)
                if b"\n" in output:
                    break
                if len(output) > MAX_HEADER_BYTES:
                    raise ValueError("dataset CSV header exceeded byte limit")
    except Exception as exc:
        raise RuntimeError(
            f"public dataset header request failed for {data_type}: "
            f"{type(exc).__name__}"
        ) from None
    if b"\n" not in output:
        raise ProbeSchemaError(
            "DATASET_HEADER_INCOMPLETE",
            f"{data_type} CSV header is incomplete",
        )
    first_line = bytes(output).split(b"\n", 1)[0].rstrip(b"\r")
    if len(first_line) > MAX_HEADER_BYTES:
        raise ProbeSchemaError(
            "DATASET_HEADER_TOO_LARGE",
            f"{data_type} CSV header exceeds byte limit",
        )
    try:
        header = first_line.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProbeSchemaError(
            "DATASET_HEADER_ENCODING_INVALID",
            f"{data_type} CSV header is not UTF-8",
        ) from exc
    try:
        return validate_dataset_header(data_type, header)
    except ValueError as exc:
        raise ProbeSchemaError(
            "DATASET_HEADER_SCHEMA_INVALID",
            str(exc),
        ) from exc


def _parse_lifecycle_timestamp(value: Any, *, label: str) -> datetime:
    normalized = str(value or "").strip()
    if not normalized:
        raise ProbeSchemaError(
            "LIFECYCLE_TIMESTAMP_MISSING",
            f"{label} is missing",
        )
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProbeSchemaError(
            "LIFECYCLE_TIMESTAMP_INVALID",
            f"{label} is not an ISO timestamp",
        ) from exc
    if parsed.tzinfo is None:
        raise ProbeSchemaError(
            "LIFECYCLE_TIMESTAMP_INVALID",
            f"{label} must include a timezone",
        )
    return parsed


def _summarize_exchange_metadata(
    payload: Mapping[str, Any],
    *,
    expected_exchange_id: str,
    expected_instrument_type: str,
    required_data_types: Sequence[str],
    require_closed_lifecycle: bool,
) -> dict[str, Any]:
    if payload.get("id") != expected_exchange_id:
        raise ProbeSchemaError(
            "EXCHANGE_METADATA_ID_MISMATCH",
            f"expected exchange metadata id {expected_exchange_id}",
        )
    if payload.get("supportsDatasets") is not True:
        raise ProbeSchemaError(
            "EXCHANGE_DATASETS_UNSUPPORTED",
            f"{expected_exchange_id} does not expose downloadable datasets",
        )
    datasets = payload.get("datasets")
    if not isinstance(datasets, Mapping):
        raise ProbeSchemaError(
            "DATASET_METADATA_SCHEMA_MISSING",
            f"{expected_exchange_id} datasets metadata is missing",
        )
    symbols = datasets.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ProbeSchemaError(
            "DATASET_SYMBOL_INVENTORY_MISSING",
            f"{expected_exchange_id} dataset symbol inventory is empty",
        )

    ids: list[str] = []
    available_since = 0
    available_to = 0
    instrument_type_count = 0
    observed_data_types = {
        str(value)
        for value in (datasets.get("dataTypes") or ())
        if str(value)
    }
    for index, item in enumerate(symbols):
        if not isinstance(item, Mapping):
            raise ProbeSchemaError(
                "DATASET_SYMBOL_SCHEMA_INVALID",
                f"{expected_exchange_id} symbol row {index} is not an object",
            )
        symbol_id = str(item.get("id") or "").strip()
        if not symbol_id:
            raise ProbeSchemaError(
                "DATASET_SYMBOL_SCHEMA_INVALID",
                f"{expected_exchange_id} symbol row {index} has no id",
            )
        ids.append(symbol_id)
        instrument_type_count += int(
            str(item.get("type") or "").lower() == expected_instrument_type
        )
        since_value = item.get("availableSince")
        since: datetime | None = None
        if since_value:
            since = _parse_lifecycle_timestamp(
                since_value,
                label=f"{expected_exchange_id}.{symbol_id}.availableSince",
            )
            available_since += 1
        to_value = item.get("availableTo")
        if to_value:
            to = _parse_lifecycle_timestamp(
                to_value,
                label=f"{expected_exchange_id}.{symbol_id}.availableTo",
            )
            if since is not None and to < since:
                raise ProbeSchemaError(
                    "LIFECYCLE_RANGE_INVALID",
                    f"{expected_exchange_id}.{symbol_id} availableTo precedes availableSince",
                )
            available_to += 1
        observed_data_types.update(
            str(value)
            for value in (item.get("dataTypes") or ())
            if str(value)
        )

    if len(ids) != len(set(ids)):
        raise ProbeSchemaError(
            "DUPLICATE_DATASET_SYMBOL_IDS",
            f"{expected_exchange_id} dataset inventory contains duplicate ids",
        )
    coverage = available_since / len(symbols)
    if coverage < 0.90:
        raise ProbeSchemaError(
            "LIFECYCLE_AVAILABLE_SINCE_COVERAGE_LOW",
            f"{expected_exchange_id} availableSince coverage is below 90%",
        )
    if instrument_type_count == 0:
        raise ProbeSchemaError(
            "EXPECTED_INSTRUMENT_TYPE_MISSING",
            f"{expected_exchange_id} has no {expected_instrument_type} dataset symbols",
        )
    missing_types = sorted(set(required_data_types) - observed_data_types)
    if missing_types:
        raise ProbeSchemaError(
            "REQUIRED_DATASET_TYPES_MISSING",
            f"{expected_exchange_id} is missing dataset types: {', '.join(missing_types)}",
        )
    if require_closed_lifecycle and available_to == 0:
        raise ProbeSchemaError(
            "GATE_CLOSED_LIFECYCLE_SCHEMA_MISSING",
            "Gate dataset metadata exposes no availableTo lifecycle example",
        )

    return {
        "exchange_id": expected_exchange_id,
        "dataset_symbol_count": len(symbols),
        "expected_instrument_type_count": instrument_type_count,
        "available_since_symbols": available_since,
        "available_since_coverage": round(coverage, 6),
        "closed_lifecycle_symbols": available_to,
        "required_data_types_present": sorted(set(required_data_types)),
        "exported_from_present": bool(datasets.get("exportedFrom")),
        "exported_until_present": bool(datasets.get("exportedUntil")),
        "symbol_inventory_sha256": hashlib.sha256(
            "\n".join(sorted(ids)).encode("utf-8")
        ).hexdigest(),
        "raw_symbol_ids_persisted": False,
    }


def _probe_result_hash(result: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in result.items()
            if key not in {"generated_at_utc", "elapsed_sec", "artifact_hash", "output_path"}
        }
    )


def execute_momentum_public_schema_probe(
    plan: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    output_path: str | Path | None = None,
    *,
    expected_plan_hash: str | None = None,
    session: Any | None = None,
    entitlement_present: bool | None = None,
    timeout_sec: int = 15,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    validated_plan = validate_momentum_archive_plan(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    validated_descriptor = validate_momentum_public_probe_descriptor(
        validated_plan,
        descriptor,
        expected_plan_hash=expected_plan_hash,
    )
    parent = validated_descriptor["parent_descriptor"]
    runtime_sec = int(parent["runtime"]["max_runtime_sec"])
    timeout = int(timeout_sec)
    if timeout <= 0 or timeout > 60:
        raise ValueError("timeout_sec must be in [1, 60]")
    present = (
        bool(os.environ.get(DEFAULT_CREDENTIAL_ENV))
        if entitlement_present is None
        else bool(entitlement_present)
    )
    if not bool(parent.get("sample_only_without_entitlement")) and not present:
        raise ValueError(
            "public unauthenticated schema probe requires the first day of a month"
        )

    started = time.monotonic()
    deadline = started + runtime_sec
    http = session if session is not None else requests.Session()
    own_session = session is None
    network_requests = 0
    gate_summary: dict[str, Any] | None = None
    binance_summary: dict[str, Any] | None = None
    headers: dict[str, dict[str, Any]] = {}
    reason_codes: list[str] = []
    failure_type: str | None = None
    failure_message: str | None = None

    try:
        for request_plan in validated_descriptor["requests"]:
            kind = str(request_plan.get("kind") or "")
            url = str(request_plan.get("url") or "")
            request_timeout = _remaining_timeout(deadline, timeout)
            network_requests += 1
            print(
                f"[gate-momentum-archive] request={network_requests}/4 "
                f"kind={kind} elapsed_sec={time.monotonic() - started:.1f} "
                f"remaining_sec={max(0.0, deadline - time.monotonic()):.1f}",
                flush=True,
            )
            if kind == "exchange_metadata":
                payload = _fetch_json_object(
                    http,
                    url,
                    timeout_sec=request_timeout,
                )
                gate_summary = _summarize_exchange_metadata(
                    payload,
                    expected_exchange_id="gate-io-futures",
                    expected_instrument_type="perpetual",
                    required_data_types=DATASET_TYPES,
                    require_closed_lifecycle=True,
                )
            elif kind == "dataset_header":
                data_type = str(request_plan.get("data_type") or "")
                columns = _fetch_dataset_header(
                    http,
                    url,
                    data_type,
                    timeout_sec=request_timeout,
                )
                headers[data_type] = {
                    "column_count": len(columns),
                    "columns": columns,
                    "header_sha256": hashlib.sha256(
                        ",".join(columns).encode("utf-8")
                    ).hexdigest(),
                    "market_rows_read": 0,
                }
            elif kind == "binance_reference_exchange_metadata":
                payload = _fetch_json_object(
                    http,
                    url,
                    timeout_sec=request_timeout,
                )
                binance_summary = _summarize_exchange_metadata(
                    payload,
                    expected_exchange_id="binance",
                    expected_instrument_type="spot",
                    required_data_types=("trades",),
                    require_closed_lifecycle=False,
                )
            else:
                raise ProbeSchemaError(
                    "UNEXPECTED_PROBE_REQUEST_KIND",
                    f"unexpected probe request kind: {kind}",
                )
            print(
                f"[gate-momentum-archive] request={network_requests}/4 "
                f"kind={kind} status=schema_read_complete",
                flush=True,
            )
            _remaining_timeout(deadline, timeout)
    except ProbeSchemaError as exc:
        reason_codes.append(exc.reason_code)
        failure_type = type(exc).__name__
        failure_message = str(exc)
    except TimeoutError as exc:
        reason_codes.append("PUBLIC_SCHEMA_PROBE_RUNTIME_EXCEEDED")
        failure_type = type(exc).__name__
        failure_message = str(exc)
    except Exception as exc:
        reason_codes.append("PUBLIC_SCHEMA_PROBE_NETWORK_OR_TRANSPORT_FAILURE")
        failure_type = type(exc).__name__
        failure_message = str(exc)
    finally:
        if own_session:
            close = getattr(http, "close", None)
            if callable(close):
                close()

    success = (
        not reason_codes
        and gate_summary is not None
        and binance_summary is not None
        and set(headers) == set(DATASET_TYPES)
        and network_requests == 4
    )
    if success:
        verdict = (
            "PUBLIC_SCHEMA_ACCEPTED_IDENTITY_PROBE_REQUIRED"
            if present
            else "PUBLIC_SCHEMA_ACCEPTED_ENTITLEMENT_REQUIRED_FOR_IDENTITY_AND_HISTORY"
        )
        next_command = (
            "freeze_authenticated_identity_probe_planonly"
            if present
            else "obtain_tardis_entitlement_then_freeze_authenticated_identity_probe_planonly"
        )
    else:
        if not reason_codes:
            reason_codes.append("PUBLIC_SCHEMA_PROBE_INCOMPLETE")
        verdict = "REJECTED_SOURCE_SCHEMA"
        next_command = "none_source_rejected_or_fix_transport_then_new_hash_bound_probe"

    result: dict[str, Any] = {
        "schema": PROBE_RESULT_SCHEMA,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "final": True,
        "partial_accept": False,
        "hypothesis_id": HYPOTHESIS_ID,
        "plan_hash": validated_plan["plan_hash"],
        "descriptor_hash": validated_descriptor["descriptor_hash"],
        "verdict": verdict,
        "reason_codes": reason_codes,
        "archive_entitlement_present": present,
        "authorization_header_sent": False,
        "credential_value_persisted": False,
        "network_requests": network_requests,
        "runtime_limit_sec": runtime_sec,
        "elapsed_sec": round(time.monotonic() - started, 6),
        "gate_metadata": gate_summary,
        "binance_reference": binance_summary,
        "dataset_headers": headers,
        "identity_schema_status": (
            "PENDING_ENTITLED_INSTRUMENT_METADATA"
            if success
            else "REJECTED_OR_NOT_REACHED"
        ),
        "history_collect_allowed": False,
        "failure": (
            {
                "type": failure_type,
                "message": failure_message,
            }
            if failure_type
            else None
        ),
        "data_access_audit": {
            "network_access": network_requests > 0,
            "metadata_values_read": network_requests > 0,
            "market_rows_read": False,
            "market_values_read": False,
            "returns_read": False,
            "signals_computed": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "safety": {
            "schema_only": True,
            "history_collect": False,
            "strategy_evaluation": False,
            "oos": False,
            "grid_search": False,
            "live_orders": False,
            "private_exchange_api_keys": False,
            "leverage_or_margin": False,
        },
        "next_allowed_command": next_command,
        "output_path": (
            str(Path(output_path).expanduser().resolve())
            if output_path is not None
            else None
        ),
    }
    result["artifact_hash"] = _probe_result_hash(result)
    if output_path is not None:
        _write_json_immutable(output_path, result)
    return result


def validate_momentum_public_probe_result(
    result: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    validated_plan = validate_momentum_archive_plan(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    validated_descriptor = validate_momentum_public_probe_descriptor(
        validated_plan,
        descriptor,
        expected_plan_hash=expected_plan_hash,
    )
    if (
        result.get("schema") != PROBE_RESULT_SCHEMA
        or result.get("final") is not True
        or result.get("partial_accept") is not False
    ):
        raise ValueError("unexpected or non-final momentum public probe result")
    observed_hash = _validate_hash(
        result.get("artifact_hash"),
        label="probe result artifact hash",
    )
    if _probe_result_hash(result) != observed_hash:
        raise ValueError("probe result hash mismatch")
    if result.get("plan_hash") != validated_plan["plan_hash"]:
        raise ValueError("probe result plan hash mismatch")
    if result.get("descriptor_hash") != validated_descriptor["descriptor_hash"]:
        raise ValueError("probe result descriptor hash mismatch")
    if result.get("history_collect_allowed") is not False:
        raise ValueError("public probe result cannot authorize history collection")
    if result.get("authorization_header_sent") is not False:
        raise ValueError("public probe result unexpectedly used authorization")
    if result.get("credential_value_persisted") is not False:
        raise ValueError("public probe result persisted credential material")
    audit = result.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("public probe data-access audit is missing")
    for key in (
        "market_rows_read",
        "market_values_read",
        "returns_read",
        "signals_computed",
        "pnl_read",
        "oos_read",
    ):
        if audit.get(key) is not False:
            raise ValueError(f"public probe unexpectedly accessed {key}")
    safety = result.get("safety")
    if not isinstance(safety, Mapping) or safety.get("schema_only") is not True:
        raise ValueError("public probe safety contract is missing")
    for key in (
        "history_collect",
        "strategy_evaluation",
        "oos",
        "grid_search",
        "live_orders",
        "private_exchange_api_keys",
        "leverage_or_margin",
    ):
        if safety.get(key) is not False:
            raise ValueError(f"public probe safety mismatch: {key}")

    verdict = str(result.get("verdict") or "")
    accepted_verdicts = {
        "PUBLIC_SCHEMA_ACCEPTED_ENTITLEMENT_REQUIRED_FOR_IDENTITY_AND_HISTORY",
        "PUBLIC_SCHEMA_ACCEPTED_IDENTITY_PROBE_REQUIRED",
    }
    accepted = verdict in accepted_verdicts
    if accepted:
        if list(result.get("reason_codes") or ()):
            raise ValueError("accepted public probe has rejection reason codes")
        if int(result.get("network_requests") or 0) != 4:
            raise ValueError("accepted public probe request count mismatch")
        if not isinstance(result.get("gate_metadata"), Mapping):
            raise ValueError("accepted public probe Gate metadata summary is missing")
        if not isinstance(result.get("binance_reference"), Mapping):
            raise ValueError("accepted public probe Binance metadata summary is missing")
        headers = result.get("dataset_headers")
        if not isinstance(headers, Mapping) or set(headers) != set(DATASET_TYPES):
            raise ValueError("accepted public probe dataset headers are incomplete")
        if result.get("identity_schema_status") != "PENDING_ENTITLED_INSTRUMENT_METADATA":
            raise ValueError("accepted public probe identity status mismatch")
    elif verdict == "REJECTED_SOURCE_SCHEMA":
        if not list(result.get("reason_codes") or ()):
            raise ValueError("rejected public probe has no reason code")
    else:
        raise ValueError("unsupported public probe verdict")

    validated = dict(result)
    validated["accepted_for_identity_probe_planonly"] = accepted
    return validated


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PlanOnly Gate momentum survivorship repair via Tardis archives"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--archive-plan", required=True)
    plan.add_argument("--source-closure", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--frozen-at-utc")

    validate = subparsers.add_parser("validate-plan")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash")

    audit = subparsers.add_parser("actionability")
    audit.add_argument("--plan", required=True)
    audit.add_argument("--expected-plan-hash")
    audit.add_argument("--output", required=True)

    descriptor = subparsers.add_parser("probe-descriptor")
    descriptor.add_argument("--plan", required=True)
    descriptor.add_argument("--expected-plan-hash")
    descriptor.add_argument("--sample-date", default="2020-07-01")
    descriptor.add_argument("--max-runtime-sec", type=int, default=120)
    descriptor.add_argument("--output", required=True)

    validate_descriptor = subparsers.add_parser("validate-probe-descriptor")
    validate_descriptor.add_argument("--plan", required=True)
    validate_descriptor.add_argument("--descriptor", required=True)
    validate_descriptor.add_argument("--expected-plan-hash")

    probe = subparsers.add_parser("public-schema-probe")
    probe.add_argument("--plan", required=True)
    probe.add_argument("--descriptor", required=True)
    probe.add_argument("--expected-plan-hash")
    probe.add_argument("--timeout-sec", type=int, default=15)
    probe.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan":
        result = build_momentum_archive_plan(
            args.archive_plan,
            args.source_closure,
            args.output,
            frozen_at_utc=args.frozen_at_utc,
        )
    elif args.command == "validate-plan":
        result = validate_momentum_archive_plan(
            _read_json(args.plan),
            expected_plan_hash=args.expected_plan_hash,
        )
    elif args.command == "actionability":
        result = assess_momentum_archive_actionability(
            _read_json(args.plan),
            args.output,
            expected_plan_hash=args.expected_plan_hash,
        )
    elif args.command == "probe-descriptor":
        plan = validate_momentum_archive_plan(
            _read_json(args.plan),
            expected_plan_hash=args.expected_plan_hash,
        )
        result = build_momentum_public_probe_descriptor(
            plan,
            sample_date=args.sample_date,
            max_runtime_sec=args.max_runtime_sec,
        )
        _write_json_immutable(args.output, result)
    elif args.command == "validate-probe-descriptor":
        result = validate_momentum_public_probe_descriptor(
            _read_json(args.plan),
            _read_json(args.descriptor),
            expected_plan_hash=args.expected_plan_hash,
        )
    elif args.command == "public-schema-probe":
        result = execute_momentum_public_schema_probe(
            _read_json(args.plan),
            _read_json(args.descriptor),
            args.output,
            expected_plan_hash=args.expected_plan_hash,
            timeout_sec=args.timeout_sec,
        )
    else:  # pragma: no cover
        raise AssertionError(f"unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
