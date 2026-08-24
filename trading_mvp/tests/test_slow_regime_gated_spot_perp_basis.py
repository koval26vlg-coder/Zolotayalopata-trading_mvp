from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slow_regime_gated_spot_perp_basis import (  # noqa: E402
    ComboPlanConfig,
    build_planonly_report,
    classify_combo_signal,
    extract_identity_bases,
    extract_paired_ok_bases,
    frozen_contract_hash,
    universe_intersection,
)


class ComboSignalTests(unittest.TestCase):
    def test_basis_alone_is_not_enough_without_slow_regime(self) -> None:
        result = classify_combo_signal(
            spot_mid=100.0,
            perp_mid=101.2,
            spot_spread_bps=5.0,
            perp_spread_bps=5.0,
            funding_rate=0.0001,
            regime_state="none",
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["combo_signal"], "blocked")
        self.assertIn("slow_regime_absent", result["reasons"])

    def test_compression_and_positive_basis_allows_hedge(self) -> None:
        result = classify_combo_signal(
            spot_mid=100.0,
            perp_mid=101.2,
            spot_spread_bps=5.0,
            perp_spread_bps=5.0,
            funding_rate=0.0001,
            regime_state="compression",
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["combo_signal"], "regime_and_long_spot_short_perp")
        self.assertFalse(result["needs_spot_short"])

    def test_valid_retest_is_an_allowed_regime(self) -> None:
        result = classify_combo_signal(
            spot_mid=100.0,
            perp_mid=101.2,
            spot_spread_bps=5.0,
            perp_spread_bps=5.0,
            funding_rate=0.0001,
            regime_state="valid_retest",
        )
        self.assertTrue(result["allowed"])

    def test_negative_basis_stays_blocked(self) -> None:
        result = classify_combo_signal(
            spot_mid=100.0,
            perp_mid=98.5,
            spot_spread_bps=5.0,
            perp_spread_bps=5.0,
            funding_rate=0.0001,
            regime_state="compression",
        )
        self.assertFalse(result["allowed"])
        self.assertIn("negative_basis_requires_spot_short", result["reasons"])


class UniverseIntersectionTests(unittest.TestCase):
    def test_extracts_paired_ok_from_probe_rows(self) -> None:
        probe = {
            "rows": [
                {"base": "AERO", "paired_ok": True},
                {"base": "ARX", "paired_ok": False},
                {"base": "DEEP", "paired_ok": True},
            ]
        }
        self.assertEqual(extract_paired_ok_bases(probe), ["AERO", "DEEP"])

    def test_extracts_identity_accepted_bases_only(self) -> None:
        identity = {
            "identity_acceptance": {
                "accepted_bases": ["BDX", "OKB"],
                "excluded_bases": [{"base": "EDGE", "reason": "COLLISION"}],
            }
        }
        self.assertEqual(extract_identity_bases(identity), ["BDX", "OKB"])

    def test_empty_intersection_is_sorted_and_empty(self) -> None:
        self.assertEqual(universe_intersection(["AERO", "DEEP"], ["BDX", "OKB"]), [])

    def test_overlap_is_sorted_upper(self) -> None:
        self.assertEqual(
            universe_intersection(["deep", "AERO", "OKB"], ["OKB", "DEEP"]),
            ["DEEP", "OKB"],
        )


class ComboPlanOnlyReportTests(unittest.TestCase):
    def _write(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_empty_intersection_is_infeasible_and_blocks_collect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe = root / "probe.json"
            identity = root / "identity.json"
            self._write(
                probe,
                {
                    "summary": {"paired_ok_bases": ["AERO", "DEEP"]},
                    "rows": [
                        {"base": "AERO", "paired_ok": True},
                        {"base": "DEEP", "paired_ok": True},
                    ],
                },
            )
            self._write(
                identity,
                {"identity_acceptance": {"accepted_bases": ["BDX", "OKB", "STETH"]}},
            )

            report = build_planonly_report(
                repo_root=root,
                probe_path=probe,
                identity_path=identity,
                rejected_collect_run_id="spot_perp_basis_collect_20260819_083140",
            )

        self.assertEqual(
            report["decision"],
            "SLOW_REGIME_GATED_SPOT_PERP_BASIS_PLANONLY_INFEASIBLE_ON_CURRENT_NAMED_ARTIFACTS",
        )
        self.assertEqual(report["feasibility"]["intersection_bases"], [])
        self.assertEqual(report["feasibility"]["intersection_count"], 0)
        self.assertFalse(report["collect_allowed_now"])
        self.assertFalse(report["replay_allowed_now"])
        self.assertFalse(report["grid_allowed_now"])
        self.assertFalse(report["paper_forward_allowed"])
        self.assertFalse(report["strategy_accepted"])
        self.assertFalse(report["would_start"])
        self.assertIn("rejected_incomplete_collect_not_evidence", report["blocked_evidence"])
        self.assertIn("slow_liquidity_14_event_sample_not_retunable", report["blocked_evidence"])
        self.assertEqual(report["hypothesis"]["join_rule"], "AND")
        self.assertEqual(report["plan_hash"], frozen_contract_hash())

    def test_sufficient_overlap_stays_planonly_not_collect(self) -> None:
        cfg = ComboPlanConfig(min_bases=2, min_independent_events=100)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe = root / "probe.json"
            identity = root / "identity.json"
            self._write(
                probe,
                {"summary": {"paired_ok_bases": ["OKB", "DEEP", "BDX"]}},
            )
            self._write(
                identity,
                {"identity_acceptance": {"accepted_bases": ["BDX", "OKB", "STETH"]}},
            )
            report = build_planonly_report(
                repo_root=root,
                probe_path=probe,
                identity_path=identity,
                cfg=cfg,
            )

        self.assertEqual(
            report["decision"],
            "SLOW_REGIME_GATED_SPOT_PERP_BASIS_PLANONLY_READY_FOR_PAIRED_HISTORY_PREFLIGHT",
        )
        self.assertEqual(report["feasibility"]["intersection_bases"], ["BDX", "OKB"])
        self.assertFalse(report["collect_allowed_now"])
        self.assertFalse(report["evaluator_or_oos_authorized"])

    def test_contract_hash_is_stable(self) -> None:
        self.assertEqual(len(frozen_contract_hash()), 64)
        self.assertEqual(frozen_contract_hash(), frozen_contract_hash())


if __name__ == "__main__":
    unittest.main()
