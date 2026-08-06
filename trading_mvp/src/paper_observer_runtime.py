from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from basis_paper_oms import _normalize_observation
from historical_basis_v2 import sha256_file, sha256_json
from historical_basis_v2_paper_oms import (
    PAPER_PLAN_SCHEMA,
    apply_historical_basis_v2_paper_observation,
    initialize_historical_basis_v2_paper_oms,
    reconcile_historical_basis_v2_paper_state,
    validate_historical_basis_v2_paper_plan,
    verify_historical_basis_v2_paper_ledger,
)
from paper_contract_validator import (
    validate_health_contract,
    validate_runtime_contract,
)
from paper_public_reader import (
    SNAPSHOT_SCHEMA,
    FixturePublicGetTransport,
    FixturePublicMarketReader,
    _valid_fixture_outcomes,
)
from paper_public_readonly_probe import (
    validate_probe_evidence,
    validate_probe_plan,
)


RUNTIME_PLAN_SCHEMA = "trading_mvp_paper_observer_fixture_plan_v1"
AUDIT_ROW_SCHEMA = "trading_mvp_paper_observer_fixture_audit_v1"
ACCEPTED_ROW_SCHEMA = "trading_mvp_paper_observer_fixture_accepted_v1"
MANIFEST_SCHEMA = "trading_mvp_paper_observer_fixture_manifest_v1"
SINK_MANIFEST_SCHEMA = "trading_mvp_paper_observer_fixture_oms_sink_manifest_v1"
RUNTIME_CONTRACT_SCHEMA = "trading_mvp_paper_observer_runtime_contract_v1"
HEALTH_CONTRACT_SCHEMA = "trading_mvp_paper_venue_health_gate_contract_v1"
PUBLIC_BRIDGE_SAMPLE_SCHEMA = (
    "trading_mvp_public_snapshot_observer_health_sample_v1"
)
PUBLIC_BRIDGE_REPORT_SCHEMA = (
    "trading_mvp_public_snapshot_observer_bridge_report_v1"
)
PUBLIC_HEALTH_BINDING_REPORT_SCHEMA = (
    "trading_mvp_public_health_contract_binding_fixture_v1"
)
PUBLIC_PROBE_OBSERVER_INPUT_SCHEMA = (
    "trading_mvp_public_probe_observer_input_v1"
)
PUBLIC_PROBE_OBSERVER_BINDING_REPORT_SCHEMA = (
    "trading_mvp_public_probe_evidence_observer_binding_fixture_v1"
)
MAX_RUNTIME_SEC = 1_800
PERSISTENT_STALE_SAMPLE_COUNT = 3


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL line {line_number}: {path}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL line {line_number} is not an object: {path}")
            rows.append(row)
    return rows


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    _atomic_write_json(target, payload)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _fixture_writer_lock(manifest_path: Path, *, run_id: str) -> Iterator[Path]:
    lock_path = manifest_path.with_suffix(f"{manifest_path.suffix}.writer.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    payload = {
        "schema": "trading_mvp_paper_observer_fixture_writer_lock_v1",
        "run_id": str(run_id),
        "pid": os.getpid(),
        "token": token,
        "acquired_at_utc": _utc_now(),
        "manifest_path": str(manifest_path),
    }
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"fixture observer writer lock is already held: {lock_path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield lock_path
    finally:
        try:
            current = _read_json(lock_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"fixture observer writer lock ownership cannot be verified: {lock_path}"
            ) from exc
        if current.get("token") != token:
            raise RuntimeError(
                f"fixture observer writer lock ownership changed unexpectedly: {lock_path}"
            )
        lock_path.unlink()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "plan_hash"}
        }
    )


def _runtime_manifest_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"updated_at_utc", "deterministic_result_hash"}
        }
    )


def _require_safe_flags(payload: Mapping[str, Any], *, label: str) -> None:
    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        raise ValueError(f"{label} safety contract is missing")
    for key in (
        "live_orders",
        "private_api_keys",
        "leverage",
        "margin",
        "grid_search",
        "retune",
    ):
        if safety.get(key) is not False:
            raise ValueError(f"{label} safety contract was loosened: {key}")


def _validate_contract(
    path: str | Path,
    *,
    expected_schema: str,
    label: str,
) -> tuple[dict[str, Any], Path]:
    target = Path(path).expanduser().resolve()
    payload = _read_json(target)
    if payload.get("schema") != expected_schema:
        raise ValueError(f"unexpected {label} schema")
    _require_safe_flags(payload, label=label)
    return payload, target


