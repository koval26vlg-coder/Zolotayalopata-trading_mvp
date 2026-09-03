"""Watch for a scheduled spot listing, then record the order book across it.

Two modes, deliberately separate.

``--scan`` is one bounded pass over venue metadata. It asks which spot pairs are scheduled to
open, keeps the ones whose perpetual was already trading, and writes them to an armed-events
file. It launches nothing unless a window is about to open. Run it on a timer.

``--capture`` records one armed event: a book snapshot every twenty seconds from two hours
before the opening to two hours after. It is started by ``--scan`` as a detached process and
lives for about four hours.

Nothing here concludes anything. It produces the one observation the retrospective study
could not make and no archive holds.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from premarket_forward_depth_plan import (
    PLAN_RELATIVE_PATH,
    REPO_ROOT,
    validate_plan,
)

try:  # pragma: no cover - the reference is optional and its absence is recorded, not fatal
    from listing_equity_ticker_reference import available as _equity_available
    from listing_equity_ticker_reference import common_stock_tickers as _equity_tickers
except ImportError:  # the watcher must still run without the equity reference module
    _equity_available = None
    _equity_tickers = None

USER_AGENT = "ZolotyayLopata-research/1.0 (public forward market data)"
ARMED_RELATIVE = "docs/analysis/premarket-forward-depth/armed-events.json"
CAPTURE_DIR_RELATIVE = "docs/analysis/premarket-forward-depth/captures"


class ForwardDepthError(RuntimeError):
    """The watch cannot proceed, or cannot honestly describe what it recorded."""


def _now() -> int:
    return int(time.time())


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def load_plan(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    path = repo_root / PLAN_RELATIVE_PATH
    if not path.is_file():
        raise ForwardDepthError(f"the plan is not present: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    validate_plan(plan, repo_root=repo_root)
    return plan


def http_get_json(url: str, params: dict[str, Any], *, allowed_host: str,
                  timeout_sec: int, max_bytes: int) -> tuple[Any, dict[str, Any]]:
    """One request, to one declared host, with its bytes recorded before parsing."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != allowed_host:
        raise ForwardDepthError(f"refusing a request off the declared host: {url}")
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    # Compression asked for explicitly. The scan pulls whole instrument catalogues, and
    # measured on these four endpoints that is 4.16 MB uncompressed against 1.38 MB with
    # gzip - eighteen times smaller on the largest of them. Three of the four honour it;
    # Gate's futures contracts endpoint returns identical bytes either way, which is the
    # venue's choice and not something to work around.
    request = urllib.request.Request(
        full, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            if urllib.parse.urlparse(response.geturl()).hostname != allowed_host:
                raise ForwardDepthError("response came from another host")
            raw = response.read(max_bytes + 1)
            encoding = (response.headers.get("Content-Encoding") or "").lower()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ForwardDepthError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if len(raw) > max_bytes:
        raise ForwardDepthError("response exceeded the readable bound")
    wire_bytes = len(raw)
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, ValueError) as exc:
            raise ForwardDepthError(f"gzip response is not readable: {exc}") from exc
        if len(raw) > max_bytes:
            raise ForwardDepthError("decompressed response exceeded the readable bound")
    provenance = {
        "url": full,
        # Hashed after decompression, so the digest identifies the content rather than a
        # particular transfer encoding and stays comparable across scans.
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_bytes": len(raw),
        "wire_bytes": wire_bytes,
        "content_encoding": encoding or "identity",
        "observed_at_utc": _iso(_now()),
    }
    try:
        return json.loads(raw.decode("utf-8")), provenance
    except (ValueError, UnicodeDecodeError) as exc:
        raise ForwardDepthError(f"response is not readable JSON: {exc}") from exc


# --------------------------------------------------------------------------- schedule


def _okx_rows(payload: Any) -> list[dict[str, Any]]:
    return list((payload or {}).get("data") or [])


