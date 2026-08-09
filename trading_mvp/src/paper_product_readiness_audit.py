from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from paper_code_provenance import validate_code_manifest
from paper_public_readonly_probe import (
    validate_probe_evidence,
    validate_probe_plan,
)


AUDIT_SCHEMA = "trading_mvp_paper_product_readiness_audit_v3"
AUDIT_SCHEMA_V4 = "trading_mvp_paper_product_readiness_audit_v4"
AUDIT_SCHEMA_V5 = "trading_mvp_paper_product_readiness_audit_v5"
AUDIT_SCHEMA_V6 = "trading_mvp_paper_product_readiness_audit_v6"
AUDIT_SCHEMA_V7 = "trading_mvp_paper_product_readiness_audit_v7"
AUDIT_SCHEMA_V8 = "trading_mvp_paper_product_readiness_audit_v8"
AUDIT_SCHEMA_V9 = "trading_mvp_paper_product_readiness_audit_v9"
AUDIT_SCHEMA_V10 = "trading_mvp_paper_product_readiness_audit_v10"
AUDIT_SCHEMA_V11 = "trading_mvp_paper_product_readiness_audit_v11"
COMPONENT_REQUIREMENTS: dict[str, tuple[str, str, Any]] = {
    "fast-regression-lane-v1.json": (
        "schema",
        "trading_mvp_fast_regression_lane_result_v1",
        None,
    ),
    "paper-public-reader-contract-v1.json": (
        "status",
        "FROZEN_DESIGN_NO_NETWORK_REQUESTS",
        None,
    ),
    "paper-public-reader-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_READER_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-cache-idempotency-v1.json": (
        "verdict",
        "CONTENT_ADDRESSED_CACHE_IDEMPOTENT_AND_HASH_BOUND",
        None,
    ),
    "pit-train-progress-monitor-v1.json": (
        "schema",
        "trading_mvp_pit_train_progress_monitor_v1",
        None,
    ),
    "paper-code-provenance-merkle-v1.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "paper-forward-failure-runbook-v1.json": (
        "verdict",
        "FAILURE_RUNBOOK_FROZEN_FAIL_CLOSED",
        None,
    ),
    "paper-product-readiness-audit-v2.json": (
        "verdict",
        "FIXTURE_PAPER_PRODUCT_READY_EVIDENCE_GATES_BLOCK_FORWARD_AND_LIVE",
        None,
    ),
}
COMPONENT_REQUIREMENTS_V4: dict[str, tuple[str, str, Any]] = {
    "fast-regression-lane-v1.json": (
        "schema",
        "trading_mvp_fast_regression_lane_result_v1",
        None,
    ),
    "paper-public-reader-contract-v1.json": (
        "status",
        "FROZEN_DESIGN_NO_NETWORK_REQUESTS",
        None,
    ),
    "paper-public-reader-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_READER_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-cache-idempotency-v1.json": (
        "verdict",
        "CONTENT_ADDRESSED_CACHE_IDEMPOTENT_AND_HASH_BOUND",
        None,
    ),
    "paper-public-retry-rate-limit-fixture-v1.json": (
        "verdict",
        "FIXTURE_RETRY_RATE_LIMIT_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-snapshot-observer-bridge-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_SNAPSHOT_OBSERVER_BRIDGE_ACCEPTED",
        None,
    ),
    "paper-public-transport-adapter-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_TRANSPORT_ADAPTER_ACCEPTED_NO_NETWORK",
        None,
    ),
    "pit-train-progress-monitor-v1.json": (
        "schema",
        "trading_mvp_pit_train_progress_monitor_v1",
        None,
    ),
    "paper-code-provenance-merkle-v2.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "paper-forward-failure-runbook-v1.json": (
        "verdict",
        "FAILURE_RUNBOOK_FROZEN_FAIL_CLOSED",
        None,
    ),
    "paper-product-readiness-audit-v3.json": (
        "schema",
        "trading_mvp_paper_product_readiness_audit_v3",
        None,
    ),
}
COMPONENT_REQUIREMENTS_V5: dict[str, tuple[str, str, Any]] = {
    **{
        name: requirement
        for name, requirement in COMPONENT_REQUIREMENTS_V4.items()
        if name != "paper-code-provenance-merkle-v2.json"
    },
    "paper-code-provenance-merkle-v3.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "paper-public-reader-transport-wiring-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_READER_TRANSPORT_WIRING_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-streaming-byte-limit-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_STREAMING_BYTE_LIMIT_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-health-contract-binding-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_HEALTH_BINDING_BLOCKED_AS_EXPECTED",
        None,
    ),
    "paper-product-readiness-audit-v4.json": (
        "schema",
        AUDIT_SCHEMA_V4,
        None,
    ),
}
COMPONENT_REQUIREMENTS_V6: dict[str, tuple[str, str, Any]] = {
    **{
        name: requirement
        for name, requirement in COMPONENT_REQUIREMENTS_V5.items()
        if name != "paper-code-provenance-merkle-v3.json"
    },
    "paper-code-provenance-merkle-v4.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "paper-public-system-clock-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_SYSTEM_CLOCK_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-transport-retry-wiring-fixture-v2.json": (
        "verdict",
        "FIXTURE_PUBLIC_TRANSPORT_RETRY_WIRING_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-cache-transport-integration-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_CACHE_TRANSPORT_INTEGRATION_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-product-readiness-audit-v5.json": (
        "schema",
        AUDIT_SCHEMA_V5,
        None,
    ),
}
COMPONENT_REQUIREMENTS_V7: dict[str, tuple[str, str, Any]] = {
    **{
        name: requirement
        for name, requirement in COMPONENT_REQUIREMENTS_V6.items()
        if name != "paper-code-provenance-merkle-v4.json"
    },
    "paper-code-provenance-merkle-v5.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "paper-public-runtime-reader-factory-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_RUNTIME_READER_FACTORY_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-endpoint-contract-parity-fixture-v1.json": (
        "verdict",
        "FIXTURE_PUBLIC_ENDPOINT_CONTRACT_PARITY_ACCEPTED_NO_NETWORK",
        None,
    ),
    "paper-public-readonly-probe-plan-v1.json": (
        "verdict",
        "PUBLIC_READONLY_PROBE_PLAN_FROZEN_NOT_AUTHORIZED",
        None,
    ),
    "paper-product-readiness-audit-v6.json": (
        "schema",
        AUDIT_SCHEMA_V6,
        None,
    ),
}
COMPONENT_REQUIREMENTS_V8: dict[str, tuple[str, str, Any]] = {
    **COMPONENT_REQUIREMENTS_V7,
    "paper-public-reader-contract-v3.json": (
        "status",
        "FROZEN_DESIGN_NO_NETWORK_REQUESTS",
        None,
    ),
    "paper-public-readonly-probe-plan-v3.json": (
        "verdict",
        (
            "PUBLIC_READONLY_PROBE_PLAN_V3_FROZEN_"
            "REQUIRES_ONE_TIME_CRITICAL_AUTHORIZATION"
        ),
        None,
    ),
    "paper-public-readonly-probe-evidence-v3.json": (
        "verdict",
        "PUBLIC_READONLY_PROBE_EVIDENCE_ACCEPTED",
        None,
    ),
    "paper-product-readiness-audit-v7.json": (
        "schema",
        AUDIT_SCHEMA_V7,
        None,
    ),
}
COMPONENT_REQUIREMENTS_V9: dict[str, tuple[str, str, Any]] = {
    **{
        name: requirement
        for name, requirement in COMPONENT_REQUIREMENTS_V8.items()
        if name != "paper-code-provenance-merkle-v5.json"
    },
    "paper-code-provenance-merkle-v6.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "paper-public-probe-evidence-observer-binding-fixture-v1.json": (
        "verdict",
        "PUBLIC_PROBE_EVIDENCE_BOUND_TO_FAIL_CLOSED_OBSERVER_INPUT",
        None,
    ),
    "paper-product-readiness-audit-v8.json": (
        "schema",
        AUDIT_SCHEMA_V8,
        None,
    ),
}
COMPONENT_REQUIREMENTS_V10: dict[str, tuple[str, str, Any]] = {
    **{
        name: requirement
        for name, requirement in COMPONENT_REQUIREMENTS_V9.items()
        if name != "paper-code-provenance-merkle-v6.json"
    },
    "paper-code-provenance-merkle-v7.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "paper-product-readiness-audit-v9.json": (
        "schema",
        AUDIT_SCHEMA_V9,
        None,
    ),
}
COMPONENT_REQUIREMENTS_V11: dict[str, tuple[str, str, Any]] = {
    **{
        name: requirement
        for name, requirement in COMPONENT_REQUIREMENTS_V10.items()
        if name != "paper-code-provenance-merkle-v7.json"
    },
    "paper-code-provenance-merkle-v8.json": (
        "verdict",
        "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        None,
    ),
    "same-scope-strategy-census-v2.json": (
        "verdict",
        "NO_ALTERNATIVE_STRATEGY_CAN_BE_HONESTLY_TESTED_ON_CURRENT_IMMUTABLE_DATA",
        None,
    ),
    "paper-product-readiness-audit-v10-reconciled-v1.json": (
        "schema",
        AUDIT_SCHEMA_V10,
        None,
    ),
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _parse_test_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    matches = re.findall(r"Ran\s+(\d+)\s+tests?", text)
    if not matches or not re.search(r"(?m)^OK(?:\s|$)", text):
        raise ValueError("catalog v2 targeted test log did not pass")
    return {
        "tests_run": int(matches[-1]),
        "status": "PASS",
        "log_path": str(path),
        "log_sha256": sha256_file(path),
    }


def _load_components(
    research_root: Path,
    requirements: Mapping[str, tuple[str, str, Any]] = COMPONENT_REQUIREMENTS,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    payloads: dict[str, dict[str, Any]] = {}
    descriptors: list[dict[str, Any]] = []
    for name, (field, expected, _unused) in requirements.items():
        path = research_root / name
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = _read_json(path)
        if payload.get(field) != expected:
            raise ValueError(
                f"component {name} failed {field}: "
                f"expected={expected}, observed={payload.get(field)}"
            )
        payloads[name] = payload
        descriptors.append(
            {
                "name": name,
                "path": str(path),
                "file_sha256": sha256_file(path),
                "assertion": f"{field}={expected}",
            }
        )
    return payloads, descriptors


def _validate_deterministic_result_hash(
    payload: Mapping[str, Any],
    *,
    label: str,
) -> None:
    deterministic = {
        key: value
        for key, value in payload.items()
        if key not in {"deterministic_result_hash", "generated_at_utc"}
    }
    expected = str(payload.get("deterministic_result_hash") or "").lower()
    actual = sha256_json(deterministic)
    if len(expected) != 64 or expected != actual:
        raise ValueError(f"{label} deterministic result hash mismatch")


def _validate_current_guard_snapshot(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("schema") != "trading_mvp_autopilot_state_v1":
        raise ValueError("v10 guard snapshot schema mismatch")
    if payload.get("status") != "ACTIVE":
        raise ValueError("v10 guard snapshot is not ACTIVE")
    if payload.get("stop_new_actions") is not False:
        raise ValueError("v10 guard snapshot stops new actions")

    usage = payload.get("usage")
    gate = payload.get("gate")
    schedule = payload.get("schedule_window")
    postrun = payload.get("pit_postrun_disposition")
    if not all(
        isinstance(value, Mapping)
        for value in (usage, gate, schedule, postrun)
    ):
        raise ValueError("v10 guard snapshot is incomplete")
    if (
        usage.get("status") != "AVAILABLE"
        or usage.get("decision") != "CONTINUE"
        or float(usage.get("remaining_percent") or 0.0) <= 15.0
    ):
        raise ValueError("v10 guard snapshot weekly quota is not available")
    if gate.get("status") != "READY_FOR_POSTPROCESS":
        raise ValueError("v10 guard snapshot active-run gate is not ready")
    if postrun.get("status") != "COMPLETE":
        raise ValueError("v10 guard snapshot PIT postrun is not complete")
    if postrun.get("new_collector_allowed") is not False:
        raise ValueError("v10 guard snapshot unexpectedly permits a collector")
    if (
        schedule.get("classification") != "PREAPPROVED_SHORT_SEGMENT"
        or schedule.get("data_type") != "PIT_UNIVERSE_V2_FORWARD"
        or schedule.get("status") not in {"WAITING", "DUE"}
        or not str(schedule.get("run_id") or "")
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(schedule.get("plan_hash") or "").lower()
        )
    ):
        raise ValueError("v10 guard snapshot PIT pointer is invalid")
    accepted_dates = int(schedule.get("accepted_distinct_dates") or 0)
    target_dates = int(schedule.get("stage_target_distinct_dates") or 0)
    if accepted_dates < 0 or target_dates <= 0 or accepted_dates >= target_dates:
        raise ValueError("v10 guard snapshot train checkpoint requires review")
    return dict(payload)


def build_readiness_assessment(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
) -> dict[str, Any]:
    progress = components["pit-train-progress-monitor-v1.json"]
    gate = progress["gate"]
    quality = progress["quality"]
    train_eta = progress["train_eta"]
    accepted_dates = int(quality["accepted_distinct_dates"])
    train_target = int(train_eta["target_accepted_dates"])
    if accepted_dates >= train_target:
        raise ValueError(
            "train checkpoint reached; audit must stop before feasibility/OOS"
        )
    fixture_ready = all(
        (
            components["fast-regression-lane-v1.json"].get("successful")
            is True,
            components["paper-public-reader-fixture-v1.json"].get(
                "network_requests"
            )
            == 0,
            components["paper-public-cache-idempotency-v1.json"].get(
                "network_requests"
            )
            == 0,
            int(targeted_tests["tests_run"]) > 0,
        )
    )
    if not fixture_ready:
        raise ValueError("catalog v2 fixture readiness checks failed")
    schedule_waiting = progress.get("decision") in {
        "SCHEDULE_WAIT_OFFLINE_AUTOPILOT_ACTIVE",
        "COUNTDOWN_WINDOW_VISIBLE_START",
    }
    next_catalog = [
        {
            "id": "paper_code_provenance_merkle_v2",
            "priority": 1,
            "reason": "v1 baseline predates the final failure-runbook module"
            if not code_provenance_current
            else "refresh only after the next code change",
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_public_retry_rate_limit_fixture_v1",
            "priority": 2,
            "reason": "contract has retry and token-bucket policy but fixture transport does not yet prove it",
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_public_snapshot_observer_bridge_v1",
            "priority": 3,
            "reason": "venue snapshots are not yet converted into one dual-venue health sample",
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_public_transport_adapter_v1",
            "priority": 4,
            "reason": "real public requests transport remains intentionally unimplemented",
            "maximum_runtime_sec": 1800,
            "network": False,
            "implementation_only": True,
        },
        {
            "id": "paper_product_readiness_audit_v4",
            "priority": 5,
            "reason": "repeat bounded audit after the above components",
            "maximum_runtime_sec": 1800,
            "network": False,
        },
    ]
    return {
        "readiness": {
            "fixture_paper_product": "READY",
            "public_reader_contract": "FROZEN",
            "public_reader_fixture": "PASS",
            "public_snapshot_cache": "PASS",
            "failure_runbook": "PASS",
            "code_provenance": (
                "CURRENT" if code_provenance_current else "STALE_AFTER_NEW_CODE"
            ),
            "public_network_transport": "NOT_IMPLEMENTED",
            "dual_venue_observer_bridge": "NOT_IMPLEMENTED",
            "paper_forward": "BLOCKED_BY_EVIDENCE_GATE",
            "live": "BLOCKED",
        },
        "evidence_gates": {
            "pit_technical_quality_accepted_dates": accepted_dates,
            "pit_train_dates_required": train_target,
            "pit_dates_remaining": train_target - accepted_dates,
            "replay_allowed": bool(gate.get("replay_allowed", False)),
            "edge_proven": False,
            "paper_forward_ready": False,
            "live_review_eligible": False,
        },
        "schedule": {
            "decision": progress["decision"],
            "next_segment": progress.get("next_segment"),
            "schedule_waiting": schedule_waiting,
            "offline_work_must_continue_while_waiting": True,
            "earliest_train_checkpoint_projection": train_eta[
                "earliest_possible_train_checkpoint_date_if_each_future_date_passes"
            ],
        },
        "next_bounded_catalog_requirement": next_catalog,
        "verdict": (
            "FIXTURE_PRODUCT_READY_PUBLIC_DATA_PLANE_INCOMPLETE_"
            "EVIDENCE_GATES_BLOCK_FORWARD_AND_LIVE"
        ),
        "maximum_authority": "OFFLINE_FIXTURE_PAPER_PRODUCT_ONLY",
        "next_allowed_action": (
            "derive_and_install_catalog_v3_then_continue_bounded_offline_work"
            if schedule_waiting
            else "follow_exact_pit_monitor_decision"
        ),
    }


def build_readiness_audit(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    components, descriptors = _load_components(research)
    targeted_tests = _parse_test_log(test_log)
    provenance = components["paper-code-provenance-merkle-v1.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)
    assessment = build_readiness_assessment(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_assessment_v4(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
) -> dict[str, Any]:
    progress = components["pit-train-progress-monitor-v1.json"]
    gate = progress["gate"]
    quality = progress["quality"]
    train_eta = progress["train_eta"]
    accepted_dates = int(quality["accepted_distinct_dates"])
    train_target = int(train_eta["target_accepted_dates"])
    if accepted_dates >= train_target:
        raise ValueError(
            "train checkpoint reached; audit must stop before feasibility/OOS"
        )
    retry = components["paper-public-retry-rate-limit-fixture-v1.json"]
    bridge = components["paper-public-snapshot-observer-bridge-v1.json"]
    transport = components["paper-public-transport-adapter-v1.json"]
    fixture_ready = all(
        (
            components["fast-regression-lane-v1.json"].get("successful")
            is True,
            components["paper-public-reader-fixture-v1.json"].get(
                "network_requests"
            )
            == 0,
            components["paper-public-cache-idempotency-v1.json"].get(
                "network_requests"
            )
            == 0,
            retry.get("network_requests") == 0,
            retry.get("accepted_scenario_count")
            == retry.get("scenario_count"),
            bridge.get("network_requests") == 0,
            bridge.get("oms_mutations") == 0,
            bridge.get("snapshot_hashes_match_fixture") is True,
            transport.get("network_requests") == 0,
            transport.get("adapter_network_capable") is True,
            (
                transport.get("response_byte_limit") or {}
            ).get("declared_oversize_rejected")
            is True,
            int(targeted_tests["tests_run"]) > 0,
            targeted_tests.get("status") == "PASS",
        )
    )
    if not fixture_ready:
        raise ValueError("catalog v3 fixture readiness checks failed")
    schedule_waiting = progress.get("decision") in {
        "SCHEDULE_WAIT_OFFLINE_AUTOPILOT_ACTIVE",
        "COUNTDOWN_WINDOW_VISIBLE_START",
    }
    next_catalog = [
        {
            "id": "paper_code_provenance_merkle_v3",
            "priority": 1,
            "reason": (
                "v2 baseline predates retry, bridge and transport adapter code"
                if not code_provenance_current
                else "refresh only after the next code change"
            ),
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_public_reader_transport_wiring_fixture_v1",
            "priority": 2,
            "reason": (
                "requests adapter is fixture-proven but not yet wired through "
                "the normalized reader end to end"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_public_streaming_byte_limit_fixture_v1",
            "priority": 3,
            "reason": (
                "declared Content-Length overflow is proven; streamed overflow "
                "without Content-Length still needs a bounded fixture"
            ),
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_public_health_contract_binding_fixture_v1",
            "priority": 4,
            "reason": (
                "dual-venue health sample is hash-bound but intentionally has "
                "no frozen health verdict or OMS authority"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_product_readiness_audit_v5",
            "priority": 5,
            "reason": "repeat bounded audit after the remaining runtime fixtures",
            "maximum_runtime_sec": 1800,
            "network": False,
        },
    ]
    return {
        "readiness": {
            "fixture_paper_product": "READY",
            "public_reader_contract": "FROZEN",
            "public_reader_fixture": "PASS",
            "public_snapshot_cache": "PASS",
            "public_retry_rate_limit": "PASS",
            "dual_venue_observer_bridge": "PASS_BRIDGE_ONLY",
            "public_network_transport": (
                "IMPLEMENTED_FIXTURE_TESTED_NOT_NETWORK_PROBED"
            ),
            "failure_runbook": "PASS",
            "code_provenance": (
                "CURRENT" if code_provenance_current else "STALE_AFTER_NEW_CODE"
            ),
            "paper_forward": "BLOCKED_BY_EVIDENCE_GATE",
            "live": "BLOCKED",
        },
        "evidence_gates": {
            "pit_technical_quality_accepted_dates": accepted_dates,
            "pit_train_dates_required": train_target,
            "pit_dates_remaining": train_target - accepted_dates,
            "replay_allowed": bool(gate.get("replay_allowed", False)),
            "edge_proven": False,
            "historical_accept": False,
            "paper_forward_ready": False,
            "live_review_eligible": False,
        },
        "public_data_plane": {
            "network_requests_performed_by_catalog_v3": 0,
            "retry_scenarios_accepted": int(
                retry["accepted_scenario_count"]
            ),
            "snapshot_bridge_health_decision": bridge["health_decision"],
            "snapshot_bridge_oms_transition_allowed": bool(
                bridge["oms_transition_allowed"]
            ),
            "transport_adapter_authority": (
                "IMPLEMENTATION_AND_FIXTURE_ONLY"
            ),
        },
        "schedule": {
            "decision": progress["decision"],
            "next_segment": progress.get("next_segment"),
            "schedule_waiting": schedule_waiting,
            "offline_work_must_continue_while_waiting": True,
            "earliest_train_checkpoint_projection": train_eta[
                "earliest_possible_train_checkpoint_date_if_each_future_date_passes"
            ],
        },
        "next_bounded_catalog_requirement": next_catalog,
        "verdict": (
            "PUBLIC_DATA_PLANE_FIXTURE_READY_RUNTIME_WIRING_INCOMPLETE_"
            "EVIDENCE_GATES_BLOCK_FORWARD_AND_LIVE"
        ),
        "maximum_authority": "OFFLINE_FIXTURE_PAPER_PRODUCT_ONLY",
        "next_allowed_action": (
            "derive_and_install_catalog_v4_then_continue_bounded_offline_work"
            if schedule_waiting
            else "follow_exact_pit_monitor_decision"
        ),
    }


def build_readiness_audit_v4(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V4
    )
    targeted_tests = _parse_test_log(test_log)
    provenance = components["paper-code-provenance-merkle-v2.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)
    assessment = build_readiness_assessment_v4(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V4,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v2",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_assessment_v5(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_readiness_assessment_v4(
        components=components,
        code_provenance_current=code_provenance_current,
        targeted_tests=targeted_tests,
    )
    wiring = components[
        "paper-public-reader-transport-wiring-fixture-v1.json"
    ]
    streaming = components[
        "paper-public-streaming-byte-limit-fixture-v1.json"
    ]
    binding = components[
        "paper-public-health-contract-binding-fixture-v1.json"
    ]
    fixture_ready = all(
        (
            wiring.get("network_requests") == 0,
            int(wiring.get("fixture_session_calls") or 0) == 8,
            wiring.get("responses_closed") is True,
            len(wiring.get("normalized_snapshots") or []) == 2,
            streaming.get("network_requests") == 0,
            (streaming.get("scenario") or {}).get("observed_category")
            == "response_too_large",
            (streaming.get("scenario") or {}).get("response_closed")
            is True,
            binding.get("network_requests") == 0,
            binding.get("oms_mutations") == 0,
            binding.get("oms_transition_allowed") is False,
            (binding.get("health") or {}).get("decision")
            == "BLOCK_TRANSITION",
        )
    )
    if not fixture_ready:
        raise ValueError("catalog v4 runtime wiring readiness checks failed")
    schedule_waiting = bool(base["schedule"]["schedule_waiting"])
    next_catalog = [
        {
            "id": "paper_code_provenance_merkle_v4",
            "priority": 1,
            "reason": (
                "v3 baseline predates transport wiring and health binding code"
                if not code_provenance_current
                else "refresh only after the next code change"
            ),
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_public_system_clock_fixture_v1",
            "priority": 2,
            "reason": (
                "normalized runtime reader still requires an injected fixture "
                "clock; real-time sleep and Retry-After behavior need a "
                "bounded fake-clock contract"
            ),
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_public_transport_retry_wiring_fixture_v2",
            "priority": 3,
            "reason": (
                "prove retry and token-bucket behavior through the requests "
                "adapter plus normalized reader using a fake session"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_public_cache_transport_integration_fixture_v1",
            "priority": 4,
            "reason": (
                "bind normalized transport output to content-addressed cache "
                "without network or mutable OMS state"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_product_readiness_audit_v6",
            "priority": 5,
            "reason": "repeat bounded audit after runtime clock and cache wiring",
            "maximum_runtime_sec": 1800,
            "network": False,
        },
    ]
    return {
        **base,
        "readiness": {
            **base["readiness"],
            "dual_venue_observer_bridge": (
                "PASS_HEALTH_CONTRACT_BOUND_BLOCKED_FIXTURE"
            ),
            "public_network_transport": (
                "WIRED_FIXTURE_TESTED_NOT_NETWORK_PROBED"
            ),
            "code_provenance": (
                "CURRENT"
                if code_provenance_current
                else "STALE_AFTER_NEW_CODE"
            ),
        },
        "public_data_plane": {
            **base["public_data_plane"],
            "network_requests_performed_by_catalog_v4": 0,
            "transport_wiring_fixture_calls": int(
                wiring["fixture_session_calls"]
            ),
            "streaming_byte_limit_classification": streaming["scenario"][
                "observed_category"
            ],
            "health_binding_decision": binding["health"]["decision"],
            "health_binding_oms_transition_allowed": False,
        },
        "next_bounded_catalog_requirement": next_catalog,
        "verdict": (
            "PUBLIC_DATA_PLANE_RUNTIME_FIXTURE_READY_NETWORK_PROBE_"
            "AND_EVIDENCE_GATES_BLOCK_FORWARD_AND_LIVE"
        ),
        "next_allowed_action": (
            "derive_and_install_catalog_v5_then_continue_bounded_offline_work"
            if schedule_waiting
            else "follow_exact_pit_monitor_decision"
        ),
    }


def build_readiness_audit_v5(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V5
    )
    targeted_tests = _parse_test_log(test_log)
    provenance = components["paper-code-provenance-merkle-v3.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)
    assessment = build_readiness_assessment_v5(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V5,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v3",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_assessment_v6(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_readiness_assessment_v5(
        components=components,
        code_provenance_current=code_provenance_current,
        targeted_tests=targeted_tests,
    )
    clock = components["paper-public-system-clock-fixture-v1.json"]
    retry = components[
        "paper-public-transport-retry-wiring-fixture-v2.json"
    ]
    cache = components[
        "paper-public-cache-transport-integration-fixture-v1.json"
    ]
    fixture_ready = all(
        (
            clock.get("network_requests") == 0,
            (clock.get("token_bucket") or {}).get("second_wait_ms") == 500,
            clock.get("retry_after_ms") == 2000,
            retry.get("network_requests") == 0,
            len(retry.get("retry_trace") or []) == 1,
            (retry.get("retry_trace") or [{}])[0].get("reason")
            == "http_503",
            cache.get("network_requests") == 0,
            cache.get("oms_mutations") == 0,
            (cache.get("cache") or {}).get("lookup_status") == "HIT",
            cache.get("snapshot_hash_sha256")
            == cache.get("replay_snapshot_hash_sha256"),
        )
    )
    if not fixture_ready:
        raise ValueError("catalog v5 runtime readiness checks failed")
    schedule_waiting = bool(base["schedule"]["schedule_waiting"])
    next_catalog = [
        {
            "id": "paper_code_provenance_merkle_v5",
            "priority": 1,
            "reason": (
                "v4 baseline predates runtime clock and cache integration code"
                if not code_provenance_current
                else "refresh only after the next code change"
            ),
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_public_runtime_reader_factory_fixture_v1",
            "priority": 2,
            "reason": (
                "bind SystemClock, requests transport and normalized reader "
                "behind one fail-closed factory using a fake session"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_public_endpoint_contract_parity_fixture_v1",
            "priority": 3,
            "reason": (
                "prove every frozen MEXC/Gate endpoint maps to the expected "
                "normalizer and allowlist without network"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_public_readonly_probe_plan_v1",
            "priority": 4,
            "reason": (
                "freeze a bounded public read-only probe plan without "
                "executing network requests"
            ),
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_product_readiness_audit_v7",
            "priority": 5,
            "reason": "repeat bounded audit after runtime factory and probe plan",
            "maximum_runtime_sec": 1800,
            "network": False,
        },
    ]
    return {
        **base,
        "readiness": {
            **base["readiness"],
            "public_network_transport": (
                "OFFLINE_RUNTIME_CHAIN_READY_NOT_NETWORK_PROBED"
            ),
            "public_snapshot_cache": "PASS_TRANSPORT_INTEGRATED",
            "code_provenance": (
                "CURRENT"
                if code_provenance_current
                else "STALE_AFTER_NEW_CODE"
            ),
        },
        "public_data_plane": {
            **base["public_data_plane"],
            "network_requests_performed_by_catalog_v5": 0,
            "runtime_clock": "PASS",
            "transport_retry_wiring": "PASS",
            "cache_transport_replay": "PASS",
        },
        "next_bounded_catalog_requirement": next_catalog,
        "verdict": (
            "PUBLIC_DATA_PLANE_OFFLINE_RUNTIME_READY_NETWORK_PROBE_"
            "AND_EVIDENCE_GATES_BLOCK_FORWARD_AND_LIVE"
        ),
        "next_allowed_action": (
            "derive_and_install_catalog_v6_then_continue_bounded_offline_work"
            if schedule_waiting
            else "follow_exact_pit_monitor_decision"
        ),
    }


def build_readiness_audit_v6(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V6
    )
    targeted_tests = _parse_test_log(test_log)
    provenance = components["paper-code-provenance-merkle-v4.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)
    assessment = build_readiness_assessment_v6(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V6,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v4",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_assessment_v7(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_readiness_assessment_v6(
        components=components,
        code_provenance_current=code_provenance_current,
        targeted_tests=targeted_tests,
    )
    factory = components[
        "paper-public-runtime-reader-factory-fixture-v1.json"
    ]
    parity = components[
        "paper-public-endpoint-contract-parity-fixture-v1.json"
    ]
    plan = components["paper-public-readonly-probe-plan-v1.json"]
    fixture_ready = all(
        (
            factory.get("network_requests") == 0,
            int(factory.get("fixture_session_calls") or 0) == 8,
            (factory.get("factory") or {}).get("clock_type")
            == "SystemClock",
            parity.get("network_requests") == 0,
            int(parity.get("endpoint_count") or 0) == 8,
            (parity.get("venue_counts") or {}).get("mexc") == 4,
            (parity.get("venue_counts") or {}).get("gateio") == 4,
            (plan.get("authorization") or {}).get(
                "network_authorized"
            )
            is False,
            (plan.get("authorization") or {}).get(
                "execution_authorized"
            )
            is False,
            (plan.get("safety") or {}).get(
                "network_requests_performed"
            )
            == 0,
            (plan.get("safety") or {}).get(
                "market_data_writer_started"
            )
            is False,
        )
    )
    if not fixture_ready:
        raise ValueError("catalog v6 offline readiness checks failed")
    plan_path = next(
        descriptor["path"]
        for descriptor in base.get("components", [])
        if descriptor.get("name")
        == "paper-public-readonly-probe-plan-v1.json"
    ) if base.get("components") else str(
        Path(
            r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot"
            r"\research\paper-public-readonly-probe-plan-v1.json"
        )
    )
    critical_checkpoint = {
        "status": "USER_REVIEW_REQUIRED",
        "reason": (
            "the offline public data plane is fixture-ready; executing the "
            "frozen plan would start a public network probe outside the "
            "bounded offline autopilot authority"
        ),
        "requested_action": "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE",
        "plan_path": plan_path,
        "plan_hash_sha256": plan["plan_hash_sha256"],
        "duration_sec": int(plan["probe"]["duration_sec"]),
        "max_runtime_sec": int(plan["probe"]["max_runtime_sec"]),
        "venues": list(plan["probe"]["venues"]),
        "visible_terminal_required": True,
        "public_api_only": True,
        "private_api_keys": False,
        "live_orders": False,
    }
    return {
        **base,
        "readiness": {
            **base["readiness"],
            "public_network_transport": (
                "OFFLINE_RUNTIME_READY_BOUNDED_NETWORK_PROBE_NOT_AUTHORIZED"
            ),
            "public_readonly_probe_plan": "FROZEN_NOT_AUTHORIZED",
            "code_provenance": (
                "CURRENT"
                if code_provenance_current
                else "STALE_AFTER_NEW_CODE"
            ),
        },
        "public_data_plane": {
            **base["public_data_plane"],
            "network_requests_performed_by_catalog_v6": 0,
            "runtime_reader_factory": "PASS",
            "endpoint_contract_parity": "PASS_8_OF_8",
            "readonly_probe_plan": "FROZEN_NOT_EXECUTED",
        },
        "next_bounded_catalog_requirement": [],
        "critical_checkpoint": critical_checkpoint,
        "verdict": (
            "PUBLIC_DATA_PLANE_OFFLINE_READY_USER_REVIEW_REQUIRED_FOR_"
            "BOUNDED_PUBLIC_PROBE_EVIDENCE_GATES_BLOCK_FORWARD_AND_LIVE"
        ),
        "maximum_authority": "OFFLINE_FIXTURE_AND_PLAN_ONLY",
        "next_allowed_action": (
            "USER_REVIEW_REQUIRED_FOR_BOUNDED_PUBLIC_READONLY_PROBE"
        ),
    }


def build_readiness_assessment_v8(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_readiness_assessment_v7(
        components=components,
        code_provenance_current=code_provenance_current,
        targeted_tests=targeted_tests,
    )
    plan = components["paper-public-readonly-probe-plan-v3.json"]
    evidence = components["paper-public-readonly-probe-evidence-v3.json"]
    probe = plan.get("probe")
    compatibility = plan.get("compatibility_scope")
    quality = evidence.get("quality")
    safety = evidence.get("safety")
    result_binding = evidence.get("probe_result")
    if not all(
        isinstance(value, Mapping)
        for value in (
            probe,
            compatibility,
            quality,
            safety,
            result_binding,
        )
    ):
        raise ValueError("v8 public probe plan or evidence block is missing")

    expected_quote_ages = {"mexc": 6000, "gateio": 5000}
    expected_safety = {
        "public_get_only": True,
        "returns_or_pnl_read": False,
        "signals_read": False,
        "oms_mutations": 0,
        "private_api_keys": False,
        "live_orders": False,
        "leverage_or_margin": False,
        "grid_or_retune": False,
        "hypothesis_changed": False,
    }
    expected_snapshot_count = int(probe["max_cycles"]) * len(probe["venues"])
    expected_endpoint_reads = int(probe["planned_endpoint_reads"])
    accepted = all(
        (
            evidence.get("schema")
            == "trading_mvp_paper_public_readonly_probe_evidence_v3",
            evidence.get("next_allowed_action")
            == "paper_product_readiness_audit_v8",
            result_binding.get("plan_hash_sha256")
            == plan.get("plan_hash_sha256"),
            bool(str(result_binding.get("run_id") or "").strip()),
            probe.get("maximum_quote_age_ms_by_venue")
            == expected_quote_ages,
            compatibility.get("maximum_quote_age_ms_by_venue")
            == expected_quote_ages,
            compatibility.get(
                "venue_universe_hypothesis_signal_cost_changed"
            )
            is False,
            compatibility.get("private_live_leverage_margin_changed") is False,
            int(compatibility.get("maximum_runs_for_new_plan_hash") or 0) == 1,
            quality.get("venues") == ["mexc", "gateio"],
            int(quality.get("expected_snapshot_count") or 0)
            == expected_snapshot_count,
            int(quality.get("snapshot_count") or 0)
            == expected_snapshot_count,
            int(quality.get("error_count") or 0) == 0,
            float(quality.get("application_error_rate") or 0.0) == 0.0,
            quality.get("partial_output") is False,
            quality.get("hard_stop_reason") is None,
            int(quality.get("planned_endpoint_reads") or 0)
            == expected_endpoint_reads,
            int(quality.get("network_requests") or 0)
            == expected_endpoint_reads,
            int(quality.get("network_requests") or 0)
            <= int(quality.get("maximum_public_get_attempts") or 0),
            int(quality.get("maximum_public_get_attempts") or 0)
            == int(probe["maximum_public_get_attempts"]),
            quality.get("maximum_quote_age_ms_by_venue")
            == expected_quote_ages,
            dict(safety) == expected_safety,
        )
    )
    if not accepted:
        raise ValueError("v8 public read-only probe evidence checks failed")

    next_catalog = [
        {
            "id": "paper_code_provenance_merkle_v6",
            "priority": 1,
            "reason": (
                "refresh the code-only baseline after v3 probe compatibility "
                "and v8 audit implementation"
            ),
            "maximum_runtime_sec": 1200,
            "network": False,
        },
        {
            "id": "paper_public_probe_evidence_observer_binding_fixture_v1",
            "priority": 2,
            "reason": (
                "bind accepted immutable public probe evidence to a fail-closed "
                "observer input without OMS mutation"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
        {
            "id": "paper_product_readiness_audit_v9",
            "priority": 3,
            "reason": (
                "repeat bounded readiness audit after provenance refresh and "
                "observer evidence binding"
            ),
            "maximum_runtime_sec": 1800,
            "network": False,
        },
    ]
    schedule_waiting = bool(base["schedule"]["schedule_waiting"])
    return {
        **base,
        "readiness": {
            **base["readiness"],
            "public_network_transport": (
                "PUBLIC_READONLY_PROBE_ACCEPTED_BOUNDED_RESEARCH_ONLY"
            ),
            "public_readonly_probe_plan": "V3_EXECUTED_ONCE_EVIDENCE_ACCEPTED",
            "code_provenance": (
                "CURRENT"
                if code_provenance_current
                else "STALE_AFTER_NEW_CODE"
            ),
            "paper_forward": "BLOCKED_BY_EVIDENCE_GATE",
            "live": "BLOCKED",
        },
        "public_data_plane": {
            **base["public_data_plane"],
            "readonly_probe_evidence": "V3_ACCEPTED",
            "readonly_probe_run_id": result_binding["run_id"],
            "readonly_probe_snapshot_count": int(quality["snapshot_count"]),
            "readonly_probe_network_requests": int(quality["network_requests"]),
            "readonly_probe_error_count": int(quality["error_count"]),
            "maximum_quote_age_ms_by_venue": expected_quote_ages,
        },
        "next_bounded_catalog_requirement": next_catalog,
        "critical_checkpoint": None,
        "verdict": (
            "PUBLIC_READONLY_PROBE_EVIDENCE_ACCEPTED_EDGE_AND_FORWARD_"
            "GATES_REMAIN_BLOCKED"
        ),
        "maximum_authority": "PUBLIC_READONLY_RESEARCH_EVIDENCE_ONLY",
        "next_allowed_action": (
            "derive_and_install_catalog_v8_then_continue_bounded_offline_work"
            if schedule_waiting
            else "follow_exact_pit_monitor_decision"
        ),
    }


def build_readiness_assessment_v9(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_readiness_assessment_v8(
        components=components,
        code_provenance_current=code_provenance_current,
        targeted_tests=targeted_tests,
    )
    plan = components["paper-public-readonly-probe-plan-v3.json"]
    evidence = components["paper-public-readonly-probe-evidence-v3.json"]
    binding = components[
        "paper-public-probe-evidence-observer-binding-fixture-v1.json"
    ]
    quality = evidence.get("quality")
    result_binding = evidence.get("probe_result")
    binding_inputs = binding.get("inputs")
    observer_input = binding.get("observer_input")
    if not all(
        isinstance(value, Mapping)
        for value in (
            quality,
            result_binding,
            binding_inputs,
            observer_input,
        )
    ):
        raise ValueError("v9 public probe observer binding block is missing")

    plan_input = binding_inputs.get("probe_plan")
    evidence_input = binding_inputs.get("probe_evidence")
    manifest_input = binding_inputs.get("probe_manifest")
    if not all(
        isinstance(value, Mapping)
        for value in (plan_input, evidence_input, manifest_input)
    ):
        raise ValueError("v9 public probe observer input binding is missing")

    expected_quote_ages = {"mexc": 6000, "gateio": 5000}
    accepted = all(
        (
            binding.get("schema")
            == (
                "trading_mvp_public_probe_evidence_observer_binding_"
                "fixture_v1"
            ),
            binding.get("task_id")
            == "paper_public_probe_evidence_observer_binding_fixture_v1",
            binding.get("verdict")
            == (
                "PUBLIC_PROBE_EVIDENCE_BOUND_TO_FAIL_CLOSED_"
                "OBSERVER_INPUT"
            ),
            binding.get("next_allowed_action")
            == "paper_product_readiness_audit_v9",
            plan_input.get("plan_hash_sha256")
            == plan.get("plan_hash_sha256"),
            observer_input.get("schema")
            == "trading_mvp_public_probe_observer_input_v1",
            observer_input.get("mode")
            == "IMMUTABLE_PUBLIC_PROBE_EVIDENCE_DESCRIPTOR_ONLY",
            observer_input.get("run_id") == result_binding.get("run_id"),
            observer_input.get("plan_hash_sha256")
            == plan.get("plan_hash_sha256"),
            observer_input.get("venues") == quality.get("venues"),
            int(observer_input.get("snapshot_count") or 0)
            == int(quality.get("snapshot_count") or -1),
            int(observer_input.get("network_requests_in_source_probe") or 0)
            == int(quality.get("network_requests") or -1),
            observer_input.get("maximum_quote_age_ms_by_venue")
            == expected_quote_ages,
            observer_input.get("health_decision")
            == "NOT_EVALUATED_DESCRIPTOR_ONLY",
            observer_input.get("oms_transition_allowed") is False,
            observer_input.get("paper_forward_allowed") is False,
            observer_input.get("live_allowed") is False,
            int(binding.get("source_probe_network_requests") or 0)
            == int(quality.get("network_requests") or -1),
            int(
                binding.get("network_requests_performed_by_task")
                if binding.get("network_requests_performed_by_task")
                is not None
                else -1
            )
            == 0,
            binding.get("returns_or_pnl_read") is False,
            binding.get("oos_read") is False,
            binding.get("signals_read") is False,
            binding.get("oms_transition_allowed") is False,
            int(
                binding.get("oms_mutations")
                if binding.get("oms_mutations") is not None
                else -1
            )
            == 0,
            binding.get("paper_forward_started") is False,
            binding.get("private_api_keys") is False,
            binding.get("live_orders") is False,
            binding.get("leverage_or_margin") is False,
            binding.get("grid_or_retune") is False,
            binding.get("hypothesis_changed") is False,
        )
    )
    if not accepted:
        raise ValueError("v9 public probe observer binding checks failed")

    schedule_waiting = bool(base["schedule"]["schedule_waiting"])
    return {
        **base,
        "readiness": {
            **base["readiness"],
            "public_network_transport": (
                "PUBLIC_READONLY_PROBE_BOUND_FAIL_CLOSED_RESEARCH_ONLY"
            ),
            "dual_venue_observer_bridge": (
                "V3_PROBE_EVIDENCE_DESCRIPTOR_BOUND_NO_HEALTH_TRANSITION"
            ),
            "code_provenance": (
                "CURRENT"
                if code_provenance_current
                else "STALE_AFTER_NEW_CODE"
            ),
            "paper_forward": "BLOCKED_BY_EVIDENCE_GATE",
            "live": "BLOCKED",
        },
        "public_data_plane": {
            **base["public_data_plane"],
            "readonly_probe_observer_binding": "PASS_FAIL_CLOSED",
            "observer_binding_hash": binding[
                "deterministic_result_hash"
            ],
            "observer_binding_task_network_requests": int(
                binding["network_requests_performed_by_task"]
            ),
            "observer_binding_oms_mutations": int(
                binding["oms_mutations"]
            ),
            "observer_binding_health_decision": observer_input[
                "health_decision"
            ],
        },
        "offline_gap_assessment": {
            "materially_useful_same_contract_tasks_remaining": False,
            "reason": (
                "accepted public probe evidence is hash-bound to a fail-closed "
                "descriptor; further fixture/provenance cycles would not "
                "advance the frozen edge evidence contract"
            ),
            "new_hypothesis_requires_user_review": True,
            "approved_pit_shadow_schedule_continues": True,
        },
        "next_bounded_catalog_requirement": [],
        "critical_checkpoint": None,
        "verdict": (
            "PUBLIC_PROBE_EVIDENCE_BINDING_COMPLETE_NO_MATERIAL_OFFLINE_"
            "GAPS_EDGE_AND_FORWARD_GATES_REMAIN_BLOCKED"
        ),
        "maximum_authority": "PUBLIC_READONLY_RESEARCH_EVIDENCE_ONLY",
        "next_allowed_action": (
            "WAITING_SCHEDULE_WINDOW_NO_FALLBACK"
            if schedule_waiting
            else "follow_exact_pit_monitor_decision"
        ),
    }


def build_readiness_assessment_v10(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
    guard_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_readiness_assessment_v9(
        components=components,
        code_provenance_current=code_provenance_current,
        targeted_tests=targeted_tests,
    )
    guard = _validate_current_guard_snapshot(guard_snapshot)
    schedule = guard["schedule_window"]
    action_due = bool(guard.get("action_due"))
    accepted_dates = int(schedule["accepted_distinct_dates"])
    target_dates = int(schedule["stage_target_distinct_dates"])
    provenance_refresh_required = not code_provenance_current
    current_schedule = {
        "decision": guard["decision"],
        "guard_status": guard["status"],
        "guard_observed_at_utc": guard["observed_at_utc"],
        "next_segment": {
            "run_id": schedule["run_id"],
            "plan_hash": schedule["plan_hash"],
            "start_local": schedule["start_local"],
            "end_local": schedule["end_local"],
            "duration_sec": int(schedule["duration_sec"]),
            "hard_deadline_local": schedule["hard_deadline_local"],
            "seconds_to_start": int(schedule.get("eta_sec") or 0),
        },
        "accepted_distinct_dates": accepted_dates,
        "stage_target_distinct_dates": target_dates,
        "schedule_waiting": not action_due,
        "offline_work_must_yield_when_due": True,
        "offline_work_allowed_now": not action_due,
    }
    return {
        **base,
        "readiness": {
            **base["readiness"],
            "code_provenance": (
                "CURRENT"
                if code_provenance_current
                else "STALE_AFTER_NEW_CODE"
            ),
        },
        "evidence_gates": {
            **base["evidence_gates"],
            "pit_technical_quality_accepted_dates": accepted_dates,
            "pit_train_dates_required": target_dates,
            "pit_dates_remaining": target_dates - accepted_dates,
        },
        "schedule": current_schedule,
        "long_campaign_branch": {
            "decision": guard["decision"],
            "next_action": guard["next_action"],
            "collector_launch_allowed": False,
            "pit_shadow_track_continues": True,
        },
        "offline_gap_assessment": {
            "materially_useful_same_contract_tasks_remaining": (
                provenance_refresh_required
            ),
            "reason": (
                "corrected dynamic readiness must be frozen and reconciled"
                if provenance_refresh_required
                else (
                    "current code provenance and dynamic PIT readiness are "
                    "refreshed; evidence gates still require scheduled PIT data"
                )
            ),
            "new_hypothesis_requires_user_review": True,
            "approved_pit_shadow_schedule_continues": True,
        },
        "next_bounded_catalog_requirement": (
            [
                {
                    "id": "same_scope_strategy_census_v2",
                    "priority": 1,
                    "reason": (
                        "Recheck alternatives on current metadata without "
                        "creating a new hypothesis."
                    ),
                    "maximum_runtime_sec": 300,
                    "network": False,
                },
                {
                    "id": "paper_code_provenance_merkle_v8",
                    "priority": 2,
                    "reason": "Freeze the corrected readiness implementation.",
                    "maximum_runtime_sec": 300,
                    "network": False,
                },
                {
                    "id": "paper_product_readiness_audit_v11",
                    "priority": 3,
                    "reason": (
                        "Bind current code, strategy census and PIT counters."
                    ),
                    "maximum_runtime_sec": 900,
                    "network": False,
                },
            ]
            if provenance_refresh_required
            else []
        ),
        "critical_checkpoint": None,
        "verdict": (
            "CURRENT_CODE_PROVENANCE_AND_DYNAMIC_PIT_READINESS_REFRESHED_"
            "EDGE_AND_FORWARD_GATES_REMAIN_BLOCKED"
        ),
        "next_allowed_action": (
            "follow_authoritative_guard_due_action"
            if action_due
            else (
                "derive_and_install_catalog_v10_then_continue_bounded_offline_work"
                if provenance_refresh_required
                else "WAITING_SCHEDULE_WINDOW_NO_FALLBACK"
            )
        ),
    }


def build_readiness_assessment_v11(
    *,
    components: Mapping[str, Mapping[str, Any]],
    code_provenance_current: bool,
    targeted_tests: Mapping[str, Any],
    guard_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_readiness_assessment_v10(
        components=components,
        code_provenance_current=code_provenance_current,
        targeted_tests=targeted_tests,
        guard_snapshot=guard_snapshot,
    )
    census = components["same-scope-strategy-census-v2.json"]
    census_safety = census.get("safety")
    if (
        census.get("selected_candidate") is not None
        or not isinstance(census_safety, Mapping)
        or census_safety.get("market_rows_read") is not False
        or census_safety.get("returns_read") is not False
        or census_safety.get("pnl_read") is not False
        or census_safety.get("oos_run") is not False
        or census_safety.get("hypothesis_changed") is not False
    ):
        raise ValueError("v11 strategy census crossed a safety boundary")
    return {
        **base,
        "alternative_strategy_review": {
            "verdict": census["verdict"],
            "selected_candidate": None,
            "testable_alternative_now": False,
            "closed_family_count": int(census["closed_family_count"]),
            "reviewed_alternative_count": len(
                census.get("reviewed_alternatives") or []
            ),
        },
        "offline_gap_assessment": {
            "materially_useful_same_contract_tasks_remaining": False,
            "reason": (
                "current code, dynamic PIT counters and alternative-strategy "
                "census are reconciled; new edge evidence requires scheduled "
                "PIT dates or an explicitly approved new data contract"
            ),
            "new_hypothesis_requires_user_review": True,
            "approved_pit_shadow_schedule_continues": True,
        },
        "next_bounded_catalog_requirement": [],
        "verdict": (
            "CURRENT_READINESS_RECONCILED_NO_HONEST_ALTERNATIVE_ON_CURRENT_"
            "IMMUTABLE_DATA"
        ),
        "next_allowed_action": (
            "follow_authoritative_guard_due_action"
            if bool(guard_snapshot.get("action_due"))
            else "WAITING_SCHEDULE_WINDOW_NO_FALLBACK"
        ),
    }


def build_readiness_audit_v7(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V7
    )
    targeted_tests = _parse_test_log(test_log)
    provenance = components["paper-code-provenance-merkle-v5.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)
    assessment = build_readiness_assessment_v7(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V7,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v5",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_audit_v8(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V8
    )
    targeted_tests = _parse_test_log(test_log)
    provenance = components["paper-code-provenance-merkle-v5.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)

    plan_path = research / "paper-public-readonly-probe-plan-v3.json"
    plan, _contract = validate_probe_plan(
        plan_path,
        str(components[plan_path.name]["plan_hash_sha256"]),
    )
    evidence_path = research / "paper-public-readonly-probe-evidence-v3.json"
    evidence = components[evidence_path.name]
    result_binding = evidence.get("probe_result")
    if not isinstance(result_binding, Mapping):
        raise ValueError("v8 public probe evidence result binding is missing")
    validate_probe_evidence(
        evidence_path,
        manifest_path=str(result_binding.get("path") or ""),
        expected_plan_hash=str(plan["plan_hash_sha256"]),
    )

    assessment = build_readiness_assessment_v8(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V8,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v5",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "public_network_evidence_consumed": True,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "paper_forward_started": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_audit_v9(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V9
    )
    targeted_tests = _parse_test_log(test_log)
    provenance = components["paper-code-provenance-merkle-v6.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)

    plan_path = research / "paper-public-readonly-probe-plan-v3.json"
    plan, _contract = validate_probe_plan(
        plan_path,
        str(components[plan_path.name]["plan_hash_sha256"]),
    )
    evidence_path = research / "paper-public-readonly-probe-evidence-v3.json"
    evidence = components[evidence_path.name]
    result_binding = evidence.get("probe_result")
    if not isinstance(result_binding, Mapping):
        raise ValueError("v9 public probe evidence result binding is missing")
    manifest_path = Path(
        str(result_binding.get("path") or "")
    ).expanduser().resolve()
    validate_probe_evidence(
        evidence_path,
        manifest_path=manifest_path,
        expected_plan_hash=str(plan["plan_hash_sha256"]),
    )

    binding = components[
        "paper-public-probe-evidence-observer-binding-fixture-v1.json"
    ]
    _validate_deterministic_result_hash(
        binding,
        label="v9 public probe observer binding",
    )
    _validate_deterministic_result_hash(
        components["paper-product-readiness-audit-v8.json"],
        label="v8 readiness audit",
    )
    binding_inputs = binding.get("inputs")
    observer_input = binding.get("observer_input")
    source_provenance = binding.get("source_provenance")
    if not all(
        isinstance(value, Mapping)
        for value in (
            binding_inputs,
            observer_input,
            source_provenance,
        )
    ):
        raise ValueError("v9 binding provenance block is missing")
    expected_inputs = {
        "probe_plan": (
            plan_path,
            str(plan["plan_hash_sha256"]),
            "plan_hash_sha256",
        ),
        "probe_evidence": (
            evidence_path,
            str(evidence["deterministic_result_hash"]),
            "deterministic_result_hash",
        ),
        "probe_manifest": (
            manifest_path,
            str(result_binding["deterministic_result_hash"]),
            "deterministic_result_hash",
        ),
    }
    for name, (path, semantic_hash, semantic_field) in expected_inputs.items():
        reference = binding_inputs.get(name)
        if (
            not isinstance(reference, Mapping)
            or Path(str(reference.get("path") or "")).expanduser().resolve()
            != path
            or str(reference.get("file_sha256") or "").lower()
            != sha256_file(path)
            or str(reference.get(semantic_field) or "").lower()
            != semantic_hash.lower()
        ):
            raise ValueError(f"v9 binding input mismatch: {name}")
    for name, reference in source_provenance.items():
        if not isinstance(reference, Mapping):
            raise ValueError(f"v9 source provenance is invalid: {name}")
        source_path = Path(
            str(reference.get("path") or "")
        ).expanduser().resolve()
        if (
            not source_path.is_file()
            or str(reference.get("file_sha256") or "").lower()
            != sha256_file(source_path)
        ):
            raise ValueError(f"v9 source provenance drift: {name}")
    observer_deterministic = {
        key: value
        for key, value in observer_input.items()
        if key != "input_hash_sha256"
    }
    if str(observer_input.get("input_hash_sha256") or "").lower() != (
        sha256_json(observer_deterministic)
    ):
        raise ValueError("v9 observer input hash mismatch")

    assessment = build_readiness_assessment_v9(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V9,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v6",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
            "refresh_required_before_next_authority_increase": True,
            "refresh_not_required_for_schedule_wait": True,
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "oos_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "public_network_evidence_consumed": True,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "paper_forward_started": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_audit_v10(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    guard_snapshot_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    guard_path = Path(guard_snapshot_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V10
    )
    targeted_tests = _parse_test_log(test_log)

    provenance = components["paper-code-provenance-merkle-v7.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)
    _validate_deterministic_result_hash(
        components["paper-product-readiness-audit-v9.json"],
        label="v9 readiness audit",
    )

    guard_snapshot = _validate_current_guard_snapshot(
        _read_json(guard_path)
    )
    assessment = build_readiness_assessment_v10(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
        guard_snapshot=guard_snapshot,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V10,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v7",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
            "refresh_required_before_next_authority_increase": True,
            "refresh_not_required_for_schedule_wait": True,
        },
        "guard_snapshot": {
            "path": str(guard_path),
            "file_sha256": sha256_file(guard_path),
            "schema": guard_snapshot["schema"],
            "policy_id": guard_snapshot["policy_id"],
            "policy_hash": guard_snapshot["policy_hash"],
            "observed_at_utc": guard_snapshot["observed_at_utc"],
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "oos_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "public_network_evidence_consumed": True,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "paper_forward_started": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


def build_readiness_audit_v11(
    *,
    research_root: str | Path,
    repo_root: str | Path,
    targeted_test_log_path: str | Path,
    guard_snapshot_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    research = Path(research_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    test_log = Path(targeted_test_log_path).expanduser().resolve()
    guard_path = Path(guard_snapshot_path).expanduser().resolve()
    components, descriptors = _load_components(
        research, COMPONENT_REQUIREMENTS_V11
    )
    targeted_tests = _parse_test_log(test_log)

    provenance = components["paper-code-provenance-merkle-v8.json"]
    try:
        validate_code_manifest(provenance, repo_root=repo)
        provenance_current = True
        provenance_drift_reason = None
    except ValueError as exc:
        provenance_current = False
        provenance_drift_reason = str(exc)
    _validate_deterministic_result_hash(
        components["paper-product-readiness-audit-v10-reconciled-v1.json"],
        label="v10 reconciled readiness audit",
    )
    _validate_deterministic_result_hash(
        components["same-scope-strategy-census-v2.json"],
        label="same-scope strategy census v2",
    )

    guard_snapshot = _validate_current_guard_snapshot(
        _read_json(guard_path)
    )
    assessment = build_readiness_assessment_v11(
        components=components,
        code_provenance_current=provenance_current,
        targeted_tests=targeted_tests,
        guard_snapshot=guard_snapshot,
    )
    deterministic = {
        "schema": AUDIT_SCHEMA_V11,
        **assessment,
        "targeted_regression": targeted_tests,
        "code_provenance_validation": {
            "manifest_version": "v8",
            "current": provenance_current,
            "drift_reason": provenance_drift_reason,
            "refresh_required_before_next_authority_increase": True,
            "refresh_not_required_for_schedule_wait": True,
        },
        "guard_snapshot": {
            "path": str(guard_path),
            "file_sha256": sha256_file(guard_path),
            "schema": guard_snapshot["schema"],
            "policy_id": guard_snapshot["policy_id"],
            "policy_hash": guard_snapshot["policy_hash"],
            "observed_at_utc": guard_snapshot["observed_at_utc"],
        },
        "components": descriptors,
        "safety": {
            "returns_or_pnl_read": False,
            "oos_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "network_collection": False,
            "public_network_evidence_consumed": True,
            "process_launches_other_than_tests": 0,
            "grid_or_retune": False,
            "oms_mutations": 0,
            "paper_forward_started": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
    }
    audit = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, audit)
    return audit


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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit catalog v2 paper-product readiness"
    )
    parser.add_argument("--research-root", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--targeted-test-log", required=True)
    parser.add_argument("--guard-snapshot")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--audit-version",
        choices=(
            "v3",
            "v4",
            "v5",
            "v6",
            "v7",
            "v8",
            "v9",
            "v10",
            "v11",
        ),
        default="v3",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    builders = {
        "v3": build_readiness_audit,
        "v4": build_readiness_audit_v4,
        "v5": build_readiness_audit_v5,
        "v6": build_readiness_audit_v6,
        "v7": build_readiness_audit_v7,
        "v8": build_readiness_audit_v8,
        "v9": build_readiness_audit_v9,
    }
    if args.audit_version in {"v10", "v11"}:
        if not args.guard_snapshot:
            raise ValueError(
                f"{args.audit_version} requires --guard-snapshot"
            )
        builder = (
            build_readiness_audit_v10
            if args.audit_version == "v10"
            else build_readiness_audit_v11
        )
        audit = builder(
            research_root=args.research_root,
            repo_root=args.repo_root,
            targeted_test_log_path=args.targeted_test_log,
            guard_snapshot_path=args.guard_snapshot,
            output_path=args.output,
        )
    else:
        builder = builders[args.audit_version]
        audit = builder(
            research_root=args.research_root,
            repo_root=args.repo_root,
            targeted_test_log_path=args.targeted_test_log,
            output_path=args.output,
        )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
