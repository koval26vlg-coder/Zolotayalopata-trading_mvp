from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

try:
    import psutil
except ModuleNotFoundError:  # Offline contract tests do not need process telemetry.
    class _PsutilFallback:
        class Error(RuntimeError):
            pass

        STATUS_ZOMBIE = "zombie"

        @staticmethod
        def cpu_count() -> int | None:
            return os.cpu_count()

        @classmethod
        def Process(cls, _pid: int) -> Any:  # noqa: N802
            raise cls.Error("psutil is required for a real campaign launch")

    psutil = _PsutilFallback()  # type: ignore[assignment]

try:
    from dense_ws_campaign_contract import (
        PLAN_SCHEMA,
        _read_json,
        sha256_file,
        validate_contract,
        validate_plan,
        validate_policy_binding,
    )
    from global_market_writer_claim import (
        attach_writer_pid as attach_global_writer_pid,
        claim_global_market_writer,
        inspect_global_market_writer_claim,
        release_global_market_writer,
    )
except ModuleNotFoundError:  # pragma: no cover - package import path
    from .dense_ws_campaign_contract import (
        PLAN_SCHEMA,
        _read_json,
        sha256_file,
        validate_contract,
        validate_plan,
        validate_policy_binding,
    )
    from .global_market_writer_claim import (
        attach_writer_pid as attach_global_writer_pid,
        claim_global_market_writer,
        inspect_global_market_writer_claim,
        release_global_market_writer,
    )


STATE_SCHEMA = "trading_mvp_dense_ws_campaign_runtime_state_v1"
LAUNCH_SCHEMA = "trading_mvp_dense_ws_campaign_launch_record_v1"
RESERVATION_SCHEMA = "trading_mvp_dense_ws_campaign_launch_reservation_v1"
MANIFEST_SCHEMA = "trading_mvp_dense_ws_campaign_manifest_v1"
PREFLIGHT_SCHEMA = "trading_mvp_dense_ws_campaign_preflight_v1"
STOP_SCHEMA = "trading_mvp_dense_ws_campaign_stop_request_v1"
PRESTART_ALLOWANCE_SEC = 1_800
LATE_START_TOLERANCE_SEC = 300
MONITOR_INTERVAL_SEC = 10
MIN_DISK_FREE_BYTES = 50 * 1024**3
RAW_SCHEMA_SAMPLE_LINES = 20
VENUE_SAMPLE_LINES_PER_FILE = 100
SYMBOL_DISCOVERY_LEAD_SEC = 300
RESERVATION_TOKEN_ENV = "TRADING_MVP_DENSE_WS_RESERVATION_TOKEN"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def redacted_process_command() -> list[str]:
    command = [sys.executable]
    redact_next = False
    for item in sys.argv:
        if redact_next:
            command.append("<redacted>")
            redact_next = False
            continue
        command.append(item)
        if item == "--reservation-token":
            redact_next = True
    return command


def reservation_token_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_control_record(
    record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if record is None:
        return None
    redacted = dict(record)
    for token_name in ("reservation_token", "ownership_token"):
        if token_name in redacted:
            redacted[f"{token_name}_present"] = bool(redacted.pop(token_name))
    return redacted


def parse_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp lacks UTC offset: {value!r}")
    return parsed


def read_json(path: str | Path) -> dict[str, Any]:
    return _read_json(path)


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise


def process_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        process = psutil.Process(value)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.Error, OSError):
        return False


def nearest_existing_parent(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    while not candidate.exists():
        if candidate.parent == candidate:
            raise FileNotFoundError(path)
        candidate = candidate.parent
    return candidate


def run_json_command(arguments: Sequence[str], *, timeout: int = 60) -> dict[str, Any]:
    completed = subprocess.run(
        list(arguments),
        cwd=str(Path(__file__).resolve().parents[2]),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(arguments)}; {detail}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"command did not return JSON: {' '.join(arguments)}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("command JSON must be an object")
    return payload


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_policy_path() -> Path:
    return project_root() / "docs" / "plans" / "trading-mvp-autopilot-policy-v1.json"


def global_writer_claim_path() -> Path:
    return project_root() / "docs" / "agent-log" / "active-market-data-writer-claim.json"


def control_paths(plan: Mapping[str, Any]) -> dict[str, Path]:
    root = Path(str(plan["outputs"]["campaign_root"])).expanduser().resolve()
    control = root / "_control"
    return {
        "root": root,
        "control": control,
        "reservation": control / "launch-reservation.json",
        "owner": control / "owner.json",
        "state": control / "campaign-state.json",
        "launch": control / "launch-record.json",
        "stop": control / "stop-request.json",
        "symbol_plan": control / "symbol-plan.json",
        "manifest": root / "campaign-manifest.json",
    }


def load_validated_bundle(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    policy_path: str | Path | None,
    verify_policy: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = read_json(resolved_plan)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported dense WS PlanOnly schema")
    if str(plan.get("plan_hash") or "") != expected_plan_hash:
        raise ValueError("ExpectedPlanHash does not match immutable PlanOnly")
    contract_path = Path(str(plan["contract"]["path"])).expanduser().resolve()
    contract = read_json(contract_path)
    validate_contract(contract, verify_files=True)
    validate_plan(plan, contract=contract, verify_files=True)
    policy: dict[str, Any] | None = None
    if verify_policy:
        if policy_path is None:
            raise ValueError("policy path is required")
        resolved_policy = Path(policy_path).expanduser().resolve()
        policy = read_json(resolved_policy)
        validate_policy_binding(
            policy,
            contract=contract,
            plan=plan,
            contract_path=contract_path,
            plan_path=resolved_plan,
        )
    tools = plan["launch_controls"]["tools"]
    runner = tools.get("runner")
    if not isinstance(runner, Mapping):
        raise ValueError("PlanOnly does not bind the campaign runner")
    this_file = Path(__file__).resolve()
    if Path(str(runner.get("path") or "")).resolve() != this_file:
        raise ValueError("PlanOnly runner path does not bind this module")
    if str(runner.get("sha256") or "") != sha256_file(this_file):
        raise ValueError("PlanOnly runner hash does not bind this module")
    if plan["approval_state"] != "NOT_APPROVED":
        raise ValueError("immutable PlanOnly approval_state must remain NOT_APPROVED")
    return contract, plan, policy


def gate_status() -> dict[str, Any]:
    checker = project_root() / "tools" / "check_active_run_gate.ps1"
    return run_json_command(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checker),
            "-Json",
        ]
    )


def autopilot_status() -> dict[str, Any]:
    checker = project_root() / "tools" / "check_trading_mvp_autopilot.ps1"
    return run_json_command(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checker),
            "-Json",
        ],
        timeout=120,
    )


def output_namespace_conflicts(plan: Mapping[str, Any]) -> list[str]:
    conflicts: list[str] = []
    for raw in plan["outputs"]["phase_namespaces"]:
        path = Path(str(raw)).expanduser().resolve()
        if not path.exists():
            continue
        try:
            if any(path.iterdir()):
                conflicts.append(str(path))
        except OSError:
            conflicts.append(str(path))
    manifest = Path(str(plan["outputs"]["campaign_root"])) / "campaign-manifest.json"
    if manifest.exists():
        conflicts.append(str(manifest.resolve()))
    return conflicts


