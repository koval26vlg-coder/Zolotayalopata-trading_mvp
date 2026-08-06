from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_membership_momentum_v2_execution_probe as probe
import gate_membership_momentum_v2_execution_probe_runtime as probe_runtime
import gate_membership_momentum_v2_execution_selection as selection
import gate_membership_momentum_v2_paper_plan as paper_plan
import gate_membership_momentum_v2_train as v2_train
from gate_membership_momentum import DAY_SEC


APPROVAL_SCHEMA = "trading_mvp_gate_membership_momentum_v2_paper_approval_v1"
PAPER_RAW_INPUT_SCHEMA = (
    "trading_mvp_gate_membership_momentum_v2_paper_raw_input_v2"
)
PAPER_RAW_SOURCE_SCHEMA = (
    "trading_mvp_gate_membership_momentum_v2_paper_raw_source_manifest_v2"
)
PAPER_SOURCE_SCHEMA = "trading_mvp_gate_membership_momentum_v2_paper_source_v2"
PAPER_EVIDENCE_SCHEMA = "trading_mvp_gate_membership_momentum_v2_paper_evidence_v2"
EVENT_SCHEMA = "trading_mvp_gate_membership_momentum_v2_paper_event_v2"
LEDGER_EVENT_SCHEMA = "trading_mvp_gate_membership_momentum_v2_paper_ledger_event_v1"
STATE_SCHEMA = "trading_mvp_gate_membership_momentum_v2_paper_state_v1"
EVENT_READY_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_PAPER_EVENT_READY"
PAPER_RAW_SOURCE_READY_DECISION = (
    "GATE_MEMBERSHIP_MOMENTUM_V2_PAPER_RAW_SOURCE_READY"
)
PAPER_SOURCE_READY_DECISION = (
    "GATE_MEMBERSHIP_MOMENTUM_V2_PAPER_SOURCE_READY"
)
PAPER_EVIDENCE_READY_DECISION = (
    "GATE_MEMBERSHIP_MOMENTUM_V2_PAPER_EVIDENCE_READY"
)
PAPER_ACTIVE_DECISION = "PAPER_FORWARD_ACTIVE"
PAPER_HALTED_DECISION = "PAPER_FORWARD_HALTED"
PAPER_REJECTED_DECISION = "PAPER_REJECTED"
LIVE_REVIEW_ELIGIBLE_DECISION = "LIVE_REVIEW_ELIGIBLE"
ZERO_HASH = "0" * 64
PAPER_SOURCE_TYPES = frozenset(
    {"entry_execution", "exit_execution", "funding_settlements"}
)
MANUAL_PNL_FIELDS = {
    "pnl",
    "pnl_quote",
    "net_pnl",
    "net_pnl_quote",
    "price_pnl",
    "price_pnl_quote",
    "funding_pnl",
    "funding_pnl_quote",
    "cost",
    "cost_quote",
    "fees",
    "fees_quote",
    "profit",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {resolved}")
    return payload


def _finite(value: Any, *, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _timestamp(value: Any, *, label: str) -> int:
    result = _finite(value, label=label)
    if result <= 0.0 or not result.is_integer():
        raise ValueError(f"{label} must be a positive whole-second timestamp")
    return int(result)


def _funding_settlement_evidence(
    raw: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    interval_sec = _timestamp(
        raw.get("funding_interval_sec"),
        label=f"{label} funding interval",
    )
    try:
        expected_count = int(raw.get("expected_settlement_count"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} expected settlement count is invalid") from exc
    if expected_count < 1:
        raise ValueError(f"{label} expected settlement count must be positive")
    raw_settlements = raw.get("settlements")
    if not isinstance(raw_settlements, list) or not raw_settlements:
        raise ValueError(f"{label} funding settlements must be a non-empty list")
    settlements: list[dict[str, Any]] = []
    previous_ts: int | None = None
    for index, item in enumerate(raw_settlements):
        if not isinstance(item, Mapping):
            raise ValueError(f"{label} funding settlement {index} is not an object")
        timestamp = _timestamp(
            item.get("ts"),
            label=f"{label} funding settlement timestamp",
        )
        if previous_ts is not None and timestamp <= previous_ts:
            raise ValueError(f"{label} funding settlements are not strictly ordered")
        previous_ts = timestamp
        settlements.append(
            {
                "ts": timestamp,
                "funding_rate": _finite(
                    item.get("funding_rate"),
                    label=f"{label} funding rate",
                ),
            }
        )
    observed_count = len(settlements)
    if observed_count > expected_count:
        raise ValueError(f"{label} observed settlements exceed the expected count")
    coverage = min(1.0, observed_count / expected_count)
    return {
        "funding_interval_sec": interval_sec,
        "expected_settlement_count": expected_count,
        "observed_settlement_count": observed_count,
        "settlement_coverage": coverage,
        "settlements": settlements,
        "funding_rate_sum": sum(
            float(item["funding_rate"]) for item in settlements
        ),
    }


def _positive(value: Any, *, label: str) -> float:
    result = _finite(value, label=label)
    if result <= 0.0:
        raise ValueError(f"{label} must be positive")
    return result


def _validate_hash(value: Any, *, label: str) -> str:
    return v2_train._validate_hash(str(value or ""), label=label)


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return v3_history_plan.sha256_json(payload)


def paper_source_hash(payload: Mapping[str, Any]) -> str:
    return _canonical_hash(payload)


def paper_raw_source_hash(payload: Mapping[str, Any]) -> str:
    return _canonical_hash(payload)


def paper_evidence_hash(payload: Mapping[str, Any]) -> str:
    return _canonical_hash(payload)


def _atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                dict(payload),
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _contains_manual_pnl(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).strip().lower() in MANUAL_PNL_FIELDS:
                return True
            if _contains_manual_pnl(item):
                return True
    elif isinstance(value, list):
        return any(_contains_manual_pnl(item) for item in value)
    return False


def _approval_id(payload: Mapping[str, Any]) -> str:
    return _canonical_hash(
        {key: value for key, value in payload.items() if key != "approval_id"}
    )


def create_paper_approval(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path,
    confirmed_paper_forward: bool,
    approved_at_utc: str | None = None,
) -> dict[str, Any]:
    if confirmed_paper_forward is not True:
        raise ValueError("paper-forward approval requires an explicit confirmation flag")
    expected = _validate_hash(expected_plan_hash, label="paper plan hash")
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = paper_plan.validate_paper_plan(resolved_plan, expected)
    if plan["plan_hash"] != expected:
        raise ValueError("paper-forward approval plan hash mismatch")
    body: dict[str, Any] = {
        "schema": APPROVAL_SCHEMA,
        "approved_at_utc": approved_at_utc or _utc_now(),
        "plan_path": str(resolved_plan),
        "plan_file_sha256": v3_history_plan.sha256_file(resolved_plan),
        "plan_hash": expected,
        "hypothesis_id": plan["hypothesis_id"],
        "authorized_action": "paper_forward_accrual_and_offline_state_evaluation",
        "paper_forward_authorized": True,
        "public_data_only": True,
        "network_collector_started": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
        "maximum_authority": "PAPER_FORWARD_ONLY",
    }
    approval = {**body, "approval_id": _canonical_hash(body)}
    v2_train._write_json_immutable(output_path, approval)
    return approval


def _validate_approval(
    approval_path: str | Path,
    *,
    plan_path: Path,
    plan: Mapping[str, Any],
) -> tuple[dict[str, Any], Path]:
    resolved = Path(approval_path).expanduser().resolve()
    approval = _read_json(resolved)
    if approval.get("schema") != APPROVAL_SCHEMA:
        raise ValueError("momentum-v2 paper approval schema mismatch")
    if approval.get("approval_id") != _approval_id(approval):
        raise ValueError("momentum-v2 paper approval id mismatch")
    if (
        Path(str(approval.get("plan_path") or "")).expanduser().resolve() != plan_path
        or approval.get("plan_file_sha256") != v3_history_plan.sha256_file(plan_path)
        or approval.get("plan_hash") != plan["plan_hash"]
    ):
        raise ValueError("momentum-v2 paper approval plan provenance mismatch")
    if approval.get("paper_forward_authorized") is not True:
        raise ValueError("momentum-v2 paper approval did not authorize accrual")
    for field in (
        "network_collector_started",
        "live_orders",
        "private_api_keys",
        "leverage_or_margin",
        "grid_search",
        "retune",
    ):
        if approval.get(field) is not False:
            raise ValueError(f"momentum-v2 paper approval safety flag changed: {field}")
    if approval.get("maximum_authority") != "PAPER_FORWARD_ONLY":
        raise ValueError("momentum-v2 paper approval authority mismatch")
    return approval, resolved


def _validate_plan_and_approval(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    expected = _validate_hash(expected_plan_hash, label="paper plan hash")
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = paper_plan.validate_paper_plan(resolved_plan, expected)
    approval, resolved_approval = _validate_approval(
        approval_path,
        plan_path=resolved_plan,
        plan=plan,
    )
    return plan, resolved_plan, approval, resolved_approval


def _validate_event_selection(
    plan: Mapping[str, Any],
    *,
    selection_path: str | Path,
    expected_selection_hash: str,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    resolved_selection = Path(selection_path).expanduser().resolve()
    selected = selection.validate_selection_artifact(
        resolved_selection,
        _validate_hash(expected_selection_hash, label="selection artifact hash"),
    )
    if (
        selected.get("decision") != selection.SELECTION_READY_DECISION
        or selected.get("execution_probe_collect_allowed") is not True
        or not selected.get("selected_positions")
    ):
        raise ValueError("paper event requires a ready causal selection")
    probe_auth = selected.get("probe_plan_authorization")
    if not isinstance(probe_auth, Mapping):
        raise ValueError("paper event selection probe authorization is missing")
    resolved_probe = Path(str(probe_auth.get("path") or "")).expanduser().resolve()
    event_probe = probe.validate_execution_probe_plan(
        resolved_probe,
        str(probe_auth.get("plan_hash") or ""),
    )
    report_auth = plan["execution_report_authorization"]
    _report, _report_path, original_probe, _original_selection = (
        paper_plan._validate_execution_report(
            report_auth["path"],
            report_auth["result_hash"],
        )
    )
    if (
        event_probe.get("historical_authorization")
        != original_probe.get("historical_authorization")
        or event_probe.get("hypothesis_id") != plan.get("hypothesis_id")
        or event_probe.get("strategy") != plan.get("strategy")
        or event_probe.get("cost_contract") != plan.get("cost_contract")
        or event_probe.get("rebalance_schedule_contract")
        != plan.get("rebalance_schedule_contract")
    ):
        raise ValueError("paper event selection belongs to another frozen strategy chain")

    target = selected["target_event_contract"]
    paper_contract = plan["paper_contract"]
    signal_day = int(target["target_signal_day"])
    anchor = int(paper_contract["global_anchor_day"])
    cadence = int(paper_contract["event_cadence_days"])
    if signal_day < int(paper_contract["first_paper_signal_day"]):
        raise ValueError("paper event predates the frozen paper start")
    if cadence <= 0 or (signal_day - anchor) % cadence:
        raise ValueError("paper event violates the frozen weekly cadence")
    if int(target["target_entry_day"]) != signal_day + 1:
        raise ValueError("paper event entry day mismatch")
    return selected, resolved_selection, event_probe, resolved_probe


def _validate_execution_metrics(
    metrics: Any,
    *,
    label: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(metrics, Mapping):
        raise ValueError(f"{label} execution metrics are missing")
    valid_snapshots = int(metrics.get("valid_snapshots") or 0)
    coverage = _finite(metrics.get("coverage"), label=f"{label} coverage")
    impact = _finite(metrics.get("p95_impact_bps"), label=f"{label} p95 impact")
    capacity = _finite(metrics.get("capacity_quote"), label=f"{label} capacity")
    skew = _finite(
        metrics.get("max_timestamp_skew_ms"),
        label=f"{label} timestamp skew",
    )
    quote_age = _finite(
        metrics.get("max_quote_age_ms"),
        label=f"{label} quote age",
    )
    critical = int(metrics.get("critical_error_count") or 0)
    evidence_hash = _validate_hash(
        metrics.get("evidence_hash"),
        label=f"{label} execution evidence hash",
    )
    if valid_snapshots < int(contract["minimum_valid_snapshots_per_asset_per_window"]):
        raise ValueError(f"{label} valid snapshots are below the frozen gate")
    if coverage < float(contract["minimum_coverage_per_asset"]):
        raise ValueError(f"{label} coverage is below the frozen gate")
    if impact > float(contract["maximum_p95_impact_bps"]):
        raise ValueError(f"{label} p95 impact exceeds the frozen gate")
    if capacity < float(contract["minimum_capacity_quote_per_asset"]):
        raise ValueError(f"{label} capacity is below the frozen gate")
    if skew > float(contract["maximum_timestamp_skew_ms"]):
        raise ValueError(f"{label} timestamp skew exceeds the frozen gate")
    if quote_age > float(contract["maximum_quote_age_ms"]):
        raise ValueError(f"{label} quote age exceeds the frozen gate")
    if critical != 0:
        raise ValueError(f"{label} contains critical execution errors")
    return {
        "valid_snapshots": valid_snapshots,
        "coverage": coverage,
        "p95_impact_bps": impact,
        "capacity_quote": capacity,
        "max_timestamp_skew_ms": skew,
        "max_quote_age_ms": quote_age,
        "critical_error_count": critical,
        "evidence_hash": evidence_hash,
    }


def _normalized_raw_source_rows(
    raw_input: Mapping[str, Any],
    *,
    input_file_hash: str,
) -> list[dict[str, Any]]:
    rows = raw_input.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("paper raw input rows must be a non-empty list")
    normalized = json.loads(json.dumps(rows, allow_nan=False))
    if not isinstance(normalized, list):
        raise ValueError("paper raw input rows are invalid")
    source_type = str(raw_input.get("source_type") or "")
    for row in normalized:
        if not isinstance(row, dict):
            raise ValueError("paper raw input rows must contain objects")
        if source_type != "funding_settlements":
            metrics = row.get("execution_metrics")
            if not isinstance(metrics, dict):
                raise ValueError("paper raw execution metrics are missing")
            if "evidence_hash" in metrics:
                raise ValueError(
                    "paper raw input must not self-declare an execution evidence hash"
                )
            metrics["evidence_hash"] = input_file_hash
    return normalized


def _normalized_funding_history(
    path: Path,
    *,
    expected_symbol: str,
) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if (
        payload.get("schema") != "trading_mvp_funding_settlements_v1"
        or str(payload.get("exchange") or "").lower() != "gateio"
        or str(payload.get("symbol") or "").upper() != expected_symbol.upper()
    ):
        raise ValueError(f"unexpected Gate funding history identity: {expected_symbol}")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) < 2:
        raise ValueError(f"Gate funding history is too short: {expected_symbol}")
    rows: list[dict[str, Any]] = []
    previous_ts: int | None = None
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Gate funding history row is invalid: {expected_symbol}:{index}")
        timestamp = _timestamp(
            raw.get("ts"),
            label=f"{expected_symbol} funding history timestamp",
        )
        if previous_ts is not None and timestamp <= previous_ts:
            raise ValueError(f"Gate funding history is not strictly ordered: {expected_symbol}")
        previous_ts = timestamp
        rows.append(
            {
                "ts": timestamp,
                "funding_rate": _finite(
                    raw.get("funding_rate"),
                    label=f"{expected_symbol} funding history rate",
                ),
            }
        )
    return rows


def _funding_evidence_for_interval(
    rows: Sequence[Mapping[str, Any]],
    *,
    entry_ts: int,
    exit_ts: int,
    label: str,
) -> dict[str, Any]:
    if exit_ts <= entry_ts:
        raise ValueError(f"{label} funding interval is not positive")
    timestamps = [int(row["ts"]) for row in rows]
    deltas = [right - left for left, right in zip(timestamps, timestamps[1:])]
    positive_deltas = [value for value in deltas if value > 0]
    if not positive_deltas:
        raise ValueError(f"{label} funding interval cannot be inferred")
    counts: dict[int, int] = {}
    for value in positive_deltas:
        counts[value] = counts.get(value, 0) + 1
    interval_sec = min(
        counts,
        key=lambda value: (-counts[value], value),
    )
    interval_confidence = counts[interval_sec] / len(positive_deltas)
    if interval_confidence < 0.80:
        raise ValueError(f"{label} funding interval confidence is below 0.80")
    phase_counts: dict[int, int] = {}
    for timestamp in timestamps:
        phase = timestamp % interval_sec
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
    phase = min(
        phase_counts,
        key=lambda value: (-phase_counts[value], value),
    )
    phase_confidence = phase_counts[phase] / len(timestamps)
    if phase_confidence < 0.80:
        raise ValueError(f"{label} funding schedule phase confidence is below 0.80")
    first_expected = entry_ts + ((phase - entry_ts) % interval_sec)
    if first_expected <= entry_ts:
        first_expected += interval_sec
    expected_timestamps = list(range(first_expected, exit_ts, interval_sec))
    if not expected_timestamps:
        raise ValueError(f"{label} funding interval contains no expected settlements")
    by_timestamp = {int(row["ts"]): dict(row) for row in rows}
    expected_timestamp_set = set(expected_timestamps)
    observed = [
        by_timestamp[timestamp]
        for timestamp in expected_timestamps
        if timestamp in by_timestamp
    ]
    unexpected_inside = [
        timestamp
        for timestamp in timestamps
        if entry_ts < timestamp < exit_ts and timestamp not in expected_timestamp_set
    ]
    if unexpected_inside:
        raise ValueError(f"{label} funding history contains off-schedule settlements")
    return {
        "funding_interval_sec": interval_sec,
        "expected_settlement_count": len(expected_timestamps),
        "settlements": observed,
    }


def _funding_rows_from_derivation(
    raw_input: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], float]:
    derivation = raw_input.get("derivation")
    if not isinstance(derivation, Mapping) or derivation.get("mode") != (
        "gate_funding_history_between_hash_bound_execution_sources_v1"
    ):
        raise ValueError("paper funding raw input derivation is missing")
    entry_auth = derivation.get("entry_source")
    exit_auth = derivation.get("exit_source")
    history_auths = derivation.get("funding_histories")
    if (
        not isinstance(entry_auth, Mapping)
        or not isinstance(exit_auth, Mapping)
        or not isinstance(history_auths, list)
    ):
        raise ValueError("paper funding derivation authorization is invalid")

    def load_source(auth: Mapping[str, Any], expected_type: str) -> dict[str, Any]:
        path = Path(str(auth.get("path") or "")).expanduser().resolve()
        if not path.is_file() or auth.get("file_sha256") != v3_history_plan.sha256_file(path):
            raise ValueError(f"paper funding {expected_type} source file hash mismatch")
        source = validate_paper_source_artifact(
            path,
            str(auth.get("artifact_hash") or ""),
        )
        if source.get("source_type") != expected_type:
            raise ValueError(f"paper funding requires {expected_type} source")
        return source

    entry_source = load_source(entry_auth, "entry_execution")
    exit_source = load_source(exit_auth, "exit_execution")
    for field in ("paper_plan_hash", "selection_hash", "signal_day"):
        if (
            entry_source.get(field) != raw_input.get(field)
            or exit_source.get(field) != raw_input.get(field)
        ):
            raise ValueError("paper funding execution sources belong to another event")
    entry_by_asset = {
        str(row.get("canonical_asset_id") or ""): row
        for row in entry_source.get("rows") or []
        if isinstance(row, Mapping)
    }
    exit_by_asset = {
        str(row.get("canonical_asset_id") or ""): row
        for row in exit_source.get("rows") or []
        if isinstance(row, Mapping)
    }
    if not entry_by_asset or set(entry_by_asset) != set(exit_by_asset):
        raise ValueError("paper funding execution source assets mismatch")
    history_by_symbol: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for auth in history_auths:
        if not isinstance(auth, Mapping):
            raise ValueError("paper funding history authorization is invalid")
        symbol = str(auth.get("symbol") or "").upper()
        path = Path(str(auth.get("path") or "")).expanduser().resolve()
        if not symbol or symbol in history_by_symbol or not path.is_file():
            raise ValueError("paper funding history path/symbol is missing or duplicated")
        if auth.get("file_sha256") != v3_history_plan.sha256_file(path):
            raise ValueError(f"paper funding history file hash mismatch: {symbol}")
        history_by_symbol[symbol] = (path, auth)
    expected_symbols = {
        str(row.get("symbol") or "").upper() for row in entry_by_asset.values()
    }
    if set(history_by_symbol) != expected_symbols:
        raise ValueError("paper funding histories differ from execution source symbols")

    output_rows: list[dict[str, Any]] = []
    coverages: list[float] = []
    for asset in sorted(entry_by_asset):
        entry = entry_by_asset[asset]
        exit_row = exit_by_asset[asset]
        identity = {
            key: str(entry.get(key) or "")
            for key in ("canonical_asset_id", "symbol", "base", "side")
        }
        if any(str(exit_row.get(key) or "") != value for key, value in identity.items()):
            raise ValueError(f"paper funding execution identity mismatch: {asset}")
        symbol = identity["symbol"].upper()
        history_path = history_by_symbol[symbol][0]
        history_rows = _normalized_funding_history(
            history_path,
            expected_symbol=symbol,
        )
        funding = _funding_evidence_for_interval(
            history_rows,
            entry_ts=_timestamp(entry.get("execution_ts"), label=f"{asset} entry timestamp"),
            exit_ts=_timestamp(exit_row.get("execution_ts"), label=f"{asset} exit timestamp"),
            label=asset,
        )
        normalized = _funding_settlement_evidence(
            funding,
            label=asset,
        )
        coverages.append(float(normalized["settlement_coverage"]))
        output_rows.append(
            {
                **identity,
                "funding_interval_sec": normalized["funding_interval_sec"],
                "expected_settlement_count": normalized[
                    "expected_settlement_count"
                ],
                "settlements": normalized["settlements"],
            }
        )
    return output_rows, min(coverages, default=0.0)


def build_paper_funding_raw_source_manifest(
    *,
    entry_source_path: str | Path,
    expected_entry_source_hash: str,
    exit_source_path: str | Path,
    expected_exit_source_hash: str,
    funding_history_paths: Sequence[str | Path],
    raw_input_path: str | Path,
    raw_manifest_path: str | Path,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    entry_path = Path(entry_source_path).expanduser().resolve()
    exit_path = Path(exit_source_path).expanduser().resolve()
    entry = validate_paper_source_artifact(entry_path, expected_entry_source_hash)
    exit_source = validate_paper_source_artifact(exit_path, expected_exit_source_hash)
    if entry.get("source_type") != "entry_execution" or exit_source.get("source_type") != "exit_execution":
        raise ValueError("paper funding adapter requires entry and exit execution sources")
    for field in ("paper_plan_hash", "selection_hash", "signal_day"):
        if entry.get(field) != exit_source.get(field):
            raise ValueError("paper funding entry/exit sources belong to different events")
    resolved_histories = [Path(path).expanduser().resolve() for path in funding_history_paths]
    if not resolved_histories or len(set(resolved_histories)) != len(resolved_histories):
        raise ValueError("paper funding adapter requires distinct funding histories")
    history_auths = []
    for path in resolved_histories:
        payload = _read_json(path)
        symbol = str(payload.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("paper funding history symbol is missing")
        history_auths.append(
            {
                "symbol": symbol,
                "path": str(path),
                "file_sha256": v3_history_plan.sha256_file(path),
            }
        )
    history_auths.sort(key=lambda item: item["symbol"])
    derivation = {
        "mode": "gate_funding_history_between_hash_bound_execution_sources_v1",
        "entry_source": {
            "path": str(entry_path),
            "file_sha256": v3_history_plan.sha256_file(entry_path),
            "artifact_hash": entry["artifact_hash"],
        },
        "exit_source": {
            "path": str(exit_path),
            "file_sha256": v3_history_plan.sha256_file(exit_path),
            "artifact_hash": exit_source["artifact_hash"],
        },
        "funding_histories": history_auths,
    }
    raw_input: dict[str, Any] = {
        "schema": PAPER_RAW_INPUT_SCHEMA,
        "source_type": "funding_settlements",
        "paper_plan_hash": entry["paper_plan_hash"],
        "selection_hash": entry["selection_hash"],
        "signal_day": int(entry["signal_day"]),
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "derivation": derivation,
    }
    rows, coverage = _funding_rows_from_derivation(raw_input)
    if coverage < 0.98 or coverage > 1.0:
        raise ValueError("funding settlement coverage is below the frozen gate")
    raw_input["rows"] = rows
    raw_input["funding_settlement_coverage"] = coverage
    raw_target = Path(raw_input_path).expanduser().resolve()
    v2_train._write_json_immutable(raw_target, raw_input)
    raw_hash = v3_history_plan.sha256_file(raw_target)
    frozen: dict[str, Any] = {
        "schema": PAPER_RAW_SOURCE_SCHEMA,
        "final": True,
        "decision": PAPER_RAW_SOURCE_READY_DECISION,
        "source_type": "funding_settlements",
        "paper_plan_hash": entry["paper_plan_hash"],
        "selection_hash": entry["selection_hash"],
        "signal_day": int(entry["signal_day"]),
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "input_artifacts": [{"path": str(raw_target), "file_sha256": raw_hash}],
        "rows": rows,
        "funding_settlement_coverage": coverage,
    }
    artifact = {
        **frozen,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "artifact_hash": paper_raw_source_hash(frozen),
        "frozen_contract": frozen,
    }
    v2_train._write_json_immutable(raw_manifest_path, artifact)
    return artifact


def _paper_execution_side(*, boundary: str, position_side: str) -> str:
    side = str(position_side).lower()
    if side not in {"long", "short"}:
        raise ValueError(f"unsupported paper position side: {side}")
    if boundary == "entry":
        return "buy" if side == "long" else "sell"
    if boundary == "exit":
        return "sell" if side == "long" else "buy"
    raise ValueError("paper execution boundary must be entry or exit")


def _first_executable_snapshot(
    plan: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    canonical_asset_id: str,
    execution_side: str,
) -> tuple[int, float]:
    window = plan["window_contract"]
    contract = plan["collector_contract"]
    expected_cycles = int(window["expected_cycles"])
    by_cycle: dict[int, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        cycle = int(row.get("cycle") or 0)
        identity = str(row.get("canonical_asset_id") or "")
        if cycle < 1 or cycle > expected_cycles or not identity:
            raise ValueError("paper execution sample is outside the frozen cycle contract")
        bucket = by_cycle.setdefault(cycle, {})
        if identity in bucket:
            raise ValueError("duplicate paper execution sample for cycle/asset")
        bucket[identity] = row
    for cycle in range(1, expected_cycles + 1):
        cycle_rows = by_cycle.get(cycle, {})
        exchange_times = []
        for row in cycle_rows.values():
            if row.get("collection_error"):
                continue
            try:
                exchange_ts = float(row.get("exchange_ts"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(exchange_ts) and exchange_ts > 0:
                exchange_times.append(exchange_ts)
        cycle_skew_ms = (
            (max(exchange_times) - min(exchange_times)) * 1000.0
            if len(exchange_times) >= 2
            else math.inf
        )
        row = cycle_rows.get(canonical_asset_id)
        if row is None or row.get("collection_error"):
            continue
        try:
            received_ts = float(row.get("received_ts"))
            exchange_ts = float(row.get("exchange_ts"))
        except (TypeError, ValueError):
            continue
        quote_age_ms = (received_ts - exchange_ts) * 1000.0
        if (
            not math.isfinite(exchange_ts)
            or not math.isfinite(quote_age_ms)
            or quote_age_ms < 0
            or quote_age_ms > float(contract["maximum_quote_age_ms"])
            or not math.isfinite(cycle_skew_ms)
            or cycle_skew_ms > float(contract["maximum_timestamp_skew_ms"])
        ):
            continue
        levels = row.get("asks") if execution_side == "buy" else row.get("bids")
        metrics = probe_runtime.depth_execution_metrics(
            levels or [],
            side=execution_side,
            notional_quote=float(contract["notional_quote_per_asset"]),
            max_impact_bps=float(contract["maximum_p95_impact_bps"]),
        )
        if (
            metrics.get("filled") is not True
            or float(metrics["impact_bps"]) > float(contract["maximum_p95_impact_bps"])
            or float(metrics["capacity_quote_at_max_impact"])
            < float(contract["minimum_capacity_quote_per_asset"])
        ):
            continue
        execution_ts = int(exchange_ts)
        if not int(window["start_ts"]) <= execution_ts < int(window["end_ts"]):
            continue
        price = _positive(
            metrics.get("average_price"),
            label=f"{canonical_asset_id} executable price",
        )
        return execution_ts, price
    raise ValueError(
        f"no causal executable snapshot in first frozen window: {canonical_asset_id}"
    )


def _paper_execution_rows_from_derivation(
    raw_input: Mapping[str, Any],
) -> list[dict[str, Any]]:
    derivation = raw_input.get("derivation")
    if not isinstance(derivation, Mapping) or derivation.get("mode") != (
        "gate_depth_windows_for_hash_bound_paper_boundary_v1"
    ):
        raise ValueError("paper execution raw input depth-window derivation is missing")
    boundary = str(derivation.get("boundary") or "").lower()
    source_type = str(raw_input.get("source_type") or "")
    expected_source_type = {
        "entry": "entry_execution",
        "exit": "exit_execution",
    }.get(boundary)
    if source_type != expected_source_type:
        raise ValueError("paper execution source type/boundary mismatch")
    plan_auth = derivation.get("paper_plan")
    approval_auth = derivation.get("paper_approval")
    selection_auth = derivation.get("selection")
    manifest_auths = derivation.get("window_manifests")
    if (
        not isinstance(plan_auth, Mapping)
        or not isinstance(approval_auth, Mapping)
        or not isinstance(selection_auth, Mapping)
        or not isinstance(manifest_auths, list)
        or len(manifest_auths) != probe.WINDOW_COUNT
    ):
        raise ValueError("paper execution derivation requires exactly three windows")
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=str(plan_auth.get("path") or ""),
        expected_plan_hash=str(plan_auth.get("plan_hash") or ""),
        approval_path=str(approval_auth.get("path") or ""),
    )
    selected, resolved_selection, event_probe, _resolved_probe = _validate_event_selection(
        plan,
        selection_path=str(selection_auth.get("path") or ""),
        expected_selection_hash=str(selection_auth.get("artifact_hash") or ""),
    )
    if (
        plan_auth.get("file_sha256") != v3_history_plan.sha256_file(resolved_plan)
        or approval_auth.get("file_sha256")
        != v3_history_plan.sha256_file(resolved_approval)
        or approval_auth.get("approval_id") != approval["approval_id"]
        or selection_auth.get("file_sha256")
        != v3_history_plan.sha256_file(resolved_selection)
    ):
        raise ValueError("paper execution derivation source hash mismatch")
    for field in ("paper_plan_hash", "selection_hash", "signal_day"):
        expected = {
            "paper_plan_hash": plan["plan_hash"],
            "selection_hash": selected["artifact_hash"],
            "signal_day": int(selected["target_event_contract"]["target_signal_day"]),
        }[field]
        if raw_input.get(field) != expected:
            raise ValueError("paper execution raw input belongs to another event")

    windows: dict[int, dict[str, Any]] = {}
    for auth in manifest_auths:
        if not isinstance(auth, Mapping):
            raise ValueError("paper execution window authorization is invalid")
        manifest_path = Path(str(auth.get("path") or "")).expanduser().resolve()
        if (
            not manifest_path.is_file()
            or auth.get("file_sha256") != v3_history_plan.sha256_file(manifest_path)
        ):
            raise ValueError("paper execution window manifest file hash mismatch")
        manifest, metrics, resolved_manifest = probe_runtime._validate_manifest(
            manifest_path,
            expected_probe_hash=event_probe["plan_hash"],
            expected_selection_hash=selected["artifact_hash"],
        )
        if (
            auth.get("deterministic_result_hash")
            != manifest["deterministic_result_hash"]
            or resolved_manifest != manifest_path
        ):
            raise ValueError("paper execution window manifest result hash mismatch")
        window_plan_path = Path(
            str(manifest["window_plan_authorization"]["path"])
        ).expanduser().resolve()
        window_plan = probe_runtime.validate_window_collect_plan(
            window_plan_path,
            str(manifest["window_plan_authorization"]["plan_hash"]),
        )
        index = int(window_plan["window_contract"]["index"])
        if (
            index in windows
            or window_plan.get("mode") != probe_runtime.PAPER_BOUNDARY_WINDOW_MODE
            or window_plan.get("paper_boundary") != boundary
            or window_plan["paper_plan_authorization"]["plan_hash"] != plan["plan_hash"]
            or window_plan["paper_approval_authorization"]["approval_id"]
            != approval["approval_id"]
            or metrics.get("all_selected_assets_eligible") is not True
            or int(manifest.get("critical_error_count") or 0) != 0
        ):
            raise ValueError("paper execution window is ineligible or belongs to another boundary")
        samples_path = Path(str(manifest["samples"]["path"])).expanduser().resolve()
        windows[index] = {
            "plan": window_plan,
            "manifest": manifest,
            "metrics": metrics,
            "rows": probe_runtime._read_jsonl(samples_path),
        }
    if set(windows) != set(range(probe.WINDOW_COUNT)):
        raise ValueError("paper execution derivation requires exactly three indexed windows")

    selected_by_asset = {
        str(row["canonical_asset_id"]): dict(row)
        for row in selected["selected_positions"]
    }
    per_asset_by_window: dict[int, dict[str, Mapping[str, Any]]] = {}
    for index, window in windows.items():
        per_asset = window["metrics"].get("per_asset")
        if not isinstance(per_asset, list):
            raise ValueError("paper execution window per-asset metrics are missing")
        per_asset_by_window[index] = {
            str(item.get("canonical_asset_id") or ""): item
            for item in per_asset
            if isinstance(item, Mapping)
        }
        if set(per_asset_by_window[index]) != set(selected_by_asset):
            raise ValueError("paper execution window asset set changed")

    output_rows: list[dict[str, Any]] = []
    first_window = windows[0]
    for asset in sorted(selected_by_asset):
        selected_row = selected_by_asset[asset]
        execution_side = _paper_execution_side(
            boundary=boundary,
            position_side=str(selected_row["side"]),
        )
        execution_ts, executable_price = _first_executable_snapshot(
            first_window["plan"],
            first_window["rows"],
            canonical_asset_id=asset,
            execution_side=execution_side,
        )
        window_metrics = [per_asset_by_window[index][asset] for index in range(3)]
        impact_key = (
            "p95_buy_impact_bps" if execution_side == "buy" else "p95_sell_impact_bps"
        )
        capacity_key = (
            "minimum_buy_capacity_quote"
            if execution_side == "buy"
            else "minimum_sell_capacity_quote"
        )
        metrics = {
            "valid_snapshots": min(int(item["valid_snapshots"]) for item in window_metrics),
            "coverage": min(float(item["coverage"]) for item in window_metrics),
            "p95_impact_bps": max(float(item[impact_key]) for item in window_metrics),
            "capacity_quote": min(float(item[capacity_key]) for item in window_metrics),
            "max_timestamp_skew_ms": max(
                float(item["p95_timestamp_skew_ms"]) for item in window_metrics
            ),
            "max_quote_age_ms": max(
                float(item["p95_quote_age_ms"]) for item in window_metrics
            ),
            "critical_error_count": 0,
            "window_count": probe.WINDOW_COUNT,
            "window_indices": list(range(probe.WINDOW_COUNT)),
            "execution_side": execution_side,
        }
        output_rows.append(
            {
                "canonical_asset_id": asset,
                "symbol": str(selected_row["symbol"]),
                "base": str(selected_row["base"]),
                "side": str(selected_row["side"]),
                "execution_ts": execution_ts,
                "executable_price": executable_price,
                "execution_metrics": metrics,
            }
        )
    return output_rows


def build_paper_execution_raw_source_manifest(
    *,
    paper_plan_path: str | Path,
    expected_paper_plan_hash: str,
    approval_path: str | Path,
    selection_path: str | Path,
    expected_selection_hash: str,
    boundary: str,
    window_manifest_paths: Sequence[str | Path],
    raw_input_path: str | Path,
    raw_manifest_path: str | Path,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized_boundary = str(boundary).strip().lower()
    source_type = {"entry": "entry_execution", "exit": "exit_execution"}.get(
        normalized_boundary
    )
    if source_type is None:
        raise ValueError("paper execution boundary must be entry or exit")
    if len(window_manifest_paths) != probe.WINDOW_COUNT:
        raise ValueError("paper execution adapter requires exactly three window manifests")
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=paper_plan_path,
        expected_plan_hash=expected_paper_plan_hash,
        approval_path=approval_path,
    )
    selected, resolved_selection, event_probe, _resolved_probe = _validate_event_selection(
        plan,
        selection_path=selection_path,
        expected_selection_hash=expected_selection_hash,
    )
    manifest_auths = []
    seen_indices: set[int] = set()
    for value in window_manifest_paths:
        path = Path(value).expanduser().resolve()
        manifest, _metrics, _resolved = probe_runtime._validate_manifest(
            path,
            expected_probe_hash=event_probe["plan_hash"],
            expected_selection_hash=selected["artifact_hash"],
        )
        window_plan = probe_runtime.validate_window_collect_plan(
            manifest["window_plan_authorization"]["path"],
            manifest["window_plan_authorization"]["plan_hash"],
        )
        index = int(window_plan["window_contract"]["index"])
        if index in seen_indices:
            raise ValueError("paper execution adapter received a duplicate window index")
        seen_indices.add(index)
        manifest_auths.append(
            {
                "window_index": index,
                "path": str(path),
                "file_sha256": v3_history_plan.sha256_file(path),
                "deterministic_result_hash": manifest["deterministic_result_hash"],
            }
        )
    if seen_indices != set(range(probe.WINDOW_COUNT)):
        raise ValueError("paper execution adapter requires exactly three indexed windows")
    manifest_auths.sort(key=lambda item: int(item["window_index"]))
    derivation = {
        "mode": "gate_depth_windows_for_hash_bound_paper_boundary_v1",
        "boundary": normalized_boundary,
        "paper_plan": {
            "path": str(resolved_plan),
            "file_sha256": v3_history_plan.sha256_file(resolved_plan),
            "plan_hash": plan["plan_hash"],
        },
        "paper_approval": {
            "path": str(resolved_approval),
            "file_sha256": v3_history_plan.sha256_file(resolved_approval),
            "approval_id": approval["approval_id"],
        },
        "selection": {
            "path": str(resolved_selection),
            "file_sha256": v3_history_plan.sha256_file(resolved_selection),
            "artifact_hash": selected["artifact_hash"],
        },
        "window_manifests": manifest_auths,
    }
    raw_input: dict[str, Any] = {
        "schema": PAPER_RAW_INPUT_SCHEMA,
        "source_type": source_type,
        "paper_plan_hash": plan["plan_hash"],
        "selection_hash": selected["artifact_hash"],
        "signal_day": int(selected["target_event_contract"]["target_signal_day"]),
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "derivation": derivation,
        "funding_settlement_coverage": None,
    }
    rows = _paper_execution_rows_from_derivation(raw_input)
    raw_input["rows"] = rows
    raw_target = Path(raw_input_path).expanduser().resolve()
    v2_train._write_json_immutable(raw_target, raw_input)
    raw_hash = v3_history_plan.sha256_file(raw_target)
    frozen: dict[str, Any] = {
        "schema": PAPER_RAW_SOURCE_SCHEMA,
        "final": True,
        "decision": PAPER_RAW_SOURCE_READY_DECISION,
        "source_type": source_type,
        "paper_plan_hash": plan["plan_hash"],
        "selection_hash": selected["artifact_hash"],
        "signal_day": int(selected["target_event_contract"]["target_signal_day"]),
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "input_artifacts": [{"path": str(raw_target), "file_sha256": raw_hash}],
        "rows": _normalized_raw_source_rows(raw_input, input_file_hash=raw_hash),
        "funding_settlement_coverage": None,
    }
    artifact = {
        **frozen,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "artifact_hash": paper_raw_source_hash(frozen),
        "frozen_contract": frozen,
    }
    v2_train._write_json_immutable(raw_manifest_path, artifact)
    return artifact


def validate_paper_raw_source_manifest(
    path: str | Path,
    expected_raw_manifest_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    manifest = _read_json(resolved)
    frozen = manifest.get("frozen_contract")
    if (
        manifest.get("schema") != PAPER_RAW_SOURCE_SCHEMA
        or manifest.get("decision") != PAPER_RAW_SOURCE_READY_DECISION
        or manifest.get("final") is not True
        or not isinstance(frozen, Mapping)
    ):
        raise ValueError("unexpected momentum-v2 paper raw source manifest")
    computed = paper_raw_source_hash(frozen)
    if (
        manifest.get("artifact_hash") != computed
        or (
            expected_raw_manifest_hash is not None
            and _validate_hash(
                expected_raw_manifest_hash,
                label="paper raw source manifest hash",
            )
            != computed
        )
        or not all(manifest.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 paper raw source manifest hash mismatch")
    if _contains_manual_pnl(frozen):
        raise ValueError("manual PnL fields are forbidden in paper raw source evidence")
    source_type = str(manifest.get("source_type") or "")
    if source_type not in PAPER_SOURCE_TYPES:
        raise ValueError(f"unsupported momentum-v2 paper source type: {source_type}")
    _validate_hash(manifest.get("paper_plan_hash"), label="paper raw source plan hash")
    _validate_hash(
        manifest.get("selection_hash"),
        label="paper raw source selection hash",
    )
    if int(manifest.get("signal_day") or 0) <= 0:
        raise ValueError("paper raw source signal day is invalid")
    if manifest.get("public_data_only") is not True:
        raise ValueError("paper raw source must contain public data only")
    for field in ("live_orders", "private_api_keys", "leverage_or_margin"):
        if manifest.get(field) is not False:
            raise ValueError(f"paper raw source safety flag changed: {field}")

    input_artifacts = manifest.get("input_artifacts")
    if not isinstance(input_artifacts, list) or len(input_artifacts) != 1:
        raise ValueError("paper raw source requires exactly one normalized input artifact")
    input_auth = input_artifacts[0]
    if not isinstance(input_auth, Mapping):
        raise ValueError("paper raw source input provenance is invalid")
    input_path = Path(str(input_auth.get("path") or "")).expanduser().resolve()
    if not input_path.is_file():
        raise ValueError("paper source provenance normalized input is missing")
    input_hash = _validate_hash(
        input_auth.get("file_sha256"),
        label="paper raw source input hash",
    )
    if v3_history_plan.sha256_file(input_path) != input_hash:
        raise ValueError("paper source provenance normalized input hash mismatch")
    raw_input = _read_json(input_path)
    if raw_input.get("schema") != PAPER_RAW_INPUT_SCHEMA:
        raise ValueError("paper raw source normalized input schema mismatch")
    if _contains_manual_pnl(raw_input):
        raise ValueError("manual PnL fields are forbidden in paper raw input")
    for field in (
        "source_type",
        "paper_plan_hash",
        "selection_hash",
        "signal_day",
        "public_data_only",
        "live_orders",
        "private_api_keys",
        "leverage_or_margin",
        "funding_settlement_coverage",
    ):
        if raw_input.get(field) != manifest.get(field):
            raise ValueError("paper raw source normalized input metadata mismatch")
    derived_rows = _normalized_raw_source_rows(
        raw_input,
        input_file_hash=input_hash,
    )
    if manifest.get("rows") != derived_rows:
        raise ValueError("paper raw source rows do not match normalized input derivation")
    if source_type == "funding_settlements":
        expected_rows, expected_coverage = _funding_rows_from_derivation(raw_input)
        if raw_input.get("rows") != expected_rows:
            raise ValueError(
                "paper funding raw rows do not match execution/history derivation"
            )
        if not math.isclose(
            _finite(
                raw_input.get("funding_settlement_coverage"),
                label="raw funding settlement coverage",
            ),
            expected_coverage,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "paper funding raw coverage does not match execution/history derivation"
            )
        row_coverages = []
        for index, row in enumerate(derived_rows):
            if not isinstance(row, Mapping):
                raise ValueError("paper funding raw source rows must contain objects")
            funding = _funding_settlement_evidence(
                row,
                label=f"paper funding raw source row {index}",
            )
            row_coverages.append(float(funding["settlement_coverage"]))
        coverage = _finite(
            manifest.get("funding_settlement_coverage"),
            label="funding settlement coverage",
        )
        derived_coverage = min(row_coverages, default=0.0)
        if not math.isclose(coverage, derived_coverage, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                "funding settlement coverage does not match derived row coverage"
            )
        if coverage < 0.98 or coverage > 1.0:
            raise ValueError("funding settlement coverage is below the frozen gate")
    else:
        if manifest.get("funding_settlement_coverage") is not None:
            raise ValueError("execution raw source must not declare funding coverage")
        if raw_input.get("derivation") is not None:
            expected_rows = _paper_execution_rows_from_derivation(raw_input)
            if raw_input.get("rows") != expected_rows:
                raise ValueError(
                    "paper execution raw rows do not match depth-window derivation"
                )
        for index, row in enumerate(derived_rows):
            if not isinstance(row, Mapping):
                raise ValueError("paper execution raw source rows must contain objects")
            _timestamp(
                row.get("execution_ts"),
                label=f"paper execution raw source row {index} timestamp",
            )
            _positive(
                row.get("executable_price"),
                label=f"paper execution raw source row {index} price",
            )
    return manifest


def build_paper_source_artifact(
    *,
    raw_manifest_path: str | Path,
    expected_raw_manifest_hash: str,
    output_path: str | Path | None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    resolved_manifest = Path(raw_manifest_path).expanduser().resolve()
    raw_manifest = validate_paper_raw_source_manifest(
        resolved_manifest,
        expected_raw_manifest_hash,
    )
    frozen: dict[str, Any] = {
        "schema": PAPER_SOURCE_SCHEMA,
        "final": True,
        "decision": PAPER_SOURCE_READY_DECISION,
        "source_type": raw_manifest["source_type"],
        "paper_plan_hash": raw_manifest["paper_plan_hash"],
        "selection_hash": raw_manifest["selection_hash"],
        "signal_day": int(raw_manifest["signal_day"]),
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "raw_manifest_authorization": {
            "path": str(resolved_manifest),
            "file_sha256": v3_history_plan.sha256_file(resolved_manifest),
            "artifact_hash": raw_manifest["artifact_hash"],
        },
        "raw_artifacts": [dict(item) for item in raw_manifest["input_artifacts"]],
        "rows": [dict(item) for item in raw_manifest["rows"]],
        "funding_settlement_coverage": raw_manifest.get(
            "funding_settlement_coverage"
        ),
    }
    artifact = {
        **frozen,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "artifact_hash": paper_source_hash(frozen),
        "frozen_contract": frozen,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, artifact)
    return artifact


def validate_paper_source_artifact(
    path: str | Path,
    expected_source_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    source = _read_json(resolved)
    frozen = source.get("frozen_contract")
    if (
        source.get("schema") != PAPER_SOURCE_SCHEMA
        or source.get("decision") != PAPER_SOURCE_READY_DECISION
        or source.get("final") is not True
        or not isinstance(frozen, Mapping)
    ):
        raise ValueError("unexpected momentum-v2 paper source artifact")
    computed = paper_source_hash(frozen)
    if (
        source.get("artifact_hash") != computed
        or (
            expected_source_hash is not None
            and _validate_hash(expected_source_hash, label="paper source hash")
            != computed
        )
        or not all(source.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 paper source hash mismatch")
    if _contains_manual_pnl(frozen):
        raise ValueError("manual PnL fields are forbidden in paper source evidence")
    source_type = str(source.get("source_type") or "")
    if source_type not in PAPER_SOURCE_TYPES:
        raise ValueError(f"unsupported momentum-v2 paper source type: {source_type}")
    _validate_hash(source.get("paper_plan_hash"), label="paper source plan hash")
    _validate_hash(source.get("selection_hash"), label="paper source selection hash")
    if int(source.get("signal_day") or 0) <= 0:
        raise ValueError("paper source signal day is invalid")
    if source.get("public_data_only") is not True:
        raise ValueError("paper source must contain public data only")
    for field in ("live_orders", "private_api_keys", "leverage_or_margin"):
        if source.get(field) is not False:
            raise ValueError(f"paper source safety flag changed: {field}")

    manifest_auth = source.get("raw_manifest_authorization")
    if not isinstance(manifest_auth, Mapping):
        raise ValueError("paper source raw manifest authorization is missing")
    raw_manifest_path = Path(
        str(manifest_auth.get("path") or "")
    ).expanduser().resolve()
    raw_manifest = validate_paper_raw_source_manifest(
        raw_manifest_path,
        str(manifest_auth.get("artifact_hash") or ""),
    )
    if (
        manifest_auth.get("file_sha256")
        != v3_history_plan.sha256_file(raw_manifest_path)
    ):
        raise ValueError("paper source raw manifest provenance mismatch")

    raw_artifacts = source.get("raw_artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError("paper source raw artifact provenance is missing")
    raw_hashes: set[str] = set()
    raw_paths: set[Path] = set()
    for item in raw_artifacts:
        if not isinstance(item, Mapping):
            raise ValueError("paper source raw artifact provenance is invalid")
        raw_path = Path(str(item.get("path") or "")).expanduser().resolve()
        if not raw_path.is_file() or raw_path in raw_paths:
            raise ValueError("paper source provenance path is missing or duplicated")
        expected_raw_hash = _validate_hash(
            item.get("file_sha256"),
            label="paper source raw file hash",
        )
        if v3_history_plan.sha256_file(raw_path) != expected_raw_hash:
            raise ValueError("paper source provenance hash mismatch")
        raw_paths.add(raw_path)
        raw_hashes.add(expected_raw_hash)

    rows = source.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("paper source rows must be a non-empty list")
    if (
        source_type != raw_manifest.get("source_type")
        or source.get("paper_plan_hash") != raw_manifest.get("paper_plan_hash")
        or source.get("selection_hash") != raw_manifest.get("selection_hash")
        or int(source.get("signal_day") or 0)
        != int(raw_manifest.get("signal_day") or 0)
        or raw_artifacts != raw_manifest.get("input_artifacts")
        or rows != raw_manifest.get("rows")
        or source.get("funding_settlement_coverage")
        != raw_manifest.get("funding_settlement_coverage")
    ):
        raise ValueError("paper source raw manifest derivation mismatch")
    if source_type == "funding_settlements":
        row_coverages = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValueError("paper funding source rows must contain objects")
            funding = _funding_settlement_evidence(
                row,
                label=f"paper funding source row {index}",
            )
            row_coverages.append(float(funding["settlement_coverage"]))
        coverage = _finite(
            source.get("funding_settlement_coverage"),
            label="funding settlement coverage",
        )
        if not math.isclose(
            coverage,
            min(row_coverages, default=0.0),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "funding settlement coverage does not match derived row coverage"
            )
        if coverage < 0.98 or coverage > 1.0:
            raise ValueError("funding settlement coverage is below the frozen gate")
    else:
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("paper execution source rows must contain objects")
            _timestamp(row.get("execution_ts"), label="source execution timestamp")
            _positive(row.get("executable_price"), label="source executable price")
            metrics = row.get("execution_metrics")
            if not isinstance(metrics, Mapping):
                raise ValueError("paper execution source metrics are missing")
            evidence_hash = _validate_hash(
                metrics.get("evidence_hash"),
                label="paper execution source evidence hash",
            )
            if evidence_hash not in raw_hashes:
                raise ValueError(
                    "paper execution source evidence hash is not bound to a raw artifact"
                )
    return source


def _source_rows_for_selection(
    source: Mapping[str, Any],
    *,
    selected_by_asset: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    source_type = str(source["source_type"])
    normalized: dict[str, dict[str, Any]] = {}
    for raw in source["rows"]:
        if not isinstance(raw, Mapping):
            raise ValueError("paper source rows must contain objects")
        asset = str(raw.get("canonical_asset_id") or "").strip()
        if not asset or asset in normalized:
            raise ValueError("paper source contains a duplicate or empty asset")
        selected_row = selected_by_asset.get(asset)
        if selected_row is None:
            raise ValueError("paper source contains an asset outside the causal selection")
        identity = {
            "canonical_asset_id": asset,
            "symbol": str(selected_row["symbol"]),
            "base": str(selected_row["base"]),
            "side": str(selected_row["side"]),
        }
        if any(str(raw.get(key) or "") != value for key, value in identity.items()):
            raise ValueError(f"paper source identity mismatch: {asset}")
        if source_type == "funding_settlements":
            normalized[asset] = _funding_settlement_evidence(
                raw,
                label=asset,
            )
        else:
            normalized[asset] = {
                "timestamp": _timestamp(
                    raw.get("execution_ts"),
                    label=f"{asset} {source_type} timestamp",
                ),
                "price": _positive(
                    raw.get("executable_price"),
                    label=f"{asset} {source_type} executable price",
                ),
                "execution": _validate_execution_metrics(
                    raw.get("execution_metrics"),
                    label=f"{asset} {source_type}",
                    contract=contract,
                ),
            }
    if set(normalized) != set(selected_by_asset):
        raise ValueError("paper source assets differ from the causal selection")
    return normalized


def _require_execution_source_derivation(
    source: Mapping[str, Any],
    *,
    source_path: Path,
) -> None:
    source_type = str(source.get("source_type") or "")
    expected_boundary = {
        "entry_execution": "entry",
        "exit_execution": "exit",
    }.get(source_type)
    if expected_boundary is None:
        return
    manifest_auth = source.get("raw_manifest_authorization")
    if not isinstance(manifest_auth, Mapping):
        raise ValueError("paper execution source raw manifest authorization is missing")
    manifest_path = Path(str(manifest_auth.get("path") or "")).expanduser().resolve()
    manifest = validate_paper_raw_source_manifest(
        manifest_path,
        str(manifest_auth.get("artifact_hash") or ""),
    )
    input_auths = manifest.get("input_artifacts")
    if not isinstance(input_auths, list) or len(input_auths) != 1:
        raise ValueError("paper execution source normalized input is missing")
    input_path = Path(str(input_auths[0].get("path") or "")).expanduser().resolve()
    raw_input = _read_json(input_path)
    derivation = raw_input.get("derivation")
    if (
        not isinstance(derivation, Mapping)
        or derivation.get("mode")
        != "gate_depth_windows_for_hash_bound_paper_boundary_v1"
        or derivation.get("boundary") != expected_boundary
    ):
        raise ValueError(
            f"paper execution source requires depth-window derivation: {source_path}"
        )


def _paper_evidence_contract(
    *,
    plan: Mapping[str, Any],
    plan_path: Path,
    approval: Mapping[str, Any],
    approval_path: Path,
    selected: Mapping[str, Any],
    selection_path: Path,
    event_probe: Mapping[str, Any],
    probe_path: Path,
    sources: Sequence[tuple[Mapping[str, Any], Path]],
) -> dict[str, Any]:
    by_type: dict[str, tuple[Mapping[str, Any], Path]] = {}
    signal_day = int(selected["target_event_contract"]["target_signal_day"])
    for source, source_path in sources:
        source_type = str(source["source_type"])
        if source_type in by_type:
            raise ValueError(f"duplicate paper source type: {source_type}")
        if (
            source.get("paper_plan_hash") != plan["plan_hash"]
            or source.get("selection_hash") != selected["artifact_hash"]
            or int(source.get("signal_day") or 0) != signal_day
        ):
            raise ValueError("paper source belongs to another plan, selection, or event")
        _require_execution_source_derivation(source, source_path=source_path)
        by_type[source_type] = (source, source_path)
    if set(by_type) != set(PAPER_SOURCE_TYPES):
        raise ValueError("paper evidence requires entry, exit, and funding sources")

    selected_by_asset = {
        str(row["canonical_asset_id"]): dict(row)
        for row in selected["selected_positions"]
    }
    paper_contract = plan["paper_contract"]
    entry_rows = _source_rows_for_selection(
        by_type["entry_execution"][0],
        selected_by_asset=selected_by_asset,
        contract=paper_contract,
    )
    exit_rows = _source_rows_for_selection(
        by_type["exit_execution"][0],
        selected_by_asset=selected_by_asset,
        contract=paper_contract,
    )
    funding_source = by_type["funding_settlements"][0]
    funding_rows = _source_rows_for_selection(
        funding_source,
        selected_by_asset=selected_by_asset,
        contract=paper_contract,
    )
    funding_coverage = _finite(
        funding_source.get("funding_settlement_coverage"),
        label="funding settlement coverage",
    )
    windows = event_probe.get("execution_contract", {}).get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("paper event probe execution windows are missing")
    first_window = windows[0]
    if not isinstance(first_window, Mapping):
        raise ValueError("paper event first execution window is invalid")
    entry_window_start = _timestamp(
        first_window.get("start_ts"),
        label="paper entry execution window start",
    )
    entry_window_end = _timestamp(
        first_window.get("end_ts"),
        label="paper entry execution window end",
    )
    hold_sec = int(paper_contract["hold_days"]) * DAY_SEC
    exit_window_start = entry_window_start + hold_sec
    exit_window_end = entry_window_end + hold_sec
    derived_funding_coverage = min(
        float(row["settlement_coverage"])
        for row in funding_rows.values()
    )
    if not math.isclose(
        funding_coverage,
        derived_funding_coverage,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("paper funding coverage differs from settlement evidence")
    positions = []
    for asset in sorted(selected_by_asset):
        selected_row = selected_by_asset[asset]
        entry_ts = int(entry_rows[asset]["timestamp"])
        exit_ts = int(exit_rows[asset]["timestamp"])
        if not entry_window_start <= entry_ts < entry_window_end:
            raise ValueError(f"{asset} entry execution timestamp is outside the frozen window")
        if not exit_window_start <= exit_ts < exit_window_end:
            raise ValueError(f"{asset} exit execution timestamp is outside the frozen window")
        if exit_ts <= entry_ts:
            raise ValueError(f"{asset} exit execution timestamp is not after entry")
        settlements = funding_rows[asset]["settlements"]
        if any(
            not entry_ts < int(item["ts"]) < exit_ts
            for item in settlements
        ):
            raise ValueError(
                f"{asset} funding settlement escapes the actual holding interval"
            )
        positions.append(
            {
                "canonical_asset_id": asset,
                "symbol": str(selected_row["symbol"]),
                "base": str(selected_row["base"]),
                "side": str(selected_row["side"]),
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "entry_price": entry_rows[asset]["price"],
                "exit_price": exit_rows[asset]["price"],
                "funding_rate_sum": funding_rows[asset]["funding_rate_sum"],
                "funding_interval_sec": funding_rows[asset]["funding_interval_sec"],
                "funding_expected_settlement_count": funding_rows[asset][
                    "expected_settlement_count"
                ],
                "funding_settlement_count": funding_rows[asset][
                    "observed_settlement_count"
                ],
                "funding_settlement_coverage": funding_rows[asset][
                    "settlement_coverage"
                ],
                "funding_settlements": settlements,
                "entry_execution": entry_rows[asset]["execution"],
                "exit_execution": exit_rows[asset]["execution"],
            }
        )
    source_authorizations = []
    for source_type in sorted(PAPER_SOURCE_TYPES):
        source, source_path = by_type[source_type]
        source_authorizations.append(
            {
                "source_type": source_type,
                "path": str(source_path),
                "file_sha256": v3_history_plan.sha256_file(source_path),
                "artifact_hash": source["artifact_hash"],
            }
        )
    target = selected["target_event_contract"]
    contract_body: dict[str, Any] = {
        "schema": PAPER_EVIDENCE_SCHEMA,
        "final": True,
        "decision": PAPER_EVIDENCE_READY_DECISION,
        "hypothesis_id": plan["hypothesis_id"],
        "research_only": True,
        "public_data_only": True,
        "network_access": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
        "paper_plan_authorization": {
            "path": str(plan_path),
            "file_sha256": v3_history_plan.sha256_file(plan_path),
            "plan_hash": plan["plan_hash"],
        },
        "approval_authorization": {
            "path": str(approval_path),
            "file_sha256": v3_history_plan.sha256_file(approval_path),
            "approval_id": approval["approval_id"],
        },
        "selection_authorization": {
            "path": str(selection_path),
            "file_sha256": v3_history_plan.sha256_file(selection_path),
            "artifact_hash": selected["artifact_hash"],
            "probe_plan_path": str(probe_path),
            "probe_plan_file_sha256": v3_history_plan.sha256_file(probe_path),
            "probe_plan_hash": event_probe["plan_hash"],
        },
        "source_authorizations": source_authorizations,
        "event_contract": {
            "signal_day": signal_day,
            "entry_day": int(target["target_entry_day"]),
            "position_count": len(positions),
        },
        "positions": positions,
        "funding_settlement_coverage": funding_coverage,
        "maximum_authority": "PAPER_EVIDENCE_ONLY",
        "next_allowed_command": "fast-edge-membership-momentum-v2-paper-event",
    }
    contract_body["input_merkle_sha256"] = _canonical_hash(
        {
            "plan_hash": plan["plan_hash"],
            "approval_id": approval["approval_id"],
            "selection_hash": selected["artifact_hash"],
            "probe_plan_hash": event_probe["plan_hash"],
            "sources": source_authorizations,
        }
    )
    return contract_body


def build_paper_evidence_artifact(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
    selection_path: str | Path,
    expected_selection_hash: str,
    source_paths: Sequence[str | Path],
    output_path: str | Path | None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        approval_path=approval_path,
    )
    selected, resolved_selection, event_probe, resolved_probe = _validate_event_selection(
        plan,
        selection_path=selection_path,
        expected_selection_hash=expected_selection_hash,
    )
    sources: list[tuple[Mapping[str, Any], Path]] = []
    for path in source_paths:
        resolved_source = Path(path).expanduser().resolve()
        sources.append((validate_paper_source_artifact(resolved_source), resolved_source))
    frozen = _paper_evidence_contract(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        selected=selected,
        selection_path=resolved_selection,
        event_probe=event_probe,
        probe_path=resolved_probe,
        sources=sources,
    )
    artifact = {
        **frozen,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "artifact_hash": paper_evidence_hash(frozen),
        "frozen_contract": frozen,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, artifact)
    return artifact


def validate_paper_evidence_artifact(
    path: str | Path,
    expected_evidence_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    evidence = _read_json(resolved)
    frozen = evidence.get("frozen_contract")
    if (
        evidence.get("schema") != PAPER_EVIDENCE_SCHEMA
        or evidence.get("decision") != PAPER_EVIDENCE_READY_DECISION
        or evidence.get("final") is not True
        or not isinstance(frozen, Mapping)
    ):
        raise ValueError("unexpected momentum-v2 paper evidence artifact")
    computed = paper_evidence_hash(frozen)
    if (
        evidence.get("artifact_hash") != computed
        or (
            expected_evidence_hash is not None
            and _validate_hash(expected_evidence_hash, label="paper evidence hash")
            != computed
        )
        or not all(evidence.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 paper evidence hash mismatch")
    if _contains_manual_pnl(frozen):
        raise ValueError("manual PnL fields are forbidden in paper evidence")
    plan_auth = evidence.get("paper_plan_authorization")
    approval_auth = evidence.get("approval_authorization")
    selection_auth = evidence.get("selection_authorization")
    source_auths = evidence.get("source_authorizations")
    if not all(
        isinstance(value, Mapping)
        for value in (plan_auth, approval_auth, selection_auth)
    ) or not isinstance(source_auths, list):
        raise ValueError("momentum-v2 paper evidence provenance is missing")
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=str(plan_auth.get("path") or ""),
        expected_plan_hash=str(plan_auth.get("plan_hash") or ""),
        approval_path=str(approval_auth.get("path") or ""),
    )
    if (
        plan_auth.get("file_sha256") != v3_history_plan.sha256_file(resolved_plan)
        or approval_auth.get("file_sha256")
        != v3_history_plan.sha256_file(resolved_approval)
        or approval_auth.get("approval_id") != approval["approval_id"]
    ):
        raise ValueError("momentum-v2 paper evidence plan provenance mismatch")
    selected, resolved_selection, event_probe, resolved_probe = _validate_event_selection(
        plan,
        selection_path=str(selection_auth.get("path") or ""),
        expected_selection_hash=str(selection_auth.get("artifact_hash") or ""),
    )
    if (
        selection_auth.get("file_sha256")
        != v3_history_plan.sha256_file(resolved_selection)
        or Path(str(selection_auth.get("probe_plan_path") or "")).expanduser().resolve()
        != resolved_probe
        or selection_auth.get("probe_plan_file_sha256")
        != v3_history_plan.sha256_file(resolved_probe)
        or selection_auth.get("probe_plan_hash") != event_probe["plan_hash"]
    ):
        raise ValueError("momentum-v2 paper evidence selection provenance mismatch")
    sources: list[tuple[Mapping[str, Any], Path]] = []
    for authorization in source_auths:
        if not isinstance(authorization, Mapping):
            raise ValueError("momentum-v2 paper evidence source provenance is invalid")
        source_path = Path(str(authorization.get("path") or "")).expanduser().resolve()
        source = validate_paper_source_artifact(
            source_path,
            str(authorization.get("artifact_hash") or ""),
        )
        if (
            authorization.get("file_sha256")
            != v3_history_plan.sha256_file(source_path)
            or authorization.get("source_type") != source["source_type"]
        ):
            raise ValueError("momentum-v2 paper evidence source provenance mismatch")
        sources.append((source, source_path))
    rebuilt = _paper_evidence_contract(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        selected=selected,
        selection_path=resolved_selection,
        event_probe=event_probe,
        probe_path=resolved_probe,
        sources=sources,
    )
    if rebuilt != dict(frozen):
        raise ValueError("momentum-v2 paper evidence deterministic reconstruction mismatch")
    return evidence


def _event_contract(
    *,
    plan: Mapping[str, Any],
    plan_path: Path,
    approval: Mapping[str, Any],
    approval_path: Path,
    selected: Mapping[str, Any],
    selection_path: Path,
    event_probe: Mapping[str, Any],
    probe_path: Path,
    evidence: Mapping[str, Any],
    evidence_path: Path,
) -> dict[str, Any]:
    if _contains_manual_pnl(evidence):
        raise ValueError("manual PnL fields are forbidden in paper evidence")
    raw_positions = evidence.get("positions")
    if not isinstance(raw_positions, list):
        raise ValueError("paper evidence positions must be a list")
    funding_coverage = _finite(
        evidence.get("funding_settlement_coverage"),
        label="funding settlement coverage",
    )
    if funding_coverage < 0.98 or funding_coverage > 1.0:
        raise ValueError("funding settlement coverage is below the frozen gate")

    selected_rows = selected["selected_positions"]
    selected_by_asset = {
        str(row["canonical_asset_id"]): dict(row) for row in selected_rows
    }
    evidence_by_asset: dict[str, Mapping[str, Any]] = {}
    for raw in raw_positions:
        if not isinstance(raw, Mapping):
            raise ValueError("paper position evidence must contain objects")
        asset = str(raw.get("canonical_asset_id") or "").strip()
        if not asset or asset in evidence_by_asset:
            raise ValueError("paper position evidence contains a duplicate or empty asset")
        evidence_by_asset[asset] = raw
    if set(evidence_by_asset) != set(selected_by_asset):
        raise ValueError("paper evidence positions differ from the causal selection")

    paper_contract = plan["paper_contract"]
    notional = _positive(
        paper_contract["notional_quote_per_asset"],
        label="notional quote per asset",
    )
    normal_cost_bps = _finite(
        plan["cost_contract"]["normal"]["total_bps"],
        label="normal total cost bps",
    )
    stress_cost_bps = _finite(
        plan["cost_contract"]["stress"]["total_bps"],
        label="stress total cost bps",
    )
    event_windows = event_probe.get("execution_contract", {}).get("windows")
    if not isinstance(event_windows, list) or not event_windows:
        raise ValueError("paper event execution windows are missing")
    first_window = event_windows[0]
    if not isinstance(first_window, Mapping):
        raise ValueError("paper event first execution window is invalid")
    entry_window_start = _timestamp(
        first_window.get("start_ts"),
        label="paper event entry window start",
    )
    entry_window_end = _timestamp(
        first_window.get("end_ts"),
        label="paper event entry window end",
    )
    hold_sec = int(paper_contract["hold_days"]) * DAY_SEC
    exit_window_start = entry_window_start + hold_sec
    exit_window_end = entry_window_end + hold_sec
    positions: list[dict[str, Any]] = []
    for asset in sorted(selected_by_asset):
        selected_row = selected_by_asset[asset]
        raw = evidence_by_asset[asset]
        expected_identity = {
            "canonical_asset_id": asset,
            "symbol": str(selected_row["symbol"]),
            "base": str(selected_row["base"]),
            "side": str(selected_row["side"]),
        }
        for key, expected_value in expected_identity.items():
            if str(raw.get(key) or "") != expected_value:
                raise ValueError(f"paper position identity mismatch: {asset} {key}")
        side = expected_identity["side"]
        if side not in {"long", "short"}:
            raise ValueError(f"unsupported paper position side: {side}")
        entry_ts = _timestamp(raw.get("entry_ts"), label=f"{asset} entry timestamp")
        exit_ts = _timestamp(raw.get("exit_ts"), label=f"{asset} exit timestamp")
        if not entry_window_start <= entry_ts < entry_window_end:
            raise ValueError(f"{asset} entry execution timestamp is outside the frozen window")
        if not exit_window_start <= exit_ts < exit_window_end:
            raise ValueError(f"{asset} exit execution timestamp is outside the frozen window")
        if exit_ts <= entry_ts:
            raise ValueError(f"{asset} exit execution timestamp is not after entry")
        entry_price = _positive(raw.get("entry_price"), label=f"{asset} entry price")
        exit_price = _positive(raw.get("exit_price"), label=f"{asset} exit price")
        declared_funding_rate_sum = _finite(
            raw.get("funding_rate_sum"),
            label=f"{asset} funding rate sum",
        )
        funding = _funding_settlement_evidence(
            {
                "funding_interval_sec": raw.get("funding_interval_sec"),
                "expected_settlement_count": raw.get(
                    "funding_expected_settlement_count"
                ),
                "settlements": raw.get("funding_settlements"),
            },
            label=asset,
        )
        if any(
            not entry_ts < int(item["ts"]) < exit_ts
            for item in funding["settlements"]
        ):
            raise ValueError(
                f"{asset} funding settlement escapes the actual holding interval"
            )
        if not math.isclose(
            declared_funding_rate_sum,
            float(funding["funding_rate_sum"]),
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError(f"{asset} funding sum differs from settlement rows")
        declared_settlement_count = int(raw.get("funding_settlement_count") or -1)
        declared_settlement_coverage = _finite(
            raw.get("funding_settlement_coverage"),
            label=f"{asset} funding settlement coverage",
        )
        if (
            declared_settlement_count != funding["observed_settlement_count"]
            or not math.isclose(
                declared_settlement_coverage,
                float(funding["settlement_coverage"]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise ValueError(f"{asset} funding settlement metrics mismatch")
        funding_rate_sum = float(funding["funding_rate_sum"])
        entry_execution = _validate_execution_metrics(
            raw.get("entry_execution"),
            label=f"{asset} entry",
            contract=paper_contract,
        )
        exit_execution = _validate_execution_metrics(
            raw.get("exit_execution"),
            label=f"{asset} exit",
            contract=paper_contract,
        )
        direction = 1.0 if side == "long" else -1.0
        raw_return = exit_price / entry_price - 1.0
        price_pnl = notional * direction * raw_return
        funding_pnl = notional * (-direction) * funding_rate_sum
        normal_cost = notional * normal_cost_bps / 10_000.0
        stress_cost = notional * stress_cost_bps / 10_000.0
        normal_net = price_pnl + funding_pnl - normal_cost
        stress_funding = funding_pnl if funding_pnl <= 0.0 else 0.0
        stress_net = price_pnl + stress_funding - stress_cost
        positions.append(
            {
                **expected_identity,
                "notional_quote": notional,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "funding_rate_sum": funding_rate_sum,
                "funding_interval_sec": funding["funding_interval_sec"],
                "funding_expected_settlement_count": funding[
                    "expected_settlement_count"
                ],
                "funding_settlement_count": funding["observed_settlement_count"],
                "funding_settlement_coverage": funding["settlement_coverage"],
                "entry_execution": entry_execution,
                "exit_execution": exit_execution,
                "price_pnl_quote": round(price_pnl, 12),
                "funding_pnl_quote": round(funding_pnl, 12),
                "normal_cost_quote": round(normal_cost, 12),
                "stress_cost_quote": round(stress_cost, 12),
                "normal_net_pnl_quote": round(normal_net, 12),
                "stress_net_pnl_quote": round(stress_net, 12),
            }
        )

    long_count = sum(row["side"] == "long" for row in positions)
    short_count = sum(row["side"] == "short" for row in positions)
    if long_count < 1 or long_count != short_count:
        raise ValueError("paper event requires balanced non-empty long/short buckets")
    derived_funding_coverage = min(
        float(row["funding_settlement_coverage"]) for row in positions
    )
    if not math.isclose(
        funding_coverage,
        derived_funding_coverage,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("paper event funding coverage differs from position evidence")
    target = selected["target_event_contract"]
    signal_day = int(target["target_signal_day"])
    entry_day = int(target["target_entry_day"])
    exit_day = entry_day + int(paper_contract["hold_days"])
    gross_notional = notional * len(positions)
    price_pnl = sum(float(row["price_pnl_quote"]) for row in positions)
    funding_pnl = sum(float(row["funding_pnl_quote"]) for row in positions)
    normal_cost = sum(float(row["normal_cost_quote"]) for row in positions)
    stress_cost = sum(float(row["stress_cost_quote"]) for row in positions)
    normal_net = sum(float(row["normal_net_pnl_quote"]) for row in positions)
    stress_net = sum(float(row["stress_net_pnl_quote"]) for row in positions)
    contract: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "final": True,
        "decision": EVENT_READY_DECISION,
        "hypothesis_id": plan["hypothesis_id"],
        "research_only": True,
        "public_data_only": True,
        "network_access": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
        "paper_plan_authorization": {
            "path": str(plan_path),
            "file_sha256": v3_history_plan.sha256_file(plan_path),
            "plan_hash": plan["plan_hash"],
        },
        "approval_authorization": {
            "path": str(approval_path),
            "file_sha256": v3_history_plan.sha256_file(approval_path),
            "approval_id": approval["approval_id"],
        },
        "selection_authorization": {
            "path": str(selection_path),
            "file_sha256": v3_history_plan.sha256_file(selection_path),
            "artifact_hash": selected["artifact_hash"],
            "probe_plan_path": str(probe_path),
            "probe_plan_file_sha256": v3_history_plan.sha256_file(probe_path),
            "probe_plan_hash": event_probe["plan_hash"],
        },
        "evidence_authorization": {
            "path": str(evidence_path),
            "file_sha256": v3_history_plan.sha256_file(evidence_path),
            "artifact_hash": evidence["artifact_hash"],
        },
        "event_contract": {
            "signal_day": signal_day,
            "entry_day": entry_day,
            "exit_day": exit_day,
            "hold_days": int(paper_contract["hold_days"]),
            "event_cadence_days": int(paper_contract["event_cadence_days"]),
            "position_count": len(positions),
            "long_count": long_count,
            "short_count": short_count,
            "notional_quote_per_asset": notional,
            "gross_notional_quote": gross_notional,
            "funding_settlement_coverage": funding_coverage,
            "entry_execution_window_start_ts": entry_window_start,
            "entry_execution_window_end_ts": entry_window_end,
            "exit_execution_window_start_ts": exit_window_start,
            "exit_execution_window_end_ts": exit_window_end,
        },
        "positions": positions,
        "metrics": {
            "price_pnl_quote": round(price_pnl, 12),
            "funding_pnl_quote": round(funding_pnl, 12),
            "normal_cost_quote": round(normal_cost, 12),
            "stress_cost_quote": round(stress_cost, 12),
            "normal_net_pnl_quote": round(normal_net, 12),
            "stress_net_pnl_quote": round(stress_net, 12),
            "normal_net_expectancy_bps": round(
                normal_net / gross_notional * 10_000.0,
                8,
            ),
            "stress_net_expectancy_bps": round(
                stress_net / gross_notional * 10_000.0,
                8,
            ),
        },
        "data_quality_violations": 0,
        "execution_quality_violations": 0,
        "reconciliation_violations": 0,
        "kill_switch_triggered": False,
        "maximum_authority": "PAPER_EVENT_ONLY",
        "next_allowed_command": "fast-edge-membership-momentum-v2-paper-apply",
    }
    contract["input_merkle_sha256"] = _canonical_hash(
        {
            "plan_hash": plan["plan_hash"],
            "approval_id": approval["approval_id"],
            "selection_hash": selected["artifact_hash"],
            "probe_plan_hash": event_probe["plan_hash"],
            "evidence_hash": evidence["artifact_hash"],
            "evidence_file_sha256": v3_history_plan.sha256_file(evidence_path),
        }
    )
    return contract


def build_paper_event(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
    selection_path: str | Path,
    expected_selection_hash: str,
    evidence_path: str | Path,
    expected_evidence_hash: str,
    output_path: str | Path | None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        approval_path=approval_path,
    )
    selected, resolved_selection, event_probe, resolved_probe = _validate_event_selection(
        plan,
        selection_path=selection_path,
        expected_selection_hash=expected_selection_hash,
    )
    resolved_evidence = Path(evidence_path).expanduser().resolve()
    evidence = validate_paper_evidence_artifact(
        resolved_evidence,
        expected_evidence_hash,
    )
    if (
        evidence["paper_plan_authorization"]["plan_hash"] != plan["plan_hash"]
        or evidence["approval_authorization"]["approval_id"]
        != approval["approval_id"]
        or evidence["selection_authorization"]["artifact_hash"]
        != selected["artifact_hash"]
    ):
        raise ValueError("paper evidence belongs to another plan, approval, or selection")
    contract = _event_contract(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        selected=selected,
        selection_path=resolved_selection,
        event_probe=event_probe,
        probe_path=resolved_probe,
        evidence=evidence,
        evidence_path=resolved_evidence,
    )
    event_hash = _canonical_hash(contract)
    event = {
        **contract,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "event_hash": event_hash,
        "frozen_contract": contract,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, event)
    return event


def validate_paper_event(
    path: str | Path,
    expected_event_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    event = _read_json(resolved)
    frozen = event.get("frozen_contract")
    if (
        event.get("schema") != EVENT_SCHEMA
        or event.get("decision") != EVENT_READY_DECISION
        or not isinstance(frozen, Mapping)
    ):
        raise ValueError("unexpected momentum-v2 paper event artifact")
    computed = _canonical_hash(frozen)
    if (
        event.get("event_hash") != computed
        or (expected_event_hash is not None and str(expected_event_hash) != computed)
        or not all(event.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 paper event hash mismatch")
    plan_auth = event.get("paper_plan_authorization")
    approval_auth = event.get("approval_authorization")
    selection_auth = event.get("selection_authorization")
    evidence_auth = event.get("evidence_authorization")
    if not all(
        isinstance(value, Mapping)
        for value in (plan_auth, approval_auth, selection_auth, evidence_auth)
    ):
        raise ValueError("momentum-v2 paper event provenance is missing")
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=str(plan_auth.get("path") or ""),
        expected_plan_hash=str(plan_auth.get("plan_hash") or ""),
        approval_path=str(approval_auth.get("path") or ""),
    )
    if (
        plan_auth.get("file_sha256") != v3_history_plan.sha256_file(resolved_plan)
        or approval_auth.get("file_sha256")
        != v3_history_plan.sha256_file(resolved_approval)
        or approval_auth.get("approval_id") != approval["approval_id"]
    ):
        raise ValueError("momentum-v2 paper event plan/approval provenance mismatch")
    selected, resolved_selection, event_probe, resolved_probe = _validate_event_selection(
        plan,
        selection_path=str(selection_auth.get("path") or ""),
        expected_selection_hash=str(selection_auth.get("artifact_hash") or ""),
    )
    if (
        selection_auth.get("file_sha256")
        != v3_history_plan.sha256_file(resolved_selection)
        or Path(str(selection_auth.get("probe_plan_path") or "")).expanduser().resolve()
        != resolved_probe
        or selection_auth.get("probe_plan_file_sha256")
        != v3_history_plan.sha256_file(resolved_probe)
        or selection_auth.get("probe_plan_hash") != event_probe["plan_hash"]
    ):
        raise ValueError("momentum-v2 paper event selection provenance mismatch")
    resolved_evidence = Path(
        str(evidence_auth.get("path") or "")
    ).expanduser().resolve()
    evidence = validate_paper_evidence_artifact(
        resolved_evidence,
        str(evidence_auth.get("artifact_hash") or ""),
    )
    if (
        evidence_auth.get("file_sha256")
        != v3_history_plan.sha256_file(resolved_evidence)
        or evidence["paper_plan_authorization"]["plan_hash"] != plan["plan_hash"]
        or evidence["approval_authorization"]["approval_id"]
        != approval["approval_id"]
        or evidence["selection_authorization"]["artifact_hash"]
        != selected["artifact_hash"]
    ):
        raise ValueError("momentum-v2 paper event evidence provenance mismatch")
    rebuilt = _event_contract(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        selected=selected,
        selection_path=resolved_selection,
        event_probe=event_probe,
        probe_path=resolved_probe,
        evidence=evidence,
        evidence_path=resolved_evidence,
    )
    if rebuilt != dict(frozen):
        raise ValueError("momentum-v2 paper event deterministic reconstruction mismatch")
    return event


def _ledger_row_hash(row: Mapping[str, Any]) -> str:
    return _canonical_hash({key: value for key, value in row.items() if key != "row_hash"})


def _read_ledger(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"paper ledger is missing: {target}")
    rows: list[dict[str, Any]] = []
    previous = ZERO_HASH
    for sequence, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("paper ledger row is not an object")
        if (
            row.get("schema") != LEDGER_EVENT_SCHEMA
            or int(row.get("sequence") or 0) != sequence
            or row.get("previous_hash") != previous
            or row.get("row_hash") != _ledger_row_hash(row)
        ):
            raise ValueError(f"paper ledger hash chain mismatch at sequence {sequence}")
        rows.append(row)
        previous = str(row["row_hash"])
    if not rows or rows[0].get("event_type") != "initialize":
        raise ValueError("paper ledger initialization event is missing")
    return rows


def _append_ledger_row(
    path: str | Path,
    *,
    event_type: str,
    plan_hash: str,
    approval_id: str,
    details: Mapping[str, Any],
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    rows = _read_ledger(target) if target.exists() else []
    row: dict[str, Any] = {
        "schema": LEDGER_EVENT_SCHEMA,
        "sequence": len(rows) + 1,
        "event_type": event_type,
        "created_at_utc": created_at_utc or _utc_now(),
        "plan_hash": plan_hash,
        "approval_id": approval_id,
        "previous_hash": rows[-1]["row_hash"] if rows else ZERO_HASH,
        "details": dict(details),
    }
    row["row_hash"] = _ledger_row_hash(row)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return row


def _state_hash(state: Mapping[str, Any]) -> str:
    return _canonical_hash({key: value for key, value in state.items() if key != "state_hash"})


def _verify_ledger_sources(rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        details = row.get("details")
        if not isinstance(details, Mapping):
            raise ValueError("paper ledger details are missing")
        if row.get("event_type") != "paper_event":
            continue
        event_path = Path(str(details.get("event_path") or "")).expanduser().resolve()
        event = validate_paper_event(event_path, str(details.get("event_hash") or ""))
        if details.get("event_file_sha256") != v3_history_plan.sha256_file(event_path):
            raise ValueError("paper ledger event file provenance mismatch")
        if details.get("signal_day") != event["event_contract"]["signal_day"]:
            raise ValueError("paper ledger event signal day mismatch")


def _project_state(
    *,
    plan: Mapping[str, Any],
    plan_path: Path,
    approval: Mapping[str, Any],
    approval_path: Path,
    rows: Sequence[Mapping[str, Any]],
    ledger_path: Path,
    updated_at_utc: str,
) -> dict[str, Any]:
    for row in rows:
        if row.get("plan_hash") != plan["plan_hash"]:
            raise ValueError("paper ledger contains another plan hash")
        if row.get("approval_id") != approval["approval_id"]:
            raise ValueError("paper ledger contains another approval id")
    _verify_ledger_sources(rows)
    event_rows = [row for row in rows if row.get("event_type") == "paper_event"]
    incident_rows = [row for row in rows if row.get("event_type") == "incident"]
    signal_days: list[int] = []
    event_hashes: list[str] = []
    normal_values: list[float] = []
    stress_values: list[float] = []
    for row in event_rows:
        details = row["details"]
        signal_days.append(int(details["signal_day"]))
        event_hashes.append(str(details["event_hash"]))
        normal_values.append(float(details["normal_net_pnl_quote"]))
        stress_values.append(float(details["stress_net_pnl_quote"]))
    if signal_days != sorted(signal_days) or len(signal_days) != len(set(signal_days)):
        raise ValueError("paper ledger signal days are not unique and chronological")
    if len(event_hashes) != len(set(event_hashes)):
        raise ValueError("paper ledger contains duplicate event hashes")
    count = len(event_rows)
    total = sum(normal_values)
    stress_total = sum(stress_values)
    gross_profit = sum(value for value in normal_values if value > 0.0)
    gross_loss = -sum(value for value in normal_values if value < 0.0)
    profit_factor = None if gross_loss == 0.0 else gross_profit / gross_loss
    concentration = 0.0
    if gross_profit > 0.0:
        concentration = max([value for value in normal_values if value > 0.0], default=0.0) / gross_profit
    minimum = int(plan["paper_contract"]["minimum_independent_events"])
    gates = plan["paper_contract"]["acceptance_gates"]
    violations = {
        "data_quality": sum(
            int((row.get("details") or {}).get("incident_type") == "data_quality")
            for row in incident_rows
        ),
        "execution_quality": sum(
            int((row.get("details") or {}).get("incident_type") == "execution_quality")
            for row in incident_rows
        ),
        "reconciliation": sum(
            int((row.get("details") or {}).get("incident_type") == "reconciliation")
            for row in incident_rows
        ),
        "kill_switch": len(incident_rows),
    }
    profit_factor_pass = gross_profit > 0.0 and (
        gross_loss == 0.0 or (profit_factor is not None and profit_factor >= float(gates["profit_factor_gte"]))
    )
    eligible = (
        count >= minimum
        and total > float(gates["paper_total_net_pnl_quote_gt"])
        and total / count > float(gates["paper_total_net_expectancy_quote_gt"])
        and profit_factor_pass
        and stress_total >= float(gates["stress_net_pnl_quote_gte"])
        and concentration <= float(gates["maximum_single_event_positive_pnl_share"])
        and not any(violations.values())
    )
    if incident_rows:
        status = PAPER_HALTED_DECISION
    elif count >= minimum:
        status = LIVE_REVIEW_ELIGIBLE_DECISION if eligible else PAPER_REJECTED_DECISION
    else:
        status = PAPER_ACTIVE_DECISION
    state: dict[str, Any] = {
        "schema": STATE_SCHEMA,
        "updated_at_utc": updated_at_utc,
        "plan_path": str(plan_path),
        "plan_file_sha256": v3_history_plan.sha256_file(plan_path),
        "plan_hash": plan["plan_hash"],
        "approval_path": str(approval_path),
        "approval_file_sha256": v3_history_plan.sha256_file(approval_path),
        "approval_id": approval["approval_id"],
        "ledger_path": str(ledger_path),
        "ledger_file_sha256": v3_history_plan.sha256_file(ledger_path),
        "last_ledger_sequence": int(rows[-1]["sequence"]),
        "last_ledger_hash": rows[-1]["row_hash"],
        "independent_paper_event_count": count,
        "minimum_independent_paper_events": minimum,
        "unique_signal_days": len(set(signal_days)),
        "paper_total_net_pnl_quote": round(total, 12),
        "paper_total_net_expectancy_quote": round(total / count, 12) if count else 0.0,
        "stress_net_pnl_quote": round(stress_total, 12),
        "gross_profit_quote": round(gross_profit, 12),
        "gross_loss_quote": round(gross_loss, 12),
        "profit_factor": round(profit_factor, 12) if profit_factor is not None else None,
        "profit_factor_infinite": gross_profit > 0.0 and gross_loss == 0.0,
        "maximum_single_event_positive_pnl_share": round(concentration, 12),
        "violations": violations,
        "status": status,
        "paper_forward_active": status == PAPER_ACTIVE_DECISION,
        "kill_switch_active": status == PAPER_HALTED_DECISION,
        "research_only": True,
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
        "maximum_authority": (
            "LIVE_REVIEW_ELIGIBLE"
            if status == LIVE_REVIEW_ELIGIBLE_DECISION
            else "PAPER_FORWARD_ONLY"
        ),
        "requires_separate_user_live_review": status == LIVE_REVIEW_ELIGIBLE_DECISION,
        "next_allowed_command": (
            "request-separate-live-review"
            if status == LIVE_REVIEW_ELIGIBLE_DECISION
            else (
                "none_membership_momentum_v2_paper_terminal"
                if status in {PAPER_HALTED_DECISION, PAPER_REJECTED_DECISION}
                else "fast-edge-membership-momentum-v2-paper-event"
            )
        ),
    }
    state["state_hash"] = _state_hash(state)
    return state


def _load_state(path: str | Path) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).expanduser().resolve()
    state = _read_json(resolved)
    if state.get("schema") != STATE_SCHEMA:
        raise ValueError("momentum-v2 paper state schema mismatch")
    if state.get("state_hash") != _state_hash(state):
        raise ValueError("momentum-v2 paper state hash mismatch")
    return state, resolved


def initialize_paper_state(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
    ledger_path: str | Path,
    state_path: str | Path,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        approval_path=approval_path,
    )
    resolved_ledger = Path(ledger_path).expanduser().resolve()
    resolved_state = Path(state_path).expanduser().resolve()
    if resolved_ledger.exists() or resolved_state.exists():
        raise FileExistsError("momentum-v2 paper ledger/state already exists")
    timestamp = generated_at_utc or _utc_now()
    _append_ledger_row(
        resolved_ledger,
        event_type="initialize",
        plan_hash=plan["plan_hash"],
        approval_id=approval["approval_id"],
        details={
            "paper_forward_started": True,
            "network_collector_started": False,
            "live_orders": False,
            "private_api_keys": False,
        },
        created_at_utc=timestamp,
    )
    rows = _read_ledger(resolved_ledger)
    state = _project_state(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        rows=rows,
        ledger_path=resolved_ledger,
        updated_at_utc=timestamp,
    )
    _atomic_write_json(resolved_state, state)
    return state


def apply_paper_event(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
    event_path: str | Path,
    expected_event_hash: str,
    ledger_path: str | Path,
    state_path: str | Path,
    applied_at_utc: str | None = None,
) -> dict[str, Any]:
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        approval_path=approval_path,
    )
    state, resolved_state = _load_state(state_path)
    resolved_ledger = Path(ledger_path).expanduser().resolve()
    rows = _read_ledger(resolved_ledger)
    if (
        state.get("plan_hash") != plan["plan_hash"]
        or state.get("approval_id") != approval["approval_id"]
    ):
        raise ValueError("paper state belongs to another plan or approval")
    if state.get("status") != PAPER_ACTIVE_DECISION:
        raise ValueError(f"paper state is terminal: {state.get('status')}")
    resolved_event = Path(event_path).expanduser().resolve()
    event = validate_paper_event(resolved_event, expected_event_hash)
    if (
        event["paper_plan_authorization"]["plan_hash"] != plan["plan_hash"]
        or event["approval_authorization"]["approval_id"] != approval["approval_id"]
    ):
        raise ValueError("paper event belongs to another plan or approval")
    event_hash = event["event_hash"]
    signal_day = int(event["event_contract"]["signal_day"])
    existing_events = [row for row in rows if row.get("event_type") == "paper_event"]
    if any(
        (row.get("details") or {}).get("event_hash") == event_hash
        or int((row.get("details") or {}).get("signal_day") or -1) == signal_day
        for row in existing_events
    ):
        raise ValueError("duplicate paper event or signal day")
    if existing_events and signal_day <= int(existing_events[-1]["details"]["signal_day"]):
        raise ValueError("paper event is not chronological")
    metrics = event["metrics"]
    timestamp = applied_at_utc or _utc_now()
    _append_ledger_row(
        resolved_ledger,
        event_type="paper_event",
        plan_hash=plan["plan_hash"],
        approval_id=approval["approval_id"],
        details={
            "event_path": str(resolved_event),
            "event_file_sha256": v3_history_plan.sha256_file(resolved_event),
            "event_hash": event_hash,
            "signal_day": signal_day,
            "entry_day": int(event["event_contract"]["entry_day"]),
            "exit_day": int(event["event_contract"]["exit_day"]),
            "normal_net_pnl_quote": float(metrics["normal_net_pnl_quote"]),
            "stress_net_pnl_quote": float(metrics["stress_net_pnl_quote"]),
        },
        created_at_utc=timestamp,
    )
    updated_rows = _read_ledger(resolved_ledger)
    updated = _project_state(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        rows=updated_rows,
        ledger_path=resolved_ledger,
        updated_at_utc=timestamp,
    )
    _atomic_write_json(resolved_state, updated)
    return updated


def record_paper_incident(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
    ledger_path: str | Path,
    state_path: str | Path,
    incident_type: str,
    reason: str,
    recorded_at_utc: str | None = None,
) -> dict[str, Any]:
    allowed = {"data_quality", "execution_quality", "reconciliation", "manual_stop"}
    normalized_type = str(incident_type).strip().lower()
    normalized_reason = str(reason).strip()
    if normalized_type not in allowed or not normalized_reason:
        raise ValueError("paper incident type/reason is invalid")
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        approval_path=approval_path,
    )
    state, resolved_state = _load_state(state_path)
    if state.get("status") != PAPER_ACTIVE_DECISION:
        raise ValueError(f"paper state is terminal: {state.get('status')}")
    resolved_ledger = Path(ledger_path).expanduser().resolve()
    timestamp = recorded_at_utc or _utc_now()
    _append_ledger_row(
        resolved_ledger,
        event_type="incident",
        plan_hash=plan["plan_hash"],
        approval_id=approval["approval_id"],
        details={"incident_type": normalized_type, "reason": normalized_reason},
        created_at_utc=timestamp,
    )
    rows = _read_ledger(resolved_ledger)
    updated = _project_state(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        rows=rows,
        ledger_path=resolved_ledger,
        updated_at_utc=timestamp,
    )
    _atomic_write_json(resolved_state, updated)
    return updated


def reconcile_paper_state(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
    ledger_path: str | Path,
    state_path: str | Path,
) -> dict[str, Any]:
    plan, resolved_plan, approval, resolved_approval = _validate_plan_and_approval(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        approval_path=approval_path,
    )
    state, resolved_state = _load_state(state_path)
    resolved_ledger = Path(ledger_path).expanduser().resolve()
    rows = _read_ledger(resolved_ledger)
    expected = _project_state(
        plan=plan,
        plan_path=resolved_plan,
        approval=approval,
        approval_path=resolved_approval,
        rows=rows,
        ledger_path=resolved_ledger,
        updated_at_utc=str(state["updated_at_utc"]),
    )
    matched = state == expected
    return {
        "schema": "trading_mvp_gate_membership_momentum_v2_paper_reconciliation_v1",
        "matched": matched,
        "state_path": str(resolved_state),
        "state_hash": state["state_hash"],
        "expected_state_hash": expected["state_hash"],
        "ledger_path": str(resolved_ledger),
        "ledger_rows": len(rows),
        "last_ledger_hash": rows[-1]["row_hash"],
        "status": state["status"],
    }


def paper_status(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    approval_path: str | Path,
    ledger_path: str | Path,
    state_path: str | Path,
) -> dict[str, Any]:
    state, _resolved = _load_state(state_path)
    reconciliation = reconcile_paper_state(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        approval_path=approval_path,
        ledger_path=ledger_path,
        state_path=state_path,
    )
    return {**state, "reconciliation": reconciliation}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate membership-momentum-v2 hash-bound paper state"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    approve = subparsers.add_parser("approve")
    approve.add_argument("--plan", required=True)
    approve.add_argument("--expected-plan-hash", required=True)
    approve.add_argument("--output", required=True)
    approve.add_argument("--confirmed-paper-forward", action="store_true")
    initialize = subparsers.add_parser("init")
    build_funding_raw = subparsers.add_parser("build-funding-raw")
    build_funding_raw.add_argument("--entry-source", required=True)
    build_funding_raw.add_argument("--expected-entry-source-hash", required=True)
    build_funding_raw.add_argument("--exit-source", required=True)
    build_funding_raw.add_argument("--expected-exit-source-hash", required=True)
    build_funding_raw.add_argument("--funding-history", action="append", required=True)
    build_funding_raw.add_argument("--raw-input-output", required=True)
    build_funding_raw.add_argument("--raw-manifest-output", required=True)
    build_execution_raw = subparsers.add_parser("build-execution-raw")
    build_execution_raw.add_argument("--plan", required=True)
    build_execution_raw.add_argument("--expected-plan-hash", required=True)
    build_execution_raw.add_argument("--approval", required=True)
    build_execution_raw.add_argument("--selection", required=True)
    build_execution_raw.add_argument("--expected-selection-hash", required=True)
    build_execution_raw.add_argument(
        "--boundary", choices=("entry", "exit"), required=True
    )
    build_execution_raw.add_argument(
        "--window-manifest", action="append", required=True
    )
    build_execution_raw.add_argument("--raw-input-output", required=True)
    build_execution_raw.add_argument("--raw-manifest-output", required=True)
    build_source = subparsers.add_parser("build-source")
    build_source.add_argument("--raw-manifest", required=True)
    build_source.add_argument("--expected-raw-manifest-hash", required=True)
    build_source.add_argument("--output", required=True)
    build_evidence = subparsers.add_parser("build-evidence")
    build_event = subparsers.add_parser("build-event")
    apply_event = subparsers.add_parser("apply")
    status = subparsers.add_parser("status")
    incident = subparsers.add_parser("incident")
    for command in (
        initialize,
        build_evidence,
        build_event,
        apply_event,
        status,
        incident,
    ):
        command.add_argument("--plan", required=True)
        command.add_argument("--expected-plan-hash", required=True)
        command.add_argument("--approval", required=True)
    for command in (initialize, apply_event, status, incident):
        command.add_argument("--ledger", required=True)
        command.add_argument("--state", required=True)
    for command in (build_evidence, build_event):
        command.add_argument("--selection", required=True)
        command.add_argument("--expected-selection-hash", required=True)
        command.add_argument("--output", required=True)
    build_evidence.add_argument("--source", action="append", required=True)
    build_event.add_argument("--evidence", required=True)
    build_event.add_argument("--expected-evidence-hash", required=True)
    apply_event.add_argument("--event", required=True)
    apply_event.add_argument("--expected-event-hash", required=True)
    incident.add_argument(
        "--incident-type",
        required=True,
        choices=("data_quality", "execution_quality", "reconciliation", "manual_stop"),
    )
    incident.add_argument("--reason", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "approve":
        result = create_paper_approval(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
            confirmed_paper_forward=args.confirmed_paper_forward,
        )
    elif args.command == "init":
        result = initialize_paper_state(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            approval_path=args.approval,
            ledger_path=args.ledger,
            state_path=args.state,
        )
    elif args.command == "build-funding-raw":
        result = build_paper_funding_raw_source_manifest(
            entry_source_path=args.entry_source,
            expected_entry_source_hash=args.expected_entry_source_hash,
            exit_source_path=args.exit_source,
            expected_exit_source_hash=args.expected_exit_source_hash,
            funding_history_paths=args.funding_history,
            raw_input_path=args.raw_input_output,
            raw_manifest_path=args.raw_manifest_output,
        )
    elif args.command == "build-execution-raw":
        result = build_paper_execution_raw_source_manifest(
            paper_plan_path=args.plan,
            expected_paper_plan_hash=args.expected_plan_hash,
            approval_path=args.approval,
            selection_path=args.selection,
            expected_selection_hash=args.expected_selection_hash,
            boundary=args.boundary,
            window_manifest_paths=args.window_manifest,
            raw_input_path=args.raw_input_output,
            raw_manifest_path=args.raw_manifest_output,
        )
    elif args.command == "build-source":
        result = build_paper_source_artifact(
            raw_manifest_path=args.raw_manifest,
            expected_raw_manifest_hash=args.expected_raw_manifest_hash,
            output_path=args.output,
        )
    elif args.command == "build-evidence":
        result = build_paper_evidence_artifact(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            approval_path=args.approval,
            selection_path=args.selection,
            expected_selection_hash=args.expected_selection_hash,
            source_paths=args.source,
            output_path=args.output,
        )
    elif args.command == "build-event":
        result = build_paper_event(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            approval_path=args.approval,
            selection_path=args.selection,
            expected_selection_hash=args.expected_selection_hash,
            evidence_path=args.evidence,
            expected_evidence_hash=args.expected_evidence_hash,
            output_path=args.output,
        )
    elif args.command == "apply":
        result = apply_paper_event(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            approval_path=args.approval,
            event_path=args.event,
            expected_event_hash=args.expected_event_hash,
            ledger_path=args.ledger,
            state_path=args.state,
        )
    elif args.command == "incident":
        result = record_paper_incident(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            approval_path=args.approval,
            ledger_path=args.ledger,
            state_path=args.state,
            incident_type=args.incident_type,
            reason=args.reason,
        )
    else:
        result = paper_status(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            approval_path=args.approval,
            ledger_path=args.ledger,
            state_path=args.state,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
