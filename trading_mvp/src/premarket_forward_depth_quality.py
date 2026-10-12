"""Offline, content-bound structural audit. No network or strategy calculations."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


SCHEMA = "trading_mvp_forward_depth_quality_v1"
CAPTURE_SCHEMA = "trading_mvp_premarket_forward_depth_capture_v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value: dict, field: str) -> str:
    return hashlib.sha256(json.dumps(
        {k: v for k, v in value.items() if k != field}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def decode(text: str) -> dict:
    value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "file_sha256": digest(path),
            "bytes": path.stat().st_size}


def number(value) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a quantity")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite quantity")
    return result


def _book_errors(row: dict) -> list[str]:
    errors = []
    if row.get("usable") is False:
        return errors
    if row.get("usable") is not True:
        return ["MISSING_USABLE_FLAG"]
    try:
        bid, ask, mid = [number(row[k]) for k in ("best_bid", "best_ask", "mid")]
        if not (0 < bid <= ask and math.isclose(mid, (bid + ask) / 2,
                                               rel_tol=1e-8, abs_tol=1e-12)):
            errors.append("INVALID_BBO")
        for side, key, best, reverse in (("bid", "top_bids", bid, True),
                                         ("ask", "top_asks", ask, False)):
            levels = row[key]
            prices, sizes = zip(*[(number(p), number(s)) for p, s in levels])
            if (any(p <= 0 for p in prices) or any(s < 0 for s in sizes)
                    or list(prices) != sorted(prices, reverse=reverse)
                    or prices[0] != best or len(set(prices)) != len(prices)):
                errors.append("INVALID_LEVELS")
            for n in (5, 10, 25, 50):
                field = f"{side}_depth_top{n}"
                if field in row and not math.isclose(number(row[field]),
                        sum(p * s for p, s in zip(prices[:n], sizes[:n])),
                        rel_tol=1e-8, abs_tol=1e-8):
                    errors.append("TOP_DEPTH_SUM_MISMATCH")
            for key, value in row.items():
                if key.startswith(f"{side}_depth_") and number(value) < 0:
                    errors.append("NEGATIVE_DEPTH")
        sha = row["response_sha256"]
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            errors.append("INVALID_RESPONSE_HASH")
        if number(row["response_bytes"]) <= 0:
            errors.append("INVALID_RESPONSE_BYTES")
    except (ValueError, KeyError, TypeError, OverflowError):
        errors.append("MALFORMED_BOOK")
    return errors


def audit_capture(path: Path, plans: dict, current_plan: dict) -> dict:
    before = ref(path)
    records, problems = [], Counter()
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            try:
                records.append(decode(line))
            except (ValueError, TypeError):
                problems["INVALID_JSON_LINE"] += 1
    if digest(path) != before["file_sha256"]:
        raise ValueError(f"input changed during read: {path}")
    result = {**before, "integrity_errors": {}, "exclusion_reasons": [],
              "candidate": False, "record_count": len(records)}
    if (not records or records[0].get("record") != "header"
            or records[-1].get("record") != "footer"
            or sum(r.get("record") == "header" for r in records) != 1
            or sum(r.get("record") == "footer" for r in records) != 1):
        result["integrity_errors"] = {**problems, "MISSING_OR_DUPLICATE_BOUNDARY": 1}
        result["exclusion_reasons"] = ["INCOMPLETE_OR_CORRUPT"]
        return result
    header, footer = records[0], records[-1]
    event = header.get("event") or {}
    source_plan = plans.get(header.get("plan_hash"))
    if (not source_plan or source_plan.get("plan_id") != header.get("plan_id")
            or header.get("schema") != CAPTURE_SCHEMA):
        problems["PLAN_BINDING_MISMATCH"] += 1
    elif header.get("hypothesis") != source_plan.get("hypothesis"):
        problems["HYPOTHESIS_BINDING_MISMATCH"] += 1
    result.update({"event": event, "plan_id": header.get("plan_id"),
                   "plan_hash": header.get("plan_hash"),
                   "footer": footer})
    try:
        t0 = number(event["t0_ts"])
        multiplier = number(event["perp_ct_val"])
        if multiplier <= 0:
            problems["INVALID_CONTRACT_MULTIPLIER"] += 1
        if header.get("size_units") != "VENUE_NATIVE_CONTRACTS_OR_BASE_NOT_CONVERTED":
            problems["UNKNOWN_SIZE_UNITS"] += 1
        pre_minutes = number(event["pre_window_available_min"])
        lead = t0 - number(event["perp_launched_ts"])
        qualification = current_plan["qualification"]
        if (event.get("venue") not in ("gate", "okx")
                or not qualification["min_lead_sec"] <= lead <= qualification["max_lead_days"] * 86400):
            problems["EVENT_QUALIFICATION_MISMATCH"] += 1
    except (ValueError, KeyError, TypeError):
        result["integrity_errors"] = {**problems, "INVALID_EVENT": 1}
        result["exclusion_reasons"] = ["INCOMPLETE_OR_CORRUPT"]
        return result
    books = {"perp": [], "spot": []}
    previous, seen = {}, set()
    errors, unusable, attempts = 0, 0, 0
    for row in records[1:-1]:
        if row.get("record") not in ("book", "error"):
            problems["UNEXPECTED_RECORD"] += 1
            continue
        attempts += 1
        leg = row.get("leg")
        try:
            ts, rel_min = number(row["ts"]), number(row["rel_min"])
            if leg not in books or row.get("symbol") != event.get(f"{leg}_symbol"):
                raise ValueError("invalid leg")
            if abs(rel_min - (ts - t0) / 60) > 0.001:
                problems["RELATIVE_TIME_MISMATCH"] += 1
            if (leg, ts) in seen or ts < previous.get(leg, -math.inf):
                problems["DUPLICATE_OR_REVERSED_TIMESTAMP"] += 1
            seen.add((leg, ts))
            previous[leg] = ts
            if not number(event["capture_from_ts"]) <= ts < number(event["capture_to_ts"]):
                problems["TIMESTAMP_OUTSIDE_CAPTURE_WINDOW"] += 1
            if leg == "spot" and ts < t0:
                problems["SPOT_BEFORE_OPEN"] += 1
        except (ValueError, KeyError, TypeError):
            problems["INVALID_TIMESTAMP_OR_SYMBOL"] += 1
            continue
        if row["record"] == "error":
            errors += 1
            continue
        row_errors = _book_errors(row)
        problems.update(row_errors)
        if row.get("usable") is not True:
            unusable += 1
        elif not row_errors:
            books[leg].append(row)
    if footer.get("snapshots") != attempts or footer.get("errors") != errors:
        problems["FOOTER_COUNT_MISMATCH"] += 1
    try:
        from datetime import datetime
        finished = datetime.fromisoformat(footer["finished_at_utc"].replace("Z", "+00:00"))
        if finished.tzinfo is None or finished.timestamp() < number(event["capture_to_ts"]):
            problems["EARLY_FOOTER"] += 1
    except (KeyError, ValueError, TypeError):
        problems["INVALID_FOOTER_TIME"] += 1
    first_spot = min((r["rel_min"] for r in books["spot"]), default=None)
    tolerance = current_plan["anchor_check"]["max_first_spot_book_delay_min"]
    anchor_suspect = first_spot is None or first_spot > tolerance
    if "first_spot_book_rel_min" in footer and footer["first_spot_book_rel_min"] != first_spot:
        problems["FOOTER_ANCHOR_MISMATCH"] += 1
    if "anchor_suspect" in footer and footer["anchor_suspect"] != anchor_suspect:
        problems["FOOTER_ANCHOR_FLAG_MISMATCH"] += 1
    coverage = {}
    interval = current_plan["capture"]["snapshot_interval_sec"]
    for leg, rows in books.items():
        stamps = sorted(number(r["ts"]) for r in rows)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        coverage[leg] = {"usable_rows": len(rows),
            "first_rel_min": round((stamps[0] - t0) / 60, 3) if stamps else None,
            "last_rel_min": round((stamps[-1] - t0) / 60, 3) if stamps else None,
            "max_gap_sec": max(gaps, default=0),
            "gaps_over_two_nominal_intervals": sum(g > 2 * interval for g in gaps),
            "windows": {name: sum(lo <= r["rel_min"] < hi for r in rows)
                        for name, lo, hi in (("pre", -120, 0), ("post_0_30", 0, 30),
                                            ("post_30_60", 30, 60), ("post_60_120", 60, 120))},
            "primary_band_inside_spread_rows": sum(r.get("bid_inside_spread_1.0pct") is True for r in rows),
            "primary_band_truncated_rows": sum(r.get("bid_truncated_1.0pct") is True for r in rows),
            "top25_short_rows": sum(r.get("bid_levels_short_top25") is True for r in rows)}
    exclusions = []
    if problems:
        exclusions.append("INCOMPLETE_OR_CORRUPT")
    if header.get("plan_hash") != current_plan["plan_hash"]:
        exclusions.append("HISTORICAL_PLAN_NOT_POOLED")
    if anchor_suspect:
        exclusions.append("SPOT_ANCHOR_UNCONFIRMED")
    minimum_pre = current_plan["notice_limit"]["minimum_useful_pre_min"]
    actual_pre = -(coverage["perp"]["first_rel_min"] or 0)
    if min(pre_minutes, actual_pre) < minimum_pre:
        exclusions.append("PRE_WINDOW_TOO_SHORT")
    for leg, c in coverage.items():
        if not all(c["windows"][name] > 0 for name in ("post_0_30", "post_30_60", "post_60_120")):
            exclusions.append(f"{leg.upper()}_POST_WINDOW_MISSING")
        # A footer written after sleep/interruption is not evidence of a full window.
        final_slot = current_plan["capture"]["window_after_min"] - interval / 60
        if c["last_rel_min"] is None or c["last_rel_min"] + 0.001 < final_slot:
            exclusions.append(f"{leg.upper()}_POST_WINDOW_TRUNCATED")
    if footer.get("reached_budget") is not False:
        exclusions.append("BUDGET_EXHAUSTED_OR_UNKNOWN")
    result.update({"integrity_errors": dict(sorted(problems.items())),
                   "exclusion_reasons": exclusions, "coverage": coverage,
                   "candidate": not exclusions, "http_error_rows": errors,
                   "unusable_book_rows": unusable, "first_spot_rel_min": first_spot,
                   "anchor_suspect": anchor_suspect,
                   "units": {"perp_native_to_base_multiplier": multiplier,
                             "cross_leg_absolute_depth_compared": False},
                   "sampling_gaps_require_review": any(c["gaps_over_two_nominal_intervals"] for c in coverage.values())})
    return result


def build_audit(capture_dir: Path, plan_paths: list[Path], current_path: Path,
                armed_path: Path) -> dict:
    source_paths = sorted(set([*plan_paths, current_path, armed_path,
                               *capture_dir.glob("*.jsonl")]), key=str)
    inputs = [ref(p) for p in source_paths]
    inputs.append(ref(Path(__file__).resolve()))
    plans = {}
    for path in sorted(set([*plan_paths, current_path]), key=str):
        plan = decode(path.read_text(encoding="utf-8-sig"))
        if plan.get("plan_hash") != canonical(plan, "plan_hash"):
            raise ValueError(f"plan hash mismatch: {path}")
        plans[plan["plan_hash"]] = plan
    current = decode(current_path.read_text(encoding="utf-8-sig"))
    for binding in current["implementation"]["files"]:
        p = Path(binding["path"])
        if digest(p) != binding["sha256"]:
            raise ValueError(f"current implementation hash mismatch: {p}")
        inputs.append(ref(p))
    armed = decode(armed_path.read_text(encoding="utf-8-sig"))
    results = [audit_capture(p, plans, current) for p in sorted(capture_dir.glob("*.jsonl"))]
    latest = {}
    for row in results:
        event = row.get("event", {})
        key = (event.get("venue"), event.get("base"))
        latest[key] = max(latest.get(key, 0), event.get("t0_ts", 0))
    explicitly_superseded = {(e["venue"], e["base"], e["superseded_t0_ts"])
                            for e in armed.get("superseded", [])}
    for row in results:
        e = row.get("event", {})
        key = (e.get("venue"), e.get("base"))
        if (e.get("t0_ts", 0) < latest[key]
                or (*key, e.get("t0_ts")) in explicitly_superseded):
            row["exclusion_reasons"].append("SUPERSEDED_SCHEDULE")
            row["candidate"] = False
    for item in inputs:
        if digest(Path(item["path"])) != item["file_sha256"]:
            raise ValueError(f"source changed during audit: {item['path']}")
    if {str(p.resolve()) for p in capture_dir.glob("*.jsonl")} != {
            r["path"] for r in results}:
        raise ValueError("capture inventory changed during audit")
    candidates = [r for r in results if r["candidate"]]
    report = {"schema": SCHEMA, "plan_hash": current["plan_hash"],
              "inputs": inputs, "input_manifest_hash": canonical({"files": inputs}, "unused"),
              "capture_directory": str(capture_dir.resolve()), "events": results,
              "summary": {"files": len(results), "distinct_venue_base": len(latest),
                  "current_plan_structural_candidates": len(candidates),
                  "candidate_unique_t0": len({r["event"]["t0_ts"] for r in candidates}),
                  "candidate_unique_utc_dates": len({r["event"]["t0_utc"][:10] for r in candidates}),
                  "candidate_files": [Path(r["path"]).name for r in candidates],
                  "minimum_events_before_any_claim": current["outcome_contract"]["minimum_events_before_any_claim"],
                  "mechanism_analysis_performed": False, "pnl_computed": False,
                  "acceptance_capable": False, "complete_statistical_sample_certified": False},
              "limitations": ["Structural candidates are not independent certified events.",
                  "Cadence gaps are disclosed, not interpolated or assigned a new statistical threshold.",
                  "Historical plans are diagnostics only until separate equivalence review.",
                  "Contract sizes remain native; no cross-leg absolute depth comparison.",
                  "No profitability or hypothesis verdict from this quality audit."]}
    report["report_hash"] = canonical(report, "report_hash")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plan_root = root / "docs/plans"
    data = root / "docs/analysis/premarket-forward-depth"
    report = build_audit(data / "captures", list(plan_root.glob("premarket-forward-depth-planonly-*.json")),
                         plan_root / "premarket-forward-depth-planonly-20260902-v6.json",
                         data / "armed-events.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Immutable output: never replace a prior audit or repair it in place.
    with args.output.open("x", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
