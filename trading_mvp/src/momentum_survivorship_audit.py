from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from momentum_backtest import DAY_SEC, load_markets


DEFAULT_MAX_DRAWDOWN_PCT = 25.0
DEFAULT_MAX_TOP_BASE_SHARE = 0.25
DEFAULT_MIN_OOS_REBALANCES = 20
DEFAULT_MIN_ROLLING_WF_POSITIVE_RATIO = 0.60
DEFAULT_MIN_HISTORY_DAYS = 120


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _has_truthy_key(payload: dict[str, Any], names: tuple[str, ...]) -> bool:
    for name in names:
        if bool(payload.get(name)):
            return True
    return False


@dataclass(frozen=True)
class AuditConfig:
    max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT
    max_top_base_share: float = DEFAULT_MAX_TOP_BASE_SHARE
    min_oos_rebalances: int = DEFAULT_MIN_OOS_REBALANCES
    min_rolling_wf_positive_ratio: float = DEFAULT_MIN_ROLLING_WF_POSITIVE_RATIO
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS


def history_coverage(run_dir: Path, min_history_days: int) -> dict[str, Any]:
    markets = load_markets(run_dir)
    rows: list[dict[str, Any]] = []
    for market in markets:
        days = sorted(market.closes)
        if not days:
            rows.append(
                {
                    "exchange": market.exchange,
                    "symbol": market.symbol,
                    "base": market.base,
                    "days": 0,
                    "first_day": None,
                    "last_day": None,
                    "passes_min_history": False,
                }
            )
            continue
        first_day = days[0]
        last_day = days[-1]
        span_days = last_day - first_day + 1
        rows.append(
            {
                "exchange": market.exchange,
                "symbol": market.symbol,
                "base": market.base,
                "days": len(days),
                "span_days": span_days,
                "first_day": first_day,
                "last_day": last_day,
                "passes_min_history": span_days >= min_history_days,
            }
        )
    failures = [row for row in rows if not row["passes_min_history"]]
    return {
        "markets": len(rows),
        "min_history_days": min_history_days,
        "passing_markets": len(rows) - len(failures),
        "failing_markets": len(failures),
        "failing_sample": failures[:20],
    }


def audit_universe(manifest: dict[str, Any]) -> dict[str, Any]:
    universe = list(manifest.get("universe") or [])
    point_in_time_keys = (
        "point_in_time_universe",
        "point_in_time",
        "historical_universe",
        "universe_asof_ts",
        "universe_asof",
        "selection_timestamp",
    )
    delisted_rows = [
        item
        for item in universe
        if bool(item.get("is_delisted"))
        or str(item.get("survivorship_status") or "").lower() in {"current_non_tradable_snapshot", "delisted", "inactive"}
        or str(item.get("status") or "").lower() in {"delisted", "inactive", "offline"}
    ]
    non_binance_rows = [item for item in universe if bool(item.get("non_binance_baseline"))]
    current_volume_fields = sum(1 for item in universe if item.get("volume_24h_quote") is not None)
    point_in_time = _has_truthy_key(manifest, point_in_time_keys)
    delisted_included = len(delisted_rows) > 0
    pass_universe = point_in_time and delisted_included
    reasons: list[str] = []
    if not point_in_time:
        reasons.append("missing_point_in_time_universe_metadata")
    if not delisted_included:
        reasons.append("missing_delisted_or_inactive_contract_coverage")
    if current_volume_fields == len(universe) and universe:
        reasons.append("current_top_volume_snapshot_bias_detected")
    return {
        "universe_rows": len(universe),
        "non_binance_rows": len(non_binance_rows),
        "point_in_time_metadata_present": point_in_time,
        "delisted_or_inactive_rows": len(delisted_rows),
        "current_volume_field_rows": current_volume_fields,
        "survivorship_control_pass": pass_universe,
        "reasons": reasons,
    }


