from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from paper_log_redaction import sanitize_for_log
from paper_public_reader import (
    PublicMarketReader,
    PublicReaderError,
    RequestsPublicGetTransport,
    SystemClock,
)
from paper_public_reader_contract import (
    sha256_file,
    sha256_json,
    validate_public_reader_contract,
)


PLAN_SCHEMA = "trading_mvp_paper_public_readonly_probe_plan_v1"
AUTHORIZATION_SCHEMA = (
    "trading_mvp_paper_public_readonly_probe_user_authorization_v1"
)
RESULT_SCHEMA = "trading_mvp_paper_public_readonly_probe_result_v1"
EVIDENCE_SCHEMA = "trading_mvp_paper_public_readonly_probe_evidence_v1"
PLAN_SCHEMAS = {
    "v1": PLAN_SCHEMA,
    "v2": "trading_mvp_paper_public_readonly_probe_plan_v2",
    "v3": "trading_mvp_paper_public_readonly_probe_plan_v3",
}
AUTHORIZATION_SCHEMAS = {
    "v1": AUTHORIZATION_SCHEMA,
    "v2": "trading_mvp_paper_public_readonly_probe_run_authorization_v2",
    "v3": "trading_mvp_paper_public_readonly_probe_run_authorization_v3",
}
RESULT_SCHEMAS = {
    "v1": RESULT_SCHEMA,
    "v2": "trading_mvp_paper_public_readonly_probe_result_v2",
    "v3": "trading_mvp_paper_public_readonly_probe_result_v3",
}
EVIDENCE_SCHEMAS = {
    "v1": EVIDENCE_SCHEMA,
    "v2": "trading_mvp_paper_public_readonly_probe_evidence_v2",
    "v3": "trading_mvp_paper_public_readonly_probe_evidence_v3",
}
STANDING_AUTHORIZATION_SCHEMA = (
    "trading_mvp_public_readonly_probe_standing_authorization_v1"
)
STANDING_AUTHORIZATION_ID = "trading_mvp_public_probe_standing_20260730_v1"
V3_CRITICAL_AUTHORIZATION_SCHEMA = (
    "trading_mvp_public_readonly_probe_v3_critical_authorization_v1"
)
V3_APPROVED_USER_INSTRUCTION = (
    "\u0420\u0430\u0437\u0440\u0435\u0448\u0430\u044e contract v3: "
    "MEXC max quote age 6000 ms, Gate 5000 ms, "
    "\u043e\u0434\u0438\u043d \u043d\u043e\u0432\u044b\u0439 "
    "\u0432\u0438\u0434\u0438\u043c\u044b\u0439 bounded probe; "
    "\u043e\u0441\u0442\u0430\u043b\u044c\u043d\u044b\u0435 standing limits "
    "\u0431\u0435\u0437 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0439."
)
STANDING_ROUTINE_ACTION = (
    "bounded same-scope public GET compatibility probes under hash-bound "
    "standing authorization"
)
REQUESTED_ACTION = "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE"
ACCEPTED_VERDICT = "PUBLIC_READONLY_PROBE_ACCEPTED"
STOPPED_VERDICT = "PUBLIC_READONLY_PROBE_STOPPED_INCOMPLETE"
EXPECTED_VENUES = ("mexc", "gateio")
EXPECTED_HOSTS = (
    "https://contract.mexc.com",
    "https://api.gateio.ws/api/v4",
)
EXPECTED_ENDPOINT_IDS = {
    "mexc": [
        "mexc_contracts",
        "mexc_tickers",
        "mexc_funding",
        "mexc_depth",
    ],
    "gateio": [
        "gateio_contracts",
        "gateio_tickers",
        "gateio_funding",
        "gateio_depth",
    ],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {target}")
    return payload


def _write_json_immutable(
    path: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _append_jsonl(handle: Any, payload: Mapping[str, Any]) -> None:
    handle.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )
    handle.flush()
    os.fsync(handle.fileno())


def _canonical_plan_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {"plan_hash_sha256", "generated_at_utc"}
    }


def _canonical_authorization_payload(
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in authorization.items()
        if key not in {"authorization_hash_sha256", "generated_at_utc"}
    }


def _canonical_standing_authorization_payload(
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in authorization.items()
        if key
        not in {
            "authorization_hash_sha256",
            "generated_at_utc",
        }
    }


def _canonical_v3_critical_authorization_payload(
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in authorization.items()
        if key
        not in {
            "authorization_hash_sha256",
            "generated_at_utc",
        }
    }


def _canonical_result_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key
        not in {
            "deterministic_result_hash",
            "started_at_utc",
            "completed_at_utc",
        }
    }


def _plan_version(plan: Mapping[str, Any]) -> str:
    schema = str(plan.get("schema") or "")
    for version, expected_schema in PLAN_SCHEMAS.items():
        if schema == expected_schema:
            return version
    raise ValueError("public read-only probe plan schema mismatch")


def _result_version(result: Mapping[str, Any]) -> str:
    schema = str(result.get("schema") or "")
    for version, expected_schema in RESULT_SCHEMAS.items():
        if schema == expected_schema:
            return version
    raise ValueError("public probe result schema mismatch")


def _assert_exact_keys(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    label: str,
) -> None:
    for key, value in expected.items():
        if actual.get(key) != value:
            raise ValueError(
                f"{label}.{key} mismatch: "
                f"expected={value!r} actual={actual.get(key)!r}"
            )


