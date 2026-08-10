from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib import error as urlerror
from urllib import request


MEXC_ENDPOINT = "https://contract.mexc.com/api/v1/contract/detail"
GATEIO_ENDPOINT = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
ENDPOINTS = (MEXC_ENDPOINT, GATEIO_ENDPOINT)

PROPOSAL_SCHEMA = (
    "trading_mvp_funding_unrestricted_metadata_discovery_diagnostic_refreeze_proposal_v2"
)
RECEIPT_SCHEMA = (
    "trading_mvp_funding_unrestricted_metadata_discovery_approval_receipt_v2"
)
RUNTIME_MANIFEST_SCHEMA = (
    "trading_mvp_funding_unrestricted_metadata_discovery_runtime_manifest_v2"
)
FAILURE_DIAGNOSTIC_SCHEMA = (
    "trading_mvp_funding_unrestricted_metadata_discovery_failure_v2"
)
GLOBAL_WRITER_CLAIM_SCHEMA = "trading_mvp_global_market_writer_claim_v1"

PROPOSAL_STATUS = "AWAIT_EXACT_HASH_BOUND_APPROVAL"
RECEIPT_STATUS = "ACTIVE_SINGLE_USE"
RUNTIME_MANIFEST_STATUS = "FROZEN_WITH_EXACT_SINGLE_USE_APPROVAL"
COMPLETE_STATUS = "COMPLETE_REQUIRES_IDENTITY_VERIFICATION"

MEXC_FIELDS = (
    "symbol",
    "baseCoin",
    "baseCoinName",
    "quoteCoin",
    "quoteCoinName",
    "settleCoin",
    "state",
    "apiAllowed",
)
GATEIO_FIELDS = ("name", "status", "type", "in_delisting")
REQUIRED_OUTPUT_FILES = (
    "mexc-active-contracts.json",
    "gateio-active-contracts.json",
    "provisional-shared-ticker-candidates.json",
    "manifest.json",
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_CONTRACT_NAME = re.compile(r"^[A-Za-z0-9._-]+_USDT$")
MAX_RESPONSE_BYTES = 25_000_000
DEFAULT_USER_AGENT = "trading-mvp-metadata-discovery/1.0"
FAILURE_DIAGNOSTIC_MAX_BYTES = 16_384
FAILURE_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)

ENDPOINT_IDS = {
    MEXC_ENDPOINT: "MEXC_CONTRACT_DETAIL",
    GATEIO_ENDPOINT: "GATEIO_CONTRACTS",
}
FAILURE_CATEGORIES = frozenset(
    {
        "BINDING_VALIDATION",
        "CONNECTION_REFUSED",
        "CONNECTION_RESET",
        "DNS_RESOLUTION",
        "HTTP_STATUS",
        "INVALID_JSON",
        "NETWORK_IO",
        "REQUEST_BUDGET",
        "RESPONSE_TOO_LARGE",
        "RUNTIME_DEADLINE",
        "TLS_FAILURE",
        "TIMEOUT",
        "URL_ERROR",
        "WRITER_CLAIM",
        "CONTRACT_METADATA_VALIDATION",
        "OUTPUT_COMMIT",
        "INTERNAL_ERROR",
    }
)
FAILURE_STAGES = frozenset(
    {
        "BINDING_VALIDATION",
        "WRITER_CLAIM",
        "HTTP_REQUEST",
        "HTTP_RESPONSE",
        "RESPONSE_DECODE",
        "CONTRACT_PROJECTION",
        "OUTPUT_COMMIT",
        "RUNTIME_DEADLINE",
        "INTERNAL",
    }
)
SAFE_EXCEPTION_TYPES = frozenset(
    {
        "DISCOVERY_ERROR",
        "HTTP_ERROR",
        "OS_ERROR",
        "SSL_ERROR",
        "TIMEOUT_ERROR",
        "URL_ERROR",
        "VALUE_ERROR",
        "OTHER",
    }
)
FAILURE_RECORD_FIELDS = frozenset(
    {
        "schema",
        "status",
        "run_id",
        "observed_at_utc",
        "proposal_hash",
        "failure",
        "maximum_total_http_requests",
        "raw_payload_persisted",
        "funding_rates_persisted",
        "prices_persisted",
        "retry_authorized",
        "failure_hash_method",
        "failure_hash",
    }
)
FAILURE_DETAIL_FIELDS = frozenset(
    {
        "category",
        "stage",
        "endpoint_id",
        "exception_type",
        "http_status",
        "attempt",
        "request_count",
    }
)


class DiscoveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        diagnostic: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic or {})


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"{label} could not be loaded: {exc}") from exc
    if not isinstance(payload, dict):
        raise DiscoveryError(f"{label} must be a JSON object")
    return payload


def _verify_file_hash(path: Path, expected: str, label: str) -> str:
    expected_lower = str(expected or "").lower()
    if SHA256_PATTERN.fullmatch(expected_lower) is None:
        raise DiscoveryError(f"{label} expected SHA-256 is invalid")
    if not path.is_file():
        raise DiscoveryError(f"{label} is missing: {path}")
    observed = _sha256_file(path)
    if observed != expected_lower:
        raise DiscoveryError(
            f"{label} SHA-256 mismatch: expected {expected_lower}, observed {observed}"
        )
    return observed


