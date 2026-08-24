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

from gate_historical_membership_v1 import (  # noqa: E402
    ACCEPTED_PROBE_DECISION,
    PLAN_DECISION,
    STOPPED_INCOMPLETE_DECISION,
    authorize_probe,
    build_plan,
    fetch_contracts_all,
    parse_contracts_all,
    run_probe,
    summarize_membership_rows,
)


def _write_daily_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "daily_forward_fixture",
                "params": {"exchanges": ["mexc", "gateio"], "days": 200, "top": 200},
                "statuses": [],
            }
        ),
        encoding="utf-8",
    )


class GateHistoricalMembershipPlanTests(unittest.TestCase):
    def test_plan_is_deterministic_data_only_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            first = root / "first.json"
            second = root / "second.json"
            _write_daily_manifest(manifest)

            plan_a = build_plan(
                daily_manifest_path=manifest,
                output_path=first,
                run_id="gate_membership_fixture",
                max_runtime_sec=600,
                generated_at_utc="2026-07-17T01:00:00Z",
            )
            plan_b = build_plan(
                daily_manifest_path=manifest,
                output_path=second,
                run_id="gate_membership_fixture",
                max_runtime_sec=600,
                generated_at_utc="2026-07-17T02:00:00Z",
            )

            self.assertEqual(plan_a["decision"], PLAN_DECISION)
            self.assertEqual(plan_a["plan_hash"], plan_b["plan_hash"])
            self.assertFalse(plan_a["network_calls_now"])
            self.assertFalse(plan_a["collect_allowed_now"])
            self.assertEqual(plan_a["next_allowed_command"], "fast-edge-membership-probe")
            self.assertIn(plan_a["plan_hash"], plan_a["approval_phrase"])
            self.assertEqual(
                plan_a["source_contract"]["gate_contracts_all_endpoint"],
                "https://api.gateio.ws/api/v4/futures/usdt/contracts_all",
            )
            self.assertEqual(plan_a["source_contract"]["pagination"]["limit"], 100)
            self.assertEqual(
                plan_a["data_access_audit"],
                {
                    "returns_read": False,
                    "pnl_read": False,
                    "signals_read": False,
                    "oos_read": False,
                    "oos_metrics_read": False,
                },
            )
            self.assertEqual(
                plan_a["input_provenance"]["daily_manifest_path"],
                str(manifest.resolve()),
            )
            self.assertEqual(len(plan_a["code_provenance"]["module_sha256"]), 64)
            self.assertTrue(first.is_file())

    def test_plan_rejects_runtime_over_ten_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            _write_daily_manifest(manifest)

            with self.assertRaisesRegex(ValueError, "max_runtime_sec must be in"):
                build_plan(
                    daily_manifest_path=manifest,
                    output_path=None,
                    run_id="too_long",
                    max_runtime_sec=601,
                )

    def test_probe_authorization_fails_closed_on_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            plan_path = root / "plan.json"
            _write_daily_manifest(manifest)
            plan = build_plan(
                daily_manifest_path=manifest,
                output_path=plan_path,
                run_id="gate_membership_fixture",
                max_runtime_sec=600,
            )

            authorized = authorize_probe(plan_path, plan["plan_hash"])
            self.assertEqual(authorized["plan_hash"], plan["plan_hash"])
            with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
                authorize_probe(plan_path, "0" * 64)

    def test_network_failure_writes_resumable_stopped_incomplete_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            plan_path = root / "plan.json"
            output = root / "probe.json"
            _write_daily_manifest(manifest)
            plan = build_plan(
                daily_manifest_path=manifest,
                output_path=plan_path,
                run_id="gate_membership_fixture",
                max_runtime_sec=600,
            )

            report = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                fetch_page_override=lambda _limit, _offset: (_ for _ in ()).throw(TimeoutError("fixture")),
            )

            self.assertEqual(report["decision"], STOPPED_INCOMPLETE_DECISION)
            self.assertFalse(report["final"])
            self.assertFalse(report["accepted"])
            self.assertEqual(report["next_allowed_command"], "fast-edge-membership-probe")
            self.assertTrue(output.is_file())

    def test_final_probe_cache_is_reused_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            plan_path = root / "plan.json"
            output = root / "probe.json"
            _write_daily_manifest(manifest)
            plan = build_plan(
                daily_manifest_path=manifest,
                output_path=plan_path,
                run_id="gate_membership_fixture",
                max_runtime_sec=600,
            )
            output.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_gate_historical_membership_probe_v1",
                        "plan_hash": plan["plan_hash"],
                        "final": True,
                        "decision": ACCEPTED_PROBE_DECISION,
                        "accepted": True,
                    }
                ),
                encoding="utf-8",
            )

            report = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                fetch_page_override=lambda _limit, _offset: self.fail("network must not be called"),
            )

            self.assertTrue(report["cache_reused"])
            self.assertEqual(report["decision"], ACCEPTED_PROBE_DECISION)


