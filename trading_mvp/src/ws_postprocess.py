from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ws_data_quality import WsDataQualityConfig, run_ws_data_quality_file
from ws_normalizer import normalize_ws_files


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def default_ws_postprocess_report_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / f"ws_postprocess_{_utc_stamp()}.json"


def default_ws_postprocess_normalized_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / f"ws_normalized_postprocess_{_utc_stamp()}.jsonl"


def default_ws_postprocess_quality_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / f"ws_data_quality_postprocess_{_utc_stamp()}.json"


def _next_steps(replay_allowed: bool) -> list[str]:
    if not replay_allowed:
        return [
            "Do not run ws-replay/ws-grid-search. Mark this WS dataset incomplete/rejected or collect a cleaner visible dataset.",
            "Inspect data_quality.reasons and coverage.by_market before changing strategy parameters.",
        ]
    return [
        "ws-replay/ws-grid-search may be run only as research with OOS/walk-forward/stress gates; this is not strategy acceptance.",
        "Record replay artifacts and rerun sweep_reversal_acceptance_gate before any paper-forward discussion.",
    ]


def run_ws_postprocess_file(
    input_path: str | Path,
    *,
    normalized_output_path: str | Path,
    quality_output_path: str | Path,
    report_output_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    quality_config: WsDataQualityConfig | None = None,
) -> dict[str, Any]:
    source = Path(input_path)
    manifest = manifest_path or (source if source.suffix.lower() == ".json" else None)
    normalization = normalize_ws_files(source, normalized_output_path)
    data_quality = run_ws_data_quality_file(
        normalized_output_path,
        quality_output_path,
        manifest_path=manifest,
        config=quality_config,
    )
    replay_allowed = bool(data_quality.get("accepted"))
    result = {
        "mode": "ws_postprocess_guarded",
        "input": str(source),
        "manifest": str(manifest) if manifest else None,
        "normalized_output": str(normalized_output_path),
        "quality_output": str(quality_output_path),
        "replay_allowed": replay_allowed,
        "normalization": normalization,
        "data_quality": data_quality,
        "next_steps": _next_steps(replay_allowed),
        "blocked_actions": [
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward_without_accepted_research",
            "replay_grid_if_data_quality_rejected",
        ],
    }
    if report_output_path:
        target = Path(report_output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output"] = str(target)
    return result
