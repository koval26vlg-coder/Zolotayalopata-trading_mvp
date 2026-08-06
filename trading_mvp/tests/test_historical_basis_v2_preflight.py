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

from historical_basis_v2_preflight import (  # noqa: E402
    DAY_SEC,
    HOUR_SEC,
    audit_funding_events,
    build_arg_parser,
    derive_frozen_window,
    run_historical_basis_v2_preflight,
)


class FakeBoundaryClient:
    public_only = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch_1h_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, float]]:
        self.calls.append((symbol, series, start_sec, end_sec))
        return [
            {
                "ts": float(start_sec),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume_base": 10.0,
                "volume_quote": 1_005.0,
            }
        ]


def _funding_rows(start_sec: int, end_sec: int, cadence_sec: int = 4 * HOUR_SEC):
    rows = []
    for index, ts in enumerate(range(start_sec, end_sec, cadence_sec)):
        rows.append(
            {
                "ts": float(ts + (index % 3)),
                "funding_rate": -0.0001 if index % 2 else 0.0001,
            }
        )
    return rows


def _write_preflight_inputs(root: Path, count: int = 9) -> tuple[Path, Path, Path, int]:
    cutoff_sec = 180 * DAY_SEC + 5 * HOUR_SEC + 37
    window = derive_frozen_window([cutoff_sec])
    registry_path = root / "coins.csv"
    registry_rows = [
        {
            "rank": str(index + 1),
            "name": f"Asset {index}",
            "symbol": f"A{index}",
            "coin_id": f"asset-{index:02d}",
            "market_cap_usd": "1",
            "price_usd": "1",
        }
        for index in range(count)
    ]
    with registry_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(registry_rows[0]))
        writer.writeheader()
        writer.writerows(registry_rows)

    symbols: dict[str, object] = {}
    funding_root = root / "funding-cache"
    for index in range(count):
        base = f"A{index}"
        for venue in ("mexc", "gateio"):
            symbol = f"{base}_USDT"
            symbols[f"{venue}|{symbol}"] = {
                "row": {
                    "exchange": venue,
                    "symbol": symbol,
                    "base": base,
                    "quote": "USDT",
                    "contract_type": "linear_perp",
                    "status": "trading",
                    "listed_now": True,
                    "inactive_or_delisted": False,
                    "eligible_non_binance_spot": True,
                    "binance_spot_listed": False,
                    # Deliberately reverse identity order. A0 must not rank on this.
                    "volume_24h_quote": float(index + 1),
                    "listed_at_ts": window["window_start_sec"] - DAY_SEC,
                }
            }
            funding_path = funding_root / venue / "funding" / f"{symbol}.json"
            funding_path.parent.mkdir(parents=True, exist_ok=True)
            funding_path.write_text(
                json.dumps(
                    {
                        "exchange": venue,
                        "symbol": symbol,
                        "cutoff_sec": cutoff_sec,
                        "rows": _funding_rows(
                            window["window_start_sec"],
                            window["window_end_sec"],
                        ),
                    }
                ),
                encoding="utf-8",
            )

    pit_path = root / "universe_state.json"
    pit_path.write_text(
        json.dumps({"schema": "pit_universe_state_v1", "symbols": symbols}),
        encoding="utf-8",
    )
    manifest_path = funding_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "fixture-daily-cache",
                "params": {"end_sec": cutoff_sec},
                "statuses": [],
            }
        ),
        encoding="utf-8",
    )
    return pit_path, registry_path, manifest_path, cutoff_sec


class HistoricalBasisV2WindowTests(unittest.TestCase):
    def test_180_day_cache_boundary_freezes_exactly_179_closed_utc_days(self) -> None:
        cutoff_sec = 180 * DAY_SEC + 5 * HOUR_SEC + 37
        window = derive_frozen_window([cutoff_sec, cutoff_sec + 120])

        self.assertEqual(window["window_end_sec"], 180 * DAY_SEC + 5 * HOUR_SEC)
        self.assertEqual(
            window["window_end_sec"] - window["window_start_sec"],
            179 * DAY_SEC,
        )
        self.assertEqual(window["expected_candle_rows"], 179 * 24)
        self.assertEqual(window["interval"], "[start,end)")
        self.assertEqual(window["window_start_sec"] % HOUR_SEC, 0)
        self.assertEqual(window["window_end_sec"] % HOUR_SEC, 0)

    def test_funding_audit_preserves_jitter_and_detects_cadence_change(self) -> None:
        hours = HOUR_SEC
        timestamps = [0, 4 * hours + 2, 8 * hours - 1, 12 * hours + 1]
        timestamps += [20 * hours + 2, 28 * hours + 1, 36 * hours + 2, 44 * hours + 1]
        rows = [
            {"ts": float(ts), "funding_rate": -0.001 if index % 2 else 0.001}
            for index, ts in enumerate(timestamps)
        ]

        report = audit_funding_events(
            rows,
            start_sec=0,
            end_sec=48 * hours,
            minimum_coverage=0.98,
            jitter_tolerance_sec=5,
        )

        self.assertTrue(report["accepted"])
        self.assertEqual(report["exact_settlement_timestamps"], timestamps)
        self.assertEqual(report["duplicate_count"], 0)
        self.assertEqual(report["missing_settlement_count"], 0)
        self.assertEqual(report["cadence_change_count"], 1)
        self.assertGreaterEqual(len(report["cadence_schedule"]), 2)
        self.assertEqual(report["positive_rate_count"], 4)
        self.assertEqual(report["negative_rate_count"], 4)

    def test_funding_audit_rejects_exact_duplicates_and_schedule_gaps(self) -> None:
        rows = [
            {"ts": 0.0, "funding_rate": 0.001},
            {"ts": float(4 * HOUR_SEC), "funding_rate": 0.001},
            {"ts": float(4 * HOUR_SEC), "funding_rate": 0.002},
            {"ts": float(12 * HOUR_SEC), "funding_rate": 0.001},
            {"ts": float(16 * HOUR_SEC), "funding_rate": 0.001},
        ]
        report = audit_funding_events(
            rows,
            start_sec=0,
            end_sec=20 * HOUR_SEC,
            minimum_coverage=0.98,
        )

        self.assertFalse(report["accepted"])
        self.assertEqual(report["duplicate_count"], 1)
        self.assertGreaterEqual(report["missing_settlement_count"], 1)


