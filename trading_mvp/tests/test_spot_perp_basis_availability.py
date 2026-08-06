from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spot_perp_basis_availability import (  # noqa: E402
    REQUIRED_FIELDS,
    build_availability_preflight,
    field_coverage_summary,
    load_non_binance_bases,
)


def write_fixture_repo(root: Path) -> Path:
    universe_csv = root / "coins_not_on_binance_full_2026-05-29.csv"
    universe_csv.write_text("rank,name,symbol\n1,Hype,HYPE\n2,Foo,FOO\n", encoding="utf-8")
    run = root / "exports" / "trading-mvp" / "daily" / "daily_collect_20260702_top200"
    run.mkdir(parents=True)
    for exchange in ("mexc", "gateio"):
        for folder in ("klines", "funding"):
            path = run / exchange / folder
            path.mkdir(parents=True)
            (path / "HYPE_USDT.json").write_text(json.dumps({"rows": [{"ts": 1}]}), encoding="utf-8")
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "daily_collect_20260702_top200",
                "klines_rows_total": 20,
                "funding_rows_total": 20,
                "error_count": 0,
                "universe": [
                    {
                        "exchange": "mexc",
                        "symbol": "HYPE_USDT",
                        "base": "HYPE",
                        "non_binance_baseline": True,
                    },
                    {
                        "exchange": "gateio",
                        "symbol": "HYPE_USDT",
                        "base": "HYPE",
                        "non_binance_baseline": True,
                    },
                    {
                        "exchange": "mexc",
                        "symbol": "FOO_USDT",
                        "base": "FOO",
                        "non_binance_baseline": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return run


class SpotPerpBasisAvailabilityTests(unittest.TestCase):
    def test_load_non_binance_bases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u.csv"
            path.write_text("rank,symbol\n1,hype\n2,foo\n", encoding="utf-8")
            self.assertEqual(load_non_binance_bases(path), {"HYPE", "FOO"})

    def test_field_coverage_declares_all_required_fields_public(self) -> None:
        coverage = field_coverage_summary()
        self.assertTrue(set(REQUIRED_FIELDS).issubset(coverage))
        self.assertTrue(all(coverage[field]["public_api_available"] for field in REQUIRED_FIELDS))
        self.assertFalse(coverage["spot_mid"]["existing_files_available"])

    def test_preflight_ready_for_public_probe_but_not_backtest_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_fixture_repo(repo)

            report = build_availability_preflight(
                repo_root=repo,
                min_candidate_bases=1,
            )

        self.assertEqual(report["decision"], "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE")
        self.assertEqual(report["daily_history"]["candidate_non_binance_bases_count"], 1)
        self.assertFalse(report["preflight_interpretation"]["existing_files_are_backtest_ready"])
        self.assertTrue(report["preflight_interpretation"]["public_probe_needed"])
        self.assertFalse(report["collect_allowed_now"])
        self.assertFalse(report["replay_allowed_now"])
        self.assertFalse(report["grid_allowed_now"])
        self.assertFalse(report["live_orders"])
        self.assertFalse(report["api_keys"])
        self.assertFalse(report["leverage_or_margin"])
        self.assertFalse(report["strategy_accepted"])

    def test_preflight_rejects_when_candidate_bases_too_few(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_fixture_repo(repo)

            report = build_availability_preflight(
                repo_root=repo,
                min_candidate_bases=2,
            )

        self.assertEqual(report["decision"], "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED_TOO_FEW_CANDIDATES")
        self.assertIn("Do not start collect/grid/replay/live/API/paper-forward.", report["next_valid_moves"])


if __name__ == "__main__":
    unittest.main()
