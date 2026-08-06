from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests


PLAN_DECISION = "PIT_UNIVERSE_PUBLIC_PROBE_PLAN_READY"
ACCEPTED_DECISION = "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL"
REJECTED_DECISION = "PIT_UNIVERSE_PUBLIC_PROBE_REJECTED_RESCOPE"
MEXC_CONTRACTS_URL = "https://contract.mexc.com/api/v1/contract/detail"
MEXC_TICKERS_URL = "https://contract.mexc.com/api/v1/contract/ticker"
MEXC_DEPTH_URL_TEMPLATE = "https://contract.mexc.com/api/v1/contract/depth/{symbol}?limit=5"
MIN_MEXC_DEPTH_COVERAGE = 0.95
MEXC_DEPTH_RUNTIME_BUDGET_SEC = 120.0
MEXC_DEPTH_REQUEST_INTERVAL_SEC = 0.25
MEXC_DEPTH_MAX_WORKERS = 3
GATE_CONTRACTS_URL = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
GATE_TICKERS_URL = "https://api.gateio.ws/api/v4/futures/usdt/tickers"
BINANCE_SPOT_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
REQUIRED_SNAPSHOT_FIELDS = (
    "snapshot_ts",
    "exchange",
    "symbol",
    "base",
    "quote",
    "contract_type",
    "status",
    "listed_now",
    "inactive_or_delisted",
    "volume_24h_quote",
    "bid_price",
    "ask_price",
    "mid_price",
    "spread_bps",
    "bid_size_contracts",
    "ask_size_contracts",
    "liquidity_proxy_source",
    "mark_price",
    "index_price",
    "funding_rate",
    "funding_interval_sec",
    "funding_next_apply_ts",
    "contract_multiplier",
    "minimum_order_size",
    "maximum_order_size",
    "price_tick",
    "quantity_step",
    "binance_spot_listed",
    "excluded_by_binance_spot",
    "eligible_non_binance_spot",
    "binance_reference_ts",
    "source_endpoint",
    "raw_status",
    "first_seen_ts",
    "last_seen_ts",
)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mexc_data(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(f"MEXC error {payload.get('code')}: {payload.get('message')}")
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _get_json(session: requests.Session, url: str, timeout_sec: int) -> Any:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=timeout_sec)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"GET failed: {url}")


def mexc_ticker_map(payload: Any) -> dict[str, dict[str, Any]]:
    tickers = _mexc_data(payload)
    if not isinstance(tickers, list):
        return {}
    return {str(item.get("symbol") or "").upper(): item for item in tickers if isinstance(item, dict)}


