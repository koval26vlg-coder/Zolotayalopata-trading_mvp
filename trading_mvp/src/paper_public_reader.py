from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from paper_public_reader_contract import (
    authorize_public_get,
    sha256_file,
    sha256_json,
    validate_public_reader_contract,
)
from paper_log_redaction import sanitize_for_log


SNAPSHOT_SCHEMA = "trading_mvp_public_market_snapshot_v1"
REPORT_SCHEMA = "trading_mvp_paper_public_reader_fixture_report_v1"
RETRY_REPORT_SCHEMA = (
    "trading_mvp_paper_public_retry_rate_limit_fixture_report_v1"
)
MAX_RETRY_AFTER_SEC = 60.0


class PublicReaderError(RuntimeError):
    def __init__(self, category: str, endpoint_id: str, message: str) -> None:
        super().__init__(f"{category}:{endpoint_id}:{message}")
        self.category = category
        self.endpoint_id = endpoint_id
        self.detail = message


class FixtureTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class FixtureOutcome:
    status_code: int = 200
    payload: Any = None
    error: str | None = None
    headers: Mapping[str, str] | None = None


@dataclass
class FixtureClock:
    now_ms: int = 0

    def __post_init__(self) -> None:
        self.sleep_calls_ms: list[int] = []

    def sleep_ms(self, delay_ms: int) -> None:
        if isinstance(delay_ms, bool) or not isinstance(delay_ms, int):
            raise TypeError("fixture delay must be an integer number of milliseconds")
        if delay_ms < 0:
            raise ValueError("fixture delay cannot be negative")
        self.sleep_calls_ms.append(delay_ms)
        self.now_ms += delay_ms


class ReaderClock(Protocol):
    @property
    def now_ms(self) -> int:
        ...

    def sleep_ms(self, delay_ms: int) -> None:
        ...


class SystemClock:
    def __init__(
        self,
        *,
        wall_time_sec: Callable[[], float] = time.time,
        sleep_sec: Callable[[float], None] = time.sleep,
    ) -> None:
        self._wall_time_sec = wall_time_sec
        self._sleep_sec = sleep_sec
        self._last_now_ms = int(float(self._wall_time_sec()) * 1000.0)

    @property
    def now_ms(self) -> int:
        observed = int(float(self._wall_time_sec()) * 1000.0)
        self._last_now_ms = max(self._last_now_ms, observed)
        return self._last_now_ms

    def sleep_ms(self, delay_ms: int) -> None:
        if isinstance(delay_ms, bool) or not isinstance(delay_ms, int):
            raise TypeError("delay must be an integer number of milliseconds")
        if delay_ms < 0:
            raise ValueError("delay cannot be negative")
        self._sleep_sec(delay_ms / 1000.0)


class DeterministicTokenBucket:
    def __init__(
        self,
        *,
        requests_per_sec: float,
        burst: int,
        start_ms: int,
    ) -> None:
        if not math.isfinite(requests_per_sec) or requests_per_sec <= 0:
            raise ValueError("requests_per_sec must be finite and positive")
        if isinstance(burst, bool) or not isinstance(burst, int) or burst <= 0:
            raise ValueError("burst must be a positive integer")
        self.requests_per_sec = float(requests_per_sec)
        self.capacity = int(burst)
        self.tokens = float(burst)
        self.last_refill_ms = int(start_ms)

    def acquire(self, clock: ReaderClock) -> int:
        if clock.now_ms < self.last_refill_ms:
            raise ValueError("fixture clock moved backwards")
        elapsed_ms = clock.now_ms - self.last_refill_ms
        self.tokens = min(
            float(self.capacity),
            self.tokens + elapsed_ms * self.requests_per_sec / 1000.0,
        )
        self.last_refill_ms = clock.now_ms
        wait_ms = 0
        if self.tokens < 1.0:
            wait_ms = int(
                math.ceil(
                    (1.0 - self.tokens) * 1000.0 / self.requests_per_sec
                )
            )
            clock.sleep_ms(wait_ms)
            self.tokens = min(
                float(self.capacity),
                self.tokens + wait_ms * self.requests_per_sec / 1000.0,
            )
            self.last_refill_ms = clock.now_ms
        self.tokens = max(0.0, self.tokens - 1.0)
        return wait_ms


class PublicGetTransport(Protocol):
    network_capable: bool

    def get(
        self,
        *,
        authorization: Mapping[str, Any],
        url: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        connect_timeout_sec: float,
        read_timeout_sec: float,
    ) -> tuple[int, Any]:
        ...


class FixturePublicGetTransport:
    network_capable = False

    def __init__(
        self,
        outcomes: Mapping[
            str, FixtureOutcome | Sequence[FixtureOutcome]
        ],
    ) -> None:
        self._outcomes: dict[str, tuple[FixtureOutcome, ...]] = {}
        for endpoint_id, configured in outcomes.items():
            if isinstance(configured, FixtureOutcome):
                sequence = (configured,)
            else:
                sequence = tuple(configured)
                if not sequence or not all(
                    isinstance(item, FixtureOutcome) for item in sequence
                ):
                    raise ValueError(
                        f"{endpoint_id} fixture outcomes must be non-empty"
                    )
            self._outcomes[str(endpoint_id)] = sequence
        self._attempts: dict[str, int] = {}
        self.last_response_headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        *,
        authorization: Mapping[str, Any],
        url: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        connect_timeout_sec: float,
        read_timeout_sec: float,
    ) -> tuple[int, Any]:
        endpoint_id = str(authorization["endpoint_id"])
        self.calls.append(
            {
                "endpoint_id": endpoint_id,
                "url": url,
                "params": copy.deepcopy(dict(params)),
                "headers": sorted(str(key).lower() for key in headers),
                "connect_timeout_sec": connect_timeout_sec,
                "read_timeout_sec": read_timeout_sec,
            }
        )
        outcomes = self._outcomes.get(endpoint_id)
        if outcomes is None:
            raise PublicReaderError(
                "fixture_missing", endpoint_id, "fixture outcome is missing"
            )
        attempt_index = self._attempts.get(endpoint_id, 0)
        self._attempts[endpoint_id] = attempt_index + 1
        outcome = outcomes[min(attempt_index, len(outcomes) - 1)]
        self.last_response_headers = {
            str(key).lower(): str(value)
            for key, value in dict(outcome.headers or {}).items()
        }
        if outcome.error == "timeout":
            raise FixtureTimeoutError(endpoint_id)
        if outcome.error:
            raise OSError(outcome.error)
        return int(outcome.status_code), copy.deepcopy(outcome.payload)


class RequestsPublicGetTransport:
    network_capable = True

    def __init__(
        self,
        contract: Mapping[str, Any],
        *,
        session: Any | None = None,
    ) -> None:
        self.contract = validate_public_reader_contract(contract)
        if session is None:
            import requests

            session = requests.Session()
            self._timeout_errors = (requests.Timeout, TimeoutError)
            self._request_errors = (requests.RequestException, OSError)
        else:
            self._timeout_errors = (TimeoutError,)
            self._request_errors = (OSError,)
        self.session = session
        self.session.trust_env = False
        if hasattr(self.session, "auth"):
            self.session.auth = None
        if hasattr(self.session, "headers"):
            self.session.headers.clear()
            self.session.headers.update(
                {"User-Agent": "trading-mvp-public-reader/1"}
            )
        if hasattr(self.session, "cookies"):
            self.session.cookies.clear()
        self.last_response_headers: dict[str, str] = {}
        self.safe_calls: list[dict[str, Any]] = []
        self.network_requests = 0

    def get(
        self,
        *,
        authorization: Mapping[str, Any],
        url: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        connect_timeout_sec: float,
        read_timeout_sec: float,
    ) -> tuple[int, Any]:
        venue = str(authorization.get("venue") or "")
        observed_authorization = authorize_public_get(
            self.contract,
            venue=venue,
            method="GET",
            url=url,
            params=params,
            headers=headers,
        )
        if dict(authorization) != observed_authorization:
            raise ValueError("public GET authorization does not match request")
        endpoint_id = str(observed_authorization["endpoint_id"])
        safe_call = sanitize_for_log(
            {
                "endpoint_id": endpoint_id,
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "connect_timeout_sec": connect_timeout_sec,
                "read_timeout_sec": read_timeout_sec,
            }
        )
        if bool(getattr(self.session, "network_capable", True)):
            self.network_requests += 1
        try:
            response = self.session.get(
                url,
                params=dict(params),
                headers=dict(headers),
                timeout=(float(connect_timeout_sec), float(read_timeout_sec)),
                allow_redirects=False,
                verify=True,
                stream=True,
            )
        except self._timeout_errors as exc:
            raise FixtureTimeoutError(endpoint_id) from exc
        except self._request_errors as exc:
            raise OSError(f"public GET transport failed: {type(exc).__name__}") from exc
        self.safe_calls.append(dict(safe_call))
        try:
            self.last_response_headers = {
                str(key).lower(): str(value)
                for key, value in dict(response.headers or {}).items()
            }
            maximum_bytes = int(
                self.contract["transport_policy"]["response_max_bytes"]
            )
            content_length = self.last_response_headers.get("content-length")
            if content_length:
                try:
                    declared_bytes = int(content_length)
                except ValueError as exc:
                    raise PublicReaderError(
                        "invalid_response",
                        endpoint_id,
                        "Content-Length is invalid",
                    ) from exc
                if declared_bytes > maximum_bytes:
                    raise PublicReaderError(
                        "response_too_large",
                        endpoint_id,
                        f"declared bytes exceed {maximum_bytes}",
                    )
            chunks: list[bytes] = []
            total_bytes = 0
            for chunk in response.iter_content(chunk_size=65_536):
                if not chunk:
                    continue
                if not isinstance(chunk, bytes):
                    raise PublicReaderError(
                        "invalid_response",
                        endpoint_id,
                        "response chunk is not bytes",
                    )
                total_bytes += len(chunk)
                if total_bytes > maximum_bytes:
                    raise PublicReaderError(
                        "response_too_large",
                        endpoint_id,
                        f"streamed bytes exceed {maximum_bytes}",
                    )
                chunks.append(chunk)
            raw = b"".join(chunks)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PublicReaderError(
                    "schema_mismatch",
                    endpoint_id,
                    "response is not valid UTF-8 JSON",
                ) from exc
            return int(response.status_code), payload
        finally:
            response.close()


