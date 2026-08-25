from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA = "zolotyaylopata.canonical_strategy_runtime.v1"
STAGING_ACTIVATION_STATUS = "STAGING_NOT_INSTALLED"
EXTERNAL_REGISTRY_PATH = (
    Path.home()
    / "AppData"
    / "Local"
    / "ZolotyayLopata"
    / "control"
    / "canonical_strategy_runtime.json"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

_TOP_LEVEL_FIELDS = {
    "schema",
    "registry_id",
    "generated_at_utc",
    "activation_status",
    "canonical_owners",
    "runtimes",
}
_OWNER_FIELDS = {
    "strategy_id",
    "namespace_prefix",
    "scope",
    "venues",
}
_RUNTIME_FIELDS = {
    "strategy_id",
    "track_class",
    "runtime_status",
    "activation_readiness",
    "namespace_prefix",
    "scope",
    "venues",
    "canonical_repo",
    "canonical_remote_url",
    "canonical_git_commit",
    "canonical_plan_path",
    "canonical_plan_sha256",
    "canonical_plan_file_sha256",
    "canonical_plan_id",
    "canonical_plan_status",
    "launcher_path",
    "launcher_sha256",
    "scheduler_routable",
    "allowed_modes",
    "state_path",
    "ledger_path",
    "public_data_only",
    "live_trading_allowed",
    "implementation_bindings",
    "supersedes",
    "retired_aliases",
}
_IMPLEMENTATION_BINDING_FIELDS = {"role", "path", "sha256"}
_RUNTIME_STATUSES = {"ACTIVE", "INACTIVE", "RETIRED"}


class DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _load_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def canonical_plan_hash(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("plan_hash", None)
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _unknown_or_missing_fields(
    payload: Any,
    expected: set[str],
    context: str,
) -> list[str]:
    if not isinstance(payload, dict):
        return [f"invalid_object:{context}"]
    reasons: list[str] = []
    unknown = sorted(set(payload) - expected)
    missing = sorted(expected - set(payload))
    if unknown:
        reasons.append(f"unknown_fields:{context}:{','.join(unknown)}")
    if missing:
        reasons.append(f"missing_fields:{context}:{','.join(missing)}")
    return reasons


def _valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER_RE.fullmatch(value))


def _valid_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _valid_string_list(value: Any, *, nonempty: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    if nonempty and not value:
        return False
    if not all(_valid_nonempty_string(item) for item in value):
        return False
    return len(value) == len(set(value))


def _is_normalized_absolute(path_text: Any) -> tuple[bool, str | None]:
    if not isinstance(path_text, str) or not path_text:
        return False, "path_not_string"
    path = Path(path_text)
    if not path.is_absolute():
        return False, "path_not_absolute"
    if os.path.normpath(path_text) != path_text:
        return False, "path_not_normalized"
    return True, None


def _is_within_repo(path_text: str, repo_text: str) -> bool:
    try:
        Path(path_text).resolve(strict=False).relative_to(
            Path(repo_text).resolve(strict=False)
        )
        return True
    except ValueError:
        return False


def _git_executable() -> str:
    windows_git = Path(r"C:\Program Files\Git\cmd\git.exe")
    if os.name == "nt":
        return str(windows_git)
    discovered = shutil.which("git")
    if discovered:
        return discovered
    return "git"


def _git_output(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [_git_executable(), "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    return completed.stdout.strip()


def _git_toplevel(repo: Path) -> Path:
    return Path(_git_output(repo, "rev-parse", "--show-toplevel")).resolve(
        strict=True
    )


def _git_head_blob(repo: Path, path: Path, *, commit: str) -> bytes | None:
    if not _COMMIT_RE.fullmatch(commit):
        return None
    try:
        resolved_repo = repo.resolve(strict=True)
        if _git_toplevel(resolved_repo) != resolved_repo:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        relative = path.resolve(strict=False).relative_to(resolved_repo)
    except ValueError:
        return None
    relative_text = relative.as_posix()
    blob = subprocess.run(
        [
            _git_executable(),
            "-C",
            str(repo),
            "show",
            f"{commit}:{relative_text}",
        ],
        check=False,
        capture_output=True,
        timeout=15,
    )
    if blob.returncode != 0:
        return None
    return blob.stdout


def _extract_plan_bindings(
    plan: dict[str, Any],
    canonical_repo: Path | None = None,
) -> list[dict[str, Any]]:
    implementation = plan.get("implementation")
    if isinstance(implementation, dict):
        files = implementation.get("files")
        if set(implementation) != {"files"} or not isinstance(files, list):
            raise ValueError("plan_implementation_layout_invalid")
        implementation = files
    if not isinstance(implementation, list) or not implementation:
        raise ValueError("plan_implementation_layout_invalid")

    bindings: list[dict[str, Any]] = []
    roles: set[str] = set()
    paths: set[str] = set()
    for index, row in enumerate(implementation):
        if not isinstance(row, dict):
            raise ValueError(f"plan_implementation_row_invalid:{index}")
        role = row.get("role")
        path = row.get("path")
        if path is None and isinstance(row.get("repo_path"), str):
            repo_path = Path(row["repo_path"])
            if (
                canonical_repo is None
                or repo_path.is_absolute()
                or ".." in repo_path.parts
            ):
                raise ValueError(f"plan_implementation_repo_path_invalid:{index}")
            resolved = (canonical_repo / repo_path).resolve(strict=False)
            try:
                resolved.relative_to(canonical_repo.resolve(strict=False))
            except ValueError as exc:
                raise ValueError(
                    f"plan_implementation_repo_path_invalid:{index}"
                ) from exc
            path = str(resolved)
        sha256 = row.get("sha256")
        if not _valid_nonempty_string(role):
            raise ValueError(f"plan_implementation_role_invalid:{index}")
        if not _valid_nonempty_string(path):
            raise ValueError(f"plan_implementation_path_invalid:{index}")
        if not _valid_sha256(sha256):
            raise ValueError(f"plan_implementation_sha256_invalid:{index}")
        if role in roles:
            raise ValueError(f"plan_implementation_duplicate_role:{role}")
        if path in paths:
            raise ValueError(f"plan_implementation_duplicate_path:{path}")
        roles.add(role)
        paths.add(path)
        bindings.append({"role": role, "path": path, "sha256": sha256})
    return bindings


def _validate_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _validate_structure(payload: Any) -> tuple[list[str], list[dict[str, Any]]]:
    reasons = _unknown_or_missing_fields(payload, _TOP_LEVEL_FIELDS, "registry")
    if reasons or not isinstance(payload, dict):
        return reasons, []

    if payload.get("schema") != SCHEMA:
        reasons.append("schema_invalid")
    if not _valid_identifier(payload.get("registry_id")):
        reasons.append("registry_id_invalid")
    if not _validate_timestamp(payload.get("generated_at_utc")):
        reasons.append("generated_at_utc_invalid")
    if payload.get("activation_status") != STAGING_ACTIVATION_STATUS:
        reasons.append("activation_status_invalid")

    owners = payload.get("canonical_owners")
    runtimes = payload.get("runtimes")
    if not isinstance(owners, list) or not owners:
        reasons.append("canonical_owners_invalid")
        owners = []
    if not isinstance(runtimes, list) or not runtimes:
        reasons.append("runtimes_invalid")
        runtimes = []

    owner_ids: list[str] = []
    owner_namespaces: list[str] = []
    for index, owner in enumerate(owners):
        context = f"canonical_owners[{index}]"
        reasons.extend(_unknown_or_missing_fields(owner, _OWNER_FIELDS, context))
        if not isinstance(owner, dict):
            continue
        if not _valid_identifier(owner.get("strategy_id")):
            reasons.append(f"owner_strategy_id_invalid:{index}")
        else:
            owner_ids.append(owner["strategy_id"])
        if not _valid_identifier(owner.get("namespace_prefix")):
            reasons.append(f"owner_namespace_prefix_invalid:{index}")
        else:
            owner_namespaces.append(owner["namespace_prefix"])
        if not _valid_identifier(owner.get("scope")):
            reasons.append(f"owner_scope_invalid:{index}")
        if not _valid_string_list(owner.get("venues"), nonempty=True):
            reasons.append(f"owner_venues_invalid:{index}")

    if len(owner_ids) != len(set(owner_ids)):
        reasons.append("duplicate_owner_strategy_id")
    if len(owner_namespaces) != len(set(owner_namespaces)):
        reasons.append("duplicate_owner_namespace_prefix")

    runtime_ids: list[str] = []
    runtime_namespaces: list[str] = []
    structurally_valid_runtimes: list[dict[str, Any]] = []
    for index, runtime in enumerate(runtimes):
        context = f"runtimes[{index}]"
        row_reasons = _unknown_or_missing_fields(runtime, _RUNTIME_FIELDS, context)
        reasons.extend(row_reasons)
        if not isinstance(runtime, dict):
            continue

        strategy_id = runtime.get("strategy_id")
        namespace = runtime.get("namespace_prefix")
        if not _valid_identifier(strategy_id):
            reasons.append(f"strategy_id_invalid:{index}")
        else:
            runtime_ids.append(strategy_id)
        if not _valid_identifier(namespace):
            reasons.append(f"namespace_prefix_invalid:{index}")
        else:
            runtime_namespaces.append(namespace)
        if not _valid_identifier(runtime.get("track_class")):
            reasons.append(f"track_class_invalid:{index}")
        if runtime.get("runtime_status") not in _RUNTIME_STATUSES:
            reasons.append(f"runtime_status_invalid:{index}")
        if not _valid_nonempty_string(runtime.get("activation_readiness")):
            reasons.append(f"activation_readiness_invalid:{index}")
        if not _valid_identifier(runtime.get("scope")):
            reasons.append(f"scope_invalid:{index}")
        if not _valid_string_list(runtime.get("venues"), nonempty=True):
            reasons.append(f"venues_invalid:{index}")
        if not _valid_nonempty_string(runtime.get("canonical_remote_url")):
            reasons.append(f"canonical_remote_url_invalid:{index}")
        if not isinstance(
            runtime.get("canonical_git_commit"), str
        ) or not _COMMIT_RE.fullmatch(runtime["canonical_git_commit"]):
            reasons.append(f"canonical_git_commit_invalid:{index}")
        for field in ("canonical_plan_sha256", "canonical_plan_file_sha256"):
            if not _valid_sha256(runtime.get(field)):
                reasons.append(f"{field}_invalid:{index}")
        for field in ("canonical_plan_id", "canonical_plan_status"):
            if not _valid_nonempty_string(runtime.get(field)):
                reasons.append(f"{field}_invalid:{index}")
        if not isinstance(runtime.get("scheduler_routable"), bool):
            reasons.append(f"scheduler_routable_invalid:{index}")
        if not isinstance(runtime.get("public_data_only"), bool):
            reasons.append(f"public_data_only_invalid:{index}")
        if not isinstance(runtime.get("live_trading_allowed"), bool):
            reasons.append(f"live_trading_allowed_invalid:{index}")
        if not _valid_string_list(runtime.get("allowed_modes"), nonempty=True):
            reasons.append(f"allowed_modes_invalid:{index}")
        elif any(mode.upper().startswith("LIVE") for mode in runtime["allowed_modes"]):
            reasons.append(f"live_mode_declared:{strategy_id}")
        for field in ("supersedes", "retired_aliases"):
            if not _valid_string_list(runtime.get(field)):
                reasons.append(f"{field}_invalid:{index}")

        canonical_repo = runtime.get("canonical_repo")
        path_fields = (
            "canonical_repo",
            "canonical_plan_path",
            "state_path",
            "ledger_path",
        )
        for field in path_fields:
            path_ok, path_reason = _is_normalized_absolute(runtime.get(field))
            if not path_ok:
                reasons.append(f"{path_reason}:{strategy_id}:{field}")
        launcher_path = runtime.get("launcher_path")
        launcher_sha = runtime.get("launcher_sha256")
        if launcher_path is None:
            if launcher_sha is not None:
                reasons.append(f"launcher_sha_without_path:{strategy_id}")
            if runtime.get("scheduler_routable") is True:
                reasons.append(f"routable_launcher_missing:{strategy_id}")
        else:
            path_ok, path_reason = _is_normalized_absolute(launcher_path)
            if not path_ok:
                reasons.append(f"{path_reason}:{strategy_id}:launcher_path")
            if not _valid_sha256(launcher_sha):
                reasons.append(f"launcher_sha256_invalid:{index}")

        bindings = runtime.get("implementation_bindings")
        if not isinstance(bindings, list) or not bindings:
            reasons.append(f"implementation_bindings_invalid:{index}")
            bindings = []
        binding_roles: list[str] = []
        binding_paths: list[str] = []
        for binding_index, binding in enumerate(bindings):
            binding_context = f"{context}.implementation_bindings[{binding_index}]"
            reasons.extend(
                _unknown_or_missing_fields(
                    binding,
                    _IMPLEMENTATION_BINDING_FIELDS,
                    binding_context,
                )
            )
            if not isinstance(binding, dict):
                continue
            if not _valid_nonempty_string(binding.get("role")):
                reasons.append(f"implementation_role_invalid:{index}:{binding_index}")
            else:
                binding_roles.append(binding["role"])
            path_ok, path_reason = _is_normalized_absolute(binding.get("path"))
            if not path_ok:
                reasons.append(
                    f"{path_reason}:{strategy_id}:implementation_bindings[{binding_index}].path"
                )
            else:
                binding_paths.append(binding["path"])
            if not _valid_sha256(binding.get("sha256")):
                reasons.append(f"implementation_sha256_invalid:{index}:{binding_index}")
        if len(binding_roles) != len(set(binding_roles)):
            reasons.append(f"duplicate_implementation_role:{strategy_id}")
        if len(binding_paths) != len(set(binding_paths)):
            reasons.append(f"duplicate_implementation_path:{strategy_id}")

        if isinstance(canonical_repo, str) and Path(canonical_repo).is_absolute():
            for field in ("canonical_plan_path", "launcher_path"):
                path_text = runtime.get(field)
                if isinstance(path_text, str) and Path(path_text).is_absolute():
                    if not _is_within_repo(path_text, canonical_repo):
                        reasons.append(
                            f"path_outside_canonical_repo:{strategy_id}:{field}"
                        )
            for binding_index, binding in enumerate(bindings):
                if isinstance(binding, dict) and isinstance(binding.get("path"), str):
                    if Path(binding["path"]).is_absolute() and not _is_within_repo(
                        binding["path"], canonical_repo
                    ):
                        reasons.append(
                            "path_outside_canonical_repo:"
                            f"{strategy_id}:implementation_bindings[{binding_index}].path"
                        )

        if runtime.get("public_data_only") is not True:
            reasons.append(f"public_data_only_required:{strategy_id}")
        if runtime.get("live_trading_allowed") is not False:
            reasons.append(f"live_trading_forbidden:{strategy_id}")
        if runtime.get("scheduler_routable") is True:
            reasons.append(f"staging_runtime_routable:{strategy_id}")
            if runtime.get("runtime_status") == "RETIRED":
                reasons.append(f"retired_runtime_routable:{strategy_id}")

        if not row_reasons:
            structurally_valid_runtimes.append(runtime)

    if len(runtime_ids) != len(set(runtime_ids)):
        reasons.append("duplicate_strategy_id")

    owner_by_id = {
        owner.get("strategy_id"): owner
        for owner in owners
        if isinstance(owner, dict) and _valid_identifier(owner.get("strategy_id"))
    }
    for runtime in runtimes:
        if not isinstance(runtime, dict):
            continue
        strategy_id = runtime.get("strategy_id")
        owner = owner_by_id.get(strategy_id)
        if owner is None:
            reasons.append(f"canonical_owner_missing:{strategy_id}")
            continue
        for field in ("namespace_prefix", "scope", "venues"):
            if owner.get(field) != runtime.get(field):
                reasons.append(f"canonical_owner_mismatch:{strategy_id}:{field}")
    runtime_id_set = {item for item in runtime_ids}
    for owner_id in owner_ids:
        if owner_id not in runtime_id_set:
            reasons.append(f"canonical_owner_without_runtime:{owner_id}")

    active = [
        runtime
        for runtime in runtimes
        if isinstance(runtime, dict) and runtime.get("runtime_status") == "ACTIVE"
    ]
    for left_index, left in enumerate(active):
        left_id = str(left.get("strategy_id"))
        for right in active[left_index + 1 :]:
            right_id = str(right.get("strategy_id"))
            if left.get("scope") == right.get("scope"):
                left_venues = set(left.get("venues") or [])
                overlap = sorted(left_venues.intersection(right.get("venues") or []))
                if overlap:
                    reasons.append(
                        "active_scope_venue_overlap:"
                        f"{left_id}:{right_id}:{','.join(overlap)}"
                    )

    namespace_rows = [runtime for runtime in runtimes if isinstance(runtime, dict)]
    for left_index, left in enumerate(namespace_rows):
        left_id = str(left.get("strategy_id"))
        left_namespace = str(left.get("namespace_prefix"))
        for right in namespace_rows[left_index + 1 :]:
            right_id = str(right.get("strategy_id"))
            right_namespace = str(right.get("namespace_prefix"))
            if (
                left_namespace == right_namespace
                or left_namespace.startswith(right_namespace + ".")
                or right_namespace.startswith(left_namespace + ".")
            ):
                reasons.append(f"namespace_prefix_collision:{left_id}:{right_id}")

    return sorted(set(reasons)), structurally_valid_runtimes


def _runtime_binding_result(runtime: dict[str, Any]) -> dict[str, Any]:
    strategy_id = str(runtime["strategy_id"])
    reasons: list[str] = []
    repo = Path(runtime["canonical_repo"])
    initial_head: str | None = None
    initial_remote: str | None = None

    try:
        resolved_repo = repo.resolve(strict=True)
        git_toplevel = _git_toplevel(resolved_repo)
    except (OSError, subprocess.SubprocessError):
        reasons.append("canonical_repo_git_toplevel_unreadable")
    else:
        if git_toplevel != resolved_repo:
            reasons.append("canonical_repo_not_git_toplevel")

    try:
        head = _git_output(repo, "rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError):
        reasons.append("repo_head_unreadable")
    else:
        initial_head = head
        if head != runtime["canonical_git_commit"]:
            reasons.append("repo_head_mismatch")
    try:
        remote = _git_output(repo, "remote", "get-url", "origin")
    except (OSError, subprocess.SubprocessError):
        reasons.append("repo_remote_unreadable")
    else:
        initial_remote = remote
        if remote != runtime["canonical_remote_url"]:
            reasons.append("repo_remote_mismatch")

    plan_path = Path(runtime["canonical_plan_path"])
    plan: dict[str, Any] | None = None
    plan_bindings: list[dict[str, Any]] = []
    if not plan_path.is_file():
        reasons.append("plan_file_missing")
    else:
        raw_plan = plan_path.read_bytes()
        if _sha256_bytes(raw_plan) != runtime["canonical_plan_file_sha256"]:
            reasons.append("plan_file_sha256_mismatch")
        plan_blob = _git_head_blob(
            repo,
            plan_path,
            commit=runtime["canonical_git_commit"],
        )
        if plan_blob is None:
            reasons.append("plan_not_tracked")
        elif _sha256_bytes(plan_blob) != runtime["canonical_plan_file_sha256"]:
            reasons.append("plan_git_blob_mismatch")
        try:
            loaded_plan = _load_json_bytes(raw_plan)
        except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError):
            reasons.append("plan_json_invalid")
        else:
            if not isinstance(loaded_plan, dict):
                reasons.append("plan_json_not_object")
            else:
                plan = loaded_plan
                calculated_hash = canonical_plan_hash(plan)
                if plan.get("plan_hash") != calculated_hash:
                    reasons.append("plan_internal_hash_invalid")
                if runtime["canonical_plan_sha256"] != calculated_hash:
                    reasons.append("plan_canonical_hash_mismatch")
                if plan.get("plan_id") != runtime["canonical_plan_id"]:
                    reasons.append("plan_id_mismatch")
                if plan.get("status") != runtime["canonical_plan_status"]:
                    reasons.append("plan_status_mismatch")
                try:
                    plan_bindings = _extract_plan_bindings(plan, repo)
                except ValueError as exc:
                    reasons.append(str(exc))

    declared_bindings = runtime["implementation_bindings"]
    declared_by_role = {row["role"]: row for row in declared_bindings}
    plan_by_role = {row["role"]: row for row in plan_bindings}
    if set(declared_by_role) != set(plan_by_role):
        reasons.append("implementation_binding_set_mismatch")
    for role, declared in declared_by_role.items():
        plan_row = plan_by_role.get(role)
        if plan_row is None:
            continue
        if declared != plan_row:
            reasons.append(f"implementation_plan_binding_mismatch:{role}")
        implementation_path = Path(declared["path"])
        if not implementation_path.is_file():
            reasons.append(f"implementation_missing:{role}")
        elif _file_sha256(implementation_path) != declared["sha256"]:
            reasons.append(f"implementation_bytes_mismatch:{role}")
        implementation_blob = _git_head_blob(
            repo,
            implementation_path,
            commit=runtime["canonical_git_commit"],
        )
        if implementation_blob is None:
            reasons.append(f"implementation_not_tracked:{role}")
        elif _sha256_bytes(implementation_blob) != declared["sha256"]:
            reasons.append(f"implementation_git_blob_mismatch:{role}")

    launcher_path_text = runtime["launcher_path"]
    if launcher_path_text is not None:
        launcher_path = Path(launcher_path_text)
        if not launcher_path.is_file():
            reasons.append("launcher_missing")
        elif _file_sha256(launcher_path) != runtime["launcher_sha256"]:
            reasons.append("launcher_sha256_mismatch")
        launcher_blob = _git_head_blob(
            repo,
            launcher_path,
            commit=runtime["canonical_git_commit"],
        )
        if launcher_blob is None:
            reasons.append("launcher_not_tracked")
        elif _sha256_bytes(launcher_blob) != runtime["launcher_sha256"]:
            reasons.append("launcher_git_blob_mismatch")
    elif runtime["scheduler_routable"]:
        reasons.append("routable_launcher_missing")

    if initial_head is not None:
        try:
            final_head = _git_output(repo, "rev-parse", "HEAD")
        except (OSError, subprocess.SubprocessError):
            reasons.append("repo_head_recheck_unreadable")
        else:
            if final_head != initial_head:
                reasons.append("repo_head_changed_during_validation")
    if initial_remote is not None:
        try:
            final_remote = _git_output(repo, "remote", "get-url", "origin")
        except (OSError, subprocess.SubprocessError):
            reasons.append("repo_remote_recheck_unreadable")
        else:
            if final_remote != initial_remote:
                reasons.append("repo_remote_changed_during_validation")

    runtime_status = runtime["runtime_status"]
    state_path = Path(runtime["state_path"])
    if runtime_status == "INACTIVE":
        state_status = "IGNORED_INACTIVE"
    elif runtime_status == "RETIRED":
        state_status = "IGNORED_RETIRED"
    elif not state_path.is_file():
        state_status = "MISSING"
    else:
        try:
            state_payload = _load_json_bytes(state_path.read_bytes())
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            DuplicateJsonKeyError,
        ):
            state_status = "CORRUPT"
        else:
            state_status = "READY" if isinstance(state_payload, dict) else "CORRUPT"

    if reasons:
        decision = "BLOCKED_BINDING_MISMATCH"
    elif runtime_status == "RETIRED":
        decision = "RETIRED_NOT_ROUTABLE"
    elif runtime_status == "INACTIVE":
        decision = "INACTIVE_NOT_ROUTABLE"
    elif state_status != "READY":
        decision = "RETRY_WITHOUT_LAUNCH"
    elif runtime["scheduler_routable"]:
        decision = "READY_ROUTABLE"
    else:
        decision = "READY_NOT_ROUTABLE"

    return {
        "strategy_id": strategy_id,
        "decision": decision,
        "launch_allowed": False,
        "state_status": state_status,
        "binding_status": "MATCH" if not reasons else "MISMATCH",
        "reasons": sorted(set(reasons)),
    }


def _invalid_result(raw_sha256: str | None, reasons: Iterable[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "registry_valid": False,
        "decision": "REGISTRY_INVALID",
        "launch_allowed": False,
        "registry_raw_sha256": raw_sha256,
        "reasons": sorted(set(reasons)),
        "runtimes": [],
    }


def validate_registry(
    path: str | Path,
    expected_raw_sha256: str | None = None,
) -> dict[str, Any]:
    registry_path = Path(path)
    try:
        raw = registry_path.read_bytes()
    except OSError as exc:
        return _invalid_result(None, [f"registry_read_error:{type(exc).__name__}"])

    raw_sha256 = _sha256_bytes(raw)
    if expected_raw_sha256 is not None and expected_raw_sha256 != raw_sha256:
        return _invalid_result(raw_sha256, ["registry_raw_sha256_mismatch"])
    try:
        payload = _load_json_bytes(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        return _invalid_result(raw_sha256, [f"registry_json_invalid:{exc}"])

    structural_reasons, runtimes = _validate_structure(payload)
    if structural_reasons:
        return _invalid_result(raw_sha256, structural_reasons)

    runtime_results = [_runtime_binding_result(runtime) for runtime in runtimes]
    all_runtime_ready = all(
        row["decision"]
        in {
            "READY_NOT_ROUTABLE",
            "INACTIVE_NOT_ROUTABLE",
            "RETIRED_NOT_ROUTABLE",
        }
        for row in runtime_results
    )
    return {
        "ok": all_runtime_ready,
        "registry_valid": True,
        "decision": "STAGED_FAIL_CLOSED"
        if all_runtime_ready
        else "PARTIAL_RUNTIME_BLOCK",
        "launch_allowed": False,
        "registry_raw_sha256": raw_sha256,
        "reasons": [],
        "runtimes": runtime_results,
    }


def generate_staged_registry(
    source_path: str | Path,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    del source_path, generated_at_utc
    raise ValueError("external_head_materializer_required")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline validator for the canonical strategy runtime registry."
    )
    parser.add_argument("--validate", required=True, type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = validate_registry(
        args.validate,
        expected_raw_sha256=args.expected_sha256,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{result['decision']} registry_valid={str(result['registry_valid']).lower()} "
            f"launch_allowed={str(result['launch_allowed']).lower()}"
        )
        for reason in result["reasons"]:
            print(f"reason={reason}")
        for runtime in result["runtimes"]:
            print(
                f"runtime={runtime['strategy_id']} decision={runtime['decision']} "
                f"state={runtime['state_status']}"
            )
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
