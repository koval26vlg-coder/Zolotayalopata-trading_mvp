from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_code_provenance as provenance  # noqa: E402


def _repo(root: Path) -> Path:
    (root / "trading_mvp" / "src").mkdir(parents=True)
    (root / "trading_mvp" / "tests").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (root / "trading_mvp" / "run_mvp.ps1").write_text(
        "Write-Output run\n", encoding="utf-8"
    )
    (root / "trading_mvp" / "src" / "paper_observer.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (root / "trading_mvp" / "src" / "basis_paper_oms.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    (root / "trading_mvp" / "src" / "autopilot_guard.py").write_text(
        "VALUE = 5\n", encoding="utf-8"
    )
    (root / "trading_mvp" / "tests" / "test_paper_observer.py").write_text(
        "VALUE = 3\n", encoding="utf-8"
    )
    (root / "trading_mvp" / "tests" / "test_autopilot_guard.py").write_text(
        "VALUE = 6\n", encoding="utf-8"
    )
    (root / "tools" / "check_pit_train_progress.ps1").write_text(
        "Write-Output check\n", encoding="utf-8"
    )
    (root / "tools" / "check_trading_mvp_autopilot.ps1").write_text(
        "Write-Output guard\n", encoding="utf-8"
    )
    (root / "data.json").write_text('{"secret":"not-read"}', encoding="utf-8")
    return root


class PaperCodeProvenanceTests(unittest.TestCase):
    def test_manifest_contains_only_selected_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                generated_at_utc="2026-07-28T21:00:00+00:00",
            )
        paths = {item["path"] for item in manifest["files"]}
        self.assertIn("AGENTS.md", paths)
        self.assertIn("trading_mvp/src/paper_observer.py", paths)
        self.assertNotIn("trading_mvp/src/autopilot_guard.py", paths)
        self.assertNotIn("data.json", paths)
        self.assertFalse(manifest["operations"]["git_stage"])
        self.assertFalse(manifest["operations"]["file_copy"])

    def test_v2_includes_bounded_autopilot_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                manifest_version="v2",
                generated_at_utc="2026-07-29T04:30:00+00:00",
            )
            provenance.validate_code_manifest(manifest, repo_root=root)
        paths = {item["path"] for item in manifest["files"]}
        self.assertEqual(manifest["schema"], provenance.MANIFEST_SCHEMA_V2)
        self.assertEqual(
            manifest["task_id"], "paper_code_provenance_merkle_v2"
        )
        self.assertIn("trading_mvp/src/autopilot_guard.py", paths)
        self.assertIn(
            "trading_mvp/tests/test_autopilot_guard.py", paths
        )
        self.assertIn(
            "tools/check_trading_mvp_autopilot.ps1", paths
        )
        self.assertEqual(
            manifest["next_allowed_action"],
            "paper_public_retry_rate_limit_fixture_v1",
        )

    def test_v3_refreshes_bounded_code_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                manifest_version="v3",
                generated_at_utc="2026-07-29T05:00:00+00:00",
            )
            provenance.validate_code_manifest(manifest, repo_root=root)
        paths = {item["path"] for item in manifest["files"]}
        self.assertEqual(manifest["schema"], provenance.MANIFEST_SCHEMA_V3)
        self.assertEqual(
            manifest["task_id"], "paper_code_provenance_merkle_v3"
        )
        self.assertEqual(
            manifest["selection_contract"]["selection_contract_version"], 3
        )
        self.assertIn("trading_mvp/src/autopilot_guard.py", paths)
        self.assertIn("trading_mvp/tests/test_autopilot_guard.py", paths)
        self.assertIn("tools/check_trading_mvp_autopilot.ps1", paths)
        self.assertEqual(
            manifest["next_allowed_action"],
            "paper_public_reader_transport_wiring_fixture_v1",
        )

    def test_v4_refreshes_runtime_wiring_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                manifest_version="v4",
                generated_at_utc="2026-07-29T05:15:00+00:00",
            )
            provenance.validate_code_manifest(manifest, repo_root=root)
        self.assertEqual(manifest["schema"], provenance.MANIFEST_SCHEMA_V4)
        self.assertEqual(
            manifest["task_id"], "paper_code_provenance_merkle_v4"
        )
        self.assertEqual(
            manifest["selection_contract"]["selection_contract_version"], 4
        )
        self.assertEqual(
            manifest["next_allowed_action"],
            "paper_public_system_clock_fixture_v1",
        )

    def test_v5_refreshes_offline_runtime_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                manifest_version="v5",
                generated_at_utc="2026-07-29T05:20:00+00:00",
            )
            provenance.validate_code_manifest(manifest, repo_root=root)
        self.assertEqual(manifest["schema"], provenance.MANIFEST_SCHEMA_V5)
        self.assertEqual(
            manifest["task_id"], "paper_code_provenance_merkle_v5"
        )
        self.assertEqual(
            manifest["selection_contract"]["selection_contract_version"], 5
        )
        self.assertEqual(
            manifest["next_allowed_action"],
            "paper_public_runtime_reader_factory_fixture_v1",
        )

    def test_v6_refreshes_public_probe_and_v8_audit_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                manifest_version="v6",
                generated_at_utc="2026-07-30T16:00:00+00:00",
            )
            provenance.validate_code_manifest(manifest, repo_root=root)
        self.assertEqual(manifest["schema"], provenance.MANIFEST_SCHEMA_V6)
        self.assertEqual(
            manifest["task_id"], "paper_code_provenance_merkle_v6"
        )
        self.assertEqual(
            manifest["selection_contract"]["selection_contract_version"], 6
        )
        self.assertEqual(
            manifest["next_allowed_action"],
            "paper_public_probe_evidence_observer_binding_fixture_v1",
        )

    def test_v7_refreshes_current_readiness_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                manifest_version="v7",
                generated_at_utc="2026-08-09T16:00:00+00:00",
            )
            provenance.validate_code_manifest(manifest, repo_root=root)
        self.assertEqual(manifest["schema"], provenance.MANIFEST_SCHEMA_V7)
        self.assertEqual(
            manifest["task_id"], "paper_code_provenance_merkle_v7"
        )
        self.assertEqual(
            manifest["selection_contract"]["selection_contract_version"], 7
        )
        self.assertEqual(
            manifest["next_allowed_action"],
            "paper_product_readiness_audit_v10",
        )

    def test_manifest_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            first = provenance.build_code_manifest(repo_root=root)
            second = provenance.build_code_manifest(repo_root=root)
        self.assertEqual(
            first["merkle_root_sha256"], second["merkle_root_sha256"]
        )
        self.assertEqual(
            first["deterministic_result_hash"],
            second["deterministic_result_hash"],
        )

    def test_validation_detects_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(repo_root=root)
            (root / "trading_mvp" / "src" / "paper_observer.py").write_text(
                "VALUE = 9\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "hash drifted"):
                provenance.validate_code_manifest(
                    manifest, repo_root=root
                )

    def test_validation_detects_new_selected_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(repo_root=root)
            (root / "trading_mvp" / "src" / "paper_new.py").write_text(
                "VALUE = 4\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "file set drifted"):
                provenance.validate_code_manifest(
                    manifest, repo_root=root
                )

    def test_merkle_root_depends_on_paths_and_content(self) -> None:
        first = provenance.merkle_root(
            [provenance._leaf_hash("a.py", "0" * 64)]
        )
        second = provenance.merkle_root(
            [provenance._leaf_hash("b.py", "0" * 64)]
        )
        self.assertNotEqual(first, second)

    def test_rejects_schema_task_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            manifest = provenance.build_code_manifest(
                repo_root=root,
                manifest_version="v2",
            )
            manifest["task_id"] = "paper_code_provenance_merkle_v1"
            with self.assertRaisesRegex(ValueError, "schema/task"):
                provenance.validate_code_manifest(
                    manifest,
                    repo_root=root,
                )


if __name__ == "__main__":
    unittest.main()