def gate_ticker_map(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        return {}
    return {str(item.get("contract") or "").upper(): item for item in payload if isinstance(item, dict)}


def parse_binance_spot_symbols(payload: Any) -> set[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("Binance exchangeInfo payload has no symbols list")
    symbols: set[str] = set()
    for item in payload["symbols"]:
        if not isinstance(item, dict):
            continue
        if str(item.get("quoteAsset") or "").upper() != "USDT":
            continue
        if str(item.get("status") or "").upper() != "TRADING":
            continue
        if item.get("isSpotTradingAllowed") is False:
            continue
        symbol = str(item.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    return symbols


def _bbo_metrics(
    ticker: dict[str, Any],
    bid_fields: tuple[str, ...],
    ask_fields: tuple[str, ...],
    bid_size_fields: tuple[str, ...] = (),
    ask_size_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    bid = next((_as_float(ticker.get(name)) for name in bid_fields if _as_float(ticker.get(name)) is not None), None)
    ask = next((_as_float(ticker.get(name)) for name in ask_fields if _as_float(ticker.get(name)) is not None), None)
    mid = None
    spread_bps = None
    if bid is not None and ask is not None and bid > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / mid) * 10_000.0 if mid > 0 else None
    return {
        "bid_price": bid,
        "ask_price": ask,
        "mid_price": mid,
        "spread_bps": spread_bps,
        "bid_size_contracts": next(
            (_as_float(ticker.get(name)) for name in bid_size_fields if _as_float(ticker.get(name)) is not None),
            None,
        ),
        "ask_size_contracts": next(
            (_as_float(ticker.get(name)) for name in ask_size_fields if _as_float(ticker.get(name)) is not None),
            None,
        ),
        "liquidity_proxy_source": "ticker_bbo_and_24h_quote_volume",
    }


def _mexc_depth_side(levels: Any, *, side: str) -> tuple[float, float]:
    if not isinstance(levels, list):
        raise ValueError(f"MEXC depth {side} must be a list")
    parsed: list[tuple[float, float]] = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price = _as_float(level[0])
        size = _as_float(level[1])
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        parsed.append((price, size))
    if not parsed:
        raise ValueError(f"MEXC depth {side} has no positive levels")
    return (max(parsed) if side == "bids" else min(parsed))


def parse_mexc_depth_l1(payload: Any) -> dict[str, Any]:
    depth = _mexc_data(payload)
    if not isinstance(depth, dict):
        raise ValueError("MEXC depth payload must contain an object")
    bid_price, bid_size = _mexc_depth_side(depth.get("bids"), side="bids")
    ask_price, ask_size = _mexc_depth_side(depth.get("asks"), side="asks")
    if ask_price < bid_price:
        raise ValueError("MEXC depth is crossed")
    mid = (bid_price + ask_price) / 2.0
    return {
        "bid_price": bid_price,
        "ask_price": ask_price,
        "mid_price": mid,
        "spread_bps": ((ask_price - bid_price) / mid) * 10_000.0,
        "bid_size_contracts": bid_size,
        "ask_size_contracts": ask_size,
        "depth_snapshot_ts_ms": int(depth["timestamp"]) if depth.get("timestamp") is not None else None,
        "liquidity_proxy_source": "mexc_rest_depth_l1",
    }


def enrich_mexc_depth(
    rows: list[dict[str, Any]],
    *,
    fetch_depth: Callable[[str], Any],
    pace_sec: float = MEXC_DEPTH_REQUEST_INTERVAL_SEC,
    max_runtime_sec: float = MEXC_DEPTH_RUNTIME_BUDGET_SEC,
    max_workers: int = MEXC_DEPTH_MAX_WORKERS,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if pace_sec < 0 or max_runtime_sec < 0:
        raise ValueError("pace_sec and max_runtime_sec must be non-negative")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    output = [dict(row) for row in rows]
    targets = _mexc_depth_targets(output)
    errors: dict[str, str] = {}
    deadline = time.monotonic() + max_runtime_sec
    if not targets or time.monotonic() >= deadline:
        for pending in targets:
            symbol = str(pending.get("symbol") or "").upper()
            errors[symbol] = "TimeoutError: depth_enrichment_budget_exhausted"
        return output, errors

    executor = ThreadPoolExecutor(
        max_workers=min(max_workers, len(targets)),
        thread_name_prefix="mexc-depth",
    )
    futures: dict[Any, tuple[dict[str, Any], str]] = {}
    submitted_count = 0
    last_submitted_at: float | None = None
    try:
        for index, row in enumerate(targets):
            now = time.monotonic()
            if last_submitted_at is not None and pace_sec:
                sleep_sec = (last_submitted_at + pace_sec) - now
                if sleep_sec > 0:
                    if now + sleep_sec >= deadline:
                        break
                    time.sleep(sleep_sec)
            if time.monotonic() >= deadline:
                break
            symbol = str(row.get("symbol") or "").upper()
            future = executor.submit(fetch_depth, symbol)
            futures[future] = (row, symbol)
            submitted_count = index + 1
            last_submitted_at = time.monotonic()

        remaining = max(0.0, deadline - time.monotonic())
        completed, pending = wait(futures, timeout=remaining)
        for future in completed:
            row, symbol = futures[future]
            try:
                row.update(parse_mexc_depth_l1(future.result()))
                source = str(row.get("source_endpoint") or "").strip()
                depth_source = f"contract/depth/{symbol}"
                row["source_endpoint"] = f"{source} + {depth_source}" if source else depth_source
            except Exception as exc:  # noqa: BLE001 - preserve per-contract public depth failure.
                errors[symbol] = f"{type(exc).__name__}: {exc}"
        for future in pending:
            _row, symbol = futures[future]
            future.cancel()
            errors[symbol] = "TimeoutError: depth_enrichment_budget_exhausted"
        for row in targets[submitted_count:]:
            symbol = str(row.get("symbol") or "").upper()
            errors[symbol] = "TimeoutError: depth_enrichment_budget_exhausted"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return output, errors


def _mexc_depth_targets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    venues_by_base: dict[str, set[str]] = {}
    for row in rows:
        if row.get("listed_now") is not True or row.get("eligible_non_binance_spot") is not True:
            continue
        base = str(row.get("base") or "").upper()
        exchange = str(row.get("exchange") or "").lower()
        if base and exchange:
            venues_by_base.setdefault(base, set()).add(exchange)
    dual_bases = {
        base for base, venues in venues_by_base.items() if {"mexc", "gateio"}.issubset(venues)
    }
    return sorted(
        (
            row
            for row in rows
            if str(row.get("exchange") or "").lower() == "mexc"
            and row.get("listed_now") is True
            and row.get("eligible_non_binance_spot") is True
            and str(row.get("base") or "").upper() in dual_bases
        ),
        key=lambda row: str(row.get("symbol") or ""),
    )


def summarize_mexc_depth_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    targets = _mexc_depth_targets(rows)
    complete = sum(
        (_as_float(row.get("bid_size_contracts")) or 0.0) > 0.0
        and (_as_float(row.get("ask_size_contracts")) or 0.0) > 0.0
        for row in targets
    )
    total = len(targets)
    return {
        "targets": total,
        "complete": complete,
        "missing": total - complete,
        "coverage": complete / total if total else 0.0,
        "minimum_required_coverage": MIN_MEXC_DEPTH_COVERAGE,
    }


def annotate_binance_spot_membership(
    rows: list[dict[str, Any]],
    spot_symbols: set[str],
    reference_ts: str,
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        spot_symbol = f"{str(row.get('base') or '').upper()}{str(row.get('quote') or '').upper()}"
        listed = spot_symbol in spot_symbols
        row.update(
            {
                "binance_spot_symbol": spot_symbol,
                "binance_spot_listed": listed,
                "excluded_by_binance_spot": listed,
                "eligible_non_binance_spot": not listed,
                "binance_reference_ts": reference_ts,
            }
        )
        annotated.append(row)
    return annotated


def parse_mexc_contract_rows(
    payload: Any,
    tickers: dict[str, dict[str, Any]],
    snapshot_ts: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _mexc_data(payload):
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quoteCoin") or item.get("quoteCoinName") or "").upper()
        settle = str(item.get("settleCoin") or quote).upper()
        symbol = str(item.get("symbol") or "").upper()
        if not symbol or quote != "USDT" or settle != "USDT":
            continue
        raw_status = item.get("state")
        listed_now = int(raw_status if raw_status is not None else -1) == 0 and item.get("apiAllowed") is not False
        ticker = tickers.get(symbol, {})
        row = {
                "snapshot_ts": snapshot_ts,
                "exchange": "mexc",
                "symbol": symbol,
                "base": str(item.get("baseCoin") or item.get("baseCoinName") or "").upper(),
                "quote": quote,
                "contract_type": "linear_perp",
                "status": "trading" if listed_now else "inactive",
                "listed_now": listed_now,
                "inactive_or_delisted": not listed_now,
                "volume_24h_quote": _as_float(ticker.get("amount24")),
                **_bbo_metrics(ticker, ("bid1", "bidPrice", "bid"), ("ask1", "askPrice", "ask")),
                "mark_price": _as_float(ticker.get("fairPrice")),
                "index_price": _as_float(ticker.get("indexPrice")),
                "funding_rate": _as_float(ticker.get("fundingRate")),
                "funding_interval_sec": None,
                "funding_next_apply_ts": None,
                "contract_multiplier": _as_float(item.get("contractSize")),
                "minimum_order_size": _as_float(item.get("minVol")),
                "maximum_order_size": _as_float(item.get("maxVol")),
                "price_tick": _as_float(item.get("priceUnit")),
                "quantity_step": _as_float(item.get("volUnit")),
                "binance_spot_listed": None,
                "excluded_by_binance_spot": None,
                "eligible_non_binance_spot": None,
                "binance_reference_ts": None,
                "source_endpoint": "contract/detail + contract/ticker",
                "raw_status": raw_status,
                "first_seen_ts": None,
                "last_seen_ts": snapshot_ts,
            }
        rows.append(row)
    return rows


def parse_gate_contract_rows(
    payload: Any,
    tickers: dict[str, dict[str, Any]],
    snapshot_ts: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, list):
        return rows
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("name") or "").upper()
        if not symbol.endswith("_USDT"):
            continue
        raw_status = str(item.get("status") or "").lower()
        listed_now = raw_status == "trading"
        ticker = tickers.get(symbol, {})
        row = {
                "snapshot_ts": snapshot_ts,
                "exchange": "gateio",
                "symbol": symbol,
                "base": symbol.rsplit("_", 1)[0],
                "quote": "USDT",
                "contract_type": "linear_perp",
                "status": raw_status or "unknown",
                "listed_now": listed_now,
                "inactive_or_delisted": not listed_now,
                "volume_24h_quote": (
                    _as_float(ticker.get("volume_24h_quote"))
                    or _as_float(ticker.get("volume_24h_settle"))
                ),
                **_bbo_metrics(
                    ticker,
                    ("highest_bid", "bid"),
                    ("lowest_ask", "ask"),
                    ("highest_size", "bid_size"),
                    ("lowest_size", "ask_size"),
                ),
                "mark_price": _as_float(ticker.get("mark_price")) or _as_float(item.get("mark_price")),
                "index_price": _as_float(ticker.get("index_price")) or _as_float(item.get("index_price")),
                "funding_rate": _as_float(ticker.get("funding_rate")) or _as_float(item.get("funding_rate")),
                "funding_interval_sec": int(item["funding_interval"]) if item.get("funding_interval") else None,
                "funding_next_apply_ts": _as_float(item.get("funding_next_apply")),
                "contract_multiplier": _as_float(item.get("quanto_multiplier")),
                "minimum_order_size": _as_float(item.get("order_size_min")),
                "maximum_order_size": _as_float(item.get("order_size_max")),
                "price_tick": _as_float(item.get("order_price_round")),
                "quantity_step": 1.0 if item.get("enable_decimal") is not True else None,
                "binance_spot_listed": None,
                "excluded_by_binance_spot": None,
                "eligible_non_binance_spot": None,
                "binance_reference_ts": None,
                "source_endpoint": "futures/usdt/contracts + futures/usdt/tickers",
                "raw_status": raw_status,
                "first_seen_ts": None,
                "last_seen_ts": snapshot_ts,
            }
        rows.append(row)
    return rows


def missing_required_fields(row: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_SNAPSHOT_FIELDS if field not in row]


def summarize_rows(rows: list[dict[str, Any]], min_contracts_per_exchange: int) -> dict[str, Any]:
    by_exchange: dict[str, list[dict[str, Any]]] = {}
    missing_fields: dict[str, int] = {}
    for row in rows:
        by_exchange.setdefault(str(row.get("exchange") or ""), []).append(row)
        for field in missing_required_fields(row):
            missing_fields[field] = missing_fields.get(field, 0) + 1

    exchange_summary: dict[str, dict[str, Any]] = {}
    for exchange in ("mexc", "gateio"):
        exchange_rows = by_exchange.get(exchange, [])
        exchange_summary[exchange] = {
            "rows": len(exchange_rows),
            "listed_now": sum(1 for row in exchange_rows if row.get("listed_now")),
            "inactive_or_delisted": sum(1 for row in exchange_rows if row.get("inactive_or_delisted")),
            "rows_with_volume": sum(1 for row in exchange_rows if _as_float(row.get("volume_24h_quote")) is not None),
            "rows_with_spread": sum(1 for row in exchange_rows if _as_float(row.get("spread_bps")) is not None),
            "non_binance_spot": sum(1 for row in exchange_rows if row.get("eligible_non_binance_spot") is True),
            "pass_min_contracts": len(exchange_rows) >= min_contracts_per_exchange,
        }

    accepted = (
        all(item["pass_min_contracts"] for item in exchange_summary.values())
        and not missing_fields
        and all(item["rows_with_volume"] > 0 for item in exchange_summary.values())
    )
    return {
        "accepted": accepted,
        "decision": ACCEPTED_DECISION if accepted else REJECTED_DECISION,
        "rows_total": len(rows),
        "required_fields": list(REQUIRED_SNAPSHOT_FIELDS),
        "missing_required_fields": missing_fields,
        "min_contracts_per_exchange": min_contracts_per_exchange,
        "exchanges": exchange_summary,
    }


def build_plan_report(output_path: Path | None, min_contracts_per_exchange: int) -> dict[str, Any]:
    return {
        "mode": "pit_universe_public_probe_plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": PLAN_DECISION,
        "selected_branch": "forward_pit_universe_event_liquidity_anomaly",
        "research_only": True,
        "would_start": False,
        "confirmed_public_probe": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "strategy_accepted": False,
        "output_path": str(output_path) if output_path else None,
        "params": {"min_contracts_per_exchange": min_contracts_per_exchange},
        "endpoints": {
            "mexc_contracts": MEXC_CONTRACTS_URL,
            "mexc_tickers": MEXC_TICKERS_URL,
            "gate_contracts": GATE_CONTRACTS_URL,
            "gate_tickers": GATE_TICKERS_URL,
            "binance_spot_reference": BINANCE_SPOT_EXCHANGE_INFO_URL,
        },
        "required_snapshot_fields": list(REQUIRED_SNAPSHOT_FIELDS),
        "network_calls_now": False,
        "next_valid_moves": [
            "Run the same wrapper with -ConfirmedPublicProbe -UpdateGate -Json for a short public REST probe.",
            "If accepted, build a visible PIT snapshot collector approval packet.",
            "Do not run long collect/replay/grid/live/API-key/paper-forward from this plan.",
        ],
    }


def run_public_probe(
    *,
    output_path: Path | None,
    min_contracts_per_exchange: int,
    timeout_sec: int,
    include_mexc_depth: bool = False,
) -> dict[str, Any]:
    snapshot_ts = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    session.trust_env = False
    errors: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    binance_spot_symbols: set[str] | None = None
    depth_errors: dict[str, str] = {}

    try:
        binance_spot_symbols = parse_binance_spot_symbols(
            _get_json(session, BINANCE_SPOT_EXCHANGE_INFO_URL, timeout_sec)
        )
    except Exception as exc:  # noqa: BLE001 - exclusion reference failure must reject the probe.
        errors["binance_spot_reference"] = f"{type(exc).__name__}: {exc}"

    try:
        mexc_contracts = _get_json(session, MEXC_CONTRACTS_URL, timeout_sec)
        mexc_tickers = mexc_ticker_map(_get_json(session, MEXC_TICKERS_URL, timeout_sec))
        rows.extend(parse_mexc_contract_rows(mexc_contracts, mexc_tickers, snapshot_ts))
    except Exception as exc:  # noqa: BLE001 - probe artifact must preserve endpoint failure.
        errors["mexc"] = f"{type(exc).__name__}: {exc}"

    try:
        gate_contracts = _get_json(session, GATE_CONTRACTS_URL, timeout_sec)
        gate_tickers = gate_ticker_map(_get_json(session, GATE_TICKERS_URL, timeout_sec))
        rows.extend(parse_gate_contract_rows(gate_contracts, gate_tickers, snapshot_ts))
    except Exception as exc:  # noqa: BLE001 - probe artifact must preserve endpoint failure.
        errors["gateio"] = f"{type(exc).__name__}: {exc}"

    if binance_spot_symbols is not None:
        rows = annotate_binance_spot_membership(rows, binance_spot_symbols, snapshot_ts)
    if include_mexc_depth:
        def fetch_mexc_depth(symbol: str) -> Any:
            # Keep mutable requests.Session state isolated across depth workers.
            with requests.Session() as depth_session:
                depth_session.trust_env = False
                return _get_json(
                    depth_session,
                    MEXC_DEPTH_URL_TEMPLATE.format(symbol=symbol),
                    timeout_sec,
                )

        rows, depth_errors = enrich_mexc_depth(
            rows,
            fetch_depth=fetch_mexc_depth,
        )

    summary = summarize_rows(rows, min_contracts_per_exchange=min_contracts_per_exchange)
    depth_summary = summarize_mexc_depth_coverage(rows)
    summary["mexc_depth"] = depth_summary
    if include_mexc_depth and (
        depth_summary["targets"] == 0
        or depth_summary["coverage"] < MIN_MEXC_DEPTH_COVERAGE
    ):
        summary["accepted"] = False
        summary["decision"] = REJECTED_DECISION
    if errors:
        summary["accepted"] = False
        summary["decision"] = REJECTED_DECISION

    return {
        "mode": "pit_universe_public_probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": summary["decision"],
        "selected_branch": "forward_pit_universe_event_liquidity_anomaly",
        "research_only": True,
        "would_start": True,
        "confirmed_public_probe": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "strategy_accepted": False,
        "output_path": str(output_path) if output_path else None,
        "params": {
            "min_contracts_per_exchange": min_contracts_per_exchange,
            "timeout_sec": timeout_sec,
            "include_mexc_depth": include_mexc_depth,
            "mexc_depth_runtime_budget_sec": MEXC_DEPTH_RUNTIME_BUDGET_SEC,
            "mexc_depth_request_interval_sec": MEXC_DEPTH_REQUEST_INTERVAL_SEC,
            "mexc_depth_max_workers": MEXC_DEPTH_MAX_WORKERS,
        },
        "errors": errors,
        "depth_errors": depth_errors,
        "binance_spot_reference_available": binance_spot_symbols is not None,
        "summary": summary,
        "sample_rows": rows[:25],
        "rows": rows,
        "next_valid_moves": (
            [
                "Build a visible PIT universe snapshot collector approval packet.",
                "Actual long collect still requires explicit user confirmation and visible monitor.",
                "Replay/grid/live/API-key/paper-forward remain blocked.",
            ]
            if summary["decision"] == ACCEPTED_DECISION
            else [
                "Reject or rescope forward_pit_universe_event_liquidity_anomaly.",
                "Do not start collect/replay/grid/live/API-key/paper-forward.",
            ]
        ),
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(output_path)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="PIT universe public REST probe for MEXC/Gate")
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-contracts-per-exchange", type=int, default=50)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()

    output_path = Path(args.out)
    if args.probe:
        report = run_public_probe(
            output_path=output_path,
            min_contracts_per_exchange=args.min_contracts_per_exchange,
            timeout_sec=args.timeout_sec,
        )
    else:
        report = build_plan_report(
            output_path=output_path,
            min_contracts_per_exchange=args.min_contracts_per_exchange,
        )
    write_report(report, output_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
