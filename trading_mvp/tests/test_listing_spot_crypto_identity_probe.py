from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import listing_spot_crypto_identity_probe as probe  # noqa: E402
from listing_spot_crypto_identity_plan import CryptoIdentityPlanError  # noqa: E402
from listing_spot_crypto_identity_probe import ProbeError, evidence_from_response  # noqa: E402

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


def venue_payload(base: str, chains: list[dict]) -> bytes:
    return json.dumps(
        {
            "code": "00000",
            "msg": "success",
            "requestTime": 1,
            "data": [{"coinId": "1", "coin": base, "transfer": "true", "chains": chains}],
        }
    ).encode("utf-8")


MOVABLE = {
    "chain": "Ethereum",
    "contractAddress": "0xabc0000000000000000000000000000000000001",
    "rechargeable": "true",
    "withdrawable": "true",
}
DEPOSIT_ONLY = {"chain": "Ethereum", "rechargeable": "true", "withdrawable": "false"}


class ProbeReadingTests(unittest.TestCase):
    def test_string_flags_are_read_as_the_venue_writes_them(self) -> None:
        evidence = evidence_from_response(
            venue_payload("SWARM", [MOVABLE]),
            base="SWARM", exchange="bitget",
            source_url="https://api.bitget.com/api/v2/spot/public/coins?coin=SWARM",
            observed_at_utc="2026-08-26T11:00:00Z",
        )
        self.assertEqual(1, len(evidence.chains))
        chain = evidence.chains[0]
        self.assertTrue(chain.deposit_enabled)
        self.assertTrue(chain.withdraw_enabled)
        self.assertTrue(chain.is_movable)
        self.assertEqual("Ethereum", chain.network)

    def test_a_missing_or_unexpected_flag_reads_as_disabled(self) -> None:
        for chain_row in (
            {"chain": "Ethereum"},
            {"chain": "Ethereum", "rechargeable": "yes", "withdrawable": "1"},
            {"chain": "Ethereum", "rechargeable": None, "withdrawable": None},
        ):
            with self.subTest(chain=chain_row):
                evidence = evidence_from_response(
                    venue_payload("SWARM", [chain_row]),
                    base="SWARM", exchange="bitget",
                    source_url="https://api.bitget.com/x", observed_at_utc="2026-08-26T11:00:00Z",
                )
                self.assertFalse(evidence.chains[0].is_movable)

    def test_an_empty_contract_address_becomes_absent_rather_than_empty(self) -> None:
        evidence = evidence_from_response(
            venue_payload("BTC", [{"chain": "Bitcoin", "contractAddress": "",
                                   "rechargeable": "true", "withdrawable": "true"}]),
            base="BTC", exchange="bitget",
            source_url="https://api.bitget.com/x", observed_at_utc="2026-08-26T11:00:00Z",
        )
        self.assertIsNone(evidence.chains[0].contract_address)

    def test_a_venue_error_code_is_a_refusal_not_an_empty_answer(self) -> None:
        raw = json.dumps({"code": "40034", "msg": "param error", "data": []}).encode()
        with self.assertRaisesRegex(ProbeError, "venue refused"):
            evidence_from_response(raw, base="SWARM", exchange="bitget",
                                   source_url="https://api.bitget.com/x",
                                   observed_at_utc="2026-08-26T11:00:00Z")

    def test_two_records_for_one_ticker_are_ambiguous(self) -> None:
        raw = json.dumps({
            "code": "00000", "msg": "success",
            "data": [{"coin": "SWARM", "chains": [MOVABLE]}, {"coin": "SWARM", "chains": []}],
        }).encode()
        with self.assertRaisesRegex(ProbeError, "2 records"):
            evidence_from_response(raw, base="SWARM", exchange="bitget",
                                   source_url="https://api.bitget.com/x",
                                   observed_at_utc="2026-08-26T11:00:00Z")

    def test_a_ticker_the_venue_does_not_list_yields_no_chains(self) -> None:
        raw = json.dumps({"code": "00000", "msg": "success", "data": []}).encode()
        evidence = evidence_from_response(raw, base="SWARM", exchange="bitget",
                                          source_url="https://api.bitget.com/x",
                                          observed_at_utc="2026-08-26T11:00:00Z")
        self.assertEqual((), evidence.chains)

    def test_unreadable_bytes_are_refused(self) -> None:
        for raw in (b"not json", b"[]", b'{"code":"00000","data":"nope"}'):
            with self.subTest(raw=raw[:12]):
                with self.assertRaises(ProbeError):
                    evidence_from_response(raw, base="SWARM", exchange="bitget",
                                           source_url="https://api.bitget.com/x",
                                           observed_at_utc="2026-08-26T11:00:00Z")


class ProbeRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.slept: list[float] = []

    def fetcher(self, mapping: dict[str, bytes], fail: set[str] | None = None):
        def fetch(url: str) -> bytes:
            self.calls.append(url)
            base = url.rsplit("=", 1)[-1]
            if fail and base in fail:
                raise ProbeError("connection refused")
            return mapping.get(base, json.dumps({"code": "00000", "data": []}).encode())
        return fetch

    def run_with(self, mapping: dict[str, bytes], fail: set[str] | None = None) -> dict:
        return probe.run_probe(
            fetch=self.fetcher(mapping, fail),
            now=lambda: NOW,
            sleep=self.slept.append,
        )

    def test_one_request_per_declared_base_spaced_by_the_declared_interval(self) -> None:
        result = self.run_with({})
        plan = json.loads(
            (probe.REPO_ROOT / probe.PLAN_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(len(plan["probe"]["bases"]), len(self.calls))
        self.assertEqual(len(plan["probe"]["bases"]) - 1, len(self.slept))
        self.assertTrue(all(gap == plan["probe"]["min_interval_between_requests_sec"]
                            for gap in self.slept))
        self.assertEqual(plan["plan_hash"], result["plan_hash"])
        for url in self.calls:
            self.assertTrue(url.startswith(plan["probe"]["endpoint"]))

    def test_a_movable_asset_produces_a_proposal_a_static_one_does_not(self) -> None:
        plan = json.loads(
            (probe.REPO_ROOT / probe.PLAN_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        movable, static = plan["probe"]["bases"][0], plan["probe"]["bases"][1]
        result = self.run_with({
            movable: venue_payload(movable, [MOVABLE]),
            static: venue_payload(static, [DEPOSIT_ONLY]),
        })
        by_base = {row["base"]: row for row in result["observations"]}
        self.assertEqual("PROPOSED", by_base[movable]["status"])
        self.assertEqual("NOT_ESTABLISHED", by_base[static]["status"])
        self.assertEqual(1, len(result["proposals"]))
        self.assertEqual(movable, result["proposals"][0]["base"])
        self.assertTrue(result["proposals"][0]["requires_human_review"])

    def test_a_failed_request_is_recorded_and_does_not_stop_the_rest(self) -> None:
        plan = json.loads(
            (probe.REPO_ROOT / probe.PLAN_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        first = plan["probe"]["bases"][0]
        result = self.run_with({}, fail={first})
        by_base = {row["base"]: row for row in result["observations"]}
        self.assertEqual("REQUEST_FAILED", by_base[first]["status"])
        self.assertNotIn("response_sha256", by_base[first])
        self.assertEqual(len(plan["probe"]["bases"]), len(result["observations"]))
        self.assertEqual(len(plan["probe"]["bases"]) - 1, result["requests_made"])

    def test_every_answered_base_records_the_bytes_its_verdict_rests_on(self) -> None:
        plan = json.loads(
            (probe.REPO_ROOT / probe.PLAN_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        base = plan["probe"]["bases"][0]
        raw = venue_payload(base, [MOVABLE])
        result = self.run_with({base: raw})
        import hashlib

        row = next(item for item in result["observations"] if item["base"] == base)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), row["response_sha256"])
        self.assertEqual(len(raw), row["response_bytes"])

    def test_the_result_states_that_it_decided_nothing(self) -> None:
        result = self.run_with({})
        self.assertFalse(result["registry_edited"])
        self.assertTrue(result["human_review_required"])
        self.assertEqual("NONE_IDENTITY_EVIDENCE_ONLY", result["acceptance_decision"])

    def test_the_registry_is_untouched_by_a_run(self) -> None:
        from listing_spot_asset_class import DECLARED_CRYPTO_TOKEN_BASES

        before = dict(DECLARED_CRYPTO_TOKEN_BASES)
        plan = json.loads(
            (probe.REPO_ROOT / probe.PLAN_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.run_with({base: venue_payload(base, [MOVABLE]) for base in plan["probe"]["bases"]})
        self.assertEqual(before, dict(DECLARED_CRYPTO_TOKEN_BASES))

    def test_an_invalid_plan_stops_the_probe_before_any_request(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "plan.json"
            plan = json.loads(
                (probe.REPO_ROOT / probe.PLAN_RELATIVE_PATH).read_text(encoding="utf-8")
            )
            plan["live_orders"] = True
            broken.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaises(CryptoIdentityPlanError):
                probe.run_probe(plan_path=broken, fetch=self.fetcher({}), now=lambda: NOW,
                                sleep=self.slept.append)
        self.assertEqual([], self.calls)

    def test_http_get_refuses_a_non_https_url_without_opening_anything(self) -> None:
        with self.assertRaisesRegex(ProbeError, "non-https"):
            probe.http_get("http://api.bitget.com/api/v2/spot/public/coins", timeout_sec=5)


if __name__ == "__main__":
    unittest.main()
