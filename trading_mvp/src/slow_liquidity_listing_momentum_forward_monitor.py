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
from listing_calendar import (
    GATE_CURRENCY_PAIRS_URL,
    MEXC_EXCHANGE_INFO_URL,
    fetch_json,
    rows_from_gate_currency_pairs,
    rows_from_mexc_exchange_info,
)
from slow_liquidity_listing_momentum_first_days_census import compute_window_stats
from slow_liquidity_listing_momentum_first_days_collector import (
    GRANULARITY,
    PROBE_BEFORE_SEC,
    WINDOW_SEC,
    classify_job_bars,
    collect_window_bars,
)
from slow_liquidity_calendar_first_universe import CALENDAR_PATH
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_forward_monitor_planonly_v2"
PLAN_ID = "slow_liquidity_listing_momentum_forward_monitor_20260817_v2"
REPO_ROOT = Path(__file__).resolve().parents[2]
FORWARD_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260817-v2.json"
)
FORWARD_ROOT = Path("E:/trading_mvp/listing-momentum-forward")
TICKS_DIR = FORWARD_ROOT / "ticks"
CLAIM_PATH = (
    REPO_ROOT
    / "docs/agent-log/active-market-data-writer-claim.json"
)
FORWARD_STATE_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_forward_state_20260816.json"
)
BASELINE_AS_OF_TS = int(
    datetime(2026, 8, 16, tzinfo=timezone.utc).timestamp()
)
MAX_NEW_LISTINGS_PER_TICK = 50
MAX_RUNTIME_SEC = 600
TIMEOUT_SEC = 20
SLEEP_SEC = 0.25
EFFECTIVE_PAGE_SIZES = {"mexc": 500, "gateio": 1000}
BASELINE_SNAPSHOT_REQUESTS = 2
EXPECTED_IMPLEMENTATION_PATHS = {
    "forward_monitor": Path(__file__).resolve(),
    "event_window_collector": REPO_ROOT
    / "trading_mvp/src/slow_liquidity_listing_momentum_first_days_collector.py",
    "snapshot_parsers": REPO_ROOT / "trading_mvp/src/listing_calendar.py",
    "public_ohlcv_clients": REPO_ROOT
    / "trading_mvp/src/listing_event_history_collector.py",
    "interval_contract": REPO_ROOT
    / "trading_mvp/src/listing_event_history_collect_plan.py",
    "global_writer_claim": REPO_ROOT
    / "trading_mvp/src/global_market_writer_claim.py",
    "census_stats": REPO_ROOT
    / "trading_mvp/src/slow_liquidity_listing_momentum_first_days_census.py",
    "visible_launcher": REPO_ROOT
    / "tools/start_listing_momentum_forward_tick_visible.ps1",
}


