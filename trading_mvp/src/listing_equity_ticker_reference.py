"""The listed-equity tickers, from the exchanges rather than from a crypto venue.

The tokenised-equity heuristic can only recognise a wrapper when it knows the thing being
wrapped. Its reference until now was derived from the twenty-eight equities declared by
hand on OKX, which recognises XCRM over CRM and is blind to RULTA over ULTA - so fifteen
tokenised US shares on Bitget came back unclassified, and a probe designed to establish
crypto identity proposed all fifteen as tokens because they pass its test honestly.

The authority on whether a symbol is a listed US equity is the exchange that lists it, not
a venue that lists a wrapper around it. This reads the symbol directory the exchanges
publish - NASDAQ-listed issues and everything else, test issues excluded.

The registrar was tried first and refused: the SEC serves its ticker file only to callers
that identify themselves with a personal contact address. The directory asks for no such
thing, and answers the question more exactly - the SEC file lists registrants, of which
only some are listed equities.

Two properties matter more than coverage:

**It is a frozen snapshot, bound by hash.** The file is fetched once under a plan and read
from disk thereafter. A reference that silently changes underneath a classification would
make yesterday's verdict unreproducible, and the verdicts here decide what may enter an
acceptance universe.

**It answers one question.** Whether a string is a ticker some exchange lists. It says
nothing about whether an instrument on a venue *is* that company's share - that inference
belongs to the heuristic, which requires a wrapper prefix as well, and still produces a
proposal rather than a decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_RELATIVE_PATH = "docs/reference/exchange-symbol-directory-20260827.json"
SOURCE_URLS = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
)
SOURCE_AUTHORITY = "nasdaq_trader_symbol_directory"

_TICKER_RE = re.compile(r"\A[A-Z][A-Z0-9.\-]{0,9}\Z")

# What a tokenised share wraps is an ordinary share in a company, so the narrowed view
# keeps those and drops everything else the directory lists alongside them. This matters
# more than it looks: the wrapper heuristic reads a symbol's remainder against this set,
# and every extra short ticker in it is another chance for a genuine token to collide
# with one. Dropping funds and derivatives halves the three-letter surface.
_COMMON_STOCK_RE = re.compile(
    r"(common stock|common share|ordinary share|class [a-z] (common|ordinary))", re.I
)
_NOT_A_SHARE_RE = re.compile(
    r"(etf|fund|trust|warrant|units?|preferred|depositary"
    r"|notes?|rights?|index|portfolio)",
    re.I,
)


class EquityReferenceError(ValueError):
    """The reference cannot be read, or does not describe what it claims."""


@dataclass(frozen=True)
class EquityTickerReference:
    """A snapshot of listed tickers, with the provenance that makes it checkable."""

    tickers: frozenset[str]
    common_stock: frozenset[str]
    source_url: str
    source_authority: str
    observed_at_utc: str
    payload_sha256: str

    def __contains__(self, symbol: object) -> bool:
        return isinstance(symbol, str) and symbol.strip().upper() in self.tickers


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EquityReferenceError(message)


def parse_reference(payload: Mapping[str, Any]) -> EquityTickerReference:
    """Read a stored snapshot, refusing anything that cannot vouch for itself."""
    _require(isinstance(payload, Mapping), "the reference is not an object")
    for field in ("source_url", "source_authority", "observed_at_utc", "payload_sha256", "rows"):
        _require(bool(payload.get(field)), f"the reference has no {field}")
    _require(
        all(
            str(url).startswith("https://www.nasdaqtrader.com/")
            for url in (payload.get("source_urls") or [payload["source_url"]])
        ),
        "the reference did not come from the exchange symbol directory",
    )
    rows = payload["rows"]
    _require(isinstance(rows, list) and bool(rows), "the reference carries no rows")

    tickers: set[str] = set()
    shares: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("ticker") or "").strip().upper()
        if not _TICKER_RE.match(symbol):
            continue
        tickers.add(symbol)
        name = str(row.get("name") or "")
        if str(row.get("etf") or "").strip().upper() == "Y":
            continue
        if _COMMON_STOCK_RE.search(name) and not _NOT_A_SHARE_RE.search(name):
            shares.add(symbol)
    # A reference that shrank to a handful would quietly stop recognising wrappers, and a
    # heuristic that recognises nothing looks exactly like one that found nothing.
    _require(len(tickers) >= 1000, f"the reference holds only {len(tickers)} usable tickers")
    _require(
        len(shares) >= 1000,
        f"the reference holds only {len(shares)} ordinary shares; the narrowing that "
        "protects the wrapper heuristic would be doing the harm it exists to prevent",
    )

    return EquityTickerReference(
        tickers=frozenset(tickers),
        common_stock=frozenset(shares),
        source_url=str(payload["source_url"]),
        source_authority=str(payload["source_authority"]),
        observed_at_utc=str(payload["observed_at_utc"]),
        payload_sha256=str(payload["payload_sha256"]),
    )


@lru_cache(maxsize=4)
def load_reference(path: str | None = None) -> EquityTickerReference:
    """The frozen snapshot, read from disk. Never fetched here."""
    target = Path(path) if path else REPO_ROOT / REFERENCE_RELATIVE_PATH
    _require(target.is_file(), f"the equity ticker reference is not present: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EquityReferenceError(f"the reference is unreadable: {exc}") from exc
    reference = parse_reference(payload)
    recorded = str(payload.get("payload_sha256"))
    actual = hashlib.sha256(
        json.dumps(payload["rows"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _require(recorded == actual, "the reference rows do not match their recorded hash")
    return reference


def listed_tickers(path: str | None = None) -> frozenset[str]:
    """Every symbol the directory lists, funds and derivatives included."""
    return load_reference(path).tickers


def common_stock_tickers(path: str | None = None) -> frozenset[str]:
    """Only ordinary shares in companies - what a tokenised share can be wrapping.

    This is the set the wrapper heuristic should read. The wide set answers "is this a
    symbol somebody lists"; this one answers "is this a company's share", and the gap
    between them is thousands of short fund tickers that a token symbol can collide
    with by accident."""
    return load_reference(path).common_stock


def available(path: str | None = None) -> bool:
    """Whether a usable reference is present, without raising if it is not.

    Callers fall back to the hand-declared reference when this is false, which keeps the
    heuristic working - narrower, but working - on a checkout that has never fetched it."""
    try:
        load_reference(path)
    except EquityReferenceError:
        return False
    return True


def unresolved_against(symbols: Iterable[str], path: str | None = None) -> list[str]:
    """Which of these are not tickers the directory lists. Useful for reporting a gap."""
    reference = load_reference(path)
    return sorted({str(s).strip().upper() for s in symbols} - reference.tickers)


__all__ = [
    "REFERENCE_RELATIVE_PATH",
    "SOURCE_AUTHORITY",
    "SOURCE_URLS",
    "EquityReferenceError",
    "EquityTickerReference",
    "available",
    "common_stock_tickers",
    "listed_tickers",
    "load_reference",
    "parse_reference",
    "unresolved_against",
]
