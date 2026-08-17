from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from global_market_writer_claim import (
    claim_global_market_writer,
    release_global_market_writer,
)
from listing_momentum_exchange_expansion import (
    SUPPORTED_VENUES,
    DEFAULT_PREFLIGHT_PATH,
    ExpansionSpotOhlcvClient,
    fetch_current_snapshot_rows,
    resolve_proxy_timestamp,
)
from slow_liquidity_listing_momentum_first_days_census import compute_window_stats
from slow_liquidity_listing_momentum_first_days_collector import (
    GRANULARITY,
    PROBE_BEFORE_SEC,
    WINDOW_SEC,
    classify_job_bars,
    collect_window_bars,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_monitor_planonly_v1"
PLAN_ID = "slow_liquidity_listing_momentum_forward_expansion_20260817_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-expansion-planonly-20260817.json"
)
FORWARD_ROOT = Path("E:/trading_mvp/listing-momentum-forward-expansion")
TICKS_DIR = FORWARD_ROOT / "ticks"
STATE_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_forward_expansion_state_20260817.json"
)
CLAIM_PATH = (
    REPO_ROOT
    / "docs/agent-log/active-market-data-writer-expansion-claim.json"
)
MAX_NEW_LISTINGS_PER_TICK = 50
MAX_RUNTIME_SEC = 600
TIMEOUT_SEC = 20
SLEEP_SEC = 0.25
EFFECTIVE_PAGE_SIZES = {
    "binance": 1000,
    "bybit": 1000,
    "okx": 300,
    "bitget": 1000,
}


class ExpansionMonitorError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ExpansionMonitorError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_ts(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp())


