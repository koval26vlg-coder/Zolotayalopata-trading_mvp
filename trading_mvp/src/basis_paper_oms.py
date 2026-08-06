from __future__ import annotations

import argparse
import json
import math
import os
import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from historical_basis_edge import (
    HYPOTHESIS_ID,
    sha256_file,
    sha256_json,
    validate_historical_basis_plan,
)
from historical_basis_evaluator import SCHEMA as EVALUATION_SCHEMA


STATE_SCHEMA = "trading_mvp_basis_paper_oms_state_v1"
LEDGER_EVENT_SCHEMA = "trading_mvp_basis_paper_oms_event_v1"
REPORT_SCHEMA = "trading_mvp_historical_basis_sprint_report_v1"
MANUAL_PNL_FIELDS = {
    "pnl",
    "pnl_quote",
    "net_pnl",
    "net_pnl_quote",
    "price_pnl_quote",
    "funding_pnl_quote",
    "cost_quote",
    "fees_quote",
    "profit",
}


ReadyChainValidator = Callable[
    [str | Path, str | Path],
    tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
]
ExecutionGuard = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    dict[str, Any],
]


@dataclass(frozen=True)
class BasisPaperOmsContract:
    state_schema: str
    ledger_event_schema: str
    hypothesis_id: str
    ready_chain_validator: ReadyChainValidator
    execution_guard: ExecutionGuard | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _semantic_hash(payload: dict[str, Any]) -> str:
    ignored = {"generated_at_utc", "deterministic_result_hash", "runtime_sec", "cache_hit"}
    return sha256_json({key: value for key, value in payload.items() if key not in ignored})


def _state_hash(payload: dict[str, Any]) -> str:
    ignored = {"updated_at_utc", "deterministic_state_hash"}
    return sha256_json({key: value for key, value in payload.items() if key not in ignored})


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def paper_oms_single_writer_lock(
    *,
    ledger_path: str | Path,
    state_path: str | Path,
    operation: str,
) -> Iterator[dict[str, Any]]:
    ledger_target = Path(ledger_path).expanduser().resolve()
    state_target = Path(state_path).expanduser().resolve()
    lock_path = state_target.with_suffix(f"{state_target.suffix}.writer.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    payload = {
        "schema": "trading_mvp_basis_paper_oms_writer_lock_v1",
        "token": token,
        "pid": os.getpid(),
        "operation": str(operation),
        "acquired_at_utc": _utc_now(),
        "ledger_path": str(ledger_target),
        "state_path": str(state_target),
    }
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as exc:
        try:
            owner = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            owner = {"status": "unreadable_lock_owner"}
        raise RuntimeError(
            f"paper OMS writer lock is already held: {lock_path}; owner={owner}"
        ) from exc

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        lock_path.unlink(missing_ok=True)
        raise

    try:
        yield {**payload, "lock_path": str(lock_path)}
    finally:
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"paper OMS writer lock ownership cannot be verified: {lock_path}"
            ) from exc
        if current.get("token") != token:
            raise RuntimeError(
                f"paper OMS writer lock ownership changed unexpectedly: {lock_path}"
            )
        lock_path.unlink()


