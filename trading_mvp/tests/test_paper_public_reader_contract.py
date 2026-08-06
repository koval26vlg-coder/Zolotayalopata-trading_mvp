from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_public_reader_contract as reader  # noqa: E402


def _fixture_files(root: Path) -> tuple[Path, Path, Path]:
    funding = root / "funding.py"
    observer = root / "observer.py"
    evidence = root / "reliability.json"
    funding.write_text("funding fixture\n", encoding="utf-8")
    observer.write_text("observer fixture\n", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_venue_api_reliability_evidence_v1",
                "scope": {
                    "venues": ["mexc", "gateio"],
                    "private_api_keys": False,
                    "live_orders": False,
                },
                "historical_rest_collect": {"completion_rate": 1.0},
                "pit_snapshot_collect": {
                    "aggregate": {"dual_venue_success_rate": 1.0}
                },
                "verdict": "RESEARCH_DATA_PATH_RELIABLE_WITH_GUARDS_PRODUCTION_SLA_UNPROVEN",
            }
        ),
        encoding="utf-8",
    )
    return funding, observer, evidence


def _contract(root: Path) -> dict:
    funding, observer, evidence = _fixture_files(root)
    return reader.build_public_reader_contract(
        funding_client_path=funding,
        observer_runtime_path=observer,
        reliability_evidence_path=evidence,
        generated_at_utc="2026-07-28T19:30:00+00:00",
    )


