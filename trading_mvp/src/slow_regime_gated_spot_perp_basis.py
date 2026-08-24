from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spot_perp_basis_mean_reversion import (
    SpotPerpBasisPlanConfig,
    classify_basis_signal,
    round_trip_cost_hurdle_bps,
)

BRANCH_ID = "slow_regime_gated_spot_perp_basis_v1"
MODE = "slow_regime_gated_spot_perp_basis_planonly"
DEFAULT_REJECTED_COLLECT_RUN_ID = "spot_perp_basis_collect_20260819_083140"

FROZEN_CONTRACT: dict[str, Any] = {
    "schema": "trading_mvp_slow_regime_gated_spot_perp_basis_planonly_v1",
    "branch": BRANCH_ID,
    "join_rule": "AND",
    "not_or_portfolio": True,
    "thesis": (
        "Enter long-spot/short-perp basis mean-reversion only when the same "
        "non-Binance base is already in a frozen 1h compression or valid 1h "
        "retest regime against a 4h context. Funding is a blocking filter, "
        "never PnL. Negative basis stays blocked because it needs a spot short."
    ),
    "parents": [
        "spot_perp_basis_mean_reversion_no_funding",
        "slow_liquidity_regime_breakout_retest",
    ],
    "new_hypothesis": True,
    "regime": {
        "direction": "long_only_spot_context",
        "primary_timeframe": "1h",
        "context_timeframe": "4h",
        "disabled_timeframe": "15m",
        "lookback_1h_bars": 96,
        "context_4h_bars": 42,
        "compression_range_width_max_atr": 1.2,
        "compression_min_bars": 24,
        "breakout_close_buffer_bps": 60.0,
        "volume_percentile_min": 0.7,
        "retest_window_bars": 12,
        "retest_tolerance_atr": 0.35,
        "allowed_regime_states": ["compression", "valid_retest"],
    },
    "basis": {
        "formula": "(perp_mid_or_mark - spot_mid) / spot_mid * 10000",
        "positive_entry": "long_spot_short_perp",
        "negative_entry": "blocked_without_spot_short",
        "spot_fee_bps_per_side": 10.0,
        "perp_fee_bps_per_side": 10.0,
        "spot_slippage_bps_per_side": 5.0,
        "perp_slippage_bps_per_side": 5.0,
        "adverse_basis_buffer_bps": 20.0,
        "max_spot_spread_bps": 20.0,
        "max_perp_spread_bps": 20.0,
        "max_adverse_funding_rate": -0.0003,
        "allow_spot_short": False,
        "funding_counted_as_pnl": False,
    },
    "feasibility": {
        "min_bases": 10,
        "min_independent_events": 100,
        "min_venues": 2,
        "max_single_base_event_fraction": 0.25,
        "min_profit_factor": 1.2,
        "min_positive_walk_forward_ratio": 0.60,
    },
    "blocked_evidence": [
        "rejected_incomplete_collect_not_evidence",
        "slow_liquidity_14_event_sample_not_retunable",
        "or_union_of_parent_universes",
        "grid_or_post_hoc_threshold_fit",
    ],
}


