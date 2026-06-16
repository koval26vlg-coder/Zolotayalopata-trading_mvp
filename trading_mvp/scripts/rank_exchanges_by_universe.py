from __future__ import annotations

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import requests


COINPAPRIKA_EXCHANGES_URL = "https://api.coinpaprika.com/v1/exchanges?quotes=USD"
COINPAPRIKA_MARKETS_URL = "https://api.coinpaprika.com/v1/exchanges/{exchange_id}/markets?quotes=USD"
COINGECKO_EXCHANGES_URL = "https://api.coingecko.com/api/v3/exchanges?per_page=250&page={page}"

COINGECKO_ID_ALIASES = {
    "ascendex": "ascendex",
    "azbit": "azbit",
    "binance-us": "binance_us",
    "bingx": "bingx",
    "bitfinex": "bitfinex",
    "bitget": "bitget",
    "bithumb": "bithumb",
    "bitmart": "bitmart",
    "bitrue": "bitrue",
    "bitstamp": "bitstamp",
    "bitvavo": "bitvavo",
    "btse": "btse",
    "bybit-spot": "bybit_spot",
    "coinbase": "gdax",
    "coinex": "coinex",
    "coinw": "coinw",
    "cryptocom-exchange": "crypto_com",
    "digifinex": "digifinex",
    "gateio": "gate",
    "gemini": "gemini",
    "hitbtc": "hitbtc",
    "htx": "huobi",
    "kraken": "kraken",
    "kucoin": "kucoin",
    "latoken": "latoken",
    "lbank": "lbank",
    "mexc": "mxc",
    "okx": "okex",
    "phemex": "phemex",
    "pionex": "pionex",
    "poloniex": "poloniex",
    "upbit": "upbit",
    "weex": "weex",
    "whitebit": "whitebit",
    "xt": "xt",
    "yobit": "yobit",
}


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def get_json(url: str, timeout: int = 30) -> Any:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def read_universe(path: Path) -> tuple[set[str], dict[str, str]]:
    ids: set[str] = set()
    names_by_id: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            coin_id = (row.get("coin_id") or "").strip()
            symbol = (row.get("symbol") or "").strip()
            if not coin_id:
                continue
            ids.add(coin_id)
            names_by_id[coin_id] = symbol
    return ids, names_by_id


def load_coingecko_ranks() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for page in range(1, 6):
        payload = get_json(COINGECKO_EXCHANGES_URL.format(page=page))
        if not payload:
            break
        for exchange in payload:
            by_id[exchange["id"]] = exchange
            by_name[normalize_name(exchange.get("name", ""))] = exchange
    return by_id, by_name


def coingecko_rank(
    exchange: dict[str, Any],
    cg_by_id: dict[str, dict[str, Any]],
    cg_by_name: dict[str, dict[str, Any]],
) -> tuple[int | None, str | None, str | None]:
    exchange_id = exchange["id"]
    cg_id = COINGECKO_ID_ALIASES.get(exchange_id)
    candidate = cg_by_id.get(cg_id) if cg_id else None
    if candidate is None:
        candidate = cg_by_name.get(normalize_name(exchange.get("name", "")))
    if candidate is None:
        return None, None, None
    return (
        candidate.get("trust_score_rank"),
        candidate.get("id"),
        candidate.get("name"),
    )


def is_spot_cex_candidate(exchange: dict[str, Any], min_currencies: int) -> bool:
    name = str(exchange.get("name", ""))
    exchange_id = str(exchange.get("id", ""))
    types = exchange.get("type") or []
    if not exchange.get("active") or not exchange.get("markets_data_fetched"):
        return False
    if "cex" not in types:
        return False
    if exchange.get("currencies", 0) < min_currencies:
        return False
    if exchange_id == "binance":
        return False
    return not re.search(r"futures|perpetual|derivative", f"{name} {exchange_id}", re.I)


def fetch_exchange_coverage(
    exchange: dict[str, Any],
    focus_ids: set[str],
    full_ids: set[str],
    symbols_by_id: dict[str, str],
) -> dict[str, Any]:
    exchange_id = exchange["id"]
    markets = get_json(COINPAPRIKA_MARKETS_URL.format(exchange_id=exchange_id))
    market_coin_ids: set[str] = set()
    for market in markets:
        for field in ("base_currency_id", "quote_currency_id"):
            coin_id = str(market.get(field) or "").strip()
            if coin_id:
                market_coin_ids.add(coin_id)

    focus_matches = sorted(focus_ids & market_coin_ids, key=lambda coin_id: symbols_by_id.get(coin_id, coin_id))
    full_matches = full_ids & market_coin_ids
    return {
        "coinpaprika_id": exchange_id,
        "name": exchange.get("name"),
        "coinpaprika_adjusted_rank": exchange.get("adjusted_rank"),
        "coinpaprika_currencies": exchange.get("currencies"),
        "coinpaprika_markets": exchange.get("markets"),
        "focus_count": len(focus_matches),
        "full_count": len(full_matches),
        "sample_focus_symbols": " ".join(symbols_by_id.get(coin_id, coin_id) for coin_id in focus_matches[:40]),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "coverage_rank",
        "name",
        "coinpaprika_id",
        "focus_count",
        "full_count",
        "coingecko_trust_score_rank",
        "coingecko_id",
        "coingecko_name",
        "coinpaprika_adjusted_rank",
        "coinpaprika_currencies",
        "coinpaprika_markets",
        "sample_focus_symbols",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focus-csv", required=True, type=Path)
    parser.add_argument("--full-csv", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--date-stamp", default=date.today().isoformat())
    parser.add_argument("--min-currencies", type=int, default=50)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    focus_ids, focus_symbols = read_universe(args.focus_csv)
    full_ids, full_symbols = read_universe(args.full_csv)
    symbols_by_id = {**full_symbols, **focus_symbols}

    exchanges = get_json(COINPAPRIKA_EXCHANGES_URL)
    candidates = [
        exchange
        for exchange in exchanges
        if is_spot_cex_candidate(exchange, args.min_currencies)
    ]

    cg_by_id, cg_by_name = load_coingecko_ranks()
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(fetch_exchange_coverage, exchange, focus_ids, full_ids, symbols_by_id): exchange
            for exchange in candidates
        }
        for future in as_completed(futures):
            exchange = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001
                errors.append({"id": exchange["id"], "name": exchange.get("name"), "error": str(exc)})
                continue
            rank, cg_id, cg_name = coingecko_rank(exchange, cg_by_id, cg_by_name)
            row["coingecko_trust_score_rank"] = rank
            row["coingecko_id"] = cg_id
            row["coingecko_name"] = cg_name
            rows.append(row)

    rows.sort(
        key=lambda row: (
            -int(row["focus_count"]),
            -int(row["full_count"]),
            row["coingecko_trust_score_rank"] or 10**9,
            str(row["name"]),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["coverage_rank"] = index

    out_csv = args.out_dir / f"exchange_coverage_no_binance_{args.date_stamp}.csv"
    out_json = args.out_dir / f"exchange_coverage_no_binance_{args.date_stamp}.summary.json"
    write_csv(out_csv, rows)
    out_json.write_text(
        json.dumps(
            {
                "focus_universe": len(focus_ids),
                "full_universe": len(full_ids),
                "candidate_exchanges": len(candidates),
                "ranked_exchanges": len(rows),
                "errors": errors,
                "output_csv": str(out_csv),
                "top_20": rows[:20],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "output_csv": str(out_csv), "summary_json": str(out_json), "ranked_exchanges": len(rows), "errors": len(errors)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
