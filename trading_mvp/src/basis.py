from __future__ import annotations

import csv
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

from exchanges import MarketPair, MarketSnapshot, PublicSpotClient, build_clients
from funding import FundingClient, FundingContract, FundingSnapshot, build_funding_clients
from multi_bot import load_universe_symbols, select_pairs


FUNDING_PAPER_REQUIRED_METRICS = (
    "total_trades",
    "win_rate",
    "expectancy_quote",
    "net_pnl_quote",
    "max_drawdown_quote",
    "funding_pnl_quote",
    "basis_pnl_quote",
    "fees_quote",
    "slippage_quote",
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _spread_bps(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    return ((ask - bid) / mid) * 1e4 if mid > 0 else None


def _current_execution_spread_risk_bps(row: dict[str, Any]) -> float:
    spot_spread = max(_row_float(row, "spot_spread_bps", 0.0), 0.0)
    perp_spread = max(_row_float(row, "perp_spread_bps", 0.0), 0.0)
    return (spot_spread + perp_spread) / 2.0


def _funding_risk_adjusted_edge_fields(
    row: dict[str, Any],
    *,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
) -> dict[str, float]:
    expected_net_carry_bps = _row_float(row, "expected_net_carry_bps", -1e9)
    basis_std_bps = max(_row_float(row, "regime_basis_std_bps", 0.0), 0.0)
    spread_risk_bps = max(_row_float(row, "regime_spread_avg_bps", _current_execution_spread_risk_bps(row)), 0.0)
    basis_penalty_bps = max(float(basis_risk_multiplier), 0.0) * basis_std_bps
    spread_penalty_bps = max(float(spread_risk_multiplier), 0.0) * spread_risk_bps
    return {
        "basis_risk_penalty_bps": basis_penalty_bps,
        "spread_risk_penalty_bps": spread_penalty_bps,
        "risk_adjusted_edge_bps": expected_net_carry_bps - basis_penalty_bps - spread_penalty_bps,
    }


@dataclass(frozen=True)
class BasisScanConfig:
    notional_quote: float = 25.0
    max_spot_spread_bps: float = 30.0
    max_perp_spread_bps: float = 30.0
    max_abs_basis_bps: float = 500.0
    min_basis_bps: float = -1e9
    min_funding_rate: float = 0.0
    min_volume_24h_quote: float = 0.0
    min_spot_top_notional_quote: float = 0.0
    spot_fee_bps: float = 10.0
    perp_fee_bps: float = 7.5
    slippage_bps: float = 1.0
    target_hold_intervals: float = 1.0
    min_expected_net_carry_bps: float = -1e9
    min_risk_adjusted_edge_bps: float = -1e9
    basis_risk_multiplier: float = 1.0
    spread_risk_multiplier: float = 1.0
    max_break_even_hours: float = 1e9


@dataclass(frozen=True)
class FundingBacktestConfig:
    notional_quote: float = 100.0
    spot_fee_bps: float = 10.0
    perp_fee_bps: float = 7.5
    slippage_bps: float = 1.0
    min_funding_rate: float = 0.0
    min_total_score: float = 0.0
    max_spot_spread_bps: float = 30.0
    max_perp_spread_bps: float = 30.0
    max_abs_basis_bps: float = 500.0
    min_basis_bps: float = -1e9
    min_expected_net_carry_bps: float = -1e9
    min_risk_adjusted_edge_bps: float = -1e9
    basis_risk_multiplier: float = 1.0
    spread_risk_multiplier: float = 1.0
    max_break_even_hours: float = 1e9
    min_funding_observations: int = 1
    min_funding_positive_ratio: float = 0.0
    min_funding_persistence_score: float = -1e9
    min_regime_observations: int = 1
    min_perp_volume_24h_quote: float = 0.0
    min_spot_top_notional_quote: float = 0.0
    max_basis_std_bps: float = 1e9
    max_avg_spot_spread_bps: float = 1e9
    max_avg_perp_spread_bps: float = 1e9


@dataclass(frozen=True)
class FundingOosConfig:
    train_fraction: float = 0.7
    min_train_rows: int = 20
    min_oos_rows: int = 20
    min_train_span_hours: float = 0.0
    min_oos_span_hours: float = 0.0


@dataclass(frozen=True)
class FundingWalkForwardConfig:
    train_rows: int = 200
    test_rows: int = 50
    step_rows: int = 50
    min_windows: int = 3
    min_accepted_windows: int = 3
    min_accepted_ratio: float = 1.0
    min_train_span_hours: float = 0.0
    min_test_span_hours: float = 0.0


@dataclass(frozen=True)
class FundingDataQualityConfig:
    min_rows: int = 1
    min_markets: int = 1
    min_completed_cycles: int = 1
    min_unique_cycles: int = 0
    min_avg_rows_per_cycle: float = 0.0
    min_min_rows_per_cycle: int = 0
    max_error_rate: float = 1.0
    max_cycle_market_duplicate_rate: float = 1.0
    required_row_fields: tuple[str, ...] = ()
    min_required_row_field_presence: float = 1.0


@dataclass(frozen=True)
class FundingRankConfig:
    min_funding_rate: float = 0.0
    min_funding_observations: int = 1
    min_funding_positive_ratio: float = 0.0
    min_funding_persistence_score: float = -1e9
    persistence_weight: float = 1.0
    max_spot_spread_bps: float = 30.0
    max_perp_spread_bps: float = 30.0
    max_abs_basis_bps: float = 500.0
    min_basis_bps: float = -1e9
    min_expected_net_carry_bps: float = -1e9
    min_risk_adjusted_edge_bps: float = -1e9
    basis_risk_multiplier: float = 1.0
    spread_risk_multiplier: float = 1.0
    max_break_even_hours: float = 1e9
    min_regime_observations: int = 1
    min_perp_volume_24h_quote: float = 0.0
    min_spot_top_notional_quote: float = 0.0
    max_basis_std_bps: float = 1e9
    max_avg_spot_spread_bps: float = 1e9
    max_avg_perp_spread_bps: float = 1e9


@dataclass(frozen=True)
class FundingAcceptanceConfig:
    min_trades: int = 20
    min_win_rate: float = 0.6
    min_expectancy_quote: float = 0.0
    min_net_pnl_quote: float = 0.0
    max_drawdown_quote: float = 5.0
    min_profit_factor: float = 1.2
    min_markets: int = 1
    max_market_trade_share: float = 1.0
    min_exchanges: int = 1
    max_exchange_trade_share: float = 1.0
    min_profitable_windows: int = 0
    max_window_pnl_share: float = 1.0


@dataclass(frozen=True)
class FundingStressConfig:
    enabled: bool = False
    adverse_basis_bps: float = 0.0
    spread_widen_bps: float = 0.0
    funding_flip_bps: float = 0.0
    min_stress_net_pnl_quote: float = 0.0
    max_stress_drawdown_quote: float = 5.0


@dataclass(frozen=True)
class FundingSensitivityConfig:
    spot_fee_bps_values: tuple[float, ...] = (0.0, 5.0, 10.0)
    perp_fee_bps_values: tuple[float, ...] = (0.0, 2.5, 7.5)
    slippage_bps_values: tuple[float, ...] = (0.0, 0.5, 1.0)
    target_hold_intervals_values: tuple[float, ...] = (1.0, 3.0, 6.0)
    max_break_even_hours_values: tuple[float, ...] = (24.0, 72.0, 168.0)
    top_n: int = 20


@dataclass(frozen=True)
class FundingPosition:
    market: str
    exchange: str
    base: str
    spot_symbol: str
    perp_symbol: str
    entry_ts: float
    spot_entry_price: float
    perp_entry_price: float
    spot_qty: float
    perp_qty: float
    notional_quote: float
    entry_fee_quote: float
    entry_slippage_quote: float
    funding_pnl_quote: float
    last_ts: float
    last_funding_rate: float
    funding_interval_sec: float


@dataclass(frozen=True)
class FundingTrade:
    market: str
    exchange: str
    base: str
    spot_symbol: str
    perp_symbol: str
    entry_ts: float
    exit_ts: float
    hold_sec: float
    notional_quote: float
    spot_entry_price: float
    spot_exit_price: float
    perp_entry_price: float
    perp_exit_price: float
    funding_pnl_quote: float
    basis_pnl_quote: float
    fees_quote: float
    slippage_quote: float
    net_pnl_quote: float
    exit_reason: str


def contract_index_by_base(contracts: list[FundingContract], quote: str = "USDT") -> dict[str, FundingContract]:
    out: dict[str, FundingContract] = {}
    for contract in contracts:
        if contract.quote.upper() != quote.upper():
            continue
        out.setdefault(contract.base.upper(), contract)
    return out


def match_contract_for_spot(pair: MarketPair, contracts: list[FundingContract]) -> FundingContract | None:
    return contract_index_by_base(contracts, pair.quote).get(pair.base.upper())


def select_pairs_with_contracts(
    exchange_pairs: list[MarketPair],
    contracts: list[FundingContract],
    universe_symbols: list[str],
    max_pairs: int,
) -> tuple[list[MarketPair], dict[str, int]]:
    pairs_by_base = {pair.base.upper(): pair for pair in exchange_pairs}
    contracts_by_base = contract_index_by_base(contracts)
    selected: list[MarketPair] = []
    seen: set[str] = set()
    stats = {"spot_available": 0, "perp_available": 0, "spot_and_perp": 0, "skipped_no_spot": 0, "skipped_no_perp": 0}
    for symbol in universe_symbols:
        base = symbol.strip().upper()
        if not base or base in seen:
            continue
        pair = pairs_by_base.get(base)
        contract = contracts_by_base.get(base)
        if pair is not None:
            stats["spot_available"] += 1
        if contract is not None:
            stats["perp_available"] += 1
        if pair is None:
            stats["skipped_no_spot"] += 1
            continue
        if contract is None:
            stats["skipped_no_perp"] += 1
            continue
        selected.append(pair)
        seen.add(base)
        stats["spot_and_perp"] += 1
        if len(selected) >= max_pairs:
            break
    return selected, stats


def funding_universe_coverage(
    spot_clients: dict[str, PublicSpotClient],
    funding_clients: dict[str, FundingClient],
    universe_symbols: list[str],
    quote: str = "USDT",
) -> dict[str, Any]:
    quote = quote.upper()
    normalized_universe: list[str] = []
    seen: set[str] = set()
    for symbol in universe_symbols:
        base = symbol.strip().upper()
        if not base or base in seen:
            continue
        normalized_universe.append(base)
        seen.add(base)

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    per_exchange: dict[str, Any] = {}
    exchange_ids = sorted(set(spot_clients) | set(funding_clients))
    for exchange_id in exchange_ids:
        spot_client = spot_clients.get(exchange_id)
        funding_client = funding_clients.get(exchange_id)
        spot_pairs: list[MarketPair] = []
        contracts: list[FundingContract] = []
        if spot_client is None:
            errors.append({"exchange": exchange_id, "stage": "spot_client", "error": "missing_spot_client"})
        else:
            try:
                spot_pairs = spot_client.fetch_pairs(quote=quote)
            except Exception as exc:  # noqa: BLE001
                errors.append({"exchange": exchange_id, "stage": "fetch_spot_pairs", "error": str(exc)[:300]})
        if funding_client is None:
            errors.append({"exchange": exchange_id, "stage": "funding_client", "error": "missing_funding_client"})
        else:
            try:
                contracts = funding_client.fetch_contracts()
            except Exception as exc:  # noqa: BLE001
                errors.append({"exchange": exchange_id, "stage": "fetch_contracts", "error": str(exc)[:300]})

        spot_by_base = {pair.base.upper(): pair for pair in spot_pairs if pair.quote.upper() == quote}
        perp_by_base = contract_index_by_base(contracts, quote)
        counts = {
            "universe_symbols": len(normalized_universe),
            "spot_available": 0,
            "perp_available": 0,
            "spot_and_perp": 0,
            "spot_only": 0,
            "perp_only": 0,
            "missing_both": 0,
        }
        matched_symbols: list[str] = []
        for universe_rank, base in enumerate(normalized_universe, start=1):
            pair = spot_by_base.get(base)
            contract = perp_by_base.get(base)
            has_spot = pair is not None
            has_perp = contract is not None
            if has_spot:
                counts["spot_available"] += 1
            if has_perp:
                counts["perp_available"] += 1
            if has_spot and has_perp:
                status = "spot_and_perp"
                counts["spot_and_perp"] += 1
                matched_symbols.append(base)
            elif has_spot:
                status = "spot_only"
                counts["spot_only"] += 1
            elif has_perp:
                status = "perp_only"
                counts["perp_only"] += 1
            else:
                status = "missing_both"
                counts["missing_both"] += 1
            rows.append(
                {
                    "exchange": exchange_id,
                    "base": base,
                    "quote": quote,
                    "universe_rank": universe_rank,
                    "status": status,
                    "has_spot": has_spot,
                    "has_perp": has_perp,
                    "spot_symbol": pair.symbol if pair else None,
                    "perp_symbol": contract.symbol if contract else None,
                }
            )
        universe_count = max(len(normalized_universe), 1)
        per_exchange[exchange_id] = {
            **counts,
            "spot_coverage_ratio": counts["spot_available"] / universe_count,
            "perp_coverage_ratio": counts["perp_available"] / universe_count,
            "spot_and_perp_coverage_ratio": counts["spot_and_perp"] / universe_count,
            "matched_symbols": matched_symbols,
        }

    symbols_with_spot_and_perp = sorted({str(row["base"]) for row in rows if row["status"] == "spot_and_perp"})
    symbols_without_spot_and_perp = [base for base in normalized_universe if base not in set(symbols_with_spot_and_perp)]
    total_both = sum(int(item["spot_and_perp"]) for item in per_exchange.values())
    best_exchange = max(
        per_exchange.items(),
        key=lambda item: (int(item[1]["spot_and_perp"]), float(item[1]["spot_and_perp_coverage_ratio"])),
        default=(None, None),
    )
    universe_count = max(len(normalized_universe), 1)
    return {
        "mode": "funding_universe_coverage",
        "ts": time.time(),
        "quote": quote,
        "summary": {
            "universe_symbols": len(normalized_universe),
            "exchanges": len(exchange_ids),
            "exchange_symbol_slots": len(normalized_universe) * len(exchange_ids),
            "spot_and_perp_slots": total_both,
            "unique_spot_and_perp_symbols": len(symbols_with_spot_and_perp),
            "unique_spot_and_perp_coverage_ratio": len(symbols_with_spot_and_perp) / universe_count,
            "unique_missing_spot_and_perp_symbols": len(symbols_without_spot_and_perp),
            "best_exchange": best_exchange[0],
            "best_exchange_spot_and_perp": int(best_exchange[1]["spot_and_perp"]) if best_exchange[1] else 0,
            "errors": len(errors),
        },
        "per_exchange": per_exchange,
        "symbols_with_spot_and_perp": symbols_with_spot_and_perp,
        "symbols_without_spot_and_perp": symbols_without_spot_and_perp,
        "rows": rows,
        "errors": errors,
    }


def write_funding_matched_universe_csv(coverage: dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in coverage.get("rows") or []:
        if row.get("status") != "spot_and_perp":
            continue
        symbol = str(row.get("base") or "").strip().upper()
        exchange = str(row.get("exchange") or "").strip().lower()
        if not symbol or not exchange:
            continue
        bucket = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "universe_rank": int(row.get("universe_rank") or 1_000_000_000),
                "exchanges": [],
                "spot_symbols": [],
                "perp_symbols": [],
            },
        )
        bucket["universe_rank"] = min(bucket["universe_rank"], int(row.get("universe_rank") or 1_000_000_000))
        bucket["exchanges"].append(exchange)
        if row.get("spot_symbol"):
            bucket["spot_symbols"].append(str(row["spot_symbol"]))
        if row.get("perp_symbol"):
            bucket["perp_symbols"].append(str(row["perp_symbol"]))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for symbol, item in sorted(
        grouped.items(),
        key=lambda kv: (-len(set(kv[1]["exchanges"])), int(kv[1]["universe_rank"]), kv[0]),
    ):
        exchanges = sorted(set(item["exchanges"]))
        rows.append(
            {
                "symbol": symbol,
                "universe_rank": int(item["universe_rank"]),
                "exchange_count": len(exchanges),
                "exchanges": ",".join(exchanges),
                "spot_symbols": ",".join(sorted(set(item["spot_symbols"]))),
                "perp_symbols": ",".join(sorted(set(item["perp_symbols"]))),
            }
        )
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["symbol", "universe_rank", "exchange_count", "exchanges", "spot_symbols", "perp_symbols"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return {
        "output": str(output),
        "symbols": len(rows),
        "exchange_symbol_slots": sum(int(row["exchange_count"]) for row in rows),
    }


def build_funding_quality_universe_rows(
    rows: list[dict[str, Any]],
    cfg: FundingRankConfig | None = None,
    top_n: int = 0,
) -> list[dict[str, Any]]:
    cfg = cfg or FundingRankConfig()
    markets_analyzed = len({_funding_market_key(row) for row in rows})
    ranked = [
        {**row, **_funding_viability_gap_fields(row, cfg)}
        for row in rank_funding_rows(rows, top_n=max(markets_analyzed, top_n or 0), cfg=cfg)
    ]
    grouped: dict[str, dict[str, Any]] = {}
    for row in ranked:
        symbol = str(row.get("base") or "").strip().upper()
        exchange = str(row.get("exchange") or "").strip().lower()
        if not symbol or not exchange:
            continue
        bucket = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "exchanges": set(),
                "spot_symbols": set(),
                "perp_symbols": set(),
                "rank_eligible": False,
                "funding_gap_pass": False,
                "best_exchange": exchange,
                "best_spot_symbol": row.get("spot_symbol"),
                "best_perp_symbol": row.get("perp_symbol"),
                "best_funding_gap_bps_per_interval_for_risk_edge": -1e9,
                "best_risk_adjusted_edge_bps": -1e9,
                "best_expected_net_carry_bps": -1e9,
                "max_regime_spot_top_min_notional_avg_quote": 0.0,
                "max_regime_perp_volume_avg_quote": 0.0,
                "min_regime_spread_avg_bps": 1e9,
                "best_funding_positive_ratio": 0.0,
                "best_rank_reasons": [],
            },
        )
        bucket["exchanges"].add(exchange)
        if row.get("spot_symbol"):
            bucket["spot_symbols"].add(str(row["spot_symbol"]))
        if row.get("perp_symbol"):
            bucket["perp_symbols"].add(str(row["perp_symbol"]))
        bucket["rank_eligible"] = bool(bucket["rank_eligible"] or row.get("rank_eligible"))
        bucket["funding_gap_pass"] = bool(bucket["funding_gap_pass"] or row.get("funding_gap_pass"))
        spot_top = _row_float(row, "regime_spot_top_min_notional_avg_quote", _row_float(row, "spot_top_min_notional_quote", 0.0))
        perp_volume = _row_float(row, "regime_perp_volume_avg_quote", _row_float(row, "perp_volume_24h_quote", 0.0))
        spread = _row_float(row, "regime_spread_avg_bps", _row_float(row, "execution_cost_bps", 1e9))
        funding_gap = _row_float(row, "funding_gap_bps_per_interval_for_risk_edge", -1e9)
        risk_edge = _row_float(row, "risk_adjusted_edge_bps", -1e9)
        expected_edge = _row_float(row, "expected_net_carry_bps", -1e9)
        if spot_top > float(bucket["max_regime_spot_top_min_notional_avg_quote"]):
            bucket["max_regime_spot_top_min_notional_avg_quote"] = spot_top
        if perp_volume > float(bucket["max_regime_perp_volume_avg_quote"]):
            bucket["max_regime_perp_volume_avg_quote"] = perp_volume
        if spread < float(bucket["min_regime_spread_avg_bps"]):
            bucket["min_regime_spread_avg_bps"] = spread
        best_key = (
            bool(row.get("rank_eligible")),
            bool(row.get("funding_gap_pass")),
            spot_top,
            perp_volume,
            funding_gap,
            risk_edge,
            expected_edge,
        )
        current_key = (
            bool(bucket["rank_eligible"]),
            bool(bucket["funding_gap_pass"]),
            float(bucket["max_regime_spot_top_min_notional_avg_quote"]),
            float(bucket["max_regime_perp_volume_avg_quote"]),
            float(bucket["best_funding_gap_bps_per_interval_for_risk_edge"]),
            float(bucket["best_risk_adjusted_edge_bps"]),
            float(bucket["best_expected_net_carry_bps"]),
        )
        if best_key >= current_key:
            bucket["best_exchange"] = exchange
            bucket["best_spot_symbol"] = row.get("spot_symbol")
            bucket["best_perp_symbol"] = row.get("perp_symbol")
            bucket["best_funding_gap_bps_per_interval_for_risk_edge"] = funding_gap
            bucket["best_risk_adjusted_edge_bps"] = risk_edge
            bucket["best_expected_net_carry_bps"] = expected_edge
            bucket["best_funding_positive_ratio"] = _row_float(row, "funding_positive_ratio", 0.0)
            bucket["best_rank_reasons"] = list(row.get("rank_reasons") or [])

    out: list[dict[str, Any]] = []
    for bucket in grouped.values():
        exchanges = sorted(bucket["exchanges"])
        spot_top = float(bucket["max_regime_spot_top_min_notional_avg_quote"])
        perp_volume = float(bucket["max_regime_perp_volume_avg_quote"])
        spread = float(bucket["min_regime_spread_avg_bps"])
        if spread >= 1e9:
            spread = 0.0
        exchange_count = len(exchanges)
        out.append(
            {
                "symbol": bucket["symbol"],
                "exchange_count": exchange_count,
                "exchanges": ",".join(exchanges),
                "best_exchange": bucket["best_exchange"],
                "best_spot_symbol": bucket["best_spot_symbol"],
                "best_perp_symbol": bucket["best_perp_symbol"],
                "rank_eligible": bool(bucket["rank_eligible"]),
                "funding_gap_pass": bool(bucket["funding_gap_pass"]),
                "max_regime_spot_top_min_notional_avg_quote": spot_top,
                "max_regime_perp_volume_avg_quote": perp_volume,
                "min_regime_spread_avg_bps": spread,
                "best_funding_gap_bps_per_interval_for_risk_edge": float(bucket["best_funding_gap_bps_per_interval_for_risk_edge"]),
                "best_risk_adjusted_edge_bps": float(bucket["best_risk_adjusted_edge_bps"]),
                "best_expected_net_carry_bps": float(bucket["best_expected_net_carry_bps"]),
                "best_funding_positive_ratio": float(bucket["best_funding_positive_ratio"]),
                "best_rank_reasons": ";".join(str(reason) for reason in bucket["best_rank_reasons"]),
                "spot_symbols": ",".join(sorted(bucket["spot_symbols"])),
                "perp_symbols": ",".join(sorted(bucket["perp_symbols"])),
            }
        )
    out.sort(
        key=lambda row: (
            bool(row["rank_eligible"]),
            bool(row["funding_gap_pass"]),
            int(row["exchange_count"]),
            float(row["max_regime_spot_top_min_notional_avg_quote"]),
            float(row["max_regime_perp_volume_avg_quote"]),
            float(row["best_funding_gap_bps_per_interval_for_risk_edge"]),
            -float(row["min_regime_spread_avg_bps"]),
            str(row["symbol"]),
        ),
        reverse=True,
    )
    for idx, row in enumerate(out, start=1):
        row["quality_rank"] = idx
    return out[:top_n] if top_n and top_n > 0 else out


