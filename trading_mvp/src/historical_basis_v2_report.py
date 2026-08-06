from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from historical_basis_v2 import sha256_json
from historical_basis_v2_evaluator import (
    _artifact_hash,
    quality_semantic_hash,
    validate_full_evaluation_result,
)


SCHEMA = "trading_mvp_historical_basis_v2_terminal_report_v1"
CLOSURE_SCHEMA = "trading_mvp_historical_basis_v2_branch_closure_v1"
CLOSURE_MANIFEST_SCHEMA = "trading_mvp_historical_basis_v2_branch_closure_manifest_v1"
QUALITY_SCHEMA = "trading_mvp_historical_basis_v2_quality_v2"
POSTPROCESS_SCHEMA = "trading_mvp_historical_basis_v2_train_postprocess_v1"
HYPOTHESIS_ID = "cross_venue_perp_basis_convergence_1h_v2"


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_hash_bound_json(
    path: str | Path,
    expected_sha256: str,
    *,
    label: str,
) -> tuple[Path, dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"{label} is missing: {target}")
    if _sha256_file(target) != str(expected_sha256 or ""):
        raise ValueError(f"{label} file hash mismatch")
    return target, _read_json(target)


def _require_false_flags(payload: Mapping[str, Any], keys: Sequence[str], *, label: str) -> None:
    for key in keys:
        if payload.get(key) is not False:
            raise ValueError(f"{label} safety flag must be false: {key}")