def _validate_ready_chain(
    paper_plan_path: str | Path,
    probe_report_path: str | Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    report_target = Path(probe_report_path).expanduser().resolve()
    report = _read_json(report_target)
    if report.get("verdict") != "PAPER_FORWARD_READY":
        raise ValueError("fixture observer requires PAPER_FORWARD_READY")
    report_safety = report.get("safety")
    if not isinstance(report_safety, Mapping):
        raise ValueError("execution probe report safety contract is missing")
    for key in ("live_orders", "private_api_keys", "leverage_or_margin", "grid_search", "retune"):
        if report_safety.get(key) is not False:
            raise ValueError(f"unsafe execution probe report flag: {key}")

    plan_target = Path(paper_plan_path).expanduser().resolve()
    plan = validate_historical_basis_v2_paper_plan(plan_target)
    if plan.get("schema") != PAPER_PLAN_SCHEMA:
        raise ValueError("unexpected paper plan schema")
    reference = plan.get("execution_probe_report")
    if not isinstance(reference, Mapping):
        raise ValueError("paper plan execution probe report reference is missing")
    if Path(str(reference.get("path") or "")).expanduser().resolve() != report_target:
        raise ValueError("paper plan belongs to another execution probe report")
    if reference.get("file_sha256") != sha256_file(report_target):
        raise ValueError("execution probe report file hash mismatch")
    if reference.get("deterministic_result_hash") != report.get("deterministic_result_hash"):
        raise ValueError("execution probe report semantic hash mismatch")
    return plan, plan_target, report, report_target


def build_fixture_observer_plan(
    *,
    paper_plan_path: str | Path,
    probe_report_path: str | Path,
    runtime_contract_path: str | Path,
    health_contract_path: str | Path,
    fixture_path: str | Path,
    output_path: str | Path,
    audit_path: str | Path,
    accepted_path: str | Path,
    manifest_path: str | Path,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    paper_plan, paper_target, report, report_target = _validate_ready_chain(
        paper_plan_path,
        probe_report_path,
    )
    runtime_target = Path(runtime_contract_path).expanduser().resolve()
    runtime_contract = validate_runtime_contract(runtime_target)
    health_target = Path(health_contract_path).expanduser().resolve()
    health_contract = validate_health_contract(
        health_target,
        runtime_contract=runtime_contract,
    )
    if runtime_contract.get("status") != "FROZEN_DESIGN_READY_FOR_FIXTURE_IMPLEMENTATION":
        raise ValueError("runtime contract is not frozen for fixture implementation")
    if health_contract.get("status") != "FROZEN_DESIGN_READY_FOR_FIXTURE_IMPLEMENTATION":
        raise ValueError("venue health contract is not frozen for fixture implementation")

    fixture_target = Path(fixture_path).expanduser().resolve()
    if not fixture_target.is_file():
        raise ValueError(f"fixture input is missing: {fixture_target}")
    output_targets = {
        "audit_path": Path(audit_path).expanduser().resolve(),
        "accepted_path": Path(accepted_path).expanduser().resolve(),
        "manifest_path": Path(manifest_path).expanduser().resolve(),
    }
    if len(set(output_targets.values())) != len(output_targets):
        raise ValueError("fixture observer output paths must be distinct")
    if fixture_target in output_targets.values():
        raise ValueError("fixture input and output paths must be distinct")

    candidates = {
        str(row.get("base") or "").strip().upper()
        for row in (paper_plan.get("universe") or {}).get("candidates") or []
        if isinstance(row, Mapping)
    }
    if not candidates or "" in candidates:
        raise ValueError("paper plan has no valid frozen candidate bases")

    source_paths = {
        "runtime_module": Path(__file__).resolve(),
        "paper_oms_module": Path(sys.modules["historical_basis_v2_paper_oms"].__file__).resolve(),
        "paper_core_module": Path(sys.modules["basis_paper_oms"].__file__).resolve(),
        "contract_validator_module": Path(
            sys.modules["paper_contract_validator"].__file__
        ).resolve(),
    }
    contract: dict[str, Any] = {
        "schema": RUNTIME_PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": "deterministic_fixture_only",
        "stage": "paper_observer_fixture_verification",
        "paper_plan": {
            "path": str(paper_target),
            "file_sha256": sha256_file(paper_target),
            "paper_plan_hash": paper_plan["paper_plan_hash"],
        },
        "execution_probe_report": {
            "path": str(report_target),
            "file_sha256": sha256_file(report_target),
            "deterministic_result_hash": report["deterministic_result_hash"],
            "verdict": report["verdict"],
        },
        "runtime_contract": {
            "path": str(runtime_target),
            "file_sha256": sha256_file(runtime_target),
            "contract_hash_sha256": runtime_contract["contract_hash_sha256"],
        },
        "venue_health_contract": {
            "path": str(health_target),
            "file_sha256": sha256_file(health_target),
            "contract_hash_sha256": health_contract["contract_hash_sha256"],
        },
        "fixture": {
            "path": str(fixture_target),
            "file_sha256": sha256_file(fixture_target),
        },
        "frozen_bases": sorted(candidates),
        "runtime": {
            "max_runtime_sec": runtime,
            "network_access": False,
            "source_provider": "deterministic_jsonl_fixture",
            "resume_same_run_id_only": True,
            "append_safe": True,
        },
        "outputs": {key: str(value) for key, value in output_targets.items()},
        "code_provenance": {
            name: {"path": str(path), "file_sha256": sha256_file(path)}
            for name, path in source_paths.items()
        },
        "safety": {
            "paper_only": True,
            "public_data_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
            "grid_search": False,
            "retune": False,
        },
        "maximum_authority": "FIXTURE_RUNTIME_VERIFIED",
        "next_allowed_action": "implement_visible_public_observer_only_after_PAPER_FORWARD_READY",
    }
    contract["input_merkle_sha256"] = sha256_json(
        {
            "paper_plan_hash": paper_plan["paper_plan_hash"],
            "probe_report_hash": report["deterministic_result_hash"],
            "runtime_contract_hash": runtime_contract["contract_hash_sha256"],
            "health_contract_hash": health_contract["contract_hash_sha256"],
            "fixture_sha256": contract["fixture"]["file_sha256"],
            "code_hashes": {
                key: value["file_sha256"] for key, value in contract["code_provenance"].items()
            },
        }
    )
    plan = {
        **contract,
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    plan["plan_hash"] = _plan_hash(plan)
    _write_json_immutable(output_path, plan)
    return plan


def validate_fixture_observer_plan(
    path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    plan = _read_json(target)
    if plan.get("schema") != RUNTIME_PLAN_SCHEMA:
        raise ValueError(f"expected {RUNTIME_PLAN_SCHEMA}")
    if plan.get("mode") != "deterministic_fixture_only":
        raise ValueError("fixture observer plan mode mismatch")
    if plan.get("plan_hash") != _plan_hash(plan):
        raise ValueError("fixture observer plan hash mismatch")
    if expected_plan_hash and plan.get("plan_hash") != str(expected_plan_hash):
        raise ValueError("fixture observer plan does not match expected hash")
    runtime = plan.get("runtime")
    if (
        not isinstance(runtime, Mapping)
        or runtime.get("network_access") is not False
        or runtime.get("source_provider") != "deterministic_jsonl_fixture"
    ):
        raise ValueError("fixture observer network boundary was loosened")
    maximum_runtime = int(runtime.get("max_runtime_sec") or 0)
    if maximum_runtime < 1 or maximum_runtime > MAX_RUNTIME_SEC:
        raise ValueError("fixture observer max runtime is invalid")
    _require_safe_flags(plan, label="fixture observer plan")

    paper_reference = plan.get("paper_plan") or {}
    report_reference = plan.get("execution_probe_report") or {}
    paper_target = Path(str(paper_reference.get("path") or "")).expanduser().resolve()
    report_target = Path(str(report_reference.get("path") or "")).expanduser().resolve()
    paper_plan, _paper_target, report, _report_target = _validate_ready_chain(
        paper_target,
        report_target,
    )
    if paper_reference.get("file_sha256") != sha256_file(paper_target):
        raise ValueError("fixture observer paper plan file hash mismatch")
    if paper_reference.get("paper_plan_hash") != paper_plan.get("paper_plan_hash"):
        raise ValueError("fixture observer paper plan hash mismatch")
    if report_reference.get("file_sha256") != sha256_file(report_target):
        raise ValueError("fixture observer report file hash mismatch")
    if report_reference.get("deterministic_result_hash") != report.get(
        "deterministic_result_hash"
    ):
        raise ValueError("fixture observer report semantic hash mismatch")
    if report_reference.get("verdict") != "PAPER_FORWARD_READY":
        raise ValueError("fixture observer requires PAPER_FORWARD_READY")

    runtime_reference = plan.get("runtime_contract") or {}
    runtime_target = Path(str(runtime_reference.get("path") or "")).expanduser().resolve()
    runtime_contract = validate_runtime_contract(runtime_target)
    if runtime_reference.get("file_sha256") != sha256_file(runtime_target):
        raise ValueError("fixture observer runtime contract file hash mismatch")
    if runtime_reference.get("contract_hash_sha256") != runtime_contract.get(
        "contract_hash_sha256"
    ):
        raise ValueError("fixture observer runtime contract semantic hash mismatch")
    health_reference = plan.get("venue_health_contract") or {}
    health_target = Path(str(health_reference.get("path") or "")).expanduser().resolve()
    health_contract = validate_health_contract(
        health_target,
        runtime_contract=runtime_contract,
    )
    if health_reference.get("file_sha256") != sha256_file(health_target):
        raise ValueError("fixture observer venue health contract file hash mismatch")
    if health_reference.get("contract_hash_sha256") != health_contract.get(
        "contract_hash_sha256"
    ):
        raise ValueError("fixture observer venue health contract semantic hash mismatch")
    fixture_reference = plan.get("fixture") or {}
    fixture_target = Path(str(fixture_reference.get("path") or "")).expanduser().resolve()
    if not fixture_target.is_file() or fixture_reference.get("file_sha256") != sha256_file(
        fixture_target
    ):
        raise ValueError("fixture observer input hash mismatch")
    code_hashes: dict[str, str] = {}
    code_provenance = plan.get("code_provenance")
    if not isinstance(code_provenance, Mapping) or not code_provenance:
        raise ValueError("fixture observer code provenance is missing")
    for name, raw in code_provenance.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"fixture observer code provenance is invalid: {name}")
        source_target = Path(str(raw.get("path") or "")).expanduser().resolve()
        observed_hash = sha256_file(source_target)
        if raw.get("file_sha256") != observed_hash:
            raise ValueError(f"fixture observer runtime code drift: {name}")
        code_hashes[str(name)] = observed_hash
    expected_merkle = sha256_json(
        {
            "paper_plan_hash": paper_plan["paper_plan_hash"],
            "probe_report_hash": report["deterministic_result_hash"],
            "runtime_contract_hash": (plan.get("runtime_contract") or {}).get(
                "contract_hash_sha256"
            ),
            "health_contract_hash": (plan.get("venue_health_contract") or {}).get(
                "contract_hash_sha256"
            ),
            "fixture_sha256": fixture_reference["file_sha256"],
            "code_hashes": code_hashes,
        }
    )
    if plan.get("input_merkle_sha256") != expected_merkle:
        raise ValueError("fixture observer input merkle mismatch")
    return plan


def _finite_number(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _snapshot_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"snapshot_hash_sha256", "decision", "reasons"}
        }
    )


def evaluate_fixture_health(
    sample: Mapping[str, Any],
    health_contract: Mapping[str, Any],
) -> dict[str, Any]:
    received_ms = _finite_number(
        sample.get("observer_received_ts_ms"),
        field="observer_received_ts_ms",
    )
    thresholds = health_contract.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise ValueError("venue health thresholds are missing")
    reasons: list[str] = []
    venue_metrics: dict[str, dict[str, float]] = {}
    observed: dict[str, float] = {}

    for venue in ("mexc", "gateio"):
        raw = sample.get(venue)
        if not isinstance(raw, Mapping):
            raise ValueError(f"fixture sample missing {venue} venue snapshot")
        if raw.get("transport_ok") is not True:
            reasons.append("transport_failure")
        if int(raw.get("http_status") or 0) != 200:
            reasons.append("http_failure")
        if raw.get("schema_ok") is not True:
            reasons.append("schema_mismatch")
        if raw.get("contract_trading") is not True:
            reasons.append("contract_not_trading")
        if raw.get("maintenance_flag") is True:
            reasons.append("venue_maintenance")
        bid = _finite_number(raw.get("best_bid"), field=f"{venue}.best_bid")
        ask = _finite_number(raw.get("best_ask"), field=f"{venue}.best_ask")
        if bid <= 0.0 or ask <= 0.0:
            reasons.append("invalid_bbo")
        elif bid >= ask:
            reasons.append("crossed_book")
        observed_ms = _finite_number(raw.get("observed_ts_ms"), field=f"{venue}.observed_ts_ms")
        observed[venue] = observed_ms
        quote_age = received_ms - observed_ms
        if quote_age < 0.0 or quote_age > float(thresholds["maximum_quote_age_ms"]):
            reasons.append("stale_quote")
        spread_bps = (ask - bid) / ((ask + bid) / 2.0) * 10_000.0 if ask > bid > 0 else math.inf
        if spread_bps > float(thresholds["maximum_spread_bps_for_transition"]):
            reasons.append("spread_too_wide")
        if int(raw.get("bid_depth_levels") or 0) < int(thresholds["minimum_bid_depth_levels"]):
            reasons.append("missing_depth_levels")
        if int(raw.get("ask_depth_levels") or 0) < int(thresholds["minimum_ask_depth_levels"]):
            reasons.append("missing_depth_levels")
        capacities = [
            _finite_number(
                raw.get(f"{side}_capacity_quote_at_10bps"),
                field=f"{venue}.{side}_capacity_quote_at_10bps",
            )
            for side in ("buy", "sell")
        ]
        impacts = [
            _finite_number(
                raw.get(f"{side}_impact_bps_at_notional"),
                field=f"{venue}.{side}_impact_bps_at_notional",
            )
            for side in ("buy", "sell")
        ]
        if min(capacities) < float(thresholds["minimum_capacity_quote_per_leg"]):
            reasons.append("insufficient_capacity")
        if max(impacts) > float(thresholds["maximum_impact_bps_at_notional"]):
            reasons.append("excessive_impact")
        raw_hash = str(raw.get("raw_payload_hash_sha256") or "").lower()
        if len(raw_hash) != 64 or any(character not in "0123456789abcdef" for character in raw_hash):
            reasons.append("payload_hash_mismatch")
        bids = raw.get("bids")
        asks = raw.get("asks")
        if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
            reasons.append("missing_depth_levels")
        venue_metrics[venue] = {
            "quote_age_ms": quote_age,
            "spread_bps": spread_bps,
            "minimum_capacity_quote": min(capacities),
            "maximum_impact_bps": max(impacts),
        }

    skew_ms = abs(observed["mexc"] - observed["gateio"])
    if skew_ms > float(thresholds["maximum_cross_venue_timestamp_skew_ms"]):
        reasons.append("timestamp_skew")
    error_rate = _finite_number(
        sample.get("recent_application_error_rate", 0.0),
        field="recent_application_error_rate",
    )
    if error_rate > float(thresholds["maximum_recent_application_error_rate"]):
        reasons.append("error_rate_exceeded")
    missing_intervals = int(sample.get("consecutive_missing_intervals") or 0)
    if missing_intervals > int(thresholds["maximum_consecutive_missing_intervals"]):
        reasons.append("missing_intervals_exceeded")

    priority = [str(value) for value in health_contract.get("reason_priority") or []]
    unique_reasons = sorted(
        set(reasons),
        key=lambda value: (priority.index(value) if value in priority else len(priority), value),
    )
    fatal = any(
        reason in {"schema_mismatch", "payload_hash_mismatch"}
        for reason in unique_reasons
    )
    decision = (
        "STOPPED_INCOMPLETE"
        if fatal
        else "BLOCK_TRANSITION"
        if unique_reasons
        else "HEALTHY_TRANSITION_ALLOWED"
    )
    result = {
        "decision": decision,
        "reasons": unique_reasons,
        "cross_venue_timestamp_skew_ms": skew_ms,
        "recent_application_error_rate": error_rate,
        "consecutive_missing_intervals": missing_intervals,
        "venue_metrics": venue_metrics,
    }
    result["snapshot_hash_sha256"] = _snapshot_hash({**dict(sample), **result})
    return result


def _validate_fixture_rows(
    rows: list[dict[str, Any]],
    *,
    frozen_bases: set[str],
) -> None:
    previous_sequence = 0
    previous_ts = -1.0
    for row in rows:
        sequence = int(row.get("sample_sequence") or 0)
        if sequence != previous_sequence + 1:
            raise ValueError("fixture sample_sequence must be contiguous from 1")
        timestamp = _finite_number(
            row.get("observer_received_ts_ms"),
            field="observer_received_ts_ms",
        )
        if timestamp <= previous_ts:
            raise ValueError("fixture observations must be strictly chronological")
        base = str(row.get("canonical_base") or "").strip().upper()
        if base not in frozen_bases:
            raise ValueError(f"fixture base is outside frozen universe: {base}")
        if not isinstance(row.get("observation"), Mapping):
            raise ValueError("fixture sample observation is missing")
        previous_sequence = sequence
        previous_ts = timestamp


def _initial_incident_state() -> dict[str, Any]:
    return {
        "current_state": "HEALTHY",
        "consecutive_degraded_samples": 0,
        "consecutive_stale_samples": 0,
        "incident_count": 0,
        "recovery_count": 0,
        "last_reasons": [],
    }


def _incident_state_from_audit(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _initial_incident_state()
    incident = rows[-1].get("incident")
    if not isinstance(incident, Mapping) or not isinstance(
        incident.get("state_after"),
        Mapping,
    ):
        raise ValueError("existing fixture observer audit incident state is missing")
    state = dict(incident["state_after"])
    required = {
        "current_state",
        "consecutive_degraded_samples",
        "consecutive_stale_samples",
        "incident_count",
        "recovery_count",
        "last_reasons",
    }
    if not required.issubset(state):
        raise ValueError("existing fixture observer incident state is incomplete")
    return state


def update_incident_state(
    previous: Mapping[str, Any],
    health: Mapping[str, Any],
) -> dict[str, Any]:
    state = dict(previous)
    prior_state = str(state.get("current_state") or "HEALTHY")
    decision = str(health.get("decision") or "")
    reasons = sorted({str(value) for value in health.get("reasons") or []})
    event = "HEALTHY_SAMPLE"

    if decision == "HEALTHY_TRANSITION_ALLOWED":
        if prior_state != "HEALTHY":
            state["recovery_count"] = int(state.get("recovery_count") or 0) + 1
            event = "RECOVERED"
        state["current_state"] = "HEALTHY"
        state["consecutive_degraded_samples"] = 0
        state["consecutive_stale_samples"] = 0
    elif decision == "BLOCK_TRANSITION":
        if prior_state == "HEALTHY":
            state["incident_count"] = int(state.get("incident_count") or 0) + 1
            event = "TRANSIENT_DEGRADATION_STARTED"
        else:
            event = "TRANSIENT_DEGRADATION_CONTINUED"
        state["consecutive_degraded_samples"] = int(
            state.get("consecutive_degraded_samples") or 0
        ) + 1
        if "stale_quote" in reasons:
            state["consecutive_stale_samples"] = int(
                state.get("consecutive_stale_samples") or 0
            ) + 1
        else:
            state["consecutive_stale_samples"] = 0
        if int(state["consecutive_stale_samples"]) >= PERSISTENT_STALE_SAMPLE_COUNT:
            state["current_state"] = "PERSISTENT_STALE_DATA"
            event = "PERSISTENT_STALE_DATA"
        else:
            state["current_state"] = "DEGRADED_TRANSIENT"
    elif decision == "STOPPED_INCOMPLETE":
        if prior_state == "HEALTHY":
            state["incident_count"] = int(state.get("incident_count") or 0) + 1
        state["consecutive_degraded_samples"] = int(
            state.get("consecutive_degraded_samples") or 0
        ) + 1
        if any(reason in {"schema_mismatch", "payload_hash_mismatch"} for reason in reasons):
            state["current_state"] = "FATAL_SCHEMA_FAILURE"
            event = "FATAL_SCHEMA_FAILURE"
        else:
            state["current_state"] = "FATAL_RUNTIME_FAILURE"
            event = "FATAL_RUNTIME_FAILURE"
    else:
        raise ValueError(f"unknown venue-health decision: {decision}")

    state["last_reasons"] = reasons
    return {
        "event": event,
        "state_before": prior_state,
        "state_after": state,
    }


def _write_manifest(
    target: Path,
    *,
    plan: Mapping[str, Any],
    status: str,
    final: bool,
    completed_samples: int,
    accepted_samples: int,
    blocked_samples: int,
    stop_reason: str,
    runtime_sec: float,
    errors: list[str],
    incident_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "run_id": plan["run_id"],
        "plan_hash": plan["plan_hash"],
        "input_merkle_sha256": plan["input_merkle_sha256"],
        "status": status,
        "final": bool(final),
        "completed_samples": int(completed_samples),
        "accepted_samples": int(accepted_samples),
        "blocked_samples": int(blocked_samples),
        "runtime_sec": float(runtime_sec),
        "stop_reason": str(stop_reason),
        "errors": list(errors),
        "incident_state": dict(incident_state or _initial_incident_state()),
        "updated_at_utc": _utc_now(),
        "safety": dict(plan["safety"]),
        "next_allowed_action": (
            "fixture_runtime_verified"
            if final and status == "COMPLETED"
            else "resume_same_run_id"
            if status == "STOPPED_INCOMPLETE"
            else "fail_closed_review"
        ),
    }
    payload["deterministic_result_hash"] = _runtime_manifest_hash(payload)
    _atomic_write_json(target, payload)
    return payload


def run_fixture_observer_segment(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    max_new_samples: int | None = None,
    monotonic_fn: Callable[[], float] = time.monotonic,
    progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    plan = validate_fixture_observer_plan(plan_path, expected_plan_hash)
    fixture_path = Path(plan["fixture"]["path"]).resolve()
    audit_path = Path(plan["outputs"]["audit_path"]).resolve()
    accepted_path = Path(plan["outputs"]["accepted_path"]).resolve()
    manifest_path = Path(plan["outputs"]["manifest_path"]).resolve()
    with _fixture_writer_lock(manifest_path, run_id=str(plan["run_id"])):
        return _run_fixture_observer_segment_locked(
            plan=plan,
            fixture_path=fixture_path,
            audit_path=audit_path,
            accepted_path=accepted_path,
            manifest_path=manifest_path,
            max_new_samples=max_new_samples,
            monotonic_fn=monotonic_fn,
            progress=progress,
        )


def _run_fixture_observer_segment_locked(
    *,
    plan: Mapping[str, Any],
    fixture_path: Path,
    audit_path: Path,
    accepted_path: Path,
    manifest_path: Path,
    max_new_samples: int | None,
    monotonic_fn: Callable[[], float],
    progress: Callable[[Mapping[str, Any]], None] | None,
) -> dict[str, Any]:
    if manifest_path.exists():
        prior_manifest = _read_json(manifest_path)
        if prior_manifest.get("plan_hash") != plan["plan_hash"]:
            raise ValueError("existing fixture observer manifest belongs to another plan")
        if prior_manifest.get("final") is True:
            raise ValueError("fixture observer segment is already final")
        if prior_manifest.get("stop_reason") == "validation_or_integrity_failure":
            raise ValueError("fixture observer integrity failure requires fail-closed review")

    fixture_rows = _read_jsonl(fixture_path)
    _validate_fixture_rows(fixture_rows, frozen_bases=set(plan["frozen_bases"]))
    existing_audit = _read_jsonl(audit_path)
    existing_by_sequence: dict[int, str] = {}
    for row in existing_audit:
        if row.get("schema") != AUDIT_ROW_SCHEMA or row.get("plan_hash") != plan["plan_hash"]:
            raise ValueError("existing fixture observer audit provenance mismatch")
        sequence = int(row.get("sample_sequence") or 0)
        input_hash = str(row.get("input_hash_sha256") or "")
        if sequence in existing_by_sequence:
            raise ValueError("existing fixture observer audit contains duplicate sequences")
        existing_by_sequence[sequence] = input_hash

    accepted_existing = _read_jsonl(accepted_path)
    accepted_sequences: set[int] = set()
    for row in accepted_existing:
        if row.get("schema") != ACCEPTED_ROW_SCHEMA or row.get("plan_hash") != plan["plan_hash"]:
            raise ValueError("existing accepted observation provenance mismatch")
        sequence = int(row.get("sample_sequence") or 0)
        if sequence in accepted_sequences:
            raise ValueError("existing accepted observations contain duplicate sequences")
        if sequence not in existing_by_sequence:
            raise ValueError("accepted observation has no matching audit row")
        accepted_sequences.add(sequence)
    incident_state = _incident_state_from_audit(existing_audit)
    health_contract = _read_json(plan["venue_health_contract"]["path"])
    started = monotonic_fn()
    newly_processed = 0
    errors: list[str] = []
    _write_manifest(
        manifest_path,
        plan=plan,
        status="RUNNING",
        final=False,
        completed_samples=len(existing_by_sequence),
        accepted_samples=len(accepted_sequences),
        blocked_samples=len(existing_by_sequence) - len(accepted_sequences),
        stop_reason="running",
        runtime_sec=0.0,
        errors=[],
        incident_state=incident_state,
    )

    try:
        for sample in fixture_rows:
            sequence = int(sample["sample_sequence"])
            input_hash = sha256_json(sample)
            if sequence in existing_by_sequence:
                if existing_by_sequence[sequence] != input_hash:
                    raise ValueError("resume fixture sample hash mismatch")
                continue
            if max_new_samples is not None and newly_processed >= int(max_new_samples):
                break
            elapsed = monotonic_fn() - started
            if elapsed >= float(plan["runtime"]["max_runtime_sec"]):
                break
            health = evaluate_fixture_health(sample, health_contract)
            incident = update_incident_state(incident_state, health)
            incident_state = dict(incident["state_after"])
            audit_row = {
                "schema": AUDIT_ROW_SCHEMA,
                "run_id": plan["run_id"],
                "plan_hash": plan["plan_hash"],
                "sample_sequence": sequence,
                "canonical_base": str(sample["canonical_base"]).strip().upper(),
                "observer_received_ts_ms": float(sample["observer_received_ts_ms"]),
                "input_hash_sha256": input_hash,
                "health": health,
                "incident": incident,
            }
            _append_jsonl(audit_path, audit_row)
            existing_by_sequence[sequence] = input_hash
            newly_processed += 1
            if health["decision"] == "STOPPED_INCOMPLETE":
                raise ValueError(
                    "fixture venue-health fatal failure: " + ",".join(health["reasons"])
                )
            if health["decision"] == "HEALTHY_TRANSITION_ALLOWED":
                observation = _normalize_observation(dict(sample["observation"]))
                base = str(sample["canonical_base"]).strip().upper()
                if observation["base"] != base:
                    raise ValueError("fixture health base and paper observation base mismatch")
                observation["data_quality_ok"] = True
                observation["venue_health_hash"] = health["snapshot_hash_sha256"]
                observation["execution_books"] = {
                    venue: {
                        "observed_ts_ms": float(sample[venue]["observed_ts_ms"]),
                        "bids": sample[venue]["bids"],
                        "asks": sample[venue]["asks"],
                    }
                    for venue in ("mexc", "gateio")
                }
                accepted_row = {
                    "schema": ACCEPTED_ROW_SCHEMA,
                    "run_id": plan["run_id"],
                    "plan_hash": plan["plan_hash"],
                    "sample_sequence": sequence,
                    "health_hash_sha256": health["snapshot_hash_sha256"],
                    "observation": observation,
                }
                _append_jsonl(accepted_path, accepted_row)
                accepted_sequences.add(sequence)
            if progress is not None:
                progress(
                    {
                        "run_id": plan["run_id"],
                        "completed_samples": len(existing_by_sequence),
                        "total_samples": len(fixture_rows),
                        "accepted_samples": len(accepted_sequences),
                        "last_decision": health["decision"],
                    }
                )
    except Exception as exc:
        errors.append(str(exc))
        _write_manifest(
            manifest_path,
            plan=plan,
            status="STOPPED_INCOMPLETE",
            final=False,
            completed_samples=len(existing_by_sequence),
            accepted_samples=len(accepted_sequences),
            blocked_samples=len(existing_by_sequence) - len(accepted_sequences),
            stop_reason="validation_or_integrity_failure",
            runtime_sec=monotonic_fn() - started,
            errors=errors,
            incident_state=incident_state,
        )
        raise

    complete = len(existing_by_sequence) == len(fixture_rows)
    return _write_manifest(
        manifest_path,
        plan=plan,
        status="COMPLETED" if complete else "STOPPED_INCOMPLETE",
        final=complete,
        completed_samples=len(existing_by_sequence),
        accepted_samples=len(accepted_sequences),
        blocked_samples=len(existing_by_sequence) - len(accepted_sequences),
        stop_reason="completed" if complete else "bounded_interruption",
        runtime_sec=monotonic_fn() - started,
        errors=errors,
        incident_state=incident_state,
    )


def _sink_observation_id(plan_hash: str, row: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            "observer_plan_hash": plan_hash,
            "sample_sequence": int(row["sample_sequence"]),
            "health_hash_sha256": row["health_hash_sha256"],
            "observation": row["observation"],
        }
    )


def _sink_manifest_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"updated_at_utc", "runtime_sec", "deterministic_result_hash"}
        }
    )


