from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from funding import FundingContract, GateFundingClient
import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_membership_momentum_v2_execution_probe as probe
import gate_membership_momentum_v2_execution_selection as selection
import gate_membership_momentum_v2_oos as v2_oos
import gate_membership_momentum_v2_train as v2_train
from historical_basis_probe import depth_execution_metrics
from perp_collector import GatePerpRestClient


WINDOW_PLAN_SCHEMA = (
    "trading_mvp_gate_membership_momentum_v2_execution_probe_window_plan_v1"
)
WINDOW_PLAN_DECISION = (
    "GATE_MEMBERSHIP_MOMENTUM_V2_EXECUTION_PROBE_WINDOW_PLAN_READY"
)
PAPER_BOUNDARY_WINDOW_MODE = (
    "gate_membership_momentum_v2_paper_execution_boundary_window_planonly"
)
SAMPLE_SCHEMA = "trading_mvp_gate_membership_momentum_v2_execution_probe_sample_v1"
MANIFEST_SCHEMA = "trading_mvp_gate_membership_momentum_v2_execution_probe_manifest_v1"
REPORT_SCHEMA = "trading_mvp_gate_membership_momentum_v2_execution_probe_report_v1"
PAPER_FORWARD_READY_DECISION = "PAPER_FORWARD_READY"
REJECT_DECISION = "REJECT"
MAX_RUNTIME_SEC = 1_800
MIN_RUNTIME_SEC = probe.WINDOW_DURATION_SEC
MAX_WORKERS = 8
DEPTH_LIMIT = 50


ContractFetcher = Callable[[], Iterable[FundingContract]]
DepthFetcher = Callable[[FundingContract, int], Any]


def _utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "deterministic_result_hash"}
        }
    )


def _p95(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid execution-probe JSONL line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"execution-probe JSONL line {line_number} is not an object")
            rows.append(value)
    return rows


