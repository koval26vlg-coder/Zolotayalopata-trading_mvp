from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from historical_basis_v2 import sha256_file, sha256_json


RUNTIME_SCHEMA = "trading_mvp_paper_observer_runtime_contract_v1"
HEALTH_SCHEMA = "trading_mvp_paper_venue_health_gate_contract_v1"
PRIVATE_SCHEMA = "trading_mvp_private_boundary_attestation_contract_v1"
REPORT_SCHEMA = "trading_mvp_paper_contract_validation_report_v1"


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def contract_hash(payload: Mapping[str, Any]) -> str:
    canonical = {
        key: value
        for key, value in payload.items()
        if key != "contract_hash_sha256"
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_contract_hash(payload: Mapping[str, Any], *, label: str) -> None:
    expected = str(payload.get("contract_hash_sha256") or "").lower()
    if len(expected) != 64 or expected != contract_hash(payload):
        raise ValueError(f"{label} contract hash mismatch")


def _require_bool(
    payload: Mapping[str, Any],
    key: str,
    expected: bool,
    *,
    label: str,
) -> None:
    if payload.get(key) is not expected:
        raise ValueError(f"{label} must be {expected}: {key}")


def _require_safety(payload: Mapping[str, Any], *, label: str) -> None:
    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        raise ValueError(f"{label} safety contract is missing")
    for key in ("live_orders", "private_api_keys", "leverage", "margin", "grid_search", "retune"):
        _require_bool(safety, key, False, label=f"{label}.safety")


def validate_runtime_contract(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema") != RUNTIME_SCHEMA:
        raise ValueError(f"expected {RUNTIME_SCHEMA}")
    _validate_contract_hash(payload, label="runtime")
    if payload.get("status") != "FROZEN_DESIGN_READY_FOR_FIXTURE_IMPLEMENTATION":
        raise ValueError("runtime contract status is not frozen")
    scope = payload.get("scope")
    if not isinstance(scope, Mapping) or scope.get("venues") != ["mexc", "gateio"]:
        raise ValueError("runtime contract venues changed")
    activation = payload.get("activation_gate")
    if not isinstance(activation, Mapping):
        raise ValueError("runtime activation gate is missing")
    if (
        activation.get("required_verdict") != "PAPER_FORWARD_READY"
        or activation.get("reject_when_missing_or_mismatched") is not True
    ):
        raise ValueError("runtime PAPER_FORWARD_READY gate was loosened")
    runtime = payload.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("runtime settings are missing")
    if int(runtime.get("segment_duration_sec") or 0) != 1_200:
        raise ValueError("runtime segment duration changed")
    if int(runtime.get("sample_interval_sec") or 0) != 5:
        raise ValueError("runtime sample interval changed")
    maximum_runtime = int(runtime.get("max_runtime_sec") or 0)
    if maximum_runtime < 1 or maximum_runtime > 1_800:
        raise ValueError("runtime max_runtime_sec must be in [1, 1800]")
    for key in (
        "visible_terminal_required",
        "single_market_data_writer",
        "paper_oms_single_writer_lock_required",
    ):
        _require_bool(runtime, key, True, label="runtime")
    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        raise ValueError("runtime safety contract is missing")
    _require_bool(safety, "public_get_requests_only", True, label="runtime.safety")
    _require_safety(payload, label="runtime")
    return payload


def validate_health_contract(
    path: str | Path,
    *,
    runtime_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = _read_json(target)
    if payload.get("schema") != HEALTH_SCHEMA:
        raise ValueError(f"expected {HEALTH_SCHEMA}")
    _validate_contract_hash(payload, label="health")
    if payload.get("status") != "FROZEN_DESIGN_READY_FOR_FIXTURE_IMPLEMENTATION":
        raise ValueError("venue-health contract status is not frozen")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise ValueError("venue-health thresholds are missing")
    if float(thresholds.get("minimum_capacity_quote_per_leg") or 0.0) < 500.0:
        raise ValueError("venue-health minimum capacity was weakened")
    if float(thresholds.get("maximum_impact_bps_at_notional") or 0.0) > 10.0:
        raise ValueError("venue-health maximum impact was weakened")
    if float(thresholds.get("maximum_quote_age_ms") or 0.0) > 5_000.0:
        raise ValueError("venue-health quote age was weakened")
    if float(thresholds.get("maximum_cross_venue_timestamp_skew_ms") or 0.0) > 2_000.0:
        raise ValueError("venue-health timestamp skew was weakened")
    if float(thresholds.get("maximum_recent_application_error_rate") or 0.0) > 0.05:
        raise ValueError("venue-health application error rate was weakened")
    if int(thresholds.get("maximum_consecutive_missing_intervals") or 0) > 2:
        raise ValueError("venue-health missing interval gate was weakened")
    if float(thresholds.get("maximum_spread_bps_for_transition") or 0.0) > 10.0:
        raise ValueError("venue-health maximum spread was weakened")
    transition = payload.get("transition_policy")
    if not isinstance(transition, Mapping):
        raise ValueError("venue-health transition policy is missing")
    if (
        transition.get("never_submit_transient_bad_snapshot_as_data_quality_false")
        is not True
        or transition.get("paper_observation_data_quality_ok_when_submitted") is not True
        or transition.get("use_synchronized_depth_vwap_trade_prices") is not True
    ):
        raise ValueError("venue-health transition policy was loosened")
    _require_safety(payload, label="venue-health")

    if runtime_contract is not None:
        parent = payload.get("parent_contract")
        if not isinstance(parent, Mapping):
            raise ValueError("venue-health parent runtime contract is missing")
        runtime_path = Path(str(parent.get("path") or "")).expanduser().resolve()
        if not runtime_path.is_file():
            raise ValueError("venue-health parent runtime contract file is missing")
        if parent.get("file_sha256") != sha256_file(runtime_path):
            raise ValueError("venue-health parent runtime file hash mismatch")
        if runtime_contract.get("contract_hash_sha256") != _read_json(runtime_path).get(
            "contract_hash_sha256"
        ):
            raise ValueError("venue-health parent runtime semantic hash mismatch")
    return payload


def validate_private_boundary_contract(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema") != PRIVATE_SCHEMA:
        raise ValueError(f"expected {PRIVATE_SCHEMA}")
    _validate_contract_hash(payload, label="private boundary")
    if (
        payload.get("status") != "CONTRACT_READY_NOT_ATTESTED"
        or payload.get("current_live_authority") != "NONE"
    ):
        raise ValueError("private boundary contract granted unexpected authority")
    artifact_policy = payload.get("artifact_policy")
    if not isinstance(artifact_policy, Mapping):
        raise ValueError("private boundary artifact policy is missing")
    _require_bool(artifact_policy, "contains_secrets", False, label="artifact policy")
    for key in (
        "api_key_value_forbidden",
        "api_secret_value_forbidden",
        "passphrase_value_forbidden",
        "private_headers_or_signatures_forbidden",
        "ip_address_values_forbidden",
        "full_account_or_subaccount_identifiers_forbidden",
        "immutable",
    ):
        _require_bool(artifact_policy, key, True, label="artifact policy")
    permissions = payload.get("permission_gates")
    if not isinstance(permissions, Mapping):
        raise ValueError("private boundary permission gates are missing")
    for key in (
        "read_permission",
        "trade_permission",
        "dedicated_subaccount",
        "ip_allowlist_enabled",
        "ip_allowlist_matches_runtime_egress",
        "wildcard_ip_forbidden",
        "master_account_key_forbidden",
    ):
        _require_bool(permissions, key, True, label="permission gate")
    for key in ("withdrawal_permission", "internal_transfer_permission"):
        if permissions.get(key) is not False:
            raise ValueError(f"private boundary {key} must remain disabled")
    activation = payload.get("live_activation_decision")
    if not isinstance(activation, Mapping):
        raise ValueError("private boundary activation decision is missing")
    if activation.get("automatic_live_activation") is not False:
        raise ValueError("private boundary automatic live activation is forbidden")
    if activation.get("decision_now") != "LIVE_REVIEW_BLOCKED_NOT_ATTESTED":
        raise ValueError("private boundary current decision must remain blocked")
    return payload


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


def build_validation_report(
    *,
    runtime_contract_path: str | Path,
    health_contract_path: str | Path,
    private_contract_path: str | Path,
    output_path: str | Path | None,
) -> dict[str, Any]:
    runtime_target = Path(runtime_contract_path).expanduser().resolve()
    health_target = Path(health_contract_path).expanduser().resolve()
    private_target = Path(private_contract_path).expanduser().resolve()
    runtime = validate_runtime_contract(runtime_target)
    health = validate_health_contract(health_target, runtime_contract=runtime)
    private = validate_private_boundary_contract(private_target)
    deterministic = {
        "schema": REPORT_SCHEMA,
        "verdict": "CONTRACT_CHAIN_VALID",
        "contracts": {
            "runtime": {
                "path": str(runtime_target),
                "file_sha256": sha256_file(runtime_target),
                "contract_hash_sha256": runtime["contract_hash_sha256"],
            },
            "health": {
                "path": str(health_target),
                "file_sha256": sha256_file(health_target),
                "contract_hash_sha256": health["contract_hash_sha256"],
            },
            "private_boundary": {
                "path": str(private_target),
                "file_sha256": sha256_file(private_target),
                "contract_hash_sha256": private["contract_hash_sha256"],
            },
        },
        "safety": {
            "network_access": False,
            "credentials_read": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "grid_search": False,
            "retune": False,
        },
        "maximum_authority": "CONTRACT_VALIDATION_ONLY",
        "next_allowed_action": "paper_oms_fixture_sink_v1",
    }
    result = {
        **deterministic,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "deterministic_result_hash": sha256_json(deterministic),
    }
    if output_path is not None:
        _write_json_immutable(output_path, result)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate paper runtime contract chain")
    parser.add_argument("--runtime-contract", required=True)
    parser.add_argument("--health-contract", required=True)
    parser.add_argument("--private-contract", required=True)
    parser.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = build_validation_report(
        runtime_contract_path=args.runtime_contract,
        health_contract_path=args.health_contract,
        private_contract_path=args.private_contract,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
