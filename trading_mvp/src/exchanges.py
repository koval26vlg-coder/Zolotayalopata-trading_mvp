from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class MarketPair:
    exchange: str
    symbol: str
    base: str
    quote: str


@dataclass(frozen=True)
class MarketSnapshot:
    exchange: str
    symbol: str
    ts: float
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    spread_bps: float
    imbalance: float
    signed_flow_notional: float
    new_trade_count: int
    last_trade_price: float | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class PublicSpotClient:
    exchange_id = ""
    display_name = ""

    def __init__(self, timeout_sec: int = 10) -> None:
        self.timeout_sec = timeout_sec
        self.session = requests.Session()
        self.session.trust_env = False
        self._last_trade_ids: dict[str, int] = {}

    def fetch_pairs(self, quote: str = "USDT") -> list[MarketPair]:
        raise NotImplementedError

    def fetch_snapshot(self, pair: MarketPair, depth_limit: int, trades_limit: int) -> MarketSnapshot:
        depth = self._fetch_depth(pair, depth_limit)
        trades = self._fetch_trades(pair, trades_limit)
        return self._snapshot_from_payloads(pair, depth, trades)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_sec)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Не удалось выполнить GET {url}")

    def _fetch_depth(self, pair: MarketPair, depth_limit: int) -> Any:
        raise NotImplementedError

    def _fetch_trades(self, pair: MarketPair, trades_limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _snapshot_from_payloads(
        self,
        pair: MarketPair,
        depth: Any,
        trades: list[dict[str, Any]],
    ) -> MarketSnapshot:
        bids, asks = self._extract_book(depth)
        if not bids or not asks:
            raise RuntimeError(f"{pair.exchange}:{pair.symbol}: пустой стакан")
        bid, bid_qty = float(bids[0][0]), float(bids[0][1])
        ask, ask_qty = float(asks[0][0]), float(asks[0][1])
        mid = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / mid) * 1e4 if mid else 0.0
        denom = bid_qty + ask_qty
        imbalance = (bid_qty - ask_qty) / denom if denom else 0.0
        flow, count, last_price = self._signed_flow(pair.symbol, trades)
        return MarketSnapshot(
            exchange=pair.exchange,
            symbol=pair.symbol,
            ts=time.time(),
            bid=bid,
            ask=ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            spread_bps=spread_bps,
            imbalance=imbalance,
            signed_flow_notional=flow,
            new_trade_count=count,
            last_trade_price=last_price,
        )

    def _extract_book(self, depth: Any) -> tuple[list[list[Any]], list[list[Any]]]:
        return depth["bids"], depth["asks"]

    def _signed_flow(self, symbol: str, trades: list[dict[str, Any]]) -> tuple[float, int, float | None]:
        if not trades:
            return 0.0, 0, None
        normalized: list[tuple[int, dict[str, Any]]] = []
        for trade in trades:
            trade_id = self._trade_key(trade)
            if trade_id is not None:
                normalized.append((trade_id, trade))
        normalized.sort(key=lambda item: item[0])
        if not normalized:
            return 0.0, 0, None
        last_seen = self._last_trade_ids.get(symbol)
        max_seen = normalized[-1][0]
        if last_seen is None:
            self._last_trade_ids[symbol] = max_seen
            last_price = float(self._trade_price(normalized[-1][1]))
            return 0.0, 0, last_price

        signed_flow = 0.0
        new_count = 0
        last_price: float | None = None
        for trade_id, trade in normalized:
            if trade_id <= last_seen:
                continue
            price = float(self._trade_price(trade))
            qty = float(self._trade_qty(trade))
            signed_flow += self._trade_side_sign(trade) * price * qty
            new_count += 1
            last_price = price
        self._last_trade_ids[symbol] = max(max_seen, last_seen)
        return signed_flow, new_count, last_price

    def _trade_key(self, trade: dict[str, Any]) -> int | None:
        raise NotImplementedError

    def _trade_price(self, trade: dict[str, Any]) -> float:
        raise NotImplementedError

    def _trade_qty(self, trade: dict[str, Any]) -> float:
        raise NotImplementedError

    def _trade_side_sign(self, trade: dict[str, Any]) -> float:
        raise NotImplementedError


