from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


MEXC_EXCHANGE_INFO_URL = "https://api.mexc.com/api/v3/exchangeInfo"
GATE_CURRENCY_PAIRS_URL = "https://api.gateio.ws/api/v4/spot/currency_pairs"
BITGET_SYMBOLS_URL = "https://api.bitget.com/api/v2/spot/public/symbols"

REQUIRED_CALENDAR_FIELDS = [
    "event_id",
    "exchange",
    "base",
    "quote",
    "symbol",
    "listed_at_utc",
    "announcement_at_utc",
    "source_url",
    "source_type",
    "delisted_at_utc",
    "is_delisted",
    "first_trade_ts_utc",
    "survivorship_status",
]

CALENDAR_FIELDS = REQUIRED_CALENDAR_FIELDS + [
    "event_type",
    "status",
    "trade_status",
    "symbol_type",
    "name",
    "listed_ts",
    "announcement_ts",
    "delisted_ts",
    "listing_timestamp_source",
    "source_quality",
    "bias_flags",
    "included_by_universe",
]


@dataclass(frozen=True)
class ListingCalendarPaths:
    output: Path
    summary: Path


def default_listing_calendar_paths(base_dir: Path | str = Path("exports/trading-mvp")) -> ListingCalendarPaths:
    root = Path(base_dir)
    out = root / "listings" / "non_binance_listing_events.csv"
    return ListingCalendarPaths(output=out, summary=out.with_suffix(".summary.json"))


def fetch_json(url: str, timeout_sec: int = 20) -> Any:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def _iso_from_epoch(value: int | float | str | None, *, milliseconds: bool = False) -> str:
    if value in (None, "", 0, "0"):
        return ""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    if milliseconds:
        ts /= 1000.0
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_seconds(value: int | float | str | None, *, milliseconds: bool = False) -> float | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    if milliseconds:
        ts /= 1000.0
    return ts


def load_universe_symbols(path: Path | str | None) -> set[str]:
    if path is None:
        return set()
    p = Path(path)
    if not p.exists():
        return set()
    if p.suffix.lower() == ".txt":
        return {line.strip().upper() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}
    out: set[str] = set()
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            value = row.get("symbol") or row.get("base") or row.get("asset")
            if value:
                out.add(str(value).strip().upper())
    return out


def _row(
    *,
    exchange: str,
    base: str,
    quote: str,
    symbol: str,
    listed_ts: float | None,
    listed_at: str,
    source_url: str,
    source_type: str,
    status: str,
    trade_status: str,
    symbol_type: str,
    name: str,
    listing_timestamp_source: str,
    source_quality: str,
    survivorship_status: str,
    bias_flags: Iterable[str],
    included_by_universe: bool,
    is_delisted: bool = False,
    delisted_ts: float | None = None,
    delisted_at: str = "",
) -> dict[str, Any]:
    event_id = f"{exchange}:{symbol}:listing"
    return {
        "event_id": event_id,
        "exchange": exchange,
        "base": base.upper(),
        "quote": quote.upper(),
        "symbol": symbol,
        "listed_at_utc": listed_at,
        "announcement_at_utc": "",
        "source_url": source_url,
        "source_type": source_type,
        "delisted_at_utc": delisted_at,
        "is_delisted": "true" if is_delisted else "false",
        "first_trade_ts_utc": listed_at,
        "survivorship_status": survivorship_status,
        "event_type": "spot_listing",
        "status": status,
        "trade_status": trade_status,
        "symbol_type": symbol_type,
        "name": name,
        "listed_ts": "" if listed_ts is None else f"{listed_ts:.0f}",
        "announcement_ts": "",
        "delisted_ts": "" if delisted_ts is None else f"{delisted_ts:.0f}",
        "listing_timestamp_source": listing_timestamp_source,
        "source_quality": source_quality,
        "bias_flags": "|".join(sorted(set(flag for flag in bias_flags if flag))),
        "included_by_universe": "true" if included_by_universe else "false",
    }


