"""Reading another repository's declarations is evidence-gathering, not code loading.

This module exists because the probe's sample comes from the expansion runtime while its
classification came from this repository's frozen copy of the registry - so fifteen
instruments declared there stayed "unresolved" here and would have been probed forever.

Two things have to hold for that to be safe. The declarations are parsed and never
executed, because a module import runs whatever the file happens to contain. And the
source is an artifact the plan binds by hash, because a file that decides which questions
get asked cannot be free to move under a plan that fixes the question.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import listing_runtime_declared_identity as runtime_identity  # noqa: E402
from listing_runtime_declared_identity import (  # noqa: E402
    RuntimeDeclarationError,
    declared_pairs,
    parse_declarations,
    provenance,
)

WELL_FORMED = '''
DECLARED_TOKENIZED_EQUITY_BASES: dict[str, frozenset[str]] = {
    "bitget": frozenset({"RULTA", "RAA"}),
    "okx": frozenset({"XCRM"}),
}
DECLARED_CRYPTO_TOKEN_BASES: dict[str, frozenset[str]] = {
    "bitget": frozenset({"ALIGN"}),
}
'''


def write(source: str) -> Path:
    directory = tempfile.mkdtemp(prefix="runtime-declared-")
    path = Path(directory) / "listing_spot_asset_class.py"
    path.write_text(source, encoding="utf-8")
    return path


class ParseTests(unittest.TestCase):
    def test_both_registries_are_read_and_normalised(self) -> None:
        parsed = parse_declarations(WELL_FORMED)
        self.assertEqual(
            {"bitget": frozenset({"RULTA", "RAA"}), "okx": frozenset({"XCRM"})},
            parsed["DECLARED_TOKENIZED_EQUITY_BASES"],
        )
        self.assertEqual(
            {"bitget": frozenset({"ALIGN"})}, parsed["DECLARED_CRYPTO_TOKEN_BASES"]
        )

    def test_settled_is_settled_in_either_direction(self) -> None:
        """An instrument declared as equity and one declared as a token are both answered.

        Neither belongs in a probe whose whole purpose is to establish identity."""
        pairs = declared_pairs(write(WELL_FORMED))
        self.assertIn(("bitget", "RULTA"), pairs)
        self.assertIn(("bitget", "ALIGN"), pairs)
        self.assertIn(("okx", "XCRM"), pairs)
        self.assertEqual(4, len(pairs))

    def test_the_declarations_are_never_executed(self) -> None:
        """A module import would run this. Parsing reads it."""
        hostile = WELL_FORMED + "\nraise SystemExit('this file was executed')\n"
        parsed = parse_declarations(hostile)
        self.assertIn("bitget", parsed["DECLARED_CRYPTO_TOKEN_BASES"])

    def test_a_declaration_that_is_not_a_literal_is_refused(self) -> None:
        # Computed membership is exactly what must not pass: the registry is a reviewed
        # list of identities, and something assembled at import time is not reviewable.
        for source, expected in (
            ('DECLARED_TOKENIZED_EQUITY_BASES = {"bitget": frozenset(load())}\n'
             'DECLARED_CRYPTO_TOKEN_BASES = {}\n', "not a literal"),
            ('DECLARED_TOKENIZED_EQUITY_BASES = build()\n'
             'DECLARED_CRYPTO_TOKEN_BASES = {}\n', "not a mapping of venues"),
            ('DECLARED_TOKENIZED_EQUITY_BASES = {KEY: frozenset({"A"})}\n'
             'DECLARED_CRYPTO_TOKEN_BASES = {}\n', "not a plain string"),
            ('DECLARED_TOKENIZED_EQUITY_BASES = {"bitget": set_of(1)}\n'
             'DECLARED_CRYPTO_TOKEN_BASES = {}\n', "unexpected call"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(RuntimeDeclarationError, expected):
                    parse_declarations(source)

    def test_a_file_missing_either_registry_is_refused(self) -> None:
        with self.assertRaisesRegex(RuntimeDeclarationError, "DECLARED_CRYPTO_TOKEN_BASES"):
            parse_declarations('DECLARED_TOKENIZED_EQUITY_BASES = {}\n')

    def test_an_unparsable_file_is_refused_rather_than_read_as_empty(self) -> None:
        # Empty would silently widen nothing and narrow nothing, which reads as "the
        # runtime has declared nothing" - a false statement that costs a probe run.
        with self.assertRaisesRegex(RuntimeDeclarationError, "unparsable"):
            parse_declarations("def (:\n")

    def test_an_absent_runtime_is_reported_not_raised_at_the_caller(self) -> None:
        """A checkout without the sibling runtime still works, and asks more questions.

        Falling back to this repository's own registry is narrower, so the unresolved set
        is larger. Failing towards a bigger question is the safe direction."""
        missing = Path(tempfile.mkdtemp(prefix="runtime-absent-")) / "nothing.py"
        self.assertFalse(runtime_identity.available(missing))
        with self.assertRaisesRegex(RuntimeDeclarationError, "not present"):
            declared_pairs(missing)


class ProvenanceTests(unittest.TestCase):
    def test_provenance_names_the_file_and_its_bytes(self) -> None:
        import hashlib

        path = write(WELL_FORMED)
        record = provenance(path)
        self.assertEqual(str(path), record["classifier_path"])
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(), record["classifier_file_sha256"]
        )
        self.assertEqual(4, record["declared_pairs"])
        self.assertEqual(["bitget", "okx"], record["venues"])

    def test_the_checked_in_runtime_is_readable_and_declares_something(self) -> None:
        """Not a mock: the real sibling repository, read the way the plan reads it."""
        if not runtime_identity.available():
            self.skipTest("the expansion runtime is not checked out beside this repository")
        pairs = declared_pairs()
        self.assertTrue(pairs)
        self.assertTrue(all(v == v.lower() and b == b.upper() for v, b in pairs))


if __name__ == "__main__":
    unittest.main()
