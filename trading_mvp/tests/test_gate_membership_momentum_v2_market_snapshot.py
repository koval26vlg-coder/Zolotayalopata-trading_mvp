from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from funding import FundingContract  # noqa: E402
import gate_membership_momentum_v2_execution_selection as selection  # noqa: E402
from test_gate_membership_momentum_v2_execution_selection import (  # noqa: E402
    _iso,
    _probe_plan,
)


snapshot = importlib.import_module("gate_membership_momentum_v2_market_snapshot")


def _contracts(plan: dict) -> list[FundingContract]:
    return [
        FundingContract(
            exchange="gateio",
            symbol=row["symbol"],
            base=row["base"],
            quote="USDT",
            status="trading",
            raw={"name": row["symbol"], "status": "trading"},
        )
        for row in plan["candidate_universe"]
    ]


def _candles(plan: dict, symbol: str) -> list[dict]:
    by_symbol = {row["symbol"]: index for index, row in enumerate(plan["candidate_universe"])}
    index = by_symbol[symbol]
    start_day = int(plan["snapshot_contract"]["start_day"])
    signal_day = int(plan["target_event_contract"]["target_signal_day"])
    rows = []
    for day in range(start_day, signal_day + 1):
        relative = day - start_day
        rows.append(
            {
                "ts": day * 86_400,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + relative * (index + 1) / 100.0,
                "volume_base": 20_000.0,
                "volume_quote": 2_000_000.0 + index,
            }
        )
    return rows


class GateMembershipMomentumV2MarketSnapshotTests(unittest.TestCase):
    def test_plan_is_hash_bound_public_only_and_has_prep_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            output = root / "market-snapshot-plan.json"
            result = snapshot.build_market_snapshot_plan(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                output_path=output,
                run_id="momentum-v2-market-snapshot",
                max_runtime_sec=600,
                generated_at_utc="2026-07-17T09:00:00Z",
            )

            self.assertEqual(result["decision"], snapshot.PLAN_DECISION)
            self.assertFalse(result["network_access"])
            self.assertFalse(result["oos_returns_read"])
            self.assertEqual(len(result["candidate_universe"]), 24)
            self.assertTrue(all(row["non_binance_baseline"] for row in result["candidate_universe"]))
            first_window = int(result["execution_contract"]["windows"][0]["start_ts"])
            signal_close = int(result["target_event_contract"]["target_signal_close_ts"])
            self.assertGreaterEqual(first_window - signal_close, 900)
            validated = snapshot.validate_market_snapshot_plan(output, result["plan_hash"])
            self.assertEqual(validated["plan_hash"], result["plan_hash"])

    def test_collect_builds_selection_consumable_public_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            plan_path = root / "market-snapshot-plan.json"
            plan = snapshot.build_market_snapshot_plan(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                output_path=plan_path,
                run_id="momentum-v2-market-snapshot",
                max_runtime_sec=600,
                generated_at_utc="2026-07-17T09:00:00Z",
            )
            signal_close = int(plan["target_event_contract"]["target_signal_close_ts"])
            output = root / "market-snapshot.json"
            result = snapshot.collect_market_snapshot(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                workers=4,
                contract_fetcher=lambda: _contracts(plan),
                candle_fetcher=lambda symbol, _start, _end: _candles(plan, symbol),
                now_fn=lambda: float(signal_close + 60),
                generated_at_utc=_iso(signal_close + 60),
            )

            self.assertEqual(result["decision"], selection.MARKET_SNAPSHOT_READY_DECISION)
            self.assertEqual(result["artifact_hash"], selection.market_snapshot_hash(result))
            self.assertEqual(len(result["rows"]), 24)
            self.assertEqual(result["collection_summary"]["successful_markets"], 24)
            selected = selection.build_selection_artifact(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                market_snapshot_manifest_path=output,
                expected_market_snapshot_hash=result["artifact_hash"],
                output_path=None,
                generated_at_utc=_iso(signal_close + 120),
            )
            self.assertEqual(selected["decision"], selection.SELECTION_READY_DECISION)
            self.assertEqual(len(selected["selected_positions"]), 10)

    def test_collect_refuses_before_due_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            plan_path = root / "market-snapshot-plan.json"
            plan = snapshot.build_market_snapshot_plan(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                output_path=plan_path,
                run_id="momentum-v2-market-snapshot",
                max_runtime_sec=600,
            )
            calls = []
            signal_close = int(plan["target_event_contract"]["target_signal_close_ts"])
            with self.assertRaisesRegex(RuntimeError, "not due"):
                snapshot.collect_market_snapshot(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    output_path=root / "snapshot.json",
                    contract_fetcher=lambda: calls.append("network") or [],
                    candle_fetcher=lambda *_args: [],
                    now_fn=lambda: float(signal_close - 1),
                )
            self.assertEqual(calls, [])

    def test_collect_refuses_missed_window_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            plan_path = root / "market-snapshot-plan.json"
            plan = snapshot.build_market_snapshot_plan(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                output_path=plan_path,
                run_id="momentum-v2-market-snapshot",
                max_runtime_sec=600,
            )
            calls = []
            first_window = int(plan["execution_contract"]["windows"][0]["start_ts"])
            with self.assertRaisesRegex(RuntimeError, "window missed"):
                snapshot.collect_market_snapshot(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    output_path=root / "snapshot.json",
                    contract_fetcher=lambda: calls.append("network") or [],
                    candle_fetcher=lambda *_args: [],
                    now_fn=lambda: float(first_window),
                )
            self.assertEqual(calls, [])

    def test_run_mvp_exposes_fail_closed_visible_routes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        wrapper = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((root / "trading_mvp" / "run_mvp.ps1"))
        visible = root / "tools" / "start_gate_membership_momentum_v2_market_snapshot_visible.ps1"
        self.assertIn('"fast-edge-membership-momentum-v2-market-snapshot-plan"', wrapper)
        self.assertIn('"fast-edge-membership-momentum-v2-market-snapshot-collect"', wrapper)
        self.assertTrue(visible.is_file())
        self.assertIn("ConfirmedPublicMarketSnapshotCollect", visible.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
