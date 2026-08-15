#!/usr/bin/env python3
"""Freeze the fail-closed slow-liquidity identity runtime v7 offline."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_official_identity_verification import (  # type: ignore
    PARENT_IDENTITY_V6_RUNTIME_FILE_SHA256,
    PARENT_IDENTITY_V6_RUNTIME_HASH,
    PHASE1_STATUS,
    RUNTIME_REVISION_V7,
    _load_json,
    _sha256_file,
    _write_immutable_json,
    build_runtime_manifest_v7,
    validate_runtime_manifest,
)

PROPOSAL_PATH = (
    REPO_ROOT
    / "docs/plans/drafts/slow-liquidity-official-asset-identity-verification-proposal-20260813-v1.json"
)
PROPOSAL_HASH = "3a4479cacaceb310556821df8bd0f28d5cb1dac06644764c9b209bf3e234d8a4"
PROPOSAL_FILE_SHA256 = (
    "52d2c848888577a61e6994b57786616a9732c2ec384d6c4633325123b1b63c62"
)
OFFLINE_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals/2026-08-13-slow-liquidity-official-identity-offline-v1-approval.json"
)
PARENT_V6_RUNTIME_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-runtime-manifest-20260814-v6.json"
)
OUTPUT_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-runtime-manifest-20260815-v7.json"
)
EXECUTION_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-execution-manifest-20260815-v7.json"
)
REJECTED_V6_ARTIFACT_PATHS = (
    REPO_ROOT
    / "docs/agent-log/approvals/2026-08-15-slow-liquidity-identity-v6-execution-approval-receipt.json",
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-execution-manifest-20260814-v6.json",
)
RUNTIME_MODULE_PATH = (
    REPO_ROOT
    / "trading_mvp/src/slow_liquidity_official_identity_verification.py"
)
SYNTHETIC_TESTS_PATH = (
    REPO_ROOT
    / "trading_mvp/tests/test_slow_liquidity_official_identity_verification.py"
)
LAUNCHER_PATH = (
    REPO_ROOT
    / "tools/start_exact_approved_slow_liquidity_official_identity_visible.ps1"
)


def _timestamp_for_freeze() -> str:
    if OUTPUT_PATH.exists():
        observed = _load_json(OUTPUT_PATH, "identity v7 runtime manifest")
        generated_at_utc = observed.get("generated_at_utc")
        if not isinstance(generated_at_utc, str):
            raise SystemExit("existing v7 runtime has no valid generated_at_utc")
        return generated_at_utc
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def main() -> int:
    for required in (
        PROPOSAL_PATH,
        OFFLINE_RECEIPT_PATH,
        PARENT_V6_RUNTIME_PATH,
        RUNTIME_MODULE_PATH,
        SYNTHETIC_TESTS_PATH,
        LAUNCHER_PATH,
    ):
        if not required.is_file():
            raise SystemExit(f"required file missing: {required}")

    parent_file_sha256 = _sha256_file(PARENT_V6_RUNTIME_PATH)
    if parent_file_sha256 != PARENT_IDENTITY_V6_RUNTIME_FILE_SHA256:
        raise SystemExit("identity v6 parent runtime file hash mismatch")
    parent = _load_json(PARENT_V6_RUNTIME_PATH, "identity v6 parent runtime")
    if parent.get("manifest_hash") != PARENT_IDENTITY_V6_RUNTIME_HASH:
        raise SystemExit("identity v6 parent runtime canonical hash mismatch")

    blocked_paths = [path for path in REJECTED_V6_ARTIFACT_PATHS if path.exists()]
    if EXECUTION_MANIFEST_PATH.exists():
        blocked_paths.append(EXECUTION_MANIFEST_PATH)
    if blocked_paths:
        joined = ", ".join(str(path) for path in blocked_paths)
        raise SystemExit(f"execution artifacts must be absent before v7 freeze: {joined}")

    manifest = build_runtime_manifest_v7(
        proposal_path=PROPOSAL_PATH,
        expected_proposal_hash=PROPOSAL_HASH,
        expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
        approval_receipt_path=OFFLINE_RECEIPT_PATH,
        parent_runtime_manifest_path=PARENT_V6_RUNTIME_PATH,
        runtime_module_path=RUNTIME_MODULE_PATH,
        synthetic_tests_path=SYNTHETIC_TESTS_PATH,
        launcher_path=LAUNCHER_PATH,
        generated_at_utc=_timestamp_for_freeze(),
    )
    validate_runtime_manifest(manifest)
    written = _write_immutable_json(OUTPUT_PATH, manifest)

    result = {
        "status": PHASE1_STATUS,
        "runtime_revision": RUNTIME_REVISION_V7,
        "runtime_manifest_path": str(written),
        "runtime_manifest_file_sha256": _sha256_file(written),
        "runtime_manifest_hash": manifest["manifest_hash"],
        "parent_runtime_file_sha256": parent_file_sha256,
        "parent_runtime_hash": parent["manifest_hash"],
        "approval_receipt_created": False,
        "execution_manifest_created": False,
        "invalid_execution_approval_artifacts_reused": False,
        "network_accessed": False,
        "official_source_content_read": False,
        "identity_output_created": False,
        "separate_exact_code_bound_execution_approval_required": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
