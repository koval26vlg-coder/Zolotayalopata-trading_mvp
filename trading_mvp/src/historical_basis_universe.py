from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

from costs import validate_runtime_sec
from historical_basis_collector import (
    GateHistoricalBasisClient,
    HistoricalDataRetentionError,
    MexcHistoricalBasisClient,
)
from historical_basis_code_snapshot import validate_basis_code_snapshot_reference
from historical_basis_edge import sha256_file, sha256_json
from owned_run_gate import publish_owned_run_gate


SCHEMA = "trading_mvp_historical_basis_universe_availability_v1"
MIN_ASSETS = 8
MAX_PROBE_POOL = 60
MAX_PLAN_ASSETS = 20
HISTORY_DAYS = 220
DAY_SEC = 86_400
CANDLE_SEC = 300
SERIES = ("trade", "mark", "index")
DEFAULT_OUTPUT_ROOT = Path(r"E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis\universe")


class BoundaryHistoryClient(Protocol):
    def fetch_5m_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]: ...


class MinimumIntervalLimiter:
    def __init__(self, interval_sec: float) -> None:
        self.interval_sec = max(float(interval_sec), 0.0)
        self._next_allowed = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            if delay:
                time.sleep(delay)
            self._next_allowed = time.monotonic() + self.interval_sec


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def classify_excluded_categories(name: str, symbol: str, coin_id: str) -> list[str]:
    text = " ".join((name, symbol, coin_id)).lower().replace("-", " ").replace("_", " ")
    compact_symbol = symbol.strip().upper()
    categories: set[str] = set()
    if compact_symbol in {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USD1"} or "stablecoin" in text:
        categories.add("stable")
    if any(term in text for term in ("wrapped ", "bridged ", "wormhole ")):
        categories.add("wrapped")
    if any(term in text for term in ("staked ", "liquid staking", "restaked ")):
        categories.add("staked")
    if any(term in text for term in ("leveraged", "3x long", "3x short")) or compact_symbol.endswith(("3L", "3S", "BULL", "BEAR")):
        categories.add("leveraged")
    if any(term in text for term in (" lp token", "liquidity pool", "liquidity provider")):
        categories.add("lp")
    if any(term in text for term in ("synthetic", "synth ")):
        categories.add("synthetic")
    if any(term in text for term in ("tokenized stock", "stock token", "tokenized etf", "tokenized commodity", "equity token")):
        categories.add("tokenized")
    if "stock" in compact_symbol or "ETF" in compact_symbol:
        categories.add("tokenized")
    if any(term in text for term in ("pre market", "pre-market", "premarket")):
        categories.add("pre-market")
    if " index" in f" {text}" or text.endswith(" index"):
        categories.add("index")
    return sorted(categories)


def _load_coin_registry(path: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    by_symbol: dict[str, list[dict[str, str]]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "").strip().upper()
            coin_id = str(row.get("coin_id") or "").strip()
            if symbol and coin_id:
                by_symbol.setdefault(symbol, []).append(row)
    collisions = {symbol for symbol, rows in by_symbol.items() if len({row["coin_id"] for row in rows}) != 1}
    unique = {symbol: rows[0] for symbol, rows in by_symbol.items() if symbol not in collisions}
    return unique, collisions


def _load_dual_pit_rows(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "pit_universe_state_v1" or not isinstance(payload.get("symbols"), dict):
        raise ValueError("expected pit_universe_state_v1")
    by_base: dict[str, dict[str, dict[str, Any]]] = {}
    for item in payload["symbols"].values():
        row = item.get("row") if isinstance(item, dict) else None
        if not isinstance(row, dict):
            continue
        venue = str(row.get("exchange") or "").strip().lower()
        base = str(row.get("base") or "").strip().upper()
        if venue in {"mexc", "gateio"} and base:
            by_base.setdefault(base, {})[venue] = row
    return by_base


def _prefilter_candidates(
    pit_rows: dict[str, dict[str, dict[str, Any]]],
    registry: dict[str, dict[str, str]],
    collisions: set[str],
    *,
    minimum_current_volume_quote: float,
    maximum_current_spread_bps: float,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    for base, venues in sorted(pit_rows.items()):
        if set(venues) != {"mexc", "gateio"}:
            rejections["not_dual_venue"] += 1
            continue
        if base in collisions or base not in registry:
            rejections["identity_collision" if base in collisions else "identity_unmatched"] += 1
            continue
        rows = [venues["mexc"], venues["gateio"]]
        if any(str(row.get("status") or "").lower() != "trading" or not row.get("listed_now") or row.get("tombstone") for row in rows):
            rejections["lifecycle"] += 1
            continue
        if any(row.get("eligible_non_binance_spot") is not True or row.get("binance_spot_listed") is not False for row in rows):
            rejections["binance_spot_or_unverified"] += 1
            continue
        worst_volume = min(float(row.get("volume_24h_quote") or 0.0) for row in rows)
        worst_spread = max(float(row.get("spread_bps") or float("inf")) for row in rows)
        if worst_volume < minimum_current_volume_quote:
            rejections["current_execution_volume"] += 1
            continue
        if worst_spread > maximum_current_spread_bps:
            rejections["current_execution_spread"] += 1
            continue
        identity = registry[base]
        categories = classify_excluded_categories(identity.get("name") or "", base, identity["coin_id"])
        if categories:
            rejections["excluded_category"] += 1
            continue
        candidates.append(
            {
                "canonical_asset_id": f"coingecko:{identity['coin_id']}",
                "base": base,
                "quote": "USDT",
                "mexc_symbol": str(venues["mexc"]["symbol"]),
                "gateio_symbol": str(venues["gateio"]["symbol"]),
                "mexc_status": "trading",
                "gateio_status": "trading",
                "binance_spot": False,
                "categories": [],
                "identity_source": "coingecko_coin_id_unique_symbol_join",
                "identity_name": identity.get("name"),
                "current_worst_leg_volume_quote": worst_volume,
                "current_worst_spread_bps": worst_spread,
            }
        )
    candidates.sort(key=lambda row: (-row["current_worst_leg_volume_quote"], row["canonical_asset_id"]))
    return candidates[:MAX_PROBE_POOL], rejections


def _probe_venue(
    venue: str,
    client: BoundaryHistoryClient,
    candidates: list[dict[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    deadline: float,
    request_interval_sec: float,
) -> list[dict[str, Any]]:
    limiter = MinimumIntervalLimiter(request_interval_sec)
    statuses: list[dict[str, Any]] = []
    symbol_key = f"{venue}_symbol"
    total = len(candidates) * len(SERIES)
    completed = 0
    started = time.monotonic()
    for candidate in candidates:
        for series in SERIES:
            completed += 1
            status = "available"
            error = None
            rows = 0
            if time.monotonic() >= deadline:
                status = "timeout"
                error = "MaxRuntimeSec exceeded"
            else:
                try:
                    limiter.wait()
                    values = client.fetch_5m_series(candidate[symbol_key], series, start_sec, end_sec)
                    rows = len(values)
                    if rows == 0:
                        status = "missing"
                except Exception as exc:  # noqa: BLE001
                    retention_limited = isinstance(exc, HistoricalDataRetentionError) or (
                        "maximum_recent_points=10000" in str(exc).lower()
                    )
                    status = "retention_limited" if retention_limited else "error"
                    error = f"{type(exc).__name__}: {exc}"
            statuses.append(
                {
                    "canonical_asset_id": candidate["canonical_asset_id"],
                    "base": candidate["base"],
                    "venue": venue,
                    "symbol": candidate[symbol_key],
                    "series": series,
                    "status": status,
                    "rows": rows,
                    "error": error,
                }
            )
            elapsed = max(time.monotonic() - started, 1e-9)
            eta = (total - completed) / (completed / elapsed)
            print(
                f"[basis-universe:{venue}] {completed}/{total} {candidate['base']} {series} "
                f"status={status} rows={rows} eta_sec={eta:.1f}",
                flush=True,
            )
    return statuses


def build_basis_universe_availability(
    pit_state_path: str | Path,
    coin_registry_path: str | Path,
    output_path: str | Path,
    *,
    clients: dict[str, BoundaryHistoryClient] | None = None,
    now_sec: int | None = None,
    max_runtime_sec: int = 600,
    minimum_current_volume_quote: float = 1_000_000.0,
    maximum_current_spread_bps: float = 10.0,
    request_interval_sec: float = 0.0,
    active_gate_path: str | Path | None = None,
    run_id: str | None = None,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
) -> dict[str, Any]:
    runtime = validate_runtime_sec(max_runtime_sec)
    if runtime > 600:
        raise ValueError("basis universe availability max_runtime_sec must be <= 600")
    snapshot = validate_basis_code_snapshot_reference(
        code_snapshot_hash,
        code_snapshot_manifest,
        fallback_code_path=__file__,
    )
    pit_target = Path(pit_state_path).expanduser().resolve()
    registry_target = Path(coin_registry_path).expanduser().resolve()
    output_target = Path(output_path).expanduser().resolve()
    if output_target.exists():
        raise FileExistsError(f"artifact already exists: {output_target}")
    registry, collisions = _load_coin_registry(registry_target)
    candidates, rejections = _prefilter_candidates(
        _load_dual_pit_rows(pit_target),
        registry,
        collisions,
        minimum_current_volume_quote=minimum_current_volume_quote,
        maximum_current_spread_bps=maximum_current_spread_bps,
    )
    end_sec = ((int(now_sec if now_sec is not None else time.time()) // CANDLE_SEC) * CANDLE_SEC) - CANDLE_SEC
    boundary_start_sec = end_sec - HISTORY_DAYS * DAY_SEC + CANDLE_SEC
    boundary_end_sec = boundary_start_sec + DAY_SEC - CANDLE_SEC
    clients = clients or {
        "mexc": MexcHistoricalBasisClient(),
        "gateio": GateHistoricalBasisClient(),
    }
    if set(clients) != {"mexc", "gateio"}:
        raise ValueError("basis universe availability requires mexc and gateio clients")
    started = time.monotonic()
    deadline = started + runtime
    run_id = run_id or f"basis_universe_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    gate_target = Path(active_gate_path).expanduser().resolve() if active_gate_path else None
    gate_base = {
        "schema": "active_run_gate_v2",
        "project": "trading_mvp",
        "run_id": run_id,
        "collector_pid": os.getpid(),
        "process_ids": [os.getpid()],
        "monitor_pid": None,
        "output": {"path": str(output_target), "kind": "file"},
        "output_path": str(output_target),
        "manifest_path": str(output_target),
        "locks": ["market_data_writer"],
        "owner_output_prefix": str(output_target.parent),
        "code_snapshot_hash": snapshot["code_snapshot_hash"],
        "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
        "parallel_safe_actions": ["code_work", "unit_tests", "fixtures", "static_analysis", "immutable_cache_compute"],
        "forbidden_overlapping_actions": ["collector", "probe", "consumer_of_owner_output", "postprocess", "grid_search"],
        "replay_allowed": False,
        "grid_allowed": False,
        "live_orders_allowed": False,
    }
    if gate_target is not None:
        publish_owned_run_gate(
            gate_target,
            {**gate_base, "status": "RUNNING", "gate_status": "RUNNING", "updated_at": _utc_now()},
            run_type="historical_basis_universe_availability",
        )
    statuses: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="basis-universe") as pool:
        futures = {
            pool.submit(
                _probe_venue,
                venue,
                clients[venue],
                candidates,
                start_sec=boundary_start_sec,
                end_sec=boundary_end_sec,
                deadline=deadline,
                request_interval_sec=request_interval_sec,
            ): venue
            for venue in ("mexc", "gateio")
        }
        for future in as_completed(futures):
            statuses.extend(future.result())
    status_by_asset: dict[str, list[dict[str, Any]]] = {}
    for status in statuses:
        status_by_asset.setdefault(status["canonical_asset_id"], []).append(status)
    eligible: list[dict[str, Any]] = []
    retention_limited_assets: set[str] = set()
    for candidate in candidates:
        rows = status_by_asset.get(candidate["canonical_asset_id"], [])
        if len(rows) != 6 or any(row["status"] != "available" for row in rows):
            if any(row["status"] == "retention_limited" for row in rows):
                rejections["history_api_retention_limit"] += 1
                retention_limited_assets.add(candidate["canonical_asset_id"])
            else:
                rejections["history_boundary_missing"] += 1
            continue
        eligible.append({**candidate, "common_history_days": HISTORY_DAYS})
    eligible = eligible[:MAX_PLAN_ASSETS]
    for rank, row in enumerate(eligible, start=1):
        row["liquidity_rank"] = rank
    if len(eligible) >= MIN_ASSETS:
        decision = "READY_FOR_BASIS_PLAN"
    elif retention_limited_assets:
        decision = "INSUFFICIENT_DATA"
    else:
        decision = "INSUFFICIENT_EXECUTABLE_UNIVERSE"
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": _utc_now(),
        "run_id": run_id,
        "final": True,
        "decision": decision,
        "assets": eligible,
        "asset_count": len(eligible),
        "probed_candidate_count": len(candidates),
        "rejections_by_reason": dict(sorted(rejections.items())),
        "history_probe": {
            "history_days": HISTORY_DAYS,
            "boundary_start_sec": boundary_start_sec,
            "boundary_end_sec": boundary_end_sec,
            "required_series": list(SERIES),
            "required_series_count_per_asset": 6,
            "retention_limited_asset_count": len(retention_limited_assets),
            "known_api_limits": {
                "gateio_5m_maximum_recent_points": 10_000,
                "gateio_5m_maximum_recent_days": round(10_000 * CANDLE_SEC / DAY_SEC, 3),
            },
            "statuses": sorted(statuses, key=lambda row: (row["base"], row["venue"], row["series"])),
        },
        "selection_policy": {
            "identity": "unique CoinGecko coin_id by symbol; collisions excluded",
            "current_metadata_role": "acquisition priority and execution sanity only; never OOS return selection",
            "minimum_current_worst_leg_volume_quote": minimum_current_volume_quote,
            "maximum_current_worst_spread_bps": maximum_current_spread_bps,
            "train_liquidity_reselection_required": True,
            "survivorship_limit": "current active contracts; historical lifecycle quality remains mandatory",
        },
        "source_provenance": {
            "pit_state_path": str(pit_target),
            "pit_state_sha256": sha256_file(pit_target),
            "coin_registry_path": str(registry_target),
            "coin_registry_sha256": sha256_file(registry_target),
            "code_sha256": sha256_file(__file__),
            **snapshot,
        },
        "runtime_sec": round(time.monotonic() - started, 3),
        "max_runtime_sec": runtime,
        "safety": {"research_only": True, "public_api_only": True, "live_orders": False, "api_keys": False},
        "next_allowed_command": (
            "fast-edge-basis-plan"
            if decision == "READY_FOR_BASIS_PLAN"
            else "close-hypothesis-insufficient-history-api-retention"
            if decision == "INSUFFICIENT_DATA"
            else "close-hypothesis-insufficient-universe"
        ),
    }
    result["universe_hash"] = sha256_json(eligible)
    result["artifact_hash"] = sha256_json({key: value for key, value in result.items() if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}})
    _atomic_write_json(output_target, result)
    if gate_target is not None:
        publish_owned_run_gate(
            gate_target,
            {
                **gate_base,
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "final": True,
                "collector_pid": None,
                "process_ids": [],
                "next_goal_decision": decision,
                "next_step_after_ready": result["next_allowed_command"],
                "updated_at": _utc_now(),
            },
            run_type="historical_basis_universe_availability",
        )
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Bounded public availability builder for historical basis universe")
    parser.add_argument("--pit-state", required=True)
    parser.add_argument("--coin-registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=600)
    parser.add_argument("--active-run-gate")
    parser.add_argument("--run-id")
    parser.add_argument("--code-snapshot-hash")
    parser.add_argument("--code-snapshot-manifest")
    args = parser.parse_args()
    result = build_basis_universe_availability(
        args.pit_state,
        args.coin_registry,
        args.output,
        max_runtime_sec=args.max_runtime_sec,
        request_interval_sec=0.05,
        active_gate_path=args.active_run_gate,
        run_id=args.run_id,
        code_snapshot_hash=args.code_snapshot_hash,
        code_snapshot_manifest=args.code_snapshot_manifest,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
