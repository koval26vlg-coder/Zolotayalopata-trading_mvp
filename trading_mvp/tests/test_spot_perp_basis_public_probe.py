from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spot_perp_basis_public_probe import (  # noqa: E402
    ACCEPTED_DECISION,
    PLAN_DECISION,
    REJECTED_DECISION,
    _probe_gateio,
    _probe_mexc,
    build_plan_report,
    candidate_pairs_from_preflight,
    extract_book_metrics,
    paired_base_ok,
    summarize_probe_rows,
)


def fixture_preflight() -> dict[str, object]:
    return {
        "decision": "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE",
        "daily_history": {
            "candidate_non_binance_bases": ["HYPE", "AERO"],
            "candidate_symbols_by_base": {
                "HYPE": {"mexc": "HYPE_USDT", "gateio": "HYPE_USDT"},
                "AERO": {"mexc": "AERO_USDT", "gateio": "AERO_USDT"},
            },
        },
    }


def valid_probe_venue() -> dict[str, object]:
    return {
        "ok": True,
        "spot": {"mid": 100, "spread_bps": 1, "top_depth_notional": 1000},
        "perp": {
            "mid_or_mark": 101,
            "funding_rate": 0.0001,
            "next_funding_ts": 123,
            "book": {"spread_bps": 1, "top_depth_notional": 1000},
        },
    }


def fake_snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        mark_price=100.1,
        index_price=100.0,
        perp_bid=100.0,
        perp_ask=100.2,
        funding_rate=0.0001,
        next_funding_ts=1234567890,
        funding_interval_sec=28800,
    )


