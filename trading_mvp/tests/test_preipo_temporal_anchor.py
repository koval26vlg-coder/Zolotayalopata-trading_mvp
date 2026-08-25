from __future__ import annotations

import importlib
import inspect
import sys
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class PreIPOTemporalAnchorTests(unittest.TestCase):
    def test_anchor_api_keeps_venue_and_announcement_provenance(self) -> None:
        anchors = importlib.import_module("preipo_temporal_anchor")

        names = {field.name for field in fields(anchors.PreIPOTemporalAnchor)}
        parameters = inspect.signature(anchors.resolve_anchor).parameters

        self.assertTrue({"venue", "announcement_ts"}.issubset(names), names)
        self.assertIn("source_venues", parameters)
        self.assertIn("announcement_timestamps", parameters)

    def test_only_provenanced_equity_first_trade_is_an_exact_anchor(self) -> None:
        module_path = SRC / "preipo_temporal_anchor.py"
        self.assertTrue(module_path.is_file(), module_path)
        anchors = importlib.import_module("preipo_temporal_anchor")

        metadata_only = anchors.resolve_anchor(
            {anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_100.0},
            source_class="official",
        )
        official = anchors.resolve_anchor(
            {anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_100.0},
            source_classes={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "official"},
            source_urls={
                anchors.ANCHOR_OFFICIAL_FIRST_TRADE:
                    "https://support.kraken.com/articles/official-first-trade"
            },
            source_venues={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "kraken"},
            announcement_timestamps={
                anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_000.0
            },
        )
        arbitrary_https = anchors.resolve_anchor(
            {anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_100.0},
            source_classes={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "official"},
            source_urls={
                anchors.ANCHOR_OFFICIAL_FIRST_TRADE:
                    "https://example.test/official-first-trade"
            },
            source_venues={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "kraken"},
            announcement_timestamps={
                anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_000.0
            },
        )
        wrong_venue_host = anchors.resolve_anchor(
            {anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_100.0},
            source_classes={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "official"},
            source_urls={
                anchors.ANCHOR_OFFICIAL_FIRST_TRADE:
                    "https://www.okx.com/help/official-first-trade"
            },
            source_venues={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "kraken"},
            announcement_timestamps={
                anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_000.0
            },
        )
        missing_announcement = anchors.resolve_anchor(
            {anchors.ANCHOR_OFFICIAL_FIRST_TRADE: 1_780_000_100.0},
            source_classes={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "official"},
            source_urls={
                anchors.ANCHOR_OFFICIAL_FIRST_TRADE:
                    "https://support.kraken.com/articles/official-first-trade"
            },
            source_venues={anchors.ANCHOR_OFFICIAL_FIRST_TRADE: "kraken"},
        )
        transition = anchors.resolve_anchor(
            {anchors.ANCHOR_TRANSITION: 1_780_000_100.0},
            source_class="official",
        )

        self.assertIsNotNone(metadata_only)
        self.assertFalse(metadata_only.is_official_time)
        self.assertIsNotNone(official)
        self.assertTrue(official.is_official_time)
        self.assertEqual(official.kind, "official_first_trade_ts")
        self.assertIsNotNone(arbitrary_https)
        self.assertFalse(arbitrary_https.is_official_time)
        self.assertIsNotNone(wrong_venue_host)
        self.assertFalse(wrong_venue_host.is_official_time)
        self.assertIsNotNone(missing_announcement)
        self.assertFalse(missing_announcement.is_official_time)
        self.assertIsNotNone(transition)
        self.assertFalse(transition.is_official_time)

    def test_contract_keeps_equity_first_trade_provenance_on_the_timestamp(self) -> None:
        from preipo_adapters import PreIPOContract

        names = {field.name for field in fields(PreIPOContract)}
        self.assertTrue(
            {
                "official_first_trade_ts",
                "official_first_trade_announcement_ts",
                "official_first_trade_source_class",
                "official_first_trade_source_url",
                "official_first_trade_source_family",
            }.issubset(names),
            names,
        )

    def test_official_announcement_binding_preserves_identity_and_provenance(self) -> None:
        import preipo_adapters

        self.assertTrue(hasattr(preipo_adapters, "bind_official_first_trade"))
        contract = preipo_adapters.PreIPOContract(
            venue="gate",
            contract_id="UNITREE_USDT",
            underlying_symbol="UNITREE",
            quote="USDT",
            lifecycle_status="ipo_pending",
            phase="preipo_continuous",
        )
        bound = preipo_adapters.bind_official_first_trade(
            contract,
            {
                "venue": "gate",
                "source_url": "https://www.gate.com/announcements/article/99999",
                "announcement_ts": 1_780_000_000,
                "contract_id": "UNITREE_USDT",
                "underlying_symbol": "UNITREE",
                "quote": "USDT",
                "official_first_trade_ts": 1_780_003_600,
            },
            source_family="gate_preipo_perpetual_official_first_trade_notice",
        )

        self.assertEqual(bound.official_first_trade_ts, 1_780_003_600)
        self.assertEqual(
            bound.official_first_trade_announcement_ts,
            1_780_000_000,
        )
        self.assertEqual(bound.official_first_trade_source_class, "official")
        self.assertEqual(
            bound.official_first_trade_source_url,
            "https://www.gate.com/announcements/article/99999",
        )
        self.assertEqual(
            bound.official_first_trade_source_family,
            "gate_preipo_perpetual_official_first_trade_notice",
        )

        with self.assertRaises(ValueError):
            preipo_adapters.bind_official_first_trade(
                contract,
                {
                    "venue": "gate",
                    "source_url": "https://www.gate.com/announcements/article/99999",
                    "contract_id": "OTHER_USDT",
                    "underlying_symbol": "OTHER",
                    "quote": "USDT",
                    "official_first_trade_ts": 1_780_003_600,
                },
                source_family="gate_preipo_perpetual_official_first_trade_notice",
            )
        with self.assertRaises(ValueError):
            preipo_adapters.bind_official_first_trade(
                contract,
                {
                    "venue": "gate",
                    "source_url": "https://www.gate.com/announcements/article/99999",
                    "contract_id": "UNITREE_USDT",
                    "underlying_symbol": "UNITREE",
                    "quote": "USDT",
                    "official_first_trade_ts": 1_780_003_600,
                },
                source_family="unregistered_family",
            )
        for missing_field in ("quote", "announcement_ts"):
            with self.subTest(missing_field=missing_field):
                payload = {
                    "venue": "gate",
                    "source_url": "https://www.gate.com/announcements/article/99999",
                    "announcement_ts": 1_780_000_000,
                    "contract_id": "UNITREE_USDT",
                    "underlying_symbol": "UNITREE",
                    "quote": "USDT",
                    "official_first_trade_ts": 1_780_003_600,
                }
                del payload[missing_field]
                with self.assertRaises(ValueError):
                    preipo_adapters.bind_official_first_trade(
                        contract,
                        payload,
                        source_family=(
                            "gate_preipo_perpetual_official_first_trade_notice"
                        ),
                    )

    def test_automation_uses_official_equity_first_trade_as_primary_exact_t0(self) -> None:
        from preipo_adapters import PreIPOContract
        from preipo_automation import discover_and_snapshot
        from preipo_raw_event_store import RawEventStore

        class Adapter:
            venue = "gate"

            def discover_contracts(self):
                return [
                    PreIPOContract(
                        venue="gate",
                        contract_id="UNITREE_USDT",
                        underlying_symbol="UNITREE",
                        quote="USDT",
                        lifecycle_status="ipo_pending",
                        phase="preipo_continuous",
                        source_class="official",
                        official_first_trade_ts=1_780_003_600,
                        official_first_trade_announcement_ts=1_780_000_000,
                        official_first_trade_source_class="official",
                        official_first_trade_source_url=(
                            "https://www.gate.com/announcements/article/99999"
                        ),
                        official_first_trade_source_family=(
                            "gate_preipo_perpetual_official_first_trade_notice"
                        ),
                    )
                ]

            def snapshot_payloads(self, contract):
                return [
                    {
                        "channel": "futures.tickers",
                        "result": {"time": 1_780_000_001, "last": "10.0"},
                    }
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = Path(temp_dir) / "raw_events.jsonl"
            result = discover_and_snapshot(
                adapters={"gate": Adapter()},
                store=RawEventStore(events_path),
                now_ts=1_780_000_000.0,
            )
            rows = list(RawEventStore(events_path).iter_events())

        observation = result["cadence_observation"]
        self.assertEqual(
            observation["event_anchor_kind"], "official_first_trade_ts"
        )
        self.assertEqual(observation["event_anchor_ts"], 1_780_003_600.0)
        self.assertIs(observation["official_confirmed"], True)
        self.assertIs(observation["exact_timestamp"], True)
        lifecycle = next(row for row in rows if row["event_kind"] == "lifecycle")
        self.assertEqual(lifecycle["official_first_trade_ts"], 1_780_003_600)
        self.assertIn("official_first_trade_announcement_ts", lifecycle)
        self.assertEqual(
            lifecycle["official_first_trade_announcement_ts"],
            1_780_000_000,
        )
        self.assertEqual(
            lifecycle["official_first_trade_source_family"],
            "gate_preipo_perpetual_official_first_trade_notice",
        )
        ticker = next(row for row in rows if row["event_kind"] == "ticker")
        self.assertIn("official_first_trade_ts", ticker)
        self.assertIn("official_first_trade_source_url", ticker)
        self.assertIn("official_first_trade_announcement_ts", ticker)
        self.assertEqual(ticker["official_first_trade_ts"], 1_780_003_600)
        self.assertEqual(
            ticker["official_first_trade_announcement_ts"],
            1_780_000_000,
        )
        self.assertEqual(
            ticker["official_first_trade_source_url"],
            "https://www.gate.com/announcements/article/99999",
        )

    def test_contract_rejects_unbound_or_foreign_official_first_trade_proof(self) -> None:
        from preipo_adapters import PreIPOContract

        common = {
            "venue": "gate",
            "contract_id": "UNITREE_USDT",
            "underlying_symbol": "UNITREE",
            "quote": "USDT",
            "lifecycle_status": "ipo_pending",
            "phase": "preipo_continuous",
            "official_first_trade_ts": 1_780_003_600,
            "official_first_trade_source_class": "official",
        }
        with self.assertRaises(ValueError):
            PreIPOContract(
                **common,
                official_first_trade_source_url="https://example.test/notice",
                official_first_trade_source_family="gate_notice",
            )
        with self.assertRaises(ValueError):
            PreIPOContract(
                **common,
                official_first_trade_source_url=(
                    "https://www.gate.com/announcements/article/99999"
                ),
                official_first_trade_source_family="",
            )
        with self.assertRaises(ValueError):
            PreIPOContract(
                **common,
                official_first_trade_source_url=(
                    "https://www.gate.com/announcements/article/99999"
                ),
                official_first_trade_source_family=(
                    "gate_preipo_perpetual_official_first_trade_notice"
                ),
            )
        with self.assertRaises(ValueError):
            PreIPOContract(
                venue="gate",
                contract_id="UNITREE_USDT",
                underlying_symbol="UNITREE",
                quote="USDT",
                lifecycle_status="ipo_pending",
                phase="preipo_continuous",
                official_first_trade_announcement_ts=1_780_000_000,
            )


if __name__ == "__main__":
    unittest.main()
