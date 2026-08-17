from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slow_liquidity_provenance import (
    build_input_binding,
    canonical_plan_hash,
    sha256_file,
    state_hash_from_rows,
)


READY_V0_DECISION = "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER"
V1_DECISION = "SLOW_LIQUIDITY_FIXED_V1_COMPRESSION_PLANONLY_READY_FOR_FEATURE_NORMALIZER"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_fixed_compression_v1_plan(
    *,
    history_jsonl_path: Path,
    history_manifest_path: Path,
    fixed_signal_path: Path,
    quality_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    fixed_v0 = load_json(fixed_signal_path)
    manifest = load_json(history_manifest_path)
    quality = load_json(quality_path)
    if fixed_v0.get("decision") != READY_V0_DECISION:
        raise ValueError(
            "fixed v0 PlanOnly is not ready for a versioned compression refreeze: "
            f"{fixed_v0.get('decision')}"
        )
    if manifest.get("final") is not True:
        raise ValueError("history manifest must be final")
    if quality.get("accepted") is not True:
        raise ValueError("history quality artifact must be accepted")

    signal = copy.deepcopy(fixed_v0.get("fixed_signal_v0") or {})
    if not signal:
        raise ValueError("fixed v0 PlanOnly has no fixed_signal_v0 contract")
    signal.update(
        {
            "name": "slow_liquidity_regime_breakout_retest_v1_scaled_compression",
            "version": "v1",
            "compression_metric": "range_width_over_atr_sqrt_lookback",
            "compression_scale": "sqrt(lookback_1h_bars)",
            "compression_formula": (
                "range_width_lookback / "
                "(ATR_same_lookback * sqrt(lookback_1h_bars))"
            ),
            "compression_threshold_is_frozen": True,
            "parameter_change_reason": (
                "dimensionally align a lookback range with same-window volatility; "
                "do not tune the threshold from observed event counts"
            ),
        }
    )

    rows = load_jsonl(history_jsonl_path)
    parent_plan_hash = canonical_plan_hash(fixed_v0)
    input_binding = build_input_binding(
        {
            "history_jsonl": history_jsonl_path,
            "history_manifest": history_manifest_path,
            "fixed_signal_v0": fixed_signal_path,
            "quality": quality_path,
        },
        state_hash=state_hash_from_rows(rows),
        plan_hash=parent_plan_hash,
    )
    clean_slice = copy.deepcopy(fixed_v0.get("clean_slice") or {})
    cost_model = copy.deepcopy(fixed_v0.get("base_fee_cost_model") or {})
    validation_contract = copy.deepcopy(fixed_v0.get("validation_contract") or {})
    result: dict[str, Any] = {
        "mode": "slow_liquidity_fixed_compression_v1_planonly",
        "generated_at": utc_now_iso(),
        "decision": V1_DECISION,
        "selected_branch": "slow_liquidity_regime_breakout_retest",
        "would_start": False,
        "research_only": True,
        "strategy_accepted": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "parent_fixed_signal_path": str(fixed_signal_path),
        "parent_fixed_signal_file_sha256": sha256_file(fixed_signal_path),
        "quality_path": str(quality_path),
        "history_jsonl_path": str(history_jsonl_path),
        "history_manifest_path": str(history_manifest_path),
        "input_binding": input_binding,
        "state_hash": input_binding["state_hash"],
        "clean_slice": clean_slice,
        "fixed_signal_v1": signal,
        "base_fee_cost_model": cost_model,
        "validation_contract": validation_contract,
        "hypothesis_contract": {
            "scope_change": "metric dimensionality only; venue/universe/direction/cost/risk unchanged",
            "threshold_selection": "frozen at the inherited v0 value 1.20",
            "no_data_driven_threshold_selection": True,
            "v0_disposition": "REJECTED_AS_DEGENERATE",
            "replay_allowed": False,
        },
        "blocked_actions": [
            "grid_search",
            "retune_after_event_census_or_replay",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward",
        ],
        "next_valid_moves": [
            "Run the existing feature normalizer once against this immutable v1 contract.",
            "If independent events remain below gate, reject this v1 without threshold tuning.",
            "If gates pass, run one fixed replay then OOS/walk-forward/stress in order.",
        ],
        "output_path": str(output_path) if output_path else "",
    }
    result["plan_hash"] = canonical_plan_hash(result)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a fixed, no-grid slow-liquidity v1 compression PlanOnly."
    )
    parser.add_argument("--history-jsonl", required=True)
    parser.add_argument("--history-manifest", required=True)
    parser.add_argument("--fixed-signal-v0", required=True)
    parser.add_argument("--quality", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = build_fixed_compression_v1_plan(
        history_jsonl_path=Path(args.history_jsonl),
        history_manifest_path=Path(args.history_manifest),
        fixed_signal_path=Path(args.fixed_signal_v0),
        quality_path=Path(args.quality),
        output_path=Path(args.output),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
