from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from canonical_asset_registry import (
    PLAN_SCHEMA as REGISTRY_PLAN_SCHEMA,
    RESULT_SCHEMA as REGISTRY_RESULT_SCHEMA,
    build_canonical_registry_plan,
    sha256_file,
    validate_canonical_registry_plan,
    validate_canonical_registry_result,
)
from gate_futures_archive import DEFAULT_CREDENTIAL_ENV
from gate_momentum_archive import (
    HYPOTHESIS_ID,
    PROBE_DESCRIPTOR_SCHEMA,
    PROBE_RESULT_SCHEMA,
    build_momentum_archive_plan,
    validate_momentum_archive_plan,
    validate_momentum_public_probe_descriptor,
    validate_momentum_public_probe_result,
)


IDENTITY_PLAN_SCHEMA = "trading_mvp_gate_momentum_identity_plan_v1"
IDENTITY_RESULT_SCHEMA = "trading_mvp_gate_momentum_identity_result_v1"
TARDIS_INSTRUMENTS_BASE_URL = "https://api.tardis.dev/v1/instruments"
MAX_IDENTITY_RUNTIME_SEC = 300
DEFAULT_IDENTITY_RUNTIME_SEC = 120
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MINIMUM_CANONICAL_ASSETS = 20
HISTORY_DAYS = 220
HASH_CHARACTERS = frozenset("0123456789abcdef")


class IdentityCredentialError(RuntimeError):
    pass


