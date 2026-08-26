from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "trading_mvp"
    / "src"
    / "funding_unrestricted_metadata_discovery_proposal.py"
)


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> dict[str, Path]:
    policy_path = root / "funding-policy.json"
    policy = {
        "schema": "trading_mvp_funding_asset_universe_policy_v1",
        "status": "ACTIVE_FOR_NEW_FUNDING_PLANONLY_CONTRACTS",
        "scope": "FUNDING_STRATEGIES_ONLY",
        "asset_universe": {
            "mode": "ALL_ASSETS_WITHOUT_CATEGORY_EXCLUSIONS",
            "whitelist_required": False,
            "blacklisted_symbols": [],
            "blacklisted_categories": [],
            "binance_listing_status_filter": "NONE",
            "category_filters": {
                "exclude_binance_listed": False,
                "exclude_stablecoins": False,
                "exclude_memecoins": False,
            },
        },
        "candidate_eligibility_gates": {
            "official_identity": "EXACT_SAME_UNDERLYING_VERIFIED_PER_VENUE",
            "ticker_text_alone_is_identity_evidence": False,
        },
        "current_venue_scope": ["mexc", "gateio"],
        "authorization": {
            "candidate_discovery_on_pre_oos_data": True,
            "official_identity_metadata_verification": True,
            "oos_market_value_read": False,
            "evaluator_or_collector_launch": False,
        },
        "policy_hash_method": "sha256_canonical_json_excluding_policy_hash",
    }
    policy["policy_hash"] = _canonical_hash(policy)
    _write_json(policy_path, policy)

    audit_path = root / "cache-audit.json"
    audit_core = {
        "pair_summary_sha256": "1" * 64,
        "dataset_path": str(root / "top-200-cache"),
        "manifest_sha256": "2" * 64,
        "cost_contract_proposal_sha256": "3" * 64,
        "cost_contract_proposal_hash": "4" * 64,
        "universe_policy_sha256": _sha256(policy_path),
        "universe_policy_hash": policy["policy_hash"],
        "pair_summary_analysis_as_of_utc": "2026-07-21T00:00:00+00:00",
        "pre_oos_cutoff_utc": "2026-07-21T00:00:00+00:00",
        "cached_assets_analyzed": 108,
        "oos_horizon_days": 20,
        "minimum_assets_required": 4,
        "normal_cycle_cost_bps": 78.0,
        "stress_cycle_cost_bps": 116.0,
        "stress_favorable_funding_haircut": 0.5,
        "normal_positive_at_oos_horizon": 11,
        "stress_positive_at_oos_horizon": 2,
        "minimum_horizon_days_for_required_assets": 29,
        "candidate_upper_bounds": [],
        "decision": "CURRENT_CACHE_FIXED_HOLD_STRESS_INSUFFICIENT",
        "fixed_hold_planonly_allowed_from_current_cache": False,
        "complete_unrestricted_universe_or_longer_oos_required": True,
        "blocking_reasons": [
            "the cached universe is not proven to contain every MEXC/Gate funding asset"
        ],
    }
    audit = {
        "schema": "trading_mvp_funding_unrestricted_cache_feasibility_v1",
        "created_at_utc": "2026-08-10T08:00:00+00:00",
        "audit_passed": True,
        **audit_core,
        "deterministic_result_hash": _canonical_hash(audit_core),
        "data_access_audit": {
            "raw_market_rows_read": False,
            "oos_values_read": False,
            "returns_or_pnl_computed": False,
            "network_market_data_accessed": False,
            "collector_run": False,
            "evaluator_run": False,
            "grid_or_retune_run": False,
        },
    }
    _write_json(audit_path, audit)

    return {
        "policy": policy_path,
        "audit": audit_path,
        "output": root / "proposal.json",
    }


def _run(paths: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--universe-policy",
            str(paths["policy"]),
            "--expected-universe-policy-sha256",
            _sha256(paths["policy"]),
            "--cache-audit",
            str(paths["audit"]),
            "--expected-cache-audit-sha256",
            _sha256(paths["audit"]),
            "--generated-at-utc",
            "2026-08-10T08:30:00Z",
            "--out",
            str(paths["output"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


class FundingUnrestrictedMetadataDiscoveryProposalTests(unittest.TestCase):
    def test_builds_all_asset_fail_closed_metadata_discovery_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            completed = _run(paths)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            proposal = json.loads(paths["output"].read_text(encoding="utf-8"))
            scope = proposal["discovery_contract"]["instrument_scope"]
            exclusions = proposal["discovery_contract"]["exclusion_contract"]
            endpoints = proposal["discovery_contract"]["endpoint_allowlist"]

            self.assertEqual(proposal["status"], "AWAIT_EXACT_HASH_BOUND_APPROVAL")
            self.assertTrue(scope["all_active_contracts_per_venue"])
            self.assertTrue(scope["all_shared_ticker_candidates"])
            self.assertIsNone(scope["maximum_candidates"])
            self.assertFalse(exclusions["top_n_filter_allowed"])
            self.assertFalse(exclusions["binance_status_filter_allowed"])
            self.assertFalse(exclusions["asset_category_filter_allowed"])
            self.assertEqual(
                {(row["venue"], row["path"]) for row in endpoints},
                {
                    ("mexc", "/api/v1/contract/detail"),
                    ("gateio", "/api/v4/futures/usdt/contracts"),
                },
            )
            self.assertEqual(proposal["runtime_contract"]["max_runtime_sec"], 300)
            self.assertEqual(proposal["runtime_contract"]["hard_output_cap_bytes"], 50_000_000)
            self.assertTrue(proposal["runtime_contract"]["visible_terminal_required"])
            self.assertFalse(proposal["authorization"]["actual_network_run_allowed"])
            self.assertFalse(proposal["authorization"]["oos_market_value_read_allowed"])
            self.assertTrue(
                proposal["next_checkpoint"]["separate_exact_candidate_planonly_required"]
            )
            self.assertEqual(
                proposal["identity_contract"]["ticker_match_disposition"],
                "PROVISIONAL_CANDIDATE_ONLY_NOT_IDENTITY_EVIDENCE",
            )

            expected_hash = proposal.pop("proposal_hash")
            self.assertEqual(
                proposal["proposal_hash_method"],
                "sha256_canonical_json_excluding_proposal_hash",
            )
            self.assertEqual(expected_hash, _canonical_hash(proposal))

    def test_rejects_a_validly_rehashed_policy_with_any_category_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            policy = json.loads(paths["policy"].read_text(encoding="utf-8"))
            policy["asset_universe"]["category_filters"]["exclude_memecoins"] = True
            policy.pop("policy_hash")
            policy["policy_hash"] = _canonical_hash(policy)
            _write_json(paths["policy"], policy)

            completed = _run(paths)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(paths["output"].exists())
            self.assertIn("category filter", completed.stderr)

    def test_rejects_tampered_cache_audit_deterministic_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            audit = json.loads(paths["audit"].read_text(encoding="utf-8"))
            audit["cached_assets_analyzed"] = 999
            _write_json(paths["audit"], audit)

            completed = _run(paths)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(paths["output"].exists())
            self.assertIn("deterministic_result_hash mismatch", completed.stderr)

    def test_existing_output_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            paths["output"].write_text("sentinel", encoding="utf-8")

            completed = _run(paths)

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(paths["output"].read_text(encoding="utf-8"), "sentinel")
            self.assertIn("already exists", completed.stderr)


if __name__ == "__main__":
    unittest.main()
