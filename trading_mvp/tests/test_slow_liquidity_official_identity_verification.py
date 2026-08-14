from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from trading_mvp.src.slow_liquidity_official_identity_verification import (
    EXECUTION_APPROVED_STATUS,
    EXECUTION_MANIFEST_SCHEMA,
    EXECUTION_RECEIPT_SCHEMA,
    OFFLINE_RECEIPT_SCHEMA,
    RUNTIME_MANIFEST_SCHEMA,
    FetchedResponse,
    IdentityVerificationError,
    build_identity_result,
    build_offline_approval_receipt,
    build_runtime_manifest,
    canonical_hash_without,
    collect_identity_evidence,
    collect_identity_evidence_bundle,
    freeze_offline_bundle,
    validate_exact_guard_snapshot,
    validate_execution_manifest,
    validate_execution_snapshot_files_unchanged,
    validate_global_writer_claim,
    validate_offline_approval_receipt,
    validate_preclaim_guard_attestation,
    validate_runtime_manifest,
    validate_visible_launcher_capability,
    write_identity_output,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_PATH = (
    REPO_ROOT
    / "docs/plans/drafts/"
    "slow-liquidity-official-asset-identity-verification-proposal-20260813-v1.json"
)
PROPOSAL_HASH = "3a4479cacaceb310556821df8bd0f28d5cb1dac06644764c9b209bf3e234d8a4"
PROPOSAL_FILE_SHA256 = (
    "52d2c848888577a61e6994b57786616a9732c2ec384d6c4633325123b1b63c62"
)
BASES = ("STETH", "WEETH", "CC", "OKB", "RAIN", "MNT", "USDD", "BDX", "EDGE")


def canonical_evidence_assertion(
    *, venue: str, base: str, instrument: str, label: str, identifier: str
) -> str:
    return json.dumps(
        {
            "base_ticker": base,
            "canonical_asset_identifier_label": label,
            "canonical_asset_identifier_value": identifier,
            "instrument_id": instrument,
            "venue": venue,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(payload))


def source_bindings(root: Path) -> dict[str, dict[str, str]]:
    return {
        "proposal": {
            "path": str(root / "proposal.json"),
            "file_sha256": "1" * 64,
            "proposal_hash": "2" * 64,
        },
        "offline_approval_receipt": {
            "path": str(root / "offline-receipt.json"),
            "file_sha256": "3" * 64,
            "receipt_hash": "4" * 64,
        },
        "phase1_runtime_manifest": {
            "path": str(root / "runtime.json"),
            "file_sha256": "5" * 64,
            "manifest_hash": "6" * 64,
        },
        "execution_manifest": {
            "path": str(root / "execution.json"),
            "file_sha256": "7" * 64,
            "manifest_hash": "8" * 64,
        },
        "execution_approval_receipt": {
            "path": str(root / "execution-receipt.json"),
            "file_sha256": "9" * 64,
            "receipt_hash": "a" * 64,
        },
    }


def evidence_record(
    *,
    venue: str,
    base: str,
    identifier: str,
    namespace: str = "EVM_CONTRACT",
) -> dict[str, object]:
    host = "www.mexc.com" if venue == "mexc" else "www.gate.com"
    prefix = "support/articles" if venue == "mexc" else "announcements/article"
    instrument = f"{base}_USDT"
    fragment = canonical_evidence_assertion(
        venue=venue,
        base=base,
        instrument=instrument,
        label="contract_address",
        identifier=identifier,
    )
    return {
        "venue": venue,
        "base_ticker": base,
        "instrument_id": instrument,
        "official_source_url": f"https://{host}/{prefix}/{base.lower()}-identity",
        "canonical_asset_identifier_namespace": namespace,
        "canonical_asset_identifier_value": identifier,
        "canonical_asset_identifier_label": "contract_address",
        "evidence_locator_type": "CANONICAL_REQUIRED_EXACT_UTF8_TOKENS_V1",
        "evidence_locator_value": fragment,
        "response_body_sha256": "a" * 64,
        "evidence_fragment_sha256": hashlib.sha256(fragment.encode()).hexdigest(),
        "sanitized_evidence_fragment": fragment,
    }


class IdentityDecisionTests(unittest.TestCase):
    def test_accepts_all_bases_when_both_venues_publish_same_identifier(self) -> None:
        records: list[dict[str, object]] = []
        for index, base in enumerate(BASES, start=1):
            identifier = f"0x{index:040x}"
            records.append(evidence_record(venue="mexc", base=base, identifier=identifier))
            records.append(
                evidence_record(
                    venue="gateio",
                    base=base,
                    identifier=identifier.upper(),
                )
            )

        result = build_identity_result(records)

        self.assertEqual(result["status"], "IDENTITY_VERIFIED_CANDIDATE_PLANONLY_REQUIRED")
        self.assertEqual(result["verified_bases"], list(BASES))
        self.assertEqual(result["verified_base_count"], 9)
        self.assertEqual(result["rejected_bases"], [])
        self.assertFalse(result["candidate_planonly_created"])
        self.assertFalse(result["data_collection_authorized"])

    def test_conflicting_identifier_is_rejected_without_rescope(self) -> None:
        records: list[dict[str, object]] = []
        for index, base in enumerate(BASES, start=1):
            identifier = f"0x{index:040x}"
            records.append(evidence_record(venue="mexc", base=base, identifier=identifier))
            records.append(
                evidence_record(
                    venue="gateio",
                    base=base,
                    identifier=("0x" + "f" * 40) if base == "EDGE" else identifier,
                )
            )

        result = build_identity_result(records)

        self.assertEqual(result["status"], "IDENTITY_VERIFIED_CANDIDATE_PLANONLY_REQUIRED")
        self.assertEqual(result["verified_base_count"], 8)
        self.assertEqual(result["rejected_bases"], ["EDGE"])
        self.assertEqual(result["base_decisions"]["EDGE"]["decision"], "REJECT_EXCLUDE_FAIL_CLOSED")
        self.assertFalse(result["rescope_authorized"])

    def test_missing_identifier_below_minimum_fails_closed(self) -> None:
        records: list[dict[str, object]] = []
        for index, base in enumerate(BASES[:7], start=1):
            identifier = f"asset-{index}"
            records.append(
                evidence_record(
                    venue="mexc",
                    base=base,
                    identifier=identifier,
                    namespace="NATIVE_ASSET_ID",
                )
            )
            records.append(
                evidence_record(
                    venue="gateio",
                    base=base,
                    identifier=identifier,
                    namespace="NATIVE_ASSET_ID",
                )
            )

        result = build_identity_result(records)

        self.assertEqual(
            result["status"],
            "INSUFFICIENT_IDENTITY_VERIFIED_UNIVERSE_NO_RESCOPE_WITHOUT_NEW_APPROVAL",
        )
        self.assertEqual(result["verified_base_count"], 7)
        self.assertEqual(result["unresolved_bases"], ["BDX", "EDGE"])
        self.assertFalse(result["evaluator_authorized"])

    def test_non_evm_identifiers_compare_exactly(self) -> None:
        records: list[dict[str, object]] = []
        for index, base in enumerate(BASES, start=1):
            left = f"asset-{index}"
            right = left.upper() if base == "EDGE" else left
            records.append(
                evidence_record(
                    venue="mexc",
                    base=base,
                    identifier=left,
                    namespace="NATIVE_ASSET_ID",
                )
            )
            records.append(
                evidence_record(
                    venue="gateio",
                    base=base,
                    identifier=right,
                    namespace="NATIVE_ASSET_ID",
                )
            )

        result = build_identity_result(records)

        self.assertEqual(result["rejected_bases"], ["EDGE"])

    def test_rejects_ticker_only_or_non_allowlisted_evidence(self) -> None:
        record = evidence_record(venue="mexc", base="STETH", identifier="0x" + "1" * 40)
        record["canonical_asset_identifier_value"] = ""
        with self.assertRaisesRegex(IdentityVerificationError, "identifier"):
            build_identity_result([record])

        record = evidence_record(venue="mexc", base="STETH", identifier="0x" + "1" * 40)
        record["official_source_url"] = "https://example.com/support/articles/steth"
        with self.assertRaisesRegex(IdentityVerificationError, "official source"):
            build_identity_result([record])


class SyntheticCollectionTests(unittest.TestCase):
    @staticmethod
    def metadata_response(url: str, instruments: tuple[str, ...]) -> FetchedResponse:
        if url == "https://contract.mexc.com/api/v1/contract/detail":
            body = {
                "success": True,
                "code": 0,
                "data": [
                    {
                        "symbol": instrument,
                        "baseCoin": instrument.removesuffix("_USDT"),
                        "quoteCoin": "USDT",
                        "settleCoin": "USDT",
                        "state": 0,
                        "apiAllowed": True,
                    }
                    for instrument in instruments
                ],
            }
        elif url == "https://api.gateio.ws/api/v4/futures/usdt/contracts":
            body = [
                {
                    "name": instrument,
                    "status": "trading",
                    "in_delisting": False,
                }
                for instrument in instruments
            ]
        else:
            raise AssertionError(f"not a metadata URL: {url}")
        return FetchedResponse(
            requested_url=url,
            final_url=url,
            status=200,
            body=json.dumps(body, separators=(",", ":")).encode(),
        )

    def test_collects_only_sanitized_exact_fragment_evidence(self) -> None:
        identifier = "0x" + "1" * 40
        fragment = canonical_evidence_assertion(
            venue="mexc",
            base="STETH",
            instrument="STETH_USDT",
            label="contract_address",
            identifier=identifier,
        )
        request_plan = [
            {
                "venue": "mexc",
                "base_ticker": "STETH",
                "instrument_id": "STETH_USDT",
                "official_source_url": "https://www.mexc.com/support/articles/steth-identity",
                "canonical_asset_identifier_namespace": "EVM_CONTRACT",
                "canonical_asset_identifier_value": identifier,
                "canonical_asset_identifier_label": "contract_address",
                "evidence_locator_type": "CANONICAL_REQUIRED_EXACT_UTF8_TOKENS_V1",
                "evidence_locator_value": fragment,
                "sanitized_evidence_fragment": fragment,
            }
        ]
        seen: list[str] = []

        def fetch(url: str) -> FetchedResponse:
            seen.append(url)
            if url.startswith("https://contract.mexc.com/") or url.startswith(
                "https://api.gateio.ws/"
            ):
                return self.metadata_response(url, ("STETH_USDT",))
            return FetchedResponse(
                requested_url=url,
                final_url=url,
                status=200,
                body=(
                    f"STETH canonical contract_address {identifier}"
                ).encode(),
            )

        records = collect_identity_evidence(request_plan, fetch=fetch)

        self.assertEqual(
            seen,
            [
                "https://contract.mexc.com/api/v1/contract/detail",
                "https://api.gateio.ws/api/v4/futures/usdt/contracts",
                request_plan[0]["official_source_url"],
            ],
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["sanitized_evidence_fragment"], fragment)
        self.assertNotIn("body", records[0])
        self.assertEqual(
            records[0]["response_body_sha256"],
            hashlib.sha256(
                f"STETH canonical contract_address {identifier}".encode()
            ).hexdigest(),
        )
        self.assertEqual(
            records[0]["evidence_fragment_sha256"],
            hashlib.sha256(fragment.encode()).hexdigest(),
        )

    def test_metadata_hashes_are_bound_but_payload_is_not_persisted(self) -> None:
        identifier = "0x" + "1" * 40
        fragment = canonical_evidence_assertion(
            venue="mexc",
            base="STETH",
            instrument="STETH_USDT",
            label="contract_address",
            identifier=identifier,
        )
        plan = {
            "venue": "mexc",
            "base_ticker": "STETH",
            "instrument_id": "STETH_USDT",
            "official_source_url": "https://www.mexc.com/support/articles/steth-identity",
            "canonical_asset_identifier_namespace": "EVM_CONTRACT",
            "canonical_asset_identifier_value": identifier,
            "canonical_asset_identifier_label": "contract_address",
            "evidence_locator_type": "CANONICAL_REQUIRED_EXACT_UTF8_TOKENS_V1",
            "evidence_locator_value": fragment,
            "sanitized_evidence_fragment": fragment,
        }

        def fetch(url: str) -> FetchedResponse:
            if url.startswith("https://contract.mexc.com/") or url.startswith(
                "https://api.gateio.ws/"
            ):
                return self.metadata_response(url, ("STETH_USDT",))
            return FetchedResponse(
                url, url, 200, f"STETH contract_address {identifier}".encode()
            )

        bundle = collect_identity_evidence_bundle([plan], fetch=fetch)

        self.assertEqual(bundle.request_count, 3)
        self.assertEqual(len(bundle.response_body_hashes), 3)
        self.assertEqual(bundle.metadata_active_instruments["mexc"], ("STETH_USDT",))
        self.assertEqual(bundle.metadata_active_instruments["gateio"], ("STETH_USDT",))
        self.assertNotIn("metadata_payload", json.dumps(bundle.records))

    def test_skips_evidence_when_exact_perpetual_is_missing_from_metadata(self) -> None:
        identifier = "0x" + "1" * 40
        fragment = canonical_evidence_assertion(
            venue="mexc",
            base="STETH",
            instrument="STETH_USDT",
            label="contract_address",
            identifier=identifier,
        )
        plan = {
            "venue": "mexc",
            "base_ticker": "STETH",
            "instrument_id": "STETH_USDT",
            "official_source_url": "https://www.mexc.com/support/articles/steth-identity",
            "canonical_asset_identifier_namespace": "EVM_CONTRACT",
            "canonical_asset_identifier_value": identifier,
            "canonical_asset_identifier_label": "contract_address",
            "evidence_locator_type": "CANONICAL_REQUIRED_EXACT_UTF8_TOKENS_V1",
            "evidence_locator_value": fragment,
            "sanitized_evidence_fragment": fragment,
        }
        evidence_called = False

        def fetch(url: str) -> FetchedResponse:
            nonlocal evidence_called
            if url.startswith("https://contract.mexc.com/"):
                return self.metadata_response(url, ())
            if url.startswith("https://api.gateio.ws/"):
                return self.metadata_response(url, ("STETH_USDT",))
            evidence_called = True
            return FetchedResponse(
                url, url, 200, f"STETH contract_address {identifier}".encode()
            )

        bundle = collect_identity_evidence_bundle([plan], fetch=fetch)

        self.assertEqual(bundle.records, ())
        self.assertFalse(evidence_called)
        self.assertEqual(bundle.missing_metadata_instruments, ("mexc:STETH_USDT",))

    def test_rejects_redirect_oversize_or_missing_fragment(self) -> None:
        identifier = "0x" + "1" * 40
        fragment = canonical_evidence_assertion(
            venue="mexc",
            base="STETH",
            instrument="STETH_USDT",
            label="contract_address",
            identifier=identifier,
        )
        plan = {
            "venue": "mexc",
            "base_ticker": "STETH",
            "instrument_id": "STETH_USDT",
            "official_source_url": "https://www.mexc.com/support/articles/steth-identity",
            "canonical_asset_identifier_namespace": "EVM_CONTRACT",
            "canonical_asset_identifier_value": identifier,
            "canonical_asset_identifier_label": "contract_address",
            "evidence_locator_type": "CANONICAL_REQUIRED_EXACT_UTF8_TOKENS_V1",
            "evidence_locator_value": fragment,
            "sanitized_evidence_fragment": fragment,
        }
        def violating_fetch(kind: str):
            def fetch(url: str) -> FetchedResponse:
                if url.startswith("https://contract.mexc.com/") or url.startswith(
                    "https://api.gateio.ws/"
                ):
                    return self.metadata_response(url, ("STETH_USDT",))
                if kind == "redirect":
                    return FetchedResponse(
                        url,
                        url + "/redirect",
                        200,
                        f"STETH contract_address {identifier}".encode(),
                    )
                if kind == "oversize":
                    return FetchedResponse(url, url, 200, b"x" * 1_000_001)
                return FetchedResponse(url, url, 200, b"not present")

            return fetch

        with self.assertRaisesRegex(IdentityVerificationError, "redirect"):
            collect_identity_evidence(
                [plan],
                fetch=violating_fetch("redirect"),
            )
        with self.assertRaisesRegex(IdentityVerificationError, "response cap"):
            collect_identity_evidence(
                [plan],
                fetch=violating_fetch("oversize"),
            )
        with self.assertRaisesRegex(IdentityVerificationError, "identity evidence"):
            collect_identity_evidence(
                [plan],
                fetch=violating_fetch("missing"),
            )

    def test_evidence_assertion_must_bind_venue_base_instrument_label_and_identifier(self) -> None:
        record = evidence_record(
            venue="mexc",
            base="STETH",
            identifier="0x" + "1" * 40,
        )
        record["evidence_locator_value"] = "unrelated official announcement"
        record["sanitized_evidence_fragment"] = "unrelated official announcement"
        record["evidence_fragment_sha256"] = hashlib.sha256(
            b"unrelated official announcement"
        ).hexdigest()

        with self.assertRaisesRegex(IdentityVerificationError, "canonical evidence assertion"):
            build_identity_result([record])

    def test_official_source_rejects_dot_segments_and_encoded_dot_segments(self) -> None:
        for suffix in (
            "../outside",
            "%2e%2e/outside",
            "%252e%252e/outside",
        ):
            record = evidence_record(
                venue="mexc",
                base="STETH",
                identifier="0x" + "1" * 40,
            )
            record["official_source_url"] = (
                "https://www.mexc.com/support/articles/" + suffix
            )
            with self.subTest(suffix=suffix):
                with self.assertRaisesRegex(IdentityVerificationError, "official source path"):
                    build_identity_result([record])


class OfflineFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.receipt_path = self.root / "approvals" / "identity-offline-v1.json"
        self.manifest_path = self.root / "plans" / "identity-runtime-v1.json"
        self.module_path = (
            REPO_ROOT / "trading_mvp/src/slow_liquidity_official_identity_verification.py"
        )
        self.tests_path = Path(__file__).resolve()
        self.launcher_path = (
            REPO_ROOT / "tools/start_exact_approved_slow_liquidity_official_identity_visible.ps1"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_receipt_binds_exact_proposal_and_offline_only_authorization(self) -> None:
        receipt = build_offline_approval_receipt(
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
            approved_at_utc="2026-08-13T14:15:00Z",
            user_authorization_text="разрешаю",
            response_annotation_index=1,
        )

        self.assertEqual(receipt["schema"], OFFLINE_RECEIPT_SCHEMA)
        self.assertEqual(receipt["status"], "APPROVED_OFFLINE_IMPLEMENTATION_ONLY")
        self.assertEqual(receipt["proposal"]["proposal_hash"], PROPOSAL_HASH)
        self.assertTrue(receipt["authorized_scope"]["offline_runtime_implementation"])
        self.assertTrue(receipt["authorized_scope"]["synthetic_tests"])
        self.assertTrue(receipt["authorized_scope"]["runtime_manifest_creation"])
        self.assertFalse(receipt["authorized_scope"]["official_source_content_read"])
        self.assertFalse(receipt["authorized_scope"]["actual_network_run"])
        self.assertFalse(receipt["authorized_scope"]["identity_output"])
        self.assertEqual(
            receipt["receipt_hash"], canonical_hash_without(receipt, "receipt_hash")
        )
        validate_offline_approval_receipt(
            receipt,
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
        )
        with self.assertRaisesRegex(IdentityVerificationError, "text mismatch"):
            build_offline_approval_receipt(
                proposal_path=PROPOSAL_PATH,
                expected_proposal_hash=PROPOSAL_HASH,
                expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
                approved_at_utc="2026-08-13T14:15:00Z",
                user_authorization_text="да",
                response_annotation_index=1,
            )

    def test_runtime_manifest_binds_code_and_keeps_execution_closed(self) -> None:
        receipt = build_offline_approval_receipt(
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
            approved_at_utc="2026-08-13T14:15:00Z",
            user_authorization_text="разрешаю",
            response_annotation_index=1,
        )
        write_json(self.receipt_path, receipt)

        manifest = build_runtime_manifest(
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
            approval_receipt_path=self.receipt_path,
            runtime_module_path=self.module_path,
            synthetic_tests_path=self.tests_path,
            launcher_path=self.launcher_path,
            generated_at_utc="2026-08-13T14:16:00Z",
        )

        self.assertEqual(manifest["schema"], RUNTIME_MANIFEST_SCHEMA)
        self.assertEqual(
            manifest["status"],
            "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
        )
        self.assertEqual(manifest["runtime"]["module_sha256"], sha256(self.module_path))
        self.assertEqual(manifest["runtime"]["launcher_sha256"], sha256(self.launcher_path))
        self.assertFalse(manifest["execution_authorization"]["approved"])
        self.assertFalse(manifest["execution_authorization"]["actual_network_run_allowed"])
        self.assertFalse(manifest["execution_authorization"]["identity_output_allowed"])
        self.assertEqual(
            manifest["manifest_hash"], canonical_hash_without(manifest, "manifest_hash")
        )
        validate_runtime_manifest(manifest)

    def test_freeze_is_exclusive_and_idempotent_only_for_exact_bytes(self) -> None:
        first = freeze_offline_bundle(
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
            approval_receipt_path=self.receipt_path,
            runtime_manifest_path=self.manifest_path,
            runtime_module_path=self.module_path,
            synthetic_tests_path=self.tests_path,
            launcher_path=self.launcher_path,
            approved_at_utc="2026-08-13T14:15:00Z",
            generated_at_utc="2026-08-13T14:16:00Z",
            user_authorization_text="разрешаю",
            response_annotation_index=1,
        )
        second = freeze_offline_bundle(
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
            approval_receipt_path=self.receipt_path,
            runtime_manifest_path=self.manifest_path,
            runtime_module_path=self.module_path,
            synthetic_tests_path=self.tests_path,
            launcher_path=self.launcher_path,
            approved_at_utc="2026-08-13T14:15:00Z",
            generated_at_utc="2026-08-13T14:16:00Z",
            user_authorization_text="разрешаю",
            response_annotation_index=1,
        )

        self.assertEqual(first, second)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["user_authorization_text"] = "different"
        write_json(self.receipt_path, receipt)
        with self.assertRaisesRegex(IdentityVerificationError, "immutable"):
            freeze_offline_bundle(
                proposal_path=PROPOSAL_PATH,
                expected_proposal_hash=PROPOSAL_HASH,
                expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
                approval_receipt_path=self.receipt_path,
                runtime_manifest_path=self.manifest_path,
                runtime_module_path=self.module_path,
                synthetic_tests_path=self.tests_path,
                launcher_path=self.launcher_path,
                approved_at_utc="2026-08-13T14:15:00Z",
                generated_at_utc="2026-08-13T14:16:00Z",
                user_authorization_text="разрешаю",
                response_annotation_index=1,
            )

    def test_runtime_manifest_tamper_is_rejected(self) -> None:
        receipt = build_offline_approval_receipt(
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
            approved_at_utc="2026-08-13T14:15:00Z",
            user_authorization_text="разрешаю",
            response_annotation_index=1,
        )
        write_json(self.receipt_path, receipt)
        manifest = build_runtime_manifest(
            proposal_path=PROPOSAL_PATH,
            expected_proposal_hash=PROPOSAL_HASH,
            expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
            approval_receipt_path=self.receipt_path,
            runtime_module_path=self.module_path,
            synthetic_tests_path=self.tests_path,
            launcher_path=self.launcher_path,
            generated_at_utc="2026-08-13T14:16:00Z",
        )
        manifest["execution_authorization"]["actual_network_run_allowed"] = True
        manifest["manifest_hash"] = canonical_hash_without(manifest, "manifest_hash")
        with self.assertRaisesRegex(IdentityVerificationError, "network"):
            validate_runtime_manifest(manifest)


class ExecutionBoundaryTests(unittest.TestCase):
    def _execution_fixture(self, root: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        runtime_path = root / "runtime-manifest.json"
        receipt_path = root / "execution-receipt.json"
        request_plan = []
        for index, base in enumerate(BASES, start=1):
            for venue in ("mexc", "gateio"):
                identifier = f"0x{index:040x}"
                record = evidence_record(venue=venue, base=base, identifier=identifier)
                record.pop("response_body_sha256")
                record.pop("evidence_fragment_sha256")
                request_plan.append(record)
        request_plan_hash = hashlib.sha256(
            json.dumps(
                request_plan,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        runtime = {
            "schema": RUNTIME_MANIFEST_SCHEMA,
            "status": "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
            "manifest_hash": "b" * 64,
            "output_contract": {"run_output_path": str(root / "output")},
        }
        runtime_binding = {
            "path": str(runtime_path.resolve()),
            "file_sha256": "c" * 64,
            "manifest_hash": runtime["manifest_hash"],
        }
        limits = {
            "maximum_total_http_requests": 40,
            "maximum_attempts_per_url": 2,
            "maximum_response_bytes_per_request": 1_000_000,
            "max_runtime_sec": 600,
            "hard_output_cap_bytes": 20_000_000,
        }
        scope = {
            "one_visible_public_read_only_identity_run": True,
            "official_source_content_read": True,
            "technical_identity_output": True,
            "global_writer_claim": True,
            "candidate_planonly_creation": False,
            "collector_or_evaluator": False,
            "oos": False,
            "returns_or_pnl": False,
            "grid_or_retune": False,
            "execution_probe": False,
            "paper_or_live": False,
            "private_api": False,
            "real_capital": False,
            "leverage_or_margin": False,
        }
        approval_text = (
            "Разрешаю один видимый public read-only запуск "
            "slow_liquidity_official_asset_identity_verification_20260813_v1 "
            f"runtime_manifest_path={runtime_binding['path']} "
            f"runtime_manifest_file_sha256={runtime_binding['file_sha256']} "
            f"runtime_manifest_hash={runtime_binding['manifest_hash']} "
            f"request_plan_sha256={request_plan_hash} "
            f"required_policy_file_sha256={'d' * 64} "
            "maximum_total_http_requests=40 maximum_attempts_per_url=2 "
            "maximum_response_bytes_per_request=1000000 max_runtime_sec=600 "
            "hard_output_cap_bytes=20000000. STOPPED_INCOMPLETE не повторять. "
            "Без candidate PlanOnly, collector/evaluator, OOS, returns/PnL, "
            "grid/retune, execution probe, paper/live, private API, реальных денег, "
            "плеча или маржи."
        )
        message_timestamp = "2026-08-13T13:05:57.033Z"
        receipt = {
            "schema": EXECUTION_RECEIPT_SCHEMA,
            "status": "APPROVED_SINGLE_USE",
            "approved_at_utc": message_timestamp,
            "user_approval_text": approval_text,
            "approval_provenance": {
                "mode": "MANUAL_CODEX_CHECKPOINT_AFTER_DIRECT_USER_APPROVAL",
                "runtime_minting_allowed": False,
                "launcher_minting_allowed": False,
            },
            "phase1_runtime_manifest": runtime_binding,
            "request_plan_sha256": request_plan_hash,
            "authorized_scope": scope,
            "limits": limits,
            "authoritative_guard_contract": {
                "required_guard_decision": "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION",
                "required_readiness_source_status": "IDENTITY_RUNTIME_FROZEN_WITH_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
                "required_readiness_checkpoint_id": "slow_liquidity_identity_execution_phase_2",
                "required_policy_file_sha256": "d" * 64,
            },
            "single_use": True,
            "stopped_incomplete_retry_authorized": False,
            "receipt_hash_method": "sha256_canonical_json_excluding_receipt_hash",
        }
        receipt["receipt_hash"] = canonical_hash_without(receipt, "receipt_hash")
        write_json(receipt_path, receipt)
        receipt_sha = sha256(receipt_path)
        execution = {
            "schema": EXECUTION_MANIFEST_SCHEMA,
            "status": EXECUTION_APPROVED_STATUS,
            "execution_authorized": True,
            "execution_approval": {
                "status": "APPROVED",
                "path": str(receipt_path.resolve()),
                "file_sha256": receipt_sha,
                "receipt_hash": receipt["receipt_hash"],
                "user_approval_text": approval_text,
                "approved_at_utc": message_timestamp,
            },
            "phase1_runtime_manifest": runtime_binding,
            "authorized_scope": scope,
            "limits": limits,
            "single_use": True,
            "stopped_incomplete_retry_authorized": False,
            "request_plan": request_plan,
            "output_path": str((root / "output").resolve()),
            "manifest_hash_method": "sha256_canonical_json_excluding_manifest_hash",
        }
        execution["manifest_hash"] = canonical_hash_without(execution, "manifest_hash")
        return runtime, receipt, execution

    def test_runtime_cli_cannot_mint_execution_approval(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "trading_mvp.src.slow_liquidity_official_identity_verification",
                "--validate-runtime-manifest",
                "--freeze-exact-execution-bundle",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unrecognized arguments", proc.stderr)

    def test_launcher_capability_requires_exact_bound_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            launcher = root / "approved-launcher.ps1"
            launcher.write_text("Write-Host approved\n", encoding="utf-8")
            output = root / "output"
            token = "a" * 64
            owner_pid = 100
            writer_pid = 101
            owner_command = (
                f'"pwsh.exe" -NoExit -File "{launcher.resolve()}" -VisibleWorker'
            )
            writer_command = '"python.exe" -m identity --run-approved'
            capability = {
                "schema": "trading_mvp_slow_liquidity_official_identity_launcher_capability_v1",
                "status": "ACTIVE",
                "run_id": "slow_liquidity_official_asset_identity_verification_20260813_v1",
                "owner_pid": owner_pid,
                "writer_pid": writer_pid,
                "owner_process_creation_utc": "2026-08-13T15:00:00.0000000Z",
                "owner_executable_path": "C:/Program Files/PowerShell/7/pwsh.exe",
                "owner_command_line_sha256": hashlib.sha256(
                    owner_command.encode()
                ).hexdigest(),
                "writer_process_creation_utc": "2026-08-13T15:00:01.0000000Z",
                "writer_executable_path": "C:/Python313/python.exe",
                "writer_command_line_sha256": hashlib.sha256(
                    writer_command.encode()
                ).hexdigest(),
                "launcher_path": str(launcher.resolve()),
                "launcher_file_sha256": sha256(launcher),
                "runtime_manifest_file_sha256": "b" * 64,
                "execution_manifest_file_sha256": "c" * 64,
                "output_path": str(output.resolve()),
                "capability_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "visible_console_verified": True,
                "single_use": True,
                "guard_decision": "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION",
                "policy_hash": "d" * 64,
                "readiness_hash": "e" * 64,
                "guard_observed_at_utc": "2026-08-13T15:00:00Z",
                "guard_checked_before_writer_claim": True,
                "created_at_utc": "2026-08-13T15:00:01Z",
            }
            capability_path = root / "capability.json"
            write_json(capability_path, capability)
            owner = {
                "CreationDate": capability["owner_process_creation_utc"],
                "ExecutablePath": capability["owner_executable_path"],
                "CommandLine": owner_command,
            }
            writer = {
                "CreationDate": capability["writer_process_creation_utc"],
                "ExecutablePath": capability["writer_executable_path"],
                "CommandLine": writer_command,
                "ParentProcessId": owner_pid,
            }
            process_snapshot = (
                "trading_mvp.src.slow_liquidity_official_identity_verification."
                "_windows_process_snapshot"
            )
            with mock.patch(process_snapshot, side_effect=[owner, writer]):
                validate_visible_launcher_capability(
                    capability_path=capability_path,
                    capability_token=token,
                    owner_pid=owner_pid,
                    writer_pid=writer_pid,
                    launcher_path=launcher,
                    launcher_file_sha256=sha256(launcher),
                    runtime_manifest_file_sha256="b" * 64,
                    execution_manifest_file_sha256="c" * 64,
                    output_path=output,
                )

            forged_command = (
                f'"pwsh.exe" -NoExit -File "{root / "forged.ps1"}" -VisibleWorker'
            )
            capability["owner_command_line_sha256"] = hashlib.sha256(
                forged_command.encode()
            ).hexdigest()
            write_json(capability_path, capability)
            owner["CommandLine"] = forged_command
            with mock.patch(process_snapshot, side_effect=[owner, writer]):
                with self.assertRaisesRegex(
                    IdentityVerificationError, "exact approved launcher"
                ):
                    validate_visible_launcher_capability(
                        capability_path=capability_path,
                        capability_token=token,
                        owner_pid=owner_pid,
                        writer_pid=writer_pid,
                        launcher_path=launcher,
                        launcher_file_sha256=sha256(launcher),
                        runtime_manifest_file_sha256="b" * 64,
                        execution_manifest_file_sha256="c" * 64,
                        output_path=output,
                    )

    def test_preclaim_guard_attestation_avoids_writer_self_block(self) -> None:
        capability = {
            "guard_checked_before_writer_claim": True,
            "guard_decision": "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION",
            "policy_hash": "d" * 64,
            "readiness_hash": "e" * 64,
            "guard_observed_at_utc": "2026-08-13T15:00:00Z",
        }
        receipt = {
            "authoritative_guard_contract": {
                "required_guard_decision": "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION",
                "required_policy_file_sha256": "d" * 64,
            }
        }
        validate_preclaim_guard_attestation(
            capability,
            receipt,
            now_utc=datetime(2026, 8, 13, 15, 0, 30, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(IdentityVerificationError, "stale"):
            validate_preclaim_guard_attestation(
                capability,
                receipt,
                now_utc=datetime(2026, 8, 13, 15, 1, 1, tzinfo=timezone.utc),
            )

    def test_global_writer_claim_must_match_visible_owner_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "identity-output"
            claim_path = root / "writer-claim.json"
            token = "a" * 32
            claim = {
                "schema": "trading_mvp_global_market_writer_claim_v1",
                "project": "trading_mvp",
                "status": "CLAIMED",
                "run_id": "slow_liquidity_official_asset_identity_verification_20260813_v1",
                "owner_pid": os.getpid(),
                "writer_pid": os.getpid(),
                "terminal_pid": os.getpid(),
                "owner_kind": "slow_liquidity_official_identity",
                "ownership_token": token,
                "plan_hash": PROPOSAL_HASH,
                "output_namespace": str(output.resolve()),
                "claimed_at_utc": "2026-08-13T14:20:00+00:00",
                "writer_attached_at_utc": "2026-08-13T14:20:01+00:00",
                "research_only": True,
                "live_orders": False,
                "private_api_keys": False,
                "real_capital": False,
                "leverage_or_margin": False,
            }
            write_json(claim_path, claim)

            validate_global_writer_claim(
                claim_path=claim_path,
                run_id=claim["run_id"],
                owner_pid=os.getpid(),
                writer_pid=os.getpid(),
                ownership_token=token,
                output_path=output,
            )
            with self.assertRaisesRegex(IdentityVerificationError, "token"):
                validate_global_writer_claim(
                    claim_path=claim_path,
                    run_id=claim["run_id"],
                    owner_pid=os.getpid(),
                    writer_pid=os.getpid(),
                    ownership_token="b" * 32,
                    output_path=output,
                )

    def test_execution_manifest_requires_separate_exact_approval(self) -> None:
        phase1 = {
            "schema": RUNTIME_MANIFEST_SCHEMA,
            "status": "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
            "manifest_hash": "1" * 64,
        }
        execution = {
            "schema": EXECUTION_MANIFEST_SCHEMA,
            "status": "NOT_APPROVED",
            "phase1_runtime_manifest": {
                "path": "C:/phase1.json",
                "file_sha256": "2" * 64,
                "manifest_hash": "1" * 64,
            },
            "execution_approval": None,
            "execution_authorized": False,
        }
        with self.assertRaisesRegex(IdentityVerificationError, "execution approval"):
            validate_execution_manifest(execution, phase1_manifest=phase1)

    def test_execution_manifest_rejects_runtime_minted_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            phase1, receipt, execution = self._execution_fixture(root)
            receipt["approval_provenance"]["runtime_minting_allowed"] = True
            receipt["receipt_hash"] = canonical_hash_without(receipt, "receipt_hash")
            receipt_path = root / "execution-receipt.json"
            write_json(receipt_path, receipt)
            execution["execution_approval"]["file_sha256"] = sha256(receipt_path)
            execution["execution_approval"]["receipt_hash"] = receipt["receipt_hash"]
            execution["manifest_hash"] = canonical_hash_without(execution, "manifest_hash")
            with self.assertRaisesRegex(IdentityVerificationError, "external manual"):
                validate_execution_manifest(
                    execution,
                    phase1_manifest=phase1,
                    approval_receipt_snapshot=receipt,
                    approval_receipt_file_sha256=sha256(receipt_path),
                )

    def test_execution_manifest_rejects_incomplete_exact_approval_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            phase1, receipt, execution = self._execution_fixture(root)
            receipt["user_approval_text"] = "разрешаю"
            receipt["receipt_hash"] = canonical_hash_without(receipt, "receipt_hash")
            receipt_path = root / "execution-receipt.json"
            write_json(receipt_path, receipt)
            execution["execution_approval"]["user_approval_text"] = "разрешаю"
            execution["execution_approval"]["file_sha256"] = sha256(receipt_path)
            execution["execution_approval"]["receipt_hash"] = receipt["receipt_hash"]
            execution["manifest_hash"] = canonical_hash_without(execution, "manifest_hash")
            with self.assertRaisesRegex(IdentityVerificationError, "does not bind"):
                validate_execution_manifest(
                    execution,
                    phase1_manifest=phase1,
                    approval_receipt_snapshot=receipt,
                    approval_receipt_file_sha256=sha256(receipt_path),
                )

    def test_snapshot_change_is_rejected_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime_path = root / "runtime.json"
            execution_path = root / "execution.json"
            receipt_path = root / "receipt.json"
            runtime_path.write_text("runtime", encoding="utf-8")
            execution_path.write_text("execution", encoding="utf-8")
            receipt_path.write_text("receipt", encoding="utf-8")
            snapshot = mock.Mock(
                runtime_manifest_path=runtime_path,
                runtime_manifest_file_sha256=sha256(runtime_path),
                execution_manifest_path=execution_path,
                execution_manifest_file_sha256=sha256(execution_path),
                execution_approval_receipt_path=receipt_path,
                execution_approval_receipt_file_sha256=sha256(receipt_path),
            )
            validate_execution_snapshot_files_unchanged(snapshot)
            execution_path.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(IdentityVerificationError, "changed after snapshot"):
                validate_execution_snapshot_files_unchanged(snapshot)

    def test_guard_requires_exact_execution_decision_and_readiness_binding(self) -> None:
        snapshot = mock.Mock(
            execution_manifest={
                "execution_approval": {"receipt_hash": "a" * 64},
            },
            execution_approval_receipt={
                "authoritative_guard_contract": {
                    "required_guard_decision": "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION",
                    "required_readiness_source_status": "IDENTITY_RUNTIME_FROZEN_WITH_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
                    "required_readiness_checkpoint_id": "slow_liquidity_identity_execution_phase_2",
                    "required_policy_file_sha256": "b" * 64,
                }
            },
            runtime_manifest_file_sha256="c" * 64,
            runtime_manifest={"manifest_hash": "d" * 64},
            execution_approval_receipt_file_sha256="e" * 64,
            request_plan=tuple(),
        )
        guard = {
            "status": "ACTIVE",
            "stop_new_actions": False,
            "decision": "AWAIT_EXACT_ONE_WEEK_EDGE_SPRINT_APPROVAL_CHECKPOINT",
            "policy_hash": "b" * 64,
            "usage": {
                "status": "AVAILABLE",
                "decision": "CONTINUE",
                "remaining_percent": 100.0,
            },
            "gate": {"status": "READY_FOR_POSTPROCESS"},
            "current_sprint_readiness": {},
        }
        with self.assertRaisesRegex(IdentityVerificationError, "exact execution decision"):
            validate_exact_guard_snapshot(guard, snapshot=snapshot)

    def test_direct_runtime_cli_blocks_without_launcher_capability_before_network(self) -> None:
        module = "trading_mvp.src.slow_liquidity_official_identity_verification"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                module,
                "--run-approved",
                "--runtime-manifest-path",
                "missing-runtime.json",
                "--execution-manifest-path",
                "missing-execution.json",
                "--output-path",
                "missing-output",
                "--global-writer-claim-path",
                "missing-claim.json",
                "--owner-pid",
                str(os.getpid()),
                "--ownership-token",
                "a" * 32,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(proc.stderr)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("visible launcher capability", payload["reason"])
        self.assertFalse(payload["network_accessed"])
        self.assertFalse(payload["identity_output_created"])

    def test_output_writer_is_immutable_and_persists_no_raw_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "identity-output"
            records = []
            for index, base in enumerate(BASES, start=1):
                identifier = f"0x{index:040x}"
                records.append(evidence_record(venue="mexc", base=base, identifier=identifier))
                records.append(evidence_record(venue="gateio", base=base, identifier=identifier))
            result = build_identity_result(records)

            written = write_identity_output(
                output_path=root,
                identity_result=result,
                run_id="slow_liquidity_official_asset_identity_verification_20260813_v1",
                proposal_hash=PROPOSAL_HASH,
                response_body_hashes=["a" * 64],
                generated_at_utc="2026-08-13T14:20:00Z",
                source_bindings=source_bindings(root),
            )

            self.assertEqual(set(written), {"identity-evidence.json", "manifest.json"})
            self.assertFalse(any("raw" in path.name.lower() for path in root.iterdir()))
            self.assertNotIn("raw_payload", (root / "identity-evidence.json").read_text())
            with self.assertRaisesRegex(IdentityVerificationError, "already exists"):
                write_identity_output(
                    output_path=root,
                    identity_result=result,
                    run_id="slow_liquidity_official_asset_identity_verification_20260813_v1",
                    proposal_hash=PROPOSAL_HASH,
                    response_body_hashes=["a" * 64],
                    generated_at_utc="2026-08-13T14:20:00Z",
                    source_bindings=source_bindings(root),
                )

    def test_output_writer_rejects_partial_or_free_form_source_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "identity-output"
            records = []
            for index, base in enumerate(BASES, start=1):
                identifier = f"0x{index:040x}"
                records.append(evidence_record(venue="mexc", base=base, identifier=identifier))
                records.append(evidence_record(venue="gateio", base=base, identifier=identifier))
            result = build_identity_result(records)
            partial = source_bindings(root)
            partial.pop("execution_approval_receipt")
            with self.assertRaisesRegex(IdentityVerificationError, "binding set"):
                write_identity_output(
                    output_path=root,
                    identity_result=result,
                    run_id="slow_liquidity_official_asset_identity_verification_20260813_v1",
                    proposal_hash=PROPOSAL_HASH,
                    response_body_hashes=["a" * 64],
                    generated_at_utc="2026-08-13T14:20:00Z",
                    source_bindings=partial,
                )

    def test_launcher_preflight_blocks_without_execution_manifest_and_writes_nothing(self) -> None:
        launcher = (
            REPO_ROOT / "tools/start_exact_approved_slow_liquidity_official_identity_visible.ps1"
        )
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "must-not-exist"
            command = [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(launcher),
                "-PreflightOnly",
                "-RuntimeManifestPath",
                str(Path(temp) / "missing-runtime.json"),
                "-ExecutionManifestPath",
                str(Path(temp) / "missing-execution.json"),
                "-OutputPath",
                str(output),
            ]
            proc = subprocess.run(command, capture_output=True, text=True, check=False)

            self.assertNotEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout)
            self.assertEqual(
                payload["status"],
                "BLOCKED_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
            )
            self.assertFalse(payload["network_accessed"])
            self.assertFalse(payload["identity_output_created"])
            self.assertFalse(output.exists())

    def test_launcher_default_binds_current_runtime_manifest_v4(self) -> None:
        launcher = (
            REPO_ROOT / "tools/start_exact_approved_slow_liquidity_official_identity_visible.ps1"
        )
        source = launcher.read_text(encoding="utf-8")

        self.assertIn(
            "slow-liquidity-official-identity-runtime-manifest-20260813-v4.json",
            source,
        )
        self.assertNotIn(
            "slow-liquidity-official-identity-runtime-manifest-20260813-v1.json",
            source,
        )


if __name__ == "__main__":
    unittest.main()
