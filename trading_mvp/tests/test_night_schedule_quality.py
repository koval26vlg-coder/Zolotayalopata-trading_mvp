from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from night_schedule_plan import build_night_schedule_plan  # noqa: E402
from night_schedule_quality import certify_night_schedule_quality  # noqa: E402
from night_schedule_quality_dry_run import (  # noqa: E402
    _validate_ledger_contract,
    certify_night_schedule_quality_dry_run,
)
from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _snapshot_row(
    run_id: str,
    cycle: int,
    exchange: str,
    symbol: str,
    ts: str,
    first_seen_ts: str,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "cycle": cycle,
        "snapshot_ts": ts,
        "exchange": exchange,
        "symbol": symbol,
        "base": symbol.replace("_USDT", "").replace("USDT", ""),
        "quote": "USDT",
        "contract_type": "linear_perp",
        "status": "trading",
        "listed_now": True,
        "inactive_or_delisted": False,
        "volume_24h_quote": 1000.0,
        "bid_price": 9.99,
        "ask_price": 10.01,
        "mid_price": 10.0,
        "spread_bps": 20.0,
        "bid_size_contracts": 1000.0,
        "ask_size_contracts": 1000.0,
        "liquidity_proxy_source": "fixture",
        "mark_price": 10.0,
        "index_price": 10.0,
        "funding_rate": 0.0001,
        "funding_interval_sec": 28_800,
        "funding_next_apply_ts": None,
        "contract_multiplier": 1.0,
        "minimum_order_size": 0.001,
        "maximum_order_size": 1_000_000.0,
        "price_tick": 0.001,
        "quantity_step": 0.001,
        "binance_spot_listed": False,
        "excluded_by_binance_spot": False,
        "eligible_non_binance_spot": True,
        "binance_reference_ts": ts,
        "source_endpoint": "fixture",
        "raw_status": "trading",
        "first_seen_ts": first_seen_ts,
        "last_seen_ts": ts,
        "missing_since_ts": None,
        "observed_now": True,
        "tombstone": False,
        "presence_state": "observed",
    }


class NightScheduleQualityTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        nights: int = 2,
        schedule_start_date: str = "2026-07-14",
        quality_ledger_path: Path | None = None,
    ) -> tuple[Path, str, dict, Path]:
        bank = root / "bank.json"
        _write_json(
            bank,
            {
                "version": "fixture-v1",
                "hypotheses": [
                    {
                        "id": "pit_universe_membership_drift_reversion_v1",
                        "status": "BANKED_NEEDS_NEW_DATA",
                        "required_data_type": "PIT_UNIVERSE_V2_FORWARD",
                        "contract": build_pit_membership_drift_contract(),
                        "minimum_data": {
                            "days": 120,
                            "portfolio_events": 20,
                            "per_venue_events": 10,
                            "unique_dates": 10,
                        },
                    }
                ],
            },
        )
        goal = root / "goal.md"
        goal.write_text("# Goal fixture\n", encoding="utf-8")
        plan_path = root / "schedule.json"
        sealed_ledger_path = quality_ledger_path or (root / "quality-ledger.jsonl")
        built = build_night_schedule_plan(
            hypothesis_bank_path=bank,
            hypothesis_id="pit_universe_membership_drift_reversion_v1",
            data_type="PIT_UNIVERSE_V2_FORWARD",
            goal_path=goal,
            output_path=plan_path,
            schedule_start_date=schedule_start_date,
            nights=nights,
            segment_start_local="23:00",
            segment_duration_sec=1200,
            interval_sec=300,
            output_root=str(root / "data"),
            quality_ledger_path=sealed_ledger_path,
            created_at_utc="2026-07-14T13:00:00+00:00",
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        approval_root = root / "approvals"
        _write_json(
            approval_root / f"{built['plan_hash']}.approval.json",
            {
                "schema": "trading_mvp_night_schedule_approval_v1",
                "status": "ACTIVE",
                "approved_at": f"{schedule_start_date}T17:00:00+03:00",
                "expires_at": plan["segments"][-1]["hard_deadline_local"],
                "approved_by": "User",
                "approval_scope": "one frozen schedule; no auto-resume; no OOS/grid/paper/live/API keys",
                "plan_path": str(plan_path.resolve()),
                "plan_hash": built["plan_hash"],
                "plan_file_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                "data_type": "PIT_UNIVERSE_V2_FORWARD",
                "segment_run_ids": [item["run_id"] for item in plan["segments"]],
                "visible_terminal_required": True,
                "data_embargo": True,
                "auto_resume_allowed": False,
            },
        )
        return plan_path, built["plan_hash"], plan, approval_root

    def _complete_segment(
        self,
        plan: dict,
        sequence: int,
        *,
        thin_cycle: int | None = None,
        time_shift_days: int = 0,
        time_shift_minutes: int = 0,
    ) -> Path:
        segment = plan["segments"][sequence - 1]
        run_id = segment["run_id"]
        run_dir = Path(plan["output_root"]) / run_id
        snapshots: list[dict] = []
        cycles: list[dict] = []
        segment_start = datetime.fromisoformat(segment["start_local"]).astimezone(timezone.utc)
        observed_start = segment_start + timedelta(
            days=time_shift_days,
            minutes=time_shift_minutes,
        )
        first_seen_ts = (observed_start + timedelta(minutes=1)).isoformat()
        for cycle in range(1, segment["expected_cycles_floor"] + 1):
            ts = (observed_start + timedelta(minutes=cycle)).isoformat()
            exchanges = ["mexc"] if thin_cycle == cycle else ["mexc", "gateio"]
            for exchange in exchanges:
                symbol = "AAA_USDT" if exchange == "mexc" else "BBB_USDT"
                snapshots.append(_snapshot_row(run_id, cycle, exchange, symbol, ts, first_seen_ts))
            errors = {"gateio": "Read timed out"} if thin_cycle == cycle else {}
            cycles.append(
                {
                    "run_id": run_id,
                    "cycle": cycle,
                    "cycle_started_at_utc": ts,
                    "cycle_finished_at_utc": ts,
                    "decision": "accepted" if not errors else "rejected",
                    "source_rows": len(exchanges),
                    "output_rows": len(exchanges),
                    "errors": errors,
                    "successful_exchanges": exchanges,
                }
            )
        snapshots_path = run_dir / "snapshots.jsonl"
        cycles_path = run_dir / "cycles.jsonl"
        _write_jsonl(snapshots_path, snapshots)
        _write_jsonl(cycles_path, cycles)
        manifest_path = run_dir / "manifest.json"
        _write_json(
            manifest_path,
            {
                "schema": "pit_universe_snapshot_manifest_v2",
                "mode": "pit_universe_snapshot_collect",
                "run_id": run_id,
                "started_at_utc": observed_start.isoformat(),
                "updated_at_utc": (observed_start + timedelta(minutes=20)).isoformat(),
                "finished_at_utc": (observed_start + timedelta(minutes=20)).isoformat(),
                "stopped_at_utc": None,
                "final": True,
                "incomplete": False,
                "status": "COMPLETED",
                "stop_condition": "duration_sec",
                "stop_reason": None,
                "duration_sec": segment["duration_sec"],
                "interval_sec": segment["interval_sec"],
                "timeout_sec": 10,
                "min_contracts_per_exchange": 50,
                "cycle_count": len(cycles),
                "rows_total": len(snapshots),
                "errors_total": sum(len(item["errors"]) for item in cycles),
                "snapshots_path": str(snapshots_path),
                "cycles_path": str(cycles_path),
                "last_successful_exchanges": cycles[-1]["successful_exchanges"],
            },
        )
        return manifest_path

    def test_accepted_segment_appends_hash_bound_partial_certification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1)
            ledger_path = root / "quality-ledger.jsonl"
            report = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(report["decision"], "PARTIAL_PIT_QUALITY_CERTIFIED")
        self.assertEqual(report["segments_evaluated"], 1)
        self.assertEqual(report["segments_accepted"], 1)
        self.assertEqual(report["ledger"]["entries_appended"], 1)
        self.assertEqual(report["ledger"]["accepted_distinct_dates"], 1)
        self.assertEqual(report["ledger"]["required_distinct_days"], 120)
        self.assertEqual(report["ledger"]["train_feasibility_required_days"], 20)
        self.assertFalse(report["train_feasibility_gate_satisfied"])
        self.assertFalse(report["minimum_data_gate_satisfied"])
        self.assertFalse(report["oos_allowed"])
        self.assertTrue(report["technical_market_rows_read"])
        self.assertFalse(report["returns_read"])
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["technical_quality_accepted"])
        self.assertEqual(
            entries[0]["hypothesis_contract_sha256"],
            build_pit_membership_drift_contract()["contract_hash"],
        )
        self.assertEqual(len(entries[0]["certification_id"]), 64)

    def test_dry_run_certifies_without_writing_the_quality_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1)
            ledger_path = root / "quality-ledger.jsonl"
            report = certify_night_schedule_quality_dry_run(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
                output_path=root / "dry-run.json",
            )

        self.assertFalse(ledger_path.exists())
        self.assertEqual(report["decision"], "PIT_SEGMENT_QUALITY_DRY_RUN_ACCEPTED")
        self.assertFalse(report["ledger"]["write_requested"])
        self.assertEqual(report["ledger"]["entries_appended"], 0)
        self.assertEqual(report["ledger"]["total_entries"], 0)
        self.assertEqual(report["ledger"]["projected_total_entries"], 1)
        self.assertEqual(report["ledger"]["accepted_distinct_dates"], 0)
        self.assertEqual(report["ledger"]["projected_accepted_distinct_dates"], 1)
        self.assertFalse(report["train_feasibility_gate_satisfied"])
        self.assertFalse(report["projected_train_feasibility_gate_satisfied"])
        self.assertTrue(report["commit_required"])

    def test_thin_exchange_cycle_is_rejected_and_preserved_in_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1, thin_cycle=2)
            ledger_path = root / "quality-ledger.jsonl"
            report = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            entry = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(report["decision"], "PIT_SEGMENT_QUALITY_REJECTED")
        self.assertEqual(report["segments_rejected"], 1)
        self.assertEqual(report["ledger"]["accepted_distinct_dates"], 0)
        self.assertIn("insufficient_exchange_coverage", entry["reasons"])
        self.assertFalse(entry["technical_quality_accepted"])
        self.assertFalse(report["oos_allowed"])

    def test_segment_outside_approved_night_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1, time_shift_days=-1)
            ledger_path = root / "quality-ledger.jsonl"
            report = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            entry = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(report["decision"], "PIT_SEGMENT_QUALITY_REJECTED")
        self.assertFalse(entry["technical_quality_accepted"])
        self.assertIn("segment_time_bounds_mismatch", entry["reasons"])

    def test_late_start_before_hard_deadline_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1, time_shift_minutes=130)
            ledger_path = root / "quality-ledger.jsonl"
            report = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            entry = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(report["decision"], "PARTIAL_PIT_QUALITY_CERTIFIED")
        self.assertTrue(entry["technical_quality_accepted"])
        self.assertNotIn("segment_time_bounds_mismatch", entry["reasons"])

    def test_artifacts_after_hard_deadline_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1, time_shift_minutes=600)
            ledger_path = root / "quality-ledger.jsonl"
            report = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T10:00:00+03:00",
            )
            entry = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(report["decision"], "PIT_SEGMENT_QUALITY_REJECTED")
        self.assertFalse(entry["technical_quality_accepted"])
        self.assertIn("segment_time_bounds_mismatch", entry["reasons"])

    def test_ledger_accumulates_distinct_dates_across_schedule_tranches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_plan, first_hash, first_payload, first_approvals = self._fixture(
                root / "first",
                nights=1,
                schedule_start_date="2026-07-14",
                quality_ledger_path=root / "quality-ledger.jsonl",
            )
            second_plan, second_hash, second_payload, second_approvals = self._fixture(
                root / "second",
                nights=1,
                schedule_start_date="2026-07-15",
                quality_ledger_path=root / "quality-ledger.jsonl",
            )
            self._complete_segment(first_payload, 1)
            self._complete_segment(second_payload, 1)
            ledger_path = root / "quality-ledger.jsonl"
            certify_night_schedule_quality(
                first_plan,
                first_hash,
                approval_record_root=first_approvals,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            report = certify_night_schedule_quality(
                second_plan,
                second_hash,
                approval_record_root=second_approvals,
                ledger_path=ledger_path,
                now="2026-07-16T08:00:00+03:00",
            )

        self.assertEqual(report["ledger"]["total_entries"], 2)
        self.assertEqual(report["ledger"]["accepted_distinct_dates"], 2)
        self.assertEqual(
            report["ledger"]["accepted_distinct_date_values"],
            ["2026-07-14", "2026-07-15"],
        )

    def test_same_track_with_different_contract_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(
                root,
                nights=1,
            )
            self._complete_segment(plan, 1)
            ledger_path = root / "quality-ledger.jsonl"
            certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            entry = json.loads(ledger_path.read_text(encoding="utf-8").strip())
            entry["hypothesis_contract_sha256"] = "f" * 64
            body = {key: value for key, value in entry.items() if key != "certification_id"}
            entry["certification_id"] = hashlib.sha256(
                json.dumps(
                    body,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            _write_jsonl(ledger_path, [entry])

            with self.assertRaisesRegex(
                ValueError,
                "another hypothesis/data/contract track",
            ):
                _validate_ledger_contract([entry], plan)

            operations = (
                certify_night_schedule_quality,
                certify_night_schedule_quality_dry_run,
            )
            for operation in operations:
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(
                        ValueError,
                        "hypothesis contract hash mismatch|another hypothesis/data/contract track",
                    ):
                        operation(
                            plan_path,
                            plan_hash,
                            approval_record_root=approval_root,
                            ledger_path=ledger_path,
                            now="2026-07-15T08:00:00+03:00",
                        )

    def test_twenty_dates_stop_accrual_for_train_feasibility_before_oos_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_plan, first_hash, first_payload, first_approvals = self._fixture(
                root / "first",
                nights=14,
                schedule_start_date="2026-07-14",
                quality_ledger_path=root / "quality-ledger.jsonl",
            )
            second_plan, second_hash, second_payload, second_approvals = self._fixture(
                root / "second",
                nights=6,
                schedule_start_date="2026-07-28",
                quality_ledger_path=root / "quality-ledger.jsonl",
            )
            for sequence in range(1, 15):
                self._complete_segment(first_payload, sequence)
            for sequence in range(1, 7):
                self._complete_segment(second_payload, sequence)
            ledger_path = root / "quality-ledger.jsonl"
            certify_night_schedule_quality(
                first_plan,
                first_hash,
                approval_record_root=first_approvals,
                ledger_path=ledger_path,
                now="2026-07-28T08:00:00+03:00",
            )
            report = certify_night_schedule_quality(
                second_plan,
                second_hash,
                approval_record_root=second_approvals,
                ledger_path=ledger_path,
                now="2026-08-03T08:00:00+03:00",
            )

        self.assertEqual(report["decision"], "PIT_TRAIN_FEASIBILITY_DAYS_REACHED")
        self.assertTrue(report["train_feasibility_gate_satisfied"])
        self.assertFalse(report["minimum_data_gate_satisfied"])
        self.assertFalse(report["oos_allowed"])
        self.assertEqual(
            report["next_allowed_action"],
            "build_train_feasibility_input_plan_and_run_train_feasibility_before_more_accrual",
        )

    def test_repeated_certification_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1)
            ledger_path = root / "quality-ledger.jsonl"
            first = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            second = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            lines = ledger_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(first["ledger"]["entries_appended"], 1)
        self.assertEqual(second["ledger"]["entries_appended"], 0)
        self.assertEqual(len(lines), 1)

    def test_tampered_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            self._complete_segment(plan, 1)
            ledger_path = root / "quality-ledger.jsonl"
            certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )
            entry = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])
            entry["rows"] += 1
            _write_jsonl(ledger_path, [entry])

            with self.assertRaisesRegex(ValueError, "certification_id mismatch"):
                certify_night_schedule_quality(
                    plan_path,
                    plan_hash,
                    approval_record_root=approval_root,
                    ledger_path=ledger_path,
                    now="2026-07-15T08:00:00+03:00",
                )

    def test_missing_approval_reads_no_market_rows_and_writes_no_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan, approval_root = self._fixture(root)
            (approval_root / f"{plan_hash}.approval.json").unlink()
            self._complete_segment(plan, 1)
            ledger_path = root / "quality-ledger.jsonl"
            report = certify_night_schedule_quality(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                ledger_path=ledger_path,
                now="2026-07-15T08:00:00+03:00",
            )

        self.assertEqual(report["decision"], "AWAIT_EXPLICIT_SCHEDULE_APPROVAL")
        self.assertFalse(report["technical_market_rows_read"])
        self.assertFalse(ledger_path.exists())
        self.assertFalse(report["oos_allowed"])

    def test_quality_certification_rejects_unsealed_ledger_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, _, approval_root = self._fixture(root)

            with self.assertRaisesRegex(ValueError, "differs from the sealed collection stage"):
                certify_night_schedule_quality(
                    plan_path,
                    plan_hash,
                    approval_record_root=approval_root,
                    ledger_path=root / "bypass-ledger.jsonl",
                    now="2026-07-15T08:00:00+03:00",
                )

    def test_run_mvp_exposes_quality_action_as_short_local_postprocess(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, _plan, approval_root = self._fixture(root)
            (approval_root / f"{plan_hash}.approval.json").unlink()
            ledger_path = root / "quality-ledger.jsonl"
            output_path = root / "quality-report.json"
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REPO_ROOT / "trading_mvp" / "run_mvp.ps1"),
                    "-Action",
                    "fast-edge-night-schedule-quality",
                    "-PlanPath",
                    str(plan_path),
                    "-ExpectedPlanHash",
                    plan_hash,
                    "-ApprovalRecordRoot",
                    str(approval_root),
                    "-QualityLedgerPath",
                    str(ledger_path),
                    "-OutputPath",
                    str(output_path),
                    "-MaxRuntimeSec",
                    "300",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload.get("decision"), "AWAIT_EXPLICIT_SCHEDULE_APPROVAL")
        self.assertFalse(payload.get("technical_market_rows_read", True))
        self.assertFalse(payload.get("oos_allowed", True))
        self.assertFalse(ledger_path.exists())


if __name__ == "__main__":
    unittest.main()