class GateHistoricalMembershipParsingTests(unittest.TestCase):
    def test_parser_preserves_active_and_delisted_lifecycle(self) -> None:
        payload = [
            {
                "name": "ALPHA_USDT",
                "type": "direct",
                "contract_type": "crypto",
                "status": "trading",
                "create_time": 1_700_000_000,
                "launch_time": 1_700_000_100,
                "in_delisting": False,
                "position_size": "100",
            },
            {
                "name": "DEAD_USDT",
                "type": "direct",
                "contract_type": "crypto",
                "status": "delisted",
                "create_time": 1_600_000_000,
                "launch_time": 1_600_000_100,
                "delisting_time": 1_650_000_000,
                "delisted_time": 1_650_010_000,
                "in_delisting": True,
                "position_size": "0",
            },
            {
                "name": "SPX500_USDT",
                "type": "direct",
                "contract_type": "indices",
                "status": "trading",
                "create_time": 1_700_000_000,
            },
        ]

        rows = parse_contracts_all(payload, snapshot_ts=1_800_000_000)

        self.assertEqual([row["symbol"] for row in rows], ["ALPHA_USDT", "DEAD_USDT"])
        active, dead = rows
        self.assertTrue(active["active_at_snapshot"])
        self.assertIsNone(active["listed_to_ts"])
        self.assertFalse(dead["active_at_snapshot"])
        self.assertEqual(dead["listed_from_ts"], 1_600_000_100)
        self.assertEqual(dead["listed_to_ts"], 1_650_010_000)
        self.assertEqual(dead["lifecycle_status"], "delisted")

    def test_parser_infers_delisted_from_official_position_condition(self) -> None:
        rows = parse_contracts_all(
            [
                {
                    "name": "GONE_USDT",
                    "type": "direct",
                    "status": "unknown",
                    "create_time": 1_500_000_000,
                    "delisted_time": 1_550_000_000,
                    "in_delisting": True,
                    "position_size": "0",
                }
            ],
            snapshot_ts=1_800_000_000,
        )

        self.assertEqual(rows[0]["lifecycle_status"], "delisted")
        self.assertFalse(rows[0]["active_at_snapshot"])

    def test_pagination_rejects_duplicate_nonempty_page(self) -> None:
        page = [{"name": "A_USDT"}]

        with self.assertRaisesRegex(ValueError, "duplicate contracts_all page"):
            fetch_contracts_all(
                lambda _limit, _offset: page,
                page_limit=1,
                max_pages=3,
                deadline_monotonic=time.monotonic() + 10,
            )

    def test_quality_accepts_complete_active_and_delisted_fixture(self) -> None:
        rows = parse_contracts_all(
            [
                {
                    "name": f"A{index:03d}_USDT",
                    "type": "direct",
                    "contract_type": "crypto",
                    "status": "trading",
                    "create_time": 1_600_000_000 + index,
                    "launch_time": 1_600_000_100 + index,
                    "in_delisting": False,
                    "position_size": "100",
                }
                for index in range(100)
            ]
            + [
                {
                    "name": "DEAD_USDT",
                    "type": "direct",
                    "contract_type": "crypto",
                    "status": "delisted",
                    "create_time": 1_500_000_000,
                    "launch_time": 1_500_000_100,
                    "delisted_time": 1_550_000_000,
                    "in_delisting": True,
                    "position_size": "0",
                }
            ],
            snapshot_ts=1_800_000_000,
        )

        summary = summarize_membership_rows(rows)

        self.assertTrue(summary["accepted"])
        self.assertEqual(summary["decision"], ACCEPTED_PROBE_DECISION)
        self.assertEqual(summary["delisted_contracts"], 1)
        self.assertEqual(summary["duplicate_symbols"], [])


class GateHistoricalMembershipWrapperTests(unittest.TestCase):
    def test_run_mvp_exposes_plan_and_probe_actions(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(wrapper)

        self.assertIn('"fast-edge-membership-plan"', text)
        self.assertIn('"fast-edge-membership-probe"', text)
        self.assertIn("gate_historical_membership_v1.py", text)
        self.assertIn("MaxRuntimeSec must be <= 600 for fast-edge-membership-plan", text)
        self.assertIn("MaxRuntimeSec must be <= 600 for fast-edge-membership-probe", text)
        self.assertIn('"--expected-plan-hash", $ExpectedPlanHash', text)


if __name__ == "__main__":
    unittest.main()
