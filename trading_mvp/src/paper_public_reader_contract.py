from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


CONTRACT_SCHEMA = "trading_mvp_paper_public_market_reader_contract_v1"
CONTRACT_SCHEMA_V2 = "trading_mvp_paper_public_market_reader_contract_v2"
CONTRACT_SCHEMA_V3 = "trading_mvp_paper_public_market_reader_contract_v3"
CONTRACT_SCHEMAS = {
    "v1": CONTRACT_SCHEMA,
    "v2": CONTRACT_SCHEMA_V2,
    "v3": CONTRACT_SCHEMA_V3,
}
STATUS = "FROZEN_DESIGN_NO_NETWORK_REQUESTS"
VENUES = ("mexc", "gateio")
MEXC_DEPTH_MIGRATION_PROBE_PLAN_HASH = (
    "318c6dbd76777cc4cff8f8e4e0ec67df10b497b33709155c642d2476285527ff"
)
PRIVATE_HEADER_NAMES = {
    "api-key",
    "api-sign",
    "authorization",
    "gate-channel-id",
    "key",
    "signature",
    "x-api-key",
    "x-gate-channel-id",
    "x-mexc-apikey",
}
ALLOWED_HEADER_NAMES = {"accept", "user-agent"}
PRIVATE_QUERY_NAMES = {
    "api_key",
    "apikey",
    "recvwindow",
    "signature",
    "timestamp",
}
SYMBOL_PATTERNS = {
    "mexc": r"^[A-Z0-9]+_USDT$",
    "gateio": r"^[A-Z0-9]+_USDT$",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contract_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "contract_hash_sha256"}
        }
    )


def _endpoint(
    endpoint_id: str,
    path_template: str,
    *,
    purpose: str,
    query: Mapping[str, Mapping[str, Any]] | None,
    response_schema: Mapping[str, Any],
    cache_ttl_sec: int,
) -> dict[str, Any]:
    request_schema = {
        "method": "GET",
        "path_template": path_template,
        "path_parameters": (
            {
                "symbol": {
                    "required": True,
                    "pattern": r"^[A-Z0-9]+_USDT$",
                }
            }
            if "{symbol}" in path_template
            else {}
        ),
        "query_parameters": dict(query or {}),
        "embedded_url_query_forbidden": True,
        "request_body_forbidden": True,
    }
    descriptor = {
        "endpoint_id": endpoint_id,
        "purpose": purpose,
        "request_schema": request_schema,
        "response_schema": dict(response_schema),
        "cache_ttl_sec": cache_ttl_sec,
    }
    descriptor["schema_hash_sha256"] = sha256_json(
        {
            "request_schema": request_schema,
            "response_schema": descriptor["response_schema"],
        }
    )
    return descriptor


