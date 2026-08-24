"""Bounded public-data automation helpers for the pre-IPO perpetual track.

The visible PowerShell orchestrator owns cadence, process visibility and the
writer claim.  This module owns one bounded discovery/snapshot tick, append-only
storage, manifest publication and retry state.  A failed venue is retained in
``pending_retry`` for the next interval; no tight-loop retry is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from preipo_adapters import (
    VENUES,
    PublicPreIPOAdapter,
    build_public_adapters,
    normalize_market_snapshot,
)
from preipo_raw_event_store import RawEventStore
from adaptive_cadence import (
    SEARCH_INTERVAL_SEC,
    SCHEDULED_INTERVAL_SEC,
    decide_cadence,
)
from premarket_temporal_anchor import (
    ANCHOR_CONTRACT_LAUNCH,
    ANCHOR_TRANSITION,
    anchor_observation,
    resolve_anchor,
    select_cadence_anchor,
)
from global_market_writer_claim import consume_worker_handoff_receipt


AUTOMATION_ID = "zolotyaylopata-preipo-perpetual-event-monitor"
STATE_SCHEMA = "trading_mvp_preipo_perpetual_event_automation_state_v1"
ATTEMPT_SCHEMA = "trading_mvp_preipo_perpetual_event_automation_attempt_v1"
TERMINAL_RECEIPT_SCHEMA = "trading_mvp_preipo_perpetual_event_terminal_intent_receipt_v1"
SCHEDULE_INTERVAL_SEC = SEARCH_INTERVAL_SEC
CAPTURE_DURATION_SEC = 5 * 60
# Backwards-compatible alias for callers that still use the old name.  The
# value now represents the scheduler interval, never the WS capture window.
CADENCE_SEC = SCHEDULE_INTERVAL_SEC


@dataclass(frozen=True)
class AutomationPaths:
    state_path: Path
    ledger_path: Path
    claim_path: Path
    launch_path: Path
    worker_error_path: Path
    events_path: Path
    manifest_path: Path


@dataclass
class WriterClaim:
    path: Path
    stream: Any


def utc_iso(ts: float | None = None) -> str:
    value = datetime.now(timezone.utc) if ts is None else datetime.fromtimestamp(float(ts), timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _default_state() -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "automation_id": AUTOMATION_ID,
        "cadence_seconds": SEARCH_INTERVAL_SEC,
        "cadence_stage": "SEARCH",
        "cadence_reason": "initial_search",
        "event_eta_utc": None,
        "official_confirmation": False,
        "exact_timestamp": False,
        "wake_interval_seconds": SCHEDULED_INTERVAL_SEC,
        "schedule_interval_seconds": SCHEDULE_INTERVAL_SEC,
        "capture_duration_seconds": CAPTURE_DURATION_SEC,
        "status": "IDLE",
        "pending_retry": False,
        "retry_count": 0,
        "attempt_count": 0,
        "next_interval_at_utc": None,
        "last_attempt_id": None,
        "last_started_at_utc": None,
        "last_finished_at_utc": None,
        "worker_pid": None,
        "worker_process_started_at_utc": None,
        "outcomes": {},
        "accrual": {"contracts_seen": 0, "events_written": 0, "complete_events": 0, "official_events": 0, "proxy_events": 0},
        "last_error": None,
        "updated_at_utc": utc_iso(),
    }


def load_state(paths: AutomationPaths) -> dict[str, Any]:
    if not paths.state_path.exists():
        return _default_state()
    try:
        payload = json.loads(paths.state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"pre-IPO automation state unreadable: {exc}") from exc
    if payload.get("schema") != STATE_SCHEMA:
        raise RuntimeError("pre-IPO automation state schema mismatch")
    return payload


def save_state(paths: AutomationPaths, state: Mapping[str, Any]) -> None:
    payload = dict(state)
    payload["updated_at_utc"] = utc_iso()
    _atomic_write(paths.state_path, payload)


def append_attempt(paths: AutomationPaths, payload: Mapping[str, Any]) -> None:
    paths.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"schema": ATTEMPT_SCHEMA, **dict(payload)}
    with paths.ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _terminal_receipt_path(paths: AutomationPaths, attempt_id: str) -> Path:
    if not attempt_id or Path(attempt_id).name != attempt_id:
        raise ValueError("invalid terminal receipt attempt_id")
    return paths.ledger_path.parent / "terminal-receipts" / f"{attempt_id}.json"


def _write_terminal_receipt(
    paths: AutomationPaths,
    *,
    attempt_id: str,
    status: str,
    outcomes: Mapping[str, Any],
    reason: str | None,
    pending_retry: bool,
    next_interval_at_utc: str,
    expected_manifest_path: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Atomically create an immutable terminal intent receipt."""

    receipt_path = _terminal_receipt_path(paths, attempt_id)
    core = {
        "schema": TERMINAL_RECEIPT_SCHEMA,
        "automation_id": AUTOMATION_ID,
        "attempt_id": attempt_id,
        "status": "PREPARED",
        "intended_status": status,
        "outcomes": dict(outcomes),
        "reason": reason,
        "pending_retry": bool(pending_retry),
        "next_interval_at_utc": next_interval_at_utc,
        "expected_manifest_path": expected_manifest_path,
        "expected_manifest_sha256": expected_manifest_sha256,
    }
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt = {**core, "receipt_sha256": hashlib.sha256(canonical).hexdigest()}

    def existing_or_conflict() -> dict[str, Any]:
        try:
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"terminal receipt conflict: unreadable existing receipt: {exc}") from exc
        if existing != receipt:
            raise RuntimeError(f"terminal receipt conflict: {receipt_path}")
        return existing

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        return existing_or_conflict()

    encoded = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temp_path = receipt_path.with_name(f".{receipt_path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with temp_path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, receipt_path)
        except FileExistsError:
            return existing_or_conflict()
    finally:
        temp_path.unlink(missing_ok=True)
    return receipt


def next_interval_iso(now_ts: float | None = None, interval_sec: int = SCHEDULE_INTERVAL_SEC) -> str:
    base = time.time() if now_ts is None else float(now_ts)
    return utc_iso(base + int(interval_sec))


def mark_retry_next_interval(
    state: Mapping[str, Any],
    reason: str,
    *,
    now_ts: float | None = None,
    interval_sec: int = SCHEDULE_INTERVAL_SEC,
    state_path: Path | None = None,
) -> tuple[dict[str, Any], str]:
    updated = dict(state)
    next_at = next_interval_iso(now_ts, interval_sec)
    updated.update(
        {
            "status": "RETRY_NEXT_INTERVAL",
            "pending_retry": True,
            "retry_count": int(updated.get("retry_count", 0)) + 1,
            "next_interval_at_utc": next_at,
            "last_error": reason,
        }
    )
    if state_path is not None:
        _atomic_write(state_path, updated)
    return updated, next_at


def acquire_writer_claim(paths: AutomationPaths, *, pid: int | None = None) -> WriterClaim | None:
    paths.claim_path.parent.mkdir(parents=True, exist_ok=True)
    stream = None
    try:
        stream = paths.claim_path.open("x", encoding="utf-8", newline="\n")
        payload = {
            "schema": "trading_mvp_preipo_perpetual_event_claim_v1",
            "automation_id": AUTOMATION_ID,
            "pid": int(pid or os.getpid()),
            "claimed_at_utc": utc_iso(),
        }
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        return WriterClaim(paths.claim_path, stream)
    except FileExistsError:
        if stream is not None:
            stream.close()
        return None
    except OSError:
        if stream is not None:
            stream.close()
        raise


def release_writer_claim(paths: AutomationPaths, claim: WriterClaim) -> None:
    claim.stream.close()
    try:
        paths.claim_path.unlink()
    except FileNotFoundError:
        pass


def _contract_metadata(contract: Any, *, received_ts: float) -> dict[str, Any]:
    return {
        "venue": contract.venue,
        "contract_id": contract.contract_id,
        "asset_class": contract.asset_class,
        "underlying_symbol": contract.underlying_symbol,
        "quote": contract.quote,
        "lifecycle_status": contract.lifecycle_status,
        "phase": contract.phase,
        "source_class": contract.source_class,
        "received_ts": received_ts,
    }


def capture_websocket_events(
    adapter: PublicPreIPOAdapter,
    contract: Any,
    store: RawEventStore,
    *,
    duration_sec: float = CAPTURE_DURATION_SEC,
    received_clock: Any = time.time,
) -> dict[str, Any]:
    """Capture a bounded public WS slice; failures are deferred, not retried inline."""

    if duration_sec <= 0:
        return {"status": "SKIPPED", "events_written": 0, "reason": "duration_sec_not_positive"}
    try:
        import websocket  # type: ignore
    except ImportError as exc:
        return {"status": "RETRY_NEXT_INTERVAL", "events_written": 0, "reason": f"websocket_dependency_missing:{exc}"}
    subscriptions = adapter.websocket_subscriptions(contract)
    if not subscriptions:
        return {"status": "SKIPPED", "events_written": 0, "reason": "no_public_subscriptions"}
    socket = None
    written = 0
    started = float(received_clock())
    try:
        socket = websocket.create_connection(adapter.ws_url, timeout=min(max(float(duration_sec), 1.0), 15.0), enable_multithread=True)
        for message in subscriptions:
            socket.send(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        deadline = time.monotonic() + float(duration_sec)
        while time.monotonic() < deadline:
            try:
                raw = socket.recv()
            except Exception as exc:
                if "timeout" in str(exc).lower():
                    continue
                raise
            if raw is None:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, Mapping) and payload.get("op") == "ping":
                socket.send(json.dumps({"op": "pong"}, separators=(",", ":")))
                continue
            if isinstance(payload, Mapping) and payload.get("event") == "ping":
                socket.send(json.dumps({"time": int(time.time()), "channel": payload.get("channel"), "event": "pong", "payload": payload.get("payload", [])}, separators=(",", ":")))
                continue
            if not isinstance(payload, Mapping):
                continue
            received_ts = float(received_clock())
            events = [
                {**_contract_metadata(contract, received_ts=received_ts), **event}
                for event in normalize_market_snapshot(adapter.venue, contract.contract_id, payload, received_ts=received_ts)
            ]
            written += int(store.append(events)["written"])
        return {"status": "COMPLETE", "events_written": written, "duration_sec": float(received_clock()) - started}
    except Exception as exc:
        return {"status": "RETRY_NEXT_INTERVAL", "events_written": written, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass


def discover_and_snapshot(
    *,
    adapters: Mapping[str, PublicPreIPOAdapter],
    store: RawEventStore,
    max_contracts_per_venue: int = 25,
    websocket_duration_sec: float = 0.0,
    now_ts: float | None = None,
) -> dict[str, Any]:
    received_ts = time.time() if now_ts is None else float(now_ts)
    outcomes: dict[str, Any] = {}
    total_contracts = 0
    total_events = 0
    official_contracts = 0
    proxy_contracts = 0
    discovered: dict[str, tuple[PublicPreIPOAdapter, list[Any], int]] = {}
    for venue, adapter in adapters.items():
        try:
            contracts = adapter.discover_contracts()
            selected = list(contracts)[: max(0, int(max_contracts_per_venue))]
            for contract in selected:
                if contract.source_class == "official":
                    official_contracts += 1
                else:
                    proxy_contracts += 1
            total_contracts += len(selected)
            discovered[venue] = (adapter, selected, len(contracts))
        except Exception as exc:
            outcomes[venue] = {
                "status": "RETRY_NEXT_INTERVAL",
                "contracts_seen": 0,
                "contracts_selected": 0,
                "events_written": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

    eligible_contracts = [
        (venue, contract)
        for venue, (_, selected, _) in discovered.items()
        for contract in selected
        if contract.lifecycle_status in {"preipo_continuous", "ipo_pending"}
    ]
    remaining_eligible = len(eligible_contracts)
    capture_started = time.monotonic()
    capture_budget_sec = max(0.0, float(websocket_duration_sec))
    capture_deadline = capture_started + capture_budget_sec
    allocated_capture_sec = 0.0

    cadence_contracts: list[dict[str, Any]] = []

    for venue, (adapter, selected, contracts_seen) in discovered.items():
        venue_events = 0
        ws_outcomes: list[dict[str, Any]] = []
        try:
            for contract in selected:
                # official_conversion_ts is read from Bybit preMktSwTime and OKX
                # conversion_time. That is a transition, not an official spot t0 - the
                # hardened capture repo maps the same field to transition_ts and refuses
                # official_spot_t0 to anything short of an OFFICIAL_ANNOUNCEMENT. No
                # venue endpoint feeding this track publishes a spot t0, so this track
                # can carry no exact official time at all, and now says so.
                anchor = resolve_anchor(
                    {
                        ANCHOR_TRANSITION: contract.official_conversion_ts,
                        ANCHOR_CONTRACT_LAUNCH: contract.tradable_ts,
                    },
                    source_class=contract.source_class,
                )
                cadence_contracts.append(
                    {
                        "lifecycle_status": contract.lifecycle_status,
                        "source_class": contract.source_class,
                        "event_eta_utc": utc_iso(anchor.ts) if anchor else None,
                        **anchor_observation(anchor),
                        "contract_present": True,
                    }
                )
                lifecycle_event = {
                    **_contract_metadata(contract, received_ts=received_ts),
                    "event_kind": "lifecycle",
                    "exchange_ts": contract.tradable_ts or received_ts,
                    "official_conversion_ts": contract.official_conversion_ts,
                    "rebase_ts": contract.rebase_ts,
                    "maintenance_margin_rate": contract.maintenance_margin_rate,
                    "taker_fee_bps": contract.taker_fee_bps,
                    "maker_fee_bps": contract.maker_fee_bps,
                }
                venue_events += int(store.append([lifecycle_event])["written"])
                for payload in adapter.snapshot_payloads(contract):
                    normalizer = getattr(adapter, "normalize_snapshot", None)
                    normalized = normalizer(contract, payload, received_ts=received_ts) if callable(normalizer) else normalize_market_snapshot(adapter.venue, contract.contract_id, payload, received_ts=received_ts)
                    events = [
                        {**_contract_metadata(contract, received_ts=received_ts), **event}
                        for event in normalized
                    ]
                    venue_events += int(store.append(events)["written"])
                if contract.lifecycle_status in {"preipo_continuous", "ipo_pending"}:
                    remaining_budget = max(0.0, capture_budget_sec - allocated_capture_sec)
                    remaining_wall = max(0.0, capture_deadline - time.monotonic())
                    duration = min(remaining_budget / max(1, remaining_eligible), remaining_wall)
                    allocated_capture_sec += duration
                    remaining_eligible -= 1
                    if duration > 0:
                        ws_result = capture_websocket_events(adapter, contract, store, duration_sec=duration)
                    else:
                        ws_result = {
                            "status": "SKIPPED",
                            "events_written": 0,
                            "reason": "capture_window_exhausted",
                        }
                    ws_outcomes.append({"contract_id": contract.contract_id, **ws_result})
                    venue_events += int(ws_result.get("events_written", 0))
            total_events += venue_events
            failures = [row for row in ws_outcomes if row.get("status") not in {"COMPLETE", "SKIPPED"}]
            outcomes[venue] = {
                "status": "RETRY_NEXT_INTERVAL" if failures else "COMPLETE",
                "contracts_seen": contracts_seen,
                "contracts_selected": len(selected),
                "events_written": venue_events,
                "websocket": ws_outcomes,
                "retry_reason": "websocket_capture_failed" if failures else None,
            }
        except Exception as exc:
            outcomes[venue] = {
                "status": "RETRY_NEXT_INTERVAL",
                "contracts_seen": contracts_seen,
                "contracts_selected": len(selected),
                "events_written": venue_events,
                "websocket": ws_outcomes,
                "error": f"{type(exc).__name__}: {exc}",
            }
            total_events += venue_events
    # The anchor is one observation, and its confirmation flags travel with it. They
    # used to be any() over the whole batch, so one contract's official source was
    # combined with another contract's timestamp into a confirmation no single
    # observation supported. pre_market_active stays a batch fact: it says a live
    # pre-IPO contract exists somewhere, which is true of the set, not of the anchor.
    cadence_observation: dict[str, Any] = {}
    anchor_row = select_cadence_anchor(cadence_contracts, now_ts=time.time())
    if anchor_row is not None:
        cadence_observation = {
            **anchor_row,
            "candidate": True,
            "pre_market_active": any(row.get("lifecycle_status") in {"preipo_continuous", "ipo_pending"} for row in cadence_contracts),
        }
    return {
        "outcomes": outcomes,
        "contracts_seen": total_contracts,
        "events_written": total_events,
        "official_contracts": official_contracts,
        "proxy_contracts": proxy_contracts,
        "capture_budget_sec": capture_budget_sec,
        "capture_elapsed_sec": time.monotonic() - capture_started,
        "checked_at_utc": utc_iso(received_ts),
        "cadence_observation": cadence_observation,
    }


def _build_manifest_payload(
    paths: AutomationPaths,
    *,
    attempt_id: str,
    status: str,
    result: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    store = RawEventStore(paths.events_path, paths.manifest_path)
    payload = store.manifest()
    payload.update({
        "automation_id": AUTOMATION_ID,
        "attempt_id": attempt_id,
        "status": status,
        "generated_at_utc": utc_iso(),
        "result": dict(result or {}),
        "error": error,
    })
    return payload


def _manifest_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _manifest_payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_manifest_payload_bytes(payload)).hexdigest()


def _commit_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with temp_path.open("xb") as handle:
            handle.write(_manifest_payload_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_manifest(
    paths: AutomationPaths,
    *,
    attempt_id: str,
    status: str,
    result: Mapping[str, Any] | None = None,
    error: str | None = None,
    prepared_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(prepared_payload or _build_manifest_payload(
        paths,
        attempt_id=attempt_id,
        status=status,
        result=result,
        error=error,
    ))
    _commit_manifest(paths.manifest_path, payload)
    return payload


def _read_prepared_receipt(path: Path) -> dict[str, Any] | None:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"terminal receipt conflict: unreadable receipt: {exc}") from exc
    if receipt.get("schema") != TERMINAL_RECEIPT_SCHEMA:
        return None
    if receipt.get("status") != "PREPARED" or not receipt.get("attempt_id"):
        raise RuntimeError(f"terminal receipt conflict: invalid prepared receipt: {path}")
    stored_sha256 = str(receipt.get("receipt_sha256") or "")
    core = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != stored_sha256:
        raise RuntimeError(f"terminal receipt conflict: receipt hash mismatch: {path}")
    manifest_sha256 = str(receipt.get("expected_manifest_sha256") or "")
    if len(manifest_sha256) != 64 or any(char not in "0123456789abcdef" for char in manifest_sha256.lower()):
        raise RuntimeError(f"terminal receipt conflict: invalid manifest hash: {path}")
    return receipt


def _receipt_reference(paths: AutomationPaths, receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": receipt["schema"],
        "path": str(_terminal_receipt_path(paths, str(receipt["attempt_id"]))),
        "receipt_sha256": receipt["receipt_sha256"],
    }


def _load_attempt_rows(paths: AutomationPaths, attempt_id: str) -> list[dict[str, Any]]:
    if not paths.ledger_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in paths.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("attempt_id") == attempt_id:
                rows.append(row)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"terminal receipt conflict: attempts ledger unreadable: {exc}") from exc
    return rows


def _existing_receipt_terminal(
    paths: AutomationPaths,
    receipt: Mapping[str, Any],
) -> dict[str, Any] | None:
    terminals = [
        row
        for row in _load_attempt_rows(paths, str(receipt["attempt_id"]))
        if row.get("record_type") == "TERMINAL" or row.get("terminal") is True
    ]
    if len(terminals) > 1:
        raise RuntimeError("terminal receipt conflict: multiple terminal rows")
    if not terminals:
        return None
    terminal = terminals[0]
    reference = terminal.get("terminal_receipt") or {}
    if reference.get("receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("terminal receipt conflict: terminal references another receipt")
    allowed_statuses = {str(receipt["intended_status"]), "RETRY_NEXT_INTERVAL"}
    if str(terminal.get("status")) not in allowed_statuses:
        raise RuntimeError("terminal receipt conflict: incompatible terminal status")
    manifest_committed = bool(terminal.get("manifest_committed"))
    if str(terminal.get("status")) != "RETRY_NEXT_INTERVAL" and not manifest_committed:
        raise RuntimeError("terminal receipt conflict: intended terminal lacks manifest commit")
    if manifest_committed:
        manifest_commit = terminal.get("manifest_commit") or {}
        if (
            manifest_commit.get("path") != receipt.get("expected_manifest_path")
            or manifest_commit.get("sha256") != receipt.get("expected_manifest_sha256")
        ):
            raise RuntimeError("terminal receipt conflict: manifest commit mismatch")
    return terminal


def _append_receipt_terminal_once(
    paths: AutomationPaths,
    receipt: Mapping[str, Any],
    *,
    status: str,
    reason: str | None,
    pending_retry: bool,
    manifest_committed: bool = False,
    extra_fields: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    allowed_statuses = {str(receipt["intended_status"]), "RETRY_NEXT_INTERVAL"}
    if status not in allowed_statuses:
        raise RuntimeError("terminal receipt conflict: incompatible requested status")
    existing = _existing_receipt_terminal(paths, receipt)
    if existing is not None:
        if (
            str(existing.get("status")) != status
            or bool(existing.get("manifest_committed")) != bool(manifest_committed)
        ):
            raise RuntimeError("terminal receipt conflict: terminal outcome differs")
        return existing, False
    manifest_commit: dict[str, Any] | None = None
    if manifest_committed:
        issue = _manifest_integrity_issue(paths, receipt)
        if issue is not None:
            raise RuntimeError(f"terminal receipt conflict: uncommitted manifest {issue}")
        manifest_commit = {
            "path": receipt["expected_manifest_path"],
            "sha256": receipt["expected_manifest_sha256"],
        }
    elif status != "RETRY_NEXT_INTERVAL":
        raise RuntimeError("terminal receipt conflict: intended terminal requires manifest commit")
    terminal = {
        "record_type": "TERMINAL",
        "terminal": True,
        "attempt_id": receipt["attempt_id"],
        "status": status,
        "finished_at_utc": utc_iso(),
        "outcomes": dict(receipt.get("outcomes") or {}),
        "reason": reason,
        "pending_retry": bool(pending_retry),
        "next_interval_at_utc": receipt["next_interval_at_utc"],
        "intended_status": receipt["intended_status"],
        "manifest_committed": bool(manifest_committed),
        "terminal_receipt": _receipt_reference(paths, receipt),
    }
    if manifest_commit is not None:
        terminal["manifest_commit"] = manifest_commit
    terminal.update(dict(extra_fields or {}))
    append_attempt(paths, terminal)
    return terminal, True


def _manifest_integrity_issue(paths: AutomationPaths, receipt: Mapping[str, Any]) -> str | None:
    expected_path = Path(str(receipt["expected_manifest_path"]))
    if expected_path.resolve() != paths.manifest_path.resolve():
        return "manifest_path_mismatch"
    if not paths.manifest_path.exists():
        return "manifest_missing"
    actual_sha256 = hashlib.sha256(paths.manifest_path.read_bytes()).hexdigest()
    if actual_sha256 != receipt["expected_manifest_sha256"]:
        return "manifest_hash_mismatch"
    return None


def _apply_reconciled_state(
    paths: AutomationPaths,
    receipt: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> None:
    state = load_state(paths)
    if state.get("last_attempt_id") != receipt.get("attempt_id"):
        return
    status = str(terminal["status"])
    prior_status = str(state.get("status") or "")
    state.update({
        "status": status,
        "pending_retry": bool(terminal.get("pending_retry")),
        "next_interval_at_utc": terminal.get("next_interval_at_utc"),
        "last_finished_at_utc": terminal.get("finished_at_utc") or utc_iso(),
        "worker_pid": None,
        "outcomes": dict(receipt.get("outcomes") or {}),
        "last_error": terminal.get("reason"),
    })
    if status == "RETRY_NEXT_INTERVAL" and prior_status != "RETRY_NEXT_INTERVAL":
        state["retry_count"] = int(state.get("retry_count", 0)) + 1
    save_state(paths, state)


def reconcile_prepared_receipts(paths: AutomationPaths) -> dict[str, Any]:
    """Resolve orphan PREPARED receipts without ever inferring an uncommitted COMPLETE."""

    receipt_dir = paths.ledger_path.parent / "terminal-receipts"
    outcomes: list[dict[str, Any]] = []
    if not receipt_dir.exists():
        return {"checked": 0, "outcomes": outcomes}
    for receipt_path in sorted(receipt_dir.glob("*.json")):
        receipt = _read_prepared_receipt(receipt_path)
        if receipt is None:
            continue
        existing = _existing_receipt_terminal(paths, receipt)
        if existing is not None:
            _apply_reconciled_state(paths, receipt, existing)
            outcomes.append({"attempt_id": receipt["attempt_id"], "status": existing["status"], "created": False})
            continue

        issue = _manifest_integrity_issue(paths, receipt)
        committed = issue is None
        terminal_status = str(receipt["intended_status"]) if committed else "RETRY_NEXT_INTERVAL"
        terminal_reason = receipt.get("reason") if committed else f"interrupted_prepared_receipt:{issue}"
        terminal, created = _append_receipt_terminal_once(
            paths,
            receipt,
            status=terminal_status,
            reason=terminal_reason,
            pending_retry=bool(receipt.get("pending_retry")) if committed else True,
            manifest_committed=committed,
        )
        _apply_reconciled_state(paths, receipt, terminal)
        outcomes.append({"attempt_id": receipt["attempt_id"], "status": terminal["status"], "created": created})
    return {"checked": len(outcomes), "outcomes": outcomes}


def _finalize_failed_attempt(
    paths: AutomationPaths,
    *,
    attempt_id: str,
    status: str,
    finished_at_utc: str,
    reason: str,
    next_interval_at_utc: str,
    state_error: str | None = None,
    worker_error: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Durably append the terminal failure before best-effort publications."""

    extra_fields: dict[str, Any] = {"finished_at_utc": finished_at_utc}
    if state_error is not None:
        extra_fields["state_error"] = state_error
    if worker_error is not None:
        extra_fields["worker_error"] = worker_error
    receipt_path = _terminal_receipt_path(paths, attempt_id)
    receipt = _read_prepared_receipt(receipt_path) if receipt_path.exists() else None
    if receipt is not None:
        _append_receipt_terminal_once(
            paths,
            receipt,
            status=status,
            reason=reason,
            pending_retry=True,
            extra_fields=extra_fields,
        )
    else:
        append_attempt(paths, {
            "record_type": "TERMINAL",
            "terminal": True,
            "attempt_id": attempt_id,
            "status": status,
            "finished_at_utc": finished_at_utc,
            "reason": reason,
            "pending_retry": True,
            "next_interval_at_utc": next_interval_at_utc,
            **extra_fields,
        })

    manifest: dict[str, Any] | None = None
    manifest_error: str | None = None
    try:
        manifest = _write_manifest(paths, attempt_id=attempt_id, status=status, error=reason)
    except Exception as exc:
        manifest_error = f"{type(exc).__name__}: {exc}"
        diagnostic = {
            "record_type": "DIAGNOSTIC",
            "terminal": False,
            "attempt_id": attempt_id,
            "status": "DIAGNOSTIC",
            "recorded_at_utc": utc_iso(),
            "diagnostic": "manifest_write_failed",
            "manifest_error": manifest_error,
        }
        try:
            append_attempt(paths, diagnostic)
        except Exception:
            # The terminal row is already durable; diagnostics are best-effort.
            pass
    return manifest, manifest_error


def _ensure_failure_receipt(
    paths: AutomationPaths,
    *,
    attempt_id: str,
    reason: str,
    next_interval_at_utc: str,
    outcomes: Mapping[str, Any],
) -> dict[str, Any]:
    """Create immutable retry intent before publishing failure state or diagnostics."""

    receipt_path = _terminal_receipt_path(paths, attempt_id)
    if receipt_path.exists():
        receipt = _read_prepared_receipt(receipt_path)
        if receipt is None:
            raise RuntimeError(f"terminal receipt conflict: unsupported receipt: {receipt_path}")
        return receipt
    prepared_manifest = _build_manifest_payload(
        paths,
        attempt_id=attempt_id,
        status="RETRY_NEXT_INTERVAL",
        error=reason,
    )
    return _write_terminal_receipt(
        paths,
        attempt_id=attempt_id,
        status="RETRY_NEXT_INTERVAL",
        outcomes=outcomes,
        reason=reason,
        pending_retry=True,
        next_interval_at_utc=next_interval_at_utc,
        expected_manifest_path=str(paths.manifest_path),
        expected_manifest_sha256=_manifest_payload_sha256(prepared_manifest),
    )


def run_tick(
    paths: AutomationPaths,
    *,
    adapters: Mapping[str, PublicPreIPOAdapter] | None = None,
    venues: Iterable[str] = VENUES,
    max_contracts_per_venue: int = 25,
    timeout_sec: float = 10.0,
    websocket_duration_sec: float = 0.0,
    now_ts: float | None = None,
    attempt_id: str | None = None,
    external_worker_pid: int | None = None,
    external_worker_process_started_at_utc: str | None = None,
    running_evidence_already_persisted: bool = False,
) -> dict[str, Any]:
    reconcile_prepared_receipts(paths)
    state = load_state(paths)
    attempt_id = attempt_id or f"preipo_automation_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if not attempt_id or Path(attempt_id).name != attempt_id:
        raise ValueError("unsafe attempt_id")
    worker_pid = int(external_worker_pid or os.getpid())
    if running_evidence_already_persisted:
        if (
            state.get("status") != "RUNNING"
            or state.get("last_attempt_id") != attempt_id
            or int(state.get("worker_pid") or 0) != worker_pid
            or state.get("worker_process_started_at_utc")
            != external_worker_process_started_at_utc
        ):
            raise RuntimeError("launcher RUNNING handoff state mismatch")
        started = str(state.get("last_started_at_utc") or utc_iso(now_ts))
    else:
        started = utc_iso(now_ts)
        state.update({"status": "RUNNING", "attempt_count": int(state.get("attempt_count", 0)) + 1, "last_attempt_id": attempt_id, "last_started_at_utc": started, "worker_pid": worker_pid, "worker_process_started_at_utc": external_worker_process_started_at_utc})
    try:
        if not running_evidence_already_persisted:
            append_attempt(paths, {"attempt_id": attempt_id, "status": "RUNNING", "started_at_utc": started, "worker_pid": worker_pid, "worker_process_started_at_utc": external_worker_process_started_at_utc})
            save_state(paths, state)
        store = RawEventStore(paths.events_path, paths.manifest_path)
        active_adapters = dict(adapters or build_public_adapters(venues, timeout_sec=timeout_sec))
        result = discover_and_snapshot(
            adapters=active_adapters,
            store=store,
            max_contracts_per_venue=max_contracts_per_venue,
            websocket_duration_sec=websocket_duration_sec,
            now_ts=now_ts,
        )
        failed = [venue for venue, outcome in result["outcomes"].items() if outcome.get("status") != "COMPLETE"]
        if not result["outcomes"]:
            failed = ["no_active_venues"]
        status = "PARTIAL_RETRY_NEXT_INTERVAL" if failed and len(failed) < len(result["outcomes"]) else "RETRY_NEXT_INTERVAL" if failed else "COMPLETE"
        cadence = decide_cadence(result.get("cadence_observation"), now=now_ts)
        next_at = cadence.next_interval_at_utc
        state.update({
            "status": status,
            "pending_retry": bool(failed),
            "cadence_stage": cadence.stage.value,
            "cadence_seconds": cadence.interval_sec,
            "cadence_reason": cadence.reason,
            "event_eta_utc": cadence.event_eta_utc,
            "official_confirmation": bool((result.get("cadence_observation") or {}).get("official_confirmed")),
            "exact_timestamp": bool((result.get("cadence_observation") or {}).get("exact_timestamp")),
            "next_interval_at_utc": next_at,
            "last_finished_at_utc": utc_iso(now_ts),
            "worker_pid": None,
            "worker_process_started_at_utc": None,
            "outcomes": result["outcomes"],
            "accrual": {
                "contracts_seen": result["contracts_seen"],
                "events_written": result["events_written"],
                "complete_events": 0,
                "official_events": result["official_contracts"],
                "proxy_events": result["proxy_contracts"],
            },
            "last_error": "; ".join(failed) if failed else None,
        })
        if failed:
            state["retry_count"] = int(state.get("retry_count", 0)) + 1
        terminal_reason = "; ".join(failed) if failed else None
        prepared_manifest = _build_manifest_payload(
            paths,
            attempt_id=attempt_id,
            status=status,
            result=result,
        )
        receipt = _write_terminal_receipt(
            paths,
            attempt_id=attempt_id,
            status=status,
            outcomes=result["outcomes"],
            reason=terminal_reason,
            pending_retry=bool(failed),
            next_interval_at_utc=next_at,
            expected_manifest_path=str(paths.manifest_path),
            expected_manifest_sha256=_manifest_payload_sha256(prepared_manifest),
        )
        manifest = _write_manifest(
            paths,
            attempt_id=attempt_id,
            status=status,
            result=result,
            prepared_payload=prepared_manifest,
        )
        save_state(paths, state)
        terminal, _ = _append_receipt_terminal_once(
            paths,
            receipt,
            status=status,
            reason=terminal_reason,
            pending_retry=bool(failed),
            manifest_committed=True,
            extra_fields={"finished_at_utc": utc_iso(now_ts)},
        )
        receipt_ref = dict(terminal["terminal_receipt"])
        return {"ok": not failed, "attempt_id": attempt_id, "status": status, "pending_retry": bool(failed), "outcomes": result["outcomes"], "accrual": state["accrual"], "manifest": manifest, "next_interval_at_utc": next_at, "cadence": cadence.as_dict(), "terminal_receipt": receipt_ref}
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        retry_interval = int(state.get("cadence_seconds") or SCHEDULE_INTERVAL_SEC)
        state, next_at = mark_retry_next_interval(
            state,
            reason,
            now_ts=now_ts,
            interval_sec=retry_interval,
        )
        state.update({"last_finished_at_utc": utc_iso(now_ts), "worker_pid": None, "worker_process_started_at_utc": None})
        failure_receipt = _ensure_failure_receipt(
            paths,
            attempt_id=attempt_id,
            reason=reason,
            next_interval_at_utc=next_at,
            outcomes=state.get("outcomes") if isinstance(state.get("outcomes"), Mapping) else {},
        )
        state_error: str | None = None
        try:
            save_state(paths, state)
        except Exception as state_exc:
            state_error = f"{type(state_exc).__name__}: {state_exc}"
        worker_error: str | None = None
        try:
            paths.worker_error_path.parent.mkdir(parents=True, exist_ok=True)
            paths.worker_error_path.write_text(reason + "\n", encoding="utf-8")
        except Exception as worker_exc:
            worker_error = f"{type(worker_exc).__name__}: {worker_exc}"
        manifest, manifest_error = _finalize_failed_attempt(
            paths,
            attempt_id=attempt_id,
            status="RETRY_NEXT_INTERVAL",
            finished_at_utc=utc_iso(now_ts),
            reason=reason,
            next_interval_at_utc=next_at,
            state_error=state_error,
            worker_error=worker_error,
        )
        return {
            "ok": False,
            "attempt_id": attempt_id,
            "status": "RETRY_NEXT_INTERVAL",
            "pending_retry": True,
            "reason": reason,
            "manifest": manifest,
            "manifest_error": manifest_error,
            "state_error": state_error,
            "worker_error": worker_error,
            "next_interval_at_utc": next_at,
            "terminal_receipt": _receipt_reference(paths, failure_receipt),
        }


def automation_status(paths: AutomationPaths) -> dict[str, Any]:
    state = load_state(paths)
    payload = dict(state)
    payload.update({"state_path": str(paths.state_path), "ledger_path": str(paths.ledger_path), "events_path": str(paths.events_path), "manifest_path": str(paths.manifest_path)})
    if paths.manifest_path.exists():
        try:
            payload["manifest"] = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload["manifest"] = {"status": "UNREADABLE"}
    return payload


def _default_paths(repo_root: Path) -> AutomationPaths:
    run_dir = repo_root / "docs" / "agent-log" / "run-gates"
    output_dir = repo_root / "exports" / "trading-mvp" / "preipo-perp"
    return AutomationPaths(
        state_path=run_dir / "preipo_perpetual_event_automation_state.json",
        ledger_path=run_dir / "preipo_perpetual_event_automation_attempts.jsonl",
        claim_path=run_dir / "preipo_perpetual_event_automation.claim.json",
        launch_path=run_dir / "preipo_perpetual_event_automation.launch.json",
        worker_error_path=run_dir / "preipo_perpetual_event_automation.worker-error.log",
        events_path=output_dir / "raw_events.jsonl",
        manifest_path=output_dir / "manifest.json",
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description="Public pre-IPO perpetual automation worker")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--tick", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-contracts-per-venue", type=int, default=25)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--websocket-duration-sec", type=float, default=CAPTURE_DURATION_SEC)
    parser.add_argument("--attempt-id")
    parser.add_argument("--worker-handoff-token")
    parser.add_argument("--plan-hash")
    args = parser.parse_args()
    paths = _default_paths(Path(args.repo_root))
    if args.status:
        payload = automation_status(paths)
    elif args.tick:
        if not args.attempt_id or not args.worker_handoff_token or not args.plan_hash:
            raise SystemExit("tick requires a launcher-issued worker handoff")
        handoff = consume_worker_handoff_receipt(
            Path(args.repo_root) / "docs" / "agent-log" / "active-market-data-writer-claim.json",
            receipt_path=paths.ledger_path.parent / "python-worker-handoffs" / f"{args.attempt_id}.json",
            consumed_dir=paths.ledger_path.parent / "python-worker-handoffs" / "consumed",
            handoff_token=args.worker_handoff_token,
            attempt_id=args.attempt_id,
            plan_hash=args.plan_hash,
            automation_id=AUTOMATION_ID,
        )
        payload = run_tick(paths, max_contracts_per_venue=args.max_contracts_per_venue, timeout_sec=args.timeout_sec, websocket_duration_sec=args.websocket_duration_sec, attempt_id=args.attempt_id, external_worker_pid=int(handoff["wrapper_pid"]), external_worker_process_started_at_utc=str(handoff["wrapper_process_started_at_utc"]), running_evidence_already_persisted=True)
    else:
        payload = {"ok": True, "usage": "--status or --tick"}
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
