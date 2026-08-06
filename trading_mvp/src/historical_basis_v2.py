from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from costs import (
        CostProfile,
        VenueFeeSchedule,
        base_api_cost_profile,
        route_legs,
        validate_runtime_sec,
    )
    from historical_basis_code_snapshot import validate_basis_code_snapshot_reference
except ImportError:  # pragma: no cover - package import fallback
    from .costs import (
        CostProfile,
        VenueFeeSchedule,
        base_api_cost_profile,
        route_legs,
        validate_runtime_sec,
    )
    from .historical_basis_code_snapshot import validate_basis_code_snapshot_reference


HYPOTHESIS_ID = "cross_venue_perp_basis_convergence_1h_v2"
DATA_TYPE = "HISTORICAL_PERP_BASIS_1H_FUNDING_EVENTS_V2"
PLAN_SCHEMA = "trading_mvp_historical_basis_v2_plan_v1"
RESULT_SCHEMA = "trading_mvp_historical_basis_v2_evaluation_v1"
PREFLIGHT_ACCEPTED = "PREFLIGHT_ACCEPTED_NOT_COLLECTED"
PLAN_MODE = "PlanOnly"

HOUR_SEC = 3_600
FOUR_HOUR_SEC = 4 * HOUR_SEC
DAY_SEC = 86_400
WINDOW_DAYS = 179
WARMUP_DAYS = 14
TRAIN_DAYS = 85
OOS_DAYS = 80
OOS_SUBPERIOD_COUNT = 5
OOS_SUBPERIOD_DAYS = 16
MIN_UNIVERSE_ASSETS = 8
MAX_UNIVERSE_ASSETS = 20
DEFAULT_EXIT_THRESHOLD_BPS = 20.0
DEFAULT_SAFETY_MARGIN_BPS = 20.0
DEFAULT_MAX_HOLD_HOURS = 72
DEFAULT_NOTIONAL_QUOTE_PER_LEG = 500.0
DEFAULT_MAX_GAP_SEC = 3 * HOUR_SEC
NO_LOSS_PROFIT_FACTOR = 1_000_000_000.0

EXCLUDED_CATEGORIES = {
    "index",
    "leveraged",
    "lp",
    "pre-market",
    "pre_market",
    "stable",
    "staked",
    "synthetic",
    "tokenized",
    "tokenized_stock",
    "wrapped",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _finite(value: Any, *, name: str, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if positive and result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _normalize_venue(value: str) -> str:
    venue = str(value).strip().lower()
    if venue == "gate":
        venue = "gateio"
    if venue not in {"mexc", "gateio"}:
        raise ValueError(f"unsupported venue: {value}")
    return venue


@dataclass(frozen=True)
class BasisBar:
    ts: int
    base: str
    mexc_trade_open: float
    mexc_trade_close: float
    mexc_mark_close: float
    mexc_index_close: float
    mexc_volume_quote: float
    gateio_trade_open: float
    gateio_trade_close: float
    gateio_mark_close: float
    gateio_index_close: float
    gateio_volume_quote: float

    def __post_init__(self) -> None:
        ts = int(self.ts)
        if ts < 0:
            raise ValueError("bar timestamp must be non-negative")
        base = str(self.base).strip().upper()
        if not base:
            raise ValueError("bar base is required")
        object.__setattr__(self, "ts", ts)
        object.__setattr__(self, "base", base)
        for name in self.__dataclass_fields__:
            if name in {"ts", "base"}:
                continue
            value = _finite(getattr(self, name), name=name)
            if name.endswith("volume_quote"):
                if value < 0.0:
                    raise ValueError(f"{name} must be non-negative")
            elif value <= 0.0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "BasisBar":
        forbidden = [key for key in row if "funding" in str(key).lower()]
        if forbidden:
            raise ValueError("funding fields are forbidden in BasisBar")
        try:
            values = {name: row[name] for name in cls.__dataclass_fields__}
        except KeyError as exc:
            raise ValueError(f"missing BasisBar field: {exc.args[0]}") from exc
        return cls(**values)

    def venue_basis_bps(self, venue: str) -> float:
        normalized = _normalize_venue(venue)
        if normalized == "mexc":
            mark, index = self.mexc_mark_close, self.mexc_index_close
        else:
            mark, index = self.gateio_mark_close, self.gateio_index_close
        return (mark - index) / index * 10_000.0

    def basis_spread_bps(self) -> float:
        return abs(self.venue_basis_bps("mexc") - self.venue_basis_bps("gateio"))

    def trade_open(self, venue: str) -> float:
        return (
            self.mexc_trade_open
            if _normalize_venue(venue) == "mexc"
            else self.gateio_trade_open
        )


@dataclass(frozen=True)
class FundingEvent:
    venue: str
    base: str
    settlement_ts: int | float
    rate: float
    event_id: str | None = None
    settlement_identity: str = field(init=False)

    def __post_init__(self) -> None:
        venue = _normalize_venue(self.venue)
        base = str(self.base).strip().upper()
        settlement_value = _finite(self.settlement_ts, name="funding settlement timestamp")
        settlement_ts: int | float = (
            int(settlement_value) if settlement_value.is_integer() else settlement_value
        )
        rate = _finite(self.rate, name="funding rate")
        if not base:
            raise ValueError("funding event base is required")
        if settlement_ts < 0:
            raise ValueError("funding settlement timestamp must be non-negative")
        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "settlement_ts", settlement_ts)
        object.__setattr__(self, "rate", rate)
        settlement_identity = sha256_json(
            {
                "venue": venue,
                "base": base,
                "settlement_ts": settlement_ts,
            }
        )
        event_id = settlement_identity if self.event_id is None else str(self.event_id).strip()
        if not event_id:
            raise ValueError("funding event identity must not be empty")
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "settlement_identity", settlement_identity)

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "FundingEvent":
        settlement_ts = row.get("settlement_ts", row.get("ts"))
        rate = row.get("rate", row.get("funding_rate"))
        event = cls(
            venue=str(row.get("venue") or row.get("exchange") or ""),
            base=str(row.get("base") or ""),
            settlement_ts=float(settlement_ts),
            rate=float(rate),
            event_id=(str(row["event_id"]) if row.get("event_id") is not None else None),
        )
        return event


@dataclass(frozen=True)
class EntrySignal:
    base: str
    signal_ts: int
    signal_available_ts: int
    entry_ts: int
    long_venue: str
    short_venue: str
    long_entry_price: float
    short_entry_price: float
    signal_spread_bps: float
    episode_id: str

    @property
    def direction(self) -> str:
        return f"{self.long_venue}_long"


@dataclass(frozen=True)
class TradeResult:
    episode_id: str
    base: str
    signal_ts: int
    signal_available_ts: int
    entry_ts: int
    exit_signal_ts: int | None
    exit_ts: int
    long_venue: str
    short_venue: str
    exit_reason: str
    long_entry_price: float
    short_entry_price: float
    long_exit_price: float
    short_exit_price: float
    gross_price_pnl_quote: float
    funding_pnl_quote: float
    cost_quote: float
    price_only_net_pnl_quote: float
    net_pnl_quote: float
    holding_sec: int
    stress: bool
    funding_event_ids: tuple[str, ...]

    @property
    def direction(self) -> str:
        return f"{self.long_venue}_long"

    @property
    def signal_date(self) -> str:
        return datetime.fromtimestamp(self.signal_available_ts, timezone.utc).date().isoformat()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["funding_event_ids"] = list(self.funding_event_ids)
        return payload


@dataclass(frozen=True)
class InvalidatedPosition:
    episode_id: str
    base: str
    entry_ts: int
    invalidated_ts: int
    reason: str


@dataclass(frozen=True)
class SimulationResult:
    trades: tuple[TradeResult, ...]
    entries: tuple[EntrySignal, ...]
    invalidated_positions: tuple[InvalidatedPosition, ...]


def _normalize_funding_events(
    events: Iterable[FundingEvent | Mapping[str, Any]],
) -> list[FundingEvent]:
    normalized = [
        event if isinstance(event, FundingEvent) else FundingEvent.from_dict(event)
        for event in events
    ]
    seen: set[str] = set()
    seen_settlements: set[str] = set()
    for event in normalized:
        if event.event_id in seen:
            raise ValueError(f"duplicate funding event identity: {event.event_id}")
        if event.settlement_identity in seen_settlements:
            raise ValueError(
                f"duplicate funding event settlement: {event.settlement_identity}"
            )
        seen.add(event.event_id)
        seen_settlements.add(event.settlement_identity)
    return sorted(
        normalized,
        key=lambda event: (event.settlement_ts, event.base, event.venue, event.event_id),
    )


