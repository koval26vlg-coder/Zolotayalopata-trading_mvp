from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from funding import FundingContract, FundingSnapshot, build_funding_clients
from multi_bot import load_universe_symbols


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def _spread_bps(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    return ((ask - bid) / mid) * 1e4 if mid > 0 else None


def _json_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _mexc_data(payload: Any) -> Any:
    payload = _json_payload(payload)
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(f"MEXC error {payload.get('code')}: {payload.get('message')}")
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


@dataclass(frozen=True)
class PerpCollectConfig:
    cycles: int = 3
    duration_sec: int | None = None
    poll_interval_sec: float = 10.0
    depth_limit: int = 20
    trades_limit: int = 50
    max_symbols: int = 200
    max_pairs_per_exchange: int = 5
    quote: str = "USDT"


class PublicPerpRestClient:
    exchange_id = ""
    base_url = ""

    def __init__(self, timeout_sec: int = 10) -> None:
        self.timeout_sec = timeout_sec
        self.session = requests.Session()
        self._last_trade_ids: dict[str, int] = {}

    def fetch_depth(self, contract: FundingContract, depth_limit: int) -> Any:
        raise NotImplementedError

    def fetch_trades(self, contract: FundingContract, trades_limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalized_events(
        self,
        contract: FundingContract,
        snapshot: FundingSnapshot,
        depth_limit: int,
        trades_limit: int,
    ) -> list[dict[str, Any]]:
        depth = self.fetch_depth(contract, depth_limit)
        trades = self.fetch_trades(contract, trades_limit)
        return self._events_from_payloads(contract, snapshot, depth, trades)

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
        raise RuntimeError(f"Не удалось выполнить GET {url}")

    def _events_from_payloads(
        self,
        contract: FundingContract,
        snapshot: FundingSnapshot,
        depth: Any,
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        bids, asks, depth_ts, version = self._extract_book(contract, depth)
        ts = depth_ts or snapshot.ts or time.time()
        out: list[dict[str, Any]] = []
        if bids and asks:
            bid = bids[0][0]
            ask = asks[0][0]
            out.append(
                {
                    "recv_ts": time.time(),
                    "exchange_ts": ts,
                    "exchange": contract.exchange,
                    "symbol": contract.symbol,
                    "event_kind": "bbo",
                    "channel": "perp.rest.bbo",
                    "bid_price": bid,
                    "bid_qty": bids[0][1],
                    "ask_price": ask,
                    "ask_qty": asks[0][1],
                    "spread_bps": _spread_bps(bid, ask),
                    **self._perp_fields(snapshot),
                }
            )
            out.append(
                {
                    "recv_ts": time.time(),
                    "exchange_ts": ts,
                    "exchange": contract.exchange,
                    "symbol": contract.symbol,
                    "event_kind": "depth",
                    "channel": "perp.rest.depth",
                    "depth_type": "snapshot",
                    "bids": bids,
                    "asks": asks,
                    "version": version,
                    **self._perp_fields(snapshot),
                }
            )
        out.extend(self._trade_events(contract, snapshot, trades))
        return out

    def _perp_fields(self, snapshot: FundingSnapshot) -> dict[str, Any]:
        return {
            "mark_price": snapshot.mark_price,
            "index_price": snapshot.index_price,
            "funding_rate": snapshot.funding_rate,
            "next_funding_ts": snapshot.next_funding_ts,
            "funding_interval_sec": snapshot.funding_interval_sec,
            "open_interest": snapshot.open_interest,
            "volume_24h_quote": snapshot.volume_24h_quote,
        }

    def _trade_events(
        self,
        contract: FundingContract,
        snapshot: FundingSnapshot,
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized: list[tuple[int, dict[str, Any]]] = []
        for trade in trades:
            trade_id = self._trade_id(trade)
            if trade_id is not None:
                normalized.append((trade_id, trade))
        normalized.sort(key=lambda item: item[0])
        if not normalized:
            return []
        last_seen = self._last_trade_ids.get(contract.symbol)
        max_seen = normalized[-1][0]
        out: list[dict[str, Any]] = []
        for trade_id, trade in normalized:
            if last_seen is not None and trade_id <= last_seen:
                continue
            price = self._trade_price(trade)
            qty = self._trade_qty(contract, trade)
            side = self._trade_side(trade)
            trade_ts = self._trade_ts(trade) or snapshot.ts or time.time()
            if price is None or qty is None or side is None:
                continue
            out.append(
                {
                    "recv_ts": time.time(),
                    "exchange_ts": trade_ts,
                    "exchange": contract.exchange,
                    "symbol": contract.symbol,
                    "event_kind": "trade",
                    "channel": "perp.rest.trades",
                    "trade_id": trade_id,
                    "price": price,
                    "qty": qty,
                    "side": side,
                    **self._perp_fields(snapshot),
                }
            )
        self._last_trade_ids[contract.symbol] = max(max_seen, last_seen or max_seen)
        return out

    def _extract_book(self, contract: FundingContract, depth: Any) -> tuple[list[list[float]], list[list[float]], float | None, Any]:
        raise NotImplementedError

    def _trade_id(self, trade: dict[str, Any]) -> int | None:
        raise NotImplementedError

    def _trade_price(self, trade: dict[str, Any]) -> float | None:
        raise NotImplementedError

    def _trade_qty(self, contract: FundingContract, trade: dict[str, Any]) -> float | None:
        raise NotImplementedError

    def _trade_side(self, trade: dict[str, Any]) -> str | None:
        raise NotImplementedError

    def _trade_ts(self, trade: dict[str, Any]) -> float | None:
        raise NotImplementedError

    def _contract_multiplier(self, contract: FundingContract) -> float:
        return 1.0


class MexcPerpRestClient(PublicPerpRestClient):
    exchange_id = "mexc"
    base_url = "https://contract.mexc.com"

    def fetch_depth(self, contract: FundingContract, depth_limit: int) -> Any:
        return self._get(
            f"/api/v1/contract/depth/{contract.symbol}",
            {"limit": min(depth_limit, 100)},
        )

    def fetch_trades(self, contract: FundingContract, trades_limit: int) -> list[dict[str, Any]]:
        payload = self._get(
            f"/api/v1/contract/deals/{contract.symbol}",
            {"limit": min(trades_limit, 100)},
        )
        return list(_mexc_data(payload) or [])

    def _extract_book(self, contract: FundingContract, depth: Any) -> tuple[list[list[float]], list[list[float]], float | None, Any]:
        data = _mexc_data(depth)
        multiplier = self._contract_multiplier(contract)
        bids = [[float(level[0]), float(level[1]) * multiplier] for level in data.get("bids", []) if len(level) >= 2]
        asks = [[float(level[0]), float(level[1]) * multiplier] for level in data.get("asks", []) if len(level) >= 2]
        return bids, asks, _ms_or_s_to_seconds(data.get("timestamp")), data.get("version")

    def _trade_id(self, trade: dict[str, Any]) -> int | None:
        value = trade.get("i") or trade.get("id") or trade.get("t")
        return _as_int(value)

    def _trade_price(self, trade: dict[str, Any]) -> float | None:
        return _as_float(trade.get("p"))

    def _trade_qty(self, contract: FundingContract, trade: dict[str, Any]) -> float | None:
        qty = _as_float(trade.get("v"))
        return qty * self._contract_multiplier(contract) if qty is not None else None

    def _trade_side(self, trade: dict[str, Any]) -> str | None:
        trade_type = _as_int(trade.get("T"))
        if trade_type == 1:
            return "buy"
        if trade_type == 2:
            return "sell"
        return None

    def _trade_ts(self, trade: dict[str, Any]) -> float | None:
        return _ms_or_s_to_seconds(trade.get("t"))

    def _contract_multiplier(self, contract: FundingContract) -> float:
        raw = contract.raw or {}
        return _as_float(raw.get("contractSize")) or 1.0


class GatePerpRestClient(PublicPerpRestClient):
    exchange_id = "gateio"
    base_url = "https://api.gateio.ws/api/v4"

    def fetch_depth(self, contract: FundingContract, depth_limit: int) -> Any:
        return self._get(
            "/futures/usdt/order_book",
            {"contract": contract.symbol, "limit": min(depth_limit, 100), "with_id": "true"},
        )

    def fetch_trades(self, contract: FundingContract, trades_limit: int) -> list[dict[str, Any]]:
        return list(
            self._get(
                "/futures/usdt/trades",
                {"contract": contract.symbol, "limit": min(trades_limit, 100)},
            )
            or []
        )

    def _extract_book(self, contract: FundingContract, depth: Any) -> tuple[list[list[float]], list[list[float]], float | None, Any]:
        multiplier = self._contract_multiplier(contract)
        bids = [[float(item["p"]), float(item["s"]) * multiplier] for item in depth.get("bids", [])]
        asks = [[float(item["p"]), float(item["s"]) * multiplier] for item in depth.get("asks", [])]
        return bids, asks, _ms_or_s_to_seconds(depth.get("update") or depth.get("current")), depth.get("id")

    def _trade_id(self, trade: dict[str, Any]) -> int | None:
        return _as_int(trade.get("id"))

    def _trade_price(self, trade: dict[str, Any]) -> float | None:
        return _as_float(trade.get("price"))

    def _trade_qty(self, contract: FundingContract, trade: dict[str, Any]) -> float | None:
        size = _as_float(trade.get("size"))
        return abs(size) * self._contract_multiplier(contract) if size is not None else None

    def _trade_side(self, trade: dict[str, Any]) -> str | None:
        size = _as_float(trade.get("size"))
        if size is None:
            return None
        return "buy" if size > 0 else "sell"

    def _trade_ts(self, trade: dict[str, Any]) -> float | None:
        return _ms_or_s_to_seconds(trade.get("create_time_ms") or trade.get("create_time"))

    def _contract_multiplier(self, contract: FundingContract) -> float:
        raw = contract.raw or {}
        return _as_float(raw.get("quanto_multiplier")) or 1.0


PERP_REST_CLIENTS: dict[str, type[PublicPerpRestClient]] = {
    MexcPerpRestClient.exchange_id: MexcPerpRestClient,
    GatePerpRestClient.exchange_id: GatePerpRestClient,
}


def build_perp_rest_clients(exchange_ids: list[str], timeout_sec: int = 10) -> dict[str, PublicPerpRestClient]:
    clients: dict[str, PublicPerpRestClient] = {}
    for exchange_id in exchange_ids:
        key = exchange_id.strip().lower()
        if key == "gate":
            key = "gateio"
        if not key:
            continue
        if key not in PERP_REST_CLIENTS:
            raise ValueError(f"Неизвестная perp-биржа: {exchange_id}. Доступно: {', '.join(PERP_REST_CLIENTS)}")
        clients[key] = PERP_REST_CLIENTS[key](timeout_sec=timeout_sec)
    return clients


def select_contracts(
    contracts: list[FundingContract],
    universe_symbols: set[str],
    quote: str,
    max_pairs: int,
) -> list[FundingContract]:
    selected: list[FundingContract] = []
    for contract in contracts:
        if contract.quote.upper() != quote.upper():
            continue
        if str(contract.status).lower() != "trading":
            continue
        if universe_symbols and contract.base.upper() not in universe_symbols:
            continue
        selected.append(contract)
        if len(selected) >= max_pairs:
            break
    return selected


def collect_perp_rest_file(
    output_path: str | Path,
    exchange_ids: list[str],
    universe_csv: str | Path,
    cfg: PerpCollectConfig,
    timeout_sec: int = 10,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = Path(manifest_path) if manifest_path else output.with_suffix(".manifest.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    universe_symbols = load_universe_symbols(Path(universe_csv), max_symbols=cfg.max_symbols)
    funding_clients = build_funding_clients(exchange_ids, timeout_sec=timeout_sec)
    rest_clients = build_perp_rest_clients(exchange_ids, timeout_sec=timeout_sec)
    discovery: dict[str, Any] = {}
    contracts_by_exchange: dict[str, list[FundingContract]] = {}
    errors: list[dict[str, Any]] = []
    for exchange_id, funding_client in funding_clients.items():
        try:
            contracts = funding_client.fetch_contracts()
            selected = select_contracts(
                contracts,
                universe_symbols=universe_symbols,
                quote=cfg.quote,
                max_pairs=cfg.max_pairs_per_exchange,
            )
            contracts_by_exchange[exchange_id] = selected
            discovery[exchange_id] = {
                "available_contracts": len(contracts),
                "selected_contracts": len(selected),
                "symbols": [contract.symbol for contract in selected],
            }
        except Exception as exc:  # noqa: BLE001
            contracts_by_exchange[exchange_id] = []
            discovery[exchange_id] = {"available_contracts": 0, "selected_contracts": 0, "symbols": [], "error": str(exc)[:300]}

    total_rows = 0
    cycle_summaries: list[dict[str, Any]] = []
    started = time.time()
    with output.open("a", encoding="utf-8") as fh:
        cycle = 0
        while _should_continue_collect(cycle, started, cfg):
            cycle_started = time.time()
            cycle_rows = 0
            cycle_errors: list[dict[str, Any]] = []
            for exchange_id, contracts in contracts_by_exchange.items():
                funding_client = funding_clients.get(exchange_id)
                rest_client = rest_clients.get(exchange_id)
                if funding_client is None or rest_client is None:
                    continue
                for contract in contracts:
                    try:
                        snapshot = funding_client.fetch_snapshot(contract.symbol)
                        events = rest_client.normalized_events(
                            contract=contract,
                            snapshot=snapshot,
                            depth_limit=cfg.depth_limit,
                            trades_limit=cfg.trades_limit,
                        )
                        for event in events:
                            event["cycle"] = cycle + 1
                            fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                            total_rows += 1
                            cycle_rows += 1
                    except Exception as exc:  # noqa: BLE001
                        err = {"cycle": cycle + 1, "exchange": exchange_id, "symbol": contract.symbol, "error": str(exc)[:300]}
                        errors.append(err)
                        cycle_errors.append(err)
            fh.flush()
            cycle_summaries.append(
                _cycle_summary(
                    cycle=cycle + 1,
                    started=cycle_started,
                    rows=cycle_rows,
                    errors=cycle_errors,
                    discovery=discovery,
                )
            )
            _write_manifest(manifest, output, cfg, started, discovery, cycle_summaries, errors, final=False)
            cycle += 1
            if _should_continue_collect(cycle, started, cfg):
                time.sleep(_sleep_interval(started, cfg))
    _write_manifest(manifest, output, cfg, started, discovery, cycle_summaries, errors, final=True)
    return {
        "ok": True,
        "output": str(output),
        "manifest": str(manifest),
        "cycles": cfg.cycles,
        "rows": total_rows,
        "errors": len(errors),
        "discovery": discovery,
        "duration_sec": time.time() - started,
    }


def _should_continue_collect(cycle: int, started: float, cfg: PerpCollectConfig, now: float | None = None) -> bool:
    if cfg.duration_sec is None or cfg.duration_sec <= 0:
        return cycle < cfg.cycles
    current = now if now is not None else time.time()
    return current - started < cfg.duration_sec


def _sleep_interval(started: float, cfg: PerpCollectConfig) -> float:
    if cfg.duration_sec is None or cfg.duration_sec <= 0:
        return cfg.poll_interval_sec
    remaining = cfg.duration_sec - (time.time() - started)
    return max(0.0, min(cfg.poll_interval_sec, remaining))


def _cycle_summary(
    cycle: int,
    started: float,
    rows: int,
    errors: list[dict[str, Any]],
    discovery: dict[str, Any],
) -> dict[str, Any]:
    return {
        "cycle": cycle,
        "ts": time.time(),
        "duration_sec": time.time() - started,
        "rows": rows,
        "errors": len(errors),
        "selected_by_exchange": {
            exchange: data.get("symbols", [])
            for exchange, data in discovery.items()
            if isinstance(data, dict)
        },
        "error_breakdown": [
            {"key": key, "count": count}
            for key, count in Counter(f"{err.get('exchange')}:{err.get('symbol')}:{err.get('error')}" for err in errors).most_common(20)
        ],
    }


def _write_manifest(
    manifest: Path,
    output: Path,
    cfg: PerpCollectConfig,
    started: float,
    discovery: dict[str, Any],
    cycle_summaries: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    final: bool,
) -> None:
    payload = {
        "mode": "perp_rest_collect_manifest",
        "ok": True,
        "final": final,
        "output": str(output),
        "config": cfg.__dict__,
        "stop_condition": "duration_sec" if cfg.duration_sec and cfg.duration_sec > 0 else "cycles",
        "discovery": discovery,
        "cycles": cfg.cycles if cfg.duration_sec is None or cfg.duration_sec <= 0 else None,
        "completed_cycles": len(cycle_summaries),
        "rows": sum(item.get("rows", 0) for item in cycle_summaries),
        "errors": len(errors),
        "duration_sec": time.time() - started,
        "cycle_summaries": cycle_summaries,
        "error_samples": errors[:20],
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_perp_collect_path(normalized_dir: str | Path) -> Path:
    return Path(normalized_dir) / f"perp_normalized_{utc_stamp()}.jsonl"
