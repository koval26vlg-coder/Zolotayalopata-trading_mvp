"""Bounded offline sampling diagnostics, never an evaluator or collector."""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from premarket_forward_depth_quality import canonical, decode, ref
from research_checkpoint import verify_audit, verify_ref

SCHEMA = "premarket_depth_sampling_quality_protocol_v1"
RULES = {
    "purpose": "QUALITY_DIAGNOSTICS_NOT_EVALUATOR",
    "grid": "T0_ANCHORED_NOMINAL_CADENCE_FULL_HALF_OPEN_SLOTS_ONLY",
    "missing": "KEEP_MISSING_NO_INTERPOLATION_NO_ZERO_FILL",
    "attempts": "COUNT_ERRORS_UNUSABLE_AND_NO_ATTEMPT_SEPARATELY",
    "multiple_attempts": "FLAG_ONLY_NEVER_SELECT_A_PRICE_OR_DEPTH",
    "fallback_diagnostic": "PER_LEG_USABLE_BOOK_ROWS_BID_INSIDE_SPREAD_TIMES_THREE_GT_COUNT",
    "fallback_scope": "ONE_ROUTE_FOR_WHOLE_LEG_NOT_PER_ROW_OR_PER_SIDE",
    "top25": "REQUIRE_25_LEVELS_PER_SIDE_NO_PARTIAL_SUM_AS_FULL_DEPTH",
    "control": "BID_AND_ASK_OBSERVABILITY_REPORTED_SEPARATELY_AND_PAIRED",
    "dependency_tags": "CONNECTED_COMPONENTS_OF_OVERLAPPING_CAPTURE_WINDOWS_OR_SAME_BASE",
    "independence": "COMPONENTS_ARE_REVIEW_TAGS_NOT_CERTIFIED_INDEPENDENT_EVENTS",
    "acceptance": "UNCHANGED_BASE_PLAN_NO_SAMPLE_OR_STRATEGY_ACCEPTANCE",
    "method_status": "QUALITY_ONLY_CLARIFICATION_NOT_BOUND_INTO_EVALUATOR",
}
LIMITS = {"max_runtime_sec": 300, "max_input_bytes": 134217728,
          "max_output_bytes": 5242880, "max_line_bytes": 1048576}


def audit_leg(rows: list[dict], *, leg: str, t0: float, start: float,
              end: float, interval: int) -> dict:
    if (leg not in ("spot", "perp") or isinstance(interval, bool) or interval <= 0
            or not all(math.isfinite(v) for v in (t0, start, end, interval)) or end <= start):
        raise ValueError("invalid sampling grid")
    start = max(start, t0) if leg == "spot" else start
    first, stop = math.ceil((start - t0) / interval), math.floor((end - t0) / interval)
    slots = {i: [] for i in range(first, stop)}
    usable, partial = [], 0
    for row in rows:
        if row.get("leg") != leg or row.get("record") not in ("book", "error"):
            continue
        ts = row.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, (float, int)) or not math.isfinite(ts):
            raise ValueError("invalid timestamp")
        if not start <= ts < end:
            continue
        if row["record"] == "book" and row.get("usable") is True:
            usable.append(row)
        slot = math.floor((ts - t0) / interval)
        if slot not in slots:
            partial += 1
        else:
            slots[slot].append(row)

    counts = {"expected": len(slots), "usable": 0, "missing": 0, "no_attempt": 0,
              "request_error_only": 0, "unusable_only": 0,
              "mixed_error_unusable": 0, "multiple_attempts": 0}
    missing_indices = []
    for index, attempts in slots.items():
        counts["multiple_attempts"] += len(attempts) > 1
        if any(r.get("record") == "book" and r.get("usable") is True for r in attempts):
            counts["usable"] += 1
            continue
        counts["missing"] += 1
        missing_indices.append(index)
        kinds = {r["record"] for r in attempts}
        category = ("no_attempt" if not attempts else "request_error_only" if kinds == {"error"}
                    else "unusable_only" if kinds == {"book"} else "mixed_error_unusable")
        counts[category] += 1
    runs = []
    for index in missing_indices:
        if runs and runs[-1]["to_rel_sec_exclusive"] == index * interval:
            runs[-1]["to_rel_sec_exclusive"] = (index + 1) * interval
        else:
            runs.append({"from_rel_sec": index * interval,
                         "to_rel_sec_exclusive": (index + 1) * interval})

    flags = [r.get("bid_inside_spread_1.0pct") for r in usable]
    inside = sum(f is True for f in flags)
    route = ("NO_USABLE_BOOKS" if not usable else "UNKNOWN_FLAGS"
             if any(type(f) is not bool for f in flags)
             else "TOP25" if inside * 3 > len(usable) else "BAND_1PCT")
    measurement = {"usable_book_rows": len(usable), "bid_inside_spread_rows": inside,
                   "bid_unobservable": 0, "ask_unobservable": 0, "paired_observable": 0}
    phases = {name: {"usable_book_rows": 0, "paired_observable": 0}
              for name in ("pre", "post_0_30", "post_30_60", "post_60_120")}
    for row in usable:
        visible = []
        for side in ("bid", "ask"):
            if route == "TOP25":
                levels = row.get(f"levels_{side}")
                valid = (row.get(f"{side}_levels_short_top25") is False
                         and type(levels) is int and levels >= 25)
            elif route == "BAND_1PCT":
                valid = (row.get(f"{side}_inside_spread_1.0pct") is False
                         and row.get(f"{side}_truncated_1.0pct") is False)
            else:
                valid = False
            visible.append(valid)
            measurement[f"{side}_unobservable"] += not valid
        paired = all(visible)
        measurement["paired_observable"] += paired
        rel_sec = row["ts"] - t0
        phase = "pre" if rel_sec < 0 else "post_0_30" if rel_sec < 1800 else "post_30_60" if rel_sec < 3600 else "post_60_120"
        phases[phase]["usable_book_rows"] += 1
        phases[phase]["paired_observable"] += paired
    return {"leg": leg, "slots": counts, "missing_runs": runs,
            "partial_boundary_rows": partial, "diagnostic_measure_route": route,
            "measurement_rows": measurement, "phases": phases,
            "interpolation_performed": False, "numerical_depth_or_returns_computed": False}


