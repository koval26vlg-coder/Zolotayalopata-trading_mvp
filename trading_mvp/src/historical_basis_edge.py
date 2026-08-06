from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from costs import base_api_cost_profile, route_legs, validate_runtime_sec
from historical_basis_code_snapshot import validate_basis_code_snapshot_reference


HYPOTHESIS_ID = "cross_venue_perp_basis_convergence_history_v1"
DATA_TYPE = "HISTORICAL_PERP_MARK_INDEX_FUNDING_V1"
PLAN_SCHEMA = "trading_mvp_historical_basis_plan_v1"
RESULT_SCHEMA = "trading_mvp_historical_basis_evaluation_v1"
PLAN_MODE = "PlanOnly"
UNIVERSE_AVAILABILITY_SCHEMA = "trading_mvp_historical_basis_universe_availability_v1"
CANDLE_SEC = 300
DAY_SEC = 86_400
MIN_UNIVERSE_ASSETS = 8
MAX_UNIVERSE_ASSETS = 20
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
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    target = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    mexc_funding_rate: float | None = None
    gateio_funding_rate: float | None = None

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "BasisBar":
        values = {field: row.get(field) for field in cls.__dataclass_fields__}
        values["ts"] = int(values["ts"])
        values["base"] = str(values["base"]).strip().upper()
        for name in cls.__dataclass_fields__:
            if name in {"ts", "base", "mexc_funding_rate", "gateio_funding_rate"}:
                continue
            values[name] = float(values[name])
        for name in ("mexc_funding_rate", "gateio_funding_rate"):
            if values[name] is not None:
                values[name] = float(values[name])
        return cls(**values)

    def venue_basis_bps(self, venue: str) -> float:
        if venue == "mexc":
            mark, index = self.mexc_mark_close, self.mexc_index_close
        elif venue == "gateio":
            mark, index = self.gateio_mark_close, self.gateio_index_close
        else:
            raise ValueError(f"unsupported venue: {venue}")
        if mark <= 0 or index <= 0:
            raise ValueError("mark and index prices must be positive")
        return (mark - index) / index * 10_000.0

    def basis_spread_bps(self) -> float:
        return abs(self.venue_basis_bps("mexc") - self.venue_basis_bps("gateio"))


@dataclass(frozen=True)
class EntrySignal:
    base: str
    signal_ts: int
    entry_ts: int
    long_venue: str
    short_venue: str
    long_entry_price: float
    short_entry_price: float
    signal_spread_bps: float

    @property
    def direction(self) -> str:
        return f"{self.long_venue}_long"


@dataclass(frozen=True)
class TradeResult:
    base: str
    signal_ts: int
    entry_ts: int
    exit_ts: int
    long_venue: str
    short_venue: str
    exit_reason: str
    price_pnl_quote: float
    funding_pnl_quote: float
    cost_quote: float
    price_only_net_pnl_quote: float
    net_pnl_quote: float
    holding_sec: int

    @property
    def direction(self) -> str:
        return f"{self.long_venue}_long"

    @property
    def signal_date(self) -> str:
        return datetime.fromtimestamp(self.signal_ts, timezone.utc).date().isoformat()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _historical_costs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    profile = replace(base_api_cost_profile(), maker_fill_probability=0.0)
    legs = route_legs("cross_venue_perp_perp", profile=profile)
    normal = profile.cycle_cost(legs)
    stress = profile.cycle_cost(legs, stress=True)
    return profile.as_dict(), normal, stress


def _normalized_candidate(asset: dict[str, Any]) -> dict[str, Any] | None:
    base = str(asset.get("base") or "").strip().upper()
    canonical_id = str(asset.get("canonical_asset_id") or "").strip()
    quote = str(asset.get("quote") or "USDT").strip().upper()
    categories = {str(value).strip().lower() for value in asset.get("categories") or []}
    if not base or not canonical_id or quote != "USDT":
        return None
    if bool(asset.get("binance_spot")):
        return None
    if categories & EXCLUDED_CATEGORIES:
        return None
    if int(asset.get("common_history_days") or 0) < 220:
        return None
    if str(asset.get("mexc_status") or "").lower() != "trading":
        return None
    if str(asset.get("gateio_status") or "").lower() != "trading":
        return None
    mexc_symbol = str(asset.get("mexc_symbol") or "").strip().upper()
    gateio_symbol = str(asset.get("gateio_symbol") or "").strip().upper()
    if not mexc_symbol or not gateio_symbol:
        return None
    return {
        "canonical_asset_id": canonical_id,
        "base": base,
        "quote": "USDT",
        "mexc_symbol": mexc_symbol,
        "gateio_symbol": gateio_symbol,
        "common_history_days": int(asset["common_history_days"]),
        "liquidity_rank": int(asset.get("liquidity_rank") or 1_000_000),
        "categories": sorted(categories),
        "binance_spot": False,
    }


