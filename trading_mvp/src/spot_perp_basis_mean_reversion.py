from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SpotPerpBasisPlanConfig:
    spot_fee_bps_per_side: float = 10.0
    perp_fee_bps_per_side: float = 10.0
    spot_slippage_bps_per_side: float = 5.0
    perp_slippage_bps_per_side: float = 5.0
    adverse_basis_buffer_bps: float = 20.0
    max_spot_spread_bps: float = 20.0
    max_perp_spread_bps: float = 20.0
    max_adverse_funding_rate: float = -0.0003
    allow_spot_short: bool = False
    min_independent_events: int = 100
    min_bases: int = 10
    max_single_base_pnl_share: float = 0.25
    min_profit_factor: float = 1.2
    min_positive_walk_forward_ratio: float = 0.60


def basis_bps(spot_mid: float, perp_mid: float) -> float:
    if spot_mid <= 0 or perp_mid <= 0:
        raise ValueError("spot_mid and perp_mid must be positive")
    return (perp_mid - spot_mid) / spot_mid * 10_000.0


def round_trip_cost_hurdle_bps(cfg: SpotPerpBasisPlanConfig) -> float:
    open_close_cost = 2.0 * (
        cfg.spot_fee_bps_per_side
        + cfg.perp_fee_bps_per_side
        + cfg.spot_slippage_bps_per_side
        + cfg.perp_slippage_bps_per_side
    )
    return open_close_cost + cfg.adverse_basis_buffer_bps


