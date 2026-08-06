from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence


SCHEMA = "trading_mvp_historical_basis_v2_cache_audit_v1"
MAX_RUNTIME_SEC = 300


def _load_collector(code_snapshot_dir: str | Path) -> ModuleType:
    source_root = Path(code_snapshot_dir).expanduser().resolve()
    collector_path = source_root / "historical_basis_v2_collector.py"
    if not collector_path.is_file():
        raise ValueError(f"historical basis v2 collector is missing: {collector_path}")
    source_text = str(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    module = importlib.import_module("historical_basis_v2_collector")
    loaded_path = Path(module.__file__ or "").resolve()
    if loaded_path != collector_path:
        raise ValueError(
            f"collector module path mismatch: expected {collector_path}, loaded {loaded_path}"
        )
    return module


def _atomic_write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite cache audit: {path}")
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def audit_historical_basis_v2_cache(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_root: str | Path,
    report_output: str | Path,
    code_snapshot_dir: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    if max_runtime_sec < 1 or max_runtime_sec > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    started = time.monotonic()
    deadline = started + max_runtime_sec
    plan_target = Path(plan_path).expanduser().resolve()
    output_target = Path(output_root).expanduser().resolve()
    report_target = Path(report_output).expanduser().resolve()
    collector = _load_collector(code_snapshot_dir)

    plan = json.loads(plan_target.read_text(encoding="utf-8"))
    contract = collector.resolve_historical_basis_v2_plan_data_contract(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    snapshot = collector.validate_basis_code_snapshot_reference(
        None,
        None,
        fallback_code_path=Path(code_snapshot_dir) / "historical_basis_v2_collector.py",
    )
    collector.require_plan_code_snapshot(plan, snapshot)
    funding_references = collector._funding_references(contract["candidates"])

    cache_root = output_target / "cache"
    items: list[dict[str, Any]] = []
    market_rows_read = False
    for candidate in contract["candidates"]:
        for venue in collector.VENUES:
            symbol = str(candidate[f"{venue}_symbol"])
            for series in collector.SERIES:
                if time.monotonic() > deadline:
                    raise TimeoutError("basis-v2 cache audit exceeded max_runtime_sec")
                path = collector._cache_path(
                    cache_root,
                    venue,
                    symbol,
                    series,
                    int(contract["start_sec"]),
                    int(contract["end_sec"]),
                ).resolve()
                exists = path.is_file() and path.stat().st_size > 0
                payload = None
                if exists:
                    market_rows_read = True
                    payload = collector._read_valid_cache(
                        path,
                        venue=venue,
                        symbol=symbol,
                        series=series,
                        start_sec=int(contract["start_sec"]),
                        end_sec=int(contract["end_sec"]),
                    )
                status = "valid" if payload is not None else ("invalid" if exists else "missing")
                item: dict[str, Any] = {
                    "canonical_asset_id": str(candidate["canonical_asset_id"]),
                    "venue": venue,
                    "symbol": symbol,
                    "series": series,
                    "path": str(path),
                    "status": status,
                    "bytes": path.stat().st_size if exists else 0,
                }
                if payload is not None:
                    item.update(
                        {
                            "data_request_hash": payload.get("data_request_hash"),
                            "origin_plan_hash": payload.get("origin_plan_hash"),
                            "rows_sha256": payload.get("rows_sha256"),
                            "row_count": len(payload.get("rows") or []),
                            "cache_file_sha256": collector.sha256_file(path),
                        }
                    )
                elif exists:
                    item["cache_file_sha256"] = collector.sha256_file(path)
                items.append(item)

    expected = len(items)
    valid = sum(item["status"] == "valid" for item in items)
    invalid = sum(item["status"] == "invalid" for item in items)
    missing = sum(item["status"] == "missing" for item in items)
    if invalid:
        decision = "CACHE_INVALID_NETWORK_REPAIR_REQUIRED"
    elif missing:
        decision = "NETWORK_COLLECT_REQUIRED"
    else:
        decision = "CACHE_READY_NO_NETWORK_REQUIRED"

    def grouped(field: str, values: Sequence[str]) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for value in values:
            selected = [item for item in items if item[field] == value]
            result[value] = {
                "expected_items": len(selected),
                "valid_items": sum(item["status"] == "valid" for item in selected),
                "invalid_items": sum(item["status"] == "invalid" for item in selected),
                "missing_items": sum(item["status"] == "missing" for item in selected),
            }
        return result

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "plan": {
            "path": str(plan_target),
            "plan_hash": str(contract["plan_hash"]),
            "file_sha256": collector.sha256_file(plan_target),
            "preflight_hash": contract.get("preflight_hash"),
        },
        "code_provenance": {
            **snapshot,
            "audit_tool_path": str(Path(__file__).resolve()),
            "audit_tool_sha256": collector.sha256_file(__file__),
        },
        "frozen_contract": {
            "asset_count": len(contract["candidates"]),
            "venues": list(collector.VENUES),
            "series": list(collector.SERIES),
            "start_sec": int(contract["start_sec"]),
            "end_sec": int(contract["end_sec"]),
        },
        "candle_cache": {
            "root": str(cache_root.resolve()),
            "expected_items": expected,
            "valid_items": valid,
            "invalid_items": invalid,
            "missing_items": missing,
            "valid_coverage_fraction": valid / expected if expected else 0.0,
            "by_venue": grouped("venue", collector.VENUES),
            "by_series": grouped("series", collector.SERIES),
            "items": items,
        },
        "funding_references": {
            "expected_items": len(contract["candidates"]) * len(collector.VENUES),
            "verified_items": len(funding_references),
            "all_paths_exist_and_hash_match": (
                len(funding_references)
                == len(contract["candidates"]) * len(collector.VENUES)
            ),
            "references": funding_references,
            "payload_values_parsed": False,
        },
        "access_audit": {
            "market_candle_rows_read": market_rows_read,
            "market_candle_rows_used_for_integrity_only": market_rows_read,
            "signals_read": False,
            "returns_read": False,
            "pnl_read": False,
            "oos_read": False,
            "network_accessed": False,
        },
        "conclusion": {
            "cache_can_bypass_network_collect": decision == "CACHE_READY_NO_NETWORK_REQUIRED",
            "actual_public_network_collect_required": decision != "CACHE_READY_NO_NETWORK_REQUIRED",
            "train_postprocess_allowed_now": False,
            "oos_allowed_now": False,
            "reason": f"valid={valid}, invalid={invalid}, missing={missing}, expected={expected}",
        },
        "duration_sec": round(time.monotonic() - started, 3),
    }
    semantic = dict(report)
    semantic.pop("generated_at_utc", None)
    semantic.pop("duration_sec", None)
    report["audit_semantic_hash"] = collector.sha256_json(semantic)
    _atomic_write_new(report_target, report)
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit request-addressed basis-v2 cache")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--report-output", required=True)
    parser.add_argument("--code-snapshot-dir", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = audit_historical_basis_v2_cache(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_root=args.output_root,
            report_output=args.report_output,
            code_snapshot_dir=args.code_snapshot_dir,
            max_runtime_sec=args.max_runtime_sec,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(
        json.dumps(
            {
                "status": "OK",
                "decision": report["decision"],
                "valid_items": report["candle_cache"]["valid_items"],
                "invalid_items": report["candle_cache"]["invalid_items"],
                "missing_items": report["candle_cache"]["missing_items"],
                "report": str(Path(args.report_output).expanduser().resolve()),
                "audit_semantic_hash": report["audit_semantic_hash"],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