def directory_size_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def classify_launch_window(plan: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    start = parse_time(plan["window"]["start_local"])
    latest = start + timedelta(seconds=LATE_START_TOLERANCE_SEC)
    earliest = start - timedelta(seconds=PRESTART_ALLOWANCE_SEC)
    if now < earliest:
        status = "NOT_DUE"
    elif now <= latest:
        status = "DUE"
    else:
        status = "EXPIRED"
    return {
        "status": status,
        "observed_at": now.isoformat(),
        "earliest_launch_at": earliest.isoformat(),
        "writer_start_at": start.isoformat(),
        "latest_launch_at": latest.isoformat(),
        "seconds_to_writer_start": round((start - now).total_seconds()),
    }


def preflight(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    policy_path: str | Path,
    now: datetime | None = None,
    require_due: bool = False,
) -> dict[str, Any]:
    contract, plan, _ = load_validated_bundle(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        policy_path=policy_path,
        verify_policy=True,
    )
    paths = control_paths(plan)
    observed = now or utc_now()
    window = classify_launch_window(plan, observed)
    reasons: list[str] = []
    if plan["launch_controls"]["status"] != "READY_FOR_SEPARATE_EXACT_APPROVAL":
        reasons.append(
            "long_campaign_contract_not_approval_ready:"
            f"{plan['launch_controls']['status']}"
        )
    owner = read_json(paths["owner"]) if paths["owner"].exists() else None
    reservation = (
        read_json(paths["reservation"]) if paths["reservation"].exists() else None
    )
    state = read_json(paths["state"]) if paths["state"].exists() else None
    if owner:
        reasons.append("campaign_owner_record_exists")
        if process_alive(owner.get("orchestrator_pid")):
            reasons.append("live_campaign_owner_exists")
    if reservation:
        reasons.append("launch_reservation_exists")
        if process_alive(reservation.get("orchestrator_pid")) or process_alive(
            reservation.get("terminal_pid")
        ):
            reasons.append("live_launch_reservation_exists")
    if state and str(state.get("status") or "") == "STOPPED_INCOMPLETE":
        reasons.append("stopped_incomplete_requires_new_exact_recovery_approval")
    if state and str(state.get("status") or "") in {
        "READY_FOR_POSTPROCESS",
        "COMPLETE",
    }:
        reasons.append("campaign_already_completed")
    reasons.extend(
        f"nonempty_output_namespace:{item}" for item in output_namespace_conflicts(plan)
    )
    gate = gate_status()
    if str(gate.get("status") or "") in {"RUNNING", "STOPPED_INCOMPLETE"}:
        reasons.append(
            f"active_gate_{str(gate.get('status')).lower()}:{gate.get('run_id')}"
        )
    live_ids = [
        int(item) for item in gate.get("live_process_ids") or [] if process_alive(item)
    ]
    if live_ids:
        reasons.append(f"active_gate_live_processes:{','.join(map(str, live_ids))}")
    active_writer_claim: dict[str, Any] | None = None
    try:
        active_writer_claim = inspect_global_market_writer_claim(
            global_writer_claim_path()
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reasons.append(f"global_writer_claim_unreadable:{type(exc).__name__}")
    if active_writer_claim is not None:
        reasons.append(
            "global_writer_claim_exists:"
            f"{active_writer_claim.get('run_id')}:{active_writer_claim.get('owner_pid')}"
        )
    disk_root = nearest_existing_parent(paths["root"])
    free_bytes = shutil.disk_usage(disk_root).free
    required_free = max(
        MIN_DISK_FREE_BYTES,
        int(plan["resources"]["estimated_disk_bytes"]) * 2,
    )
    if free_bytes < required_free:
        reasons.append("insufficient_disk_headroom")
    hard_output_cap = int(plan["resources"].get("hard_output_cap_bytes") or 0)
    estimated_output = int(plan["resources"]["estimated_disk_bytes"])
    existing_output = directory_size_bytes(paths["root"])
    if hard_output_cap <= 0:
        reasons.append("hard_output_cap_missing_or_invalid")
    elif estimated_output > hard_output_cap:
        reasons.append("estimated_output_exceeds_hard_output_cap")
    elif existing_output >= hard_output_cap:
        reasons.append("campaign_output_cap_already_reached")
    if require_due and window["status"] != "DUE":
        reasons.append(f"launch_window_{str(window['status']).lower()}")
    structurally_valid = not [
        item for item in reasons if not item.startswith("launch_window_")
    ]
    can_launch_now = not reasons and window["status"] == "DUE"
    status = (
        "READY_FOR_EXACT_APPROVAL_LAUNCH"
        if can_launch_now
        else (
            "STRUCTURALLY_VALID_NOT_DUE"
            if structurally_valid and window["status"] == "NOT_DUE"
            else "BLOCKED"
        )
    )
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": status,
        "structurally_valid": structurally_valid,
        "can_launch_now": can_launch_now,
        "no_run_or_output_writes": True,
        "campaign_id": plan["campaign_id"],
        "candidate_contract_hash": contract["source_candidate"][
            "candidate_contract_hash"
        ],
        "contract_hash": contract["contract_hash"],
        "plan_path": str(Path(plan_path).expanduser().resolve()),
        "plan_hash": expected_plan_hash,
        "approval_state": plan["approval_state"],
        "launch_control_status": plan["launch_controls"]["status"],
        "window": window,
        "gate_status": gate.get("status"),
        "gate_run_id": gate.get("run_id"),
        "free_bytes": free_bytes,
        "required_free_bytes": required_free,
        "existing_campaign_output_bytes": existing_output,
        "hard_output_cap_bytes": hard_output_cap,
        "global_writer_claim": redact_control_record(active_writer_claim),
        "global_writer_claim_path": str(global_writer_claim_path()),
        "reasons": reasons,
    }


def assert_fresh_runtime_guard(plan: Mapping[str, Any]) -> dict[str, Any]:
    state = autopilot_status()
    remaining = float((state.get("usage") or {}).get("remaining_percent") or 0.0)
    if remaining <= 15.0:
        raise RuntimeError(f"weekly quota remaining is {remaining}%, must exceed 15%")
    candidate = state.get("long_campaign_candidate") or {}
    if candidate.get("status") != "READY_FOR_APPROVAL":
        raise RuntimeError("authoritative guard does not expose READY_FOR_APPROVAL")
    if candidate.get("plan_hash") != plan.get("plan_hash"):
        raise RuntimeError("authoritative guard plan hash mismatch")
    if state.get("status") != "ACTIVE" or state.get("stop_new_actions"):
        raise RuntimeError("authoritative guard blocks new actions")
    return state


def assert_runtime_gate_clear() -> dict[str, Any]:
    gate = gate_status()
    status = str(gate.get("status") or "")
    live_ids = [
        int(item) for item in gate.get("live_process_ids") or [] if process_alive(item)
    ]
    if status in {"RUNNING", "STOPPED_INCOMPLETE"} or live_ids:
        raise RuntimeError(
            f"active gate is not clear: status={status}, "
            f"run_id={gate.get('run_id')}, live_process_ids={live_ids}"
        )
    return gate


def symbol_base(symbol: str, *, exchange: str, quote: str = "USDT") -> str:
    value = symbol.strip().upper()
    if exchange == "gateio":
        suffix = f"_{quote}"
    else:
        suffix = quote
    if not value.endswith(suffix) or len(value) <= len(suffix):
        raise ValueError(f"unexpected {exchange} symbol: {symbol}")
    return value[: -len(suffix)]


def validate_symbol_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    symbols = payload.get("symbols_by_exchange")
    if not isinstance(symbols, Mapping) or set(symbols) != {"mexc", "gateio"}:
        raise ValueError("symbol plan must contain exactly mexc and gateio")
    bases: dict[str, set[str]] = {}
    for exchange in ("mexc", "gateio"):
        values = symbols.get(exchange)
        if not isinstance(values, list):
            raise ValueError(f"symbol plan {exchange} list is missing")
        if not 10 <= len(values) <= 16:
            raise ValueError(f"symbol plan {exchange} count is outside [10,16]")
        normalized = [str(item).strip().upper() for item in values]
        if normalized != values:
            raise ValueError(
                f"symbol plan {exchange} symbols must be canonical uppercase"
            )
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"symbol plan {exchange} contains duplicate symbols")
        bases[exchange] = {symbol_base(item, exchange=exchange) for item in normalized}
        if len(bases[exchange]) != len(normalized):
            raise ValueError(f"symbol plan {exchange} contains duplicate base assets")
    expected_symbols_arg = ";".join(
        f"{exchange}:{','.join(symbols[exchange])}"
        for exchange in sorted(("mexc", "gateio"))
    )
    if payload.get("symbols_arg") != expected_symbols_arg:
        raise ValueError("symbol plan symbols_arg does not match symbols_by_exchange")
    denominator = min(len(bases["mexc"]), len(bases["gateio"]))
    coverage = len(bases["mexc"] & bases["gateio"]) / float(denominator)
    if coverage < 0.8:
        raise ValueError(f"dual-venue base coverage is {coverage:.4f}, below 0.8")
    return {
        "mexc_pairs": len(symbols["mexc"]),
        "gateio_pairs": len(symbols["gateio"]),
        "matched_bases": len(bases["mexc"] & bases["gateio"]),
        "dual_venue_coverage": round(coverage, 6),
    }


def count_jsonl_lines(paths: Sequence[Path]) -> int:
    total = 0
    for path in paths:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += chunk.count(b"\n")
    return total


def phase_manifest_ready(
    manifest: Mapping[str, Any] | None,
    *,
    writer_exit_code: int | None,
    errors: Sequence[Any],
    schema_checked: bool,
    zero_checked: bool,
    density_checked: bool,
) -> bool:
    return bool(
        writer_exit_code == 0
        and manifest
        and manifest.get("runtime_completed") is True
        and manifest.get("liveness_clean") is True
        and manifest.get("quality_eligible") is True
        and not (manifest.get("dirty_segment_ids") or [])
        and manifest.get("completed") is True
        and manifest.get("final") is True
        and float(manifest.get("coverage_ratio") or 0.0) >= 0.99
        and int(manifest.get("market_envelope_rows") or 0) > 0
        and not errors
        and schema_checked
        and zero_checked
        and density_checked
    )


