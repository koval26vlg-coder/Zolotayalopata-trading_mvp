from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from costs import validate_runtime_sec
from funding import GateFundingClient, MexcFundingClient, _as_float
from historical_basis_code_snapshot import require_plan_code_snapshot, validate_basis_code_snapshot_reference
from historical_basis_edge import sha256_file, sha256_json, validate_historical_basis_plan
from owned_run_gate import publish_owned_run_gate


PLAN_SCHEMA = "trading_mvp_historical_basis_probe_plan_v1"
MANIFEST_SCHEMA = "trading_mvp_historical_basis_probe_manifest_v1"
REPORT_SCHEMA = "trading_mvp_historical_basis_sprint_report_v1"
EVALUATION_SCHEMA = "trading_mvp_historical_basis_owned_evaluation_v1"


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _semantic_hash(payload: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {
                "deterministic_result_hash",
                "generated_at_utc",
                "runtime_sec",
            }
        }
    )


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, target)


def _write_owned_gate(path: Path, payload: dict[str, Any]) -> None:
    publish_owned_run_gate(path, payload, run_type="historical_basis_execution_probe")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("probe window timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _validate_semantic_artifact(payload: dict[str, Any], *, schema: str, name: str) -> None:
    if payload.get("schema") != schema:
        raise ValueError(f"unexpected {name} schema")
    if payload.get("deterministic_result_hash") != _semantic_hash(payload):
        raise ValueError(f"{name} deterministic hash mismatch")


def depth_execution_metrics(
    levels: Iterable[Sequence[float]],
    *,
    side: str,
    notional_quote: float,
    max_impact_bps: float,
) -> dict[str, Any]:
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    parsed = []
    for level in levels:
        try:
            price, quantity = float(level[0]), abs(float(level[1]))
        except (IndexError, TypeError, ValueError):
            continue
        if price > 0 and quantity > 0:
            parsed.append((price, quantity))
    parsed.sort(key=lambda item: item[0], reverse=side == "sell")
    if not parsed or notional_quote <= 0:
        return {
            "filled": False,
            "best_price": None,
            "average_price": None,
            "impact_bps": math.inf,
            "filled_quote": 0.0,
            "capacity_quote_at_max_impact": 0.0,
        }
    best = parsed[0][0]
    limit_price = best * (1.0 + max_impact_bps / 10_000.0) if side == "buy" else best * (
        1.0 - max_impact_bps / 10_000.0
    )
    capacity = sum(
        price * quantity
        for price, quantity in parsed
        if (price <= limit_price if side == "buy" else price >= limit_price)
    )
    remaining = float(notional_quote)
    acquired_quantity = 0.0
    spent_quote = 0.0
    for price, available_quantity in parsed:
        available_quote = price * available_quantity
        take_quote = min(remaining, available_quote)
        acquired_quantity += take_quote / price
        spent_quote += take_quote
        remaining -= take_quote
        if remaining <= 1e-9:
            break
    filled = remaining <= 1e-9 and acquired_quantity > 0
    average = spent_quote / acquired_quantity if acquired_quantity else None
    if average is None:
        impact = math.inf
    elif side == "buy":
        impact = (average - best) / best * 10_000.0
    else:
        impact = (best - average) / best * 10_000.0
    return {
        "filled": filled,
        "best_price": best,
        "average_price": average,
        "impact_bps": impact,
        "filled_quote": spent_quote,
        "capacity_quote_at_max_impact": capacity,
    }


def build_basis_probe_plan(
    evaluation_path: str | Path,
    output_path: str | Path,
    *,
    first_window_start_utc: str | None = None,
    duration_sec: int = 1200,
    interval_sec: int = 5,
) -> dict[str, Any]:
    evaluation_target = Path(evaluation_path).expanduser().resolve()
    evaluation = _read_json(evaluation_target)
    _validate_semantic_artifact(evaluation, schema=EVALUATION_SCHEMA, name="evaluation")
    if evaluation.get("stage") != "full_evaluation" or evaluation.get("verdict") != "ACCEPT_FOR_EXECUTION_PROBE":
        raise ValueError("probe plan requires full historical ACCEPT_FOR_EXECUTION_PROBE")
    plan_path = Path(str(evaluation.get("plan_path") or "")).expanduser().resolve()
    if not plan_path.exists() or sha256_file(plan_path) != evaluation.get("plan_file_sha256"):
        raise ValueError("evaluation plan provenance mismatch")
    validate_historical_basis_plan(plan_path, str(evaluation.get("plan_hash") or ""))
    historical_plan = _read_json(plan_path)
    if historical_plan.get("plan_hash") != evaluation.get("plan_hash"):
        raise ValueError("evaluation and historical plan hash mismatch")
    snapshot = validate_basis_code_snapshot_reference(None, None, fallback_code_path=__file__)
    require_plan_code_snapshot(historical_plan, snapshot)
    require_plan_code_snapshot(historical_plan, evaluation.get("code_provenance") or {})
    quality_path = Path(str(evaluation.get("quality_report_path") or "")).expanduser().resolve()
    quality = _read_json(quality_path)
    trade_counts: dict[str, int] = {}
    for trade in evaluation.get("normal_trades") or []:
        base = str(trade.get("base") or "").upper()
        if base:
            trade_counts[base] = trade_counts.get(base, 0) + 1
    preferred = sorted(trade_counts, key=lambda base: (-trade_counts[base], base))
    preferred.extend(base for base in quality.get("primary_assets") or [] if base not in preferred)
    candidates_by_base = {
        str(row["base"]).upper(): row
        for row in (historical_plan.get("universe") or {}).get("candidates") or []
    }
    candidates = [candidates_by_base[base] for base in preferred if base in candidates_by_base][:10]
    if not candidates:
        raise ValueError("probe plan has no historically accepted candidates")
    if duration_sec != 1200 or interval_sec != 5:
        raise ValueError("probe duration/interval are frozen at 1200/5 seconds")
    first = _parse_utc(first_window_start_utc) if first_window_start_utc else (
        datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    )
    windows = [
        {
            "index": index,
            "start_utc": (first + timedelta(hours=4 * index)).isoformat(),
            "end_utc": (first + timedelta(hours=4 * index, seconds=duration_sec)).isoformat(),
        }
        for index in range(3)
    ]
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_evaluation": {
            "path": str(evaluation_target),
            "file_sha256": sha256_file(evaluation_target),
            "semantic_hash": evaluation["deterministic_result_hash"],
        },
        "historical_plan_hash": evaluation["plan_hash"],
        "code_provenance": historical_plan.get("code_provenance") or snapshot,
        "candidates": candidates,
        "windows": windows,
        "duration_sec": duration_sec,
        "interval_sec": interval_sec,
        "notional_quote_per_leg": float((historical_plan.get("economics") or {})["notional_quote_per_leg"]),
        "entry_threshold_bps": float((historical_plan.get("strategy") or {})["entry_threshold_bps"]),
        "minimum_valid_cycles_per_window": 180,
        "minimum_coverage": 0.80,
        "maximum_timestamp_skew_ms": 2000.0,
        "minimum_capacity_quote_per_leg": 500.0,
        "maximum_p95_impact_bps": 10.0,
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "live_orders": False,
            "api_keys": False,
            "grid_search": False,
        },
        "next_allowed_command": "fast-edge-basis-probe -WindowIndex 0",
    }
    plan["probe_plan_hash"] = _semantic_hash(plan)
    _write_json_immutable(output_path, plan)
    return plan


