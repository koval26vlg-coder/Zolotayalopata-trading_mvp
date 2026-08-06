from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence


SCHEMA = "trading_mvp_historical_basis_v2_preflight_v2"
HYPOTHESIS_ID = "cross_venue_perp_basis_convergence_1h_v2"
HOUR_SEC = 3_600
DAY_SEC = 86_400
WINDOW_DAYS = 179
EXPECTED_CANDLE_ROWS = WINDOW_DAYS * 24
MIN_CANDIDATES = 8
MAX_CANDIDATES = 20
SERIES = ("trade", "mark", "index")
VENUES = ("mexc", "gateio")
MAX_PREFLIGHT_RUNTIME_SEC = 1_800
MAX_COLLECTOR_RUNTIME_SEC = 5_400
MAX_PAGE_BARS = 2_000


class BoundaryClient(Protocol):
    public_only: bool

    def fetch_1h_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_iso(ts: int | float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _as_timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str) and not value.strip().replace(".", "", 1).isdigit():
            normalized = value.strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            result = parsed.timestamp()
        else:
            result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def derive_frozen_window(cutoff_seconds: Sequence[int | float]) -> dict[str, Any]:
    """Freeze the latest hour closed in every immutable source."""
    if not cutoff_seconds:
        raise ValueError("at least one funding-cache cutoff is required")
    cutoffs = []
    for raw in cutoff_seconds:
        value = _as_timestamp(raw)
        if value is None or value <= WINDOW_DAYS * DAY_SEC:
            raise ValueError(f"invalid funding-cache cutoff: {raw!r}")
        cutoffs.append(int(value))
    common_cutoff = min(cutoffs)
    end_sec = (common_cutoff // HOUR_SEC) * HOUR_SEC
    start_sec = end_sec - WINDOW_DAYS * DAY_SEC
    if start_sec < 0:
        raise ValueError("funding-cache cutoff cannot cover 179 days")
    return {
        "interval": "[start,end)",
        "interval_name": "1h",
        "bar_timestamp_semantics": "bar_open",
        "signal_available": "after_bar_close",
        "window_days": WINDOW_DAYS,
        "window_start_sec": start_sec,
        "window_end_sec": end_sec,
        "window_start_utc": _utc_iso(start_sec),
        "window_end_utc": _utc_iso(end_sec),
        "funding_cache_common_cutoff_sec": common_cutoff,
        "funding_cache_common_cutoff_utc": _utc_iso(common_cutoff),
        "expected_candle_rows": EXPECTED_CANDLE_ROWS,
    }


def _run_lengths(values: Sequence[int]) -> list[tuple[int, int, int]]:
    if not values:
        return []
    runs: list[tuple[int, int, int]] = []
    start = 0
    for index in range(1, len(values) + 1):
        if index == len(values) or values[index] != values[start]:
            runs.append((start, index, values[start]))
            start = index
    return runs


def _infer_interval_cadences(
    deltas: Sequence[float],
    *,
    jitter_tolerance_sec: int,
) -> tuple[list[int], list[float], int]:
    quantized: list[int] = []
    residuals: list[float] = []
    anomaly_count = 0
    allowed_residual = max(1.0, 2.0 * float(jitter_tolerance_sec))
    for delta in deltas:
        hours = max(1, int(round(delta / HOUR_SEC)))
        cadence = hours * HOUR_SEC
        residual = abs(delta - cadence)
        if hours > 24 or residual > allowed_residual:
            quantized.append(0)
            residuals.append(residual)
            anomaly_count += 1
        else:
            quantized.append(cadence)
            residuals.append(residual)

    valid = [value for value in quantized if value > 0]
    if not valid:
        return quantized, residuals, anomaly_count
    counts = Counter(valid)
    global_mode = min(counts, key=lambda value: (-counts[value], value))
    assigned = list(quantized)
    runs = _run_lengths(assigned)
    for run_index, (start, end, cadence) in enumerate(runs):
        if cadence <= 0:
            continue
        length = end - start
        previous = runs[run_index - 1][2] if run_index else 0
        following = runs[run_index + 1][2] if run_index + 1 < len(runs) else 0
        if length == 1 and previous > 0 and previous == following and cadence % previous == 0:
            assigned[start] = previous
        elif length == 1 and cadence > global_mode and cadence % global_mode == 0:
            assigned[start] = global_mode
    return assigned, residuals, anomaly_count


def _cadence_schedule(
    timestamps: Sequence[float],
    interval_cadences: Sequence[int],
) -> list[dict[str, Any]]:
    if len(timestamps) < 2 or not interval_cadences:
        return []
    schedule: list[dict[str, Any]] = []
    for start, end, cadence in _run_lengths(interval_cadences):
        if cadence <= 0:
            continue
        schedule.append(
            {
                "start_ts": timestamps[start],
                "start_utc": _utc_iso(timestamps[start]),
                "last_observed_ts": timestamps[end],
                "last_observed_utc": _utc_iso(timestamps[end]),
                "cadence_sec": cadence,
                "observed_intervals": end - start,
            }
        )
    return schedule


def audit_funding_events(
    rows: Sequence[dict[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    minimum_coverage: float = 0.98,
    jitter_tolerance_sec: int = 300,
) -> dict[str, Any]:
    """Audit exact events while inferring a piecewise observed cadence schedule."""
    if end_sec <= start_sec:
        raise ValueError("funding audit requires a non-empty half-open range")
    parsed: list[tuple[float, float]] = []
    invalid_count = 0
    out_of_window_count = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid_count += 1
            continue
        ts = _as_timestamp(row.get("ts"))
        try:
            rate = float(row["funding_rate"])
        except (KeyError, TypeError, ValueError, OverflowError):
            rate = math.nan
        if ts is None or not math.isfinite(rate):
            invalid_count += 1
            continue
        if not start_sec <= ts < end_sec:
            out_of_window_count += 1
            continue
        parsed.append((ts, rate))

    parsed.sort(key=lambda item: item[0])
    timestamp_counts = Counter(ts for ts, _ in parsed)
    duplicate_count = sum(count - 1 for count in timestamp_counts.values() if count > 1)
    unique_events: list[tuple[float, float]] = []
    seen: set[float] = set()
    for event in parsed:
        if event[0] not in seen:
            unique_events.append(event)
            seen.add(event[0])
    timestamps = [event[0] for event in unique_events]
    deltas = [right - left for left, right in zip(timestamps, timestamps[1:])]
    cadences, residuals, anomaly_count = _infer_interval_cadences(
        deltas,
        jitter_tolerance_sec=jitter_tolerance_sec,
    )
    schedule = _cadence_schedule(timestamps, cadences)

    missing_count = 0
    gap_count = 0
    allowed_residual = max(1.0, 2.0 * float(jitter_tolerance_sec))
    for delta, cadence in zip(deltas, cadences):
        if cadence <= 0:
            gap_count += 1
            continue
        multiples = max(1, int(round(delta / cadence)))
        if abs(delta - multiples * cadence) > allowed_residual:
            anomaly_count += 1
            gap_count += 1
            continue
        if multiples > 1:
            missing_count += multiples - 1
            gap_count += 1

    valid_cadences = [value for value in cadences if value > 0]
    if timestamps and valid_cadences:
        first_cadence = valid_cadences[0]
        last_cadence = valid_cadences[-1]
        prefix_distance = timestamps[0] - start_sec
        suffix_distance = end_sec - timestamps[-1]
        prefix_missing = max(0, math.ceil(max(0.0, prefix_distance) / first_cadence) - 1)
        suffix_missing = max(0, math.ceil(max(0.0, suffix_distance) / last_cadence) - 1)
        missing_count += prefix_missing + suffix_missing
        gap_count += int(prefix_missing > 0) + int(suffix_missing > 0)

    expected = len(unique_events) + missing_count
    coverage = len(unique_events) / expected if expected else 0.0
    rates = [event[1] for event in unique_events]
    accepted = (
        len(unique_events) >= 2
        and coverage >= float(minimum_coverage)
        and duplicate_count == 0
        and invalid_count == 0
        and anomaly_count == 0
        and bool(schedule)
    )
    normalized_timestamps: list[int | float] = [
        int(value) if float(value).is_integer() else value for value in timestamps
    ]
    return {
        "source_rows": len(rows),
        "in_window_rows": len(parsed),
        "unique_settlement_count": len(unique_events),
        "expected_settlement_count": expected,
        "coverage": coverage,
        "minimum_coverage": float(minimum_coverage),
        "duplicate_count": duplicate_count,
        "missing_settlement_count": missing_count,
        "gap_count": gap_count,
        "invalid_event_count": invalid_count,
        "out_of_window_count": out_of_window_count,
        "cadence_schedule": schedule,
        "cadence_change_count": max(0, len(schedule) - 1),
        "jitter_tolerance_sec": int(jitter_tolerance_sec),
        "maximum_observed_jitter_sec": max(residuals, default=0.0),
        "cadence_anomaly_count": anomaly_count,
        "positive_rate_count": sum(rate > 0 for rate in rates),
        "negative_rate_count": sum(rate < 0 for rate in rates),
        "zero_rate_count": sum(rate == 0 for rate in rates),
        "first_settlement_ts": normalized_timestamps[0] if normalized_timestamps else None,
        "last_settlement_ts": normalized_timestamps[-1] if normalized_timestamps else None,
        "exact_settlement_timestamps": normalized_timestamps,
        "event_rows_sha256": sha256_json(
            [
                {"ts": normalized_timestamps[index], "funding_rate": event[1]}
                for index, event in enumerate(unique_events)
            ]
        ),
        "accepted": accepted,
    }


def classify_excluded_categories(name: str, symbol: str, coin_id: str) -> list[str]:
    text = " ".join((name, symbol, coin_id)).lower().replace("-", " ").replace("_", " ")
    compact = symbol.strip().upper()
    categories: set[str] = set()
    if compact in {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USD1"} or "stablecoin" in text:
        categories.add("stable")
    if any(term in text for term in ("wrapped", "bridged", "wormhole")):
        categories.add("wrapped")
    if any(term in text for term in ("staked", "liquid staking", "restaked")):
        categories.add("staked")
    if any(term in text for term in ("leveraged", "3x long", "3x short")) or compact.endswith(("3L", "3S", "BULL", "BEAR")):
        categories.add("leveraged")
    if any(term in text for term in (" lp token", "liquidity pool", "liquidity provider")):
        categories.add("lp")
    if any(term in text for term in ("synthetic", "synth ")):
        categories.add("synthetic")
    if any(term in text for term in ("pre market", "premarket")):
        categories.add("pre-market")
    if any(term in text for term in ("tokenized stock", "stock token", "tokenized etf", "tokenized commodity", "equity token")):
        categories.add("tokenized")
    if "STOCK" in compact or "ETF" in compact:
        categories.add("tokenized")
    if " index" in f" {text}" or text.endswith(" index"):
        categories.add("index")
    return sorted(categories)


def _load_registry(path: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    by_symbol: dict[str, list[dict[str, str]]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "").strip().upper()
            coin_id = str(row.get("coin_id") or "").strip()
            if symbol and coin_id:
                by_symbol.setdefault(symbol, []).append(dict(row))
    collisions = {
        symbol
        for symbol, rows in by_symbol.items()
        if len({str(row.get("coin_id") or "").strip() for row in rows}) != 1
    }
    unique = {symbol: rows[0] for symbol, rows in by_symbol.items() if symbol not in collisions}
    return unique, collisions


def _load_pit_rows(path: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "pit_universe_state_v1" or not isinstance(payload.get("symbols"), dict):
        raise ValueError("expected pit_universe_state_v1")
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in payload["symbols"].values():
        row = item.get("row") if isinstance(item, dict) else None
        if not isinstance(row, dict):
            continue
        venue = str(row.get("exchange") or "").strip().lower()
        base = str(row.get("base") or "").strip().upper()
        if venue in VENUES and base:
            grouped.setdefault(base, {}).setdefault(venue, []).append(row)
    return grouped


def _first_timestamp(row: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = _as_timestamp(row.get(key))
        if value is not None:
            return value
    return None


def _identity_candidates(
    pit_rows: dict[str, dict[str, list[dict[str, Any]]]],
    registry: dict[str, dict[str, str]],
    collisions: set[str],
    *,
    window_start_sec: int,
    window_end_sec: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for base in sorted(pit_rows):
        venues = pit_rows[base]
        if set(venues) != set(VENUES):
            rejected["not_dual_venue"] += 1
            continue
        if any(len(venues[venue]) != 1 for venue in VENUES):
            rejected["venue_symbol_collision"] += 1
            continue
        if base in collisions or base not in registry:
            rejected["identity_collision" if base in collisions else "identity_unmatched"] += 1
            continue
        rows = {venue: venues[venue][0] for venue in VENUES}
        if any(
            str(row.get("quote") or "").upper() != "USDT"
            or str(row.get("contract_type") or "").lower() != "linear_perp"
            or str(row.get("status") or "").lower() != "trading"
            or row.get("listed_now") is not True
            or row.get("tombstone") is True
            or row.get("inactive_or_delisted") is True
            for row in rows.values()
        ):
            rejected["lifecycle"] += 1
            continue
        if any(
            row.get("eligible_non_binance_spot") is not True
            or row.get("binance_spot_listed") is not False
            for row in rows.values()
        ):
            rejected["binance_spot_or_unverified"] += 1
            continue
        identity = registry[base]
        categories = classify_excluded_categories(
            str(identity.get("name") or ""),
            base,
            str(identity.get("coin_id") or ""),
        )
        if categories:
            rejected["excluded_category"] += 1
            continue
        starts = [
            value
            for value in (
                _first_timestamp(rows[venue], ("listed_at_ts", "listing_ts", "launch_ts"))
                for venue in VENUES
            )
            if value is not None
        ]
        ends = [
            value
            for value in (
                _first_timestamp(rows[venue], ("delisted_at_ts", "delist_ts", "inactive_at_ts"))
                for venue in VENUES
            )
            if value is not None
        ]
        lifecycle_start = max(starts, default=float(window_start_sec))
        lifecycle_end = min(ends, default=float(window_end_sec))
        if lifecycle_start > window_start_sec or lifecycle_end < window_end_sec:
            rejected["lifecycle_window"] += 1
            continue
        candidates.append(
            {
                "canonical_asset_id": f"coingecko:{identity['coin_id']}",
                "base": base,
                "quote": "USDT",
                "mexc_symbol": str(rows["mexc"]["symbol"]),
                "gateio_symbol": str(rows["gateio"]["symbol"]),
                "binance_spot": False,
                "categories": [],
                "identity_name": identity.get("name"),
                "identity_source": "coingecko_coin_id_unique_symbol_join",
                "lifecycle": {
                    "active_from_sec": lifecycle_start,
                    "active_until_sec": lifecycle_end,
                    "mask_interval": "[active_from,active_until)",
                    "covers_frozen_window": True,
                },
            }
        )
    candidates.sort(key=lambda row: row["canonical_asset_id"])
    return candidates, rejected


def _load_daily_manifest(path: Path) -> tuple[dict[str, Any], int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "daily_collect_v1":
        raise ValueError("daily cache manifest must use daily_collect_v1")
    params = payload.get("params")
    if not isinstance(params, dict):
        raise ValueError("daily cache manifest params are required")
    cutoff = _as_timestamp(params.get("end_sec"))
    if cutoff is None:
        raise ValueError("daily cache manifest params.end_sec is required")
    return payload, int(cutoff)


def _load_funding_file(path: Path, *, venue: str, symbol: str) -> tuple[list[dict[str, Any]], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("exchange") != venue or payload.get("symbol") != symbol:
        raise ValueError(f"funding cache metadata mismatch: {path}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"funding cache rows missing: {path}")
    return rows, sha256_file(path)


def _probe_row_is_valid(
    rows: Sequence[dict[str, Any]],
    *,
    expected_start_sec: int,
    expected_end_sec: int,
) -> bool:
    matching = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _as_timestamp(row.get("ts"))
        if ts is None or not expected_start_sec <= ts < expected_end_sec:
            continue
        if ts != expected_start_sec or ts % HOUR_SEC != 0:
            continue
        try:
            prices = [float(row[key]) for key in ("open", "high", "low", "close")]
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if all(math.isfinite(value) and value > 0 for value in prices):
            matching.append(row)
    return len(matching) == 1


def _probe_boundaries(
    candidates: Sequence[dict[str, Any]],
    clients: dict[str, BoundaryClient],
    *,
    window_start_sec: int,
    window_end_sec: int,
    deadline: float,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    boundaries = (
        ("oldest", window_start_sec, window_start_sec + HOUR_SEC),
        ("newest", window_end_sec - HOUR_SEC, window_end_sec),
    )
    total = len(candidates) * len(VENUES) * len(SERIES) * len(boundaries)
    completed = 0
    started = time.monotonic()
    for candidate in candidates:
        for venue in VENUES:
            client = clients[venue]
            if getattr(client, "public_only", None) is not True:
                raise ValueError(f"{venue} boundary client is not declared public-only")
            symbol = str(candidate[f"{venue}_symbol"])
            for series in SERIES:
                for boundary, start_sec, end_sec in boundaries:
                    completed += 1
                    status = "available"
                    error = None
                    rows_count = 0
                    if time.monotonic() >= deadline:
                        status = "timeout"
                        error = "MaxRuntimeSec exceeded"
                    else:
                        try:
                            rows = client.fetch_1h_series(symbol, series, start_sec, end_sec)
                            rows_count = len(rows)
                            if not _probe_row_is_valid(
                                rows,
                                expected_start_sec=start_sec,
                                expected_end_sec=end_sec,
                            ):
                                status = "invalid_or_missing"
                        except Exception as exc:  # noqa: BLE001
                            status = "error"
                            error = f"{type(exc).__name__}: {exc}"
                    statuses.append(
                        {
                            "canonical_asset_id": candidate["canonical_asset_id"],
                            "base": candidate["base"],
                            "venue": venue,
                            "symbol": symbol,
                            "series": series,
                            "boundary": boundary,
                            "request_start_sec": start_sec,
                            "request_end_sec": end_sec,
                            "status": status,
                            "rows": rows_count,
                            "error": error,
                            "public_only": True,
                        }
                    )
                    elapsed = max(0.001, time.monotonic() - started)
                    eta = (total - completed) / (completed / elapsed)
                    print(
                        f"[basis-v2-preflight] {completed}/{total} {candidate['base']} "
                        f"{venue} {series} {boundary} status={status} eta_sec={eta:.1f}",
                        flush=True,
                    )
    return statuses


def _request_estimate(candidate_count: int, latency_sec: float) -> dict[str, Any]:
    pages_per_series = math.ceil(EXPECTED_CANDLE_ROWS / MAX_PAGE_BARS)
    boundary_requests = candidate_count * len(VENUES) * len(SERIES) * 2
    collector_requests = candidate_count * len(VENUES) * len(SERIES) * pages_per_series
    total = boundary_requests + collector_requests
    worst_case = math.ceil(total * max(0.01, float(latency_sec)) * 1.25)
    return {
        "candidate_count": candidate_count,
        "boundary_probe_requests": boundary_requests,
        "collector_pages_per_series": pages_per_series,
        "estimated_collector_requests": collector_requests,
        "estimated_total_public_requests": total,
        "estimated_request_latency_sec": float(latency_sec),
        "worst_case_runtime_sec": worst_case,
        "maximum_allowed_runtime_sec": MAX_COLLECTOR_RUNTIME_SEC,
        "within_90_minutes": worst_case <= MAX_COLLECTOR_RUNTIME_SEC,
    }


def _merkle_root(leaves: Sequence[str]) -> str:
    if not leaves:
        return hashlib.sha256(b"").hexdigest()
    level = [bytes.fromhex(leaf) for leaf in leaves]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


def run_historical_basis_v2_preflight(
    pit_state_path: str | Path,
    coin_registry_path: str | Path,
    daily_cache_manifest_path: str | Path,
    output_path: str | Path,
    *,
    clients: dict[str, BoundaryClient] | None = None,
    max_runtime_sec: int = MAX_PREFLIGHT_RUNTIME_SEC,
    estimated_request_latency_sec: float = 1.0,
    minimum_funding_coverage: float = 0.98,
    funding_jitter_tolerance_sec: int = 300,
    max_candidates: int = MAX_CANDIDATES,
) -> dict[str, Any]:
    if not 0 < int(max_runtime_sec) <= MAX_PREFLIGHT_RUNTIME_SEC:
        raise ValueError("preflight max_runtime_sec must be in [1, 1800]")
    if not MIN_CANDIDATES <= int(max_candidates) <= MAX_CANDIDATES:
        raise ValueError("max_candidates must be in [8, 20]")
    started = time.monotonic()
    deadline = started + int(max_runtime_sec)
    pit_path = Path(pit_state_path).expanduser().resolve()
    registry_path = Path(coin_registry_path).expanduser().resolve()
    manifest_path = Path(daily_cache_manifest_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    daily_manifest, cutoff_sec = _load_daily_manifest(manifest_path)
    window = derive_frozen_window([cutoff_sec])
    registry, collisions = _load_registry(registry_path)
    identity_candidates, rejections = _identity_candidates(
        _load_pit_rows(pit_path),
        registry,
        collisions,
        window_start_sec=window["window_start_sec"],
        window_end_sec=window["window_end_sec"],
    )
    cache_root = manifest_path.parent
    funding_reports: list[dict[str, Any]] = []
    funding_eligible: list[dict[str, Any]] = []
    funding_merkle_leaves: list[str] = []
    for candidate in identity_candidates:
        references: dict[str, Any] = {}
        candidate_ok = True
        for venue in VENUES:
            symbol = str(candidate[f"{venue}_symbol"])
            path = (cache_root / venue / "funding" / f"{symbol}.json").resolve()
            try:
                rows, file_hash = _load_funding_file(path, venue=venue, symbol=symbol)
                audit = audit_funding_events(
                    rows,
                    start_sec=window["window_start_sec"],
                    end_sec=window["window_end_sec"],
                    minimum_coverage=minimum_funding_coverage,
                    jitter_tolerance_sec=funding_jitter_tolerance_sec,
                )
                if not audit["accepted"]:
                    candidate_ok = False
                reference = {
                    "venue": venue,
                    "symbol": symbol,
                    "path": str(path),
                    "file_sha256": file_hash,
                    "source_manifest_path": str(manifest_path),
                    "source_manifest_sha256": sha256_file(manifest_path),
                    "audit": audit,
                }
                references[venue] = reference
                funding_reports.append(
                    {
                        "canonical_asset_id": candidate["canonical_asset_id"],
                        "base": candidate["base"],
                        **reference,
                    }
                )
                for index, row in enumerate(rows):
                    ts = _as_timestamp(row.get("ts")) if isinstance(row, dict) else None
                    if ts is None or not window["window_start_sec"] <= ts < window["window_end_sec"]:
                        continue
                    leaf = sha256_json(
                        {
                            "canonical_asset_id": candidate["canonical_asset_id"],
                            "venue": venue,
                            "symbol": symbol,
                            "source_row_index": index,
                            "ts": int(ts) if ts.is_integer() else ts,
                            "funding_rate": row.get("funding_rate"),
                        }
                    )
                    funding_merkle_leaves.append(leaf)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                candidate_ok = False
                rejections["funding_cache_invalid_or_missing"] += 1
                funding_reports.append(
                    {
                        "canonical_asset_id": candidate["canonical_asset_id"],
                        "base": candidate["base"],
                        "venue": venue,
                        "symbol": symbol,
                        "path": str(path),
                        "error": f"{type(exc).__name__}: {exc}",
                        "audit": {"accepted": False},
                    }
                )
        if candidate_ok and set(references) == set(VENUES):
            funding_eligible.append({**candidate, "funding_cache": references})
        else:
            rejections["funding_history"] += 1

    shortlist = funding_eligible[: int(max_candidates)]
    estimate = _request_estimate(len(shortlist), estimated_request_latency_sec)
    if clients is None:
        from historical_basis_v2_collector import (  # pylint: disable=import-outside-toplevel
            GateHistoricalBasisV2Client,
            MexcHistoricalBasisV2Client,
        )

        clients = {
            "mexc": MexcHistoricalBasisV2Client(),
            "gateio": GateHistoricalBasisV2Client(),
        }
    if set(clients) != set(VENUES):
        raise ValueError("preflight requires exactly mexc and gateio boundary clients")

    probes: list[dict[str, Any]] = []
    if len(shortlist) >= MIN_CANDIDATES and estimate["within_90_minutes"]:
        probes = _probe_boundaries(
            shortlist,
            clients,
            window_start_sec=window["window_start_sec"],
            window_end_sec=window["window_end_sec"],
            deadline=deadline,
        )
    probe_by_asset: dict[str, list[dict[str, Any]]] = {}
    for row in probes:
        probe_by_asset.setdefault(str(row["canonical_asset_id"]), []).append(row)
    expected_probes = len(VENUES) * len(SERIES) * 2
    final_candidates = [
        candidate
        for candidate in shortlist
        if len(probe_by_asset.get(str(candidate["canonical_asset_id"]), [])) == expected_probes
        and all(
            row["status"] == "available"
            for row in probe_by_asset[str(candidate["canonical_asset_id"])]
        )
    ]
    rejections["history_boundary_missing"] += len(shortlist) - len(final_candidates)

    if len(identity_candidates) < MIN_CANDIDATES:
        verdict = "INSUFFICIENT_EXECUTABLE_UNIVERSE"
        next_command = "none-branch-insufficient-universe"
    elif len(funding_eligible) < MIN_CANDIDATES:
        verdict = "INSUFFICIENT_FUNDING_HISTORY"
        next_command = "none-branch-insufficient-funding-history"
    elif not estimate["within_90_minutes"] or len(final_candidates) < MIN_CANDIDATES:
        verdict = "UNRESOLVED_DATA_CONTRACT"
        next_command = "none-resolve-v2-data-contract"
    else:
        verdict = "PREFLIGHT_ACCEPTED_NOT_COLLECTED"
        next_command = "fast-edge-basis-v2-plan"

    candidate_payload = []
    for candidate in final_candidates:
        clean = dict(candidate)
        clean["funding_cache"] = {
            venue: {
                key: value
                for key, value in candidate["funding_cache"][venue].items()
                if key != "audit"
            }
            for venue in VENUES
        }
        candidate_payload.append(clean)
    input_hashes = {
        "pit_state_sha256": sha256_file(pit_path),
        "coin_registry_sha256": sha256_file(registry_path),
        "daily_cache_manifest_sha256": sha256_file(manifest_path),
        "funding_files_merkle_sha256": _merkle_root(
            sorted(
                reference["file_sha256"]
                for candidate in final_candidates
                for reference in candidate["funding_cache"].values()
            )
        ),
        "funding_event_merkle_sha256": _merkle_root(sorted(funding_merkle_leaves)),
    }
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "hypothesis_id": HYPOTHESIS_ID,
        "generated_at_utc": _utc_now(),
        "final": True,
        "status": verdict,
        "verdict": verdict,
        "window": window,
        "daily_cache": {
            "manifest_path": str(manifest_path),
            "manifest_schema": daily_manifest.get("schema"),
            "manifest_run_id": daily_manifest.get("run_id"),
            "cache_root": str(cache_root),
            "manifest_cutoff_sec": cutoff_sec,
        },
        "universe": {
            "selection_basis": "identity_lifecycle_availability_only",
            "maximum_candidates": MAX_CANDIDATES,
            "minimum_candidates": MIN_CANDIDATES,
            "candidate_count": len(candidate_payload),
            "candidates": candidate_payload,
            "candidate_set_sha256": sha256_json(candidate_payload),
        },
        "funding_audits": funding_reports,
        "funding_event_merkle_sha256": input_hashes["funding_event_merkle_sha256"],
        "boundary_probes": probes,
        "boundary_probe_sha256": sha256_json(probes),
        "request_estimate": estimate,
        "rejections_by_reason": dict(sorted(rejections.items())),
        "input_hashes": input_hashes,
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_metrics_read": False,
            "liquidity_used_for_selection": False,
        },
        "runtime": {
            "duration_sec": round(time.monotonic() - started, 3),
            "max_runtime_sec": int(max_runtime_sec),
        },
        "next_allowed_command": next_command,
    }
    result["preflight_hash"] = sha256_json(result)
    _atomic_write_json(target, result)
    return result


# A descriptive alias keeps the Python API stable for plan builders.
build_historical_basis_v2_preflight = run_historical_basis_v2_preflight


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the historical-basis 1h v2 A0 preflight")
    parser.add_argument("--pit-state", required=True)
    parser.add_argument("--coin-registry", required=True)
    parser.add_argument("--daily-cache-manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_PREFLIGHT_RUNTIME_SEC)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        result = run_historical_basis_v2_preflight(
            args.pit_state,
            args.coin_registry,
            args.daily_cache_manifest,
            args.output,
            max_runtime_sec=args.max_runtime_sec,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "candidate_count": result["universe"]["candidate_count"],
                "output": str(Path(args.output).expanduser().resolve()),
                "preflight_hash": result["preflight_hash"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
