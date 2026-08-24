from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_verification import (
    build_runtime_manifest_spot_v2,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash_without


SCHEMA = "trading_mvp_slow_liquidity_spot_v2_runtime_refreeze_20260817_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_PATH = (
    REPO_ROOT
    / "docs/plans/drafts/"
    "slow-liquidity-official-asset-identity-verification-proposal-20260815-spot-v2.json"
)
PROPOSAL_HASH = (
    "4ff5732fed76dd70ab1208253dfdf617aa33ac9d55580dffe5d08d4f5cae86bf"
)
PROPOSAL_FILE_SHA256 = (
    "64bedf76b55a1bdada04c9b627f0df5c93cc47a329a709783cad16aa1ba02d48"
)
APPROVAL_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals/"
    "2026-08-15-slow-liquidity-official-identity-offline-spot-v2-approval.json"
)
OLD_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/"
    "slow-liquidity-official-identity-runtime-manifest-20260815-spot-v2.json"
)
OLD_MANIFEST_HASH = (
    "bc726311f22b81608da2de86ee0b997fdbfb5545f9675deaecb5df25a245a416"
)
REFREEZE_PATH = (
    REPO_ROOT
    / "docs/plans/"
    "slow-liquidity-official-identity-runtime-manifest-20260817-spot-v2-refreeze.json"
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
GUARD_CHECKER_PATH = REPO_ROOT / "tools/check_trading_mvp_autopilot.ps1"
AUTOPILOT_GUARD_MODULE_PATH = (
    REPO_ROOT / "trading_mvp/src/autopilot_guard.py"
)
READINESS_MODULE_PATH = (
    REPO_ROOT / "trading_mvp/src/one_week_edge_sprint_readiness.py"
)


class SpotV2RuntimeRefreezeError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotV2RuntimeRefreezeError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_refreeze_manifest(generated_at_utc: str) -> dict[str, Any]:
    manifest = build_runtime_manifest_spot_v2(
        proposal_path=PROPOSAL_PATH,
        expected_proposal_hash=PROPOSAL_HASH,
        expected_proposal_file_sha256=PROPOSAL_FILE_SHA256,
        approval_receipt_path=APPROVAL_RECEIPT_PATH,
        runtime_module_path=RUNTIME_MODULE_PATH,
        synthetic_tests_path=SYNTHETIC_TESTS_PATH,
        launcher_path=LAUNCHER_PATH,
        generated_at_utc=generated_at_utc,
    )
    wrapper: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "provenance_refreeze_after_shared_module_drift",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "reason": (
            "The shared readiness and autopilot-guard modules legitimately "
            "changed after the 2026-08-15 spot-v2 freeze (forward-accrual "
            "readiness era). This artifact re-freezes the runtime binding to "
            "the current modules. Execution remains not approved and the "
            "branch stays closed; the original 2026-08-15 manifest is "
            "preserved untouched as the historical immutable record that "
            "accepted-plan chains still reference."
        ),
        "supersedes_for_provenance": {
            "path": str(OLD_MANIFEST_PATH),
            "manifest_hash": OLD_MANIFEST_HASH,
            "still_authoritative_for_existing_chains": True,
        },
        "runtime_manifest": manifest,
    }
    wrapper["refreeze_hash"] = canonical_hash_without(wrapper, "refreeze_hash")
    validate_refreeze_manifest(wrapper)
    return wrapper


def validate_refreeze_manifest(wrapper: Mapping[str, Any]) -> None:
    _require(wrapper.get("schema") == SCHEMA, "refreeze schema mismatch")
    manifest = wrapper.get("runtime_manifest") or {}
    _require(
        manifest.get("execution_authorization", {}).get("approved") is False,
        "refreeze manifest must not approve execution",
    )
    _require(
        manifest.get("manifest_hash")
        == canonical_hash_without(manifest, "manifest_hash"),
        "inner manifest hash is not internally consistent",
    )
    runtime = manifest.get("runtime") or {}
    current_bindings = {
        "module_sha256": RUNTIME_MODULE_PATH,
        "synthetic_tests_sha256": SYNTHETIC_TESTS_PATH,
        "launcher_sha256": LAUNCHER_PATH,
        "guard_checker_sha256": GUARD_CHECKER_PATH,
        "autopilot_guard_module_sha256": AUTOPILOT_GUARD_MODULE_PATH,
        "readiness_module_sha256": READINESS_MODULE_PATH,
    }
    for field, path in current_bindings.items():
        bound = str(runtime.get(field) or "")
        _require(
            bound == _sha256_file(path),
            f"refreeze does not bind the current {field}",
        )
    supersede = wrapper.get("supersedes_for_provenance") or {}
    _require(
        supersede.get("manifest_hash") == OLD_MANIFEST_HASH,
        "supersede binding mismatch",
    )
    _require(
        OLD_MANIFEST_PATH.is_file()
        and _sha256_file(OLD_MANIFEST_PATH) is not None,
        "original manifest must remain present",
    )
    old = json.loads(OLD_MANIFEST_PATH.read_text(encoding="utf-8"))
    _require(
        old.get("manifest_hash") == OLD_MANIFEST_HASH,
        "original manifest was mutated",
    )
    _require(
        wrapper.get("refreeze_hash")
        == canonical_hash_without(wrapper, "refreeze_hash"),
        "refreeze hash mismatch",
    )


def write_refreeze(generated_at_utc: str) -> Path:
    wrapper = build_refreeze_manifest(generated_at_utc)
    content = json.dumps(wrapper, indent=2, ensure_ascii=False) + "\n"
    if REFREEZE_PATH.exists():
        _require(
            REFREEZE_PATH.read_text(encoding="utf-8") == content,
            f"immutable artifact mismatch: {REFREEZE_PATH}",
        )
        return REFREEZE_PATH
    REFREEZE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFREEZE_PATH.write_text(content, encoding="utf-8")
    return REFREEZE_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-refreeze", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args(argv)
    if not args.write_refreeze:
        raise SystemExit("no authorized action requested")
    generated = args.generated_at_utc or (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    path = write_refreeze(generated)
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": "REFREEZE_WRITTEN",
                "path": str(path),
                "refreeze_hash": wrapper["refreeze_hash"],
                "inner_manifest_hash": wrapper["runtime_manifest"]["manifest_hash"],
                "old_manifest_hash_unchanged": OLD_MANIFEST_HASH,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
