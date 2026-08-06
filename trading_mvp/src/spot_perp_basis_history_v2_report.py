from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from spot_perp_basis_history_v2 import (
    HYPOTHESIS_ID,
    sha256_file,
    sha256_json,
    validate_gate_spot_perp_plan,
)
from spot_perp_basis_history_v2_collector import COLLECT_SCHEMA
from spot_perp_basis_history_v2_quality import QUALITY_SCHEMA
from spot_perp_basis_history_v2_train import (
    TRAIN_PLAN_SCHEMA,
    TRAIN_RESULT_SCHEMA,
    validate_train_plan,
)


CLOSURE_SCHEMA = "trading_mvp_gate_spot_perp_branch_closure_v1"
CLOSURE_MANIFEST_SCHEMA = "trading_mvp_gate_spot_perp_branch_closure_manifest_v1"
BRANCH_STATUS = "CLOSED_WITHOUT_OOS_OR_RETUNE"
VERDICT = "INFEASIBLE_ON_CURRENT_DATA"
REASON_CODE = "FROZEN_ECONOMIC_ENTRY_THRESHOLD_NOT_OBSERVED_IN_TRAIN"


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {target}")
    return value


def _read_jsonl_hash_bound(path: str | Path, expected_sha256: str) -> list[dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if sha256_file(target) != str(expected_sha256).lower():
        raise ValueError(f"input hash mismatch: {target}")
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row is not an object: {target}:{line_number}")
            rows.append(value)
    return rows


def _write_json_immutable(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _as_positive_float(value: Any, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return parsed


def _nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def summarize_basis_values(
    values_by_base: Mapping[str, Sequence[float]],
    *,
    normal_break_even_bps: float,
    stress_break_even_bps: float,
    frozen_entry_threshold_bps: float,
) -> dict[str, Any]:
    thresholds = {
        "normal_break_even_bps": float(normal_break_even_bps),
        "stress_break_even_bps": float(stress_break_even_bps),
        "frozen_entry_threshold_bps": float(frozen_entry_threshold_bps),
    }
    assets: list[dict[str, Any]] = []
    all_values: list[float] = []
    for base in sorted(values_by_base):
        values = [float(value) for value in values_by_base[base] if math.isfinite(float(value))]
        all_values.extend(values)
        assets.append(
            {
                "base": base,
                "observation_count": len(values),
                "maximum_basis_bps": max(values) if values else None,
                "p99_basis_bps_nearest_rank": _nearest_rank(values, 0.99),
                "count_at_or_above_normal_break_even": sum(
                    value >= normal_break_even_bps for value in values
                ),
                "count_at_or_above_stress_break_even": sum(
                    value >= stress_break_even_bps for value in values
                ),
                "count_at_or_above_frozen_entry": sum(
                    value >= frozen_entry_threshold_bps for value in values
                ),
            }
        )
    assets.sort(
        key=lambda row: (
            -(float(row["maximum_basis_bps"]) if row["maximum_basis_bps"] is not None else -math.inf),
            str(row["base"]),
        )
    )
    summary = {
        "thresholds": thresholds,
        "asset_count": len(assets),
        "observation_count": len(all_values),
        "maximum_basis_bps": max(all_values) if all_values else None,
        "p99_basis_bps_nearest_rank": _nearest_rank(all_values, 0.99),
        "count_at_or_above_normal_break_even": sum(
            value >= normal_break_even_bps for value in all_values
        ),
        "count_at_or_above_stress_break_even": sum(
            value >= stress_break_even_bps for value in all_values
        ),
        "count_at_or_above_frozen_entry": sum(
            value >= frozen_entry_threshold_bps for value in all_values
        ),
        "asset_count_at_or_above_frozen_entry": sum(
            row["count_at_or_above_frozen_entry"] > 0 for row in assets
        ),
        "assets": assets,
    }
    summary["diagnostic_hash"] = sha256_json(summary)
    return summary


def _validate_collector(manifest: Mapping[str, Any], *, expected_plan_hash: str) -> None:
    if manifest.get("schema") != COLLECT_SCHEMA:
        raise ValueError("collector schema mismatch")
    if manifest.get("status") != "READY_FOR_POSTPROCESS" or manifest.get("final") is not True:
        raise ValueError("collector is not final READY_FOR_POSTPROCESS")
    if manifest.get("plan_hash") != expected_plan_hash:
        raise ValueError("collector plan hash mismatch")
    expected = int(manifest.get("expected_tasks") or 0)
    if expected <= 0 or int(manifest.get("completed_tasks") or 0) != expected:
        raise ValueError("collector task completion mismatch")
    if int(manifest.get("error_count") or 0) != 0:
        raise ValueError("collector contains errors")
    payload = {
        key: value
        for key, value in manifest.items()
        if key
        not in {
            "updated_at",
            "actual_duration_sec",
            "manifest_hash",
            "collector_pid",
            "process_ids",
            "resume_command",
        }
    }
    if sha256_json(payload) != manifest.get("manifest_hash"):
        raise ValueError("collector semantic hash mismatch")


def _validate_quality(report: Mapping[str, Any], *, expected_plan_hash: str) -> None:
    if report.get("schema") != QUALITY_SCHEMA or report.get("final") is not True:
        raise ValueError("quality schema/finality mismatch")
    if report.get("decision") != "GATE_SPOT_PERP_HISTORY_READY_FOR_TRAIN_FEASIBILITY":
        raise ValueError("quality report did not admit train feasibility")
    if report.get("plan_hash") != expected_plan_hash:
        raise ValueError("quality plan hash mismatch")
    if int(report.get("accepted_asset_count") or 0) < int(report.get("minimum_assets") or 0):
        raise ValueError("quality report has too few accepted assets")
    payload = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
    }
    if sha256_json(payload) != report.get("artifact_hash"):
        raise ValueError("quality artifact hash mismatch")
    for flag in ("returns_read", "signals_read", "pnl_read", "oos_read", "grid_search", "live_orders"):
        if report.get(flag) is not False:
            raise ValueError(f"quality safety flag must be false: {flag}")


def validate_train_reject_result(
    result: Mapping[str, Any],
    *,
    expected_train_plan_hash: str,
) -> None:
    if result.get("schema") != TRAIN_RESULT_SCHEMA or result.get("final") is not True:
        raise ValueError("train result schema/finality mismatch")
    if result.get("train_plan_hash") != expected_train_plan_hash:
        raise ValueError("train result plan hash mismatch")
    if result.get("decision") != VERDICT:
        raise ValueError("closure requires an infeasible train result")
    if result.get("deterministic_repeat_match") is not True:
        raise ValueError("train deterministic repeat did not match")
    expected_hash = str(result.get("deterministic_result_hash") or "")
    if result.get("deterministic_repeat_hash") != expected_hash:
        raise ValueError("train deterministic repeat hash mismatch")
    core_keys = (
        "schema",
        "final",
        "decision",
        "train_plan_hash",
        "metrics",
        "rejection_reasons",
        "asset_diagnostics",
        "episodes",
        "oos_read",
        "grid_search",
        "retune",
        "network_access",
        "live_orders",
        "next_allowed_command",
    )
    core = {key: result[key] for key in core_keys}
    if sha256_json(core) != expected_hash:
        raise ValueError("train deterministic result hash mismatch")
    if result.get("oos_read") is not False or result.get("grid_search") is not False:
        raise ValueError("train result violates OOS/grid safety")
    if result.get("retune") is not False or result.get("network_access") is not False:
        raise ValueError("train result violates retune/network safety")
    if result.get("next_allowed_command") != "none_branch_closed_no_retune":
        raise ValueError("train reject does not close the branch")


def build_train_basis_diagnostic(train_plan: Mapping[str, Any]) -> dict[str, Any]:
    window = train_plan["train_window"]
    strategy = train_plan["strategy"]
    economics = train_plan["economics"]
    signal_start = int(window["signal_start_sec"])
    train_end = int(window["train_end_sec"])
    values_by_base: dict[str, list[float]] = {}
    for asset in train_plan["asset_inputs"]:
        base = str(asset["base"]).upper()
        values: list[float] = []
        for row in _read_jsonl_hash_bound(asset["train_rows_path"], asset["train_rows_sha256"]):
            timestamp = int(row["ts"])
            if not signal_start <= timestamp < train_end:
                continue
            spot_close = _as_positive_float((row.get("spot") or {}).get("close"), field="spot.close")
            mark_close = _as_positive_float((row.get("mark") or {}).get("close"), field="mark.close")
            values.append((mark_close - spot_close) / spot_close * 10_000.0)
        values_by_base[base] = values
    exit_threshold = float(strategy["exit_threshold_bps"])
    return summarize_basis_values(
        values_by_base,
        normal_break_even_bps=float(economics["normal_cycle_cost_bps"]) + exit_threshold,
        stress_break_even_bps=float(economics["stress_cycle_cost_bps"]) + exit_threshold,
        frozen_entry_threshold_bps=float(strategy["entry_threshold_bps"]),
    )


def _provenance(path: Path, payload: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "path": str(path),
        "file_sha256": sha256_file(path),
        **fields,
    }


def build_train_reject_closure(
    *,
    parent_plan_path: str | Path,
    expected_parent_plan_hash: str,
    collector_manifest_path: str | Path,
    quality_report_path: str | Path,
    train_plan_path: str | Path,
    expected_train_plan_hash: str,
    train_result_path: str | Path,
    output_directory: str | Path,
    run_id: str,
    max_runtime_sec: int = 1_800,
) -> dict[str, Any]:
    if not 0 < int(max_runtime_sec) <= 1_800:
        raise ValueError("closure MaxRuntimeSec must be in [1, 1800]")
    started = time.monotonic()
    paths = {
        "parent": Path(parent_plan_path).expanduser().resolve(),
        "collector": Path(collector_manifest_path).expanduser().resolve(),
        "quality": Path(quality_report_path).expanduser().resolve(),
        "train_plan": Path(train_plan_path).expanduser().resolve(),
        "train_result": Path(train_result_path).expanduser().resolve(),
    }
    parent = _read_json(paths["parent"])
    validate_gate_spot_perp_plan(parent, expected_plan_hash=expected_parent_plan_hash)
    collector = _read_json(paths["collector"])
    _validate_collector(collector, expected_plan_hash=expected_parent_plan_hash)
    quality = _read_json(paths["quality"])
    _validate_quality(quality, expected_plan_hash=expected_parent_plan_hash)
    train_plan = _read_json(paths["train_plan"])
    validate_train_plan(train_plan, expected_plan_hash=expected_train_plan_hash)
    if train_plan.get("parent_plan_hash") != expected_parent_plan_hash:
        raise ValueError("train plan parent hash mismatch")
    if train_plan.get("quality_artifact_hash") != quality.get("artifact_hash"):
        raise ValueError("train plan quality hash mismatch")
    train_result = _read_json(paths["train_result"])
    validate_train_reject_result(train_result, expected_train_plan_hash=expected_train_plan_hash)
    diagnostic = build_train_basis_diagnostic(train_plan)
    if diagnostic["count_at_or_above_frozen_entry"] != 0:
        raise ValueError("train rejection is not explained by an unobserved frozen threshold")
    if time.monotonic() - started > int(max_runtime_sec):
        raise TimeoutError("closure exceeded MaxRuntimeSec")

    output = Path(output_directory).expanduser().resolve()
    closure_path = output / f"{run_id}.closure.json"
    manifest_path = output / f"{run_id}.closure.manifest.json"
    generated = datetime.now(timezone.utc).isoformat()
    max_basis = float(diagnostic["maximum_basis_bps"] or 0.0)
    threshold = float(diagnostic["thresholds"]["frozen_entry_threshold_bps"])
    closure: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA,
        "generated_at_utc": generated,
        "project": "trading_mvp",
        "hypothesis_id": HYPOTHESIS_ID,
        "run_id": run_id,
        "final": True,
        "verdict": VERDICT,
        "branch_status": BRANCH_STATUS,
        "reason_code": REASON_CODE,
        "reason": (
            f"The frozen {threshold:.1f} bps entry threshold was never observed in the "
            f"100-day train window; maximum observed basis was {max_basis:.6f} bps."
        ),
        "parent_plan": _provenance(
            paths["parent"],
            parent,
            plan_hash=expected_parent_plan_hash,
            frozen_parameters_no_grid=True,
        ),
        "collector": _provenance(
            paths["collector"],
            collector,
            manifest_hash=collector["manifest_hash"],
            status=collector["status"],
            expected_tasks=collector["expected_tasks"],
            completed_tasks=collector["completed_tasks"],
            error_count=collector["error_count"],
        ),
        "quality": _provenance(
            paths["quality"],
            quality,
            artifact_hash=quality["artifact_hash"],
            decision=quality["decision"],
            accepted_assets=quality["accepted_assets"],
            accepted_asset_count=quality["accepted_asset_count"],
            minimum_assets=quality["minimum_assets"],
        ),
        "train_plan": _provenance(
            paths["train_plan"],
            train_plan,
            plan_hash=expected_train_plan_hash,
            code_snapshot_hash=train_plan["code_provenance"]["code_snapshot_hash"],
            code_snapshot_manifest=train_plan["code_provenance"]["code_snapshot_manifest"],
            code_snapshot_manifest_sha256=train_plan["code_provenance"]["code_snapshot_manifest_sha256"],
        ),
        "train_result": _provenance(
            paths["train_result"],
            train_result,
            deterministic_result_hash=train_result["deterministic_result_hash"],
            deterministic_repeat_match=True,
            decision=train_result["decision"],
            metrics=train_result["metrics"],
            rejection_reasons=train_result["rejection_reasons"],
        ),
        "train_basis_diagnostic": diagnostic,
        "data_access_audit": {
            "train_price_rows_read": True,
            "train_signal_metrics_read": True,
            "train_pnl_computed": True,
            "oos_read": False,
            "oos_metrics_computed": False,
            "network_access": False,
            "grid_search": False,
            "retune": False,
        },
        "safety": {
            "research_only": True,
            "public_data_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "automatic_oos": False,
        },
        "forbidden_next_actions": [
            "oos_for_this_branch",
            "threshold_retune_for_this_branch",
            "grid_search_for_this_branch",
            "execution_probe_for_this_branch",
            "paper_forward_for_this_branch",
            "live_trading_for_this_branch",
        ],
        "next_allowed_action": "open_materially_new_planonly_hypothesis_or_continue_independent_pit_shadow_track",
    }
    closure["artifact_hash"] = sha256_json(
        {key: value for key, value in closure.items() if key not in {"generated_at_utc", "artifact_hash"}}
    )
    _write_json_immutable(closure_path, closure)
    manifest: dict[str, Any] = {
        "schema": CLOSURE_MANIFEST_SCHEMA,
        "generated_at_utc": generated,
        "project": "trading_mvp",
        "hypothesis_id": HYPOTHESIS_ID,
        "run_id": run_id,
        "status": "BRANCH_CLOSED_TRAIN_INFEASIBLE",
        "final": True,
        "verdict": VERDICT,
        "closure_path": str(closure_path),
        "closure_file_sha256": sha256_file(closure_path),
        "closure_artifact_hash": closure["artifact_hash"],
        "source_train_result_path": str(paths["train_result"]),
        "source_train_result_file_sha256": sha256_file(paths["train_result"]),
        "source_train_result_hash": train_result["deterministic_result_hash"],
        "oos_read": False,
        "retune": False,
        "grid_allowed": False,
        "replay_allowed": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders_allowed": False,
        "next_allowed_action": closure["next_allowed_action"],
    }
    manifest["manifest_hash"] = sha256_json(
        {key: value for key, value in manifest.items() if key not in {"generated_at_utc", "manifest_hash"}}
    )
    _write_json_immutable(manifest_path, manifest)
    return {
        "closure_path": str(closure_path),
        "closure_file_sha256": manifest["closure_file_sha256"],
        "closure_artifact_hash": closure["artifact_hash"],
        "manifest_path": str(manifest_path),
        "manifest_file_sha256": sha256_file(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "verdict": VERDICT,
        "reason_code": REASON_CODE,
        "maximum_basis_bps": diagnostic["maximum_basis_bps"],
        "frozen_entry_threshold_bps": threshold,
        "runtime_sec": round(time.monotonic() - started, 6),
    }


def validate_train_reject_closure_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != CLOSURE_MANIFEST_SCHEMA:
        raise ValueError("closure manifest schema mismatch")
    if manifest.get("status") != "BRANCH_CLOSED_TRAIN_INFEASIBLE" or manifest.get("final") is not True:
        raise ValueError("closure manifest is not terminal train-infeasible")
    if manifest.get("verdict") != VERDICT or manifest.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("closure manifest identity mismatch")
    manifest_payload = {
        key: value
        for key, value in manifest.items()
        if key not in {"generated_at_utc", "manifest_hash"}
    }
    if sha256_json(manifest_payload) != manifest.get("manifest_hash"):
        raise ValueError("closure manifest semantic hash mismatch")
    for flag in (
        "oos_read",
        "retune",
        "grid_allowed",
        "replay_allowed",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders_allowed",
    ):
        if manifest.get(flag) is not False:
            raise ValueError(f"closure manifest safety flag must be false: {flag}")
    closure_path = Path(str(manifest.get("closure_path") or "")).expanduser().resolve()
    if sha256_file(closure_path) != manifest.get("closure_file_sha256"):
        raise ValueError("closure file hash mismatch")
    closure = _read_json(closure_path)
    if closure.get("schema") != CLOSURE_SCHEMA or closure.get("final") is not True:
        raise ValueError("closure schema/finality mismatch")
    if closure.get("branch_status") != BRANCH_STATUS or closure.get("verdict") != VERDICT:
        raise ValueError("closure verdict/status mismatch")
    if closure.get("reason_code") != REASON_CODE:
        raise ValueError("closure reason code mismatch")
    closure_payload = {
        key: value
        for key, value in closure.items()
        if key not in {"generated_at_utc", "artifact_hash"}
    }
    if sha256_json(closure_payload) != closure.get("artifact_hash"):
        raise ValueError("closure artifact hash mismatch")
    if closure.get("artifact_hash") != manifest.get("closure_artifact_hash"):
        raise ValueError("closure/manifest artifact hash mismatch")
    diagnostic = closure.get("train_basis_diagnostic") or {}
    if int(diagnostic.get("count_at_or_above_frozen_entry") or 0) != 0:
        raise ValueError("terminal reason is inconsistent with basis diagnostic")
    audit = closure.get("data_access_audit") or {}
    if audit.get("train_pnl_computed") is not True or audit.get("oos_read") is not False:
        raise ValueError("closure data-access audit is inconsistent")
    for reference_name in ("parent_plan", "collector", "quality", "train_plan", "train_result"):
        reference = closure.get(reference_name) or {}
        referenced_path = Path(str(reference.get("path") or "")).expanduser().resolve()
        if sha256_file(referenced_path) != reference.get("file_sha256"):
            raise ValueError(f"closure provenance changed: {reference_name}")
    return {
        "valid": True,
        "manifest_path": str(manifest_path),
        "manifest_file_sha256": sha256_file(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "closure_path": str(closure_path),
        "closure_file_sha256": manifest["closure_file_sha256"],
        "closure_artifact_hash": closure["artifact_hash"],
        "verdict": closure["verdict"],
        "reason_code": closure["reason_code"],
        "maximum_basis_bps": diagnostic.get("maximum_basis_bps"),
        "frozen_entry_threshold_bps": (diagnostic.get("thresholds") or {}).get(
            "frozen_entry_threshold_bps"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Close a Gate spot/perp v2 train-infeasible branch")
    parser.add_argument("--parent-plan", required=True)
    parser.add_argument("--expected-parent-plan-hash", required=True)
    parser.add_argument("--collector-manifest", required=True)
    parser.add_argument("--quality-report", required=True)
    parser.add_argument("--train-plan", required=True)
    parser.add_argument("--expected-train-plan-hash", required=True)
    parser.add_argument("--train-result", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=1_800)
    args = parser.parse_args(argv)
    result = build_train_reject_closure(
        parent_plan_path=args.parent_plan,
        expected_parent_plan_hash=args.expected_parent_plan_hash,
        collector_manifest_path=args.collector_manifest,
        quality_report_path=args.quality_report,
        train_plan_path=args.train_plan,
        expected_train_plan_hash=args.expected_train_plan_hash,
        train_result_path=args.train_result,
        output_directory=args.output_directory,
        run_id=args.run_id,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
