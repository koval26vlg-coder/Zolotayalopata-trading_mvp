from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cross_venue_full_scan_audit import (  # noqa: E402
    INVALID_EVIDENCE,
    VERIFIED_REJECTION,
    CrossVenueFullScanAuditConfig,
    build_cross_venue_full_scan_audit,
    run_cross_venue_full_scan_audit,
    sample_file_fingerprint,
)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _candidate() -> dict[str, object]:
    gross = (100.4 / 100.0 - 1.0) * 10000.0
    return {
        "ts": 1000.5,
        "base": "TEST",
        "direction": "buy_mexc_sell_gateio",
        "buy_exchange": "mexc",
        "buy_symbol": "TESTUSDT",
        "buy_ask": 100.0,
        "buy_ask_qty": 10.0,
        "sell_exchange": "gateio",
        "sell_symbol": "TEST_USDT",
        "sell_bid": 100.4,
        "sell_bid_qty": 10.0,
        "gross_edge_bps": gross,
        "net_edge_bps": gross - 69.0,
        "total_cost_bps": 69.0,
        "capacity_quote": 1000.0,
        "buy_capacity_quote": 1000.0,
        "sell_capacity_quote": 1004.0,
        "age_sec": 0.5,
        "fresh": True,
    }


def _fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    source = root / "clean.jsonl"
    source.write_bytes((b'{"event_kind":"bbo"}\n' * 1000) + b"tail")
    legacy = root / "legacy" / source.name
    legacy.parent.mkdir()
    legacy.write_bytes(source.read_bytes())
    report_path = root / "report.json"
    manifest_path = root / "manifest.json"
    candidate = _candidate()
    summary = {
        "rows_read": 1000,
        "bbo_rows": 1000,
        "parse_errors": 0,
        "matched_bases": 1,
        "candidate_events": 1,
        "eligible_events": 0,
        "max_gross_edge_bps": candidate["gross_edge_bps"],
        "max_net_edge_bps": candidate["net_edge_bps"],
        "scan_complete": True,
    }
    report: dict[str, object] = {
        "mode": "cross_venue_dislocation_planonly_research",
        "input": rf"C:\old\{source.name}",
        "research_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "config": {
            "round_trip_fee_bps": 39.0,
            "slippage_bps": 10.0,
            "inventory_rebalance_buffer_bps": 20.0,
            "min_top_notional_quote": 25.0,
            "total_cost_bps": 69.0,
            "max_rows": 0,
        },
        "cost_model": {"total_cost_bps": 69.0},
        "markets": {"gateio": ["TEST_USDT"], "mexc": ["TESTUSDT"]},
        "summary": summary,
        "top_candidates": [candidate],
        "top_eligible": [],
        "decision": "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES",
        "accepted": False,
    }
    manifest: dict[str, object] = {
        "schema": "cross_venue_dislocation_full_scan_manifest_v1",
        "run_id": "test_full_scan",
        "status": "READY_FOR_POSTPROCESS",
        "final": True,
        "exit_code": 0,
        "input_path": rf"C:\old\{source.name}",
        "output_path": rf"C:\old\{report_path.name}",
        "summary": summary,
        "decision": "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES",
        "research_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
    }
    _write_json(report_path, report)
    _write_json(manifest_path, manifest)
    return report_path, manifest_path, source, legacy


class CrossVenueFullScanAuditTests(unittest.TestCase):
    def test_sample_fingerprint_matches_copied_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, source, legacy = _fixture(Path(tmp))
            left = sample_file_fingerprint(source, sample_bytes=128)
            right = sample_file_fingerprint(legacy, sample_bytes=128)
        self.assertEqual(left["size_bytes"], right["size_bytes"])
        self.assertEqual(left["sample_fingerprint_sha256"], right["sample_fingerprint_sha256"])

    def test_verified_rejection_closes_branch_before_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, manifest, source, legacy = _fixture(Path(tmp))
            result = build_cross_venue_full_scan_audit(
                report,
                manifest,
                source,
                legacy_source_path=legacy,
                cfg=CrossVenueFullScanAuditConfig(expected_min_rows=1000, sample_bytes=128),
            )
        self.assertTrue(result["audit_passed"])
        self.assertEqual(result["decision"], VERIFIED_REJECTION)
        self.assertEqual(result["branch_verdict"], "rejected")
        self.assertEqual(result["proof_gates"]["oos"], "not_reached_economics_screen_failed")
        self.assertLess(result["economics"]["max_net_without_inventory_buffer_bps"], 0.0)

    def test_non_final_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, manifest, source, _ = _fixture(Path(tmp))
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["final"] = False
            _write_json(manifest, value)
            result = build_cross_venue_full_scan_audit(report, manifest, source)
        self.assertFalse(result["audit_passed"])
        self.assertEqual(result["decision"], INVALID_EVIDENCE)
        self.assertIn("manifest_not_final_ready_for_postprocess", result["failures"])

    def test_candidate_math_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, manifest, source, _ = _fixture(Path(tmp))
            value = json.loads(report.read_text(encoding="utf-8"))
            value["top_candidates"][0]["net_edge_bps"] = 123.0
            _write_json(report, value)
            result = build_cross_venue_full_scan_audit(report, manifest, source)
        self.assertFalse(result["audit_passed"])
        self.assertIn("top_candidates[0]_net_edge_math_mismatch", result["failures"])

    def test_run_writes_atomic_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, manifest, source, legacy = _fixture(root)
            output = root / "audit.json"
            result = run_cross_venue_full_scan_audit(
                report,
                manifest,
                source,
                output,
                legacy_source_path=legacy,
                cfg=CrossVenueFullScanAuditConfig(expected_min_rows=1000, sample_bytes=128),
            )
            stored = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(result["audit_passed"])
        self.assertEqual(stored["decision"], VERIFIED_REJECTION)
        self.assertEqual(stored["output_path"], str(output))
        self.assertFalse(output.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
