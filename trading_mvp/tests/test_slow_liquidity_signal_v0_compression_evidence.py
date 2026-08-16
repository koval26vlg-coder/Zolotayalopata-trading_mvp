from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import slow_liquidity_signal_v0_compression_evidence as m  # noqa: E402


class CompressionEvidenceTests(unittest.TestCase):
    def test_bindings_reference_frozen_v0_contract(self) -> None:
        bindings = m.load_bindings()
        self.assertEqual(bindings["threshold"], 1.2)
        self.assertTrue(bindings["v6_sha256"])
        self.assertTrue(bindings["packet_sha256"])

    def test_synthetic_flat_series_passes_and_volatile_fails(self) -> None:
        # flat series: range 0 -> ratio 0 (passes any threshold)
        flat = [
            {"exchange": "mexc", "symbol": "FLATUSDT", "granularity": "1h",
             "data_status": "ok", "candle_ts": 3600 * i, "high": 10.0,
             "low": 10.0, "close": 10.0}
            for i in range(200)
        ]
        result = m.compute_compression_distribution(flat)
        self.assertEqual(result["market_count"], 0)  # atr==0 -> skipped
        # volatile random-walk-like series
        volatile = []
        price = 100.0
        for i in range(200):
            drift = 1.0 if (i // 7) % 2 == 0 else -0.9
            price = max(1.0, price + drift)
            volatile.append(
                {"exchange": "mexc", "symbol": "VOLUSDT", "granularity": "1h",
                 "data_status": "ok", "candle_ts": 3600 * i, "high": price + 0.5,
                 "low": price - 0.5, "close": price}
            )
        result = m.compute_compression_distribution(volatile)
        self.assertEqual(result["market_count"], 1)
        self.assertGreater(result["median_of_market_medians"], 1.2)

    def test_real_dataset_evidence_zero_passes(self) -> None:
        if not m.V6_JSONL.is_file():
            self.skipTest("v6 dataset not present on this machine")
        payload = m.build_evidence_payload()
        m.validate_evidence_payload(payload)
        distribution = payload["distribution"]
        self.assertEqual(distribution["market_count"], 18)
        self.assertEqual(distribution["bars_passing_contract_threshold"], 0)
        self.assertGreater(distribution["median_of_market_medians"], 10.0)
        self.assertEqual(
            distribution["pass_counts_by_reference_threshold"]["4.0"], 0
        )

    def test_checked_in_artifact_matches_rebuild(self) -> None:
        if not m.OUTPUT_PATH.is_file():
            self.skipTest("evidence artifact not yet written")
        on_disk = json.loads(m.OUTPUT_PATH.read_text(encoding="utf-8"))
        rebuilt = m.build_evidence_payload()
        self.assertEqual(on_disk["evidence_hash"], rebuilt["evidence_hash"])


if __name__ == "__main__":
    unittest.main()
