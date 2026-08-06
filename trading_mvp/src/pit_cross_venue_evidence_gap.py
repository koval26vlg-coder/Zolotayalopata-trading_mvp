from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCREEN_SCHEMA = "pit_linear_perp_cross_venue_screen_v1"
SCREEN_MODE = "pit_linear_perp_cross_venue_screen_planonly"
GAP_SCHEMA = "pit_linear_perp_cross_venue_evidence_gap_v1"


def build_evidence_gap_report(screen_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(screen_path).resolve()
    output = Path(output_path).resolve()
    if output == source:
        raise ValueError("evidence-gap output must not overwrite the screen report")
    if output.exists():
        raise FileExistsError(f"evidence-gap output already exists: {output}")
    screen = _load_json(source)
    _validate_screen(screen)
    summary = _object(screen.get("summary"), "summary")
    per_base = _base_rows(screen.get("per_base"))
    raw_events = int(summary.get("cost_positive_events") or 0)
    per_base_total = sum(int(row.get("cost_positive_events") or 0) for row in per_base)
    if per_base_total != raw_events:
        raise ValueError(f"per_base cost-positive total mismatch: summary={raw_events}, per_base={per_base_total}")

    ranked = sorted(per_base, key=lambda row: int(row.get("cost_positive_events") or 0), reverse=True)
    shares = {
        f"top_{size}_share": _top_share(ranked, raw_events, size)
        for size in (1, 3, 5, 8)
    }
    retained_cycles = int(summary.get("retained_cycles_seen") or 0)
    persistent_threshold = math.ceil(retained_cycles * 0.90) if retained_cycles else 0
    persistent = sorted(
        str(row.get("base") or "")
        for row in per_base
        if persistent_threshold and int(row.get("cost_positive_events") or 0) >= persistent_threshold
    )
    extreme_scale = sorted(
        str(row.get("base") or "")
        for row in per_base
        if _number(row.get("max_gross_edge_bps")) >= 10_000.0
    )
    large_dislocation = sorted(
        str(row.get("base") or "")
        for row in per_base
        if _number(row.get("max_gross_edge_bps")) >= 1_000.0
    )

    if raw_events <= 0:
        decision = "PIT_LINEAR_PERP_SCREEN_EVIDENCE_GAP_REJECTED_NO_RAW_EDGE"
        next_valid_move = "select_new_structural_hypothesis_planonly"
        reasons = ["no_raw_observation_survived_fixed_base_cost_hurdle"]
    else:
        decision = "PIT_LINEAR_PERP_SCREEN_EVIDENCE_GAP_BLOCKED_CONTRACT_IDENTITY_DEPTH_FUNDING"
        next_valid_move = "build_public_contract_identity_depth_funding_availability_preflight_planonly"
        reasons = [
            "raw_price_crosses_are_not_validated_contract_identity_matches",
            "executable_capacity_is_unknown_without_depth_or_bbo_quantity",
            "perp_funding_is_missing_from_economics",
            "single_24h_window_has_no_independent_oos_holdout",
        ]

    report = {
        "schema": GAP_SCHEMA,
        "mode": "pit_linear_perp_cross_venue_evidence_gap_planonly",
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "would_start": False,
        "network_calls": False,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "backtest_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_ready": False,
        "source": {
            "screen_path": str(source),
            "screen_sha256": _sha256(source),
            "screen_decision": screen.get("decision"),
            "mask_sha256": _object(screen.get("source"), "source").get("mask_sha256"),
            "run_id": _object(screen.get("source"), "source").get("run_id"),
        },
        "instrument_scope": screen.get("instrument_scope"),
        "spot_objective_verdict": screen.get("spot_objective_verdict"),
        "raw_observations": {
            "cost_positive_events": raw_events,
            "cost_positive_bases": int(summary.get("cost_positive_bases") or 0),
            "max_gross_edge_bps": summary.get("max_gross_edge_bps"),
            "max_net_screening_edge_bps": summary.get("max_net_screening_edge_bps"),
            "label": "unvalidated_price_cross_observations_not_trade_candidates",
        },
        "validated_candidates": {
            "events": 0,
            "bases": 0,
            "reason": "contract identity, multiplier, executable depth, exact quote age and funding are not verified",
        },
        "concentration": shares,
        "diagnostics": {
            "retained_cycles": retained_cycles,
            "persistent_threshold_cycles": persistent_threshold,
            "persistent_raw_positive_bases": persistent,
            "extreme_price_scale_threshold_bps": 10_000.0,
            "extreme_price_scale_bases": extreme_scale,
            "large_dislocation_threshold_bps": 1_000.0,
            "large_dislocation_bases": large_dislocation,
            "identity_collision_indicator": bool(extreme_scale or persistent),
        },
        "required_evidence": {
            "contract_identity": [
                "canonical underlying identifier",
                "contract multiplier/quanto multiplier",
                "settle and quote asset",
                "contract status and expiry/perpetual flag",
            ],
            "execution": [
                "bid/ask quantity or executable depth at target notional",
                "exchange quote timestamp and collection lag",
                "base/VIP0 fee schedule per venue and leg",
            ],
            "economics": [
                "funding rate, interval and settlement timing on both venues",
                "funding differential during hold",
                "basis convergence/exit rule predeclared before replay",
            ],
            "validation": [
                "chronological OOS holdout",
                "walk-forward folds",
                "fee/slippage/latency/gap stress",
                "venue/base concentration cap",
            ],
        },
        "reasons": reasons,
        "next_valid_move": next_valid_move,
        "blocked_actions": [
            "treat_raw_observations_as_valid_candidates",
            "interpret_as_spot_result",
            "replay_or_backtest",
            "grid_optimization",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ],
        "output_path": str(output),
    }
    _atomic_write(output, report)
    return report


def _validate_screen(screen: dict[str, Any]) -> None:
    if screen.get("schema") != SCREEN_SCHEMA or screen.get("mode") != SCREEN_MODE:
        raise ValueError("input is not a supported PIT linear-perp screen report")
    required_false = (
        "accepted",
        "strategy_accepted",
        "replay_allowed",
        "grid_allowed",
        "backtest_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "oos_ready",
    )
    if any(screen.get(key) is not False for key in required_false):
        raise ValueError("screen safety flags are not fail-closed")
    if screen.get("research_only") is not True or screen.get("screening_only") is not True:
        raise ValueError("screen must be research-only and screening-only")
    scope = _object(screen.get("instrument_scope"), "instrument_scope")
    if scope.get("screened_contract_type") != "linear_perp" or scope.get("supports_spot_objective") is not False:
        raise ValueError("screen instrument scope is unsafe or ambiguous")
    summary = _object(screen.get("summary"), "summary")
    if summary.get("scan_complete") is not True:
        raise ValueError("screen is incomplete")


def _base_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("per_base must be a list of objects")
    return value


def _top_share(rows: list[dict[str, Any]], total: int, size: int) -> float:
    if total <= 0:
        return 0.0
    return sum(int(row.get("cost_positive_events") or 0) for row in rows[:size]) / total


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid screen JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("screen report must be a JSON object")
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
    parser = argparse.ArgumentParser(description="Build a fail-closed PIT linear-perp screening evidence-gap report")
    parser.add_argument("--screen", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = build_evidence_gap_report(args.screen, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
