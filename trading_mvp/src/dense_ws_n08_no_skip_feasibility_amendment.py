from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import night_schedule_plan as pit_schedule
from feasibility_gate import read_json


SCHEMA = "trading_mvp_dense_ws_n08_no_skip_feasibility_amendment_v1"
N08_RUN_ID = "pit_universe_v2_forward_20260805_n08"


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


def _write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} must use ISO-8601 time with UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _find_exact_segment(segments: Any, run_id: str) -> dict[str, Any]:
    if not isinstance(segments, list):
        raise ValueError("PIT plan segments must be a list")
    matches = [
        item for item in segments if isinstance(item, dict) and str(item.get("run_id") or "") == run_id
    ]
    if len(matches) != 1:
        raise ValueError(f"PIT plan must contain exactly one segment for run_id={run_id}")
    return dict(matches[0])


def _assert_planonly_false_flags(payload: Mapping[str, Any], *, label: str) -> None:
    for flag in (
        "would_start",
        "network_access",
        "returns_read",
        "pnl_computed",
        "oos_read",
        "grid_or_retune",
        "live_orders",
        "private_api_keys",
        "leverage_or_margin",
        "actual_collection_allowed",
    ):
        if payload.get(flag) is not False:
            raise ValueError(f"{label}.{flag} must be false")


