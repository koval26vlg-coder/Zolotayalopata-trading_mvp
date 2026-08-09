from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


MANIFEST_SCHEMA = "trading_mvp_paper_code_provenance_merkle_v1"
MANIFEST_SCHEMA_V2 = "trading_mvp_paper_code_provenance_merkle_v2"
MANIFEST_SCHEMA_V3 = "trading_mvp_paper_code_provenance_merkle_v3"
MANIFEST_SCHEMA_V4 = "trading_mvp_paper_code_provenance_merkle_v4"
MANIFEST_SCHEMA_V5 = "trading_mvp_paper_code_provenance_merkle_v5"
MANIFEST_SCHEMA_V6 = "trading_mvp_paper_code_provenance_merkle_v6"
MANIFEST_SCHEMA_V7 = "trading_mvp_paper_code_provenance_merkle_v7"
DEFAULT_MANIFEST_VERSION = "v1"
ALLOWED_SUFFIXES = {".md", ".ps1", ".py"}
ROOT_FILES = ("AGENTS.md", "trading_mvp/run_mvp.ps1")
EXPLICIT_SRC_FILES = {
    "basis_paper_oms.py",
    "costs.py",
    "historical_basis_v2_execution_probe.py",
    "historical_basis_v2_paper_oms.py",
    "pit_train_progress_monitor.py",
}
EXPLICIT_TEST_FILES = {
    "test_basis_paper_oms.py",
    "test_historical_basis_v2_execution_probe.py",
    "test_historical_basis_v2_paper_oms.py",
    "test_pit_train_progress_monitor.py",
}
EXPLICIT_TOOL_FILES = {
    "check_pit_train_progress.ps1",
    "monitor_paper_observer_fixture_visible.ps1",
    "run_trading_mvp_fast_regression.ps1",
}
EXPLICIT_TOOL_FILES_V2 = EXPLICIT_TOOL_FILES | {
    "check_trading_mvp_autopilot.ps1",
    "derive_trading_mvp_research_catalog.ps1",
    "run_trading_mvp_productive_fallback.ps1",
    "trading_mvp_research_backlog.ps1",
}
PROVENANCE_CONTRACTS: dict[str, dict[str, Any]] = {
    "v1": {
        "schema": MANIFEST_SCHEMA,
        "task_id": "paper_code_provenance_merkle_v1",
        "src_prefixes": ("paper_",),
        "test_prefixes": ("test_paper_",),
        "tool_prefixes": ("paper_",),
        "tool_explicit": EXPLICIT_TOOL_FILES,
        "next_allowed_action": "paper_forward_failure_runbook_v1",
    },
    "v2": {
        "schema": MANIFEST_SCHEMA_V2,
        "task_id": "paper_code_provenance_merkle_v2",
        "src_prefixes": ("paper_", "autopilot_"),
        "test_prefixes": ("test_paper_", "test_autopilot_"),
        "tool_prefixes": ("paper_",),
        "tool_explicit": EXPLICIT_TOOL_FILES_V2,
        "next_allowed_action": "paper_public_retry_rate_limit_fixture_v1",
    },
    "v3": {
        "schema": MANIFEST_SCHEMA_V3,
        "task_id": "paper_code_provenance_merkle_v3",
        "src_prefixes": ("paper_", "autopilot_"),
        "test_prefixes": ("test_paper_", "test_autopilot_"),
        "tool_prefixes": ("paper_",),
        "tool_explicit": EXPLICIT_TOOL_FILES_V2,
        "next_allowed_action": "paper_public_reader_transport_wiring_fixture_v1",
    },
    "v4": {
        "schema": MANIFEST_SCHEMA_V4,
        "task_id": "paper_code_provenance_merkle_v4",
        "src_prefixes": ("paper_", "autopilot_"),
        "test_prefixes": ("test_paper_", "test_autopilot_"),
        "tool_prefixes": ("paper_",),
        "tool_explicit": EXPLICIT_TOOL_FILES_V2,
        "next_allowed_action": "paper_public_system_clock_fixture_v1",
    },
    "v5": {
        "schema": MANIFEST_SCHEMA_V5,
        "task_id": "paper_code_provenance_merkle_v5",
        "src_prefixes": ("paper_", "autopilot_"),
        "test_prefixes": ("test_paper_", "test_autopilot_"),
        "tool_prefixes": ("paper_",),
        "tool_explicit": EXPLICIT_TOOL_FILES_V2,
        "next_allowed_action": (
            "paper_public_runtime_reader_factory_fixture_v1"
        ),
    },
    "v6": {
        "schema": MANIFEST_SCHEMA_V6,
        "task_id": "paper_code_provenance_merkle_v6",
        "src_prefixes": ("paper_", "autopilot_"),
        "test_prefixes": ("test_paper_", "test_autopilot_"),
        "tool_prefixes": ("paper_",),
        "tool_explicit": EXPLICIT_TOOL_FILES_V2,
        "next_allowed_action": (
            "paper_public_probe_evidence_observer_binding_fixture_v1"
        ),
    },
    "v7": {
        "schema": MANIFEST_SCHEMA_V7,
        "task_id": "paper_code_provenance_merkle_v7",
        "src_prefixes": ("paper_", "autopilot_"),
        "test_prefixes": ("test_paper_", "test_autopilot_"),
        "tool_prefixes": ("paper_",),
        "tool_explicit": EXPLICIT_TOOL_FILES_V2,
        "next_allowed_action": "paper_product_readiness_audit_v10",
    },
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contract(manifest_version: str) -> Mapping[str, Any]:
    try:
        return PROVENANCE_CONTRACTS[manifest_version]
    except KeyError as exc:
        raise ValueError(
            f"unsupported provenance manifest version: {manifest_version}"
        ) from exc


def _selection_contract_payload(manifest_version: str) -> dict[str, Any]:
    contract = _contract(manifest_version)
    payload: dict[str, Any] = {
        "root_files": list(ROOT_FILES),
        "src_prefix": "paper_",
        "src_explicit": sorted(EXPLICIT_SRC_FILES),
        "test_prefix": "test_paper_",
        "test_explicit": sorted(EXPLICIT_TEST_FILES),
        "tool_explicit": sorted(contract["tool_explicit"]),
        "allowed_suffixes": sorted(ALLOWED_SUFFIXES),
        "symlinks_forbidden": True,
    }
    if manifest_version != "v1":
        payload.update(
            {
                "src_prefixes": list(contract["src_prefixes"]),
                "test_prefixes": list(contract["test_prefixes"]),
                "tool_prefixes": list(contract["tool_prefixes"]),
                "selection_contract_version": int(manifest_version[1:]),
            }
        )
    return payload


def _manifest_version(manifest: Mapping[str, Any]) -> str:
    schema = manifest.get("schema")
    task_id = manifest.get("task_id")
    for version, contract in PROVENANCE_CONTRACTS.items():
        if schema == contract["schema"]:
            if task_id != contract["task_id"]:
                raise ValueError(
                    "code provenance schema/task contract mismatch"
                )
            return version
    raise ValueError(f"unsupported code provenance schema: {schema}")


def _is_selected(relative: Path, manifest_version: str) -> bool:
    contract = _contract(manifest_version)
    text = relative.as_posix()
    if text in ROOT_FILES:
        return True
    if relative.parent.as_posix() == "trading_mvp/src":
        return (
            relative.name.startswith(tuple(contract["src_prefixes"]))
            or relative.name in EXPLICIT_SRC_FILES
        )
    if relative.parent.as_posix() == "trading_mvp/tests":
        return (
            relative.name.startswith(tuple(contract["test_prefixes"]))
            or relative.name in EXPLICIT_TEST_FILES
        )
    if relative.parent.as_posix() == "tools":
        return (
            relative.name.startswith(tuple(contract["tool_prefixes"]))
            or relative.name in contract["tool_explicit"]
        )
    return False


def discover_code_files(
    repo_root: str | Path,
    *,
    manifest_version: str = DEFAULT_MANIFEST_VERSION,
) -> list[Path]:
    _contract(manifest_version)
    root = Path(repo_root).expanduser().resolve()
    candidates: set[Path] = set()
    for relative in ROOT_FILES:
        candidate = root / relative
        if candidate.is_file():
            candidates.add(candidate)
    for directory in (
        root / "trading_mvp" / "src",
        root / "trading_mvp" / "tests",
        root / "tools",
    ):
        if not directory.is_dir():
            continue
        for candidate in directory.iterdir():
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root)
            if _is_selected(relative, manifest_version):
                candidates.add(candidate)
    resolved: list[Path] = []
    for candidate in candidates:
        if candidate.is_symlink():
            raise ValueError(f"code provenance rejects symlink: {candidate}")
        if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(f"non-code artifact selected: {candidate}")
        resolved.append(candidate.resolve())
    return sorted(
        resolved,
        key=lambda value: value.relative_to(root).as_posix().casefold(),
    )