def _sealed_plan(plan: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "hypothesis",
        "universe",
        "strategy",
        "economics",
        "sample_plan",
        "quality_gates",
        "acceptance_gates",
        "runtime",
        "safety",
        "code_provenance",
    )
    return {key: plan[key] for key in keys}


def build_historical_basis_plan(
    assets: Iterable[dict[str, Any]],
    output_path: str | Path,
    *,
    frozen_at_utc: str | None = None,
    max_runtime_sec: int = 600,
    universe_provenance: dict[str, Any] | None = None,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
) -> dict[str, Any]:
    validate_runtime_sec(max_runtime_sec)
    snapshot = validate_basis_code_snapshot_reference(
        code_snapshot_hash,
        code_snapshot_manifest,
        fallback_code_path=__file__,
    )
    deduped: dict[str, dict[str, Any]] = {}
    base_owners: dict[str, set[str]] = {}
    mexc_symbol_owners: dict[str, set[str]] = {}
    gate_symbol_owners: dict[str, set[str]] = {}
    for raw in assets:
        candidate = _normalized_candidate(raw)
        if candidate is None:
            continue
        canonical_id = candidate["canonical_asset_id"]
        if canonical_id in deduped and deduped[canonical_id] != candidate:
            raise ValueError(f"canonical identity collision: {canonical_id}")
        deduped[canonical_id] = candidate
        base_owners.setdefault(candidate["base"], set()).add(canonical_id)
        mexc_symbol_owners.setdefault(candidate["mexc_symbol"], set()).add(canonical_id)
        gate_symbol_owners.setdefault(candidate["gateio_symbol"], set()).add(canonical_id)
    ambiguous_ids = {
        canonical_id
        for owners_by_key in (base_owners, mexc_symbol_owners, gate_symbol_owners)
        for owners in owners_by_key.values()
        if len(owners) > 1
        for canonical_id in owners
    }
    deduped = {
        canonical_id: candidate
        for canonical_id, candidate in deduped.items()
        if canonical_id not in ambiguous_ids
    }
    candidates = sorted(
        deduped.values(),
        key=lambda row: (row["liquidity_rank"], row["canonical_asset_id"]),
    )[:MAX_UNIVERSE_ASSETS]
    if len(candidates) < MIN_UNIVERSE_ASSETS:
        raise ValueError(
            f"INSUFFICIENT_EXECUTABLE_UNIVERSE: need {MIN_UNIVERSE_ASSETS}, observed {len(candidates)}"
        )

    profile, normal_cost, stress_cost = _historical_costs()
    exit_threshold_bps = 20.0
    safety_margin_bps = 20.0
    entry_threshold_bps = float(stress_cost["total_bps"]) + exit_threshold_bps + safety_margin_bps
    module_path = Path(__file__).resolve()
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "decision": "HISTORICAL_BASIS_PLAN_FROZEN_NOT_EVALUATED",
        "generated_at_utc": frozen_at_utc or datetime.now(timezone.utc).isoformat(),
        "hypothesis": {
            "id": HYPOTHESIS_ID,
            "required_data_type": DATA_TYPE,
            "thesis": "Cross-venue linear-perp mark/index basis dislocations may converge after full base-fee costs.",
            "frozen_parameters_no_grid": True,
            "retune": False,
        },
        "universe": {
            "venues": ["mexc", "gateio"],
            "market_type": "linear_perp",
            "quote": "USDT",
            "binance_role": "reference_exclusion_only",
            "candidate_limit": MAX_UNIVERSE_ASSETS,
            "primary_limit": 12,
            "reserve_limit": 8,
            "minimum_surviving_assets": MIN_UNIVERSE_ASSETS,
            "selection_uses_oos_returns": False,
            "candidates": candidates,
            "universe_hash": sha256_json(candidates),
            "source_artifact": dict(universe_provenance) if universe_provenance else None,
        },
        "strategy": {
            "signal_interval_sec": CANDLE_SEC,
            "signal_price": "closed_mark_and_index",
            "entry_price": "next_5m_trade_open",
            "entry_delay_bars": 1,
            "robustness_entry_delay_bars": 2,
            "entry_threshold_bps": entry_threshold_bps,
            "exit_threshold_bps": exit_threshold_bps,
            "safety_margin_bps": safety_margin_bps,
            "maximum_holding_hours": 72,
            "one_position_per_base": True,
            "route": "long_lower_basis_perp_short_higher_basis_perp",
            "funding_is_not_a_signal": True,
        },
        "economics": {
            "notional_quote_per_leg": 500.0,
            "gross_leverage": 1.0,
            "fully_collateralized": True,
            "maker_fill_probability": 0.0,
            "cost_profile": profile,
            "cost_profile_sha256": sha256_json(profile),
            "normal_cycle_cost": normal_cost,
            "stress_cycle_cost": stress_cost,
            "favorable_funding_stress_haircut": 0.5,
            "adverse_funding_stress_haircut": 1.0,
            "funding_cannot_rescue_negative_price_only_pnl": True,
        },
        "sample_plan": {
            "interval": "5m",
            "warmup_days": 20,
            "train_days": 100,
            "oos_days": 100,
            "total_closed_days": 220,
            "walk_forward_folds": 5,
            "walk_forward_days_per_fold": 20,
            "chronological": True,
            "oos_embargo_until_train_feasible": True,
        },
        "quality_gates": {
            "minimum_series_coverage": 0.98,
            "minimum_dual_venue_aligned_coverage": 0.95,
            "minimum_funding_coverage": 0.98,
            "maximum_gap_sec": 900,
            "open_bars_allowed": False,
            "duplicate_timestamps_allowed": False,
            "minimum_median_quote_volume": 1_000_000.0,
        },
        "acceptance_gates": {
            "minimum_train_events": 20,
            "minimum_train_dates": 10,
            "minimum_oos_events_for_accept": 40,
            "minimum_oos_events_for_insufficient": 20,
            "minimum_oos_dates": 20,
            "minimum_oos_assets": 8,
            "minimum_profit_factor": 1.2,
            "minimum_positive_folds": 4,
            "minimum_cluster_bootstrap_lower_95_quote": 0.0,
            "maximum_concentration_share": 0.25,
            "maximum_drawdown_fraction": 0.10,
            "maximum_historical_verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        },
        "runtime": {
            "plan_max_runtime_sec": int(max_runtime_sec),
            "history_collect_max_runtime_sec": 7200,
            "quality_max_runtime_sec": 1800,
            "evaluation_max_runtime_sec": 1800,
            "probe_duration_sec": 1200,
        },
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "grid_search": False,
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
        "next_allowed_command": "fast-edge-basis-history-collect",
        "output_path": str(Path(output_path).expanduser().resolve()),
    }
    plan["plan_hash"] = sha256_json(_sealed_plan(plan))
    _write_json_immutable(output_path, plan)
    return plan


