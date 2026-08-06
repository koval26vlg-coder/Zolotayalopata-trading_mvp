from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_historical_membership_v2 import build_plan as build_v2_plan  # noqa: E402
from gate_historical_membership_v2 import run_probe as run_v2_probe  # noqa: E402
from gate_historical_membership_v2_closure import build_source_reject_closure  # noqa: E402
from gate_historical_membership_v3 import build_plan as build_v3_plan  # noqa: E402
from gate_historical_membership_v3 import run_probe as run_v3_probe  # noqa: E402
from gate_historical_membership_v3_closure import (  # noqa: E402
    build_archive_source_reject_closure,
    validate_archive_source_closure_manifest,
)


END_SEC = 1_800_000_000


def _contract(index: int, cohort: str) -> dict:
    delisted = cohort != "active"
    age_offset = index % 100
    row = {
        "name": f"C{index:03d}_USDT",
        "type": "direct",
        "contract_type": "crypto",
        "status": "delisted" if delisted else "trading",
        "create_time": END_SEC - (150 + age_offset) * 86_400,
        "launch_time": END_SEC - (149 + age_offset) * 86_400,
        "in_delisting": delisted,
        "position_size": "0" if delisted else "100",
        "quanto_multiplier": "0.01",
        "funding_interval": 28_800,
        "order_size_min": 1,
        "order_size_max": 1_000_000,
    }
    if cohort == "known_end":
        row["delisted_time"] = END_SEC - (10 + age_offset) * 86_400
    return row


def _write_daily(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "daily_fixture",
                "params": {"exchanges": ["mexc", "gateio"], "days": 220, "end_sec": END_SEC},
                "statuses": [],
            }
        ),
        encoding="utf-8",
    )


def _write_registry(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "symbol", "name", "coin_id"])
        writer.writeheader()
        for index, row in enumerate(rows):
            base = row["name"].rsplit("_", 1)[0]
            writer.writerow({"rank": index + 1, "symbol": base, "name": base, "coin_id": f"coin-{base.lower()}"})


class GateHistoricalMembershipV3ClosureTests(unittest.TestCase):
    def _rejected_probe(self, root: Path) -> tuple[Path, Path, dict]:
        daily_path = root / "daily.json"
        registry_path = root / "registry.csv"
        v2_plan_path = root / "v2-plan.json"
        v2_probe_path = root / "v2-probe.json"
        v2_closure_dir = root / "v2-closure"
        v3_plan_path = root / "v3-plan.json"
        v3_probe_path = root / "v3-probe.json"
        _write_daily(daily_path)
        rows = [*(_contract(index, "active") for index in range(100))]
        rows.extend(_contract(200 + index, "missing_end") for index in range(15))
        rows.extend(_contract(300 + index, "known_end") for index in range(10))
        _write_registry(registry_path, rows)

        v2_plan = build_v2_plan(
            daily_manifest_path=daily_path,
            output_path=v2_plan_path,
            run_id="v2_fixture",
            generated_at_utc="2026-07-17T00:00:00Z",
        )
        run_v2_probe(
            plan_path=v2_plan_path,
            expected_plan_hash=v2_plan["plan_hash"],
            output_path=v2_probe_path,
            max_runtime_sec=600,
            fetch_page_override=lambda _limit, offset: rows if offset == 0 else [],
        )
        v2_closure = build_source_reject_closure(
            plan_path=v2_plan_path,
            probe_path=v2_probe_path,
            output_dir=v2_closure_dir,
            run_id="v2_closure",
            generated_at_utc="2026-07-17T00:01:00Z",
        )
        v3_plan = build_v3_plan(
            closure_manifest_path=Path(v2_closure["manifest_path"]),
            daily_manifest_path=daily_path,
            coin_registry_path=registry_path,
            output_path=v3_plan_path,
            run_id="v3_fixture",
            generated_at_utc="2026-07-17T00:02:00Z",
        )
        probe = run_v3_probe(
            plan_path=v3_plan_path,
            expected_plan_hash=v3_plan["plan_hash"],
            output_path=v3_probe_path,
            max_runtime_sec=600,
            fetch_override=lambda task, _timeout: (
                404 if task["cohort"] == "missing_end_delisted" else 200,
                {},
            ),
        )
        self.assertFalse(probe["accepted"])
        return v3_plan_path, v3_probe_path, probe

    def test_rejected_source_closes_branch_without_history_or_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, probe_path, probe = self._rejected_probe(root)
            result = build_archive_source_reject_closure(
                plan_path=plan_path,
                probe_path=probe_path,
                output_dir=root / "closure",
                run_id="v3_source_closure",
                generated_at_utc="2026-07-17T00:03:00Z",
            )

            self.assertEqual(result["verdict"], "INSUFFICIENT_SOURCE_QUALITY")
            self.assertEqual(result["branch_status"], "CLOSED_WITHOUT_HISTORY_OR_OOS")
            self.assertEqual(result["reason_codes"], ["MISSING_END_DELISTED_ARCHIVE_AVAILABILITY_BELOW_FROZEN_GATE"])
            self.assertEqual(result["observed_quality"]["errors"], 0)
            self.assertEqual(result["observed_quality"]["cohorts"]["missing_end_delisted"]["available_symbols"], 0)
            self.assertFalse(result["data_access_audit"]["history_read"])
            self.assertFalse(result["data_access_audit"]["oos_read"])
            self.assertFalse(result["history_authorized"])
            self.assertEqual(result["probe_artifact_hash"], probe["artifact_hash"])

            repeated = validate_archive_source_closure_manifest(result["manifest_path"])
            self.assertEqual(repeated["closure_artifact_hash"], result["closure_artifact_hash"])


if __name__ == "__main__":
    unittest.main()
