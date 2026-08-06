from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from listing_event_history_collect_plan import INTERVAL_SECONDS
from listing_event_history_collector import CLIENTS, Candle, PublicOhlcvClient, iso_from_ts, utc_now_iso, write_manifest


APPROVAL_TEXT = "подтверждаю visible slow-liquidity OHLCV history collect"
DEFAULT_UNIVERSE_PATH = Path("coins_not_on_binance_full_2026-05-29.csv")
DEFAULT_EXCHANGES = ("mexc", "gateio", "bitget")
DEFAULT_GRANULARITIES = ("15m", "1h", "4h")


@dataclass(frozen=True)
class UniverseAsset:
    rank: int | None
    name: str
    base: str
    coin_id: str


@dataclass(frozen=True)
class HistoryJob:
    exchange: str
    symbol: str
    base: str
    quote: str
    granularity: str
    start_ts: int
    end_ts: int

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.symbol}:{self.granularity}"


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def normalize_base(value: Any) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_exchange(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"gate", "gate.io", "gateio"}:
        return "gateio"
    return text


def split_csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def load_universe(path: Path, *, max_bases: int) -> list[UniverseAsset]:
    assets: list[UniverseAsset] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            base = normalize_base(row.get("symbol"))
            if not base or base in seen:
                continue
            assets.append(
                UniverseAsset(
                    rank=_as_int(row.get("rank")),
                    name=str(row.get("name") or "").strip(),
                    base=base,
                    coin_id=str(row.get("coin_id") or "").strip(),
                )
            )
            seen.add(base)
            if max_bases > 0 and len(assets) >= max_bases:
                break
    return assets


def symbol_for_exchange(exchange: str, base: str, quote: str) -> str:
    if exchange == "gateio":
        return f"{base}_{quote}"
    return f"{base}{quote}"


def build_jobs(
    assets: list[UniverseAsset],
    *,
    exchanges: list[str],
    granularities: list[str],
    quote: str,
    start_ts: int,
    end_ts: int,
) -> list[HistoryJob]:
    jobs: list[HistoryJob] = []
    for asset in assets:
        for exchange in exchanges:
            for granularity in granularities:
                jobs.append(
                    HistoryJob(
                        exchange=exchange,
                        symbol=symbol_for_exchange(exchange, asset.base, quote),
                        base=asset.base,
                        quote=quote,
                        granularity=granularity,
                        start_ts=start_ts,
                        end_ts=end_ts,
                    )
                )
    return jobs


def output_row(job: HistoryJob, *, candle: Candle | None, data_status: str, error: str = "") -> dict[str, Any]:
    candle_ts = candle.ts if candle else None
    return {
        "source": "slow_liquidity_history",
        "exchange": job.exchange,
        "symbol": job.symbol,
        "base": job.base,
        "quote": job.quote,
        "granularity": job.granularity,
        "job_key": job.key,
        "history_start_ts": job.start_ts,
        "history_start_iso": iso_from_ts(job.start_ts),
        "history_end_ts": job.end_ts,
        "history_end_iso": iso_from_ts(job.end_ts),
        "candle_ts": candle_ts,
        "candle_iso": iso_from_ts(candle_ts),
        "open": candle.open if candle else None,
        "high": candle.high if candle else None,
        "low": candle.low if candle else None,
        "close": candle.close if candle else None,
        "volume": candle.volume if candle else None,
        "quote_volume": candle.quote_volume if candle else None,
        "trade_count_if_available": candle.trade_count if candle else None,
        "data_status": data_status,
        "error": error,
    }


