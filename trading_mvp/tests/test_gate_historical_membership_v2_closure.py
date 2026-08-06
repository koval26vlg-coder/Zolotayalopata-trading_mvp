from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_historical_membership_v2 import build_plan, run_probe  # noqa: E402
from gate_historical_membership_v2_closure import (  # noqa: E402
    BRANCH_STATUS,
    VERDICT,
    build_source_reject_closure,
    diagnose_source_rows,
    validate_closure_manifest,
)


def _write_daily_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "daily_fixture",
                "params": {"exchanges": ["mexc", "gateio"], "days": 220},
                "statuses": [],
            }
        ),
        encoding="utf-8",
    )


def _raw_contract(index: int, *, delisted: bool = False, with_end: bool = True) -> dict:
    row = {
        "name": f"A{index:03d}_USDT",
        "type": "direct",
        "contract_type": "crypto",
        "status": "delisted" if delisted else "trading",
        "create_time": 1_600_000_000 + index,
        "launch_time": 1_600_000_100 + index,
        "in_delisting": delisted,
        "position_size": "0" if delisted else "100",
        "quanto_multiplier": "0.01",
        "funding_interval": 28_800,
        "order_size_min": 1,
        "order_size_max": 1_000_000,
    }
    if delisted and with_end:
        row["delisted_time"] = 1_700_000_000 + index
    return row


class GateHistoricalMembershipV2ClosureTests(unittest.TestCase):
    def _source_reject_fixture(self, root: Path) -> tuple[Path, Path]:
        daily = root / "daily.json"
        plan_path = root / "plan.json"
        probe_path = root / "probe.json"
        _write_daily_manifest(daily)
        plan = build_plan(
            daily_manifest_path=daily,
            output_path=plan_path,
            run_id="membership_v2_fixture",
            generated_at_utc="2026-07-17T00:00:00Z",
        )
        raw = [_raw_contract(index) for index in range(100)]
        raw.extend(_raw_contract(1_000 + index, delisted=True, with_end=index < 2) for index in range(10))
        raw.append(dict(raw[0]))
        report = run_probe(
            plan_path=plan_path,
            expected_plan_hash=plan["plan_hash"],
            output_path=probe_path,
            max_runtime_sec=600,
            fetch_page_override=lambda _limit, offset: raw if offset == 0 else [],
        )
        self.assertFalse(report["accepted"])
        return plan_path, probe_path

    def test_diagnosis_separates_exact_and_conflicting_duplicates(self) -> None:
        rows = [
            {"symbol": "AAA_USDT", "contract_multiplier": None},
            {"symbol": "AAA_USDT", "contract_multiplier": None},
            {"symbol": "BBB_USDT", "contract_multiplier": 1.0},
            {"symbol": "BBB_USDT", "contract_multiplier": 2.0},
        ]

        diagnosis = diagnose_source_rows(rows)

        self.assertEqual(diagnosis["exact_duplicate_symbols"], ["AAA_USDT"])
        self.assertEqual(diagnosis["conflicting_duplicate_symbols"], ["BBB_USDT"])
        self.assertEqual(diagnosis["unique_symbols"], 2)

    def test_builds_hash_bound_terminal_closure_without_history_or_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, probe_path = self._source_reject_fixture(root)

            result = build_source_reject_closure(
                plan_path=plan_path,
                probe_path=probe_path,
                output_dir=root / "closure",
                run_id="membership_v2_source_reject",
                generated_at_utc="2026-07-17T01:00:00Z",
            )

            self.assertEqual(result["verdict"], VERDICT)
            self.assertEqual(result["branch_status"], BRANCH_STATUS)
            self.assertIn("DELISTED_END_COVERAGE_BELOW_FROZEN_GATE", result["reason_codes"])
            self.assertIn("DUPLICATE_SYMBOLS_PRESENT", result["reason_codes"])
            self.assertEqual(result["next_allowed_action"], "select_new_materially_distinct_planonly_hypothesis")
            closure = json.loads(Path(result["closure_path"]).read_text(encoding="utf-8"))
            self.assertFalse(closure["data_access_audit"]["history_read"])
            self.assertFalse(closure["data_access_audit"]["oos_read"])
            self.assertFalse(closure["safety"]["live_orders"])
            self.assertGreater(closure["source_diagnosis"]["unique_delisted_missing_end"], 0)

            repeated = build_source_reject_closure(
                plan_path=plan_path,
                probe_path=probe_path,
                output_dir=root / "closure",
                run_id="membership_v2_source_reject",
            )
            self.assertEqual(repeated["closure_artifact_hash"], result["closure_artifact_hash"])

    def test_validation_fails_closed_after_probe_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, probe_path = self._source_reject_fixture(root)
            result = build_source_reject_closure(
                plan_path=plan_path,
                probe_path=probe_path,
                output_dir=root / "closure",
                run_id="membership_v2_source_reject",
                generated_at_utc="2026-07-17T01:00:00Z",
            )
            closure = Path(result["closure_path"])
            closure.write_text(closure.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "closure file hash mismatch"):
                validate_closure_manifest(result["manifest_path"])


if __name__ == "__main__":
    unittest.main()
