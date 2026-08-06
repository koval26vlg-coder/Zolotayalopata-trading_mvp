from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from funding import FundingClient, FundingContract, FundingSnapshot, build_funding_clients
from perp_collector import PublicPerpRestClient, build_perp_rest_clients


AVAILABILITY_SCHEMA = "pit_linear_perp_cross_venue_availability_preflight_v1"
AVAILABILITY_MODE = "pit_linear_perp_cross_venue_availability_preflight_planonly"
AVAILABILITY_DECISION = (
    "PIT_LINEAR_PERP_CURRENT_DATASET_REJECTED_FOR_EDGE_VALIDATION_MISSING_HISTORICAL_EVIDENCE"
)
PROBE_SCHEMA = "pit_linear_perp_cross_venue_forward_probe_v1"
PROBE_MODE = "pit_linear_perp_cross_venue_forward_public_probe"
PLAN_MODE = "pit_linear_perp_cross_venue_forward_public_probe_planonly"
SUPPORTED_EXCHANGES = ("mexc", "gateio")


@dataclass(frozen=True)
class ForwardProbeConfig:
    target_notional_quote: float = 100.0
    depth_limit: int = 20
    timeout_sec: int = 10
    max_index_divergence_bps: float = 100.0
    max_mark_index_divergence_bps: float = 200.0
    max_quote_age_sec: float = 10.0
    max_clock_lead_sec: float = 2.0
    max_cross_venue_skew_sec: float = 5.0
    min_provisional_identity_pairs: int = 10
    min_fully_valid_pairs: int = 8
    round_trip_fee_bps: float = 39.0
    slippage_bps: float = 10.0
    operational_buffer_bps: float = 20.0
    progress: bool = True

    @property
    def total_cost_bps(self) -> float:
        return self.round_trip_fee_bps + self.slippage_bps + self.operational_buffer_bps

    def validate(self) -> None:
        positive = {
            "target_notional_quote": self.target_notional_quote,
            "depth_limit": self.depth_limit,
            "timeout_sec": self.timeout_sec,
            "max_index_divergence_bps": self.max_index_divergence_bps,
            "max_mark_index_divergence_bps": self.max_mark_index_divergence_bps,
            "max_quote_age_sec": self.max_quote_age_sec,
            "max_cross_venue_skew_sec": self.max_cross_venue_skew_sec,
            "min_provisional_identity_pairs": self.min_provisional_identity_pairs,
            "min_fully_valid_pairs": self.min_fully_valid_pairs,
        }
        invalid = [name for name, value in positive.items() if float(value) <= 0]
        if invalid:
            raise ValueError(f"forward probe parameters must be positive: {', '.join(invalid)}")
        if self.max_clock_lead_sec < 0:
            raise ValueError("max_clock_lead_sec must be non-negative")
        if min(self.round_trip_fee_bps, self.slippage_bps, self.operational_buffer_bps) < 0:
            raise ValueError("cost assumptions must be non-negative")
        if self.min_fully_valid_pairs > self.min_provisional_identity_pairs:
            raise ValueError("min_fully_valid_pairs cannot exceed min_provisional_identity_pairs")