class MexcSpotClient(PublicSpotClient):
    exchange_id = "mexc"
    display_name = "MEXC"
    base_url = "https://api.mexc.com"

    def fetch_pairs(self, quote: str = "USDT") -> list[MarketPair]:
        data = self._get(f"{self.base_url}/api/v3/exchangeInfo")
        out: list[MarketPair] = []
        for item in data.get("symbols", []):
            if str(item.get("quoteAsset", "")).upper() != quote:
                continue
            if str(item.get("status", "")).upper() not in {"1", "TRADING", "ENABLED"}:
                continue
            out.append(
                MarketPair(
                    exchange=self.exchange_id,
                    symbol=str(item["symbol"]),
                    base=str(item["baseAsset"]).upper(),
                    quote=str(item["quoteAsset"]).upper(),
                )
            )
        return out

    def _fetch_depth(self, pair: MarketPair, depth_limit: int) -> Any:
        return self._get(
            f"{self.base_url}/api/v3/depth",
            {"symbol": pair.symbol, "limit": min(depth_limit, 100)},
        )

    def _fetch_trades(self, pair: MarketPair, trades_limit: int) -> list[dict[str, Any]]:
        return self._get(
            f"{self.base_url}/api/v3/trades",
            {"symbol": pair.symbol, "limit": min(trades_limit, 100)},
        )

    def _trade_key(self, trade: dict[str, Any]) -> int | None:
        value = trade.get("id")
        return int(value) if value is not None else None

    def _trade_price(self, trade: dict[str, Any]) -> float:
        return float(trade["price"])

    def _trade_qty(self, trade: dict[str, Any]) -> float:
        return float(trade["qty"])

    def _trade_side_sign(self, trade: dict[str, Any]) -> float:
        return -1.0 if bool(trade.get("isBuyerMaker", False)) else 1.0


class GateSpotClient(PublicSpotClient):
    exchange_id = "gateio"
    display_name = "Gate"
    base_url = "https://api.gateio.ws/api/v4"

    def fetch_pairs(self, quote: str = "USDT") -> list[MarketPair]:
        data = self._get(f"{self.base_url}/spot/currency_pairs")
        out: list[MarketPair] = []
        for item in data:
            if str(item.get("quote", "")).upper() != quote:
                continue
            if str(item.get("trade_status", "")).lower() != "tradable":
                continue
            out.append(
                MarketPair(
                    exchange=self.exchange_id,
                    symbol=str(item["id"]),
                    base=str(item["base"]).upper(),
                    quote=str(item["quote"]).upper(),
                )
            )
        return out

    def _fetch_depth(self, pair: MarketPair, depth_limit: int) -> Any:
        return self._get(
            f"{self.base_url}/spot/order_book",
            {"currency_pair": pair.symbol, "limit": min(depth_limit, 100)},
        )

    def _fetch_trades(self, pair: MarketPair, trades_limit: int) -> list[dict[str, Any]]:
        return self._get(
            f"{self.base_url}/spot/trades",
            {"currency_pair": pair.symbol, "limit": min(trades_limit, 100)},
        )

    def _trade_key(self, trade: dict[str, Any]) -> int | None:
        value = trade.get("sequence_id") or trade.get("id")
        return int(value) if value is not None else None

    def _trade_price(self, trade: dict[str, Any]) -> float:
        return float(trade["price"])

    def _trade_qty(self, trade: dict[str, Any]) -> float:
        return float(trade["amount"])

    def _trade_side_sign(self, trade: dict[str, Any]) -> float:
        return 1.0 if str(trade.get("side", "")).lower() == "buy" else -1.0


class KucoinSpotClient(PublicSpotClient):
    exchange_id = "kucoin"
    display_name = "KuCoin"
    base_url = "https://api.kucoin.com"

    def fetch_pairs(self, quote: str = "USDT") -> list[MarketPair]:
        data = self._get(f"{self.base_url}/api/v2/symbols")
        out: list[MarketPair] = []
        for item in data.get("data", []):
            if str(item.get("quoteCurrency", "")).upper() != quote:
                continue
            if not bool(item.get("enableTrading", False)):
                continue
            out.append(
                MarketPair(
                    exchange=self.exchange_id,
                    symbol=str(item["symbol"]),
                    base=str(item["baseCurrency"]).upper(),
                    quote=str(item["quoteCurrency"]).upper(),
                )
            )
        return out

    def _fetch_depth(self, pair: MarketPair, depth_limit: int) -> Any:
        return self._get(
            f"{self.base_url}/api/v1/market/orderbook/level2_20",
            {"symbol": pair.symbol},
        )

    def _fetch_trades(self, pair: MarketPair, trades_limit: int) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.base_url}/api/v1/market/histories",
            {"symbol": pair.symbol},
        )
        return list(data.get("data", []))[:trades_limit]

    def _extract_book(self, depth: Any) -> tuple[list[list[Any]], list[list[Any]]]:
        return depth["data"]["bids"], depth["data"]["asks"]

    def _trade_key(self, trade: dict[str, Any]) -> int | None:
        value = trade.get("sequence") or trade.get("tradeId")
        return int(value) if value is not None else None

    def _trade_price(self, trade: dict[str, Any]) -> float:
        return float(trade["price"])

    def _trade_qty(self, trade: dict[str, Any]) -> float:
        return float(trade["size"])

    def _trade_side_sign(self, trade: dict[str, Any]) -> float:
        return 1.0 if str(trade.get("side", "")).lower() == "buy" else -1.0


