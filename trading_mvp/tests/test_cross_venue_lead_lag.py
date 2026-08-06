from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cross_venue_lead_lag import (  # noqa: E402
    build_cross_venue_lead_lag_report,
    run_cross_venue_lead_lag,
)
from cross_venue_lead_lag_audit import build_lead_lag_audit  # noqa: E402


def _bbo(
    ts: float,
    exchange: str,
    symbol: str,
    mid: float,
    *,
    qty: float = 10.0,
    half_spread: float = 0.01,
) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": exchange,
        "symbol": symbol,
        "event_kind": "bbo",
        "channel": "spot.book_ticker",
        "bid_price": mid - half_spread,
        "bid_qty": qty,
        "ask_price": mid + half_spread,
        "ask_qty": qty,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _plan(input_path: Path) -> dict[str, object]:
    return {
        "schema": "cross_venue_spot_lead_lag_plan_v1",
        "branch": "cross_venue_spot_lead_lag_spillover",
        "research_only": True,
        "fixed_parameters_no_grid": True,
        "strategy_accepted": False,
        "input_path": str(input_path),
        "signal": {
            "quote": "USDT",
            "supported_exchanges": ["gateio", "mexc"],
            "direction": "long_only_no_margin",
            "lookback_sec": 10.0,
            "leader_min_return_bps": 100.0,
            "lagger_abs_max_return_bps": 35.0,
            "min_return_gap_bps": 75.0,
            "max_quote_age_sec": 1.0,
            "max_spread_bps": 20.0,
            "min_top_notional_quote": 100.0,
            "cooldown_sec": 300.0,
        },
        "execution": {
            "baseline_latency_sec": 0.5,
            "stress_latency_sec": 2.0,
            "max_entry_wait_sec": 2.0,
            "hold_sec": 60.0,
            "exit_grace_sec": 5.0,
            "round_trip_fee_bps": 39.0,
            "slippage_bps": 10.0,
            "operational_buffer_bps": 20.0,
            "fixed_total_cost_bps": 69.0,
            "stress_fee_multiplier": 1.5,
            "stress_slippage_multiplier": 2.0,
            "stress_total_cost_bps": 98.5,
            "exit_liquidity_failure_penalty_bps": 200.0,
        },
        "validation": {
            "train_fraction": 0.5,
            "walk_forward_folds": 4,
            "min_total_trades": 100,
            "min_oos_trades": 30,
            "min_distinct_bases": 5,
            "max_top_base_positive_contribution": 0.5,
            "min_oos_profit_factor": 1.2,
            "min_oos_expectancy_bps": 0.0,
            "min_positive_fold_ratio": 0.6,
            "min_stress_execution_coverage": 0.8,
            "min_stress_expectancy_bps": 0.0,
            "min_trades_per_fold": 10,
        },
    }


