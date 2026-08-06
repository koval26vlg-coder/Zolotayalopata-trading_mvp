from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from funding import (
    FundingClient,
    GateFundingClient,
    MexcFundingClient,
    _as_float,
)

DEFAULT_DAYS = 730
DEFAULT_TOP = 200
DEFAULT_SLEEP_SEC = 0.15
# Gate funding_rate endpoint: без from/to отдаёт только ~30 дней,
# а from глубже 180 дней отклоняет (INVALID_PARAM_VALUE).
GATE_FUNDING_MAX_DAYS = 179
DEFAULT_UNIVERSE_CSV = Path(__file__).resolve().parents[2] / "coins_not_on_binance_full_2026-05-29.csv"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _force_utf8_stdio() -> None:
    # Символы контрактов бывают не-ASCII; cp1251-консоль Windows роняет print.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def load_non_binance_symbols(csv_path: str | Path) -> set[str]:
    path = Path(csv_path)
    if not path.exists():
        return set()
    symbols: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol:
                symbols.add(symbol)
    return symbols


@dataclass(frozen=True)
class SymbolPlan:
    exchange: str
    symbol: str
    base: str
    volume_24h_quote: float
    non_binance_baseline: bool

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def parse_mexc_kline_payload(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    times = data.get("time") or []
    rows: list[dict[str, Any]] = []
    for index, ts in enumerate(times):
        try:
            rows.append(
                {
                    "ts": float(ts),
                    "open": float(data["open"][index]),
                    "high": float(data["high"][index]),
                    "low": float(data["low"][index]),
                    "close": float(data["close"][index]),
                    "volume_base": _as_float((data.get("vol") or [None] * len(times))[index]),
                    "volume_quote": _as_float((data.get("amount") or [None] * len(times))[index]),
                }
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    rows.sort(key=lambda row: row["ts"])
    return rows


def parse_gate_candles(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        ts = _as_float(item.get("t"))
        close = _as_float(item.get("c"))
        if ts is None or close is None:
            continue
        rows.append(
            {
                "ts": ts,
                "open": _as_float(item.get("o")),
                "high": _as_float(item.get("h")),
                "low": _as_float(item.get("l")),
                "close": close,
                "volume_base": _as_float(item.get("v")),
                "volume_quote": _as_float(item.get("sum")),
            }
        )
    rows.sort(key=lambda row: row["ts"])
    return rows


def parse_mexc_funding_page(data: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(data, dict):
        return [], 0
    rows: list[dict[str, Any]] = []
    for item in data.get("resultList") or []:
        rate = _as_float(item.get("fundingRate"))
        settle_ms = _as_float(item.get("settleTime"))
        if rate is None or settle_ms is None:
            continue
        rows.append({"ts": settle_ms / 1000.0, "funding_rate": rate})
    total_pages = int(_as_float(data.get("totalPage")) or 0)
    return rows, total_pages


def parse_gate_funding(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload:
        rate = _as_float(item.get("r"))
        ts = _as_float(item.get("t"))
        if rate is None or ts is None:
            continue
        rows.append({"ts": ts, "funding_rate": rate})
    rows.sort(key=lambda row: row["ts"])
    return rows


class MexcDailyClient(MexcFundingClient):
    def fetch_ticker_map(self) -> dict[str, dict[str, Any]]:
        return self._ticker_map()

    def fetch_daily_klines(self, symbol: str, start_sec: int, end_sec: int) -> list[dict[str, Any]]:
        payload = self._get(
            f"/api/v1/contract/kline/{symbol}",
            {"interval": "Day1", "start": start_sec, "end": end_sec},
        )
        data = payload.get("data") if isinstance(payload, dict) else payload
        return parse_mexc_kline_payload(data)

    def fetch_funding_history_full(
        self,
        symbol: str,
        page_size: int = 1000,
        max_pages: int = 60,
        sleep_sec: float = 0.0,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_num = 1
        while page_num <= max_pages:
            payload = self._get(
                "/api/v1/contract/funding_rate/history",
                {"symbol": symbol, "page_num": page_num, "page_size": page_size},
            )
            data = payload.get("data") if isinstance(payload, dict) else payload
            page_rows, total_pages = parse_mexc_funding_page(data)
            rows.extend(page_rows)
            if page_num >= total_pages or not page_rows:
                break
            page_num += 1
            if sleep_sec > 0:
                time.sleep(sleep_sec)
        deduped = {row["ts"]: row for row in rows}
        return [deduped[key] for key in sorted(deduped)]


class GateDailyClient(GateFundingClient):
    def fetch_ticker_map(self) -> dict[str, dict[str, Any]]:
        payload = self._get("/futures/usdt/tickers")
        result: dict[str, dict[str, Any]] = {}
        for item in payload if isinstance(payload, list) else []:
            contract = str(item.get("contract") or "")
            if contract:
                result[contract] = item
        return result

    def fetch_daily_klines(self, symbol: str, start_sec: int, end_sec: int) -> list[dict[str, Any]]:
        payload = self._get(
            "/futures/usdt/candlesticks",
            {"contract": symbol, "interval": "1d", "from": start_sec, "to": end_sec},
        )
        return parse_gate_candles(payload)

    def fetch_funding_history_full(
        self,
        symbol: str,
        limit: int = 1000,
        start_sec: int | None = None,
    ) -> list[dict[str, Any]]:
        now = int(time.time())
        from_sec = now - GATE_FUNDING_MAX_DAYS * 86400
        if start_sec is not None:
            from_sec = max(from_sec, int(start_sec))
        return self._fetch_funding_window(symbol, from_sec, now, limit)

    def _fetch_funding_window(
        self,
        symbol: str,
        from_sec: int,
        to_sec: int,
        limit: int,
        depth: int = 0,
    ) -> list[dict[str, Any]]:
        payload = self._get(
            "/futures/usdt/funding_rate",
            {"contract": symbol, "limit": limit, "from": from_sec, "to": to_sec},
        )
        rows = parse_gate_funding(payload)
        # limit=1000 — потолок API: контракты с funding-интервалом < 8h не
        # влезают в одно 179d-окно, поэтому окно делится пополам.
        if len(rows) >= limit and depth < 4 and to_sec - from_sec > 86400:
            mid = (from_sec + to_sec) // 2
            left = self._fetch_funding_window(symbol, from_sec, mid, limit, depth + 1)
            right = self._fetch_funding_window(symbol, mid + 1, to_sec, limit, depth + 1)
            merged = {row["ts"]: row for row in left + right}
            return [merged[key] for key in sorted(merged)]
        return rows


DAILY_CLIENTS: dict[str, type[FundingClient]] = {
    MexcDailyClient.exchange_id: MexcDailyClient,
    GateDailyClient.exchange_id: GateDailyClient,
}


def _mexc_volume_quote(ticker: dict[str, Any]) -> float:
    return _as_float(ticker.get("amount24")) or 0.0


def _gate_volume_quote(ticker: dict[str, Any]) -> float:
    return (
        _as_float(ticker.get("volume_24h_settle"))
        or _as_float(ticker.get("volume_24h_quote"))
        or 0.0
    )


def plan_universe(
    exchange_id: str,
    contracts: list[Any],
    ticker_map: dict[str, dict[str, Any]],
    non_binance: set[str],
    top: int,
) -> list[SymbolPlan]:
    volume_fn = _mexc_volume_quote if exchange_id == "mexc" else _gate_volume_quote
    plans: list[SymbolPlan] = []
    for contract in contracts:
        ticker = ticker_map.get(contract.symbol, {})
        plans.append(
            SymbolPlan(
                exchange=exchange_id,
                symbol=contract.symbol,
                base=contract.base,
                volume_24h_quote=volume_fn(ticker),
                non_binance_baseline=contract.base in non_binance,
            )
        )
    plans.sort(key=lambda plan: plan.volume_24h_quote, reverse=True)
    if top > 0:
        plans = plans[:top]
    return plans


@dataclass
class SymbolStatus:
    exchange: str
    symbol: str
    klines_rows: int = 0
    funding_rows: int = 0
    klines_status: str = "pending"
    funding_status: str = "pending"
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _existing_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    rows = payload.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def collect_daily(
    exchanges: list[str],
    out_root: str | Path,
    run_id: str | None = None,
    days: int = DEFAULT_DAYS,
    top: int = DEFAULT_TOP,
    max_symbols: int = 0,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    universe_csv: str | Path = DEFAULT_UNIVERSE_CSV,
    skip_klines: bool = False,
    skip_funding: bool = False,
) -> dict[str, Any]:
    run_id = run_id or f"daily_collect_{_utc_stamp()}"
    run_dir = Path(out_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    end_sec = int(started)
    start_sec = end_sec - days * 86400
    non_binance = load_non_binance_symbols(universe_csv)
    statuses: list[SymbolStatus] = []
    universe_dump: list[dict[str, Any]] = []

    for exchange_id in exchanges:
        key = exchange_id.strip().lower()
        if key == "gate":
            key = "gateio"
        if key not in DAILY_CLIENTS:
            raise ValueError(f"Неизвестная биржа: {exchange_id}. Доступно: {', '.join(DAILY_CLIENTS)}")
        client = DAILY_CLIENTS[key]()
        contracts = client.fetch_contracts()
        ticker_map = client.fetch_ticker_map()
        plans = plan_universe(key, contracts, ticker_map, non_binance, top)
        if max_symbols > 0:
            plans = plans[:max_symbols]
        print(f"[{key}] universe: {len(plans)} symbols (top={top}, max_symbols={max_symbols})", flush=True)
        universe_dump.extend(plan.as_dict() for plan in plans)

        for index, plan in enumerate(plans, start=1):
            status = SymbolStatus(exchange=key, symbol=plan.symbol)
            statuses.append(status)
            klines_path = run_dir / key / "klines" / f"{plan.symbol}.json"
            funding_path = run_dir / key / "funding" / f"{plan.symbol}.json"

            if not skip_klines:
                existing = _existing_rows(klines_path)
                if existing > 0:
                    status.klines_rows = existing
                    status.klines_status = "skipped_existing"
                else:
                    try:
                        rows = client.fetch_daily_klines(plan.symbol, start_sec, end_sec)
                        _write_json(
                            klines_path,
                            {
                                "exchange": key,
                                "symbol": plan.symbol,
                                "interval": "1d",
                                "start_sec": start_sec,
                                "end_sec": end_sec,
                                "rows": rows,
                            },
                        )
                        status.klines_rows = len(rows)
                        status.klines_status = "ok"
                    except Exception as exc:  # noqa: BLE001
                        status.klines_status = "error"
                        status.errors.append(f"klines {type(exc).__name__}: {exc}")
                    time.sleep(sleep_sec)
            else:
                status.klines_status = "skipped_by_flag"

            if not skip_funding:
                existing = _existing_rows(funding_path)
                if existing > 0:
                    status.funding_rows = existing
                    status.funding_status = "skipped_existing"
                else:
                    try:
                        if isinstance(client, MexcDailyClient):
                            rows = client.fetch_funding_history_full(plan.symbol, sleep_sec=sleep_sec)
                        else:
                            rows = client.fetch_funding_history_full(plan.symbol, start_sec=start_sec)
                        rows = [row for row in rows if row["ts"] >= start_sec]
                        _write_json(
                            funding_path,
                            {"exchange": key, "symbol": plan.symbol, "rows": rows},
                        )
                        status.funding_rows = len(rows)
                        status.funding_status = "ok"
                    except Exception as exc:  # noqa: BLE001
                        status.funding_status = "error"
                        status.errors.append(f"funding {type(exc).__name__}: {exc}")
                    time.sleep(sleep_sec)
            else:
                status.funding_status = "skipped_by_flag"

            print(
                f"[{key}] {index}/{len(plans)} {plan.symbol}: "
                f"klines={status.klines_status}({status.klines_rows}) "
                f"funding={status.funding_status}({status.funding_rows})",
                flush=True,
            )

    finished = time.time()
    error_statuses = [s for s in statuses if s.errors]
    manifest = {
        "schema": "daily_collect_v1",
        "run_id": run_id,
        "started_at_utc": datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
        "finished_at_utc": datetime.fromtimestamp(finished, tz=timezone.utc).isoformat(),
        "duration_sec": round(finished - started, 3),
        "params": {
            "exchanges": exchanges,
            "days": days,
            "top": top,
            "max_symbols": max_symbols,
            "sleep_sec": sleep_sec,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "universe_csv": str(universe_csv),
            "skip_klines": skip_klines,
            "skip_funding": skip_funding,
        },
        "universe": universe_dump,
        "symbols_total": len(statuses),
        "klines_rows_total": sum(s.klines_rows for s in statuses),
        "funding_rows_total": sum(s.funding_rows for s in statuses),
        "error_count": len(error_statuses),
        "statuses": [s.as_dict() for s in statuses],
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE run_id={run_id} symbols={len(statuses)} "
        f"klines_rows={manifest['klines_rows_total']} funding_rows={manifest['funding_rows_total']} "
        f"errors={len(error_statuses)} manifest={manifest_path}",
        flush=True,
    )
    return manifest


def main() -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="Daily klines + funding history collector (research-only, public REST)")
    parser.add_argument("--exchanges", default="mexc,gateio")
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[2] / "exports" / "trading-mvp" / "daily"))
    parser.add_argument("--run-id", default=None, help="Переиспользовать run_id для resume (skip существующих файлов)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="Top-N по 24h quote volume на биржу")
    parser.add_argument("--max-symbols", type=int, default=0, help="Жесткий cap для smoke-прогонов")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SEC)
    parser.add_argument("--universe-csv", default=str(DEFAULT_UNIVERSE_CSV))
    parser.add_argument("--skip-klines", action="store_true")
    parser.add_argument("--skip-funding", action="store_true")
    args = parser.parse_args()
    manifest = collect_daily(
        exchanges=[item for item in args.exchanges.split(",") if item.strip()],
        out_root=args.out_dir,
        run_id=args.run_id,
        days=args.days,
        top=args.top,
        max_symbols=args.max_symbols,
        sleep_sec=args.sleep,
        universe_csv=args.universe_csv,
        skip_klines=args.skip_klines,
        skip_funding=args.skip_funding,
    )
    return 0 if manifest["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
