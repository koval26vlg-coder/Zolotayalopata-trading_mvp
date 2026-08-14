from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = (
    REPO_ROOT
    / "tools"
    / "start_exact_approved_slow_liquidity_official_currentness_topology_visible.ps1"
)


def _launcher() -> str:
    return LAUNCHER_PATH.read_text(encoding="utf-8")


def test_embedded_worker_is_valid_python_and_emits_only_reason_codes() -> None:
    launcher = _launcher()
    match = re.search(
        r"\$workerCode = @'\n(?P<worker>.*?)\n'@",
        launcher,
        flags=re.DOTALL,
    )
    assert match is not None
    worker = match.group("worker")
    compile(worker, str(LAUNCHER_PATH), "exec")
    assert '"reason": reason_code' in worker
    assert 'file=sys.stderr' in worker
    assert '"OFFICIAL_TOPOLOGY_HTTP_REQUEST_FAILED"' in worker
    assert '"TOPOLOGY_INTERNAL_RUNTIME_FAILURE"' in worker
    assert '"identity_evidence_created": False' in worker
    assert '"request_plan_created": False' in worker
    assert '"currentness_verdict_created": False' in worker


def test_launcher_retains_exact_guard_and_hard_limits() -> None:
    launcher = _launcher()
    assert "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY" in launcher
    assert "2026-08-14T07:45:00+03:00" in launcher
    assert "2026-08-14T08:00:00+03:00" in launcher
    assert "AddSeconds(300)" in launcher
    assert "hard_output_cap_bytes = 10000000" in launcher
    assert "remaining_percent -le 15" in launcher
    assert "single_use_launch_record_exists" in launcher


def test_output_parent_is_created_only_after_global_writer_claim() -> None:
    launcher = _launcher()
    claim_index = launcher.index("$claimToken = [string]$claim.ownership_token")
    parent_index = launcher.index("$outputParent = Split-Path -Parent $OutputPath")
    runtime_index = launcher.index("$runtimeProcess = Start-TopologyRuntimeProcess")
    assert claim_index < parent_index < runtime_index


def test_failure_record_keeps_conservative_network_state_and_no_retry() -> None:
    launcher = _launcher()
    assert "$launchRecord.failure_reason_code" in launcher
    assert "$launchRecord.network_access_state" in launcher
    assert 'retry_authorized = $false' in launcher
    assert "STOPPED_INCOMPLETE; retry is not authorized" in launcher