def _venue_definitions(
    contract_version: str = "v1",
) -> dict[str, dict[str, Any]]:
    if contract_version not in CONTRACT_SCHEMAS:
        raise ValueError(f"unsupported public reader contract version: {contract_version}")
    mexc = {
        "base_url": "https://contract.mexc.com",
        "rate_limit": {
            "requests_per_sec": 5.0,
            "burst": 5,
            "maximum_in_flight": 4,
        },
        "timeouts": {
            "connect_sec": 3.0,
            "read_sec": 7.0,
            "maximum_attempts": 3,
            "retry_backoff_sec": [0.5, 1.0],
            "retry_http_statuses": [429, 500, 502, 503, 504],
        },
        "endpoints": [
            _endpoint(
                "mexc_contracts",
                "/api/v1/contract/detail",
                purpose="tradable contract metadata",
                query=None,
                response_schema={
                    "root": "object",
                    "required": ["success", "data"],
                    "data": "array",
                    "item_required": [
                        "symbol",
                        "baseCoin",
                        "quoteCoin",
                        "state",
                    ],
                },
                cache_ttl_sec=86_400,
            ),
            _endpoint(
                "mexc_tickers",
                "/api/v1/contract/ticker",
                purpose="public all-contract BBO, mark, index and funding",
                query=None,
                response_schema={
                    "root": "object",
                    "required": ["success", "data"],
                    "data": "array",
                    "item_required": [
                        "symbol",
                        "bid1",
                        "ask1",
                        "fairPrice",
                        "indexPrice",
                        "timestamp",
                    ],
                },
                cache_ttl_sec=5,
            ),
            _endpoint(
                "mexc_funding",
                "/api/v1/contract/funding_rate/{symbol}",
                purpose="public current funding and next settlement",
                query=None,
                response_schema={
                    "root": "object",
                    "required": ["success", "data"],
                    "data": "object",
                    "item_required": [
                        "symbol",
                        "fundingRate",
                        "nextSettleTime",
                        "timestamp",
                    ],
                },
                cache_ttl_sec=60,
            ),
            _endpoint(
                "mexc_depth",
                "/api/v1/contract/depth/{symbol}",
                purpose="public order-book capacity and impact",
                query={
                    "limit": {
                        "required": True,
                        "type": "integer",
                        "allowed_values": [20],
                    }
                },
                response_schema={
                    "root": "object",
                    "required": ["success", "data"],
                    "data": "object",
                    "item_required": ["bids", "asks"],
                    "level_shape": "[price, quantity, order_count?]",
                },
                cache_ttl_sec=0,
            ),
        ],
    }
    gateio = {
        "base_url": "https://api.gateio.ws/api/v4",
        "rate_limit": {
            "requests_per_sec": 5.0,
            "burst": 5,
            "maximum_in_flight": 4,
        },
        "timeouts": {
            "connect_sec": 3.0,
            "read_sec": 7.0,
            "maximum_attempts": 3,
            "retry_backoff_sec": [0.5, 1.0],
            "retry_http_statuses": [429, 500, 502, 503, 504],
        },
        "endpoints": [
            _endpoint(
                "gateio_contracts",
                "/futures/usdt/contracts",
                purpose="tradable contract metadata",
                query=None,
                response_schema={
                    "root": "array",
                    "item_required": [
                        "name",
                        "status",
                        "mark_price",
                        "index_price",
                        "funding_rate",
                    ],
                },
                cache_ttl_sec=86_400,
            ),
            _endpoint(
                "gateio_tickers",
                "/futures/usdt/tickers",
                purpose="public contract BBO, mark, index and funding",
                query={
                    "contract": {
                        "required": False,
                        "type": "symbol",
                        "pattern": r"^[A-Z0-9]+_USDT$",
                    }
                },
                response_schema={
                    "root": "array",
                    "item_required": [
                        "contract",
                        "highest_bid",
                        "lowest_ask",
                        "mark_price",
                        "index_price",
                        "funding_rate",
                    ],
                },
                cache_ttl_sec=5,
            ),
            _endpoint(
                "gateio_funding",
                "/futures/usdt/funding_rate",
                purpose="public funding settlement history",
                query={
                    "contract": {
                        "required": True,
                        "type": "symbol",
                        "pattern": r"^[A-Z0-9]+_USDT$",
                    },
                    "limit": {
                        "required": True,
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                response_schema={
                    "root": "array",
                    "item_required": ["t", "r"],
                },
                cache_ttl_sec=60,
            ),
            _endpoint(
                "gateio_depth",
                "/futures/usdt/order_book",
                purpose="public order-book capacity and impact",
                query={
                    "contract": {
                        "required": True,
                        "type": "symbol",
                        "pattern": r"^[A-Z0-9]+_USDT$",
                    },
                    "limit": {
                        "required": True,
                        "type": "integer",
                        "allowed_values": [20],
                    },
                },
                response_schema={
                    "root": "object",
                    "required": ["bids", "asks"],
                    "level_required": ["p", "s"],
                },
                cache_ttl_sec=0,
            ),
        ],
    }
    if contract_version in {"v2", "v3"}:
        ticker = next(
            endpoint
            for endpoint in mexc["endpoints"]
            if endpoint["endpoint_id"] == "mexc_tickers"
        )
        ticker["purpose"] = "public all-contract mark, index and timestamp"
        ticker["response_schema"]["item_required"] = [
            "symbol",
            "fairPrice",
            "indexPrice",
            "timestamp",
        ]
        ticker["schema_hash_sha256"] = sha256_json(
            {
                "request_schema": ticker["request_schema"],
                "response_schema": ticker["response_schema"],
            }
        )
        depth = next(
            endpoint
            for endpoint in mexc["endpoints"]
            if endpoint["endpoint_id"] == "mexc_depth"
        )
        depth["purpose"] = "public order-book BBO, capacity and impact"
        depth["response_schema"]["item_required"] = [
            "bids",
            "asks",
            "timestamp",
        ]
        depth["schema_hash_sha256"] = sha256_json(
            {
                "request_schema": depth["request_schema"],
                "response_schema": depth["response_schema"],
            }
        )
    return {"mexc": mexc, "gateio": gateio}


def _normalization_contract(contract_version: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "output_schema": "trading_mvp_public_market_snapshot_v1",
        "key": ["observer_received_ts_ms", "canonical_base", "venue"],
        "required_fields": [
            "venue",
            "symbol",
            "canonical_base",
            "observer_received_ts_ms",
            "observed_ts_ms",
            "best_bid",
            "best_ask",
            "mark_price",
            "index_price",
            "funding_rate",
            "bid_depth",
            "ask_depth",
            "contract_trading",
            "raw_payload_hash_sha256",
        ],
        "finite_positive_price_fields": [
            "best_bid",
            "best_ask",
            "mark_price",
            "index_price",
        ],
        "crossed_book_forbidden": True,
        "unknown_fields_preserved_only_in_raw_hash": True,
    }
    if contract_version in {"v2", "v3"}:
        payload["bbo_sources"] = {
            "mexc": "mexc_depth_l1",
            "gateio": "gateio_tickers",
        }
        payload["compatibility_guarantee"] = {
            "output_schema_changed": False,
            "normalized_fields_changed": False,
            "economic_contract_changed": False,
            "venue_universe_signal_cost_risk_changed": False,
        }
    if contract_version == "v3":
        payload["quote_freshness_policy"] = {
            "maximum_quote_age_ms_by_venue": {
                "mexc": 6000,
                "gateio": 5000,
            },
            "age_reference": "local_receive_time_after_all_endpoint_responses",
            "stale_quote_action": "STOPPED_INCOMPLETE",
        }
    return payload


def _contract_version(payload: Mapping[str, Any]) -> str:
    schema = str(payload.get("schema") or "")
    contract_id = str(payload.get("contract_id") or "")
    for version, expected_schema in CONTRACT_SCHEMAS.items():
        if (
            schema == expected_schema
            and contract_id == f"paper_public_reader_contract_{version}"
        ):
            return version
    raise ValueError("unsupported public reader contract schema or id")


def _read_reliability_evidence(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if payload.get("schema") != "trading_mvp_venue_api_reliability_evidence_v1":
        raise ValueError("unexpected reliability evidence schema")
    scope = payload.get("scope")
    if not isinstance(scope, Mapping):
        raise ValueError("reliability evidence scope is missing")
    if set(scope.get("venues") or []) != set(VENUES):
        raise ValueError("reliability evidence venue scope mismatch")
    if scope.get("private_api_keys") is not False or scope.get("live_orders") is not False:
        raise ValueError("reliability evidence safety scope was loosened")
    return payload


def _read_mexc_depth_migration_evidence(
    *,
    manifest_path: str | Path,
    depth_reference_path: str | Path,
) -> dict[str, Any]:
    manifest_target = Path(manifest_path).expanduser().resolve()
    depth_target = Path(depth_reference_path).expanduser().resolve()
    if not manifest_target.is_file():
        raise FileNotFoundError(manifest_target)
    if not depth_target.is_file():
        raise FileNotFoundError(depth_target)
    manifest = json.loads(manifest_target.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("migration probe manifest root must be an object")
    if (
        manifest.get("schema")
        != "trading_mvp_paper_public_readonly_probe_result_v1"
    ):
        raise ValueError("unexpected migration probe manifest schema")
    deterministic = {
        key: value
        for key, value in manifest.items()
        if key
        not in {
            "deterministic_result_hash",
            "started_at_utc",
            "completed_at_utc",
        }
    }
    if str(manifest.get("deterministic_result_hash") or "").lower() != (
        sha256_json(deterministic)
    ):
        raise ValueError("migration probe manifest deterministic hash mismatch")
    plan = manifest.get("plan")
    quality = manifest.get("quality")
    artifacts = manifest.get("artifacts")
    safety = manifest.get("safety")
    if not all(
        isinstance(value, Mapping)
        for value in (plan, quality, artifacts, safety)
    ):
        raise ValueError("migration probe manifest evidence blocks are missing")
    if (
        str(plan.get("plan_hash_sha256") or "").lower()
        != MEXC_DEPTH_MIGRATION_PROBE_PLAN_HASH
    ):
        raise ValueError("migration probe plan hash mismatch")
    if (
        manifest.get("status") != "STOPPED_INCOMPLETE"
        or manifest.get("final") is not False
        or quality.get("hard_stop_reason") != "schema_mismatch"
    ):
        raise ValueError("migration probe did not stop on schema mismatch")
    expected_safety = {
        "public_get_only": True,
        "returns_or_pnl_read": False,
        "signals_read": False,
        "oms_mutations": 0,
        "private_api_keys": False,
        "live_orders": False,
        "leverage_or_margin": False,
        "grid_or_retune": False,
        "hypothesis_changed": False,
    }
    if dict(safety) != expected_safety:
        raise ValueError("migration probe safety boundary mismatch")
    errors_target = Path(
        str(artifacts.get("errors_path") or "")
    ).expanduser().resolve()
    if not errors_target.is_file():
        raise FileNotFoundError(errors_target)
    errors_hash = sha256_file(errors_target)
    if errors_hash != str(
        artifacts.get("errors_file_sha256") or ""
    ).lower():
        raise ValueError("migration probe errors artifact hash mismatch")
    errors = [
        json.loads(line)
        for line in errors_target.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    matching = [
        row
        for row in errors
        if isinstance(row, dict)
        and row.get("venue") == "mexc"
        and row.get("category") == "schema_mismatch"
        and row.get("endpoint_id") == "mexc_tickers"
        and "bid1" in str(row.get("detail") or "")
        and "ask1" in str(row.get("detail") or "")
    ]
    if len(matching) != 1:
        raise ValueError("migration probe lacks the exact MEXC BBO mismatch")
    return {
        "source_probe_manifest": {
            "path": str(manifest_target),
            "file_sha256": sha256_file(manifest_target),
            "deterministic_result_hash": manifest[
                "deterministic_result_hash"
            ],
            "run_id": manifest["run_id"],
            "plan_hash_sha256": plan["plan_hash_sha256"],
            "stop_reason": quality["hard_stop_reason"],
        },
        "source_probe_errors": {
            "path": str(errors_target),
            "file_sha256": errors_hash,
            "venue": "mexc",
            "endpoint_id": "mexc_tickers",
            "missing_fields": ["bid1", "ask1"],
        },
        "depth_l1_reference": {
            "path": str(depth_target),
            "file_sha256": sha256_file(depth_target),
            "function": "parse_mexc_depth_l1",
            "existing_output_field": "liquidity_proxy_source=mexc_rest_depth_l1",
        },
        "approved_change": {
            "mexc_bbo_before": "mexc_tickers.bid1/ask1",
            "mexc_bbo_after": "mexc_depth best bid/min ask",
            "ticker_fields_retained": [
                "fairPrice",
                "indexPrice",
                "timestamp",
            ],
            "normalized_output_schema_changed": False,
            "economic_contract_changed": False,
        },
    }


def _read_mexc_quote_freshness_migration_evidence(
    *,
    prior_contract_path: str | Path,
    failure_audit_path: str | Path,
) -> dict[str, Any]:
    prior_target = Path(prior_contract_path).expanduser().resolve()
    audit_target = Path(failure_audit_path).expanduser().resolve()
    if not prior_target.is_file():
        raise FileNotFoundError(prior_target)
    if not audit_target.is_file():
        raise FileNotFoundError(audit_target)

    prior_contract = validate_public_reader_contract(
        json.loads(prior_target.read_text(encoding="utf-8-sig"))
    )
    if prior_contract.get("contract_id") != "paper_public_reader_contract_v2":
        raise ValueError("v3 freshness migration requires the frozen v2 contract")

    audit = json.loads(audit_target.read_text(encoding="utf-8-sig"))
    if not isinstance(audit, dict):
        raise ValueError("freshness failure audit root must be an object")
    if (
        audit.get("schema")
        != "trading_mvp_public_readonly_probe_failure_audit_v1"
        or audit.get("status") != "USER_REVIEW_REQUIRED"
    ):
        raise ValueError("unexpected freshness failure audit")
    plan_audit = audit.get("plan")
    result_audit = audit.get("result")
    quality_audit = audit.get("quality")
    failure = audit.get("failure")
    safety_audit = audit.get("safety")
    critical = audit.get("critical_checkpoint")
    if not all(
        isinstance(value, Mapping)
        for value in (
            plan_audit,
            result_audit,
            quality_audit,
            failure,
            safety_audit,
            critical,
        )
    ):
        raise ValueError("freshness failure audit evidence blocks are missing")

    manifest_target = Path(
        str(result_audit.get("path") or "")
    ).expanduser().resolve()
    if not manifest_target.is_file():
        raise FileNotFoundError(manifest_target)
    if sha256_file(manifest_target) != str(
        result_audit.get("file_sha256") or ""
    ).lower():
        raise ValueError("freshness source manifest file hash mismatch")
    manifest = json.loads(manifest_target.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("freshness source manifest root must be an object")
    deterministic = {
        key: value
        for key, value in manifest.items()
        if key
        not in {
            "deterministic_result_hash",
            "started_at_utc",
            "completed_at_utc",
        }
    }
    observed_result_hash = sha256_json(deterministic)
    if (
        manifest.get("schema")
        != "trading_mvp_paper_public_readonly_probe_result_v2"
        or manifest.get("status") != "STOPPED_INCOMPLETE"
        or manifest.get("final") is not False
        or manifest.get("verdict") != "PUBLIC_READONLY_PROBE_STOPPED_INCOMPLETE"
        or str(manifest.get("deterministic_result_hash") or "").lower()
        != observed_result_hash
        or str(result_audit.get("deterministic_result_hash") or "").lower()
        != observed_result_hash
    ):
        raise ValueError("freshness source manifest is not the frozen v2 failure")

    plan = manifest.get("plan")
    contract_descriptor = manifest.get("contract")
    quality = manifest.get("quality")
    artifacts = manifest.get("artifacts")
    safety = manifest.get("safety")
    if not all(
        isinstance(value, Mapping)
        for value in (plan, contract_descriptor, quality, artifacts, safety)
    ):
        raise ValueError("freshness source manifest evidence blocks are missing")
    expected_quality = {
        "expected_snapshot_count": 48,
        "snapshot_count": 46,
        "error_count": 2,
        "planned_endpoint_reads": 192,
        "network_requests": 192,
        "retry_count": 0,
    }
    for key, expected in expected_quality.items():
        if quality.get(key) != expected or quality_audit.get(key) != expected:
            raise ValueError(f"freshness source quality mismatch: {key}")
    if (
        quality.get("partial_output") is not True
        or quality.get("hard_stop_reason") is not None
    ):
        raise ValueError("freshness source output state mismatch")
    if str(plan.get("plan_hash_sha256") or "").lower() != str(
        plan_audit.get("plan_hash_sha256") or ""
    ).lower():
        raise ValueError("freshness source plan hash mismatch")
    if Path(
        str(contract_descriptor.get("path") or "")
    ).expanduser().resolve() != prior_target:
        raise ValueError("freshness source manifest does not bind the v2 contract")
    if (
        str(contract_descriptor.get("contract_hash_sha256") or "").lower()
        != str(prior_contract.get("contract_hash_sha256") or "").lower()
        or str(contract_descriptor.get("file_sha256") or "").lower()
        != sha256_file(prior_target)
    ):
        raise ValueError("freshness source v2 contract binding mismatch")

    expected_safety = {
        "public_get_only": True,
        "returns_or_pnl_read": False,
        "signals_read": False,
        "oms_mutations": 0,
        "private_api_keys": False,
        "live_orders": False,
        "leverage_or_margin": False,
        "grid_or_retune": False,
        "hypothesis_changed": False,
    }
    if dict(safety) != expected_safety or dict(safety_audit) != expected_safety:
        raise ValueError("freshness source safety boundary mismatch")

    errors_target = Path(
        str(artifacts.get("errors_path") or "")
    ).expanduser().resolve()
    if not errors_target.is_file():
        raise FileNotFoundError(errors_target)
    errors_hash = sha256_file(errors_target)
    if errors_hash != str(artifacts.get("errors_file_sha256") or "").lower():
        raise ValueError("freshness source errors artifact hash mismatch")
    errors = [
        json.loads(line)
        for line in errors_target.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    quote_ages: list[int] = []
    for row in errors:
        if (
            not isinstance(row, dict)
            or row.get("venue") != "mexc"
            or row.get("category") != "stale_quote"
            or row.get("endpoint_id") != "mexc_tickers"
        ):
            raise ValueError("freshness source contains a non-MEXC stale error")
        match = re.fullmatch(
            r"quote age (\d+)ms exceeds 5000ms",
            str(row.get("detail") or ""),
        )
        if match is None:
            raise ValueError("freshness source error detail mismatch")
        quote_ages.append(int(match.group(1)))
    approved_ages = sorted(
        int(value) for value in (failure.get("observed_rejected_quote_ages_ms") or [])
    )
    if (
        sorted(quote_ages) != approved_ages
        or len(quote_ages) != 2
        or failure.get("category") != "stale_quote"
        or failure.get("venue") != "mexc"
        or failure.get("endpoint_id") != "mexc_tickers"
        or failure.get("frozen_max_quote_age_ms") != 5000
        or any(age <= 5000 or age > 6000 for age in quote_ages)
    ):
        raise ValueError("freshness source quote-age evidence mismatch")
    if critical.get("recommended_option") != (
        "contract_v3_mexc_max_quote_age_ms_6000_"
        "gateio_5000_one_new_visible_bounded_probe"
    ):
        raise ValueError("freshness audit does not recommend the approved v3 option")

    return {
        "prior_contract": {
            "path": str(prior_target),
            "file_sha256": sha256_file(prior_target),
            "contract_hash_sha256": prior_contract["contract_hash_sha256"],
            "contract_id": prior_contract["contract_id"],
            "inherited_depth_migration_hash_sha256": sha256_json(
                prior_contract["migration_evidence"]
            ),
        },
        "source_failure_audit": {
            "path": str(audit_target),
            "file_sha256": sha256_file(audit_target),
            "run_id": audit["run_id"],
            "plan_hash_sha256": plan["plan_hash_sha256"],
            "deterministic_result_hash": observed_result_hash,
        },
        "source_probe_manifest": {
            "path": str(manifest_target),
            "file_sha256": sha256_file(manifest_target),
            "run_id": manifest["run_id"],
            "status": manifest["status"],
            "final": manifest["final"],
        },
        "source_probe_errors": {
            "path": str(errors_target),
            "file_sha256": errors_hash,
            "count": len(errors),
            "quote_ages_ms": sorted(quote_ages),
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
            "maximum_runs_for_new_plan_hash": 1,
            "normalized_output_schema_changed": False,
            "venue_universe_hypothesis_signal_cost_changed": False,
            "private_live_leverage_margin_changed": False,
        },
    }


def build_public_reader_contract(
    *,
    funding_client_path: str | Path,
    observer_runtime_path: str | Path,
    reliability_evidence_path: str | Path,
    contract_version: str = "v1",
    migration_probe_manifest_path: str | Path | None = None,
    depth_reference_path: str | Path | None = None,
    prior_contract_path: str | Path | None = None,
    freshness_failure_audit_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if contract_version not in CONTRACT_SCHEMAS:
        raise ValueError(
            f"unsupported public reader contract version: {contract_version}"
        )
    source_paths = [
        Path(funding_client_path).expanduser().resolve(),
        Path(observer_runtime_path).expanduser().resolve(),
    ]
    for source in source_paths:
        if not source.is_file():
            raise FileNotFoundError(source)
    reliability_path = Path(reliability_evidence_path).expanduser().resolve()
    reliability = _read_reliability_evidence(reliability_path)
    definitions = _venue_definitions(contract_version)
    payload: dict[str, Any] = {
        "schema": CONTRACT_SCHEMAS[contract_version],
        "contract_id": f"paper_public_reader_contract_{contract_version}",
        "status": STATUS,
        "scope": {
            "venues": list(VENUES),
            "market_type": "usdt_linear_perpetual",
            "transport": "https_public_rest",
            "methods": ["GET"],
            "network_requests_performed_while_building": 0,
            "maximum_authority": "PUBLIC_MARKET_DATA_READ_ONLY",
        },
        "transport_policy": {
            "requests_stack": "requests",
            "trust_env": False,
            "redirects_allowed": False,
            "tls_verification_required": True,
            "request_body_forbidden": True,
            "embedded_url_query_forbidden": True,
            "allowed_headers": sorted(ALLOWED_HEADER_NAMES),
            "private_headers_forbidden": sorted(PRIVATE_HEADER_NAMES),
            "private_query_parameters_forbidden": sorted(PRIVATE_QUERY_NAMES),
            "response_max_bytes": 8 * 1024 * 1024,
        },
        "venues": definitions,
        "normalization_contract": _normalization_contract(contract_version),
        "failure_policy": {
            "schema_mismatch": "STOPPED_INCOMPLETE",
            "host_path_method_or_parameter_not_allowlisted": "REJECT_BEFORE_NETWORK",
            "private_header_or_query_detected": "REJECT_BEFORE_NETWORK",
            "http_429_or_5xx": "BOUNDED_RETRY_THEN_DEGRADED_TRANSIENT",
            "timeout_or_transport_error": "BOUNDED_RETRY_THEN_DEGRADED_TRANSIENT",
            "persistent_stale_data": "STOPPED_INCOMPLETE",
            "partial_response": "AUDIT_ONLY_NO_OMS_TRANSITION",
        },
        "safety": {
            "public_get_requests_only": True,
            "credentials": False,
            "private_api_keys": False,
            "request_signing": False,
            "account_endpoints": False,
            "order_endpoints": False,
            "live_orders": False,
            "withdrawal_permission": False,
            "leverage": False,
            "margin": False,
            "grid_search": False,
            "retune": False,
            "automatic_live_promotion": False,
        },
        "reliability_evidence": {
            "path": str(reliability_path),
            "file_sha256": sha256_file(reliability_path),
            "verdict": reliability.get("verdict"),
            "historical_completion_rate": (
                reliability.get("historical_rest_collect") or {}
            ).get("completion_rate"),
            "pit_dual_venue_success_rate": (
                reliability.get("pit_snapshot_collect") or {}
            ).get("aggregate", {}).get("dual_venue_success_rate"),
            "production_sla": "UNPROVEN",
        },
        "source_provenance": [
            {"path": str(path), "sha256": sha256_file(path)}
            for path in source_paths
        ],
        "next_allowed_action": {
            "v1": "paper_public_reader_fixture_v1",
            "v2": "paper_public_reader_fixture_v2",
            "v3": "paper_public_readonly_probe_plan_v3",
        }[contract_version],
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if contract_version == "v2":
        if migration_probe_manifest_path is None:
            raise ValueError("v2 requires migration_probe_manifest_path")
        if depth_reference_path is None:
            raise ValueError("v2 requires depth_reference_path")
        payload["migration_evidence"] = _read_mexc_depth_migration_evidence(
            manifest_path=migration_probe_manifest_path,
            depth_reference_path=depth_reference_path,
        )
    elif contract_version == "v3":
        if prior_contract_path is None:
            raise ValueError("v3 requires prior_contract_path")
        if freshness_failure_audit_path is None:
            raise ValueError("v3 requires freshness_failure_audit_path")
        payload["migration_evidence"] = (
            _read_mexc_quote_freshness_migration_evidence(
                prior_contract_path=prior_contract_path,
                failure_audit_path=freshness_failure_audit_path,
            )
        )
    payload["contract_hash_sha256"] = contract_hash(payload)
    return payload


def validate_public_reader_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract_version = _contract_version(payload)
    if payload.get("contract_hash_sha256") != contract_hash(payload):
        raise ValueError("public reader contract hash mismatch")
    if payload.get("status") != STATUS:
        raise ValueError("public reader contract status changed")
    scope = payload.get("scope")
    if not isinstance(scope, Mapping):
        raise ValueError("public reader scope is missing")
    if scope.get("methods") != ["GET"]:
        raise ValueError("public reader method allowlist changed")
    if scope.get("network_requests_performed_while_building") != 0:
        raise ValueError("contract builder unexpectedly performed network requests")
    transport = payload.get("transport_policy")
    if not isinstance(transport, Mapping):
        raise ValueError("transport policy is missing")
    expected_transport = {
        "requests_stack": "requests",
        "trust_env": False,
        "redirects_allowed": False,
        "tls_verification_required": True,
        "request_body_forbidden": True,
        "embedded_url_query_forbidden": True,
        "allowed_headers": sorted(ALLOWED_HEADER_NAMES),
        "private_headers_forbidden": sorted(PRIVATE_HEADER_NAMES),
        "private_query_parameters_forbidden": sorted(PRIVATE_QUERY_NAMES),
        "response_max_bytes": 8 * 1024 * 1024,
    }
    if dict(transport) != expected_transport:
        raise ValueError("frozen public transport policy changed")
    if payload.get("venues") != _venue_definitions(contract_version):
        raise ValueError("frozen venue endpoint definitions changed")
    if payload.get("normalization_contract") != _normalization_contract(
        contract_version
    ):
        raise ValueError("frozen normalization contract changed")
    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        raise ValueError("public reader safety boundary is missing")
    expected_true = {"public_get_requests_only"}
    for key, value in safety.items():
        if bool(value) is not (key in expected_true):
            raise ValueError(f"public reader safety boundary changed: {key}")
    evidence = payload.get("reliability_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("public reader reliability evidence is missing")
    if evidence.get("production_sla") != "UNPROVEN":
        raise ValueError("public reader may not claim a production SLA")
    if contract_version == "v2":
        migration = payload.get("migration_evidence")
        if not isinstance(migration, Mapping):
            raise ValueError("v2 migration evidence is missing")
        source_probe = migration.get("source_probe_manifest")
        depth_reference = migration.get("depth_l1_reference")
        if not isinstance(source_probe, Mapping) or not isinstance(
            depth_reference, Mapping
        ):
            raise ValueError("v2 migration evidence bindings are missing")
        observed_migration = _read_mexc_depth_migration_evidence(
            manifest_path=str(source_probe.get("path") or ""),
            depth_reference_path=str(depth_reference.get("path") or ""),
        )
        if dict(migration) != observed_migration:
            raise ValueError("v2 migration evidence changed")
    elif contract_version == "v3":
        migration = payload.get("migration_evidence")
        if not isinstance(migration, Mapping):
            raise ValueError("v3 migration evidence is missing")
        prior_contract = migration.get("prior_contract")
        failure_audit = migration.get("source_failure_audit")
        if not isinstance(prior_contract, Mapping) or not isinstance(
            failure_audit, Mapping
        ):
            raise ValueError("v3 migration evidence bindings are missing")
        observed_migration = _read_mexc_quote_freshness_migration_evidence(
            prior_contract_path=str(prior_contract.get("path") or ""),
            failure_audit_path=str(failure_audit.get("path") or ""),
        )
        if dict(migration) != observed_migration:
            raise ValueError("v3 migration evidence changed")
    return copy.deepcopy(dict(payload))


def _match_path(template: str, path: str, *, venue: str) -> bool:
    escaped = re.escape(template)
    escaped = escaped.replace(
        re.escape("{symbol}"),
        f"(?P<symbol>{SYMBOL_PATTERNS[venue][1:-1]})",
    )
    return re.fullmatch(escaped, path) is not None


def _validate_query_value(name: str, value: Any, rule: Mapping[str, Any]) -> None:
    kind = rule.get("type")
    if kind == "integer":
        if isinstance(value, bool):
            raise ValueError(f"query parameter {name} must be an integer")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"query parameter {name} must be an integer") from exc
        if str(normalized) != str(value) and not isinstance(value, int):
            raise ValueError(f"query parameter {name} must be an integer")
        if "allowed_values" in rule and normalized not in rule["allowed_values"]:
            raise ValueError(f"query parameter {name} is not allowlisted")
        if normalized < int(rule.get("minimum", normalized)):
            raise ValueError(f"query parameter {name} is below minimum")
        if normalized > int(rule.get("maximum", normalized)):
            raise ValueError(f"query parameter {name} exceeds maximum")
        return
    if kind == "symbol":
        if re.fullmatch(str(rule["pattern"]), str(value)) is None:
            raise ValueError(f"query parameter {name} has invalid symbol")
        return
    raise ValueError(f"unsupported query parameter type: {name}")


def authorize_public_get(
    contract: Mapping[str, Any],
    *,
    venue: str,
    method: str,
    url: str,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    validated = validate_public_reader_contract(contract)
    venue_key = str(venue).strip().lower()
    if venue_key not in VENUES:
        raise ValueError("venue is not allowlisted")
    if method.strip().upper() != "GET":
        raise ValueError("only public GET requests are allowed")
    split = urlsplit(url)
    if split.username or split.password or split.fragment:
        raise ValueError("URL credentials and fragments are forbidden")
    if split.query:
        raise ValueError("embedded URL query is forbidden")
    venue_contract = validated["venues"][venue_key]
    base = urlsplit(venue_contract["base_url"])
    if (
        split.scheme.lower() != "https"
        or split.scheme.lower() != base.scheme.lower()
        or split.netloc.lower() != base.netloc.lower()
    ):
        raise ValueError("request host is not allowlisted")
    base_path = base.path.rstrip("/")
    if base_path and not split.path.startswith(base_path + "/"):
        raise ValueError("request API base path is not allowlisted")
    relative_path = split.path[len(base_path) :] if base_path else split.path
    endpoint = next(
        (
            item
            for item in venue_contract["endpoints"]
            if _match_path(
                item["request_schema"]["path_template"],
                relative_path,
                venue=venue_key,
            )
        ),
        None,
    )
    if endpoint is None:
        raise ValueError("request path is not allowlisted")
    normalized_headers = {str(key).strip().lower() for key in (headers or {})}
    if normalized_headers.intersection(PRIVATE_HEADER_NAMES):
        raise ValueError("private or signed request header is forbidden")
    if not normalized_headers.issubset(ALLOWED_HEADER_NAMES):
        raise ValueError("request header is not allowlisted")
    normalized_params = {str(key): value for key, value in (params or {}).items()}
    lowered_params = {key.lower() for key in normalized_params}
    if lowered_params.intersection(PRIVATE_QUERY_NAMES):
        raise ValueError("private or signed query parameter is forbidden")
    query_contract = endpoint["request_schema"]["query_parameters"]
    if not set(normalized_params).issubset(query_contract):
        raise ValueError("query parameter is not allowlisted")
    for name, rule in query_contract.items():
        if rule.get("required") and name not in normalized_params:
            raise ValueError(f"required query parameter is missing: {name}")
        if name in normalized_params:
            _validate_query_value(name, normalized_params[name], rule)
    deterministic = {
        "schema": "trading_mvp_public_get_authorization_v1",
        "decision": "AUTHORIZED_PUBLIC_GET",
        "venue": venue_key,
        "endpoint_id": endpoint["endpoint_id"],
        "contract_hash_sha256": validated["contract_hash_sha256"],
        "schema_hash_sha256": endpoint["schema_hash_sha256"],
        "network_request_performed": False,
    }
    return {
        **deterministic,
        "authorization_hash_sha256": sha256_json(deterministic),
    }


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
        description="Freeze a no-network public market-reader contract"
    )
    parser.add_argument("--funding-client", required=True)
    parser.add_argument("--observer-runtime", required=True)
    parser.add_argument("--reliability-evidence", required=True)
    parser.add_argument(
        "--contract-version",
        choices=tuple(CONTRACT_SCHEMAS),
        default="v1",
    )
    parser.add_argument("--migration-probe-manifest")
    parser.add_argument("--depth-reference")
    parser.add_argument("--prior-contract")
    parser.add_argument("--freshness-failure-audit")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    contract = build_public_reader_contract(
        funding_client_path=args.funding_client,
        observer_runtime_path=args.observer_runtime,
        reliability_evidence_path=args.reliability_evidence,
        contract_version=args.contract_version,
        migration_probe_manifest_path=args.migration_probe_manifest,
        depth_reference_path=args.depth_reference,
        prior_contract_path=args.prior_contract,
        freshness_failure_audit_path=args.freshness_failure_audit,
    )
    validate_public_reader_contract(contract)
    _write_json_immutable(args.output, contract)
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