def _write_sink_manifest(
    target: Path,
    *,
    plan: Mapping[str, Any],
    status: str,
    final: bool,
    accepted_observations: int,
    applied_observations: int,
    skipped_existing_observations: int,
    stop_reason: str,
    runtime_sec: float,
    ledger_path: Path,
    state_path: Path,
    reconciliation: Mapping[str, Any] | None,
    errors: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SINK_MANIFEST_SCHEMA,
        "run_id": f"{plan['run_id']}:paper-oms-fixture-sink",
        "observer_plan_hash": plan["plan_hash"],
        "paper_plan_hash": plan["paper_plan"]["paper_plan_hash"],
        "status": status,
        "final": bool(final),
        "accepted_observations": int(accepted_observations),
        "applied_observations": int(applied_observations),
        "skipped_existing_observations": int(skipped_existing_observations),
        "stop_reason": str(stop_reason),
        "runtime_sec": float(runtime_sec),
        "ledger_path": str(ledger_path),
        "state_path": str(state_path),
        "reconciliation": dict(reconciliation or {}),
        "errors": list(errors),
        "updated_at_utc": _utc_now(),
        "safety": {
            "fixture_only": True,
            "paper_only": True,
            "network_access": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
            "grid_search": False,
            "retune": False,
        },
        "maximum_authority": "FIXTURE_PAPER_OMS_VERIFIED",
        "next_allowed_action": (
            "paper_observer_incident_state_v1"
            if final and status == "COMPLETED"
            else "resume_same_run_id"
            if stop_reason == "bounded_interruption"
            else "fail_closed_review"
        ),
    }
    payload["deterministic_result_hash"] = _sink_manifest_hash(payload)
    _atomic_write_json(target, payload)
    return payload


