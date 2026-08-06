from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import historical_basis_code_snapshot as snapshot_module  # noqa: E402

from historical_basis_code_snapshot import (  # noqa: E402
    create_basis_code_snapshot,
    validate_basis_code_snapshot_reference,
)


class HistoricalBasisCodeSnapshotTests(unittest.TestCase):
    def test_runtime_snapshot_must_match_frozen_plan_snapshot(self) -> None:
        helper = getattr(snapshot_module, "require_plan_runtime_code_snapshot", None)
        self.assertIsNotNone(helper, "runtime snapshot binding helper is missing")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_source = root / "first-src"
            second_source = root / "second-src"
            first_source.mkdir()
            second_source.mkdir()
            (first_source / "historical_basis_v2.py").write_text(
                "VERSION = 1\n", encoding="utf-8"
            )
            (second_source / "historical_basis_v2.py").write_text(
                "VERSION = 2\n", encoding="utf-8"
            )
            first = create_basis_code_snapshot(first_source, root / "snapshots")
            second = create_basis_code_snapshot(second_source, root / "snapshots")
            plan = {
                "code_provenance": {
                    "immutable_snapshot": True,
                    "code_snapshot_hash": first["code_snapshot_hash"],
                    "code_snapshot_manifest": first["manifest_path"],
                }
            }

            with self.assertRaisesRegex(
                ValueError, "runtime code snapshot does not match frozen plan"
            ):
                helper(
                    plan,
                    runtime_code_path=(
                        Path(second["snapshot_path"]) / "historical_basis_v2.py"
                    ),
                )

    def test_matching_runtime_snapshot_is_accepted(self) -> None:
        helper = getattr(snapshot_module, "require_plan_runtime_code_snapshot", None)
        self.assertIsNotNone(helper, "runtime snapshot binding helper is missing")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            source.mkdir()
            (source / "historical_basis_v2.py").write_text(
                "VERSION = 1\n", encoding="utf-8"
            )
            snapshot = create_basis_code_snapshot(source, root / "snapshots")
            plan = {
                "code_provenance": {
                    "immutable_snapshot": True,
                    "code_snapshot_hash": snapshot["code_snapshot_hash"],
                    "code_snapshot_manifest": snapshot["manifest_path"],
                }
            }

            runtime = helper(
                plan,
                runtime_code_path=(
                    Path(snapshot["snapshot_path"]) / "historical_basis_v2.py"
                ),
            )
            self.assertEqual(runtime["code_snapshot_hash"], snapshot["code_snapshot_hash"])
            self.assertTrue(runtime["immutable_snapshot"])

    def test_snapshot_is_content_addressed_reused_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            source.mkdir()
            (source / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            nested = source / "nested"
            nested.mkdir()
            (nested / "b.py").write_text("VALUE = 2\n", encoding="utf-8")

            first = create_basis_code_snapshot(source, root / "snapshots")
            second = create_basis_code_snapshot(source, root / "snapshots")

            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            self.assertEqual(first["code_snapshot_hash"], second["code_snapshot_hash"])
            snapshot_path = Path(first["snapshot_path"])
            self.assertEqual((snapshot_path / "a.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertTrue(Path(first["manifest_path"]).is_file())
            reference = validate_basis_code_snapshot_reference(
                first["code_snapshot_hash"],
                first["manifest_path"],
                fallback_code_path=__file__,
            )
            self.assertTrue(reference["immutable_snapshot"])

            copied = snapshot_path / "a.py"
            copied.chmod(stat.S_IREAD | stat.S_IWRITE)
            copied.write_text("TAMPERED = True\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "snapshot file hash mismatch"):
                create_basis_code_snapshot(source, root / "snapshots")

    def test_manifest_inventory_cannot_be_resealed_under_old_bundle_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            source.mkdir()
            (source / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            snapshot = create_basis_code_snapshot(source, root / "snapshots")
            snapshot_path = Path(snapshot["snapshot_path"])
            copied = snapshot_path / "a.py"
            manifest_path = Path(snapshot["manifest_path"])

            copied.chmod(stat.S_IREAD | stat.S_IWRITE)
            copied.write_text("TAMPERED = True\n", encoding="utf-8")
            manifest_path.chmod(stat.S_IREAD | stat.S_IWRITE)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["size_bytes"] = copied.stat().st_size
            manifest["files"][0]["sha256"] = hashlib.sha256(copied.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "bundle hash"):
                validate_basis_code_snapshot_reference(
                    snapshot["code_snapshot_hash"],
                    manifest_path,
                    fallback_code_path=__file__,
                )


if __name__ == "__main__":
    unittest.main()