def validate_historical_basis_plan(
    plan_path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    plan = _read_json(target)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != PLAN_MODE:
        raise ValueError(f"expected {PLAN_SCHEMA} {PLAN_MODE}")
    observed_hash = sha256_json(_sealed_plan(plan))
    if plan.get("plan_hash") != observed_hash:
        raise ValueError("plan hash mismatch")
    if expected_plan_hash is not None and expected_plan_hash != observed_hash:
        raise ValueError("plan does not match expected plan hash")
    hypothesis = plan.get("hypothesis") or {}
    if hypothesis.get("id") != HYPOTHESIS_ID or hypothesis.get("required_data_type") != DATA_TYPE:
        raise ValueError("unexpected historical basis hypothesis")
    sample = plan.get("sample_plan") or {}
    expected_sample = {
        "warmup_days": 20,
        "train_days": 100,
        "oos_days": 100,
        "total_closed_days": 220,
        "walk_forward_folds": 5,
        "walk_forward_days_per_fold": 20,
    }
    for key, value in expected_sample.items():
        if sample.get(key) != value:
            raise ValueError(f"frozen sample plan mismatch: {key}")
    candidates = list((plan.get("universe") or {}).get("candidates") or [])
    if not MIN_UNIVERSE_ASSETS <= len(candidates) <= MAX_UNIVERSE_ASSETS:
        raise ValueError("invalid frozen candidate count")
    if any(row.get("binance_spot") is not False for row in candidates):
        raise ValueError("Binance Spot assets are forbidden")
    universe = plan.get("universe") or {}
    if universe.get("universe_hash") != sha256_json(candidates):
        raise ValueError("frozen universe hash mismatch")
    source_artifact = universe.get("source_artifact")
    if source_artifact is not None:
        if not isinstance(source_artifact, dict):
            raise ValueError("invalid universe source artifact provenance")
        source_path = Path(str(source_artifact.get("path") or "")).expanduser().resolve()
        if not source_path.is_file() or sha256_file(source_path) != source_artifact.get("file_sha256"):
            raise ValueError("universe source artifact hash mismatch")
        if source_artifact.get("schema") == UNIVERSE_AVAILABILITY_SCHEMA:
            source_payload = _read_json(source_path)
            expected_artifact_hash = sha256_json(
                {
                    key: value
                    for key, value in source_payload.items()
                    if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
                }
            )
            if source_payload.get("artifact_hash") != expected_artifact_hash:
                raise ValueError("universe source semantic hash mismatch")
            if source_payload.get("final") is not True or source_payload.get("decision") != "READY_FOR_BASIS_PLAN":
                raise ValueError("universe source is not READY_FOR_BASIS_PLAN")
            if source_artifact.get("artifact_hash") != source_payload.get("artifact_hash"):
                raise ValueError("universe source artifact provenance mismatch")
            if source_artifact.get("universe_hash") != source_payload.get("universe_hash"):
                raise ValueError("universe source universe hash mismatch")
    economics = plan.get("economics") or {}
    maker_fill_probability = economics.get("maker_fill_probability")
    if maker_fill_probability is None or float(maker_fill_probability) != 0.0:
        raise ValueError("historical maker fill probability must be zero")
    expected_profile, normal_cost, stress_cost = _historical_costs()
    if economics.get("cost_profile") != expected_profile:
        raise ValueError("cost profile mismatch")
    if economics.get("normal_cycle_cost") != normal_cost or economics.get("stress_cycle_cost") != stress_cost:
        raise ValueError("cycle cost mismatch")
    strategy = plan.get("strategy") or {}
    expected_entry = float(stress_cost["total_bps"]) + float(strategy["exit_threshold_bps"]) + float(
        strategy["safety_margin_bps"]
    )
    if float(strategy.get("entry_threshold_bps") or 0.0) != expected_entry:
        raise ValueError("entry threshold cost seal mismatch")
    safety = plan.get("safety") or {}
    for key in ("grid_search", "live_orders", "api_keys", "leverage_or_margin"):
        if safety.get(key) is not False:
            raise ValueError(f"safety flag must be false: {key}")
    code = plan.get("code_provenance") or {}
    module_path = Path(str(code.get("module_path") or "")).expanduser().resolve()
    if not module_path.exists() or sha256_file(module_path) != code.get("module_sha256"):
        raise ValueError("code provenance mismatch")
    if code.get("immutable_snapshot"):
        validate_basis_code_snapshot_reference(
            code.get("code_snapshot_hash"),
            code.get("code_snapshot_manifest"),
            fallback_code_path=module_path,
        )
    return {
        "plan_path": str(target),
        "plan_file_sha256": sha256_file(target),
        "plan_hash": observed_hash,
        "candidate_count": len(candidates),
    }


def detect_entries(
    bars: Sequence[BasisBar],
    *,
    entry_threshold_bps: float,
    entry_delay_bars: int = 1,
) -> list[EntrySignal]:
    if entry_delay_bars < 1:
        raise ValueError("entry_delay_bars must be positive")
    ordered = sorted(bars, key=lambda row: row.ts)
    entries: list[EntrySignal] = []
    for index, signal_bar in enumerate(ordered):
        entry_index = index + entry_delay_bars
        if entry_index >= len(ordered):
            break
        entry_bar = ordered[entry_index]
        if entry_bar.ts - signal_bar.ts != CANDLE_SEC * entry_delay_bars:
            continue
        try:
            mexc_basis = signal_bar.venue_basis_bps("mexc")
            gate_basis = signal_bar.venue_basis_bps("gateio")
        except ValueError:
            continue
        spread = abs(mexc_basis - gate_basis)
        if spread < float(entry_threshold_bps):
            continue
        if mexc_basis < gate_basis:
            long_venue, short_venue = "mexc", "gateio"
            long_price, short_price = entry_bar.mexc_trade_open, entry_bar.gateio_trade_open
        else:
            long_venue, short_venue = "gateio", "mexc"
            long_price, short_price = entry_bar.gateio_trade_open, entry_bar.mexc_trade_open
        if long_price <= 0 or short_price <= 0:
            continue
        entries.append(
            EntrySignal(
                base=signal_bar.base,
                signal_ts=signal_bar.ts,
                entry_ts=entry_bar.ts,
                long_venue=long_venue,
                short_venue=short_venue,
                long_entry_price=float(long_price),
                short_entry_price=float(short_price),
                signal_spread_bps=spread,
            )
        )
    return entries


def _trade_open(bar: BasisBar, venue: str) -> float:
    return bar.mexc_trade_open if venue == "mexc" else bar.gateio_trade_open


def _funding_rate(bar: BasisBar, venue: str) -> float | None:
    return bar.mexc_funding_rate if venue == "mexc" else bar.gateio_funding_rate


def calculate_trade(
    bars: Sequence[BasisBar],
    entry: EntrySignal,
    *,
    exit_threshold_bps: float,
    maximum_holding_hours: int,
    notional_quote_per_leg: float,
    cycle_cost_bps: float,
    favorable_funding_haircut: float,
) -> TradeResult:
    if not 0.0 <= favorable_funding_haircut <= 1.0:
        raise ValueError("favorable_funding_haircut must be in [0, 1]")
    ordered = sorted(bars, key=lambda row: row.ts)
    entry_index = next((i for i, row in enumerate(ordered) if row.ts == entry.entry_ts), None)
    if entry_index is None:
        raise ValueError("entry timestamp is not present in bars")
    max_hold_sec = int(maximum_holding_hours) * 3600
    exit_bar: BasisBar | None = None
    exit_reason = "force_end"
    for index in range(entry_index, len(ordered) - 1):
        observed = ordered[index]
        if observed.ts - entry.entry_ts >= max_hold_sec:
            exit_bar = observed
            exit_reason = "max_hold"
            break
        executable = ordered[index + 1]
        if executable.ts - observed.ts != CANDLE_SEC:
            raise ValueError("price gap breaks position; cross-gap PnL is forbidden")
        if observed.basis_spread_bps() <= float(exit_threshold_bps):
            exit_bar = executable
            exit_reason = "convergence"
            break
    if exit_bar is None:
        raise ValueError("right-censored trade has no convergence or max-hold exit")
    if exit_bar.ts <= entry.entry_ts:
        raise ValueError("exit must occur after entry")

    long_exit = _trade_open(exit_bar, entry.long_venue)
    short_exit = _trade_open(exit_bar, entry.short_venue)
    if long_exit <= 0 or short_exit <= 0:
        raise ValueError("exit prices must be positive")
    long_qty = notional_quote_per_leg / entry.long_entry_price
    short_qty = notional_quote_per_leg / entry.short_entry_price
    price_pnl = (long_exit - entry.long_entry_price) * long_qty
    price_pnl += (entry.short_entry_price - short_exit) * short_qty

    funding_pnl = 0.0
    for bar in ordered:
        if not entry.entry_ts <= bar.ts < exit_bar.ts:
            continue
        long_rate = _funding_rate(bar, entry.long_venue)
        short_rate = _funding_rate(bar, entry.short_venue)
        event_pnl = 0.0
        if long_rate is not None:
            event_pnl -= notional_quote_per_leg * long_rate
        if short_rate is not None:
            event_pnl += notional_quote_per_leg * short_rate
        funding_pnl += event_pnl * favorable_funding_haircut if event_pnl > 0 else event_pnl

    cost_quote = notional_quote_per_leg * float(cycle_cost_bps) / 10_000.0
    price_only = price_pnl - cost_quote
    return TradeResult(
        base=entry.base,
        signal_ts=entry.signal_ts,
        entry_ts=entry.entry_ts,
        exit_ts=exit_bar.ts,
        long_venue=entry.long_venue,
        short_venue=entry.short_venue,
        exit_reason=exit_reason,
        price_pnl_quote=price_pnl,
        funding_pnl_quote=funding_pnl,
        cost_quote=cost_quote,
        price_only_net_pnl_quote=price_only,
        net_pnl_quote=price_only + funding_pnl,
        holding_sec=exit_bar.ts - entry.entry_ts,
    )


def _entry_dates(entries: Sequence[EntrySignal]) -> set[str]:
    return {
        datetime.fromtimestamp(row.signal_ts, timezone.utc).date().isoformat()
        for row in entries
    }


def _bounded_entries(
    bars_by_base: dict[str, list[BasisBar]],
    *,
    start_ts: int,
    end_ts: int,
    threshold_bps: float,
    delay_bars: int,
    maximum_holding_hours: int,
) -> list[EntrySignal]:
    result: list[EntrySignal] = []
    cooldown = maximum_holding_hours * 3600
    for base in sorted(bars_by_base):
        last_entry = -10**18
        entries = detect_entries(
            bars_by_base[base],
            entry_threshold_bps=threshold_bps,
            entry_delay_bars=delay_bars,
        )
        for entry in entries:
            if not start_ts <= entry.signal_ts < end_ts:
                continue
            if entry.entry_ts < last_entry + cooldown:
                continue
            result.append(entry)
            last_entry = entry.entry_ts
    return sorted(result, key=lambda row: (row.signal_ts, row.base))


def _simulate_entries(
    bars_by_base: dict[str, list[BasisBar]],
    entries: Sequence[EntrySignal],
    *,
    strategy: dict[str, Any],
    economics: dict[str, Any],
    stress: bool,
) -> list[TradeResult]:
    cycle_cost = economics["stress_cycle_cost" if stress else "normal_cycle_cost"]
    haircut = float(economics["favorable_funding_stress_haircut"] if stress else 1.0)
    trades: list[TradeResult] = []
    for entry in entries:
        try:
            trade = calculate_trade(
                bars_by_base[entry.base],
                entry,
                exit_threshold_bps=float(strategy["exit_threshold_bps"]),
                maximum_holding_hours=int(strategy["maximum_holding_hours"]),
                notional_quote_per_leg=float(economics["notional_quote_per_leg"]),
                cycle_cost_bps=float(cycle_cost["total_bps"]),
                favorable_funding_haircut=haircut,
            )
        except ValueError:
            continue
        trades.append(trade)
    return trades


def _profit_factor(values: Sequence[float]) -> float:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    if gross_loss == 0:
        return math.inf if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _concentration_shares(trades: Sequence[TradeResult]) -> dict[str, float]:
    positive_total = sum(max(row.net_pnl_quote, 0.0) for row in trades)
    if positive_total <= 0:
        return {"base": 1.0, "date": 1.0, "episode": 1.0, "maximum": 1.0}
    buckets: dict[str, dict[str, float]] = {"base": {}, "date": {}, "episode": {}}
    for row in trades:
        positive = max(row.net_pnl_quote, 0.0)
        keys = {
            "base": row.base,
            "date": row.signal_date,
            "episode": f"{row.base}:{row.signal_ts}",
        }
        for dimension, key in keys.items():
            dimension_buckets = buckets[dimension]
            dimension_buckets[key] = dimension_buckets.get(key, 0.0) + positive
    shares = {
        dimension: max(values.values(), default=positive_total) / positive_total
        for dimension, values in buckets.items()
    }
    shares["maximum"] = max(shares.values())
    return shares


def _effective_sample_size_by_date(trades: Sequence[TradeResult]) -> float:
    counts: dict[str, int] = {}
    for row in trades:
        counts[row.signal_date] = counts.get(row.signal_date, 0) + 1
    total = sum(counts.values())
    denominator = sum(count * count for count in counts.values())
    return (total * total / denominator) if denominator else 0.0


def _peak_concurrent_positions(trades: Sequence[TradeResult]) -> int:
    events: list[tuple[int, int, int]] = []
    for row in trades:
        events.append((row.entry_ts, 1, 1))
        events.append((row.exit_ts, 0, -1))
    active = 0
    peak = 0
    for _ts, _order, delta in sorted(events):
        active += delta
        peak = max(peak, active)
    return peak


def _cluster_bootstrap_lower(
    trades: Sequence[TradeResult],
    *,
    seed_text: str,
    samples: int = 1000,
) -> float:
    clusters: dict[str, float] = {}
    for row in trades:
        clusters[row.signal_date] = clusters.get(row.signal_date, 0.0) + row.net_pnl_quote
    values = list(clusters.values())
    if len(values) < 2:
        return float("-inf")
    rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16))
    means = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        means.append(statistics.fmean(draw))
    means.sort()
    return means[max(0, int(len(means) * 0.025) - 1)]


