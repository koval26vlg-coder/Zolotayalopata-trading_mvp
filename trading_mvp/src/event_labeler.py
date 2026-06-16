from __future__ import annotations

import bisect
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
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


def _spread_bps(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    return ((ask - bid) / mid) * 1e4 if mid > 0 else None


def _basis_bps(mark_price: float | None, index_price: float | None) -> float | None:
    if mark_price is None or index_price is None or index_price <= 0:
        return None
    return (mark_price - index_price) / index_price * 1e4


@dataclass(frozen=True)
class EventQualityConfig:
    lookback_sec: float = 120.0
    horizon_sec: float = 300.0
    min_sweep_notional_quote: float = 1000.0
    reclaim_bps: float = 0.0
    target_bps: float = 6.0
    stop_bps: float = 3.0
    max_pre_spread_bps: float = 0.0
    event_cooldown_sec: float = 10.0
    max_events: int = 5000


@dataclass(frozen=True)
class BboSample:
    ts: float
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    spread_bps: float | None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True)
class TradeSample:
    ts: float
    exchange: str
    symbol: str
    side: str
    price: float
    qty: float
    notional_quote: float
    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None


def default_event_quality_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"event_quality_report_{utc_stamp()}.json"


def run_event_quality_report_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    cfg: EventQualityConfig | None = None,
) -> dict[str, Any]:
    report = build_event_quality_report(input_path, cfg or EventQualityConfig())
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        report["output"] = str(out)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_event_quality_report(input_path: str | Path, cfg: EventQualityConfig) -> dict[str, Any]:
    src = Path(input_path)
    rows = 0
    malformed_rows = 0
    markets: dict[str, dict[str, list[Any]]] = defaultdict(lambda: {"bbo": [], "trades": []})
    events_by_kind: Counter[str] = Counter()
    events_by_exchange: Counter[str] = Counter()

    with src.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed_rows += 1
                continue
            rows += 1
            kind = str(event.get("event_kind") or "unknown")
            events_by_kind[kind] += 1
            events_by_exchange[str(event.get("exchange") or "unknown")] += 1
            market = _market_key(event)
            if kind in {"bbo", "depth"}:
                sample = _bbo_from_event(event)
                if sample is not None:
                    markets[market]["bbo"].append(sample)
            elif kind == "trade":
                trade = _trade_from_event(event)
                if trade is not None:
                    markets[market]["trades"].append(trade)

    labels: list[dict[str, Any]] = []
    by_market: dict[str, dict[str, Any]] = {}
    for market, payload in sorted(markets.items()):
        bbo_samples = sorted(payload["bbo"], key=lambda item: item.ts)
        trade_samples = sorted(payload["trades"], key=lambda item: item.ts)
        market_labels = _label_market_events(market, bbo_samples, trade_samples, cfg)
        by_market[market] = _summarize_labels(market_labels)
        labels.extend(market_labels)

    labels.sort(key=lambda item: (item["sweep_ts"], item["market"]))
    summary = _summarize_labels(labels)
    report = {
        "mode": "event_quality_report",
        "input": str(src),
        "config": asdict(cfg),
        "rows": rows,
        "malformed_rows": malformed_rows,
        "events_by_kind": dict(events_by_kind),
        "events_by_exchange": dict(events_by_exchange),
        "market_count": len(markets),
        "total_sweeps": len(labels),
        "summary": summary,
        "by_market": by_market,
        "events_truncated": len(labels) > cfg.max_events,
        "events": labels[: cfg.max_events],
    }
    return report


def _bbo_from_event(event: dict[str, Any]) -> BboSample | None:
    ts = _event_ts(event)
    bid = _as_float(event.get("bid_price"))
    ask = _as_float(event.get("ask_price"))
    if ts is None or bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return BboSample(
        ts=ts,
        bid=bid,
        ask=ask,
        bid_qty=_as_float(event.get("bid_qty")) or 0.0,
        ask_qty=_as_float(event.get("ask_qty")) or 0.0,
        spread_bps=_as_float(event.get("spread_bps")) or _spread_bps(bid, ask),
    )


