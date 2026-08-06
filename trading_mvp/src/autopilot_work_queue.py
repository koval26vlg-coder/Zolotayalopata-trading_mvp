from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from autopilot_guard import resolve_productive_fallback


SUPPORTED_RUNNERS = {
    "code_baseline_manifest",
    "evidence_manifest",
    "git_worktree_inventory",
    "python_unittest",
    "python_unittest_discover",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object: {path}:{line_number}")
        rows.append(value)
    return rows


def _append_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _collect_baseline_files(repo_root: Path, task: dict[str, Any]) -> list[Path]:
    includes = task.get("include")
    if not isinstance(includes, list) or not includes:
        raise ValueError("code_baseline_manifest requires a non-empty include list")
    excludes = {
        str(value).replace("\\", "/")
        for value in (task.get("exclude") or [])
    }
    selected: dict[str, Path] = {}
    for pattern_value in includes:
        pattern = str(pattern_value)
        for candidate in repo_root.glob(pattern):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(repo_root).as_posix()
            if any(candidate.match(exclude) or relative.startswith(exclude) for exclude in excludes):
                continue
            selected[relative] = candidate
    return [selected[key] for key in sorted(selected)]


def _classify_worktree_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith(
        (
            "exports/",
            ".test-tmp/",
            ".tmp-tests/",
            "trading_mvp/.tmp-tests/",
        )
    ) or normalized.endswith((".jsonl", ".log", ".csv", ".txt")):
        return "data_artifact"
    if normalized.startswith(
        (
            "trading_mvp/src/",
            "trading_mvp/tests/",
            "tools/",
        )
    ) or normalized in {"AGENTS.md", "trading_mvp/run_mvp.ps1"}:
        return "code"
    return "control_or_documentation"


def parse_git_status_lines(lines: Iterable[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_line in lines:
        line = str(raw_line).rstrip("\r\n")
        if not line:
            continue
        if len(line) < 4 or line[2] != " ":
            raise ValueError(f"invalid git porcelain v1 row: {line!r}")
        status = line[:2]
        path = line[3:]
        rows.append(
            {
                "status": status,
                "path": path,
                "scope": _classify_worktree_path(path),
            }
        )
    return rows


def _run_code_baseline_manifest(
    task: dict[str, Any],
    *,
    repo_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    files = _collect_baseline_files(repo_root, task)
    if not files:
        raise ValueError("code baseline include patterns selected no files")
    inventory = [
        {
            "path": path.relative_to(repo_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in files
    ]
    content_hash = _sha256_json(inventory)
    manifest = {
        "schema": "trading_mvp_code_only_baseline_v1",
        "task_id": task["id"],
        "generated_at_utc": _utc_now(),
        "repo_root": str(repo_root),
        "file_count": len(inventory),
        "content_hash": content_hash,
        "files": inventory,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"code-baseline-{content_hash[:16]}.json"
    if not manifest_path.exists():
        temporary = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, manifest_path)
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "file_count": len(inventory),
        "content_hash": content_hash,
    }


def _resolve_git() -> str:
    candidates = [
        shutil.which("git"),
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FileNotFoundError("git executable is unavailable")


def _run_git_worktree_inventory(
    task: dict[str, Any],
    *,
    repo_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            _resolve_git(),
            "-c",
            "core.quotepath=false",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=int(task["max_runtime_sec"]),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git status failed with exit code {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    rows = parse_git_status_lines(completed.stdout.splitlines())
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["scope"]] = counts.get(row["scope"], 0) + 1
    content_hash = _sha256_json(rows)
    payload = {
        "schema": "trading_mvp_git_worktree_inventory_v1",
        "task_id": task["id"],
        "generated_at_utc": _utc_now(),
        "repo_root": str(repo_root),
        "entry_count": len(rows),
        "counts_by_scope": counts,
        "content_hash": content_hash,
        "entries": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"git-worktree-{content_hash[:16]}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "manifest_path": str(path),
        "manifest_sha256": _sha256_file(path),
        "entry_count": len(rows),
        "counts_by_scope": counts,
        "content_hash": content_hash,
    }


def _run_evidence_manifest(
    task: dict[str, Any],
    *,
    repo_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    raw_inputs = task.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("evidence_manifest requires a non-empty inputs list")
    rows: list[dict[str, Any]] = []
    for raw_path in raw_inputs:
        source = Path(str(raw_path)).expanduser()
        if not source.is_absolute():
            source = repo_root / source
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(f"evidence input is missing: {source}")
        rows.append(
            {
                "path": str(source),
                "bytes": source.stat().st_size,
                "sha256": _sha256_file(source),
            }
        )
    rows.sort(key=lambda row: row["path"].lower())
    content_hash = _sha256_json(rows)
    payload = {
        "schema": "trading_mvp_terminal_evidence_manifest_v1",
        "task_id": task["id"],
        "generated_at_utc": _utc_now(),
        "input_count": len(rows),
        "content_hash": content_hash,
        "inputs": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"terminal-evidence-{content_hash[:16]}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "manifest_path": str(path),
        "manifest_sha256": _sha256_file(path),
        "input_count": len(rows),
        "content_hash": content_hash,
    }


def _run_python(
    task: dict[str, Any],
    *,
    repo_root: Path,
    output_dir: Path,
    discover: bool,
) -> dict[str, Any]:
    if discover:
        start_dir = str(task.get("start_dir") or "trading_mvp/tests")
        command = [sys.executable, "-m", "unittest", "discover", "-s", start_dir]
    else:
        modules = task.get("modules")
        if not isinstance(modules, list) or not modules:
            raise ValueError("python_unittest requires a non-empty modules list")
        command = [sys.executable, "-m", "unittest", *map(str, modules)]
    timeout = int(task["max_runtime_sec"])
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    runtime_sec = round(time.monotonic() - started, 3)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{task['id']}-{int(time.time())}"
    stdout_path = output_dir / f"{stem}.stdout.log"
    stderr_path = output_dir / f"{stem}.stderr.log"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result = {
        "command": command,
        "exit_code": completed.returncode,
        "runtime_sec": runtime_sec,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_sha256": _sha256_file(stdout_path),
        "stderr_sha256": _sha256_file(stderr_path),
    }
    if completed.returncode != 0:
        raise RuntimeError(
            f"fallback test task failed with exit code {completed.returncode}; "
            f"stderr={stderr_path}"
        )
    return result


def run_task(
    task: dict[str, Any],
    *,
    repo_root: str | Path,
    output_dir: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    ledger = Path(ledger_path).expanduser().resolve()
    task_id = str(task.get("id") or "").strip()
    runner = str(task.get("runner") or "").strip()
    if not task_id:
        raise ValueError("fallback task id is required")
    if runner not in SUPPORTED_RUNNERS:
        raise ValueError(f"unsupported fallback runner: {runner}")
    max_runtime_sec = int(task.get("max_runtime_sec") or 0)
    if max_runtime_sec <= 0 or max_runtime_sec > 1_800:
        raise ValueError("fallback max_runtime_sec must be in [1, 1800]")

    existing = _read_ledger(ledger)
    events = [row for row in existing if str(row.get("task_id") or "") == task_id]
    if any(str(row.get("status") or "") == "COMPLETED" for row in events):
        raise ValueError(f"fallback task already completed: {task_id}")
    attempts = sum(str(row.get("status") or "") == "STARTED" for row in events)
    max_attempts = int(task.get("max_attempts") or 1)
    if attempts >= max_attempts:
        raise ValueError(f"fallback task exhausted attempts: {task_id}")

    lock_path = ledger.with_suffix(f"{ledger.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"fallback queue is already owned: {lock_path}") from exc
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        task_hash = _sha256_json(task)
        started_at = _utc_now()
        _append_ledger(
            ledger,
            {
                "schema": "trading_mvp_productive_fallback_event_v1",
                "task_id": task_id,
                "task_hash": task_hash,
                "status": "STARTED",
                "attempt": attempts + 1,
                "pid": os.getpid(),
                "started_at_utc": started_at,
            },
        )
        try:
            if runner == "code_baseline_manifest":
                result = _run_code_baseline_manifest(
                    task,
                    repo_root=root,
                    output_dir=output,
                )
            elif runner == "git_worktree_inventory":
                result = _run_git_worktree_inventory(
                    task,
                    repo_root=root,
                    output_dir=output,
                )
            elif runner == "evidence_manifest":
                result = _run_evidence_manifest(
                    task,
                    repo_root=root,
                    output_dir=output,
                )
            elif runner == "python_unittest":
                result = _run_python(
                    task,
                    repo_root=root,
                    output_dir=output,
                    discover=False,
                )
            else:
                result = _run_python(
                    task,
                    repo_root=root,
                    output_dir=output,
                    discover=True,
                )
        except Exception as exc:
            _append_ledger(
                ledger,
                {
                    "schema": "trading_mvp_productive_fallback_event_v1",
                    "task_id": task_id,
                    "task_hash": task_hash,
                    "status": "FAILED",
                    "attempt": attempts + 1,
                    "finished_at_utc": _utc_now(),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise
        event = {
            "schema": "trading_mvp_productive_fallback_event_v1",
            "task_id": task_id,
            "task_hash": task_hash,
            "status": "COMPLETED",
            "attempt": attempts + 1,
            "finished_at_utc": _utc_now(),
            "result": result,
        }
        _append_ledger(ledger, event)
        return event
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        lock_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute one allowlisted trading_mvp productive fallback task."
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--task-id")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = _read_json(args.policy)
    queue = policy.get("productive_fallback_queue")
    if not isinstance(queue, dict):
        raise ValueError("productive_fallback_queue is not configured")
    ledger = Path(str(queue.get("ledger_path") or "")).expanduser().resolve()
    output = Path(str(queue.get("output_dir") or "")).expanduser().resolve()
    if not str(queue.get("ledger_path") or "") or not str(queue.get("output_dir") or ""):
        raise ValueError("productive fallback ledger_path and output_dir are required")
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("productive_fallback_queue.tasks must be a list")
    task: dict[str, Any] | None = None
    if args.task_id:
        task = next(
            (
                dict(value)
                for value in tasks
                if isinstance(value, dict) and value.get("id") == args.task_id
            ),
            None,
        )
        if task is None:
            raise ValueError(f"unknown productive fallback task: {args.task_id}")
    else:
        selected = resolve_productive_fallback(
            policy,
            ledger_entries=_read_ledger(ledger),
        )
        if selected.get("status") != "READY":
            print(json.dumps(selected, ensure_ascii=False, indent=2))
            return 0
        task = dict(selected["task"])
    result = run_task(
        task,
        repo_root=args.repo_root,
        output_dir=output,
        ledger_path=ledger,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