def validate_raw_envelope(row: Any, *, path: Path) -> dict[str, Any]:
    required = {"recv_ts", "exchange", "event_type", "channel", "symbol", "payload"}
    if not isinstance(row, dict) or set(row) != required:
        raise ValueError(f"raw envelope mismatch in {path}")
    recv_ts = row["recv_ts"]
    if (
        isinstance(recv_ts, bool)
        or not isinstance(recv_ts, (int, float))
        or not math.isfinite(float(recv_ts))
    ):
        raise ValueError(f"raw recv_ts is not finite in {path}")
    exchange = row["exchange"]
    if exchange not in {"mexc", "gateio"}:
        raise ValueError(f"raw exchange is unsupported in {path}: {exchange!r}")
    event_type = row["event_type"]
    if not isinstance(event_type, str) or not event_type:
        raise ValueError(f"raw event_type is invalid in {path}")
    if row["channel"] is not None and not isinstance(row["channel"], str):
        raise ValueError(f"raw channel is invalid in {path}")
    if row["symbol"] is not None and not isinstance(row["symbol"], str):
        raise ValueError(f"raw symbol is invalid in {path}")
    payload = row["payload"]
    if not isinstance(payload, dict):
        raise ValueError(f"raw payload is not an object in {path}")
    encoding = payload.get("encoding")
    if encoding in {"json", "text"}:
        if set(payload) != {"encoding", "data"}:
            raise ValueError(f"raw {encoding} payload fields mismatch in {path}")
        if encoding == "text" and not isinstance(payload["data"], str):
            raise ValueError(f"raw text payload data is invalid in {path}")
    elif encoding == "base64":
        if set(payload) != {"encoding", "byte_length", "data"}:
            raise ValueError(f"raw base64 payload fields mismatch in {path}")
        if (
            isinstance(payload["byte_length"], bool)
            or not isinstance(payload["byte_length"], int)
            or payload["byte_length"] < 0
            or not isinstance(payload["data"], str)
        ):
            raise ValueError(f"raw base64 payload data is invalid in {path}")
    else:
        raise ValueError(f"raw payload encoding is unsupported in {path}: {encoding!r}")
    return row


def iter_complete_jsonl_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            # A concurrently written final line is not evidence until its newline lands.
            if not raw.endswith("\n"):
                continue
            yield validate_raw_envelope(json.loads(raw), path=path)


def schema_probe(
    paths: Sequence[Path], max_lines: int = RAW_SCHEMA_SAMPLE_LINES
) -> dict[str, Any]:
    checked = 0
    exchanges: set[str] = set()
    symbols: dict[str, set[str]] = {"mexc": set(), "gateio": set()}
    for path in paths:
        if checked >= max_lines:
            break
        for row in iter_complete_jsonl_rows(path):
            exchange = str(row["exchange"])
            exchanges.add(exchange)
            if row.get("symbol"):
                symbols[exchange].add(str(row["symbol"]))
            checked += 1
            if checked >= max_lines:
                break
    if checked < max_lines:
        raise ValueError(
            f"raw schema probe found {checked} complete rows; requires {max_lines}"
        )
    return {
        "checked_lines": checked,
        "exchanges": sorted(exchanges),
        "symbols_seen": {key: len(value) for key, value in symbols.items()},
    }


def venue_presence_probe(
    paths: Sequence[Path],
    *,
    max_lines_per_file: int = VENUE_SAMPLE_LINES_PER_FILE,
) -> dict[str, Any]:
    sampled_rows = {"mexc": 0, "gateio": 0}
    files_by_venue = {"mexc": set(), "gateio": set()}
    for path in paths:
        checked = 0
        for row in iter_complete_jsonl_rows(path):
            exchange = str(row["exchange"])
            sampled_rows[exchange] += 1
            files_by_venue[exchange].add(str(path))
            checked += 1
            if checked >= max_lines_per_file:
                break
    missing = [venue for venue, rows in sampled_rows.items() if rows <= 0]
    if missing:
        raise ValueError(f"raw rows missing for venues: {','.join(missing)}")
    return {
        "sampled_rows_by_venue": sampled_rows,
        "files_by_venue": {
            venue: len(paths_for_venue)
            for venue, paths_for_venue in files_by_venue.items()
        },
    }


def terminate_writer(process: subprocess.Popen[Any], *, reason: str) -> None:
    if process.poll() is not None:
        return
    print(f"Stopping writer: {reason}", flush=True)
    try:
        if os.name == "nt":
            process.send_signal(getattr(signal, "CTRL_BREAK_EVENT"))
        else:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=20)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.terminate()
        process.wait(timeout=10)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    process.kill()
    process.wait(timeout=10)


