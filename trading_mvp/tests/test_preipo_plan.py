from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_plan import canonical_plan_hash, validate_plan  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPO_ROOT / "docs" / "plans" / "preipo-perpetual-event-planonly-20260826-v11.json"
V10_PLAN = REPO_ROOT / "docs" / "plans" / "preipo-perpetual-event-planonly-20260825-v10.json"
V9_PLAN = REPO_ROOT / "docs" / "plans" / "preipo-perpetual-event-planonly-20260825-v9.json"
V10_FILE_SHA256 = "56d450dba620044fa1662c82d3d1d8381fbfc26a4ed72a6de7aa0ee5e4604d9f"
V9_FILE_SHA256 = "766f0848ea265389422431210902b4150657af5693bbdf3985f008a1549e5324"


class PreIPOPlanTests(unittest.TestCase):
    def test_git_blob_reader_uses_only_fixed_windows_git_with_15s_timeout(self) -> None:
        import preipo_plan

        completed = SimpleNamespace(returncode=0, stdout=b"committed-plan")
        with (
            patch.object(preipo_plan, "os", SimpleNamespace(name="nt"), create=True),
            patch("shutil.which", return_value=r"C:\attacker\git.exe"),
            patch.object(Path, "is_file", return_value=True),
            patch.object(preipo_plan.subprocess, "run", return_value=completed) as run,
        ):
            preipo_plan._git_blob_sha256(PLAN)

        command = run.call_args.args[0]
        self.assertEqual(command[0], r"C:\Program Files\Git\cmd\git.exe")
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_git_blob_reader_uses_only_fixed_posix_git(self) -> None:
        import preipo_plan

        completed = SimpleNamespace(returncode=0, stdout=b"committed-plan")
        with (
            patch.object(preipo_plan, "os", SimpleNamespace(name="posix"), create=True),
            patch("shutil.which", return_value="/tmp/attacker/git"),
            patch.object(Path, "is_file", return_value=True),
            patch.object(preipo_plan.subprocess, "run", return_value=completed) as run,
        ):
            preipo_plan._git_blob_sha256(PLAN)

        self.assertEqual(run.call_args.args[0][0], "/usr/bin/git")

    def test_git_blob_timeout_fails_closed(self) -> None:
        import preipo_plan

        with (
            patch.object(preipo_plan, "os", SimpleNamespace(name="nt"), create=True),
            patch.object(Path, "is_file", return_value=True),
            patch.object(
                preipo_plan.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("git", 15),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "predecessor_git_blob_timeout"):
                preipo_plan._git_blob_sha256(PLAN)

    def test_the_interim_tier_cannot_be_collapsed_into_acceptance(self) -> None:
        """The early read must stay strictly below the acceptance sample.

        The interim tier exists so a verdict can be read sooner without lowering the bar
        that authorises anything. If its number could be raised to meet
        minimum_complete_events, the descriptive read would silently become the
        acceptance decision - which is precisely the shortcut it was built to avoid."""
        import json

        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        gates = plan["acceptance_gates"]
        self.assertLess(
            gates["interim_descriptive_events"], gates["minimum_complete_events"]
        )
        self.assertIs(gates["interim_authorizes"], False)

        collapsed = json.loads(PLAN.read_text(encoding="utf-8"))
        collapsed["acceptance_gates"]["interim_descriptive_events"] = collapsed[
            "acceptance_gates"
        ]["minimum_complete_events"]
        collapsed["plan_hash"] = canonical_plan_hash(
            {k: v for k, v in collapsed.items() if k != "plan_hash"}
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collapsed.json"
            path.write_text(json.dumps(collapsed), encoding="utf-8")
            result = validate_plan(path)
        self.assertFalse(result["ok"])
        self.assertIn("acceptance_interim_tier_not_below_minimum", result["reasons"])

    def test_an_interim_tier_that_authorizes_is_refused(self) -> None:
        import json
        import tempfile

        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        plan["acceptance_gates"]["interim_authorizes"] = True
        plan["plan_hash"] = canonical_plan_hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authorizing.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            result = validate_plan(path)
        self.assertFalse(result["ok"])
        self.assertIn("acceptance_interim_tier_must_not_authorize", result["reasons"])

    def test_the_plan_is_valid_and_collects_exactly_the_declared_venues(self) -> None:
        """Pin the plan to its declaration, not to a frozen pair of venue names.

        The old assertion hard-coded {okx, gate}. That made every venue widening look
        like a test failure and invited fixing it by editing the expected set, which
        would have checked nothing at all. Comparing against REQUIRED_VENUES asserts the
        property that matters: the plan collects where the module says it collects."""
        import preipo_plan

        result = validate_plan(PLAN)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PLAN_OK")
        self.assertEqual(set(result["venues"]), set(preipo_plan.REQUIRED_VENUES))
        self.assertEqual(result["plan_id"], "preipo_perpetual_event_20260826_v11")

    def test_every_collected_venue_has_an_adapter(self) -> None:
        """A venue may be declared without an adapter only while it is a candidate.

        Once it is in `venues` the automation will try to build an adapter for it on the
        next tick, and a missing one is a hard failure rather than a deferred venue."""
        import preipo_adapters
        import preipo_plan

        for venue in preipo_plan.REQUIRED_VENUES:
            with self.subTest(venue=venue):
                self.assertIn(venue, preipo_adapters.ADAPTERS)

    def test_candidates_and_collected_venues_do_not_overlap(self) -> None:
        import preipo_plan

        self.assertEqual(
            set(preipo_plan.REQUIRED_VENUES) & set(preipo_plan.REQUIRED_CANDIDATE_VENUES),
            set(),
        )

    def test_plan_hash_is_canonical_and_excludes_stored_hash(self) -> None:
        import json

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertEqual(payload["plan_hash"], canonical_plan_hash(payload))

    def test_bybit_is_candidate_only_until_official_contract_and_timestamp_method(self) -> None:
        import json

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertNotIn("bybit", payload["venues"])
        self.assertIn("bybit", payload["candidate_venues"])
        self.assertIn("official pre-IPO contract", payload["bybit_extension_condition"])
        self.assertFalse(payload["proxy_acceptance_allowed"])

    def test_collection_schedule_starts_at_six_hours_with_five_minute_capture(self) -> None:
        import json

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        automation = payload["automation"]
        self.assertEqual(automation["schedule_interval_sec"], 6 * 60 * 60)
        self.assertEqual(automation["scheduler_wake_interval_sec"], 5 * 60)
        self.assertEqual(automation["capture_duration_sec"], 5 * 60)
        self.assertEqual(payload["recovery_contract"]["interval_sec"], 6 * 60 * 60)

    def test_v11_supersedes_v10_without_reusing_its_identity(self) -> None:
        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertEqual(payload["supersedes_plan_id"], "preipo_perpetual_event_20260825_v10")
        self.assertEqual(
            payload["supersedes_plan_hash"],
            "bdfb567da778f4f7f6ac7c6b1625fcd7d5013ab42734e15e3037ad3679db0f13",
        )
        self.assertEqual(
            payload["supersedes_plan_file_sha256"],
            V10_FILE_SHA256,
        )

    def test_v11_validator_rejects_backdated_supersession(self) -> None:
        import tempfile

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        superseded = json.loads(V10_PLAN.read_text(encoding="utf-8"))
        payload["generated_at_utc"] = superseded["generated_at_utc"]
        payload["plan_hash"] = canonical_plan_hash(payload)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backdated.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = validate_plan(path)

        self.assertFalse(result["ok"], result)
        self.assertIn(
            "generated_at_utc_not_after_superseded_plan", result["reasons"]
        )

    def test_v11_validator_rejects_superseded_git_blob_mismatch(self) -> None:
        import preipo_plan

        with patch.object(
            preipo_plan,
            "_git_blob_sha256",
            return_value="0" * 64,
        ):
            result = validate_plan(PLAN)

        self.assertFalse(result["ok"], result)
        self.assertIn(
            "superseded_plan_git_blob_sha256_mismatch", result["reasons"]
        )

    def test_v9_bytes_are_preserved(self) -> None:
        self.assertEqual(hashlib.sha256(V9_PLAN.read_bytes()).hexdigest(), V9_FILE_SHA256)

    def test_v10_bytes_are_preserved(self) -> None:
        self.assertEqual(hashlib.sha256(V10_PLAN.read_bytes()).hexdigest(), V10_FILE_SHA256)

    def test_v11_is_only_a_technical_cwe426_rebind(self) -> None:
        v10 = json.loads(V10_PLAN.read_text(encoding="utf-8"))
        v11 = json.loads(PLAN.read_text(encoding="utf-8"))

        technical_top_level = {
            "commands",
            "generated_at_utc",
            "implementation",
            "plan_hash",
            "plan_id",
            "source_bindings",
            "supersedes_plan_file_sha256",
            "supersedes_plan_hash",
            "supersedes_plan_id",
            "supersedes_plan_path",
        }
        self.assertEqual(
            {key: value for key, value in v11.items() if key not in technical_top_level},
            {key: value for key, value in v10.items() if key not in technical_top_level},
        )
        self.assertEqual(
            {
                key: value
                for key, value in v11["source_bindings"].items()
                if key != "technical_rebind"
            },
            {
                key: value
                for key, value in v10["source_bindings"].items()
                if key != "technical_rebind"
            },
        )
        self.assertEqual(
            [(row["role"], row["path"]) for row in v11["implementation"]],
            [(row["role"], row["path"]) for row in v10["implementation"]],
        )
        rebind = v11["source_bindings"]["technical_rebind"]
        self.assertIs(rebind["research_scope_changed"], False)
        self.assertEqual(
            rebind["changed_dimensions"],
            [
                "implementation_exact_byte_sha256",
                "launcher_default_plan",
                "plan_identity",
                "trusted_git_executable_resolution",
            ],
        )

    def test_visible_launcher_defaults_only_to_v11(self) -> None:
        launcher = (
            REPO_ROOT / "tools" / "start_preipo_perpetual_event_automation_visible.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("preipo-perpetual-event-planonly-20260826-v11.json", launcher)
        self.assertIn("use the immutable v11 default", launcher)

    def test_implementation_role_cannot_be_substituted_with_an_arbitrary_file(self) -> None:
        import json
        import tempfile

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        payload["implementation"][0]["path"] = payload["implementation"][1]["path"]
        payload["implementation"][0]["sha256"] = payload["implementation"][1]["sha256"]
        payload["plan_hash"] = canonical_plan_hash(payload)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "substituted.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = validate_plan(path)
        self.assertFalse(result["ok"])
        self.assertIn("implementation_path_mismatch:preipo_event_lifecycle_and_causal_paper_replay", result["reasons"])


if __name__ == "__main__":
    unittest.main()
