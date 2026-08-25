from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_plan import canonical_plan_hash, validate_plan  # noqa: E402


PLAN = Path(__file__).resolve().parents[2] / "docs" / "plans" / "preipo-perpetual-event-planonly-20260825-v4.json"


class PreIPOPlanTests(unittest.TestCase):
    def test_the_interim_tier_cannot_be_collapsed_into_acceptance(self) -> None:
        """The early read must stay strictly below the acceptance sample.

        The interim tier exists so a verdict can be read sooner without lowering the bar
        that authorises anything. If its number could be raised to meet
        minimum_complete_events, the descriptive read would silently become the
        acceptance decision - which is precisely the shortcut it was built to avoid."""
        import json

        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        gates = plan["acceptance_gates"]
        self.assertLess(
            gates["interim_descriptive_events"], gates["minimum_complete_events"]
        )
        self.assertIs(gates["interim_authorizes"], False)

        collapsed = json.loads(PLAN.read_text(encoding="utf-8"))
        collapsed["acceptance_gates"]["interim_descriptive_events"] = collapsed[
            "acceptance_gates"
        ]["minimum_complete_events"]
        collapsed["plan_hash"] = canonical_plan_hash(
            {k: v for k, v in collapsed.items() if k != "plan_hash"}
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collapsed.json"
            path.write_text(json.dumps(collapsed), encoding="utf-8")
            result = validate_plan(path)
        self.assertFalse(result["ok"])
        self.assertIn("acceptance_interim_tier_not_below_minimum", result["reasons"])

    def test_an_interim_tier_that_authorizes_is_refused(self) -> None:
        import json
        import tempfile

        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        plan["acceptance_gates"]["interim_authorizes"] = True
        plan["plan_hash"] = canonical_plan_hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authorizing.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            result = validate_plan(path)
        self.assertFalse(result["ok"])
        self.assertIn("acceptance_interim_tier_must_not_authorize", result["reasons"])

    def test_immutable_plan_is_valid_and_uses_only_okx_and_gate(self) -> None:
        result = validate_plan(PLAN)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PLAN_OK")
        self.assertEqual(set(result["venues"]), {"okx", "gate"})
        self.assertEqual(result["plan_id"], "preipo_perpetual_event_20260825_v4")

    def test_plan_hash_is_canonical_and_excludes_stored_hash(self) -> None:
        import json

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertEqual(payload["plan_hash"], canonical_plan_hash(payload))

    def test_bybit_is_candidate_only_until_official_contract_and_timestamp_method(self) -> None:
        import json

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertNotIn("bybit", payload["venues"])
        self.assertIn("bybit", payload["candidate_venues"])
        self.assertIn("official pre-IPO contract", payload["bybit_extension_condition"])
        self.assertFalse(payload["proxy_acceptance_allowed"])

    def test_collection_schedule_starts_at_six_hours_with_five_minute_capture(self) -> None:
        import json

        payload = json.loads(PLAN.read_text(encoding="utf-8"))
        automation = payload["automation"]
        self.assertEqual(automation["schedule_interval_sec"], 6 * 60 * 60)
        self.assertEqual(automation["scheduler_wake_interval_sec"], 5 * 60)
        self.assertEqual(automation["capture_duration_sec"], 5 * 60)
        self.assertEqual(payload["recovery_contract"]["interval_sec"], 6 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
