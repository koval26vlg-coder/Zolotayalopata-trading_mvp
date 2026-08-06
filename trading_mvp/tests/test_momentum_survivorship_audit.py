from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from momentum_survivorship_audit import (  # noqa: E402
    AuditConfig,
    audit_momentum_report,
    audit_universe,
    build_audit,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_run_dir(root: Path, *, point_in_time: bool = False, include_delisted: bool = False) -> Path:
    run_dir = root / "daily"
    universe = [
        {
            "exchange": "mexc",
            "symbol": "AAA_USDT",
            "base": "AAA",
            "volume_24h_quote": 1_000_000,
            "non_binance_baseline": True,
        }
    ]
    if include_delisted:
        universe.append(
            {
                "exchange": "mexc",
                "symbol": "DEAD_USDT",
                "base": "DEAD",
                "volume_24h_quote": 0,
                "non_binance_baseline": True,
                "survivorship_status": "current_non_tradable_snapshot",
            }
        )
    manifest = {"run_id": "test", "universe": universe}
    if point_in_time:
        manifest["point_in_time_universe"] = True
        manifest["universe_asof_ts"] = 1_700_000_000
    write_json(run_dir / "manifest.json", manifest)
    rows = [
        {
            "ts": day * 86400,
            "close": 100 + day,
            "volume_quote": 1_000_000,
        }
        for day in range(130)
    ]
    write_json(run_dir / "mexc" / "klines" / "AAA_USDT.json", {"rows": rows})
    if include_delisted:
        write_json(run_dir / "mexc" / "klines" / "DEAD_USDT.json", {"rows": rows})
    return run_dir


def make_report(*, drawdown: float = 10.0, top_share: float = 0.1) -> dict:
    return {
        "configs": {
            "non_binance_baseline": {
                "markets_in_universe": 20,
                "selected_lookback": 30,
                "oos_by_scenario": {
                    "base_vip0_taker_taker_20bps": {
                        "n_rebalances": 28,
                        "mean_weekly_net_bps": 100,
                        "profit_factor": 2.0,
                        "hit_rate": 0.6,
                        "max_drawdown_pct": drawdown,
                        "top_base": "AAA",
                        "top_base_positive_share": top_share,
                    }
                },
                "rolling_walk_forward": {
                    "positive_fold_ratio": 0.8,
                    "median_mean_weekly_net_bps": 50,
                },
            }
        }
    }


class UniverseAuditTests(unittest.TestCase):
    def test_current_snapshot_without_delisted_fails_survivorship(self) -> None:
        result = audit_universe({"universe": [{"volume_24h_quote": 1000}]})
        self.assertFalse(result["survivorship_control_pass"])
        self.assertIn("missing_point_in_time_universe_metadata", result["reasons"])
        self.assertIn("missing_delisted_or_inactive_contract_coverage", result["reasons"])

    def test_point_in_time_with_delisted_passes_survivorship(self) -> None:
        result = audit_universe(
            {
                "point_in_time_universe": True,
                "universe": [
                    {"volume_24h_quote": 1000},
                    {"survivorship_status": "current_non_tradable_snapshot"},
                ],
            }
        )
        self.assertTrue(result["survivorship_control_pass"])


class RiskPolicyAuditTests(unittest.TestCase):
    def test_drawdown_policy_failure_blocks_label(self) -> None:
        result = audit_momentum_report(make_report(drawdown=35), AuditConfig(max_drawdown_pct=25))
        self.assertFalse(result["all_labels_pass"])
        self.assertIn("max_drawdown_policy_failed", result["labels"][0]["reasons"])

    def test_concentration_policy_failure_blocks_label(self) -> None:
        result = audit_momentum_report(make_report(top_share=0.4), AuditConfig(max_top_base_share=0.25))
        self.assertFalse(result["all_labels_pass"])
        self.assertIn("top_base_concentration_policy_failed", result["labels"][0]["reasons"])


class BuildAuditTests(unittest.TestCase):
    def test_build_audit_revise_required_when_survivorship_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = make_run_dir(root)
            report_path = root / "report.json"
            output_path = root / "audit.json"
            write_json(report_path, make_report())

            result = build_audit(run_dir, report_path, output_path, AuditConfig())

        self.assertEqual(result["decision"], "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_REVISE_REQUIRED")
        self.assertIn("survivorship_bias_not_controlled", result["blocked_reasons"])
        self.assertFalse(result["strategy_accepted"])
        self.assertFalse(result["paper_forward_allowed"])

    def test_build_audit_ready_only_when_survivorship_history_and_risk_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = make_run_dir(root, point_in_time=True, include_delisted=True)
            report_path = root / "report.json"
            output_path = root / "audit.json"
            write_json(report_path, make_report())

            result = build_audit(run_dir, report_path, output_path, AuditConfig())

        self.assertEqual(
            result["decision"],
            "DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_READY_FOR_INDEPENDENT_REVIEW",
        )


if __name__ == "__main__":
    unittest.main()
