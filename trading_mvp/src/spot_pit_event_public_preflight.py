from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from universe import UniverseRow, is_focus_candidate


PLAN_SCHEMA = "spot_pit_event_forward_plan_v1"
REPORT_SCHEMA = "spot_pit_event_public_preflight_v1"
MEXC_INFO = "https://api.mexc.com/api/v3/exchangeInfo"
MEXC_BOOK = "https://api.mexc.com/api/v3/ticker/bookTicker"
MEXC_24H = "https://api.mexc.com/api/v3/ticker/24hr"
GATE_PAIRS = "https://api.gateio.ws/api/v4/spot/currency_pairs"
GATE_TICKERS = "https://api.gateio.ws/api/v4/spot/tickers"
BINANCE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
COINPAPRIKA_TICKERS = "https://api.coinpaprika.com/v1/tickers?quotes=USD"

FetchResult = tuple[Any, float]
Fetcher = Callable[[str], FetchResult]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_fetcher(timeout_sec: int) -> Fetcher:
    session = requests.Session()
    session.trust_env = False

    def fetch(url: str) -> FetchResult:
        last_error: Exception | None = None
        for attempt in range(3):
            started = time.perf_counter()
            try:
                response = session.get(url, timeout=timeout_sec)
                response.raise_for_status()
                return response.json(), time.perf_counter() - started
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"public GET failed: {url}: {last_error}")

    return fetch


def _rows(value: Any, *, key: str | None = None) -> list[dict[str, Any]]:
    if key and isinstance(value, dict):
        value = value.get(key)
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _mexc_markets(info: Any, book: Any, tickers: Any) -> dict[str, dict[str, Any]]:
    books = {str(row.get("symbol") or ""): row for row in _rows(book)}
    stats = {str(row.get("symbol") or ""): row for row in _rows(tickers)}
    markets: dict[str, dict[str, Any]] = {}
    for row in _rows(info, key="symbols"):
        if str(row.get("quoteAsset") or "").upper() != "USDT":
            continue
        if str(row.get("status") or "").upper() not in {"1", "TRADING", "ENABLED"}:
            continue
        symbol = str(row.get("symbol") or "")
        base = str(row.get("baseAsset") or "").upper()
        bbo = books.get(symbol, {})
        ticker = stats.get(symbol, {})
        bid = _float(bbo.get("bidPrice"))
        ask = _float(bbo.get("askPrice"))
        quote_volume = _float(ticker.get("quoteVolume"))
        if bid is not None and ask is not None and bid > 0 and ask >= bid:
            spread = (ask - bid) / ((ask + bid) / 2.0) * 10000.0
        else:
            spread = None
        markets[base] = {
            "exchange": "mexc",
            "symbol": symbol,
            "base": base,
            "bid": bid,
            "ask": ask,
            "bid_qty": _float(bbo.get("bidQty")),
            "ask_qty": _float(bbo.get("askQty")),
            "last": _float(ticker.get("lastPrice")),
            "quote_volume_24h": quote_volume,
            "spread_bps": spread,
            "bbo_complete": bid is not None and ask is not None and bid > 0 and ask >= bid,
            "volume_complete": quote_volume is not None,
        }
    return markets


def _gate_markets(pairs: Any, tickers: Any) -> dict[str, dict[str, Any]]:
    ticker_rows = {str(row.get("currency_pair") or ""): row for row in _rows(tickers)}
    markets: dict[str, dict[str, Any]] = {}
    for row in _rows(pairs):
        if str(row.get("quote") or "").upper() != "USDT" or str(row.get("trade_status") or "").lower() != "tradable":
            continue
        symbol = str(row.get("id") or "")
        base = str(row.get("base") or "").upper()
        ticker = ticker_rows.get(symbol, {})
        bid = _float(ticker.get("highest_bid"))
        ask = _float(ticker.get("lowest_ask"))
        quote_volume = _float(ticker.get("quote_volume"))
        if bid is not None and ask is not None and bid > 0 and ask >= bid:
            spread = (ask - bid) / ((ask + bid) / 2.0) * 10000.0
        else:
            spread = None
        markets[base] = {
            "exchange": "gateio",
            "symbol": symbol,
            "base": base,
            "bid": bid,
            "ask": ask,
            "bid_qty": None,
            "ask_qty": None,
            "last": _float(ticker.get("last")),
            "quote_volume_24h": quote_volume,
            "spread_bps": spread,
            "bbo_complete": bid is not None and ask is not None and bid > 0 and ask >= bid,
            "volume_complete": quote_volume is not None,
        }
    return markets