def _int_or_none(value: Any, *, divisor: int = 1) -> int | None:
    try:
        out = int(value) // divisor
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _scan_okx(getter, plan, *, timeout, max_bytes) -> list[dict[str, Any]]:
    src = plan["schedule_sources"]
    offset = int(plan["trade_open_offset_sec"]["okx"])
    spot, _ = getter(src["okx_spot"]["endpoint"], src["okx_spot"]["fixed_query"],
                     allowed_host="www.okx.com", timeout_sec=timeout, max_bytes=max_bytes)
    swap, _ = getter(src["okx_swap"]["endpoint"], src["okx_swap"]["fixed_query"],
                     allowed_host="www.okx.com", timeout_sec=timeout, max_bytes=max_bytes)
    perps: dict[str, dict[str, Any]] = {}
    for row in _okx_rows(swap):
        inst = str(row.get("instId") or "")
        if inst.endswith("-USDT-SWAP"):
            launched = _int_or_none(row.get("listTime"), divisor=1000)
            if launched:
                perps[inst.split("-")[0]] = {"symbol": inst, "launched_ts": launched,
                                             "ct_val": row.get("ctVal"),
                                             "tick": row.get("tickSz")}
    out = []
    for row in _okx_rows(spot):
        inst = str(row.get("instId") or "")
        if not inst.endswith("-USDT"):
            continue
        listed = _int_or_none(row.get("listTime"), divisor=1000)
        if listed is None:
            continue
        base = inst.split("-")[0]
        perp = perps.get(base)
        if not perp:
            continue
        out.append({
            "venue": "okx", "base": base,
            "spot_symbol": inst, "perp_symbol": perp["symbol"],
            "spot_state": row.get("state"),
            "schedule_ts": listed,
            "t0_ts": listed + offset,
            "perp_launched_ts": perp["launched_ts"],
            "perp_ct_val": perp["ct_val"],
            "spot_tick": row.get("tickSz"),
            "schedule_field": "listTime",
            "trade_open_offset_sec": offset,
        })
    return out


def _scan_gate(getter, plan, *, timeout, max_bytes) -> list[dict[str, Any]]:
    src = plan["schedule_sources"]
    offset = int(plan["trade_open_offset_sec"]["gate"])
    spot, _ = getter(src["gate_spot"]["endpoint"], src["gate_spot"]["fixed_query"],
                     allowed_host="api.gateio.ws", timeout_sec=timeout, max_bytes=max_bytes)
    perp, _ = getter(src["gate_perp"]["endpoint"], src["gate_perp"]["fixed_query"],
                     allowed_host="api.gateio.ws", timeout_sec=timeout, max_bytes=max_bytes)
    perps: dict[str, dict[str, Any]] = {}
    for row in perp if isinstance(perp, list) else []:
        name = str(row.get("name") or "")
        if name.endswith("_USDT"):
            launched = _int_or_none(row.get("launch_time"))
            if launched:
                perps[name.split("_")[0]] = {
                    "symbol": name, "launched_ts": launched,
                    "ct_val": row.get("quanto_multiplier"),
                    "tick": row.get("order_price_round"),
                }
    out = []
    for row in spot if isinstance(spot, list) else []:
        pair = str(row.get("id") or "")
        if not pair.endswith("_USDT"):
            continue
        opens = _int_or_none(row.get("buy_start"))
        if opens is None:
            continue
        base = pair.split("_")[0]
        p = perps.get(base)
        if not p:
            continue
        out.append({
            "venue": "gate", "base": base,
            "spot_symbol": pair, "perp_symbol": p["symbol"],
            "spot_state": row.get("trade_status"),
            "schedule_ts": opens,
            "t0_ts": opens + offset,
            "perp_launched_ts": p["launched_ts"],
            "perp_ct_val": p["ct_val"],
            "spot_tick": row.get("precision"),
            "schedule_field": "buy_start",
            "trade_open_offset_sec": offset,
        })
    return out


def equity_note(base: str) -> dict[str, Any]:
    """Whether this base looks like a tokenised equity rather than a crypto token.

    The first captured event was AINVDA on Gate - an NVDA derivative. Whether a tokenised
    share behaves like a token listing is exactly the question this study must not assume,
    since a share has an external reference price and a token does not. The retrospective
    work built a listed-equity reference for precisely this distinction, so it is reused.

    Recorded, never used to drop an event. A forward study that captures once every four
    days cannot afford to discard a capture on a heuristic; the split belongs to analysis,
    where it can be argued with, and the capture is on disk either way."""
    if _equity_available is None or not _equity_available():
        return {"checked": False, "reason": "EQUITY_REFERENCE_UNAVAILABLE"}
    tickers = _equity_tickers()
    upper = base.upper()
    exact = upper in tickers
    # A tokenised share is often the ticker with an issuer prefix or suffix rather than the
    # ticker itself, which is why exact membership alone would have passed AINVDA.
    contained = sorted(
        t for t in tickers
        if len(t) >= 3 and t != upper and (upper.startswith(t) or upper.endswith(t))
    )
    return {
        "checked": True,
        "exact_listed_ticker": exact,
        "contains_listed_ticker": contained[:4],
        "looks_like_equity": bool(exact or contained),
        "note": "RECORDED_NOT_EXCLUDED",
    }


