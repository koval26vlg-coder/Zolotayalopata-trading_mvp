from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_v2 import DAY_SEC, build_historical_basis_v2_plan, sha256_file  # noqa: E402
from historical_basis_v2_evaluator import (  # noqa: E402
    SCHEMA as EVALUATION_SCHEMA,
    _artifact_hash as evaluation_hash,
)
from historical_basis_v2_execution_probe import (  # noqa: E402
    artifact_hash as probe_artifact_hash,
    build_execution_probe_plan,
    build_execution_probe_report,
    finalize_execution_probe_window,
)
from historical_basis_v2_paper_oms import (  # noqa: E402
    LEDGER_EVENT_SCHEMA,
    PAPER_PLAN_SCHEMA,
    STATE_SCHEMA,
    apply_historical_basis_v2_paper_observation,
    build_historical_basis_v2_paper_plan,
    initialize_historical_basis_v2_paper_oms,
    historical_basis_v2_paper_status,
    reconcile_historical_basis_v2_paper_state,
    validate_historical_basis_v2_paper_plan,
    verify_historical_basis_v2_paper_ledger,
)


def _asset(index: int) -> dict[str, object]:
    base = f"A{index:02d}"
    return {
        "canonical_asset_id": f"asset:{base.lower()}",
        "base": base,
        "quote": "USDT",
        "mexc_symbol": f"{base}_USDT",
        "gateio_symbol": f"{base}_USDT",
        "mexc_status": "trading",
        "gateio_status": "trading",
        "common_history_days": 179,
        "binance_spot": False,
        "categories": [],
        "availability_rank": index,
    }


def _write_evaluation(root: Path) -> tuple[dict[str, object], Path]:
    root.mkdir(parents=True, exist_ok=True)
    historical_plan_path = root / "historical-plan.json"
    historical_plan = build_historical_basis_v2_plan(
        [_asset(index) for index in range(8)],
        output_path=historical_plan_path,
        window_end_ts=179 * DAY_SEC,
        frozen_at_utc="2026-07-16T00:00:00+00:00",
    )
    evaluation: dict[str, object] = {
        "schema": EVALUATION_SCHEMA,
        "stage": "full_evaluation",
        "verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        "plan_hash": historical_plan["plan_hash"],
        "plan_path": str(historical_plan_path),
        "plan_file_sha256": sha256_file(historical_plan_path),
        "code_provenance": historical_plan["code_provenance"],
        "normal_trades": [
            {"base": f"A{index % 8:02d}", "episode_id": f"episode-{index}"}
            for index in range(40)
        ],
        "stress_trades": [
            {"base": f"A{index % 8:02d}", "episode_id": f"episode-{index}"}
            for index in range(40)
        ],
        "metrics": {
            "independent_episode_count": 40,
            "unique_dates": 20,
            "base_count": 8,
            "price_only_expectancy_quote": 1.0,
            "total_expectancy_quote": 1.0,
            "profit_factor": 1.4,
            "positive_fixed_subperiods": 4,
            "normal_net_pnl_quote": 40.0,
            "stress_net_pnl_quote": 5.0,
            "stress_expectancy_quote": 0.125,
            "cluster_bootstrap_lower_95_quote": 0.01,
            "max_concentration_share": 0.20,
            "max_drawdown_fraction": 0.05,
            "direction_net_pnl_quote": {"mexc_long": 1.0, "gateio_long": 1.0},
        },
        "four_hour_robustness": {"passed": True, "rejection_reasons": []},
        "oos_read": True,
        "oos_input_hashes": {"candles_sha256": "b" * 64},
        "feasibility_provenance": {"deterministic_result_hash": "c" * 64},
        "data_access_audit": {
            "oos_files_opened": True,
            "oos_returns_read": True,
            "network_access": False,
            "grid_search": False,
            "retune": False,
        },
        "rejection_reasons": [],
    }
    evaluation["deterministic_result_hash"] = evaluation_hash(evaluation)
    evaluation_path = root / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    return historical_plan, evaluation_path