class ForwardMonitorError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ForwardMonitorError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _validate_implementation_bindings(plan: Mapping[str, Any]) -> None:
    raw_files = (plan.get("implementation") or {}).get("files") or []
    _require(isinstance(raw_files, list), "implementation files missing")
    by_role: dict[str, Mapping[str, Any]] = {}
    for item in raw_files:
        _require(isinstance(item, Mapping), "implementation entry invalid")
        role = str(item.get("role") or "")
        _require(role and role not in by_role, "implementation role invalid")
        by_role[role] = item
    _require(
        set(by_role) == set(EXPECTED_IMPLEMENTATION_PATHS),
        "implementation role set mismatch",
    )
    for role, expected_path in EXPECTED_IMPLEMENTATION_PATHS.items():
        item = by_role[role]
        bound_path = Path(str(item.get("path") or ""))
        _require(
            _normalized_path(bound_path) == _normalized_path(expected_path),
            f"implementation path mismatch: {role}",
        )
        _require(expected_path.is_file(), f"implementation file missing: {role}")
        _require(
            str(item.get("sha256") or "") == _sha256_file(expected_path),
            f"implementation sha256 mismatch: {role}",
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def load_and_validate_forward_plan(plan_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _require(plan.get("schema") == SCHEMA, "forward plan schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "forward plan id mismatch")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    _require(plan.get("research_only") is True, "research_only")
    _require(plan.get("public_data_only") is True, "public_data_only")
    _require(plan.get("private_api") is False, "private api")
    _require(
        plan.get("tick", {}).get("max_runtime_sec") == MAX_RUNTIME_SEC,
        "tick runtime bound mismatch",
    )
    baseline = (plan.get("source_bindings") or {}).get("baseline_calendar") or {}
    _require(
        _normalized_path(Path(str(baseline.get("path") or "")))
        == _normalized_path(CALENDAR_PATH),
        "baseline calendar path mismatch",
    )
    _require(
        str(baseline.get("file_sha256") or "") == _sha256_file(CALENDAR_PATH),
        "baseline calendar sha256 mismatch",
    )
    _validate_implementation_bindings(plan)
    return plan


def load_baseline_keys(calendar_path: Path) -> set[tuple[str, str]]:
    import csv

    keys: set[tuple[str, str]] = set()
    with calendar_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            venue = str(row.get("exchange") or "").strip().lower()
            if venue == "gate":
                venue = "gateio"
            if venue not in ("mexc", "gateio"):
                continue
            if str(row.get("quote") or "").strip().upper() != "USDT":
                continue
            if str(row.get("is_delisted") or "").strip().lower() == "true":
                continue
            base = str(row.get("base") or "").strip().upper()
            symbol = str(row.get("symbol") or "").strip().upper()
            if base and symbol:
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
        if str(row.get("is_delisted")).lower() == "true":
            continue
        venue = str(row.get("exchange"))
        base = str(row.get("base") or "").upper()
        symbol = str(row.get("symbol") or "").upper()
        key = (venue, symbol)
        if not base or not symbol or key in baseline_keys:
            continue
        listed_ts = row.get("listed_ts")
        if listed_ts is None or str(listed_ts).strip() == "":
            continue
        listed_ts = int(float(listed_ts))
        previous = candidates.get(key)
        if previous is None or listed_ts < previous["listed_ts"]:
            candidates[key] = {
                "exchange": venue,
                "base": base,
                "symbol": symbol,
                "listed_ts": listed_ts,
            }
    results: list[dict[str, Any]] = []
    for key in sorted(candidates):
        entry = dict(candidates[key])
        if entry["listed_ts"] < baseline_as_of_ts:
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


def derive_forward_jobs(
    new_listings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
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
                "probe_start_ts": ((proxy_ts - PROBE_BEFORE_SEC) // 3600) * 3600,
                "window_end_ts": ((proxy_ts + WINDOW_SEC) // 3600) * 3600,
                "category": entry["category"],
            }
        )
    jobs.sort(key=lambda job: (job["exchange"], job["base"]))
    return jobs


def fetch_current_rows() -> tuple[list[dict[str, Any]], int]:
    mexc_payload = fetch_json(MEXC_EXCHANGE_INFO_URL, timeout_sec=TIMEOUT_SEC)
    gate_payload = fetch_json(GATE_CURRENCY_PAIRS_URL, timeout_sec=TIMEOUT_SEC)
    rows = rows_from_mexc_exchange_info(mexc_payload) + rows_from_gate_currency_pairs(
        gate_payload
    )
    return rows, BASELINE_SNAPSHOT_REQUESTS


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
        "window_role": "first_days_forward",
    }


def run_tick(
    plan: Mapping[str, Any],
    *,
    tick_id: str,
    clients: Mapping[str, Any],
    fetcher: Any = None,
    now_ts: int | None = None,
) -> dict[str, Any]:
    _require(
        tick_id and all(char.isalnum() or char in "_-" for char in tick_id),
        "unsafe tick id",
    )
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
        owner_kind="listing_momentum_forward_monitor_tick",
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
        baseline_keys = load_baseline_keys(CALENDAR_PATH)
        new_listings = diff_new_listings(
            baseline_keys,
            current_rows,
            baseline_as_of_ts=BASELINE_AS_OF_TS,
            now_ts=now_ts,
        )
        skipped = [
            {k: entry[k] for k in ("exchange", "base", "symbol", "listed_ts", "category")}
            for entry in new_listings
            if not entry["collect"]
        ]
        jobs = derive_forward_jobs(new_listings)
        _require(
            len(jobs) <= MAX_NEW_LISTINGS_PER_TICK,
            f"new listings {len(jobs)} exceed tick cap {MAX_NEW_LISTINGS_PER_TICK}",
        )
        tick_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = tick_dir / "manifest.json"
        write_manifest(
            manifest_path,
            {
                "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_tick_manifest_v1",
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
                        candles_per_request=int(
                            EFFECTIVE_PAGE_SIZES.get(
                                job["exchange"], EFFECTIVE_PAGE_SIZES["mexc"]
                            )
                        ),
                        sleep_sec=SLEEP_SEC,
                    )
                    requests_made += requests
                except Exception as exc:  # noqa: BLE001
                    bars = []
                    summary = {
                        "flags": ["request_error"],
                        "error": f"{type(exc).__name__}: {exc}",
                        "window_bar_count": 0,
                    }
                else:
                    summary = classify_job_bars(job, bars)
                    if job["category"] == "new_listing_in_progress":
                        summary["flags"] = list(summary["flags"]) + [
                            "window_in_progress"
                        ]
                summary.pop("window_bars", None)
                summary.update(
                    {
                        "exchange": job["exchange"],
                        "base": job["base"],
                        "symbol": job["symbol"],
                        "proxy_ts": job["proxy_ts"],
                        "category": job["category"],
                        "requests": requests,
                    }
                )
                job_summaries.append(summary)
                for bar in bars:
                    if job["proxy_ts"] <= bar.ts < job["window_end_ts"]:
                        handle.write(
                            json.dumps(_forward_row(job, bar), ensure_ascii=False)
                            + "\n"
                        )
                        rows_written += 1
        manifest = {
            "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_tick_manifest_v1",
            "tick_id": tick_id,
            "status": "COMPLETED" if stop_reason == "completed" else "STOPPED_INCOMPLETE",
            "stop_reason": stop_reason,
            "started_at_utc": started_utc,
            "finished_at_utc": utc_now_iso(),
            "plan_hash": plan["plan_hash"],
            "now_ts": now_ts,
            "baseline_as_of_ts": BASELINE_AS_OF_TS,
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
            bars_by_key.setdefault(
                (str(row["exchange"]), str(row["base"])), []
            ).append(row)
        job_flags = {
            (job.get("exchange"), job.get("base")): job.get("flags") or []
            for job in manifest.get("jobs") or []
        }
        for key, bars in bars_by_key.items():
            windows[key] = {
                "exchange": key[0],
                "base": key[1],
                "flags": job_flags.get(key, []),
                "window_complete": "window_in_progress"
                not in job_flags.get(key, []),
                "stats": compute_window_stats(bars),
            }
    ordered_windows = [windows[key] for key in sorted(windows)]
    payload: dict[str, Any] = {
        "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_state_v1",
        "monitor": PLAN_ID,
        "evidence_class": "PROXY_DATE_FORWARD_ACCRUAL",
        "acceptance_decision": "NONE_ACCRUAL_ONLY",
        "ticks": ticks,
        "tick_count": len(ticks),
        "window_count": len(ordered_windows),
        "complete_window_count": sum(
            1 for window in ordered_windows if window["window_complete"]
        ),
        "windows": ordered_windows,
    }
    payload["state_hash"] = canonical_hash(payload)
    FORWARD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FORWARD_STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return payload


def tick_status() -> dict[str, Any]:
    if not FORWARD_STATE_PATH.is_file():
        return {"status": "NO_TICKS_YET", "monitor": PLAN_ID}
    payload = json.loads(FORWARD_STATE_PATH.read_text(encoding="utf-8"))
    return {
        "status": "ACCRUING",
        "tick_count": payload["tick_count"],
        "window_count": payload["window_count"],
        "complete_window_count": payload["complete_window_count"],
        "state_hash": payload["state_hash"],
        "last_ticks": payload["ticks"][-3:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(FORWARD_PLAN_PATH))
    parser.add_argument("--tick", action="store_true")
    parser.add_argument("--confirmed-visible-tick", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--plan-check", action="store_true")
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(tick_status(), ensure_ascii=False))
        return 0
    plan = load_and_validate_forward_plan(Path(args.plan))
    if args.plan_check:
        baseline_sha = _sha256_file(CALENDAR_PATH)
        print(
            json.dumps(
                {
                    "status": "PLAN_OK",
                    "plan_hash": plan["plan_hash"],
                    "baseline_calendar_sha256": baseline_sha,
                    "max_runtime_sec": MAX_RUNTIME_SEC,
                    "tick_output_root": str(TICKS_DIR),
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not args.tick or not args.confirmed_visible_tick:
        raise SystemExit("no authorized action requested")
    tick_id = "forward_tick_" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    from listing_event_history_collector import CLIENTS

    clients = {
        venue: CLIENTS[venue](timeout_sec=TIMEOUT_SEC, max_retries=1)
        for venue in ("mexc", "gateio")
    }
    manifest = run_tick(plan, tick_id=tick_id, clients=clients)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "tick_id": manifest["tick_id"],
                "new_listing_count": manifest["new_listing_count"],
                "rows_written": manifest["rows_written"],
                "skipped": manifest["skipped_backfill_or_relist"],
                "state": tick_status(),
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