def read_completed_keys(path: Path) -> tuple[set[str], dict[str, Any]]:
    completed: set[str] = set()
    stats: dict[str, Any] = {
        "rows": 0,
        "ohlcv_rows": 0,
        "placeholder_rows": 0,
        "errors": 0,
        "data_status_counts": Counter(),
        "by_exchange": {},
        "by_granularity": {},
        "by_market": {},
    }
    if not path.exists():
        return completed, stats
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            job_key = str(row.get("job_key") or "")
            if job_key:
                completed.add(job_key)
            stats["rows"] += 1
            status = str(row.get("data_status") or "")
            stats["data_status_counts"][status] += 1
            if status == "ok":
                stats["ohlcv_rows"] += 1
            else:
                stats["placeholder_rows"] += 1
            if status == "api_error":
                stats["errors"] += 1
            exchange = str(row.get("exchange") or "")
            granularity = str(row.get("granularity") or "")
            market = f"{exchange}:{row.get('symbol') or ''}"
            if exchange:
                exchange_stats = stats["by_exchange"].setdefault(exchange, {"rows": 0, "placeholders": 0, "errors": 0, "completed_jobs": 0})
                exchange_stats["rows"] += 1 if status == "ok" else 0
                exchange_stats["placeholders"] += 0 if status == "ok" else 1
                exchange_stats["errors"] += 1 if status == "api_error" else 0
            if granularity:
                granularity_stats = stats["by_granularity"].setdefault(granularity, {"rows": 0, "placeholders": 0, "errors": 0, "completed_jobs": 0})
                granularity_stats["rows"] += 1 if status == "ok" else 0
                granularity_stats["placeholders"] += 0 if status == "ok" else 1
                granularity_stats["errors"] += 1 if status == "api_error" else 0
            if market:
                market_stats = stats["by_market"].setdefault(market, {"rows": 0, "placeholders": 0, "errors": 0, "completed_jobs": 0})
                market_stats["rows"] += 1 if status == "ok" else 0
                market_stats["placeholders"] += 0 if status == "ok" else 1
                market_stats["errors"] += 1 if status == "api_error" else 0
    for key in completed:
        exchange, symbol, granularity = key.split(":", 2)
        market = f"{exchange}:{symbol}"
        if exchange in stats["by_exchange"]:
            stats["by_exchange"][exchange]["completed_jobs"] += 1
        if granularity in stats["by_granularity"]:
            stats["by_granularity"][granularity]["completed_jobs"] += 1
        if market in stats["by_market"]:
            stats["by_market"][market]["completed_jobs"] += 1
    stats["data_status_counts"] = dict(stats["data_status_counts"])
    return completed, stats


def fetch_range(
    *,
    client: PublicOhlcvClient,
    job: HistoryJob,
    candles_per_request: int,
    sleep_sec: float,
) -> tuple[list[Candle], int]:
    interval_sec = INTERVAL_SECONDS[job.granularity]
    cursor = job.start_ts
    requests_made = 0
    deduped: dict[int, Candle] = {}
    while cursor <= job.end_ts:
        chunk_end = min(job.end_ts, cursor + interval_sec * max(1, candles_per_request - 1))
        candles = client.fetch_ohlcv(job.symbol, job.granularity, cursor, chunk_end, candles_per_request)
        requests_made += 1
        for candle in candles:
            if job.start_ts <= candle.ts <= job.end_ts:
                deduped[candle.ts] = candle
        cursor = chunk_end + interval_sec
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    return [deduped[key] for key in sorted(deduped)], requests_made


def increment(mapping: dict[str, Any], key: str, amount: int = 1) -> None:
    mapping[key] = int(mapping.get(key) or 0) + amount


def build_initial_manifest(
    *,
    run_id: str,
    universe_path: Path,
    output_jsonl: Path,
    manifest_path: Path,
    assets: list[UniverseAsset],
    jobs: list[HistoryJob],
    exchanges: list[str],
    granularities: list[str],
    history_days: int,
    candles_per_request: int,
    approval_text: str,
    resumed_existing_stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": "slow_liquidity_history_collect",
        "run_id": run_id,
        "started_at": utc_now_iso(),
        "finished_at": None,
        "final": False,
        "decision": "SLOW_LIQUIDITY_HISTORY_COLLECT_RUNNING",
        "research_only": True,
        "public_data_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "approval_text_sha256": hashlib.sha256(approval_text.encode("utf-8")).hexdigest(),
        "universe_path": str(universe_path),
        "output_jsonl": str(output_jsonl),
        "manifest_path": str(manifest_path),
        "quote": "USDT",
        "history_days": history_days,
        "selected_bases": [asset.base for asset in assets],
        "selected_assets": [asset.__dict__ for asset in assets],
        "exchanges": exchanges,
        "granularities": granularities,
        "candles_per_request": candles_per_request,
        "planned_market_granularity_requests": len(jobs),
        "completed_market_granularity_requests": 0,
        "skipped_completed_jobs": 0,
        "http_requests": 0,
        "rows": int(resumed_existing_stats.get("rows") or 0),
        "ohlcv_rows": int(resumed_existing_stats.get("ohlcv_rows") or 0),
        "placeholder_rows": int(resumed_existing_stats.get("placeholder_rows") or 0),
        "errors": int(resumed_existing_stats.get("errors") or 0),
        "error_samples": [],
        "data_status_counts": resumed_existing_stats.get("data_status_counts") or {},
        "by_exchange": resumed_existing_stats.get("by_exchange") or {},
        "by_granularity": resumed_existing_stats.get("by_granularity") or {},
        "by_market": resumed_existing_stats.get("by_market") or {},
        "next_step_after_ready": "Run slow-liquidity history data-quality gate; keep replay/grid/live/API/paper-forward blocked until quality and fixed-signal gates pass.",
    }


