from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cross_sectional_capitulation import build_report, run_report  # noqa: E402
from cross_sectional_capitulation_audit import build_audit  # noqa: E402


BASES = [f"B{index:02d}" for index in range(12)]
BAR_SEC = 14400


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_universe(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "name", "symbol", "coin_id"])
        writer.writeheader()
        for rank, base in enumerate(BASES, 1):
            writer.writerow({"rank": rank, "name": base, "symbol": base, "coin_id": base.lower()})


def _write_history(path: Path, *, signal_volume: float = 100000.0) -> None:
    rows = []
    for base in BASES:
        for index in range(30):
            open_price = high = low = close = 100.0
            quote_volume = 30000.0
            if base == BASES[0] and index == 20:
                open_price, high, low, close = 90.0, 95.0, 80.0, 90.0
                quote_volume = signal_volume
            elif base == BASES[0] and index == 21:
                open_price, high, low, close = 92.0, 101.0, 91.0, 100.0
            rows.append(
                {
                    "source": "slow_liquidity_history",
                    "exchange": "gateio",
                    "symbol": f"{base}_USDT",
                    "base": base,
                    "quote": "USDT",
                    "granularity": "4h",
                    "candle_ts": index * BAR_SEC,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1000.0,
                    "quote_volume": quote_volume,
                    "data_status": "ok",
                    "error": "",
                }
            )
    # Grouping by market is deliberate; the replay must not assume global time order.
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_plan(root: Path, *, signal_volume: float = 100000.0) -> tuple[Path, str]:
    history = root / "history.jsonl"
    manifest = root / "manifest.json"
    universe = root / "universe.csv"
    plan_path = root / "plan.json"
    _write_history(history, signal_volume=signal_volume)
    _write_universe(universe)
    manifest.write_text(json.dumps({"final": True, "errors": 0}), encoding="utf-8")
    plan = {
        "schema": "cross_sectional_capitulation_plan_v1",
        "branch": "cross_sectional_capitulation_rebound_4h_spot",
        "research_only": True,
        "fixed_parameters_no_grid": True,
        "strategy_accepted": False,
        "data": {
            "history_jsonl_path": str(history),
            "history_jsonl_sha256": _sha(history),
            "history_manifest_path": str(manifest),
            "history_manifest_sha256": _sha(manifest),
            "universe_path": str(universe),
            "universe_sha256": _sha(universe),
            "universe_asof": -1,
            "analysis_start": 0,
            "max_universe_rank": 50,
            "exchange": "gateio",
            "instrument": "spot",
            "quote": "USDT",
            "timeframe": "4h",
            "bar_sec": BAR_SEC,
            "require_source_status": "ok",
            "retain_no_data_and_api_error_bases_in_coverage": True,
        },
        "signal": {
            "name": "cross_sectional_capitulation_rebound_v1",
            "direction": "long_only_spot",
            "lookback_bars": 6,
            "base_return_max_bps": -800.0,
            "residual_vs_peer_median_max_bps": -600.0,
            "min_peer_count": 10,
            "close_location_min": 0.60,
            "volume_lookback_bars": 20,
            "min_current_quote_volume": 50000.0,
            "min_trailing_median_quote_volume": 25000.0,
            "min_volume_ratio": 1.50,
            "hold_bars": 6,
            "cooldown_bars": 12,
            "max_concurrent_positions": 3,
            "same_timestamp_priority": "most_negative_residual_first",
        },
        "execution": {
            "notional_quote": 100.0,
            "normal_round_trip_fee_bps": 40.0,
            "normal_spread_slippage_buffer_bps": 80.0,
            "normal_total_cost_bps": 120.0,
            "stress_total_cost_bps": 245.0,
        },
        "validation": {
            "train_fraction": 0.70,
            "walk_forward_folds": 4,
            "min_total_trades": 50,
            "min_oos_trades": 15,
            "min_distinct_oos_bases": 5,
            "min_oos_expectancy_bps": 0.0,
            "min_oos_profit_factor": 1.20,
            "min_positive_fold_ratio": 0.60,
            "min_trades_per_fold": 5,
            "min_stress_expectancy_bps": 0.0,
            "max_top_base_positive_contribution": 0.40,
            "max_drawdown_quote": 25.0,
        },
    }
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan_path, _sha(plan_path)


