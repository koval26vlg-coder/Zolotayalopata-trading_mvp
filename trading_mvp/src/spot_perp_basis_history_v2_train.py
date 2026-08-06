from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from spot_perp_basis_history_v2 import (
    MINIMUM_ASSETS,
    sha256_file,
    sha256_json,
    validate_gate_spot_perp_plan,
)
from spot_perp_basis_history_v2_quality import QUALITY_SCHEMA


TRAIN_PLAN_SCHEMA = "trading_mvp_gate_spot_perp_train_plan_v1"
TRAIN_RESULT_SCHEMA = "trading_mvp_gate_spot_perp_train_result_v1"
HOUR_SEC = 3_600
DAY_SEC = 86_400


def _as_float(value: Any, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _atomic_write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    count = 0
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    os.replace(temporary, path)
    return count


def _read_jsonl_hash_bound(path: str | Path, expected_sha256: str) -> list[dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if sha256_file(target) != str(expected_sha256).lower():
        raise ValueError(f"input hash mismatch: {target}")
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row is not an object: {target}:{line_number}")
            rows.append(row)
    return rows


def _basis_bps(row: Mapping[str, Any]) -> float:
    spot_close = _as_float((row.get("spot") or {}).get("close"), field="spot.close")
    mark_close = _as_float((row.get("mark") or {}).get("close"), field="mark.close")
    if spot_close <= 0 or mark_close <= 0:
        raise ValueError("basis prices must be positive")
    return (mark_close - spot_close) / spot_close * 10_000.0


def _entry_or_exit_open(row: Mapping[str, Any]) -> tuple[float, float]:
    spot_open = _as_float((row.get("spot") or {}).get("open"), field="spot.open")
    perp_open = _as_float((row.get("perp") or {}).get("open"), field="perp.open")
    if spot_open <= 0 or perp_open <= 0:
        raise ValueError("trade opens must be positive")
    return spot_open, perp_open


def simulate_asset_train(
    *,
    base: str,
    canonical_asset_id: str,
    rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    signal_start_sec: int,
    train_end_sec: int,
    entry_threshold_bps: float,
    exit_threshold_bps: float,
    max_hold_hours: int,
    adverse_funding_entry_floor: float,
    normal_cycle_cost_bps: float,
    stress_cycle_cost_bps: float,
    notional_per_leg_quote: float,
    gap_break_sec: int = 10_800,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if max_hold_hours < 1 or notional_per_leg_quote <= 0:
        raise ValueError("invalid strategy sizing or holding period")
    ordered = sorted((dict(row) for row in rows), key=lambda item: int(item["ts"]))
    timestamps = [int(row["ts"]) for row in ordered]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError(f"duplicate train timestamp for {base}")
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError(f"non-monotonic train timestamps for {base}")
    funding = sorted(
        (
            int(row["ts"]),
            _as_float(row.get("funding_rate"), field="funding_rate"),
        )
        for row in funding_rows
        if int(row["ts"]) < train_end_sec
    )
    funding_ts = [item[0] for item in funding]
    diagnostics = {
        "signals": 0,
        "blocked_adverse_funding": 0,
        "blocked_noncontiguous_entry": 0,
        "aborted_data_gap": 0,
        "censored_train_end": 0,
    }
    episodes: list[dict[str, Any]] = []
    index = 0
    while index + 1 < len(ordered):
        signal_row = ordered[index]
        signal_ts = int(signal_row["ts"])
        if signal_ts < signal_start_sec:
            index += 1
            continue
        if signal_ts >= train_end_sec:
            break
        entry_row = ordered[index + 1]
        entry_ts = int(entry_row["ts"])
        if entry_ts != signal_ts + HOUR_SEC:
            diagnostics["blocked_noncontiguous_entry"] += 1
            index += 1
            continue
        signal_basis = _basis_bps(signal_row)
        if signal_basis < entry_threshold_bps:
            index += 1
            continue
        diagnostics["signals"] += 1
        latest_index = bisect.bisect_left(funding_ts, entry_ts) - 1
        latest_rate = funding[latest_index][1] if latest_index >= 0 else 0.0
        if latest_rate < adverse_funding_entry_floor:
            diagnostics["blocked_adverse_funding"] += 1
            index += 1
            continue

        entry_spot, entry_perp = _entry_or_exit_open(entry_row)
        maximum_exit_ts = entry_ts + max_hold_hours * HOUR_SEC
        exit_index: int | None = None
        exit_reason: str | None = None
        exit_basis: float | None = None
        gap_abort_index: int | None = None
        cursor = index + 1
        while cursor < len(ordered):
            current_ts = int(ordered[cursor]["ts"])
            if current_ts >= train_end_sec:
                break
            if cursor > index + 1 and current_ts - int(ordered[cursor - 1]["ts"]) > gap_break_sec:
                gap_abort_index = cursor
                break
            if current_ts >= maximum_exit_ts:
                exit_index = cursor
                exit_reason = "max_hold"
                exit_basis = _basis_bps(ordered[cursor - 1]) if cursor > 0 else signal_basis
                break
            close_basis = _basis_bps(ordered[cursor])
            if close_basis <= exit_threshold_bps and cursor + 1 < len(ordered):
                next_ts = int(ordered[cursor + 1]["ts"])
                if next_ts == current_ts + HOUR_SEC and next_ts < train_end_sec:
                    exit_index = cursor + 1
                    exit_reason = "basis_converged"
                    exit_basis = close_basis
                    break
            cursor += 1

        if gap_abort_index is not None:
            diagnostics["aborted_data_gap"] += 1
            index = gap_abort_index
            continue
        if exit_index is None or exit_reason is None or exit_basis is None:
            diagnostics["censored_train_end"] += 1
            break

        exit_row = ordered[exit_index]
        exit_ts = int(exit_row["ts"])
        exit_spot, exit_perp = _entry_or_exit_open(exit_row)
        spot_return = exit_spot / entry_spot - 1.0
        short_perp_return = 1.0 - exit_perp / entry_perp
        price_gross_bps = (spot_return + short_perp_return) * 10_000.0
        price_normal_net_bps = price_gross_bps - normal_cycle_cost_bps
        price_stress_net_bps = price_gross_bps - stress_cycle_cost_bps
        funding_rates = [rate for ts, rate in funding if entry_ts < ts < exit_ts]
        funding_bps = sum(funding_rates) * 10_000.0
        stress_funding_bps = sum(rate * (0.5 if rate > 0 else 1.0) for rate in funding_rates) * 10_000.0
        episodes.append(
            {
                "canonical_asset_id": canonical_asset_id,
                "base": base,
                "signal_ts": signal_ts,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "hold_hours": (exit_ts - entry_ts) / HOUR_SEC,
                "exit_reason": exit_reason,
                "signal_basis_bps": signal_basis,
                "exit_basis_bps": exit_basis,
                "entry_spot": entry_spot,
                "entry_perp": entry_perp,
                "exit_spot": exit_spot,
                "exit_perp": exit_perp,
                "price_gross_bps": price_gross_bps,
                "price_normal_net_bps": price_normal_net_bps,
                "price_stress_net_bps": price_stress_net_bps,
                "price_normal_net_quote": notional_per_leg_quote * price_normal_net_bps / 10_000.0,
                "price_stress_net_quote": notional_per_leg_quote * price_stress_net_bps / 10_000.0,
                "funding_event_count": len(funding_rates),
                "funding_bps": funding_bps,
                "stress_funding_bps": stress_funding_bps,
                "funding_quote": notional_per_leg_quote * funding_bps / 10_000.0,
                "stress_funding_quote": notional_per_leg_quote * stress_funding_bps / 10_000.0,
            }
        )
        index = exit_index
    return episodes, diagnostics


def compute_episode_metrics(episodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted((dict(row) for row in episodes), key=lambda item: (int(item["exit_ts"]), str(item["base"])))
    price_normal = [_as_float(row["price_normal_net_quote"], field="price_normal_net_quote") for row in ordered]
    price_stress = [_as_float(row["price_stress_net_quote"], field="price_stress_net_quote") for row in ordered]
    funding = [_as_float(row.get("funding_quote", 0.0), field="funding_quote") for row in ordered]
    stress_funding = [_as_float(row.get("stress_funding_quote", row.get("funding_quote", 0.0)), field="stress_funding_quote") for row in ordered]
    gains = sum(value for value in price_normal if value > 0)
    losses = -sum(value for value in price_normal if value < 0)
    profit_factor = gains / losses if losses > 0 else None
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in price_normal:
        running += value
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
    positive_total = gains
    positive_by_base: dict[str, float] = defaultdict(float)
    positive_by_date: dict[str, float] = defaultdict(float)
    maximum_episode_share = 0.0
    for row, value in zip(ordered, price_normal):
        if value <= 0:
            continue
        positive_by_base[str(row["base"])] += value
        date = datetime.fromtimestamp(int(row["entry_ts"]), timezone.utc).date().isoformat()
        positive_by_date[date] += value
        if positive_total > 0:
            maximum_episode_share = max(maximum_episode_share, value / positive_total)
    maximum_asset_share = max((value / positive_total for value in positive_by_base.values()), default=0.0) if positive_total > 0 else 1.0
    maximum_date_share = max((value / positive_total for value in positive_by_date.values()), default=0.0) if positive_total > 0 else 1.0
    total_price = sum(price_normal)
    total_stress_price = sum(price_stress)
    total_funding = sum(funding)
    total_stress_funding = sum(stress_funding)
    return {
        "episode_count": len(ordered),
        "entry_date_count": len({datetime.fromtimestamp(int(row["entry_ts"]), timezone.utc).date().isoformat() for row in ordered}),
        "asset_count": len({str(row["base"]) for row in ordered}),
        "positive_episode_count": sum(value > 0 for value in price_normal),
        "price_win_rate": sum(value > 0 for value in price_normal) / len(price_normal) if price_normal else 0.0,
        "price_normal_net_quote": total_price,
        "price_normal_expectancy_quote": statistics.mean(price_normal) if price_normal else 0.0,
        "price_stress_net_quote": total_stress_price,
        "funding_quote": total_funding,
        "stress_funding_quote": total_stress_funding,
        "total_normal_net_quote": total_price + total_funding,
        "total_stress_net_quote": total_stress_price + total_stress_funding,
        "price_profit_factor": profit_factor,
        "price_profit_factor_infinite": losses == 0 and gains > 0,
        "price_gross_profit_quote": gains,
        "price_gross_loss_quote": losses,
        "maximum_drawdown_quote": max_drawdown,
        "maximum_positive_episode_share": maximum_episode_share,
        "maximum_positive_asset_share": maximum_asset_share,
        "maximum_positive_date_share": maximum_date_share,
    }


def _quality_artifact_is_valid(report: Mapping[str, Any]) -> bool:
    expected = str(report.get("artifact_hash") or "")
    payload = {key: value for key, value in report.items() if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}}
    return len(expected) == 64 and sha256_json(payload) == expected


def freeze_train_plan(
    *,
    parent_plan_path: str | Path,
    expected_parent_plan_hash: str,
    quality_report_path: str | Path,
    train_input_root: str | Path,
    output_plan_path: str | Path,
    max_runtime_sec: int = 600,
) -> dict[str, Any]:
    if not 0 < int(max_runtime_sec) <= 1_800:
        raise ValueError("train freeze MaxRuntimeSec must be in [1, 1800]")
    started = time.monotonic()
    parent_path = Path(parent_plan_path).expanduser().resolve()
    quality_path = Path(quality_report_path).expanduser().resolve()
    input_root = Path(train_input_root).expanduser().resolve()
    output_path = Path(output_plan_path).expanduser().resolve()
    if input_root.exists() or output_path.exists():
        raise FileExistsError("train input root and plan must be immutable new paths")
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    validate_gate_spot_perp_plan(parent, expected_plan_hash=expected_parent_plan_hash)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    if (
        quality.get("schema") != QUALITY_SCHEMA
        or quality.get("final") is not True
        or quality.get("decision") != "GATE_SPOT_PERP_HISTORY_READY_FOR_TRAIN_FEASIBILITY"
        or quality.get("plan_hash") != expected_parent_plan_hash
        or not _quality_artifact_is_valid(quality)
    ):
        raise ValueError("quality report is not final, accepted, and hash-valid")
    sample = parent["sample_plan"]
    window_start = int(sample["window_start_sec"])
    signal_start = window_start + int(sample["warmup_days"]) * DAY_SEC
    train_end = signal_start + int(sample["train_days"]) * DAY_SEC
    asset_inputs: list[dict[str, Any]] = []
    input_root.mkdir(parents=True, exist_ok=False)
    for index, asset in enumerate((row for row in quality["asset_reports"] if row.get("accepted") is True), start=1):
        if time.monotonic() - started >= int(max_runtime_sec):
            raise TimeoutError("train input freeze exceeded MaxRuntimeSec")
        base = str(asset["base"]).upper()
        print(f"[train-freeze] asset={index}/{quality['accepted_asset_count']} base={base}", flush=True)
        normalized = _read_jsonl_hash_bound(asset["normalized_path"], asset["normalized_sha256"])
        funding = _read_jsonl_hash_bound(asset["funding_path"], asset["funding_sha256"])
        train_rows = [row for row in normalized if window_start <= int(row["ts"]) < train_end]
        train_funding = [row for row in funding if window_start <= int(row["ts"]) < train_end]
        row_path = input_root / "assets" / f"{base}.jsonl"
        funding_path = input_root / "funding" / f"{base}.jsonl"
        row_count = _atomic_write_jsonl(row_path, train_rows)
        funding_count = _atomic_write_jsonl(funding_path, train_funding)
        asset_inputs.append(
            {
                "canonical_asset_id": asset["canonical_asset_id"],
                "base": base,
                "train_rows_path": str(row_path),
                "train_rows_sha256": sha256_file(row_path),
                "train_row_count": row_count,
                "train_funding_path": str(funding_path),
                "train_funding_sha256": sha256_file(funding_path),
                "train_funding_count": funding_count,
            }
        )
    if len(asset_inputs) < MINIMUM_ASSETS:
        raise ValueError("fewer than eight accepted train inputs")
    snapshot_manifest = os.environ.get("TRADING_MVP_CODE_SNAPSHOT_MANIFEST", "").strip()
    snapshot_manifest_sha256 = os.environ.get("TRADING_MVP_CODE_SNAPSHOT_MANIFEST_SHA256", "").strip().lower()
    snapshot_hash = os.environ.get("TRADING_MVP_CODE_SNAPSHOT_HASH", "").strip().lower()
    if not snapshot_manifest or not snapshot_manifest_sha256 or not snapshot_hash:
        raise ValueError("immutable code snapshot provenance is required")
    snapshot_manifest_path = Path(snapshot_manifest).expanduser().resolve()
    if sha256_file(snapshot_manifest_path) != snapshot_manifest_sha256:
        raise ValueError("code snapshot manifest hash mismatch")
    train_plan: dict[str, Any] = {
        "schema": TRAIN_PLAN_SCHEMA,
        "mode": "PlanOnly",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final": True,
        "parent_plan_path": str(parent_path),
        "parent_plan_hash": expected_parent_plan_hash,
        "quality_report_path": str(quality_path),
        "quality_artifact_hash": quality["artifact_hash"],
        "input_hashes": {
            "parent_plan_sha256": sha256_file(parent_path),
            "quality_report_sha256": sha256_file(quality_path),
        },
        "code_provenance": {
            "immutable_snapshot": True,
            "code_snapshot_manifest": str(snapshot_manifest_path),
            "code_snapshot_manifest_sha256": snapshot_manifest_sha256,
            "code_snapshot_hash": snapshot_hash,
            "train_module_path": str(Path(__file__).resolve()),
            "train_module_sha256": sha256_file(Path(__file__).resolve()),
        },
        "train_window": {
            "data_start_sec": window_start,
            "signal_start_sec": signal_start,
            "train_end_sec": train_end,
            "warmup_days": int(sample["warmup_days"]),
            "train_days": int(sample["train_days"]),
            "oos_embargoed": True,
        },
        "strategy": parent["strategy"],
        "economics": {
            "normal_cycle_cost_bps": float(parent["economics"]["normal_cycle_cost"]["total_bps"]),
            "stress_cycle_cost_bps": float(parent["economics"]["stress_cycle_cost"]["total_bps"]),
            "funding_cannot_rescue_price_gate": True,
            "favorable_funding_stress_haircut": 0.5,
        },
        "feasibility_gates": {
            "minimum_independent_episodes": 20,
            "minimum_entry_dates": 10,
            "minimum_assets_with_episodes": 4,
            "price_normal_expectancy_quote_gt": 0.0,
            "price_profit_factor_min": 1.2,
            "price_stress_net_quote_min": 0.0,
            "maximum_positive_asset_date_or_episode_share": 0.25,
        },
        "asset_inputs": asset_inputs,
        "safety": {
            "oos_read": False,
            "returns_read_before_plan_freeze": False,
            "grid_search": False,
            "retune": False,
            "network_access": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
        "next_allowed_command": "fast-edge-gate-spot-perp-train-evaluate",
    }
    train_plan["plan_hash"] = sha256_json(
        {key: value for key, value in train_plan.items() if key not in {"generated_at_utc", "plan_hash"}}
    )
    _atomic_write_json(output_path, train_plan)
    train_plan["output_path"] = str(output_path)
    train_plan["runtime_sec"] = round(time.monotonic() - started, 6)
    return train_plan


def validate_train_plan(plan: Mapping[str, Any], *, expected_plan_hash: str) -> None:
    if plan.get("schema") != TRAIN_PLAN_SCHEMA or plan.get("final") is not True:
        raise ValueError("invalid train plan schema/finality")
    actual = sha256_json({key: value for key, value in plan.items() if key not in {"generated_at_utc", "plan_hash"}})
    if actual != expected_plan_hash or plan.get("plan_hash") != expected_plan_hash:
        raise ValueError("train plan hash mismatch")
    if (plan.get("safety") or {}).get("oos_read") is not False:
        raise ValueError("train plan violates OOS embargo")
    provenance = plan.get("code_provenance") or {}
    if provenance.get("immutable_snapshot") is not True:
        raise ValueError("train plan requires immutable code provenance")
    manifest_path = Path(str(provenance.get("code_snapshot_manifest") or ""))
    if not manifest_path.is_file() or sha256_file(manifest_path) != provenance.get("code_snapshot_manifest_sha256"):
        raise ValueError("train code snapshot manifest is missing or changed")


def _evaluate_once(plan: Mapping[str, Any], *, max_runtime_sec: int) -> dict[str, Any]:
    started = time.monotonic()
    strategy = plan["strategy"]
    economics = plan["economics"]
    window = plan["train_window"]
    all_episodes: list[dict[str, Any]] = []
    diagnostics: dict[str, dict[str, int]] = {}
    for index, asset in enumerate(plan["asset_inputs"], start=1):
        if time.monotonic() - started >= max_runtime_sec:
            raise TimeoutError("train evaluation exceeded MaxRuntimeSec")
        base = str(asset["base"])
        print(f"[train-evaluate] asset={index}/{len(plan['asset_inputs'])} base={base}", flush=True)
        rows = _read_jsonl_hash_bound(asset["train_rows_path"], asset["train_rows_sha256"])
        funding = _read_jsonl_hash_bound(asset["train_funding_path"], asset["train_funding_sha256"])
        episodes, asset_diagnostics = simulate_asset_train(
            base=base,
            canonical_asset_id=str(asset["canonical_asset_id"]),
            rows=rows,
            funding_rows=funding,
            signal_start_sec=int(window["signal_start_sec"]),
            train_end_sec=int(window["train_end_sec"]),
            entry_threshold_bps=float(strategy["entry_threshold_bps"]),
            exit_threshold_bps=float(strategy["exit_threshold_bps"]),
            max_hold_hours=int(strategy["max_hold_hours"]),
            adverse_funding_entry_floor=float(strategy["adverse_funding_entry_floor"]),
            normal_cycle_cost_bps=float(economics["normal_cycle_cost_bps"]),
            stress_cycle_cost_bps=float(economics["stress_cycle_cost_bps"]),
            notional_per_leg_quote=float(strategy["notional_per_leg_quote"]),
        )
        all_episodes.extend(episodes)
        diagnostics[base] = asset_diagnostics
    metrics = compute_episode_metrics(all_episodes)
    gates = plan["feasibility_gates"]
    reasons: list[str] = []
    if metrics["episode_count"] < int(gates["minimum_independent_episodes"]):
        reasons.append("minimum_independent_episodes")
    if metrics["entry_date_count"] < int(gates["minimum_entry_dates"]):
        reasons.append("minimum_entry_dates")
    if metrics["asset_count"] < int(gates["minimum_assets_with_episodes"]):
        reasons.append("minimum_assets_with_episodes")
    if metrics["price_normal_expectancy_quote"] <= float(gates["price_normal_expectancy_quote_gt"]):
        reasons.append("price_normal_expectancy")
    profit_factor = metrics["price_profit_factor"]
    if not metrics["price_profit_factor_infinite"] and (profit_factor is None or profit_factor < float(gates["price_profit_factor_min"])):
        reasons.append("price_profit_factor")
    if metrics["price_stress_net_quote"] < float(gates["price_stress_net_quote_min"]):
        reasons.append("price_stress_net")
    concentration_limit = float(gates["maximum_positive_asset_date_or_episode_share"])
    if max(
        metrics["maximum_positive_asset_share"],
        metrics["maximum_positive_date_share"],
        metrics["maximum_positive_episode_share"],
    ) > concentration_limit:
        reasons.append("positive_pnl_concentration")
    decision = "FEASIBLE_FOR_OOS" if not reasons else "INFEASIBLE_ON_CURRENT_DATA"
    result: dict[str, Any] = {
        "schema": TRAIN_RESULT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final": True,
        "decision": decision,
        "train_plan_hash": plan["plan_hash"],
        "metrics": metrics,
        "rejection_reasons": reasons,
        "asset_diagnostics": diagnostics,
        "episodes": all_episodes,
        "oos_read": False,
        "grid_search": False,
        "retune": False,
        "network_access": False,
        "live_orders": False,
        "next_allowed_command": "fast-edge-gate-spot-perp-oos-planonly" if decision == "FEASIBLE_FOR_OOS" else "none_branch_closed_no_retune",
    }
    result["deterministic_result_hash"] = sha256_json(
        {key: value for key, value in result.items() if key not in {"generated_at_utc", "deterministic_result_hash"}}
    )
    result["runtime_sec"] = round(time.monotonic() - started, 6)
    return result


def evaluate_train_plan(
    *,
    train_plan_path: str | Path,
    expected_train_plan_hash: str,
    output_path: str | Path,
    max_runtime_sec: int = 1_800,
) -> dict[str, Any]:
    if not 0 < int(max_runtime_sec) <= 1_800:
        raise ValueError("train evaluation MaxRuntimeSec must be in [1, 1800]")
    plan_path = Path(train_plan_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"train result already exists: {target}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_train_plan(plan, expected_plan_hash=expected_train_plan_hash)
    first = _evaluate_once(plan, max_runtime_sec=int(max_runtime_sec))
    second = _evaluate_once(plan, max_runtime_sec=int(max_runtime_sec))
    if first["deterministic_result_hash"] != second["deterministic_result_hash"]:
        raise RuntimeError("deterministic train repeat mismatch")
    first["deterministic_repeat_match"] = True
    first["deterministic_repeat_hash"] = second["deterministic_result_hash"]
    first["train_plan_path"] = str(plan_path)
    first["train_plan_file_sha256"] = sha256_file(plan_path)
    first["runtime_sec_with_repeat"] = round(first["runtime_sec"] + second["runtime_sec"], 6)
    _atomic_write_json(target, first)
    first["output_path"] = str(target)
    first["output_file_sha256"] = sha256_file(target)
    return first


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen Gate spot/perp train-only evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--parent-plan", required=True)
    freeze_parser.add_argument("--expected-parent-plan-hash", required=True)
    freeze_parser.add_argument("--quality-report", required=True)
    freeze_parser.add_argument("--train-input-root", required=True)
    freeze_parser.add_argument("--out-plan", required=True)
    freeze_parser.add_argument("--max-runtime-sec", type=int, default=600)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--train-plan", required=True)
    evaluate_parser.add_argument("--expected-train-plan-hash", required=True)
    evaluate_parser.add_argument("--out", required=True)
    evaluate_parser.add_argument("--max-runtime-sec", type=int, default=1_800)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_train_plan(
            parent_plan_path=args.parent_plan,
            expected_parent_plan_hash=args.expected_parent_plan_hash,
            quality_report_path=args.quality_report,
            train_input_root=args.train_input_root,
            output_plan_path=args.out_plan,
            max_runtime_sec=args.max_runtime_sec,
        )
        print(json.dumps({key: result[key] for key in ("plan_hash", "output_path", "runtime_sec")}, ensure_ascii=False, indent=2))
        return 0
    result = evaluate_train_plan(
        train_plan_path=args.train_plan,
        expected_train_plan_hash=args.expected_train_plan_hash,
        output_path=args.out,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "episode_count": result["metrics"]["episode_count"],
                "rejection_reasons": result["rejection_reasons"],
                "deterministic_repeat_match": result["deterministic_repeat_match"],
                "output_path": result["output_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
