from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _ms_or_s_to_seconds(value: Any) -> float | None:
    raw = _as_float(value)
    if raw is None:
        return None
    return raw / 1000.0 if raw > 10_000_000_000 else raw


@dataclass(frozen=True)
class FundingContract:
    exchange: str
    symbol: str
    base: str
    quote: str
    status: str
    funding_interval_sec: int | None = None
    maker_fee_rate: float | None = None
    taker_fee_rate: float | None = None
    raw: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class FundingSnapshot:
    exchange: str
    symbol: str
    base: str
    quote: str
    ts: float
    funding_rate: float | None
    next_funding_ts: float | None
    funding_interval_sec: int | None
    mark_price: float | None
    index_price: float | None
    perp_bid: float | None
    perp_ask: float | None
    open_interest: float | None = None
    volume_24h: float | None = None
    volume_24h_quote: float | None = None
    maker_fee_rate: float | None = None
    taker_fee_rate: float | None = None
    raw: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class FundingHistoryRow:
    exchange: str
    symbol: str
    ts: float
    funding_rate: float

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class FundingClient:
    exchange_id = ""
    display_name = ""
    base_url = ""
    TICKERS_CACHE_TTL_SEC = 300.0

    def __init__(self, timeout_sec: int = 10) -> None:
        self.timeout_sec = timeout_sec
        self.session = requests.Session()
        self.session.trust_env = False

    def fetch_contracts(self) -> list[FundingContract]:
        raise NotImplementedError

    def fetch_snapshot(self, symbol: str) -> FundingSnapshot:
        raise NotImplementedError

    def fetch_funding_history(self, symbol: str, limit: int = 100) -> list[FundingHistoryRow]:
        raise NotImplementedError

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
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
        raise RuntimeError(f"GET failed: {url}")


