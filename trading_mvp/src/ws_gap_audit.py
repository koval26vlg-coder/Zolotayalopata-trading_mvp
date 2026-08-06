from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _iso_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _safe_rate(num: float, den: float) -> float:
    return num / den if den else 0.0


@dataclass
class GapStats:
    count: int = 0
    first_ts: float | None = None
    last_ts: float | None = None
    max_gap_sec: float = 0.0
    max_gap_start_ts: float | None = None
    max_gap_end_ts: float | None = None
    gaps_over_threshold: int = 0
    out_of_order: int = 0

    def observe(self, ts: float, gap_threshold_sec: float) -> float | None:
        if self.first_ts is None:
            self.first_ts = ts
        gap: float | None = None
        if self.last_ts is not None:
            if ts < self.last_ts:
                self.out_of_order += 1
            else:
                gap = ts - self.last_ts
                if gap > self.max_gap_sec:
                    self.max_gap_sec = gap
                    self.max_gap_start_ts = self.last_ts
                    self.max_gap_end_ts = ts
                if gap_threshold_sec > 0 and gap > gap_threshold_sec:
                    self.gaps_over_threshold += 1
        if self.last_ts is None or ts >= self.last_ts:
            self.last_ts = ts
        self.count += 1
        return gap

    def to_dict(self, key: str) -> dict[str, Any]:
        span_sec = (self.last_ts - self.first_ts) if self.first_ts is not None and self.last_ts is not None else 0.0
        return {
            "key": key,
            "count": self.count,
            "first_ts": self.first_ts,
            "first_iso": _iso_utc(self.first_ts),
            "last_ts": self.last_ts,
            "last_iso": _iso_utc(self.last_ts),
            "span_sec": span_sec,
            "span_hours": span_sec / 3600.0,
            "max_gap_sec": self.max_gap_sec,
            "max_gap_hours": self.max_gap_sec / 3600.0,
            "max_gap_start_ts": self.max_gap_start_ts,
            "max_gap_start_iso": _iso_utc(self.max_gap_start_ts),
            "max_gap_end_ts": self.max_gap_end_ts,
            "max_gap_end_iso": _iso_utc(self.max_gap_end_ts),
            "gaps_over_threshold": self.gaps_over_threshold,
            "out_of_order": self.out_of_order,
        }


class BinCoverage:
    def __init__(self) -> None:
        self.markets_by_kind: dict[str, set[str]] = defaultdict(set)
        self.events_by_kind: Counter[str] = Counter()

    def observe(self, market: str, kind: str) -> None:
        self.markets_by_kind[kind].add(market)
        self.events_by_kind[kind] += 1

    def metrics(self) -> dict[str, Any]:
        return {
            "markets_by_kind": {kind: len(markets) for kind, markets in sorted(self.markets_by_kind.items())},
            "events_by_kind": dict(self.events_by_kind),
        }


def _top_stats(stats: dict[str, GapStats], top_n: int) -> list[dict[str, Any]]:
    return [
        item.to_dict(key)
        for key, item in sorted(stats.items(), key=lambda kv: (kv[1].max_gap_sec, kv[1].count), reverse=True)[:top_n]
    ]


def _find_clean_windows(
    bins: dict[int, BinCoverage],
    *,
    bin_sec: float,
    min_bbo_markets: int,
    min_depth_markets: int,
    min_trade_markets: int,
    top_n: int,
) -> list[dict[str, Any]]:
    if not bins:
        return []
    required = {
        "bbo": min_bbo_markets,
        "depth": min_depth_markets,
        "trade": min_trade_markets,
    }
    good_bins: set[int] = set()
    for bin_id, coverage in bins.items():
        metrics = coverage.metrics()["markets_by_kind"]
        if all(metrics.get(kind, 0) >= min_markets for kind, min_markets in required.items() if min_markets > 0):
            good_bins.add(bin_id)

    windows: list[dict[str, Any]] = []
    start: int | None = None
    previous: int | None = None
    for bin_id in sorted(good_bins):
        if start is None:
            start = previous = bin_id
            continue
        if previous is not None and bin_id == previous + 1:
            previous = bin_id
            continue
        if start is not None and previous is not None:
            windows.append(_window_payload(start, previous, bins, bin_sec))
        start = previous = bin_id
    if start is not None and previous is not None:
        windows.append(_window_payload(start, previous, bins, bin_sec))
    return sorted(windows, key=lambda row: row["duration_sec"], reverse=True)[:top_n]