def _validate_quality_reject_closure(
    closure_manifest_path: str | Path,
) -> dict[str, Any]:
    manifest_target = Path(closure_manifest_path).expanduser().resolve()
    manifest = _read_json(manifest_target)
    if manifest.get("schema") != CLOSURE_MANIFEST_SCHEMA:
        raise ValueError("unexpected quality closure manifest schema")
    if manifest.get("status") != "BRANCH_CLOSED_QUALITY_REJECTED" or manifest.get("final") is not True:
        raise ValueError("quality closure manifest is not final BRANCH_CLOSED_QUALITY_REJECTED")
    if manifest.get("verdict") != "INSUFFICIENT_EXECUTABLE_UNIVERSE":
        raise ValueError("unsupported quality closure verdict")
    if manifest.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("quality closure hypothesis mismatch")
    _require_false_flags(
        manifest,
        ("oos_read", "pnl_read", "retune", "replay_allowed", "grid_allowed", "live_orders_allowed"),
        label="quality closure manifest",
    )

    closure_target, closure = _read_hash_bound_json(
        str(manifest.get("closure_path") or ""),
        str(manifest.get("closure_file_sha256") or ""),
        label="closure",
    )
    if closure.get("schema") != CLOSURE_SCHEMA:
        raise ValueError("unexpected quality closure schema")
    if closure.get("final") is not True or closure.get("branch_status") != "CLOSED_WITHOUT_OOS_OR_RETUNE":
        raise ValueError("quality closure is not terminal")
    if closure.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("quality closure hypothesis mismatch")
    if closure.get("verdict") != manifest.get("verdict"):
        raise ValueError("quality closure verdict mismatch")
    if closure.get("artifact_hash") != manifest.get("closure_artifact_hash"):
        raise ValueError("quality closure artifact hash mismatch")
    _require_false_flags(
        closure,
        ("edge_evaluated", "train_signal_metrics_read", "oos_read", "pnl_read"),
        label="quality closure",
    )

    plan_ref = closure.get("plan_provenance")
    if not isinstance(plan_ref, Mapping):
        raise ValueError("quality closure plan provenance is missing")
    _plan_target, plan = _read_hash_bound_json(
        str(plan_ref.get("path") or ""),
        str(plan_ref.get("file_sha256") or ""),
        label="plan",
    )
    plan_hash = str(plan_ref.get("plan_hash") or "")
    if not plan_hash or plan.get("plan_hash") != plan_hash:
        raise ValueError("quality closure plan hash mismatch")
    hypothesis = plan.get("hypothesis")
    if not isinstance(hypothesis, Mapping) or hypothesis.get("id") != HYPOTHESIS_ID:
        raise ValueError("quality closure plan hypothesis mismatch")
    if hypothesis.get("frozen_parameters_no_grid") is not True or plan_ref.get("frozen_parameters_no_grid") is not True:
        raise ValueError("quality closure plan is not frozen no-grid")

    collector_ref = closure.get("collector")
    if not isinstance(collector_ref, Mapping):
        raise ValueError("quality closure collector provenance is missing")
    _collector_target, collector = _read_hash_bound_json(
        str(collector_ref.get("manifest_path") or ""),
        str(collector_ref.get("manifest_file_sha256") or ""),
        label="collector manifest",
    )
    if collector.get("status") != "READY_FOR_POSTPROCESS" or collector.get("final") is not True:
        raise ValueError("quality closure collector is not final READY_FOR_POSTPROCESS")
    if collector.get("plan_hash") != plan_hash or collector.get("expected_plan_hash") != plan_hash:
        raise ValueError("quality closure collector plan hash mismatch")
    expected_items = int(collector.get("expected_items") or 0)
    if expected_items <= 0 or int(collector.get("completed_items") or 0) != expected_items:
        raise ValueError("quality closure collector completion mismatch")
    if int(collector.get("error_count") or 0) != 0:
        raise ValueError("quality closure collector contains errors")

    quality_ref = closure.get("quality")
    if not isinstance(quality_ref, Mapping):
        raise ValueError("quality closure quality provenance is missing")
    _quality_target, quality = _read_hash_bound_json(
        str(quality_ref.get("report_path") or ""),
        str(quality_ref.get("report_file_sha256") or ""),
        label="quality report",
    )
    if quality.get("schema") != QUALITY_SCHEMA or quality.get("final") is not True:
        raise ValueError("quality closure quality report schema/finality mismatch")
    if quality.get("plan_hash") != plan_hash:
        raise ValueError("quality closure quality report plan hash mismatch")
    if quality.get("verdict") != "INSUFFICIENT_EXECUTABLE_UNIVERSE":
        raise ValueError("quality closure quality report verdict mismatch")
    if quality.get("report_payload_sha256") != quality_semantic_hash(quality):
        raise ValueError("quality report semantic hash mismatch")
    if quality_ref.get("report_payload_sha256") != quality.get("report_payload_sha256"):
        raise ValueError("quality closure report payload hash mismatch")

    quality_assets = int(quality.get("quality_surviving_asset_count") or 0)
    liquidity_assets = int(quality.get("surviving_asset_count") or 0)
    minimum_assets = int(quality_ref.get("minimum_required_assets") or 0)
    if quality_assets != int(quality_ref.get("quality_surviving_assets") or 0):
        raise ValueError("quality closure quality-surviving count mismatch")
    if liquidity_assets != int(quality_ref.get("liquidity_surviving_assets") or 0):
        raise ValueError("quality closure liquidity-surviving count mismatch")
    if minimum_assets <= 0 or liquidity_assets >= minimum_assets:
        raise ValueError("quality closure does not prove insufficient executable universe")
    audit = quality.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("quality closure data access audit is missing")
    _require_false_flags(
        audit,
        (
            "returns_read",
            "pnl_read",
            "pnl_computed",
            "signals_read",
            "oos_metrics_read",
            "oos_candle_values_used_for_liquidity",
        ),
        label="quality report",
    )

    postprocess_ref = closure.get("train_postprocess")
    if not isinstance(postprocess_ref, Mapping):
        raise ValueError("quality closure postprocess provenance is missing")
    postprocess_target, postprocess = _read_hash_bound_json(
        str(postprocess_ref.get("manifest_path") or ""),
        str(postprocess_ref.get("manifest_file_sha256") or ""),
        label="postprocess manifest",
    )
    if postprocess.get("schema") != POSTPROCESS_SCHEMA:
        raise ValueError("quality closure postprocess schema mismatch")
    if postprocess.get("status") != "BRANCH_CLOSED_QUALITY_REJECTED" or postprocess.get("final") is not True:
        raise ValueError("quality closure postprocess is not terminal quality reject")
    if postprocess.get("plan_hash") != plan_hash or postprocess.get("verdict") != manifest.get("verdict"):
        raise ValueError("quality closure postprocess identity mismatch")
    _require_false_flags(
        postprocess,
        ("oos_read", "full_evaluation", "network_access", "grid_search", "retune"),
        label="quality closure postprocess",
    )
    postprocess_hash_payload = {
        key: value
        for key, value in postprocess.items()
        if key not in {"generated_at_utc", "runtime_sec", "deterministic_result_hash"}
    }
    expected_postprocess_hash = sha256_json(postprocess_hash_payload)
    if postprocess.get("deterministic_result_hash") != expected_postprocess_hash:
        raise ValueError("quality closure postprocess deterministic hash mismatch")
    if postprocess_ref.get("deterministic_result_hash") != expected_postprocess_hash:
        raise ValueError("quality closure postprocess provenance hash mismatch")
    if Path(str(manifest.get("source_postprocess_manifest") or "")).expanduser().resolve() != postprocess_target:
        raise ValueError("quality closure source postprocess path mismatch")
    if manifest.get("source_deterministic_result_hash") != expected_postprocess_hash:
        raise ValueError("quality closure source result hash mismatch")

    accepted_assets = quality_ref.get("accepted_assets")
    if not isinstance(accepted_assets, list) or len(accepted_assets) != liquidity_assets:
        raise ValueError("quality closure accepted asset list mismatch")
    quality_ranking = quality.get("train_liquidity_ranking")
    if not isinstance(quality_ranking, list):
        raise ValueError("quality closure train liquidity ranking is missing")
    expected_asset_ids = [str(row.get("canonical_asset_id") or "") for row in quality_ranking]
    closure_asset_ids = [str(row.get("canonical_asset_id") or "") for row in accepted_assets]
    if closure_asset_ids != expected_asset_ids:
        raise ValueError("quality closure accepted assets do not match quality ranking")

    return {
        "manifest_path": str(manifest_target),
        "manifest_file_sha256": _sha256_file(manifest_target),
        "closure_path": str(closure_target),
        "closure_file_sha256": str(manifest["closure_file_sha256"]),
        "closure_artifact_hash": str(manifest["closure_artifact_hash"]),
        "plan_hash": plan_hash,
        "universe_hash": str(plan_ref.get("universe_hash") or ""),
        "code_snapshot_hash": str(plan_ref.get("code_snapshot_hash") or ""),
        "postprocess_path": str(postprocess_target),
        "postprocess_result_hash": expected_postprocess_hash,
        "verdict": str(manifest["verdict"]),
        "reason_code": str(closure.get("reason_code") or ""),
        "reason": str(closure.get("reason") or ""),
        "quality_summary": {
            "quality_surviving_assets": quality_assets,
            "liquidity_surviving_assets": liquidity_assets,
            "minimum_required_assets": minimum_assets,
            "minimum_train_median_quote_volume": float(
                quality_ref.get("minimum_train_median_quote_volume") or 0.0
            ),
            "accepted_assets": accepted_assets,
            "train_rows": int(quality_ref.get("train_rows") or 0),
            "oos_rows_normalized_not_evaluated": int(
                quality_ref.get("oos_rows_normalized_not_evaluated") or 0
            ),
            "funding_events": int(quality_ref.get("funding_events") or 0),
            "input_file_merkle_sha256": str(quality_ref.get("input_file_merkle_sha256") or ""),
        },
    }


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _validate_evaluation(evaluation: Mapping[str, Any]) -> None:
    validate_full_evaluation_result(evaluation)