class HistoricalBasisV2PreflightTests(unittest.TestCase):
    def test_preflight_is_identity_ordered_public_only_and_reads_no_market_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pit_path, registry_path, daily_manifest, _ = _write_preflight_inputs(root, count=21)
            clients = {"mexc": FakeBoundaryClient(), "gateio": FakeBoundaryClient()}
            output_path = root / "preflight.json"

            result = run_historical_basis_v2_preflight(
                pit_path,
                registry_path,
                daily_manifest,
                output_path,
                clients=clients,
                max_runtime_sec=300,
                estimated_request_latency_sec=0.1,
            )

            self.assertEqual(result["verdict"], "PREFLIGHT_ACCEPTED_NOT_COLLECTED")
            self.assertEqual(len(result["universe"]["candidates"]), 20)
            canonical_ids = [
                row["canonical_asset_id"] for row in result["universe"]["candidates"]
            ]
            self.assertEqual(canonical_ids, sorted(canonical_ids))
            self.assertEqual(result["universe"]["selection_basis"], "identity_lifecycle_availability_only")
            self.assertNotIn("volume", json.dumps(result["universe"]).lower())
            self.assertEqual(
                result["data_access_audit"],
                {
                    "returns_read": False,
                    "pnl_read": False,
                    "signals_read": False,
                    "oos_metrics_read": False,
                    "liquidity_used_for_selection": False,
                },
            )
            self.assertLessEqual(result["request_estimate"]["worst_case_runtime_sec"], 5_400)
            self.assertEqual(result["window"]["expected_candle_rows"], 179 * 24)
            self.assertEqual(result["next_allowed_command"], "fast-edge-basis-v2-plan")
            self.assertTrue(output_path.is_file())

            for client in clients.values():
                self.assertEqual(len(client.calls), 20 * 3 * 2)
                self.assertTrue(all(end - start == HOUR_SEC for _, _, start, end in client.calls))

    def test_preflight_excludes_binance_and_structural_categories_before_probes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pit_path, registry_path, daily_manifest, _ = _write_preflight_inputs(root, count=10)
            pit = json.loads(pit_path.read_text(encoding="utf-8"))
            for venue in ("mexc", "gateio"):
                pit["symbols"][f"{venue}|A8_USDT"]["row"]["binance_spot_listed"] = True
                pit["symbols"][f"{venue}|A8_USDT"]["row"]["eligible_non_binance_spot"] = False
            pit_path.write_text(json.dumps(pit), encoding="utf-8")
            with registry_path.open(encoding="utf-8") as handle:
                registry = list(csv.DictReader(handle))
            registry[9]["name"] = "Wrapped Asset 9"
            with registry_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(registry[0]))
                writer.writeheader()
                writer.writerows(registry)

            result = run_historical_basis_v2_preflight(
                pit_path,
                registry_path,
                daily_manifest,
                root / "preflight.json",
                clients={"mexc": FakeBoundaryClient(), "gateio": FakeBoundaryClient()},
                max_runtime_sec=300,
            )

            self.assertEqual(result["verdict"], "PREFLIGHT_ACCEPTED_NOT_COLLECTED")
            self.assertEqual(result["universe"]["candidate_count"], 8)
            self.assertEqual(result["rejections_by_reason"]["binance_spot_or_unverified"], 1)
            self.assertEqual(result["rejections_by_reason"]["excluded_category"], 1)

    def test_cli_contract_uses_daily_cache_manifest(self) -> None:
        args = build_arg_parser().parse_args(
            [
                "--pit-state",
                "pit.json",
                "--coin-registry",
                "coins.csv",
                "--daily-cache-manifest",
                "daily/manifest.json",
                "--output",
                "preflight.json",
                "--max-runtime-sec",
                "900",
            ]
        )
        self.assertEqual(args.daily_cache_manifest, "daily/manifest.json")
        self.assertEqual(args.max_runtime_sec, 900)


if __name__ == "__main__":
    unittest.main()
