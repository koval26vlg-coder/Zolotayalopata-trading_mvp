from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


HISTORY_ONLY = "OVERLAPPING_SUMMARIES_NOT_INDEPENDENT_EDGE_EVIDENCE"
INVALID_EVIDENCE = "FUNDING_FORWARD_HISTORY_AUDIT_REJECTED_INVALID_EVIDENCE"
STAMP_PATTERN = re.compile(r"funding_pairs_forward_(\d{8})\.json$")


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
    return {"path": str(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stamp_date(stamp: str) -> date:
    return datetime.strptime(stamp, "%Y%m%d").date()


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _series_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "range": None}
    return {
        "count": len(values),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "mean": round(sum(values) / len(values), 6),
        "range": round(max(values) - min(values), 6),
    }


def _cost_contract(pair_payload: dict[str, Any]) -> dict[str, Any]:
    params = pair_payload.get("params") if isinstance(pair_payload.get("params"), dict) else {}
    return {
        "window_days": params.get("window_days"),
        "min_aligned_days": params.get("min_aligned_days"),
        "turnover_per_year": params.get("turnover_per_year"),
        "non_binance_only": params.get("non_binance_only"),
        "route": params.get("route"),
        "cycle_cost_bps": params.get("cycle_cost_bps"),
        "spread_definition": params.get("spread_definition"),
        "cost_profile": pair_payload.get("cost_profile"),
    }


def _universe_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    params = manifest.get("params") if isinstance(manifest.get("params"), dict) else {}
    return {
        "exchanges": params.get("exchanges"),
        "collection_days": params.get("days"),
        "top": params.get("top"),
        "universe_csv": str(params.get("universe_csv") or ""),
    }


def _overlap_days(left: tuple[date, date], right: tuple[date, date]) -> int:
    start = max(left[0], right[0])
    end = min(left[1], right[1])
    return max(0, (end - start).days + 1)


def _invalid_shell(failures: list[str]) -> dict[str, Any]:
    stable = {"decision": INVALID_EVIDENCE, "failures": failures}
    return {
        "schema": "funding_forward_history_audit_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": False,
        "decision": INVALID_EVIDENCE,
        "promotion_allowed": False,
        "failures": failures,
        "warnings": [],
        "proof_gates": {
            "chronological_oos": "not_run",
            "walk_forward": "not_run",
            "stress": "not_run",
        },
        "safety": {
            "market_rows_read": False,
            "returns_or_pnl_read": False,
            "oos_read": False,
            "grid_or_retune": False,
            "network_access": False,
        },
        "deterministic_result_hash": _canonical_hash(stable),
    }


def build_funding_forward_history_audit(
    analysis_dir: str | Path,
    daily_dir: str | Path,
    through_stamp: str,
    symbol: str,
    current_audit_path: str | Path,
) -> dict[str, Any]:
    analysis_root = Path(analysis_dir)
    daily_root = Path(daily_dir)
    current_audit_file = Path(current_audit_path)
    failures: list[str] = []
    warnings: list[str] = []
    try:
        _stamp_date(through_stamp)
    except ValueError:
        return _invalid_shell(["through_stamp_invalid"])
    if not analysis_root.is_dir():
        failures.append(f"analysis_dir_missing:{analysis_root}")
    if not daily_root.is_dir():
        failures.append(f"daily_dir_missing:{daily_root}")
    if not current_audit_file.is_file():
        failures.append(f"current_audit_missing:{current_audit_file}")
    if failures:
        return _invalid_shell(failures)

    pair_files: list[tuple[str, Path]] = []
    for path in analysis_root.glob("funding_pairs_forward_*.json"):
        match = STAMP_PATTERN.search(path.name)
        if match and match.group(1) <= through_stamp:
            pair_files.append((match.group(1), path))
    pair_files.sort()
    if not pair_files:
        return _invalid_shell(["no_funding_pair_snapshots"])

    try:
        current_audit = _load_json(current_audit_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid_shell([f"current_audit_load_failed:{exc}"])
    if current_audit.get("schema") != "funding_forward_audit_v1":
        failures.append("current_audit_schema_mismatch")
    if current_audit.get("audit_passed") is not True:
        failures.append("current_audit_not_passed")
    if current_audit.get("decision") != "WATCHLIST_ONLY_NOT_EDGE_EVIDENCE":
        failures.append("current_audit_decision_mismatch")
    if current_audit.get("acceptance_allowed") is not False:
        failures.append("current_audit_acceptance_not_false")
    current_candidate = next(
        (
            item
            for item in current_audit.get("candidates") or []
            if isinstance(item, dict) and item.get("symbol") == symbol
        ),
        None,
    )
    if current_candidate is None:
        failures.append(f"current_audit_symbol_missing:{symbol}")
        identity_status = None
        source_coin_id = None
    else:
        identity = current_candidate.get("identity") if isinstance(current_candidate.get("identity"), dict) else {}
        identity_status = identity.get("status")
        source_coin_id = identity.get("source_coin_id")
        if identity_status != "OFFICIAL_SAME_ASSET_VERIFIED":
            failures.append(f"current_audit_identity_not_verified:{symbol}")

    input_refs: dict[str, dict[str, Any]] = {"current_audit": _input_ref(current_audit_file)}
    comparable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for stamp, pairs_file in pair_files:
        execution_file = analysis_root / f"execution_gate_forward_{stamp}.json"
        manifest_file = daily_root / f"daily_forward_{stamp}" / "manifest.json"
        missing = [str(path) for path in (execution_file, manifest_file) if not path.is_file()]
        if missing:
            failures.append(f"snapshot_files_missing:{stamp}:{'|'.join(missing)}")
            continue
        try:
            pairs_payload = _load_json(pairs_file)
            execution_payload = _load_json(execution_file)
            manifest = _load_json(manifest_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"snapshot_load_failed:{stamp}:{exc}")
            continue
        input_refs[f"pairs_{stamp}"] = _input_ref(pairs_file)
        input_refs[f"execution_{stamp}"] = _input_ref(execution_file)
        input_refs[f"manifest_{stamp}"] = _input_ref(manifest_file)
        reasons: list[str] = []
        if pairs_payload.get("schema") != "funding_pairs_v2":
            reasons.append(f"pairs_schema={pairs_payload.get('schema')}")
        if execution_payload.get("schema") != "execution_gate_v2":
            reasons.append(f"execution_schema={execution_payload.get('schema')}")
        params = pairs_payload.get("params") if isinstance(pairs_payload.get("params"), dict) else {}
        if params.get("non_binance_only") is not True:
            reasons.append("non_binance_contract_missing")
        if params.get("route") != "cross_venue_perp_perp" or params.get("cycle_cost_bps") is None:
            reasons.append("base_cost_contract_missing")
        if reasons:
            excluded_item = {
                "stamp": stamp,
                "reasons": reasons,
                "manifest_error_count": manifest.get("error_count"),
                "pairs_sha256": input_refs[f"pairs_{stamp}"]["sha256"],
                "execution_sha256": input_refs[f"execution_{stamp}"]["sha256"],
            }
            excluded.append(excluded_item)
            continue
        if manifest.get("schema") != "daily_collect_v1":
            failures.append(f"comparable_manifest_schema_mismatch:{stamp}")
        if int(manifest.get("error_count", -1)) != 0:
            failures.append(f"comparable_manifest_errors:{stamp}:{manifest.get('error_count')}")
        if str(execution_payload.get("pairs_source") or "").replace("\\", "/").rsplit("/", 1)[-1] != pairs_file.name:
            failures.append(f"execution_pairs_source_mismatch:{stamp}")
        snapshot = {
            "stamp": stamp,
            "date": _stamp_date(stamp),
            "pairs": pairs_payload,
            "execution": execution_payload,
            "manifest": manifest,
            "cost_contract": _cost_contract(pairs_payload),
            "universe_contract": _universe_contract(manifest),
        }
        comparable.append(snapshot)

    if not comparable:
        failures.append("no_comparable_v2_snapshots")
    cost_hashes = {_canonical_hash(item["cost_contract"]) for item in comparable}
    if len(cost_hashes) > 1:
        failures.append("comparable_cost_contract_drift")
    universe_hashes = {_canonical_hash(item["universe_contract"]) for item in comparable}
    if len(universe_hashes) > 1:
        failures.append("comparable_universe_contract_drift")

    comparable.sort(key=lambda item: item["stamp"])
    if comparable:
        latest_stamp = comparable[-1]["stamp"]
        if latest_stamp != through_stamp:
            failures.append(f"latest_comparable_stamp_mismatch:{latest_stamp}:{through_stamp}")

        current_inputs = current_audit.get("inputs")
        if not isinstance(current_inputs, dict):
            failures.append("current_audit_inputs_missing")
        else:
            for input_name in ("manifest", "pairs", "execution"):
                audit_ref = current_inputs.get(input_name)
                observed_ref = input_refs[f"{input_name}_{latest_stamp}"]
                audit_sha256 = audit_ref.get("sha256") if isinstance(audit_ref, dict) else None
                if not isinstance(audit_sha256, str):
                    failures.append(f"current_audit_{input_name}_hash_missing")
                elif audit_sha256.lower() != observed_ref["sha256"].lower():
                    failures.append(f"current_audit_latest_{input_name}_hash_mismatch")

    observations: list[dict[str, Any]] = []
    windows: list[tuple[date, date]] = []
    for item in comparable:
        params = item["pairs"].get("params") if isinstance(item["pairs"].get("params"), dict) else {}
        window_days = int(params.get("window_days") or 0)
        end = item["date"]
        start = end - timedelta(days=window_days)
        windows.append((start, end))
        pair = next(
            (
                row
                for row in item["pairs"].get("pairs") or []
                if isinstance(row, dict) and row.get("symbol") == symbol
            ),
            None,
        )
        candidate = next(
            (
                row
                for row in item["execution"].get("candidates") or []
                if isinstance(row, dict) and row.get("symbol") == symbol
            ),
            None,
        )
        if pair is None:
            observations.append(
                {
                    "stamp": item["stamp"],
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "pair_present": False,
                    "execution_candidate_present": candidate is not None,
                }
            )
            continue
        spread = pair.get("spread_gate_minus_mexc") if isinstance(pair.get("spread_gate_minus_mexc"), dict) else {}
        g_part = (
            candidate.get("g_construction_perp_perp")
            if isinstance(candidate, dict) and isinstance(candidate.get("g_construction_perp_perp"), dict)
            else {}
        )
        observations.append(
            {
                "stamp": item["stamp"],
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "pair_present": True,
                "execution_candidate_present": candidate is not None,
                "aligned_days": spread.get("aligned_days"),
                "annualized_spread_pct": spread.get("annualized_spread_pct"),
                "sign_consistency": spread.get("sign_consistency"),
                "direction": spread.get("direction"),
                "pair_modeled_net_pct": pair.get("net_abs_annualized_after_costs_pct"),
                "execution_snapshot_net_pct": g_part.get("net_annual_pct"),
                "execution_snapshot_capacity_usd": g_part.get("capacity_usd"),
            }
        )

    cadence = [
        (comparable[index]["date"] - comparable[index - 1]["date"]).days
        for index in range(1, len(comparable))
    ]
    union_days: set[date] = set()
    total_window_days = 0
    for start, end in windows:
        count = (end - start).days + 1
        total_window_days += count
        union_days.update(start + timedelta(days=offset) for offset in range(count))
    pairwise = [
        {
            "left_stamp": comparable[index - 1]["stamp"],
            "right_stamp": comparable[index]["stamp"],
            "overlap_days": _overlap_days(windows[index - 1], windows[index]),
        }
        for index in range(1, len(windows))
    ]
    first_last_overlap = _overlap_days(windows[0], windows[-1]) if windows else 0
    all_intersection = 0
    if windows:
        intersection_start = max(window[0] for window in windows)
        intersection_end = min(window[1] for window in windows)
        all_intersection = max(0, (intersection_end - intersection_start).days + 1)
    first_window_days = (windows[0][1] - windows[0][0]).days + 1 if windows else 0
    independent_holdouts = 0
    covered_end = windows[0][1] if windows else None
    for start, end in windows[1:]:
        if covered_end is not None and start > covered_end:
            independent_holdouts += 1
        covered_end = max(covered_end, end) if covered_end is not None else end

    present = [item for item in observations if item.get("pair_present")]
    directions = {str(item.get("direction")) for item in present if item.get("direction")}
    spreads = [value for item in present if (value := _float(item.get("annualized_spread_pct"))) is not None]
    consistencies = [value for item in present if (value := _float(item.get("sign_consistency"))) is not None]
    pair_nets = [value for item in present if (value := _float(item.get("pair_modeled_net_pct"))) is not None]
    execution_nets = [
        value for item in present if (value := _float(item.get("execution_snapshot_net_pct"))) is not None
    ]
    capacities = [
        value for item in present if (value := _float(item.get("execution_snapshot_capacity_usd"))) is not None
    ]
    capacity_growth = None
    if len(capacities) >= 2 and capacities[0] != 0:
        capacity_growth = round((capacities[-1] / capacities[0] - 1.0) * 100.0, 6)

    history_contract = {
        "through_stamp": through_stamp,
        "total_snapshot_count": len(pair_files),
        "comparable_snapshot_count": len(comparable),
        "excluded_snapshot_count": len(excluded),
        "comparable_stamps": [item["stamp"] for item in comparable],
        "excluded_snapshots": excluded,
        "comparable_cost_contract": comparable[0]["cost_contract"] if comparable else None,
        "comparable_universe_contract": comparable[0]["universe_contract"] if comparable else None,
    }
    window_overlap = {
        "inclusive_window_days": first_window_days,
        "cadence_days": cadence,
        "pairwise_overlap": pairwise,
        "first_last_overlap_days": first_last_overlap,
        "all_window_intersection_days": all_intersection,
        "unique_calendar_days": len(union_days),
        "total_window_day_observations": total_window_days,
        "duplicate_observation_fraction": _round(
            1.0 - len(union_days) / total_window_days if total_window_days else None
        ),
        "new_days_after_first_snapshot": max(0, len(union_days) - first_window_days),
        "independent_holdout_windows": independent_holdouts,
        "overlap_blocks_independence": any(item["overlap_days"] > 0 for item in pairwise),
    }
    symbol_track = {
        "symbol": symbol,
        "identity_status": identity_status,
        "source_coin_id": source_coin_id,
        "comparable_presence_count": len(present),
        "execution_candidate_presence_count": sum(bool(item.get("execution_candidate_present")) for item in observations),
        "direction_count": len(directions),
        "directions": sorted(directions),
        "observations": observations,
        "stability_diagnostics": {
            "annualized_spread_pct": _series_stats(spreads),
            "sign_consistency": _series_stats(consistencies),
            "pair_modeled_net_pct": _series_stats(pair_nets),
            "execution_snapshot_net_pct": _series_stats(execution_nets),
            "execution_snapshot_capacity_usd": _series_stats(capacities),
            "capacity_first_to_last_growth_pct": capacity_growth,
        },
        "maximum_claim": "repeated_screen_result_under_heavily_overlapping_windows",
    }
    proof_gates = {
        "chronological_oos": "not_run",
        "five_fold_walk_forward": "not_run",
        "stress": "not_run",
        "economics": "summary_screen_only",
        "execution_capacity": "one_snapshot_per_observation_not_time_averaged",
    }
    safety = {
        "market_rows_read": False,
        "returns_or_pnl_read": False,
        "oos_read": False,
        "grid_or_retune": False,
        "network_access": False,
        "collector_started": False,
        "paper_or_live_started": False,
    }
    if len(comparable) < 2:
        warnings.append("fewer_than_two_comparable_snapshots")
    if not present:
        warnings.append(f"symbol_absent_from_comparable_snapshots:{symbol}")
    decision = INVALID_EVIDENCE if failures else HISTORY_ONLY
    stable = {
        "input_hashes": {name: value["sha256"] for name, value in sorted(input_refs.items())},
        "decision": decision,
        "failures": failures,
        "warnings": warnings,
        "history_contract": history_contract,
        "window_overlap": window_overlap,
        "symbol_track": symbol_track,
        "proof_gates": proof_gates,
        "safety": safety,
    }
    return {
        "schema": "funding_forward_history_audit_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": not failures,
        "decision": decision,
        "promotion_allowed": False,
        "research_only": True,
        "inputs": input_refs,
        "history_contract": history_contract,
        "window_overlap": window_overlap,
        "symbol_track": symbol_track,
        "proof_gates": proof_gates,
        "safety": safety,
        "caveats": [
            "Legacy v1 reports are excluded because their universe and cost contracts are not comparable to v2.",
            "Rolling 90-day summaries share most calendar observations and are not independent forward trials.",
            "Current-volume universe selection is not point-in-time and can contain survivorship bias.",
            "Modeled annualized net values are not realized expectancy, return, or PnL.",
            "A chronological holdout requires a separate frozen manifest and explicit authorization before reading OOS.",
        ],
        "failures": failures,
        "warnings": warnings,
        "deterministic_result_hash": _canonical_hash(stable),
    }


def run_funding_forward_history_audit(
    analysis_dir: str | Path,
    daily_dir: str | Path,
    through_stamp: str,
    symbol: str,
    current_audit_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    result = build_funding_forward_history_audit(
        analysis_dir,
        daily_dir,
        through_stamp,
        symbol,
        current_audit_path,
    )
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
    parser = argparse.ArgumentParser(description="Offline longitudinal audit of funding-forward summary overlap")
    parser.add_argument("--analysis-dir", required=True)
    parser.add_argument("--daily-dir", required=True)
    parser.add_argument("--through-stamp", required=True)
    parser.add_argument("--symbol", default="AKE_USDT")
    parser.add_argument("--current-audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = run_funding_forward_history_audit(
        args.analysis_dir,
        args.daily_dir,
        args.through_stamp,
        args.symbol,
        args.current_audit,
        args.out,
    )
    overlap = result.get("window_overlap") or {}
    history = result.get("history_contract") or {}
    print(
        f"HISTORY_AUDIT decision={result['decision']} passed={str(result['audit_passed']).lower()} "
        f"comparable={history.get('comparable_snapshot_count', 0)} "
        f"first_last_overlap_days={overlap.get('first_last_overlap_days', 0)} "
        f"independent_holdouts={overlap.get('independent_holdout_windows', 0)} "
        f"hash={result['deterministic_result_hash']} out={args.out}"
    )
    return 0 if result["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
