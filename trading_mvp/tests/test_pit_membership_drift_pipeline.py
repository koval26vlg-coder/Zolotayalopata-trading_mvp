from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402
from pit_membership_drift_evaluator import (  # noqa: E402
    build_evaluation_input_plan,
    run_oos_evaluation,
    run_train_feasibility,
    validate_evaluation_input_plan,
)
from night_schedule_plan import build_night_schedule_plan, validate_night_schedule_plan  # noqa: E402


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _market_row(
    *,
    run_id: str,
    cycle: int,
    timestamp: str,
    venue: str,
    base: str,
    mid: float,
) -> dict:
    spread_bps = 10.0
    half = spread_bps / 20_000.0
    return {
        "run_id": run_id,
        "cycle": cycle,
        "snapshot_ts": timestamp,
        "exchange": venue,
        "symbol": f"{base}_USDT",
        "base": base,
        "quote": "USDT",
        "contract_type": "linear_perp",
        "volume_24h_quote": 1_000_000.0,
        "bid_price": mid * (1.0 - half),
        "ask_price": mid * (1.0 + half),
        "mid_price": mid,
        "spread_bps": spread_bps,
        "binance_spot_listed": False,
        "eligible_non_binance_spot": True,
        "observed_now": True,
        "tombstone": False,
        "presence_state": "observed",
        "funding_rate": 0.0001,
        "funding_interval_sec": 28_800,
        "funding_next_apply_ts": None,
        "mark_price": mid,
        "index_price": mid,
        "contract_multiplier": 1.0,
        "minimum_order_size": 0.001,
        "maximum_order_size": 1_000_000.0,
        "price_tick": 0.001,
        "quantity_step": 0.001,
        "bid_size_contracts": 100_000.0,
        "ask_size_contracts": 100_000.0,
    }


def _segment_rows(index: int, scheduled_date: str) -> tuple[list[dict], list[dict]]:
    run_id = f"segment-{index:03d}"
    block = index // 7
    phase = index % 7
    bases = [f"X{block:03d}_{offset}" for offset in range(4)]
    snapshots: list[dict] = []
    cycles: list[dict] = []
    start = datetime.fromisoformat(f"{scheduled_date}T00:00:00+00:00")
    for cycle in range(1, 5):
        timestamp = (start + timedelta(minutes=5 * cycle)).isoformat()
        markets: list[tuple[str, str, float]] = []
        for offset, base in enumerate(bases):
            activation = "mexc" if offset % 2 == 0 else "gateio"
            reference = "gateio" if activation == "mexc" else "mexc"
            if phase <= 1:
                markets.append((reference, base, 100.0))
            elif phase <= 5:
                markets.extend(((reference, base, 100.0), (activation, base, 102.0)))
            else:
                markets.extend(((reference, base, 101.0), (activation, base, 101.0)))
        for venue, base, mid in markets:
            snapshots.append(
                _market_row(
                    run_id=run_id,
                    cycle=cycle,
                    timestamp=timestamp,
                    venue=venue,
                    base=base,
                    mid=mid,
                )
            )
        cycles.append(
            {
                "run_id": run_id,
                "cycle": cycle,
                "cycle_started_at_utc": timestamp,
                "cycle_finished_at_utc": timestamp,
                "decision": "accepted",
                "source_rows": len(markets),
                "output_rows": len(markets),
                "errors": {},
                "successful_exchanges": ["mexc", "gateio"],
            }
        )
    return snapshots, cycles


