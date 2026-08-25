from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


PAPER_ONLY = "PAPER_ONLY"
PREPARATION_ONLY = "PREPARATION_ONLY"
BLOCKED_LIVE = "BLOCKED_LIVE"


class PolicyFormatError(ValueError):
    """Raised when a readiness document violates the closed JSON schema."""

_DENIED_PERMISSIONS = {
    "authenticated_api": False,
    "live_orders": False,
    "real_capital": False,
    "leverage": False,
    "margin": False,
}
_CAPABILITIES = tuple(_DENIED_PERMISSIONS)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")

_ENVELOPE_FIELDS = {
    "schema",
    "frozen_state",
    "candidate_policy",
    "runtime_snapshot",
}
_RUNTIME_FIELDS = {
    "strategy_plan_sha256",
    "canonical_runtime_registry_raw_sha256",
    "account_alias",
    "venue",
    "requested_capabilities",
    "requested_notional_usd",
    "current_daily_loss_usd",
    "resulting_position_usd",
    "kill_switch_ready",
    "reconciliation_ok",
    "reconciliation_age_seconds",
    "market_data_age_seconds",
    "clock_skew_seconds",
}
_POLICY_BODY_FIELDS = {
    "schema",
    "policy_id",
    "strategy_plan_sha256",
    "canonical_runtime_registry_raw_sha256",
    "account_venue_allowlist",
    "allowed_capabilities",
    "limits",
    "controls",
}
_LIMIT_FIELDS = {
    "max_notional_usd",
    "max_daily_loss_usd",
    "max_position_usd",
}
_CONTROL_FIELDS = {
    "kill_switch",
    "reconciliation",
    "max_market_data_age_seconds",
    "max_clock_skew_seconds",
}
_APPROVAL_FIELDS = {
    "two_person_rule",
    "human_approved",
    "policy_payload_sha256",
    "approved_at_utc",
    "expires_at_utc",
    "approvers",
}
_APPROVER_FIELDS = {
    "identity",
    "role",
    "approved_at_utc",
    "signed_payload_sha256",
    "signature",
}
_SIGNATURE_FIELDS = {
    "algorithm",
    "key_id",
    "detached_signature_sha256",
    "verified",
}


