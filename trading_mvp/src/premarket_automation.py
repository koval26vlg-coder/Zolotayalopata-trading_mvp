"""Public, paper-only pre-market discovery and automation helpers.

This module has no authenticated code path.  The PowerShell wrapper launches it
in a visible terminal and owns the scheduler cadence; the Python side owns
public REST/WebSocket adapters, append-only event materialisation and the
retry state helpers used by unit tests and recovery tooling.
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
from urllib.parse import urlsplit

import requests

from premarket_perp import (
    PreMarketContract,
    VENUES,
    normalize_market_payload,
    normalise_contract,
    official_preflight_contract,
)
from adaptive_cadence import SEARCH_INTERVAL_SEC, SCHEDULED_INTERVAL_SEC, decide_cadence
from premarket_temporal_anchor import (
    ANCHOR_CONTRACT_LAUNCH,
    ANCHOR_OFFICIAL_SPOT_T0,
    ANCHOR_TRANSITION,
    anchor_observation,
    resolve_anchor,
    select_cadence_anchor,
)
from global_market_writer_claim import consume_worker_handoff_receipt


AUTOMATION_ID = "zolotyaylopata-premarket-perp-listing-monitor"
STATE_SCHEMA = "trading_mvp_premarket_perp_listing_automation_state_v1"
ATTEMPT_SCHEMA = "trading_mvp_premarket_perp_listing_automation_attempt_v1"
TERMINAL_RECEIPT_SCHEMA = "trading_mvp_premarket_perp_terminal_intent_receipt_v1"
DEFAULT_INTERVAL_SEC = SEARCH_INTERVAL_SEC


@dataclass(frozen=True)
class AutomationPaths:
    state_path: Path
    ledger_path: Path
    claim_path: Path
    launch_path: Path
    worker_error_path: Path
    events_path: Path | None = None
    manifest_path: Path | None = None


def utc_iso(ts: float | None = None) -> str:
    value = datetime.now(timezone.utc) if ts is None else datetime.fromtimestamp(float(ts), timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _default_state() -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "automation_id": AUTOMATION_ID,
        "cadence_minutes": SEARCH_INTERVAL_SEC // 60,
        "cadence_seconds": SEARCH_INTERVAL_SEC,
        "cadence_stage": "SEARCH",
        "cadence_reason": "initial_search",
        "event_eta_utc": None,
        "official_confirmation": False,
        "exact_timestamp": False,
        "wake_interval_seconds": SCHEDULED_INTERVAL_SEC,
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
        "accrual": {"contracts_seen": 0, "events_written": 0, "complete_events": 0},
        "last_error": None,
        "updated_at_utc": utc_iso(),
    }


def load_state(paths: AutomationPaths) -> dict[str, Any]:
    if not paths.state_path.exists():
        return _default_state()
    try:
        payload = json.loads(paths.state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"automation state unreadable: {exc}") from exc
    if payload.get("schema") != STATE_SCHEMA:
        raise RuntimeError("automation state schema mismatch")
    return payload


def save_state(paths: AutomationPaths, state: Mapping[str, Any]) -> None:
    payload = dict(state)
    payload["updated_at_utc"] = utc_iso()
    _atomic_write(paths.state_path, payload)


def append_attempt(paths: AutomationPaths, payload: Mapping[str, Any]) -> None:
    paths.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"schema": ATTEMPT_SCHEMA, **dict(payload)}
    with paths.ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
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


def next_interval_iso(now_ts: float | None = None, interval_sec: int = DEFAULT_INTERVAL_SEC) -> str:
    base = time.time() if now_ts is None else float(now_ts)
    return utc_iso(base + int(interval_sec))


def mark_retry_next_interval(
    state: Mapping[str, Any],
    reason: str,
    *,
    now_ts: float | None = None,
    interval_sec: int = DEFAULT_INTERVAL_SEC,
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


class PublicAdapter:
    venue = ""
    base_url = ""
    ws_url = ""
    allowed_paths: frozenset[str] = frozenset()

    def __init__(self, timeout_sec: float = 10.0, session: requests.Session | None = None) -> None:
        self.timeout_sec = timeout_sec
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.last_response_received_ts: float | None = None

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        if not path.startswith("/") or "://" in path or path not in self.allowed_paths:
            raise ValueError(f"{self.venue} public request requires a relative approved path")
        base = urlsplit(self.base_url)
        if base.scheme.lower() != "https" or not base.hostname:
            raise RuntimeError(f"{self.venue} adapter base URL is not approved HTTPS")
        url = f"{self.base_url}{path}"
        response = self.session.get(
            url,
            params=dict(params or {}),
            timeout=self.timeout_sec,
            allow_redirects=False,
        )
        status = int(getattr(response, "status_code", 0) or 0)
        final = urlsplit(str(getattr(response, "url", url) or url))
        expected = urlsplit(url)
        if (
            status != 200
            or final.scheme.lower() != "https"
            or (final.hostname or "").lower() != (expected.hostname or "").lower()
            or final.path != expected.path
        ):
            raise RuntimeError(f"{self.venue} redirect_or_final_url_rejected:{status}")
        response.raise_for_status()
        payload = response.json()
        self.last_response_received_ts = time.time()
        if isinstance(payload, Mapping) and str(payload.get("retCode", 0)) not in {"0", ""}:
            raise RuntimeError(f"{self.venue} retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}")
        if isinstance(payload, Mapping) and str(payload.get("code", "0")) not in {"0", ""}:
            raise RuntimeError(f"{self.venue} code={payload.get('code')} msg={payload.get('msg')}")
        return payload

    def discover_contracts(self) -> list[PreMarketContract]:
        raise NotImplementedError

    def snapshot_payloads(self, contract: PreMarketContract) -> list[Mapping[str, Any] | list[Any]]:
        raise NotImplementedError

    def websocket_subscription(self, contract: PreMarketContract) -> dict[str, Any]:
        raise NotImplementedError

    def websocket_subscriptions(self, contract: PreMarketContract) -> list[dict[str, Any]]:
        return [self.websocket_subscription(contract)]


class BybitPublicAdapter(PublicAdapter):
    venue = "bybit"
    base_url = "https://api.bybit.com"
    ws_url = "wss://stream.bybit.com/v5/public/linear"
    allowed_paths = frozenset(
        {
            "/v5/market/instruments-info",
            "/v5/market/orderbook",
            "/v5/market/tickers",
        }
    )

    def discover_contracts(self) -> list[PreMarketContract]:
        out: list[PreMarketContract] = []
        cursor: str | None = None
        for _ in range(10):
            params: dict[str, Any] = {"category": "linear", "status": "PreLaunch", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/v5/market/instruments-info", params)
            result = payload.get("result") or {}
            for item in result.get("list") or []:
                contract = normalise_contract(self.venue, item)
                if contract is not None:
                    out.append(contract)
            cursor = result.get("nextPageCursor")
            if not cursor:
                break
        return out

    def snapshot_payloads(self, contract: PreMarketContract) -> list[Mapping[str, Any]]:
        book = self._get("/v5/market/orderbook", {"category": "linear", "symbol": contract.contract_id, "limit": 50})
        book_received_ts = self.last_response_received_ts
        ticker = self._get("/v5/market/tickers", {"category": "linear", "symbol": contract.contract_id})
        ticker_received_ts = self.last_response_received_ts
        return [
            {"topic": f"orderbook.50.{contract.contract_id}", **book, "__received_ts": book_received_ts},
            {"topic": f"tickers.{contract.contract_id}", **ticker, "__received_ts": ticker_received_ts},
        ]

    def websocket_subscription(self, contract: PreMarketContract) -> dict[str, Any]:
        return {"op": "subscribe", "args": [f"orderbook.50.{contract.contract_id}", f"publicTrade.{contract.contract_id}", f"tickers.{contract.contract_id}"]}


class OkxPublicAdapter(PublicAdapter):
    venue = "okx"
    base_url = "https://www.okx.com"
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"
    allowed_paths = frozenset(
        {
            "/api/v5/public/instruments",
            "/api/v5/market/books",
            "/api/v5/market/ticker",
            "/api/v5/public/mark-price",
        }
    )

    def discover_contracts(self) -> list[PreMarketContract]:
        payload = self._get("/api/v5/public/instruments", {"instType": "SWAP"})
        return [contract for item in payload.get("data") or [] if (contract := normalise_contract(self.venue, item)) is not None]

    def snapshot_payloads(self, contract: PreMarketContract) -> list[Mapping[str, Any]]:
        book = self._get("/api/v5/market/books", {"instId": contract.contract_id, "sz": 50})
        book_received_ts = self.last_response_received_ts
        ticker = self._get("/api/v5/market/ticker", {"instId": contract.contract_id})
        ticker_received_ts = self.last_response_received_ts
        mark = self._get("/api/v5/public/mark-price", {"instType": "SWAP", "instId": contract.contract_id})
        mark_received_ts = self.last_response_received_ts
        return [
            {"arg": {"channel": "books", "instId": contract.contract_id}, **book, "__received_ts": book_received_ts},
            {"arg": {"channel": "tickers", "instId": contract.contract_id}, **ticker, "__received_ts": ticker_received_ts},
            {"arg": {"channel": "mark-price", "instId": contract.contract_id}, **mark, "__received_ts": mark_received_ts},
        ]

    def websocket_subscription(self, contract: PreMarketContract) -> dict[str, Any]:
        return {
            "op": "subscribe",
            "args": [
                {"channel": "books", "instId": contract.contract_id},
                {"channel": "trades", "instId": contract.contract_id},
                {"channel": "tickers", "instId": contract.contract_id},
            ],
        }


class GatePublicAdapter(PublicAdapter):
    venue = "gate"
    base_url = "https://api.gateio.ws/api/v4"
    ws_url = "wss://fx-ws.gateio.ws/v4/ws/usdt"
    allowed_paths = frozenset(
        {
            "/futures/usdt/contracts",
            "/futures/usdt/order_book",
            "/futures/usdt/tickers",
        }
    )

    def discover_contracts(self) -> list[PreMarketContract]:
        payload = self._get("/futures/usdt/contracts")
        return [contract for item in payload if (contract := normalise_contract(self.venue, item)) is not None]

    def snapshot_payloads(self, contract: PreMarketContract) -> list[Mapping[str, Any]]:
        book = self._get("/futures/usdt/order_book", {"contract": contract.contract_id, "limit": 50})
        book_received_ts = self.last_response_received_ts
        ticker = self._get("/futures/usdt/tickers", {"contract": contract.contract_id})
        ticker_received_ts = self.last_response_received_ts
        return [
            {"channel": "futures.order_book", "result": book, "__received_ts": book_received_ts},
            {"channel": "futures.tickers", "result": ticker, "__received_ts": ticker_received_ts},
        ]

    def websocket_subscription(self, contract: PreMarketContract) -> dict[str, Any]:
        now = int(time.time())
        return {
            "time": now,
            "channel": "futures.order_book",
            "event": "subscribe",
            "payload": [contract.contract_id, "50", "100ms"],
        }

    def websocket_subscriptions(self, contract: PreMarketContract) -> list[dict[str, Any]]:
        now = int(time.time())
        return [
            {"time": now, "channel": "futures.order_book", "event": "subscribe", "payload": [contract.contract_id, "50", "100ms"]},
            {"time": now, "channel": "futures.trades", "event": "subscribe", "payload": [contract.contract_id]},
            {"time": now, "channel": "futures.tickers", "event": "subscribe", "payload": [contract.contract_id]},
        ]


ADAPTERS: dict[str, type[PublicAdapter]] = {"bybit": BybitPublicAdapter, "okx": OkxPublicAdapter, "gate": GatePublicAdapter}


def build_public_adapters(venues: Iterable[str] = VENUES, *, timeout_sec: float = 10.0) -> dict[str, PublicAdapter]:
    result: dict[str, PublicAdapter] = {}
    for venue in venues:
        key = venue.strip().lower()
        if key == "gateio":
            key = "gate"
        if key not in ADAPTERS:
            raise ValueError(f"Unsupported pre-market venue: {venue}")
        result[key] = ADAPTERS[key](timeout_sec=timeout_sec)
    return result


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def _enrich_contract_events(contract: PreMarketContract, events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Attach lifecycle/identity metadata to every normalized market event."""

    metadata = {
        "venue": contract.venue,
        "premarket_contract_id": contract.contract_id,
        "spot_symbol": contract.spot_symbol,
        "quote": contract.quote,
        "phase": contract.phase,
        "premarket_phase": contract.phase,
        "lifecycle_status": contract.lifecycle_status,
        "source_class": contract.source_class,
        "listing_source_class": contract.listing_source_class,
        "listing_acceptance_eligible": contract.listing_acceptance_eligible,
        "announcement_ts": contract.announcement_ts,
        "official_spot_listing_ts": contract.official_spot_listing_ts,
        "transition_ts": contract.transition_ts,
        "price_limit_up": contract.price_limit_up,
        "price_limit_down": contract.price_limit_down,
        "maintenance_margin_rate": contract.maintenance_margin_rate,
        "completion_reason": contract.lifecycle_status if contract.lifecycle_status in {"cancelled", "delisted", "expired", "transitioned"} else None,
    }
    return [{**dict(event), **metadata} for event in events]


