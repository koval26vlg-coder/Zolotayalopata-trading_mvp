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

from slow_liquidity_feature_normalizer import (  # noqa: E402
    SlowLiquidityFeatureConfig,
    normalize_slow_liquidity_features_planonly,
)
from slow_liquidity_provenance import state_hash_from_rows  # noqa: E402


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


def fixture_rows_for_event(exchange: str, base: str = "AAA") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(7):
        ts = idx * 4 * 3600
        rows.append(candle(exchange, base, "4h", ts, 100.0 + idx, 101.0 + idx, 99.5 + idx, 100.8 + idx, 1000.0))

    start = 24 * 3600
    one_hour = [
        (100.0, 100.6, 99.9, 100.2, 100.0),
        (100.2, 100.8, 100.0, 100.4, 110.0),
        (100.4, 101.0, 100.1, 100.8, 120.0),
        (100.8, 101.1, 100.2, 100.9, 130.0),
        (100.9, 102.6, 100.8, 102.2, 1000.0),  # breakout
        (102.2, 102.4, 101.0, 101.8, 400.0),  # retest and hold
        (101.8, 102.2, 101.6, 102.0, 350.0),  # delayed entry
        (102.0, 102.3, 101.9, 102.1, 300.0),
    ]
    for idx, (open_, high, low, close, quote_volume) in enumerate(one_hour):
        rows.append(candle(exchange, base, "1h", start + idx * 3600, open_, high, low, close, quote_volume))
    return rows


def fixed_plan() -> dict[str, object]:
    return {
        "decision": "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER",
        "clean_slice": {
            "clean_bases": ["AAA"],
            "required_timeframes": ["1h", "4h"],
            "disabled_timeframes": ["15m"],
            "min_clean_bases_required": 1,
        },
        "base_fee_cost_model": {
            "minimum_target_after_cost_bps": 300.0,
        },
        "fixed_signal_v0": {
            "name": "slow_liquidity_regime_breakout_retest_v0",
            "direction": "long_only_spot",
            "lookback_1h_bars": 4,
            "context_4h_bars": 2,
            "compression_range_width_max_atr": 2.0,
            "breakout_close_buffer_bps": 60.0,
            "volume_percentile_min": 0.70,
            "retest_window_bars": 2,
            "retest_tolerance_atr": 0.50,
            "entry_delay_bars": 1,
            "stop_atr_multiple": 1.20,
            "min_stop_bps": 120.0,
            "target_r_multiple": 2.20,
            "min_target_bps": 300.0,
            "max_hold_bars": 24,
            "cooldown_bars_after_exit": 1,
            "max_events_per_base_per_week": 3,
        },
        "validation_contract": {
            "min_independent_events": 1,
            "min_bases": 1,
        },
    }