def write_funding_quality_universe_csv(
    rows: list[dict[str, Any]],
    output_path: str | Path,
    cfg: FundingRankConfig | None = None,
    top_n: int = 0,
) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    quality_rows = build_funding_quality_universe_rows(rows, cfg=cfg, top_n=top_n)
    fieldnames = [
        "symbol",
        "quality_rank",
        "exchange_count",
        "exchanges",
        "best_exchange",
        "best_spot_symbol",
        "best_perp_symbol",
        "rank_eligible",
        "funding_gap_pass",
        "max_regime_spot_top_min_notional_avg_quote",
        "max_regime_perp_volume_avg_quote",
        "min_regime_spread_avg_bps",
        "best_funding_gap_bps_per_interval_for_risk_edge",
        "best_risk_adjusted_edge_bps",
        "best_expected_net_carry_bps",
        "best_funding_positive_ratio",
        "best_rank_reasons",
        "spot_symbols",
        "perp_symbols",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(quality_rows)
    return {
        "output": str(output),
        "symbols": len(quality_rows),
        "rank_eligible": sum(1 for row in quality_rows if row.get("rank_eligible")),
        "funding_gap_pass": sum(1 for row in quality_rows if row.get("funding_gap_pass")),
        "top_symbols": [row["symbol"] for row in quality_rows[: min(10, len(quality_rows))]],
    }


def write_funding_quality_universe_file(
    input_path: str | Path,
    output_path: str | Path,
    cfg: FundingRankConfig | None = None,
    top_n: int = 0,
) -> dict[str, Any]:
    return write_funding_quality_universe_csv(load_funding_rows(input_path), output_path, cfg=cfg, top_n=top_n)


def opportunity_from_snapshots(
    spot: MarketSnapshot,
    funding: FundingSnapshot,
    cfg: BasisScanConfig,
) -> dict[str, Any] | None:
    spot_mid = (spot.bid + spot.ask) / 2.0 if spot.bid > 0 and spot.ask > 0 else None
    perp_mark = funding.mark_price
    if spot_mid is None or perp_mark is None or perp_mark <= 0:
        return None
    perp_spread_bps = _spread_bps(funding.perp_bid, funding.perp_ask)
    spot_spread_bps = spot.spread_bps
    basis_bps = ((perp_mark - spot_mid) / spot_mid) * 1e4
    funding_rate = funding.funding_rate or 0.0
    volume_quote = funding.volume_24h_quote or 0.0
    spot_bid_notional_quote = max(spot.bid, 0.0) * max(spot.bid_qty, 0.0)
    spot_ask_notional_quote = max(spot.ask, 0.0) * max(spot.ask_qty, 0.0)
    spot_top_min_notional_quote = min(spot_bid_notional_quote, spot_ask_notional_quote)
    carry_score = funding_rate * 1e4
    round_trip_cost_bps = _round_trip_cost_bps(cfg.spot_fee_bps, cfg.perp_fee_bps, cfg.slippage_bps)
    target_hold_intervals = max(float(cfg.target_hold_intervals), 0.0)
    expected_gross_carry_bps = carry_score * target_hold_intervals
    expected_net_carry_bps = expected_gross_carry_bps - round_trip_cost_bps
    break_even_funding_intervals = (
        round_trip_cost_bps / carry_score
        if carry_score > 0
        else None
    )
    break_even_hours = (
        break_even_funding_intervals * float(funding.funding_interval_sec or 0) / 3600.0
        if break_even_funding_intervals is not None and funding.funding_interval_sec
        else None
    )
    liquidity_score = min(10.0, math.log10(max(volume_quote, 1.0)) * 1.5)
    execution_cost_bps = (spot_spread_bps / 2.0) + ((perp_spread_bps or 1_000.0) / 2.0)
    execution_score = -execution_cost_bps
    risk_score = -abs(basis_bps) * 0.05
    total_score = carry_score + liquidity_score + execution_score + risk_score
    risk_fields = _funding_risk_adjusted_edge_fields(
        {
            "expected_net_carry_bps": expected_net_carry_bps,
            "spot_spread_bps": spot_spread_bps,
            "perp_spread_bps": perp_spread_bps,
        },
        basis_risk_multiplier=cfg.basis_risk_multiplier,
        spread_risk_multiplier=cfg.spread_risk_multiplier,
    )
    reasons: list[str] = []
    if funding_rate <= cfg.min_funding_rate:
        reasons.append("funding_below_min")
    if expected_net_carry_bps < cfg.min_expected_net_carry_bps:
        reasons.append("expected_edge_below_min")
    if risk_fields["risk_adjusted_edge_bps"] < cfg.min_risk_adjusted_edge_bps:
        reasons.append("risk_adjusted_edge_below_min")
    if cfg.max_break_even_hours < 1e9 and (break_even_hours is None or break_even_hours > cfg.max_break_even_hours):
        reasons.append("break_even_horizon_too_long")
    if spot_spread_bps > cfg.max_spot_spread_bps:
        reasons.append("spot_spread_wide")
    if perp_spread_bps is None or perp_spread_bps > cfg.max_perp_spread_bps:
        reasons.append("perp_spread_wide")
    if abs(basis_bps) > cfg.max_abs_basis_bps:
        reasons.append("basis_too_wide")
    if basis_bps < cfg.min_basis_bps:
        reasons.append("basis_below_min")
    if volume_quote < cfg.min_volume_24h_quote:
        reasons.append("perp_volume_low")
    if spot_top_min_notional_quote < cfg.min_spot_top_notional_quote:
        reasons.append("spot_top_liquidity_low")
    return {
        "ts": max(spot.ts, funding.ts),
        "exchange": spot.exchange,
        "base": funding.base,
        "quote": funding.quote,
        "spot_symbol": spot.symbol,
        "perp_symbol": funding.symbol,
        "funding_rate": funding_rate,
        "next_funding_ts": funding.next_funding_ts,
        "funding_interval_sec": funding.funding_interval_sec,
        "spot_bid": spot.bid,
        "spot_ask": spot.ask,
        "spot_bid_qty": spot.bid_qty,
        "spot_ask_qty": spot.ask_qty,
        "spot_mid": spot_mid,
        "spot_bid_notional_quote": spot_bid_notional_quote,
        "spot_ask_notional_quote": spot_ask_notional_quote,
        "spot_top_min_notional_quote": spot_top_min_notional_quote,
        "perp_bid": funding.perp_bid,
        "perp_ask": funding.perp_ask,
        "perp_mark": funding.mark_price,
        "perp_index": funding.index_price,
        "spot_spread_bps": spot_spread_bps,
        "perp_spread_bps": perp_spread_bps,
        "basis_bps": basis_bps,
        "perp_volume_24h_quote": volume_quote,
        "perp_open_interest": funding.open_interest,
        "carry_score": carry_score,
        "funding_bps_per_interval": carry_score,
        "target_hold_intervals": target_hold_intervals,
        "expected_gross_carry_bps": expected_gross_carry_bps,
        "round_trip_cost_bps": round_trip_cost_bps,
        "expected_net_carry_bps": expected_net_carry_bps,
        "execution_cost_bps": execution_cost_bps,
        **risk_fields,
        "break_even_funding_intervals": break_even_funding_intervals,
        "break_even_hours": break_even_hours,
        "liquidity_score": liquidity_score,
        "execution_score": execution_score,
        "risk_score": risk_score,
        "total_score": total_score,
        "eligible": not reasons,
        "reasons": reasons,
    }


def scan_basis_opportunities(
    spot_clients: dict[str, PublicSpotClient],
    funding_clients: dict[str, FundingClient],
    pairs_by_exchange: dict[str, list[MarketPair]],
    depth_limit: int,
    trades_limit: int,
    cfg: BasisScanConfig,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for exchange_id, pairs in pairs_by_exchange.items():
        spot_client = spot_clients.get(exchange_id)
        funding_client = funding_clients.get(exchange_id)
        if spot_client is None or funding_client is None:
            continue
        try:
            contracts = funding_client.fetch_contracts()
        except Exception as exc:  # noqa: BLE001
            errors.append({"exchange": exchange_id, "stage": "fetch_contracts", "error": str(exc)[:300]})
            continue
        for pair in pairs:
            contract = match_contract_for_spot(pair, contracts)
            if contract is None:
                errors.append({"exchange": exchange_id, "symbol": pair.symbol, "stage": "match_contract", "error": "no_perp_contract"})
                continue
            try:
                spot = spot_client.fetch_snapshot(pair, depth_limit=depth_limit, trades_limit=trades_limit)
                funding = funding_client.fetch_snapshot(contract.symbol)
                row = opportunity_from_snapshots(spot, funding, cfg)
                if row is not None:
                    rows.append(row)
            except Exception as exc:  # noqa: BLE001
                errors.append({"exchange": exchange_id, "symbol": pair.symbol, "stage": "scan_pair", "error": str(exc)[:300]})
    rows.sort(key=lambda item: item["total_score"], reverse=True)
    return {
        "mode": "funding_basis_scan",
        "ts": time.time(),
        "config": cfg.__dict__,
        "rows": rows,
        "summary": {
            "markets": len(rows),
            "eligible": sum(1 for row in rows if row["eligible"]),
            "errors": len(errors),
        },
        "errors": errors,
    }


def run_funding_scan(
    exchange_ids: list[str],
    universe_csv: Path,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    timeout_sec: int,
    depth_limit: int,
    trades_limit: int,
    cfg: BasisScanConfig,
) -> dict[str, Any]:
    spot_clients = build_clients(exchange_ids, timeout_sec=timeout_sec)
    funding_clients = build_funding_clients(exchange_ids, timeout_sec=timeout_sec)
    universe_symbols = load_universe_symbols(universe_csv, max_symbols=max_symbols)
    pairs_by_exchange: dict[str, list[MarketPair]] = {}
    discovery: dict[str, Any] = {}
    for exchange_id, client in spot_clients.items():
        try:
            pairs = client.fetch_pairs(quote=quote)
            funding_client = funding_clients.get(exchange_id)
            if funding_client is None:
                raise ValueError(f"missing funding client for {exchange_id}")
            contracts = funding_client.fetch_contracts()
            selected, selection_stats = select_pairs_with_contracts(
                pairs,
                contracts,
                universe_symbols,
                max_pairs=max_pairs_per_exchange,
            )
            pairs_by_exchange[exchange_id] = selected
            discovery[exchange_id] = {
                "available_pairs": len(pairs),
                "available_contracts": len(contracts),
                "selected_pairs": len(selected),
                "selection": selection_stats,
                "symbols": [pair.symbol for pair in selected],
            }
        except Exception as exc:  # noqa: BLE001
            pairs_by_exchange[exchange_id] = []
            discovery[exchange_id] = {"available_pairs": 0, "available_contracts": 0, "selected_pairs": 0, "symbols": [], "error": str(exc)[:300]}
    payload = scan_basis_opportunities(
        spot_clients=spot_clients,
        funding_clients=funding_clients,
        pairs_by_exchange=pairs_by_exchange,
        depth_limit=depth_limit,
        trades_limit=trades_limit,
        cfg=cfg,
    )
    payload["universe_csv"] = str(universe_csv)
    payload["discovery"] = discovery
    return payload


def _latest_universe_csv(universe_dir: Path) -> Path:
    files = list(universe_dir.glob("no_binance_focus_*.csv"))
    if not files:
        raise FileNotFoundError(f"В {universe_dir} нет no_binance_focus_*.csv")
    return max(files, key=lambda p: p.stat().st_mtime)


def run_funding_scan_file(
    funding_dir: str | Path,
    universe_dir: str | Path,
    universe_path: str | None,
    exchange_ids: list[str],
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    timeout_sec: int,
    depth_limit: int,
    trades_limit: int,
    cfg: BasisScanConfig,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    universe_csv = Path(universe_path) if universe_path else _latest_universe_csv(Path(universe_dir))
    output = Path(output_path) if output_path else default_funding_scan_path(funding_dir)
    payload = run_funding_scan(
        exchange_ids=exchange_ids,
        universe_csv=universe_csv,
        quote=quote,
        max_symbols=max_symbols,
        max_pairs_per_exchange=max_pairs_per_exchange,
        timeout_sec=timeout_sec,
        depth_limit=depth_limit,
        trades_limit=trades_limit,
        cfg=cfg,
    )
    payload["output"] = str(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_funding_coverage(
    exchange_ids: list[str],
    universe_csv: Path,
    quote: str,
    max_symbols: int,
    timeout_sec: int,
) -> dict[str, Any]:
    spot_clients = build_clients(exchange_ids, timeout_sec=timeout_sec)
    funding_clients = build_funding_clients(exchange_ids, timeout_sec=timeout_sec)
    universe_symbols = load_universe_symbols(universe_csv, max_symbols=max_symbols)
    payload = funding_universe_coverage(
        spot_clients=spot_clients,
        funding_clients=funding_clients,
        universe_symbols=universe_symbols,
        quote=quote,
    )
    payload["universe_csv"] = str(universe_csv)
    payload["exchange_ids"] = exchange_ids
    payload["max_symbols"] = max_symbols
    return payload


def run_funding_coverage_file(
    funding_dir: str | Path,
    universe_dir: str | Path,
    universe_path: str | None,
    exchange_ids: list[str],
    quote: str,
    max_symbols: int,
    timeout_sec: int,
    output_path: str | Path | None = None,
    matched_universe_output_path: str | Path | None = None,
) -> dict[str, Any]:
    universe_csv = Path(universe_path) if universe_path else _latest_universe_csv(Path(universe_dir))
    output = Path(output_path) if output_path else default_funding_coverage_path(funding_dir)
    payload = run_funding_coverage(
        exchange_ids=exchange_ids,
        universe_csv=universe_csv,
        quote=quote,
        max_symbols=max_symbols,
        timeout_sec=timeout_sec,
    )
    payload["output"] = str(output)
    if matched_universe_output_path:
        matched_summary = write_funding_matched_universe_csv(payload, matched_universe_output_path)
        payload["matched_universe_output"] = matched_summary["output"]
        payload["matched_universe_summary"] = matched_summary
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def collect_funding_file(
    output_path: str | Path,
    cycles: int,
    poll_interval_sec: float,
    manifest_path: str | Path | None = None,
    resume: bool = False,
    **scan_kwargs: Any,
) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = Path(manifest_path) if manifest_path else output.with_suffix(".manifest.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    total_rows = 0
    total_errors = 0
    cycle_summaries: list[dict[str, Any]] = []
    if resume:
        existing_manifest = _load_funding_manifest(manifest)
        if existing_manifest:
            cycle_summaries = list(existing_manifest.get("cycle_summaries") or [])
            completed_cycles = int(existing_manifest.get("completed_cycles") or len(cycle_summaries))
            if completed_cycles > len(cycle_summaries):
                cycle_summaries.extend(
                    {"cycle": cycle + 1, "resumed_placeholder": True}
                    for cycle in range(len(cycle_summaries), completed_cycles)
                )
            total_rows = int(existing_manifest.get("rows") or 0)
            total_errors = int(existing_manifest.get("errors") or 0)
            started = time.time() - float(existing_manifest.get("duration_sec") or 0.0)
            if bool(existing_manifest.get("final")) and completed_cycles >= cycles:
                return {
                    "ok": True,
                    "output": str(output),
                    "manifest": str(manifest),
                    "cycles": cycles,
                    "rows": total_rows,
                    "errors": total_errors,
                    "duration_sec": time.time() - started,
                    "resumed": True,
                    "already_final": True,
                }
    with output.open("a", encoding="utf-8") as fh:
        for cycle in range(len(cycle_summaries), cycles):
            cycle_started = time.time()
            payload = run_funding_scan(**scan_kwargs)
            cycle_number = cycle + 1
            for row in payload["rows"]:
                row = dict(row)
                row["cycle"] = cycle_number
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                total_rows += 1
            fh.flush()
            errors = list(payload.get("errors", []))
            total_errors += len(errors)
            cycle_summaries.append(_funding_cycle_summary(cycle_number, payload, cycle_started))
            _write_funding_collect_manifest(
                manifest,
                output,
                cycles,
                started,
                total_rows,
                total_errors,
                cycle_summaries,
                final=False,
            )
            if cycle + 1 < cycles:
                time.sleep(poll_interval_sec)
    _write_funding_collect_manifest(
        manifest,
        output,
        cycles,
        started,
        total_rows,
        total_errors,
        cycle_summaries,
        final=True,
    )
    return {
        "ok": True,
        "output": str(output),
        "manifest": str(manifest),
        "cycles": cycles,
        "rows": total_rows,
        "errors": total_errors,
        "duration_sec": time.time() - started,
        "resumed": resume,
    }


def funding_collect_status(
    output_path: str | Path,
    manifest_path: str | Path | None = None,
    stale_after_sec: float = 900.0,
    now_ts: float | None = None,
    data_quality_cfg: FundingDataQualityConfig | None = None,
) -> dict[str, Any]:
    output = Path(output_path)
    manifest = Path(manifest_path) if manifest_path else output.with_suffix(".manifest.json")
    now = time.time() if now_ts is None else now_ts
    output_exists = output.exists()
    manifest_payload = _load_funding_manifest(manifest)
    line_count = _count_jsonl_lines(output) if output_exists else 0
    last_write_ts = output.stat().st_mtime if output_exists else None
    last_write_age_sec = (now - last_write_ts) if last_write_ts is not None else None
    manifest_rows = int(manifest_payload.get("rows") or 0) if manifest_payload else None
    cycles = int(manifest_payload.get("cycles") or 0) if manifest_payload else None
    expected_cycles = cycles
    completed_cycles = int(manifest_payload.get("completed_cycles") or 0) if manifest_payload else None
    final = bool(manifest_payload.get("final")) if manifest_payload else False
    cycle_interval_estimate_sec = _funding_cycle_interval_estimate(manifest_payload)
    line_count_matches_manifest = manifest_rows is not None and line_count == manifest_rows
    stale = (
        output_exists
        and not final
        and last_write_age_sec is not None
        and last_write_age_sec > stale_after_sec
    )
    if not output_exists:
        status = "missing_output"
    elif not manifest_payload:
        status = "missing_manifest"
    elif final and line_count_matches_manifest:
        status = "final"
    elif stale:
        status = "stale"
    else:
        status = "running_or_waiting"
    remaining_cycles = max(0, cycles - completed_cycles) if cycles is not None and completed_cycles is not None else None
    progress_pct = (completed_cycles / cycles * 100.0) if cycles else None
    last_cycle_ts = _last_funding_cycle_ts(manifest_payload)
    estimated_next_cycle_ts = (
        last_cycle_ts + cycle_interval_estimate_sec
        if last_cycle_ts is not None and cycle_interval_estimate_sec is not None and not final
        else None
    )
    estimated_next_cycle_in_sec = (
        estimated_next_cycle_ts - now
        if estimated_next_cycle_ts is not None
        else None
    )
    eta_sec = (
        remaining_cycles * cycle_interval_estimate_sec
        if remaining_cycles is not None and cycle_interval_estimate_sec is not None
        else None
    )
    data_quality: dict[str, Any] | None = None
    data_quality_error: str | None = None
    if data_quality_cfg is not None and output_exists and manifest_payload:
        try:
            data_quality = evaluate_funding_data_quality(load_funding_rows(output), manifest_payload, data_quality_cfg)
        except Exception as exc:  # pragma: no cover - defensive status path
            data_quality_error = str(exc)
    readiness_reasons: list[str] = []
    if status != "final":
        readiness_reasons.append("status_not_final")
    if not line_count_matches_manifest:
        readiness_reasons.append("line_count_mismatch")
    if data_quality_error is not None:
        readiness_reasons.append("data_quality_error")
    if data_quality is not None and not data_quality.get("accepted"):
        readiness_reasons.extend(f"data_quality:{reason}" for reason in data_quality.get("reasons", []))
    readiness = {
        "accepted": not readiness_reasons,
        "reasons": readiness_reasons,
        "final_required_passed": status == "final",
        "line_count_required_passed": line_count_matches_manifest,
        "data_quality_required_passed": data_quality.get("accepted") if data_quality is not None else None,
        "data_quality_error": data_quality_error,
    }
    return {
        "mode": "funding_collect_status",
        "status": status,
        "ready_for_postprocess": readiness["accepted"],
        "readiness": readiness,
        "output": str(output),
        "manifest": str(manifest),
        "output_exists": output_exists,
        "manifest_exists": manifest_payload is not None,
        "final": final,
        "cycles": cycles,
        "expected_cycles": expected_cycles,
        "completed_cycles": completed_cycles,
        "remaining_cycles": remaining_cycles,
        "progress_pct": progress_pct,
        "cycle_interval_estimate_sec": cycle_interval_estimate_sec,
        "estimated_next_cycle_ts": estimated_next_cycle_ts,
        "estimated_next_cycle_in_sec": estimated_next_cycle_in_sec,
        "eta_sec": eta_sec,
        "manifest_rows": manifest_rows,
        "line_count": line_count,
        "line_count_matches_manifest": line_count_matches_manifest,
        "errors": int(manifest_payload.get("errors") or 0) if manifest_payload else None,
        "last_write_ts": last_write_ts,
        "last_write_age_sec": last_write_age_sec,
        "stale_after_sec": stale_after_sec,
        "data_quality": data_quality,
    }


def load_funding_rows(path: str | Path) -> list[dict[str, Any]]:
    src = Path(path)
    if src.suffix.lower() == ".json":
        payload = json.loads(src.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "rows" in payload:
            return list(payload["rows"])
        if isinstance(payload, list):
            return payload
        raise ValueError(f"JSON не содержит rows: {src}")
    rows: list[dict[str, Any]] = []
    with src.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _funding_rank_filter_reasons(row: dict[str, Any], cfg: FundingRankConfig) -> list[str]:
    reasons: list[str] = []
    if "eligible" in row and not bool(row.get("eligible")):
        reasons.append("source_not_eligible")
        for reason in row.get("reasons") or []:
            reasons.append(f"source:{reason}")
    if _row_float(row, "funding_rate", 0.0) <= cfg.min_funding_rate:
        reasons.append("funding_below_min")
    if _row_float(row, "spot_spread_bps", 1e9) > cfg.max_spot_spread_bps:
        reasons.append("spot_spread_wide")
    if _row_float(row, "perp_spread_bps", 1e9) > cfg.max_perp_spread_bps:
        reasons.append("perp_spread_wide")
    if abs(_row_float(row, "basis_bps", 0.0)) > cfg.max_abs_basis_bps:
        reasons.append("basis_too_wide")
    if _row_float(row, "basis_bps", -1e9) < cfg.min_basis_bps:
        reasons.append("basis_below_min")
    if _row_float(row, "expected_net_carry_bps", -1e9) < cfg.min_expected_net_carry_bps:
        reasons.append("expected_edge_below_min")
    if _row_float(row, "risk_adjusted_edge_bps", -1e9) < cfg.min_risk_adjusted_edge_bps:
        reasons.append("risk_adjusted_edge_below_min")
    if not _break_even_hours_within(row, cfg.max_break_even_hours):
        reasons.append("break_even_horizon_too_long")
    if int(row.get("regime_observations") or 0) < cfg.min_regime_observations:
        reasons.append("regime_observations_below_min")
    if _row_float(row, "perp_volume_24h_quote", 0.0) < cfg.min_perp_volume_24h_quote:
        reasons.append("perp_volume_low")
    if _row_float(row, "regime_perp_volume_avg_quote", 0.0) < cfg.min_perp_volume_24h_quote:
        reasons.append("perp_volume_regime_low")
    if _row_float(row, "spot_top_min_notional_quote", 0.0) < cfg.min_spot_top_notional_quote:
        reasons.append("spot_top_liquidity_low")
    if _row_float(row, "regime_spot_top_min_notional_avg_quote", 0.0) < cfg.min_spot_top_notional_quote:
        reasons.append("spot_top_liquidity_regime_low")
    if _row_float(row, "regime_basis_std_bps", 1e9) > cfg.max_basis_std_bps:
        reasons.append("basis_regime_unstable")
    if _row_float(row, "regime_spot_spread_avg_bps", 1e9) > cfg.max_avg_spot_spread_bps:
        reasons.append("spot_spread_regime_wide")
    if _row_float(row, "regime_perp_spread_avg_bps", 1e9) > cfg.max_avg_perp_spread_bps:
        reasons.append("perp_spread_regime_wide")
    return reasons


_FUNDING_ECONOMIC_REASONS = {"expected_edge_below_min", "risk_adjusted_edge_below_min", "break_even_horizon_too_long"}
_FUNDING_LIQUIDITY_REASONS = {"spot_top_liquidity_low", "spot_top_liquidity_regime_low"}
_FUNDING_REGIME_REASONS = {
    "basis_regime_unstable",
    "spot_spread_regime_wide",
    "perp_spread_regime_wide",
    "perp_volume_low",
    "perp_volume_regime_low",
    "regime_observations_below_min",
}


def reprice_funding_rows_for_costs(
    rows: list[dict[str, Any]],
    *,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    target_hold_intervals: float,
    min_expected_net_carry_bps: float = -1e9,
    min_risk_adjusted_edge_bps: float = -1e9,
    basis_risk_multiplier: float = 1.0,
    spread_risk_multiplier: float = 1.0,
    max_break_even_hours: float = 1e9,
) -> list[dict[str, Any]]:
    repriced: list[dict[str, Any]] = []
    round_trip_cost_bps = _round_trip_cost_bps(spot_fee_bps, perp_fee_bps, slippage_bps)
    hold_intervals = max(float(target_hold_intervals), 0.0)
    for row in rows:
        updated = dict(row)
        funding_bps = _row_float(updated, "funding_bps_per_interval", _row_float(updated, "funding_rate", 0.0) * 1e4)
        interval_sec = _row_float(updated, "funding_interval_sec", 0.0)
        expected_gross_carry_bps = funding_bps * hold_intervals
        expected_net_carry_bps = expected_gross_carry_bps - round_trip_cost_bps
        break_even_intervals = (round_trip_cost_bps / funding_bps) if funding_bps > 0.0 else None
        break_even_hours = (
            break_even_intervals * interval_sec / 3600.0
            if break_even_intervals is not None and interval_sec > 0.0
            else None
        )
        updated.update(
            {
                "target_hold_intervals": hold_intervals,
                "round_trip_cost_bps": round_trip_cost_bps,
                "expected_gross_carry_bps": expected_gross_carry_bps,
                "expected_net_carry_bps": expected_net_carry_bps,
                "break_even_funding_intervals": break_even_intervals,
                "break_even_hours": break_even_hours,
            }
        )
        updated.update(
            _funding_risk_adjusted_edge_fields(
                updated,
                basis_risk_multiplier=basis_risk_multiplier,
                spread_risk_multiplier=spread_risk_multiplier,
            )
        )
        reasons = [reason for reason in (updated.get("reasons") or []) if reason not in _FUNDING_ECONOMIC_REASONS]
        if expected_net_carry_bps < min_expected_net_carry_bps:
            reasons.append("expected_edge_below_min")
        if _row_float(updated, "risk_adjusted_edge_bps", -1e9) < min_risk_adjusted_edge_bps:
            reasons.append("risk_adjusted_edge_below_min")
        if max_break_even_hours < 1e9 and (break_even_hours is None or break_even_hours > max_break_even_hours):
            reasons.append("break_even_horizon_too_long")
        updated["reasons"] = reasons
        updated["eligible"] = not reasons
        repriced.append(updated)
    return repriced


def rank_funding_rows(rows: list[dict[str, Any]], top_n: int = 20, cfg: FundingRankConfig | None = None) -> list[dict[str, Any]]:
    cfg = cfg or FundingRankConfig()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _funding_market_key(row)
        grouped[key].append(row)
        if key not in latest or float(row.get("ts") or 0) >= float(latest[key].get("ts") or 0):
            latest[key] = row
    enriched: list[dict[str, Any]] = []
    for key, row in latest.items():
        ranked_row = dict(row)
        ranked_row.update(_funding_persistence_metrics(grouped[key], cfg))
        ranked_row.update(_funding_regime_metrics(grouped[key]))
        ranked_row.update(
            _funding_risk_adjusted_edge_fields(
                ranked_row,
                basis_risk_multiplier=cfg.basis_risk_multiplier,
                spread_risk_multiplier=cfg.spread_risk_multiplier,
            )
        )
        rank_reasons = _funding_rank_filter_reasons(ranked_row, cfg)
        ranked_row["rank_reasons"] = rank_reasons
        ranked_row["rank_eligible"] = bool(ranked_row.get("persistence_eligible")) and not rank_reasons
        total_score = _row_float(ranked_row, "total_score", -1e9)
        persistence_score = _row_float(ranked_row, "funding_persistence_score", 0.0)
        ranked_row["persistence_adjusted_total_score"] = total_score + (cfg.persistence_weight * persistence_score)
        enriched.append(ranked_row)
    ranked = sorted(
        enriched,
        key=lambda item: (
            bool(item.get("rank_eligible")),
            bool(item.get("persistence_eligible")),
            _row_float(item, "persistence_adjusted_total_score", -1e9),
            _row_float(item, "total_score", -1e9),
        ),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for rank, row in enumerate(ranked[:top_n], start=1):
        ranked_row = dict(row)
        ranked_row["rank"] = rank
        out.append(ranked_row)
    return out


def rank_funding_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    top_n: int = 20,
    cfg: FundingRankConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or FundingRankConfig()
    rows = load_funding_rows(input_path)
    ranked = rank_funding_rows(rows, top_n=top_n, cfg=cfg)
    markets_analyzed = len({_funding_market_key(row) for row in rows})
    payload = {
        "mode": "funding_rank",
        "input": str(input_path),
        "top_n": top_n,
        "config": cfg.__dict__,
        "rows": ranked,
        "summary": {
            "input_rows": len(rows),
            "markets_analyzed": markets_analyzed,
            "ranked_rows": len(ranked),
            "rank_eligible": sum(1 for row in ranked if row.get("rank_eligible")),
            "persistence_eligible": sum(1 for row in ranked if row.get("persistence_eligible")),
        },
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    q = min(max(float(q), 0.0), 1.0)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return ordered[lower]
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _field_distribution(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [
        value
        for value in (_as_float(row.get(field)) for row in rows)
        if value is not None
    ]
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p25": _percentile(values, 0.25),
        "p50": _percentile(values, 0.50),
        "p75": _percentile(values, 0.75),
        "p90": _percentile(values, 0.90),
        "max": max(values) if values else None,
        "avg": _avg(values),
    }


def _funding_viability_gap_fields(row: dict[str, Any], cfg: FundingRankConfig) -> dict[str, Any]:
    target_hold_intervals = max(_row_float(row, "target_hold_intervals", 1.0), 0.0)
    funding_bps = _row_float(
        row,
        "funding_bps_per_interval",
        _row_float(row, "funding_avg_bps", _row_float(row, "funding_rate", 0.0) * 1e4),
    )
    interval_sec = _row_float(row, "funding_interval_sec", 0.0)
    round_trip_cost_bps = max(_row_float(row, "round_trip_cost_bps", 0.0), 0.0)
    basis_penalty_bps = max(_row_float(row, "basis_risk_penalty_bps", 0.0), 0.0)
    spread_penalty_bps = max(_row_float(row, "spread_risk_penalty_bps", 0.0), 0.0)
    required_edge_bps = max(float(cfg.min_risk_adjusted_edge_bps), 0.0)
    required_total_carry_bps = round_trip_cost_bps + basis_penalty_bps + spread_penalty_bps + required_edge_bps
    required_funding_bps = (
        required_total_carry_bps / target_hold_intervals
        if target_hold_intervals > 0.0
        else None
    )
    funding_gap_bps = (
        funding_bps - required_funding_bps
        if required_funding_bps is not None
        else None
    )
    required_hold_intervals = (
        required_total_carry_bps / funding_bps
        if funding_bps > 0.0
        else None
    )
    required_hold_hours = (
        required_hold_intervals * interval_sec / 3600.0
        if required_hold_intervals is not None and interval_sec > 0.0
        else None
    )
    target_hold_hours = (
        target_hold_intervals * interval_sec / 3600.0
        if interval_sec > 0.0
        else None
    )
    return {
        "funding_bps_per_interval": funding_bps,
        "required_total_carry_bps_for_risk_edge": required_total_carry_bps,
        "required_funding_bps_per_interval_for_risk_edge": required_funding_bps,
        "funding_gap_bps_per_interval_for_risk_edge": funding_gap_bps,
        "required_hold_intervals_for_risk_edge": required_hold_intervals,
        "required_hold_hours_for_risk_edge": required_hold_hours,
        "target_hold_hours": target_hold_hours,
        "funding_gap_pass": funding_gap_bps is not None and funding_gap_bps >= 0.0,
    }


def _funding_gate_pass_counts(rows: list[dict[str, Any]], cfg: FundingRankConfig) -> dict[str, int]:
    return {
        "source_eligible": sum(1 for row in rows if bool(row.get("eligible", True))),
        "persistence_eligible": sum(1 for row in rows if bool(row.get("persistence_eligible"))),
        "expected_edge_pass": sum(
            1 for row in rows if _row_float(row, "expected_net_carry_bps", -1e9) >= cfg.min_expected_net_carry_bps
        ),
        "risk_adjusted_edge_pass": sum(
            1 for row in rows if _row_float(row, "risk_adjusted_edge_bps", -1e9) >= cfg.min_risk_adjusted_edge_bps
        ),
        "spot_top_liquidity_pass": sum(
            1 for row in rows if _row_float(row, "regime_spot_top_min_notional_avg_quote", 0.0) >= cfg.min_spot_top_notional_quote
        ),
        "basis_floor_pass": sum(1 for row in rows if _row_float(row, "basis_bps", -1e9) >= cfg.min_basis_bps),
        "break_even_pass": sum(1 for row in rows if _break_even_hours_within(row, cfg.max_break_even_hours)),
        "funding_gap_pass": sum(1 for row in rows if row.get("funding_gap_pass") is True),
        "rank_eligible": sum(1 for row in rows if bool(row.get("rank_eligible"))),
    }


def funding_gate_report(rows: list[dict[str, Any]], top_n: int = 20, cfg: FundingRankConfig | None = None) -> dict[str, Any]:
    cfg = cfg or FundingRankConfig()
    markets_analyzed = len({_funding_market_key(row) for row in rows})
    ranked = [
        {**row, **_funding_viability_gap_fields(row, cfg)}
        for row in rank_funding_rows(rows, top_n=max(markets_analyzed, top_n), cfg=cfg)
    ]
    reason_counts = Counter(reason for row in ranked for reason in (row.get("rank_reasons") or []))
    source_reason_counts = Counter(reason for row in ranked for reason in (row.get("reasons") or []))
    persistence_reason_counts = Counter(reason for row in ranked for reason in (row.get("persistence_reasons") or []))
    exchange_counts: dict[str, dict[str, int]] = {}
    for row in ranked:
        exchange = str(row.get("exchange") or "unknown")
        bucket = exchange_counts.setdefault(exchange, {"markets": 0, "rank_eligible": 0, "persistence_eligible": 0})
        bucket["markets"] += 1
        if row.get("rank_eligible"):
            bucket["rank_eligible"] += 1
        if row.get("persistence_eligible"):
            bucket["persistence_eligible"] += 1
    distribution_fields = (
        "funding_avg_bps",
        "funding_min_bps",
        "expected_net_carry_bps",
        "risk_adjusted_edge_bps",
        "basis_risk_penalty_bps",
        "spread_risk_penalty_bps",
        "required_total_carry_bps_for_risk_edge",
        "required_funding_bps_per_interval_for_risk_edge",
        "funding_gap_bps_per_interval_for_risk_edge",
        "required_hold_intervals_for_risk_edge",
        "required_hold_hours_for_risk_edge",
        "target_hold_hours",
        "break_even_hours",
        "regime_basis_std_bps",
        "regime_spread_avg_bps",
        "regime_spot_top_min_notional_avg_quote",
        "regime_perp_volume_avg_quote",
    )
    top_fields = (
        "exchange",
        "base",
        "spot_symbol",
        "perp_symbol",
        "rank",
        "rank_eligible",
        "rank_reasons",
        "expected_net_carry_bps",
        "risk_adjusted_edge_bps",
        "basis_risk_penalty_bps",
        "spread_risk_penalty_bps",
        "required_total_carry_bps_for_risk_edge",
        "required_funding_bps_per_interval_for_risk_edge",
        "funding_gap_bps_per_interval_for_risk_edge",
        "required_hold_intervals_for_risk_edge",
        "required_hold_hours_for_risk_edge",
        "target_hold_hours",
        "funding_gap_pass",
        "funding_avg_bps",
        "funding_positive_ratio",
        "break_even_hours",
        "regime_spot_top_min_notional_avg_quote",
        "regime_basis_std_bps",
        "regime_spread_avg_bps",
    )

    def compact(row: dict[str, Any]) -> dict[str, Any]:
        return {field: row.get(field) for field in top_fields if field in row}

    return {
        "mode": "funding_gate_report",
        "config": cfg.__dict__,
        "summary": {
            "input_rows": len(rows),
            "markets_analyzed": markets_analyzed,
            "ranked_markets": len(ranked),
            "rank_eligible": sum(1 for row in ranked if row.get("rank_eligible")),
            "persistence_eligible": sum(1 for row in ranked if row.get("persistence_eligible")),
            "reason_counts": dict(reason_counts.most_common()),
            "source_reason_counts": dict(source_reason_counts.most_common()),
            "persistence_reason_counts": dict(persistence_reason_counts.most_common()),
            "pass_counts": _funding_gate_pass_counts(ranked, cfg),
            "best_funding_gap_bps_per_interval_for_risk_edge": max(
                (
                    value
                    for value in (
                        _as_float(row.get("funding_gap_bps_per_interval_for_risk_edge"))
                        for row in ranked
                    )
                    if value is not None
                ),
                default=None,
            ),
            "exchange_counts": exchange_counts,
        },
        "distributions": {field: _field_distribution(ranked, field) for field in distribution_fields},
        "top_ranked": [compact(row) for row in ranked[:top_n]],
        "top_by_risk_adjusted_edge": [
            compact(row)
            for row in sorted(ranked, key=lambda item: _row_float(item, "risk_adjusted_edge_bps", -1e9), reverse=True)[:top_n]
        ],
        "top_by_expected_net_carry": [
            compact(row)
            for row in sorted(ranked, key=lambda item: _row_float(item, "expected_net_carry_bps", -1e9), reverse=True)[:top_n]
        ],
        "top_by_funding_gap": [
            compact(row)
            for row in sorted(
                ranked,
                key=lambda item: _row_float(item, "funding_gap_bps_per_interval_for_risk_edge", -1e9),
                reverse=True,
            )[:top_n]
        ],
    }


def funding_gate_report_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    top_n: int = 20,
    cfg: FundingRankConfig | None = None,
) -> dict[str, Any]:
    rows = load_funding_rows(input_path)
    payload = funding_gate_report(rows, top_n=top_n, cfg=cfg)
    payload["input"] = str(input_path)
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def _funding_regime_report_row(market_rows: list[dict[str, Any]], cfg: FundingRankConfig) -> dict[str, Any]:
    ordered = sorted(market_rows, key=lambda row: _row_float(row, "ts", 0.0))
    latest = dict(ordered[-1]) if ordered else {}
    enriched = dict(latest)
    enriched.update(_funding_persistence_metrics(ordered, cfg))
    enriched.update(_funding_regime_metrics(ordered))
    enriched.update(
        _funding_risk_adjusted_edge_fields(
            enriched,
            basis_risk_multiplier=cfg.basis_risk_multiplier,
            spread_risk_multiplier=cfg.spread_risk_multiplier,
        )
    )
    reasons = _funding_rank_filter_reasons(enriched, cfg)
    source_reasons = [reason for reason in reasons if reason == "source_not_eligible" or reason.startswith("source:")]
    persistence_reasons = list(enriched.get("persistence_reasons") or [])
    regime_reasons = [reason for reason in reasons if reason in _FUNDING_REGIME_REASONS]
    liquidity_reasons = [reason for reason in reasons if reason in _FUNDING_LIQUIDITY_REASONS]
    economic_reasons = [reason for reason in reasons if reason in _FUNDING_ECONOMIC_REASONS]
    return {
        "market": _funding_market_key(enriched),
        "exchange": enriched.get("exchange"),
        "base": enriched.get("base"),
        "spot_symbol": enriched.get("spot_symbol"),
        "perp_symbol": enriched.get("perp_symbol"),
        "observations": len(ordered),
        "first_ts": _row_float(ordered[0], "ts", 0.0) if ordered else None,
        "last_ts": _row_float(ordered[-1], "ts", 0.0) if ordered else None,
        "latest_funding_rate": enriched.get("funding_rate"),
        "latest_basis_bps": enriched.get("basis_bps"),
        "latest_expected_net_carry_bps": enriched.get("expected_net_carry_bps"),
        "risk_adjusted_edge_bps": enriched.get("risk_adjusted_edge_bps"),
        "funding_positive_ratio": enriched.get("funding_positive_ratio"),
        "funding_persistence_score": enriched.get("funding_persistence_score"),
        "regime_observations": enriched.get("regime_observations"),
        "regime_perp_volume_avg_quote": enriched.get("regime_perp_volume_avg_quote"),
        "regime_spot_top_min_notional_avg_quote": enriched.get("regime_spot_top_min_notional_avg_quote"),
        "regime_basis_avg_bps": enriched.get("regime_basis_avg_bps"),
        "regime_basis_std_bps": enriched.get("regime_basis_std_bps"),
        "regime_spot_spread_avg_bps": enriched.get("regime_spot_spread_avg_bps"),
        "regime_perp_spread_avg_bps": enriched.get("regime_perp_spread_avg_bps"),
        "eligible": not reasons,
        "source_pass": not source_reasons,
        "persistence_pass": not persistence_reasons,
        "regime_pass": not regime_reasons,
        "liquidity_pass": not liquidity_reasons,
        "economics_pass": not economic_reasons,
        "reasons": reasons,
        "source_reasons": source_reasons,
        "persistence_reasons": persistence_reasons,
        "regime_reasons": regime_reasons,
        "liquidity_reasons": liquidity_reasons,
        "economic_reasons": economic_reasons,
    }


def funding_regime_report(
    rows: list[dict[str, Any]],
    top_n: int = 20,
    cfg: FundingRankConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or FundingRankConfig()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_funding_market_key(row)].append(row)
    markets = [_funding_regime_report_row(group, cfg) for group in grouped.values()]
    reason_counts = Counter(reason for row in markets for reason in row["reasons"])
    sorted_markets = sorted(
        markets,
        key=lambda row: (
            bool(row.get("eligible")),
            bool(row.get("regime_pass")),
            bool(row.get("liquidity_pass")),
            bool(row.get("persistence_pass")),
            _row_float(row, "risk_adjusted_edge_bps", -1e9),
            int(row.get("observations") or 0),
        ),
        reverse=True,
    )
    return {
        "mode": "funding_regime_report",
        "config": cfg.__dict__,
        "summary": {
            "input_rows": len(rows),
            "markets": len(markets),
            "eligible_markets": sum(1 for row in markets if row["eligible"]),
            "source_pass": sum(1 for row in markets if row["source_pass"]),
            "persistence_pass": sum(1 for row in markets if row["persistence_pass"]),
            "regime_pass": sum(1 for row in markets if row["regime_pass"]),
            "liquidity_pass": sum(1 for row in markets if row["liquidity_pass"]),
            "economics_pass": sum(1 for row in markets if row["economics_pass"]),
            "reason_counts": dict(reason_counts.most_common()),
        },
        "top_markets": sorted_markets[:top_n],
        "markets": sorted_markets,
    }


def funding_regime_report_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    top_n: int = 20,
    cfg: FundingRankConfig | None = None,
) -> dict[str, Any]:
    rows = load_funding_rows(input_path)
    payload = funding_regime_report(rows, top_n=top_n, cfg=cfg)
    payload["input"] = str(input_path)
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def _ranked_with_viability(rows: list[dict[str, Any]], top_n: int, cfg: FundingRankConfig) -> list[dict[str, Any]]:
    markets_analyzed = len({_funding_market_key(row) for row in rows})
    return [
        {**row, **_funding_viability_gap_fields(row, cfg)}
        for row in rank_funding_rows(rows, top_n=max(markets_analyzed, top_n), cfg=cfg)
    ]


def _funding_frontier_row(row: dict[str, Any], cfg: FundingRankConfig) -> dict[str, Any]:
    reasons = set(row.get("rank_reasons") or [])
    source_reasons = {reason for reason in reasons if reason == "source_not_eligible" or reason.startswith("source:")}
    economic_reasons = reasons & _FUNDING_ECONOMIC_REASONS
    liquidity_reasons = reasons & _FUNDING_LIQUIDITY_REASONS
    regime_reasons = reasons & _FUNDING_REGIME_REASONS
    if row.get("rank_eligible"):
        primary_blocker = "none"
    elif source_reasons:
        primary_blocker = "source"
    elif economic_reasons and liquidity_reasons:
        primary_blocker = "economics_and_liquidity"
    elif economic_reasons:
        primary_blocker = "economics"
    elif liquidity_reasons:
        primary_blocker = "liquidity"
    elif regime_reasons:
        primary_blocker = "regime"
    else:
        primary_blocker = "other"

    threshold = max(float(cfg.min_spot_top_notional_quote), 0.0)
    current_liquidity = _row_float(row, "spot_top_min_notional_quote", 0.0)
    regime_liquidity = _row_float(row, "regime_spot_top_min_notional_avg_quote", current_liquidity)
    liquidity_gap = max(threshold - regime_liquidity, 0.0) if threshold > 0.0 else 0.0
    liquidity_ratio = (regime_liquidity / threshold) if threshold > 0.0 else None
    funding_gap = _as_float(row.get("funding_gap_bps_per_interval_for_risk_edge"))
    required_hold_hours = _as_float(row.get("required_hold_hours_for_risk_edge"))
    frontier_score = (
        (funding_gap if funding_gap is not None else -1e6)
        + (min(liquidity_ratio, 1.0) if liquidity_ratio is not None else 1.0)
        - (5.0 if source_reasons else 0.0)
        - (2.0 if regime_reasons else 0.0)
    )
    return {
        "exchange": row.get("exchange"),
        "base": row.get("base"),
        "spot_symbol": row.get("spot_symbol"),
        "perp_symbol": row.get("perp_symbol"),
        "rank": row.get("rank"),
        "rank_eligible": row.get("rank_eligible"),
        "primary_blocker": primary_blocker,
        "rank_reasons": row.get("rank_reasons"),
        "funding_bps_per_interval": row.get("funding_bps_per_interval"),
        "expected_net_carry_bps": row.get("expected_net_carry_bps"),
        "risk_adjusted_edge_bps": row.get("risk_adjusted_edge_bps"),
        "required_funding_bps_per_interval_for_risk_edge": row.get("required_funding_bps_per_interval_for_risk_edge"),
        "funding_gap_bps_per_interval_for_risk_edge": funding_gap,
        "required_hold_hours_for_risk_edge": required_hold_hours,
        "target_hold_hours": row.get("target_hold_hours"),
        "spot_top_min_notional_quote": current_liquidity,
        "regime_spot_top_min_notional_avg_quote": regime_liquidity,
        "required_spot_top_notional_quote": threshold,
        "spot_top_liquidity_gap_quote": liquidity_gap,
        "spot_top_liquidity_ratio": liquidity_ratio,
        "basis_risk_penalty_bps": row.get("basis_risk_penalty_bps"),
        "spread_risk_penalty_bps": row.get("spread_risk_penalty_bps"),
        "regime_basis_std_bps": row.get("regime_basis_std_bps"),
        "regime_spread_avg_bps": row.get("regime_spread_avg_bps"),
        "frontier_score": frontier_score,
    }


def funding_frontier_report(rows: list[dict[str, Any]], top_n: int = 20, cfg: FundingRankConfig | None = None) -> dict[str, Any]:
    cfg = cfg or FundingRankConfig()
    markets_analyzed = len({_funding_market_key(row) for row in rows})
    strict_ranked = _ranked_with_viability(rows, top_n=max(markets_analyzed, top_n), cfg=cfg)
    liquidity_relaxed_cfg = replace(cfg, min_spot_top_notional_quote=0.0)
    economics_relaxed_cfg = replace(
        cfg,
        min_expected_net_carry_bps=-1e9,
        min_risk_adjusted_edge_bps=-1e9,
        max_break_even_hours=1e9,
    )
    fully_relaxed_cfg = replace(
        liquidity_relaxed_cfg,
        min_expected_net_carry_bps=-1e9,
        min_risk_adjusted_edge_bps=-1e9,
        max_break_even_hours=1e9,
    )
    liquidity_relaxed = _ranked_with_viability(rows, top_n=max(markets_analyzed, top_n), cfg=liquidity_relaxed_cfg)
    economics_relaxed = _ranked_with_viability(rows, top_n=max(markets_analyzed, top_n), cfg=economics_relaxed_cfg)
    fully_relaxed = _ranked_with_viability(rows, top_n=max(markets_analyzed, top_n), cfg=fully_relaxed_cfg)
    frontier_rows = [_funding_frontier_row(row, cfg) for row in strict_ranked]
    primary_counts = Counter(str(row.get("primary_blocker") or "other") for row in frontier_rows)
    reason_counts = Counter(reason for row in strict_ranked for reason in (row.get("rank_reasons") or []))
    liquidity_ratios = [
        value
        for value in (_as_float(row.get("spot_top_liquidity_ratio")) for row in frontier_rows)
        if value is not None
    ]
    funding_gaps = [
        value
        for value in (_as_float(row.get("funding_gap_bps_per_interval_for_risk_edge")) for row in frontier_rows)
        if value is not None
    ]
    required_hold_hours = [
        value
        for value in (_as_float(row.get("required_hold_hours_for_risk_edge")) for row in frontier_rows)
        if value is not None
    ]

    def eligible_count(ranked: list[dict[str, Any]]) -> int:
        return sum(1 for row in ranked if bool(row.get("rank_eligible")))

    return {
        "mode": "funding_frontier_report",
        "config": cfg.__dict__,
        "relaxed_configs": {
            "liquidity_relaxed": liquidity_relaxed_cfg.__dict__,
            "economics_relaxed": economics_relaxed_cfg.__dict__,
            "fully_relaxed": fully_relaxed_cfg.__dict__,
        },
        "summary": {
            "input_rows": len(rows),
            "markets_analyzed": markets_analyzed,
            "strict_rank_eligible": eligible_count(strict_ranked),
            "liquidity_relaxed_rank_eligible": eligible_count(liquidity_relaxed),
            "economics_relaxed_rank_eligible": eligible_count(economics_relaxed),
            "fully_relaxed_rank_eligible": eligible_count(fully_relaxed),
            "funding_gap_pass": sum(1 for row in strict_ranked if row.get("funding_gap_pass") is True),
            "spot_liquidity_pass": sum(
                1
                for row in frontier_rows
                if _row_float(row, "spot_top_liquidity_gap_quote", 1e9) <= 0.0
            ),
            "primary_blocker_counts": dict(primary_counts.most_common()),
            "reason_counts": dict(reason_counts.most_common()),
            "best_funding_gap_bps_per_interval": max(funding_gaps, default=None),
            "best_spot_top_liquidity_ratio": max(liquidity_ratios, default=None),
            "median_spot_top_liquidity_ratio": _percentile(liquidity_ratios, 0.5),
            "min_required_hold_hours": min(required_hold_hours, default=None),
        },
        "top_frontier": sorted(
            frontier_rows,
            key=lambda item: (
                bool(item.get("rank_eligible")),
                _row_float(item, "frontier_score", -1e9),
                _row_float(item, "spot_top_liquidity_ratio", -1e9),
            ),
            reverse=True,
        )[:top_n],
        "top_by_funding_gap": sorted(
            frontier_rows,
            key=lambda item: _row_float(item, "funding_gap_bps_per_interval_for_risk_edge", -1e9),
            reverse=True,
        )[:top_n],
        "top_by_liquidity_ratio": sorted(
            frontier_rows,
            key=lambda item: _row_float(item, "spot_top_liquidity_ratio", -1e9),
            reverse=True,
        )[:top_n],
    }


def funding_frontier_report_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    top_n: int = 20,
    cfg: FundingRankConfig | None = None,
) -> dict[str, Any]:
    rows = load_funding_rows(input_path)
    payload = funding_frontier_report(rows, top_n=top_n, cfg=cfg)
    payload["input"] = str(input_path)
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def _load_json_artifact(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    src = Path(path)
    if not src.exists():
        return None
    payload = json.loads(src.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def funding_decision_report(
    input_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    postprocess_report_path: str | Path | None = None,
    gate_report_path: str | Path | None = None,
    regime_report_path: str | Path | None = None,
    frontier_report_path: str | Path | None = None,
    sensitivity_report_path: str | Path | None = None,
    output_path: str | Path | None = None,
    stale_after_sec: float = 900.0,
    data_quality_cfg: FundingDataQualityConfig | None = None,
) -> dict[str, Any]:
    status = funding_collect_status(
        input_path,
        manifest_path=manifest_path,
        stale_after_sec=stale_after_sec,
        data_quality_cfg=data_quality_cfg,
    )
    postprocess = _load_json_artifact(postprocess_report_path)
    gate = _load_json_artifact(gate_report_path)
    regime = _load_json_artifact(regime_report_path)
    frontier = _load_json_artifact(frontier_report_path)
    sensitivity = _load_json_artifact(sensitivity_report_path)
    postprocess_research = postprocess.get("research_acceptance", {}) if postprocess else {}
    gate_summary = gate.get("summary", {}) if gate else {}
    regime_summary = regime.get("summary", {}) if regime else {}
    frontier_summary = frontier.get("summary", {}) if frontier else {}
    sensitivity_summary = sensitivity.get("summary", {}) if sensitivity else {}
    missing_artifacts = [
        name
        for name, artifact in (
            ("postprocess_report", postprocess),
            ("gate_report", gate),
            ("regime_report", regime),
            ("frontier_report", frontier),
            ("sensitivity_report", sensitivity),
        )
        if artifact is None
    ]

    reasons: list[str] = []
    next_action = "wait_and_recheck"
    verdict = "wait_for_final_dataset"
    accepted = False
    if not bool(status.get("ready_for_postprocess")):
        reasons.append("collector_not_ready")
        reasons.extend(f"readiness:{reason}" for reason in status.get("readiness", {}).get("reasons", []))
    else:
        if missing_artifacts:
            reasons.extend(f"missing:{name}" for name in missing_artifacts)
        if postprocess is not None:
            if postprocess.get("ok") is not True:
                reasons.append(f"postprocess_status:{postprocess.get('status') or 'not_ok'}")
            if postprocess_research.get("accepted") is not True:
                reasons.append("postprocess_research_not_accepted")
                reasons.extend(f"postprocess:{reason}" for reason in postprocess_research.get("reasons") or [])
        if int(gate_summary.get("rank_eligible") or 0) <= 0:
            reasons.append("gate_rank_eligible_zero")
        if int(regime_summary.get("eligible_markets") or 0) <= 0:
            reasons.append("regime_eligible_markets_zero")
        if int(regime_summary.get("liquidity_pass") or 0) <= 0:
            reasons.append("regime_liquidity_pass_zero")
        if int(regime_summary.get("economics_pass") or 0) <= 0:
            reasons.append("regime_economics_pass_zero")
        if int(frontier_summary.get("strict_rank_eligible") or 0) <= 0:
            reasons.append("frontier_strict_rank_eligible_zero")
        if int(frontier_summary.get("funding_gap_pass") or 0) <= 0:
            reasons.append("frontier_funding_gap_pass_zero")
        if int(sensitivity_summary.get("accepted_scenarios") or 0) <= 0:
            reasons.append("sensitivity_accepted_scenarios_zero")
        if sensitivity_summary.get("oos_enabled") is not True:
            reasons.append("sensitivity_oos_not_enabled")
        elif int(sensitivity_summary.get("oos_accepted_scenarios") or 0) <= 0:
            reasons.append("sensitivity_oos_accepted_zero")
        if sensitivity_summary.get("walk_forward_enabled") is not True:
            reasons.append("sensitivity_walk_forward_not_enabled")
        elif int(sensitivity_summary.get("walk_forward_accepted_scenarios") or 0) <= 0:
            reasons.append("sensitivity_walk_forward_accepted_zero")
        if sensitivity_summary.get("stress_enabled") is not True:
            reasons.append("sensitivity_stress_not_enabled")
        elif sensitivity_summary.get("stress_assumptions_passed") is not True:
            reasons.append("sensitivity_stress_assumptions_missing")
        elif int(sensitivity_summary.get("stress_accepted_scenarios") or 0) <= 0:
            reasons.append("sensitivity_stress_accepted_zero")
        if reasons:
            verdict = "research_rework_required"
            next_action = "tighten_universe_or_shift_strategy"
        else:
            verdict = "paper_forward_candidate"
            next_action = "run_funding_paper_plan"
            accepted = True

    payload = {
        "mode": "funding_decision_report",
        "input": str(input_path),
        "manifest": str(manifest_path) if manifest_path else str(Path(input_path).with_suffix(".manifest.json")),
        "artifacts": {
            "postprocess_report": str(postprocess_report_path) if postprocess_report_path else None,
            "gate_report": str(gate_report_path) if gate_report_path else None,
            "regime_report": str(regime_report_path) if regime_report_path else None,
            "frontier_report": str(frontier_report_path) if frontier_report_path else None,
            "sensitivity_report": str(sensitivity_report_path) if sensitivity_report_path else None,
            "missing": missing_artifacts,
        },
        "status": status,
        "summary": {
            "accepted": accepted,
            "verdict": verdict,
            "next_action": next_action,
            "reasons": reasons,
            "ready_for_postprocess": bool(status.get("ready_for_postprocess")),
            "postprocess_research_accepted": postprocess_research.get("accepted") if postprocess else None,
            "postprocess_research_reasons": postprocess_research.get("reasons") if postprocess else None,
            "gate_rank_eligible": gate_summary.get("rank_eligible"),
            "regime_eligible_markets": regime_summary.get("eligible_markets"),
            "regime_source_pass": regime_summary.get("source_pass"),
            "regime_persistence_pass": regime_summary.get("persistence_pass"),
            "regime_regime_pass": regime_summary.get("regime_pass"),
            "regime_liquidity_pass": regime_summary.get("liquidity_pass"),
            "regime_economics_pass": regime_summary.get("economics_pass"),
            "regime_reason_counts": regime_summary.get("reason_counts"),
            "frontier_strict_rank_eligible": frontier_summary.get("strict_rank_eligible"),
            "frontier_funding_gap_pass": frontier_summary.get("funding_gap_pass"),
            "frontier_primary_blocker_counts": frontier_summary.get("primary_blocker_counts"),
            "sensitivity_accepted_scenarios": sensitivity_summary.get("accepted_scenarios"),
            "sensitivity_oos_enabled": sensitivity_summary.get("oos_enabled"),
            "sensitivity_oos_accepted_scenarios": sensitivity_summary.get("oos_accepted_scenarios"),
            "sensitivity_walk_forward_enabled": sensitivity_summary.get("walk_forward_enabled"),
            "sensitivity_walk_forward_accepted_scenarios": sensitivity_summary.get("walk_forward_accepted_scenarios"),
            "sensitivity_stress_enabled": sensitivity_summary.get("stress_enabled"),
            "sensitivity_stress_assumptions_passed": sensitivity_summary.get("stress_assumptions_passed"),
            "sensitivity_stress_accepted_scenarios": sensitivity_summary.get("stress_accepted_scenarios"),
            "best_net_pnl_quote": sensitivity_summary.get("best_net_pnl_quote"),
            "best_oos_net_pnl_quote": sensitivity_summary.get("best_oos_net_pnl_quote"),
            "best_walk_forward_avg_test_net_pnl_quote": sensitivity_summary.get("best_walk_forward_avg_test_net_pnl_quote"),
        },
        "postprocess_summary": postprocess_research,
        "gate_summary": gate_summary,
        "regime_summary": regime_summary,
        "frontier_summary": frontier_summary,
        "sensitivity_summary": sensitivity_summary,
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def funding_paper_decision_report(
    summary_path: str | Path,
    *,
    plan_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    summary = _load_json_artifact(summary_path)
    plan = _load_json_artifact(plan_path)
    reasons: list[str] = []
    if summary is None:
        reasons.append("summary_missing_or_invalid")
        summary = {}
    if plan_path is None:
        reasons.append("plan_required")
    elif plan is None:
        reasons.append("plan_missing_or_invalid")
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    paper_acceptance = summary.get("paper_acceptance") if isinstance(summary.get("paper_acceptance"), dict) else {}
    coverage = summary.get("coverage") if isinstance(summary.get("coverage"), dict) else {}
    frozen_config = summary.get("frozen_config") if isinstance(summary.get("frozen_config"), dict) else {}
    required_metrics = FUNDING_PAPER_REQUIRED_METRICS
    if summary.get("mode") != "funding_paper_forward":
        reasons.append("mode_not_funding_paper_forward")
    if summary.get("status") != "completed":
        reasons.append(f"status:{summary.get('status') or 'missing'}")
    if summary.get("ok") is not True:
        reasons.append("ok_not_true")
    for field, expected in (
        ("research_only", True),
        ("live_orders", False),
        ("api_keys_required", False),
        ("leverage_enabled", False),
        ("margin_execution", False),
    ):
        if summary.get(field) is not expected:
            reasons.append(f"{field}_not_{str(expected).lower()}")
    if paper_acceptance.get("accepted") is not True:
        reasons.append("paper_acceptance_not_accepted")
        reasons.extend(f"paper_acceptance:{reason}" for reason in paper_acceptance.get("reasons") or [])
    for coverage_field in ("duration_accepted", "rows_accepted", "markets_accepted"):
        if coverage.get(coverage_field) is not True:
            reasons.append(f"coverage:{coverage_field}_not_true")
    if not isinstance(frozen_config.get("acceptance_config"), dict):
        reasons.append("frozen_acceptance_config_missing")
    if not isinstance(frozen_config.get("backtest_config"), dict):
        reasons.append("frozen_backtest_config_missing")
    for metric in required_metrics:
        if _as_float(metrics.get(metric)) is None:
            reasons.append(f"metric:{metric}_missing")
    if plan is not None:
        plan_gate = _funding_paper_forward_plan_gate_reasons(plan)
        if plan_gate["all"]:
            reasons.append("plan_gate_failed")
            reasons.extend(f"plan:{reason}" for reason in plan_gate["all"])
        if not summary.get("plan"):
            reasons.append("summary_plan_path_missing")
        elif not _same_path(Path(str(summary.get("plan"))), Path(plan_path)):  # type: ignore[arg-type]
            reasons.append("summary_plan_path_mismatch")
        plan_frozen_config = _canonical_funding_frozen_config(plan.get("frozen_config"))
        summary_frozen_config = _canonical_funding_frozen_config(frozen_config)
        if summary_frozen_config != plan_frozen_config:
            reasons.append("summary_frozen_config_mismatch")
        plan_paper_output = plan.get("paper_output_path")
        if plan_paper_output:
            if not summary.get("output"):
                reasons.append("summary_output_path_missing")
            elif not _same_path(Path(str(summary.get("output"))), Path(str(plan_paper_output))):
                reasons.append("summary_output_path_mismatch")
        plan_source_input = plan.get("source_input")
        if plan_source_input:
            if not summary.get("source_input"):
                reasons.append("summary_source_input_missing")
            elif not _same_path(Path(str(summary.get("source_input"))), Path(str(plan_source_input))):
                reasons.append("summary_source_input_mismatch")
            if summary.get("input") and _same_path(Path(str(summary.get("input"))), Path(str(plan_source_input))):
                reasons.append("summary_input_reuses_source_input")

    accepted = not reasons
    verdict = "continue_paper_forward" if accepted else "paper_rework_required"
    next_action = "extend_paper_forward_dataset" if accepted else "fix_plan_or_rework_strategy"
    payload = {
        "mode": "funding_paper_decision_report",
        "summary_path": str(summary_path),
        "plan_path": str(plan_path) if plan_path else None,
        "output": str(output_path) if output_path else None,
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "summary": {
            "accepted": accepted,
            "verdict": verdict,
            "next_action": next_action,
            "reasons": reasons,
            "status": summary.get("status"),
            "paper_acceptance_accepted": paper_acceptance.get("accepted"),
            "total_trades": metrics.get("total_trades"),
            "win_rate": metrics.get("win_rate"),
            "expectancy_quote": metrics.get("expectancy_quote"),
            "net_pnl_quote": metrics.get("net_pnl_quote"),
            "max_drawdown_quote": metrics.get("max_drawdown_quote"),
            "profit_factor": metrics.get("profit_factor"),
            "funding_pnl_quote": metrics.get("funding_pnl_quote"),
            "basis_pnl_quote": metrics.get("basis_pnl_quote"),
            "fees_quote": metrics.get("fees_quote"),
            "slippage_quote": metrics.get("slippage_quote"),
            "coverage": coverage,
        },
        "metrics": metrics,
        "paper_acceptance": paper_acceptance,
        "coverage": coverage,
        "frozen_config": frozen_config,
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def _funding_goal_audit_metric_summary(
    final_review: dict[str, Any] | None,
    paper_summary: dict[str, Any] | None,
    paper_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    final_summary = final_review.get("summary") if final_review and isinstance(final_review.get("summary"), dict) else {}
    paper_metrics = paper_summary.get("metrics") if paper_summary and isinstance(paper_summary.get("metrics"), dict) else {}
    paper_acceptance = (
        paper_summary.get("paper_acceptance")
        if paper_summary and isinstance(paper_summary.get("paper_acceptance"), dict)
        else {}
    )
    paper_coverage = paper_summary.get("coverage") if paper_summary and isinstance(paper_summary.get("coverage"), dict) else {}
    decision_summary = paper_decision.get("summary") if paper_decision and isinstance(paper_decision.get("summary"), dict) else {}
    return {
        "final_review_accepted": final_summary.get("accepted"),
        "final_review_verdict": final_summary.get("verdict"),
        "final_review_next_action": final_summary.get("next_action"),
        "final_backtest_total_trades": final_summary.get("backtest_total_trades"),
        "final_backtest_win_rate": final_summary.get("backtest_win_rate"),
        "final_backtest_expectancy_quote": final_summary.get("backtest_expectancy_quote"),
        "final_backtest_net_pnl_quote": final_summary.get("backtest_net_pnl_quote"),
        "final_backtest_max_drawdown_quote": final_summary.get("backtest_max_drawdown_quote"),
        "final_funding_pnl_quote": final_summary.get("backtest_funding_pnl_quote"),
        "final_basis_pnl_quote": final_summary.get("backtest_basis_pnl_quote"),
        "final_fees_quote": final_summary.get("backtest_fees_quote"),
        "final_slippage_quote": final_summary.get("backtest_slippage_quote"),
        "final_oos_accepted": final_summary.get("oos_accepted"),
        "final_oos_net_pnl_quote": final_summary.get("oos_net_pnl_quote"),
        "final_walk_forward_accepted": final_summary.get("walk_forward_accepted"),
        "final_walk_forward_avg_test_net_pnl_quote": final_summary.get("walk_forward_avg_test_net_pnl_quote"),
        "final_stress_accepted": final_summary.get("stress_accepted"),
        "paper_forward_status": paper_summary.get("status") if paper_summary else None,
        "paper_forward_total_trades": paper_metrics.get("total_trades"),
        "paper_forward_win_rate": paper_metrics.get("win_rate"),
        "paper_forward_expectancy_quote": paper_metrics.get("expectancy_quote"),
        "paper_forward_net_pnl_quote": paper_metrics.get("net_pnl_quote"),
        "paper_forward_max_drawdown_quote": paper_metrics.get("max_drawdown_quote"),
        "paper_forward_profit_factor": paper_metrics.get("profit_factor"),
        "paper_forward_funding_pnl_quote": paper_metrics.get("funding_pnl_quote"),
        "paper_forward_basis_pnl_quote": paper_metrics.get("basis_pnl_quote"),
        "paper_forward_fees_quote": paper_metrics.get("fees_quote"),
        "paper_forward_slippage_quote": paper_metrics.get("slippage_quote"),
        "paper_forward_acceptance_accepted": paper_acceptance.get("accepted"),
        "paper_forward_coverage": paper_coverage or None,
        "paper_decision_accepted": decision_summary.get("accepted"),
        "paper_decision_verdict": decision_summary.get("verdict"),
        "paper_decision_next_action": decision_summary.get("next_action"),
    }


def funding_goal_audit(
    input_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    final_review_path: str | Path | None = None,
    paper_plan_path: str | Path | None = None,
    paper_summary_path: str | Path | None = None,
    paper_decision_path: str | Path | None = None,
    output_path: str | Path | None = None,
    stale_after_sec: float = 900.0,
    data_quality_cfg: FundingDataQualityConfig | None = None,
) -> dict[str, Any]:
    status = funding_collect_status(
        input_path,
        manifest_path=manifest_path,
        stale_after_sec=stale_after_sec,
        data_quality_cfg=data_quality_cfg,
    )
    final_review = _load_json_artifact(final_review_path)
    paper_plan = _load_json_artifact(paper_plan_path)
    paper_summary = _load_json_artifact(paper_summary_path)
    paper_decision = _load_json_artifact(paper_decision_path)
    blockers: list[str] = []
    stage = "collecting_funding"
    next_action = "wait_and_recheck"
    accepted = False

    if not bool(status.get("ready_for_postprocess")):
        blockers.append("collector_not_ready")
        blockers.extend(f"readiness:{reason}" for reason in status.get("readiness", {}).get("reasons", []))
    else:
        stage = "funding_final_review_pending"
        next_action = "run_funding_final_review"
        if final_review is not None:
            final_summary = final_review.get("summary") if isinstance(final_review.get("summary"), dict) else {}
            final_review_gate = _funding_final_review_artifact_gate_reasons(
                final_review,
                input_path=input_path,
                manifest_path=manifest_path,
            )
            if final_review_gate:
                blockers.append("final_review_artifact_mismatch")
                blockers.extend(f"final_review:{reason}" for reason in final_review_gate)
                stage = "funding_final_review_invalid"
                next_action = "rerun_funding_final_review"
            elif final_review.get("status") not in {"completed", "not_ready_for_postprocess"}:
                blockers.append(f"final_review_status:{final_review.get('status') or 'missing'}")
                stage = "funding_final_review_invalid"
                next_action = "rerun_funding_final_review"
            elif final_summary.get("accepted") is not True:
                blockers.append("funding_final_review_not_accepted")
                blockers.extend(f"final_review:{reason}" for reason in final_summary.get("reasons") or [])
                stage = "research_rework_required"
                next_action = "tighten_universe_or_shift_strategy"
            elif paper_plan is None:
                blockers.append("paper_plan_missing")
                stage = "paper_plan_pending"
                next_action = "inspect_or_create_funding_paper_plan"
            elif paper_plan.get("ready_for_paper_forward") is not True:
                blockers.append(f"paper_plan_status:{paper_plan.get('status') or 'not_ready'}")
                stage = "paper_plan_not_ready"
                next_action = "fix_research_acceptance_before_paper_forward"
            elif (paper_plan_gate := _funding_paper_forward_plan_gate_reasons(paper_plan))["all"]:
                blockers.append("paper_plan_gate_failed")
                blockers.extend(f"paper_plan:{reason}" for reason in paper_plan_gate["all"])
                stage = "paper_plan_not_ready"
                next_action = "fix_research_acceptance_before_paper_forward"
            elif (
                paper_plan_artifact_gate := _funding_paper_plan_artifact_gate_reasons(
                    paper_plan,
                    input_path=input_path,
                    final_review=final_review,
                    paper_plan_path=paper_plan_path,
                )
            ):
                blockers.append("paper_plan_artifact_mismatch")
                blockers.extend(f"paper_plan:{reason}" for reason in paper_plan_artifact_gate)
                stage = "paper_plan_not_ready"
                next_action = "fix_research_acceptance_before_paper_forward"
            elif paper_summary is None:
                stage = "paper_forward_pending"
                next_action = "collect_forward_dataset_and_run_paper_forward"
            elif (
                paper_summary_gate := _funding_paper_summary_artifact_gate_reasons(
                    paper_summary,
                    paper_plan=paper_plan,
                    paper_plan_path=paper_plan_path,
                )
            ):
                blockers.append("paper_summary_artifact_mismatch")
                blockers.extend(f"paper_summary:{reason}" for reason in paper_summary_gate)
                stage = "paper_forward_invalid"
                next_action = "rerun_funding_paper_forward"
            elif paper_decision is None:
                stage = "paper_decision_pending"
                next_action = "run_funding_paper_decision_report"
            else:
                paper_decision_summary = paper_decision.get("summary") if isinstance(paper_decision.get("summary"), dict) else {}
                paper_decision_gate = _funding_paper_decision_artifact_gate_reasons(
                    paper_decision,
                    paper_summary_path=paper_summary_path,
                    paper_plan_path=paper_plan_path,
                    paper_summary=paper_summary,
                )
                if paper_decision_gate:
                    blockers.append("paper_decision_artifact_mismatch")
                    blockers.extend(f"paper_decision:{reason}" for reason in paper_decision_gate)
                    stage = "paper_decision_invalid"
                    next_action = "rerun_funding_paper_decision_report"
                elif paper_decision_summary.get("accepted") is True:
                    stage = "paper_forward_validated"
                    next_action = "extend_paper_forward_dataset"
                    accepted = True
                else:
                    blockers.append("paper_decision_not_accepted")
                    blockers.extend(f"paper_decision:{reason}" for reason in paper_decision_summary.get("reasons") or [])
                    stage = "paper_rework_required"
                    next_action = "fix_plan_or_rework_strategy"

    payload = {
        "mode": "funding_goal_audit",
        "input": str(input_path),
        "manifest": str(manifest_path) if manifest_path else str(Path(input_path).with_suffix(".manifest.json")),
        "artifacts": {
            "final_review": str(final_review_path) if final_review_path else None,
            "paper_plan": str(paper_plan_path) if paper_plan_path else None,
            "paper_summary": str(paper_summary_path) if paper_summary_path else None,
            "paper_decision": str(paper_decision_path) if paper_decision_path else None,
        },
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "summary": {
            "accepted": accepted,
            "stage": stage,
            "next_action": next_action,
            "blockers": blockers,
            "ready_for_postprocess": bool(status.get("ready_for_postprocess")),
            "collector_status": status.get("status"),
            "completed_cycles": status.get("completed_cycles"),
            "cycles": status.get("cycles"),
            "expected_cycles": status.get("expected_cycles"),
            "remaining_cycles": status.get("remaining_cycles"),
            "progress_pct": status.get("progress_pct"),
            "eta_sec": status.get("eta_sec"),
            "estimated_next_cycle_in_sec": status.get("estimated_next_cycle_in_sec"),
            "line_count": status.get("line_count"),
            "errors": status.get("errors"),
            "last_write_ts": status.get("last_write_ts"),
            "last_write_age_sec": status.get("last_write_age_sec"),
            "data_quality_accepted": (status.get("data_quality") or {}).get("accepted"),
            "data_quality_reasons": (status.get("data_quality") or {}).get("reasons"),
            "data_quality_metrics": (status.get("data_quality") or {}).get("metrics"),
            **_funding_goal_audit_metric_summary(final_review, paper_summary, paper_decision),
        },
        "collect_status": status,
        "final_review_summary": (final_review or {}).get("summary") if final_review else None,
        "paper_plan_summary": {
            "status": paper_plan.get("status"),
            "ready_for_paper_forward": paper_plan.get("ready_for_paper_forward"),
            "min_forward_hours": paper_plan.get("min_forward_hours"),
            "min_forward_rows": paper_plan.get("min_forward_rows"),
            "min_forward_markets": paper_plan.get("min_forward_markets"),
        }
        if paper_plan
        else None,
        "paper_summary": {
            "status": paper_summary.get("status"),
            "paper_acceptance": paper_summary.get("paper_acceptance"),
            "metrics": paper_summary.get("metrics"),
            "coverage": paper_summary.get("coverage"),
        }
        if paper_summary
        else None,
        "paper_decision_summary": (paper_decision or {}).get("summary") if paper_decision else None,
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def _funding_wait_status_entry(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": time.time(),
        "status": status.get("status"),
        "ready_for_postprocess": bool(status.get("ready_for_postprocess")),
        "completed_cycles": status.get("completed_cycles"),
        "cycles": status.get("cycles"),
        "expected_cycles": status.get("expected_cycles"),
        "remaining_cycles": status.get("remaining_cycles"),
        "progress_pct": status.get("progress_pct"),
        "eta_sec": status.get("eta_sec"),
        "estimated_next_cycle_in_sec": status.get("estimated_next_cycle_in_sec"),
        "line_count": status.get("line_count"),
        "errors": status.get("errors"),
        "last_write_age_sec": status.get("last_write_age_sec"),
        "readiness_reasons": status.get("readiness", {}).get("reasons", []),
    }


def wait_funding_ready(
    input_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    output_path: str | Path | None = None,
    timeout_sec: float = 0.0,
    poll_interval_sec: float = 60.0,
    stale_after_sec: float = 900.0,
    data_quality_cfg: FundingDataQualityConfig | None = None,
    max_history: int = 100,
) -> dict[str, Any]:
    started = time.time()
    deadline = started + max(float(timeout_sec), 0.0)
    interval = max(float(poll_interval_sec), 0.0)
    history: list[dict[str, Any]] = []
    final_status: dict[str, Any] | None = None
    terminal_statuses = {"missing_output", "missing_manifest", "stale"}
    while True:
        status = funding_collect_status(
            input_path,
            manifest_path=manifest_path,
            stale_after_sec=stale_after_sec,
            data_quality_cfg=data_quality_cfg,
        )
        final_status = status
        history.append(_funding_wait_status_entry(status))
        if len(history) > max_history:
            history = history[-max_history:]
        if bool(status.get("ready_for_postprocess")):
            wait_status = "ready_for_postprocess"
            ok = True
            break
        if status.get("status") in terminal_statuses:
            wait_status = str(status.get("status"))
            ok = False
            break
        now = time.time()
        if now >= deadline:
            wait_status = "timeout"
            ok = False
            break
        sleep_sec = min(interval, max(0.0, deadline - now))
        if sleep_sec <= 0.0:
            wait_status = "timeout"
            ok = False
            break
        time.sleep(sleep_sec)

    payload = {
        "mode": "funding_wait_ready",
        "ok": ok,
        "status": wait_status,
        "input": str(input_path),
        "manifest": str(manifest_path) if manifest_path else str(Path(input_path).with_suffix(".manifest.json")),
        "timeout_sec": timeout_sec,
        "poll_interval_sec": poll_interval_sec,
        "stale_after_sec": stale_after_sec,
        "elapsed_sec": time.time() - started,
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "ready_for_postprocess": bool((final_status or {}).get("ready_for_postprocess")),
        "final_status": final_status,
        "history": history,
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def funding_progress_report(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any] | None = None,
    top_n: int = 5,
    cfg: FundingRankConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or FundingRankConfig()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cycle = int(row.get("cycle") or 0)
        grouped[cycle].append(row)
    manifest_cycles = {
        int(item.get("cycle") or 0): item
        for item in (manifest or {}).get("cycle_summaries", [])
        if int(item.get("cycle") or 0) > 0
    }

    cycle_reports: list[dict[str, Any]] = []
    for cycle in sorted(grouped):
        cycle_rows = grouped[cycle]
        markets = len({_funding_market_key(row) for row in cycle_rows})
        ranked = [
            {**row, **_funding_viability_gap_fields(row, cfg)}
            for row in rank_funding_rows(cycle_rows, top_n=max(markets, top_n), cfg=cfg)
        ]
        best = ranked[0] if ranked else {}
        spot_top_values = [
            value
            for value in (_as_float(row.get("spot_top_min_notional_quote")) for row in cycle_rows)
            if value is not None
        ]
        spread_values = [
            value
            for value in (_as_float(row.get("execution_cost_bps")) for row in cycle_rows)
            if value is not None
        ]
        funding_values = [
            value
            for value in (_as_float(row.get("funding_bps_per_interval")) for row in cycle_rows)
            if value is not None
        ]
        manifest_cycle = manifest_cycles.get(cycle, {})
        cycle_reports.append(
            {
                "cycle": cycle,
                "rows": len(cycle_rows),
                "markets": markets,
                "source_eligible": sum(1 for row in cycle_rows if bool(row.get("eligible", True))),
                "rank_eligible": sum(1 for row in ranked if bool(row.get("rank_eligible"))),
                "funding_gap_pass": sum(1 for row in ranked if row.get("funding_gap_pass") is True),
                "best_base": best.get("base"),
                "best_exchange": best.get("exchange"),
                "best_funding_gap_bps_per_interval_for_risk_edge": best.get("funding_gap_bps_per_interval_for_risk_edge"),
                "best_risk_adjusted_edge_bps": best.get("risk_adjusted_edge_bps"),
                "best_expected_net_carry_bps": best.get("expected_net_carry_bps"),
                "avg_spot_top_min_notional_quote": _avg(spot_top_values),
                "max_spot_top_min_notional_quote": max(spot_top_values) if spot_top_values else None,
                "avg_execution_cost_bps": _avg(spread_values),
                "avg_funding_bps_per_interval": _avg(funding_values),
                "manifest_errors": int(manifest_cycle.get("errors") or 0),
                "manifest_rows": int(manifest_cycle.get("rows") or 0) if manifest_cycle else None,
                "manifest_eligible": int(manifest_cycle.get("eligible") or 0) if manifest_cycle else None,
                "top": [
                    {
                        "exchange": row.get("exchange"),
                        "base": row.get("base"),
                        "rank_eligible": row.get("rank_eligible"),
                        "funding_gap_pass": row.get("funding_gap_pass"),
                        "funding_gap_bps_per_interval_for_risk_edge": row.get("funding_gap_bps_per_interval_for_risk_edge"),
                        "risk_adjusted_edge_bps": row.get("risk_adjusted_edge_bps"),
                        "expected_net_carry_bps": row.get("expected_net_carry_bps"),
                        "regime_spot_top_min_notional_avg_quote": row.get("regime_spot_top_min_notional_avg_quote"),
                        "rank_reasons": row.get("rank_reasons"),
                    }
                    for row in ranked[:top_n]
                ],
            }
        )

    first = cycle_reports[0] if cycle_reports else {}
    latest = cycle_reports[-1] if cycle_reports else {}
    best_gap_first = _as_float(first.get("best_funding_gap_bps_per_interval_for_risk_edge")) if first else None
    best_gap_latest = _as_float(latest.get("best_funding_gap_bps_per_interval_for_risk_edge")) if latest else None
    spot_top_first = _as_float(first.get("avg_spot_top_min_notional_quote")) if first else None
    spot_top_latest = _as_float(latest.get("avg_spot_top_min_notional_quote")) if latest else None
    warnings: list[str] = []
    if latest and int(latest.get("rank_eligible") or 0) == 0:
        warnings.append("latest_cycle_no_rank_eligible")
    if latest and int(latest.get("funding_gap_pass") or 0) == 0:
        warnings.append("latest_cycle_no_funding_gap_pass")
    if best_gap_latest is not None and best_gap_latest < 0.0:
        warnings.append("latest_best_gap_negative")
    return {
        "mode": "funding_progress_report",
        "config": cfg.__dict__,
        "summary": {
            "input_rows": len(rows),
            "cycles": len(cycle_reports),
            "first_cycle": first.get("cycle"),
            "latest_cycle": latest.get("cycle"),
            "latest_rows": latest.get("rows"),
            "latest_markets": latest.get("markets"),
            "latest_rank_eligible": latest.get("rank_eligible"),
            "latest_funding_gap_pass": latest.get("funding_gap_pass"),
            "latest_best_base": latest.get("best_base"),
            "latest_best_exchange": latest.get("best_exchange"),
            "latest_best_funding_gap_bps_per_interval_for_risk_edge": best_gap_latest,
            "best_gap_delta_bps": (
                best_gap_latest - best_gap_first
                if best_gap_latest is not None and best_gap_first is not None
                else None
            ),
            "avg_spot_top_notional_delta_quote": (
                spot_top_latest - spot_top_first
                if spot_top_latest is not None and spot_top_first is not None
                else None
            ),
            "manifest_final": bool((manifest or {}).get("final")),
            "manifest_completed_cycles": int((manifest or {}).get("completed_cycles") or 0) if manifest else None,
            "manifest_errors": int((manifest or {}).get("errors") or 0) if manifest else None,
            "warnings": warnings,
        },
        "cycles": cycle_reports,
    }


def funding_progress_report_file(
    input_path: str | Path,
    manifest_path: str | Path | None = None,
    output_path: str | Path | None = None,
    top_n: int = 5,
    cfg: FundingRankConfig | None = None,
) -> dict[str, Any]:
    src = Path(input_path)
    manifest = _load_funding_manifest(Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json"))
    payload = funding_progress_report(load_funding_rows(src), manifest=manifest, top_n=top_n, cfg=cfg)
    payload["input"] = str(src)
    if manifest_path or manifest:
        payload["manifest"] = str(Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json"))
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def funding_collect_diagnostics_file(
    input_path: str | Path,
    manifest_path: str | Path | None = None,
    output_path: str | Path | None = None,
    top_n: int = 20,
    required_fields: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    src = Path(input_path)
    manifest_file = Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json")
    manifest = _load_funding_manifest(manifest_file) or {}
    rows = load_funding_rows(src)
    required = required_fields or (
        "ts",
        "exchange",
        "base",
        "quote",
        "spot_symbol",
        "perp_symbol",
        "funding_rate",
        "next_funding_ts",
        "funding_interval_sec",
        "spot_bid",
        "spot_ask",
        "spot_mid",
        "perp_bid",
        "perp_ask",
        "perp_mark",
        "spot_spread_bps",
        "perp_spread_bps",
        "basis_bps",
        "spot_top_min_notional_quote",
        "expected_net_carry_bps",
        "round_trip_cost_bps",
        "eligible",
        "cycle",
    )
    cycles = sorted({row.get("cycle") for row in rows if row.get("cycle") is not None})
    cycle_rows = Counter(row.get("cycle") for row in rows if row.get("cycle") is not None)
    eligible_rows = [row for row in rows if row.get("eligible") is True]
    cycle_eligible = Counter(row.get("cycle") for row in eligible_rows if row.get("cycle") is not None)
    exchange_counts = Counter(str(row.get("exchange") or "unknown") for row in rows)
    markets = {_funding_market_key(row) for row in rows}
    reason_counts = Counter(reason for row in rows for reason in (row.get("reasons") or []))
    missing_required = Counter()
    for row in rows:
        for field in required:
            if field not in row or row.get(field) is None:
                missing_required[field] += 1
    manifest_error_breakdown = Counter()
    for cycle in manifest.get("cycle_summaries") or []:
        for item in cycle.get("error_breakdown") or []:
            key = str(item.get("key") or "unknown")
            manifest_error_breakdown[key] += int(item.get("count") or 0)
    positive_expected_net = [
        row for row in rows
        if (value := _as_float(row.get("expected_net_carry_bps"))) is not None and value > 0.0
    ]
    positive_funding = [
        row for row in rows
        if (value := _as_float(row.get("funding_rate"))) is not None and value > 0.0
    ]
    rows_per_cycle = [float(value) for value in cycle_rows.values()]
    summary = {
        "final": bool(manifest.get("final")) if manifest else None,
        "completed_cycles": manifest.get("completed_cycles"),
        "expected_cycles": manifest.get("cycles"),
        "remaining_cycles": (
            max(0, int(manifest.get("cycles") or 0) - int(manifest.get("completed_cycles") or 0))
            if manifest.get("cycles") is not None else None
        ),
        "progress_pct": (
            float(manifest.get("completed_cycles") or 0) / float(manifest.get("cycles") or 1) * 100.0
            if manifest else None
        ),
        "rows_jsonl": len(rows),
        "rows_manifest": manifest.get("rows"),
        "rows_match_manifest": manifest.get("rows") == len(rows) if manifest.get("rows") is not None else None,
        "errors_manifest": manifest.get("errors"),
        "unique_cycles": len(cycles),
        "unique_exchanges": sorted(exchange_counts),
        "unique_markets": len(markets),
        "eligible_rows": len(eligible_rows),
        "eligible_ratio": len(eligible_rows) / len(rows) if rows else 0.0,
        "positive_funding_rows": len(positive_funding),
        "positive_expected_net_carry_rows": len(positive_expected_net),
        "all_expected_net_carry_negative": len(positive_expected_net) == 0 if rows else None,
        "min_rows_per_cycle": min(rows_per_cycle) if rows_per_cycle else 0,
        "max_rows_per_cycle": max(rows_per_cycle) if rows_per_cycle else 0,
        "avg_rows_per_cycle": _avg(rows_per_cycle) or 0.0,
        "avg_eligible_per_cycle": sum(cycle_eligible.values()) / len(cycles) if cycles else 0.0,
    }

    def compact_row(row: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "cycle",
            "exchange",
            "base",
            "spot_symbol",
            "perp_symbol",
            "funding_bps_per_interval",
            "expected_net_carry_bps",
            "basis_bps",
            "spot_top_min_notional_quote",
            "total_score",
            "eligible",
            "reasons",
        )
        return {field: row.get(field) for field in fields}

    distribution_fields = (
        "funding_bps_per_interval",
        "expected_net_carry_bps",
        "spot_spread_bps",
        "perp_spread_bps",
        "basis_bps",
        "spot_top_min_notional_quote",
        "total_score",
    )
    payload = {
        "mode": "funding_collect_diagnostics",
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "input": str(src),
        "manifest": str(manifest_file),
        "summary": summary,
        "exchange_rows": dict(exchange_counts),
        "reason_breakdown": dict(reason_counts),
        "manifest_error_breakdown": dict(manifest_error_breakdown),
        "missing_required_fields": {key: value for key, value in missing_required.items() if value},
        "distributions": {field: _field_distribution(rows, field) for field in distribution_fields},
        "top_by_total_score": [
            compact_row(row)
            for row in sorted(rows, key=lambda item: _row_float(item, "total_score", -1e18), reverse=True)[:top_n]
        ],
        "top_by_expected_net_carry": [
            compact_row(row)
            for row in sorted(
                [row for row in rows if _as_float(row.get("expected_net_carry_bps")) is not None],
                key=lambda item: _row_float(item, "expected_net_carry_bps", -1e18),
                reverse=True,
            )[:top_n]
        ],
        "notes": [
            "Diagnostics may be generated before the collector is final; do not use partial diagnostics as acceptance evidence.",
            "Strategy acceptance still requires strict final-review, OOS/stress checks, and paper-forward evidence.",
        ],
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(target)
    return payload


def run_funding_backtest(rows: list[dict[str, Any]], cfg: FundingBacktestConfig) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = _funding_market_key(row)
        grouped[key].append(row)

    trades: list[FundingTrade] = []
    open_positions: list[FundingPosition] = []
    for market, market_rows in grouped.items():
        position: FundingPosition | None = None
        history: list[dict[str, Any]] = []
        last_row: dict[str, Any] | None = None
        for raw_row in sorted(market_rows, key=lambda item: float(item.get("ts") or 0)):
            history.append(raw_row)
            row = _with_rolling_persistence(raw_row, history, cfg)
            last_row = row
            if position is not None:
                position = _accrue_funding(position, row)
                exit_reason = _exit_reason(row, cfg)
                if exit_reason:
                    trade = _close_position(position, row, cfg, exit_reason)
                    trades.append(trade)
                    position = None
                    continue
            if position is None and _entry_allowed(row, cfg):
                position = _open_position(market, row, cfg)
        if position is not None and last_row is not None:
            trade = _close_position(position, last_row, cfg, "force_end")
            trades.append(trade)
    equity_curve = _funding_equity_curve(trades)
    metrics = _funding_metrics(trades, len(rows), len(grouped), equity_curve)
    return {
        "mode": "funding_basis_backtest",
        "config": cfg.__dict__,
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": [trade.__dict__ for trade in trades],
        "open_positions": [position.__dict__ for position in open_positions],
    }


def run_funding_backtest_file(
    input_path: str | Path,
    output_path: str | Path,
    cfg: FundingBacktestConfig,
) -> dict[str, Any]:
    rows = load_funding_rows(input_path)
    payload = run_funding_backtest(rows, cfg)
    payload["input"] = str(input_path)
    payload["output"] = str(output_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _funding_oos_result_summary(oos: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": oos.get("ok"),
        "status": oos.get("status"),
        "accepted": oos.get("accepted"),
        "split": oos.get("split"),
        "coverage": oos.get("coverage"),
        "coverage_acceptance": oos.get("coverage_acceptance"),
        "in_sample_metrics": (oos.get("in_sample") or {}).get("metrics"),
        "out_of_sample_metrics": (oos.get("out_of_sample") or {}).get("metrics"),
        "in_sample_acceptance": oos.get("in_sample_acceptance"),
        "out_of_sample_acceptance": oos.get("out_of_sample_acceptance"),
    }


def _funding_walk_forward_result_summary(walk_forward: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": walk_forward.get("ok"),
        "status": walk_forward.get("status"),
        "accepted": walk_forward.get("accepted"),
        "reasons": walk_forward.get("reasons", []),
        "summary": walk_forward.get("summary"),
        "acceptance_config": walk_forward.get("acceptance_config"),
        "walk_forward_config": walk_forward.get("walk_forward_config"),
    }


def _optional_gate_sort_value(value: Any) -> bool:
    return True if value is None else bool(value)


def run_funding_sensitivity(
    rows: list[dict[str, Any]],
    sensitivity_cfg: FundingSensitivityConfig,
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig | None = None,
    stress_cfg: FundingStressConfig | None = None,
    oos_cfg: FundingOosConfig | None = None,
    walk_forward_cfg: FundingWalkForwardConfig | None = None,
) -> dict[str, Any]:
    acceptance_cfg = acceptance_cfg or FundingAcceptanceConfig()
    stress_cfg = stress_cfg or FundingStressConfig()
    scenarios: list[dict[str, Any]] = []
    oos_enabled = oos_cfg is not None
    walk_forward_enabled = walk_forward_cfg is not None
    stress_enabled = bool(stress_cfg.enabled)
    stress_assumptions_passed = _funding_stress_assumptions_passed(stress_cfg)
    for spot_fee_bps, perp_fee_bps, slippage_bps, target_hold_intervals, max_break_even_hours in product(
        sensitivity_cfg.spot_fee_bps_values,
        sensitivity_cfg.perp_fee_bps_values,
        sensitivity_cfg.slippage_bps_values,
        sensitivity_cfg.target_hold_intervals_values,
        sensitivity_cfg.max_break_even_hours_values,
    ):
        repriced_rows = reprice_funding_rows_for_costs(
            rows,
            spot_fee_bps=spot_fee_bps,
            perp_fee_bps=perp_fee_bps,
            slippage_bps=slippage_bps,
            target_hold_intervals=target_hold_intervals,
            min_expected_net_carry_bps=backtest_cfg.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=backtest_cfg.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=backtest_cfg.basis_risk_multiplier,
            spread_risk_multiplier=backtest_cfg.spread_risk_multiplier,
            max_break_even_hours=max_break_even_hours,
        )
        scenario_backtest_cfg = FundingBacktestConfig(
            **{
                **backtest_cfg.__dict__,
                "spot_fee_bps": spot_fee_bps,
                "perp_fee_bps": perp_fee_bps,
                "slippage_bps": slippage_bps,
                "max_break_even_hours": max_break_even_hours,
            }
        )
        scenario_rank_cfg = FundingRankConfig(
            min_funding_rate=backtest_cfg.min_funding_rate,
            min_funding_observations=backtest_cfg.min_funding_observations,
            min_funding_positive_ratio=backtest_cfg.min_funding_positive_ratio,
            min_funding_persistence_score=backtest_cfg.min_funding_persistence_score,
            max_spot_spread_bps=backtest_cfg.max_spot_spread_bps,
            max_perp_spread_bps=backtest_cfg.max_perp_spread_bps,
            max_abs_basis_bps=backtest_cfg.max_abs_basis_bps,
            min_basis_bps=backtest_cfg.min_basis_bps,
            min_expected_net_carry_bps=backtest_cfg.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=backtest_cfg.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=backtest_cfg.basis_risk_multiplier,
            spread_risk_multiplier=backtest_cfg.spread_risk_multiplier,
            max_break_even_hours=max_break_even_hours,
            min_regime_observations=backtest_cfg.min_regime_observations,
            min_perp_volume_24h_quote=backtest_cfg.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=backtest_cfg.min_spot_top_notional_quote,
            max_basis_std_bps=backtest_cfg.max_basis_std_bps,
            max_avg_spot_spread_bps=backtest_cfg.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=backtest_cfg.max_avg_perp_spread_bps,
        )
        ranked = rank_funding_rows(repriced_rows, top_n=sensitivity_cfg.top_n, cfg=scenario_rank_cfg)
        backtest = run_funding_backtest(repriced_rows, scenario_backtest_cfg)
        acceptance = evaluate_funding_backtest_metrics(backtest["metrics"], acceptance_cfg, stress_cfg)
        oos = (
            run_funding_oos_backtest(
                repriced_rows,
                backtest_cfg=scenario_backtest_cfg,
                acceptance_cfg=acceptance_cfg,
                oos_cfg=oos_cfg,
                stress_cfg=stress_cfg,
            )
            if oos_cfg is not None
            else None
        )
        walk_forward = (
            run_funding_walk_forward_backtest(
                repriced_rows,
                backtest_cfg=scenario_backtest_cfg,
                acceptance_cfg=acceptance_cfg,
                walk_cfg=walk_forward_cfg,
                stress_cfg=stress_cfg,
            )
            if walk_forward_cfg is not None
            else None
        )
        research_reasons: list[str] = []
        stress_reasons = [reason for reason in acceptance.get("reasons", []) if str(reason).startswith("stress_")]
        if not bool(acceptance.get("accepted")):
            research_reasons.append("full_backtest_rejected")
        if not oos_enabled:
            research_reasons.append("oos_required")
        elif not bool(oos and oos.get("accepted")):
            research_reasons.append("oos_rejected")
        if not walk_forward_enabled:
            research_reasons.append("walk_forward_required")
        elif not bool(walk_forward and walk_forward.get("accepted")):
            research_reasons.append("walk_forward_rejected")
        if not stress_enabled:
            research_reasons.append("stress_required")
        elif not stress_assumptions_passed:
            research_reasons.append("stress_assumptions_required")
        elif stress_reasons:
            research_reasons.append("stress_rejected")
        research_acceptance = {
            "accepted": not research_reasons,
            "reasons": research_reasons,
            "full_backtest_accepted": bool(acceptance.get("accepted")),
            "oos_required_passed": oos_enabled,
            "oos_accepted": None if oos is None else bool(oos.get("accepted")),
            "walk_forward_required_passed": walk_forward_enabled,
            "walk_forward_accepted": None if walk_forward is None else bool(walk_forward.get("accepted")),
            "stress_required_passed": stress_enabled,
            "stress_assumptions_passed": stress_assumptions_passed,
            "stress_accepted": None if not stress_enabled else bool(stress_assumptions_passed and not stress_reasons),
        }
        scenario = {
            "scenario": {
                "spot_fee_bps": spot_fee_bps,
                "perp_fee_bps": perp_fee_bps,
                "slippage_bps": slippage_bps,
                "target_hold_intervals": target_hold_intervals,
                "max_break_even_hours": max_break_even_hours,
                "round_trip_cost_bps": _round_trip_cost_bps(spot_fee_bps, perp_fee_bps, slippage_bps),
            },
            "rank_summary": {
                "ranked_rows": len(ranked),
                "rank_eligible": sum(1 for row in ranked if row.get("rank_eligible")),
                "persistence_eligible": sum(1 for row in ranked if row.get("persistence_eligible")),
            },
            "metrics": backtest["metrics"],
            "accepted": bool(research_acceptance["accepted"]),
            "acceptance": acceptance,
            "research_acceptance": research_acceptance,
            "top": ranked[: min(5, len(ranked))],
        }
        if oos is not None:
            scenario["oos"] = _funding_oos_result_summary(oos)
        if walk_forward is not None:
            scenario["walk_forward"] = _funding_walk_forward_result_summary(walk_forward)
        scenarios.append(scenario)
    scenarios.sort(
        key=lambda item: (
            bool(item.get("accepted")),
            _optional_gate_sort_value((item.get("research_acceptance") or {}).get("oos_accepted")),
            _optional_gate_sort_value((item.get("research_acceptance") or {}).get("walk_forward_accepted")),
            _row_float(((item.get("walk_forward") or {}).get("summary") or {}), "avg_test_net_pnl_quote", -1e9),
            _row_float(((item.get("walk_forward") or {}).get("summary") or {}), "worst_test_net_pnl_quote", -1e9),
            _row_float(((item.get("oos") or {}).get("out_of_sample_metrics") or {}), "net_pnl_quote", -1e9),
            _row_float(item["metrics"], "net_pnl_quote", -1e9),
            _row_float(item["metrics"], "expectancy_quote", -1e9),
            int(item["metrics"].get("total_trades") or 0),
            int(item["rank_summary"].get("rank_eligible") or 0),
        ),
        reverse=True,
    )
    return {
        "mode": "funding_sensitivity",
        "config": sensitivity_cfg.__dict__,
        "backtest_config": backtest_cfg.__dict__,
        "acceptance_config": acceptance_cfg.__dict__,
        "stress_config": stress_cfg.__dict__,
        "oos_config": None if oos_cfg is None else oos_cfg.__dict__,
        "walk_forward_config": None if walk_forward_cfg is None else walk_forward_cfg.__dict__,
        "summary": {
            "input_rows": len(rows),
            "markets": len({_funding_market_key(row) for row in rows}),
            "scenarios": len(scenarios),
            "accepted_scenarios": sum(1 for scenario in scenarios if scenario.get("accepted")),
            "oos_enabled": oos_enabled,
            "oos_accepted_scenarios": sum(
                1 for scenario in scenarios if bool((scenario.get("research_acceptance") or {}).get("oos_accepted"))
            )
            if oos_enabled
            else None,
            "best_net_pnl_quote": max((_row_float(scenario["metrics"], "net_pnl_quote", -1e9) for scenario in scenarios), default=0.0),
            "best_oos_net_pnl_quote": max(
                (
                    _row_float(((scenario.get("oos") or {}).get("out_of_sample_metrics") or {}), "net_pnl_quote", -1e9)
                    for scenario in scenarios
                ),
                default=0.0,
            )
            if oos_enabled
            else None,
            "walk_forward_enabled": walk_forward_enabled,
            "walk_forward_accepted_scenarios": sum(
                1 for scenario in scenarios if bool((scenario.get("research_acceptance") or {}).get("walk_forward_accepted"))
            )
            if walk_forward_enabled
            else None,
            "stress_enabled": stress_enabled,
            "stress_assumptions_passed": stress_assumptions_passed,
            "stress_accepted_scenarios": sum(
                1 for scenario in scenarios if bool((scenario.get("research_acceptance") or {}).get("stress_accepted"))
            )
            if stress_enabled
            else None,
            "best_walk_forward_avg_test_net_pnl_quote": max(
                (
                    _row_float(((scenario.get("walk_forward") or {}).get("summary") or {}), "avg_test_net_pnl_quote", -1e9)
                    for scenario in scenarios
                ),
                default=0.0,
            )
            if walk_forward_enabled
            else None,
            "best_walk_forward_worst_test_net_pnl_quote": max(
                (
                    _row_float(((scenario.get("walk_forward") or {}).get("summary") or {}), "worst_test_net_pnl_quote", -1e9)
                    for scenario in scenarios
                ),
                default=0.0,
            )
            if walk_forward_enabled
            else None,
            "best_rank_eligible": max((int(scenario["rank_summary"].get("rank_eligible") or 0) for scenario in scenarios), default=0),
        },
        "scenarios": scenarios,
    }


def run_funding_sensitivity_file(
    input_path: str | Path,
    output_path: str | Path,
    sensitivity_cfg: FundingSensitivityConfig,
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig | None = None,
    stress_cfg: FundingStressConfig | None = None,
    oos_cfg: FundingOosConfig | None = None,
    walk_forward_cfg: FundingWalkForwardConfig | None = None,
) -> dict[str, Any]:
    rows = load_funding_rows(input_path)
    payload = run_funding_sensitivity(
        rows,
        sensitivity_cfg=sensitivity_cfg,
        backtest_cfg=backtest_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        oos_cfg=oos_cfg,
        walk_forward_cfg=walk_forward_cfg,
    )
    payload["input"] = str(input_path)
    payload["output"] = str(output_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_funding_oos_backtest(
    rows: list[dict[str, Any]],
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig,
    oos_cfg: FundingOosConfig | None = None,
    stress_cfg: FundingStressConfig | None = None,
) -> dict[str, Any]:
    oos_cfg = oos_cfg or FundingOosConfig()
    stress_cfg = stress_cfg or FundingStressConfig()
    ordered = sorted(rows, key=lambda item: float(item.get("ts") or 0.0))
    split = _funding_oos_split_index(len(ordered), oos_cfg)
    if split is None:
        return {
            "ok": False,
            "mode": "funding_oos_backtest",
            "status": "insufficient_rows",
            "accepted": False,
            "split": {
                "total_rows": len(ordered),
                "train_rows": 0,
                "oos_rows": 0,
                "train_fraction": oos_cfg.train_fraction,
                "min_train_rows": oos_cfg.min_train_rows,
                "min_oos_rows": oos_cfg.min_oos_rows,
            },
            "config": backtest_cfg.__dict__,
            "acceptance_config": acceptance_cfg.__dict__,
            "oos_config": oos_cfg.__dict__,
            "stress_config": stress_cfg.__dict__,
        }
    train_rows = ordered[:split]
    oos_rows = ordered[split:]
    in_sample = run_funding_backtest(train_rows, backtest_cfg)
    out_of_sample = run_funding_backtest(oos_rows, backtest_cfg)
    in_acceptance = evaluate_funding_backtest_metrics(in_sample["metrics"], acceptance_cfg, stress_cfg)
    oos_acceptance = evaluate_funding_backtest_metrics(out_of_sample["metrics"], acceptance_cfg, stress_cfg)
    coverage = _funding_oos_coverage(train_rows, oos_rows, oos_cfg)
    coverage_acceptance = _funding_oos_coverage_acceptance(coverage)
    accepted = bool(in_acceptance["accepted"] and oos_acceptance["accepted"] and coverage_acceptance["accepted"])
    return {
        "ok": True,
        "mode": "funding_oos_backtest",
        "status": "completed",
        "accepted": accepted,
        "split": {
            "total_rows": len(ordered),
            "train_rows": len(train_rows),
            "oos_rows": len(oos_rows),
            "train_fraction": oos_cfg.train_fraction,
            "min_train_rows": oos_cfg.min_train_rows,
            "min_oos_rows": oos_cfg.min_oos_rows,
            "min_train_span_hours": oos_cfg.min_train_span_hours,
            "min_oos_span_hours": oos_cfg.min_oos_span_hours,
            "split_ts": float(oos_rows[0].get("ts") or 0.0) if oos_rows else None,
        },
        "coverage": coverage,
        "coverage_acceptance": coverage_acceptance,
        "config": backtest_cfg.__dict__,
        "acceptance_config": acceptance_cfg.__dict__,
        "oos_config": oos_cfg.__dict__,
        "stress_config": stress_cfg.__dict__,
        "in_sample": in_sample,
        "out_of_sample": out_of_sample,
        "in_sample_acceptance": in_acceptance,
        "out_of_sample_acceptance": oos_acceptance,
    }


def run_funding_oos_backtest_file(
    input_path: str | Path,
    output_path: str | Path,
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig,
    oos_cfg: FundingOosConfig | None = None,
    stress_cfg: FundingStressConfig | None = None,
) -> dict[str, Any]:
    rows = load_funding_rows(input_path)
    payload = run_funding_oos_backtest(rows, backtest_cfg, acceptance_cfg, oos_cfg, stress_cfg)
    payload["input"] = str(input_path)
    payload["output"] = str(output_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_funding_walk_forward_backtest(
    rows: list[dict[str, Any]],
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig,
    walk_cfg: FundingWalkForwardConfig | None = None,
    stress_cfg: FundingStressConfig | None = None,
) -> dict[str, Any]:
    walk_cfg = walk_cfg or FundingWalkForwardConfig()
    stress_cfg = stress_cfg or FundingStressConfig()
    ordered = sorted(rows, key=lambda item: float(item.get("ts") or 0.0))
    windows: list[dict[str, Any]] = []
    total_rows = len(ordered)
    train_rows_required = max(int(walk_cfg.train_rows), 1)
    test_rows_required = max(int(walk_cfg.test_rows), 1)
    step_rows = max(int(walk_cfg.step_rows), 1)
    if total_rows < train_rows_required + test_rows_required:
        return {
            "ok": False,
            "mode": "funding_walk_forward_backtest",
            "status": "insufficient_rows",
            "accepted": False,
            "summary": {
                "total_rows": total_rows,
                "windows": 0,
                "accepted_windows": 0,
                "accepted_ratio": 0.0,
                "min_windows": walk_cfg.min_windows,
                "min_accepted_windows": walk_cfg.min_accepted_windows,
                "min_accepted_ratio": walk_cfg.min_accepted_ratio,
            },
            "config": backtest_cfg.__dict__,
            "acceptance_config": acceptance_cfg.__dict__,
            "walk_forward_config": walk_cfg.__dict__,
            "stress_config": stress_cfg.__dict__,
            "windows": [],
        }

    for index, start in enumerate(range(0, total_rows - train_rows_required - test_rows_required + 1, step_rows), start=1):
        train = ordered[start : start + train_rows_required]
        test = ordered[start + train_rows_required : start + train_rows_required + test_rows_required]
        in_sample = run_funding_backtest(train, backtest_cfg)
        out_of_sample = run_funding_backtest(test, backtest_cfg)
        in_acceptance = evaluate_funding_backtest_metrics(in_sample["metrics"], acceptance_cfg, stress_cfg)
        oos_acceptance = evaluate_funding_backtest_metrics(out_of_sample["metrics"], acceptance_cfg, stress_cfg)
        coverage = _funding_oos_coverage(
            train,
            test,
            FundingOosConfig(
                min_train_span_hours=walk_cfg.min_train_span_hours,
                min_oos_span_hours=walk_cfg.min_test_span_hours,
            ),
        )
        coverage_acceptance = _funding_oos_coverage_acceptance(coverage)
        accepted = bool(in_acceptance["accepted"] and oos_acceptance["accepted"] and coverage_acceptance["accepted"])
        windows.append(
            {
                "index": index,
                "accepted": accepted,
                "train": {
                    "start_index": start,
                    "rows": len(train),
                    "first_ts": float(train[0].get("ts") or 0.0) if train else None,
                    "last_ts": float(train[-1].get("ts") or 0.0) if train else None,
                    "metrics": in_sample["metrics"],
                    "acceptance": in_acceptance,
                },
                "test": {
                    "start_index": start + train_rows_required,
                    "rows": len(test),
                    "first_ts": float(test[0].get("ts") or 0.0) if test else None,
                    "last_ts": float(test[-1].get("ts") or 0.0) if test else None,
                    "metrics": out_of_sample["metrics"],
                    "acceptance": oos_acceptance,
                },
                "coverage": coverage,
                "coverage_acceptance": coverage_acceptance,
            }
        )

    accepted_windows = sum(1 for window in windows if window.get("accepted"))
    accepted_ratio = accepted_windows / len(windows) if windows else 0.0
    reasons: list[str] = []
    if len(windows) < walk_cfg.min_windows:
        reasons.append("min_windows")
    if accepted_windows < walk_cfg.min_accepted_windows:
        reasons.append("min_accepted_windows")
    if accepted_ratio < walk_cfg.min_accepted_ratio:
        reasons.append("min_accepted_ratio")
    accepted = not reasons
    return {
        "ok": True,
        "mode": "funding_walk_forward_backtest",
        "status": "completed",
        "accepted": accepted,
        "reasons": reasons,
        "summary": {
            "total_rows": total_rows,
            "windows": len(windows),
            "accepted_windows": accepted_windows,
            "failed_windows": len(windows) - accepted_windows,
            "accepted_ratio": accepted_ratio,
            "min_windows": walk_cfg.min_windows,
            "min_accepted_windows": walk_cfg.min_accepted_windows,
            "min_accepted_ratio": walk_cfg.min_accepted_ratio,
            "best_test_net_pnl_quote": max(
                (_row_float(window["test"]["metrics"], "net_pnl_quote", -1e9) for window in windows),
                default=0.0,
            ),
            "worst_test_net_pnl_quote": min(
                (_row_float(window["test"]["metrics"], "net_pnl_quote", 1e9) for window in windows),
                default=0.0,
            ),
            "avg_test_net_pnl_quote": _avg([
                _row_float(window["test"]["metrics"], "net_pnl_quote", 0.0)
                for window in windows
            ])
            or 0.0,
            "avg_test_win_rate": _avg([
                _row_float(window["test"]["metrics"], "win_rate", 0.0)
                for window in windows
            ])
            or 0.0,
        },
        "config": backtest_cfg.__dict__,
        "acceptance_config": acceptance_cfg.__dict__,
        "walk_forward_config": walk_cfg.__dict__,
        "stress_config": stress_cfg.__dict__,
        "windows": windows,
    }


def run_funding_walk_forward_backtest_file(
    input_path: str | Path,
    output_path: str | Path,
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig,
    walk_cfg: FundingWalkForwardConfig | None = None,
    stress_cfg: FundingStressConfig | None = None,
) -> dict[str, Any]:
    rows = load_funding_rows(input_path)
    payload = run_funding_walk_forward_backtest(rows, backtest_cfg, acceptance_cfg, walk_cfg, stress_cfg)
    payload["input"] = str(input_path)
    payload["output"] = str(output_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def create_funding_paper_forward_plan_file(
    postprocess_path: str | Path,
    output_path: str | Path,
    paper_output_path: str | Path | None = None,
    decision_report_path: str | Path | None = None,
    min_forward_hours: float = 24.0,
    min_forward_rows: int = 20,
    min_forward_markets: int = 1,
) -> dict[str, Any]:
    src = Path(postprocess_path)
    payload = json.loads(src.read_text(encoding="utf-8"))
    research_acceptance = payload.get("research_acceptance") or {}
    source_data_quality = payload.get("data_quality")
    source_time_range = _funding_source_time_range(source_data_quality)
    decision = _load_json_artifact(decision_report_path)
    decision_summary = decision.get("summary", {}) if decision else {}
    gate_reasons = _funding_research_gate_reasons(research_acceptance) + _funding_data_quality_gate_reasons(source_data_quality, source_time_range)
    if decision_report_path is None:
        gate_reasons.append("decision_report_missing")
    elif decision is None:
        gate_reasons.append("decision_report_missing_or_invalid")
    elif decision_summary.get("accepted") is not True:
        gate_reasons.append("decision_report_not_accepted")
        gate_reasons.extend(f"decision:{reason}" for reason in decision_summary.get("reasons") or [])
    accepted = bool(research_acceptance.get("accepted")) and decision_summary.get("accepted") is True and not gate_reasons
    status = "ready_for_paper_forward" if accepted else "research_not_accepted"
    if bool(research_acceptance.get("accepted")) and decision is None:
        status = "decision_report_required"
    elif bool(research_acceptance.get("accepted")) and decision_summary.get("accepted") is not True:
        status = "decision_report_not_accepted"
    elif bool(research_acceptance.get("accepted")) and gate_reasons:
        status = "research_gate_evidence_missing"
    paper_output = Path(paper_output_path) if paper_output_path else Path(output_path).with_suffix(".jsonl")
    plan = {
        "mode": "funding_paper_forward_plan",
        "ok": accepted,
        "status": status,
        "ready_for_paper_forward": accepted,
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "min_forward_hours": min_forward_hours,
        "min_forward_rows": min_forward_rows,
        "min_forward_markets": min_forward_markets,
        "source_postprocess": str(src),
        "source_decision_report": str(decision_report_path) if decision_report_path else None,
        "source_input": payload.get("input"),
        "source_data_quality": source_data_quality,
        "source_time_range": source_time_range,
        "rank_output": payload.get("rank_output"),
        "backtest_output": payload.get("backtest_output"),
        "oos_output": payload.get("oos_output"),
        "walk_forward_output": payload.get("walk_forward_output"),
        "paper_output_path": str(paper_output),
        "research_acceptance": research_acceptance,
        "research_gate_reasons": gate_reasons,
        "decision_summary": decision_summary if decision else None,
        "acceptance": payload.get("acceptance"),
        "oos": payload.get("oos"),
        "walk_forward": payload.get("walk_forward"),
        "frozen_config": {
            "backtest_config": payload.get("backtest_config"),
            "acceptance_config": payload.get("acceptance_config"),
            "stress_config": payload.get("stress_config"),
            "rank_config": payload.get("rank_config"),
            "walk_forward_config": payload.get("walk_forward_config"),
        },
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["output"] = str(target)
    return plan


def create_blocked_funding_paper_forward_plan_file(
    postprocess_path: str | Path,
    decision_report_path: str | Path,
    output_path: str | Path,
    *,
    decision_summary: dict[str, Any],
    paper_output_path: str | Path | None = None,
    min_forward_hours: float = 24.0,
    min_forward_rows: int = 20,
    min_forward_markets: int = 1,
) -> dict[str, Any]:
    paper_output = Path(paper_output_path) if paper_output_path else Path(output_path).with_suffix(".jsonl")
    reasons = ["decision_not_accepted", *[str(reason) for reason in decision_summary.get("reasons") or []]]
    plan = {
        "mode": "funding_paper_forward_plan",
        "ok": False,
        "status": "blocked_by_decision_report",
        "ready_for_paper_forward": False,
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "min_forward_hours": min_forward_hours,
        "min_forward_rows": min_forward_rows,
        "min_forward_markets": min_forward_markets,
        "source_postprocess": str(postprocess_path),
        "source_decision_report": str(decision_report_path),
        "paper_output_path": str(paper_output),
        "decision_summary": decision_summary,
        "research_acceptance": {"accepted": False, "reasons": reasons},
        "research_gate_reasons": reasons,
        "frozen_config": None,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["output"] = str(target)
    return plan


def run_funding_paper_forward_file(
    plan_path: str | Path,
    input_path: str | Path,
    output_path: str | Path | None = None,
    summary_output_path: str | Path | None = None,
    allow_source_input: bool = False,
) -> dict[str, Any]:
    plan_src = Path(plan_path)
    data_src = Path(input_path)
    plan = json.loads(plan_src.read_text(encoding="utf-8"))
    target = Path(output_path or plan.get("paper_output_path") or data_src.with_suffix(".paper_forward.jsonl"))
    summary_target = Path(summary_output_path) if summary_output_path else default_funding_paper_forward_summary_path(target)

    if not bool(plan.get("ready_for_paper_forward")):
        summary = _funding_paper_forward_summary(
            ok=False,
            status="plan_not_ready",
            plan_path=plan_src,
            input_path=data_src,
            output_path=target,
            plan=plan,
            message="Paper-forward requires an accepted research plan.",
        )
        summary["summary_output"] = str(summary_target)
        _write_funding_paper_forward_records(target, [summary])
        _write_json(summary_target, summary)
        return summary

    gate_reasons = _funding_paper_forward_plan_gate_reasons(plan)
    if gate_reasons["all"]:
        status = "plan_safety_gate_failed" if gate_reasons["safety"] else "plan_research_gate_failed"
        summary = _funding_paper_forward_summary(
            ok=False,
            status=status,
            plan_path=plan_src,
            input_path=data_src,
            output_path=target,
            plan=plan,
            message="Paper-forward plan failed safety or research-evidence validation.",
        )
        summary["summary_output"] = str(summary_target)
        summary["plan_gate_reasons"] = gate_reasons["all"]
        summary["plan_safety_reasons"] = gate_reasons["safety"]
        summary["plan_research_gate_reasons"] = gate_reasons["research"]
        summary["paper_acceptance"] = {"accepted": False, "reasons": gate_reasons["all"]}
        _write_funding_paper_forward_records(target, [summary])
        _write_json(summary_target, summary)
        return summary

    source_input = plan.get("source_input")
    if source_input and not allow_source_input and _same_path(data_src, Path(str(source_input))):
        summary = _funding_paper_forward_summary(
            ok=False,
            status="source_input_reuse_blocked",
            plan_path=plan_src,
            input_path=data_src,
            output_path=target,
            plan=plan,
            message="Paper-forward input must be separate from the in-sample research input.",
        )
        summary["summary_output"] = str(summary_target)
        _write_funding_paper_forward_records(target, [summary])
        _write_json(summary_target, summary)
        return summary

    rows = load_funding_rows(data_src)
    temporal_gate = _funding_paper_forward_temporal_gate(rows, plan)
    if not bool(temporal_gate["accepted"]):
        summary = _funding_paper_forward_summary(
            ok=False,
            status="source_time_overlap_blocked",
            plan_path=plan_src,
            input_path=data_src,
            output_path=target,
            plan=plan,
            message="Paper-forward input must start after the research source time range.",
        )
        summary["summary_output"] = str(summary_target)
        summary["temporal_gate"] = temporal_gate
        summary["paper_acceptance"] = {"accepted": False, "reasons": temporal_gate["reasons"]}
        _write_funding_paper_forward_records(target, [summary])
        _write_json(summary_target, summary)
        return summary

    frozen = plan.get("frozen_config") or {}
    backtest_cfg = _dataclass_from_dict(FundingBacktestConfig, frozen.get("backtest_config") or {})
    acceptance_cfg = _dataclass_from_dict(FundingAcceptanceConfig, frozen.get("acceptance_config") or {})
    stress_cfg = _dataclass_from_dict(FundingStressConfig, frozen.get("stress_config") or {})
    backtest = run_funding_backtest(rows, backtest_cfg)
    backtest_acceptance = evaluate_funding_backtest_metrics(backtest["metrics"], acceptance_cfg, stress_cfg)
    coverage = _funding_forward_coverage(rows, plan)
    acceptance = _funding_paper_forward_acceptance(backtest_acceptance, coverage)
    summary = _funding_paper_forward_summary(
        ok=True,
        status="completed",
        plan_path=plan_src,
        input_path=data_src,
        output_path=target,
        plan=plan,
        metrics=backtest["metrics"],
        paper_acceptance=acceptance,
        coverage=coverage,
        frozen_config={
            "backtest_config": backtest_cfg.__dict__,
            "acceptance_config": acceptance_cfg.__dict__,
            "stress_config": stress_cfg.__dict__,
        },
    )
    summary["summary_output"] = str(summary_target)
    records = [
        {
            "event": "start",
            "mode": "funding_paper_forward",
            "ts": time.time(),
            "plan": str(plan_src),
            "input": str(data_src),
            "output": str(target),
            "research_only": True,
            "live_orders": False,
            "api_keys_required": False,
            "leverage_enabled": False,
            "margin_execution": False,
            "frozen_config": summary["frozen_config"],
        }
    ]
    records.extend({"event": "trade", **trade} for trade in backtest["trades"])
    records.append({"event": "summary", **summary})
    _write_funding_paper_forward_records(target, records)
    _write_json(summary_target, summary)
    return summary


def run_funding_postprocess_file(
    input_path: str | Path,
    manifest_path: str | Path | None,
    rank_output_path: str | Path,
    backtest_output_path: str | Path,
    rank_cfg: FundingRankConfig,
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig | None = None,
    stress_cfg: FundingStressConfig | None = None,
    oos_output_path: str | Path | None = None,
    oos_cfg: FundingOosConfig | None = None,
    walk_forward_output_path: str | Path | None = None,
    walk_forward_cfg: FundingWalkForwardConfig | None = None,
    data_quality_cfg: FundingDataQualityConfig | None = None,
    top_n: int = 20,
    require_final: bool = True,
) -> dict[str, Any]:
    src = Path(input_path)
    manifest = _load_funding_manifest(manifest_path)
    if require_final:
        if not manifest_path:
            return {
                "ok": False,
                "status": "manifest_required",
                "input": str(src),
                "manifest": None,
                "manifest_summary": None,
                "message": "Manifest is required for funding postprocess; rank/backtest were not run.",
            }
        if manifest is None:
            return {
                "ok": False,
                "status": "manifest_missing",
                "input": str(src),
                "manifest": str(manifest_path),
                "manifest_summary": None,
                "message": "Manifest was not found; rank/backtest were not run.",
            }
        if not bool(manifest.get("final")):
            return {
                "ok": False,
                "status": "not_final",
                "input": str(src),
                "manifest": str(manifest_path),
                "manifest_summary": _funding_manifest_summary(manifest),
                "message": "Manifest is not final; funding postprocess was not run.",
            }
        collect_status = funding_collect_status(src, manifest_path=manifest_path, stale_after_sec=1e18)
        if not collect_status["line_count_matches_manifest"]:
            return {
                "ok": False,
                "status": "line_count_mismatch",
                "input": str(src),
                "manifest": str(manifest_path),
                "manifest_summary": _funding_manifest_summary(manifest),
                "collect_status": collect_status,
                "message": "Funding output line count does not match manifest rows; rank/backtest were not run.",
            }
        rows_for_quality = load_funding_rows(src)
        data_quality = evaluate_funding_data_quality(rows_for_quality, manifest, data_quality_cfg or FundingDataQualityConfig())
        if not bool(data_quality["accepted"]):
            return {
                "ok": False,
                "status": "data_quality_rejected",
                "input": str(src),
                "manifest": str(manifest_path),
                "manifest_summary": _funding_manifest_summary(manifest),
                "collect_status": collect_status,
                "data_quality": data_quality,
                "message": "Funding data quality gate rejected the dataset; rank/backtest were not run.",
            }

    rank = rank_funding_file(src, output_path=rank_output_path, top_n=top_n, cfg=rank_cfg)
    backtest = run_funding_backtest_file(src, backtest_output_path, backtest_cfg)
    acceptance_cfg = acceptance_cfg or FundingAcceptanceConfig()
    stress_cfg = stress_cfg or FundingStressConfig()
    acceptance = evaluate_funding_backtest_metrics(backtest["metrics"], acceptance_cfg, stress_cfg)
    oos = None
    if oos_output_path is not None:
        oos = run_funding_oos_backtest_file(
            src,
            oos_output_path,
            backtest_cfg=backtest_cfg,
            acceptance_cfg=acceptance_cfg,
            oos_cfg=oos_cfg,
            stress_cfg=stress_cfg,
        )
    walk_forward = None
    if walk_forward_output_path is not None:
        walk_forward = run_funding_walk_forward_backtest_file(
            src,
            walk_forward_output_path,
            backtest_cfg=backtest_cfg,
            acceptance_cfg=acceptance_cfg,
            walk_cfg=walk_forward_cfg,
            stress_cfg=stress_cfg,
        )
    research_reasons: list[str] = []
    stress_enabled = bool(stress_cfg.enabled)
    stress_assumptions_passed = _funding_stress_assumptions_passed(stress_cfg)
    stress_reasons = [reason for reason in acceptance.get("reasons", []) if str(reason).startswith("stress_")]
    if not bool(acceptance["accepted"]):
        research_reasons.append("full_backtest_rejected")
    if oos is None:
        research_reasons.append("oos_required")
    elif not bool(oos.get("accepted")):
        research_reasons.append("oos_rejected")
    if walk_forward is None:
        research_reasons.append("walk_forward_required")
    elif not bool(walk_forward.get("accepted")):
        research_reasons.append("walk_forward_rejected")
    if not stress_enabled:
        research_reasons.append("stress_required")
    elif not stress_assumptions_passed:
        research_reasons.append("stress_assumptions_required")
    elif stress_reasons:
        research_reasons.append("stress_rejected")
    research_acceptance = {
        "accepted": not research_reasons,
        "reasons": research_reasons,
        "full_backtest_accepted": bool(acceptance["accepted"]),
        "oos_required_passed": oos is not None,
        "oos_accepted": None if oos is None else bool(oos.get("accepted")),
        "walk_forward_required_passed": walk_forward is not None,
        "walk_forward_accepted": None if walk_forward is None else bool(walk_forward.get("accepted")),
        "stress_required_passed": stress_enabled,
        "stress_assumptions_passed": stress_assumptions_passed,
        "stress_accepted": None if not stress_enabled else bool(stress_assumptions_passed and not stress_reasons),
    }
    payload = {
        "ok": True,
        "status": "completed",
        "input": str(src),
        "manifest": str(manifest_path) if manifest_path else None,
        "manifest_summary": _funding_manifest_summary(manifest) if manifest else None,
        "rank_output": str(rank_output_path),
        "backtest_output": str(backtest_output_path),
        "oos_output": str(oos_output_path) if oos_output_path is not None else None,
        "walk_forward_output": str(walk_forward_output_path) if walk_forward_output_path is not None else None,
        "rank_summary": rank["summary"],
        "backtest_metrics": backtest["metrics"],
        "acceptance": acceptance,
        "research_acceptance": research_acceptance,
        "data_quality": evaluate_funding_data_quality(load_funding_rows(src), manifest, data_quality_cfg or FundingDataQualityConfig())
        if manifest
        else None,
        "rank_config": rank_cfg.__dict__,
        "backtest_config": backtest_cfg.__dict__,
        "acceptance_config": acceptance_cfg.__dict__,
        "stress_config": stress_cfg.__dict__,
        "walk_forward_config": None if walk_forward_cfg is None else walk_forward_cfg.__dict__,
        "data_quality_config": (data_quality_cfg or FundingDataQualityConfig()).__dict__,
    }
    if oos is not None:
        payload["oos"] = {
            "ok": oos["ok"],
            "status": oos["status"],
            "accepted": oos["accepted"],
            "split": oos["split"],
            "coverage": oos.get("coverage"),
            "coverage_acceptance": oos.get("coverage_acceptance"),
            "in_sample_acceptance": oos.get("in_sample_acceptance"),
            "out_of_sample_acceptance": oos.get("out_of_sample_acceptance"),
        }
    if walk_forward is not None:
        payload["walk_forward"] = {
            "ok": walk_forward["ok"],
            "status": walk_forward["status"],
            "accepted": walk_forward["accepted"],
            "reasons": walk_forward.get("reasons", []),
            "summary": walk_forward.get("summary"),
        }
    return payload


def run_funding_research_finalize_file(
    input_path: str | Path,
    manifest_path: str | Path,
    postprocess_output_path: str | Path,
    rank_output_path: str | Path,
    backtest_output_path: str | Path,
    oos_output_path: str | Path | None,
    walk_forward_output_path: str | Path | None,
    paper_plan_output_path: str | Path,
    paper_output_path: str | Path | None,
    rank_cfg: FundingRankConfig,
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig,
    stress_cfg: FundingStressConfig,
    oos_cfg: FundingOosConfig,
    walk_forward_cfg: FundingWalkForwardConfig | None = None,
    data_quality_cfg: FundingDataQualityConfig | None = None,
    top_n: int = 20,
    min_forward_hours: float = 24.0,
    min_forward_rows: int = 20,
    min_forward_markets: int = 1,
    create_paper_plan: bool = False,
    decision_report_path: str | Path | None = None,
) -> dict[str, Any]:
    src = Path(input_path)
    manifest = Path(manifest_path)
    postprocess_out = Path(postprocess_output_path)
    paper_plan_out = Path(paper_plan_output_path)
    collect_status = funding_collect_status(src, manifest_path=manifest, stale_after_sec=1e18)
    if not bool(collect_status.get("ready_for_postprocess")):
        return {
            "ok": False,
            "mode": "funding_research_finalize",
            "status": "not_ready_for_postprocess",
            "input": str(src),
            "manifest": str(manifest),
            "collect_status": collect_status,
            "postprocess_output": str(postprocess_out),
            "paper_plan_output": str(paper_plan_out),
            "message": "Funding collect is not ready for final postprocess.",
        }
    if oos_output_path is None:
        return {
            "ok": False,
            "mode": "funding_research_finalize",
            "status": "oos_output_required",
            "input": str(src),
            "manifest": str(manifest),
            "collect_status": collect_status,
            "message": "OOS output path is required for research finalization.",
        }
    if walk_forward_output_path is None:
        return {
            "ok": False,
            "mode": "funding_research_finalize",
            "status": "walk_forward_output_required",
            "input": str(src),
            "manifest": str(manifest),
            "collect_status": collect_status,
            "message": "Walk-forward output path is required for research finalization.",
        }
    if not bool(stress_cfg.enabled):
        return {
            "ok": False,
            "mode": "funding_research_finalize",
            "status": "stress_required",
            "input": str(src),
            "manifest": str(manifest),
            "collect_status": collect_status,
            "message": "Stress gate must be enabled for research finalization.",
        }
    if not _funding_stress_assumptions_passed(stress_cfg):
        return {
            "ok": False,
            "mode": "funding_research_finalize",
            "status": "stress_assumptions_required",
            "input": str(src),
            "manifest": str(manifest),
            "collect_status": collect_status,
            "message": "At least one stress assumption must be non-zero.",
        }

    postprocess = run_funding_postprocess_file(
        input_path=src,
        manifest_path=manifest,
        rank_output_path=rank_output_path,
        backtest_output_path=backtest_output_path,
        rank_cfg=rank_cfg,
        backtest_cfg=backtest_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        oos_output_path=oos_output_path,
        oos_cfg=oos_cfg,
        walk_forward_output_path=walk_forward_output_path,
        walk_forward_cfg=walk_forward_cfg,
        data_quality_cfg=data_quality_cfg,
        top_n=top_n,
        require_final=True,
    )
    postprocess["postprocess_output"] = str(postprocess_out)
    postprocess_out.parent.mkdir(parents=True, exist_ok=True)
    postprocess_out.write_text(json.dumps(postprocess, ensure_ascii=False, indent=2), encoding="utf-8")

    paper_plan: dict[str, Any] | None = None
    if create_paper_plan and bool((postprocess.get("research_acceptance") or {}).get("accepted")):
        paper_plan = create_funding_paper_forward_plan_file(
            postprocess_out,
            paper_plan_out,
            paper_output_path=paper_output_path,
            decision_report_path=decision_report_path,
            min_forward_hours=min_forward_hours,
            min_forward_rows=min_forward_rows,
            min_forward_markets=min_forward_markets,
        )

    return {
        "ok": bool(postprocess.get("ok")),
        "mode": "funding_research_finalize",
        "status": "completed" if bool(postprocess.get("ok")) else postprocess.get("status", "postprocess_failed"),
        "input": str(src),
        "manifest": str(manifest),
        "collect_status": collect_status,
        "postprocess_output": str(postprocess_out),
        "rank_output": str(rank_output_path),
        "backtest_output": str(backtest_output_path),
        "oos_output": str(oos_output_path),
        "walk_forward_output": str(walk_forward_output_path),
        "paper_plan_output": str(paper_plan_out),
        "paper_plan_created": paper_plan is not None and bool(paper_plan.get("ready_for_paper_forward")),
        "paper_plan_creation_deferred": not create_paper_plan,
        "postprocess": postprocess,
        "research_acceptance": postprocess.get("research_acceptance"),
        "paper_plan": paper_plan,
    }


def _funding_final_review_metric_summary(finalize: dict[str, Any], collect_status: dict[str, Any]) -> dict[str, Any]:
    postprocess = finalize.get("postprocess") if isinstance(finalize.get("postprocess"), dict) else {}
    backtest_metrics = postprocess.get("backtest_metrics") if isinstance(postprocess.get("backtest_metrics"), dict) else {}
    data_quality = postprocess.get("data_quality") if isinstance(postprocess.get("data_quality"), dict) else collect_status.get("data_quality")
    data_quality = data_quality if isinstance(data_quality, dict) else {}
    research_acceptance = (
        postprocess.get("research_acceptance")
        if isinstance(postprocess.get("research_acceptance"), dict)
        else finalize.get("research_acceptance")
    )
    research_acceptance = research_acceptance if isinstance(research_acceptance, dict) else {}
    oos = postprocess.get("oos") if isinstance(postprocess.get("oos"), dict) else {}
    oos_split = oos.get("split") if isinstance(oos.get("split"), dict) else {}
    oos_out_acceptance = oos.get("out_of_sample_acceptance") if isinstance(oos.get("out_of_sample_acceptance"), dict) else {}
    oos_out_metrics = oos_out_acceptance.get("metrics") if isinstance(oos_out_acceptance.get("metrics"), dict) else {}
    walk_forward = postprocess.get("walk_forward") if isinstance(postprocess.get("walk_forward"), dict) else {}
    walk_summary = walk_forward.get("summary") if isinstance(walk_forward.get("summary"), dict) else {}
    return {
        "data_quality_accepted": data_quality.get("accepted"),
        "data_quality_metrics": data_quality.get("metrics"),
        "backtest_total_trades": backtest_metrics.get("total_trades"),
        "backtest_win_rate": backtest_metrics.get("win_rate"),
        "backtest_expectancy_quote": backtest_metrics.get("expectancy_quote"),
        "backtest_net_pnl_quote": backtest_metrics.get("net_pnl_quote"),
        "backtest_max_drawdown_quote": backtest_metrics.get("max_drawdown_quote"),
        "backtest_profit_factor": backtest_metrics.get("profit_factor"),
        "backtest_funding_pnl_quote": backtest_metrics.get("funding_pnl_quote"),
        "backtest_basis_pnl_quote": backtest_metrics.get("basis_pnl_quote"),
        "backtest_fees_quote": backtest_metrics.get("fees_quote"),
        "backtest_slippage_quote": backtest_metrics.get("slippage_quote"),
        "oos_accepted": oos.get("accepted"),
        "oos_train_rows": oos_split.get("train_rows"),
        "oos_rows": oos_split.get("oos_rows"),
        "oos_net_pnl_quote": oos_out_metrics.get("net_pnl_quote"),
        "oos_win_rate": oos_out_metrics.get("win_rate"),
        "oos_expectancy_quote": oos_out_metrics.get("expectancy_quote"),
        "oos_max_drawdown_quote": oos_out_metrics.get("max_drawdown_quote"),
        "walk_forward_accepted": walk_forward.get("accepted"),
        "walk_forward_windows": walk_summary.get("windows"),
        "walk_forward_accepted_windows": walk_summary.get("accepted_windows"),
        "walk_forward_avg_test_net_pnl_quote": walk_summary.get("avg_test_net_pnl_quote"),
        "walk_forward_worst_test_net_pnl_quote": walk_summary.get("worst_test_net_pnl_quote"),
        "stress_accepted": research_acceptance.get("stress_accepted"),
        "research_acceptance_accepted": research_acceptance.get("accepted"),
        "research_acceptance_reasons": research_acceptance.get("reasons"),
    }


def run_funding_final_review_file(
    input_path: str | Path,
    manifest_path: str | Path,
    output_path: str | Path,
    postprocess_output_path: str | Path,
    rank_output_path: str | Path,
    backtest_output_path: str | Path,
    oos_output_path: str | Path,
    walk_forward_output_path: str | Path,
    paper_plan_output_path: str | Path,
    paper_output_path: str | Path | None,
    gate_report_output_path: str | Path,
    frontier_report_output_path: str | Path,
    sensitivity_output_path: str | Path,
    decision_report_output_path: str | Path,
    rank_cfg: FundingRankConfig,
    backtest_cfg: FundingBacktestConfig,
    acceptance_cfg: FundingAcceptanceConfig,
    stress_cfg: FundingStressConfig,
    sensitivity_cfg: FundingSensitivityConfig,
    oos_cfg: FundingOosConfig,
    walk_forward_cfg: FundingWalkForwardConfig | None = None,
    data_quality_cfg: FundingDataQualityConfig | None = None,
    top_n: int = 20,
    min_forward_hours: float = 24.0,
    min_forward_rows: int = 20,
    min_forward_markets: int = 1,
    regime_report_output_path: str | Path | None = None,
) -> dict[str, Any]:
    src = Path(input_path)
    manifest = Path(manifest_path)
    out = Path(output_path)
    regime_report_path = (
        Path(regime_report_output_path)
        if regime_report_output_path
        else out.with_name(f"funding_regime_report_{src.stem}.json")
    )
    collect_status = funding_collect_status(
        src,
        manifest_path=manifest,
        stale_after_sec=1e18,
        data_quality_cfg=data_quality_cfg,
    )
    artifact_paths = {
        "postprocess": str(postprocess_output_path),
        "rank": str(rank_output_path),
        "backtest": str(backtest_output_path),
        "oos": str(oos_output_path),
        "walk_forward": str(walk_forward_output_path),
        "paper_plan": str(paper_plan_output_path),
        "paper_output": str(paper_output_path) if paper_output_path else None,
        "gate_report": str(gate_report_output_path),
        "regime_report": str(regime_report_path),
        "frontier_report": str(frontier_report_output_path),
        "sensitivity_report": str(sensitivity_output_path),
        "decision_report": str(decision_report_output_path),
    }
    if not bool(collect_status.get("ready_for_postprocess")):
        payload = {
            "ok": False,
            "mode": "funding_final_review",
            "status": "not_ready_for_postprocess",
            "research_only": True,
            "live_orders": False,
            "api_keys_required": False,
            "leverage_enabled": False,
            "margin_execution": False,
            "input": str(src),
            "manifest": str(manifest),
            "output": str(out),
            "collect_status": collect_status,
            "artifact_paths": artifact_paths,
            "artifacts_created": [],
            "summary": {
                "ready_for_postprocess": False,
                "accepted": False,
                "verdict": "wait_for_final_dataset",
                "next_action": "wait_and_recheck",
                "collector_status": collect_status.get("status"),
                "completed_cycles": collect_status.get("completed_cycles"),
                "expected_cycles": collect_status.get("expected_cycles"),
                "remaining_cycles": collect_status.get("remaining_cycles"),
                "progress_pct": collect_status.get("progress_pct"),
                "line_count": collect_status.get("line_count"),
                "errors": collect_status.get("errors"),
                "data_quality_accepted": (collect_status.get("data_quality") or {}).get("accepted"),
                "data_quality_reasons": (collect_status.get("data_quality") or {}).get("reasons"),
                "data_quality_metrics": (collect_status.get("data_quality") or {}).get("metrics"),
                "reasons": [
                    "collector_not_ready",
                    *[f"readiness:{reason}" for reason in collect_status.get("readiness", {}).get("reasons", [])],
                ],
            },
        }
        _write_json(out, payload)
        return payload

    finalize = run_funding_research_finalize_file(
        input_path=src,
        manifest_path=manifest,
        postprocess_output_path=postprocess_output_path,
        rank_output_path=rank_output_path,
        backtest_output_path=backtest_output_path,
        oos_output_path=oos_output_path,
        walk_forward_output_path=walk_forward_output_path,
        paper_plan_output_path=paper_plan_output_path,
        paper_output_path=paper_output_path,
        rank_cfg=rank_cfg,
        backtest_cfg=backtest_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        oos_cfg=oos_cfg,
        walk_forward_cfg=walk_forward_cfg,
        data_quality_cfg=data_quality_cfg,
        top_n=top_n,
        min_forward_hours=min_forward_hours,
        min_forward_rows=min_forward_rows,
        min_forward_markets=min_forward_markets,
        create_paper_plan=False,
    )

    gate = funding_gate_report_file(src, output_path=gate_report_output_path, top_n=top_n, cfg=rank_cfg)
    regime = funding_regime_report_file(src, output_path=regime_report_path, top_n=top_n, cfg=rank_cfg)
    frontier = funding_frontier_report_file(src, output_path=frontier_report_output_path, top_n=top_n, cfg=rank_cfg)
    sensitivity = run_funding_sensitivity_file(
        input_path=src,
        output_path=sensitivity_output_path,
        sensitivity_cfg=sensitivity_cfg,
        backtest_cfg=backtest_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        oos_cfg=oos_cfg,
        walk_forward_cfg=walk_forward_cfg,
    )
    decision = funding_decision_report(
        src,
        manifest_path=manifest,
        postprocess_report_path=postprocess_output_path,
        gate_report_path=gate_report_output_path,
        regime_report_path=regime_report_path,
        frontier_report_path=frontier_report_output_path,
        sensitivity_report_path=sensitivity_output_path,
        output_path=decision_report_output_path,
        stale_after_sec=1e18,
        data_quality_cfg=data_quality_cfg,
    )
    decision_summary = decision.get("summary", {})
    paper_plan: dict[str, Any]
    if bool(decision_summary.get("accepted")):
        paper_plan = create_funding_paper_forward_plan_file(
            postprocess_output_path,
            paper_plan_output_path,
            paper_output_path=paper_output_path,
            decision_report_path=decision_report_output_path,
            min_forward_hours=min_forward_hours,
            min_forward_rows=min_forward_rows,
            min_forward_markets=min_forward_markets,
        )
    else:
        paper_plan = create_blocked_funding_paper_forward_plan_file(
            postprocess_output_path,
            decision_report_output_path,
            paper_plan_output_path,
            decision_summary=decision_summary,
            paper_output_path=paper_output_path,
            min_forward_hours=min_forward_hours,
            min_forward_rows=min_forward_rows,
            min_forward_markets=min_forward_markets,
        )
    paper_plan_created = bool(paper_plan.get("ready_for_paper_forward"))
    payload = {
        "ok": bool(finalize.get("ok")),
        "mode": "funding_final_review",
        "status": "completed" if bool(finalize.get("ok")) else str(finalize.get("status") or "finalize_failed"),
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "input": str(src),
        "manifest": str(manifest),
        "output": str(out),
        "collect_status": collect_status,
        "artifact_paths": artifact_paths,
        "artifacts_created": [
            str(path)
            for path in (
                postprocess_output_path,
                rank_output_path,
                backtest_output_path,
                oos_output_path,
                walk_forward_output_path,
                paper_plan_output_path,
                gate_report_output_path,
                regime_report_path,
                frontier_report_output_path,
                sensitivity_output_path,
                decision_report_output_path,
            )
            if Path(path).exists()
        ],
        "summary": {
            "ready_for_postprocess": True,
            "accepted": bool(decision_summary.get("accepted")),
            "verdict": decision_summary.get("verdict"),
            "next_action": decision_summary.get("next_action"),
            "reasons": decision_summary.get("reasons") or [],
            "paper_plan_created": paper_plan_created,
            "paper_plan_status": paper_plan.get("status"),
            "gate_rank_eligible": decision_summary.get("gate_rank_eligible"),
            "regime_eligible_markets": regime.get("summary", {}).get("eligible_markets"),
            "regime_persistence_pass": regime.get("summary", {}).get("persistence_pass"),
            "regime_regime_pass": regime.get("summary", {}).get("regime_pass"),
            "regime_liquidity_pass": regime.get("summary", {}).get("liquidity_pass"),
            "regime_economics_pass": regime.get("summary", {}).get("economics_pass"),
            "frontier_strict_rank_eligible": decision_summary.get("frontier_strict_rank_eligible"),
            "frontier_funding_gap_pass": decision_summary.get("frontier_funding_gap_pass"),
            "sensitivity_accepted_scenarios": decision_summary.get("sensitivity_accepted_scenarios"),
            "sensitivity_stress_accepted_scenarios": decision_summary.get("sensitivity_stress_accepted_scenarios"),
            "best_net_pnl_quote": decision_summary.get("best_net_pnl_quote"),
            **_funding_final_review_metric_summary(finalize, collect_status),
        },
        "finalize": finalize,
        "gate_summary": gate.get("summary", {}),
        "regime_summary": regime.get("summary", {}),
        "frontier_summary": frontier.get("summary", {}),
        "sensitivity_summary": sensitivity.get("summary", {}),
        "decision_summary": decision_summary,
        "paper_plan": paper_plan,
    }
    _write_json(out, payload)
    return payload


def evaluate_funding_backtest_metrics(
    metrics: dict[str, Any],
    cfg: FundingAcceptanceConfig,
    stress_cfg: FundingStressConfig | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if int(metrics.get("total_trades") or 0) < cfg.min_trades:
        reasons.append("min_trades")
    if _row_float(metrics, "win_rate", 0.0) < cfg.min_win_rate:
        reasons.append("min_win_rate")
    if _row_float(metrics, "expectancy_quote", -1e9) < cfg.min_expectancy_quote:
        reasons.append("min_expectancy_quote")
    if _row_float(metrics, "net_pnl_quote", -1e9) < cfg.min_net_pnl_quote:
        reasons.append("min_net_pnl_quote")
    if _row_float(metrics, "max_drawdown_quote", 1e9) > cfg.max_drawdown_quote:
        reasons.append("max_drawdown_quote")
    profit_factor = metrics.get("profit_factor")
    if profit_factor is None:
        if int(metrics.get("total_trades") or 0) <= 0 or _row_float(metrics, "net_pnl_quote", 0.0) <= 0:
            reasons.append("min_profit_factor")
    elif _row_float(metrics, "profit_factor", -1e9) < cfg.min_profit_factor:
        reasons.append("min_profit_factor")
    traded_markets_value = metrics.get("traded_markets")
    if traded_markets_value is None:
        traded_markets_value = metrics.get("markets")
    if int(traded_markets_value or 0) < cfg.min_markets:
        reasons.append("min_markets")
    if _row_float(metrics, "max_market_trade_share", 0.0) > cfg.max_market_trade_share:
        reasons.append("max_market_trade_share")
    traded_exchanges_value = metrics.get("traded_exchanges")
    if traded_exchanges_value is None:
        exchange_counts = metrics.get("exchange_trade_counts")
        if isinstance(exchange_counts, dict):
            traded_exchanges_value = len(exchange_counts)
        elif int(metrics.get("total_trades") or 0) > 0:
            traded_exchanges_value = 1
        else:
            traded_exchanges_value = 0
    if int(traded_exchanges_value or 0) < cfg.min_exchanges:
        reasons.append("min_exchanges")
    if _row_float(metrics, "max_exchange_trade_share", 0.0) > cfg.max_exchange_trade_share:
        reasons.append("max_exchange_trade_share")
    if int(metrics.get("profitable_windows") or 0) < cfg.min_profitable_windows:
        reasons.append("min_profitable_windows")
    if _row_float(metrics, "max_window_pnl_share", 0.0) > cfg.max_window_pnl_share:
        reasons.append("max_window_pnl_share")
    stress = None
    if stress_cfg is not None and stress_cfg.enabled:
        stress = stress_funding_backtest_metrics(metrics, stress_cfg)
        if _row_float(stress, "stress_net_pnl_quote", -1e9) < stress_cfg.min_stress_net_pnl_quote:
            reasons.append("stress_min_net_pnl_quote")
        if _row_float(stress, "stress_max_drawdown_quote", 1e9) > stress_cfg.max_stress_drawdown_quote:
            reasons.append("stress_max_drawdown_quote")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "metrics": {
            "total_trades": metrics.get("total_trades"),
            "win_rate": metrics.get("win_rate"),
            "expectancy_quote": metrics.get("expectancy_quote"),
            "net_pnl_quote": metrics.get("net_pnl_quote"),
            "max_drawdown_quote": metrics.get("max_drawdown_quote"),
            "profit_factor": metrics.get("profit_factor"),
            "markets": metrics.get("markets"),
            "traded_markets": metrics.get("traded_markets"),
            "max_market_trade_share": metrics.get("max_market_trade_share"),
            "traded_exchanges": traded_exchanges_value,
            "max_exchange_trade_share": metrics.get("max_exchange_trade_share"),
            "active_windows": metrics.get("active_windows"),
            "profitable_windows": metrics.get("profitable_windows"),
            "max_window_pnl_share": metrics.get("max_window_pnl_share"),
        },
        "stress": stress,
        "config": cfg.__dict__,
        "stress_config": stress_cfg.__dict__ if stress_cfg else None,
    }


def evaluate_funding_data_quality(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any] | None,
    cfg: FundingDataQualityConfig,
) -> dict[str, Any]:
    row_count = len(rows)
    market_count = len({_funding_market_key(row) for row in rows})
    completed_cycles = int((manifest or {}).get("completed_cycles") or 0)
    errors = int((manifest or {}).get("errors") or 0)
    attempts = row_count + errors
    error_rate = errors / attempts if attempts > 0 else 0.0
    time_span = _funding_rows_time_span(rows)
    cycle_values = [
        int(value)
        for value in (_as_float(row.get("cycle")) for row in rows)
        if value is not None
    ]
    cycle_market_counts: Counter[tuple[int, str]] = Counter()
    rows_by_cycle: Counter[int] = Counter()
    for row in rows:
        cycle_value = _as_float(row.get("cycle"))
        if cycle_value is not None:
            cycle_int = int(cycle_value)
            rows_by_cycle[cycle_int] += 1
            cycle_market_counts[(cycle_int, _funding_market_key(row))] += 1
    unique_cycles = len(set(cycle_values))
    avg_rows_per_cycle = row_count / unique_cycles if unique_cycles > 0 else 0.0
    min_rows_per_cycle = min(rows_by_cycle.values(), default=0)
    cycle_market_duplicates = sum(max(0, count - 1) for count in cycle_market_counts.values())
    cycle_market_duplicate_rate = cycle_market_duplicates / row_count if row_count > 0 else 0.0
    required_field_presence: dict[str, float] = {}
    for field in cfg.required_row_fields:
        present = sum(1 for row in rows if row.get(field) is not None)
        required_field_presence[field] = present / row_count if row_count > 0 else 0.0
    reasons: list[str] = []
    if row_count < cfg.min_rows:
        reasons.append("min_rows")
    if market_count < cfg.min_markets:
        reasons.append("min_markets")
    if completed_cycles < cfg.min_completed_cycles:
        reasons.append("min_completed_cycles")
    if unique_cycles < cfg.min_unique_cycles:
        reasons.append("min_unique_cycles")
    if avg_rows_per_cycle < cfg.min_avg_rows_per_cycle:
        reasons.append("min_avg_rows_per_cycle")
    if min_rows_per_cycle < cfg.min_min_rows_per_cycle:
        reasons.append("min_min_rows_per_cycle")
    if error_rate > cfg.max_error_rate:
        reasons.append("max_error_rate")
    if cycle_market_duplicate_rate > cfg.max_cycle_market_duplicate_rate:
        reasons.append("max_cycle_market_duplicate_rate")
    for field, presence in required_field_presence.items():
        if presence < cfg.min_required_row_field_presence:
            reasons.append(f"required_row_field:{field}")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "metrics": {
            "rows": row_count,
            "markets": market_count,
            "completed_cycles": completed_cycles,
            "unique_cycles": unique_cycles,
            "avg_rows_per_cycle": avg_rows_per_cycle,
            "min_rows_per_cycle": min_rows_per_cycle,
            "errors": errors,
            "attempts": attempts,
            "error_rate": error_rate,
            "cycle_market_duplicates": cycle_market_duplicates,
            "cycle_market_duplicate_rate": cycle_market_duplicate_rate,
            "required_row_field_presence": required_field_presence,
            "first_ts": time_span["first_ts"],
            "last_ts": time_span["last_ts"],
            "span_sec": time_span["span_sec"],
            "span_hours": time_span["span_hours"],
        },
        "config": cfg.__dict__,
    }


def stress_funding_backtest_metrics(metrics: dict[str, Any], cfg: FundingStressConfig) -> dict[str, Any]:
    total_notional = _row_float(metrics, "total_notional_quote", 0.0)
    total_trades = int(metrics.get("total_trades") or 0)
    stress_cost_bps = max(cfg.adverse_basis_bps, 0.0) + (2.0 * max(cfg.spread_widen_bps, 0.0)) + max(cfg.funding_flip_bps, 0.0)
    stress_cost_quote = total_notional * stress_cost_bps / 1e4
    stress_net = _row_float(metrics, "net_pnl_quote", 0.0) - stress_cost_quote
    stress_drawdown = _row_float(metrics, "max_drawdown_quote", 0.0) + stress_cost_quote
    return {
        "stress_cost_bps": stress_cost_bps,
        "stress_cost_quote": stress_cost_quote,
        "stress_net_pnl_quote": stress_net,
        "stress_expectancy_quote": stress_net / total_trades if total_trades else 0.0,
        "stress_max_drawdown_quote": stress_drawdown,
    }


def _entry_allowed(row: dict[str, Any], cfg: FundingBacktestConfig) -> bool:
    return (
        float(row.get("funding_rate") or 0.0) > cfg.min_funding_rate
        and float(row.get("total_score") or -1e9) >= cfg.min_total_score
        and _row_float(row, "expected_net_carry_bps", -1e9) >= cfg.min_expected_net_carry_bps
        and _row_float(row, "risk_adjusted_edge_bps", -1e9) >= cfg.min_risk_adjusted_edge_bps
        and int(row.get("funding_observations") or 0) >= cfg.min_funding_observations
        and _row_float(row, "funding_positive_ratio", 0.0) >= cfg.min_funding_positive_ratio
        and _row_float(row, "funding_persistence_score", -1e9) >= cfg.min_funding_persistence_score
        and int(row.get("regime_observations") or 0) >= cfg.min_regime_observations
        and _row_float(row, "regime_perp_volume_avg_quote", 0.0) >= cfg.min_perp_volume_24h_quote
        and _row_float(row, "spot_top_min_notional_quote", 0.0) >= cfg.min_spot_top_notional_quote
        and _row_float(row, "regime_spot_top_min_notional_avg_quote", 0.0) >= cfg.min_spot_top_notional_quote
        and _row_float(row, "regime_basis_std_bps", 1e9) <= cfg.max_basis_std_bps
        and _row_float(row, "regime_spot_spread_avg_bps", 1e9) <= cfg.max_avg_spot_spread_bps
        and _row_float(row, "regime_perp_spread_avg_bps", 1e9) <= cfg.max_avg_perp_spread_bps
        and float(row.get("spot_spread_bps") or 1e9) <= cfg.max_spot_spread_bps
        and float(row.get("perp_spread_bps") or 1e9) <= cfg.max_perp_spread_bps
        and abs(_row_float(row, "basis_bps", 0.0)) <= cfg.max_abs_basis_bps
        and _row_float(row, "basis_bps", -1e9) >= cfg.min_basis_bps
        and _break_even_hours_within(row, cfg.max_break_even_hours)
        and _as_float(row.get("spot_ask")) is not None
        and _as_float(row.get("perp_bid")) is not None
    )


def _exit_reason(row: dict[str, Any], cfg: FundingBacktestConfig) -> str:
    if float(row.get("funding_rate") or 0.0) <= cfg.min_funding_rate:
        return "funding_not_positive"
    if float(row.get("spot_spread_bps") or 1e9) > cfg.max_spot_spread_bps:
        return "spot_spread_wide"
    if float(row.get("perp_spread_bps") or 1e9) > cfg.max_perp_spread_bps:
        return "perp_spread_wide"
    if abs(_row_float(row, "basis_bps", 0.0)) > cfg.max_abs_basis_bps:
        return "basis_too_wide"
    if _row_float(row, "basis_bps", -1e9) < cfg.min_basis_bps:
        return "basis_below_min"
    if float(row.get("total_score") or -1e9) < cfg.min_total_score:
        return "score_below_min"
    if _row_float(row, "expected_net_carry_bps", -1e9) < cfg.min_expected_net_carry_bps:
        return "expected_edge_below_min"
    if _row_float(row, "risk_adjusted_edge_bps", -1e9) < cfg.min_risk_adjusted_edge_bps:
        return "risk_adjusted_edge_below_min"
    if not _break_even_hours_within(row, cfg.max_break_even_hours):
        return "break_even_horizon_too_long"
    if int(row.get("funding_observations") or 0) < cfg.min_funding_observations:
        return "funding_observations_below_min"
    if _row_float(row, "funding_positive_ratio", 0.0) < cfg.min_funding_positive_ratio:
        return "funding_positive_ratio_below_min"
    if _row_float(row, "funding_persistence_score", -1e9) < cfg.min_funding_persistence_score:
        return "funding_persistence_score_below_min"
    if int(row.get("regime_observations") or 0) < cfg.min_regime_observations:
        return "regime_observations_below_min"
    if _row_float(row, "regime_perp_volume_avg_quote", 0.0) < cfg.min_perp_volume_24h_quote:
        return "perp_volume_regime_low"
    if _row_float(row, "spot_top_min_notional_quote", 0.0) < cfg.min_spot_top_notional_quote:
        return "spot_top_liquidity_low"
    if _row_float(row, "regime_spot_top_min_notional_avg_quote", 0.0) < cfg.min_spot_top_notional_quote:
        return "spot_top_liquidity_regime_low"
    if _row_float(row, "regime_basis_std_bps", 1e9) > cfg.max_basis_std_bps:
        return "basis_regime_unstable"
    if _row_float(row, "regime_spot_spread_avg_bps", 1e9) > cfg.max_avg_spot_spread_bps:
        return "spot_spread_regime_wide"
    if _row_float(row, "regime_perp_spread_avg_bps", 1e9) > cfg.max_avg_perp_spread_bps:
        return "perp_spread_regime_wide"
    return ""


def _open_position(market: str, row: dict[str, Any], cfg: FundingBacktestConfig) -> FundingPosition:
    spot_entry = float(row["spot_ask"])
    perp_entry = float(row["perp_bid"])
    spot_qty = cfg.notional_quote / spot_entry
    perp_qty = cfg.notional_quote / perp_entry
    entry_fee = _fee(cfg.notional_quote, cfg.spot_fee_bps) + _fee(cfg.notional_quote, cfg.perp_fee_bps)
    entry_slippage = _fee(cfg.notional_quote * 2.0, cfg.slippage_bps)
    interval = float(row.get("funding_interval_sec") or 28_800)
    return FundingPosition(
        market=market,
        exchange=str(row.get("exchange")),
        base=str(row.get("base")),
        spot_symbol=str(row.get("spot_symbol")),
        perp_symbol=str(row.get("perp_symbol")),
        entry_ts=float(row.get("ts") or 0.0),
        spot_entry_price=spot_entry,
        perp_entry_price=perp_entry,
        spot_qty=spot_qty,
        perp_qty=perp_qty,
        notional_quote=cfg.notional_quote,
        entry_fee_quote=entry_fee,
        entry_slippage_quote=entry_slippage,
        funding_pnl_quote=0.0,
        last_ts=float(row.get("ts") or 0.0),
        last_funding_rate=float(row.get("funding_rate") or 0.0),
        funding_interval_sec=max(interval, 1.0),
    )


def _accrue_funding(position: FundingPosition, row: dict[str, Any]) -> FundingPosition:
    ts = float(row.get("ts") or position.last_ts)
    dt = max(0.0, ts - position.last_ts)
    funding_pnl = position.funding_pnl_quote + position.notional_quote * position.last_funding_rate * (dt / position.funding_interval_sec)
    interval = float(row.get("funding_interval_sec") or position.funding_interval_sec)
    return FundingPosition(
        **{
            **position.__dict__,
            "funding_pnl_quote": funding_pnl,
            "last_ts": ts,
            "last_funding_rate": float(row.get("funding_rate") or 0.0),
            "funding_interval_sec": max(interval, 1.0),
        }
    )


def _close_position(position: FundingPosition, row: dict[str, Any], cfg: FundingBacktestConfig, reason: str) -> FundingTrade:
    spot_exit = float(row.get("spot_bid") or row.get("spot_mid") or position.spot_entry_price)
    perp_exit = float(row.get("perp_ask") or row.get("perp_mark") or position.perp_entry_price)
    spot_pnl = (spot_exit - position.spot_entry_price) * position.spot_qty
    perp_pnl = (position.perp_entry_price - perp_exit) * position.perp_qty
    basis_pnl = spot_pnl + perp_pnl
    exit_fees = _fee(position.notional_quote, cfg.spot_fee_bps) + _fee(position.notional_quote, cfg.perp_fee_bps)
    exit_slippage = _fee(position.notional_quote * 2.0, cfg.slippage_bps)
    total_fees = position.entry_fee_quote + exit_fees
    total_slippage = position.entry_slippage_quote + exit_slippage
    total_cost = total_fees + total_slippage
    net = basis_pnl + position.funding_pnl_quote - total_cost
    exit_ts = float(row.get("ts") or position.last_ts)
    return FundingTrade(
        market=position.market,
        exchange=position.exchange,
        base=position.base,
        spot_symbol=position.spot_symbol,
        perp_symbol=position.perp_symbol,
        entry_ts=position.entry_ts,
        exit_ts=exit_ts,
        hold_sec=exit_ts - position.entry_ts,
        notional_quote=position.notional_quote,
        spot_entry_price=position.spot_entry_price,
        spot_exit_price=spot_exit,
        perp_entry_price=position.perp_entry_price,
        perp_exit_price=perp_exit,
        funding_pnl_quote=position.funding_pnl_quote,
        basis_pnl_quote=basis_pnl,
        fees_quote=total_fees,
        slippage_quote=total_slippage,
        net_pnl_quote=net,
        exit_reason=reason,
    )


def _fee(notional: float, bps: float) -> float:
    return abs(notional) * bps / 1e4


def _row_float(row: dict[str, Any], key: str, default: float) -> float:
    value = _as_float(row.get(key))
    return default if value is None else value


def _break_even_hours_within(row: dict[str, Any], max_hours: float) -> bool:
    if max_hours >= 1e9:
        return True
    break_even_hours = _as_float(row.get("break_even_hours"))
    return break_even_hours is not None and break_even_hours <= max_hours


def _avg(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _std(values: list[float]) -> float | None:
    if not values:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _funding_market_key(row: dict[str, Any]) -> str:
    return f"{row.get('exchange')}:{row.get('spot_symbol')}:{row.get('perp_symbol')}"


def _load_funding_manifest(manifest_path: str | Path | None) -> dict[str, Any] | None:
    if not manifest_path:
        return None
    path = Path(manifest_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _count_jsonl_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _funding_oos_split_index(row_count: int, cfg: FundingOosConfig) -> int | None:
    if row_count <= 0:
        return None
    split = int(row_count * cfg.train_fraction)
    split = max(cfg.min_train_rows, split)
    split = min(split, row_count - cfg.min_oos_rows)
    if split < cfg.min_train_rows:
        return None
    if row_count - split < cfg.min_oos_rows:
        return None
    return split


def _funding_oos_coverage(train_rows: list[dict[str, Any]], oos_rows: list[dict[str, Any]], cfg: FundingOosConfig) -> dict[str, Any]:
    train_span = _funding_rows_time_span(train_rows)
    oos_span = _funding_rows_time_span(oos_rows)
    return {
        "train_rows": len(train_rows),
        "oos_rows": len(oos_rows),
        "train_first_ts": train_span["first_ts"],
        "train_last_ts": train_span["last_ts"],
        "train_span_sec": train_span["span_sec"],
        "train_span_hours": train_span["span_hours"],
        "oos_first_ts": oos_span["first_ts"],
        "oos_last_ts": oos_span["last_ts"],
        "oos_span_sec": oos_span["span_sec"],
        "oos_span_hours": oos_span["span_hours"],
        "min_train_span_hours": cfg.min_train_span_hours,
        "min_oos_span_hours": cfg.min_oos_span_hours,
        "train_span_accepted": train_span["span_hours"] >= max(float(cfg.min_train_span_hours), 0.0),
        "oos_span_accepted": oos_span["span_hours"] >= max(float(cfg.min_oos_span_hours), 0.0),
    }


def _funding_oos_coverage_acceptance(coverage: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if not bool(coverage.get("train_span_accepted")):
        reasons.append("min_train_span_hours")
    if not bool(coverage.get("oos_span_accepted")):
        reasons.append("min_oos_span_hours")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "coverage": coverage,
    }


def _funding_rows_time_span(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    timestamps = [
        ts
        for ts in (_as_float(row.get("ts")) for row in rows)
        if ts is not None
    ]
    if not timestamps:
        return {"first_ts": None, "last_ts": None, "span_sec": 0.0, "span_hours": 0.0}
    first_ts = min(timestamps)
    last_ts = max(timestamps)
    span_sec = max(0.0, last_ts - first_ts)
    return {"first_ts": first_ts, "last_ts": last_ts, "span_sec": span_sec, "span_hours": span_sec / 3600.0}


def _funding_cycle_interval_estimate(manifest: dict[str, Any] | None) -> float | None:
    if not manifest:
        return None
    timestamps = [
        ts
        for ts in (_as_float(item.get("ts")) for item in manifest.get("cycle_summaries") or [])
        if ts is not None
    ]
    if len(timestamps) >= 2:
        interval = timestamps[-1] - timestamps[-2]
        if interval > 0:
            return interval
    completed_cycles = int(manifest.get("completed_cycles") or 0)
    duration_sec = _as_float(manifest.get("duration_sec"))
    if completed_cycles > 0 and duration_sec is not None and duration_sec > 0:
        return duration_sec / completed_cycles
    return None


def _last_funding_cycle_ts(manifest: dict[str, Any] | None) -> float | None:
    if not manifest:
        return None
    timestamps = [
        ts
        for ts in (_as_float(item.get("ts")) for item in manifest.get("cycle_summaries") or [])
        if ts is not None
    ]
    return timestamps[-1] if timestamps else None


def _funding_manifest_summary(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        "final": manifest.get("final"),
        "completed_cycles": manifest.get("completed_cycles"),
        "cycles": manifest.get("cycles"),
        "rows": manifest.get("rows"),
        "errors": manifest.get("errors"),
        "duration_sec": manifest.get("duration_sec"),
    }


def _with_rolling_persistence(row: dict[str, Any], history: list[dict[str, Any]], cfg: FundingBacktestConfig) -> dict[str, Any]:
    rank_cfg = FundingRankConfig(
        min_funding_observations=cfg.min_funding_observations,
        min_funding_positive_ratio=cfg.min_funding_positive_ratio,
        min_funding_persistence_score=cfg.min_funding_persistence_score,
    )
    out = dict(row)
    out.update(_funding_persistence_metrics(history, rank_cfg))
    out.update(_funding_regime_metrics(history))
    out.update(
        _funding_risk_adjusted_edge_fields(
            out,
            basis_risk_multiplier=cfg.basis_risk_multiplier,
            spread_risk_multiplier=cfg.spread_risk_multiplier,
        )
    )
    return out


def _funding_regime_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    basis_values = [
        value
        for value in (_as_float(row.get("basis_bps")) for row in rows)
        if value is not None
    ]
    spot_spreads = [
        value
        for value in (_as_float(row.get("spot_spread_bps")) for row in rows)
        if value is not None
    ]
    perp_spreads = [
        value
        for value in (_as_float(row.get("perp_spread_bps")) for row in rows)
        if value is not None
    ]
    volumes = [
        value
        for value in (_as_float(row.get("perp_volume_24h_quote")) for row in rows)
        if value is not None
    ]
    spot_top_notional = [
        value
        for value in (_as_float(row.get("spot_top_min_notional_quote")) for row in rows)
        if value is not None
    ]
    observations = max(len(basis_values), len(spot_spreads), len(perp_spreads), len(volumes), len(spot_top_notional))
    return {
        "regime_observations": observations,
        "regime_perp_volume_avg_quote": _avg(volumes),
        "regime_perp_volume_min_quote": min(volumes) if volumes else None,
        "regime_spot_top_min_notional_avg_quote": _avg(spot_top_notional),
        "regime_spot_top_min_notional_min_quote": min(spot_top_notional) if spot_top_notional else None,
        "regime_basis_avg_bps": _avg(basis_values),
        "regime_basis_std_bps": _std(basis_values),
        "regime_basis_abs_max_bps": max((abs(value) for value in basis_values), default=None),
        "regime_spot_spread_avg_bps": _avg(spot_spreads),
        "regime_perp_spread_avg_bps": _avg(perp_spreads),
        "regime_spread_avg_bps": _avg([*spot_spreads, *perp_spreads]),
    }


def _funding_persistence_metrics(rows: list[dict[str, Any]], cfg: FundingRankConfig) -> dict[str, Any]:
    rates = [
        rate
        for rate in (_as_float(row.get("funding_rate")) for row in rows)
        if rate is not None
    ]
    observations = len(rates)
    positive_observations = sum(1 for rate in rates if rate > 0)
    negative_observations = sum(1 for rate in rates if rate < 0)
    positive_ratio = positive_observations / observations if observations else 0.0
    if observations:
        avg_rate = sum(rates) / observations
        min_rate = min(rates)
        max_rate = max(rates)
        variance = sum((rate - avg_rate) ** 2 for rate in rates) / observations
        std_rate = math.sqrt(variance)
        avg_bps = avg_rate * 1e4
        min_bps = min_rate * 1e4
        max_bps = max_rate * 1e4
        std_bps = std_rate * 1e4
        negative_penalty = max(0.0, -min_bps) * 2.0
        persistence_score = (positive_ratio * max(avg_bps, 0.0)) + (positive_ratio * 2.0) - std_bps - negative_penalty
    else:
        avg_rate = None
        min_rate = None
        max_rate = None
        std_rate = None
        avg_bps = None
        min_bps = None
        max_bps = None
        std_bps = None
        persistence_score = -1e9

    reasons: list[str] = []
    if observations < cfg.min_funding_observations:
        reasons.append("funding_observations_below_min")
    if positive_ratio < cfg.min_funding_positive_ratio:
        reasons.append("funding_positive_ratio_below_min")
    if persistence_score < cfg.min_funding_persistence_score:
        reasons.append("funding_persistence_score_below_min")

    return {
        "funding_observations": observations,
        "funding_positive_observations": positive_observations,
        "funding_negative_observations": negative_observations,
        "funding_positive_ratio": positive_ratio,
        "funding_avg_rate": avg_rate,
        "funding_min_rate": min_rate,
        "funding_max_rate": max_rate,
        "funding_rate_std": std_rate,
        "funding_avg_bps": avg_bps,
        "funding_min_bps": min_bps,
        "funding_max_bps": max_bps,
        "funding_std_bps": std_bps,
        "funding_persistence_score": persistence_score,
        "persistence_eligible": not reasons,
        "persistence_reasons": reasons,
    }


def _round_trip_cost_bps(spot_fee_bps: float, perp_fee_bps: float, slippage_bps: float) -> float:
    return (2.0 * spot_fee_bps) + (2.0 * perp_fee_bps) + (4.0 * slippage_bps)


def _funding_cycle_summary(cycle: int, payload: dict[str, Any], cycle_started: float) -> dict[str, Any]:
    errors = list(payload.get("errors", []))
    rows = list(payload.get("rows", []))
    error_breakdown = Counter(f"{err.get('exchange')}:{err.get('stage')}:{err.get('error')}" for err in errors)
    discovery = payload.get("discovery", {})
    selected_by_exchange = {
        exchange: data.get("symbols", [])
        for exchange, data in discovery.items()
        if isinstance(data, dict)
    }
    return {
        "cycle": cycle,
        "ts": time.time(),
        "duration_sec": time.time() - cycle_started,
        "rows": len(rows),
        "eligible": sum(1 for row in rows if row.get("eligible")),
        "errors": len(errors),
        "selected_by_exchange": selected_by_exchange,
        "top": [
            {
                "exchange": row.get("exchange"),
                "base": row.get("base"),
                "spot_symbol": row.get("spot_symbol"),
                "perp_symbol": row.get("perp_symbol"),
                "funding_rate": row.get("funding_rate"),
                "total_score": row.get("total_score"),
                "expected_net_carry_bps": row.get("expected_net_carry_bps"),
                "reasons": row.get("reasons", []),
            }
            for row in rows[:5]
        ],
        "error_breakdown": [
            {"key": key, "count": count}
            for key, count in error_breakdown.most_common(20)
        ],
    }


def _write_funding_collect_manifest(
    manifest: Path,
    output: Path,
    cycles: int,
    started: float,
    total_rows: int,
    total_errors: int,
    cycle_summaries: list[dict[str, Any]],
    final: bool,
) -> None:
    payload = {
        "mode": "funding_collect_manifest",
        "ok": True,
        "final": final,
        "output": str(output),
        "cycles": cycles,
        "completed_cycles": len(cycle_summaries),
        "rows": total_rows,
        "errors": total_errors,
        "duration_sec": time.time() - started,
        "cycle_summaries": cycle_summaries,
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _funding_equity_curve(trades: list[FundingTrade]) -> list[dict[str, Any]]:
    cumulative = 0.0
    peak = 0.0
    curve: list[dict[str, Any]] = []
    for index, trade in enumerate(sorted(trades, key=lambda item: (item.exit_ts, item.market)), start=1):
        cumulative += trade.net_pnl_quote
        peak = max(peak, cumulative)
        drawdown = max(0.0, peak - cumulative)
        curve.append(
            {
                "trade_index": index,
                "exit_ts": trade.exit_ts,
                "market": trade.market,
                "exchange": trade.exchange,
                "base": trade.base,
                "net_pnl_quote": trade.net_pnl_quote,
                "cumulative_pnl_quote": cumulative,
                "peak_equity_quote": peak,
                "drawdown_quote": drawdown,
            }
        )
    return curve


def _funding_metrics(trades: list[FundingTrade], rows: int, markets: int, equity_curve: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(trades)
    wins = sum(1 for trade in trades if trade.net_pnl_quote > 0)
    losses = total - wins
    net = sum(trade.net_pnl_quote for trade in trades)
    gross_wins = sum(trade.net_pnl_quote for trade in trades if trade.net_pnl_quote > 0)
    gross_losses = abs(sum(trade.net_pnl_quote for trade in trades if trade.net_pnl_quote < 0))
    total_notional = sum(trade.notional_quote for trade in trades)
    ending_equity = float(equity_curve[-1]["cumulative_pnl_quote"]) if equity_curve else 0.0
    peak_equity = max((float(point["peak_equity_quote"]) for point in equity_curve), default=0.0)
    max_drawdown = max((float(point["drawdown_quote"]) for point in equity_curve), default=0.0)
    market_trade_counts = dict(Counter(trade.market for trade in trades))
    max_market_trade_count = max(market_trade_counts.values(), default=0)
    exchange_trade_counts = dict(Counter(trade.exchange for trade in trades))
    max_exchange_trade_count = max(exchange_trade_counts.values(), default=0)
    window_metrics = _funding_window_metrics(trades)
    return {
        "rows": rows,
        "markets": markets,
        "traded_markets": len(market_trade_counts),
        "total_trades": total,
        "market_trade_counts": market_trade_counts,
        "max_market_trade_share": max_market_trade_count / total if total else 0.0,
        "traded_exchanges": len(exchange_trade_counts),
        "exchange_trade_counts": exchange_trade_counts,
        "max_exchange_trade_share": max_exchange_trade_count / total if total else 0.0,
        **window_metrics,
        "wins": wins,
        "losses": losses,
        "total_notional_quote": total_notional,
        "avg_notional_quote": total_notional / total if total else 0.0,
        "win_rate": wins / total if total else 0.0,
        "funding_pnl_quote": sum(trade.funding_pnl_quote for trade in trades),
        "basis_pnl_quote": sum(trade.basis_pnl_quote for trade in trades),
        "fees_quote": sum(trade.fees_quote for trade in trades),
        "slippage_quote": sum(trade.slippage_quote for trade in trades),
        "net_pnl_quote": net,
        "expectancy_quote": net / total if total else 0.0,
        "profit_factor": (gross_wins / gross_losses) if gross_losses else None,
        "ending_equity_quote": ending_equity,
        "peak_equity_quote": peak_equity,
        "max_drawdown_quote": max_drawdown,
        "max_drawdown_pct": (max_drawdown / peak_equity) if peak_equity > 0 else None,
    }


def _funding_window_metrics(trades: list[FundingTrade], window_sec: float = 3600.0) -> dict[str, Any]:
    window_pnl: dict[str, float] = defaultdict(float)
    window_trade_counts: Counter[str] = Counter()
    for trade in trades:
        bucket = int(float(trade.exit_ts) // max(window_sec, 1.0))
        key = str(bucket)
        window_pnl[key] += trade.net_pnl_quote
        window_trade_counts[key] += 1
    sorted_keys = sorted(window_pnl.keys(), key=lambda item: int(item))
    ordered_window_pnl = {key: window_pnl[key] for key in sorted_keys}
    ordered_window_counts = {key: int(window_trade_counts[key]) for key in sorted_keys}
    positive_window_pnl = [pnl for pnl in ordered_window_pnl.values() if pnl > 0.0]
    gross_positive_window_pnl = sum(positive_window_pnl)
    max_window_pnl = max(positive_window_pnl, default=0.0)
    return {
        "window_sec": window_sec,
        "active_windows": len(ordered_window_pnl),
        "profitable_windows": len(positive_window_pnl),
        "window_pnl_quote": ordered_window_pnl,
        "window_trade_counts": ordered_window_counts,
        "max_window_pnl_quote": max_window_pnl,
        "max_window_pnl_share": max_window_pnl / gross_positive_window_pnl if gross_positive_window_pnl > 0.0 else 0.0,
    }


def _dataclass_from_dict(cls: Any, values: dict[str, Any]) -> Any:
    allowed = getattr(cls, "__dataclass_fields__", {})
    filtered = {key: value for key, value in values.items() if key in allowed}
    return cls(**filtered)


def _funding_research_gate_reasons(research_acceptance: dict[str, Any]) -> list[str]:
    required_true_fields = [
        "full_backtest_accepted",
        "oos_required_passed",
        "oos_accepted",
        "walk_forward_required_passed",
        "walk_forward_accepted",
        "stress_required_passed",
        "stress_assumptions_passed",
        "stress_accepted",
    ]
    reasons: list[str] = []
    for field in required_true_fields:
        if research_acceptance.get(field) is not True:
            reasons.append(f"{field}_missing")
    if research_acceptance.get("reasons") not in ([], None):
        reasons.append("research_acceptance_reasons_not_empty")
    return reasons


def _funding_stress_assumptions_passed(stress_cfg: FundingStressConfig) -> bool:
    return any(
        value > 0.0
        for value in (
            max(float(stress_cfg.adverse_basis_bps), 0.0),
            max(float(stress_cfg.spread_widen_bps), 0.0),
            max(float(stress_cfg.funding_flip_bps), 0.0),
        )
    )


def _funding_plan_safety_reasons(plan: dict[str, Any]) -> list[str]:
    checks = {
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
    }
    reasons: list[str] = []
    for field, expected in checks.items():
        if plan.get(field) is not expected:
            reasons.append(f"{field}_not_{str(expected).lower()}")
    return reasons


def _funding_paper_forward_plan_gate_reasons(plan: dict[str, Any]) -> dict[str, list[str]]:
    safety_reasons = _funding_plan_safety_reasons(plan)
    research_reasons = _funding_research_gate_reasons(plan.get("research_acceptance") or {})
    research_reasons.extend(_funding_data_quality_gate_reasons(plan.get("source_data_quality"), plan.get("source_time_range")))
    if not plan.get("source_decision_report"):
        research_reasons.append("decision_report_missing")
    decision_summary = plan.get("decision_summary")
    if not isinstance(decision_summary, dict):
        research_reasons.append("decision_summary_missing")
    elif decision_summary.get("accepted") is not True:
        research_reasons.append("decision_report_not_accepted")
        research_reasons.extend(f"decision:{reason}" for reason in decision_summary.get("reasons") or [])
    existing_gate_reasons = plan.get("research_gate_reasons") or []
    if existing_gate_reasons:
        research_reasons.append("research_gate_reasons_not_empty")
        if isinstance(existing_gate_reasons, list):
            research_reasons.extend(str(reason) for reason in existing_gate_reasons)
    return {
        "safety": safety_reasons,
        "research": research_reasons,
        "all": safety_reasons + research_reasons,
    }


def _funding_paper_decision_artifact_gate_reasons(
    decision: dict[str, Any],
    *,
    paper_summary_path: str | Path | None,
    paper_plan_path: str | Path | None,
    paper_summary: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(_funding_plan_safety_reasons(decision))
    if decision.get("mode") != "funding_paper_decision_report":
        reasons.append("mode_not_funding_paper_decision_report")
    decision_summary_path = decision.get("summary_path")
    if paper_summary_path is not None:
        if not decision_summary_path:
            reasons.append("summary_path_missing")
        elif not _same_path(Path(str(decision_summary_path)), Path(paper_summary_path)):
            reasons.append("summary_path_mismatch")
    decision_plan_path = decision.get("plan_path")
    if paper_plan_path is not None:
        if not decision_plan_path:
            reasons.append("plan_path_missing")
        elif not _same_path(Path(str(decision_plan_path)), Path(paper_plan_path)):
            reasons.append("plan_path_mismatch")
    decision_summary = decision.get("summary") if isinstance(decision.get("summary"), dict) else {}
    metrics = decision.get("metrics") if isinstance(decision.get("metrics"), dict) else {}
    summary_metrics = paper_summary.get("metrics") if isinstance(paper_summary.get("metrics"), dict) else {}
    for metric in FUNDING_PAPER_REQUIRED_METRICS:
        if _as_float(metrics.get(metric)) is None:
            reasons.append(f"metric:{metric}_missing")
        elif decision_summary.get(metric) != metrics.get(metric):
            reasons.append(f"summary_metric:{metric}_mismatch")
        elif summary_metrics.get(metric) != metrics.get(metric):
            reasons.append(f"paper_summary_metric:{metric}_mismatch")
    paper_acceptance = decision.get("paper_acceptance") if isinstance(decision.get("paper_acceptance"), dict) else {}
    summary_acceptance = paper_summary.get("paper_acceptance") if isinstance(paper_summary.get("paper_acceptance"), dict) else {}
    if paper_acceptance.get("accepted") is not True:
        reasons.append("paper_acceptance_not_accepted")
    elif decision_summary.get("paper_acceptance_accepted") is not True:
        reasons.append("summary_paper_acceptance_mismatch")
    elif summary_acceptance != paper_acceptance:
        reasons.append("paper_summary_acceptance_mismatch")
    coverage = decision.get("coverage") if isinstance(decision.get("coverage"), dict) else {}
    summary_coverage = paper_summary.get("coverage") if isinstance(paper_summary.get("coverage"), dict) else {}
    for coverage_field in ("duration_accepted", "rows_accepted", "markets_accepted"):
        if coverage.get(coverage_field) is not True:
            reasons.append(f"coverage:{coverage_field}_not_true")
    if decision_summary.get("coverage") != coverage:
        reasons.append("summary_coverage_mismatch")
    if summary_coverage != coverage:
        reasons.append("paper_summary_coverage_mismatch")
    if _canonical_funding_frozen_config(decision.get("frozen_config")) != _canonical_funding_frozen_config(paper_summary.get("frozen_config")):
        reasons.append("paper_summary_frozen_config_mismatch")
    return reasons


def _funding_paper_plan_artifact_gate_reasons(
    plan: dict[str, Any],
    *,
    input_path: str | Path,
    final_review: dict[str, Any],
    paper_plan_path: str | Path | None,
) -> list[str]:
    reasons: list[str] = []
    if plan.get("mode") != "funding_paper_forward_plan":
        reasons.append("mode_not_funding_paper_forward_plan")
    source_input = plan.get("source_input")
    if not source_input:
        reasons.append("source_input_missing")
    elif not _same_path(Path(str(source_input)), Path(input_path)):
        reasons.append("source_input_mismatch")

    artifact_paths = final_review.get("artifact_paths") if isinstance(final_review.get("artifact_paths"), dict) else {}
    expected_plan = artifact_paths.get("paper_plan")
    if expected_plan and paper_plan_path is not None and not _same_path(Path(str(expected_plan)), Path(paper_plan_path)):
        reasons.append("paper_plan_path_mismatch")

    expected_postprocess = artifact_paths.get("postprocess")
    if expected_postprocess:
        source_postprocess = plan.get("source_postprocess")
        if not source_postprocess:
            reasons.append("source_postprocess_missing")
        elif not _same_path(Path(str(source_postprocess)), Path(str(expected_postprocess))):
            reasons.append("source_postprocess_mismatch")

    expected_decision = artifact_paths.get("decision_report")
    if expected_decision:
        source_decision = plan.get("source_decision_report")
        if not source_decision:
            reasons.append("source_decision_report_missing")
        elif not _same_path(Path(str(source_decision)), Path(str(expected_decision))):
            reasons.append("source_decision_report_mismatch")
    return reasons


def _funding_paper_summary_artifact_gate_reasons(
    summary: dict[str, Any],
    *,
    paper_plan: dict[str, Any],
    paper_plan_path: str | Path | None,
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(_funding_plan_safety_reasons(summary))
    if summary.get("mode") != "funding_paper_forward":
        reasons.append("mode_not_funding_paper_forward")
    if summary.get("status") != "completed":
        reasons.append(f"status:{summary.get('status') or 'missing'}")
    if summary.get("ok") is not True:
        reasons.append("ok_not_true")
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    for metric in FUNDING_PAPER_REQUIRED_METRICS:
        if _as_float(metrics.get(metric)) is None:
            reasons.append(f"metric:{metric}_missing")
    paper_acceptance = summary.get("paper_acceptance") if isinstance(summary.get("paper_acceptance"), dict) else {}
    if paper_acceptance.get("accepted") is not True:
        reasons.append("paper_acceptance_not_accepted")
        reasons.extend(f"paper_acceptance:{reason}" for reason in paper_acceptance.get("reasons") or [])
    coverage = summary.get("coverage") if isinstance(summary.get("coverage"), dict) else {}
    for coverage_field in ("duration_accepted", "rows_accepted", "markets_accepted"):
        if coverage.get(coverage_field) is not True:
            reasons.append(f"coverage:{coverage_field}_not_true")

    summary_plan = summary.get("plan")
    if paper_plan_path is not None:
        if not summary_plan:
            reasons.append("plan_path_missing")
        elif not _same_path(Path(str(summary_plan)), Path(paper_plan_path)):
            reasons.append("plan_path_mismatch")

    plan_source_input = paper_plan.get("source_input")
    summary_source_input = summary.get("source_input")
    if plan_source_input:
        if not summary_source_input:
            reasons.append("source_input_missing")
        elif not _same_path(Path(str(summary_source_input)), Path(str(plan_source_input))):
            reasons.append("source_input_mismatch")
        if summary.get("input") and _same_path(Path(str(summary.get("input"))), Path(str(plan_source_input))):
            reasons.append("input_reuses_source_input")

    plan_output = paper_plan.get("paper_output_path")
    if plan_output:
        summary_output = summary.get("output")
        if not summary_output:
            reasons.append("output_path_missing")
        elif not _same_path(Path(str(summary_output)), Path(str(plan_output))):
            reasons.append("output_path_mismatch")

    plan_frozen_config = _canonical_funding_frozen_config(paper_plan.get("frozen_config"))
    summary_frozen_config = _canonical_funding_frozen_config(summary.get("frozen_config"))
    if summary_frozen_config != plan_frozen_config:
        reasons.append("frozen_config_mismatch")
    return reasons


def _funding_final_review_artifact_gate_reasons(
    final_review: dict[str, Any],
    *,
    input_path: str | Path,
    manifest_path: str | Path | None,
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(_funding_plan_safety_reasons(final_review))
    if final_review.get("mode") != "funding_final_review":
        reasons.append("mode_not_funding_final_review")
    review_input = final_review.get("input")
    if not review_input:
        reasons.append("input_path_missing")
    elif not _same_path(Path(str(review_input)), Path(input_path)):
        reasons.append("input_path_mismatch")
    expected_manifest = Path(manifest_path) if manifest_path is not None else Path(input_path).with_suffix(".manifest.json")
    review_manifest = final_review.get("manifest")
    if not review_manifest:
        reasons.append("manifest_path_missing")
    elif not _same_path(Path(str(review_manifest)), expected_manifest):
        reasons.append("manifest_path_mismatch")
    return reasons


def _funding_data_quality_gate_reasons(source_data_quality: Any, source_time_range: Any) -> list[str]:
    reasons: list[str] = []
    if not isinstance(source_data_quality, dict):
        reasons.append("data_quality_missing")
    elif source_data_quality.get("accepted") is not True:
        reasons.append("data_quality_not_accepted")
    if not isinstance(source_time_range, dict):
        reasons.append("source_time_range_missing")
    else:
        if _as_float(source_time_range.get("first_ts")) is None:
            reasons.append("source_time_range_first_ts_missing")
        if _as_float(source_time_range.get("last_ts")) is None:
            reasons.append("source_time_range_last_ts_missing")
    return reasons


def _funding_source_time_range(source_data_quality: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source_data_quality, dict):
        return None
    metrics = source_data_quality.get("metrics")
    if not isinstance(metrics, dict):
        return None
    first_ts = _as_float(metrics.get("first_ts"))
    last_ts = _as_float(metrics.get("last_ts"))
    if first_ts is None or last_ts is None:
        return None
    return {
        "first_ts": first_ts,
        "last_ts": last_ts,
        "span_sec": _row_float(metrics, "span_sec", max(0.0, last_ts - first_ts)),
        "span_hours": _row_float(metrics, "span_hours", max(0.0, last_ts - first_ts) / 3600.0),
    }


def _funding_paper_forward_temporal_gate(rows: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    forward_range = _funding_rows_time_span(rows)
    source_range = plan.get("source_time_range")
    if not isinstance(source_range, dict):
        return {
            "accepted": True,
            "reasons": [],
            "source_time_range": None,
            "forward_time_range": forward_range,
        }
    source_last_ts = _as_float(source_range.get("last_ts"))
    forward_first_ts = _as_float(forward_range.get("first_ts"))
    reasons: list[str] = []
    if source_last_ts is not None and forward_first_ts is not None and forward_first_ts <= source_last_ts:
        reasons.append("source_time_overlap")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "source_time_range": source_range,
        "forward_time_range": forward_range,
    }


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left).lower() == str(right).lower()


def _canonical_funding_frozen_config(frozen_config: Any) -> dict[str, Any]:
    if not isinstance(frozen_config, dict):
        frozen_config = {}
    return {
        "backtest_config": _dataclass_from_dict(
            FundingBacktestConfig,
            frozen_config.get("backtest_config") or {},
        ).__dict__,
        "acceptance_config": _dataclass_from_dict(
            FundingAcceptanceConfig,
            frozen_config.get("acceptance_config") or {},
        ).__dict__,
        "stress_config": _dataclass_from_dict(
            FundingStressConfig,
            frozen_config.get("stress_config") or {},
        ).__dict__,
    }


def _funding_paper_forward_summary(
    *,
    ok: bool,
    status: str,
    plan_path: Path,
    input_path: Path,
    output_path: Path,
    plan: dict[str, Any],
    message: str | None = None,
    metrics: dict[str, Any] | None = None,
    paper_acceptance: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    frozen_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "mode": "funding_paper_forward",
        "ok": ok,
        "status": status,
        "plan": str(plan_path),
        "input": str(input_path),
        "output": str(output_path),
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "source_postprocess": plan.get("source_postprocess"),
        "source_input": plan.get("source_input"),
        "metrics": metrics or {},
        "paper_acceptance": paper_acceptance or {"accepted": False, "reasons": [status]},
        "coverage": coverage or {},
        "frozen_config": frozen_config or plan.get("frozen_config") or {},
    }
    if message:
        payload["message"] = message
    return payload


def _funding_forward_coverage(rows: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    timestamps = [
        ts
        for ts in (_as_float(row.get("ts")) for row in rows)
        if ts is not None
    ]
    first_ts = min(timestamps) if timestamps else None
    last_ts = max(timestamps) if timestamps else None
    span_sec = max(0.0, float(last_ts - first_ts)) if first_ts is not None and last_ts is not None else 0.0
    min_forward_hours = _row_float(plan, "min_forward_hours", 0.0)
    min_forward_rows = int(plan.get("min_forward_rows") or 0)
    min_forward_markets = int(plan.get("min_forward_markets") or 0)
    markets = {_funding_market_key(row) for row in rows}
    return {
        "rows": len(rows),
        "markets": len(markets),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "span_sec": span_sec,
        "span_hours": span_sec / 3600.0,
        "min_forward_hours": min_forward_hours,
        "min_forward_rows": min_forward_rows,
        "min_forward_markets": min_forward_markets,
        "duration_accepted": span_sec >= max(min_forward_hours, 0.0) * 3600.0,
        "rows_accepted": len(rows) >= max(min_forward_rows, 0),
        "markets_accepted": len(markets) >= max(min_forward_markets, 0),
    }


def _funding_paper_forward_acceptance(
    backtest_acceptance: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    reasons = list(backtest_acceptance.get("reasons") or [])
    if not bool(coverage.get("duration_accepted")):
        reasons.append("min_forward_hours")
    if not bool(coverage.get("rows_accepted")):
        reasons.append("min_forward_rows")
    if not bool(coverage.get("markets_accepted")):
        reasons.append("min_forward_markets")
    return {
        **backtest_acceptance,
        "accepted": not reasons,
        "reasons": reasons,
        "coverage": coverage,
        "backtest_acceptance": {
            "accepted": backtest_acceptance.get("accepted"),
            "reasons": backtest_acceptance.get("reasons") or [],
        },
    }


def _write_funding_paper_forward_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_funding_scan_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_scan_{utc_stamp()}.json"


def default_funding_coverage_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_coverage_{utc_stamp()}.json"


def default_funding_matched_universe_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_matched_universe_{utc_stamp()}.csv"


def default_funding_collect_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_collect_{utc_stamp()}.jsonl"


def default_funding_rank_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_rank_{utc_stamp()}.json"


def default_funding_gate_report_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_gate_report_{utc_stamp()}.json"


def default_funding_regime_report_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_regime_report_{utc_stamp()}.json"


def default_funding_frontier_report_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_frontier_report_{utc_stamp()}.json"


def default_funding_decision_report_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_decision_report_{utc_stamp()}.json"


def default_funding_final_review_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_final_review_{utc_stamp()}.json"


def default_funding_progress_report_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_progress_report_{utc_stamp()}.json"


def default_funding_collect_diagnostics_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_collect_diagnostics_{utc_stamp()}.json"


def default_funding_backtest_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"funding_backtest_{utc_stamp()}.json"


def default_funding_sensitivity_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"funding_sensitivity_{utc_stamp()}.json"


def default_funding_oos_backtest_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"funding_oos_backtest_{utc_stamp()}.json"


def default_funding_walk_forward_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"funding_walk_forward_{utc_stamp()}.json"


def default_funding_paper_forward_plan_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_paper_forward_plan_{utc_stamp()}.json"


def default_funding_paper_forward_summary_path(output_path: str | Path) -> Path:
    return Path(output_path).with_suffix(".summary.json")


def default_funding_paper_decision_report_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_paper_decision_report_{utc_stamp()}.json"


def default_funding_goal_audit_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_goal_audit_{utc_stamp()}.json"


def default_funding_wait_ready_path(funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_wait_ready_{utc_stamp()}.json"


def default_funding_postprocess_summary_path(input_path: str | Path, funding_dir: str | Path) -> Path:
    return Path(funding_dir) / f"funding_postprocess_{Path(input_path).stem}.json"


def default_funding_postprocess_output(input_path: str | Path, funding_dir: str | Path, backtest_dir: str | Path) -> tuple[Path, Path]:
    stem = Path(input_path).stem
    return Path(funding_dir) / f"funding_rank_{stem}.json", Path(backtest_dir) / f"funding_backtest_{stem}.json"