def _build_manifest_payload(
    paths: AutomationPaths,
    *,
    attempt_id: str,
    status: str,
    result: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build the exact manifest payload before publishing its intent receipt."""

    events_path = paths.events_path or paths.state_path.with_name("premarket_events.jsonl")
    events_sha256 = None
    events_bytes = 0
    if events_path.exists():
        digest = hashlib.sha256()
        with events_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                events_bytes += len(chunk)
        events_sha256 = digest.hexdigest()
    return {
        "schema": "trading_mvp_premarket_perp_listing_manifest_v1",
        "automation_id": AUTOMATION_ID,
        "attempt_id": attempt_id,
        "status": status,
        "generated_at_utc": utc_iso(),
        "public_data_only": True,
        "private_api": False,
        "live_orders": False,
        "events_path": str(events_path),
        "events_sha256": events_sha256,
        "events_bytes": events_bytes,
        "result": dict(result or {}),
        "error": error,
    }


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
) -> dict[str, Any] | None:
    """Publish one atomic, auditable manifest for the latest bounded tick."""

    if paths.manifest_path is None:
        return None
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
    if paths.manifest_path is None:
        return "manifest_path_missing"
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
) -> str | None:
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

    manifest_error: str | None = None
    try:
        _write_manifest(paths, attempt_id=attempt_id, status=status, error=reason)
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
    return manifest_error


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
    expected_manifest_path = paths.manifest_path or paths.state_path.with_name("premarket_failure_manifest.json")
    return _write_terminal_receipt(
        paths,
        attempt_id=attempt_id,
        status="RETRY_NEXT_INTERVAL",
        outcomes=outcomes,
        reason=reason,
        pending_retry=True,
        next_interval_at_utc=next_interval_at_utc,
        expected_manifest_path=str(expected_manifest_path),
        expected_manifest_sha256=_manifest_payload_sha256(prepared_manifest),
    )


def capture_websocket_events(
    adapter: PublicAdapter,
    contract: PreMarketContract,
    *,
    events_path: Path,
    duration_sec: float = 10.0,
    received_clock: Any = time.time,
) -> dict[str, Any]:
    """Capture a bounded public WS slice; never creates an authenticated path."""

    if duration_sec <= 0:
        return {"status": "SKIPPED", "events_written": 0, "reason": "duration_sec_not_positive"}
    try:
        import websocket  # type: ignore
    except ImportError as exc:
        return {"status": "RETRY_NEXT_INTERVAL", "events_written": 0, "reason": f"websocket_dependency_missing:{exc}"}

    events: list[dict[str, Any]] = []
    socket = None
    started = float(received_clock())
    try:
        socket = websocket.create_connection(adapter.ws_url, timeout=min(max(duration_sec, 1.0), 15.0), enable_multithread=True)
        for message in adapter.websocket_subscriptions(contract):
            socket.send(json.dumps(message, separators=(",", ":")))
        deadline = time.monotonic() + duration_sec
        while time.monotonic() < deadline:
            try:
                raw = socket.recv()
            except Exception as exc:  # websocket-client has venue-specific timeout classes
                if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
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
            events.extend(_enrich_contract_events(contract, normalize_market_payload(adapter.venue, contract.contract_id, payload, received_ts=float(received_clock()))))
        written = _append_jsonl(events_path, events)
        return {"status": "COMPLETE", "events_written": written, "duration_sec": float(received_clock()) - started}
    except Exception as exc:
        return {"status": "RETRY_NEXT_INTERVAL", "events_written": 0, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass


def discover_and_snapshot(
    *,
    adapters: Mapping[str, PublicAdapter],
    events_path: Path,
    max_contracts_per_venue: int = 25,
    websocket_duration_sec: float = 10.0,
    max_active_websockets_per_venue: int = 1,
    now_ts: float | None = None,
) -> dict[str, Any]:
    received_ts = time.time() if now_ts is None else float(now_ts)
    outcomes: dict[str, Any] = {}
    total_contracts = 0
    total_events = 0
    cadence_contracts: list[dict[str, Any]] = []
    for venue, adapter in adapters.items():
        try:
            contracts = adapter.discover_contracts()
            selected = contracts[:max_contracts_per_venue]
            venue_events: list[dict[str, Any]] = []
            for contract in selected:
                # Keep the kind of moment attached to the moment. The old chain
                # collapsed an announced spot t0, a transition and a contract launch
                # into one undifferentiated event_ts, after which "official" was
                # asserted from the *record's* source_class alone - dropping the half
                # of the test that the model already got right in
                # PreMarketContract.has_official_listing_time.
                anchor = resolve_anchor(
                    {
                        ANCHOR_OFFICIAL_SPOT_T0: contract.official_spot_listing_ts,
                        ANCHOR_TRANSITION: contract.transition_ts,
                        ANCHOR_CONTRACT_LAUNCH: contract.tradable_ts,
                    },
                    source_class=contract.source_class,
                    source_classes={
                        ANCHOR_OFFICIAL_SPOT_T0: (
                            contract.listing_source_class
                            if contract.listing_acceptance_eligible
                            else "proxy"
                        ),
                    },
                )
                cadence_contracts.append(
                    {
                        "lifecycle_status": contract.lifecycle_status,
                        "source_class": contract.source_class,
                        "event_eta_utc": utc_iso(anchor.ts) if anchor else None,
                        **anchor_observation(anchor),
                        "contract_present": True,
                        "pre_market_active": contract.lifecycle_status in {"call_auction", "continuous"},
                    }
                )
                for payload in adapter.snapshot_payloads(contract):
                    payload_received_ts = received_ts
                    normalized_payload = payload
                    if isinstance(payload, Mapping):
                        payload_received_ts = float(payload.get("__received_ts") or received_ts)
                        normalized_payload = dict(payload)
                        normalized_payload.pop("__received_ts", None)
                    venue_events.extend(
                        _enrich_contract_events(
                            contract,
                            normalize_market_payload(
                                venue,
                                contract.contract_id,
                                normalized_payload,
                                received_ts=payload_received_ts,
                            ),
                        )
                    )
            total_contracts += len(selected)
            total_events += _append_jsonl(events_path, venue_events)
            active = [contract for contract in selected if contract.lifecycle_status in {"call_auction", "continuous"}][:max_active_websockets_per_venue]
            ws_outcomes: list[dict[str, Any]] = []
            for contract in active:
                ws_result = capture_websocket_events(adapter, contract, events_path=events_path, duration_sec=websocket_duration_sec)
                ws_outcomes.append({"contract_id": contract.contract_id, **ws_result})
                total_events += int(ws_result.get("events_written", 0))
            # A REST snapshot is useful evidence, but it does not make an active
            # contract complete when the bounded live capture failed. Keep that
            # venue queued for the next interval so a transient WS/network error
            # cannot silently turn into a false successful tick.
            websocket_failures = [
                item for item in ws_outcomes
                if str(item.get("status")) not in {"COMPLETE", "SKIPPED"}
            ]
            venue_status = "RETRY_NEXT_INTERVAL" if websocket_failures else "COMPLETE"
            outcomes[venue] = {
                "status": venue_status,
                "contracts_seen": len(contracts),
                "contracts_selected": len(selected),
                "events_written": len(venue_events),
                "websocket": ws_outcomes,
                "retry_reason": "websocket_capture_failed" if websocket_failures else None,
            }
        except Exception as exc:  # public venue failure is retried by the next scheduler tick
            outcomes[venue] = {"status": "RETRY_NEXT_INTERVAL", "error": f"{type(exc).__name__}: {exc}"}
    # The anchor is one observation, and its confirmation flags travel with it. They
    # used to be any() over the whole batch, so one contract's official source was
    # combined with another contract's timestamp into a confirmation no single
    # observation supported.
    cadence_observation: dict[str, Any] = {}
    anchor_row = select_cadence_anchor(cadence_contracts, now_ts=received_ts)
    if anchor_row is not None:
        cadence_observation = {
            **anchor_row,
            "candidate": True,
        }
    return {
        "outcomes": outcomes,
        "contracts_seen": total_contracts,
        "events_written": total_events,
        "checked_at_utc": utc_iso(received_ts),
        "cadence_observation": cadence_observation,
    }


def automation_status(paths: AutomationPaths) -> dict[str, Any]:
    state = load_state(paths)
    payload = dict(state)
    repo_root = paths.state_path.parents[3] if len(paths.state_path.parents) > 3 else paths.state_path.parent
    launcher = repo_root / "tools" / "start_premarket_perp_listing_automation_visible.ps1"
    payload["status_command"] = f"pwsh -NoProfile -ExecutionPolicy Bypass -File {launcher} -Status -Json"
    payload["state_path"] = str(paths.state_path)
    payload["ledger_path"] = str(paths.ledger_path)
    payload["manifest_path"] = str(paths.manifest_path) if paths.manifest_path else None
    return payload


def run_tick(
    paths: AutomationPaths,
    *,
    venues: Iterable[str] = VENUES,
    max_contracts_per_venue: int = 25,
    timeout_sec: float = 10.0,
    websocket_duration_sec: float = 10.0,
    attempt_id: str | None = None,
    external_worker_pid: int | None = None,
    external_worker_process_started_at_utc: str | None = None,
    running_evidence_already_persisted: bool = False,
) -> dict[str, Any]:
    reconcile_prepared_receipts(paths)
    state = load_state(paths)
    prior_cadence = {
        key: state.get(key)
        for key in (
            "cadence_stage",
            "cadence_seconds",
            "cadence_minutes",
            "cadence_reason",
            "event_eta_utc",
            "official_confirmation",
            "exact_timestamp",
        )
    }
    attempt_id = attempt_id or f"premarket_perp_automation_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
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
        started = str(state.get("last_started_at_utc") or utc_iso())
    else:
        started = utc_iso()
        state.update({"status": "RUNNING", "attempt_count": int(state.get("attempt_count", 0)) + 1, "last_attempt_id": attempt_id, "last_started_at_utc": started, "worker_pid": worker_pid, "worker_process_started_at_utc": external_worker_process_started_at_utc})
    events_path = paths.events_path or paths.state_path.with_name("premarket_events.jsonl")
    try:
        if not running_evidence_already_persisted:
            append_attempt(paths, {"attempt_id": attempt_id, "status": "RUNNING", "started_at_utc": started, "worker_pid": worker_pid, "worker_process_started_at_utc": external_worker_process_started_at_utc})
            save_state(paths, state)
        result = discover_and_snapshot(adapters=build_public_adapters(venues, timeout_sec=timeout_sec), events_path=events_path, max_contracts_per_venue=max_contracts_per_venue, websocket_duration_sec=websocket_duration_sec)
        failed = [venue for venue, outcome in result["outcomes"].items() if outcome.get("status") != "COMPLETE"]
        status = "PARTIAL_RETRY_NEXT_INTERVAL" if failed and len(failed) < len(result["outcomes"]) else "RETRY_NEXT_INTERVAL" if failed else "COMPLETE"
        cadence = decide_cadence(result.get("cadence_observation"))
        cadence_fields = {
            "cadence_stage": cadence.stage.value,
            "cadence_seconds": cadence.interval_sec,
            "cadence_minutes": cadence.interval_sec // 60,
            "cadence_reason": cadence.reason,
            "event_eta_utc": cadence.event_eta_utc,
            "official_confirmation": bool((result.get("cadence_observation") or {}).get("official_confirmed")),
            "exact_timestamp": bool((result.get("cadence_observation") or {}).get("exact_timestamp")),
            "next_interval_at_utc": cadence.next_interval_at_utc,
        }
        prior_interval = int(prior_cadence.get("cadence_seconds") or SEARCH_INTERVAL_SEC)
        if (
            failed
            and prior_cadence.get("event_eta_utc")
            and prior_interval in {SCHEDULED_INTERVAL_SEC, 3600, 10800, SEARCH_INTERVAL_SEC}
            and prior_interval < cadence.interval_sec
        ):
            # A failed acquisition cannot erase a previously known near event
            # and postpone its retry to SEARCH.  Preserve the closer cadence;
            # the next successful observation may retire or revise it.
            cadence_fields.update(prior_cadence)
            cadence_fields["next_interval_at_utc"] = next_interval_iso(interval_sec=prior_interval)
        state.update({"status": status, "pending_retry": bool(failed), **cadence_fields, "last_finished_at_utc": utc_iso(), "worker_pid": None, "worker_process_started_at_utc": None, "outcomes": result["outcomes"], "accrual": {"contracts_seen": result["contracts_seen"], "events_written": result["events_written"], "complete_events": 0}, "last_error": "; ".join(failed) if failed else None})
        if failed:
            state["retry_count"] = int(state.get("retry_count", 0)) + 1
        terminal_reason = "; ".join(failed) if failed else None
        if paths.manifest_path is None:
            raise RuntimeError("manifest_path_missing")
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
            next_interval_at_utc=state["next_interval_at_utc"],
            expected_manifest_path=str(paths.manifest_path),
            expected_manifest_sha256=_manifest_payload_sha256(prepared_manifest),
        )
        _write_manifest(
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
        )
        receipt_ref = dict(terminal["terminal_receipt"])
        return {"ok": not failed, "attempt_id": attempt_id, "status": status, "result": result, "cadence": cadence.as_dict(), "next_interval_at_utc": state["next_interval_at_utc"], "terminal_receipt": receipt_ref}
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        state, next_at = mark_retry_next_interval(
            state,
            reason,
            interval_sec=int(state.get("cadence_seconds") or SEARCH_INTERVAL_SEC),
        )
        state.update({"last_finished_at_utc": utc_iso(), "worker_pid": None, "worker_process_started_at_utc": None})
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
        manifest_error = _finalize_failed_attempt(
            paths,
            attempt_id=attempt_id,
            status=state["status"],
            finished_at_utc=utc_iso(),
            reason=reason,
            next_interval_at_utc=next_at,
            state_error=state_error,
            worker_error=worker_error,
        )
        return {
            "ok": False,
            "attempt_id": attempt_id,
            "status": state["status"],
            "reason": reason,
            "manifest_error": manifest_error,
            "state_error": state_error,
            "worker_error": worker_error,
            "next_interval_at_utc": next_at,
            "terminal_receipt": _receipt_reference(paths, failure_receipt),
        }


def _default_paths(repo_root: Path) -> AutomationPaths:
    run_dir = repo_root / "docs" / "agent-log" / "run-gates"
    return AutomationPaths(
        state_path=run_dir / "premarket_perp_listing_automation_state.json",
        ledger_path=run_dir / "premarket_perp_listing_automation_attempts.jsonl",
        claim_path=run_dir / "premarket_perp_listing_automation.claim.json",
        launch_path=run_dir / "premarket_perp_listing_automation.launch.json",
        worker_error_path=run_dir / "premarket_perp_listing_automation.worker-error.log",
        events_path=repo_root / "exports" / "trading-mvp" / "premarket-perp" / "raw_events.jsonl",
        manifest_path=repo_root / "exports" / "trading-mvp" / "premarket-perp" / "manifest.json",
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description="Public pre-market perpetual automation worker")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--tick", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-contracts-per-venue", type=int, default=25)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--websocket-duration-sec", type=float, default=10.0)
    parser.add_argument("--attempt-id")
    parser.add_argument("--worker-handoff-token")
    parser.add_argument("--plan-hash")
    args = parser.parse_args()
    paths = _default_paths(Path(args.repo_root))
    if args.preflight:
        payload = official_preflight_contract() | {"adapters": sorted(ADAPTERS), "automation_id": AUTOMATION_ID}
    elif args.status:
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
        payload = {"ok": True, "usage": "--preflight, --status or --tick"}
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