def qualifies(event: dict[str, Any], plan: dict[str, Any], now: int) -> str | None:
    """Why this event is not a pre-market listing, or None when it is one.

    The ordering test is the whole point. An earlier forward scan accepted a token because a
    perpetual existed, and did not notice the perpetual launched ten minutes AFTER the spot.
    A simultaneous launch is a different phenomenon and must not enter this sample."""
    qual = plan["qualification"]
    if event["t0_ts"] <= now:
        return "already open"
    lead = event["t0_ts"] - event["perp_launched_ts"]
    if lead < int(qual["min_lead_sec"]):
        return f"perp leads by only {lead}s - simultaneous or spot-first launch"
    if lead > int(qual["max_lead_days"]) * 86400:
        return f"perp leads by {lead / 86400:.1f} days, past the declared window"
    return None


def scan(*, repo_root: Path = REPO_ROOT,
         get: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
         spawn: bool = True) -> dict[str, Any]:
    plan = load_plan(repo_root)
    getter = get or http_get_json
    cap = plan["capture"]
    timeout = int(cap["request_timeout_sec"])
    max_bytes = int(cap["max_response_bytes"])
    now = _now()

    scheduled: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for name, fn in (("okx", _scan_okx), ("gate", _scan_gate)):
        try:
            scheduled.extend(fn(getter, plan, timeout=timeout, max_bytes=max_bytes))
        except ForwardDepthError as exc:
            errors.append({"venue": name, "reason": str(exc)})

    armed, rejected = [], []
    for event in scheduled:
        reason = qualifies(event, plan, now)
        if reason:
            if event["t0_ts"] > now:
                rejected.append({**{k: event[k] for k in ("venue", "base", "t0_ts")},
                                 "reason": reason})
            continue
        want = int(cap["window_before_min"])
        by_notice = max(0, (event["t0_ts"] - now) // 60)
        by_perp_age = max(0, (event["t0_ts"] - event["perp_launched_ts"]) // 60)
        pre_min = min(want, by_notice, by_perp_age)
        # Which constraint bit. A 64-minute lead can never yield a 120-minute control
        # however early the venue announces - the perpetual did not exist then - and that is
        # a property of the event, not a failure of the capture. The first captured event
        # was exactly this case, and calling it "short notice" would have blamed the venue
        # for the calendar.
        if pre_min >= want:
            bound = "FULL"
        elif by_perp_age <= by_notice:
            bound = "PERP_LAUNCH"
        else:
            bound = "VENUE_NOTICE"
        armed.append({
            **event,
            "t0_utc": _iso(event["t0_ts"]),
            "perp_lead_days": round((event["t0_ts"] - event["perp_launched_ts"]) / 86400, 3),
            "equity_note": equity_note(event["base"]),
            "pre_window_bounded_by": bound,
            "pre_window_by_notice_min": by_notice,
            "pre_window_by_perp_age_min": by_perp_age,
            "capture_from_ts": max(now, event["t0_ts"] - int(cap["window_before_min"]) * 60),
            "capture_to_ts": event["t0_ts"] + int(cap["window_after_min"]) * 60,
            "pre_window_available_min": pre_min,
            "pre_window_short": pre_min < int(cap["window_before_min"]),
            "armed_at_utc": _iso(now),
        })

    armed.sort(key=lambda e: e["t0_ts"])
    path = repo_root / ARMED_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = {}
    if path.is_file():
        previous = json.loads(path.read_text(encoding="utf-8"))
    launched = list(previous.get("capture_launched") or [])

    # How much warning each venue actually gives. The scan cadence was picked out of fear of
    # Gate, whose notice nobody has measured - OKX has been seen publishing at least 7h46m
    # ahead, which any sane cadence covers. Recording when a scheduled event was FIRST seen
    # turns that fear into a number, and once the number exists the cadence follows from it
    # instead of from caution.
    seen = dict(previous.get("first_seen") or {})
    notice = list(previous.get("notice_observed") or [])
    for event in scheduled:
        if event["t0_ts"] <= now:
            continue
        key = f"{event['venue']}:{event['base']}:{event['t0_ts']}"
        if key not in seen:
            seen[key] = now
            notice.append({
                "venue": event["venue"], "base": event["base"],
                "t0_utc": _iso(event["t0_ts"]),
                "first_seen_utc": _iso(now),
                "notice_sec": event["t0_ts"] - now,
                "notice_hours": round((event["t0_ts"] - now) / 3600.0, 2),
                "is_lower_bound": True,
            })
    # A key whose t0 has passed can be forgotten; keeping it would grow without limit.
    seen = {k: v for k, v in seen.items() if int(k.rsplit(":", 1)[1]) > now - 86400}
    notice = notice[-200:]

    to_launch = []
    if spawn:
        for event in armed:
            key = f"{event['venue']}:{event['base']}:{event['t0_ts']}"
            if key in launched:
                continue
            if now >= event["capture_from_ts"]:
                to_launch.append((key, event))

    started = []
    for key, event in to_launch:
        try:
            _spawn_capture(event, repo_root)
            launched.append(key)
            started.append(key)
        except OSError as exc:
            errors.append({"venue": event["venue"], "reason": f"spawn failed: {exc}"})

    payload = {
        "schema": "trading_mvp_premarket_forward_depth_armed_v1",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "scanned_at_utc": _iso(now),
        "scheduled_seen": len(scheduled),
        "armed": armed,
        "rejected": rejected,
        "capture_launched": launched,
        "first_seen": seen,
        # Every entry is a LOWER bound: the venue may have published earlier than the first
        # scan that looked. It tightens toward the truth as the cadence tightens, and never
        # overstates the warning available.
        "notice_observed": notice,
        "errors": errors,
    }
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {
        "status": "SCAN_COMPLETE",
        "scheduled_seen": len(scheduled),
        "armed": len(armed),
        "rejected": len(rejected),
        "captures_started": started,
        "next_t0_utc": armed[0]["t0_utc"] if armed else None,
        "notice_samples": len(notice),
        "errors": len(errors),
        "execution_performed": True,
    }


def _spawn_capture(event: dict[str, Any], repo_root: Path) -> None:
    """Start the capture as a detached process.

    ``sys.executable`` is the absolute path of the running interpreter, not a name resolved
    against PATH - an unqualified interpreter name is CWE-426."""
    cmd = [sys.executable, str(Path(__file__).resolve()), "--capture",
           "--venue", event["venue"], "--base", event["base"],
           "--t0", str(event["t0_ts"])]
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)


# --------------------------------------------------------------------------- books


def _levels(payload: Any, venue: str, leg: str) -> tuple[list, list]:
    """Bids and asks as (price, size) pairs, oldest venue quirks absorbed here."""
    if venue == "okx":
        rows = (payload or {}).get("data") or []
        book = rows[0] if rows else {}
        take = lambda side: [(float(x[0]), float(x[1])) for x in (book.get(side) or [])]
        return take("bids"), take("asks")
    if venue == "gate" and leg == "spot":
        take = lambda side: [(float(x[0]), float(x[1]))
                             for x in ((payload or {}).get(side) or [])]
        return take("bids"), take("asks")
    if venue == "gate" and leg == "perp":
        # Futures returns objects, and its bid sizes are positive while ask sizes are too;
        # the side is the key, not the sign.
        take = lambda side: [(float(x["p"]), abs(float(x["s"])))
                             for x in ((payload or {}).get(side) or [])]
        return take("bids"), take("asks")
    raise ForwardDepthError(f"no book reader for {venue}/{leg}")


def _book_request(venue: str, leg: str, symbol: str, levels: int) -> dict[str, Any]:
    if venue == "okx":
        # 400 is the ceiling on /books. Taking it costs nothing and widens the reach the
        # band summary can honestly report on a thin, newly listed book.
        return {"instId": symbol, "sz": str(min(levels, 400))}
    if venue == "gate" and leg == "spot":
        return {"currency_pair": symbol, "limit": str(min(levels, 100))}
    if venue == "gate" and leg == "perp":
        return {"contract": symbol, "limit": str(min(levels, 100))}
    raise ForwardDepthError(f"no book request shape for {venue}/{leg}")


def summarise(bids: list, asks: list, bands: list[float], retain: int) -> dict[str, Any]:
    """Depth standing within each distance band, in quote units of the venue's own sizes.

    Sizes are left in whatever unit the venue quotes - contracts for a perpetual, base units
    for spot - because the hypothesis is about depth falling relative to the same book's own
    pre-window, and a ratio does not need the contract multiplier. The multiplier is recorded
    on the armed event so absolute conversion stays possible later."""
    if not bids or not asks:
        return {"mid": None, "usable": False}
    best_bid, best_ask = bids[0][0], asks[0][0]
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return {"mid": None, "usable": False}
    mid = (best_bid + best_ask) / 2.0
    out: dict[str, Any] = {
        "mid": round(mid, 12),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": round((best_ask - best_bid) / mid * 10000.0, 4),
        "usable": True,
        "levels_bid": len(bids),
        "levels_ask": len(asks),
    }
    # How far from mid the returned levels actually reach. A venue sends its top N levels,
    # not the whole book, so a band wider than that reach is not a measurement of "nothing
    # stands out there" - it is the book running out. Recorded per side and per band,
    # because a truncated band silently reported as a number is exactly the failure this
    # study keeps having to correct after the fact.
    bid_reach = round((mid - min(p for p, _ in bids)) / mid * 100.0, 4)
    ask_reach = round((max(p for p, _ in asks) - mid) / mid * 100.0, 4)
    out["bid_covered_pct"] = bid_reach
    out["ask_covered_pct"] = ask_reach

    for band in bands:
        lo, hi = mid * (1 - band / 100.0), mid * (1 + band / 100.0)
        out[f"bid_depth_{band}pct"] = round(
            sum(p * s for p, s in bids if p >= lo), 8)
        out[f"ask_depth_{band}pct"] = round(
            sum(p * s for p, s in asks if p <= hi), 8)
        out[f"bid_truncated_{band}pct"] = bid_reach < band
        out[f"ask_truncated_{band}pct"] = ask_reach < band
        # v4. The other way a band comes back empty, and the one the truncation flag above
        # cannot see. When the spread is wider than twice the band, no level can lie inside
        # it: the best bid already sits further from mid than the band reaches. The first
        # live capture had a perpetual quoting 385 bps, and its 1% band was inside the
        # spread in 77% of snapshots - eight hundred readings that say "no depth within one
        # percent" when they mean "one percent is inside the spread". Both flags are needed:
        # truncation is the book ending, this is the book not starting.
        out[f"bid_inside_spread_{band}pct"] = best_bid < lo
        out[f"ask_inside_spread_{band}pct"] = best_ask > hi
    # v4. Depth of the best N levels, which no spread can make undefined. On a book whose
    # spread swings between 76 and 512 bps within one event - as the first capture's did -
    # a fixed distance band measures the spread as much as the depth, while a level count
    # measures the same thing at every moment. Declared as the fallback primary.
    for count in (5, 10, 25, 50):
        out[f"bid_depth_top{count}"] = round(sum(p * s for p, s in bids[:count]), 8)
        out[f"ask_depth_top{count}"] = round(sum(p * s for p, s in asks[:count]), 8)
        out[f"bid_levels_short_top{count}"] = len(bids) < count
        out[f"ask_levels_short_top{count}"] = len(asks) < count

    out["top_bids"] = [[p, s] for p, s in bids[:retain]]
    out["top_asks"] = [[p, s] for p, s in asks[:retain]]
    return out


def capture(*, venue: str, base: str, t0: int, repo_root: Path = REPO_ROOT,
            get: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
            sleep: Callable[[float], None] = time.sleep,
            now_fn: Callable[[], int] = _now) -> dict[str, Any]:
    plan = load_plan(repo_root)
    getter = get or http_get_json
    cap = plan["capture"]
    bands = list(cap["distance_bands_pct"])
    retain = int(cap["levels_retained_per_side"])
    interval = int(cap["snapshot_interval_sec"])
    budget = int(cap["max_snapshots_per_event"])
    timeout = int(cap["request_timeout_sec"])
    max_bytes = int(cap["max_response_bytes"])
    levels = int(cap["depth_levels_requested"])

    armed_path = repo_root / ARMED_RELATIVE
    armed = json.loads(armed_path.read_text(encoding="utf-8")) if armed_path.is_file() else {}
    event = next((e for e in (armed.get("armed") or [])
                  if e["venue"] == venue and e["base"] == base and int(e["t0_ts"]) == t0), None)
    if event is None:
        raise ForwardDepthError(f"no armed event for {venue}:{base}:{t0}")

    out_dir = repo_root / CAPTURE_DIR_RELATIVE
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{venue}-{base}-{t0}.jsonl"

    header = {
        "record": "header",
        "schema": "trading_mvp_premarket_forward_depth_capture_v1",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "event": event,
        "hypothesis": plan["hypothesis"],
        "started_at_utc": _iso(now_fn()),
        "size_units": "VENUE_NATIVE_CONTRACTS_OR_BASE_NOT_CONVERTED",
    }
    with out_path.open("ab") as handle:
        handle.write((json.dumps(header, ensure_ascii=False) + "\n").encode("utf-8"))

    host = {"okx": "www.okx.com", "gate": "api.gateio.ws"}[venue]
    legs = [("perp", event["perp_symbol"]), ("spot", event["spot_symbol"])]
    end = t0 + int(cap["window_after_min"]) * 60
    taken, errors = 0, 0

    while now_fn() < end and taken < budget:
        stamp = now_fn()
        for leg, symbol in legs:
            if leg == "spot" and stamp < t0:
                continue  # it does not exist yet; a request now would only record an error
            if taken >= budget:
                break
            endpoint = plan["depth_books"][
                f"{venue}_{'spot' if leg == 'spot' else ('swap' if venue == 'okx' else 'perp')}"
            ]
            try:
                payload, provenance = getter(
                    endpoint, _book_request(venue, leg, symbol, levels),
                    allowed_host=host, timeout_sec=timeout, max_bytes=max_bytes)
                bids, asks = _levels(payload, venue, leg)
                row = {"record": "book", "leg": leg, "symbol": symbol,
                       "ts": stamp, "rel_min": round((stamp - t0) / 60.0, 3),
                       **summarise(bids, asks, bands, retain),
                       "response_sha256": provenance["response_sha256"],
                       "response_bytes": provenance["response_bytes"]}
            except ForwardDepthError as exc:
                errors += 1
                row = {"record": "error", "leg": leg, "symbol": symbol,
                       "ts": stamp, "rel_min": round((stamp - t0) / 60.0, 3),
                       "reason": str(exc)}
            taken += 1
            with out_path.open("ab") as handle:
                handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
            sleep(float(cap["min_interval_between_requests_sec"]))
        remaining = interval - (now_fn() - stamp)
        if remaining > 0:
            sleep(float(remaining))

    footer = {"record": "footer", "finished_at_utc": _iso(now_fn()),
              "snapshots": taken, "errors": errors,
              "reached_budget": taken >= budget}
    with out_path.open("ab") as handle:
        handle.write((json.dumps(footer, ensure_ascii=False) + "\n").encode("utf-8"))
    return {"status": "CAPTURE_COMPLETE", "path": str(out_path),
            "snapshots": taken, "errors": errors, "execution_performed": True}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--scan", action="store_true",
                         help="one pass: find scheduled listings, arm the qualifying ones")
    actions.add_argument("--capture", action="store_true",
                         help="record one armed event; normally started by --scan")
    parser.add_argument("--venue", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--t0", type=int, default=0)
    parser.add_argument("--no-spawn", action="store_true",
                        help="scan without starting any capture")
    args = parser.parse_args(argv)

    try:
        if args.scan:
            print(json.dumps(scan(spawn=not args.no_spawn), ensure_ascii=False))
            return 0
        if not (args.venue and args.base and args.t0):
            raise ForwardDepthError("--capture needs --venue, --base and --t0")
        print(json.dumps(capture(venue=args.venue, base=args.base, t0=args.t0),
                         ensure_ascii=False))
        return 0
    except ForwardDepthError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
