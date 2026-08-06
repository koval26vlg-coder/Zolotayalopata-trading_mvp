from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "tools" / "check_dense_ws_host_readiness.ps1"


class DenseWsHostReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CHECKER.read_text(encoding="utf-8-sig")

    def test_checks_hidden_lid_action_for_ac_and_battery(self) -> None:
        self.assertIn('"/QH"', self.source)
        self.assertIn("LIDACTION", self.source)
        self.assertIn("lid_action_ac_index", self.source)
        self.assertIn("lid_action_dc_index", self.source)
        self.assertIn("ac_lid_close_can_interrupt_run", self.source)
        self.assertIn("battery_lid_close_can_interrupt_run", self.source)

    def test_blocks_only_strong_windows_reboot_markers(self) -> None:
        self.assertIn("Component Based Servicing\\RebootPending", self.source)
        self.assertIn("WindowsUpdate\\Auto Update\\RebootRequired", self.source)
        self.assertIn("windows_reboot_pending", self.source)
        self.assertIn("pending_file_rename_operations_present", self.source)
        self.assertIn("pending_file_rename_operations_count", self.source)

    def test_remains_read_only_and_does_not_start_work(self) -> None:
        self.assertIn("system_setting_changed = $false", self.source)
        self.assertIn("network_request_performed = $false", self.source)
        self.assertIn("writer_started = $false", self.source)
        self.assertNotIn("/SETACTIVE", self.source.upper())
        self.assertNotIn("/SETACVALUEINDEX", self.source.upper())
        self.assertNotIn("/SETDCVALUEINDEX", self.source.upper())
        self.assertNotIn("Restart-Computer", self.source)


if __name__ == "__main__":
    unittest.main()