def run_forward_probe(
    availability_path: str | Path,
    output_path: str | Path,
    config: ForwardProbeConfig | None = None,
    *,
    funding_clients: dict[str, FundingClient] | None = None,
    rest_clients: dict[str, PublicPerpRestClient] | None = None,
    now_fn: Callable[[], float] = time.time,
) -> dict[str, Any]:
    cfg = config or ForwardProbeConfig()
    cfg.validate()
    source_path = Path(availability_path).resolve()
    destination = Path(output_path).resolve()
    availability = _load_availability(source_path)
    if destination == source_path:
        raise ValueError("probe output must not overwrite availability evidence")
    if destination.exists():
        raise FileExistsError(f"forward probe output already exists: {destination}")

    bases = _discovery_bases(availability)
    if cfg.min_provisional_identity_pairs > len(bases):
        raise ValueError("min_provisional_identity_pairs exceeds sealed discovery universe size")
    if cfg.min_fully_valid_pairs > len(bases):
        raise ValueError("min_fully_valid_pairs exceeds sealed discovery universe size")

    cycle = collect_forward_cycle(
        bases,
        cfg,
        funding_clients=funding_clients,
        rest_clients=rest_clients,
        now_fn=now_fn,
        progress_label=PROBE_MODE,
    )
    probe_started_ts = cycle["started_ts"]
    probe_finished_ts = cycle["finished_ts"]
    discovery_errors = cycle["discovery_errors"]
    pairs = cycle["pairs"]

    provisional = sum(1 for pair in pairs if pair["provisional_identity_match"])
    fully_valid = sum(1 for pair in pairs if pair["fully_valid"])
    cost_positive = sum(
        1
        for pair in pairs
        if pair["fully_valid"] and _finite(pair.get("max_net_screening_edge_bps")) and pair["max_net_screening_edge_bps"] > 0
    )
    observed_fee_cost_positive = sum(
        1
        for pair in pairs
        if pair["fully_valid"]
        and _finite(pair.get("max_net_observed_base_fee_bps"))
        and pair["max_net_observed_base_fee_bps"] > 0
    )
    if discovery_errors:
        decision = "PIT_LINEAR_PERP_FORWARD_PROBE_REJECTED_VENUE_DISCOVERY_ERROR"
        reasons = ["contract_discovery_failed_for_at_least_one_required_venue"]
    elif provisional < cfg.min_provisional_identity_pairs:
        decision = "PIT_LINEAR_PERP_FORWARD_PROBE_REJECTED_INSUFFICIENT_IDENTITY_MATCHES"
        reasons = ["provisional_contract_identity_universe_is_too_small"]
    elif fully_valid < cfg.min_fully_valid_pairs:
        decision = "PIT_LINEAR_PERP_FORWARD_PROBE_REJECTED_INSUFFICIENT_EXECUTABLE_EVIDENCE"
        reasons = ["too_few_pairs_have_complete_depth_timestamp_and_funding_evidence"]
    else:
        decision = "PIT_LINEAR_PERP_FORWARD_PROBE_ACCEPTED_READY_FOR_OOS_APPROVAL_PACKET"
        reasons = []

    report: dict[str, Any] = {
        "schema": PROBE_SCHEMA,
        "mode": PROBE_MODE,
        "decision": decision,
        "generated_at_utc": _iso_utc(probe_finished_ts),
        "research_only": True,
        "public_data_only": True,
        "network_calls": True,
        "collect_started": False,
        "one_shot_probe_only": True,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "backtest_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_ready": False,
        "source": {
            "availability_path": str(source_path),
            "availability_sha256": _sha256_file(source_path),
            "availability_decision": availability["decision"],
            "discovery_run_id": (availability.get("source") or {}).get("run_id"),
            "discovery_mask_sha256": (availability.get("source") or {}).get("mask_sha256"),
            "historical_dataset_verdict": "rejected_not_modified",
        },
        "discovery_universe": {
            "bases": bases,
            "count": len(bases),
            "sha256": _canonical_sha256({"bases": bases}),
            "selection_rule": "all discovery cost-positive bases; no outcome pruning",
        },
        "config": asdict(cfg) | {"total_cost_bps": cfg.total_cost_bps},
        "cost_model": {
            "total_cost_bps": cfg.total_cost_bps,
            "round_trip_fee_bps": cfg.round_trip_fee_bps,
            "slippage_bps": cfg.slippage_bps,
            "operational_buffer_bps": cfg.operational_buffer_bps,
            "label": "screening hurdle only; this one-shot probe is not PnL or a trade sample",
        },
        "probe_span": {
            "started_at_utc": _iso_utc(probe_started_ts),
            "finished_at_utc": _iso_utc(probe_finished_ts),
            "duration_sec": max(0.0, probe_finished_ts - probe_started_ts),
        },
        "summary": {
            "discovery_bases": len(bases),
            "provisional_identity_pairs": provisional,
            "fully_valid_pairs": fully_valid,
            "one_shot_cost_positive_pairs": cost_positive,
            "one_shot_observed_base_fee_cost_positive_pairs": observed_fee_cost_positive,
            "min_provisional_identity_pairs": cfg.min_provisional_identity_pairs,
            "min_fully_valid_pairs": cfg.min_fully_valid_pairs,
        },
        "discovery_errors": discovery_errors,
        "pairs": pairs,
        "rejection_reasons": reasons,
        "interpretation_limits": [
            "index-price parity is a provisional identity check, not a canonical underlying identifier",
            "one observation cannot establish persistence, fill probability, capacity, PnL, expectancy or OOS performance",
            "a passing probe only permits a separately approved visible forward-OOS collector",
        ],
        "next_valid_move": (
            "build_sealed_forward_oos_collector_approval_packet_planonly"
            if decision == "PIT_LINEAR_PERP_FORWARD_PROBE_ACCEPTED_READY_FOR_OOS_APPROVAL_PACKET"
            else "reject_or_rescope_linear_perp_cross_venue_branch_planonly"
        ),
        "blocked_actions": [
            "treat_probe_rows_as_trades_or_candidates",
            "reuse_discovery_window_as_oos",
            "replay_or_backtest",
            "grid_optimization",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ],
        "output_path": str(destination),
    }
    _atomic_write_json(destination, report)
    return report


