from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tools" / "audit_historical_basis_v2_cache.py"
SRC_PATH = REPO_ROOT / "trading_mvp" / "src"


def _load_tool():
    if not TOOL_PATH.is_file():
        raise AssertionError(f"cache audit tool is missing: {TOOL_PATH}")
    spec = importlib.util.spec_from_file_location("historical_basis_v2_cache_audit", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load cache audit tool: {TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HistoricalBasisV2CacheAuditTests(unittest.TestCase):
    def test_missing_cache_requires_network_without_reading_market_rows(self) -> None:
        from trading_mvp.tests.test_historical_basis_v2_collector import _write_plan

        tool = _load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path = _write_plan(root)
            report_path = root / "audit.json"

            report = tool.audit_historical_basis_v2_cache(
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                output_root=root / "historical-basis-1h-v2",
                report_output=report_path,
                code_snapshot_dir=SRC_PATH,
                max_runtime_sec=60,
            )

            self.assertEqual(report["decision"], "NETWORK_COLLECT_REQUIRED")
            self.assertEqual(report["candle_cache"]["expected_items"], 48)
            self.assertEqual(report["candle_cache"]["valid_items"], 0)
            self.assertEqual(report["candle_cache"]["missing_items"], 48)
            self.assertEqual(report["funding_references"]["verified_items"], 16)
            self.assertFalse(report["access_audit"]["market_candle_rows_read"])
            self.assertFalse(report["access_audit"]["network_accessed"])
            self.assertFalse(report["access_audit"]["oos_read"])
            self.assertTrue(report_path.is_file())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), report)

    def test_valid_request_addressed_cache_bypasses_network(self) -> None:
        from trading_mvp.tests.test_historical_basis_v2_collector import (
            CollectFixtureClient,
            _write_plan,
        )
        from historical_basis_v2_collector import collect_historical_basis_v2

        tool = _load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "historical-basis-1h-v2"
            plan, plan_path = _write_plan(root)
            collected = collect_historical_basis_v2(
                plan,
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                output_root=output_root,
                clients={
                    "mexc": CollectFixtureClient("mexc"),
                    "gateio": CollectFixtureClient("gateio"),
                },
                max_runtime_sec=60,
                run_id="cache-audit-fixture",
            )
            self.assertTrue(collected["final"])

            report = tool.audit_historical_basis_v2_cache(
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                output_root=output_root,
                report_output=root / "audit-ready.json",
                code_snapshot_dir=SRC_PATH,
                max_runtime_sec=60,
            )

            self.assertEqual(report["decision"], "CACHE_READY_NO_NETWORK_REQUIRED")
            self.assertEqual(report["candle_cache"]["valid_items"], 48)
            self.assertEqual(report["candle_cache"]["missing_items"], 0)
            self.assertEqual(report["candle_cache"]["invalid_items"], 0)
            self.assertTrue(report["access_audit"]["market_candle_rows_read"])
            self.assertTrue(report["conclusion"]["cache_can_bypass_network_collect"])

    def test_tampered_cache_is_invalid_and_requires_repair(self) -> None:
        from trading_mvp.tests.test_historical_basis_v2_collector import (
            CollectFixtureClient,
            _write_plan,
        )
        from historical_basis_v2_collector import collect_historical_basis_v2

        tool = _load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "historical-basis-1h-v2"
            plan, plan_path = _write_plan(root)
            collected = collect_historical_basis_v2(
                plan,
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                output_root=output_root,
                clients={
                    "mexc": CollectFixtureClient("mexc"),
                    "gateio": CollectFixtureClient("gateio"),
                },
                max_runtime_sec=60,
                run_id="cache-audit-tamper-fixture",
            )
            first_cache = Path(collected["statuses"][0]["cache_path"])
            payload = json.loads(first_cache.read_text(encoding="utf-8"))
            payload["rows"][0]["close"] = 999.0
            first_cache.write_text(json.dumps(payload), encoding="utf-8")

            report = tool.audit_historical_basis_v2_cache(
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                output_root=output_root,
                report_output=root / "audit-invalid.json",
                code_snapshot_dir=SRC_PATH,
                max_runtime_sec=60,
            )

            self.assertEqual(report["decision"], "CACHE_INVALID_NETWORK_REPAIR_REQUIRED")
            self.assertEqual(report["candle_cache"]["invalid_items"], 1)
            self.assertEqual(report["candle_cache"]["valid_items"], 47)
            self.assertFalse(report["conclusion"]["cache_can_bypass_network_collect"])


if __name__ == "__main__":
    unittest.main()
