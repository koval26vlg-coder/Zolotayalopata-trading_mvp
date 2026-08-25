from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_perp_event import (  # noqa: E402
    ACTIVE_VENUES,
    EXIT_LABELS,
    LIFECYCLE_STATUSES,
    PreIPOEvent,
    PreIPOEventError,
    build_entry_candidates,
    parse_announcement,
    replay_preipo_event,
    rebase_position,
    transition_event,
)


class PreIPOEventTests(unittest.TestCase):
    def test_event_model_accepts_every_plan_active_venue(self) -> None:
        self.assertEqual(set(ACTIVE_VENUES), {"okx", "gate", "bitmex", "kraken"})
        official_hosts = {
            "okx": "https://www.okx.com/help/pre-ipo",
            "gate": "https://www.gate.com/announcements/pre-ipo",
            "bitmex": "https://www.bitmex.com/app/announcements/pre-ipo",
            "kraken": "https://support.kraken.com/articles/pre-ipo",
        }
        for venue in ACTIVE_VENUES:
            with self.subTest(venue=venue):
                event = parse_announcement(
                    {
                        "venue": venue,
                        "source_url": official_hosts[venue],
                        "contract_id": f"TEST-{venue.upper()}-USDT",
                        "underlying_symbol": "TEST",
                        "quote": "USDT",
                        "announcement_ts": 1_780_000_000,
                        "official_first_trade_ts": 1_780_010_000,
                    }
                )
                self.assertEqual(event.venue, venue)
                self.assertTrue(event.acceptance_eligible)

    def test_candidate_venue_cannot_enter_acceptance_before_promotion(self) -> None:
        event = parse_announcement(
            {
                "venue": "bybit",
                "source_url": "https://www.bybit.com/en/help-center/article/pre-ipo",
                "contract_id": "TESTUSDT",
                "underlying_symbol": "TEST",
                "quote": "USDT",
                "official_first_trade_ts": 1_780_010_000,
            }
        )

        self.assertEqual(event.venue, "bybit")
        self.assertFalse(event.acceptance_eligible)

    def _official_event(self) -> PreIPOEvent:
        return parse_announcement(
            {
                "venue": "okx",
                "source_url": "https://www.okx.com/help/okx-to-convert-spcxusdt-pre-ipo-contract",
                "title": "Convert SPCX pre-IPO perpetual",
                "announcement_ts": 1_780_000_000,
                "contract_id": "SPCX-USDT-SWAP",
                "underlying_symbol": "SPCX",
                "quote": "USDT",
                "official_first_trade_ts": 1_780_010_000,
                "conversion_window_start_ts": 1_780_010_000,
                "conversion_window_end_ts": 1_780_028_000,
                "rebase_ts": 1_780_009_000,
                "lifecycle_status": "ipo_pending",
            }
        )

    def test_official_first_trade_and_conversion_are_separate(self) -> None:
        event = self._official_event()

        self.assertEqual(event.asset_class, "preipo_equity")
        self.assertEqual(event.source_class, "official")
        self.assertTrue(event.acceptance_eligible)
        self.assertEqual(event.official_first_trade_ts, 1_780_010_000)
        self.assertEqual(event.conversion_window_start_ts, 1_780_010_000)
        self.assertEqual(event.conversion_window_end_ts, 1_780_028_000)
        self.assertNotIn("official_spot_listing_ts", event.to_dict())

    def test_acceptance_requires_complete_venue_official_provenance(self) -> None:
        complete = {
            "venue": "okx",
            "contract_id": "SPCX-USDT-SWAP",
            "underlying_symbol": "SPCX",
            "quote": "USDT",
            "announcement_ts": 1_780_000_000,
            "official_first_trade_ts": 1_780_010_000,
            "source_url": "https://www.okx.com/help/spcx-pre-ipo-first-trade",
            "source_class": "official",
        }
        self.assertTrue(PreIPOEvent(**complete).acceptance_eligible)

        for override in (
            {"source_url": "https://example.test/spcx-first-trade"},
            {"announcement_ts": None},
        ):
            with self.subTest(override=override):
                payload = {**complete, **override}
                direct = PreIPOEvent(**payload)
                restored = PreIPOEvent.from_dict(payload)
                self.assertFalse(direct.acceptance_eligible)
                self.assertFalse(restored.acceptance_eligible)
                self.assertTrue(direct.proxy_only)
                self.assertTrue(restored.proxy_only)

    def test_expected_date_without_exact_time_is_proxy_only(self) -> None:
        event = parse_announcement(
            {
                "venue": "gate",
                "source_url": "https://www.gate.com/announcements/article/101203",
                "title": "UNITREE pre-IPO perpetual",
                "announcement_ts": 1_780_000_000,
                "contract_id": "UNITREE_USDT",
                "underlying_symbol": "UNITREE",
                "quote": "USDT",
                "expected_ipo_date": "2026-08-19",
            }
        )

        self.assertEqual(event.source_class, "proxy")
        self.assertTrue(event.proxy_only)
        self.assertFalse(event.acceptance_eligible)
        self.assertIsNone(event.official_first_trade_ts)

    def test_ambiguous_first_trade_aliases_cannot_become_equity_t0(self) -> None:
        for field in (
            "first_trade_ts",
            "ipo_open_ts",
            "ipo_start_ts",
            "first_trading_ts",
        ):
            with self.subTest(field=field):
                event = parse_announcement(
                    {
                        "venue": "kraken",
                        "source_url": (
                            "https://support.kraken.com/articles/"
                            "pre-ipo-perpetual-futures-faq"
                        ),
                        "contract_id": "PF_TESTUSD",
                        "underlying_symbol": "TEST",
                        "quote": "USD",
                        field: 1_780_010_000,
                    }
                )
                self.assertIsNone(event.official_first_trade_ts)
                self.assertFalse(event.acceptance_eligible)

    def test_unofficial_url_is_rejected_for_official_parser(self) -> None:
        with self.assertRaises(PreIPOEventError):
            parse_announcement(
                {
                    "venue": "okx",
                    "source_url": "https://example.test/preipo",
                    "contract_id": "ABC-USDT-SWAP",
                    "underlying_symbol": "ABC",
                    "quote": "USDT",
                    "official_first_trade_ts": 1_780_010_000,
                }
            )

    def test_official_host_over_plain_http_is_rejected(self) -> None:
        with self.assertRaises(PreIPOEventError):
            parse_announcement(
                {
                    "venue": "bitmex",
                    "source_url": "http://www.bitmex.com/app/announcements/pre-ipo",
                    "contract_id": "SPCXUSDT",
                    "underlying_symbol": "SPACEX",
                    "quote": "USDT",
                    "official_first_trade_ts": 1_780_010_000,
                }
            )

    def test_lifecycle_transition_is_explicit_and_terminal_states_are_safe(self) -> None:
        event = self._official_event()
        self.assertEqual(set(LIFECYCLE_STATUSES), {
            "scheduled",
            "preipo_continuous",
            "s1_disclosed",
            "rebase",
            "ipo_pending",
            "ipo_open",
            "converted",
            "postponed",
            "cancelled",
            "delisted",
            "expired",
        })

        opened = transition_event(event, "ipo_open", at_ts=1_780_010_000, reason="first trade observed")
        self.assertEqual(opened.lifecycle_status, "ipo_open")
        self.assertEqual(opened.status_reason, "first trade observed")
        converted = transition_event(opened, "converted", at_ts=1_780_028_000, reason="venue conversion")
        self.assertEqual(converted.actual_conversion_ts, 1_780_028_000)
        with self.assertRaises(PreIPOEventError):
            transition_event(converted, "ipo_open", at_ts=1_780_030_000, reason="illegal reopen")

    def test_rebase_is_value_neutral_and_not_pnl(self) -> None:
        result = rebase_position(
            entry_price=80,
            entry_quantity=0.5,
            estimated_share_count=100,
            actual_share_count=200,
        )

        self.assertEqual(result["share_count_ratio"], 2.0)
        self.assertEqual(result["post_price"], 40.0)
        self.assertEqual(result["post_quantity"], 1.0)
        self.assertEqual(result["pre_notional"], result["post_notional"])
        self.assertTrue(result["value_neutral"])
        self.assertEqual(result["pnl_credit"], 0.0)

    def test_entry_cohorts_have_causal_timestamps_only(self) -> None:
        event = self._official_event()
        candidates = build_entry_candidates(event, first_tradable_ts=1_780_000_000)

        self.assertEqual(
            {candidate["entry_cohort"] for candidate in candidates},
            {"first_tradable", "last_1_4h"},
        )
        last = next(item for item in candidates if item["entry_cohort"] == "last_1_4h")
        self.assertEqual(last["entry_ts"], 1_780_010_000 - 4 * 3600)
        self.assertNotIn("price", last)

    def test_long_and_short_use_fixed_event_relative_exits_without_peak(self) -> None:
        event = self._official_event()
        snapshots = [
            {"ts": 1_780_000_000, "bid": 10.0, "ask": 10.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_000, "bid": 12.0, "ask": 12.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_005, "bid": 15.0, "ask": 15.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_015, "bid": 13.0, "ask": 13.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_060, "bid": 11.0, "ask": 11.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_028_000, "bid": 10.5, "ask": 10.6, "bid_qty": 20.0, "ask_qty": 20.0},
        ]

        long_result = replay_preipo_event(event, snapshots, entry_ts=1_780_000_000, side="long")
        short_result = replay_preipo_event(event, snapshots, entry_ts=1_780_000_000, side="short")

        self.assertEqual(long_result["event_status"], "complete")
        self.assertEqual(short_result["event_status"], "complete")
        self.assertEqual(set(long_result["exits"]), set(EXIT_LABELS))
        self.assertEqual(set(short_result["exits"]), set(EXIT_LABELS))
        self.assertNotIn("peak_price", long_result)
        self.assertNotIn("peak_price", short_result)
        self.assertGreater(long_result["exits"]["ipo_open"]["net_pnl_quote"], 0)
        self.assertLess(short_result["exits"]["ipo_open"]["net_pnl_quote"], 0)

    def test_proxy_event_does_not_produce_primary_exits(self) -> None:
        event = parse_announcement(
            {
                "venue": "gate",
                "source_url": "https://www.gate.com/announcements/article/100758",
                "contract_id": "KIMI_USDT",
                "underlying_symbol": "KIMI",
                "quote": "USDT",
                "expected_ipo_date": "2026-08-19",
            }
        )
        result = replay_preipo_event(
            event,
            [{"ts": 1_780_000_000, "bid": 10.0, "ask": 10.1, "bid_qty": 20, "ask_qty": 20}],
            entry_ts=1_780_000_000,
            side="long",
        )

        self.assertEqual(result["event_status"], "proxy_only")
        self.assertFalse(result["acceptance_eligible"])
        self.assertEqual(result["exits"], {})

    def test_zero_entry_fill_has_no_artificial_profit(self) -> None:
        event = self._official_event()
        result = replay_preipo_event(
            event,
            [
                {"ts": 1_780_000_000, "bid": 10.0, "ask": 10.1, "bid_qty": 20, "ask_qty": 0},
                {"ts": 1_780_010_000, "bid": 20.0, "ask": 20.1, "bid_qty": 20, "ask_qty": 20},
            ],
            entry_ts=1_780_000_000,
            side="long",
        )

        self.assertEqual(result["entry_fill_status"], "unfilled")
        self.assertEqual(result["filled_quantity"], 0.0)
        self.assertEqual(result["net_pnl_quote"], 0.0)
        self.assertFalse(result["acceptance_eligible"])

    def test_replay_result_hash_is_deterministic(self) -> None:
        event = self._official_event()
        snapshots = [
            {"ts": 1_780_000_000, "bid": 10.0, "ask": 10.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_000, "bid": 11.0, "ask": 11.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_005, "bid": 11.0, "ask": 11.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_015, "bid": 11.0, "ask": 11.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_010_060, "bid": 11.0, "ask": 11.1, "bid_qty": 20.0, "ask_qty": 20.0},
            {"ts": 1_780_028_000, "bid": 11.0, "ask": 11.1, "bid_qty": 20.0, "ask_qty": 20.0},
        ]

        first = replay_preipo_event(event, snapshots, entry_ts=1_780_000_000, side="long")
        second = replay_preipo_event(event, snapshots, entry_ts=1_780_000_000, side="long")
        self.assertEqual(first["result_hash"], second["result_hash"])


if __name__ == "__main__":
    unittest.main()
