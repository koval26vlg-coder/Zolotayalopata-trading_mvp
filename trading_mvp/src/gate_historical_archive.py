from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ARCHIVE_BASE_URL = "https://download.gatedata.org"
ARCHIVE_BIZ = "futures_usdt"
SPOT_ARCHIVE_BIZ = "spot"
ARCHIVE_TYPES = frozenset(
    {
        "candlesticks_1m",
        "candlesticks_1h",
        "mark_prices",
        "funding_applies",
        "funding_updates",
    }
)
SPOT_ARCHIVE_TYPES = frozenset({"candlesticks_1m", "candlesticks_1h"})
RECOVERY_SCHEMA = "trading_mvp_gate_archive_recovery_preflight_v1"
UNIVERSE_SCHEMA = "trading_mvp_historical_basis_universe_availability_v1"
CLOSURE_SCHEMA = "trading_mvp_historical_basis_retention_closure_v1"
HYPOTHESIS_ID = "cross_venue_perp_basis_convergence_history_v1"
REQUIRED_SERIES = ("trade", "mark", "index")
MINIMUM_ASSETS = 8
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+_[A-Z0-9]+$")
_MONTH_PATTERN = re.compile(r"^\d{6}$")


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


def _finite_float(value: str, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"invalid {field}: {value!r}")
    return result


def _fields(line: str, expected: int) -> list[str]:
    values = [value.strip() for value in str(line).strip().split(",")]
    if len(values) != expected or any(value == "" for value in values):
        raise ValueError(f"expected {expected} non-empty CSV fields")
    return values


def _integer_timestamp(value: str) -> int:
    timestamp = _finite_float(value, field="timestamp")
    if timestamp < 0 or not timestamp.is_integer():
        raise ValueError(f"invalid integer timestamp: {value!r}")
    return int(timestamp)


def build_gate_archive_url(archive_type: str, symbol: str, year_month: str) -> str:
    normalized_type = str(archive_type).strip()
    normalized_symbol = str(symbol).strip().upper()
    normalized_month = str(year_month).strip()
    if normalized_type not in ARCHIVE_TYPES:
        raise ValueError(f"unsupported archive type: {normalized_type}")
    if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
        raise ValueError(f"invalid Gate futures symbol: {symbol!r}")
    if not _MONTH_PATTERN.fullmatch(normalized_month):
        raise ValueError(f"invalid archive month: {year_month!r}")
    return (
        f"{ARCHIVE_BASE_URL}/{ARCHIVE_BIZ}/{normalized_type}/{normalized_month}/"
        f"{normalized_symbol}-{normalized_month}.csv.gz"
    )


def build_gate_spot_archive_url(archive_type: str, symbol: str, year_month: str) -> str:
    normalized_type = str(archive_type).strip()
    normalized_symbol = str(symbol).strip().upper()
    normalized_month = str(year_month).strip()
    if normalized_type not in SPOT_ARCHIVE_TYPES:
        raise ValueError(f"unsupported spot archive type: {normalized_type}")
    if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
        raise ValueError(f"invalid Gate spot symbol: {symbol!r}")
    if not _MONTH_PATTERN.fullmatch(normalized_month):
        raise ValueError(f"invalid archive month: {year_month!r}")
    return (
        f"{ARCHIVE_BASE_URL}/{SPOT_ARCHIVE_BIZ}/{normalized_type}/{normalized_month}/"
        f"{normalized_symbol}-{normalized_month}.csv.gz"
    )