def _verify_embedded_hash(
    payload: Mapping[str, Any],
    *,
    field: str,
    label: str,
) -> str:
    expected = str(payload.get(field) or "").lower()
    if SHA256_PATTERN.fullmatch(expected) is None:
        raise DiscoveryError(f"{label} {field} is missing or invalid")
    canonical = dict(payload)
    canonical.pop(field, None)
    observed = _canonical_hash(canonical)
    if observed != expected:
        raise DiscoveryError(
            f"{label} {field} mismatch: expected {expected}, observed {observed}"
        )
    return observed


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(str(Path(left).expanduser().resolve())) == os.path.normcase(
        str(Path(right).expanduser().resolve())
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _safe_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if minimum <= normalized <= maximum else None


def _sanitize_failure_diagnostic(
    diagnostic: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = diagnostic if isinstance(diagnostic, Mapping) else {}
    category = str(source.get("category") or "")
    stage = str(source.get("stage") or "")
    endpoint_id = str(source.get("endpoint_id") or "") or None
    exception_type = str(source.get("exception_type") or "")
    if category not in FAILURE_CATEGORIES:
        category = "INTERNAL_ERROR"
    if stage not in FAILURE_STAGES:
        stage = "INTERNAL"
    if endpoint_id not in set(ENDPOINT_IDS.values()):
        endpoint_id = None
    if exception_type not in SAFE_EXCEPTION_TYPES:
        exception_type = "OTHER"
    return {
        "category": category,
        "stage": stage,
        "endpoint_id": endpoint_id,
        "exception_type": exception_type,
        "http_status": _safe_int(source.get("http_status"), minimum=100, maximum=599),
        "attempt": _safe_int(source.get("attempt"), minimum=0, maximum=2),
        "request_count": _safe_int(
            source.get("request_count"), minimum=0, maximum=4
        ),
    }


def _failure_context(
    *,
    category: str,
    stage: str,
    endpoint_url: str | None = None,
    exception_type: str = "DISCOVERY_ERROR",
    http_status: int | None = None,
    attempt: int | None = None,
    request_count: int | None = None,
) -> dict[str, Any]:
    return _sanitize_failure_diagnostic(
        {
            "category": category,
            "stage": stage,
            "endpoint_id": ENDPOINT_IDS.get(str(endpoint_url or "")),
            "exception_type": exception_type,
            "http_status": http_status,
            "attempt": attempt,
            "request_count": request_count,
        }
    )


def _classify_request_failure(
    exc: Exception,
    *,
    endpoint_url: str,
    attempt: int,
    request_count: int,
) -> dict[str, Any]:
    category = "NETWORK_IO"
    exception_type = "OTHER"
    http_status = None
    reason: Any = exc
    if isinstance(exc, urlerror.HTTPError):
        category = "HTTP_STATUS"
        exception_type = "HTTP_ERROR"
        http_status = int(exc.code)
    elif isinstance(exc, urlerror.URLError):
        category = "URL_ERROR"
        exception_type = "URL_ERROR"
        reason = exc.reason

    if isinstance(reason, socket.gaierror):
        category = "DNS_RESOLUTION"
        exception_type = "OS_ERROR"
    elif isinstance(reason, (TimeoutError, socket.timeout)):
        category = "TIMEOUT"
        exception_type = "TIMEOUT_ERROR"
    elif isinstance(reason, ssl.SSLError):
        category = "TLS_FAILURE"
        exception_type = "SSL_ERROR"
    elif isinstance(reason, ConnectionRefusedError):
        category = "CONNECTION_REFUSED"
        exception_type = "OS_ERROR"
    elif isinstance(reason, ConnectionResetError):
        category = "CONNECTION_RESET"
        exception_type = "OS_ERROR"
    elif isinstance(reason, OSError) and not isinstance(exc, urlerror.HTTPError):
        if category != "URL_ERROR":
            category = "NETWORK_IO"
        exception_type = "OS_ERROR"

    return _failure_context(
        category=category,
        stage="HTTP_REQUEST",
        endpoint_url=endpoint_url,
        exception_type=exception_type,
        http_status=http_status,
        attempt=attempt,
        request_count=request_count,
    )


def build_failure_diagnostic_record(
    *,
    run_id: str,
    expected_proposal_hash: str,
    diagnostic: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise DiscoveryError("run_id contains unsafe characters")
    if SHA256_PATTERN.fullmatch(expected_proposal_hash) is None:
        raise DiscoveryError("expected proposal hash is invalid")
    record: dict[str, Any] = {
        "schema": FAILURE_DIAGNOSTIC_SCHEMA,
        "status": "STOPPED_INCOMPLETE",
        "run_id": run_id,
        "observed_at_utc": _utc_now(),
        "proposal_hash": expected_proposal_hash,
        "failure": _sanitize_failure_diagnostic(diagnostic),
        "maximum_total_http_requests": 4,
        "raw_payload_persisted": False,
        "funding_rates_persisted": False,
        "prices_persisted": False,
        "retry_authorized": False,
        "failure_hash_method": "sha256_canonical_json_excluding_failure_hash",
    }
    record["failure_hash"] = _canonical_hash(record)
    return record


def _require_optional_json_int(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiscoveryError(f"failure diagnostic {label} must be an integer or null")
    if not minimum <= value <= maximum:
        raise DiscoveryError(f"failure diagnostic {label} is outside its safe range")


def validate_failure_diagnostic_record(
    record: Mapping[str, Any],
    *,
    expected_run_id: str | None = None,
    expected_proposal_hash: str | None = None,
) -> dict[str, Any]:
    normalized = dict(record)
    _require_exact_keys(normalized, set(FAILURE_RECORD_FIELDS), "failure diagnostic top-level")
    if normalized.get("schema") != FAILURE_DIAGNOSTIC_SCHEMA:
        raise DiscoveryError("failure diagnostic schema mismatch")
    if normalized.get("status") != "STOPPED_INCOMPLETE":
        raise DiscoveryError("failure diagnostic status mismatch")

    run_id = normalized.get("run_id")
    if not isinstance(run_id, str) or SAFE_RUN_ID.fullmatch(run_id) is None:
        raise DiscoveryError("failure diagnostic run_id is invalid")
    if expected_run_id is not None and run_id != expected_run_id:
        raise DiscoveryError("failure diagnostic run_id binding mismatch")

    observed_at = normalized.get("observed_at_utc")
    if not isinstance(observed_at, str) or FAILURE_TIMESTAMP_PATTERN.fullmatch(observed_at) is None:
        raise DiscoveryError("failure diagnostic timestamp is invalid")
    try:
        parsed_timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiscoveryError("failure diagnostic timestamp is invalid") from exc
    if parsed_timestamp.utcoffset() != timezone.utc.utcoffset(parsed_timestamp):
        raise DiscoveryError("failure diagnostic timestamp is not UTC")

    proposal_hash = normalized.get("proposal_hash")
    if not isinstance(proposal_hash, str) or SHA256_PATTERN.fullmatch(proposal_hash) is None:
        raise DiscoveryError("failure diagnostic proposal hash is invalid")
    if expected_proposal_hash is not None and proposal_hash != expected_proposal_hash:
        raise DiscoveryError("failure diagnostic proposal hash binding mismatch")

    if (
        isinstance(normalized.get("maximum_total_http_requests"), bool)
        or normalized.get("maximum_total_http_requests") != 4
    ):
        raise DiscoveryError("failure diagnostic request cap changed")
    for field in (
        "raw_payload_persisted",
        "funding_rates_persisted",
        "prices_persisted",
        "retry_authorized",
    ):
        if normalized.get(field) is not False:
            raise DiscoveryError(f"failure diagnostic {field} must remain false")
    if (
        normalized.get("failure_hash_method")
        != "sha256_canonical_json_excluding_failure_hash"
    ):
        raise DiscoveryError("failure diagnostic hash method changed")

    failure = normalized.get("failure")
    if not isinstance(failure, Mapping):
        raise DiscoveryError("failure diagnostic detail must be an object")
    detail = dict(failure)
    _require_exact_keys(detail, set(FAILURE_DETAIL_FIELDS), "failure diagnostic detail")
    if detail.get("category") not in FAILURE_CATEGORIES:
        raise DiscoveryError("failure diagnostic category is not allowlisted")
    if detail.get("stage") not in FAILURE_STAGES:
        raise DiscoveryError("failure diagnostic stage is not allowlisted")
    if detail.get("endpoint_id") not in {None, *ENDPOINT_IDS.values()}:
        raise DiscoveryError("failure diagnostic endpoint is not allowlisted")
    if detail.get("exception_type") not in SAFE_EXCEPTION_TYPES:
        raise DiscoveryError("failure diagnostic exception type is not allowlisted")
    _require_optional_json_int(
        detail.get("http_status"),
        label="http_status",
        minimum=100,
        maximum=599,
    )
    _require_optional_json_int(
        detail.get("attempt"),
        label="attempt",
        minimum=0,
        maximum=2,
    )
    _require_optional_json_int(
        detail.get("request_count"),
        label="request_count",
        minimum=0,
        maximum=4,
    )

    observed_hash = normalized.get("failure_hash")
    if not isinstance(observed_hash, str) or SHA256_PATTERN.fullmatch(observed_hash) is None:
        raise DiscoveryError("failure diagnostic hash is invalid")
    body = dict(normalized)
    body.pop("failure_hash", None)
    if observed_hash != _canonical_hash(body):
        raise DiscoveryError("failure diagnostic canonical hash mismatch")
    return normalized


def validate_failure_diagnostic_path(
    repo_root: str | Path,
    run_id: str,
    requested_path: str | Path,
) -> Path:
    root = Path(repo_root).expanduser().resolve()
    expected = (
        root
        / "docs"
        / "agent-log"
        / "run-gates"
        / f"{run_id}.runtime-failure.json"
    ).resolve()
    requested = Path(requested_path).expanduser().resolve()
    if not _same_path(expected, requested):
        raise DiscoveryError("failure diagnostic path is not the exact run binding")
    return requested


def write_failure_diagnostic(
    path: str | Path,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    normalized = validate_failure_diagnostic_record(record)
    encoded = _json_bytes(normalized)
    if len(encoded) > FAILURE_DIAGNOSTIC_MAX_BYTES:
        raise DiscoveryError("failure diagnostic exceeds the byte cap")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise DiscoveryError("failure diagnostic already exists") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return normalized


def read_failure_diagnostic(
    path: str | Path,
    *,
    expected_run_id: str,
    expected_proposal_hash: str,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise DiscoveryError("failure diagnostic is missing or unreadable") from exc
    if size <= 0 or size > FAILURE_DIAGNOSTIC_MAX_BYTES:
        raise DiscoveryError("failure diagnostic size is outside the safe range")
    payload = _load_json_object(target, "failure diagnostic")
    return validate_failure_diagnostic_record(
        payload,
        expected_run_id=expected_run_id,
        expected_proposal_hash=expected_proposal_hash,
    )


def _write_json(path: Path, payload: Any) -> tuple[str, int]:
    raw = _json_bytes(payload)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise DiscoveryError(
            f"{label} fields changed: missing={missing}, unexpected={unexpected}"
        )


def _validate_contract_name(value: Any, label: str) -> str:
    name = str(value or "").strip()
    if SAFE_CONTRACT_NAME.fullmatch(name) is None:
        raise DiscoveryError(f"{label} has an unsafe USDT contract identifier: {name!r}")
    return name


def _ticker_from_contract_name(name: str) -> str:
    ticker = name[: -len("_USDT")].upper()
    if not ticker:
        raise DiscoveryError(f"contract has an empty ticker: {name}")
    return ticker


def project_mexc_active_contracts(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise DiscoveryError("MEXC response must be a JSON object")
    if payload.get("success") is not True or payload.get("code") not in (0, "0"):
        raise DiscoveryError("MEXC response did not report success")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise DiscoveryError("MEXC response data must be an array")

    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DiscoveryError(f"MEXC contract row {index} must be an object")
        quote = str(row.get("quoteCoin") or "").upper()
        settle = str(row.get("settleCoin") or "").upper()
        if quote != "USDT" or settle != "USDT":
            continue
        if row.get("state") not in (0, "0"):
            continue
        if row.get("apiAllowed") is False:
            continue

        symbol = _validate_contract_name(row.get("symbol"), f"MEXC row {index}")
        ticker = _ticker_from_contract_name(symbol)
        base_coin = str(row.get("baseCoin") or "").strip()
        if base_coin.upper() != ticker:
            raise DiscoveryError(
                f"MEXC row {index} baseCoin does not match its contract ticker"
            )
        if symbol in seen:
            raise DiscoveryError(f"MEXC duplicate active contract: {symbol}")
        seen.add(symbol)
        record = {field: row.get(field) for field in MEXC_FIELDS}
        _require_exact_keys(record, set(MEXC_FIELDS), "MEXC projection")
        projected.append(record)

    projected.sort(key=lambda row: str(row["symbol"]))
    return projected


def project_gateio_active_contracts(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise DiscoveryError("Gate response must be a JSON array")

    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise DiscoveryError(f"Gate contract row {index} must be an object")
        if str(row.get("status") or "").lower() != "trading":
            continue
        if row.get("in_delisting") is True:
            continue
        name = _validate_contract_name(row.get("name"), f"Gate row {index}")
        if name in seen:
            raise DiscoveryError(f"Gate duplicate active contract: {name}")
        seen.add(name)
        record = {field: row.get(field) for field in GATEIO_FIELDS}
        _require_exact_keys(record, set(GATEIO_FIELDS), "Gate projection")
        projected.append(record)

    projected.sort(key=lambda row: str(row["name"]))
    return projected


def _unique_ticker_map(
    records: Sequence[Mapping[str, Any]],
    *,
    contract_field: str,
    venue: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in records:
        name = _validate_contract_name(row.get(contract_field), venue)
        ticker = _ticker_from_contract_name(name)
        if ticker in result:
            raise DiscoveryError(
                f"{venue} duplicate normalized ticker cannot be resolved: {ticker}"
            )
        result[ticker] = name
    return result


def build_provisional_ticker_candidates(
    mexc_records: Sequence[Mapping[str, Any]],
    gateio_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    mexc = _unique_ticker_map(
        mexc_records,
        contract_field="symbol",
        venue="MEXC",
    )
    gateio = _unique_ticker_map(
        gateio_records,
        contract_field="name",
        venue="Gate",
    )
    return [
        {
            "ticker": ticker,
            "mexc_symbol": mexc[ticker],
            "gateio_name": gateio[ticker],
            "identity_status": "UNRESOLVED_TICKER_MATCH_ONLY",
            "same_underlying_verified": False,
        }
        for ticker in sorted(mexc.keys() & gateio.keys())
    ]


class RejectRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class BoundedMetadataClient:
    def __init__(
        self,
        *,
        opener: Any | None = None,
        max_total_requests: int = 4,
        max_attempts_per_endpoint: int = 2,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        monotonic: Callable[[], float] = time.monotonic,
        deadline_monotonic: float | None = None,
    ) -> None:
        if max_total_requests != 4:
            raise DiscoveryError("HTTP request budget must remain exactly 4")
        if max_attempts_per_endpoint != 2:
            raise DiscoveryError("endpoint attempt budget must remain exactly 2")
        if max_response_bytes <= 0 or max_response_bytes > MAX_RESPONSE_BYTES:
            raise DiscoveryError("response byte cap is invalid")
        self.opener = opener or request.build_opener(
            request.ProxyHandler({}),
            RejectRedirectHandler(),
        )
        self.max_total_requests = max_total_requests
        self.max_attempts_per_endpoint = max_attempts_per_endpoint
        self.max_response_bytes = max_response_bytes
        self.monotonic = monotonic
        self.deadline_monotonic = (
            float(deadline_monotonic)
            if deadline_monotonic is not None
            else monotonic() + 300.0
        )
        self.request_count = 0

    def fetch(self, url: str) -> tuple[Any, dict[str, Any]]:
        if url not in ENDPOINTS:
            raise DiscoveryError(
                "endpoint is not allowlisted",
                diagnostic=_failure_context(
                    category="BINDING_VALIDATION",
                    stage="BINDING_VALIDATION",
                    request_count=self.request_count,
                ),
            )
        if self.request_count >= self.max_total_requests:
            raise DiscoveryError(
                "HTTP request budget exhausted",
                diagnostic=_failure_context(
                    category="REQUEST_BUDGET",
                    stage="HTTP_REQUEST",
                    endpoint_url=url,
                    request_count=self.request_count,
                ),
            )

        last_diagnostic = _failure_context(
            category="INTERNAL_ERROR",
            stage="HTTP_REQUEST",
            endpoint_url=url,
            request_count=self.request_count,
        )
        for attempt in range(1, self.max_attempts_per_endpoint + 1):
            if self.request_count >= self.max_total_requests:
                raise DiscoveryError(
                    "HTTP request budget exhausted",
                    diagnostic=_failure_context(
                        category="REQUEST_BUDGET",
                        stage="HTTP_REQUEST",
                        endpoint_url=url,
                        attempt=attempt,
                        request_count=self.request_count,
                    ),
                )
            remaining = self.deadline_monotonic - self.monotonic()
            if remaining <= 0:
                raise DiscoveryError(
                    "runtime deadline reached before HTTP request",
                    diagnostic=_failure_context(
                        category="RUNTIME_DEADLINE",
                        stage="RUNTIME_DEADLINE",
                        endpoint_url=url,
                        attempt=attempt,
                        request_count=self.request_count,
                    ),
                )
            timeout = max(0.1, min(30.0, remaining))
            req = request.Request(
                url,
                data=None,
                headers={
                    "Accept": "application/json",
                    "User-Agent": DEFAULT_USER_AGENT,
                },
                method="GET",
            )
            self.request_count += 1
            try:
                with self.opener.open(req, timeout=timeout) as response:
                    status = int(getattr(response, "status", 200))
                    if status != 200:
                        raise DiscoveryError(
                            "metadata endpoint returned a non-200 status",
                            diagnostic=_failure_context(
                                category="HTTP_STATUS",
                                stage="HTTP_RESPONSE",
                                endpoint_url=url,
                                exception_type="HTTP_ERROR",
                                http_status=status,
                                attempt=attempt,
                                request_count=self.request_count,
                            ),
                        )
                    raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise DiscoveryError(
                        "metadata response exceeds the in-memory byte cap",
                        diagnostic=_failure_context(
                            category="RESPONSE_TOO_LARGE",
                            stage="HTTP_RESPONSE",
                            endpoint_url=url,
                            attempt=attempt,
                            request_count=self.request_count,
                        ),
                    )
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DiscoveryError(
                        "metadata response is not valid UTF-8 JSON",
                        diagnostic=_failure_context(
                            category="INVALID_JSON",
                            stage="RESPONSE_DECODE",
                            endpoint_url=url,
                            exception_type="VALUE_ERROR",
                            attempt=attempt,
                            request_count=self.request_count,
                        ),
                    ) from exc
                return payload, {
                    "url": url,
                    "method": "GET",
                    "http_status": status,
                    "attempts": attempt,
                    "response_bytes": len(raw),
                    "response_body_sha256": hashlib.sha256(raw).hexdigest(),
                }
            except DiscoveryError as exc:
                last_diagnostic = exc.diagnostic or _failure_context(
                    category="INTERNAL_ERROR",
                    stage="HTTP_REQUEST",
                    endpoint_url=url,
                    attempt=attempt,
                    request_count=self.request_count,
                )
            except Exception as exc:  # urllib exposes several unrelated error types.
                last_diagnostic = _classify_request_failure(
                    exc,
                    endpoint_url=url,
                    attempt=attempt,
                    request_count=self.request_count,
                )

        raise DiscoveryError(
            f"metadata endpoint failed after {self.max_attempts_per_endpoint} attempts",
            diagnostic=last_diagnostic,
        )


def _validate_endpoint_evidence(endpoint_evidence: Mapping[str, Any]) -> None:
    expected = {"mexc": MEXC_ENDPOINT, "gateio": GATEIO_ENDPOINT}
    _require_exact_keys(endpoint_evidence, set(expected), "endpoint evidence")
    for venue, url in expected.items():
        value = endpoint_evidence.get(venue)
        if not isinstance(value, dict):
            raise DiscoveryError(f"{venue} endpoint evidence must be an object")
        if value.get("url") != url:
            raise DiscoveryError(f"{venue} endpoint evidence URL changed")
        digest = str(value.get("response_body_sha256") or "").lower()
        if SHA256_PATTERN.fullmatch(digest) is None:
            raise DiscoveryError(f"{venue} response SHA-256 is invalid")
        attempts = int(value.get("attempts") or 0)
        if attempts < 1 or attempts > 2:
            raise DiscoveryError(f"{venue} endpoint attempts exceed the frozen limit")
        if "response_body" in value or "raw" in value:
            raise DiscoveryError(f"{venue} endpoint evidence contains raw response data")


def _validate_bindings(bindings: Mapping[str, Any]) -> None:
    for key in ("proposal_hash", "receipt_hash", "runtime_manifest_hash"):
        if SHA256_PATTERN.fullmatch(str(bindings.get(key) or "").lower()) is None:
            raise DiscoveryError(f"output binding is missing or invalid: {key}")


def write_immutable_discovery(
    output_path: str | Path,
    *,
    run_id: str,
    mexc_records: Sequence[Mapping[str, Any]],
    gateio_records: Sequence[Mapping[str, Any]],
    provisional_candidates: Sequence[Mapping[str, Any]],
    endpoint_evidence: Mapping[str, Any],
    bindings: Mapping[str, Any],
    started_at_utc: str,
    finished_at_utc: str,
    duration_sec: float,
    request_count: int,
    hard_output_cap_bytes: int,
    minimum_active_contracts_per_venue: int,
) -> dict[str, Any]:
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise DiscoveryError(f"immutable output already exists: {target}")
    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise DiscoveryError("run_id contains unsafe characters")
    if hard_output_cap_bytes != 50_000_000:
        raise DiscoveryError("hard output cap must remain exactly 50000000 bytes")
    if request_count < 1 or request_count > 4:
        raise DiscoveryError("HTTP request count is outside the frozen range")
    if duration_sec < 0 or duration_sec > 300:
        raise DiscoveryError("runtime duration exceeds the frozen 300-second limit")
    if minimum_active_contracts_per_venue < 1:
        raise DiscoveryError("minimum active-contract threshold is invalid")
    if len(mexc_records) < minimum_active_contracts_per_venue:
        raise DiscoveryError("MEXC active-contract count is suspiciously incomplete")
    if len(gateio_records) < minimum_active_contracts_per_venue:
        raise DiscoveryError("Gate active-contract count is suspiciously incomplete")
    if not provisional_candidates:
        raise DiscoveryError("no provisional shared ticker candidate was discovered")
    _validate_endpoint_evidence(endpoint_evidence)
    _validate_bindings(bindings)

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(parent))
    ).resolve()
    try:
        documents: dict[str, Any] = {
            "mexc-active-contracts.json": {
                "schema": "trading_mvp_funding_active_contract_metadata_v1",
                "run_id": run_id,
                "venue": "mexc",
                "endpoint_url": MEXC_ENDPOINT,
                "observed_at_utc": finished_at_utc,
                "active_contract_count": len(mexc_records),
                "records": list(mexc_records),
            },
            "gateio-active-contracts.json": {
                "schema": "trading_mvp_funding_active_contract_metadata_v1",
                "run_id": run_id,
                "venue": "gateio",
                "endpoint_url": GATEIO_ENDPOINT,
                "observed_at_utc": finished_at_utc,
                "active_contract_count": len(gateio_records),
                "records": list(gateio_records),
            },
            "provisional-shared-ticker-candidates.json": {
                "schema": "trading_mvp_funding_provisional_ticker_candidates_v1",
                "run_id": run_id,
                "match_method": "NORMALIZED_CONTRACT_TICKER_INTERSECTION",
                "identity_disposition": "PROVISIONAL_ONLY_NOT_IDENTITY_EVIDENCE",
                "same_underlying_verified": False,
                "candidate_count": len(provisional_candidates),
                "candidates": list(provisional_candidates),
            },
        }
        file_metadata: dict[str, dict[str, Any]] = {}
        for name, document in documents.items():
            digest, size = _write_json(temporary / name, document)
            file_metadata[name] = {"sha256": digest, "bytes": size}

        manifest: dict[str, Any] = {
            "schema": "trading_mvp_funding_unrestricted_metadata_discovery_output_v1",
            "status": COMPLETE_STATUS,
            "run_id": run_id,
            "research_only": True,
            "started_at_utc": started_at_utc,
            "finished_at_utc": finished_at_utc,
            "duration_sec": round(float(duration_sec), 6),
            "request_count": int(request_count),
            "request_limit": 4,
            "hard_output_cap_bytes": hard_output_cap_bytes,
            "contract_counts": {
                "mexc": len(mexc_records),
                "gateio": len(gateio_records),
                "provisional_shared_tickers": len(provisional_candidates),
            },
            "bindings": dict(bindings),
            "endpoint_evidence": dict(endpoint_evidence),
            "projected_outputs": file_metadata,
            "raw_response_persisted": False,
            "funding_rates_or_prices_persisted": False,
            "identity_verified": False,
            "next_checkpoint": (
                "SEPARATE_EXACT_IDENTITY_VERIFIED_CANDIDATE_PLANONLY_REQUIRED"
            ),
            "automatic_data_collection_allowed": False,
        }
        manifest_digest, manifest_size = _write_json(
            temporary / "manifest.json",
            manifest,
        )
        total_bytes = sum(path.stat().st_size for path in temporary.iterdir())
        if total_bytes > hard_output_cap_bytes:
            raise DiscoveryError(
                f"output cap exceeded: {total_bytes} > {hard_output_cap_bytes}"
            )
        if sorted(path.name for path in temporary.iterdir()) != sorted(
            REQUIRED_OUTPUT_FILES
        ):
            raise DiscoveryError("required output file set changed")
        manifest["manifest_file_sha256"] = manifest_digest
        manifest["manifest_file_bytes"] = manifest_size
        manifest["total_output_bytes"] = total_bytes
        os.replace(temporary, target)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_global_writer_claim(
    claim_path: str | Path,
    *,
    run_id: str,
    owner_pid: int,
    ownership_token: str,
) -> dict[str, Any]:
    claim = _load_json_object(Path(claim_path).expanduser().resolve(), "writer claim")
    if claim.get("schema") != GLOBAL_WRITER_CLAIM_SCHEMA:
        raise DiscoveryError("global writer claim schema mismatch")
    if claim.get("status") != "CLAIMED":
        raise DiscoveryError("global writer claim is not active")
    if claim.get("run_id") != run_id:
        raise DiscoveryError("global writer claim run_id mismatch")
    if int(claim.get("owner_pid") or 0) != int(owner_pid):
        raise DiscoveryError("global writer claim owner_pid mismatch")
    if claim.get("ownership_token") != ownership_token:
        raise DiscoveryError("global writer claim token mismatch")
    return claim


@dataclass(frozen=True)
class ValidatedArtifacts:
    proposal: dict[str, Any]
    proposal_file_sha256: str
    proposal_hash: str
    receipt: dict[str, Any]
    receipt_file_sha256: str
    receipt_hash: str
    runtime_manifest: dict[str, Any]
    runtime_manifest_file_sha256: str
    runtime_manifest_hash: str
    output_path: Path
    minimum_active_contracts_per_venue: int


def _validate_proposal(
    proposal: Mapping[str, Any],
    *,
    expected_file_sha256: str,
    expected_hash: str,
) -> None:
    if proposal.get("schema") != PROPOSAL_SCHEMA:
        raise DiscoveryError("proposal schema mismatch")
    if proposal.get("status") != PROPOSAL_STATUS:
        raise DiscoveryError("proposal status changed")
    if proposal.get("proposal_hash") != expected_hash:
        raise DiscoveryError("proposal hash binding changed")
    discovery = proposal.get("discovery_contract")
    runtime = proposal.get("runtime_contract")
    authorization = proposal.get("authorization")
    if not isinstance(discovery, dict) or not isinstance(runtime, dict):
        raise DiscoveryError("proposal discovery/runtime contract is missing")
    endpoint_entries = discovery.get("endpoint_allowlist")
    if not isinstance(endpoint_entries, list):
        raise DiscoveryError("proposal endpoint allowlist is missing")
    urls = [
        f"{entry.get('base_url')}{entry.get('path')}"
        for entry in endpoint_entries
        if isinstance(entry, dict)
    ]
    if urls != list(ENDPOINTS):
        raise DiscoveryError("proposal endpoint allowlist changed")
    limits = discovery.get("request_limits")
    if not isinstance(limits, dict):
        raise DiscoveryError("proposal request limits are missing")
    if limits.get("maximum_total_http_requests") != 4:
        raise DiscoveryError("proposal request limit changed")
    if limits.get("maximum_attempts_per_endpoint") != 2:
        raise DiscoveryError("proposal endpoint attempt limit changed")
    if runtime.get("max_runtime_sec") != 300:
        raise DiscoveryError("proposal runtime limit changed")
    if runtime.get("hard_output_cap_bytes") != 50_000_000:
        raise DiscoveryError("proposal output cap changed")
    if not isinstance(authorization, dict):
        raise DiscoveryError("proposal authorization boundary is missing")
    if authorization.get("actual_network_run_allowed") is not False:
        raise DiscoveryError("proposal must remain non-executable without receipt")
    failure_diagnostic = runtime.get("failure_diagnostic")
    if not isinstance(failure_diagnostic, dict):
        raise DiscoveryError("proposal failure diagnostic contract is missing")
    if failure_diagnostic.get("required_on_execution_failure") is not True:
        raise DiscoveryError("proposal no longer requires a failure diagnostic")
    if failure_diagnostic.get("maximum_bytes") != FAILURE_DIAGNOSTIC_MAX_BYTES:
        raise DiscoveryError("proposal failure diagnostic byte cap changed")
    if failure_diagnostic.get("free_form_error_text_allowed") is not False:
        raise DiscoveryError("proposal unexpectedly allows free-form failure text")


def _validate_receipt(
    receipt: Mapping[str, Any],
    *,
    proposal_path: Path,
    proposal_file_sha256: str,
    proposal_hash: str,
    run_id: str,
    failure_diagnostic_path: Path,
) -> Path:
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise DiscoveryError("approval receipt schema mismatch")
    if receipt.get("status") != RECEIPT_STATUS:
        raise DiscoveryError("approval receipt is not active")
    if receipt.get("user_approval_received") is not True:
        raise DiscoveryError("approval receipt has no exact user approval")
    proposal = receipt.get("proposal")
    binding = receipt.get("run_binding")
    scope = receipt.get("execution_scope")
    forbidden = receipt.get("forbidden_scope")
    if not all(isinstance(value, dict) for value in (proposal, binding, scope, forbidden)):
        raise DiscoveryError("approval receipt boundary is incomplete")
    if not _same_path(proposal.get("path", ""), proposal_path):
        raise DiscoveryError("approval receipt proposal path mismatch")
    if proposal.get("file_sha256") != proposal_file_sha256:
        raise DiscoveryError("approval receipt proposal file SHA mismatch")
    if proposal.get("proposal_hash") != proposal_hash:
        raise DiscoveryError("approval receipt proposal hash mismatch")
    if binding.get("run_id") != run_id or binding.get("single_use") is not True:
        raise DiscoveryError("approval receipt single-use run binding changed")
    if binding.get("stopped_incomplete_retry_authorized") is not False:
        raise DiscoveryError("approval receipt unexpectedly allows retry")
    if not _same_path(
        str(binding.get("failure_diagnostic_path") or ""),
        failure_diagnostic_path,
    ):
        raise DiscoveryError("approval receipt failure diagnostic path mismatch")
    if scope.get("one_visible_public_read_only_metadata_run_allowed") is not True:
        raise DiscoveryError("approval receipt does not allow the visible metadata run")
    if scope.get("max_runtime_sec") != 300:
        raise DiscoveryError("approval receipt runtime limit changed")
    if scope.get("hard_output_cap_bytes") != 50_000_000:
        raise DiscoveryError("approval receipt output cap changed")
    if scope.get("maximum_total_http_requests") != 4:
        raise DiscoveryError("approval receipt request limit changed")
    if scope.get("maximum_attempts_per_endpoint") != 2:
        raise DiscoveryError("approval receipt endpoint attempts changed")
    if scope.get("allowed_endpoint_urls") != list(ENDPOINTS):
        raise DiscoveryError("approval receipt endpoint scope changed")
    if scope.get("global_writer_claim_required") is not True:
        raise DiscoveryError("approval receipt no longer requires one writer")
    if scope.get("sanitized_failure_diagnostic_required") is not True:
        raise DiscoveryError("approval receipt no longer requires safe diagnostics")
    if scope.get("failure_diagnostic_max_bytes") != FAILURE_DIAGNOSTIC_MAX_BYTES:
        raise DiscoveryError("approval receipt diagnostic byte cap changed")
    if any(value is not False for value in forbidden.values()):
        raise DiscoveryError("approval receipt forbidden scope changed")
    return Path(str(binding.get("output_path") or "")).expanduser().resolve()


def _validate_runtime_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path,
    proposal_path: Path,
    proposal_file_sha256: str,
    proposal_hash: str,
    receipt_path: Path,
    receipt_file_sha256: str,
    receipt_hash: str,
    run_id: str,
    output_path: Path,
    failure_diagnostic_path: Path,
) -> int:
    if manifest.get("schema") != RUNTIME_MANIFEST_SCHEMA:
        raise DiscoveryError("runtime manifest schema mismatch")
    if manifest.get("status") != RUNTIME_MANIFEST_STATUS:
        raise DiscoveryError("runtime manifest is not frozen")
    if manifest.get("run_id") != run_id:
        raise DiscoveryError("runtime manifest run_id mismatch")
    proposal = manifest.get("proposal")
    receipt = manifest.get("approval_receipt")
    runtime = manifest.get("runtime")
    execution = manifest.get("execution")
    if not all(isinstance(value, dict) for value in (proposal, receipt, runtime, execution)):
        raise DiscoveryError("runtime manifest binding is incomplete")
    if not _same_path(proposal.get("path", ""), proposal_path):
        raise DiscoveryError("runtime manifest proposal path mismatch")
    if proposal.get("file_sha256") != proposal_file_sha256:
        raise DiscoveryError("runtime manifest proposal file SHA mismatch")
    if proposal.get("proposal_hash") != proposal_hash:
        raise DiscoveryError("runtime manifest proposal hash mismatch")
    if not _same_path(receipt.get("path", ""), receipt_path):
        raise DiscoveryError("runtime manifest receipt path mismatch")
    if receipt.get("file_sha256") != receipt_file_sha256:
        raise DiscoveryError("runtime manifest receipt file SHA mismatch")
    if receipt.get("receipt_hash") != receipt_hash:
        raise DiscoveryError("runtime manifest receipt hash mismatch")

    module_path = repo_root / "trading_mvp" / "src" / Path(__file__).name
    launcher_path = (
        repo_root / "tools" / "start_funding_unrestricted_metadata_discovery_visible.ps1"
    )
    if not _same_path(runtime.get("module_path", ""), module_path):
        raise DiscoveryError("runtime manifest module path mismatch")
    _verify_file_hash(module_path, str(runtime.get("module_sha256") or ""), "runtime module")
    if not _same_path(runtime.get("launcher_path", ""), launcher_path):
        raise DiscoveryError("runtime manifest launcher path mismatch")
    _verify_file_hash(
        launcher_path,
        str(runtime.get("launcher_sha256") or ""),
        "visible launcher",
    )
    if not _same_path(execution.get("output_path", ""), output_path):
        raise DiscoveryError("runtime manifest output path mismatch")
    if not _same_path(
        execution.get("failure_diagnostic_path", ""),
        failure_diagnostic_path,
    ):
        raise DiscoveryError("runtime manifest failure diagnostic path mismatch")
    if execution.get("endpoint_urls") != list(ENDPOINTS):
        raise DiscoveryError("runtime manifest endpoint URLs changed")
    if execution.get("max_runtime_sec") != 300:
        raise DiscoveryError("runtime manifest runtime limit changed")
    if execution.get("hard_output_cap_bytes") != 50_000_000:
        raise DiscoveryError("runtime manifest output cap changed")
    if execution.get("maximum_total_http_requests") != 4:
        raise DiscoveryError("runtime manifest request limit changed")
    if execution.get("maximum_attempts_per_endpoint") != 2:
        raise DiscoveryError("runtime manifest attempt limit changed")
    minimum = int(execution.get("minimum_active_contracts_per_venue") or 0)
    if minimum < 50:
        raise DiscoveryError("runtime manifest completeness threshold is too low")
    if execution.get("raw_response_persistence_allowed") is not False:
        raise DiscoveryError("runtime manifest unexpectedly allows raw responses")
    if execution.get("funding_rates_or_prices_persisted_allowed") is not False:
        raise DiscoveryError("runtime manifest unexpectedly allows market values")
    if execution.get("sanitized_failure_diagnostic_required") is not True:
        raise DiscoveryError("runtime manifest no longer requires safe diagnostics")
    if execution.get("failure_diagnostic_max_bytes") != FAILURE_DIAGNOSTIC_MAX_BYTES:
        raise DiscoveryError("runtime manifest diagnostic byte cap changed")
    if execution.get("free_form_failure_text_persistence_allowed") is not False:
        raise DiscoveryError("runtime manifest allows free-form failure text")
    return minimum


def _validate_execution_artifacts_full(
    *,
    repo_root: str | Path,
    proposal_path: str | Path,
    expected_proposal_file_sha256: str,
    expected_proposal_hash: str,
    receipt_path: str | Path,
    runtime_manifest_path: str | Path,
    output_path: str | Path,
    run_id: str,
) -> ValidatedArtifacts:
    root = Path(repo_root).expanduser().resolve()
    proposal_target = Path(proposal_path).expanduser().resolve()
    receipt_target = Path(receipt_path).expanduser().resolve()
    runtime_manifest_target = Path(runtime_manifest_path).expanduser().resolve()
    requested_output = Path(output_path).expanduser().resolve()
    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise DiscoveryError("run_id contains unsafe characters")
    failure_diagnostic_path = validate_failure_diagnostic_path(
        root,
        run_id,
        root
        / "docs"
        / "agent-log"
        / "run-gates"
        / f"{run_id}.runtime-failure.json",
    )

    proposal_file_sha256 = _verify_file_hash(
        proposal_target,
        expected_proposal_file_sha256,
        "proposal",
    )
    proposal = _load_json_object(proposal_target, "proposal")
    proposal_hash = _verify_embedded_hash(
        proposal,
        field="proposal_hash",
        label="proposal",
    )
    if proposal_hash != expected_proposal_hash:
        raise DiscoveryError("proposal canonical hash does not match approval")
    _validate_proposal(
        proposal,
        expected_file_sha256=proposal_file_sha256,
        expected_hash=proposal_hash,
    )

    receipt = _load_json_object(receipt_target, "approval receipt")
    receipt_hash = _verify_embedded_hash(
        receipt,
        field="receipt_hash",
        label="approval receipt",
    )
    receipt_file_sha256 = _sha256_file(receipt_target)
    bound_output = _validate_receipt(
        receipt,
        proposal_path=proposal_target,
        proposal_file_sha256=proposal_file_sha256,
        proposal_hash=proposal_hash,
        run_id=run_id,
        failure_diagnostic_path=failure_diagnostic_path,
    )
    if not _same_path(requested_output, bound_output):
        raise DiscoveryError("requested output does not match the approval receipt")

    runtime_manifest = _load_json_object(runtime_manifest_target, "runtime manifest")
    runtime_manifest_hash = _verify_embedded_hash(
        runtime_manifest,
        field="manifest_hash",
        label="runtime manifest",
    )
    runtime_manifest_file_sha256 = _sha256_file(runtime_manifest_target)
    minimum = _validate_runtime_manifest(
        runtime_manifest,
        repo_root=root,
        proposal_path=proposal_target,
        proposal_file_sha256=proposal_file_sha256,
        proposal_hash=proposal_hash,
        receipt_path=receipt_target,
        receipt_file_sha256=receipt_file_sha256,
        receipt_hash=receipt_hash,
        run_id=run_id,
        output_path=bound_output,
        failure_diagnostic_path=failure_diagnostic_path,
    )
    return ValidatedArtifacts(
        proposal=proposal,
        proposal_file_sha256=proposal_file_sha256,
        proposal_hash=proposal_hash,
        receipt=receipt,
        receipt_file_sha256=receipt_file_sha256,
        receipt_hash=receipt_hash,
        runtime_manifest=runtime_manifest,
        runtime_manifest_file_sha256=runtime_manifest_file_sha256,
        runtime_manifest_hash=runtime_manifest_hash,
        output_path=bound_output,
        minimum_active_contracts_per_venue=minimum,
    )


def validate_execution_artifacts(**kwargs: Any) -> dict[str, Any]:
    artifacts = _validate_execution_artifacts_full(**kwargs)
    output_status = "ABSENT_READY_FOR_SINGLE_USE"
    status = "PREFLIGHT_OK_NO_NETWORK"
    if artifacts.output_path.exists():
        manifest_path = artifacts.output_path / "manifest.json"
        manifest = _load_json_object(manifest_path, "existing output manifest")
        if (
            manifest.get("schema")
            != "trading_mvp_funding_unrestricted_metadata_discovery_output_v1"
            or manifest.get("status") != COMPLETE_STATUS
            or manifest.get("run_id") != kwargs.get("run_id")
            or manifest.get("bindings", {}).get("proposal_hash")
            != artifacts.proposal_hash
            or manifest.get("bindings", {}).get("receipt_hash")
            != artifacts.receipt_hash
            or manifest.get("bindings", {}).get("runtime_manifest_hash")
            != artifacts.runtime_manifest_hash
        ):
            raise DiscoveryError("existing output is not the exact immutable completion")
        output_status = "EXACT_IMMUTABLE_COMPLETION_EXISTS"
        status = "ALREADY_COMPLETE_IMMUTABLE_NO_NETWORK"
    return {
        "schema": "trading_mvp_funding_metadata_discovery_preflight_v1",
        "status": status,
        "run_id": kwargs.get("run_id"),
        "proposal_hash": artifacts.proposal_hash,
        "proposal_file_sha256": artifacts.proposal_file_sha256,
        "receipt_hash": artifacts.receipt_hash,
        "receipt_file_sha256": artifacts.receipt_file_sha256,
        "runtime_manifest_hash": artifacts.runtime_manifest_hash,
        "runtime_manifest_file_sha256": artifacts.runtime_manifest_file_sha256,
        "output_path": str(artifacts.output_path),
        "output_status": output_status,
        "network_requested": False,
        "http_requests_made": 0,
    }


def execute_discovery(
    *,
    artifacts: ValidatedArtifacts,
    claim_path: str | Path,
    owner_pid: int,
    ownership_token: str,
    run_id: str,
) -> dict[str, Any]:
    if artifacts.output_path.exists():
        raise DiscoveryError(
            "single-use immutable output already exists",
            diagnostic=_failure_context(
                category="BINDING_VALIDATION",
                stage="BINDING_VALIDATION",
                request_count=0,
            ),
        )
    try:
        verify_global_writer_claim(
            claim_path,
            run_id=run_id,
            owner_pid=owner_pid,
            ownership_token=ownership_token,
        )
    except DiscoveryError as exc:
        raise DiscoveryError(
            "global writer claim validation failed",
            diagnostic=_failure_context(
                category="WRITER_CLAIM",
                stage="WRITER_CLAIM",
                request_count=0,
            ),
        ) from exc
    started_at_utc = _utc_now()
    started_monotonic = time.monotonic()
    deadline = started_monotonic + 300.0
    client = BoundedMetadataClient(deadline_monotonic=deadline)

    mexc_payload, mexc_evidence = client.fetch(MEXC_ENDPOINT)
    gate_payload, gate_evidence = client.fetch(GATEIO_ENDPOINT)
    try:
        mexc_records = project_mexc_active_contracts(mexc_payload)
        gate_records = project_gateio_active_contracts(gate_payload)
        candidates = build_provisional_ticker_candidates(mexc_records, gate_records)
    except DiscoveryError as exc:
        raise DiscoveryError(
            "contract metadata projection failed",
            diagnostic=_failure_context(
                category="CONTRACT_METADATA_VALIDATION",
                stage="CONTRACT_PROJECTION",
                request_count=client.request_count,
            ),
        ) from exc
    finished_monotonic = time.monotonic()
    duration = finished_monotonic - started_monotonic
    if duration > 300.0 or finished_monotonic > deadline:
        raise DiscoveryError(
            "runtime exceeded 300 seconds before output commit",
            diagnostic=_failure_context(
                category="RUNTIME_DEADLINE",
                stage="RUNTIME_DEADLINE",
                request_count=client.request_count,
            ),
        )
    finished_at_utc = _utc_now()

    try:
        manifest = write_immutable_discovery(
            artifacts.output_path,
            run_id=run_id,
            mexc_records=mexc_records,
            gateio_records=gate_records,
            provisional_candidates=candidates,
            endpoint_evidence={"mexc": mexc_evidence, "gateio": gate_evidence},
            bindings={
                "proposal_path": str(
                    Path(artifacts.receipt["proposal"]["path"]).resolve()
                ),
                "proposal_file_sha256": artifacts.proposal_file_sha256,
                "proposal_hash": artifacts.proposal_hash,
                "receipt_file_sha256": artifacts.receipt_file_sha256,
                "receipt_hash": artifacts.receipt_hash,
                "runtime_manifest_file_sha256": artifacts.runtime_manifest_file_sha256,
                "runtime_manifest_hash": artifacts.runtime_manifest_hash,
            },
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            duration_sec=duration,
            request_count=client.request_count,
            hard_output_cap_bytes=50_000_000,
            minimum_active_contracts_per_venue=(
                artifacts.minimum_active_contracts_per_venue
            ),
        )
    except (DiscoveryError, OSError) as exc:
        raise DiscoveryError(
            "immutable output commit failed",
            diagnostic=_failure_context(
                category="OUTPUT_COMMIT",
                stage="OUTPUT_COMMIT",
                exception_type=(
                    "DISCOVERY_ERROR" if isinstance(exc, DiscoveryError) else "OS_ERROR"
                ),
                request_count=client.request_count,
            ),
        ) from exc
    return {
        "schema": "trading_mvp_funding_metadata_discovery_execution_v1",
        "status": COMPLETE_STATUS,
        "run_id": run_id,
        "output_path": str(artifacts.output_path),
        "request_count": client.request_count,
        "contract_counts": manifest["contract_counts"],
        "duration_sec": manifest["duration_sec"],
        "network_scope": "PUBLIC_CONTRACT_METADATA_ONLY",
        "raw_response_persisted": False,
        "funding_rates_or_prices_persisted": False,
        "next_checkpoint": manifest["next_checkpoint"],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the exact unrestricted funding metadata discovery."
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--proposal-path", required=True)
    parser.add_argument("--expected-proposal-file-sha256", required=True)
    parser.add_argument("--expected-proposal-hash", required=True)
    parser.add_argument("--receipt-path", required=True)
    parser.add_argument("--runtime-manifest-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--run-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--validate-failure-diagnostic-only", action="store_true")
    parser.add_argument("--global-writer-claim-path")
    parser.add_argument("--owner-pid", type=int)
    parser.add_argument("--ownership-token")
    parser.add_argument("--failure-diagnostic-path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    failure_diagnostic_path: Path | None = None
    common = {
        "repo_root": args.repo_root,
        "proposal_path": args.proposal_path,
        "expected_proposal_file_sha256": args.expected_proposal_file_sha256,
        "expected_proposal_hash": args.expected_proposal_hash,
        "receipt_path": args.receipt_path,
        "runtime_manifest_path": args.runtime_manifest_path,
        "output_path": args.output_path,
        "run_id": args.run_id,
    }
    try:
        if args.validate_failure_diagnostic_only:
            if not args.failure_diagnostic_path:
                raise DiscoveryError("failure diagnostic validation requires its path")
            failure_diagnostic_path = validate_failure_diagnostic_path(
                args.repo_root,
                args.run_id,
                args.failure_diagnostic_path,
            )
            record = read_failure_diagnostic(
                failure_diagnostic_path,
                expected_run_id=args.run_id,
                expected_proposal_hash=args.expected_proposal_hash,
            )
            result = {
                "schema": "trading_mvp_funding_metadata_failure_validation_v2",
                "status": "VALIDATED_ALLOWLISTED_FAILURE",
                "run_id": args.run_id,
                "failure_hash": record["failure_hash"],
                "failure": record["failure"],
                "raw_payload_persisted": False,
                "funding_rates_persisted": False,
                "prices_persisted": False,
                "retry_authorized": False,
            }
        elif args.preflight_only:
            result = validate_execution_artifacts(**common)
        else:
            if not args.failure_diagnostic_path:
                raise DiscoveryError("execute requires the failure diagnostic path")
            failure_diagnostic_path = validate_failure_diagnostic_path(
                args.repo_root,
                args.run_id,
                args.failure_diagnostic_path,
            )
            if failure_diagnostic_path.exists():
                raise DiscoveryError(
                    "failure diagnostic already exists; single-use run is terminal",
                    diagnostic=_failure_context(
                        category="BINDING_VALIDATION",
                        stage="BINDING_VALIDATION",
                        request_count=0,
                    ),
                )
            if not args.global_writer_claim_path:
                raise DiscoveryError("execute requires the global writer claim path")
            if not args.owner_pid or args.owner_pid <= 0:
                raise DiscoveryError("execute requires a positive owner PID")
            if re.fullmatch(r"[0-9a-f]{32}", str(args.ownership_token or "")) is None:
                raise DiscoveryError("execute requires the exact ownership token")
            artifacts = _validate_execution_artifacts_full(**common)
            result = execute_discovery(
                artifacts=artifacts,
                claim_path=args.global_writer_claim_path,
                owner_pid=args.owner_pid,
                ownership_token=args.ownership_token,
                run_id=args.run_id,
            )
    except Exception as exc:
        diagnostic = (
            exc.diagnostic
            if isinstance(exc, DiscoveryError) and exc.diagnostic
            else _failure_context(
                category=(
                    "BINDING_VALIDATION"
                    if isinstance(exc, DiscoveryError)
                    else "INTERNAL_ERROR"
                ),
                stage=(
                    "BINDING_VALIDATION"
                    if isinstance(exc, DiscoveryError)
                    else "INTERNAL"
                ),
                exception_type=(
                    "DISCOVERY_ERROR" if isinstance(exc, DiscoveryError) else "OTHER"
                ),
                request_count=0,
            )
        )
        diagnostic_record = None
        diagnostic_write_status = "NOT_REQUESTED_PREFLIGHT"
        if args.execute and failure_diagnostic_path is not None:
            try:
                diagnostic_record = write_failure_diagnostic(
                    failure_diagnostic_path,
                    build_failure_diagnostic_record(
                        run_id=args.run_id,
                        expected_proposal_hash=args.expected_proposal_hash,
                        diagnostic=diagnostic,
                    ),
                )
                diagnostic_write_status = "IMMUTABLE_SANITIZED_FAILURE_WRITTEN"
            except Exception:
                diagnostic_write_status = "FAILURE_DIAGNOSTIC_WRITE_FAILED_CLOSED"
        print(
            json.dumps(
                {
                    "schema": "trading_mvp_funding_metadata_discovery_error_v2",
                    "status": "STOPPED_INCOMPLETE",
                    "run_id": args.run_id,
                    "failure": _sanitize_failure_diagnostic(diagnostic),
                    "failure_hash": (
                        diagnostic_record.get("failure_hash")
                        if isinstance(diagnostic_record, dict)
                        else None
                    ),
                    "diagnostic_write_status": diagnostic_write_status,
                    "raw_payload_persisted": False,
                    "funding_rates_persisted": False,
                    "prices_persisted": False,
                    "retry_authorized": False,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
