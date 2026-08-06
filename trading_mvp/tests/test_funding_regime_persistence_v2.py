from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    funding_regime = importlib.import_module("funding_regime_persistence_v2")
except ModuleNotFoundError:
    funding_regime = None


DAY_SEC = 86_400


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    source_plan_path = root / "basis-v2-plan.json"
    source_plan = {
        "schema": "fast_edge_historical_basis_v2_plan_v1",
        "plan_hash": "a" * 64,
    }
    _write_json(source_plan_path, source_plan)

    train_path = root / "normalized-candles.train.jsonl"
    oos_path = root / "normalized-candles.oos.jsonl"
    funding_path = root / "funding-events.jsonl"
    train_path.write_bytes(b"train-cache-is-hash-bound\n")
    oos_path.write_bytes(b"this-is-intentionally-not-json-and-must-not-be-parsed\n")
    funding_path.write_bytes(b"funding-cache-is-hash-bound\n")

    train_start = 14 * DAY_SEC
    train_end = train_start + 85 * DAY_SEC
    oos_end = train_end + 80 * DAY_SEC
    ranking = [
        ("coingecko:pippin-pippin", "PIPPIN", 21_022_577.79),
        ("coingecko:hype-hyperliquid", "HYPE", 15_647_977.92),
        ("coingecko:pi2-pi-network", "PI", 3_254_198.42),
        ("coingecko:myx-myx", "MYX", 1_679_997.46),
        ("coingecko:h-humanity", "H", 1_606_268.10),
    ]
    quality_path = root / "quality-report.json"
    quality = {
        "schema": "historical_basis_v2_quality_report_v1",
        "status": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "verdict": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "final": True,
        "plan_path": str(source_plan_path),
        "plan_file_sha256": _sha256(source_plan_path),
        "plan_hash": source_plan["plan_hash"],
        "split": {
            "warmup_days": 14,
            "train_days": 85,
            "oos_days": 80,
            "train_start_sec": train_start,
            "train_end_sec": train_end,
            "oos_start_sec": train_end,
            "oos_end_sec": oos_end,
        },
        "quality_surviving_asset_count": 20,
        "surviving_asset_count": 5,
        "primary_asset_ids": [row[0] for row in ranking],
        "reserve_asset_ids": [],
        "train_liquidity_ranking": [
            {
                "canonical_asset_id": canonical_id,
                "base": base,
                "train_worse_leg_quote_volume": volume,
            }
            for canonical_id, base, volume in ranking
        ],
        "train_row_count": 10_200,
        "oos_row_count": 9_600,
        "funding_event_count": 12_977,
        "train_output": str(train_path),
        "train_output_sha256": _sha256(train_path),
        "oos_output": str(oos_path),
        "oos_output_sha256": _sha256(oos_path),
        "funding_output": str(funding_path),
        "funding_output_sha256": _sha256(funding_path),
        "candle_merkle_sha256": "b" * 64,
        "funding_event_merkle_sha256": "c" * 64,
        "input_file_merkle_sha256": "d" * 64,
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "pnl_computed": False,
            "signals_read": False,
            "oos_metrics_read": False,
            "oos_candle_values_used_for_liquidity": False,
            "funding_exact_joined_to_candles": False,
        },
    }
    _write_json(quality_path, quality)

    bank_path = root / "hypothesis-bank.json"
    _write_json(
        bank_path,
        {
            "schema": "trading_mvp_hypothesis_bank_v1",
            "hypotheses": [
                {
                    "id": "funding_regime_persistence_carry_v2",
                    "status": "BANKED_NEEDS_NEW_DATA",
                    "required_data_type": "FUNDING_HISTORY_EXTENSION",
                    "thesis": "Persistent funding regimes may support hedged carry.",
                    "minimum_data": {
                        "days": 90,
                        "settlements": 180,
                        "dual_leg_coverage": 0.8,
                        "execution_snapshots": 180,
                    },
                    "forbidden": [
                        "favorable funding rescues negative price-only gate where not allowed",
                        "VIP/rebate assumption",
                        "leverage",
                    ],
                    "next_artifact": "funding history cache-diff and no-grid carry PlanOnly",
                }
            ],
        },
    )
    goal_path = root / "goal.md"
    goal_path.write_text("# One-Week Historical Edge Sprint\n", encoding="utf-8")
    return quality_path, bank_path, goal_path


class FundingRegimePersistencePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(
            funding_regime,
            "funding_regime_persistence_v2 module must be implemented",
        )
        for name in (
            "build_plan_from_basis_v2_cache",
            "canonical_plan_hash",
            "validate_plan",
            "write_plan_from_basis_v2_cache",
        ):
            self.assertTrue(callable(getattr(funding_regime, name, None)), name)

    def _plan(self, root: Path) -> dict:
        quality_path, bank_path, goal_path = _fixture(root)
        return funding_regime.build_plan_from_basis_v2_cache(
            quality_path,
            hypothesis_bank_path=bank_path,
            goal_path=goal_path,
            created_at_utc="2026-07-16T21:00:00+00:00",
            max_runtime_sec=300,
        )

    def test_plan_freezes_cross_venue_carry_without_reading_oos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir))

            funding_regime.validate_plan(plan, verify_files=True)
            self.assertEqual(plan["schema"], funding_regime.PLAN_SCHEMA)
            self.assertEqual(plan["mode"], "PlanOnly")
            self.assertEqual(
                plan["hypothesis"]["id"],
                "funding_regime_persistence_carry_v2",
            )
            self.assertEqual(plan["strategy"]["route"], "cross_venue_perp_perp")
            self.assertEqual(plan["strategy"]["direction"], "long_lower_funding_short_higher_funding")
            self.assertEqual(plan["strategy"]["regime_confirmation_complete_utc_days"], 3)
            self.assertEqual(plan["strategy"]["maximum_holding_days"], 14)
            self.assertEqual(plan["strategy"]["adverse_exit_complete_utc_days"], 2)
            self.assertFalse(plan["strategy"]["parameter_selection_on_train"])
            self.assertFalse(plan["strategy"]["parameter_selection_on_oos"])
            self.assertEqual(plan["economics"]["normal_cycle_cost"]["total_bps"], 78.0)
            self.assertEqual(plan["economics"]["stress_cycle_cost"]["total_bps"], 116.0)
            self.assertEqual(plan["strategy"]["minimum_expected_hold_carry_bps"], 136.0)
            self.assertAlmostEqual(
                plan["strategy"]["minimum_abs_daily_funding_differential_bps"],
                136.0 / 14.0,
            )
            self.assertEqual(len(plan["universe"]["candidates"]), 5)
            self.assertEqual(plan["universe"]["minimum_surviving_assets"], 4)
            self.assertTrue(plan["universe"]["selection_uses_train_liquidity_only"])
            self.assertFalse(plan["data_access_audit"]["oos_values_read"])
            self.assertTrue(plan["data_access_audit"]["oos_file_hash_verified"])
            self.assertFalse(plan["data_access_audit"]["signals_computed"])
            self.assertFalse(plan["data_access_audit"]["pnl_computed"])
            self.assertEqual(len(plan["code_provenance"]["module_sha256"]), 64)
            self.assertTrue(Path(plan["code_provenance"]["module_path"]).is_file())
            self.assertTrue(plan["validation"]["oos_embargo_until_train_feasible"])
            self.assertEqual(len(plan["validation"]["walk_forward"]["folds"]), 5)
            self.assertEqual(plan["oos_metrics"], {})
            self.assertEqual(plan["observed_performance"], {})
            self.assertEqual(plan["next_allowed_action"], "run_hash_bound_train_feasibility")
            self.assertEqual(plan["plan_hash"], funding_regime.canonical_plan_hash(plan))

    def test_tampering_is_rejected_even_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir))
            plan["strategy"]["maximum_holding_days"] = 7
            with self.assertRaisesRegex(ValueError, "Plan hash mismatch"):
                funding_regime.validate_plan(plan)

            plan["plan_hash"] = funding_regime.canonical_plan_hash(plan)
            with self.assertRaisesRegex(ValueError, "maximum_holding_days"):
                funding_regime.validate_plan(plan)

    def test_source_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = self._plan(root)
            Path(plan["sealed_input"]["train_path"]).write_bytes(b"tampered")

            with self.assertRaisesRegex(ValueError, "train source hash mismatch"):
                funding_regime.validate_plan(plan, verify_files=True)

    def test_quality_report_must_preserve_embargo_and_four_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            quality_path, bank_path, goal_path = _fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            quality["data_access_audit"]["oos_metrics_read"] = True
            _write_json(quality_path, quality)
            with self.assertRaisesRegex(ValueError, "OOS embargo"):
                funding_regime.build_plan_from_basis_v2_cache(
                    quality_path,
                    hypothesis_bank_path=bank_path,
                    goal_path=goal_path,
                )

            quality["data_access_audit"]["oos_metrics_read"] = False
            quality["train_liquidity_ranking"] = quality["train_liquidity_ranking"][:3]
            quality["primary_asset_ids"] = quality["primary_asset_ids"][:3]
            quality["surviving_asset_count"] = 3
            _write_json(quality_path, quality)
            with self.assertRaisesRegex(ValueError, "INSUFFICIENT_EXECUTABLE_UNIVERSE"):
                funding_regime.build_plan_from_basis_v2_cache(
                    quality_path,
                    hypothesis_bank_path=bank_path,
                    goal_path=goal_path,
                )

    def test_bank_record_and_runtime_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            quality_path, bank_path, goal_path = _fixture(root)
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            bank["hypotheses"][0]["id"] = "different_hypothesis"
            _write_json(bank_path, bank)
            with self.assertRaisesRegex(ValueError, "hypothesis bank"):
                funding_regime.build_plan_from_basis_v2_cache(
                    quality_path,
                    hypothesis_bank_path=bank_path,
                    goal_path=goal_path,
                )

            _fixture(root)
            with self.assertRaisesRegex(ValueError, "max_runtime_sec"):
                funding_regime.build_plan_from_basis_v2_cache(
                    quality_path,
                    hypothesis_bank_path=bank_path,
                    goal_path=goal_path,
                    max_runtime_sec=601,
                )

    def test_write_plan_is_deterministic_for_frozen_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            quality_path, bank_path, goal_path = _fixture(root)
            first_path = root / "plan-a.json"
            second_path = root / "plan-b.json"
            kwargs = {
                "hypothesis_bank_path": bank_path,
                "goal_path": goal_path,
                "created_at_utc": "2026-07-16T21:00:00+00:00",
                "max_runtime_sec": 300,
            }

            first = funding_regime.write_plan_from_basis_v2_cache(
                quality_path,
                first_path,
                **kwargs,
            )
            second = funding_regime.write_plan_from_basis_v2_cache(
                quality_path,
                second_path,
                **kwargs,
            )

            self.assertEqual(first["plan_hash"], second["plan_hash"])
            self.assertEqual(first["output_sha256"], second["output_sha256"])
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_run_mvp_exposes_bounded_plan_and_validate_actions(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
        text = wrapper.read_text(encoding="utf-8")
        for action in (
            "fast-edge-funding-persistence-v2-plan",
            "fast-edge-funding-persistence-v2-validate",
            "fast-edge-funding-persistence-v2-train-feasibility",
        ):
            self.assertIn(f'"{action}"', text)
        self.assertIn('src\\funding_regime_persistence_v2.py', text)
        self.assertIn('[string]$GoalPath = ""', text)
        self.assertIn(
            "MaxRuntimeSec must be <= 600 for fast-edge-funding-persistence-v2-plan",
            text,
        )
        self.assertIn(
            "MaxRuntimeSec must be <= 1800 for fast-edge-funding-persistence-v2-train-feasibility",
            text,
        )
        self.assertIn('"--verify-files"', text)
        self.assertIn(
            'Join-Path $codeSnapshot.snapshot_path "funding_regime_persistence_v2.py"',
            text,
        )
        self.assertIn(
            'Join-Path $codeSnapshot.snapshot_path "funding_regime_persistence_v2_evaluator.py"',
            text,
        )

    def test_train_feasibility_has_visible_launcher(self) -> None:
        launcher = (
            Path(__file__).resolve().parents[2]
            / "tools"
            / "run_funding_regime_persistence_v2_train_feasibility_visible.ps1"
        )
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("[int]$MaxRuntimeSec = 1800", text)
        self.assertIn("[int]$HoldOpenSec = 60", text)
        self.assertIn("check_active_run_gate.ps1", text)
        self.assertIn("fast-edge-funding-persistence-v2-train-feasibility", text)
        self.assertIn("Start-Process", text)
        self.assertIn("-WindowStyle Normal", text)
        self.assertIn("launch_record_path", text)
        self.assertNotIn("-WindowStyle Hidden", text)


if __name__ == "__main__":
    unittest.main()
