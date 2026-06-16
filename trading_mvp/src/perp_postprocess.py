from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from config import RiskConfig, StrategyConfig
from perp_report import run_perp_report_file
from perp_replay import run_perp_grid_search_file
from ws_replay import ReplayConfig


DEFAULT_PERP_GRID: dict[str, list[str] | list[float] | list[int]] = {
    "signal_type": ["flow_continue", "fade_exhaustion", "liquidity_sweep_reversal"],
    "entry_imbalance_abs": [0.05, 0.1],
    "entry_signed_flow_notional": [250.0, 1000.0, 2500.0],
    "max_spread_bps": [3.0, 6.0],
    "take_profit_bps": [6.0, 10.0],
    "stop_loss_bps": [3.0, 6.0],
    "max_hold_sec": [15, 25],
}


@dataclass(frozen=True)
class PerpPostprocessConfig:
    require_final: bool = True
    min_field_coverage_ratio: float = 0.95
    min_market_count: int = 2
    min_trades: int = 20
    min_win_rate: float = 0.6
    min_expectancy_quote: float = 0.0
    min_net_pnl_quote: float = 0.0
    min_profit_factor: float = 1.2
    max_drawdown_quote: float = 5.0
    top_n: int = 30


GridRunner = Callable[..., dict[str, Any]]


def run_perp_postprocess_file(
    input_path: str | Path,
    manifest_path: str | Path | None,
    report_output_path: str | Path,
    grid_output_path: str | Path,
    base_strategy: StrategyConfig,
    risk_cfg: RiskConfig,
    replay_cfg: ReplayConfig | None = None,
    cfg: PerpPostprocessConfig | None = None,
    grid_runner: GridRunner = run_perp_grid_search_file,
) -> dict[str, Any]:
    cfg = cfg or PerpPostprocessConfig()
    src = Path(input_path)
    manifest = _load_manifest(manifest_path)
    if cfg.require_final:
        if not manifest_path:
            return {
                "ok": False,
                "status": "manifest_required",
                "input": str(src),
                "manifest": None,
                "manifest_summary": None,
                "message": "Manifest is required for final postprocess; grid-search was not run.",
            }
        if manifest is None:
            return {
                "ok": False,
                "status": "manifest_missing",
                "input": str(src),
                "manifest": str(manifest_path),
                "manifest_summary": None,
                "message": "Manifest was not found; grid-search was not run.",
            }
        if not bool(manifest.get("final")):
            return {
                "ok": False,
                "status": "not_final",
                "input": str(src),
                "manifest": str(manifest_path),
                "manifest_summary": _manifest_summary(manifest),
                "message": "Manifest is not final; postprocess grid-search was not run.",
            }

    report = run_perp_report_file(src, report_output_path)
    qa_passed, qa_reasons = _qa_gate(report, cfg)
    result: dict[str, Any] = {
        "ok": qa_passed,
        "status": "qa_passed" if qa_passed else "qa_failed",
        "input": str(src),
        "manifest": str(manifest_path) if manifest_path else None,
        "manifest_summary": _manifest_summary(manifest) if manifest else None,
        "report_output": str(report_output_path),
        "grid_output": str(grid_output_path),
        "qa_reasons": qa_reasons,
        "report_summary": _report_summary(report),
        "postprocess_config": asdict(cfg),
    }
    if not qa_passed:
        return result

    replay_cfg = replay_cfg or default_perp_postprocess_replay_config()
    grid = grid_runner(
        input_path=src,
        output_path=grid_output_path,
        base_strategy=base_strategy,
        risk_cfg=risk_cfg,
        replay_cfg=replay_cfg,
        grid=DEFAULT_PERP_GRID,
        min_trades=cfg.min_trades,
        top_n=cfg.top_n,
        min_win_rate=cfg.min_win_rate,
        min_expectancy_quote=cfg.min_expectancy_quote,
        min_net_pnl_quote=cfg.min_net_pnl_quote,
        min_profit_factor=cfg.min_profit_factor,
        max_drawdown_quote=cfg.max_drawdown_quote,
    )
    result["status"] = "grid_completed"
    result["grid_summary"] = {
        "events": grid.get("events"),
        "total_combinations": grid.get("total_combinations"),
        "eligible_combinations": grid.get("eligible_combinations"),
        "best_by_signal_type": _best_metrics_by_signal(grid.get("best_by_signal_type") or {}),
    }
    return result


def default_perp_postprocess_replay_config() -> ReplayConfig:
    return ReplayConfig(
        notional_quote=25.0,
        execution_mode="maker",
        taker_fee_bps=10.0,
        maker_fee_bps=0.0,
        slippage_bps=0.0,
        latency_ms=250,
        flow_window_sec=5.0,
        allow_short=True,
        max_open_positions=1,
        maker_queue_model="top_qty_fraction",
        maker_queue_ahead_fraction=1.0,
        maker_queue_ahead_qty=0.0,
        maker_order_ttl_sec=5.0,
        min_net_take_profit_bps=1.0,
    )


def default_perp_postprocess_output(input_path: str | Path, backtest_dir: str | Path) -> tuple[Path, Path]:
    stem = Path(input_path).stem
    out_dir = Path(backtest_dir)
    return out_dir / f"perp_report_{stem}.json", out_dir / f"perp_grid_search_{stem}.json"


def _load_manifest(manifest_path: str | Path | None) -> dict[str, Any] | None:
    if not manifest_path:
        return None
    path = Path(manifest_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _qa_gate(report: dict[str, Any], cfg: PerpPostprocessConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    rows = int(report.get("rows") or 0)
    if rows <= 0:
        reasons.append("no_rows")
        return False, reasons
    if int(report.get("market_count") or 0) < cfg.min_market_count:
        reasons.append("min_market_count")
    warnings = list(report.get("warnings") or [])
    if warnings:
        reasons.append("report_warnings")
    field_coverage = report.get("field_coverage") or {}
    for field in ("mark_price", "index_price", "funding_rate", "funding_interval_sec"):
        coverage_ratio = float(field_coverage.get(field) or 0) / rows
        if coverage_ratio < cfg.min_field_coverage_ratio:
            reasons.append(f"field_coverage:{field}")
    kinds = report.get("events_by_kind") or {}
    if int(kinds.get("bbo") or 0) <= 0:
        reasons.append("no_bbo")
    if int(kinds.get("trade") or 0) <= 0:
        reasons.append("no_trades")
    return not reasons, reasons


def _manifest_summary(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        "final": manifest.get("final"),
        "completed_cycles": manifest.get("completed_cycles"),
        "cycles": manifest.get("cycles"),
        "rows": manifest.get("rows"),
        "errors": manifest.get("errors"),
        "duration_sec": manifest.get("duration_sec"),
    }


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "rows": report.get("rows"),
        "market_count": report.get("market_count"),
        "cycles_seen": report.get("cycles_seen"),
        "events_by_kind": report.get("events_by_kind"),
        "events_by_exchange": report.get("events_by_exchange"),
        "field_coverage": report.get("field_coverage"),
        "warnings": report.get("warnings"),
        "malformed_rows": report.get("malformed_rows"),
    }


def _best_metrics_by_signal(best_by_signal_type: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for signal_type, payload in best_by_signal_type.items():
        out[signal_type] = {
            "strategy_config": payload.get("strategy_config"),
            "metrics": payload.get("metrics"),
            "eligible": payload.get("eligible"),
            "eligibility_reasons": payload.get("eligibility_reasons"),
        }
    return out