class FixtureRequestsResponse:
    def __init__(
        self,
        *,
        status_code: int,
        body: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = int(status_code)
        self.body = bytes(body)
        self.headers = dict(headers or {})
        self.closed = False

    def iter_content(self, *, chunk_size: int) -> Sequence[bytes]:
        return [
            self.body[offset : offset + chunk_size]
            for offset in range(0, len(self.body), chunk_size)
        ]

    def close(self) -> None:
        self.closed = True


class FixtureRequestsSession:
    network_capable = False

    def __init__(self, responses: Sequence[FixtureRequestsResponse]) -> None:
        if not responses:
            raise ValueError("fixture requests session requires responses")
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.trust_env = True
        self.auth: Any = "must-be-cleared"
        self.headers: dict[str, str] = {"Authorization": "must-be-cleared"}
        self.cookies: dict[str, str] = {"session": "must-be-cleared"}

    def get(self, url: str, **kwargs: Any) -> FixtureRequestsResponse:
        self.calls.append({"url": url, **copy.deepcopy(kwargs)})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def _retry_after_ms(
    headers: Mapping[str, str],
    *,
    now_ms: int,
    maximum_sec: float = MAX_RETRY_AFTER_SEC,
) -> int | None:
    raw = next(
        (
            str(value).strip()
            for key, value in headers.items()
            if str(key).strip().lower() == "retry-after"
        ),
        "",
    )
    if not raw:
        return None
    delay_sec: float
    try:
        delay_sec = float(raw)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Retry-After is neither seconds nor an HTTP date") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delay_sec = (
            parsed.astimezone(timezone.utc).timestamp() - now_ms / 1000.0
        )
    if not math.isfinite(delay_sec):
        raise ValueError("Retry-After must be finite")
    bounded_sec = min(max(delay_sec, 0.0), float(maximum_sec))
    return int(math.ceil(bounded_sec * 1000.0))


