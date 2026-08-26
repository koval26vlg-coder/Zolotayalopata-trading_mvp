from __future__ import annotations

import ast

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


class CryptoIdentityProbePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = build_plan(generated_at_utc=STAMP)

    def test_the_issued_plan_validates(self) -> None:
        path = plan_module.REPO_ROOT / plan_module.PLAN_RELATIVE_PATH
        self.assertTrue(path.is_file(), path)
        validate_plan(json.loads(path.read_text(encoding="utf-8")))

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
