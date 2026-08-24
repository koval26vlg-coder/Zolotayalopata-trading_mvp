"""Fail-closed immutable PlanOnly rebind helpers for listing strategy tracks.

The helpers intentionally update only technical provenance, implementation
hashes and launcher command paths.  Research contracts are compared after a
small, explicit normalization so a venue, hypothesis, risk or acceptance
change cannot be hidden inside a technical rebind.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


BATCH1_RECEIPT_SHA256 = (
    "b310912a5c1d4e5b4bca16d8e343bb77aecca837a4ad32d4917a899fd08eeb56"
)
SOURCE_PLAN_SHA256 = {
    "premarket": "2f07a9b9621081b7f638042be0dadbd97a938d0741bc6fefe7c5fc1f25b13625",
    "preipo": "6f8dd54c3d0666c5f8507103c194ce8ea546b57018d8a85aaf6f8f38104abd1c",
}
DERIVATIVE_TRACKS = frozenset(SOURCE_PLAN_SHA256)
DERIVATIVE_IDENTITIES = {
    "premarket": {
        "schema": "trading_mvp_premarket_perp_listing_impulse_planonly_v2",
        "plan_id": "premarket_perp_listing_impulse_20260821_v2",
    },
    "preipo": {
        "schema": "trading_mvp_preipo_perpetual_event_planonly_v2",
        "plan_id": "preipo_perpetual_event_20260821_v2",
    },
}


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_plan_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "plan_hash"}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _normalized_research_contract(
    track: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(payload))
    for key in (
        "schema",
        "plan_id",
        "generated_at_utc",
        "plan_hash",
        "implementation",
        "commands",
    ):
        normalized.pop(key, None)

    source_bindings = normalized.get("source_bindings")
    if isinstance(source_bindings, dict):
        source_bindings.pop("technical_rebind", None)
        source_bindings.pop("control_plane_readiness_receipt", None)
        if track == "expansion":
            source_bindings.pop("parent_v2", None)
        if not source_bindings:
            normalized.pop("source_bindings", None)

    if track in DERIVATIVE_TRACKS:
        guard = normalized.get("guard_contract")
        if isinstance(guard, dict):
            guard.pop("visible_terminal_required", None)
            guard.pop("inline_worker_no_terminal_allowed", None)

    if track == "expansion":
        tick = normalized.get("tick")
        if isinstance(tick, dict):
            tick.pop("claim_path", None)

    return normalized


def validate_rebind_semantics(
    track: str,
    source: Mapping[str, Any],
    rebound: Mapping[str, Any],
) -> None:
    """Reject any rebind that changes the research contract."""

    _require(
        track in {"spot", "expansion", "premarket", "preipo"},
        f"unknown listing strategy track: {track}",
    )
    _require(
        _normalized_research_contract(track, source)
        == _normalized_research_contract(track, rebound),
        f"research contract changed during {track} technical rebind",
    )
    _require(
        rebound.get("plan_hash") == canonical_plan_hash(rebound),
        "rebound plan hash mismatch",
    )

    old_rows = source.get("implementation") or []
    new_rows = rebound.get("implementation") or []
    if isinstance(old_rows, Mapping):
        old_rows = old_rows.get("files") or []
    if isinstance(new_rows, Mapping):
        new_rows = new_rows.get("files") or []
    old_by_role = {str(row.get("role") or ""): row for row in old_rows}
    new_by_role = {str(row.get("role") or ""): row for row in new_rows}
    _require(set(old_by_role) == set(new_by_role), "implementation role set changed")
    for role, new_row in new_by_role.items():
        old_row = old_by_role[role]
        _require(new_row.get("path") == old_row.get("path"), f"implementation path changed: {role}")
        bound_path = Path(str(new_row.get("path") or ""))
        _require(bound_path.is_file(), f"implementation file missing: {role}")
        _require(
            new_row.get("sha256") == file_sha256(bound_path),
            f"implementation sha256 mismatch: {role}",
        )
        provenance = new_row.get("provenance") or {}
        _require(
            provenance.get("superseded_sha256") == old_row.get("sha256"),
            f"implementation provenance mismatch: {role}",
        )


def build_derivative_rebind(
    *,
    track: str,
    source_path: str | Path,
    output_path: str | Path,
    generated_at_utc: str,
    receipt_path: str | Path,
) -> dict[str, Any]:
    """Build, but do not write, one derivative technical rebind."""

    _require(track in DERIVATIVE_TRACKS, f"unsupported derivative track: {track}")
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    receipt_path = Path(receipt_path).resolve()
    _require(source_path.is_file(), "source PlanOnly missing")
    _require(receipt_path.is_file(), "Batch 1 readiness receipt missing")
    _require(
        file_sha256(source_path) == SOURCE_PLAN_SHA256[track],
        "source PlanOnly file sha256 mismatch",
    )
    _require(
        file_sha256(receipt_path) == BATCH1_RECEIPT_SHA256,
        "Batch 1 readiness receipt sha256 mismatch",
    )

    source = json.loads(source_path.read_text(encoding="utf-8"))
    _require(
        source.get("plan_hash") == canonical_plan_hash(source),
        "source PlanOnly canonical hash mismatch",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    _require(
        receipt.get("status") == "READY_FOR_PLANONLY_REBIND_NOT_ACTIVATED",
        "Batch 1 readiness receipt status mismatch",
    )

    rebound = copy.deepcopy(source)
    rebound.update(DERIVATIVE_IDENTITIES[track])
    rebound["generated_at_utc"] = generated_at_utc
    source_bindings = rebound.setdefault("source_bindings", {})
    source_bindings["technical_rebind"] = {
        "kind": "listing_strategy_control_plane_batch2_hash_rebind",
        "supersedes_plan_id": source.get("plan_id"),
        "supersedes_plan_hash": source.get("plan_hash"),
        "supersedes_plan_file_sha256": file_sha256(source_path),
        "supersedes_plan_path": str(source_path),
        "research_scope_changed": False,
        "reason": (
            "Rebind current fail-closed launchers, retry recovery and canonical "
            "writer controls without changing venue, universe, signal, cost, "
            "risk, cadence or acceptance contracts."
        ),
    }
    source_bindings["control_plane_readiness_receipt"] = {
        "path": str(receipt_path),
        "file_sha256": BATCH1_RECEIPT_SHA256,
        "status": receipt["status"],
    }

    old_rows = {str(row["role"]): row for row in source.get("implementation") or []}
    rebound_rows: list[dict[str, Any]] = []
    for role, old_row in old_rows.items():
        bound_path = Path(str(old_row.get("path") or ""))
        _require(bound_path.is_file(), f"implementation file missing: {role}")
        rebound_rows.append(
            {
                "role": role,
                "path": str(bound_path),
                "sha256": file_sha256(bound_path),
                "provenance": {
                    "kind": "technical_rebind_from_superseded_plan_row",
                    "superseded_sha256": old_row.get("sha256"),
                    "superseded_plan_hash": source.get("plan_hash"),
                    "superseded_plan_file_sha256": file_sha256(source_path),
                    "batch1_readiness_receipt_sha256": BATCH1_RECEIPT_SHA256,
                },
            }
        )
    rebound["implementation"] = rebound_rows

    guard = rebound.setdefault("guard_contract", {})
    guard["visible_terminal_required"] = True
    guard["inline_worker_no_terminal_allowed"] = False

    source_name = source_path.name
    output_name = output_path.name
    commands = {
        key: value.replace(source_name, output_name) if isinstance(value, str) else value
        for key, value in (source.get("commands") or {}).items()
        if key != "inline_tick"
    }
    rebound["commands"] = commands
    rebound["plan_hash"] = canonical_plan_hash(rebound)
    validate_rebind_semantics(track, source, rebound)
    return rebound


def write_immutable_plan(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write one canonical immutable JSON artifact, allowing exact idempotence."""

    path = Path(path)
    encoded = (json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        _require(path.read_bytes() == encoded, f"immutable artifact mismatch: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(encoded)
    return path