def _migration_files(root: Path) -> tuple[Path, Path]:
    depth_reference = root / "pit_universe_public_probe.py"
    depth_reference.write_text(
        "def parse_mexc_depth_l1(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    errors_path = root / "errors.jsonl"
    errors_path.write_text(
        json.dumps(
            {
                "cycle_index": 0,
                "venue": "mexc",
                "category": "schema_mismatch",
                "endpoint_id": "mexc_tickers",
                "detail": "missing required fields: bid1, ask1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    deterministic = {
        "schema": "trading_mvp_paper_public_readonly_probe_result_v1",
        "run_id": "paper_public_readonly_probe_20260730_142851",
        "status": "STOPPED_INCOMPLETE",
        "final": False,
        "plan": {
            "plan_hash_sha256": (
                "318c6dbd76777cc4cff8f8e4e0ec67df"
                "10b497b33709155c642d2476285527ff"
            )
        },
        "quality": {"hard_stop_reason": "schema_mismatch"},
        "artifacts": {
            "errors_path": str(errors_path.resolve()),
            "errors_file_sha256": reader.sha256_file(errors_path),
        },
        "safety": {
            "public_get_only": True,
            "returns_or_pnl_read": False,
            "signals_read": False,
            "oms_mutations": 0,
            "private_api_keys": False,
            "live_orders": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
            "hypothesis_changed": False,
        },
    }
    manifest = {
        **deterministic,
        "deterministic_result_hash": reader.sha256_json(deterministic),
        "started_at_utc": "2026-07-30T11:28:51+00:00",
        "completed_at_utc": "2026-07-30T11:28:52+00:00",
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path, depth_reference


def _contract_v2(root: Path) -> dict:
    funding, observer, evidence = _fixture_files(root)
    manifest, depth_reference = _migration_files(root)
    return reader.build_public_reader_contract(
        funding_client_path=funding,
        observer_runtime_path=observer,
        reliability_evidence_path=evidence,
        contract_version="v2",
        migration_probe_manifest_path=manifest,
        depth_reference_path=depth_reference,
        generated_at_utc="2026-07-30T15:00:00+00:00",
    )


class PaperPublicReaderContractTests(unittest.TestCase):
    def test_contract_is_get_only_and_no_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = reader.validate_public_reader_contract(
                _contract(Path(tmp))
            )
        self.assertEqual(contract["scope"]["methods"], ["GET"])
        self.assertEqual(
            contract["scope"]["network_requests_performed_while_building"], 0
        )
        self.assertFalse(contract["safety"]["private_api_keys"])
        self.assertFalse(contract["safety"]["live_orders"])
        self.assertEqual(
            {item["request_schema"]["method"] for venue in contract["venues"].values() for item in venue["endpoints"]},
            {"GET"},
        )

    def test_endpoint_schema_hashes_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract(Path(tmp))
        for venue in contract["venues"].values():
            for endpoint in venue["endpoints"]:
                expected = reader.sha256_json(
                    {
                        "request_schema": endpoint["request_schema"],
                        "response_schema": endpoint["response_schema"],
                    }
                )
                self.assertEqual(endpoint["schema_hash_sha256"], expected)

    def test_rehashed_contract_cannot_enable_post_or_unknown_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract(Path(tmp))
        contract["venues"]["mexc"]["endpoints"][0]["request_schema"][
            "method"
        ] = "POST"
        contract["contract_hash_sha256"] = reader.contract_hash(contract)
        with self.assertRaisesRegex(ValueError, "endpoint definitions"):
            reader.validate_public_reader_contract(contract)

    def test_authorizes_exact_mexc_and_gate_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract(Path(tmp))
        mexc = reader.authorize_public_get(
            contract,
            venue="mexc",
            method="GET",
            url="https://contract.mexc.com/api/v1/contract/depth/HYPE_USDT",
            params={"limit": 20},
            headers={"Accept": "application/json"},
        )
        gate = reader.authorize_public_get(
            contract,
            venue="gateio",
            method="GET",
            url="https://api.gateio.ws/api/v4/futures/usdt/funding_rate",
            params={"contract": "HYPE_USDT", "limit": 100},
        )
        self.assertEqual(mexc["endpoint_id"], "mexc_depth")
        self.assertEqual(gate["endpoint_id"], "gateio_funding")
        self.assertFalse(mexc["network_request_performed"])

    def test_rejects_non_get_foreign_host_and_unknown_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract(Path(tmp))
        with self.assertRaisesRegex(ValueError, "only public GET"):
            reader.authorize_public_get(
                contract,
                venue="mexc",
                method="POST",
                url="https://contract.mexc.com/api/v1/contract/detail",
            )
        with self.assertRaisesRegex(ValueError, "host"):
            reader.authorize_public_get(
                contract,
                venue="mexc",
                method="GET",
                url="https://evil.example/api/v1/contract/detail",
            )
        with self.assertRaisesRegex(ValueError, "path"):
            reader.authorize_public_get(
                contract,
                venue="gateio",
                method="GET",
                url="https://api.gateio.ws/api/v4/futures/usdt/orders",
            )

    def test_rejects_private_headers_and_signed_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract(Path(tmp))
        with self.assertRaisesRegex(ValueError, "header"):
            reader.authorize_public_get(
                contract,
                venue="mexc",
                method="GET",
                url="https://contract.mexc.com/api/v1/contract/detail",
                headers={"X-MEXC-APIKEY": "secret"},
            )
        with self.assertRaisesRegex(ValueError, "query"):
            reader.authorize_public_get(
                contract,
                venue="gateio",
                method="GET",
                url="https://api.gateio.ws/api/v4/futures/usdt/contracts",
                params={"signature": "secret"},
            )

    def test_rejects_bad_symbol_limit_and_embedded_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract(Path(tmp))
        with self.assertRaisesRegex(ValueError, "symbol"):
            reader.authorize_public_get(
                contract,
                venue="gateio",
                method="GET",
                url="https://api.gateio.ws/api/v4/futures/usdt/order_book",
                params={"contract": "../BTC_USDT", "limit": 20},
            )
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            reader.authorize_public_get(
                contract,
                venue="mexc",
                method="GET",
                url="https://contract.mexc.com/api/v1/contract/depth/HYPE_USDT",
                params={"limit": 100},
            )
        with self.assertRaisesRegex(ValueError, "embedded URL query"):
            reader.authorize_public_get(
                contract,
                venue="gateio",
                method="GET",
                url="https://api.gateio.ws/api/v4/futures/usdt/contracts?limit=1",
            )

    def test_reliability_scope_cannot_claim_production_sla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract(Path(tmp))
        self.assertEqual(
            contract["reliability_evidence"]["production_sla"], "UNPROVEN"
        )
        tampered = deepcopy(contract)
        tampered["reliability_evidence"]["production_sla"] = "PROVEN"
        tampered["contract_hash_sha256"] = reader.contract_hash(tampered)
        with self.assertRaisesRegex(ValueError, "production SLA"):
            reader.validate_public_reader_contract(tampered)

    def test_v2_moves_mexc_bbo_to_depth_without_changing_output_schema(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = reader.validate_public_reader_contract(
                _contract_v2(Path(tmp))
            )
        mexc = contract["venues"]["mexc"]["endpoints"]
        ticker = next(
            item for item in mexc if item["endpoint_id"] == "mexc_tickers"
        )
        depth = next(
            item for item in mexc if item["endpoint_id"] == "mexc_depth"
        )
        self.assertEqual(
            ticker["response_schema"]["item_required"],
            ["symbol", "fairPrice", "indexPrice", "timestamp"],
        )
        self.assertEqual(
            depth["response_schema"]["item_required"],
            ["bids", "asks", "timestamp"],
        )
        self.assertEqual(
            contract["normalization_contract"]["output_schema"],
            "trading_mvp_public_market_snapshot_v1",
        )
        self.assertEqual(
            contract["normalization_contract"]["bbo_sources"]["mexc"],
            "mexc_depth_l1",
        )
        self.assertFalse(
            contract["migration_evidence"]["approved_change"][
                "economic_contract_changed"
            ]
        )

    def test_v2_rejects_rehashed_migration_scope_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _contract_v2(Path(tmp))
            contract["migration_evidence"]["approved_change"][
                "mexc_bbo_after"
            ] = "another endpoint"
            contract["contract_hash_sha256"] = reader.contract_hash(contract)
            with self.assertRaisesRegex(
                ValueError,
                "migration evidence changed",
            ):
                reader.validate_public_reader_contract(contract)

    def test_cli_writes_immutable_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            funding, observer, evidence = _fixture_files(root)
            output = root / "contract.json"
            self.assertEqual(
                reader.main(
                    [
                        "--funding-client",
                        str(funding),
                        "--observer-runtime",
                        str(observer),
                        "--reliability-evidence",
                        str(evidence),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            reader.validate_public_reader_contract(
                json.loads(output.read_text(encoding="utf-8"))
            )
            with self.assertRaises(FileExistsError):
                reader.main(
                    [
                        "--funding-client",
                        str(funding),
                        "--observer-runtime",
                        str(observer),
                        "--reliability-evidence",
                        str(evidence),
                        "--output",
                        str(output),
                    ]
                )


if __name__ == "__main__":
    unittest.main()
