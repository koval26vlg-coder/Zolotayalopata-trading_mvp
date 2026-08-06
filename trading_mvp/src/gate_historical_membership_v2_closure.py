from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PLAN_SCHEMA = "trading_mvp_gate_historical_membership_plan_v2"
PROBE_SCHEMA = "trading_mvp_gate_historical_membership_probe_v2"
PROBE_REJECT_DECISION = "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED"
CLOSURE_SCHEMA = "trading_mvp_gate_historical_membership_v2_source_closure_v1"
MANIFEST_SCHEMA = "trading_mvp_gate_historical_membership_v2_source_closure_manifest_v1"
VERDICT = "INSUFFICIENT_SOURCE_QUALITY"
BRANCH_STATUS = "CLOSED_WITHOUT_HISTORY_OR_OOS"
MAX_RUNTIME_SEC = 1_800


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {resolved}")
    return payload


def _write_json_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        existing = _read_json_object(path)
        if existing != dict(payload):
            raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
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


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _probe_payload_for_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
    }


def _closure_payload_for_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "artifact_hash"}
    }


def _manifest_payload_for_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "artifact_hash"}
    }


def _validate_plan(path: Path) -> dict[str, Any]:
    plan = _read_json_object(path)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != PLAN_SCHEMA or not isinstance(frozen, Mapping):
        raise ValueError("unexpected membership-v2 PlanOnly artifact")
    computed = sha256_json(frozen)
    if plan.get("plan_hash") != computed:
        raise ValueError("membership-v2 plan hash mismatch")
    if plan.get("final") is not True:
        raise ValueError("membership-v2 plan is not final")
    return plan


