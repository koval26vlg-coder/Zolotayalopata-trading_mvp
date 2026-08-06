from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from historical_basis_code_snapshot import require_plan_runtime_code_snapshot
    from historical_basis_v2 import sha256_file, sha256_json, validate_historical_basis_v2_plan
    from historical_basis_v2_evaluator import (
        SCHEMA as EVALUATION_SCHEMA,
        _artifact_hash,
        run_hash_bound_evaluation,
        validate_full_evaluation_result,
    )
    from historical_basis_v2_postprocess import SCHEMA as TRAIN_POSTPROCESS_SCHEMA
    from historical_basis_v2_report import build_terminal_report
except ImportError:  # pragma: no cover - package import fallback
    from .historical_basis_code_snapshot import require_plan_runtime_code_snapshot
    from .historical_basis_v2 import sha256_file, sha256_json, validate_historical_basis_v2_plan
    from .historical_basis_v2_evaluator import (
        SCHEMA as EVALUATION_SCHEMA,
        _artifact_hash,
        run_hash_bound_evaluation,
        validate_full_evaluation_result,
    )
    from .historical_basis_v2_postprocess import SCHEMA as TRAIN_POSTPROCESS_SCHEMA
    from .historical_basis_v2_report import build_terminal_report


SCHEMA = "trading_mvp_historical_basis_v2_oos_postprocess_v1"
FAILURE_SCHEMA = "trading_mvp_historical_basis_v2_oos_postprocess_failure_v1"
MAX_RUNTIME_SEC = 1_800
TERMINAL_VERDICTS = {"ACCEPT_FOR_EXECUTION_PROBE", "INSUFFICIENT_DATA", "REJECT"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_runtime(value: int) -> int:
    runtime = int(value)
    if not 0 < runtime <= MAX_RUNTIME_SEC:
        raise ValueError("OOS postprocess max_runtime_sec must be in [1, 1800]")
    return runtime


def _remaining_runtime(started: float, maximum: int) -> int:
    remaining = int(math.floor(maximum - (time.monotonic() - started)))
    if remaining <= 0:
        raise TimeoutError("OOS postprocess MaxRuntimeSec exceeded")
    return remaining


def _oos_paths(output_root: str | Path, collector_run_id: str) -> dict[str, Path]:
    run_root = Path(output_root).expanduser().resolve() / collector_run_id
    return {
        "run_root": run_root,
        "evaluation_repeat_1": run_root / "full-evaluation-repeat-1.json",
        "evaluation_repeat_2": run_root / "full-evaluation-repeat-2.json",
        "terminal_report": run_root / "terminal-report.json",
        "manifest": run_root / "oos-postprocess-manifest.json",
        "failure": run_root / "oos-postprocess-failure.json",
    }


def _train_manifest_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"deterministic_result_hash", "generated_at_utc", "runtime_sec", "manifest_path"}
        }
    )


def _validate_train_feasibility(
    payload: Mapping[str, Any],
    *,
    path: Path,
    expected_file_sha256: str,
    plan_hash: str,
    quality_sha256: str,
    deterministic_hash: str,
    oos_seal: Any,
) -> None:
    if sha256_file(path) != expected_file_sha256:
        raise ValueError("feasibility repeat file hash mismatch")
    if payload.get("schema") != EVALUATION_SCHEMA or payload.get("stage") != "train_feasibility":
        raise ValueError("unexpected train feasibility artifact")
    if payload.get("verdict") != "FEASIBLE_FOR_OOS":
        raise ValueError("train feasibility artifact is not FEASIBLE_FOR_OOS")
    if payload.get("plan_hash") != plan_hash:
        raise ValueError("train feasibility plan hash mismatch")
    if payload.get("quality_report_sha256") != quality_sha256:
        raise ValueError("train feasibility quality hash mismatch")
    if payload.get("deterministic_result_hash") != deterministic_hash:
        raise ValueError("train feasibility deterministic hash mismatch")
    if payload.get("deterministic_result_hash") != _artifact_hash(payload):
        raise ValueError("train feasibility artifact hash is invalid")
    if payload.get("oos_seal") != oos_seal:
        raise ValueError("train feasibility OOS seal mismatch")
    if payload.get("oos_read") is not False:
        raise ValueError("train feasibility artifact violates OOS embargo")
    audit = payload.get("data_access_audit") or {}
    if audit.get("oos_files_opened") is not False or int(audit.get("oos_rows_read") or 0) != 0:
        raise ValueError("train feasibility artifact violates OOS access audit")
    if audit.get("network_access") not in {None, False}:
        raise ValueError("train feasibility artifact reports network access")