def _write_plan(path: Path, input_path: Path) -> str:
    path.write_text(json.dumps(_plan(input_path), indent=2), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lead_lag_rows(*, lagger_qty: float = 10.0) -> list[dict[str, object]]:
    # Deliberately group the source by market. The file is globally out of
    # order, while each market remains chronological as in the real dataset.
    gate = [
        _bbo(1000.0, "gateio", "HYPE_USDT", 100.00, qty=lagger_qty),
        _bbo(1005.0, "gateio", "HYPE_USDT", 100.00, qty=lagger_qty),
        _bbo(1010.0, "gateio", "HYPE_USDT", 100.10, qty=lagger_qty),
        _bbo(1010.6, "gateio", "HYPE_USDT", 100.10, qty=lagger_qty),
        _bbo(1012.1, "gateio", "HYPE_USDT", 100.10, qty=lagger_qty),
        _bbo(1070.6, "gateio", "HYPE_USDT", 101.01, qty=lagger_qty),
        _bbo(1072.1, "gateio", "HYPE_USDT", 101.01, qty=lagger_qty),
    ]
    mexc = [
        _bbo(1000.0, "mexc", "HYPEUSDT", 100.00),
        _bbo(1005.0, "mexc", "HYPEUSDT", 100.00),
        _bbo(1010.0, "mexc", "HYPEUSDT", 101.20),
    ]
    return gate + mexc


class CrossVenueLeadLagTests(unittest.TestCase):
    def test_partition_merge_detects_signal_without_global_lookahead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "grouped.jsonl"
            plan_path = root / "plan.json"
            _write_jsonl(source, _lead_lag_rows())
            plan_hash = _write_plan(plan_path, source)

            report = build_cross_venue_lead_lag_report(
                source,
                plan_path,
                expected_plan_sha256=plan_hash,
                temp_parent=root,
            )

            self.assertTrue(report["partition"]["scan_complete"])
            self.assertGreater(report["partition"]["global_out_of_order"], 0)
            self.assertEqual(report["summary"]["signals"], 1)
            self.assertEqual(report["summary"]["baseline_trades"], 1)
            self.assertEqual(report["summary"]["stress_trades"], 1)
            baseline = report["baseline_trades"][0]
            self.assertEqual(baseline["leader_exchange"], "mexc")
            self.assertEqual(baseline["lagger_exchange"], "gateio")
            self.assertAlmostEqual(baseline["entry_ts"], 1010.6)
            self.assertAlmostEqual(baseline["exit_ts"], 1070.6)
            self.assertAlmostEqual(
                baseline["net_pnl_bps"],
                (101.0 / 100.11 - 1.0) * 10000.0 - 69.0,
            )
            self.assertFalse(report["strategy_accepted"])
            self.assertFalse(report["paper_forward_ready"])
            self.assertFalse(report["partition"]["partition_files_retained"])
            self.assertTrue(all("path" not in row for row in report["partition"]["markets"]))
            self.assertFalse(any(root.glob("lead_lag_partitions_*")))

    def test_low_top_liquidity_blocks_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "thin.jsonl"
            plan_path = root / "plan.json"
            _write_jsonl(source, _lead_lag_rows(lagger_qty=0.5))
            _write_plan(plan_path, source)

            report = build_cross_venue_lead_lag_report(source, plan_path, temp_parent=root)

        self.assertEqual(report["summary"]["signals"], 0)
        self.assertEqual(report["decision"], "CROSS_VENUE_SPOT_LEAD_LAG_REJECTED_NO_FIXED_SIGNALS")

    def test_max_rows_distinguishes_exact_file_from_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "three.jsonl"
            plan_path = root / "plan.json"
            rows = _lead_lag_rows()[:3]
            _write_jsonl(source, rows)
            _write_plan(plan_path, source)

            exact = build_cross_venue_lead_lag_report(
                source, plan_path, max_rows=3, temp_parent=root
            )
            truncated = build_cross_venue_lead_lag_report(
                source, plan_path, max_rows=2, temp_parent=root
            )

        self.assertTrue(exact["partition"]["scan_complete"])
        self.assertFalse(exact["partition"]["truncated_by_max_rows"])
        self.assertFalse(truncated["partition"]["scan_complete"])
        self.assertTrue(truncated["partition"]["truncated_by_max_rows"])
        self.assertEqual(truncated["decision"], "CROSS_VENUE_SPOT_LEAD_LAG_SMOKE_TRUNCATED")

    def test_plan_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.jsonl"
            plan_path = root / "plan.json"
            _write_jsonl(source, _lead_lag_rows())
            _write_plan(plan_path, source)

            with self.assertRaisesRegex(ValueError, "plan sha256 mismatch"):
                build_cross_venue_lead_lag_report(
                    source,
                    plan_path,
                    expected_plan_sha256="0" * 64,
                    temp_parent=root,
                )

    def test_closure_audit_binds_report_manifest_plan_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "thin.jsonl"
            plan_path = root / "plan.json"
            report_path = root / "report.json"
            manifest_path = root / "manifest.json"
            _write_jsonl(source, _lead_lag_rows(lagger_qty=0.5))
            plan_hash = _write_plan(plan_path, source)
            report = run_cross_venue_lead_lag(
                source,
                plan_path,
                report_path,
                expected_plan_sha256=plan_hash,
                temp_parent=root,
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "cross_venue_spot_lead_lag_manifest_v1",
                        "status": "COMPLETED",
                        "final": True,
                        "stop_reason": "completed",
                        "errors": 0,
                        "rows": report["partition"]["rows_read"],
                        "output_path": str(report_path),
                        "plan_path": str(plan_path),
                        "plan_sha256": plan_hash,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys": False,
                        "leverage_or_margin": False,
                        "grid_search": False,
                        "collect": False,
                    }
                ),
                encoding="utf-8",
            )

            audit = build_lead_lag_audit(
                report_path,
                manifest_path,
                plan_path,
                expected_plan_sha256=plan_hash,
            )

        self.assertTrue(audit["audit_passed"])
        self.assertEqual(
            audit["decision"],
            "CROSS_VENUE_SPOT_LEAD_LAG_VERIFIED_REJECTED_NO_FIXED_SIGNALS",
        )
        self.assertEqual(audit["evidence"]["signals"], 0)

    def test_closure_audit_rejects_tampered_signal_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "thin.jsonl"
            plan_path = root / "plan.json"
            report_path = root / "report.json"
            manifest_path = root / "manifest.json"
            _write_jsonl(source, _lead_lag_rows(lagger_qty=0.5))
            plan_hash = _write_plan(plan_path, source)
            report = run_cross_venue_lead_lag(source, plan_path, report_path, temp_parent=root)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            payload["summary"]["signals"] = 7
            report_path.write_text(json.dumps(payload), encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "cross_venue_spot_lead_lag_manifest_v1",
                        "status": "COMPLETED",
                        "final": True,
                        "stop_reason": "completed",
                        "errors": 0,
                        "rows": report["partition"]["rows_read"],
                        "output_path": str(report_path),
                        "plan_path": str(plan_path),
                        "plan_sha256": plan_hash,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys": False,
                        "leverage_or_margin": False,
                        "grid_search": False,
                        "collect": False,
                    }
                ),
                encoding="utf-8",
            )

            audit = build_lead_lag_audit(report_path, manifest_path, plan_path)

        self.assertFalse(audit["audit_passed"])
        self.assertIn("signal_summary_mismatch", audit["failures"])


if __name__ == "__main__":
    unittest.main()
