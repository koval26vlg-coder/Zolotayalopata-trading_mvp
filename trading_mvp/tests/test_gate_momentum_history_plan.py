from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for candidate in (SRC, TESTS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from gate_momentum_history_plan import (  # noqa: E402
    DATA_TYPES,
    HISTORY_DAYS,
    OOS_FOLDS,
    PLAN_SCHEMA,
    build_gate_momentum_history_plan,
    main as history_main,
    sha256_json,
    validate_gate_momentum_history_plan,
)
from gate_momentum_identity import (  # noqa: E402
    collect_gate_momentum_identity_metadata,
)
import test_gate_momentum_identity as identity_fixtures  # noqa: E402


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


class GateMomentumHistoryPlanTests(unittest.TestCase):
    def _accepted_identity(self, root: Path) -> dict[str, Path]:
        fixture = identity_fixtures.GateMomentumIdentityCollectorTests()
        paths, _ = fixture._ready_identity_plan(root)
        collect_gate_momentum_identity_metadata(
            paths["identity_plan"],
            environ={"TARDIS_API_KEY": "fixture-secret"},
            session=identity_fixtures.JsonSession(
                [fixture._gate_instruments(), fixture._binance_instruments()]
            ),
            generated_at_utc="2026-07-24T21:00:00+00:00",
        )
        return paths

    @staticmethod
    def _history_paths(root: Path) -> dict[str, Path]:
        return {
            "plan": root / "history-plan.json",
            "train_cache": root / "cache" / "train",
            "oos_cache": root / "cache" / "sealed-oos",
            "train_normalized": root / "normalized" / "train.jsonl",
            "oos_normalized": root / "normalized" / "sealed-oos.jsonl",
            "manifest": root / "history-manifest.json",
            "quality": root / "history-quality.json",
        }

    def _build_plan(
        self,
        root: Path,
        *,
        paths: dict[str, Path] | None = None,
    ) -> tuple[dict[str, Path], dict[str, Path], dict[str, object]]:
        identity_paths = paths or self._accepted_identity(root)
        outputs = self._history_paths(root)
        plan = build_gate_momentum_history_plan(
            identity_paths["momentum_plan"],
            identity_paths["identity_plan"],
            identity_paths["identity_result"],
            train_cache_root=outputs["train_cache"],
            oos_cache_root=outputs["oos_cache"],
            train_normalized_output_path=outputs["train_normalized"],
            oos_normalized_output_path=outputs["oos_normalized"],
            history_manifest_output_path=outputs["manifest"],
            quality_report_output_path=outputs["quality"],
            history_end_exclusive="2026-07-24",
            frozen_at_utc="2026-07-25T00:30:00+00:00",
            max_runtime_sec=7200,
        )
        return identity_paths, outputs, plan

    def test_plan_is_deterministic_hash_bound_and_non_evaluating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity_paths = self._accepted_identity(root)
            _, _, first = self._build_plan(root, paths=identity_paths)
            _, _, second = self._build_plan(root, paths=identity_paths)

        self.assertEqual(first["schema"], PLAN_SCHEMA)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(first["mode"], "PlanOnly")
        self.assertFalse(first["data_access_audit"]["market_values_read"])
        self.assertFalse(first["data_access_audit"]["returns_read"])
        self.assertFalse(first["data_access_audit"]["pnl_read"])
        self.assertFalse(first["safety"]["history_collect_currently_allowed"])
        self.assertFalse(first["safety"]["oos_currently_allowed"])
        self.assertEqual(
            first["next_allowed_command"],
            "gate-momentum-history-collect-visible",
        )
        self.assertNotIn("fixture-secret", json.dumps(first))

    def test_plan_freezes_exact_220_day_split_and_440_grouped_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan = self._build_plan(Path(tmp))

        history = plan["history"]
        start = date.fromisoformat(history["history_start"])
        end = date.fromisoformat(history["history_end_exclusive"])
        self.assertEqual((end - start).days, HISTORY_DAYS)
        self.assertEqual(history["warmup_days"], 20)
        self.assertEqual(history["train_days"], 100)
        self.assertEqual(history["oos_days"], 100)
        self.assertEqual(len(history["oos_folds"]), OOS_FOLDS)
        self.assertEqual(
            history["global_rebalance_anchor"],
            (start + timedelta(days=30)).isoformat(),
        )

        tasks = plan["download"]["tasks"]
        self.assertEqual(len(tasks), HISTORY_DAYS * len(DATA_TYPES))
        self.assertEqual({task["symbol"] for task in tasks}, {"PERPETUALS"})
        self.assertEqual(
            {task["data_type"] for task in tasks},
            set(DATA_TYPES),
        )
        self.assertTrue(
            all(
                task["url"].startswith(
                    "https://datasets.tardis.dev/v1/gate-io-futures/"
                )
                for task in tasks
            )
        )
        self.assertEqual(
            sum(task["partition"] == "warmup" for task in tasks),
            20 * len(DATA_TYPES),
        )
        self.assertEqual(
            sum(task["partition"] == "train" for task in tasks),
            100 * len(DATA_TYPES),
        )
        for fold in range(1, 6):
            self.assertEqual(
                sum(task["oos_fold"] == fold for task in tasks),
                20 * len(DATA_TYPES),
            )

    def test_train_and_oos_cache_roots_are_physically_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity_paths = self._accepted_identity(root)
            outputs = self._history_paths(root)
            with self.assertRaisesRegex(ValueError, "must be disjoint"):
                build_gate_momentum_history_plan(
                    identity_paths["momentum_plan"],
                    identity_paths["identity_plan"],
                    identity_paths["identity_result"],
                    train_cache_root=outputs["train_cache"],
                    oos_cache_root=outputs["train_cache"] / "oos",
                    train_normalized_output_path=outputs["train_normalized"],
                    oos_normalized_output_path=outputs["oos_normalized"],
                    history_manifest_output_path=outputs["manifest"],
                    quality_report_output_path=outputs["quality"],
                    history_end_exclusive="2026-07-24",
                    frozen_at_utc="2026-07-25T00:30:00+00:00",
                )

    def test_history_plan_requires_accepted_identity_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = identity_fixtures.GateMomentumIdentityCollectorTests()
            identity_paths, _ = fixture._ready_identity_plan(root)
            collect_gate_momentum_identity_metadata(
                identity_paths["identity_plan"],
                environ={"TARDIS_API_KEY": "fixture-secret"},
                session=identity_fixtures.JsonSession(
                    [fixture._gate_instruments(19), fixture._binance_instruments()]
                ),
                generated_at_utc="2026-07-24T21:00:00+00:00",
            )
            outputs = self._history_paths(root)
            with self.assertRaisesRegex(
                ValueError,
                "cannot authorize history PlanOnly",
            ):
                build_gate_momentum_history_plan(
                    identity_paths["momentum_plan"],
                    identity_paths["identity_plan"],
                    identity_paths["identity_result"],
                    train_cache_root=outputs["train_cache"],
                    oos_cache_root=outputs["oos_cache"],
                    train_normalized_output_path=outputs["train_normalized"],
                    oos_normalized_output_path=outputs["oos_normalized"],
                    history_manifest_output_path=outputs["manifest"],
                    quality_report_output_path=outputs["quality"],
                    history_end_exclusive="2026-07-24",
                    frozen_at_utc="2026-07-25T00:30:00+00:00",
                )

    def test_history_end_requires_a_fully_exported_day_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity_paths = self._accepted_identity(root)
            outputs = self._history_paths(root)
            with self.assertRaisesRegex(ValueError, "fully exported UTC day"):
                build_gate_momentum_history_plan(
                    identity_paths["momentum_plan"],
                    identity_paths["identity_plan"],
                    identity_paths["identity_result"],
                    train_cache_root=outputs["train_cache"],
                    oos_cache_root=outputs["oos_cache"],
                    train_normalized_output_path=outputs["train_normalized"],
                    oos_normalized_output_path=outputs["oos_normalized"],
                    history_manifest_output_path=outputs["manifest"],
                    quality_report_output_path=outputs["quality"],
                    history_end_exclusive="2026-07-25",
                    frozen_at_utc="2026-07-25T12:00:00+00:00",
                )

    def test_validator_accepts_frozen_plan_and_cli_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, outputs, plan = self._build_plan(root)
            _write_json(outputs["plan"], plan)
            validated = validate_gate_momentum_history_plan(outputs["plan"])
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = history_main(
                    ["validate-plan", "--plan", str(outputs["plan"])]
                )

        self.assertEqual(validated["plan_hash"], plan["plan_hash"])
        self.assertEqual(exit_code, 0)
        self.assertIn("GATE_MOMENTUM_HISTORY_PLAN_VALID", stdout.getvalue())

    def test_rehashed_task_mutation_still_fails_semantic_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, outputs, plan = self._build_plan(root)
            tampered = copy.deepcopy(plan)
            tampered["download"]["tasks"][0]["url"] = (
                "https://datasets.tardis.dev/v1/gate-io-futures/"
                "trades/1900/01/01/PERPETUALS.csv.gz"
            )
            task = tampered["download"]["tasks"][0]
            task["task_hash"] = sha256_json(
                {key: value for key, value in task.items() if key != "task_hash"}
            )
            tampered["plan_hash"] = sha256_json(
                {
                    key: value
                    for key, value in tampered.items()
                    if key != "plan_hash"
                }
            )
            _write_json(outputs["plan"], tampered)

            with self.assertRaisesRegex(ValueError, "download task contract mismatch"):
                validate_gate_momentum_history_plan(outputs["plan"])

    def test_upstream_identity_mutation_invalidates_frozen_history_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity_paths, outputs, plan = self._build_plan(root)
            _write_json(outputs["plan"], plan)
            result = json.loads(
                identity_paths["identity_result"].read_text(encoding="utf-8")
            )
            result["canonical_gate_asset_count"] = 19
            _write_json(identity_paths["identity_result"], result)

            with self.assertRaisesRegex(ValueError, "input file hash mismatch"):
                validate_gate_momentum_history_plan(outputs["plan"])


if __name__ == "__main__":
    unittest.main()
