from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import requests


PLAN_SCHEMA = "trading_mvp_canonical_asset_registry_plan_v1"
RESULT_SCHEMA = "trading_mvp_canonical_asset_registry_result_v1"
SOURCE_URL = "https://api.coingecko.com/api/v3/coins/list"
SOURCE_STATUSES = ("active", "inactive")
CREDENTIAL_ENV = "COINGECKO_DEMO_API_KEY"
MAX_ALLOWED_RUNTIME_SEC = 300
DEFAULT_MAX_RUNTIME_SEC = 60
MAX_ALLOWED_RESPONSE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
DEFAULT_MINIMUM_ROWS = 1_000
HASH_CHARACTERS = frozenset("0123456789abcdef")


class MissingCredentialError(RuntimeError):
    pass


class RegistrySchemaError(ValueError):
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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_without_hash(
    payload: Mapping[str, Any],
    *,
    hash_key: str,
    volatile_keys: Sequence[str] = (),
) -> dict[str, Any]:
    excluded = {hash_key, *volatile_keys}
    return {key: value for key, value in payload.items() if key not in excluded}


def _read_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {source}")
    return payload


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


def _write_json_immutable(path: Path, payload: Mapping[str, Any]) -> None:
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
    _write_bytes_immutable(path, content)


def _validate_sha256(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(character not in HASH_CHARACTERS for character in digest):
        raise ValueError(f"invalid {label}")
    return digest


def build_canonical_registry_plan(
    registry_output_path: str | Path,
    manifest_output_path: str | Path,
    *,
    frozen_at_utc: str | None = None,
    minimum_rows: int = DEFAULT_MINIMUM_ROWS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_runtime_sec: int = DEFAULT_MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    if minimum_rows < 1:
        raise ValueError("minimum_rows must be positive")
    if not 1 <= max_runtime_sec <= MAX_ALLOWED_RUNTIME_SEC:
        raise ValueError(
            f"max_runtime_sec must be between 1 and {MAX_ALLOWED_RUNTIME_SEC}"
        )
    if not 1 <= max_response_bytes <= MAX_ALLOWED_RESPONSE_BYTES:
        raise ValueError(
            f"max_response_bytes must be between 1 and {MAX_ALLOWED_RESPONSE_BYTES}"
        )

    registry_path = Path(registry_output_path).expanduser().resolve()
    manifest_path = Path(manifest_output_path).expanduser().resolve()
    if registry_path == manifest_path:
        raise ValueError("registry and manifest paths must be different")

    module_path = Path(__file__).resolve()
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_at_utc": frozen_at_utc or _utc_now(),
        "source": {
            "provider": "CoinGecko",
            "base_tier": "Demo API",
            "url": SOURCE_URL,
            "method": "GET",
            "statuses": list(SOURCE_STATUSES),
            "include_platform": True,
            "pagination": False,
            "response_scope": "all_supported_coins_active_and_inactive",
            "authentication": {
                "location": "header",
                "header_name": "x-cg-demo-api-key",
                "credential_env": CREDENTIAL_ENV,
                "query_auth_forbidden": True,
            },
        },
        "identity": {
            "canonical_prefix": "coingecko:",
            "symbol_normalization": "strip_and_uppercase",
            "preserve_symbol_collisions": True,
            "exchange_filtering": False,
            "binance_filtering": False,
            "historical_membership_inference": False,
            "contract_addresses_retained": True,
        },
        "minimum_rows": int(minimum_rows),
        "limits": {
            "max_runtime_sec": int(max_runtime_sec),
            "max_response_bytes_per_status": int(max_response_bytes),
            "request_count": len(SOURCE_STATUSES),
        },
        "outputs": {
            "registry_jsonl_path": str(registry_path),
            "manifest_json_path": str(manifest_path),
            "immutable": True,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
        },
        "data_access_audit": {
            "market_prices_read": False,
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "exchange_membership_filtered": False,
        },
        "prohibited": [
            "exchange_filtering",
            "binance_current_snapshot_as_historical_identity",
            "symbol_collision_autoresolution",
            "returns",
            "pnl",
            "signals",
            "grid_search",
            "oos",
            "live_orders",
            "private_exchange_api_keys",
        ],
        "decision": "CANONICAL_REGISTRY_PLAN_READY_AWAITING_VISIBLE_COLLECT",
        "next_allowed_command": "canonical-registry-collect-visible",
    }
    plan["plan_hash"] = sha256_json(
        _payload_without_hash(plan, hash_key="plan_hash")
    )
    return plan


def validate_canonical_registry_plan(path: str | Path) -> dict[str, Any]:
    plan = _read_json_object(path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unexpected canonical registry plan schema")
    stored_hash = _validate_sha256(plan.get("plan_hash"), label="plan_hash")
    computed_hash = sha256_json(_payload_without_hash(plan, hash_key="plan_hash"))
    if stored_hash != computed_hash:
        raise ValueError("plan hash mismatch")
    if plan.get("mode") != "PlanOnly" or plan.get("research_only") is not True:
        raise ValueError("canonical registry plan must remain research-only PlanOnly")

    source = plan.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("source contract is missing")
    if (
        source.get("url") != SOURCE_URL
        or source.get("method") != "GET"
        or source.get("statuses") != list(SOURCE_STATUSES)
        or source.get("include_platform") is not True
        or source.get("pagination") is not False
    ):
        raise ValueError("source contract mismatch")
    auth = source.get("authentication")
    if not isinstance(auth, Mapping) or auth != {
        "location": "header",
        "header_name": "x-cg-demo-api-key",
        "credential_env": CREDENTIAL_ENV,
        "query_auth_forbidden": True,
    }:
        raise ValueError("source authentication contract mismatch")

    identity = plan.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError("identity contract is missing")
    if (
        identity.get("canonical_prefix") != "coingecko:"
        or identity.get("preserve_symbol_collisions") is not True
        or identity.get("exchange_filtering") is not False
        or identity.get("binance_filtering") is not False
        or identity.get("historical_membership_inference") is not False
    ):
        raise ValueError("identity contract mismatch")

    minimum_rows = plan.get("minimum_rows")
    if not isinstance(minimum_rows, int) or minimum_rows < 1:
        raise ValueError("invalid minimum_rows")
    limits = plan.get("limits")
    if not isinstance(limits, Mapping):
        raise ValueError("limits contract is missing")
    max_runtime_sec = limits.get("max_runtime_sec")
    max_response_bytes = limits.get("max_response_bytes_per_status")
    if (
        not isinstance(max_runtime_sec, int)
        or not 1 <= max_runtime_sec <= MAX_ALLOWED_RUNTIME_SEC
    ):
        raise ValueError("invalid max_runtime_sec")
    if (
        not isinstance(max_response_bytes, int)
        or not 1 <= max_response_bytes <= MAX_ALLOWED_RESPONSE_BYTES
    ):
        raise ValueError("invalid max_response_bytes_per_status")
    if limits.get("request_count") != len(SOURCE_STATUSES):
        raise ValueError("request count mismatch")

    outputs = plan.get("outputs")
    if not isinstance(outputs, Mapping) or outputs.get("immutable") is not True:
        raise ValueError("output contract is missing")
    registry_path = Path(str(outputs.get("registry_jsonl_path") or "")).resolve()
    manifest_path = Path(str(outputs.get("manifest_json_path") or "")).resolve()
    if registry_path == manifest_path:
        raise ValueError("registry and manifest paths must be different")

    provenance = plan.get("code_provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("code provenance is missing")
    module_path = Path(str(provenance.get("module_path") or "")).resolve()
    if module_path != Path(__file__).resolve():
        raise ValueError("canonical registry module path mismatch")
    if _validate_sha256(
        provenance.get("module_sha256"),
        label="module_sha256",
    ) != sha256_file(module_path):
        raise ValueError("canonical registry module hash mismatch")

    if plan.get("decision") != "CANONICAL_REGISTRY_PLAN_READY_AWAITING_VISIBLE_COLLECT":
        raise ValueError("plan decision mismatch")
    if plan.get("next_allowed_command") != "canonical-registry-collect-visible":
        raise ValueError("plan next command mismatch")
    return plan


def _bounded_response_bytes(
    response: Any,
    *,
    max_bytes: int,
) -> bytes:
    raw_length = response.headers.get("Content-Length") if response.headers else None
    if raw_length:
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise RegistrySchemaError(
                "INVALID_CONTENT_LENGTH",
                "invalid response Content-Length",
            ) from exc
        if content_length > max_bytes:
            raise RegistrySchemaError(
                "RESPONSE_TOO_LARGE",
                f"response exceeds {max_bytes} bytes",
            )

    payload = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        payload.extend(chunk)
        if len(payload) > max_bytes:
            raise RegistrySchemaError(
                "RESPONSE_TOO_LARGE",
                f"response exceeds {max_bytes} bytes",
            )
    return bytes(payload)


def _normalize_platforms(value: Any, *, coin_id: str) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise RegistrySchemaError(
            "INVALID_PLATFORMS",
            f"invalid platforms for CoinGecko id {coin_id}",
        )
    normalized: dict[str, str | None] = {}
    for raw_platform, raw_address in value.items():
        platform = str(raw_platform).strip().lower()
        if not platform or platform in normalized:
            raise RegistrySchemaError(
                "INVALID_PLATFORM",
                f"invalid or duplicate platform for CoinGecko id {coin_id}",
            )
        if raw_address is None:
            address = None
        elif isinstance(raw_address, str):
            address = raw_address.strip()
            if address.lower().startswith("0x"):
                address = address.lower()
        else:
            raise RegistrySchemaError(
                "INVALID_CONTRACT_ADDRESS",
                f"invalid contract address for CoinGecko id {coin_id}",
            )
        normalized[platform] = address
    return dict(sorted(normalized.items()))


def _normalize_registry_row(
    raw: Any,
    *,
    status: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise RegistrySchemaError("INVALID_ROW", "CoinGecko row must be an object")
    coin_id = raw.get("id")
    symbol = raw.get("symbol")
    name = raw.get("name")
    if not isinstance(coin_id, str) or not coin_id.strip():
        raise RegistrySchemaError("INVALID_ID", "invalid CoinGecko id")
    coin_id = coin_id.strip()
    if not isinstance(symbol, str) or not symbol.strip():
        raise RegistrySchemaError(
            "INVALID_SYMBOL",
            f"invalid symbol for CoinGecko id {coin_id}",
        )
    if not isinstance(name, str) or not name.strip():
        raise RegistrySchemaError(
            "INVALID_NAME",
            f"invalid name for CoinGecko id {coin_id}",
        )
    platforms = _normalize_platforms(raw.get("platforms"), coin_id=coin_id)
    return {
        "canonical_asset_id": f"coingecko:{coin_id}",
        "coingecko_id": coin_id,
        "symbol": symbol.strip().upper(),
        "name": name.strip(),
        "status": status,
        "platforms": platforms,
        "platform_fingerprint_sha256": sha256_json(platforms),
    }


def _decode_rows(body: bytes, *, status: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistrySchemaError(
            "INVALID_JSON",
            f"invalid CoinGecko {status} response JSON",
        ) from exc
    if not isinstance(payload, list):
        raise RegistrySchemaError(
            "INVALID_RESPONSE_SHAPE",
            f"CoinGecko {status} response must be an array",
        )
    return [_normalize_registry_row(raw, status=status) for raw in payload]


def _registry_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return (
        "".join(f"{_canonical_json(row)}\n" for row in rows)
    ).encode("utf-8")


def _cached_manifest_if_valid(plan: Mapping[str, Any]) -> dict[str, Any] | None:
    outputs = plan["outputs"]
    registry_path = Path(outputs["registry_jsonl_path"])
    manifest_path = Path(outputs["manifest_json_path"])
    if not registry_path.exists() and not manifest_path.exists():
        return None
    if not registry_path.is_file() or not manifest_path.is_file():
        raise ValueError("canonical registry cache is incomplete")
    manifest = _read_json_object(manifest_path)
    if manifest.get("schema") != RESULT_SCHEMA or manifest.get("final") is not True:
        raise ValueError("canonical registry cache manifest is not final")
    if manifest.get("plan_hash") != plan["plan_hash"]:
        raise ValueError("canonical registry cache plan hash mismatch")
    if manifest.get("registry_sha256") != sha256_file(registry_path):
        raise ValueError("canonical registry cache content hash mismatch")
    stored_hash = _validate_sha256(manifest.get("artifact_hash"), label="artifact_hash")
    computed_hash = sha256_json(
        _payload_without_hash(
            manifest,
            hash_key="artifact_hash",
            volatile_keys=("generated_at_utc", "runtime_sec"),
        )
    )
    if stored_hash != computed_hash:
        raise ValueError("canonical registry cache artifact hash mismatch")
    return manifest


def validate_canonical_registry_result(
    manifest_path: str | Path,
    *,
    plan_path: str | Path,
) -> dict[str, Any]:
    plan = validate_canonical_registry_plan(plan_path)
    expected_manifest_path = Path(plan["outputs"]["manifest_json_path"]).resolve()
    observed_manifest_path = Path(manifest_path).expanduser().resolve()
    if observed_manifest_path != expected_manifest_path:
        raise ValueError("canonical registry manifest path mismatch")
    manifest = _read_json_object(observed_manifest_path)
    if manifest.get("schema") != RESULT_SCHEMA or manifest.get("final") is not True:
        raise ValueError("canonical registry result is not final")
    if manifest.get("plan_hash") != plan["plan_hash"]:
        raise ValueError("canonical registry result plan hash mismatch")
    if manifest.get("plan_path") != str(Path(plan_path).expanduser().resolve()):
        raise ValueError("canonical registry result plan path mismatch")
    if manifest.get("module_sha256") != plan["code_provenance"]["module_sha256"]:
        raise ValueError("canonical registry result module hash mismatch")

    registry_path = Path(str(manifest.get("registry_jsonl_path") or "")).resolve()
    expected_registry_path = Path(plan["outputs"]["registry_jsonl_path"]).resolve()
    if registry_path != expected_registry_path or not registry_path.is_file():
        raise ValueError("canonical registry content path mismatch")
    if manifest.get("registry_sha256") != sha256_file(registry_path):
        raise ValueError("canonical registry content hash mismatch")

    stored_hash = _validate_sha256(manifest.get("artifact_hash"), label="artifact_hash")
    computed_hash = sha256_json(
        _payload_without_hash(
            manifest,
            hash_key="artifact_hash",
            volatile_keys=("generated_at_utc", "runtime_sec"),
        )
    )
    if stored_hash != computed_hash:
        raise ValueError("canonical registry result artifact hash mismatch")

    row_count = manifest.get("row_count")
    active_count = manifest.get("active_row_count")
    inactive_count = manifest.get("inactive_row_count")
    if (
        not isinstance(row_count, int)
        or row_count < int(plan["minimum_rows"])
        or not isinstance(active_count, int)
        or not isinstance(inactive_count, int)
        or active_count + inactive_count != row_count
    ):
        raise ValueError("canonical registry result row counts are invalid")
    identity = manifest.get("identity_policy")
    if not isinstance(identity, Mapping) or identity != {
        "canonical_prefix": "coingecko:",
        "symbol_collisions_preserved": True,
        "exchange_filtering_applied": False,
        "historical_binance_exclusion_applied": False,
    }:
        raise ValueError("canonical registry result identity policy mismatch")
    audit = manifest.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(value is not False for value in audit.values()):
        raise ValueError("canonical registry result data-access audit mismatch")
    if (
        manifest.get("verdict")
        != "CANONICAL_REGISTRY_ACCEPTED_READY_FOR_IDENTITY_PLANONLY"
        or manifest.get("next_allowed_command") != "gate-momentum-identity-plan"
    ):
        raise ValueError("canonical registry result verdict mismatch")
    return manifest


def collect_canonical_asset_registry(
    plan_path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    session: Any | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan = validate_canonical_registry_plan(plan_path)
    cached = _cached_manifest_if_valid(plan)
    if cached is not None:
        return cached

    environment = os.environ if environ is None else environ
    credential = str(environment.get(CREDENTIAL_ENV) or "").strip()
    if not credential:
        raise MissingCredentialError(
            f"{CREDENTIAL_ENV} is required for the CoinGecko Demo API"
        )

    limits = plan["limits"]
    max_runtime_sec = int(limits["max_runtime_sec"])
    max_response_bytes = int(limits["max_response_bytes_per_status"])
    started = time.monotonic()
    owns_session = session is None
    http = requests.Session() if owns_session else session
    all_rows: list[dict[str, Any]] = []
    response_summaries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    try:
        for status in SOURCE_STATUSES:
            elapsed = time.monotonic() - started
            remaining = max_runtime_sec - elapsed
            if remaining <= 0:
                raise TimeoutError("canonical registry collection exceeded max_runtime_sec")
            timeout = (min(10.0, remaining), min(30.0, remaining))
            with http.get(
                SOURCE_URL,
                params={"include_platform": "true", "status": status},
                headers={
                    "Accept": "application/json",
                    "User-Agent": "trading_mvp-research/1.0",
                    "x-cg-demo-api-key": credential,
                },
                timeout=timeout,
                stream=True,
            ) as response:
                response.raise_for_status()
                body = _bounded_response_bytes(
                    response,
                    max_bytes=max_response_bytes,
                )
            rows = _decode_rows(body, status=status)
            for row in rows:
                coin_id = row["coingecko_id"]
                if coin_id in seen_ids:
                    raise RegistrySchemaError(
                        "DUPLICATE_COIN_ID",
                        f"duplicate CoinGecko id across statuses: {coin_id}",
                    )
                seen_ids.add(coin_id)
                all_rows.append(row)
            response_summaries.append(
                {
                    "status": status,
                    "row_count": len(rows),
                    "response_bytes": len(body),
                    "response_sha256": sha256_bytes(body),
                }
            )
    finally:
        if owns_session:
            http.close()

    elapsed = time.monotonic() - started
    if elapsed > max_runtime_sec:
        raise TimeoutError("canonical registry collection exceeded max_runtime_sec")
    minimum_rows = int(plan["minimum_rows"])
    if len(all_rows) < minimum_rows:
        raise RegistrySchemaError(
            "INSUFFICIENT_REGISTRY_ROWS",
            f"registry has {len(all_rows)} rows; minimum is {minimum_rows}",
        )

    all_rows.sort(key=lambda row: row["coingecko_id"])
    symbol_counts = Counter(row["symbol"] for row in all_rows)
    collision_symbols = {
        symbol: count for symbol, count in symbol_counts.items() if count > 1
    }
    registry_content = _registry_bytes(all_rows)
    outputs = plan["outputs"]
    registry_path = Path(outputs["registry_jsonl_path"])
    manifest_path = Path(outputs["manifest_json_path"])
    _write_bytes_immutable(registry_path, registry_content)

    manifest: MutableMapping[str, Any] = {
        "schema": RESULT_SCHEMA,
        "final": True,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "runtime_sec": round(elapsed, 6),
        "plan_path": str(Path(plan_path).expanduser().resolve()),
        "plan_hash": plan["plan_hash"],
        "module_sha256": plan["code_provenance"]["module_sha256"],
        "registry_jsonl_path": str(registry_path),
        "registry_sha256": sha256_bytes(registry_content),
        "row_count": len(all_rows),
        "active_row_count": sum(row["status"] == "active" for row in all_rows),
        "inactive_row_count": sum(row["status"] == "inactive" for row in all_rows),
        "unique_symbol_count": len(symbol_counts),
        "symbol_collision_group_count": len(collision_symbols),
        "symbol_collision_asset_count": sum(collision_symbols.values()),
        "response_summaries": response_summaries,
        "identity_policy": {
            "canonical_prefix": "coingecko:",
            "symbol_collisions_preserved": True,
            "exchange_filtering_applied": False,
            "historical_binance_exclusion_applied": False,
        },
        "data_access_audit": {
            "market_prices_read": False,
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "exchange_membership_filtered": False,
        },
        "verdict": "CANONICAL_REGISTRY_ACCEPTED_READY_FOR_IDENTITY_PLANONLY",
        "next_allowed_command": "gate-momentum-identity-plan",
    }
    manifest["artifact_hash"] = sha256_json(
        _payload_without_hash(
            manifest,
            hash_key="artifact_hash",
            volatile_keys=("generated_at_utc", "runtime_sec"),
        )
    )
    _write_json_immutable(manifest_path, manifest)
    return dict(manifest)


def _write_plan(path: str | Path, payload: Mapping[str, Any]) -> None:
    _write_json_immutable(Path(path).expanduser().resolve(), payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and collect a venue-neutral CoinGecko canonical asset registry."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--registry-output", required=True)
    plan_parser.add_argument("--manifest-output", required=True)
    plan_parser.add_argument("--frozen-at-utc")
    plan_parser.add_argument("--minimum-rows", type=int, default=DEFAULT_MINIMUM_ROWS)
    plan_parser.add_argument(
        "--max-response-bytes",
        type=int,
        default=DEFAULT_MAX_RESPONSE_BYTES,
    )
    plan_parser.add_argument(
        "--max-runtime-sec",
        type=int,
        default=DEFAULT_MAX_RUNTIME_SEC,
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
        plan = build_canonical_registry_plan(
            args.registry_output,
            args.manifest_output,
            frozen_at_utc=args.frozen_at_utc,
            minimum_rows=args.minimum_rows,
            max_response_bytes=args.max_response_bytes,
            max_runtime_sec=args.max_runtime_sec,
        )
        _write_plan(args.output, plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "validate-plan":
        plan = validate_canonical_registry_plan(args.plan)
        print(
            json.dumps(
                {
                    "decision": "CANONICAL_REGISTRY_PLAN_VALID",
                    "plan_hash": plan["plan_hash"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "collect":
        result = collect_canonical_asset_registry(args.plan)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "validate-result":
        result = validate_canonical_registry_result(
            args.result,
            plan_path=args.plan,
        )
        print(
            json.dumps(
                {
                    "decision": "CANONICAL_REGISTRY_RESULT_VALID",
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
