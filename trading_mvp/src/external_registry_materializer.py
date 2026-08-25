from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable


RECEIPT_SCHEMA = "zolotyaylopata.external_registry_materialization_receipt.v2"
REGISTRY_FILENAME = "canonical_strategy_runtime.json"
RECEIPT_FILENAME = "materialization_receipt.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class MaterializationError(RuntimeError):
    """A fail-closed external registry materialization error."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_executable() -> str:
    windows_git = Path(r"C:\Program Files\Git\cmd\git.exe")
    if os.name == "nt":
        if not windows_git.is_file():
            raise MaterializationError("pinned_git_executable_missing")
        return str(windows_git)
    discovered = shutil.which("git")
    if discovered:
        return discovered
    raise MaterializationError("git_executable_missing")


def _git_run(repo: Path, *args: str, text: bool = False) -> bytes | str:
    try:
        completed = subprocess.run(
            [_git_executable(), "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MaterializationError(
            f"git_command_failed:{repo}:{' '.join(args)}:{type(exc).__name__}"
        ) from exc
    if text:
        assert isinstance(completed.stdout, str)
        return completed.stdout.strip()
    assert isinstance(completed.stdout, bytes)
    return completed.stdout


def _git_root(path: Path) -> Path:
    probe = path if path.is_dir() else path.parent
    root_text = _git_run(probe, "rev-parse", "--show-toplevel", text=True)
    assert isinstance(root_text, str)
    root = Path(root_text).resolve(strict=True)
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise MaterializationError(f"path_outside_git_root:{path}") from exc
    return root


def _repo_head(repo: Path) -> str:
    value = _git_run(repo, "rev-parse", "HEAD", text=True)
    assert isinstance(value, str)
    if not _COMMIT_RE.fullmatch(value):
        raise MaterializationError(f"invalid_repo_head:{repo}:{value}")
    return value


def _repo_remote(repo: Path) -> str:
    value = _git_run(repo, "remote", "get-url", "origin", text=True)
    assert isinstance(value, str)
    if not value:
        raise MaterializationError(f"missing_origin_remote:{repo}")
    return value


def _relative_repo_path(repo: Path, path: Path, *, field: str) -> str:
    resolved_repo = repo.resolve(strict=True)
    resolved_path = path.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(resolved_repo)
    except ValueError as exc:
        raise MaterializationError(
            f"path_outside_canonical_repo:{field}:{path}"
        ) from exc
    if not relative.parts:
        raise MaterializationError(f"path_is_canonical_repo:{field}:{path}")
    return relative.as_posix()


def _head_blob(repo: Path, commit: str, path: Path, *, field: str) -> bytes:
    resolved_repo = repo.resolve(strict=True)
    actual_root = _git_root(resolved_repo)
    if actual_root != resolved_repo:
        raise MaterializationError(
            f"canonical_repo_not_git_toplevel:{field}:{resolved_repo}:{actual_root}"
        )
    relative = _relative_repo_path(repo, path, field=field)
    try:
        raw = _git_run(repo, "show", f"{commit}:{relative}")
    except MaterializationError as exc:
        raise MaterializationError(f"head_blob_missing:{field}:{path}") from exc
    assert isinstance(raw, bytes)
    return raw


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_new_file(path: Path, raw: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise MaterializationError(f"publication_file_write_failed:{path.name}") from exc


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    if os.name == "nt":
        try:
            os.rename(source, destination)
        except OSError as exc:
            raise MaterializationError(
                f"publication_directory_publish_failed:{destination}"
            ) from exc
        return

    if os.name != "posix":
        raise MaterializationError("atomic_directory_publish_unsupported")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise MaterializationError("renameat2_unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd,
        os.fsencode(source),
        at_fdcwd,
        os.fsencode(destination),
        rename_noreplace,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.ENOSYS:
            raise MaterializationError("renameat2_unavailable")
        raise MaterializationError(
            f"publication_directory_publish_failed:{destination}:{error_number}"
        )


def _open_publication_root_guard(root: Path) -> tuple[str, int]:
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        create_file.restype = ctypes.c_void_p
        file_share_read = 0x00000001
        file_share_write = 0x00000002
        open_existing = 3
        file_flag_backup_semantics = 0x02000000
        handle = create_file(
            str(root),
            0,
            file_share_read | file_share_write,
            None,
            open_existing,
            file_flag_backup_semantics,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, invalid_handle):
            raise MaterializationError(
                f"publication_root_guard_open_failed:{ctypes.get_last_error()}"
            )
        return "windows_handle", int(handle)

    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as exc:
        raise MaterializationError("publication_root_guard_open_failed") from exc
    return "directory_fd", descriptor


def _close_publication_root_guard(guard: tuple[str, int]) -> None:
    kind, value = guard
    if kind == "windows_handle":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        if close_handle(ctypes.c_void_p(value)) == 0:
            raise MaterializationError(
                f"publication_root_guard_close_failed:{ctypes.get_last_error()}"
            )
        return
    os.close(value)


def _publish_versioned_pair(
    *,
    publication_root: Path,
    expected_root_identity: tuple[str, int, int],
    protected_snapshots: dict[str, dict[str, str]],
    publication_id: str,
    registry_raw: bytes,
    receipt_raw: bytes,
    pre_publish_guard: Callable[[], None],
) -> tuple[Path, Path]:
    if not _SHA256_RE.fullmatch(publication_id):
        raise MaterializationError("publication_id_invalid")
    resolved_root = publication_root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise MaterializationError("publication_root_not_directory")
    root_identity = _output_parent_identity(resolved_root / "placeholder")
    if root_identity != expected_root_identity:
        raise MaterializationError(
            "publication_root_path_changed_during_materialization"
        )
    _assert_external_output_paths(
        resolved_root / "candidate",
        resolved_root / "receipt",
        protected_snapshots,
    )
    publication_directory = resolved_root / publication_id
    registry_path = publication_directory / REGISTRY_FILENAME
    receipt_path = publication_directory / RECEIPT_FILENAME
    lock_path = resolved_root / f".{publication_id}.lock"
    root_guard = _open_publication_root_guard(resolved_root)
    lock_descriptor: int | None = None
    temporary_directory: Path | None = None
    try:
        try:
            lock_descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except OSError as exc:
            raise MaterializationError(
                f"publication_lock_unavailable:{publication_id}"
            ) from exc
        if publication_directory.exists():
            raise MaterializationError(
                f"publication_already_exists:{publication_directory}"
            )
        temporary_directory = Path(
            tempfile.mkdtemp(
                prefix=f".{publication_id}.",
                suffix=".tmp",
                dir=resolved_root,
            )
        )
        _write_new_file(temporary_directory / REGISTRY_FILENAME, registry_raw)
        _write_new_file(temporary_directory / RECEIPT_FILENAME, receipt_raw)
        pre_publish_guard()
        _assert_output_parent_unchanged(
            "publication_root",
            resolved_root / "placeholder",
            expected_root_identity,
        )
        if publication_directory.exists():
            raise MaterializationError(
                f"publication_appeared_during_write:{publication_directory}"
            )
        _rename_directory_no_replace(temporary_directory, publication_directory)
        temporary_directory = None
        if registry_path.read_bytes() != registry_raw:
            raise MaterializationError("published_registry_readback_mismatch")
        if receipt_path.read_bytes() != receipt_raw:
            raise MaterializationError("published_receipt_readback_mismatch")
    finally:
        if temporary_directory is not None and temporary_directory.exists():
            shutil.rmtree(temporary_directory)
        if lock_descriptor is not None:
            os.close(lock_descriptor)
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
        _close_publication_root_guard(root_guard)
    return registry_path, receipt_path


def _snapshot_repository(repo: Path) -> dict[str, str]:
    resolved = repo.resolve(strict=True)
    actual_root = _git_root(resolved)
    if actual_root != resolved:
        raise MaterializationError(
            f"canonical_repo_not_git_toplevel:{resolved}:{actual_root}"
        )
    if not (resolved / ".git").exists():
        # Worktrees may use a .git file; rev-parse remains authoritative.
        _git_run(resolved, "rev-parse", "--git-dir", text=True)
    return {
        "canonical_repo": str(resolved),
        "canonical_git_commit": _repo_head(resolved),
        "canonical_remote_url": _repo_remote(resolved),
    }


def _assert_heads_unchanged(snapshots: dict[str, dict[str, str]]) -> None:
    for repo_text, snapshot in snapshots.items():
        current = _repo_head(Path(repo_text))
        expected = snapshot["canonical_git_commit"]
        if current != expected:
            raise MaterializationError(
                f"repository_head_changed:{repo_text}:{expected}:{current}"
            )
        current_remote = _repo_remote(Path(repo_text))
        expected_remote = snapshot["canonical_remote_url"]
        if current_remote != expected_remote:
            raise MaterializationError(
                "repository_remote_changed:"
                f"{repo_text}:{expected_remote}:{current_remote}"
            )


def _assert_external_output_paths(
    output: Path,
    receipt: Path,
    snapshots: dict[str, dict[str, str]],
) -> None:
    for label, candidate in (("output", output), ("receipt", receipt)):
        resolved_candidate = candidate.resolve(strict=False)
        for repo_text in snapshots:
            repo = Path(repo_text).resolve(strict=True)
            try:
                resolved_candidate.relative_to(repo)
            except ValueError:
                continue
            raise MaterializationError(f"{label}_inside_canonical_repo:{repo}")


def _output_parent_identity(path: Path) -> tuple[str, int, int]:
    try:
        parent = path.parent.resolve(strict=True)
        stat = parent.stat()
    except OSError as exc:
        raise MaterializationError(f"output_parent_unavailable:{path.parent}") from exc
    return str(parent), stat.st_dev, stat.st_ino


def _assert_output_parent_unchanged(
    label: str,
    path: Path,
    expected_identity: tuple[str, int, int],
) -> None:
    current_identity = _output_parent_identity(path)
    if current_identity != expected_identity:
        raise MaterializationError(
            f"{label}_path_changed_during_materialization:"
            f"{expected_identity[0]}:{current_identity[0]}"
        )


def _build_registry_from_snapshots(
    source_payload: dict[str, Any],
    snapshots: dict[str, dict[str, str]],
    runtime_registry: types.ModuleType,
) -> dict[str, Any]:
    generated = json.loads(json.dumps(source_payload, ensure_ascii=False))
    generated["activation_status"] = runtime_registry.STAGING_ACTIVATION_STATUS

    for runtime in generated["runtimes"]:
        strategy_id = runtime["strategy_id"]
        repo = Path(runtime["canonical_repo"]).resolve(strict=True)
        snapshot = snapshots[str(repo)]
        commit = snapshot["canonical_git_commit"]
        if runtime["canonical_remote_url"] != snapshot["canonical_remote_url"]:
            raise MaterializationError(
                f"canonical_remote_mismatch:{strategy_id}:"
                f"{runtime['canonical_remote_url']}:{snapshot['canonical_remote_url']}"
            )
        runtime["canonical_repo"] = str(repo)
        runtime["canonical_git_commit"] = commit
        runtime["canonical_remote_url"] = snapshot["canonical_remote_url"]
        runtime["scheduler_routable"] = False
        runtime["public_data_only"] = True
        runtime["live_trading_allowed"] = False
        runtime["allowed_modes"] = [
            mode
            for mode in runtime["allowed_modes"]
            if not str(mode).upper().startswith("LIVE")
        ]
        if not runtime["allowed_modes"]:
            raise MaterializationError(f"no_non_live_mode:{strategy_id}")

        plan_path = Path(runtime["canonical_plan_path"])
        plan_raw = _head_blob(
            repo,
            commit,
            plan_path,
            field=f"{strategy_id}:canonical_plan_path",
        )
        try:
            plan = runtime_registry._load_json_bytes(plan_raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise MaterializationError(f"plan_json_invalid:{strategy_id}") from exc
        if not isinstance(plan, dict):
            raise MaterializationError(f"plan_not_object:{strategy_id}")
        calculated_plan_hash = runtime_registry.canonical_plan_hash(plan)
        if plan.get("plan_hash") != calculated_plan_hash:
            raise MaterializationError(f"plan_internal_hash_invalid:{strategy_id}")
        try:
            plan_bindings = runtime_registry._extract_plan_bindings(plan, repo)
        except ValueError as exc:
            raise MaterializationError(
                f"plan_implementation_invalid:{strategy_id}:{exc}"
            ) from exc

        verified_bindings: list[dict[str, str]] = []
        for binding in plan_bindings:
            role = binding["role"]
            implementation_path = Path(binding["path"])
            implementation_raw = _head_blob(
                repo,
                commit,
                implementation_path,
                field=f"{strategy_id}:implementation:{role}",
            )
            actual_sha256 = _sha256_bytes(implementation_raw)
            if actual_sha256 != binding["sha256"]:
                raise MaterializationError(
                    "implementation_head_sha256_mismatch:"
                    f"{strategy_id}:{role}:{binding['sha256']}:{actual_sha256}"
                )
            verified_bindings.append(
                {
                    "role": role,
                    "path": str(implementation_path.resolve(strict=False)),
                    "sha256": actual_sha256,
                }
            )

        runtime["canonical_plan_path"] = str(plan_path.resolve(strict=False))
        runtime["canonical_plan_sha256"] = calculated_plan_hash
        runtime["canonical_plan_file_sha256"] = _sha256_bytes(plan_raw)
        runtime["canonical_plan_id"] = plan.get("plan_id")
        runtime["canonical_plan_status"] = plan.get("status")
        runtime["implementation_bindings"] = verified_bindings

        launcher_text = runtime["launcher_path"]
        if launcher_text is None:
            runtime["launcher_sha256"] = None
        else:
            launcher_path = Path(launcher_text)
            launcher_raw = _head_blob(
                repo,
                commit,
                launcher_path,
                field=f"{strategy_id}:launcher_path",
            )
            runtime["launcher_path"] = str(launcher_path.resolve(strict=False))
            runtime["launcher_sha256"] = _sha256_bytes(launcher_raw)

    structural_reasons, _ = runtime_registry._validate_structure(generated)
    if structural_reasons:
        raise MaterializationError(
            "generated_registry_structure_invalid:" + ";".join(structural_reasons)
        )
    return generated


def _validate_generated_registry_against_snapshots(
    payload: dict[str, Any],
    snapshots: dict[str, dict[str, str]],
    runtime_registry: types.ModuleType,
) -> dict[str, Any]:
    structural_reasons, _ = runtime_registry._validate_structure(payload)
    if structural_reasons:
        raise MaterializationError(
            "materialized_registry_structure_invalid:" + ";".join(structural_reasons)
        )

    for runtime in payload["runtimes"]:
        strategy_id = runtime["strategy_id"]
        repo = Path(runtime["canonical_repo"]).resolve(strict=True)
        snapshot = snapshots.get(str(repo))
        if snapshot is None:
            raise MaterializationError(f"runtime_snapshot_missing:{strategy_id}")
        commit = snapshot["canonical_git_commit"]
        if runtime["canonical_git_commit"] != commit:
            raise MaterializationError(f"runtime_commit_mismatch:{strategy_id}")
        if runtime["canonical_remote_url"] != snapshot["canonical_remote_url"]:
            raise MaterializationError(f"runtime_remote_mismatch:{strategy_id}")

        plan_path = Path(runtime["canonical_plan_path"])
        plan_raw = _head_blob(
            repo,
            commit,
            plan_path,
            field=f"{strategy_id}:validation:canonical_plan_path",
        )
        if _sha256_bytes(plan_raw) != runtime["canonical_plan_file_sha256"]:
            raise MaterializationError(f"plan_file_sha256_mismatch:{strategy_id}")
        try:
            plan = runtime_registry._load_json_bytes(plan_raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise MaterializationError(
                f"validation_plan_json_invalid:{strategy_id}"
            ) from exc
        if not isinstance(plan, dict):
            raise MaterializationError(f"validation_plan_not_object:{strategy_id}")
        plan_hash = runtime_registry.canonical_plan_hash(plan)
        if plan.get("plan_hash") != plan_hash:
            raise MaterializationError(
                f"validation_plan_internal_hash_invalid:{strategy_id}"
            )
        if runtime["canonical_plan_sha256"] != plan_hash:
            raise MaterializationError(f"plan_hash_mismatch:{strategy_id}")
        if runtime["canonical_plan_id"] != plan.get("plan_id"):
            raise MaterializationError(f"plan_id_mismatch:{strategy_id}")
        if runtime["canonical_plan_status"] != plan.get("status"):
            raise MaterializationError(f"plan_status_mismatch:{strategy_id}")

        try:
            plan_bindings = runtime_registry._extract_plan_bindings(plan, repo)
        except ValueError as exc:
            raise MaterializationError(
                f"validation_plan_implementation_invalid:{strategy_id}:{exc}"
            ) from exc
        plan_by_role = {row["role"]: row for row in plan_bindings}
        runtime_by_role = {
            row["role"]: row for row in runtime["implementation_bindings"]
        }
        if set(plan_by_role) != set(runtime_by_role):
            raise MaterializationError(
                f"implementation_binding_set_mismatch:{strategy_id}"
            )
        for role, plan_binding in plan_by_role.items():
            runtime_binding = runtime_by_role[role]
            implementation_path = Path(runtime_binding["path"])
            if implementation_path.resolve(strict=False) != Path(
                plan_binding["path"]
            ).resolve(strict=False):
                raise MaterializationError(
                    f"implementation_path_mismatch:{strategy_id}:{role}"
                )
            implementation_raw = _head_blob(
                repo,
                commit,
                implementation_path,
                field=f"{strategy_id}:validation:implementation:{role}",
            )
            actual_sha256 = _sha256_bytes(implementation_raw)
            if (
                runtime_binding["sha256"] != actual_sha256
                or plan_binding["sha256"] != actual_sha256
            ):
                raise MaterializationError(
                    f"implementation_binding_mismatch:{strategy_id}:{role}"
                )

        launcher_text = runtime["launcher_path"]
        if launcher_text is None:
            if runtime["launcher_sha256"] is not None:
                raise MaterializationError(f"launcher_sha_without_path:{strategy_id}")
        else:
            launcher_raw = _head_blob(
                repo,
                commit,
                Path(launcher_text),
                field=f"{strategy_id}:validation:launcher_path",
            )
            if _sha256_bytes(launcher_raw) != runtime["launcher_sha256"]:
                raise MaterializationError(f"launcher_binding_mismatch:{strategy_id}")
        if runtime["scheduler_routable"] is not False:
            raise MaterializationError(f"scheduler_routable_forbidden:{strategy_id}")
        if runtime["live_trading_allowed"] is not False:
            raise MaterializationError(f"live_trading_forbidden:{strategy_id}")

    return {
        "registry_valid": True,
        "all_runtime_bindings_valid": True,
        "decision": "STAGED_FAIL_CLOSED",
        "launch_allowed": False,
    }


def _bind_control_plane_file(
    *,
    path: Path,
    expected_commit: str,
    expected_sha256: str,
    field: str,
) -> dict[str, Any]:
    repo = _git_root(path)
    head = _repo_head(repo)
    if head != expected_commit:
        raise MaterializationError(
            f"control_plane_commit_mismatch:{field}:{expected_commit}:{head}"
        )
    head_raw = _head_blob(repo, head, path, field=field)
    head_sha256 = _sha256_bytes(head_raw)
    if head_sha256 != expected_sha256:
        raise MaterializationError(
            f"{field}_head_sha256_mismatch:{expected_sha256}:{head_sha256}"
        )
    try:
        worktree_raw = path.read_bytes()
    except OSError as exc:
        raise MaterializationError(f"{field}_worktree_read_error") from exc
    if worktree_raw != head_raw:
        raise MaterializationError(f"{field}_worktree_differs_from_head")
    return {
        "path": str(path),
        "repo": str(repo),
        "git_commit": head,
        "head_sha256": head_sha256,
        "head_raw": head_raw,
    }


def _assert_control_plane_binding_unchanged(binding: dict[str, Any]) -> None:
    path = Path(binding["path"])
    repo = Path(binding["repo"])
    if _repo_head(repo) != binding["git_commit"]:
        raise MaterializationError(
            f"control_plane_head_changed:{path}:{binding['git_commit']}"
        )
    try:
        worktree_raw = path.read_bytes()
    except OSError as exc:
        raise MaterializationError(f"control_plane_worktree_unreadable:{path}") from exc
    if worktree_raw != binding["head_raw"]:
        raise MaterializationError(f"control_plane_worktree_changed:{path}")


def _load_bound_validator(binding: dict[str, Any]) -> types.ModuleType:
    path = Path(binding["path"])
    raw = binding["head_raw"]
    if not isinstance(raw, bytes):
        raise MaterializationError("validator_bound_bytes_invalid")
    module = types.ModuleType("_zolotyaylopata_bound_canonical_strategy_runtime")
    module.__file__ = str(path)
    module.__package__ = None
    try:
        code = compile(raw, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except BaseException as exc:
        raise MaterializationError(
            f"validator_bound_module_load_failed:{type(exc).__name__}"
        ) from exc
    for attribute in (
        "STAGING_ACTIVATION_STATUS",
        "_load_json_bytes",
        "_validate_structure",
        "_extract_plan_bindings",
        "canonical_plan_hash",
    ):
        if not hasattr(module, attribute):
            raise MaterializationError(
                f"validator_bound_module_attribute_missing:{attribute}"
            )
    return module


def materialize_external_registry(
    *,
    source_path: str | Path,
    publication_root: str | Path,
    expected_source_head_sha256: str,
    expected_materializer_head_sha256: str,
    expected_validator_head_sha256: str,
    expected_control_plane_git_commit: str,
) -> dict[str, Any]:
    if not _SHA256_RE.fullmatch(expected_source_head_sha256):
        raise MaterializationError("expected_source_head_sha256_invalid")
    if not _SHA256_RE.fullmatch(expected_materializer_head_sha256):
        raise MaterializationError("expected_materializer_head_sha256_invalid")
    if not _SHA256_RE.fullmatch(expected_validator_head_sha256):
        raise MaterializationError("expected_validator_head_sha256_invalid")
    if not _COMMIT_RE.fullmatch(expected_control_plane_git_commit):
        raise MaterializationError("expected_control_plane_git_commit_invalid")

    source = Path(source_path).resolve(strict=False)
    publication_root_path = Path(publication_root).resolve(strict=True)
    if not publication_root_path.is_dir():
        raise MaterializationError("publication_root_not_directory")
    publication_root_identity = _output_parent_identity(
        publication_root_path / "placeholder"
    )

    materializer_entrypoint = Path(__file__).resolve(strict=False)
    validator_entrypoint = materializer_entrypoint.with_name(
        "canonical_strategy_runtime.py"
    )
    materializer_binding = _bind_control_plane_file(
        path=materializer_entrypoint,
        expected_commit=expected_control_plane_git_commit,
        expected_sha256=expected_materializer_head_sha256,
        field="materializer",
    )
    validator_binding = _bind_control_plane_file(
        path=validator_entrypoint,
        expected_commit=expected_control_plane_git_commit,
        expected_sha256=expected_validator_head_sha256,
        field="validator",
    )
    if materializer_binding["repo"] != validator_binding["repo"]:
        raise MaterializationError("control_plane_files_cross_repository")
    runtime_registry = _load_bound_validator(validator_binding)
    materializer_repo = Path(materializer_binding["repo"])
    materializer_commit = materializer_binding["git_commit"]
    materializer_head_sha256 = materializer_binding["head_sha256"]
    validator_head_sha256 = validator_binding["head_sha256"]

    source_repo = _git_root(source)
    source_commit = _repo_head(source_repo)
    source_raw = _head_blob(
        source_repo,
        source_commit,
        source,
        field="registry_source",
    )
    source_head_sha256 = _sha256_bytes(source_raw)
    if source_head_sha256 != expected_source_head_sha256:
        raise MaterializationError(
            "source_head_sha256_mismatch:"
            f"{expected_source_head_sha256}:{source_head_sha256}"
        )
    try:
        source_payload = runtime_registry._load_json_bytes(source_raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MaterializationError("source_json_invalid") from exc
    structural_reasons, _ = runtime_registry._validate_structure(source_payload)
    if structural_reasons:
        raise MaterializationError(
            "source_structure_invalid:" + ";".join(structural_reasons)
        )

    snapshots: dict[str, dict[str, str]] = {}
    for runtime in source_payload["runtimes"]:
        repo = Path(runtime["canonical_repo"]).resolve(strict=True)
        repo_text = str(repo)
        if repo_text not in snapshots:
            snapshots[repo_text] = _snapshot_repository(repo)

    protected_snapshots = dict(snapshots)
    for protected_repo in (source_repo, materializer_repo):
        protected_text = str(protected_repo.resolve(strict=True))
        protected_snapshots.setdefault(
            protected_text,
            {
                "canonical_repo": protected_text,
                "canonical_git_commit": _repo_head(protected_repo),
                "canonical_remote_url": _repo_remote(protected_repo),
            },
        )
    _assert_external_output_paths(
        publication_root_path / "candidate",
        publication_root_path / "receipt",
        protected_snapshots,
    )

    generated = _build_registry_from_snapshots(
        source_payload,
        snapshots,
        runtime_registry,
    )
    registry_raw = _canonical_json_bytes(generated)
    round_trip_payload = runtime_registry._load_json_bytes(registry_raw)
    if not isinstance(round_trip_payload, dict):
        raise MaterializationError("materialized_registry_not_object")
    validation = _validate_generated_registry_against_snapshots(
        round_trip_payload,
        snapshots,
        runtime_registry,
    )
    if validation["launch_allowed"] is not False:
        raise MaterializationError("materialized_registry_launch_allowed")
    registry_raw_sha256 = _sha256_bytes(registry_raw)
    validation["ok"] = True
    validation["registry_raw_sha256"] = registry_raw_sha256

    canonical_repositories = [
        {
            "canonical_repo": snapshot["canonical_repo"],
            "canonical_git_commit": snapshot["canonical_git_commit"],
        }
        for snapshot in sorted(
            snapshots.values(), key=lambda row: row["canonical_repo"].casefold()
        )
    ]
    publication_descriptor = {
        "schema": "zolotyaylopata.external_registry_publication_identity.v1",
        "source_git_commit": source_commit,
        "source_head_sha256": source_head_sha256,
        "control_plane_git_commit": materializer_commit,
        "materializer_head_sha256": materializer_head_sha256,
        "validator_head_sha256": validator_head_sha256,
        "registry_raw_sha256": registry_raw_sha256,
        "canonical_repositories": canonical_repositories,
    }
    publication_id = _sha256_bytes(_canonical_json_bytes(publication_descriptor))
    publication_directory = publication_root_path / publication_id
    output = publication_directory / REGISTRY_FILENAME
    receipt = publication_directory / RECEIPT_FILENAME
    receipt_payload = {
        "schema": RECEIPT_SCHEMA,
        "status": "MATERIALIZED_FAIL_CLOSED",
        "decision": "STAGED_FAIL_CLOSED",
        "launch_allowed": False,
        "publication_id": publication_id,
        "publication_directory": str(publication_directory),
        "source_path": str(source),
        "source_git_commit": source_commit,
        "source_head_sha256": source_head_sha256,
        "materializer_path": str(materializer_entrypoint),
        "materializer_git_commit": materializer_commit,
        "materializer_head_sha256": materializer_head_sha256,
        "validator_path": str(validator_entrypoint),
        "validator_git_commit": validator_binding["git_commit"],
        "validator_head_sha256": validator_head_sha256,
        "registry_path": str(output),
        "receipt_path": str(receipt),
        "registry_raw_sha256": registry_raw_sha256,
        "canonical_repositories": canonical_repositories,
        "validation": validation,
    }
    receipt_raw = _canonical_json_bytes(receipt_payload)
    receipt_raw_sha256 = _sha256_bytes(receipt_raw)

    def pre_publish_guard() -> None:
        _assert_output_parent_unchanged(
            "publication_root",
            publication_root_path / "placeholder",
            publication_root_identity,
        )
        _assert_external_output_paths(
            output,
            receipt,
            protected_snapshots,
        )
        if _repo_head(source_repo) != source_commit:
            raise MaterializationError(
                f"source_repository_head_changed:{source_repo}:{source_commit}"
            )
        if _repo_head(materializer_repo) != materializer_commit:
            raise MaterializationError(
                "materializer_repository_head_changed:"
                f"{materializer_repo}:{materializer_commit}"
            )
        _assert_heads_unchanged(snapshots)
        _assert_control_plane_binding_unchanged(materializer_binding)
        _assert_control_plane_binding_unchanged(validator_binding)

    pre_publish_guard()

    published_registry, published_receipt = _publish_versioned_pair(
        publication_root=publication_root_path,
        expected_root_identity=publication_root_identity,
        protected_snapshots=protected_snapshots,
        publication_id=publication_id,
        registry_raw=registry_raw,
        receipt_raw=receipt_raw,
        pre_publish_guard=pre_publish_guard,
    )
    if published_registry.read_bytes() != registry_raw:
        raise MaterializationError("published_registry_readback_mismatch")
    if published_receipt.read_bytes() != receipt_raw:
        raise MaterializationError("published_receipt_readback_mismatch")

    return {
        "status": "MATERIALIZED_FAIL_CLOSED",
        "decision": "STAGED_FAIL_CLOSED",
        "launch_allowed": False,
        "publication_id": publication_id,
        "publication_directory": str(publication_directory),
        "registry_path": str(published_registry),
        "receipt_path": str(published_receipt),
        "registry_raw_sha256": registry_raw_sha256,
        "receipt_raw_sha256": receipt_raw_sha256,
        "source_head_sha256": source_head_sha256,
        "materializer_head_sha256": materializer_head_sha256,
        "validator_head_sha256": validator_head_sha256,
        "control_plane_git_commit": materializer_commit,
        "canonical_repositories": canonical_repositories,
        "validation": validation,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize a deterministic fail-closed registry from Git HEAD."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--publication-root", required=True, type=Path)
    parser.add_argument("--expected-source-head-sha256", required=True)
    parser.add_argument("--expected-materializer-head-sha256", required=True)
    parser.add_argument("--expected-validator-head-sha256", required=True)
    parser.add_argument("--expected-control-plane-git-commit", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = materialize_external_registry(
            source_path=args.source,
            publication_root=args.publication_root,
            expected_source_head_sha256=args.expected_source_head_sha256,
            expected_materializer_head_sha256=(args.expected_materializer_head_sha256),
            expected_validator_head_sha256=args.expected_validator_head_sha256,
            expected_control_plane_git_commit=(
                args.expected_control_plane_git_commit
            ),
        )
    except MaterializationError as exc:
        result = {
            "status": "MATERIALIZATION_BLOCKED",
            "decision": "STAGED_FAIL_CLOSED",
            "launch_allowed": False,
            "reason": str(exc),
        }
        exit_code = 2
    else:
        exit_code = 0
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{result['status']} launch_allowed={str(result['launch_allowed']).lower()}"
        )
        if "registry_raw_sha256" in result:
            print(f"registry_raw_sha256={result['registry_raw_sha256']}")
            print(f"receipt_path={result['receipt_path']}")
        if "reason" in result:
            print(f"reason={result['reason']}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