def audit_momentum_report(report: dict[str, Any], config: AuditConfig) -> dict[str, Any]:
    configs = report.get("configs") or {}
    labels: list[dict[str, Any]] = []
    for label, result in configs.items():
        oos = ((result.get("oos_by_scenario") or {}).get("base_vip0_taker_taker_20bps") or {})
        rolling = result.get("rolling_walk_forward") or {}
        drawdown = float(oos.get("max_drawdown_pct") or 0.0)
        top_share = float(oos.get("top_base_positive_share") or 0.0)
        oos_n = int(oos.get("n_rebalances") or 0)
        rolling_ratio = float(rolling.get("positive_fold_ratio") or 0.0)
        rolling_median = float(rolling.get("median_mean_weekly_net_bps") or 0.0)
        reasons: list[str] = []
        if oos_n < config.min_oos_rebalances:
            reasons.append("too_few_oos_rebalances")
        if drawdown > config.max_drawdown_pct:
            reasons.append("max_drawdown_policy_failed")
        if top_share > config.max_top_base_share:
            reasons.append("top_base_concentration_policy_failed")
        if rolling_ratio < config.min_rolling_wf_positive_ratio or rolling_median <= 0:
            reasons.append("rolling_walk_forward_policy_failed")
        labels.append(
            {
                "label": label,
                "markets": result.get("markets_in_universe"),
                "selected_lookback": result.get("selected_lookback"),
                "oos_rebalances": oos_n,
                "mean_weekly_net_bps": oos.get("mean_weekly_net_bps"),
                "profit_factor": oos.get("profit_factor"),
                "hit_rate": oos.get("hit_rate"),
                "max_drawdown_pct": drawdown,
                "max_drawdown_limit_pct": config.max_drawdown_pct,
                "top_base": oos.get("top_base"),
                "top_base_positive_share": top_share,
                "top_base_share_limit": config.max_top_base_share,
                "rolling_wf_positive_ratio": rolling_ratio,
                "rolling_wf_median_mean_weekly_net_bps": rolling_median,
                "passes_risk_policy": not reasons,
                "reasons": reasons,
            }
        )
    return {
        "labels": labels,
        "all_labels_pass": all(row["passes_risk_policy"] for row in labels) if labels else False,
        "failed_labels": [row["label"] for row in labels if not row["passes_risk_policy"]],
    }


def build_audit(
    run_dir: Path,
    report_path: Path,
    output_path: Path,
    config: AuditConfig,
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    universe = audit_universe(manifest)
    history = history_coverage(run_dir, config.min_history_days)
    risk = audit_momentum_report(report, config)
    history_pass = history["failing_markets"] == 0
    survivorship_pass = bool(universe["survivorship_control_pass"])
    risk_pass = bool(risk["all_labels_pass"])
    accepted = survivorship_pass and history_pass and risk_pass
    if accepted:
        decision = "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_READY_FOR_INDEPENDENT_REVIEW"
    else:
        decision = "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_REVISE_REQUIRED"

    payload: dict[str, Any] = {
        "mode": "cross_sectional_momentum_daily_survivorship_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "selected_branch": "cross_sectional_momentum_daily",
        "research_only": True,
        "strategy_accepted": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "paper_forward_allowed": False,
        "run_dir": str(run_dir),
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "output_path": str(output_path),
        "config": {
            "max_drawdown_pct": config.max_drawdown_pct,
            "max_top_base_share": config.max_top_base_share,
            "min_oos_rebalances": config.min_oos_rebalances,
            "min_rolling_wf_positive_ratio": config.min_rolling_wf_positive_ratio,
            "min_history_days": config.min_history_days,
        },
        "checks": {
            "survivorship": universe,
            "history_coverage": history,
            "risk_policy": risk,
        },
        "summary": {
            "survivorship_pass": survivorship_pass,
            "history_pass": history_pass,
            "risk_policy_pass": risk_pass,
            "accepted_for_paper_forward": False,
        },
        "blocked_reasons": [],
        "next_valid_moves": [
            "Build a point-in-time/delisted universe source before treating positive daily momentum as accepted evidence.",
            "Keep paper-forward/live/API/grid blocked until survivorship and live long/short perp feasibility are resolved.",
            "If point-in-time universe cannot be sourced, mark this branch as research-inconclusive/rejected for acceptance.",
        ],
    }
    if not survivorship_pass:
        payload["blocked_reasons"].append("survivorship_bias_not_controlled")
    if not history_pass:
        payload["blocked_reasons"].append("insufficient_history_coverage_for_some_markets")
    if not risk_pass:
        payload["blocked_reasons"].append("risk_policy_failed")
    return payload


def default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("exports") / "trading-mvp" / "analysis" / f"cross_sectional_momentum_survivorship_audit_{stamp}.json"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = argparse.ArgumentParser(description="Research-only survivorship/risk audit for daily cross-sectional momentum.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--max-drawdown-pct", type=float, default=DEFAULT_MAX_DRAWDOWN_PCT)
    parser.add_argument("--max-top-base-share", type=float, default=DEFAULT_MAX_TOP_BASE_SHARE)
    parser.add_argument("--min-oos-rebalances", type=int, default=DEFAULT_MIN_OOS_REBALANCES)
    parser.add_argument("--min-rolling-wf-positive-ratio", type=float, default=DEFAULT_MIN_ROLLING_WF_POSITIVE_RATIO)
    parser.add_argument("--min-history-days", type=int, default=DEFAULT_MIN_HISTORY_DAYS)
    args = parser.parse_args()

    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_audit(
        Path(args.run_dir),
        Path(args.report),
        output,
        AuditConfig(
            max_drawdown_pct=args.max_drawdown_pct,
            max_top_base_share=args.max_top_base_share,
            min_oos_rebalances=args.min_oos_rebalances,
            min_rolling_wf_positive_ratio=args.min_rolling_wf_positive_ratio,
            min_history_days=args.min_history_days,
        ),
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
