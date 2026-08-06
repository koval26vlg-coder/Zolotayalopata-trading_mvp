from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_historical_membership_v2 import (  # noqa: E402
    ACCEPTED_PROBE_DECISION,
    PLAN_DECISION,
    STOPPED_INCOMPLETE_DECISION,
    authorize_probe,
    build_plan,
    parse_contracts_all,
    run_probe,
    summarize_membership_rows,
)


def _write_daily_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "daily_fixture",
                "params": {"exchanges": ["mexc", "gateio"], "days": 200},
                "statuses": [],
            }
        ),
        encoding="utf-8",
    )


def _raw_contract(index: int, *, delisted: bool = False, multiplier: str | None = "0.01") -> dict:
    row = {
        "name": f"A{index:03d}_USDT",
        "type": "direct",
        "contract_type": "crypto",
        "status": "delisted" if delisted else "trading",
        "create_time": 1_600_000_000 + index,
        "launch_time": 1_600_000_100 + index,
        "in_delisting": delisted,
        "position_size": "0" if delisted else "100",
        "funding_interval": 28_800,
        "order_size_min": 1,
        "order_size_max": 1_000_000,
    }
    if multiplier is not None:
        row["quanto_multiplier"] = multiplier
    if delisted:
        row["delisted_time"] = 1_700_000_000 + index
    return row


class GateHistoricalMembershipV2Tests(unittest.TestCase):
    def test_plan_is_deterministic_and_binds_lifecycle_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            first = root / "first.json"
            second = root / "second.json"
            _write_daily_manifest(manifest)

            a = build_plan(
                daily_manifest_path=manifest,
                output_path=first,
                run_id="membership_v2_fixture",
                max_runtime_sec=600,
                generated_at_utc="2026-07-17T03:00:00Z",
            )
            b = build_plan(
                daily_manifest_path=manifest,
                output_path=second,
                run_id="membership_v2_fixture",
                max_runtime_sec=600,
                generated_at_utc="2026-07-17T04:00:00Z",
            )

            self.assertEqual(a["decision"], PLAN_DECISION)
            self.assertEqual(a["plan_hash"], b["plan_hash"])
            self.assertEqual(len(a["code_provenance"]["module_sha256"]), 64)
            self.assertEqual(len(a["code_provenance"]["lifecycle_helper_sha256"]), 64)
            self.assertIn("quanto_multiplier", a["source_contract"]["required_contract_fields"])
            self.assertFalse(a["network_calls_now"])
            self.assertIn(a["plan_hash"], a["approval_phrase"])

    def test_parser_preserves_multiplier_and_execution_metadata(self) -> None:
        rows = parse_contracts_all([_raw_contract(1)], snapshot_ts=1_800_000_000)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contract_multiplier"], 0.01)
        self.assertEqual(rows[0]["funding_interval_sec"], 28_800)
        self.assertEqual(rows[0]["order_size_min_contracts"], 1.0)
        self.assertEqual(rows[0]["order_size_max_contracts"], 1_000_000.0)
        self.assertEqual(
            rows[0]["quote_volume_formula"],
            "volume_contracts * close_price * contract_multiplier",
        )

    def test_quality_requires_multiplier_coverage_for_delisted_rows(self) -> None:
        raw = [_raw_contract(index) for index in range(100)]
        raw.append(_raw_contract(999, delisted=True, multiplier=None))
        rows = parse_contracts_all(raw, snapshot_ts=1_800_000_000)

        quality = summarize_membership_rows(rows)

        self.assertFalse(quality["accepted"])
        self.assertEqual(quality["missing_contract_multiplier"], ["A999_USDT"])
        self.assertLess(quality["delisted_multiplier_coverage"], 0.90)

    def test_probe_is_hash_bound_and_cache_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            plan_path = root / "plan.json"
            output = root / "probe.json"
            _write_daily_manifest(manifest)
            plan = build_plan(
                daily_manifest_path=manifest,
                output_path=plan_path,
                run_id="membership_v2_fixture",
            )
            raw = [_raw_contract(index) for index in range(100)] + [_raw_contract(999, delisted=True)]

            report = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                fetch_page_override=lambda _limit, offset: raw if offset == 0 else [],
            )
            self.assertEqual(report["decision"], ACCEPTED_PROBE_DECISION)
            self.assertTrue(report["final"])
            self.assertEqual(report["rows"][-1]["contract_multiplier"], 0.01)

            cached = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                fetch_page_override=lambda *_args: self.fail("network must not run"),
            )
            self.assertTrue(cached["cache_reused"])

    def test_network_failure_is_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            plan_path = root / "plan.json"
            output = root / "probe.json"
            _write_daily_manifest(manifest)
            plan = build_plan(
                daily_manifest_path=manifest,
                output_path=plan_path,
                run_id="membership_v2_fixture",
            )

            report = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                fetch_page_override=lambda *_args: (_ for _ in ()).throw(TimeoutError("fixture")),
            )

            self.assertEqual(report["decision"], STOPPED_INCOMPLETE_DECISION)
            self.assertFalse(report["final"])

    def test_plan_hash_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            plan_path = root / "plan.json"
            _write_daily_manifest(manifest)
            plan = build_plan(
                daily_manifest_path=manifest,
                output_path=plan_path,
                run_id="membership_v2_fixture",
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["quality_gates"]["minimum_multiplier_coverage"] = 0.5
            plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
                authorize_probe(plan_path, plan["plan_hash"])


class GateHistoricalMembershipV2WrapperTests(unittest.TestCase):
    def test_run_mvp_exposes_v2_actions(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
        text = wrapper.read_text(encoding="utf-8")

        self.assertIn('"fast-edge-membership-v2-plan"', text)
        self.assertIn('"fast-edge-membership-v2-probe"', text)
        self.assertIn("gate_historical_membership_v2.py", text)
        self.assertIn("MaxRuntimeSec must be <= 600 for fast-edge-membership-v2-probe", text)


if __name__ == "__main__":
    unittest.main()