def _object(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PolicyFormatError(f"{path} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise PolicyFormatError(f"{path} field names must be strings")
    return value


def _closed_fields(
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str] | None = None,
    path: str,
) -> None:
    actual = set(value)
    unknown = sorted(actual - allowed)
    if unknown:
        raise PolicyFormatError(f"{path} has unknown field(s): {', '.join(unknown)}")
    missing = sorted((required if required is not None else allowed) - actual)
    if missing:
        raise PolicyFormatError(f"{path} is missing required field(s): {', '.join(missing)}")


def _nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PolicyFormatError(f"{field} must be a non-empty trimmed string")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PolicyFormatError(f"{field} must be a lowercase SHA-256 hex string")
    return value


def _boolean(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise PolicyFormatError(f"{field} must be a boolean")
    return value


def _nonnegative_integer(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise PolicyFormatError(f"{field} must be a non-negative integer")
    return value


def _utc_now(now: datetime | None) -> datetime:
    value = now if now is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PolicyFormatError(f"{field} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PolicyFormatError(f"{field} must be a valid UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PolicyFormatError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, *, field: str) -> Decimal:
    if not isinstance(value, str) or _DECIMAL_RE.fullmatch(value) is None:
        raise PolicyFormatError(f"{field} must be a canonical decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise PolicyFormatError(f"{field} must be a decimal string") from exc
    if not parsed.is_finite() or parsed < 0:
        raise PolicyFormatError(f"{field} must be finite and non-negative")
    return parsed


def _validate_capabilities(value: Any, *, path: str) -> Mapping[str, Any]:
    capabilities = _object(value, path=path)
    _closed_fields(capabilities, allowed=set(_CAPABILITIES), path=path)
    for capability in _CAPABILITIES:
        _boolean(capabilities[capability], field=f"{path}.{capability}")
    return capabilities


def _validate_runtime(value: Any) -> Mapping[str, Any]:
    runtime = _object(value, path="runtime_snapshot")
    _closed_fields(runtime, allowed=_RUNTIME_FIELDS, path="runtime_snapshot")
    _sha256(runtime["strategy_plan_sha256"], field="runtime_snapshot.strategy_plan_sha256")
    _sha256(
        runtime["canonical_runtime_registry_raw_sha256"],
        field="runtime_snapshot.canonical_runtime_registry_raw_sha256",
    )
    _nonempty_string(runtime["account_alias"], field="runtime_snapshot.account_alias")
    _nonempty_string(runtime["venue"], field="runtime_snapshot.venue")
    _validate_capabilities(
        runtime["requested_capabilities"],
        path="runtime_snapshot.requested_capabilities",
    )
    for field in ("requested_notional_usd", "current_daily_loss_usd", "resulting_position_usd"):
        _decimal(runtime[field], field=f"runtime_snapshot.{field}")
    _boolean(runtime["kill_switch_ready"], field="runtime_snapshot.kill_switch_ready")
    _boolean(runtime["reconciliation_ok"], field="runtime_snapshot.reconciliation_ok")
    for field in (
        "reconciliation_age_seconds",
        "market_data_age_seconds",
        "clock_skew_seconds",
    ):
        _nonnegative_integer(runtime[field], field=f"runtime_snapshot.{field}")
    return runtime


def _validate_approval(value: Any) -> None:
    approval = _object(value, path="candidate_policy.approval")
    _closed_fields(approval, allowed=_APPROVAL_FIELDS, path="candidate_policy.approval")
    _boolean(approval["two_person_rule"], field="candidate_policy.approval.two_person_rule")
    _boolean(approval["human_approved"], field="candidate_policy.approval.human_approved")
    _sha256(
        approval["policy_payload_sha256"],
        field="candidate_policy.approval.policy_payload_sha256",
    )
    _parse_utc_timestamp(
        approval["approved_at_utc"],
        field="candidate_policy.approval.approved_at_utc",
    )
    _parse_utc_timestamp(
        approval["expires_at_utc"],
        field="candidate_policy.approval.expires_at_utc",
    )
    approvers = approval["approvers"]
    if not isinstance(approvers, list):
        raise PolicyFormatError("candidate_policy.approval.approvers must be an array")
    for index, value in enumerate(approvers):
        path = f"candidate_policy.approval.approvers[{index}]"
        approver = _object(value, path=path)
        _closed_fields(approver, allowed=_APPROVER_FIELDS, path=path)
        _nonempty_string(approver["identity"], field=f"{path}.identity")
        _nonempty_string(approver["role"], field=f"{path}.role")
        _parse_utc_timestamp(approver["approved_at_utc"], field=f"{path}.approved_at_utc")
        _sha256(approver["signed_payload_sha256"], field=f"{path}.signed_payload_sha256")
        signature_path = f"{path}.signature"
        signature = _object(approver["signature"], path=signature_path)
        _closed_fields(signature, allowed=_SIGNATURE_FIELDS, path=signature_path)
        if signature["algorithm"] != "EXTERNAL_DETACHED":
            raise PolicyFormatError(
                f"{signature_path}.algorithm must be EXTERNAL_DETACHED"
            )
        _nonempty_string(signature["key_id"], field=f"{signature_path}.key_id")
        _sha256(
            signature["detached_signature_sha256"],
            field=f"{signature_path}.detached_signature_sha256",
        )
        _boolean(signature["verified"], field=f"{signature_path}.verified")


def _validate_candidate_policy(value: Any) -> Mapping[str, Any]:
    policy = _object(value, path="candidate_policy")
    _closed_fields(
        policy,
        allowed=_POLICY_BODY_FIELDS | {"approval"},
        required=_POLICY_BODY_FIELDS,
        path="candidate_policy",
    )
    if policy["schema"] != "future_live_policy_v1":
        raise PolicyFormatError("candidate_policy.schema must be future_live_policy_v1")
    _nonempty_string(policy["policy_id"], field="candidate_policy.policy_id")
    _sha256(policy["strategy_plan_sha256"], field="candidate_policy.strategy_plan_sha256")
    _sha256(
        policy["canonical_runtime_registry_raw_sha256"],
        field="candidate_policy.canonical_runtime_registry_raw_sha256",
    )

    allowlist = policy["account_venue_allowlist"]
    if not isinstance(allowlist, list) or not allowlist:
        raise PolicyFormatError("candidate_policy.account_venue_allowlist must be a non-empty array")
    seen_pairs: set[tuple[str, str]] = set()
    for index, value in enumerate(allowlist):
        path = f"candidate_policy.account_venue_allowlist[{index}]"
        entry = _object(value, path=path)
        _closed_fields(entry, allowed={"account_alias", "venue"}, path=path)
        account_alias = _nonempty_string(entry["account_alias"], field=f"{path}.account_alias")
        venue = _nonempty_string(entry["venue"], field=f"{path}.venue")
        pair = (account_alias, venue)
        if pair in seen_pairs:
            raise PolicyFormatError(f"{path} duplicates an account/venue allowlist entry")
        seen_pairs.add(pair)

    _validate_capabilities(
        policy["allowed_capabilities"],
        path="candidate_policy.allowed_capabilities",
    )
    limits = _object(policy["limits"], path="candidate_policy.limits")
    _closed_fields(limits, allowed=_LIMIT_FIELDS, path="candidate_policy.limits")
    for field in sorted(_LIMIT_FIELDS):
        _decimal(limits[field], field=f"candidate_policy.limits.{field}")

    controls = _object(policy["controls"], path="candidate_policy.controls")
    _closed_fields(controls, allowed=_CONTROL_FIELDS, path="candidate_policy.controls")
    kill_switch = _object(
        controls["kill_switch"],
        path="candidate_policy.controls.kill_switch",
    )
    _closed_fields(
        kill_switch,
        allowed={"required", "control_id"},
        path="candidate_policy.controls.kill_switch",
    )
    _boolean(
        kill_switch["required"],
        field="candidate_policy.controls.kill_switch.required",
    )
    _nonempty_string(
        kill_switch["control_id"],
        field="candidate_policy.controls.kill_switch.control_id",
    )
    reconciliation = _object(
        controls["reconciliation"],
        path="candidate_policy.controls.reconciliation",
    )
    _closed_fields(
        reconciliation,
        allowed={"required", "control_id", "max_age_seconds"},
        path="candidate_policy.controls.reconciliation",
    )
    _boolean(
        reconciliation["required"],
        field="candidate_policy.controls.reconciliation.required",
    )
    _nonempty_string(
        reconciliation["control_id"],
        field="candidate_policy.controls.reconciliation.control_id",
    )
    _nonnegative_integer(
        reconciliation["max_age_seconds"],
        field="candidate_policy.controls.reconciliation.max_age_seconds",
    )
    _nonnegative_integer(
        controls["max_market_data_age_seconds"],
        field="candidate_policy.controls.max_market_data_age_seconds",
    )
    _nonnegative_integer(
        controls["max_clock_skew_seconds"],
        field="candidate_policy.controls.max_clock_skew_seconds",
    )
    if "approval" in policy:
        _validate_approval(policy["approval"])
    return policy


def _validate_document(document: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    envelope = _object(document, path="document")
    _closed_fields(envelope, allowed=_ENVELOPE_FIELDS, path="document")
    if envelope["schema"] != "live_readiness_validation_v1":
        raise PolicyFormatError("schema must be live_readiness_validation_v1")
    if envelope["frozen_state"] != PAPER_ONLY:
        raise PolicyFormatError("frozen_state must remain PAPER_ONLY")
    runtime = _validate_runtime(envelope["runtime_snapshot"])
    candidate = envelope["candidate_policy"]
    if candidate is not None:
        _validate_candidate_policy(candidate)
    return envelope, runtime


def _approval_blockers(
    policy: Mapping[str, Any],
    *,
    payload_hash: str,
    now: datetime,
) -> list[str]:
    approval = policy.get("approval")
    if approval is None:
        return ["missing_approval"]
    if not isinstance(approval, Mapping):
        raise ValueError("candidate_policy.approval must be an object")

    blockers: list[str] = []
    if approval.get("human_approved") is not True:
        blockers.append("human_approval_missing")
    if approval.get("two_person_rule") is not True:
        blockers.append("two_person_approval_missing")
    if approval.get("policy_payload_sha256") != payload_hash:
        blockers.append("approval_payload_hash_mismatch")

    expires_at = _parse_utc_timestamp(
        approval.get("expires_at_utc"),
        field="candidate_policy.approval.expires_at_utc",
    )
    approved_at = _parse_utc_timestamp(
        approval.get("approved_at_utc"),
        field="candidate_policy.approval.approved_at_utc",
    )
    if expires_at <= now:
        blockers.append("approval_expired")
    if expires_at <= approved_at:
        blockers.append("approval_expiry_not_after_approval")
    if approved_at > now:
        blockers.append("approval_from_future")

    approvers = approval.get("approvers")
    if not isinstance(approvers, list):
        raise ValueError("candidate_policy.approval.approvers must be an array")
    identities: list[str] = []
    roles: list[str] = []
    signature_key_ids: list[str] = []
    signature_receipts: list[str] = []
    if len(approvers) != 2:
        blockers.append("two_person_approval_missing")
    for index, approver in enumerate(approvers):
        if not isinstance(approver, Mapping):
            raise ValueError(f"candidate_policy.approval.approvers[{index}] must be an object")
        identity = approver.get("identity")
        role = approver.get("role")
        if isinstance(identity, str) and identity:
            identities.append(identity)
        if isinstance(role, str) and role:
            roles.append(role)
        if approver.get("signed_payload_sha256") != payload_hash:
            blockers.append("approval_signature_payload_hash_mismatch")
        approver_time = _parse_utc_timestamp(
            approver.get("approved_at_utc"),
            field=f"candidate_policy.approval.approvers[{index}].approved_at_utc",
        )
        if approver_time > now:
            blockers.append("approval_from_future")
        signature = approver.get("signature")
        if not isinstance(signature, Mapping):
            blockers.append("approval_signature_missing")
        else:
            key_id = signature.get("key_id")
            signature_receipt = signature.get("detached_signature_sha256")
            if isinstance(key_id, str) and key_id:
                signature_key_ids.append(key_id)
            if isinstance(signature_receipt, str) and signature_receipt:
                signature_receipts.append(signature_receipt)
            if signature.get("verified") is not True:
                blockers.append("approval_signature_unverified")

    if len(identities) != 2 or len(set(identities)) != 2:
        blockers.append("two_person_approval_missing")
    if len(roles) != 2 or len(set(roles)) != 2:
        blockers.append("two_person_approval_missing")
    if len(approvers) == 2:
        if len(signature_key_ids) != 2 or len(set(signature_key_ids)) != 2:
            blockers.append("two_person_signature_keys_not_distinct")
        if len(signature_receipts) != 2 or len(set(signature_receipts)) != 2:
            blockers.append("two_person_signatures_not_distinct")
    return blockers


def _candidate_blockers(
    policy: Mapping[str, Any],
    runtime: Mapping[str, Any],
    *,
    now: datetime,
) -> tuple[list[str], str]:
    blockers: list[str] = []
    payload_hash = policy_payload_sha256(policy)
    blockers.extend(_approval_blockers(policy, payload_hash=payload_hash, now=now))

    if policy.get("schema") != "future_live_policy_v1":
        blockers.append("candidate_policy_schema_mismatch")
    if policy.get("strategy_plan_sha256") != runtime.get("strategy_plan_sha256"):
        blockers.append("strategy_plan_hash_mismatch")
    if policy.get("canonical_runtime_registry_raw_sha256") != runtime.get(
        "canonical_runtime_registry_raw_sha256"
    ):
        blockers.append("canonical_runtime_registry_hash_mismatch")

    allowlist = policy.get("account_venue_allowlist")
    if not isinstance(allowlist, list):
        raise ValueError("candidate_policy.account_venue_allowlist must be an array")
    requested_pair = {
        "account_alias": runtime.get("account_alias"),
        "venue": runtime.get("venue"),
    }
    if requested_pair not in allowlist:
        blockers.append("account_venue_not_allowlisted")

    allowed = policy.get("allowed_capabilities")
    requested = runtime.get("requested_capabilities")
    if not isinstance(allowed, Mapping):
        raise ValueError("candidate_policy.allowed_capabilities must be an object")
    if not isinstance(requested, Mapping):
        raise ValueError("runtime_snapshot.requested_capabilities must be an object")
    for capability in _CAPABILITIES:
        if requested.get(capability) is True and allowed.get(capability) is not True:
            blockers.append(f"capability_not_allowed:{capability}")

    limits = policy.get("limits")
    if not isinstance(limits, Mapping):
        raise ValueError("candidate_policy.limits must be an object")
    comparisons = (
        ("requested_notional_usd", "max_notional_usd", "max_notional_exceeded"),
        ("current_daily_loss_usd", "max_daily_loss_usd", "max_daily_loss_exceeded"),
        ("resulting_position_usd", "max_position_usd", "max_position_exceeded"),
    )
    for observed_field, limit_field, blocker in comparisons:
        observed = _decimal(runtime.get(observed_field), field=f"runtime_snapshot.{observed_field}")
        maximum = _decimal(limits.get(limit_field), field=f"candidate_policy.limits.{limit_field}")
        if maximum <= 0:
            blockers.append(f"invalid_non_positive_limit:{limit_field}")
        if observed > maximum:
            blockers.append(blocker)

    controls = policy.get("controls")
    if not isinstance(controls, Mapping):
        raise ValueError("candidate_policy.controls must be an object")
    kill_switch = controls.get("kill_switch")
    reconciliation = controls.get("reconciliation")
    if not isinstance(kill_switch, Mapping):
        raise ValueError("candidate_policy.controls.kill_switch must be an object")
    if not isinstance(reconciliation, Mapping):
        raise ValueError("candidate_policy.controls.reconciliation must be an object")
    if kill_switch.get("required") is not True:
        blockers.append("kill_switch_not_required_by_policy")
    if runtime.get("kill_switch_ready") is not True:
        blockers.append("kill_switch_not_ready")
    if reconciliation.get("required") is not True:
        blockers.append("reconciliation_not_required_by_policy")
    if runtime.get("reconciliation_ok") is not True:
        blockers.append("reconciliation_not_ok")
    if runtime.get("reconciliation_age_seconds") > reconciliation.get("max_age_seconds"):
        blockers.append("reconciliation_stale")
    if runtime.get("market_data_age_seconds") > controls.get("max_market_data_age_seconds"):
        blockers.append("market_data_stale")
    if runtime.get("clock_skew_seconds") > controls.get("max_clock_skew_seconds"):
        blockers.append("clock_skew_exceeded")
    return sorted(set(blockers)), payload_hash


def policy_payload_sha256(policy: Mapping[str, Any]) -> str:
    """Hash policy terms plus approval identity/expiry, excluding circular receipts."""
    body = {key: value for key, value in policy.items() if key != "approval"}
    approval = policy.get("approval")
    if isinstance(approval, Mapping):
        approver_contracts: list[dict[str, Any]] = []
        approvers = approval.get("approvers")
        if isinstance(approvers, list):
            for approver in approvers:
                if not isinstance(approver, Mapping):
                    approver_contracts.append({"invalid_approver": approver})
                    continue
                signature = approver.get("signature")
                signature_contract = (
                    {
                        "algorithm": signature.get("algorithm"),
                        "key_id": signature.get("key_id"),
                    }
                    if isinstance(signature, Mapping)
                    else {"invalid_signature": signature}
                )
                approver_contracts.append(
                    {
                        "identity": approver.get("identity"),
                        "role": approver.get("role"),
                        "approved_at_utc": approver.get("approved_at_utc"),
                        "signature": signature_contract,
                    }
                )
        body["approval_contract"] = {
            "two_person_rule": approval.get("two_person_rule"),
            "human_approved": approval.get("human_approved"),
            "approved_at_utc": approval.get("approved_at_utc"),
            "expires_at_utc": approval.get("expires_at_utc"),
            "approvers": approver_contracts,
        }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_readiness(
    document: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate an offline candidate policy without authorizing live execution."""
    evaluation_time = _utc_now(now)
    envelope, runtime = _validate_document(document)
    if envelope["candidate_policy"] is None:
        return {
            "schema": "live_readiness_result_v1",
            "status": BLOCKED_LIVE,
            "frozen_state": PAPER_ONLY,
            "candidate_policy_complete": False,
            "blockers": ["missing_candidate_policy"],
            "live_execution_allowed": False,
            "separate_execution_authorization_required": True,
            "external_signature_cryptographic_verification_performed": False,
            "effective_permissions": dict(_DENIED_PERMISSIONS),
        }
    candidate = envelope["candidate_policy"]
    assert isinstance(candidate, Mapping)
    blockers, payload_hash = _candidate_blockers(candidate, runtime, now=evaluation_time)
    complete = not blockers
    return {
        "schema": "live_readiness_result_v1",
        "status": PREPARATION_ONLY if complete else BLOCKED_LIVE,
        "frozen_state": PAPER_ONLY,
        "candidate_policy_complete": complete,
        "policy_payload_sha256": payload_hash,
        "blockers": blockers,
        "live_execution_allowed": False,
        "separate_execution_authorization_required": True,
        "external_signature_cryptographic_verification_performed": False,
        "effective_permissions": dict(_DENIED_PERMISSIONS),
    }


def _no_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyFormatError(f"JSON object has duplicate field: {key}")
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> Any:
    raise PolicyFormatError(f"JSON number must be finite: {value}")


def load_validation_document(path: str | Path) -> Mapping[str, Any]:
    """Load one local JSON document with duplicate-key and non-finite-number rejection."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PolicyFormatError(f"cannot read validation document: {exc}") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_no_duplicate_fields,
            parse_constant=_reject_non_json_number,
        )
    except json.JSONDecodeError as exc:
        raise PolicyFormatError(
            f"invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    return _object(payload, path="document")


def _invalid_document_result(exc: Exception) -> dict[str, Any]:
    return {
        "schema": "live_readiness_result_v1",
        "status": BLOCKED_LIVE,
        "frozen_state": PAPER_ONLY,
        "candidate_policy_complete": False,
        "blockers": ["invalid_policy_document"],
        "validation_errors": [str(exc)],
        "live_execution_allowed": False,
        "separate_execution_authorization_required": True,
        "external_signature_cryptographic_verification_performed": False,
        "effective_permissions": dict(_DENIED_PERMISSIONS),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline-only live-readiness preparation validator; never authorizes execution."
    )
    parser.add_argument("--validate", metavar="PATH", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--now",
        metavar="UTC",
        help="Deterministic UTC evaluation time ending in Z; defaults to the current UTC time.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evaluation_time = (
            _parse_utc_timestamp(args.now, field="--now")
            if args.now is not None
            else None
        )
        document = load_validation_document(args.validate)
        result = validate_readiness(document, now=evaluation_time)
    except (PolicyFormatError, ValueError, TypeError) as exc:
        result = _invalid_document_result(exc)

    if args.as_json:
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    else:
        print(result["status"])
        for blocker in result.get("blockers", []):
            print(f"- {blocker}")
    return 0 if result["status"] == PREPARATION_ONLY else 2


if __name__ == "__main__":
    sys.exit(main())
