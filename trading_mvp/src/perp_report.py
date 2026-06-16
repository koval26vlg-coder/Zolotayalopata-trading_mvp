from __future__ import annotations

import json
from json import JSONDecodeError
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_ts(event: dict[str, Any]) -> float | None:
    return _as_float(event.get("exchange_ts")) or _as_float(event.get("recv_ts"))


def _market_key(event: dict[str, Any]) -> str:
    return f"{event.get('exchange')}:{event.get('symbol')}"


def default_perp_report_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"perp_report_{utc_stamp()}.json"


def run_perp_report_file(input_path: str | Path, output_path: str | Path | None = None) -> dict[str, Any]:
    report = build_perp_report(input_path)
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        report["output"] = str(out)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_perp_report(input_path: str | Path) -> dict[str, Any]:
    src = Path(input_path)
    events_by_kind: Counter[str] = Counter()
    events_by_exchange: Counter[str] = Counter()
    cycle_values: set[int] = set()
    field_coverage: Counter[str] = Counter()
    markets: dict[str, dict[str, Any]] = defaultdict(_empty_market_stats)
    first_ts: float | None = None
    last_ts: float | None = None
    rows = 0
    malformed_rows = 0

    with src.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except JSONDecodeError:
                malformed_rows += 1
                continue
            rows += 1
            kind = str(event.get("event_kind") or "unknown")
            exchange = str(event.get("exchange") or "unknown")
            events_by_kind[kind] += 1
            events_by_exchange[exchange] += 1
            cycle = event.get("cycle")
            if isinstance(cycle, int):
                cycle_values.add(cycle)
            _update_field_coverage(field_coverage, event)
            ts = _event_ts(event)
            if ts is not None:
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)
            _update_market_stats(markets[_market_key(event)], event, kind, ts, line_no)

    market_payload = {key: _finalize_market_stats(value) for key, value in sorted(markets.items())}
    report = {
        "mode": "perp_dataset_report",
        "input": str(src),
        "rows": rows,
        "events_by_kind": dict(events_by_kind),
        "events_by_exchange": dict(events_by_exchange),
        "markets": market_payload,
        "market_count": len(market_payload),
        "cycles_seen": len(cycle_values),
        "cycle_min": min(cycle_values) if cycle_values else None,
        "cycle_max": max(cycle_values) if cycle_values else None,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "time_coverage_sec": (last_ts - first_ts) if first_ts is not None and last_ts is not None else 0.0,
        "field_coverage": dict(field_coverage),
        "malformed_rows": malformed_rows,
        "warnings": _warnings(rows, market_payload, field_coverage, malformed_rows),
    }
    return report


def _empty_market_stats() -> dict[str, Any]:
    return {
        "rows": 0,
        "events_by_kind": Counter(),
        "first_ts": None,
        "last_ts": None,
        "line_first": None,
        "line_last": None,
        "spread_count": 0,
        "spread_sum_bps": 0.0,
        "spread_min_bps": None,
        "spread_max_bps": None,
        "trade_count": 0,
        "trade_notional_quote_sum": 0.0,
        "trade_qty_sum": 0.0,
        "funding_rate_count": 0,
        "funding_rate_min": None,
        "funding_rate_max": None,
        "funding_rate_last": None,
        "mark_price_last": None,
        "index_price_last": None,
    }


def _update_field_coverage(counter: Counter[str], event: dict[str, Any]) -> None:
    for field in (
        "mark_price",
        "index_price",
        "funding_rate",
        "next_funding_ts",
        "funding_interval_sec",
        "open_interest",
        "volume_24h_quote",
    ):
        if event.get(field) is not None:
            counter[field] += 1