def _processed_sink_ids(ledger_path: Path) -> set[str]:
    processed: set[str] = set()
    for event in _read_jsonl(ledger_path):
        if event.get("event_type") != "OBSERVATION_RECORDED":
            continue
        observation = (event.get("details") or {}).get("observation")
        if not isinstance(observation, Mapping):
            continue
        sink_id = str(observation.get("fixture_observer_sink_id") or "").strip()
        if not sink_id:
            continue
        if sink_id in processed:
            raise ValueError("paper OMS ledger contains duplicate fixture sink IDs")
        processed.add(sink_id)
    return processed


def run_fixture_observer_oms_sink(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    ledger_path: str | Path,
    state_path: str | Path,
    sink_manifest_path: str | Path,
    max_new_observations: int | None = None,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    plan = validate_fixture_observer_plan(plan_path, expected_plan_hash)
    accepted_path = Path(plan["outputs"]["accepted_path"]).resolve()
    observer_manifest_path = Path(plan["outputs"]["manifest_path"]).resolve()
    observer_manifest = _read_json(observer_manifest_path)
    if (
        observer_manifest.get("schema") != MANIFEST_SCHEMA
        or observer_manifest.get("plan_hash") != plan["plan_hash"]
        or observer_manifest.get("status") != "COMPLETED"
        or observer_manifest.get("final") is not True
    ):
        raise ValueError("fixture observer must be final and completed before OMS sink")

    accepted_rows = _read_jsonl(accepted_path)
    if int(observer_manifest.get("accepted_samples") or 0) != len(accepted_rows):
        raise ValueError("fixture observer accepted row count mismatch")
    previous_sequence = 0
    sink_rows: list[tuple[str, dict[str, Any]]] = []
    for row in accepted_rows:
        if row.get("schema") != ACCEPTED_ROW_SCHEMA or row.get("plan_hash") != plan["plan_hash"]:
            raise ValueError("accepted observation provenance mismatch")
        sequence = int(row.get("sample_sequence") or 0)
        if sequence <= previous_sequence:
            raise ValueError("accepted observations must be strictly ordered")
        if not isinstance(row.get("observation"), Mapping):
            raise ValueError("accepted observation payload is missing")
        sink_rows.append((_sink_observation_id(str(plan["plan_hash"]), row), row))
        previous_sequence = sequence
    if len({sink_id for sink_id, _row in sink_rows}) != len(sink_rows):
        raise ValueError("accepted observations contain duplicate sink IDs")

    ledger_target = Path(ledger_path).expanduser().resolve()
    state_target = Path(state_path).expanduser().resolve()
    manifest_target = Path(sink_manifest_path).expanduser().resolve()
    lock_run_id = f"{plan['run_id']}:paper-oms-fixture-sink"
    with _fixture_writer_lock(manifest_target, run_id=lock_run_id):
        return _run_fixture_observer_oms_sink_locked(
            plan=plan,
            sink_rows=sink_rows,
            ledger_path=ledger_target,
            state_path=state_target,
            manifest_path=manifest_target,
            max_new_observations=max_new_observations,
            monotonic_fn=monotonic_fn,
        )


def _run_fixture_observer_oms_sink_locked(
    *,
    plan: Mapping[str, Any],
    sink_rows: list[tuple[str, dict[str, Any]]],
    ledger_path: Path,
    state_path: Path,
    manifest_path: Path,
    max_new_observations: int | None,
    monotonic_fn: Callable[[], float],
) -> dict[str, Any]:
    if manifest_path.exists():
        prior = _read_json(manifest_path)
        if prior.get("schema") != SINK_MANIFEST_SCHEMA:
            raise ValueError("existing OMS sink manifest schema mismatch")
        if prior.get("observer_plan_hash") != plan["plan_hash"]:
            raise ValueError("existing OMS sink manifest belongs to another observer plan")
        if prior.get("deterministic_result_hash") != _sink_manifest_hash(prior):
            raise ValueError("existing OMS sink manifest hash mismatch")
        if prior.get("final") is True:
            reconciliation = reconcile_historical_basis_v2_paper_state(
                state_path,
                ledger_path,
            )
            if not reconciliation["matched"]:
                raise ValueError("final OMS sink state no longer reconciles")
            return prior
        if prior.get("stop_reason") == "validation_or_integrity_failure":
            raise ValueError("OMS sink integrity failure requires fail-closed review")

    paper_plan_path = Path(plan["paper_plan"]["path"]).resolve()
    report_path = Path(plan["execution_probe_report"]["path"]).resolve()
    if ledger_path.exists() != state_path.exists():
        raise ValueError("paper OMS ledger and state must either both exist or both be absent")
    if not ledger_path.exists():
        initialize_historical_basis_v2_paper_oms(
            paper_plan_path,
            report_path,
            ledger_path=ledger_path,
            state_path=state_path,
        )
    verify_historical_basis_v2_paper_ledger(ledger_path)
    reconciliation = reconcile_historical_basis_v2_paper_state(state_path, ledger_path)
    if not reconciliation["matched"]:
        raise ValueError("paper OMS state does not reconcile before fixture sink")

    started = monotonic_fn()
    processed = _processed_sink_ids(ledger_path)
    all_sink_ids = {sink_id for sink_id, _row in sink_rows}
    unexpected = processed - all_sink_ids
    if unexpected:
        raise ValueError("paper OMS ledger contains fixture sink IDs from another observer plan")
    initially_processed = len(processed)
    newly_applied = 0
    errors: list[str] = []
    _write_sink_manifest(
        manifest_path,
        plan=plan,
        status="RUNNING",
        final=False,
        accepted_observations=len(sink_rows),
        applied_observations=len(processed),
        skipped_existing_observations=initially_processed,
        stop_reason="running",
        runtime_sec=0.0,
        ledger_path=ledger_path,
        state_path=state_path,
        reconciliation=reconciliation,
        errors=[],
    )

    try:
        for sink_id, accepted_row in sink_rows:
            if sink_id in processed:
                continue
            if (
                max_new_observations is not None
                and newly_applied >= int(max_new_observations)
            ):
                break
            observation = dict(accepted_row["observation"])
            observation["fixture_observer_sink_id"] = sink_id
            observation["fixture_observer_plan_hash"] = plan["plan_hash"]
            observation["fixture_observer_sample_sequence"] = int(
                accepted_row["sample_sequence"]
            )
            apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger_path,
                state_path=state_path,
                observation=observation,
            )
            reconciliation = reconcile_historical_basis_v2_paper_state(
                state_path,
                ledger_path,
            )
            if not reconciliation["matched"]:
                raise ValueError("paper OMS state failed reconciliation after fixture sink")
            processed.add(sink_id)
            newly_applied += 1
    except Exception as exc:
        errors.append(str(exc))
        _write_sink_manifest(
            manifest_path,
            plan=plan,
            status="STOPPED_INCOMPLETE",
            final=False,
            accepted_observations=len(sink_rows),
            applied_observations=len(processed),
            skipped_existing_observations=initially_processed,
            stop_reason="validation_or_integrity_failure",
            runtime_sec=monotonic_fn() - started,
            ledger_path=ledger_path,
            state_path=state_path,
            reconciliation=reconciliation,
            errors=errors,
        )
        raise

    complete = processed == all_sink_ids
    return _write_sink_manifest(
        manifest_path,
        plan=plan,
        status="COMPLETED" if complete else "STOPPED_INCOMPLETE",
        final=complete,
        accepted_observations=len(sink_rows),
        applied_observations=len(processed),
        skipped_existing_observations=initially_processed,
        stop_reason="completed" if complete else "bounded_interruption",
        runtime_sec=monotonic_fn() - started,
        ledger_path=ledger_path,
        state_path=state_path,
        reconciliation=reconciliation,
        errors=errors,
    )