def _validate_train_postprocess_manifest(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    plan_path: Path,
    plan_hash: str,
    plan_file_sha256: str,
) -> dict[str, Any]:
    if manifest.get("schema") != TRAIN_POSTPROCESS_SCHEMA:
        raise ValueError("unexpected train postprocess manifest schema")
    if manifest.get("status") != "READY_FOR_OOS_EVALUATION_NOT_RUN" or manifest.get("final") is not True:
        raise ValueError("train postprocess manifest is not READY_FOR_OOS_EVALUATION_NOT_RUN")
    if manifest.get("verdict") != "FEASIBLE_FOR_OOS":
        raise ValueError("train postprocess manifest is not FEASIBLE_FOR_OOS")
    if manifest.get("plan_hash") != plan_hash:
        raise ValueError("train postprocess plan hash mismatch")
    if manifest.get("plan_file_sha256") != plan_file_sha256:
        raise ValueError("train postprocess plan file hash mismatch")
    recorded_plan = Path(str(manifest.get("plan_path") or "")).expanduser().resolve()
    if recorded_plan != plan_path:
        raise ValueError("train postprocess plan path mismatch")
    if manifest.get("oos_read") is not False or manifest.get("full_evaluation") is not False:
        raise ValueError("train postprocess manifest violates OOS embargo")
    for key in ("network_access", "grid_search", "retune", "live_orders", "private_api_keys", "leverage_or_margin"):
        if manifest.get(key) is not False:
            raise ValueError(f"train postprocess safety flag must be false: {key}")
    if manifest.get("deterministic_result_hash") != _train_manifest_hash(manifest):
        raise ValueError("train postprocess deterministic result hash mismatch")

    collector_run_id = str(manifest.get("collector_run_id") or "").strip()
    if not collector_run_id:
        raise ValueError("train postprocess collector_run_id is missing")
    quality_path = Path(str(manifest.get("quality_report_path") or "")).expanduser().resolve()
    quality_sha256 = str(manifest.get("quality_report_sha256") or "")
    if not quality_path.is_file() or sha256_file(quality_path) != quality_sha256:
        raise ValueError("train postprocess quality report hash mismatch")

    raw_paths = manifest.get("feasibility_repeat_paths")
    raw_hashes = manifest.get("feasibility_repeat_file_sha256")
    if not isinstance(raw_paths, list) or len(raw_paths) != 2:
        raise ValueError("train postprocess must contain exactly two feasibility paths")
    if not isinstance(raw_hashes, list) or len(raw_hashes) != 2:
        raise ValueError("train postprocess must contain exactly two feasibility file hashes")
    deterministic_hash = str(manifest.get("feasibility_deterministic_result_hash") or "")
    if not deterministic_hash:
        raise ValueError("train postprocess feasibility deterministic hash is missing")
    oos_seal = manifest.get("oos_seal")
    feasibility_paths: list[Path] = []
    for raw_path, expected_hash in zip(raw_paths, raw_hashes, strict=True):
        target = Path(str(raw_path)).expanduser().resolve()
        if not target.is_file():
            raise ValueError("train feasibility artifact is missing")
        payload = _read_json(target)
        _validate_train_feasibility(
            payload,
            path=target,
            expected_file_sha256=str(expected_hash),
            plan_hash=plan_hash,
            quality_sha256=quality_sha256,
            deterministic_hash=deterministic_hash,
            oos_seal=oos_seal,
        )
        feasibility_paths.append(target)

    return {
        "collector_run_id": collector_run_id,
        "quality_report_path": quality_path,
        "quality_report_sha256": quality_sha256,
        "feasibility_paths": feasibility_paths,
        "feasibility_file_sha256": [str(value) for value in raw_hashes],
        "feasibility_deterministic_result_hash": deterministic_hash,
        "oos_seal": oos_seal,
        "manifest_path": manifest_path,
        "manifest_file_sha256": sha256_file(manifest_path),
        "manifest_deterministic_result_hash": str(manifest["deterministic_result_hash"]),
    }