def _update_market_stats(
    stats: dict[str, Any],
    event: dict[str, Any],
    kind: str,
    ts: float | None,
    line_no: int,
) -> None:
    stats["rows"] += 1
    stats["events_by_kind"][kind] += 1
    stats["line_first"] = line_no if stats["line_first"] is None else stats["line_first"]
    stats["line_last"] = line_no
    if ts is not None:
        stats["first_ts"] = ts if stats["first_ts"] is None else min(stats["first_ts"], ts)
        stats["last_ts"] = ts if stats["last_ts"] is None else max(stats["last_ts"], ts)

    spread = _as_float(event.get("spread_bps"))
    if spread is not None:
        stats["spread_count"] += 1
        stats["spread_sum_bps"] += spread
        stats["spread_min_bps"] = spread if stats["spread_min_bps"] is None else min(stats["spread_min_bps"], spread)
        stats["spread_max_bps"] = spread if stats["spread_max_bps"] is None else max(stats["spread_max_bps"], spread)

    if kind == "trade":
        price = _as_float(event.get("price"))
        qty = _as_float(event.get("qty"))
        if price is not None and qty is not None:
            stats["trade_count"] += 1
            stats["trade_qty_sum"] += qty
            stats["trade_notional_quote_sum"] += price * qty

    funding_rate = _as_float(event.get("funding_rate"))
    if funding_rate is not None:
        stats["funding_rate_count"] += 1
        stats["funding_rate_min"] = funding_rate if stats["funding_rate_min"] is None else min(stats["funding_rate_min"], funding_rate)
        stats["funding_rate_max"] = funding_rate if stats["funding_rate_max"] is None else max(stats["funding_rate_max"], funding_rate)
        stats["funding_rate_last"] = funding_rate

    mark_price = _as_float(event.get("mark_price"))
    index_price = _as_float(event.get("index_price"))
    if mark_price is not None:
        stats["mark_price_last"] = mark_price
    if index_price is not None:
        stats["index_price_last"] = index_price


def _finalize_market_stats(stats: dict[str, Any]) -> dict[str, Any]:
    spread_count = int(stats["spread_count"])
    trade_count = int(stats["trade_count"])
    first_ts = stats["first_ts"]
    last_ts = stats["last_ts"]
    return {
        "rows": stats["rows"],
        "events_by_kind": dict(stats["events_by_kind"]),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "time_coverage_sec": (last_ts - first_ts) if first_ts is not None and last_ts is not None else 0.0,
        "line_first": stats["line_first"],
        "line_last": stats["line_last"],
        "avg_spread_bps": (stats["spread_sum_bps"] / spread_count) if spread_count else None,
        "min_spread_bps": stats["spread_min_bps"],
        "max_spread_bps": stats["spread_max_bps"],
        "trade_count": trade_count,
        "trade_qty_sum": stats["trade_qty_sum"],
        "trade_notional_quote_sum": stats["trade_notional_quote_sum"],
        "avg_trade_notional_quote": (stats["trade_notional_quote_sum"] / trade_count) if trade_count else None,
        "funding_rate_count": stats["funding_rate_count"],
        "funding_rate_min": stats["funding_rate_min"],
        "funding_rate_max": stats["funding_rate_max"],
        "funding_rate_last": stats["funding_rate_last"],
        "mark_price_last": stats["mark_price_last"],
        "index_price_last": stats["index_price_last"],
    }


def _warnings(
    rows: int,
    markets: dict[str, dict[str, Any]],
    field_coverage: Counter[str],
    malformed_rows: int,
) -> list[str]:
    warnings: list[str] = []
    if malformed_rows > 0:
        warnings.append("malformed_rows")
    if rows == 0:
        warnings.append("no_rows")
        return warnings
    for field in ("mark_price", "index_price", "funding_rate", "funding_interval_sec"):
        if field_coverage.get(field, 0) == 0:
            warnings.append(f"missing_{field}")
    for market, stats in markets.items():
        kinds = stats.get("events_by_kind", {})
        if kinds.get("bbo", 0) == 0:
            warnings.append(f"{market}:no_bbo")
        if kinds.get("trade", 0) == 0:
            warnings.append(f"{market}:no_trades")
        if stats.get("funding_rate_count", 0) == 0:
            warnings.append(f"{market}:no_funding_rate")
    return warnings
