from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import night_schedule_plan as pit_schedule


SCHEMA = "trading_mvp_dense_ws_refreeze_preview_v1"
RESERVATION_SCHEMA = "trading_mvp_dense_ws_next_no_skip_window_reservation_v1"
FEASIBILITY_SCHEMA = "trading_mvp_dense_ws_campaign_feasibility_v1"
POLICY_SCHEMA = "trading_mvp_continuous_production_policy_v1"
CONTINGENT_STATUS = "CONTINGENT_ON_FRESH_PIT_EXTENSION_APPROVAL"
PREVIEW_STATUS = "CONTINGENT_NOT_APPROVAL_READY_FRESH_PIT_EXTENSION_REQUIRED"
FEASIBILITY_VERDICT = "FEASIBILITY_CONFIRMED_CONTRACT_FREEZE_REQUIRED"

STRING_BINDINGS = (
    "AEF_CAMPAIGN_ID",
    "AEF_EXPECTED_CANDIDATE_HASH",
    "AEF_EXPECTED_WINDOW_ID",
    "AEF_EXPECTED_START_LOCAL",
    "AEF_EXPECTED_WRITER_DEADLINE_LOCAL",
    "AEF_EXPECTED_HARD_DEADLINE_LOCAL",
)
PHASE_TIME_KEYS = ("start_local", "end_local", "hard_end_local")
PLANNED_OUTPUT_KEYS = (
    "immutable_feasibility_path",
    "immutable_pit_amendment_path",
    "contract_path",
    "plan_path",
    "campaign_output_root",
    "runtime_dependency_manifest_path",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_hash(value: Mapping[str, Any], *, excluded_key: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded_key}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_value_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonical_proposal_hash(proposal: Mapping[str, Any]) -> str:
    return _canonical_hash(proposal, excluded_key="proposal_hash")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_sha256(value: Any, *, label: str) -> str:
    text = str(value or "").lower()
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 value")
    return text


def _assert_file_sha(path: Path, expected: str, *, label: str) -> None:
    observed = _sha256_file(path)
    if observed != _expect_sha256(expected, label=label):
        raise ValueError(f"{label} mismatch: expected {expected}, got {observed}")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must use ISO-8601 time with a UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(str(Path(left).expanduser().resolve())) == os.path.normcase(
        str(Path(right).expanduser().resolve())
    )


def _assert_false(payload: Mapping[str, Any], keys: Iterable[str], *, label: str) -> None:
    for key in keys:
        if payload.get(key) is not False:
            raise ValueError(f"{label}.{key} must remain false")


def _validate_reservation(
    payload: Mapping[str, Any],
    *,
    expected_reservation_hash: str,
) -> Mapping[str, Any]:
    if payload.get("schema") != RESERVATION_SCHEMA or payload.get("mode") != "PlanOnly":
        raise ValueError("unsupported Dense window reservation")
    if payload.get("status") != CONTINGENT_STATUS:
        raise ValueError("reservation is not contingent on a fresh PIT extension approval")
    embedded_hash = _expect_sha256(payload.get("reservation_hash"), label="reservation_hash")
    if embedded_hash != _expect_sha256(
        expected_reservation_hash, label="expected_reservation_hash"
    ):
        raise ValueError("reservation hash differs from the expected binding")
    if _canonical_hash(payload, excluded_key="reservation_hash") != embedded_hash:
        raise ValueError("reservation canonical hash mismatch")

    source = _mapping(payload.get("source"), label="reservation.source")
    extension = _mapping(
        source.get("extension_binding"), label="reservation.source.extension_binding"
    )
    if source.get("pit_schedule_approved") is not False:
        raise ValueError("contingent reservation must not claim PIT schedule approval")
    if extension.get("fresh_horizon_required") is not True:
        raise ValueError("contingent reservation must require a fresh PIT horizon")

    boundary = _mapping(
        payload.get("authorization_boundary"), label="reservation.authorization_boundary"
    )
    if boundary.get("this_is_not_contract_refreeze_approval") is not True:
        raise ValueError("reservation must not claim contract-refreeze approval")
    if boundary.get("this_is_not_launch_approval") is not True:
        raise ValueError("reservation must not claim launch approval")
    _assert_false(
        boundary,
        (
            "collector_launch_allowed",
            "network_access",
            "market_data_read",
            "returns_or_pnl",
            "oos",
            "paper_or_live",
            "private_api",
            "real_capital",
            "leverage_or_margin",
            "stopped_incomplete_retry_authorized",
        ),
        label="reservation.authorization_boundary",
    )
    frozen = _mapping(payload.get("frozen_invariants"), label="reservation.frozen_invariants")
    _assert_false(
        frozen,
        (
            "hypothesis_changed",
            "venue_changed",
            "universe_changed",
            "signal_changed",
            "cost_changed",
            "risk_changed",
            "duration_changed",
            "output_cap_changed",
            "grid_or_retune",
        ),
        label="reservation.frozen_invariants",
    )

    reservation = _mapping(payload.get("reservation"), label="reservation.reservation")
    if reservation.get("suppressed_pit_run_ids") != []:
        raise ValueError("reservation must preserve PIT without suppression")
    if reservation.get("uninterrupted_required") is not True:
        raise ValueError("Dense reservation must remain uninterrupted")
    start = _parse_timestamp(reservation.get("start_local"), label="reservation.start_local")
    writer_deadline = _parse_timestamp(
        reservation.get("writer_deadline_local"),
        label="reservation.writer_deadline_local",
    )
    hard_deadline = _parse_timestamp(
        reservation.get("hard_deadline_local"),
        label="reservation.hard_deadline_local",
    )
    writer_sec = int(reservation.get("writer_duration_sec") or 0)
    max_runtime_sec = int(reservation.get("max_runtime_sec") or 0)
    if writer_sec <= 0 or int((writer_deadline - start).total_seconds()) != writer_sec:
        raise ValueError("reservation writer duration does not match its timestamps")
    if max_runtime_sec < writer_sec or int((hard_deadline - start).total_seconds()) != max_runtime_sec:
        raise ValueError("reservation max runtime does not match its timestamps")
    return reservation


def _validate_amendment(
    payload: Mapping[str, Any],
    *,
    expected_plan_hash: str,
    reservation: Mapping[str, Any],
    amendment_path: Path,
) -> Mapping[str, Any]:
    expected_hash = _expect_sha256(expected_plan_hash, label="expected_amendment_plan_hash")
    if payload.get("mode") != "PlanOnly" or payload.get("plan_hash") != expected_hash:
        raise ValueError("PIT amendment PlanOnly identity mismatch")
    pit_schedule.validate_night_schedule_plan(amendment_path, expected_hash)
    amendment = _mapping(payload.get("time_only_amendment"), label="time_only_amendment")
    deferred = _mapping(reservation.get("deferred_pit"), label="reservation.deferred_pit")
    for key in (
        "run_id",
        "original_start_local",
        "original_end_local",
        "new_start_local",
        "new_end_local",
        "hard_deadline_local",
    ):
        if amendment.get(key) != deferred.get(key):
            raise ValueError(f"PIT amendment {key} differs from the reservation")
    if amendment.get("trade_contract_changed") is not False:
        raise ValueError("PIT amendment must not change the trading contract")
    if payload.get("explicit_approval_required") is not True:
        raise ValueError("contingent PIT amendment must still require explicit approval")
    return amendment


def _validate_candidate_policy(
    payload: Mapping[str, Any],
    *,
    source_policy_path: Path,
    source_policy_sha256: str,
    reservation_path: Path,
    reservation_sha256: str,
    reservation_hash: str,
    amendment_path: Path,
    amendment_sha256: str,
    amendment_plan_hash: str,
    reservation: Mapping[str, Any],
) -> None:
    if payload.get("schema") != POLICY_SCHEMA:
        raise ValueError("unsupported candidate continuous policy")
    stale = [
        key
        for key in payload
        if re.fullmatch(r"pit_n\d+_time_only_amendment", str(key)) is not None
    ]
    if stale:
        raise ValueError(f"candidate policy retained stale PIT bindings: {', '.join(stale)}")

    binding = _mapping(
        payload.get("pit_no_skip_time_only_amendment"),
        label="candidate_policy.pit_no_skip_time_only_amendment",
    )
    path_bindings = (
        ("source_policy_path", source_policy_path),
        ("reservation_path", reservation_path),
        ("amended_pit_schedule_path", amendment_path),
    )
    for key, expected_path in path_bindings:
        if not _same_path(str(binding.get(key) or ""), expected_path):
            raise ValueError(f"candidate policy {key} mismatch")
    hash_bindings = (
        ("source_policy_sha256", source_policy_sha256),
        ("reservation_file_sha256", reservation_sha256),
        ("reservation_hash", reservation_hash),
        ("amended_pit_schedule_file_sha256", amendment_sha256),
        ("amended_pit_schedule_plan_hash", amendment_plan_hash),
    )
    for key, expected in hash_bindings:
        if str(binding.get(key) or "") != expected:
            raise ValueError(f"candidate policy {key} mismatch")
    if binding.get("trade_contract_changed") is not False:
        raise ValueError("candidate policy must not change the trading contract")
    if binding.get("collector_launch_allowed") is not False:
        raise ValueError("candidate policy must not authorize a collector")
    if binding.get("contingent_on_fresh_pit_extension_approval") is not True:
        raise ValueError("candidate policy lost the fresh PIT extension dependency")

    factory = _mapping(
        payload.get("accelerated_evidence_factory"),
        label="candidate_policy.accelerated_evidence_factory",
    )
    exception = _mapping(
        factory.get("continuous_evidence_exception"),
        label="candidate_policy.continuous_evidence_exception",
    )
    expected_exception = {
        "campaign_id": reservation.get("campaign_id"),
        "window_id": reservation.get("window_id"),
        "start_local": reservation.get("start_local"),
        "writer_deadline_local": reservation.get("writer_deadline_local"),
        "hard_deadline_local": reservation.get("hard_deadline_local"),
        "deferred_pit_run_id": _mapping(
            reservation.get("deferred_pit"), label="reservation.deferred_pit"
        ).get("run_id"),
    }
    for key, expected in expected_exception.items():
        if exception.get(key) != expected:
            raise ValueError(f"candidate policy Dense exception {key} mismatch")
    if exception.get("suppressed_pit_run_ids") != []:
        raise ValueError("candidate policy must not suppress PIT")
    if int(factory.get("dense_writer_target_sec") or 0) != int(
        reservation.get("writer_duration_sec") or 0
    ):
        raise ValueError("candidate policy writer duration mismatch")
    if int(factory.get("dense_campaign_max_elapsed_sec") or 0) != int(
        reservation.get("max_runtime_sec") or 0
    ):
        raise ValueError("candidate policy max runtime mismatch")

    sequence = factory.get("market_data_sequence")
    if not isinstance(sequence, list) or len(sequence) != 3:
        raise ValueError("candidate policy must contain the three-entry no-skip sequence")
    preceding = _mapping(reservation.get("preceding_pit"), label="reservation.preceding_pit")
    deferred = _mapping(reservation.get("deferred_pit"), label="reservation.deferred_pit")
    expected_run_ids = (
        preceding.get("run_id"),
        f"{reservation.get('campaign_id')}_phase_01",
        deferred.get("run_id"),
    )
    observed_run_ids = tuple(
        item.get("run_id") for item in sequence if isinstance(item, Mapping)
    )
    if observed_run_ids != expected_run_ids:
        raise ValueError("candidate policy no-skip sequence identity mismatch")


def _validate_feasibility(
    payload: Mapping[str, Any],
    *,
    expected_candidate_contract_hash: str,
    candidate_policy_sha256: str,
    amendment_sha256: str,
    reservation: Mapping[str, Any],
) -> Mapping[str, Any]:
    if payload.get("schema") != FEASIBILITY_SCHEMA or payload.get("mode") != "PlanOnly":
        raise ValueError("unsupported Dense feasibility artifact")
    if payload.get("verdict") != FEASIBILITY_VERDICT:
        raise ValueError("Dense feasibility verdict is not contract-freeze ready")
    _assert_false(
        payload,
        (
            "would_start",
            "network_access",
            "returns_read",
            "pnl_computed",
            "oos_read",
            "grid_or_retune",
            "live_orders",
            "private_api_keys",
            "leverage_or_margin",
            "actual_collection_allowed",
        ),
        label="feasibility",
    )
    frozen = _mapping(payload.get("frozen_candidate"), label="feasibility.frozen_candidate")
    embedded_hash = _expect_sha256(
        payload.get("candidate_contract_hash"), label="candidate_contract_hash"
    )
    if embedded_hash != _expect_sha256(
        expected_candidate_contract_hash, label="expected_candidate_contract_hash"
    ):
        raise ValueError("candidate contract hash differs from the expected binding")
    if _canonical_value_hash(frozen) != embedded_hash:
        raise ValueError("candidate contract canonical hash mismatch")

    hypothesis = _mapping(payload.get("hypothesis"), label="feasibility.hypothesis")
    if frozen.get("hypothesis_id") != hypothesis.get("id"):
        raise ValueError("Dense feasibility hypothesis identity mismatch")
    universe = _mapping(
        payload.get("candidate_universe"), label="feasibility.candidate_universe"
    )
    if (
        frozen.get("universe_sha256") != universe.get("sha256")
        or frozen.get("universe_rows") != universe.get("rows")
    ):
        raise ValueError("Dense feasibility universe binding mismatch")

    expected = {
        "requested_start_local": reservation.get("start_local"),
        "window_id": reservation.get("window_id"),
        "hard_deadline_local": reservation.get("hard_deadline_local"),
        "writer_deadline_local": reservation.get("writer_deadline_local"),
        "target_writer_sec": reservation.get("writer_duration_sec"),
        "continuous_policy_sha256": candidate_policy_sha256,
        "pit_schedule_sha256": amendment_sha256,
        "suppressed_pit_run_ids": [],
    }
    for key, value in expected.items():
        if frozen.get(key) != value:
            raise ValueError(f"Dense feasibility frozen_candidate.{key} mismatch")

    window = _mapping(payload.get("window_feasibility"), label="window_feasibility")
    window_expected = {
        "window_id": reservation.get("window_id"),
        "campaign_start_local": reservation.get("start_local"),
        "writer_deadline_local": reservation.get("writer_deadline_local"),
        "hard_deadline_local": reservation.get("hard_deadline_local"),
        "planned_writer_sec": reservation.get("writer_duration_sec"),
        "suppressed_pit_run_ids": [],
    }
    for key, value in window_expected.items():
        if window.get(key) != value:
            raise ValueError(f"Dense feasibility window_feasibility.{key} mismatch")
    if window.get("uninterrupted_required") is not True:
        raise ValueError("Dense feasibility must remain uninterrupted")

    phases = frozen.get("phases")
    if not isinstance(phases, list) or len(phases) != 1 or not isinstance(phases[0], Mapping):
        raise ValueError("Dense feasibility must contain exactly one frozen phase")
    phase = phases[0]
    phase_expected = {
        "phase_id": "phase_01",
        "start_local": reservation.get("start_local"),
        "end_local": reservation.get("writer_deadline_local"),
        "hard_end_local": reservation.get("hard_deadline_local"),
        "writer_duration_sec": reservation.get("writer_duration_sec"),
    }
    for key, value in phase_expected.items():
        if phase.get(key) != value:
            raise ValueError(f"Dense feasibility phase {key} mismatch")

    resources = _mapping(payload.get("resource_estimate"), label="resource_estimate")
    estimate = int(resources.get("estimated_disk_bytes") or 0)
    cap = int(reservation.get("hard_output_cap_bytes") or 0)
    if estimate <= 0 or cap <= 0 or estimate > cap:
        raise ValueError("Dense feasibility disk estimate exceeds the frozen cap")
    if int(resources.get("hard_output_cap_bytes") or 0) != cap:
        raise ValueError("Dense feasibility output cap mismatch")
    return phase


def _top_level_literals(source_text: str) -> tuple[dict[str, Any], ast.Assign]:
    tree = ast.parse(source_text)
    values: dict[str, Any] = {}
    phase_assignment: ast.Assign | None = None
    wanted = set(STRING_BINDINGS) | {
        "AEF_EXPECTED_WRITER_SEC",
        "AEF_EXPECTED_MAX_RUNTIME_SEC",
        "AEF_SUPPRESSED_PIT_RUN_IDS",
        "AEF_EXPECTED_PHASES",
    }
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in wanted:
            continue
        try:
            values[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"source binding {target.id} must be a literal") from exc
        if target.id == "AEF_EXPECTED_PHASES":
            phase_assignment = node
    missing = sorted(wanted - set(values))
    if missing or phase_assignment is None:
        raise ValueError(f"source is missing AEF bindings: {', '.join(missing)}")
    return values, phase_assignment


def _replace_assignment(source_text: str, name: str, value: str) -> str:
    pattern = re.compile(rf'(?m)^{re.escape(name)} = "[^"\r\n]*"(?=\r?$)')
    updated, count = pattern.subn(f'{name} = {json.dumps(value)}', source_text)
    if count != 1:
        raise ValueError(f"source must contain exactly one simple assignment for {name}")
    return updated


def _replace_phase_time(
    source_text: str,
    *,
    phase_assignment: ast.Assign,
    key: str,
    value: str,
) -> str:
    lines = source_text.splitlines(keepends=True)
    start = phase_assignment.lineno - 1
    end = phase_assignment.end_lineno or phase_assignment.lineno
    block = "".join(lines[start:end])
    pattern = re.compile(rf'(?m)^(\s*"{re.escape(key)}"\s*:\s*)"[^"\r\n]*"')
    replaced, count = pattern.subn(rf'\g<1>{json.dumps(value)}', block)
    if count != 1:
        raise ValueError(f"AEF_EXPECTED_PHASES must contain exactly one {key}")
    lines[start:end] = [replaced]
    return "".join(lines)


def _build_source_postimage(
    source_text: str,
    *,
    campaign_id: str,
    candidate_contract_hash: str,
    window_id: str,
    start_local: str,
    writer_deadline_local: str,
    hard_deadline_local: str,
    writer_sec: int,
    max_runtime_sec: int,
) -> tuple[str, dict[str, Any]]:
    current, phase_assignment = _top_level_literals(source_text)
    if int(current["AEF_EXPECTED_WRITER_SEC"]) != writer_sec:
        raise ValueError("source AEF writer duration differs from the reservation")
    if int(current["AEF_EXPECTED_MAX_RUNTIME_SEC"]) != max_runtime_sec:
        raise ValueError("source AEF max runtime differs from the reservation")
    if current["AEF_SUPPRESSED_PIT_RUN_IDS"] != ():
        raise ValueError("source AEF profile unexpectedly suppresses PIT")
    old_phases = current["AEF_EXPECTED_PHASES"]
    if not isinstance(old_phases, tuple) or len(old_phases) != 1:
        raise ValueError("source AEF profile must contain exactly one phase")
    old_phase = old_phases[0]
    if not isinstance(old_phase, dict):
        raise ValueError("source AEF phase must be a literal object")
    if old_phase.get("phase_id") != "phase_01":
        raise ValueError("source AEF phase identity changed")
    if int(old_phase.get("writer_duration_sec") or 0) != writer_sec:
        raise ValueError("source AEF phase writer duration changed")

    values = {
        "AEF_CAMPAIGN_ID": campaign_id,
        "AEF_EXPECTED_CANDIDATE_HASH": candidate_contract_hash,
        "AEF_EXPECTED_WINDOW_ID": window_id,
        "AEF_EXPECTED_START_LOCAL": start_local,
        "AEF_EXPECTED_WRITER_DEADLINE_LOCAL": writer_deadline_local,
        "AEF_EXPECTED_HARD_DEADLINE_LOCAL": hard_deadline_local,
    }
    updated = source_text
    for name, value in values.items():
        updated = _replace_assignment(updated, name, value)
    for key, value in (
        ("start_local", start_local),
        ("end_local", writer_deadline_local),
        ("hard_end_local", hard_deadline_local),
    ):
        _, current_phase_assignment = _top_level_literals(updated)
        updated = _replace_phase_time(
            updated,
            phase_assignment=current_phase_assignment,
            key=key,
            value=value,
        )

    final, final_phase_assignment = _top_level_literals(updated)
    for name, value in values.items():
        if final[name] != value:
            raise AssertionError(f"postimage binding {name} was not applied")
    final_phase = final["AEF_EXPECTED_PHASES"][0]
    for key, value in (
        ("start_local", start_local),
        ("end_local", writer_deadline_local),
        ("hard_end_local", hard_deadline_local),
    ):
        if final_phase.get(key) != value:
            raise AssertionError(f"postimage phase binding {key} was not applied")

    old_lines = source_text.splitlines()
    new_lines = updated.splitlines()
    if len(old_lines) != len(new_lines):
        raise ValueError("source preview must not change the source line count")
    phase_start = final_phase_assignment.lineno
    phase_end = final_phase_assignment.end_lineno or final_phase_assignment.lineno
    changed_labels: list[str] = []
    for line_number, (old_line, new_line) in enumerate(zip(old_lines, new_lines), start=1):
        if old_line == new_line:
            continue
        assignment = next(
            (name for name in STRING_BINDINGS if new_line.startswith(f"{name} = ")),
            None,
        )
        if assignment is not None:
            changed_labels.append(assignment)
            continue
        stripped = new_line.strip()
        phase_key = next(
            (key for key in PHASE_TIME_KEYS if stripped.startswith(f'"{key}":')),
            None,
        )
        if phase_key is not None and phase_start <= line_number <= phase_end:
            changed_labels.append(f"AEF_EXPECTED_PHASES.{phase_key}")
            continue
        raise ValueError(f"source preview changed a forbidden line: {line_number}")
    expected_labels = set(STRING_BINDINGS) | {
        f"AEF_EXPECTED_PHASES.{key}" for key in PHASE_TIME_KEYS
    }
    if set(changed_labels) != expected_labels or len(changed_labels) != len(expected_labels):
        raise ValueError("source preview did not change exactly the nine time-only bindings")
    return updated, {
        "campaign_id": current["AEF_CAMPAIGN_ID"],
        "candidate_contract_hash": current["AEF_EXPECTED_CANDIDATE_HASH"],
        "window_id": current["AEF_EXPECTED_WINDOW_ID"],
        "start_local": current["AEF_EXPECTED_START_LOCAL"],
        "writer_deadline_local": current["AEF_EXPECTED_WRITER_DEADLINE_LOCAL"],
        "hard_deadline_local": current["AEF_EXPECTED_HARD_DEADLINE_LOCAL"],
    }


def _unified_patch(old_text: str, new_text: str, *, relative_path: str) -> bytes:
    old_lf = old_text.replace("\r\n", "\n")
    new_lf = new_text.replace("\r\n", "\n")
    patch = "".join(
        difflib.unified_diff(
            old_lf.splitlines(keepends=True),
            new_lf.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=2,
        )
    )
    if not patch or patch.count("--- ") != 1 or patch.count("+++ ") != 1:
        raise ValueError("failed to create a single-file source patch")
    return patch.encode("utf-8")


def _verify_patch_roundtrip(
    *,
    git_executable: str | Path,
    source_bytes: bytes,
    patch_bytes: bytes,
    relative_path: str,
    expected_postimage_sha256: str,
) -> str:
    executable = str(Path(git_executable).expanduser().resolve())
    if not Path(executable).is_file():
        raise ValueError(f"git executable is missing: {executable}")
    with tempfile.TemporaryDirectory(prefix="trading-mvp-refreeze-preview-") as temp_dir:
        root = Path(temp_dir)
        target = root / Path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_bytes)
        patch_path = root / "preview.patch"
        patch_path.write_bytes(patch_bytes)
        base_command = [executable, "-C", str(root), "apply", "--whitespace=nowarn"]
        for check_only in (True, False):
            command = [*base_command]
            if check_only:
                command.append("--check")
            command.extend(["--", str(patch_path)])
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                action = "check" if check_only else "apply"
                raise ValueError(f"isolated git apply {action} failed: {detail}")
        observed = _sha256_file(target)
    if observed != expected_postimage_sha256:
        raise ValueError(
            "isolated git apply postimage mismatch: "
            f"expected {expected_postimage_sha256}, got {observed}"
        )
    return observed