def _trade_metrics(
    normal: Sequence[TradeResult],
    stress: Sequence[TradeResult],
    *,
    oos_start_ts: int,
    plan_hash: str,
) -> dict[str, Any]:
    chronological = sorted(normal, key=lambda row: (row.exit_ts, row.signal_ts, row.base))
    net_values = [row.net_pnl_quote for row in chronological]
    price_values = [row.price_only_net_pnl_quote for row in chronological]
    dates = {row.signal_date for row in normal}
    bases = {row.base for row in normal}
    direction: dict[str, float] = {"mexc_long": 0.0, "gateio_long": 0.0}
    for row in normal:
        direction[row.direction] = direction.get(row.direction, 0.0) + row.net_pnl_quote
    folds = []
    for index in range(5):
        start = oos_start_ts + index * 20 * DAY_SEC
        end = start + 20 * DAY_SEC
        fold_net = sum(row.net_pnl_quote for row in normal if start <= row.signal_ts < end)
        folds.append({"index": index + 1, "net_pnl_quote": fold_net, "positive": fold_net > 0})
    concentration = _concentration_shares(normal)
    peak_positions = _peak_concurrent_positions(normal)
    collateral = max(1, peak_positions) * 1000.0
    return {
        "trade_count": len(normal),
        "independent_episode_count": len({(row.base, row.signal_ts) for row in normal}),
        "unique_dates": len(dates),
        "effective_sample_size_dates": _effective_sample_size_by_date(normal),
        "base_count": len(bases),
        "price_only_net_pnl_quote": sum(price_values),
        "price_only_expectancy_quote": statistics.fmean(price_values) if price_values else 0.0,
        "net_pnl_quote": sum(net_values),
        "net_expectancy_quote": statistics.fmean(net_values) if net_values else 0.0,
        "profit_factor": _profit_factor(net_values),
        "win_rate": sum(value > 0 for value in net_values) / len(net_values) if net_values else 0.0,
        "positive_folds": sum(row["positive"] for row in folds),
        "folds": folds,
        "stress_net_pnl_quote": sum(row.net_pnl_quote for row in stress),
        "cluster_bootstrap_lower_95_quote": _cluster_bootstrap_lower(normal, seed_text=plan_hash),
        "direction_net_pnl_quote": direction,
        "max_concentration_share": concentration["maximum"],
        "max_concentration_share_by_dimension": {
            key: value for key, value in concentration.items() if key != "maximum"
        },
        "peak_concurrent_positions": peak_positions,
        "secured_collateral_quote": collateral,
        "max_drawdown_quote": _max_drawdown(net_values),
        "max_drawdown_fraction": _max_drawdown(net_values) / collateral,
    }


