from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import slow_liquidity_listing_momentum_forward_expansion_plan as expansion_plan  # noqa: E402


AUTOMATION_LAUNCHER = (
    ROOT / "tools" / "start_listing_momentum_forward_automation_visible.ps1"
)
EXPANSION_TICK_LAUNCHER = (
    ROOT / "tools" / "start_listing_momentum_forward_expansion_tick_visible.ps1"
)


class ListingMomentumAutomationTests(unittest.TestCase):
    def test_visible_orchestrator_has_durable_next_interval_recovery(self) -> None:
        text = AUTOMATION_LAUNCHER.read_text(encoding="utf-8")
        for marker in (
            "RETRY_NEXT_INTERVAL",
            "pending_retry",
            "next_interval_at_utc",
            "zolotyaylopata-listing-momentum-monitor",
            "WindowStyle Normal",
            "-VisibleWorker",
            "failed_or_deferred_track_retries_on_next_scheduled_interval",
        ):
            self.assertIn(marker, text)

    def test_expansion_plan_excludes_retired_combined_launcher_and_binds_dedicated_tick(
        self,
    ) -> None:
        plan = json.loads(expansion_plan.FORWARD_PLAN_PATH.read_text(encoding="utf-8"))
        expansion_plan.validate_plan(plan)
        roles = {item["role"]: item for item in plan["implementation"]["files"]}
        self.assertNotIn("automation_launcher", roles)
        self.assertIn("visible_tick_launcher", roles)
        self.assertEqual(
            Path(roles["visible_tick_launcher"]["path"]).resolve(),
            EXPANSION_TICK_LAUNCHER.resolve(),
        )
        self.assertTrue(
            plan["guard_contract"][
                "canonical_primary_spot_owned_by_dedicated_repository"
            ]
        )
        self.assertFalse(plan["guard_contract"]["combined_launcher_scheduler_routable"])
        self.assertIn(EXPANSION_TICK_LAUNCHER.name, plan["commands"]["visible_tick"])
        self.assertNotIn(AUTOMATION_LAUNCHER.name, plan["commands"]["visible_tick"])


if __name__ == "__main__":
    unittest.main()
