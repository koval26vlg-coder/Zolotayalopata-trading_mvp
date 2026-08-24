from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ws_data_quality import WsDataQualityConfig, run_ws_data_quality_file


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def _parse_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        return None
    data = json.loads(source.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _duration_from_doc(doc: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if not doc:
        return None, None
    for key in ("duration_sec", "requested_duration_sec", "actual_duration_sec"):
        value = _as_float(doc.get(key))
        if value is not None and value > 0:
            return value, key
    nested_candidates = (
        ("slice", "duration_sec"),
        ("market_filter", "duration_sec"),
        ("manifest", "duration_sec"),
    )
    for outer_key, inner_key in nested_candidates:
        nested = doc.get(outer_key)
        if isinstance(nested, dict):
            value = _as_float(nested.get(inner_key))
            if value is not None and value > 0:
                return value, f"{outer_key}.{inner_key}"
    return None, None


def _market_key(exchange: str, symbol: str) -> str:
    return f"{exchange}:{symbol}"


def _progress_payload(
    *,
    stage: str,
    pass_no: int,
    total_passes: int,
    parsed_rows: int,
    output_rows: int,
    bytes_read: int,
    file_size: int,
    started: float,
) -> dict[str, Any]:
    elapsed = max(time.monotonic() - started, 0.001)
    return {
        "progress": "ws_market_filter",
        "stage": stage,
        "pass_no": pass_no,
        "total_passes": total_passes,
        "parsed_rows": parsed_rows,
        "output_rows": output_rows,
        "stage_pct": round(100.0 * (bytes_read / file_size), 2) if file_size else 0.0,
        "rows_per_sec": round(parsed_rows / elapsed, 1),
        "elapsed_sec": round(elapsed, 1),
        "bytes_read": bytes_read,
        "file_size_bytes": file_size,
    }


def _emit_progress(progress_file: Path | None, payload: dict[str, Any], *, print_progress: bool) -> None:
    line = json.dumps(payload, ensure_ascii=False)
    if print_progress:
        print(line, flush=True)
    if progress_file is not None:
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        with progress_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


@dataclass(frozen=True)
class WsMarketFilterConfig:
    required_event_kinds: tuple[str, ...] = ("bbo", "depth", "trade")
    max_gap_sec: float = 300.0
    min_rows_per_market: int = 1
    min_market_span_hours: float = 0.0
    min_market_duration_ratio: float = 0.0
    reject_out_of_order: bool = True
    min_accepted_markets: int = 1
    min_accepted_exchanges: int = 1
    min_total_rows: int = 1
    max_market_event_share: float = 1.0
    min_trade_frequency_hz: float = 0.0
    max_avg_spread_bps: float = 0.0


@dataclass
class _MarketStats:
    exchange: str
    symbol: str
    rows: int = 0
    timestamp_missing: int = 0
    out_of_order_count: int = 0
    kinds: Counter[str] = field(default_factory=Counter)
    first_ts: float | None = None
    last_ts: float | None = None
    last_seen_ts: float | None = None
    max_gap_sec: float = 0.0
    sum_spread_bps: float = 0.0
    spread_samples: int = 0

    def add(self, *, kind: str, ts: float | None, spread_bps: float | None = None) -> None:
        self.rows += 1
        self.kinds[kind] += 1
        if spread_bps is not None and spread_bps > 0:
            self.sum_spread_bps += spread_bps
            self.spread_samples += 1
        if ts is None:
            self.timestamp_missing += 1
            return
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts
        if self.last_seen_ts is not None:
            if ts < self.last_seen_ts:
                self.out_of_order_count += 1
            else:
                self.max_gap_sec = max(self.max_gap_sec, ts - self.last_seen_ts)
        self.last_seen_ts = ts

    def span_sec(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return max(0.0, self.last_ts - self.first_ts)

    def to_report(self, *, source_duration_sec: float | None, reasons: list[str]) -> dict[str, Any]:
        span = self.span_sec()
        return {
            "market": _market_key(self.exchange, self.symbol),
            "exchange": self.exchange,
            "symbol": self.symbol,
            "accepted": not reasons,
            "reasons": reasons,
            "rows": self.rows,
            "event_kinds": dict(self.kinds),
            "first_ts": self.first_ts,
            "first_iso": _iso_utc(self.first_ts),
            "last_ts": self.last_ts,
            "last_iso": _iso_utc(self.last_ts),
            "span_sec": span,
            "span_hours": span / 3600.0,
            "duration_ratio": (span / source_duration_sec) if source_duration_sec and source_duration_sec > 0 else None,
            "max_gap_sec": self.max_gap_sec,
            "timestamp_missing": self.timestamp_missing,
            "out_of_order_count": self.out_of_order_count,
        }


def _market_reasons(
    stats: _MarketStats,
    *,
    config: WsMarketFilterConfig,
    source_duration_sec: float | None,
) -> list[str]:
    reasons: list[str] = []
    required = set(config.required_event_kinds)
    if stats.rows < config.min_rows_per_market:
        reasons.append("min_rows_per_market")
    if not required.issubset(set(stats.kinds)):
        reasons.append("required_event_kinds")
    if stats.timestamp_missing > 0:
        reasons.append("timestamp_missing")
    if config.reject_out_of_order and stats.out_of_order_count > 0:
        reasons.append("out_of_order")
    if config.max_gap_sec > 0 and stats.max_gap_sec > config.max_gap_sec:
        reasons.append("max_gap_sec")
    if (stats.span_sec() / 3600.0) < config.min_market_span_hours:
        reasons.append("min_market_span_hours")
    if config.min_market_duration_ratio > 0:
        duration_ratio = (stats.span_sec() / source_duration_sec) if source_duration_sec and source_duration_sec > 0 else None
        if duration_ratio is None or duration_ratio < config.min_market_duration_ratio:
            reasons.append("min_market_duration_ratio")
    
    if config.min_trade_frequency_hz > 0:
        trades = stats.kinds.get("trade", 0)
        span = stats.span_sec()
        hz = trades / span if span > 0 else 0.0
        if hz < config.min_trade_frequency_hz:
            reasons.append("min_trade_frequency")
            
    if config.max_avg_spread_bps > 0 and stats.spread_samples > 0:
        avg_spread = stats.sum_spread_bps / stats.spread_samples
        if avg_spread > config.max_avg_spread_bps:
            reasons.append("max_avg_spread")
            
    return reasons


def run_ws_market_filter(
    input_path: str | Path,
    *,
    normalized_output_path: str | Path,
    manifest_output_path: str | Path,
    report_output_path: str | Path,
    quality_output_path: str | Path,
    postprocess_output_path: str | Path,
    source_manifest_path: str | Path | None = None,
    source_postprocess_path: str | Path | None = None,
    filter_config: WsMarketFilterConfig | None = None,
    quality_config: WsDataQualityConfig | None = None,
    progress_every_lines: int = 1_000_000,
    progress_file: str | Path | None = None,
    print_progress: bool = False,
) -> dict[str, Any]:
    source = Path(input_path)
    normalized_output = Path(normalized_output_path)
    manifest_output = Path(manifest_output_path)
    report_output = Path(report_output_path)
    quality_output = Path(quality_output_path)
    postprocess_output = Path(postprocess_output_path)
    progress_path = Path(progress_file) if progress_file else None
    cfg = filter_config or WsMarketFilterConfig()

    normalized_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    quality_output.parent.mkdir(parents=True, exist_ok=True)
    postprocess_output.parent.mkdir(parents=True, exist_ok=True)
    if progress_path and progress_path.exists():
        progress_path.unlink()

    source_manifest = _read_json(source_manifest_path)
    source_postprocess = _read_json(source_postprocess_path)
    source_duration_sec, source_duration_source = _duration_from_doc(source_postprocess)
    if source_duration_sec is None:
        source_duration_sec, source_duration_source = _duration_from_doc(source_manifest)

    started = time.monotonic()
    file_size = source.stat().st_size
    stats_by_market: dict[str, _MarketStats] = {}
    by_exchange: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    total_lines = 0
    parsed_rows = 0
    malformed_rows = 0
    pass1_bytes = 0

    _emit_progress(
        progress_path,
        _progress_payload(
            stage="pass1_started",
            pass_no=1,
            total_passes=2,
            parsed_rows=0,
            output_rows=0,
            bytes_read=0,
            file_size=file_size,
            started=started,
        ),
        print_progress=print_progress,
    )

    with source.open("rb") as src:
        for raw_line in src:
            pass1_bytes += len(raw_line)
            if not raw_line.strip():
                continue
            total_lines += 1
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                malformed_rows += 1
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
            parsed_rows += 1
            by_exchange[exchange] += 1
            by_kind[kind] += 1
            key = _market_key(exchange, symbol)
            if key not in stats_by_market:
                stats_by_market[key] = _MarketStats(exchange=exchange, symbol=symbol)
            spread_bps = _as_float(row.get("spread_bps")) if kind in ("bbo", "depth") else None
            stats_by_market[key].add(
                kind=kind, 
                ts=_as_float(row.get("recv_ts") or row.get("exchange_ts")),
                spread_bps=spread_bps
            )
            if progress_every_lines > 0 and parsed_rows % progress_every_lines == 0:
                _emit_progress(
                    progress_path,
                    _progress_payload(
                        stage="pass1_scanning",
                        pass_no=1,
                        total_passes=2,
                        parsed_rows=parsed_rows,
                        output_rows=0,
                        bytes_read=pass1_bytes,
                        file_size=file_size,
                        started=started,
                    ),
                    print_progress=print_progress,
                )

    if source_duration_sec is None:
        first_values = [stats.first_ts for stats in stats_by_market.values() if stats.first_ts is not None]
        last_values = [stats.last_ts for stats in stats_by_market.values() if stats.last_ts is not None]
        if first_values and last_values:
            source_duration_sec = max(last_values) - min(first_values)
            source_duration_source = "input_span"

    market_reports: list[dict[str, Any]] = []
    accepted_markets: set[str] = set()
    rejected_markets: dict[str, list[str]] = {}
    for key, stats in sorted(stats_by_market.items()):
        reasons = _market_reasons(stats, config=cfg, source_duration_sec=source_duration_sec)
        market_reports.append(stats.to_report(source_duration_sec=source_duration_sec, reasons=reasons))
        if reasons:
            rejected_markets[key] = reasons
        else:
            accepted_markets.add(key)

    pass2_bytes = 0
    output_rows = 0
    output_by_exchange: Counter[str] = Counter()
    output_by_kind: Counter[str] = Counter()
    output_by_market: Counter[str] = Counter()
    output_first_ts: float | None = None
    output_last_ts: float | None = None

    _emit_progress(
        progress_path,
        _progress_payload(
            stage="pass2_started",
            pass_no=2,
            total_passes=2,
            parsed_rows=parsed_rows,
            output_rows=0,
            bytes_read=0,
            file_size=file_size,
            started=started,
        ),
        print_progress=print_progress,
    )

    with source.open("rb") as src, normalized_output.open("w", encoding="utf-8") as out:
        for raw_line in src:
            pass2_bytes += len(raw_line)
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            exchange = str(row.get("exchange") or "")
            symbol = str(row.get("symbol") or "")
            kind = str(row.get("event_kind") or "")
            if not exchange or not symbol or not kind:
                continue
            key = _market_key(exchange, symbol)
            if key not in accepted_markets:
                continue
            ts = _as_float(row.get("recv_ts") or row.get("exchange_ts"))
            if ts is None:
                continue
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            output_rows += 1
            output_by_exchange[exchange] += 1
            output_by_kind[kind] += 1
            output_by_market[key] += 1
            output_first_ts = ts if output_first_ts is None else min(output_first_ts, ts)
            output_last_ts = ts if output_last_ts is None else max(output_last_ts, ts)
            if progress_every_lines > 0 and output_rows > 0 and output_rows % progress_every_lines == 0:
                _emit_progress(
                    progress_path,
                    _progress_payload(
                        stage="pass2_writing",
                        pass_no=2,
                        total_passes=2,
                        parsed_rows=parsed_rows,
                        output_rows=output_rows,
                        bytes_read=pass2_bytes,
                        file_size=file_size,
                        started=started,
                    ),
                    print_progress=print_progress,
                )

    output_span_sec = (output_last_ts - output_first_ts) if output_first_ts is not None and output_last_ts is not None else 0.0
    max_output_market_events = max(output_by_market.values()) if output_by_market else 0
    output_market_event_share = (max_output_market_events / output_rows) if output_rows else 0.0

    filter_reasons: list[str] = []
    if len(accepted_markets) < cfg.min_accepted_markets:
        filter_reasons.append("min_accepted_markets")
    if len(output_by_exchange) < cfg.min_accepted_exchanges:
        filter_reasons.append("min_accepted_exchanges")
    if output_rows < cfg.min_total_rows:
        filter_reasons.append("min_total_rows")
    if output_market_event_share > cfg.max_market_event_share:
        filter_reasons.append("max_market_event_share")

    manifest = {
        "schema": "ws_market_filtered_slice_v1",
        "mode": "ws_market_filter_manifest",
        "source_input": str(source),
        "source_manifest": str(source_manifest_path) if source_manifest_path else None,
        "source_postprocess": str(source_postprocess_path) if source_postprocess_path else None,
        "normalized_output": str(normalized_output),
        "duration_sec": source_duration_sec,
        "duration_source": source_duration_source,
        "actual_first_ts": output_first_ts,
        "actual_first_iso": _iso_utc(output_first_ts),
        "actual_last_ts": output_last_ts,
        "actual_last_iso": _iso_utc(output_last_ts),
        "actual_span_sec": output_span_sec,
        "rows": output_rows,
        "markets": len(output_by_market),
        "accepted_markets": sorted(accepted_markets),
        "rejected_markets": rejected_markets,
        "filter_reasons": filter_reasons,
        "by_exchange": dict(output_by_exchange),
        "by_kind": dict(output_by_kind),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "mode": "ws_market_filter",
        "input": str(source),
        "output": str(normalized_output),
        "manifest": str(manifest_output),
        "accepted": not filter_reasons,
        "reasons": filter_reasons,
        "config": asdict(cfg),
        "source_duration_sec": source_duration_sec,
        "source_duration_source": source_duration_source,
        "metrics": {
            "total_lines": total_lines,
            "parsed_rows": parsed_rows,
            "malformed_rows": malformed_rows,
            "input_exchanges": len(by_exchange),
            "input_markets": len(stats_by_market),
            "input_event_kinds": len(by_kind),
            "accepted_markets": len(accepted_markets),
            "rejected_markets": len(rejected_markets),
            "output_rows": output_rows,
            "output_exchanges": len(output_by_exchange),
            "output_markets": len(output_by_market),
            "output_event_kinds": len(output_by_kind),
            "output_span_sec": output_span_sec,
            "output_span_hours": output_span_sec / 3600.0,
            "output_duration_ratio": (output_span_sec / source_duration_sec) if source_duration_sec and source_duration_sec > 0 else None,
            "output_max_market_event_share": output_market_event_share,
        },
        "coverage": {
            "input_by_exchange": dict(by_exchange),
            "input_by_kind": dict(by_kind),
            "output_by_exchange": dict(output_by_exchange),
            "output_by_kind": dict(output_by_kind),
            "output_by_market": dict(output_by_market),
        },
        "markets": market_reports,
    }
    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _emit_progress(
        progress_path,
        _progress_payload(
            stage="quality_check",
            pass_no=2,
            total_passes=2,
            parsed_rows=parsed_rows,
            output_rows=output_rows,
            bytes_read=pass2_bytes,
            file_size=file_size,
            started=started,
        ),
        print_progress=print_progress,
    )

    data_quality = run_ws_data_quality_file(
        normalized_output,
        quality_output,
        manifest_path=manifest_output,
        config=quality_config or WsDataQualityConfig(),
    )
    replay_allowed = bool(not filter_reasons and data_quality.get("accepted"))
    postprocess = {
        "mode": "ws_market_filter_postprocess_guarded",
        "input": str(source),
        "manifest": str(manifest_output),
        "normalized_output": str(normalized_output),
        "market_filter_output": str(report_output),
        "quality_output": str(quality_output),
        "replay_allowed": replay_allowed,
        "market_filter": report,
        "data_quality": data_quality,
        "next_steps": [
            "If replay_allowed=true, run replay validation PlanOnly with ExpectedManifestPath set to this market-filter manifest.",
            "If replay_allowed=false, do not run replay/grid; inspect market_filter.reasons and data_quality.reasons.",
        ],
        "blocked_actions": [
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward_without_accepted_research",
            "replay_grid_if_market_filter_or_data_quality_rejected",
        ],
    }
    postprocess_output.write_text(json.dumps(postprocess, ensure_ascii=False, indent=2), encoding="utf-8")

    _emit_progress(
        progress_path,
        {
            **_progress_payload(
                stage="done",
                pass_no=2,
                total_passes=2,
                parsed_rows=parsed_rows,
                output_rows=output_rows,
                bytes_read=pass2_bytes,
                file_size=file_size,
                started=started,
            ),
            "replay_allowed": replay_allowed,
            "filter_reasons": filter_reasons,
            "data_quality_reasons": data_quality.get("reasons", []),
        },
        print_progress=print_progress,
    )
    postprocess["output"] = str(postprocess_output)
    return postprocess


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter normalized WS rows by strict per-market quality before replay.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--normalized-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    parser.add_argument("--report-output", required=True)
    parser.add_argument("--quality-output", required=True)
    parser.add_argument("--postprocess-output", required=True)
    parser.add_argument("--source-manifest")
    parser.add_argument("--source-postprocess")
    parser.add_argument("--filter-required-event-kinds", default="bbo,depth,trade")
    parser.add_argument("--filter-max-gap-sec", type=float, default=300.0)
    parser.add_argument("--filter-min-rows-per-market", type=int, default=1000)
    parser.add_argument("--filter-min-market-span-hours", type=float, default=5.0)
    parser.add_argument("--filter-min-market-duration-ratio", type=float, default=0.80)
    parser.add_argument("--filter-allow-out-of-order", action="store_true")
    parser.add_argument("--filter-min-accepted-markets", type=int, default=5)
    parser.add_argument("--filter-min-accepted-exchanges", type=int, default=2)
    parser.add_argument("--filter-min-total-rows", type=int, default=5000)
    parser.add_argument("--filter-max-market-event-share", type=float, default=0.50)
    parser.add_argument("--filter-min-trade-frequency-hz", type=float, default=0.0)
    parser.add_argument("--filter-max-avg-spread-bps", type=float, default=0.0)
    parser.add_argument("--min-rows", type=int, default=5000)
    parser.add_argument("--min-exchanges", type=int, default=2)
    parser.add_argument("--min-markets", type=int, default=5)
    parser.add_argument("--min-span-hours", type=float, default=5.0)
    parser.add_argument("--min-duration-ratio", type=float, default=0.80)
    parser.add_argument("--max-parse-error-rate", type=float, default=0.05)
    parser.add_argument("--required-event-kinds", default="bbo,depth,trade")
    parser.add_argument("--min-markets-with-required-kinds", type=int, default=5)
    parser.add_argument("--max-market-event-share", type=float, default=0.50)
    parser.add_argument("--max-gap-sec", type=float, default=300.0)
    parser.add_argument("--max-manifest-error-count", type=int, default=50)
    parser.add_argument("--progress-every-lines", type=int, default=1_000_000)
    parser.add_argument("--progress-file")
    parser.add_argument("--print-progress", action="store_true")
    args = parser.parse_args()

    result = run_ws_market_filter(
        args.input,
        normalized_output_path=args.normalized_output,
        manifest_output_path=args.manifest_output,
        report_output_path=args.report_output,
        quality_output_path=args.quality_output,
        postprocess_output_path=args.postprocess_output,
        source_manifest_path=args.source_manifest,
        source_postprocess_path=args.source_postprocess,
        filter_config=WsMarketFilterConfig(
            required_event_kinds=_parse_csv(args.filter_required_event_kinds) or ("bbo", "depth", "trade"),
            max_gap_sec=args.filter_max_gap_sec,
            min_rows_per_market=args.filter_min_rows_per_market,
            min_market_span_hours=args.filter_min_market_span_hours,
            min_market_duration_ratio=args.filter_min_market_duration_ratio,
            reject_out_of_order=not args.filter_allow_out_of_order,
            min_accepted_markets=args.filter_min_accepted_markets,
            min_accepted_exchanges=args.filter_min_accepted_exchanges,
            min_total_rows=args.filter_min_total_rows,
            max_market_event_share=args.filter_max_market_event_share,
            min_trade_frequency_hz=args.filter_min_trade_frequency_hz,
            max_avg_spread_bps=args.filter_max_avg_spread_bps,
        ),
        quality_config=WsDataQualityConfig(
            min_rows=args.min_rows,
            min_exchanges=args.min_exchanges,
            min_markets=args.min_markets,
            min_span_hours=args.min_span_hours,
            min_duration_ratio=args.min_duration_ratio,
            max_parse_error_rate=args.max_parse_error_rate,
            required_event_kinds=_parse_csv(args.required_event_kinds) or ("bbo", "depth", "trade"),
            min_markets_with_required_kinds=args.min_markets_with_required_kinds,
            max_market_event_share=args.max_market_event_share,
            max_gap_sec=args.max_gap_sec,
            max_manifest_error_count=args.max_manifest_error_count,
        ),
        progress_every_lines=args.progress_every_lines,
        progress_file=args.progress_file,
        print_progress=args.print_progress,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": result["output"],
                "replay_allowed": result["replay_allowed"],
                "accepted_markets": result["market_filter"]["metrics"]["accepted_markets"],
                "rejected_markets": result["market_filter"]["metrics"]["rejected_markets"],
                "output_rows": result["market_filter"]["metrics"]["output_rows"],
                "filter_reasons": result["market_filter"]["reasons"],
                "data_quality_reasons": result["data_quality"]["reasons"],
                "data_quality_metrics": result["data_quality"]["metrics"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