class CampaignRuntime:
    def __init__(
        self,
        *,
        contract: dict[str, Any],
        plan: dict[str, Any],
        plan_path: Path,
        expected_plan_hash: str,
        policy_path: Path,
        reservation_token: str,
    ) -> None:
        self.contract = contract
        self.plan = plan
        self.campaign_id = str(plan["campaign_id"])
        self.candidate_contract_hash = str(
            contract["source_candidate"]["candidate_contract_hash"]
        )
        self.universe_sha256 = str(
            contract["universe_contract"]["source"]["sha256"]
        )
        self.plan_path = plan_path
        self.expected_plan_hash = expected_plan_hash
        self.policy_path = policy_path
        self.reservation_token = reservation_token
        self.paths = control_paths(plan)
        self.stop_requested = False
        self.writer: subprocess.Popen[Any] | None = None
        self.current_phase: dict[str, Any] | None = None
        self.phase_results: list[dict[str, Any]] = []
        self.symbol_plan_sha256: str | None = None
        self.previous_gate_bytes: bytes | None = None
        self.previous_gate_path = (
            project_root() / "docs" / "agent-log" / "active-run-gate.json"
        )
        self.current_pointer_path = (
            project_root() / "docs" / "agent-log" / "current-run.json"
        )
        self.previous_pointer_bytes: bytes | None = None
        self.global_claim_path = global_writer_claim_path()
        self.global_claim_token: str | None = None
        self.global_claim_run_id: str | None = None
        self.phase_gate_claimed = False

    def acquire_global_writer_claim(self, phase: Mapping[str, Any]) -> None:
        if self.global_claim_token is not None:
            raise RuntimeError("orchestrator already owns a global writer claim")
        claim = claim_global_market_writer(
            self.global_claim_path,
            run_id=str(phase["run_id"]),
            owner_pid=os.getpid(),
            owner_kind="dense_ws_campaign_phase",
            plan_hash=self.expected_plan_hash,
            output_namespace=str(phase["output_namespace"]),
            terminal_pid=os.getppid(),
        )
        self.global_claim_token = str(claim["ownership_token"])
        self.global_claim_run_id = str(phase["run_id"])

    def attach_global_writer(self, writer_pid: int) -> None:
        if self.global_claim_token is None or self.global_claim_run_id is None:
            raise RuntimeError("global writer claim is not owned")
        attach_global_writer_pid(
            self.global_claim_path,
            run_id=self.global_claim_run_id,
            owner_pid=os.getpid(),
            ownership_token=self.global_claim_token,
            writer_pid=writer_pid,
        )

    def release_global_writer_claim(self, final_status: str) -> None:
        if self.global_claim_token is None or self.global_claim_run_id is None:
            return
        archive_path = release_global_market_writer(
            self.global_claim_path,
            run_id=self.global_claim_run_id,
            owner_pid=os.getpid(),
            ownership_token=self.global_claim_token,
            final_status=final_status,
        )
        self.global_claim_token = None
        self.global_claim_run_id = None
        self.update_state(
            "GLOBAL_WRITER_CLAIM_RELEASED",
            claim_final_status=final_status,
            global_writer_claim_archive_path=str(archive_path),
        )

    def campaign_output_bytes(self) -> int:
        return directory_size_bytes(self.paths["root"])

    def update_state(self, status: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "schema": STATE_SCHEMA,
            "campaign_id": self.campaign_id,
            "status": status,
            "updated_at_utc": iso_now(),
            "orchestrator_pid": os.getpid(),
            "writer_pid": self.writer.pid
            if self.writer and self.writer.poll() is None
            else None,
            "plan_path": str(self.plan_path),
            "plan_hash": self.expected_plan_hash,
            "contract_hash": self.contract["contract_hash"],
            "current_phase_id": (
                self.current_phase.get("phase_id") if self.current_phase else None
            ),
            "phase_results": self.phase_results,
            "symbol_plan_path": str(self.paths["symbol_plan"]),
            "symbol_plan_sha256": self.symbol_plan_sha256,
            "stop_request_path": str(self.paths["stop"]),
        }
        payload.update(extra)
        write_json_atomic(self.paths["state"], payload)

    def stop_signal_handler(self, signum: int, _frame: Any) -> None:
        self.stop_requested = True
        self.update_state("STOP_REQUESTED", signal=signum)

    def adopt_reservation(self) -> None:
        reservation = read_json(self.paths["reservation"])
        if reservation.get("schema") != RESERVATION_SCHEMA:
            raise ValueError("launch reservation schema mismatch")
        if reservation.get("campaign_id") != self.campaign_id:
            raise ValueError("launch reservation campaign mismatch")
        if reservation.get("reservation_token") != self.reservation_token:
            raise ValueError("launch reservation token mismatch")
        if reservation.get("plan_hash") != self.expected_plan_hash:
            raise ValueError("launch reservation plan hash mismatch")
        if (
            Path(str(reservation.get("plan_path") or "")).expanduser().resolve()
            != self.plan_path
        ):
            raise ValueError("launch reservation plan path mismatch")
        if (
            Path(str(reservation.get("policy_path") or "")).expanduser().resolve()
            != self.policy_path
        ):
            raise ValueError("launch reservation policy path mismatch")
        if reservation.get("explicit_confirmation") is not True:
            raise ValueError("launch reservation lacks explicit confirmation")
        if not process_alive(reservation.get("top_level_pid")):
            raise ValueError("top-level visible launcher is not alive")
        observed_terminal_pid = os.getppid()
        try:
            expected_terminal_pid = int(reservation.get("expected_terminal_pid"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "launch reservation lacks expected terminal PID"
            ) from exc
        if expected_terminal_pid != observed_terminal_pid:
            raise ValueError(
                "visible terminal PID does not match the parent-bound reservation"
            )
        if not process_alive(expected_terminal_pid):
            raise ValueError("parent-bound visible terminal is not alive")
        reservation["terminal_pid"] = observed_terminal_pid
        reservation["orchestrator_pid"] = os.getpid()
        reservation["adopted_at_utc"] = iso_now()
        write_json_atomic(self.paths["reservation"], reservation)
        owner = {
            "schema": "trading_mvp_dense_ws_campaign_owner_v1",
            "campaign_id": self.campaign_id,
            "orchestrator_pid": os.getpid(),
            "reservation_token_sha256": reservation_token_sha256(
                self.reservation_token
            ),
            "terminal_pid": observed_terminal_pid,
            "plan_hash": self.expected_plan_hash,
            "started_at_utc": iso_now(),
            "final": False,
        }
        write_json_immutable(self.paths["owner"], owner)

    def write_launch_record(self, guard: Mapping[str, Any]) -> None:
        reservation = read_json(self.paths["reservation"])
        record = {
            "schema": LAUNCH_SCHEMA,
            "campaign_id": self.campaign_id,
            "created_at_utc": iso_now(),
            "terminal_pid": reservation.get("terminal_pid"),
            "orchestrator_pid": os.getpid(),
            "top_level_launcher_pid": reservation.get("top_level_pid"),
            "orchestrator_command": redacted_process_command(),
            "cwd": str(project_root()),
            "plan_path": str(self.plan_path),
            "plan_file_sha256": sha256_file(self.plan_path),
            "plan_hash": self.expected_plan_hash,
            "contract_path": self.plan["contract"]["path"],
            "contract_file_sha256": self.plan["contract"]["file_sha256"],
            "contract_hash": self.contract["contract_hash"],
            "candidate_contract_hash": self.candidate_contract_hash,
            "universe_sha256": self.universe_sha256,
            "guard_observed_at_utc": guard.get("observed_at_utc"),
            "weekly_remaining_percent": (guard.get("usage") or {}).get(
                "remaining_percent"
            ),
            "campaign_output_root": str(self.paths["root"]),
            "global_writer_claim_path": str(self.global_claim_path),
            "campaign_manifest_path": str(self.paths["manifest"]),
            "phase_output_namespaces": self.plan["outputs"]["phase_namespaces"],
            "expected_writer_duration_sec": self.plan["window"]["target_writer_sec"],
            "expected_elapsed_sec": self.plan["window"]["expected_elapsed_sec"],
            "hard_deadline_local": self.plan["window"]["hard_deadline_local"],
            "status_command": self.plan["launch_controls"]["status_command"],
            "stop_command": self.plan["launch_controls"]["stop_command"],
            "visible_terminal_required": True,
            "single_writer": True,
            "actual_collection_authorized_by_runtime_switch": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        }
        write_json_immutable(self.paths["launch"], record)

    def discover_symbols(self) -> dict[str, Any]:
        if self.paths["symbol_plan"].exists():
            payload = read_json(self.paths["symbol_plan"])
            validate_symbol_plan(payload)
            if payload.get("campaign_id") != self.campaign_id:
                raise ValueError("symbol plan campaign mismatch")
            if payload.get("plan_hash") != self.expected_plan_hash:
                raise ValueError("symbol plan PlanOnly hash mismatch")
            if payload.get("contract_hash") != self.contract["contract_hash"]:
                raise ValueError("symbol plan contract hash mismatch")
            if payload.get("universe_sha256") != self.universe_sha256:
                raise ValueError("symbol plan universe hash mismatch")
            self.symbol_plan_sha256 = sha256_file(self.paths["symbol_plan"])
            return payload
        source = self.contract["universe_contract"]["source"]
        writer = Path(
            self.contract["source_bindings"]["durable_collector"]["path"]
        ).resolve()
        config = project_root() / "trading_mvp" / "config.json"
        command = [
            sys.executable,
            str(writer),
            "plan-symbols",
            "--config",
            str(config),
            "--exchanges",
            "mexc,gateio",
            "--universe",
            str(source["path"]),
            "--quote",
            "USDT",
            "--max-symbols",
            "300",
            "--max-pairs-per-exchange",
            "16",
        ]
        print("Resolving launch-time public symbol availability", flush=True)
        completed = subprocess.run(
            command,
            cwd=str(project_root()),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"symbol discovery failed ({completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        payload = json.loads(completed.stdout)
        quality = validate_symbol_plan(payload)
        payload["campaign_id"] = self.campaign_id
        payload["created_at_utc"] = iso_now()
        payload["quality"] = quality
        payload["plan_hash"] = self.expected_plan_hash
        payload["contract_hash"] = self.contract["contract_hash"]
        payload["universe_sha256"] = self.universe_sha256
        write_json_immutable(self.paths["symbol_plan"], payload)
        self.symbol_plan_sha256 = sha256_file(self.paths["symbol_plan"])
        return payload

    def wait_until(self, target: datetime, *, status: str) -> None:
        last_report = 0.0
        while utc_now() < target:
            if self.paths["stop"].exists():
                self.stop_requested = True
            if self.stop_requested:
                raise RuntimeError("user_stop_requested")
            remaining = (target - utc_now()).total_seconds()
            now_monotonic = time.monotonic()
            if now_monotonic - last_report >= 30:
                print(
                    f"[{iso_now()}] {status}; starts in {max(0, round(remaining))}s",
                    flush=True,
                )
                self.update_state(
                    status, seconds_to_next_phase=max(0, round(remaining))
                )
                last_report = now_monotonic
            time.sleep(min(MONITOR_INTERVAL_SEC, max(0.25, remaining)))

    def phase_start_blockers(self) -> list[str]:
        blockers: list[str] = []
        gate = gate_status()
        status = str(gate.get("status") or "")
        live_ids = [
            int(item)
            for item in gate.get("live_process_ids") or []
            if process_alive(item)
        ]
        if status in {"RUNNING", "STOPPED_INCOMPLETE"}:
            blockers.append(f"active_gate_{status.lower()}:{gate.get('run_id')}")
        if live_ids:
            blockers.append(
                f"active_gate_live_processes:{','.join(map(str, live_ids))}"
            )
        if blockers:
            return blockers

        guard = autopilot_status()
        usage = guard.get("usage") or {}
        if usage.get("status") != "AVAILABLE":
            blockers.append("weekly_usage_unavailable")
        remaining = float(usage.get("remaining_percent") or 0.0)
        if remaining <= 15.0:
            blockers.append(f"weekly_quota_remaining_{remaining}")
        if guard.get("status") != "ACTIVE" or guard.get("stop_new_actions"):
            blockers.append(
                f"autopilot_guard_blocks:{guard.get('status')}:{guard.get('decision')}"
            )
        candidate = guard.get("long_campaign_candidate") or {}
        if candidate.get("status") != "READY_FOR_APPROVAL":
            blockers.append("long_campaign_candidate_not_ready")
        if candidate.get("plan_hash") != self.expected_plan_hash:
            blockers.append("long_campaign_candidate_plan_hash_mismatch")

        gate_run_id = str(gate.get("run_id") or "")
        if status == "READY_FOR_POSTPROCESS" and gate_run_id.startswith("pit_"):
            disposition = guard.get("pit_postrun_disposition") or {}
            if (
                disposition.get("run_id") != gate_run_id
                or disposition.get("status") != "COMPLETE"
            ):
                blockers.append(
                    "pit_postrun_not_complete:"
                    f"{disposition.get('run_id')}:{disposition.get('status')}"
                )
        return blockers

    def wait_for_gate(self, latest_start: datetime) -> None:
        while True:
            blockers = self.phase_start_blockers()
            if not blockers:
                return
            if utc_now() > latest_start:
                raise RuntimeError(
                    "phase_start_blockers_did_not_clear_before_deadline:"
                    + ",".join(blockers)
                )
            if self.paths["stop"].exists():
                raise RuntimeError("user_stop_requested")
            self.update_state("WAITING_FOR_PHASE_START_GATES", blockers=blockers)
            print(
                "Waiting for phase-start gates: " + ", ".join(blockers),
                flush=True,
            )
            time.sleep(15)

    def publish_owned_gate(
        self,
        gate: dict[str, Any],
        *,
        run_type: str,
    ) -> None:
        run_id = str(gate.get("run_id") or "")
        if not run_id or re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id) != run_id:
            raise ValueError(f"unsafe active gate run_id: {run_id!r}")
        launch_path = (
            self.previous_gate_path.parent / "run-gates" / f"{run_id}.launch.json"
        )
        output = gate.get("output")
        if not isinstance(output, dict):
            output = {
                "path": str(gate.get("output_path") or ""),
                "kind": "directory",
            }
        launch_record = {
            "schema": "active_run_launch_record_v1",
            "project": "trading_mvp",
            "run_id": run_id,
            "run_type": run_type,
            "created_at": gate.get("updated_at"),
            "command": " ".join(redacted_process_command()),
            "cwd": str(project_root()),
            "output": output,
            "manifest_path": str(gate.get("manifest_path") or ""),
            "owner_output_prefix": str(output.get("path") or ""),
            "code_snapshot_hash": sha256_file(Path(__file__).resolve()),
            "plan_path": str(self.plan_path),
            "plan_hash": self.expected_plan_hash,
            "contract_hash": self.contract["contract_hash"],
            "research_only": True,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
        }
        if launch_path.exists():
            existing = read_json(launch_path)
            for key in (
                "schema",
                "project",
                "run_id",
                "run_type",
                "manifest_path",
                "plan_hash",
                "contract_hash",
            ):
                if existing.get(key) != launch_record.get(key):
                    raise RuntimeError(
                        f"canonical launch record integrity conflict: {key}"
                    )
        else:
            write_json_immutable(launch_path, launch_record)
        gate["launch_record_path"] = str(launch_path)
        pointer = {
            "schema": "active_run_pointer_v1",
            "project": "trading_mvp",
            "run_id": run_id,
            "status": gate["status"],
            "updated_at": gate.get("updated_at"),
            "manifest_path": str(gate.get("manifest_path") or ""),
            "output": output,
            "collector_pid": gate.get("collector_pid"),
            "monitor_pid": gate.get("monitor_pid"),
            "process_ids": list(gate.get("process_ids") or []),
            "launch_record_path": str(launch_path),
        }
        write_json_atomic(self.previous_gate_path, gate)
        write_json_atomic(self.current_pointer_path, pointer)

    def claim_gate(self, phase: Mapping[str, Any], writer_pid: int | None) -> None:
        gate_path = self.previous_gate_path
        self.previous_gate_bytes = (
            gate_path.read_bytes() if gate_path.exists() else None
        )
        self.previous_pointer_bytes = (
            self.current_pointer_path.read_bytes()
            if self.current_pointer_path.exists()
            else None
        )
        gate = {
            "schema": "active_run_gate_v2",
            "project": "trading_mvp",
            "run_id": phase["run_id"],
            "run_type": "dense_ws_campaign_phase",
            "campaign_id": self.campaign_id,
            "status": "RUNNING",
            "gate_status": "RUNNING",
            "created_at": datetime.now().astimezone().isoformat(),
            "updated_at": datetime.now().astimezone().isoformat(),
            "purpose": "Visible hash-bound dense WS campaign phase",
            "blocking_rule": (
                "While RUNNING, do not start another writer or consume unfinished output."
            ),
            "monitor_pid": os.getpid(),
            "collector_pid": writer_pid,
            "process_ids": [
                value for value in (os.getpid(), writer_pid) if value is not None
            ],
            "output_path": phase["output_namespace"],
            "output": {
                "path": phase["output_namespace"],
                "kind": "directory",
            },
            "manifest_path": str(
                Path(phase["output_namespace"]) / f"ws_collect_{phase['run_id']}.json"
            ),
            "duration_sec": phase["writer_duration_sec"],
            "plan_path": str(self.plan_path),
            "plan_hash": self.expected_plan_hash,
            "contract_hash": self.contract["contract_hash"],
            "phase_id": phase["phase_id"],
            "hard_deadline_local": phase.get("hard_end_local") or phase["end_local"],
            "notification_required": False,
            "replay_allowed": False,
            "grid_allowed": False,
            "paper_forward_allowed": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "next_step_after_ready": (
                "Do not consume raw output. Complete remaining approved campaign "
                "phases, then run campaign data-quality only."
            ),
        }
        if self.previous_gate_bytes is not None:
            prior_gate = json.loads(self.previous_gate_bytes.decode("utf-8-sig"))
            if "approved_night_schedule" in prior_gate:
                gate["approved_night_schedule"] = prior_gate["approved_night_schedule"]
        self.publish_owned_gate(gate, run_type="dense_ws_campaign_phase")
        self.phase_gate_claimed = True

    def release_gate_for_blackout(self, phase: Mapping[str, Any]) -> None:
        gate_path = self.previous_gate_path
        current = read_json(gate_path) if gate_path.exists() else None
        if current and current.get("run_id") != phase.get("run_id"):
            raise RuntimeError("active gate ownership changed before blackout release")
        pointer = (
            read_json(self.current_pointer_path)
            if self.current_pointer_path.exists()
            else None
        )
        if pointer and pointer.get("run_id") != phase.get("run_id"):
            raise RuntimeError("current-run ownership changed before blackout release")
        if self.previous_gate_bytes is None:
            gate_path.unlink(missing_ok=True)
        else:
            temporary = gate_path.with_name(f"{gate_path.name}.tmp.{os.getpid()}")
            temporary.write_bytes(self.previous_gate_bytes)
            os.replace(temporary, gate_path)
        if self.previous_pointer_bytes is None:
            self.current_pointer_path.unlink(missing_ok=True)
        else:
            temporary = self.current_pointer_path.with_name(
                f"{self.current_pointer_path.name}.tmp.{os.getpid()}"
            )
            temporary.write_bytes(self.previous_pointer_bytes)
            os.replace(temporary, self.current_pointer_path)
        self.previous_gate_bytes = None
        self.previous_pointer_bytes = None
        self.phase_gate_claimed = False

    def attach_writer_to_gate(
        self,
        *,
        phase: Mapping[str, Any],
        writer_pid: int,
    ) -> None:
        gate = read_json(self.previous_gate_path)
        if gate.get("run_id") != phase.get("run_id"):
            raise RuntimeError("active gate ownership changed before writer attach")
        gate["collector_pid"] = writer_pid
        gate["monitor_pid"] = os.getpid()
        gate["process_ids"] = [os.getpid(), writer_pid]
        gate["updated_at"] = datetime.now().astimezone().isoformat()
        self.publish_owned_gate(gate, run_type="dense_ws_campaign_phase")

    def update_owned_gate(
        self,
        *,
        phase: Mapping[str, Any],
        status: str,
        manifest: Mapping[str, Any] | None,
        reason: str | None,
    ) -> None:
        gate_path = self.previous_gate_path
        gate = read_json(gate_path) if gate_path.exists() else {}
        if gate.get("run_id") != phase.get("run_id"):
            raise RuntimeError("active gate ownership changed")
        gate["status"] = status
        gate["gate_status"] = status
        gate["updated_at"] = datetime.now().astimezone().isoformat()
        gate["process_ids"] = []
        gate["collector_pid"] = None
        gate["monitor_pid"] = None
        gate["final"] = bool(manifest and manifest.get("final"))
        gate["completed"] = bool(manifest and manifest.get("completed"))
        gate["actual_duration_sec"] = (
            manifest.get("actual_duration_sec") if manifest else None
        )
        gate["total_events"] = manifest.get("total_events") if manifest else None
        gate["rows"] = manifest.get("total_events") if manifest else 0
        gate["stop_reason"] = reason
        gate["notification_required"] = status == "STOPPED_INCOMPLETE"
        self.publish_owned_gate(gate, run_type="dense_ws_campaign_phase")

    def disk_headroom(
        self,
        *,
        phase: Mapping[str, Any],
        elapsed_sec: float,
        phase_root: Path,
    ) -> dict[str, int]:
        total_writer_sec = sum(
            int(item["writer_duration_sec"]) for item in self.plan["phases"]
        )
        phase_index = next(
            index
            for index, item in enumerate(self.plan["phases"])
            if item["phase_id"] == phase["phase_id"]
        )
        completed_writer_sec = sum(
            int(item["writer_duration_sec"])
            for item in self.plan["phases"][:phase_index]
        )
        elapsed_bounded = min(
            max(0.0, elapsed_sec),
            float(phase["writer_duration_sec"]),
        )
        remaining_writer_sec = max(
            0.0,
            total_writer_sec - completed_writer_sec - elapsed_bounded,
        )
        estimated_total = int(self.plan["resources"]["estimated_disk_bytes"])
        estimated_remaining = math.ceil(
            estimated_total * remaining_writer_sec / float(total_writer_sec)
        )
        required_free = max(MIN_DISK_FREE_BYTES, estimated_remaining * 2)
        free_bytes = shutil.disk_usage(nearest_existing_parent(phase_root)).free
        return {
            "free_bytes": free_bytes,
            "required_free_bytes": required_free,
            "estimated_remaining_raw_bytes": estimated_remaining,
            "remaining_writer_sec": math.ceil(remaining_writer_sec),
        }

    def monitor_phase(
        self,
        *,
        phase: dict[str, Any],
        symbol_plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        phase_root = Path(phase["output_namespace"]).resolve()
        if phase_root.exists() and any(phase_root.iterdir()):
            raise RuntimeError(f"phase output is not empty: {phase_root}")
        start = parse_time(phase["start_local"])
        writer_end = parse_time(phase["end_local"])
        hard_end = parse_time(phase.get("hard_end_local") or phase["end_local"])
        if utc_now() < start:
            self.wait_until(start, status=f"WAITING_FOR_{phase['phase_id'].upper()}")
        if utc_now() > start + timedelta(seconds=LATE_START_TOLERANCE_SEC):
            raise RuntimeError(f"late_phase_start:{phase['phase_id']}")
        self.wait_for_gate(start + timedelta(seconds=LATE_START_TOLERANCE_SEC))
        durable = Path(
            self.contract["source_bindings"]["durable_collector"]["path"]
        ).resolve()
        campaign_root = Path(self.plan["outputs"]["campaign_root"]).resolve()
        stdout_path = self.paths["control"] / f"{phase['phase_id']}.stdout.log"
        stderr_path = self.paths["control"] / f"{phase['phase_id']}.stderr.log"
        phase_record_path = self.paths["control"] / f"{phase['phase_id']}.launch.json"
        command = [
            sys.executable,
            str(durable),
            "collect",
            "--symbols",
            str(symbol_plan["symbols_arg"]),
            "--out-dir",
            str(campaign_root),
            "--run-id",
            str(phase["run_id"]),
            "--total-sec",
            str(phase["writer_duration_sec"]),
            "--segment-sec",
            str(self.contract["segment_validity_contract"]["full_segment_sec"]),
            "--update-interval",
            "100ms",
        ]
        output_cap = int(self.plan["resources"].get("hard_output_cap_bytes") or 0)
        if output_cap <= 0:
            raise RuntimeError("campaign output cap is missing or invalid")
        existing_output_bytes = self.campaign_output_bytes()
        if existing_output_bytes >= output_cap:
            raise RuntimeError(
                f"campaign_output_cap_reached:{existing_output_bytes}:{output_cap}"
            )
        self.acquire_global_writer_claim(phase)
        self.claim_gate(phase, writer_pid=None)
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        with (
            stdout_path.open("w", encoding="utf-8") as stdout,
            stderr_path.open("w", encoding="utf-8") as stderr,
        ):
            process = subprocess.Popen(
                command,
                cwd=str(project_root()),
                stdout=stdout,
                stderr=stderr,
                creationflags=creation_flags,
            )
        self.writer = process
        self.attach_global_writer(process.pid)
        self.attach_writer_to_gate(phase=phase, writer_pid=process.pid)
        write_json_immutable(
            phase_record_path,
            {
                "schema": "trading_mvp_dense_ws_phase_launch_v1",
                "campaign_id": self.campaign_id,
                "phase_id": phase["phase_id"],
                "run_id": phase["run_id"],
                "started_at_utc": iso_now(),
                "writer_pid": process.pid,
                "command": command,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "output_namespace": str(phase_root),
                "writer_target_end": writer_end.isoformat(),
                "hard_end": hard_end.isoformat(),
                "plan_hash": self.expected_plan_hash,
            },
        )
        self.update_state("RUNNING")
        started = time.monotonic()
        zero_checked = False
        schema_checked = False
        density_checked = False
        monitor_stop_reason: str | None = None
        last_report = 0.0
        last_disk_check = float("-inf")
        try:
            tracked = psutil.Process(process.pid)
            tracked.cpu_percent(None)
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if self.paths["stop"].exists():
                    self.stop_requested = True
                if self.stop_requested:
                    monitor_stop_reason = "user_stop_requested"
                    terminate_writer(process, reason="user_stop_requested")
                    break
                if utc_now() >= hard_end:
                    monitor_stop_reason = "phase_hard_end_reached"
                    terminate_writer(process, reason="phase_hard_end_reached")
                    break
                raw_files = sorted(phase_root.glob("seg_*/ws_*.jsonl"))
                aggregate_output_bytes = self.campaign_output_bytes()
                if aggregate_output_bytes >= output_cap:
                    monitor_stop_reason = "campaign_output_cap_reached"
                    terminate_writer(process, reason=monitor_stop_reason)
                    break
                if elapsed >= 60 and not schema_checked:
                    try:
                        result = schema_probe(
                            raw_files,
                            max_lines=RAW_SCHEMA_SAMPLE_LINES,
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ) as exc:
                        monitor_stop_reason = f"raw_schema_gate_failed:{exc}"
                        terminate_writer(process, reason=monitor_stop_reason)
                        break
                    schema_checked = True
                    self.update_state("RUNNING", schema_probe=result)
                if elapsed >= 600 and not zero_checked:
                    lines = count_jsonl_lines(raw_files)
                    try:
                        venue_presence = venue_presence_probe(raw_files)
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ) as exc:
                        monitor_stop_reason = f"zero_line_gate_failed:{exc}"
                        terminate_writer(process, reason=monitor_stop_reason)
                        break
                    zero_checked = True
                    self.update_state(
                        "RUNNING",
                        zero_line_count=lines,
                        zero_line_venue_presence=venue_presence,
                    )
                if elapsed >= 3_600 and not density_checked:
                    lines = count_jsonl_lines(raw_files)
                    lines_per_minute = lines / max(elapsed / 60.0, 0.001)
                    try:
                        venue_presence = venue_presence_probe(raw_files)
                        symbol_quality = validate_symbol_plan(symbol_plan)
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ) as exc:
                        monitor_stop_reason = f"early_density_gate_failed:{exc}"
                        terminate_writer(process, reason=monitor_stop_reason)
                        break
                    if (
                        lines < 600
                        or lines_per_minute < 10
                        or float(symbol_quality["dual_venue_coverage"]) < 0.8
                    ):
                        monitor_stop_reason = "early_density_gate_failed"
                        terminate_writer(process, reason=monitor_stop_reason)
                        break
                    density_checked = True
                    self.update_state(
                        "RUNNING",
                        early_density_lines=lines,
                        early_density_lines_per_minute=round(lines_per_minute, 3),
                        early_density_venue_presence=venue_presence,
                        early_density_symbol_quality=symbol_quality,
                    )
                try:
                    memory = tracked.memory_info().rss
                    normalized_cpu = tracked.cpu_percent(None) / max(
                        1, psutil.cpu_count() or 1
                    )
                except (psutil.Error, OSError):
                    if process.poll() is not None:
                        break
                    raise
                resource_window = float(
                    self.plan["resources"]["resource_gate_window_sec"]
                )
                hard_memory = int(self.plan["resources"]["hard_working_set_stop_bytes"])
                hard_cpu = float(
                    self.plan["resources"]["hard_normalized_cpu_stop_percent"]
                )
                if elapsed <= resource_window and (
                    memory > hard_memory or normalized_cpu > hard_cpu
                ):
                    monitor_stop_reason = "resource_gate_failed"
                    terminate_writer(process, reason=monitor_stop_reason)
                    break
                now_monotonic = time.monotonic()
                if now_monotonic - last_disk_check >= 60:
                    disk = self.disk_headroom(
                        phase=phase,
                        elapsed_sec=elapsed,
                        phase_root=phase_root,
                    )
                    disk["campaign_output_bytes"] = aggregate_output_bytes
                    disk["hard_output_cap_bytes"] = output_cap
                    if disk["free_bytes"] < disk["required_free_bytes"]:
                        monitor_stop_reason = "disk_headroom_gate_failed"
                        terminate_writer(process, reason=monitor_stop_reason)
                        break
                    self.update_state("RUNNING", disk_headroom=disk)
                    last_disk_check = now_monotonic
                if now_monotonic - last_report >= 30:
                    print(
                        f"[{iso_now()}] phase={phase['phase_id']} writer_pid={process.pid} "
                        f"elapsed={round(elapsed)}s raw_files={len(raw_files)} "
                        f"rss_mb={round(memory / 1024**2, 1)} cpu={round(normalized_cpu, 2)}%",
                        flush=True,
                    )
                    self.update_state(
                        "RUNNING",
                        elapsed_sec=round(elapsed),
                        raw_files=len(raw_files),
                        writer_rss_bytes=memory,
                        writer_normalized_cpu_percent=round(normalized_cpu, 3),
                    )
                    last_report = now_monotonic
                time.sleep(MONITOR_INTERVAL_SEC)
        finally:
            if process.poll() is None:
                terminate_writer(process, reason="monitor_finalizer")
            self.writer = None
        manifest_path = phase_root / f"ws_collect_{phase['run_id']}.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else None
        errors = list((manifest or {}).get("errors") or [])
        ready = phase_manifest_ready(
            manifest,
            writer_exit_code=process.returncode,
            errors=errors,
            schema_checked=schema_checked,
            zero_checked=zero_checked,
            density_checked=density_checked,
        )
        reason = (
            None
            if ready
            else str(
                monitor_stop_reason
                or (manifest or {}).get("stop_condition")
                or f"writer_exit_{process.returncode}"
            )
        )
        result = {
            "phase_id": phase["phase_id"],
            "run_id": phase["run_id"],
            "status": "READY" if ready else "STOPPED_INCOMPLETE",
            "writer_exit_code": process.returncode,
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path) if manifest else None,
            "actual_duration_sec": (
                manifest.get("actual_duration_sec") if manifest else None
            ),
            "total_events": manifest.get("total_events") if manifest else None,
            "transport_rows": manifest.get("transport_rows") if manifest else None,
            "market_envelope_rows": (
                manifest.get("market_envelope_rows") if manifest else None
            ),
            "normalized_events": manifest.get("normalized_events") if manifest else None,
            "control_rows": manifest.get("control_rows") if manifest else None,
            "unclassified_messages": (
                manifest.get("unclassified_messages") if manifest else None
            ),
            "market_silence_events": (
                manifest.get("market_silence_events") if manifest else None
            ),
            "reconnect_attempts": (
                manifest.get("reconnect_attempts") if manifest else None
            ),
            "runtime_completed": manifest.get("runtime_completed") if manifest else False,
            "liveness_clean": manifest.get("liveness_clean") if manifest else False,
            "quality_eligible": manifest.get("quality_eligible") if manifest else False,
            "dirty_segment_ids": manifest.get("dirty_segment_ids") if manifest else [],
            "symbol_plan_path": str(self.paths["symbol_plan"]),
            "symbol_plan_sha256": self.symbol_plan_sha256,
            "stop_reason": reason,
        }
        self.phase_results.append(result)
        self.update_owned_gate(
            phase=phase,
            status="READY_FOR_POSTPROCESS" if ready else "STOPPED_INCOMPLETE",
            manifest=manifest,
            reason=reason,
        )
        self.release_global_writer_claim(
            "READY_FOR_POSTPROCESS" if ready else "STOPPED_INCOMPLETE"
        )
        if not ready:
            raise RuntimeError(f"phase_stopped_incomplete:{phase['phase_id']}:{reason}")
        return result

    def write_campaign_manifest(self) -> dict[str, Any]:
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "campaign_id": self.campaign_id,
            "created_at_utc": iso_now(),
            "plan_path": str(self.plan_path),
            "plan_hash": self.expected_plan_hash,
            "contract_hash": self.contract["contract_hash"],
            "candidate_contract_hash": self.candidate_contract_hash,
            "universe_sha256": self.universe_sha256,
            "symbol_plan_path": str(self.paths["symbol_plan"]),
            "symbol_plan_sha256": self.symbol_plan_sha256,
            "phase_results": self.phase_results,
            "phases_completed": len(self.phase_results),
            "writer_duration_requested_sec": sum(
                int(item["writer_duration_sec"]) for item in self.plan["phases"]
            ),
            "writer_duration_actual_sec": round(
                sum(
                    float(item.get("actual_duration_sec") or 0.0)
                    for item in self.phase_results
                ),
                3,
            ),
            "total_events": sum(
                int(item.get("total_events") or 0) for item in self.phase_results
            ),
            "transport_rows": sum(
                int(item.get("transport_rows") or 0) for item in self.phase_results
            ),
            "market_envelope_rows": sum(
                int(item.get("market_envelope_rows") or 0)
                for item in self.phase_results
            ),
            "normalized_events": sum(
                int(item.get("normalized_events") or 0)
                for item in self.phase_results
            ),
            "control_rows": sum(
                int(item.get("control_rows") or 0) for item in self.phase_results
            ),
            "unclassified_messages": sum(
                int(item.get("unclassified_messages") or 0)
                for item in self.phase_results
            ),
            "market_silence_events": sum(
                int(item.get("market_silence_events") or 0)
                for item in self.phase_results
            ),
            "reconnect_attempts": sum(
                int(item.get("reconnect_attempts") or 0)
                for item in self.phase_results
            ),
            "runtime_completed": bool(self.phase_results)
            and len(self.phase_results) == len(self.plan["phases"])
            and all(item.get("runtime_completed") is True for item in self.phase_results),
            "liveness_clean": bool(self.phase_results)
            and all(item.get("liveness_clean") is True for item in self.phase_results),
            "quality_eligible": bool(self.phase_results)
            and all(item.get("quality_eligible") is True for item in self.phase_results),
            "dirty_segment_ids": [
                segment_id
                for item in self.phase_results
                for segment_id in item.get("dirty_segment_ids") or []
            ],
            "completed": bool(self.phase_results)
            and len(self.phase_results) == len(self.plan["phases"])
            and all(item.get("quality_eligible") is True for item in self.phase_results),
            "final": bool(self.phase_results)
            and len(self.phase_results) == len(self.plan["phases"])
            and all(item.get("quality_eligible") is True for item in self.phase_results),
            "returns_read": False,
            "pnl_computed": False,
            "oos_read": False,
            "next_allowed_action": self.plan["post_collection"][
                "next_allowed_result"
            ],
        }
        write_json_immutable(self.paths["manifest"], manifest)
        return manifest

    def set_final_campaign_gate(
        self, manifest: Mapping[str, Any], final_phase: Mapping[str, Any]
    ) -> None:
        gate = read_json(self.previous_gate_path)
        if gate.get("run_id") != final_phase.get("run_id"):
            raise RuntimeError("final phase no longer owns active gate")
        gate.update(
            {
                "run_id": self.campaign_id,
                "run_type": "dense_ws_campaign",
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "updated_at": datetime.now().astimezone().isoformat(),
                "process_ids": [],
                "collector_pid": None,
                "monitor_pid": None,
                "output_path": str(self.paths["root"]),
                "output": {
                    "path": str(self.paths["root"]),
                    "kind": "directory",
                },
                "manifest_path": str(self.paths["manifest"]),
                "final": True,
                "completed": True,
                "rows": manifest["total_events"],
                "total_events": manifest["total_events"],
                "notification_required": False,
                "next_step_after_ready": (
                    "Execute the exact hash-bound automatic gated evidence pipeline; "
                    "stop on the first failed gate and keep live/private API disabled."
                ),
            }
        )
        self.publish_owned_gate(gate, run_type="dense_ws_campaign")

    def finish_owner(self, status: str) -> None:
        if self.paths["owner"].exists():
            owner = read_json(self.paths["owner"])
            owner["final"] = True
            owner["status"] = status
            owner["finished_at_utc"] = iso_now()
            owner["orchestrator_pid"] = None
            write_json_atomic(self.paths["owner"], owner)
        if self.paths["reservation"].exists():
            reservation = read_json(self.paths["reservation"])
            if reservation.get("reservation_token") == self.reservation_token:
                reservation["final"] = True
                reservation["status"] = status
                reservation["finished_at_utc"] = iso_now()
                reservation["orchestrator_pid"] = None
                write_json_atomic(self.paths["reservation"], reservation)

    def run(self) -> int:
        if self.plan["launch_controls"]["status"] != (
            "READY_FOR_SEPARATE_EXACT_APPROVAL"
        ):
            raise RuntimeError("PlanOnly launch controls are not approval-ready")
        for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            value = getattr(signal, sig_name, None)
            if value is not None:
                try:
                    signal.signal(value, self.stop_signal_handler)
                except (OSError, ValueError):
                    pass
        adopted = False
        try:
            self.adopt_reservation()
            adopted = True
            window = classify_launch_window(self.plan, utc_now())
            if window["status"] != "DUE":
                raise RuntimeError(
                    f"runtime launch window is {window['status']}, expected DUE"
                )
            guard = assert_fresh_runtime_guard(self.plan)
            assert_runtime_gate_clear()
            self.write_launch_record(guard)
            self.update_state("PREFLIGHT_VALID", launch_window=window)
            first_phase_start = parse_time(self.plan["phases"][0]["start_local"])
            discovery_at = first_phase_start - timedelta(
                seconds=SYMBOL_DISCOVERY_LEAD_SEC
            )
            if utc_now() < discovery_at:
                self.wait_until(
                    discovery_at,
                    status="WAITING_FOR_SYMBOL_DISCOVERY",
                )
            assert_fresh_runtime_guard(self.plan)
            assert_runtime_gate_clear()
            symbol_plan = self.discover_symbols()
            for index, phase in enumerate(self.plan["phases"]):
                self.current_phase = dict(phase)
                result = self.monitor_phase(
                    phase=self.current_phase,
                    symbol_plan=symbol_plan,
                )
                if index < len(self.plan["phases"]) - 1:
                    self.release_gate_for_blackout(self.current_phase)
                    next_start = parse_time(
                        self.plan["phases"][index + 1]["start_local"]
                    )
                    self.wait_until(next_start, status="WAITING_PIT_BLACKOUT")
                self.update_state("PHASE_READY", last_phase_result=result)
            manifest = self.write_campaign_manifest()
            self.set_final_campaign_gate(manifest, self.current_phase or {})
            self.update_state(
                "READY_FOR_POSTPROCESS",
                campaign_manifest_path=str(self.paths["manifest"]),
            )
            self.finish_owner("READY_FOR_POSTPROCESS")
            print("Dense WS campaign reached READY_FOR_POSTPROCESS", flush=True)
            return 0
        except Exception as exc:
            if self.writer and self.writer.poll() is None:
                terminate_writer(self.writer, reason="campaign_exception")
            self.writer = None
            if adopted:
                self.update_state(
                    "STOPPED_INCOMPLETE",
                    error=f"{type(exc).__name__}: {exc}",
                )
            terminal_gate_written = False
            try:
                if adopted and self.current_phase and self.previous_gate_path.exists():
                    gate = read_json(self.previous_gate_path)
                    if gate.get("run_id") == self.current_phase.get("run_id"):
                        gate["status"] = "STOPPED_INCOMPLETE"
                        gate["gate_status"] = "STOPPED_INCOMPLETE"
                        gate["updated_at"] = datetime.now().astimezone().isoformat()
                        gate["process_ids"] = []
                        gate["collector_pid"] = None
                        gate["monitor_pid"] = None
                        gate["notification_required"] = True
                        gate["stop_reason"] = f"{type(exc).__name__}: {exc}"
                        self.publish_owned_gate(
                            gate,
                            run_type="dense_ws_campaign_phase",
                        )
                        terminal_gate_written = True
                if adopted and self.global_claim_token is not None:
                    if self.phase_gate_claimed and not terminal_gate_written:
                        raise RuntimeError(
                            "global writer claim retained because terminal phase gate "
                            "could not be verified"
                        )
                    final_status = (
                        "STOPPED_INCOMPLETE"
                        if self.phase_gate_claimed
                        else "ABORTED_BEFORE_GATE"
                    )
                    self.release_global_writer_claim(final_status)
            except Exception as cleanup_exc:
                if adopted:
                    self.update_state(
                        "STOPPED_INCOMPLETE",
                        error=f"{type(exc).__name__}: {exc}",
                        cleanup_error=(
                            f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                        ),
                        global_writer_claim_retained=(
                            self.global_claim_token is not None
                        ),
                    )
                print(
                    "Campaign cleanup failed closed: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}",
                    flush=True,
                )
            finally:
                if adopted:
                    self.finish_owner("STOPPED_INCOMPLETE")
            print(
                f"Campaign stopped incomplete: {type(exc).__name__}: {exc}", flush=True
            )
            return 1


