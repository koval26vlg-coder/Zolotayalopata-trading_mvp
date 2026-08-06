from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from feasibility_gate import sha256_file
from pit_membership_drift_evaluator import (
    EVALUATION_SCHEMA,
    _result_hash as membership_evaluation_result_hash,
    validate_evaluation_input_plan,
)


PLAN_SCHEMA = "pit_membership_drift_execution_probe_plan_v1"
PLAN_MODE = "PlanOnly"
PLAN_DECISION = "PIT_MEMBERSHIP_DRIFT_EXECUTION_PROBE_PLAN_READY_REQUIRES_EXPLICIT_APPROVAL"
SAMPLE_SCHEMA = "pit_membership_drift_execution_probe_sample_v1"
MANIFEST_SCHEMA = "pit_membership_drift_execution_probe_manifest_v1"
MANIFEST_MODE = "pit_membership_drift_execution_probe_collect"
EVALUATION_OUTPUT_SCHEMA = "pit_membership_drift_execution_probe_evaluation_v1"
SUPPORTED_VENUES = ("mexc", "gateio")


def build_execution_probe_plan(
    evaluation_path: str | Path,
    output_path: str | Path,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    evaluation_target = Path(evaluation_path).expanduser().resolve()
    output_target = Path(output_path).expanduser().resolve()
    if output_target.exists():
        raise FileExistsError(f"execution-probe plan already exists: {output_target}")
    evaluation = _read_json(evaluation_target)
    _validate_accepted_evaluation(evaluation_target, evaluation)

    full_plan_target = Path(str(evaluation["plan_path"])).expanduser().resolve()
    full_plan_validation = validate_evaluation_input_plan(full_plan_target, str(evaluation["plan_hash"]))
    full_plan = _read_json(full_plan_target)
    sealed = full_plan["sealed_input"]
    contract = sealed["hypothesis_contract"]
    normal_events = evaluation.get("normal_events") or []
    candidate_bases = sorted(
        {
            str(event.get("base") or "").strip().upper()
            for event in normal_events
            if str(event.get("base") or "").strip()
        }
    )
    if not candidate_bases:
        raise ValueError("accepted evaluation has no executable event bases for the probe")
    for event in normal_events:
        if str(event.get("long_venue") or "") not in SUPPORTED_VENUES:
            raise ValueError("accepted evaluation contains an unsupported long venue")
        if str(event.get("short_venue") or "") not in SUPPORTED_VENUES:
            raise ValueError("accepted evaluation contains an unsupported short venue")

    route_counts: dict[str, int] = {}
    for event in normal_events:
        key = f"{event['long_venue']}->{event['short_venue']}"
        route_counts[key] = route_counts.get(key, 0) + 1

    sealed_probe = {
        "hypothesis_id": str(evaluation["hypothesis_id"]),
        "source": {
            "evaluation_path": str(evaluation_target),
            "evaluation_file_sha256": sha256_file(evaluation_target),
            "evaluation_result_hash": str(evaluation["deterministic_result_hash"]),
            "evaluation_verdict": str(evaluation["verdict"]),
            "full_plan_path": str(full_plan_target),
            "full_plan_file_sha256": sha256_file(full_plan_target),
            "full_plan_hash": full_plan_validation["plan_hash"],
            "input_merkle_root": full_plan_validation["input_merkle_root"],
            "hypothesis_contract_sha256": str(evaluation["hypothesis_contract_sha256"]),
            "cost_profile_sha256": str(evaluation["cost_profile_sha256"]),
        },
        "instrument_scope": {
            "venues": list(SUPPORTED_VENUES),
            "market_type": "linear_perp",
            "quote": "USDT",
            "candidate_bases": candidate_bases,
            "candidate_count": len(candidate_bases),
            "candidate_selection": "all unique bases from accepted OOS normal events; no top-N or outcome pruning",
            "historical_route_counts": dict(sorted(route_counts.items())),
            "sampling_order": "lexicographic candidate bases in deterministic round-robin order",
        },
        "collection_contract": {
            "duration_sec": 1200,
            "interval_sec": 5,
            "planned_attempts": 240,
            "target_notional_quote_per_leg": float(contract["position"]["notional_quote_per_leg"]),
            "depth_limit": 50,
            "max_quote_age_sec": 10.0,
            "max_cross_venue_skew_sec": 5.0,
            "max_index_divergence_bps": 100.0,
            "max_mark_index_divergence_bps": 200.0,
            "sample_unit": "one base with simultaneous public depth evidence from both venues",
            "valid_snapshot_definition": (
                "matching live linear-perp identity on both venues with fresh synchronized depth and complete "
                "$500 buy and sell VWAP on every leg"
            ),
            "public_data_only": True,
            "api_keys": False,
            "resume_same_run_id_only": True,
            "immutable_append_only_samples": True,
        },
        "acceptance_gates": {
            "minimum_valid_snapshots": 180,
            "minimum_coverage_ratio": 0.80,
            "maximum_p95_impact_bps_per_leg": 10.0,
            "minimum_coverage_ratio_per_candidate_base": 0.80,
            "maximum_p95_impact_bps_per_candidate_base_leg": 10.0,
            "minimum_elapsed_active_sec": 1200,
            "all_candidate_bases_attempted": True,
            "impact_definition": (
                "adverse VWAP displacement from same-side BBO for $500; both pooled venue-side and "
                "candidate-base venue-side p95 gates apply"
            ),
            "failed_probe_verdict": "REJECT_EXECUTION",
            "passed_probe_verdict": "PAPER_READY",
            "capacity_reduction_after_failure_allowed": False,
        },
    }
    if sealed_probe["collection_contract"]["target_notional_quote_per_leg"] != 500.0:
        raise ValueError("execution-probe notional must remain frozen at $500 per leg")
    plan_hash = _canonical_hash(sealed_probe)
    approval_phrase = (
        "подтверждаю visible PIT membership-drift execution probe "
        f"plan_hash={plan_hash} на 20 минут"
    )
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "decision": PLAN_DECISION,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "would_start": False,
        "network_access": False,
        "collect_started": False,
        "requires_explicit_user_approval_for_actual_probe": True,
        "plan_hash": plan_hash,
        **sealed_probe,
        "approval_phrase": approval_phrase,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
        "next_allowed_action": "request_explicit_user_approval_for_exact_hash_bound_20m_probe",
        "next_allowed_command": approval_phrase,
        "output_path": str(output_target),
    }
    _write_json_immutable(output_target, plan)
    return plan