def _trade_from_event(event: dict[str, Any]) -> TradeSample | None:
    ts = _event_ts(event)
    price = _as_float(event.get("price"))
    qty = _as_float(event.get("qty"))
    side = str(event.get("side") or "").lower()
    if ts is None or price is None or qty is None or price <= 0 or qty <= 0 or side not in {"buy", "sell"}:
        return None
    return TradeSample(
        ts=ts,
        exchange=str(event.get("exchange") or ""),
        symbol=str(event.get("symbol") or ""),
        side=side,
        price=price,
        qty=qty,
        notional_quote=price * qty,
        mark_price=_as_float(event.get("mark_price")),
        index_price=_as_float(event.get("index_price")),
        funding_rate=_as_float(event.get("funding_rate")),
    )


def _label_market_events(
    market: str,
    bbo_samples: list[BboSample],
    trade_samples: list[TradeSample],
    cfg: EventQualityConfig,
) -> list[dict[str, Any]]:
    if not bbo_samples or not trade_samples:
        return []
    bbo_ts = [sample.ts for sample in bbo_samples]
    labels: list[dict[str, Any]] = []
    last_event_ts_by_side: dict[str, float] = {}

    for trade in trade_samples:
        if trade.notional_quote < cfg.min_sweep_notional_quote:
            continue
        prior_start = bisect.bisect_left(bbo_ts, trade.ts - cfg.lookback_sec)
        prior_end = bisect.bisect_left(bbo_ts, trade.ts)
        if prior_end <= prior_start:
            continue
        prior = bbo_samples[prior_start:prior_end]
        last_prior = prior[-1]
        if cfg.max_pre_spread_bps > 0 and last_prior.spread_bps is not None and last_prior.spread_bps > cfg.max_pre_spread_bps:
            continue
        candidate = _sweep_candidate(market, trade, prior, last_prior)
        if candidate is None:
            continue
        last_ts = last_event_ts_by_side.get(str(candidate["sweep_side"]))
        if last_ts is not None and trade.ts - last_ts < cfg.event_cooldown_sec:
            continue
        last_event_ts_by_side[str(candidate["sweep_side"])] = trade.ts
        label = _score_candidate(candidate, bbo_samples, bbo_ts, cfg)
        labels.append(label)
    return labels


def _sweep_candidate(
    market: str,
    trade: TradeSample,
    prior: list[BboSample],
    last_prior: BboSample,
) -> dict[str, Any] | None:
    if trade.side == "sell":
        level = min(sample.bid for sample in prior)
        if trade.price >= level:
            return None
        sweep_intensity_bps = (level - trade.price) / level * 1e4
        expected_side = "LONG"
        direction = 1
    else:
        level = max(sample.ask for sample in prior)
        if trade.price <= level:
            return None
        sweep_intensity_bps = (trade.price - level) / level * 1e4
        expected_side = "SHORT"
        direction = -1
    return {
        "market": market,
        "exchange": trade.exchange,
        "symbol": trade.symbol,
        "sweep_side": trade.side,
        "expected_side": expected_side,
        "direction": direction,
        "sweep_ts": trade.ts,
        "sweep_price": trade.price,
        "sweep_level": level,
        "sweep_intensity_bps": sweep_intensity_bps,
        "trade_notional_quote": trade.notional_quote,
        "pre_bid": last_prior.bid,
        "pre_ask": last_prior.ask,
        "pre_spread_bps": last_prior.spread_bps,
        "funding_rate": trade.funding_rate,
        "mark_index_basis_bps": _basis_bps(trade.mark_price, trade.index_price),
    }


