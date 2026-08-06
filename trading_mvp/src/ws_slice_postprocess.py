from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ws_data_quality import WsDataQualityConfig, run_ws_data_quality_file


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


def _emit_progress(progress_file: Path | None, payload: dict[str, Any], *, print_progress: bool) -> None:
    line = json.dumps(payload, ensure_ascii=False)
    if print_progress:
        print(line, flush=True)
    if progress_file is not None:
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        with progress_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _progress_payload(
    *,
    parsed_rows: int,
    rows_written: int,
    bytes_read: int,
    file_size: int,
    started: float,
    stage: str,
) -> dict[str, Any]:
    elapsed = max(time.monotonic() - started, 0.001)
    return {
        "progress": "ws_slice_postprocess",
        "stage": stage,
        "parsed_rows": parsed_rows,
        "rows_written": rows_written,
        "pct": round(100.0 * (bytes_read / file_size), 2) if file_size else 0.0,
        "rows_per_sec": round(parsed_rows / elapsed, 1),
        "elapsed_sec": round(elapsed, 1),
        "bytes_read": bytes_read,
        "file_size_bytes": file_size,
    }


def run_ws_slice_postprocess(
    input_path: str | Path,
    *,
    start_ts: float,
    end_ts: float,
    normalized_output_path: str | Path,
    manifest_output_path: str | Path,
    quality_output_path: str | Path,
    postprocess_output_path: str | Path,
    source_manifest_path: str | Path | None = None,
    source_postprocess_path: str | Path | None = None,
    source_gap_audit_path: str | Path | None = None,
    quality_config: WsDataQualityConfig | None = None,
    progress_every_lines: int = 1_000_000,
    progress_file: str | Path | None = None,
    print_progress: bool = False,
) -> dict[str, Any]:
    if end_ts <= start_ts:
        raise ValueError("end_ts must be greater than start_ts")

    source = Path(input_path)
    normalized_output = Path(normalized_output_path)
    manifest_output = Path(manifest_output_path)
    quality_output = Path(quality_output_path)
    postprocess_output = Path(postprocess_output_path)
    progress_path = Path(progress_file) if progress_file else None
    normalized_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    quality_output.parent.mkdir(parents=True, exist_ok=True)
    postprocess_output.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    file_size = source.stat().st_size
    bytes_read = 0
    total_lines = 0
    parsed_rows = 0
    rows_written = 0
    malformed_rows = 0
    timestamp_missing = 0
    by_exchange: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    by_market: Counter[str] = Counter()
    first_ts: float | None = None
    last_ts: float | None = None

    if progress_path and progress_path.exists():
        progress_path.unlink()
    _emit_progress(
        progress_path,
        _progress_payload(
            parsed_rows=parsed_rows,
            rows_written=rows_written,
            bytes_read=bytes_read,
            file_size=file_size,
            started=started,
            stage="started",
        ),
        print_progress=print_progress,
    )

    with source.open("rb") as src, normalized_output.open("w", encoding="utf-8") as out:
        for raw_line in src:
            bytes_read += len(raw_line)
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
            parsed_rows += 1
            if progress_every_lines > 0 and parsed_rows % progress_every_lines == 0:
                _emit_progress(
                    progress_path,
                    _progress_payload(
                        parsed_rows=parsed_rows,
                        rows_written=rows_written,
                        bytes_read=bytes_read,
                        file_size=file_size,
                        started=started,
                        stage="scanning",
                    ),
                    print_progress=print_progress,
                )
            ts = _as_float(row.get("recv_ts") or row.get("exchange_ts"))
            if ts is None:
                timestamp_missing += 1
                continue
            if ts < start_ts or ts >= end_ts:
                continue
            exchange = str(row.get("exchange") or "")
            symbol = str(row.get("symbol") or "")
            kind = str(row.get("event_kind") or "")
            if not exchange or not symbol or not kind:
                malformed_rows += 1
                continue
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            rows_written += 1
            by_exchange[exchange] += 1
            by_kind[kind] += 1
            by_market[f"{exchange}:{symbol}"] += 1
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
    _emit_progress(
        progress_path,
        _progress_payload(
            parsed_rows=parsed_rows,
            rows_written=rows_written,
            bytes_read=bytes_read,
            file_size=file_size,
            started=started,
            stage="quality_check",
        ),
        print_progress=print_progress,
    )

    span_sec = (last_ts - first_ts) if first_ts is not None and last_ts is not None else 0.0
    manifest = {
        "schema": "ws_normalized_slice_v1",
        "mode": "ws_slice_postprocess_manifest",
        "source_input": str(source),
        "source_manifest": str(source_manifest_path) if source_manifest_path else None,
        "source_postprocess": str(source_postprocess_path) if source_postprocess_path else None,
        "source_gap_audit": str(source_gap_audit_path) if source_gap_audit_path else None,
        "normalized_output": str(normalized_output),
        "start_ts": start_ts,
        "start_iso": _iso_utc(start_ts),
        "end_ts": end_ts,
        "end_iso": _iso_utc(end_ts),
        "duration_sec": end_ts - start_ts,
        "actual_first_ts": first_ts,
        "actual_first_iso": _iso_utc(first_ts),
        "actual_last_ts": last_ts,
        "actual_last_iso": _iso_utc(last_ts),
        "actual_span_sec": span_sec,
        "rows": rows_written,
        "by_exchange": dict(by_exchange),
        "by_kind": dict(by_kind),
        "markets": len(by_market),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = quality_config or WsDataQualityConfig()
    data_quality = run_ws_data_quality_file(
        normalized_output,
        quality_output,
        manifest_path=manifest_output,
        config=cfg,
    )
    replay_allowed = bool(data_quality.get("accepted"))
    result = {
        "mode": "ws_postprocess_guarded",
        "input": str(source),
        "manifest": str(manifest_output),
        "normalized_output": str(normalized_output),
        "quality_output": str(quality_output),
        "replay_allowed": replay_allowed,
        "slice": manifest,
        "normalization": {
            "mode": "ws_normalized_slice",
            "input": str(source),
            "output": str(normalized_output),
            "total_lines": total_lines,
            "parsed_rows": parsed_rows,
            "rows_written": rows_written,
            "malformed_rows": malformed_rows,
            "timestamp_missing": timestamp_missing,
            "by_exchange": dict(by_exchange),
            "by_kind": dict(by_kind),
            "by_market": dict(by_market),
        },
        "data_quality": data_quality,
        "next_steps": [
            "If replay_allowed=true, run replay validation PlanOnly with ExpectedManifestPath set to this slice manifest.",
            "If replay_allowed=false, do not run replay/grid; inspect data_quality.reasons and either choose a stricter clean slice or reject this dataset.",
        ],
        "blocked_actions": [
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward_without_accepted_research",
            "replay_grid_if_data_quality_rejected",
        ],
    }
    postprocess_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["output"] = str(postprocess_output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a normalized WS clean slice and guarded postprocess artifact.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--start-ts", type=float, required=True)
    parser.add_argument("--end-ts", type=float, required=True)
    parser.add_argument("--normalized-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    parser.add_argument("--quality-output", required=True)
    parser.add_argument("--postprocess-output", required=True)
    parser.add_argument("--source-manifest")
    parser.add_argument("--source-postprocess")
    parser.add_argument("--source-gap-audit")
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

    result = run_ws_slice_postprocess(
        args.input,
        start_ts=args.start_ts,
        end_ts=args.end_ts,
        normalized_output_path=args.normalized_output,
        manifest_output_path=args.manifest_output,
        quality_output_path=args.quality_output,
        postprocess_output_path=args.postprocess_output,
        source_manifest_path=args.source_manifest,
        source_postprocess_path=args.source_postprocess,
        source_gap_audit_path=args.source_gap_audit,
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
                "rows_written": result["normalization"]["rows_written"],
                "data_quality_reasons": result["data_quality"]["reasons"],
                "data_quality_metrics": result["data_quality"]["metrics"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
