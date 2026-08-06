from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from continuous_production import resolve_run_window, validate_runtime_request


SCHEMA = "trading_mvp_dense_ws_campaign_feasibility_v1"
HYPOTHESIS_ID = "dense_ws_microstructure_regime_filter_v1"
DATA_TYPE = "DENSE_WS_SEGMENTED"


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    value = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {target}")
    return value


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite immutable artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _existing_ancestor(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise ValueError(f"no existing ancestor for path: {path}")
        candidate = parent
    return candidate


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _find_hypothesis(bank: dict[str, Any]) -> dict[str, Any]:
    hypotheses = bank.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("hypothesis bank must contain hypotheses")
    for hypothesis in hypotheses:
        if (
            isinstance(hypothesis, dict)
            and hypothesis.get("id") == HYPOTHESIS_ID
        ):
            if hypothesis.get("required_data_type") != DATA_TYPE:
                raise ValueError("dense WS hypothesis data type mismatch")
            if hypothesis.get("status") != "BANKED_NEEDS_NEW_DATA":
                raise ValueError("dense WS hypothesis is not banked for new data")
            return hypothesis
    raise ValueError(f"hypothesis not found: {HYPOTHESIS_ID}")


def _has_errors(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return bool(str(value).strip())


def _resolve_output_path(raw: Any, manifest_path: Path) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    local = manifest_path.parent / candidate.name
    return local.resolve() if local.is_file() else None


def inspect_prior_manifests(root: str | Path) -> dict[str, Any]:
    source = Path(root).expanduser().resolve()
    manifests = sorted(source.rglob("manifest.json")) if source.is_dir() else []
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for path in manifests:
        try:
            manifest = _read_json(path)
            requested = float(manifest.get("requested_duration_sec") or 0)
            actual = float(manifest.get("actual_duration_sec") or 0)
            results = manifest.get("results")
            if not isinstance(results, list):
                raise ValueError("results must be a list")
            exchanges = {
                str(item.get("exchange") or "").lower()
                for item in results
                if isinstance(item, dict)
                and int(item.get("events") or 0) > 0
                and not _has_errors(item.get("errors"))
            }
            reasons: list[str] = []
            if manifest.get("completed") is not True:
                reasons.append("not_completed")
            if manifest.get("final") is not True:
                reasons.append("not_final")
            if requested <= 0 or actual < requested * 0.95:
                reasons.append("duration_incomplete")
            if _has_errors(manifest.get("errors")):
                reasons.append("manifest_errors")
            if not {"mexc", "gateio"}.issubset(exchanges):
                reasons.append("dual_venue_missing")
            total_events = int(manifest.get("total_events") or 0)
            if total_events <= 0:
                reasons.append("no_events")
            if reasons:
                rejected.append(
                    {"path": str(path), "reason": ",".join(reasons)}
                )
                continue
            total_bytes = 0
            existing_outputs = 0
            for result in results:
                if not isinstance(result, dict):
                    continue
                output = _resolve_output_path(result.get("output"), path)
                if output is not None:
                    total_bytes += output.stat().st_size
                    existing_outputs += 1
            valid.append(
                {
                    "path": str(path),
                    "duration_sec": actual,
                    "total_events": total_events,
                    "events_per_sec": total_events / actual,
                    "bytes_per_sec": (
                        total_bytes / actual if total_bytes > 0 else None
                    ),
                    "existing_output_files": existing_outputs,
                    "exchanges": sorted(exchanges),
                }
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            rejected.append(
                {"path": str(path), "reason": f"{type(exc).__name__}: {exc}"}
            )

    event_rates = [item["events_per_sec"] for item in valid]
    byte_rates = [
        item["bytes_per_sec"]
        for item in valid
        if item["bytes_per_sec"] is not None
    ]
    return {
        "source_root": str(source),
        "manifests_seen": len(manifests),
        "valid_dual_venue_segments": len(valid),
        "rejected_segments": len(rejected),
        "median_events_per_sec": (
            statistics.median(event_rates) if event_rates else 0.0
        ),
        "median_bytes_per_sec": (
            statistics.median(byte_rates) if byte_rates else None
        ),
        "sample_segments": valid[:4],
        "rejection_sample": rejected[:8],
        "admissible_for_hypothesis_evidence": False,
        "use": "throughput_and_operational_feasibility_only",
    }


def _schedule_blackouts(
    schedule: dict[str, Any],
    *,
    campaign_start: datetime,
    hard_deadline: datetime,
    drain_sec: int,
    certification_sec: int,
    ignored_run_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    blackouts: list[dict[str, Any]] = []
    ignored = ignored_run_ids or set()
    for segment in schedule.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        run_id = str(segment.get("run_id") or "")
        if run_id in ignored:
            continue
        start = _parse_timestamp(
            segment.get("start_local"),
            label="schedule.segment.start_local",
        )
        end = _parse_timestamp(
            segment.get("end_local"),
            label="schedule.segment.end_local",
        )
        blackout_start = start - timedelta(seconds=drain_sec)
        blackout_end = end + timedelta(seconds=certification_sec)
        if blackout_end <= campaign_start or blackout_start >= hard_deadline:
            continue
        blackouts.append(
            {
                "run_id": run_id,
                "start_local": max(blackout_start, campaign_start).isoformat(),
                "end_local": min(blackout_end, hard_deadline).isoformat(),
                "pit_start_local": start.isoformat(),
                "pit_end_local": end.isoformat(),
            }
        )
    return sorted(blackouts, key=lambda item: item["start_local"])


def _allocate_phases(
    *,
    campaign_start: datetime,
    writer_target_sec: int,
    writer_deadline: datetime,
    hard_deadline: datetime,
    blackouts: list[dict[str, Any]],
    segment_sec: int,
    min_headroom_sec: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Allocate writer phases around blackout windows.

    Parameters
    ----------
    min_headroom_sec:
        Minimum startup/shutdown headroom to reserve at the end of each
        phase window.  When positive the writer duration for each phase is
        capped at ``window - min_headroom_sec`` instead of filling the full
        window.  Default ``0`` preserves the legacy exact-fill behaviour.
    """
    remaining = writer_target_sec
    cursor = campaign_start
    phases: list[dict[str, Any]] = []
    for blackout in blackouts:
        block_start = _parse_timestamp(
            blackout["start_local"],
            label="blackout.start_local",
        )
        block_end = _parse_timestamp(
            blackout["end_local"],
            label="blackout.end_local",
        )
        if cursor < block_start and remaining > 0:
            available = int((block_start - cursor).total_seconds())
            effective_available = max(0, available - min_headroom_sec)
            duration = min(remaining, effective_available)
            if duration > 0:
                phase_end = cursor + timedelta(seconds=duration)
                phases.append(
                    {
                        "phase_id": f"phase_{len(phases) + 1:02d}",
                        "start_local": cursor.isoformat(),
                        "end_local": phase_end.isoformat(),
                        "hard_end_local": min(
                            _parse_timestamp(
                                blackout["pit_start_local"],
                                label="blackout.pit_start_local",
                            ),
                            hard_deadline,
                        ).isoformat(),
                        "writer_duration_sec": duration,
                        "complete_durable_segments": duration // segment_sec,
                    }
                )
                remaining -= duration
                cursor = phase_end
        if remaining <= 0:
            break
        if cursor < block_end:
            cursor = block_end
    if remaining > 0 and cursor < writer_deadline:
        available_tail = max(
            0,
            int((writer_deadline - cursor).total_seconds()) - min_headroom_sec,
        )
        duration = min(remaining, available_tail)
        if duration > 0:
            phase_end = cursor + timedelta(seconds=duration)
            phases.append(
                {
                    "phase_id": f"phase_{len(phases) + 1:02d}",
                    "start_local": cursor.isoformat(),
                    "end_local": phase_end.isoformat(),
                    "hard_end_local": hard_deadline.isoformat(),
                    "writer_duration_sec": duration,
                    "complete_durable_segments": duration // segment_sec,
                }
            )
            remaining -= duration
    return phases, remaining


def _open_window_at(
    policy: dict[str, Any],
    moment: datetime,
) -> dict[str, Any]:
    window = resolve_run_window(
        policy,
        observed_at_utc=moment.astimezone(timezone.utc).isoformat(),
    )
    if window.get("status") != "OPEN":
        raise ValueError("requested start is outside an open run window")
    return window


def _next_open_window(
    policy: dict[str, Any],
    after: datetime,
) -> tuple[datetime, dict[str, Any]]:
    probe = resolve_run_window(
        policy,
        observed_at_utc=after.astimezone(timezone.utc).isoformat(),
    )
    if probe.get("status") == "OPEN":
        start = after
        return start, probe
    next_open = _parse_timestamp(
        probe.get("next_opens_at_local"),
        label="window.next_opens_at_local",
    )
    return next_open, _open_window_at(policy, next_open)


def _allocate_segmented_windows(
    *,
    policy: dict[str, Any],
    schedule: dict[str, Any],
    campaign_start: datetime,
    writer_target_sec: int,
    max_collection_windows: int,
    shutdown_grace_sec: int,
    drain_sec: int,
    certification_sec: int,
    segment_sec: int,
    min_phase_headroom_sec: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
]:
    remaining = writer_target_sec
    phases: list[dict[str, Any]] = []
    blackouts: list[dict[str, Any]] = []
    collection_windows: list[dict[str, Any]] = []
    window_start = campaign_start
    window = _open_window_at(policy, window_start)

    for index in range(max_collection_windows):
        hard_deadline = _parse_timestamp(
            window.get("hard_deadline_local"),
            label="window.hard_deadline_local",
        )
        writer_deadline = hard_deadline - timedelta(seconds=shutdown_grace_sec)
        window_blackouts = _schedule_blackouts(
            schedule,
            campaign_start=window_start,
            hard_deadline=writer_deadline,
            drain_sec=drain_sec,
            certification_sec=certification_sec,
        )
        window_phases, remaining = _allocate_phases(
            campaign_start=window_start,
            writer_target_sec=remaining,
            writer_deadline=writer_deadline,
            hard_deadline=hard_deadline,
            blackouts=window_blackouts,
            segment_sec=segment_sec,
            min_headroom_sec=min_phase_headroom_sec,
        )
        for phase in window_phases:
            phase["phase_id"] = f"phase_{len(phases) + 1:02d}"
            phases.append(phase)
        blackouts.extend(window_blackouts)
        collection_windows.append(
            {
                "sequence": index + 1,
                "window_id": window["window_id"],
                "window_type": window["window_type"],
                "writer_start_local": window_start.isoformat(),
                "writer_deadline_local": writer_deadline.isoformat(),
                "hard_deadline_local": hard_deadline.isoformat(),
            }
        )
        if remaining <= 0:
            break
        window_start, window = _next_open_window(policy, hard_deadline)

    return phases, blackouts, collection_windows, remaining


def build_feasibility(
    *,
    hypothesis_bank_path: str | Path,
    continuous_policy_path: str | Path,
    pit_schedule_path: str | Path,
    prior_manifest_root: str | Path,
    universe_path: str | Path,
    requested_start_local: str,
    output_path: str | Path,
    segment_sec: int = 3_600,
    drain_sec: int = 900,
    certification_sec: int = 1_200,
    target_writer_sec_override: int | None = None,
    min_phase_headroom_sec: int = 900,
) -> dict[str, Any]:
    if segment_sec <= 0:
        raise ValueError("segment_sec must be positive")
    bank_path = Path(hypothesis_bank_path).expanduser().resolve()
    policy_path = Path(continuous_policy_path).expanduser().resolve()
    schedule_path = Path(pit_schedule_path).expanduser().resolve()
    universe = Path(universe_path).expanduser().resolve()
    bank = _read_json(bank_path)
    policy = _read_json(policy_path)
    schedule = _read_json(schedule_path)
    hypothesis = _find_hypothesis(bank)
    minimum = hypothesis.get("minimum_data")
    if not isinstance(minimum, dict):
        raise ValueError("hypothesis minimum_data is missing")

    minimum_writer_sec = int(float(minimum.get("hours") or 0) * 3_600)
    target_writer_sec = (
        int(target_writer_sec_override)
        if target_writer_sec_override is not None
        else minimum_writer_sec
    )
    minimum_segments = int(minimum.get("valid_segments") or 0)
    minimum_coverage = float(minimum.get("dual_venue_coverage") or 0)
    minimum_snapshots = int(minimum.get("execution_snapshots") or 0)
    if minimum_writer_sec <= 0 or minimum_segments <= 0:
        raise ValueError("hypothesis minimum duration/segments are invalid")
    if target_writer_sec < minimum_writer_sec:
        raise ValueError("target writer duration cannot be below hypothesis minimum")
    if min_phase_headroom_sec < 0:
        raise ValueError("min_phase_headroom_sec cannot be negative")

    start = _parse_timestamp(
        requested_start_local,
        label="requested_start_local",
    )
    shutdown_grace_sec = int(
        (policy.get("runtime") or {}).get("shutdown_grace_sec") or 0
    )
    factory = policy.get("accelerated_evidence_factory") or {}
    max_collection_windows = int(
        factory.get("segmented_campaign_max_windows") or 1
    )
    if not 1 <= max_collection_windows <= 14:
        raise ValueError("segmented_campaign_max_windows must be in [1, 14]")

    exception = factory.get("continuous_evidence_exception") or {}
    exception_enabled = exception.get("enabled") is True
    exception_start = (
        _parse_timestamp(
            exception.get("start_local"),
            label="continuous_evidence_exception.start_local",
        )
        if exception_enabled
        else None
    )
    use_continuous_exception = exception_start == start
    uninterrupted_required = False
    suppressed_pit_run_ids: list[str] = []
    continuous_exception_reasons: list[str] = []
    collection_windows: list[dict[str, Any]] = []
    if use_continuous_exception:
        expected_writer_sec = int(exception.get("writer_duration_sec") or 0)
        if target_writer_sec != expected_writer_sec:
            raise ValueError(
                "continuous evidence exception writer duration does not match "
                "the requested target"
            )
        writer_deadline = _parse_timestamp(
            exception.get("writer_deadline_local"),
            label="continuous_evidence_exception.writer_deadline_local",
        )
        hard_deadline = _parse_timestamp(
            exception.get("hard_deadline_local"),
            label="continuous_evidence_exception.hard_deadline_local",
        )
        if writer_deadline != start + timedelta(seconds=target_writer_sec):
            raise ValueError(
                "continuous evidence exception writer deadline does not match "
                "start plus target duration"
            )
        if hard_deadline != writer_deadline + timedelta(
            seconds=shutdown_grace_sec
        ):
            raise ValueError(
                "continuous evidence exception hard deadline does not match "
                "the configured shutdown grace"
            )
        suppressed_pit_run_ids = sorted(
            {
                str(item).strip()
                for item in exception.get("suppressed_pit_run_ids") or []
                if str(item).strip()
            }
        )
        schedule_run_ids = {
            str(item.get("run_id") or "")
            for item in schedule.get("segments") or []
            if isinstance(item, dict)
        }
        unknown_suppressed = sorted(
            set(suppressed_pit_run_ids) - schedule_run_ids
        )
        if unknown_suppressed:
            raise ValueError(
                "continuous evidence exception suppresses unknown PIT runs: "
                + ",".join(unknown_suppressed)
            )
        blackouts = _schedule_blackouts(
            schedule,
            campaign_start=start,
            hard_deadline=writer_deadline,
            drain_sec=drain_sec,
            certification_sec=certification_sec,
            ignored_run_ids=set(suppressed_pit_run_ids),
        )
        uninterrupted_required = exception.get("uninterrupted_required") is True
        if uninterrupted_required and blackouts:
            continuous_exception_reasons.append(
                "continuous_evidence_exception_overlaps_pit_blackout"
            )
        phases, remaining = _allocate_phases(
            campaign_start=start,
            writer_target_sec=target_writer_sec,
            writer_deadline=writer_deadline,
            hard_deadline=hard_deadline,
            blackouts=blackouts,
            segment_sec=segment_sec,
            min_headroom_sec=0,
        )
        if uninterrupted_required and len(phases) != 1:
            continuous_exception_reasons.append(
                "continuous_evidence_exception_is_not_one_phase"
            )
        window_check = {
            "window_id": str(exception.get("window_id") or "").strip(),
            "window_type": "EVIDENCE_VALUE_EXCEPTION",
        }
        if not window_check["window_id"]:
            raise ValueError("continuous evidence exception window_id is missing")
        collection_windows = [
            {
                "sequence": 1,
                "window_id": window_check["window_id"],
                "window_type": window_check["window_type"],
                "writer_start_local": start.isoformat(),
                "writer_deadline_local": writer_deadline.isoformat(),
                "hard_deadline_local": hard_deadline.isoformat(),
            }
        ]
    elif max_collection_windows == 1:
        window_check = validate_runtime_request(
            policy,
            requested_start_local=start.isoformat(),
            expected_duration_sec=target_writer_sec,
            max_runtime_sec=target_writer_sec,
        )
        hard_deadline = _parse_timestamp(
            window_check["hard_deadline_local"],
            label="window.hard_deadline_local",
        )
        writer_deadline = hard_deadline - timedelta(seconds=shutdown_grace_sec)
        blackouts = _schedule_blackouts(
            schedule,
            campaign_start=start,
            hard_deadline=writer_deadline,
            drain_sec=drain_sec,
            certification_sec=certification_sec,
        )
        phases, remaining = _allocate_phases(
            campaign_start=start,
            writer_target_sec=target_writer_sec,
            writer_deadline=writer_deadline,
            hard_deadline=hard_deadline,
            blackouts=blackouts,
            segment_sec=segment_sec,
            min_headroom_sec=min_phase_headroom_sec,
        )
    else:
        phases, blackouts, collection_windows, remaining = (
            _allocate_segmented_windows(
                policy=policy,
                schedule=schedule,
                campaign_start=start,
                writer_target_sec=target_writer_sec,
                max_collection_windows=max_collection_windows,
                shutdown_grace_sec=shutdown_grace_sec,
                drain_sec=drain_sec,
                certification_sec=certification_sec,
                segment_sec=segment_sec,
                min_phase_headroom_sec=min_phase_headroom_sec,
            )
        )
        hard_deadline = _parse_timestamp(
            collection_windows[-1]["hard_deadline_local"],
            label="collection_window.hard_deadline_local",
        )
        writer_deadline = _parse_timestamp(
            collection_windows[-1]["writer_deadline_local"],
            label="collection_window.writer_deadline_local",
        )
        window_check = {
            "window_id": (
                f"SEGMENTED_{start.date().isoformat()}_"
                f"{hard_deadline.date().isoformat()}"
            ),
            "window_type": "SEGMENTED",
        }
    planned_writer_sec = target_writer_sec - remaining
    complete_segments = sum(
        int(phase["complete_durable_segments"]) for phase in phases
    )
    campaign_end = (
        _parse_timestamp(phases[-1]["end_local"], label="phase.end_local")
        if phases
        else start
    )

    prior = inspect_prior_manifests(prior_manifest_root)
    universe_rows = 0
    with universe.open("r", encoding="utf-8-sig", newline="") as handle:
        universe_rows = sum(1 for _ in csv.DictReader(handle))
    free_bytes = shutil.disk_usage(_existing_ancestor(output_path)).free
    median_events_per_sec = float(prior["median_events_per_sec"] or 0)
    median_bytes_per_sec = prior["median_bytes_per_sec"]
    estimated_events = int(median_events_per_sec * target_writer_sec)
    estimated_bytes = (
        int(float(median_bytes_per_sec) * target_writer_sec)
        if median_bytes_per_sec is not None
        else None
    )

    feasibility_reasons: list[str] = list(continuous_exception_reasons)
    if remaining > 0:
        feasibility_reasons.append("rolling_window_capacity_below_writer_target")
    if complete_segments < minimum_segments:
        feasibility_reasons.append("planned_complete_segments_below_minimum")
    if prior["valid_dual_venue_segments"] < 2:
        feasibility_reasons.append("insufficient_operational_throughput_samples")
    if median_events_per_sec <= 0:
        feasibility_reasons.append("event_throughput_not_observed")
    if estimated_bytes is None:
        feasibility_reasons.append("disk_throughput_not_observed")
    elif estimated_bytes * 2 > free_bytes:
        feasibility_reasons.append("disk_headroom_below_2x_estimate")
    hard_output_cap_bytes = int(
        (policy.get("accelerated_evidence_factory") or {}).get(
            "hard_campaign_output_cap_bytes"
        )
        or 0
    )
    if (
        hard_output_cap_bytes > 0
        and estimated_bytes is not None
        and estimated_bytes > hard_output_cap_bytes
    ):
        feasibility_reasons.append("estimated_output_exceeds_hard_campaign_cap")

    contract_gaps = [
        "freeze exact MEXC/Gate universe and its inclusion/exclusion rules",
        "freeze raw schema and segment-validity rules before collection",
        "freeze regime labels and feature timestamps before OOS",
        "freeze execution-snapshot sampling and stale-quote rules",
        "freeze acceptance, cost, risk and no-grid evaluation contract",
        "measure CPU and memory envelope in a bounded visible calibration",
        "create immutable multi-phase campaign plan and approval registry entry",
    ]
    verdict = (
        "INFEASIBLE_ON_CURRENT_WINDOW_OR_OPERATIONS"
        if feasibility_reasons
        else "FEASIBILITY_CONFIRMED_CONTRACT_FREEZE_REQUIRED"
    )

    frozen_candidate = {
        "hypothesis_id": HYPOTHESIS_ID,
        "data_type": DATA_TYPE,
        "requested_start_local": start.isoformat(),
        "window_id": window_check["window_id"],
        "window_type": window_check["window_type"],
        "hard_deadline_local": hard_deadline.isoformat(),
        "writer_deadline_local": writer_deadline.isoformat(),
        "target_writer_sec": target_writer_sec,
        "minimum_writer_sec": minimum_writer_sec,
        "segment_sec": segment_sec,
        "minimum_valid_segments": minimum_segments,
        "minimum_dual_venue_coverage": minimum_coverage,
        "minimum_execution_snapshots": minimum_snapshots,
        "pit_blackouts": blackouts,
        "phases": phases,
        "universe_path": str(universe),
        "universe_sha256": _sha256(universe),
        "universe_rows": universe_rows,
        "hypothesis_bank_sha256": _sha256(bank_path),
        "continuous_policy_sha256": _sha256(policy_path),
        "pit_schedule_sha256": _sha256(schedule_path),
    }
    if collection_windows:
        frozen_candidate["collection_windows"] = collection_windows
    if use_continuous_exception:
        frozen_candidate["uninterrupted_required"] = uninterrupted_required
        frozen_candidate["suppressed_pit_run_ids"] = suppressed_pit_run_ids
    result = {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "research_only": True,
        "would_start": False,
        "network_access": False,
        "returns_read": False,
        "pnl_computed": False,
        "oos_read": False,
        "grid_or_retune": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "hypothesis": {
            "id": HYPOTHESIS_ID,
            "status": hypothesis.get("status"),
            "required_data_type": DATA_TYPE,
            "thesis": hypothesis.get("thesis"),
            "minimum_data": minimum,
            "forbidden": hypothesis.get("forbidden") or [],
        },
        "window_feasibility": {
            "window_id": window_check["window_id"],
            "window_type": window_check["window_type"],
            "campaign_start_local": start.isoformat(),
            "campaign_end_local": campaign_end.isoformat(),
            "writer_deadline_local": writer_deadline.isoformat(),
            "hard_deadline_local": hard_deadline.isoformat(),
            "target_writer_sec": target_writer_sec,
            "minimum_writer_sec": minimum_writer_sec,
            "planned_writer_sec": planned_writer_sec,
            "unallocated_writer_sec": remaining,
            "complete_durable_segments": complete_segments,
            "phases": phases,
            "pit_blackouts": blackouts,
            "collection_windows": collection_windows,
            "uninterrupted_required": uninterrupted_required,
            "suppressed_pit_run_ids": suppressed_pit_run_ids,
        },
        "operational_baseline": prior,
        "resource_estimate": {
            "estimated_events": estimated_events,
            "estimated_disk_bytes": estimated_bytes,
            "disk_free_bytes_at_plan_time": free_bytes,
            "disk_headroom_multiplier": (
                round(free_bytes / estimated_bytes, 3)
                if estimated_bytes
                else None
            ),
            "hard_output_cap_bytes": hard_output_cap_bytes or None,
            "cpu_estimate": "requires_bounded_visible_calibration",
            "memory_estimate": "requires_bounded_visible_calibration",
        },
        "candidate_universe": {
            "path": str(universe),
            "sha256": _sha256(universe),
            "rows": universe_rows,
            "frozen_for_launch": False,
        },
        "feasibility_reasons": feasibility_reasons,
        "contract_gaps_before_approval": contract_gaps,
        "verdict": verdict,
        "actual_collection_allowed": False,
        "next_allowed_action": (
            "freeze_dense_ws_data_contract_and_build_immutable_campaign_planonly"
            if not feasibility_reasons
            else "repair_feasibility_before_contract_freeze"
        ),
        "frozen_candidate": frozen_candidate,
        "candidate_contract_hash": _canonical_hash(frozen_candidate),
    }
    _write_json_atomic(output_path, result)
    persisted = _read_json(output_path)
    if persisted.get("candidate_contract_hash") != _canonical_hash(
        persisted["frozen_candidate"]
    ):
        raise ValueError("persisted candidate contract hash mismatch")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build dense-WS duration feasibility without starting a collector."
    )
    parser.add_argument("--hypothesis-bank", type=Path, required=True)
    parser.add_argument("--continuous-policy", type=Path, required=True)
    parser.add_argument("--pit-schedule", type=Path, required=True)
    parser.add_argument("--prior-manifest-root", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--requested-start-local", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segment-sec", type=int, default=3_600)
    parser.add_argument("--drain-sec", type=int, default=900)
    parser.add_argument("--certification-sec", type=int, default=1_200)
    parser.add_argument("--target-writer-sec", type=int)
    parser.add_argument("--min-phase-headroom-sec", type=int, default=900)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_feasibility(
        hypothesis_bank_path=args.hypothesis_bank,
        continuous_policy_path=args.continuous_policy,
        pit_schedule_path=args.pit_schedule,
        prior_manifest_root=args.prior_manifest_root,
        universe_path=args.universe,
        requested_start_local=args.requested_start_local,
        output_path=args.output,
        segment_sec=args.segment_sec,
        drain_sec=args.drain_sec,
        certification_sec=args.certification_sec,
        target_writer_sec_override=args.target_writer_sec,
        min_phase_headroom_sec=args.min_phase_headroom_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