def _leaf_hash(relative_path: str, file_sha256: str) -> str:
    return hashlib.sha256(
        b"leaf\0"
        + relative_path.encode("utf-8")
        + b"\0"
        + file_sha256.encode("ascii")
    ).hexdigest()


def merkle_root(leaves: Iterable[str]) -> str:
    level = list(leaves)
    if not level:
        return hashlib.sha256(b"empty").hexdigest()
    while len(level) > 1:
        next_level: list[str] = []
        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1] if index + 1 < len(level) else left
            next_level.append(
                hashlib.sha256(
                    b"node\0"
                    + left.encode("ascii")
                    + b"\0"
                    + right.encode("ascii")
                ).hexdigest()
            )
        level = next_level
    return level[0]


def build_code_manifest(
    *,
    repo_root: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
    manifest_version: str = DEFAULT_MANIFEST_VERSION,
) -> dict[str, Any]:
    contract = _contract(manifest_version)
    root = Path(repo_root).expanduser().resolve()
    files = discover_code_files(
        root,
        manifest_version=manifest_version,
    )
    entries: list[dict[str, Any]] = []
    leaves: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest = sha256_file(path)
        leaf = _leaf_hash(relative, digest)
        entries.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": digest,
                "leaf_sha256": leaf,
            }
        )
        leaves.append(leaf)
    deterministic = {
        "schema": contract["schema"],
        "task_id": contract["task_id"],
        "manifest_version": manifest_version,
        "selection_contract": _selection_contract_payload(manifest_version),
        "files": entries,
        "file_count": len(entries),
        "total_bytes": sum(int(item["bytes"]) for item in entries),
        "merkle_algorithm": "sha256_binary_tree_duplicate_odd_leaf_v1",
        "merkle_root_sha256": merkle_root(leaves),
        "manifest_content_sha256": sha256_json(entries),
        "operations": {
            "git_stage": False,
            "git_revert": False,
            "git_commit": False,
            "file_copy": False,
            "data_artifacts_read": False,
        },
        "private_api_keys": False,
        "live_orders": False,
        "verdict": "CODE_ONLY_MERKLE_BASELINE_FROZEN",
        "next_allowed_action": contract["next_allowed_action"],
    }
    manifest = {
        **deterministic,
        "repo_root": str(root),
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, manifest)
    return manifest


