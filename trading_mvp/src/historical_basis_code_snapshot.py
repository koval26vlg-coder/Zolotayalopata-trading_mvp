from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "trading_mvp_historical_basis_code_snapshot_v1"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_files(source_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(source_root.rglob("*.py"), key=lambda item: item.relative_to(source_root).as_posix()):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rows.append(
            {
                "relative_path": path.relative_to(source_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not rows:
        raise ValueError(f"no Python source files found: {source_root}")
    return rows


def _verify_snapshot(snapshot_root: Path, expected_files: list[dict[str, Any]], bundle_hash: str) -> Path:
    if snapshot_root.name != bundle_hash or sha256_json(expected_files) != bundle_hash:
        raise ValueError("snapshot bundle hash mismatch")
    manifest_path = snapshot_root / "snapshot-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("snapshot manifest is missing")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA or payload.get("code_snapshot_hash") != bundle_hash:
        raise ValueError("snapshot manifest identity mismatch")
    if payload.get("files") != expected_files:
        raise ValueError("snapshot manifest file inventory mismatch")
    for row in expected_files:
        target = snapshot_root / Path(row["relative_path"])
        if not target.is_file() or target.stat().st_size != row["size_bytes"] or sha256_file(target) != row["sha256"]:
            raise ValueError(f"snapshot file hash mismatch: {row['relative_path']}")
    return manifest_path


def _make_read_only(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(stat.S_IREAD)


def create_basis_code_snapshot(
    source_dir: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    source_root = Path(source_dir).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"source directory does not exist: {source_root}")
    snapshot_parent = Path(output_root).expanduser().resolve()
    snapshot_parent.mkdir(parents=True, exist_ok=True)
    files = _source_files(source_root)
    bundle_hash = sha256_json(files)
    snapshot_root = snapshot_parent / bundle_hash
    cache_hit = snapshot_root.exists()
    if not cache_hit:
        temporary = Path(tempfile.mkdtemp(prefix=f".{bundle_hash}.", dir=snapshot_parent))
        try:
            for row in files:
                source = source_root / Path(row["relative_path"])
                destination = temporary / Path(row["relative_path"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            manifest = {
                "schema": SCHEMA,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_root": str(source_root),
                "code_snapshot_hash": bundle_hash,
                "files": files,
            }
            (temporary / "snapshot-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            try:
                os.replace(temporary, snapshot_root)
            except OSError:
                if not snapshot_root.exists():
                    raise
                shutil.rmtree(temporary, ignore_errors=True)
            _make_read_only(snapshot_root)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    manifest_path = _verify_snapshot(snapshot_root, files, bundle_hash)
    return {
        "schema": SCHEMA,
        "code_snapshot_hash": bundle_hash,
        "snapshot_path": str(snapshot_root),
        "manifest_path": str(manifest_path),
        "file_count": len(files),
        "cache_hit": cache_hit,
    }


def validate_basis_code_snapshot_reference(
    code_snapshot_hash: str | None,
    manifest_path: str | Path | None,
    *,
    fallback_code_path: str | Path,
) -> dict[str, Any]:
    if code_snapshot_hash is None and manifest_path is None:
        discovered_manifest = Path(fallback_code_path).expanduser().resolve().parent / "snapshot-manifest.json"
        if discovered_manifest.is_file():
            discovered = json.loads(discovered_manifest.read_text(encoding="utf-8"))
            return validate_basis_code_snapshot_reference(
                str(discovered.get("code_snapshot_hash") or ""),
                discovered_manifest,
                fallback_code_path=fallback_code_path,
            )
        return {
            "code_snapshot_hash": sha256_file(fallback_code_path),
            "code_snapshot_manifest": None,
            "immutable_snapshot": False,
        }
    if not code_snapshot_hash or not manifest_path:
        raise ValueError("code snapshot hash and manifest must be provided together")
    manifest_target = Path(manifest_path).expanduser().resolve()
    if not manifest_target.is_file():
        raise ValueError("code snapshot manifest is missing")
    payload = json.loads(manifest_target.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA or payload.get("code_snapshot_hash") != code_snapshot_hash:
        raise ValueError("code snapshot reference mismatch")
    files = payload.get("files")
    if not isinstance(files, list):
        raise ValueError("code snapshot file inventory is missing")
    _verify_snapshot(manifest_target.parent, files, code_snapshot_hash)
    return {
        "code_snapshot_hash": code_snapshot_hash,
        "code_snapshot_manifest": str(manifest_target),
        "immutable_snapshot": True,
    }


def require_plan_code_snapshot(plan: dict[str, Any], snapshot: dict[str, Any]) -> None:
    provenance = plan.get("code_provenance") or {}
    if not provenance.get("immutable_snapshot"):
        return
    if not snapshot.get("immutable_snapshot"):
        raise ValueError("frozen plan requires immutable code snapshot execution")
    validated = validate_basis_code_snapshot_reference(
        snapshot.get("code_snapshot_hash"),
        snapshot.get("code_snapshot_manifest"),
        fallback_code_path=provenance.get("module_path") or __file__,
    )
    if provenance.get("code_snapshot_hash") != validated.get("code_snapshot_hash"):
        raise ValueError("runtime code snapshot does not match frozen plan")


def require_plan_runtime_code_snapshot(
    plan: dict[str, Any],
    *,
    runtime_code_path: str | Path,
) -> dict[str, Any]:
    runtime_snapshot = validate_basis_code_snapshot_reference(
        None,
        None,
        fallback_code_path=runtime_code_path,
    )
    require_plan_code_snapshot(plan, runtime_snapshot)
    return runtime_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a content-addressed read-only basis code snapshot")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = create_basis_code_snapshot(args.source_dir, args.output_root)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
