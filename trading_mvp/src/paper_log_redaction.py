from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from paper_secret_provider import SecretHandle, SecretLease


REDACTION_SCHEMA = "trading_mvp_paper_log_redaction_guard_v1"
REDACTED = "[REDACTED]"
_NORMALIZE_KEY = re.compile(r"[^a-z0-9]+")
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_KEY_PATTERN = re.compile(
    r"(?i)\b(sk[-_][A-Za-z0-9_-]{12,}|(?:api[-_]?key|secret|signature)\s*[:=]\s*[^\s,;]+)"
)
_SENSITIVE_KEYS = {
    "apikey",
    "apisecret",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "key",
    "passphrase",
    "password",
    "privatekey",
    "secret",
    "setcookie",
    "sign",
    "signature",
    "token",
    "xgatechannelid",
    "xgateexptime",
    "xmexcapikey",
}


def _key_token(value: object) -> str:
    return _NORMALIZE_KEY.sub("", str(value).strip().casefold())


def is_sensitive_key(value: object) -> bool:
    token = _key_token(value)
    return (
        token in _SENSITIVE_KEYS
        or token.endswith("apikey")
        or token.endswith("apisecret")
        or token.endswith("signature")
        or token.endswith("password")
        or token.endswith("passphrase")
        or token.endswith("authorization")
    )


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _redact_inline(value)
    if not parsed.scheme or not parsed.netloc:
        return _redact_inline(value)
    query = [
        (key, REDACTED if is_sensitive_key(key) else _redact_inline(raw))
        for key, raw in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    username = parsed.username
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    if username is not None:
        netloc = f"{REDACTED}@{hostname}{port}"
    else:
        netloc = parsed.netloc
    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def _redact_inline(value: str) -> str:
    redacted = _BEARER_PATTERN.sub(lambda match: f"{match.group(1)} {REDACTED}", value)
    return _PRIVATE_KEY_PATTERN.sub(REDACTED, redacted)


def sanitize_for_log(value: Any) -> Any:
    if isinstance(value, SecretLease):
        raise ValueError("SecretLease cannot be serialized or logged")
    if isinstance(value, SecretHandle):
        return value.to_public_dict()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("raw byte material cannot be serialized or logged")
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, raw in value.items():
            rendered_key = str(key)
            sanitized[rendered_key] = (
                REDACTED if is_sensitive_key(rendered_key) else sanitize_for_log(raw)
            )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_for_log(item) for item in value]
    if isinstance(value, str):
        return redact_url(value) if "://" in value else _redact_inline(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"unsupported log value type: {type(value).__name__}")


def safe_json_dumps(value: Any) -> str:
    return json.dumps(
        sanitize_for_log(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def guard_capabilities() -> dict[str, object]:
    return {
        "schema": REDACTION_SCHEMA,
        "status": "DETERMINISTIC_REDACTION_GUARD_READY",
        "headers": True,
        "query_parameters": True,
        "payload_fields": True,
        "inline_authorization": True,
        "secret_handle_public_projection": True,
        "secret_lease_serialization": False,
        "raw_bytes_serialization": False,
        "network_access": False,
        "live_orders": False,
        "private_clients": False,
    }