def dependence_groups(events: list[dict]) -> list[dict]:
    events = sorted(events, key=lambda e: e["id"])
    if len({e["id"] for e in events}) != len(events):
        raise ValueError("duplicate event ID")
    for event in events:
        start, end = event["capture_from_ts"], event["capture_to_ts"]
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
                or end <= start):
            raise ValueError("invalid dependency window")
    parent = list(range(len(events)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    links = []
    for i, a in enumerate(events):
        for j in range(i):
            b = events[j]
            overlap = max(a["capture_from_ts"], b["capture_from_ts"]) < min(a["capture_to_ts"], b["capture_to_ts"])
            same_base = a["base"] == b["base"]
            if overlap or same_base:
                parent[find(i)] = find(j)
                links.append({"a": a["id"], "b": b["id"], "overlapping_capture_window": overlap,
                              "same_base": same_base})
    components = defaultdict(list)
    for i, event in enumerate(events):
        components[find(i)].append(event["id"])
    return [{"members": members, "links": [link for link in links if link["a"] in members],
             "independence_certified": False}
            for members in sorted(components.values())]


def freeze(root: Path) -> dict:
    plan_path = root / "docs/plans/premarket-forward-depth-planonly-20260902-v6.json"
    audit_path = root / "docs/analysis/strategy-reconciliation-20260929/depth-quality-v2.json"
    audit = verify_audit(ref(audit_path), root)
    plan = decode(plan_path.read_text(encoding="utf-8-sig"))
    if canonical(plan, "plan_hash") != plan["plan_hash"] or plan["plan_hash"] != audit["plan_hash"]:
        raise ValueError("plan binding mismatch")
    protocol = {"schema": SCHEMA, "mode": "OFFLINE_QUALITY_ONLY", "rules": RULES,
                "limits": LIMITS, "base_plan": ref(plan_path), "plan_hash": plan["plan_hash"],
                "quality_audit": ref(audit_path), "input_manifest_hash": audit["input_manifest_hash"],
                "minimum_events_before_any_claim": plan["outcome_contract"]["minimum_events_before_any_claim"],
                "hypothesis_modified": False, "network_authorized": False,
                "evaluator_authorized": False, "schedules_resume_authorized": False,
                "code": [ref(root / "trading_mvp/src" / name) for name in (
                    "premarket_depth_sampling_protocol.py", "premarket_forward_depth_quality.py", "research_checkpoint.py")]}
    protocol["protocol_hash"] = canonical(protocol, "protocol_hash")
    return protocol


def validate_protocol(protocol: dict, root: Path) -> dict:
    if (protocol.get("schema") != SCHEMA or protocol.get("rules") != RULES or protocol.get("limits") != LIMITS
            or protocol.get("protocol_hash") != canonical(protocol, "protocol_hash")
            or protocol.get("mode") != "OFFLINE_QUALITY_ONLY"):
        raise ValueError("protocol contract mismatch")
    for flag in ("network_authorized", "evaluator_authorized", "schedules_resume_authorized", "hypothesis_modified"):
        if protocol.get(flag) is not False:
            raise ValueError(f"forbidden protocol authorization: {flag}")
    expected = {str((root / "trading_mvp/src" / name).resolve()) for name in (
        "premarket_depth_sampling_protocol.py", "premarket_forward_depth_quality.py", "research_checkpoint.py")}
    if {c["path"] for c in protocol["code"]} != expected:
        raise ValueError("code bindings missing")
    for binding in [protocol["base_plan"], *protocol["code"]]:
        verify_ref(binding, root)
    audit = verify_audit(protocol["quality_audit"], root)
    plan = decode(Path(protocol["base_plan"]["path"]).read_text(encoding="utf-8-sig"))
    if (protocol["plan_hash"] != audit["plan_hash"] or protocol["plan_hash"] != canonical(plan, "plan_hash")
            or protocol["input_manifest_hash"] != audit["input_manifest_hash"]
            or protocol["minimum_events_before_any_claim"] != plan["outcome_contract"]["minimum_events_before_any_claim"]):
        raise ValueError("protocol input binding mismatch")
    return audit


def run(protocol: dict, root: Path) -> dict:
    begun = time.monotonic()
    audit = validate_protocol(protocol, root)
    plan = decode(Path(protocol["base_plan"]["path"]).read_text(encoding="utf-8-sig"))
    results, identities = [], []
    candidates = [e for e in audit["events"] if e["candidate"]]
    if sum(e["bytes"] for e in candidates) > LIMITS["max_input_bytes"]:
        raise ValueError("bounded input budget exceeded")
    for item in candidates:
        path = verify_ref(item, root)
        rows = []
        with path.open("rb") as stream:
            while line := stream.readline(LIMITS["max_line_bytes"] + 1):
                if len(line) > LIMITS["max_line_bytes"] or time.monotonic() - begun > LIMITS["max_runtime_sec"]:
                    raise ValueError("bounded audit budget exceeded")
                rows.append(decode(line.decode("utf-8")))
        event = item["event"]
        identity = {**event, "id": f"{event['venue']}:{event['base']}:{event['t0_ts']}"}
        identities.append(identity)
        results.append({"event_id": identity["id"], "source": ref(path),
            "candidate_is_not_final_eligibility": True,
            "legs": {leg: audit_leg(rows, leg=leg, t0=event["t0_ts"], start=event["capture_from_ts"],
                      end=event["capture_to_ts"], interval=plan["capture"]["snapshot_interval_sec"])
                     for leg in ("perp", "spot")}})
        print(f"Audited {identity['id']}: timing/flags only", flush=True)
    validate_protocol(protocol, root)
    if time.monotonic() - begun > LIMITS["max_runtime_sec"]:
        raise ValueError("runtime budget exceeded")
    groups = dependence_groups(identities)
    result = {"schema": "premarket_depth_sampling_diagnostics_v1", "status": "OFFLINE_QUALITY_COMPLETE",
        "protocol_hash": protocol["protocol_hash"], "input_manifest_hash": audit["input_manifest_hash"],
        "events": results, "dependence_review_components": groups,
        "summary": {"structural_candidates": len(results), "dependency_components": len(groups),
                    "minimum_events_before_any_claim": protocol["minimum_events_before_any_claim"],
                    "independent_sample_certified": False, "network_requests": 0,
                    "returns_or_pnl_computed": False, "mechanism_evaluated": False,
                    "schedule_resumed": False},
        "next_step": "visible_single_writer_runtime_repair_before_any_schedule_resume",
        "limits": LIMITS}
    result["report_hash"] = canonical(result, "report_hash")
    return result


def write_new(path: Path, value: dict):
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(content) > LIMITS["max_output_bytes"]:
        raise ValueError("output budget exceeded")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    guard = decode((root / "docs/agent-log/trading-mvp-autopilot-state.json").read_text(encoding="utf-8-sig"))
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(guard["observed_at_utc"].replace("Z", "+00:00"))).total_seconds()
    if (not 0 <= age <= 300 or guard["usage"]["decision"] != "CONTINUE"
            or guard["usage"]["remaining_percent"] <= 15
            or guard["decision"] != "PREMARKET_DEPTH_QUALITY_COMPLETE_INSUFFICIENT_SAMPLE"
            or guard["gate"]["status"] != "READY_FOR_POSTPROCESS"
            or (root / "docs/agent-log/active-market-data-writer-claim.json").exists()):
        raise ValueError("fresh offline checkpoint and quota required")
    if args.freeze_only:
        write_new(args.protocol, freeze(root))
        print("OFFLINE_PROTOCOL_FROZEN_NO_LAUNCH")
    else:
        if args.output is None or args.output.exists():
            raise ValueError("new output path required")
        result = run(decode(args.protocol.read_text(encoding="utf-8-sig")), root)
        write_new(args.output, result)
        print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
