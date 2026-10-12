import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from premarket_depth_sampling_protocol import (audit_leg, dependence_groups, freeze,
                                               run, validate_protocol, write_new)
from premarket_forward_depth_quality import SCHEMA, canonical, ref


def book(ts, *, inside=False, short=False):
    return {"record": "book", "leg": "perp", "ts": ts, "usable": True,
            "bid_inside_spread_1.0pct": inside, "ask_inside_spread_1.0pct": inside,
            "bid_truncated_1.0pct": False, "ask_truncated_1.0pct": False,
            "bid_levels_short_top25": short, "ask_levels_short_top25": False,
            "levels_bid": 24 if short else 25, "levels_ask": 25}


def event(base, start, stop, venue="gate"):
    return {"id": f"{venue}:{base}:{start}", "base": base, "venue": venue,
            "capture_from_ts": start, "capture_to_ts": stop, "t0_ts": start + 3600}


class SamplingProtocolTests(unittest.TestCase):
    def test_missing_is_never_imputed_zero(self):
        result = audit_leg([book(0), book(40)], leg="perp", t0=0, start=0, end=60, interval=20)
        self.assertEqual(result["slots"]["expected"], 3)
        self.assertEqual(result["slots"]["missing"], 1)
        self.assertEqual(result["missing_runs"], [{"from_rel_sec": 20, "to_rel_sec_exclusive": 40}])
        self.assertFalse(result["interpolation_performed"])

    def test_errors_and_unusable_are_separate_from_no_attempt(self):
        rows = [{"record": "error", "leg": "perp", "ts": 0},
                {"record": "book", "leg": "perp", "ts": 20, "usable": False}]
        result = audit_leg(rows, leg="perp", t0=0, start=0, end=60, interval=20)
        self.assertEqual(result["slots"]["request_error_only"], 1)
        self.assertEqual(result["slots"]["unusable_only"], 1)
        self.assertEqual(result["slots"]["no_attempt"], 1)

    def test_exactly_third_is_not_over_third(self):
        result = audit_leg([book(0, inside=True), book(20), book(40)],
                           leg="perp", t0=0, start=0, end=60, interval=20)
        self.assertEqual(result["diagnostic_measure_route"], "BAND_1PCT")

    def test_over_third_uses_one_route_for_entire_leg(self):
        result = audit_leg([book(0, inside=True), book(20, inside=True), book(40, short=True)],
                           leg="perp", t0=0, start=0, end=60, interval=20)
        self.assertEqual(result["diagnostic_measure_route"], "TOP25")
        self.assertEqual(result["measurement_rows"]["paired_observable"], 2)
        self.assertEqual(result["measurement_rows"]["bid_unobservable"], 1)

    def test_unknown_flag_does_not_become_false(self):
        row = book(0)
        del row["bid_inside_spread_1.0pct"]
        result = audit_leg([row], leg="perp", t0=0, start=0, end=20, interval=20)
        self.assertEqual(result["diagnostic_measure_route"], "UNKNOWN_FLAGS")

    def test_partial_boundary_slot_is_disclosed_not_counted_full(self):
        result = audit_leg([book(7), book(27)], leg="perp", t0=0, start=7, end=40, interval=20)
        self.assertEqual(result["slots"]["expected"], 1)
        self.assertEqual(result["partial_boundary_rows"], 1)

    def test_duplicate_attempts_do_not_inflate_coverage(self):
        result = audit_leg([book(0), book(1)], leg="perp", t0=0, start=0, end=20, interval=20)
        self.assertEqual(result["slots"]["usable"], 1)
        self.assertEqual(result["slots"]["multiple_attempts"], 1)

    def test_spot_has_no_preopen_missing_slots(self):
        row = book(0)
        row["leg"] = "spot"
        result = audit_leg([row], leg="spot", t0=0, start=-60, end=20, interval=20)
        self.assertEqual(result["slots"]["expected"], 1)

    def test_ask_control_is_not_replaced_by_bid_availability(self):
        row = book(0)
        row["ask_truncated_1.0pct"] = True
        result = audit_leg([row], leg="perp", t0=0, start=0, end=20, interval=20)
        self.assertEqual(result["measurement_rows"]["paired_observable"], 0)

    def test_raw_prices_or_returns_do_not_enter_output(self):
        row = book(0)
        row.update({"mid": 1e30, "bid_depth_top25": 1e25, "ret_72h": 12345})
        result = audit_leg([row], leg="perp", t0=0, start=0, end=20, interval=20)
        import json
        self.assertNotIn("ret_72h", json.dumps(result))
        self.assertNotIn("1e+30", json.dumps(result))

    def test_time_clusters_are_transitive(self):
        events = [event("A", 0, 10), event("B", 9, 20), event("C", 19, 30), event("D", 31, 40)]
        groups = dependence_groups(events)
        self.assertEqual(sorted(len(g["members"]) for g in groups), [1, 3])
        self.assertEqual(groups, dependence_groups(list(reversed(events))))

    def test_same_base_across_venues_not_independent(self):
        groups = dependence_groups([event("A", 0, 10), event("A", 20, 30, "okx")])
        self.assertEqual(len(groups), 1)

    def test_touching_windows_do_not_overlap(self):
        self.assertEqual(len(dependence_groups([event("A", 0, 10), event("B", 10, 20)])), 2)

    def test_invalid_grid_arguments_rejected(self):
        for interval in (0, -1):
            with self.assertRaises(ValueError):
                audit_leg([], leg="perp", t0=0, start=0, end=20, interval=interval)

    def test_invalid_dependency_windows_rejected(self):
        for end in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                dependence_groups([event("A", 0, end)])


class ProtocolBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.captures = self.root / "captures"
        self.captures.mkdir()
        self.raw = self.captures / "a.jsonl"
        self.raw.write_text(json.dumps(book(1)) + "\n", encoding="utf-8")
        self.plan_path = self.root / "docs/plans/premarket-forward-depth-planonly-20260902-v6.json"
        plan = {"capture": {"snapshot_interval_sec": 20},
                "outcome_contract": {"minimum_events_before_any_claim": 12}}
        plan["plan_hash"] = canonical(plan, "plan_hash")
        write_new(self.plan_path, plan)
        inputs = [ref(self.raw), ref(self.plan_path)]
        self.audit = {"schema": SCHEMA, "plan_hash": plan["plan_hash"], "inputs": inputs,
                      "input_manifest_hash": canonical({"files": inputs}, "unused"),
                      "capture_directory": str(self.captures),
                      "events": [{**ref(self.raw), "candidate": True,
                                  "event": {**event("A", 0, 60), "t0_ts": 0}}],
                      "summary": {"current_plan_structural_candidates": 1,
                                  "minimum_events_before_any_claim": 12,
                                  "mechanism_analysis_performed": False, "pnl_computed": False,
                                  "acceptance_capable": False, "complete_statistical_sample_certified": False}}
        self.audit["report_hash"] = canonical(self.audit, "report_hash")
        write_new(self.root / "docs/analysis/strategy-reconciliation-20260929/depth-quality-v2.json", self.audit)
        code_dir = self.root / "trading_mvp/src"
        code_dir.mkdir(parents=True)
        for name in ("premarket_depth_sampling_protocol.py", "premarket_forward_depth_quality.py", "research_checkpoint.py"):
            (code_dir / name).write_text("# synthetic code binding\n", encoding="utf-8")
        self.protocol = freeze(self.root)

    def test_frozen_protocol_validates(self):
        self.assertEqual(validate_protocol(self.protocol, self.root), self.audit)

    def test_same_count_source_change_rejected(self):
        self.raw.write_text(json.dumps(book(2)) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            validate_protocol(self.protocol, self.root)

    def test_changed_code_rejected(self):
        Path(self.protocol["code"][0]["path"]).write_text("# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            validate_protocol(self.protocol, self.root)

    def test_extra_capture_rejected(self):
        (self.captures / "b.jsonl").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            validate_protocol(self.protocol, self.root)

    def test_rehashed_rules_change_rejected(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["rules"]["missing"] = "ZERO_FILL"
        protocol["protocol_hash"] = canonical(protocol, "protocol_hash")
        with self.assertRaisesRegex(ValueError, "contract mismatch"):
            validate_protocol(protocol, self.root)

    def test_rehashed_authorization_change_rejected(self):
        for field in ("network_authorized", "evaluator_authorized", "schedules_resume_authorized", "hypothesis_modified"):
            protocol = copy.deepcopy(self.protocol)
            protocol[field] = True
            protocol["protocol_hash"] = canonical(protocol, "protocol_hash")
            with self.assertRaisesRegex(ValueError, "forbidden protocol authorization"):
                validate_protocol(protocol, self.root)

    def test_rehashed_input_manifest_change_rejected(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["input_manifest_hash"] = "0" * 64
        protocol["protocol_hash"] = canonical(protocol, "protocol_hash")
        with self.assertRaisesRegex(ValueError, "input binding mismatch"):
            validate_protocol(protocol, self.root)

    def test_no_overwrite_of_artifact(self):
        path = self.root / "result.json"
        write_new(path, {"a": 1})
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            write_new(path, {"a": 2})
        self.assertEqual(path.read_bytes(), before)

    def test_end_to_end_without_network(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = run(self.protocol, self.root)
        self.assertEqual(result["report_hash"], canonical(result, "report_hash"))
        self.assertEqual(result["summary"]["structural_candidates"], 1)
        self.assertFalse(result["summary"]["returns_or_pnl_computed"])
        self.assertEqual(result["events"][0]["legs"]["perp"]["slots"]["missing"], 2)


if __name__ == "__main__":
    unittest.main()
