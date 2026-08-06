from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROBE_SCHEMA = "pit_linear_perp_cross_venue_forward_probe_v1"
PROBE_MODE = "pit_linear_perp_cross_venue_forward_public_probe"
PROBE_DECISION = "PIT_LINEAR_PERP_FORWARD_PROBE_ACCEPTED_READY_FOR_OOS_APPROVAL_PACKET"
PLAN_SCHEMA = "pit_linear_perp_cross_venue_forward_oos_plan_v1"
PLAN_MODE = "pit_linear_perp_cross_venue_forward_oos_collect_approval_packet_planonly"
PLAN_DECISION = "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY"


@dataclass(frozen=True)
class ForwardOosPlanConfig:
    interval_sec: int = 300
    target_valid_cycles: int = 800
    min_active_span_sec: int = 72 * 3600
    max_active_duration_sec: int = 96 * 3600
    min_identity_pairs: int = 10
    min_valid_pair_coverage_ratio: float = 0.75
    max_attempt_error_ratio: float = 0.20
    retry_attempts: int = 3
    retry_initial_backoff_sec: float = 0.5
    target_notional_quote: float = 100.0
    depth_limit: int = 20
    max_index_divergence_bps: float = 100.0
    max_mark_index_divergence_bps: float = 200.0
    max_quote_age_sec: float = 10.0
    max_cross_venue_skew_sec: float = 5.0

    def validate(self) -> None:
        positive = {
            "interval_sec": self.interval_sec,
            "target_valid_cycles": self.target_valid_cycles,
            "min_active_span_sec": self.min_active_span_sec,
            "max_active_duration_sec": self.max_active_duration_sec,
            "min_identity_pairs": self.min_identity_pairs,
            "retry_attempts": self.retry_attempts,
            "retry_initial_backoff_sec": self.retry_initial_backoff_sec,
            "target_notional_quote": self.target_notional_quote,
            "depth_limit": self.depth_limit,
            "max_index_divergence_bps": self.max_index_divergence_bps,
            "max_mark_index_divergence_bps": self.max_mark_index_divergence_bps,
            "max_quote_age_sec": self.max_quote_age_sec,
            "max_cross_venue_skew_sec": self.max_cross_venue_skew_sec,
        }
        invalid = [name for name, value in positive.items() if float(value) <= 0]
        if invalid:
            raise ValueError(f"forward OOS plan parameters must be positive: {', '.join(invalid)}")
        if self.max_active_duration_sec < self.min_active_span_sec:
            raise ValueError("max_active_duration_sec must be >= min_active_span_sec")
        if not 0 < self.min_valid_pair_coverage_ratio <= 1:
            raise ValueError("min_valid_pair_coverage_ratio must be in (0, 1]")
        if not 0 <= self.max_attempt_error_ratio < 1:
            raise ValueError("max_attempt_error_ratio must be in [0, 1)")
        max_attempts = math.ceil(self.max_active_duration_sec / self.interval_sec) + 1
        if self.target_valid_cycles > max_attempts:
            raise ValueError("target_valid_cycles exceeds maximum scheduled attempts")


