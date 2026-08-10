from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


DISCOVERY_MANIFEST_SCHEMA = (
    "trading_mvp_funding_unrestricted_metadata_discovery_output_v1"
)
DISCOVERY_STATUS = "COMPLETE_REQUIRES_IDENTITY_VERIFICATION"
METADATA_SCHEMA = "trading_mvp_funding_active_contract_metadata_v1"
CANDIDATE_SCHEMA = "trading_mvp_funding_provisional_ticker_candidates_v1"
EVIDENCE_BUNDLE_SCHEMA = "trading_mvp_funding_official_identity_bundle_v1"
READINESS_SCHEMA = "trading_mvp_funding_unrestricted_identity_readiness_v1"
BUNDLE_HASH_METHOD = "sha256_canonical_json_excluding_bundle_hash"
READINESS_HASH_METHOD = "sha256_canonical_json_excluding_readiness_hash"
MEXC_ENDPOINT = "https://contract.mexc.com/api/v1/contract/detail"
GATEIO_ENDPOINT = "https://api.gateio.ws/api/v4/futures/usdt/contracts"

PROJECTED_OUTPUT_FILES = (
    "mexc-active-contracts.json",
    "gateio-active-contracts.json",
    "provisional-shared-ticker-candidates.json",
)
MEXC_RECORD_KEYS = {
    "symbol",
    "baseCoin",
    "baseCoinName",
    "quoteCoin",
    "quoteCoinName",
    "settleCoin",
    "state",
    "apiAllowed",
}
GATEIO_RECORD_KEYS = {"name", "status", "type", "in_delisting"}
CANDIDATE_KEYS = {
    "ticker",
    "mexc_symbol",
    "gateio_name",
    "identity_status",
    "same_underlying_verified",
}
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
INSTRUMENT_PATTERN = re.compile(r"^[A-Z0-9._-]+_USDT$")
NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
CAIP19_PATTERN = re.compile(
    r"^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}/"
    r"[-a-z0-9]{3,8}:[-.%a-zA-Z0-9]{1,128}$"
)


