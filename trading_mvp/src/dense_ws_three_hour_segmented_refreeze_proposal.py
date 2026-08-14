from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import continuous_production
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from trading_mvp.src import continuous_production


SCHEMA = "trading_mvp_dense_ws_three_hour_segmented_refreeze_proposal_v1"
HYPOTHESIS_ID = "dense_ws_microstructure_regime_filter_v1"
DATA_TYPE = "DENSE_WS_SEGMENTED"
PIT_DATA_TYPE = "PIT_UNIVERSE_V2_FORWARD"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PRESERVED_CONTRACT_KEYS = (
    "universe_contract",
    "raw_schema_contract",
    "segment_validity_contract",
    "causal_regime_contract",
    "execution_sampling_contract",
    "cost_risk_no_grid_contract",
    "evidence_and_acceptance_contract",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonical_proposal_hash(proposal: Mapping[str, Any]) -> str:
    payload = {
        key: value for key, value in proposal.items() if key != "proposal_hash"
    }
    return _canonical_hash(payload)


def _canonical_document_hash(document: Mapping[str, Any], *, excluded_key: str) -> str:
    payload = {key: value for key, value in document.items() if key != excluded_key}
    return _canonical_hash(payload)


def _normalize_sha256(value: Any, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return normalized


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path, *, label: str) -> tuple[Path, dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is missing: {target}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {target}")
    return target, value


def _verify_file_hash(path: Path, expected: Any, *, label: str) -> str:
    expected_hash = _normalize_sha256(expected, label=f"expected {label} SHA-256")
    observed_hash = _sha256_file(path)
    if observed_hash != expected_hash:
        raise ValueError(
            f"{label} file SHA-256 mismatch: expected {expected_hash}, "
            f"observed {observed_hash}"
        )
    return observed_hash


def _write_json_immutable(path: str | Path, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(target, flags)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite immutable proposal: {target}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _expect_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _validate_source_contract(
    contract: Mapping[str, Any],
    *,
    expected_contract_hash: str,
) -> Mapping[str, Any]:
    if contract.get("schema") != "trading_mvp_dense_ws_microstructure_contract_v1":
        raise ValueError("source contract schema mismatch")
    if contract.get("mode") != "PlanOnly":
        raise ValueError("source contract must remain PlanOnly")
    if contract.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("source contract hypothesis mismatch")
    if contract.get("data_type") != DATA_TYPE:
        raise ValueError("source contract data type mismatch")
    if contract.get("actual_collection_allowed") is not False:
        raise ValueError("source contract must remain non-executable")
    if contract.get("network_access") is not False:
        raise ValueError("source contract must remain network-disabled")

    bound_hash = _normalize_sha256(
        contract.get("contract_hash"),
        label="source contract contract_hash",
    )
    if bound_hash != expected_contract_hash:
        raise ValueError("source contract hash binding mismatch")
    observed_canonical = _canonical_document_hash(
        contract,
        excluded_key="contract_hash",
    )
    if observed_canonical != expected_contract_hash:
        raise ValueError("source contract canonical hash mismatch")

    source_candidate = _expect_mapping(
        contract.get("source_candidate"),
        label="source_candidate",
    )
    frozen = _expect_mapping(
        source_candidate.get("frozen_candidate"),
        label="source_candidate.frozen_candidate",
    )
    if int(frozen.get("minimum_writer_sec") or 0) != 86_400:
        raise ValueError("source minimum writer duration must remain 86400 seconds")
    if int(frozen.get("target_writer_sec") or 0) != 86_400:
        raise ValueError("source target writer duration must remain 86400 seconds")
    if int(frozen.get("segment_sec") or 0) != 3_600:
        raise ValueError("source durable segment duration must remain 3600 seconds")
    if frozen.get("uninterrupted_required") is not True:
        raise ValueError("source contract is not the uninterrupted campaign preimage")

    universe = _expect_mapping(
        contract.get("universe_contract"),
        label="universe_contract",
    )
    venues = {str(item) for item in universe.get("venues") or []}
    if venues != {"mexc", "gateio"}:
        raise ValueError("source universe must remain exactly MEXC and Gate")
    if universe.get("quote") != "USDT" or universe.get("market_type") != "spot":
        raise ValueError("source universe quote or market type changed")

    no_grid = _expect_mapping(
        _expect_mapping(
            contract.get("cost_risk_no_grid_contract"),
            label="cost_risk_no_grid_contract",
        ).get("no_grid"),
        label="cost_risk_no_grid_contract.no_grid",
    )
    if no_grid.get("grid_search") is not False or no_grid.get("retune") is not False:
        raise ValueError("source contract must remain no-grid and no-retune")

    for key in PRESERVED_CONTRACT_KEYS:
        _expect_mapping(contract.get(key), label=key)
    return frozen


def _validate_source_plan(
    plan: Mapping[str, Any],
    *,
    expected_plan_hash: str,
    expected_contract_hash: str,
) -> int:
    if plan.get("schema") != "trading_mvp_dense_ws_campaign_planonly_v1":
        raise ValueError("source plan schema mismatch")
    if plan.get("mode") != "PlanOnly":
        raise ValueError("source plan must remain PlanOnly")
    if plan.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("source plan hypothesis mismatch")
    if plan.get("actual_collection_allowed") is not False:
        raise ValueError("source plan must remain non-executable")
    if plan.get("network_access") is not False:
        raise ValueError("source plan must remain network-disabled")
    if str(plan.get("approval_state") or "") == "APPROVED":
        raise ValueError("source plan must not carry execution approval")

    bound_hash = _normalize_sha256(plan.get("plan_hash"), label="source plan plan_hash")
    if bound_hash != expected_plan_hash:
        raise ValueError("source plan hash binding mismatch")
    if _canonical_document_hash(plan, excluded_key="plan_hash") != expected_plan_hash:
        raise ValueError("source plan canonical hash mismatch")

    contract_binding = _expect_mapping(plan.get("contract"), label="plan.contract")
    if contract_binding.get("contract_hash") != expected_contract_hash:
        raise ValueError("source plan contract hash mismatch")
    window = _expect_mapping(plan.get("window"), label="plan.window")
    maximum = int(window.get("max_runtime_sec") or 0)
    if maximum <= 0:
        raise ValueError("source plan max_runtime_sec must be positive")
    return maximum


def _validate_policies(
    continuous_policy: Mapping[str, Any],
    autopilot_policy: Mapping[str, Any],
) -> None:
    if continuous_policy.get("schema") != continuous_production.POLICY_SCHEMA:
        raise ValueError("continuous policy schema mismatch")
    run_windows = _expect_mapping(
        continuous_policy.get("run_windows"),
        label="continuous policy run_windows",
    )
    weekend = _expect_mapping(run_windows.get("weekend"), label="run_windows.weekend")
    if weekend.get("fresh_start_allowed_inside_open_envelope") is not True:
        raise ValueError("weekend fresh segmented starts must be explicitly allowed")
    invariants = _expect_mapping(
        continuous_policy.get("invariants"),
        label="continuous policy invariants",
    )
    required = {
        "single_market_data_writer": True,
        "grid_and_retune_forbidden": True,
        "live_orders": False,
        "private_api_keys": False,
        "real_capital": False,
        "leverage": False,
        "margin": False,
    }
    for key, expected in required.items():
        if invariants.get(key) is not expected:
            raise ValueError(f"continuous policy invariant changed: {key}")
    if not str(autopilot_policy.get("policy_id") or ""):
        raise ValueError("autopilot policy_id is missing")


def _validate_pit_pointer(
    pointer: Mapping[str, Any],
    *,
    expected_plan_hash: str,
    runtime_status: str,
) -> None:
    if pointer.get("schema") != "trading_mvp_autopilot_schedule_pointer_v1":
        raise ValueError("PIT pointer schema mismatch")
    if pointer.get("project") != "trading_mvp" or pointer.get("status") != "ACTIVE":
        raise ValueError("PIT pointer is not active for trading_mvp")
    if pointer.get("data_type") != PIT_DATA_TYPE:
        raise ValueError("PIT pointer data type mismatch")
    if pointer.get("plan_hash") != expected_plan_hash:
        raise ValueError("PIT pointer plan hash mismatch")
    if runtime_status != "NO_PENDING_SEGMENT":
        raise ValueError(
            "PIT runtime status must be NO_PENDING_SEGMENT for proposal generation"
        )


def _next_fitting_start(
    policy: dict[str, Any],
    *,
    cursor: datetime,
    max_runtime_sec: int,
) -> tuple[datetime, dict[str, Any]]:
    for _ in range(32):
        window = continuous_production.resolve_run_window(
            policy,
            observed_at_utc=cursor.astimezone(timezone.utc).isoformat(),
        )
        if window.get("status") != "OPEN":
            cursor = _parse_timestamp(
                window.get("next_opens_at_local"),
                label="next_opens_at_local",
            )
            continue
        hard_deadline = _parse_timestamp(
            window.get("hard_deadline_local"),
            label="hard_deadline_local",
        )
        if cursor + timedelta(seconds=max_runtime_sec) <= hard_deadline:
            return cursor, window
        cursor = hard_deadline
    raise ValueError("unable to find a policy window for bounded Dense segments")


def _build_segments(
    policy: dict[str, Any],
    *,
    requested_start: datetime,
    minimum_writer_sec: int,
    writer_sec_per_run: int,
    max_runtime_sec_per_run: int,
    inter_run_gap_sec: int,
    full_segment_sec: int,
    terminal_partial_min_sec: int,
) -> list[dict[str, Any]]:
    run_count = math.ceil(minimum_writer_sec / writer_sec_per_run)
    full_segments = writer_sec_per_run // full_segment_sec
    terminal_partial = writer_sec_per_run % full_segment_sec
    if full_segments <= 0:
        raise ValueError("each bounded run must contain at least one full segment")
    if terminal_partial and terminal_partial < terminal_partial_min_sec:
        raise ValueError("terminal partial segment is below the frozen minimum")

    cursor = requested_start
    segments: list[dict[str, Any]] = []
    campaign_date = requested_start.date().strftime("%Y%m%d")
    for sequence in range(1, run_count + 1):
        start, _ = _next_fitting_start(
            policy,
            cursor=cursor,
            max_runtime_sec=max_runtime_sec_per_run,
        )
        runtime = continuous_production.validate_runtime_request(
            policy,
            requested_start_local=start.isoformat(),
            expected_duration_sec=writer_sec_per_run,
            max_runtime_sec=max_runtime_sec_per_run,
        )
        writer_end = start + timedelta(seconds=writer_sec_per_run)
        hard_end = start + timedelta(seconds=max_runtime_sec_per_run)
        segments.append(
            {
                "sequence": sequence,
                "run_id": (
                    f"{HYPOTHESIS_ID}_{campaign_date}_segmented_3h_v1_s{sequence:02d}"
                ),
                "start_local": start.isoformat(),
                "writer_end_local": writer_end.isoformat(),
                "hard_end_local": hard_end.isoformat(),
                "writer_duration_sec": writer_sec_per_run,
                "max_runtime_sec": max_runtime_sec_per_run,
                "finalization_headroom_sec": (
                    max_runtime_sec_per_run - writer_sec_per_run
                ),
                "full_durable_segments_planned": full_segments,
                "terminal_partial_sec": terminal_partial,
                "window_id": runtime["window_id"],
                "window_type": runtime["window_type"],
                "visible_terminal_required": True,
                "single_global_writer_required": True,
                "launch_authorized": False,
                "stopped_incomplete_retry_authorized": False,
            }
        )
        cursor = hard_end + timedelta(seconds=inter_run_gap_sec)
    return segments


def build_proposal(
    *,
    source_contract_path: str | Path,
    expected_source_contract_sha256: str,
    expected_source_contract_hash: str,
    source_plan_path: str | Path,
    expected_source_plan_sha256: str,
    expected_source_plan_hash: str,
    continuous_policy_path: str | Path,
    expected_continuous_policy_sha256: str,
    autopilot_policy_path: str | Path,
    expected_autopilot_policy_sha256: str,
    pit_pointer_path: str | Path,
    expected_pit_pointer_sha256: str,
    expected_pit_plan_hash: str,
    pit_runtime_status: str,
    pit_guard_observed_at_utc: str,
    requested_start_local: str,
    generated_at_utc: str,
    output_path: str | Path,
    current_per_run_cap_sec: int = 10_800,
    writer_sec_per_run: int = 9_900,
    finalization_headroom_sec: int = 900,
    inter_run_gap_sec: int = 300,
) -> dict[str, Any]:
    if current_per_run_cap_sec <= 0 or current_per_run_cap_sec > 10_800:
        raise ValueError("current per-run cap must be in (0, 10800]")
    if writer_sec_per_run <= 0 or writer_sec_per_run >= current_per_run_cap_sec:
        raise ValueError("writer duration must be positive and below the per-run cap")
    if current_per_run_cap_sec - writer_sec_per_run != finalization_headroom_sec:
        raise ValueError("finalization headroom must fill the bounded runtime envelope")
    if finalization_headroom_sec < 900:
        raise ValueError("finalization headroom must be at least 900 seconds")
    if inter_run_gap_sec < 300:
        raise ValueError("inter-run global writer gap must be at least 300 seconds")

    expected_contract_hash = _normalize_sha256(
        expected_source_contract_hash,
        label="expected source contract hash",
    )
    expected_plan_hash = _normalize_sha256(
        expected_source_plan_hash,
        label="expected source plan hash",
    )
    expected_pit_hash = _normalize_sha256(
        expected_pit_plan_hash,
        label="expected PIT plan hash",
    )

    contract_target, contract = _read_json(
        source_contract_path,
        label="source contract",
    )
    contract_file_hash = _verify_file_hash(
        contract_target,
        expected_source_contract_sha256,
        label="source contract",
    )
    frozen = _validate_source_contract(
        contract,
        expected_contract_hash=expected_contract_hash,
    )

    plan_target, plan = _read_json(source_plan_path, label="source plan")
    plan_file_hash = _verify_file_hash(
        plan_target,
        expected_source_plan_sha256,
        label="source plan",
    )
    source_plan_max_runtime_sec = _validate_source_plan(
        plan,
        expected_plan_hash=expected_plan_hash,
        expected_contract_hash=expected_contract_hash,
    )
    if source_plan_max_runtime_sec <= current_per_run_cap_sec:
        raise ValueError("source plan does not exceed the current per-run cap")

    continuous_target, continuous_policy = _read_json(
        continuous_policy_path,
        label="continuous policy",
    )
    continuous_file_hash = _verify_file_hash(
        continuous_target,
        expected_continuous_policy_sha256,
        label="continuous policy",
    )
    autopilot_target, autopilot_policy = _read_json(
        autopilot_policy_path,
        label="autopilot policy",
    )
    autopilot_file_hash = _verify_file_hash(
        autopilot_target,
        expected_autopilot_policy_sha256,
        label="autopilot policy",
    )
    _validate_policies(continuous_policy, autopilot_policy)

    pointer_target, pointer = _read_json(pit_pointer_path, label="PIT pointer")
    pointer_file_hash = _verify_file_hash(
        pointer_target,
        expected_pit_pointer_sha256,
        label="PIT pointer",
    )
    _validate_pit_pointer(
        pointer,
        expected_plan_hash=expected_pit_hash,
        runtime_status=str(pit_runtime_status),
    )

    requested_start = _parse_timestamp(
        requested_start_local,
        label="requested_start_local",
    )
    generated_at = _parse_timestamp(generated_at_utc, label="generated_at_utc")
    guard_observed_at = _parse_timestamp(
        pit_guard_observed_at_utc,
        label="pit_guard_observed_at_utc",
    )
    if generated_at < guard_observed_at:
        raise ValueError("proposal generation cannot predate the PIT guard snapshot")

    segment_validity = _expect_mapping(
        contract.get("segment_validity_contract"),
        label="segment_validity_contract",
    )
    minimums = _expect_mapping(
        segment_validity.get("campaign_minimums"),
        label="segment_validity_contract.campaign_minimums",
    )
    minimum_writer_sec = int(minimums.get("writer_duration_sec") or 0)
    full_segment_sec = int(segment_validity.get("full_segment_sec") or 0)
    terminal_partial_min_sec = int(
        segment_validity.get("terminal_partial_segment_min_sec") or 0
    )
    segments = _build_segments(
        continuous_policy,
        requested_start=requested_start,
        minimum_writer_sec=minimum_writer_sec,
        writer_sec_per_run=writer_sec_per_run,
        max_runtime_sec_per_run=current_per_run_cap_sec,
        inter_run_gap_sec=inter_run_gap_sec,
        full_segment_sec=full_segment_sec,
        terminal_partial_min_sec=terminal_partial_min_sec,
    )
    total_writer_sec = sum(int(item["writer_duration_sec"]) for item in segments)
    total_full_segments = sum(
        int(item["full_durable_segments_planned"]) for item in segments
    )
    minimum_valid_segments = int(minimums.get("valid_full_segments") or 0)
    if total_writer_sec < minimum_writer_sec:
        raise ValueError("bounded schedule does not satisfy campaign writer minimum")
    if total_full_segments < minimum_valid_segments:
        raise ValueError("bounded schedule does not satisfy valid full segment minimum")

    preserved_hashes = {
        key: _canonical_hash(contract[key]) for key in PRESERVED_CONTRACT_KEYS
    }
    proposal_id = (
        f"{HYPOTHESIS_ID}_{requested_start.date().strftime('%Y%m%d')}_"
        "segmented_3h_refreeze_v1"
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "proposal_id": proposal_id,
        "generated_at_utc": generated_at.isoformat(),
        "status": "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL",
        "campaign_id": plan.get("campaign_id"),
        "hypothesis_id": HYPOTHESIS_ID,
        "data_type": DATA_TYPE,
        "purpose": (
            "Replace only the expired uninterrupted runtime schedule with bounded "
            "three-hour envelopes while preserving the frozen research contracts."
        ),
        "authorization_boundary": {
            "proposal_preparation_authorized": True,
            "implementation_authorized": False,
            "contract_refreeze_authorized": False,
            "runtime_manifest_creation_authorized": False,
            "collector_launch_authorized": False,
            "network_access": False,
            "approval_receipt_created": False,
            "output_namespace_created": False,
            "market_data_read": False,
            "returns_or_pnl_read": False,
            "oos_read": False,
            "grid_or_retune": False,
            "paper_or_live": False,
            "private_api_keys": False,
            "real_capital": False,
            "leverage_or_margin": False,
            "stopped_incomplete_retry_authorized": False,
        },
        "source_bindings": {
            "source_contract": {
                "path": str(contract_target),
                "file_sha256": contract_file_hash,
                "contract_hash": expected_contract_hash,
            },
            "source_plan": {
                "path": str(plan_target),
                "file_sha256": plan_file_hash,
                "plan_hash": expected_plan_hash,
            },
            "continuous_policy": {
                "path": str(continuous_target),
                "file_sha256": continuous_file_hash,
            },
            "autopilot_policy": {
                "path": str(autopilot_target),
                "file_sha256": autopilot_file_hash,
                "policy_id": autopilot_policy.get("policy_id"),
            },
        },
        "preserved_contract_hashes": preserved_hashes,
        "source_runtime_incompatibility": {
            "source_uninterrupted_required": frozen.get("uninterrupted_required"),
            "source_target_writer_sec": frozen.get("target_writer_sec"),
            "source_minimum_writer_sec": frozen.get("minimum_writer_sec"),
            "source_plan_max_runtime_sec": source_plan_max_runtime_sec,
            "current_per_run_cap_sec": current_per_run_cap_sec,
            "source_plan_launchable": False,
            "source_plan_resume_allowed": False,
            "material_schedule_contract_change": True,
            "reason": (
                "The source plan requires one uninterrupted 24-hour writer and "
                "exceeds the current three-hour maximum for every new run."
            ),
        },
        "proposed_schedule_contract": {
            "requested_start_local": requested_start.isoformat(),
            "per_run_cap_sec": current_per_run_cap_sec,
            "writer_sec_per_run": writer_sec_per_run,
            "finalization_headroom_sec": finalization_headroom_sec,
            "inter_run_global_writer_gap_sec": inter_run_gap_sec,
            "minimum_writer_sec": minimum_writer_sec,
            "total_writer_sec": total_writer_sec,
            "total_valid_full_segments_planned": total_full_segments,
            "run_count": len(segments),
            "last_hard_end_local": segments[-1]["hard_end_local"],
            "segments": segments,
        },
        "pit_pointer_binding": {
            "path": str(pointer_target),
            "file_sha256": pointer_file_hash,
            "plan_path": pointer.get("plan_path"),
            "plan_hash": expected_pit_hash,
            "runtime_status": pit_runtime_status,
            "guard_observed_at_utc": guard_observed_at.isoformat(),
            "pointer_change_invalidates_remaining_schedule": True,
            "due_pit_segment_has_priority": True,
            "schedule_extension_activated": False,
            "automatic_pit_extension_allowed": False,
        },
        "scientific_impact": {
            "uninterrupted_market_day_equivalence_claimed": False,
            "planned_gaps_excluded_from_writer_time": True,
            "each_run_independently_finalized": True,
            "invalid_segments_never_stitched_as_valid_evidence": True,
            "aggregate_campaign_quality_required_before_any_consumer": True,
            "frozen_universe_schema_signal_cost_risk_and_acceptance_unchanged": True,
            "schedule_change_requires_exact_user_review": True,
        },
        "approval_checkpoint": {
            "phase_1_required": (
                "exact proposal-hash and proposal-file-SHA-bound approval for "
                "segmented contract/runtime implementation and immutable refreeze"
            ),
            "phase_1_does_not_authorize_collection": True,
            "phase_2_required": (
                "separate exact immutable plan/manifest-bound visible launch approval"
            ),
            "one_approval_may_cover_only_explicitly_listed_segments": True,
            "any_hash_scope_window_runtime_disk_or_pointer_change_requires_new_approval": True,
            "stopped_incomplete_requires_new_exact_approval": True,
        },
        "invalidation_conditions": [
            "PIT pointer file hash or plan hash changes",
            "PIT runtime status is not NO_PENDING_SEGMENT",
            "continuous or autopilot policy file hash changes",
            "source contract or source plan hash changes",
            "per-run maximum exceeds 10800 seconds",
            "venue, universe, schema, signal, cost, risk or acceptance contract changes",
            "another global market-data writer is active",
            "weekly quota is at or below 15 percent or telemetry is stale",
        ],
        "next_allowed_action": (
            "request_exact_proposal_bound_segmented_refreeze_implementation_approval"
        ),
        "proposal_hash_method": "sha256_canonical_json_excluding_proposal_hash",
    }
    payload["proposal_hash"] = canonical_proposal_hash(payload)
    _write_json_immutable(output_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a fail-closed three-hour Dense WS refreeze proposal."
    )
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--expected-source-contract-sha256", required=True)
    parser.add_argument("--expected-source-contract-hash", required=True)
    parser.add_argument("--source-plan", type=Path, required=True)
    parser.add_argument("--expected-source-plan-sha256", required=True)
    parser.add_argument("--expected-source-plan-hash", required=True)
    parser.add_argument("--continuous-policy", type=Path, required=True)
    parser.add_argument("--expected-continuous-policy-sha256", required=True)
    parser.add_argument("--autopilot-policy", type=Path, required=True)
    parser.add_argument("--expected-autopilot-policy-sha256", required=True)
    parser.add_argument("--pit-pointer", type=Path, required=True)
    parser.add_argument("--expected-pit-pointer-sha256", required=True)
    parser.add_argument("--expected-pit-plan-hash", required=True)
    parser.add_argument("--pit-runtime-status", required=True)
    parser.add_argument("--pit-guard-observed-at-utc", required=True)
    parser.add_argument("--requested-start-local", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_proposal(
        source_contract_path=args.source_contract,
        expected_source_contract_sha256=args.expected_source_contract_sha256,
        expected_source_contract_hash=args.expected_source_contract_hash,
        source_plan_path=args.source_plan,
        expected_source_plan_sha256=args.expected_source_plan_sha256,
        expected_source_plan_hash=args.expected_source_plan_hash,
        continuous_policy_path=args.continuous_policy,
        expected_continuous_policy_sha256=args.expected_continuous_policy_sha256,
        autopilot_policy_path=args.autopilot_policy,
        expected_autopilot_policy_sha256=args.expected_autopilot_policy_sha256,
        pit_pointer_path=args.pit_pointer,
        expected_pit_pointer_sha256=args.expected_pit_pointer_sha256,
        expected_pit_plan_hash=args.expected_pit_plan_hash,
        pit_runtime_status=args.pit_runtime_status,
        pit_guard_observed_at_utc=args.pit_guard_observed_at_utc,
        requested_start_local=args.requested_start_local,
        generated_at_utc=args.generated_at_utc,
        output_path=args.output,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