def rows_from_mexc_exchange_info(
    payload: dict[str, Any],
    *,
    quote: str = "USDT",
    universe_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    universe_symbols = universe_symbols or set()
    rows: list[dict[str, Any]] = []
    for item in payload.get("symbols", []):
        item_quote = str(item.get("quoteAsset", "")).upper()
        if item_quote != quote.upper():
            continue
        base = str(item.get("baseAsset", "")).upper()
        if not base:
            continue
        included = not universe_symbols or base in universe_symbols
        if not included:
            continue
        status = str(item.get("status", ""))
        spot_allowed = bool(item.get("isSpotTradingAllowed", False))
        first_open_ms = item.get("firstOpenTime")
        listed_ts = _epoch_seconds(first_open_ms, milliseconds=True)
        listed_at = _iso_from_epoch(first_open_ms, milliseconds=True)
        bias_flags = ["current_api_snapshot"]
        if not listed_at:
            bias_flags.append("missing_listing_timestamp")
        if spot_allowed and status in {"1", "TRADING", "ENABLED"}:
            survivorship = "current_active_snapshot"
        else:
            survivorship = "current_non_tradable_snapshot"
            bias_flags.append("non_tradable_current_status")
        rows.append(
            _row(
                exchange="mexc",
                base=base,
                quote=item_quote,
                symbol=str(item.get("symbol", "")),
                listed_ts=listed_ts,
                listed_at=listed_at,
                source_url=MEXC_EXCHANGE_INFO_URL,
                source_type="public_api_exchange_info_current_snapshot",
                status=status,
                trade_status="tradable" if spot_allowed else "not_tradable",
                symbol_type="spot",
                name=str(item.get("fullName", "")),
                listing_timestamp_source="firstOpenTime" if listed_at else "",
                source_quality="api_timestamp" if listed_at else "api_snapshot_missing_timestamp",
                survivorship_status=survivorship,
                bias_flags=bias_flags,
                included_by_universe=included,
                is_delisted=not spot_allowed,
            )
        )
    return rows


def rows_from_gate_currency_pairs(
    payload: list[dict[str, Any]],
    *,
    quote: str = "USDT",
    universe_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    universe_symbols = universe_symbols or set()
    rows: list[dict[str, Any]] = []
    for item in payload:
        item_quote = str(item.get("quote", "")).upper()
        if item_quote != quote.upper():
            continue
        base = str(item.get("base", "")).upper()
        if not base:
            continue
        included = not universe_symbols or base in universe_symbols
        if not included:
            continue
        buy_ts = _epoch_seconds(item.get("buy_start"))
        sell_ts = _epoch_seconds(item.get("sell_start"))
        timestamps = [ts for ts in (buy_ts, sell_ts) if ts is not None]
        listed_ts = min(timestamps) if timestamps else None
        listed_at = _iso_from_epoch(listed_ts)
        trade_status = str(item.get("trade_status", ""))
        status_lower = trade_status.lower()
        is_delisted = status_lower in {"delisted", "untradable", "not_tradable", "not tradable"}
        bias_flags = ["current_api_snapshot"]
        if not listed_at:
            bias_flags.append("missing_listing_timestamp")
        if status_lower != "tradable":
            bias_flags.append("non_tradable_current_status")
        survivorship = "current_active_snapshot" if status_lower == "tradable" else "current_non_tradable_snapshot"
        rows.append(
            _row(
                exchange="gateio",
                base=base,
                quote=item_quote,
                symbol=str(item.get("id", "")),
                listed_ts=listed_ts,
                listed_at=listed_at,
                source_url=GATE_CURRENCY_PAIRS_URL,
                source_type="public_api_currency_pairs_current_snapshot",
                status=trade_status,
                trade_status=trade_status,
                symbol_type=str(item.get("type", "")),
                name=str(item.get("base_name", "")),
                listing_timestamp_source="min_nonzero_buy_start_sell_start" if listed_at else "",
                source_quality="api_timestamp" if listed_at else "api_snapshot_missing_timestamp",
                survivorship_status=survivorship,
                bias_flags=bias_flags,
                included_by_universe=included,
                is_delisted=is_delisted,
            )
        )
    return rows


def rows_from_bitget_symbols(
    payload: dict[str, Any],
    *,
    quote: str = "USDT",
    universe_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    universe_symbols = universe_symbols or set()
    rows: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        item_quote = str(item.get("quoteCoin", "")).upper()
        if item_quote != quote.upper():
            continue
        base = str(item.get("baseCoin", "")).upper()
        if not base:
            continue
        included = not universe_symbols or base in universe_symbols
        if not included:
            continue
        status = str(item.get("status", ""))
        status_lower = status.lower()
        open_ms = item.get("openTime")
        listed_ts = _epoch_seconds(open_ms, milliseconds=True)
        listed_at = _iso_from_epoch(open_ms, milliseconds=True)
        off_ts = _epoch_seconds(item.get("offTime"), milliseconds=True)
        off_at = _iso_from_epoch(item.get("offTime"), milliseconds=True)
        is_delisted = bool(off_ts) or status_lower not in {"online", "tradable", "trading", "enable", "enabled"}
        bias_flags = ["current_api_snapshot"]
        if not listed_at:
            bias_flags.append("missing_listing_timestamp")
        if is_delisted:
            bias_flags.append("non_tradable_current_status")
        survivorship = "current_active_snapshot" if not is_delisted else "current_non_tradable_snapshot"
        rows.append(
            _row(
                exchange="bitget",
                base=base,
                quote=item_quote,
                symbol=str(item.get("symbol", "")),
                listed_ts=listed_ts,
                listed_at=listed_at,
                source_url=BITGET_SYMBOLS_URL,
                source_type="public_api_spot_symbols_current_snapshot",
                status=status,
                trade_status="tradable" if not is_delisted else status,
                symbol_type="spot",
                name=str(item.get("symbol", "")),
                listing_timestamp_source="openTime" if listed_at else "",
                source_quality="api_timestamp" if listed_at else "api_snapshot_missing_timestamp",
                survivorship_status=survivorship,
                bias_flags=bias_flags,
                included_by_universe=included,
                is_delisted=is_delisted,
                delisted_ts=off_ts,
                delisted_at=off_at,
            )
        )
    return rows


def summarize_calendar(rows: list[dict[str, Any]], *, universe_size: int, quote: str) -> dict[str, Any]:
    exchange_counts: dict[str, int] = {}
    for row in rows:
        exchange_counts[row["exchange"]] = exchange_counts.get(row["exchange"], 0) + 1
    rows_with_timestamps = sum(1 for row in rows if row.get("listed_at_utc"))
    non_tradable_rows = sum(1 for row in rows if row.get("survivorship_status") == "current_non_tradable_snapshot")
    delisted_rows = sum(1 for row in rows if row.get("is_delisted") == "true")
    current_snapshot_rows = sum(1 for row in rows if "current_api_snapshot" in str(row.get("bias_flags", "")))
    bases = {str(row.get("base", "")).upper() for row in rows if row.get("base")}
    timestamp_coverage = rows_with_timestamps / len(rows) if rows else 0.0
    exchange_count = len(exchange_counts)
    bias_control_pass = bool(
        len(rows) >= 100
        and exchange_count >= 2
        and timestamp_coverage >= 0.80
        and (delisted_rows + non_tradable_rows) >= 10
    )
    if bias_control_pass:
        decision = "LISTING_EVENT_CALENDAR_BIAS_CONTROL_PASS_READY_FOR_NORMALIZER"
    elif not rows:
        decision = "LISTING_EVENT_CALENDAR_EMPTY"
    elif exchange_count < 2:
        decision = "LISTING_EVENT_CALENDAR_NEEDS_TWO_EXCHANGES"
    elif timestamp_coverage < 0.80:
        decision = "LISTING_EVENT_CALENDAR_NEEDS_TIMESTAMP_COVERAGE"
    else:
        decision = "LISTING_EVENT_CALENDAR_PARTIAL_NEEDS_DELISTED_OR_NONTRADABLE_COVERAGE"
    return {
        "mode": "listing_event_calendar_summary",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "quote": quote.upper(),
        "decision": decision,
        "bias_control_pass": bias_control_pass,
        "rows": len(rows),
        "unique_bases": len(bases),
        "universe_size": universe_size,
        "exchange_count": exchange_count,
        "exchange_counts": exchange_counts,
        "rows_with_timestamps": rows_with_timestamps,
        "timestamp_coverage": timestamp_coverage,
        "delisted_rows": delisted_rows,
        "non_tradable_rows": non_tradable_rows,
        "current_api_snapshot_rows": current_snapshot_rows,
        "coverage_warnings": [
            warning
            for warning in [
                "current_api_snapshots_are_not_full_delisting_history" if current_snapshot_rows else "",
                "missing_delisted_or_nontradable_outcomes" if (delisted_rows + non_tradable_rows) < 10 else "",
                "timestamp_coverage_below_80pct" if timestamp_coverage < 0.80 else "",
                "less_than_two_exchanges" if exchange_count < 2 else "",
            ]
            if warning
        ],
        "required_next_step": (
            "implement_read_only_listing_event_normalizer_backtester_planonly"
            if bias_control_pass
            else "add_delisted_frozen_no_trade_event_source_before_backtest"
        ),
        "sources": [
            {
                "exchange": "mexc",
                "url": MEXC_EXCHANGE_INFO_URL,
                "source_type": "public_api_exchange_info_current_snapshot",
            },
            {
                "exchange": "gateio",
                "url": GATE_CURRENCY_PAIRS_URL,
                "source_type": "public_api_currency_pairs_current_snapshot",
            },
            {
                "exchange": "bitget",
                "url": BITGET_SYMBOLS_URL,
                "source_type": "public_api_spot_symbols_current_snapshot",
            },
        ],
    }


def write_calendar_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CALENDAR_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CALENDAR_FIELDS})


def build_listing_event_calendar_file(
    *,
    output_path: Path,
    summary_path: Path | None = None,
    universe_path: Path | None = None,
    quote: str = "USDT",
    timeout_sec: int = 20,
    mexc_payload: dict[str, Any] | None = None,
    gate_payload: list[dict[str, Any]] | None = None,
    bitget_payload: dict[str, Any] | None = None,
    include_bitget: bool = True,
) -> dict[str, Any]:
    universe = load_universe_symbols(universe_path)
    if mexc_payload is None:
        mexc_payload = fetch_json(MEXC_EXCHANGE_INFO_URL, timeout_sec=timeout_sec)
    if gate_payload is None:
        gate_payload = fetch_json(GATE_CURRENCY_PAIRS_URL, timeout_sec=timeout_sec)
    rows = rows_from_mexc_exchange_info(mexc_payload, quote=quote, universe_symbols=universe)
    rows.extend(rows_from_gate_currency_pairs(gate_payload, quote=quote, universe_symbols=universe))
    if include_bitget:
        if bitget_payload is None:
            bitget_payload = fetch_json(BITGET_SYMBOLS_URL, timeout_sec=timeout_sec)
        rows.extend(rows_from_bitget_symbols(bitget_payload, quote=quote, universe_symbols=universe))
    rows.sort(key=lambda row: (row.get("listed_ts") in ("", None), row.get("listed_ts") or "999999999999", row["exchange"], row["symbol"]))
    write_calendar_csv(output_path, rows)
    summary = summarize_calendar(rows, universe_size=len(universe), quote=quote)
    summary["mode"] = "listing_event_calendar_build"
    summary["output_path"] = str(output_path)
    summary["summary_path"] = str(summary_path) if summary_path else ""
    summary["universe_path"] = str(universe_path) if universe_path else ""
    summary["research_only"] = True
    summary["live_orders"] = False
    summary["api_keys"] = False
    summary["leverage_or_margin"] = False
    summary["paper_forward_allowed"] = False
    if summary_path:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build research-only listing event calendar from public exchange APIs.")
    defaults = default_listing_calendar_paths()
    parser.add_argument("--output", default=str(defaults.output))
    parser.add_argument("--summary", default=str(defaults.summary))
    parser.add_argument("--universe", default="")
    parser.add_argument("--quote", default="USDT")
    parser.add_argument("--timeout-sec", type=int, default=20)
    args = parser.parse_args(argv)
    result = build_listing_event_calendar_file(
        output_path=Path(args.output),
        summary_path=Path(args.summary) if args.summary else None,
        universe_path=Path(args.universe) if args.universe else None,
        quote=args.quote,
        timeout_sec=args.timeout_sec,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
