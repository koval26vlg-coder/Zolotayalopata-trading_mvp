from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402
from pit_membership_drift_futility import (  # noqa: E402
    build_futility_plan,
    evaluate_futility_plan,
    poisson_upper_mean,
    project_futility_bounds,
    validate_futility_plan,
)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


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
    phase = index % 4
    base = f"X{index // 4:03d}"
    snapshots: list[dict] = []
    cycles: list[dict] = []
    start = datetime.fromisoformat(f"{scheduled_date}T00:00:00+00:00")
    for cycle in range(1, 5):
        timestamp = (start + timedelta(minutes=5 * cycle)).isoformat()
        markets: list[tuple[str, str, float]] = []
        if phase == 0:
            markets.append(("gateio", base, 100.0))
        elif phase in (1, 2):
            markets.extend((("gateio", base, 100.0), ("mexc", base, 102.0)))
        else:
            markets.extend((("gateio", base, 101.0), ("mexc", base, 101.0)))
        for venue, market_base, mid in markets:
            snapshots.append(
                _market_row(
                    run_id=run_id,
                    cycle=cycle,
                    timestamp=timestamp,
                    venue=venue,
                    base=market_base,
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


def _dataset(root: Path, *, days: int = 10, corrupt_rows: bool = False) -> tuple[Path, Path, dict]:
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
        if corrupt_rows:
            snapshots_path.parent.mkdir(parents=True, exist_ok=True)
            snapshots_path.write_text("not-json\n", encoding="utf-8")
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


class PitMembershipDriftFutilityTests(unittest.TestCase):
    def test_exact_poisson_upper_mean_for_zero_events(self) -> None:
        self.assertAlmostEqual(poisson_upper_mean(0, confidence=0.90), 2.302585093, places=8)

    def test_optimistic_projection_can_close_only_when_upper_bound_misses_gate(self) -> None:
        projection = project_futility_bounds(
            checkpoint_days=10,
            oos_days=100,
            candidate_events=100,
            valid_events=0,
            candidate_events_by_venue={"mexc": 50, "gateio": 50},
            valid_events_by_venue={"mexc": 0, "gateio": 0},
            valid_event_dates=0,
            minimum_total_events=20,
            minimum_events_per_venue=10,
            minimum_unique_dates=10,
            venues=("mexc", "gateio"),
        )

        self.assertEqual(projection["verdict"], "FUTILE_CLOSE_BRANCH_BEFORE_TRAIN")
        self.assertIn("optimistic_oos_event_upper_below_minimum", projection["reasons"])

    def test_plan_requires_ten_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank, ledger, contract = _dataset(root, days=9)

            with self.assertRaisesRegex(ValueError, "insufficient futility quality dates"):
                build_futility_plan(
                    quality_ledger_path=ledger,
                    hypothesis_bank_path=bank,
                    hypothesis_id=contract["id"],
                    output_path=root / "futility-plan.json",
                )

    def test_plan_seals_rows_without_reading_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank, ledger, contract = _dataset(root, corrupt_rows=True)
            output = root / "futility-plan.json"

            result = build_futility_plan(
                quality_ledger_path=ledger,
                hypothesis_bank_path=bank,
                hypothesis_id=contract["id"],
                output_path=output,
                created_at_utc="2026-07-17T00:00:00+00:00",
            )
            validation = validate_futility_plan(output, result["plan_hash"])

            self.assertEqual(validation["selected_dates"], 10)
            self.assertFalse(result["forward_market_rows_read"])
            with self.assertRaisesRegex(ValueError, "invalid JSONL"):
                evaluate_futility_plan(
                    output,
                    expected_plan_hash=result["plan_hash"],
                    output_path=root / "futility-result.json",
                )

    def test_evaluation_is_deterministic_and_never_reads_returns_or_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank, ledger, contract = _dataset(root)
            plan_path = root / "futility-plan.json"
            plan = build_futility_plan(
                quality_ledger_path=ledger,
                hypothesis_bank_path=bank,
                hypothesis_id=contract["id"],
                output_path=plan_path,
                created_at_utc="2026-07-17T00:00:00+00:00",
            )
            first_path = root / "futility-result-1.json"
            second_path = root / "futility-result-2.json"

            first = evaluate_futility_plan(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=first_path,
                created_at_utc="2026-07-17T00:01:00+00:00",
            )
            second = evaluate_futility_plan(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=second_path,
                created_at_utc="2026-07-17T00:02:00+00:00",
            )

            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertTrue(first["forward_market_rows_read"])
            self.assertFalse(first["returns_read"])
            self.assertFalse(first["pnl_computed"])
            self.assertFalse(first["oos_metrics_computed"])
            self.assertEqual(first["checkpoint_dates_read"], 10)
            self.assertIn(
                first["verdict"],
                {"FUTILE_CLOSE_BRANCH_BEFORE_TRAIN", "CONTINUE_TO_20_DATE_TRAIN_GATE"},
            )


if __name__ == "__main__":
    unittest.main()