def historical_verdict(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    trades = int(metrics.get("trade_count") or 0)
    if trades < 20:
        return "INSUFFICIENT_DATA", ["oos_events_below_minimum"]
    if trades < 40:
        return "INSUFFICIENT_DATA", ["oos_events_below_acceptance"]
    reasons: list[str] = []
    checks = (
        (int(metrics.get("unique_dates") or 0) >= 20, "oos_dates"),
        (int(metrics.get("base_count") or 0) >= 8, "oos_assets"),
        (float(metrics.get("price_only_expectancy_quote") or 0.0) > 0.0, "price_only_expectancy"),
        (float(metrics.get("net_expectancy_quote") or 0.0) > 0.0, "net_expectancy"),
        (float(metrics.get("profit_factor") or 0.0) >= 1.2, "profit_factor"),
        (int(metrics.get("positive_folds") or 0) >= 4, "walk_forward_folds"),
        (float(metrics.get("stress_net_pnl_quote") or 0.0) >= 0.0, "stress_net_pnl"),
        (
            float(metrics.get("cluster_bootstrap_lower_95_quote") or 0.0) > 0.0,
            "cluster_bootstrap_lower_95",
        ),
        (float(metrics.get("max_concentration_share") or 1.0) <= 0.25, "concentration"),
        (float(metrics.get("max_drawdown_fraction") or 1.0) <= 0.10, "drawdown"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    direction = metrics.get("direction_net_pnl_quote") or {}
    if float(direction.get("mexc_long") or 0.0) < 0.0:
        reasons.append("mexc_long_direction")
    if float(direction.get("gateio_long") or 0.0) < 0.0:
        reasons.append("gateio_long_direction")
    return ("REJECT", reasons) if reasons else ("ACCEPT_FOR_EXECUTION_PROBE", [])


def evaluate_historical_basis(
    plan: dict[str, Any],
    bars: Iterable[BasisBar | dict[str, Any]],
    *,
    stage: str,
) -> dict[str, Any]:
    if stage not in {"train_feasibility", "full_evaluation"}:
        raise ValueError("stage must be train_feasibility or full_evaluation")
    normalized = [row if isinstance(row, BasisBar) else BasisBar.from_dict(row) for row in bars]
    normalized.sort(key=lambda row: (row.ts, row.base))
    bars_by_base: dict[str, list[BasisBar]] = {}
    for row in normalized:
        bars_by_base.setdefault(row.base, []).append(row)
    sample = plan.get("sample_plan") or {}
    strategy = plan.get("strategy") or {}
    gates = plan.get("acceptance_gates") or {}
    if not normalized:
        train_entries: list[EntrySignal] = []
        data_start = 0
    else:
        data_start = min(row.ts for row in normalized)
        data_start -= data_start % DAY_SEC
        train_start = data_start + int(sample.get("warmup_days") or 20) * DAY_SEC
        train_end = train_start + int(sample.get("train_days") or 100) * DAY_SEC
        train_entries = _bounded_entries(
            bars_by_base,
            start_ts=train_start,
            end_ts=train_end,
            threshold_bps=float(strategy.get("entry_threshold_bps") or 0.0),
            delay_bars=int(strategy.get("entry_delay_bars") or 1),
            maximum_holding_hours=int(strategy.get("maximum_holding_hours") or 72),
        )
    train_dates = _entry_dates(train_entries)
    directions = {row.direction for row in train_entries}
    train_reasons: list[str] = []
    if len(train_entries) < int(gates.get("minimum_train_events") or 20):
        train_reasons.append("train_events")
    if len(train_dates) < int(gates.get("minimum_train_dates") or 10):
        train_reasons.append("train_dates")
    if not {"mexc_long", "gateio_long"}.issubset(directions):
        train_reasons.append("train_directions")
    base_result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "hypothesis_id": HYPOTHESIS_ID,
        "plan_hash": str(plan.get("plan_hash") or ""),
        "stage": stage,
        "train_feasibility": {
            "event_count": len(train_entries),
            "unique_dates": len(train_dates),
            "directions": sorted(directions),
            "feasible": not train_reasons,
        },
        "oos_read": False,
        "rejection_reasons": train_reasons,
        "verdict": "FEASIBLE_FOR_OOS" if not train_reasons else "INSUFFICIENT_DATA",
        "next_allowed_command": (
            "fast-edge-basis-evaluate -Stage full_evaluation"
            if not train_reasons
            else "close-hypothesis-without-retune"
        ),
    }
    if stage == "train_feasibility" or train_reasons:
        base_result["deterministic_result_hash"] = sha256_json(base_result)
        return base_result

    train_start = data_start + int(sample["warmup_days"]) * DAY_SEC
    oos_start = train_start + int(sample["train_days"]) * DAY_SEC
    oos_end = oos_start + int(sample["oos_days"]) * DAY_SEC
    entries = _bounded_entries(
        bars_by_base,
        start_ts=oos_start,
        end_ts=oos_end,
        threshold_bps=float(strategy["entry_threshold_bps"]),
        delay_bars=int(strategy["entry_delay_bars"]),
        maximum_holding_hours=int(strategy["maximum_holding_hours"]),
    )
    normal = _simulate_entries(
        bars_by_base,
        entries,
        strategy=strategy,
        economics=plan["economics"],
        stress=False,
    )
    stress_entries = _bounded_entries(
        bars_by_base,
        start_ts=oos_start,
        end_ts=oos_end,
        threshold_bps=float(strategy["entry_threshold_bps"]),
        delay_bars=int(strategy.get("robustness_entry_delay_bars") or 2),
        maximum_holding_hours=int(strategy["maximum_holding_hours"]),
    )
    stress = _simulate_entries(
        bars_by_base,
        stress_entries,
        strategy=strategy,
        economics=plan["economics"],
        stress=True,
    )
    metrics = _trade_metrics(normal, stress, oos_start_ts=oos_start, plan_hash=str(plan.get("plan_hash") or ""))
    verdict, reasons = historical_verdict(metrics)
    base_result.update(
        {
            "oos_read": True,
            "metrics": metrics,
            "normal_trades": [row.as_dict() for row in normal],
            "stress_trades": [row.as_dict() for row in stress],
            "verdict": verdict,
            "rejection_reasons": reasons,
            "next_allowed_command": (
                "fast-edge-basis-probe-plan"
                if verdict == "ACCEPT_FOR_EXECUTION_PROBE"
                else "close-hypothesis-without-retune"
            ),
        }
    )
    base_result["deterministic_result_hash"] = sha256_json(base_result)
    return base_result


def _load_assets_with_provenance(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    payload = _read_json(target)
    assets = payload.get("assets") or payload.get("candidates") or payload.get("rows")
    if not isinstance(assets, list):
        raise ValueError("universe artifact must contain assets/candidates/rows list")
    provenance: dict[str, Any] = {
        "path": str(target),
        "file_sha256": sha256_file(target),
        "schema": payload.get("schema"),
    }
    if payload.get("schema") == UNIVERSE_AVAILABILITY_SCHEMA:
        expected_artifact_hash = sha256_json(
            {
                key: value
                for key, value in payload.items()
                if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
            }
        )
        if payload.get("artifact_hash") != expected_artifact_hash:
            raise ValueError("universe source semantic hash mismatch")
        if payload.get("final") is not True or payload.get("decision") != "READY_FOR_BASIS_PLAN":
            raise ValueError("universe source is not READY_FOR_BASIS_PLAN")
        provenance["artifact_hash"] = payload.get("artifact_hash")
        provenance["universe_hash"] = payload.get("universe_hash")
    return [row for row in assets if isinstance(row, dict)], provenance


def _load_assets(path: str | Path) -> list[dict[str, Any]]:
    assets, _ = _load_assets_with_provenance(path)
    return assets


def _load_jsonl_bars(path: str | Path) -> list[BasisBar]:
    rows: list[BasisBar] = []
    with Path(path).expanduser().resolve().open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                rows.append(BasisBar.from_dict(payload))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid normalized basis row {path}:{line_number}: {exc}") from exc
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Historical MEXC/Gate perp basis research pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--universe", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=600)
    plan_parser.add_argument("--code-snapshot-hash")
    plan_parser.add_argument("--code-snapshot-manifest")
    validate_parser = sub.add_parser("validate-plan")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash")
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--input", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument("--stage", choices=("train_feasibility", "full_evaluation"), required=True)
    evaluate_parser.add_argument("--expected-plan-hash")
    args = parser.parse_args(argv)

    if args.command == "plan":
        assets, universe_provenance = _load_assets_with_provenance(args.universe)
        result = build_historical_basis_plan(
            assets,
            args.output,
            max_runtime_sec=args.max_runtime_sec,
            universe_provenance=universe_provenance,
            code_snapshot_hash=args.code_snapshot_hash,
            code_snapshot_manifest=args.code_snapshot_manifest,
        )
    elif args.command == "validate-plan":
        result = validate_historical_basis_plan(args.plan, args.expected_plan_hash)
    else:
        plan = _read_json(args.plan)
        validation = validate_historical_basis_plan(args.plan, args.expected_plan_hash)
        result = evaluate_historical_basis(plan, _load_jsonl_bars(args.input), stage=args.stage)
        result["plan_file_sha256"] = validation["plan_file_sha256"]
        _write_json_immutable(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
