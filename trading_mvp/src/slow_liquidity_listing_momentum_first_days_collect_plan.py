from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import slow_liquidity_listing_momentum_first_days_collector as collector
from slow_liquidity_listing_momentum_proxy_date_acceptance import (
    MATERIALIZATION_PATH,
    PROXY_PLAN_PATH,
    PLAN_ID as PARENT_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_first_days_collect_planonly_v1"
PLAN_ID = collector.RUN_ID
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECT_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-first-days-collect-planonly-20260816.json"
)
LAUNCHER_PATH = (
    REPO_ROOT / "tools" / "start_listing_momentum_first_days_collect_visible.ps1"
)
PROXY_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-momentum-proxy-date-acceptance-approval.json"
)
SHARED_FILES = (
    (
        "public_ohlcv_clients",
        REPO_ROOT / "trading_mvp/src/listing_event_history_collector.py",
    ),
    (
        "interval_contract",
        REPO_ROOT / "trading_mvp/src/listing_event_history_collect_plan.py",
    ),
    (
        "global_writer_claim",
        REPO_ROOT / "trading_mvp/src/global_market_writer_claim.py",
    ),
)
OUTPUT_ROOT = Path("E:/trading_mvp/listing-momentum-first-days") / PLAN_ID
CLAIM_PATH = (
    REPO_ROOT / "docs/agent-log" / "active-market-data-writer-claim.json"
)
LAUNCH_RECORD_PATH = (
    REPO_ROOT / "docs/agent-log/run-gates" / f"{PLAN_ID}.launch.json"
)
MAX_RUNTIME_SEC = 1800
SLEEP_SEC = 0.25
TIMEOUT_SEC = 15
MAX_RETRIES = 1
HARD_OUTPUT_CAP_BYTES = 100_000_000
EFFECTIVE_PAGE_SIZES = {"mexc": 500, "gateio": 1000}


