from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import continuous_production
import dense_ws_next_window_reservation as window_reservation
import night_schedule_plan as pit_schedule


SCHEMA = "trading_mvp_dense_ws_no_skip_policy_candidate_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    value = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {target}")
    return value


def _write_json_atomic(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite immutable candidate policy: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} must use ISO-8601 time with UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _validate_reservation(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != window_reservation.SCHEMA or payload.get("mode") != "PlanOnly":
        raise ValueError("unsupported Dense window reservation")
    observed_hash = str(payload.get("reservation_hash") or "")
    hash_input = dict(payload)
    hash_input.pop("reservation_hash", None)
    if observed_hash != _canonical_hash(hash_input):
        raise ValueError("Dense window reservation hash mismatch")
    authorization = payload.get("authorization_boundary")
    if not isinstance(authorization, Mapping):
        raise ValueError("Dense window reservation authorization boundary is required")
    if authorization.get("collector_launch_allowed") is not False:
        raise ValueError("Dense window reservation must not authorize a collector")
    candidate = payload.get("reservation")
    if not isinstance(candidate, Mapping):
        raise ValueError("Dense window reservation payload is required")
    if candidate.get("suppressed_pit_run_ids") != []:
        raise ValueError("Dense window reservation must preserve PIT without suppression")
    return dict(candidate)


def _validate_amendment(
    plan: Mapping[str, Any],
    *,
    expected_plan_hash: str,
    reservation: Mapping[str, Any],
) -> dict[str, Any]:
    if plan.get("mode") != "PlanOnly" or plan.get("plan_hash") != expected_plan_hash:
        raise ValueError("amended PIT plan identity mismatch")
    amendment = plan.get("time_only_amendment")
    if not isinstance(amendment, Mapping):
        raise ValueError("amended PIT plan time_only_amendment is required")
    deferred = reservation.get("deferred_pit")
    if not isinstance(deferred, Mapping):
        raise ValueError("reservation deferred PIT binding is required")
    expected = {
        "run_id": deferred.get("run_id"),
        "original_start_local": deferred.get("original_start_local"),
        "original_end_local": deferred.get("original_end_local"),
        "new_start_local": deferred.get("new_start_local"),
        "new_end_local": deferred.get("new_end_local"),
        "hard_deadline_local": deferred.get("hard_deadline_local"),
    }
    for key, value in expected.items():
        if amendment.get(key) != value:
            raise ValueError(f"amended PIT plan {key} differs from reservation")
    if amendment.get("trade_contract_changed") is not False:
        raise ValueError("PIT amendment must not change the trade contract")
    return dict(amendment)


def build_candidate_policy(
    *,
    source_policy_path: str | Path,
    expected_source_policy_sha256: str,
    reservation_path: str | Path,
    expected_reservation_file_sha256: str,
    amended_pit_schedule_path: str | Path,
    expected_amended_pit_schedule_sha256: str,
    expected_amended_pit_plan_hash: str,
    output_path: str | Path,
    generated_at_local: str,
) -> dict[str, Any]:
    """Build a time-only policy candidate without changing trading contracts."""

    source_target = Path(source_policy_path).expanduser().resolve()
    reservation_target = Path(reservation_path).expanduser().resolve()
    amendment_target = Path(amended_pit_schedule_path).expanduser().resolve()
    if _sha256_file(source_target) != expected_source_policy_sha256:
        raise ValueError("source continuous policy file SHA-256 mismatch")
    if _sha256_file(reservation_target) != expected_reservation_file_sha256:
        raise ValueError("reservation file SHA-256 mismatch")
    if _sha256_file(amendment_target) != expected_amended_pit_schedule_sha256:
        raise ValueError("amended PIT schedule file SHA-256 mismatch")

    source = _read_json(source_target)
    if source.get("schema") != continuous_production.POLICY_SCHEMA:
        raise ValueError("unsupported source continuous policy schema")
    reservation_payload = _read_json(reservation_target)
    reservation = _validate_reservation(reservation_payload)
    amended_plan = _read_json(amendment_target)
    pit_schedule.validate_night_schedule_plan(amendment_target, expected_amended_pit_plan_hash)
    amendment = _validate_amendment(
        amended_plan,
        expected_plan_hash=expected_amended_pit_plan_hash,
        reservation=reservation,
    )

    generated = _parse_timestamp(generated_at_local, label="generated_at_local")
    campaign_id = str(reservation.get("campaign_id") or "")
    if not campaign_id:
        raise ValueError("reservation campaign_id is required")
    campaign_date = _parse_timestamp(
        reservation.get("start_local"),
        label="reservation.start_local",
    ).strftime("%Y%m%d")
    preceding = reservation.get("preceding_pit")
    deferred = reservation.get("deferred_pit")
    if not isinstance(preceding, Mapping) or not isinstance(deferred, Mapping):
        raise ValueError("reservation PIT bindings are required")

    hard_output_cap = int(reservation.get("hard_output_cap_bytes") or 0)
    source_cap = int(
        (source.get("accelerated_evidence_factory") or {}).get(
            "hard_campaign_output_cap_bytes"
        )
        or 0
    )
    if hard_output_cap <= 0 or hard_output_cap != source_cap:
        raise ValueError("reservation output cap differs from source policy")

    writer_sec = int(reservation.get("writer_duration_sec") or 0)
    max_runtime_sec = int(reservation.get("max_runtime_sec") or 0)
    configured_grace = int((source.get("runtime") or {}).get("shutdown_grace_sec") or 0)
    if writer_sec <= 0 or max_runtime_sec - writer_sec != configured_grace:
        raise ValueError("reservation runtime differs from source shutdown grace")

    candidate = copy.deepcopy(source)
    stale_amendment_fields = {
        key
        for key in candidate
        if key.startswith("pit_n") and key.endswith("_time_only_amendment")
    }
    for key in stale_amendment_fields:
        candidate.pop(key)
    candidate["policy_id"] = (
        f"trading_mvp_continuous_production_{campaign_date}_dense_ws_no_skip_planonly_v1"
    )
    candidate["effective_at"] = generated.isoformat()
    candidate["approved_by"] = "PLANONLY_NEXT_WINDOW_RESERVATION_NO_LAUNCH_APPROVAL"

    source_factory = source.get("accelerated_evidence_factory")
    if not isinstance(source_factory, Mapping):
        raise ValueError("source accelerated_evidence_factory is required")
    factory = copy.deepcopy(dict(source_factory))
    factory["factory_id"] = f"accelerated_evidence_factory_v1_{campaign_date}_no_skip_planonly_v1"
    factory["status"] = (
        "PLANONLY_FUTURE_WINDOW_NO_SKIP_CANDIDATE_SEPARATE_EXACT_APPROVAL_REQUIRED"
    )
    factory["market_data_sequence"] = [
        {
            "sequence": 1,
            "run_id": preceding["run_id"],
            "kind": "PREAPPROVED_SHORT_SEGMENT",
            "end_local": preceding["end_local"],
            "disposition": "PRESERVED_NOT_SKIPPED_BEFORE_DENSE",
        },
        {
            "sequence": 2,
            "run_id": f"{campaign_id}_phase_01",
            "kind": "LONG_CAMPAIGN_PHASE",
            "start_local": reservation["start_local"],
            "end_local": reservation["writer_deadline_local"],
            "hard_end_local": reservation["hard_deadline_local"],
            "writer_duration_sec": writer_sec,
            "uninterrupted_required": True,
        },
        {
            "sequence": 3,
            "run_id": deferred["run_id"],
            "kind": "PREAPPROVED_SHORT_SEGMENT",
            "start_local": deferred["new_start_local"],
            "end_local": deferred["new_end_local"],
            "hard_deadline_local": deferred["hard_deadline_local"],
            "duration_sec": int(
                (
                    _parse_timestamp(deferred["new_end_local"], label="deferred PIT end")
                    - _parse_timestamp(deferred["new_start_local"], label="deferred PIT start")
                ).total_seconds()
            ),
            "disposition": "PRESERVED_NOT_SKIPPED_AFTER_DENSE_FINALIZATION",
            "requires_dense_finalization": True,
            "requires_global_writer_claim_absent": True,
            "amended_schedule_plan_path": str(amendment_target),
        },
    ]
    factory["continuous_evidence_exception"] = {
        "enabled": True,
        "campaign_id": campaign_id,
        "window_id": reservation["window_id"],
        "start_local": reservation["start_local"],
        "writer_duration_sec": writer_sec,
        "writer_deadline_local": reservation["writer_deadline_local"],
        "hard_deadline_local": reservation["hard_deadline_local"],
        "uninterrupted_required": True,
        "suppressed_pit_run_ids": [],
        "suppression_disposition": "NOT_APPLICABLE_DEFERRED_PIT_PRESERVED",
        "reason": (
            "Keep one uninterrupted Dense market day while preserving the preceding PIT "
            "and deferring the overlapping PIT until after Dense finalization."
        ),
        "deferred_pit_run_id": deferred["run_id"],
        "deferred_pit_start_local": deferred["new_start_local"],
        "deferred_pit_end_local": deferred["new_end_local"],
        "deferred_pit_requires_dense_finalization": True,
        "deferred_pit_requires_global_writer_claim_absent": True,
    }
    factory["dense_writer_target_sec"] = writer_sec
    factory["dense_campaign_max_elapsed_sec"] = max_runtime_sec
    factory["dense_campaign_hard_deadline_local"] = reservation["hard_deadline_local"]
    candidate["accelerated_evidence_factory"] = factory
    candidate["pit_no_skip_time_only_amendment"] = {
        "source_policy_path": str(source_target),
        "source_policy_sha256": expected_source_policy_sha256,
        "reservation_path": str(reservation_target),
        "reservation_file_sha256": expected_reservation_file_sha256,
        "reservation_hash": reservation_payload["reservation_hash"],
        "amended_pit_schedule_path": str(amendment_target),
        "amended_pit_schedule_file_sha256": expected_amended_pit_schedule_sha256,
        "amended_pit_schedule_plan_hash": expected_amended_pit_plan_hash,
        "run_id": amendment["run_id"],
        "original_start_local": amendment["original_start_local"],
        "new_start_local": amendment["new_start_local"],
        "new_end_local": amendment["new_end_local"],
        "trade_contract_changed": False,
        "collector_launch_allowed": False,
        "contingent_on_fresh_pit_extension_approval": (
            reservation_payload.get("status")
            == "CONTINGENT_ON_FRESH_PIT_EXTENSION_APPROVAL"
        ),
    }

    allowed_top_level_changes = {
        "policy_id",
        "effective_at",
        "approved_by",
        "accelerated_evidence_factory",
        "pit_no_skip_time_only_amendment",
        *stale_amendment_fields,
    }
    for key in sorted(set(source) | set(candidate)):
        if key in allowed_top_level_changes:
            continue
        if source.get(key) != candidate.get(key):
            raise ValueError(f"candidate changed source policy outside time-only scope: {key}")

    _write_json_atomic(output_path, candidate)
    output_target = Path(output_path).expanduser().resolve()
    return {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "verdict": "TIME_ONLY_NO_SKIP_POLICY_CANDIDATE_VALID",
        "candidate_policy_path": str(output_target),
        "candidate_policy_sha256": _sha256_file(output_target),
        "campaign_id": campaign_id,
        "reservation_hash": reservation_payload["reservation_hash"],
        "amended_pit_plan_hash": expected_amended_pit_plan_hash,
        "collector_launch_allowed": False,
        "trade_contract_changed": False,
        "contingent_on_fresh_pit_extension_approval": candidate[
            "pit_no_skip_time_only_amendment"
        ]["contingent_on_fresh_pit_extension_approval"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a no-skip Dense continuous-policy candidate without authorizing a run."
    )
    parser.add_argument("--source-policy", type=Path, required=True)
    parser.add_argument("--expected-source-policy-sha256", required=True)
    parser.add_argument("--reservation", type=Path, required=True)
    parser.add_argument("--expected-reservation-file-sha256", required=True)
    parser.add_argument("--amended-pit-schedule", type=Path, required=True)
    parser.add_argument("--expected-amended-pit-schedule-sha256", required=True)
    parser.add_argument("--expected-amended-pit-plan-hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-at-local", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_candidate_policy(
        source_policy_path=args.source_policy,
        expected_source_policy_sha256=args.expected_source_policy_sha256,
        reservation_path=args.reservation,
        expected_reservation_file_sha256=args.expected_reservation_file_sha256,
        amended_pit_schedule_path=args.amended_pit_schedule,
        expected_amended_pit_schedule_sha256=args.expected_amended_pit_schedule_sha256,
        expected_amended_pit_plan_hash=args.expected_amended_pit_plan_hash,
        output_path=args.output,
        generated_at_local=args.generated_at_local,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
