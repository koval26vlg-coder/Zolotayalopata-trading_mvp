from __future__ import annotations

import argparse
import hashlib
import json
import math
import signal
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from funding import build_funding_clients
from perp_collector import build_perp_rest_clients
from pit_cross_venue_fast_pipeline import DECISION_READY, FAST_MODE, FAST_SCHEMA, _build_episodes
from pit_cross_venue_forward_probe import ForwardProbeConfig, collect_forward_cycle
from pit_cross_venue_short_probe_plan import SHORT_PLAN_DECISION, SHORT_PLAN_MODE, SHORT_PLAN_SCHEMA
from pit_universe_snapshot_collector import CollectorLock, atomic_write_json


MANIFEST_SCHEMA = "pit_linear_perp_cross_venue_short_probe_manifest_v1"
MANIFEST_MODE = "pit_linear_perp_cross_venue_short_execution_probe_collect"
SAMPLE_SCHEMA = "pit_linear_perp_cross_venue_short_probe_sample_v1"
SAMPLE_MODE = "pit_linear_perp_cross_venue_short_execution_probe_sample"


CycleFetcher = Callable[[int, list[str], ForwardProbeConfig], dict[str, Any]]


def collect_short_probe(
    plan_path: str | Path,
    output_root: str | Path,
    run_id: str,
    *,
    resume: bool = False,
    cycle_fetcher: CycleFetcher | None = None,
    stop_requested: Callable[[], bool] | None = None,
    wall_time_fn: Callable[[], float] = time.time,
    monotonic_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    plan_file = Path(plan_path).resolve()
    plan = _load_plan(plan_file)
    plan_sha256 = _sha256_file(plan_file)
    root = Path(output_root).resolve()
    if not run_id or any(character in run_id for character in "\\/:"):
        raise ValueError("run_id must be a non-empty filesystem-safe name")
    run_dir = root / run_id
    sample_dir = run_dir / "samples"
    manifest_path = run_dir / "manifest.json"
    lock = CollectorLock(run_dir / "collector.lock", run_id)
    stop_requested = stop_requested or (lambda: False)
    candidates = sorted(plan["instrument_scope"]["candidate_bases"])
    contract = plan["collection_contract"]
    sequential = plan["sequential_stop_contract"]
    interval_sec = float(contract["interval_sec"])
    max_duration_sec = float(contract["max_duration_sec"])
    probe_cfg = _probe_config(contract, len(candidates))

    if run_dir.exists() and any(run_dir.iterdir()) and not resume:
        raise FileExistsError(f"run_id={run_id} already has artifacts; pass resume=True explicitly")
    if resume and not manifest_path.is_file():
        raise FileNotFoundError(f"cannot resume run_id={run_id}: manifest not found")

    lock.acquire()
    session_started_mono = monotonic_fn()
    try:
        scan = _scan_samples(sample_dir, run_id, plan_sha256, candidates, int(contract["min_valid_pairs_per_sample"]))
        if resume:
            manifest = _load_json(manifest_path)
            _validate_resume_manifest(manifest, run_id, plan_sha256, scan)
            elapsed_before = float(manifest.get("elapsed_active_sec") or 0.0)
            resume_count = int(manifest.get("resume_count") or 0) + 1
            started_at_utc = str(manifest.get("started_at_utc") or _iso_utc(wall_time_fn()))
        else:
            if scan["attempt_sample_count"]:
                raise ValueError("fresh short probe cannot start with existing samples")
            elapsed_before = 0.0
            resume_count = 0
            started_at_utc = _iso_utc(wall_time_fn())

        manifest = _manifest_payload(
            run_id=run_id,
            run_dir=run_dir,
            sample_dir=sample_dir,
            manifest_path=manifest_path,
            plan_file=plan_file,
            plan_sha256=plan_sha256,
            plan=plan,
            scan=scan,
            started_at_utc=started_at_utc,
            elapsed_active_sec=elapsed_before,
            resume_count=resume_count,
        )
        sample_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(manifest_path, manifest)

        if cycle_fetcher is None:
            funding_clients = build_funding_clients(["mexc", "gateio"], timeout_sec=probe_cfg.timeout_sec)
            rest_clients = build_perp_rest_clients(["mexc", "gateio"], timeout_sec=probe_cfg.timeout_sec)
            for client in [*funding_clients.values(), *rest_clients.values()]:
                session = getattr(client, "session", None)
                if session is not None:
                    session.trust_env = False

            def cycle_fetcher(sample_index: int, bases: list[str], cfg: ForwardProbeConfig) -> dict[str, Any]:
                return collect_forward_cycle(
                    bases,
                    cfg,
                    funding_clients=funding_clients,
                    rest_clients=rest_clients,
                    now_fn=wall_time_fn,
                    progress_label=f"{MANIFEST_MODE}:sample={sample_index}",
                )

        interrupted = False
        terminal_reason = ""
        terminal_class = ""
        session_attempts = 0
        while True:
            elapsed = elapsed_before + max(0.0, monotonic_fn() - session_started_mono)
            terminal = _terminal_decision(scan, elapsed, contract, sequential)
            if terminal:
                terminal_class, terminal_reason = terminal
                break
            if elapsed >= max_duration_sec:
                terminal_class, terminal_reason = "insufficient", "maximum_duration_without_success"
                break
            if stop_requested():
                interrupted = True
                terminal_reason = "signal_or_user_interrupt"
                break

            sample_index = int(scan["attempt_sample_count"]) + 1
            sample_started = wall_time_fn()
            try:
                cycle = cycle_fetcher(sample_index, candidates, probe_cfg)
            except KeyboardInterrupt:
                interrupted = True
                terminal_reason = "keyboard_interrupt_before_sample_commit"
                break
            except Exception as exc:  # noqa: BLE001 - failed public fetch is immutable evidence.
                cycle = {
                    "started_ts": sample_started,
                    "finished_ts": wall_time_fn(),
                    "discovery_errors": {"collector": f"{type(exc).__name__}: {exc}"[:500]},
                    "pairs": [
                        {
                            "base": base,
                            "provisional_identity_match": False,
                            "fully_valid": False,
                            "invalid_reasons": ["whole_sample_fetch_error"],
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                        }
                        for base in candidates
                    ],
                }
            sample = _build_sample(
                cycle,
                run_id=run_id,
                plan_sha256=plan_sha256,
                sample_index=sample_index,
                candidates=candidates,
                min_valid_pairs=int(contract["min_valid_pairs_per_sample"]),
                started_ts=sample_started,
                finished_ts=wall_time_fn(),
            )
            sample_path = sample_dir / f"sample_{sample_index:06d}.json"
            if sample_path.exists():
                raise FileExistsError(f"refusing to overwrite immutable sample: {sample_path}")
            atomic_write_json(sample_path, sample)
            sample_hash = _sha256_file(sample_path)
            _apply_sample(scan, sample, sample_hash)
            session_attempts += 1
            elapsed = elapsed_before + max(0.0, monotonic_fn() - session_started_mono)
            manifest.update(
                _manifest_progress(
                    scan,
                    elapsed_active_sec=elapsed,
                    last_sample_path=sample_path,
                    last_sample_sha256=sample_hash,
                    resume_count=resume_count,
                    independence_gap_samples=int(contract["independence_gap_samples"]),
                )
            )
            atomic_write_json(manifest_path, manifest)
            print(
                json.dumps(
                    {
                        "progress": MANIFEST_MODE,
                        "run_id": run_id,
                        "sample": sample_index,
                        "sample_valid": sample["sample_valid"],
                        "valid_pairs": sample["valid_pair_count"],
                        "fixed_positive_pairs": sample["fixed_cost_positive_pair_count"],
                        "valid_samples": scan["valid_sample_count"],
                        "failed_samples": scan["failed_sample_count"],
                        "elapsed_active_sec": round(elapsed, 3),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if stop_requested():
                interrupted = True
                terminal_reason = "signal_or_user_interrupt"
                break

            terminal = _terminal_decision(scan, elapsed, contract, sequential)
            if terminal:
                terminal_class, terminal_reason = terminal
                break
            next_due = session_started_mono + session_attempts * interval_sec
            _sleep_interruptibly(max(0.0, next_due - monotonic_fn()), stop_requested, sleep_fn)

        elapsed = min(max_duration_sec, elapsed_before + max(0.0, monotonic_fn() - session_started_mono))
        if interrupted:
            status = "STOPPED_INCOMPLETE"
            final = False
        elif terminal_class == "success":
            status = "COMPLETED_SHORT_PROBE_READY_FOR_OFFLINE_EVALUATION"
            final = True
        elif terminal_class == "futility":
            status = "COMPLETED_SHORT_PROBE_FUTILITY"
            final = True
        else:
            status = "COMPLETED_SHORT_PROBE_INSUFFICIENT_EVIDENCE"
            final = True
        manifest.update(
            _manifest_progress(
                scan,
                elapsed_active_sec=elapsed,
                last_sample_path=Path(str(manifest.get("last_sample_path")))
                if manifest.get("last_sample_path")
                else None,
                last_sample_sha256=manifest.get("last_sample_sha256"),
                resume_count=resume_count,
                independence_gap_samples=int(contract["independence_gap_samples"]),
            )
        )
        manifest.update(
            {
                "updated_at_utc": _iso_utc(wall_time_fn()),
                "finished_at_utc": _iso_utc(wall_time_fn()) if final else None,
                "stopped_at_utc": _iso_utc(wall_time_fn()) if interrupted else None,
                "status": status,
                "final": final,
                "incomplete": not final,
                "short_probe_ready_for_offline_evaluation": terminal_class == "success",
                "stop_reason": terminal_reason,
                "strategy_accepted": False,
                "long_run_allowed": False,
                "replay_allowed": False,
                "paper_forward_allowed": False,
                "live_orders": False,
                "api_keys": False,
                "leverage_or_margin": False,
            }
        )
        atomic_write_json(manifest_path, manifest)
        return manifest
    except BaseException as exc:
        if "manifest" in locals():
            manifest.update(
                {
                    "updated_at_utc": _iso_utc(wall_time_fn()),
                    "stopped_at_utc": _iso_utc(wall_time_fn()),
                    "status": "STOPPED_INCOMPLETE",
                    "final": False,
                    "incomplete": True,
                    "stop_reason": "collector_exception",
                    "fatal_error": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
            atomic_write_json(manifest_path, manifest)
        raise
    finally:
        lock.release()


def _terminal_decision(
    scan: dict[str, Any],
    elapsed_sec: float,
    contract: dict[str, Any],
    sequential: dict[str, Any],
) -> tuple[str, str] | None:
    attempts = int(scan["attempt_sample_count"])
    if attempts <= 0:
        return None
    valid_ratio = int(scan["valid_sample_count"]) / attempts
    fetch_ratio = int(scan["fetch_error_sample_count"]) / attempts
    if attempts >= int(sequential["quality_checkpoint_min_attempts"]):
        if valid_ratio < float(sequential["quality_min_valid_sample_ratio"]):
            return "futility", "quality_checkpoint_valid_sample_ratio_below_floor"
        if fetch_ratio > float(sequential["quality_max_fetch_error_ratio"]):
            return "futility", "quality_checkpoint_fetch_error_ratio_above_cap"
    if (
        attempts >= int(sequential["futility_checkpoint_min_attempts"])
        and sequential.get("futility_if_zero_fixed_cost_positive_samples") is True
        and int(scan["fixed_cost_positive_observations"]) == 0
    ):
        return "futility", "futility_checkpoint_zero_fixed_cost_positive_samples"

    metrics = _episode_metrics(scan["positive_rows"], attempts, int(contract["independence_gap_samples"]))
    success = (
        elapsed_sec >= float(contract["min_duration_sec"])
        and int(scan["valid_sample_count"]) >= int(sequential["success_min_valid_samples"])
        and metrics["independent_episodes"] >= int(sequential["success_min_independent_episodes"])
        and metrics["event_bases"] >= int(sequential["success_min_event_bases"])
        and metrics["top1_base_concentration"] <= float(sequential["success_max_top1_base_concentration"])
        and (
            not sequential.get("success_requires_positive_samples_in_both_chronological_halves")
            or metrics["positive_in_both_halves"]
        )
    )
    if success:
        return "success", "sequential_short_probe_success"
    return None


def _build_sample(
    cycle: dict[str, Any],
    *,
    run_id: str,
    plan_sha256: str,
    sample_index: int,
    candidates: list[str],
    min_valid_pairs: int,
    started_ts: float,
    finished_ts: float,
) -> dict[str, Any]:
    by_base = {
        str(row.get("base") or "").upper(): row
        for row in cycle.get("pairs") or []
        if isinstance(row, dict) and row.get("base")
    }
    pairs = []
    for base in candidates:
        row = by_base.get(base)
        if row is None:
            row = {
                "base": base,
                "provisional_identity_match": False,
                "fully_valid": False,
                "invalid_reasons": ["missing_candidate_pair"],
            }
        pairs.append(row)
    discovery_errors = cycle.get("discovery_errors") or {}
    valid_count = sum(1 for pair in pairs if pair.get("fully_valid") is True)
    fixed_positive = sum(
        1
        for pair in pairs
        if pair.get("fully_valid") is True
        and _finite(pair.get("max_net_screening_edge_bps"))
        and float(pair["max_net_screening_edge_bps"]) > 0
    )
    observed_positive = sum(
        1
        for pair in pairs
        if pair.get("fully_valid") is True
        and _finite(pair.get("max_net_observed_base_fee_bps"))
        and float(pair["max_net_observed_base_fee_bps"]) > 0
    )
    reasons = Counter()
    for pair in pairs:
        reasons.update(str(reason) for reason in pair.get("invalid_reasons") or [])
    return {
        "schema": SAMPLE_SCHEMA,
        "mode": SAMPLE_MODE,
        "run_id": run_id,
        "plan_sha256": plan_sha256,
        "sample_index": sample_index,
        "sample_started_at_utc": _iso_utc(float(cycle.get("started_ts") or started_ts)),
        "sample_finished_at_utc": _iso_utc(float(cycle.get("finished_ts") or finished_ts)),
        "sample_valid": not discovery_errors and valid_count >= min_valid_pairs,
        "valid_pair_count": valid_count,
        "required_valid_pair_count": min_valid_pairs,
        "fetch_error_sample": bool(discovery_errors),
        "discovery_errors": discovery_errors,
        "fixed_cost_positive_pair_count": fixed_positive,
        "observed_base_fee_positive_pair_count": observed_positive,
        "invalid_reason_counts": dict(sorted(reasons.items())),
        "pairs": pairs,
    }


def _scan_samples(
    sample_dir: Path,
    run_id: str,
    plan_sha256: str,
    candidates: list[str],
    min_valid_pairs: int,
) -> dict[str, Any]:
    scan = _empty_scan()
    if not sample_dir.exists():
        return scan
    for expected, path in enumerate(sorted(sample_dir.glob("sample_*.json")), start=1):
        sample = _load_json(path)
        if sample.get("schema") != SAMPLE_SCHEMA or sample.get("mode") != SAMPLE_MODE:
            raise ValueError(f"invalid short sample schema/mode: {path}")
        if sample.get("run_id") != run_id or sample.get("plan_sha256") != plan_sha256:
            raise ValueError(f"short sample provenance mismatch: {path}")
        if int(sample.get("sample_index") or 0) != expected or path.name != f"sample_{expected:06d}.json":
            raise ValueError(f"short samples are not contiguous at {path}")
        pairs = sample.get("pairs") or []
        if [str(pair.get("base") or "") for pair in pairs] != candidates:
            raise ValueError(f"short sample candidate universe/order mismatch: {path}")
        valid_count = sum(1 for pair in pairs if pair.get("fully_valid") is True)
        expected_valid = not (sample.get("discovery_errors") or {}) and valid_count >= min_valid_pairs
        if bool(sample.get("sample_valid")) != expected_valid or int(sample.get("valid_pair_count") or 0) != valid_count:
            raise ValueError(f"short sample validity mismatch: {path}")
        _apply_sample(scan, sample, _sha256_file(path))
    return scan


def _empty_scan() -> dict[str, Any]:
    return {
        "attempt_sample_count": 0,
        "valid_sample_count": 0,
        "failed_sample_count": 0,
        "fetch_error_sample_count": 0,
        "pair_rows": 0,
        "fixed_cost_positive_observations": 0,
        "observed_base_fee_positive_observations": 0,
        "sample_chain_sha256": "",
        "invalid_reason_counts": Counter(),
        "positive_rows": [],
    }


def _apply_sample(scan: dict[str, Any], sample: dict[str, Any], sample_hash: str) -> None:
    scan["attempt_sample_count"] += 1
    if sample.get("sample_valid") is True:
        scan["valid_sample_count"] += 1
    else:
        scan["failed_sample_count"] += 1
    if sample.get("fetch_error_sample") is True:
        scan["fetch_error_sample_count"] += 1
    pairs = sample.get("pairs") or []
    scan["pair_rows"] += len(pairs)
    scan["fixed_cost_positive_observations"] += int(sample.get("fixed_cost_positive_pair_count") or 0)
    scan["observed_base_fee_positive_observations"] += int(
        sample.get("observed_base_fee_positive_pair_count") or 0
    )
    scan["invalid_reason_counts"].update(sample.get("invalid_reason_counts") or {})
    index = int(sample["sample_index"])
    for pair in pairs:
        if pair.get("fully_valid") is not True or not _finite(pair.get("max_net_screening_edge_bps")):
            continue
        if float(pair["max_net_screening_edge_bps"]) <= 0:
            continue
        gross = pair.get("gross_execution_edges") or {}
        direction = "unknown"
        finite_gross = {key: float(value) for key, value in gross.items() if _finite(value)}
        if finite_gross:
            direction = max(finite_gross, key=finite_gross.get)
        scan["positive_rows"].append(
            {
                "cycle": index,
                "base": str(pair.get("base") or ""),
                "direction": direction,
                "net_bps": float(pair["max_net_screening_edge_bps"]),
            }
        )
    previous = str(scan.get("sample_chain_sha256") or "")
    scan["sample_chain_sha256"] = hashlib.sha256(f"{previous}:{sample_hash}".encode("ascii")).hexdigest()


def _episode_metrics(positive_rows: list[dict[str, Any]], attempts: int, gap_samples: int) -> dict[str, Any]:
    episodes = _build_episodes(positive_rows, gap_samples)
    counts = Counter(str(event["base"]) for event in episodes)
    total = len(episodes)
    top1 = max(counts.values()) / total if total else 0.0
    half = max(1, math.ceil(attempts / 2))
    first = any(int(row["cycle"]) <= half for row in positive_rows)
    second = any(int(row["cycle"]) > half for row in positive_rows)
    return {
        "independent_episodes": total,
        "event_bases": len(counts),
        "top1_base_concentration": top1,
        "positive_in_both_halves": first and second,
        "per_base_episode_counts": dict(sorted(counts.items())),
    }


def _manifest_payload(
    *,
    run_id: str,
    run_dir: Path,
    sample_dir: Path,
    manifest_path: Path,
    plan_file: Path,
    plan_sha256: str,
    plan: dict[str, Any],
    scan: dict[str, Any],
    started_at_utc: str,
    elapsed_active_sec: float,
    resume_count: int,
) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "mode": MANIFEST_MODE,
        "run_id": run_id,
        "status": "RUNNING",
        "final": False,
        "incomplete": False,
        "research_only": True,
        "strategy_accepted": False,
        "short_probe_ready_for_offline_evaluation": False,
        "long_run_allowed": False,
        "replay_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "started_at_utc": started_at_utc,
        "updated_at_utc": _iso_utc(time.time()),
        "finished_at_utc": None,
        "stopped_at_utc": None,
        "run_dir": str(run_dir),
        "samples_dir": str(sample_dir),
        "manifest_path": str(manifest_path),
        "plan_path": str(plan_file),
        "plan_sha256": plan_sha256,
        "collection_contract": plan["collection_contract"],
        "sequential_stop_contract": plan["sequential_stop_contract"],
        "candidate_bases": sorted(plan["instrument_scope"]["candidate_bases"]),
        "elapsed_active_sec": elapsed_active_sec,
        "resume_count": resume_count,
        **_manifest_fields(scan, int(plan["collection_contract"]["independence_gap_samples"])),
    }


def _manifest_progress(
    scan: dict[str, Any],
    *,
    elapsed_active_sec: float,
    last_sample_path: Path | None,
    last_sample_sha256: str | None,
    resume_count: int,
    independence_gap_samples: int,
) -> dict[str, Any]:
    return {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "elapsed_active_sec": elapsed_active_sec,
        "resume_count": resume_count,
        "last_sample_path": str(last_sample_path) if last_sample_path else None,
        "last_sample_sha256": last_sample_sha256,
        **_manifest_fields(scan, independence_gap_samples),
    }


def _manifest_fields(scan: dict[str, Any], gap_samples: int) -> dict[str, Any]:
    attempts = int(scan["attempt_sample_count"])
    metrics = _episode_metrics(scan["positive_rows"], attempts, gap_samples)
    return {
        "attempt_sample_count": attempts,
        "valid_sample_count": int(scan["valid_sample_count"]),
        "failed_sample_count": int(scan["failed_sample_count"]),
        "valid_sample_ratio": int(scan["valid_sample_count"]) / attempts if attempts else 0.0,
        "fetch_error_sample_count": int(scan["fetch_error_sample_count"]),
        "fetch_error_ratio": int(scan["fetch_error_sample_count"]) / attempts if attempts else 0.0,
        "pair_rows": int(scan["pair_rows"]),
        "fixed_cost_positive_observations": int(scan["fixed_cost_positive_observations"]),
        "observed_base_fee_positive_observations": int(scan["observed_base_fee_positive_observations"]),
        "sample_chain_sha256": str(scan["sample_chain_sha256"]),
        "invalid_reason_counts": dict(sorted(scan["invalid_reason_counts"].items())),
        **metrics,
    }


def _load_plan(path: Path) -> dict[str, Any]:
    plan = _load_json(path)
    if plan.get("schema") != SHORT_PLAN_SCHEMA or plan.get("mode") != SHORT_PLAN_MODE:
        raise ValueError("unsupported short probe plan schema/mode")
    if plan.get("decision") != SHORT_PLAN_DECISION:
        raise ValueError("short probe plan is not ready")
    if plan.get("would_start") is not False or plan.get("collect_started") is not False:
        raise ValueError("short probe plan safety flags are not fail-closed")
    if plan.get("strategy_accepted") is not False or plan.get("long_run_required_now") is not False:
        raise ValueError("short probe plan must not accept a strategy or require a long run")
    fail_closed = plan.get("fail_closed_contract") or {}
    if (
        fail_closed.get("thresholds_frozen_before_independent_short_probe") is not True
        or fail_closed.get("threshold_mutation_after_start_allowed") is not False
        or fail_closed.get("automatic_next_stage_allowed") is not False
    ):
        raise ValueError("short probe fail-closed contract is incomplete")
    source = plan.get("source") or {}
    fast_path = Path(str(source.get("fast_output_path") or "")).resolve()
    if not fast_path.is_file() or _sha256_file(fast_path) != str(source.get("fast_output_sha256") or ""):
        raise ValueError("short probe fast-output binding is missing or changed")
    fast = _load_json(fast_path)
    if fast.get("schema") != FAST_SCHEMA or fast.get("mode") != FAST_MODE or fast.get("decision") != DECISION_READY:
        raise ValueError("short probe source fast-output is no longer eligible")
    candidates = plan.get("instrument_scope", {}).get("candidate_bases") or []
    if not candidates or len(candidates) != len(set(candidates)):
        raise ValueError("short probe candidate universe is invalid")
    contract = plan.get("collection_contract") or {}
    sequential = plan.get("sequential_stop_contract") or {}
    required_contract = (
        "interval_sec",
        "min_duration_sec",
        "max_duration_sec",
        "target_valid_samples",
        "min_valid_pairs_per_sample",
        "independence_gap_samples",
        "target_notional_quote",
        "depth_limit",
        "max_index_divergence_bps",
        "max_mark_index_divergence_bps",
        "max_quote_age_sec",
        "max_cross_venue_skew_sec",
        "round_trip_fee_bps",
        "slippage_bps",
        "operational_buffer_bps",
        "fixed_total_cost_bps",
    )
    required_sequential = (
        "quality_checkpoint_min_attempts",
        "quality_min_valid_sample_ratio",
        "quality_max_fetch_error_ratio",
        "futility_checkpoint_min_attempts",
        "futility_if_zero_fixed_cost_positive_samples",
        "success_min_valid_samples",
        "success_min_independent_episodes",
        "success_min_event_bases",
        "success_max_top1_base_concentration",
        "success_requires_positive_samples_in_both_chronological_halves",
    )
    missing = [name for name in required_contract if name not in contract]
    missing += [name for name in required_sequential if name not in sequential]
    if missing:
        raise ValueError(f"short probe plan is incomplete: {', '.join(missing)}")
    if not 0 < float(contract["min_duration_sec"]) <= float(contract["max_duration_sec"]) <= 10800:
        raise ValueError("short probe duration contract is invalid")
    if int(contract["min_valid_pairs_per_sample"]) > len(candidates):
        raise ValueError("short probe valid-pair threshold exceeds candidate universe")
    component_total = sum(float(contract[name]) for name in ("round_trip_fee_bps", "slippage_bps", "operational_buffer_bps"))
    if not math.isclose(component_total, float(contract["fixed_total_cost_bps"])):
        raise ValueError("short probe cost components do not match fixed total cost")
    return plan


def _probe_config(contract: dict[str, Any], candidate_count: int) -> ForwardProbeConfig:
    return ForwardProbeConfig(
        target_notional_quote=float(contract["target_notional_quote"]),
        depth_limit=int(contract["depth_limit"]),
        max_index_divergence_bps=float(contract["max_index_divergence_bps"]),
        max_mark_index_divergence_bps=float(contract["max_mark_index_divergence_bps"]),
        max_quote_age_sec=float(contract["max_quote_age_sec"]),
        max_cross_venue_skew_sec=float(contract["max_cross_venue_skew_sec"]),
        min_provisional_identity_pairs=candidate_count,
        min_fully_valid_pairs=int(contract["min_valid_pairs_per_sample"]),
        round_trip_fee_bps=float(contract["round_trip_fee_bps"]),
        slippage_bps=float(contract["slippage_bps"]),
        operational_buffer_bps=float(contract["operational_buffer_bps"]),
        progress=False,
    )


def _validate_resume_manifest(manifest: dict[str, Any], run_id: str, plan_sha256: str, scan: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("mode") != MANIFEST_MODE:
        raise ValueError("short probe resume manifest schema/mode mismatch")
    if manifest.get("run_id") != run_id or manifest.get("plan_sha256") != plan_sha256:
        raise ValueError("short probe resume provenance mismatch")
    if manifest.get("final") is True:
        raise ValueError("cannot resume a final short probe")
    if int(manifest.get("attempt_sample_count") or 0) > int(scan["attempt_sample_count"]):
        raise ValueError("short probe resume manifest is ahead of immutable samples")


def _sleep_interruptibly(seconds: float, stop_requested: Callable[[], bool], sleep_fn: Callable[[float], None]) -> None:
    remaining = seconds
    while remaining > 0 and not stop_requested():
        chunk = min(1.0, remaining)
        sleep_fn(chunk)
        remaining -= chunk


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a sealed 1-3h public short execution probe")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confirmed-short-probe-collect", action="store_true")
    args = parser.parse_args()
    if not args.confirmed_short_probe_collect:
        raise SystemExit("short probe collector requires --confirmed-short-probe-collect")
    stop_event = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    manifest = collect_short_probe(
        args.plan,
        args.output_root,
        args.run_id,
        resume=args.resume,
        stop_requested=stop_event.is_set,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
