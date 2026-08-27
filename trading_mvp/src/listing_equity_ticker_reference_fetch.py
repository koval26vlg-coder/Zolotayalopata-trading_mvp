"""Fetch the exchange symbol directory once, and freeze it with its provenance.

Two requests, to the directory the exchanges themselves publish, for one thing: which
symbols are listed equities. It is kept separate from every module that reasons about
tickers for the same reason the crypto probe is separate from the proposer - what fetched
the evidence should be readable without wondering what else it did.

The registrar was the first choice and refused: the SEC serves its ticker file only to
callers that identify themselves with a personal contact address, and handing a personal
address to a third party is not something to do quietly on someone's behalf. The exchange
directory asks for no such thing, and answers the question more exactly anyway - the SEC
file lists registrants, of which only some are listed equities.

The snapshot records both URLs, the moment observed, and the hash of each response and of
the rows. A classification made against a reference that can silently change is not
reproducible, and these classifications decide what may enter an acceptance universe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from listing_equity_ticker_reference import (
    REFERENCE_RELATIVE_PATH,
    REPO_ROOT,
    SOURCE_AUTHORITY,
    SOURCE_URLS,
    parse_reference,
)

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
REQUEST_TIMEOUT_SEC = 30
USER_AGENT = "ZolotyayLopata-research/1.0 (public symbol directory)"

# Column names differ between the two files; the symbol is the first field in both, and
# the test-issue flag is named the same. Reading by header rather than by position keeps
# a column being inserted upstream from silently shifting what is read.
SYMBOL_COLUMNS = ("Symbol", "ACT Symbol")
TEST_ISSUE_COLUMN = "Test Issue"
NAME_COLUMN = "Security Name"
ETF_COLUMN = "ETF"


class TickerFetchError(RuntimeError):
    """The fetch cannot proceed, or cannot honestly describe what it returned."""


def http_get(url: str, *, timeout_sec: int = REQUEST_TIMEOUT_SEC) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "") != "www.nasdaqtrader.com":
        raise TickerFetchError(f"refusing a request outside the symbol directory: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            if urllib.parse.urlparse(response.geturl()).hostname != parsed.hostname:
                raise TickerFetchError(f"response came from another host: {response.geturl()}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise TickerFetchError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise TickerFetchError("response exceeded the readable bound")
    return raw


def rows_from_directory(raw: bytes, *, source_url: str) -> list[dict[str, Any]]:
    """Read one pipe-delimited directory file, dropping its trailer and test issues."""
    text = raw.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise TickerFetchError(f"the directory at {source_url} carried no rows")
    header = [column.strip() for column in lines[0].split("|")]
    symbol_column = next((c for c in SYMBOL_COLUMNS if c in header), None)
    if symbol_column is None:
        raise TickerFetchError(f"no symbol column in {source_url}: {header}")
    symbol_index = header.index(symbol_column)
    test_index = header.index(TEST_ISSUE_COLUMN) if TEST_ISSUE_COLUMN in header else None
    name_index = header.index(NAME_COLUMN) if NAME_COLUMN in header else None
    etf_index = header.index(ETF_COLUMN) if ETF_COLUMN in header else None

    rows: list[dict[str, Any]] = []
    for line in lines[1:]:
        # The file ends with a creation-time line that has no symbol of its own.
        if line.startswith("File Creation Time"):
            continue
        fields = line.split("|")
        if len(fields) <= symbol_index:
            continue
        symbol = fields[symbol_index].strip().upper()
        if not symbol:
            continue
        if test_index is not None and len(fields) > test_index:
            if fields[test_index].strip().upper() == "Y":
                # A test issue is a symbol the exchange reserved for its own checks; it is
                # not something a venue would wrap and list.
                continue
        # The directory carries the fund flag itself; taking it from the file beats
        # inferring it from the name, which is what the narrowing falls back to for the
        # things the flag does not cover - warrants, units, preferred shares.
        etf = ""
        if etf_index is not None and len(fields) > etf_index:
            etf = fields[etf_index].strip().upper()
        rows.append(
            {
                "ticker": symbol,
                "name": fields[name_index].strip() if name_index is not None and len(fields) > name_index else "",
                "etf": etf,
                "source_url": source_url,
            }
        )
    if not rows:
        raise TickerFetchError(f"the directory at {source_url} yielded no usable rows")
    return rows


def build_snapshot(
    responses: dict[str, bytes], *, observed_at_utc: str
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for url in SOURCE_URLS:
        raw = responses[url]
        rows.extend(rows_from_directory(raw, source_url=url))
        sources.append(
            {
                "url": url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "response_bytes": len(raw),
            }
        )
    # One symbol can appear in both files; keep the first sighting and count the rest.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        unique.append(row)
    unique.sort(key=lambda row: row["ticker"])

    snapshot: dict[str, Any] = {
        "schema": "trading_mvp_equity_ticker_reference_v1",
        "source_url": SOURCE_URLS[0],
        "source_urls": list(SOURCE_URLS),
        "source_authority": SOURCE_AUTHORITY,
        "observed_at_utc": observed_at_utc,
        "sources": sources,
        "row_count": len(unique),
        "duplicate_symbols_dropped": len(rows) - len(unique),
        "rows": unique,
    }
    snapshot["payload_sha256"] = hashlib.sha256(
        json.dumps(unique, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # Read it back through the consumer before writing, so a snapshot the reference module
    # would refuse is never left on disk looking authoritative.
    parse_reference(snapshot)
    return snapshot


def fetch(
    *,
    repo_root: Path = REPO_ROOT,
    get: Callable[[str], bytes] | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    getter = get or (lambda url: http_get(url))
    moment = (now or (lambda: datetime.now(timezone.utc)))()
    responses = {url: getter(url) for url in SOURCE_URLS}
    snapshot = build_snapshot(
        responses,
        observed_at_utc=moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    target = repo_root / REFERENCE_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {
        "status": "REFERENCE_WRITTEN",
        "path": str(target),
        "row_count": snapshot["row_count"],
        "duplicate_symbols_dropped": snapshot["duplicate_symbols_dropped"],
        "payload_sha256": snapshot["payload_sha256"],
        "observed_at_utc": snapshot["observed_at_utc"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        print(json.dumps(fetch(), ensure_ascii=False))
        return 0
    except (TickerFetchError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FETCH_BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
