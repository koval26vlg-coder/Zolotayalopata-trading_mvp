from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import gate_historical_membership_v3 as membership_v3


CLOSURE_SCHEMA = "trading_mvp_gate_historical_membership_v3_archive_source_closure_v1"
MANIFEST_SCHEMA = "trading_mvp_gate_historical_membership_v3_archive_source_closure_manifest_v1"
VERDICT = "INSUFFICIENT_SOURCE_QUALITY"
BRANCH_STATUS = "CLOSED_WITHOUT_HISTORY_OR_OOS"
NEXT_ALLOWED_ACTION = "select_new_materially_distinct_planonly_hypothesis"
REASON_CODE = "MISSING_END_DELISTED_ARCHIVE_AVAILABILITY_BELOW_FROZEN_GATE"
MAX_RUNTIME_SEC = 300


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {resolved}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {resolved}")
    return value


def _write_json_immutable(path: Path, value: Mapping[str, Any]) -> None:
    payload = dict(value)
    if path.exists():
        if _read_json_object(path) != payload:
            raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _hash_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in {"generated_at_utc", "artifact_hash"}}


def _probe_payload_for_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
    }


def _require_false(audit: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if audit.get(field) is not False:
            raise ValueError(f"membership-v3 source embargo mismatch: {field}")


def _validate_rejected_probe(
    plan_path: Path, probe_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    probe = _read_json_object(probe_path)
    plan = membership_v3.authorize_probe(plan_path, str(probe.get("plan_hash") or ""))
    if probe.get("schema") != membership_v3.PROBE_SCHEMA:
        raise ValueError("unexpected membership-v3 source probe schema")
    if probe.get("plan_hash") != plan.get("plan_hash") or probe.get("run_id") != plan.get("run_id"):
        raise ValueError("membership-v3 source probe provenance mismatch")
    if probe.get("final") is not True or probe.get("accepted") is not False:
        raise ValueError("membership-v3 source probe is not a final reject")
    if probe.get("decision") != membership_v3.REJECTED_PROBE_DECISION:
        raise ValueError("membership-v3 source probe decision is not a source reject")
    if probe.get("next_allowed_command") != "none_membership_v3_archive_source_rejected":
        raise ValueError("membership-v3 source probe permits an unexpected follow-up")
    if probe.get("artifact_hash") != membership_v3.sha256_json(_probe_payload_for_hash(probe)):
        raise ValueError("membership-v3 source probe artifact hash mismatch")

    audit = probe.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("membership-v3 source probe data-access audit is missing")
    _require_false(audit, ("archive_payload_read", "returns_read", "signals_read", "pnl_read", "oos_read"))

    quality = probe.get("quality")
    if not isinstance(quality, Mapping):
        raise ValueError("membership-v3 source probe quality is missing")
    if int(quality.get("errors") or 0) != 0 or float(quality.get("request_error_rate") or 0.0) != 0.0:
        raise ValueError("membership-v3 source reject has transport errors and cannot prove source absence")
    expected_tasks = len(plan.get("probe_tasks") or [])
    if int(quality.get("tasks_expected") or -1) != expected_tasks or int(quality.get("tasks_completed") or -1) != expected_tasks:
        raise ValueError("membership-v3 source probe task completion mismatch")
    cohorts = quality.get("cohorts")
    if not isinstance(cohorts, Mapping):
        raise ValueError("membership-v3 source probe cohorts are missing")
    missing = cohorts.get("missing_end_delisted")
    active = cohorts.get("active_control")
    known = cohorts.get("known_end_delisted_control")
    if not all(isinstance(item, Mapping) for item in (missing, active, known)):
        raise ValueError("membership-v3 source probe cohort detail is incomplete")
    threshold = float(dict(plan.get("quality_gates") or {}).get("minimum_cohort_symbol_availability") or 0.0)
    if active.get("passed") is not True or known.get("passed") is not True:
        raise ValueError("membership-v3 archive controls failed; source absence is not attributable")
    if missing.get("passed") is not False or float(missing.get("symbol_availability") or 0.0) >= threshold:
        raise ValueError("membership-v3 reject is not explained by missing delisted archive availability")
    return plan, probe, dict(quality)


def _closure_result(closure_path: Path, manifest_path: Path) -> dict[str, Any]:
    closure = _read_json_object(closure_path)
    manifest = _read_json_object(manifest_path)
    return {
        "manifest_path": str(manifest_path),
        "closure_path": str(closure_path),
        "closure_artifact_hash": closure["artifact_hash"],
        "manifest_artifact_hash": manifest["artifact_hash"],
        "verdict": closure["verdict"],
        "branch_status": closure["branch_status"],
        "reason_codes": list(closure["reason_codes"]),
        "observed_quality": dict(closure["observed_quality"]),
        "data_access_audit": dict(closure["data_access_audit"]),
        "history_authorized": manifest["history_authorized"],
        "oos_authorized": manifest["oos_authorized"],
        "live_authorized": manifest["live_authorized"],
        "probe_artifact_hash": manifest["probe_artifact_hash"],
        "next_allowed_action": manifest["next_allowed_action"],
    }


def build_archive_source_reject_closure(
    *,
    plan_path: str | Path,
    probe_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"MaxRuntimeSec must be in [1, {MAX_RUNTIME_SEC}]")
    started = time.monotonic()
    resolved_plan = Path(plan_path).expanduser().resolve()
    resolved_probe = Path(probe_path).expanduser().resolve()
    resolved_output = Path(output_dir).expanduser().resolve()
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    closure_path = resolved_output / f"{normalized_run_id}.closure.json"
    manifest_path = resolved_output / f"{normalized_run_id}.closure.manifest.json"
    if closure_path.exists() or manifest_path.exists():
        return validate_archive_source_closure_manifest(manifest_path)

    plan, probe, quality = _validate_rejected_probe(resolved_plan, resolved_probe)
    if time.monotonic() - started > runtime:
        raise TimeoutError("membership-v3 source closure exceeded MaxRuntimeSec")
    closure: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "run_id": normalized_run_id,
        "final": True,
        "branch_status": BRANCH_STATUS,
        "verdict": VERDICT,
        "reason_codes": [REASON_CODE],
        "reason": (
            "The frozen Gate membership-v3 archive metadata source cannot recover the missing "
            "delisted lifecycle-end cohort. No archive payload, history, returns, signals, PnL, "
            "train, or OOS evaluation is authorized."
        ),
        "plan_provenance": {
            "path": str(resolved_plan),
            "file_sha256": membership_v3.sha256_file(resolved_plan),
            "plan_hash": plan["plan_hash"],
        },
        "probe_provenance": {
            "path": str(resolved_probe),
            "file_sha256": membership_v3.sha256_file(resolved_probe),
            "artifact_hash": probe["artifact_hash"],
            "decision": probe["decision"],
            "runtime_sec": probe.get("runtime_sec"),
            "tasks_completed": quality["tasks_completed"],
            "tasks_expected": quality["tasks_expected"],
        },
        "observed_quality": quality,
        "source_diagnosis": {
            "active_control_passed": True,
            "known_end_delisted_control_passed": True,
            "missing_end_delisted_available_symbols": quality["cohorts"]["missing_end_delisted"]["available_symbols"],
            "missing_end_delisted_symbol_availability": quality["cohorts"]["missing_end_delisted"]["symbol_availability"],
            "required_minimum_availability": plan["quality_gates"]["minimum_cohort_symbol_availability"],
            "operational_transport_errors": 0,
        },
        "data_access_audit": {
            "archive_payload_read": False,
            "history_read": False,
            "returns_read": False,
            "signals_read": False,
            "pnl_read": False,
            "train_read": False,
            "oos_read": False,
        },
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "grid_search": False,
            "retune": False,
            "execution_probe": False,
            "paper_forward": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
        "next_allowed_action": NEXT_ALLOWED_ACTION,
        "blocked_actions": [
            "membership_v3_history_plan",
            "membership_v3_history_collect",
            "membership_v3_history_quality",
            "membership_v3_train",
            "membership_v3_oos",
            "membership_v3_retune",
            "grid_search",
            "execution_probe",
            "paper_forward",
            "live_orders",
        ],
    }
    closure["artifact_hash"] = membership_v3.sha256_json(_hash_payload(closure))
    _write_json_immutable(closure_path, closure)

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generated_at_utc": closure["generated_at_utc"],
        "run_id": normalized_run_id,
        "final": True,
        "branch_status": BRANCH_STATUS,
        "verdict": VERDICT,
        "closure_path": str(closure_path),
        "closure_file_sha256": membership_v3.sha256_file(closure_path),
        "closure_artifact_hash": closure["artifact_hash"],
        "plan_hash": plan["plan_hash"],
        "probe_artifact_hash": probe["artifact_hash"],
        "next_allowed_action": NEXT_ALLOWED_ACTION,
        "history_authorized": False,
        "oos_authorized": False,
        "live_authorized": False,
    }
    manifest["artifact_hash"] = membership_v3.sha256_json(_hash_payload(manifest))
    _write_json_immutable(manifest_path, manifest)
    return validate_archive_source_closure_manifest(manifest_path)