def _validate_probe_and_selection(
    *,
    probe_plan_path: str | Path,
    expected_probe_plan_hash: str,
    selection_path: str | Path,
    expected_selection_hash: str,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    resolved_probe = Path(probe_plan_path).expanduser().resolve()
    probe_plan = probe.validate_execution_probe_plan(
        resolved_probe,
        v2_train._validate_hash(expected_probe_plan_hash, label="execution probe plan hash"),
    )
    resolved_selection = Path(selection_path).expanduser().resolve()
    selected = selection.validate_selection_artifact(
        resolved_selection,
        v2_train._validate_hash(expected_selection_hash, label="execution selection hash"),
    )
    if (
        selected.get("decision") != selection.SELECTION_READY_DECISION
        or selected.get("execution_probe_collect_allowed") is not True
        or selected.get("next_allowed_command")
        != "fast-edge-membership-momentum-v2-execution-probe-window-plan"
    ):
        raise ValueError("execution probe requires a ready causal selection")
    authorization = selected.get("probe_plan_authorization")
    if not isinstance(authorization, Mapping):
        raise ValueError("execution selection probe authorization is missing")
    if (
        Path(str(authorization.get("path") or "")).expanduser().resolve()
        != resolved_probe
        or authorization.get("file_sha256") != v3_history_plan.sha256_file(resolved_probe)
        or authorization.get("plan_hash") != probe_plan["plan_hash"]
    ):
        raise ValueError("execution selection belongs to another probe PlanOnly")
    positions = selected.get("selected_positions")
    if not isinstance(positions, list) or not positions:
        raise ValueError("execution selection has no selected positions")
    identities: set[str] = set()
    symbols: set[str] = set()
    sides: set[str] = set()
    for raw in positions:
        if not isinstance(raw, Mapping):
            raise ValueError("execution selection position is not an object")
        identity = str(raw.get("canonical_asset_id") or "").strip()
        symbol = str(raw.get("symbol") or "").strip().upper()
        base = str(raw.get("base") or "").strip().upper()
        side = str(raw.get("side") or "").strip().lower()
        if not identity or not symbol or not base or side not in {"long", "short"}:
            raise ValueError("execution selection position identity/side is invalid")
        if identity in identities or symbol in symbols:
            raise ValueError("execution selection contains duplicate positions")
        identities.add(identity)
        symbols.add(symbol)
        sides.add(side)
    if sides != {"long", "short"}:
        raise ValueError("execution selection must contain both long and short buckets")
    return probe_plan, resolved_probe, selected, resolved_selection


def build_window_collect_plan(
    *,
    probe_plan_path: str | Path,
    expected_probe_plan_hash: str,
    selection_path: str | Path,
    expected_selection_hash: str,
    output_path: str | Path | None,
    samples_path: str | Path,
    manifest_path: str | Path,
    run_id: str,
    window_index: int,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    workers: int = 4,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    runtime = int(max_runtime_sec)
    if runtime < MIN_RUNTIME_SEC or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [{MIN_RUNTIME_SEC}, {MAX_RUNTIME_SEC}]")
    worker_count = int(workers)
    if worker_count < 1 or worker_count > MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    index = int(window_index)
    if index < 0 or index >= probe.WINDOW_COUNT:
        raise ValueError("window_index must be 0, 1 or 2")
    probe_plan, resolved_probe, selected, resolved_selection = _validate_probe_and_selection(
        probe_plan_path=probe_plan_path,
        expected_probe_plan_hash=expected_probe_plan_hash,
        selection_path=selection_path,
        expected_selection_hash=expected_selection_hash,
    )
    window = dict(probe_plan["execution_contract"]["windows"][index])
    if int(window.get("index", -1)) != index:
        raise ValueError("execution probe window index mismatch")
    samples_target = Path(samples_path).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    if samples_target == manifest_target:
        raise ValueError("samples_path and manifest_path must be distinct")
    selected_positions = [
        {
            "canonical_asset_id": str(row["canonical_asset_id"]),
            "symbol": str(row["symbol"]).upper(),
            "base": str(row["base"]).upper(),
            "side": str(row["side"]).lower(),
        }
        for row in selected["selected_positions"]
    ]
    selected_positions.sort(key=lambda row: (row["side"], row["canonical_asset_id"], row["symbol"]))
    module_paths = {
        "module": Path(__file__).resolve(),
        "probe_module": Path(probe.__file__).resolve(),
        "selection_module": Path(selection.__file__).resolve(),
        "depth_metrics_module": Path(__import__("historical_basis_probe").__file__).resolve(),
        "perp_client_module": Path(__import__("perp_collector").__file__).resolve(),
        "funding_client_module": Path(__import__("funding").__file__).resolve(),
    }
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    execution = probe_plan["execution_contract"]
    contract: dict[str, Any] = {
        "schema": WINDOW_PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": "gate_membership_momentum_v2_execution_probe_window_planonly",
        "stage": "execution_capacity_probe_window",
        "decision": WINDOW_PLAN_DECISION,
        "hypothesis_id": probe_plan["hypothesis_id"],
        "research_only": True,
        "network_access": False,
        "public_api_only": True,
        "grid_search": False,
        "retune": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "probe_plan_authorization": {
            "path": str(resolved_probe),
            "file_sha256": v3_history_plan.sha256_file(resolved_probe),
            "plan_hash": probe_plan["plan_hash"],
        },
        "selection_authorization": {
            "path": str(resolved_selection),
            "file_sha256": v3_history_plan.sha256_file(resolved_selection),
            "artifact_hash": selected["artifact_hash"],
        },
        "window_contract": {
            **window,
            "duration_sec": int(execution["duration_sec"]),
            "interval_sec": int(execution["interval_sec"]),
            "expected_cycles": int(execution["duration_sec"]) // int(execution["interval_sec"]),
        },
        "collector_contract": {
            "exchange": "gateio",
            "market_type": "usdt_linear_perpetual",
            "public_contracts_endpoint": "https://api.gateio.ws/api/v4/futures/usdt/contracts",
            "public_depth_endpoint": "https://api.gateio.ws/api/v4/futures/usdt/order_book",
            "depth_limit": DEPTH_LIMIT,
            "maximum_runtime_sec": runtime,
            "maximum_workers": worker_count,
            "notional_quote_per_asset": float(execution["notional_quote_per_asset"]),
            "minimum_valid_snapshots_per_asset_per_window": int(
                execution["minimum_valid_snapshots_per_asset_per_window"]
            ),
            "minimum_coverage_per_asset": float(execution["minimum_coverage_per_asset"]),
            "maximum_timestamp_skew_ms": float(execution["maximum_timestamp_skew_ms"]),
            "maximum_quote_age_ms": float(execution["maximum_quote_age_ms"]),
            "minimum_capacity_quote_per_asset": float(
                execution["minimum_capacity_quote_per_asset"]
            ),
            "maximum_p95_impact_bps": float(execution["maximum_p95_impact_bps"]),
            "critical_errors_allowed": int(
                execution["critical_schema_reconnect_or_stale_quote_errors_allowed"]
            ),
        },
        "selected_positions": selected_positions,
        "output_contract": {
            "samples_path": str(samples_target),
            "manifest_path": str(manifest_target),
            "overwrite_allowed": False,
        },
        "code_provenance": code_provenance,
        "maximum_authority": "PUBLIC_EXECUTION_PROBE_WINDOW_COLLECT",
        "next_allowed_command": "fast-edge-membership-momentum-v2-execution-probe-collect",
        "blocked_actions": [
            "manual_shortlist",
            "threshold_weakening",
            "grid_search",
            "retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
    }
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "probe_plan_hash": probe_plan["plan_hash"],
            "probe_plan_file_sha256": contract["probe_plan_authorization"]["file_sha256"],
            "selection_hash": selected["artifact_hash"],
            "selection_file_sha256": contract["selection_authorization"]["file_sha256"],
            "window_contract": contract["window_contract"],
            "selected_positions": selected_positions,
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = v3_history_plan.sha256_json(contract)
    approval_phrase = (
        "Подтверждаю visible Gate membership-momentum-v2 execution probe "
        f"plan_hash={plan_hash}, run_id={normalized_run_id}, window_index={index}, "
        f"MaxRuntimeSec={runtime}, public order book only, без grid/live/private API keys."
    )
    payload = {
        **contract,
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": plan_hash,
        "approval_phrase": approval_phrase,
        "frozen_contract": contract,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, payload)
    return payload


def build_paper_boundary_window_collect_plan(
    *,
    paper_plan_path: str | Path,
    expected_paper_plan_hash: str,
    approval_path: str | Path,
    selection_path: str | Path,
    expected_selection_hash: str,
    boundary: str,
    output_path: str | Path | None,
    samples_path: str | Path,
    manifest_path: str | Path,
    run_id: str,
    window_index: int,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    workers: int = 4,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    # Imported lazily because paper_state also uses this runtime for provenance checks.
    import gate_membership_momentum_v2_paper_plan as paper_plan
    import gate_membership_momentum_v2_paper_state as paper_state

    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    normalized_boundary = str(boundary).strip().lower()
    if normalized_boundary not in {"entry", "exit"}:
        raise ValueError("paper execution boundary must be entry or exit")
    runtime = int(max_runtime_sec)
    if runtime < MIN_RUNTIME_SEC or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [{MIN_RUNTIME_SEC}, {MAX_RUNTIME_SEC}]")
    worker_count = int(workers)
    if worker_count < 1 or worker_count > MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    index = int(window_index)
    if index < 0 or index >= probe.WINDOW_COUNT:
        raise ValueError("window_index must be 0, 1 or 2")

    plan, resolved_paper, approval, resolved_approval = (
        paper_state._validate_plan_and_approval(
            plan_path=paper_plan_path,
            expected_plan_hash=expected_paper_plan_hash,
            approval_path=approval_path,
        )
    )
    selected, resolved_selection, event_probe, resolved_probe = (
        paper_state._validate_event_selection(
            plan,
            selection_path=selection_path,
            expected_selection_hash=expected_selection_hash,
        )
    )
    execution = event_probe.get("execution_contract")
    if not isinstance(execution, Mapping):
        raise ValueError("paper event execution contract is missing")
    windows = execution.get("windows")
    if not isinstance(windows, list) or len(windows) != probe.WINDOW_COUNT:
        raise ValueError("paper event requires exactly three execution windows")
    raw_window = windows[index]
    if not isinstance(raw_window, Mapping) or int(raw_window.get("index", -1)) != index:
        raise ValueError("paper execution window index mismatch")
    shift_sec = (
        int(plan["paper_contract"]["hold_days"]) * 24 * 60 * 60
        if normalized_boundary == "exit"
        else 0
    )
    start_ts = int(raw_window["start_ts"]) + shift_sec
    end_ts = int(raw_window["end_ts"]) + shift_sec
    window = {
        "index": index,
        "start_ts": start_ts,
        "start_utc": _utc_iso(start_ts),
        "end_ts": end_ts,
        "end_utc": _utc_iso(end_ts),
        "duration_sec": int(execution["duration_sec"]),
        "interval_sec": int(execution["interval_sec"]),
        "expected_cycles": int(execution["duration_sec"])
        // int(execution["interval_sec"]),
    }
    if window["end_ts"] - window["start_ts"] != window["duration_sec"]:
        raise ValueError("paper execution window duration mismatch")

    samples_target = Path(samples_path).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    if samples_target == manifest_target:
        raise ValueError("samples_path and manifest_path must be distinct")
    selected_positions = [
        {
            "canonical_asset_id": str(row["canonical_asset_id"]),
            "symbol": str(row["symbol"]).upper(),
            "base": str(row["base"]).upper(),
            "side": str(row["side"]).lower(),
        }
        for row in selected["selected_positions"]
    ]
    selected_positions.sort(
        key=lambda row: (row["side"], row["canonical_asset_id"], row["symbol"])
    )
    module_paths = {
        "module": Path(__file__).resolve(),
        "paper_state_module": Path(paper_state.__file__).resolve(),
        "paper_plan_module": Path(paper_plan.__file__).resolve(),
        "probe_module": Path(probe.__file__).resolve(),
        "selection_module": Path(selection.__file__).resolve(),
        "depth_metrics_module": Path(__import__("historical_basis_probe").__file__).resolve(),
        "perp_client_module": Path(__import__("perp_collector").__file__).resolve(),
        "funding_client_module": Path(__import__("funding").__file__).resolve(),
    }
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    paper_contract = plan["paper_contract"]
    frozen: dict[str, Any] = {
        "schema": WINDOW_PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": PAPER_BOUNDARY_WINDOW_MODE,
        "stage": "paper_execution_boundary_window",
        "decision": WINDOW_PLAN_DECISION,
        "paper_boundary": normalized_boundary,
        "hypothesis_id": plan["hypothesis_id"],
        "research_only": True,
        "network_access": False,
        "public_api_only": True,
        "grid_search": False,
        "retune": False,
        "paper_forward_allowed": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "paper_plan_authorization": {
            "path": str(resolved_paper),
            "file_sha256": v3_history_plan.sha256_file(resolved_paper),
            "plan_hash": plan["plan_hash"],
        },
        "paper_approval_authorization": {
            "path": str(resolved_approval),
            "file_sha256": v3_history_plan.sha256_file(resolved_approval),
            "approval_id": approval["approval_id"],
        },
        "probe_plan_authorization": {
            "path": str(resolved_probe),
            "file_sha256": v3_history_plan.sha256_file(resolved_probe),
            "plan_hash": event_probe["plan_hash"],
        },
        "selection_authorization": {
            "path": str(resolved_selection),
            "file_sha256": v3_history_plan.sha256_file(resolved_selection),
            "artifact_hash": selected["artifact_hash"],
        },
        "window_contract": window,
        "collector_contract": {
            "exchange": "gateio",
            "market_type": "usdt_linear_perpetual",
            "public_contracts_endpoint": "https://api.gateio.ws/api/v4/futures/usdt/contracts",
            "public_depth_endpoint": "https://api.gateio.ws/api/v4/futures/usdt/order_book",
            "depth_limit": DEPTH_LIMIT,
            "maximum_runtime_sec": runtime,
            "maximum_workers": worker_count,
            "notional_quote_per_asset": float(paper_contract["notional_quote_per_asset"]),
            "minimum_valid_snapshots_per_asset_per_window": int(
                paper_contract["minimum_valid_snapshots_per_asset_per_window"]
            ),
            "minimum_coverage_per_asset": float(
                paper_contract["minimum_coverage_per_asset"]
            ),
            "maximum_timestamp_skew_ms": float(
                paper_contract["maximum_timestamp_skew_ms"]
            ),
            "maximum_quote_age_ms": float(paper_contract["maximum_quote_age_ms"]),
            "minimum_capacity_quote_per_asset": float(
                paper_contract["minimum_capacity_quote_per_asset"]
            ),
            "maximum_p95_impact_bps": float(
                paper_contract["maximum_p95_impact_bps"]
            ),
            "critical_errors_allowed": 0,
        },
        "selected_positions": selected_positions,
        "output_contract": {
            "samples_path": str(samples_target),
            "manifest_path": str(manifest_target),
            "overwrite_allowed": False,
        },
        "code_provenance": code_provenance,
        "maximum_authority": "PUBLIC_PAPER_EXECUTION_BOUNDARY_WINDOW_COLLECT",
        "next_allowed_command": "fast-edge-membership-momentum-v2-execution-probe-collect",
        "blocked_actions": [
            "manual_shortlist",
            "manual_execution_price",
            "grid_search",
            "retune",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
    }
    frozen["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "paper_plan_hash": plan["plan_hash"],
            "paper_approval_id": approval["approval_id"],
            "probe_plan_hash": event_probe["plan_hash"],
            "selection_hash": selected["artifact_hash"],
            "paper_boundary": normalized_boundary,
            "window_contract": window,
            "selected_positions": selected_positions,
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = v3_history_plan.sha256_json(frozen)
    approval_phrase = (
        "Подтверждаю visible Gate membership-momentum-v2 paper execution "
        f"plan_hash={plan_hash}, run_id={normalized_run_id}, boundary={normalized_boundary}, "
        f"window_index={index}, MaxRuntimeSec={runtime}, public order book only, "
        "без live/private API keys/leverage/margin."
    )
    payload = {
        **frozen,
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": plan_hash,
        "approval_phrase": approval_phrase,
        "frozen_contract": frozen,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, payload)
    return payload


def validate_window_collect_plan(
    path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    plan = v2_train._read_json_object(resolved)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != WINDOW_PLAN_SCHEMA or plan.get("decision") != WINDOW_PLAN_DECISION:
        raise ValueError("unexpected momentum-v2 execution window PlanOnly")
    if not isinstance(frozen, Mapping):
        raise ValueError("execution window frozen contract is missing")
    computed = v3_history_plan.sha256_json(frozen)
    if (
        plan.get("plan_hash") != computed
        or (expected_plan_hash is not None and str(expected_plan_hash) != computed)
        or not all(plan.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("execution window PlanOnly hash mismatch")
    probe_auth = plan.get("probe_plan_authorization")
    selection_auth = plan.get("selection_authorization")
    if not isinstance(probe_auth, Mapping) or not isinstance(selection_auth, Mapping):
        raise ValueError("execution window source authorization is missing")
    if plan.get("mode") == PAPER_BOUNDARY_WINDOW_MODE:
        paper_auth = plan.get("paper_plan_authorization")
        approval_auth = plan.get("paper_approval_authorization")
        if not isinstance(paper_auth, Mapping) or not isinstance(approval_auth, Mapping):
            raise ValueError("paper execution window authorization is missing")
        rebuilt = build_paper_boundary_window_collect_plan(
            paper_plan_path=str(paper_auth.get("path") or ""),
            expected_paper_plan_hash=str(paper_auth.get("plan_hash") or ""),
            approval_path=str(approval_auth.get("path") or ""),
            selection_path=str(selection_auth.get("path") or ""),
            expected_selection_hash=str(selection_auth.get("artifact_hash") or ""),
            boundary=str(plan.get("paper_boundary") or ""),
            output_path=None,
            samples_path=str(plan["output_contract"]["samples_path"]),
            manifest_path=str(plan["output_contract"]["manifest_path"]),
            run_id=str(plan.get("run_id") or ""),
            window_index=int(plan["window_contract"]["index"]),
            max_runtime_sec=int(plan["collector_contract"]["maximum_runtime_sec"]),
            workers=int(plan["collector_contract"]["maximum_workers"]),
            generated_at_utc=str(plan.get("generated_at_utc") or ""),
        )
    else:
        rebuilt = build_window_collect_plan(
            probe_plan_path=str(probe_auth.get("path") or ""),
            expected_probe_plan_hash=str(probe_auth.get("plan_hash") or ""),
            selection_path=str(selection_auth.get("path") or ""),
            expected_selection_hash=str(selection_auth.get("artifact_hash") or ""),
            output_path=None,
            samples_path=str(plan["output_contract"]["samples_path"]),
            manifest_path=str(plan["output_contract"]["manifest_path"]),
            run_id=str(plan.get("run_id") or ""),
            window_index=int(plan["window_contract"]["index"]),
            max_runtime_sec=int(plan["collector_contract"]["maximum_runtime_sec"]),
            workers=int(plan["collector_contract"]["maximum_workers"]),
            generated_at_utc=str(plan.get("generated_at_utc") or ""),
        )
    if rebuilt["plan_hash"] != computed or rebuilt["frozen_contract"] != frozen:
        raise ValueError("execution window PlanOnly no longer matches source/code provenance")
    return plan


def _normalize_gate_book(
    contract: FundingContract,
    payload: Any,
) -> tuple[list[list[float]], list[list[float]], float]:
    if not isinstance(payload, Mapping):
        raise ValueError("Gate depth payload is not an object")
    multiplier_raw = (contract.raw or {}).get("quanto_multiplier")
    try:
        multiplier = float(multiplier_raw or 1.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Gate contract multiplier is invalid") from exc
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("Gate contract multiplier is invalid")

    def levels(value: Any) -> list[list[float]]:
        result: list[list[float]] = []
        if not isinstance(value, list):
            raise ValueError("Gate depth side is not a list")
        for raw in value:
            if isinstance(raw, Mapping):
                price_raw = raw.get("p") or raw.get("price")
                quantity_raw = raw.get("s") or raw.get("size")
            elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                price_raw, quantity_raw = raw[0], raw[1]
            else:
                raise ValueError("Gate depth level is invalid")
            try:
                price = float(price_raw)
                quantity = abs(float(quantity_raw)) * multiplier
            except (TypeError, ValueError) as exc:
                raise ValueError("Gate depth price/quantity is invalid") from exc
            if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
                raise ValueError("Gate depth price/quantity is invalid")
            result.append([price, quantity])
        if not result:
            raise ValueError("Gate depth side is empty")
        return result

    timestamp_raw = payload.get("update") or payload.get("current")
    try:
        exchange_ts = float(timestamp_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Gate depth timestamp is missing") from exc
    if exchange_ts > 10_000_000_000:
        exchange_ts /= 1000.0
    if not math.isfinite(exchange_ts) or exchange_ts <= 0:
        raise ValueError("Gate depth timestamp is invalid")
    return levels(payload.get("bids")), levels(payload.get("asks")), exchange_ts


def _compute_window_metrics(
    plan: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    window = plan["window_contract"]
    contract = plan["collector_contract"]
    expected_cycles = int(window["expected_cycles"])
    expected_positions = {
        str(row["canonical_asset_id"]): dict(row) for row in plan["selected_positions"]
    }
    by_cycle: dict[int, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    invalid_reasons: Counter[str] = Counter()
    for row in rows:
        if row.get("schema") != SAMPLE_SCHEMA:
            raise ValueError("execution probe sample schema mismatch")
        if (
            row.get("window_plan_hash") != plan["plan_hash"]
            or row.get("selection_hash") != plan["selection_authorization"]["artifact_hash"]
            or int(row.get("window_index", -1)) != int(window["index"])
        ):
            raise ValueError("execution probe sample provenance mismatch")
        cycle = int(row.get("cycle") or 0)
        identity = str(row.get("canonical_asset_id") or "")
        if cycle < 1 or cycle > expected_cycles or identity not in expected_positions:
            raise ValueError("execution probe sample cycle/identity is outside the frozen contract")
        expected = expected_positions[identity]
        if (
            str(row.get("symbol") or "").upper() != expected["symbol"]
            or str(row.get("base") or "").upper() != expected["base"]
            or str(row.get("side") or "").lower() != expected["side"]
        ):
            raise ValueError("execution probe sample identity changed after selection")
        if identity in by_cycle[cycle]:
            raise ValueError("duplicate execution probe sample for cycle/asset")
        by_cycle[cycle][identity] = row

    stats: dict[str, dict[str, Any]] = {
        identity: {
            "position": expected,
            "attempted": 0,
            "valid": 0,
            "buy_impacts": [],
            "sell_impacts": [],
            "buy_capacities": [],
            "sell_capacities": [],
            "quote_ages": [],
            "skews": [],
            "invalid_reasons": Counter(),
        }
        for identity, expected in expected_positions.items()
    }
    for cycle in range(1, expected_cycles + 1):
        cycle_rows = by_cycle.get(cycle, {})
        exchange_times = []
        for row in cycle_rows.values():
            if row.get("collection_error"):
                continue
            try:
                exchange_times.append(float(row["exchange_ts"]))
            except (KeyError, TypeError, ValueError):
                continue
        cycle_skew_ms = (
            (max(exchange_times) - min(exchange_times)) * 1000.0
            if len(exchange_times) >= 2
            else math.inf
        )
        for identity, expected in expected_positions.items():
            bucket = stats[identity]
            row = cycle_rows.get(identity)
            if row is None:
                bucket["invalid_reasons"]["missing_sample"] += 1
                invalid_reasons["missing_sample"] += 1
                continue
            bucket["attempted"] += 1
            reasons: list[str] = []
            if row.get("collection_error"):
                reasons.append("collection_error")
            try:
                received_ts = float(row.get("received_ts"))
                exchange_ts = float(row.get("exchange_ts"))
                quote_age_ms = (received_ts - exchange_ts) * 1000.0
            except (TypeError, ValueError):
                quote_age_ms = math.inf
                reasons.append("invalid_timestamp")
            if not math.isfinite(cycle_skew_ms) or cycle_skew_ms > float(
                contract["maximum_timestamp_skew_ms"]
            ):
                reasons.append("timestamp_skew")
            if (
                not math.isfinite(quote_age_ms)
                or quote_age_ms < 0
                or quote_age_ms > float(contract["maximum_quote_age_ms"])
            ):
                reasons.append("quote_age")
            buy = depth_execution_metrics(
                row.get("asks") or [],
                side="buy",
                notional_quote=float(contract["notional_quote_per_asset"]),
                max_impact_bps=float(contract["maximum_p95_impact_bps"]),
            )
            sell = depth_execution_metrics(
                row.get("bids") or [],
                side="sell",
                notional_quote=float(contract["notional_quote_per_asset"]),
                max_impact_bps=float(contract["maximum_p95_impact_bps"]),
            )
            if not buy["filled"] or not sell["filled"]:
                reasons.append("notional_not_filled")
            if (
                float(buy["impact_bps"]) > float(contract["maximum_p95_impact_bps"])
                or float(sell["impact_bps"]) > float(contract["maximum_p95_impact_bps"])
            ):
                reasons.append("impact")
            if (
                float(buy["capacity_quote_at_max_impact"])
                < float(contract["minimum_capacity_quote_per_asset"])
                or float(sell["capacity_quote_at_max_impact"])
                < float(contract["minimum_capacity_quote_per_asset"])
            ):
                reasons.append("capacity")
            if reasons:
                for reason in sorted(set(reasons)):
                    bucket["invalid_reasons"][reason] += 1
                    invalid_reasons[reason] += 1
                continue
            bucket["valid"] += 1
            bucket["buy_impacts"].append(float(buy["impact_bps"]))
            bucket["sell_impacts"].append(float(sell["impact_bps"]))
            bucket["buy_capacities"].append(float(buy["capacity_quote_at_max_impact"]))
            bucket["sell_capacities"].append(float(sell["capacity_quote_at_max_impact"]))
            bucket["quote_ages"].append(quote_age_ms)
            bucket["skews"].append(cycle_skew_ms)

    per_asset: list[dict[str, Any]] = []
    eligible_assets: list[str] = []
    eligible_by_side: dict[str, list[str]] = {"long": [], "short": []}
    for identity in sorted(stats):
        bucket = stats[identity]
        valid = int(bucket["valid"])
        coverage = valid / expected_cycles if expected_cycles else 0.0
        buy_p95 = _p95(bucket["buy_impacts"])
        sell_p95 = _p95(bucket["sell_impacts"])
        quote_age_p95 = _p95(bucket["quote_ages"])
        skew_p95 = _p95(bucket["skews"])
        minimum_buy_capacity = min(bucket["buy_capacities"], default=0.0)
        minimum_sell_capacity = min(bucket["sell_capacities"], default=0.0)
        reasons: list[str] = []
        if valid < int(contract["minimum_valid_snapshots_per_asset_per_window"]):
            reasons.append("valid_snapshots")
        if coverage < float(contract["minimum_coverage_per_asset"]):
            reasons.append("coverage")
        if buy_p95 is None or sell_p95 is None or max(buy_p95, sell_p95) > float(
            contract["maximum_p95_impact_bps"]
        ):
            reasons.append("p95_impact")
        if min(minimum_buy_capacity, minimum_sell_capacity) < float(
            contract["minimum_capacity_quote_per_asset"]
        ):
            reasons.append("capacity")
        if quote_age_p95 is None or quote_age_p95 > float(contract["maximum_quote_age_ms"]):
            reasons.append("quote_age")
        if skew_p95 is None or skew_p95 > float(contract["maximum_timestamp_skew_ms"]):
            reasons.append("timestamp_skew")
        eligible = not reasons
        position = bucket["position"]
        if eligible:
            eligible_assets.append(identity)
            eligible_by_side[position["side"]].append(identity)
        per_asset.append(
            {
                **position,
                "attempted_snapshots": int(bucket["attempted"]),
                "valid_snapshots": valid,
                "coverage": coverage,
                "p95_buy_impact_bps": buy_p95,
                "p95_sell_impact_bps": sell_p95,
                "minimum_buy_capacity_quote": minimum_buy_capacity,
                "minimum_sell_capacity_quote": minimum_sell_capacity,
                "p95_quote_age_ms": quote_age_p95,
                "p95_timestamp_skew_ms": skew_p95,
                "eligible": eligible,
                "eligibility_reasons": reasons,
                "invalid_reason_counts": dict(sorted(bucket["invalid_reasons"].items())),
            }
        )
    return {
        "expected_cycles": expected_cycles,
        "observed_cycles": len(by_cycle),
        "sample_rows": len(rows),
        "selected_asset_count": len(expected_positions),
        "eligible_asset_count": len(eligible_assets),
        "eligible_assets": eligible_assets,
        "eligible_assets_by_side": eligible_by_side,
        "all_selected_assets_eligible": len(eligible_assets) == len(expected_positions),
        "invalid_reason_counts": dict(sorted(invalid_reasons.items())),
        "per_asset": per_asset,
    }


def finalize_execution_probe_window(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    completed_cycles: int,
    errors: Sequence[str],
    critical_errors: Sequence[str],
    runtime_sec: float,
) -> dict[str, Any]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = validate_window_collect_plan(resolved_plan, expected_plan_hash)
    samples_path = Path(plan["output_contract"]["samples_path"])
    manifest_path = Path(plan["output_contract"]["manifest_path"])
    if not samples_path.is_file():
        raise FileNotFoundError(f"execution probe samples are missing: {samples_path}")
    if manifest_path.exists():
        raise FileExistsError(f"execution probe manifest already exists: {manifest_path}")
    rows = _read_jsonl(samples_path)
    metrics = _compute_window_metrics(plan, rows)
    expected_cycles = int(plan["window_contract"]["expected_cycles"])
    completed = int(completed_cycles)
    final = completed == expected_cycles
    payload: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "mode": "gate_membership_momentum_v2_execution_probe_collect",
        "run_id": plan["run_id"],
        "final": final,
        "incomplete": not final,
        "status": "READY_FOR_POSTPROCESS" if final else "STOPPED_INCOMPLETE",
        "stop_reason": "duration_complete" if final else "collector_stopped_before_frozen_cycles",
        "window_index": int(plan["window_contract"]["index"]),
        "completed_cycles": completed,
        "expected_cycles": expected_cycles,
        "runtime_sec": max(0.0, float(runtime_sec)),
        "network_access": True,
        "public_api_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "grid_search": False,
        "retune": False,
        "paper_forward_allowed": False,
        "leverage_or_margin": False,
        "window_plan_authorization": {
            "path": str(resolved_plan),
            "file_sha256": v3_history_plan.sha256_file(resolved_plan),
            "plan_hash": plan["plan_hash"],
        },
        "probe_plan_hash": plan["probe_plan_authorization"]["plan_hash"],
        "selection_hash": plan["selection_authorization"]["artifact_hash"],
        "samples": {
            "path": str(samples_path),
            "file_sha256": v3_history_plan.sha256_file(samples_path),
            "rows": len(rows),
        },
        "errors": [str(value)[:1000] for value in errors[:100]],
        "error_count": len(errors),
        "critical_errors": [str(value)[:1000] for value in critical_errors[:100]],
        "critical_error_count": len(critical_errors),
        "metrics": metrics,
        "code_provenance": plan["code_provenance"],
        "next_allowed_command": (
            "fast-edge-membership-momentum-v2-execution-probe-evaluate"
            if final
            else "create_new_hash_bound_execution_probe_window_plan"
        ),
    }
    payload["deterministic_result_hash"] = _artifact_hash(payload)
    v2_train._write_json_immutable(manifest_path, payload)
    return payload


def collect_execution_probe_window(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    max_runtime_sec: int | None = None,
    contract_fetcher: ContractFetcher | None = None,
    depth_fetcher: DepthFetcher | None = None,
    now_fn: Callable[[], float] = time.time,
    monotonic_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = validate_window_collect_plan(resolved_plan, expected_plan_hash)
    samples_path = Path(plan["output_contract"]["samples_path"])
    manifest_path = Path(plan["output_contract"]["manifest_path"])
    if samples_path.exists() or manifest_path.exists():
        raise FileExistsError("execution probe output already exists")
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    frozen_runtime = int(plan["collector_contract"]["maximum_runtime_sec"])
    runtime_limit = int(max_runtime_sec or frozen_runtime)
    if runtime_limit < MIN_RUNTIME_SEC or runtime_limit > frozen_runtime:
        raise ValueError("execution probe runtime exceeds frozen window contract")
    start_ts = float(plan["window_contract"]["start_ts"])
    end_ts = float(plan["window_contract"]["end_ts"])
    now = float(now_fn())
    if now >= end_ts:
        raise ValueError("execution probe window has already ended")
    wait_sec = max(0.0, start_ts - now)
    if wait_sec + probe.WINDOW_DURATION_SEC > runtime_limit:
        raise ValueError("MaxRuntimeSec does not cover countdown plus frozen probe window")
    if now > start_ts + probe.SAMPLE_INTERVAL_SEC:
        raise ValueError("execution probe window start was missed")
    while float(now_fn()) < start_ts:
        remaining = max(0.0, start_ts - float(now_fn()))
        print(
            f"PROBE_COUNTDOWN window={plan['window_contract']['index']} remaining_sec={remaining:.1f}",
            flush=True,
        )
        sleep_fn(min(10.0, remaining))

    funding_client: GateFundingClient | None = None
    rest_client: GatePerpRestClient | None = None
    if contract_fetcher is None:
        funding_client = GateFundingClient(timeout_sec=10)
        contract_fetcher = funding_client.fetch_contracts
    if depth_fetcher is None:
        rest_client = GatePerpRestClient(timeout_sec=10)
        depth_fetcher = rest_client.fetch_depth
    assert contract_fetcher is not None and depth_fetcher is not None
    contracts = list(contract_fetcher())
    contracts_by_symbol = {
        item.symbol: item
        for item in contracts
        if isinstance(item, FundingContract)
        and item.exchange == "gateio"
        and str(item.status).lower() == "trading"
    }
    selected_contracts: dict[str, FundingContract | None] = {}
    critical_errors: list[str] = []
    errors: list[str] = []
    for position in plan["selected_positions"]:
        symbol = str(position["symbol"])
        current = contracts_by_symbol.get(symbol)
        if current is None or current.base.upper() != position["base"] or current.quote.upper() != "USDT":
            selected_contracts[symbol] = None
            critical_errors.append(f"contract_identity_unavailable:{symbol}")
        else:
            selected_contracts[symbol] = current

    expected_cycles = int(plan["window_contract"]["expected_cycles"])
    interval = float(plan["window_contract"]["interval_sec"])
    depth_limit = int(plan["collector_contract"]["depth_limit"])
    workers = int(plan["collector_contract"]["maximum_workers"])
    completed_cycles = 0
    started_monotonic = float(monotonic_fn())
    try:
        with samples_path.open("x", encoding="utf-8", buffering=1) as handle, ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="gate-momentum-v2-depth",
        ) as pool:
            for cycle in range(1, expected_cycles + 1):
                target_ts = start_ts + (cycle - 1) * interval
                now = float(now_fn())
                if now < target_ts:
                    sleep_fn(target_ts - now)
                completed_cycles = cycle
                futures: dict[Any, tuple[dict[str, Any], float]] = {}
                rows_by_identity: dict[str, dict[str, Any]] = {}
                for position in plan["selected_positions"]:
                    identity = str(position["canonical_asset_id"])
                    symbol = str(position["symbol"])
                    current = selected_contracts.get(symbol)
                    request_started = float(now_fn())
                    if current is None:
                        rows_by_identity[identity] = {
                            "schema": SAMPLE_SCHEMA,
                            "window_plan_hash": plan["plan_hash"],
                            "selection_hash": plan["selection_authorization"]["artifact_hash"],
                            "window_index": int(plan["window_contract"]["index"]),
                            "cycle": cycle,
                            "scheduled_ts": target_ts,
                            **position,
                            "request_started_ts": request_started,
                            "received_ts": request_started,
                            "exchange_ts": None,
                            "timestamp_skew_ms": None,
                            "bids": [],
                            "asks": [],
                            "collection_error": "contract_identity_unavailable",
                        }
                        continue
                    futures[pool.submit(depth_fetcher, current, depth_limit)] = (
                        position,
                        request_started,
                    )
                successful_exchange_times: list[float] = []
                for future in as_completed(futures):
                    position, request_started = futures[future]
                    identity = str(position["canonical_asset_id"])
                    received = float(now_fn())
                    try:
                        current = selected_contracts[str(position["symbol"])]
                        assert current is not None
                        bids, asks, exchange_ts = _normalize_gate_book(current, future.result())
                        successful_exchange_times.append(exchange_ts)
                        collection_error = None
                    except (KeyError, TypeError, ValueError) as exc:
                        message = f"cycle={cycle}:asset={identity}:schema:{type(exc).__name__}:{exc}"
                        critical_errors.append(message)
                        bids, asks, exchange_ts = [], [], None
                        collection_error = message
                    except Exception as exc:  # Public request failures become coverage evidence.
                        message = f"cycle={cycle}:asset={identity}:network:{type(exc).__name__}:{exc}"
                        if len(errors) < 100:
                            errors.append(message)
                        bids, asks, exchange_ts = [], [], None
                        collection_error = message
                    rows_by_identity[identity] = {
                        "schema": SAMPLE_SCHEMA,
                        "window_plan_hash": plan["plan_hash"],
                        "selection_hash": plan["selection_authorization"]["artifact_hash"],
                        "window_index": int(plan["window_contract"]["index"]),
                        "cycle": cycle,
                        "scheduled_ts": target_ts,
                        **position,
                        "request_started_ts": request_started,
                        "received_ts": received,
                        "exchange_ts": exchange_ts,
                        "timestamp_skew_ms": None,
                        "bids": bids,
                        "asks": asks,
                        "collection_error": collection_error,
                    }
                cycle_skew_ms = (
                    (max(successful_exchange_times) - min(successful_exchange_times)) * 1000.0
                    if len(successful_exchange_times) >= 2
                    else None
                )
                for position in plan["selected_positions"]:
                    row = rows_by_identity[str(position["canonical_asset_id"])]
                    row["timestamp_skew_ms"] = cycle_skew_ms
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                elapsed = max(0.0, float(monotonic_fn()) - started_monotonic)
                eta = max(0, expected_cycles - cycle) * interval
                print(
                    f"PROBE window={plan['window_contract']['index']} cycle={cycle}/{expected_cycles} "
                    f"assets={len(rows_by_identity)} errors={len(errors)} "
                    f"critical={len(critical_errors)} elapsed_sec={elapsed:.1f} eta_sec={eta:.0f}",
                    flush=True,
                )
        return finalize_execution_probe_window(
            plan_path=resolved_plan,
            expected_plan_hash=plan["plan_hash"],
            completed_cycles=completed_cycles,
            errors=errors,
            critical_errors=critical_errors,
            runtime_sec=max(0.0, float(monotonic_fn()) - started_monotonic),
        )
    except Exception as exc:
        if samples_path.is_file() and not manifest_path.exists():
            try:
                finalize_execution_probe_window(
                    plan_path=resolved_plan,
                    expected_plan_hash=plan["plan_hash"],
                    completed_cycles=completed_cycles,
                    errors=[*errors, f"collector:{type(exc).__name__}:{exc}"],
                    critical_errors=critical_errors,
                    runtime_sec=max(0.0, float(monotonic_fn()) - started_monotonic),
                )
            except Exception:
                pass
        raise


def _validate_manifest(
    path: str | Path,
    *,
    expected_probe_hash: str,
    expected_selection_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    resolved = Path(path).expanduser().resolve()
    manifest = v2_train._read_json_object(resolved)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("final") is not True:
        raise ValueError("execution probe manifest is not final")
    if manifest.get("deterministic_result_hash") != _artifact_hash(manifest):
        raise ValueError("execution probe manifest hash mismatch")
    authorization = manifest.get("window_plan_authorization")
    samples = manifest.get("samples")
    if not isinstance(authorization, Mapping) or not isinstance(samples, Mapping):
        raise ValueError("execution probe manifest provenance is missing")
    plan_path = Path(str(authorization.get("path") or "")).expanduser().resolve()
    plan = validate_window_collect_plan(plan_path, str(authorization.get("plan_hash") or ""))
    if (
        authorization.get("file_sha256") != v3_history_plan.sha256_file(plan_path)
        or manifest.get("probe_plan_hash") != expected_probe_hash
        or manifest.get("selection_hash") != expected_selection_hash
        or plan["probe_plan_authorization"]["plan_hash"] != expected_probe_hash
        or plan["selection_authorization"]["artifact_hash"] != expected_selection_hash
    ):
        raise ValueError("execution probe manifest belongs to another frozen selection")
    sample_path = Path(str(samples.get("path") or "")).expanduser().resolve()
    if not sample_path.is_file() or samples.get("file_sha256") != v3_history_plan.sha256_file(sample_path):
        raise ValueError("execution probe raw sample hash mismatch")
    rows = _read_jsonl(sample_path)
    recomputed = _compute_window_metrics(plan, rows)
    if recomputed != manifest.get("metrics"):
        raise ValueError("execution probe manifest metrics do not match raw depth samples")
    if (
        int(manifest.get("completed_cycles") or 0) != int(plan["window_contract"]["expected_cycles"])
        or manifest.get("stop_reason") != "duration_complete"
    ):
        raise ValueError("execution probe manifest did not complete frozen cycles")
    return manifest, recomputed, resolved


def evaluate_execution_probe_windows(
    *,
    probe_plan_path: str | Path,
    expected_probe_plan_hash: str,
    selection_path: str | Path,
    expected_selection_hash: str,
    manifest_paths: Iterable[str | Path],
    output_path: str | Path,
) -> dict[str, Any]:
    probe_plan, resolved_probe, selected, resolved_selection = _validate_probe_and_selection(
        probe_plan_path=probe_plan_path,
        expected_probe_plan_hash=expected_probe_plan_hash,
        selection_path=selection_path,
        expected_selection_hash=expected_selection_hash,
    )
    paths = [Path(path).expanduser().resolve() for path in manifest_paths]
    if len(paths) != probe.WINDOW_COUNT or len(set(paths)) != probe.WINDOW_COUNT:
        raise ValueError("exactly three distinct execution probe manifests are required")
    validated = [
        _validate_manifest(
            path,
            expected_probe_hash=probe_plan["plan_hash"],
            expected_selection_hash=selected["artifact_hash"],
        )
        for path in paths
    ]
    by_index: dict[int, tuple[dict[str, Any], dict[str, Any], Path]] = {}
    for item in validated:
        index = int(item[0]["window_index"])
        if index in by_index:
            raise ValueError("duplicate execution probe window index")
        by_index[index] = item
    if sorted(by_index) != list(range(probe.WINDOW_COUNT)):
        raise ValueError("execution probe manifests do not cover all frozen windows")
    selected_assets = sorted(
        str(row["canonical_asset_id"]) for row in selected["selected_positions"]
    )
    eligible_sets = [set(by_index[index][1]["eligible_assets"]) for index in range(probe.WINDOW_COUNT)]
    execution_eligible = sorted(set.intersection(*eligible_sets)) if eligible_sets else []
    critical_errors = sum(
        int(by_index[index][0].get("critical_error_count") or 0)
        for index in range(probe.WINDOW_COUNT)
    )
    rejection_reasons: list[str] = []
    if critical_errors > int(
        probe_plan["execution_contract"]["critical_schema_reconnect_or_stale_quote_errors_allowed"]
    ):
        rejection_reasons.append("critical_execution_probe_errors")
    if execution_eligible != selected_assets:
        rejection_reasons.append("selected_asset_failed_one_or_more_windows")
    verdict = PAPER_FORWARD_READY_DECISION if not rejection_reasons else REJECT_DECISION
    contract: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "final": True,
        "hypothesis_id": probe_plan["hypothesis_id"],
        "verdict": verdict,
        "historical_oos_decision": v2_oos.HISTORICAL_ACCEPT_DECISION,
        "probe_plan": {
            "path": str(resolved_probe),
            "file_sha256": v3_history_plan.sha256_file(resolved_probe),
            "plan_hash": probe_plan["plan_hash"],
        },
        "selection": {
            "path": str(resolved_selection),
            "file_sha256": v3_history_plan.sha256_file(resolved_selection),
            "artifact_hash": selected["artifact_hash"],
        },
        "selected_assets": selected_assets,
        "execution_eligible_assets": execution_eligible,
        "all_selected_assets_eligible": execution_eligible == selected_assets,
        "critical_error_count": critical_errors,
        "rejection_reasons": rejection_reasons,
        "windows": [
            {
                "index": index,
                "manifest_path": str(by_index[index][2]),
                "manifest_file_sha256": v3_history_plan.sha256_file(by_index[index][2]),
                "manifest_result_hash": by_index[index][0]["deterministic_result_hash"],
                "metrics": by_index[index][1],
            }
            for index in range(probe.WINDOW_COUNT)
        ],
        "research_only": True,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "maximum_authority": (
            "PAPER_FORWARD_PLANONLY" if verdict == PAPER_FORWARD_READY_DECISION else "BRANCH_CLOSED"
        ),
        "next_allowed_command": (
            "fast-edge-membership-momentum-v2-paper-plan"
            if verdict == PAPER_FORWARD_READY_DECISION
            else "none_membership_momentum_v2_branch_closed_no_retune"
        ),
    }
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "probe_plan_hash": probe_plan["plan_hash"],
            "selection_hash": selected["artifact_hash"],
            "window_result_hashes": [
                by_index[index][0]["deterministic_result_hash"]
                for index in range(probe.WINDOW_COUNT)
            ],
        }
    )
    contract["deterministic_result_hash"] = _artifact_hash(contract)
    v2_train._write_json_immutable(output_path, contract)
    return contract


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate membership-momentum-v2 execution-capacity probe"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    window_plan = subparsers.add_parser("plan-window")
    window_plan.add_argument("--probe-plan", required=True)
    window_plan.add_argument("--expected-probe-plan-hash", required=True)
    window_plan.add_argument("--selection", required=True)
    window_plan.add_argument("--expected-selection-hash", required=True)
    window_plan.add_argument("--output", required=True)
    window_plan.add_argument("--samples", required=True)
    window_plan.add_argument("--manifest", required=True)
    window_plan.add_argument("--run-id", required=True)
    window_plan.add_argument("--window-index", type=int, choices=(0, 1, 2), required=True)
    window_plan.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    window_plan.add_argument("--workers", type=int, default=4)
    paper_window = subparsers.add_parser("plan-paper-window")
    paper_window.add_argument("--paper-plan", required=True)
    paper_window.add_argument("--expected-paper-plan-hash", required=True)
    paper_window.add_argument("--approval", required=True)
    paper_window.add_argument("--selection", required=True)
    paper_window.add_argument("--expected-selection-hash", required=True)
    paper_window.add_argument("--boundary", choices=("entry", "exit"), required=True)
    paper_window.add_argument("--output", required=True)
    paper_window.add_argument("--samples", required=True)
    paper_window.add_argument("--manifest", required=True)
    paper_window.add_argument("--run-id", required=True)
    paper_window.add_argument("--window-index", type=int, choices=(0, 1, 2), required=True)
    paper_window.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    paper_window.add_argument("--workers", type=int, default=4)
    validate = subparsers.add_parser("validate-plan")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash")
    collect = subparsers.add_parser("collect")
    collect.add_argument("--plan", required=True)
    collect.add_argument("--expected-plan-hash", required=True)
    collect.add_argument("--max-runtime-sec", type=int)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--probe-plan", required=True)
    evaluate.add_argument("--expected-probe-plan-hash", required=True)
    evaluate.add_argument("--selection", required=True)
    evaluate.add_argument("--expected-selection-hash", required=True)
    evaluate.add_argument("--manifests", required=True)
    evaluate.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan-window":
        result = build_window_collect_plan(
            probe_plan_path=args.probe_plan,
            expected_probe_plan_hash=args.expected_probe_plan_hash,
            selection_path=args.selection,
            expected_selection_hash=args.expected_selection_hash,
            output_path=args.output,
            samples_path=args.samples,
            manifest_path=args.manifest,
            run_id=args.run_id,
            window_index=args.window_index,
            max_runtime_sec=args.max_runtime_sec,
            workers=args.workers,
        )
    elif args.command == "plan-paper-window":
        result = build_paper_boundary_window_collect_plan(
            paper_plan_path=args.paper_plan,
            expected_paper_plan_hash=args.expected_paper_plan_hash,
            approval_path=args.approval,
            selection_path=args.selection,
            expected_selection_hash=args.expected_selection_hash,
            boundary=args.boundary,
            output_path=args.output,
            samples_path=args.samples,
            manifest_path=args.manifest,
            run_id=args.run_id,
            window_index=args.window_index,
            max_runtime_sec=args.max_runtime_sec,
            workers=args.workers,
        )
    elif args.command == "validate-plan":
        plan = validate_window_collect_plan(args.plan, args.expected_plan_hash)
        result = {
            "schema": "trading_mvp_gate_membership_momentum_v2_execution_probe_window_validation_v1",
            "valid": True,
            "plan_hash": plan["plan_hash"],
            "run_id": plan["run_id"],
            "window_index": int(plan["window_contract"]["index"]),
            "decision": plan["decision"],
            "approval_phrase": plan["approval_phrase"],
        }
    elif args.command == "collect":
        result = collect_execution_probe_window(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = evaluate_execution_probe_windows(
            probe_plan_path=args.probe_plan,
            expected_probe_plan_hash=args.expected_probe_plan_hash,
            selection_path=args.selection,
            expected_selection_hash=args.expected_selection_hash,
            manifest_paths=[value.strip() for value in args.manifests.split(",") if value.strip()],
            output_path=args.output,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
