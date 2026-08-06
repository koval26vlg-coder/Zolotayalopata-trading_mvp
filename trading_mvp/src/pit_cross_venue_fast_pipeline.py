from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pit_cross_venue_diagnostic_freeze import FREEZE_DECISION, FREEZE_MODE, FREEZE_SCHEMA
from pit_cross_venue_forward_collector import _load_plan, _scan_segments, _sha256_file


FAST_SCHEMA = "pit_linear_perp_cross_venue_fast_pipeline_v1"
FAST_MODE = "pit_linear_perp_cross_venue_fast_first_offline_gate"
DECISION_READY = "PIT_LINEAR_PERP_FAST_GATE_READY_FOR_SHORT_EXECUTION_PROBE_PLANONLY"
DECISION_REJECT_NO_EDGE = "PIT_LINEAR_PERP_FAST_GATE_REJECTED_NO_FIXED_COST_EDGE"
DECISION_REJECT_GATES = "PIT_LINEAR_PERP_FAST_GATE_REJECTED_DIAGNOSTIC_GATES"


@dataclass(frozen=True)
class FastGateConfig:
    min_attempt_cycles: int = 60
    max_failed_cycle_ratio: float = 0.35
    min_fully_valid_observations: int = 500
    min_fixed_cost_positive_observations: int = 20
    independence_gap_cycles: int = 6
    min_independent_episodes: int = 10
    min_event_bases: int = 3
    max_top1_episode_concentration: float = 0.50
    max_top3_episode_concentration: float = 0.80
    time_block_count: int = 4
    min_active_time_blocks: int = 2
    min_second_half_rate_ratio: float = 0.25
    max_short_probe_bases: int = 5
    min_candidate_episodes: int = 2

    def validate(self) -> None:
        positive = {
            "min_attempt_cycles": self.min_attempt_cycles,
            "min_fully_valid_observations": self.min_fully_valid_observations,
            "min_fixed_cost_positive_observations": self.min_fixed_cost_positive_observations,
            "independence_gap_cycles": self.independence_gap_cycles,
            "min_independent_episodes": self.min_independent_episodes,
            "min_event_bases": self.min_event_bases,
            "time_block_count": self.time_block_count,
            "min_active_time_blocks": self.min_active_time_blocks,
            "max_short_probe_bases": self.max_short_probe_bases,
            "min_candidate_episodes": self.min_candidate_episodes,
        }
        invalid = [name for name, value in positive.items() if int(value) <= 0]
        if invalid:
            raise ValueError(f"fast gate integer parameters must be positive: {', '.join(invalid)}")
        ratios = {
            "max_failed_cycle_ratio": self.max_failed_cycle_ratio,
            "max_top1_episode_concentration": self.max_top1_episode_concentration,
            "max_top3_episode_concentration": self.max_top3_episode_concentration,
            "min_second_half_rate_ratio": self.min_second_half_rate_ratio,
        }
        invalid_ratios = [name for name, value in ratios.items() if not 0 <= float(value) <= 1]
        if invalid_ratios:
            raise ValueError(f"fast gate ratios must be in [0, 1]: {', '.join(invalid_ratios)}")
        if self.min_active_time_blocks > self.time_block_count:
            raise ValueError("min_active_time_blocks exceeds time_block_count")


