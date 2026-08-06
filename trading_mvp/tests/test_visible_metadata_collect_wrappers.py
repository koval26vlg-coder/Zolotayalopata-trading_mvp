from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"


class VisibleMetadataCollectWrapperTests(unittest.TestCase):
    def _read(self, name: str) -> str:
        return (TOOLS / name).read_text(encoding="utf-8")

    def test_common_runner_is_bounded_visible_and_fail_closed(self) -> None:
        text = self._read("visible_owned_metadata_collect_common.ps1")
        self.assertIn("[ValidateRange(1, 600)][int]$MaxRuntimeSec", text)
        self.assertIn('"RUNNING", "STOPPED_INCOMPLETE"', text)
        self.assertIn("Start-Process -FilePath $Python", text)
        self.assertIn("-WindowStyle Hidden", text)
        self.assertIn("remaining_sec=", text)
        self.assertIn("bytes=", text)
        self.assertIn("rows=", text)
        self.assertIn("Update-OwnedMetadataRunState", text)
        self.assertIn('-Status "STOPPED_INCOMPLETE"', text)
        self.assertIn("validate-result `", text)

    def test_common_runner_never_serializes_or_prints_credential_value(self) -> None:
        text = self._read("visible_owned_metadata_collect_common.ps1")
        self.assertIn("credential_value_persisted = $false", text)
        self.assertIn("(value hidden)", text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("x-cg-demo-api-key", text)
        self.assertIsNone(
            re.search(
                (
                    r"Write-Host[^\r\n]*\$(?:"
                    r"credential(?![A-Za-z0-9_])|"
                    r"env:TARDIS_API_KEY|"
                    r"env:COINGECKO_DEMO_API_KEY)"
                ),
                text,
                flags=re.IGNORECASE,
            )
        )

    def test_registry_wrapper_uses_main_worktree_module(self) -> None:
        text = self._read("run_canonical_asset_registry_collect_visible.ps1")
        self.assertIn("-ConfirmedCanonicalAssetRegistryCollect", text)
        self.assertIn('"COINGECKO_DEMO_API_KEY"', text)
        self.assertNotIn("$env:COINGECKO_DEMO_API_KEY", text)
        self.assertIn(
            '$Module = Join-Path $RepoRoot '
            '"trading_mvp\\src\\canonical_asset_registry.py"',
            text,
        )
        self.assertNotIn("$ScratchRoot", text)

    def test_identity_wrapper_uses_main_worktree_module(self) -> None:
        text = self._read(
            "run_gate_momentum_identity_metadata_collect_visible.ps1"
        )
        self.assertIn("-ConfirmedGateMomentumIdentityMetadataCollect", text)
        self.assertIn('"TARDIS_API_KEY"', text)
        self.assertNotIn("$env:TARDIS_API_KEY", text)
        self.assertIn(
            '$Module = Join-Path $RepoRoot '
            '"trading_mvp\\src\\gate_momentum_identity.py"',
            text,
        )
        self.assertNotIn("$ScratchRoot", text)

    def test_public_probe_wrapper_uses_main_worktree_module_and_project_gate(
        self,
    ) -> None:
        text = self._read(
            "run_gate_momentum_archive_public_schema_probe_visible.ps1"
        )
        self.assertIn(
            '$Module = Join-Path $RepoRoot '
            '"trading_mvp\\src\\gate_momentum_archive.py"',
            text,
        )
        self.assertIn(
            '$GateChecker = Join-Path $ProjectRoot "tools\\check_active_run_gate.ps1"',
            text,
        )
        self.assertNotIn("$ScratchRoot", text)

    def test_public_probe_wrapper_records_deterministic_nonempty_command(
        self,
    ) -> None:
        text = self._read(
            "run_gate_momentum_archive_public_schema_probe_visible.ps1"
        )
        self.assertIn("$launchCommand =", text)
        self.assertIn("command = $launchCommand", text)
        self.assertNotIn("command = $MyInvocation.Line", text)

    def test_public_probe_wrapper_resets_run_specific_gate_metadata(
        self,
    ) -> None:
        text = self._read(
            "run_gate_momentum_archive_public_schema_probe_visible.ps1"
        )
        self.assertIn('@("next_goal_reason", $GoalReason)', text)
        self.assertRegex(
            text,
            r'"expected_outputs",\s+\[pscustomobject\]@\{',
        )
        self.assertRegex(text, r'"actual_duration_sec",')
        self.assertIn("$runStartedAt", text)


if __name__ == "__main__":
    unittest.main()
