#!/usr/bin/env python3
"""Freeze the fail-closed slow-liquidity spot v2 identity runtime offline."""
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
    PHASE1_STATUS,
    RUNTIME_REVISION_SPOT_V2,
    SPOT_V2_OFFLINE_AUTHORIZATION_TEXT,
    _sha256_file,
    freeze_offline_bundle_spot_v2,
    validate_runtime_manifest,
    _load_json,
)

PROPOSAL_PATH = (
    REPO_ROOT
    / "docs/plans/drafts/slow-liquidity-official-asset-identity-verification-proposal-20260815-spot-v2.json"
)
PROPOSAL_HASH = "4ff5732fed76dd70ab1208253dfdf617aa33ac9d55580dffe5d08d4f5cae86bf"
PROPOSAL_FILE_SHA256 = (
    "64bedf76b55a1bdada04c9b627f0df5c93cc47a329a709783cad16aa1ba02d48"
)
RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals/2026-08-15-slow-liquidity-official-identity-offline-spot-v2-approval.json"
)
RUNTIME_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-runtime-manifest-20260815-spot-v2.json"
)
EXECUTION_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-execution-manifest-20260815-spot-v2.json"
)
RUNTIME_MODULE_PATH = (
    REPO_ROOT / "trading_mvp/src/slow_liquidity_official_identity_verification.py"
)
SYNTHETIC_TESTS_PATH = (
    REPO_ROOT / "trading_mvp/tests/test_slow_liquidity_official_identity_verification.py"
)
LAUNCHER_PATH = (
    REPO_ROOT / "tools/start_exact_approved_slow_liquidity_official_identity_visible.ps1"
)


def _timestamp(path: Path, field: str, fallback: str) -> str:
    if not path.exists():
        return fallback
    observed = _load_json(path, str(path.name))
    value = observed.get(field)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"existing artifact missing {field}: {path}")
    return value


def main() -> int:
    for required in (
        PROPOSAL_PATH,
        RUNTIME_MODULE_PATH,
        SYNTHETIC_TESTS_PATH,
        LAUNCHER_PATH,
    ):
        if not required.is_file():
            raise SystemExit(f"required file missing: {required}")
    if _sha256_file(PROPOSAL_PATH) != PROPOSAL_FILE_SHA256:
        raise SystemExit("spot v2 proposal file hash mismatch")
    if EXECUTION_MANIFEST_PATH.exists():
        raise SystemExit(
            f"execution artifacts must be absent before spot v2 freeze: {EXECUTION_MANIFEST_PATH}"
        )

    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    result = freeze_offline_bundle_spot_v2(
        proposal_path=PROPOSAL_PATH,
        expected_proposal_hash=PROPOSAL_HASH,
        expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
        approval_receipt_path=RECEIPT_PATH,
        runtime_manifest_path=RUNTIME_PATH,
        runtime_module_path=RUNTIME_MODULE_PATH,
        synthetic_tests_path=SYNTHETIC_TESTS_PATH,
        launcher_path=LAUNCHER_PATH,
        approved_at_utc=_timestamp(RECEIPT_PATH, "approved_at_utc", now),
        generated_at_utc=_timestamp(RUNTIME_PATH, "generated_at_utc", now),
        user_authorization_text=SPOT_V2_OFFLINE_AUTHORIZATION_TEXT,
        response_annotation_index=1,
    )
    manifest = _load_json(RUNTIME_PATH, "spot v2 runtime manifest")
    validate_runtime_manifest(manifest)
    result["status"] = PHASE1_STATUS
    result["runtime_revision"] = RUNTIME_REVISION_SPOT_V2
    result["execution_manifest_created"] = False
    result["invalid_execution_approval_artifacts_reused"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