def _funding_attribution(
    events: Sequence[FundingEvent],
    *,
    base: str,
    long_venue: str,
    short_venue: str,
    entry_ts: int,
    exit_ts: int,
    notional_quote_per_leg: float,
    stress: bool,
    favorable_stress_haircut: float,
) -> tuple[float, tuple[str, ...]]:
    if exit_ts <= entry_ts:
        raise ValueError("funding attribution requires exit_ts > entry_ts")
    if not 0.0 <= favorable_stress_haircut <= 1.0:
        raise ValueError("favorable_stress_haircut must be in [0, 1]")
    normalized_base = str(base).strip().upper()
    normalized_long = _normalize_venue(long_venue)
    normalized_short = _normalize_venue(short_venue)
    notional = _finite(
        notional_quote_per_leg,
        name="notional_quote_per_leg",
        positive=True,
    )
    total = 0.0
    attributed: list[str] = []
    for event in events:
        if event.base != normalized_base:
            continue
        if not entry_ts <= event.settlement_ts < exit_ts:
            continue
        if event.venue == normalized_long:
            cashflow = -notional * event.rate
        elif event.venue == normalized_short:
            cashflow = notional * event.rate
        else:  # pragma: no cover - normalized venues make this defensive only
            continue
        if stress and cashflow > 0.0:
            cashflow *= favorable_stress_haircut
        total += cashflow
        attributed.append(event.event_id)
    return total, tuple(attributed)


def compute_funding_cashflow(
    events: Iterable[FundingEvent | Mapping[str, Any]],
    *,
    base: str,
    long_venue: str,
    short_venue: str,
    entry_ts: int,
    exit_ts: int,
    notional_quote_per_leg: float,
    stress: bool = False,
    favorable_stress_haircut: float = 0.5,
) -> float:
    normalized = _normalize_funding_events(events)
    value, _event_ids = _funding_attribution(
        normalized,
        base=base,
        long_venue=long_venue,
        short_venue=short_venue,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        notional_quote_per_leg=notional_quote_per_leg,
        stress=stress,
        favorable_stress_haircut=favorable_stress_haircut,
    )
    return value


def _entry_signal(signal_bar: BasisBar, entry_bar: BasisBar, interval_sec: int) -> EntrySignal:
    mexc_basis = signal_bar.venue_basis_bps("mexc")
    gate_basis = signal_bar.venue_basis_bps("gateio")
    if mexc_basis < gate_basis:
        long_venue, short_venue = "mexc", "gateio"
    else:
        long_venue, short_venue = "gateio", "mexc"
    identity = {
        "base": signal_bar.base,
        "signal_ts": signal_bar.ts,
        "entry_ts": entry_bar.ts,
        "long_venue": long_venue,
        "short_venue": short_venue,
    }
    return EntrySignal(
        base=signal_bar.base,
        signal_ts=signal_bar.ts,
        signal_available_ts=signal_bar.ts + interval_sec,
        entry_ts=entry_bar.ts,
        long_venue=long_venue,
        short_venue=short_venue,
        long_entry_price=entry_bar.trade_open(long_venue),
        short_entry_price=entry_bar.trade_open(short_venue),
        signal_spread_bps=signal_bar.basis_spread_bps(),
        episode_id=sha256_json(identity),
    )


def _close_trade(
    entry: EntrySignal,
    exit_bar: BasisBar,
    *,
    exit_signal_ts: int | None,
    exit_reason: str,
    funding_events: Sequence[FundingEvent],
    notional_quote_per_leg: float,
    cycle_cost_bps: float,
    stress: bool,
    favorable_funding_stress_haircut: float,
) -> TradeResult:
    long_exit = exit_bar.trade_open(entry.long_venue)
    short_exit = exit_bar.trade_open(entry.short_venue)
    notional = _finite(
        notional_quote_per_leg,
        name="notional_quote_per_leg",
        positive=True,
    )
    long_quantity = notional / entry.long_entry_price
    short_quantity = notional / entry.short_entry_price
    gross_price = (long_exit - entry.long_entry_price) * long_quantity
    gross_price += (entry.short_entry_price - short_exit) * short_quantity
    funding, event_ids = _funding_attribution(
        funding_events,
        base=entry.base,
        long_venue=entry.long_venue,
        short_venue=entry.short_venue,
        entry_ts=entry.entry_ts,
        exit_ts=exit_bar.ts,
        notional_quote_per_leg=notional,
        stress=stress,
        favorable_stress_haircut=favorable_funding_stress_haircut,
    )
    cost = notional * _finite(cycle_cost_bps, name="cycle_cost_bps") / 10_000.0
    price_only = gross_price - cost
    return TradeResult(
        episode_id=entry.episode_id,
        base=entry.base,
        signal_ts=entry.signal_ts,
        signal_available_ts=entry.signal_available_ts,
        entry_ts=entry.entry_ts,
        exit_signal_ts=exit_signal_ts,
        exit_ts=exit_bar.ts,
        long_venue=entry.long_venue,
        short_venue=entry.short_venue,
        exit_reason=exit_reason,
        long_entry_price=entry.long_entry_price,
        short_entry_price=entry.short_entry_price,
        long_exit_price=long_exit,
        short_exit_price=short_exit,
        gross_price_pnl_quote=gross_price,
        funding_pnl_quote=funding,
        cost_quote=cost,
        price_only_net_pnl_quote=price_only,
        net_pnl_quote=price_only + funding,
        holding_sec=exit_bar.ts - entry.entry_ts,
        stress=stress,
        funding_event_ids=event_ids,
    )


