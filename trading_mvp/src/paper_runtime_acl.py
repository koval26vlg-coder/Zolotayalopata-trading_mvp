from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence

from historical_basis_v2 import sha256_json


POLICY_SCHEMA = "trading_mvp_paper_runtime_acl_policy_v1"
SNAPSHOT_SCHEMA = "trading_mvp_windows_acl_fixture_snapshot_v1"
SYSTEM_SID = "S-1-5-18"
OWNER_TOKEN = "RUNTIME_OWNER_SID"
FORBIDDEN_BROAD_SIDS = {
    "S-1-1-0",  # Everyone
    "S-1-5-11",  # Authenticated Users
    "S-1-5-32-545",  # Builtin Users
}
PRIVATE_REQUIRED_RIGHTS = {
    "read",
    "write",
    "append",
    "delete",
    "read_permissions",
    "change_permissions",
}


def _normalized_windows_path(value: str) -> PureWindowsPath:
    text = os.path.expandvars(str(value).strip())
    if not text:
        raise ValueError("ACL root path must not be blank")
    path = PureWindowsPath(text)
    if not path.is_absolute():
        raise ValueError(f"ACL root must be absolute: {value}")
    return path


def _path_key(path: PureWindowsPath) -> str:
    return str(path).rstrip("\\/").casefold()


def _semantic_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "policy_hash_sha256"}
        }
    )


