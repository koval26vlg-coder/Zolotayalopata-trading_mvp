from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "trading_mvp" / "src" / "funding_daily_hold_proposal_audit.py"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fixture(root: Path, daily_spreads_bps: list[float]) -> tuple[Path, Path]:
    pairs_path = root / "funding_pairs_forward_20260720.json"
    candidates = []
    pairs = []
    for index, daily_spread_bps in enumerate(daily_spreads_bps, start=1):
        symbol = f"ASSET{index}"
        candidates.append({"symbol": symbol, "instrument": f"{symbol}_USDT"})
        pairs.append(
            {
                "symbol": f"{symbol}_USDT",
                "base": symbol,
                "spread_gate_minus_mexc": {
                    "mean_daily_spread_bps": daily_spread_bps,
                },
            }
        )
    _write_json(pairs_path, {"schema": "funding_pairs_v2", "pairs": pairs})

    proposal_path = root / "proposal.json"
    proposal = {
        "schema": "trading_mvp_funding_spread_daily_hold_planonly_proposal_v1",
        "status": "USER_REVIEW_REQUIRED_NOT_AUTHORIZED",
        "pre_oos_candidate_freeze": {
            "pair_summary": {
                "path": str(pairs_path),
                "sha256": _sha256(pairs_path),
            },
            "candidates": candidates,
        },
        "strategy_contract": {
            "holding_period_complete_utc_days": 4,
            "position_direction": "fixed from pre-OOS funding spread",
            "price_component": "reported separately",
        },
        "chronological_oos": {"complete_utc_days": 20},
        "economics_contract": {
            "normal_cycle_cost_bps_per_asset_fold": 78.0,
            "stress_cycle_cost_bps_per_asset_fold": 116.0,
            "stress_favorable_funding_haircut": 0.5,
        },
        "validation_contract": {
            "pre_oos_gates": {"minimum_verified_source_complete_assets": len(candidates)}
        },
        "authorization": {
            "implementation_allowed": False,
            "oos_evaluation_allowed": False,
        },
        "proposal_hash_method": "sha256_canonical_json_excluding_proposal_hash",
    }
    proposal["proposal_hash"] = _canonical_hash(proposal)
    _write_json(proposal_path, proposal)
    return proposal_path, root / "audit.json"


def _run(proposal_path: Path, output_path: Path, *, expected_sha256: str | None = None):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--proposal",
            str(proposal_path),
            "--expected-proposal-file-sha256",
            expected_sha256 or _sha256(proposal_path),
            "--out",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


class FundingDailyHoldProposalAuditTests(unittest.TestCase):
    def test_rejects_cost_mismatch_before_oos_or_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path, output_path = _fixture(Path(tmp), [15.0, 10.0])

            completed = _run(proposal_path, output_path)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            audit = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                audit["decision"],
                "REJECT_PROPOSAL_PREIMPLEMENTATION_ECONOMICS_MISMATCH",
            )
            self.assertTrue(audit["audit_passed"])
            self.assertFalse(audit["proposal_approval_consumable"])
            self.assertFalse(audit["planonly_implementation_allowed"])
            self.assertEqual(audit["normal_positive_candidate_count"], 0)
            self.assertEqual(audit["stress_positive_candidate_count"], 0)
            self.assertEqual(audit["stress_break_even_within_oos_count"], 1)
            self.assertEqual(audit["candidate_economics"][0]["normal_net_bps"], -18.0)
            self.assertEqual(audit["candidate_economics"][1]["stress_break_even_days"], 24)
            self.assertFalse(audit["data_access_audit"]["oos_market_rows_read"])
            self.assertFalse(audit["data_access_audit"]["returns_or_pnl_computed"])

    def test_does_not_block_when_funding_carry_covers_normal_and_stress_costs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path, output_path = _fixture(Path(tmp), [70.0, 60.0])

            completed = _run(proposal_path, output_path)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            audit = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["decision"], "PRE_OOS_ECONOMICS_NOT_BLOCKING")
            self.assertTrue(audit["proposal_approval_consumable"])
            self.assertTrue(audit["planonly_implementation_allowed"])
            self.assertFalse(audit["safety"]["approval_consumed"])
            self.assertEqual(audit["normal_positive_candidate_count"], 2)
            self.assertEqual(audit["stress_positive_candidate_count"], 2)

    def test_embedded_proposal_hash_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path, output_path = _fixture(Path(tmp), [70.0, 60.0])
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            proposal["strategy_contract"]["holding_period_complete_utc_days"] = 5
            _write_json(proposal_path, proposal)

            completed = _run(proposal_path, output_path)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(output_path.exists())
            self.assertIn("proposal_hash mismatch", completed.stderr)

    def test_pre_oos_summary_hash_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposal_path, output_path = _fixture(root, [70.0, 60.0])
            pairs_path = root / "funding_pairs_forward_20260720.json"
            with pairs_path.open("a", encoding="utf-8") as handle:
                handle.write("\n")

            completed = _run(proposal_path, output_path)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(output_path.exists())
            self.assertIn("pre-OOS pair summary SHA-256 mismatch", completed.stderr)

    def test_deterministic_result_hash_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path, output_path = _fixture(Path(tmp), [15.0, 10.0])
            first = _run(proposal_path, output_path)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_audit = json.loads(output_path.read_text(encoding="utf-8"))
            second = _run(proposal_path, output_path)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_audit = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(
                first_audit["deterministic_result_hash"],
                second_audit["deterministic_result_hash"],
            )

    def test_invalid_proposal_file_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path, output_path = _fixture(Path(tmp), [70.0, 60.0])

            completed = _run(proposal_path, output_path, expected_sha256="0" * 64)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(output_path.exists())
            self.assertIn("proposal file SHA-256 mismatch", completed.stderr)


if __name__ == "__main__":
    unittest.main()