def update_job_stats(manifest: dict[str, Any], job: HistoryJob, *, status: str, row_count: int, requests_made: int = 0) -> None:
    exchange_stats = manifest["by_exchange"].setdefault(job.exchange, {"requests": 0, "rows": 0, "placeholders": 0, "errors": 0, "completed_jobs": 0})
    granularity_stats = manifest["by_granularity"].setdefault(job.granularity, {"requests": 0, "rows": 0, "placeholders": 0, "errors": 0, "completed_jobs": 0})
    market_key = f"{job.exchange}:{job.symbol}"
    market_stats = manifest["by_market"].setdefault(market_key, {"requests": 0, "rows": 0, "placeholders": 0, "errors": 0, "completed_jobs": 0})
    for stats in (exchange_stats, granularity_stats, market_stats):
        stats["requests"] = int(stats.get("requests") or 0) + requests_made
        stats["completed_jobs"] = int(stats.get("completed_jobs") or 0) + 1
        if status == "ok":
            stats["rows"] = int(stats.get("rows") or 0) + row_count
        else:
            stats["placeholders"] = int(stats.get("placeholders") or 0) + 1
        if status == "api_error":
            stats["errors"] = int(stats.get("errors") or 0) + 1


def collect_history(
    *,
    run_id: str,
    universe_path: Path,
    output_jsonl: Path,
    manifest_path: Path,
    confirmed_approval_text: str,
    exchanges: list[str],
    granularities: list[str],
    quote: str,
    history_days: int,
    target_bases: int,
    candles_per_request: int,
    sleep_sec: float,
    timeout_sec: int,
    max_retries: int,
    progress_every: int,
    resume: bool,
    max_jobs: int = 0,
) -> dict[str, Any]:
    if confirmed_approval_text != APPROVAL_TEXT:
        raise ValueError("exact slow-liquidity history collect approval text is required")
    unknown_exchanges = [exchange for exchange in exchanges if exchange not in CLIENTS]
    if unknown_exchanges:
        raise ValueError(f"unsupported exchanges: {', '.join(unknown_exchanges)}")
    unknown_granularities = [granularity for granularity in granularities if granularity not in INTERVAL_SECONDS]
    if unknown_granularities:
        raise ValueError(f"unsupported granularities: {', '.join(unknown_granularities)}")
    if history_days <= 0:
        raise ValueError("history_days must be positive")

    now = datetime.now(timezone.utc)
    end_ts = int(now.timestamp())
    start_ts = int((now - timedelta(days=history_days)).timestamp())
    assets = load_universe(universe_path, max_bases=target_bases)
    jobs = build_jobs(assets, exchanges=exchanges, granularities=granularities, quote=quote, start_ts=start_ts, end_ts=end_ts)
    if max_jobs > 0:
        jobs = jobs[:max_jobs]

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    completed_keys, existing_stats = read_completed_keys(output_jsonl) if resume else (set(), {})
    if not resume and output_jsonl.exists():
        output_jsonl.unlink()
    manifest = build_initial_manifest(
        run_id=run_id,
        universe_path=universe_path,
        output_jsonl=output_jsonl,
        manifest_path=manifest_path,
        assets=assets,
        jobs=jobs,
        exchanges=exchanges,
        granularities=granularities,
        history_days=history_days,
        candles_per_request=candles_per_request,
        approval_text=confirmed_approval_text,
        resumed_existing_stats=existing_stats,
    )
    manifest["completed_market_granularity_requests"] = len(completed_keys)
    manifest["skipped_completed_jobs"] = len(completed_keys)
    write_manifest(manifest_path, manifest)

    clients = {
        exchange: client_cls(timeout_sec=timeout_sec, max_retries=max_retries)
        for exchange, client_cls in CLIENTS.items()
        if exchange in exchanges
    }

    mode = "a" if resume else "w"
    completed = len(completed_keys)
    with output_jsonl.open(mode, encoding="utf-8", newline="\n") as out:
        for job in jobs:
            if job.key in completed_keys:
                continue
            completed += 1
            try:
                candles, requests_made = fetch_range(
                    client=clients[job.exchange],
                    job=job,
                    candles_per_request=candles_per_request,
                    sleep_sec=sleep_sec,
                )
                manifest["http_requests"] += requests_made
                if candles:
                    for candle in candles:
                        out.write(json.dumps(output_row(job, candle=candle, data_status="ok"), ensure_ascii=False) + "\n")
                    manifest["rows"] += len(candles)
                    manifest["ohlcv_rows"] += len(candles)
                    increment(manifest["data_status_counts"], "ok", len(candles))
                    update_job_stats(manifest, job, status="ok", row_count=len(candles), requests_made=requests_made)
                else:
                    out.write(json.dumps(output_row(job, candle=None, data_status="no_data_or_unmatched"), ensure_ascii=False) + "\n")
                    manifest["rows"] += 1
                    manifest["placeholder_rows"] += 1
                    increment(manifest["data_status_counts"], "no_data_or_unmatched")
                    update_job_stats(manifest, job, status="no_data_or_unmatched", row_count=0, requests_made=requests_made)
                out.flush()
            except Exception as exc:  # noqa: BLE001 - preserve failed market evidence and keep the run alive.
                message = f"{job.exchange}:{job.symbol}:{job.granularity} {type(exc).__name__}: {exc}"
                manifest["errors"] += 1
                manifest["rows"] += 1
                manifest["placeholder_rows"] += 1
                if len(manifest["error_samples"]) < 200:
                    manifest["error_samples"].append(message)
                increment(manifest["data_status_counts"], "api_error")
                update_job_stats(manifest, job, status="api_error", row_count=0, requests_made=0)
                out.write(json.dumps(output_row(job, candle=None, data_status="api_error", error=message), ensure_ascii=False) + "\n")
                out.flush()

            manifest["completed_market_granularity_requests"] = completed
            if progress_every > 0 and (completed % progress_every == 0 or completed == len(jobs)):
                print(
                    f"[{utc_now_iso()}] slow-liquidity-history progress "
                    f"{completed}/{len(jobs)} rows={manifest['rows']} "
                    f"ohlcv={manifest['ohlcv_rows']} placeholders={manifest['placeholder_rows']} "
                    f"errors={manifest['errors']} http={manifest['http_requests']}",
                    flush=True,
                )
            write_manifest(manifest_path, manifest)

    manifest["finished_at"] = utc_now_iso()
    manifest["final"] = True
    manifest["decision"] = "SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
    write_manifest(manifest_path, manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect public OHLCV history for slow-liquidity research branch.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--confirmed-approval-text", required=True)
    parser.add_argument("--exchanges", default=",".join(DEFAULT_EXCHANGES))
    parser.add_argument("--granularities", default=",".join(DEFAULT_GRANULARITIES))
    parser.add_argument("--quote", default="USDT")
    parser.add_argument("--history-days", type=int, default=56)
    parser.add_argument("--target-bases", type=int, default=50)
    parser.add_argument("--candles-per-request", type=int, default=1000)
    parser.add_argument("--sleep-sec", type=float, default=0.25)
    parser.add_argument("--timeout-sec", type=int, default=15)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = parse_args(argv)
    exchanges = [normalize_exchange(item) for item in split_csv_list(args.exchanges)]
    granularities = split_csv_list(args.granularities)
    manifest = collect_history(
        run_id=args.run_id,
        universe_path=args.universe,
        output_jsonl=args.output_jsonl,
        manifest_path=args.manifest,
        confirmed_approval_text=args.confirmed_approval_text,
        exchanges=exchanges,
        granularities=granularities,
        quote=str(args.quote or "USDT").strip().upper(),
        history_days=args.history_days,
        target_bases=args.target_bases,
        candles_per_request=args.candles_per_request,
        sleep_sec=args.sleep_sec,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
        progress_every=args.progress_every,
        resume=bool(args.resume),
        max_jobs=args.max_jobs,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "decision": manifest["decision"],
                "run_id": manifest["run_id"],
                "rows": manifest["rows"],
                "ohlcv_rows": manifest["ohlcv_rows"],
                "placeholder_rows": manifest["placeholder_rows"],
                "errors": manifest["errors"],
                "manifest": manifest["manifest_path"],
                "output_jsonl": manifest["output_jsonl"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