def request_stop(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    reason: str,
) -> dict[str, Any]:
    _contract, plan, _policy = load_validated_bundle(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        policy_path=None,
        verify_policy=False,
    )
    paths = control_paths(plan)
    campaign_id = str(plan["campaign_id"])
    state = read_json(paths["state"]) if paths["state"].exists() else {}
    owner = read_json(paths["owner"]) if paths["owner"].exists() else {}
    orchestrator_pid = state.get("orchestrator_pid") or owner.get("orchestrator_pid")
    writer_pid = state.get("writer_pid")
    if not process_alive(orchestrator_pid) and not process_alive(writer_pid):
        return {
            "status": "NO_ACTIVE_CAMPAIGN",
            "campaign_id": campaign_id,
            "plan_hash": expected_plan_hash,
            "stop_request_written": False,
        }
    payload = {
        "schema": STOP_SCHEMA,
        "campaign_id": campaign_id,
        "requested_at_utc": iso_now(),
        "requested_by_pid": os.getpid(),
        "reason": reason,
        "plan_hash": expected_plan_hash,
        "orchestrator_pid": orchestrator_pid,
        "writer_pid": writer_pid,
    }
    if paths["stop"].exists():
        prior = read_json(paths["stop"])
        return {
            "status": "STOP_ALREADY_REQUESTED",
            "stop_request_path": str(paths["stop"]),
            "request": prior,
        }
    write_json_immutable(paths["stop"], payload)
    if process_alive(writer_pid):
        try:
            ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
            if ctrl_break is not None:
                os.kill(int(writer_pid), ctrl_break)
        except (OSError, ValueError, TypeError):
            pass
    return {
        "status": "STOP_REQUESTED",
        "stop_request_path": str(paths["stop"]),
        "request": payload,
    }


