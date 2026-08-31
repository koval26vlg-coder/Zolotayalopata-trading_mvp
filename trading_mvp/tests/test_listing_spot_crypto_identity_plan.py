from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import listing_runtime_declared_identity as runtime_identity  # noqa: E402
import listing_spot_crypto_identity_plan as plan_module  # noqa: E402
from listing_spot_crypto_identity_plan import (  # noqa: E402
    CryptoIdentityPlanError,
    build_plan,
    observed_pairs,
    validate_plan,
)

STAMP = "2026-08-26T12:00:00Z"

# Modules that actually open a connection. urllib.parse is not among them: parsing a URL
# to check which host published a claim is the opposite of fetching from it, and a check
# that forbade the whole urllib package would forbid reading the evidence carefully.
NETWORK_MODULES = (
    "requests",
    "urllib.request",
    "urllib.error",
    "http.client",
    "socket",
    "aiohttp",
    "httpx",
    "websockets",
)


def _imported_modules(path: Path) -> set[str]:
    """Every module this file imports, by full dotted name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CryptoIdentityProbePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = build_plan(generated_at_utc=STAMP)

    def test_the_issued_plan_validates(self) -> None:
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        self.assertTrue(path.is_file(), path)
        validate_plan(json.loads(path.read_text(encoding="utf-8")))

    def test_the_module_and_its_artifacts_agree_on_which_plan_this_is(self) -> None:
        """Derived, not named.

        This test used to spell out the current and previous version, which made every
        reissue a test edit and taught nothing: the property worth pinning is that the
        module, the file it writes, and the file it supersedes all agree - and that a
        plan never points at itself as its own predecessor."""
        self.assertEqual(plan_module.PLAN_ID, self.plan["plan_id"])
        self.assertTrue(
            plan_module.PLAN_RELATIVE_PATH.endswith(".json"),
            plan_module.PLAN_RELATIVE_PATH,
        )
        self.assertNotEqual(
            plan_module.PLAN_RELATIVE_PATH, plan_module.PREVIOUS_PLAN_RELATIVE_PATH
        )
        previous = plan_module.REPO_ROOT / plan_module.PREVIOUS_PLAN_RELATIVE_PATH
        self.assertTrue(previous.is_file(), previous)
        self.assertEqual(
            json.loads(previous.read_text(encoding="utf-8"))["plan_id"],
            self.plan["supersedes"]["plan_id"],
        )

    def test_the_plan_records_what_it_supersedes_and_binds_it(self) -> None:
        """This family issued six versions in two days with the chain living only in
        filenames. A version number is a convention; this is the artifact saying what it
        replaced, in bytes."""
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        issued = json.loads(path.read_text(encoding="utf-8"))
        superseded = issued["supersedes"]
        previous_path = Path(superseded["plan_path"])
        self.assertTrue(previous_path.is_file(), previous_path)
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        self.assertEqual(previous["plan_id"], superseded["plan_id"])
        self.assertEqual(previous["plan_hash"], superseded["plan_hash"])
        self.assertNotEqual(issued["plan_id"], superseded["plan_id"])

    def test_a_broken_or_absent_chain_is_refused(self) -> None:
        """Each case asserts the reason, not just the refusal.

        This module cannot be mutation-tested the usual way - the issued plan binds the
        generator by hash, so editing it fails on the implementation binding before the
        chain check is ever reached. Naming the expected reason is what proves these cases
        exercise the chain rather than tripping over something else on the way."""
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        issued = json.loads(path.read_text(encoding="utf-8"))
        good = issued["supersedes"]
        # Self-supersession has to be built so that the id and hash agree with the file
        # it points at, or it is refused for naming the wrong plan and the guard against
        # a plan superseding itself is never reached.
        itself = {
            "plan_id": issued["plan_id"],
            "plan_hash": issued["plan_hash"],
            "plan_file_sha256": file_sha256(path),
            "plan_path": str(path),
        }
        for broken, expected in (
            ({}, "supersedes block"),
            ({**good, "plan_hash": "c" * 64}, "superseded plan hash"),
            ({**good, "plan_file_sha256": "c" * 64}, "superseded plan file sha256"),
            ({**good, "plan_id": "listing_spot_crypto_identity_probe_20260827_v1"},
             "superseded plan id"),
            ({**good, "plan_path": str(path.with_name("absent.json"))},
             "superseded plan missing"),
            (itself, "cannot supersede itself"),
        ):
            with self.subTest(expected=expected):
                candidate = {**issued, "supersedes": broken}
                candidate["plan_hash"] = plan_module.canonical_hash(candidate)
                with self.assertRaisesRegex(CryptoIdentityPlanError, expected):
                    validate_plan(candidate)

    def test_a_sample_that_has_moved_on_does_not_invalidate_the_plan(self) -> None:
        """The sample binding is provenance, not authorisation.

        It names the observed state the bases were read out of. That file is rewritten by
        every tick of the expansion monitor, and the collector never opens it - the bases
        are frozen in the plan. Requiring the live file to still match made the artifact
        stop validating within hours of being issued, and took nine tests with it the
        first time the automation completed a tick."""
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        issued = json.loads(path.read_text(encoding="utf-8"))
        moved = {
            **issued,
            "sample_binding": {**issued["sample_binding"], "state_file_sha256": "b" * 64},
        }
        # Re-stamped, or this would fail on the plan hash and prove nothing about the
        # sample - the mutation has to be the only thing under test.
        moved["plan_hash"] = plan_module.canonical_hash(moved)
        validate_plan(moved)

    def test_a_plan_that_cannot_say_what_it_was_derived_from_is_still_refused(self) -> None:
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        issued = json.loads(path.read_text(encoding="utf-8"))
        for broken in (
            {},
            {**issued["sample_binding"], "state_file_sha256": "not a hash"},
            {**issued["sample_binding"], "state_file_sha256": ""},
            {**issued["sample_binding"], "state_path": "relative/state.json"},
            {**issued["sample_binding"], "state_path": ""},
        ):
            with self.subTest(broken=sorted(broken)):
                candidate = {**issued, "sample_binding": broken}
                candidate["plan_hash"] = plan_module.canonical_hash(candidate)
                with self.assertRaises(CryptoIdentityPlanError):
                    validate_plan(candidate)

    def test_bases_are_derived_from_the_collected_sample_not_typed(self) -> None:
        pairs = observed_pairs()
        sample_bases = {base for venue, base in pairs if venue == plan_module.PROBE_VENUE}
        for base in self.plan["probe"]["bases"]:
            self.assertIn(base, sample_bases)
        self.assertEqual(
            self.plan["sample_binding"]["observed_pairs"], len(pairs)
        )

    def test_the_sample_state_is_bound_by_hash(self) -> None:
        binding = self.plan["sample_binding"]
        state = Path(binding["state_path"])
        self.assertTrue(state.is_file())
        import hashlib

        self.assertEqual(
            hashlib.sha256(state.read_bytes()).hexdigest(), binding["state_file_sha256"]
        )

    def test_already_classified_instruments_are_not_probed(self) -> None:
        # The 28 OKX tokenised equities have a settled identity and must not appear.
        self.assertNotIn("XCRM", self.plan["probe"]["bases"])
        self.assertEqual(plan_module.PROBE_VENUE, self.plan["probe"]["venue"])

    def test_a_rebind_may_narrow_the_question_but_never_silently(self) -> None:
        """The scope does legitimately change, and the change has to be declared.

        This started as "the bases must be identical across a rebind", which is right
        for a technical rebind and wrong as an absolute: an instrument whose identity
        has been declared stops being unresolved, and a probe that kept asking about it
        would collect an answer it already has. So the difference is declared and has to
        account for itself exactly - a forgotten base and an invented one both fail."""
        previous_path = plan_module.REPO_ROOT / plan_module.PREVIOUS_PLAN_RELATIVE_PATH
        before = json.loads(previous_path.read_text(encoding="utf-8"))["probe"]["bases"]
        current = self.plan["probe"]["bases"]
        scope = self.plan["scope_change"]
        self.assertEqual(sorted(set(before) - set(current)), scope["bases_removed"])
        self.assertEqual(sorted(set(current) - set(before)), scope["bases_added"])
        self.assertEqual(bool(scope["bases_removed"] or scope["bases_added"]),
                         scope["declared"])
        if scope["declared"]:
            self.assertTrue(scope["reason"].strip())

    def test_an_unaccounted_scope_change_is_refused(self) -> None:
        """The cases are built against whatever the truth currently is.

        A first version of this hard-coded them, and half of them silently passed the
        moment the scope stopped changing - an empty removal list is a defect when
        fifteen bases were dropped and the plain truth when none were."""
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        issued = json.loads(path.read_text(encoding="utf-8"))
        good = issued["scope_change"]
        broken = [
            {**good, "declared": not good["declared"]},
            {**good, "bases_added": [*good["bases_added"], "INVENTED"]},
            {**good, "bases_removed": [*good["bases_removed"], "INVENTED"]},
            {k: v for k, v in good.items() if k != "declared"},
            {},
        ]
        if good["bases_removed"]:
            broken.append({**good, "bases_removed": good["bases_removed"][:-1]})
        if good["declared"]:
            broken.append({**good, "reason": "   "})
        for case in broken:
            with self.subTest(case=sorted(case)):
                candidate = {**issued, "scope_change": case}
                candidate["plan_hash"] = plan_module.canonical_hash(candidate)
                with self.assertRaises(CryptoIdentityPlanError):
                    validate_plan(candidate)

    def test_the_runtime_classifier_that_shaped_the_question_is_bound(self) -> None:
        """The sample comes from the runtime, and now so does the classification.

        Which bases are still worth asking about is decided by the runtime's declared
        registry, so that file is bound by hash like any other thing that decides an
        outcome. Citing it without binding it would leave the question free to change
        under a plan whose whole job is to fix the question."""
        import hashlib

        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        issued = json.loads(path.read_text(encoding="utf-8"))
        declared = issued["runtime_declared_identity"]
        if declared is None:
            self.skipTest("the expansion runtime is not checked out beside this repository")
        classifier = Path(declared["classifier_path"])
        self.assertTrue(classifier.is_file(), classifier)
        self.assertEqual(
            hashlib.sha256(classifier.read_bytes()).hexdigest(),
            declared["classifier_file_sha256"],
        )
        self.assertGreater(declared["declared_pairs"], 0)

    def test_a_runtime_classifier_that_has_moved_is_refused(self) -> None:
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        issued = json.loads(path.read_text(encoding="utf-8"))
        if issued["runtime_declared_identity"] is None:
            self.skipTest("the expansion runtime is not checked out beside this repository")
        good = issued["runtime_declared_identity"]
        for broken, expected in (
            ({**good, "classifier_file_sha256": "d" * 64}, "runtime classifier sha256"),
            ({**good, "classifier_path": str(path.with_name("absent.py"))},
             "runtime classifier missing"),
        ):
            with self.subTest(expected=expected):
                candidate = {**issued, "runtime_declared_identity": broken}
                candidate["plan_hash"] = plan_module.canonical_hash(candidate)
                with self.assertRaisesRegex(CryptoIdentityPlanError, expected):
                    validate_plan(candidate)

    def test_bases_the_runtime_has_settled_are_not_asked_about_again(self) -> None:
        """Fifteen Bitget Reality shares, declared in the runtime on 2026-08-28 from the
        venue's own UTA metadata while this repository's registry stayed frozen.

        They were listed as unresolved here for three days. The probe would have gone on
        asking a question that had been answered - which is the cost this binding pays
        for, not a hypothetical."""
        if not runtime_identity.available():
            self.skipTest("the expansion runtime is not checked out beside this repository")
        settled = {b for v, b in runtime_identity.declared_pairs() if v == plan_module.PROBE_VENUE}
        self.assertTrue(settled, "the runtime declares nothing for the probe venue")
        self.assertFalse(settled & set(self.plan["probe"]["bases"]))

    def test_the_plan_cannot_claim_any_authority_it_does_not_have(self) -> None:
        outcome = self.plan["outcome_contract"]
        for flag in ("may_edit_declared_registry", "may_accept_a_listing",
                     "may_authorise_paper_forward", "may_authorise_live_trading"):
            self.assertFalse(outcome[flag], flag)
        self.assertTrue(outcome["human_review_required"])
        self.assertEqual("NONE_IDENTITY_EVIDENCE_ONLY", outcome["acceptance_decision"])
        for flag in ("private_api", "authenticated", "live_orders", "real_capital",
                     "leverage_or_margin", "writes_market_data"):
            self.assertFalse(self.plan[flag], flag)

    def test_the_probe_stays_one_request_per_base(self) -> None:
        probe = self.plan["probe"]
        self.assertLessEqual(len(probe["bases"]), probe["max_requests"])
        self.assertFalse(probe["pagination"])
        self.assertFalse(probe["discovery"])
        self.assertTrue(probe["endpoint"].startswith("https://"))
        self.assertIn(probe["endpoint"].split("/")[2], probe["accepted_hosts"])

    def test_the_endpoint_host_must_be_one_the_proposer_would_trust(self) -> None:
        from listing_spot_crypto_identity import VENUE_EVIDENCE_HOSTS

        host = self.plan["probe"]["endpoint"].split("/")[2]
        self.assertIn(host, VENUE_EVIDENCE_HOSTS[plan_module.PROBE_VENUE])

    def test_validate_rejects_a_tampered_plan(self) -> None:
        mutations = (
            {"live_orders": True},
            {"public_data_only": False},
            {"authenticated": True},
            {"plan_id": "other"},
            {"mode": "Execute"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                tampered = {**self.plan, **mutation}
                with self.assertRaises(CryptoIdentityPlanError):
                    validate_plan(tampered)

    def test_validate_rejects_a_widened_outcome_contract(self) -> None:
        widened = {
            **self.plan,
            "outcome_contract": {
                **self.plan["outcome_contract"],
                "may_edit_declared_registry": True,
            },
        }
        widened["plan_hash"] = plan_module.canonical_hash(widened)
        with self.assertRaisesRegex(CryptoIdentityPlanError, "may_edit_declared_registry"):
            validate_plan(widened)

    def test_validate_rejects_implementation_drift(self) -> None:
        drifted = json.loads(json.dumps(self.plan))
        drifted["implementation"]["files"][0]["sha256"] = "0" * 64
        drifted["plan_hash"] = plan_module.canonical_hash(drifted)
        with self.assertRaisesRegex(CryptoIdentityPlanError, "implementation sha256"):
            validate_plan(drifted)

    def test_a_sample_with_nothing_unresolved_refuses_to_produce_a_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(
                json.dumps({"windows": [{"exchange": "okx", "base": "XCRM"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CryptoIdentityPlanError, "already answered"):
                build_plan(generated_at_utc=STAMP, state_path=state)

    def test_a_sample_larger_than_the_request_bound_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "windows": [
                            {"exchange": "bitget", "base": f"AAA{index}"}
                            for index in range(plan_module.MAX_REQUESTS + 1)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CryptoIdentityPlanError, "request bound"):
                build_plan(generated_at_utc=STAMP, state_path=state)

    def test_an_unreadable_sample_is_refused_rather_than_assumed_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.json"
            with self.assertRaisesRegex(CryptoIdentityPlanError, "state missing"):
                build_plan(generated_at_utc=STAMP, state_path=missing)
            empty = Path(directory) / "empty.json"
            empty.write_text(json.dumps({"windows": []}), encoding="utf-8")
            with self.assertRaisesRegex(CryptoIdentityPlanError, "no windows"):
                build_plan(generated_at_utc=STAMP, state_path=empty)

    def test_the_generator_performs_no_collection(self) -> None:
        # Checked against the imports rather than the text: this module legitimately
        # says the word in prose and in max_requests, so a substring search reports a
        # network dependency that does not exist.
        imported = _imported_modules(SRC_ROOT / "listing_spot_crypto_identity_plan.py")
        for forbidden in NETWORK_MODULES:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imported)


if __name__ == "__main__":
    unittest.main()
