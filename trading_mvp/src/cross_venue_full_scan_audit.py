from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERIFIED_REJECTION = "CROSS_VENUE_SPOT_FULL_SCAN_VERIFIED_REJECTED_NO_NET_EDGE_AFTER_BASE_COSTS"
VERIFIED_CANDIDATES = "CROSS_VENUE_SPOT_FULL_SCAN_VERIFIED_CANDIDATES_REQUIRE_OOS"
INVALID_EVIDENCE = "CROSS_VENUE_SPOT_FULL_SCAN_AUDIT_REJECTED_INVALID_EVIDENCE"


@dataclass(frozen=True)
class CrossVenueFullScanAuditConfig:
    expected_round_trip_fee_bps: float = 39.0
    expected_slippage_bps: float = 10.0
    expected_inventory_buffer_bps: float = 20.0
    expected_min_top_notional_quote: float = 25.0
    expected_min_rows: int = 1
    sample_bytes: int = 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
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


def sample_file_fingerprint(path: str | Path, sample_bytes: int = 1024 * 1024) -> dict[str, Any]:
    source = Path(path)
    if sample_bytes <= 0:
        raise ValueError("sample_bytes must be positive")
    size = source.stat().st_size
    width = min(sample_bytes, size)
    offsets = sorted({0, max((size - width) // 2, 0), max(size - width, 0)})
    digest = hashlib.sha256()
    digest.update(f"size:{size};width:{width};".encode("ascii"))
    with source.open("rb") as handle:
        for offset in offsets:
            handle.seek(offset)
            data = handle.read(width)
            digest.update(f"offset:{offset};length:{len(data)};".encode("ascii"))
            digest.update(data)
    return {
        "path": str(source),
        "size_bytes": size,
        "sample_bytes": width,
        "sample_offsets": offsets,
        "sample_fingerprint_sha256": digest.hexdigest(),
        "note": "Sample fingerprint binds size plus first/middle/last chunks; it is not a full-file hash.",
    }


def _portable_name(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _float(value: Any) -> float:
    return float(value)


def _close(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def _candidate_math_failures(candidate: dict[str, Any], total_cost_bps: float, index: int) -> list[str]:
    failures: list[str] = []
    prefix = f"top_candidates[{index}]"
    try:
        buy_ask = _float(candidate["buy_ask"])
        buy_qty = _float(candidate["buy_ask_qty"])
        sell_bid = _float(candidate["sell_bid"])
        sell_qty = _float(candidate["sell_bid_qty"])
        gross = (sell_bid / buy_ask - 1.0) * 10000.0
        net = gross - total_cost_bps
        capacity = min(buy_ask * buy_qty, sell_bid * sell_qty)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        return [f"{prefix}_invalid_fields:{exc}"]

    if buy_ask <= 0 or sell_bid <= 0 or buy_qty < 0 or sell_qty < 0:
        failures.append(f"{prefix}_non_positive_price_or_negative_quantity")
    if not _close(candidate.get("gross_edge_bps"), gross, 1e-8):
        failures.append(f"{prefix}_gross_edge_math_mismatch")
    if not _close(candidate.get("net_edge_bps"), net, 1e-8):
        failures.append(f"{prefix}_net_edge_math_mismatch")
    if not _close(candidate.get("capacity_quote"), capacity, 1e-8):
        failures.append(f"{prefix}_capacity_math_mismatch")
    if not _close(candidate.get("total_cost_bps"), total_cost_bps, 1e-9):
        failures.append(f"{prefix}_cost_mismatch")
    if not bool(candidate.get("fresh")):
        failures.append(f"{prefix}_not_fresh")
    return failures


def build_cross_venue_full_scan_audit(
    report_path: str | Path,
    manifest_path: str | Path,
    source_path: str | Path,
    *,
    legacy_source_path: str | Path | None = None,
    cfg: CrossVenueFullScanAuditConfig | None = None,
) -> dict[str, Any]:
    config = cfg or CrossVenueFullScanAuditConfig()
    report_file = Path(report_path)
    manifest_file = Path(manifest_path)
    source_file = Path(source_path)
    failures: list[str] = []
    warnings: list[str] = []

    for label, path in (("report", report_file), ("manifest", manifest_file), ("source", source_file)):
        if not path.is_file():
            failures.append(f"{label}_file_missing:{path}")
    if failures:
        return _invalid_result(config, report_file, manifest_file, source_file, failures, warnings)

    try:
        report = _load_json(report_file)
        manifest = _load_json(manifest_file)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        failures.append(f"json_load_failed:{exc}")
        return _invalid_result(config, report_file, manifest_file, source_file, failures, warnings)

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    manifest_summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    report_config = report.get("config") if isinstance(report.get("config"), dict) else {}
    cost_model = report.get("cost_model") if isinstance(report.get("cost_model"), dict) else {}
    markets = report.get("markets") if isinstance(report.get("markets"), dict) else {}
    candidates = report.get("top_candidates") if isinstance(report.get("top_candidates"), list) else []
    top_eligible = report.get("top_eligible") if isinstance(report.get("top_eligible"), list) else []

    if manifest.get("schema") != "cross_venue_dislocation_full_scan_manifest_v1":
        failures.append("manifest_schema_mismatch")
    if manifest.get("final") is not True or manifest.get("status") != "READY_FOR_POSTPROCESS":
        failures.append("manifest_not_final_ready_for_postprocess")
    if int(manifest.get("exit_code", -1)) != 0:
        failures.append("manifest_exit_code_nonzero")
    if report.get("mode") != "cross_venue_dislocation_planonly_research":
        failures.append("report_mode_mismatch")
    if report.get("research_only") is not True or manifest.get("research_only") is not True:
        failures.append("research_only_flag_missing")
    for label, payload in (("report", report), ("manifest", manifest)):
        if payload.get("live_orders") is not False:
            failures.append(f"{label}_live_orders_not_false")
        if payload.get("api_keys") is not False:
            failures.append(f"{label}_api_keys_not_false")
        if payload.get("leverage_or_margin") is not False:
            failures.append(f"{label}_leverage_or_margin_not_false")

    if set(markets) != {"gateio", "mexc"}:
        failures.append("market_exchange_set_mismatch")
    if _portable_name(report.get("input")) != source_file.name:
        failures.append("report_source_basename_mismatch")
    if _portable_name(manifest.get("input_path")) != source_file.name:
        failures.append("manifest_source_basename_mismatch")
    if _portable_name(manifest.get("output_path")) != report_file.name:
        failures.append("manifest_report_basename_mismatch")

    expected_costs = {
        "round_trip_fee_bps": config.expected_round_trip_fee_bps,
        "slippage_bps": config.expected_slippage_bps,
        "inventory_rebalance_buffer_bps": config.expected_inventory_buffer_bps,
        "min_top_notional_quote": config.expected_min_top_notional_quote,
    }
    for name, expected in expected_costs.items():
        if not _close(report_config.get(name), expected):
            failures.append(f"config_{name}_mismatch")
    total_cost_bps = (
        config.expected_round_trip_fee_bps
        + config.expected_slippage_bps
        + config.expected_inventory_buffer_bps
    )
    if not _close(report_config.get("total_cost_bps"), total_cost_bps):
        failures.append("config_total_cost_bps_mismatch")
    if not _close(cost_model.get("total_cost_bps"), total_cost_bps):
        failures.append("cost_model_total_cost_bps_mismatch")
    if int(report_config.get("max_rows", -1)) != 0 or summary.get("scan_complete") is not True:
        failures.append("full_scan_not_complete")
    if int(summary.get("rows_read", 0)) < config.expected_min_rows:
        failures.append("rows_below_expected_minimum")
    if int(summary.get("parse_errors", -1)) != 0:
        failures.append("parse_errors_nonzero")
    if int(summary.get("matched_bases", 0)) <= 0:
        failures.append("no_matched_bases")

    for name in (
        "rows_read",
        "bbo_rows",
        "parse_errors",
        "matched_bases",
        "candidate_events",
        "eligible_events",
    ):
        if manifest_summary.get(name) != summary.get(name):
            failures.append(f"manifest_summary_{name}_mismatch")
    if manifest.get("decision") != report.get("decision"):
        failures.append("manifest_report_decision_mismatch")

    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            failures.append(f"top_candidates[{index}]_not_object")
            continue
        failures.extend(_candidate_math_failures(candidate, total_cost_bps, index))

    gross_values = [float(item["gross_edge_bps"]) for item in candidates if isinstance(item, dict)]
    net_values = [float(item["net_edge_bps"]) for item in candidates if isinstance(item, dict)]
    if gross_values and not _close(summary.get("max_gross_edge_bps"), max(gross_values), 1e-8):
        failures.append("summary_max_gross_edge_mismatch")
    if net_values and not _close(summary.get("max_net_edge_bps"), max(net_values), 1e-8):
        failures.append("summary_max_net_edge_mismatch")

    liquidity_candidates = [
        item
        for item in candidates
        if isinstance(item, dict)
        and float(item.get("capacity_quote", -1.0)) >= config.expected_min_top_notional_quote
    ]
    max_liquidity_gross = max(
        (float(item["gross_edge_bps"]) for item in liquidity_candidates),
        default=None,
    )
    max_liquidity_net = (
        max_liquidity_gross - total_cost_bps if max_liquidity_gross is not None else None
    )
    fee_plus_slippage_bps = config.expected_round_trip_fee_bps + config.expected_slippage_bps
    max_net_without_inventory_buffer = (
        max_liquidity_gross - fee_plus_slippage_bps if max_liquidity_gross is not None else None
    )

    eligible_events = int(summary.get("eligible_events", 0))
    report_is_rejection = report.get("decision") == "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES"
    if eligible_events == 0:
        if top_eligible:
            failures.append("top_eligible_nonempty_when_eligible_count_zero")
        if not report_is_rejection:
            failures.append("zero_eligible_events_without_rejection_decision")
    elif report_is_rejection:
        failures.append("rejection_decision_with_positive_eligible_count")

    source_fingerprint = sample_file_fingerprint(source_file, config.sample_bytes)
    legacy_fingerprint: dict[str, Any] | None = None
    source_copy_match: bool | None = None
    if legacy_source_path is not None:
        legacy_file = Path(legacy_source_path)
        if not legacy_file.is_file():
            failures.append(f"legacy_source_file_missing:{legacy_file}")
        else:
            legacy_fingerprint = sample_file_fingerprint(legacy_file, config.sample_bytes)
            source_copy_match = (
                source_fingerprint["size_bytes"] == legacy_fingerprint["size_bytes"]
                and source_fingerprint["sample_fingerprint_sha256"]
                == legacy_fingerprint["sample_fingerprint_sha256"]
            )
            if not source_copy_match:
                failures.append("source_copy_sample_fingerprint_mismatch")
            else:
                warnings.append("source_identity_uses_sample_fingerprint_not_full_file_hash")

    audit_passed = not failures
    if not audit_passed:
        decision = INVALID_EVIDENCE
        branch_verdict = "evidence_invalid"
    elif eligible_events == 0 and (max_liquidity_net is None or max_liquidity_net < 0):
        decision = VERIFIED_REJECTION
        branch_verdict = "rejected"
    else:
        decision = VERIFIED_CANDIDATES
        branch_verdict = "requires_oos_validation"

    economics_failed = branch_verdict == "rejected"
    return {
        "schema": "cross_venue_spot_full_scan_audit_v1",
        "generated_at": _utc_now(),
        "research_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "audit_passed": audit_passed,
        "decision": decision,
        "branch_verdict": branch_verdict,
        "strategy_accepted": False,
        "config": asdict(config),
        "evidence": {
            "report_path": str(report_file),
            "report_sha256": _sha256(report_file),
            "manifest_path": str(manifest_file),
            "manifest_sha256": _sha256(manifest_file),
            "source": source_fingerprint,
            "legacy_source": legacy_fingerprint,
            "source_copy_sample_match": source_copy_match,
        },
        "scan": {
            "run_id": manifest.get("run_id"),
            "rows_read": summary.get("rows_read"),
            "bbo_rows": summary.get("bbo_rows"),
            "matched_bases": summary.get("matched_bases"),
            "candidate_events": summary.get("candidate_events"),
            "eligible_events": eligible_events,
            "scan_complete": summary.get("scan_complete"),
            "report_decision": report.get("decision"),
        },
        "economics": {
            "fixed_total_cost_bps": total_cost_bps,
            "fee_plus_slippage_bps": fee_plus_slippage_bps,
            "min_top_notional_quote": config.expected_min_top_notional_quote,
            "retained_candidate_count": len(candidates),
            "liquidity_qualified_retained_count": len(liquidity_candidates),
            "max_all_fresh_gross_edge_bps": max(gross_values, default=None),
            "max_liquidity_qualified_gross_edge_bps": max_liquidity_gross,
            "max_liquidity_qualified_net_edge_bps": max_liquidity_net,
            "max_net_without_inventory_buffer_bps": max_net_without_inventory_buffer,
            "inventory_buffer_needed_for_rejection": bool(
                max_net_without_inventory_buffer is not None
                and max_net_without_inventory_buffer >= 0
            ),
        },
        "proof_gates": {
            "economics": "failed" if economics_failed else "passed_to_validation",
            "oos": "not_reached_economics_screen_failed" if economics_failed else "required",
            "walk_forward": "not_reached_economics_screen_failed" if economics_failed else "required",
            "stress": "base_cost_and_no_inventory_buffer_sensitivity_failed"
            if economics_failed and max_net_without_inventory_buffer is not None and max_net_without_inventory_buffer < 0
            else ("not_reached_economics_screen_failed" if economics_failed else "required"),
            "paper_forward": "blocked",
        },
        "failures": failures,
        "warnings": warnings,
        "next_step": (
            "Close this spot branch and select a new structural hypothesis using existing data; do not rerun, grid-tune, or paper-trade it."
            if branch_verdict == "rejected"
            else "Repair invalid evidence before any branch decision."
            if branch_verdict == "evidence_invalid"
            else "Freeze the event protocol before OOS/walk-forward/stress validation; no grid or live execution."
        ),
    }


def _invalid_result(
    config: CrossVenueFullScanAuditConfig,
    report_file: Path,
    manifest_file: Path,
    source_file: Path,
    failures: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema": "cross_venue_spot_full_scan_audit_v1",
        "generated_at": _utc_now(),
        "research_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "audit_passed": False,
        "decision": INVALID_EVIDENCE,
        "branch_verdict": "evidence_invalid",
        "strategy_accepted": False,
        "config": asdict(config),
        "evidence": {
            "report_path": str(report_file),
            "manifest_path": str(manifest_file),
            "source_path": str(source_file),
        },
        "failures": failures,
        "warnings": warnings,
        "next_step": "Repair invalid evidence before any branch decision.",
    }


def run_cross_venue_full_scan_audit(
    report_path: str | Path,
    manifest_path: str | Path,
    source_path: str | Path,
    output_path: str | Path,
    *,
    legacy_source_path: str | Path | None = None,
    cfg: CrossVenueFullScanAuditConfig | None = None,
) -> dict[str, Any]:
    result = build_cross_venue_full_scan_audit(
        report_path,
        manifest_path,
        source_path,
        legacy_source_path=legacy_source_path,
        cfg=cfg,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    result["output_path"] = str(target)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed audit of the completed MEXC/Gate spot full scan.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--legacy-source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-min-rows", type=int, default=1)
    parser.add_argument("--sample-bytes", type=int, default=1024 * 1024)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_cross_venue_full_scan_audit(
        args.report,
        args.manifest,
        args.source,
        args.output,
        legacy_source_path=args.legacy_source,
        cfg=CrossVenueFullScanAuditConfig(
            expected_min_rows=args.expected_min_rows,
            sample_bytes=args.sample_bytes,
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["audit_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
