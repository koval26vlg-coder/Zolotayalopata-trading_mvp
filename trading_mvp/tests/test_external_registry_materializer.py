from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    import external_registry_materializer as materializer  # noqa: E402
except ImportError:  # RED: the production module is introduced after this test.
    materializer = None


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_plan_hash(payload: dict) -> str:
    unsigned = dict(payload)
    unsigned.pop("plan_hash", None)
    raw = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(raw)


class MaterializerFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "canonical"
        self.external = root / "external"
        self.repo.mkdir()
        self.external.mkdir()
        self._git("init", "--quiet")
        self._git("config", "core.autocrlf", "false")
        self._git("config", "user.email", "registry-tests@example.invalid")
        self._git("config", "user.name", "Registry Tests")
        self._git(
            "remote",
            "add",
            "origin",
            "https://example.invalid/canonical.git",
        )

        self.worker = self.repo / "worker.py"
        self.worker.write_bytes(b"def run():\n    return 'committed'\n")
        self.materializer = self.repo / "registry_materializer.py"
        self.materializer.write_bytes(b"# committed materializer entrypoint\n")
        self.validator = self.repo / "canonical_strategy_runtime.py"
        self.validator.write_bytes(
            (SRC_ROOT / "canonical_strategy_runtime.py").read_bytes()
        )
        self.launcher = self.repo / "start_visible.ps1"
        self.launcher.write_bytes(b"Write-Output 'committed launcher'\r\n")
        self.plan = self.repo / "plan.json"
        self._write_plan()
        self._git(
            "add",
            "worker.py",
            "registry_materializer.py",
            "canonical_strategy_runtime.py",
            "start_visible.ps1",
            "plan.json",
        )
        self._git("commit", "--quiet", "-m", "runtime")

        first_commit = self.head()
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        self.source = self.repo / "registry.staging.json"
        source_payload = {
            "schema": "zolotyaylopata.canonical_strategy_runtime.v1",
            "registry_id": "fixture_external_registry_v1",
            "generated_at_utc": "2026-08-25T17:00:00Z",
            "activation_status": "STAGING_NOT_INSTALLED",
            "canonical_owners": [
                {
                    "strategy_id": "fixture_runtime",
                    "namespace_prefix": "listing.fixture.runtime",
                    "scope": "fixture_scope",
                    "venues": ["fixture"],
                }
            ],
            "runtimes": [
                {
                    "strategy_id": "fixture_runtime",
                    "track_class": "fixture_track",
                    "runtime_status": "INACTIVE",
                    "activation_readiness": "STAGED_ONLY",
                    "namespace_prefix": "listing.fixture.runtime",
                    "scope": "fixture_scope",
                    "venues": ["fixture"],
                    "canonical_repo": str(self.repo),
                    "canonical_remote_url": "https://example.invalid/canonical.git",
                    "canonical_git_commit": first_commit,
                    "canonical_plan_path": str(self.plan),
                    "canonical_plan_sha256": "0" * 64,
                    "canonical_plan_file_sha256": "0" * 64,
                    "canonical_plan_id": plan["plan_id"],
                    "canonical_plan_status": plan["status"],
                    "launcher_path": str(self.launcher),
                    "launcher_sha256": "0" * 64,
                    "scheduler_routable": False,
                    "allowed_modes": ["DISCOVERY"],
                    "state_path": str(self.repo / "state.json"),
                    "ledger_path": str(self.repo / "attempts.jsonl"),
                    "public_data_only": True,
                    "live_trading_allowed": False,
                    "implementation_bindings": [
                        {
                            "role": "worker",
                            "path": str(self.worker),
                            "sha256": "0" * 64,
                        }
                    ],
                    "supersedes": [],
                    "retired_aliases": [],
                }
            ],
        }
        self.source.write_text(
            json.dumps(source_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._git("add", "registry.staging.json")
        self._git("commit", "--quiet", "-m", "declarative source")

    def _git(self, *args: str) -> str:
        git = Path(r"C:\Program Files\Git\cmd\git.exe")
        executable = str(git) if git.exists() else "git"
        completed = subprocess.run(
            [executable, "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return completed.stdout.strip()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def head_blob(self, path: Path) -> bytes:
        relative = path.relative_to(self.repo).as_posix()
        git = Path(r"C:\Program Files\Git\cmd\git.exe")
        executable = str(git) if git.exists() else "git"
        return subprocess.check_output(
            [executable, "-C", str(self.repo), "show", f"HEAD:{relative}"],
        )

    def _write_plan(self) -> None:
        payload = {
            "schema": "fixture_plan_v1",
            "plan_id": "fixture_plan_20260825_v1",
            "status": "READY_FOR_OFFLINE_VALIDATION",
            "implementation": {
                "files": [
                    {
                        "role": "worker",
                        "repo_path": "worker.py",
                        "sha256": sha256_bytes(self.worker.read_bytes()),
                    }
                ]
            },
        }
        payload["plan_hash"] = canonical_plan_hash(payload)
        self.plan.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class ExternalRegistryMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(
            materializer,
            "external_registry_materializer production module is missing",
        )
        self.temp = tempfile.TemporaryDirectory(prefix="external-registry-test-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = MaterializerFixture(Path(self.temp.name))

    def materialize(
        self,
        *,
        expected_materializer_head_sha256: str | None = None,
        **kwargs: object,
    ) -> dict:
        test_before_write_hook = kwargs.pop("test_before_write_hook", None)
        output_path = kwargs.pop("output_path", None)
        receipt_path = kwargs.pop("receipt_path", None)
        if "publication_root" not in kwargs:
            legacy_paths = [
                Path(path)
                for path in (output_path, receipt_path)
                if path is not None
            ]
            inside_repo = [
                path.parent
                for path in legacy_paths
                if path.parent.resolve(strict=False).is_relative_to(
                    self.fixture.repo.resolve(strict=True)
                )
            ]
            kwargs["publication_root"] = (
                inside_repo[0]
                if inside_repo
                else legacy_paths[0].parent
                if legacy_paths
                else self.fixture.external
            )
        expected = expected_materializer_head_sha256 or sha256_bytes(
            self.fixture.head_blob(self.fixture.materializer)
        )
        expected_validator = kwargs.pop(
            "expected_validator_head_sha256",
            sha256_bytes(self.fixture.head_blob(self.fixture.validator)),
        )
        expected_control_plane_commit = kwargs.pop(
            "expected_control_plane_git_commit",
            self.fixture.head(),
        )
        original_module_file = materializer.__file__
        original_publish = materializer._publish_versioned_pair

        def publish_with_hook(**publish_kwargs: object) -> tuple[Path, Path]:
            if test_before_write_hook is not None:
                test_before_write_hook()
            return original_publish(**publish_kwargs)

        materializer.__file__ = str(self.fixture.materializer)
        materializer._publish_versioned_pair = publish_with_hook
        try:
            return materializer.materialize_external_registry(
                expected_materializer_head_sha256=expected,
                expected_validator_head_sha256=expected_validator,
                expected_control_plane_git_commit=expected_control_plane_commit,
                **kwargs,
            )
        finally:
            materializer.__file__ = original_module_file
            materializer._publish_versioned_pair = original_publish

    def test_public_api_cannot_substitute_materializer_binding_path(self) -> None:
        parameters = inspect.signature(
            materializer.materialize_external_registry
        ).parameters
        self.assertNotIn("materializer_path", parameters)
        self.assertNotIn("before_write_hook", parameters)

    def test_validator_dependency_is_not_imported_before_commit_binding(self) -> None:
        self.assertNotIn("runtime_registry", materializer.__dict__)
        source = (SRC_ROOT / "external_registry_materializer.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import canonical_strategy_runtime", source)

    def test_public_api_requires_bound_validator_and_versioned_publication_root(
        self,
    ) -> None:
        parameters = inspect.signature(
            materializer.materialize_external_registry
        ).parameters
        self.assertIn("expected_validator_head_sha256", parameters)
        self.assertIn("expected_control_plane_git_commit", parameters)
        self.assertIn("publication_root", parameters)
        self.assertNotIn("output_path", parameters)
        self.assertNotIn("receipt_path", parameters)

    def test_snapshot_rejects_nested_git_directory_as_canonical_repo(self) -> None:
        nested = self.fixture.repo / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "canonical_repo_not_git_toplevel",
        ):
            materializer._snapshot_repository(nested)

    def test_versioned_pair_publisher_is_present(self) -> None:
        self.assertTrue(
            hasattr(materializer, "_publish_versioned_pair"),
            "registry and receipt need one versioned atomic publication primitive",
        )

    def test_versioned_pair_failure_leaves_no_half_publication(self) -> None:
        source_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        original_write = materializer._write_new_file
        writes = 0

        def fail_second_write(path: Path, raw: bytes) -> None:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise materializer.MaterializationError("injected_receipt_write_failure")
            original_write(path, raw)

        materializer._write_new_file = fail_second_write
        try:
            with self.assertRaisesRegex(
                materializer.MaterializationError,
                "injected_receipt_write_failure",
            ):
                self.materialize(
                    source_path=self.fixture.source,
                    publication_root=self.fixture.external,
                    expected_source_head_sha256=source_sha,
                )
        finally:
            materializer._write_new_file = original_write

        self.assertEqual(
            [path for path in self.fixture.external.iterdir() if path.is_dir()],
            [],
        )
        self.assertEqual(
            [path for path in self.fixture.external.iterdir() if path.is_file()],
            [],
        )

    @unittest.skipUnless(os.name == "nt", "Windows directory-handle guard")
    def test_publication_root_cannot_be_renamed_during_atomic_pair_write(self) -> None:
        source_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        original_write = materializer._write_new_file
        renamed_root = self.fixture.root / "external-renamed"
        rename_was_blocked = False
        writes = 0

        def attempt_root_swap(path: Path, raw: bytes) -> None:
            nonlocal rename_was_blocked, writes
            writes += 1
            original_write(path, raw)
            if writes == 1:
                try:
                    self.fixture.external.rename(renamed_root)
                except OSError:
                    rename_was_blocked = True

        materializer._write_new_file = attempt_root_swap
        try:
            result = self.materialize(
                source_path=self.fixture.source,
                publication_root=self.fixture.external,
                expected_source_head_sha256=source_sha,
            )
        finally:
            materializer._write_new_file = original_write

        self.assertTrue(rename_was_blocked)
        self.assertTrue(Path(result["registry_path"]).is_file())
        self.assertTrue(Path(result["receipt_path"]).is_file())
        self.assertFalse(renamed_root.exists())

    def test_same_content_cannot_overwrite_existing_version(self) -> None:
        source_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        first = self.materialize(
            source_path=self.fixture.source,
            publication_root=self.fixture.external,
            expected_source_head_sha256=source_sha,
        )
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "publication_already_exists",
        ):
            self.materialize(
                source_path=self.fixture.source,
                publication_root=self.fixture.external,
                expected_source_head_sha256=source_sha,
            )
        publication = Path(first["publication_directory"])
        self.assertEqual(
            sorted(path.name for path in publication.iterdir()),
            [materializer.REGISTRY_FILENAME, materializer.RECEIPT_FILENAME],
        )

    @unittest.skipUnless(os.name == "nt", "Windows PATH hardening")
    def test_git_executable_ignores_path_shadow_on_windows(self) -> None:
        original_which = materializer.shutil.which
        materializer.shutil.which = lambda _: r"C:\untrusted\git.exe"
        try:
            self.assertEqual(
                Path(materializer._git_executable()),
                Path(r"C:\Program Files\Git\cmd\git.exe"),
            )
        finally:
            materializer.shutil.which = original_which

    def test_materializes_deterministic_registry_from_exact_committed_blobs(
        self,
    ) -> None:
        source_head_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        committed_head = self.fixture.head()
        committed_worker_sha = sha256_bytes(self.fixture.head_blob(self.fixture.worker))
        committed_launcher_sha = sha256_bytes(
            self.fixture.head_blob(self.fixture.launcher)
        )

        # Every scoped worktree file is dirty. None of these bytes is trusted.
        self.fixture.source.write_text("{}\n", encoding="utf-8")
        self.fixture.worker.write_text(
            "raise RuntimeError('dirty')\n", encoding="utf-8"
        )
        self.fixture.launcher.write_text("throw 'dirty'\n", encoding="utf-8")
        self.fixture.plan.write_text("{}\n", encoding="utf-8")

        publication_root = self.fixture.external
        result = self.materialize(
            source_path=self.fixture.source,
            publication_root=publication_root,
            expected_source_head_sha256=source_head_sha,
            expected_materializer_head_sha256=sha256_bytes(
                self.fixture.head_blob(self.fixture.materializer)
            ),
        )
        output = Path(result["registry_path"])
        receipt = Path(result["receipt_path"])

        self.assertEqual(result["status"], "MATERIALIZED_FAIL_CLOSED", result)
        self.assertEqual(result["decision"], "STAGED_FAIL_CLOSED", result)
        self.assertFalse(result["launch_allowed"], result)
        self.assertEqual(
            result["registry_raw_sha256"], sha256_bytes(output.read_bytes())
        )

        payload = json.loads(output.read_text(encoding="utf-8"))
        runtime = payload["runtimes"][0]
        self.assertEqual(runtime["canonical_git_commit"], committed_head)
        self.assertEqual(
            runtime["canonical_remote_url"], "https://example.invalid/canonical.git"
        )
        self.assertEqual(
            runtime["implementation_bindings"][0]["sha256"], committed_worker_sha
        )
        self.assertEqual(runtime["launcher_sha256"], committed_launcher_sha)
        self.assertFalse(runtime["scheduler_routable"])
        self.assertFalse(runtime["live_trading_allowed"])

        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt_payload.get("validation"),
            {
                "all_runtime_bindings_valid": True,
                "decision": "STAGED_FAIL_CLOSED",
                "launch_allowed": False,
                "ok": True,
                "registry_valid": True,
                "registry_raw_sha256": result["registry_raw_sha256"],
            },
        )
        self.assertEqual(
            receipt_payload["registry_raw_sha256"], result["registry_raw_sha256"]
        )
        self.assertEqual(receipt_payload["source_head_sha256"], source_head_sha)
        self.assertEqual(
            receipt_payload["materializer_head_sha256"],
            sha256_bytes(self.fixture.head_blob(self.fixture.materializer)),
        )
        self.assertEqual(receipt_payload["materializer_git_commit"], committed_head)
        self.assertEqual(
            receipt_payload["canonical_repositories"],
            [
                {
                    "canonical_repo": str(self.fixture.repo),
                    "canonical_git_commit": committed_head,
                }
            ],
        )
        self.assertFalse(receipt_payload["launch_allowed"])

        second_root = self.fixture.root / "external-2"
        second_root.mkdir()
        second = self.materialize(
            source_path=self.fixture.source,
            publication_root=second_root,
            expected_source_head_sha256=source_head_sha,
            expected_materializer_head_sha256=sha256_bytes(
                self.fixture.head_blob(self.fixture.materializer)
            ),
        )
        second_output = Path(second["registry_path"])
        self.assertEqual(second["registry_raw_sha256"], result["registry_raw_sha256"])
        self.assertEqual(second_output.read_bytes(), output.read_bytes())

    def test_rejects_registry_or_receipt_inside_any_canonical_repository(self) -> None:
        expected = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        cases = (
            (
                self.fixture.repo / "external-registry.json",
                self.fixture.external / "outside.receipt.json",
                "output_inside_canonical_repo",
            ),
            (
                self.fixture.external / "outside.json",
                self.fixture.repo / "external-registry.receipt.json",
                "output_inside_canonical_repo",
            ),
        )
        for output, receipt, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                with self.assertRaisesRegex(
                    materializer.MaterializationError,
                    expected_reason,
                ):
                    self.materialize(
                        source_path=self.fixture.source,
                        output_path=output,
                        receipt_path=receipt,
                        expected_source_head_sha256=expected,
                        expected_materializer_head_sha256=sha256_bytes(
                            self.fixture.head_blob(self.fixture.materializer)
                        ),
                    )
                self.assertFalse(output.exists())
                self.assertFalse(receipt.exists())

    def test_resolves_symlink_alias_before_enforcing_external_boundary(self) -> None:
        expected = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        alias = self.fixture.external / "canonical-alias"
        try:
            os.symlink(self.fixture.repo, alias, target_is_directory=True)
        except OSError as exc:  # pragma: no cover - host privilege dependent
            self.skipTest(f"directory symlink unavailable: {exc}")
        output = alias / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "output_inside_canonical_repo",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=expected,
                expected_materializer_head_sha256=sha256_bytes(
                    self.fixture.head_blob(self.fixture.materializer)
                ),
            )
        self.assertFalse((self.fixture.repo / "candidate.json").exists())
        self.assertFalse(receipt.exists())

    def test_rejects_materializer_hash_mismatch_or_dirty_entrypoint(self) -> None:
        parameters = inspect.signature(
            materializer.materialize_external_registry
        ).parameters
        self.assertIn("expected_materializer_head_sha256", parameters)
        source_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        materializer_sha = sha256_bytes(
            self.fixture.head_blob(self.fixture.materializer)
        )
        output = self.fixture.external / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"

        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "materializer_head_sha256_mismatch",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=source_sha,
                expected_materializer_head_sha256="f" * 64,
            )

        self.fixture.materializer.write_bytes(b"# dirty materializer\n")
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "materializer_worktree_differs_from_head",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=source_sha,
                expected_materializer_head_sha256=materializer_sha,
            )
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())

    def test_rejects_dirty_or_hash_mismatched_validator_dependency(self) -> None:
        expected_source = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        expected_validator = sha256_bytes(
            self.fixture.head_blob(self.fixture.validator)
        )
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "validator_head_sha256_mismatch",
        ):
            self.materialize(
                source_path=self.fixture.source,
                publication_root=self.fixture.external,
                expected_source_head_sha256=expected_source,
                expected_validator_head_sha256="f" * 64,
            )

        self.fixture.validator.write_bytes(b"# dirty validator\n")
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "validator_worktree_differs_from_head",
        ):
            self.materialize(
                source_path=self.fixture.source,
                publication_root=self.fixture.external,
                expected_source_head_sha256=expected_source,
                expected_validator_head_sha256=expected_validator,
            )
        self.assertEqual(list(self.fixture.external.iterdir()), [])

    def test_rejects_source_head_hash_mismatch_before_writing(self) -> None:
        output = self.fixture.external / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "source_head_sha256_mismatch",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256="f" * 64,
                expected_materializer_head_sha256=sha256_bytes(
                    self.fixture.head_blob(self.fixture.materializer)
                ),
            )
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())

    def test_rejects_mutable_origin_that_disagrees_with_committed_source(self) -> None:
        source = json.loads(self.fixture.source.read_text(encoding="utf-8"))
        source["runtimes"][0]["canonical_remote_url"] = (
            "https://example.invalid/other.git"
        )
        self.fixture.source.write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.fixture._git("add", "registry.staging.json")
        self.fixture._git("commit", "--quiet", "-m", "mismatched declared remote")

        output = self.fixture.external / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "canonical_remote_mismatch:fixture_runtime",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=sha256_bytes(
                    self.fixture.head_blob(self.fixture.source)
                ),
            )
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())

    def test_detects_repository_head_change_before_writing_outputs(self) -> None:
        source_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        materializer_sha = sha256_bytes(
            self.fixture.head_blob(self.fixture.materializer)
        )
        output = self.fixture.external / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"

        def advance_head() -> None:
            self.fixture.worker.write_bytes(b"def run():\n    return 'new head'\n")
            self.fixture._git("add", "worker.py")
            self.fixture._git("commit", "--quiet", "-m", "advance during build")

        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "repository_head_changed",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=source_sha,
                expected_materializer_head_sha256=materializer_sha,
                test_before_write_hook=advance_head,
            )
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())

    def test_detects_canonical_remote_change_before_writing_outputs(self) -> None:
        output = self.fixture.external / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"

        def change_origin() -> None:
            self.fixture._git(
                "remote",
                "set-url",
                "origin",
                "https://example.invalid/swapped.git",
            )

        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "repository_remote_changed",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=sha256_bytes(
                    self.fixture.head_blob(self.fixture.source)
                ),
                test_before_write_hook=change_origin,
            )
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())

    def test_rejects_plan_binding_that_does_not_match_exact_commit_blob(self) -> None:
        plan = json.loads(self.fixture.plan.read_text(encoding="utf-8"))
        plan["implementation"]["files"][0]["sha256"] = "f" * 64
        plan["plan_hash"] = canonical_plan_hash(plan)
        self.fixture.plan.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.fixture._git("add", "plan.json")
        self.fixture._git("commit", "--quiet", "-m", "invalid plan binding")

        source_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        materializer_sha = sha256_bytes(
            self.fixture.head_blob(self.fixture.materializer)
        )
        output = self.fixture.external / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"
        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "implementation_head_sha256_mismatch:fixture_runtime:worker",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=source_sha,
                expected_materializer_head_sha256=materializer_sha,
            )
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())

    def test_rejects_output_parent_path_swap_after_boundary_check(self) -> None:
        source_sha = sha256_bytes(self.fixture.head_blob(self.fixture.source))
        materializer_sha = sha256_bytes(
            self.fixture.head_blob(self.fixture.materializer)
        )
        output = self.fixture.external / "candidate.json"
        receipt = self.fixture.external / "candidate.receipt.json"
        original_external = self.fixture.root / "external-original"

        def restore_external_directory() -> None:
            if self.fixture.external.exists():
                os.rmdir(self.fixture.external)
            if original_external.exists():
                original_external.rename(self.fixture.external)

        def swap_parent_to_canonical_junction() -> None:
            self.fixture.external.rename(original_external)
            completed = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(self.fixture.external),
                    str(self.fixture.repo),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if completed.returncode != 0:
                original_external.rename(self.fixture.external)
                self.skipTest(f"junction unavailable: {completed.stderr}")
            self.addCleanup(restore_external_directory)

        with self.assertRaisesRegex(
            materializer.MaterializationError,
            "publication_root_path_changed_during_materialization",
        ):
            self.materialize(
                source_path=self.fixture.source,
                output_path=output,
                receipt_path=receipt,
                expected_source_head_sha256=source_sha,
                expected_materializer_head_sha256=materializer_sha,
                test_before_write_hook=swap_parent_to_canonical_junction,
            )
        self.assertFalse((self.fixture.repo / "candidate.json").exists())
        self.assertFalse((self.fixture.repo / "candidate.receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
