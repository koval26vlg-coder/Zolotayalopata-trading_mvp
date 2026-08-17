from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slow_liquidity_replay_v1 import ReplayV1Config, replay_slow_liquidity_v1_planonly  # noqa: E402
from slow_liquidity_provenance import build_input_binding  # noqa: E402


def candle(
    exchange: str,
    base: str,
    symbol: str,
    ts: int,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> dict[str, object]:
    return {
        "exchange": exchange,
        "symbol": symbol,
        "base": base,
        "quote": "USDT",
        "granularity": "1h",
        "candle_ts": ts,
        "candle_iso": "1970-01-01T00:00:00Z",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1.0,
        "quote_volume": close,
        "data_status": "ok",
    }


def event(exchange: str, base: str, symbol: str, ts: int) -> dict[str, object]:
    return {
        "event_id": f"fixture-{exchange}-{base}-{ts}",
        "family": "volatility_expansion_continuation_v1",
        "exchange": exchange,
        "symbol": symbol,
        "base": base,
        "quote": "USDT",
        "event_ts": ts - 3600,
        "event_iso": "1970-01-01T00:00:00Z",
        "entry_ts": ts,
        "entry_iso": "1970-01-01T00:00:00Z",
        "entry_price": 100.0,
        "stop_price": 95.0,
        "risk_bps": 500.0,
        "target_bps": 300.0,
    }


class SlowLiquidityReplayV1Tests(unittest.TestCase):
    def test_replay_rejects_stale_census_binding_even_when_row_count_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            census = root / "census.json"
            fixed = root / "fixed_v1.json"
            output = root / "replay.json"
            row = candle("mexc", "AAA", "AAAUSDT", 3600, 100.0, 104.0, 99.0, 103.0)
            history.write_text(json.dumps(row) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture", "rows": 1, "ohlcv_rows": 1}), encoding="utf-8")
            census.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "history_jsonl_path": str(history),
                            "history_manifest_path": str(manifest),
                        },
                        "input_binding": build_input_binding(
                            {"history_jsonl": history, "history_manifest": manifest}
                        ),
                        "event_census": {"normalized_events": [event("mexc", "AAA", "AAAUSDT", 3600)]},
                    }
                ),
                encoding="utf-8",
            )
            fixed.write_text(
                json.dumps(
                    {
                        "event_census_path": str(census),
                        "fixed_signal_v1": {"family": "volatility_expansion_continuation_v1", "max_hold_bars": 2},
                        "cost_model": {"normal_total_cost_bps": 120.0, "stress_total_cost_bps": 245.0},
                        "validation_contract": {"min_trades": 1, "min_oos_trades": 0, "min_event_bases": 1, "min_event_exchanges": 1, "max_single_base_net_pnl_share": 1.0},
                    }
                ),
                encoding="utf-8",
            )
            changed = dict(row)
            changed["close"] = 102.5
            history.write_text(json.dumps(changed) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "stale input binding"):
                replay_slow_liquidity_v1_planonly(fixed_v1_path=fixed, output_path=output)

    def test_replay_accepts_profitable_fixed_fixture_and_keeps_live_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            census = root / "census.json"
            fixed = root / "fixed_v1.json"
            output = root / "replay.json"
            rows = [
                candle("mexc", "AAA", "AAAUSDT", 3600, 100.0, 104.0, 99.0, 103.0),
                candle("gateio", "BBB", "BBB_USDT", 7200, 100.0, 104.0, 99.0, 103.0),
            ]
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture", "rows": len(rows), "ohlcv_rows": len(rows)}), encoding="utf-8")
            census.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "history_jsonl_path": str(history),
                            "history_manifest_path": str(manifest),
                        },
                        "event_census": {
                            "normalized_events": [
                                event("mexc", "AAA", "AAAUSDT", 3600),
                                event("gateio", "BBB", "BBB_USDT", 7200),
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            fixed.write_text(
                json.dumps(
                    {
                        "event_census_path": str(census),
                        "fixed_signal_v1": {
                            "family": "volatility_expansion_continuation_v1",
                            "max_hold_bars": 2,
                        },
                        "cost_model": {
                            "normal_total_cost_bps": 120.0,
                            "stress_total_cost_bps": 245.0,
                        },
                        "validation_contract": {
                            "min_trades": 2,
                            "min_oos_trades": 1,
                            "min_event_bases": 2,
                            "min_event_exchanges": 2,
                            "max_single_base_net_pnl_share": 1.0,
                            "min_profit_factor": 1.2,
                            "min_walk_forward_positive_ratio": 0.5,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = replay_slow_liquidity_v1_planonly(
                fixed_v1_path=fixed,
                output_path=output,
                cfg=ReplayV1Config(walk_forward_windows=2),
            )
            self.assertTrue(output.exists())

        self.assertEqual(result["decision"], "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW")
        self.assertFalse(result["paper_forward_allowed"])
        self.assertFalse(result["live_orders"])
        self.assertFalse(result["api_keys"])
        self.assertFalse(result["grid_allowed_now"])
        self.assertEqual(result["summary"]["trades"], 2)
        self.assertGreater(result["summary"]["expectancy_quote"], 0)

    def test_replay_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            census = root / "census.json"
            fixed = root / "fixed_v1.json"
            output = root / "replay.json"
            row = candle("mexc", "AAA", "AAAUSDT", 3600, 100.0, 104.0, 99.0, 103.0)
            history.write_text(json.dumps(row) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture", "rows": 1, "ohlcv_rows": 1}), encoding="utf-8")
            census.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "history_jsonl_path": str(history),
                            "history_manifest_path": str(manifest),
                        },
                        "event_census": {
                            "normalized_events": [event("mexc", "AAA", "AAAUSDT", 3600)]
                        },
                    }
                ),
                encoding="utf-8",
            )
            fixed.write_text(
                json.dumps(
                    {
                        "event_census_path": str(census),
                        "fixed_signal_v1": {"family": "volatility_expansion_continuation_v1", "max_hold_bars": 2},
                        "cost_model": {"normal_total_cost_bps": 120.0, "stress_total_cost_bps": 245.0},
                        "validation_contract": {"min_trades": 1, "min_oos_trades": 0, "min_event_bases": 1, "min_event_exchanges": 1, "max_single_base_net_pnl_share": 1.0},
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "slow_liquidity_replay_v1.py"),
                    "--fixed-v1",
                    str(fixed),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertTrue(output.exists())

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["coverage"]["events_from_census"], 1)
        self.assertFalse(payload["live_orders"])

    def test_wrapper_and_router_are_guarded_and_non_live(self) -> None:
        wrapper = REPO_ROOT / "tools" / "trading_slow_liquidity_replay_v1_planonly.ps1"
        router = REPO_ROOT / "tools" / "trading_next_goal_step.ps1"
        for path in (wrapper, router):
            self.assertTrue(path.exists())
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for needle in (
            "check_active_run_gate.ps1",
            "BLOCKED_BY_ACTIVE_RUN_GATE",
            "SLOW_LIQUIDITY_FIXED_V1_PLANONLY_READY_FOR_REPLAY_VALIDATION",
            "replay_allowed",
            "grid_allowed",
            "paper_forward_allowed",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ):
            self.assertIn(needle, wrapper_text)
        router_text = router.read_text(encoding="utf-8")
        self.assertIn("trading_slow_liquidity_replay_v1_planonly.ps1", router_text)
        self.assertIn("SLOW_LIQUIDITY_FIXED_V1_REPLAY_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW", router_text)


if __name__ == "__main__":
    unittest.main()