def validate_archive_source_closure_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    manifest = _read_json_object(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("final") is not True:
        raise ValueError("unexpected membership-v3 source closure manifest")
    if manifest.get("verdict") != VERDICT or manifest.get("branch_status") != BRANCH_STATUS:
        raise ValueError("membership-v3 source closure manifest verdict mismatch")
    if manifest.get("artifact_hash") != membership_v3.sha256_json(_hash_payload(manifest)):
        raise ValueError("membership-v3 source closure manifest hash mismatch")
    for field in ("history_authorized", "oos_authorized", "live_authorized"):
        if manifest.get(field) is not False:
            raise ValueError(f"membership-v3 source closure safety flag must be false: {field}")
    closure_path = Path(str(manifest.get("closure_path") or "")).expanduser().resolve()
    if membership_v3.sha256_file(closure_path) != manifest.get("closure_file_sha256"):
        raise ValueError("membership-v3 source closure file hash mismatch")
    closure = _read_json_object(closure_path)
    if closure.get("schema") != CLOSURE_SCHEMA or closure.get("final") is not True:
        raise ValueError("unexpected membership-v3 source closure artifact")
    if closure.get("verdict") != VERDICT or closure.get("branch_status") != BRANCH_STATUS:
        raise ValueError("membership-v3 source closure verdict mismatch")
    if closure.get("artifact_hash") != membership_v3.sha256_json(_hash_payload(closure)):
        raise ValueError("membership-v3 source closure artifact hash mismatch")
    if closure.get("artifact_hash") != manifest.get("closure_artifact_hash"):
        raise ValueError("membership-v3 source closure/manifest hash mismatch")
    return _closure_result(closure_path, manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Close a rejected Gate membership-v3 archive source append-only")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--plan", required=True)
    build.add_argument("--probe", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build_archive_source_reject_closure(
            plan_path=args.plan,
            probe_path=args.probe,
            output_dir=args.output_dir,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = validate_archive_source_closure_manifest(args.manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
