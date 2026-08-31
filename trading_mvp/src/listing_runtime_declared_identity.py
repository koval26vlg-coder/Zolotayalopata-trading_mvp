"""What the expansion runtime has declared, read from the runtime rather than from here.

The probe already takes its sample from the runtime: the state it reads is written by the
activated monitor in a separate repository, because that is where collection happens now.
Its classification did not follow. It consulted this repository's copy of the declared
registry, which is frozen at the plan this repository's own lineage binds and cannot
advance - expansion v15 through v20 exist in the runtime with different content, so a
successor here would be a second artifact wearing an existing identity.

The consequence was concrete and silly: fifteen Bitget Reality shares were declared in the
runtime on 2026-08-28 from the venue's own UTA metadata, and the probe here kept listing
them as unresolved and would have gone on asking a question that had been answered.

So the sample and the classification now come from the same place. Two properties make
that safe rather than merely convenient:

**The declarations are parsed, never executed.** ``ast.literal_eval`` on the two dict
literals. This module reads a file from another repository, and reading evidence is not
the same as running it - a module import would execute whatever that file happens to
contain at the moment it is read.

**The file is an artifact, and the plan binds it.** The runtime's classifier is immutable
by its own commit, so binding it by sha256 in the probe plan is a check that stays true,
the same way the equity ticker snapshot is bound. What decides the outcome may not be free
to change under a plan that fixes the question.

This module adds a source of *settled* identities. It never widens acceptance: an entry
here can only take an instrument out of the unresolved set, never put one into the crypto
universe. That decision still requires a human edit in the runtime's own registry.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

# The runtime the activated expansion monitor collects into. Named here rather than
# discovered, for the same reason the probe names its venue: a path that adjusts itself
# to whatever it finds is not a binding.
EXPANSION_RUNTIME_REPO = Path(r"C:\Users\koval\Documents\ZolotyayLopata-listing-momentum-expansion")
RUNTIME_CLASSIFIER_PATH = (
    EXPANSION_RUNTIME_REPO / "trading_mvp/src/listing_spot_asset_class.py"
)

DECLARATION_NAMES = (
    "DECLARED_TOKENIZED_EQUITY_BASES",
    "DECLARED_CRYPTO_TOKEN_BASES",
)


class RuntimeDeclarationError(ValueError):
    """The runtime's declarations cannot be read, or do not look like declarations."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeDeclarationError(message)


def _literal_bases(node: ast.AST, name: str) -> frozenset[str]:
    """One venue's declared bases, from ``frozenset({...})`` or a bare set literal."""
    target = node
    if isinstance(node, ast.Call):
        func = node.func
        _require(
            isinstance(func, ast.Name) and func.id == "frozenset",
            f"{name}: unexpected call in a declaration",
        )
        _require(len(node.args) == 1 and not node.keywords, f"{name}: unexpected call shape")
        target = node.args[0]
    try:
        value = ast.literal_eval(target)
    except (ValueError, SyntaxError, TypeError) as exc:
        raise RuntimeDeclarationError(f"{name}: declaration is not a literal: {exc}") from exc
    _require(isinstance(value, (set, frozenset, list, tuple)), f"{name}: not a set of bases")
    bases = {str(item).strip().upper() for item in value}
    _require(all(bases), f"{name}: an empty base in the declaration")
    return frozenset(bases)


def parse_declarations(source: str, *, label: str = "runtime classifier") -> dict[str, dict[str, frozenset[str]]]:
    """Read the two declared registries out of the runtime's classifier source."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RuntimeDeclarationError(f"{label}: unparsable: {exc}") from exc

    found: dict[str, dict[str, frozenset[str]]] = {}
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        for name in names:
            if name not in DECLARATION_NAMES:
                continue
            value = node.value
            _require(isinstance(value, ast.Dict), f"{name}: not a mapping of venues")
            venues: dict[str, frozenset[str]] = {}
            for key, entry in zip(value.keys, value.values):
                _require(isinstance(key, ast.Constant) and isinstance(key.value, str),
                         f"{name}: a venue key that is not a plain string")
                venues[str(key.value).strip().lower()] = _literal_bases(entry, name)
            found[name] = venues

    for name in DECLARATION_NAMES:
        _require(name in found, f"{label}: {name} not found")
    return found


def declared_pairs(path: Path | None = None) -> frozenset[tuple[str, str]]:
    """Every ``(venue, base)`` the runtime has settled, in either direction.

    Settled is settled: an instrument declared as a tokenised equity and one declared as a
    crypto token are both answered questions, and neither belongs in a probe that exists
    to establish identity."""
    target = Path(path) if path else RUNTIME_CLASSIFIER_PATH
    _require(target.is_file(), f"the runtime classifier is not present: {target}")
    try:
        source = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeDeclarationError(f"the runtime classifier is unreadable: {exc}") from exc
    declarations = parse_declarations(source, label=str(target))
    return frozenset(
        (venue, base)
        for registry in declarations.values()
        for venue, bases in registry.items()
        for base in bases
    )


def provenance(path: Path | None = None) -> dict[str, Any]:
    """What was read and from where, in the form a plan can bind."""
    target = Path(path) if path else RUNTIME_CLASSIFIER_PATH
    _require(target.is_file(), f"the runtime classifier is not present: {target}")
    raw = target.read_bytes()
    declarations = parse_declarations(raw.decode("utf-8"), label=str(target))
    return {
        "classifier_path": str(target),
        "classifier_file_sha256": hashlib.sha256(raw).hexdigest(),
        "declared_pairs": sum(len(b) for r in declarations.values() for b in r.values()),
        "venues": sorted(
            {venue for registry in declarations.values() for venue in registry}
        ),
    }


def available(path: Path | None = None) -> bool:
    """Whether the runtime's declarations can be read, without raising if they cannot.

    A checkout without the sibling runtime still works: the probe falls back to this
    repository's own declarations, which is narrower and therefore asks about more, not
    fewer, instruments. Failing towards a larger question is the safe direction."""
    try:
        declared_pairs(path)
    except RuntimeDeclarationError:
        return False
    return True


__all__ = [
    "DECLARATION_NAMES",
    "EXPANSION_RUNTIME_REPO",
    "RUNTIME_CLASSIFIER_PATH",
    "RuntimeDeclarationError",
    "available",
    "declared_pairs",
    "parse_declarations",
    "provenance",
]