def _depth_execution_metrics(
    levels: Sequence[Mapping[str, Any]],
    *,
    reference_price: float,
    side: str,
    notional_quote: float,
    tolerance_bps: float,
) -> tuple[float, float]:
    if side not in {"buy", "sell"}:
        raise ValueError("depth side must be buy or sell")
    if reference_price <= 0.0 or notional_quote <= 0.0:
        raise ValueError("depth reference and notional must be positive")
    maximum_buy = reference_price * (1.0 + tolerance_bps / 10_000.0)
    minimum_sell = reference_price * (1.0 - tolerance_bps / 10_000.0)
    capacity = 0.0
    remaining = notional_quote
    filled_quote = 0.0
    filled_base = 0.0
    for level in levels:
        price = _finite_number(level.get("price"), field=f"{side}.price")
        quantity = _finite_number(
            level.get("quantity"), field=f"{side}.quantity"
        )
        if price <= 0.0 or quantity <= 0.0:
            raise ValueError("depth levels must be positive")
        within_tolerance = (
            price <= maximum_buy if side == "buy" else price >= minimum_sell
        )
        if within_tolerance:
            capacity += price * quantity
        if remaining <= 0.0:
            continue
        available_quote = price * quantity
        taken_quote = min(remaining, available_quote)
        filled_quote += taken_quote
        filled_base += taken_quote / price
        remaining -= taken_quote
    if remaining > 1e-9 or filled_base <= 0.0:
        raise ValueError(f"{side} fixture depth cannot fill frozen notional")
    average_price = filled_quote / filled_base
    impact_bps = (
        (average_price - reference_price) / reference_price * 10_000.0
        if side == "buy"
        else (reference_price - average_price)
        / reference_price
        * 10_000.0
    )
    return capacity, max(0.0, impact_bps)