def _single_writer_operation(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
        ledger_path = kwargs.get("ledger_path")
        state_path = kwargs.get("state_path")
        if ledger_path is None or state_path is None:
            raise TypeError("ledger_path and state_path are required for paper OMS mutation")
        with paper_oms_single_writer_lock(
            ledger_path=ledger_path,
            state_path=state_path,
            operation=function.__name__,
        ):
            return function(*args, **kwargs)

    return guarded


def _persist_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at_utc"] = _utc_now()
    state["deterministic_state_hash"] = _state_hash(state)
    _atomic_write_json(path, state)


def _validate_semantic_artifact(payload: dict[str, Any], *, schema: str, label: str) -> None:
    if payload.get("schema") != schema:
        raise ValueError(f"unexpected {label} schema")
    if payload.get("deterministic_result_hash") != _semantic_hash(payload):
        raise ValueError(f"{label} semantic hash mismatch")


def _validate_ready_chain(
    plan_path: str | Path,
    report_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_validation = validate_historical_basis_plan(plan_path)
    plan = _read_json(plan_path)
    report_target = Path(report_path).expanduser().resolve()
    report = _read_json(report_target)
    _validate_semantic_artifact(report, schema=REPORT_SCHEMA, label="sprint report")
    if report.get("verdict") != "PAPER_FORWARD_READY":
        raise ValueError("paper OMS requires PAPER_FORWARD_READY")
    safety = report.get("safety") or {}
    for key in ("live_orders", "api_keys", "leverage"):
        if safety.get(key) is not False:
            raise ValueError(f"unsafe sprint report flag: {key}")
    evaluation_ref = report.get("historical_evaluation") or {}
    evaluation_path = Path(str(evaluation_ref.get("path") or "")).expanduser().resolve()
    if not evaluation_path.is_file() or sha256_file(evaluation_path) != evaluation_ref.get("file_sha256"):
        raise ValueError("historical evaluation provenance mismatch")
    evaluation = _read_json(evaluation_path)
    _validate_semantic_artifact(evaluation, schema=EVALUATION_SCHEMA, label="historical evaluation")
    if evaluation.get("deterministic_result_hash") != evaluation_ref.get("semantic_hash"):
        raise ValueError("historical evaluation semantic reference mismatch")
    if evaluation.get("plan_hash") != plan_validation["plan_hash"]:
        raise ValueError("paper report belongs to another plan")
    if evaluation.get("verdict") != "ACCEPT_FOR_EXECUTION_PROBE":
        raise ValueError("historical evaluation was not accepted")
    return plan, report, {
        **plan_validation,
        "report_path": str(report_target),
        "report_file_sha256": sha256_file(report_target),
        "report_semantic_hash": report["deterministic_result_hash"],
    }


def _v1_contract() -> BasisPaperOmsContract:
    return BasisPaperOmsContract(
        state_schema=STATE_SCHEMA,
        ledger_event_schema=LEDGER_EVENT_SCHEMA,
        hypothesis_id=HYPOTHESIS_ID,
        ready_chain_validator=_validate_ready_chain,
    )


def _event_without_hash(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "event_hash"}


def _read_ledger_events(
    path: str | Path,
    *,
    contract: BasisPaperOmsContract | None = None,
) -> list[dict[str, Any]]:
    resolved_contract = contract or _v1_contract()
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"paper ledger is missing: {target}")
    events: list[dict[str, Any]] = []
    previous_hash = "GENESIS"
    for line_number, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        event = json.loads(raw)
        if not isinstance(event, dict) or event.get("schema") != resolved_contract.ledger_event_schema:
            raise ValueError(f"paper ledger schema mismatch at line {line_number}")
        if int(event.get("sequence") or 0) != len(events) + 1:
            raise ValueError(f"paper ledger sequence mismatch at line {line_number}")
        if event.get("previous_event_hash") != previous_hash:
            raise ValueError(f"paper ledger previous hash mismatch at line {line_number}")
        expected_hash = sha256_json(_event_without_hash(event))
        if event.get("event_hash") != expected_hash:
            raise ValueError(f"paper ledger event hash mismatch at line {line_number}")
        previous_hash = expected_hash
        events.append(event)
    if not events:
        raise ValueError("paper ledger is empty")
    return events


def verify_basis_paper_ledger(
    path: str | Path,
    *,
    contract: BasisPaperOmsContract | None = None,
) -> dict[str, Any]:
    events = _read_ledger_events(path, contract=contract)
    return {
        "event_count": len(events),
        "last_sequence": events[-1]["sequence"],
        "last_event_hash": events[-1]["event_hash"],
        "plan_hash": events[0]["plan_hash"],
        "report_hash": events[0]["report_hash"],
        "valid": True,
    }


def _projection(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": state["status"],
        "positions": deepcopy(state["positions"]),
        "realized_net_pnl_quote": float(state["realized_net_pnl_quote"]),
        "daily_realized_date": state.get("daily_realized_date"),
        "daily_realized_net_pnl_quote": float(state["daily_realized_net_pnl_quote"]),
        "last_observation_ts": state.get("last_observation_ts"),
        "kill_switch_reason": state.get("kill_switch_reason"),
        "blocked_execution_count": int(state.get("blocked_execution_count") or 0),
        "executed_transition_count": int(state.get("executed_transition_count") or 0),
        "last_execution_block_reason": state.get("last_execution_block_reason"),
    }


def _append_event(
    ledger_path: Path,
    state_path: Path,
    state: dict[str, Any],
    *,
    event_type: str,
    event_ts: int,
    details: dict[str, Any],
    contract: BasisPaperOmsContract | None = None,
) -> None:
    resolved_contract = contract or _v1_contract()
    sequence = int(state["last_ledger_sequence"]) + 1
    event = {
        "schema": resolved_contract.ledger_event_schema,
        "sequence": sequence,
        "event_type": event_type,
        "event_ts": int(event_ts),
        "plan_hash": state["plan_hash"],
        "report_hash": state["report_semantic_hash"],
        "previous_event_hash": state["last_event_hash"],
        "details": {**details, "state_after": _projection(state)},
    }
    event["event_hash"] = sha256_json(_event_without_hash(event))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    state["last_ledger_sequence"] = sequence
    state["last_event_hash"] = event["event_hash"]
    _persist_state(state_path, state)


def _load_state(
    path: Path,
    *,
    contract: BasisPaperOmsContract | None = None,
) -> dict[str, Any]:
    resolved_contract = contract or _v1_contract()
    state = _read_json(path)
    if state.get("schema") != resolved_contract.state_schema:
        raise ValueError("paper state schema mismatch")
    if state.get("deterministic_state_hash") != _state_hash(state):
        raise ValueError("paper state hash mismatch")
    return state


def _recover_or_validate_state(
    state_path: Path,
    ledger_path: Path,
    *,
    contract: BasisPaperOmsContract | None = None,
) -> dict[str, Any]:
    resolved_contract = contract or _v1_contract()
    state = _load_state(state_path, contract=resolved_contract)
    events = _read_ledger_events(ledger_path, contract=resolved_contract)
    last = events[-1]
    if int(state.get("last_ledger_sequence") or 0) == int(last["sequence"]):
        if state.get("last_event_hash") != last["event_hash"]:
            raise ValueError("paper state and ledger last hash mismatch")
        return state
    if int(state.get("last_ledger_sequence") or 0) > int(last["sequence"]):
        raise ValueError("paper state is ahead of append-only ledger")
    recovered = (last.get("details") or {}).get("state_after")
    if not isinstance(recovered, dict):
        raise ValueError("paper ledger cannot recover stale state")
    for key, value in recovered.items():
        state[key] = deepcopy(value)
    state["last_ledger_sequence"] = int(last["sequence"])
    state["last_event_hash"] = last["event_hash"]
    _persist_state(state_path, state)
    return state


@_single_writer_operation
def initialize_basis_paper_oms(
    plan_path: str | Path,
    report_path: str | Path,
    *,
    ledger_path: str | Path,
    state_path: str | Path,
    daily_loss_limit_quote: float = 50.0,
    contract: BasisPaperOmsContract | None = None,
) -> dict[str, Any]:
    resolved_contract = contract or _v1_contract()
    if daily_loss_limit_quote <= 0:
        raise ValueError("daily_loss_limit_quote must be positive")
    ledger_target = Path(ledger_path).expanduser().resolve()
    state_target = Path(state_path).expanduser().resolve()
    if ledger_target.exists() or state_target.exists():
        raise FileExistsError("paper OMS artifacts already exist")
    plan, _report, provenance = resolved_contract.ready_chain_validator(plan_path, report_path)
    state: dict[str, Any] = {
        "schema": resolved_contract.state_schema,
        "hypothesis_id": resolved_contract.hypothesis_id,
        "plan_path": provenance["plan_path"],
        "plan_file_sha256": provenance["plan_file_sha256"],
        "plan_hash": provenance["plan_hash"],
        "report_path": provenance["report_path"],
        "report_file_sha256": provenance["report_file_sha256"],
        "report_semantic_hash": provenance["report_semantic_hash"],
        "status": "FLAT",
        "positions": {},
        "realized_net_pnl_quote": 0.0,
        "daily_realized_date": None,
        "daily_realized_net_pnl_quote": 0.0,
        "daily_loss_limit_quote": float(daily_loss_limit_quote),
        "last_observation_ts": None,
        "kill_switch_reason": None,
        "blocked_execution_count": 0,
        "executed_transition_count": 0,
        "last_execution_block_reason": None,
        "last_ledger_sequence": 0,
        "last_event_hash": "GENESIS",
        "safety": {
            "paper_only": True,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
        },
        "cost_cycle_bps": float(plan["economics"]["normal_cycle_cost"]["total_bps"]),
    }
    _append_event(
        ledger_target,
        state_target,
        state,
        event_type="INITIALIZED",
        event_ts=0,
        details={"daily_loss_limit_quote": float(daily_loss_limit_quote)},
        contract=resolved_contract,
    )
    return deepcopy(state)


def _normalize_observation(raw: dict[str, Any]) -> dict[str, Any]:
    if MANUAL_PNL_FIELDS.intersection(raw):
        raise ValueError("manual PnL fields are forbidden")
    required = (
        "ts",
        "base",
        "mexc_trade_price",
        "gateio_trade_price",
        "mexc_mark_price",
        "mexc_index_price",
        "gateio_mark_price",
        "gateio_index_price",
        "data_quality_ok",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"paper observation missing fields: {','.join(missing)}")
    observation = dict(raw)
    observation["ts"] = int(observation["ts"])
    observation["base"] = str(observation["base"]).strip().upper()
    for key in (
        "mexc_trade_price",
        "gateio_trade_price",
        "mexc_mark_price",
        "mexc_index_price",
        "gateio_mark_price",
        "gateio_index_price",
    ):
        observation[key] = float(observation[key])
        if not math.isfinite(observation[key]) or observation[key] <= 0:
            raise ValueError(f"paper observation {key} must be finite and positive")
    for key in ("mexc_funding_rate", "gateio_funding_rate"):
        if observation.get(key) is not None:
            observation[key] = float(observation[key])
            if not math.isfinite(observation[key]):
                raise ValueError(f"paper observation {key} must be finite")
    observation["data_quality_ok"] = bool(observation["data_quality_ok"])
    return observation


def _basis_snapshot(observation: dict[str, Any]) -> tuple[float, float, float, str, str]:
    mexc = (observation["mexc_mark_price"] - observation["mexc_index_price"]) / observation[
        "mexc_index_price"
    ] * 10_000.0
    gateio = (observation["gateio_mark_price"] - observation["gateio_index_price"]) / observation[
        "gateio_index_price"
    ] * 10_000.0
    if mexc <= gateio:
        return mexc, gateio, gateio - mexc, "mexc", "gateio"
    return mexc, gateio, mexc - gateio, "gateio", "mexc"


def _venue_price(observation: dict[str, Any], venue: str) -> float:
    return float(observation[f"{venue}_trade_price"])


def _funding_pnl(position: dict[str, Any], observation: dict[str, Any], notional: float) -> float:
    long_rate = observation.get(f"{position['long_venue']}_funding_rate")
    short_rate = observation.get(f"{position['short_venue']}_funding_rate")
    if long_rate is None or short_rate is None:
        raise ValueError("funding settlement requires both venue rates")
    return -notional * float(long_rate) + notional * float(short_rate)


def _position_price_pnl(position: dict[str, Any], observation: dict[str, Any], notional: float) -> float:
    long_exit = _venue_price(observation, position["long_venue"])
    short_exit = _venue_price(observation, position["short_venue"])
    long_qty = notional / float(position["long_entry_price"])
    short_qty = notional / float(position["short_entry_price"])
    return (long_exit - float(position["long_entry_price"])) * long_qty + (
        float(position["short_entry_price"]) - short_exit
    ) * short_qty


def _guard_position_transition(
    plan: dict[str, Any],
    state: dict[str, Any],
    row: dict[str, Any],
    transition: dict[str, Any],
    *,
    ledger_path: Path,
    state_path: Path,
    contract: BasisPaperOmsContract,
) -> tuple[bool, dict[str, Any], dict[str, Any] | None]:
    if contract.execution_guard is None:
        state["executed_transition_count"] = int(state.get("executed_transition_count") or 0) + 1
        state["last_execution_block_reason"] = None
        return True, row, None
    result = contract.execution_guard(plan, state, row, transition)
    if not isinstance(result, dict) or not isinstance(result.get("allowed"), bool):
        raise ValueError("paper execution guard returned an invalid decision")
    if not result["allowed"]:
        reason = str(result.get("reason") or "execution_guard_rejected")
        state["blocked_execution_count"] = int(state.get("blocked_execution_count") or 0) + 1
        state["last_execution_block_reason"] = reason
        _append_event(
            ledger_path,
            state_path,
            state,
            event_type="EXECUTION_BLOCKED",
            event_ts=int(row["ts"]),
            details={"transition": transition, "execution_guard": result},
            contract=contract,
        )
        return False, row, result
    prices = result.get("trade_prices")
    if not isinstance(prices, Mapping):
        raise ValueError("paper execution guard allowed a transition without trade prices")
    guarded_row = deepcopy(row)
    for venue in ("mexc", "gateio"):
        try:
            price = float(prices[venue])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"paper execution guard missing {venue} trade price") from exc
        if not math.isfinite(price) or price <= 0.0:
            raise ValueError(f"paper execution guard {venue} trade price must be finite and positive")
        guarded_row[f"{venue}_trade_price"] = price
    state["executed_transition_count"] = int(state.get("executed_transition_count") or 0) + 1
    state["last_execution_block_reason"] = None
    return True, guarded_row, result