def classify_basis_signal(
    *,
    spot_mid: float,
    perp_mid: float,
    spot_spread_bps: float,
    perp_spread_bps: float,
    funding_rate: float | None,
    cfg: SpotPerpBasisPlanConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or SpotPerpBasisPlanConfig()
    basis = basis_bps(spot_mid, perp_mid)
    hurdle = round_trip_cost_hurdle_bps(cfg)
    reasons: list[str] = []

    if spot_spread_bps > cfg.max_spot_spread_bps:
        reasons.append("spot_spread_too_wide")
    if perp_spread_bps > cfg.max_perp_spread_bps:
        reasons.append("perp_spread_too_wide")
    if funding_rate is not None and funding_rate < cfg.max_adverse_funding_rate:
        reasons.append("funding_regime_adverse")

    if basis >= hurdle:
        signal = "long_spot_short_perp"
        needs_spot_short = False
    elif basis <= -hurdle:
        signal = "short_spot_long_perp"
        needs_spot_short = True
        if not cfg.allow_spot_short:
            reasons.append("negative_basis_requires_spot_short")
    else:
        signal = "no_signal"
        needs_spot_short = False
        reasons.append("basis_below_cost_hurdle")

    allowed = signal != "no_signal" and not reasons
    return {
        "signal": signal,
        "allowed": allowed,
        "basis_bps": round(basis, 6),
        "cost_hurdle_bps": round(hurdle, 6),
        "needs_spot_short": needs_spot_short,
        "reasons": reasons,
    }


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def discover_daily_run(exports_root: Path, explicit_run_dir: Path | None = None) -> Path | None:
    if explicit_run_dir is not None:
        return explicit_run_dir if (explicit_run_dir / "manifest.json").exists() else None
    daily_root = exports_root / "daily"
    if not daily_root.exists():
        return None
    manifests = sorted(
        daily_root.glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return manifests[0].parent if manifests else None


def summarize_daily_manifest(run_dir: Path | None) -> dict[str, Any]:
    if run_dir is None:
        return {
            "present": False,
            "run_dir": None,
            "reason": "daily_manifest_missing",
            "perp_history_hint": False,
            "spot_history_hint": False,
            "paired_spot_perp_history_ready": False,
        }

    manifest_path = run_dir / "manifest.json"
    manifest = load_json(manifest_path)
    if manifest is None:
        return {
            "present": False,
            "run_dir": str(run_dir),
            "reason": "daily_manifest_missing",
            "perp_history_hint": False,
            "spot_history_hint": False,
            "paired_spot_perp_history_ready": False,
        }

    universe = manifest.get("universe") or []
    by_exchange: dict[str, dict[str, Any]] = {}
    non_binance_bases_by_exchange: dict[str, set[str]] = {}
    for item in universe:
        exchange = str(item.get("exchange") or "").lower()
        symbol = str(item.get("symbol") or "").upper()
        base = str(item.get("base") or "").upper()
        if not exchange or not symbol:
            continue
        by_exchange.setdefault(exchange, {})[symbol] = item
        if bool(item.get("non_binance_baseline")) and base:
            non_binance_bases_by_exchange.setdefault(exchange, set()).add(base)

    exchange_symbols = {name: len(symbols) for name, symbols in sorted(by_exchange.items())}
    shared_symbols: set[str] = set()
    if by_exchange:
        exchange_sets = [set(symbols) for symbols in by_exchange.values()]
        shared_symbols = set.intersection(*exchange_sets) if exchange_sets else set()
    non_binance_shared_bases: set[str] = set()
    if non_binance_bases_by_exchange:
        base_sets = list(non_binance_bases_by_exchange.values())
        non_binance_shared_bases = set.intersection(*base_sets) if base_sets else set()

    funding_rows_total = int(manifest.get("funding_rows_total") or 0)
    klines_rows_total = int(manifest.get("klines_rows_total") or 0)
    return {
        "present": True,
        "run_dir": str(run_dir),
        "manifest_path": str(manifest_path),
        "run_id": manifest.get("run_id"),
        "exchange_symbols": exchange_symbols,
        "shared_symbols_total": len(shared_symbols),
        "non_binance_shared_bases_total": len(non_binance_shared_bases),
        "klines_rows_total": klines_rows_total,
        "funding_rows_total": funding_rows_total,
        "perp_history_hint": funding_rows_total > 0,
        "spot_history_hint": False,
        "paired_spot_perp_history_ready": False,
        "reason": (
            "current_daily_history_has_perp_funding_and_klines_but_no_verified_spot_mid_history"
            if funding_rows_total or klines_rows_total
            else "daily_history_empty_or_unverified"
        ),
    }


def build_planonly_report(
    *,
    repo_root: Path,
    output_path: Path | None = None,
    daily_run_dir: Path | None = None,
    cfg: SpotPerpBasisPlanConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or SpotPerpBasisPlanConfig()
    exports_root = repo_root / "exports" / "trading-mvp"
    daily_run = discover_daily_run(exports_root, daily_run_dir)
    availability = summarize_daily_manifest(daily_run)
    hurdle = round_trip_cost_hurdle_bps(cfg)
    paired_ready = bool(availability["paired_spot_perp_history_ready"])

    decision = (
        "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_BACKTEST_SCAFFOLD"
        if paired_ready
        else "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_AVAILABILITY_PREFLIGHT"
    )
    next_step = (
        "Build read-only detector/backtester PlanOnly on existing paired spot/perp history."
        if paired_ready
        else "Build public-data availability preflight for paired spot mid, perp mark/mid, spread/depth and funding-regime fields; do not collect yet."
    )

    report: dict[str, Any] = {
        "mode": "spot_perp_basis_mean_reversion_planonly",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "selected_branch": "spot_perp_basis_mean_reversion_no_funding",
        "research_only": True,
        "would_start": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "strategy_accepted": False,
        "reason": (
            "PlanOnly scaffold only. Funding is not counted as PnL; it is a risk/regime filter. "
            "The branch is not backtest-ready until paired spot/perp history and hedge feasibility pass preflight."
        ),
        "signal_contract": {
            "basis_bps": "(perp_mid_or_mark - spot_mid) / spot_mid * 10000",
            "positive_basis_entry": "long spot + short perp when basis exceeds full round-trip hurdle",
            "negative_basis_entry": "blocked by default because it requires spot shorting",
            "funding_usage": "risk filter only; do not include expected funding payout in signal PnL",
            "exit": [
                "basis_reverts_to_zero_or_target_band",
                "funding_regime_turns_adverse",
                "spread_or_depth_degrades",
                "max_hold_or_force_end",
            ],
        },
        "economics_policy": {
            "optimize_for": "net_expectancy_after_costs",
            "base_fee_model": "base/VIP0/no-volume fees",
            "spot_fee_bps_per_side": cfg.spot_fee_bps_per_side,
            "perp_fee_bps_per_side": cfg.perp_fee_bps_per_side,
            "spot_slippage_bps_per_side": cfg.spot_slippage_bps_per_side,
            "perp_slippage_bps_per_side": cfg.perp_slippage_bps_per_side,
            "adverse_basis_buffer_bps": cfg.adverse_basis_buffer_bps,
            "minimum_entry_basis_hurdle_bps": round(hurdle, 6),
            "winrate_policy": "supporting metric only; reject high win-rate variants with negative expectancy or tail loss",
        },
        "data_requirements": [
            "non-Binance base universe with spot and perp availability by venue",
            "spot best bid/ask or OHLCV-derived mid with spread proxy",
            "perp mark/index or best bid/ask with spread proxy",
            "funding rate and next funding time only for adverse-regime filter",
            "top-of-book depth or liquidity proxy for both legs",
            "base/VIP0 fee assumptions for spot and perp",
            "no leverage/margin/live execution assumption in research acceptance",
        ],
        "availability_snapshot": availability,
        "acceptance_gates": {
            "sample_size": f">= {cfg.min_independent_events} independent excursions after cooldown",
            "market_diversity": f">= {cfg.min_bases} bases, single-base net PnL share <= {cfg.max_single_base_pnl_share:.0%}",
            "economics": "net expectancy after fees, spread, slippage and adverse-basis buffer > 0",
            "oos": f"holdout net PnL > 0 and profit factor >= {cfg.min_profit_factor}",
            "walk_forward": f">= {cfg.min_positive_walk_forward_ratio:.0%} positive folds with positive median expectancy",
            "stress": "non-negative under 2x slippage, +50% fee buffer, partial-fill haircut and delayed exit",
            "hedge_feasibility": "both legs available with borrow/margin assumptions explicitly blocked or separately approved before live",
        },
        "rejection_gates": [
            "paired_spot_perp_history_missing",
            "basis_excursion_below_cost_hurdle",
            "too_few_independent_events",
            "single_market_cherry_picking",
            "holdout_net_pnl_negative",
            "walk_forward_or_stress_failure",
            "requires_live_margin_or_spot_short_to_work",
            "uses_funding_payout_as_hidden_pnl_source",
        ],
        "next_valid_moves": [next_step],
        "blocked_moves": [
            "actual_collect_without_new_explicit_confirmation",
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward",
            "funding_payout_rescue",
        ],
        "commands": {
            "availability_preflight_planonly_needed": not paired_ready,
        },
        "output_path": str(output_path) if output_path else None,
    }
    return report


def write_planonly_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(output_path)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="spot/perp basis mean-reversion PlanOnly scaffold")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--daily-run-dir", default="")
    args = parser.parse_args()

    output_path = Path(args.out)
    report = build_planonly_report(
        repo_root=Path(args.repo_root),
        output_path=output_path,
        daily_run_dir=Path(args.daily_run_dir) if args.daily_run_dir else None,
    )
    write_planonly_report(report, output_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