def simulate_basis_episodes(
    bars: Iterable[BasisBar | Mapping[str, Any]],
    funding_events: Iterable[FundingEvent | Mapping[str, Any]],
    *,
    entry_threshold_bps: float,
    exit_threshold_bps: float = DEFAULT_EXIT_THRESHOLD_BPS,
    maximum_holding_hours: int = DEFAULT_MAX_HOLD_HOURS,
    notional_quote_per_leg: float = DEFAULT_NOTIONAL_QUOTE_PER_LEG,
    cycle_cost_bps: float = 0.0,
    stress: bool = False,
    favorable_funding_stress_haircut: float = 0.5,
    interval_sec: int = HOUR_SEC,
    maximum_gap_sec: int = DEFAULT_MAX_GAP_SEC,
) -> SimulationResult:
    if interval_sec <= 0:
        raise ValueError("interval_sec must be positive")
    if maximum_gap_sec < interval_sec:
        raise ValueError("maximum_gap_sec must be at least one interval")
    if maximum_holding_hours <= 0:
        raise ValueError("maximum_holding_hours must be positive")
    entry_threshold = _finite(entry_threshold_bps, name="entry_threshold_bps")
    exit_threshold = _finite(exit_threshold_bps, name="exit_threshold_bps")
    if entry_threshold <= exit_threshold:
        raise ValueError("entry threshold must exceed exit threshold")
    normalized_bars = [
        row if isinstance(row, BasisBar) else BasisBar.from_dict(row) for row in bars
    ]
    normalized_events = _normalize_funding_events(funding_events)
    events_by_base: dict[str, list[FundingEvent]] = {}
    for event in normalized_events:
        events_by_base.setdefault(event.base, []).append(event)
    bars_by_base: dict[str, list[BasisBar]] = {}
    for bar in normalized_bars:
        bars_by_base.setdefault(bar.base, []).append(bar)

    trades: list[TradeResult] = []
    entries: list[EntrySignal] = []
    invalidated: list[InvalidatedPosition] = []
    max_hold_sec = int(maximum_holding_hours) * HOUR_SEC

    for base in sorted(bars_by_base):
        ordered = sorted(bars_by_base[base], key=lambda row: row.ts)
        timestamps = [row.ts for row in ordered]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError(f"duplicate BasisBar timestamp for {base}")
        position: EntrySignal | None = None
        awaiting_reset = False
        previous_spread: float | None = None
        index = 0
        while index < len(ordered):
            current = ordered[index]
            if index > 0:
                gap = current.ts - ordered[index - 1].ts
                if gap != interval_sec:
                    if position is not None:
                        reason = (
                            "gap_over_3h"
                            if gap > maximum_gap_sec
                            else "non_contiguous_execution"
                        )
                        invalidated.append(
                            InvalidatedPosition(
                                episode_id=position.episode_id,
                                base=position.base,
                                entry_ts=position.entry_ts,
                                invalidated_ts=current.ts,
                                reason=reason,
                            )
                        )
                        position = None
                        awaiting_reset = False
                    previous_spread = None

            spread = current.basis_spread_bps()
            if position is not None:
                if current.ts - position.entry_ts >= max_hold_sec:
                    trades.append(
                        _close_trade(
                            position,
                            current,
                            exit_signal_ts=None,
                            exit_reason="max_hold",
                            funding_events=events_by_base.get(base, []),
                            notional_quote_per_leg=notional_quote_per_leg,
                            cycle_cost_bps=cycle_cost_bps,
                            stress=stress,
                            favorable_funding_stress_haircut=(
                                favorable_funding_stress_haircut
                            ),
                        )
                    )
                    position = None
                    awaiting_reset = True
                    previous_spread = None
                elif spread <= exit_threshold:
                    if index + 1 >= len(ordered):
                        invalidated.append(
                            InvalidatedPosition(
                                episode_id=position.episode_id,
                                base=position.base,
                                entry_ts=position.entry_ts,
                                invalidated_ts=current.ts + interval_sec,
                                reason="right_censored",
                            )
                        )
                        position = None
                        break
                    executable = ordered[index + 1]
                    execution_gap = executable.ts - current.ts
                    if execution_gap != interval_sec:
                        reason = (
                            "gap_over_3h"
                            if execution_gap > maximum_gap_sec
                            else "non_contiguous_execution"
                        )
                        invalidated.append(
                            InvalidatedPosition(
                                episode_id=position.episode_id,
                                base=position.base,
                                entry_ts=position.entry_ts,
                                invalidated_ts=executable.ts,
                                reason=reason,
                            )
                        )
                        position = None
                        awaiting_reset = False
                        previous_spread = None
                    else:
                        trades.append(
                            _close_trade(
                                position,
                                executable,
                                exit_signal_ts=current.ts,
                                exit_reason="convergence",
                                funding_events=events_by_base.get(base, []),
                                notional_quote_per_leg=notional_quote_per_leg,
                                cycle_cost_bps=cycle_cost_bps,
                                stress=stress,
                                favorable_funding_stress_haircut=(
                                    favorable_funding_stress_haircut
                                ),
                            )
                        )
                        position = None
                        awaiting_reset = True
                        previous_spread = None
                        index += 1
                        continue
                else:
                    index += 1
                    continue

            if awaiting_reset:
                if spread <= exit_threshold:
                    awaiting_reset = False
                    previous_spread = spread
                else:
                    previous_spread = None
            else:
                crossed = (
                    previous_spread is not None
                    and previous_spread < entry_threshold
                    and spread >= entry_threshold
                )
                if crossed and index + 1 < len(ordered):
                    executable = ordered[index + 1]
                    if executable.ts - current.ts == interval_sec:
                        position = _entry_signal(current, executable, interval_sec)
                        entries.append(position)
                        previous_spread = None
                    else:
                        previous_spread = None
                elif crossed:
                    previous_spread = None
                else:
                    previous_spread = spread
            index += 1

        if position is not None:
            invalidated.append(
                InvalidatedPosition(
                    episode_id=position.episode_id,
                    base=position.base,
                    entry_ts=position.entry_ts,
                    invalidated_ts=ordered[-1].ts + interval_sec,
                    reason="right_censored",
                )
            )

    return SimulationResult(
        trades=tuple(sorted(trades, key=lambda row: (row.entry_ts, row.base, row.episode_id))),
        entries=tuple(sorted(entries, key=lambda row: (row.entry_ts, row.base, row.episode_id))),
        invalidated_positions=tuple(
            sorted(
                invalidated,
                key=lambda row: (row.invalidated_ts, row.base, row.episode_id),
            )
        ),
    )


def build_split_contract(window_start_ts: int, window_end_ts: int) -> dict[str, Any]:
    start = int(window_start_ts)
    end = int(window_end_ts)
    if start % HOUR_SEC or end % HOUR_SEC:
        raise ValueError("window boundaries must be closed UTC hours")
    if end - start != WINDOW_DAYS * DAY_SEC:
        raise ValueError("historical window must contain exactly 179 closed UTC days")
    warmup_end = start + WARMUP_DAYS * DAY_SEC
    train_end = warmup_end + TRAIN_DAYS * DAY_SEC
    subperiods = []
    for index in range(OOS_SUBPERIOD_COUNT):
        subperiod_start = train_end + index * OOS_SUBPERIOD_DAYS * DAY_SEC
        subperiods.append(
            {
                "label": f"oos_subperiod_{index + 1}",
                "start_ts": subperiod_start,
                "end_ts": subperiod_start + OOS_SUBPERIOD_DAYS * DAY_SEC,
                "days": OOS_SUBPERIOD_DAYS,
            }
        )
    return {
        "interval": "[start,end)",
        "window_start_ts": start,
        "window_end_ts": end,
        "warmup": {
            "label": "warmup",
            "start_ts": start,
            "end_ts": warmup_end,
            "days": WARMUP_DAYS,
        },
        "train": {
            "label": "train",
            "start_ts": warmup_end,
            "end_ts": train_end,
            "days": TRAIN_DAYS,
        },
        "oos": {
            "label": "oos",
            "start_ts": train_end,
            "end_ts": end,
            "days": OOS_DAYS,
        },
        "oos_subperiods": subperiods,
    }


def label_split_timestamp(split: Mapping[str, Any], ts: int) -> str | None:
    value = int(ts)
    for key in ("warmup", "train"):
        row = split[key]
        if int(row["start_ts"]) <= value < int(row["end_ts"]):
            return str(row["label"])
    for row in split["oos_subperiods"]:
        if int(row["start_ts"]) <= value < int(row["end_ts"]):
            return str(row["label"])
    return None


def fixed_oos_subperiods(
    oos_start_ts: int,
    oos_end_ts: int | None = None,
) -> list[dict[str, Any]]:
    start = int(oos_start_ts)
    expected_end = start + OOS_DAYS * DAY_SEC
    if oos_end_ts is not None and int(oos_end_ts) != expected_end:
        raise ValueError("OOS window must contain exactly 80 days")
    return [
        {
            "label": f"oos_subperiod_{index + 1}",
            "start_ts": start + index * OOS_SUBPERIOD_DAYS * DAY_SEC,
            "end_ts": start + (index + 1) * OOS_SUBPERIOD_DAYS * DAY_SEC,
            "days": OOS_SUBPERIOD_DAYS,
        }
        for index in range(OOS_SUBPERIOD_COUNT)
    ]


def _cost_profile_from_dict(payload: Mapping[str, Any]) -> CostProfile:
    schedules: dict[str, VenueFeeSchedule] = {}
    raw_schedules = payload.get("schedules")
    if not isinstance(raw_schedules, Mapping):
        raise ValueError("cost profile schedules are missing")
    for key, row in raw_schedules.items():
        if not isinstance(row, Mapping):
            raise ValueError("invalid venue fee schedule")
        schedules[str(key)] = VenueFeeSchedule(
            exchange=str(row.get("exchange") or key),
            spot_maker_bps=float(row["spot_maker_bps"]),
            spot_taker_bps=float(row["spot_taker_bps"]),
            perp_maker_bps=float(row["perp_maker_bps"]),
            perp_taker_bps=float(row["perp_taker_bps"]),
            source=str(row.get("source") or ""),
            effective_at=(
                str(row["effective_at"]) if row.get("effective_at") is not None else None
            ),
            account_verified=bool(row.get("account_verified")),
            conservative_floor_bps=float(row.get("conservative_floor_bps") or 0.0),
        )
    return CostProfile(
        name=str(payload.get("name") or "base_api"),
        schedules=schedules,
        maker_fill_probability=float(payload.get("maker_fill_probability") or 0.0),
        slippage_bps_per_order=float(payload.get("slippage_bps_per_order") or 0.0),
        rebalance_buffer_bps=float(payload.get("rebalance_buffer_bps") or 0.0),
        default_spread_bps=float(payload.get("default_spread_bps") or 0.0),
        default_impact_bps=float(payload.get("default_impact_bps") or 0.0),
        funding_haircut=float(payload.get("funding_haircut", 1.0)),
    )