@_single_writer_operation
def apply_basis_paper_observation(
    plan_path: str | Path,
    report_path: str | Path,
    *,
    ledger_path: str | Path,
    state_path: str | Path,
    observation: dict[str, Any],
    contract: BasisPaperOmsContract | None = None,
) -> dict[str, Any]:
    resolved_contract = contract or _v1_contract()
    plan, _report, provenance = resolved_contract.ready_chain_validator(plan_path, report_path)
    ledger_target = Path(ledger_path).expanduser().resolve()
    state_target = Path(state_path).expanduser().resolve()
    state = _recover_or_validate_state(
        state_target,
        ledger_target,
        contract=resolved_contract,
    )
    if state["plan_hash"] != provenance["plan_hash"] or state["report_semantic_hash"] != provenance[
        "report_semantic_hash"
    ]:
        raise ValueError("paper OMS provenance mismatch")
    if state["status"] == "HALTED":
        raise ValueError("paper OMS kill switch is active")
    row = _normalize_observation(observation)
    allowed_bases = {str(item["base"]) for item in plan["universe"]["candidates"]}
    if row["base"] not in allowed_bases:
        raise ValueError("paper observation base is outside frozen universe")
    prior_ts = state.get("last_observation_ts")
    if prior_ts is not None and row["ts"] <= int(prior_ts):
        raise ValueError("paper observations must be strictly chronological")
    state["last_observation_ts"] = row["ts"]
    if not row["data_quality_ok"]:
        state["status"] = "HALTED"
        state["kill_switch_reason"] = "data_quality_failure"
        _append_event(
            ledger_target,
            state_target,
            state,
            event_type="KILL_SWITCH",
            event_ts=row["ts"],
            details={"reason": state["kill_switch_reason"], "observation": row},
            contract=resolved_contract,
        )
        return deepcopy(state)

    mexc_basis, gate_basis, spread, lower_venue, higher_venue = _basis_snapshot(row)
    position = state["positions"].get(row["base"])
    settlement_id = row.get("funding_settlement_id")
    if position is not None and settlement_id is not None:
        settlement_id = str(settlement_id).strip()
        if not settlement_id:
            raise ValueError("funding_settlement_id must not be blank")
        if settlement_id in position["funding_settlement_ids"]:
            raise ValueError("duplicate funding settlement")
        if row.get("mexc_funding_rate") is None or row.get("gateio_funding_rate") is None:
            raise ValueError("funding settlement requires both venue rates")
    snapshot = {
        "observation": row,
        "mexc_basis_bps": mexc_basis,
        "gateio_basis_bps": gate_basis,
        "basis_spread_bps": spread,
    }
    _append_event(
        ledger_target,
        state_target,
        state,
        event_type="OBSERVATION_RECORDED",
        event_ts=row["ts"],
        details=snapshot,
        contract=resolved_contract,
    )

    strategy = plan["strategy"]
    notional = float(plan["economics"]["notional_quote_per_leg"])
    if position is None:
        if spread >= float(strategy["entry_threshold_bps"]):
            transition = {
                "action": "open",
                "base": row["base"],
                "long_venue": lower_venue,
                "short_venue": higher_venue,
                "notional_quote_per_leg": notional,
            }
            allowed, row, execution_decision = _guard_position_transition(
                plan,
                state,
                row,
                transition,
                ledger_path=ledger_target,
                state_path=state_target,
                contract=resolved_contract,
            )
            if not allowed:
                return deepcopy(state)
            position_id = sha256_json(
                {"plan_hash": state["plan_hash"], "base": row["base"], "entry_ts": row["ts"]}
            )[:24]
            position = {
                "position_id": position_id,
                "base": row["base"],
                "entry_ts": row["ts"],
                "long_venue": lower_venue,
                "short_venue": higher_venue,
                "long_entry_price": _venue_price(row, lower_venue),
                "short_entry_price": _venue_price(row, higher_venue),
                "entry_basis_spread_bps": spread,
                "funding_pnl_quote": 0.0,
                "funding_settlement_ids": [],
                "entry_execution": deepcopy(execution_decision),
            }
            state["positions"][row["base"]] = position
            state["status"] = "OPEN"
            _append_event(
                ledger_target,
                state_target,
                state,
                event_type="POSITION_OPENED",
                event_ts=row["ts"],
                details={"position": deepcopy(position)},
                contract=resolved_contract,
            )
        return deepcopy(state)

    if settlement_id is not None:
        event_funding = _funding_pnl(position, row, notional)
        position["funding_pnl_quote"] += event_funding
        position["funding_settlement_ids"].append(settlement_id)
        _append_event(
            ledger_target,
            state_target,
            state,
            event_type="FUNDING_SETTLED",
            event_ts=row["ts"],
            details={
                "position_id": position["position_id"],
                "settlement_id": settlement_id,
                "event_funding_pnl_quote": event_funding,
            },
            contract=resolved_contract,
        )

    holding_sec = row["ts"] - int(position["entry_ts"])
    exit_reason = None
    if spread <= float(strategy["exit_threshold_bps"]):
        exit_reason = "convergence"
    elif holding_sec >= int(strategy["maximum_holding_hours"]) * 3600:
        exit_reason = "max_hold"
    if exit_reason is None:
        return deepcopy(state)

    transition = {
        "action": "close",
        "base": row["base"],
        "position_id": position["position_id"],
        "long_venue": position["long_venue"],
        "short_venue": position["short_venue"],
        "notional_quote_per_leg": notional,
        "exit_reason": exit_reason,
    }
    allowed, row, execution_decision = _guard_position_transition(
        plan,
        state,
        row,
        transition,
        ledger_path=ledger_target,
        state_path=state_target,
        contract=resolved_contract,
    )
    if not allowed:
        return deepcopy(state)

    price_pnl = _position_price_pnl(position, row, notional)
    cost_quote = notional * float(state["cost_cycle_bps"]) / 10_000.0
    net_pnl = price_pnl + float(position["funding_pnl_quote"]) - cost_quote
    closed = {
        "position_id": position["position_id"],
        "base": row["base"],
        "entry_ts": position["entry_ts"],
        "exit_ts": row["ts"],
        "exit_reason": exit_reason,
        "price_pnl_quote": price_pnl,
        "funding_pnl_quote": float(position["funding_pnl_quote"]),
        "cost_quote": cost_quote,
        "net_pnl_quote": net_pnl,
        "exit_execution": deepcopy(execution_decision),
    }
    del state["positions"][row["base"]]
    state["status"] = "OPEN" if state["positions"] else "FLAT"
    state["realized_net_pnl_quote"] += net_pnl
    close_date = datetime.fromtimestamp(row["ts"], timezone.utc).date().isoformat()
    if state.get("daily_realized_date") != close_date:
        state["daily_realized_date"] = close_date
        state["daily_realized_net_pnl_quote"] = 0.0
    state["daily_realized_net_pnl_quote"] += net_pnl
    _append_event(
        ledger_target,
        state_target,
        state,
        event_type="POSITION_CLOSED",
        event_ts=row["ts"],
        details={"closed_position": closed},
        contract=resolved_contract,
    )
    if state["daily_realized_net_pnl_quote"] <= -float(state["daily_loss_limit_quote"]):
        state["status"] = "HALTED"
        state["kill_switch_reason"] = "daily_loss_limit"
        _append_event(
            ledger_target,
            state_target,
            state,
            event_type="KILL_SWITCH",
            event_ts=row["ts"],
            details={"reason": state["kill_switch_reason"]},
            contract=resolved_contract,
        )
    return deepcopy(state)