def month_keys_for_range(start_sec: int, end_sec: int) -> list[str]:
    start = int(start_sec)
    end = int(end_sec)
    if start < 0 or end <= start:
        raise ValueError("archive range must be positive and half-open")
    first = datetime.fromtimestamp(start, timezone.utc)
    last = datetime.fromtimestamp(end - 1, timezone.utc)
    year, month = first.year, first.month
    result: list[str] = []
    while (year, month) <= (last.year, last.month):
        result.append(f"{year:04d}{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return result


def parse_gate_archive_candlestick(line: str) -> dict[str, float]:
    raw_ts, raw_volume, raw_close, raw_high, raw_low, raw_open = _fields(line, 6)
    timestamp = _integer_timestamp(raw_ts)
    volume = _finite_float(raw_volume, field="volume_contracts")
    close = _finite_float(raw_close, field="close")
    high = _finite_float(raw_high, field="high")
    low = _finite_float(raw_low, field="low")
    open_price = _finite_float(raw_open, field="open")
    if volume < 0:
        raise ValueError("volume_contracts must be non-negative")
    if min(open_price, high, low, close) <= 0:
        raise ValueError("archive candle prices must be positive")
    if high < max(open_price, close, low) or low > min(open_price, close, high):
        raise ValueError("invalid archive candle OHLC")
    return {
        "ts": float(timestamp),
        "volume_contracts": volume,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
    }


def parse_gate_archive_mark_price(line: str) -> dict[str, float]:
    raw_ts, raw_index, raw_mark, raw_last = _fields(line, 4)
    timestamp = _finite_float(raw_ts, field="timestamp")
    index_price = _finite_float(raw_index, field="index_price")
    mark_price = _finite_float(raw_mark, field="mark_price")
    last_price = _finite_float(raw_last, field="last_price")
    if timestamp < 0 or min(index_price, mark_price, last_price) <= 0:
        raise ValueError("archive mark-price row must contain positive values")
    return {
        "ts": timestamp,
        "index_price": index_price,
        "mark_price": mark_price,
        "last_price": last_price,
    }


def parse_gate_archive_funding_apply(line: str) -> dict[str, float]:
    raw_ts, raw_rate = _fields(line, 2)
    timestamp = _finite_float(raw_ts, field="timestamp")
    rate = _finite_float(raw_rate, field="funding_rate")
    if timestamp < 0:
        raise ValueError("funding timestamp must be non-negative")
    return {"ts": timestamp, "funding_rate": rate}


def _new_ohlc(timestamp: int, value: float) -> dict[str, float]:
    return {
        "ts": float(timestamp),
        "open": value,
        "high": value,
        "low": value,
        "close": value,
        "volume_base": 0.0,
        "volume_quote": 0.0,
    }


def _update_ohlc(row: dict[str, float], value: float) -> None:
    row["high"] = max(row["high"], value)
    row["low"] = min(row["low"], value)
    row["close"] = value


def aggregate_gate_archive_mark_prices(
    rows: Iterable[Mapping[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    interval_sec: int = 300,
) -> dict[str, list[dict[str, float]]]:
    start = int(start_sec)
    end = int(end_sec)
    interval = int(interval_sec)
    if interval <= 0 or start < 0 or end <= start:
        raise ValueError("invalid aggregation range")
    if start % interval or end % interval:
        raise ValueError("aggregation range must be interval-aligned")
    buckets: dict[str, dict[int, dict[str, float]]] = {"index": {}, "mark": {}}
    previous_timestamp: float | None = None
    for raw in rows:
        try:
            timestamp = float(raw["ts"])
            index_price = float(raw["index_price"])
            mark_price = float(raw["mark_price"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid mark-price row") from exc
        if not all(math.isfinite(value) for value in (timestamp, index_price, mark_price)):
            raise ValueError("non-finite mark-price row")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError("mark-price timestamps must be strictly increasing")
        previous_timestamp = timestamp
        if not start <= timestamp < end:
            continue
        if min(index_price, mark_price) <= 0:
            raise ValueError("mark and index prices must be positive")
        bucket = int(timestamp // interval) * interval
        for series, value in (("index", index_price), ("mark", mark_price)):
            output = buckets[series]
            if bucket not in output:
                output[bucket] = _new_ohlc(bucket, value)
            else:
                _update_ohlc(output[bucket], value)
    return {
        series: [values[timestamp] for timestamp in sorted(values)]
        for series, values in buckets.items()
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _validate_universe_artifact(
    universe_path: Path,
    closure: Mapping[str, Any],
) -> dict[str, Any]:
    source = closure.get("original_artifact")
    if not isinstance(source, Mapping):
        raise ValueError("closure original_artifact is missing")
    expected_path = Path(str(source.get("path") or "")).expanduser().resolve()
    if expected_path != universe_path:
        raise ValueError("closure source path mismatch")
    expected_file_hash = str(source.get("file_sha256") or "")
    if not expected_file_hash or sha256_file(universe_path) != expected_file_hash:
        raise ValueError("source artifact hash mismatch")
    universe = _read_json(universe_path)
    if universe.get("schema") != UNIVERSE_SCHEMA or universe.get("final") is not True:
        raise ValueError("unexpected historical-basis universe artifact")
    expected_semantic_hash = sha256_json(
        {
            key: value
            for key, value in universe.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
        }
    )
    if universe.get("artifact_hash") != expected_semantic_hash:
        raise ValueError("source artifact semantic hash mismatch")
    if source.get("internal_artifact_hash") != expected_semantic_hash:
        raise ValueError("closure source semantic hash mismatch")
    return universe


def _mexc_history_upper_bound(universe: Mapping[str, Any]) -> list[dict[str, Any]]:
    history = universe.get("history_probe")
    if not isinstance(history, Mapping):
        raise ValueError("universe history_probe is missing")
    if int(history.get("history_days") or 0) != 220:
        raise ValueError("unexpected frozen history horizon")
    if tuple(history.get("required_series") or ()) != REQUIRED_SERIES:
        raise ValueError("unexpected frozen candle series")
    statuses = history.get("statuses")
    if not isinstance(statuses, list):
        raise ValueError("universe history statuses are missing")
    by_asset: dict[str, dict[str, Any]] = {}
    for status in statuses:
        if not isinstance(status, Mapping):
            raise ValueError("invalid universe history status")
        canonical_id = str(status.get("canonical_asset_id") or "")
        base = str(status.get("base") or "").upper()
        venue = str(status.get("venue") or "")
        series = str(status.get("series") or "")
        if not canonical_id or not base or venue not in {"mexc", "gateio"}:
            raise ValueError("invalid universe history identity")
        if series not in REQUIRED_SERIES:
            raise ValueError("invalid universe history series")
        asset = by_asset.setdefault(
            canonical_id,
            {
                "canonical_asset_id": canonical_id,
                "base": base,
                "mexc": {},
                "gateio": {},
            },
        )
        if asset["base"] != base:
            raise ValueError("canonical asset base collision")
        venue_rows = asset[venue]
        if series in venue_rows:
            raise ValueError("duplicate universe history status")
        venue_rows[series] = str(status.get("status") or "")
    candidates: list[dict[str, Any]] = []
    for canonical_id in sorted(by_asset):
        asset = by_asset[canonical_id]
        mexc = asset["mexc"]
        mexc_complete = (
            set(mexc) == set(REQUIRED_SERIES)
            and all(mexc[series] == "available" for series in REQUIRED_SERIES)
        )
        candidates.append(
            {
                "canonical_asset_id": canonical_id,
                "base": asset["base"],
                "mexc_all_required_series_available": mexc_complete,
                "mexc_series_status": {series: mexc.get(series) for series in REQUIRED_SERIES},
                "gateio_series_status": {
                    series: asset["gateio"].get(series) for series in REQUIRED_SERIES
                },
            }
        )
    return candidates


def build_archive_recovery_preflight(
    universe_artifact_path: str | Path,
    closure_report_path: str | Path,
    *,
    minimum_assets: int = MINIMUM_ASSETS,
) -> dict[str, Any]:
    minimum = int(minimum_assets)
    if minimum < 1:
        raise ValueError("minimum_assets must be positive")
    universe_path = Path(universe_artifact_path).expanduser().resolve()
    closure_path = Path(closure_report_path).expanduser().resolve()
    closure = _read_json(closure_path)
    if closure.get("schema") != CLOSURE_SCHEMA or closure.get("final") is not True:
        raise ValueError("unexpected historical-basis closure report")
    if closure.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("unexpected historical-basis hypothesis")
    if closure.get("edge_evaluated") is not False or closure.get("pnl_read") is not False:
        raise ValueError("closure outcome embargo mismatch")
    frozen = closure.get("frozen_contract")
    if not isinstance(frozen, Mapping):
        raise ValueError("closure frozen contract is missing")
    if (
        frozen.get("interval") != "5m"
        or int(frozen.get("required_history_days") or 0) != 220
        or frozen.get("strategy_change_allowed") is not False
    ):
        raise ValueError("unexpected frozen historical-basis contract")
    universe = _validate_universe_artifact(universe_path, closure)
    candidates = _mexc_history_upper_bound(universe)
    survivors = [
        row for row in candidates if row["mexc_all_required_series_available"] is True
    ]
    count = len(survivors)
    if count < minimum:
        verdict = "INSUFFICIENT_EXECUTABLE_UNIVERSE"
        reason = "MEXC_HISTORY_UPPER_BOUND_LT_MINIMUM_BEFORE_GATE_ARCHIVE"
        next_command = "none_archive_collect_forbidden"
        collect_allowed = False
    else:
        verdict = "ARCHIVE_SOURCE_AMENDMENT_PLANONLY_REQUIRED"
        reason = "GATE_ARCHIVE_CAN_BE_PROBED_WITHOUT_CHANGING_FROZEN_STRATEGY"
        next_command = "fast-edge-basis-gate-archive-source-planonly"
        collect_allowed = False
    result: dict[str, Any] = {
        "schema": RECOVERY_SCHEMA,
        "generated_at_utc": _utc_now(),
        "hypothesis_id": HYPOTHESIS_ID,
        "final": True,
        "verdict": verdict,
        "reason_code": reason,
        "minimum_required_assets": minimum,
        "probed_candidate_count": len(candidates),
        "mexc_history_upper_bound_assets": count,
        "mexc_history_upper_bound_candidates": survivors,
        "candidate_audit": candidates,
        "gate_archive": {
            "base_url": ARCHIVE_BASE_URL,
            "business": ARCHIVE_BIZ,
            "required_types_for_future_source_amendment": [
                "candlesticks_1m",
                "mark_prices",
                "funding_applies",
            ],
            "network_probe_performed": False,
            "bulk_collect_performed": False,
        },
        "network_requests": 0,
        "archive_collect_allowed": collect_allowed,
        "source_provenance": {
            "universe_artifact_path": str(universe_path),
            "universe_artifact_sha256": sha256_file(universe_path),
            "universe_artifact_hash": universe["artifact_hash"],
            "closure_report_path": str(closure_path),
            "closure_report_sha256": sha256_file(closure_path),
        },
        "frozen_contract": dict(frozen),
        "data_access_audit": {
            "returns_read": False,
            "oos_read": False,
            "signals_read": False,
            "pnl_computed": False,
        },
        "safety": {
            "research_only": True,
            "public_data_only": True,
            "grid_search": False,
            "retune": False,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
        },
        "next_allowed_command": next_command,
    }
    result["artifact_hash"] = sha256_json(
        {key: value for key, value in result.items() if key not in {"generated_at_utc", "artifact_hash"}}
    )
    return result


def write_archive_recovery_preflight(
    universe_artifact_path: str | Path,
    closure_report_path: str | Path,
    output_path: str | Path,
    *,
    minimum_assets: int = MINIMUM_ASSETS,
) -> dict[str, Any]:
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    result = build_archive_recovery_preflight(
        universe_artifact_path,
        closure_report_path,
        minimum_assets=minimum_assets,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    result["output_path"] = str(target)
    result["output_file_sha256"] = sha256_file(target)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-fast PlanOnly preflight for Gate historical archive recovery"
    )
    parser.add_argument("--universe-artifact", required=True)
    parser.add_argument("--closure-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--minimum-assets", type=int, default=MINIMUM_ASSETS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = write_archive_recovery_preflight(
        args.universe_artifact,
        args.closure_report,
        args.output,
        minimum_assets=args.minimum_assets,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