def _score_candidate(candidate: dict[str, Any], bbo_samples: list[BboSample], bbo_ts: list[float], cfg: EventQualityConfig) -> dict[str, Any]:
    start = bisect.bisect_left(bbo_ts, float(candidate["sweep_ts"]))
    end = bisect.bisect_right(bbo_ts, float(candidate["sweep_ts"]) + cfg.horizon_sec)
    future = bbo_samples[start:end]
    direction = int(candidate["direction"])
    sweep_level = float(candidate["sweep_level"])
    reclaim_level = sweep_level * (1.0 + cfg.reclaim_bps / 1e4) if direction > 0 else sweep_level * (1.0 - cfg.reclaim_bps / 1e4)

    reclaim_index: int | None = None
    for idx, sample in enumerate(future):
        if direction > 0 and sample.bid >= reclaim_level:
            reclaim_index = idx
            break
        if direction < 0 and sample.ask <= reclaim_level:
            reclaim_index = idx
            break

    label = {key: value for key, value in candidate.items() if key != "direction"}
    label["reclaimed"] = reclaim_index is not None
    label["quote_updates_horizon"] = len(future)
    if reclaim_index is None:
        label.update(
            {
                "reclaim_ts": None,
                "time_to_reclaim_sec": None,
                "entry_mid": None,
                "favorable_excursion_bps": None,
                "adverse_excursion_bps": None,
                "target_hit": False,
                "stop_hit": False,
                "first_hit": None,
                "outcome": "no_reclaim",
            }
        )
        return label

    reclaim_sample = future[reclaim_index]
    entry_mid = reclaim_sample.mid
    returns: list[tuple[float, float]] = []
    first_hit: str | None = None
    for sample in future[reclaim_index:]:
        ret = ((sample.mid - entry_mid) / entry_mid * 1e4) if direction > 0 else ((entry_mid - sample.mid) / entry_mid * 1e4)
        returns.append((sample.ts, ret))
        if first_hit is None:
            if ret >= cfg.target_bps:
                first_hit = "target"
            elif ret <= -abs(cfg.stop_bps):
                first_hit = "stop"

    favorable = max((item[1] for item in returns), default=0.0)
    adverse = min((item[1] for item in returns), default=0.0)
    target_hit = any(item[1] >= cfg.target_bps for item in returns)
    stop_hit = any(item[1] <= -abs(cfg.stop_bps) for item in returns)
    if first_hit == "target":
        outcome = "target_before_stop"
    elif first_hit == "stop":
        outcome = "stop_before_target"
    else:
        outcome = "reclaimed_no_hit"

    label.update(
        {
            "reclaim_ts": reclaim_sample.ts,
            "time_to_reclaim_sec": reclaim_sample.ts - float(candidate["sweep_ts"]),
            "entry_mid": entry_mid,
            "favorable_excursion_bps": favorable,
            "adverse_excursion_bps": adverse,
            "target_hit": target_hit,
            "stop_hit": stop_hit,
            "first_hit": first_hit,
            "outcome": outcome,
        }
    )
    return label


def _summarize_labels(labels: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(labels)
    outcomes = Counter(str(item.get("outcome")) for item in labels)
    by_side = Counter(str(item.get("expected_side")) for item in labels)
    reclaimed = sum(1 for item in labels if item.get("reclaimed"))
    target_first = outcomes.get("target_before_stop", 0)
    stop_first = outcomes.get("stop_before_target", 0)
    with_reclaim = [item for item in labels if item.get("reclaimed")]
    return {
        "total_sweeps": total,
        "reclaimed": reclaimed,
        "reclaim_rate": reclaimed / total if total else 0.0,
        "target_before_stop": target_first,
        "stop_before_target": stop_first,
        "target_before_stop_rate": target_first / reclaimed if reclaimed else 0.0,
        "false_sweep_rate": (total - target_first) / total if total else 0.0,
        "avg_sweep_intensity_bps": _avg(item.get("sweep_intensity_bps") for item in labels),
        "avg_time_to_reclaim_sec": _avg(item.get("time_to_reclaim_sec") for item in with_reclaim),
        "avg_favorable_excursion_bps": _avg(item.get("favorable_excursion_bps") for item in with_reclaim),
        "avg_adverse_excursion_bps": _avg(item.get("adverse_excursion_bps") for item in with_reclaim),
        "outcomes": dict(outcomes),
        "by_expected_side": dict(by_side),
    }


def _avg(values: Any) -> float | None:
    nums = [float(value) for value in values if value is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)