def collect_forward_cycle(
    bases: list[str],
    config: ForwardProbeConfig,
    *,
    funding_clients: dict[str, FundingClient] | None = None,
    rest_clients: dict[str, PublicPerpRestClient] | None = None,
    now_fn: Callable[[], float] = time.time,
    progress_label: str = PROBE_MODE,
) -> dict[str, Any]:
    """Collect one fixed-universe public evidence cycle without writing artifacts."""
    config.validate()
    normalized_bases = sorted({str(base).strip().upper() for base in bases if str(base).strip()})
    if not normalized_bases:
        raise ValueError("forward cycle requires at least one sealed base")
    owned_clients = funding_clients is None or rest_clients is None
    funding = funding_clients or build_funding_clients(list(SUPPORTED_EXCHANGES), timeout_sec=config.timeout_sec)
    rest = rest_clients or build_perp_rest_clients(list(SUPPORTED_EXCHANGES), timeout_sec=config.timeout_sec)
    _validate_clients(funding, rest)
    if owned_clients:
        for client in [*funding.values(), *rest.values()]:
            session = getattr(client, "session", None)
            if session is not None:
                session.trust_env = False

    # MEXC exposes a batch ticker cache. Invalidate it once per evidence cycle so
    # all bases share one fresh snapshot instead of silently reusing the prior cycle.
    mexc_client = funding.get("mexc")
    if mexc_client is not None and hasattr(mexc_client, "_tickers_cache"):
        setattr(mexc_client, "_tickers_cache", None)
        setattr(mexc_client, "_tickers_cache_ts", 0.0)

    started_ts = now_fn()
    contract_maps: dict[str, dict[str, list[FundingContract]]] = {}
    discovery_errors: dict[str, str] = {}
    for exchange in SUPPORTED_EXCHANGES:
        try:
            contracts = funding[exchange].fetch_contracts()
            contract_maps[exchange] = _contracts_by_base(contracts, normalized_bases)
        except Exception as exc:  # noqa: BLE001 - a public endpoint failure is part of cycle evidence.
            contract_maps[exchange] = {}
            discovery_errors[exchange] = f"{type(exc).__name__}: {exc}"

    pairs: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="forward-cycle") as pool:
        for index, base in enumerate(normalized_bases, start=1):
            contracts = {exchange: contract_maps.get(exchange, {}).get(base, []) for exchange in SUPPORTED_EXCHANGES}
            venue_rows: dict[str, dict[str, Any]] = {}
            futures = {}
            for exchange in SUPPORTED_EXCHANGES:
                matches = contracts[exchange]
                if len(matches) != 1:
                    venue_rows[exchange] = _missing_contract_evidence(exchange, base, matches)
                    continue
                futures[exchange] = pool.submit(
                    _collect_venue_evidence,
                    matches[0],
                    funding[exchange],
                    rest[exchange],
                    config,
                    started_ts,
                    now_fn,
                )
            for exchange, future in futures.items():
                try:
                    venue_rows[exchange] = future.result()
                except Exception as exc:  # noqa: BLE001 - retain a failed venue row rather than erasing the base.
                    venue_rows[exchange] = _failed_venue_evidence(exchange, base, contracts[exchange][0], exc)

            pair = evaluate_pair_evidence(base, venue_rows.get("mexc"), venue_rows.get("gateio"), config)
            pairs.append(pair)
            if config.progress:
                print(
                    json.dumps(
                        {
                            "progress": progress_label,
                            "base": base,
                            "index": index,
                            "total": len(normalized_bases),
                            "identity": pair["provisional_identity_match"],
                            "fully_valid": pair["fully_valid"],
                            "reasons": pair["invalid_reasons"][:4],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    return {
        "started_ts": started_ts,
        "finished_ts": now_fn(),
        "discovery_errors": discovery_errors,
        "pairs": pairs,
    }


def build_forward_probe_plan(
    availability_path: str | Path,
    output_path: str | Path,
    config: ForwardProbeConfig | None = None,
) -> dict[str, Any]:
    cfg = config or ForwardProbeConfig()
    cfg.validate()
    source_path = Path(availability_path).resolve()
    availability = _load_availability(source_path)
    bases = _discovery_bases(availability)
    if cfg.min_provisional_identity_pairs > len(bases) or cfg.min_fully_valid_pairs > len(bases):
        raise ValueError("probe acceptance thresholds exceed sealed discovery universe size")
    return {
        "schema": PROBE_SCHEMA,
        "mode": PLAN_MODE,
        "decision": "PIT_LINEAR_PERP_FORWARD_PUBLIC_PROBE_PLAN_READY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "would_start": False,
        "network_calls": False,
        "collect_started": False,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "source": {
            "availability_path": str(source_path),
            "availability_sha256": _sha256_file(source_path),
        },
        "discovery_universe": {
            "bases": bases,
            "count": len(bases),
            "sha256": _canonical_sha256({"bases": bases}),
        },
        "config": asdict(cfg) | {"total_cost_bps": cfg.total_cost_bps},
        "output_path": str(Path(output_path).resolve()),
        "next_valid_move": "run_one_shot_public_probe_then_decide_forward_oos_approval_packet",
    }


def evaluate_pair_evidence(
    base: str,
    mexc: dict[str, Any] | None,
    gateio: dict[str, Any] | None,
    config: ForwardProbeConfig,
) -> dict[str, Any]:
    venues = {"mexc": mexc or {}, "gateio": gateio or {}}
    identity_reasons: list[str] = []
    execution_reasons: list[str] = []
    funding_reasons: list[str] = []
    expected_symbol = f"{base}_USDT"

    for exchange, row in venues.items():
        if row.get("error"):
            identity_reasons.append(f"{exchange}_venue_error")
            continue
        if str(row.get("base") or "").upper() != base or str(row.get("quote") or "").upper() != "USDT":
            identity_reasons.append(f"{exchange}_base_or_quote_mismatch")
        if str(row.get("symbol") or "").upper() != expected_symbol:
            identity_reasons.append(f"{exchange}_symbol_mismatch")
        if str(row.get("status") or "").lower() != "trading":
            identity_reasons.append(f"{exchange}_contract_not_trading")
        if str(row.get("contract_type") or "") != "linear_perp":
            identity_reasons.append(f"{exchange}_instrument_mismatch")
        if not _positive(row.get("contract_size")):
            identity_reasons.append(f"{exchange}_invalid_contract_size")
        index_price = _float(row.get("index_price"))
        mark_price = _float(row.get("mark_price"))
        if not _positive(index_price):
            identity_reasons.append(f"{exchange}_missing_index_price")
        if not _positive(mark_price):
            identity_reasons.append(f"{exchange}_missing_mark_price")
        elif _positive(index_price) and _symmetric_bps(mark_price, index_price) > config.max_mark_index_divergence_bps:
            identity_reasons.append(f"{exchange}_mark_index_divergence")

    mexc_index = _float(venues["mexc"].get("index_price"))
    gate_index = _float(venues["gateio"].get("index_price"))
    index_divergence_bps = _symmetric_bps(mexc_index, gate_index) if _positive(mexc_index) and _positive(gate_index) else None
    if index_divergence_bps is not None and index_divergence_bps > config.max_index_divergence_bps:
        identity_reasons.append("index_price_divergence")
    provisional_identity = not identity_reasons

    fills: dict[str, dict[str, Any]] = {}
    for exchange, row in venues.items():
        if row.get("error"):
            execution_reasons.append(f"{exchange}_venue_error")
            funding_reasons.append(f"{exchange}_venue_error")
            continue
        bid = _float(row.get("bid_price"))
        ask = _float(row.get("ask_price"))
        if not (_positive(bid) and _positive(ask) and ask >= bid):
            execution_reasons.append(f"{exchange}_invalid_bbo")
        exchange_ts = _float(row.get("exchange_ts"))
        recv_ts = _float(row.get("recv_ts"))
        if exchange_ts is None or recv_ts is None:
            execution_reasons.append(f"{exchange}_missing_depth_timestamp")
        else:
            age = recv_ts - exchange_ts
            if age > config.max_quote_age_sec:
                execution_reasons.append(f"{exchange}_stale_depth")
            if age < -config.max_clock_lead_sec:
                execution_reasons.append(f"{exchange}_exchange_clock_ahead")
        buy_fill = _depth_fill(row.get("asks") or [], config.target_notional_quote)
        sell_fill = _depth_fill(row.get("bids") or [], config.target_notional_quote)
        fills[exchange] = {"buy": buy_fill, "sell": sell_fill}
        if not buy_fill["complete"]:
            execution_reasons.append(f"{exchange}_insufficient_ask_depth")
        if not sell_fill["complete"]:
            execution_reasons.append(f"{exchange}_insufficient_bid_depth")

        if _float(row.get("funding_rate")) is None:
            funding_reasons.append(f"{exchange}_missing_funding_rate")
        if not _positive(row.get("funding_interval_sec")):
            funding_reasons.append(f"{exchange}_missing_funding_interval")
        next_funding = _float(row.get("next_funding_ts"))
        if next_funding is None or (recv_ts is not None and next_funding <= recv_ts):
            funding_reasons.append(f"{exchange}_invalid_next_funding_time")

    mexc_ts = _float(venues["mexc"].get("exchange_ts"))
    gate_ts = _float(venues["gateio"].get("exchange_ts"))
    quote_skew_sec = abs(mexc_ts - gate_ts) if mexc_ts is not None and gate_ts is not None else None
    if quote_skew_sec is not None and quote_skew_sec > config.max_cross_venue_skew_sec:
        execution_reasons.append("cross_venue_quote_skew")

    gross_edges: dict[str, float | None] = {
        "buy_mexc_sell_gateio_bps": _execution_edge_bps(
            fills.get("mexc", {}).get("buy"), fills.get("gateio", {}).get("sell")
        ),
        "buy_gateio_sell_mexc_bps": _execution_edge_bps(
            fills.get("gateio", {}).get("buy"), fills.get("mexc", {}).get("sell")
        ),
    }
    finite_edges = [value for value in gross_edges.values() if _finite(value)]
    max_gross = max(finite_edges) if finite_edges else None
    max_net = max_gross - config.total_cost_bps if max_gross is not None else None
    taker_rates = [_float(venues[exchange].get("taker_fee_rate")) for exchange in SUPPORTED_EXCHANGES]
    observed_round_trip_fee_bps = (
        2.0 * sum(max(0.0, rate) for rate in taker_rates) * 10_000.0
        if all(rate is not None for rate in taker_rates)
        else None
    )
    observed_total_cost_bps = (
        observed_round_trip_fee_bps + config.slippage_bps + config.operational_buffer_bps
        if observed_round_trip_fee_bps is not None
        else None
    )
    observed_net = (
        max_gross - observed_total_cost_bps
        if max_gross is not None and observed_total_cost_bps is not None
        else None
    )
    invalid_reasons = _unique(identity_reasons + execution_reasons + funding_reasons)
    return {
        "base": base,
        "provisional_identity_match": provisional_identity,
        "fully_valid": provisional_identity and not execution_reasons and not funding_reasons,
        "identity_reasons": _unique(identity_reasons),
        "execution_reasons": _unique(execution_reasons),
        "funding_reasons": _unique(funding_reasons),
        "invalid_reasons": invalid_reasons,
        "index_divergence_bps": index_divergence_bps,
        "quote_skew_sec": quote_skew_sec,
        "depth_fills": fills,
        "gross_execution_edges": gross_edges,
        "max_gross_execution_edge_bps": max_gross,
        "max_net_screening_edge_bps": max_net,
        "observed_round_trip_taker_fee_bps": observed_round_trip_fee_bps,
        "observed_total_cost_bps": observed_total_cost_bps,
        "max_net_observed_base_fee_bps": observed_net,
        "venues": venues,
    }


def _collect_venue_evidence(
    contract: FundingContract,
    funding_client: FundingClient,
    rest_client: PublicPerpRestClient,
    config: ForwardProbeConfig,
    metadata_snapshot_ts: float,
    now_fn: Callable[[], float],
) -> dict[str, Any]:
    request_started = now_fn()
    snapshot = funding_client.fetch_snapshot(contract.symbol)
    depth_payload = rest_client.fetch_depth(contract, config.depth_limit)
    bids, asks, exchange_ts, version = _normalized_depth(rest_client, contract, depth_payload)
    recv_ts = now_fn()
    bids = _clean_levels(bids)
    asks = _clean_levels(asks)
    bid = bids[0] if bids else [None, None]
    ask = asks[0] if asks else [None, None]
    raw = contract.raw or {}
    metadata = {
        "exchange": contract.exchange,
        "symbol": contract.symbol,
        "base": contract.base,
        "quote": contract.quote,
        "status": contract.status,
        "contract_size": _contract_size(contract),
        "settle": str(raw.get("settleCoin") or raw.get("settle") or contract.quote).upper(),
        "venue_type": raw.get("type"),
        "venue_contract_type": raw.get("contract_type"),
        "display_name": raw.get("displayNameEn") or raw.get("displayName"),
        "automatic_delivery": raw.get("automaticDelivery"),
    }
    return {
        **metadata,
        "contract_type": "linear_perp",
        "metadata_hash": _canonical_sha256(metadata),
        "metadata_snapshot_ts": metadata_snapshot_ts,
        "request_started_ts": request_started,
        "recv_ts": recv_ts,
        "exchange_ts": exchange_ts,
        "depth_version": version,
        "bid_price": bid[0],
        "bid_qty": bid[1],
        "ask_price": ask[0],
        "ask_qty": ask[1],
        "bids": bids,
        "asks": asks,
        "mark_price": snapshot.mark_price,
        "index_price": snapshot.index_price,
        "funding_rate": snapshot.funding_rate,
        "funding_interval_sec": snapshot.funding_interval_sec,
        "next_funding_ts": snapshot.next_funding_ts,
        "maker_fee_rate": snapshot.maker_fee_rate,
        "taker_fee_rate": snapshot.taker_fee_rate,
        "error": None,
    }


def _normalized_depth(
    rest_client: PublicPerpRestClient,
    contract: FundingContract,
    payload: Any,
) -> tuple[list[list[float]], list[list[float]], float | None, Any]:
    method = getattr(rest_client, "normalized_depth", None)
    if callable(method):
        return method(contract, payload)
    internal = getattr(rest_client, "_extract_book", None)
    if callable(internal):
        return internal(contract, payload)
    raise TypeError(f"rest client for {contract.exchange} cannot normalize depth")


def _depth_fill(levels: list[Any], target_notional_quote: float) -> dict[str, Any]:
    remaining = float(target_notional_quote)
    base_qty = 0.0
    quote_notional = 0.0
    levels_used = 0
    for raw in levels:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        price = _float(raw[0])
        qty = _float(raw[1])
        if not (_positive(price) and _positive(qty)):
            continue
        available_quote = price * qty
        take_quote = min(remaining, available_quote)
        take_qty = take_quote / price
        base_qty += take_qty
        quote_notional += take_quote
        remaining -= take_quote
        levels_used += 1
        if remaining <= max(1e-9, target_notional_quote * 1e-12):
            remaining = 0.0
            break
    complete = remaining <= 0.0
    return {
        "complete": complete,
        "target_quote_notional": float(target_notional_quote),
        "filled_quote_notional": quote_notional,
        "filled_base_qty": base_qty,
        "vwap": quote_notional / base_qty if base_qty > 0 else None,
        "levels_used": levels_used,
        "shortfall_quote": remaining,
    }


def _execution_edge_bps(buy_fill: dict[str, Any] | None, sell_fill: dict[str, Any] | None) -> float | None:
    if not buy_fill or not sell_fill or not buy_fill.get("complete") or not sell_fill.get("complete"):
        return None
    buy = _float(buy_fill.get("vwap"))
    sell = _float(sell_fill.get("vwap"))
    if not (_positive(buy) and _positive(sell)):
        return None
    return ((sell - buy) / buy) * 10_000.0


def _contracts_by_base(contracts: list[FundingContract], bases: list[str]) -> dict[str, list[FundingContract]]:
    allowed = set(bases)
    result = {base: [] for base in bases}
    for contract in contracts:
        base = contract.base.upper()
        if base in allowed and contract.quote.upper() == "USDT":
            result[base].append(contract)
    return result


def _contract_size(contract: FundingContract) -> float | None:
    raw = contract.raw or {}
    for field in ("contractSize", "quanto_multiplier"):
        value = _float(raw.get(field))
        if _positive(value):
            return value
    return None


def _missing_contract_evidence(exchange: str, base: str, matches: list[FundingContract]) -> dict[str, Any]:
    return {
        "exchange": exchange,
        "symbol": None,
        "base": base,
        "quote": "USDT",
        "status": None,
        "contract_type": "linear_perp",
        "error": "contract_missing" if not matches else "ambiguous_duplicate_contracts",
        "match_count": len(matches),
    }


def _failed_venue_evidence(
    exchange: str,
    base: str,
    contract: FundingContract,
    exc: BaseException,
) -> dict[str, Any]:
    return {
        "exchange": exchange,
        "symbol": contract.symbol,
        "base": base,
        "quote": contract.quote,
        "status": contract.status,
        "contract_type": "linear_perp",
        "contract_size": _contract_size(contract),
        "error": f"{type(exc).__name__}: {exc}"[:500],
    }


def _load_availability(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"availability evidence not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid availability JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("availability evidence must be a JSON object")
    if value.get("schema") != AVAILABILITY_SCHEMA or value.get("mode") != AVAILABILITY_MODE:
        raise ValueError("unsupported availability schema/mode")
    if value.get("decision") != AVAILABILITY_DECISION:
        raise ValueError("availability evidence does not carry the required rejection decision")
    if value.get("historical_retrofit_possible") is not False:
        raise ValueError("historical dataset rejection must remain fail-closed")
    return value


def _discovery_bases(availability: dict[str, Any]) -> list[str]:
    raw = (availability.get("raw_observations") or {}).get("bases") or []
    bases = sorted({str(value).strip().upper() for value in raw if str(value).strip()})
    if not bases:
        raise ValueError("availability evidence has no sealed discovery bases")
    return bases


def _validate_clients(
    funding_clients: dict[str, FundingClient],
    rest_clients: dict[str, PublicPerpRestClient],
) -> None:
    missing = [
        f"{kind}:{exchange}"
        for kind, clients in (("funding", funding_clients), ("rest", rest_clients))
        for exchange in SUPPORTED_EXCHANGES
        if exchange not in clients
    ]
    if missing:
        raise ValueError(f"missing required public clients: {', '.join(missing)}")


def _clean_levels(levels: Any) -> list[list[float]]:
    output: list[list[float]] = []
    for raw in levels or []:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        price = _float(raw[0])
        qty = _float(raw[1])
        if _positive(price) and _positive(qty):
            output.append([price, qty])
    return output


def _symmetric_bps(left: float | None, right: float | None) -> float:
    if not (_positive(left) and _positive(right)):
        return math.inf
    midpoint = (left + right) / 2.0
    return abs(left - right) / midpoint * 10_000.0


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> bool:
    number = _float(value)
    return number is not None and number > 0


def _finite(value: Any) -> bool:
    return _float(value) is not None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot public MEXC/Gate linear-perp forward evidence probe")
    parser.add_argument("--availability", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--target-notional-quote", type=float, default=100.0)
    parser.add_argument("--depth-limit", type=int, default=20)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--max-index-divergence-bps", type=float, default=100.0)
    parser.add_argument("--max-mark-index-divergence-bps", type=float, default=200.0)
    parser.add_argument("--max-quote-age-sec", type=float, default=10.0)
    parser.add_argument("--max-cross-venue-skew-sec", type=float, default=5.0)
    parser.add_argument("--min-provisional-identity-pairs", type=int, default=10)
    parser.add_argument("--min-fully-valid-pairs", type=int, default=8)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    cfg = ForwardProbeConfig(
        target_notional_quote=args.target_notional_quote,
        depth_limit=args.depth_limit,
        timeout_sec=args.timeout_sec,
        max_index_divergence_bps=args.max_index_divergence_bps,
        max_mark_index_divergence_bps=args.max_mark_index_divergence_bps,
        max_quote_age_sec=args.max_quote_age_sec,
        max_cross_venue_skew_sec=args.max_cross_venue_skew_sec,
        min_provisional_identity_pairs=args.min_provisional_identity_pairs,
        min_fully_valid_pairs=args.min_fully_valid_pairs,
        progress=not args.quiet,
    )
    if args.probe:
        report = run_forward_probe(args.availability, args.out, cfg)
    else:
        report = build_forward_probe_plan(args.availability, args.out, cfg)
        _atomic_write_json(Path(args.out).resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
