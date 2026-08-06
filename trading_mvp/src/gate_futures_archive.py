from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import zlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

try:
    from costs import validate_runtime_sec
except ImportError:  # pragma: no cover - package import fallback
    from .costs import validate_runtime_sec


ARCHIVE_PLAN_SCHEMA = "trading_mvp_gate_futures_tardis_archive_source_plan_v1"
SCHEMA_PROBE_SCHEMA = "trading_mvp_gate_futures_tardis_schema_probe_plan_v1"
ACTIONABILITY_SCHEMA = "trading_mvp_gate_futures_archive_actionability_v1"
SOURCE_ROUTE_SCHEMA = "trading_mvp_historical_archive_route_planonly_v1"
SOURCE_ROUTE_STATUS = "EXTERNAL_SOURCE_PREPARED_AWAIT_ACCESS"
RECOVERY_PREFLIGHT_SCHEMA = "trading_mvp_gate_archive_recovery_preflight_v1"
FROZEN_BASIS_HYPOTHESIS_ID = "cross_venue_perp_basis_convergence_history_v1"
EXCHANGE_ID = "gate-io-futures"
PROVIDER_NAME = "Tardis.dev"
API_BASE_URL = "https://api.tardis.dev/v1"
DATASETS_BASE_URL = "https://datasets.tardis.dev/v1"
EXCHANGE_METADATA_URL = f"{API_BASE_URL}/exchanges/{EXCHANGE_ID}"
DEFAULT_CREDENTIAL_ENV = "TARDIS_API_KEY"
MAX_SCHEMA_PROBE_RUNTIME_SEC = 300
MAX_HEADER_BYTES = 16_384
MAX_HEADER_DOWNLOAD_BYTES = 1_048_576
DATASET_TYPES = ("trades", "derivative_ticker")
REQUIRED_COLUMNS = {
    "trades": (
        "exchange",
        "symbol",
        "timestamp",
        "local_timestamp",
        "id",
        "side",
        "price",
        "amount",
    ),
    "derivative_ticker": (
        "exchange",
        "symbol",
        "timestamp",
        "local_timestamp",
        "funding_timestamp",
        "funding_rate",
        "predicted_funding_rate",
        "open_interest",
        "last_price",
        "index_price",
        "mark_price",
    ),
}

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+_[A-Z0-9]+$")
_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ArchiveEntitlementError(RuntimeError):
    """Raised before network access when archive entitlement is unavailable."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {source}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {source}")
    return value


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def _parse_dataset_date(value: str | date) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"invalid dataset date: {value!r}")
    if isinstance(value, date):
        return value
    normalized = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        raise ValueError(f"invalid dataset date: {value!r}")
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid dataset date: {value!r}") from exc


def _validate_dataset_type(value: str) -> str:
    normalized = str(value).strip()
    if normalized not in DATASET_TYPES:
        raise ValueError(f"unsupported dataset type: {normalized}")
    return normalized


def _validate_symbol(value: str) -> str:
    normalized = str(value).strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid Gate futures symbol: {value!r}")
    return normalized


def _validate_credential_env(value: str) -> str:
    normalized = str(value).strip()
    if not _ENV_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid credential environment variable: {value!r}")
    return normalized


def _validate_schema_probe_runtime(value: int | float) -> int:
    runtime = validate_runtime_sec(value, name="schema_probe_max_runtime_sec")
    if runtime > MAX_SCHEMA_PROBE_RUNTIME_SEC:
        raise ValueError(
            f"schema_probe_max_runtime_sec must be <= {MAX_SCHEMA_PROBE_RUNTIME_SEC}"
        )
    return runtime


def build_dataset_url(
    data_type: str,
    dataset_date: str | date,
    symbol: str,
) -> str:
    normalized_type = _validate_dataset_type(data_type)
    normalized_date = _parse_dataset_date(dataset_date)
    normalized_symbol = _validate_symbol(symbol)
    return (
        f"{DATASETS_BASE_URL}/{EXCHANGE_ID}/{normalized_type}/"
        f"{normalized_date:%Y/%m/%d}/{normalized_symbol}.csv.gz"
    )


def validate_dataset_header(data_type: str, header: str | Sequence[str]) -> list[str]:
    normalized_type = _validate_dataset_type(data_type)
    if isinstance(header, str):
        try:
            rows = list(csv.reader([header.strip()]))
        except csv.Error as exc:
            raise ValueError("invalid CSV header") from exc
        columns = [value.strip() for value in rows[0]] if rows else []
    else:
        columns = [str(value).strip() for value in header]
    if not columns or any(not value for value in columns):
        raise ValueError("CSV header contains empty columns")
    if len(columns) != len(set(columns)):
        raise ValueError("CSV header contains duplicate columns")
    missing = [name for name in REQUIRED_COLUMNS[normalized_type] if name not in columns]
    if missing:
        raise ValueError(
            f"{normalized_type} missing required columns: {', '.join(missing)}"
        )
    return columns


def _route_semantic_hash(route: Mapping[str, Any]) -> str:
    return sha256_json({key: value for key, value in route.items() if key != "plan_hash"})


def _validate_source_route(
    route: Mapping[str, Any],
    *,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    observed_hash = str(route.get("plan_hash") or "").lower()
    if not _HASH_PATTERN.fullmatch(observed_hash) or _route_semantic_hash(route) != observed_hash:
        raise ValueError("source route hash mismatch")
    if expected_plan_hash and observed_hash != str(expected_plan_hash).lower():
        raise ValueError("source route plan hash differs from archive contract")
    if route.get("schema") != SOURCE_ROUTE_SCHEMA:
        raise ValueError("unexpected source route schema")
    if route.get("mode") != "PlanOnly" or route.get("research_only") is not True:
        raise ValueError("source route is not research-only PlanOnly")
    if route.get("status") != SOURCE_ROUTE_STATUS:
        raise ValueError("source route is not awaiting archive access")

    facts = route.get("immutable_facts")
    candidate = (
        facts.get("gate_futures_external_archive_candidate")
        if isinstance(facts, Mapping)
        else None
    )
    if not isinstance(candidate, Mapping):
        raise ValueError("source route archive candidate is missing")
    if candidate.get("provider") != PROVIDER_NAME or candidate.get("exchange") != EXCHANGE_ID:
        raise ValueError("source route archive provider mismatch")
    documented = set(candidate.get("documented_data_types") or ())
    if not set(DATASET_TYPES).issubset(documented):
        raise ValueError("source route lacks required archive dataset types")

    audit = route.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(value is not False for value in audit.values()):
        raise ValueError("source route data embargo mismatch")
    prohibited = set(route.get("prohibited") or ())
    for required in ("retune", "grid_search", "oos", "live_orders", "private_api_keys"):
        if required not in prohibited:
            raise ValueError(f"source route does not prohibit {required}")
    return dict(route)


def _sealed_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    source_route = plan.get("source_route")
    route_reference = (
        {
            "schema": source_route.get("schema"),
            "plan_hash": source_route.get("plan_hash"),
        }
        if isinstance(source_route, Mapping)
        else None
    )
    return {
        "source_route": route_reference,
        "contract": plan.get("contract"),
        "provider": plan.get("provider"),
        "schema_probe": plan.get("schema_probe"),
        "quality_contract": plan.get("quality_contract"),
        "evaluation_boundary": plan.get("evaluation_boundary"),
        "runtime": plan.get("runtime"),
        "safety": plan.get("safety"),
        "code_provenance": plan.get("code_provenance"),
    }


def build_archive_source_plan(
    source_route_path: str | Path,
    output_path: str | Path | None = None,
    *,
    frozen_at_utc: str | None = None,
    credential_env: str = DEFAULT_CREDENTIAL_ENV,
    max_runtime_sec: int = MAX_SCHEMA_PROBE_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = _validate_schema_probe_runtime(max_runtime_sec)
    env_name = _validate_credential_env(credential_env)
    route_path = Path(source_route_path).expanduser().resolve()
    route = _validate_source_route(_read_json(route_path))
    module_path = Path(__file__).resolve()
    plan: dict[str, Any] = {
        "schema": ARCHIVE_PLAN_SCHEMA,
        "mode": "PlanOnly",
        "status": "ARCHIVE_SOURCE_CONTRACT_FROZEN_AWAITING_SCHEMA_PROBE",
        "generated_at_utc": frozen_at_utc or datetime.now(timezone.utc).isoformat(),
        "source_route": {
            "schema": route["schema"],
            "plan_hash": route["plan_hash"],
            "path": str(route_path),
            "file_sha256": sha256_file(route_path),
        },
        "contract": {
            "id": "gate_futures_tardis_archive_source_contract_v1",
            "purpose": "source_qualification_only",
            "strategy_frozen": False,
            "strategy_evaluation_allowed": False,
            "closed_branch_reopened": False,
            "market_values_embargoed_until_contract_frozen": True,
        },
        "provider": {
            "name": PROVIDER_NAME,
            "exchange_id": EXCHANGE_ID,
            "metadata_url": EXCHANGE_METADATA_URL,
            "datasets_base_url": DATASETS_BASE_URL,
            "documented_available_since": "2020-07-01",
            "dataset_types": list(DATASET_TYPES),
            "required_columns": {
                key: list(value) for key, value in REQUIRED_COLUMNS.items()
            },
            "credential": {
                "source": "environment_only",
                "environment_variable": env_name,
                "secret_persisted": False,
                "secret_logged": False,
            },
        },
        "schema_probe": {
            "control_symbol": "BTC_USDT",
            "documented_no_key_sample_rule": "first_calendar_day_of_month_only",
            "metadata_required": True,
            "dataset_header_only": True,
            "maximum_dataset_files": len(DATASET_TYPES),
            "market_values_read": False,
            "symbol_identity_evaluated": False,
            "edge_evaluated": False,
        },
        "quality_contract": {
            "fail_closed": True,
            "required_exchange_id": EXCHANGE_ID,
            "supports_datasets_required": True,
            "required_dataset_types": list(DATASET_TYPES),
            "required_mark_index_funding_columns": [
                "mark_price",
                "index_price",
                "funding_timestamp",
                "funding_rate",
            ],
            "gzip_integrity_required_for_future_collect": True,
            "canonical_identity_required_before_history_collect": True,
            "archive_values_may_not_select_strategy_parameters": True,
        },
        "evaluation_boundary": {
            "current_stage": "source_schema_only",
            "quality_evaluation_allowed_after_schema_accept": True,
            "strategy_evaluation_allowed": False,
            "oos_allowed": False,
            "next_hypothesis_must_be_materially_new_and_hash_bound": True,
            "automatic_transition": False,
        },
        "runtime": {
            "schema_probe_max_runtime_sec": runtime,
            "quality_max_runtime_sec": 1_800,
            "future_history_collect_hard_cap_sec": 7_200,
        },
        "safety": {
            "research_only": True,
            "strategy_evaluation": False,
            "materially_new_hypothesis_required": True,
            "grid_search": False,
            "retune": False,
            "oos": False,
            "execution_probe": False,
            "paper_forward": False,
            "live_orders": False,
            "private_exchange_api_keys": False,
            "leverage_or_margin": False,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
        },
        "data_access_audit": {
            "network_access": False,
            "provider_account_accessed": False,
            "market_rows_read": False,
            "returns_read": False,
            "pnl_read": False,
            "signals_computed": False,
        },
        "next_allowed_command": "gate_futures_archive_binding_audit",
        "output_path": (
            str(Path(output_path).expanduser().resolve()) if output_path is not None else None
        ),
    }
    plan["plan_hash"] = sha256_json(_sealed_plan(plan))
    if output_path is not None:
        _write_json_immutable(output_path, plan)
    return plan


def validate_archive_source_plan(
    plan: Mapping[str, Any],
    *,
    expected_plan_hash: str | None = None,
    source_route_path: str | Path | None = None,
) -> dict[str, Any]:
    if plan.get("schema") != ARCHIVE_PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError("unexpected archive source plan")
    observed_hash = str(plan.get("plan_hash") or "").lower()
    if not _HASH_PATTERN.fullmatch(observed_hash) or sha256_json(_sealed_plan(plan)) != observed_hash:
        raise ValueError("plan hash mismatch")
    if expected_plan_hash and observed_hash != str(expected_plan_hash).lower():
        raise ValueError("plan hash differs from expected")

    runtime = plan.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("archive source runtime is missing")
    _validate_schema_probe_runtime(runtime.get("schema_probe_max_runtime_sec"))

    provider = plan.get("provider")
    if not isinstance(provider, Mapping):
        raise ValueError("archive provider is missing")
    if provider.get("name") != PROVIDER_NAME or provider.get("exchange_id") != EXCHANGE_ID:
        raise ValueError("archive provider mismatch")
    if tuple(provider.get("dataset_types") or ()) != DATASET_TYPES:
        raise ValueError("archive dataset contract mismatch")
    credential = provider.get("credential")
    if not isinstance(credential, Mapping):
        raise ValueError("archive credential reference is missing")
    _validate_credential_env(str(credential.get("environment_variable") or ""))
    if credential.get("source") != "environment_only":
        raise ValueError("archive credential must be environment-only")
    if credential.get("secret_persisted") is not False or credential.get("secret_logged") is not False:
        raise ValueError("archive credential safety mismatch")

    safety = plan.get("safety")
    if not isinstance(safety, Mapping) or safety.get("research_only") is not True:
        raise ValueError("archive plan is not research-only")
    for key in (
        "strategy_evaluation",
        "grid_search",
        "retune",
        "oos",
        "execution_probe",
        "paper_forward",
        "live_orders",
        "private_exchange_api_keys",
        "leverage_or_margin",
    ):
        if safety.get(key) is not False:
            raise ValueError(f"archive plan safety mismatch: {key}")
    if safety.get("materially_new_hypothesis_required") is not True:
        raise ValueError("archive plan may reopen a closed branch")

    source = plan.get("source_route")
    if not isinstance(source, Mapping):
        raise ValueError("archive source route reference is missing")
    if source_route_path is not None:
        route_path = Path(source_route_path).expanduser().resolve()
        route = _validate_source_route(
            _read_json(route_path),
            expected_plan_hash=str(source.get("plan_hash") or ""),
        )
        if sha256_file(route_path) != source.get("file_sha256"):
            raise ValueError("source route file hash mismatch")
        if route.get("schema") != source.get("schema"):
            raise ValueError("source route schema mismatch")
    return {"plan_hash": observed_hash, "schema": ARCHIVE_PLAN_SCHEMA}


def build_schema_probe_descriptor(
    plan: Mapping[str, Any],
    *,
    symbol: str,
    sample_date: str | date,
    max_runtime_sec: int,
) -> dict[str, Any]:
    validation = validate_archive_source_plan(plan)
    runtime = _validate_schema_probe_runtime(max_runtime_sec)
    plan_runtime = int(plan["runtime"]["schema_probe_max_runtime_sec"])
    if runtime > plan_runtime:
        raise ValueError(
            f"schema_probe_max_runtime_sec must be <= frozen limit {plan_runtime}"
        )
    normalized_symbol = _validate_symbol(symbol)
    normalized_date = _parse_dataset_date(sample_date)
    requests_plan = [
        {
            "kind": "exchange_metadata",
            "url": EXCHANGE_METADATA_URL,
            "value_access": "schema_and_availability_only",
        }
    ]
    requests_plan.extend(
        {
            "kind": "dataset_header",
            "data_type": data_type,
            "url": build_dataset_url(data_type, normalized_date, normalized_symbol),
            "value_access": "csv_header_only",
        }
        for data_type in DATASET_TYPES
    )
    descriptor: dict[str, Any] = {
        "schema": SCHEMA_PROBE_SCHEMA,
        "mode": "PlanOnly",
        "archive_plan_hash": validation["plan_hash"],
        "exchange_id": EXCHANGE_ID,
        "symbol": normalized_symbol,
        "sample_date": normalized_date.isoformat(),
        "sample_only_without_entitlement": normalized_date.day == 1,
        "request_count": len(requests_plan),
        "requests": requests_plan,
        "credential_reference": {
            "source": "environment_only",
            "environment_variable": plan["provider"]["credential"]["environment_variable"],
            "secret_persisted": False,
        },
        "runtime": {"max_runtime_sec": runtime},
        "data_access_audit": {
            "network_access": False,
            "market_values_read": False,
            "returns_read": False,
            "pnl_computed": False,
        },
        "safety": {
            "schema_only": True,
            "strategy_evaluation": False,
            "oos": False,
            "grid_search": False,
            "live_orders": False,
        },
        "next_allowed_command": "run_visible_schema_probe_after_access_check",
    }
    descriptor["descriptor_hash"] = sha256_json(descriptor)
    return descriptor


def _validate_recovery_preflight(
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    observed_hash = str(preflight.get("artifact_hash") or "").lower()
    semantic = {
        key: value
        for key, value in preflight.items()
        if key not in {"generated_at_utc", "artifact_hash"}
    }
    if not _HASH_PATTERN.fullmatch(observed_hash) or sha256_json(semantic) != observed_hash:
        raise ValueError("recovery preflight hash mismatch")
    if (
        preflight.get("schema") != RECOVERY_PREFLIGHT_SCHEMA
        or preflight.get("final") is not True
        or preflight.get("hypothesis_id") != FROZEN_BASIS_HYPOTHESIS_ID
    ):
        raise ValueError("unexpected recovery preflight")
    if int(preflight.get("network_requests") or 0) != 0:
        raise ValueError("recovery preflight performed network requests")
    if preflight.get("archive_collect_allowed") is not False:
        raise ValueError("recovery preflight archive boundary mismatch")

    audit = preflight.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(value is not False for value in audit.values()):
        raise ValueError("recovery preflight data embargo mismatch")
    safety = preflight.get("safety")
    if not isinstance(safety, Mapping) or safety.get("research_only") is not True:
        raise ValueError("recovery preflight is not research-only")
    for key in ("grid_search", "retune", "live_orders", "leverage_or_margin"):
        if safety.get(key) is not False:
            raise ValueError(f"recovery preflight safety mismatch: {key}")

    minimum = int(preflight.get("minimum_required_assets") or 0)
    survivors = int(preflight.get("mexc_history_upper_bound_assets") or 0)
    if minimum < 1 or survivors < 0:
        raise ValueError("invalid recovery preflight universe counts")
    verdict = str(preflight.get("verdict") or "")
    if survivors < minimum:
        if (
            verdict != "INSUFFICIENT_EXECUTABLE_UNIVERSE"
            or preflight.get("reason_code")
            != "MEXC_HISTORY_UPPER_BOUND_LT_MINIMUM_BEFORE_GATE_ARCHIVE"
            or preflight.get("next_allowed_command") != "none_archive_collect_forbidden"
        ):
            raise ValueError("inconsistent insufficient-universe recovery verdict")
    elif (
        verdict != "ARCHIVE_SOURCE_AMENDMENT_PLANONLY_REQUIRED"
        or preflight.get("reason_code")
        != "GATE_ARCHIVE_CAN_BE_PROBED_WITHOUT_CHANGING_FROZEN_STRATEGY"
    ):
        raise ValueError("inconsistent archive-amendment recovery verdict")
    return dict(preflight)


def assess_archive_actionability(
    archive_plan: Mapping[str, Any],
    recovery_preflight_path: str | Path,
    output_path: str | Path | None = None,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan_validation = validate_archive_source_plan(archive_plan)
    preflight_path = Path(recovery_preflight_path).expanduser().resolve()
    preflight = _validate_recovery_preflight(_read_json(preflight_path))
    minimum = int(preflight["minimum_required_assets"])
    survivors = int(preflight["mexc_history_upper_bound_assets"])
    actionable = survivors >= minimum
    if actionable:
        verdict = "ARCHIVE_SCHEMA_PROBE_PERMITTED_FOR_FROZEN_BASIS"
        reason = "MEXC_HISTORY_UPPER_BOUND_MEETS_FROZEN_MINIMUM"
        next_command = "visible_gate_futures_archive_schema_probe"
    else:
        verdict = "ARCHIVE_NOT_ACTIONABLE_FOR_FROZEN_BASIS"
        reason = "GATE_ARCHIVE_CANNOT_REPAIR_MEXC_HISTORY_UPPER_BOUND_LT_MINIMUM"
        next_command = "none_frozen_basis_branch_remains_closed"

    result: dict[str, Any] = {
        "schema": ACTIONABILITY_SCHEMA,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "final": True,
        "hypothesis_id": FROZEN_BASIS_HYPOTHESIS_ID,
        "archive_plan_hash": plan_validation["plan_hash"],
        "recovery_preflight": {
            "path": str(preflight_path),
            "file_sha256": sha256_file(preflight_path),
            "artifact_hash": preflight["artifact_hash"],
            "verdict": preflight["verdict"],
        },
        "verdict": verdict,
        "reason_code": reason,
        "minimum_required_assets": minimum,
        "mexc_history_upper_bound_assets": survivors,
        "archive_schema_probe_allowed_for_frozen_basis": actionable,
        "edge_evaluated": False,
        "network_requests": 0,
        "data_access_audit": {
            "market_rows_read": False,
            "returns_read": False,
            "oos_read": False,
            "signals_read": False,
            "pnl_computed": False,
        },
        "safety": {
            "research_only": True,
            "grid_search": False,
            "retune": False,
            "oos": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
        "next_allowed_command": next_command,
        "output_path": (
            str(Path(output_path).expanduser().resolve()) if output_path is not None else None
        ),
    }
    result["artifact_hash"] = sha256_json(
        {
            key: value
            for key, value in result.items()
            if key not in {"generated_at_utc", "artifact_hash", "output_path"}
        }
    )
    if output_path is not None:
        _write_json_immutable(output_path, result)
    return result


class GateFuturesArchiveClient:
    """Bounded HTTP adapter that resolves entitlement only at request time."""

    def __init__(
        self,
        *,
        session: Any | None = None,
        environ: Mapping[str, str] | None = None,
        credential_env: str = DEFAULT_CREDENTIAL_ENV,
        timeout_sec: int = 15,
    ) -> None:
        timeout = int(timeout_sec)
        if timeout <= 0 or timeout > 60:
            raise ValueError("timeout_sec must be in [1, 60]")
        self.session = session if session is not None else requests.Session()
        self._environ = os.environ if environ is None else environ
        self.credential_env = _validate_credential_env(credential_env)
        self.timeout_sec = timeout

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(exchange_id={EXCHANGE_ID!r}, "
            f"credential_env={self.credential_env!r}, authenticated={self.authenticated})"
        )

    @property
    def authenticated(self) -> bool:
        return bool(str(self._environ.get(self.credential_env) or "").strip())

    def _headers(self, *, require_entitlement: bool) -> dict[str, str]:
        secret = str(self._environ.get(self.credential_env) or "").strip()
        if not secret and require_entitlement:
            raise ArchiveEntitlementError(
                f"archive entitlement is unavailable; set {self.credential_env} "
                "in the local process environment"
            )
        return {"Authorization": f"Bearer {secret}"} if secret else {}

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "provider": PROVIDER_NAME,
            "exchange_id": EXCHANGE_ID,
            "credential_env": self.credential_env,
            "authenticated": self.authenticated,
            "secret_persisted": False,
            "secret_logged": False,
        }

    def fetch_exchange_metadata(self) -> dict[str, Any]:
        headers = self._headers(require_entitlement=False)
        try:
            response = self.session.get(
                EXCHANGE_METADATA_URL,
                headers=headers,
                timeout=self.timeout_sec,
            )
            with response:
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"archive metadata request failed for {EXCHANGE_ID}: {type(exc).__name__}"
            ) from None
        if not isinstance(payload, Mapping):
            raise ValueError("archive exchange metadata must be an object")
        if payload.get("id") != EXCHANGE_ID:
            raise ValueError("archive exchange metadata id mismatch")
        if payload.get("supportsDatasets") is not True:
            raise ValueError("archive exchange does not support datasets")
        return dict(payload)

    def fetch_dataset_header(
        self,
        data_type: str,
        dataset_date: str | date,
        symbol: str,
        *,
        require_entitlement: bool,
        max_download_bytes: int = MAX_HEADER_DOWNLOAD_BYTES,
        max_header_bytes: int = MAX_HEADER_BYTES,
    ) -> list[str]:
        if int(max_download_bytes) <= 0 or int(max_header_bytes) <= 0:
            raise ValueError("header probe byte limits must be positive")
        url = build_dataset_url(data_type, dataset_date, symbol)
        headers = self._headers(require_entitlement=require_entitlement)
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout_sec,
                stream=True,
            )
            with response:
                response.raise_for_status()
                header = _read_first_csv_line(
                    response,
                    max_download_bytes=int(max_download_bytes),
                    max_header_bytes=int(max_header_bytes),
                )
        except ArchiveEntitlementError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"archive dataset header request failed for {EXCHANGE_ID}/"
                f"{_validate_dataset_type(data_type)}: {type(exc).__name__}"
            ) from None
        return validate_dataset_header(data_type, header)


def _read_first_csv_line(
    response: Any,
    *,
    max_download_bytes: int,
    max_header_bytes: int,
) -> str:
    downloaded = 0
    output = bytearray()
    prefix = bytearray()
    decompressor: zlib.Decompress | None = None
    gzip_body: bool | None = None

    for raw_chunk in response.iter_content(chunk_size=8192):
        chunk = bytes(raw_chunk or b"")
        if not chunk:
            continue
        downloaded += len(chunk)
        if downloaded > max_download_bytes:
            raise ValueError("dataset header was not found within download byte limit")

        if gzip_body is None:
            prefix.extend(chunk)
            if len(prefix) < 2:
                continue
            gzip_body = prefix[:2] == b"\x1f\x8b"
            chunk = bytes(prefix)
            prefix.clear()
            if gzip_body:
                decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)

        if gzip_body:
            assert decompressor is not None
            remaining = max_header_bytes + 1 - len(output)
            decoded = decompressor.decompress(chunk, max(1, remaining))
        else:
            decoded = chunk
        output.extend(decoded)
        if b"\n" in output:
            break
        if len(output) > max_header_bytes:
            raise ValueError("dataset CSV header exceeds byte limit")

    if b"\n" not in output:
        raise ValueError("dataset CSV header is incomplete")
    first_line = bytes(output).split(b"\n", 1)[0].rstrip(b"\r")
    if len(first_line) > max_header_bytes:
        raise ValueError("dataset CSV header exceeds byte limit")
    try:
        return first_line.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("dataset CSV header is not UTF-8") from exc


def _load_plan(path: str | Path) -> dict[str, Any]:
    plan = _read_json(path)
    validate_archive_source_plan(plan)
    return plan


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PlanOnly contract for Gate Futures Tardis archive qualification"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--source-route", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--credential-env", default=DEFAULT_CREDENTIAL_ENV)
    plan.add_argument(
        "--max-runtime-sec",
        type=int,
        default=MAX_SCHEMA_PROBE_RUNTIME_SEC,
    )

    validate = subparsers.add_parser("validate-plan")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash")
    validate.add_argument("--source-route")

    descriptor = subparsers.add_parser("schema-probe-descriptor")
    descriptor.add_argument("--plan", required=True)
    descriptor.add_argument("--symbol", default="BTC_USDT")
    descriptor.add_argument("--sample-date", required=True)
    descriptor.add_argument("--max-runtime-sec", type=int, default=120)
    descriptor.add_argument("--output", required=True)

    audit = subparsers.add_parser("binding-audit")
    audit.add_argument("--plan", required=True)
    audit.add_argument("--recovery-preflight", required=True)
    audit.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan":
        result = build_archive_source_plan(
            args.source_route,
            args.output,
            credential_env=args.credential_env,
            max_runtime_sec=args.max_runtime_sec,
        )
        print(
            json.dumps(
                {
                    "schema": result["schema"],
                    "status": result["status"],
                    "plan_hash": result["plan_hash"],
                    "output": str(Path(args.output).expanduser().resolve()),
                    "next_allowed_command": result["next_allowed_command"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "validate-plan":
        plan = _read_json(args.plan)
        result = validate_archive_source_plan(
            plan,
            expected_plan_hash=args.expected_plan_hash,
            source_route_path=args.source_route,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "schema-probe-descriptor":
        plan = _load_plan(args.plan)
        result = build_schema_probe_descriptor(
            plan,
            symbol=args.symbol,
            sample_date=args.sample_date,
            max_runtime_sec=args.max_runtime_sec,
        )
        _write_json_immutable(args.output, result)
        print(
            json.dumps(
                {
                    "schema": result["schema"],
                    "descriptor_hash": result["descriptor_hash"],
                    "output": str(Path(args.output).expanduser().resolve()),
                    "next_allowed_command": result["next_allowed_command"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "binding-audit":
        plan = _load_plan(args.plan)
        result = assess_archive_actionability(
            plan,
            args.recovery_preflight,
            args.output,
        )
        print(
            json.dumps(
                {
                    "schema": result["schema"],
                    "verdict": result["verdict"],
                    "artifact_hash": result["artifact_hash"],
                    "output": str(Path(args.output).expanduser().resolve()),
                    "next_allowed_command": result["next_allowed_command"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