def frozen_contract_hash() -> str:
    encoded = json.dumps(FROZEN_CONTRACT, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ComboPlanConfig:
    min_bases: int = 10
    min_independent_events: int = 100
    min_venues: int = 2
    max_single_base_event_fraction: float = 0.25
    basis: SpotPerpBasisPlanConfig = SpotPerpBasisPlanConfig()


def _upper_unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        item = str(raw or "").strip().upper()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return sorted(ordered)


def extract_paired_ok_bases(probe: dict[str, Any] | None) -> list[str]:
    if not probe:
        return []
    summary = probe.get("summary") or {}
    if isinstance(summary.get("paired_ok_bases"), list) and summary.get("paired_ok_bases"):
        return _upper_unique(list(summary["paired_ok_bases"]))
    probe_ref = probe.get("probe_reference") or {}
    if isinstance(probe_ref.get("paired_ok_bases"), list) and probe_ref.get("paired_ok_bases"):
        return _upper_unique(list(probe_ref["paired_ok_bases"]))
    rows = probe.get("rows") or []
    bases = [row.get("base") for row in rows if isinstance(row, dict) and bool(row.get("paired_ok"))]
    return _upper_unique(bases)


def extract_identity_bases(identity: dict[str, Any] | None) -> list[str]:
    if not identity:
        return []
    block = identity.get("identity_acceptance") or {}
    accepted = block.get("accepted_bases") or identity.get("accepted_bases") or []
    if not isinstance(accepted, list):
        return []
    return _upper_unique(accepted)


def universe_intersection(left: list[str], right: list[str]) -> list[str]:
    return sorted(set(_upper_unique(left)) & set(_upper_unique(right)))


def classify_combo_signal(
    *,
    spot_mid: float,
    perp_mid: float,
    spot_spread_bps: float,
    perp_spread_bps: float,
    funding_rate: float | None,
    regime_state: str,
    cfg: ComboPlanConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or ComboPlanConfig()
    allowed_regimes = set(FROZEN_CONTRACT["regime"]["allowed_regime_states"])
    basis = classify_basis_signal(
        spot_mid=spot_mid,
        perp_mid=perp_mid,
        spot_spread_bps=spot_spread_bps,
        perp_spread_bps=perp_spread_bps,
        funding_rate=funding_rate,
        cfg=cfg.basis,
    )
    reasons = list(basis["reasons"])
    regime_ok = regime_state in allowed_regimes
    if not regime_ok:
        reasons.append("slow_regime_absent")

    allowed = bool(basis["allowed"]) and regime_ok
    combo_signal = "blocked"
    if allowed and basis["signal"] == "long_spot_short_perp":
        combo_signal = "regime_and_long_spot_short_perp"
    elif regime_ok:
        combo_signal = f"regime_but_{basis['signal']}"

    return {
        "combo_signal": combo_signal,
        "allowed": allowed,
        "regime_state": regime_state,
        "regime_ok": regime_ok,
        "basis_signal": basis["signal"],
        "basis_allowed": basis["allowed"],
        "basis_bps": basis["basis_bps"],
        "cost_hurdle_bps": basis["cost_hurdle_bps"],
        "needs_spot_short": basis["needs_spot_short"],
        "join_rule": "AND",
        "reasons": reasons,
    }


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_planonly_report(
    *,
    repo_root: Path,
    output_path: Path | None = None,
    probe_path: Path | None = None,
    identity_path: Path | None = None,
    rejected_collect_run_id: str = DEFAULT_REJECTED_COLLECT_RUN_ID,
    cfg: ComboPlanConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or ComboPlanConfig()
    analysis_root = repo_root / "exports" / "trading-mvp" / "analysis"
    if probe_path is None:
        probe_path = analysis_root / "spot_perp_basis_public_probe_20260818_200756.json"
    if identity_path is None:
        identity_path = analysis_root / "slow_liquidity_history_recollect_quality_v6_identity_accepted_rebind.json"

    probe = _load_json(probe_path)
    identity = _load_json(identity_path)
    probe_bases = extract_paired_ok_bases(probe)
    identity_bases = extract_identity_bases(identity)
    intersection = universe_intersection(probe_bases, identity_bases)
    intersection_count = len(intersection)
    feasible = intersection_count >= cfg.min_bases
    hurdle = round_trip_cost_hurdle_bps(cfg.basis)
    plan_hash = frozen_contract_hash()

    if feasible:
        decision = "SLOW_REGIME_GATED_SPOT_PERP_BASIS_PLANONLY_READY_FOR_PAIRED_HISTORY_PREFLIGHT"
        reason = (
            "AND PlanOnly is frozen. Named artifacts currently share enough bases "
            "for a later paired-history preflight. This is not collect, replay, "
            "evaluator, or edge proof."
        )
        next_moves = [
            "Build a read-only paired-history preflight only for intersection bases.",
            "Do not start a collector, evaluator, OOS, grid, paper, or live run.",
            "Do not use the rejected incomplete snapshot collect as evidence.",
        ]
    else:
        decision = "SLOW_REGIME_GATED_SPOT_PERP_BASIS_PLANONLY_INFEASIBLE_ON_CURRENT_NAMED_ARTIFACTS"
        reason = (
            "AND PlanOnly is frozen. Current named probe and identity universes "
            f"intersect in {intersection_count} bases, below min_bases="
            f"{cfg.min_bases}. The hypothesis stays in the bank as "
            "INFEASIBLE_ON_CURRENT_DATA. This does not reopen either parent branch "
            "and does not authorize a collect."
        )
        next_moves = [
            "Keep this combo PlanOnly frozen; do not retune thresholds.",
            "A later combo requires a new named universe where both legs exist, then a new hash-bound PlanOnly.",
            "Do not resume the rejected spot-perp snapshot collect.",
            "Do not retune slow-liquidity on the 14-event sample.",
        ]

    return {
        "schema": FROZEN_CONTRACT["schema"],
        "mode": MODE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "selected_branch": BRANCH_ID,
        "plan_hash": plan_hash,
        "research_only": True,
        "would_start": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "evaluator_or_oos_authorized": False,
        "strategy_accepted": False,
        "reason": reason,
        "hypothesis": FROZEN_CONTRACT,
        "economics_policy": {
            "optimize_for": "net_expectancy_after_costs",
            "base_fee_model": "base/VIP0/no-volume fees",
            "minimum_entry_basis_hurdle_bps": round(hurdle, 6),
            "slow_regime_gross_hurdle_bps": 245.0,
            "slow_regime_min_target_bps": 300.0,
            "funding_counted_as_pnl": False,
            "winrate_policy": "supporting metric only",
        },
        "feasibility": {
            "probe_path": str(probe_path) if probe_path else None,
            "identity_path": str(identity_path) if identity_path else None,
            "probe_bases": probe_bases,
            "probe_base_count": len(probe_bases),
            "identity_bases": identity_bases,
            "identity_base_count": len(identity_bases),
            "intersection_bases": intersection,
            "intersection_count": intersection_count,
            "min_bases": cfg.min_bases,
            "min_independent_events": cfg.min_independent_events,
            "feasible_on_named_artifacts": feasible,
        },
        "blocked_evidence": [
            "rejected_incomplete_collect_not_evidence",
            "slow_liquidity_14_event_sample_not_retunable",
        ],
        "rejected_collect_run_id": rejected_collect_run_id,
        "acceptance_gates": {
            "join_rule": "AND",
            "sample_size": f">= {cfg.min_independent_events} independent AND-events after cooldown",
            "market_diversity": (
                f">= {cfg.min_bases} intersection bases, single-base net PnL share "
                f"<= {cfg.max_single_base_event_fraction:.0%}"
            ),
            "regime": "compression or valid_retest on 1h/4h frozen geometry",
            "basis": f"positive basis >= {hurdle:.1f} bps after round-trip costs",
            "oos": "holdout net PnL > 0 and profit factor >= 1.2",
            "walk_forward": ">= 60% positive folds with positive median expectancy",
            "stress": "non-negative under 2x slippage, +50% fee buffer, delayed entry, partial-fill haircut",
        },
        "rejection_gates": [
            "empty_or_small_universe_intersection",
            "slow_regime_absent",
            "basis_below_cost_hurdle",
            "negative_basis_requires_spot_short",
            "too_few_independent_and_events",
            "uses_rejected_incomplete_collect",
            "retunes_slow_liquidity_on_14_events",
            "or_portfolio_instead_of_and",
        ],
        "next_valid_moves": next_moves,
        "blocked_moves": [
            "actual_collect_without_new_exact_visible_approval",
            "resume_rejected_incomplete_spot_perp_collect",
            "evaluator_or_oos",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "funding_payout_rescue",
        ],
        "output_path": str(output_path) if output_path else None,
    }


def write_planonly_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(output_path)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="AND combo PlanOnly: slow regime gates spot/perp basis")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--probe-path", default="")
    parser.add_argument("--identity-path", default="")
    args = parser.parse_args()

    output_path = Path(args.out)
    report = build_planonly_report(
        repo_root=Path(args.repo_root),
        output_path=output_path,
        probe_path=Path(args.probe_path) if args.probe_path else None,
        identity_path=Path(args.identity_path) if args.identity_path else None,
    )
    write_planonly_report(report, output_path)
    print(json.dumps({"decision": report["decision"], "plan_hash": report["plan_hash"], "intersection_count": report["feasibility"]["intersection_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