def validate_basis_probe_plan(path: str | Path, expected_hash: str | None = None) -> dict[str, Any]:
    plan = _read_json(path)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError("unexpected probe plan")
    observed = _semantic_hash({key: value for key, value in plan.items() if key != "probe_plan_hash"})
    if plan.get("probe_plan_hash") != observed:
        raise ValueError("probe plan hash mismatch")
    if expected_hash and expected_hash != observed:
        raise ValueError("probe plan does not match expected hash")
    if len(plan.get("windows") or []) != 3 or int(plan.get("duration_sec") or 0) != 1200:
        raise ValueError("probe plan frozen windows mismatch")
    code = plan.get("code_provenance") or {}
    if code.get("immutable_snapshot"):
        validate_basis_code_snapshot_reference(
            code.get("code_snapshot_hash"),
            code.get("code_snapshot_manifest"),
            fallback_code_path=__file__,
        )
    return plan


def _normalize_book_levels(raw: Any) -> list[list[float]]:
    result: list[list[float]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            price = _as_float(item.get("p") or item.get("price"))
            quantity = _as_float(item.get("s") or item.get("size") or item.get("v") or item.get("vol"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            price, quantity = _as_float(item[0]), _as_float(item[1])
        else:
            continue
        if price and quantity:
            result.append([price, abs(quantity)])
    return result


class MexcBasisProbeClient(MexcFundingClient):
    def fetch_ticker_map_fresh(self) -> dict[str, dict[str, Any]]:
        payload = self._get("/api/v1/contract/ticker")
        data = payload.get("data") if isinstance(payload, dict) else payload
        return {str(row.get("symbol")): row for row in data if isinstance(row, dict) and row.get("symbol")}

    def fetch_depth(self, symbol: str) -> dict[str, list[list[float]]]:
        payload = self._get(f"/api/v1/contract/depth/{symbol}", {"limit": 20})
        data = payload.get("data") if isinstance(payload, dict) else payload
        data = data if isinstance(data, dict) else {}
        return {"bids": _normalize_book_levels(data.get("bids")), "asks": _normalize_book_levels(data.get("asks"))}


class GateBasisProbeClient(GateFundingClient):
    def fetch_ticker_map_fresh(self) -> dict[str, dict[str, Any]]:
        payload = self._get("/futures/usdt/tickers")
        return {str(row.get("contract")): row for row in payload if isinstance(row, dict) and row.get("contract")}

    def fetch_depth(self, symbol: str) -> dict[str, list[list[float]]]:
        payload = self._get("/futures/usdt/order_book", {"contract": symbol, "limit": 20})
        data = payload if isinstance(payload, dict) else {}
        return {"bids": _normalize_book_levels(data.get("bids")), "asks": _normalize_book_levels(data.get("asks"))}


def _basis(mark: float | None, index: float | None) -> float | None:
    if mark is None or index is None or mark <= 0 or index <= 0:
        return None
    return (mark - index) / index * 10_000.0


def _ticker_prices(venue: str, ticker: dict[str, Any]) -> tuple[float | None, float | None]:
    if venue == "mexc":
        return _as_float(ticker.get("fairPrice")), _as_float(ticker.get("indexPrice"))
    return _as_float(ticker.get("mark_price")), _as_float(ticker.get("index_price"))


def collect_basis_probe_window(
    probe_plan_path: str | Path,
    *,
    expected_probe_plan_hash: str,
    window_index: int,
    samples_path: str | Path,
    manifest_path: str | Path,
    max_runtime_sec: int = 1200,
    clients: dict[str, Any] | None = None,
    active_gate_path: str | Path | None = None,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
) -> dict[str, Any]:
    validate_runtime_sec(max_runtime_sec)
    snapshot = validate_basis_code_snapshot_reference(
        code_snapshot_hash,
        code_snapshot_manifest,
        fallback_code_path=__file__,
    )
    plan = validate_basis_probe_plan(probe_plan_path, expected_probe_plan_hash)
    require_plan_code_snapshot(plan, snapshot)
    if not 0 <= int(window_index) < 3:
        raise ValueError("window_index must be 0, 1 or 2")
    duration = int(plan["duration_sec"])
    if max_runtime_sec < duration or max_runtime_sec > 1800:
        raise ValueError("probe MaxRuntimeSec must cover 1200 seconds and remain <=1800")
    samples_target = Path(samples_path).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    if samples_target.exists() or manifest_target.exists():
        raise FileExistsError("probe artifacts already exist")
    samples_target.parent.mkdir(parents=True, exist_ok=True)
    owner_prefix = Path(os.path.commonpath([samples_target.parent, manifest_target.parent])).resolve()
    gate_path = Path(active_gate_path).expanduser().resolve() if active_gate_path else None
    run_id = f"basis_probe_{plan['probe_plan_hash'][:12]}_w{window_index}"
    if gate_path is not None:
        _write_owned_gate(
            gate_path,
            {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": run_id,
                "status": "RUNNING",
                "gate_status": "RUNNING",
                "collector_pid": os.getpid(),
                "process_ids": [os.getpid()],
                "output": {"path": str(samples_target), "kind": "file"},
                "manifest_path": str(manifest_target),
                "locks": ["market_data_writer"],
                "owner_output_prefix": str(owner_prefix),
                "code_snapshot_hash": snapshot["code_snapshot_hash"],
                "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
                "parallel_safe_actions": ["code_work", "unit_tests", "fixtures", "static_analysis", "immutable_cache_compute"],
                "forbidden_overlapping_actions": ["collector", "probe", "consumer_of_owner_output", "postprocess", "grid_search"],
                "replay_allowed": False,
                "live_orders_allowed": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    clients = clients or {"mexc": MexcBasisProbeClient(), "gateio": GateBasisProbeClient()}
    started = time.monotonic()
    deadline = started + duration
    interval = int(plan["interval_sec"])
    expected_cycles = duration // interval
    cycle = 0
    valid_cycles = 0
    errors: list[str] = []
    impacts: list[float] = []
    capacities: list[float] = []
    skews: list[float] = []
    qualifying = 0
    with samples_target.open("x", encoding="utf-8", buffering=1) as handle:
        while cycle < expected_cycles and time.monotonic() < deadline:
            cycle_started = time.monotonic()
            cycle += 1
            try:
                mexc_at = time.time()
                mexc_tickers = clients["mexc"].fetch_ticker_map_fresh()
                gate_at = time.time()
                gate_tickers = clients["gateio"].fetch_ticker_map_fresh()
                skew_ms = abs(gate_at - mexc_at) * 1000.0
                cycle_valid = False
                for candidate in plan["candidates"]:
                    mexc_symbol = candidate["mexc_symbol"]
                    gate_symbol = candidate["gateio_symbol"]
                    mexc_mark, mexc_index = _ticker_prices("mexc", mexc_tickers.get(mexc_symbol, {}))
                    gate_mark, gate_index = _ticker_prices("gateio", gate_tickers.get(gate_symbol, {}))
                    mexc_basis = _basis(mexc_mark, mexc_index)
                    gate_basis = _basis(gate_mark, gate_index)
                    if mexc_basis is None or gate_basis is None:
                        continue
                    mexc_book = clients["mexc"].fetch_depth(mexc_symbol)
                    gate_book = clients["gateio"].fetch_depth(gate_symbol)
                    if mexc_basis < gate_basis:
                        long_venue, short_venue = "mexc", "gateio"
                    else:
                        long_venue, short_venue = "gateio", "mexc"
                    long_book = mexc_book if long_venue == "mexc" else gate_book
                    short_book = gate_book if short_venue == "gateio" else mexc_book
                    long_metrics = depth_execution_metrics(
                        long_book["asks"], side="buy", notional_quote=plan["notional_quote_per_leg"], max_impact_bps=10.0
                    )
                    short_metrics = depth_execution_metrics(
                        short_book["bids"], side="sell", notional_quote=plan["notional_quote_per_leg"], max_impact_bps=10.0
                    )
                    row_valid = bool(long_metrics["filled"] and short_metrics["filled"])
                    spread = abs(mexc_basis - gate_basis)
                    is_qualifying = row_valid and spread >= float(plan["entry_threshold_bps"])
                    row = {
                        "schema": "trading_mvp_historical_basis_probe_sample_v1",
                        "window_index": int(window_index),
                        "cycle": cycle,
                        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "base": candidate["base"],
                        "long_venue": long_venue,
                        "short_venue": short_venue,
                        "mexc_basis_bps": mexc_basis,
                        "gateio_basis_bps": gate_basis,
                        "basis_spread_bps": spread,
                        "timestamp_skew_ms": skew_ms,
                        "long_execution": long_metrics,
                        "short_execution": short_metrics,
                        "valid": row_valid,
                        "qualifying": is_qualifying,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    if row_valid:
                        cycle_valid = True
                        impacts.append(max(long_metrics["impact_bps"], short_metrics["impact_bps"]))
                        capacities.append(min(long_metrics["capacity_quote_at_max_impact"], short_metrics["capacity_quote_at_max_impact"]))
                        skews.append(skew_ms)
                    if is_qualifying:
                        qualifying += 1
                if cycle_valid:
                    valid_cycles += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"cycle={cycle}:{type(exc).__name__}:{exc}")
            elapsed = time.monotonic() - cycle_started
            remaining = max(0.0, deadline - time.monotonic())
            print(
                f"PROBE window={window_index} cycle={cycle}/{expected_cycles} valid={valid_cycles} "
                f"errors={len(errors)} remaining_sec={remaining:.1f}",
                flush=True,
            )
            sleep_for = interval - elapsed
            if sleep_for > 0 and cycle < expected_cycles:
                time.sleep(min(sleep_for, max(0.0, deadline - time.monotonic())))
    coverage = valid_cycles / expected_cycles if expected_cycles else 0.0
    ordered_impacts = sorted(impacts)
    ordered_skews = sorted(skews)
    p95_index = lambda values: min(len(values) - 1, max(0, math.ceil(len(values) * 0.95) - 1))
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "final": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "probe_plan_path": str(Path(probe_plan_path).expanduser().resolve()),
        "probe_plan_file_sha256": sha256_file(probe_plan_path),
        "probe_plan_hash": plan["probe_plan_hash"],
        "window_index": int(window_index),
        "expected_cycles": expected_cycles,
        "completed_cycles": cycle,
        "valid_cycles": valid_cycles,
        "coverage": coverage,
        "p95_timestamp_skew_ms": ordered_skews[p95_index(ordered_skews)] if ordered_skews else math.inf,
        "minimum_capacity_quote": min(capacities, default=0.0),
        "p95_impact_bps": ordered_impacts[p95_index(ordered_impacts)] if ordered_impacts else math.inf,
        "error_count": len(errors),
        "errors": errors,
        "qualifying_event_count": qualifying,
        "samples_path": str(samples_target),
        "samples_sha256": sha256_file(samples_target),
        "runtime_sec": round(time.monotonic() - started, 3),
        "code_snapshot_hash": snapshot["code_snapshot_hash"],
        "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
        "immutable_code_snapshot": snapshot["immutable_snapshot"],
    }
    manifest["deterministic_result_hash"] = _semantic_hash(manifest)
    _write_json_immutable(manifest_target, manifest)
    if gate_path is not None:
        _write_owned_gate(
            gate_path,
            {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": run_id,
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "final": True,
                "collector_pid": None,
                "process_ids": [],
                "output": {"path": str(samples_target), "kind": "file"},
                "manifest_path": str(manifest_target),
                "locks": ["market_data_writer"],
                "owner_output_prefix": str(owner_prefix),
                "code_snapshot_hash": snapshot["code_snapshot_hash"],
                "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
                "parallel_safe_actions": ["code_work", "unit_tests", "fixtures", "static_analysis", "immutable_cache_compute"],
                "forbidden_overlapping_actions": ["collector", "probe", "consumer_of_owner_output", "postprocess", "grid_search"],
                "replay_allowed": False,
                "live_orders_allowed": False,
                "next_goal_decision": "BASIS_EXECUTION_PROBE_WINDOW_READY",
                "next_step_after_ready": "fast-edge-basis-report after all three windows",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return manifest


def build_basis_sprint_report(
    *,
    evaluation_path: str | Path,
    probe_plan_path: str | Path | None,
    manifest_paths: Iterable[str | Path],
    output_path: str | Path,
) -> dict[str, Any]:
    evaluation_target = Path(evaluation_path).expanduser().resolve()
    evaluation = _read_json(evaluation_target)
    _validate_semantic_artifact(evaluation, schema=EVALUATION_SCHEMA, name="evaluation")
    historical_plan_path = Path(str(evaluation.get("plan_path") or "")).expanduser().resolve()
    if not historical_plan_path.exists() or sha256_file(historical_plan_path) != evaluation.get("plan_file_sha256"):
        raise ValueError("evaluation plan provenance mismatch")
    validate_historical_basis_plan(historical_plan_path, str(evaluation.get("plan_hash") or ""))
    historical_plan = _read_json(historical_plan_path)
    snapshot = validate_basis_code_snapshot_reference(None, None, fallback_code_path=__file__)
    require_plan_code_snapshot(historical_plan, snapshot)
    require_plan_code_snapshot(historical_plan, evaluation.get("code_provenance") or {})
    historical_verdict = evaluation.get("verdict")
    if historical_verdict != "ACCEPT_FOR_EXECUTION_PROBE":
        verdict = historical_verdict if historical_verdict in {"REJECT", "INSUFFICIENT_DATA"} else "REJECT"
        reasons = list(evaluation.get("rejection_reasons") or ["historical_not_accepted"])
        manifests: list[dict[str, Any]] = []
        probe_plan = None
    else:
        paths = [Path(path).expanduser().resolve() for path in manifest_paths]
        if not paths:
            verdict = "ACCEPT_FOR_EXECUTION_PROBE"
            reasons = []
            manifests = []
            probe_plan = None
        else:
            if probe_plan_path is None:
                raise ValueError("probe manifests require probe_plan_path")
            probe_plan_target = Path(probe_plan_path).expanduser().resolve()
            probe_plan = validate_basis_probe_plan(probe_plan_target)
            if probe_plan["historical_evaluation"]["file_sha256"] != sha256_file(evaluation_target):
                raise ValueError("probe plan historical evaluation provenance mismatch")
            manifests = []
            for path in paths:
                manifest = _read_json(path)
                _validate_semantic_artifact(manifest, schema=MANIFEST_SCHEMA, name="probe manifest")
                if not manifest.get("final") or manifest.get("probe_plan_hash") != probe_plan["probe_plan_hash"]:
                    raise ValueError("probe manifest is incomplete or belongs to another plan")
                samples = Path(str(manifest.get("samples_path") or "")).expanduser().resolve()
                if not samples.exists() or sha256_file(samples) != manifest.get("samples_sha256"):
                    raise ValueError("probe sample provenance mismatch")
                manifests.append(manifest)
            indices = sorted(int(row["window_index"]) for row in manifests)
            if indices != [0, 1, 2]:
                raise ValueError("exactly three distinct probe windows are required")
            reasons = []
            for row in manifests:
                prefix = f"window_{row['window_index']}"
                if int(row.get("valid_cycles") or 0) < int(probe_plan["minimum_valid_cycles_per_window"]):
                    reasons.append(f"{prefix}:valid_cycles")
                if float(row.get("coverage") or 0.0) < float(probe_plan["minimum_coverage"]):
                    reasons.append(f"{prefix}:coverage")
                if float(row.get("p95_timestamp_skew_ms") or math.inf) > float(probe_plan["maximum_timestamp_skew_ms"]):
                    reasons.append(f"{prefix}:timestamp_skew")
                if float(row.get("minimum_capacity_quote") or 0.0) < float(probe_plan["minimum_capacity_quote_per_leg"]):
                    reasons.append(f"{prefix}:capacity")
                if float(row.get("p95_impact_bps") or math.inf) > float(probe_plan["maximum_p95_impact_bps"]):
                    reasons.append(f"{prefix}:impact")
                if int(row.get("error_count") or 0) > 0:
                    reasons.append(f"{prefix}:errors")
            if reasons:
                verdict = "REJECT"
            elif sum(int(row.get("qualifying_event_count") or 0) for row in manifests) > 0:
                verdict = "PAPER_FORWARD_READY"
            else:
                verdict = "HISTORICAL_ACCEPT_AWAIT_EVENT"
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_evaluation": {
            "path": str(evaluation_target),
            "file_sha256": sha256_file(evaluation_target),
            "semantic_hash": evaluation["deterministic_result_hash"],
            "verdict": historical_verdict,
        },
        "probe_plan_hash": probe_plan.get("probe_plan_hash") if probe_plan else None,
        "code_provenance": historical_plan.get("code_provenance") or snapshot,
        "probe_windows": [
            {
                "window_index": row["window_index"],
                "manifest_hash": row["deterministic_result_hash"],
                "valid_cycles": row["valid_cycles"],
                "coverage": row["coverage"],
                "qualifying_event_count": row["qualifying_event_count"],
            }
            for row in sorted(manifests, key=lambda item: item["window_index"])
        ],
        "verdict": verdict,
        "rejection_reasons": reasons,
        "live_review_eligible": False,
        "safety": {"live_orders": False, "api_keys": False, "leverage": False},
        "next_allowed_command": {
            "ACCEPT_FOR_EXECUTION_PROBE": "fast-edge-basis-probe-plan",
            "HISTORICAL_ACCEPT_AWAIT_EVENT": "wait-for-new-frozen-probe-window",
            "PAPER_FORWARD_READY": "paper-forward-observation-plan",
        }.get(verdict, "close-hypothesis-without-retune"),
    }
    report["deterministic_result_hash"] = _semantic_hash(report)
    _write_json_immutable(output_path, report)
    return report


def main() -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="Historical basis execution-probe and sprint report")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--evaluation", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--first-window-start-utc")
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--plan", required=True)
    collect_parser.add_argument("--expected-plan-hash", required=True)
    collect_parser.add_argument("--window-index", type=int, required=True)
    collect_parser.add_argument("--samples", required=True)
    collect_parser.add_argument("--manifest", required=True)
    collect_parser.add_argument("--max-runtime-sec", type=int, default=1200)
    collect_parser.add_argument("--active-run-gate")
    collect_parser.add_argument("--code-snapshot-hash")
    collect_parser.add_argument("--code-snapshot-manifest")
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--evaluation", required=True)
    report_parser.add_argument("--probe-plan")
    report_parser.add_argument("--manifests", default="")
    report_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        result = build_basis_probe_plan(
            args.evaluation,
            args.output,
            first_window_start_utc=args.first_window_start_utc,
        )
    elif args.command == "collect":
        result = collect_basis_probe_window(
            args.plan,
            expected_probe_plan_hash=args.expected_plan_hash,
            window_index=args.window_index,
            samples_path=args.samples,
            manifest_path=args.manifest,
            max_runtime_sec=args.max_runtime_sec,
            active_gate_path=args.active_run_gate,
            code_snapshot_hash=args.code_snapshot_hash,
            code_snapshot_manifest=args.code_snapshot_manifest,
        )
    else:
        manifests = [value for value in args.manifests.split(",") if value.strip()]
        result = build_basis_sprint_report(
            evaluation_path=args.evaluation,
            probe_plan_path=args.probe_plan,
            manifest_paths=manifests,
            output_path=args.output,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
