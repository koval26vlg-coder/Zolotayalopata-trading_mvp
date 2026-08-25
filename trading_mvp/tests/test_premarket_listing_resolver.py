from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from premarket_listing_resolver import (  # noqa: E402
    OfficialListingAnnouncementError,
    fetch_public_announcement,
    materialize_premarket_events,
    parse_official_listing_announcement,
    resolve_contract_listing,
)


class PreMarketListingResolverTests(unittest.TestCase):
    def test_bounded_public_fetch_accepts_only_same_host_official_response(self) -> None:
        class Response:
            status_code = 200
            url = "https://www.gate.com/announcements/abc"
            content = (
                b"<h1>ABC listing</h1>"
                b"Spot Trading Opens: August 18, 2026, at 12:00 UTC."
            )

        class Session:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []

            def get(self, url: str, **kwargs: object) -> Response:
                self.calls.append((url, kwargs))
                return Response()

        session = Session()
        announcement = fetch_public_announcement(
            "gate",
            "https://www.gate.com/announcements/abc",
            session=session,
            timeout_sec=3.0,
            max_bytes=1024,
            metadata={"spot_symbol": "ABC_USDT", "pre_market_contract_id": "ABC_USDT"},
        )

        self.assertEqual(announcement.official_spot_listing_ts, 1787054400.0)
        self.assertEqual(session.calls[0][1]["allow_redirects"], False)
        self.assertEqual(session.calls[0][1]["timeout"], 3.0)

    def test_fetched_announcement_requires_timestamp_in_saved_response_evidence(self) -> None:
        class Response:
            status_code = 200
            url = "https://www.gate.com/announcements/abc"
            content = b"<h1>ABC listing</h1><p>Trading time will be announced later.</p>"

        class Session:
            def get(self, url: str, **kwargs: object) -> Response:
                return Response()

        with self.assertRaisesRegex(
            OfficialListingAnnouncementError,
            "official_spot_listing_timestamp_missing",
        ):
            fetch_public_announcement(
                "gate",
                "https://www.gate.com/announcements/abc",
                session=Session(),
                metadata={
                    "spot_symbol": "ABC_USDT",
                    "pre_market_contract_id": "ABC_USDT",
                    # Caller metadata is not response evidence and must not be
                    # allowed to manufacture an official t0.
                    "official_spot_listing_ts": 1_900_000_000,
                    "title": "Spot opens 2030-03-17 17:46 UTC",
                },
            )

    def test_gate_exact_utc_listing_phrase_keeps_publish_and_t0_distinct(self) -> None:
        announcement = parse_official_listing_announcement(
            "gate",
            {
                "url": "https://www.gate.com/announcements/robo-spot",
                "title": "Gate Will List ROBO (ROBO) in Spot Trading",
                "published_at": "2026-02-26T15:00:00Z",
                "body": (
                    "ROBO_USDT pre-market perpetual is available. "
                    "Spot Trading Opens: February 27, 2026, at 10:00 UTC."
                ),
                "pre_market_contract_id": "ROBO_USDT",
                "spot_symbol": "ROBO_USDT",
            },
        )

        self.assertEqual(announcement.source_class, "official")
        self.assertEqual(announcement.official_spot_listing_ts, 1772186400.0)
        self.assertEqual(announcement.announcement_ts, 1772118000.0)
        self.assertEqual(announcement.spot_symbol, "ROBO_USDT")
        self.assertIn("ROBO_USDT", announcement.contract_aliases)
        self.assertEqual(announcement.confidence, "high")

    def test_bybit_structured_listing_field_is_not_announcement_publish_time(self) -> None:
        announcement = parse_official_listing_announcement(
            "bybit",
            {
                "source_url": "https://www.bybit.com/en/announcement-info/abc",
                "publishedAt": "2026-08-18T08:00:00Z",
                "spotTradingStartTime": "2026-08-18T12:30:00Z",
                "preMarketContractId": "ABCUSDT",
                "spotSymbol": "ABCUSDT",
            },
        )

        self.assertEqual(announcement.announcement_ts, 1787040000.0)
        self.assertEqual(announcement.official_spot_listing_ts, 1787056200.0)
        self.assertNotEqual(announcement.announcement_ts, announcement.official_spot_listing_ts)
        self.assertEqual(announcement.venue, "bybit")

    def test_okx_text_listing_time_is_parsed_from_official_phrase(self) -> None:
        announcement = parse_official_listing_announcement(
            "okx",
            {
                "source_url": "https://www.okx.com/help/abc-listing",
                "published_at": "2026-08-19T07:00:00Z",
                "title": "OKX to list ABC spot trading",
                "body": "Spot trading for ABC-USDT will start at 2026-08-20 09:00 UTC.",
                "spot_symbol": "ABC-USDT",
                "pre_market_contract_id": "ABC-USDT-SWAP",
            },
        )

        self.assertEqual(announcement.official_spot_listing_ts, 1787216400.0)
        self.assertEqual(announcement.spot_symbol, "ABC-USDT")
        self.assertEqual(announcement.contract_aliases, ("ABC-USDT-SWAP",))

    def test_missing_or_placeholder_timestamp_cannot_become_official(self) -> None:
        for body in (
            "Spot trading opens soon.",
            "Spot trading opens at ... UTC.",
            "Spot trading opens at <LISTING_TIME> UTC.",
        ):
            with self.subTest(body=body):
                with self.assertRaises(OfficialListingAnnouncementError):
                    parse_official_listing_announcement(
                        "gate",
                        {
                            "url": "https://www.gate.com/announcements/abc",
                            "body": body,
                            "spot_symbol": "ABC_USDT",
                        },
                    )

    def test_resolver_separates_proxy_detection_from_official_t0(self) -> None:
        resolved = resolve_contract_listing(
            {
                "venue": "bybit",
                "contract_id": "ABCUSDT",
                "spot_symbol": "ABCUSDT",
                "quote": "USDT",
            },
            [],
            detection_ts=1700000000.0,
        )

        self.assertEqual(resolved["listing_resolution_status"], "proxy_only")
        self.assertEqual(resolved["listing_source_class"], "proxy")
        self.assertIsNone(resolved["official_spot_listing_ts"])
        self.assertEqual(resolved["proxy_spot_listing_ts"], 1700000000.0)
        self.assertFalse(resolved["acceptance_eligible"])

    def test_resolver_rejects_ambiguous_official_matches(self) -> None:
        announcements = [
            parse_official_listing_announcement(
                "gate",
                {
                    "url": f"https://www.gate.com/announcements/abc-{suffix}",
                    "published_at": "2026-08-18T08:00:00Z",
                    "spot_listing_ts": ts,
                    "spot_symbol": "ABC_USDT",
                    "pre_market_contract_id": "ABC_USDT",
                },
            )
            for suffix, ts in (("one", "2026-08-18T12:00:00Z"), ("two", "2026-08-18T12:05:00Z"))
        ]

        resolved = resolve_contract_listing(
            {"venue": "gate", "contract_id": "ABC_USDT", "spot_symbol": "ABC_USDT", "quote": "USDT"},
            announcements,
        )

        self.assertEqual(resolved["listing_resolution_status"], "ambiguous")
        self.assertIsNone(resolved["official_spot_listing_ts"])
        self.assertFalse(resolved["acceptance_eligible"])

    def test_resolver_does_not_match_a_different_spot_pair(self) -> None:
        announcement = parse_official_listing_announcement(
            "okx",
            {
                "source_url": "https://www.okx.com/help/xyz-listing",
                "spot_listing_ts": "2026-08-18T12:00:00Z",
                "spot_symbol": "XYZ-USDT",
                "pre_market_contract_id": "XYZ-USDT-SWAP",
            },
        )

        resolved = resolve_contract_listing(
            {"venue": "okx", "contract_id": "ABC-USDT-SWAP", "spot_symbol": "ABC-USDT", "quote": "USDT"},
            [announcement],
        )

        self.assertEqual(resolved["listing_resolution_status"], "unresolved")
        self.assertIsNone(resolved["official_spot_listing_ts"])

    def test_materializer_enriches_events_atomically_without_mutating_raw_input(self) -> None:
        raw_rows = [
            {
                "venue": "gate",
                "premarket_contract_id": "ABC_USDT",
                "spot_symbol": "ABC_USDT",
                "exchange_ts": 1787054400.0,
                "event_kind": "bbo",
                "bid_price": 1.0,
                "ask_price": 1.1,
            },
            {
                "venue": "gate",
                "premarket_contract_id": "UNMATCHED_USDT",
                "spot_symbol": "UNMATCHED_USDT",
                "exchange_ts": 1787054401.0,
                "event_kind": "bbo",
            },
        ]
        announcement = parse_official_listing_announcement(
            "gate",
            {
                "url": "https://www.gate.com/announcements/abc",
                "published_at": "2026-08-18T08:00:00Z",
                "spot_listing_ts": "2026-08-18T12:00:00Z",
                "spot_symbol": "ABC_USDT",
                "pre_market_contract_id": "ABC_USDT",
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_path = root / "raw.jsonl"
            output_path = root / "materialized.jsonl"
            raw_path.write_text("".join(json.dumps(row) + "\n" for row in raw_rows), encoding="utf-8")
            before = raw_path.read_bytes()

            result = materialize_premarket_events(raw_path, [announcement], output_path)

            self.assertEqual(raw_path.read_bytes(), before)
            self.assertEqual(result["rows_written"], 2)
            self.assertEqual(result["matched_official"], 1)
            self.assertEqual(result["unresolved"], 1)
            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["official_spot_listing_ts"], 1787054400.0)
            self.assertEqual(rows[0]["listing_source_class"], "official")
            self.assertEqual(rows[0]["listing_resolution_status"], "official")
            self.assertIsNone(rows[1]["official_spot_listing_ts"])
            self.assertEqual(rows[1]["listing_resolution_status"], "unresolved")

            second_output = root / "materialized-second.jsonl"
            second = materialize_premarket_events(raw_path, [announcement], second_output)
            self.assertEqual(result["output_sha256"], second["output_sha256"])
            self.assertEqual(result["result_hash"], second["result_hash"])


if __name__ == "__main__":
    unittest.main()
