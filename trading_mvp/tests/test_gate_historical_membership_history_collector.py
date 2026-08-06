from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_historical_membership_history_collector import (  # noqa: E402
    READY_FOR_QUALITY_DECISION,
    STOPPED_INCOMPLETE_DECISION,
    collect_history_archives,
)
from gate_historical_membership_history_plan import build_history_plan, sha256_json  # noqa: E402


def _write_fixture_plan(root: Path, *, max_runtime_sec: int = 60) -> tuple[Path, dict]:
    asset_count = 24
    listed_from_ts = 1_781_913_600 - 2 * 86_400
    manifest = root / "daily.json"
    registry = root / "coins.csv"
    probe_path = root / "probe.json"
    plan_path = root / "plan.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "daily_fixture",
                "params": {"start_sec": 1_764_633_600, "end_sec": 1_781_913_605},
                "universe": [],
            }
        ),
        encoding="utf-8",
    )
    with registry.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "name", "symbol", "coin_id"])
        writer.writeheader()
        for index in range(asset_count):
            writer.writerow(
                {
                    "rank": index + 1,
                    "name": f"Asset {index}",
                    "symbol": f"A{index:02d}",
                    "coin_id": f"asset-{index}",
                }
            )
    rows = [
        {
            "exchange": "gateio",
            "symbol": f"A{index:02d}_USDT",
            "base": f"A{index:02d}",
            "quote": "USDT",
            "instrument_type": "linear_perpetual",
            "contract_type": "crypto",
            "lifecycle_status": "trading",
            "listed_from_ts": listed_from_ts,
            "listed_to_ts": None,
            "active_at_snapshot": True,
            "contract_multiplier": 0.01,
            "funding_interval_sec": 28_800,
            "order_size_min_contracts": 1.0,
            "order_size_max_contracts": 1_000_000.0,
        }
        for index in range(asset_count)
    ]
    probe = {
        "schema": "trading_mvp_gate_historical_membership_probe_v2",
        "generated_at_utc": "2026-07-17T02:00:00Z",
        "run_id": "probe_fixture",
        "plan_hash": "b" * 64,
        "final": True,
        "decision": "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_ACCEPTED_READY_FOR_BACKFILL_PLANONLY",
        "accepted": True,
        "runtime_sec": 1.0,
        "quality": {"accepted": True},
        "rows": rows,
    }
    probe["artifact_hash"] = sha256_json(
        {
            key: value
            for key, value in probe.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
        }
    )
    probe_path.write_text(json.dumps(probe), encoding="utf-8")
    plan = build_history_plan(
        probe_report_path=probe_path,
        expected_probe_plan_hash=probe["plan_hash"],
        expected_probe_artifact_hash=probe["artifact_hash"],
        daily_manifest_path=manifest,
        coin_registry_path=registry,
        output_path=plan_path,
        run_id="history_collect_fixture",
        max_runtime_sec=max_runtime_sec,
    )
    return plan_path, plan


def _gzip_payload() -> bytes:
    return gzip.compress(b"1700000000,1\n")


class GateMembershipHistoryCollectorTests(unittest.TestCase):
    def test_collect_downloads_all_tasks_and_reuses_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)
            output_root = root / "cache"
            manifest = root / "collect.manifest.json"
            calls: list[str] = []

            def fetch(task: dict, _timeout: float) -> tuple[int, bytes, dict[str, str]]:
                calls.append(task["cache_key"])
                return 200, _gzip_payload(), {}

            result = collect_history_archives(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_root=output_root,
                manifest_path=manifest,
                max_runtime_sec=60,
                max_workers=4,
                fetch_override=fetch,
            )

            self.assertTrue(result["final"])
            self.assertEqual(result["decision"], READY_FOR_QUALITY_DECISION)
            self.assertEqual(result["summary"]["downloaded"], len(plan["archive_tasks"]))
            self.assertEqual(result["summary"]["errors"], 0)
            self.assertEqual(result["next_allowed_command"], "fast-edge-membership-history-quality")
            self.assertEqual(len(calls), len(plan["archive_tasks"]))
            self.assertTrue(all(Path(row["path"]).is_file() for row in result["files"] if row["status"] == "downloaded"))

            cached = collect_history_archives(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_root=output_root,
                manifest_path=manifest,
                max_runtime_sec=60,
                fetch_override=lambda *_args: self.fail("network must not run for final cache"),
            )
            self.assertTrue(cached["cache_reused"])

    def test_404_is_terminal_missing_for_later_quality_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)

            result = collect_history_archives(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_root=root / "cache",
                manifest_path=root / "manifest.json",
                max_runtime_sec=60,
                fetch_override=lambda _task, _timeout: (404, b"", {}),
            )

            self.assertTrue(result["final"])
            self.assertEqual(result["summary"]["missing"], len(plan["archive_tasks"]))
            self.assertEqual(result["summary"]["errors"], 0)
            self.assertEqual(result["decision"], READY_FOR_QUALITY_DECISION)

    def test_transient_http_failure_is_resumable_stopped_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)
            failed_key = plan["archive_tasks"][0]["cache_key"]

            def fetch(task: dict, _timeout: float) -> tuple[int, bytes, dict[str, str]]:
                if task["cache_key"] == failed_key:
                    return 503, b"busy", {}
                return 200, _gzip_payload(), {}

            result = collect_history_archives(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_root=root / "cache",
                manifest_path=root / "manifest.json",
                max_runtime_sec=60,
                fetch_override=fetch,
            )

            self.assertFalse(result["final"])
            self.assertEqual(result["decision"], STOPPED_INCOMPLETE_DECISION)
            self.assertEqual(result["summary"]["errors"], 1)
            self.assertEqual(result["next_allowed_command"], "fast-edge-membership-history-collect")
            self.assertEqual(result["resume_contract"]["same_plan_hash"], plan["plan_hash"])

    def test_tampered_plan_is_rejected_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["history_window"]["days"] = 221
            plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "history plan hash mismatch"):
                collect_history_archives(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    output_root=root / "cache",
                    manifest_path=root / "manifest.json",
                    max_runtime_sec=60,
                    fetch_override=lambda *_args: self.fail("fetch must not run"),
                )


class GateMembershipHistoryCollectorWrapperTests(unittest.TestCase):
    def test_run_mvp_exposes_collect_action(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
        text = wrapper.read_text(encoding="utf-8")

        self.assertIn('"fast-edge-membership-history-collect"', text)
        self.assertIn("gate_historical_membership_history_collector.py", text)
        self.assertIn("ManifestPath is required for fast-edge-membership-history-collect", text)
        self.assertIn("MaxRuntimeSec must be <= 7200 for fast-edge-membership-history-collect", text)


if __name__ == "__main__":
    unittest.main()
