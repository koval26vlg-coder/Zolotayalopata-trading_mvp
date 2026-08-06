from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MANIFEST_SCHEMA = "pit_universe_snapshot_manifest_v2"
SPEC_SCHEMA = "pit_two_venue_clean_slice_spec_v1"
MASK_SCHEMA = "pit_two_venue_clean_slice_mask_v1"
DEFAULT_RULE_REVISION = "whole_cycle_two_venue_availability_v1"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_artifact(manifest_path: Path, value: Any, fallback: str) -> Path:
    raw = str(value or fallback)
    path = Path(raw)
    return path if path.is_absolute() else manifest_path.parent / path


def _sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_cycle_journal(path: Path, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid cycle journal JSON at line {line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"cycle journal row {line_number} is not an object")
            if str(row.get("run_id") or "") != run_id:
                raise ValueError(f"cycle journal run_id mismatch at line {line_number}")
            cycle = row.get("cycle")
            if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle <= 0:
                raise ValueError(f"invalid cycle id at line {line_number}: {cycle!r}")
            output_rows = row.get("output_rows")
            if not isinstance(output_rows, int) or isinstance(output_rows, bool) or output_rows < 0:
                raise ValueError(f"invalid output_rows at cycle {cycle}: {output_rows!r}")
            errors = row.get("errors")
            if not isinstance(errors, dict):
                raise ValueError(f"cycle {cycle} errors must be an object")
            successful = row.get("successful_exchanges")
            if not isinstance(successful, list) or any(not isinstance(value, str) for value in successful):
                raise ValueError(f"cycle {cycle} successful_exchanges must be a string list")
            rows.append(row)
    if not rows:
        raise ValueError("cycle journal is empty")
    return rows


def _dropped_runs(dropped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not dropped:
        return []
    by_cycle = {int(item["cycle"]): item for item in dropped}
    cycles = sorted(by_cycle)
    groups: list[list[int]] = [[cycles[0]]]
    for cycle in cycles[1:]:
        if cycle == groups[-1][-1] + 1:
            groups[-1].append(cycle)
        else:
            groups.append([cycle])
    return [
        {
            "start_cycle": group[0],
            "end_cycle": group[-1],
            "count": len(group),
            "started_at_utc": by_cycle[group[0]].get("cycle_started_at_utc"),
            "finished_at_utc": by_cycle[group[-1]].get("cycle_finished_at_utc"),
        }
        for group in groups
    ]


def _ensure_output_outside_source(output_path: Path, source_dir: Path) -> None:
    output_resolved = output_path.resolve()
    source_resolved = source_dir.resolve()
    try:
        output_resolved.relative_to(source_resolved)
    except ValueError:
        return
    raise ValueError("output_path must be outside the source run directory")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_clean_slice_spec(
    manifest_path: str | Path,
    output_path: str | Path,
    required_exchanges: Iterable[str] = ("gateio", "mexc"),
    rule_revision: str = DEFAULT_RULE_REVISION,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    output_path = Path(output_path).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    _ensure_output_outside_source(output_path, manifest_path.parent)

    required = sorted({str(value).strip().lower() for value in required_exchanges if str(value).strip()})
    if len(required) < 2:
        raise ValueError("at least two required_exchanges are required")
    if not rule_revision.strip():
        raise ValueError("rule_revision must not be empty")

    manifest = _load_json(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"manifest schema must be {MANIFEST_SCHEMA}")
    if manifest.get("mode") != "pit_universe_snapshot_collect":
        raise ValueError("manifest mode must be pit_universe_snapshot_collect")
    if not bool(manifest.get("final")):
        raise ValueError("manifest.final=true is required")
    run_id = str(manifest.get("run_id") or "")
    if not run_id:
        raise ValueError("manifest run_id is required")

    snapshots_path = _resolve_artifact(manifest_path, manifest.get("snapshots_path"), "snapshots.jsonl").resolve()
    cycles_path = _resolve_artifact(manifest_path, manifest.get("cycles_path"), "cycles.jsonl").resolve()
    for label, path in (("snapshots", snapshots_path), ("cycles", cycles_path)):
        if not path.exists():
            raise FileNotFoundError(f"{label} artifact not found: {path}")

    cycle_rows = _load_cycle_journal(cycles_path, run_id)
    cycle_count = int(manifest.get("cycle_count") or 0)
    actual_ids = [int(row["cycle"]) for row in cycle_rows]
    expected_ids = list(range(1, cycle_count + 1))
    if actual_ids != expected_ids:
        raise ValueError("cycle journal IDs must be unique, ordered, and contiguous from 1 through manifest cycle_count")
    journal_rows = sum(int(row["output_rows"]) for row in cycle_rows)
    manifest_rows = int(manifest.get("rows_total") or 0)
    if journal_rows != manifest_rows:
        raise ValueError(f"cycle journal row sum {journal_rows} does not match manifest rows_total {manifest_rows}")

    source_artifacts = {
        "manifest": _artifact_record(manifest_path),
        "cycles": _artifact_record(cycles_path),
        "snapshots": _artifact_record(snapshots_path),
    }
    required_set = set(required)
    retained: list[int] = []
    dropped_details: list[dict[str, Any]] = []
    retained_rows = 0
    dropped_rows = 0
    for row in cycle_rows:
        cycle = int(row["cycle"])
        output_rows = int(row["output_rows"])
        errors = dict(row["errors"])
        successful = sorted({str(value).lower() for value in row["successful_exchanges"]})
        missing = sorted(required_set.difference(successful))
        if not errors and not missing:
            retained.append(cycle)
            retained_rows += output_rows
            continue
        reasons: list[str] = []
        if errors:
            reasons.append("cycle_errors_present")
        if missing:
            reasons.append("required_exchange_missing")
        dropped_rows += output_rows
        dropped_details.append(
            {
                "cycle": cycle,
                "output_rows": output_rows,
                "reasons": reasons,
                "errors": errors,
                "successful_exchanges": successful,
                "missing_exchanges": missing,
                "cycle_started_at_utc": row.get("cycle_started_at_utc"),
                "cycle_finished_at_utc": row.get("cycle_finished_at_utc"),
            }
        )

    dropped_cycles = [int(item["cycle"]) for item in dropped_details]
    if sorted(retained + dropped_cycles) != expected_ids or set(retained).intersection(dropped_cycles):
        raise AssertionError("retained/dropped masks must be mutually exclusive and cover every source cycle")

    mask_core = {
        "schema": MASK_SCHEMA,
        "rule_revision": rule_revision,
        "source_run_id": run_id,
        "cycles_sha256": source_artifacts["cycles"]["sha256"],
        "required_exchanges": required,
        "retained_cycles": retained,
        "dropped_cycles": dropped_cycles,
    }
    mask_sha256 = _canonical_sha256(mask_core)
    payload: dict[str, Any] = {
        "schema": SPEC_SCHEMA,
        "mode": "pit_two_venue_clean_slice_spec_planonly",
        "decision": "PIT_TWO_VENUE_CLEAN_SLICE_SPEC_PLANONLY_READY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "would_start": False,
        "would_materialize": False,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "backtest_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "source_run": {
            "run_id": run_id,
            "manifest_final": True,
            "full_dataset_verdict": "rejected_not_modified",
            "cycle_count": cycle_count,
            "rows_total": manifest_rows,
        },
        "source_artifacts": source_artifacts,
        "selection_rule": {
            "revision": rule_revision,
            "required_exchanges": required,
            "predicate": "errors is empty AND every required exchange is in successful_exchanges",
            "selection_inputs": ["cycle", "errors", "successful_exchanges", "output_rows", "cycle timestamps"],
            "outcome_fields_consulted": [],
            "whole_cycle_only": True,
            "retain_all_symbols_and_exchanges_within_retained_cycles": True,
            "preserve_source_cycle_ids_chronology_and_gaps": True,
            "forward_fill_allowed": False,
            "imputation_allowed": False,
            "symbol_level_filtering_allowed": False,
        },
        "mask": {
            "retained_cycles": retained,
            "dropped_cycles": dropped_cycles,
            "retained_cycle_count": len(retained),
            "dropped_cycle_count": len(dropped_cycles),
            "retained_rows": retained_rows,
            "dropped_rows": dropped_rows,
            "retained_ratio": len(retained) / cycle_count if cycle_count else 0.0,
            "dropped_details": dropped_details,
            "dropped_runs": _dropped_runs(dropped_details),
        },
        "temporal_coverage": {
            "first_cycle_started_at_utc": cycle_rows[0].get("cycle_started_at_utc"),
            "last_cycle_finished_at_utc": cycle_rows[-1].get("cycle_finished_at_utc"),
            "gaps_preserved_as_dropped_cycle_ids": dropped_cycles,
        },
        "mask_sha256": mask_sha256,
        "mask_hash_payload": mask_core,
        "output_path": str(output_path),
        "next_valid_move": (
            "Independent approval is required before any clean-slice materialization; "
            "replay/grid/backtest/paper/live remain blocked."
        ),
    }
    _atomic_write_json(output_path, payload)
    return payload


def _parse_exchanges(raw: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in raw.split(",") if value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a PIT two-venue clean-slice PlanOnly specification")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--required-exchanges", default="gateio,mexc")
    parser.add_argument("--rule-revision", default=DEFAULT_RULE_REVISION)
    args = parser.parse_args()
    result = build_clean_slice_spec(
        args.manifest,
        args.out,
        required_exchanges=_parse_exchanges(args.required_exchanges),
        rule_revision=args.rule_revision,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
