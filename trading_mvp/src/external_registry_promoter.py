from __future__ import annotations

import argparse
import copy
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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


RECEIPT_SCHEMA = "zolotyaylopata.external_registry_activation_receipt.v1"
REGISTRY_FILENAME = "canonical_strategy_runtime.json"
RECEIPT_FILENAME = "activation_receipt.json"
ACTIVE_READINESS = "READY_AFTER_ROUTER_MIGRATION"
ACTIVE_ALLOWED_MODES = frozenset({"DISCOVERY", "PAPER_RESEARCH"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class PromotionError(RuntimeError):
    """A fail-closed canonical public-research activation error."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def _file_identity(path: Path) -> tuple[str, int, int, int, int]:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    return (
        str(resolved),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
    )


def _read_stable_file(path: Path, *, field: str) -> tuple[Path, bytes, tuple[str, int, int, int, int]]:
    try:
        resolved = path.resolve(strict=True)
        before = _file_identity(resolved)
        raw = resolved.read_bytes()
        after = _file_identity(resolved)
    except OSError as exc:
        raise PromotionError(f"{field}_read_failed:{type(exc).__name__}") from exc
    if before != after or len(raw) != before[3]:
        raise PromotionError(f"{field}_changed_during_read")
    return resolved, raw, after


def _assert_stable_file(
    path: Path,
    expected_raw: bytes,
    expected_identity: tuple[str, int, int, int, int],
    *,
    field: str,
) -> None:
    try:
        resolved = path.resolve(strict=True)
        identity = _file_identity(resolved)
        raw = resolved.read_bytes()
        final_identity = _file_identity(resolved)
    except OSError as exc:
        raise PromotionError(f"{field}_unreadable_during_promotion") from exc
    if (
        str(resolved) != expected_identity[0]
        or identity != expected_identity
        or final_identity != expected_identity
        or raw != expected_raw
    ):
        raise PromotionError(f"{field}_changed_during_promotion")


def _parse_utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PromotionError(f"{field}_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PromotionError(f"{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise PromotionError(f"{field}_invalid")
    return parsed


def _write_new_file(path: Path, raw: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise PromotionError(f"publication_file_write_failed:{path.name}") from exc


def _publish_active_pair(
    *,
    publication_module: types.ModuleType,
    publication_root: Path,
    expected_root_identity: tuple[str, int, int],
    protected_snapshots: dict[str, dict[str, str]],
    publication_id: str,
    registry_raw: bytes,
    receipt_raw: bytes,
    pre_publish_guard: Callable[[], None],
) -> tuple[Path, Path]:
    publication = publication_module
    if not _SHA256_RE.fullmatch(publication_id):
        raise PromotionError("publication_id_invalid")
    resolved_root = publication_root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise PromotionError("publication_root_not_directory")
    if publication._output_parent_identity(resolved_root / "placeholder") != expected_root_identity:
        raise PromotionError("publication_root_path_changed_during_promotion")
    publication._assert_external_output_paths(
        resolved_root / "candidate",
        resolved_root / "receipt",
        protected_snapshots,
    )

    publication_directory = resolved_root / publication_id
    registry_path = publication_directory / REGISTRY_FILENAME
    receipt_path = publication_directory / RECEIPT_FILENAME
    lock_path = resolved_root / f".{publication_id}.activation.lock"
    root_guard = publication._open_publication_root_guard(resolved_root)
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
            raise PromotionError(
                f"publication_lock_unavailable:{publication_id}"
            ) from exc
        if publication_directory.exists():
            raise PromotionError(f"publication_already_exists:{publication_directory}")
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
        if (
            publication._output_parent_identity(resolved_root / "placeholder")
            != expected_root_identity
        ):
            raise PromotionError("publication_root_path_changed_during_promotion")
        if publication_directory.exists():
            raise PromotionError(
                f"publication_appeared_during_write:{publication_directory}"
            )
        publication._rename_directory_no_replace(
            temporary_directory,
            publication_directory,
        )
        temporary_directory = None
        if registry_path.read_bytes() != registry_raw:
            raise PromotionError("published_registry_readback_mismatch")
        if receipt_path.read_bytes() != receipt_raw:
            raise PromotionError("published_receipt_readback_mismatch")
    except publication.MaterializationError as exc:
        raise PromotionError(str(exc)) from exc
    finally:
        if temporary_directory is not None and temporary_directory.exists():
            shutil.rmtree(temporary_directory)
        if lock_descriptor is not None:
            os.close(lock_descriptor)
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            publication._close_publication_root_guard(root_guard)
        except publication.MaterializationError as exc:
            raise PromotionError(str(exc)) from exc
    return registry_path, receipt_path


def _bootstrap_git(repo: Path, *args: str) -> bytes:
    windows_git = Path(r"C:\Program Files\Git\cmd\git.exe")
    if os.name == "nt":
        if not windows_git.is_file():
            raise PromotionError("pinned_git_executable_missing")
        executable = str(windows_git)
    else:
        discovered = shutil.which("git")
        if not discovered:
            raise PromotionError("git_executable_missing")
        executable = discovered
    try:
        completed = subprocess.run(
            [executable, "-C", str(repo), *args],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PromotionError(
            f"control_bootstrap_git_failed:{type(exc).__name__}"
        ) from exc
    return completed.stdout


def _load_bound_publication(
    *,
    expected_commit: str,
    expected_sha256: str,
) -> tuple[types.ModuleType, dict[str, Any]]:
    entrypoint = Path(__file__).resolve(strict=True)
    source_dir = entrypoint.parent
    root_text = _bootstrap_git(source_dir, "rev-parse", "--show-toplevel")
    control_repo = Path(root_text.decode("utf-8").strip()).resolve(strict=True)
    dependency = source_dir / "external_registry_materializer.py"
    resolved_dependency = dependency.resolve(strict=True)
    if resolved_dependency != dependency or resolved_dependency.parent != source_dir:
        raise PromotionError("publication_primitive_path_mismatch")
    try:
        relative = dependency.relative_to(control_repo).as_posix()
    except ValueError as exc:
        raise PromotionError("publication_primitive_outside_control_repo") from exc
    head = _bootstrap_git(control_repo, "rev-parse", "HEAD").decode("ascii").strip()
    if head != expected_commit:
        raise PromotionError(
            f"control_plane_commit_mismatch:publication_primitive:{expected_commit}:{head}"
        )
    head_raw = _bootstrap_git(control_repo, "show", f"{head}:{relative}")
    actual_sha256 = _sha256_bytes(head_raw)
    if actual_sha256 != expected_sha256:
        raise PromotionError("publication_primitive_head_sha256_mismatch")
    dependency_path, worktree_raw, dependency_identity = _read_stable_file(
        dependency,
        field="publication_primitive",
    )
    if worktree_raw != head_raw:
        raise PromotionError("publication_primitive_worktree_differs_from_head")

    # The publisher is executable code. Only the exact verified Git blob is loaded.
    module = types.ModuleType("_zolotyaylopata_bound_registry_publication")
    module.__file__ = str(dependency_path)
    module.__package__ = None
    try:
        exec(
            compile(head_raw, str(dependency_path), "exec", dont_inherit=True),
            module.__dict__,
        )
    except BaseException as exc:
        raise PromotionError(
            f"publication_primitive_module_load_failed:{type(exc).__name__}"
        ) from exc
    for attribute in (
        "MaterializationError",
        "RECEIPT_FILENAME",
        "_bind_control_plane_file",
        "_load_bound_validator",
        "_open_publication_root_guard",
        "_close_publication_root_guard",
        "_rename_directory_no_replace",
        "_assert_external_output_paths",
        "_output_parent_identity",
        "_snapshot_repository",
        "_assert_heads_unchanged",
        "_assert_control_plane_binding_unchanged",
        "_git_root",
        "_head_blob",
        "_build_registry_from_snapshots",
    ):
        if not hasattr(module, attribute):
            raise PromotionError(
                f"publication_primitive_attribute_missing:{attribute}"
            )
    _assert_stable_file(
        dependency_path,
        worktree_raw,
        dependency_identity,
        field="publication_primitive",
    )
    return module, {
        "path": str(dependency_path),
        "repo": str(control_repo),
        "git_commit": head,
        "head_sha256": actual_sha256,
        "head_raw": head_raw,
    }


def _bind_control_plane(
    *,
    expected_promoter_head_sha256: str,
    expected_validator_head_sha256: str,
    expected_publication_primitive_head_sha256: str,
    expected_coordinator_head_sha256: str,
    expected_installer_head_sha256: str,
    expected_control_plane_git_commit: str,
) -> tuple[dict[str, dict[str, Any]], Any, types.ModuleType]:
    entrypoint = Path(__file__).resolve(strict=False)
    source_dir = entrypoint.parent
    publication, primitive_binding = _load_bound_publication(
        expected_commit=expected_control_plane_git_commit,
        expected_sha256=expected_publication_primitive_head_sha256,
    )
    control_repo = publication._git_root(entrypoint)
    paths = {
        "promoter": entrypoint,
        "validator": source_dir / "canonical_strategy_runtime.py",
        "publication_primitive": source_dir / "external_registry_materializer.py",
        "coordinator": control_repo / "tools" / "invoke_listing_strategy_due_coordinator.ps1",
        "installer": control_repo / "tools" / "install_listing_strategy_due_coordinator_task.ps1",
    }
    expected_hashes = {
        "promoter": expected_promoter_head_sha256,
        "validator": expected_validator_head_sha256,
        "publication_primitive": expected_publication_primitive_head_sha256,
        "coordinator": expected_coordinator_head_sha256,
        "installer": expected_installer_head_sha256,
    }
    bindings: dict[str, dict[str, Any]] = {
        "publication_primitive": primitive_binding
    }
    for role, path in paths.items():
        bindings[role] = publication._bind_control_plane_file(
            path=path,
            expected_commit=expected_control_plane_git_commit,
            expected_sha256=expected_hashes[role],
            field=role,
        )
        if Path(bindings[role]["repo"]).resolve(strict=True) != control_repo:
            raise PromotionError(f"control_plane_cross_repository:{role}")
    validator = publication._load_bound_validator(bindings["validator"])
    for attribute in (
        "ACTIVE_SCHEMA",
        "ACTIVE_ACTIVATION_STATUS",
        "validate_registry",
        "_validate_timestamp",
    ):
        if not hasattr(validator, attribute):
            raise PromotionError(f"validator_active_attribute_missing:{attribute}")
    return bindings, validator, publication


def _validate_parent_receipt(
    *,
    receipt: dict[str, Any],
    parent_registry_path: Path,
    parent_receipt_path: Path,
    registry_raw_sha256: str,
    runtime_ids: set[str],
) -> None:
    exact = {
        "schema": "zolotyaylopata.external_registry_materialization_receipt.v2",
        "status": "MATERIALIZED_FAIL_CLOSED",
        "decision": "STAGED_FAIL_CLOSED",
        "launch_allowed": False,
    }
    for field, expected in exact.items():
        actual = receipt.get(field)
        if type(actual) is not type(expected) or actual != expected:
            raise PromotionError(f"parent_receipt_{field}_invalid")
    if receipt.get("registry_raw_sha256") != registry_raw_sha256:
        raise PromotionError("parent_receipt_registry_raw_sha256_mismatch")
    if Path(str(receipt.get("registry_path"))).resolve(strict=False) != parent_registry_path:
        raise PromotionError("parent_receipt_registry_path_mismatch")
    if Path(str(receipt.get("receipt_path"))).resolve(strict=False) != parent_receipt_path:
        raise PromotionError("parent_receipt_receipt_path_mismatch")
    publication_id = receipt.get("publication_id")
    if not isinstance(publication_id, str) or not _SHA256_RE.fullmatch(publication_id):
        raise PromotionError("parent_receipt_publication_id_invalid")
    if parent_registry_path.parent != parent_receipt_path.parent:
        raise PromotionError("parent_publication_pair_directory_mismatch")
    if parent_registry_path.parent.name != publication_id:
        raise PromotionError("parent_receipt_publication_directory_identity_mismatch")
    if (
        Path(str(receipt.get("publication_directory"))).resolve(strict=False)
        != parent_registry_path.parent
    ):
        raise PromotionError("parent_receipt_publication_directory_mismatch")

    validation = receipt.get("validation")
    if not isinstance(validation, dict):
        raise PromotionError("parent_receipt_validation_invalid")
    expected_validation = {
        "ok": True,
        "registry_valid": True,
        "all_runtime_bindings_valid": True,
        "decision": "STAGED_FAIL_CLOSED",
        "launch_allowed": False,
        "registry_raw_sha256": registry_raw_sha256,
    }
    for field, expected in expected_validation.items():
        actual = validation.get(field)
        if type(actual) is not type(expected) or actual != expected:
            raise PromotionError(f"parent_receipt_validation_{field}_invalid")
    receipt_runtime_rows = validation.get("runtimes")
    if receipt_runtime_rows is not None:
        if not isinstance(receipt_runtime_rows, list):
            raise PromotionError("parent_receipt_runtime_bindings_invalid")
        seen: set[str] = set()
        for row in receipt_runtime_rows:
            if not isinstance(row, dict) or row.get("binding_status") != "MATCH":
                raise PromotionError("parent_receipt_runtime_binding_not_match")
            strategy_id = row.get("strategy_id")
            if not isinstance(strategy_id, str) or strategy_id in seen:
                raise PromotionError("parent_receipt_runtime_binding_identity_invalid")
            seen.add(strategy_id)
        if seen != runtime_ids:
            raise PromotionError("parent_receipt_runtime_binding_set_mismatch")


def _validate_parent_lineage(
    *,
    receipt: dict[str, Any],
    parent_registry: dict[str, Any],
    bindings: dict[str, dict[str, Any]],
    publication_module: types.ModuleType,
    runtime_registry: types.ModuleType,
) -> None:
    expected_control_paths = {
        "materializer": Path(bindings["publication_primitive"]["path"]),
        "validator": Path(bindings["validator"]["path"]),
    }
    historical_blobs: dict[str, bytes] = {}
    for role in ("source", "materializer", "validator"):
        path_field = f"{role}_path"
        commit_field = f"{role}_git_commit"
        hash_field = f"{role}_head_sha256"
        path_text = receipt.get(path_field)
        commit = receipt.get(commit_field)
        expected_sha256 = receipt.get(hash_field)
        if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
            raise PromotionError(f"parent_lineage_{commit_field}_invalid")
        if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256):
            raise PromotionError(f"parent_lineage_{hash_field}_invalid")
        if (
            not isinstance(path_text, str)
            or not Path(path_text).is_absolute()
            or os.path.normpath(path_text) != path_text
        ):
            raise PromotionError(f"parent_lineage_{path_field}_invalid")
        path = Path(path_text).resolve(strict=False)
        if role in expected_control_paths and path != expected_control_paths[role]:
            raise PromotionError(f"parent_lineage_{role}_path_mismatch")
        try:
            repo = publication_module._git_root(path)
            historical_raw = publication_module._head_blob(
                repo,
                commit,
                path,
                field=f"parent_lineage:{role}",
            )
        except publication_module.MaterializationError as exc:
            raise PromotionError(
                f"parent_lineage_{role}_historical_blob_unavailable"
            ) from exc
        if _sha256_bytes(historical_raw) != expected_sha256:
            raise PromotionError(f"parent_lineage_{role}_sha256_mismatch")
        historical_blobs[role] = historical_raw
    if receipt["materializer_git_commit"] != receipt["validator_git_commit"]:
        raise PromotionError("parent_lineage_control_commit_mismatch")

    expected_repositories = {
        (runtime["canonical_repo"], runtime["canonical_git_commit"])
        for runtime in parent_registry["runtimes"]
    }
    declared = receipt.get("canonical_repositories")
    if not isinstance(declared, list):
        raise PromotionError("parent_canonical_repository_set_mismatch")
    declared_repositories: set[tuple[str, str]] = set()
    for row in declared:
        if (
            not isinstance(row, dict)
            or set(row) != {"canonical_repo", "canonical_git_commit"}
            or not isinstance(row["canonical_repo"], str)
            or not isinstance(row["canonical_git_commit"], str)
        ):
            raise PromotionError("parent_canonical_repository_set_mismatch")
        identity = (row["canonical_repo"], row["canonical_git_commit"])
        if identity in declared_repositories:
            raise PromotionError("parent_canonical_repository_set_mismatch")
        declared_repositories.add(identity)
    if declared_repositories != expected_repositories:
        raise PromotionError("parent_canonical_repository_set_mismatch")

    try:
        source_payload = runtime_registry._load_json_bytes(historical_blobs["source"])
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PromotionError("parent_lineage_source_json_invalid") from exc
    structural_reasons, _ = runtime_registry._validate_structure(source_payload)
    if structural_reasons:
        raise PromotionError(
            "parent_lineage_source_structure_invalid:" + ";".join(structural_reasons)
        )

    snapshots: dict[str, dict[str, str]] = {}
    for runtime in parent_registry["runtimes"]:
        repo_text = str(Path(runtime["canonical_repo"]).resolve(strict=True))
        snapshot = {
            "canonical_repo": repo_text,
            "canonical_git_commit": runtime["canonical_git_commit"],
            "canonical_remote_url": runtime["canonical_remote_url"],
        }
        if snapshots.setdefault(repo_text, snapshot) != snapshot:
            raise PromotionError("parent_lineage_runtime_snapshot_conflict")
    source_repositories = {
        str(Path(runtime["canonical_repo"]).resolve(strict=True))
        for runtime in source_payload["runtimes"]
    }
    if source_repositories != set(snapshots):
        raise PromotionError("parent_lineage_source_repository_set_mismatch")

    # Reconstruct with the already SHA-bound current helper and the parent's
    # exact Git snapshots. Historical code is evidence only, never executed.
    try:
        reconstructed = publication_module._build_registry_from_snapshots(
            source_payload, snapshots, runtime_registry
        )
    except publication_module.MaterializationError as exc:
        raise PromotionError(
            f"parent_lineage_source_reconstruction_failed:{exc}"
        ) from exc
    if (
        reconstructed != parent_registry
        or _sha256_bytes(_canonical_json_bytes(reconstructed))
        != receipt["registry_raw_sha256"]
    ):
        raise PromotionError("parent_lineage_source_registry_mismatch")

    publication_descriptor = {
        "schema": "zolotyaylopata.external_registry_publication_identity.v1",
        "source_git_commit": receipt["source_git_commit"],
        "source_head_sha256": receipt["source_head_sha256"],
        "control_plane_git_commit": receipt["materializer_git_commit"],
        "materializer_head_sha256": receipt["materializer_head_sha256"],
        "validator_head_sha256": receipt["validator_head_sha256"],
        "registry_raw_sha256": receipt["registry_raw_sha256"],
        "canonical_repositories": [
            {
                "canonical_repo": snapshot["canonical_repo"],
                "canonical_git_commit": snapshot["canonical_git_commit"],
            }
            for snapshot in sorted(
                snapshots.values(), key=lambda row: row["canonical_repo"].casefold()
            )
        ],
    }
    if _sha256_bytes(_canonical_json_bytes(publication_descriptor)) != receipt["publication_id"]:
        raise PromotionError("parent_lineage_publication_id_mismatch")


def _validate_active_registry(
    registry_raw: bytes,
    runtime_registry: Any,
) -> dict[str, Any]:
    temporary_directory = tempfile.TemporaryDirectory(
        prefix="active-registry-validation-"
    )
    try:
        path = Path(temporary_directory.name) / REGISTRY_FILENAME
        path.write_bytes(registry_raw)
        result = runtime_registry.validate_registry(
            path,
            expected_raw_sha256=_sha256_bytes(registry_raw),
        )
    finally:
        temporary_directory.cleanup()
    if (
        result.get("ok") is not True
        or result.get("registry_valid") is not True
        or result.get("decision") != "ACTIVE_ROUTABLE"
        or result.get("launch_allowed") is not True
    ):
        reasons = ";".join(str(reason) for reason in result.get("reasons", []))
        runtime_reasons = ";".join(
            str(reason)
            for row in result.get("runtimes", [])
            for reason in row.get("reasons", [])
        )
        detail = reasons or runtime_reasons or str(result.get("decision"))
        raise PromotionError(f"active_registry_validation_failed:{detail}")
    return result


def _snapshot_runtime_artifacts(
    active_registry: dict[str, Any],
) -> list[tuple[Path, bytes, tuple[str, int, int, int, int]]]:
    expected_by_path: dict[str, tuple[Path, str, str]] = {}
    for runtime in active_registry["runtimes"]:
        strategy_id = runtime["strategy_id"]
        rows = [
            (
                "plan",
                Path(runtime["canonical_plan_path"]),
                runtime["canonical_plan_file_sha256"],
            )
        ]
        if runtime["launcher_path"] is not None:
            rows.append(
                (
                    "launcher",
                    Path(runtime["launcher_path"]),
                    runtime["launcher_sha256"],
                )
            )
        rows.extend(
            (
                f"implementation:{binding['role']}",
                Path(binding["path"]),
                binding["sha256"],
            )
            for binding in runtime["implementation_bindings"]
        )
        for role, path, expected_sha256 in rows:
            resolved_text = str(path.resolve(strict=False))
            previous = expected_by_path.get(resolved_text)
            if previous is not None and previous[1] != expected_sha256:
                raise PromotionError(
                    f"runtime_artifact_binding_conflict:{resolved_text}"
                )
            expected_by_path[resolved_text] = (
                path,
                expected_sha256,
                f"{strategy_id}:{role}",
            )

    snapshots: list[tuple[Path, bytes, tuple[str, int, int, int, int]]] = []
    for path, expected_sha256, label in expected_by_path.values():
        resolved, raw, identity = _read_stable_file(
            path,
            field="runtime_artifact",
        )
        if _sha256_bytes(raw) != expected_sha256:
            raise PromotionError(f"runtime_artifact_sha256_mismatch:{label}")
        snapshots.append((resolved, raw, identity))
    return snapshots


def _promote_external_registry(
    *,
    parent_registry_path: str | Path,
    parent_receipt_path: str | Path,
    publication_root: str | Path,
    active_strategy_id: str,
    generated_at_utc: str,
    expected_parent_registry_raw_sha256: str,
    expected_parent_receipt_raw_sha256: str,
    expected_promoter_head_sha256: str,
    expected_validator_head_sha256: str,
    expected_publication_primitive_head_sha256: str,
    expected_coordinator_head_sha256: str,
    expected_installer_head_sha256: str,
    expected_control_plane_git_commit: str,
) -> dict[str, Any]:
    expected_hashes = (
        expected_parent_registry_raw_sha256,
        expected_parent_receipt_raw_sha256,
        expected_promoter_head_sha256,
        expected_validator_head_sha256,
        expected_publication_primitive_head_sha256,
        expected_coordinator_head_sha256,
        expected_installer_head_sha256,
    )
    if any(not _SHA256_RE.fullmatch(value) for value in expected_hashes):
        raise PromotionError("expected_sha256_invalid")
    if not _COMMIT_RE.fullmatch(expected_control_plane_git_commit):
        raise PromotionError("expected_control_plane_git_commit_invalid")
    if not isinstance(active_strategy_id, str) or not active_strategy_id:
        raise PromotionError("active_strategy_id_invalid")

    bindings, runtime_registry, publication = _bind_control_plane(
        expected_promoter_head_sha256=expected_promoter_head_sha256,
        expected_validator_head_sha256=expected_validator_head_sha256,
        expected_publication_primitive_head_sha256=(
            expected_publication_primitive_head_sha256
        ),
        expected_coordinator_head_sha256=expected_coordinator_head_sha256,
        expected_installer_head_sha256=expected_installer_head_sha256,
        expected_control_plane_git_commit=expected_control_plane_git_commit,
    )

    registry_path, parent_registry_raw, registry_identity = _read_stable_file(
        Path(parent_registry_path), field="parent_registry"
    )
    receipt_path, parent_receipt_raw, receipt_identity = _read_stable_file(
        Path(parent_receipt_path), field="parent_receipt"
    )
    if registry_path.name != REGISTRY_FILENAME:
        raise PromotionError("parent_registry_filename_invalid")
    if receipt_path.name != publication.RECEIPT_FILENAME:
        raise PromotionError("parent_receipt_filename_invalid")
    if _sha256_bytes(parent_registry_raw) != expected_parent_registry_raw_sha256:
        raise PromotionError("parent_registry_raw_sha256_mismatch")
    if _sha256_bytes(parent_receipt_raw) != expected_parent_receipt_raw_sha256:
        raise PromotionError("parent_receipt_raw_sha256_mismatch")

    try:
        parent_registry = runtime_registry._load_json_bytes(parent_registry_raw)
        parent_receipt = runtime_registry._load_json_bytes(parent_receipt_raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PromotionError("parent_publication_json_invalid") from exc
    if not isinstance(parent_registry, dict):
        raise PromotionError("parent_registry_not_object")
    if not isinstance(parent_receipt, dict):
        raise PromotionError("parent_receipt_not_object")
    runtimes = parent_registry.get("runtimes")
    if not isinstance(runtimes, list):
        raise PromotionError("parent_registry_runtimes_invalid")
    runtime_ids = {
        row.get("strategy_id")
        for row in runtimes
        if isinstance(row, dict) and isinstance(row.get("strategy_id"), str)
    }
    if len(runtime_ids) != len(runtimes):
        raise PromotionError("parent_registry_runtime_identity_invalid")
    _validate_parent_receipt(
        receipt=parent_receipt,
        parent_registry_path=registry_path,
        parent_receipt_path=receipt_path,
        registry_raw_sha256=expected_parent_registry_raw_sha256,
        runtime_ids=runtime_ids,
    )
    parent_validation = runtime_registry.validate_registry(
        registry_path,
        expected_raw_sha256=expected_parent_registry_raw_sha256,
    )
    if (
        parent_validation.get("ok") is not True
        or parent_validation.get("registry_valid") is not True
        or parent_validation.get("decision") != "STAGED_FAIL_CLOSED"
        or parent_validation.get("launch_allowed") is not False
    ):
        raise PromotionError(
            "parent_registry_validation_failed:"
            f"{parent_validation.get('decision')}"
        )
    validated_runtime_ids: set[str] = set()
    for row in parent_validation.get("runtimes", []):
        if row.get("binding_status") != "MATCH":
            raise PromotionError(
                f"parent_registry_binding_not_match:{row.get('strategy_id')}"
            )
        validated_runtime_ids.add(str(row.get("strategy_id")))
    if validated_runtime_ids != runtime_ids:
        raise PromotionError("parent_registry_validation_runtime_set_mismatch")
    _validate_parent_lineage(
        receipt=parent_receipt,
        parent_registry=parent_registry,
        bindings=bindings,
        publication_module=publication,
        runtime_registry=runtime_registry,
    )

    selected = next(
        (
            row
            for row in runtimes
            if isinstance(row, dict) and row.get("strategy_id") == active_strategy_id
        ),
        None,
    )
    if selected is None:
        raise PromotionError("active_strategy_not_found")
    if selected.get("runtime_status") == "RETIRED":
        raise PromotionError("active_strategy_retired")
    if selected.get("activation_readiness") != ACTIVE_READINESS:
        raise PromotionError("active_strategy_not_ready")
    if selected.get("public_data_only") is not True:
        raise PromotionError("active_strategy_not_public_data_only")
    if selected.get("live_trading_allowed") is not False:
        raise PromotionError("active_strategy_live_trading_forbidden")
    allowed_modes = selected.get("allowed_modes")
    if (
        not isinstance(allowed_modes, list)
        or not allowed_modes
        or any(mode not in ACTIVE_ALLOWED_MODES for mode in allowed_modes)
    ):
        raise PromotionError("active_strategy_allowed_modes_invalid")
    if selected.get("launcher_path") is None:
        raise PromotionError("active_strategy_launcher_missing")

    parent_generated = _parse_utc(
        str(parent_registry.get("generated_at_utc")),
        field="parent_generated_at_utc",
    )
    active_generated = _parse_utc(generated_at_utc, field="generated_at_utc")
    if active_generated < parent_generated:
        raise PromotionError("generated_at_utc_precedes_parent")

    state_path, state_raw, state_identity = _read_stable_file(
        Path(str(selected["state_path"])), field="active_state"
    )
    try:
        state_payload = runtime_registry._load_json_bytes(state_raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PromotionError("active_state_due_contract_invalid") from exc
    if (
        not isinstance(state_payload, dict)
        or not isinstance(state_payload.get("status"), str)
        or not state_payload["status"].strip()
        or not runtime_registry._validate_timestamp(
            state_payload.get("next_interval_at_utc")
        )
    ):
        raise PromotionError("active_state_due_contract_invalid")
    active_registry = copy.deepcopy(parent_registry)
    active_registry["schema"] = runtime_registry.ACTIVE_SCHEMA
    active_registry["registry_id"] = (
        f"{parent_registry['registry_id']}.active.{active_strategy_id}"
    )
    active_registry["generated_at_utc"] = generated_at_utc
    active_registry["activation_status"] = runtime_registry.ACTIVE_ACTIVATION_STATUS
    active_registry["active_strategy_id"] = active_strategy_id
    for runtime in active_registry["runtimes"]:
        if runtime["strategy_id"] == active_strategy_id:
            runtime["runtime_status"] = "ACTIVE"
            runtime["scheduler_routable"] = True
        else:
            if runtime["runtime_status"] != "RETIRED":
                runtime["runtime_status"] = "INACTIVE"
            runtime["scheduler_routable"] = False

    registry_raw = _canonical_json_bytes(active_registry)
    registry_raw_sha256 = _sha256_bytes(registry_raw)
    active_validation = _validate_active_registry(registry_raw, runtime_registry)
    runtime_artifact_snapshots = _snapshot_runtime_artifacts(active_registry)

    snapshots: dict[str, dict[str, str]] = {}
    for runtime in active_registry["runtimes"]:
        repo = Path(runtime["canonical_repo"]).resolve(strict=True)
        repo_text = str(repo)
        if repo_text not in snapshots:
            snapshots[repo_text] = publication._snapshot_repository(repo)
        snapshot = snapshots[repo_text]
        if snapshot["canonical_git_commit"] != runtime["canonical_git_commit"]:
            raise PromotionError(
                f"runtime_repository_commit_stale:{runtime['strategy_id']}"
            )
        if snapshot["canonical_remote_url"] != runtime["canonical_remote_url"]:
            raise PromotionError(
                f"runtime_repository_remote_stale:{runtime['strategy_id']}"
            )
    runtime_snapshots = dict(snapshots)
    control_repo = Path(bindings["promoter"]["repo"]).resolve(strict=True)
    control_repo_text = str(control_repo)
    snapshots.setdefault(
        control_repo_text,
        publication._snapshot_repository(control_repo),
    )

    publication_root_path = Path(publication_root).resolve(strict=True)
    if not publication_root_path.is_dir():
        raise PromotionError("publication_root_not_directory")
    try:
        publication_root_path.relative_to(registry_path.parent)
    except ValueError:
        pass
    else:
        raise PromotionError("active_publication_root_inside_parent_publication")
    publication_root_identity = publication._output_parent_identity(
        publication_root_path / "placeholder"
    )
    publication._assert_external_output_paths(
        publication_root_path / "candidate",
        publication_root_path / "receipt",
        snapshots,
    )

    control_bindings = [
        {
            "role": role,
            "path": binding["path"],
            "git_commit": binding["git_commit"],
            "head_sha256": binding["head_sha256"],
        }
        for role, binding in sorted(bindings.items())
    ]
    publication_descriptor = {
        "schema": "zolotyaylopata.external_registry_activation_identity.v1",
        "parent_registry_raw_sha256": expected_parent_registry_raw_sha256,
        "parent_receipt_raw_sha256": expected_parent_receipt_raw_sha256,
        "active_strategy_id": active_strategy_id,
        "registry_raw_sha256": registry_raw_sha256,
        "control_plane_git_commit": expected_control_plane_git_commit,
        "control_bindings": control_bindings,
    }
    publication_id = _sha256_bytes(_canonical_json_bytes(publication_descriptor))
    publication_directory = publication_root_path / publication_id
    output_registry = publication_directory / REGISTRY_FILENAME
    output_receipt = publication_directory / RECEIPT_FILENAME

    active_runtime = next(
        row
        for row in active_registry["runtimes"]
        if row["strategy_id"] == active_strategy_id
    )
    active_runtime_binding = {
        field: copy.deepcopy(active_runtime[field])
        for field in (
            "strategy_id",
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
            "state_path",
            "implementation_bindings",
        )
    }
    active_runtime_binding["state_raw_sha256"] = _sha256_bytes(state_raw)
    active_runtime_binding["state_status"] = state_payload["status"]
    active_runtime_binding["next_interval_at_utc"] = state_payload[
        "next_interval_at_utc"
    ]
    receipt_payload = {
        "schema": RECEIPT_SCHEMA,
        "status": "ACTIVATED_PUBLIC_RESEARCH_ONLY",
        "decision": "ACTIVE_ROUTABLE",
        "launch_allowed": True,
        "publication_id": publication_id,
        "publication_directory": str(publication_directory),
        "registry_path": str(output_registry),
        "receipt_path": str(output_receipt),
        "registry_raw_sha256": registry_raw_sha256,
        "active_strategy_id": active_strategy_id,
        "parent_lineage": {
            "publication_id": parent_receipt["publication_id"],
            "registry_path": str(registry_path),
            "registry_raw_sha256": expected_parent_registry_raw_sha256,
            "receipt_path": str(receipt_path),
            "receipt_raw_sha256": expected_parent_receipt_raw_sha256,
            "source_path": parent_receipt["source_path"],
            "source_git_commit": parent_receipt["source_git_commit"],
            "source_head_sha256": parent_receipt["source_head_sha256"],
            "materializer_path": parent_receipt["materializer_path"],
            "materializer_git_commit": parent_receipt["materializer_git_commit"],
            "materializer_head_sha256": parent_receipt["materializer_head_sha256"],
            "validator_path": parent_receipt["validator_path"],
            "validator_git_commit": parent_receipt["validator_git_commit"],
            "validator_head_sha256": parent_receipt["validator_head_sha256"],
        },
        "policy_evidence": {
            "source_decision": "STAGED_FAIL_CLOSED",
            "all_source_bindings_match": True,
            "active_runtime_count": 1,
            "routable_runtime_count": 1,
            "activation_readiness": active_runtime["activation_readiness"],
            "public_data_only": active_runtime["public_data_only"],
            "live_trading_allowed": active_runtime["live_trading_allowed"],
            "allowed_modes": copy.deepcopy(active_runtime["allowed_modes"]),
        },
        "active_runtime_binding": active_runtime_binding,
        "control_plane_git_commit": expected_control_plane_git_commit,
        "control_bindings": control_bindings,
        "canonical_repositories": [
            {
                "canonical_repo": snapshot["canonical_repo"],
                "canonical_git_commit": snapshot["canonical_git_commit"],
            }
            for snapshot in sorted(
                runtime_snapshots.values(),
                key=lambda row: row["canonical_repo"].casefold(),
            )
        ],
        "validation": active_validation,
    }
    receipt_raw = _canonical_json_bytes(receipt_payload)
    receipt_raw_sha256 = _sha256_bytes(receipt_raw)

    def pre_publish_guard() -> None:
        _assert_stable_file(
            registry_path,
            parent_registry_raw,
            registry_identity,
            field="parent_registry",
        )
        _assert_stable_file(
            receipt_path,
            parent_receipt_raw,
            receipt_identity,
            field="parent_receipt",
        )
        _assert_stable_file(
            state_path,
            state_raw,
            state_identity,
            field="active_state",
        )
        for artifact_path, artifact_raw, artifact_identity in runtime_artifact_snapshots:
            _assert_stable_file(
                artifact_path,
                artifact_raw,
                artifact_identity,
                field="runtime_artifact",
            )
        publication._assert_heads_unchanged(snapshots)
        for binding in bindings.values():
            publication._assert_control_plane_binding_unchanged(binding)

    pre_publish_guard()
    published_registry, published_receipt = _publish_active_pair(
        publication_module=publication,
        publication_root=publication_root_path,
        expected_root_identity=publication_root_identity,
        protected_snapshots=snapshots,
        publication_id=publication_id,
        registry_raw=registry_raw,
        receipt_raw=receipt_raw,
        pre_publish_guard=pre_publish_guard,
    )
    if published_registry.read_bytes() != registry_raw:
        raise PromotionError("published_registry_readback_mismatch")
    if published_receipt.read_bytes() != receipt_raw:
        raise PromotionError("published_receipt_readback_mismatch")
    return {
        "status": "ACTIVATED_PUBLIC_RESEARCH_ONLY",
        "decision": "ACTIVE_ROUTABLE",
        "launch_allowed": True,
        "execution_performed": False,
        "active_strategy_id": active_strategy_id,
        "publication_id": publication_id,
        "publication_directory": str(publication_directory),
        "registry_path": str(published_registry),
        "receipt_path": str(published_receipt),
        "registry_raw_sha256": registry_raw_sha256,
        "receipt_raw_sha256": receipt_raw_sha256,
        "parent_registry_raw_sha256": expected_parent_registry_raw_sha256,
        "parent_receipt_raw_sha256": expected_parent_receipt_raw_sha256,
        "validation": active_validation,
    }


def promote_external_registry(
    *,
    parent_registry_path: str | Path,
    parent_receipt_path: str | Path,
    publication_root: str | Path,
    active_strategy_id: str,
    generated_at_utc: str,
    expected_parent_registry_raw_sha256: str,
    expected_parent_receipt_raw_sha256: str,
    expected_promoter_head_sha256: str,
    expected_validator_head_sha256: str,
    expected_publication_primitive_head_sha256: str,
    expected_coordinator_head_sha256: str,
    expected_installer_head_sha256: str,
    expected_control_plane_git_commit: str,
) -> dict[str, Any]:
    try:
        return _promote_external_registry(
            parent_registry_path=parent_registry_path,
            parent_receipt_path=parent_receipt_path,
            publication_root=publication_root,
            active_strategy_id=active_strategy_id,
            generated_at_utc=generated_at_utc,
            expected_parent_registry_raw_sha256=(
                expected_parent_registry_raw_sha256
            ),
            expected_parent_receipt_raw_sha256=(
                expected_parent_receipt_raw_sha256
            ),
            expected_promoter_head_sha256=expected_promoter_head_sha256,
            expected_validator_head_sha256=expected_validator_head_sha256,
            expected_publication_primitive_head_sha256=(
                expected_publication_primitive_head_sha256
            ),
            expected_coordinator_head_sha256=expected_coordinator_head_sha256,
            expected_installer_head_sha256=expected_installer_head_sha256,
            expected_control_plane_git_commit=expected_control_plane_git_commit,
        )
    except PromotionError:
        raise
    except RuntimeError as exc:
        raise PromotionError(str(exc)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PromotionError(f"promotion_failed:{type(exc).__name__}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one immutable ACTIVE public-research registry; never launch it."
    )
    parser.add_argument("--promote", action="store_true", required=True)
    parser.add_argument("--parent-registry", required=True, type=Path)
    parser.add_argument("--parent-receipt", required=True, type=Path)
    parser.add_argument("--publication-root", required=True, type=Path)
    parser.add_argument("--active-strategy-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--expected-parent-registry-raw-sha256", required=True)
    parser.add_argument("--expected-parent-receipt-raw-sha256", required=True)
    parser.add_argument("--expected-promoter-head-sha256", required=True)
    parser.add_argument("--expected-validator-head-sha256", required=True)
    parser.add_argument("--expected-publication-primitive-head-sha256", required=True)
    parser.add_argument("--expected-coordinator-head-sha256", required=True)
    parser.add_argument("--expected-installer-head-sha256", required=True)
    parser.add_argument("--expected-control-plane-git-commit", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = promote_external_registry(
            parent_registry_path=args.parent_registry,
            parent_receipt_path=args.parent_receipt,
            publication_root=args.publication_root,
            active_strategy_id=args.active_strategy_id,
            generated_at_utc=args.generated_at_utc,
            expected_parent_registry_raw_sha256=(
                args.expected_parent_registry_raw_sha256
            ),
            expected_parent_receipt_raw_sha256=(
                args.expected_parent_receipt_raw_sha256
            ),
            expected_promoter_head_sha256=args.expected_promoter_head_sha256,
            expected_validator_head_sha256=args.expected_validator_head_sha256,
            expected_publication_primitive_head_sha256=(
                args.expected_publication_primitive_head_sha256
            ),
            expected_coordinator_head_sha256=args.expected_coordinator_head_sha256,
            expected_installer_head_sha256=args.expected_installer_head_sha256,
            expected_control_plane_git_commit=args.expected_control_plane_git_commit,
        )
        exit_code = 0
    except PromotionError as exc:
        result = {
            "status": "PROMOTION_BLOCKED",
            "decision": "PROMOTION_BLOCKED",
            "launch_allowed": False,
            "execution_performed": False,
            "reason": str(exc),
        }
        exit_code = 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{result['status']} launch_allowed={str(result['launch_allowed']).lower()} "
            "execution_performed=false"
        )
        for field in ("reason", "registry_path", "receipt_path"):
            if field in result:
                print(f"{field}={result[field]}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
