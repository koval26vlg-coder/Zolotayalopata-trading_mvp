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

from slow_liquidity_event_census import (  # noqa: E402
    EventCensusConfig,
    run_slow_liquidity_event_census_planonly,
)


def candle(
    exchange: str,
    base: str,
    granularity: str,
    ts: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    quote_volume: float = 100.0,
) -> dict[str, object]:
    return {
        "source": "slow_liquidity_history",
        "exchange": exchange,
        "symbol": f"{base}_USDT" if exchange == "gateio" else f"{base}USDT",
        "base": base,
        "quote": "USDT",
        "granularity": granularity,
        "job_key": f"{exchange}:{base}:{granularity}",
        "history_start_ts": 0,
        "history_start_iso": "1970-01-01T00:00:00Z",
        "history_end_ts": 999999,
        "history_end_iso": "1970-01-12T13:46:39Z",
        "candle_ts": ts,
        "candle_iso": "1970-01-01T00:00:00Z",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": quote_volume / close,
        "quote_volume": quote_volume,
        "trade_count_if_available": None,
        "data_status": "ok",
        "error": "",
    }


def fixture_rows_with_census_events(exchange: str, base: str = "AAA") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(40):
        ts = idx * 4 * 3600
        rows.append(
            candle(
                exchange,
                base,
                "4h",
                ts,
                100.0 + idx * 0.10,
                101.0 + idx * 0.10,
                99.5 + idx * 0.10,
                100.7 + idx * 0.10,
                1000.0,
            )
        )

    start = 40 * 4 * 3600
    close = 100.0
    for idx in range(80):
        ts = start + idx * 3600
        quote_volume = 100.0 + idx
        high = close * 1.003
        low = close * 0.997
        next_close = close * 1.0002
        if idx == 72:
            high = close * 1.095
            low = close * 0.998
            next_close = close * 1.085
            quote_volume = 10000.0
        rows.append(candle(exchange, base, "1h", ts, close, high, low, next_close, quote_volume))
        close = next_close
    return rows


def rescope_plan() -> dict[str, object]:
    return {
        "decision": "SLOW_LIQUIDITY_FIXED_V0_REJECTED_NO_EVENT_BASE_RATE_READY_FOR_EVENT_CENSUS_V1_PLANONLY",
        "v1_event_census_plan": {
            "clean_bases": ["AAA"],
            "required_timeframes": ["1h", "4h"],
            "acceptance_before_replay": {
                "min_independent_events": 1,
                "min_event_bases": 1,
                "min_event_exchanges": 1,
                "min_target_geometry_bps": 300.0,
            },
        },
    }


class SlowLiquidityEventCensusTests(unittest.TestCase):
    def test_event_census_finds_base_rate_and_keeps_replay_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            rescope = root / "rescope.json"
            quality = root / "quality.json"
            output = root / "event_census.json"
            rows = fixture_rows_with_census_events("mexc") + fixture_rows_with_census_events("gateio")
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture"}), encoding="utf-8")
            rescope.write_text(json.dumps(rescope_plan()), encoding="utf-8")
            quality.write_text(
                json.dumps(
                    {
                        "accepted": True,
                        "clean_markets": {
                            "two_exchange_full_coverage_1h4h_bases": ["AAA"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_slow_liquidity_event_census_planonly(
                history_jsonl_path=history,
                history_manifest_path=manifest,
                rescope_path=rescope,
                quality_path=quality,
                output_path=output,
                config=EventCensusConfig(
                    min_independent_events=1,
                    min_event_bases=1,
                    min_event_exchanges=1,
                    max_single_base_event_fraction=1.0,
                    min_target_geometry_bps=300.0,
                ),
            )
            self.assertTrue(output.exists())

        self.assertEqual(result["decision"], "SLOW_LIQUIDITY_EVENT_CENSUS_V1_ACCEPTED_READY_FOR_FIXED_V1_PLANONLY")
        self.assertFalse(result["replay_allowed_now"])
        self.assertFalse(result["grid_allowed_now"])
        self.assertGreaterEqual(result["event_census"]["independent_events"], 1)
        self.assertTrue(result["event_census"]["accepted_families"])

    def test_event_census_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            rescope = root / "rescope.json"
            quality = root / "quality.json"
            output = root / "event_census.json"
            rows = fixture_rows_with_census_events("mexc") + fixture_rows_with_census_events("gateio")
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture"}), encoding="utf-8")
            rescope.write_text(json.dumps(rescope_plan()), encoding="utf-8")
            quality.write_text(json.dumps({"accepted": True}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "slow_liquidity_event_census.py"),
                    "--history-jsonl",
                    str(history),
                    "--history-manifest",
                    str(manifest),
                    "--rescope",
                    str(rescope),
                    "--quality",
                    str(quality),
                    "--output",
                    str(output),
                    "--min-independent-events",
                    "1",
                    "--min-event-bases",
                    "1",
                    "--min-event-exchanges",
                    "1",
                    "--max-single-base-event-fraction",
                    "1.0",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertTrue(output.exists())

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["replay_allowed_now"])

    def test_wrappers_are_guarded_and_non_live(self) -> None:
        for script_name in (
            "trading_slow_liquidity_rescope_planonly.ps1",
            "trading_slow_liquidity_event_census_planonly.ps1",
        ):
            script = REPO_ROOT / "tools" / script_name
            self.assertTrue(script.exists())
            text = script.read_text(encoding="utf-8")
            for needle in (
                "check_active_run_gate.ps1",
                "BLOCKED_BY_ACTIVE_RUN_GATE",
                "replay_allowed",
                "grid_allowed",
                "paper_forward_allowed",
                "live_orders",
                "api_keys",
                "leverage_or_margin",
            ):
                self.assertIn(needle, text)

    def test_next_goal_step_knows_slow_liquidity_rescope_and_census(self) -> None:
        script = REPO_ROOT / "tools" / "trading_next_goal_step.ps1"
        text = script.read_text(encoding="utf-8")
        for needle in (
            "trading_slow_liquidity_rescope_planonly.ps1",
            "trading_slow_liquidity_event_census_planonly.ps1",
            "SLOW_LIQUIDITY_FEATURE_NORMALIZER_REJECTED_RESCOPE_V0_PLANONLY",
            "SLOW_LIQUIDITY_FIXED_V0_REJECTED_RUN_EVENT_CENSUS_V1_PLANONLY",
            "SLOW_LIQUIDITY_EVENT_CENSUS_V1_REJECTED_SELECT_NEXT_BRANCH",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