def public_snapshot_to_health_venue(
    snapshot: Mapping[str, Any],
    *,
    notional_quote: float = 500.0,
    tolerance_bps: float = 10.0,
) -> dict[str, Any]:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("unexpected public snapshot schema")
    if snapshot.get("network_request_performed") is not False:
        raise ValueError("bridge accepts fixture-only public snapshots")
    bids = snapshot.get("bid_depth")
    asks = snapshot.get("ask_depth")
    if not isinstance(bids, list) or not bids:
        raise ValueError("public snapshot bid depth is missing")
    if not isinstance(asks, list) or not asks:
        raise ValueError("public snapshot ask depth is missing")
    best_bid = _finite_number(snapshot.get("best_bid"), field="best_bid")
    best_ask = _finite_number(snapshot.get("best_ask"), field="best_ask")
    buy_capacity, buy_impact = _depth_execution_metrics(
        asks,
        reference_price=best_ask,
        side="buy",
        notional_quote=notional_quote,
        tolerance_bps=tolerance_bps,
    )
    sell_capacity, sell_impact = _depth_execution_metrics(
        bids,
        reference_price=best_bid,
        side="sell",
        notional_quote=notional_quote,
        tolerance_bps=tolerance_bps,
    )
    return {
        "transport_ok": True,
        "http_status": 200,
        "schema_ok": True,
        "contract_trading": snapshot.get("contract_trading") is True,
        "maintenance_flag": False,
        "observed_ts_ms": int(snapshot["observed_ts_ms"]),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": (best_ask - best_bid)
        / ((best_ask + best_bid) / 2.0)
        * 10_000.0,
        "bid_depth_levels": len(bids),
        "ask_depth_levels": len(asks),
        "buy_capacity_quote_at_10bps": buy_capacity,
        "sell_capacity_quote_at_10bps": sell_capacity,
        "buy_impact_bps_at_notional": buy_impact,
        "sell_impact_bps_at_notional": sell_impact,
        "raw_payload_hash_sha256": str(
            snapshot["raw_payload_hash_sha256"]
        ),
        "bids": [
            [
                _finite_number(level.get("price"), field="bid.price"),
                _finite_number(
                    level.get("quantity"), field="bid.quantity"
                ),
            ]
            for level in bids
        ],
        "asks": [
            [
                _finite_number(level.get("price"), field="ask.price"),
                _finite_number(
                    level.get("quantity"), field="ask.quantity"
                ),
            ]
            for level in asks
        ],
    }