def validate_execution_probe_plan(
    plan_path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    plan = _read_json(target)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != PLAN_MODE:
        raise ValueError(f"expected {PLAN_SCHEMA} {PLAN_MODE} artifact")
    if plan.get("decision") != PLAN_DECISION or plan.get("research_only") is not True:
        raise ValueError("execution-probe PlanOnly decision is invalid")
    sealed_probe = {
        key: plan[key]
        for key in (
            "hypothesis_id",
            "source",
            "instrument_scope",
            "collection_contract",
            "acceptance_gates",
        )
    }
    observed_hash = _canonical_hash(sealed_probe)
    if plan.get("plan_hash") != observed_hash:
        raise ValueError("execution-probe plan hash mismatch")
    if expected_plan_hash is not None and observed_hash != expected_plan_hash:
        raise ValueError("execution-probe plan does not match the expected plan hash")
    if plan.get("would_start") is not False or plan.get("network_access") is not False:
        raise ValueError("execution-probe PlanOnly unexpectedly starts network work")
    for field in ("paper_forward_allowed", "live_orders", "api_keys", "leverage_or_margin", "grid_search", "retune"):
        if plan.get(field) is not False:
            raise ValueError(f"execution-probe PlanOnly safety flag must be false: {field}")
    contract = plan.get("collection_contract") or {}
    gates = plan.get("acceptance_gates") or {}
    expected = {
        "duration_sec": 1200,
        "interval_sec": 5,
        "planned_attempts": 240,
        "target_notional_quote_per_leg": 500.0,
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise ValueError(f"execution-probe frozen collection contract mismatch: {key}")
    if gates.get("minimum_valid_snapshots") != 180:
        raise ValueError("execution-probe minimum valid snapshots mismatch")
    if float(gates.get("minimum_coverage_ratio") or 0.0) != 0.80:
        raise ValueError("execution-probe minimum coverage mismatch")
    if float(gates.get("maximum_p95_impact_bps_per_leg") or 0.0) != 10.0:
        raise ValueError("execution-probe p95 impact gate mismatch")
    if float(gates.get("minimum_coverage_ratio_per_candidate_base") or 0.0) != 0.80:
        raise ValueError("execution-probe per-base coverage gate mismatch")
    if float(gates.get("maximum_p95_impact_bps_per_candidate_base_leg") or 0.0) != 10.0:
        raise ValueError("execution-probe per-base p95 impact gate mismatch")
    bases = plan.get("instrument_scope", {}).get("candidate_bases") or []
    normalized = sorted({str(value).strip().upper() for value in bases if str(value).strip()})
    if not normalized or normalized != bases:
        raise ValueError("execution-probe candidate bases must be non-empty, unique and sorted")

    source = plan.get("source") or {}
    evaluation_target = _verify_file(
        source.get("evaluation_path"), source.get("evaluation_file_sha256"), "evaluation"
    )
    evaluation = _read_json(evaluation_target)
    _validate_accepted_evaluation(evaluation_target, evaluation)
    if evaluation.get("deterministic_result_hash") != source.get("evaluation_result_hash"):
        raise ValueError("execution-probe evaluation result binding mismatch")
    full_plan_target = _verify_file(
        source.get("full_plan_path"), source.get("full_plan_file_sha256"), "full plan"
    )
    validation = validate_evaluation_input_plan(full_plan_target, str(source.get("full_plan_hash") or ""))
    if validation["input_merkle_root"] != source.get("input_merkle_root"):
        raise ValueError("execution-probe input Merkle binding mismatch")
    return {
        "plan_path": str(target),
        "plan_file_sha256": sha256_file(target),
        "plan_hash": observed_hash,
        "candidate_bases": normalized,
        "hypothesis_id": str(plan["hypothesis_id"]),
    }


def evaluate_execution_probe(
    plan_path: str | Path,
    manifest_path: str | Path,
    output_path: str | Path,
    *,
    expected_plan_hash: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan_target = Path(plan_path).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    output_target = Path(output_path).expanduser().resolve()
    if output_target.exists():
        raise FileExistsError(f"execution-probe evaluation already exists: {output_target}")
    validation = validate_execution_probe_plan(plan_target, expected_plan_hash)
    plan = _read_json(plan_target)
    manifest = _read_json(manifest_target)
    _validate_manifest(manifest_target, manifest, plan_target, validation)
    sample_target = _verify_file(
        manifest.get("sample_path"), manifest.get("sample_file_sha256"), "execution-probe samples"
    )
    rows = list(_read_jsonl(sample_target))
    if len(rows) != int(manifest.get("attempted_snapshots") or -1):
        raise ValueError("execution-probe manifest sample count mismatch")

    candidates = validation["candidate_bases"]
    valid_rows = 0
    attempted_by_base = {base: 0 for base in candidates}
    valid_by_base = {base: 0 for base in candidates}
    impacts_by_leg: dict[str, list[float]] = {
        f"{venue}_{side}": []
        for venue in SUPPORTED_VENUES
        for side in ("buy", "sell")
    }
    impacts_by_base_leg: dict[str, dict[str, list[float]]] = {
        base: {
            f"{venue}_{side}": []
            for venue in SUPPORTED_VENUES
            for side in ("buy", "sell")
        }
        for base in candidates
    }
    invalid_reason_counts: dict[str, int] = {}
    for expected_index, row in enumerate(rows):
        if row.get("schema") != SAMPLE_SCHEMA:
            raise ValueError(f"execution-probe sample schema mismatch at index {expected_index}")
        if int(row.get("attempt_index", -1)) != expected_index:
            raise ValueError("execution-probe sample indices must be contiguous from zero")
        if row.get("plan_hash") != validation["plan_hash"]:
            raise ValueError("execution-probe sample plan hash mismatch")
        expected_base = candidates[expected_index % len(candidates)]
        base = str(row.get("base") or "").upper()
        if base != expected_base:
            raise ValueError("execution-probe sample violates deterministic round-robin order")
        attempted_by_base[base] += 1
        pair = row.get("pair") or {}
        if str(pair.get("base") or "").upper() != base:
            raise ValueError("execution-probe sample pair base mismatch")
        if pair.get("fully_valid") is True:
            row_impacts = _pair_impacts(pair, float(plan["collection_contract"]["target_notional_quote_per_leg"]))
            for leg, impact in row_impacts.items():
                impacts_by_leg[leg].append(impact)
                impacts_by_base_leg[base][leg].append(impact)
            valid_rows += 1
            valid_by_base[base] += 1
        else:
            reasons = pair.get("invalid_reasons") or ["unspecified_invalid_snapshot"]
            for reason in reasons:
                key = str(reason)
                invalid_reason_counts[key] = invalid_reason_counts.get(key, 0) + 1

    attempted = len(rows)
    coverage = valid_rows / attempted if attempted else 0.0
    p95_by_leg = {
        leg: (_nearest_rank(values, 0.95) if values else math.inf)
        for leg, values in impacts_by_leg.items()
    }
    p95_impact = max(p95_by_leg.values(), default=math.inf)
    coverage_by_base = {
        base: (valid_by_base[base] / attempted_by_base[base] if attempted_by_base[base] else 0.0)
        for base in candidates
    }
    p95_by_base_leg = {
        base: {
            leg: (_nearest_rank(values, 0.95) if values else math.inf)
            for leg, values in by_leg.items()
        }
        for base, by_leg in impacts_by_base_leg.items()
    }
    worst_p95_by_base = {
        base: max(by_leg.values(), default=math.inf)
        for base, by_leg in p95_by_base_leg.items()
    }
    gates = plan["acceptance_gates"]
    elapsed_active_sec = float(manifest.get("elapsed_active_sec") or 0.0)
    rejection_reasons: list[str] = []
    if elapsed_active_sec < float(gates["minimum_elapsed_active_sec"]):
        rejection_reasons.append("probe_duration_below_gate")
    if valid_rows < int(gates["minimum_valid_snapshots"]):
        rejection_reasons.append("valid_snapshots_below_gate")
    if coverage < float(gates["minimum_coverage_ratio"]):
        rejection_reasons.append("coverage_ratio_below_gate")
    if p95_impact > float(gates["maximum_p95_impact_bps_per_leg"]):
        rejection_reasons.append("p95_impact_above_gate")
    if any(count == 0 for count in attempted_by_base.values()):
        rejection_reasons.append("candidate_base_attempt_coverage_incomplete")
    for base in candidates:
        if coverage_by_base[base] < float(gates["minimum_coverage_ratio_per_candidate_base"]):
            rejection_reasons.append(f"candidate_base_coverage_below_gate:{base}")
        if worst_p95_by_base[base] > float(gates["maximum_p95_impact_bps_per_candidate_base_leg"]):
            rejection_reasons.append(f"candidate_base_p95_impact_above_gate:{base}")

    verdict = "PAPER_READY" if not rejection_reasons else "REJECT_EXECUTION"
    paper_allowed = verdict == "PAPER_READY"
    metrics = {
        "elapsed_active_sec": elapsed_active_sec,
        "attempted_snapshots": attempted,
        "valid_snapshots": valid_rows,
        "coverage_ratio": coverage,
        "impact_observations": sum(len(values) for values in impacts_by_leg.values()),
        "p95_impact_bps_by_leg": p95_by_leg,
        "p95_impact_bps_per_leg": p95_impact,
        "attempted_snapshots_by_base": attempted_by_base,
        "valid_snapshots_by_base": valid_by_base,
        "coverage_ratio_by_base": coverage_by_base,
        "p95_impact_bps_by_base_leg": p95_by_base_leg,
        "worst_p95_impact_bps_by_base": worst_p95_by_base,
        "invalid_reason_counts": dict(sorted(invalid_reason_counts.items())),
    }
    artifact: dict[str, Any] = {
        "schema": EVALUATION_OUTPUT_SCHEMA,
        "mode": "offline_hash_bound_execution_probe_evaluation",
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "hypothesis_id": validation["hypothesis_id"],
        "plan_path": str(plan_target),
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": validation["plan_hash"],
        "manifest_path": str(manifest_target),
        "manifest_file_sha256": sha256_file(manifest_target),
        "sample_path": str(sample_target),
        "sample_file_sha256": sha256_file(sample_target),
        "source_evaluation_result_hash": plan["source"]["evaluation_result_hash"],
        "metrics": metrics,
        "acceptance_gates": gates,
        "verdict": verdict,
        "rejection_reasons": rejection_reasons,
        "next_allowed_action": (
            "request_explicit_user_approval_for_bounded_paper_forward"
            if paper_allowed
            else "close_hypothesis_without_retune"
        ),
        "next_allowed_command": (
            "REQUEST_EXPLICIT_USER_APPROVAL_FOR_PIT_PAPER_FORWARD_PLANONLY"
            if paper_allowed
            else "NO_COMMAND_TERMINAL_HYPOTHESIS_CLOSED"
        ),
        "paper_forward_allowed": paper_allowed,
        "requires_explicit_user_approval_for_paper_forward": paper_allowed,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
        "network_access": False,
    }
    artifact["deterministic_result_hash"] = _artifact_result_hash(artifact)
    _write_json_immutable(output_target, artifact)
    return artifact


def _validate_accepted_evaluation(path: Path, evaluation: dict[str, Any]) -> None:
    if evaluation.get("schema") != EVALUATION_SCHEMA:
        raise ValueError(f"expected {EVALUATION_SCHEMA} evaluation")
    observed_hash = membership_evaluation_result_hash(
        evaluation,
        {"deterministic_result_hash"},
    )
    if evaluation.get("deterministic_result_hash") != observed_hash:
        raise ValueError(f"evaluation deterministic result hash mismatch: {path}")
    if evaluation.get("verdict") != "ACCEPT_FOR_SHORT_EXECUTION_PROBE":
        raise ValueError("execution probe requires ACCEPT_FOR_SHORT_EXECUTION_PROBE")
    if evaluation.get("execution_probe_allowed") is not True:
        raise ValueError("accepted evaluation did not open the execution-probe gate")
    if evaluation.get("deterministic_repeats_match") is not True:
        raise ValueError("accepted evaluation deterministic repeats did not match")
    for field in ("paper_forward_allowed", "live_orders", "api_keys", "grid_search", "retune", "network_access"):
        if evaluation.get(field) is not False:
            raise ValueError(f"accepted evaluation safety flag must be false: {field}")


def _validate_manifest(
    manifest_path: Path,
    manifest: dict[str, Any],
    plan_path: Path,
    plan_validation: dict[str, Any],
) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("mode") != MANIFEST_MODE:
        raise ValueError("unsupported execution-probe manifest schema/mode")
    if manifest.get("final") is not True or manifest.get("incomplete") is not False:
        raise ValueError("execution-probe manifest is not final")
    if Path(str(manifest.get("plan_path") or "")).expanduser().resolve() != plan_path:
        raise ValueError("execution-probe manifest plan path mismatch")
    if manifest.get("plan_file_sha256") != plan_validation["plan_file_sha256"]:
        raise ValueError("execution-probe manifest plan file hash mismatch")
    if manifest.get("plan_hash") != plan_validation["plan_hash"]:
        raise ValueError("execution-probe manifest plan hash mismatch")
    if manifest.get("stop_reason") != "duration_complete":
        raise ValueError("execution-probe manifest did not complete the frozen duration")
    if manifest.get("network_access") is not True:
        raise ValueError("execution-probe manifest must identify public network collection")
    for field in ("grid_search", "retune", "paper_forward", "live_orders", "api_keys"):
        if manifest.get(field) is not False:
            raise ValueError(f"execution-probe manifest safety flag must be false: {field}")
    if not str(manifest.get("run_id") or "").strip():
        raise ValueError(f"execution-probe manifest has no run_id: {manifest_path}")


def _pair_impacts(pair: dict[str, Any], target_notional: float) -> dict[str, float]:
    venues = pair.get("venues") or {}
    fills = pair.get("depth_fills") or {}
    impacts: dict[str, float] = {}
    for venue in SUPPORTED_VENUES:
        row = venues.get(venue) or {}
        venue_fills = fills.get(venue) or {}
        bid = _positive_float(row.get("bid_price"), f"{venue} bid")
        ask = _positive_float(row.get("ask_price"), f"{venue} ask")
        for side, bbo in (("buy", ask), ("sell", bid)):
            fill = venue_fills.get(side) or {}
            if fill.get("complete") is not True:
                raise ValueError(f"fully-valid sample has incomplete {venue} {side} fill")
            target = _positive_float(fill.get("target_quote_notional"), f"{venue} {side} target")
            filled = _positive_float(fill.get("filled_quote_notional"), f"{venue} {side} filled")
            if not math.isclose(target, target_notional) or filled + 1e-9 < target_notional:
                raise ValueError(f"fully-valid sample does not prove ${target_notional:g} on {venue} {side}")
            vwap = _positive_float(fill.get("vwap"), f"{venue} {side} vwap")
            adverse = (vwap / bbo - 1.0) if side == "buy" else (bbo / vwap - 1.0)
            impacts[f"{venue}_{side}"] = max(0.0, adverse * 10_000.0)
    return impacts


def _positive_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"missing or invalid {label}") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"missing or invalid {label}")
    return result


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _artifact_result_hash(payload: dict[str, Any]) -> str:
    ignored = {"generated_at_utc", "deterministic_result_hash"}
    return _canonical_hash({key: value for key, value in payload.items() if key not in ignored})


def _verify_file(path_value: Any, expected_hash: Any, label: str) -> Path:
    path = Path(str(path_value or "")).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} file not found: {path}")
    observed = sha256_file(path)
    if observed != str(expected_hash or ""):
        raise ValueError(f"{label} file hash mismatch")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL object required: {path}:{line_number}")
            yield value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_immutable(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PIT membership-drift hash-bound execution probe")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Build immutable execution-probe PlanOnly")
    plan.add_argument("--evaluation", required=True)
    plan.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate-plan", help="Validate execution-probe PlanOnly")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash")
    evaluate = subparsers.add_parser("evaluate", help="Evaluate a completed public execution probe offline")
    evaluate.add_argument("--plan", required=True)
    evaluate.add_argument("--expected-plan-hash")
    evaluate.add_argument("--manifest", required=True)
    evaluate.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        result = build_execution_probe_plan(args.evaluation, args.output)
    elif args.command == "validate-plan":
        result = validate_execution_probe_plan(args.plan, args.expected_plan_hash)
    elif args.command == "evaluate":
        result = evaluate_execution_probe(
            args.plan,
            args.manifest,
            args.output,
            expected_plan_hash=args.expected_plan_hash,
        )
    else:
        raise ValueError(f"unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
