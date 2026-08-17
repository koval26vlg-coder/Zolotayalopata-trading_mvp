from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def canonical_plan_hash(document: Mapping[str, Any]) -> str:
    """Hash plan semantics without volatile generation/output bookkeeping."""
    volatile_keys = {
        "generated_at",
        "output_path",
        "plan_hash",
        "plan_file_sha256",
        "gate_updated",
    }
    stable = {
        key: value for key, value in document.items() if key not in volatile_keys
    }
    return canonical_json_hash(stable)


def _state_row(row: Mapping[str, Any]) -> dict[str, Any]:
    # Hash only normalized market state, not volatile collector bookkeeping.
    keys = (
        "exchange",
        "symbol",
        "base",
        "quote",
        "granularity",
        "candle_ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "data_status",
    )
    return {key: row.get(key) for key in keys}


def state_hash_from_rows(rows: list[Mapping[str, Any]]) -> str:
    normalized = [_state_row(row) for row in rows]
    normalized.sort(
        key=lambda row: (
            str(row.get("exchange") or ""),
            str(row.get("symbol") or ""),
            str(row.get("granularity") or ""),
            int(row.get("candle_ts") or 0),
        )
    )
    return canonical_json_hash(normalized)


def build_input_binding(
    paths: Mapping[str, Path],
    *,
    state_hash: str | None = None,
    plan_hash: str | None = None,
) -> dict[str, Any]:
    files: dict[str, dict[str, str]] = {}
    for label, path in sorted(paths.items()):
        files[label] = {
            "path": str(path),
            "sha256": sha256_file(path),
        }
    binding: dict[str, Any] = {"files": files}
    if state_hash:
        binding["state_hash"] = state_hash
    if plan_hash:
        binding["plan_hash"] = plan_hash
    return binding


def compare_input_binding(
    binding: Mapping[str, Any],
    paths: Mapping[str, Path],
) -> list[str]:
    mismatches: list[str] = []
    expected_files = binding.get("files")
    if not isinstance(expected_files, Mapping):
        return mismatches
    for label, path in sorted(paths.items()):
        expected = expected_files.get(label)
        if not isinstance(expected, Mapping):
            continue
        expected_sha = str(expected.get("sha256") or "")
        if expected_sha and expected_sha != sha256_file(path):
            mismatches.append(label)
    return mismatches