def build_public_snapshot_health_sample(
    *,
    mexc_snapshot: Mapping[str, Any],
    gateio_snapshot: Mapping[str, Any],
    sample_sequence: int = 1,
) -> dict[str, Any]:
    snapshots = {"mexc": mexc_snapshot, "gateio": gateio_snapshot}
    bases = {
        str(snapshot.get("canonical_base") or "").strip().upper()
        for snapshot in snapshots.values()
    }
    if len(bases) != 1 or not next(iter(bases), ""):
        raise ValueError("public snapshots must share one canonical base")
    received = {
        int(snapshot.get("observer_received_ts_ms") or 0)
        for snapshot in snapshots.values()
    }
    if len(received) != 1 or next(iter(received), 0) <= 0:
        raise ValueError("public snapshots must share one observer timestamp")
    if isinstance(sample_sequence, bool) or int(sample_sequence) <= 0:
        raise ValueError("sample_sequence must be positive")
    deterministic = {
        "schema": PUBLIC_BRIDGE_SAMPLE_SCHEMA,
        "sample_sequence": int(sample_sequence),
        "observer_received_ts_ms": next(iter(received)),
        "canonical_base": next(iter(bases)),
        "recent_application_error_rate": 0.0,
        "consecutive_missing_intervals": 0,
        "mexc": public_snapshot_to_health_venue(mexc_snapshot),
        "gateio": public_snapshot_to_health_venue(gateio_snapshot),
        "source_snapshot_hashes": {
            venue: str(snapshot["snapshot_hash_sha256"])
            for venue, snapshot in snapshots.items()
        },
    }
    return {
        **deterministic,
        "sample_hash_sha256": sha256_json(deterministic),
    }