def build_oos_postprocess_preview(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    train_postprocess_manifest_path: str | Path,
    output_root: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = _validate_runtime(max_runtime_sec)
    plan_target = Path(plan_path).expanduser().resolve()
    validation = validate_historical_basis_v2_plan(plan_target, expected_plan_hash)
    require_plan_runtime_code_snapshot(_read_json(plan_target), runtime_code_path=__file__)
    plan_hash = str(validation["plan_hash"])
    train_manifest_target = Path(train_postprocess_manifest_path).expanduser().resolve()
    manifest = _read_json(train_manifest_target)
    upstream = _validate_train_postprocess_manifest(
        manifest,
        manifest_path=train_manifest_target,
        plan_path=plan_target,
        plan_hash=plan_hash,
        plan_file_sha256=str(validation["plan_file_sha256"]),
    )
    paths = _oos_paths(output_root, str(upstream["collector_run_id"]))
    conflicts = sorted(str(path) for name, path in paths.items() if name != "run_root" and path.exists())
    return {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "decision": "READY_FOR_VISIBLE_OOS_POSTPROCESS" if not conflicts else "OOS_POSTPROCESS_OUTPUT_CONFLICT",
        "plan_path": str(plan_target),
        "plan_file_sha256": str(validation["plan_file_sha256"]),
        "plan_hash": plan_hash,
        "train_postprocess_manifest_path": str(train_manifest_target),
        "train_postprocess_manifest_sha256": upstream["manifest_file_sha256"],
        "train_postprocess_deterministic_result_hash": upstream["manifest_deterministic_result_hash"],
        "collector_run_id": upstream["collector_run_id"],
        "quality_report_path": str(upstream["quality_report_path"]),
        "quality_report_sha256": upstream["quality_report_sha256"],
        "feasibility_repeat_paths": [str(path) for path in upstream["feasibility_paths"]],
        "feasibility_repeat_file_sha256": upstream["feasibility_file_sha256"],
        "selected_feasibility_path": str(upstream["feasibility_paths"][0]),
        "feasibility_deterministic_result_hash": upstream["feasibility_deterministic_result_hash"],
        "oos_seal": upstream["oos_seal"],
        "output_root": str(Path(output_root).expanduser().resolve()),
        "run_root": str(paths["run_root"]),
        "paths": {name: str(path) for name, path in paths.items() if name != "run_root"},
        "conflicting_outputs": conflicts,
        "max_runtime_sec": runtime,
        "stages": ["full_evaluation_repeat_1", "full_evaluation_repeat_2", "terminal_report"],
        "network_access": False,
        "oos_read": False,
        "full_evaluation": False,
        "grid_search": False,
        "retune": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
    }


def _assert_full_result(result: Mapping[str, Any], *, plan_hash: str, label: str) -> None:
    validate_full_evaluation_result(result)
    if result.get("schema") != EVALUATION_SCHEMA or result.get("stage") != "full_evaluation":
        raise ValueError(f"{label} is not a full_evaluation artifact")
    if result.get("plan_hash") != plan_hash:
        raise ValueError(f"{label} plan hash mismatch")
    if result.get("verdict") not in TERMINAL_VERDICTS:
        raise ValueError(f"{label} has unsupported verdict")
    if result.get("oos_read") is not True:
        raise ValueError(f"{label} did not read OOS")
    audit = result.get("data_access_audit") or {}
    if audit.get("oos_files_opened") is not True or audit.get("oos_returns_read") is not True:
        raise ValueError(f"{label} has an invalid OOS access audit")
    if audit.get("network_access") not in {None, False}:
        raise ValueError(f"{label} reports network access")
    if audit.get("grid_search") not in {None, False} or audit.get("retune") not in {None, False}:
        raise ValueError(f"{label} violates no-grid/no-retune")
    if result.get("deterministic_result_hash") != _artifact_hash(result):
        raise ValueError(f"{label} deterministic result hash mismatch")


def _failure_payload(
    *,
    plan_hash: str,
    collector_run_id: str,
    error: Exception,
    oos_read: bool,
) -> dict[str, Any]:
    return {
        "schema": FAILURE_SCHEMA,
        "status": "STOPPED_INCOMPLETE",
        "final": False,
        "generated_at_utc": _utc_now(),
        "plan_hash": plan_hash,
        "collector_run_id": collector_run_id,
        "error_type": type(error).__name__,
        "error": str(error),
        "network_access": False,
        "oos_read": oos_read,
        "full_evaluation": oos_read,
        "partial_accept": False,
        "next_allowed_command": "inspect-oos-postprocess-failure-before-new-run-id",
    }


def _terminal_status(verdict: str) -> tuple[str, str]:
    if verdict == "ACCEPT_FOR_EXECUTION_PROBE":
        return "HISTORICAL_ACCEPT_FOR_EXECUTION_PROBE", "create-separate-visible-execution-probe-planonly"
    if verdict == "INSUFFICIENT_DATA":
        return "BRANCH_CLOSED_INSUFFICIENT_DATA", "close-hypothesis-without-retune"
    return "BRANCH_CLOSED_HISTORICAL_REJECTED", "close-hypothesis-without-retune"


def run_oos_postprocess(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    train_postprocess_manifest_path: str | Path,
    output_root: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    preview = build_oos_postprocess_preview(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        train_postprocess_manifest_path=train_postprocess_manifest_path,
        output_root=output_root,
        max_runtime_sec=max_runtime_sec,
    )
    if preview["decision"] != "READY_FOR_VISIBLE_OOS_POSTPROCESS":
        raise FileExistsError("OOS postprocess outputs already exist: " + ", ".join(preview["conflicting_outputs"]))
    runtime = int(preview["max_runtime_sec"])
    started = time.monotonic()
    paths = {name: Path(value) for name, value in dict(preview["paths"]).items()}
    run_root = Path(str(preview["run_root"]))
    run_root.mkdir(parents=True, exist_ok=True)
    oos_read_started = False

    try:
        evaluations: list[dict[str, Any]] = []
        for output in (paths["evaluation_repeat_1"], paths["evaluation_repeat_2"]):
            oos_read_started = True
            evaluation = run_hash_bound_evaluation(
                plan_path=preview["plan_path"],
                quality_report_path=preview["quality_report_path"],
                output_path=output,
                stage="full_evaluation",
                expected_plan_hash=str(preview["plan_hash"]),
                feasibility_path=preview["selected_feasibility_path"],
                max_runtime_sec=_remaining_runtime(started, runtime),
            )
            _assert_full_result(evaluation, plan_hash=str(preview["plan_hash"]), label=output.name)
            if not output.is_file() or sha256_file(output) == "":
                raise ValueError(f"{output.name} was not written")
            evaluations.append(evaluation)

        first, second = evaluations
        if first["deterministic_result_hash"] != second["deterministic_result_hash"]:
            raise ValueError("deterministic OOS repeat mismatch")
        if first.get("verdict") != second.get("verdict"):
            raise ValueError("OOS repeat verdict mismatch")

        terminal_report = build_terminal_report(paths["evaluation_repeat_1"], paths["terminal_report"])
        if terminal_report.get("evaluation_result_hash") != first["deterministic_result_hash"]:
            raise ValueError("terminal report evaluation hash mismatch")
        verdict = str(first["verdict"])
        status, next_command = _terminal_status(verdict)
        deterministic_core = {
            "schema": SCHEMA,
            "plan_hash": preview["plan_hash"],
            "train_postprocess_deterministic_result_hash": preview[
                "train_postprocess_deterministic_result_hash"
            ],
            "feasibility_deterministic_result_hash": preview["feasibility_deterministic_result_hash"],
            "oos_deterministic_result_hash": first["deterministic_result_hash"],
            "terminal_report_deterministic_result_hash": terminal_report["deterministic_result_hash"],
            "status": status,
            "verdict": verdict,
            "rejection_reasons": list(first.get("rejection_reasons") or []),
            "next_allowed_command": next_command,
        }
        result = {
            "schema": SCHEMA,
            "status": status,
            "final": True,
            "generated_at_utc": _utc_now(),
            "plan_path": preview["plan_path"],
            "plan_file_sha256": preview["plan_file_sha256"],
            "plan_hash": preview["plan_hash"],
            "collector_run_id": preview["collector_run_id"],
            "train_postprocess_manifest_path": preview["train_postprocess_manifest_path"],
            "train_postprocess_manifest_sha256": preview["train_postprocess_manifest_sha256"],
            "train_postprocess_deterministic_result_hash": preview[
                "train_postprocess_deterministic_result_hash"
            ],
            "quality_report_path": preview["quality_report_path"],
            "quality_report_sha256": preview["quality_report_sha256"],
            "selected_feasibility_path": preview["selected_feasibility_path"],
            "feasibility_repeat_paths": preview["feasibility_repeat_paths"],
            "feasibility_repeat_file_sha256": preview["feasibility_repeat_file_sha256"],
            "feasibility_deterministic_result_hash": preview["feasibility_deterministic_result_hash"],
            "evaluation_repeat_paths": [
                str(paths["evaluation_repeat_1"]),
                str(paths["evaluation_repeat_2"]),
            ],
            "evaluation_repeat_file_sha256": [
                sha256_file(paths["evaluation_repeat_1"]),
                sha256_file(paths["evaluation_repeat_2"]),
            ],
            "oos_deterministic_result_hash": first["deterministic_result_hash"],
            "terminal_report_path": str(paths["terminal_report"]),
            "terminal_report_file_sha256": sha256_file(paths["terminal_report"]),
            "terminal_report_deterministic_result_hash": terminal_report["deterministic_result_hash"],
            "verdict": verdict,
            "rejection_reasons": list(first.get("rejection_reasons") or []),
            "oos_read": True,
            "full_evaluation": True,
            "network_access": False,
            "grid_search": False,
            "retune": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "runtime_sec": round(time.monotonic() - started, 6),
            "max_runtime_sec": runtime,
            "next_allowed_command": next_command,
            "deterministic_result_hash": sha256_json(deterministic_core),
        }
        _write_json_immutable(paths["manifest"], result)
        result["manifest_path"] = str(paths["manifest"])
        return result
    except Exception as exc:
        failure = _failure_payload(
            plan_hash=str(preview["plan_hash"]),
            collector_run_id=str(preview["collector_run_id"]),
            error=exc,
            oos_read=oos_read_started,
        )
        if not paths["failure"].exists():
            _write_json_immutable(paths["failure"], failure)
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Historical basis v2 deterministic OOS postprocess")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--train-postprocess-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    parser.add_argument("--plan-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    kwargs = {
        "plan_path": args.plan,
        "expected_plan_hash": args.expected_plan_hash,
        "train_postprocess_manifest_path": args.train_postprocess_manifest,
        "output_root": args.output_root,
        "max_runtime_sec": args.max_runtime_sec,
    }
    result = build_oos_postprocess_preview(**kwargs) if args.plan_only else run_oos_postprocess(**kwargs)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
