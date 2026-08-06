from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from costs import validate_runtime_sec
from historical_basis_code_snapshot import (
    require_plan_code_snapshot,
    require_plan_runtime_code_snapshot,
    validate_basis_code_snapshot_reference,
)
from historical_basis_probe import (
    GateBasisProbeClient,
    MexcBasisProbeClient,
    _basis,
    _ticker_prices,
    depth_execution_metrics,
)
from historical_basis_v2 import (
    sha256_file,
    sha256_json,
    validate_historical_basis_v2_plan,
)
from historical_basis_v2_evaluator import (
    SCHEMA as EVALUATION_SCHEMA,
    validate_full_evaluation_result,
)
from owned_run_gate import publish_owned_run_gate


PLAN_SCHEMA = "trading_mvp_historical_basis_v2_execution_probe_plan_v1"
SAMPLE_SCHEMA = "trading_mvp_historical_basis_v2_execution_probe_sample_v1"
MANIFEST_SCHEMA = "trading_mvp_historical_basis_v2_execution_probe_manifest_v1"
REPORT_SCHEMA = "trading_mvp_historical_basis_v2_execution_probe_report_v1"
WINDOW_COUNT = 3
WINDOW_DURATION_SEC = 1_200
SAMPLE_INTERVAL_SEC = 5
WINDOW_START_SEPARATION_SEC = 4 * 60 * 60


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _deterministic_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        ignored = {
            "code_snapshot_manifest",
            "generated_at_utc",
            "module_path",
            "path",
            "runtime_sec",
        }
        return {
            str(key): _deterministic_value(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
            if str(key) not in ignored
        }
    if isinstance(value, (list, tuple)):
        return [_deterministic_value(item) for item in value]
    return value


def artifact_hash(payload: Mapping[str, Any]) -> str:
    root = {
        key: value
        for key, value in payload.items()
        if key not in {"deterministic_result_hash", "probe_plan_hash"}
    }
    return sha256_json(_deterministic_value(root))


def _validate_hashed_artifact(
    payload: Mapping[str, Any],
    *,
    expected_schema: str,
    hash_field: str = "deterministic_result_hash",
    label: str,
) -> None:
    if payload.get("schema") != expected_schema:
        raise ValueError(f"unexpected {label} schema")
    observed = artifact_hash(payload)
    if payload.get(hash_field) != observed:
        raise ValueError(f"{label} deterministic hash mismatch")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("probe window timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _p95(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return ordered[index]


def _validate_historical_evaluation(
    evaluation_path: str | Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    evaluation_target = Path(evaluation_path).expanduser().resolve()
    evaluation = _read_json(evaluation_target)
    if evaluation.get("schema") != EVALUATION_SCHEMA:
        raise ValueError(f"expected historical evaluation schema {EVALUATION_SCHEMA}")
    if evaluation.get("stage") != "full_evaluation":
        raise ValueError("execution probe requires full_evaluation")
    if evaluation.get("verdict") != "ACCEPT_FOR_EXECUTION_PROBE":
        raise ValueError("execution probe requires historical ACCEPT_FOR_EXECUTION_PROBE")
    validate_full_evaluation_result(evaluation, require_accept=True)

    historical_plan_target = Path(str(evaluation.get("plan_path") or "")).expanduser().resolve()
    if not historical_plan_target.is_file():
        raise ValueError("historical evaluation plan is missing")
    if sha256_file(historical_plan_target) != evaluation.get("plan_file_sha256"):
        raise ValueError("historical evaluation plan file hash mismatch")
    validation = validate_historical_basis_v2_plan(
        historical_plan_target,
        str(evaluation.get("plan_hash") or ""),
    )
    historical_plan = _read_json(historical_plan_target)
    runtime_snapshot = require_plan_runtime_code_snapshot(
        historical_plan,
        runtime_code_path=__file__,
    )
    require_plan_code_snapshot(historical_plan, dict(evaluation.get("code_provenance") or {}))
    if validation["plan_hash"] != evaluation.get("plan_hash"):
        raise ValueError("historical evaluation and plan hash mismatch")
    return evaluation, evaluation_target, historical_plan, historical_plan_target


def _probe_candidates(
    evaluation: Mapping[str, Any],
    historical_plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    trade_counts: dict[str, int] = {}
    for row in evaluation.get("normal_trades") or []:
        if not isinstance(row, Mapping):
            continue
        base = str(row.get("base") or "").strip().upper()
        if base:
            trade_counts[base] = trade_counts.get(base, 0) + 1
    candidates_by_base = {
        str(row.get("base") or "").strip().upper(): dict(row)
        for row in (historical_plan.get("universe") or {}).get("candidates") or []
        if isinstance(row, Mapping) and str(row.get("base") or "").strip()
    }
    ordered_bases = sorted(trade_counts, key=lambda base: (-trade_counts[base], base))
    ordered_bases.extend(base for base in sorted(candidates_by_base) if base not in ordered_bases)
    selected = [candidates_by_base[base] for base in ordered_bases if base in candidates_by_base][:10]
    if not selected:
        raise ValueError("execution probe has no historical candidates")
    for row in selected:
        if not row.get("mexc_symbol") or not row.get("gateio_symbol"):
            raise ValueError(f"execution probe candidate is missing venue symbols: {row.get('base')}")
    return selected


def build_execution_probe_plan(
    evaluation_path: str | Path,
    output_path: str | Path,
    *,
    first_window_start_utc: str | None = None,
    duration_sec: int = WINDOW_DURATION_SEC,
    interval_sec: int = SAMPLE_INTERVAL_SEC,
) -> dict[str, Any]:
    if int(duration_sec) != WINDOW_DURATION_SEC or int(interval_sec) != SAMPLE_INTERVAL_SEC:
        raise ValueError("execution probe duration/interval are frozen at 1200/5 seconds")
    evaluation, evaluation_target, historical_plan, historical_plan_target = (
        _validate_historical_evaluation(evaluation_path)
    )
    first = (
        _parse_utc(first_window_start_utc)
        if first_window_start_utc
        else datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    )
    windows = [
        {
            "index": index,
            "start_utc": (first + timedelta(seconds=WINDOW_START_SEPARATION_SEC * index)).isoformat(),
            "end_utc": (
                first
                + timedelta(seconds=WINDOW_START_SEPARATION_SEC * index + WINDOW_DURATION_SEC)
            ).isoformat(),
        }
        for index in range(WINDOW_COUNT)
    ]
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_evaluation": {
            "path": str(evaluation_target),
            "file_sha256": sha256_file(evaluation_target),
            "deterministic_result_hash": evaluation["deterministic_result_hash"],
        },
        "historical_plan": {
            "path": str(historical_plan_target),
            "file_sha256": sha256_file(historical_plan_target),
        },
        "historical_plan_hash": evaluation["plan_hash"],
        "code_provenance": historical_plan["code_provenance"],
        "candidates": _probe_candidates(evaluation, historical_plan),
        "windows": windows,
        "duration_sec": WINDOW_DURATION_SEC,
        "interval_sec": SAMPLE_INTERVAL_SEC,
        "notional_quote_per_leg": float(historical_plan["economics"]["notional_quote_per_leg"]),
        "entry_threshold_bps": float(historical_plan["strategy"]["entry_threshold_bps"]),
        "minimum_valid_snapshots_per_base_per_window": 180,
        "minimum_coverage_per_base": 0.80,
        "maximum_timestamp_skew_ms": 2_000.0,
        "minimum_capacity_quote_per_leg": 500.0,
        "maximum_p95_impact_bps": 10.0,
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "grid_search": False,
            "retune": False,
        },
        "maximum_authority": "PAPER_FORWARD_PLANONLY",
        "next_allowed_command": "fast-edge-basis-v2-execution-probe -WindowIndex 0",
    }
    plan["probe_plan_hash"] = artifact_hash(plan)
    _write_json_immutable(output_path, plan)
    return plan


def validate_execution_probe_plan(
    path: str | Path,
    expected_probe_plan_hash: str | None = None,
) -> dict[str, Any]:
    plan = _read_json(path)
    _validate_hashed_artifact(
        plan,
        expected_schema=PLAN_SCHEMA,
        hash_field="probe_plan_hash",
        label="execution probe plan",
    )
    if plan.get("mode") != "PlanOnly":
        raise ValueError("execution probe plan must be PlanOnly")
    if expected_probe_plan_hash and plan.get("probe_plan_hash") != expected_probe_plan_hash:
        raise ValueError("execution probe plan does not match expected hash")
    windows = plan.get("windows") or []
    if len(windows) != WINDOW_COUNT:
        raise ValueError("execution probe must contain exactly three windows")
    previous_start: datetime | None = None
    for expected_index, row in enumerate(windows):
        if int(row.get("index", -1)) != expected_index:
            raise ValueError("execution probe window indices must be contiguous")
        start = _parse_utc(str(row.get("start_utc") or ""))
        end = _parse_utc(str(row.get("end_utc") or ""))
        if int((end - start).total_seconds()) != WINDOW_DURATION_SEC:
            raise ValueError("execution probe window duration mismatch")
        if previous_start is not None and int((start - previous_start).total_seconds()) < WINDOW_START_SEPARATION_SEC:
            raise ValueError("execution probe windows must be separated by at least four hours")
        previous_start = start
    if int(plan.get("duration_sec") or 0) != WINDOW_DURATION_SEC:
        raise ValueError("execution probe duration mismatch")
    if int(plan.get("interval_sec") or 0) != SAMPLE_INTERVAL_SEC:
        raise ValueError("execution probe interval mismatch")
    safety = plan.get("safety") or {}
    if any(bool(safety.get(key)) for key in ("live_orders", "private_api_keys", "leverage_or_margin", "grid_search", "retune")):
        raise ValueError("execution probe safety contract was loosened")
    historical_reference = plan.get("historical_evaluation") or {}
    evaluation_path = Path(str(historical_reference.get("path") or "")).expanduser().resolve()
    if not evaluation_path.is_file():
        raise ValueError("execution probe historical evaluation is missing")
    if sha256_file(evaluation_path) != historical_reference.get("file_sha256"):
        raise ValueError("execution probe historical evaluation file hash mismatch")
    evaluation, _evaluation_target, historical_plan, historical_plan_target = (
        _validate_historical_evaluation(evaluation_path)
    )
    if historical_reference.get("deterministic_result_hash") != evaluation.get(
        "deterministic_result_hash"
    ):
        raise ValueError("execution probe historical evaluation result hash mismatch")
    historical_plan_reference = plan.get("historical_plan") or {}
    if Path(str(historical_plan_reference.get("path") or "")).expanduser().resolve() != historical_plan_target:
        raise ValueError("execution probe historical plan path mismatch")
    if historical_plan_reference.get("file_sha256") != sha256_file(historical_plan_target):
        raise ValueError("execution probe historical plan file hash mismatch")
    if plan.get("historical_plan_hash") != historical_plan.get("plan_hash"):
        raise ValueError("execution probe historical plan hash mismatch")
    if (plan.get("code_provenance") or {}).get("code_snapshot_hash") != (
        historical_plan.get("code_provenance") or {}
    ).get("code_snapshot_hash"):
        raise ValueError("execution probe code provenance mismatch")
    historical_candidates = {
        str(row.get("base") or "").upper(): row
        for row in (historical_plan.get("universe") or {}).get("candidates") or []
        if isinstance(row, Mapping)
    }
    for candidate in plan.get("candidates") or []:
        base = str(candidate.get("base") or "").upper()
        if base not in historical_candidates or dict(candidate) != dict(historical_candidates[base]):
            raise ValueError(f"execution probe candidate provenance mismatch: {base}")
    require_plan_runtime_code_snapshot(plan, runtime_code_path=__file__)
    return plan


def _sample_metrics(
    rows: Iterable[Mapping[str, Any]],
    *,
    plan: Mapping[str, Any],
    window_index: int,
    expected_cycles: int,
) -> dict[str, Any]:
    candidate_bases = [str(row["base"]).upper() for row in plan["candidates"]]
    accumulators: dict[str, dict[str, Any]] = {
        base: {
            "observed": 0,
            "valid": 0,
            "impacts": [],
            "capacities": [],
            "skews": [],
            "qualifying": 0,
        }
        for base in candidate_bases
    }
    seen: set[tuple[str, int]] = set()
    total_rows = 0
    for row in rows:
        if row.get("schema") != SAMPLE_SCHEMA:
            raise ValueError("unexpected execution probe sample schema")
        if int(row.get("window_index", -1)) != int(window_index):
            raise ValueError("execution probe sample window mismatch")
        base = str(row.get("base") or "").upper()
        if base not in accumulators:
            raise ValueError(f"execution probe sample base is outside plan: {base}")
        cycle = int(row.get("cycle") or 0)
        if not 1 <= cycle <= expected_cycles:
            raise ValueError("execution probe sample cycle is outside expected range")
        identity = (base, cycle)
        if identity in seen:
            raise ValueError(f"duplicate execution probe sample: {base}/{cycle}")
        seen.add(identity)
        total_rows += 1
        bucket = accumulators[base]
        bucket["observed"] += 1
        long_execution = row.get("long_execution") or {}
        short_execution = row.get("short_execution") or {}
        valid = bool(
            row.get("valid")
            and long_execution.get("filled")
            and short_execution.get("filled")
        )
        if not valid:
            continue
        try:
            impact = max(
                float(long_execution["impact_bps"]),
                float(short_execution["impact_bps"]),
            )
            capacity = min(
                float(long_execution["capacity_quote_at_max_impact"]),
                float(short_execution["capacity_quote_at_max_impact"]),
            )
            skew = float(row["timestamp_skew_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid execution probe sample metrics: {base}/{cycle}") from exc
        if not all(math.isfinite(value) and value >= 0 for value in (impact, capacity, skew)):
            raise ValueError(f"non-finite execution probe sample metrics: {base}/{cycle}")
        bucket["valid"] += 1
        bucket["impacts"].append(impact)
        bucket["capacities"].append(capacity)
        bucket["skews"].append(skew)
        if row.get("qualifying"):
            bucket["qualifying"] += 1

    per_base: dict[str, dict[str, Any]] = {}
    eligible_bases: list[str] = []
    for base in candidate_bases:
        bucket = accumulators[base]
        valid_count = int(bucket["valid"])
        coverage = valid_count / expected_cycles if expected_cycles else 0.0
        p95_impact = _p95(bucket["impacts"])
        p95_skew = _p95(bucket["skews"])
        minimum_capacity = min(bucket["capacities"], default=None)
        reasons: list[str] = []
        if valid_count < int(plan["minimum_valid_snapshots_per_base_per_window"]):
            reasons.append("valid_snapshots")
        if coverage < float(plan["minimum_coverage_per_base"]):
            reasons.append("coverage")
        if p95_skew is None or p95_skew > float(plan["maximum_timestamp_skew_ms"]):
            reasons.append("timestamp_skew")
        if minimum_capacity is None or minimum_capacity < float(plan["minimum_capacity_quote_per_leg"]):
            reasons.append("capacity")
        if p95_impact is None or p95_impact > float(plan["maximum_p95_impact_bps"]):
            reasons.append("impact")
        passed = not reasons
        if passed:
            eligible_bases.append(base)
        per_base[base] = {
            "observed_snapshots": int(bucket["observed"]),
            "valid_snapshots": valid_count,
            "coverage": coverage,
            "p95_timestamp_skew_ms": p95_skew,
            "minimum_capacity_quote_per_leg": minimum_capacity,
            "p95_impact_bps": p95_impact,
            "qualifying_event_count": int(bucket["qualifying"]),
            "passed": passed,
            "rejection_reasons": reasons,
        }
    return {
        "expected_cycles": expected_cycles,
        "sample_row_count": total_rows,
        "per_base": per_base,
        "eligible_bases": sorted(eligible_bases),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            rows.append(payload)
    return rows


def finalize_execution_probe_window(
    probe_plan_path: str | Path,
    *,
    expected_probe_plan_hash: str,
    window_index: int,
    samples_path: str | Path,
    manifest_path: str | Path,
    completed_cycles: int,
    expected_cycles: int,
    errors: Sequence[str],
    critical_errors: Sequence[str] = (),
    runtime_sec: float = 0.0,
    code_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    plan = validate_execution_probe_plan(probe_plan_path, expected_probe_plan_hash)
    if not 0 <= int(window_index) < WINDOW_COUNT:
        raise ValueError("window_index must be 0, 1 or 2")
    expected_from_plan = int(plan["duration_sec"]) // int(plan["interval_sec"])
    if int(expected_cycles) != expected_from_plan:
        raise ValueError("execution probe expected cycle count mismatch")
    if not 0 <= int(completed_cycles) <= int(expected_cycles):
        raise ValueError("execution probe completed cycle count is invalid")
    samples_target = Path(samples_path).expanduser().resolve()
    if not samples_target.is_file():
        raise ValueError("execution probe samples are missing")
    window_metrics = _sample_metrics(
        _read_jsonl(samples_target),
        plan=plan,
        window_index=int(window_index),
        expected_cycles=int(expected_cycles),
    )
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final": int(completed_cycles) == int(expected_cycles),
        "probe_plan": {
            "path": str(Path(probe_plan_path).expanduser().resolve()),
            "file_sha256": sha256_file(probe_plan_path),
            "probe_plan_hash": plan["probe_plan_hash"],
        },
        "window_index": int(window_index),
        "expected_cycles": int(expected_cycles),
        "completed_cycles": int(completed_cycles),
        "samples": {
            "path": str(samples_target),
            "file_sha256": sha256_file(samples_target),
        },
        "window_metrics": window_metrics,
        "error_count": len(errors),
        "errors": list(errors),
        "critical_error_count": len(critical_errors),
        "critical_errors": list(critical_errors),
        "runtime_sec": round(float(runtime_sec), 6),
        "code_provenance": dict(code_provenance or plan["code_provenance"]),
        "live_orders": False,
        "private_api_keys": False,
    }
    manifest["deterministic_result_hash"] = artifact_hash(manifest)
    _write_json_immutable(manifest_path, manifest)
    return manifest


def _validate_probe_manifest(
    path: str | Path,
    *,
    plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_target = Path(path).expanduser().resolve()
    manifest = _read_json(manifest_target)
    _validate_hashed_artifact(
        manifest,
        expected_schema=MANIFEST_SCHEMA,
        label="execution probe manifest",
    )
    if not manifest.get("final"):
        raise ValueError("execution probe manifest is not final")
    expected_cycles = int(plan["duration_sec"]) // int(plan["interval_sec"])
    if (
        int(manifest.get("expected_cycles") or 0) != expected_cycles
        or int(manifest.get("completed_cycles") or 0) != expected_cycles
    ):
        raise ValueError("execution probe completed cycle count mismatch")
    plan_reference = manifest.get("probe_plan") or {}
    if plan_reference.get("probe_plan_hash") != plan.get("probe_plan_hash"):
        raise ValueError("execution probe manifest belongs to another plan")
    if plan_reference.get("file_sha256") != sha256_file(plan_reference.get("path") or ""):
        raise ValueError("execution probe manifest plan provenance mismatch")
    samples_reference = manifest.get("samples") or {}
    samples_target = Path(str(samples_reference.get("path") or "")).expanduser().resolve()
    if not samples_target.is_file() or sha256_file(samples_target) != samples_reference.get("file_sha256"):
        raise ValueError("execution probe sample provenance mismatch")
    require_plan_code_snapshot(plan, dict(manifest.get("code_provenance") or {}))
    recomputed = _sample_metrics(
        _read_jsonl(samples_target),
        plan=plan,
        window_index=int(manifest.get("window_index", -1)),
        expected_cycles=int(manifest.get("expected_cycles") or 0),
    )
    if recomputed != manifest.get("window_metrics"):
        raise ValueError("execution probe manifest metrics do not match raw samples")
    return manifest, recomputed


def build_execution_probe_report(
    *,
    evaluation_path: str | Path,
    probe_plan_path: str | Path,
    manifest_paths: Iterable[str | Path],
    output_path: str | Path,
) -> dict[str, Any]:
    evaluation, evaluation_target, _historical_plan, _historical_plan_target = (
        _validate_historical_evaluation(evaluation_path)
    )
    probe_plan_target = Path(probe_plan_path).expanduser().resolve()
    plan = validate_execution_probe_plan(probe_plan_target)
    historical_reference = plan.get("historical_evaluation") or {}
    if historical_reference.get("file_sha256") != sha256_file(evaluation_target):
        raise ValueError("probe plan historical evaluation file hash mismatch")
    if historical_reference.get("deterministic_result_hash") != evaluation.get("deterministic_result_hash"):
        raise ValueError("probe plan historical evaluation result hash mismatch")
    if plan.get("historical_plan_hash") != evaluation.get("plan_hash"):
        raise ValueError("probe plan historical plan hash mismatch")

    paths = [Path(path).expanduser().resolve() for path in manifest_paths]
    if len(paths) != WINDOW_COUNT:
        raise ValueError("exactly three distinct probe windows are required")
    rows = [_validate_probe_manifest(path, plan=plan) for path in paths]
    indices = sorted(int(manifest["window_index"]) for manifest, _metrics in rows)
    if indices != [0, 1, 2]:
        raise ValueError("exactly three distinct probe windows are required")
    manifest_targets_by_index = {
        int(manifest["window_index"]): path
        for path, (manifest, _metrics) in zip(paths, rows)
    }
    ordered = sorted(rows, key=lambda item: int(item[0]["window_index"]))

    eligible_sets = [set(metrics["eligible_bases"]) for _manifest, metrics in ordered]
    eligible_bases = sorted(set.intersection(*eligible_sets)) if eligible_sets else []
    qualifying_bases = sorted(
        base
        for base in eligible_bases
        if any(
            int(metrics["per_base"][base]["qualifying_event_count"]) > 0
            for _manifest, metrics in ordered
        )
    )
    rejection_reasons: list[str] = []
    for manifest, _metrics in ordered:
        if int(manifest.get("critical_error_count") or 0) > 0:
            rejection_reasons.append(f"window_{manifest['window_index']}:critical_errors")
    if not eligible_bases:
        rejection_reasons.append("no_base_passed_all_three_execution_windows")

    if rejection_reasons:
        verdict = "REJECT"
        next_command = "close-hypothesis-without-retune"
    elif qualifying_bases:
        verdict = "PAPER_FORWARD_READY"
        next_command = "fast-edge-basis-v2-paper-plan"
    else:
        verdict = "HISTORICAL_ACCEPT_AWAIT_EVENT"
        next_command = "wait-for-materially-new-qualifying-event"
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_evaluation": {
            "path": str(evaluation_target),
            "file_sha256": sha256_file(evaluation_target),
            "deterministic_result_hash": evaluation["deterministic_result_hash"],
            "verdict": evaluation["verdict"],
        },
        "probe_plan": {
            "path": str(probe_plan_target),
            "file_sha256": sha256_file(probe_plan_target),
            "probe_plan_hash": plan["probe_plan_hash"],
        },
        "windows": [
            {
                "index": int(manifest["window_index"]),
                "manifest_path": str(manifest_targets_by_index[int(manifest["window_index"])]),
                "manifest_file_sha256": sha256_file(
                    manifest_targets_by_index[int(manifest["window_index"])]
                ),
                "manifest_result_hash": manifest["deterministic_result_hash"],
                "metrics": metrics,
                "critical_error_count": int(manifest.get("critical_error_count") or 0),
            }
            for manifest, metrics in ordered
        ],
        "execution_eligible_bases": eligible_bases,
        "qualifying_execution_eligible_bases": qualifying_bases,
        "verdict": verdict,
        "rejection_reasons": rejection_reasons,
        "maximum_authority": "PAPER_FORWARD_PLANONLY",
        "safety": {
            "research_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "grid_search": False,
            "retune": False,
        },
        "next_allowed_command": next_command,
    }
    report["deterministic_result_hash"] = artifact_hash(report)
    _write_json_immutable(output_path, report)
    return report


def _publish_probe_gate(
    gate_path: Path,
    *,
    status: str,
    run_id: str,
    samples_path: Path,
    manifest_path: Path,
    snapshot: Mapping[str, Any],
    window_index: int,
    failure: str | None = None,
) -> None:
    final = status == "READY_FOR_POSTPROCESS"
    payload: dict[str, Any] = {
        "schema": "active_run_gate_v2",
        "project": "trading_mvp",
        "run_id": run_id,
        "status": status,
        "gate_status": status,
        "final": final,
        "collector_pid": os.getpid() if status == "RUNNING" else None,
        "process_ids": [os.getpid()] if status == "RUNNING" else [],
        "output": {"path": str(samples_path), "kind": "file"},
        "manifest_path": str(manifest_path),
        "locks": ["market_data_writer"],
        "owner_output_prefix": str(samples_path.parent),
        "code_snapshot_hash": snapshot.get("code_snapshot_hash"),
        "code_snapshot_manifest": snapshot.get("code_snapshot_manifest"),
        "parallel_safe_actions": [
            "code_work",
            "unit_tests",
            "fixtures",
            "static_analysis",
            "immutable_cache_compute",
        ],
        "forbidden_overlapping_actions": [
            "collector",
            "probe",
            "consumer_of_owner_output",
            "postprocess",
            "grid_search",
        ],
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders_allowed": False,
        "window_index": int(window_index),
        "failure": failure,
        "next_goal_decision": {
            "READY_FOR_POSTPROCESS": "BASIS_V2_EXECUTION_PROBE_WINDOW_READY",
            "STOPPED_INCOMPLETE": "BASIS_V2_EXECUTION_PROBE_STOPPED_INCOMPLETE",
        }.get(status, "BASIS_V2_EXECUTION_PROBE_RUNNING"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    publish_owned_run_gate(gate_path, payload, run_type="historical_basis_v2_execution_probe")


def _fetch_tickers(clients: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        mexc_future = executor.submit(clients["mexc"].fetch_ticker_map_fresh)
        gate_future = executor.submit(clients["gateio"].fetch_ticker_map_fresh)
        return mexc_future.result(), gate_future.result()


def _fetch_books(
    clients: Mapping[str, Any],
    mexc_symbol: str,
    gateio_symbol: str,
) -> tuple[dict[str, Any], float, dict[str, Any], float]:
    def fetch(client: Any, symbol: str) -> tuple[dict[str, Any], float]:
        book = client.fetch_depth(symbol)
        return book, time.time()

    with ThreadPoolExecutor(max_workers=2) as executor:
        mexc_future = executor.submit(fetch, clients["mexc"], mexc_symbol)
        gate_future = executor.submit(fetch, clients["gateio"], gateio_symbol)
        mexc_book, mexc_at = mexc_future.result()
        gate_book, gate_at = gate_future.result()
    return mexc_book, mexc_at, gate_book, gate_at


def collect_execution_probe_window(
    probe_plan_path: str | Path,
    *,
    expected_probe_plan_hash: str,
    window_index: int,
    samples_path: str | Path,
    manifest_path: str | Path,
    max_runtime_sec: int = 1_800,
    clients: Mapping[str, Any] | None = None,
    active_gate_path: str | Path | None = None,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    runtime_limit = validate_runtime_sec(max_runtime_sec)
    if runtime_limit < WINDOW_DURATION_SEC or runtime_limit > 1_800:
        raise ValueError("execution probe MaxRuntimeSec must be in [1200, 1800]")
    plan = validate_execution_probe_plan(probe_plan_path, expected_probe_plan_hash)
    snapshot = validate_basis_code_snapshot_reference(
        code_snapshot_hash,
        code_snapshot_manifest,
        fallback_code_path=__file__,
    )
    require_plan_code_snapshot(plan, snapshot)
    if not 0 <= int(window_index) < WINDOW_COUNT:
        raise ValueError("window_index must be 0, 1 or 2")

    samples_target = Path(samples_path).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    if samples_target.exists() or manifest_target.exists():
        raise FileExistsError("execution probe artifacts already exist")
    samples_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    gate_target = Path(active_gate_path).expanduser().resolve() if active_gate_path else None
    owned_run_id = (
        str(run_id).strip()
        if run_id is not None and str(run_id).strip()
        else f"basis_v2_probe_{plan['probe_plan_hash'][:12]}_w{window_index}"
    )
    window = plan["windows"][int(window_index)]
    start_at = _parse_utc(window["start_utc"])
    end_at = _parse_utc(window["end_utc"])
    now = datetime.now(timezone.utc)
    if now >= end_at:
        raise ValueError("execution probe window has already ended")
    wait_sec = max(0.0, (start_at - now).total_seconds())
    if wait_sec + WINDOW_DURATION_SEC > runtime_limit:
        raise ValueError("MaxRuntimeSec does not cover countdown plus frozen probe window")
    if now > start_at + timedelta(seconds=SAMPLE_INTERVAL_SEC):
        raise ValueError("execution probe window start was missed")

    if gate_target is not None:
        _publish_probe_gate(
            gate_target,
            status="RUNNING",
            run_id=owned_run_id,
            samples_path=samples_target,
            manifest_path=manifest_target,
            snapshot=snapshot,
            window_index=int(window_index),
        )
    started_monotonic = time.monotonic()
    errors: list[str] = []
    critical_errors: list[str] = []
    expected_cycles = WINDOW_DURATION_SEC // SAMPLE_INTERVAL_SEC
    completed_cycles = 0
    clients = clients or {
        "mexc": MexcBasisProbeClient(),
        "gateio": GateBasisProbeClient(),
    }
    try:
        while datetime.now(timezone.utc) < start_at:
            remaining = max(0.0, (start_at - datetime.now(timezone.utc)).total_seconds())
            print(
                f"PROBE_COUNTDOWN window={window_index} remaining_sec={remaining:.1f}",
                flush=True,
            )
            time.sleep(min(10.0, remaining))

        with samples_target.open("x", encoding="utf-8", buffering=1) as handle:
            for cycle in range(1, expected_cycles + 1):
                target_at = start_at + timedelta(seconds=(cycle - 1) * SAMPLE_INTERVAL_SEC)
                now = datetime.now(timezone.utc)
                if now < target_at:
                    time.sleep((target_at - now).total_seconds())
                completed_cycles = cycle
                try:
                    mexc_tickers, gate_tickers = _fetch_tickers(clients)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"cycle={cycle}:ticker:{type(exc).__name__}:{exc}")
                    print(
                        f"PROBE window={window_index} cycle={cycle}/{expected_cycles} "
                        f"rows=0 errors={len(errors)}",
                        flush=True,
                    )
                    continue
                rows_written = 0
                for candidate in plan["candidates"]:
                    base = str(candidate["base"]).upper()
                    mexc_symbol = str(candidate["mexc_symbol"])
                    gateio_symbol = str(candidate["gateio_symbol"])
                    try:
                        mexc_mark, mexc_index = _ticker_prices(
                            "mexc", mexc_tickers.get(mexc_symbol, {})
                        )
                        gate_mark, gate_index = _ticker_prices(
                            "gateio", gate_tickers.get(gateio_symbol, {})
                        )
                        mexc_basis = _basis(mexc_mark, mexc_index)
                        gate_basis = _basis(gate_mark, gate_index)
                        if mexc_basis is None or gate_basis is None:
                            raise ValueError("mark/index price is missing")
                        mexc_book, mexc_at, gate_book, gate_at = _fetch_books(
                            clients,
                            mexc_symbol,
                            gateio_symbol,
                        )
                        if mexc_basis < gate_basis:
                            long_venue, short_venue = "mexc", "gateio"
                        else:
                            long_venue, short_venue = "gateio", "mexc"
                        long_book = mexc_book if long_venue == "mexc" else gate_book
                        short_book = gate_book if short_venue == "gateio" else mexc_book
                        long_execution = depth_execution_metrics(
                            long_book["asks"],
                            side="buy",
                            notional_quote=float(plan["notional_quote_per_leg"]),
                            max_impact_bps=float(plan["maximum_p95_impact_bps"]),
                        )
                        short_execution = depth_execution_metrics(
                            short_book["bids"],
                            side="sell",
                            notional_quote=float(plan["notional_quote_per_leg"]),
                            max_impact_bps=float(plan["maximum_p95_impact_bps"]),
                        )
                        valid = bool(long_execution["filled"] and short_execution["filled"])
                        spread = abs(mexc_basis - gate_basis)
                        row = {
                            "schema": SAMPLE_SCHEMA,
                            "window_index": int(window_index),
                            "cycle": cycle,
                            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                            "base": base,
                            "long_venue": long_venue,
                            "short_venue": short_venue,
                            "mexc_basis_bps": mexc_basis,
                            "gateio_basis_bps": gate_basis,
                            "basis_spread_bps": spread,
                            "timestamp_skew_ms": abs(mexc_at - gate_at) * 1_000.0,
                            "long_execution": long_execution,
                            "short_execution": short_execution,
                            "valid": valid,
                            "qualifying": bool(
                                valid and spread >= float(plan["entry_threshold_bps"])
                            ),
                        }
                        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        rows_written += 1
                    except (KeyError, TypeError, ValueError) as exc:
                        message = f"cycle={cycle}:base={base}:schema:{type(exc).__name__}:{exc}"
                        critical_errors.append(message)
                        if len(critical_errors) <= 100:
                            errors.append(message)
                    except Exception as exc:  # noqa: BLE001
                        message = f"cycle={cycle}:base={base}:network:{type(exc).__name__}:{exc}"
                        if len(errors) < 100:
                            errors.append(message)
                elapsed = time.monotonic() - started_monotonic
                eta = max(0, expected_cycles - cycle) * SAMPLE_INTERVAL_SEC
                print(
                    f"PROBE window={window_index} cycle={cycle}/{expected_cycles} "
                    f"rows={rows_written} errors={len(errors)} critical={len(critical_errors)} "
                    f"elapsed_sec={elapsed:.1f} eta_sec={eta}",
                    flush=True,
                )
        manifest = finalize_execution_probe_window(
            probe_plan_path,
            expected_probe_plan_hash=expected_probe_plan_hash,
            window_index=int(window_index),
            samples_path=samples_target,
            manifest_path=manifest_target,
            completed_cycles=completed_cycles,
            expected_cycles=expected_cycles,
            errors=errors,
            critical_errors=critical_errors,
            runtime_sec=time.monotonic() - started_monotonic,
            code_provenance=snapshot,
        )
        if gate_target is not None:
            _publish_probe_gate(
                gate_target,
                status="READY_FOR_POSTPROCESS",
                run_id=owned_run_id,
                samples_path=samples_target,
                manifest_path=manifest_target,
                snapshot=snapshot,
                window_index=int(window_index),
            )
        return manifest
    except Exception as exc:
        if gate_target is not None:
            _publish_probe_gate(
                gate_target,
                status="STOPPED_INCOMPLETE",
                run_id=owned_run_id,
                samples_path=samples_target,
                manifest_path=manifest_target,
                snapshot=snapshot,
                window_index=int(window_index),
                failure=f"{type(exc).__name__}: {exc}",
            )
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Historical basis v2 execution-capacity probe")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--evaluation", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--first-window-start-utc")

    validate_parser = subparsers.add_parser("validate-plan")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash", required=True)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--plan", required=True)
    collect_parser.add_argument("--expected-plan-hash", required=True)
    collect_parser.add_argument("--window-index", type=int, choices=(0, 1, 2), required=True)
    collect_parser.add_argument("--samples", required=True)
    collect_parser.add_argument("--manifest", required=True)
    collect_parser.add_argument("--max-runtime-sec", type=int, default=1_800)
    collect_parser.add_argument("--active-run-gate")
    collect_parser.add_argument("--code-snapshot-hash")
    collect_parser.add_argument("--code-snapshot-manifest")
    collect_parser.add_argument("--run-id")

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--evaluation", required=True)
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--expected-plan-hash", required=True)
    evaluate_parser.add_argument("--manifests", required=True)
    evaluate_parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan":
        result = build_execution_probe_plan(
            args.evaluation,
            args.output,
            first_window_start_utc=args.first_window_start_utc,
        )
    elif args.command == "validate-plan":
        plan = validate_execution_probe_plan(args.plan, args.expected_plan_hash)
        result = {
            "schema": "trading_mvp_historical_basis_v2_execution_probe_validation_v1",
            "decision": "PROBE_PLAN_VALID",
            "probe_plan_hash": plan["probe_plan_hash"],
            "candidate_count": len(plan["candidates"]),
            "window_count": len(plan["windows"]),
            "duration_sec": plan["duration_sec"],
            "interval_sec": plan["interval_sec"],
        }
    elif args.command == "collect":
        result = collect_execution_probe_window(
            args.plan,
            expected_probe_plan_hash=args.expected_plan_hash,
            window_index=args.window_index,
            samples_path=args.samples,
            manifest_path=args.manifest,
            max_runtime_sec=args.max_runtime_sec,
            active_gate_path=args.active_run_gate,
            code_snapshot_hash=args.code_snapshot_hash,
            code_snapshot_manifest=args.code_snapshot_manifest,
            run_id=args.run_id,
        )
    else:
        plan = validate_execution_probe_plan(args.plan, args.expected_plan_hash)
        result = build_execution_probe_report(
            evaluation_path=args.evaluation,
            probe_plan_path=args.plan,
            manifest_paths=[item.strip() for item in args.manifests.split(",") if item.strip()],
            output_path=args.output,
        )
        if result["probe_plan"]["probe_plan_hash"] != plan["probe_plan_hash"]:
            raise ValueError("execution probe report plan hash mismatch")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    _force_utf8_stdio()
    raise SystemExit(main())
