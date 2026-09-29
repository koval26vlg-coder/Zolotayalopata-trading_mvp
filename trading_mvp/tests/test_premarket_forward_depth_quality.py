import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from premarket_forward_depth_quality import audit_capture, build_audit, canonical, decode


def plan_fixture():
    plan = {"plan_id": "test_v6", "hypothesis": {"statement": "synthetic"},
            "anchor_check": {"max_first_spot_book_delay_min": 5},
            "capture": {"snapshot_interval_sec": 20, "window_after_min": 120},
            "notice_limit": {"minimum_useful_pre_min": 30},
            "qualification": {"min_lead_sec": 3600, "max_lead_days": 30},
            "implementation": {"files": []},
            "outcome_contract": {"minimum_events_before_any_claim": 12}}
    plan["plan_hash"] = canonical(plan, "plan_hash")
    return plan


def records_fixture(plan, *, t0=100000):
    event = {"venue": "gate", "base": "TEST", "t0_ts": t0,
             "t0_utc": "1970-01-02T03:46:40Z", "perp_ct_val": "10",
             "perp_launched_ts": t0 - 86400,
             "spot_symbol": "TEST_USDT", "perp_symbol": "TEST_USDT",
             "pre_window_available_min": 60, "capture_from_ts": t0 - 3600,
             "capture_to_ts": t0 + 7200}
    rows = [{"record": "header", "schema": "trading_mvp_premarket_forward_depth_capture_v1",
             "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
             "hypothesis": plan["hypothesis"], "event": event,
             "size_units": "VENUE_NATIVE_CONTRACTS_OR_BASE_NOT_CONVERTED"}]
    for rel in (-60, -30, -1, 0, 30, 60, 119.9):
        for leg in (["perp", "spot"] if rel >= 0 else ["perp"]):
            rows.append({"record": "book", "leg": leg, "symbol": "TEST_USDT",
                         "ts": t0 + rel * 60, "rel_min": rel, "usable": True,
                         "best_bid": 99, "best_ask": 101, "mid": 100,
                         "top_bids": [[99, 2]], "top_asks": [[101, 3]],
                         "bid_depth_top25": 198, "ask_depth_top25": 303,
                         "response_sha256": "a" * 64, "response_bytes": 100})
    from datetime import datetime, timezone
    rows.append({"record": "footer", "finished_at_utc": datetime.fromtimestamp(
        t0 + 7200, timezone.utc).isoformat(), "snapshots": len(rows) - 1, "errors": 0,
        "reached_budget": False, "first_spot_book_rel_min": 0, "anchor_suspect": False})
    return rows


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = plan_fixture()
        self.rows = records_fixture(self.plan)
        self.path = self.root / "capture.jsonl"

    def write(self):
        self.path.write_text("".join(json.dumps(r) + "\n" for r in self.rows), encoding="utf-8")

    def audit(self):
        self.write()
        return audit_capture(self.path, {self.plan["plan_hash"]: self.plan}, self.plan)

    def test_valid_is_only_structural_candidate(self):
        row = self.audit()
        self.assertTrue(row["candidate"])
        self.assertTrue(row["sampling_gaps_require_review"])
        self.assertFalse(row["units"]["cross_leg_absolute_depth_compared"])

    def test_partial_stopped_run_is_not_usable(self):
        self.rows.pop()
        self.assertFalse(self.audit()["candidate"])

    def test_duplicate_header_rejected(self):
        self.rows.insert(1, self.rows[0])
        self.assertFalse(self.audit()["candidate"])

    def test_wrong_plan_hash_rejected(self):
        self.rows[0]["plan_hash"] = "f" * 64
        self.assertIn("PLAN_BINDING_MISMATCH", self.audit()["integrity_errors"])

    def test_same_count_changed_bytes_changes_binding(self):
        first = self.audit()
        self.rows[1]["response_sha256"] = "b" * 64
        second = self.audit()
        self.assertEqual(first["record_count"], second["record_count"])
        self.assertNotEqual(first["file_sha256"], second["file_sha256"])

    def test_short_pre_window_excluded(self):
        self.rows[0]["event"]["pre_window_available_min"] = 14
        self.assertIn("PRE_WINDOW_TOO_SHORT", self.audit()["exclusion_reasons"])

    def test_footer_counts_verified(self):
        self.rows[-1]["snapshots"] += 1
        self.assertIn("FOOTER_COUNT_MISMATCH", self.audit()["integrity_errors"])

    def test_late_footer_does_not_certify_truncated_window(self):
        for row in self.rows:
            if row.get("rel_min") == 119.9:
                row["rel_min"] = 64.2
                row["ts"] = 100000 + 64.2 * 60
        result = self.audit()
        self.assertFalse(result["candidate"])
        self.assertIn("PERP_POST_WINDOW_TRUNCATED", result["exclusion_reasons"])

    def test_early_footer_rejected(self):
        self.rows[-1]["finished_at_utc"] = "1970-01-01T00:00:00Z"
        self.assertIn("EARLY_FOOTER", self.audit()["integrity_errors"])

    def test_spoofed_anchor_rejected(self):
        self.rows[-1]["first_spot_book_rel_min"] = 1
        self.assertIn("FOOTER_ANCHOR_MISMATCH", self.audit()["integrity_errors"])

    def test_contract_multiplier_not_ignored(self):
        self.rows[0]["event"]["perp_ct_val"] = "0"
        self.assertFalse(self.audit()["candidate"])

    def test_top25_recomputed_not_trusted(self):
        self.rows[1]["bid_depth_top25"] = 999
        self.assertIn("TOP_DEPTH_SUM_MISMATCH", self.audit()["integrity_errors"])

    def test_reversed_time_rejected(self):
        self.rows[1], self.rows[2] = self.rows[2], self.rows[1]
        self.assertIn("DUPLICATE_OR_REVERSED_TIMESTAMP", self.audit()["integrity_errors"])

    def test_strict_json(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '[]'):
            with self.assertRaises(ValueError):
                decode(text)

    def test_new_t0_supersedes_old_never_double_counts(self):
        self.write()
        other = self.root / "new.jsonl"
        other.write_text("".join(json.dumps(r) + "\n" for r in records_fixture(
            self.plan, t0=110000)), encoding="utf-8")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps(self.plan), encoding="utf-8")
        armed = self.root / "armed.json"
        armed.write_text("{}", encoding="utf-8")
        report = build_audit(self.root, [plan], plan, armed)
        self.assertEqual(report["summary"]["current_plan_structural_candidates"], 1)
        self.assertIn("SUPERSEDED_SCHEDULE", report["events"][0]["exclusion_reasons"])
        self.assertFalse(report["summary"]["pnl_computed"])

    def test_historical_plan_not_pooled(self):
        historical = copy.deepcopy(self.plan)
        historical["plan_id"] = "v3"
        historical["plan_hash"] = canonical(historical, "plan_hash")
        self.rows = records_fixture(historical)
        self.write()
        row = audit_capture(self.path, {historical["plan_hash"]: historical}, self.plan)
        self.assertIn("HISTORICAL_PLAN_NOT_POOLED", row["exclusion_reasons"])


if __name__ == "__main__":
    unittest.main()