def frozen_cost_economics(
    profile: CostProfile | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    taker_profile = replace(
        profile or base_api_cost_profile(),
        maker_fill_probability=0.0,
    )
    legs = route_legs("cross_venue_perp_perp", profile=taker_profile)
    return (
        taker_profile.as_dict(),
        taker_profile.cycle_cost(legs),
        taker_profile.cycle_cost(legs, stress=True),
    )


def _candidate_symbol(asset: Mapping[str, Any], venue: str) -> str:
    direct_names = (
        ("mexc_symbol", "mexc_contract")
        if venue == "mexc"
        else ("gateio_symbol", "gate_symbol", "gateio_contract")
    )
    for name in direct_names:
        value = str(asset.get(name) or "").strip().upper()
        if value:
            return value
    for container_name in ("symbols", "venue_symbols", "native_symbols"):
        container = asset.get(container_name)
        if isinstance(container, Mapping):
            value = str(container.get(venue) or container.get("gate" if venue == "gateio" else venue) or "")
            if value.strip():
                return value.strip().upper()
    return ""


def _normalize_candidate(asset: Mapping[str, Any]) -> dict[str, Any] | None:
    base = str(asset.get("base") or asset.get("symbol") or "").strip().upper()
    canonical_id = str(
        asset.get("canonical_asset_id") or asset.get("coin_id") or asset.get("asset_id") or ""
    ).strip()
    quote = str(asset.get("quote") or "USDT").strip().upper()
    categories = {str(value).strip().lower() for value in asset.get("categories") or []}
    if not base or not canonical_id or quote != "USDT":
        return None
    if bool(asset.get("binance_spot") or asset.get("binance_spot_listed")):
        return None
    if categories & EXCLUDED_CATEGORIES:
        return None
    mexc_symbol = _candidate_symbol(asset, "mexc")
    gateio_symbol = _candidate_symbol(asset, "gateio")
    if not mexc_symbol or not gateio_symbol:
        return None
    return {
        "canonical_asset_id": canonical_id,
        "base": base,
        "quote": "USDT",
        "mexc_symbol": mexc_symbol,
        "gateio_symbol": gateio_symbol,
        "common_history_days": int(asset.get("common_history_days") or WINDOW_DAYS),
        "categories": sorted(categories),
        "binance_spot": False,
    }


def _freeze_candidates(assets: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    key_owners: dict[tuple[str, str], set[str]] = {}
    for raw in assets:
        candidate = _normalize_candidate(raw)
        if candidate is None:
            continue
        canonical_id = candidate["canonical_asset_id"]
        if canonical_id in by_id and by_id[canonical_id] != candidate:
            raise ValueError(f"canonical identity collision: {canonical_id}")
        by_id[canonical_id] = candidate
        for key_name in ("base", "mexc_symbol", "gateio_symbol"):
            key_owners.setdefault((key_name, candidate[key_name]), set()).add(canonical_id)
    ambiguous = {
        owner
        for owners in key_owners.values()
        if len(owners) > 1
        for owner in owners
    }
    candidates = sorted(
        (row for key, row in by_id.items() if key not in ambiguous),
        key=lambda row: (row["canonical_asset_id"], row["base"]),
    )[:MAX_UNIVERSE_ASSETS]
    if len(candidates) < MIN_UNIVERSE_ASSETS:
        raise ValueError(
            "INSUFFICIENT_EXECUTABLE_UNIVERSE: "
            f"need {MIN_UNIVERSE_ASSETS}, observed {len(candidates)}"
        )
    return candidates


def _content_addressed_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        ignored_location_keys = {
            "path",
            "module_path",
            "code_snapshot_manifest",
        }
        return {
            key: _content_addressed_value(item)
            for key, item in value.items()
            if key not in ignored_location_keys and not str(key).endswith("_path")
        }
    if isinstance(value, (list, tuple)):
        return [_content_addressed_value(item) for item in value]
    return value


def _sealed_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "hypothesis",
        "preflight_provenance",
        "universe",
        "strategy",
        "economics",
        "sample_plan",
        "split_contract",
        "quality_gates",
        "acceptance_gates",
        "runtime",
        "safety",
        "code_provenance",
    )
    return _content_addressed_value({key: plan.get(key) for key in keys})


def build_historical_basis_v2_plan(
    assets: Iterable[Mapping[str, Any]],
    output_path: str | Path | None = None,
    *,
    window_end_ts: int,
    window_start_ts: int | None = None,
    cost_profile: CostProfile | None = None,
    frozen_at_utc: str | None = None,
    max_runtime_sec: int = 600,
    preflight_provenance: Mapping[str, Any] | None = None,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
) -> dict[str, Any]:
    runtime = validate_runtime_sec(max_runtime_sec)
    if runtime > 600:
        raise ValueError("plan max_runtime_sec must be <= 600")
    end = int(window_end_ts)
    start = end - WINDOW_DAYS * DAY_SEC if window_start_ts is None else int(window_start_ts)
    split = build_split_contract(start, end)
    candidates = _freeze_candidates(assets)
    profile, normal_cost, stress_cost = frozen_cost_economics(cost_profile)
    entry_threshold = (
        float(stress_cost["total_bps"])
        + DEFAULT_EXIT_THRESHOLD_BPS
        + DEFAULT_SAFETY_MARGIN_BPS
    )
    snapshot = validate_basis_code_snapshot_reference(
        code_snapshot_hash,
        code_snapshot_manifest,
        fallback_code_path=__file__,
    )
    module_path = Path(__file__).resolve()
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "decision": "HISTORICAL_BASIS_V2_PLAN_FROZEN_NOT_EVALUATED",
        "generated_at_utc": frozen_at_utc or datetime.now(timezone.utc).isoformat(),
        "hypothesis": {
            "id": HYPOTHESIS_ID,
            "required_data_type": DATA_TYPE,
            "frozen_parameters_no_grid": True,
            "retune": False,
        },
        "preflight_provenance": (
            dict(preflight_provenance) if preflight_provenance is not None else None
        ),
        "universe": {
            "venues": ["mexc", "gateio"],
            "market_type": "linear_perp",
            "quote": "USDT",
            "binance_role": "identity_exclusion_reference_only",
            "candidate_limit": MAX_UNIVERSE_ASSETS,
            "primary_limit": 12,
            "reserve_limit": 8,
            "minimum_surviving_assets": MIN_UNIVERSE_ASSETS,
            "selection_uses_oos_outcomes": False,
            "candidates": candidates,
            "universe_hash": sha256_json(candidates),
        },
        "strategy": {
            "signal_interval_sec": HOUR_SEC,
            "signal_price": "closed_mark_and_index",
            "entry_price": "next_contiguous_1h_trade_open",
            "entry_delay_bars": 1,
            "entry_threshold_bps": entry_threshold,
            "exit_threshold_bps": DEFAULT_EXIT_THRESHOLD_BPS,
            "safety_margin_bps": DEFAULT_SAFETY_MARGIN_BPS,
            "maximum_holding_hours": DEFAULT_MAX_HOLD_HOURS,
            "fresh_crossing_from_below": True,
            "post_close_reset_required_bps": DEFAULT_EXIT_THRESHOLD_BPS,
            "fixed_cooldown": False,
            "one_position_per_base": True,
            "route": "long_lower_basis_perp_short_higher_basis_perp",
            "intrabar_touch_used": False,
            "funding_is_signal": False,
        },
        "economics": {
            "notional_quote_per_leg": DEFAULT_NOTIONAL_QUOTE_PER_LEG,
            "gross_leverage": 1.0,
            "fully_collateralized": True,
            "historical_execution": "taker_only",
            "cost_profile": profile,
            "cost_profile_sha256": sha256_json(profile),
            "normal_cycle_cost": normal_cost,
            "stress_cycle_cost": stress_cost,
            "favorable_funding_stress_haircut": 0.5,
            "adverse_funding_stress_haircut": 1.0,
            "funding_attribution_interval": "entry_ts<=settlement_ts<exit_ts",
            "funding_cannot_rescue_negative_price_only_expectancy": True,
        },
        "sample_plan": {
            "interval": "1h",
            "interval_sec": HOUR_SEC,
            "warmup_days": WARMUP_DAYS,
            "train_days": TRAIN_DAYS,
            "oos_days": OOS_DAYS,
            "total_closed_days": WINDOW_DAYS,
            "fixed_oos_subperiod_count": OOS_SUBPERIOD_COUNT,
            "fixed_oos_subperiod_days": OOS_SUBPERIOD_DAYS,
            "chronological": True,
            "oos_embargo_until_train_feasible": True,
        },
        "split_contract": split,
        "quality_gates": {
            "minimum_series_coverage": 0.98,
            "minimum_dual_venue_aligned_coverage": 0.95,
            "minimum_funding_settlement_coverage": 0.98,
            "maximum_segment_gap_sec": DEFAULT_MAX_GAP_SEC,
            "contiguous_execution_required": True,
            "open_bars_allowed": False,
            "duplicate_timestamps_allowed": False,
            "merged_funding_events_allowed": False,
            "minimum_train_median_quote_volume": 1_000_000.0,
        },
        "acceptance_gates": {
            "minimum_train_independent_episodes": 20,
            "minimum_train_dates": 10,
            "minimum_train_directions": 2,
            "minimum_oos_independent_episodes": 40,
            "oos_scarcity_below_minimum_verdict": "INSUFFICIENT_DATA",
            "minimum_oos_dates": 20,
            "minimum_oos_assets": 8,
            "minimum_profit_factor": 1.2,
            "minimum_positive_fixed_subperiods": 4,
            "minimum_four_hour_independent_episodes": 1,
            "four_hour_price_only_must_be_nonnegative": True,
            "four_hour_total_net_must_be_nonnegative": True,
            "minimum_cluster_bootstrap_lower_95_quote": 0.0,
            "maximum_concentration_share": 0.25,
            "maximum_drawdown_fraction": 0.10,
            "maximum_historical_verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        },
        "runtime": {
            "plan_max_runtime_sec": runtime,
            "history_collect_max_runtime_sec": 5_400,
            "quality_max_runtime_sec": 1_800,
            "evaluation_max_runtime_sec": 1_800,
        },
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "grid_search": False,
            "retune": False,
            "paper_forward": False,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
            **snapshot,
        },
        "data_access_audit": {
            "network_access": False,
            "collector_started": False,
            "oos_rows_read": False,
            "pnl_computed": False,
        },
        "next_allowed_command": "fast-edge-basis-v2-history-collect",
        "output_path": (
            str(Path(output_path).expanduser().resolve()) if output_path is not None else None
        ),
    }
    plan["plan_hash"] = sha256_json(_sealed_plan(plan))
    if output_path is not None:
        _write_json_immutable(output_path, plan)
    return plan


