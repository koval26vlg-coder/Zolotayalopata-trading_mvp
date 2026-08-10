from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from funding_unrestricted_identity_readiness import (  # noqa: E402
    BUNDLE_HASH_METHOD,
    EVIDENCE_BUNDLE_SCHEMA,
    IdentityReadinessError,
    build_identity_readiness,
    canonical_hash,
    write_identity_readiness,
)
from funding_unrestricted_metadata_discovery import (  # noqa: E402
    GATEIO_ENDPOINT,
    MEXC_ENDPOINT,
    build_provisional_ticker_candidates,
    project_gateio_active_contracts,
    project_mexc_active_contracts,
    write_immutable_discovery,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _identifier(
    value: str,
    *,
    namespace: str = "eip155:56/erc20",
    comparison: str = "ASCII_CASE_INSENSITIVE",
) -> dict[str, str]:
    return {
        "namespace": namespace,
        "value": value,
        "comparison": comparison,
    }


class FundingUnrestrictedIdentityReadinessTests(unittest.TestCase):
    @staticmethod
    def _build_discovery(root: Path, *, ticker: str = "AKE") -> Path:
        mexc = project_mexc_active_contracts(
            {
                "success": True,
                "code": 0,
                "data": [
                    {
                        "symbol": f"{ticker}_USDT",
                        "baseCoin": ticker,
                        "baseCoinName": "Akedo",
                        "quoteCoin": "USDT",
                        "quoteCoinName": "Tether",
                        "settleCoin": "USDT",
                        "state": 0,
                        "apiAllowed": True,
                    }
                ],
            }
        )
        gateio = project_gateio_active_contracts(
            [
                {
                    "name": f"{ticker}_USDT",
                    "status": "trading",
                    "type": "direct",
                    "in_delisting": False,
                }
            ]
        )
        candidates = build_provisional_ticker_candidates(mexc, gateio)
        output = root / "discovery"
        write_immutable_discovery(
            output,
            run_id="funding_identity_fixture",
            mexc_records=mexc,
            gateio_records=gateio,
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
        return output

    @staticmethod
    def _bundle(
        discovery_root: Path,
        *,
        identifier: dict[str, str] | None = None,
    ) -> dict[str, object]:
        contract = identifier or _identifier(
            "0x2c3a8Ee94dDD97244a93Bc48298f97d2C412F7Db"
        )
        manifest_sha256 = hashlib.sha256(
            (discovery_root / "manifest.json").read_bytes()
        ).hexdigest()
        payload: dict[str, object] = {
            "schema": EVIDENCE_BUNDLE_SCHEMA,
            "created_at_utc": "2026-08-10T00:10:00Z",
            "verification_scope": "identity_only_no_market_values",
            "research_only": True,
            "discovery_binding": {
                "run_id": "funding_identity_fixture",
                "manifest_file_sha256": manifest_sha256,
            },
            "assets": [
                {
                    "ticker": "AKE",
                    "asset_name": "Akedo",
                    "canonical_identifier": contract,
                    "venues": [
                        {
                            "venue": "mexc",
                            "instrument_id": "AKE_USDT",
                            "base_ticker": "AKE",
                            "market_type": "perpetual",
                            "observed_identifier": copy.deepcopy(contract),
                            "official_sources": [
                                {
                                    "url": "https://www.mexc.com/announcements/article/ake",
                                    "response_body_sha256": "1" * 64,
                                }
                            ],
                        },
                        {
                            "venue": "gateio",
                            "instrument_id": "AKE_USDT",
                            "base_ticker": "AKE",
                            "market_type": "perpetual",
                            "observed_identifier": copy.deepcopy(contract),
                            "official_sources": [
                                {
                                    "url": "https://www.gate.com/announcements/article/ake",
                                    "response_body_sha256": "2" * 64,
                                }
                            ],
                        },
                    ],
                }
            ],
            "safety": {
                "raw_payload_persisted": False,
                "funding_rates_read": False,
                "prices_read": False,
                "returns_or_pnl_computed": False,
                "oos_read": False,
                "collector_or_evaluator_run": False,
            },
            "bundle_hash_method": BUNDLE_HASH_METHOD,
        }
        payload["bundle_hash"] = canonical_hash(payload)
        return payload

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _readiness(
        self,
        discovery: Path,
        bundle_path: Path,
        *,
        expected_discovery_manifest_sha256: str | None = None,
    ) -> dict[str, object]:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        return build_identity_readiness(
            discovery,
            bundle_path,
            expected_discovery_manifest_sha256=(
                expected_discovery_manifest_sha256
                or self._sha256(discovery / "manifest.json")
            ),
            expected_proposal_hash="c" * 64,
            expected_receipt_hash="d" * 64,
            expected_runtime_manifest_hash="e" * 64,
            expected_identity_bundle_file_sha256=self._sha256(bundle_path),
            expected_identity_bundle_hash=str(bundle["bundle_hash"]),
        )

    def _write_readiness(
        self,
        discovery: Path,
        bundle_path: Path,
        output: Path,
    ) -> dict[str, object]:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        return write_identity_readiness(
            discovery,
            bundle_path,
            output,
            expected_discovery_manifest_sha256=self._sha256(
                discovery / "manifest.json"
            ),
            expected_proposal_hash="c" * 64,
            expected_receipt_hash="d" * 64,
            expected_runtime_manifest_hash="e" * 64,
            expected_identity_bundle_file_sha256=self._sha256(bundle_path),
            expected_identity_bundle_hash=str(bundle["bundle_hash"]),
        )

    def test_valid_bundle_is_ready_for_exact_review_but_never_authorizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))

            report = self._readiness(discovery, bundle_path)

        self.assertEqual(
            report["status"],
            "IDENTITY_CLAIM_BUNDLE_STRUCTURALLY_VALID_AWAIT_SOURCE_CONTENT_REVIEW",
        )
        self.assertEqual(report["candidate_summary"]["discovered"], 1)
        self.assertEqual(report["candidate_summary"]["structurally_complete_claims"], 1)
        self.assertEqual(
            report["candidates"][0]["identity_status"],
            "HASH_BOUND_IDENTITY_CLAIM_AWAIT_SOURCE_CONTENT_REVIEW",
        )
        self.assertFalse(report["candidates"][0]["same_underlying_verified"])
        self.assertFalse(report["authorization"]["candidate_planonly_creation"])
        self.assertFalse(report["authorization"]["data_collection"])
        self.assertFalse(report["source_review"]["source_content_validated"])
        self.assertFalse(report["source_review"]["same_underlying_accepted"])
        self.assertFalse(report["safety"]["funding_rates_read"])
        self.assertFalse(report["safety"]["prices_read"])

    def test_missing_asset_evidence_remains_unresolved_without_category_exclusion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(discovery)
            bundle["assets"] = []
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            report = self._readiness(discovery, bundle_path)

        self.assertEqual(report["status"], "NO_COMPLETE_IDENTITY_CLAIM")
        self.assertEqual(report["candidate_summary"]["unresolved"], 1)
        self.assertEqual(
            report["candidates"][0]["identity_status"],
            "UNRESOLVED_REQUIRES_OFFICIAL_EVIDENCE",
        )
        self.assertEqual(report["universe_policy"]["category_exclusions"], [])

    def test_candidate_list_must_equal_full_metadata_ticker_intersection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            candidates_path = discovery / "provisional-shared-ticker-candidates.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates["candidate_count"] = 0
            candidates["candidates"] = []
            _write_json(candidates_path, candidates)
            manifest_path = discovery / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["projected_outputs"][candidates_path.name] = {
                "sha256": self._sha256(candidates_path),
                "bytes": candidates_path.stat().st_size,
            }
            manifest["contract_counts"]["provisional_shared_tickers"] = 0
            _write_json(manifest_path, manifest)
            bundle_path = root / "identity-bundle.json"
            bundle = self._bundle(discovery)
            bundle["assets"] = []
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            _write_json(bundle_path, bundle)

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "candidate set does not equal full metadata ticker intersection",
            ):
                self._readiness(discovery, bundle_path)

    def test_discovery_manifest_must_match_external_trusted_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "discovery manifest does not match trusted SHA-256",
            ):
                self._readiness(
                    discovery,
                    bundle_path,
                    expected_discovery_manifest_sha256="f" * 64,
                )

    def test_case_sensitive_identifier_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(
                discovery,
                identifier=_identifier(
                    "solana:mainnet/spl:SoLCaseSensitiveId",
                    namespace="caip19",
                    comparison="EXACT",
                ),
            )
            bundle["assets"][0]["venues"][1]["observed_identifier"]["value"] = (
                "solana:mainnet/spl:solcasesensitiveid"
            )
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            report = self._readiness(discovery, bundle_path)

        self.assertEqual(report["candidate_summary"]["structurally_complete_claims"], 0)
        self.assertIn(
            "gateio_identifier_mismatch",
            report["candidates"][0]["reason_codes"],
        )

    def test_case_insensitive_mode_is_rejected_for_non_evm_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(
                discovery,
                identifier=_identifier(
                    "solana:mainnet/spl:SoLCaseSensitiveId",
                    namespace="caip19",
                    comparison="ASCII_CASE_INSENSITIVE",
                ),
            )
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "non-EVM identifier must use EXACT comparison",
            ):
                self._readiness(discovery, bundle_path)

    def test_numeric_sha_and_identifier_types_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(discovery)
            bundle["assets"][0]["venues"][0]["official_sources"][0][
                "response_body_sha256"
            ] = int("1" * 64)
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "numeric-sha-bundle.json"
            _write_json(bundle_path, bundle)

            report = self._readiness(discovery, bundle_path)
            self.assertIn(
                "mexc_official_source_invalid",
                report["candidates"][0]["reason_codes"],
            )

            bundle = self._bundle(discovery)
            bundle["assets"][0]["canonical_identifier"]["value"] = 123
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "numeric-identifier-bundle.json"
            _write_json(bundle_path, bundle)
            with self.assertRaisesRegex(
                IdentityReadinessError,
                "identifier fields must be strings",
            ):
                self._readiness(discovery, bundle_path)

    def test_numeric_ticker_and_asset_name_types_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            candidates_path = discovery / "provisional-shared-ticker-candidates.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates["candidates"][0]["ticker"] = 123
            _write_json(candidates_path, candidates)
            manifest_path = discovery / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["projected_outputs"][candidates_path.name] = {
                "sha256": self._sha256(candidates_path),
                "bytes": candidates_path.stat().st_size,
            }
            _write_json(manifest_path, manifest)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "candidate 0 ticker fields must be strings",
            ):
                self._readiness(discovery, bundle_path)

            discovery = self._build_discovery(root / "second")
            bundle = self._bundle(discovery)
            bundle["assets"][0]["asset_name"] = 123
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "numeric-name-bundle.json"
            _write_json(bundle_path, bundle)
            with self.assertRaisesRegex(
                IdentityReadinessError,
                "identity asset AKE name must be a string",
            ):
                self._readiness(discovery, bundle_path)

    def test_namespace_must_be_canonical_lowercase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(discovery)
            for asset in bundle["assets"]:
                asset["canonical_identifier"]["namespace"] = "EIP155:56/erc20"
                for venue in asset["venues"]:
                    venue["observed_identifier"]["namespace"] = "EIP155:56/erc20"
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "namespace must be canonical lowercase",
            ):
                self._readiness(discovery, bundle_path)

    def test_evm_identifier_comparison_is_explicitly_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(discovery)
            bundle["assets"][0]["venues"][0]["observed_identifier"]["value"] = (
                "0X2C3A8EE94DDD97244A93BC48298F97D2C412F7DB"
            )
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            report = self._readiness(discovery, bundle_path)

        self.assertEqual(report["candidate_summary"]["structurally_complete_claims"], 1)

    def test_unofficial_venue_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(discovery)
            bundle["assets"][0]["venues"][0]["official_sources"][0]["url"] = (
                "https://example.com/ake"
            )
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            report = self._readiness(discovery, bundle_path)

        self.assertEqual(report["candidate_summary"]["structurally_complete_claims"], 0)
        self.assertIn(
            "mexc_official_source_invalid",
            report["candidates"][0]["reason_codes"],
        )

    def test_instrument_binding_must_match_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(discovery)
            bundle["assets"][0]["venues"][1]["instrument_id"] = "OTHER_USDT"
            bundle["bundle_hash"] = canonical_hash(
                {key: value for key, value in bundle.items() if key != "bundle_hash"}
            )
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            report = self._readiness(discovery, bundle_path)

        self.assertIn(
            "gateio_instrument_mismatch",
            report["candidates"][0]["reason_codes"],
        )

    def test_discovery_projection_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))
            candidate_path = discovery / "provisional-shared-ticker-candidates.json"
            candidate_path.write_bytes(
                candidate_path.read_bytes().replace(
                    b"UNRESOLVED_TICKER_MATCH_ONLY",
                    b"XNRESOLVED_TICKER_MATCH_ONLY",
                    1,
                )
            )

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "projected output SHA-256 mismatch",
            ):
                self._readiness(discovery, bundle_path)

    def test_rehashed_inactive_discovery_contract_is_rejected_semantically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            mexc_path = discovery / "mexc-active-contracts.json"
            mexc = json.loads(mexc_path.read_text(encoding="utf-8"))
            mexc["records"][0]["state"] = 1
            _write_json(mexc_path, mexc)
            manifest_path = discovery / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["projected_outputs"]["mexc-active-contracts.json"] = {
                "sha256": hashlib.sha256(mexc_path.read_bytes()).hexdigest(),
                "bytes": mexc_path.stat().st_size,
            }
            _write_json(manifest_path, manifest)
            bundle = self._bundle(discovery)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "MEXC record 0 is not an active USDT contract",
            ):
                self._readiness(discovery, bundle_path)

    def test_rehashed_nonofficial_discovery_endpoint_is_rejected_semantically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            gate_path = discovery / "gateio-active-contracts.json"
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            gate["endpoint_url"] = "https://example.com/contracts"
            _write_json(gate_path, gate)
            manifest_path = discovery / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["projected_outputs"]["gateio-active-contracts.json"] = {
                "sha256": hashlib.sha256(gate_path.read_bytes()).hexdigest(),
                "bytes": gate_path.stat().st_size,
            }
            _write_json(manifest_path, manifest)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "gateio metadata endpoint mismatch",
            ):
                self._readiness(discovery, bundle_path)

    def test_rehashed_metadata_boolean_type_confusion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            mexc_path = discovery / "mexc-active-contracts.json"
            mexc = json.loads(mexc_path.read_text(encoding="utf-8"))
            mexc["records"][0]["apiAllowed"] = 1
            _write_json(mexc_path, mexc)
            manifest_path = discovery / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["projected_outputs"][mexc_path.name] = {
                "sha256": self._sha256(mexc_path),
                "bytes": mexc_path.stat().st_size,
            }
            _write_json(manifest_path, manifest)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "MEXC record 0 is not an active USDT contract",
            ):
                self._readiness(discovery, bundle_path)

    def test_extra_file_inside_discovery_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))
            (discovery / "unexpected.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "discovery root file set mismatch",
            ):
                self._readiness(discovery, bundle_path)

    def test_bundle_hash_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle = self._bundle(discovery)
            bundle["assets"][0]["asset_name"] = "Tampered"
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, bundle)

            with self.assertRaisesRegex(IdentityReadinessError, "bundle hash mismatch"):
                self._readiness(discovery, bundle_path)

    def test_readiness_report_is_immutable_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))
            output = root / "readiness.json"

            first = self._write_readiness(discovery, bundle_path, output)
            second = self._write_readiness(discovery, bundle_path, output)
            persisted = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(first, second)
        self.assertEqual(persisted, first)
        self.assertEqual(
            first["readiness_hash"],
            canonical_hash(
                {key: value for key, value in first.items() if key != "readiness_hash"}
            ),
        )

    def test_output_cannot_be_written_inside_discovery_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery = self._build_discovery(root)
            bundle_path = root / "identity-bundle.json"
            _write_json(bundle_path, self._bundle(discovery))

            with self.assertRaisesRegex(
                IdentityReadinessError,
                "output must be outside immutable discovery root",
            ):
                self._write_readiness(
                    discovery,
                    bundle_path,
                    discovery / "readiness.json",
                )


if __name__ == "__main__":
    unittest.main()