def _write_samples(path: Path, *, window_index: int, qualifying: bool) -> None:
    rows = []
    for cycle in range(1, 201):
        rows.append(
            {
                "schema": "trading_mvp_historical_basis_v2_execution_probe_sample_v1",
                "window_index": window_index,
                "cycle": cycle,
                "base": "A00",
                "timestamp_skew_ms": 400.0,
                "long_execution": {
                    "filled": True,
                    "impact_bps": 7.0,
                    "capacity_quote_at_max_impact": 750.0,
                },
                "short_execution": {
                    "filled": True,
                    "impact_bps": 8.0,
                    "capacity_quote_at_max_impact": 700.0,
                },
                "valid": True,
                "qualifying": qualifying and cycle == 200,
            }
        )
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_probe_report(root: Path, *, qualifying: bool = True) -> tuple[dict[str, object], Path]:
    _historical_plan, evaluation_path = _write_evaluation(root)
    probe_plan_path = root / "probe-plan.json"
    probe_plan = build_execution_probe_plan(
        evaluation_path,
        probe_plan_path,
        first_window_start_utc="2026-07-17T00:00:00+00:00",
    )
    manifests = []
    for window_index in range(3):
        samples = root / f"samples-{window_index}.jsonl"
        _write_samples(samples, window_index=window_index, qualifying=qualifying and window_index == 2)
        manifest = root / f"manifest-{window_index}.json"
        finalize_execution_probe_window(
            probe_plan_path,
            expected_probe_plan_hash=probe_plan["probe_plan_hash"],
            window_index=window_index,
            samples_path=samples,
            manifest_path=manifest,
            completed_cycles=240,
            expected_cycles=240,
            errors=[],
        )
        manifests.append(manifest)
    report_path = root / "probe-report.json"
    report = build_execution_probe_report(
        evaluation_path=evaluation_path,
        probe_plan_path=probe_plan_path,
        manifest_paths=manifests,
        output_path=report_path,
    )
    return report, report_path


def _execution_books(
    ts: int,
    *,
    converged: bool,
    mexc_observed_offset_ms: int = 0,
    gateio_observed_offset_ms: int = 0,
    mexc_quantity: float = 10.0,
    gateio_quantity: float = 10.0,
) -> dict[str, object]:
    if converged:
        mexc_bid, mexc_ask = 100.9, 101.1
        gateio_bid, gateio_ask = 100.9, 101.1
    else:
        mexc_bid, mexc_ask = 99.9, 100.1
        gateio_bid, gateio_ask = 101.9, 102.1
    return {
        "mexc": {
            "observed_ts_ms": ts * 1_000 + mexc_observed_offset_ms,
            "bids": [[mexc_bid, mexc_quantity]],
            "asks": [[mexc_ask, mexc_quantity]],
        },
        "gateio": {
            "observed_ts_ms": ts * 1_000 + gateio_observed_offset_ms,
            "bids": [[gateio_bid, gateio_quantity]],
            "asks": [[gateio_ask, gateio_quantity]],
        },
    }


def _observation(
    ts: int,
    *,
    converged: bool = False,
    settlement: bool = False,
    include_execution_books: bool = True,
    mexc_observed_offset_ms: int = 0,
    gateio_observed_offset_ms: int = 0,
    mexc_quantity: float = 10.0,
    gateio_quantity: float = 10.0,
) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": ts,
        "base": "A00",
        "mexc_trade_price": 100.0 if not converged else 101.0,
        "gateio_trade_price": 102.0 if not converged else 101.0,
        "mexc_mark_price": 100.0,
        "mexc_index_price": 100.0,
        "gateio_mark_price": 102.0 if not converged else 100.1,
        "gateio_index_price": 100.0,
        "data_quality_ok": True,
    }
    if include_execution_books:
        row["execution_books"] = _execution_books(
            ts,
            converged=converged,
            mexc_observed_offset_ms=mexc_observed_offset_ms,
            gateio_observed_offset_ms=gateio_observed_offset_ms,
            mexc_quantity=mexc_quantity,
            gateio_quantity=gateio_quantity,
        )
    if settlement:
        row.update(
            {
                "funding_settlement_id": f"settlement-{ts}",
                "mexc_funding_rate": 0.001,
                "gateio_funding_rate": 0.002,
            }
        )
    return row


