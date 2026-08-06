from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_EXCHANGES = ("gateio", "mexc")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def default_cross_venue_dislocation_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / f"cross_venue_dislocation_{_utc_stamp()}.json"


@dataclass(frozen=True)
class CrossVenueDislocationConfig:
    quote: str = "USDT"
    stale_quote_sec: float = 2.0
    min_top_notional_quote: float = 25.0
    round_trip_fee_bps: float = 39.0
    slippage_bps: float = 10.0
    inventory_rebalance_buffer_bps: float = 20.0
    min_net_edge_bps: float = 0.0
    cooldown_sec: float = 60.0
    max_rows: int = 0
    max_events: int = 1000
    progress_every_rows: int = 0
    include_bases: tuple[str, ...] = ()

    @property
    def total_cost_bps(self) -> float:
        return self.round_trip_fee_bps + self.slippage_bps + self.inventory_rebalance_buffer_bps


@dataclass
class BboQuote:
    exchange: str
    symbol: str
    base: str
    quote: str
    ts: float
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    spread_bps: float


def normalize_spot_symbol(symbol: str, quote: str = "USDT") -> tuple[str, str] | None:
    normalized = str(symbol or "").strip().upper()
    expected_quote = quote.upper()
    if not normalized:
        return None
    if "_" in normalized:
        parts = normalized.split("_")
        if len(parts) != 2:
            return None
        base, found_quote = parts
    elif normalized.endswith(expected_quote):
        base = normalized[: -len(expected_quote)]
        found_quote = expected_quote
    else:
        return None
    if not base or found_quote != expected_quote:
        return None
    return base, found_quote