def _binance_bases(info: Any) -> set[str]:
    out: set[str] = set()
    for row in _rows(info, key="symbols"):
        if str(row.get("status") or "").upper() != "TRADING":
            continue
        base = str(row.get("baseAsset") or "").upper()
        if base:
            out.add(base)
    return out


def _ranked_focus(tickers: Any) -> list[UniverseRow]:
    result: list[UniverseRow] = []
    for row in _rows(tickers):
        try:
            rank = int(row.get("rank") or 0)
        except (TypeError, ValueError):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if rank <= 0 or not symbol:
            continue
        quotes = row.get("quotes") if isinstance(row.get("quotes"), dict) else {}
        usd = quotes.get("USD") if isinstance(quotes.get("USD"), dict) else {}
        candidate = UniverseRow(
            rank=rank,
            symbol=symbol,
            name=str(row.get("name") or ""),
            coin_id=str(row.get("id") or ""),
            market_cap_usd=float(usd.get("market_cap") or 0),
            price_usd=float(usd.get("price") or 0),
        )
        if is_focus_candidate(candidate):
            result.append(candidate)
    return sorted(result, key=lambda row: (row.rank, row.symbol))


def build_preflight(
    plan_path: str | Path,
    *,
    expected_plan_sha256: str | None = None,
    fetcher: Fetcher | None = None,
    timeout_sec: int = 15,
) -> dict[str, Any]:
    plan_file = Path(plan_path)
    plan_hash = _sha(plan_file)
    if expected_plan_sha256 and plan_hash.lower() != expected_plan_sha256.lower():
        raise ValueError(f"plan sha256 mismatch: expected={expected_plan_sha256}, observed={plan_hash}")
    plan = json.loads(plan_file.read_text(encoding="utf-8-sig"))
    if plan.get("schema") != PLAN_SCHEMA or plan.get("research_only") is not True or plan.get("strategy_accepted") is not False:
        raise ValueError("invalid spot PIT forward plan contract")
    fetch = fetcher or _default_fetcher(timeout_sec)
    payloads: dict[str, Any] = {}
    latencies: dict[str, float] = {}
    errors: dict[str, str] = {}
    endpoints = {
        "mexc_exchange_info": MEXC_INFO,
        "mexc_book_ticker": MEXC_BOOK,
        "mexc_24h": MEXC_24H,
        "gate_pairs": GATE_PAIRS,
        "gate_tickers": GATE_TICKERS,
        "binance_exchange_info": BINANCE_INFO,
        "coinpaprika_tickers": COINPAPRIKA_TICKERS,
    }
    for name, url in endpoints.items():
        try:
            payloads[name], latencies[name] = fetch(url)
        except Exception as exc:  # noqa: BLE001 - report every public endpoint failure
            errors[name] = str(exc)
            payloads[name] = None
            latencies[name] = 0.0

    mexc = _mexc_markets(payloads["mexc_exchange_info"], payloads["mexc_book_ticker"], payloads["mexc_24h"])
    gate = _gate_markets(payloads["gate_pairs"], payloads["gate_tickers"])
    binance = _binance_bases(payloads["binance_exchange_info"])
    ranked = _ranked_focus(payloads["coinpaprika_tickers"])
    max_bases = int(plan["universe"]["max_initial_bases"])
    candidates = []
    seen: set[str] = set()
    for coin in ranked:
        if coin.symbol in seen or coin.symbol in binance or (coin.symbol not in mexc and coin.symbol not in gate):
            continue
        seen.add(coin.symbol)
        venues = [venue for venue, markets in (("mexc", mexc), ("gateio", gate)) if coin.symbol in markets]
        candidate = {
            "rank": coin.rank,
            "base": coin.symbol,
            "name": coin.name,
            "coin_id": coin.coin_id,
            "venues": venues,
            "two_venue": len(venues) == 2,
            "mexc": mexc.get(coin.symbol),
            "gateio": gate.get(coin.symbol),
        }
        candidates.append(candidate)
        if len(candidates) >= max_bases:
            break

    mexc_bbo = sum(int(row["bbo_complete"]) for row in mexc.values())
    gate_bbo = sum(int(row["bbo_complete"]) for row in gate.values())
    mexc_volume = sum(int(row["volume_complete"]) for row in mexc.values())
    gate_volume = sum(int(row["volume_complete"]) for row in gate.values())
    two_venue = sum(int(row["two_venue"]) for row in candidates)
    checks = {
        "all_public_endpoints_succeeded": not errors,
        "mexc_tradable_usdt_pairs": len(mexc) >= 15,
        "gate_tradable_usdt_pairs": len(gate) >= 15,
        "mexc_bbo_coverage": mexc_bbo >= 15,
        "gate_bbo_coverage": gate_bbo >= 15,
        "mexc_quote_volume_coverage": mexc_volume >= 15,
        "gate_quote_volume_coverage": gate_volume >= 15,
        "frozen_non_binance_focus_universe": len(candidates) >= 15,
        "two_venue_non_binance_bases": two_venue >= 8,
        "latency_headroom": all(value <= timeout_sec for value in latencies.values()),
    }
    accepted = all(checks.values())
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": "SPOT_PIT_EVENT_PUBLIC_PREFLIGHT_ACCEPTED_READY_FOR_COLLECTOR_IMPLEMENTATION" if accepted else "SPOT_PIT_EVENT_PUBLIC_PREFLIGHT_REJECTED_FIX_BEFORE_COLLECTOR",
        "accepted": accepted,
        "research_only": True,
        "would_start_collect": False,
        "collect_allowed_now": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "paper_forward_allowed": False,
        "plan_path": str(plan_file),
        "plan_sha256": plan_hash,
        "checks": checks,
        "errors": errors,
        "latency_sec": latencies,
        "coverage": {
            "mexc_tradable_usdt_pairs": len(mexc),
            "gate_tradable_usdt_pairs": len(gate),
            "mexc_bbo_complete": mexc_bbo,
            "gate_bbo_complete": gate_bbo,
            "mexc_quote_volume_complete": mexc_volume,
            "gate_quote_volume_complete": gate_volume,
            "ranked_focus_rows": len(ranked),
            "frozen_candidates": len(candidates),
            "two_venue_candidates": two_venue,
        },
        "frozen_universe_preview": candidates,
        "next_step": "Implement the durable visible collector against this exact normalized schema; actual 14-day start still requires a separate explicit confirmation." if accepted else "Fix endpoint/schema/coverage failures and repeat only the short public preflight.",
    }


def run_preflight(plan_path: str | Path, output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    report = build_preflight(plan_path, **kwargs)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(target)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Short public endpoint/schema preflight for forward spot PIT research.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-sec", type=int, default=15)
    args = parser.parse_args()
    report = run_preflight(args.plan, args.output, expected_plan_sha256=args.expected_plan_sha256, timeout_sec=args.timeout_sec)
    print(json.dumps({"output": args.output, "decision": report["decision"], "accepted": report["accepted"], "coverage": report["coverage"], "errors": report["errors"]}, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