def _window_payload(start_bin: int, end_bin: int, bins: dict[int, BinCoverage], bin_sec: float) -> dict[str, Any]:
    first_ts = start_bin * bin_sec
    end_ts = (end_bin + 1) * bin_sec
    min_markets_by_kind: dict[str, int] = {}
    for kind in ("bbo", "depth", "trade"):
        values = [len(bins[bin_id].markets_by_kind.get(kind, set())) for bin_id in range(start_bin, end_bin + 1)]
        min_markets_by_kind[kind] = min(values) if values else 0
    return {
        "start_ts": first_ts,
        "start_iso": _iso_utc(first_ts),
        "end_ts": end_ts,
        "end_iso": _iso_utc(end_ts),
        "duration_sec": end_ts - first_ts,
        "duration_hours": (end_ts - first_ts) / 3600.0,
        "bins": end_bin - start_bin + 1,
        "min_markets_by_kind": min_markets_by_kind,
    }


def _read_json_line(fh: BinaryIO) -> tuple[dict[str, Any] | None, int]:
    line = fh.readline()
    if not line:
        return None, 0
    if not line.strip():
        return {}, len(line)
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return {}, len(line)
    return row if isinstance(row, dict) else {}, len(line)


def run_ws_gap_audit(
    input_path: str | Path,
    *,
    gap_threshold_sec: float = 300.0,
    bin_sec: float = 300.0,
    top_n: int = 50,
    min_bbo_markets: int = 5,
    min_depth_markets: int = 5,
    min_trade_markets: int = 5,
    progress_every_lines: int = 1_000_000,
    progress: bool = False,
    progress_file: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(input_path)
    file_size = source.stat().st_size
    started = time.monotonic()

    market_stats: dict[str, GapStats] = defaultdict(GapStats)
    market_kind_stats: dict[str, GapStats] = defaultdict(GapStats)
    exchange_kind_stats: dict[str, GapStats] = defaultdict(GapStats)
    bins: dict[int, BinCoverage] = defaultdict(BinCoverage)
    by_exchange: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    by_market: Counter[str] = Counter()
    malformed_rows = 0
    timestamp_missing = 0
    rows = 0
    total_lines = 0
    bytes_read = 0
    progress_fh = None

    def emit_progress(payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        if progress:
            print(line, flush=True)
        if progress_fh is not None:
            progress_fh.write(line + "\n")
            progress_fh.flush()

    try:
        if progress_file is not None:
            progress_path = Path(progress_file)
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_fh = progress_path.open("w", encoding="utf-8")

        with source.open("rb") as fh:
            while True:
                raw_row, consumed = _read_json_line(fh)
                if consumed == 0:
                    break
                bytes_read += consumed
                if raw_row is None:
                    break
                if raw_row == {}:
                    malformed_rows += 1
                    continue
                total_lines += 1
                exchange = str(raw_row.get("exchange") or "")
                symbol = str(raw_row.get("symbol") or "")
                kind = str(raw_row.get("event_kind") or "")
                ts = _as_float(raw_row.get("recv_ts") or raw_row.get("exchange_ts"))
                if not exchange or not symbol or not kind:
                    malformed_rows += 1
                    continue
                if ts is None:
                    timestamp_missing += 1
                    continue

                rows += 1
                market = f"{exchange}:{symbol}"
                market_kind = f"{market}:{kind}"
                exchange_kind = f"{exchange}:{kind}"
                by_exchange[exchange] += 1
                by_kind[kind] += 1
                by_market[market] += 1
                market_stats[market].observe(ts, gap_threshold_sec)
                market_kind_stats[market_kind].observe(ts, gap_threshold_sec)
                exchange_kind_stats[exchange_kind].observe(ts, gap_threshold_sec)
                if bin_sec > 0:
                    bins[int(ts // bin_sec)].observe(market, kind)

                if progress_every_lines > 0 and rows % progress_every_lines == 0:
                    elapsed = max(time.monotonic() - started, 0.001)
                    pct = 100.0 * _safe_rate(bytes_read, file_size)
                    rate = rows / elapsed
                    emit_progress(
                        {
                            "progress": "ws_gap_audit",
                            "rows": rows,
                            "pct": round(pct, 2),
                            "rows_per_sec": round(rate, 1),
                            "elapsed_sec": round(elapsed, 1),
                            "bytes_read": bytes_read,
                            "file_size_bytes": file_size,
                        }
                    )
    finally:
        if progress_fh is not None:
            progress_fh.close()

    elapsed = time.monotonic() - started
    market_gap_over = sum(1 for stat in market_stats.values() if stat.max_gap_sec > gap_threshold_sec)
    market_kind_gap_over = sum(1 for stat in market_kind_stats.values() if stat.max_gap_sec > gap_threshold_sec)
    clean_windows = _find_clean_windows(
        bins,
        bin_sec=bin_sec,
        min_bbo_markets=min_bbo_markets,
        min_depth_markets=min_depth_markets,
        min_trade_markets=min_trade_markets,
        top_n=top_n,
    )
    top_market_gaps = _top_stats(market_stats, top_n)
    top_market_kind_gaps = _top_stats(market_kind_stats, top_n)
    top_exchange_kind_gaps = _top_stats(exchange_kind_stats, top_n)

    bbo_depth_max = max(
        [row["max_gap_sec"] for row in top_market_kind_gaps if row["key"].endswith(":bbo") or row["key"].endswith(":depth")]
        or [0.0]
    )
    trade_max = max([row["max_gap_sec"] for row in top_market_kind_gaps if row["key"].endswith(":trade")] or [0.0])
    if bbo_depth_max > gap_threshold_sec:
        diagnosis = "collector_or_quote_feed_gaps_present"
    elif trade_max > gap_threshold_sec:
        diagnosis = "trade_sparsity_or_trade_feed_gaps_present"
    else:
        diagnosis = "no_gap_threshold_breach_by_market_kind"

    return {
        "mode": "ws_gap_audit",
        "input": str(source),
        "config": {
            "gap_threshold_sec": gap_threshold_sec,
            "bin_sec": bin_sec,
            "top_n": top_n,
            "min_bbo_markets": min_bbo_markets,
            "min_depth_markets": min_depth_markets,
            "min_trade_markets": min_trade_markets,
        },
        "summary": {
            "rows": rows,
            "total_lines": total_lines,
            "malformed_rows": malformed_rows,
            "timestamp_missing": timestamp_missing,
            "elapsed_sec": elapsed,
            "file_size_bytes": file_size,
            "by_exchange": dict(by_exchange),
            "by_kind": dict(by_kind),
            "markets": len(by_market),
            "market_kind_keys": len(market_kind_stats),
            "market_gap_over_threshold": market_gap_over,
            "market_kind_gap_over_threshold": market_kind_gap_over,
            "top_level_diagnosis": diagnosis,
            "clean_window_count": len(clean_windows),
        },
        "top_market_gaps": top_market_gaps,
        "top_market_kind_gaps": top_market_kind_gaps,
        "top_exchange_kind_gaps": top_exchange_kind_gaps,
        "clean_windows": clean_windows,
        "market_rows_top": [
            {"market": market, "rows": count}
            for market, count in by_market.most_common(top_n)
        ],
    }


def run_ws_gap_audit_file(
    input_path: str | Path,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    result = run_ws_gap_audit(input_path, **kwargs)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["output"] = str(target)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit normalized WS data gaps by market and event kind.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--gap-threshold-sec", type=float, default=300.0)
    parser.add_argument("--bin-sec", type=float, default=300.0)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--min-bbo-markets", type=int, default=5)
    parser.add_argument("--min-depth-markets", type=int, default=5)
    parser.add_argument("--min-trade-markets", type=int, default=5)
    parser.add_argument("--progress-every-lines", type=int, default=1_000_000)
    parser.add_argument("--progress-file")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()
    result = run_ws_gap_audit_file(
        args.input,
        args.output,
        gap_threshold_sec=args.gap_threshold_sec,
        bin_sec=args.bin_sec,
        top_n=args.top_n,
        min_bbo_markets=args.min_bbo_markets,
        min_depth_markets=args.min_depth_markets,
        min_trade_markets=args.min_trade_markets,
        progress_every_lines=args.progress_every_lines,
        progress=not args.no_progress,
        progress_file=args.progress_file,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": result["output"],
                "summary": result["summary"],
                "top_market_gap": result["top_market_gaps"][0] if result["top_market_gaps"] else None,
                "top_market_kind_gap": result["top_market_kind_gaps"][0] if result["top_market_kind_gaps"] else None,
                "best_clean_window": result["clean_windows"][0] if result["clean_windows"] else None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