def run_cross_venue_dislocation_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    cfg: CrossVenueDislocationConfig | None = None,
) -> dict[str, Any]:
    source = Path(input_path)
    if not source.exists():
        raise FileNotFoundError(f"normalized WS input not found: {source}")

    report = build_cross_venue_dislocation_report(source, cfg or CrossVenueDislocationConfig())
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        report["output"] = str(target)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_cross_venue_dislocation_report(
    input_path: str | Path,
    cfg: CrossVenueDislocationConfig,
) -> dict[str, Any]:
    source = Path(input_path)
    latest: dict[tuple[str, str], BboQuote] = {}
    exchanges_by_base: dict[str, set[str]] = {}
    markets_by_exchange: dict[str, set[str]] = {}
    base_stats: dict[str, dict[str, Any]] = {}
    last_eligible_by_direction: dict[tuple[str, str], float] = {}
    top_candidates: list[dict[str, Any]] = []
    top_eligible: list[dict[str, Any]] = []

    rows_read = 0
    bbo_rows = 0
    parse_errors = 0
    skipped_non_bbo = 0
    skipped_exchange = 0
    skipped_symbol = 0
    skipped_bad_quote = 0
    stale_rejects = 0
    notional_rejects = 0
    cooldown_rejects = 0
    candidate_events = 0
    eligible_events = 0
    min_ts: float | None = None
    max_ts: float | None = None
    include_bases = {base.upper() for base in cfg.include_bases if base}

    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            if cfg.max_rows and rows_read >= cfg.max_rows:
                break
            rows_read += 1
            if cfg.progress_every_rows > 0 and rows_read % cfg.progress_every_rows == 0:
                print(
                    json.dumps(
                        {
                            "progress": "cross_venue_dislocation",
                            "rows_read": rows_read,
                            "bbo_rows": bbo_rows,
                            "matched_bases": len([base for base, venues in exchanges_by_base.items() if len(venues) >= 2]),
                            "candidate_events": candidate_events,
                            "eligible_events": eligible_events,
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue

            if row.get("event_kind") != "bbo":
                skipped_non_bbo += 1
                continue

            bbo_rows += 1
            exchange = str(row.get("exchange") or "").strip().lower()
            if exchange not in SUPPORTED_EXCHANGES:
                skipped_exchange += 1
                continue

            symbol = str(row.get("symbol") or "").strip()
            parsed_symbol = normalize_spot_symbol(symbol, cfg.quote)
            if parsed_symbol is None:
                skipped_symbol += 1
                continue
            base, quote = parsed_symbol
            if include_bases and base not in include_bases:
                continue

            quote_obj = _parse_bbo_quote(row, exchange=exchange, symbol=symbol, base=base, quote=quote)
            if quote_obj is None:
                skipped_bad_quote += 1
                continue

            min_ts = quote_obj.ts if min_ts is None else min(min_ts, quote_obj.ts)
            max_ts = quote_obj.ts if max_ts is None else max(max_ts, quote_obj.ts)
            latest[(exchange, base)] = quote_obj
            exchanges_by_base.setdefault(base, set()).add(exchange)
            markets_by_exchange.setdefault(exchange, set()).add(symbol)
            _stats_for(base_stats, base)["bbo_rows"] += 1

            if len(exchanges_by_base.get(base, ())) < 2:
                continue

            pair_quotes = [latest.get((venue, base)) for venue in SUPPORTED_EXCHANGES]
            if any(item is None for item in pair_quotes):
                continue
            gate_quote, mexc_quote = pair_quotes  # type: ignore[misc]
            evaluations = (
                _evaluate_direction(
                    base=base,
                    buy_quote=mexc_quote,
                    sell_quote=gate_quote,
                    direction="buy_mexc_sell_gateio",
                    now_ts=quote_obj.ts,
                    cfg=cfg,
                ),
                _evaluate_direction(
                    base=base,
                    buy_quote=gate_quote,
                    sell_quote=mexc_quote,
                    direction="buy_gateio_sell_mexc",
                    now_ts=quote_obj.ts,
                    cfg=cfg,
                ),
            )
            for event in evaluations:
                stats = _stats_for(base_stats, base)
                stats["evaluations"] += 1
                stats["max_gross_edge_bps"] = max(stats["max_gross_edge_bps"], event["gross_edge_bps"])
                stats["max_net_edge_bps"] = max(stats["max_net_edge_bps"], event["net_edge_bps"])
                stats["max_capacity_quote"] = max(stats["max_capacity_quote"], event["capacity_quote"])

                if not event["fresh"]:
                    stale_rejects += 1
                    stats["stale_rejects"] += 1
                    continue
                if event["gross_edge_bps"] <= 0:
                    continue

                candidate_events += 1
                stats["candidate_events"] += 1
                _keep_top(top_candidates, event, cfg.max_events)
                if event["capacity_quote"] < cfg.min_top_notional_quote:
                    notional_rejects += 1
                    stats["notional_rejects"] += 1
                    continue
                if event["net_edge_bps"] < cfg.min_net_edge_bps:
                    stats["cost_rejects"] += 1
                    continue

                cooldown_key = (base, event["direction"])
                previous_ts = last_eligible_by_direction.get(cooldown_key)
                if previous_ts is not None and event["ts"] - previous_ts < cfg.cooldown_sec:
                    cooldown_rejects += 1
                    stats["cooldown_rejects"] += 1
                    continue

                last_eligible_by_direction[cooldown_key] = event["ts"]
                eligible_events += 1
                stats["eligible_events"] += 1
                _keep_top(top_eligible, event, cfg.max_events)

    matched_bases = sorted(base for base, venues in exchanges_by_base.items() if len(venues) >= 2)
    scan_complete = not cfg.max_rows or rows_read < cfg.max_rows
    summary = {
        "rows_read": rows_read,
        "bbo_rows": bbo_rows,
        "parse_errors": parse_errors,
        "skipped_non_bbo": skipped_non_bbo,
        "skipped_exchange": skipped_exchange,
        "skipped_symbol": skipped_symbol,
        "skipped_bad_quote": skipped_bad_quote,
        "bases_seen": len(exchanges_by_base),
        "matched_bases": len(matched_bases),
        "candidate_events": candidate_events,
        "eligible_events": eligible_events,
        "stale_rejects": stale_rejects,
        "notional_rejects": notional_rejects,
        "cooldown_rejects": cooldown_rejects,
        "max_gross_edge_bps": _max_event_value(top_candidates, "gross_edge_bps"),
        "max_net_edge_bps": _max_event_value(top_candidates, "net_edge_bps"),
        "max_eligible_net_edge_bps": _max_event_value(top_eligible, "net_edge_bps"),
        "scan_complete": scan_complete,
    }
    decision, rejection_reasons = _decision(summary, scan_complete)

    return {
        "mode": "cross_venue_dislocation_planonly_research",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(source),
        "research_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "config": asdict(cfg) | {"total_cost_bps": cfg.total_cost_bps},
        "cost_model": {
            "round_trip_fee_bps": cfg.round_trip_fee_bps,
            "slippage_bps": cfg.slippage_bps,
            "inventory_rebalance_buffer_bps": cfg.inventory_rebalance_buffer_bps,
            "total_cost_bps": cfg.total_cost_bps,
            "note": "Base-tier cost model; no fee-tier optimism and no inventory transfer latency benefit assumed.",
        },
        "time_span": {
            "start_ts": min_ts,
            "end_ts": max_ts,
            "span_hours": ((max_ts - min_ts) / 3600.0) if min_ts is not None and max_ts is not None else 0.0,
        },
        "markets": {
            exchange: sorted(symbols)
            for exchange, symbols in sorted(markets_by_exchange.items())
        },
        "matched_bases": matched_bases,
        "summary": summary,
        "top_candidates": _sorted_events(top_candidates),
        "top_eligible": _sorted_events(top_eligible),
        "per_base": _per_base_rows(base_stats, exchanges_by_base),
        "accepted": False,
        "decision": decision,
        "rejection_reasons": rejection_reasons,
        "next_valid_moves": _next_valid_moves(summary, scan_complete),
        "blocked_actions": [
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "grid_optimization_before_full_scan",
            "paper_forward_before_oos_walk_forward_stress",
        ],
    }


def _parse_bbo_quote(
    row: dict[str, Any],
    *,
    exchange: str,
    symbol: str,
    base: str,
    quote: str,
) -> BboQuote | None:
    ts = _as_float(row.get("recv_ts"))
    if ts is None:
        ts = _as_float(row.get("exchange_ts"))
    bid_price = _as_float(row.get("bid_price"))
    bid_qty = _as_float(row.get("bid_qty"))
    ask_price = _as_float(row.get("ask_price"))
    ask_qty = _as_float(row.get("ask_qty"))
    if ts is None or bid_price is None or bid_qty is None or ask_price is None or ask_qty is None:
        return None
    if bid_price <= 0 or ask_price <= 0 or bid_qty < 0 or ask_qty < 0 or ask_price < bid_price:
        return None
    mid = (bid_price + ask_price) / 2.0
    spread_bps = ((ask_price - bid_price) / mid * 10000.0) if mid > 0 else 0.0
    return BboQuote(
        exchange=exchange,
        symbol=symbol,
        base=base,
        quote=quote,
        ts=ts,
        bid_price=bid_price,
        bid_qty=bid_qty,
        ask_price=ask_price,
        ask_qty=ask_qty,
        spread_bps=spread_bps,
    )


def _evaluate_direction(
    *,
    base: str,
    buy_quote: BboQuote,
    sell_quote: BboQuote,
    direction: str,
    now_ts: float,
    cfg: CrossVenueDislocationConfig,
) -> dict[str, Any]:
    gross_edge_bps = (sell_quote.bid_price / buy_quote.ask_price - 1.0) * 10000.0
    net_edge_bps = gross_edge_bps - cfg.total_cost_bps
    buy_capacity_quote = buy_quote.ask_price * buy_quote.ask_qty
    sell_capacity_quote = sell_quote.bid_price * sell_quote.bid_qty
    capacity_quote = min(buy_capacity_quote, sell_capacity_quote)
    age_sec = max(abs(now_ts - buy_quote.ts), abs(now_ts - sell_quote.ts), abs(buy_quote.ts - sell_quote.ts))
    return {
        "ts": now_ts,
        "base": base,
        "direction": direction,
        "buy_exchange": buy_quote.exchange,
        "buy_symbol": buy_quote.symbol,
        "buy_ask": buy_quote.ask_price,
        "buy_ask_qty": buy_quote.ask_qty,
        "sell_exchange": sell_quote.exchange,
        "sell_symbol": sell_quote.symbol,
        "sell_bid": sell_quote.bid_price,
        "sell_bid_qty": sell_quote.bid_qty,
        "gross_edge_bps": gross_edge_bps,
        "net_edge_bps": net_edge_bps,
        "total_cost_bps": cfg.total_cost_bps,
        "capacity_quote": capacity_quote,
        "buy_capacity_quote": buy_capacity_quote,
        "sell_capacity_quote": sell_capacity_quote,
        "age_sec": age_sec,
        "fresh": age_sec <= cfg.stale_quote_sec,
        "buy_spread_bps": buy_quote.spread_bps,
        "sell_spread_bps": sell_quote.spread_bps,
    }


def _stats_for(stats_by_base: dict[str, dict[str, Any]], base: str) -> dict[str, Any]:
    if base not in stats_by_base:
        stats_by_base[base] = {
            "base": base,
            "bbo_rows": 0,
            "evaluations": 0,
            "candidate_events": 0,
            "eligible_events": 0,
            "stale_rejects": 0,
            "notional_rejects": 0,
            "cost_rejects": 0,
            "cooldown_rejects": 0,
            "max_gross_edge_bps": -1e18,
            "max_net_edge_bps": -1e18,
            "max_capacity_quote": 0.0,
        }
    return stats_by_base[base]


def _keep_top(events: list[dict[str, Any]], event: dict[str, Any], limit: int) -> None:
    if limit <= 0:
        return
    events.append(event)
    if len(events) > limit * 2:
        events.sort(key=lambda item: float(item.get("net_edge_bps", -1e18)), reverse=True)
        del events[limit:]


def _sorted_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda item: float(item.get("net_edge_bps", -1e18)), reverse=True)


def _per_base_rows(
    stats_by_base: dict[str, dict[str, Any]],
    exchanges_by_base: dict[str, set[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for base, stats in stats_by_base.items():
        row = dict(stats)
        if row["max_gross_edge_bps"] <= -1e17:
            row["max_gross_edge_bps"] = None
        if row["max_net_edge_bps"] <= -1e17:
            row["max_net_edge_bps"] = None
        row["exchanges"] = sorted(exchanges_by_base.get(base, ()))
        rows.append(row)
    return sorted(
        rows,
        key=lambda item: float(item["max_net_edge_bps"] if item["max_net_edge_bps"] is not None else -1e18),
        reverse=True,
    )


def _max_event_value(events: list[dict[str, Any]], key: str) -> float | None:
    if not events:
        return None
    return max(float(event[key]) for event in events if key in event)


def _decision(summary: dict[str, Any], scan_complete: bool) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if summary["matched_bases"] <= 0:
        reasons.append("no_matched_cross_venue_bases")
    if summary["candidate_events"] <= 0:
        reasons.append("no_positive_gross_crossed_bbo_events")
    if summary["eligible_events"] <= 0:
        reasons.append("no_net_edge_after_base_fees_slippage_rebalance_buffer")
    if not scan_complete:
        reasons.append("scan_truncated_by_max_rows")

    if summary["matched_bases"] <= 0:
        return "REJECTED_NO_MATCHED_CROSS_VENUE_QUOTES", reasons
    if summary["eligible_events"] <= 0:
        return "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES", reasons
    if not scan_complete:
        return "PLANONLY_CANDIDATES_REQUIRE_VISIBLE_FULL_SCAN", reasons
    return "PLANONLY_CANDIDATES_REQUIRE_OOS_WALK_FORWARD_STRESS", reasons or ["research_only_not_accepted"]


def _next_valid_moves(summary: dict[str, Any], scan_complete: bool) -> list[str]:
    if not scan_complete:
        return [
            "Run the same detector visibly on the full clean slice before interpreting candidate frequency.",
            "Do not grid-tune thresholds from the truncated sample.",
        ]
    if summary["eligible_events"] <= 0:
        return [
            "Reject or park this branch under the current base-tier cost model.",
            "Only revisit if fee tier, maker routing, or inventory/rebalance assumptions materially improve.",
        ]
    return [
        "Build OOS/walk-forward/stress validation for the detected cross-venue events.",
        "Add execution feasibility checks: pre-funded inventory, withdrawal/deposit downtime, queue depth, API latency, and venue incident risk.",
    ]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