class SlowLiquidityFeatureNormalizerTests(unittest.TestCase):
    def test_state_hash_changes_when_same_count_has_different_market_state(self) -> None:
        rows = fixture_rows_for_event("mexc")
        changed = [dict(row) for row in rows]
        changed[0]["close"] = float(changed[0]["close"]) + 0.25

        self.assertEqual(len(rows), len(changed))
        self.assertNotEqual(state_hash_from_rows(rows), state_hash_from_rows(changed))

    def test_normalizer_builds_fixed_signal_event_and_allows_replay_when_thresholds_are_relaxed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            plan = root / "fixed_signal.json"
            quality = root / "quality.json"
            output = root / "normalizer.json"
            rows = fixture_rows_for_event("mexc") + fixture_rows_for_event("gateio")
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture"}), encoding="utf-8")
            plan.write_text(json.dumps(fixed_plan()), encoding="utf-8")
            quality.write_text(json.dumps({"accepted": True}), encoding="utf-8")

            result = normalize_slow_liquidity_features_planonly(
                history_jsonl_path=history,
                history_manifest_path=manifest,
                fixed_signal_path=plan,
                quality_path=quality,
                output_path=output,
                config=SlowLiquidityFeatureConfig(
                    min_independent_events=1,
                    min_event_bases=1,
                    min_event_exchanges=1,
                    max_single_base_event_fraction=1.0,
                    cluster_window_sec=12 * 3600,
                ),
            )
            self.assertTrue(output.exists())

        self.assertEqual(result["decision"], "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_READY_FOR_FIXED_REPLAY_VALIDATION")
        self.assertTrue(result["replay_allowed_now"])
        self.assertEqual(result["event_set"]["raw_candidate_events"], 2)
        self.assertEqual(result["event_set"]["independent_events"], 1)
        self.assertEqual(result["event_set"]["event_bases"], 1)
        self.assertIn("state_hash", result["input_binding"])
        self.assertEqual(result["state_hash"], result["input_binding"]["state_hash"])
        self.assertEqual(
            result["event_set"]["sample_events"][0]["compression_metric"],
            "range_width_over_atr",
        )

    def test_scaled_compression_v1_uses_frozen_metric_without_changing_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            plan = root / "fixed_signal_v1.json"
            quality = root / "quality.json"
            output = root / "normalizer.json"
            rows = fixture_rows_for_event("mexc") + fixture_rows_for_event("gateio")
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture-v1"}), encoding="utf-8")
            v1 = fixed_plan()
            v1["decision"] = "SLOW_LIQUIDITY_FIXED_V1_COMPRESSION_PLANONLY_READY_FOR_FEATURE_NORMALIZER"
            v1["fixed_signal_v1"] = dict(v1.pop("fixed_signal_v0"))
            v1["fixed_signal_v1"]["compression_metric"] = "range_width_over_atr_sqrt_lookback"
            v1["fixed_signal_v1"]["name"] = "slow_liquidity_regime_breakout_retest_v1_scaled_compression"
            plan.write_text(json.dumps(v1), encoding="utf-8")
            quality.write_text(json.dumps({"accepted": True}), encoding="utf-8")

            result = normalize_slow_liquidity_features_planonly(
                history_jsonl_path=history,
                history_manifest_path=manifest,
                fixed_signal_path=plan,
                quality_path=quality,
                output_path=output,
                config=SlowLiquidityFeatureConfig(
                    min_independent_events=1,
                    min_event_bases=1,
                    min_event_exchanges=1,
                    max_single_base_event_fraction=1.0,
                ),
            )

        self.assertEqual(result["fixed_contract"]["signal"]["compression_metric"], "range_width_over_atr_sqrt_lookback")
        self.assertEqual(result["event_set"]["raw_candidate_events"], 2)
        self.assertEqual(
            result["event_set"]["sample_events"][0]["compression_metric"],
            "range_width_over_atr_sqrt_lookback",
        )

    def test_normalizer_rejects_when_fixed_events_are_too_few(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            plan = root / "fixed_signal.json"
            quality = root / "quality.json"
            output = root / "normalizer.json"
            rows = fixture_rows_for_event("mexc") + fixture_rows_for_event("gateio")
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture"}), encoding="utf-8")
            plan.write_text(json.dumps(fixed_plan()), encoding="utf-8")
            quality.write_text(json.dumps({"accepted": True}), encoding="utf-8")

            result = normalize_slow_liquidity_features_planonly(
                history_jsonl_path=history,
                history_manifest_path=manifest,
                fixed_signal_path=plan,
                quality_path=quality,
                output_path=output,
                config=SlowLiquidityFeatureConfig(
                    min_independent_events=2,
                    min_event_bases=1,
                    min_event_exchanges=1,
                    max_single_base_event_fraction=1.0,
                ),
            )

        self.assertEqual(result["decision"], "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_REJECTED_INSUFFICIENT_EVENTS")
        self.assertFalse(result["replay_allowed_now"])
        self.assertIn("min_independent_events", result["reasons"])

    def test_feature_normalizer_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            plan = root / "fixed_signal.json"
            quality = root / "quality.json"
            output = root / "normalizer.json"
            rows = fixture_rows_for_event("mexc") + fixture_rows_for_event("gateio")
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture"}), encoding="utf-8")
            plan.write_text(json.dumps(fixed_plan()), encoding="utf-8")
            quality.write_text(json.dumps({"accepted": True}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "slow_liquidity_feature_normalizer.py"),
                    "--history-jsonl",
                    str(history),
                    "--history-manifest",
                    str(manifest),
                    "--fixed-signal",
                    str(plan),
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
        self.assertTrue(payload["replay_allowed_now"])

    def test_powershell_wrapper_is_guarded_and_non_live(self) -> None:
        script = REPO_ROOT / "tools" / "trading_slow_liquidity_feature_normalizer_planonly.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        for needle in (
            "check_active_run_gate.ps1",
            "BLOCKED_BY_ACTIVE_RUN_GATE",
            "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_READY_FOR_FIXED_REPLAY_VALIDATION",
            "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_REJECTED_INSUFFICIENT_EVENTS",
            "grid_allowed",
            "paper_forward_allowed",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
