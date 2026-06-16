from __future__ import annotations

import hashlib
import json
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
    )


def append_experiment_record(ledger_path: str | Path, record: ExperimentRecord) -> dict[str, Any]:
    target = Path(ledger_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.__dict__, ensure_ascii=False, sort_keys=True) + "\n")
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