def build_forward_oos_plan(
    probe_path: str | Path,
    output_path: str | Path,
    config: ForwardOosPlanConfig | None = None,
) -> dict[str, Any]:
    cfg = config or ForwardOosPlanConfig()
    cfg.validate()
    source = Path(probe_path).resolve()
    destination = Path(output_path).resolve()
    probe = _load_probe(source)
    if destination == source:
        raise ValueError("plan output must not overwrite probe evidence")
    if destination.exists():
        raise FileExistsError(f"forward OOS plan already exists: {destination}")

    discovery = probe.get("discovery_universe") or {}
    all_bases = sorted({str(value).upper() for value in discovery.get("bases") or [] if str(value).strip()})
    if len(all_bases) != int(discovery.get("count") or 0):
        raise ValueError("probe discovery universe count mismatch")
    observed_universe_hash = _canonical_sha256({"bases": all_bases})
    if observed_universe_hash != str(discovery.get("sha256") or ""):
        raise ValueError("probe discovery universe SHA-256 mismatch")

    pair_rows = probe.get("pairs") or []
    if not isinstance(pair_rows, list):
        raise ValueError("probe pairs must be a list")
    by_base: dict[str, dict[str, Any]] = {}
    for row in pair_rows:
        if not isinstance(row, dict):
            raise ValueError("probe pair row must be an object")
        base = str(row.get("base") or "").upper()
        if not base or base in by_base:
            raise ValueError("probe pairs contain missing or duplicate bases")
        by_base[base] = row
    if set(by_base) != set(all_bases):
        raise ValueError("probe pair bases do not cover the sealed discovery universe")

    identity_bases = sorted(base for base, row in by_base.items() if row.get("provisional_identity_match") is True)
    quarantine_bases = sorted(set(all_bases) - set(identity_bases))
    if len(identity_bases) < cfg.min_identity_pairs:
        raise ValueError(
            f"probe has only {len(identity_bases)} identity pairs; plan requires at least {cfg.min_identity_pairs}"
        )
    min_valid_pairs = max(1, math.ceil(len(identity_bases) * cfg.min_valid_pair_coverage_ratio))
    max_attempt_cycles = math.ceil(cfg.max_active_duration_sec / cfg.interval_sec) + 1
    expected_attempts_at_min_span = math.floor(cfg.min_active_span_sec / cfg.interval_sec) + 1
    diagnostics = probe.get("summary") or {}
    probe_cost = probe.get("cost_model") or {}

    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "decision": PLAN_DECISION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "would_start": False,
        "collect_started": False,
        "requires_explicit_user_approval_for_actual_collect": True,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "backtest_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_ready": False,
        "instrument_scope": {
            "contract_type": "linear_perp",
            "exchanges": ["mexc", "gateio"],
            "quote_and_settle": "USDT",
            "supports_spot_objective": False,
            "spot_branch_status": "rejected_on_prior_evidence_not_reopened",
        },
        "source": {
            "probe_path": str(source),
            "probe_sha256": _sha256_file(source),
            "probe_decision": probe["decision"],
            "availability_sha256": (probe.get("source") or {}).get("availability_sha256"),
            "discovery_window_role": "discovery_only_excluded_from_oos_evaluation",
        },
        "sealed_universe": {
            "all_discovery_bases": all_bases,
            "all_discovery_bases_sha256": observed_universe_hash,
            "identity_evaluation_bases": identity_bases,
            "identity_evaluation_bases_sha256": _canonical_sha256({"bases": identity_bases}),
            "identity_quarantine_bases": quarantine_bases,
            "selection_rule": (
                "collect every discovery base; evaluate only bases passing the pre-OOS index-parity identity rule; "
                "never select by observed edge or PnL"
            ),
        },
        "probe_diagnostics": {
            "provisional_identity_pairs": int(diagnostics.get("provisional_identity_pairs") or 0),
            "fully_valid_pairs": int(diagnostics.get("fully_valid_pairs") or 0),
            "one_shot_cost_positive_pairs": int(diagnostics.get("one_shot_cost_positive_pairs") or 0),
            "one_shot_observed_base_fee_cost_positive_pairs": int(
                diagnostics.get("one_shot_observed_base_fee_cost_positive_pairs") or 0
            ),
            "interpretation": "data-path feasibility only; no expectancy or candidate claim",
        },
        "collection_contract": {
            **asdict(cfg),
            "min_valid_pairs_per_cycle": min_valid_pairs,
            "max_attempt_cycles": max_attempt_cycles,
            "expected_attempts_at_min_span": expected_attempts_at_min_span,
            "stop_success": (
                "elapsed_active_sec >= min_active_span_sec AND valid_cycle_count >= target_valid_cycles "
                "AND failed_cycle_count / attempt_cycle_count <= max_attempt_error_ratio"
            ),
            "stop_failure": (
                "elapsed_active_sec >= max_active_duration_sec without success; finalize as insufficient evidence"
            ),
            "failed_attempt_policy": "append and retain; never overwrite; failed attempts do not increment valid_cycle_count",
        },
        "valid_cycle_definition": {
            "required_pair_count": min_valid_pairs,
            "pair_universe": "sealed_universe.identity_evaluation_bases",
            "required_pair_evidence": [
                "active linear USDT perpetual contract and positive contract multiplier on both venues",
                "cross-venue index divergence within max_index_divergence_bps",
                "mark/index divergence within max_mark_index_divergence_bps on each venue",
                "exchange timestamp, receive timestamp and quote age within max_quote_age_sec",
                "cross-venue depth timestamp skew within max_cross_venue_skew_sec",
                "both bid and ask depth executable for target_notional_quote on both venues",
                "funding rate, funding interval and next settlement timestamp on both venues",
            ],
            "identity_collision_policy": "fail closed per pair and retain reason in the cycle segment",
            "imputation_allowed": False,
            "forward_fill_allowed": False,
        },
        "cost_contract": {
            "probe_total_cost_bps": probe_cost.get("total_cost_bps"),
            "base_fee_mode": "public contract VIP0/base taker rates per venue and base",
            "fee_fallback": "fixed conservative probe hurdle if a public fee field is missing",
            "slippage_and_operational_stress_required": True,
            "funding_cashflows": "discrete settlements only; no continuous accrual",
            "one_shot_probe_cost_positive_pairs": int(diagnostics.get("one_shot_cost_positive_pairs") or 0),
            "one_shot_probe_observed_base_fee_cost_positive_pairs": int(
                diagnostics.get("one_shot_observed_base_fee_cost_positive_pairs") or 0
            ),
        },
        "durability_contract": {
            "canonical_cycle_artifact": "atomic immutable segment JSON per attempt cycle",
            "segment_overwrite_allowed": False,
            "manifest_write": "atomic replace",
            "resume": "same run_id only; validate plan hash, config, universe hashes and contiguous segments",
            "interrupted_run_status": "STOPPED_INCOMPLETE and visibly resumable",
            "quality_shortfall_status": "COMPLETED_INSUFFICIENT_EVIDENCE and not silently extended",
        },
        "evaluation_protocol": {
            "discovery_data_reused_as_oos": False,
            "parameter_grid_allowed": False,
            "minimum_independent_oos_events": 100,
            "chronological_holdout_required": True,
            "walk_forward_min_pass_ratio": 0.60,
            "fee_slippage_latency_gap_stress_required": True,
            "venue_and_base_concentration_caps_required": True,
            "optimization_target": "net expectancy after all costs",
        },
        "blocked_actions": [
            "start_collect_without_explicit_user_approval",
            "overwrite_failed_cycles",
            "count_failed_attempts_as_valid_cycles",
            "drop_bases_by_probe_edge_or_pnl",
            "reuse_discovery_as_oos",
            "replay_or_backtest_before_forward_data_quality",
            "grid_optimization",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ],
        "next_valid_move": "implement_and_verify_visible_resumable_forward_oos_collector_without_starting_it",
        "output_path": str(destination),
    }
    _atomic_write_json(destination, plan)
    return plan


