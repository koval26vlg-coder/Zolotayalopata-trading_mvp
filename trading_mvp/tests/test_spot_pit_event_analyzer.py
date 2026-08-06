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

from spot_pit_event_analyzer import analyze  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(root: Path, *, min_bases: int = 10, min_signals: int = 1) -> Path:
    path = root / "plan.json"
    path.write_text(
        json.dumps(
            {
                "schema": "spot_pit_event_forward_plan_v1",
                "fixed_signal": {
                    "shock_lookback_min": 3,
                    "hold_min": 2,
                    "cooldown_min": 10,
                    "base_return_max_bps": -500.0,
                    "residual_vs_cross_sectional_median_max_bps": -300.0,
                    "reclaim_from_rolling_low_min_bps": 100.0,
                    "max_spread_bps": 30.0,
                    "min_quote_volume_24h": 500000.0,
                    "min_peer_count": 10,
                    "max_concurrent_positions": 3,
                },
                "economics": {
                    "normal_total_cost_bps": 120.0,
                    "stress_total_cost_bps": 245.0,
                    "notional_quote": 100.0,
                },
                "early_gates": {
                    "coverage_gate_after_hours": 2,
                    "futility_gate_after_hours": 48,
                    "min_valid_cycle_ratio": 0.95,
                    "min_bases_per_venue": min_bases,
                    "min_two_venue_bases": min_bases,
                    "min_fixed_signals_by_48h": min_signals,
                    "min_signal_bases_by_48h": 1,
                },
                "validation": {
                    "chronological_train_fraction": 0.7,
                    "walk_forward_folds": 2,
                    "min_total_trades": 1,
                    "min_oos_trades": 1,
                    "min_oos_expectancy_bps": 0.0,
                    "min_oos_profit_factor": 1.0,
                    "min_distinct_oos_bases": 1,
                    "max_top_base_positive_contribution": 1.0,
                    "min_positive_fold_ratio": 0.0,
                    "min_stress_expectancy_bps": -10000.0,
                    "max_drawdown_quote": 1000.0,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _row(cycle: int, base: str, exchange: str, mid: float, *, spread_bps: float = 10.0) -> dict[str, object]:
    half = spread_bps / 20000.0
    return {
        "run_id": "test-run",
        "cycle": cycle,
        "snapshot_ts": f"2026-01-01T00:{cycle:02d}:00+00:00",
        "exchange": exchange,
        "symbol": f"{base}USDT" if exchange == "mexc" else f"{base}_USDT",
        "base": base,
        "quote": "USDT",
        "listed_now": True,
        "tombstone": False,
        "bid": mid * (1.0 - half),
        "ask": mid * (1.0 + half),
        "spread_bps": spread_bps,
        "quote_volume_24h": 1_000_000.0,
        "eligible_non_binance_spot": True,
    }


def _dataset(
    root: Path,
    plan: Path,
    rows_by_cycle: list[list[dict[str, object]]],
    *,
    final: bool,
    elapsed_hours: float,
    stop_reason: str | None = None,
) -> Path:
    run_dir = root / "run"
    segments = run_dir / "segments"
    segments.mkdir(parents=True)
    with (segments / "segment_000001.jsonl").open("w", encoding="utf-8") as handle:
        for rows in rows_by_cycle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
    cycles_path = run_dir / "cycles.jsonl"
    with cycles_path.open("w", encoding="utf-8") as handle:
        for cycle, rows in enumerate(rows_by_cycle, 1):
            handle.write(json.dumps({"run_id": "test-run", "cycle": cycle, "rows": len(rows)}) + "\n")
    manifest = run_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "spot_pit_event_collector_manifest_v1",
                "run_id": "test-run",
                "plan_sha256": _sha(plan),
                "segments_dir": str(segments),
                "cycles_path": str(cycles_path),
                "interval_sec": 60,
                "elapsed_active_sec": elapsed_hours * 3600.0,
                "final": final,
                "stop_reason": stop_reason,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _normal_cycle(cycle: int, count: int = 12) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(count):
        base = f"B{index:02d}"
        rows.extend((_row(cycle, base, "mexc", 100.0), _row(cycle, base, "gateio", 100.0)))
    return rows


class SpotPitEventAnalyzerTests(unittest.TestCase):
    def test_fixed_signal_uses_same_venue_for_lookback_entry_and_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan(root)
            cycles = []
            prices = {1: 100.0, 2: 100.0, 3: 100.0, 4: 90.0, 5: 92.0, 6: 93.0, 7: 95.0, 8: 100.0}
            for cycle in range(1, 9):
                rows = _normal_cycle(cycle)
                rows = [row for row in rows if row["base"] != "B00"]
                rows.extend((_row(cycle, "B00", "mexc", prices[cycle]), _row(cycle, "B00", "gateio", prices[cycle], spread_bps=12.0)))
                cycles.append(rows)
            manifest = _dataset(root, plan, cycles, final=True, elapsed_hours=8 / 60)

            report = analyze(plan, manifest, expected_plan_sha256=_sha(plan))

        self.assertEqual(report["summary"]["fixed_signals"], 1)
        self.assertEqual(report["summary"]["completed_trades"], 1)
        trade = report["trades"][0]
        self.assertEqual(trade["exchange"], "mexc")
        self.assertEqual(trade["entry_cycle"], 6)
        self.assertEqual(trade["exit_cycle"], 8)
        self.assertAlmostEqual(trade["normal_net_pnl_bps"], trade["gross_pnl_bps"] - 120.0)

    def test_venue_switch_cannot_create_artificial_shock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan(root)
            cycles = []
            for cycle in range(1, 6):
                rows = _normal_cycle(cycle)
                rows = [row for row in rows if row["base"] != "B00"]
                mexc_spread = 2.0 if cycle <= 3 else 20.0
                gate_spread = 20.0 if cycle <= 3 else 2.0
                rows.extend((_row(cycle, "B00", "mexc", 100.0, spread_bps=mexc_spread), _row(cycle, "B00", "gateio", 90.0, spread_bps=gate_spread)))
                cycles.append(rows)
            manifest = _dataset(root, plan, cycles, final=False, elapsed_hours=1)

            report = analyze(plan, manifest)

        self.assertEqual(report["summary"]["fixed_signals"], 0)

    def test_checkpoint_stops_for_bad_data_before_futility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan(root, min_bases=10)
            manifest = _dataset(root, plan, [_normal_cycle(cycle, count=5) for cycle in range(1, 5)], final=False, elapsed_hours=2)
            report = analyze(plan, manifest)

        self.assertEqual(report["decision"], "SPOT_PIT_EVENT_CHECKPOINT_DATA_QUALITY_STOP_RECOMMENDED")
        self.assertFalse(report["data_quality"]["passed"])
        self.assertFalse(report["futility_gate"]["stop_recommended"])

    def test_checkpoint_rejects_futile_signal_only_with_valid_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan(root, min_signals=2)
            manifest = _dataset(root, plan, [_normal_cycle(cycle) for cycle in range(1, 6)], final=False, elapsed_hours=48)
            report = analyze(plan, manifest)

        self.assertEqual(report["decision"], "SPOT_PIT_EVENT_CHECKPOINT_FUTILITY_STOP_RECOMMENDED")
        self.assertTrue(report["data_quality"]["passed"])
        self.assertTrue(report["futility_gate"]["stop_recommended"])

    def test_zero_row_network_cycle_is_quality_evidence_not_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan(root)
            cycles = [_normal_cycle(1), [], _normal_cycle(3)]
            manifest = _dataset(root, plan, cycles, final=False, elapsed_hours=2)
            report = analyze(plan, manifest)

        self.assertEqual(report["data_quality"]["total_cycles"], 3)
        self.assertEqual(report["data_quality"]["valid_cycles"], 2)
        self.assertEqual(report["decision"], "SPOT_PIT_EVENT_CHECKPOINT_DATA_QUALITY_STOP_RECOMMENDED")

    def test_plan_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan(root)
            manifest = _dataset(root, plan, [_normal_cycle(1)], final=False, elapsed_hours=0)
            with self.assertRaisesRegex(ValueError, "plan sha256 mismatch"):
                analyze(plan, manifest, expected_plan_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
