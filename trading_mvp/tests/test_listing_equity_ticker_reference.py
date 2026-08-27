"""A reference that decides classifications has to be able to vouch for itself.

The wrapper heuristic reads a symbol's remainder against this snapshot, and a proposal it
makes removes an instrument from the crypto acceptance universe. So the snapshot is bound
by hash, refuses a source it does not recognise, and refuses to shrink quietly - a
reference that lost its rows would stop recognising wrappers, and a heuristic recognising
nothing looks exactly like one that found nothing.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import listing_equity_ticker_reference as reference  # noqa: E402
import listing_equity_ticker_reference_fetch as fetch  # noqa: E402

NASDAQ = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
    "ULTA|Ulta Beauty, Inc. Common Stock|Q|N|N|100|N|N\n"
    "AAAU|Goldman Sachs Physical Gold ETF Shares|G|N|N|100|Y|N\n"
    "ZTEST|Nasdaq Test Issue|Q|Y|N|100|N|N\n"
    "File Creation Time: 0827202611:01|||||||\n"
)
OTHER = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
    "AA|Alcoa Corporation Common Stock|N|AA|N|100|N|AA\n"
    "PRT|PermRock Royalty Trust Units of Beneficial Interest|N|PRT|N|100|N|PRT\n"
    "File Creation Time: 0827202611:01|||||||\n"
)


def snapshot(rows: list[dict], **overrides) -> dict:
    payload = {
        "schema": "trading_mvp_equity_ticker_reference_v1",
        "source_url": reference.SOURCE_URLS[0],
        "source_urls": list(reference.SOURCE_URLS),
        "source_authority": reference.SOURCE_AUTHORITY,
        "observed_at_utc": "2026-08-27T00:00:00Z",
        "rows": rows,
    }
    payload["payload_sha256"] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload.update(overrides)
    return payload


def bulk(count: int, *, common: bool = True) -> list[dict]:
    name = "Example Corp Common Stock" if common else "Example Bond ETF"
    return [
        {"ticker": f"T{index:04d}", "name": name, "etf": "N" if common else "Y"}
        for index in range(count)
    ]


class ParseTests(unittest.TestCase):
    def test_a_snapshot_from_an_unrecognised_source_is_refused(self) -> None:
        payload = snapshot(bulk(1200), source_urls=["https://example.invalid/tickers.txt"])
        with self.assertRaisesRegex(reference.EquityReferenceError, "exchange symbol directory"):
            reference.parse_reference(payload)

    def test_a_snapshot_that_shrank_is_refused_rather_than_quietly_narrowing(self) -> None:
        with self.assertRaisesRegex(reference.EquityReferenceError, "usable tickers"):
            reference.parse_reference(snapshot(bulk(10)))

    def test_a_snapshot_of_nothing_but_funds_is_refused(self) -> None:
        # It would parse, hold 1200 tickers, and answer "is this a company's share" with
        # a set containing no company shares at all.
        with self.assertRaisesRegex(reference.EquityReferenceError, "ordinary shares"):
            reference.parse_reference(snapshot(bulk(1200, common=False)))

    def test_the_narrow_view_keeps_shares_and_drops_the_rest(self) -> None:
        rows = bulk(1200) + [
            {"ticker": "ULTA", "name": "Ulta Beauty, Inc. Common Stock", "etf": "N"},
            {"ticker": "AAAU", "name": "Goldman Sachs Physical Gold ETF Shares", "etf": "Y"},
            {"ticker": "PRT", "name": "PermRock Royalty Trust Units", "etf": "N"},
        ]
        parsed = reference.parse_reference(snapshot(rows))
        self.assertIn("ULTA", parsed.common_stock)
        self.assertIn("AAAU", parsed.tickers)
        self.assertNotIn("AAAU", parsed.common_stock)
        self.assertNotIn("PRT", parsed.common_stock)

    def test_rows_that_do_not_match_their_hash_are_refused_on_load(self) -> None:
        payload = snapshot(bulk(1200))
        payload["rows"][0]["ticker"] = "TAMPERED"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            reference.load_reference.cache_clear()
            with self.assertRaisesRegex(reference.EquityReferenceError, "recorded hash"):
                reference.load_reference(str(path))

    def test_a_missing_reference_is_reported_rather_than_raised_at_the_caller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference.load_reference.cache_clear()
            self.assertFalse(reference.available(str(Path(directory) / "absent.json")))


class FetchTests(unittest.TestCase):
    def test_a_request_outside_the_directory_is_refused_before_it_is_made(self) -> None:
        with self.assertRaisesRegex(fetch.TickerFetchError, "outside the symbol directory"):
            fetch.http_get("https://example.invalid/nasdaqlisted.txt")
        with self.assertRaisesRegex(fetch.TickerFetchError, "outside the symbol directory"):
            fetch.http_get("http://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt")

    def test_the_trailer_and_test_issues_are_dropped(self) -> None:
        rows = fetch.rows_from_directory(NASDAQ.encode("utf-8"), source_url=reference.SOURCE_URLS[0])
        self.assertEqual({"ULTA", "AAAU"}, {row["ticker"] for row in rows})

    def test_both_files_are_read_and_the_fund_flag_is_carried_through(self) -> None:
        rows = fetch.rows_from_directory(
            NASDAQ.encode("utf-8"), source_url=reference.SOURCE_URLS[0]
        ) + fetch.rows_from_directory(OTHER.encode("utf-8"), source_url=reference.SOURCE_URLS[1])
        by_ticker = {row["ticker"]: row for row in rows}
        self.assertEqual({"AA", "AAAU", "PRT", "ULTA"}, set(by_ticker))
        self.assertEqual("Y", by_ticker["AAAU"]["etf"])
        self.assertEqual("N", by_ticker["AA"]["etf"])

    def test_a_snapshot_the_reader_would_refuse_is_never_written(self) -> None:
        # build_snapshot reads its own output back through parse_reference, so a fetch
        # that returned four rows fails here rather than leaving an authoritative-looking
        # file that every later classification would silently narrow against.
        with self.assertRaises(reference.EquityReferenceError):
            fetch.build_snapshot(
                {
                    reference.SOURCE_URLS[0]: NASDAQ.encode("utf-8"),
                    reference.SOURCE_URLS[1]: OTHER.encode("utf-8"),
                },
                observed_at_utc="2026-08-27T00:00:00Z",
            )

    def test_an_empty_directory_response_is_an_error_not_an_empty_reference(self) -> None:
        with self.assertRaisesRegex(fetch.TickerFetchError, "carried no rows"):
            fetch.rows_from_directory(b"Symbol|Security Name\n", source_url=reference.SOURCE_URLS[0])


if __name__ == "__main__":
    unittest.main()
