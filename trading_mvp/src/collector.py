from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from config import ExchangeConfig


class BinanceCollector:
    def __init__(self, cfg: ExchangeConfig) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.last_trade_id = -1

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        url = f"{self.cfg.base_url}{endpoint}"
        response = self.session.get(url, params=params, timeout=self.cfg.timeout_sec)
        response.raise_for_status()
        return response.json()

    def _fetch_depth(self) -> dict[str, Any]:
        payload = self._get(
            "/api/v3/depth",
            {"symbol": self.cfg.symbol, "limit": self.cfg.depth_limit},
        )
        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        if not bids or not asks:
            raise RuntimeError("Пустой стакан от биржи")
        bid = float(bids[0][0])
        ask = float(asks[0][0])
        bid_qty = float(bids[0][1])
        ask_qty = float(asks[0][1])
        spread_bps = ((ask - bid) / ((ask + bid) / 2.0)) * 1e4
        denom = bid_qty + ask_qty
        imbalance = (bid_qty - ask_qty) / denom if denom else 0.0
        return {
            "bid": bid,
            "ask": ask,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "spread_bps": spread_bps,
            "imbalance": imbalance,
        }

    def _fetch_trades(self) -> dict[str, Any]:
        payload = self._get(
            "/api/v3/trades",
            {"symbol": self.cfg.symbol, "limit": self.cfg.trades_limit},
        )
        if not isinstance(payload, list):
            return {
                "new_trade_count": 0,
                "signed_flow_notional": 0.0,
                "last_trade_price": None,
            }
        signed_flow_notional = 0.0
        new_count = 0
        last_price = None
        for tr in payload:
            tr_id = int(tr["id"])
            price = float(tr["price"])
            qty = float(tr["qty"])
            last_price = price
            if tr_id <= self.last_trade_id:
                continue
            # true => buyer was maker => агрессор SELL
            side = -1.0 if bool(tr.get("isBuyerMaker", False)) else 1.0
            signed_flow_notional += side * price * qty
            new_count += 1
            if tr_id > self.last_trade_id:
                self.last_trade_id = tr_id
        return {
            "new_trade_count": new_count,
            "signed_flow_notional": signed_flow_notional,
            "last_trade_price": last_price,
        }

    def collect(self, duration_sec: int, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        end_ts = time.time() + duration_sec
        with out_path.open("w", encoding="utf-8") as f:
            while time.time() < end_ts:
                ts = time.time()
                iso_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                depth = self._fetch_depth()
                trades = self._fetch_trades()
                row = {
                    "ts": ts,
                    "iso_ts": iso_ts,
                    "symbol": self.cfg.symbol,
                    **depth,
                    **trades,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                time.sleep(self.cfg.poll_interval_sec)
        return out_path
