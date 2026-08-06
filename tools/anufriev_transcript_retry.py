from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any


THEME_PATTERNS: dict[str, list[str]] = {
    "high_winrate_claims": [
        r"\bвинрейт\b",
        r"\bwin[\s-]?rate\b",
        r"90\s*%",
        r"доходност",
        r"прибыл",
        r"разгон",
        r"депозит",
    ],
    "hft_orderbook_scalping": [
        r"\bстакан",
        r"\border\s*book\b",
        r"\blevel\s*2\b",
        r"\bскальп",
        r"\bhft\b",
        r"айсберг",
        r"ликвидност",
    ],
    "market_maker_manipulation": [
        r"маркетмейкер",
        r"market\s*maker",
        r"манипул",
        r"стоп[\s-]?лосс",
        r"stop[\s-]?loss",
        r"спуф",
        r"spoof",
        r"вынос",
    ],
    "funding_basis_arbitrage": [
        r"фандинг",
        r"funding",
        r"\bbasis\b",
        r"базис",
        r"арбитраж",
        r"пассив",
        r"carry",
    ],
    "ai_trading": [
        r"искусственн",
        r"\bии\b",
        r"\bai\b",
        r"нейросет",
        r"\bбот(?:ы|а|ом|ов)?\b",
        r"алгоритм",
        r"агент",
    ],
    "risk_psychology_process": [
        r"риск",
        r"психолог",
        r"дисциплин",
        r"плейбук",
        r"playbook",
        r"лимит",
        r"ошибк",
    ],
    "prop_moex_traditional": [
        r"проп",
        r"prop",
        r"фьючерс",
        r"futures",
        r"мосбирж",
        r"\bmoex\b",
        r"срочн",
    ],
    "news_event_trading": [
        r"новост",
        r"событи",
        r"polymarket",
        r"волатильност",
        r"цикл",
        r"рынок руш",
    ],
    "crypto_regulation_legal": [
        r"закон",
        r"регулир",
        r"юрист",
        r"налог",
        r"крипт",
        r"легаль",
    ],
}


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _load_queue(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _load_metadata_by_id(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        video_id = str(row.get("id") or "")
        if video_id:
            out[video_id] = row
    return out


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"attempts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"attempts": {}}
    if not isinstance(data.get("attempts"), dict):
        data["attempts"] = {}
    return data


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _successful_ids_from_jsonl(path: Path) -> set[str]:
    ids: set[str] = set()
    for row in _read_jsonl(path):
        if row.get("transcript_ok") is True and row.get("id"):
            ids.add(str(row["id"]))
    return ids


def _discover_existing_successes(queue_path: Path, output_path: Path, include_output: bool = True) -> set[str]:
    successes: set[str] = set()
    for path in queue_path.parent.glob("anufriev_transcript_claim_cards*.jsonl"):
        if path.resolve() == output_path.resolve():
            continue
        successes.update(_successful_ids_from_jsonl(path))
    if include_output:
        successes.update(_successful_ids_from_jsonl(output_path))
    return successes


def _caption_candidates(meta: dict[str, Any]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for bucket_name in ("subtitles", "automatic_captions"):
        bucket = meta.get(bucket_name) or {}
        for lang in ("ru", "ru-orig", "en"):
            entries = bucket.get(lang) or []
            for item in entries:
                if item.get("ext") == "json3" and item.get("url"):
                    candidates.append((f"{bucket_name}:{lang}:json3", str(item["url"])))
            for item in entries:
                if item.get("url") and item.get("ext") != "json3":
                    candidates.append((f"{bucket_name}:{lang}:{item.get('ext')}", str(item["url"])))
    return candidates


def _fetch_json(url: str, timeout_sec: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _json3_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        start_ms = event.get("tStartMs")
        dur_ms = event.get("dDurationMs") or 0
        pieces = []
        for seg in event.get("segs") or []:
            text = seg.get("utf8")
            if text:
                pieces.append(str(text))
        text = " ".join(" ".join(pieces).split())
        if start_ms is None or not text:
            continue
        segments.append(
            {
                "start_sec": round(float(start_ms) / 1000.0, 3),
                "end_sec": round((float(start_ms) + float(dur_ms)) / 1000.0, 3),
                "text": text,
            }
        )
    return segments


def _compile_patterns() -> dict[str, list[re.Pattern[str]]]:
    return {
        theme: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        for theme, patterns in THEME_PATTERNS.items()
    }


def _matching_themes(text: str, compiled: dict[str, list[re.Pattern[str]]]) -> list[str]:
    return [
        theme
        for theme, patterns in compiled.items()
        if any(pattern.search(text) for pattern in patterns)
    ]


def _claim_windows(
    segments: list[dict[str, Any]],
    max_windows: int,
    context_segments: int = 1,
) -> tuple[list[str], list[dict[str, Any]]]:
    compiled = _compile_patterns()
    windows: list[dict[str, Any]] = []
    matched_themes: set[str] = set()
    seen: set[tuple[int, str]] = set()
    for idx, segment in enumerate(segments):
        themes = _matching_themes(str(segment.get("text") or ""), compiled)
        if not themes:
            continue
        matched_themes.update(themes)
        start_idx = max(0, idx - context_segments)
        end_idx = min(len(segments), idx + context_segments + 1)
        excerpt = " ".join(str(item.get("text") or "") for item in segments[start_idx:end_idx])
        excerpt = " ".join(excerpt.split())
        if len(excerpt) > 700:
            excerpt = excerpt[:697].rstrip() + "..."
        key = (start_idx, excerpt)
        if key in seen:
            continue
        seen.add(key)
        windows.append(
            {
                "start_sec": segments[start_idx].get("start_sec"),
                "end_sec": segments[end_idx - 1].get("end_sec"),
                "themes": themes,
                "excerpt": excerpt,
            }
        )
        if len(windows) >= max_windows:
            break
    return sorted(matched_themes), windows


def _attempt_video(
    queue_row: dict[str, str],
    meta: dict[str, Any] | None,
    timeout_sec: int,
    max_windows: int,
) -> dict[str, Any]:
    video_id = queue_row.get("id") or ""
    base = {
        "id": video_id,
        "title": queue_row.get("title", ""),
        "url": queue_row.get("url", ""),
        "priority_rank": int(queue_row.get("rank") or 0),
        "priority_score": float(queue_row.get("priority_score") or 0.0),
        "strategy_clusters_title_only": queue_row.get("strategy_clusters_title_only", ""),
        "participant_candidates_conservative": queue_row.get("participant_candidates_conservative", ""),
    }
    if not meta:
        return {**base, "transcript_ok": False, "error": "metadata_not_found"}
    candidates = _caption_candidates(meta)
    if not candidates:
        return {**base, "transcript_ok": False, "error": "caption_url_not_found"}

    errors: list[str] = []
    for source, url in candidates:
        try:
            payload = _fetch_json(url, timeout_sec=timeout_sec)
            segments = _json3_segments(payload)
        except urllib.error.HTTPError as exc:
            errors.append(f"HTTPError:{exc.code}:{source}")
            if exc.code == 429:
                raise
            continue
        except Exception as exc:  # noqa: BLE001 - this is an offline-safe collector.
            errors.append(f"{type(exc).__name__}:{source}:{str(exc)[:160]}")
            continue

        if not segments:
            errors.append(f"empty_segments:{source}")
            continue

        matched_themes, windows = _claim_windows(segments, max_windows=max_windows)
        return {
            **base,
            "transcript_ok": True,
            "matched_themes": matched_themes,
            "claim_windows": windows,
            "caption_source": source,
            "transcript_segment_count": len(segments),
            "transcript_char_count": sum(len(str(item.get("text") or "")) for item in segments),
        }

    return {**base, "transcript_ok": False, "error": "; ".join(errors)[:500]}


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def run(args: argparse.Namespace) -> int:
    queue_path = Path(args.queue)
    metadata_path = Path(args.metadata)
    output_path = Path(args.output)
    state_path = Path(args.state)
    queue = _load_queue(queue_path)
    metadata_by_id = _load_metadata_by_id(metadata_path)
    state = _load_state(state_path)
    attempts: dict[str, Any] = state["attempts"]
    existing_successes = set()
    if not args.reprocess:
        existing_successes = _discover_existing_successes(queue_path, output_path)

    processed = 0
    ok = 0
    failed = 0
    skipped_success = 0
    skipped_state = 0
    stopped_on_rate_limit = False

    for row in queue:
        video_id = row.get("id") or ""
        if not video_id:
            continue
        if video_id in existing_successes:
            skipped_success += 1
            continue
        prev = attempts.get(video_id) or {}
        if prev.get("transcript_ok") is True:
            skipped_state += 1
            continue
        if processed >= args.max_videos:
            break

        try:
            payload = _attempt_video(
                row,
                metadata_by_id.get(video_id),
                timeout_sec=args.timeout_sec,
                max_windows=args.max_windows,
            )
        except urllib.error.HTTPError as exc:
            payload = {
                "id": video_id,
                "title": row.get("title", ""),
                "url": row.get("url", ""),
                "priority_rank": int(row.get("rank") or 0),
                "transcript_ok": False,
                "error": f"HTTPError:{exc.code}:{str(exc)[:200]}",
            }
            _append_jsonl(output_path, payload)
            attempts[video_id] = {
                "last_status": "rate_limited" if exc.code == 429 else "http_error",
                "transcript_ok": False,
                "error": payload["error"],
                "ts": time.time(),
            }
            _save_state(state_path, state)
            processed += 1
            failed += 1
            if exc.code == 429 and args.stop_on_rate_limit:
                stopped_on_rate_limit = True
                break
        else:
            _append_jsonl(output_path, payload)
            attempts[video_id] = {
                "last_status": "ok" if payload.get("transcript_ok") else "failed",
                "transcript_ok": bool(payload.get("transcript_ok")),
                "error": payload.get("error"),
                "ts": time.time(),
            }
            _save_state(state_path, state)
            processed += 1
            if payload.get("transcript_ok"):
                ok += 1
                existing_successes.add(video_id)
            else:
                failed += 1

        if args.sleep_sec > 0 and processed < args.max_videos and not stopped_on_rate_limit:
            time.sleep(args.sleep_sec)

    state["last_run_summary"] = {
        "processed": processed,
        "ok": ok,
        "failed": failed,
        "skipped_existing_success": skipped_success,
        "skipped_state_success": skipped_state,
        "stopped_on_rate_limit": stopped_on_rate_limit,
        "output": str(output_path),
        "ts": time.time(),
    }
    _save_state(state_path, state)
    print(json.dumps(state["last_run_summary"], ensure_ascii=False, indent=2))
    return 0 if not stopped_on_rate_limit else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retry prioritized Anufriev YouTube transcript extraction from yt-dlp metadata. "
            "Writes only short claim windows, never full transcripts."
        )
    )
    parser.add_argument("--queue", required=True, help="CSV retry queue path")
    parser.add_argument("--metadata", required=True, help="yt-dlp metadata JSONL path")
    parser.add_argument("--output", required=True, help="Output claim cards JSONL path")
    parser.add_argument("--state", required=True, help="Resumable state JSON path")
    parser.add_argument("--max-videos", type=int, default=20)
    parser.add_argument("--sleep-sec", type=float, default=60.0)
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--max-windows", type=int, default=8)
    parser.add_argument("--stop-on-rate-limit", action="store_true")
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Do not skip existing successes; useful when theme patterns changed and output is a new file.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
