from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from gate_historical_archive import (
    ARCHIVE_BASE_URL,
    build_gate_archive_url,
    month_keys_for_range,
)


SCHEMA = "trading_mvp_gate_historical_membership_history_plan_v1"
PROBE_SCHEMA = "trading_mvp_gate_historical_membership_probe_v2"
PROBE_ACCEPTED_DECISION = "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_ACCEPTED_READY_FOR_BACKFILL_PLANONLY"
HISTORY_PLAN_DECISION = "GATE_MEMBERSHIP_HISTORY_PLAN_READY_AWAITING_EXPLICIT_VISIBLE_COLLECT_APPROVAL"
INSUFFICIENT_UNIVERSE_DECISION = "INSUFFICIENT_EXECUTABLE_GATE_MEMBERSHIP_HISTORY_UNIVERSE"
HYPOTHESIS_ID = "cross_sectional_momentum_daily_survivorship_repair_v1"
MAX_RUNTIME_SEC = 7200
DAY_SEC = 86_400
WARMUP_DAYS = 30
TRAIN_DAYS = 140
OOS_DAYS = 210
OOS_FOLDS = 5
OOS_FOLD_DAYS = 42
HISTORY_DAYS = WARMUP_DAYS + TRAIN_DAYS + OOS_DAYS
MINIMUM_CANONICAL_ASSETS = 20
ARCHIVE_TYPES = ("candlesticks_1h", "funding_applies")

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+$")
_STABLE_SYMBOLS = frozenset(
    {
        "BUSD",
        "DAI",
        "FDUSD",
        "FRAX",
        "GUSD",
        "PYUSD",
        "TUSD",
        "USDC",
        "USDD",
        "USDE",
        "USDP",
        "USDS",
        "USDT",
        "USDX",
    }
)
_WRAPPED_OR_STAKED_SYMBOLS = frozenset(
    {
        "CBETH",
        "RETH",
        "STETH",
        "WBETH",
        "WBTC",
        "WETH",
        "WSTETH",
    }
)
_NON_CRYPTO_NAME_TERMS = (
    "commodity",
    "etf",
    "index",
    "pre-market",
    "pre market",
    "stock",
    "tokenized equity",
    "tokenized stock",
)
_WRAPPED_OR_STAKED_NAME_TERMS = (
    "liquid staked",
    "liquid staking",
    "staked ",
    "wrapped ",
)
_LP_NAME_TERMS = (" liquidity pool", " lp token", "pool token")
_LEVERAGED_NAME_TERMS = (" leveraged", "2x ", "3x ", "5x ")


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {resolved}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _probe_payload_for_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
    }


def history_plan_payload_for_hash(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {"schema", "generated_at_utc", "plan_hash", "approval_phrase"}
    }