def run_fast_pipeline(
    freeze_path: str | Path,
    output_path: str | Path,
    config: FastGateConfig | None = None,
) -> dict[str, Any]:
    cfg = config or FastGateConfig()
    cfg.validate()
    source = Path(freeze_path).resolve()
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError(f"fast pipeline output already exists: {destination}")
    freeze = _load_json(source)
    _validate_freeze(freeze)

    provenance = freeze["source"]
    plan_path = Path(str(provenance["plan_path"])).resolve()
    plan = _load_plan(plan_path)
    if _sha256_file(plan_path) != provenance["plan_sha256"]:
        raise ValueError("diagnostic freeze plan hash changed")
    run_dir = Path(str(provenance["run_dir"])).resolve()
    segment_dir = Path(str(provenance["segments_dir"])).resolve()
    universe = plan["sealed_universe"]
    contract = plan["collection_contract"]
    run_id = str(provenance["run_id"])
    scan = _scan_segments(
        segment_dir,
        run_id,
        str(provenance["plan_sha256"]),
        list(universe["all_discovery_bases"]),
        set(universe["identity_evaluation_bases"]),
        int(contract["min_valid_pairs_per_cycle"]),
    )
    if scan["segment_chain_sha256"] != provenance["segment_chain_sha256"]:
        raise ValueError("diagnostic freeze segment chain changed")
    if int(scan["attempt_cycle_count"]) != int(freeze["counts"]["attempt_cycles"]):
        raise ValueError("diagnostic freeze attempt count changed")

    observations = _read_observations(segment_dir, set(universe["identity_evaluation_bases"]))
    diagnostics = evaluate_observations(
        observations,
        attempt_cycles=int(scan["attempt_cycle_count"]),
        failed_cycles=int(scan["failed_cycle_count"]),
        config=cfg,
    )
    fixed_cost_bps = float((plan.get("cost_contract") or {}).get("probe_total_cost_bps") or 0.0)
    if fixed_cost_bps <= 0:
        raise ValueError("sealed plan fixed cost hurdle is missing")

    reasons = list(diagnostics["eligibility_reasons"])
    positive = int(diagnostics["fixed_cost_positive_observations"])
    if positive == 0:
        decision = DECISION_REJECT_NO_EDGE
    elif reasons:
        decision = DECISION_REJECT_GATES
    else:
        decision = DECISION_READY

    report: dict[str, Any] = {
        "schema": FAST_SCHEMA,
        "mode": FAST_MODE,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "strategy_accepted": False,
        "oos_evidence": False,
        "expectancy_claim_allowed": False,
        "would_start_collect": False,
        "source": {
            "diagnostic_freeze_path": str(source),
            "diagnostic_freeze_sha256": _sha256_file(source),
            "run_id": run_id,
            "segment_chain_sha256": scan["segment_chain_sha256"],
            "dataset_role": "diagnostic_only",
        },
        "sealed_config": asdict(cfg),
        "cost_gate": {
            "fixed_total_cost_bps": fixed_cost_bps,
            "positive_definition": "fully_valid identity pair AND max_net_screening_edge_bps > 0",
            "fee_tier": "base/VIP0 plus conservative slippage and operational stress from sealed plan",
            "parameter_grid_allowed": False,
        },
        "diagnostics": diagnostics,
        "short_probe_contract": _short_probe_contract(diagnostics) if decision == DECISION_READY else None,
        "final_validation_contract": {
            "only_after_short_probe_pass": True,
            "minimum_independent_oos_events": 100,
            "sequential_checkpoint_events": [30, 60, 100],
            "early_futility": "stop when one-sided 95% upper confidence bound for net expectancy is <= 0",
            "success": (
                "at >=100 independent OOS events require lower 95% confidence bound for net expectancy > 0, "
                "profit_factor >= 1.2, walk_forward_pass_ratio >= 0.6 and concentration caps"
            ),
            "maximum_duration_is_safety_cap_not_primary_target": True,
            "paper_forward_before_live": True,
        },
        "blocked_actions": [
            "treat_diagnostic_data_as_oos",
            "grid_tuning",
            "strategy_acceptance",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ],
        "next_valid_move": (
            "build_short_execution_probe_planonly" if decision == DECISION_READY else "reject_or_rescope_branch_offline"
        ),
        "output_path": str(destination),
    }
    _atomic_write_json(destination, report)
    return report


