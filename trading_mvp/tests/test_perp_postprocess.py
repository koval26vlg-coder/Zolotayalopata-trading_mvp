from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import build_parser  # noqa: E402
from config import RiskConfig, StrategyConfig  # noqa: E402
from perp_postprocess import PerpPostprocessConfig, run_perp_postprocess_file  # noqa: E402


def _row(exchange: str, symbol: str, kind: str, ts: float, **extra: object) -> dict[str, object]:
    base = {
        "exchange": exchange,
        "symbol": symbol,
        "event_kind": kind,
        "exchange_ts": ts,
        "recv_ts": ts,
        "mark_price": 100.0,
        "index_price": 99.9,
        "funding_rate": 0.0001,
        "funding_interval_sec": 28800,
        "next_funding_ts": 1_700_000_000.0,
        "open_interest": 1000.0,
        "volume_24h_quote": 1_000_000.0,
        "spread_bps": 1.0,
    }
    base.update(extra)
    return base


class PerpPostprocessTests(unittest.TestCase):
    def test_not_final_manifest_blocks_grid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "dataset.jsonl"
            manifest = Path(tmp) / "manifest.json"
            report_out = Path(tmp) / "report.json"
            grid_out = Path(tmp) / "grid.json"
            src.write_text(json.dumps(_row("mexc", "HYPE_USDT", "bbo", 1.0)), encoding="utf-8")
            manifest.write_text(json.dumps({"final": False, "completed_cycles": 1}), encoding="utf-8")

            calls: list[dict[str, object]] = []

            def fake_grid_runner(**kwargs):
                calls.append(kwargs)
                return {"events": 0, "total_combinations": 0, "eligible_combinations": 0, "best_by_signal_type": {}}

            result = run_perp_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                report_output_path=report_out,
                grid_output_path=grid_out,
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(),
                cfg=PerpPostprocessConfig(require_final=True),
                grid_runner=fake_grid_runner,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "not_final")
            self.assertEqual(calls, [])
            self.assertFalse(report_out.exists())
            self.assertFalse(grid_out.exists())

    def test_missing_manifest_blocks_grid_when_final_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "dataset.jsonl"
            report_out = Path(tmp) / "report.json"
            grid_out = Path(tmp) / "grid.json"
            src.write_text(json.dumps(_row("mexc", "HYPE_USDT", "bbo", 1.0)), encoding="utf-8")

            calls: list[dict[str, object]] = []

            def fake_grid_runner(**kwargs):
                calls.append(kwargs)
                return {"events": 0, "total_combinations": 0, "eligible_combinations": 0, "best_by_signal_type": {}}

            result = run_perp_postprocess_file(
                input_path=src,
                manifest_path=None,
                report_output_path=report_out,
                grid_output_path=grid_out,
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(),
                cfg=PerpPostprocessConfig(require_final=True),
                grid_runner=fake_grid_runner,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "manifest_required")
            self.assertEqual(calls, [])
            self.assertFalse(report_out.exists())
            self.assertFalse(grid_out.exists())

    def test_qa_passes_and_grid_runs_for_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "dataset.jsonl"
            manifest = Path(tmp) / "manifest.json"
            report_out = Path(tmp) / "report.json"
            grid_out = Path(tmp) / "grid.json"
            rows = [
                _row("mexc", "HYPE_USDT", "bbo", 1.0),
                _row("mexc", "HYPE_USDT", "trade", 1.1, price=100.0, qty=1.0),
                _row("gateio", "CC_USDT", "bbo", 2.0),
                _row("gateio", "CC_USDT", "trade", 2.1, price=100.0, qty=1.0),
            ]
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 3, "rows": 4}), encoding="utf-8")

            calls: list[dict[str, object]] = []

            def fake_grid_runner(**kwargs):
                calls.append(kwargs)
                return {
                    "events": 4,
                    "total_combinations": 192,
                    "eligible_combinations": 0,
                    "best_by_signal_type": {
                        "flow_continue": {"strategy_config": {"signal_type": "flow_continue"}, "metrics": {"net_pnl_quote": 1.0}, "eligible": True, "eligibility_reasons": []}
                    },
                }

            result = run_perp_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                report_output_path=report_out,
                grid_output_path=grid_out,
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(),
                cfg=PerpPostprocessConfig(require_final=True, top_n=10),
                grid_runner=fake_grid_runner,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "grid_completed")
            self.assertEqual(len(calls), 1)
            self.assertTrue(report_out.exists())
            self.assertFalse(grid_out.exists(), "fake grid runner should not write file")
            self.assertEqual(result["report_summary"]["rows"], 4)
            self.assertEqual(result["grid_summary"]["events"], 4)

    def test_cli_accepts_perp_postprocess_command(self) -> None:
        args = build_parser().parse_args(
            [
                "perp-postprocess",
                "--input",
                "data.jsonl",
                "--manifest",
                "manifest.json",
                "--report-output",
                "report.json",
                "--grid-output",
                "grid.json",
                "--allow-partial",
            ]
        )

        self.assertEqual(args.command, "perp-postprocess")
        self.assertTrue(args.allow_partial)


if __name__ == "__main__":
    unittest.main()