def _load_probe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"accepted probe not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid accepted probe JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("accepted probe must be a JSON object")
    if value.get("schema") != PROBE_SCHEMA or value.get("mode") != PROBE_MODE:
        raise ValueError("unsupported accepted probe schema/mode")
    if value.get("decision") != PROBE_DECISION:
        raise ValueError("accepted probe decision is required")
    if value.get("strategy_accepted") is not False or value.get("collect_started") is not False:
        raise ValueError("accepted probe safety flags are not fail-closed")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    parser = argparse.ArgumentParser(description="Build a sealed MEXC/Gate linear-perp forward-OOS collect plan")
    parser.add_argument("--probe", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval-sec", type=int, default=300)
    parser.add_argument("--target-valid-cycles", type=int, default=800)
    parser.add_argument("--min-active-span-sec", type=int, default=72 * 3600)
    parser.add_argument("--max-active-duration-sec", type=int, default=96 * 3600)
    parser.add_argument("--min-identity-pairs", type=int, default=10)
    parser.add_argument("--min-valid-pair-coverage-ratio", type=float, default=0.75)
    args = parser.parse_args()
    report = build_forward_oos_plan(
        args.probe,
        args.out,
        ForwardOosPlanConfig(
            interval_sec=args.interval_sec,
            target_valid_cycles=args.target_valid_cycles,
            min_active_span_sec=args.min_active_span_sec,
            max_active_duration_sec=args.max_active_duration_sec,
            min_identity_pairs=args.min_identity_pairs,
            min_valid_pair_coverage_ratio=args.min_valid_pair_coverage_ratio,
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
