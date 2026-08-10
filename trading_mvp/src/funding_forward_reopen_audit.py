from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HYPOTHESIS_ID = "funding_regime_persistence_carry_v2"
INVALID_EVIDENCE = "FUNDING_REOPEN_AUDIT_REJECTED_INVALID_EVIDENCE"
DISTINCT_PLAN_REQUIRED = "CURRENT_CACHE_REQUIRES_MATERIALLY_DISTINCT_PLANONLY"
PLANONLY_REVIEW_READY = "READY_FOR_HASH_BOUND_PLANONLY_REVIEW"
DAY_SEC = 86_400
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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


def _input_ref(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_expected_hash(
    path: Path,
    expected_sha256: str,
    label: str,
    failures: list[str],
) -> dict[str, Any] | None:
    if not path.is_file():
        failures.append(f"{label}_missing:{path}")
        return None
    expected = str(expected_sha256 or "").lower()
    if not SHA256_PATTERN.fullmatch(expected):
        failures.append(f"{label}_expected_sha256_invalid")
        return None
    ref = _input_ref(path)
    if ref["sha256"] != expected:
        failures.append(f"{label}_sha256_mismatch")
    return ref


def _load_container_header(path: Path) -> dict[str, Any]:
    """Read only object metadata before the market-value `rows` array."""
    marker = b'"rows"'
    prefix = bytearray()
    with path.open("rb") as handle:
        while len(prefix) <= 64 * 1024:
            value = handle.read(1)
            if not value:
                break
            prefix.extend(value)
            if prefix.endswith(marker):
                break
    if not prefix.endswith(marker):
        raise ValueError(f"rows marker missing: {path}")
    header_text = bytes(prefix[: -len(marker)]).decode("utf-8-sig").rstrip()
    header_text = re.sub(r",\s*$", "", header_text)
    value = json.loads(header_text + "\n}")
    if not isinstance(value, dict):
        raise ValueError(f"container header is not an object: {path}")
    return value


def _hypothesis_record(bank: dict[str, Any]) -> dict[str, Any] | None:
    records = bank.get("hypotheses")
    if not isinstance(records, list):
        return None
    return next(
        (
            item
            for item in records
            if isinstance(item, dict) and (item.get("id") or item.get("hypothesis_id")) == HYPOTHESIS_ID
        ),
        None,
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _latest_symbol_observation(history: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    track = history.get("symbol_track") if isinstance(history.get("symbol_track"), dict) else {}
    if track.get("symbol") != symbol:
        return None
    observations = [item for item in track.get("observations") or [] if isinstance(item, dict)]
    return max(observations, key=lambda item: str(item.get("stamp") or ""), default=None)


def _invalid_result(failures: list[str], inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    stable = {
        "input_hashes": {name: value["sha256"] for name, value in sorted(inputs.items())},
        "decision": INVALID_EVIDENCE,
        "failures": failures,
    }
    return {
        "schema": "funding_forward_reopen_audit_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": False,
        "decision": INVALID_EVIDENCE,
        "same_strategy_planonly_allowed": False,
        "oos_evaluation_allowed": False,
        "execution_probe_ready": False,
        "new_contract_review_required": False,
        "inputs": inputs,
        "failures": failures,
        "blocking_reasons": [],
        "data_access_audit": {
            "market_file_bytes_hashed": False,
            "market_container_headers_read": False,
            "market_row_arrays_parsed": False,
            "funding_rates_read": False,
            "prices_read": False,
            "returns_or_pnl_read": False,
            "pnl_computed": False,
            "oos_evaluated": False,
            "grid_or_retune": False,
            "network_access": False,
        },
        "deterministic_result_hash": _canonical_hash(stable),
    }


def build_reopen_audit(
    *,
    hypothesis_bank_path: str | Path,
    expected_bank_sha256: str,
    legacy_plan_path: str | Path,
    expected_legacy_plan_sha256: str,
    legacy_closure_path: str | Path,
    expected_legacy_closure_sha256: str,
    current_manifest_path: str | Path,
    expected_current_manifest_sha256: str,
    history_audit_path: str | Path,
    expected_history_audit_sha256: str,
    run_dir: str | Path,
    symbol: str,
) -> dict[str, Any]:
    bank_file = Path(hypothesis_bank_path)
    legacy_plan_file = Path(legacy_plan_path)
    legacy_closure_file = Path(legacy_closure_path)
    current_manifest_file = Path(current_manifest_path)
    history_audit_file = Path(history_audit_path)
    run_root = Path(run_dir)
    failures: list[str] = []
    inputs: dict[str, dict[str, Any]] = {}

    requested_inputs = (
        ("hypothesis_bank", bank_file, expected_bank_sha256),
        ("legacy_plan", legacy_plan_file, expected_legacy_plan_sha256),
        ("legacy_closure", legacy_closure_file, expected_legacy_closure_sha256),
        ("current_manifest", current_manifest_file, expected_current_manifest_sha256),
        ("history_audit", history_audit_file, expected_history_audit_sha256),
    )
    for label, path, expected in requested_inputs:
        ref = _verify_expected_hash(path, expected, label, failures)
        if ref is not None:
            inputs[label] = ref
    if failures:
        return _invalid_result(failures, inputs)

    try:
        bank = _load_json(bank_file)
        legacy_plan = _load_json(legacy_plan_file)
        legacy_closure = _load_json(legacy_closure_file)
        current_manifest = _load_json(current_manifest_file)
        history = _load_json(history_audit_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid_result([f"metadata_load_failed:{exc}"], inputs)

    hypothesis = _hypothesis_record(bank)
    if hypothesis is None:
        failures.append("hypothesis_bank_record_missing")
        minimum_data: dict[str, Any] = {}
    else:
        minimum_data = hypothesis.get("minimum_data") if isinstance(hypothesis.get("minimum_data"), dict) else {}
        if hypothesis.get("status") != "BANKED_NEEDS_NEW_DATA":
            failures.append("hypothesis_bank_status_mismatch")
        if hypothesis.get("required_data_type") != "FUNDING_HISTORY_EXTENSION":
            failures.append("hypothesis_bank_required_data_type_mismatch")

    if legacy_plan.get("schema") != "fast_first_funding_regime_persistence_plan_v2":
        failures.append("legacy_plan_schema_mismatch")
    if legacy_plan.get("mode") != "PlanOnly":
        failures.append("legacy_plan_mode_mismatch")
    if legacy_plan.get("frozen_parameters_no_grid") is not True:
        failures.append("legacy_plan_no_grid_contract_missing")
    legacy_plan_hash = str(legacy_plan.get("plan_hash") or "")
    if not SHA256_PATTERN.fullmatch(legacy_plan_hash):
        failures.append("legacy_plan_hash_invalid")

    if legacy_closure.get("schema") != "funding_regime_persistence_v2_terminal_closure_v1":
        failures.append("legacy_closure_schema_mismatch")
    if legacy_closure.get("status") != "BRANCH_CLOSED_INSUFFICIENT_DATA" or legacy_closure.get("final") is not True:
        failures.append("legacy_closure_not_terminal")
    if legacy_closure.get("hypothesis_id") != HYPOTHESIS_ID:
        failures.append("legacy_closure_hypothesis_mismatch")
    if legacy_closure.get("plan_hash") != legacy_plan_hash:
        failures.append("legacy_plan_closure_hash_mismatch")
    legacy_governance = (
        legacy_closure.get("governance") if isinstance(legacy_closure.get("governance"), dict) else {}
    )
    if legacy_governance.get("retune_allowed") is not False:
        failures.append("legacy_retune_prohibition_missing")

    if current_manifest.get("schema") != "daily_collect_v1":
        failures.append("current_manifest_schema_mismatch")
    if _safe_int(current_manifest.get("error_count"), -1) != 0:
        failures.append("current_manifest_has_errors")
    current_params = (
        current_manifest.get("params") if isinstance(current_manifest.get("params"), dict) else {}
    )
    if current_params.get("exchanges") != ["mexc", "gateio"]:
        failures.append("current_manifest_venue_contract_mismatch")

    if history.get("schema") != "funding_forward_history_audit_v1":
        failures.append("history_audit_schema_mismatch")
    if history.get("audit_passed") is not True:
        failures.append("history_audit_not_passed")
    if history.get("decision") != "OVERLAPPING_SUMMARIES_NOT_INDEPENDENT_EDGE_EVIDENCE":
        failures.append("history_audit_decision_mismatch")
    if history.get("promotion_allowed") is not False:
        failures.append("history_audit_promotion_not_false")
    history_safety = history.get("safety") if isinstance(history.get("safety"), dict) else {}
    for key in ("market_rows_read", "returns_or_pnl_read", "oos_read", "grid_or_retune", "network_access"):
        if history_safety.get(key) is not False:
            failures.append(f"history_audit_safety_mismatch:{key}")

    history_contract = (
        history.get("history_contract") if isinstance(history.get("history_contract"), dict) else {}
    )
    through_stamp = str(history_contract.get("through_stamp") or "")
    history_manifest_ref = (
        history.get("inputs", {}).get(f"manifest_{through_stamp}")
        if isinstance(history.get("inputs"), dict)
        else None
    )
    history_manifest_sha = (
        history_manifest_ref.get("sha256") if isinstance(history_manifest_ref, dict) else None
    )
    if history_manifest_sha != inputs["current_manifest"]["sha256"]:
        failures.append("history_current_manifest_hash_mismatch")

    track = history.get("symbol_track") if isinstance(history.get("symbol_track"), dict) else {}
    if track.get("symbol") != symbol:
        failures.append("history_symbol_mismatch")
    if track.get("identity_status") != "OFFICIAL_SAME_ASSET_VERIFIED":
        failures.append("history_symbol_identity_not_verified")
    latest_observation = _latest_symbol_observation(history, symbol)
    if latest_observation is None or latest_observation.get("pair_present") is not True:
        failures.append("history_latest_symbol_observation_missing")

    statuses = [item for item in current_manifest.get("statuses") or [] if isinstance(item, dict)]
    symbol_statuses = {
        str(item.get("exchange") or ""): item
        for item in statuses
        if item.get("symbol") == symbol and item.get("exchange") in ("mexc", "gateio")
    }
    if set(symbol_statuses) != {"mexc", "gateio"}:
        failures.append("current_manifest_symbol_legs_missing")

    container_headers: dict[str, dict[str, Any]] = {}
    market_paths: dict[str, Path] = {}
    if run_root.is_dir():
        for exchange in ("mexc", "gateio"):
            market_paths[f"{exchange}_klines"] = run_root / exchange / "klines" / f"{symbol}.json"
            market_paths[f"{exchange}_funding"] = run_root / exchange / "funding" / f"{symbol}.json"
    else:
        failures.append(f"run_dir_missing:{run_root}")

    for label, path in market_paths.items():
        if not path.is_file():
            failures.append(f"market_container_missing:{label}:{path}")
            continue
        inputs[label] = _input_ref(path)
        try:
            header = _load_container_header(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"market_container_header_invalid:{label}:{exc}")
            continue
        container_headers[label] = header
        expected_exchange = label.split("_", 1)[0]
        if header.get("exchange") != expected_exchange or header.get("symbol") != symbol:
            failures.append(f"market_container_identity_mismatch:{label}")

    strategy = legacy_plan.get("strategy") if isinstance(legacy_plan.get("strategy"), dict) else {}
    legacy_entry = str(strategy.get("entry") or "")
    required_resolution = "1h" if "1h trade open" in legacy_entry else None
    if required_resolution is None:
        failures.append("legacy_entry_resolution_not_frozen")
    observed_resolutions = sorted(
        {
            str(container_headers[label].get("interval") or "")
            for label in ("mexc_klines", "gateio_klines")
            if label in container_headers
        }
    )

    split = (
        legacy_plan.get("sealed_input", {}).get("split", {})
        if isinstance(legacy_plan.get("sealed_input"), dict)
        else {}
    )
    legacy_oos_end_sec = _safe_int(split.get("oos_end_sec"), -1)
    current_end_sec = _safe_int(current_params.get("end_sec"), -1)
    if legacy_oos_end_sec <= 0 or current_end_sec <= 0:
        failures.append("cache_diff_time_boundary_invalid")

    legacy_execution_required = _safe_int(
        (legacy_plan.get("validation") or {}).get("execution_probe_snapshots_required"),
        -1,
    )
    bank_execution_required = _safe_int(minimum_data.get("execution_snapshots"), -1)
    if legacy_execution_required != bank_execution_required or legacy_execution_required <= 0:
        failures.append("execution_snapshot_requirement_drift")

    if failures:
        return _invalid_result(failures, inputs)

    history_days_required = _safe_int(minimum_data.get("days"), 0)
    history_days_observed = _safe_int(current_params.get("days"), 0)
    settlements_required = _safe_int(minimum_data.get("settlements"), 0)
    settlement_rows = {
        exchange: _safe_int(symbol_statuses[exchange].get("funding_rows"), 0)
        for exchange in ("mexc", "gateio")
    }
    minimum_settlement_rows = min(settlement_rows.values())
    coverage_required = _safe_float(minimum_data.get("dual_leg_coverage"), 0.0)
    inclusive_window_days = _safe_int((history.get("window_overlap") or {}).get("inclusive_window_days"), 0)
    aligned_days = _safe_int(latest_observation.get("aligned_days"), 0)
    aligned_coverage = aligned_days / inclusive_window_days if inclusive_window_days else 0.0
    observed_execution_snapshots = _safe_int(track.get("execution_candidate_presence_count"), 0)

    resolution_passed = observed_resolutions == [required_resolution]
    source_gates = {
        "manifest_quality": {"observed_error_count": 0, "required_error_count": 0, "passed": True},
        "official_same_asset_identity": {
            "observed": track.get("identity_status"),
            "required": "OFFICIAL_SAME_ASSET_VERIFIED",
            "passed": True,
        },
        "history_days": {
            "observed": history_days_observed,
            "required_minimum": history_days_required,
            "passed": history_days_observed >= history_days_required,
        },
        "funding_settlements_per_leg": {
            "observed": settlement_rows,
            "observed_minimum_leg": minimum_settlement_rows,
            "required_minimum": settlements_required,
            "passed": minimum_settlement_rows >= settlements_required,
        },
        "dual_leg_coverage": {
            "source": "latest frozen summary aligned_days / inclusive_window_days",
            "observed": round(aligned_coverage, 6),
            "required_minimum": coverage_required,
            "passed": aligned_coverage >= coverage_required,
        },
        "kline_resolution": {
            "observed": observed_resolutions,
            "required_exact": required_resolution,
            "passed": resolution_passed,
        },
    }
    same_strategy_planonly_allowed = all(bool(gate["passed"]) for gate in source_gates.values())
    execution_probe_ready = observed_execution_snapshots >= legacy_execution_required
    blocking_reasons: list[str] = []
    for gate_name, gate in source_gates.items():
        if not gate["passed"]:
            blocking_reasons.append(f"source_gate_failed:{gate_name}")
    if not resolution_passed:
        blocking_reasons.append(
            f"current_kline_resolution_{'_'.join(observed_resolutions)}_incompatible_with_legacy_{required_resolution}_entry"
        )
    if not execution_probe_ready:
        blocking_reasons.append("execution_snapshots_below_required")

    complete_extension_days = max(0, (current_end_sec - legacy_oos_end_sec) // DAY_SEC)
    cache_diff = {
        "legacy_oos_end_sec": legacy_oos_end_sec,
        "current_cache_end_sec": current_end_sec,
        "complete_days_after_legacy_oos": complete_extension_days,
        "source_contract_changed": True,
        "legacy_market_data_contract": "normalized_1h_candles_plus_funding_events_jsonl",
        "current_market_data_contract": "daily_klines_plus_funding_history_json_containers",
        "same_strategy_source_compatible": resolution_passed,
    }
    execution_gate = {
        "observed_snapshots": observed_execution_snapshots,
        "required_snapshots": legacy_execution_required,
        "passed": execution_probe_ready,
        "note": "One weekly execution summary is one snapshot, not a time series of depth observations.",
    }
    decision = PLANONLY_REVIEW_READY if same_strategy_planonly_allowed else DISTINCT_PLAN_REQUIRED
    new_contract_review_required = not resolution_passed
    data_access_audit = {
        "metadata_json_read": [
            "hypothesis bank",
            "legacy PlanOnly",
            "legacy terminal closure",
            "current collector manifest",
            "current longitudinal summary audit",
        ],
        "market_file_bytes_hashed": True,
        "market_container_headers_read": True,
        "market_row_arrays_parsed": False,
        "funding_rates_read": False,
        "prices_read": False,
        "returns_or_pnl_read": False,
        "pnl_computed": False,
        "oos_evaluated": False,
        "grid_or_retune": False,
        "network_access": False,
    }
    safety = {
        "research_only": True,
        "collector_started": False,
        "oos_started": False,
        "evaluator_started": False,
        "paper_or_live_started": False,
        "private_api_keys_used": False,
        "real_capital_used": False,
        "leverage_or_margin_used": False,
    }
    result_core = {
        "input_hashes": {name: value["sha256"] for name, value in sorted(inputs.items())},
        "decision": decision,
        "same_strategy_planonly_allowed": same_strategy_planonly_allowed,
        "oos_evaluation_allowed": False,
        "execution_probe_ready": execution_probe_ready,
        "new_contract_review_required": new_contract_review_required,
        "cache_diff": cache_diff,
        "source_gates": source_gates,
        "execution_gate": execution_gate,
        "blocking_reasons": blocking_reasons,
        "data_access_audit": data_access_audit,
        "safety": safety,
    }
    return {
        "schema": "funding_forward_reopen_audit_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": True,
        "decision": decision,
        "same_strategy_planonly_allowed": same_strategy_planonly_allowed,
        "oos_evaluation_allowed": False,
        "execution_probe_ready": execution_probe_ready,
        "new_contract_review_required": new_contract_review_required,
        "hypothesis_id": HYPOTHESIS_ID,
        "inputs": inputs,
        "legacy_terminal_state": {
            "plan_hash": legacy_plan_hash,
            "closure_status": legacy_closure.get("status"),
            "verdict": legacy_closure.get("verdict"),
            "observed": legacy_closure.get("observed"),
            "retune_allowed": False,
        },
        "cache_diff": cache_diff,
        "source_gates": source_gates,
        "execution_gate": execution_gate,
        "blocking_reasons": blocking_reasons,
        "next_allowed_action": (
            "REQUEST_MATERIALLY_DISTINCT_DAILY_PLANONLY_REVIEW"
            if new_contract_review_required
            else "FREEZE_HASH_BOUND_NO_GRID_PLANONLY_WITH_OOS_EMBARGO"
        ),
        "data_access_audit": data_access_audit,
        "safety": safety,
        "failures": [],
        "deterministic_result_hash": _canonical_hash(result_core),
    }


def run_reopen_audit(output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    result = build_reopen_audit(**kwargs)
    output = Path(output_path)
    result["output_path"] = str(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = argparse.ArgumentParser(description="Metadata-only funding branch reopening audit")
    parser.add_argument("--hypothesis-bank", required=True)
    parser.add_argument("--expected-bank-sha256", required=True)
    parser.add_argument("--legacy-plan", required=True)
    parser.add_argument("--expected-legacy-plan-sha256", required=True)
    parser.add_argument("--legacy-closure", required=True)
    parser.add_argument("--expected-legacy-closure-sha256", required=True)
    parser.add_argument("--current-manifest", required=True)
    parser.add_argument("--expected-current-manifest-sha256", required=True)
    parser.add_argument("--history-audit", required=True)
    parser.add_argument("--expected-history-audit-sha256", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--symbol", default="AKE_USDT")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = run_reopen_audit(
        output_path=args.out,
        hypothesis_bank_path=args.hypothesis_bank,
        expected_bank_sha256=args.expected_bank_sha256,
        legacy_plan_path=args.legacy_plan,
        expected_legacy_plan_sha256=args.expected_legacy_plan_sha256,
        legacy_closure_path=args.legacy_closure,
        expected_legacy_closure_sha256=args.expected_legacy_closure_sha256,
        current_manifest_path=args.current_manifest,
        expected_current_manifest_sha256=args.expected_current_manifest_sha256,
        history_audit_path=args.history_audit,
        expected_history_audit_sha256=args.expected_history_audit_sha256,
        run_dir=args.run_dir,
        symbol=args.symbol,
    )
    print(
        f"FUNDING_REOPEN_AUDIT decision={result['decision']} "
        f"passed={str(result['audit_passed']).lower()} "
        f"same_strategy_planonly={str(result['same_strategy_planonly_allowed']).lower()} "
        f"oos_allowed={str(result['oos_evaluation_allowed']).lower()} "
        f"hash={result['deterministic_result_hash']} out={args.out}"
    )
    return 0 if result["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
