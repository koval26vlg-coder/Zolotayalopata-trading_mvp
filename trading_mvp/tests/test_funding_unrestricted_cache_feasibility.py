from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "trading_mvp" / "src" / "funding_unrestricted_cache_feasibility.py"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _fixture(root: Path, daily_spreads_bps: list[float]) -> dict[str, Path]:
    end_sec = 1_785_000_000
    manifest = root / "run" / "manifest.json"
    _write_json(
        manifest,
        {
            "schema": "daily_collect_v1",
            "params": {"end_sec": end_sec},
            "universe": [],
        },
    )

    pair_summary = root / "pairs.json"
    _write_json(
        pair_summary,
        {
            "schema": "funding_pairs_v2",
            "dataset": str(manifest.parent),
            "params": {
                "non_binance_only": False,
                "analysis_as_of_ts": float(end_sec),
                "analysis_as_of_utc": datetime.fromtimestamp(end_sec, timezone.utc).isoformat(),
                "analysis_as_of_source": "manifest.params.end_sec",
            },
            "shared_symbols_before_non_binance_filter": len(daily_spreads_bps),
            "shared_symbols_total": len(daily_spreads_bps),
            "pairs_analyzed": len(daily_spreads_bps),
            "pairs": [
                {
                    "base": f"ASSET{index}",
                    "symbol": f"ASSET{index}_USDT",
                    "spread_gate_minus_mexc": {
                        "mean_daily_spread_bps": daily_spread,
                    },
                }
                for index, daily_spread in enumerate(daily_spreads_bps, start=1)
            ],
        },
    )

    proposal = root / "legacy-cost-contract.json"
    cutoff = datetime.fromtimestamp(end_sec + 3600, timezone.utc).isoformat()
    proposal_payload = {
        "schema": "trading_mvp_funding_spread_daily_hold_planonly_proposal_v1",
        "chronological_oos": {
            "pre_oos_cutoff_utc": cutoff,
            "complete_utc_days": 20,
        },
        "economics_contract": {
            "normal_cycle_cost_bps_per_asset_fold": 78.0,
            "stress_cycle_cost_bps_per_asset_fold": 116.0,
            "stress_favorable_funding_haircut": 0.5,
        },
        "validation_contract": {
            "pre_oos_gates": {"minimum_verified_source_complete_assets": 4}
        },
        "proposal_hash_method": "sha256_canonical_json_excluding_proposal_hash",
    }
    proposal_payload["proposal_hash"] = _canonical_hash(proposal_payload)
    _write_json(proposal, proposal_payload)

    policy = root / "policy.json"
    policy_payload = {
        "schema": "trading_mvp_funding_asset_universe_policy_v1",
        "scope": "FUNDING_STRATEGIES_ONLY",
        "asset_universe": {"mode": "ALL_ASSETS_WITHOUT_CATEGORY_EXCLUSIONS"},
        "current_venue_scope": ["mexc", "gateio"],
        "policy_hash_method": "sha256_canonical_json_excluding_policy_hash",
    }
    policy_payload["policy_hash"] = _canonical_hash(policy_payload)
    _write_json(policy, policy_payload)

    return {
        "manifest": manifest,
        "pairs": pair_summary,
        "proposal": proposal,
        "policy": policy,
        "output": root / "audit.json",
    }


def _run(paths: dict[str, Path], *, pair_sha: str | None = None):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pair-summary",
            str(paths["pairs"]),
            "--expected-pair-summary-sha256",
            pair_sha or _sha(paths["pairs"]),
            "--manifest",
            str(paths["manifest"]),
            "--expected-manifest-sha256",
            _sha(paths["manifest"]),
            "--cost-contract-proposal",
            str(paths["proposal"]),
            "--expected-cost-contract-proposal-sha256",
            _sha(paths["proposal"]),
            "--universe-policy",
            str(paths["policy"]),
            "--expected-universe-policy-sha256",
            _sha(paths["policy"]),
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


class FundingUnrestrictedCacheFeasibilityTests(unittest.TestCase):
    def test_rejects_current_cache_upper_bound_when_four_assets_need_more_than_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp), [15.0, 12.0, 10.0, 8.0])
            completed = _run(paths)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))
            self.assertEqual(
                audit["decision"],
                "CURRENT_CACHE_FIXED_HOLD_STRESS_INSUFFICIENT",
            )
            self.assertTrue(audit["audit_passed"])
            self.assertEqual(audit["stress_positive_at_oos_horizon"], 2)
            self.assertEqual(audit["minimum_assets_required"], 4)
            self.assertEqual(audit["minimum_horizon_days_for_required_assets"], 29)
            self.assertFalse(audit["fixed_hold_planonly_allowed_from_current_cache"])
            self.assertTrue(audit["complete_unrestricted_universe_or_longer_oos_required"])
            self.assertFalse(audit["data_access_audit"]["raw_market_rows_read"])
            self.assertFalse(audit["data_access_audit"]["oos_values_read"])
            self.assertFalse(audit["data_access_audit"]["returns_or_pnl_computed"])

    def test_allows_planonly_design_when_upper_bound_has_four_stress_positive_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp), [20.0, 18.0, 15.0, 12.0])
            completed = _run(paths)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))
            self.assertEqual(audit["decision"], "CURRENT_CACHE_FIXED_HOLD_PRE_OOS_FEASIBLE")
            self.assertTrue(audit["fixed_hold_planonly_allowed_from_current_cache"])
            self.assertEqual(audit["stress_positive_at_oos_horizon"], 4)

    def test_pair_summary_hash_mismatch_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp), [20.0, 18.0, 15.0, 12.0])
            completed = _run(paths, pair_sha="0" * 64)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(paths["output"].exists())
            self.assertIn("pair summary SHA-256 mismatch", completed.stderr)

    def test_pair_summary_dataset_must_match_manifest_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp), [20.0, 18.0, 15.0, 12.0])
            pairs = json.loads(paths["pairs"].read_text(encoding="utf-8"))
            pairs["dataset"] = str(Path(tmp) / "different-run")
            _write_json(paths["pairs"], pairs)

            completed = _run(paths)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(paths["output"].exists())
            self.assertIn("dataset does not match manifest parent", completed.stderr)


if __name__ == "__main__":
    unittest.main()