class IdentityReadinessError(ValueError):
    pass


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise IdentityReadinessError(f"cannot read {label}: {path}") from exc


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json_object(content: bytes, label: str, path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            content.decode("utf-8-sig"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise IdentityReadinessError(f"invalid {label} JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise IdentityReadinessError(f"{label} must be a JSON object")
    return payload


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise IdentityReadinessError(
            f"{label} keys mismatch; missing={missing}; extra={extra}"
        )


def _require_hash(value: Any, label: str) -> str:
    if type(value) is not str or HASH_PATTERN.fullmatch(value) is None:
        raise IdentityReadinessError(f"invalid {label} SHA-256")
    return value


def _file_ref(path: Path, content: bytes) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256_bytes(content),
        "size_bytes": len(content),
    }


def _validate_projected_file(
    root: Path,
    name: str,
    metadata: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(metadata, dict):
        raise IdentityReadinessError(f"projected output {name} metadata is invalid")
    _require_exact_keys(metadata, {"sha256", "bytes"}, f"projected output {name}")
    expected_sha256 = _require_hash(metadata.get("sha256"), f"projected output {name}")
    expected_bytes = metadata.get("bytes")
    if type(expected_bytes) is not int or expected_bytes < 1:
        raise IdentityReadinessError(f"projected output {name} byte count is invalid")
    path = (root / name).resolve()
    if path.parent != root:
        raise IdentityReadinessError(f"projected output path escaped root: {name}")
    if not path.is_file():
        raise IdentityReadinessError(f"projected output is missing: {name}")
    content = _read_bytes(path, f"projected output {name}")
    if len(content) != expected_bytes:
        raise IdentityReadinessError(f"projected output byte count mismatch: {name}")
    if _sha256_bytes(content) != expected_sha256:
        raise IdentityReadinessError(f"projected output SHA-256 mismatch: {name}")
    return path, _parse_json_object(content, f"projected output {name}", path)


def _validate_metadata_document(
    payload: Mapping[str, Any],
    *,
    venue: str,
    run_id: str,
) -> set[str]:
    _require_exact_keys(
        payload,
        {
            "schema",
            "run_id",
            "venue",
            "endpoint_url",
            "observed_at_utc",
            "active_contract_count",
            "records",
        },
        f"{venue} metadata document",
    )
    if payload.get("schema") != METADATA_SCHEMA:
        raise IdentityReadinessError(f"{venue} metadata schema mismatch")
    if payload.get("run_id") != run_id or payload.get("venue") != venue:
        raise IdentityReadinessError(f"{venue} metadata run binding mismatch")
    expected_endpoint = MEXC_ENDPOINT if venue == "mexc" else GATEIO_ENDPOINT
    if payload.get("endpoint_url") != expected_endpoint:
        raise IdentityReadinessError(f"{venue} metadata endpoint mismatch")
    records = payload.get("records")
    if not isinstance(records, list):
        raise IdentityReadinessError(f"{venue} metadata records must be an array")
    count = payload.get("active_contract_count")
    if type(count) is not int or count != len(records):
        raise IdentityReadinessError(f"{venue} active contract count mismatch")
    expected_keys = MEXC_RECORD_KEYS if venue == "mexc" else GATEIO_RECORD_KEYS
    instrument_field = "symbol" if venue == "mexc" else "name"
    instruments: set[str] = set()
    ordered_instruments: list[str] = []
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise IdentityReadinessError(f"{venue} record {index} must be an object")
        _require_exact_keys(row, expected_keys, f"{venue} record {index}")
        if type(row.get(instrument_field)) is not str:
            raise IdentityReadinessError(
                f"{venue} record {index} instrument must be a string"
            )
        instrument = row[instrument_field]
        if INSTRUMENT_PATTERN.fullmatch(instrument) is None:
            raise IdentityReadinessError(
                f"{venue} record {index} instrument is invalid"
            )
        if instrument in instruments:
            raise IdentityReadinessError(f"{venue} duplicate instrument: {instrument}")
        if venue == "mexc":
            state = row.get("state")
            state_is_active = (type(state) is int and state == 0) or (
                type(state) is str and state == "0"
            )
            if any(
                type(row.get(field)) is not str
                for field in (
                    "baseCoin",
                    "baseCoinName",
                    "quoteCoin",
                    "quoteCoinName",
                    "settleCoin",
                )
            ):
                raise IdentityReadinessError(
                    f"MEXC record {index} asset fields must be strings"
                )
            base = row["baseCoin"].strip().upper()
            if (
                not state_is_active
                or row.get("apiAllowed") is not True
                or row["quoteCoin"].upper() != "USDT"
                or row["settleCoin"].upper() != "USDT"
                or instrument != f"{base}_USDT"
            ):
                raise IdentityReadinessError(
                    f"MEXC record {index} is not an active USDT contract"
                )
        elif any(type(row.get(field)) is not str for field in ("status", "type")):
            raise IdentityReadinessError(
                f"Gate record {index} status fields must be strings"
            )
        elif (
            row["status"].lower() != "trading"
            or row.get("in_delisting") is not False
            or row.get("type") != "direct"
        ):
            raise IdentityReadinessError(
                f"Gate record {index} is not an active USDT contract"
            )
        instruments.add(instrument)
        ordered_instruments.append(instrument)
    if ordered_instruments != sorted(ordered_instruments):
        raise IdentityReadinessError(f"{venue} metadata records are not sorted")
    return instruments


def _validate_candidates_document(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    mexc_instruments: set[str],
    gateio_instruments: set[str],
) -> list[dict[str, str]]:
    _require_exact_keys(
        payload,
        {
            "schema",
            "run_id",
            "match_method",
            "identity_disposition",
            "same_underlying_verified",
            "candidate_count",
            "candidates",
        },
        "provisional candidate document",
    )
    if payload.get("schema") != CANDIDATE_SCHEMA:
        raise IdentityReadinessError("provisional candidate schema mismatch")
    if payload.get("run_id") != run_id:
        raise IdentityReadinessError("provisional candidate run binding mismatch")
    if payload.get("match_method") != "NORMALIZED_CONTRACT_TICKER_INTERSECTION":
        raise IdentityReadinessError("provisional candidate match method changed")
    if payload.get("identity_disposition") != "PROVISIONAL_ONLY_NOT_IDENTITY_EVIDENCE":
        raise IdentityReadinessError(
            "provisional candidate identity disposition changed"
        )
    if payload.get("same_underlying_verified") is not False:
        raise IdentityReadinessError("ticker intersection cannot verify identity")
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        raise IdentityReadinessError("provisional candidates must be an array")
    count = payload.get("candidate_count")
    if type(count) is not int or count != len(rows):
        raise IdentityReadinessError("provisional candidate count mismatch")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise IdentityReadinessError(
                f"provisional candidate {index} must be an object"
            )
        _require_exact_keys(row, CANDIDATE_KEYS, f"provisional candidate {index}")
        if any(
            type(row.get(field)) is not str
            for field in ("ticker", "mexc_symbol", "gateio_name")
        ):
            raise IdentityReadinessError(
                f"candidate {index} ticker fields must be strings"
            )
        ticker = row["ticker"]
        mexc_symbol = row["mexc_symbol"]
        gateio_name = row["gateio_name"]
        if TICKER_PATTERN.fullmatch(ticker) is None or ticker in seen:
            raise IdentityReadinessError(
                f"provisional candidate {index} ticker is invalid"
            )
        if mexc_symbol != f"{ticker}_USDT" or mexc_symbol not in mexc_instruments:
            raise IdentityReadinessError(
                f"provisional candidate {ticker} MEXC binding mismatch"
            )
        if gateio_name != f"{ticker}_USDT" or gateio_name not in gateio_instruments:
            raise IdentityReadinessError(
                f"provisional candidate {ticker} Gate binding mismatch"
            )
        if row.get("identity_status") != "UNRESOLVED_TICKER_MATCH_ONLY":
            raise IdentityReadinessError(
                f"provisional candidate {ticker} identity was promoted"
            )
        if row.get("same_underlying_verified") is not False:
            raise IdentityReadinessError(
                f"provisional candidate {ticker} identity was promoted"
            )
        seen.add(ticker)
        normalized.append(
            {
                "ticker": ticker,
                "mexc_symbol": mexc_symbol,
                "gateio_name": gateio_name,
            }
        )
    if [row["ticker"] for row in normalized] != sorted(seen):
        raise IdentityReadinessError(
            "provisional candidates are not deterministically sorted"
        )
    return normalized


def _load_discovery(
    root_value: str | Path,
    *,
    expected_manifest_sha256: str,
    expected_proposal_hash: str,
    expected_receipt_hash: str,
    expected_runtime_manifest_hash: str,
) -> dict[str, Any]:
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise IdentityReadinessError(f"discovery root is missing: {root}")
    actual_entries = {entry.name for entry in root.iterdir()}
    expected_entries = set(PROJECTED_OUTPUT_FILES) | {"manifest.json"}
    if actual_entries != expected_entries or any(
        not (root / name).is_file() for name in expected_entries
    ):
        raise IdentityReadinessError("discovery root file set mismatch")
    manifest_path = root / "manifest.json"
    trusted_manifest_sha256 = _require_hash(
        expected_manifest_sha256,
        "trusted discovery manifest",
    )
    manifest_content = _read_bytes(manifest_path, "discovery manifest")
    if _sha256_bytes(manifest_content) != trusted_manifest_sha256:
        raise IdentityReadinessError(
            "discovery manifest does not match trusted SHA-256"
        )
    manifest = _parse_json_object(
        manifest_content,
        "discovery manifest",
        manifest_path,
    )
    if manifest.get("schema") != DISCOVERY_MANIFEST_SCHEMA:
        raise IdentityReadinessError("discovery manifest schema mismatch")
    if manifest.get("status") != DISCOVERY_STATUS:
        raise IdentityReadinessError("discovery is not an immutable completion")
    run_id = manifest.get("run_id")
    if type(run_id) is not str or not run_id:
        raise IdentityReadinessError("discovery run_id must be a non-empty string")
    required_false = {
        "raw_response_persisted",
        "funding_rates_or_prices_persisted",
        "identity_verified",
        "automatic_data_collection_allowed",
    }
    if any(manifest.get(field) is not False for field in required_false):
        raise IdentityReadinessError("discovery safety state changed")
    if manifest.get("research_only") is not True:
        raise IdentityReadinessError("discovery must remain research-only")
    if (
        manifest.get("next_checkpoint")
        != "SEPARATE_EXACT_IDENTITY_VERIFIED_CANDIDATE_PLANONLY_REQUIRED"
    ):
        raise IdentityReadinessError("discovery next checkpoint changed")
    bindings = manifest.get("bindings")
    if not isinstance(bindings, dict):
        raise IdentityReadinessError("discovery bindings are missing")
    _require_exact_keys(
        bindings,
        {"proposal_hash", "receipt_hash", "runtime_manifest_hash"},
        "discovery bindings",
    )
    expected_bindings = {
        "proposal_hash": _require_hash(expected_proposal_hash, "trusted proposal"),
        "receipt_hash": _require_hash(expected_receipt_hash, "trusted receipt"),
        "runtime_manifest_hash": _require_hash(
            expected_runtime_manifest_hash,
            "trusted runtime manifest",
        ),
    }
    if bindings != expected_bindings:
        raise IdentityReadinessError("discovery trusted binding mismatch")
    projected = manifest.get("projected_outputs")
    if not isinstance(projected, dict) or set(projected) != set(PROJECTED_OUTPUT_FILES):
        raise IdentityReadinessError("discovery projected output set mismatch")
    projected_artifacts = {
        name: _validate_projected_file(root, name, projected[name])
        for name in PROJECTED_OUTPUT_FILES
    }
    mexc = projected_artifacts["mexc-active-contracts.json"][1]
    gateio = projected_artifacts["gateio-active-contracts.json"][1]
    candidate_payload = projected_artifacts[
        "provisional-shared-ticker-candidates.json"
    ][1]
    mexc_instruments = _validate_metadata_document(mexc, venue="mexc", run_id=run_id)
    gateio_instruments = _validate_metadata_document(
        gateio, venue="gateio", run_id=run_id
    )
    candidates = _validate_candidates_document(
        candidate_payload,
        run_id=run_id,
        mexc_instruments=mexc_instruments,
        gateio_instruments=gateio_instruments,
    )
    full_intersection = sorted(
        {instrument[: -len("_USDT")] for instrument in mexc_instruments}
        & {instrument[: -len("_USDT")] for instrument in gateio_instruments}
    )
    if [candidate["ticker"] for candidate in candidates] != full_intersection:
        raise IdentityReadinessError(
            "candidate set does not equal full metadata ticker intersection"
        )
    counts = manifest.get("contract_counts")
    if not isinstance(counts, dict):
        raise IdentityReadinessError("discovery contract counts are missing")
    expected_counts = {
        "mexc": len(mexc_instruments),
        "gateio": len(gateio_instruments),
        "provisional_shared_tickers": len(candidates),
    }
    if any(type(counts.get(key)) is not int for key in expected_counts):
        raise IdentityReadinessError("discovery contract count type mismatch")
    if counts != expected_counts:
        raise IdentityReadinessError("discovery contract counts mismatch")
    return {
        "root": root,
        "manifest": manifest,
        "manifest_ref": _file_ref(manifest_path, manifest_content),
        "run_id": run_id,
        "candidates": candidates,
    }


def _validate_identifier(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise IdentityReadinessError(f"{label} must be an object")
    _require_exact_keys(value, {"namespace", "value", "comparison"}, label)
    if any(
        type(value.get(field)) is not str
        for field in ("namespace", "value", "comparison")
    ):
        raise IdentityReadinessError(f"{label} identifier fields must be strings")
    namespace = value["namespace"]
    identifier = value["value"]
    comparison = value["comparison"]
    if NAMESPACE_PATTERN.fullmatch(namespace) is None:
        raise IdentityReadinessError(f"{label} namespace is invalid")
    if namespace != namespace.lower():
        raise IdentityReadinessError(f"{label} namespace must be canonical lowercase")
    if not identifier or len(identifier) > 256 or identifier != identifier.strip():
        raise IdentityReadinessError(f"{label} value is invalid")
    if comparison not in {"EXACT", "ASCII_CASE_INSENSITIVE"}:
        raise IdentityReadinessError(f"{label} comparison mode is invalid")
    if namespace.startswith("eip155:"):
        if re.fullmatch(r"eip155:[1-9][0-9]*/erc20", namespace) is None:
            raise IdentityReadinessError(f"{label} EVM namespace is invalid")
        if comparison != "ASCII_CASE_INSENSITIVE":
            raise IdentityReadinessError(
                f"{label} EVM identifier must use ASCII_CASE_INSENSITIVE comparison"
            )
        if re.fullmatch(r"0x[0-9a-fA-F]{40}", identifier, re.IGNORECASE) is None:
            raise IdentityReadinessError(f"{label} EVM address is invalid")
    elif namespace == "caip19":
        if comparison != "EXACT":
            raise IdentityReadinessError(
                f"{label} non-EVM identifier must use EXACT comparison"
            )
        if CAIP19_PATTERN.fullmatch(identifier) is None:
            raise IdentityReadinessError(f"{label} CAIP-19 value is invalid")
    else:
        raise IdentityReadinessError(f"{label} identifier namespace is unsupported")
    if comparison == "ASCII_CASE_INSENSITIVE" and not identifier.isascii():
        raise IdentityReadinessError(f"{label} case-insensitive value must be ASCII")
    return {
        "namespace": namespace,
        "value": identifier,
        "comparison": comparison,
    }


def _identifiers_equal(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    if (
        left["namespace"] != right["namespace"]
        or left["comparison"] != right["comparison"]
    ):
        return False
    if left["comparison"] == "EXACT":
        return left["value"] == right["value"]
    return left["value"].lower() == right["value"].lower()


def _official_source_url_valid(venue: str, value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.path in {"", "/"}
    ):
        return False
    host = (parsed.hostname or "").lower()
    if venue == "mexc":
        return host == "mexc.com" or host.endswith(".mexc.com")
    if venue == "gateio":
        return (
            host in {"gate.com", "gate.io"}
            or host.endswith(".gate.com")
            or host.endswith(".gate.io")
        )
    return False


def _validate_source_list(value: Any, venue: str) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for index, source in enumerate(value):
        if not isinstance(source, dict):
            return False
        try:
            _require_exact_keys(
                source,
                {"url", "response_body_sha256"},
                f"{venue} source {index}",
            )
            _require_hash(source.get("response_body_sha256"), f"{venue} source {index}")
        except IdentityReadinessError:
            return False
        if not _official_source_url_valid(venue, source.get("url")):
            return False
    return True


def _validate_bundle(
    path_value: str | Path,
    *,
    discovery: Mapping[str, Any],
    expected_file_sha256: str,
    expected_bundle_hash: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    path = Path(path_value).expanduser().resolve()
    trusted_file_sha256 = _require_hash(
        expected_file_sha256,
        "trusted identity bundle file",
    )
    bundle_content = _read_bytes(path, "identity evidence bundle")
    if _sha256_bytes(bundle_content) != trusted_file_sha256:
        raise IdentityReadinessError(
            "identity bundle does not match trusted file SHA-256"
        )
    payload = _parse_json_object(
        bundle_content,
        "identity evidence bundle",
        path,
    )
    _require_exact_keys(
        payload,
        {
            "schema",
            "created_at_utc",
            "verification_scope",
            "research_only",
            "discovery_binding",
            "assets",
            "safety",
            "bundle_hash_method",
            "bundle_hash",
        },
        "identity evidence bundle",
    )
    if payload.get("schema") != EVIDENCE_BUNDLE_SCHEMA:
        raise IdentityReadinessError("identity evidence bundle schema mismatch")
    if type(payload.get("created_at_utc")) is not str:
        raise IdentityReadinessError("identity evidence creation time must be a string")
    if payload.get("verification_scope") != "identity_only_no_market_values":
        raise IdentityReadinessError("identity evidence scope mismatch")
    if payload.get("research_only") is not True:
        raise IdentityReadinessError("identity evidence must remain research-only")
    if payload.get("bundle_hash_method") != BUNDLE_HASH_METHOD:
        raise IdentityReadinessError("identity evidence bundle hash method mismatch")
    expected_hash = canonical_hash(
        {key: value for key, value in payload.items() if key != "bundle_hash"}
    )
    if payload.get("bundle_hash") != expected_hash:
        raise IdentityReadinessError("identity evidence bundle hash mismatch")
    trusted_bundle_hash = _require_hash(
        expected_bundle_hash,
        "trusted identity bundle",
    )
    if payload.get("bundle_hash") != trusted_bundle_hash:
        raise IdentityReadinessError(
            "identity bundle hash does not match trust binding"
        )
    binding = payload.get("discovery_binding")
    if not isinstance(binding, dict):
        raise IdentityReadinessError("identity evidence discovery binding is missing")
    _require_exact_keys(
        binding,
        {"run_id", "manifest_file_sha256"},
        "identity evidence discovery binding",
    )
    if binding.get("run_id") != discovery["run_id"]:
        raise IdentityReadinessError("identity evidence run binding mismatch")
    if binding.get("manifest_file_sha256") != discovery["manifest_ref"]["sha256"]:
        raise IdentityReadinessError("identity evidence manifest binding mismatch")
    safety = payload.get("safety")
    if not isinstance(safety, dict):
        raise IdentityReadinessError("identity evidence safety block is missing")
    _require_exact_keys(
        safety,
        {
            "raw_payload_persisted",
            "funding_rates_read",
            "prices_read",
            "returns_or_pnl_computed",
            "oos_read",
            "collector_or_evaluator_run",
        },
        "identity evidence safety",
    )
    if any(value is not False for value in safety.values()):
        raise IdentityReadinessError("identity evidence safety block is not closed")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise IdentityReadinessError("identity evidence assets must be an array")
    discovered = {row["ticker"] for row in discovery["candidates"]}
    by_ticker: dict[str, dict[str, Any]] = {}
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise IdentityReadinessError(f"identity asset {index} must be an object")
        _require_exact_keys(
            asset,
            {"ticker", "asset_name", "canonical_identifier", "venues"},
            f"identity asset {index}",
        )
        if type(asset.get("ticker")) is not str:
            raise IdentityReadinessError(
                f"identity asset {index} ticker must be a string"
            )
        ticker = asset["ticker"]
        if TICKER_PATTERN.fullmatch(ticker) is None or ticker in by_ticker:
            raise IdentityReadinessError(f"identity asset {index} ticker is invalid")
        if ticker not in discovered:
            raise IdentityReadinessError(
                f"identity asset is outside discovery: {ticker}"
            )
        if type(asset.get("asset_name")) is not str:
            raise IdentityReadinessError(
                f"identity asset {ticker} name must be a string"
            )
        if not asset["asset_name"].strip():
            raise IdentityReadinessError(f"identity asset {ticker} name is missing")
        _validate_identifier(
            asset.get("canonical_identifier"), f"{ticker} canonical identifier"
        )
        venues = asset.get("venues")
        if not isinstance(venues, list):
            raise IdentityReadinessError(
                f"identity asset {ticker} venues must be an array"
            )
        if any(
            not isinstance(item, dict) or type(item.get("venue")) is not str
            for item in venues
        ):
            raise IdentityReadinessError(
                f"identity asset {ticker} venues must contain string venue names"
            )
        venue_names = [item["venue"] for item in venues]
        if set(venue_names) != {"mexc", "gateio"}:
            raise IdentityReadinessError(f"identity asset {ticker} venue set mismatch")
        if len(set(venue_names)) != len(venue_names):
            raise IdentityReadinessError(
                f"identity asset {ticker} has duplicate venues"
            )
        by_ticker[ticker] = asset
    return payload, by_ticker, _file_ref(path, bundle_content)


def _assess_asset(
    candidate: Mapping[str, str],
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    ticker = candidate["ticker"]
    result: dict[str, Any] = {
        "ticker": ticker,
        "mexc_symbol": candidate["mexc_symbol"],
        "gateio_name": candidate["gateio_name"],
        "identity_status": "UNRESOLVED_REQUIRES_OFFICIAL_EVIDENCE",
        "same_underlying_verified": False,
        "reason_codes": [],
    }
    if evidence is None:
        result["reason_codes"] = ["official_identity_evidence_missing"]
        return result
    canonical = _validate_identifier(
        evidence.get("canonical_identifier"),
        f"{ticker} canonical identifier",
    )
    venues = {item["venue"]: item for item in evidence["venues"]}
    expected_instruments = {
        "mexc": candidate["mexc_symbol"],
        "gateio": candidate["gateio_name"],
    }
    reasons: list[str] = []
    for venue in ("mexc", "gateio"):
        item = venues[venue]
        _require_exact_keys(
            item,
            {
                "venue",
                "instrument_id",
                "base_ticker",
                "market_type",
                "observed_identifier",
                "official_sources",
            },
            f"{ticker} {venue} identity evidence",
        )
        if any(
            type(item.get(field)) is not str
            for field in ("instrument_id", "base_ticker", "market_type")
        ):
            raise IdentityReadinessError(
                f"{ticker} {venue} identity fields must be strings"
            )
        if item.get("instrument_id") != expected_instruments[venue]:
            reasons.append(f"{venue}_instrument_mismatch")
        if item.get("base_ticker") != ticker:
            reasons.append(f"{venue}_base_ticker_mismatch")
        if item.get("market_type") != "perpetual":
            reasons.append(f"{venue}_market_type_mismatch")
        observed = _validate_identifier(
            item.get("observed_identifier"),
            f"{ticker} {venue} observed identifier",
        )
        if not _identifiers_equal(canonical, observed):
            reasons.append(f"{venue}_identifier_mismatch")
        if not _validate_source_list(item.get("official_sources"), venue):
            reasons.append(f"{venue}_official_source_invalid")
    result["reason_codes"] = sorted(set(reasons))
    if not reasons:
        result["identity_status"] = (
            "HASH_BOUND_IDENTITY_CLAIM_AWAIT_SOURCE_CONTENT_REVIEW"
        )
        result["asset_name"] = evidence["asset_name"]
        result["canonical_identifier"] = canonical
    else:
        result["identity_status"] = "IDENTITY_EVIDENCE_REJECTED_FAIL_CLOSED"
    return result


def build_identity_readiness(
    discovery_root: str | Path,
    identity_bundle_path: str | Path,
    *,
    expected_discovery_manifest_sha256: str,
    expected_proposal_hash: str,
    expected_receipt_hash: str,
    expected_runtime_manifest_hash: str,
    expected_identity_bundle_file_sha256: str,
    expected_identity_bundle_hash: str,
) -> dict[str, Any]:
    discovery = _load_discovery(
        discovery_root,
        expected_manifest_sha256=expected_discovery_manifest_sha256,
        expected_proposal_hash=expected_proposal_hash,
        expected_receipt_hash=expected_receipt_hash,
        expected_runtime_manifest_hash=expected_runtime_manifest_hash,
    )
    bundle, evidence_by_ticker, bundle_ref = _validate_bundle(
        identity_bundle_path,
        discovery=discovery,
        expected_file_sha256=expected_identity_bundle_file_sha256,
        expected_bundle_hash=expected_identity_bundle_hash,
    )
    candidates = [
        _assess_asset(candidate, evidence_by_ticker.get(candidate["ticker"]))
        for candidate in discovery["candidates"]
    ]
    structurally_complete = sum(
        item["identity_status"]
        == "HASH_BOUND_IDENTITY_CLAIM_AWAIT_SOURCE_CONTENT_REVIEW"
        for item in candidates
    )
    report: dict[str, Any] = {
        "schema": READINESS_SCHEMA,
        "status": (
            "IDENTITY_CLAIM_BUNDLE_STRUCTURALLY_VALID_AWAIT_SOURCE_CONTENT_REVIEW"
            if structurally_complete
            else "NO_COMPLETE_IDENTITY_CLAIM"
        ),
        "research_only": True,
        "inputs": {
            "discovery_manifest": discovery["manifest_ref"],
            "identity_bundle": bundle_ref,
            "identity_bundle_hash": bundle["bundle_hash"],
        },
        "discovery": {
            "run_id": discovery["run_id"],
            "proposal_hash": discovery["manifest"]
            .get("bindings", {})
            .get("proposal_hash"),
            "identity_verified": False,
        },
        "universe_policy": {
            "mode": "ALL_ASSETS_WITHOUT_CATEGORY_EXCLUSIONS",
            "category_exclusions": [],
            "ticker_text_alone_is_identity_evidence": False,
        },
        "candidate_summary": {
            "discovered": len(candidates),
            "structurally_complete_claims": structurally_complete,
            "unresolved": len(candidates) - structurally_complete,
        },
        "candidates": candidates,
        "source_review": {
            "source_content_validated": False,
            "same_underlying_accepted": False,
            "bundle_claims_are_identity_evidence": False,
            "required_next_review": (
                "VERIFY_EXACT_OFFICIAL_SOURCE_CONTENT_AGAINST_HASH_BOUND_CLAIMS"
            ),
        },
        "authorization": {
            "candidate_planonly_creation": False,
            "data_collection": False,
            "evaluator_or_oos": False,
            "paper_or_live": False,
        },
        "safety": {
            "network_accessed": False,
            "raw_payload_read": False,
            "funding_rates_read": False,
            "prices_read": False,
            "returns_or_pnl_computed": False,
            "oos_read": False,
            "collector_or_evaluator_run": False,
            "private_api_or_real_capital": False,
        },
        "next_checkpoint": (
            "SEPARATE_EXACT_IDENTITY_VERIFIED_CANDIDATE_PLANONLY_REQUIRED"
        ),
        "readiness_hash_method": READINESS_HASH_METHOD,
    }
    report["readiness_hash"] = canonical_hash(report)
    return report


def write_identity_readiness(
    discovery_root: str | Path,
    identity_bundle_path: str | Path,
    output_path: str | Path,
    *,
    expected_discovery_manifest_sha256: str,
    expected_proposal_hash: str,
    expected_receipt_hash: str,
    expected_runtime_manifest_hash: str,
    expected_identity_bundle_file_sha256: str,
    expected_identity_bundle_hash: str,
) -> dict[str, Any]:
    report = build_identity_readiness(
        discovery_root,
        identity_bundle_path,
        expected_discovery_manifest_sha256=expected_discovery_manifest_sha256,
        expected_proposal_hash=expected_proposal_hash,
        expected_receipt_hash=expected_receipt_hash,
        expected_runtime_manifest_hash=expected_runtime_manifest_hash,
        expected_identity_bundle_file_sha256=expected_identity_bundle_file_sha256,
        expected_identity_bundle_hash=expected_identity_bundle_hash,
    )
    target = Path(output_path).expanduser().resolve()
    discovery_path = Path(discovery_root).expanduser().resolve()
    if target == discovery_path or discovery_path in target.parents:
        raise IdentityReadinessError("output must be outside immutable discovery root")
    content = (
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != content:
                raise FileExistsError(
                    f"refusing to overwrite immutable report: {target}"
                )
    finally:
        temporary.unlink(missing_ok=True)
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline fail-closed readiness audit for funding identity evidence"
    )
    parser.add_argument("--discovery-root", required=True)
    parser.add_argument("--identity-bundle", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-discovery-manifest-sha256", required=True)
    parser.add_argument("--expected-proposal-hash", required=True)
    parser.add_argument("--expected-receipt-hash", required=True)
    parser.add_argument("--expected-runtime-manifest-hash", required=True)
    parser.add_argument("--expected-identity-bundle-file-sha256", required=True)
    parser.add_argument("--expected-identity-bundle-hash", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = write_identity_readiness(
            args.discovery_root,
            args.identity_bundle,
            args.out,
            expected_discovery_manifest_sha256=(
                args.expected_discovery_manifest_sha256
            ),
            expected_proposal_hash=args.expected_proposal_hash,
            expected_receipt_hash=args.expected_receipt_hash,
            expected_runtime_manifest_hash=args.expected_runtime_manifest_hash,
            expected_identity_bundle_file_sha256=(
                args.expected_identity_bundle_file_sha256
            ),
            expected_identity_bundle_hash=args.expected_identity_bundle_hash,
        )
    except (IdentityReadinessError, FileExistsError, OSError) as exc:
        print(f"IDENTITY_READINESS_FAILED: {exc}", file=sys.stderr)
        return 2
    print(
        "IDENTITY_READINESS "
        f"status={report['status']} "
        "identity_verified=false source_content_validated=false "
        f"claims={report['candidate_summary']['structurally_complete_claims']} "
        "planonly_allowed=false data_collection_allowed=false "
        f"hash={report['readiness_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