def _validate_probe(path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    probe = _read_json_object(path)
    if probe.get("schema") != PROBE_SCHEMA:
        raise ValueError("unexpected membership-v2 probe schema")
    if probe.get("final") is not True or probe.get("accepted") is not False:
        raise ValueError("membership-v2 probe is not a final source reject")
    if probe.get("decision") != PROBE_REJECT_DECISION:
        raise ValueError("membership-v2 probe decision is not a source reject")
    if probe.get("plan_hash") != plan.get("plan_hash"):
        raise ValueError("membership-v2 probe plan hash mismatch")
    expected_artifact_hash = sha256_json(_probe_payload_for_hash(probe))
    if probe.get("artifact_hash") != expected_artifact_hash:
        raise ValueError("membership-v2 probe artifact hash mismatch")
    audit = probe.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("membership-v2 probe data-access audit is missing")
    for field in ("returns_read", "pnl_read", "signals_read", "oos_read"):
        if audit.get(field) is not False:
            raise ValueError(f"membership-v2 probe embargo mismatch: {field}")
    if not isinstance(probe.get("rows"), list):
        raise ValueError("membership-v2 probe rows are missing")
    return probe


def diagnose_source_rows(rows: list[Any]) -> dict[str, Any]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        by_symbol[symbol].append(row)

    duplicate_symbols: list[str] = []
    exact_duplicate_symbols: list[str] = []
    conflicting_duplicate_symbols: list[str] = []
    unique_rows: list[dict[str, Any]] = []
    for symbol in sorted(by_symbol):
        candidates = by_symbol[symbol]
        unique_rows.append(candidates[0])
        if len(candidates) <= 1:
            continue
        duplicate_symbols.append(symbol)
        candidate_hashes = {sha256_json(candidate) for candidate in candidates}
        if len(candidate_hashes) == 1:
            exact_duplicate_symbols.append(symbol)
        else:
            conflicting_duplicate_symbols.append(symbol)

    delisted = [
        row
        for row in unique_rows
        if row.get("active_at_snapshot") is False
        and str(row.get("lifecycle_status") or "") in {"delisted", "delisting"}
    ]
    delisted_with_end = [row for row in delisted if row.get("listed_to_ts") is not None]
    unique_with_multiplier = [
        row for row in unique_rows if _positive_float(row.get("contract_multiplier")) is not None
    ]
    delisted_with_multiplier = [
        row for row in delisted if _positive_float(row.get("contract_multiplier")) is not None
    ]
    duplicate_rows = sum(len(by_symbol[symbol]) for symbol in duplicate_symbols)
    duplicate_missing_multiplier = sorted(
        symbol
        for symbol in duplicate_symbols
        if all(_positive_float(row.get("contract_multiplier")) is None for row in by_symbol[symbol])
    )
    return {
        "raw_normalized_rows": len(rows),
        "valid_symbol_rows": sum(len(group) for group in by_symbol.values()),
        "unique_symbols": len(unique_rows),
        "duplicate_symbol_count": len(duplicate_symbols),
        "duplicate_rows": duplicate_rows,
        "duplicate_symbols": duplicate_symbols,
        "exact_duplicate_symbol_count": len(exact_duplicate_symbols),
        "exact_duplicate_symbols": exact_duplicate_symbols,
        "conflicting_duplicate_symbol_count": len(conflicting_duplicate_symbols),
        "conflicting_duplicate_symbols": conflicting_duplicate_symbols,
        "duplicate_symbols_with_all_multiplier_values_missing": duplicate_missing_multiplier,
        "unique_delisted_contracts": len(delisted),
        "unique_delisted_with_end": len(delisted_with_end),
        "unique_delisted_end_coverage": len(delisted_with_end) / len(delisted) if delisted else 0.0,
        "unique_delisted_missing_end": len(delisted) - len(delisted_with_end),
        "unique_delisted_missing_end_symbols": sorted(
            str(row.get("symbol") or "") for row in delisted if row.get("listed_to_ts") is None
        ),
        "unique_multiplier_coverage": len(unique_with_multiplier) / len(unique_rows) if unique_rows else 0.0,
        "unique_delisted_multiplier_coverage": (
            len(delisted_with_multiplier) / len(delisted) if delisted else 0.0
        ),
    }


def build_source_reject_closure(
    *,
    plan_path: str | Path,
    probe_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    max_runtime_sec: int = 300,
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
        return validate_closure_manifest(manifest_path)

    plan = _validate_plan(resolved_plan)
    probe = _validate_probe(resolved_probe, plan)
    diagnosis = diagnose_source_rows(list(probe["rows"]))
    quality = probe.get("quality")
    if not isinstance(quality, Mapping):
        raise ValueError("membership-v2 probe quality summary is missing")
    gates = plan.get("quality_gates")
    if not isinstance(gates, Mapping):
        raise ValueError("membership-v2 frozen quality gates are missing")

    required_end_coverage = float(gates.get("minimum_delisted_end_coverage") or 0.0)
    observed_end_coverage = float(quality.get("delisted_end_coverage") or 0.0)
    reasons: list[str] = []
    if observed_end_coverage < required_end_coverage:
        reasons.append("DELISTED_END_COVERAGE_BELOW_FROZEN_GATE")
    if quality.get("duplicate_symbols"):
        reasons.append("DUPLICATE_SYMBOLS_PRESENT")
    if float(quality.get("multiplier_coverage") or 0.0) < float(
        gates.get("minimum_multiplier_coverage") or 0.0
    ):
        reasons.append("MULTIPLIER_COVERAGE_BELOW_FROZEN_GATE")
    if not reasons:
        raise ValueError("source-reject probe does not contain a reproducible quality failure")
    if time.monotonic() - started > runtime:
        raise TimeoutError("membership-v2 closure exceeded MaxRuntimeSec")

    closure: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "run_id": normalized_run_id,
        "final": True,
        "branch_status": BRANCH_STATUS,
        "verdict": VERDICT,
        "reason_codes": reasons,
        "reason": (
            "The frozen Gate membership-v2 public source failed its lifecycle-quality contract. "
            "No history, returns, signals, PnL, train, or OOS evaluation is authorized."
        ),
        "plan_provenance": {
            "path": str(resolved_plan),
            "file_sha256": sha256_file(resolved_plan),
            "plan_hash": plan["plan_hash"],
        },
        "probe_provenance": {
            "path": str(resolved_probe),
            "file_sha256": sha256_file(resolved_probe),
            "artifact_hash": probe["artifact_hash"],
            "decision": probe["decision"],
            "rows": len(probe["rows"]),
            "runtime_sec": probe.get("runtime_sec"),
        },
        "frozen_quality_gates": dict(gates),
        "observed_quality": dict(quality),
        "source_diagnosis": diagnosis,
        "engineering_assessment": {
            "duplicate_normalization_defect_confirmed": (
                diagnosis["exact_duplicate_symbol_count"] > 0
                and diagnosis["conflicting_duplicate_symbol_count"] == 0
            ),
            "duplicate_fix_cannot_repair_lifecycle_end_coverage": True,
            "new_independent_lifecycle_end_source_required": True,
            "frozen_v2_must_not_be_mutated_or_rerun_after_code_change": True,
        },
        "data_access_audit": {
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
        "next_allowed_action": "select_new_materially_distinct_planonly_hypothesis",
        "blocked_actions": [
            "membership_v2_history_collect",
            "membership_v2_train",
            "membership_v2_oos",
            "membership_v2_retune",
            "grid_search",
            "execution_probe",
            "paper_forward",
            "live_orders",
        ],
    }
    closure["artifact_hash"] = sha256_json(_closure_payload_for_hash(closure))
    _write_json_immutable(closure_path, closure)

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generated_at_utc": closure["generated_at_utc"],
        "run_id": normalized_run_id,
        "final": True,
        "branch_status": BRANCH_STATUS,
        "verdict": VERDICT,
        "closure_path": str(closure_path),
        "closure_file_sha256": sha256_file(closure_path),
        "closure_artifact_hash": closure["artifact_hash"],
        "plan_hash": plan["plan_hash"],
        "probe_artifact_hash": probe["artifact_hash"],
        "next_allowed_action": closure["next_allowed_action"],
        "history_authorized": False,
        "oos_authorized": False,
        "live_authorized": False,
    }
    manifest["artifact_hash"] = sha256_json(_manifest_payload_for_hash(manifest))
    _write_json_immutable(manifest_path, manifest)
    return validate_closure_manifest(manifest_path)


def validate_closure_manifest(path: str | Path) -> dict[str, Any]:
    resolved_manifest = Path(path).expanduser().resolve()
    manifest = _read_json_object(resolved_manifest)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("final") is not True:
        raise ValueError("unexpected membership-v2 closure manifest")
    if manifest.get("verdict") != VERDICT or manifest.get("branch_status") != BRANCH_STATUS:
        raise ValueError("membership-v2 closure manifest verdict mismatch")
    if sha256_json(_manifest_payload_for_hash(manifest)) != manifest.get("artifact_hash"):
        raise ValueError("membership-v2 closure manifest artifact hash mismatch")
    closure_path = Path(str(manifest.get("closure_path") or "")).expanduser().resolve()
    if sha256_file(closure_path) != manifest.get("closure_file_sha256"):
        raise ValueError("membership-v2 closure file hash mismatch")
    closure = _read_json_object(closure_path)
    if closure.get("schema") != CLOSURE_SCHEMA or closure.get("final") is not True:
        raise ValueError("unexpected membership-v2 closure artifact")
    if closure.get("verdict") != VERDICT or closure.get("branch_status") != BRANCH_STATUS:
        raise ValueError("membership-v2 closure verdict mismatch")
    if sha256_json(_closure_payload_for_hash(closure)) != closure.get("artifact_hash"):
        raise ValueError("membership-v2 closure artifact hash mismatch")
    if closure.get("artifact_hash") != manifest.get("closure_artifact_hash"):
        raise ValueError("membership-v2 closure/manifest hash mismatch")
    for field in ("history_authorized", "oos_authorized", "live_authorized"):
        if manifest.get(field) is not False:
            raise ValueError(f"membership-v2 closure safety flag must be false: {field}")
    return {
        "manifest_path": str(resolved_manifest),
        "manifest_file_sha256": sha256_file(resolved_manifest),
        "manifest_artifact_hash": manifest["artifact_hash"],
        "closure_path": str(closure_path),
        "closure_file_sha256": manifest["closure_file_sha256"],
        "closure_artifact_hash": closure["artifact_hash"],
        "verdict": VERDICT,
        "branch_status": BRANCH_STATUS,
        "reason_codes": list(closure.get("reason_codes") or []),
        "next_allowed_action": closure["next_allowed_action"],
        "source_diagnosis": dict(closure.get("source_diagnosis") or {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Close a rejected Gate membership-v2 source append-only")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--plan", required=True)
    build.add_argument("--probe", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--max-runtime-sec", type=int, default=300)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build_source_reject_closure(
            plan_path=args.plan,
            probe_path=args.probe,
            output_dir=args.output_dir,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = validate_closure_manifest(args.manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
