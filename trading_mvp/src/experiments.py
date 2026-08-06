from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_VERDICTS = {
    "untested",
    "failed",
    "inconclusive",
    "promising",
    "accepted_research",
    "rejected",
    "blocked",
}


SETUP_REGISTRY: list[dict[str, Any]] = [
    {
        "setup_id": "flow_continue",
        "family": "spot_or_perp_microstructure",
        "source_claim_family": "orderbook_tape_continuation",
        "source_participants": ["Михаил Латогузов", "Андрей Демченко"],
        "status": "implemented_spot_replay",
        "description": "Continuation setup: top-of-book imbalance and signed trade flow point in the same direction.",
        "required_data": ["bbo", "depth_or_top_qty", "trades"],
        "entry_logic": "Long when bid-side imbalance and buy flow pass thresholds; short only when replay allows short.",
        "exit_logic": ["take_profit_bps", "stop_loss_bps", "max_hold_sec", "force_end"],
        "risk_gates": ["max_spread_bps", "market_quality_filter", "min_net_take_profit_bps", "fill_probability"],
        "acceptance_gates": ["min_trades", "net_pnl_quote>0", "expectancy_quote>0", "profit_factor>=1.2"],
        "no_go": ["Do not use win rate without expectancy and costs."],
    },
    {
        "setup_id": "fade_exhaustion",
        "family": "spot_or_perp_microstructure",
        "source_claim_family": "absorption_after_aggressive_flow",
        "source_participants": ["Михаил Латогузов", "Андрей Демченко", "Нарэк Григорян"],
        "status": "implemented_spot_replay",
        "description": "Fade setup: trade flow is aggressive one way while top-of-book imbalance shows absorption on the other side.",
        "required_data": ["bbo", "depth_or_top_qty", "trades"],
        "entry_logic": "Long after sell flow with bid absorption; short after buy flow with ask absorption when replay allows short.",
        "exit_logic": ["take_profit_bps", "stop_loss_bps", "max_hold_sec", "force_end"],
        "risk_gates": ["max_spread_bps", "market_quality_filter", "min_net_take_profit_bps", "fill_probability"],
        "acceptance_gates": ["min_trades", "net_pnl_quote>0", "expectancy_quote>0", "profit_factor>=1.2"],
        "no_go": ["Do not call this market-maker manipulation; it is an observable absorption hypothesis."],
    },
    {
        "setup_id": "perp_replay",
        "family": "perp_microstructure_research",
        "source_claim_family": "futures_prop_orderbook",
        "source_participants": ["Игорь Андреев", "HAMAHA / Максим HAMAHA", "Андрей Демченко"],
        "status": "implemented_research_skeleton",
        "description": "Perpetual long/short replay with funding, mark/index and maker/taker accounting.",
        "required_data": ["bbo", "depth_or_top_qty", "trades", "mark_price", "index_price", "funding_rate"],
        "entry_logic": "Reuse flow_continue and fade_exhaustion with short allowed and funding included.",
        "exit_logic": ["take_profit_bps", "stop_loss_bps", "max_hold_sec", "force_end"],
        "risk_gates": ["market_quality_filter", "min_net_take_profit_bps", "funding_drag", "venue_risk"],
        "acceptance_gates": ["min_trades", "net_pnl_quote>0", "expectancy_quote>0", "profit_factor>=1.2"],
        "no_go": ["Do not treat perp access as proof of live profitability."],
    },
    {
        "setup_id": "liquidity_sweep_reversal",
        "family": "perp_microstructure_research",
        "source_claim_family": "stop_cascade_liquidity_sweep",
        "source_participants": ["Нарэк Григорян", "Андрей Демченко", "HAMAHA / Максим HAMAHA"],
        "status": "planned_after_perp_replay",
        "description": "Neutral detector for sweep/cascade followed by failed continuation and reversal.",
        "required_data": ["depth_updates", "trades", "mark_price", "index_price"],
        "entry_logic": "Enter only after an observable sweep event, reversal confirmation, and acceptable fill/adverse-move profile.",
        "exit_logic": ["post_sweep_reversal_target", "invalidation_after_continuation", "max_hold_sec", "force_end"],
        "risk_gates": ["no_intent_labels", "max_spread_bps", "trade_density", "adverse_move_after_fill"],
        "acceptance_gates": ["out_of_sample_positive_expectancy", "profit_factor>=1.2", "per_market_concentration_cap"],
        "no_go": ["Do not infer manipulative intent from order-book behavior alone."],
    },
    {
        "setup_id": "large_move_breakout",
        "family": "spot_or_perp_microstructure",
        "source_claim_family": "large_move_breakout_momentum",
        "source_participants": ["Claude Code (engineering review)"],
        "status": "implemented_replay_oos_failed",
        "description": "Momentum breakout: price breaks the window extreme by breakout_bps with signed-flow confirmation; sized for a large TP that exceeds round-trip fees.",
        "required_data": ["bbo", "depth_or_top_qty", "trades"],
        "entry_logic": "Long when ask breaks above prior window max by breakout_bps and signed flow is positive; short symmetrically when replay allows short.",
        "exit_logic": ["take_profit_bps", "stop_loss_bps", "max_hold_sec", "force_end"],
        "risk_gates": ["max_spread_bps", "min_net_take_profit_bps", "market_quality_filter", "per_market_concentration_cap"],
        "acceptance_gates": ["out_of_sample_positive_expectancy", "min_trades", "profit_factor>=1.2"],
        "no_go": ["Needs dense WebSocket BBO, not sparse REST snapshots.", "Do not promote an in-sample-only edge that fails holdout."],
    },
    {
        "setup_id": "cross_sectional_momentum_daily",
        "family": "daily_portfolio_research",
        "source_claim_family": "cross_sectional_momentum",
        "source_participants": ["Claude Code (edge hypothesis backlog H1, 2026-07-02)"],
        "status": "implemented_daily_backtest_v1",
        "description": "Weekly-rebalanced long/short portfolio: rank perp markets by trailing 30/60/90d return, long top bucket, short bottom bucket, funding and fee scenarios included.",
        "required_data": ["daily_klines", "funding_rate_history", "universe_tags", "volume_quote"],
        "entry_logic": "At each weekly rebalance rank eligible markets by lookback return; long top bucket, short bottom bucket, equal weight, dollar-neutral.",
        "exit_logic": ["weekly_rebalance", "liquidity_filter_dropout"],
        "risk_gates": ["min_markets_per_side", "min_rolling_quote_volume", "funding_drag_accounting", "per_market_concentration_cap"],
        "acceptance_gates": [
            "lookback_selected_on_train_only",
            "oos_net_expectancy>0",
            "min_rebalances",
            "not_concentrated_in_few_markets",
            "survivorship_bias_documented",
        ],
        "no_go": [
            "Do not select lookback or scenario on OOS data.",
            "Universe snapshot is current top-volume contracts: survivorship bias must be reported with any positive result.",
        ],
    },
    {
        "setup_id": "cross_exchange_funding_carry",
        "family": "carry_research",
        "source_claim_family": "cross_exchange_funding_spread",
        "source_participants": ["Claude Code (edge hypothesis backlog H2, 2026-07-02)"],
        "status": "implemented_pair_analysis_v1",
        "description": "Delta-neutral perp-perp carry: short the leg with higher funding, long the leg with lower funding on another venue; income = funding spread, costs = maker legs (scenario G).",
        "required_data": ["funding_rate_history_multi_exchange", "daily_klines_both_venues", "volume_quote"],
        "entry_logic": "Enter only when trailing daily funding spread is stable (sign consistency gate) and exceeds cost + safety margin.",
        "exit_logic": ["spread_sign_flip", "spread_below_threshold", "venue_risk_event"],
        "risk_gates": ["basis_volatility", "sign_consistency", "min_capacity", "venue_risk", "leg_execution_fill"],
        "acceptance_gates": [
            "multiweek_forward_persistence",
            "net_spread_after_costs>0",
            "execution_gate_maker_fill_model",
            "capacity_aware_economics",
        ],
        "no_go": [
            "90d backward window alone is not proof of persistence.",
            "Do not treat mark-to-market basis swings as realized pnl.",
        ],
    },
    {
        "setup_id": "funding_basis_carry",
        "family": "carry_research",
        "source_claim_family": "funding_passive_crypto",
        "source_participants": ["Иван Шашков"],
        "status": "implemented_research_v1",
        "description": "Long spot plus short perp carry research with funding, basis, fees and slippage.",
        "required_data": ["spot_mid", "perp_mark_or_mid", "funding_rate", "next_funding_ts", "spread"],
        "entry_logic": "Enter only when funding is positive and spread/basis/liquidity gates pass.",
        "exit_logic": ["funding_negative", "score_degrades", "spread_too_wide", "force_end"],
        "risk_gates": ["basis_widening", "venue_risk", "counterparty_risk", "capital_lockup"],
        "acceptance_gates": ["7_to_30_day_positive_net", "fees_and_slippage_included", "basis_pnl_reported"],
        "no_go": ["Do not mix carry score into intraday microstructure alpha."],
    },
    {
        "setup_id": "gate_spot_perp_basis_convergence_history_v2",
        "family": "same_venue_structural_basis_research",
        "source_claim_family": "same_venue_spot_perp_basis_convergence",
        "source_participants": ["internal One-Week Historical Edge Sprint"],
        "status": "train_infeasible_closed_no_retune",
        "description": (
            "Gate long-spot/short-perp convergence after a cost-derived positive basis threshold, "
            "with funding reported separately and forbidden from rescuing price-only economics."
        ),
        "required_data": ["gate_spot_ohlcv", "gate_perp_ohlcv", "gate_mark_history", "gate_funding_history"],
        "entry_logic": "Enter at next hourly opens only after closed-hour basis reaches the frozen economic threshold.",
        "exit_logic": ["basis_converged_to_20bps", "72h_max_hold"],
        "risk_gates": ["base_api_costs", "train_liquidity", "funding_floor", "gap_abort", "no_oos_before_feasibility"],
        "acceptance_gates": ["train_episode_count", "price_only_expectancy", "profit_factor", "stress", "concentration"],
        "no_go": [
            "The frozen 132 bps threshold was absent in 100 train days; do not lower or retune it on this dataset.",
            "Do not run OOS, execution probe, paper-forward or live trading for this closed branch.",
        ],
    },
    {
        "setup_id": "cross_venue_dislocation",
        "family": "cross_venue_structural_research",
        "source_claim_family": "cross_venue_price_dislocation",
        "source_participants": ["internal research"],
        "status": "implemented_research_v1",
        "description": "Cross-venue price dislocation with executable bid/ask and transfer/latency cost gates.",
        "required_data": ["multi_venue_bbo", "venue_fees", "latency", "capacity"],
        "entry_logic": "Open only when executable spread exceeds all-leg costs and safety buffer.",
        "exit_logic": ["spread_convergence", "timeout", "venue_risk"],
        "risk_gates": ["venue_specific_costs", "stale_quote", "fill_risk", "counterparty_risk"],
        "acceptance_gates": ["chronological_oos", "walk_forward", "stress", "positive_net_expectancy"],
        "no_go": ["Do not infer executable arbitrage from mid prices."],
    },
    {
        "setup_id": "listing_event_drift_reversal",
        "family": "listing_event_research",
        "source_claim_family": "post_listing_drift_reversal",
        "source_participants": ["internal research"],
        "status": "implemented_planonly_v1",
        "description": "Long-only reversal after an observed post-listing selloff.",
        "required_data": ["point_in_time_listing_calendar", "ohlcv_horizon", "venue_fees"],
        "entry_logic": "Enter after fixed delay only when initial selloff crosses the fixed threshold.",
        "exit_logic": ["fixed_horizon"],
        "risk_gates": ["complete_horizon", "delist_freeze_haircut", "base_tier_costs"],
        "acceptance_gates": ["chronological_oos", "walk_forward", "stress", "min_trades"],
        "no_go": ["Never substitute the final available candle for a missing exit horizon."],
    },
    {
        "setup_id": "slow_liquidity_reversal",
        "family": "slow_structural_liquidity",
        "source_claim_family": "thin_market_liquidity_reversal",
        "source_participants": ["internal research"],
        "status": "implemented_research_v1",
        "description": "Slow reversal in thin non-Binance markets using historical OHLCV and liquidity gates.",
        "required_data": ["ohlcv", "volume", "spread_proxy", "point_in_time_universe"],
        "entry_logic": "Fixed non-HFT signal after a liquidity shock and reversal confirmation.",
        "exit_logic": ["target", "stop", "timeout"],
        "risk_gates": ["survivorship", "costs", "capacity", "venue_concentration"],
        "acceptance_gates": ["oos", "walk_forward", "stress", "economics"],
        "no_go": ["Do not tune on the validation slice."],
    },
    {
        "setup_id": "pit_universe_event_liquidity",
        "family": "point_in_time_structural_research",
        "source_claim_family": "universe_entry_exit_liquidity_anomaly",
        "source_participants": ["internal research"],
        "status": "collector_v2_ready",
        "description": "Forward point-in-time universe changes with non-Binance membership and liquidity state.",
        "required_data": ["first_seen", "last_seen", "tombstones", "binance_spot_reference", "bbo_spread"],
        "entry_logic": "Research events only after PIT quality and survivorship gates pass.",
        "exit_logic": ["fixed_event_horizon", "liquidity_failure", "force_end"],
        "risk_gates": ["complete_cycles", "exchange_errors", "tombstone_integrity", "venue_costs"],
        "acceptance_gates": ["independent_oos", "walk_forward", "stress", "paper_forward"],
        "no_go": ["Current exchange membership must not be backfilled into historical rows."],
    },
    {
        "setup_id": "venue_local_lottery_max_factor_v1",
        "family": "daily_cross_sectional_lottery_factor",
        "source_claim_family": "retail_lottery_demand_overpricing",
        "source_participants": ["internal Fast-First research"],
        "status": "evaluated_oos_insufficient_negative",
        "description": (
            "Same-venue four-leg perp factor: long the two lowest and short the two highest "
            "MAX20 markets, then hold for five closed daily bars."
        ),
        "required_data": ["daily_klines", "funding_rate_history", "non_binance_universe_tags", "volume_quote"],
        "entry_logic": (
            "Within each venue, rank the frozen liquid candidate pool by its maximum one-day "
            "close-to-close return over 20 completed days; enter at the next daily open."
        ),
        "exit_logic": ["fifth_daily_close", "no_overlap", "force_end_only_for_incomplete_data"],
        "risk_gates": [
            "base_api_four_leg_costs",
            "selected_leg_capacity",
            "venue_replication",
            "survivorship_ceiling",
            "funding_drag",
            "drawdown_and_concentration",
        ],
        "acceptance_gates": [
            "fixed_139_60_chronological_oos",
            "five_walk_forward_folds_no_refit",
            "price_only_net_after_costs>0",
            "residualized_momentum_liquidity_robustness>0",
            "stress_net_pnl>=0",
            "profit_factor>=1.2",
            "positive_event_rate>=0.60",
        ],
        "no_go": [
            "Do not retune prior funding, listing-event, slow-liquidity, momentum, residual-dispersion or HFT branches.",
            "Do not inspect or optimize OOS before the hash-bound evaluator and leakage tests are complete.",
            "No grid, execution probe, paper-forward, API keys or live orders in PlanOnly.",
            "The frozen OOS produced only two main events and negative net economics; do not retune this branch on the same data.",
        ],
    },
    {
        "setup_id": "venue_local_funding_pressure_reversal_v1",
        "family": "venue_local_directional_funding_pressure_reversal",
        "source_claim_family": "crowded_perpetual_positioning_reversal",
        "source_participants": ["internal Fast-First research"],
        "status": "plan_frozen_oos_not_evaluated",
        "description": (
            "Same-venue four-leg perpetual portfolio that fades extreme normalized funding pressure "
            "on MEXC and Gate independently."
        ),
        "required_data": [
            "daily_klines",
            "closed_funding_settlements",
            "non_binance_universe_tags",
            "volume_quote",
        ],
        "entry_logic": (
            "Within each venue, long the two lowest and short the two highest three-day normalized "
            "funding scores; enter at the next daily open after the closed signal day."
        ),
        "exit_logic": ["third_daily_close_after_entry", "no_overlap", "incomplete_data_fail_closed"],
        "risk_gates": [
            "base_api_four_leg_costs",
            "price_only_net_after_costs",
            "selected_leg_capacity",
            "venue_replication",
            "funding_interval_integrity",
            "drawdown_and_concentration",
        ],
        "acceptance_gates": [
            "fixed_139_60_chronological_oos",
            "five_walk_forward_folds_no_refit",
            "both_venues_price_only_expectancy>0",
            "price_only_profit_factor>=1.2",
            "stress_price_only_net_pnl>=0",
            "positive_event_rate>=0.60",
        ],
        "no_go": [
            "No OOS access before the plan hash, input Merkle and evaluator readiness are verified.",
            "No grid, OOS tuning, execution probe, paper-forward, API keys or live orders in PlanOnly.",
            "Funding cash flow cannot rescue negative price-only economics.",
        ],
    },
    {
        "setup_id": "ai_research_tooling",
        "family": "research_automation",
        "source_claim_family": "ai_trading_bots",
        "source_participants": ["Роман Пищулов / OpenClaw", "Тимур Султанов"],
        "status": "tooling_only",
        "description": "AI assists classification, monitoring and reporting; deterministic replay decides strategy acceptance.",
        "required_data": ["experiment_artifacts", "source_cards", "metrics"],
        "entry_logic": "No trade entry logic; this setup is not an execution signal.",
        "exit_logic": [],
        "risk_gates": ["no_autonomous_live_orders", "human_review", "deterministic_acceptance_gates"],
        "acceptance_gates": ["reduces_research_time", "does_not_change_trade_decisions_without_replay"],
        "no_go": ["Do not let LLM output bypass replay, risk, or paper-forward gates."],
    },
]


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    created_at: str
    source_channel: str
    source_video_id: str
    source_url: str
    participant: str
    claim_family: str
    hypothesis: str
    setup_id: str
    dataset: str
    config: dict[str, Any]
    result_artifact: str
    metrics: dict[str, Any]
    verdict: str
    verdict_reason: str
    tags: list[str]
    notes: str
    dataset_sha256: str = ""
    result_artifact_sha256: str = ""
    config_sha256: str = ""
    code_commit: str = ""
    code_dirty: bool = False
    python_version: str = ""
    platform: str = ""
    fee_schedule_revision: str = "unspecified"
    evaluation_scope: str = "unspecified"
    oos_status: str = "not_evaluated"
    provenance_complete: bool = False


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def setup_registry_payload() -> dict[str, Any]:
    return {
        "mode": "setup_registry",
        "setups": SETUP_REGISTRY,
        "count": len(SETUP_REGISTRY),
    }


