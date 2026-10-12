"""Two bounded phases: find candidate listings, then read the price path around them.

Split deliberately. The first phase asks the venues what they listed and when, and stops -
so the candidate list can be looked at by a person before ninety candle requests are spent
on it. The second phase reads price paths for candidates that survived that look.

Neither phase concludes anything. What comes out is a distribution to stare at, under an
anchor this module keeps calling a proxy.

Every response is hashed and its bytes counted before anything is parsed, because a
descriptive result whose inputs cannot be re-derived is an anecdote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from premarket_descriptive_history_plan import (
    PLAN_RELATIVE_PATH,
    REPO_ROOT,
    validate_plan,
)

USER_AGENT = "ZolotyayLopata-research/1.0 (public post-hoc market data)"
# Binance publishes its whole spot catalogue in one document and it runs past eight
# megabytes. The bound exists to stop an unbounded read, not to pick a catalogue size, so
# it moves to fit the largest thing actually requested rather than the largest imagined.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

CANDIDATES_RELATIVE = "docs/analysis/premarket-descriptive-history/candidates-v1.json"
PATHS_RELATIVE = "docs/analysis/premarket-descriptive-history/price-paths-v1.json"
# v21. The canonical name above is overwritten by every run, and six runs in one day
# overwrote each other: only the last survived, and every comparison between them lives in
# a log rather than in a file anyone can re-read. Each run now also writes an archive copy
# stamped with its own plan and moment, so the series is on disk instead of in prose.
PATHS_ARCHIVE_DIR = "docs/analysis/premarket-descriptive-history/runs"


class DescriptiveHistoryError(RuntimeError):
    """The collection cannot proceed, or cannot honestly describe what it returned."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_plan(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The plan, validated. Nothing is requested under a plan that does not hold."""
    path = repo_root / PLAN_RELATIVE_PATH
    if not path.is_file():
        raise DescriptiveHistoryError(f"the plan is not present: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    validate_plan(plan, repo_root=repo_root)
    return plan


def http_get_json(url: str, params: dict[str, Any], *, allowed_host: str,
                  timeout_sec: int) -> tuple[Any, dict[str, Any]]:
    """One request, to one declared host, with its bytes recorded before parsing."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != allowed_host:
        raise DescriptiveHistoryError(f"refusing a request off the declared host: {url}")
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            if urllib.parse.urlparse(response.geturl()).hostname != allowed_host:
                raise DescriptiveHistoryError("response came from another host")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DescriptiveHistoryError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DescriptiveHistoryError("response exceeded the readable bound")
    provenance = {
        "url": full,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_bytes": len(raw),
        "observed_at_utc": _iso(_now()),
    }
    try:
        return json.loads(raw.decode("utf-8")), provenance
    except (ValueError, UnicodeDecodeError) as exc:
        raise DescriptiveHistoryError(f"response is not readable JSON: {exc}") from exc


def _okx_candidates(payload: Any, *, instrument_kind: str = "spot") -> list[dict[str, Any]]:
    """OKX publishes ``listTime`` per instrument - a venue-stated listing moment.

    Better than an announcement title for this purpose and cheaper: one request describes
    every spot instrument the venue lists. Still a proxy for the research anchor, because
    it is market metadata rather than an official announcement."""
    out: list[dict[str, Any]] = []
    for row in (payload or {}).get("data") or []:
        inst, list_time = row.get("instId"), row.get("listTime")
        if not inst or not list_time:
            continue
        try:
            ts = int(list_time) // 1000
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        out.append({
            "venue": "okx",
            "instrument_kind": instrument_kind,
            "tick_size": row.get("tickSz"),
            "symbol": str(inst),
            "base": str(inst).split("-")[0],
            "listed_at_ts": ts,
            "listed_at_utc": _iso(datetime.fromtimestamp(ts, timezone.utc)),
            "source": "VENUE_INSTRUMENT_METADATA_LIST_TIME",
        })
    return out


def _bybit_candidates(payload: Any) -> list[dict[str, Any]]:
    """Bybit's announcement index gives a title and a publication time, and this reads no
    further. The title carries the ticker; the moment will come from candles."""
    out: list[dict[str, Any]] = []
    result = (payload or {}).get("result") or {}
    for row in result.get("list") or []:
        title = str(row.get("title") or "")
        published = row.get("publishTime") or row.get("dateTimestamp")
        try:
            ts = int(published) // 1000 if published else 0
        except (TypeError, ValueError):
            ts = 0
        out.append({
            "venue": "bybit",
            "title": title,
            "published_at_ts": ts,
            "published_at_utc": _iso(datetime.fromtimestamp(ts, timezone.utc)) if ts else None,
            "url": str(row.get("url") or ""),
            "source": "VENUE_ANNOUNCEMENT_INDEX_TITLE_ONLY",
        })
    return out


def _gate_candidates(payload: object, *, instrument_kind: str) -> list[dict[str, Any]]:
    """Gate publishes a bare array. Spot carries ``buy_start``, futures ``launch_time``.

    Both are venue-stated listing moments in seconds, the same class of evidence OKX's
    ``listTime`` is - market metadata, not an announcement."""
    field = "buy_start" if instrument_kind == "spot" else "launch_time"
    out: list[dict[str, Any]] = []
    for row in payload if isinstance(payload, list) else []:
        symbol = row.get("id") or row.get("name")
        stamp = row.get(field)
        if not symbol or not stamp:
            continue
        try:
            ts = int(stamp)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        out.append({
            "venue": "gate",
            "instrument_kind": instrument_kind,
            "tick_size": row.get("order_price_round"),
            "symbol": str(symbol),
            "base": str(symbol).split("_")[0],
            "listed_at_ts": ts,
            "listed_at_utc": _iso(datetime.fromtimestamp(ts, timezone.utc)),
            "source": "VENUE_INSTRUMENT_METADATA_" + field.upper(),
        })
    return out


def _bybit_instruments(payload: object, *, instrument_kind: str) -> list[dict[str, Any]]:
    """Bybit's perpetual list carries ``launchTime``; its spot list carries no such field.

    That asymmetry is the finding, not a parsing failure: without a spot listing moment
    there is no anchor, so Bybit cannot join this study the way OKX and Gate do. The rows
    are still read and counted, so the absence is visible in the artifact rather than
    inferred from a venue missing off a chart."""
    out: list[dict[str, Any]] = []
    rows = ((payload or {}).get("result") or {}).get("list") or []
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        stamp = row.get("launchTime")
        ts = 0
        try:
            ts = int(stamp) // 1000 if stamp else 0
        except (TypeError, ValueError):
            ts = 0
        entry: dict[str, Any] = {
            "venue": "bybit",
            "instrument_kind": instrument_kind,
            "tick_size": (row.get("priceFilter") or {}).get("tickSize"),
            "symbol": str(symbol),
            "base": str(row.get("baseCoin") or symbol),
            "source": "VENUE_INSTRUMENT_METADATA_LAUNCH_TIME" if ts else "NO_LISTING_TIME_PUBLISHED",
        }
        if ts > 0:
            entry["listed_at_ts"] = ts
            entry["listed_at_utc"] = _iso(datetime.fromtimestamp(ts, timezone.utc))
        out.append(entry)
    return out


def _binance_instruments(payload: object, *, instrument_kind: str) -> list[dict[str, Any]]:
    """Binance perpetuals carry ``onboardDate``; spot symbols carry no listing field.

    The spot rows are still returned, without a moment, because the anchor phase needs to
    know which spot symbols exist before spending a request asking when each began."""
    out: list[dict[str, Any]] = []
    for row in (payload or {}).get("symbols") or []:
        symbol = row.get("symbol")
        if not symbol or row.get("status") not in (None, "TRADING"):
            continue
        if instrument_kind == "swap" and row.get("contractType") != "PERPETUAL":
            continue
        tick = None
        for f in row.get("filters") or []:
            if f.get("filterType") == "PRICE_FILTER":
                tick = f.get("tickSize")
        entry: dict[str, Any] = {
            "venue": "binance",
            "instrument_kind": instrument_kind,
            "tick_size": tick,
            "symbol": str(symbol),
            "base": str(row.get("baseAsset") or ""),
            "quote": str(row.get("quoteAsset") or ""),
            "source": "VENUE_INSTRUMENT_METADATA",
        }
        stamp = row.get("onboardDate")
        try:
            ts = int(stamp) // 1000 if stamp else 0
        except (TypeError, ValueError):
            ts = 0
        if ts > 0:
            entry["listed_at_ts"] = ts
            entry["listed_at_utc"] = _iso(datetime.fromtimestamp(ts, timezone.utc))
            entry["source"] = "VENUE_INSTRUMENT_METADATA_ONBOARD_DATE"
        out.append(entry)
    return out


def _study_population(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Spot listings whose perpetual already existed - what the strategy could have traded.

    The perpetual has to be older than the spot listing, or there was nothing to hold
    across the moment. Everything else in the spot list is a listing the strategy never
    had a position in, and counting it would inflate the population with events that were
    never available."""
    # Earliest per base, not an arbitrary one. A token is listed against several quote
    # currencies - BTC-USDT, BTC-USDC, BTC-TRY - and only the first of them is the moment
    # the token started trading on this venue. Keying on base without taking the minimum
    # silently picked whichever row came last, which is a different event and usually a
    # much later one.
    def earliest(venue: str, kind: str) -> dict[str, dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for row in candidates:
            if row.get("venue") != venue or row.get("instrument_kind") != kind:
                continue
            if not row.get("listed_at_ts"):
                continue
            base = row["base"]
            if base not in best or int(row["listed_at_ts"]) < int(best[base]["listed_at_ts"]):
                best[base] = row
        return best

    spot: dict[str, dict[str, Any]] = {}
    swap: dict[str, dict[str, Any]] = {}
    coverage: dict[str, dict[str, int]] = {}
    for venue in ("okx", "gate", "bybit", "binance"):
        s, w = earliest(venue, "spot"), earliest(venue, "swap")
        coverage[venue] = {"spot_bases_with_a_listing_time": len(s),
                           "perp_bases_with_a_listing_time": len(w)}
        # A venue that publishes no spot listing time has no anchor and cannot contribute.
        if not s or not w:
            continue
        for base, row in s.items():
            spot[f"{venue}:{base}"] = row
        for base, row in w.items():
            swap[f"{venue}:{base}"] = row
    events: list[dict[str, Any]] = []
    perp_after = 0
    for key, s in spot.items():
        base = key.split(":", 1)[1]
        w = swap.get(key)
        if not w:
            continue
        lead = int(s["listed_at_ts"]) - int(w["listed_at_ts"])
        if lead <= 0:
            perp_after += 1
            continue
        events.append({
            "venue": s["venue"],
            "base": base,
            "tick_size": w.get("tick_size"),
            "spot_symbol": s["symbol"],
            "perp_symbol": w["symbol"],
            "spot_listed_at_utc": s["listed_at_utc"],
            "perp_listed_at_utc": w["listed_at_utc"],
            "perp_lead_days": round(lead / 86400.0, 2),
            "proxy_t0_ts": int(s["listed_at_ts"]),
        })
    events.sort(key=lambda e: e["spot_listed_at_utc"], reverse=True)
    return {
        "spot_bases": len(spot),
        "perp_bases": len(swap),
        "venue_coverage": coverage,
        "with_a_perpetual": len(events) + perp_after,
        "perpetual_listed_after_spot": perp_after,
        "study_population": len(events),
        "events": events,
    }


def discover(*, repo_root: Path = REPO_ROOT,
             get: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Phase one. Index requests only; writes a candidate list and stops."""
    plan = load_plan(repo_root)
    getter = get or http_get_json
    bounds = plan["bounds"]
    discovery = plan["discovery"]
    budget = int(discovery["max_index_requests"])

    candidates: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    made = 0
    for venue, spec in sorted(discovery["sources"].items()):
        if made >= budget:
            break
        if made:
            sleep(float(bounds["min_interval_between_requests_sec"]))
        url = spec["endpoint"]
        host = urllib.parse.urlparse(url).hostname or ""
        made += 1
        try:
            payload, provenance = getter(
                url, dict(spec["fixed_query"]), allowed_host=host,
                timeout_sec=int(bounds["request_timeout_sec"]),
            )
        except DescriptiveHistoryError as exc:
            errors.append({"venue": venue, "reason": str(exc)})
            continue
        provenance["venue"] = venue
        sources.append(provenance)
        try:
            if venue == "okx":
                rows = _okx_candidates(payload, instrument_kind="spot")
            elif venue == "okx_swap":
                rows = _okx_candidates(payload, instrument_kind="swap")
            elif venue == "gate_spot":
                rows = _gate_candidates(payload, instrument_kind="spot")
            elif venue == "gate_perp":
                rows = _gate_candidates(payload, instrument_kind="swap")
            elif venue == "bybit_spot":
                rows = _bybit_instruments(payload, instrument_kind="spot")
            elif venue == "bybit_perp":
                rows = _bybit_instruments(payload, instrument_kind="swap")
            elif venue == "binance_spot":
                rows = _binance_instruments(payload, instrument_kind="spot")
            elif venue == "binance_perp":
                rows = _binance_instruments(payload, instrument_kind="swap")
            else:
                rows = _bybit_candidates(payload)
        except (AttributeError, TypeError, KeyError) as exc:
            # A shape nobody anticipated is recorded, not fatal: the other venues still
            # have something to say, and a crash here would lose their answers too.
            errors.append({"venue": venue, "reason": f"unreadable shape: {type(exc).__name__}: {exc}"})
            continue
        provenance["rows_read"] = len(rows)
        candidates.extend(rows)

    population = _study_population(candidates)
    result = {
        "schema": "trading_mvp_premarket_descriptive_history_candidates_v1",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "anchor": plan["temporal_anchor"]["t0_kind"],
        "generated_at_utc": _iso(_now()),
        "index_requests_made": made,
        "index_request_budget": budget,
        "sources": sources,
        "errors": errors,
        "candidate_count": len(candidates),
        "population": {k: v for k, v in population.items() if k != "events"},
        "venue_coverage": population["venue_coverage"],
        "study_events": population["events"],
        "candidates": candidates,
        "evidence_use": "DESCRIPTIVE_ONLY",
        "decides_nothing": True,
    }
    target = repo_root / CANDIDATES_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    return {
        "status": "CANDIDATES_WRITTEN",
        "path": str(target),
        "candidates": len(candidates),
        "study_population": population["study_population"],
        "spot_bases": population["spot_bases"],
        "perp_bases": population["perp_bases"],
        "requests_made": made,
        "errors": errors,
        "execution_performed": True,
        "measurement_performed": False,
    }


PREMARKET_LEAD_MAX_DAYS = 30


def _okx_candles(payload: object) -> list[dict[str, float]]:
    """OKX returns newest-first rows of [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm].

    Index 7 is turnover in the quote currency. Read because a flat price on no volume and a
    flat price on heavy volume are different facts, and this study discarded the difference
    until v18."""
    rows: list[dict[str, float]] = []
    for row in (payload or {}).get("data") or []:
        try:
            rows.append({
                "ts": int(row[0]) // 1000,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "quote_volume": float(row[7]) if len(row) > 7 else 0.0,
            })
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort(key=lambda r: r["ts"])
    return rows


def _path_stats(bars: list[dict[str, float]], t0: int, *, bar_sec: int = 60) -> dict[str, object] | None:
    """What the perpetual did across the spot listing moment.

    **A candle timestamp is its opening time, so a bar stamped t0 closes at t0 + bar_sec.**
    An earlier version of this treated ``ts <= t0`` as "before the moment" and took that
    bar's close as the reference - which is the price one whole bar *after* t0. Everything
    it then reported as "the first minute" was really the second, and the first minute -
    the one the listing happens in - was skipped entirely. Measured at second resolution
    on the four events still inside the venue's retention window, price moved -0.35%,
    -3.37% and -0.25% during that skipped minute, so the old figures were a bounce off a
    fall the measurement could not see.

    A bar counts as before the moment only when it has *closed* by then. Returns are
    reported at horizons rather than as one number, because a move that reverts in five
    minutes and one that holds for two hours are different claims, and only the second is
    worth anything."""
    before = [b for b in bars if b["ts"] + bar_sec <= t0]
    after = [b for b in bars if b["ts"] + bar_sec > t0]
    if not before or not after:
        return None
    ref = before[-1]["close"]
    if ref <= 0:
        return None
    out: dict[str, object] = {
        "reference_close": ref,
        "reference_closed_at": before[-1]["ts"] + bar_sec,
        "bar_seconds": bar_sec,
        "bars_before": len(before),
        "bars_after": len(after),
    }
    for minutes in (1, 5, 15, 30, 35, 40, 45, 50, 55, 60, 75, 90, 120):
        # The bar that closes at t0 + horizon, not the one that opens there.
        cut = [b for b in after if b["ts"] + bar_sec <= t0 + minutes * 60]
        out[f"ret_{minutes}m_pct"] = (
            round((cut[-1]["close"] / ref - 1.0) * 100.0, 4) if cut else None
        )

    # Turnover per segment, as a share of the whole measured window. The question this
    # answers is narrow and worth stating: when a half hour shows no price change, was it
    # quiet or was it untraded? Shares rather than absolutes so tokens of wildly different
    # size can be pooled at all.
    total_turnover = sum(b.get("quote_volume", 0.0) for b in bars)
    out["quote_volume_total"] = round(total_turnover, 2)
    for lo, hi in ((-120, 0), (0, 1), (1, 5), (5, 15), (15, 30), (30, 45), (45, 60),
                   (60, 120)):
        seg = [b for b in bars
               if t0 + lo * 60 <= b["ts"] and b["ts"] + bar_sec <= t0 + hi * 60]
        turnover = sum(b.get("quote_volume", 0.0) for b in seg)
        out[f"vol_share_{lo}_{hi}m"] = (
            round(turnover / total_turnover * 100.0, 3) if total_turnover > 0 else None
        )
        # Absolute turnover per segment as well as the share, so a rate can be formed
        # against the minutes that actually existed rather than the minutes assumed. Three
        # perpetuals in this sample launched inside the control window, and dividing their
        # pre-window turnover by a hard-coded 120 understated their baseline.
        out[f"vol_abs_{lo}_{hi}m"] = round(turnover, 2)
        out[f"bars_{lo}_{hi}m"] = len(seg)

        # Direction. Present only where the venue publishes it; None elsewhere, never zero,
        # because zero would pool as a real observation of perfectly one-sided selling.
        taker_buy = sum(b["taker_buy_quote"] for b in seg if "taker_buy_quote" in b)
        has_side = any("taker_buy_quote" in b for b in seg)
        out[f"taker_buy_share_{lo}_{hi}m"] = (
            round(taker_buy / turnover * 100.0, 3)
            if has_side and turnover > 0 else None
        )
        trades = sum(b["trades"] for b in seg if "trades" in b)
        out[f"trades_{lo}_{hi}m"] = int(trades) if has_side else None
        out[f"avg_trade_quote_{lo}_{hi}m"] = (
            round(turnover / trades, 2) if has_side and trades > 0 else None
        )
    # The control. Same horizons, read backwards from t0, off bars this request already
    # returned. ret_pre60m is the move over the hour *ending* at t0, so it is directly
    # comparable to ret_60m, the move over the hour beginning there. A bar counts only once
    # it has closed, on this side too - the rule that was got wrong before and is now the
    # one thing this function is careful about.
    for minutes in (30, 60, 120):
        cut = [b for b in before if b["ts"] + bar_sec <= t0 - minutes * 60]
        prior = cut[-1]["close"] if cut else 0.0
        out[f"ret_pre{minutes}m_pct"] = (
            round((ref / prior - 1.0) * 100.0, 4) if prior > 0 else None
        )

    window = [b for b in after if b["ts"] + bar_sec <= t0 + 120 * 60]
    if window:
        out["max_up_pct"] = round((max(b["high"] for b in window) / ref - 1.0) * 100.0, 4)
        out["max_down_pct"] = round((min(b["low"] for b in window) / ref - 1.0) * 100.0, 4)
    return out


def _binance_candles(payload: object) -> list[dict[str, float]]:
    """Binance klines are [openTime, o, h, l, c, volume, closeTime, quoteAssetVolume, ...].

    Oldest-first, milliseconds. Index 7 is quote-asset turnover, the same quantity OKX puts
    at index 7 of its own row - comparable across tokens whose unit prices differ wildly."""
    rows: list[dict[str, float]] = []
    for row in payload if isinstance(payload, list) else []:
        try:
            rows.append({
                "ts": int(row[0]) // 1000,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "quote_volume": float(row[7]) if len(row) > 7 else 0.0,
                # v20. Index 8 is the trade count, index 10 the quote turnover of trades
                # where the BUYER was the taker - i.e. flow that crossed the spread upward.
                # Both are already in every response; only OKX lacks an equivalent.
                "trades": float(row[8]) if len(row) > 8 else 0.0,
                "taker_buy_quote": float(row[10]) if len(row) > 10 else 0.0,
            })
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort(key=lambda r: r["ts"])
    return rows


def _candle_request(venue: str, symbol: str, start: int, end: int) -> dict[str, str]:
    """Each venue spells the same window differently; nothing else about them differs."""
    if venue == "okx":
        return {"instId": symbol, "bar": "1m",
                "after": str(end * 1000), "before": str(start * 1000), "limit": "300"}
    if venue == "binance":
        return {"symbol": symbol, "interval": "1m",
                "startTime": str(start * 1000), "endTime": str(end * 1000), "limit": "500"}
    raise DescriptiveHistoryError(f"no candle request shape declared for {venue}")


def _candles_for(venue: str, payload: object) -> list[dict[str, float]]:
    if venue == "okx":
        return _okx_candles(payload)
    if venue == "binance":
        return _binance_candles(payload)
    raise DescriptiveHistoryError(f"no candle reader declared for {venue}")


def measure(*, repo_root: Path = REPO_ROOT,
            get: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Phase two. Candle requests for the events the first phase found."""
    plan = load_plan(repo_root)
    getter = get or http_get_json
    bounds, measurement = plan["bounds"], plan["measurement"]

    candidates_path = repo_root / CANDIDATES_RELATIVE
    if not candidates_path.is_file():
        raise DescriptiveHistoryError("run --discover first; no candidate list on disk")
    found = json.loads(candidates_path.read_text(encoding="utf-8"))
    if found.get("plan_hash") != plan["plan_hash"]:
        raise DescriptiveHistoryError(
            "the candidate list was produced under a different plan; re-run --discover"
        )

    # Only the plausible pre-market cases. A perpetual listed a year before the spot is a
    # perpetual on a token that already traded elsewhere - a different situation, and
    # counting it would answer a question nobody asked.
    # Only venues whose candle endpoint this phase declares. Gate publishes listings and
    # would join the population, but reading its candles is a different endpoint and so a
    # different declaration - measuring it under this one would be a collection the plan
    # does not describe.
    events = [
        e for e in found["study_events"]
        if float(e["perp_lead_days"]) <= PREMARKET_LEAD_MAX_DAYS
        and e.get("venue") in ("okx", "binance")
    ][: int(measurement["max_events"])]

    before_min = int(measurement["window_before_min"])
    after_min = int(measurement["window_after_min"])
    budget = int(measurement["max_candle_requests"])
    basis_spec = measurement["basis_test"]
    basis_budget = int(basis_spec["max_requests"])
    basis_made = 0
    benchmark = measurement["market_benchmark"]
    bench_budget = int(benchmark["max_requests"])
    bench_cache: dict[tuple[str, int], dict[str, Any] | None] = {}
    bench_made = 0

    paths: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    made = 0
    for event in events:
        if made >= budget:
            break
        if made:
            sleep(float(bounds["min_interval_between_requests_sec"]))
        t0 = int(event["proxy_t0_ts"])
        start, end = t0 - before_min * 60, t0 + after_min * 60
        made += 1
        venue = event["venue"]
        endpoint = measurement["perp_candles"][venue]
        host = urllib.parse.urlparse(endpoint).hostname or ""
        try:
            payload, provenance = getter(
                endpoint, _candle_request(venue, event["perp_symbol"], start, end),
                allowed_host=host, timeout_sec=int(bounds["request_timeout_sec"]),
            )
            bars = _candles_for(venue, payload)
        except DescriptiveHistoryError as exc:
            errors.append({"base": event["base"], "venue": venue, "reason": str(exc)})
            continue
        provenance.update({"base": event["base"], "venue": venue, "bars_read": len(bars)})
        sources.append(provenance)
        stats = _path_stats(bars, t0)

        if stats is not None:
            bench_key = (venue, t0)
            if bench_key not in bench_cache and bench_made < bench_budget:
                sleep(float(bounds["min_interval_between_requests_sec"]))
                bench_made += 1
                try:
                    bench_payload, bench_prov = getter(
                        endpoint,
                        _candle_request(venue, benchmark["symbols"][venue], start, end),
                        allowed_host=host, timeout_sec=int(bounds["request_timeout_sec"]),
                    )
                    bench_cache[bench_key] = _path_stats(
                        _candles_for(venue, bench_payload), t0)
                    bench_prov.update(
                        {"benchmark": benchmark["symbols"][venue], "venue": venue})
                    sources.append(bench_prov)
                except DescriptiveHistoryError as exc:
                    errors.append({"base": "BENCHMARK", "venue": venue, "reason": str(exc)})
                    bench_cache[bench_key] = None
            # The basis. Its own budget and its own counter, because a phase sharing
            # one already reported starvation as a measured zero once in this study.
            if basis_made < basis_budget:
                spot_symbol = (event["base"] + "-USDT" if venue == "okx"
                               else event["base"] + "USDT")
                spot_endpoint = measurement["spot_candles"][venue]
                spot_host = urllib.parse.urlparse(spot_endpoint).hostname or ""
                sleep(float(bounds["min_interval_between_requests_sec"]))
                basis_made += 1
                try:
                    spot_payload, spot_prov = getter(
                        spot_endpoint,
                        _candle_request(venue, spot_symbol, start, end),
                        allowed_host=spot_host,
                        timeout_sec=int(bounds["request_timeout_sec"]),
                    )
                    spot_bars = {b["ts"]: b for b in _candles_for(venue, spot_payload)}
                    spot_prov.update({"spot_symbol": spot_symbol, "venue": venue,
                                      "bars_read": len(spot_bars)})
                    sources.append(spot_prov)
                except DescriptiveHistoryError as exc:
                    errors.append({"base": event["base"], "venue": venue,
                                   "reason": "spot: " + str(exc)})
                    spot_bars = {}
                perp_bars = {b["ts"]: b for b in bars}
                for minutes in basis_spec["horizons_min"]:
                    # The bar that CLOSES at t0 + horizon on both legs, so the two prices
                    # are the same instant on the same venue - the only comparison that
                    # makes a basis mean anything.
                    stamp = t0 + minutes * 60 - 60
                    perp_bar, spot_bar = perp_bars.get(stamp), spot_bars.get(stamp)
                    ok = (perp_bar and spot_bar
                          and spot_bar["close"] > 0 and perp_bar["close"] > 0)
                    stats[f"basis_{minutes}m_pct"] = (
                        round((perp_bar["close"] / spot_bar["close"] - 1.0) * 100.0, 4)
                        if ok else None
                    )

            bench_stats = bench_cache.get(bench_key)
            for horizon in ("1m", "5m", "15m", "30m", "35m", "40m", "45m", "50m",
                            "55m", "60m", "75m", "90m", "120m",
                            "pre30m", "pre60m", "pre120m"):
                mine = stats.get(f"ret_{horizon}_pct")
                theirs = bench_stats.get(f"ret_{horizon}_pct") if bench_stats else None
                stats[f"bench_{horizon}_pct"] = theirs
                stats[f"excess_{horizon}_pct"] = (
                    round(mine - theirs, 4)
                    if isinstance(mine, (int, float)) and isinstance(theirs, (int, float))
                    else None
                )

        paths.append({
            **{k: event[k] for k in ("venue", "base", "perp_symbol", "spot_listed_at_utc",
                                     "perp_lead_days", "proxy_t0_ts")},
            "measured": stats is not None,
            "why_not": None if stats else "no bars on both sides of the proxy anchor",
            **(stats or {}),
        })

    measured = [p for p in paths if p.get("measured")]
    result = {
        "schema": "trading_mvp_premarket_descriptive_history_paths_v1",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "anchor": plan["temporal_anchor"]["t0_kind"],
        "anchor_source_class": plan["temporal_anchor"]["t0_source_class"],
        "generated_at_utc": _iso(_now()),
        "events_offered": len(events),
        "candle_requests_made": made,
        "candle_request_budget": budget,
        "measured_events": len(measured),
        "basis_requests_made": basis_made,
        "benchmark_requests_made": bench_made,
        "benchmark_windows": len(bench_cache),
        "benchmark_symbols": benchmark["symbols"],
        "window_before_min": before_min,
        "window_after_min": after_min,
        "sources": sources,
        "errors": errors,
        "paths": paths,
        "evidence_use": "DESCRIPTIVE_ONLY",
        "no_fees_no_spread_no_slippage": True,
        "decides_nothing": True,
    }
    target = repo_root / PATHS_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    target.write_bytes(encoded)

    # The archive name carries the plan and the moment, so two runs can never collide and
    # the file says which code produced it without being opened.
    stamp = result["generated_at_utc"].replace("-", "").replace(":", "")
    archive = repo_root / PATHS_ARCHIVE_DIR / f"price-paths-{stamp}-{plan['plan_id']}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(encoded)

    return {
        "status": "PATHS_WRITTEN",
        "path": str(target),
        "archive_path": str(archive),
        "events_offered": len(events),
        "measured": len(measured),
        "requests_made": made,
        "errors": errors,
        "execution_performed": True,
    }


def _okx_first_bar_at_or_after(getter, endpoint: str, spot_symbol: str, announced: int,
                               timeout_sec: int) -> tuple[int | None, dict[str, Any] | None]:
    """The first spot bar OKX actually produced at or after its announced listing time.

    Measured, not assumed: across seven OKX events the announced ``listTime`` preceded the
    first traded bar by exactly 3600 seconds every time - the venue publishes when a
    listing is scheduled, and trading opens an hour later. Anchoring on the announcement
    put every OKX window in an hour when the pair was not trading at all, which is why
    OKX showed nothing while Binance - anchored on its first actual bar - showed a large
    move. Two anchor definitions in one study is not a venue difference; it is a bug that
    looks like one."""
    payload, provenance = getter(
        endpoint,
        {"instId": spot_symbol, "bar": "1m",
         "after": str((announced + 6 * 3600) * 1000),
         "before": str((announced - 60) * 1000), "limit": "300"},
        allowed_host="www.okx.com", timeout_sec=timeout_sec,
    )
    bars = [b for b in _okx_candles(payload) if b["ts"] >= announced]
    if not bars:
        return None, provenance
    return bars[0]["ts"], provenance


def anchors(*, repo_root: Path = REPO_ROOT,
            get: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Derive the spot moment for a venue that publishes only the perpetual's.

    One request per candidate, newest perpetual first, because that is where pre-market
    listings are. A candidate qualifies when its spot pair started trading *after* the
    perpetual was onboarded and within the pre-market window - the same rule the other
    venues satisfy from metadata alone."""
    plan = load_plan(repo_root)
    getter = get or http_get_json
    spec, bounds = plan["anchor_discovery"], plan["bounds"]
    budget = int(spec["max_requests"])
    host = urllib.parse.urlparse(spec["endpoint"]).hostname or ""

    found = json.loads((repo_root / CANDIDATES_RELATIVE).read_text(encoding="utf-8"))
    rows = found["candidates"]
    perps = sorted(
        (r for r in rows if r.get("venue") == "binance"
         and r.get("instrument_kind") == "swap" and r.get("listed_at_ts")),
        key=lambda r: -int(r["listed_at_ts"]),
    )
    spot_symbols = {
        r["symbol"] for r in rows
        if r.get("venue") == "binance" and r.get("instrument_kind") == "spot"
    }

    events: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    made = 0
    for perp in perps:
        if made >= budget:
            break
        spot = perp["base"] + "USDT"
        if spot not in spot_symbols:
            continue
        if made:
            sleep(float(bounds["min_interval_between_requests_sec"]))
        made += 1
        try:
            payload, provenance = getter(
                spec["endpoint"], {"symbol": spot, **spec["fixed_query"]},
                allowed_host=host, timeout_sec=int(bounds["request_timeout_sec"]),
            )
        except DescriptiveHistoryError as exc:
            errors.append({"symbol": spot, "reason": str(exc)})
            continue
        if not isinstance(payload, list) or not payload:
            continue
        try:
            spot_ts = int(payload[0][0]) // 1000
        except (TypeError, ValueError, IndexError):
            continue
        provenance.update({"symbol": spot, "first_bar_ts": spot_ts})
        sources.append(provenance)
        lead = spot_ts - int(perp["listed_at_ts"])
        if lead <= 0:
            continue
        lead_days = round(lead / 86400.0, 2)
        if lead_days > PREMARKET_LEAD_MAX_DAYS:
            continue
        events.append({
            "venue": "binance",
            "base": perp["base"],
            "spot_symbol": spot,
            "perp_symbol": perp["symbol"],
            "tick_size": perp.get("tick_size"),
            "spot_listed_at_utc": _iso(datetime.fromtimestamp(spot_ts, timezone.utc)),
            "perp_listed_at_utc": perp["listed_at_utc"],
            "perp_lead_days": lead_days,
            "proxy_t0_ts": spot_ts,
        })

    # OKX is re-anchored the same way: on the bar it actually produced, not on the time it
    # announced. Without this the two venues answer different questions and the comparison
    # between them means nothing.
    okx_endpoint = plan["measurement"]["spot_candles"]["okx"]
    okx_budget = int(spec["reanchor_max_requests"])
    okx_made = 0
    okx_shifted = 0
    for event in found["study_events"]:
        if event.get("venue") != "okx" or okx_made >= okx_budget:
            continue
        if float(event.get("perp_lead_days", 999)) > PREMARKET_LEAD_MAX_DAYS:
            continue
        sleep(float(bounds["min_interval_between_requests_sec"]))
        okx_made += 1
        announced = int(event["proxy_t0_ts"])
        try:
            actual, provenance = _okx_first_bar_at_or_after(
                getter, okx_endpoint, event["base"] + "-USDT", announced,
                int(bounds["request_timeout_sec"]),
            )
        except DescriptiveHistoryError as exc:
            errors.append({"symbol": event["base"], "reason": str(exc)})
            continue
        if actual is None:
            event["anchor_note"] = "no spot bar found at or after the announced time"
            continue
        if provenance is not None:
            provenance.update({"symbol": event["base"] + "-USDT", "first_bar_ts": actual})
            sources.append(provenance)
        if actual != announced:
            okx_shifted += 1
            event["announced_t0_ts"] = announced
            event["anchor_shift_sec"] = actual - announced
            event["proxy_t0_ts"] = actual
            event["spot_listed_at_utc"] = _iso(datetime.fromtimestamp(actual, timezone.utc))

    events.sort(key=lambda e: e["spot_listed_at_utc"], reverse=True)
    found["okx_reanchored_from_first_bar"] = okx_shifted
    found["study_events"] = [e for e in found["study_events"] if e.get("venue") != "binance"] + events
    found["binance_anchor_discovery"] = {
        "requests_made": made,
        "budget": budget,
        "perpetuals_considered": len(perps),
        "events_found": len(events),
        "errors": errors,
        "sources": sources[:20],
    }
    (repo_root / CANDIDATES_RELATIVE).write_bytes(
        (json.dumps(found, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    return {
        "status": "ANCHORS_WRITTEN",
        "requests_made": made,
        "perpetuals_considered": len(perps),
        "binance_events": len(events),
        "okx_reanchor_requests": okx_made,
        "okx_reanchored": okx_shifted,
        "errors": len(errors),
        "execution_performed": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--discover", action="store_true",
                         help="phase one: index requests only, writes the candidate list")
    actions.add_argument("--anchors", action="store_true",
                         help="phase one-and-a-half: derive spot moments where the venue publishes none")
    actions.add_argument("--measure", action="store_true",
                         help="phase two: candle requests for the discovered events")
    args = parser.parse_args(argv)
    try:
        action = measure if args.measure else (anchors if args.anchors else discover)
        print(json.dumps(action(), ensure_ascii=False))
        return 0
    except (DescriptiveHistoryError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