class PitMembershipDriftPipelineTests(unittest.TestCase):
    def _dataset(
        self,
        root: Path,
        *,
        invalid_oos_json: bool = False,
        days: int = 120,
    ) -> tuple[Path, Path, dict]:
        contract = build_pit_membership_drift_contract()
        bank = root / "bank.json"
        _write_json(
            bank,
            {
                "version": "fixture-v1",
                "hypotheses": [
                    {
                        "id": contract["id"],
                        "status": "BANKED_NEEDS_NEW_DATA",
                        "required_data_type": contract["required_data_type"],
                        "minimum_data": {
                            "days": 120,
                            "train_eligibility_days": 20,
                            "oos_closed_days": 100,
                            "portfolio_events": 20,
                            "per_venue_events": 10,
                            "unique_dates": 10,
                        },
                        "contract": contract,
                    }
                ],
            },
        )
        entries: list[dict] = []
        first_day = date(2026, 1, 1)
        for index in range(days):
            scheduled_date = (first_day + timedelta(days=index)).isoformat()
            run_id = f"segment-{index:03d}"
            segment_root = root / "segments" / run_id
            plan_path = segment_root / "schedule.json"
            snapshots_path = segment_root / "snapshots.jsonl"
            cycles_path = segment_root / "cycles.jsonl"
            manifest_path = segment_root / "manifest.json"
            _write_json(plan_path, {"run_id": run_id, "scheduled_date": scheduled_date})
            snapshots, cycles = _segment_rows(index, scheduled_date)
            if invalid_oos_json and index >= 20:
                snapshots_path.parent.mkdir(parents=True, exist_ok=True)
                snapshots_path.write_text("this is deliberately not json\n", encoding="utf-8")
            else:
                _write_jsonl(snapshots_path, snapshots)
            _write_jsonl(cycles_path, cycles)
            _write_json(
                manifest_path,
                {
                    "schema": "pit_universe_snapshot_manifest_v2",
                    "run_id": run_id,
                    "final": True,
                    "snapshots_path": str(snapshots_path.resolve()),
                    "cycles_path": str(cycles_path.resolve()),
                },
            )
            body = {
                "schema": "pit_universe_v2_quality_certification_v1",
                "track_key": f"{contract['id']}|{contract['required_data_type']}",
                "hypothesis_id": contract["id"],
                "data_type": contract["required_data_type"],
                "hypothesis_contract_sha256": contract["contract_hash"],
                "plan_path": str(plan_path.resolve()),
                "plan_hash": _canonical_hash({"run_id": run_id, "scheduled_date": scheduled_date}),
                "plan_file_sha256": _file_hash(plan_path),
                "segment_sequence": index + 1,
                "segment_run_id": run_id,
                "scheduled_date": scheduled_date,
                "manifest_path": str(manifest_path.resolve()),
                "manifest_sha256": _file_hash(manifest_path),
                "snapshots_path": str(snapshots_path.resolve()),
                "snapshots_sha256": _file_hash(snapshots_path),
                "cycles_path": str(cycles_path.resolve()),
                "cycles_sha256": _file_hash(cycles_path),
                "technical_quality_accepted": True,
                "reasons": [],
                "returns_read": False,
                "pnl_read": False,
            }
            entries.append({**body, "certification_id": _canonical_hash(body)})
        ledger = root / "quality-ledger.jsonl"
        _write_jsonl(ledger, entries)
        return bank, ledger, contract

    def _train_plan(
        self,
        root: Path,
        *,
        invalid_oos_json: bool = False,
        days: int = 120,
    ) -> tuple[Path, dict, Path, Path, dict]:
        bank, ledger, contract = self._dataset(root, invalid_oos_json=invalid_oos_json, days=days)
        output = root / "train-input-plan.json"
        result = build_evaluation_input_plan(
            quality_ledger_path=ledger,
            hypothesis_bank_path=bank,
            hypothesis_id=contract["id"],
            output_path=output,
            created_at_utc="2026-07-14T16:30:00+00:00",
            plan_stage="train_feasibility",
        )
        return output, result, bank, ledger, contract

    def _full_plan(self, root: Path, *, invalid_oos_json: bool = False) -> tuple[Path, dict, Path]:
        train_path, train_plan, bank, ledger, contract = self._train_plan(
            root,
            invalid_oos_json=invalid_oos_json,
        )
        feasibility_path = root / "feasibility.json"
        run_train_feasibility(
            train_path,
            expected_plan_hash=train_plan["plan_hash"],
            output_path=feasibility_path,
        )
        output = root / "full-input-plan.json"
        result = build_evaluation_input_plan(
            quality_ledger_path=ledger,
            hypothesis_bank_path=bank,
            hypothesis_id=contract["id"],
            output_path=output,
            created_at_utc="2026-07-14T16:31:00+00:00",
            plan_stage="full_evaluation",
            train_plan_path=train_path,
            feasibility_path=feasibility_path,
        )
        return output, result, feasibility_path

    def test_train_plan_can_run_feasibility_after_20_dates_without_waiting_for_oos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan, _, _, _ = self._train_plan(root, days=20)
            validation = validate_evaluation_input_plan(plan_path, plan["plan_hash"])
            result = run_train_feasibility(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "feasibility-20d.json",
            )

        self.assertEqual(validation["plan_stage"], "train_feasibility")
        self.assertEqual(validation["train_dates"], 20)
        self.assertEqual(validation["oos_dates"], 0)
        self.assertEqual(result["oos_dates_read"], 0)
        self.assertIn("-Action fast-edge-pit-feasibility", plan["next_allowed_command"])
        self.assertIn(plan["plan_hash"], plan["next_allowed_command"])

    def test_plan_seals_earliest_120_dates_without_reading_market_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path, result, _ = self._full_plan(Path(temp_dir), invalid_oos_json=True)
            validation = validate_evaluation_input_plan(plan_path, result["plan_hash"])

        self.assertEqual(result["decision"], "READY_FOR_OOS_EVALUATION")
        self.assertEqual(validation["plan_stage"], "full_evaluation")
        self.assertEqual(validation["train_dates"], 20)
        self.assertEqual(validation["oos_dates"], 100)
        self.assertFalse(result["forward_market_rows_read"])
        self.assertFalse(result["oos_returns_read"])
        self.assertEqual(len(result["input_merkle_root"]), 64)

    def test_train_feasibility_does_not_read_deliberately_invalid_oos_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan, _, _, _ = self._train_plan(root, invalid_oos_json=True)
            output = root / "feasibility.json"
            result = run_train_feasibility(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
            )

        self.assertEqual(result["verdict"], "FEASIBLE_FOR_OOS")
        self.assertEqual(result["train_dates_read"], 20)
        self.assertEqual(result["oos_dates_read"], 0)
        self.assertFalse(result["returns_read"])
        self.assertFalse(result["pnl_computed"])
        self.assertEqual(result["next_allowed_action"], "build_oos_accrual_schedule_planonly")
        self.assertIn("-Action fast-edge-night-schedule-plan", result["next_allowed_command"])
        self.assertIn("-ScheduleCollectionStage 'oos_accrual'", result["next_allowed_command"])

    def test_oos_collection_schedule_requires_and_seals_passed_train_feasibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            train_path, train_plan, bank, ledger, contract = self._train_plan(root, days=20)
            feasibility_path = root / "feasibility.json"
            feasibility = run_train_feasibility(
                train_path,
                expected_plan_hash=train_plan["plan_hash"],
                output_path=feasibility_path,
            )
            goal = root / "goal.md"
            goal.write_text("# Goal fixture\n", encoding="utf-8")
            schedule_path = root / "oos-schedule.json"

            result = build_night_schedule_plan(
                hypothesis_bank_path=bank,
                hypothesis_id=contract["id"],
                data_type=contract["required_data_type"],
                goal_path=goal,
                output_path=schedule_path,
                schedule_start_date="2026-07-14",
                nights=14,
                output_root=str(root / "oos-data"),
                collection_stage="oos_accrual",
                quality_ledger_path=ledger,
                train_plan_path=train_path,
                feasibility_path=feasibility_path,
            )
            validation = validate_night_schedule_plan(schedule_path, result["plan_hash"])
            stage = json.loads(schedule_path.read_text(encoding="utf-8"))["sealed_schedule"][
                "collection_stage"
            ]

        self.assertEqual(feasibility["verdict"], "FEASIBLE_FOR_OOS")
        self.assertEqual(validation["collection_stage"], "oos_accrual")
        self.assertEqual(stage["initial_accepted_distinct_dates"], 20)
        self.assertEqual(stage["stage_target_distinct_dates"], 120)
        self.assertEqual(stage["maximum_new_accepted_dates"], 100)
        self.assertEqual(stage["upstream_train_feasibility"]["verdict"], "FEASIBLE_FOR_OOS")

    def test_oos_collection_schedule_without_feasibility_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, _, bank, ledger, contract = self._train_plan(root, days=20)
            goal = root / "goal.md"
            goal.write_text("# Goal fixture\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "requires train_plan_path and feasibility_path"):
                build_night_schedule_plan(
                    hypothesis_bank_path=bank,
                    hypothesis_id=contract["id"],
                    data_type=contract["required_data_type"],
                    goal_path=goal,
                    output_path=root / "invalid-oos-schedule.json",
                    schedule_start_date="2026-07-14",
                    nights=14,
                    output_root=str(root / "oos-data"),
                    collection_stage="oos_accrual",
                    quality_ledger_path=ledger,
                )

    def test_oos_requires_hash_bound_feasibility_and_repeats_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan, feasibility_path = self._full_plan(root)
            output = root / "evaluation.json"
            result = run_oos_evaluation(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                feasibility_path=feasibility_path,
                output_path=output,
            )
            strict_payload = json.loads(
                output.read_text(encoding="utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )

        self.assertEqual(result["verdict"], "ACCEPT_FOR_SHORT_EXECUTION_PROBE")
        self.assertTrue(result["deterministic_repeats_match"])
        self.assertEqual(result["deterministic_repeats"], 2)
        self.assertEqual(result["metrics"]["oos_closed_days"], 100)
        self.assertGreaterEqual(result["metrics"]["event_count"], 20)
        self.assertEqual(len(result["git_head_sha256"]), 40)
        self.assertIn("python_version", result["runtime_versions"])
        self.assertIn("schedules", result["fee_provenance"])
        self.assertEqual(len(result["input_artifact_hashes"]), 120)
        self.assertEqual(len(result["split"]["walk_forward_folds"]), 5)
        self.assertFalse(result["paper_forward_allowed"])
        self.assertFalse(result["live_orders"])
        self.assertEqual(
            result["next_allowed_command"],
            "REQUEST_EXPLICIT_USER_APPROVAL_FOR_PIT_SHORT_EXECUTION_PROBE_PLANONLY",
        )
        self.assertEqual(strict_payload["deterministic_result_hash"], result["deterministic_result_hash"])

    def test_duplicate_accepted_certification_for_one_date_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank, ledger, contract = self._dataset(root)
            plan_path = root / "sealed-input-plan.json"
            sealed = build_evaluation_input_plan(
                quality_ledger_path=ledger,
                hypothesis_bank_path=bank,
                hypothesis_id=contract["id"],
                output_path=plan_path,
                plan_stage="train_feasibility",
            )
            entries = ledger.read_text(encoding="utf-8").splitlines()
            duplicate = json.loads(entries[0])
            body = {key: value for key, value in duplicate.items() if key != "certification_id"}
            body["segment_run_id"] = "conflicting-run"
            duplicate = {**body, "certification_id": _canonical_hash(body)}
            with ledger.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(duplicate, separators=(",", ":")) + "\n")

            with self.assertRaisesRegex(ValueError, "duplicate accepted certification date"):
                validate_evaluation_input_plan(plan_path, sealed["plan_hash"])
            with self.assertRaisesRegex(ValueError, "duplicate accepted certification date"):
                build_evaluation_input_plan(
                    quality_ledger_path=ledger,
                    hypothesis_bank_path=bank,
                    hypothesis_id=contract["id"],
                    output_path=root / "second-input-plan.json",
                    plan_stage="train_feasibility",
                )

    def test_plan_rejects_tampered_next_command_outside_sealed_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, result, _, _, _ = self._train_plan(root, days=20)
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["next_allowed_command"] = "Invoke-UnsafeRetune"
            _write_json(plan_path, payload)

            with self.assertRaisesRegex(ValueError, "next_allowed_command mismatch"):
                validate_evaluation_input_plan(plan_path, result["plan_hash"])


if __name__ == "__main__":
    unittest.main()