class BingxSpotClient(PublicSpotClient):
    exchange_id = "bingx"
    display_name = "BingX"
    base_url = "https://open-api.bingx.com"

    def fetch_pairs(self, quote: str = "USDT") -> list[MarketPair]:
        data = self._get(f"{self.base_url}/openApi/spot/v1/common/symbols")
        out: list[MarketPair] = []
        for item in data.get("data", {}).get("symbols", []):
            display = str(item.get("displayName") or item.get("symbol", ""))
            parts = display.split("-")
            if len(parts) != 2:
                continue
            base, pair_quote = parts[0].upper(), parts[1].upper()
            if pair_quote != quote:
                continue
            if int(item.get("status", -1)) != 1:
                continue
            if not bool(item.get("apiStateBuy")) or not bool(item.get("apiStateSell")):
                continue
            out.append(
                MarketPair(
                    exchange=self.exchange_id,
                    symbol=display,
                    base=base,
                    quote=pair_quote,
                )
            )
        return out

    def _fetch_depth(self, pair: MarketPair, depth_limit: int) -> Any:
        return self._get(
            f"{self.base_url}/openApi/spot/v1/market/depth",
            {"symbol": pair.symbol, "limit": min(depth_limit, 100)},
        )

    def _fetch_trades(self, pair: MarketPair, trades_limit: int) -> list[dict[str, Any]]:
        try:
            data = self._get(
                f"{self.base_url}/openApi/spot/v1/market/trades",
                {"symbol": pair.symbol, "limit": min(trades_limit, 100)},
            )
        except requests.RequestException:
            return []
        payload = data.get("data", [])
        if isinstance(payload, dict):
            payload = payload.get("trades") or payload.get("list") or []
        return list(payload)

    def _extract_book(self, depth: Any) -> tuple[list[list[Any]], list[list[Any]]]:
        data = depth["data"]
        return data["bids"], data["asks"]

    def _trade_key(self, trade: dict[str, Any]) -> int | None:
        for key in ("id", "tradeId", "ts", "time"):
            if key in trade:
                return int(trade[key])
        return None

    def _trade_price(self, trade: dict[str, Any]) -> float:
        return float(trade.get("price") or trade.get("p"))

    def _trade_qty(self, trade: dict[str, Any]) -> float:
        return float(trade.get("qty") or trade.get("quantity") or trade.get("q"))

    def _trade_side_sign(self, trade: dict[str, Any]) -> float:
        side = str(trade.get("side") or trade.get("m") or "").lower()
        if side in {"buy", "bid", "b", "false"}:
            return 1.0
        return -1.0


CLIENTS: dict[str, type[PublicSpotClient]] = {
    MexcSpotClient.exchange_id: MexcSpotClient,
    GateSpotClient.exchange_id: GateSpotClient,
    KucoinSpotClient.exchange_id: KucoinSpotClient,
    BingxSpotClient.exchange_id: BingxSpotClient,
}


def build_clients(exchange_ids: list[str], timeout_sec: int = 10) -> dict[str, PublicSpotClient]:
    clients: dict[str, PublicSpotClient] = {}
    for exchange_id in exchange_ids:
        key = exchange_id.strip().lower()
        if not key:
            continue
        if key not in CLIENTS:
            raise ValueError(f"Неизвестная биржа: {exchange_id}. Доступно: {', '.join(CLIENTS)}")
        clients[key] = CLIENTS[key](timeout_sec=timeout_sec)
    return clients