def build_terminal_report(
    evaluation_path: str | Path | None,
    output_path: str | Path,
    *,
    closure_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    if (evaluation_path is None) == (closure_manifest_path is None):
        raise ValueError("exactly one terminal source is required: evaluation or closure manifest")

    if closure_manifest_path is not None:
        source = _validate_quality_reject_closure(closure_manifest_path)
        report: dict[str, Any] = {
            "schema": SCHEMA,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "TERMINAL_PRE_OOS_QUALITY_VERDICT",
            "source_kind": "quality_reject_closure",
            "hypothesis_id": HYPOTHESIS_ID,
            "plan_hash": source["plan_hash"],
            "universe_hash": source["universe_hash"],
            "code_snapshot_hash": source["code_snapshot_hash"],
            "closure_manifest_path": source["manifest_path"],
            "closure_manifest_file_sha256": source["manifest_file_sha256"],
            "closure_path": source["closure_path"],
            "closure_file_sha256": source["closure_file_sha256"],
            "closure_artifact_hash": source["closure_artifact_hash"],
            "postprocess_path": source["postprocess_path"],
            "postprocess_result_hash": source["postprocess_result_hash"],
            "verdict": source["verdict"],
            "rejection_reasons": [source["reason_code"]],
            "reason": source["reason"],
            "quality_summary": source["quality_summary"],
            "data_access_audit": {
                "oos_read": False,
                "pnl_read": False,
                "returns_read": False,
                "network_access": False,
                "grid_search": False,
                "retune": False,
            },
            "maximum_authority": "BRANCH_CLOSED_NO_OOS",
            "safety": {
                "research_only": True,
                "live_orders": False,
                "private_api_keys": False,
                "leverage_or_margin": False,
                "grid_search": False,
                "retune": False,
                "automatic_oos": False,
            },
            "next_allowed_command": "open-materially-new-planonly-hypothesis-or-continue-pit-shadow",
        }
        report["deterministic_result_hash"] = _artifact_hash(report)
        _write_json_immutable(output_path, report)
        return report

    assert evaluation_path is not None
    evaluation_target = Path(evaluation_path).expanduser().resolve()
    evaluation = _read_json(evaluation_target)
    _validate_evaluation(evaluation)
    verdict = str(evaluation["verdict"])
    next_command = (
        "fast-edge-basis-v2-execution-probe-plan"
        if verdict == "ACCEPT_FOR_EXECUTION_PROBE"
        else "close-hypothesis-without-retune"
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "TERMINAL_HISTORICAL_VERDICT",
        "source_kind": "full_evaluation",
        "hypothesis_id": HYPOTHESIS_ID,
        "plan_hash": evaluation["plan_hash"],
        "evaluation_path": str(evaluation_target),
        "evaluation_result_hash": evaluation["deterministic_result_hash"],
        "verdict": verdict,
        "rejection_reasons": list(evaluation.get("rejection_reasons") or []),
        "metrics": evaluation.get("metrics"),
        "four_hour_robustness": evaluation.get("four_hour_robustness"),
        # Preserve legacy aliases for older frozen evaluator artifacts.
        "normal_metrics": evaluation.get("normal_metrics"),
        "stress_metrics": evaluation.get("stress_metrics"),
        "robustness_4h": evaluation.get("robustness_4h"),
        "maximum_authority": "EXECUTION_PROBE_PLANONLY",
        "safety": {
            "research_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "grid_search": False,
            "retune": False,
        },
        "next_allowed_command": next_command,
    }
    report["deterministic_result_hash"] = _artifact_hash(report)
    _write_json_immutable(output_path, report)
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the historical basis v2 terminal report")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--evaluation")
    source.add_argument("--closure-manifest")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_terminal_report(
        args.evaluation,
        args.output,
        closure_manifest_path=args.closure_manifest,
    )
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