class CrossSectionalCapitulationTests(unittest.TestCase):
    def test_fixed_signal_uses_next_open_and_subtracts_base_costs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan_hash = _write_plan(root)
            report = build_report(plan_path, expected_plan_sha256=plan_hash)

        self.assertTrue(report["universe"]["coverage_gate"])
        self.assertEqual(report["summary"]["fixed_signal_candidates"], 1)
        self.assertEqual(report["summary"]["executed_trades"], 1)
        trade = report["trades"][0]
        self.assertEqual(trade["base"], BASES[0])
        self.assertEqual(trade["signal_ts"], 21 * BAR_SEC)
        self.assertEqual(trade["entry_ts"], 21 * BAR_SEC)
        self.assertEqual(trade["entry_price"], 92.0)
        self.assertEqual(trade["exit_price"], 100.0)
        expected_gross = (100.0 / 92.0 - 1.0) * 10000.0
        self.assertAlmostEqual(trade["gross_pnl_bps"], expected_gross)
        self.assertAlmostEqual(trade["normal_net_pnl_bps"], expected_gross - 120.0)
        self.assertAlmostEqual(trade["stress_net_pnl_bps"], expected_gross - 245.0)
        self.assertFalse(report["strategy_accepted"])
        self.assertFalse(report["paper_forward_ready"])

    def test_low_signal_volume_blocks_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, _ = _write_plan(Path(tmp), signal_volume=40000.0)
            report = build_report(plan_path)

        self.assertEqual(report["summary"]["fixed_signal_candidates"], 0)
        self.assertEqual(report["decision"], "CROSS_SECTIONAL_CAPITULATION_REJECTED_NO_FIXED_SIGNALS")
        self.assertGreater(report["filters"].get("current_quote_volume", 0), 0)

    def test_plan_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, _ = _write_plan(Path(tmp))
            with self.assertRaisesRegex(ValueError, "plan sha256 mismatch"):
                build_report(plan_path, expected_plan_sha256="0" * 64)

    def test_run_report_writes_research_only_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan_hash = _write_plan(root)
            output = root / "report.json"
            report = run_report(plan_path, output, expected_plan_sha256=plan_hash)
            stored = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(stored["decision"], report["decision"])
        self.assertFalse(stored["grid_search"])
        self.assertFalse(stored["collect"])
        self.assertFalse(stored["live_orders"])

    def test_no_signal_closure_audit_passes_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan_hash = _write_plan(root, signal_volume=40000.0)
            output = root / "report.json"
            manifest = root / "run.manifest.json"
            report = run_report(plan_path, output, expected_plan_sha256=plan_hash)
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "cross_sectional_capitulation_manifest_v1",
                        "status": "COMPLETED",
                        "final": True,
                        "stop_reason": "completed",
                        "errors": 0,
                        "rows": report["history"]["total_source_rows"],
                        "output_path": str(output),
                        "plan_path": str(plan_path),
                        "plan_sha256": plan_hash,
                    }
                ),
                encoding="utf-8",
            )
            audit = build_audit(output, manifest, plan_path, expected_plan_sha256=plan_hash)
            self.assertTrue(audit["audit_passed"])

            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["summary"]["fixed_signal_candidates"] = 3
            output.write_text(json.dumps(payload), encoding="utf-8")
            tampered = build_audit(output, manifest, plan_path)

        self.assertFalse(tampered["audit_passed"])
        self.assertIn("candidate_summary_mismatch", tampered["failures"])


if __name__ == "__main__":
    unittest.main()
