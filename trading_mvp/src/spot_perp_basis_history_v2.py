from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

from costs import base_api_cost_profile, route_legs, validate_runtime_sec
from gate_historical_archive import build_gate_archive_url, build_gate_spot_archive_url
from historical_basis_v2_preflight import classify_excluded_categories


HYPOTHESIS_ID = "gate_spot_perp_basis_convergence_history_v2"
DATA_TYPE = "GATE_SPOT_PERP_ARCHIVE_1H_V1"
PREFLIGHT_SCHEMA = "trading_mvp_gate_spot_perp_history_preflight_v2"
PLAN_SCHEMA = "trading_mvp_gate_spot_perp_history_plan_v2"
PREFLIGHT_DECISION_READY = "GATE_SPOT_PERP_HISTORY_READY_FOR_PLANONLY"
PREFLIGHT_DECISION_INSUFFICIENT = "INSUFFICIENT_EXECUTABLE_UNIVERSE"
PREFLIGHT_DECISION_INCOMPLETE = "STOPPED_INCOMPLETE"
MINIMUM_ASSETS = 8
PRIMARY_ASSETS = 12
RESERVE_ASSETS = 8
MAX_PLAN_ASSETS = PRIMARY_ASSETS + RESERVE_ASSETS
DAY_SEC = 86_400
HOUR_SEC = 3_600
HISTORY_DAYS = 220
WARMUP_DAYS = 20
TRAIN_DAYS = 100
OOS_DAYS = 100
ARCHIVE_SERIES = ("spot_trade", "perp_trade", "perp_mark", "funding")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _registry_index(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        coin_id = str(row.get("coin_id") or "").strip()
        if symbol and coin_id:
            grouped.setdefault(symbol, []).append(row)
    collisions = {
        symbol
        for symbol, values in grouped.items()
        if len({str(value.get("coin_id") or "").strip() for value in values}) != 1
    }
    return {symbol: values[0] for symbol, values in grouped.items() if symbol not in collisions}, collisions


def _pit_gate_rows(pit_state: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    if pit_state.get("schema") != "pit_universe_state_v1":
        raise ValueError("expected pit_universe_state_v1")
    symbols = pit_state.get("symbols")
    if not isinstance(symbols, Mapping):
        raise ValueError("PIT symbols are missing")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in symbols.values():
        row = item.get("row") if isinstance(item, Mapping) else None
        if not isinstance(row, Mapping) or str(row.get("exchange") or "").lower() != "gateio":
            continue
        base = str(row.get("base") or "").strip().upper()
        if base:
            grouped.setdefault(base, []).append(row)
    collisions = {base for base, rows in grouped.items() if len(rows) != 1}
    return {base: rows[0] for base, rows in grouped.items() if base not in collisions}, collisions


def build_candidate_pool(
    *,
    pit_state: Mapping[str, Any],
    registry_rows: Iterable[Mapping[str, Any]],
    gate_spot_pairs: Iterable[Mapping[str, Any]],
    gate_spot_tickers: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    registry, registry_collisions = _registry_index(registry_rows)
    pit_rows, pit_collisions = _pit_gate_rows(pit_state)
    spot_pairs = {
        str(row.get("base") or "").strip().upper(): str(row.get("id") or "").strip().upper()
        for row in gate_spot_pairs
        if str(row.get("quote") or "").strip().upper() == "USDT"
        and str(row.get("trade_status") or "").strip().lower() == "tradable"
        and str(row.get("base") or "").strip()
    }
    spot_volume = {
        str(row.get("currency_pair") or "").strip().upper(): _as_float(row.get("quote_volume"))
        for row in gate_spot_tickers
        if str(row.get("currency_pair") or "").strip()
    }
    rejected: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    for base in sorted(set(pit_rows) | pit_collisions):
        if base in pit_collisions:
            rejected["venue_symbol_collision"] += 1
            continue
        if re.fullmatch(r"[A-Z0-9]+", base) is None:
            rejected["invalid_symbol"] += 1
            continue
        row = pit_rows[base]
        if base in registry_collisions:
            rejected["identity_collision"] += 1
            continue
        identity = registry.get(base)
        if identity is None:
            rejected["identity_unmatched"] += 1
            continue
        if (
            str(row.get("quote") or "").upper() != "USDT"
            or str(row.get("contract_type") or "").lower() != "linear_perp"
            or str(row.get("status") or "").lower() != "trading"
            or row.get("listed_now") is not True
            or row.get("inactive_or_delisted") is True
            or row.get("tombstone") is True
        ):
            rejected["lifecycle"] += 1
            continue
        if row.get("eligible_non_binance_spot") is not True or row.get("binance_spot_listed") is not False:
            rejected["binance_spot_or_unverified"] += 1
            continue
        categories = classify_excluded_categories(
            str(identity.get("name") or ""),
            base,
            str(identity.get("coin_id") or ""),
        )
        identity_text = " ".join(
            (str(identity.get("name") or ""), str(identity.get("coin_id") or ""))
        ).lower()
        if base in {"XAU", "XAG", "GOLD", "SILVER"} or any(
            term in identity_text
            for term in ("tokenized gold", "tether gold", "pax gold", "gold token", "silver token")
        ):
            categories = sorted(set(categories) | {"tokenized_commodity"})
        if categories:
            rejected["excluded_category"] += 1
            continue
        spot_symbol = spot_pairs.get(base)
        if not spot_symbol:
            rejected["gate_spot_unavailable"] += 1
            continue
        spot_quote_volume = spot_volume.get(spot_symbol)
        perp_quote_volume = _as_float(row.get("volume_24h_quote"))
        if spot_quote_volume is None or spot_quote_volume <= 0 or perp_quote_volume is None or perp_quote_volume <= 0:
            rejected["current_liquidity_metadata_missing"] += 1
            continue
        try:
            registry_rank = int(str(identity.get("rank") or "999999"))
        except ValueError:
            registry_rank = 999_999
        candidates.append(
            {
                "canonical_asset_id": f"coingecko:{identity['coin_id']}",
                "base": base,
                "quote": "USDT",
                "gate_spot_symbol": spot_symbol,
                "gate_perp_symbol": str(row.get("symbol") or f"{base}_USDT").upper(),
                "identity_name": identity.get("name"),
                "identity_source": "coingecko_coin_id_unique_symbol_join",
                "registry_rank": registry_rank,
                "binance_spot": False,
                "categories": [],
                "spot_quote_volume_24h": spot_quote_volume,
                "perp_quote_volume_24h": perp_quote_volume,
                "minimum_current_quote_volume": min(spot_quote_volume, perp_quote_volume),
            }
        )
    candidates.sort(
        key=lambda item: (-float(item["minimum_current_quote_volume"]), int(item["registry_rank"]), item["canonical_asset_id"])
    )
    return candidates, dict(sorted(rejected.items()))


def required_archive_urls(base: str, oldest_month: str) -> dict[str, str]:
    symbol = f"{str(base).strip().upper()}_USDT"
    return {
        "spot_trade": build_gate_spot_archive_url("candlesticks_1h", symbol, oldest_month),
        "perp_trade": build_gate_archive_url("candlesticks_1h", symbol, oldest_month),
        "perp_mark": build_gate_archive_url("mark_prices", symbol, oldest_month),
        "funding": build_gate_archive_url("funding_applies", symbol, oldest_month),
    }


def assess_archive_availability(
    candidates: Sequence[Mapping[str, Any]],
    head_results: Mapping[str, Mapping[str, Any]],
    *,
    oldest_month: str,
    minimum_assets: int = MINIMUM_ASSETS,
) -> dict[str, Any]:
    if minimum_assets < 1:
        raise ValueError("minimum_assets must be positive")
    eligible: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    audited: list[dict[str, Any]] = []
    for raw in candidates:
        row = dict(raw)
        urls = required_archive_urls(str(row.get("base") or ""), oldest_month)
        series: dict[str, dict[str, Any]] = {}
        available = True
        for name, url in urls.items():
            result = dict(head_results.get(url) or {})
            status = int(result.get("status") or 0)
            series[name] = {
                "url": url,
                "status": status,
                "content_length": int(result.get("content_length") or 0),
                "error": result.get("error"),
            }
            if status != 200:
                available = False
        row["archive_boundary"] = {
            "oldest_month": oldest_month,
            "proof_level": "monthly_file_presence_only_exact_coverage_deferred_to_quality",
            "all_required_series_present": available,
            "series": series,
        }
        audited.append(row)
        if available:
            eligible.append(row)
        else:
            rejected["archive_boundary_missing"] += 1
    decision = PREFLIGHT_DECISION_READY if len(eligible) >= minimum_assets else PREFLIGHT_DECISION_INSUFFICIENT
    return {
        "decision": decision,
        "minimum_assets": minimum_assets,
        "audited_assets": audited,
        "eligible_assets": eligible,
        "eligible_asset_count": len(eligible),
        "rejected_by_reason": dict(sorted(rejected.items())),
        "primary_assets": eligible[:PRIMARY_ASSETS],
        "reserve_assets": eligible[PRIMARY_ASSETS:MAX_PLAN_ASSETS],
    }


def _sealed_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "hypothesis",
        "universe",
        "strategy",
        "economics",
        "sample_plan",
        "quality_gates",
        "acceptance_gates",
        "runtime",
        "safety",
        "input_hashes",
    )
    return {key: plan[key] for key in keys}


def build_gate_spot_perp_plan(
    preflight: Mapping[str, Any],
    *,
    max_runtime_sec: int = 600,
) -> dict[str, Any]:
    runtime = validate_runtime_sec(max_runtime_sec)
    if preflight.get("schema") != PREFLIGHT_SCHEMA or preflight.get("final") is not True:
        raise ValueError("unexpected or incomplete Gate spot/perp preflight")
    if preflight.get("decision") != PREFLIGHT_DECISION_READY:
        raise ValueError("Gate spot/perp preflight is not ready")
    invalidation = preflight.get("prior_rejection_invalidation")
    if not isinstance(invalidation, Mapping) or invalidation.get("invalidated") is not True:
        raise ValueError("prior technical rejection invalidation is not proven")
    eligible = [dict(row) for row in preflight.get("eligible_assets") or []]
    if len(eligible) < MINIMUM_ASSETS:
        raise ValueError(f"INSUFFICIENT_EXECUTABLE_UNIVERSE: need {MINIMUM_ASSETS}, observed {len(eligible)}")
    selected = eligible[:MAX_PLAN_ASSETS]
    profile = replace(base_api_cost_profile(), maker_fill_probability=0.0)
    legs = route_legs("same_venue_gateio_spot_perp", profile=profile)
    normal_cost = profile.cycle_cost(legs)
    stress_cost = profile.cycle_cost(legs, stress=True)
    exit_threshold_bps = 20.0
    safety_margin_bps = 20.0
    entry_threshold_bps = float(stress_cost["total_bps"]) + exit_threshold_bps + safety_margin_bps
    window = preflight.get("frozen_window") if isinstance(preflight.get("frozen_window"), Mapping) else {}
    window_start_sec = int(window.get("start_sec") or 0)
    window_end_sec = int(window.get("end_sec") or HISTORY_DAYS * DAY_SEC)
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "generated_at_utc": _utc_now(),
        "final": True,
        "hypothesis": {
            "id": HYPOTHESIS_ID,
            "venue": "gateio",
            "allowed_project_venues": ["mexc", "gateio"],
            "data_type": DATA_TYPE,
            "thesis": "Large positive Gate spot/perp mark basis may converge after full base-tier costs without relying on funding income.",
            "material_distance_from_closed_branches": [
                "same-venue price-basis convergence, not funding carry",
                "official Gate spot and futures archive, not prior short WS cache",
                "prior public-probe rejection invalidated by a proven Gate size-field parser bug",
            ],
        },
        "universe": {
            "minimum_assets": MINIMUM_ASSETS,
            "primary_target": PRIMARY_ASSETS,
            "reserve_target": RESERVE_ASSETS,
            "selected_assets": selected,
            "primary_assets": selected[:PRIMARY_ASSETS],
            "reserve_assets": selected[PRIMARY_ASSETS:MAX_PLAN_ASSETS],
            "selection_basis": "current_PIT_identity_lifecycle_Binance_exclusion_then_archive_presence_and_train_only_liquidity",
            "manual_additions_allowed": False,
        },
        "strategy": {
            "signal_interval": "1h",
            "basis_bps": "(gate_perp_mark_close - gate_spot_close) / gate_spot_close * 10000",
            "direction": "long_spot_short_perp_only",
            "entry_timing": "after closed signal hour at next spot and perp trade-candle open",
            "entry_threshold_bps": entry_threshold_bps,
            "entry_threshold_formula": "stress_cycle_cost_bps + exit_threshold_bps + 20_bps_safety_margin",
            "exit_threshold_bps": exit_threshold_bps,
            "max_hold_hours": 72,
            "adverse_funding_entry_floor": -0.0003,
            "funding_usage": "cashflow reported separately; price-only net must pass and funding cannot rescue rejection",
            "take_profit": None,
            "stop_loss": None,
            "trailing": None,
            "grid_search": False,
            "retune": False,
            "one_position_per_canonical_asset": True,
            "notional_per_leg_quote": 500.0,
            "leverage": 1.0,
        },
        "economics": {
            "cost_profile": profile.as_dict(),
            "normal_cycle_cost": normal_cost,
            "stress_cycle_cost": stress_cost,
            "maker_fill_probability_historical": 0.0,
            "four_operations": True,
            "funding_pnl_rescue_allowed": False,
        },
        "sample_plan": {
            "history_days": HISTORY_DAYS,
            "warmup_days": WARMUP_DAYS,
            "train_days": TRAIN_DAYS,
            "oos_days": OOS_DAYS,
            "oos_folds": 5,
            "fold_days": 20,
            "window_start_sec": window_start_sec,
            "window_end_sec": window_end_sec,
            "chronological": True,
            "oos_embargo": True,
        },
        "quality_gates": {
            "series_coverage_min": 0.98,
            "spot_perp_aligned_coverage_min": 0.95,
            "funding_settlement_coverage_min": 0.98,
            "gap_breaks_position_minutes": 180,
            "minimum_assets_after_quality": MINIMUM_ASSETS,
            "exact_oldest_day_coverage_required": True,
            "open_bars_allowed": False,
            "duplicate_timestamps_allowed": False,
        },
        "acceptance_gates": {
            "train_minimum_independent_episodes": 20,
            "oos_minimum_independent_episodes": 40,
            "oos_minimum_dates": 20,
            "oos_minimum_assets": MINIMUM_ASSETS,
            "price_only_net_expectancy_positive": True,
            "total_net_expectancy_positive": True,
            "profit_factor_min": 1.2,
            "positive_folds_min": 4,
            "folds_total": 5,
            "stress_net_pnl_nonnegative": True,
            "cluster_bootstrap_95pct_lower_expectancy_positive": True,
            "maximum_single_asset_date_or_episode_positive_pnl_share": 0.25,
            "maximum_drawdown_fraction_of_fully_funded_capital": 0.10,
            "historical_maximum_verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        },
        "runtime": {
            "max_runtime_sec": runtime,
            "collector_absolute_max_runtime_sec": 7_200,
            "new_run_absolute_project_cap_sec": 10_800,
        },
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "grid_search": False,
            "retune": False,
            "oos_read_now": False,
            "pnl_read_now": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
        "input_hashes": {
            **dict(preflight.get("input_hashes") or {}),
            "preflight_artifact_hash": str(preflight.get("artifact_hash") or "fixture_without_artifact_hash"),
        },
        "next_allowed_command": "fast-edge-gate-spot-perp-history-collect",
    }
    plan["plan_hash"] = sha256_json(_sealed_plan(plan))
    return plan


def validate_gate_spot_perp_plan(
    plan: Mapping[str, Any],
    *,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != "PlanOnly" or plan.get("final") is not True:
        raise ValueError("unexpected or incomplete Gate spot/perp plan")
    actual_hash = sha256_json(_sealed_plan(plan))
    if str(plan.get("plan_hash") or "") != actual_hash:
        raise ValueError("Gate spot/perp plan hash mismatch")
    if expected_plan_hash is not None and actual_hash != str(expected_plan_hash):
        raise ValueError("Gate spot/perp expected plan hash mismatch")
    hypothesis = plan.get("hypothesis")
    strategy = plan.get("strategy")
    safety = plan.get("safety")
    if not isinstance(hypothesis, Mapping) or hypothesis.get("id") != HYPOTHESIS_ID:
        raise ValueError("unexpected Gate spot/perp hypothesis")
    if not isinstance(strategy, Mapping) or strategy.get("grid_search") is not False or strategy.get("retune") is not False:
        raise ValueError("Gate spot/perp strategy contract is not frozen")
    if not isinstance(safety, Mapping) or any(
        safety.get(field) is not False
        for field in ("oos_read_now", "pnl_read_now", "live_orders", "private_api_keys", "leverage_or_margin")
    ):
        raise ValueError("Gate spot/perp safety contract mismatch")
    selected = ((plan.get("universe") or {}).get("selected_assets") or [])
    if len(selected) < MINIMUM_ASSETS:
        raise ValueError("Gate spot/perp selected universe is too small")
    return {"plan_hash": actual_hash, "candidate_count": len(selected)}


def _read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def _read_registry(path: str | Path) -> list[dict[str, str]]:
    with Path(path).expanduser().resolve().open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _get_json(url: str, *, timeout_sec: int) -> Any:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def _head_archive(url: str, *, timeout_sec: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(2):
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.head(url, timeout=timeout_sec, allow_redirects=True)
            return {
                "status": int(response.status_code),
                "content_length": int(response.headers.get("Content-Length") or 0),
                "error": None,
            }
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.25)
    return {"status": 0, "content_length": 0, "error": f"{type(last_error).__name__}: {last_error}"}


def run_archive_preflight(
    *,
    pit_state_path: str | Path,
    registry_path: str | Path,
    corrected_probe_path: str | Path,
    max_runtime_sec: int = 1_200,
    max_candidates: int = 60,
    minimum_assets: int = MINIMUM_ASSETS,
    target_assets: int = MAX_PLAN_ASSETS,
    timeout_sec: int = 15,
) -> dict[str, Any]:
    runtime_limit = validate_runtime_sec(max_runtime_sec)
    started = time.monotonic()
    pit_path = Path(pit_state_path).expanduser().resolve()
    coin_path = Path(registry_path).expanduser().resolve()
    probe_path = Path(corrected_probe_path).expanduser().resolve()
    pit_state = _read_json(pit_path)
    registry_rows = _read_registry(coin_path)
    corrected_probe = _read_json(probe_path)
    if corrected_probe.get("decision") != "SPOT_PERP_BASIS_PUBLIC_PROBE_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET":
        raise ValueError("corrected public probe is not accepted")
    spot_pairs = _get_json("https://api.gateio.ws/api/v4/spot/currency_pairs", timeout_sec=timeout_sec)
    spot_tickers = _get_json("https://api.gateio.ws/api/v4/spot/tickers", timeout_sec=timeout_sec)
    candidates, rejected = build_candidate_pool(
        pit_state=pit_state,
        registry_rows=registry_rows,
        gate_spot_pairs=spot_pairs,
        gate_spot_tickers=spot_tickers,
    )
    window_end = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    window_start = window_end - HISTORY_DAYS * DAY_SEC
    oldest_month = datetime.fromtimestamp(window_start, timezone.utc).strftime("%Y%m")
    audited_candidates = candidates[: max(0, int(max_candidates))]
    head_results: dict[str, dict[str, Any]] = {}
    completed_candidates = 0
    timed_out = False
    batch_size = 20
    for offset in range(0, len(audited_candidates), batch_size):
        if time.monotonic() - started >= runtime_limit:
            timed_out = True
            break
        batch = audited_candidates[offset : offset + batch_size]
        urls = [url for candidate in batch for url in required_archive_urls(candidate["base"], oldest_month).values()]
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_head_archive, url, timeout_sec=timeout_sec): url for url in urls}
            for future in as_completed(futures):
                url = futures[future]
                if time.monotonic() - started >= runtime_limit:
                    timed_out = True
                try:
                    head_results[url] = future.result()
                except Exception as exc:  # noqa: BLE001 - preserve a per-URL technical failure.
                    head_results[url] = {"status": 0, "content_length": 0, "error": f"{type(exc).__name__}: {exc}"}
        completed_candidates += len(batch)
        partial = assess_archive_availability(
            audited_candidates[:completed_candidates],
            head_results,
            oldest_month=oldest_month,
            minimum_assets=minimum_assets,
        )
        if int(partial["eligible_asset_count"]) >= target_assets:
            break
        if timed_out:
            break
    assessment = assess_archive_availability(
        audited_candidates[:completed_candidates],
        head_results,
        oldest_month=oldest_month,
        minimum_assets=minimum_assets,
    )
    decision = PREFLIGHT_DECISION_INCOMPLETE if timed_out else assessment["decision"]
    report = {
        "schema": PREFLIGHT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "final": not timed_out,
        "decision": decision,
        "hypothesis_id": HYPOTHESIS_ID,
        "data_type": DATA_TYPE,
        "frozen_window": {"start_sec": window_start, "end_sec": window_end, "history_days": HISTORY_DAYS},
        "candidate_pool_count": len(candidates),
        "candidate_pool_rejected_by_reason": rejected,
        "audited_candidate_count": completed_candidates,
        **{key: value for key, value in assessment.items() if key != "decision"},
        "prior_rejection_invalidation": {
            "invalidated": True,
            "reason": "gate_order_book_size_field_s_was_not_parsed",
            "corrected_probe_path": str(probe_path),
            "corrected_probe_sha256": sha256_file(probe_path),
            "corrected_probe_paired_ok": int((corrected_probe.get("summary") or {}).get("paired_ok_bases") or 0),
        },
        "input_hashes": {
            "pit_state_sha256": sha256_file(pit_path),
            "registry_sha256": sha256_file(coin_path),
            "corrected_probe_sha256": sha256_file(probe_path),
        },
        "source_provenance": {
            "gate_spot_pairs": "https://api.gateio.ws/api/v4/spot/currency_pairs",
            "gate_spot_tickers": "https://api.gateio.ws/api/v4/spot/tickers",
            "gate_archive": "https://download.gatedata.org",
            "archive_boundary_proof": "HEAD monthly file presence only; exact timestamps deferred to collector quality",
        },
        "runtime_sec": round(time.monotonic() - started, 6),
        "max_runtime_sec": runtime_limit,
        "network_requests": 2 + len(head_results),
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "returns_read": False,
            "pnl_read": False,
            "grid_search": False,
            "live_orders": False,
            "private_api_keys": False,
        },
        "next_allowed_command": (
            "fast-edge-gate-spot-perp-plan"
            if decision == PREFLIGHT_DECISION_READY
            else "none_preflight_incomplete_or_insufficient"
        ),
    }
    report["artifact_hash"] = sha256_json(
        {key: value for key, value in report.items() if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}}
    )
    return report


def write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate same-venue spot/perp historical basis PlanOnly pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--pit-state", required=True)
    preflight_parser.add_argument("--registry", required=True)
    preflight_parser.add_argument("--corrected-probe", required=True)
    preflight_parser.add_argument("--out", required=True)
    preflight_parser.add_argument("--max-runtime-sec", type=int, default=1_200)
    preflight_parser.add_argument("--max-candidates", type=int, default=60)
    preflight_parser.add_argument("--minimum-assets", type=int, default=MINIMUM_ASSETS)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--preflight", required=True)
    plan_parser.add_argument("--out", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=600)
    validate_parser = subparsers.add_parser("validate-plan")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash", required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        result = run_archive_preflight(
            pit_state_path=args.pit_state,
            registry_path=args.registry,
            corrected_probe_path=args.corrected_probe,
            max_runtime_sec=args.max_runtime_sec,
            max_candidates=args.max_candidates,
            minimum_assets=args.minimum_assets,
        )
    elif args.command == "plan":
        result = build_gate_spot_perp_plan(
            _read_json(args.preflight),
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = validate_gate_spot_perp_plan(
            _read_json(args.plan),
            expected_plan_hash=args.expected_plan_hash,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    write_json_immutable(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