def validate_code_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> dict[str, Any]:
    manifest_version = _manifest_version(manifest)
    root = Path(repo_root).expanduser().resolve()
    if manifest.get("manifest_version", "v1") != manifest_version:
        raise ValueError("code provenance manifest version mismatch")
    expected_selection = _selection_contract_payload(manifest_version)
    if manifest.get("selection_contract") != expected_selection:
        raise ValueError("code provenance selection contract mismatch")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("code provenance file list is empty")
    expected_paths = [
        path.relative_to(root).as_posix()
        for path in discover_code_files(
            root,
            manifest_version=manifest_version,
        )
    ]
    observed_paths = [str(item.get("path") or "") for item in entries]
    if observed_paths != expected_paths:
        raise ValueError("code provenance selected file set drifted")
    leaves: list[str] = []
    for item in entries:
        path = (root / str(item["path"])).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("code provenance path escapes repository") from exc
        digest = sha256_file(path)
        if digest != item.get("sha256"):
            raise ValueError(f"code provenance file hash drifted: {item['path']}")
        if path.stat().st_size != int(item.get("bytes", -1)):
            raise ValueError(f"code provenance file size drifted: {item['path']}")
        leaf = _leaf_hash(str(item["path"]), digest)
        if leaf != item.get("leaf_sha256"):
            raise ValueError(f"code provenance leaf hash mismatch: {item['path']}")
        leaves.append(leaf)
    if int(manifest.get("file_count", -1)) != len(entries):
        raise ValueError("code provenance file count mismatch")
    if int(manifest.get("total_bytes", -1)) != sum(
        int(item["bytes"]) for item in entries
    ):
        raise ValueError("code provenance total bytes mismatch")
    if sha256_json(entries) != manifest.get("manifest_content_sha256"):
        raise ValueError("code provenance manifest content hash mismatch")
    if merkle_root(leaves) != manifest.get("merkle_root_sha256"):
        raise ValueError("code provenance Merkle root mismatch")
    deterministic = {
        key: value
        for key, value in manifest.items()
        if key not in {"repo_root", "deterministic_result_hash", "generated_at_utc"}
    }
    if sha256_json(deterministic) != manifest.get(
        "deterministic_result_hash"
    ):
        raise ValueError("code provenance deterministic hash mismatch")
    return dict(manifest)


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build deterministic paper code-only Merkle provenance"
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--manifest-version",
        choices=sorted(PROVENANCE_CONTRACTS),
        default=DEFAULT_MANIFEST_VERSION,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    manifest = build_code_manifest(
        repo_root=args.repo_root,
        output_path=args.output,
        manifest_version=args.manifest_version,
    )
    validate_code_manifest(manifest, repo_root=args.repo_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
