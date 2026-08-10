from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "trading_mvp" / "src" / "funding_forward_audit.py"
RUNNER = PROJECT_ROOT / "tools" / "run_weekly_forward_collect.ps1"


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _book(mid: float, spread_bps: float) -> dict[str, object]:
    return {
        "mid": mid,
        "spread_bps": spread_bps,
        "depth": {
            "band_25bps": {"bid_quote_usd": 25_000.0, "ask_quote_usd": 25_000.0},
            "band_50bps": {"bid_quote_usd": 100_000.0, "ask_quote_usd": 100_000.0},
            "band_100bps": {"bid_quote_usd": 200_000.0, "ask_quote_usd": 200_000.0},
        },
    }


def _economics(gross_pct: float, capacity_usd: float, route: str) -> dict[str, object]:
    annual_cost_pct = 8.4
    net_pct = round(gross_pct - annual_cost_pct, 2)
    return {
        "capacity_usd": capacity_usd,
        "gross_after_persistence_haircut_pct": gross_pct,
        "spread_costs_annual_pct": 1.8,
        "all_in_costs_annual_pct": annual_cost_pct,
        "cycle_cost": {
            "profile": "base_api",
            "stress": False,
            "spread_bps": 15.0,
            "total_bps": 70.0,
        },
        "route": route,
        "net_annual_pct": net_pct,
        "net_annual_usd_at_capacity": round(net_pct / 100.0 * capacity_usd, 2),
    }


def _fixture(root: Path) -> dict[str, Path]:
    run_dir = root / "daily_forward_20260810"
    run_dir.mkdir(parents=True)
    universe = root / "coins_not_on_binance_full_2026-05-29.csv"
    with universe.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "name", "symbol", "coin_id"])
        writer.writeheader()
        writer.writerow({"rank": 1, "name": "Akedo", "symbol": "AKE", "coin_id": "ake-akedo"})

    manifest = run_dir / "manifest.json"
    _write_json(
        manifest,
        {
            "schema": "daily_collect_v1",
            "run_id": "daily_forward_20260810",
            "started_at_utc": "2026-08-10T05:00:00+00:00",
            "finished_at_utc": "2026-08-10T05:10:00+00:00",
            "duration_sec": 600.0,
            "params": {
                "exchanges": ["mexc", "gateio"],
                "days": 200,
                "top": 200,
                "max_symbols": 0,
                "universe_csv": str(universe),
            },
            "symbols_total": 400,
            "klines_rows_total": 70_000,
            "funding_rows_total": 320_000,
            "error_count": 0,
            "statuses": [],
        },
    )

    pair = {
        "symbol": "AKE_USDT",
        "base": "AKE",
        "spread_gate_minus_mexc": {
            "aligned_days": 91,
            "mean_daily_spread_bps": -8.132,
            "annualized_spread_pct": -29.68,
            "abs_annualized_spread_pct": 29.68,
            "sign_consistency": 0.901,
            "direction": "short_b_long_a",
        },
        "basis_mexc_vs_gate": {
            "days": 91,
            "mean_basis_bps": 12.1,
            "std_basis_bps": 17.46,
            "max_abs_basis_bps": 58.36,
        },
        "leg_annualized_pct": {"mexc": 23.36, "gateio": -6.32},
        "min_volume_24h_quote": 1_000_000.0,
        "mexc_spot_available": True,
        "non_binance_baseline": True,
    }
    pairs = root / "funding_pairs_forward_20260810.json"
    _write_json(
        pairs,
        {
            "schema": "funding_pairs_v2",
            "created_at_utc": "2026-08-10T05:11:00+00:00",
            "dataset": str(run_dir),
            "params": {
                "window_days": 90,
                "min_aligned_days": 30,
                "turnover_per_year": 12.0,
                "non_binance_only": True,
                "route": "cross_venue_perp_perp",
                "cycle_cost_bps": 70.0,
                "spread_definition": "daily_funding_gate_minus_mexc",
            },
            "shared_symbols_before_non_binance_filter": 1,
            "shared_symbols_total": 1,
            "pairs_analyzed": 1,
            "pairs": [pair],
        },
    )

    execution = root / "execution_gate_forward_20260810.json"
    g_economics = _economics(29.68, 5_000.0, "cross_venue_perp_perp")
    g_economics.update({"spread_annual_pct": -29.68, "sign_consistency": 0.901})
    e_economics = _economics(23.36, 5_000.0, "same_venue_mexc_spot_perp")
    e_economics.update({"leg_annual_pct": 23.36})
    _write_json(
        execution,
        {
            "schema": "execution_gate_v2",
            "created_at_utc": "2026-08-10T05:12:00+00:00",
            "pairs_source": str(pairs),
            "params": {
                "bands_bps": [25, 50, 100],
                "depth_share_cap": 0.2,
                "daily_volume_cap": 0.005,
                "turnover_per_year": 12.0,
                "auto_candidates": True,
            },
            "cost_profile": {"profile": "base_api"},
            "caveat": "one-time orderbook snapshot",
            "candidates": [
                {
                    "symbol": "AKE_USDT",
                    "books": {
                        "mexc_spot": _book(1.0, 10.0),
                        "mexc_perp": _book(1.0, 10.0),
                        "gate_perp": _book(1.001, 12.0),
                    },
                    "errors": [],
                    "e_construction_short_mexc_perp_long_mexc_spot": e_economics,
                    "g_construction_perp_perp": g_economics,
                }
            ],
        },
    )

    identity = root / "funding_forward_identity_evidence_20260810_v1.json"
    contract = "0x2c3a8Ee94dDD97244a93Bc48298f97d2C412F7Db"
    _write_json(
        identity,
        {
            "schema": "funding_forward_identity_evidence_v1",
            "created_at_utc": "2026-08-10T06:00:00+00:00",
            "verification_scope": "identity_only_no_profitability_claim",
            "assets": [
                {
                    "symbol": "AKE",
                    "source_coin_id": "ake-akedo",
                    "asset_name": "Akedo",
                    "contract": {"network": "BSC", "address": contract},
                    "venues": [
                        {
                            "venue": "mexc",
                            "name": "AKEDO",
                            "symbol": "AKE",
                            "market_types": ["spot", "perpetual"],
                            "contract_address": contract,
                            "official_urls": ["https://www.mexc.com/announcements/article/test"],
                        },
                        {
                            "venue": "gateio",
                            "name": "Akedo",
                            "symbol": "AKE",
                            "market_types": ["spot", "perpetual"],
                            "contract_address": contract,
                            "official_urls": ["https://www.gate.com/announcements/article/test"],
                        },
                    ],
                }
            ],
        },
    )
    return {
        "manifest": manifest,
        "pairs": pairs,
        "execution": execution,
        "universe": universe,
        "identity": identity,
        "output": root / "funding_forward_audit_20260810.json",
    }


