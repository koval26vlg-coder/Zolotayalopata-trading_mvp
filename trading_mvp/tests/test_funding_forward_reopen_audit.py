from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "trading_mvp" / "src" / "funding_forward_reopen_audit.py"
DAY_SEC = 86_400


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_unparseable_market_file(
    path: Path,
    *,
    exchange: str,
    symbol: str,
    interval: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    interval_field = f', "interval": "{interval}"' if interval else ""
    path.write_text(
        f'{{"exchange": "{exchange}", "symbol": "{symbol}"{interval_field}, '
        '"start_sec": 1769061904, "end_sec": 1786341904, "rows": ['
        "THIS_MARKET_VALUE_PAYLOAD_MUST_NEVER_BE_PARSED]}",
        encoding="utf-8",
    )


def _fixture(root: Path, *, interval: str = "1d", execution_snapshots: int = 3) -> dict[str, object]:
    symbol = "AKE_USDT"
    run_dir = root / "daily_forward_20260810"
    manifest = run_dir / "manifest.json"
    _write_json(
        manifest,
        {
            "schema": "daily_collect_v1",
            "run_id": "daily_forward_20260810",
            "params": {
                "exchanges": ["mexc", "gateio"],
                "days": 200,
                "start_sec": 1769061904,
                "end_sec": 1786341904,
                "universe_csv": "coins_not_on_binance_full_2026-05-29.csv",
            },
            "symbols_total": 400,
            "error_count": 0,
            "statuses": [
                {
                    "exchange": "mexc",
                    "symbol": symbol,
                    "klines_rows": 200,
                    "funding_rows": 1200,
                    "klines_status": "ok",
                    "funding_status": "ok",
                    "errors": [],
                },
                {
                    "exchange": "gateio",
                    "symbol": symbol,
                    "klines_rows": 201,
                    "funding_rows": 1073,
                    "klines_status": "ok",
                    "funding_status": "ok",
                    "errors": [],
                },
            ],
        },
    )
    for exchange in ("mexc", "gateio"):
        _write_unparseable_market_file(
            run_dir / exchange / "klines" / f"{symbol}.json",
            exchange=exchange,
            symbol=symbol,
            interval=interval,
        )
        _write_unparseable_market_file(
            run_dir / exchange / "funding" / f"{symbol}.json",
            exchange=exchange,
            symbol=symbol,
        )

    bank = root / "hypothesis_bank.json"
    _write_json(
        bank,
        {
            "hypotheses": [
                {
                    "id": "funding_regime_persistence_carry_v2",
                    "status": "BANKED_NEEDS_NEW_DATA",
                    "required_data_type": "FUNDING_HISTORY_EXTENSION",
                    "minimum_data": {
                        "days": 90,
                        "settlements": 180,
                        "dual_leg_coverage": 0.8,
                        "execution_snapshots": 180,
                    },
                    "forbidden": ["VIP/rebate assumption", "leverage"],
                }
            ]
        },
    )

    legacy_plan = root / "legacy_plan.json"
    legacy_plan_hash = "c" * 64
    legacy_oos_end = 1783000800
    _write_json(
        legacy_plan,
        {
            "schema": "fast_first_funding_regime_persistence_plan_v2",
            "mode": "PlanOnly",
            "plan_hash": legacy_plan_hash,
            "frozen_parameters_no_grid": True,
            "strategy": {
                "entry": "next contiguous 1h trade open after the complete UTC signal day",
                "grid_search": False,
                "parameter_selection_on_oos": False,
            },
            "sealed_input": {
                "split": {"oos_end_sec": legacy_oos_end},
                "oos_path": "normalized-candles.oos.jsonl",
            },
            "validation": {"execution_probe_snapshots_required": 180},
        },
    )

    closure = root / "legacy_closure.json"
    _write_json(
        closure,
        {
            "schema": "funding_regime_persistence_v2_terminal_closure_v1",
            "status": "BRANCH_CLOSED_INSUFFICIENT_DATA",
            "final": True,
            "hypothesis_id": "funding_regime_persistence_carry_v2",
            "plan_hash": legacy_plan_hash,
            "verdict": "INSUFFICIENT_DATA",
            "observed": {
                "independent_episodes": 11,
                "required_independent_episodes": 20,
                "stress_net_pnl_quote": -130.79,
            },
            "governance": {
                "retune_allowed": False,
                "execution_probe_allowed": False,
                "paper_forward_allowed": False,
                "live_orders_allowed": False,
            },
        },
    )

    history = root / "funding_forward_history_audit_20260810.json"
    _write_json(
        history,
        {
            "schema": "funding_forward_history_audit_v1",
            "audit_passed": True,
            "decision": "OVERLAPPING_SUMMARIES_NOT_INDEPENDENT_EDGE_EVIDENCE",
            "promotion_allowed": False,
            "inputs": {
                "manifest_20260810": {"path": str(manifest), "sha256": _sha256(manifest)},
            },
            "history_contract": {
                "through_stamp": "20260810",
                "comparable_snapshot_count": execution_snapshots,
            },
            "window_overlap": {"inclusive_window_days": 91},
            "symbol_track": {
                "symbol": symbol,
                "identity_status": "OFFICIAL_SAME_ASSET_VERIFIED",
                "execution_candidate_presence_count": execution_snapshots,
                "observations": [
                    {
                        "stamp": "20260810",
                        "pair_present": True,
                        "aligned_days": 91,
                        "direction": "short_b_long_a",
                    }
                ],
            },
            "safety": {
                "market_rows_read": False,
                "returns_or_pnl_read": False,
                "oos_read": False,
                "grid_or_retune": False,
                "network_access": False,
            },
        },
    )

    return {
        "bank": bank,
        "legacy_plan": legacy_plan,
        "closure": closure,
        "manifest": manifest,
        "history": history,
        "run_dir": run_dir,
        "output": root / "reopen_audit.json",
        "symbol": symbol,
    }


def _run(paths: dict[str, object]) -> subprocess.CompletedProcess[str]:
    bank = Path(paths["bank"])
    legacy_plan = Path(paths["legacy_plan"])
    closure = Path(paths["closure"])
    manifest = Path(paths["manifest"])
    history = Path(paths["history"])
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--hypothesis-bank",
            str(bank),
            "--expected-bank-sha256",
            _sha256(bank),
            "--legacy-plan",
            str(legacy_plan),
            "--expected-legacy-plan-sha256",
            _sha256(legacy_plan),
            "--legacy-closure",
            str(closure),
            "--expected-legacy-closure-sha256",
            _sha256(closure),
            "--current-manifest",
            str(manifest),
            "--expected-current-manifest-sha256",
            _sha256(manifest),
            "--history-audit",
            str(history),
            "--expected-history-audit-sha256",
            _sha256(history),
            "--run-dir",
            str(paths["run_dir"]),
            "--symbol",
            str(paths["symbol"]),
            "--out",
            str(paths["output"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


class FundingForwardReopenAuditTests(unittest.TestCase):
    def test_daily_cache_cannot_reopen_exact_hourly_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            completed = _run(paths)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            audit = json.loads(Path(paths["output"]).read_text(encoding="utf-8"))

        self.assertTrue(audit["audit_passed"])
        self.assertEqual(audit["decision"], "CURRENT_CACHE_REQUIRES_MATERIALLY_DISTINCT_PLANONLY")
        self.assertFalse(audit["same_strategy_planonly_allowed"])
        self.assertFalse(audit["oos_evaluation_allowed"])
        self.assertFalse(audit["execution_probe_ready"])
        self.assertTrue(audit["new_contract_review_required"])
        self.assertEqual(audit["source_gates"]["history_days"]["observed"], 200)
        self.assertTrue(audit["source_gates"]["funding_settlements_per_leg"]["passed"])
        self.assertTrue(audit["source_gates"]["dual_leg_coverage"]["passed"])
        self.assertFalse(audit["source_gates"]["kline_resolution"]["passed"])
        self.assertEqual(audit["execution_gate"]["observed_snapshots"], 3)
        self.assertEqual(audit["execution_gate"]["required_snapshots"], 180)
        self.assertEqual(audit["cache_diff"]["complete_days_after_legacy_oos"], 38)
        self.assertFalse(audit["data_access_audit"]["market_row_arrays_parsed"])
        self.assertFalse(audit["data_access_audit"]["funding_rates_read"])
        self.assertFalse(audit["data_access_audit"]["prices_read"])
        self.assertFalse(audit["data_access_audit"]["pnl_computed"])

    def test_hourly_source_can_only_advance_to_planonly_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp), interval="1h", execution_snapshots=180)
            completed = _run(paths)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            audit = json.loads(Path(paths["output"]).read_text(encoding="utf-8"))

        self.assertEqual(audit["decision"], "READY_FOR_HASH_BOUND_PLANONLY_REVIEW")
        self.assertTrue(audit["same_strategy_planonly_allowed"])
        self.assertFalse(audit["oos_evaluation_allowed"])
        self.assertTrue(audit["execution_probe_ready"])
        self.assertFalse(audit["new_contract_review_required"])

    def test_legacy_plan_and_closure_hash_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            closure = Path(paths["closure"])
            payload = json.loads(closure.read_text(encoding="utf-8"))
            payload["plan_hash"] = "d" * 64
            _write_json(closure, payload)
            completed = _run(paths)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            audit = json.loads(Path(paths["output"]).read_text(encoding="utf-8"))

        self.assertFalse(audit["audit_passed"])
        self.assertIn("legacy_plan_closure_hash_mismatch", audit["failures"])

    def test_history_manifest_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            history = Path(paths["history"])
            payload = json.loads(history.read_text(encoding="utf-8"))
            payload["inputs"]["manifest_20260810"]["sha256"] = "0" * 64
            _write_json(history, payload)
            completed = _run(paths)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            audit = json.loads(Path(paths["output"]).read_text(encoding="utf-8"))

        self.assertFalse(audit["audit_passed"])
        self.assertIn("history_current_manifest_hash_mismatch", audit["failures"])

    def test_deterministic_hash_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            first = _run(paths)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_result = json.loads(Path(paths["output"]).read_text(encoding="utf-8"))
            second = _run(paths)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            second_result = json.loads(Path(paths["output"]).read_text(encoding="utf-8"))

        self.assertEqual(first_result["deterministic_result_hash"], second_result["deterministic_result_hash"])


if __name__ == "__main__":
    unittest.main()
