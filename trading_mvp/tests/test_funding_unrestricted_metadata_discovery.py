from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from funding_unrestricted_metadata_discovery import (  # noqa: E402
    GATEIO_ENDPOINT,
    MEXC_ENDPOINT,
    BoundedMetadataClient,
    DiscoveryError,
    build_provisional_ticker_candidates,
    project_gateio_active_contracts,
    project_mexc_active_contracts,
    validate_execution_artifacts,
    verify_global_writer_claim,
    write_immutable_discovery,
)


PROPOSAL_PATH = (
    ROOT
    / "docs"
    / "plans"
    / "drafts"
    / "funding-unrestricted-active-perp-metadata-discovery-proposal-20260810-v1.json"
)
RECEIPT_PATH = (
    ROOT
    / "docs"
    / "agent-log"
    / "approvals"
    / "2026-08-10-funding-unrestricted-metadata-discovery-v1-approval.json"
)
RUNTIME_MANIFEST_PATH = (
    ROOT
    / "docs"
    / "plans"
    / "funding-unrestricted-metadata-discovery-runtime-manifest-20260810-v1.json"
)
LAUNCHER_PATH = (
    ROOT / "tools" / "start_funding_unrestricted_metadata_discovery_visible.ps1"
)


class FakeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return io.BytesIO(self._raw).read(size)