def reconcile_basis_paper_state(
    state_path: str | Path,
    ledger_path: str | Path,
    *,
    contract: BasisPaperOmsContract | None = None,
) -> dict[str, Any]:
    resolved_contract = contract or _v1_contract()
    state_target = Path(state_path).expanduser().resolve()
    state = _load_state(state_target, contract=resolved_contract)
    events = _read_ledger_events(ledger_path, contract=resolved_contract)
    last = events[-1]
    expected_projection = (last.get("details") or {}).get("state_after")
    matched = (
        isinstance(expected_projection, dict)
        and expected_projection == _projection(state)
        and int(state.get("last_ledger_sequence") or 0) == int(last["sequence"])
        and state.get("last_event_hash") == last["event_hash"]
    )
    return {
        "matched": matched,
        "event_count": len(events),
        "state_last_sequence": state.get("last_ledger_sequence"),
        "ledger_last_sequence": last["sequence"],
        "status": state.get("status"),
        "open_position_count": len(state.get("positions") or {}),
        "kill_switch_active": state.get("status") == "HALTED",
    }


def basis_paper_status(
    *,
    ledger_path: str | Path,
    state_path: str | Path,
    contract: BasisPaperOmsContract | None = None,
) -> dict[str, Any]:
    resolved_contract = contract or _v1_contract()
    with paper_oms_single_writer_lock(
        ledger_path=ledger_path,
        state_path=state_path,
        operation="status",
    ):
        return {
            "ledger": verify_basis_paper_ledger(
                ledger_path,
                contract=resolved_contract,
            ),
            "reconciliation": reconcile_basis_paper_state(
                state_path,
                ledger_path,
                contract=resolved_contract,
            ),
            "state": _load_state(
                Path(state_path).expanduser().resolve(),
                contract=resolved_contract,
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper-only OMS for the frozen historical basis hypothesis")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--plan", required=True)
    init_parser.add_argument("--report", required=True)
    init_parser.add_argument("--ledger", required=True)
    init_parser.add_argument("--state", required=True)
    init_parser.add_argument("--daily-loss-limit-quote", type=float, default=50.0)
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--plan", required=True)
    observe_parser.add_argument("--report", required=True)
    observe_parser.add_argument("--ledger", required=True)
    observe_parser.add_argument("--state", required=True)
    observe_parser.add_argument("--observation", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--ledger", required=True)
    status_parser.add_argument("--state", required=True)
    args = parser.parse_args()
    if args.command == "init":
        result = initialize_basis_paper_oms(
            args.plan,
            args.report,
            ledger_path=args.ledger,
            state_path=args.state,
            daily_loss_limit_quote=args.daily_loss_limit_quote,
        )
    elif args.command == "observe":
        result = apply_basis_paper_observation(
            args.plan,
            args.report,
            ledger_path=args.ledger,
            state_path=args.state,
            observation=_read_json(args.observation),
        )
    else:
        result = basis_paper_status(
            ledger_path=args.ledger,
            state_path=args.state,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
