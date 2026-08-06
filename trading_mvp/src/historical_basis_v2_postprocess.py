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
    from historical_basis_v2_collector import SCHEMA as COLLECTOR_SCHEMA
    from historical_basis_v2_evaluator import run_hash_bound_evaluation
    from historical_basis_v2_quality import run_historical_basis_v2_quality
except ImportError:  # pragma: no cover - package import fallback
    from .historical_basis_code_snapshot import require_plan_runtime_code_snapshot
    from .historical_basis_v2 import sha256_file, sha256_json, validate_historical_basis_v2_plan
    from .historical_basis_v2_collector import SCHEMA as COLLECTOR_SCHEMA
    from .historical_basis_v2_evaluator import run_hash_bound_evaluation
    from .historical_basis_v2_quality import run_historical_basis_v2_quality


SCHEMA = "trading_mvp_historical_basis_v2_train_postprocess_v1"
FAILURE_SCHEMA = "trading_mvp_historical_basis_v2_train_postprocess_failure_v1"
MAX_RUNTIME_SEC = 1_800


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
        raise ValueError("postprocess max_runtime_sec must be in [1, 1800]")
    return runtime


def _remaining_runtime(started: float, maximum: int) -> int:
    remaining = int(math.floor(maximum - (time.monotonic() - started)))
    if remaining <= 0:
        raise TimeoutError("train postprocess MaxRuntimeSec exceeded")
    return remaining


def _postprocess_paths(output_root: str | Path, run_id: str) -> dict[str, Path]:
    run_root = Path(output_root).expanduser().resolve() / run_id
    candles = run_root / "normalized-candles.jsonl"
    return {
        "run_root": run_root,
        "candles": candles,
        "funding": run_root / "funding-events.jsonl",
        "train": candles.with_name(f"{candles.stem}.train{candles.suffix}"),
        "oos": candles.with_name(f"{candles.stem}.oos{candles.suffix}"),
        "quality": run_root / "quality-report.json",
        "feasibility_repeat_1": run_root / "train-feasibility-repeat-1.json",
        "feasibility_repeat_2": run_root / "train-feasibility-repeat-2.json",
        "manifest": run_root / "postprocess-manifest.json",
        "failure": run_root / "postprocess-failure.json",
    }