def _preflight_candidates(preflight: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    universe = preflight.get("universe")
    if not isinstance(universe, Mapping):
        raise ValueError("preflight universe is missing")
    candidates = universe.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("preflight candidates are missing")
    return candidates


def build_historical_basis_v2_plan_from_preflight(
    preflight_path: str | Path,
    output_path: str | Path,
    *,
    max_runtime_sec: int = 600,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(preflight_path).expanduser().resolve()
    preflight = _read_json(target)
    if preflight.get("verdict") != PREFLIGHT_ACCEPTED:
        raise ValueError("preflight is not PREFLIGHT_ACCEPTED_NOT_COLLECTED")
    audit = preflight.get("data_access_audit") or {}
    forbidden_audit = ("returns_read", "pnl_read", "signals_read", "oos_metrics_read")
    if any(audit.get(key) is not False for key in forbidden_audit):
        raise ValueError("preflight violated the no-outcomes data contract")
    window = preflight.get("window")
    if not isinstance(window, Mapping):
        raise ValueError("preflight window is missing")
    start = int(window.get("window_start_sec"))
    end = int(window.get("window_end_sec"))
    candidates = _preflight_candidates(preflight)
    provenance = {
        "path": str(target),
        "file_sha256": sha256_file(target),
        "schema": preflight.get("schema"),
        "artifact_hash": (
            preflight.get("artifact_hash") or preflight.get("deterministic_result_hash")
        ),
        "preflight_hash": preflight.get("preflight_hash"),
        "verdict": preflight.get("verdict"),
        "window_start_ts": start,
        "window_end_ts": end,
        "candidate_hash": sha256_json(candidates),
    }
    return build_historical_basis_v2_plan(
        candidates,
        output_path,
        window_start_ts=start,
        window_end_ts=end,
        max_runtime_sec=max_runtime_sec,
        preflight_provenance=provenance,
        code_snapshot_hash=code_snapshot_hash,
        code_snapshot_manifest=code_snapshot_manifest,
    )


def _contains_forbidden_split_name(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            "walk" in str(key).lower() or _contains_forbidden_split_name(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_split_name(item) for item in value)
    return isinstance(value, str) and "walk" in value.lower()


def validate_historical_basis_v2_plan(
    plan_or_path: Mapping[str, Any] | str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target: Path | None = None
    if isinstance(plan_or_path, Mapping):
        plan = dict(plan_or_path)
    else:
        target = Path(plan_or_path).expanduser().resolve()
        plan = _read_json(target)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != PLAN_MODE:
        raise ValueError(f"expected {PLAN_SCHEMA} {PLAN_MODE}")
    observed_hash = sha256_json(_sealed_plan(plan))
    if plan.get("plan_hash") != observed_hash:
        raise ValueError("plan hash mismatch")
    if expected_plan_hash is not None and expected_plan_hash != observed_hash:
        raise ValueError("plan does not match expected plan hash")
    if _contains_forbidden_split_name(plan):
        raise ValueError("forbidden split terminology in v2 plan")
    hypothesis = plan.get("hypothesis") or {}
    if hypothesis.get("id") != HYPOTHESIS_ID or hypothesis.get("required_data_type") != DATA_TYPE:
        raise ValueError("unexpected v2 hypothesis")
    sample = plan.get("sample_plan") or {}
    expected_sample = {
        "interval": "1h",
        "interval_sec": HOUR_SEC,
        "warmup_days": WARMUP_DAYS,
        "train_days": TRAIN_DAYS,
        "oos_days": OOS_DAYS,
        "total_closed_days": WINDOW_DAYS,
        "fixed_oos_subperiod_count": OOS_SUBPERIOD_COUNT,
        "fixed_oos_subperiod_days": OOS_SUBPERIOD_DAYS,
    }
    for key, expected in expected_sample.items():
        if sample.get(key) != expected:
            raise ValueError(f"frozen sample plan mismatch: {key}")
    split = plan.get("split_contract") or {}
    expected_split = build_split_contract(
        int(split.get("window_start_ts")),
        int(split.get("window_end_ts")),
    )
    if split != expected_split:
        raise ValueError("split contract mismatch")
    universe = plan.get("universe") or {}
    candidates = list(universe.get("candidates") or [])
    if not MIN_UNIVERSE_ASSETS <= len(candidates) <= MAX_UNIVERSE_ASSETS:
        raise ValueError("invalid frozen candidate count")
    if universe.get("universe_hash") != sha256_json(candidates):
        raise ValueError("frozen universe hash mismatch")
    if any(row.get("binance_spot") is not False for row in candidates):
        raise ValueError("Binance Spot assets are forbidden")
    economics = plan.get("economics") or {}
    profile_payload = economics.get("cost_profile")
    if not isinstance(profile_payload, Mapping):
        raise ValueError("cost profile is missing")
    if economics.get("cost_profile_sha256") != sha256_json(profile_payload):
        raise ValueError("cost profile hash mismatch")
    profile = _cost_profile_from_dict(profile_payload)
    expected_profile, normal_cost, stress_cost = frozen_cost_economics(profile)
    if profile_payload != expected_profile:
        raise ValueError("cost profile mismatch")
    if economics.get("normal_cycle_cost") != normal_cost:
        raise ValueError("normal cycle cost mismatch")
    if economics.get("stress_cycle_cost") != stress_cost:
        raise ValueError("stress cycle cost mismatch")
    strategy = plan.get("strategy") or {}
    expected_entry = (
        float(stress_cost["total_bps"])
        + float(strategy.get("exit_threshold_bps"))
        + float(strategy.get("safety_margin_bps"))
    )
    if float(strategy.get("entry_threshold_bps")) != expected_entry:
        raise ValueError("entry threshold cost seal mismatch")
    if strategy.get("fixed_cooldown") is not False:
        raise ValueError("fixed cooldown is forbidden")
    gates = plan.get("acceptance_gates") or {}
    if gates.get("minimum_oos_independent_episodes") != 40:
        raise ValueError("OOS episode minimum mismatch")
    if gates.get("oos_scarcity_below_minimum_verdict") != "INSUFFICIENT_DATA":
        raise ValueError("OOS scarcity verdict mismatch")
    if gates.get("minimum_four_hour_independent_episodes") != 1:
        raise ValueError("4h robustness episode minimum mismatch")
    if gates.get("four_hour_price_only_must_be_nonnegative") is not True:
        raise ValueError("4h price-only robustness gate mismatch")
    if gates.get("four_hour_total_net_must_be_nonnegative") is not True:
        raise ValueError("4h total-net robustness gate mismatch")
    safety = plan.get("safety") or {}
    for key in ("grid_search", "retune", "paper_forward", "live_orders", "api_keys", "leverage_or_margin"):
        if safety.get(key) is not False:
            raise ValueError(f"safety flag must be false: {key}")
    provenance = plan.get("preflight_provenance")
    if provenance is not None:
        if not isinstance(provenance, Mapping):
            raise ValueError("invalid preflight provenance")
        preflight_path = Path(str(provenance.get("path") or "")).expanduser().resolve()
        if not preflight_path.is_file() or sha256_file(preflight_path) != provenance.get("file_sha256"):
            raise ValueError("preflight artifact hash mismatch")
        preflight = _read_json(preflight_path)
        if preflight.get("verdict") != PREFLIGHT_ACCEPTED:
            raise ValueError("preflight verdict changed")
        source_preflight_hash = preflight.get("preflight_hash")
        if source_preflight_hash is not None:
            expected_preflight_hash = sha256_json(
                {key: value for key, value in preflight.items() if key != "preflight_hash"}
            )
            if source_preflight_hash != expected_preflight_hash:
                raise ValueError("preflight semantic hash mismatch")
            if provenance.get("preflight_hash") != source_preflight_hash:
                raise ValueError("preflight semantic hash binding mismatch")
        source_candidates = _preflight_candidates(preflight)
        if provenance.get("candidate_hash") != sha256_json(source_candidates):
            raise ValueError("preflight candidate binding mismatch")
        source_window = preflight.get("window") or {}
        if int(source_window.get("window_start_sec")) != split["window_start_ts"]:
            raise ValueError("preflight window start mismatch")
        if int(source_window.get("window_end_sec")) != split["window_end_ts"]:
            raise ValueError("preflight window end mismatch")
    code = plan.get("code_provenance") or {}
    module_path = Path(str(code.get("module_path") or "")).expanduser().resolve()
    if not module_path.is_file() or sha256_file(module_path) != code.get("module_sha256"):
        raise ValueError("code provenance mismatch")
    if code.get("immutable_snapshot"):
        validate_basis_code_snapshot_reference(
            code.get("code_snapshot_hash"),
            code.get("code_snapshot_manifest"),
            fallback_code_path=module_path,
        )
    return {
        "plan_path": str(target) if target is not None else None,
        "plan_file_sha256": sha256_file(target) if target is not None else None,
        "plan_hash": observed_hash,
        "candidate_count": len(candidates),
        "window_start_ts": split["window_start_ts"],
        "window_end_ts": split["window_end_ts"],
    }


def _profit_factor(values: Sequence[float]) -> float:
    gains = sum(value for value in values if value > 0.0)
    losses = -sum(value for value in values if value < 0.0)
    if losses > 0.0:
        return gains / losses
    return NO_LOSS_PROFIT_FACTOR if gains > 0.0 else 0.0


def _max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _peak_concurrent_positions(trades: Sequence[TradeResult]) -> int:
    events: list[tuple[int, int]] = []
    for trade in trades:
        events.append((trade.entry_ts, 1))
        events.append((trade.exit_ts, -1))
    active = 0
    peak = 0
    for _ts, delta in sorted(events, key=lambda row: (row[0], row[1])):
        active += delta
        peak = max(peak, active)
    return peak


def _concentration(trades: Sequence[TradeResult]) -> dict[str, float]:
    positive_total = sum(max(trade.net_pnl_quote, 0.0) for trade in trades)
    if positive_total <= 0.0:
        return {"base": 1.0, "date": 1.0, "episode": 1.0, "maximum": 1.0}
    buckets: dict[str, dict[str, float]] = {"base": {}, "date": {}, "episode": {}}
    for trade in trades:
        positive = max(trade.net_pnl_quote, 0.0)
        keys = {
            "base": trade.base,
            "date": trade.signal_date,
            "episode": trade.episode_id,
        }
        for dimension, key in keys.items():
            bucket = buckets[dimension]
            bucket[key] = bucket.get(key, 0.0) + positive
    result = {
        dimension: max(bucket.values(), default=positive_total) / positive_total
        for dimension, bucket in buckets.items()
    }
    result["maximum"] = max(result.values())
    return result


def cluster_bootstrap_lower_bound(
    trades: Sequence[TradeResult],
    *,
    seed_text: str,
    samples: int = 2_000,
) -> float:
    if samples < 100:
        raise ValueError("cluster bootstrap requires at least 100 samples")
    dates = sorted({trade.signal_date for trade in trades})
    bases = sorted({trade.base for trade in trades})
    if len(dates) < 2 or len(bases) < 2:
        return -NO_LOSS_PROFIT_FACTOR
    by_cluster: dict[tuple[str, str], list[float]] = {}
    for trade in trades:
        by_cluster.setdefault((trade.signal_date, trade.base), []).append(trade.net_pnl_quote)
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(samples):
        date_draw = [dates[rng.randrange(len(dates))] for _item in dates]
        base_draw = [bases[rng.randrange(len(bases))] for _item in bases]
        values = [
            value
            for date in date_draw
            for base in base_draw
            for value in by_cluster.get((date, base), ())
        ]
        means.append(statistics.fmean(values) if values else 0.0)
    means.sort()
    index = max(0, math.ceil(0.05 * len(means)) - 1)
    return means[index]


def compute_oos_metrics(
    normal_trades: Sequence[TradeResult],
    stress_trades: Sequence[TradeResult],
    *,
    oos_start_ts: int,
    oos_end_ts: int,
    plan_hash: str,
    notional_quote_per_leg: float = DEFAULT_NOTIONAL_QUOTE_PER_LEG,
) -> dict[str, Any]:
    normal = sorted(normal_trades, key=lambda row: (row.exit_ts, row.entry_ts, row.base))
    stress_by_episode = {trade.episode_id: trade for trade in stress_trades}
    if set(stress_by_episode) != {trade.episode_id for trade in normal}:
        raise ValueError("normal and stress simulations must contain identical episodes")
    net_values = [trade.net_pnl_quote for trade in normal]
    price_values = [trade.price_only_net_pnl_quote for trade in normal]
    stress_values = [stress_by_episode[trade.episode_id].net_pnl_quote for trade in normal]
    periods = fixed_oos_subperiods(oos_start_ts, oos_end_ts)
    period_rows = []
    for period in periods:
        pnl = sum(
            trade.net_pnl_quote
            for trade in normal
            if int(period["start_ts"]) <= trade.signal_available_ts < int(period["end_ts"])
        )
        period_rows.append({**period, "net_pnl_quote": pnl, "positive": pnl > 0.0})
    directions = {"mexc_long": 0.0, "gateio_long": 0.0}
    for trade in normal:
        directions[trade.direction] = directions.get(trade.direction, 0.0) + trade.net_pnl_quote
    concentration = _concentration(normal)
    peak_positions = _peak_concurrent_positions(normal)
    collateral = max(1, peak_positions) * 2.0 * float(notional_quote_per_leg)
    drawdown = _max_drawdown(net_values)
    return {
        "independent_episode_count": len({trade.episode_id for trade in normal}),
        "unique_dates": len({trade.signal_date for trade in normal}),
        "base_count": len({trade.base for trade in normal}),
        "price_only_net_pnl_quote": sum(price_values),
        "price_only_expectancy_quote": (
            statistics.fmean(price_values) if price_values else 0.0
        ),
        "total_net_pnl_quote": sum(net_values),
        "total_expectancy_quote": statistics.fmean(net_values) if net_values else 0.0,
        "profit_factor": _profit_factor(net_values),
        "fixed_oos_subperiods": period_rows,
        "positive_fixed_subperiods": sum(row["positive"] for row in period_rows),
        "normal_net_pnl_quote": sum(net_values),
        "stress_net_pnl_quote": sum(stress_values),
        "stress_expectancy_quote": (
            statistics.fmean(stress_values) if stress_values else 0.0
        ),
        "cluster_bootstrap_lower_95_quote": cluster_bootstrap_lower_bound(
            normal,
            seed_text=f"{plan_hash}:day-base-cluster",
        ),
        "cluster_dimensions": ["utc_date", "base"],
        "direction_net_pnl_quote": directions,
        "max_concentration_share": concentration["maximum"],
        "max_concentration_share_by_dimension": {
            key: value for key, value in concentration.items() if key != "maximum"
        },
        "peak_concurrent_positions": peak_positions,
        "peak_collateral_quote": collateral,
        "max_drawdown_quote": drawdown,
        "max_drawdown_fraction": drawdown / collateral,
    }


def historical_oos_verdict(metrics: Mapping[str, Any]) -> tuple[str, list[str]]:
    if int(metrics.get("independent_episode_count") or 0) < 40:
        return "INSUFFICIENT_DATA", ["oos_independent_episodes_below_40"]
    reasons: list[str] = []
    checks = (
        (int(metrics.get("unique_dates") or 0) >= 20, "oos_dates"),
        (int(metrics.get("base_count") or 0) >= 8, "oos_assets"),
        (
            float(metrics.get("price_only_expectancy_quote") or 0.0) > 0.0,
            "price_only_expectancy",
        ),
        (
            float(metrics.get("total_expectancy_quote") or 0.0) > 0.0,
            "total_expectancy",
        ),
        (float(metrics.get("profit_factor") or 0.0) >= 1.2, "profit_factor"),
        (
            int(metrics.get("positive_fixed_subperiods") or 0) >= 4,
            "fixed_oos_subperiods",
        ),
        (
            float(metrics.get("normal_net_pnl_quote") or 0.0) >= 0.0,
            "normal_net_pnl",
        ),
        (
            float(metrics.get("stress_net_pnl_quote") or 0.0) >= 0.0,
            "stress_net_pnl",
        ),
        (
            float(metrics.get("stress_expectancy_quote") or 0.0) > 0.0,
            "stress_expectancy",
        ),
        (
            float(metrics.get("cluster_bootstrap_lower_95_quote") or 0.0) > 0.0,
            "cluster_bootstrap_lower_95",
        ),
        (
            float(metrics.get("max_concentration_share") or 1.0) <= 0.25,
            "concentration",
        ),
        (
            float(metrics.get("max_drawdown_fraction") or 1.0) <= 0.10,
            "drawdown",
        ),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    directions = metrics.get("direction_net_pnl_quote") or {}
    if float(directions.get("mexc_long") or 0.0) < 0.0:
        reasons.append("mexc_long_direction")
    if float(directions.get("gateio_long") or 0.0) < 0.0:
        reasons.append("gateio_long_direction")
    return ("REJECT", reasons) if reasons else ("ACCEPT_FOR_EXECUTION_PROBE", [])


def compute_four_hour_robustness(
    normal_trades: Sequence[TradeResult],
    stress_trades: Sequence[TradeResult],
    *,
    minimum_independent_episodes: int = 1,
) -> dict[str, Any]:
    minimum_episodes = int(minimum_independent_episodes)
    if minimum_episodes <= 0:
        raise ValueError("minimum_independent_episodes must be positive")
    normal = sorted(normal_trades, key=lambda row: (row.exit_ts, row.entry_ts, row.base))
    stress = sorted(stress_trades, key=lambda row: (row.exit_ts, row.entry_ts, row.base))
    normal_ids = [trade.episode_id for trade in normal]
    stress_ids = [trade.episode_id for trade in stress]
    if len(normal_ids) != len(set(normal_ids)) or len(stress_ids) != len(set(stress_ids)):
        raise ValueError("4h robustness simulations contain duplicate episodes")
    if set(normal_ids) != set(stress_ids):
        raise ValueError("4h normal and stress simulations must contain identical episodes")

    normal_price_only = sum(trade.price_only_net_pnl_quote for trade in normal)
    stress_price_only = sum(trade.price_only_net_pnl_quote for trade in stress)
    normal_net = sum(trade.net_pnl_quote for trade in normal)
    stress_net = sum(trade.net_pnl_quote for trade in stress)
    reasons: list[str] = []
    if len(set(normal_ids)) < minimum_episodes:
        reasons.append("four_hour_no_independent_episodes")
    if normal_price_only < 0.0:
        reasons.append("four_hour_normal_price_only_net_pnl")
    if stress_price_only < 0.0:
        reasons.append("four_hour_stress_price_only_net_pnl")
    if normal_net < 0.0:
        reasons.append("four_hour_normal_net_pnl")
    if stress_net < 0.0:
        reasons.append("four_hour_stress_net_pnl")
    return {
        "source_interval": "immutable_1h",
        "interval": "4h",
        "parameters_changed": False,
        "normal_episode_count": len(normal),
        "stress_episode_count": len(stress),
        "independent_episode_count": len(set(normal_ids)),
        "minimum_independent_episodes": minimum_episodes,
        "normal_price_only_net_pnl_quote": normal_price_only,
        "stress_price_only_net_pnl_quote": stress_price_only,
        "normal_net_pnl_quote": normal_net,
        "stress_net_pnl_quote": stress_net,
        "funding_cannot_rescue_negative_price_only_pnl": True,
        "passed": not reasons,
        "rejection_reasons": reasons,
    }


def aggregate_1h_to_4h(
    bars: Iterable[BasisBar | Mapping[str, Any]],
) -> list[BasisBar]:
    normalized = [
        row if isinstance(row, BasisBar) else BasisBar.from_dict(row) for row in bars
    ]
    by_base_and_bucket: dict[tuple[str, int], list[BasisBar]] = {}
    for bar in normalized:
        bucket = bar.ts - bar.ts % FOUR_HOUR_SEC
        by_base_and_bucket.setdefault((bar.base, bucket), []).append(bar)
    result: list[BasisBar] = []
    for (base, bucket), group in sorted(by_base_and_bucket.items()):
        ordered = sorted(group, key=lambda row: row.ts)
        expected = [bucket + index * HOUR_SEC for index in range(4)]
        if [row.ts for row in ordered] != expected:
            continue
        first, last = ordered[0], ordered[-1]
        result.append(
            BasisBar(
                ts=bucket,
                base=base,
                mexc_trade_open=first.mexc_trade_open,
                mexc_trade_close=last.mexc_trade_close,
                mexc_mark_close=last.mexc_mark_close,
                mexc_index_close=last.mexc_index_close,
                mexc_volume_quote=sum(row.mexc_volume_quote for row in ordered),
                gateio_trade_open=first.gateio_trade_open,
                gateio_trade_close=last.gateio_trade_close,
                gateio_mark_close=last.gateio_mark_close,
                gateio_index_close=last.gateio_index_close,
                gateio_volume_quote=sum(row.gateio_volume_quote for row in ordered),
            )
        )
    return result


def _simulation_for_plan(
    plan: Mapping[str, Any],
    bars: Sequence[BasisBar],
    funding_events: Sequence[FundingEvent],
    *,
    stress: bool,
    interval_sec: int,
) -> SimulationResult:
    strategy = plan["strategy"]
    economics = plan["economics"]
    cycle = economics["stress_cycle_cost" if stress else "normal_cycle_cost"]
    return simulate_basis_episodes(
        bars,
        funding_events,
        entry_threshold_bps=float(strategy["entry_threshold_bps"]),
        exit_threshold_bps=float(strategy["exit_threshold_bps"]),
        maximum_holding_hours=int(strategy["maximum_holding_hours"]),
        notional_quote_per_leg=float(economics["notional_quote_per_leg"]),
        cycle_cost_bps=float(cycle["total_bps"]),
        stress=stress,
        favorable_funding_stress_haircut=float(
            economics["favorable_funding_stress_haircut"]
        ),
        interval_sec=interval_sec,
        maximum_gap_sec=max(DEFAULT_MAX_GAP_SEC, interval_sec),
    )


def _trades_in_window(
    trades: Sequence[TradeResult],
    *,
    start_ts: int,
    end_ts: int,
) -> list[TradeResult]:
    return [
        trade
        for trade in trades
        if start_ts <= trade.signal_available_ts < end_ts and trade.exit_ts <= end_ts
    ]


def _core_result_hash(result: Mapping[str, Any]) -> str:
    return sha256_json(
        {key: value for key, value in result.items() if key != "deterministic_result_hash"}
    )


def evaluate_historical_basis_v2(
    plan: Mapping[str, Any],
    bars: Iterable[BasisBar | Mapping[str, Any]],
    funding_events: Iterable[FundingEvent | Mapping[str, Any]],
    *,
    stage: str,
    quality_surviving_bases: Iterable[str] | None = None,
) -> dict[str, Any]:
    if stage not in {"train_feasibility", "full_evaluation"}:
        raise ValueError("stage must be train_feasibility or full_evaluation")
    validation = validate_historical_basis_v2_plan(plan)
    normalized_bars = [
        row if isinstance(row, BasisBar) else BasisBar.from_dict(row) for row in bars
    ]
    normalized_events = _normalize_funding_events(funding_events)
    split = plan["split_contract"]
    train_start = int(split["train"]["start_ts"])
    train_end = int(split["train"]["end_ts"])
    train_bars = [bar for bar in normalized_bars if bar.ts < train_end]
    train_events = [event for event in normalized_events if event.settlement_ts < train_end]
    train_simulation = _simulation_for_plan(
        plan,
        train_bars,
        train_events,
        stress=False,
        interval_sec=HOUR_SEC,
    )
    train_trades = _trades_in_window(
        train_simulation.trades,
        start_ts=train_start,
        end_ts=train_end,
    )
    surviving_bases = {
        str(base).strip().upper()
        for base in (
            quality_surviving_bases
            if quality_surviving_bases is not None
            else {bar.base for bar in train_bars}
        )
    }
    train_dates = {trade.signal_date for trade in train_trades}
    train_directions = {trade.direction for trade in train_trades}
    train_reasons: list[str] = []
    if len(train_trades) < 20:
        train_reasons.append("train_independent_episodes")
    if len(train_dates) < 10:
        train_reasons.append("train_dates")
    if not {"mexc_long", "gateio_long"}.issubset(train_directions):
        train_reasons.append("train_directions")
    if len(surviving_bases) < MIN_UNIVERSE_ASSETS:
        train_reasons.append("train_quality_surviving_assets")
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "hypothesis_id": HYPOTHESIS_ID,
        "plan_hash": validation["plan_hash"],
        "stage": stage,
        "train_feasibility": {
            "independent_episode_count": len({trade.episode_id for trade in train_trades}),
            "unique_dates": len(train_dates),
            "directions": sorted(train_directions),
            "quality_surviving_asset_count": len(surviving_bases),
            "feasible": not train_reasons,
        },
        "oos_read": False,
        "verdict": "FEASIBLE_FOR_OOS" if not train_reasons else "INSUFFICIENT_DATA",
        "rejection_reasons": train_reasons,
        "next_allowed_command": (
            "fast-edge-basis-v2-evaluate --stage full_evaluation"
            if not train_reasons
            else "close-hypothesis-without-retune"
        ),
    }
    if stage == "train_feasibility" or train_reasons:
        result["deterministic_result_hash"] = _core_result_hash(result)
        return result

    oos_start = int(split["oos"]["start_ts"])
    oos_end = int(split["oos"]["end_ts"])
    normal_simulation = _simulation_for_plan(
        plan,
        normalized_bars,
        normalized_events,
        stress=False,
        interval_sec=HOUR_SEC,
    )
    stress_simulation = _simulation_for_plan(
        plan,
        normalized_bars,
        normalized_events,
        stress=True,
        interval_sec=HOUR_SEC,
    )
    normal_trades = _trades_in_window(
        normal_simulation.trades,
        start_ts=oos_start,
        end_ts=oos_end,
    )
    stress_trades = _trades_in_window(
        stress_simulation.trades,
        start_ts=oos_start,
        end_ts=oos_end,
    )
    metrics = compute_oos_metrics(
        normal_trades,
        stress_trades,
        oos_start_ts=oos_start,
        oos_end_ts=oos_end,
        plan_hash=str(validation["plan_hash"]),
        notional_quote_per_leg=float(plan["economics"]["notional_quote_per_leg"]),
    )
    verdict, reasons = historical_oos_verdict(metrics)
    robustness: dict[str, Any] | None = None
    if verdict == "ACCEPT_FOR_EXECUTION_PROBE":
        bars_4h = aggregate_1h_to_4h(normalized_bars)
        normal_4h = _trades_in_window(
            _simulation_for_plan(
                plan,
                bars_4h,
                normalized_events,
                stress=False,
                interval_sec=FOUR_HOUR_SEC,
            ).trades,
            start_ts=oos_start,
            end_ts=oos_end,
        )
        stress_4h = _trades_in_window(
            _simulation_for_plan(
                plan,
                bars_4h,
                normalized_events,
                stress=True,
                interval_sec=FOUR_HOUR_SEC,
            ).trades,
            start_ts=oos_start,
            end_ts=oos_end,
        )
        robustness = compute_four_hour_robustness(
            normal_4h,
            stress_4h,
            minimum_independent_episodes=int(
                plan["acceptance_gates"]["minimum_four_hour_independent_episodes"]
            ),
        )
        reasons.extend(robustness["rejection_reasons"])
        if reasons:
            verdict = "REJECT"
    result.update(
        {
            "oos_read": True,
            "metrics": metrics,
            "normal_trades": [trade.as_dict() for trade in normal_trades],
            "stress_trades": [trade.as_dict() for trade in stress_trades],
            "four_hour_robustness": robustness,
            "verdict": verdict,
            "rejection_reasons": reasons,
            "next_allowed_command": (
                "fast-edge-basis-v2-execution-probe-plan"
                if verdict == "ACCEPT_FOR_EXECUTION_PROBE"
                else "close-hypothesis-without-retune"
            ),
        }
    )
    result["deterministic_result_hash"] = _core_result_hash(result)
    return result


# Short aliases keep callers explicit about the versioned module while easing migration.
build_historical_basis_plan = build_historical_basis_v2_plan
validate_historical_basis_plan = validate_historical_basis_v2_plan
evaluate_historical_basis = evaluate_historical_basis_v2
historical_verdict = historical_oos_verdict


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Frozen historical basis v2 core")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--preflight", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=600)
    plan_parser.add_argument("--code-snapshot-hash")
    plan_parser.add_argument("--code-snapshot-manifest")

    validate_parser = subparsers.add_parser("validate-plan")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash")

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--expected-plan-hash")
    evaluate_parser.add_argument("--quality-report", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument(
        "--stage",
        choices=("train_feasibility", "full_evaluation"),
        required=True,
    )
    evaluate_parser.add_argument("--feasibility")
    evaluate_parser.add_argument("--max-runtime-sec", type=int, default=1_800)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        result = build_historical_basis_v2_plan_from_preflight(
            args.preflight,
            args.output,
            max_runtime_sec=args.max_runtime_sec,
            code_snapshot_hash=args.code_snapshot_hash,
            code_snapshot_manifest=args.code_snapshot_manifest,
        )
    elif args.command == "validate-plan":
        result = validate_historical_basis_v2_plan(
            args.plan,
            args.expected_plan_hash,
        )
    else:
        try:
            from historical_basis_v2_evaluator import run_hash_bound_evaluation
        except ImportError:  # pragma: no cover - package import fallback
            from .historical_basis_v2_evaluator import run_hash_bound_evaluation
        result = run_hash_bound_evaluation(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            quality_report_path=args.quality_report,
            output_path=args.output,
            stage=args.stage,
            feasibility_path=args.feasibility,
            max_runtime_sec=args.max_runtime_sec,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
