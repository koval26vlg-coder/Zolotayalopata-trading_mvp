from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    import external_registry_promoter as promoter  # noqa: E402
except ImportError:  # RED: production module follows the contract tests.
    promoter = None


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json_bytes(payload: dict) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_plan_hash(payload: dict) -> str:
    unsigned = dict(payload)
    unsigned.pop("plan_hash", None)
    return sha256_bytes(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


class PromotionFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "control"
        self.parent_root = root / "staging-publications"
        self.active_root = root / "active-publications"
        self.repo.mkdir()
        self.parent_root.mkdir()
        self.active_root.mkdir()
        (self.repo / "trading_mvp" / "src").mkdir(parents=True)
        (self.repo / "tools").mkdir()
        (self.repo / "runtime").mkdir()

        self._git("init", "--quiet")
        self._git("config", "core.autocrlf", "false")
        self._git("config", "user.email", "promoter-tests@example.invalid")
        self._git("config", "user.name", "Promoter Tests")
        self._git(
            "remote",
            "add",
            "origin",
            "https://example.invalid/control.git",
        )

        self.worker = self.repo / "runtime" / "worker.py"
        self.worker.write_bytes(b"def run():\n    return 'public research'\n")
        self.launcher = self.repo / "runtime" / "start_visible.ps1"
        self.launcher.write_bytes(b"Write-Output 'public research only'\r\n")
        self.state = self.repo / "runtime" / "state.json"
        self.ledger = self.repo / "runtime" / "attempts.jsonl"
        self.state.write_bytes(
            canonical_json_bytes(
                {
                    "status": "IDLE",
                    "next_interval_at_utc": "2026-08-26T04:00:00Z",
                }
            )
        )
        self.ledger.write_bytes(b"")

        self.plan = self.repo / "runtime" / "plan.json"
        plan_payload = {
            "schema": "fixture_plan_v1",
            "plan_id": "fixture_plan_20260826_v1",
            "status": "PUBLIC_RESEARCH_ONLY",
            "implementation": {
                "files": [
                    {
                        "role": "worker",
                        "repo_path": "runtime/worker.py",
                        "sha256": sha256_bytes(self.worker.read_bytes()),
                    }
                ]
            },
        }
        plan_payload["plan_hash"] = canonical_plan_hash(plan_payload)
        self.plan.write_bytes(canonical_json_bytes(plan_payload))

        self.validator = self.repo / "trading_mvp" / "src" / "canonical_strategy_runtime.py"
        self.validator.write_bytes((SRC_ROOT / "canonical_strategy_runtime.py").read_bytes())
        self.materializer = (
            self.repo / "trading_mvp" / "src" / "external_registry_materializer.py"
        )
        self.materializer.write_bytes(
            (SRC_ROOT / "external_registry_materializer.py").read_bytes()
        )
        self.alternate_materializer = (
            self.repo / "trading_mvp" / "src" / "alternate_publication.py"
        )
        self.alternate_materializer.write_bytes(b"# not the bound publication primitive\n")
        self.promoter = self.repo / "trading_mvp" / "src" / "external_registry_promoter.py"
        self.promoter.write_bytes(b"# committed promoter entrypoint\n")
        self.coordinator = self.repo / "tools" / "invoke_listing_strategy_due_coordinator.ps1"
        self.coordinator.write_bytes(b"Write-Output 'coordinator'\r\n")
        self.installer = self.repo / "tools" / "install_listing_strategy_due_coordinator_task.ps1"
        self.installer.write_bytes(b"Write-Output 'installer'\r\n")
        self.remote = self._git("remote", "get-url", "origin")
        self.source = self.repo / "registry-source.json"
        source_payload = self._source_payload()
        self.source.write_bytes(canonical_json_bytes(source_payload))
        self.invalid_source = self.repo / "invalid-source.json"
        self.invalid_source.write_bytes(b"{}\n")
        self.unrelated_source = self.repo / "unrelated-source.json"
        unrelated_payload = json.loads(json.dumps(source_payload))
        unrelated_payload["registry_id"] = "unrelated_staging_20260826_v1"
        self.unrelated_source.write_bytes(canonical_json_bytes(unrelated_payload))

        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "bound public research runtime")
        self.commit = self.head()
        self._build_parent_publication()

    def _git(self, *args: str) -> str:
        git = Path(r"C:\Program Files\Git\cmd\git.exe")
        executable = str(git) if git.exists() else "git"
        completed = subprocess.run(
            [executable, "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
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
            [executable, "-C", str(self.repo), "show", f"HEAD:{relative}"]
        )

    def _source_payload(self) -> dict:
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        return {
            "schema": "zolotyaylopata.canonical_strategy_runtime.v1",
            "registry_id": "fixture_runtime_staging_20260826_v1",
            "generated_at_utc": "2026-08-26T01:00:00Z",
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
                    "activation_readiness": "READY_AFTER_ROUTER_MIGRATION",
                    "namespace_prefix": "listing.fixture.runtime",
                    "scope": "fixture_scope",
                    "venues": ["fixture"],
                    "canonical_repo": str(self.repo),
                    "canonical_remote_url": self.remote,
                    "canonical_git_commit": "0" * 40,
                    "canonical_plan_path": str(self.plan),
                    "canonical_plan_sha256": plan["plan_hash"],
                    "canonical_plan_file_sha256": sha256_bytes(
                        self.plan.read_bytes()
                    ),
                    "canonical_plan_id": plan["plan_id"],
                    "canonical_plan_status": plan["status"],
                    "launcher_path": str(self.launcher),
                    "launcher_sha256": sha256_bytes(self.launcher.read_bytes()),
                    "scheduler_routable": False,
                    "allowed_modes": ["DISCOVERY", "PAPER_RESEARCH"],
                    "state_path": str(self.state),
                    "ledger_path": str(self.ledger),
                    "public_data_only": True,
                    "live_trading_allowed": False,
                    "implementation_bindings": [
                        {
                            "role": "worker",
                            "path": str(self.worker),
                            "sha256": sha256_bytes(self.worker.read_bytes()),
                        }
                    ],
                    "supersedes": [],
                    "retired_aliases": [],
                }
            ],
        }

    def _build_parent_publication(self) -> None:
        registry_payload = json.loads(self.head_blob(self.source))
        snapshots = {}
        for runtime in registry_payload["runtimes"]:
            repo = Path(runtime["canonical_repo"])
            runtime_commit = self._git("-C", str(repo), "rev-parse", "HEAD")
            runtime["canonical_git_commit"] = runtime_commit
            snapshots[str(repo)] = {
                "canonical_repo": str(repo),
                "canonical_git_commit": runtime_commit,
            }
        canonical_repositories = sorted(
            snapshots.values(), key=lambda row: row["canonical_repo"].casefold()
        )
        registry_raw = canonical_json_bytes(registry_payload)
        registry_sha = sha256_bytes(registry_raw)
        publication_id = sha256_bytes(
            canonical_json_bytes(
                {
                    "schema": "zolotyaylopata.external_registry_publication_identity.v1",
                    "source_git_commit": self.commit,
                    "source_head_sha256": sha256_bytes(self.head_blob(self.source)),
                    "control_plane_git_commit": self.commit,
                    "materializer_head_sha256": sha256_bytes(
                        self.head_blob(self.materializer)
                    ),
                    "validator_head_sha256": sha256_bytes(self.head_blob(self.validator)),
                    "registry_raw_sha256": registry_sha,
                    "canonical_repositories": canonical_repositories,
                }
            )
        )
        publication_dir = self.parent_root / publication_id
        publication_dir.mkdir()
        self.parent_registry = publication_dir / "canonical_strategy_runtime.json"
        self.parent_receipt = publication_dir / "materialization_receipt.json"
        self.parent_registry.write_bytes(registry_raw)

        runtime_validation = {
            "strategy_id": "fixture_runtime",
            "decision": "INACTIVE_NOT_ROUTABLE",
            "launch_allowed": False,
            "state_status": "IGNORED_INACTIVE",
            "binding_status": "MATCH",
            "reasons": [],
        }
        receipt_payload = {
            "schema": "zolotyaylopata.external_registry_materialization_receipt.v2",
            "status": "MATERIALIZED_FAIL_CLOSED",
            "decision": "STAGED_FAIL_CLOSED",
            "launch_allowed": False,
            "publication_id": publication_id,
            "publication_directory": str(publication_dir),
            "source_path": str(self.source),
            "source_git_commit": self.commit,
            "source_head_sha256": sha256_bytes(self.head_blob(self.source)),
            "materializer_path": str(self.materializer),
            "materializer_git_commit": self.commit,
            "materializer_head_sha256": sha256_bytes(
                self.head_blob(self.materializer)
            ),
            "validator_path": str(self.validator),
            "validator_git_commit": self.commit,
            "validator_head_sha256": sha256_bytes(self.head_blob(self.validator)),
            "registry_path": str(self.parent_registry),
            "receipt_path": str(self.parent_receipt),
            "registry_raw_sha256": registry_sha,
            "canonical_repositories": canonical_repositories,
            "validation": {
                "ok": True,
                "registry_valid": True,
                "all_runtime_bindings_valid": True,
                "decision": "STAGED_FAIL_CLOSED",
                "launch_allowed": False,
                "registry_raw_sha256": registry_sha,
                "reasons": [],
                "runtimes": [runtime_validation],
            },
        }
        self.parent_receipt.write_bytes(canonical_json_bytes(receipt_payload))
        self.parent_registry_sha = registry_sha
        self.parent_receipt_sha = sha256_bytes(self.parent_receipt.read_bytes())

    def expected_hashes(self) -> dict[str, str]:
        return {
            "expected_promoter_head_sha256": sha256_bytes(
                self.head_blob(self.promoter)
            ),
            "expected_validator_head_sha256": sha256_bytes(
                self.head_blob(self.validator)
            ),
            "expected_publication_primitive_head_sha256": sha256_bytes(
                self.head_blob(self.materializer)
            ),
            "expected_coordinator_head_sha256": sha256_bytes(
                self.head_blob(self.coordinator)
            ),
            "expected_installer_head_sha256": sha256_bytes(
                self.head_blob(self.installer)
            ),
            "expected_control_plane_git_commit": self.commit,
        }


class ExternalRegistryPromoterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(
            promoter,
            "external_registry_promoter production module is missing",
        )
        self.temp = tempfile.TemporaryDirectory(prefix="registry-promoter-test-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = PromotionFixture(Path(self.temp.name))

    def promote(self, **overrides: object) -> dict:
        kwargs: dict[str, object] = {
            "parent_registry_path": self.fixture.parent_registry,
            "parent_receipt_path": self.fixture.parent_receipt,
            "publication_root": self.fixture.active_root,
            "active_strategy_id": "fixture_runtime",
            "generated_at_utc": "2026-08-26T02:00:00Z",
            "expected_parent_registry_raw_sha256": self.fixture.parent_registry_sha,
            "expected_parent_receipt_raw_sha256": self.fixture.parent_receipt_sha,
            **self.fixture.expected_hashes(),
        }
        kwargs.update(overrides)
        original_promoter_file = promoter.__file__
        promoter.__file__ = str(self.fixture.promoter)
        try:
            return promoter.promote_external_registry(**kwargs)
        finally:
            promoter.__file__ = original_promoter_file

    def test_promotes_exactly_one_public_research_runtime_with_bound_receipt(self) -> None:
        result = self.promote()

        self.assertEqual(result["decision"], "ACTIVE_ROUTABLE", result)
        self.assertTrue(result["launch_allowed"], result)
        registry_path = Path(result["registry_path"])
        receipt_path = Path(result["receipt_path"])
        self.assertEqual(registry_path.parent, receipt_path.parent)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        self.assertEqual(registry["schema"], "zolotyaylopata.canonical_strategy_runtime.v2")
        self.assertEqual(registry["activation_status"], "ACTIVE_INSTALLED")
        active = [row for row in registry["runtimes"] if row["runtime_status"] == "ACTIVE"]
        routable = [row for row in registry["runtimes"] if row["scheduler_routable"]]
        self.assertEqual([row["strategy_id"] for row in active], ["fixture_runtime"])
        self.assertEqual([row["strategy_id"] for row in routable], ["fixture_runtime"])
        self.assertFalse(active[0]["live_trading_allowed"])
        self.assertTrue(active[0]["public_data_only"])
        self.assertLessEqual(
            set(active[0]["allowed_modes"]),
            {"DISCOVERY", "PAPER_RESEARCH"},
        )

        self.assertEqual(
            receipt["schema"],
            "zolotyaylopata.external_registry_activation_receipt.v1",
        )
        self.assertEqual(receipt["decision"], "ACTIVE_ROUTABLE")
        self.assertEqual(receipt["active_strategy_id"], "fixture_runtime")
        self.assertEqual(
            receipt["parent_lineage"]["registry_raw_sha256"],
            self.fixture.parent_registry_sha,
        )
        self.assertEqual(
            receipt["parent_lineage"]["receipt_raw_sha256"],
            self.fixture.parent_receipt_sha,
        )
        self.assertEqual(
            receipt["registry_raw_sha256"],
            sha256_bytes(registry_path.read_bytes()),
        )
        self.assertEqual(
            {row["role"] for row in receipt["control_bindings"]},
            {"promoter", "validator", "publication_primitive", "coordinator", "installer"},
        )
        self.assertEqual(
            receipt["policy_evidence"],
            {
                "source_decision": "STAGED_FAIL_CLOSED",
                "all_source_bindings_match": True,
                "active_runtime_count": 1,
                "routable_runtime_count": 1,
                "activation_readiness": "READY_AFTER_ROUTER_MIGRATION",
                "public_data_only": True,
                "live_trading_allowed": False,
                "allowed_modes": ["DISCOVERY", "PAPER_RESEARCH"],
            },
        )
        self.assertEqual(
            receipt["active_runtime_binding"]["canonical_git_commit"],
            self.fixture.commit,
        )
        self.assertEqual(
            receipt["active_runtime_binding"]["state_raw_sha256"],
            sha256_bytes(self.fixture.state.read_bytes()),
        )
        self.assertEqual(
            receipt["active_runtime_binding"]["state_status"],
            "IDLE",
        )
        self.assertEqual(
            receipt["active_runtime_binding"]["next_interval_at_utc"],
            "2026-08-26T04:00:00Z",
        )

    def test_cli_failure_is_json_fail_closed_without_execution(self) -> None:
        self.assertTrue(hasattr(promoter, "main"), "promoter CLI is missing")
        argv = [
            "--promote",
            "--parent-registry",
            str(self.fixture.parent_registry),
            "--parent-receipt",
            str(self.fixture.parent_receipt),
            "--publication-root",
            str(self.fixture.active_root),
            "--active-strategy-id",
            "fixture_runtime",
            "--generated-at-utc",
            "2026-08-26T02:00:00Z",
            "--expected-parent-registry-raw-sha256",
            self.fixture.parent_registry_sha,
            "--expected-parent-receipt-raw-sha256",
            self.fixture.parent_receipt_sha,
            "--expected-promoter-head-sha256",
            "not-a-hash",
            "--expected-validator-head-sha256",
            "1" * 64,
            "--expected-publication-primitive-head-sha256",
            "2" * 64,
            "--expected-coordinator-head-sha256",
            "3" * 64,
            "--expected-installer-head-sha256",
            "4" * 64,
            "--expected-control-plane-git-commit",
            self.fixture.commit,
            "--json",
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = promoter.main(argv)
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "PROMOTION_BLOCKED")
        self.assertEqual(payload["reason"], "expected_sha256_invalid")
        self.assertFalse(payload["launch_allowed"])
        self.assertFalse(payload["execution_performed"])
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_cli_success_publishes_fixture_pair_without_execution(self) -> None:
        self.assertTrue(hasattr(promoter, "main"), "promoter CLI is missing")
        values = {
            "parent_registry": str(self.fixture.parent_registry),
            "parent_receipt": str(self.fixture.parent_receipt),
            "publication_root": str(self.fixture.active_root),
            "active_strategy_id": "fixture_runtime",
            "generated_at_utc": "2026-08-26T02:00:00Z",
            "expected_parent_registry_raw_sha256": self.fixture.parent_registry_sha,
            "expected_parent_receipt_raw_sha256": self.fixture.parent_receipt_sha,
            **self.fixture.expected_hashes(),
        }
        argv = ["--promote", "--json"]
        for name, value in values.items():
            argv.extend(["--" + name.replace("_", "-"), value])
        original_promoter_file = promoter.__file__
        promoter.__file__ = str(self.fixture.promoter)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                exit_code = promoter.main(argv)
        finally:
            promoter.__file__ = original_promoter_file
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["decision"], "ACTIVE_ROUTABLE")
        self.assertFalse(payload["execution_performed"])
        self.assertTrue(Path(payload["registry_path"]).is_file())
        self.assertTrue(Path(payload["receipt_path"]).is_file())

    def test_rejects_alternate_same_repo_publication_dependency(self) -> None:
        with self.assertRaisesRegex(
            promoter.PromotionError,
            "publication_primitive_path_mismatch|publication_primitive_head_sha256_mismatch",
        ):
            self.promote(
                expected_publication_primitive_head_sha256=sha256_bytes(
                    self.fixture.head_blob(self.fixture.alternate_materializer)
                ),
            )
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_rejects_parent_hash_or_receipt_tamper_without_publication(self) -> None:
        with self.assertRaisesRegex(
            promoter.PromotionError,
            "parent_receipt_raw_sha256_mismatch",
        ):
            self.promote(expected_parent_receipt_raw_sha256="f" * 64)
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

        payload = json.loads(self.fixture.parent_receipt.read_text(encoding="utf-8"))
        payload["validation"]["runtimes"][0]["binding_status"] = "MISMATCH"
        self.fixture.parent_receipt.write_bytes(canonical_json_bytes(payload))
        with self.assertRaisesRegex(
            promoter.PromotionError,
            "parent_receipt_runtime_binding_not_match",
        ):
            self.promote(
                expected_parent_receipt_raw_sha256=sha256_bytes(
                    self.fixture.parent_receipt.read_bytes()
                )
            )
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_parent_receipt_policy_fields_require_json_booleans(self) -> None:
        original = self.fixture.parent_receipt.read_bytes()
        cases = (
            ("launch_allowed", 0, "parent_receipt_launch_allowed_invalid"),
            ("validation.ok", 1, "parent_receipt_validation_ok_invalid"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field):
                receipt = json.loads(original)
                if field.startswith("validation."):
                    receipt["validation"][field.split(".", 1)[1]] = value
                else:
                    receipt[field] = value
                raw = canonical_json_bytes(receipt)
                self.fixture.parent_receipt.write_bytes(raw)
                with self.assertRaisesRegex(promoter.PromotionError, reason):
                    self.promote(
                        expected_parent_receipt_raw_sha256=sha256_bytes(raw)
                    )
                self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_rejects_missing_or_forged_historical_parent_lineage(self) -> None:
        original = self.fixture.parent_receipt.read_bytes()
        cases = (
            ("source_git_commit", None, "parent_lineage_source_git_commit_invalid"),
            (
                "materializer_head_sha256",
                "f" * 64,
                "parent_lineage_materializer_sha256_mismatch",
            ),
            (
                "canonical_repositories",
                [],
                "parent_canonical_repository_set_mismatch",
            ),
        )
        for field, value, reason in cases:
            with self.subTest(field=field):
                receipt = json.loads(original)
                receipt[field] = value
                raw = canonical_json_bytes(receipt)
                self.fixture.parent_receipt.write_bytes(raw)
                with self.assertRaisesRegex(promoter.PromotionError, reason):
                    self.promote(
                        expected_parent_receipt_raw_sha256=sha256_bytes(raw)
                    )
                self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_rejects_committed_structurally_invalid_historical_source(self) -> None:
        receipt = json.loads(self.fixture.parent_receipt.read_bytes())
        receipt["source_path"] = str(self.fixture.invalid_source)
        receipt["source_head_sha256"] = sha256_bytes(
            self.fixture.head_blob(self.fixture.invalid_source)
        )
        raw = canonical_json_bytes(receipt)
        self.fixture.parent_receipt.write_bytes(raw)
        with self.assertRaisesRegex(
            promoter.PromotionError, "parent_lineage_source_structure_invalid"
        ):
            self.promote(expected_parent_receipt_raw_sha256=sha256_bytes(raw))
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_rejects_valid_unrelated_historical_source(self) -> None:
        receipt = json.loads(self.fixture.parent_receipt.read_bytes())
        receipt["source_path"] = str(self.fixture.unrelated_source)
        receipt["source_head_sha256"] = sha256_bytes(
            self.fixture.head_blob(self.fixture.unrelated_source)
        )
        raw = canonical_json_bytes(receipt)
        self.fixture.parent_receipt.write_bytes(raw)
        with self.assertRaisesRegex(
            promoter.PromotionError, "parent_lineage_source_registry_mismatch"
        ):
            self.promote(expected_parent_receipt_raw_sha256=sha256_bytes(raw))
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_rejects_parent_publication_id_not_derived_from_descriptor(self) -> None:
        publication_directory = self.fixture.parent_root / ("f" * 64)
        publication_directory.mkdir()
        registry_path = publication_directory / self.fixture.parent_registry.name
        receipt_path = publication_directory / self.fixture.parent_receipt.name
        registry_path.write_bytes(self.fixture.parent_registry.read_bytes())
        receipt = json.loads(self.fixture.parent_receipt.read_bytes())
        receipt["publication_id"] = publication_directory.name
        receipt["publication_directory"] = str(publication_directory)
        receipt["registry_path"] = str(registry_path)
        receipt["receipt_path"] = str(receipt_path)
        raw = canonical_json_bytes(receipt)
        receipt_path.write_bytes(raw)
        with self.assertRaisesRegex(
            promoter.PromotionError, "parent_lineage_publication_id_mismatch"
        ):
            self.promote(
                parent_registry_path=registry_path,
                parent_receipt_path=receipt_path,
                expected_parent_receipt_raw_sha256=sha256_bytes(raw),
            )
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_receipt_separates_runtime_repositories_from_control_bindings(self) -> None:
        runtime_commit = self.fixture.commit
        runtime_repo = self.fixture.root / "separate-runtime"
        self.fixture._git(
            "clone",
            "--quiet",
            "--local",
            "--config",
            "core.autocrlf=false",
            str(self.fixture.repo),
            str(runtime_repo),
        )
        git = Path(r"C:\Program Files\Git\cmd\git.exe")
        executable = str(git) if git.exists() else "git"
        subprocess.run(
            [
                executable,
                "-C",
                str(runtime_repo),
                "remote",
                "set-url",
                "origin",
                "https://example.invalid/separate-runtime.git",
            ],
            check=True,
            capture_output=True,
        )
        registry = json.loads(self.fixture.parent_registry.read_text(encoding="utf-8"))
        runtime = registry["runtimes"][0]
        runtime["canonical_repo"] = str(runtime_repo)
        runtime["canonical_remote_url"] = "https://example.invalid/separate-runtime.git"
        for field in ("canonical_plan_path", "launcher_path", "state_path", "ledger_path"):
            runtime[field] = str(
                runtime_repo / Path(runtime[field]).relative_to(self.fixture.repo)
            )
        for binding in runtime["implementation_bindings"]:
            binding["path"] = str(
                runtime_repo / Path(binding["path"]).relative_to(self.fixture.repo)
            )
        self.fixture.source.write_bytes(canonical_json_bytes(registry))
        self.fixture._git("add", "registry-source.json")
        self.fixture._git("commit", "--quiet", "-m", "route to separate runtime repo")
        self.fixture.commit = self.fixture.head()
        self.fixture._build_parent_publication()
        result = self.promote()
        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["canonical_repositories"],
            [
                {
                    "canonical_repo": str(runtime_repo),
                    "canonical_git_commit": runtime_commit,
                }
            ],
        )
        self.assertTrue(
            all(
                Path(binding["path"]).is_relative_to(self.fixture.repo)
                for binding in receipt["control_bindings"]
            )
        )

    def test_rejects_unready_or_non_public_research_strategy(self) -> None:
        registry = json.loads(self.fixture.parent_registry.read_text(encoding="utf-8"))
        registry["runtimes"][0]["activation_readiness"] = "STAGED_ONLY"
        self.fixture.source.write_bytes(canonical_json_bytes(registry))
        self.fixture._git("add", "registry-source.json")
        self.fixture._git("commit", "--quiet", "-m", "stage unready runtime source")
        self.fixture.commit = self.fixture.head()
        self.fixture._build_parent_publication()
        with self.assertRaisesRegex(
            promoter.PromotionError,
            "active_strategy_not_ready",
        ):
            self.promote()
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_rejects_nested_research_snapshot_without_scheduler_due_state(self) -> None:
        self.fixture.state.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "research_snapshot_v1",
                    "adaptive_cadence": {
                        "status": "IDLE",
                        "next_interval_at_utc": "2026-08-26T04:00:00Z",
                    },
                }
            )
        )
        with self.assertRaisesRegex(
            promoter.PromotionError,
            "active_state_due_contract_invalid",
        ):
            self.promote()
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_rejects_stale_repository_head(self) -> None:
        (self.fixture.repo / "after-parent.txt").write_text("stale\n", encoding="utf-8")
        self.fixture._git("add", "after-parent.txt")
        self.fixture._git("commit", "--quiet", "-m", "head moved")
        with self.assertRaisesRegex(
            promoter.PromotionError,
            "control_plane_commit_mismatch|parent_registry_validation_failed",
        ):
            self.promote()
        self.assertEqual(list(self.fixture.active_root.iterdir()), [])

    def test_parent_toctou_change_is_detected_before_atomic_publish(self) -> None:
        original_publish = promoter._publish_active_pair

        def mutate_then_publish(**kwargs: object) -> tuple[Path, Path]:
            self.fixture.parent_receipt.write_bytes(
                self.fixture.parent_receipt.read_bytes() + b" "
            )
            return original_publish(**kwargs)

        promoter._publish_active_pair = mutate_then_publish
        try:
            with self.assertRaisesRegex(
                promoter.PromotionError,
                "parent_receipt_changed_during_promotion",
            ):
                self.promote()
        finally:
            promoter._publish_active_pair = original_publish
        self.assertEqual(
            [path for path in self.fixture.active_root.iterdir() if path.is_dir()],
            [],
        )

    def test_runtime_artifact_toctou_change_is_detected_before_atomic_publish(self) -> None:
        original_publish = promoter._publish_active_pair

        def mutate_then_publish(**kwargs: object) -> tuple[Path, Path]:
            self.fixture.worker.write_bytes(b"def run():\n    return 'tampered after validation'\n")
            return original_publish(**kwargs)

        promoter._publish_active_pair = mutate_then_publish
        try:
            with self.assertRaisesRegex(
                promoter.PromotionError,
                "runtime_artifact_changed_during_promotion",
            ):
                self.promote()
        finally:
            promoter._publish_active_pair = original_publish
        self.assertEqual(
            [path for path in self.fixture.active_root.iterdir() if path.is_dir()],
            [],
        )

    def test_second_file_failure_leaves_no_half_publication(self) -> None:
        original_write = promoter._write_new_file
        calls = 0

        def fail_second(path: Path, raw: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise promoter.PromotionError("injected_activation_receipt_write_failure")
            original_write(path, raw)

        promoter._write_new_file = fail_second
        try:
            with self.assertRaisesRegex(
                promoter.PromotionError,
                "injected_activation_receipt_write_failure",
            ):
                self.promote()
        finally:
            promoter._write_new_file = original_write
        self.assertEqual(
            [path for path in self.fixture.active_root.iterdir() if path.is_dir()],
            [],
        )


if __name__ == "__main__":
    unittest.main()