def validate_probe_plan(
    plan_path: str | Path,
    expected_plan_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(plan_path).expanduser().resolve()
    plan = _read_json(target)
    version = _plan_version(plan)
    expected_hash = str(expected_plan_hash).strip().lower()
    embedded_hash = str(plan.get("plan_hash_sha256") or "").lower()
    observed_hash = sha256_json(_canonical_plan_payload(plan))
    if (
        len(expected_hash) != 64
        or embedded_hash != expected_hash
        or observed_hash != expected_hash
    ):
        raise ValueError(
            "public read-only probe plan hash mismatch: "
            f"expected={expected_hash} embedded={embedded_hash} "
            f"observed={observed_hash}"
        )
    if version == "v2":
        expected_plan = {
            "task_id": "paper_public_readonly_probe_plan_v2",
            "status": "PLAN_ONLY_STANDING_AUTHORIZATION_REQUIRED",
            "verdict": (
                "PUBLIC_READONLY_PROBE_PLAN_V2_FROZEN_"
                "REQUIRES_STANDING_AUTHORIZATION"
            ),
            "next_allowed_action": (
                "authorize_public_readonly_probe_plan_under_standing_policy"
            ),
        }
    elif version == "v3":
        expected_plan = {
            "task_id": "paper_public_readonly_probe_plan_v3",
            "status": "PLAN_ONLY_ONE_TIME_CRITICAL_AUTHORIZATION_REQUIRED",
            "verdict": (
                "PUBLIC_READONLY_PROBE_PLAN_V3_FROZEN_"
                "REQUIRES_ONE_TIME_CRITICAL_AUTHORIZATION"
            ),
            "next_allowed_action": "create_v3_one_time_critical_authorization",
        }
    else:
        expected_plan = {
            "task_id": "paper_public_readonly_probe_plan_v1",
            "status": "PLAN_ONLY_NOT_AUTHORIZED_FOR_NETWORK",
            "verdict": "PUBLIC_READONLY_PROBE_PLAN_FROZEN_NOT_AUTHORIZED",
        }
    _assert_exact_keys(plan, expected_plan, label="plan")
    probe = plan.get("probe")
    authorization = plan.get("authorization")
    safety = plan.get("safety")
    if not isinstance(probe, Mapping):
        raise ValueError("probe plan probe block is missing")
    if not isinstance(authorization, Mapping):
        raise ValueError("probe plan authorization block is missing")
    if not isinstance(safety, Mapping):
        raise ValueError("probe plan safety block is missing")
    _assert_exact_keys(
        probe,
        {
            "venues": list(EXPECTED_VENUES),
            "symbol": "HYPE_USDT",
            "canonical_base": "hype",
            "fixture_identity_only": True,
            "duration_sec": 120,
            "snapshot_interval_sec": 5,
            "max_cycles": 24,
            "max_runtime_sec": 180,
            "planned_endpoint_reads": 192,
            "maximum_public_get_attempts": 576,
            "visible_terminal_required": True,
        },
        label="plan.probe",
    )
    expected_authorization = {
        "network_authorized": False,
        "execution_authorized": False,
        "automatic_start": False,
        "requires_new_guard_decision": version == "v1",
        "requires_visible_terminal": True,
    }
    if version == "v2":
        expected_authorization.update(
            {
                "requires_standing_authorization": True,
                "automatic_start_with_valid_standing_authorization": True,
            }
        )
    elif version == "v3":
        expected_authorization.update(
            {
                "requires_standing_limits": True,
                "requires_one_time_v3_critical_authorization": True,
                "automatic_start_with_valid_v3_critical_authorization": True,
            }
        )
    _assert_exact_keys(
        authorization,
        expected_authorization,
        label="plan.authorization",
    )
    _assert_exact_keys(
        safety,
        {
            "network_requests_performed": 0,
            "market_data_writer_started": False,
            "returns_or_pnl_read": False,
            "signals_read": False,
            "oms_mutations": 0,
            "private_api_keys": False,
            "live_orders": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
            "hypothesis_changed": False,
        },
        label="plan.safety",
    )
    endpoint_ids = probe.get("endpoint_ids")
    if not isinstance(endpoint_ids, Mapping):
        raise ValueError("probe plan endpoint_ids are missing")
    _assert_exact_keys(
        endpoint_ids,
        EXPECTED_ENDPOINT_IDS,
        label="plan.probe.endpoint_ids",
    )
    if version == "v2":
        compatibility = plan.get("compatibility_scope")
        if not isinstance(compatibility, Mapping):
            raise ValueError("v2 probe plan compatibility scope is missing")
        _assert_exact_keys(
            compatibility,
            {
                "change": "mexc_bbo_source_ticker_to_depth_l1",
                "existing_hosts_and_endpoint_ids_only": True,
                "normalized_output_schema_changed": False,
                "venue_universe_signal_cost_risk_changed": False,
                "hypothesis_changed": False,
            },
            label="plan.compatibility_scope",
        )
    elif version == "v3":
        quote_ages = probe.get("maximum_quote_age_ms_by_venue")
        if not isinstance(quote_ages, Mapping):
            raise ValueError("v3 probe plan freshness limits are missing")
        _assert_exact_keys(
            quote_ages,
            {"mexc": 6000, "gateio": 5000},
            label="plan.probe.maximum_quote_age_ms_by_venue",
        )
        compatibility = plan.get("compatibility_scope")
        if not isinstance(compatibility, Mapping):
            raise ValueError("v3 probe plan compatibility scope is missing")
        _assert_exact_keys(
            compatibility,
            {
                "change": (
                    "venue_specific_quote_freshness_mexc_5000_to_6000_ms"
                ),
                "mexc_bbo_source": "mexc_depth_l1",
                "maximum_quote_age_ms_by_venue": {
                    "mexc": 6000,
                    "gateio": 5000,
                },
                "existing_hosts_and_endpoint_ids_only": True,
                "normalized_output_schema_changed": False,
                "venue_universe_hypothesis_signal_cost_changed": False,
                "private_live_leverage_margin_changed": False,
                "maximum_runs_for_new_plan_hash": 1,
            },
            label="plan.compatibility_scope",
        )
        if len(
            str(compatibility.get("source_v2_plan_hash_sha256") or "")
        ) != 64:
            raise ValueError("v3 probe plan source v2 plan hash is invalid")
    output_namespace = Path(
        str(probe.get("output_namespace") or "")
    ).expanduser().resolve()
    if not output_namespace.is_absolute():
        raise ValueError("probe output namespace must be absolute")

    contract_descriptor = plan.get("contract")
    if not isinstance(contract_descriptor, Mapping):
        raise ValueError("probe plan contract binding is missing")
    contract_path = Path(
        str(contract_descriptor.get("path") or "")
    ).expanduser().resolve()
    if not contract_path.is_file():
        raise FileNotFoundError(f"public reader contract is missing: {contract_path}")
    observed_file_hash = sha256_file(contract_path)
    if observed_file_hash != str(
        contract_descriptor.get("file_sha256") or ""
    ).lower():
        raise ValueError("public reader contract file hash mismatch")
    contract = validate_public_reader_contract(_read_json(contract_path))
    expected_contract_id = f"paper_public_reader_contract_{version}"
    if contract.get("contract_id") != expected_contract_id:
        raise ValueError("probe plan and public reader contract version mismatch")
    if contract["contract_hash_sha256"] != str(
        contract_descriptor.get("contract_hash_sha256") or ""
    ).lower():
        raise ValueError("public reader contract deterministic hash mismatch")
    return plan, contract


def _standing_scope() -> dict[str, Any]:
    return {
        "plan_versions": ["v2"],
        "methods": ["GET"],
        "venues": list(EXPECTED_VENUES),
        "base_urls": list(EXPECTED_HOSTS),
        "endpoint_ids": EXPECTED_ENDPOINT_IDS,
        "symbol": "HYPE_USDT",
        "canonical_base": "hype",
        "duration_sec": 120,
        "max_runtime_sec": 180,
        "maximum_public_get_attempts": 576,
        "maximum_runs_per_distinct_plan_hash": 1,
        "visible_terminal_required": True,
        "single_market_data_writer": True,
        "existing_hosts_and_endpoint_ids_only": True,
        "technical_response_compatibility_only": True,
        "normalized_output_schema_changed": False,
        "venue_universe_hypothesis_signal_cost_risk_changed": False,
        "returns_or_pnl_read": False,
        "oos_read": False,
        "private_api_keys": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "grid_or_retune": False,
        "automatic_retry_after_stopped_incomplete": False,
    }


def build_standing_authorization(
    *,
    policy_path: str | Path,
    project_root: str | Path,
    user_instruction: str,
    contract_authorization_text: str,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    policy_target = Path(policy_path).expanduser().resolve()
    root = Path(project_root).expanduser().resolve()
    policy = _read_json(policy_target)
    instruction = str(user_instruction).strip()
    contract_text = str(contract_authorization_text).strip()
    if policy.get("schema") != "trading_mvp_autopilot_policy_v1":
        raise ValueError("unexpected trading autopilot policy schema")
    if policy.get("project") != "trading_mvp":
        raise ValueError("standing authorization policy project mismatch")
    if policy.get("mode") != "research_and_paper_only":
        raise ValueError("standing authorization requires research-and-paper mode")
    routine = policy.get("routine_actions_without_user_confirmation")
    if not isinstance(routine, list) or STANDING_ROUTINE_ACTION not in routine:
        raise ValueError("autopilot policy lacks the bounded probe routine action")
    run_policy = policy.get("run_policy")
    if not isinstance(run_policy, Mapping):
        raise ValueError("autopilot run policy is missing")
    _assert_exact_keys(
        run_policy,
        {
            "visible_terminal_for_writers": True,
            "single_market_data_writer": True,
            "grid_and_retune_forbidden": True,
        },
        label="policy.run_policy",
    )
    if not instruction or not contract_text:
        raise ValueError("standing authorization requires exact user instructions")
    deterministic = {
        "schema": STANDING_AUTHORIZATION_SCHEMA,
        "authorization_id": STANDING_AUTHORIZATION_ID,
        "decision": "AUTHORIZED",
        "status": "ACTIVE_UNTIL_REVOKED_OR_SCOPE_CHANGE",
        "project": "trading_mvp",
        "project_root": str(root),
        "source_user_authorization": {
            "contract_v2": contract_text,
            "permission_minimization": instruction,
        },
        "policy": {
            "path": str(policy_target),
            "file_sha256": sha256_file(policy_target),
            "policy_id": policy["policy_id"],
            "thread_id": policy["thread_id"],
        },
        "scope": _standing_scope(),
        "routine_actions_without_new_user_confirmation": [
            "freeze one compatibility-only contract and plan per distinct hash",
            "create one run authorization bound to the standing and plan hashes",
            "start one visible bounded public GET probe per distinct plan hash",
            "run exact immutable postprocess and technical readiness audit",
        ],
        "still_requires_user_checkpoint": list(
            policy["critical_user_checkpoints"]
        )
        + [
            "new host or endpoint",
            "second run for the same plan hash",
            "automatic retry after STOPPED_INCOMPLETE",
            "collector or writer exceeding 180 seconds",
        ],
    }
    authorization = {
        **deterministic,
        "authorization_hash_sha256": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, authorization)
    return authorization


def validate_standing_authorization(
    authorization_path: str | Path,
    *,
    expected_authorization_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(authorization_path).expanduser().resolve()
    authorization = _read_json(target)
    if authorization.get("schema") != STANDING_AUTHORIZATION_SCHEMA:
        raise ValueError("public probe standing authorization schema mismatch")
    observed_hash = sha256_json(
        _canonical_standing_authorization_payload(authorization)
    )
    embedded_hash = str(
        authorization.get("authorization_hash_sha256") or ""
    ).lower()
    if embedded_hash != observed_hash:
        raise ValueError("public probe standing authorization hash mismatch")
    if expected_authorization_hash is not None:
        expected_hash = str(expected_authorization_hash).strip().lower()
        if len(expected_hash) != 64 or embedded_hash != expected_hash:
            raise ValueError("unexpected public probe standing authorization hash")
    _assert_exact_keys(
        authorization,
        {
            "authorization_id": STANDING_AUTHORIZATION_ID,
            "decision": "AUTHORIZED",
            "status": "ACTIVE_UNTIL_REVOKED_OR_SCOPE_CHANGE",
            "project": "trading_mvp",
        },
        label="standing_authorization",
    )
    if authorization.get("scope") != _standing_scope():
        raise ValueError("public probe standing authorization scope changed")
    policy_descriptor = authorization.get("policy")
    if not isinstance(policy_descriptor, Mapping):
        raise ValueError("standing authorization policy binding is missing")
    policy_target = Path(
        str(policy_descriptor.get("path") or "")
    ).expanduser().resolve()
    policy = _read_json(policy_target)
    if sha256_file(policy_target) != str(
        policy_descriptor.get("file_sha256") or ""
    ).lower():
        raise ValueError("standing authorization policy file hash mismatch")
    _assert_exact_keys(
        policy,
        {
            "schema": "trading_mvp_autopilot_policy_v1",
            "policy_id": policy_descriptor.get("policy_id"),
            "thread_id": policy_descriptor.get("thread_id"),
            "project": "trading_mvp",
            "mode": "research_and_paper_only",
        },
        label="standing_authorization.policy",
    )
    routine = policy.get("routine_actions_without_user_confirmation")
    if not isinstance(routine, list) or STANDING_ROUTINE_ACTION not in routine:
        raise ValueError("standing authorization policy no longer allows probes")
    return authorization


def _validate_plan_within_standing_limits(
    *,
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    standing: Mapping[str, Any],
) -> None:
    scope = standing["scope"]
    if plan["probe"]["venues"] != scope["venues"]:
        raise ValueError("standing authorization venue scope mismatch")
    if plan["probe"]["symbol"] != scope["symbol"]:
        raise ValueError("standing authorization symbol scope mismatch")
    if plan["probe"]["canonical_base"] != scope["canonical_base"]:
        raise ValueError("standing authorization asset scope mismatch")
    if int(plan["probe"]["duration_sec"]) > int(scope["duration_sec"]):
        raise ValueError("standing authorization duration exceeded")
    if int(plan["probe"]["max_runtime_sec"]) > int(scope["max_runtime_sec"]):
        raise ValueError("standing authorization runtime exceeded")
    if int(plan["probe"]["maximum_public_get_attempts"]) > int(
        scope["maximum_public_get_attempts"]
    ):
        raise ValueError("standing authorization GET-attempt limit exceeded")
    base_urls = [contract["venues"][venue]["base_url"] for venue in EXPECTED_VENUES]
    if base_urls != scope["base_urls"]:
        raise ValueError("standing authorization host scope mismatch")
    if plan["probe"]["endpoint_ids"] != scope["endpoint_ids"]:
        raise ValueError("standing authorization endpoint scope mismatch")


def validate_plan_under_standing_authorization(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    standing_authorization_path: str | Path,
    expected_standing_authorization_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan, contract = validate_probe_plan(plan_path, expected_plan_hash)
    if _plan_version(plan) != "v2":
        raise ValueError("standing authorization only applies to v2 probe plans")
    standing = validate_standing_authorization(
        standing_authorization_path,
        expected_authorization_hash=expected_standing_authorization_hash,
    )
    _validate_plan_within_standing_limits(
        plan=plan,
        contract=contract,
        standing=standing,
    )
    return plan, contract, standing


def _v3_critical_authorization_deterministic(
    *,
    plan_path: Path,
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    standing_path: Path,
    standing: Mapping[str, Any],
    failure_audit_path: Path,
    user_instruction: str,
    thread_id: str,
) -> dict[str, Any]:
    migration = contract.get("migration_evidence")
    if not isinstance(migration, Mapping):
        raise ValueError("v3 contract migration evidence is missing")
    failure_binding = migration.get("source_failure_audit")
    if not isinstance(failure_binding, Mapping):
        raise ValueError("v3 contract failure-audit binding is missing")
    if failure_audit_path != Path(
        str(failure_binding.get("path") or "")
    ).expanduser().resolve():
        raise ValueError("v3 critical authorization failure audit path mismatch")
    if sha256_file(failure_audit_path) != str(
        failure_binding.get("file_sha256") or ""
    ).lower():
        raise ValueError("v3 critical authorization failure audit hash mismatch")
    failure_audit = _read_json(failure_audit_path)
    if (
        failure_audit.get("schema")
        != "trading_mvp_public_readonly_probe_failure_audit_v1"
        or failure_audit.get("status") != "USER_REVIEW_REQUIRED"
        or failure_audit.get("run_id") != failure_binding.get("run_id")
    ):
        raise ValueError("v3 critical authorization failure audit mismatch")
    source_plan_hash = str(
        (failure_audit.get("plan") or {}).get("plan_hash_sha256") or ""
    ).lower()
    if source_plan_hash != str(
        failure_binding.get("plan_hash_sha256") or ""
    ).lower():
        raise ValueError("v3 critical authorization source plan mismatch")
    instruction = str(user_instruction).strip()
    if instruction != V3_APPROVED_USER_INSTRUCTION:
        raise ValueError("v3 critical authorization user instruction mismatch")
    thread = str(thread_id).strip()
    if not thread:
        raise ValueError("v3 critical authorization thread_id is required")
    return {
        "schema": V3_CRITICAL_AUTHORIZATION_SCHEMA,
        "authorization_id": (
            "trading_mvp_public_probe_v3_one_time_"
            + str(plan["plan_hash_sha256"])[:16]
        ),
        "decision": "AUTHORIZED",
        "status": "ONE_TIME_FOR_EXACT_PLAN_HASH",
        "project": "trading_mvp",
        "thread_id": thread,
        "source_user_authorization": instruction,
        "plan": {
            "path": str(plan_path),
            "file_sha256": sha256_file(plan_path),
            "plan_hash_sha256": plan["plan_hash_sha256"],
        },
        "standing_limits": {
            "path": str(standing_path),
            "file_sha256": sha256_file(standing_path),
            "authorization_hash_sha256": standing[
                "authorization_hash_sha256"
            ],
            "authorization_id": standing["authorization_id"],
        },
        "source_failure_audit": {
            "path": str(failure_audit_path),
            "file_sha256": sha256_file(failure_audit_path),
            "run_id": failure_binding["run_id"],
            "source_plan_hash_sha256": source_plan_hash,
            "deterministic_result_hash": failure_binding[
                "deterministic_result_hash"
            ],
        },
        "approved_change": {
            "maximum_quote_age_ms_before": {
                "mexc": 5000,
                "gateio": 5000,
            },
            "maximum_quote_age_ms_after": {
                "mexc": 6000,
                "gateio": 5000,
            },
            "maximum_runs_for_exact_plan_hash": 1,
            "visible_terminal_required": True,
            "automatic_retry_after_stopped_incomplete": False,
        },
        "unchanged_standing_limits": {
            "methods": ["GET"],
            "venues": list(EXPECTED_VENUES),
            "base_urls": list(EXPECTED_HOSTS),
            "endpoint_ids": EXPECTED_ENDPOINT_IDS,
            "symbol": "HYPE_USDT",
            "canonical_base": "hype",
            "duration_sec": 120,
            "max_runtime_sec": 180,
            "maximum_public_get_attempts": 576,
            "single_market_data_writer": True,
            "returns_or_pnl_read": False,
            "oos_read": False,
            "private_api_keys": False,
            "live_orders": False,
            "real_capital": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
        },
    }


def build_v3_critical_authorization(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    standing_authorization_path: str | Path,
    expected_standing_authorization_hash: str,
    failure_audit_path: str | Path,
    user_instruction: str,
    thread_id: str,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan_target = Path(plan_path).expanduser().resolve()
    standing_target = Path(standing_authorization_path).expanduser().resolve()
    audit_target = Path(failure_audit_path).expanduser().resolve()
    plan, contract = validate_probe_plan(plan_target, expected_plan_hash)
    if _plan_version(plan) != "v3":
        raise ValueError("v3 critical authorization requires a v3 probe plan")
    standing = validate_standing_authorization(
        standing_target,
        expected_authorization_hash=expected_standing_authorization_hash,
    )
    _validate_plan_within_standing_limits(
        plan=plan,
        contract=contract,
        standing=standing,
    )
    deterministic = _v3_critical_authorization_deterministic(
        plan_path=plan_target,
        plan=plan,
        contract=contract,
        standing_path=standing_target,
        standing=standing,
        failure_audit_path=audit_target,
        user_instruction=user_instruction,
        thread_id=thread_id,
    )
    authorization = {
        **deterministic,
        "authorization_hash_sha256": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, authorization)
    return authorization


def validate_v3_critical_authorization(
    authorization_path: str | Path,
    *,
    expected_authorization_hash: str,
    plan_path: str | Path,
    expected_plan_hash: str,
    standing_authorization_path: str | Path,
    expected_standing_authorization_hash: str,
    failure_audit_path: str | Path,
) -> dict[str, Any]:
    target = Path(authorization_path).expanduser().resolve()
    plan_target = Path(plan_path).expanduser().resolve()
    standing_target = Path(standing_authorization_path).expanduser().resolve()
    audit_target = Path(failure_audit_path).expanduser().resolve()
    authorization = _read_json(target)
    if authorization.get("schema") != V3_CRITICAL_AUTHORIZATION_SCHEMA:
        raise ValueError("v3 critical authorization schema mismatch")
    expected_hash = str(expected_authorization_hash).strip().lower()
    observed_hash = sha256_json(
        _canonical_v3_critical_authorization_payload(authorization)
    )
    if (
        len(expected_hash) != 64
        or observed_hash != expected_hash
        or str(
            authorization.get("authorization_hash_sha256") or ""
        ).lower()
        != expected_hash
    ):
        raise ValueError("v3 critical authorization hash mismatch")
    plan, contract = validate_probe_plan(plan_target, expected_plan_hash)
    if _plan_version(plan) != "v3":
        raise ValueError("v3 critical authorization plan version mismatch")
    standing = validate_standing_authorization(
        standing_target,
        expected_authorization_hash=expected_standing_authorization_hash,
    )
    _validate_plan_within_standing_limits(
        plan=plan,
        contract=contract,
        standing=standing,
    )
    expected = _v3_critical_authorization_deterministic(
        plan_path=plan_target,
        plan=plan,
        contract=contract,
        standing_path=standing_target,
        standing=standing,
        failure_audit_path=audit_target,
        user_instruction=V3_APPROVED_USER_INSTRUCTION,
        thread_id=str(authorization.get("thread_id") or ""),
    )
    if _canonical_v3_critical_authorization_payload(authorization) != expected:
        raise ValueError("v3 critical authorization content mismatch")
    return authorization


def validate_plan_under_v3_critical_authorization(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    standing_authorization_path: str | Path,
    expected_standing_authorization_hash: str,
    critical_authorization_path: str | Path,
    expected_critical_authorization_hash: str,
    failure_audit_path: str | Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    plan, contract = validate_probe_plan(plan_path, expected_plan_hash)
    standing = validate_standing_authorization(
        standing_authorization_path,
        expected_authorization_hash=expected_standing_authorization_hash,
    )
    _validate_plan_within_standing_limits(
        plan=plan,
        contract=contract,
        standing=standing,
    )
    critical = validate_v3_critical_authorization(
        critical_authorization_path,
        expected_authorization_hash=expected_critical_authorization_hash,
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        standing_authorization_path=standing_authorization_path,
        expected_standing_authorization_hash=(
            expected_standing_authorization_hash
        ),
        failure_audit_path=failure_audit_path,
    )
    return plan, contract, standing, critical


def build_user_authorization(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    run_id: str,
    user_instruction: str,
    thread_id: str,
    standing_authorization_path: str | Path | None = None,
    expected_standing_authorization_hash: str | None = None,
    critical_authorization_path: str | Path | None = None,
    expected_critical_authorization_hash: str | None = None,
    freshness_failure_audit_path: str | Path | None = None,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    plan, _ = validate_probe_plan(target, expected_plan_hash)
    version = _plan_version(plan)
    run = str(run_id).strip()
    instruction = str(user_instruction).strip()
    thread = str(thread_id).strip()
    if not run:
        raise ValueError("run_id is required")
    if not instruction:
        raise ValueError("user instruction is required")
    if not thread:
        raise ValueError("thread_id is required")
    standing: dict[str, Any] | None = None
    standing_target: Path | None = None
    critical: dict[str, Any] | None = None
    critical_target: Path | None = None
    if version == "v2":
        if (
            standing_authorization_path is None
            or expected_standing_authorization_hash is None
        ):
            raise ValueError("v2 run authorization requires standing authorization")
        standing_target = Path(
            standing_authorization_path
        ).expanduser().resolve()
        plan, _, standing = validate_plan_under_standing_authorization(
            plan_path=target,
            expected_plan_hash=expected_plan_hash,
            standing_authorization_path=standing_target,
            expected_standing_authorization_hash=(
                expected_standing_authorization_hash
            ),
        )
    elif version == "v3":
        if (
            standing_authorization_path is None
            or expected_standing_authorization_hash is None
            or critical_authorization_path is None
            or expected_critical_authorization_hash is None
            or freshness_failure_audit_path is None
        ):
            raise ValueError(
                "v3 run authorization requires standing limits, "
                "critical authorization and failure audit"
            )
        standing_target = Path(
            standing_authorization_path
        ).expanduser().resolve()
        critical_target = Path(
            critical_authorization_path
        ).expanduser().resolve()
        plan, _, standing, critical = (
            validate_plan_under_v3_critical_authorization(
                plan_path=target,
                expected_plan_hash=expected_plan_hash,
                standing_authorization_path=standing_target,
                expected_standing_authorization_hash=(
                    expected_standing_authorization_hash
                ),
                critical_authorization_path=critical_target,
                expected_critical_authorization_hash=(
                    expected_critical_authorization_hash
                ),
                failure_audit_path=freshness_failure_audit_path,
            )
        )
    elif standing_authorization_path is not None:
        raise ValueError("v1 authorization cannot use standing authorization")
    deterministic: dict[str, Any] = {
        "schema": AUTHORIZATION_SCHEMAS[version],
        "decision": "AUTHORIZED",
        "requested_action": REQUESTED_ACTION,
        "run_id": run,
        "thread_id": thread,
        "user_instruction": instruction,
        "plan": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "plan_hash_sha256": plan["plan_hash_sha256"],
        },
        "scope": {
            "duration_sec": 120,
            "max_runtime_sec": 180,
            "venues": list(EXPECTED_VENUES),
            "public_api_only": True,
            "network_authorized": True,
            "execution_authorized": True,
            "visible_terminal_required": True,
            "automatic_start": version in {"v2", "v3"},
            "private_api_keys": False,
            "live_orders": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
        },
    }
    if standing is not None and standing_target is not None:
        deterministic["authorization_basis"] = (
            "hash_bound_standing_authorization"
            if version == "v2"
            else (
                "hash_bound_standing_limits_plus_"
                "one_time_v3_critical_authorization"
            )
        )
        deterministic["standing_authorization"] = {
            "path": str(standing_target),
            "file_sha256": sha256_file(standing_target),
            "authorization_hash_sha256": standing[
                "authorization_hash_sha256"
            ],
            "authorization_id": standing["authorization_id"],
        }
    if critical is not None and critical_target is not None:
        deterministic["critical_authorization"] = {
            "path": str(critical_target),
            "file_sha256": sha256_file(critical_target),
            "authorization_hash_sha256": critical[
                "authorization_hash_sha256"
            ],
            "authorization_id": critical["authorization_id"],
            "source_failure_audit": dict(
                critical["source_failure_audit"]
            ),
        }
    authorization = {
        **deterministic,
        "authorization_hash_sha256": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, authorization)
    return authorization


def validate_user_authorization(
    authorization_path: str | Path,
    *,
    expected_authorization_hash: str,
    plan_path: str | Path,
    expected_plan_hash: str,
    run_id: str,
) -> dict[str, Any]:
    target = Path(authorization_path).expanduser().resolve()
    expected_target = Path(plan_path).expanduser().resolve()
    plan, _ = validate_probe_plan(expected_target, expected_plan_hash)
    version = _plan_version(plan)
    authorization = _read_json(target)
    if authorization.get("schema") != AUTHORIZATION_SCHEMAS[version]:
        raise ValueError("public probe authorization schema mismatch")
    expected_hash = str(expected_authorization_hash).strip().lower()
    observed_hash = sha256_json(
        _canonical_authorization_payload(authorization)
    )
    if (
        len(expected_hash) != 64
        or str(
            authorization.get("authorization_hash_sha256") or ""
        ).lower()
        != expected_hash
        or observed_hash != expected_hash
    ):
        raise ValueError("public probe authorization hash mismatch")
    _assert_exact_keys(
        authorization,
        {
            "decision": "AUTHORIZED",
            "requested_action": REQUESTED_ACTION,
            "run_id": str(run_id),
        },
        label="authorization",
    )
    plan_descriptor = authorization.get("plan")
    scope = authorization.get("scope")
    if not isinstance(plan_descriptor, Mapping):
        raise ValueError("authorization plan binding is missing")
    if not isinstance(scope, Mapping):
        raise ValueError("authorization scope is missing")
    if Path(str(plan_descriptor.get("path") or "")).expanduser().resolve() != (
        expected_target
    ):
        raise ValueError("authorization plan path mismatch")
    if str(plan_descriptor.get("file_sha256") or "").lower() != sha256_file(
        expected_target
    ):
        raise ValueError("authorization plan file hash mismatch")
    if str(
        plan_descriptor.get("plan_hash_sha256") or ""
    ).lower() != str(expected_plan_hash).lower():
        raise ValueError("authorization plan hash mismatch")
    _assert_exact_keys(
        scope,
        {
            "duration_sec": 120,
            "max_runtime_sec": 180,
            "venues": list(EXPECTED_VENUES),
            "public_api_only": True,
            "network_authorized": True,
            "execution_authorized": True,
            "visible_terminal_required": True,
            "automatic_start": version in {"v2", "v3"},
            "private_api_keys": False,
            "live_orders": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
        },
        label="authorization.scope",
    )
    if version == "v2":
        if authorization.get("authorization_basis") != (
            "hash_bound_standing_authorization"
        ):
            raise ValueError("v2 run authorization basis mismatch")
        standing_descriptor = authorization.get("standing_authorization")
        if not isinstance(standing_descriptor, Mapping):
            raise ValueError("v2 run authorization standing binding is missing")
        standing_target = Path(
            str(standing_descriptor.get("path") or "")
        ).expanduser().resolve()
        if sha256_file(standing_target) != str(
            standing_descriptor.get("file_sha256") or ""
        ).lower():
            raise ValueError("v2 standing authorization file hash mismatch")
        standing = validate_standing_authorization(
            standing_target,
            expected_authorization_hash=str(
                standing_descriptor.get("authorization_hash_sha256") or ""
            ),
        )
        if standing["authorization_id"] != standing_descriptor.get(
            "authorization_id"
        ):
            raise ValueError("v2 standing authorization id mismatch")
        validate_plan_under_standing_authorization(
            plan_path=expected_target,
            expected_plan_hash=expected_plan_hash,
            standing_authorization_path=standing_target,
            expected_standing_authorization_hash=standing[
                "authorization_hash_sha256"
            ],
        )
    elif version == "v3":
        if authorization.get("authorization_basis") != (
            "hash_bound_standing_limits_plus_"
            "one_time_v3_critical_authorization"
        ):
            raise ValueError("v3 run authorization basis mismatch")
        standing_descriptor = authorization.get("standing_authorization")
        critical_descriptor = authorization.get("critical_authorization")
        if not isinstance(standing_descriptor, Mapping) or not isinstance(
            critical_descriptor, Mapping
        ):
            raise ValueError("v3 run authorization bindings are missing")
        standing_target = Path(
            str(standing_descriptor.get("path") or "")
        ).expanduser().resolve()
        critical_target = Path(
            str(critical_descriptor.get("path") or "")
        ).expanduser().resolve()
        if sha256_file(standing_target) != str(
            standing_descriptor.get("file_sha256") or ""
        ).lower():
            raise ValueError("v3 standing authorization file hash mismatch")
        if sha256_file(critical_target) != str(
            critical_descriptor.get("file_sha256") or ""
        ).lower():
            raise ValueError("v3 critical authorization file hash mismatch")
        standing = validate_standing_authorization(
            standing_target,
            expected_authorization_hash=str(
                standing_descriptor.get("authorization_hash_sha256") or ""
            ),
        )
        failure_descriptor = critical_descriptor.get("source_failure_audit")
        if not isinstance(failure_descriptor, Mapping):
            raise ValueError("v3 run authorization failure binding is missing")
        validate_plan_under_v3_critical_authorization(
            plan_path=expected_target,
            expected_plan_hash=expected_plan_hash,
            standing_authorization_path=standing_target,
            expected_standing_authorization_hash=standing[
                "authorization_hash_sha256"
            ],
            critical_authorization_path=critical_target,
            expected_critical_authorization_hash=str(
                critical_descriptor.get("authorization_hash_sha256") or ""
            ),
            failure_audit_path=str(failure_descriptor.get("path") or ""),
        )
    return authorization


class RuntimeReceivedAtPublicMarketReader(PublicMarketReader):
    """Sample local receive time after all endpoint responses are available."""

    def _assemble_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["observer_received_ts_ms"] = max(
            int(kwargs["observer_received_ts_ms"]),
            int(self.clock.now_ms),
        )
        return super()._assemble_snapshot(**kwargs)


def build_probe_runtime_reader(
    contract: Mapping[str, Any],
    _venue: str,
) -> PublicMarketReader:
    validated = validate_public_reader_contract(contract)
    return RuntimeReceivedAtPublicMarketReader(
        validated,
        RequestsPublicGetTransport(validated),
        clock=SystemClock(),
    )


def _safe_error(
    *,
    cycle_index: int,
    venue: str,
    exc: BaseException,
    observed_at_utc: str,
) -> dict[str, Any]:
    if isinstance(exc, PublicReaderError):
        category = exc.category
        endpoint_id = exc.endpoint_id
        detail = exc.detail
    else:
        category = "unexpected_runtime_error"
        endpoint_id = "runtime"
        detail = type(exc).__name__
    sanitized = sanitize_for_log(
        {
            "cycle_index": int(cycle_index),
            "venue": venue,
            "category": category,
            "endpoint_id": endpoint_id,
            "detail": detail,
            "observed_at_utc": observed_at_utc,
        }
    )
    return dict(sanitized)


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return path != parent


def run_probe(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    authorization_path: str | Path,
    expected_authorization_hash: str,
    output_dir: str | Path,
    run_id: str,
    max_runtime_sec: int,
    reader_factory: Callable[
        [Mapping[str, Any], str], PublicMarketReader
    ] = build_probe_runtime_reader,
    monotonic: Callable[[], float] = time.monotonic,
    wall_time_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    sleep: Callable[[float], None] = time.sleep,
    utc_now: Callable[[], str] = _utc_now,
    progress: Callable[[str], None] = lambda message: print(
        message,
        flush=True,
    ),
) -> dict[str, Any]:
    plan_target = Path(plan_path).expanduser().resolve()
    plan, contract = validate_probe_plan(plan_target, expected_plan_hash)
    version = _plan_version(plan)
    authorization_target = Path(authorization_path).expanduser().resolve()
    authorization = validate_user_authorization(
        authorization_target,
        expected_authorization_hash=expected_authorization_hash,
        plan_path=plan_target,
        expected_plan_hash=expected_plan_hash,
        run_id=run_id,
    )
    requested_runtime = int(max_runtime_sec)
    frozen_runtime = int(plan["probe"]["max_runtime_sec"])
    if requested_runtime <= 0 or requested_runtime > frozen_runtime:
        raise ValueError("max_runtime_sec exceeds the frozen probe plan")
    output = Path(output_dir).expanduser().resolve()
    namespace = Path(
        str(plan["probe"]["output_namespace"])
    ).expanduser().resolve()
    if not _path_is_within(output, namespace):
        raise ValueError("probe output directory escapes the frozen namespace")
    output.mkdir(parents=True, exist_ok=True)
    snapshots_path = output / "snapshots.jsonl"
    errors_path = output / "errors.jsonl"
    manifest_path = output / "manifest.json"
    for target in (snapshots_path, errors_path, manifest_path):
        if target.exists():
            raise FileExistsError(f"probe output already exists: {target}")

    readers = {
        venue: reader_factory(contract, venue) for venue in EXPECTED_VENUES
    }
    duration_sec = int(plan["probe"]["duration_sec"])
    interval_sec = int(plan["probe"]["snapshot_interval_sec"])
    maximum_cycles = int(plan["probe"]["max_cycles"])
    maximum_attempts = int(plan["probe"]["maximum_public_get_attempts"])
    quote_age_limits = (
        {
            venue: int(
                plan["probe"]["maximum_quote_age_ms_by_venue"][venue]
            )
            for venue in EXPECTED_VENUES
        }
        if version == "v3"
        else {venue: 5000 for venue in EXPECTED_VENUES}
    )
    expected_snapshots = maximum_cycles * len(EXPECTED_VENUES)
    started_monotonic = float(monotonic())
    started_at_utc = utc_now()
    snapshot_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    stale_counts = {venue: 0 for venue in EXPECTED_VENUES}
    cycles_attempted = 0
    hard_stop_reason = ""
    progress(
        "[public-readonly-probe] "
        f"start run_id={run_id} cycles={maximum_cycles} "
        f"interval_sec={interval_sec} max_runtime_sec={requested_runtime}"
    )

    with snapshots_path.open("x", encoding="utf-8", newline="\n") as snapshots_file:
        with errors_path.open("x", encoding="utf-8", newline="\n") as errors_file:
            executor = ThreadPoolExecutor(
                max_workers=len(EXPECTED_VENUES),
                thread_name_prefix="public-readonly-probe",
            )
            try:
                for cycle_index in range(maximum_cycles):
                    elapsed = float(monotonic()) - started_monotonic
                    if elapsed >= requested_runtime:
                        hard_stop_reason = "max_runtime_exceeded_before_cycle"
                        break
                    target_offset = cycle_index * interval_sec
                    wait_sec = target_offset - elapsed
                    if wait_sec > 0:
                        sleep(wait_sec)
                    if float(monotonic()) - started_monotonic >= requested_runtime:
                        hard_stop_reason = "max_runtime_exceeded_before_cycle"
                        break

                    cycles_attempted += 1
                    cycle_started = utc_now()
                    futures = {
                        venue: executor.submit(
                            readers[venue].read_market_snapshot,
                            venue=venue,
                            symbol=str(plan["probe"]["symbol"]),
                            canonical_base=str(
                                plan["probe"]["canonical_base"]
                            ),
                            observer_received_ts_ms=int(wall_time_ms()),
                            maximum_quote_age_ms=quote_age_limits[venue],
                        )
                        for venue in EXPECTED_VENUES
                    }
                    for venue in EXPECTED_VENUES:
                        try:
                            snapshot = futures[venue].result()
                            if snapshot.get("venue") != venue:
                                raise ValueError(
                                    "normalized snapshot venue mismatch"
                                )
                            row = {
                                "schema": (
                                    "trading_mvp_paper_public_readonly_"
                                    "probe_snapshot_v1"
                                ),
                                "run_id": str(run_id),
                                "cycle_index": cycle_index,
                                "cycle_started_at_utc": cycle_started,
                                "received_at_utc": utc_now(),
                                "snapshot": snapshot,
                            }
                            _append_jsonl(snapshots_file, row)
                            snapshot_rows.append(row)
                            stale_counts[venue] = 0
                            if snapshot.get("contract_trading") is not True:
                                error = {
                                    "cycle_index": cycle_index,
                                    "venue": venue,
                                    "category": "contract_not_trading",
                                    "endpoint_id": f"{venue}_contracts",
                                    "detail": "frozen probe symbol is not trading",
                                    "observed_at_utc": utc_now(),
                                }
                                _append_jsonl(errors_file, error)
                                error_rows.append(error)
                        except BaseException as exc:
                            error = _safe_error(
                                cycle_index=cycle_index,
                                venue=venue,
                                exc=exc,
                                observed_at_utc=utc_now(),
                            )
                            _append_jsonl(errors_file, error)
                            error_rows.append(error)
                            if error["category"] == "stale_quote":
                                stale_counts[venue] += 1
                            else:
                                stale_counts[venue] = 0

                    categories = {
                        str(row.get("category") or "") for row in error_rows
                    }
                    if "schema_mismatch" in categories:
                        hard_stop_reason = "schema_mismatch"
                        break
                    if any(count >= 2 for count in stale_counts.values()):
                        hard_stop_reason = "persistent_stale_quotes"
                        break
                    if len(error_rows) / expected_snapshots > 0.05:
                        hard_stop_reason = (
                            "application_error_rate_above_5_percent"
                        )
                        break
                    network_requests = sum(
                        int(
                            getattr(
                                getattr(reader, "transport", None),
                                "network_requests",
                                0,
                            )
                        )
                        for reader in readers.values()
                    )
                    if network_requests > maximum_attempts:
                        hard_stop_reason = "maximum_public_get_attempts_exceeded"
                        break
                    progress(
                        "[public-readonly-probe] "
                        f"cycle={cycle_index + 1}/{maximum_cycles} "
                        f"snapshots={len(snapshot_rows)}/{expected_snapshots} "
                        f"errors={len(error_rows)} "
                        f"requests={network_requests}/{maximum_attempts} "
                        f"elapsed_sec={float(monotonic()) - started_monotonic:.3f}"
                    )
            finally:
                executor.shutdown(wait=True, cancel_futures=True)

    elapsed_sec = max(0.0, float(monotonic()) - started_monotonic)
    network_requests = sum(
        int(
            getattr(
                getattr(reader, "transport", None),
                "network_requests",
                0,
            )
        )
        for reader in readers.values()
    )
    retry_trace = [
        trace
        for venue in EXPECTED_VENUES
        for trace in list(getattr(readers[venue], "retry_trace", []))
    ]
    rate_limit_trace = [
        trace
        for venue in EXPECTED_VENUES
        for trace in list(
            getattr(readers[venue], "rate_limit_trace", [])
        )
    ]
    partial_output = len(snapshot_rows) != expected_snapshots
    application_error_rate = len(error_rows) / expected_snapshots
    accepted = (
        not hard_stop_reason
        and not partial_output
        and not error_rows
        and cycles_attempted == maximum_cycles
        and network_requests >= int(plan["probe"]["planned_endpoint_reads"])
        and network_requests <= maximum_attempts
        and elapsed_sec <= requested_runtime
    )
    status = "READY_FOR_POSTPROCESS" if accepted else "STOPPED_INCOMPLETE"
    verdict = ACCEPTED_VERDICT if accepted else STOPPED_VERDICT
    deterministic = {
        "schema": RESULT_SCHEMAS[version],
        "run_id": str(run_id),
        "status": status,
        "final": accepted,
        "verdict": verdict,
        "plan": {
            "path": str(plan_target),
            "file_sha256": sha256_file(plan_target),
            "plan_hash_sha256": plan["plan_hash_sha256"],
        },
        "authorization": {
            "path": str(authorization_target),
            "file_sha256": sha256_file(authorization_target),
            "authorization_hash_sha256": authorization[
                "authorization_hash_sha256"
            ],
            "requested_action": authorization["requested_action"],
        },
        "contract": {
            "path": str(Path(plan["contract"]["path"]).resolve()),
            "file_sha256": plan["contract"]["file_sha256"],
            "contract_hash_sha256": plan["contract"][
                "contract_hash_sha256"
            ],
        },
        "runtime": {
            "requested_duration_sec": duration_sec,
            "max_runtime_sec": requested_runtime,
            "elapsed_sec": elapsed_sec,
            "snapshot_interval_sec": interval_sec,
            "cycles_attempted": cycles_attempted,
            "cycles_completed": len(snapshot_rows)
            // len(EXPECTED_VENUES),
            "maximum_cycles": maximum_cycles,
            "worker_pid": os.getpid(),
        },
        "quality": {
            "venues": list(EXPECTED_VENUES),
            "expected_snapshot_count": expected_snapshots,
            "snapshot_count": len(snapshot_rows),
            "error_count": len(error_rows),
            "application_error_rate": application_error_rate,
            "partial_output": partial_output,
            "hard_stop_reason": hard_stop_reason or None,
            "planned_endpoint_reads": int(
                plan["probe"]["planned_endpoint_reads"]
            ),
            "network_requests": network_requests,
            "maximum_public_get_attempts": maximum_attempts,
            "retry_count": len(retry_trace),
            "rate_limit_event_count": len(rate_limit_trace),
            "retry_trace_hash_sha256": sha256_json(retry_trace),
            "rate_limit_trace_hash_sha256": sha256_json(
                rate_limit_trace
            ),
            **(
                {
                    "maximum_quote_age_ms_by_venue": quote_age_limits,
                }
                if version == "v3"
                else {}
            ),
        },
        "artifacts": {
            "snapshots_path": str(snapshots_path),
            "snapshots_file_sha256": sha256_file(snapshots_path),
            "errors_path": str(errors_path),
            "errors_file_sha256": sha256_file(errors_path),
        },
        "source_provenance": {
            "probe_runner": {
                "path": str(Path(__file__).resolve()),
                "file_sha256": sha256_file(Path(__file__).resolve()),
            },
            "public_reader": {
                "path": str(
                    Path(sys.modules[PublicMarketReader.__module__].__file__).resolve()
                ),
                "file_sha256": sha256_file(
                    Path(
                        sys.modules[PublicMarketReader.__module__].__file__
                    ).resolve()
                ),
            },
        },
        "safety": {
            "public_get_only": True,
            "returns_or_pnl_read": False,
            "signals_read": False,
            "oms_mutations": 0,
            "private_api_keys": False,
            "live_orders": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
            "hypothesis_changed": False,
        },
        "next_allowed_action": (
            "paper_public_readonly_probe_postrun"
            if accepted
            else "USER_REVIEW_REQUIRED_STOPPED_INCOMPLETE"
        ),
    }
    result = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "started_at_utc": started_at_utc,
        "completed_at_utc": utc_now(),
    }
    _write_json_immutable(manifest_path, result)
    progress(
        "[public-readonly-probe] "
        f"finish status={status} verdict={verdict} "
        f"snapshots={len(snapshot_rows)} errors={len(error_rows)} "
        f"requests={network_requests} elapsed_sec={elapsed_sec:.3f}"
    )
    return result


def validate_probe_result(
    manifest_path: str | Path,
    *,
    expected_plan_hash: str,
) -> dict[str, Any]:
    target = Path(manifest_path).expanduser().resolve()
    result = _read_json(target)
    version = _result_version(result)
    expected_hash = str(expected_plan_hash).strip().lower()
    plan_descriptor = result.get("plan")
    if not isinstance(plan_descriptor, Mapping):
        raise ValueError("public probe result plan binding is missing")
    if str(plan_descriptor.get("plan_hash_sha256") or "").lower() != expected_hash:
        raise ValueError("public probe result plan hash mismatch")
    plan_target = Path(
        str(plan_descriptor.get("path") or "")
    ).expanduser().resolve()
    if sha256_file(plan_target) != str(
        plan_descriptor.get("file_sha256") or ""
    ).lower():
        raise ValueError("public probe result plan file hash mismatch")
    plan, _ = validate_probe_plan(plan_target, expected_hash)
    if _plan_version(plan) != version:
        raise ValueError("public probe result and plan version mismatch")
    observed_result_hash = sha256_json(_canonical_result_payload(result))
    if observed_result_hash != str(
        result.get("deterministic_result_hash") or ""
    ).lower():
        raise ValueError("public probe result deterministic hash mismatch")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("public probe result artifacts are missing")
    for prefix in ("snapshots", "errors"):
        path = Path(str(artifacts.get(f"{prefix}_path") or "")).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"public probe artifact is missing: {path}")
        if sha256_file(path) != str(
            artifacts.get(f"{prefix}_file_sha256") or ""
        ).lower():
            raise ValueError(f"public probe {prefix} artifact hash mismatch")
    quality = result.get("quality")
    safety = result.get("safety")
    if not isinstance(quality, Mapping) or not isinstance(safety, Mapping):
        raise ValueError("public probe result quality or safety block is missing")
    if int(quality.get("network_requests") or 0) > int(
        quality.get("maximum_public_get_attempts") or 0
    ):
        raise ValueError("public probe exceeded maximum GET attempts")
    if version == "v3" and quality.get(
        "maximum_quote_age_ms_by_venue"
    ) != {"mexc": 6000, "gateio": 5000}:
        raise ValueError("v3 public probe freshness evidence mismatch")
    _assert_exact_keys(
        safety,
        {
            "public_get_only": True,
            "returns_or_pnl_read": False,
            "signals_read": False,
            "oms_mutations": 0,
            "private_api_keys": False,
            "live_orders": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
            "hypothesis_changed": False,
        },
        label="result.safety",
    )
    if result.get("final") is True:
        if result.get("status") != "READY_FOR_POSTPROCESS":
            raise ValueError("final public probe result status mismatch")
        if result.get("verdict") != ACCEPTED_VERDICT:
            raise ValueError("final public probe result verdict mismatch")
        if (
            quality.get("partial_output") is not False
            or int(quality.get("error_count") or 0) != 0
            or int(quality.get("snapshot_count") or 0)
            != int(quality.get("expected_snapshot_count") or -1)
        ):
            raise ValueError("final public probe result quality mismatch")
    return result


def build_probe_evidence(
    *,
    manifest_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(manifest_path).expanduser().resolve()
    result = validate_probe_result(
        target,
        expected_plan_hash=expected_plan_hash,
    )
    version = _result_version(result)
    accepted = result.get("final") is True
    deterministic = {
        "schema": EVIDENCE_SCHEMAS[version],
        "task_id": f"paper_public_readonly_probe_evidence_{version}",
        "probe_result": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "deterministic_result_hash": result[
                "deterministic_result_hash"
            ],
            "run_id": result["run_id"],
            "plan_hash_sha256": result["plan"]["plan_hash_sha256"],
        },
        "quality": dict(result["quality"]),
        "safety": dict(result["safety"]),
        "verdict": (
            "PUBLIC_READONLY_PROBE_EVIDENCE_ACCEPTED"
            if accepted
            else "PUBLIC_READONLY_PROBE_EVIDENCE_REJECTED"
        ),
        "next_allowed_action": (
            "paper_product_readiness_audit_v8"
            if accepted
            else "USER_REVIEW_REQUIRED_STOPPED_INCOMPLETE"
        ),
    }
    evidence = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc or _utc_now(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, evidence)
    return evidence


def validate_probe_evidence(
    evidence_path: str | Path,
    *,
    manifest_path: str | Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    target = Path(evidence_path).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    evidence = _read_json(target)
    result = validate_probe_result(
        manifest_target,
        expected_plan_hash=expected_plan_hash,
    )
    version = _result_version(result)
    if evidence.get("schema") != EVIDENCE_SCHEMAS[version]:
        raise ValueError("public probe evidence schema mismatch")
    if evidence.get("task_id") != (
        f"paper_public_readonly_probe_evidence_{version}"
    ):
        raise ValueError("public probe evidence task id mismatch")
    deterministic = {
        key: value
        for key, value in evidence.items()
        if key not in {"deterministic_result_hash", "generated_at_utc"}
    }
    if sha256_json(deterministic) != str(
        evidence.get("deterministic_result_hash") or ""
    ).lower():
        raise ValueError("public probe evidence deterministic hash mismatch")
    probe_result = evidence.get("probe_result")
    if not isinstance(probe_result, Mapping):
        raise ValueError("public probe evidence result binding is missing")
    if Path(str(probe_result.get("path") or "")).resolve() != manifest_target:
        raise ValueError("public probe evidence manifest path mismatch")
    if str(probe_result.get("file_sha256") or "").lower() != sha256_file(
        manifest_target
    ):
        raise ValueError("public probe evidence manifest hash mismatch")
    expected_bindings = {
        "deterministic_result_hash": result["deterministic_result_hash"],
        "run_id": result["run_id"],
        "plan_hash_sha256": result["plan"]["plan_hash_sha256"],
    }
    for key, expected_value in expected_bindings.items():
        if str(probe_result.get(key) or "") != str(expected_value):
            raise ValueError(f"public probe evidence {key} mismatch")
    if evidence.get("quality") != result.get("quality"):
        raise ValueError("public probe evidence quality mismatch")
    if evidence.get("safety") != result.get("safety"):
        raise ValueError("public probe evidence safety mismatch")
    accepted = result.get("final") is True
    expected_verdict = (
        "PUBLIC_READONLY_PROBE_EVIDENCE_ACCEPTED"
        if accepted
        else "PUBLIC_READONLY_PROBE_EVIDENCE_REJECTED"
    )
    expected_next_action = (
        "paper_product_readiness_audit_v8"
        if accepted
        else "USER_REVIEW_REQUIRED_STOPPED_INCOMPLETE"
    )
    if evidence.get("verdict") != expected_verdict:
        raise ValueError("public probe evidence verdict mismatch")
    if evidence.get("next_allowed_action") != expected_next_action:
        raise ValueError("public probe evidence next action mismatch")
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen bounded public read-only market probe."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    validate = subparsers.add_parser("validate-plan")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash", required=True)

    standing = subparsers.add_parser("create-standing-authorization")
    standing.add_argument("--policy", required=True)
    standing.add_argument("--project-root", required=True)
    standing.add_argument("--user-instruction", required=True)
    standing.add_argument("--contract-authorization-text", required=True)
    standing.add_argument("--output", required=True)

    validate_standing = subparsers.add_parser(
        "validate-standing-authorization"
    )
    validate_standing.add_argument("--authorization", required=True)
    validate_standing.add_argument(
        "--expected-authorization-hash",
        required=True,
    )

    validate_standing_plan = subparsers.add_parser(
        "validate-plan-under-standing-authorization"
    )
    validate_standing_plan.add_argument("--plan", required=True)
    validate_standing_plan.add_argument("--expected-plan-hash", required=True)
    validate_standing_plan.add_argument(
        "--standing-authorization",
        required=True,
    )
    validate_standing_plan.add_argument(
        "--expected-standing-authorization-hash",
        required=True,
    )

    critical = subparsers.add_parser("create-v3-critical-authorization")
    critical.add_argument("--plan", required=True)
    critical.add_argument("--expected-plan-hash", required=True)
    critical.add_argument("--standing-authorization", required=True)
    critical.add_argument(
        "--expected-standing-authorization-hash",
        required=True,
    )
    critical.add_argument("--failure-audit", required=True)
    critical.add_argument("--user-instruction", required=True)
    critical.add_argument("--thread-id", required=True)
    critical.add_argument("--output", required=True)

    validate_critical = subparsers.add_parser(
        "validate-v3-critical-authorization"
    )
    validate_critical.add_argument("--authorization", required=True)
    validate_critical.add_argument(
        "--expected-authorization-hash",
        required=True,
    )
    validate_critical.add_argument("--plan", required=True)
    validate_critical.add_argument("--expected-plan-hash", required=True)
    validate_critical.add_argument("--standing-authorization", required=True)
    validate_critical.add_argument(
        "--expected-standing-authorization-hash",
        required=True,
    )
    validate_critical.add_argument("--failure-audit", required=True)

    validate_v3_plan = subparsers.add_parser(
        "validate-plan-under-v3-critical-authorization"
    )
    validate_v3_plan.add_argument("--plan", required=True)
    validate_v3_plan.add_argument("--expected-plan-hash", required=True)
    validate_v3_plan.add_argument("--standing-authorization", required=True)
    validate_v3_plan.add_argument(
        "--expected-standing-authorization-hash",
        required=True,
    )
    validate_v3_plan.add_argument("--critical-authorization", required=True)
    validate_v3_plan.add_argument(
        "--expected-critical-authorization-hash",
        required=True,
    )
    validate_v3_plan.add_argument("--failure-audit", required=True)

    authorize = subparsers.add_parser("authorize")
    authorize.add_argument("--plan", required=True)
    authorize.add_argument("--expected-plan-hash", required=True)
    authorize.add_argument("--run-id", required=True)
    authorize.add_argument("--user-instruction", required=True)
    authorize.add_argument("--thread-id", required=True)
    authorize.add_argument("--standing-authorization")
    authorize.add_argument("--expected-standing-authorization-hash")
    authorize.add_argument("--critical-authorization")
    authorize.add_argument("--expected-critical-authorization-hash")
    authorize.add_argument("--freshness-failure-audit")
    authorize.add_argument("--output", required=True)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--plan", required=True)
    probe.add_argument("--expected-plan-hash", required=True)
    probe.add_argument("--authorization", required=True)
    probe.add_argument("--expected-authorization-hash", required=True)
    probe.add_argument("--output-dir", required=True)
    probe.add_argument("--run-id", required=True)
    probe.add_argument("--max-runtime-sec", type=int, required=True)

    validate_result = subparsers.add_parser("validate-result")
    validate_result.add_argument("--manifest", required=True)
    validate_result.add_argument("--expected-plan-hash", required=True)

    postprocess = subparsers.add_parser("postprocess")
    postprocess.add_argument("--manifest", required=True)
    postprocess.add_argument("--expected-plan-hash", required=True)
    postprocess.add_argument("--output", required=True)

    validate_evidence = subparsers.add_parser("validate-evidence")
    validate_evidence.add_argument("--evidence", required=True)
    validate_evidence.add_argument("--manifest", required=True)
    validate_evidence.add_argument("--expected-plan-hash", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "validate-plan":
        plan, contract = validate_probe_plan(
            args.plan,
            args.expected_plan_hash,
        )
        result = {
            "decision": "FROZEN_PUBLIC_READONLY_PROBE_PLAN_VALID",
            "plan_path": str(Path(args.plan).resolve()),
            "plan_file_sha256": sha256_file(args.plan),
            "plan_hash_sha256": plan["plan_hash_sha256"],
            "contract_hash_sha256": contract["contract_hash_sha256"],
            "duration_sec": plan["probe"]["duration_sec"],
            "max_runtime_sec": plan["probe"]["max_runtime_sec"],
            "venues": plan["probe"]["venues"],
            "network_requests_performed": 0,
        }
    elif args.action == "create-standing-authorization":
        result = build_standing_authorization(
            policy_path=args.policy,
            project_root=args.project_root,
            user_instruction=args.user_instruction,
            contract_authorization_text=args.contract_authorization_text,
            output_path=args.output,
        )
    elif args.action == "validate-standing-authorization":
        result = validate_standing_authorization(
            args.authorization,
            expected_authorization_hash=args.expected_authorization_hash,
        )
    elif args.action == "validate-plan-under-standing-authorization":
        plan, contract, standing = (
            validate_plan_under_standing_authorization(
                plan_path=args.plan,
                expected_plan_hash=args.expected_plan_hash,
                standing_authorization_path=args.standing_authorization,
                expected_standing_authorization_hash=(
                    args.expected_standing_authorization_hash
                ),
            )
        )
        result = {
            "decision": "PLAN_AUTHORIZED_BY_STANDING_POLICY",
            "plan_hash_sha256": plan["plan_hash_sha256"],
            "contract_hash_sha256": contract["contract_hash_sha256"],
            "standing_authorization_hash_sha256": standing[
                "authorization_hash_sha256"
            ],
            "automatic_start": True,
            "visible_terminal_required": True,
        }
    elif args.action == "create-v3-critical-authorization":
        result = build_v3_critical_authorization(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            standing_authorization_path=args.standing_authorization,
            expected_standing_authorization_hash=(
                args.expected_standing_authorization_hash
            ),
            failure_audit_path=args.failure_audit,
            user_instruction=args.user_instruction,
            thread_id=args.thread_id,
            output_path=args.output,
        )
    elif args.action == "validate-v3-critical-authorization":
        result = validate_v3_critical_authorization(
            args.authorization,
            expected_authorization_hash=args.expected_authorization_hash,
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            standing_authorization_path=args.standing_authorization,
            expected_standing_authorization_hash=(
                args.expected_standing_authorization_hash
            ),
            failure_audit_path=args.failure_audit,
        )
    elif args.action == "validate-plan-under-v3-critical-authorization":
        plan, contract, standing, critical = (
            validate_plan_under_v3_critical_authorization(
                plan_path=args.plan,
                expected_plan_hash=args.expected_plan_hash,
                standing_authorization_path=args.standing_authorization,
                expected_standing_authorization_hash=(
                    args.expected_standing_authorization_hash
                ),
                critical_authorization_path=args.critical_authorization,
                expected_critical_authorization_hash=(
                    args.expected_critical_authorization_hash
                ),
                failure_audit_path=args.failure_audit,
            )
        )
        result = {
            "decision": "PLAN_AUTHORIZED_BY_ONE_TIME_V3_CRITICAL_APPROVAL",
            "plan_hash_sha256": plan["plan_hash_sha256"],
            "contract_hash_sha256": contract["contract_hash_sha256"],
            "standing_authorization_hash_sha256": standing[
                "authorization_hash_sha256"
            ],
            "critical_authorization_hash_sha256": critical[
                "authorization_hash_sha256"
            ],
            "automatic_start": True,
            "visible_terminal_required": True,
        }
    elif args.action == "authorize":
        result = build_user_authorization(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            run_id=args.run_id,
            user_instruction=args.user_instruction,
            thread_id=args.thread_id,
            standing_authorization_path=args.standing_authorization,
            expected_standing_authorization_hash=(
                args.expected_standing_authorization_hash
            ),
            critical_authorization_path=args.critical_authorization,
            expected_critical_authorization_hash=(
                args.expected_critical_authorization_hash
            ),
            freshness_failure_audit_path=args.freshness_failure_audit,
            output_path=args.output,
        )
    elif args.action == "probe":
        result = run_probe(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            authorization_path=args.authorization,
            expected_authorization_hash=args.expected_authorization_hash,
            output_dir=args.output_dir,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    elif args.action == "validate-result":
        result = validate_probe_result(
            args.manifest,
            expected_plan_hash=args.expected_plan_hash,
        )
    elif args.action == "postprocess":
        result = build_probe_evidence(
            manifest_path=args.manifest,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
        )
    else:
        result = validate_probe_evidence(
            args.evidence,
            manifest_path=args.manifest,
            expected_plan_hash=args.expected_plan_hash,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    if args.action == "probe" and result.get("final") is not True:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
