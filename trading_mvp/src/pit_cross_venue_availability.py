from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCREEN_SCHEMA = "pit_linear_perp_cross_venue_screen_v1"
GAP_SCHEMA = "pit_linear_perp_cross_venue_evidence_gap_v1"
OUTPUT_SCHEMA = "pit_linear_perp_cross_venue_availability_preflight_v1"


def build_availability_report(
    screen_path: str | Path,
    evidence_gap_path: str | Path,
    fee_evidence_dir: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    screen_file = Path(screen_path).resolve()
    gap_file = Path(evidence_gap_path).resolve()
    evidence_dir = Path(fee_evidence_dir).resolve()
    output_file = Path(output_path).resolve()
    if output_file in {screen_file, gap_file}:
        raise ValueError("availability output must not overwrite source evidence")
    if output_file.exists():
        raise FileExistsError(f"availability output already exists: {output_file}")
    screen = _load_json(screen_file, "screen")
    gap = _load_json(gap_file, "evidence gap")
    _validate_inputs(screen, gap)

    raw_bases = sorted(
        str(row.get("base") or "").upper()
        for row in _list_of_objects(screen.get("per_base"), "per_base")
        if int(row.get("cost_positive_events") or 0) > 0
    )
    mexc_path = evidence_dir / "mexc_contract_detail.json"
    gate_path = evidence_dir / "gate_usdt_contracts.json"
    mexc_contracts = _mexc_contract_map(mexc_path) if mexc_path.is_file() else {}
    gate_contracts = _gate_contract_map(gate_path) if gate_path.is_file() else {}
    mexc_bases = {base for base in raw_bases if f"{base}_USDT" in mexc_contracts}
    gate_bases = {base for base in raw_bases if f"{base}_USDT" in gate_contracts}
    both = sorted(mexc_bases & gate_bases)
    missing = sorted(set(raw_bases) - set(both))
    multiplier_rows = []
    for base in both:
        symbol = f"{base}_USDT"
        mexc_item = mexc_contracts[symbol]
        gate_item = gate_contracts[symbol]
        multiplier_rows.append(
            {
                "base": base,
                "symbol": symbol,
                "mexc_contract_size": _float_or_none(mexc_item.get("contractSize")),
                "gate_quanto_multiplier": _float_or_none(gate_item.get("quanto_multiplier")),
                "mexc_concept_plate": list(mexc_item.get("conceptPlate") or []),
                "identity_verified": False,
                "note": "same symbol and multipliers do not prove canonical underlying identity or historical continuity",
            }
        )

    metadata_available = mexc_path.is_file() and gate_path.is_file()
    static_metadata = {
        "available": metadata_available,
        "directory": str(evidence_dir),
        "mexc": _file_info(mexc_path),
        "gateio": _file_info(gate_path),
        "timestamp_aligned_to_screen": False,
        "historical_identity_continuity_proven": False,
        "note": "Static contract files predate or are not bound to every retained cycle and cannot repair historical symbol reuse.",
    }
    screen_gaps = {str(value) for value in (screen.get("evidence_gaps") or [])}
    required_historical_gaps = {
        "bid_ask_quantity_and_executable_capacity_missing",
        "contract_multiplier_and_spec_parity_not_verified",
        "exchange_quote_timestamps_and_subsecond_staleness_missing",
        "funding_rate_and_funding_pnl_missing",
    }
    missing_historical = sorted(required_historical_gaps & screen_gaps)
    raw_events = int(_object(screen.get("summary"), "summary").get("cost_positive_events") or 0)
    if raw_events <= 0:
        decision = "PIT_LINEAR_PERP_CURRENT_DATASET_REJECTED_NO_RAW_EDGE"
        next_valid_move = "select_new_structural_hypothesis_planonly"
    else:
        decision = "PIT_LINEAR_PERP_CURRENT_DATASET_REJECTED_FOR_EDGE_VALIDATION_MISSING_HISTORICAL_EVIDENCE"
        next_valid_move = "park_current_dataset_then_choose_new_hypothesis_or_predeclare_focused_forward_oos_collect"

    report = {
        "schema": OUTPUT_SCHEMA,
        "mode": "pit_linear_perp_cross_venue_availability_preflight_planonly",
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "would_start": False,
        "network_calls": False,
        "collect_started": False,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "backtest_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_ready": False,
        "historical_retrofit_possible": False,
        "source": {
            "screen_path": str(screen_file),
            "screen_sha256": _sha256(screen_file),
            "evidence_gap_path": str(gap_file),
            "evidence_gap_sha256": _sha256(gap_file),
            "run_id": _object(screen.get("source"), "source").get("run_id"),
            "mask_sha256": _object(screen.get("source"), "source").get("mask_sha256"),
            "time_span": screen.get("time_span"),
        },
        "raw_observations": {
            "events": raw_events,
            "bases": raw_bases,
            "label": "discovery_only_unvalidated",
        },
        "validated_candidates": {
            "events": 0,
            "bases": 0,
        },
        "static_metadata": static_metadata,
        "metadata_coverage": {
            "raw_observation_bases": raw_bases,
            "mexc_bases": sorted(mexc_bases),
            "gateio_bases": sorted(gate_bases),
            "both_venues_bases": both,
            "missing_any_venue_bases": missing,
            "contract_rows": multiplier_rows,
        },
        "historical_evidence_missing": missing_historical,
        "why_current_probe_cannot_repair_history": [
            "A current contract metadata response cannot prove the canonical underlying used in each historical cycle.",
            "Historical executable depth and BBO quantity cannot be reconstructed from ticker-only rows.",
            "Historical exchange quote timestamps and collection lag cannot be reconstructed.",
            "Historical funding differential and settlement cashflows are absent from the PIT rows.",
            "The approximately 24h discovery window has no independent chronological holdout.",
        ],
        "future_forward_option": {
            "allowed_now": False,
            "requires_separate_plan_and_explicit_visible_collect_approval": True,
            "discovery_window_must_be_sealed_from_oos": True,
            "minimum_fields": [
                "canonical contract identity and multiplier per venue",
                "timestamped depth and BBO quantity",
                "exchange timestamps and local receive timestamps",
                "funding rate, interval, next settlement and realized funding cashflow",
                "base/VIP0 fees per leg",
            ],
        },
        "next_valid_move": next_valid_move,
        "blocked_actions": [
            "retrofit_or_impute_missing_historical_fields",
            "treat_raw_observations_as_validated_candidates",
            "replay_or_backtest_current_dataset",
            "grid_optimization",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ],
        "output_path": str(output_file),
    }
    _atomic_write(output_file, report)
    return report


def _validate_inputs(screen: dict[str, Any], gap: dict[str, Any]) -> None:
    if screen.get("schema") != SCREEN_SCHEMA or screen.get("mode") != "pit_linear_perp_cross_venue_screen_planonly":
        raise ValueError("unsupported screen report")
    if screen.get("strategy_accepted") is not False or screen.get("replay_allowed") is not False or screen.get("oos_ready") is not False:
        raise ValueError("screen safety flags are not fail-closed")
    if gap.get("schema") != GAP_SCHEMA or gap.get("mode") != "pit_linear_perp_cross_venue_evidence_gap_planonly":
        raise ValueError("unsupported evidence-gap report")
    if gap.get("strategy_accepted") is not False or gap.get("replay_allowed") is not False or gap.get("oos_ready") is not False:
        raise ValueError("evidence-gap safety flags are not fail-closed")
    validated = _object(gap.get("validated_candidates"), "validated_candidates")
    if int(validated.get("events") or 0) != 0:
        raise ValueError("availability preflight requires zero validated candidates at input")


def _mexc_contract_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path, "MEXC contract metadata")
    rows = payload.get("data") or []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def _gate_contract_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Gate contract metadata must be a list")
    return {
        str(row.get("name") or "").upper(): row
        for row in payload
        if isinstance(row, dict) and row.get("name")
    }


def _file_info(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None, "modified_at_utc": None}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": stat.st_size,
        "sha256": _sha256(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_of_objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess whether PIT linear-perp screening gaps can be repaired without new data")
    parser.add_argument("--screen", required=True)
    parser.add_argument("--evidence-gap", required=True)
    parser.add_argument("--fee-evidence-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_availability_report(args.screen, args.evidence_gap, args.fee_evidence_dir, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