class FirstDaysCollectPlanError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise FirstDaysCollectPlanError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialization_content_hash(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    content = {
        key: value for key, value in payload.items() if key != "materialization_hash"
    }
    return canonical_hash(content)


def build_first_days_collect_plan(generated_at_utc: str) -> dict[str, Any]:
    _require(PROXY_PLAN_PATH.is_file(), "proxy acceptance plan missing")
    proxy_plan = json.loads(PROXY_PLAN_PATH.read_text(encoding="utf-8"))
    _require(
        proxy_plan.get("plan_id") == PARENT_PLAN_ID,
        "parent proxy plan id mismatch",
    )
    _require(
        proxy_plan.get("plan_hash") == canonical_hash(proxy_plan),
        "parent proxy plan hash mismatch",
    )
    _require(
        PROXY_RECEIPT_PATH.is_file(),
        "proxy acceptance receipt missing",
    )
    receipt = json.loads(PROXY_RECEIPT_PATH.read_text(encoding="utf-8"))
    _require(
        receipt.get("status") == "PROXY_LISTING_DATE_SOURCE_ACCEPTED",
        "proxy acceptance receipt not accepted",
    )
    _require(
        receipt.get("authorized_scope", {}).get("actual_network_run") is False
        and receipt.get("authorized_scope", {}).get(
            "proxy_first_days_collector_plan_preparation"
        )
        is True,
        "proxy receipt does not authorize collector plan preparation",
    )
    _require(MATERIALIZATION_PATH.is_file(), "proxy materialization missing")
    materialization = json.loads(MATERIALIZATION_PATH.read_text(encoding="utf-8"))
    jobs = collector.derive_first_days_jobs(materialization.get("records") or [])
    _require(len(jobs) > 0, "no first-days jobs derived")
    jobs_by_venue: dict[str, int] = {"mexc": 0, "gateio": 0}
    for job in jobs:
        jobs_by_venue[job["exchange"]] += 1
    logical_requests = len(jobs)
    files = [
        {
            "role": "collector",
            "path": str(
                REPO_ROOT
                / "trading_mvp/src/slow_liquidity_listing_momentum_first_days_collector.py"
            ),
            "sha256": _sha256_file(
                REPO_ROOT
                / "trading_mvp/src/slow_liquidity_listing_momentum_first_days_collector.py"
            ),
        }
    ]
    files.extend(
        {"role": role, "path": str(path), "sha256": _sha256_file(path)}
        for role, path in SHARED_FILES
    )
    files.append(
        {
            "role": "visible_launcher",
            "path": str(LAUNCHER_PATH),
            "sha256": _sha256_file(LAUNCHER_PATH),
        }
    )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "strategy_branch": "slow_liquidity_listing_momentum",
        "mode": "PlanOnly",
        "status": "AWAIT_GUARD_GREEN_VISIBLE_COLLECT",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "private_api": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "actual_collection_allowed": False,
        "replay_allowed": False,
        "evaluator_or_oos_allowed": False,
        "objective": (
            "Collect per-venue first-days 1h OHLCV event windows for the "
            "two-venue universe using accepted proxy trading-start dates. "
            "One visible public read-only run; deterministic flag census in "
            "the manifest. No replay, evaluator, or identity verdict."
        ),
        "source_bindings": {
            "proxy_acceptance_plan": {
                "plan_id": PARENT_PLAN_ID,
                "path": str(PROXY_PLAN_PATH),
                "plan_hash": proxy_plan["plan_hash"],
                "plan_file_sha256": _sha256_file(PROXY_PLAN_PATH),
            },
            "proxy_acceptance_receipt": {
                "path": str(PROXY_RECEIPT_PATH),
                "receipt_hash": receipt["receipt_hash"],
                "receipt_file_sha256": _sha256_file(PROXY_RECEIPT_PATH),
                "status": receipt["status"],
            },
            "materialization": {
                "path": str(MATERIALIZATION_PATH),
                "materialization_hash": materialization["materialization_hash"],
                "file_sha256": _sha256_file(MATERIALIZATION_PATH),
                "content_hash_recomputed_ok": _materialization_content_hash(
                    MATERIALIZATION_PATH
                )
                == materialization["materialization_hash"],
            },
        },
        "universe": {
            "source": "proxy date materialization records",
            "two_venue_base_count": 407,
            "job_count": len(jobs),
            "jobs_by_venue": jobs_by_venue,
            "jobs_sha256": collector.jobs_sha256(jobs),
            "window_sec": collector.WINDOW_SEC,
            "granularity": collector.GRANULARITY,
        },
        "implementation": {
            "files": files,
            "page_caps": {
                "mexc_max_candles_per_request": EFFECTIVE_PAGE_SIZES["mexc"],
                "gateio_max_candles_per_request": EFFECTIVE_PAGE_SIZES["gateio"],
                "probe_window_before_proxy_sec": collector.PROBE_BEFORE_SEC,
                "epoch_aligned_page_boundaries": True,
            },
            "corroboration_and_flags": {
                "history_truncated": (
                    "first in-window 1h bar opens more than "
                    f"{collector.TRUNCATION_TOLERANCE_SEC}s after proxy_event_ts"
                ),
                "proxy_ts_after_first_bar": (
                    "bars exist at least "
                    f"{2 * collector.TRUNCATION_TOLERANCE_SEC}s before "
                    "proxy_event_ts (venue traded earlier than the snapshot field)"
                ),
                "short_window": (
                    f"fewer than {collector.SHORT_WINDOW_MIN_BARS} in-window bars"
                ),
                "no_data": "no bars returned for the probe+window range",
            },
        },
        "execution": {
            "run_id": PLAN_ID,
            "output_root": str(OUTPUT_ROOT),
            "output_jsonl": str(OUTPUT_ROOT / "ohlcv.jsonl"),
            "manifest_path": str(OUTPUT_ROOT / "manifest.json"),
            "stdout_path": str(OUTPUT_ROOT / "stdout.log"),
            "stderr_path": str(OUTPUT_ROOT / "stderr.log"),
            "claim_path": str(CLAIM_PATH),
            "launch_record_path": str(LAUNCH_RECORD_PATH),
            "exchanges": ["mexc", "gateio"],
            "timeframes": [collector.GRANULARITY],
            "jobs_by_venue": jobs_by_venue,
            "effective_page_sizes": dict(EFFECTIVE_PAGE_SIZES),
            "logical_requests": logical_requests,
            "maximum_http_attempts": logical_requests * (MAX_RETRIES + 1),
            "max_retries": MAX_RETRIES,
            "timeout_sec": TIMEOUT_SEC,
            "sleep_sec": SLEEP_SEC,
            "max_runtime_sec": MAX_RUNTIME_SEC,
            "hard_output_cap_bytes": HARD_OUTPUT_CAP_BYTES,
            "jobs_sha256": collector.jobs_sha256(jobs),
        },
        "guard_contract": {
            "active_gate_must_not_be_running": True,
            "global_writer_claim_must_be_absent": True,
            "proxy_acceptance_receipt_must_be_valid": True,
            "plan_hash_must_match": True,
            "output_namespace_must_be_empty": True,
            "visible_terminal_launch_required": True,
            "single_writer_single_run": True,
        },
        "authorized_after_guards": [
            "run one visible public read-only first-days OHLCV collect",
            "write the collect manifest with flag census",
            "read post-collect status",
        ],
        "forbidden": [
            "second market-data writer",
            "resume or retry after STOPPED_INCOMPLETE without a new exact plan",
            "evaluator",
            "OOS",
            "returns or PnL conclusions from flags alone",
            "grid or retune",
            "execution probe",
            "paper or live trading",
            "private API keys",
            "real capital",
            "leverage or margin",
            "treat proxy dates as official announcements",
            "identity verdict",
            "reopen closed nine as listing momentum",
        ],
        "commands": {
            "preflight": (
                "pwsh -NoProfile -ExecutionPolicy Bypass -File "
                f'"{LAUNCHER_PATH}" -PreflightOnly -Json'
            ),
            "status": (
                "pwsh -NoProfile -ExecutionPolicy Bypass -File "
                f'"{LAUNCHER_PATH}" -Status -Json'
            ),
            "visible_start": (
                "pwsh -NoProfile -ExecutionPolicy Bypass -File "
                f'"{LAUNCHER_PATH}"'
            ),
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_first_days_collect_plan(plan)
    return plan


def validate_first_days_collect_plan(plan: dict[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "collect plan schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "collect plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "AWAIT_GUARD_GREEN_VISIBLE_COLLECT",
        "status mismatch",
    )
    _require(plan.get("research_only") is True, "research_only")
    _require(plan.get("public_data_only") is True, "public_data_only")
    _require(plan.get("private_api") is False, "private api")
    _require(plan.get("replay_allowed") is False, "replay allowed")
    _require(
        plan.get("evaluator_or_oos_allowed") is False, "evaluator or oos allowed"
    )
    _require(
        plan.get("actual_collection_allowed") is False,
        "plan itself must not authorize collection without guards",
    )
    bindings = plan.get("source_bindings") or {}
    receipt = bindings.get("proxy_acceptance_receipt") or {}
    _require(
        receipt.get("status") == "PROXY_LISTING_DATE_SOURCE_ACCEPTED",
        "proxy receipt not accepted",
    )
    materialization = bindings.get("materialization") or {}
    _require(
        materialization.get("content_hash_recomputed_ok") is True,
        "materialization content hash mismatch",
    )
    universe = plan.get("universe") or {}
    _require(universe.get("job_count", 0) > 0, "no jobs")
    execution = plan.get("execution") or {}
    _require(
        execution.get("jobs_sha256") == universe.get("jobs_sha256"),
        "jobs binding mismatch",
    )
    _require(
        int(execution.get("max_runtime_sec") or 0) <= 1800,
        "max_runtime_sec exceeds the routine research-only bound",
    )
    page_caps = (plan.get("implementation") or {}).get("page_caps") or {}
    _require(
        execution.get("effective_page_sizes")
        == {
            "mexc": page_caps.get("mexc_max_candles_per_request"),
            "gateio": page_caps.get("gateio_max_candles_per_request"),
        },
        "execution page sizes must mirror implementation page caps",
    )
    guard = plan.get("guard_contract") or {}
    _require(guard.get("active_gate_must_not_be_running") is True, "gate guard")
    _require(
        guard.get("global_writer_claim_must_be_absent") is True,
        "writer claim guard",
    )
    _require(
        guard.get("visible_terminal_launch_required") is True,
        "visible launch guard",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")


def write_first_days_collect_plan(generated_at_utc: str) -> Path:
    plan = build_first_days_collect_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if COLLECT_PLAN_PATH.exists():
        _require(
            COLLECT_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {COLLECT_PLAN_PATH}",
        )
        return COLLECT_PLAN_PATH
    COLLECT_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    COLLECT_PLAN_PATH.write_text(payload, encoding="utf-8")
    return COLLECT_PLAN_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-plan", action="store_true")
    args = parser.parse_args(argv)
    if not args.write_plan:
        raise SystemExit("no authorized action requested")
    generated = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    path = write_first_days_collect_plan(generated)
    plan = json.loads(path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": "PLAN_WRITTEN",
                "path": str(path),
                "plan_hash": plan["plan_hash"],
                "plan_file_sha256": _sha256_file(path),
                "job_count": plan["universe"]["job_count"],
                "jobs_by_venue": plan["universe"]["jobs_by_venue"],
                "logical_requests": plan["execution"]["logical_requests"],
                "max_runtime_sec": plan["execution"]["max_runtime_sec"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
