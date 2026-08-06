from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cross_venue_full_scan_audit import sample_file_fingerprint


AUDIT_SCHEMA = "cross_venue_spot_lead_lag_audit_v1"
REPORT_SCHEMA = "cross_venue_spot_lead_lag_report_v1"
MANIFEST_SCHEMA = "cross_venue_spot_lead_lag_manifest_v1"
PLAN_SCHEMA = "cross_venue_spot_lead_lag_plan_v1"
NO_SIGNAL_DECISION = "CROSS_VENUE_SPOT_LEAD_LAG_REJECTED_NO_FIXED_SIGNALS"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_path(left: Any, right: Any) -> bool:
    try:
        return Path(str(left)).resolve() == Path(str(right)).resolve()
    except (OSError, TypeError, ValueError):
        return False


def build_lead_lag_audit(
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
    warnings: list[str] = []

    plan_hash = _sha256(plan_file)
    report_hash = _sha256(report_file)
    manifest_hash = _sha256(manifest_file)
    if expected_plan_sha256 and plan_hash.lower() != expected_plan_sha256.lower():
        failures.append("sealed_plan_sha256_mismatch")
    if report.get("schema") != REPORT_SCHEMA:
        failures.append("report_schema_mismatch")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        failures.append("manifest_schema_mismatch")
    if plan.get("schema") != PLAN_SCHEMA:
        failures.append("plan_schema_mismatch")
    if str(report.get("plan_sha256", "")).lower() != plan_hash.lower():
        failures.append("report_plan_sha256_mismatch")
    if str(manifest.get("plan_sha256", "")).lower() != plan_hash.lower():
        failures.append("manifest_plan_sha256_mismatch")
    if not _same_path(report.get("plan_path"), plan_file):
        failures.append("report_plan_path_mismatch")
    if not _same_path(manifest.get("plan_path"), plan_file):
        failures.append("manifest_plan_path_mismatch")

    for name in ("research_only",):
        if report.get(name) is not True or manifest.get(name) is not True or plan.get(name) is not True:
            failures.append(f"{name}_contract_broken")
    for name in ("strategy_accepted", "paper_forward_ready", "live_orders", "api_keys", "leverage_or_margin", "grid_search", "collect"):
        if report.get(name) is not False:
            failures.append(f"report_{name}_must_be_false")
    for name in ("live_orders", "api_keys", "leverage_or_margin", "grid_search", "collect"):
        if manifest.get(name) is not False:
            failures.append(f"manifest_{name}_must_be_false")
    if plan.get("fixed_parameters_no_grid") is not True or plan.get("strategy_accepted") is not False:
        failures.append("sealed_plan_fixed_research_contract_broken")

    if manifest.get("status") != "COMPLETED" or manifest.get("final") is not True:
        failures.append("manifest_not_completed_final")
    if manifest.get("stop_reason") != "completed" or int(manifest.get("errors", -1)) != 0:
        failures.append("manifest_completion_error_state")
    if not _same_path(manifest.get("output_path"), report_file):
        failures.append("manifest_output_path_mismatch")
    if not _same_path(report.get("output_path"), report_file):
        failures.append("report_output_path_mismatch")

    partition = report.get("partition") if isinstance(report.get("partition"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    markets = partition.get("markets") if isinstance(partition.get("markets"), list) else []
    base_reports = report.get("base_reports") if isinstance(report.get("base_reports"), list) else []
    baseline_trades = report.get("baseline_trades") if isinstance(report.get("baseline_trades"), list) else []
    stress_trades = report.get("stress_trades") if isinstance(report.get("stress_trades"), list) else []

    if partition.get("scan_complete") is not True or summary.get("scan_complete") is not True:
        failures.append("full_scan_not_complete")
    if partition.get("truncated_by_max_rows") is not False:
        failures.append("full_scan_marked_truncated")
    if int(partition.get("rows_read", -1)) != int(manifest.get("rows", -2)):
        failures.append("row_count_manifest_mismatch")
    if int(partition.get("bbo_rows", -1)) != int(partition.get("partitioned_rows", -2)):
        failures.append("bbo_partition_row_mismatch")
    if any(int(partition.get(name, -1)) != 0 for name in ("parse_errors", "invalid_bbo_rows", "non_spot_bbo_rows")):
        failures.append("source_or_bbo_errors_nonzero")
    if partition.get("partition_files_retained") is not False:
        failures.append("temporary_partitions_must_not_be_retained")
    if any("path" in row for row in markets if isinstance(row, dict)):
        failures.append("dead_temporary_partition_paths_published")
    if any(int(row.get("out_of_order", -1)) != 0 for row in markets if isinstance(row, dict)):
        failures.append("per_market_order_violation")

    venues_by_base: dict[str, set[str]] = {}
    for row in markets:
        if isinstance(row, dict):
            venues_by_base.setdefault(str(row.get("base")), set()).add(str(row.get("exchange")))
    expected_matched = sorted(base for base, venues in venues_by_base.items() if venues == {"gateio", "mexc"})
    observed_matched = sorted(str(value) for value in report.get("matched_bases", []))
    if observed_matched != expected_matched:
        failures.append("matched_base_set_mismatch")
    if sorted(str(row.get("base")) for row in base_reports if isinstance(row, dict)) != expected_matched:
        failures.append("base_report_set_mismatch")

    signal_sum = sum(int(row.get("signals", 0)) for row in base_reports if isinstance(row, dict))
    completed_sum = sum(int(row.get("completed_events", 0)) for row in base_reports if isinstance(row, dict))
    incomplete_sum = sum(int(row.get("incomplete_events", 0)) for row in base_reports if isinstance(row, dict))
    if signal_sum != int(summary.get("signals", -1)):
        failures.append("signal_summary_mismatch")
    if completed_sum != int(summary.get("completed_events", -1)):
        failures.append("completed_event_summary_mismatch")
    if incomplete_sum != int(summary.get("incomplete_events", -1)):
        failures.append("incomplete_event_summary_mismatch")
    if len(baseline_trades) != int(summary.get("baseline_trades", -1)):
        failures.append("baseline_trade_summary_mismatch")
    if len(stress_trades) != int(summary.get("stress_trades", -1)):
        failures.append("stress_trade_summary_mismatch")
    if int((validation.get("train") or {}).get("trades", -1)) + int((validation.get("oos") or {}).get("trades", -1)) != len(baseline_trades):
        failures.append("train_oos_trade_partition_mismatch")
    gates = validation.get("gates") if isinstance(validation.get("gates"), dict) else {}
    if bool(validation.get("all_gates_passed")) != all(bool(value) for value in gates.values()):
        failures.append("all_gates_passed_mismatch")

    execution = plan.get("execution") if isinstance(plan.get("execution"), dict) else {}
    fixed_cost = float(execution.get("round_trip_fee_bps", 0)) + float(execution.get("slippage_bps", 0)) + float(execution.get("operational_buffer_bps", 0))
    stress_cost = float(execution.get("round_trip_fee_bps", 0)) * float(execution.get("stress_fee_multiplier", 0)) + float(execution.get("slippage_bps", 0)) * float(execution.get("stress_slippage_multiplier", 0)) + float(execution.get("operational_buffer_bps", 0))
    if abs(fixed_cost - float(execution.get("fixed_total_cost_bps", -1))) > 1e-9:
        failures.append("fixed_cost_math_mismatch")
    if abs(stress_cost - float(execution.get("stress_total_cost_bps", -1))) > 1e-9:
        failures.append("stress_cost_math_mismatch")

    source_path = Path(str(report.get("input_path", "")))
    if not source_path.is_file():
        failures.append("source_file_missing")
        observed_source_fingerprint = None
    else:
        observed_source_fingerprint = sample_file_fingerprint(source_path)
        embedded = report.get("source_fingerprint") if isinstance(report.get("source_fingerprint"), dict) else {}
        for name in ("size_bytes", "sample_bytes", "sample_offsets", "sample_fingerprint_sha256"):
            if embedded.get(name) != observed_source_fingerprint.get(name):
                failures.append(f"source_fingerprint_{name}_mismatch")
        warnings.append("source_binding_uses_sample_fingerprint_not_full_19gb_hash")

    if report.get("decision") == NO_SIGNAL_DECISION:
        if signal_sum != 0 or baseline_trades or stress_trades:
            failures.append("no_signal_decision_contradicts_events")
        audit_decision = "CROSS_VENUE_SPOT_LEAD_LAG_VERIFIED_REJECTED_NO_FIXED_SIGNALS"
    else:
        failures.append("unexpected_report_decision_for_closure_audit")
        audit_decision = "CROSS_VENUE_SPOT_LEAD_LAG_AUDIT_FAILED"

    if failures:
        audit_decision = "CROSS_VENUE_SPOT_LEAD_LAG_AUDIT_FAILED"
    algorithm_file = Path(algorithm_path) if algorithm_path else Path(__file__).with_name("cross_venue_lead_lag.py")
    return {
        "schema": AUDIT_SCHEMA,
        "generated_at": _utc_now(),
        "audit_passed": not failures,
        "decision": audit_decision,
        "failures": failures,
        "warnings": warnings,
        "strategy_accepted": False,
        "paper_forward_ready": False,
        "report_path": str(report_file),
        "report_sha256": report_hash,
        "manifest_path": str(manifest_file),
        "manifest_sha256": manifest_hash,
        "plan_path": str(plan_file),
        "plan_sha256": plan_hash,
        "algorithm_path": str(algorithm_file),
        "algorithm_sha256": _sha256(algorithm_file),
        "source_fingerprint": observed_source_fingerprint,
        "evidence": {
            "rows": int(partition.get("rows_read", 0)),
            "bbo_rows": int(partition.get("bbo_rows", 0)),
            "markets": len(markets),
            "matched_bases": expected_matched,
            "span_hours": float(summary.get("span_hours", 0)),
            "signals": signal_sum,
            "baseline_trades": len(baseline_trades),
            "stress_trades": len(stress_trades),
            "fixed_total_cost_bps": fixed_cost,
            "stress_total_cost_bps": stress_cost,
        },
        "next_step": "Close this fixed branch without tuning and select a genuinely different existing-data hypothesis PlanOnly." if not failures else "Fix audit failures before using this artifact as evidence.",
    }


def run_lead_lag_audit(
    report_path: str | Path,
    manifest_path: str | Path,
    plan_path: str | Path,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    audit = build_lead_lag_audit(report_path, manifest_path, plan_path, **kwargs)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed audit for a fixed cross-venue spot lead/lag full scan.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--algorithm")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit = run_lead_lag_audit(
        args.report,
        args.manifest,
        args.plan,
        args.output,
        expected_plan_sha256=args.expected_plan_sha256,
        algorithm_path=args.algorithm,
    )
    print(json.dumps({"output": args.output, "decision": audit["decision"], "audit_passed": audit["audit_passed"], "failures": audit["failures"]}, ensure_ascii=False, indent=2))
    return 0 if audit["audit_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