class HistoricalBasisV2PaperOmsTests(unittest.TestCase):
    def test_qualifying_signal_without_two_venue_books_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _report, report_path = _write_probe_report(root)
            paper_plan_path = root / "paper-plan.json"
            paper_plan = build_historical_basis_v2_paper_plan(report_path, paper_plan_path)
            self.assertTrue(paper_plan["execution_guard"]["required_for_position_transition"])
            ledger = root / "paper-ledger.jsonl"
            state = root / "paper-state.json"
            initialize_historical_basis_v2_paper_oms(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
            )

            blocked = apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(1_000, include_execution_books=False),
            )

            self.assertEqual(blocked["status"], "FLAT")
            self.assertEqual(blocked["blocked_execution_count"], 1)
            self.assertEqual(blocked["last_execution_block_reason"], "missing_execution_books")
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events[-1]["event_type"], "EXECUTION_BLOCKED")

    def test_position_uses_depth_prices_and_blocks_stale_or_thin_books(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _report, report_path = _write_probe_report(root)
            paper_plan_path = root / "paper-plan.json"
            build_historical_basis_v2_paper_plan(report_path, paper_plan_path)
            ledger = root / "paper-ledger.jsonl"
            state = root / "paper-state.json"
            initialize_historical_basis_v2_paper_oms(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
            )

            opened = apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(1_000),
            )
            self.assertAlmostEqual(opened["positions"]["A00"]["long_entry_price"], 100.1)
            self.assertAlmostEqual(opened["positions"]["A00"]["short_entry_price"], 101.9)
            self.assertEqual(opened["executed_transition_count"], 1)

            thin_exit = apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(2_000, converged=True, gateio_quantity=1.0),
            )
            self.assertEqual(thin_exit["status"], "OPEN")
            self.assertEqual(thin_exit["last_execution_block_reason"], "insufficient_capacity")

            closed = apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(3_000, converged=True),
            )
            self.assertEqual(closed["status"], "FLAT")
            self.assertEqual(closed["executed_transition_count"], 2)

            second_root = root / "stale"
            _second_report, second_report_path = _write_probe_report(second_root)
            second_plan = second_root / "paper-plan.json"
            build_historical_basis_v2_paper_plan(second_report_path, second_plan)
            second_ledger = second_root / "ledger.jsonl"
            second_state = second_root / "state.json"
            initialize_historical_basis_v2_paper_oms(
                second_plan,
                second_report_path,
                ledger_path=second_ledger,
                state_path=second_state,
            )
            stale = apply_historical_basis_v2_paper_observation(
                second_plan,
                second_report_path,
                ledger_path=second_ledger,
                state_path=second_state,
                observation=_observation(1_000, mexc_observed_offset_ms=-6_000),
            )
            self.assertEqual(stale["status"], "FLAT")
            self.assertEqual(stale["last_execution_block_reason"], "stale_quote")

    def test_ready_probe_builds_hash_bound_plan_and_two_leg_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, report_path = _write_probe_report(root)
            self.assertEqual(report["verdict"], "PAPER_FORWARD_READY")
            paper_plan_path = root / "paper-plan.json"
            paper_plan = build_historical_basis_v2_paper_plan(report_path, paper_plan_path)

            self.assertEqual(paper_plan["schema"], PAPER_PLAN_SCHEMA)
            self.assertEqual([row["base"] for row in paper_plan["universe"]["candidates"]], ["A00"])
            self.assertEqual(paper_plan["minimum_independent_paper_events"], 15)
            self.assertFalse(paper_plan["safety"]["live_orders"])
            self.assertEqual(
                validate_historical_basis_v2_paper_plan(paper_plan_path)["paper_plan_hash"],
                paper_plan["paper_plan_hash"],
            )

            ledger = root / "paper-ledger.jsonl"
            state = root / "paper-state.json"
            initialized = initialize_historical_basis_v2_paper_oms(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
            )
            self.assertEqual(initialized["schema"], STATE_SCHEMA)
            self.assertEqual(initialized["plan_hash"], paper_plan["paper_plan_hash"])

            opened = apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(1_000),
            )
            self.assertEqual(opened["positions"]["A00"]["long_venue"], "mexc")
            self.assertEqual(opened["positions"]["A00"]["short_venue"], "gateio")

            funded = apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(2_000, settlement=True),
            )
            self.assertGreater(funded["positions"]["A00"]["funding_pnl_quote"], 0.0)

            closed = apply_historical_basis_v2_paper_observation(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
                observation=_observation(3_000, converged=True),
            )
            self.assertEqual(closed["status"], "FLAT")
            ledger_status = verify_historical_basis_v2_paper_ledger(ledger)
            self.assertTrue(ledger_status["valid"])
            first_event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(first_event["schema"], LEDGER_EVENT_SCHEMA)
            self.assertTrue(reconcile_historical_basis_v2_paper_state(state, ledger)["matched"])

    def test_fifteen_positive_reconciled_events_only_reach_live_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _report, report_path = _write_probe_report(root)
            paper_plan_path = root / "paper-plan.json"
            build_historical_basis_v2_paper_plan(report_path, paper_plan_path)
            ledger = root / "ledger.jsonl"
            state = root / "state.json"
            initialize_historical_basis_v2_paper_oms(
                paper_plan_path,
                report_path,
                ledger_path=ledger,
                state_path=state,
            )
            for index in range(15):
                start = 10_000 + index * 10
                apply_historical_basis_v2_paper_observation(
                    paper_plan_path,
                    report_path,
                    ledger_path=ledger,
                    state_path=state,
                    observation=_observation(start),
                )
                apply_historical_basis_v2_paper_observation(
                    paper_plan_path,
                    report_path,
                    ledger_path=ledger,
                    state_path=state,
                    observation=_observation(start + 1, converged=True),
                )

            status = historical_basis_v2_paper_status(
                paper_plan_path,
                ledger_path=ledger,
                state_path=state,
            )
            self.assertEqual(status["independent_paper_event_count"], 15)
            self.assertGreater(status["paper_net_pnl_quote"], 0.0)
            self.assertEqual(status["verdict"], "LIVE_REVIEW_ELIGIBLE")
            self.assertEqual(status["next_allowed_command"], "request-separate-live-review")
            self.assertFalse(status["safety"]["live_orders"])

    def test_await_event_tamper_and_manual_pnl_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            await_report, await_path = _write_probe_report(root / "await", qualifying=False)
            self.assertEqual(await_report["verdict"], "HISTORICAL_ACCEPT_AWAIT_EVENT")
            with self.assertRaisesRegex(ValueError, "PAPER_FORWARD_READY"):
                build_historical_basis_v2_paper_plan(await_path, root / "rejected-plan.json")

            ready_root = root / "ready"
            report, report_path = _write_probe_report(ready_root)
            paper_plan_path = root / "paper-plan.json"
            build_historical_basis_v2_paper_plan(report_path, paper_plan_path)
            report["rejection_reasons"] = ["tampered"]
            report["deterministic_result_hash"] = probe_artifact_hash(report)
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file hash|provenance|hash"):
                validate_historical_basis_v2_paper_plan(paper_plan_path)

            raw_root = root / "raw-tamper"
            raw_report, raw_report_path = _write_probe_report(raw_root)
            manifest_path = Path(raw_report["windows"][0]["manifest_path"])
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "manifest file hash"):
                build_historical_basis_v2_paper_plan(
                    raw_report_path,
                    raw_root / "paper-plan.json",
                )

            clean_root = root / "clean"
            _report, clean_report_path = _write_probe_report(clean_root)
            clean_plan_path = clean_root / "paper-plan.json"
            build_historical_basis_v2_paper_plan(clean_report_path, clean_plan_path)
            ledger = clean_root / "ledger.jsonl"
            state = clean_root / "state.json"
            initialize_historical_basis_v2_paper_oms(
                clean_plan_path,
                clean_report_path,
                ledger_path=ledger,
                state_path=state,
            )
            row = _observation(1_000)
            row["net_pnl_quote"] = 999.0
            with self.assertRaisesRegex(ValueError, "manual PnL"):
                apply_historical_basis_v2_paper_observation(
                    clean_plan_path,
                    clean_report_path,
                    ledger_path=ledger,
                    state_path=state,
                    observation=row,
                )


if __name__ == "__main__":
    unittest.main()