def _run(paths: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(paths["manifest"]),
            "--pairs-json",
            str(paths["pairs"]),
            "--execution-json",
            str(paths["execution"]),
            "--universe-csv",
            str(paths["universe"]),
            "--identity-evidence",
            str(paths["identity"]),
            "--out",
            str(paths["output"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


class FundingForwardAuditTests(unittest.TestCase):
    def test_valid_snapshot_is_watchlist_only_with_verified_ake_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            completed = _run(paths)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))
            pairs_sha256 = _sha256(paths["pairs"])

        self.assertTrue(audit["audit_passed"])
        self.assertEqual(audit["decision"], "WATCHLIST_ONLY_NOT_EDGE_EVIDENCE")
        self.assertFalse(audit["acceptance_allowed"])
        self.assertEqual(audit["window_contract"]["collection_days"], 200)
        self.assertEqual(audit["window_contract"]["analysis_window_days"], 90)
        self.assertEqual(audit["window_contract"]["inclusive_calendar_days_observed"], 91)
        self.assertFalse(audit["universe_contract"]["point_in_time"])
        self.assertEqual(audit["candidates"][0]["identity"]["status"], "OFFICIAL_SAME_ASSET_VERIFIED")
        self.assertEqual(audit["proof_gates"]["chronological_oos"], "not_run")
        self.assertEqual(audit["inputs"]["pairs"]["sha256"], pairs_sha256)

    def test_ticker_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            with paths["universe"].open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["rank", "name", "symbol", "coin_id"])
                writer.writerow({"rank": 2, "name": "Another AKE", "symbol": "AKE", "coin_id": "ake-other"})
            completed = _run(paths)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))

        self.assertFalse(audit["audit_passed"])
        self.assertEqual(audit["decision"], "FUNDING_FORWARD_AUDIT_REJECTED_INVALID_EVIDENCE")
        self.assertEqual(audit["candidates"][0]["identity"]["status"], "TICKER_COLLISION_FAIL_CLOSED")
        self.assertIn("candidate_identity_collision:AKE", audit["failures"])

    def test_tampered_execution_math_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            payload = json.loads(paths["execution"].read_text(encoding="utf-8"))
            payload["candidates"][0]["g_construction_perp_perp"]["net_annual_pct"] = 999.0
            _write_json(paths["execution"], payload)
            completed = _run(paths)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))

        self.assertFalse(audit["audit_passed"])
        self.assertIn("candidate[AKE_USDT].g_net_math_mismatch", audit["failures"])

    def test_deterministic_hash_is_stable_across_repeated_offline_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            first = _run(paths)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_audit = json.loads(paths["output"].read_text(encoding="utf-8"))
            second = _run(paths)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            second_audit = json.loads(paths["output"].read_text(encoding="utf-8"))
            temporary_exists = paths["output"].with_suffix(".json.tmp").exists()

        self.assertEqual(first_audit["deterministic_result_hash"], second_audit["deterministic_result_hash"])
        self.assertFalse(temporary_exists)

    def test_weekly_runner_pins_universe_and_emits_audit(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn('"--universe-csv", $UniverseCsv', source)
        self.assertIn("funding_forward_audit.py", source)
        self.assertIn("funding_forward_audit_$stamp.json", source)
        self.assertIn("audit_exit=$auditExit", source)


if __name__ == "__main__":
    unittest.main()
