from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pit_cross_venue_fast_pipeline import DECISION_READY, FAST_MODE, FAST_SCHEMA


SHORT_PLAN_SCHEMA = "pit_linear_perp_cross_venue_short_execution_probe_plan_v1"
SHORT_PLAN_MODE = "pit_linear_perp_cross_venue_short_execution_probe_planonly"
SHORT_PLAN_DECISION = "PIT_LINEAR_PERP_SHORT_EXECUTION_PROBE_PLANONLY_READY"


def build_short_probe_plan(fast_output_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(fast_output_path).resolve()
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError(f"short probe plan already exists: {destination}")
    fast = _load_json(source)
    _validate_fast_output(fast)
    fast_source = fast.get("source") or {}
    freeze_path = Path(str(fast_source.get("diagnostic_freeze_path") or "")).resolve()
    if not freeze_path.is_file() or _sha256_file(freeze_path) != str(
        fast_source.get("diagnostic_freeze_sha256") or ""
    ):
        raise ValueError("fast output diagnostic freeze binding is missing or changed")
    freeze = _load_json(freeze_path)
    freeze_source = freeze.get("source") or {}
    original_plan_path = Path(str(freeze_source.get("plan_path") or "")).resolve()
    if not original_plan_path.is_file() or _sha256_file(original_plan_path) != str(
        freeze_source.get("plan_sha256") or ""
    ):
        raise ValueError("diagnostic freeze original plan binding is missing or changed")
    original_plan = _load_json(original_plan_path)
    original_contract = original_plan.get("collection_contract") or {}
    contract = fast.get("short_probe_contract") or {}
    candidates = [str(base).upper() for base in contract.get("candidate_bases") or []]
    if not candidates or len(candidates) != len(set(candidates)):
        raise ValueError("short probe candidates must be non-empty and unique")

    required = (
        "interval_sec",
        "min_duration_sec",
        "max_duration_sec",
        "target_valid_samples",
        "early_quality_checkpoint_sec",
        "early_futility_checkpoint_sec",
        "min_valid_sample_ratio",
        "max_fetch_error_ratio",
    )
    missing = [name for name in required if name not in contract]
    if missing:
        raise ValueError(f"fast output short probe contract is incomplete: {', '.join(missing)}")
    if int(contract["max_duration_sec"]) > 3 * 3600:
        raise ValueError("short probe maximum duration exceeds 3 hours")
    if int(contract["min_duration_sec"]) > int(contract["max_duration_sec"]):
        raise ValueError("short probe minimum duration exceeds maximum duration")
    interval_sec = int(contract["interval_sec"])
    min_valid_pairs = max(1, math.ceil(len(candidates) * 0.80))

    plan: dict[str, Any] = {
        "schema": SHORT_PLAN_SCHEMA,
        "mode": SHORT_PLAN_MODE,
        "decision": SHORT_PLAN_DECISION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "would_start": False,
        "collect_started": False,
        "requires_explicit_user_approval_for_actual_collect": True,
        "strategy_accepted": False,
        "oos_edge_accepted": False,
        "long_run_required_now": False,
        "replay_allowed": False,
        "backtest_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "source": {
            "fast_output_path": str(source),
            "fast_output_sha256": _sha256_file(source),
            "fast_decision": fast["decision"],
            "diagnostic_freeze_path": str(freeze_path),
            "diagnostic_freeze_sha256": _sha256_file(freeze_path),
            "original_forward_plan_path": str(original_plan_path),
            "original_forward_plan_sha256": _sha256_file(original_plan_path),
            "diagnostic_data_role": "discovery_only_excluded_from_short_probe_evaluation",
        },
        "instrument_scope": {
            "exchanges": ["mexc", "gateio"],
            "contract_type": "linear_perp",
            "quote_and_settle": "USDT",
            "candidate_bases": candidates,
            "candidate_selection": "sealed from diagnostic episodes before the independent short probe",
        },
        "collection_contract": {
            "interval_sec": interval_sec,
            "min_duration_sec": int(contract["min_duration_sec"]),
            "max_duration_sec": int(contract["max_duration_sec"]),
            "target_valid_samples": int(contract["target_valid_samples"]),
            "early_quality_checkpoint_sec": int(contract["early_quality_checkpoint_sec"]),
            "early_futility_checkpoint_sec": int(contract["early_futility_checkpoint_sec"]),
            "min_valid_sample_ratio": float(contract["min_valid_sample_ratio"]),
            "max_fetch_error_ratio": float(contract["max_fetch_error_ratio"]),
            "target_notional_quote": 100.0,
            "depth_limit": 20,
            "min_valid_pairs_per_sample": min_valid_pairs,
            "max_index_divergence_bps": float(original_contract.get("max_index_divergence_bps") or 100.0),
            "max_mark_index_divergence_bps": float(
                original_contract.get("max_mark_index_divergence_bps") or 200.0
            ),
            "max_quote_age_sec": float(original_contract.get("max_quote_age_sec") or 10.0),
            "max_cross_venue_skew_sec": float(original_contract.get("max_cross_venue_skew_sec") or 5.0),
            "round_trip_fee_bps": 39.0,
            "slippage_bps": 10.0,
            "operational_buffer_bps": 20.0,
            "fixed_total_cost_bps": float((fast.get("cost_gate") or {}).get("fixed_total_cost_bps") or 0.0),
            "retry_attempts": 3,
            "retry_initial_backoff_sec": 0.5,
            "independence_gap_samples": 60,
            "canonical_artifact": "atomic immutable JSON segment per sample",
            "segment_overwrite_allowed": False,
        },
        "sequential_stop_contract": {
            "quality_checkpoint_min_attempts": math.ceil(int(contract["early_quality_checkpoint_sec"]) / interval_sec),
            "quality_min_valid_sample_ratio": float(contract["min_valid_sample_ratio"]),
            "quality_max_fetch_error_ratio": float(contract["max_fetch_error_ratio"]),
            "futility_checkpoint_min_attempts": math.ceil(
                int(contract["early_futility_checkpoint_sec"]) / interval_sec
            ),
            "futility_if_zero_fixed_cost_positive_samples": True,
            "success_min_valid_samples": int(contract["target_valid_samples"]),
            "success_min_independent_episodes": 30,
            "success_min_event_bases": 3,
            "success_max_top1_base_concentration": 0.50,
            "success_requires_positive_samples_in_both_chronological_halves": True,
            "independent_episode_definition": (
                "same base+direction positive samples belong to one episode until at least "
                "60 sample indices separate consecutive positive samples"
            ),
            "safety_cap": "stop no later than 3 hours and classify insufficient evidence if success is absent",
            "automatic_long_run_transition": False,
        },
        "fail_closed_contract": {
            "thresholds_frozen_before_independent_short_probe": True,
            "threshold_mutation_after_start_allowed": False,
            "candidate_mutation_after_start_allowed": False,
            "any_quality_or_provenance_violation": "stop and classify rejected or stopped_incomplete",
            "missing_metric": "fail the affected gate; never impute or assume pass",
            "decision_log_required": True,
            "trade_recommendation_allowed": False,
            "automatic_next_stage_allowed": False,
        },
        "required_sample_fields": [
            "contract identity and multiplier on both venues",
            "exchange and receive timestamps",
            "bid/ask depth and executable VWAP for $100 on both venues",
            "mark/index prices and funding schedule on both venues",
            "fixed-cost and public-base-fee net edge",
            "explicit validation and failure reasons",
        ],
        "blocked_actions": [
            "start_without_explicit_visible_confirmation",
            "change_candidate_bases_after_start",
            "change_thresholds_after_start",
            "reuse_diagnostic_data_as_short_probe",
            "automatic_long_run",
            "grid_tuning",
            "strategy_acceptance",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ],
        "next_valid_move": "implement_and_verify_resumable_short_probe_collector_without_starting_it",
        "output_path": str(destination),
    }
    if float(plan["collection_contract"]["fixed_total_cost_bps"]) <= 0:
        raise ValueError("short probe fixed cost hurdle must be positive")
    component_total = sum(
        float(plan["collection_contract"][name])
        for name in ("round_trip_fee_bps", "slippage_bps", "operational_buffer_bps")
    )
    if not math.isclose(component_total, float(plan["collection_contract"]["fixed_total_cost_bps"])):
        raise ValueError("short probe cost components do not match the fixed cost hurdle")
    _atomic_write_json(destination, plan)
    return plan


def _validate_fast_output(value: dict[str, Any]) -> None:
    if value.get("schema") != FAST_SCHEMA or value.get("mode") != FAST_MODE:
        raise ValueError("unsupported fast pipeline schema/mode")
    if value.get("decision") != DECISION_READY:
        raise ValueError("fast pipeline must explicitly pass the short-probe gate")
    if value.get("strategy_accepted") is not False or value.get("oos_evidence") is not False:
        raise ValueError("fast pipeline safety flags are not fail-closed")
    diagnostics = value.get("diagnostics") or {}
    if diagnostics.get("eligible_for_short_probe") is not True or diagnostics.get("eligibility_reasons"):
        raise ValueError("fast pipeline diagnostics are not eligible for a short probe")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sealed 1-3h public short execution probe plan")
    parser.add_argument("--fast-output", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    plan = build_short_probe_plan(args.fast_output, args.out)
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