class IdentitySchemaError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {source}")
    return payload


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if target.exists():
        if target.read_bytes() != content:
            raise FileExistsError(f"refusing to overwrite immutable artifact: {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _validate_hash(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(character not in HASH_CHARACTERS for character in digest):
        raise ValueError(f"invalid {label}")
    return digest


def _module_path_for(function: Any) -> Path:
    module = sys.modules.get(function.__module__)
    path = getattr(module, "__file__", None)
    if not path:
        raise RuntimeError(f"cannot resolve module path for {function.__module__}")
    return Path(path).resolve()


def _artifact_reference(
    path: str | Path,
    *,
    semantic_hash_name: str,
    semantic_hash: str,
    schema: str,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"required immutable artifact is missing: {resolved}")
    return {
        "path": str(resolved),
        "file_sha256": sha256_file(resolved),
        "schema": schema,
        semantic_hash_name: _validate_hash(
            semantic_hash,
            label=semantic_hash_name,
        ),
    }


def _request_contract() -> list[dict[str, Any]]:
    return [
        {
            "kind": "instrument_metadata",
            "exchange": "gate-io-futures",
            "url": f"{TARDIS_INSTRUMENTS_BASE_URL}/gate-io-futures",
            "filter": {
                "quoteCurrency": "USDT",
                "type": "perpetual",
            },
            "local_required_fields": [
                "id",
                "datasetId",
                "exchange",
                "baseCurrency",
                "quoteCurrency",
                "type",
                "active",
                "availableSince",
                "availableTo",
                "contractType",
            ],
            "market_values_allowed": False,
        },
        {
            "kind": "instrument_metadata",
            "exchange": "binance",
            "url": f"{TARDIS_INSTRUMENTS_BASE_URL}/binance",
            "filter": {"type": "spot"},
            "local_required_fields": [
                "id",
                "datasetId",
                "exchange",
                "baseCurrency",
                "quoteCurrency",
                "type",
                "active",
                "availableSince",
                "availableTo",
            ],
            "market_values_allowed": False,
        },
    ]


def _identity_contract() -> dict[str, Any]:
    return {
        "canonical_registry": "CoinGecko active_plus_inactive venue-neutral registry",
        "canonical_asset_id_prefix": "coingecko:",
        "mapping_rule": "unique_coingecko_symbol_only",
        "exclude_symbol_collisions": True,
        "exclude_unmatched_assets": True,
        "manual_symbol_overrides": False,
        "duplicate_gate_canonical_assets_excluded": True,
        "tardis_normalized_base_is_not_canonical_identity": True,
        "gate_required_type": "perpetual",
        "gate_required_quote_currency": "USDT",
        "gate_required_contract_type": "linear_perpetual",
        "binance_required_type": "spot",
        "binance_any_quote_counts_as_listed": True,
        "binance_exclusion_is_point_in_time": True,
        "binance_interval_fields": ["availableSince", "availableTo"],
        "gate_interval_fields": ["availableSince", "availableTo"],
        "available_since_is_data_coverage_not_exchange_listing": True,
        "available_to_may_lag_actual_delisting": True,
        "conservative_lifecycle_masking": True,
        "current_non_binance_csv_allowed": False,
    }


def _quality_contract() -> dict[str, Any]:
    return {
        "minimum_canonical_gate_assets": MINIMUM_CANONICAL_ASSETS,
        "minimum_required_history_days": HISTORY_DAYS,
        "gate_available_since_required": True,
        "binance_available_since_required": True,
        "inverted_lifecycle_rejected": True,
        "duplicate_exchange_instrument_ids_rejected": True,
        "duplicate_dataset_ids_rejected": True,
        "minimum_gate_lifecycle_span_days": HISTORY_DAYS,
        "symbol_collision_autoresolution": False,
        "history_collect_allowed_after_identity_plan": False,
        "identity_result_required_before_history_plan": True,
    }


def _credential_contract() -> dict[str, Any]:
    return {
        "provider": "Tardis.dev",
        "environment_variable": DEFAULT_CREDENTIAL_ENV,
        "authorization_location": "header_runtime_only",
        "authorization_scheme": "Bearer",
        "minimum_subscription": "Pro_or_Business",
        "required_data_scope": ["Gate.io Futures", "Binance Spot"],
        "value_persisted": False,
    }


def _safety_contract() -> dict[str, Any]:
    return {
        "metadata_only": True,
        "history_collect": False,
        "returns": False,
        "signals": False,
        "strategy_evaluation": False,
        "pnl": False,
        "oos": False,
        "grid_search": False,
        "retune": False,
        "execution_probe": False,
        "paper_forward": False,
        "live_orders": False,
        "private_exchange_api_keys": False,
        "leverage_or_margin": False,
        "automatic_transition": False,
    }


def _plan_hash(plan: Mapping[str, Any]) -> str:
    return sha256_json(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )


def _load_and_validate_inputs(
    momentum_plan_path: str | Path,
    public_descriptor_path: str | Path,
    public_probe_result_path: str | Path,
    registry_plan_path: str | Path,
    registry_manifest_path: str | Path,
) -> dict[str, Any]:
    momentum_plan_resolved = Path(momentum_plan_path).expanduser().resolve()
    descriptor_resolved = Path(public_descriptor_path).expanduser().resolve()
    probe_result_resolved = Path(public_probe_result_path).expanduser().resolve()
    registry_plan_resolved = Path(registry_plan_path).expanduser().resolve()
    registry_manifest_resolved = Path(registry_manifest_path).expanduser().resolve()

    momentum_plan = _read_json_object(momentum_plan_resolved)
    validated_momentum = validate_momentum_archive_plan(momentum_plan)
    descriptor = _read_json_object(descriptor_resolved)
    validated_descriptor = validate_momentum_public_probe_descriptor(
        validated_momentum,
        descriptor,
    )
    probe_result = _read_json_object(probe_result_resolved)
    validated_probe = validate_momentum_public_probe_result(
        probe_result,
        plan=validated_momentum,
        descriptor=validated_descriptor,
    )
    if validated_probe.get("accepted_for_identity_probe_planonly") is not True:
        raise ValueError("public schema probe did not authorize identity PlanOnly")

    registry_plan = validate_canonical_registry_plan(registry_plan_resolved)
    registry_result = validate_canonical_registry_result(
        registry_manifest_resolved,
        plan_path=registry_plan_resolved,
    )
    return {
        "momentum_plan": validated_momentum,
        "momentum_plan_path": momentum_plan_resolved,
        "descriptor": validated_descriptor,
        "descriptor_path": descriptor_resolved,
        "probe_result": validated_probe,
        "probe_result_path": probe_result_resolved,
        "registry_plan": registry_plan,
        "registry_plan_path": registry_plan_resolved,
        "registry_result": registry_result,
        "registry_manifest_path": registry_manifest_resolved,
    }


def build_gate_momentum_identity_plan(
    momentum_plan_path: str | Path,
    public_descriptor_path: str | Path,
    public_probe_result_path: str | Path,
    registry_plan_path: str | Path,
    registry_manifest_path: str | Path,
    *,
    gate_instruments_output_path: str | Path,
    binance_instruments_output_path: str | Path,
    identity_result_output_path: str | Path,
    frozen_at_utc: str | None = None,
    max_runtime_sec: int = DEFAULT_IDENTITY_RUNTIME_SEC,
) -> dict[str, Any]:
    if not 1 <= int(max_runtime_sec) <= MAX_IDENTITY_RUNTIME_SEC:
        raise ValueError(
            f"max_runtime_sec must be between 1 and {MAX_IDENTITY_RUNTIME_SEC}"
        )
    inputs = _load_and_validate_inputs(
        momentum_plan_path,
        public_descriptor_path,
        public_probe_result_path,
        registry_plan_path,
        registry_manifest_path,
    )

    output_paths = {
        "gate_instruments_jsonl_path": str(
            Path(gate_instruments_output_path).expanduser().resolve()
        ),
        "binance_instruments_jsonl_path": str(
            Path(binance_instruments_output_path).expanduser().resolve()
        ),
        "identity_result_json_path": str(
            Path(identity_result_output_path).expanduser().resolve()
        ),
    }
    if len(set(output_paths.values())) != len(output_paths):
        raise ValueError("identity output paths must be distinct")

    module_path = Path(__file__).resolve()
    momentum_module_path = _module_path_for(build_momentum_archive_plan)
    registry_module_path = _module_path_for(build_canonical_registry_plan)
    registry_result = inputs["registry_result"]
    plan: dict[str, Any] = {
        "schema": IDENTITY_PLAN_SCHEMA,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_at_utc": frozen_at_utc or _utc_now(),
        "hypothesis_id": HYPOTHESIS_ID,
        "inputs": {
            "momentum_plan": _artifact_reference(
                inputs["momentum_plan_path"],
                semantic_hash_name="plan_hash",
                semantic_hash=inputs["momentum_plan"]["plan_hash"],
                schema=str(inputs["momentum_plan"]["schema"]),
            ),
            "public_probe_descriptor": _artifact_reference(
                inputs["descriptor_path"],
                semantic_hash_name="descriptor_hash",
                semantic_hash=inputs["descriptor"]["descriptor_hash"],
                schema=PROBE_DESCRIPTOR_SCHEMA,
            ),
            "public_probe_result": _artifact_reference(
                inputs["probe_result_path"],
                semantic_hash_name="artifact_hash",
                semantic_hash=inputs["probe_result"]["artifact_hash"],
                schema=PROBE_RESULT_SCHEMA,
            ),
            "canonical_registry_plan": _artifact_reference(
                inputs["registry_plan_path"],
                semantic_hash_name="plan_hash",
                semantic_hash=inputs["registry_plan"]["plan_hash"],
                schema=REGISTRY_PLAN_SCHEMA,
            ),
            "canonical_registry_result": {
                **_artifact_reference(
                    inputs["registry_manifest_path"],
                    semantic_hash_name="artifact_hash",
                    semantic_hash=registry_result["artifact_hash"],
                    schema=REGISTRY_RESULT_SCHEMA,
                ),
                "registry_jsonl_path": registry_result["registry_jsonl_path"],
                "registry_sha256": registry_result["registry_sha256"],
                "row_count": registry_result["row_count"],
            },
        },
        "requests": _request_contract(),
        "credential": _credential_contract(),
        "identity": _identity_contract(),
        "quality": _quality_contract(),
        "limits": {
            "max_runtime_sec": int(max_runtime_sec),
            "max_response_bytes_per_exchange": MAX_RESPONSE_BYTES,
            "request_count": 2,
        },
        "outputs": {
            **output_paths,
            "immutable": True,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
            "momentum_module_path": str(momentum_module_path),
            "momentum_module_sha256": sha256_file(momentum_module_path),
            "registry_module_path": str(registry_module_path),
            "registry_module_sha256": sha256_file(registry_module_path),
        },
        "data_access_audit": {
            "network_access": False,
            "instrument_metadata_read": False,
            "market_rows_read": False,
            "market_values_read": False,
            "returns_read": False,
            "signals_computed": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "safety": _safety_contract(),
        "decision": "IDENTITY_PLAN_READY_AWAITING_VISIBLE_METADATA_COLLECT",
        "history_collect_allowed": False,
        "next_allowed_command": "gate-momentum-identity-metadata-collect-visible",
    }
    plan["plan_hash"] = _plan_hash(plan)
    return plan


def _verify_input_reference(
    reference: Mapping[str, Any],
    *,
    label: str,
) -> Path:
    path = Path(str(reference.get("path") or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    if sha256_file(path) != reference.get("file_sha256"):
        raise ValueError(f"{label} file hash mismatch")
    return path


def validate_gate_momentum_identity_plan(path: str | Path) -> dict[str, Any]:
    plan = _read_json_object(path)
    if (
        plan.get("schema") != IDENTITY_PLAN_SCHEMA
        or plan.get("mode") != "PlanOnly"
        or plan.get("research_only") is not True
    ):
        raise ValueError("unexpected identity PlanOnly")
    observed_hash = _validate_hash(plan.get("plan_hash"), label="identity plan hash")
    if _plan_hash(plan) != observed_hash:
        raise ValueError("identity plan hash mismatch")
    if plan.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("identity hypothesis mismatch")
    if plan.get("requests") != _request_contract():
        raise ValueError("identity request contract mismatch")
    if plan.get("identity") != _identity_contract():
        raise ValueError("identity mapping contract mismatch")
    if plan.get("quality") != _quality_contract():
        raise ValueError("identity quality contract mismatch")
    if plan.get("safety") != _safety_contract():
        raise ValueError("identity safety contract mismatch")
    if plan.get("history_collect_allowed") is not False:
        raise ValueError("identity plan cannot authorize history")
    if (
        plan.get("decision") != "IDENTITY_PLAN_READY_AWAITING_VISIBLE_METADATA_COLLECT"
        or plan.get("next_allowed_command")
        != "gate-momentum-identity-metadata-collect-visible"
    ):
        raise ValueError("identity plan decision mismatch")

    limits = plan.get("limits")
    if not isinstance(limits, Mapping):
        raise ValueError("identity limits are missing")
    max_runtime_sec = limits.get("max_runtime_sec")
    if (
        not isinstance(max_runtime_sec, int)
        or not 1 <= max_runtime_sec <= MAX_IDENTITY_RUNTIME_SEC
        or limits.get("max_response_bytes_per_exchange") != MAX_RESPONSE_BYTES
        or limits.get("request_count") != 2
    ):
        raise ValueError("identity limits mismatch")

    credential = plan.get("credential")
    if not isinstance(credential, Mapping) or dict(credential) != _credential_contract():
        raise ValueError("identity credential contract mismatch")

    audit = plan.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(value is not False for value in audit.values()):
        raise ValueError("identity data-access audit mismatch")
    outputs = plan.get("outputs")
    if not isinstance(outputs, Mapping) or outputs.get("immutable") is not True:
        raise ValueError("identity outputs are missing")
    output_values = [
        str(outputs.get("gate_instruments_jsonl_path") or ""),
        str(outputs.get("binance_instruments_jsonl_path") or ""),
        str(outputs.get("identity_result_json_path") or ""),
    ]
    if any(not value for value in output_values) or len(set(output_values)) != 3:
        raise ValueError("identity output paths mismatch")

    code = plan.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("identity code provenance is missing")
    module_path = Path(str(code.get("module_path") or "")).resolve()
    momentum_module_path = Path(str(code.get("momentum_module_path") or "")).resolve()
    registry_module_path = Path(str(code.get("registry_module_path") or "")).resolve()
    expected_momentum_module = _module_path_for(build_momentum_archive_plan)
    expected_registry_module = _module_path_for(build_canonical_registry_plan)
    if module_path != Path(__file__).resolve():
        raise ValueError("identity module path mismatch")
    if momentum_module_path != expected_momentum_module:
        raise ValueError("identity momentum module path mismatch")
    if registry_module_path != expected_registry_module:
        raise ValueError("identity registry module path mismatch")
    for file_path, hash_key in (
        (module_path, "module_sha256"),
        (momentum_module_path, "momentum_module_sha256"),
        (registry_module_path, "registry_module_sha256"),
    ):
        if sha256_file(file_path) != code.get(hash_key):
            raise ValueError(f"identity code hash mismatch: {hash_key}")

    inputs = plan.get("inputs")
    if not isinstance(inputs, Mapping):
        raise ValueError("identity input references are missing")
    momentum_ref = inputs.get("momentum_plan")
    descriptor_ref = inputs.get("public_probe_descriptor")
    probe_ref = inputs.get("public_probe_result")
    registry_plan_ref = inputs.get("canonical_registry_plan")
    registry_result_ref = inputs.get("canonical_registry_result")
    for label, reference in (
        ("momentum plan", momentum_ref),
        ("public probe descriptor", descriptor_ref),
        ("public probe result", probe_ref),
        ("canonical registry plan", registry_plan_ref),
        ("canonical registry result", registry_result_ref),
    ):
        if not isinstance(reference, Mapping):
            raise ValueError(f"{label} reference is missing")

    momentum_path = _verify_input_reference(momentum_ref, label="momentum plan")
    descriptor_path = _verify_input_reference(
        descriptor_ref,
        label="public probe descriptor",
    )
    probe_path = _verify_input_reference(probe_ref, label="public probe result")
    registry_plan_path = _verify_input_reference(
        registry_plan_ref,
        label="canonical registry plan",
    )
    registry_result_path = _verify_input_reference(
        registry_result_ref,
        label="canonical registry result",
    )

    momentum_plan = _read_json_object(momentum_path)
    validated_momentum = validate_momentum_archive_plan(
        momentum_plan,
        expected_plan_hash=str(momentum_ref.get("plan_hash") or ""),
    )
    descriptor = _read_json_object(descriptor_path)
    validated_descriptor = validate_momentum_public_probe_descriptor(
        validated_momentum,
        descriptor,
    )
    if validated_descriptor["descriptor_hash"] != descriptor_ref.get("descriptor_hash"):
        raise ValueError("public probe descriptor semantic hash mismatch")
    probe_result = _read_json_object(probe_path)
    validated_probe = validate_momentum_public_probe_result(
        probe_result,
        plan=validated_momentum,
        descriptor=validated_descriptor,
    )
    if validated_probe["artifact_hash"] != probe_ref.get("artifact_hash"):
        raise ValueError("public probe result semantic hash mismatch")
    if validated_probe.get("accepted_for_identity_probe_planonly") is not True:
        raise ValueError("public schema probe does not authorize identity")

    registry_plan = validate_canonical_registry_plan(registry_plan_path)
    if registry_plan["plan_hash"] != registry_plan_ref.get("plan_hash"):
        raise ValueError("canonical registry plan semantic hash mismatch")
    registry_result = validate_canonical_registry_result(
        registry_result_path,
        plan_path=registry_plan_path,
    )
    if registry_result["artifact_hash"] != registry_result_ref.get("artifact_hash"):
        raise ValueError("canonical registry result semantic hash mismatch")
    if registry_result["registry_sha256"] != registry_result_ref.get("registry_sha256"):
        raise ValueError("canonical registry content semantic hash mismatch")
    if registry_result["registry_jsonl_path"] != registry_result_ref.get(
        "registry_jsonl_path"
    ):
        raise ValueError("canonical registry content path reference mismatch")
    return plan


def _parse_lifecycle_timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IdentitySchemaError(
            "LIFECYCLE_TIMESTAMP_MISSING",
            f"{label} is missing",
        )
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise IdentitySchemaError(
            "LIFECYCLE_TIMESTAMP_INVALID",
            f"{label} is not an ISO timestamp",
        ) from exc
    if parsed.tzinfo is None:
        raise IdentitySchemaError(
            "LIFECYCLE_TIMESTAMP_NAIVE",
            f"{label} must include timezone information",
        )
    return parsed.astimezone(timezone.utc)


def _normalized_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _bounded_json_array(
    response: Any,
    *,
    max_bytes: int,
    exchange: str,
) -> tuple[list[Any], bytes]:
    raw_length = response.headers.get("Content-Length") if response.headers else None
    if raw_length:
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise IdentitySchemaError(
                "INVALID_CONTENT_LENGTH",
                f"{exchange} metadata Content-Length is invalid",
            ) from exc
        if content_length > max_bytes:
            raise IdentitySchemaError(
                "METADATA_RESPONSE_TOO_LARGE",
                f"{exchange} metadata exceeds {max_bytes} bytes",
            )
    body = bytearray()
    for raw_chunk in response.iter_content(chunk_size=64 * 1024):
        chunk = bytes(raw_chunk or b"")
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > max_bytes:
            raise IdentitySchemaError(
                "METADATA_RESPONSE_TOO_LARGE",
                f"{exchange} metadata exceeds {max_bytes} bytes",
            )
    raw = bytes(body)
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentitySchemaError(
            "METADATA_JSON_INVALID",
            f"{exchange} metadata is not a UTF-8 JSON array",
        ) from exc
    if not isinstance(payload, list):
        raise IdentitySchemaError(
            "METADATA_RESPONSE_SHAPE_INVALID",
            f"{exchange} metadata response must be an array",
        )
    return payload, raw


def _normalize_instrument_rows(
    raw_rows: Sequence[Any],
    *,
    request_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    exchange = str(request_contract["exchange"])
    expected_filter = request_contract["filter"]
    normalized: list[dict[str, Any]] = []
    instrument_ids: set[str] = set()
    dataset_ids: set[str] = set()
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise IdentitySchemaError(
                "INSTRUMENT_ROW_INVALID",
                f"{exchange} instrument row {index} is not an object",
            )
        instrument_id = str(raw.get("id") or "").strip()
        dataset_id = str(raw.get("datasetId") or "").strip()
        observed_exchange = str(raw.get("exchange") or "").strip()
        base = str(raw.get("baseCurrency") or "").strip().upper()
        quote = str(raw.get("quoteCurrency") or "").strip().upper()
        instrument_type = str(raw.get("type") or "").strip().lower()
        active = raw.get("active")
        if not instrument_id or not dataset_id or not base or not quote:
            raise IdentitySchemaError(
                "INSTRUMENT_REQUIRED_FIELD_MISSING",
                f"{exchange} instrument row {index} has missing identity fields",
            )
        if observed_exchange != exchange:
            raise IdentitySchemaError(
                "INSTRUMENT_EXCHANGE_MISMATCH",
                f"{exchange} response contains {observed_exchange}",
            )
        if active not in (True, False):
            raise IdentitySchemaError(
                "INSTRUMENT_ACTIVE_FLAG_INVALID",
                f"{exchange}.{instrument_id} active flag is invalid",
            )
        if instrument_id in instrument_ids:
            raise IdentitySchemaError(
                "DUPLICATE_INSTRUMENT_ID",
                f"{exchange} contains duplicate instrument id {instrument_id}",
            )
        if dataset_id in dataset_ids:
            raise IdentitySchemaError(
                "DUPLICATE_DATASET_ID",
                f"{exchange} contains duplicate dataset id {dataset_id}",
            )
        instrument_ids.add(instrument_id)
        dataset_ids.add(dataset_id)

        if instrument_type != str(expected_filter["type"]).lower():
            raise IdentitySchemaError(
                "INSTRUMENT_TYPE_MISMATCH",
                f"{exchange}.{instrument_id} has unexpected type {instrument_type}",
            )
        if "quoteCurrency" in expected_filter and quote != str(
            expected_filter["quoteCurrency"]
        ).upper():
            raise IdentitySchemaError(
                "INSTRUMENT_QUOTE_MISMATCH",
                f"{exchange}.{instrument_id} has unexpected quote {quote}",
            )
        contract_type = (
            str(raw.get("contractType") or "").strip().lower()
            if exchange == "gate-io-futures"
            else None
        )
        if exchange == "gate-io-futures" and contract_type != "linear_perpetual":
            raise IdentitySchemaError(
                "GATE_CONTRACT_TYPE_MISMATCH",
                f"{exchange}.{instrument_id} is not linear_perpetual",
            )

        available_since = _parse_lifecycle_timestamp(
            raw.get("availableSince"),
            label=f"{exchange}.{instrument_id}.availableSince",
        )
        raw_available_to = raw.get("availableTo")
        available_to = (
            _parse_lifecycle_timestamp(
                raw_available_to,
                label=f"{exchange}.{instrument_id}.availableTo",
            )
            if raw_available_to not in (None, "")
            else None
        )
        if available_to is not None and available_to < available_since:
            raise IdentitySchemaError(
                "LIFECYCLE_RANGE_INVALID",
                f"{exchange}.{instrument_id} availableTo precedes availableSince",
            )
        normalized.append(
            {
                "exchange": exchange,
                "instrument_id": instrument_id,
                "dataset_id": dataset_id,
                "base_currency": base,
                "quote_currency": quote,
                "instrument_type": instrument_type,
                "contract_type": contract_type,
                "active": bool(active),
                "available_since": _normalized_timestamp(available_since),
                "available_to": (
                    _normalized_timestamp(available_to)
                    if available_to is not None
                    else None
                ),
            }
        )
    return normalized


def _load_unique_registry_symbols(plan: Mapping[str, Any]) -> dict[str, Any]:
    result_ref = plan["inputs"]["canonical_registry_result"]
    registry_path = Path(str(result_ref["registry_jsonl_path"])).resolve()
    if sha256_file(registry_path) != result_ref["registry_sha256"]:
        raise ValueError("canonical registry changed after identity PlanOnly freeze")
    by_symbol: dict[str, list[str]] = defaultdict(list)
    row_count = 0
    with registry_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid canonical registry JSONL at line {line_number}"
                ) from exc
            if not isinstance(row, Mapping):
                raise ValueError(
                    f"invalid canonical registry row at line {line_number}"
                )
            canonical_id = str(row.get("canonical_asset_id") or "")
            symbol = str(row.get("symbol") or "").strip().upper()
            if not canonical_id.startswith("coingecko:") or not symbol:
                raise ValueError(
                    f"invalid canonical registry identity at line {line_number}"
                )
            by_symbol[symbol].append(canonical_id)
            row_count += 1
    if row_count != int(result_ref["row_count"]):
        raise ValueError("canonical registry row count changed after freeze")
    collisions = {
        symbol for symbol, canonical_ids in by_symbol.items() if len(canonical_ids) != 1
    }
    unique = {
        symbol: canonical_ids[0]
        for symbol, canonical_ids in by_symbol.items()
        if len(canonical_ids) == 1
    }
    return {
        "unique": unique,
        "collisions": collisions,
        "row_count": row_count,
    }


def _map_instruments_to_canonical(
    rows: Sequence[Mapping[str, Any]],
    *,
    registry: Mapping[str, Any],
    frozen_at: datetime,
    is_gate: bool,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    unique = registry["unique"]
    collisions = registry["collisions"]
    mapped: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    for raw in rows:
        base = str(raw["base_currency"])
        if base in collisions:
            exclusions["symbol_collision"] += 1
            continue
        canonical_id = unique.get(base)
        if canonical_id is None:
            exclusions["unmatched_symbol"] += 1
            continue
        available_since = _parse_lifecycle_timestamp(
            raw["available_since"],
            label=f"{raw['exchange']}.{raw['instrument_id']}.available_since",
        )
        if available_since > frozen_at:
            exclusions["listed_after_plan_freeze"] += 1
            continue
        available_to = (
            _parse_lifecycle_timestamp(
                raw["available_to"],
                label=f"{raw['exchange']}.{raw['instrument_id']}.available_to",
            )
            if raw.get("available_to")
            else None
        )
        if is_gate:
            coverage_end = min(available_to or frozen_at, frozen_at)
            if coverage_end - available_since < timedelta(days=HISTORY_DAYS):
                exclusions["gate_lifecycle_span_below_220_days"] += 1
                continue
        mapped.append({**dict(raw), "canonical_asset_id": canonical_id})

    if is_gate:
        by_canonical: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in mapped:
            by_canonical[str(row["canonical_asset_id"])].append(row)
        ambiguous = {
            canonical_id
            for canonical_id, members in by_canonical.items()
            if len(members) > 1
        }
        if ambiguous:
            mapped = [
                row for row in mapped if row["canonical_asset_id"] not in ambiguous
            ]
            exclusions["duplicate_gate_canonical_asset"] += sum(
                len(by_canonical[canonical_id]) for canonical_id in ambiguous
            )
    mapped.sort(
        key=lambda row: (
            str(row["canonical_asset_id"]),
            str(row["instrument_id"]),
        )
    )
    return mapped, exclusions


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return "".join(f"{_canonical_json(row)}\n" for row in rows).encode("utf-8")


def _write_bytes_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _identity_result_hash(result: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in result.items()
            if key not in {"generated_at_utc", "elapsed_sec", "artifact_hash"}
        }
    )


def collect_gate_momentum_identity_metadata(
    plan_path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    session: Any | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan = validate_gate_momentum_identity_plan(plan_path)
    result_path = Path(plan["outputs"]["identity_result_json_path"]).resolve()
    if result_path.exists():
        return validate_gate_momentum_identity_result(
            result_path,
            plan_path=plan_path,
        )

    environment = os.environ if environ is None else environ
    credential = str(environment.get(DEFAULT_CREDENTIAL_ENV) or "").strip()
    if not credential:
        raise IdentityCredentialError(
            f"{DEFAULT_CREDENTIAL_ENV} is required for Tardis Instruments Metadata API"
        )

    started = time.monotonic()
    deadline = started + int(plan["limits"]["max_runtime_sec"])
    http = session if session is not None else requests.Session()
    owns_session = session is None
    network_requests = 0
    raw_by_exchange: dict[str, list[Any]] = {}
    response_summaries: list[dict[str, Any]] = []
    reason_codes: list[str] = []
    failure: dict[str, Any] | None = None
    try:
        for request_contract in plan["requests"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("identity metadata collect exceeded max_runtime_sec")
            exchange = str(request_contract["exchange"])
            network_requests += 1
            with http.get(
                str(request_contract["url"]),
                params={"filter": _canonical_json(request_contract["filter"])},
                headers={
                    "Accept": "application/json",
                    "User-Agent": "trading_mvp-research/1.0",
                    "Authorization": f"Bearer {credential}",
                },
                timeout=(min(10.0, remaining), min(30.0, remaining)),
                stream=True,
            ) as response:
                response.raise_for_status()
                payload, body = _bounded_json_array(
                    response,
                    max_bytes=int(
                        plan["limits"]["max_response_bytes_per_exchange"]
                    ),
                    exchange=exchange,
                )
            raw_by_exchange[exchange] = payload
            response_summaries.append(
                {
                    "exchange": exchange,
                    "row_count": len(payload),
                    "response_bytes": len(body),
                    "response_sha256": hashlib.sha256(body).hexdigest(),
                }
            )
    except IdentitySchemaError as exc:
        reason_codes.append(exc.reason_code)
        failure = {"type": type(exc).__name__, "message": str(exc)}
    except TimeoutError as exc:
        reason_codes.append("IDENTITY_METADATA_RUNTIME_EXCEEDED")
        failure = {"type": type(exc).__name__, "message": str(exc)}
    except Exception as exc:
        reason_codes.append("IDENTITY_METADATA_NETWORK_OR_TRANSPORT_FAILURE")
        failure = {
            "type": type(exc).__name__,
            "message": f"identity metadata request failed: {type(exc).__name__}",
        }
    finally:
        if owns_session:
            http.close()

    gate_rows: list[dict[str, Any]] = []
    binance_rows: list[dict[str, Any]] = []
    gate_exclusions: Counter[str] = Counter()
    binance_exclusions: Counter[str] = Counter()
    gate_content: bytes | None = None
    binance_content: bytes | None = None
    if not reason_codes:
        try:
            gate_raw = raw_by_exchange.get("gate-io-futures")
            binance_raw = raw_by_exchange.get("binance")
            if gate_raw is None or binance_raw is None or network_requests != 2:
                raise IdentitySchemaError(
                    "IDENTITY_METADATA_INCOMPLETE",
                    "identity metadata responses are incomplete",
                )
            gate_normalized = _normalize_instrument_rows(
                gate_raw,
                request_contract=plan["requests"][0],
            )
            binance_normalized = _normalize_instrument_rows(
                binance_raw,
                request_contract=plan["requests"][1],
            )
            registry = _load_unique_registry_symbols(plan)
            frozen_at = _parse_lifecycle_timestamp(
                plan["frozen_at_utc"],
                label="identity_plan.frozen_at_utc",
            )
            gate_rows, gate_exclusions = _map_instruments_to_canonical(
                gate_normalized,
                registry=registry,
                frozen_at=frozen_at,
                is_gate=True,
            )
            binance_rows, binance_exclusions = _map_instruments_to_canonical(
                binance_normalized,
                registry=registry,
                frozen_at=frozen_at,
                is_gate=False,
            )
            gate_content = _jsonl_bytes(gate_rows)
            binance_content = _jsonl_bytes(binance_rows)
        except IdentitySchemaError as exc:
            reason_codes.append(exc.reason_code)
            failure = {"type": type(exc).__name__, "message": str(exc)}
        except Exception as exc:
            reason_codes.append("IDENTITY_MAPPING_FAILURE")
            failure = {
                "type": type(exc).__name__,
                "message": f"identity mapping failed: {type(exc).__name__}",
            }

    unique_gate_assets = len(
        {str(row["canonical_asset_id"]) for row in gate_rows}
    )
    unique_binance_assets = len(
        {str(row["canonical_asset_id"]) for row in binance_rows}
    )
    if reason_codes:
        verdict = "REJECTED_IDENTITY_SCHEMA"
        accepted = False
        next_command = "none_fix_source_or_code_then_new_hash_bound_identity_plan"
    elif unique_gate_assets < MINIMUM_CANONICAL_ASSETS:
        reason_codes.append(
            f"CANONICAL_GATE_ASSET_COUNT_BELOW_{MINIMUM_CANONICAL_ASSETS}"
        )
        verdict = "INSUFFICIENT_CANONICAL_IDENTITY_UNIVERSE"
        accepted = False
        next_command = "none_identity_universe_insufficient"
    else:
        verdict = "IDENTITY_ACCEPTED_READY_FOR_HISTORY_PLANONLY"
        accepted = True
        next_command = "gate-momentum-history-planonly"

    gate_output = Path(plan["outputs"]["gate_instruments_jsonl_path"]).resolve()
    binance_output = Path(
        plan["outputs"]["binance_instruments_jsonl_path"]
    ).resolve()
    gate_sha: str | None = None
    binance_sha: str | None = None
    if gate_content is not None and binance_content is not None:
        _write_bytes_immutable(gate_output, gate_content)
        _write_bytes_immutable(binance_output, binance_content)
        gate_sha = hashlib.sha256(gate_content).hexdigest()
        binance_sha = hashlib.sha256(binance_content).hexdigest()

    elapsed = time.monotonic() - started
    result: dict[str, Any] = {
        "schema": IDENTITY_RESULT_SCHEMA,
        "final": True,
        "partial_accept": False,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "elapsed_sec": round(elapsed, 6),
        "plan_path": str(Path(plan_path).expanduser().resolve()),
        "plan_hash": plan["plan_hash"],
        "verdict": verdict,
        "reason_codes": reason_codes,
        "accepted_for_history_planonly": accepted,
        "history_collect_allowed": False,
        "network_requests": network_requests,
        "credential_environment_variable": DEFAULT_CREDENTIAL_ENV,
        "authorization_header_sent": network_requests > 0,
        "credential_value_persisted": False,
        "response_summaries": response_summaries,
        "canonical_gate_asset_count": unique_gate_assets,
        "canonical_binance_asset_count": unique_binance_assets,
        "gate_instrument_row_count": len(gate_rows),
        "binance_instrument_row_count": len(binance_rows),
        "gate_exclusion_counts": dict(sorted(gate_exclusions.items())),
        "binance_exclusion_counts": dict(sorted(binance_exclusions.items())),
        "gate_instruments_jsonl_path": (
            str(gate_output) if gate_content is not None else None
        ),
        "gate_instruments_sha256": gate_sha,
        "binance_instruments_jsonl_path": (
            str(binance_output) if binance_content is not None else None
        ),
        "binance_instruments_sha256": binance_sha,
        "registry_sha256": plan["inputs"]["canonical_registry_result"][
            "registry_sha256"
        ],
        "failure": failure,
        "data_access_audit": {
            "instrument_metadata_read": network_requests > 0,
            "market_rows_read": False,
            "market_values_read": False,
            "returns_read": False,
            "signals_computed": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "safety": {
            **_safety_contract(),
            "metadata_only": True,
        },
        "next_allowed_command": next_command,
    }
    result["artifact_hash"] = _identity_result_hash(result)
    _write_json_immutable(result_path, result)
    return result


def validate_gate_momentum_identity_result(
    result_path: str | Path,
    *,
    plan_path: str | Path,
) -> dict[str, Any]:
    plan = validate_gate_momentum_identity_plan(plan_path)
    expected_result_path = Path(plan["outputs"]["identity_result_json_path"]).resolve()
    observed_result_path = Path(result_path).expanduser().resolve()
    if observed_result_path != expected_result_path:
        raise ValueError("identity result path mismatch")
    result = _read_json_object(observed_result_path)
    if (
        result.get("schema") != IDENTITY_RESULT_SCHEMA
        or result.get("final") is not True
        or result.get("partial_accept") is not False
    ):
        raise ValueError("identity result is not final")
    if result.get("plan_path") != str(Path(plan_path).expanduser().resolve()):
        raise ValueError("identity result plan path mismatch")
    if result.get("plan_hash") != plan["plan_hash"]:
        raise ValueError("identity result plan hash mismatch")
    observed_hash = _validate_hash(
        result.get("artifact_hash"),
        label="identity result artifact hash",
    )
    if _identity_result_hash(result) != observed_hash:
        raise ValueError("identity result artifact hash mismatch")
    if result.get("credential_environment_variable") != DEFAULT_CREDENTIAL_ENV:
        raise ValueError("identity result credential environment mismatch")
    if result.get("credential_value_persisted") is not False:
        raise ValueError("identity result persisted credential material")
    if result.get("history_collect_allowed") is not False:
        raise ValueError("identity result cannot directly authorize history collect")
    if result.get("registry_sha256") != plan["inputs"][
        "canonical_registry_result"
    ]["registry_sha256"]:
        raise ValueError("identity result registry hash mismatch")

    audit = result.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("identity result data-access audit is missing")
    for key in (
        "market_rows_read",
        "market_values_read",
        "returns_read",
        "signals_computed",
        "pnl_read",
        "oos_read",
    ):
        if audit.get(key) is not False:
            raise ValueError(f"identity result unexpectedly accessed {key}")
    safety = result.get("safety")
    if not isinstance(safety, Mapping) or safety != _safety_contract():
        raise ValueError("identity result safety contract mismatch")

    verdict = str(result.get("verdict") or "")
    accepted = result.get("accepted_for_history_planonly")
    if verdict == "IDENTITY_ACCEPTED_READY_FOR_HISTORY_PLANONLY":
        if accepted is not True or list(result.get("reason_codes") or ()):
            raise ValueError("accepted identity result has inconsistent verdict")
        if int(result.get("canonical_gate_asset_count") or 0) < MINIMUM_CANONICAL_ASSETS:
            raise ValueError("accepted identity result has insufficient Gate assets")
        if result.get("next_allowed_command") != "gate-momentum-history-planonly":
            raise ValueError("accepted identity result next command mismatch")
    elif verdict == "INSUFFICIENT_CANONICAL_IDENTITY_UNIVERSE":
        if accepted is not False or not list(result.get("reason_codes") or ()):
            raise ValueError("insufficient identity result has inconsistent verdict")
    elif verdict == "REJECTED_IDENTITY_SCHEMA":
        if accepted is not False or not list(result.get("reason_codes") or ()):
            raise ValueError("rejected identity result has inconsistent verdict")
        return result
    else:
        raise ValueError("unsupported identity result verdict")

    for path_key, hash_key, expected_path_key in (
        (
            "gate_instruments_jsonl_path",
            "gate_instruments_sha256",
            "gate_instruments_jsonl_path",
        ),
        (
            "binance_instruments_jsonl_path",
            "binance_instruments_sha256",
            "binance_instruments_jsonl_path",
        ),
    ):
        output_path = Path(str(result.get(path_key) or "")).resolve()
        expected_path = Path(str(plan["outputs"][expected_path_key])).resolve()
        if output_path != expected_path or not output_path.is_file():
            raise ValueError(f"identity result output path mismatch: {path_key}")
        if sha256_file(output_path) != result.get(hash_key):
            raise ValueError(f"identity result output hash mismatch: {hash_key}")
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze and validate Gate/Binance point-in-time identity metadata PlanOnly."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--momentum-plan", required=True)
    plan_parser.add_argument("--public-descriptor", required=True)
    plan_parser.add_argument("--public-result", required=True)
    plan_parser.add_argument("--registry-plan", required=True)
    plan_parser.add_argument("--registry-manifest", required=True)
    plan_parser.add_argument("--gate-instruments-output", required=True)
    plan_parser.add_argument("--binance-instruments-output", required=True)
    plan_parser.add_argument("--identity-result-output", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--frozen-at-utc")
    plan_parser.add_argument(
        "--max-runtime-sec",
        type=int,
        default=DEFAULT_IDENTITY_RUNTIME_SEC,
    )

    validate_parser = subparsers.add_parser("validate-plan")
    validate_parser.add_argument("--plan", required=True)

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--plan", required=True)

    validate_result_parser = subparsers.add_parser("validate-result")
    validate_result_parser.add_argument("--plan", required=True)
    validate_result_parser.add_argument("--result", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "plan":
        plan = build_gate_momentum_identity_plan(
            args.momentum_plan,
            args.public_descriptor,
            args.public_result,
            args.registry_plan,
            args.registry_manifest,
            gate_instruments_output_path=args.gate_instruments_output,
            binance_instruments_output_path=args.binance_instruments_output,
            identity_result_output_path=args.identity_result_output,
            frozen_at_utc=args.frozen_at_utc,
            max_runtime_sec=args.max_runtime_sec,
        )
        _write_json_immutable(args.output, plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "validate-plan":
        plan = validate_gate_momentum_identity_plan(args.plan)
        print(
            json.dumps(
                {
                    "decision": "IDENTITY_PLAN_VALID",
                    "plan_hash": plan["plan_hash"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "collect":
        result = collect_gate_momentum_identity_metadata(args.plan)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "validate-result":
        result = validate_gate_momentum_identity_result(
            args.result,
            plan_path=args.plan,
        )
        print(
            json.dumps(
                {
                    "decision": "IDENTITY_RESULT_VALID",
                    "artifact_hash": result["artifact_hash"],
                    "verdict": result["verdict"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
