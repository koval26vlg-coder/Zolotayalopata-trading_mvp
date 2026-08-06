from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from basis_paper_oms import (  # noqa: E402
    apply_basis_paper_observation,
    initialize_basis_paper_oms,
    paper_oms_single_writer_lock,
    reconcile_basis_paper_state,
    verify_basis_paper_ledger,
)
from historical_basis_edge import (  # noqa: E402
    build_historical_basis_plan,
    sha256_file,
    sha256_json,
)


def _semantic_hash(payload: dict[str, object]) -> str:
    ignored = {"generated_at_utc", "deterministic_result_hash", "runtime_sec", "cache_hit"}
    return sha256_json({key: value for key, value in payload.items() if key not in ignored})


def _write_fixture_chain(root: Path) -> tuple[Path, Path]:
    plan_path = root / "plan.json"
    plan = build_historical_basis_plan(
        [
            {
                "canonical_asset_id": f"asset:{index}",
                "base": f"A{index}",
                "quote": "USDT",
                "mexc_symbol": f"A{index}_USDT",
                "gateio_symbol": f"A{index}_USDT",
                "mexc_status": "trading",
                "gateio_status": "trading",
                "common_history_days": 400,
                "binance_spot": False,
                "categories": [],
                "liquidity_rank": index,
            }
            for index in range(8)
        ],
        plan_path,
        frozen_at_utc="2026-07-15T00:00:00Z",
    )
    evaluation = {
        "schema": "trading_mvp_historical_basis_owned_evaluation_v1",
        "plan_hash": plan["plan_hash"],
        "verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        "runtime_sec": 12.345,
    }
    evaluation["deterministic_result_hash"] = _semantic_hash(evaluation)
    evaluation_path = root / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    report = {
        "schema": "trading_mvp_historical_basis_sprint_report_v1",
        "historical_evaluation": {
            "path": str(evaluation_path),
            "file_sha256": sha256_file(evaluation_path),
            "semantic_hash": evaluation["deterministic_result_hash"],
            "verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        },
        "verdict": "PAPER_FORWARD_READY",
        "safety": {"live_orders": False, "api_keys": False, "leverage": False},
    }
    report["deterministic_result_hash"] = _semantic_hash(report)
    report_path = root / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return plan_path, report_path


def _observation(
    ts: int,
    *,
    mexc_mark: float,
    gate_mark: float,
    mexc_trade: float = 100.0,
    gate_trade: float = 100.0,
    funding_settlement_id: str | None = None,
    mexc_funding_rate: float | None = None,
    gateio_funding_rate: float | None = None,
    data_quality_ok: bool = True,
) -> dict[str, object]:
    return {
        "ts": ts,
        "base": "A0",
        "mexc_trade_price": mexc_trade,
        "gateio_trade_price": gate_trade,
        "mexc_mark_price": mexc_mark,
        "mexc_index_price": 100.0,
        "gateio_mark_price": gate_mark,
        "gateio_index_price": 100.0,
        "funding_settlement_id": funding_settlement_id,
        "mexc_funding_rate": mexc_funding_rate,
        "gateio_funding_rate": gateio_funding_rate,
        "data_quality_ok": data_quality_ok,
    }


class BasisPaperOmsTests(unittest.TestCase):
    def test_single_writer_lock_blocks_concurrent_mutation_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"

            with paper_oms_single_writer_lock(
                ledger_path=ledger,
                state_path=state,
                operation="test-owner",
            ):
                with self.assertRaisesRegex(RuntimeError, "writer lock is already held"):
                    initialize_basis_paper_oms(
                        plan,
                        report,
                        ledger_path=ledger,
                        state_path=state,
                    )

            self.assertFalse(state.with_suffix(".json.writer.lock").exists())
            initialized = initialize_basis_paper_oms(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
            )
            self.assertEqual(initialized["status"], "FLAT")

    def test_two_leg_lifecycle_calculates_pnl_without_manual_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_basis_paper_oms(plan, report, ledger_path=ledger, state_path=state)

            opened = apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(300, mexc_mark=99.0, gate_mark=101.0),
            )
            self.assertEqual(opened["status"], "OPEN")
            self.assertEqual(opened["positions"]["A0"]["long_venue"], "mexc")

            funded = apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(
                    600,
                    mexc_mark=99.0,
                    gate_mark=101.0,
                    funding_settlement_id="settlement-1",
                    mexc_funding_rate=0.001,
                    gateio_funding_rate=0.002,
                ),
            )
            self.assertAlmostEqual(funded["positions"]["A0"]["funding_pnl_quote"], 0.5)

            closed = apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(
                    900,
                    mexc_mark=100.0,
                    gate_mark=100.1,
                    mexc_trade=101.0,
                    gate_trade=99.0,
                ),
            )
            self.assertEqual(closed["status"], "FLAT")
            cycle_cost = json.loads(plan.read_text(encoding="utf-8"))["economics"]["normal_cycle_cost"]["total_bps"]
            expected = 10.0 + 0.5 - 500.0 * cycle_cost / 10_000.0
            self.assertAlmostEqual(closed["realized_net_pnl_quote"], expected)
            self.assertEqual(verify_basis_paper_ledger(ledger)["event_count"], 7)
            self.assertTrue(reconcile_basis_paper_state(state, ledger)["matched"])

    def test_manual_pnl_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_basis_paper_oms(plan, report, ledger_path=ledger, state_path=state)
            observation = _observation(300, mexc_mark=99.0, gate_mark=101.0)
            observation["net_pnl_quote"] = 999.0
            with self.assertRaisesRegex(ValueError, "manual PnL"):
                apply_basis_paper_observation(
                    plan,
                    report,
                    ledger_path=ledger,
                    state_path=state,
                    observation=observation,
                )
            self.assertFalse(state.with_suffix(".json.writer.lock").exists())

    def test_ledger_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_basis_paper_oms(plan, report, ledger_path=ledger, state_path=state)
            ledger.write_text(ledger.read_text(encoding="utf-8").replace("INITIALIZED", "ALTERED"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_basis_paper_ledger(ledger)

    def test_data_quality_failure_triggers_fail_closed_kill_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_basis_paper_oms(plan, report, ledger_path=ledger, state_path=state)
            halted = apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(300, mexc_mark=99.0, gate_mark=101.0, data_quality_ok=False),
            )
            self.assertEqual(halted["status"], "HALTED")
            self.assertEqual(halted["kill_switch_reason"], "data_quality_failure")

    def test_daily_loss_limit_halts_after_internally_computed_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_basis_paper_oms(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                daily_loss_limit_quote=10.0,
            )
            apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(300, mexc_mark=99.0, gate_mark=101.0),
            )
            halted = apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(
                    600,
                    mexc_mark=100.0,
                    gate_mark=100.1,
                    mexc_trade=90.0,
                    gate_trade=110.0,
                ),
            )
            self.assertEqual(halted["status"], "HALTED")
            self.assertEqual(halted["kill_switch_reason"], "daily_loss_limit")
            self.assertLess(halted["realized_net_pnl_quote"], -10.0)

    def test_wal_recovers_a_valid_but_stale_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_basis_paper_oms(plan, report, ledger_path=ledger, state_path=state)
            initialized_state = state.read_bytes()
            apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(300, mexc_mark=99.0, gate_mark=101.0),
            )
            state.write_bytes(initialized_state)
            recovered = apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(600, mexc_mark=99.0, gate_mark=101.0),
            )
            self.assertEqual(recovered["status"], "OPEN")
            self.assertIn("A0", recovered["positions"])
            self.assertTrue(reconcile_basis_paper_state(state, ledger)["matched"])

    def test_duplicate_funding_settlement_does_not_partially_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, report = _write_fixture_chain(root)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_basis_paper_oms(plan, report, ledger_path=ledger, state_path=state)
            apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(300, mexc_mark=99.0, gate_mark=101.0),
            )
            apply_basis_paper_observation(
                plan,
                report,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(
                    600,
                    mexc_mark=99.0,
                    gate_mark=101.0,
                    funding_settlement_id="settlement-1",
                    mexc_funding_rate=0.001,
                    gateio_funding_rate=0.002,
                ),
            )
            before = verify_basis_paper_ledger(ledger)["event_count"]
            with self.assertRaisesRegex(ValueError, "duplicate funding settlement"):
                apply_basis_paper_observation(
                    plan,
                    report,
                    ledger_path=ledger,
                    state_path=state,
                    observation=_observation(
                        900,
                        mexc_mark=99.0,
                        gate_mark=101.0,
                        funding_settlement_id="settlement-1",
                        mexc_funding_rate=0.001,
                        gateio_funding_rate=0.002,
                    ),
                )
            self.assertEqual(verify_basis_paper_ledger(ledger)["event_count"], before)


if __name__ == "__main__":
    unittest.main()