def _validate_base_feasibility(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != "trading_mvp_dense_ws_campaign_feasibility_v1":
        raise ValueError("unsupported base feasibility schema")
    if payload.get("mode") != "PlanOnly" or payload.get("research_only") is not True:
        raise ValueError("base feasibility must be a research-only PlanOnly artifact")
    _assert_planonly_false_flags(payload, label="base feasibility")
    candidate = payload.get("frozen_candidate")
    if not isinstance(candidate, dict):
        raise ValueError("base feasibility frozen_candidate is required")
    observed_hash = _canonical_hash(candidate)
    if observed_hash != str(payload.get("candidate_contract_hash") or ""):
        raise ValueError("base feasibility candidate hash mismatch")
    if candidate.get("suppressed_pit_run_ids") != [N08_RUN_ID]:
        raise ValueError("base feasibility is not the expected n08-suppression candidate")
    return dict(candidate)


def _validate_no_skip_policy(
    policy: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    factory = policy.get("accelerated_evidence_factory")
    if not isinstance(factory, Mapping):
        raise ValueError("candidate policy accelerated_evidence_factory is required")
    exception = factory.get("continuous_evidence_exception")
    if not isinstance(exception, Mapping):
        raise ValueError("candidate policy continuous_evidence_exception is required")
    if exception.get("suppressed_pit_run_ids") != []:
        raise ValueError("candidate policy must not suppress PIT n08")
    expected = {
        "campaign_id": candidate.get("hypothesis_id", "").replace(
            "dense_ws_microstructure_regime_filter_v1",
            "dense_ws_microstructure_regime_filter_v1_20260804_aef_24h",
        ),
        "start_local": candidate.get("requested_start_local"),
        "writer_deadline_local": candidate.get("writer_deadline_local"),
        "hard_deadline_local": candidate.get("hard_deadline_local"),
    }
    for key, value in expected.items():
        if exception.get(key) != value:
            raise ValueError(f"candidate policy continuous exception {key} mismatch")
    if exception.get("deferred_pit_run_id") != N08_RUN_ID:
        raise ValueError("candidate policy deferred_pit_run_id must bind n08")
    if exception.get("deferred_pit_requires_dense_finalization") is not True:
        raise ValueError("candidate policy must require dense finalization before n08")
    if exception.get("deferred_pit_requires_global_writer_claim_absent") is not True:
        raise ValueError("candidate policy must require an absent global writer claim before n08")
    return dict(exception)


def _validate_amended_pit_plan(
    plan: Mapping[str, Any],
    *,
    expected_plan_hash: str,
    exception: Mapping[str, Any],
) -> dict[str, Any]:
    if plan.get("schema") != pit_schedule.PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError("amended PIT schedule must be a PlanOnly night schedule")
    if plan.get("plan_hash") != expected_plan_hash:
        raise ValueError("amended PIT schedule plan hash mismatch")
    amendment = plan.get("time_only_amendment")
    if not isinstance(amendment, Mapping):
        raise ValueError("amended PIT schedule time_only_amendment is required")
    if amendment.get("run_id") != N08_RUN_ID:
        raise ValueError("amended PIT schedule must bind n08")
    if amendment.get("trade_contract_changed") is not False:
        raise ValueError("PIT time amendment must not change the trade contract")
    segment = _find_exact_segment(plan.get("segments"), N08_RUN_ID)
    for key in ("start_local", "end_local", "hard_deadline_local"):
        if segment.get(key) != amendment.get(f"new_{key}", amendment.get(key)):
            if key == "hard_deadline_local" and segment.get(key) == amendment.get(key):
                continue
            raise ValueError(f"PIT time amendment {key} does not match runtime segment")
    if segment.get("start_local") != exception.get("deferred_pit_start_local"):
        raise ValueError("candidate policy n08 start differs from amended PIT schedule")
    if segment.get("end_local") != exception.get("deferred_pit_end_local"):
        raise ValueError("candidate policy n08 end differs from amended PIT schedule")
    return segment


def build_no_skip_feasibility_amendment(
    *,
    base_feasibility_path: str | Path,
    expected_base_feasibility_sha256: str,
    continuous_policy_path: str | Path,
    amended_pit_schedule_path: str | Path,
    expected_amended_pit_plan_hash: str,
    output_path: str | Path,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Rebind only timing/provenance without re-reading legacy partial market data."""

    base_target = Path(base_feasibility_path).expanduser().resolve()
    policy_target = Path(continuous_policy_path).expanduser().resolve()
    pit_target = Path(amended_pit_schedule_path).expanduser().resolve()
    output_target = Path(output_path).expanduser().resolve()
    if output_target.exists():
        raise ValueError(f"refusing to overwrite immutable feasibility amendment: {output_target}")
    if _sha256_file(base_target) != expected_base_feasibility_sha256:
        raise ValueError("base feasibility file SHA-256 mismatch")

    base = read_json(base_target)
    candidate = _validate_base_feasibility(base)
    policy = read_json(policy_target)
    exception = _validate_no_skip_policy(policy, candidate=candidate)
    pit_plan = read_json(pit_target)
    n08 = _validate_amended_pit_plan(
        pit_plan,
        expected_plan_hash=expected_amended_pit_plan_hash,
        exception=exception,
    )

    window = base.get("window_feasibility")
    if not isinstance(window, Mapping):
        raise ValueError("base feasibility window_feasibility is required")
    phases = window.get("phases")
    if not isinstance(phases, list) or len(phases) != 1 or not isinstance(phases[0], Mapping):
        raise ValueError("base feasibility must contain exactly one dense phase")
    phase = phases[0]
    dense_start = _parse_timestamp(phase.get("start_local"), label="dense phase start_local")
    dense_hard_end = _parse_timestamp(phase.get("hard_end_local"), label="dense phase hard_end_local")
    n08_start = _parse_timestamp(n08.get("start_local"), label="n08 start_local")
    n08_end = _parse_timestamp(n08.get("end_local"), label="n08 end_local")
    n08_deadline = _parse_timestamp(n08.get("hard_deadline_local"), label="n08 hard_deadline_local")
    if n08_start <= dense_hard_end:
        raise ValueError("n08 must start strictly after dense hard finalization")
    if n08_end > n08_deadline:
        raise ValueError("n08 must finish by its PIT hard deadline")
    if max(dense_start, n08_start) < min(dense_hard_end, n08_end):
        raise ValueError("dense phase and n08 overlap")

    amendment = {
        "schema": SCHEMA,
        "kind": "TIME_ONLY_NO_SKIP_N08",
        "base_feasibility_path": str(base_target),
        "base_feasibility_sha256": expected_base_feasibility_sha256,
        "base_candidate_contract_hash": str(base.get("candidate_contract_hash") or ""),
        "continuous_policy_path": str(policy_target),
        "continuous_policy_sha256": _sha256_file(policy_target),
        "amended_pit_schedule_path": str(pit_target),
        "amended_pit_schedule_file_sha256": _sha256_file(pit_target),
        "amended_pit_schedule_plan_hash": expected_amended_pit_plan_hash,
        "n08_run_id": N08_RUN_ID,
        "dense_hard_finalization_local": dense_hard_end.isoformat(),
        "n08_start_local": n08_start.isoformat(),
        "n08_end_local": n08_end.isoformat(),
        "n08_hard_deadline_local": n08_deadline.isoformat(),
        "global_writer_gap_sec": int((n08_start - dense_hard_end).total_seconds()),
        "legacy_partial_market_data_reread": False,
        "network_access": False,
        "actual_collection_allowed": False,
        "trade_contract_changed": False,
    }

    amended = copy.deepcopy(base)
    amended_candidate = amended["frozen_candidate"]
    amended_candidate["continuous_policy_sha256"] = amendment["continuous_policy_sha256"]
    amended_candidate["pit_schedule_sha256"] = amendment["amended_pit_schedule_file_sha256"]
    amended_candidate["suppressed_pit_run_ids"] = []
    amended["candidate_contract_hash"] = _canonical_hash(amended_candidate)
    amended["window_feasibility"]["suppressed_pit_run_ids"] = []
    amended["window_feasibility"]["pit_blackouts"] = []
    amended["window_feasibility"]["preserved_post_dense_pit_segment"] = {
        "run_id": N08_RUN_ID,
        "start_local": n08_start.isoformat(),
        "end_local": n08_end.isoformat(),
        "requires_dense_finalization": True,
        "requires_global_writer_claim_absent": True,
    }
    amended["time_only_n08_no_skip_amendment"] = amendment
    amended["generated_at_utc"] = generated_at_utc
    _assert_planonly_false_flags(amended, label="amended feasibility")

    _write_json_atomic(output_target, amended)
    persisted = read_json(output_target)
    persisted_candidate = _validate_base_feasibility(
        {
            **persisted,
            "frozen_candidate": {
                **persisted["frozen_candidate"],
                "suppressed_pit_run_ids": [N08_RUN_ID],
            },
            "candidate_contract_hash": _canonical_hash(
                {
                    **persisted["frozen_candidate"],
                    "suppressed_pit_run_ids": [N08_RUN_ID],
                }
            ),
        }
    )
    if persisted_candidate["hypothesis_id"] != candidate["hypothesis_id"]:
        raise ValueError("persisted feasibility amendment changed the hypothesis")
    return {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "verdict": "TIME_ONLY_N08_NO_SKIP_FEASIBILITY_VALID",
        "feasibility_path": str(output_target),
        "feasibility_sha256": _sha256_file(output_target),
        "candidate_contract_hash": str(persisted["candidate_contract_hash"]),
        "time_only_n08_no_skip_amendment": amendment,
        "actual_collection_allowed": False,
        "network_access": False,
        "legacy_partial_market_data_reread": False,
        "returns_read": False,
        "pnl_read": False,
        "oos_run": False,
        "grid_or_retune": False,
        "paper_or_live": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a dense-WS time-only no-skip n08 feasibility amendment without reading market data."
    )
    parser.add_argument("--base-feasibility", required=True)
    parser.add_argument("--expected-base-feasibility-sha256", required=True)
    parser.add_argument("--continuous-policy", required=True)
    parser.add_argument("--amended-pit-schedule", required=True)
    parser.add_argument("--expected-amended-pit-plan-hash", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_no_skip_feasibility_amendment(
        base_feasibility_path=args.base_feasibility,
        expected_base_feasibility_sha256=args.expected_base_feasibility_sha256,
        continuous_policy_path=args.continuous_policy,
        amended_pit_schedule_path=args.amended_pit_schedule,
        expected_amended_pit_plan_hash=args.expected_amended_pit_plan_hash,
        output_path=args.output,
        generated_at_utc=args.generated_at_utc,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
