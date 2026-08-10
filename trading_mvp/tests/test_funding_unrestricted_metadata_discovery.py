from __future__ import annotations

import contextlib
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
    RejectRedirectHandler,
    build_failure_diagnostic_record,
    build_provisional_ticker_candidates,
    project_gateio_active_contracts,
    project_mexc_active_contracts,
    main,
    read_failure_diagnostic,
    validate_execution_artifacts,
    validate_failure_diagnostic_path,
    verify_global_writer_claim,
    write_failure_diagnostic,
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

    def test_default_client_rejects_redirects_before_any_followup_request(self) -> None:
        client = BoundedMetadataClient()
        redirect_handlers = [
            handler
            for handler in client.opener.handlers
            if isinstance(handler, RejectRedirectHandler)
        ]

        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsNone(
            redirect_handlers[0].redirect_request(
                None,
                None,
                302,
                "Found",
                {},
                "https://unapproved.example/metadata",
            )
        )

    def test_network_failure_diagnostic_is_allowlisted_and_has_no_error_text(self) -> None:
        secret = "fundingRate=0.75 price=123 raw-payload-secret"
        opener = FakeOpener([OSError(secret), OSError(secret)])
        client = BoundedMetadataClient(
            opener=opener,
            max_total_requests=4,
            max_attempts_per_endpoint=2,
            monotonic=lambda: 1.0,
            deadline_monotonic=10.0,
        )

        with self.assertRaises(DiscoveryError) as raised:
            client.fetch(MEXC_ENDPOINT)

        diagnostic = raised.exception.diagnostic
        self.assertEqual(diagnostic["category"], "NETWORK_IO")
        self.assertEqual(diagnostic["stage"], "HTTP_REQUEST")
        self.assertEqual(diagnostic["endpoint_id"], "MEXC_CONTRACT_DETAIL")
        self.assertEqual(diagnostic["exception_type"], "OS_ERROR")
        self.assertEqual(diagnostic["attempt"], 2)
        self.assertEqual(diagnostic["request_count"], 2)
        self.assertNotIn(secret, json.dumps(diagnostic, sort_keys=True))

    def test_failure_diagnostic_is_immutable_bounded_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_id = "fixture_metadata_v2"
            target = root / "docs" / "agent-log" / "run-gates" / (
                f"{run_id}.runtime-failure.json"
            )
            validated = validate_failure_diagnostic_path(root, run_id, target)
            record = build_failure_diagnostic_record(
                run_id=run_id,
                expected_proposal_hash="a" * 64,
                diagnostic={
                    "category": "HTTP_STATUS",
                    "stage": "HTTP_REQUEST",
                    "endpoint_id": "GATEIO_CONTRACTS",
                    "exception_type": "HTTP_ERROR",
                    "http_status": 403,
                    "attempt": 1,
                    "request_count": 1,
                    "error": "raw fundingRate=1 price=2",
                },
            )
            written = write_failure_diagnostic(validated, record)

            persisted = json.loads(validated.read_text(encoding="utf-8"))
            self.assertEqual(written["failure_hash"], persisted["failure_hash"])
            self.assertEqual(persisted["failure"]["category"], "HTTP_STATUS")
            self.assertEqual(persisted["failure"]["http_status"], 403)
            self.assertEqual(
                sorted(persisted["failure"]),
                [
                    "attempt",
                    "category",
                    "endpoint_id",
                    "exception_type",
                    "http_status",
                    "request_count",
                    "stage",
                ],
            )
            serialized = json.dumps(persisted, sort_keys=True)
            for forbidden in (
                "raw fundingRate=1 price=2",
                "fundingRate=1",
                "price=2",
                '"error"',
            ):
                self.assertNotIn(forbidden, serialized)
            self.assertFalse(persisted["raw_payload_persisted"])
            self.assertFalse(persisted["funding_rates_persisted"])
            self.assertFalse(persisted["prices_persisted"])
            self.assertLess(validated.stat().st_size, 16_384)
            with self.assertRaisesRegex(DiscoveryError, "already exists"):
                write_failure_diagnostic(validated, record)

    def test_failure_writer_rejects_extra_top_level_or_nested_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_id = "fixture_strict_failure_v2"
            target = root / "docs" / "agent-log" / "run-gates" / (
                f"{run_id}.runtime-failure.json"
            )
            record = build_failure_diagnostic_record(
                run_id=run_id,
                expected_proposal_hash="a" * 64,
                diagnostic={
                    "category": "HTTP_STATUS",
                    "stage": "HTTP_RESPONSE",
                    "endpoint_id": "MEXC_CONTRACT_DETAIL",
                    "exception_type": "HTTP_ERROR",
                    "http_status": 302,
                    "attempt": 1,
                    "request_count": 1,
                },
            )

            top_level = dict(record)
            top_level["raw_payload"] = "fundingRate=1 price=2"
            with self.assertRaisesRegex(DiscoveryError, "top-level fields changed"):
                write_failure_diagnostic(target, top_level)

            nested = dict(record)
            nested["failure"] = dict(record["failure"])
            nested["failure"]["error"] = "fundingRate=1 price=2"
            with self.assertRaisesRegex(DiscoveryError, "detail fields changed"):
                write_failure_diagnostic(target, nested)
            self.assertFalse(target.exists())

    def test_failure_reader_rechecks_hash_and_numeric_json_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_id = "fixture_read_failure_v2"
            target = root / "docs" / "agent-log" / "run-gates" / (
                f"{run_id}.runtime-failure.json"
            )
            record = build_failure_diagnostic_record(
                run_id=run_id,
                expected_proposal_hash="a" * 64,
                diagnostic={
                    "category": "HTTP_STATUS",
                    "stage": "HTTP_RESPONSE",
                    "endpoint_id": "GATEIO_CONTRACTS",
                    "exception_type": "HTTP_ERROR",
                    "http_status": 429,
                    "attempt": 1,
                    "request_count": 1,
                },
            )
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(record), encoding="utf-8")
            loaded = read_failure_diagnostic(
                target,
                expected_run_id=run_id,
                expected_proposal_hash="a" * 64,
            )
            self.assertEqual(loaded["failure_hash"], record["failure_hash"])

            tampered = dict(record)
            tampered["failure"] = dict(record["failure"])
            tampered["failure"]["request_count"] = "1"
            target.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(DiscoveryError, "request_count must be"):
                read_failure_diagnostic(
                    target,
                    expected_run_id=run_id,
                    expected_proposal_hash="a" * 64,
                )

            tampered["failure"]["request_count"] = 1
            tampered["failure_hash"] = "b" * 64
            target.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(DiscoveryError, "canonical hash mismatch"):
                read_failure_diagnostic(
                    target,
                    expected_run_id=run_id,
                    expected_proposal_hash="a" * 64,
                )

    def test_failure_validation_cli_returns_only_allowlisted_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_id = "fixture_cli_failure_v2"
            failure_path = root / "docs" / "agent-log" / "run-gates" / (
                f"{run_id}.runtime-failure.json"
            )
            record = build_failure_diagnostic_record(
                run_id=run_id,
                expected_proposal_hash="a" * 64,
                diagnostic={
                    "category": "HTTP_STATUS",
                    "stage": "HTTP_RESPONSE",
                    "endpoint_id": "MEXC_CONTRACT_DETAIL",
                    "exception_type": "HTTP_ERROR",
                    "http_status": 302,
                    "attempt": 1,
                    "request_count": 1,
                },
            )
            write_failure_diagnostic(failure_path, record)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--repo-root",
                        str(root),
                        "--proposal-path",
                        str(root / "unused-proposal.json"),
                        "--expected-proposal-file-sha256",
                        "b" * 64,
                        "--expected-proposal-hash",
                        "a" * 64,
                        "--receipt-path",
                        str(root / "unused-receipt.json"),
                        "--runtime-manifest-path",
                        str(root / "unused-manifest.json"),
                        "--output-path",
                        str(root / "unused-output"),
                        "--run-id",
                        run_id,
                        "--failure-diagnostic-path",
                        str(failure_path),
                        "--validate-failure-diagnostic-only",
                    ]
                )

            self.assertEqual(exit_code, 0)
            rendered = json.loads(stdout.getvalue())
            self.assertEqual(rendered["status"], "VALIDATED_ALLOWLISTED_FAILURE")
            self.assertEqual(rendered["failure_hash"], record["failure_hash"])
            self.assertEqual(set(rendered["failure"]), set(record["failure"]))
            self.assertNotIn("observed_at_utc", rendered)

    def test_execute_binding_failure_writes_safe_diagnostic_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_id = "fixture_execute_failure_v2"
            failure_path = root / "docs" / "agent-log" / "run-gates" / (
                f"{run_id}.runtime-failure.json"
            )
            output = root / "output"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--repo-root",
                        str(root),
                        "--proposal-path",
                        str(root / "missing-proposal.json"),
                        "--expected-proposal-file-sha256",
                        "b" * 64,
                        "--expected-proposal-hash",
                        "a" * 64,
                        "--receipt-path",
                        str(root / "missing-receipt.json"),
                        "--runtime-manifest-path",
                        str(root / "missing-manifest.json"),
                        "--output-path",
                        str(output),
                        "--run-id",
                        run_id,
                        "--failure-diagnostic-path",
                        str(failure_path),
                        "--execute",
                        "--global-writer-claim-path",
                        str(root / "missing-claim.json"),
                        "--owner-pid",
                        "123",
                        "--ownership-token",
                        "c" * 32,
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertTrue(failure_path.is_file())
            self.assertFalse(output.exists())
            record = json.loads(failure_path.read_text(encoding="utf-8"))
            self.assertEqual(record["failure"]["category"], "BINDING_VALIDATION")
            self.assertEqual(record["failure"]["request_count"], 0)
            rendered = stderr.getvalue()
            self.assertNotIn("missing-proposal", rendered)
            self.assertNotIn("could not be loaded", rendered)

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

    def test_terminal_v1_artifacts_cannot_authorize_diagnostic_v2_runtime(self) -> None:
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        output = Path(receipt["run_binding"]["output_path"])
        existed_before = output.exists()
        with self.assertRaises(DiscoveryError):
            validate_execution_artifacts(
                repo_root=ROOT,
                proposal_path=PROPOSAL_PATH,
                expected_proposal_file_sha256=(
                    "8270be9ae66e0f5eca4d774d8f85985e732527bab0fc92415766c08b4de0"
                ),
                expected_proposal_hash=(
                    "0ac65470275e28819583bf6599d57674cda0cf6a523e4dbb1d85583997380f77"
                ),
                receipt_path=RECEIPT_PATH,
                runtime_manifest_path=RUNTIME_MANIFEST_PATH,
                output_path=output,
                run_id="funding_unrestricted_metadata_discovery_20260810_v1",
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
            "runtime-failure.json",
            "Read-RuntimeFailureDiagnostic",
            "--validate-failure-diagnostic-only",
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