def authorize_history_collect(
    plan_path: str | Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    plan = _read_json_object(plan_path)
    if plan.get("schema") != SCHEMA:
        raise ValueError("unexpected history plan schema")
    stored_hash = str(plan.get("plan_hash") or "")
    computed_hash = sha256_json(history_plan_payload_for_hash(plan))
    if stored_hash != computed_hash or stored_hash != str(expected_plan_hash):
        raise ValueError("history plan hash mismatch")
    if plan.get("decision") != HISTORY_PLAN_DECISION:
        raise ValueError("history plan is not approved for collection planning")
    if plan.get("next_allowed_command") != "fast-edge-membership-history-collect":
        raise ValueError("history plan does not allow collection")
    code = plan.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("history plan code provenance is missing")
    if str(code.get("module_sha256") or "") != sha256_file(Path(__file__).resolve()):
        raise ValueError("history plan module hash no longer matches")
    archive_module_path = Path(sys.modules[build_gate_archive_url.__module__].__file__).resolve()
    if str(code.get("archive_module_sha256") or "") != sha256_file(archive_module_path):
        raise ValueError("history archive module hash no longer matches")
    for path_key, hash_key, file_name in (
        ("collector_module_path", "collector_module_sha256", "gate_historical_membership_history_collector.py"),
        ("quality_module_path", "quality_module_sha256", "gate_historical_membership_history_quality.py"),
        ("momentum_core_module_path", "momentum_core_module_sha256", "gate_membership_momentum.py"),
        ("train_module_path", "train_module_sha256", "gate_membership_momentum_train.py"),
        ("oos_module_path", "oos_module_sha256", "gate_membership_momentum_oos.py"),
    ):
        module_path = Path(str(code.get(path_key) or "")).expanduser().resolve()
        expected_path = Path(__file__).resolve().with_name(file_name)
        if module_path != expected_path or not module_path.is_file():
            raise ValueError(f"history pipeline module path mismatch: {file_name}")
        if str(code.get(hash_key) or "") != sha256_file(module_path):
            raise ValueError(f"history pipeline module hash no longer matches: {file_name}")
    tasks = plan.get("archive_tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("history plan archive tasks are missing")
    cache_keys: set[str] = set()
    for raw in tasks:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid archive task")
        archive_type = str(raw.get("archive_type") or "")
        symbol = str(raw.get("symbol") or "")
        year_month = str(raw.get("year_month") or "")
        expected_url = build_gate_archive_url(archive_type, symbol, year_month)
        if str(raw.get("url") or "") != expected_url:
            raise ValueError("archive task URL mismatch")
        cache_key = str(raw.get("cache_key") or "")
        expected_cache_key = sha256_json(
            {
                "exchange": "gateio",
                "symbol": symbol,
                "archive_type": archive_type,
                "year_month": year_month,
            }
        )
        if cache_key != expected_cache_key or cache_key in cache_keys:
            raise ValueError("archive task cache key mismatch or duplicate")
        cache_keys.add(cache_key)
    return plan


def validate_probe_report(
    probe_report_path: str | Path,
    *,
    expected_probe_plan_hash: str,
    expected_probe_artifact_hash: str,
) -> dict[str, Any]:
    report = _read_json_object(probe_report_path)
    if report.get("schema") != PROBE_SCHEMA:
        raise ValueError("unexpected membership probe schema")
    if str(report.get("plan_hash") or "") != str(expected_probe_plan_hash):
        raise ValueError("probe plan hash mismatch")
    stored_hash = str(report.get("artifact_hash") or "")
    computed_hash = sha256_json(_probe_payload_for_hash(report))
    if stored_hash != computed_hash or stored_hash != str(expected_probe_artifact_hash):
        raise ValueError("probe artifact hash mismatch")
    if (
        report.get("final") is not True
        or report.get("accepted") is not True
        or report.get("decision") != PROBE_ACCEPTED_DECISION
    ):
        raise ValueError("probe is not accepted and final")
    rows = report.get("rows")
    if not isinstance(rows, list):
        raise ValueError("accepted probe rows are missing")
    return report


def _identity_exclusion_reason(name: str, symbol: str) -> str | None:
    normalized_name = " ".join(str(name).strip().lower().split())
    normalized_symbol = str(symbol).strip().upper()
    if normalized_symbol in _STABLE_SYMBOLS or "stablecoin" in normalized_name:
        return "stable_asset"
    if normalized_symbol in _WRAPPED_OR_STAKED_SYMBOLS or any(
        term in normalized_name for term in _WRAPPED_OR_STAKED_NAME_TERMS
    ):
        return "wrapped_or_staked_asset"
    if any(term in normalized_name for term in _NON_CRYPTO_NAME_TERMS):
        return "non_crypto_or_tokenized_asset"
    if any(term in normalized_name for term in _LP_NAME_TERMS):
        return "lp_asset"
    if any(term in normalized_name for term in _LEVERAGED_NAME_TERMS) or re.search(
        r"(?:BULL|BEAR|[235][LS])$", normalized_symbol
    ):
        return "leveraged_asset"
    return None


def load_unique_coin_registry(
    coin_registry_path: str | Path,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    resolved = Path(coin_registry_path).expanduser().resolve()
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    try:
        with resolved.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"name", "symbol", "coin_id"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError("coin registry must contain name, symbol and coin_id")
            for raw in reader:
                symbol = str(raw.get("symbol") or "").strip().upper()
                coin_id = str(raw.get("coin_id") or "").strip()
                name = str(raw.get("name") or "").strip()
                if not symbol or not coin_id or not _SYMBOL_PATTERN.fullmatch(symbol):
                    continue
                grouped[symbol].append({"name": name, "symbol": symbol, "coin_id": coin_id})
    except OSError as exc:
        raise ValueError(f"cannot read coin registry: {resolved}") from exc

    unique: dict[str, dict[str, str]] = {}
    excluded: dict[str, str] = {}
    for symbol in sorted(grouped):
        rows = grouped[symbol]
        coin_ids = {row["coin_id"] for row in rows}
        if len(rows) != 1 or len(coin_ids) != 1:
            excluded[symbol] = "ticker_collision"
            continue
        row = rows[0]
        reason = _identity_exclusion_reason(row["name"], symbol)
        if reason:
            excluded[symbol] = reason
            continue
        unique[symbol] = {
            **row,
            "canonical_asset_id": f"coingecko:{row['coin_id']}",
        }
    return unique, excluded


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def _history_window(daily_manifest: Mapping[str, Any]) -> tuple[int, int]:
    if daily_manifest.get("schema") != "daily_collect_v1":
        raise ValueError("unexpected daily manifest schema")
    params = daily_manifest.get("params")
    if not isinstance(params, Mapping):
        raise ValueError("daily manifest params are missing")
    raw_end = _as_int(params.get("end_sec"))
    if raw_end is None:
        raise ValueError("daily manifest end_sec is missing")
    end_sec = (raw_end // DAY_SEC) * DAY_SEC
    start_sec = end_sec - HISTORY_DAYS * DAY_SEC
    if start_sec < 0:
        raise ValueError("invalid historical window")
    return start_sec, end_sec


def _split_contract(window_start: int, window_end: int) -> dict[str, Any]:
    start = int(window_start)
    end = int(window_end)
    if end - start != HISTORY_DAYS * DAY_SEC:
        raise ValueError("history window does not match frozen split horizon")
    warmup_end = start + WARMUP_DAYS * DAY_SEC
    train_end = warmup_end + TRAIN_DAYS * DAY_SEC
    if train_end + OOS_DAYS * DAY_SEC != end:
        raise ValueError("frozen history split does not cover the history window")
    return {
        "warmup": {"start_sec": start, "end_sec": warmup_end, "days": WARMUP_DAYS},
        "train": {"start_sec": warmup_end, "end_sec": train_end, "days": TRAIN_DAYS},
        "oos": {
            "start_sec": train_end,
            "end_sec": end,
            "days": OOS_DAYS,
            "folds": OOS_FOLDS,
            "fold_days": OOS_FOLD_DAYS,
        },
    }


def select_history_universe(
    probe_rows: list[Any],
    registry: Mapping[str, Mapping[str, str]],
    registry_exclusions: Mapping[str, str],
    *,
    window_start_sec: int,
    window_end_sec: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    seen_symbols: set[str] = set()
    for raw in probe_rows:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()
        base = str(raw.get("base") or "").strip().upper()
        if not symbol or not base:
            continue
        if symbol in seen_symbols:
            excluded.append({"symbol": symbol, "base": base, "reason": "duplicate_probe_symbol"})
            continue
        seen_symbols.add(symbol)
        if raw.get("quote") != "USDT" or raw.get("instrument_type") != "linear_perpetual":
            excluded.append({"symbol": symbol, "base": base, "reason": "unsupported_instrument"})
            continue
        if str(raw.get("contract_type") or "crypto").lower() != "crypto":
            excluded.append({"symbol": symbol, "base": base, "reason": "non_crypto_contract"})
            continue
        try:
            contract_multiplier = float(raw.get("contract_multiplier"))
        except (TypeError, ValueError, OverflowError):
            contract_multiplier = 0.0
        if contract_multiplier <= 0:
            excluded.append({"symbol": symbol, "base": base, "reason": "missing_contract_multiplier"})
            continue
        listed_from = _as_int(raw.get("listed_from_ts"))
        listed_to = _as_int(raw.get("listed_to_ts"))
        if listed_from is None:
            excluded.append({"symbol": symbol, "base": base, "reason": "missing_lifecycle_start"})
            continue
        if listed_from >= window_end_sec or (listed_to is not None and listed_to <= window_start_sec):
            excluded.append({"symbol": symbol, "base": base, "reason": "outside_history_window"})
            continue
        identity = registry.get(base)
        if identity is None:
            reason = registry_exclusions.get(base, "not_in_frozen_non_binance_registry")
            excluded.append({"symbol": symbol, "base": base, "reason": reason})
            continue
        clipped_start = max(window_start_sec, listed_from)
        clipped_end = min(window_end_sec, listed_to) if listed_to is not None else window_end_sec
        if clipped_end <= clipped_start:
            excluded.append({"symbol": symbol, "base": base, "reason": "empty_lifecycle_overlap"})
            continue
        eligible.append(
            {
                "exchange": "gateio",
                "symbol": symbol,
                "base": base,
                "quote": "USDT",
                "canonical_asset_id": identity["canonical_asset_id"],
                "coin_id": identity["coin_id"],
                "name": identity["name"],
                "listed_from_ts": listed_from,
                "listed_to_ts": listed_to,
                "history_start_sec": clipped_start,
                "history_end_sec": clipped_end,
                "lifecycle_status": str(raw.get("lifecycle_status") or "unknown"),
                "active_at_snapshot": raw.get("active_at_snapshot") is True,
                "contract_multiplier": contract_multiplier,
                "funding_interval_sec": _as_int(raw.get("funding_interval_sec")),
                "order_size_min_contracts": raw.get("order_size_min_contracts"),
                "order_size_max_contracts": raw.get("order_size_max_contracts"),
                "quote_volume_formula": "volume_contracts * close_price * contract_multiplier",
                "non_binance_evidence": "frozen_current_registry_reference_only",
            }
        )
    eligible.sort(key=lambda row: (row["canonical_asset_id"], row["symbol"]))
    excluded.sort(key=lambda row: (row["reason"], row["symbol"]))
    return eligible, excluded


def build_archive_tasks(universe: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in universe:
        start_sec = int(row["history_start_sec"])
        end_sec = int(row["history_end_sec"])
        for month in month_keys_for_range(start_sec, end_sec):
            for archive_type in ARCHIVE_TYPES:
                tasks.append(
                    {
                        "exchange": "gateio",
                        "symbol": row["symbol"],
                        "canonical_asset_id": row["canonical_asset_id"],
                        "archive_type": archive_type,
                        "year_month": month,
                        "url": build_gate_archive_url(archive_type, str(row["symbol"]), month),
                        "cache_key": sha256_json(
                            {
                                "exchange": "gateio",
                                "symbol": row["symbol"],
                                "archive_type": archive_type,
                                "year_month": month,
                            }
                        ),
                    }
                )
    return sorted(tasks, key=lambda row: (row["symbol"], row["year_month"], row["archive_type"]))


def build_history_plan(
    *,
    probe_report_path: str | Path,
    expected_probe_plan_hash: str,
    expected_probe_artifact_hash: str,
    daily_manifest_path: str | Path,
    coin_registry_path: str | Path,
    output_path: str | Path | None,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")

    resolved_probe = Path(probe_report_path).expanduser().resolve()
    resolved_manifest = Path(daily_manifest_path).expanduser().resolve()
    resolved_registry = Path(coin_registry_path).expanduser().resolve()
    probe = validate_probe_report(
        resolved_probe,
        expected_probe_plan_hash=expected_probe_plan_hash,
        expected_probe_artifact_hash=expected_probe_artifact_hash,
    )
    daily_manifest = _read_json_object(resolved_manifest)
    window_start, window_end = _history_window(daily_manifest)
    registry, registry_exclusions = load_unique_coin_registry(resolved_registry)
    eligible, excluded = select_history_universe(
        list(probe["rows"]),
        registry,
        registry_exclusions,
        window_start_sec=window_start,
        window_end_sec=window_end,
    )
    tasks = build_archive_tasks(eligible)
    ready = len(eligible) >= MINIMUM_CANONICAL_ASSETS and bool(tasks)
    decision = HISTORY_PLAN_DECISION if ready else INSUFFICIENT_UNIVERSE_DECISION
    next_command = (
        "fast-edge-membership-history-collect"
        if ready
        else "none_membership_history_branch_closed"
    )

    module_path = Path(__file__).resolve()
    archive_module_path = Path(sys.modules[build_gate_archive_url.__module__].__file__).resolve()
    collector_module_path = module_path.with_name("gate_historical_membership_history_collector.py")
    quality_module_path = module_path.with_name("gate_historical_membership_history_quality.py")
    momentum_core_module_path = module_path.with_name("gate_membership_momentum.py")
    train_module_path = module_path.with_name("gate_membership_momentum_train.py")
    oos_module_path = module_path.with_name("gate_membership_momentum_oos.py")
    if not all(
        path.is_file()
        for path in (
            collector_module_path,
            quality_module_path,
            momentum_core_module_path,
            train_module_path,
            oos_module_path,
        )
    ):
        raise ValueError("history collector, quality and train modules must exist before freezing the plan")
    split_contract = _split_contract(window_start, window_end)
    contract: dict[str, Any] = {
        "run_id": normalized_run_id,
        "mode": "gate_historical_membership_history_planonly",
        "hypothesis_id": HYPOTHESIS_ID,
        "decision": decision,
        "research_only": True,
        "public_data_only": True,
        "network_calls_now": False,
        "collect_allowed_now": False,
        "grid_search": False,
        "retune": False,
        "oos_allowed_now": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "evidence_scope": "gate_only_weaker_evidence",
        "strategy_contract": {
            "family": "daily_cross_sectional_momentum",
            "purpose": "survivorship_repair_data_backfill_only",
            "frozen_parameters": {
                "lookback_days": 30,
                "hold_days": 7,
                "rebalance_every_days": 7,
                "min_per_side": 5,
                "minimum_scored_markets": 20,
                "bucket_rule": "max(min_per_side,floor(scored_markets/10))",
                "liquidity_lookback_days": 7,
                "minimum_median_quote_volume": 1_000_000.0,
                "signal_price": "closed_daily_close",
                "entry_price": "next_closed_daily_open",
                "exit_price": "daily_open_after_hold_days",
                "parameter_selection": "forbidden",
            },
            "evaluation_not_authorized_by_this_plan": True,
        },
        "history_window": {
            "start_sec": window_start,
            "end_sec": window_end,
            "days": HISTORY_DAYS,
            "end_policy": "last_closed_utc_day_from_frozen_daily_manifest",
        },
        "split_contract": split_contract,
        "input_provenance": {
            "probe_report_path": str(resolved_probe),
            "probe_report_sha256": sha256_file(resolved_probe),
            "probe_plan_hash": expected_probe_plan_hash,
            "probe_artifact_hash": expected_probe_artifact_hash,
            "daily_manifest_path": str(resolved_manifest),
            "daily_manifest_sha256": sha256_file(resolved_manifest),
            "coin_registry_path": str(resolved_registry),
            "coin_registry_sha256": sha256_file(resolved_registry),
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
            "archive_module_path": str(archive_module_path),
            "archive_module_sha256": sha256_file(archive_module_path),
            "collector_module_path": str(collector_module_path),
            "collector_module_sha256": sha256_file(collector_module_path),
            "quality_module_path": str(quality_module_path),
            "quality_module_sha256": sha256_file(quality_module_path),
            "momentum_core_module_path": str(momentum_core_module_path),
            "momentum_core_module_sha256": sha256_file(momentum_core_module_path),
            "train_module_path": str(train_module_path),
            "train_module_sha256": sha256_file(train_module_path),
            "oos_module_path": str(oos_module_path),
            "oos_module_sha256": sha256_file(oos_module_path),
        },
        "source_contract": {
            "exchange": "gateio",
            "archive_base_url": ARCHIVE_BASE_URL,
            "archive_types": list(ARCHIVE_TYPES),
            "contract_multiplier_source": "accepted_membership_v2_probe",
            "quote_volume_formula": "volume_contracts * close_price * contract_multiplier",
            "cache_policy": "reuse_only_on_exact_plan_and_cache_key_match",
            "open_or_partial_month_policy": "reject_rows_after_history_end",
            "missing_file_policy": "record_missing_never_interpolate",
        },
        "identity_contract": {
            "join": "unique_uppercase_base_to_frozen_coin_id",
            "canonical_asset_id": "coingecko:<coin_id>",
            "ticker_collisions": "excluded",
            "stable_wrapped_staked_lp_leveraged_non_crypto": "excluded",
            "binance_scope": "frozen_current_non_binance_registry_reference_only",
            "historical_binance_membership_proven": False,
        },
        "universe": {
            "minimum_canonical_assets": MINIMUM_CANONICAL_ASSETS,
            "eligible_count": len(eligible),
            "excluded_count": len(excluded),
            "eligible": eligible,
            "excluded": excluded,
        },
        "archive_tasks": tasks,
        "archive_task_summary": {
            "tasks": len(tasks),
            "symbols": len({task["symbol"] for task in tasks}),
            "months": len({task["year_month"] for task in tasks}),
            "types": list(ARCHIVE_TYPES),
        },
        "runtime_contract": {
            "max_runtime_sec": runtime,
            "absolute_cap_sec": MAX_RUNTIME_SEC,
            "visible_terminal_required": True,
            "single_market_data_writer": True,
            "timeout_verdict": "STOPPED_INCOMPLETE",
        },
        "future_history_quality_gates": {
            "minimum_canonical_assets": MINIMUM_CANONICAL_ASSETS,
            "minimum_series_coverage": 0.98,
            "no_interpolation": True,
            "no_duplicate_timestamps": True,
            "no_open_rows": True,
            "lifecycle_mask_required": True,
            "point_in_time_membership_required": True,
            "positive_contract_multiplier_required": True,
            "physical_train_oos_split_required": True,
            "train_view_must_not_expose_oos_paths": True,
            "minimum_scored_markets_per_rebalance": 20,
        },
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_read": False,
            "oos_metrics_read": False,
        },
        "limitations": [
            "Gate-only history is weaker evidence and does not establish MEXC portability.",
            "The frozen registry proves current reference exclusion, not historical Binance membership.",
            "Archive availability and row coverage remain unproven until a separate visible collect and quality gate.",
            "This plan cannot authorize momentum evaluation, OOS, probe, paper-forward or live trading.",
        ],
        "next_allowed_command": next_command,
        "blocked_actions": [
            "history_collect_without_exact_hash_bound_approval",
            "momentum_evaluation_before_history_quality",
            "oos",
            "grid_search",
            "retune",
            "execution_probe",
            "paper_forward",
            "live_orders",
            "private_api_keys",
        ],
    }
    contract["input_merkle_sha256"] = sha256_json(
        {
            "probe_artifact_hash": expected_probe_artifact_hash,
            "daily_manifest_sha256": contract["input_provenance"]["daily_manifest_sha256"],
            "coin_registry_sha256": contract["input_provenance"]["coin_registry_sha256"],
            "module_sha256": contract["code_provenance"]["module_sha256"],
            "archive_module_sha256": contract["code_provenance"]["archive_module_sha256"],
            "collector_module_sha256": contract["code_provenance"]["collector_module_sha256"],
            "quality_module_sha256": contract["code_provenance"]["quality_module_sha256"],
            "momentum_core_module_sha256": contract["code_provenance"]["momentum_core_module_sha256"],
            "train_module_sha256": contract["code_provenance"]["train_module_sha256"],
            "oos_module_sha256": contract["code_provenance"]["oos_module_sha256"],
        }
    )
    plan_hash = sha256_json(contract)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": generated_at_utc or _utc_now(),
        **contract,
        "plan_hash": plan_hash,
    }
    if ready:
        payload["approval_phrase"] = (
            "Подтверждаю visible Gate membership-history collect "
            f"plan_hash={plan_hash}, run_id={normalized_run_id}, MaxRuntimeSec={runtime}, "
            "public archive only, без returns/OOS/grid/live/private API keys."
        )
    if output_path is not None:
        _atomic_write_json(Path(output_path).expanduser().resolve(), payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate historical-membership archive PlanOnly")
    parser.add_argument("--probe-report", required=True)
    parser.add_argument("--expected-probe-plan-hash", required=True)
    parser.add_argument("--expected-probe-artifact-hash", required=True)
    parser.add_argument("--daily-manifest", required=True)
    parser.add_argument("--coin-registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    args = parser.parse_args()
    result = build_history_plan(
        probe_report_path=args.probe_report,
        expected_probe_plan_hash=args.expected_probe_plan_hash,
        expected_probe_artifact_hash=args.expected_probe_artifact_hash,
        daily_manifest_path=args.daily_manifest,
        coin_registry_path=args.coin_registry,
        output_path=args.output,
        run_id=args.run_id,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
