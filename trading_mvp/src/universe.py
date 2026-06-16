from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests


BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
COINPAPRIKA_TICKERS_URL = "https://api.coinpaprika.com/v1/tickers?quotes=USD"

DERIVATIVE_SYMBOLS = {
    "ALUSD",
    "BETH",
    "BTC.B",
    "BTCB",
    "CBBTC",
    "CBETH",
    "EBTC",
    "ETHX",
    "FRXETH",
    "GHO",
    "JITOSOL",
    "LBTC",
    "METH",
    "MSOL",
    "OHMV2",
    "PYUSD",
    "RETH",
    "RSETH",
    "SOLVBTC",
    "STETH",
    "STKAAVE",
    "SUSDE",
    "SUSDS",
    "TBTC",
    "TETH",
    "USDAI",
    "USDC.E",
    "USDG",
    "USDF",
    "USDTB",
    "WBNB",
    "WBTC",
    "WEETH",
    "WETH",
    "WSTETH",
    "WTRX",
}

STABLE_SYMBOLS = {
    "DAI",
    "EURC",
    "FRAX",
    "LUSD",
    "STABLE",
    "TUSD",
    "USDB",
    "USDC",
    "USDD",
    "USDE",
    "USDF",
    "USDG",
    "USDP",
    "USDT",
    "USDTB",
    "USD0",
    "USDX",
}

DERIVATIVE_NAME_MARKERS = (
    "wrapped",
    "staked",
    "restaked",
    "liquid staked",
    "binance-peg",
    "coinbase wrapped",
    "bridged",
    "beacon eth",
    "rocket pool eth",
    "frax ether",
    "treehouse eth",
    "solv protocol",
    "lombard staked",
    "kinetiq staked",
    "jito staked",
    "marinade staked",
)

STABLE_NAME_MARKERS = (
    "stablecoin",
    "usd ",
    " dollar",
    "paypal usd",
    "euro coin",
    "usual usd",
    "falcon usd",
    "global dollar",
)


@dataclass(frozen=True)
class UniverseRow:
    rank: int
    symbol: str
    name: str
    coin_id: str
    market_cap_usd: float
    price_usd: float


def fetch_json(url: str, timeout_sec: int = 30) -> Any:
    response = requests.get(url, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def binance_assets_from_exchange_info(exchange_info: dict[str, Any]) -> set[str]:
    assets: set[str] = set()
    for symbol_info in exchange_info.get("symbols", []):
        if symbol_info.get("status") != "TRADING":
            continue
        base = str(symbol_info.get("baseAsset", "")).strip().upper()
        quote = str(symbol_info.get("quoteAsset", "")).strip().upper()
        if base:
            assets.add(base)
        if quote:
            assets.add(quote)
    return assets


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def no_binance_rows(
    ranked_tickers: list[dict[str, Any]],
    binance_assets: set[str],
) -> list[UniverseRow]:
    rows: list[UniverseRow] = []
    for coin in sorted(ranked_tickers, key=lambda item: int(item.get("rank") or 10**9)):
        rank = coin.get("rank")
        if rank is None:
            continue
        symbol = str(coin.get("symbol", "")).strip().upper()
        if not symbol or symbol in binance_assets:
            continue
        usd = (coin.get("quotes") or {}).get("USD") or {}
        rows.append(
            UniverseRow(
                rank=int(rank),
                symbol=symbol,
                name=str(coin.get("name", "")),
                coin_id=str(coin.get("id", "")),
                market_cap_usd=round(_float_or_zero(usd.get("market_cap")), 2),
                price_usd=round(_float_or_zero(usd.get("price")), 10),
            )
        )
    return rows


def is_focus_candidate(row: UniverseRow) -> bool:
    symbol = row.symbol.strip().upper()
    name = row.name.lower()
    is_derivative = (
        symbol in DERIVATIVE_SYMBOLS
        or "." in symbol
        or any(marker in name for marker in DERIVATIVE_NAME_MARKERS)
    )
    is_stable = symbol in STABLE_SYMBOLS or any(
        marker in f" {name} " for marker in STABLE_NAME_MARKERS
    )
    return not is_derivative and not is_stable


def write_universe_files(
    rows: list[UniverseRow],
    out_dir: Path,
    date_stamp: str | None = None,
    top_preview: int = 100,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date_stamp or date.today().isoformat()
    focus_rows = [row for row in rows if is_focus_candidate(row)]

    full_csv = out_dir / f"no_binance_full_{stamp}.csv"
    focus_csv = out_dir / f"no_binance_focus_{stamp}.csv"
    symbols_txt = out_dir / f"no_binance_focus_symbols_{stamp}.txt"
    top_txt = out_dir / f"no_binance_focus_top{top_preview}_{stamp}.txt"

    _write_csv(full_csv, rows)
    _write_csv(focus_csv, focus_rows)
    symbols_txt.write_text(
        "\n".join(row.symbol for row in focus_rows) + "\n",
        encoding="utf-8",
    )
    top_txt.write_text(
        "\n".join(
            f"{row.rank}\t{row.symbol}\t{row.name}\t{row.coin_id}"
            for row in focus_rows[:top_preview]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "no_binance_full": len(rows),
        "no_binance_focus": len(focus_rows),
        "full_csv": str(full_csv),
        "focus_csv": str(focus_csv),
        "focus_symbols_txt": str(symbols_txt),
        "top_preview_txt": str(top_txt),
    }


def _write_csv(path: Path, rows: list[UniverseRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "rank",
                "symbol",
                "name",
                "coin_id",
                "market_cap_usd",
                "price_usd",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)
