from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pit_cross_venue_forward_collector import (
    MANIFEST_MODE,
    MANIFEST_SCHEMA,
    _load_plan,
    _scan_segments,
    _sha256_file,
)


FREEZE_SCHEMA = "pit_linear_perp_cross_venue_diagnostic_freeze_v1"
FREEZE_MODE = "pit_linear_perp_cross_venue_incomplete_dataset_freeze"
FREEZE_DECISION = "PIT_LINEAR_PERP_INCOMPLETE_DATASET_DECLARED_DIAGNOSTIC_ONLY"


def freeze_incomplete_run(
    plan_path: str | Path,
    run_dir: str | Path,
    output_path: str | Path,
    *,
    reason: str,
) -> dict[str, Any]:
    plan_file = Path(plan_path).resolve()
    source_dir = Path(run_dir).resolve()
    destination = Path(output_path).resolve()
    if destination.exists():
        raise FileExistsError(f"diagnostic freeze already exists: {destination}")
    if not reason.strip():
        raise ValueError("diagnostic freeze reason is required")

    plan = _load_plan(plan_file)
    manifest_path = source_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("mode") != MANIFEST_MODE:
        raise ValueError("unsupported forward run manifest schema/mode")
    if manifest.get("final") is True or manifest.get("quality_complete") is True:
        raise ValueError("only an incomplete non-quality-complete run may be frozen as diagnostic")

    run_id = str(manifest.get("run_id") or "")
    if not run_id:
        raise ValueError("forward run manifest is missing run_id")
    expected_plan_hash = _sha256_file(plan_file)
    if str(manifest.get("plan_sha256") or "") != expected_plan_hash:
        raise ValueError("forward run manifest plan binding mismatch")

    universe = plan["sealed_universe"]
    contract = plan["collection_contract"]
    segment_dir = source_dir / "segments"
    scan = _scan_segments(
        segment_dir,
        run_id,
        expected_plan_hash,
        list(universe["all_discovery_bases"]),
        set(universe["identity_evaluation_bases"]),
        int(contract["min_valid_pairs_per_cycle"]),
    )
    if int(scan["attempt_cycle_count"]) <= 0:
        raise ValueError("cannot freeze an incomplete run without immutable segments")

    comparable = (
        "attempt_cycle_count",
        "valid_cycle_count",
        "failed_cycle_count",
        "pair_rows",
        "cost_positive_observations",
        "observed_base_fee_cost_positive_observations",
        "segment_chain_sha256",
    )
    mismatches = [name for name in comparable if manifest.get(name) != scan.get(name)]
    if mismatches:
        raise ValueError(f"manifest/segment scan mismatch: {', '.join(mismatches)}")

    segment_files = sorted(segment_dir.glob("cycle_*.json"))
    last_segment = segment_files[-1]
    last_payload = _load_json(last_segment)
    report: dict[str, Any] = {
        "schema": FREEZE_SCHEMA,
        "mode": FREEZE_MODE,
        "decision": FREEZE_DECISION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": reason.strip(),
        "dataset_role": "diagnostic_only",
        "integrity_verified": True,
        "source": {
            "run_id": run_id,
            "run_dir": str(source_dir),
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256_file(manifest_path),
            "plan_path": str(plan_file),
            "plan_sha256": expected_plan_hash,
            "segments_dir": str(segment_dir),
            "segment_chain_sha256": scan["segment_chain_sha256"],
            "last_segment_path": str(last_segment),
            "last_segment_sha256": _sha256_file(last_segment),
            "last_cycle_finished_at_utc": last_payload.get("cycle_finished_at_utc"),
        },
        "counts": {
            "attempt_cycles": int(scan["attempt_cycle_count"]),
            "valid_cycles": int(scan["valid_cycle_count"]),
            "failed_cycles": int(scan["failed_cycle_count"]),
            "failed_cycle_ratio": int(scan["failed_cycle_count"]) / int(scan["attempt_cycle_count"]),
            "pair_rows": int(scan["pair_rows"]),
            "fixed_cost_positive_observations": int(scan["cost_positive_observations"]),
            "observed_base_fee_cost_positive_observations": int(
                scan["observed_base_fee_cost_positive_observations"]
            ),
        },
        "invalid_reason_counts": dict(sorted(scan["invalid_reason_counts"].items())),
        "safety": {
            "strategy_accepted": False,
            "oos_evidence": False,
            "expectancy_claim_allowed": False,
            "replay_acceptance_allowed": False,
            "paper_forward_allowed": False,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
            "source_segments_mutated": False,
        },
        "allowed_uses": [
            "offline_descriptive_screening",
            "economic_kill_gate",
            "event_density_and_concentration_diagnostics",
            "sealed_short_probe_design",
        ],
        "blocked_uses": [
            "claim_oos_edge",
            "claim_positive_expectancy",
            "strategy_acceptance",
            "parameter_grid_optimization",
            "paper_forward",
            "live_trading",
        ],
        "next_valid_move": "run_fast_first_offline_diagnostic_gate",
        "output_path": str(destination),
    }
    _atomic_write_json(destination, report)
    return report


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
    parser = argparse.ArgumentParser(description="Freeze an interrupted forward run as diagnostic-only evidence")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    report = freeze_incomplete_run(args.plan, args.run_dir, args.out, reason=args.reason)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