def _validate_planned_outputs(planned_outputs: Mapping[str, str | Path]) -> dict[str, str]:
    missing = [key for key in PLANNED_OUTPUT_KEYS if not str(planned_outputs.get(key) or "")]
    if missing:
        raise ValueError(f"planned outputs are missing: {', '.join(missing)}")
    normalized = {
        key: str(Path(planned_outputs[key]).expanduser().resolve()) for key in PLANNED_OUTPUT_KEYS
    }
    if len(set(os.path.normcase(value) for value in normalized.values())) != len(normalized):
        raise ValueError("planned output paths must be unique")
    return normalized


def _write_pair_immutable(
    *,
    patch_path: Path,
    patch_bytes: bytes,
    proposal_path: Path,
    proposal_bytes: bytes,
) -> None:
    for target in (patch_path, proposal_path):
        if target.exists():
            raise ValueError(f"refusing to overwrite immutable preview output: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    patch_descriptor = os.open(patch_path, flags)
    try:
        with os.fdopen(patch_descriptor, "wb") as handle:
            handle.write(patch_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        proposal_descriptor = os.open(proposal_path, flags)
        with os.fdopen(proposal_descriptor, "wb") as handle:
            handle.write(proposal_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        patch_path.unlink(missing_ok=True)
        proposal_path.unlink(missing_ok=True)
        raise


def build_refreeze_preview(
    *,
    repo_root: str | Path,
    source_path: str | Path,
    expected_source_sha256: str,
    source_policy_path: str | Path,
    expected_source_policy_sha256: str,
    reservation_path: str | Path,
    expected_reservation_sha256: str,
    expected_reservation_hash: str,
    candidate_policy_path: str | Path,
    expected_candidate_policy_sha256: str,
    amendment_path: str | Path,
    expected_amendment_sha256: str,
    expected_amendment_plan_hash: str,
    feasibility_path: str | Path,
    expected_feasibility_sha256: str,
    expected_candidate_contract_hash: str,
    output_patch_path: str | Path,
    output_proposal_path: str | Path,
    planned_outputs: Mapping[str, str | Path],
    generated_at_utc: str,
    git_executable: str | Path,
) -> dict[str, Any]:
    """Create a fail-closed, non-authorizing Dense refreeze preview."""

    root = Path(repo_root).expanduser().resolve()
    source_target = Path(source_path).expanduser().resolve()
    source_policy_target = Path(source_policy_path).expanduser().resolve()
    reservation_target = Path(reservation_path).expanduser().resolve()
    candidate_policy_target = Path(candidate_policy_path).expanduser().resolve()
    amendment_target = Path(amendment_path).expanduser().resolve()
    feasibility_target = Path(feasibility_path).expanduser().resolve()
    patch_target = Path(output_patch_path).expanduser().resolve()
    proposal_target = Path(output_proposal_path).expanduser().resolve()
    for output in (patch_target, proposal_target):
        if output.exists():
            raise ValueError(f"refusing to overwrite immutable preview output: {output}")
    try:
        relative_source = source_target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("contract source must stay inside the repository root") from exc

    expected_hashes = {
        "source": _expect_sha256(expected_source_sha256, label="expected_source_sha256"),
        "source_policy": _expect_sha256(
            expected_source_policy_sha256, label="expected_source_policy_sha256"
        ),
        "reservation": _expect_sha256(
            expected_reservation_sha256, label="expected_reservation_sha256"
        ),
        "candidate_policy": _expect_sha256(
            expected_candidate_policy_sha256, label="expected_candidate_policy_sha256"
        ),
        "amendment": _expect_sha256(
            expected_amendment_sha256, label="expected_amendment_sha256"
        ),
        "feasibility": _expect_sha256(
            expected_feasibility_sha256, label="expected_feasibility_sha256"
        ),
    }
    for label, target in (
        ("source", source_target),
        ("source_policy", source_policy_target),
        ("reservation", reservation_target),
        ("candidate_policy", candidate_policy_target),
        ("amendment", amendment_target),
        ("feasibility", feasibility_target),
    ):
        _assert_file_sha(target, expected_hashes[label], label=f"{label} file SHA-256")

    generated = _parse_timestamp(generated_at_utc, label="generated_at_utc")
    if generated.utcoffset() != timezone.utc.utcoffset(generated):
        raise ValueError("generated_at_utc must use UTC")
    normalized_outputs = _validate_planned_outputs(planned_outputs)

    reservation_payload = _read_json(reservation_target)
    reservation = _validate_reservation(
        reservation_payload,
        expected_reservation_hash=expected_reservation_hash,
    )
    amendment_payload = _read_json(amendment_target)
    amendment = _validate_amendment(
        amendment_payload,
        expected_plan_hash=expected_amendment_plan_hash,
        reservation=reservation,
        amendment_path=amendment_target,
    )
    candidate_policy = _read_json(candidate_policy_target)
    _validate_candidate_policy(
        candidate_policy,
        source_policy_path=source_policy_target,
        source_policy_sha256=expected_hashes["source_policy"],
        reservation_path=reservation_target,
        reservation_sha256=expected_hashes["reservation"],
        reservation_hash=expected_reservation_hash,
        amendment_path=amendment_target,
        amendment_sha256=expected_hashes["amendment"],
        amendment_plan_hash=expected_amendment_plan_hash,
        reservation=reservation,
    )
    feasibility = _read_json(feasibility_target)
    phase = _validate_feasibility(
        feasibility,
        expected_candidate_contract_hash=expected_candidate_contract_hash,
        candidate_policy_sha256=expected_hashes["candidate_policy"],
        amendment_sha256=expected_hashes["amendment"],
        reservation=reservation,
    )

    source_bytes = source_target.read_bytes()
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("contract source must be UTF-8") from exc
    postimage_text, old_binding = _build_source_postimage(
        source_text,
        campaign_id=str(reservation.get("campaign_id") or ""),
        candidate_contract_hash=expected_candidate_contract_hash,
        window_id=str(reservation.get("window_id") or ""),
        start_local=str(reservation.get("start_local") or ""),
        writer_deadline_local=str(reservation.get("writer_deadline_local") or ""),
        hard_deadline_local=str(reservation.get("hard_deadline_local") or ""),
        writer_sec=int(reservation.get("writer_duration_sec") or 0),
        max_runtime_sec=int(reservation.get("max_runtime_sec") or 0),
    )
    postimage_bytes = postimage_text.encode("utf-8")
    postimage_sha256 = _sha256_bytes(postimage_bytes)
    patch_bytes = _unified_patch(source_text, postimage_text, relative_path=relative_source)
    observed_postimage = _verify_patch_roundtrip(
        git_executable=git_executable,
        source_bytes=source_bytes,
        patch_bytes=patch_bytes,
        relative_path=relative_source,
        expected_postimage_sha256=postimage_sha256,
    )

    deferred = _mapping(reservation.get("deferred_pit"), label="reservation.deferred_pit")
    preceding = _mapping(reservation.get("preceding_pit"), label="reservation.preceding_pit")
    proposal: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "status": PREVIEW_STATUS,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "purpose": (
            "Prepare an exact time-only Dense contract refreeze preview while the fresh PIT "
            "extension remains unapproved. This preview cannot be used as approval or launch "
            "authority."
        ),
        "dependency_gate": {
            "fresh_pit_extension_required": True,
            "current_pit_schedule_approved": False,
            "rebuild_after_fresh_extension_required": True,
            "approval_request_allowed": False,
            "launch_allowed": False,
            "reason": "CURRENT_RESERVATION_IS_BOUND_TO_A_STALE_UNAPPROVED_PIT_HORIZON",
        },
        "source_binding": {
            "contract_source_path": str(source_target),
            "contract_source_sha256": expected_hashes["source"],
            "current_aef_binding": old_binding,
            "source_policy_path": str(source_policy_target),
            "source_policy_sha256": expected_hashes["source_policy"],
        },
        "candidate": {
            "campaign_id": reservation.get("campaign_id"),
            "candidate_contract_hash": expected_candidate_contract_hash,
            "window_id": reservation.get("window_id"),
            "reservation": {
                "path": str(reservation_target),
                "file_sha256": expected_hashes["reservation"],
                "reservation_hash": expected_reservation_hash,
                "status": reservation_payload.get("status"),
            },
            "candidate_policy": {
                "path": str(candidate_policy_target),
                "file_sha256": expected_hashes["candidate_policy"],
                "collector_launch_allowed": False,
            },
            "pit_amendment": {
                "path": str(amendment_target),
                "file_sha256": expected_hashes["amendment"],
                "plan_hash": expected_amendment_plan_hash,
                "run_id": amendment.get("run_id"),
                "schedule_approved": False,
            },
            "feasibility": {
                "path": str(feasibility_target),
                "file_sha256": expected_hashes["feasibility"],
                "verdict": feasibility.get("verdict"),
                "estimated_disk_bytes": _mapping(
                    feasibility.get("resource_estimate"), label="resource_estimate"
                ).get("estimated_disk_bytes"),
                "hard_output_cap_bytes": reservation.get("hard_output_cap_bytes"),
            },
            "timeline": {
                "preceding_pit": dict(preceding),
                "dense": {
                    "start_local": reservation.get("start_local"),
                    "writer_duration_sec": reservation.get("writer_duration_sec"),
                    "writer_deadline_local": reservation.get("writer_deadline_local"),
                    "hard_deadline_local": reservation.get("hard_deadline_local"),
                    "uninterrupted_required": True,
                },
                "deferred_pit": dict(deferred),
            },
        },
        "frozen_invariants": {
            "hypothesis_id": feasibility.get("hypothesis", {}).get("id"),
            "universe_sha256": feasibility.get("candidate_universe", {}).get("sha256"),
            "universe_rows": feasibility.get("candidate_universe", {}).get("rows"),
            "duration_sec": reservation.get("writer_duration_sec"),
            "max_runtime_sec": reservation.get("max_runtime_sec"),
            "hard_output_cap_bytes": reservation.get("hard_output_cap_bytes"),
            "phase": dict(phase),
            "trade_contract_changed": False,
            "grid_or_retune": False,
        },
        "exact_preview": {
            "patch_path": str(patch_target),
            "patch_sha256": _sha256_bytes(patch_bytes),
            "source_preimage_sha256": expected_hashes["source"],
            "expected_source_postimage_sha256": postimage_sha256,
            "isolated_git_apply_check": "PASS",
            "isolated_git_apply_postimage_sha256": observed_postimage,
            "changed_scope_only": [
                *STRING_BINDINGS,
                *(f"AEF_EXPECTED_PHASES.{key}" for key in PHASE_TIME_KEYS),
            ],
            "planned_outputs": normalized_outputs,
        },
        "approval_boundary": {
            "this_is_not_contract_refreeze_approval": True,
            "this_is_not_launch_approval": True,
            "collector_launch_allowed": False,
            "network_access": False,
            "market_data_read": False,
            "evaluator_allowed": False,
            "returns_or_pnl": False,
            "oos": False,
            "grid_or_retune": False,
            "paper_or_live": False,
            "private_api": False,
            "real_capital": False,
            "leverage_or_margin": False,
            "stopped_incomplete_retry_authorized": False,
        },
        "next_allowed_action": "REFRESH_PIT_EXTENSION_THEN_REBUILD_EXACT_REFREEZE_PACKET",
        "proposal_hash_method": "sha256_canonical_json_excluding_proposal_hash",
    }
    proposal["proposal_hash"] = canonical_proposal_hash(proposal)
    proposal_bytes = (
        json.dumps(proposal, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    _write_pair_immutable(
        patch_path=patch_target,
        patch_bytes=patch_bytes,
        proposal_path=proposal_target,
        proposal_bytes=proposal_bytes,
    )
    return {
        "schema": SCHEMA,
        "status": PREVIEW_STATUS,
        "proposal_path": str(proposal_target),
        "proposal_file_sha256": _sha256_file(proposal_target),
        "proposal_hash": proposal["proposal_hash"],
        "patch_path": str(patch_target),
        "patch_sha256": _sha256_file(patch_target),
        "expected_source_postimage_sha256": postimage_sha256,
        "collector_launch_allowed": False,
        "approval_request_allowed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a contingent Dense refreeze patch and proposal without authorizing a run."
        )
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--source-policy", type=Path, required=True)
    parser.add_argument("--expected-source-policy-sha256", required=True)
    parser.add_argument("--reservation", type=Path, required=True)
    parser.add_argument("--expected-reservation-sha256", required=True)
    parser.add_argument("--expected-reservation-hash", required=True)
    parser.add_argument("--candidate-policy", type=Path, required=True)
    parser.add_argument("--expected-candidate-policy-sha256", required=True)
    parser.add_argument("--amendment", type=Path, required=True)
    parser.add_argument("--expected-amendment-sha256", required=True)
    parser.add_argument("--expected-amendment-plan-hash", required=True)
    parser.add_argument("--feasibility", type=Path, required=True)
    parser.add_argument("--expected-feasibility-sha256", required=True)
    parser.add_argument("--expected-candidate-contract-hash", required=True)
    parser.add_argument("--output-patch", type=Path, required=True)
    parser.add_argument("--output-proposal", type=Path, required=True)
    parser.add_argument("--immutable-feasibility-path", type=Path, required=True)
    parser.add_argument("--immutable-pit-amendment-path", type=Path, required=True)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--plan-path", type=Path, required=True)
    parser.add_argument("--campaign-output-root", type=Path, required=True)
    parser.add_argument("--runtime-dependency-manifest-path", type=Path, required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--git-executable", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_refreeze_preview(
        repo_root=args.repo_root,
        source_path=args.source,
        expected_source_sha256=args.expected_source_sha256,
        source_policy_path=args.source_policy,
        expected_source_policy_sha256=args.expected_source_policy_sha256,
        reservation_path=args.reservation,
        expected_reservation_sha256=args.expected_reservation_sha256,
        expected_reservation_hash=args.expected_reservation_hash,
        candidate_policy_path=args.candidate_policy,
        expected_candidate_policy_sha256=args.expected_candidate_policy_sha256,
        amendment_path=args.amendment,
        expected_amendment_sha256=args.expected_amendment_sha256,
        expected_amendment_plan_hash=args.expected_amendment_plan_hash,
        feasibility_path=args.feasibility,
        expected_feasibility_sha256=args.expected_feasibility_sha256,
        expected_candidate_contract_hash=args.expected_candidate_contract_hash,
        output_patch_path=args.output_patch,
        output_proposal_path=args.output_proposal,
        planned_outputs={
            "immutable_feasibility_path": args.immutable_feasibility_path,
            "immutable_pit_amendment_path": args.immutable_pit_amendment_path,
            "contract_path": args.contract_path,
            "plan_path": args.plan_path,
            "campaign_output_root": args.campaign_output_root,
            "runtime_dependency_manifest_path": args.runtime_dependency_manifest_path,
        },
        generated_at_utc=args.generated_at_utc,
        git_executable=args.git_executable,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
