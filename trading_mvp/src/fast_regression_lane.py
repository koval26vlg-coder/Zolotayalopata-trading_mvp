from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from historical_basis_v2 import sha256_file, sha256_json


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


RESULT_SCHEMA = "trading_mvp_fast_regression_lane_result_v1"
MAX_RUNTIME_SEC = 300
FAST_TEST_MODULES = (
    "trading_mvp.tests.test_active_run_gate",
    "trading_mvp.tests.test_autopilot_guard",
    "trading_mvp.tests.test_autopilot_research_backlog",
    "trading_mvp.tests.test_autopilot_visible_pipeline",
    "trading_mvp.tests.test_autopilot_work_queue",
    "trading_mvp.tests.test_basis_paper_oms",
    "trading_mvp.tests.test_canonical_asset_registry",
    "trading_mvp.tests.test_costs",
    "trading_mvp.tests.test_dense_ws_campaign_contract",
    "trading_mvp.tests.test_dense_ws_campaign_quality",
    "trading_mvp.tests.test_dense_ws_causal_materializer",
    "trading_mvp.tests.test_dense_ws_materialization_bound_plan",
    "trading_mvp.tests.test_dense_ws_signal_evaluator_contract",
    "trading_mvp.tests.test_dense_ws_acceptance_proposal",
    "trading_mvp.tests.test_dense_ws_signal_evaluator_freeze",
    "trading_mvp.tests.test_dense_ws_execution_realization",
    "trading_mvp.tests.test_dense_ws_postrun_orchestration",
    "trading_mvp.tests.test_execution_gate",
    "trading_mvp.tests.test_global_market_writer_claim",
    "trading_mvp.tests.test_historical_basis_v2_paper_oms",
    "trading_mvp.tests.test_paper_contract_validator",
    "trading_mvp.tests.test_paper_log_redaction",
    "trading_mvp.tests.test_paper_observer_monitor",
    "trading_mvp.tests.test_paper_observer_runtime",
    "trading_mvp.tests.test_paper_reconciliation_adapter",
    "trading_mvp.tests.test_paper_runtime_acl",
    "trading_mvp.tests.test_paper_runtime_fault_injection",
    "trading_mvp.tests.test_paper_secret_provider",
)


def validate_fast_test_modules(modules: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in modules)
    if not normalized or any(not value for value in normalized):
        raise ValueError("fast regression modules must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("fast regression modules must be unique")
    forbidden = (
        "_collect",
        "_oos",
        "_grid",
        "_backtest",
        "_live_",
        "_private_client",
    )
    for module in normalized:
        if not module.startswith("trading_mvp.tests.test_"):
            raise ValueError(f"fast regression module is outside test package: {module}")
        lowered = module.casefold()
        if any(token in lowered for token in forbidden):
            raise ValueError(f"fast regression module may invoke a forbidden lane: {module}")
    return normalized


def _write_json_immutable(path: str | Path, payload: dict[str, Any]) -> None:
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


def run_fast_regression(
    *,
    output_path: str | Path | None = None,
    verbosity: int = 1,
) -> dict[str, Any]:
    modules = validate_fast_test_modules(FAST_TEST_MODULES)
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromNames(list(modules))
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    runtime_sec = time.monotonic() - started
    if runtime_sec > MAX_RUNTIME_SEC:
        raise TimeoutError(
            f"fast regression exceeded {MAX_RUNTIME_SEC}s: {runtime_sec:.3f}s"
        )
    deterministic = {
        "schema": RESULT_SCHEMA,
        "lane_id": "trading_mvp_fast_regression_lane_v1",
        "modules": list(modules),
        "module_list_hash_sha256": sha256_json(list(modules)),
        "tests_run": int(result.testsRun),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "successful": bool(result.wasSuccessful()),
        "maximum_runtime_sec": MAX_RUNTIME_SEC,
        "full_release_suite_retained": True,
        "full_release_suite_tests": 1_235,
        "network_collectors": False,
        "grid_or_retune": False,
        "live_orders": False,
        "private_api_keys": False,
    }
    payload = {
        **deterministic,
        "verdict": "FAST_REGRESSION_PASS" if result.wasSuccessful() else "FAST_REGRESSION_FAIL",
        "runtime_sec": runtime_sec,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runner_file_sha256": sha256_file(Path(__file__).resolve()),
        "deterministic_result_hash": sha256_json(deterministic),
    }
    if not result.wasSuccessful():
        raise RuntimeError("fast regression failed")
    if output_path is not None:
        _write_json_immutable(output_path, payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bounded trading_mvp fast regression")
    parser.add_argument("--output")
    parser.add_argument("--verbosity", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_fast_regression(
        output_path=args.output,
        verbosity=args.verbosity,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