class SpotPerpBasisPublicProbeTests(unittest.TestCase):
    def test_candidate_pairs_map_spot_and_perp_symbols(self) -> None:
        pairs = candidate_pairs_from_preflight(fixture_preflight(), max_bases=1)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["base"], "HYPE")
        self.assertEqual(pairs[0]["mexc"]["spot_symbol"], "HYPEUSDT")
        self.assertEqual(pairs[0]["mexc"]["perp_symbol"], "HYPE_USDT")
        self.assertEqual(pairs[0]["gateio"]["spot_symbol"], "HYPE_USDT")
        self.assertEqual(pairs[0]["gateio"]["perp_symbol"], "HYPE_USDT")

    def test_plan_report_never_starts_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preflight_path = Path(tmp) / "preflight.json"
            preflight_path.write_text(json.dumps(fixture_preflight()), encoding="utf-8")
            report = build_plan_report(
                preflight_path=preflight_path,
                output_path=Path(tmp) / "plan.json",
                max_bases=2,
                min_success_bases=1,
            )

        self.assertEqual(report["decision"], PLAN_DECISION)
        self.assertFalse(report["would_start"])
        self.assertFalse(report["live_orders"])
        self.assertFalse(report["api_keys"])
        self.assertFalse(report["collect_allowed_now"])
        self.assertEqual(report["candidate_count"], 2)

    def test_extract_book_metrics_accepts_list_books(self) -> None:
        metrics = extract_book_metrics({"bids": [["99", "2"]], "asks": [["101", "3"]]})

        self.assertEqual(metrics.bid, 99.0)
        self.assertEqual(metrics.ask, 101.0)
        self.assertEqual(metrics.mid, 100.0)
        self.assertAlmostEqual(metrics.spread_bps, 200.0)
        self.assertEqual(metrics.top_depth_notional, 501.0)

    def test_extract_book_metrics_accepts_gate_price_size_objects(self) -> None:
        metrics = extract_book_metrics(
            {
                "bids": [{"p": "99", "s": "2"}],
                "asks": [{"p": "101", "s": "3"}],
            }
        )

        self.assertEqual(metrics.bid, 99.0)
        self.assertEqual(metrics.ask, 101.0)
        self.assertEqual(metrics.top_depth_notional, 501.0)

    def test_extract_book_metrics_rejects_crossed_book(self) -> None:
        with self.assertRaises(ValueError):
            extract_book_metrics({"bids": [["101", "2"]], "asks": [["99", "3"]]})

    def test_paired_base_ok_requires_all_fields_on_both_exchanges(self) -> None:
        venue = valid_probe_venue()
        self.assertTrue(paired_base_ok({"venues": {"mexc": venue, "gateio": venue}}))
        missing = dict(venue)
        missing["perp"] = dict(venue["perp"])
        missing["perp"]["next_funding_ts"] = None
        self.assertFalse(paired_base_ok({"venues": {"mexc": venue, "gateio": missing}}))

    def test_paired_base_ok_rejects_unusable_ranges(self) -> None:
        venue = valid_probe_venue()

        wide_spread = dict(venue)
        wide_spread["spot"] = dict(venue["spot"])
        wide_spread["spot"]["spread_bps"] = 150
        self.assertFalse(paired_base_ok({"venues": {"mexc": venue, "gateio": wide_spread}}))

        impossible_funding = dict(venue)
        impossible_funding["perp"] = dict(venue["perp"])
        impossible_funding["perp"]["funding_rate"] = 0.5
        self.assertFalse(paired_base_ok({"venues": {"mexc": venue, "gateio": impossible_funding}}))

        no_depth = dict(venue)
        no_depth["spot"] = dict(venue["spot"])
        no_depth["spot"]["top_depth_notional"] = 0
        self.assertFalse(paired_base_ok({"venues": {"mexc": venue, "gateio": no_depth}}))

    def test_probe_mexc_uses_public_books_and_funding_snapshot(self) -> None:
        candidate = candidate_pairs_from_preflight(fixture_preflight(), max_bases=1)[0]

        def fake_get_json(_session: object, url: str, _params: dict[str, object], _timeout_sec: int) -> dict[str, object]:
            if "api.mexc.com" in url:
                return {"bids": [["99", "10"]], "asks": [["101", "10"]]}
            return {"data": {"bids": [["100", "5"]], "asks": [["100.2", "6"]]}}

        client = Mock()
        client.fetch_snapshot.return_value = fake_snapshot()
        with patch("spot_perp_basis_public_probe._get_json", side_effect=fake_get_json), patch(
            "spot_perp_basis_public_probe.MexcFundingClient",
            return_value=client,
        ):
            row = _probe_mexc(Mock(), candidate, depth_limit=5, timeout_sec=10)

        self.assertTrue(row["ok"])
        self.assertEqual(row["spot_symbol"], "HYPEUSDT")
        self.assertEqual(row["perp_symbol"], "HYPE_USDT")
        self.assertEqual(row["perp"]["funding_rate"], 0.0001)
        client.fetch_snapshot.assert_called_once_with("HYPE_USDT")

    def test_probe_gateio_uses_public_books_and_funding_snapshot(self) -> None:
        candidate = candidate_pairs_from_preflight(fixture_preflight(), max_bases=1)[0]

        def fake_get_json(_session: object, url: str, _params: dict[str, object], _timeout_sec: int) -> dict[str, object]:
            if "/spot/" in url:
                return {"bids": [["99", "10"]], "asks": [["101", "10"]]}
            return {"bids": [["100", "5"]], "asks": [["100.2", "6"]]}

        client = Mock()
        client.fetch_snapshot.return_value = fake_snapshot()
        with patch("spot_perp_basis_public_probe._get_json", side_effect=fake_get_json), patch(
            "spot_perp_basis_public_probe.GateFundingClient",
            return_value=client,
        ):
            row = _probe_gateio(Mock(), candidate, depth_limit=5, timeout_sec=10)

        self.assertTrue(row["ok"])
        self.assertEqual(row["spot_symbol"], "HYPE_USDT")
        self.assertEqual(row["perp_symbol"], "HYPE_USDT")
        self.assertEqual(row["perp"]["funding_rate"], 0.0001)
        client.fetch_snapshot.assert_called_once_with("HYPE_USDT")

    def test_summary_accepts_only_when_min_success_passes(self) -> None:
        accepted = summarize_probe_rows([{"base": "HYPE", "paired_ok": True}], min_success_bases=1)
        rejected = summarize_probe_rows([{"base": "HYPE", "paired_ok": False}], min_success_bases=1)

        self.assertEqual(accepted["decision"], ACCEPTED_DECISION)
        self.assertEqual(rejected["decision"], REJECTED_DECISION)


if __name__ == "__main__":
    unittest.main()