def _validate_collector_manifest(
    manifest: Mapping[str, Any],
    *,
    plan_hash: str,
) -> str:
    if manifest.get("schema") != COLLECTOR_SCHEMA:
        raise ValueError("unexpected collector manifest schema")
    if manifest.get("status") != "READY_FOR_POSTPROCESS" or manifest.get("final") is not True:
        raise ValueError("collector manifest is not final READY_FOR_POSTPROCESS")
    if manifest.get("plan_hash") != plan_hash or manifest.get("expected_plan_hash") != plan_hash:
        raise ValueError("collector manifest plan hash mismatch")
    expected = int(manifest.get("expected_items") or 0)
    completed = int(manifest.get("completed_items") or 0)
    if expected <= 0 or completed != expected:
        raise ValueError("collector manifest item completion mismatch")
    if int(manifest.get("error_count") or 0) != 0:
        raise ValueError("collector manifest contains errors")
    run_id = str(manifest.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("collector manifest run_id is missing")
    return run_id


def build_train_postprocess_preview(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    collector_manifest_path: str | Path,
    output_root: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = _validate_runtime(max_runtime_sec)
    plan_target = Path(plan_path).expanduser().resolve()
    validation = validate_historical_basis_v2_plan(plan_target, expected_plan_hash)
    require_plan_runtime_code_snapshot(_read_json(plan_target), runtime_code_path=__file__)
    plan_hash = str(validation["plan_hash"])
    manifest_target = Path(collector_manifest_path).expanduser().resolve()
    manifest = _read_json(manifest_target)
    run_id = _validate_collector_manifest(manifest, plan_hash=plan_hash)
    paths = _postprocess_paths(output_root, run_id)
    conflicts = sorted(str(path) for name, path in paths.items() if name != "run_root" and path.exists())
    return {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "decision": "READY_FOR_VISIBLE_TRAIN_POSTPROCESS" if not conflicts else "POSTPROCESS_OUTPUT_CONFLICT",
        "plan_path": str(plan_target),
        "plan_file_sha256": str(validation["plan_file_sha256"]),
        "plan_hash": plan_hash,
        "collector_manifest_path": str(manifest_target),
        "collector_manifest_sha256": sha256_file(manifest_target),
        "collector_run_id": run_id,
        "output_root": str(Path(output_root).expanduser().resolve()),
        "run_root": str(paths["run_root"]),
        "paths": {name: str(path) for name, path in paths.items() if name != "run_root"},
        "conflicting_outputs": conflicts,
        "max_runtime_sec": runtime,
        "stages": ["quality", "train_feasibility_repeat_1", "train_feasibility_repeat_2"],
        "network_access": False,
        "oos_read": False,
        "full_evaluation": False,
        "grid_search": False,
        "retune": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
    }


def _assert_train_only_result(result: Mapping[str, Any], *, label: str) -> None:
    if result.get("stage") != "train_feasibility":
        raise ValueError(f"{label} is not train_feasibility")
    if result.get("oos_read") is not False:
        raise ValueError(f"{label} violates OOS embargo")
    audit = result.get("data_access_audit") or {}
    if audit.get("oos_files_opened") is not False or int(audit.get("oos_rows_read") or 0) != 0:
        raise ValueError(f"{label} violates OOS access audit")
    if not str(result.get("deterministic_result_hash") or ""):
        raise ValueError(f"{label} deterministic hash is missing")


def _failure_payload(
    *,
    plan_hash: str,
    collector_run_id: str,
    error: Exception,
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
        "oos_read": False,
        "full_evaluation": False,
        "next_allowed_command": "inspect-postprocess-failure-before-resume-or-new-run-id",
    }


def run_train_postprocess(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    collector_manifest_path: str | Path,
    output_root: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    preview = build_train_postprocess_preview(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        collector_manifest_path=collector_manifest_path,
        output_root=output_root,
        max_runtime_sec=max_runtime_sec,
    )
    if preview["decision"] != "READY_FOR_VISIBLE_TRAIN_POSTPROCESS":
        raise FileExistsError("postprocess outputs already exist: " + ", ".join(preview["conflicting_outputs"]))
    runtime = int(preview["max_runtime_sec"])
    started = time.monotonic()
    plan_target = Path(str(preview["plan_path"]))
    manifest_target = Path(str(preview["collector_manifest_path"]))
    plan = _read_json(plan_target)
    manifest = _read_json(manifest_target)
    paths = {name: Path(value) for name, value in dict(preview["paths"]).items()}
    run_root = Path(str(preview["run_root"]))
    run_root.mkdir(parents=True, exist_ok=True)

    try:
        quality = run_historical_basis_v2_quality(
            plan,
            manifest,
            plan_path=plan_target,
            expected_plan_hash=str(preview["plan_hash"]),
            manifest_path=manifest_target,
            candles_output=paths["candles"],
            funding_output=paths["funding"],
            report_output=paths["quality"],
            max_runtime_sec=_remaining_runtime(started, runtime),
        )
        quality_verdict = str(quality.get("verdict") or "")
        if quality_verdict != "QUALITY_ACCEPTED_NOT_EVALUATED":
            result = {
                "schema": SCHEMA,
                "status": "BRANCH_CLOSED_QUALITY_REJECTED",
                "final": True,
                "generated_at_utc": _utc_now(),
                "plan_hash": preview["plan_hash"],
                "collector_run_id": preview["collector_run_id"],
                "quality_verdict": quality_verdict,
                "verdict": quality_verdict,
                "oos_read": False,
                "full_evaluation": False,
                "network_access": False,
                "grid_search": False,
                "retune": False,
                "next_allowed_command": "close-hypothesis-without-retune",
                "runtime_sec": round(time.monotonic() - started, 6),
            }
            result["deterministic_result_hash"] = sha256_json(
                {key: value for key, value in result.items() if key not in {"generated_at_utc", "runtime_sec"}}
            )
            _write_json_immutable(paths["manifest"], result)
            result["manifest_path"] = str(paths["manifest"])
            return result

        evaluations: list[dict[str, Any]] = []
        for output in (paths["feasibility_repeat_1"], paths["feasibility_repeat_2"]):
            evaluation = run_hash_bound_evaluation(
                plan_path=plan_target,
                quality_report_path=paths["quality"],
                output_path=output,
                stage="train_feasibility",
                expected_plan_hash=str(preview["plan_hash"]),
                feasibility_path=None,
                max_runtime_sec=_remaining_runtime(started, runtime),
            )
            _assert_train_only_result(evaluation, label=output.name)
            evaluations.append(evaluation)

        first, second = evaluations
        if first["deterministic_result_hash"] != second["deterministic_result_hash"]:
            raise ValueError("deterministic train repeat mismatch")
        if first.get("verdict") != second.get("verdict"):
            raise ValueError("train repeat verdict mismatch")

        feasible = first.get("verdict") == "FEASIBLE_FOR_OOS"
        status = "READY_FOR_OOS_EVALUATION_NOT_RUN" if feasible else "BRANCH_CLOSED_TRAIN_INFEASIBLE"
        next_command = (
            "visible-hash-bound-full-evaluation-no-grid"
            if feasible
            else "close-hypothesis-without-retune"
        )
        result = {
            "schema": SCHEMA,
            "status": status,
            "final": True,
            "generated_at_utc": _utc_now(),
            "plan_path": str(plan_target),
            "plan_file_sha256": preview["plan_file_sha256"],
            "plan_hash": preview["plan_hash"],
            "collector_manifest_path": str(manifest_target),
            "collector_manifest_sha256": preview["collector_manifest_sha256"],
            "collector_run_id": preview["collector_run_id"],
            "quality_report_path": str(paths["quality"]),
            "quality_report_sha256": sha256_file(paths["quality"]),
            "quality_verdict": quality_verdict,
            "feasibility_repeat_paths": [
                str(paths["feasibility_repeat_1"]),
                str(paths["feasibility_repeat_2"]),
            ],
            "feasibility_repeat_file_sha256": [
                sha256_file(paths["feasibility_repeat_1"]),
                sha256_file(paths["feasibility_repeat_2"]),
            ],
            "feasibility_deterministic_result_hash": first["deterministic_result_hash"],
            "verdict": first.get("verdict"),
            "rejection_reasons": list(first.get("rejection_reasons") or []),
            "oos_seal": first.get("oos_seal"),
            "oos_read": False,
            "full_evaluation": False,
            "network_access": False,
            "grid_search": False,
            "retune": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "runtime_sec": round(time.monotonic() - started, 6),
            "max_runtime_sec": runtime,
            "next_allowed_command": next_command,
        }
        result["deterministic_result_hash"] = sha256_json(
            {key: value for key, value in result.items() if key not in {"generated_at_utc", "runtime_sec"}}
        )
        _write_json_immutable(paths["manifest"], result)
        result["manifest_path"] = str(paths["manifest"])
        return result
    except Exception as exc:
        failure = _failure_payload(
            plan_hash=str(preview["plan_hash"]),
            collector_run_id=str(preview["collector_run_id"]),
            error=exc,
        )
        if not paths["failure"].exists():
            _write_json_immutable(paths["failure"], failure)
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Historical basis v2 train-only postprocess")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--collector-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    parser.add_argument("--plan-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    kwargs = {
        "plan_path": args.plan,
        "expected_plan_hash": args.expected_plan_hash,
        "collector_manifest_path": args.collector_manifest,
        "output_root": args.output_root,
        "max_runtime_sec": args.max_runtime_sec,
    }
    result = build_train_postprocess_preview(**kwargs) if args.plan_only else run_train_postprocess(**kwargs)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