def evaluate_observations(
    observations: list[dict[str, Any]],
    *,
    attempt_cycles: int,
    failed_cycles: int,
    config: FastGateConfig,
) -> dict[str, Any]:
    config.validate()
    if attempt_cycles <= 0 or failed_cycles < 0 or failed_cycles > attempt_cycles:
        raise ValueError("invalid attempt/failed cycle counts")
    valid_rows = [row for row in observations if row.get("fully_valid") is True and _finite(row.get("net_bps"))]
    positive_rows = [row for row in valid_rows if float(row["net_bps"]) > 0]
    episodes = _build_episodes(positive_rows, config.independence_gap_cycles)

    episode_counts = Counter(str(event["base"]) for event in episodes)
    total_episodes = len(episodes)
    ranked_episode_counts = sorted(episode_counts.values(), reverse=True)
    top1 = ranked_episode_counts[0] / total_episodes if total_episodes else 0.0
    top3 = sum(ranked_episode_counts[:3]) / total_episodes if total_episodes else 0.0
    active_blocks = sorted(
        {
            min(config.time_block_count - 1, ((int(event["start_cycle"]) - 1) * config.time_block_count) // attempt_cycles)
            for event in episodes
        }
    )

    half = max(1, math.ceil(attempt_cycles / 2))
    first_valid = [row for row in valid_rows if int(row["cycle"]) <= half]
    second_valid = [row for row in valid_rows if int(row["cycle"]) > half]
    first_positive = [row for row in positive_rows if int(row["cycle"]) <= half]
    second_positive = [row for row in positive_rows if int(row["cycle"]) > half]
    first_rate = len(first_positive) / len(first_valid) if first_valid else 0.0
    second_rate = len(second_positive) / len(second_valid) if second_valid else 0.0
    rate_ratio = second_rate / first_rate if first_rate > 0 else (1.0 if second_rate > 0 else 0.0)

    failed_ratio = failed_cycles / attempt_cycles
    reasons: list[str] = []
    checks = (
        (attempt_cycles >= config.min_attempt_cycles, "insufficient_attempt_cycles"),
        (failed_ratio <= config.max_failed_cycle_ratio, "failed_cycle_ratio_above_cap"),
        (len(valid_rows) >= config.min_fully_valid_observations, "insufficient_fully_valid_observations"),
        (
            len(positive_rows) >= config.min_fixed_cost_positive_observations,
            "insufficient_fixed_cost_positive_observations",
        ),
        (total_episodes >= config.min_independent_episodes, "insufficient_independent_episodes"),
        (len(episode_counts) >= config.min_event_bases, "insufficient_event_base_diversity"),
        (top1 <= config.max_top1_episode_concentration, "top1_episode_concentration_above_cap"),
        (top3 <= config.max_top3_episode_concentration, "top3_episode_concentration_above_cap"),
        (len(active_blocks) >= config.min_active_time_blocks, "insufficient_time_block_coverage"),
        (rate_ratio >= config.min_second_half_rate_ratio, "second_half_positive_rate_collapse"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)

    per_base: list[dict[str, Any]] = []
    positives_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in positive_rows:
        positives_by_base[str(row["base"])].append(row)
    for base, rows in positives_by_base.items():
        base_episodes = [event for event in episodes if event["base"] == base]
        nets = [float(row["net_bps"]) for row in rows]
        per_base.append(
            {
                "base": base,
                "positive_observations": len(rows),
                "independent_episodes": len(base_episodes),
                "median_net_bps": statistics.median(nets),
                "max_net_bps": max(nets),
                "directions": sorted({str(row["direction"]) for row in rows}),
            }
        )
    per_base.sort(
        key=lambda row: (
            -int(row["independent_episodes"]),
            -int(row["positive_observations"]),
            -float(row["median_net_bps"]),
            str(row["base"]),
        )
    )
    candidates = [
        row["base"]
        for row in per_base
        if int(row["independent_episodes"]) >= config.min_candidate_episodes
    ][: config.max_short_probe_bases]

    return {
        "attempt_cycles": attempt_cycles,
        "valid_cycles_estimate": attempt_cycles - failed_cycles,
        "failed_cycles": failed_cycles,
        "failed_cycle_ratio": failed_ratio,
        "fully_valid_observations": len(valid_rows),
        "fixed_cost_positive_observations": len(positive_rows),
        "fixed_cost_positive_rate": len(positive_rows) / len(valid_rows) if valid_rows else 0.0,
        "independent_episodes": total_episodes,
        "event_bases": len(episode_counts),
        "top1_episode_concentration": top1,
        "top3_episode_concentration": top3,
        "active_time_blocks": active_blocks,
        "first_half_positive_rate": first_rate,
        "second_half_positive_rate": second_rate,
        "second_to_first_positive_rate_ratio": rate_ratio,
        "eligible_for_short_probe": not reasons,
        "eligibility_reasons": reasons,
        "candidate_bases": candidates,
        "per_base": per_base,
        "episodes": episodes,
    }


def _read_observations(segment_dir: Path, identity_bases: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(segment_dir.glob("cycle_*.json")):
        segment = _load_json(path)
        cycle = int(segment.get("attempt_cycle") or 0)
        for pair in segment.get("pairs") or []:
            if not isinstance(pair, dict) or str(pair.get("base") or "") not in identity_bases:
                continue
            gross = pair.get("gross_execution_edges") or {}
            direction = "unknown"
            if gross:
                direction = max(gross, key=lambda key: float(gross[key]) if _finite(gross[key]) else -math.inf)
            rows.append(
                {
                    "cycle": cycle,
                    "timestamp": segment.get("cycle_finished_at_utc"),
                    "base": str(pair.get("base") or ""),
                    "direction": direction,
                    "fully_valid": pair.get("fully_valid") is True,
                    "net_bps": pair.get("max_net_screening_edge_bps"),
                    "observed_base_fee_net_bps": pair.get("max_net_observed_base_fee_bps"),
                }
            )
    return rows


def _build_episodes(positive_rows: list[dict[str, Any]], gap_cycles: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in positive_rows:
        grouped[(str(row["base"]), str(row["direction"]))].append(row)
    episodes: list[dict[str, Any]] = []
    for (base, direction), rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: int(row["cycle"]))
        current: list[dict[str, Any]] = []
        previous_cycle: int | None = None
        for row in ordered:
            cycle = int(row["cycle"])
            if current and previous_cycle is not None and cycle - previous_cycle >= gap_cycles:
                episodes.append(_episode_payload(base, direction, current))
                current = []
            current.append(row)
            previous_cycle = cycle
        if current:
            episodes.append(_episode_payload(base, direction, current))
    episodes.sort(key=lambda event: (int(event["start_cycle"]), str(event["base"]), str(event["direction"])))
    return episodes


def _episode_payload(base: str, direction: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [float(row["net_bps"]) for row in rows]
    return {
        "base": base,
        "direction": direction,
        "start_cycle": int(rows[0]["cycle"]),
        "end_cycle": int(rows[-1]["cycle"]),
        "positive_observations": len(rows),
        "median_net_bps": statistics.median(nets),
        "max_net_bps": max(nets),
    }


def _short_probe_contract(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_bases": diagnostics["candidate_bases"],
        "selection_role": "diagnostic discovery only; short probe is the first independent forward sample",
        "public_data_only": True,
        "interval_sec": 5,
        "min_duration_sec": 3600,
        "max_duration_sec": 10800,
        "target_valid_samples": 1000,
        "early_quality_checkpoint_sec": 900,
        "early_futility_checkpoint_sec": 1800,
        "min_valid_sample_ratio": 0.70,
        "max_fetch_error_ratio": 0.10,
        "early_futility": "stop after 30 minutes if zero fixed-cost-positive samples or valid ratio < 0.70",
        "success_for_full_evaluation": (
            "at least 30 independent executable episodes, no top1 base concentration above 0.50, "
            "and positive opportunities present in both chronological halves"
        ),
        "live_orders": False,
        "api_keys": False,
    }


def _validate_freeze(value: dict[str, Any]) -> None:
    if value.get("schema") != FREEZE_SCHEMA or value.get("mode") != FREEZE_MODE:
        raise ValueError("unsupported diagnostic freeze schema/mode")
    if value.get("decision") != FREEZE_DECISION or value.get("dataset_role") != "diagnostic_only":
        raise ValueError("diagnostic-only freeze decision required")
    if value.get("integrity_verified") is not True:
        raise ValueError("diagnostic freeze integrity must be verified")
    safety = value.get("safety") or {}
    if safety.get("oos_evidence") is not False or safety.get("strategy_accepted") is not False:
        raise ValueError("diagnostic freeze safety flags are not fail-closed")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fast-first offline gate on diagnostic cross-venue data")
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_fast_pipeline(args.freeze, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