def _validate_plan(plan: Mapping[str, Any], plan_path: Path) -> None:
    _require(plan.get("schema") == SCHEMA, "expansion plan schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "expansion plan id mismatch")
    _require(plan.get("plan_hash") == canonical_hash(plan), "expansion plan hash mismatch")
    _require(plan.get("research_only") is True, "expansion plan must be research-only")
    _require(plan.get("public_data_only") is True, "expansion plan must be public-data-only")
    _require(plan.get("private_api") is False, "private API is forbidden")
    _require(plan.get("replay_allowed") is False, "replay must remain blocked")
    _require(plan.get("evaluator_or_oos_allowed") is False, "evaluator/OOS must remain blocked")
    _require(tuple(plan.get("venues") or []) == SUPPORTED_VENUES, "expansion venue set mismatch")
    preflight = (plan.get("source_bindings") or {}).get("preflight") or {}
    preflight_path = Path(str(preflight.get("path") or ""))
    _require(preflight_path.resolve() == DEFAULT_PREFLIGHT_PATH.resolve(), "preflight path mismatch")
    _require(preflight_path.is_file(), "preflight receipt missing")
    _require(_sha256_file(preflight_path) == preflight.get("file_sha256"), "preflight file sha mismatch")
    payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    _require(payload.get("receipt_hash") == preflight.get("receipt_hash"), "preflight receipt binding mismatch")
    implementation = (plan.get("implementation") or {}).get("files") or []
    expected = {
        "expansion_adapter": REPO_ROOT / "trading_mvp/src/listing_momentum_exchange_expansion.py",
        "expansion_monitor": Path(__file__).resolve(),
        "preflight_launcher": REPO_ROOT / "tools/start_listing_momentum_exchange_expansion_preflight_visible.ps1",
        "expansion_plan_generator": REPO_ROOT / "trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_plan.py",
    }
    by_role = {str(item.get("role")): item for item in implementation if isinstance(item, Mapping)}
    _require(set(by_role) == set(expected), "expansion implementation role set mismatch")
    for role, expected_path in expected.items():
        _require(expected_path.is_file(), f"expansion implementation missing: {role}")
        _require(
            Path(str(by_role[role].get("path") or "")).resolve() == expected_path.resolve(),
            f"expansion implementation path mismatch: {role}",
        )
        _require(
            str(by_role[role].get("sha256") or "") == _sha256_file(expected_path),
            f"expansion implementation sha mismatch: {role}",
        )
    del plan_path


def load_plan(path: Path = PLAN_PATH) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    _validate_plan(plan, path)
    return plan


def load_baseline_keys(preflight_path: Path = DEFAULT_PREFLIGHT_PATH) -> set[tuple[str, str]]:
    payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    keys: set[tuple[str, str]] = set()
    for venue_result in payload.get("venues") or []:
        venue = str(venue_result.get("exchange") or "")
        for row in venue_result.get("snapshot_rows") or []:
            symbol = str(row.get("symbol") or "").upper()
            if venue in SUPPORTED_VENUES and symbol:
                keys.add((venue, symbol))
    return keys


def diff_new_listings(
    baseline_keys: set[tuple[str, str]],
    current_rows: Sequence[Mapping[str, Any]],
    *,
    baseline_as_of_ts: int,
    now_ts: int,
) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for row in current_rows:
        venue = str(row.get("exchange") or "")
        symbol = str(row.get("symbol") or "").upper()
        base = str(row.get("base") or "").upper()
        if venue not in SUPPORTED_VENUES or not symbol or not base:
            continue
        if bool(row.get("is_delisted")) or (venue, symbol) in baseline_keys:
            continue
        proxy_ts, timestamp_source = resolve_proxy_timestamp(row, now_ts=now_ts)
        candidate = {
            "exchange": venue,
            "base": base,
            "symbol": symbol,
            "listed_ts": proxy_ts,
            "timestamp_source": timestamp_source,
            "is_proxy_timestamp": timestamp_source.endswith("proxy"),
        }
        previous = candidates.get((venue, symbol))
        if previous is None or proxy_ts < previous["listed_ts"]:
            candidates[(venue, symbol)] = candidate
    results: list[dict[str, Any]] = []
    for key in sorted(candidates):
        entry = dict(candidates[key])
        if not entry["is_proxy_timestamp"] and entry["listed_ts"] < baseline_as_of_ts:
            entry["category"] = "backfill_or_relist_skip"
            entry["collect"] = False
        elif entry["listed_ts"] + WINDOW_SEC <= now_ts:
            entry["category"] = "new_listing_window_complete"
            entry["collect"] = True
        else:
            entry["category"] = "new_listing_in_progress"
            entry["collect"] = True
        results.append(entry)
    return results


def derive_forward_jobs(new_listings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for entry in new_listings:
        if not entry.get("collect"):
            continue
        proxy_ts = int(entry["listed_ts"])
        jobs.append(
            {
                "exchange": entry["exchange"],
                "base": entry["base"],
                "symbol": entry["symbol"],
                "proxy_ts": proxy_ts,
                "timestamp_source": entry["timestamp_source"],
                "probe_start_ts": ((proxy_ts - PROBE_BEFORE_SEC) // 3600) * 3600,
                "window_end_ts": ((proxy_ts + WINDOW_SEC) // 3600) * 3600,
                "category": entry["category"],
            }
        )
    jobs.sort(key=lambda job: (job["exchange"], job["base"], job["symbol"]))
    return jobs


def fetch_current_rows() -> tuple[list[dict[str, Any]], int]:
    return fetch_current_snapshot_rows(timeout_sec=TIMEOUT_SEC)


def _forward_row(job: Mapping[str, Any], bar: Any) -> dict[str, Any]:
    return {
        "monitor": PLAN_ID,
        "exchange": job["exchange"],
        "base": job["base"],
        "symbol": job["symbol"],
        "granularity": GRANULARITY,
        "ts": bar.ts,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "proxy_event_ts": job["proxy_ts"],
        "proxy_timestamp_source": job["timestamp_source"],
        "window_role": "first_days_forward_expansion",
    }


def run_tick(
    plan: Mapping[str, Any],
    *,
    tick_id: str,
    clients: Mapping[str, Any],
    fetcher: Any = None,
    now_ts: int | None = None,
) -> dict[str, Any]:
    _require(tick_id and all(char.isalnum() or char in "_-" for char in tick_id), "unsafe tick id")
    tick_dir = TICKS_DIR / tick_id
    _require(not tick_dir.exists(), f"tick {tick_id} already exists")
    from listing_event_history_collector import write_manifest

    now_ts = int(now_ts if now_ts is not None else time.time())
    deadline = time.monotonic() + MAX_RUNTIME_SEC
    fetcher = fetcher or fetch_current_rows
    started_utc = utc_now_iso()
    claim = claim_global_market_writer(
        CLAIM_PATH,
        run_id=f"{PLAN_ID}__{tick_id}",
        owner_pid=os.getpid(),
        owner_kind="listing_momentum_forward_expansion_monitor_tick",
        plan_hash=plan["plan_hash"],
        output_namespace=tick_dir,
    )
    stop_reason = "completed"
    rows_written = 0
    requests_made = 0
    job_summaries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        current_rows, snapshot_requests = fetcher()
        requests_made += snapshot_requests
        baseline = (plan.get("source_bindings") or {}).get("preflight") or {}
        baseline_as_of_ts = int(baseline.get("baseline_as_of_ts") or 0)
        baseline_keys = load_baseline_keys(Path(str(baseline["path"])))
        new_listings = diff_new_listings(
            baseline_keys,
            current_rows,
            baseline_as_of_ts=baseline_as_of_ts,
            now_ts=now_ts,
        )
        skipped = [
            {
                key: entry[key]
                for key in (
                    "exchange",
                    "base",
                    "symbol",
                    "listed_ts",
                    "timestamp_source",
                    "category",
                )
            }
            for entry in new_listings
            if not entry["collect"]
        ]
        jobs = derive_forward_jobs(new_listings)
        _require(len(jobs) <= MAX_NEW_LISTINGS_PER_TICK, f"new listings {len(jobs)} exceed tick cap {MAX_NEW_LISTINGS_PER_TICK}")
        tick_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = tick_dir / "manifest.json"
        write_manifest(
            manifest_path,
            {
                "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_tick_manifest_v1",
                "tick_id": tick_id,
                "status": "RUNNING",
                "started_at_utc": started_utc,
                "plan_hash": plan["plan_hash"],
                "ownership_token": claim["ownership_token"],
                "jobs_total": len(jobs),
            },
        )
        with (tick_dir / "ohlcv.jsonl").open("w", encoding="utf-8") as handle:
            for job in jobs:
                if time.monotonic() > deadline:
                    stop_reason = "max_runtime_sec_exceeded"
                    break
                requests = 0
                try:
                    client = clients[job["exchange"]]
                    bars, requests = collect_window_bars(
                        client,
                        job,
                        candles_per_request=int(EFFECTIVE_PAGE_SIZES[job["exchange"]]),
                        sleep_sec=SLEEP_SEC,
                    )
                    requests_made += requests
                except Exception as exc:  # noqa: BLE001 - per-job resilience
                    bars = []
                    summary = {
                        "flags": ["request_error"],
                        "error": f"{type(exc).__name__}: {exc}",
                        "window_bar_count": 0,
                    }
                else:
                    summary = classify_job_bars(job, bars)
                    if job["category"] == "new_listing_in_progress":
                        summary["flags"] = list(summary["flags"]) + ["window_in_progress"]
                summary.pop("window_bars", None)
                summary.update(
                    {
                        "exchange": job["exchange"],
                        "base": job["base"],
                        "symbol": job["symbol"],
                        "proxy_ts": job["proxy_ts"],
                        "timestamp_source": job["timestamp_source"],
                        "category": job["category"],
                        "requests": requests,
                    }
                )
                job_summaries.append(summary)
                for bar in bars:
                    if job["proxy_ts"] <= bar.ts < job["window_end_ts"]:
                        handle.write(json.dumps(_forward_row(job, bar), ensure_ascii=False) + "\n")
                        rows_written += 1
        manifest = {
            "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_tick_manifest_v1",
            "tick_id": tick_id,
            "status": "COMPLETED" if stop_reason == "completed" else "STOPPED_INCOMPLETE",
            "stop_reason": stop_reason,
            "started_at_utc": started_utc,
            "finished_at_utc": utc_now_iso(),
            "plan_hash": plan["plan_hash"],
            "now_ts": now_ts,
            "baseline_as_of_ts": baseline_as_of_ts,
            "new_listing_count": len(job_summaries),
            "skipped_backfill_or_relist": skipped,
            "jobs_total": len(job_summaries),
            "jobs": job_summaries,
            "rows_written": rows_written,
            "requests_made": requests_made,
        }
        write_manifest(manifest_path, manifest)
    finally:
        release_global_market_writer(
            CLAIM_PATH,
            run_id=f"{PLAN_ID}__{tick_id}",
            owner_pid=int(claim["owner_pid"]),
            ownership_token=str(claim["ownership_token"]),
            final_status=stop_reason,
        )
    rebuild_forward_state()
    return manifest


def _tick_dirs() -> list[Path]:
    if not TICKS_DIR.is_dir():
        return []
    return sorted(path for path in TICKS_DIR.iterdir() if path.is_dir())


def rebuild_forward_state() -> dict[str, Any]:
    windows: dict[tuple[str, str], dict[str, Any]] = {}
    ticks: list[dict[str, Any]] = []
    for tick_dir in _tick_dirs():
        manifest_path = tick_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ticks.append(
            {
                "tick_id": manifest.get("tick_id"),
                "status": manifest.get("status"),
                "new_listing_count": manifest.get("new_listing_count"),
                "rows_written": manifest.get("rows_written"),
            }
        )
        rows_path = tick_dir / "ohlcv.jsonl"
        if not rows_path.is_file():
            continue
        bars_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            bars_by_key.setdefault((str(row["exchange"]), str(row["base"])), []).append(row)
        job_flags = {
            (job.get("exchange"), job.get("base")): job.get("flags") or []
            for job in manifest.get("jobs") or []
        }
        for key, bars in bars_by_key.items():
            windows[key] = {
                "exchange": key[0],
                "base": key[1],
                "flags": job_flags.get(key, []),
                "window_complete": "window_in_progress" not in job_flags.get(key, []),
                "stats": compute_window_stats(bars),
            }
    ordered_windows = [windows[key] for key in sorted(windows)]
    payload: dict[str, Any] = {
        "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_state_v1",
        "monitor": PLAN_ID,
        "evidence_class": "PROXY_DATE_FORWARD_ACCRUAL_EXPANSION",
        "acceptance_decision": "NONE_ACCRUAL_ONLY",
        "venues": list(SUPPORTED_VENUES),
        "ticks": ticks,
        "tick_count": len(ticks),
        "window_count": len(ordered_windows),
        "complete_window_count": sum(1 for window in ordered_windows if window["window_complete"]),
        "windows": ordered_windows,
    }
    payload["state_hash"] = canonical_hash(payload)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def tick_status() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {"status": "NO_TICKS_YET", "monitor": PLAN_ID, "venues": list(SUPPORTED_VENUES)}
    payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "status": "ACCRUING",
        "monitor": PLAN_ID,
        "venues": payload.get("venues"),
        "tick_count": payload["tick_count"],
        "window_count": payload["window_count"],
        "complete_window_count": payload["complete_window_count"],
        "state_hash": payload["state_hash"],
        "last_ticks": payload["ticks"][-3:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(PLAN_PATH))
    parser.add_argument("--tick", action="store_true")
    parser.add_argument("--confirmed-visible-tick", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--plan-check", action="store_true")
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(tick_status(), ensure_ascii=False))
        return 0
    plan = load_plan(Path(args.plan))
    if args.plan_check:
        print(
            json.dumps(
                {
                    "status": "PLAN_OK",
                    "plan_hash": plan["plan_hash"],
                    "venues": list(SUPPORTED_VENUES),
                    "preflight_receipt_hash": (plan.get("source_bindings") or {}).get("preflight", {}).get("receipt_hash"),
                    "max_runtime_sec": MAX_RUNTIME_SEC,
                    "tick_output_root": str(TICKS_DIR),
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not args.tick or not args.confirmed_visible_tick:
        raise SystemExit("no authorized action requested")
    tick_id = "expansion_tick_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clients = {
        venue: ExpansionSpotOhlcvClient(venue, timeout_sec=TIMEOUT_SEC)
        for venue in SUPPORTED_VENUES
    }
    manifest = run_tick(plan, tick_id=tick_id, clients=clients)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "tick_id": manifest["tick_id"],
                "new_listing_count": manifest["new_listing_count"],
                "rows_written": manifest["rows_written"],
                "state": tick_status(),
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