def status_snapshot(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    _contract, plan, _policy = load_validated_bundle(
        plan_path=plan_path,
        expected_plan_hash=expected_plan_hash,
        policy_path=None,
        verify_policy=False,
    )
    paths = control_paths(plan)
    campaign_id = str(plan["campaign_id"])
    state = read_json(paths["state"]) if paths["state"].exists() else None
    owner = read_json(paths["owner"]) if paths["owner"].exists() else None
    reservation = (
        read_json(paths["reservation"]) if paths["reservation"].exists() else None
    )
    gate = gate_status()
    phase_stats: list[dict[str, Any]] = []
    for phase in plan["phases"]:
        namespace = Path(phase["output_namespace"])
        files = list(namespace.glob("seg_*/ws_*.jsonl")) if namespace.exists() else []
        phase_stats.append(
            {
                "phase_id": phase["phase_id"],
                "run_id": phase["run_id"],
                "output_namespace": str(namespace),
                "raw_files": len(files),
                "raw_bytes": sum(path.stat().st_size for path in files),
                "manifest_exists": (
                    namespace / f"ws_collect_{phase['run_id']}.json"
                ).exists(),
            }
        )
    return {
        "schema": "trading_mvp_dense_ws_campaign_status_v1",
        "campaign_id": campaign_id,
        "observed_at_utc": iso_now(),
        "plan_hash": expected_plan_hash,
        "state": state,
        "owner": redact_control_record(owner),
        "reservation": redact_control_record(reservation),
        "orchestrator_alive": process_alive((state or {}).get("orchestrator_pid")),
        "writer_alive": process_alive((state or {}).get("writer_pid")),
        "terminal_alive": process_alive((reservation or {}).get("terminal_pid")),
        "active_gate_status": gate.get("status"),
        "active_gate_run_id": gate.get("run_id"),
        "phase_stats": phase_stats,
        "campaign_manifest_exists": paths["manifest"].exists(),
        "stop_request_exists": paths["stop"].exists(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dense WS campaign runtime control")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run", "status", "request-stop"):
        command = sub.add_parser(name)
        command.add_argument("--plan", required=True)
        command.add_argument("--expected-plan-hash", required=True)
        if name in {"preflight", "run"}:
            command.add_argument(
                "--policy",
                default=str(default_policy_path()),
            )
        if name == "preflight":
            command.add_argument("--require-due", action="store_true")
        if name == "request-stop":
            command.add_argument("--reason", default="user_stop_request")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preflight":
        result = preflight(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            policy_path=args.policy,
            require_due=args.require_due,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["structurally_valid"] else 1
    if args.command == "status":
        result = status_snapshot(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "request-stop":
        result = request_stop(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            reason=args.reason,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    contract, plan, _policy = load_validated_bundle(
        plan_path=args.plan,
        expected_plan_hash=args.expected_plan_hash,
        policy_path=args.policy,
        verify_policy=True,
    )
    reservation_token = os.environ.pop(RESERVATION_TOKEN_ENV, "")
    if re.fullmatch(r"[0-9a-f]{32}", reservation_token) is None:
        raise ValueError(
            f"{RESERVATION_TOKEN_ENV} must contain the exact launch reservation token"
        )
    runtime = CampaignRuntime(
        contract=contract,
        plan=plan,
        plan_path=Path(args.plan).resolve(),
        expected_plan_hash=args.expected_plan_hash,
        policy_path=Path(args.policy).resolve(),
        reservation_token=reservation_token,
    )
    return runtime.run()


if __name__ == "__main__":
    raise SystemExit(main())
