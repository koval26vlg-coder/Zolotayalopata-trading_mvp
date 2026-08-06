from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIT_SCHEMA = "cross_sectional_capitulation_audit_v1"
NO_SIGNAL_DECISION = "CROSS_SECTIONAL_CAPITULATION_REJECTED_NO_FIXED_SIGNALS"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _same_path(left: Any, right: Any) -> bool:
    try:
        return Path(str(left)).resolve() == Path(str(right)).resolve()
    except (OSError, TypeError, ValueError):
        return False


def build_audit(
    report_path: str | Path,
    manifest_path: str | Path,
    plan_path: str | Path,
    *,
    expected_plan_sha256: str | None = None,
    algorithm_path: str | Path | None = None,
) -> dict[str, Any]:
    report_file = Path(report_path)
    manifest_file = Path(manifest_path)
    plan_file = Path(plan_path)
    report = _load(report_file)
    manifest = _load(manifest_file)
    plan = _load(plan_file)
    failures: list[str] = []
    plan_hash = _sha(plan_file)
    if expected_plan_sha256 and plan_hash.lower() != expected_plan_sha256.lower():
        failures.append("sealed_plan_sha256_mismatch")
    if report.get("schema") != "cross_sectional_capitulation_report_v1":
        failures.append("report_schema_mismatch")
    if manifest.get("schema") != "cross_sectional_capitulation_manifest_v1":
        failures.append("manifest_schema_mismatch")
    if plan.get("schema") != "cross_sectional_capitulation_plan_v1":
        failures.append("plan_schema_mismatch")
    if str(report.get("plan_sha256", "")).lower() != plan_hash.lower() or str(manifest.get("plan_sha256", "")).lower() != plan_hash.lower():
        failures.append("artifact_plan_hash_mismatch")
    if not _same_path(report.get("plan_path"), plan_file) or not _same_path(manifest.get("plan_path"), plan_file):
        failures.append("artifact_plan_path_mismatch")
    if not _same_path(report.get("output_path"), report_file) or not _same_path(manifest.get("output_path"), report_file):
        failures.append("artifact_output_path_mismatch")
    if manifest.get("status") != "COMPLETED" or manifest.get("final") is not True or manifest.get("stop_reason") != "completed" or int(manifest.get("errors", -1)) != 0:
        failures.append("manifest_not_clean_final")
    for name in ("strategy_accepted", "paper_forward_ready", "live_orders", "api_keys", "leverage_or_margin", "grid_search", "collect"):
        if report.get(name) is not False:
            failures.append(f"report_{name}_must_be_false")
    if plan.get("research_only") is not True or plan.get("fixed_parameters_no_grid") is not True or plan.get("strategy_accepted") is not False:
        failures.append("sealed_plan_research_contract_broken")

    evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
    data = plan.get("data") if isinstance(plan.get("data"), dict) else {}
    for prefix, path_field, hash_field in (
        ("history", "history_jsonl_path", "history_jsonl_sha256"),
        ("history_manifest", "history_manifest_path", "history_manifest_sha256"),
        ("universe", "universe_path", "universe_sha256"),
    ):
        path = Path(str(data.get(path_field, "")))
        if not path.is_file():
            failures.append(f"{prefix}_missing")
            continue
        observed = _sha(path)
        if observed.lower() != str(data.get(hash_field, "")).lower():
            failures.append(f"{prefix}_plan_hash_mismatch")
        embedded = evidence.get(prefix) if isinstance(evidence.get(prefix), dict) else {}
        if observed.lower() != str(embedded.get("sha256", "")).lower():
            failures.append(f"{prefix}_report_hash_mismatch")

    universe = report.get("universe") if isinstance(report.get("universe"), dict) else {}
    history = report.get("history") if isinstance(report.get("history"), dict) else {}
    filters = report.get("filters") if isinstance(report.get("filters"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    trades = report.get("trades") if isinstance(report.get("trades"), list) else []
    if universe.get("coverage_gate") is not True:
        failures.append("point_in_time_negative_outcome_coverage_failed")
    if sorted(universe.get("bases") or []) != sorted(universe.get("requested_bases_in_history") or []):
        failures.append("requested_universe_set_mismatch")
    if int(history.get("invalid_rows", -1)) != 0 or int(history.get("duplicate_bars", -1)) != 0:
        failures.append("history_invalid_or_duplicate_rows")
    if int(history.get("total_source_rows", -1)) != int(manifest.get("rows", -2)):
        failures.append("manifest_source_row_count_mismatch")

    observations = int(filters.get("return_observations", 0))
    terminal_filter_names = {
        "peer_count",
        "base_return",
        "residual",
        "volume_history",
        "current_quote_volume",
        "trailing_quote_volume",
        "volume_ratio",
        "close_location",
        "missing_execution_bars",
        "fixed_signal_candidates",
    }
    terminal_count = sum(int(filters.get(name, 0)) for name in terminal_filter_names)
    if observations != terminal_count:
        failures.append("filter_accounting_mismatch")
    candidate_count = int(summary.get("fixed_signal_candidates", -1))
    trade_count = int(summary.get("executed_trades", -1))
    if candidate_count != int(filters.get("fixed_signal_candidates", 0)):
        failures.append("candidate_summary_mismatch")
    if trade_count != len(trades):
        failures.append("trade_summary_mismatch")
    if int((validation.get("all") or {}).get("trades", -1)) != len(trades):
        failures.append("validation_trade_count_mismatch")
    gates = validation.get("gates") if isinstance(validation.get("gates"), dict) else {}
    if bool(validation.get("all_gates_passed")) != all(bool(value) for value in gates.values()):
        failures.append("all_gates_passed_mismatch")

    execution = plan.get("execution") if isinstance(plan.get("execution"), dict) else {}
    normal_cost = float(execution.get("normal_round_trip_fee_bps", 0)) + float(execution.get("normal_spread_slippage_buffer_bps", 0))
    if abs(normal_cost - float(execution.get("normal_total_cost_bps", -1))) > 1e-9:
        failures.append("normal_cost_math_mismatch")
    if float(execution.get("stress_total_cost_bps", 0)) <= normal_cost:
        failures.append("stress_cost_not_conservative")

    if report.get("decision") != NO_SIGNAL_DECISION or candidate_count != 0 or trade_count != 0:
        failures.append("no_signal_closure_contradiction")
    algorithm_file = Path(algorithm_path) if algorithm_path else Path(__file__).with_name("cross_sectional_capitulation.py")
    return {
        "schema": AUDIT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_passed": not failures,
        "decision": "CROSS_SECTIONAL_CAPITULATION_VERIFIED_REJECTED_NO_FIXED_SIGNALS" if not failures else "CROSS_SECTIONAL_CAPITULATION_AUDIT_FAILED",
        "failures": failures,
        "strategy_accepted": False,
        "paper_forward_ready": False,
        "report_path": str(report_file),
        "report_sha256": _sha(report_file),
        "manifest_path": str(manifest_file),
        "manifest_sha256": _sha(manifest_file),
        "plan_path": str(plan_file),
        "plan_sha256": plan_hash,
        "algorithm_path": str(algorithm_file),
        "algorithm_sha256": _sha(algorithm_file),
        "evidence": {
            "source_rows": int(history.get("total_source_rows", 0)),
            "universe_bases": int(universe.get("selected_unique_bases", 0)),
            "requested_bases": len(universe.get("requested_bases_in_history") or []),
            "ok_bases": int(history.get("ok_base_count", 0)),
            "analysis_span_days": float(summary.get("analysis_span_days", 0)),
            "return_observations": observations,
            "fixed_signal_candidates": candidate_count,
            "executed_trades": trade_count,
            "normal_total_cost_bps": normal_cost,
            "stress_total_cost_bps": float(execution.get("stress_total_cost_bps", 0)),
        },
        "next_step": "Close this branch without threshold tuning. Existing local hypothesis backlog is exhausted; prepare a separate forward data plan rather than another same-sample variant." if not failures else "Fix audit failures before using this report as evidence.",
    }


def run_audit(report_path: str | Path, manifest_path: str | Path, plan_path: str | Path, output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    audit = build_audit(report_path, manifest_path, plan_path, **kwargs)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed audit for cross-sectional capitulation replay.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--algorithm")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit = run_audit(args.report, args.manifest, args.plan, args.output, expected_plan_sha256=args.expected_plan_sha256, algorithm_path=args.algorithm)
    print(json.dumps({"output": args.output, "decision": audit["decision"], "audit_passed": audit["audit_passed"], "failures": audit["failures"]}, ensure_ascii=False, indent=2))
    return 0 if audit["audit_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
