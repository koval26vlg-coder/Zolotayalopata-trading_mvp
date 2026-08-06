from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from costs import validate_runtime_sec
from historical_basis_code_snapshot import require_plan_code_snapshot, validate_basis_code_snapshot_reference
from historical_basis_edge import (
    BasisBar,
    evaluate_historical_basis,
    sha256_file,
    sha256_json,
    validate_historical_basis_plan,
)


SCHEMA = "trading_mvp_historical_basis_owned_evaluation_v1"
QUALITY_SCHEMA = "trading_mvp_historical_basis_quality_v1"


def _semantic_hash(payload: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"deterministic_result_hash", "generated_at_utc", "runtime_sec"}
        }
    )


def _sha256_bytes(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _load_bars(path: Path) -> list[BasisBar]:
    rows: list[BasisBar] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(BasisBar.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid normalized row {path}:{line_number}: {exc}") from exc
    return rows


def _validate_quality(
    quality: dict[str, Any],
    *,
    quality_path: Path,
    plan_hash: str,
) -> None:
    if quality.get("schema") != QUALITY_SCHEMA:
        raise ValueError("unexpected quality report schema")
    if quality.get("verdict") != "QUALITY_ACCEPTED_NOT_EVALUATED":
        raise ValueError("quality report did not accept the dataset")
    if quality.get("plan_hash") != plan_hash:
        raise ValueError("quality report plan hash mismatch")
    if quality.get("deterministic_result_hash") != _semantic_hash(quality):
        raise ValueError("quality deterministic result hash mismatch")
    if not quality_path.exists() or quality_path.stat().st_size == 0:
        raise ValueError("quality report is missing or empty")


def _validate_feasibility(
    feasibility: dict[str, Any],
    *,
    plan_hash: str,
    quality_sha256: str,
) -> None:
    if feasibility.get("schema") != SCHEMA or feasibility.get("stage") != "train_feasibility":
        raise ValueError("unexpected feasibility artifact")
    if feasibility.get("plan_hash") != plan_hash:
        raise ValueError("feasibility plan hash mismatch")
    if feasibility.get("quality_report_sha256") != quality_sha256:
        raise ValueError("feasibility quality provenance mismatch")
    if feasibility.get("deterministic_result_hash") != _semantic_hash(feasibility):
        raise ValueError("feasibility deterministic result hash mismatch")
    if feasibility.get("verdict") != "FEASIBLE_FOR_OOS":
        raise ValueError("feasibility artifact is not FEASIBLE_FOR_OOS")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def run_hash_bound_evaluation(
    *,
    plan_path: str | Path,
    quality_report_path: str | Path,
    output_path: str | Path,
    stage: str,
    expected_plan_hash: str | None = None,
    feasibility_path: str | Path | None = None,
    max_runtime_sec: int = 1800,
    parallel_parent_run_id: str | None = None,
) -> dict[str, Any]:
    if stage not in {"train_feasibility", "full_evaluation"}:
        raise ValueError("stage must be train_feasibility or full_evaluation")
    validate_runtime_sec(max_runtime_sec)
    started = time.monotonic()
    validation = validate_historical_basis_plan(plan_path, expected_plan_hash)
    plan = _read_json(plan_path)
    snapshot = validate_basis_code_snapshot_reference(None, None, fallback_code_path=__file__)
    require_plan_code_snapshot(plan, snapshot)
    frozen_limit = int((plan.get("runtime") or {}).get("evaluation_max_runtime_sec") or 1800)
    if max_runtime_sec > frozen_limit:
        raise ValueError(f"MaxRuntimeSec exceeds frozen evaluation limit: {frozen_limit}")
    quality_path = Path(quality_report_path).expanduser().resolve()
    quality = _read_json(quality_path)
    _validate_quality(quality, quality_path=quality_path, plan_hash=validation["plan_hash"])
    require_plan_code_snapshot(plan, quality.get("code_provenance") or {})
    quality_sha = _sha256_bytes(quality_path)

    train_path = Path(str(quality.get("train_output") or "")).expanduser().resolve()
    if not train_path.exists() or _sha256_bytes(train_path) != quality.get("train_output_sha256"):
        raise ValueError("train shard hash mismatch")
    bars = _load_bars(train_path)
    oos_opened = False
    feasibility_ref: dict[str, Any] | None = None
    if stage == "full_evaluation":
        if feasibility_path is None:
            raise ValueError("full_evaluation requires feasibility_path")
        feasibility_target = Path(feasibility_path).expanduser().resolve()
        feasibility = _read_json(feasibility_target)
        _validate_feasibility(
            feasibility,
            plan_hash=validation["plan_hash"],
            quality_sha256=quality_sha,
        )
        feasibility_ref = {
            "path": str(feasibility_target),
            "file_sha256": _sha256_bytes(feasibility_target),
            "semantic_hash": feasibility["deterministic_result_hash"],
        }
        oos_path = Path(str(quality.get("oos_output") or "")).expanduser().resolve()
        if not oos_path.exists() or _sha256_bytes(oos_path) != quality.get("oos_output_sha256"):
            raise ValueError("OOS shard hash mismatch")
        bars.extend(_load_bars(oos_path))
        oos_opened = True
    if time.monotonic() - started > max_runtime_sec:
        raise TimeoutError("evaluation MaxRuntimeSec exceeded before simulation")

    core = evaluate_historical_basis(plan, bars, stage=stage)
    result: dict[str, Any] = {
        **core,
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "plan_path": validation["plan_path"],
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": validation["plan_hash"],
        "quality_report_path": str(quality_path),
        "quality_report_sha256": quality_sha,
        "quality_semantic_hash": quality["deterministic_result_hash"],
        "input_merkle_sha256": quality.get("input_merkle_sha256"),
        "feasibility_provenance": feasibility_ref,
        "parallel_parent_run_id": parallel_parent_run_id,
        "code_hash": sha256_file(__file__),
        "code_provenance": snapshot,
        "data_access_audit": {
            "train_file_opened": True,
            "oos_file_opened": oos_opened,
            "oos_rows_read": int(quality.get("oos_rows") or 0) if oos_opened else 0,
            "grid_search": False,
            "retune": False,
        },
        "runtime_sec": round(time.monotonic() - started, 3),
    }
    result["deterministic_result_hash"] = _semantic_hash(result)
    _atomic_write_json(Path(output_path).expanduser().resolve(), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Hash-bound no-grid historical basis evaluator")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--quality-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=("train_feasibility", "full_evaluation"), required=True)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--feasibility")
    parser.add_argument("--max-runtime-sec", type=int, default=1800)
    parser.add_argument("--parallel-parent-run-id")
    args = parser.parse_args()
    result = run_hash_bound_evaluation(
        plan_path=args.plan,
        quality_report_path=args.quality_report,
        output_path=args.output,
        stage=args.stage,
        expected_plan_hash=args.expected_plan_hash,
        feasibility_path=args.feasibility,
        max_runtime_sec=args.max_runtime_sec,
        parallel_parent_run_id=args.parallel_parent_run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