def _build_public_probe_observer_input(
    *,
    plan: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    probe = plan.get("probe")
    quality = evidence.get("quality")
    safety = evidence.get("safety")
    result_binding = evidence.get("probe_result")
    if not all(
        isinstance(value, Mapping)
        for value in (probe, quality, safety, result_binding)
    ):
        raise ValueError("public probe observer binding input block is missing")
    quote_ages = {"mexc": 6000, "gateio": 5000}
    if (
        plan.get("schema")
        != "trading_mvp_paper_public_readonly_probe_plan_v3"
        or evidence.get("schema")
        != "trading_mvp_paper_public_readonly_probe_evidence_v3"
        or evidence.get("verdict")
        != "PUBLIC_READONLY_PROBE_EVIDENCE_ACCEPTED"
        or result_binding.get("plan_hash_sha256")
        != plan.get("plan_hash_sha256")
        or probe.get("maximum_quote_age_ms_by_venue") != quote_ages
        or quality.get("maximum_quote_age_ms_by_venue") != quote_ages
        or quality.get("partial_output") is not False
        or int(quality.get("error_count") or 0) != 0
        or int(quality.get("snapshot_count") or 0)
        != int(quality.get("expected_snapshot_count") or -1)
        or int(quality.get("network_requests") or 0)
        != int(quality.get("planned_endpoint_reads") or -1)
        or safety.get("public_get_only") is not True
        or safety.get("returns_or_pnl_read") is not False
        or safety.get("signals_read") is not False
        or int(safety.get("oms_mutations") or 0) != 0
        or safety.get("private_api_keys") is not False
        or safety.get("live_orders") is not False
        or safety.get("leverage_or_margin") is not False
        or safety.get("grid_or_retune") is not False
        or safety.get("hypothesis_changed") is not False
    ):
        raise ValueError("public probe observer binding evidence is not accepted")

    deterministic = {
        "schema": PUBLIC_PROBE_OBSERVER_INPUT_SCHEMA,
        "mode": "IMMUTABLE_PUBLIC_PROBE_EVIDENCE_DESCRIPTOR_ONLY",
        "run_id": str(result_binding["run_id"]),
        "plan_hash_sha256": str(result_binding["plan_hash_sha256"]),
        "venues": list(quality["venues"]),
        "snapshot_count": int(quality["snapshot_count"]),
        "network_requests_in_source_probe": int(quality["network_requests"]),
        "maximum_quote_age_ms_by_venue": quote_ages,
        "health_decision": "NOT_EVALUATED_DESCRIPTOR_ONLY",
        "oms_transition_allowed": False,
        "paper_forward_allowed": False,
        "live_allowed": False,
    }
    return {
        **deterministic,
        "input_hash_sha256": sha256_json(deterministic),
    }


def build_public_probe_evidence_observer_binding_fixture_report(
    *,
    plan_path: str | Path,
    evidence_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan_target = Path(plan_path).expanduser().resolve()
    evidence_target = Path(evidence_path).expanduser().resolve()
    plan, _contract = validate_probe_plan(
        plan_target,
        expected_plan_hash,
    )
    evidence_payload = _read_json(evidence_target)
    result_binding = evidence_payload.get("probe_result")
    if not isinstance(result_binding, Mapping):
        raise ValueError("public probe evidence result binding is missing")
    manifest_target = Path(
        str(result_binding.get("path") or "")
    ).expanduser().resolve()
    evidence = validate_probe_evidence(
        evidence_target,
        manifest_path=manifest_target,
        expected_plan_hash=expected_plan_hash,
    )
    observer_input = _build_public_probe_observer_input(
        plan=plan,
        evidence=evidence,
    )
    module_path = Path(__file__).resolve()
    probe_module_path = Path(
        sys.modules[validate_probe_evidence.__module__].__file__
    ).resolve()
    deterministic = {
        "schema": PUBLIC_PROBE_OBSERVER_BINDING_REPORT_SCHEMA,
        "task_id": (
            "paper_public_probe_evidence_observer_binding_fixture_v1"
        ),
        "inputs": {
            "probe_plan": {
                "path": str(plan_target),
                "file_sha256": sha256_file(plan_target),
                "plan_hash_sha256": plan["plan_hash_sha256"],
            },
            "probe_evidence": {
                "path": str(evidence_target),
                "file_sha256": sha256_file(evidence_target),
                "deterministic_result_hash": evidence[
                    "deterministic_result_hash"
                ],
            },
            "probe_manifest": {
                "path": str(manifest_target),
                "file_sha256": sha256_file(manifest_target),
                "deterministic_result_hash": result_binding[
                    "deterministic_result_hash"
                ],
            },
        },
        "observer_input": observer_input,
        "source_provenance": {
            "paper_observer_runtime": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            },
            "paper_public_readonly_probe": {
                "path": str(probe_module_path),
                "file_sha256": sha256_file(probe_module_path),
            },
        },
        "source_probe_network_requests": int(
            evidence["quality"]["network_requests"]
        ),
        "network_requests_performed_by_task": 0,
        "returns_or_pnl_read": False,
        "oos_read": False,
        "signals_read": False,
        "oms_transition_allowed": False,
        "oms_mutations": 0,
        "paper_forward_started": False,
        "private_api_keys": False,
        "live_orders": False,
        "leverage_or_margin": False,
        "grid_or_retune": False,
        "hypothesis_changed": False,
        "verdict": (
            "PUBLIC_PROBE_EVIDENCE_BOUND_TO_FAIL_CLOSED_OBSERVER_INPUT"
        ),
        "next_allowed_action": "paper_product_readiness_audit_v9",
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_snapshot_observer_bridge_report(
    *,
    public_reader_fixture_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    fixture_target = Path(public_reader_fixture_path).expanduser().resolve()
    fixture_report = _read_json(fixture_target)
    if (
        fixture_report.get("schema")
        != "trading_mvp_paper_public_reader_fixture_report_v1"
        or fixture_report.get("verdict")
        != "FIXTURE_PUBLIC_READER_ACCEPTED_NO_NETWORK"
        or fixture_report.get("network_requests") != 0
    ):
        raise ValueError("public reader fixture evidence is not accepted")
    fixture_deterministic = {
        key: value
        for key, value in fixture_report.items()
        if key
        not in {
            "module_path",
            "module_sha256",
            "deterministic_result_hash",
            "generated_at_utc",
        }
    }
    if fixture_report.get("deterministic_result_hash") != sha256_json(
        fixture_deterministic
    ):
        raise ValueError("public reader fixture semantic hash mismatch")
    contract_reference = fixture_report.get("contract")
    if not isinstance(contract_reference, Mapping):
        raise ValueError("public reader fixture contract reference is missing")
    contract_target = Path(
        str(contract_reference.get("path") or "")
    ).expanduser().resolve()
    if sha256_file(contract_target) != contract_reference.get("file_sha256"):
        raise ValueError("public reader fixture contract file hash mismatch")
    contract = _read_json(contract_target)
    now_ms = 1_800_000_000_000
    snapshots: dict[str, dict[str, Any]] = {}
    for venue in ("mexc", "gateio"):
        transport = FixturePublicGetTransport(_valid_fixture_outcomes(now_ms))
        reader = FixturePublicMarketReader(contract, transport)
        snapshots[venue] = reader.read_market_snapshot(
            venue=venue,
            symbol="HYPE_USDT",
            canonical_base="hype",
            observer_received_ts_ms=now_ms,
        )
    expected_hashes = {
        str(item["venue"]): str(item["snapshot_hash_sha256"])
        for item in fixture_report.get("success_scenarios") or []
    }
    observed_hashes = {
        venue: str(snapshot["snapshot_hash_sha256"])
        for venue, snapshot in snapshots.items()
    }
    if observed_hashes != expected_hashes:
        raise ValueError(
            "current normalized snapshots drift from fixture evidence"
        )
    sample = build_public_snapshot_health_sample(
        mexc_snapshot=snapshots["mexc"],
        gateio_snapshot=snapshots["gateio"],
    )
    reader_module_path = Path(
        sys.modules[FixturePublicMarketReader.__module__].__file__
    ).resolve()
    code_hashes = {
        "paper_public_reader": sha256_file(reader_module_path),
        "paper_observer_runtime": sha256_file(Path(__file__).resolve()),
    }
    input_merkle = sha256_json(
        {
            "fixture_report_sha256": sha256_file(fixture_target),
            "contract_sha256": sha256_file(contract_target),
            "code_hashes": code_hashes,
            "snapshot_hashes": observed_hashes,
            "sample_hash_sha256": sample["sample_hash_sha256"],
        }
    )
    deterministic = {
        "schema": PUBLIC_BRIDGE_REPORT_SCHEMA,
        "task_id": "paper_public_snapshot_observer_bridge_v1",
        "inputs": {
            "public_reader_fixture": {
                "path": str(fixture_target),
                "file_sha256": sha256_file(fixture_target),
                "deterministic_result_hash": fixture_report[
                    "deterministic_result_hash"
                ],
            },
            "public_reader_contract": {
                "path": str(contract_target),
                "file_sha256": sha256_file(contract_target),
                "contract_hash_sha256": contract_reference[
                    "contract_hash_sha256"
                ],
            },
        },
        "code_hashes": code_hashes,
        "input_merkle_sha256": input_merkle,
        "snapshot_hashes_match_fixture": True,
        "health_sample": sample,
        "health_decision": "NOT_EVALUATED_BRIDGE_ONLY",
        "oms_transition_allowed": False,
        "network_requests": 0,
        "oms_mutations": 0,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": "FIXTURE_PUBLIC_SNAPSHOT_OBSERVER_BRIDGE_ACCEPTED",
        "next_allowed_action": "paper_public_transport_adapter_v1",
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_health_contract_binding_fixture_report(
    *,
    bridge_report_path: str | Path,
    health_contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    bridge_target = Path(bridge_report_path).expanduser().resolve()
    bridge = _read_json(bridge_target)
    if (
        bridge.get("schema") != PUBLIC_BRIDGE_REPORT_SCHEMA
        or bridge.get("verdict")
        != "FIXTURE_PUBLIC_SNAPSHOT_OBSERVER_BRIDGE_ACCEPTED"
        or bridge.get("network_requests") != 0
        or bridge.get("oms_mutations") != 0
    ):
        raise ValueError("public snapshot bridge evidence is not accepted")
    bridge_deterministic = {
        key: value
        for key, value in bridge.items()
        if key not in {"deterministic_result_hash", "generated_at_utc"}
    }
    if bridge.get("deterministic_result_hash") != sha256_json(
        bridge_deterministic
    ):
        raise ValueError("public snapshot bridge semantic hash mismatch")
    sample = bridge.get("health_sample")
    if not isinstance(sample, Mapping):
        raise ValueError("public snapshot bridge health sample is missing")
    sample_deterministic = {
        key: value
        for key, value in sample.items()
        if key != "sample_hash_sha256"
    }
    if sample.get("sample_hash_sha256") != sha256_json(
        sample_deterministic
    ):
        raise ValueError("public snapshot bridge sample hash mismatch")

    health_target = Path(health_contract_path).expanduser().resolve()
    health_contract = validate_health_contract(health_target)
    health = evaluate_fixture_health(sample, health_contract)
    oms_transition_allowed = (
        health["decision"] == "HEALTHY_TRANSITION_ALLOWED"
    )
    if oms_transition_allowed:
        raise AssertionError(
            "binding fixture unexpectedly permits an OMS transition"
        )
    if health["decision"] != "BLOCK_TRANSITION":
        raise AssertionError(
            f"binding fixture produced {health['decision']}"
        )

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": PUBLIC_HEALTH_BINDING_REPORT_SCHEMA,
        "task_id": "paper_public_health_contract_binding_fixture_v1",
        "inputs": {
            "public_snapshot_bridge": {
                "path": str(bridge_target),
                "file_sha256": sha256_file(bridge_target),
                "deterministic_result_hash": bridge[
                    "deterministic_result_hash"
                ],
                "sample_hash_sha256": sample["sample_hash_sha256"],
            },
            "venue_health_contract": {
                "path": str(health_target),
                "file_sha256": sha256_file(health_target),
                "contract_hash_sha256": health_contract[
                    "contract_hash_sha256"
                ],
            },
        },
        "health": health,
        "oms_transition_allowed": oms_transition_allowed,
        "network_requests": 0,
        "oms_mutations": 0,
        "private_api_keys": False,
        "live_orders": False,
        "source_provenance": {
            "paper_observer_runtime": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "verdict": "FIXTURE_PUBLIC_HEALTH_BINDING_BLOCKED_AS_EXPECTED",
        "next_allowed_action": "paper_product_readiness_audit_v5",
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic fixture-only paper observer runtime"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--paper-plan", required=True)
    plan_parser.add_argument("--probe-report", required=True)
    plan_parser.add_argument("--runtime-contract", required=True)
    plan_parser.add_argument("--health-contract", required=True)
    plan_parser.add_argument("--fixture", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--audit", required=True)
    plan_parser.add_argument("--accepted", required=True)
    plan_parser.add_argument("--manifest", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--expected-plan-hash", required=True)
    sink_parser = subparsers.add_parser("sink")
    sink_parser.add_argument("--plan", required=True)
    sink_parser.add_argument("--expected-plan-hash", required=True)
    sink_parser.add_argument("--ledger", required=True)
    sink_parser.add_argument("--state", required=True)
    sink_parser.add_argument("--manifest", required=True)
    bridge_parser = subparsers.add_parser("public-bridge")
    bridge_parser.add_argument("--public-reader-fixture", required=True)
    bridge_parser.add_argument("--output", required=True)
    binding_parser = subparsers.add_parser("public-health-binding")
    binding_parser.add_argument("--bridge-report", required=True)
    binding_parser.add_argument("--health-contract", required=True)
    binding_parser.add_argument("--output", required=True)
    probe_binding_parser = subparsers.add_parser(
        "public-probe-evidence-binding"
    )
    probe_binding_parser.add_argument("--plan", required=True)
    probe_binding_parser.add_argument("--evidence", required=True)
    probe_binding_parser.add_argument("--expected-plan-hash", required=True)
    probe_binding_parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan":
        result = build_fixture_observer_plan(
            paper_plan_path=args.paper_plan,
            probe_report_path=args.probe_report,
            runtime_contract_path=args.runtime_contract,
            health_contract_path=args.health_contract,
            fixture_path=args.fixture,
            output_path=args.output,
            audit_path=args.audit,
            accepted_path=args.accepted,
            manifest_path=args.manifest,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    elif args.command == "run":
        result = run_fixture_observer_segment(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            progress=lambda row: print(json.dumps(row, ensure_ascii=False), flush=True),
        )
    elif args.command == "sink":
        result = run_fixture_observer_oms_sink(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            ledger_path=args.ledger,
            state_path=args.state,
            sink_manifest_path=args.manifest,
        )
    elif args.command == "public-bridge":
        result = build_public_snapshot_observer_bridge_report(
            public_reader_fixture_path=args.public_reader_fixture,
            output_path=args.output,
        )
    elif args.command == "public-probe-evidence-binding":
        result = build_public_probe_evidence_observer_binding_fixture_report(
            plan_path=args.plan,
            evidence_path=args.evidence,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
        )
    else:
        result = build_public_health_contract_binding_fixture_report(
            bridge_report_path=args.bridge_report,
            health_contract_path=args.health_contract,
            output_path=args.output,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
