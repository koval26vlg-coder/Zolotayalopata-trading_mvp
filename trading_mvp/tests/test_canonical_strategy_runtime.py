from __future__ import annotations

import contextlib
import copy
import hashlib
import inspect
import io
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

import canonical_strategy_runtime as runtime_registry  # noqa: E402


SCHEMA = "zolotyaylopata.canonical_strategy_runtime.v1"
ACTIVE_SCHEMA = "zolotyaylopata.canonical_strategy_runtime.v2"
CHECKED_IN_TEMPLATE = (
    REPO_ROOT / "docs" / "control" / "canonical_strategy_runtime.staging.json"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_plan_hash(payload: dict) -> str:
    unsigned = dict(payload)
    unsigned.pop("plan_hash", None)
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def git_output(*args: str, repo: Path = REPO_ROOT) -> str:
    git = Path(r"C:\Program Files\Git\cmd\git.exe")
    executable = str(git) if git.exists() else "git"
    return subprocess.check_output(
        [executable, "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        encoding="utf-8",
    ).strip()


class RegistryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._git("init", "--quiet")
        self._git("config", "core.autocrlf", "false")
        self._git("config", "user.email", "canonical-runtime-tests@example.invalid")
        self._git("config", "user.name", "Canonical Runtime Tests")
        self._git(
            "remote",
            "add",
            "origin",
            "https://example.invalid/canonical-runtime-fixture.git",
        )
        self.impl = root / "worker.py"
        self.impl.write_bytes(b"def run():\n    return 'fixture'\n")
        self.launcher = root / "start_visible.ps1"
        self.launcher.write_bytes(b"Write-Output 'fixture visible launcher'\r\n")
        self.state = root / "state.json"
        self.state.write_text(
            '{"status":"IDLE","next_interval_at_utc":"2026-08-25T17:00:00Z"}',
            encoding="utf-8",
        )
        self.ledger = root / "attempts.jsonl"
        self.ledger.write_bytes(b"")
        self.plan = root / "plan.json"
        self._write_plan("list")
        self._git("add", "worker.py", "start_visible.ps1", "plan.json")
        self._git("commit", "--quiet", "-m", "fixture runtime")
        self.registry = root / "registry.json"
        self.payload = self._payload()
        self.write()

    def _git(self, *args: str) -> None:
        git = Path(r"C:\Program Files\Git\cmd\git.exe")
        executable = str(git) if git.exists() else "git"
        subprocess.check_call(
            [executable, "-C", str(self.root), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _write_plan(self, layout: str) -> None:
        binding = {
            "role": "worker",
            "path": str(self.impl),
            "sha256": file_sha256(self.impl),
        }
        implementation: object
        if layout == "list":
            implementation = [binding]
        elif layout == "files":
            implementation = {"files": [binding]}
        elif layout == "files_repo_path":
            implementation = {
                "files": [
                    {
                        "role": binding["role"],
                        "repo_path": self.impl.relative_to(self.root).as_posix(),
                        "sha256": binding["sha256"],
                    }
                ]
            }
        else:  # pragma: no cover - fixture misuse guard
            raise ValueError(layout)
        payload = {
            "schema": "fixture_plan_v1",
            "plan_id": "fixture_plan_20260825_v1",
            "status": "READY_FOR_OFFLINE_VALIDATION",
            "implementation": implementation,
        }
        payload["plan_hash"] = canonical_plan_hash(payload)
        self.plan.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _runtime(self) -> dict:
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        return {
            "strategy_id": "fixture_spot_primary",
            "track_class": "spot_listing",
            "runtime_status": "ACTIVE",
            "activation_readiness": "READY_AFTER_ROUTER_MIGRATION",
            "namespace_prefix": "listing.spot.primary",
            "scope": "crypto_spot_listing",
            "venues": ["gate", "mexc"],
            "canonical_repo": str(self.root),
            "canonical_remote_url": git_output(
                "remote", "get-url", "origin", repo=self.root
            ),
            "canonical_git_commit": git_output("rev-parse", "HEAD", repo=self.root),
            "canonical_plan_path": str(self.plan),
            "canonical_plan_sha256": plan["plan_hash"],
            "canonical_plan_file_sha256": file_sha256(self.plan),
            "canonical_plan_id": plan["plan_id"],
            "canonical_plan_status": plan["status"],
            "launcher_path": str(self.launcher),
            "launcher_sha256": file_sha256(self.launcher),
            "scheduler_routable": False,
            "allowed_modes": ["DISCOVERY", "PAPER_RESEARCH"],
            "state_path": str(self.state),
            "ledger_path": str(self.ledger),
            "public_data_only": True,
            "live_trading_allowed": False,
            "implementation_bindings": [
                {
                    "role": "worker",
                    "path": str(self.impl),
                    "sha256": file_sha256(self.impl),
                }
            ],
            "supersedes": [],
            "retired_aliases": [],
        }

    def _payload(self) -> dict:
        runtime = self._runtime()
        return {
            "schema": SCHEMA,
            "registry_id": "canonical_strategy_runtime_staging_20260825_v1",
            "generated_at_utc": "2026-08-25T16:00:00Z",
            "activation_status": "STAGING_NOT_INSTALLED",
            "canonical_owners": [
                {
                    "strategy_id": runtime["strategy_id"],
                    "namespace_prefix": runtime["namespace_prefix"],
                    "scope": runtime["scope"],
                    "venues": runtime["venues"],
                }
            ],
            "runtimes": [runtime],
        }

    def write(self) -> None:
        self.registry.write_text(
            json.dumps(self.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def add_runtime(
        self,
        *,
        strategy_id: str,
        namespace_prefix: str,
        scope: str,
        venues: list[str],
        runtime_status: str = "ACTIVE",
    ) -> dict:
        runtime = copy.deepcopy(self.payload["runtimes"][0])
        runtime.update(
            {
                "strategy_id": strategy_id,
                "namespace_prefix": namespace_prefix,
                "scope": scope,
                "venues": venues,
                "runtime_status": runtime_status,
            }
        )
        self.payload["runtimes"].append(runtime)
        self.payload["canonical_owners"].append(
            {
                "strategy_id": strategy_id,
                "namespace_prefix": namespace_prefix,
                "scope": scope,
                "venues": venues,
            }
        )
        self.write()
        return runtime


class CanonicalStrategyRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix=".canonical-runtime-test-", dir=REPO_ROOT
        )
        self.addCleanup(self.temp.cleanup)
        self.fixture = RegistryFixture(Path(self.temp.name))

    def validate(self) -> dict:
        return runtime_registry.validate_registry(self.fixture.registry)

    @unittest.skipUnless(os.name == "nt", "Windows PATH hardening")
    def test_validator_git_executable_ignores_path_shadow_on_windows(self) -> None:
        original_which = runtime_registry.shutil.which
        runtime_registry.shutil.which = lambda _: r"C:\untrusted\git.exe"
        try:
            self.assertEqual(
                Path(runtime_registry._git_executable()),
                Path(r"C:\Program Files\Git\cmd\git.exe"),
            )
        finally:
            runtime_registry.shutil.which = original_which

    def test_git_blob_reader_is_bound_to_requested_commit_not_symbolic_head(
        self,
    ) -> None:
        parameters = inspect.signature(runtime_registry._git_head_blob).parameters
        self.assertIn("commit", parameters)
        original_commit = git_output("rev-parse", "HEAD", repo=self.fixture.root)
        original_worker = self.fixture.impl.read_bytes()
        self.fixture.impl.write_bytes(b"def run():\n    return 'new commit'\n")
        self.fixture._git("add", "worker.py")
        self.fixture._git("commit", "--quiet", "-m", "new worker commit")
        self.assertEqual(
            runtime_registry._git_head_blob(
                self.fixture.root,
                self.fixture.impl,
                commit=original_commit,
            ),
            original_worker,
        )

    def test_validator_detects_repo_head_change_during_binding_read(self) -> None:
        declared_head = self.fixture.payload["runtimes"][0]["canonical_git_commit"]
        original_git_output = runtime_registry._git_output
        head_reads = 0

        def changing_git_output(repo: Path, *args: str) -> str:
            nonlocal head_reads
            if args == ("rev-parse", "HEAD"):
                head_reads += 1
                return declared_head if head_reads == 1 else "f" * 40
            return original_git_output(repo, *args)

        runtime_registry._git_output = changing_git_output
        try:
            result = self.validate()
        finally:
            runtime_registry._git_output = original_git_output
        row = result["runtimes"][0]
        self.assertEqual(row["decision"], "BLOCKED_BINDING_MISMATCH")
        self.assertIn("repo_head_changed_during_validation", row["reasons"])

    def test_valid_staged_registry_is_globally_valid_and_never_launches(self) -> None:
        result = self.validate()
        self.assertTrue(result["registry_valid"], result)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["decision"], "STAGED_FAIL_CLOSED")
        self.assertFalse(result["launch_allowed"])
        self.assertEqual(result["runtimes"][0]["decision"], "READY_NOT_ROUTABLE")
        self.assertFalse(result["runtimes"][0]["launch_allowed"])

    def test_valid_active_registry_routes_exactly_one_public_research_runtime(
        self,
    ) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        self.fixture.payload["schema"] = ACTIVE_SCHEMA
        self.fixture.payload["registry_id"] = (
            "canonical_strategy_runtime_active_20260826_v1"
        )
        self.fixture.payload["activation_status"] = "ACTIVE_INSTALLED"
        self.fixture.payload["active_strategy_id"] = runtime["strategy_id"]
        runtime["scheduler_routable"] = True
        self.fixture.write()

        result = self.validate()

        self.assertTrue(result["registry_valid"], result)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["decision"], "ACTIVE_ROUTABLE")
        self.assertTrue(result["launch_allowed"])
        self.assertEqual(result["runtimes"][0]["decision"], "READY_ROUTABLE")
        self.assertTrue(result["runtimes"][0]["launch_allowed"])

    def test_active_registry_requires_exact_active_strategy_id(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        self.fixture.payload["schema"] = ACTIVE_SCHEMA
        self.fixture.payload["registry_id"] = (
            "canonical_strategy_runtime_active_20260826_v1"
        )
        self.fixture.payload["activation_status"] = "ACTIVE_INSTALLED"
        runtime["scheduler_routable"] = True
        self.fixture.write()

        missing = self.validate()

        self.assertFalse(missing["registry_valid"], missing)
        self.assertTrue(
            any("active_strategy_id" in reason for reason in missing["reasons"]),
            missing,
        )

        self.fixture.payload["active_strategy_id"] = "different_strategy"
        self.fixture.write()
        mismatched = self.validate()
        self.assertFalse(mismatched["registry_valid"], mismatched)
        self.assertIn("active_strategy_id_mismatch", mismatched["reasons"])

    def test_active_registry_rejects_unready_runtime_or_unapproved_mode(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        self.fixture.payload["schema"] = ACTIVE_SCHEMA
        self.fixture.payload["registry_id"] = (
            "canonical_strategy_runtime_active_20260826_v1"
        )
        self.fixture.payload["activation_status"] = "ACTIVE_INSTALLED"
        self.fixture.payload["active_strategy_id"] = runtime["strategy_id"]
        runtime["scheduler_routable"] = True

        runtime["activation_readiness"] = "NO_CAPTURE_PLAN_REQUIRES_NEW_ACTIVATION_PLAN"
        self.fixture.write()
        unready = self.validate()
        self.assertFalse(unready["registry_valid"], unready)
        self.assertIn(
            "active_runtime_activation_readiness_invalid:fixture_spot_primary",
            unready["reasons"],
        )

        runtime["activation_readiness"] = "READY_AFTER_ROUTER_MIGRATION"
        runtime["allowed_modes"] = ["DISCOVERY", "DESCRIPTIVE_REPLAY"]
        self.fixture.write()
        unapproved_mode = self.validate()
        self.assertFalse(unapproved_mode["registry_valid"], unapproved_mode)
        self.assertIn(
            "active_runtime_mode_invalid:fixture_spot_primary:DESCRIPTIVE_REPLAY",
            unapproved_mode["reasons"],
        )

    def test_active_registry_requires_due_state_contract_before_routing(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        self.fixture.payload["schema"] = ACTIVE_SCHEMA
        self.fixture.payload["registry_id"] = (
            "canonical_strategy_runtime_active_20260826_v1"
        )
        self.fixture.payload["activation_status"] = "ACTIVE_INSTALLED"
        self.fixture.payload["active_strategy_id"] = runtime["strategy_id"]
        runtime["scheduler_routable"] = True
        self.fixture.state.write_text('{"status":"IDLE"}', encoding="utf-8")
        self.fixture.write()

        result = self.validate()

        self.assertTrue(result["registry_valid"], result)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["decision"], "ACTIVE_RUNTIME_BLOCKED")
        self.assertFalse(result["launch_allowed"])
        self.assertEqual(result["runtimes"][0]["state_status"], "CORRUPT")
        self.assertEqual(
            result["runtimes"][0]["decision"], "RETRY_WITHOUT_LAUNCH"
        )

    def test_active_registry_requires_nonempty_state_status(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        self.fixture.payload["schema"] = ACTIVE_SCHEMA
        self.fixture.payload["registry_id"] = (
            "canonical_strategy_runtime_active_20260826_v1"
        )
        self.fixture.payload["activation_status"] = "ACTIVE_INSTALLED"
        self.fixture.payload["active_strategy_id"] = runtime["strategy_id"]
        runtime["scheduler_routable"] = True
        self.fixture.state.write_text(
            '{"next_interval_at_utc":"2026-08-25T17:00:00Z"}',
            encoding="utf-8",
        )
        self.fixture.write()

        result = self.validate()

        self.assertTrue(result["registry_valid"], result)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["decision"], "ACTIVE_RUNTIME_BLOCKED")
        self.assertEqual(result["runtimes"][0]["state_status"], "CORRUPT")
        self.assertFalse(result["launch_allowed"])

    def test_active_registry_rejects_two_active_routable_runtimes(self) -> None:
        first = self.fixture.payload["runtimes"][0]
        self.fixture.payload["schema"] = ACTIVE_SCHEMA
        self.fixture.payload["registry_id"] = (
            "canonical_strategy_runtime_active_20260826_v1"
        )
        self.fixture.payload["activation_status"] = "ACTIVE_INSTALLED"
        self.fixture.payload["active_strategy_id"] = first["strategy_id"]
        first["scheduler_routable"] = True
        second = self.fixture.add_runtime(
            strategy_id="fixture_crypto_premarket",
            namespace_prefix="listing.crypto.premarket",
            scope="crypto_premarket_perpetual",
            venues=["bybit"],
        )
        second["scheduler_routable"] = True
        self.fixture.write()

        result = self.validate()

        self.assertFalse(result["registry_valid"], result)
        self.assertIn("active_runtime_count_invalid:2", result["reasons"])
        self.assertIn("routable_runtime_count_invalid:2", result["reasons"])

    def test_active_registry_ignores_missing_state_for_inactive_runtime(self) -> None:
        first = self.fixture.payload["runtimes"][0]
        self.fixture.payload["schema"] = ACTIVE_SCHEMA
        self.fixture.payload["registry_id"] = (
            "canonical_strategy_runtime_active_20260826_v1"
        )
        self.fixture.payload["activation_status"] = "ACTIVE_INSTALLED"
        self.fixture.payload["active_strategy_id"] = first["strategy_id"]
        first["scheduler_routable"] = True
        second = self.fixture.add_runtime(
            strategy_id="fixture_crypto_premarket",
            namespace_prefix="listing.crypto.premarket",
            scope="crypto_premarket_perpetual",
            venues=["bybit"],
            runtime_status="INACTIVE",
        )
        second["scheduler_routable"] = False
        second["state_path"] = str(Path(self.temp.name) / "missing-inactive.json")
        self.fixture.write()

        result = self.validate()

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["launch_allowed"], result)
        rows = {row["strategy_id"]: row for row in result["runtimes"]}
        self.assertEqual(
            rows["fixture_crypto_premarket"]["state_status"], "IGNORED_INACTIVE"
        )

    def test_unknown_fields_are_rejected_at_every_schema_level(self) -> None:
        targets = (
            self.fixture.payload,
            self.fixture.payload["canonical_owners"][0],
            self.fixture.payload["runtimes"][0],
            self.fixture.payload["runtimes"][0]["implementation_bindings"][0],
        )
        for index, target in enumerate(targets):
            with self.subTest(index=index):
                target["unexpected_field"] = True
                self.fixture.write()
                result = self.validate()
                self.assertFalse(result["registry_valid"], result)
                self.assertIn("unknown_fields", " ".join(result["reasons"]))
                del target["unexpected_field"]

    def test_duplicate_runtime_or_owner_identity_is_rejected(self) -> None:
        self.fixture.add_runtime(
            strategy_id="fixture_spot_primary",
            namespace_prefix="listing.spot.expansion",
            scope="different_scope",
            venues=["bybit"],
        )
        result = self.validate()
        self.assertFalse(result["registry_valid"], result)
        self.assertIn("duplicate_strategy_id", result["reasons"])
        self.assertIn("duplicate_owner_strategy_id", result["reasons"])

    def test_active_scope_venue_overlap_is_rejected(self) -> None:
        self.fixture.add_runtime(
            strategy_id="fixture_spot_conflict",
            namespace_prefix="listing.spot.conflict",
            scope="crypto_spot_listing",
            venues=["mexc"],
        )
        result = self.validate()
        self.assertFalse(result["registry_valid"], result)
        self.assertTrue(
            any(
                reason.startswith("active_scope_venue_overlap:")
                for reason in result["reasons"]
            ),
            result,
        )

    def test_namespace_prefix_collision_is_rejected(self) -> None:
        self.fixture.add_runtime(
            strategy_id="fixture_nested_namespace",
            namespace_prefix="listing.spot.primary.child",
            scope="other_scope",
            venues=["bybit"],
            runtime_status="INACTIVE",
        )
        result = self.validate()
        self.assertFalse(result["registry_valid"], result)
        self.assertTrue(
            any(
                reason.startswith("namespace_prefix_collision:")
                for reason in result["reasons"]
            ),
            result,
        )

    def test_staging_and_retired_runtimes_can_never_be_scheduler_routable(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        runtime["scheduler_routable"] = True
        self.fixture.write()
        staging_result = self.validate()
        self.assertFalse(staging_result["registry_valid"], staging_result)
        self.assertIn(
            "staging_runtime_routable:fixture_spot_primary", staging_result["reasons"]
        )

        runtime["runtime_status"] = "RETIRED"
        self.fixture.write()
        retired_result = self.validate()
        self.assertIn(
            "retired_runtime_routable:fixture_spot_primary", retired_result["reasons"]
        )

    def test_paths_must_be_absolute_normalized_and_repo_bound(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        runtime["canonical_plan_path"] = "docs/plans/relative.json"
        self.fixture.write()
        result = self.validate()
        self.assertFalse(result["registry_valid"], result)
        self.assertTrue(
            any("path_not_absolute" in reason for reason in result["reasons"]), result
        )

        runtime["canonical_plan_path"] = str(
            Path(self.temp.name) / ".." / "escaped.json"
        )
        self.fixture.write()
        result = self.validate()
        self.assertFalse(result["registry_valid"], result)
        self.assertTrue(
            any("path_not_normalized" in reason for reason in result["reasons"]), result
        )

        runtime["canonical_plan_path"] = str(Path.home() / "outside-plan.json")
        self.fixture.write()
        result = self.validate()
        self.assertFalse(result["registry_valid"], result)
        self.assertTrue(
            any(
                "path_outside_canonical_repo" in reason for reason in result["reasons"]
            ),
            result,
        )

    def test_repository_head_remote_and_plan_identity_are_exact_bindings(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        cases = (
            ("canonical_git_commit", "0" * 40, "repo_head_mismatch"),
            (
                "canonical_remote_url",
                "https://example.invalid/repo.git",
                "repo_remote_mismatch",
            ),
            ("canonical_plan_sha256", "0" * 64, "plan_canonical_hash_mismatch"),
            ("canonical_plan_file_sha256", "0" * 64, "plan_file_sha256_mismatch"),
            ("canonical_plan_id", "wrong_plan", "plan_id_mismatch"),
            ("canonical_plan_status", "WRONG", "plan_status_mismatch"),
        )
        for field, bad_value, expected_reason in cases:
            with self.subTest(field=field):
                original = runtime[field]
                runtime[field] = bad_value
                self.fixture.write()
                result = self.validate()
                self.assertTrue(result["registry_valid"], result)
                row = result["runtimes"][0]
                self.assertEqual(row["decision"], "BLOCKED_BINDING_MISMATCH")
                self.assertIn(expected_reason, " ".join(row["reasons"]))
                runtime[field] = original

    def test_both_plan_implementation_layouts_and_actual_bytes_are_verified(
        self,
    ) -> None:
        for layout in ("list", "files", "files_repo_path"):
            with self.subTest(layout=layout):
                self.fixture._write_plan(layout)
                self.fixture._git("add", "plan.json")
                self.fixture._git(
                    "commit", "--quiet", "--allow-empty", "-m", f"plan layout {layout}"
                )
                self.fixture.payload = self.fixture._payload()
                self.fixture.write()
                result = self.validate()
                self.assertTrue(result["ok"], result)

                self.fixture.impl.write_bytes(b"tampered bytes\n")
                tampered = self.validate()
                self.assertTrue(tampered["registry_valid"], tampered)
                self.assertEqual(
                    tampered["runtimes"][0]["decision"],
                    "BLOCKED_BINDING_MISMATCH",
                )
                self.assertIn(
                    "implementation_bytes_mismatch:worker",
                    tampered["runtimes"][0]["reasons"],
                )
                self.fixture.impl.write_bytes(b"def run():\n    return 'fixture'\n")

    def test_inactive_missing_state_is_ignored(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        runtime["runtime_status"] = "INACTIVE"
        runtime["state_path"] = str(Path(self.temp.name) / "missing-state.json")
        self.fixture.write()
        result = self.validate()
        self.assertTrue(result["ok"], result)
        row = result["runtimes"][0]
        self.assertEqual(row["state_status"], "IGNORED_INACTIVE")
        self.assertEqual(row["decision"], "INACTIVE_NOT_ROUTABLE")

    def test_active_missing_or_corrupt_state_retries_without_launch(self) -> None:
        runtime = self.fixture.payload["runtimes"][0]
        runtime["state_path"] = str(Path(self.temp.name) / "missing-state.json")
        self.fixture.write()
        missing = self.validate()
        self.assertTrue(missing["registry_valid"], missing)
        self.assertFalse(missing["ok"], missing)
        self.assertEqual(missing["runtimes"][0]["decision"], "RETRY_WITHOUT_LAUNCH")
        self.assertEqual(missing["runtimes"][0]["state_status"], "MISSING")
        self.assertFalse(missing["runtimes"][0]["launch_allowed"])

        state = Path(runtime["state_path"])
        state.write_text("not-json", encoding="utf-8")
        corrupt = self.validate()
        self.assertEqual(corrupt["runtimes"][0]["decision"], "RETRY_WITHOUT_LAUNCH")
        self.assertEqual(corrupt["runtimes"][0]["state_status"], "CORRUPT")

    def test_binding_failure_is_isolated_to_one_runtime(self) -> None:
        second = self.fixture.add_runtime(
            strategy_id="fixture_crypto_premarket",
            namespace_prefix="listing.crypto.premarket",
            scope="crypto_premarket_perpetual",
            venues=["bybit"],
        )
        second["canonical_plan_file_sha256"] = "0" * 64
        self.fixture.write()
        result = self.validate()
        self.assertTrue(result["registry_valid"], result)
        decisions = {row["strategy_id"]: row["decision"] for row in result["runtimes"]}
        self.assertEqual(decisions["fixture_spot_primary"], "READY_NOT_ROUTABLE")
        self.assertEqual(
            decisions["fixture_crypto_premarket"], "BLOCKED_BINDING_MISMATCH"
        )
        self.assertFalse(result["ok"])

    def test_dirty_runtime_cannot_rebind_around_the_pinned_git_commit(self) -> None:
        self.fixture.impl.write_bytes(b"def run():\n    return 'dirty-but-rehashed'\n")
        self.fixture._write_plan("files")
        self.fixture.payload = self.fixture._payload()
        self.fixture.write()
        result = self.validate()
        self.assertTrue(result["registry_valid"], result)
        row = result["runtimes"][0]
        self.assertEqual(row["decision"], "BLOCKED_BINDING_MISMATCH")
        self.assertIn("plan_git_blob_mismatch", row["reasons"])
        self.assertIn("implementation_git_blob_mismatch:worker", row["reasons"])

    def test_untracked_launcher_is_never_a_canonical_runtime_binding(self) -> None:
        untracked = self.fixture.root / "untracked_launcher.ps1"
        untracked.write_bytes(b"Write-Output 'untracked'\n")
        runtime = self.fixture.payload["runtimes"][0]
        runtime["launcher_path"] = str(untracked)
        runtime["launcher_sha256"] = file_sha256(untracked)
        self.fixture.write()
        result = self.validate()
        self.assertTrue(result["registry_valid"], result)
        row = result["runtimes"][0]
        self.assertEqual(row["decision"], "BLOCKED_BINDING_MISMATCH")
        self.assertIn("launcher_not_tracked", row["reasons"])

    def test_expected_registry_raw_sha256_is_verified_before_routing(self) -> None:
        expected = file_sha256(self.fixture.registry)
        valid = runtime_registry.validate_registry(
            self.fixture.registry, expected_raw_sha256=expected
        )
        self.assertTrue(valid["registry_valid"], valid)
        mismatch = runtime_registry.validate_registry(
            self.fixture.registry, expected_raw_sha256="0" * 64
        )
        self.assertFalse(mismatch["registry_valid"], mismatch)
        self.assertEqual(mismatch["decision"], "REGISTRY_INVALID")
        self.assertIn("registry_raw_sha256_mismatch", mismatch["reasons"])
        self.assertFalse(mismatch["launch_allowed"])

    def test_legacy_worktree_generator_is_disabled_in_favor_of_external_head_tool(
        self,
    ) -> None:
        old_external = runtime_registry.EXTERNAL_REGISTRY_PATH
        external_existed = old_external.exists()
        external_bytes = old_external.read_bytes() if external_existed else None

        self.fixture.impl.write_bytes(b"def run():\n    return 'updated'\n")
        self.fixture._write_plan("files")
        with self.assertRaisesRegex(ValueError, "external_head_materializer_required"):
            runtime_registry.generate_staged_registry(
                self.fixture.registry,
                generated_at_utc="2026-08-25T17:00:00Z",
            )
        if external_existed:
            self.assertEqual(old_external.read_bytes(), external_bytes)
        else:
            self.assertFalse(old_external.exists())

    def test_cli_validates_expected_raw_sha_and_emits_json(self) -> None:
        expected = file_sha256(self.fixture.registry)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = runtime_registry.main(
                [
                    "--validate",
                    str(self.fixture.registry),
                    "--expected-sha256",
                    expected,
                    "--json",
                ]
            )
        self.assertEqual(exit_code, 0, stdout.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["registry_valid"], result)
        self.assertFalse(result["launch_allowed"])

    def test_checked_in_template_declares_only_four_canonical_fail_closed_runtimes(
        self,
    ) -> None:
        self.assertTrue(CHECKED_IN_TEMPLATE.is_file(), CHECKED_IN_TEMPLATE)
        payload = json.loads(CHECKED_IN_TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], SCHEMA)
        self.assertEqual(payload["activation_status"], "STAGING_NOT_INSTALLED")
        runtimes = {row["strategy_id"]: row for row in payload["runtimes"]}
        self.assertEqual(
            set(runtimes),
            {
                "spot_listing_momentum_mexc_gate_v2",
                "spot_listing_momentum_expansion_v13",
                "crypto_premarket_perpetual_capture_v28",
                "preipo_perpetual_event_v11",
            },
        )
        self.assertNotIn("preipo_candidate_bybit", runtimes)
        self.assertTrue(all(not row["scheduler_routable"] for row in runtimes.values()))
        self.assertTrue(
            all(not row["live_trading_allowed"] for row in runtimes.values())
        )
        self.assertTrue(all(row["public_data_only"] for row in runtimes.values()))
        self.assertIsNone(
            runtimes["crypto_premarket_perpetual_capture_v28"]["launcher_path"]
        )
        self.assertEqual(
            runtimes["preipo_perpetual_event_v11"]["activation_readiness"],
            "BLOCKED_OFFICIAL_FIRST_TRADE_RESOLVER_AND_ROUTER_MIGRATION",
        )
        result = runtime_registry.validate_registry(CHECKED_IN_TEMPLATE)
        self.assertTrue(result["registry_valid"], result)
        self.assertFalse(result["launch_allowed"], result)
        self.assertIn(
            result["decision"], {"STAGED_FAIL_CLOSED", "PARTIAL_RUNTIME_BLOCK"}
        )

    def test_main_repo_runtime_and_control_bindings_disable_eol_conversion(self) -> None:
        payload = json.loads(CHECKED_IN_TEMPLATE.read_text(encoding="utf-8"))
        protected = {
            REPO_ROOT / "docs/control/canonical_strategy_runtime.staging.json",
            REPO_ROOT / "tools/install_listing_strategy_due_coordinator_task.ps1",
            REPO_ROOT / "tools/invoke_listing_strategy_due_coordinator.ps1",
            REPO_ROOT / "trading_mvp/src/canonical_strategy_runtime.py",
            REPO_ROOT / "trading_mvp/src/external_registry_materializer.py",
            REPO_ROOT / "trading_mvp/src/external_registry_promoter.py",
        }
        for runtime in payload["runtimes"]:
            if Path(runtime["canonical_repo"]).resolve() != REPO_ROOT.resolve():
                continue
            protected.add(Path(runtime["canonical_plan_path"]))
            if runtime["launcher_path"] is not None:
                protected.add(Path(runtime["launcher_path"]))
            protected.update(
                Path(row["path"]) for row in runtime["implementation_bindings"]
            )

        for path in sorted(protected):
            relative = path.resolve(strict=False).relative_to(REPO_ROOT).as_posix()
            with self.subTest(path=relative):
                self.assertEqual(
                    git_output("check-attr", "text", "--", relative),
                    f"{relative}: text: unset",
                )


if __name__ == "__main__":
    unittest.main()