def build_acl_policy(
    *,
    public_research_root: str,
    private_runtime_root: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    public_root = _normalized_windows_path(public_research_root)
    private_root = _normalized_windows_path(private_runtime_root)
    public_key = _path_key(public_root)
    private_key = _path_key(private_root)
    if public_key == private_key:
        raise ValueError("public and private ACL roots must differ")
    if private_key.startswith(public_key + "\\") or public_key.startswith(private_key + "\\"):
        raise ValueError("public and private ACL roots must not overlap")

    payload: dict[str, Any] = {
        "schema": POLICY_SCHEMA,
        "status": "DESIGN_VALIDATED_NOT_APPLIED",
        "platform": "windows_ntfs",
        "public_research": {
            "root": str(public_root),
            "classification": "PUBLIC_MARKET_DATA_AND_RESEARCH",
            "secret_values_forbidden": True,
            "private_headers_or_signatures_forbidden": True,
            "account_identifiers_forbidden": True,
            "acl_change_required": False,
        },
        "private_runtime": {
            "root": str(private_root),
            "classification": "FUTURE_PRIVATE_RUNTIME_STATE",
            "external_or_removable_drive_forbidden": True,
            "inheritance_enabled": False,
            "allowed_principals": [OWNER_TOKEN, SYSTEM_SID],
            "owner_required_rights": sorted(PRIVATE_REQUIRED_RIGHTS),
            "system_required_rights": sorted(PRIVATE_REQUIRED_RIGHTS),
            "broad_principal_sids_forbidden": sorted(FORBIDDEN_BROAD_SIDS),
        },
        "separation": {
            "roots_must_not_overlap": True,
            "secrets_must_never_enter_public_root": True,
            "public_collectors_must_not_read_private_root": True,
            "private_runtime_must_not_write_public_logs_with_secret_fields": True,
        },
        "application": {
            "apply_live_acl": False,
            "render_only": True,
            "requires_separate_user_authorization": True,
            "requires_non_secret_owner_sid_attestation": True,
            "automatic_permission_changes": False,
        },
        "safety": {
            "filesystem_acl_mutation": False,
            "credentials_read": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
        "maximum_authority": "ACL_DESIGN_AND_FIXTURE_VALIDATION_ONLY",
        "next_allowed_action": "paper_secret_provider_interface_v1",
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    payload["policy_hash_sha256"] = _semantic_hash(payload)
    return payload


def validate_acl_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != POLICY_SCHEMA:
        raise ValueError(f"expected {POLICY_SCHEMA}")
    if payload.get("policy_hash_sha256") != _semantic_hash(payload):
        raise ValueError("ACL policy hash mismatch")
    if payload.get("status") != "DESIGN_VALIDATED_NOT_APPLIED":
        raise ValueError("ACL policy unexpectedly claims application")
    public = payload.get("public_research")
    private = payload.get("private_runtime")
    application = payload.get("application")
    if not isinstance(public, Mapping) or not isinstance(private, Mapping):
        raise ValueError("ACL policy roots are missing")
    if not isinstance(application, Mapping):
        raise ValueError("ACL application boundary is missing")
    public_root = _normalized_windows_path(str(public.get("root") or ""))
    private_root = _normalized_windows_path(str(private.get("root") or ""))
    public_key = _path_key(public_root)
    private_key = _path_key(private_root)
    if public_key == private_key or private_key.startswith(public_key + "\\"):
        raise ValueError("private ACL root overlaps public research root")
    if public_key.startswith(private_key + "\\"):
        raise ValueError("public research root overlaps private ACL root")
    if public.get("secret_values_forbidden") is not True:
        raise ValueError("public research root must forbid secret values")
    if private.get("inheritance_enabled") is not False:
        raise ValueError("private ACL inheritance must be disabled")
    if set(private.get("allowed_principals") or []) != {OWNER_TOKEN, SYSTEM_SID}:
        raise ValueError("private ACL principal allowlist changed")
    if set(private.get("broad_principal_sids_forbidden") or []) != FORBIDDEN_BROAD_SIDS:
        raise ValueError("private ACL broad-principal denylist changed")
    for key in (
        "apply_live_acl",
        "render_only",
        "requires_separate_user_authorization",
        "automatic_permission_changes",
    ):
        expected = key in {"render_only", "requires_separate_user_authorization"}
        if application.get(key) is not expected:
            raise ValueError(f"ACL application boundary changed: {key}")
    safety = payload.get("safety")
    if not isinstance(safety, Mapping) or any(bool(value) for value in safety.values()):
        raise ValueError("ACL policy safety boundary was loosened")
    return dict(payload)


def validate_private_acl_fixture(
    policy: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_acl_policy(policy)
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"expected {SNAPSHOT_SCHEMA}")
    if snapshot.get("inheritance_enabled") is not False:
        raise ValueError("private ACL fixture has inheritance enabled")
    owner_sid = str(snapshot.get("owner_sid") or "").strip()
    if not owner_sid.startswith("S-1-"):
        raise ValueError("private ACL fixture owner SID is invalid")
    entries = snapshot.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("private ACL fixture has no entries")
    observed: dict[str, set[str]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("private ACL fixture entry is invalid")
        sid = str(entry.get("sid") or "").strip()
        if str(entry.get("access_type") or "").upper() != "ALLOW":
            raise ValueError("private ACL fixture must contain only explicit ALLOW entries")
        if bool(entry.get("inherited")):
            raise ValueError("private ACL fixture contains inherited entry")
        rights = {str(value).strip().lower() for value in entry.get("rights") or []}
        if sid in observed:
            raise ValueError("private ACL fixture contains duplicate principal entries")
        observed[sid] = rights
    if FORBIDDEN_BROAD_SIDS.intersection(observed):
        raise ValueError("private ACL fixture grants a broad principal")
    if set(observed) != {owner_sid, SYSTEM_SID}:
        raise ValueError("private ACL fixture principal set is not least privilege")
    for sid in (owner_sid, SYSTEM_SID):
        if not PRIVATE_REQUIRED_RIGHTS.issubset(observed[sid]):
            raise ValueError(f"private ACL fixture lacks required rights: {sid}")
    deterministic = {
        "schema": "trading_mvp_windows_acl_fixture_validation_v1",
        "verdict": "PRIVATE_ACL_FIXTURE_ACCEPTED",
        "policy_hash_sha256": validated["policy_hash_sha256"],
        "owner_sid_hash_sha256": hashlib.sha256(owner_sid.encode("utf-8")).hexdigest(),
        "principal_count": len(observed),
        "inheritance_enabled": False,
        "broad_principals_present": False,
        "filesystem_acl_mutation": False,
    }
    return {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
    }


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper runtime ACL policy designer")
    parser.add_argument("--public-root", required=True)
    parser.add_argument("--private-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    policy = build_acl_policy(
        public_research_root=args.public_root,
        private_runtime_root=args.private_root,
    )
    validate_acl_policy(policy)
    _write_json_immutable(args.output, policy)
    print(json.dumps(policy, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
