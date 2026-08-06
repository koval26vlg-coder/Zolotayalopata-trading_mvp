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
from pit_cross_venue_forward_plan import PLAN_DECISION, PLAN_MODE, PLAN_SCHEMA
from pit_cross_venue_forward_probe import ForwardProbeConfig, collect_forward_cycle
from pit_universe_snapshot_collector import CollectorLock, atomic_write_json


MANIFEST_SCHEMA = "pit_linear_perp_cross_venue_forward_oos_manifest_v1"
MANIFEST_MODE = "pit_linear_perp_cross_venue_forward_oos_collect"
SEGMENT_SCHEMA = "pit_linear_perp_cross_venue_forward_oos_segment_v1"
SEGMENT_MODE = "pit_linear_perp_cross_venue_forward_oos_attempt_cycle"


CycleFetcher = Callable[[int, list[str], ForwardProbeConfig], dict[str, Any]]


def collect_forward_oos(
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
    segment_dir = run_dir / "segments"
    manifest_path = run_dir / "manifest.json"
    lock = CollectorLock(run_dir / "collector.lock", run_id)
    stop_requested = stop_requested or (lambda: False)
    all_bases = list(plan["sealed_universe"]["all_discovery_bases"])
    identity_bases = set(plan["sealed_universe"]["identity_evaluation_bases"])
    contract = plan["collection_contract"]
    interval_sec = float(contract["interval_sec"])
    target_valid_cycles = int(contract["target_valid_cycles"])
    min_active_span_sec = float(contract["min_active_span_sec"])
    max_active_duration_sec = float(contract["max_active_duration_sec"])
    min_valid_pairs = int(contract["min_valid_pairs_per_cycle"])
    max_attempt_cycles = int(contract["max_attempt_cycles"])
    max_attempt_error_ratio = float(contract["max_attempt_error_ratio"])
    probe_cfg = _probe_config(contract)

    if run_dir.exists() and any(run_dir.iterdir()) and not resume:
        raise FileExistsError(f"run_id={run_id} already has artifacts; pass resume=True explicitly")
    if resume and not manifest_path.is_file():
        raise FileNotFoundError(f"cannot resume run_id={run_id}: manifest not found")

    lock.acquire()
    session_started_mono = monotonic_fn()
    try:
        scan = _scan_segments(segment_dir, run_id, plan_sha256, all_bases, identity_bases, min_valid_pairs)
        if resume:
            manifest = _load_json(manifest_path)
            _validate_resume_manifest(manifest, run_id, plan_sha256, scan)
            elapsed_before = float(manifest.get("elapsed_active_sec") or 0.0)
            resume_count = int(manifest.get("resume_count") or 0) + 1
            started_at_utc = str(manifest.get("started_at_utc") or _iso_utc(wall_time_fn()))
        else:
            if scan["attempt_cycle_count"]:
                raise ValueError("fresh run cannot start with existing cycle segments")
            elapsed_before = 0.0
            resume_count = 0
            started_at_utc = _iso_utc(wall_time_fn())

        manifest = _manifest_payload(
            run_id=run_id,
            run_dir=run_dir,
            segment_dir=segment_dir,
            manifest_path=manifest_path,
            plan_file=plan_file,
            plan_sha256=plan_sha256,
            plan=plan,
            scan=scan,
            started_at_utc=started_at_utc,
            elapsed_active_sec=elapsed_before,
            resume_count=resume_count,
        )
        segment_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(manifest_path, manifest)

        if cycle_fetcher is None:
            funding_clients = build_funding_clients(["mexc", "gateio"], timeout_sec=probe_cfg.timeout_sec)
            rest_clients = build_perp_rest_clients(["mexc", "gateio"], timeout_sec=probe_cfg.timeout_sec)
            for client in [*funding_clients.values(), *rest_clients.values()]:
                session = getattr(client, "session", None)
                if session is not None:
                    session.trust_env = False

            def cycle_fetcher(attempt_cycle: int, bases: list[str], cfg: ForwardProbeConfig) -> dict[str, Any]:
                return collect_forward_cycle(
                    bases,
                    cfg,
                    funding_clients=funding_clients,
                    rest_clients=rest_clients,
                    now_fn=wall_time_fn,
                    progress_label=f"{MANIFEST_MODE}:cycle={attempt_cycle}",
                )

        interrupted = False
        terminal_reason = ""
        session_attempts = 0
        while True:
            elapsed_active = elapsed_before + max(0.0, monotonic_fn() - session_started_mono)
            scan["elapsed_active_sec"] = elapsed_active
            if _quality_complete(
                scan,
                elapsed_active,
                target_valid_cycles,
                min_active_span_sec,
                max_attempt_error_ratio,
            ):
                terminal_reason = "valid_cycle_and_active_span_quota_reached"
                break
            if elapsed_active >= max_active_duration_sec:
                terminal_reason = "max_active_duration_without_quality_quota"
                break
            if scan["attempt_cycle_count"] >= max_attempt_cycles:
                terminal_reason = "max_attempt_cycles_without_quality_quota"
                break
            if stop_requested():
                interrupted = True
                terminal_reason = "signal_or_user_interrupt"
                break

            attempt_cycle = int(scan["attempt_cycle_count"]) + 1
            cycle_started_wall = wall_time_fn()
            cycle_started_mono = monotonic_fn()
            try:
                cycle_payload = cycle_fetcher(attempt_cycle, all_bases, probe_cfg)
            except KeyboardInterrupt:
                interrupted = True
                terminal_reason = "keyboard_interrupt_before_cycle_commit"
                break
            except Exception as exc:  # noqa: BLE001 - a whole-cycle fetch failure becomes an immutable failed segment.
                cycle_payload = {
                    "started_ts": cycle_started_wall,
                    "finished_ts": wall_time_fn(),
                    "discovery_errors": {"collector": f"{type(exc).__name__}: {exc}"[:500]},
                    "pairs": [
                        {
                            "base": base,
                            "provisional_identity_match": False,
                            "fully_valid": False,
                            "invalid_reasons": ["whole_cycle_fetch_error"],
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                        }
                        for base in all_bases
                    ],
                }
            segment = _build_segment(
                cycle_payload,
                run_id=run_id,
                plan_sha256=plan_sha256,
                attempt_cycle=attempt_cycle,
                all_bases=all_bases,
                identity_bases=identity_bases,
                min_valid_pairs=min_valid_pairs,
                cycle_started_wall=cycle_started_wall,
                cycle_finished_wall=wall_time_fn(),
            )
            segment_path = segment_dir / f"cycle_{attempt_cycle:06d}.json"
            if segment_path.exists():
                raise FileExistsError(f"refusing to overwrite immutable segment: {segment_path}")
            atomic_write_json(segment_path, segment)
            segment_hash = _sha256_file(segment_path)
            _apply_segment_to_scan(scan, segment, segment_hash)
            session_attempts += 1
            elapsed_active = elapsed_before + max(0.0, monotonic_fn() - session_started_mono)
            manifest.update(
                _manifest_progress(
                    scan,
                    elapsed_active_sec=elapsed_active,
                    last_segment_path=segment_path,
                    last_segment_sha256=segment_hash,
                    resume_count=resume_count,
                )
            )
            atomic_write_json(manifest_path, manifest)
            print(
                json.dumps(
                    {
                        "progress": MANIFEST_MODE,
                        "run_id": run_id,
                        "attempt_cycle": attempt_cycle,
                        "cycle_valid": segment["cycle_valid"],
                        "valid_pairs": segment["valid_pair_count"],
                        "required_valid_pairs": min_valid_pairs,
                        "valid_cycles": scan["valid_cycle_count"],
                        "target_valid_cycles": target_valid_cycles,
                        "failed_cycles": scan["failed_cycle_count"],
                        "elapsed_active_sec": round(elapsed_active, 3),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if stop_requested():
                interrupted = True
                terminal_reason = "signal_or_user_interrupt"
                break
            if _quality_complete(
                scan,
                elapsed_active,
                target_valid_cycles,
                min_active_span_sec,
                max_attempt_error_ratio,
            ):
                terminal_reason = "valid_cycle_and_active_span_quota_reached"
                break

            next_due = session_started_mono + (session_attempts * interval_sec)
            sleep_seconds = max(0.0, next_due - monotonic_fn())
            _sleep_interruptibly(sleep_seconds, stop_requested, sleep_fn)

        elapsed_active = min(
            max_active_duration_sec,
            elapsed_before + max(0.0, monotonic_fn() - session_started_mono),
        )
        quality_complete = _quality_complete(
            scan,
            elapsed_active,
            target_valid_cycles,
            min_active_span_sec,
            max_attempt_error_ratio,
        )
        final = not interrupted
        status = (
            "COMPLETED_QUALITY_READY"
            if quality_complete
            else "STOPPED_INCOMPLETE"
            if interrupted
            else "COMPLETED_INSUFFICIENT_EVIDENCE"
        )
        manifest.update(
            _manifest_progress(
                scan,
                elapsed_active_sec=elapsed_active,
                last_segment_path=Path(str(manifest.get("last_segment_path") or "")) if manifest.get("last_segment_path") else None,
                last_segment_sha256=manifest.get("last_segment_sha256"),
                resume_count=resume_count,
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
                "quality_complete": quality_complete,
                "stop_reason": terminal_reason,
                "strategy_accepted": False,
                "replay_allowed": False,
                "grid_allowed": False,
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
                    "quality_complete": False,
                    "stop_reason": "collector_exception",
                    "fatal_error": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
            atomic_write_json(manifest_path, manifest)
        raise
    finally:
        lock.release()


def _load_plan(path: Path) -> dict[str, Any]:
    plan = _load_json(path)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != PLAN_MODE:
        raise ValueError("unsupported forward OOS plan schema/mode")
    if plan.get("decision") != PLAN_DECISION:
        raise ValueError("forward OOS plan is not approved for a collect approval packet")
    if plan.get("would_start") is not False or plan.get("collect_started") is not False:
        raise ValueError("forward OOS plan safety flags are not fail-closed")
    if plan.get("strategy_accepted") is not False:
        raise ValueError("forward OOS plan must not accept a strategy")
    source = plan.get("source") or {}
    probe_path = Path(str(source.get("probe_path") or "")).resolve()
    expected_probe_hash = str(source.get("probe_sha256") or "")
    if not probe_path.is_file() or _sha256_file(probe_path) != expected_probe_hash:
        raise ValueError("forward OOS plan probe binding is missing or changed")
    universe = plan.get("sealed_universe") or {}
    all_bases = list(universe.get("all_discovery_bases") or [])
    identity_bases = list(universe.get("identity_evaluation_bases") or [])
    if not all_bases or not identity_bases or not set(identity_bases).issubset(set(all_bases)):
        raise ValueError("forward OOS plan has an invalid sealed universe")
    if _canonical_sha256({"bases": all_bases}) != universe.get("all_discovery_bases_sha256"):
        raise ValueError("all discovery bases SHA-256 mismatch")
    if _canonical_sha256({"bases": identity_bases}) != universe.get("identity_evaluation_bases_sha256"):
        raise ValueError("identity evaluation bases SHA-256 mismatch")
    contract = plan.get("collection_contract") or {}
    required = (
        "interval_sec",
        "target_valid_cycles",
        "min_active_span_sec",
        "max_active_duration_sec",
        "min_valid_pairs_per_cycle",
        "max_attempt_cycles",
        "max_attempt_error_ratio",
        "retry_attempts",
        "retry_initial_backoff_sec",
        "target_notional_quote",
        "depth_limit",
        "max_index_divergence_bps",
        "max_mark_index_divergence_bps",
        "max_quote_age_sec",
        "max_cross_venue_skew_sec",
    )
    missing = [name for name in required if name not in contract]
    if missing:
        raise ValueError(f"forward OOS plan collection contract is incomplete: {', '.join(missing)}")
    if int(contract["min_valid_pairs_per_cycle"]) > len(identity_bases):
        raise ValueError("min_valid_pairs_per_cycle exceeds identity universe")
    positive_fields = (
        "interval_sec",
        "target_valid_cycles",
        "min_active_span_sec",
        "max_active_duration_sec",
        "min_valid_pairs_per_cycle",
        "max_attempt_cycles",
        "target_notional_quote",
        "depth_limit",
        "max_index_divergence_bps",
        "max_mark_index_divergence_bps",
        "max_quote_age_sec",
        "max_cross_venue_skew_sec",
    )
    if any(float(contract[name]) <= 0 for name in positive_fields):
        raise ValueError("forward OOS collection contract contains non-positive parameters")
    if float(contract["max_active_duration_sec"]) < float(contract["min_active_span_sec"]):
        raise ValueError("forward OOS maximum duration is shorter than minimum active span")
    error_ratio = float(contract["max_attempt_error_ratio"])
    if not 0 <= error_ratio < 1:
        raise ValueError("max_attempt_error_ratio must be in [0, 1)")
    if int(contract["target_valid_cycles"]) > int(contract["max_attempt_cycles"]):
        raise ValueError("target_valid_cycles exceeds max_attempt_cycles")
    if int(contract["retry_attempts"]) != 3 or float(contract["retry_initial_backoff_sec"]) != 0.5:
        raise ValueError("collector v1 requires the sealed 3-attempt 0.5s initial-backoff policy")
    return plan


def _probe_config(contract: dict[str, Any]) -> ForwardProbeConfig:
    return ForwardProbeConfig(
        target_notional_quote=float(contract["target_notional_quote"]),
        depth_limit=int(contract["depth_limit"]),
        max_index_divergence_bps=float(contract["max_index_divergence_bps"]),
        max_mark_index_divergence_bps=float(contract["max_mark_index_divergence_bps"]),
        max_quote_age_sec=float(contract["max_quote_age_sec"]),
        max_cross_venue_skew_sec=float(contract["max_cross_venue_skew_sec"]),
        min_provisional_identity_pairs=1,
        min_fully_valid_pairs=1,
        progress=True,
    )


def _build_segment(
    cycle_payload: dict[str, Any],
    *,
    run_id: str,
    plan_sha256: str,
    attempt_cycle: int,
    all_bases: list[str],
    identity_bases: set[str],
    min_valid_pairs: int,
    cycle_started_wall: float,
    cycle_finished_wall: float,
) -> dict[str, Any]:
    pairs = cycle_payload.get("pairs") or []
    if not isinstance(pairs, list):
        raise ValueError("forward cycle pairs must be a list")
    by_base: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("forward cycle pair must be an object")
        base = str(pair.get("base") or "").upper()
        if not base or base in by_base:
            raise ValueError("forward cycle contains missing or duplicate pair bases")
        by_base[base] = pair
    if set(by_base) != set(all_bases):
        raise ValueError("forward cycle pair bases do not match sealed discovery universe")
    ordered_pairs = [by_base[base] for base in all_bases]
    valid_pairs = [base for base in all_bases if base in identity_bases and by_base[base].get("fully_valid") is True]
    discovery_errors = cycle_payload.get("discovery_errors") or {}
    if not isinstance(discovery_errors, dict):
        raise ValueError("forward cycle discovery_errors must be an object")
    cycle_valid = not discovery_errors and len(valid_pairs) >= min_valid_pairs
    reason_counts = Counter(
        str(reason)
        for pair in ordered_pairs
        for reason in (pair.get("invalid_reasons") or [])
    )
    return {
        "schema": SEGMENT_SCHEMA,
        "mode": SEGMENT_MODE,
        "run_id": run_id,
        "plan_sha256": plan_sha256,
        "attempt_cycle": attempt_cycle,
        "cycle_started_at_utc": _iso_utc(float(cycle_payload.get("started_ts") or cycle_started_wall)),
        "cycle_finished_at_utc": _iso_utc(float(cycle_payload.get("finished_ts") or cycle_finished_wall)),
        "cycle_valid": cycle_valid,
        "valid_pair_count": len(valid_pairs),
        "required_valid_pair_count": min_valid_pairs,
        "valid_pair_bases": valid_pairs,
        "identity_pair_count": len(identity_bases),
        "all_discovery_pair_count": len(all_bases),
        "discovery_errors": discovery_errors,
        "invalid_reason_counts": dict(sorted(reason_counts.items())),
        "one_shot_cost_positive_pairs": sum(
            1
            for pair in ordered_pairs
            if pair.get("fully_valid") is True
            and _finite(pair.get("max_net_screening_edge_bps"))
            and float(pair["max_net_screening_edge_bps"]) > 0
        ),
        "observed_base_fee_cost_positive_pairs": sum(
            1
            for pair in ordered_pairs
            if pair.get("fully_valid") is True
            and _finite(pair.get("max_net_observed_base_fee_bps"))
            and float(pair["max_net_observed_base_fee_bps"]) > 0
        ),
        "pairs": ordered_pairs,
    }


def _scan_segments(
    segment_dir: Path,
    run_id: str,
    plan_sha256: str,
    all_bases: list[str],
    identity_bases: set[str],
    min_valid_pairs: int,
) -> dict[str, Any]:
    scan = {
        "attempt_cycle_count": 0,
        "valid_cycle_count": 0,
        "failed_cycle_count": 0,
        "pair_rows": 0,
        "cost_positive_observations": 0,
        "observed_base_fee_cost_positive_observations": 0,
        "segment_chain_sha256": "",
        "invalid_reason_counts": Counter(),
    }
    if not segment_dir.exists():
        return scan
    files = sorted(segment_dir.glob("cycle_*.json"))
    for expected, path in enumerate(files, start=1):
        segment = _load_json(path)
        if segment.get("schema") != SEGMENT_SCHEMA or segment.get("mode") != SEGMENT_MODE:
            raise ValueError(f"invalid segment schema/mode: {path}")
        if segment.get("run_id") != run_id or segment.get("plan_sha256") != plan_sha256:
            raise ValueError(f"segment provenance mismatch: {path}")
        if int(segment.get("attempt_cycle") or 0) != expected or path.name != f"cycle_{expected:06d}.json":
            raise ValueError(f"segments are not contiguous at {path}")
        pairs = segment.get("pairs") or []
        bases = [str(pair.get("base") or "").upper() for pair in pairs if isinstance(pair, dict)]
        if bases != all_bases:
            raise ValueError(f"segment universe/order mismatch: {path}")
        valid_count = sum(
            1 for pair in pairs if pair.get("base") in identity_bases and pair.get("fully_valid") is True
        )
        expected_valid = not (segment.get("discovery_errors") or {}) and valid_count >= min_valid_pairs
        if bool(segment.get("cycle_valid")) != expected_valid or int(segment.get("valid_pair_count") or 0) != valid_count:
            raise ValueError(f"segment validity mismatch: {path}")
        _apply_segment_to_scan(scan, segment, _sha256_file(path))
    return scan


def _apply_segment_to_scan(scan: dict[str, Any], segment: dict[str, Any], segment_hash: str) -> None:
    scan["attempt_cycle_count"] += 1
    if segment.get("cycle_valid") is True:
        scan["valid_cycle_count"] += 1
    else:
        scan["failed_cycle_count"] += 1
    scan["pair_rows"] += len(segment.get("pairs") or [])
    scan["cost_positive_observations"] += int(segment.get("one_shot_cost_positive_pairs") or 0)
    scan["observed_base_fee_cost_positive_observations"] += int(
        segment.get("observed_base_fee_cost_positive_pairs") or 0
    )
    scan["invalid_reason_counts"].update(segment.get("invalid_reason_counts") or {})
    previous = str(scan.get("segment_chain_sha256") or "")
    scan["segment_chain_sha256"] = hashlib.sha256(f"{previous}:{segment_hash}".encode("ascii")).hexdigest()


def _manifest_payload(
    *,
    run_id: str,
    run_dir: Path,
    segment_dir: Path,
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
        "quality_complete": False,
        "research_only": True,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "started_at_utc": started_at_utc,
        "updated_at_utc": _iso_utc(time.time()),
        "finished_at_utc": None,
        "stopped_at_utc": None,
        "run_dir": str(run_dir),
        "segments_dir": str(segment_dir),
        "manifest_path": str(manifest_path),
        "plan_path": str(plan_file),
        "plan_sha256": plan_sha256,
        "collection_contract": plan["collection_contract"],
        "sealed_universe": plan["sealed_universe"],
        "elapsed_active_sec": elapsed_active_sec,
        "resume_count": resume_count,
        **_scan_manifest_fields(scan),
    }


def _manifest_progress(
    scan: dict[str, Any],
    *,
    elapsed_active_sec: float,
    last_segment_path: Path | None,
    last_segment_sha256: str | None,
    resume_count: int,
) -> dict[str, Any]:
    return {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "elapsed_active_sec": elapsed_active_sec,
        "resume_count": resume_count,
        "last_segment_path": str(last_segment_path) if last_segment_path else None,
        "last_segment_sha256": last_segment_sha256,
        **_scan_manifest_fields(scan),
    }


def _scan_manifest_fields(scan: dict[str, Any]) -> dict[str, Any]:
    attempts = int(scan["attempt_cycle_count"])
    failed = int(scan["failed_cycle_count"])
    return {
        "attempt_cycle_count": attempts,
        "valid_cycle_count": int(scan["valid_cycle_count"]),
        "failed_cycle_count": failed,
        "attempt_error_ratio": failed / attempts if attempts else 0.0,
        "pair_rows": int(scan["pair_rows"]),
        "cost_positive_observations": int(scan["cost_positive_observations"]),
        "observed_base_fee_cost_positive_observations": int(
            scan["observed_base_fee_cost_positive_observations"]
        ),
        "segment_chain_sha256": str(scan.get("segment_chain_sha256") or ""),
        "invalid_reason_counts": dict(sorted(scan["invalid_reason_counts"].items())),
    }


def _validate_resume_manifest(
    manifest: dict[str, Any],
    run_id: str,
    plan_sha256: str,
    scan: dict[str, Any],
) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("mode") != MANIFEST_MODE:
        raise ValueError("resume manifest schema/mode mismatch")
    if manifest.get("run_id") != run_id or manifest.get("plan_sha256") != plan_sha256:
        raise ValueError("resume manifest provenance mismatch")
    if manifest.get("final") is True:
        raise ValueError("cannot resume final forward OOS run")
    if int(manifest.get("attempt_cycle_count") or 0) > int(scan["attempt_cycle_count"]):
        raise ValueError("resume manifest is ahead of immutable segments")


def _quality_complete(
    scan: dict[str, Any],
    elapsed_active_sec: float,
    target_valid_cycles: int,
    min_active_span_sec: float,
    max_attempt_error_ratio: float,
) -> bool:
    attempts = int(scan["attempt_cycle_count"])
    failed = int(scan["failed_cycle_count"])
    error_ratio = failed / attempts if attempts else 1.0
    return (
        elapsed_active_sec >= min_active_span_sec
        and int(scan["valid_cycle_count"]) >= target_valid_cycles
        and error_ratio <= max_attempt_error_ratio
    )


def _sleep_interruptibly(
    seconds: float,
    stop_requested: Callable[[], bool],
    sleep_fn: Callable[[float], None],
) -> None:
    remaining = max(0.0, seconds)
    while remaining > 0 and not stop_requested():
        step = min(1.0, remaining)
        sleep_fn(step)
        remaining -= step


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible/resumable MEXC/Gate linear-perp forward-OOS collector")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confirmed-forward-oos-collect", action="store_true")
    args = parser.parse_args()
    if not args.confirmed_forward_oos_collect:
        parser.error("--confirmed-forward-oos-collect is required; use the PlanOnly wrapper before a real collect")

    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, request_stop)
        except (OSError, ValueError):
            pass
    manifest = collect_forward_oos(
        args.plan,
        args.output_root,
        args.run_id,
        resume=args.resume,
        stop_requested=stop_event.is_set,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0 if manifest.get("final") else 130


if __name__ == "__main__":
    raise SystemExit(main())