def _mexc_data(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(f"MEXC error {payload.get('code')}: {payload.get('message')}")
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def parse_mexc_contract(item: dict[str, Any]) -> FundingContract | None:
    quote = str(item.get("quoteCoin") or item.get("quoteCoinName") or "").upper()
    settle = str(item.get("settleCoin") or quote).upper()
    if quote != "USDT" or settle != "USDT":
        return None
    if int(item.get("state", -1)) != 0:
        return None
    if item.get("apiAllowed") is False:
        return None
    return FundingContract(
        exchange=MexcFundingClient.exchange_id,
        symbol=str(item["symbol"]),
        base=str(item.get("baseCoin") or item.get("baseCoinName") or "").upper(),
        quote=quote,
        status="trading",
        funding_interval_sec=None,
        maker_fee_rate=_as_float(item.get("makerFeeRate")),
        taker_fee_rate=_as_float(item.get("takerFeeRate")),
        raw=item,
    )


def parse_mexc_snapshot(
    contract: FundingContract,
    ticker: dict[str, Any] | None,
    funding: dict[str, Any] | None = None,
    ts: float | None = None,
) -> FundingSnapshot:
    ticker = ticker or {}
    funding = funding or {}
    funding_rate = _as_float(funding.get("fundingRate"))
    if funding_rate is None:
        funding_rate = _as_float(ticker.get("fundingRate"))
    collect_cycle_hours = _as_float(funding.get("collectCycle"))
    interval_sec = int(collect_cycle_hours * 3600) if collect_cycle_hours else contract.funding_interval_sec
    api_ts = _ms_or_s_to_seconds(funding.get("timestamp")) or _ms_or_s_to_seconds(ticker.get("timestamp"))
    return FundingSnapshot(
        exchange=contract.exchange,
        symbol=contract.symbol,
        base=contract.base,
        quote=contract.quote,
        ts=ts or api_ts or time.time(),
        funding_rate=funding_rate,
        next_funding_ts=_ms_or_s_to_seconds(funding.get("nextSettleTime")),
        funding_interval_sec=interval_sec,
        mark_price=_as_float(funding.get("fairPrice")) or _as_float(ticker.get("fairPrice")),
        index_price=_as_float(funding.get("idxPrice")) or _as_float(ticker.get("indexPrice")),
        perp_bid=_as_float(ticker.get("bid1")),
        perp_ask=_as_float(ticker.get("ask1")),
        open_interest=_as_float(ticker.get("holdVol")),
        volume_24h=_as_float(ticker.get("volume24")),
        volume_24h_quote=_as_float(ticker.get("amount24")),
        maker_fee_rate=contract.maker_fee_rate,
        taker_fee_rate=contract.taker_fee_rate,
        raw={"ticker": ticker, "funding": funding},
    )


class MexcFundingClient(FundingClient):
    exchange_id = "mexc"
    display_name = "MEXC Futures"
    base_url = "https://contract.mexc.com"

    def __init__(self, timeout_sec: int = 10) -> None:
        super().__init__(timeout_sec=timeout_sec)
        self._contracts_cache: dict[str, FundingContract] | None = None
        self._tickers_cache: dict[str, dict[str, Any]] | None = None
        self._tickers_cache_ts = 0.0

    def fetch_contracts(self) -> list[FundingContract]:
        payload = self._get("/api/v1/contract/detail")
        contracts: list[FundingContract] = []
        for item in _mexc_data(payload):
            contract = parse_mexc_contract(item)
            if contract is not None:
                contracts.append(contract)
        self._contracts_cache = {contract.symbol: contract for contract in contracts}
        return contracts

    def fetch_snapshot(self, symbol: str) -> FundingSnapshot:
        contract = self._contract_map().get(symbol)
        if contract is None:
            raise KeyError(f"MEXC contract not found: {symbol}")
        ticker = self._ticker_map().get(symbol, {})
        funding_payload = self._get(f"/api/v1/contract/funding_rate/{symbol}")
        funding = _mexc_data(funding_payload)
        return parse_mexc_snapshot(contract, ticker, funding)

    def fetch_funding_history(self, symbol: str, limit: int = 100) -> list[FundingHistoryRow]:
        snapshot = self.fetch_snapshot(symbol)
        if snapshot.funding_rate is None:
            return []
        return [
            FundingHistoryRow(
                exchange=self.exchange_id,
                symbol=symbol,
                ts=snapshot.ts,
                funding_rate=snapshot.funding_rate,
            )
        ]

    def _contract_map(self) -> dict[str, FundingContract]:
        if self._contracts_cache is None:
            self.fetch_contracts()
        return self._contracts_cache or {}

    def _ticker_map(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        cache_expired = now - self._tickers_cache_ts > self.TICKERS_CACHE_TTL_SEC
        if self._tickers_cache is None or cache_expired:
            payload = self._get("/api/v1/contract/ticker")
            self._tickers_cache = {str(item["symbol"]): item for item in _mexc_data(payload)}
            self._tickers_cache_ts = now
        return self._tickers_cache


def parse_gate_contract(item: dict[str, Any]) -> FundingContract | None:
    name = str(item.get("name") or "").upper()
    if not name.endswith("_USDT"):
        return None
    if str(item.get("status") or "").lower() != "trading":
        return None
    base = name.rsplit("_", 1)[0]
    return FundingContract(
        exchange=GateFundingClient.exchange_id,
        symbol=name,
        base=base,
        quote="USDT",
        status="trading",
        funding_interval_sec=_as_int(item.get("funding_interval")),
        maker_fee_rate=_as_float(item.get("maker_fee_rate")),
        taker_fee_rate=_as_float(item.get("taker_fee_rate")),
        raw=item,
    )


def parse_gate_snapshot(
    contract: FundingContract,
    ticker: dict[str, Any] | None = None,
    ts: float | None = None,
) -> FundingSnapshot:
    ticker = ticker or {}
    source = dict(contract.raw or {})
    source.update({key: value for key, value in ticker.items() if value is not None})
    return FundingSnapshot(
        exchange=contract.exchange,
        symbol=contract.symbol,
        base=contract.base,
        quote=contract.quote,
        ts=ts or time.time(),
        funding_rate=_as_float(source.get("funding_rate")),
        next_funding_ts=_ms_or_s_to_seconds(source.get("funding_next_apply")),
        funding_interval_sec=_as_int(source.get("funding_interval")) or contract.funding_interval_sec,
        mark_price=_as_float(source.get("mark_price")),
        index_price=_as_float(source.get("index_price")),
        perp_bid=_as_float(source.get("highest_bid")),
        perp_ask=_as_float(source.get("lowest_ask")),
        open_interest=_as_float(source.get("total_size")) or _as_float(source.get("position_size")),
        volume_24h=_as_float(source.get("volume_24h")),
        volume_24h_quote=_as_float(source.get("volume_24h_quote")) or _as_float(source.get("volume_24h_settle")),
        maker_fee_rate=contract.maker_fee_rate,
        taker_fee_rate=contract.taker_fee_rate,
        raw={"contract": contract.raw or {}, "ticker": ticker},
    )


class GateFundingClient(FundingClient):
    exchange_id = "gateio"
    display_name = "Gate Futures"
    base_url = "https://api.gateio.ws/api/v4"

    def __init__(self, timeout_sec: int = 10) -> None:
        super().__init__(timeout_sec=timeout_sec)
        self._contracts_cache: dict[str, FundingContract] | None = None

    def fetch_contracts(self) -> list[FundingContract]:
        payload = self._get("/futures/usdt/contracts")
        contracts: list[FundingContract] = []
        for item in payload:
            contract = parse_gate_contract(item)
            if contract is not None:
                contracts.append(contract)
        self._contracts_cache = {contract.symbol: contract for contract in contracts}
        return contracts

    def fetch_snapshot(self, symbol: str) -> FundingSnapshot:
        contract = self._contract_map().get(symbol)
        if contract is None:
            raise KeyError(f"Gate contract not found: {symbol}")
        ticker_payload = self._get("/futures/usdt/tickers", {"contract": symbol})
        ticker = ticker_payload[0] if isinstance(ticker_payload, list) and ticker_payload else {}
        return parse_gate_snapshot(contract, ticker)

    def fetch_funding_history(self, symbol: str, limit: int = 100) -> list[FundingHistoryRow]:
        payload = self._get("/futures/usdt/funding_rate", {"contract": symbol, "limit": limit})
        out: list[FundingHistoryRow] = []
        for item in payload:
            rate = _as_float(item.get("r"))
            ts = _as_float(item.get("t"))
            if rate is None or ts is None:
                continue
            out.append(FundingHistoryRow(exchange=self.exchange_id, symbol=symbol, ts=ts, funding_rate=rate))
        return out

    def _contract_map(self) -> dict[str, FundingContract]:
        if self._contracts_cache is None:
            self.fetch_contracts()
        return self._contracts_cache or {}


FUNDING_CLIENTS: dict[str, type[FundingClient]] = {
    MexcFundingClient.exchange_id: MexcFundingClient,
    GateFundingClient.exchange_id: GateFundingClient,
}


def build_funding_clients(exchange_ids: list[str], timeout_sec: int = 10) -> dict[str, FundingClient]:
    clients: dict[str, FundingClient] = {}
    for exchange_id in exchange_ids:
        key = exchange_id.strip().lower()
        if not key:
            continue
        if key == "gate":
            key = "gateio"
        if key not in FUNDING_CLIENTS:
            raise ValueError(f"Неизвестная futures-биржа: {exchange_id}. Доступно: {', '.join(FUNDING_CLIENTS)}")
        clients[key] = FUNDING_CLIENTS[key](timeout_sec=timeout_sec)
    return clients