class FakeOpener:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class FundingUnrestrictedMetadataDiscoveryTests(unittest.TestCase):
    def test_mexc_projection_keeps_every_active_usdt_contract_and_only_allowlist(self) -> None:
        payload = {
            "success": True,
            "code": 0,
            "data": [
                {
                    "symbol": "BTC_USDT",
                    "baseCoin": "BTC",
                    "baseCoinName": "Bitcoin",
                    "quoteCoin": "USDT",
                    "quoteCoinName": "Tether",
                    "settleCoin": "USDT",
                    "state": 0,
                    "apiAllowed": True,
                    "fairPrice": "123",
                    "fundingRate": "0.01",
                },
                {
                    "symbol": "1000CAT_USDT",
                    "baseCoin": "1000CAT",
                    "baseCoinName": "Any category is allowed",
                    "quoteCoin": "USDT",
                    "quoteCoinName": "Tether",
                    "settleCoin": "USDT",
                    "state": 0,
                    "apiAllowed": True,
                    "lastPrice": "9",
                },
                {
                    "symbol": "OLD_USDT",
                    "baseCoin": "OLD",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "state": 1,
                    "apiAllowed": True,
                },
                {
                    "symbol": "NOAPI_USDT",
                    "baseCoin": "NOAPI",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "state": 0,
                    "apiAllowed": False,
                },
            ],
        }

        records = project_mexc_active_contracts(payload)

        self.assertEqual([row["symbol"] for row in records], ["1000CAT_USDT", "BTC_USDT"])
        self.assertEqual(
            set(records[0]),
            {
                "symbol",
                "baseCoin",
                "baseCoinName",
                "quoteCoin",
                "quoteCoinName",
                "settleCoin",
                "state",
                "apiAllowed",
            },
        )
        self.assertNotIn("fundingRate", json.dumps(records))
        self.assertNotIn("lastPrice", json.dumps(records))

    def test_gateio_projection_keeps_every_trading_contract_and_only_allowlist(self) -> None:
        payload = [
            {
                "name": "BTC_USDT",
                "status": "trading",
                "type": "direct",
                "in_delisting": False,
                "mark_price": "123",
                "funding_rate": "0.01",
            },
            {
                "name": "1000CAT_USDT",
                "status": "trading",
                "type": "direct",
                "in_delisting": False,
                "last_price": "9",
            },
            {
                "name": "OLD_USDT",
                "status": "delisting",
                "type": "direct",
                "in_delisting": True,
            },
        ]

        records = project_gateio_active_contracts(payload)

        self.assertEqual([row["name"] for row in records], ["1000CAT_USDT", "BTC_USDT"])
        self.assertEqual(set(records[0]), {"name", "status", "type", "in_delisting"})
        self.assertNotIn("funding_rate", json.dumps(records))
        self.assertNotIn("mark_price", json.dumps(records))

    def test_ticker_intersection_is_provisional_and_never_identity_evidence(self) -> None:
        mexc = project_mexc_active_contracts(
            {
                "success": True,
                "code": 0,
                "data": [
                    {
                        "symbol": "BTC_USDT",
                        "baseCoin": "BTC",
                        "quoteCoin": "USDT",
                        "settleCoin": "USDT",
                        "state": 0,
                        "apiAllowed": True,
                    },
                    {
                        "symbol": "MEXCONLY_USDT",
                        "baseCoin": "MEXCONLY",
                        "quoteCoin": "USDT",
                        "settleCoin": "USDT",
                        "state": 0,
                        "apiAllowed": True,
                    },
                ],
            }
        )
        gate = project_gateio_active_contracts(
            [
                {
                    "name": "BTC_USDT",
                    "status": "trading",
                    "type": "direct",
                    "in_delisting": False,
                },
                {
                    "name": "GATEONLY_USDT",
                    "status": "trading",
                    "type": "direct",
                    "in_delisting": False,
                },
            ]
        )

        candidates = build_provisional_ticker_candidates(mexc, gate)

        self.assertEqual(
            candidates,
            [
                {
                    "ticker": "BTC",
                    "mexc_symbol": "BTC_USDT",
                    "gateio_name": "BTC_USDT",
                    "identity_status": "UNRESOLVED_TICKER_MATCH_ONLY",
                    "same_underlying_verified": False,
                }
            ],
        )

    def test_duplicate_or_malformed_contract_identity_fails_closed(self) -> None:
        duplicate = {
            "success": True,
            "code": 0,
            "data": [
                {
                    "symbol": "BTC_USDT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "state": 0,
                    "apiAllowed": True,
                },
                {
                    "symbol": "BTC_USDT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "state": 0,
                    "apiAllowed": True,
                },
            ],
        }
        with self.assertRaisesRegex(DiscoveryError, "duplicate"):
            project_mexc_active_contracts(duplicate)

        malformed = [
            {
                "name": "BAD/NAME_USDT",
                "status": "trading",
                "type": "direct",
                "in_delisting": False,
            }
        ]
        with self.assertRaisesRegex(DiscoveryError, "unsafe"):
            project_gateio_active_contracts(malformed)

    def test_client_uses_exact_get_without_body_and_records_hash_in_memory(self) -> None:
        opener = FakeOpener([[{"name": "BTC_USDT"}]])
        client = BoundedMetadataClient(
            opener=opener,
            max_total_requests=4,
            max_attempts_per_endpoint=2,
            monotonic=lambda: 1.0,
            deadline_monotonic=10.0,
        )

        payload, evidence = client.fetch(GATEIO_ENDPOINT)

        self.assertEqual(payload, [{"name": "BTC_USDT"}])
        self.assertEqual(client.request_count, 1)
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, GATEIO_ENDPOINT)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertGreater(timeout, 0)
        expected = hashlib.sha256(
            json.dumps(payload).encode("utf-8")
        ).hexdigest()
        self.assertEqual(evidence["response_body_sha256"], expected)
        self.assertNotIn("response_body", evidence)

    def test_client_caps_retries_and_total_requests(self) -> None:
        opener = FakeOpener(
            [OSError("first"), OSError("second"), OSError("third"), OSError("fourth")]
        )
        client = BoundedMetadataClient(
            opener=opener,
            max_total_requests=4,
            max_attempts_per_endpoint=2,
            monotonic=lambda: 1.0,
            deadline_monotonic=10.0,
        )
        with self.assertRaisesRegex(DiscoveryError, "after 2 attempts"):
            client.fetch(MEXC_ENDPOINT)
        with self.assertRaisesRegex(DiscoveryError, "after 2 attempts"):
            client.fetch(GATEIO_ENDPOINT)
        self.assertEqual(client.request_count, 4)
        with self.assertRaisesRegex(DiscoveryError, "request budget exhausted"):
            client.fetch(MEXC_ENDPOINT)

    def test_immutable_writer_refuses_overwrite_and_never_writes_raw_payload(self) -> None:
        mexc = [
            {
                "symbol": "BTC_USDT",
                "baseCoin": "BTC",
                "baseCoinName": "Bitcoin",
                "quoteCoin": "USDT",
                "quoteCoinName": "Tether",
                "settleCoin": "USDT",
                "state": 0,
                "apiAllowed": True,
            }
        ]
        gate = [
            {
                "name": "BTC_USDT",
                "status": "trading",
                "type": "direct",
                "in_delisting": False,
            }
        ]
        candidates = build_provisional_ticker_candidates(mexc, gate)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "immutable"
            manifest = write_immutable_discovery(
                output,
                run_id="fixture_run",
                mexc_records=mexc,
                gateio_records=gate,
                provisional_candidates=candidates,
                endpoint_evidence={
                    "mexc": {
                        "url": MEXC_ENDPOINT,
                        "response_body_sha256": "a" * 64,
                        "attempts": 1,
                    },
                    "gateio": {
                        "url": GATEIO_ENDPOINT,
                        "response_body_sha256": "b" * 64,
                        "attempts": 1,
                    },
                },
                bindings={
                    "proposal_hash": "c" * 64,
                    "receipt_hash": "d" * 64,
                    "runtime_manifest_hash": "e" * 64,
                },
                started_at_utc="2026-08-10T00:00:00Z",
                finished_at_utc="2026-08-10T00:00:01Z",
                duration_sec=1.0,
                request_count=2,
                hard_output_cap_bytes=50_000_000,
                minimum_active_contracts_per_venue=1,
            )

            self.assertEqual(manifest["status"], "COMPLETE_REQUIRES_IDENTITY_VERIFICATION")
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                [
                    "gateio-active-contracts.json",
                    "manifest.json",
                    "mexc-active-contracts.json",
                    "provisional-shared-ticker-candidates.json",
                ],
            )
            projected = "\n".join(
                (output / name).read_text(encoding="utf-8")
                for name in (
                    "mexc-active-contracts.json",
                    "gateio-active-contracts.json",
                    "provisional-shared-ticker-candidates.json",
                )
            )
            for forbidden in ("fundingRate", "funding_rate", "mark_price", "lastPrice"):
                self.assertNotIn(forbidden, projected)
            self.assertFalse(any("raw" in path.name.lower() for path in output.iterdir()))
            with self.assertRaisesRegex(DiscoveryError, "already exists"):
                write_immutable_discovery(
                    output,
                    run_id="fixture_run",
                    mexc_records=mexc,
                    gateio_records=gate,
                    provisional_candidates=candidates,
                    endpoint_evidence={},
                    bindings={},
                    started_at_utc="2026-08-10T00:00:00Z",
                    finished_at_utc="2026-08-10T00:00:01Z",
                    duration_sec=1.0,
                    request_count=0,
                    hard_output_cap_bytes=50_000_000,
                    minimum_active_contracts_per_venue=1,
                )

    def test_global_writer_claim_must_match_exact_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            claim_path = Path(temp_dir) / "claim.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_global_market_writer_claim_v1",
                        "status": "CLAIMED",
                        "run_id": "fixture_run",
                        "owner_pid": 123,
                        "ownership_token": "a" * 32,
                    }
                ),
                encoding="utf-8",
            )
            verified = verify_global_writer_claim(
                claim_path,
                run_id="fixture_run",
                owner_pid=123,
                ownership_token="a" * 32,
            )
            self.assertEqual(verified["run_id"], "fixture_run")
            with self.assertRaisesRegex(DiscoveryError, "token"):
                verify_global_writer_claim(
                    claim_path,
                    run_id="fixture_run",
                    owner_pid=123,
                    ownership_token="b" * 32,
                )

    def test_frozen_artifacts_validate_and_preflight_does_not_create_output(self) -> None:
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        output = Path(receipt["run_binding"]["output_path"])
        existed_before = output.exists()
        result = validate_execution_artifacts(
            repo_root=ROOT,
            proposal_path=PROPOSAL_PATH,
            expected_proposal_file_sha256=(
                "8270be9ae66e546e0f5eca4d774d8f85985e732527bab0fc92415766c08b4de0"
            ),
            expected_proposal_hash=(
                "0ac65470275e28819583bf6599d57674cda0cf6a523e4dbb1d85583997380f77"
            ),
            receipt_path=RECEIPT_PATH,
            runtime_manifest_path=RUNTIME_MANIFEST_PATH,
            output_path=output,
            run_id="funding_unrestricted_metadata_discovery_20260810_v1",
        )
        self.assertIn(
            result["status"],
            {"PREFLIGHT_OK_NO_NETWORK", "ALREADY_COMPLETE_IMMUTABLE_NO_NETWORK"},
        )
        self.assertEqual(output.exists(), existed_before)

    def test_launcher_is_visible_single_owner_and_has_no_market_data_scope(self) -> None:
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8-sig")
        for expected in (
            "start_funding_unrestricted_metadata_discovery_visible.ps1",
            "funding_unrestricted_metadata_discovery.py",
            "global_market_writer_claim.py",
            "active-market-data-writer-claim.json",
            "Start-Process",
            "-WindowStyle Normal",
            '"-NoExit"',
            "VISIBLE_TERMINAL_LAUNCHED",
            "terminal_ownership_verified",
            "PreflightOnly",
            "VisibleWorker",
            "STOPPED_INCOMPLETE",
            MEXC_ENDPOINT,
            GATEIO_ENDPOINT,
        ):
            self.assertIn(expected, launcher)
        for forbidden in (
            "mark_price",
            "last_price",
            "evaluator",
            "private api",
            "/funding_rate",
            "/tickers",
        ):
            self.assertNotIn(forbidden, launcher.lower())


if __name__ == "__main__":
    unittest.main()