def _finite_positive(value: Any, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{field} must be finite and positive")
    return result


def _finite_optional(value: Any, *, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _epoch_ms(value: Any, *, field: str) -> int:
    numeric = _finite_positive(value, field=field)
    if numeric < 10_000_000_000:
        numeric *= 1000.0
    return int(numeric)


def _validate_required(mapping: Mapping[str, Any], names: Sequence[str]) -> None:
    missing = [name for name in names if name not in mapping]
    if missing:
        raise ValueError(f"missing required fields: {','.join(missing)}")


def _validate_response_schema(payload: Any, descriptor: Mapping[str, Any]) -> None:
    schema = descriptor["response_schema"]
    root = schema.get("root")
    if root == "object":
        if not isinstance(payload, Mapping):
            raise ValueError("response root must be an object")
        _validate_required(payload, schema.get("required") or [])
        candidate: Any = payload.get("data", payload)
        data_kind = schema.get("data")
        if data_kind == "array" and not isinstance(candidate, list):
            raise ValueError("response data must be an array")
        if data_kind == "object" and not isinstance(candidate, Mapping):
            raise ValueError("response data must be an object")
    elif root == "array":
        if not isinstance(payload, list):
            raise ValueError("response root must be an array")
        candidate = payload
    else:
        raise ValueError("unsupported response root schema")
    required = schema.get("item_required") or []
    if required:
        items = candidate if isinstance(candidate, list) else [candidate]
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError("response item must be an object")
            _validate_required(item, required)
    if schema.get("level_required"):
        if not isinstance(candidate, Mapping):
            raise ValueError("order-book response must be an object")
        for side in ("bids", "asks"):
            levels = candidate.get(side)
            if not isinstance(levels, list):
                raise ValueError(f"order-book {side} must be an array")
            for level in levels:
                if not isinstance(level, Mapping):
                    raise ValueError("order-book level must be an object")
                _validate_required(level, schema["level_required"])


def _find_endpoint(contract: Mapping[str, Any], venue: str, endpoint_id: str) -> dict[str, Any]:
    for endpoint in contract["venues"][venue]["endpoints"]:
        if endpoint["endpoint_id"] == endpoint_id:
            return endpoint
    raise ValueError(f"endpoint is absent from contract: {endpoint_id}")


def _normalize_depth(
    venue: str, payload: Any
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    source = payload.get("data") if venue == "mexc" else payload
    if not isinstance(source, Mapping):
        raise ValueError("depth payload is invalid")

    def convert(side: str) -> list[dict[str, float]]:
        levels = source.get(side)
        if not isinstance(levels, list) or not levels:
            raise ValueError(f"depth {side} is empty")
        normalized: list[dict[str, float]] = []
        for level in levels:
            if venue == "mexc":
                if not isinstance(level, list) or len(level) < 2:
                    raise ValueError("MEXC depth level is invalid")
                price, quantity = level[0], level[1]
            else:
                if not isinstance(level, Mapping):
                    raise ValueError("Gate depth level is invalid")
                price, quantity = level.get("p"), level.get("s")
            normalized.append(
                {
                    "price": _finite_positive(price, field=f"{side}.price"),
                    "quantity": _finite_positive(
                        quantity, field=f"{side}.quantity"
                    ),
                }
            )
        return normalized

    return convert("bids"), convert("asks")


class PublicMarketReader:
    def __init__(
        self,
        contract: Mapping[str, Any],
        transport: PublicGetTransport,
        *,
        clock: ReaderClock,
    ) -> None:
        self.contract = validate_public_reader_contract(contract)
        self.transport = transport
        self.clock = clock
        self._rate_limiters: dict[str, DeterministicTokenBucket] = {}
        self.rate_limit_trace: list[dict[str, Any]] = []
        self.retry_trace: list[dict[str, Any]] = []

    def _rate_limiter(self, venue: str) -> DeterministicTokenBucket:
        limiter = self._rate_limiters.get(venue)
        if limiter is None:
            rate_limit = self.contract["venues"][venue]["rate_limit"]
            limiter = DeterministicTokenBucket(
                requests_per_sec=float(rate_limit["requests_per_sec"]),
                burst=int(rate_limit["burst"]),
                start_ms=self.clock.now_ms,
            )
            self._rate_limiters[venue] = limiter
        return limiter

    def _wait_before_retry(
        self,
        *,
        venue: str,
        endpoint_id: str,
        attempt: int,
        retry_backoff_sec: Sequence[Any],
        response_headers: Mapping[str, str] | None,
        reason: str,
    ) -> None:
        backoff_ms = int(
            math.ceil(float(retry_backoff_sec[attempt - 1]) * 1000.0)
        )
        retry_after_ms = _retry_after_ms(
            dict(response_headers or {}),
            now_ms=self.clock.now_ms,
        )
        delay_ms = max(backoff_ms, retry_after_ms or 0)
        self.retry_trace.append(
            {
                "venue": venue,
                "endpoint_id": endpoint_id,
                "attempt": attempt,
                "reason": reason,
                "backoff_ms": backoff_ms,
                "retry_after_ms": retry_after_ms,
                "applied_delay_ms": delay_ms,
            }
        )
        self.clock.sleep_ms(delay_ms)

    def _request(
        self,
        *,
        venue: str,
        endpoint_id: str,
        url: str,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        endpoint = _find_endpoint(self.contract, venue, endpoint_id)
        authorization = authorize_public_get(
            self.contract,
            venue=venue,
            method="GET",
            url=url,
            params=params,
            headers={"Accept": "application/json"},
        )
        timeout = self.contract["venues"][venue]["timeouts"]
        maximum_attempts = int(timeout["maximum_attempts"])
        retry_backoff_sec = tuple(timeout["retry_backoff_sec"])
        retry_statuses = {int(value) for value in timeout["retry_http_statuses"]}
        for attempt in range(1, maximum_attempts + 1):
            rate_wait_ms = self._rate_limiter(venue).acquire(self.clock)
            self.rate_limit_trace.append(
                {
                    "venue": venue,
                    "endpoint_id": endpoint_id,
                    "attempt": attempt,
                    "wait_ms": rate_wait_ms,
                    "clock_ms": self.clock.now_ms,
                }
            )
            try:
                status_code, payload = self.transport.get(
                    authorization=authorization,
                    url=url,
                    params=dict(params or {}),
                    headers={"Accept": "application/json"},
                    connect_timeout_sec=float(timeout["connect_sec"]),
                    read_timeout_sec=float(timeout["read_sec"]),
                )
            except FixtureTimeoutError as exc:
                if attempt >= maximum_attempts:
                    raise PublicReaderError(
                        "transport_timeout", endpoint_id, "fixture timeout"
                    ) from exc
                self._wait_before_retry(
                    venue=venue,
                    endpoint_id=endpoint_id,
                    attempt=attempt,
                    retry_backoff_sec=retry_backoff_sec,
                    response_headers=None,
                    reason="transport_timeout",
                )
                continue
            except PublicReaderError:
                raise
            except OSError as exc:
                if attempt >= maximum_attempts:
                    raise PublicReaderError(
                        "transport_error", endpoint_id, str(exc)
                    ) from exc
                self._wait_before_retry(
                    venue=venue,
                    endpoint_id=endpoint_id,
                    attempt=attempt,
                    retry_backoff_sec=retry_backoff_sec,
                    response_headers=None,
                    reason="transport_error",
                )
                continue
            if 200 <= status_code < 300:
                break
            if status_code not in retry_statuses or attempt >= maximum_attempts:
                raise PublicReaderError(
                    "http_error", endpoint_id, f"HTTP {status_code}"
                )
            self._wait_before_retry(
                venue=venue,
                endpoint_id=endpoint_id,
                attempt=attempt,
                retry_backoff_sec=retry_backoff_sec,
                response_headers=getattr(
                    self.transport, "last_response_headers", {}
                ),
                reason=f"http_{status_code}",
            )
        else:
            raise AssertionError("retry loop exited without a response")
        try:
            _validate_response_schema(payload, endpoint)
        except ValueError as exc:
            raise PublicReaderError(
                "schema_mismatch", endpoint_id, str(exc)
            ) from exc
        return payload

    def read_market_snapshot(
        self,
        *,
        venue: str,
        symbol: str,
        canonical_base: str,
        observer_received_ts_ms: int,
        maximum_quote_age_ms: int = 5000,
    ) -> dict[str, Any]:
        venue_key = venue.strip().lower()
        if venue_key == "mexc":
            return self._read_mexc(
                symbol=symbol,
                canonical_base=canonical_base,
                observer_received_ts_ms=observer_received_ts_ms,
                maximum_quote_age_ms=maximum_quote_age_ms,
            )
        if venue_key == "gateio":
            return self._read_gate(
                symbol=symbol,
                canonical_base=canonical_base,
                observer_received_ts_ms=observer_received_ts_ms,
                maximum_quote_age_ms=maximum_quote_age_ms,
            )
        raise ValueError("venue is not allowlisted")

    def _read_mexc(
        self,
        *,
        symbol: str,
        canonical_base: str,
        observer_received_ts_ms: int,
        maximum_quote_age_ms: int,
    ) -> dict[str, Any]:
        base = self.contract["venues"]["mexc"]["base_url"]
        contracts = self._request(
            venue="mexc",
            endpoint_id="mexc_contracts",
            url=f"{base}/api/v1/contract/detail",
        )
        tickers = self._request(
            venue="mexc",
            endpoint_id="mexc_tickers",
            url=f"{base}/api/v1/contract/ticker",
        )
        funding = self._request(
            venue="mexc",
            endpoint_id="mexc_funding",
            url=f"{base}/api/v1/contract/funding_rate/{symbol}",
        )
        depth = self._request(
            venue="mexc",
            endpoint_id="mexc_depth",
            url=f"{base}/api/v1/contract/depth/{symbol}",
            params={"limit": 20},
        )
        contract_row = next(
            (
                item
                for item in contracts["data"]
                if str(item.get("symbol")) == symbol
            ),
            None,
        )
        ticker_row = next(
            (
                item
                for item in tickers["data"]
                if str(item.get("symbol")) == symbol
            ),
            None,
        )
        if contract_row is None or ticker_row is None:
            raise PublicReaderError(
                "schema_mismatch", "mexc_tickers", "symbol is missing"
            )
        funding_row = funding["data"]
        if self.contract["contract_id"] in {
            "paper_public_reader_contract_v2",
            "paper_public_reader_contract_v3",
        }:
            try:
                bid_depth, ask_depth = _normalize_depth("mexc", depth)
                bid = max(level["price"] for level in bid_depth)
                ask = min(level["price"] for level in ask_depth)
                depth_payload = depth.get("data")
                if not isinstance(depth_payload, Mapping):
                    raise ValueError("MEXC depth payload is invalid")
                observed_ts_ms = min(
                    _epoch_ms(
                        ticker_row["timestamp"],
                        field="mexc.ticker.timestamp",
                    ),
                    _epoch_ms(
                        depth_payload["timestamp"],
                        field="mexc.depth.timestamp",
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise PublicReaderError(
                    "schema_mismatch",
                    "mexc_depth",
                    str(exc),
                ) from exc
        else:
            bid = ticker_row["bid1"]
            ask = ticker_row["ask1"]
            observed_ts_ms = _epoch_ms(
                ticker_row["timestamp"], field="mexc.timestamp"
            )
        return self._assemble_snapshot(
            venue="mexc",
            symbol=symbol,
            canonical_base=canonical_base,
            observer_received_ts_ms=observer_received_ts_ms,
            observed_ts_ms=observed_ts_ms,
            maximum_quote_age_ms=maximum_quote_age_ms,
            bid=bid,
            ask=ask,
            mark=ticker_row["fairPrice"],
            index=ticker_row["indexPrice"],
            funding_rate=funding_row["fundingRate"],
            depth_payload=depth,
            contract_trading=(
                int(contract_row["state"]) == 0
                and contract_row.get("apiAllowed") is not False
            ),
            raw_payloads=[contracts, tickers, funding, depth],
        )

    def _read_gate(
        self,
        *,
        symbol: str,
        canonical_base: str,
        observer_received_ts_ms: int,
        maximum_quote_age_ms: int,
    ) -> dict[str, Any]:
        base = self.contract["venues"]["gateio"]["base_url"]
        contracts = self._request(
            venue="gateio",
            endpoint_id="gateio_contracts",
            url=f"{base}/futures/usdt/contracts",
        )
        tickers = self._request(
            venue="gateio",
            endpoint_id="gateio_tickers",
            url=f"{base}/futures/usdt/tickers",
            params={"contract": symbol},
        )
        funding = self._request(
            venue="gateio",
            endpoint_id="gateio_funding",
            url=f"{base}/futures/usdt/funding_rate",
            params={"contract": symbol, "limit": 1},
        )
        depth = self._request(
            venue="gateio",
            endpoint_id="gateio_depth",
            url=f"{base}/futures/usdt/order_book",
            params={"contract": symbol, "limit": 20},
        )
        contract_row = next(
            (item for item in contracts if str(item.get("name")) == symbol),
            None,
        )
        ticker_row = next(
            (item for item in tickers if str(item.get("contract")) == symbol),
            None,
        )
        if contract_row is None or ticker_row is None or not funding:
            raise PublicReaderError(
                "schema_mismatch", "gateio_tickers", "symbol is missing"
            )
        observed_ts_ms = _epoch_ms(
            depth.get("current"), field="gateio.current"
        )
        return self._assemble_snapshot(
            venue="gateio",
            symbol=symbol,
            canonical_base=canonical_base,
            observer_received_ts_ms=observer_received_ts_ms,
            observed_ts_ms=observed_ts_ms,
            maximum_quote_age_ms=maximum_quote_age_ms,
            bid=ticker_row["highest_bid"],
            ask=ticker_row["lowest_ask"],
            mark=ticker_row["mark_price"],
            index=ticker_row["index_price"],
            funding_rate=funding[0]["r"],
            depth_payload=depth,
            contract_trading=str(contract_row["status"]).lower() == "trading",
            raw_payloads=[contracts, tickers, funding, depth],
        )

    def _assemble_snapshot(
        self,
        *,
        venue: str,
        symbol: str,
        canonical_base: str,
        observer_received_ts_ms: int,
        observed_ts_ms: int,
        maximum_quote_age_ms: int,
        bid: Any,
        ask: Any,
        mark: Any,
        index: Any,
        funding_rate: Any,
        depth_payload: Any,
        contract_trading: bool,
        raw_payloads: list[Any],
    ) -> dict[str, Any]:
        quote_age_ms = observer_received_ts_ms - observed_ts_ms
        if quote_age_ms < 0:
            raise PublicReaderError(
                "schema_mismatch", f"{venue}_tickers", "quote is from the future"
            )
        if quote_age_ms > maximum_quote_age_ms:
            raise PublicReaderError(
                "stale_quote",
                f"{venue}_tickers",
                f"quote age {quote_age_ms}ms exceeds {maximum_quote_age_ms}ms",
            )
        try:
            best_bid = _finite_positive(bid, field="best_bid")
            best_ask = _finite_positive(ask, field="best_ask")
            mark_price = _finite_positive(mark, field="mark_price")
            index_price = _finite_positive(index, field="index_price")
            normalized_funding = _finite_optional(
                funding_rate, field="funding_rate"
            )
            bid_depth, ask_depth = _normalize_depth(venue, depth_payload)
        except ValueError as exc:
            raise PublicReaderError(
                "schema_mismatch", f"{venue}_normalization", str(exc)
            ) from exc
        if best_bid >= best_ask:
            raise PublicReaderError(
                "schema_mismatch",
                f"{venue}_normalization",
                "BBO is crossed or locked",
            )
        deterministic = {
            "schema": SNAPSHOT_SCHEMA,
            "venue": venue,
            "symbol": symbol,
            "canonical_base": canonical_base,
            "observer_received_ts_ms": int(observer_received_ts_ms),
            "observed_ts_ms": observed_ts_ms,
            "quote_age_ms": quote_age_ms,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mark_price": mark_price,
            "index_price": index_price,
            "funding_rate": normalized_funding,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "contract_trading": bool(contract_trading),
            "raw_payload_hash_sha256": sha256_json(raw_payloads),
            "network_request_performed": bool(
                getattr(self.transport, "network_requests", 0)
            ),
        }
        return {
            **deterministic,
            "snapshot_hash_sha256": sha256_json(deterministic),
        }


class FixturePublicMarketReader(PublicMarketReader):
    def __init__(
        self,
        contract: Mapping[str, Any],
        transport: PublicGetTransport,
        *,
        clock: FixtureClock | None = None,
    ) -> None:
        if bool(getattr(transport, "network_capable", True)):
            raise ValueError("fixture reader rejects network-capable transports")
        super().__init__(
            contract,
            transport,
            clock=clock or FixtureClock(),
        )


def build_runtime_public_market_reader(
    contract: Mapping[str, Any],
    *,
    session: Any | None = None,
    clock: ReaderClock | None = None,
) -> PublicMarketReader:
    validated = validate_public_reader_contract(contract)
    transport = RequestsPublicGetTransport(validated, session=session)
    return PublicMarketReader(
        validated,
        transport,
        clock=clock or SystemClock(),
    )


def _valid_fixture_outcomes(now_ms: int) -> dict[str, FixtureOutcome]:
    mexc_symbol = "HYPE_USDT"
    gate_symbol = "HYPE_USDT"
    return {
        "mexc_contracts": FixtureOutcome(
            payload={
                "success": True,
                "data": [
                    {
                        "symbol": mexc_symbol,
                        "baseCoin": "HYPE",
                        "quoteCoin": "USDT",
                        "state": 0,
                        "apiAllowed": True,
                    }
                ],
            }
        ),
        "mexc_tickers": FixtureOutcome(
            payload={
                "success": True,
                "data": [
                    {
                        "symbol": mexc_symbol,
                        "bid1": "10.00",
                        "ask1": "10.02",
                        "fairPrice": "10.01",
                        "indexPrice": "10.005",
                        "timestamp": now_ms - 1000,
                    }
                ],
            }
        ),
        "mexc_funding": FixtureOutcome(
            payload={
                "success": True,
                "data": {
                    "symbol": mexc_symbol,
                    "fundingRate": "0.0001",
                    "nextSettleTime": now_ms + 3_600_000,
                    "timestamp": now_ms - 1000,
                },
            }
        ),
        "mexc_depth": FixtureOutcome(
            payload={
                "success": True,
                "data": {
                    "bids": [["10.00", "100", 1], ["9.99", "200", 2]],
                    "asks": [["10.02", "110", 1], ["10.03", "220", 2]],
                    "timestamp": now_ms - 900,
                },
            }
        ),
        "gateio_contracts": FixtureOutcome(
            payload=[
                {
                    "name": gate_symbol,
                    "status": "trading",
                    "mark_price": "10.03",
                    "index_price": "10.005",
                    "funding_rate": "0.0002",
                }
            ]
        ),
        "gateio_tickers": FixtureOutcome(
            payload=[
                {
                    "contract": gate_symbol,
                    "highest_bid": "10.02",
                    "lowest_ask": "10.04",
                    "mark_price": "10.03",
                    "index_price": "10.005",
                    "funding_rate": "0.0002",
                }
            ]
        ),
        "gateio_funding": FixtureOutcome(
            payload=[{"t": int(now_ms / 1000), "r": "0.0002"}]
        ),
        "gateio_depth": FixtureOutcome(
            payload={
                "current": now_ms - 1200,
                "bids": [{"p": "10.02", "s": "100"}],
                "asks": [{"p": "10.04", "s": "100"}],
            }
        ),
    }


def build_fixture_validation_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    now_ms = 1_800_000_000_000
    successes: list[dict[str, Any]] = []
    failure_results: list[dict[str, str]] = []
    request_count = 0
    for venue in ("mexc", "gateio"):
        transport = FixturePublicGetTransport(_valid_fixture_outcomes(now_ms))
        reader = FixturePublicMarketReader(contract, transport)
        snapshot = reader.read_market_snapshot(
            venue=venue,
            symbol="HYPE_USDT",
            canonical_base="hype",
            observer_received_ts_ms=now_ms,
        )
        successes.append(
            {
                "venue": venue,
                "snapshot_hash_sha256": snapshot["snapshot_hash_sha256"],
                "quote_age_ms": snapshot["quote_age_ms"],
                "contract_trading": snapshot["contract_trading"],
            }
        )
        request_count += len(transport.calls)

    scenarios = [
        ("timeout", "mexc_tickers", FixtureOutcome(error="timeout"), "mexc", "transport_timeout"),
        ("http", "gateio_tickers", FixtureOutcome(status_code=503, payload={}), "gateio", "http_error"),
        (
            "schema",
            "mexc_tickers",
            FixtureOutcome(payload={"success": True, "data": [{"symbol": "HYPE_USDT"}]}),
            "mexc",
            "schema_mismatch",
        ),
        (
            "stale",
            "gateio_depth",
            FixtureOutcome(
                payload={
                    "current": now_ms - 10_000,
                    "bids": [{"p": "10.02", "s": "100"}],
                    "asks": [{"p": "10.04", "s": "100"}],
                }
            ),
            "gateio",
            "stale_quote",
        ),
    ]
    for scenario_id, endpoint_id, outcome, venue, expected_category in scenarios:
        outcomes = _valid_fixture_outcomes(now_ms)
        outcomes[endpoint_id] = outcome
        transport = FixturePublicGetTransport(outcomes)
        reader = FixturePublicMarketReader(contract, transport)
        try:
            reader.read_market_snapshot(
                venue=venue,
                symbol="HYPE_USDT",
                canonical_base="hype",
                observer_received_ts_ms=now_ms,
            )
        except PublicReaderError as exc:
            if exc.category != expected_category:
                raise AssertionError(
                    f"{scenario_id} expected {expected_category}, got {exc.category}"
                ) from exc
            failure_results.append(
                {
                    "scenario": scenario_id,
                    "expected_category": expected_category,
                    "observed_category": exc.category,
                }
            )
        else:
            raise AssertionError(f"{scenario_id} fixture did not fail")
        request_count += len(transport.calls)

    deterministic = {
        "schema": REPORT_SCHEMA,
        "task_id": "paper_public_reader_fixture_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "success_scenarios": successes,
        "failure_scenarios": failure_results,
        "success_count": len(successes),
        "failure_count": len(failure_results),
        "fixture_transport_calls": request_count,
        "network_requests": 0,
        "network_capable_transport": False,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": "FIXTURE_PUBLIC_READER_ACCEPTED_NO_NETWORK",
        "next_allowed_action": "paper_public_cache_idempotency_v1",
    }
    report = {
        **deterministic,
        "module_path": str(Path(__file__).resolve()),
        "module_sha256": sha256_file(Path(__file__).resolve()),
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_retry_rate_limit_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    now_ms = 1_800_000_000_000
    valid = _valid_fixture_outcomes(now_ms)["mexc_contracts"]
    scenarios: list[dict[str, Any]] = []
    total_transport_calls = 0

    rate_clock = FixtureClock()
    rate_transport = FixturePublicGetTransport({"mexc_contracts": valid})
    rate_reader = FixturePublicMarketReader(
        contract, rate_transport, clock=rate_clock
    )
    base_url = str(contract["venues"]["mexc"]["base_url"])
    for _ in range(6):
        rate_reader._request(
            venue="mexc",
            endpoint_id="mexc_contracts",
            url=f"{base_url}/api/v1/contract/detail",
        )
    rate_waits = [
        int(item["wait_ms"]) for item in rate_reader.rate_limit_trace
    ]
    if rate_waits != [0, 0, 0, 0, 0, 200]:
        raise AssertionError(
            f"unexpected deterministic token-bucket waits: {rate_waits}"
        )
    scenarios.append(
        {
            "scenario": "token_bucket_burst_then_refill",
            "transport_calls": len(rate_transport.calls),
            "waits_ms": rate_waits,
            "total_wait_ms": sum(rate_waits),
            "status": "ACCEPTED",
        }
    )
    total_transport_calls += len(rate_transport.calls)

    retry_cases = [
        {
            "scenario": "retry_503_then_success",
            "outcomes": [
                FixtureOutcome(status_code=503, payload={}),
                FixtureOutcome(status_code=503, payload={}),
                valid,
            ],
            "expected_waits_ms": [500, 1000],
        },
        {
            "scenario": "retry_after_429_then_success",
            "outcomes": [
                FixtureOutcome(
                    status_code=429,
                    payload={},
                    headers={"Retry-After": "2"},
                ),
                valid,
            ],
            "expected_waits_ms": [2000],
        },
        {
            "scenario": "timeout_then_success",
            "outcomes": [
                FixtureOutcome(error="timeout"),
                valid,
            ],
            "expected_waits_ms": [500],
        },
    ]
    for case in retry_cases:
        clock = FixtureClock()
        transport = FixturePublicGetTransport(
            {"mexc_contracts": case["outcomes"]}
        )
        reader = FixturePublicMarketReader(contract, transport, clock=clock)
        reader._request(
            venue="mexc",
            endpoint_id="mexc_contracts",
            url=f"{base_url}/api/v1/contract/detail",
        )
        waits = [
            int(item["applied_delay_ms"]) for item in reader.retry_trace
        ]
        if waits != case["expected_waits_ms"]:
            raise AssertionError(
                f"{case['scenario']} expected {case['expected_waits_ms']}, got {waits}"
            )
        scenarios.append(
            {
                "scenario": case["scenario"],
                "transport_calls": len(transport.calls),
                "retry_waits_ms": waits,
                "retry_trace": reader.retry_trace,
                "status": "ACCEPTED",
            }
        )
        total_transport_calls += len(transport.calls)

    bounded_clock = FixtureClock()
    bounded_transport = FixturePublicGetTransport(
        {"mexc_contracts": FixtureOutcome(status_code=503, payload={})}
    )
    bounded_reader = FixturePublicMarketReader(
        contract, bounded_transport, clock=bounded_clock
    )
    try:
        bounded_reader._request(
            venue="mexc",
            endpoint_id="mexc_contracts",
            url=f"{base_url}/api/v1/contract/detail",
        )
    except PublicReaderError as exc:
        if exc.category != "http_error":
            raise AssertionError(
                f"persistent 503 produced {exc.category}, expected http_error"
            ) from exc
    else:
        raise AssertionError("persistent 503 unexpectedly succeeded")
    expected_attempts = int(
        contract["venues"]["mexc"]["timeouts"]["maximum_attempts"]
    )
    if len(bounded_transport.calls) != expected_attempts:
        raise AssertionError("persistent retry exceeded or missed the attempt bound")
    scenarios.append(
        {
            "scenario": "persistent_503_stops_at_maximum_attempts",
            "transport_calls": len(bounded_transport.calls),
            "retry_waits_ms": [
                int(item["applied_delay_ms"])
                for item in bounded_reader.retry_trace
            ],
            "terminal_category": "http_error",
            "status": "ACCEPTED",
        }
    )
    total_transport_calls += len(bounded_transport.calls)

    no_retry_transport = FixturePublicGetTransport(
        {"mexc_contracts": FixtureOutcome(status_code=404, payload={})}
    )
    no_retry_reader = FixturePublicMarketReader(contract, no_retry_transport)
    try:
        no_retry_reader._request(
            venue="mexc",
            endpoint_id="mexc_contracts",
            url=f"{base_url}/api/v1/contract/detail",
        )
    except PublicReaderError as exc:
        if exc.category != "http_error":
            raise AssertionError(
                f"non-retryable 404 produced {exc.category}, expected http_error"
            ) from exc
    else:
        raise AssertionError("non-retryable 404 unexpectedly succeeded")
    if len(no_retry_transport.calls) != 1 or no_retry_reader.retry_trace:
        raise AssertionError("non-retryable status was retried")
    scenarios.append(
        {
            "scenario": "non_retryable_404_fails_once",
            "transport_calls": 1,
            "retry_waits_ms": [],
            "terminal_category": "http_error",
            "status": "ACCEPTED",
        }
    )
    total_transport_calls += 1

    deterministic = {
        "schema": RETRY_REPORT_SCHEMA,
        "task_id": "paper_public_retry_rate_limit_fixture_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "policy": {
            "mexc_rate_limit": contract["venues"]["mexc"]["rate_limit"],
            "mexc_timeouts": contract["venues"]["mexc"]["timeouts"],
            "maximum_retry_after_sec": MAX_RETRY_AFTER_SEC,
            "retry_after_rule": "max(frozen_backoff,retry_after)_capped",
        },
        "scenarios": scenarios,
        "scenario_count": len(scenarios),
        "accepted_scenario_count": sum(
            item["status"] == "ACCEPTED" for item in scenarios
        ),
        "fixture_transport_calls": total_transport_calls,
        "fixture_clock_only": True,
        "network_requests": 0,
        "network_capable_transport": False,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": "FIXTURE_RETRY_RATE_LIMIT_ACCEPTED_NO_NETWORK",
        "next_allowed_action": "paper_public_snapshot_observer_bridge_v1",
    }
    report = {
        **deterministic,
        "module_path": str(Path(__file__).resolve()),
        "module_sha256": sha256_file(Path(__file__).resolve()),
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_transport_adapter_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    url = "https://contract.mexc.com/api/v1/contract/detail"
    headers = {"Accept": "application/json"}
    authorization = authorize_public_get(
        contract,
        venue="mexc",
        method="GET",
        url=url,
        params={},
        headers=headers,
    )
    response = FixtureRequestsResponse(
        status_code=200,
        body=json.dumps({"success": True, "data": []}).encode("utf-8"),
        headers={"Retry-After": "2"},
    )
    session = FixtureRequestsSession([response])
    transport = RequestsPublicGetTransport(contract, session=session)
    status_code, payload = transport.get(
        authorization=authorization,
        url=url,
        params={},
        headers=headers,
        connect_timeout_sec=3.0,
        read_timeout_sec=7.0,
    )
    call = session.calls[0]
    if (
        status_code != 200
        or payload != {"success": True, "data": []}
        or call["allow_redirects"] is not False
        or call["verify"] is not True
        or call["stream"] is not True
        or call["timeout"] != (3.0, 7.0)
        or not response.closed
    ):
        raise AssertionError("fixture public transport request policy drift")
    if (
        session.trust_env is not False
        or session.auth is not None
        or session.cookies
        or set(key.lower() for key in session.headers) != {"user-agent"}
    ):
        raise AssertionError("fixture public session retained ambient authority")

    rejected: list[dict[str, Any]] = []
    rejection_cases = [
        (
            "private_header",
            {
                "authorization": authorization,
                "url": url,
                "params": {},
                "headers": {"Authorization": "Bearer fixture-secret"},
            },
        ),
        (
            "host_not_allowlisted",
            {
                "authorization": authorization,
                "url": "https://example.invalid/api/v1/contract/detail",
                "params": {},
                "headers": headers,
            },
        ),
    ]
    for scenario, request in rejection_cases:
        blocked_session = FixtureRequestsSession([response])
        blocked_transport = RequestsPublicGetTransport(
            contract, session=blocked_session
        )
        try:
            blocked_transport.get(
                **request,
                connect_timeout_sec=3.0,
                read_timeout_sec=7.0,
            )
        except ValueError as exc:
            rejected.append(
                {
                    "scenario": scenario,
                    "error": str(exc),
                    "session_calls": len(blocked_session.calls),
                }
            )
        else:
            raise AssertionError(f"{scenario} request was not rejected")
        if blocked_session.calls:
            raise AssertionError(f"{scenario} reached fixture session")

    maximum_bytes = int(
        contract["transport_policy"]["response_max_bytes"]
    )
    oversized_response = FixtureRequestsResponse(
        status_code=200,
        body=b"{}",
        headers={"Content-Length": str(maximum_bytes + 1)},
    )
    oversized_session = FixtureRequestsSession([oversized_response])
    oversized_transport = RequestsPublicGetTransport(
        contract, session=oversized_session
    )
    try:
        oversized_transport.get(
            authorization=authorization,
            url=url,
            params={},
            headers=headers,
            connect_timeout_sec=3.0,
            read_timeout_sec=7.0,
        )
    except PublicReaderError as exc:
        if exc.category != "response_too_large":
            raise AssertionError(
                f"oversized response produced {exc.category}"
            ) from exc
    else:
        raise AssertionError("oversized response was accepted")
    if not oversized_response.closed:
        raise AssertionError("oversized response was not closed")

    module_path = Path(__file__).resolve()
    redaction_path = Path(
        sys.modules[sanitize_for_log.__module__].__file__
    ).resolve()
    source_provenance = {
        "paper_public_reader": {
            "path": str(module_path),
            "file_sha256": sha256_file(module_path),
        },
        "paper_log_redaction": {
            "path": str(redaction_path),
            "file_sha256": sha256_file(redaction_path),
        },
    }
    deterministic = {
        "schema": "trading_mvp_paper_public_transport_adapter_fixture_v1",
        "task_id": "paper_public_transport_adapter_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "accepted_request": {
            "status_code": status_code,
            "allow_redirects": call["allow_redirects"],
            "verify_tls": call["verify"],
            "streaming": call["stream"],
            "timeouts_sec": list(call["timeout"]),
            "retry_after_header": transport.last_response_headers.get(
                "retry-after"
            ),
            "safe_call": transport.safe_calls[0],
        },
        "pre_network_rejections": rejected,
        "response_byte_limit": {
            "maximum_bytes": maximum_bytes,
            "declared_oversize_rejected": True,
            "response_closed": oversized_response.closed,
        },
        "session_guards": {
            "trust_env": session.trust_env,
            "ambient_auth": session.auth is not None,
            "ambient_cookies": bool(session.cookies),
            "persistent_header_names": sorted(
                key.lower() for key in session.headers
            ),
        },
        "fixture_session_calls": len(session.calls)
        + len(oversized_session.calls),
        "source_provenance": source_provenance,
        "network_requests": 0,
        "adapter_network_capable": True,
        "fixture_session_network_capable": False,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": "FIXTURE_PUBLIC_TRANSPORT_ADAPTER_ACCEPTED_NO_NETWORK",
        "next_allowed_action": "paper_product_readiness_audit_v4",
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_reader_transport_wiring_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    now_ms = 1_800_000_000_000
    outcomes = _valid_fixture_outcomes(now_ms)
    endpoint_order = (
        "mexc_contracts",
        "mexc_tickers",
        "mexc_funding",
        "mexc_depth",
        "gateio_contracts",
        "gateio_tickers",
        "gateio_funding",
        "gateio_depth",
    )
    responses = [
        FixtureRequestsResponse(
            status_code=outcomes[endpoint_id].status_code,
            body=json.dumps(
                outcomes[endpoint_id].payload,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        )
        for endpoint_id in endpoint_order
    ]
    session = FixtureRequestsSession(responses)
    transport = RequestsPublicGetTransport(contract, session=session)
    reader = PublicMarketReader(
        contract,
        transport,
        clock=FixtureClock(),
    )
    snapshots = [
        reader.read_market_snapshot(
            venue=venue,
            symbol="HYPE_USDT",
            canonical_base="hype",
            observer_received_ts_ms=now_ms,
        )
        for venue in ("mexc", "gateio")
    ]
    if len(session.calls) != len(endpoint_order):
        raise AssertionError("transport wiring did not execute every endpoint")
    if transport.network_requests != 0:
        raise AssertionError("fixture transport wiring performed network I/O")
    if any(item["network_request_performed"] for item in snapshots):
        raise AssertionError("fixture snapshot reported network I/O")
    observed_endpoint_ids = [
        str(call["endpoint_id"]) for call in transport.safe_calls
    ]
    if observed_endpoint_ids != list(endpoint_order):
        raise AssertionError("transport wiring endpoint order drifted")
    if any(not response.closed for response in responses):
        raise AssertionError("transport wiring left a response open")

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": (
            "trading_mvp_paper_public_reader_transport_wiring_fixture_v1"
        ),
        "task_id": "paper_public_reader_transport_wiring_fixture_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "normalized_snapshots": [
            {
                "venue": snapshot["venue"],
                "schema": snapshot["schema"],
                "snapshot_hash_sha256": snapshot["snapshot_hash_sha256"],
                "quote_age_ms": snapshot["quote_age_ms"],
                "contract_trading": snapshot["contract_trading"],
                "network_request_performed": snapshot[
                    "network_request_performed"
                ],
            }
            for snapshot in snapshots
        ],
        "endpoint_order": list(endpoint_order),
        "safe_transport_calls": transport.safe_calls,
        "fixture_session_calls": len(session.calls),
        "responses_closed": all(response.closed for response in responses),
        "source_provenance": {
            "paper_public_reader": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "network_requests": transport.network_requests,
        "private_api_keys": False,
        "live_orders": False,
        "oms_mutations": 0,
        "verdict": (
            "FIXTURE_PUBLIC_READER_TRANSPORT_WIRING_ACCEPTED_NO_NETWORK"
        ),
        "next_allowed_action": (
            "paper_public_streaming_byte_limit_fixture_v1"
        ),
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_streaming_byte_limit_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    maximum_bytes = int(
        contract["transport_policy"]["response_max_bytes"]
    )
    url = "https://contract.mexc.com/api/v1/contract/detail"
    headers = {"Accept": "application/json"}
    authorization = authorize_public_get(
        contract,
        venue="mexc",
        method="GET",
        url=url,
        params={},
        headers=headers,
    )
    response = FixtureRequestsResponse(
        status_code=200,
        body=b"x" * (maximum_bytes + 1),
    )
    session = FixtureRequestsSession([response])
    transport = RequestsPublicGetTransport(contract, session=session)
    observed_category = ""
    try:
        transport.get(
            authorization=authorization,
            url=url,
            params={},
            headers=headers,
            connect_timeout_sec=3.0,
            read_timeout_sec=7.0,
        )
    except PublicReaderError as exc:
        observed_category = exc.category
    else:
        raise AssertionError("streamed oversized response was accepted")
    if observed_category != "response_too_large":
        raise AssertionError(
            f"streamed byte limit produced {observed_category}"
        )
    if not response.closed:
        raise AssertionError("streamed oversized response was not closed")
    if transport.network_requests != 0:
        raise AssertionError("streaming fixture performed network I/O")

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": (
            "trading_mvp_paper_public_streaming_byte_limit_fixture_v1"
        ),
        "task_id": "paper_public_streaming_byte_limit_fixture_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "scenario": {
            "content_length_present": False,
            "maximum_bytes": maximum_bytes,
            "streamed_bytes": maximum_bytes + 1,
            "observed_category": observed_category,
            "response_closed": response.closed,
            "safe_transport_call": transport.safe_calls[0],
        },
        "source_provenance": {
            "paper_public_reader": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "fixture_session_calls": len(session.calls),
        "network_requests": transport.network_requests,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": (
            "FIXTURE_PUBLIC_STREAMING_BYTE_LIMIT_ACCEPTED_NO_NETWORK"
        ),
        "next_allowed_action": (
            "paper_public_health_contract_binding_fixture_v1"
        ),
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_system_clock_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    state = {"now_ms": 1_800_000_000_000}
    sleep_calls_sec: list[float] = []

    def fake_wall_time() -> float:
        return state["now_ms"] / 1000.0

    def fake_sleep(delay_sec: float) -> None:
        sleep_calls_sec.append(float(delay_sec))
        state["now_ms"] += int(round(delay_sec * 1000.0))

    clock = SystemClock(
        wall_time_sec=fake_wall_time,
        sleep_sec=fake_sleep,
    )
    initial_ms = clock.now_ms
    clock.sleep_ms(250)
    after_direct_sleep_ms = clock.now_ms
    state["now_ms"] -= 100
    clamped_ms = clock.now_ms
    state["now_ms"] = after_direct_sleep_ms
    bucket = DeterministicTokenBucket(
        requests_per_sec=2.0,
        burst=1,
        start_ms=clock.now_ms,
    )
    first_wait_ms = bucket.acquire(clock)
    second_wait_ms = bucket.acquire(clock)
    retry_after_ms = _retry_after_ms(
        {"Retry-After": "2"},
        now_ms=clock.now_ms,
    )
    if (
        after_direct_sleep_ms - initial_ms != 250
        or clamped_ms != after_direct_sleep_ms
        or first_wait_ms != 0
        or second_wait_ms != 500
        or retry_after_ms != 2000
    ):
        raise AssertionError("system clock fixture behavior drifted")

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": "trading_mvp_paper_public_system_clock_fixture_v1",
        "task_id": "paper_public_system_clock_fixture_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "clock": {
            "initial_ms": initial_ms,
            "after_direct_sleep_ms": after_direct_sleep_ms,
            "backward_wall_clock_clamped_ms": clamped_ms,
            "sleep_calls_sec": sleep_calls_sec,
        },
        "token_bucket": {
            "requests_per_sec": 2.0,
            "burst": 1,
            "first_wait_ms": first_wait_ms,
            "second_wait_ms": second_wait_ms,
        },
        "retry_after_ms": retry_after_ms,
        "source_provenance": {
            "paper_public_reader": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "network_requests": 0,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": "FIXTURE_PUBLIC_SYSTEM_CLOCK_ACCEPTED_NO_NETWORK",
        "next_allowed_action": (
            "paper_public_transport_retry_wiring_fixture_v2"
        ),
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_transport_retry_wiring_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    now_ms = 1_800_000_000_000
    outcomes = _valid_fixture_outcomes(now_ms)
    endpoint_order = (
        "mexc_contracts",
        "mexc_contracts",
        "mexc_tickers",
        "mexc_funding",
        "mexc_depth",
    )
    responses = [
        FixtureRequestsResponse(
            status_code=503,
            body=b"{}",
            headers={"Retry-After": "1"},
        ),
        *[
            FixtureRequestsResponse(
                status_code=outcomes[endpoint_id].status_code,
                body=json.dumps(
                    outcomes[endpoint_id].payload,
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8"),
            )
            for endpoint_id in endpoint_order[1:]
        ],
    ]
    session = FixtureRequestsSession(responses)
    transport = RequestsPublicGetTransport(contract, session=session)
    clock = FixtureClock()
    reader = PublicMarketReader(contract, transport, clock=clock)
    snapshot = reader.read_market_snapshot(
        venue="mexc",
        symbol="HYPE_USDT",
        canonical_base="hype",
        observer_received_ts_ms=now_ms,
    )
    observed_endpoint_ids = [
        str(call["endpoint_id"]) for call in transport.safe_calls
    ]
    if observed_endpoint_ids != list(endpoint_order):
        raise AssertionError("retry wiring endpoint order drifted")
    if len(reader.retry_trace) != 1:
        raise AssertionError("retry wiring did not perform one bounded retry")
    retry = reader.retry_trace[0]
    if (
        retry["reason"] != "http_503"
        or retry["retry_after_ms"] != 1000
        or retry["applied_delay_ms"] != 1000
    ):
        raise AssertionError("retry wiring delay policy drifted")
    if transport.network_requests != 0:
        raise AssertionError("retry wiring fixture performed network I/O")
    if any(not response.closed for response in responses):
        raise AssertionError("retry wiring left a response open")

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": (
            "trading_mvp_paper_public_transport_retry_wiring_fixture_v2"
        ),
        "task_id": "paper_public_transport_retry_wiring_fixture_v2",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "endpoint_order": list(endpoint_order),
        "retry_trace": reader.retry_trace,
        "rate_limit_trace": reader.rate_limit_trace,
        "clock_sleep_calls_ms": clock.sleep_calls_ms,
        "normalized_snapshot": {
            "venue": snapshot["venue"],
            "snapshot_hash_sha256": snapshot["snapshot_hash_sha256"],
            "network_request_performed": snapshot[
                "network_request_performed"
            ],
        },
        "fixture_session_calls": len(session.calls),
        "responses_closed": all(response.closed for response in responses),
        "source_provenance": {
            "paper_public_reader": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "network_requests": transport.network_requests,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": (
            "FIXTURE_PUBLIC_TRANSPORT_RETRY_WIRING_ACCEPTED_NO_NETWORK"
        ),
        "next_allowed_action": (
            "paper_public_cache_transport_integration_fixture_v1"
        ),
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_runtime_reader_factory_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    now_ms = 1_800_000_000_000
    outcomes = _valid_fixture_outcomes(now_ms)
    endpoint_order = (
        "mexc_contracts",
        "mexc_tickers",
        "mexc_funding",
        "mexc_depth",
        "gateio_contracts",
        "gateio_tickers",
        "gateio_funding",
        "gateio_depth",
    )
    responses = [
        FixtureRequestsResponse(
            status_code=outcomes[endpoint_id].status_code,
            body=json.dumps(
                outcomes[endpoint_id].payload,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        )
        for endpoint_id in endpoint_order
    ]
    session = FixtureRequestsSession(responses)
    fake_state = {"now_ms": now_ms}

    def fake_time() -> float:
        return fake_state["now_ms"] / 1000.0

    def fake_sleep(delay_sec: float) -> None:
        fake_state["now_ms"] += int(round(delay_sec * 1000.0))

    clock = SystemClock(
        wall_time_sec=fake_time,
        sleep_sec=fake_sleep,
    )
    reader = build_runtime_public_market_reader(
        contract,
        session=session,
        clock=clock,
    )
    snapshots = [
        reader.read_market_snapshot(
            venue=venue,
            symbol="HYPE_USDT",
            canonical_base="hype",
            observer_received_ts_ms=now_ms,
        )
        for venue in ("mexc", "gateio")
    ]
    transport = reader.transport
    if not isinstance(transport, RequestsPublicGetTransport):
        raise AssertionError("runtime reader factory transport drifted")
    if not isinstance(reader.clock, SystemClock):
        raise AssertionError("runtime reader factory clock drifted")
    if transport.network_requests != 0:
        raise AssertionError("runtime reader factory fixture used network")
    if any(not response.closed for response in responses):
        raise AssertionError("runtime reader factory left a response open")

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": (
            "trading_mvp_paper_public_runtime_reader_factory_fixture_v1"
        ),
        "task_id": "paper_public_runtime_reader_factory_fixture_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "factory": {
            "reader_type": type(reader).__name__,
            "transport_type": type(transport).__name__,
            "clock_type": type(reader.clock).__name__,
        },
        "endpoint_order": [
            str(call["endpoint_id"]) for call in transport.safe_calls
        ],
        "normalized_snapshots": [
            {
                "venue": snapshot["venue"],
                "snapshot_hash_sha256": snapshot[
                    "snapshot_hash_sha256"
                ],
                "network_request_performed": snapshot[
                    "network_request_performed"
                ],
            }
            for snapshot in snapshots
        ],
        "fixture_session_calls": len(session.calls),
        "responses_closed": all(response.closed for response in responses),
        "source_provenance": {
            "paper_public_reader": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "network_requests": transport.network_requests,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": (
            "FIXTURE_PUBLIC_RUNTIME_READER_FACTORY_ACCEPTED_NO_NETWORK"
        ),
        "next_allowed_action": (
            "paper_public_endpoint_contract_parity_fixture_v1"
        ),
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_endpoint_contract_parity_fixture_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    symbol = "HYPE_USDT"
    request_specs = {
        "mexc_contracts": (
            "mexc",
            "/api/v1/contract/detail",
            {},
            "contracts",
        ),
        "mexc_tickers": (
            "mexc",
            "/api/v1/contract/ticker",
            {},
            "ticker",
        ),
        "mexc_funding": (
            "mexc",
            f"/api/v1/contract/funding_rate/{symbol}",
            {},
            "funding",
        ),
        "mexc_depth": (
            "mexc",
            f"/api/v1/contract/depth/{symbol}",
            {"limit": 20},
            "depth",
        ),
        "gateio_contracts": (
            "gateio",
            "/futures/usdt/contracts",
            {},
            "contracts",
        ),
        "gateio_tickers": (
            "gateio",
            "/futures/usdt/tickers",
            {"contract": symbol},
            "ticker",
        ),
        "gateio_funding": (
            "gateio",
            "/futures/usdt/funding_rate",
            {"contract": symbol, "limit": 1},
            "funding",
        ),
        "gateio_depth": (
            "gateio",
            "/futures/usdt/order_book",
            {"contract": symbol, "limit": 20},
            "depth",
        ),
    }
    now_ms = 1_800_000_000_000
    outcomes = _valid_fixture_outcomes(now_ms)
    parity_rows: list[dict[str, Any]] = []
    for endpoint_id, (
        venue,
        path,
        params,
        normalizer_role,
    ) in request_specs.items():
        url = f"{contract['venues'][venue]['base_url']}{path}"
        authorization = authorize_public_get(
            contract,
            venue=venue,
            method="GET",
            url=url,
            params=params,
            headers={"Accept": "application/json"},
        )
        if authorization["endpoint_id"] != endpoint_id:
            raise AssertionError(
                f"{endpoint_id} mapped to {authorization['endpoint_id']}"
            )
        endpoint = _find_endpoint(contract, venue, endpoint_id)
        _validate_response_schema(outcomes[endpoint_id].payload, endpoint)
        parity_rows.append(
            {
                "endpoint_id": endpoint_id,
                "venue": venue,
                "path": path,
                "query_names": sorted(params),
                "schema_hash_sha256": endpoint["schema_hash_sha256"],
                "normalizer_role": normalizer_role,
                "authorization": authorization,
                "fixture_schema_valid": True,
            }
        )

    snapshots: list[dict[str, Any]] = []
    total_fixture_calls = 0
    for venue in ("mexc", "gateio"):
        transport = FixturePublicGetTransport(outcomes)
        reader = FixturePublicMarketReader(contract, transport)
        snapshot = reader.read_market_snapshot(
            venue=venue,
            symbol=symbol,
            canonical_base="hype",
            observer_received_ts_ms=now_ms,
        )
        snapshots.append(
            {
                "venue": venue,
                "snapshot_hash_sha256": snapshot[
                    "snapshot_hash_sha256"
                ],
            }
        )
        total_fixture_calls += len(transport.calls)
    if len(parity_rows) != 8 or total_fixture_calls != 8:
        raise AssertionError("endpoint parity coverage is incomplete")

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": (
            "trading_mvp_paper_public_endpoint_contract_parity_fixture_v1"
        ),
        "task_id": "paper_public_endpoint_contract_parity_fixture_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "endpoint_parity": parity_rows,
        "endpoint_count": len(parity_rows),
        "venue_counts": {
            venue: sum(row["venue"] == venue for row in parity_rows)
            for venue in ("mexc", "gateio")
        },
        "normalizer_roles": sorted(
            {row["normalizer_role"] for row in parity_rows}
        ),
        "normalized_snapshots": snapshots,
        "fixture_transport_calls": total_fixture_calls,
        "source_provenance": {
            "paper_public_reader": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "network_requests": 0,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": (
            "FIXTURE_PUBLIC_ENDPOINT_CONTRACT_PARITY_ACCEPTED_NO_NETWORK"
        ),
        "next_allowed_action": "paper_public_readonly_probe_plan_v1",
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


def build_public_readonly_probe_plan(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    contract_version = str(contract["contract_id"]).rsplit("_", maxsplit=1)[-1]
    duration_sec = 120
    interval_sec = 5
    max_cycles = duration_sec // interval_sec
    endpoint_ids = {
        venue: [
            str(endpoint["endpoint_id"])
            for endpoint in contract["venues"][venue]["endpoints"]
        ]
        for venue in ("mexc", "gateio")
    }
    deterministic = {
        "schema": (
            f"trading_mvp_paper_public_readonly_probe_plan_{contract_version}"
        ),
        "task_id": f"paper_public_readonly_probe_plan_{contract_version}",
        "status": {
            "v1": "PLAN_ONLY_NOT_AUTHORIZED_FOR_NETWORK",
            "v2": "PLAN_ONLY_STANDING_AUTHORIZATION_REQUIRED",
            "v3": "PLAN_ONLY_ONE_TIME_CRITICAL_AUTHORIZATION_REQUIRED",
        }[contract_version],
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "probe": {
            "venues": ["mexc", "gateio"],
            "symbol": "HYPE_USDT",
            "canonical_base": "hype",
            "fixture_identity_only": True,
            "duration_sec": duration_sec,
            "snapshot_interval_sec": interval_sec,
            "max_cycles": max_cycles,
            "max_runtime_sec": 180,
            "endpoint_ids": endpoint_ids,
            "planned_endpoint_reads": (
                max_cycles
                * sum(len(values) for values in endpoint_ids.values())
            ),
            "maximum_public_get_attempts": max_cycles
            * sum(
                len(endpoint_ids[venue])
                * int(
                    contract["venues"][venue]["timeouts"][
                        "maximum_attempts"
                    ]
                )
                for venue in ("mexc", "gateio")
            ),
            "visible_terminal_required": True,
            "output_namespace": (
                r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot"
                r"\public-readonly-probe-runs"
            ),
        },
        "failure_policy": {
            "schema_mismatch": "STOPPED_INCOMPLETE",
            "persistent_stale_quotes": "STOPPED_INCOMPLETE",
            "application_error_rate_above_5_percent": "STOPPED_INCOMPLETE",
            "timeout": "BOUNDED_RETRY_THEN_STOPPED_INCOMPLETE",
            "partial_output": "NEVER_ACCEPTED",
        },
        "authorization": {
            "network_authorized": False,
            "execution_authorized": False,
            "automatic_start": False,
            "requires_new_guard_decision": contract_version == "v1",
            **(
                {
                    "requires_standing_authorization": True,
                    "automatic_start_with_valid_standing_authorization": True,
                }
                if contract_version == "v2"
                else {}
            ),
            **(
                {
                    "requires_standing_limits": True,
                    "requires_one_time_v3_critical_authorization": True,
                    "automatic_start_with_valid_v3_critical_authorization": True,
                }
                if contract_version == "v3"
                else {}
            ),
            "requires_visible_terminal": True,
        },
        "safety": {
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
        "verdict": {
            "v1": "PUBLIC_READONLY_PROBE_PLAN_FROZEN_NOT_AUTHORIZED",
            "v2": (
                "PUBLIC_READONLY_PROBE_PLAN_V2_FROZEN_"
                "REQUIRES_STANDING_AUTHORIZATION"
            ),
            "v3": (
                "PUBLIC_READONLY_PROBE_PLAN_V3_FROZEN_"
                "REQUIRES_ONE_TIME_CRITICAL_AUTHORIZATION"
            ),
        }[contract_version],
        "next_allowed_action": {
            "v1": "paper_product_readiness_audit_v7",
            "v2": "authorize_public_readonly_probe_plan_under_standing_policy",
            "v3": "create_v3_one_time_critical_authorization",
        }[contract_version],
    }
    if contract_version == "v2":
        deterministic["compatibility_scope"] = {
            "change": "mexc_bbo_source_ticker_to_depth_l1",
            "existing_hosts_and_endpoint_ids_only": True,
            "normalized_output_schema_changed": False,
            "venue_universe_signal_cost_risk_changed": False,
            "hypothesis_changed": False,
        }
    elif contract_version == "v3":
        deterministic["probe"]["maximum_quote_age_ms_by_venue"] = {
            "mexc": 6000,
            "gateio": 5000,
        }
        migration = contract["migration_evidence"]
        deterministic["compatibility_scope"] = {
            "change": "venue_specific_quote_freshness_mexc_5000_to_6000_ms",
            "source_v2_plan_hash_sha256": migration[
                "source_failure_audit"
            ]["plan_hash_sha256"],
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
        }
    plan = {
        **deterministic,
        "plan_hash_sha256": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, plan)
    return plan


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
    parser = argparse.ArgumentParser(
        description="Validate the public market-reader against fixtures only"
    )
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--report-kind",
        choices=(
            "reader",
            "retry-rate-limit",
            "transport-adapter",
            "transport-wiring",
            "streaming-byte-limit",
            "system-clock",
            "transport-retry-wiring",
            "runtime-reader-factory",
            "endpoint-contract-parity",
            "readonly-probe-plan",
        ),
        default="reader",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    builders = {
        "reader": build_fixture_validation_report,
        "retry-rate-limit": build_retry_rate_limit_fixture_report,
        "transport-adapter": build_public_transport_adapter_fixture_report,
        "transport-wiring": (
            build_public_reader_transport_wiring_fixture_report
        ),
        "streaming-byte-limit": (
            build_public_streaming_byte_limit_fixture_report
        ),
        "system-clock": build_public_system_clock_fixture_report,
        "transport-retry-wiring": (
            build_public_transport_retry_wiring_fixture_report
        ),
        "runtime-reader-factory": (
            build_public_runtime_reader_factory_fixture_report
        ),
        "endpoint-contract-parity": (
            build_public_endpoint_contract_parity_fixture_report
        ),
        "readonly-probe-plan": build_public_readonly_probe_plan,
    }
    builder = builders[args.report_kind]
    report = builder(contract_path=args.contract, output_path=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