def default_setup_registry_path(experiment_dir: str | Path) -> Path:
    return Path(experiment_dir) / "setup_registry.json"


def default_experiment_ledger_path(experiment_dir: str | Path) -> Path:
    return Path(experiment_dir) / "experiment_ledger.jsonl"


def write_setup_registry(output_path: str | Path) -> dict[str, Any]:
    payload = setup_registry_payload()
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(target), **payload}


def load_setup_registry() -> dict[str, dict[str, Any]]:
    return {str(item["setup_id"]): item for item in SETUP_REGISTRY}


def _resolved_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def sha256_path(raw: str | Path) -> str:
    path = _resolved_path(raw)
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _git_context() -> tuple[str, bool]:
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files\Git\bin\git.exe"),
    ]
    git = next((path for path in candidates if path.exists()), None)
    command = str(git) if git else "git"
    try:
        commit = subprocess.run(
            [command, "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                [command, "status", "--porcelain"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout.strip()
        )
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return "", False


def make_experiment_record(
    *,
    source_video_id: str,
    source_url: str,
    participant: str,
    claim_family: str,
    hypothesis: str,
    setup_id: str,
    dataset: str,
    config: dict[str, Any] | None,
    result_artifact: str,
    metrics: dict[str, Any] | None,
    verdict: str,
    verdict_reason: str,
    tags: list[str] | None = None,
    notes: str = "",
    source_channel: str = "https://www.youtube.com/@AnufrievNikita/",
    fee_schedule_revision: str = "unspecified",
    evaluation_scope: str = "unspecified",
    oos_status: str = "not_evaluated",
) -> ExperimentRecord:
    if setup_id not in load_setup_registry():
        raise ValueError(f"Unknown setup_id: {setup_id}")
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"Unknown verdict: {verdict}")
    required = {
        "claim_family": claim_family,
        "hypothesis": hypothesis,
        "setup_id": setup_id,
        "dataset": dataset,
        "verdict": verdict,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"Missing required experiment fields: {', '.join(missing)}")

    dataset_sha256 = sha256_path(dataset)
    result_artifact_sha256 = sha256_path(result_artifact) if result_artifact else ""
    positive_verdict = verdict in {"promising", "accepted_research"}
    if positive_verdict and (not dataset_sha256 or not result_artifact_sha256):
        raise ValueError("positive research verdict requires existing dataset and result artifact")
    canonical_config = json.dumps(config or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    config_sha256 = hashlib.sha256(canonical_config.encode("utf-8")).hexdigest()
    code_commit, code_dirty = _git_context()
    provenance_complete = bool(
        dataset_sha256
        and result_artifact_sha256
        and config_sha256
        and code_commit
        and fee_schedule_revision != "unspecified"
        and evaluation_scope != "unspecified"
    )

    created_at = datetime.now(timezone.utc).isoformat()
    seed = "|".join(
        [
            created_at,
            source_video_id,
            participant,
            claim_family,
            hypothesis,
            setup_id,
            dataset,
            result_artifact,
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return ExperimentRecord(
        experiment_id=f"exp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{digest}",
        created_at=created_at,
        source_channel=source_channel,
        source_video_id=source_video_id,
        source_url=source_url,
        participant=participant,
        claim_family=claim_family,
        hypothesis=hypothesis,
        setup_id=setup_id,
        dataset=dataset,
        config=config or {},
        result_artifact=result_artifact,
        metrics=metrics or {},
        verdict=verdict,
        verdict_reason=verdict_reason,
        tags=tags or [],
        notes=notes,
        dataset_sha256=dataset_sha256,
        result_artifact_sha256=result_artifact_sha256,
        config_sha256=config_sha256,
        code_commit=code_commit,
        code_dirty=code_dirty,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        fee_schedule_revision=fee_schedule_revision,
        evaluation_scope=evaluation_scope,
        oos_status=oos_status,
        provenance_complete=provenance_complete,
    )


def append_experiment_record(ledger_path: str | Path, record: ExperimentRecord) -> dict[str, Any]:
    target = Path(ledger_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    for label, raw_path, expected_hash in (
        ("dataset", record.dataset, record.dataset_sha256),
        ("result artifact", record.result_artifact, record.result_artifact_sha256),
    ):
        if expected_hash:
            current_hash = sha256_path(raw_path)
            if current_hash != expected_hash:
                raise ValueError(f"{label} hash mismatch: expected={expected_hash}, actual={current_hash or 'missing'}")

    lock_path = target.with_suffix(target.suffix + ".lock")
    descriptor: int | None = None
    deadline = time.monotonic() + 5.0
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if lock_path.exists() and time.time() - lock_path.stat().st_mtime > 60.0:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"experiment ledger lock timeout: {lock_path}")
            time.sleep(0.05)
    try:
        os.close(descriptor)
        descriptor = None
        with target.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record.__dict__, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)
    return {"output": str(target), "record": record.__dict__}


def read_experiment_ledger(ledger_path: str | Path) -> list[dict[str, Any]]:
    path = Path(ledger_path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def summarize_experiment_ledger(
    ledger_path: str | Path,
    *,
    verdict: str | None = None,
    setup_id: str | None = None,
    top_n: int = 20,
) -> dict[str, Any]:
    rows = read_experiment_ledger(ledger_path)
    filtered = rows
    if verdict:
        filtered = [row for row in filtered if row.get("verdict") == verdict]
    if setup_id:
        filtered = [row for row in filtered if row.get("setup_id") == setup_id]
    return {
        "mode": "experiment_ledger_summary",
        "input": str(ledger_path),
        "total_records": len(rows),
        "filtered_records": len(filtered),
        "by_verdict": dict(Counter(str(row.get("verdict") or "") for row in rows)),
        "by_setup_id": dict(Counter(str(row.get("setup_id") or "") for row in rows)),
        "records": filtered[-max(0, top_n):],
    }


def parse_json_object(raw: str | None, field_name: str) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def extract_metrics_from_artifact(result_path: str | Path, setup_id: str = "") -> dict[str, Any]:
    path = Path(result_path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("metrics"), dict):
        return payload["metrics"]
    best = payload.get("best_by_signal_type") if isinstance(payload, dict) else None
    if isinstance(best, dict) and setup_id in best and isinstance(best[setup_id].get("metrics"), dict):
        return best[setup_id]["metrics"]
    top = payload.get("top_results") if isinstance(payload, dict) else None
    if isinstance(top, list) and top and isinstance(top[0], dict) and isinstance(top[0].get("metrics"), dict):
        return top[0]["metrics"]
    return {}
