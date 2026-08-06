from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


@dataclass(frozen=True)
class WsDataQualityConfig:
    min_rows: int = 1
    min_exchanges: int = 1
    min_markets: int = 1
    min_span_hours: float = 0.0
    min_duration_ratio: float = 0.0
    max_parse_error_rate: float = 1.0
    required_event_kinds: tuple[str, ...] = ("bbo", "depth", "trade")
    min_markets_with_required_kinds: int = 0
    max_market_event_share: float = 1.0
    max_gap_sec: float = 0.0
    max_manifest_error_count: int = 1_000_000


def default_ws_data_quality_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / f"ws_data_quality_{_utc_stamp()}.json"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _manifest_duration(manifest: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if not manifest:
        return None, None
    for key in ("duration_sec", "requested_duration_sec", "actual_duration_sec"):
        value = _as_float(manifest.get(key))
        if value is not None and value > 0:
            return value, key
    return None, None


def _market_key(row: dict[str, Any]) -> str:
    return f"{row.get('exchange')}:{row.get('symbol')}"


def _manifest_error_count(manifest: dict[str, Any] | None) -> int:
    if not manifest:
        return 0
    errors = manifest.get("errors")
    if isinstance(errors, dict):
        return sum(len(value) for value in errors.values() if isinstance(value, list))
    if isinstance(errors, list):
        return len(errors)
    total = 0
    for item in manifest.get("results", []) if isinstance(manifest.get("results"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("errors"), list):
            total += len(item["errors"])
    return total


def _read_manifest(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    source = Path(path)
    if not source.exists():
        return None
    data = json.loads(source.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def run_ws_data_quality(
    input_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    config: WsDataQualityConfig | None = None,
) -> dict[str, Any]:
    cfg = config or WsDataQualityConfig()
    source = Path(input_path)
    manifest = _read_manifest(manifest_path)
    by_exchange: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    by_market: Counter[str] = Counter()
    market_kinds: dict[str, set[str]] = defaultdict(set)
    market_timestamps: dict[str, list[float]] = defaultdict(list)
    timestamps: list[float] = []
    parse_errors: list[dict[str, Any]] = []
    malformed_rows = 0
    rows = 0
    total_lines = 0

    with source.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            total_lines += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                parse_errors.append({"line": line_no, "error": f"JSONDecodeError: {exc.msg}"})
                continue
            if not isinstance(row, dict):
                malformed_rows += 1
                continue
            exchange = str(row.get("exchange") or "")
            symbol = str(row.get("symbol") or "")
            kind = str(row.get("event_kind") or "")
            if not exchange or not symbol or not kind:
                malformed_rows += 1
                continue

            rows += 1
            by_exchange[exchange] += 1
            by_kind[kind] += 1
            market = _market_key(row)
            by_market[market] += 1
            market_kinds[market].add(kind)
            ts = _as_float(row.get("recv_ts") or row.get("exchange_ts"))
            if ts is not None:
                timestamps.append(ts)
                market_timestamps[market].append(ts)

    span_sec = (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else 0.0
    manifest_duration_sec, manifest_duration_source = _manifest_duration(manifest)
    duration_ratio = (span_sec / manifest_duration_sec) if manifest_duration_sec and manifest_duration_sec > 0 else None
    required_kinds = set(cfg.required_event_kinds)
    markets_with_required_kinds = sum(1 for kinds in market_kinds.values() if required_kinds.issubset(kinds))
    max_market_events = max(by_market.values()) if by_market else 0
    max_market_event_share = (max_market_events / rows) if rows else 0.0
    max_gap_sec = 0.0
    markets_with_gap_over_limit = 0
    for values in market_timestamps.values():
        ordered = sorted(values)
        if len(ordered) < 2:
            continue
        market_max_gap = max((right - left) for left, right in zip(ordered, ordered[1:]))
        max_gap_sec = max(max_gap_sec, market_max_gap)
        if cfg.max_gap_sec > 0 and market_max_gap > cfg.max_gap_sec:
            markets_with_gap_over_limit += 1

    parse_error_count = len(parse_errors)
    parse_error_rate = (parse_error_count / total_lines) if total_lines else 0.0
    manifest_error_count = _manifest_error_count(manifest)
    reasons: list[str] = []
    if rows < cfg.min_rows:
        reasons.append("min_rows")
    if len(by_exchange) < cfg.min_exchanges:
        reasons.append("min_exchanges")
    if len(by_market) < cfg.min_markets:
        reasons.append("min_markets")
    if (span_sec / 3600.0) < cfg.min_span_hours:
        reasons.append("min_span_hours")
    if cfg.min_duration_ratio > 0 and (duration_ratio is None or duration_ratio < cfg.min_duration_ratio):
        reasons.append("min_duration_ratio")
    if parse_error_rate > cfg.max_parse_error_rate:
        reasons.append("max_parse_error_rate")
    if markets_with_required_kinds < cfg.min_markets_with_required_kinds:
        reasons.append("min_markets_with_required_kinds")
    if max_market_event_share > cfg.max_market_event_share:
        reasons.append("max_market_event_share")
    if cfg.max_gap_sec > 0 and markets_with_gap_over_limit > 0:
        reasons.append("max_gap_sec")
    if manifest_error_count > cfg.max_manifest_error_count:
        reasons.append("max_manifest_error_count")

    return {
        "mode": "ws_data_quality",
        "input": str(source),
        "manifest": str(manifest_path) if manifest_path else None,
        "accepted": not reasons,
        "reasons": reasons,
        "config": asdict(cfg),
        "metrics": {
            "total_lines": total_lines,
            "rows": rows,
            "malformed_rows": malformed_rows,
            "parse_error_count": parse_error_count,
            "parse_error_rate": parse_error_rate,
            "exchanges": len(by_exchange),
            "markets": len(by_market),
            "event_kinds": len(by_kind),
            "span_sec": span_sec,
            "span_hours": span_sec / 3600.0,
            "manifest_duration_sec": manifest_duration_sec,
            "manifest_duration_source": manifest_duration_source,
            "duration_ratio": duration_ratio,
            "markets_with_required_kinds": markets_with_required_kinds,
            "max_market_event_share": max_market_event_share,
            "max_gap_sec": max_gap_sec,
            "markets_with_gap_over_limit": markets_with_gap_over_limit,
            "manifest_error_count": manifest_error_count,
        },
        "coverage": {
            "by_exchange": dict(by_exchange),
            "by_kind": dict(by_kind),
            "by_market": dict(by_market),
            "market_kinds": {market: sorted(kinds) for market, kinds in market_kinds.items()},
        },
        "parse_errors": parse_errors[:50],
    }


def run_ws_data_quality_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    manifest_path: str | Path | None = None,
    config: WsDataQualityConfig | None = None,
) -> dict[str, Any]:
    result = run_ws_data_quality(input_path, manifest_path=manifest_path, config=config)
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output"] = str(target)
    return result
