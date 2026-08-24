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

from gate_historical_membership_history_plan import (  # noqa: E402
    HISTORY_PLAN_DECISION,
    INSUFFICIENT_UNIVERSE_DECISION,
    build_history_plan,
    load_unique_coin_registry,
    sha256_json,
)


def _write_daily_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "daily_forward_fixture",
                "params": {
                    "exchanges": ["mexc", "gateio"],
                    "days": 200,
                    "top": 200,
                    "start_sec": 1_764_633_600,
                    "end_sec": 1_781_913_605,
                },
                "universe": [],
                "error_count": 0,
            }
        ),
        encoding="utf-8",
    )


def _write_registry(path: Path, symbols: list[tuple[str, str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "name", "symbol", "coin_id"])
        writer.writeheader()
        for rank, (name, symbol, coin_id) in enumerate(symbols, start=1):
            writer.writerow({"rank": rank, "name": name, "symbol": symbol, "coin_id": coin_id})


def _probe_artifact_hash(report: dict) -> str:
    return sha256_json(
        {
            key: value
            for key, value in report.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
        }
    )


def _write_probe(path: Path, rows: list[dict], *, accepted: bool = True, final: bool = True) -> dict:
    report = {
        "schema": "trading_mvp_gate_historical_membership_probe_v2",
        "generated_at_utc": "2026-07-17T02:00:00Z",
        "run_id": "gate_membership_fixture",
        "plan_hash": "a" * 64,
        "final": final,
        "decision": (
            "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_ACCEPTED_READY_FOR_BACKFILL_PLANONLY"
            if accepted
            else "GATE_HISTORICAL_MEMBERSHIP_SOURCE_REJECTED"
        ),
        "accepted": accepted,
        "runtime_sec": 1.0,
        "quality": {"contracts": len(rows), "accepted": accepted},
        "rows": rows,
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_read": False,
        },
    }
    report["artifact_hash"] = _probe_artifact_hash(report)
    path.write_text(json.dumps(report), encoding="utf-8")
    return report


def _contract(symbol: str, *, start: int = 1_700_000_000, end: int | None = None) -> dict:
    return {
        "exchange": "gateio",
        "symbol": f"{symbol}_USDT",
        "base": symbol,
        "quote": "USDT",
        "instrument_type": "linear_perpetual",
        "contract_type": "crypto",
        "lifecycle_status": "delisted" if end else "trading",
        "listed_from_ts": start,
        "listed_to_ts": end,
        "active_at_snapshot": end is None,
        "contract_multiplier": 0.01,
        "funding_interval_sec": 28_800,
        "order_size_min_contracts": 1.0,
        "order_size_max_contracts": 1_000_000.0,
    }


class GateMembershipHistoryPlanTests(unittest.TestCase):
    def _fixture(self, root: Path, count: int = 24) -> tuple[Path, Path, Path, dict]:
        manifest = root / "manifest.json"
        registry = root / "coins.csv"
        probe = root / "probe.json"
        _write_daily_manifest(manifest)
        symbols = [(f"Asset {index}", f"A{index:02d}", f"asset-{index}") for index in range(count)]
        _write_registry(registry, symbols)
        report = _write_probe(probe, [_contract(symbol) for _, symbol, _ in symbols])
        return manifest, registry, probe, report

    def test_plan_is_deterministic_hash_bound_and_does_not_read_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, registry, probe, report = self._fixture(root)
            first = root / "first.json"
            second = root / "second.json"

            plan_a = build_history_plan(
                probe_report_path=probe,
                expected_probe_plan_hash=report["plan_hash"],
                expected_probe_artifact_hash=report["artifact_hash"],
                daily_manifest_path=manifest,
                coin_registry_path=registry,
                output_path=first,
                run_id="membership_history_fixture",
                max_runtime_sec=7200,
                generated_at_utc="2026-07-17T03:00:00Z",
            )
            plan_b = build_history_plan(
                probe_report_path=probe,
                expected_probe_plan_hash=report["plan_hash"],
                expected_probe_artifact_hash=report["artifact_hash"],
                daily_manifest_path=manifest,
                coin_registry_path=registry,
                output_path=second,
                run_id="membership_history_fixture",
                max_runtime_sec=7200,
                generated_at_utc="2026-07-17T04:00:00Z",
            )

            self.assertEqual(plan_a["decision"], HISTORY_PLAN_DECISION)
            self.assertEqual(plan_a["plan_hash"], plan_b["plan_hash"])
            self.assertFalse(plan_a["network_calls_now"])
            self.assertFalse(plan_a["collect_allowed_now"])
            self.assertEqual(plan_a["next_allowed_command"], "fast-edge-membership-history-collect")
            self.assertIn(plan_a["plan_hash"], plan_a["approval_phrase"])
            self.assertEqual(len(plan_a["code_provenance"]["collector_module_sha256"]), 64)
            self.assertEqual(len(plan_a["code_provenance"]["quality_module_sha256"]), 64)
            self.assertEqual(len(plan_a["code_provenance"]["momentum_core_module_sha256"]), 64)
            self.assertEqual(len(plan_a["code_provenance"]["train_module_sha256"]), 64)
            self.assertEqual(len(plan_a["code_provenance"]["oos_module_sha256"]), 64)
            self.assertEqual(plan_a["history_window"]["days"], 380)
            self.assertEqual(
                plan_a["split_contract"],
                {
                    "warmup": {
                        "start_sec": plan_a["history_window"]["start_sec"],
                        "end_sec": plan_a["history_window"]["start_sec"] + 30 * 86_400,
                        "days": 30,
                    },
                    "train": {
                        "start_sec": plan_a["history_window"]["start_sec"] + 30 * 86_400,
                        "end_sec": plan_a["history_window"]["start_sec"] + 170 * 86_400,
                        "days": 140,
                    },
                    "oos": {
                        "start_sec": plan_a["history_window"]["start_sec"] + 170 * 86_400,
                        "end_sec": plan_a["history_window"]["end_sec"],
                        "days": 210,
                        "folds": 5,
                        "fold_days": 42,
                    },
                },
            )
            self.assertEqual(plan_a["universe"]["minimum_canonical_assets"], 20)
            self.assertEqual(
                plan_a["strategy_contract"]["frozen_parameters"],
                {
                    "lookback_days": 30,
                    "hold_days": 7,
                    "rebalance_every_days": 7,
                    "min_per_side": 5,
                    "minimum_scored_markets": 20,
                    "bucket_rule": "max(min_per_side,floor(scored_markets/10))",
                    "liquidity_lookback_days": 7,
                    "minimum_median_quote_volume": 1000000.0,
                    "signal_price": "closed_daily_close",
                    "entry_price": "next_closed_daily_open",
                    "exit_price": "daily_open_after_hold_days",
                    "parameter_selection": "forbidden",
                },
            )
            self.assertEqual(plan_a["evidence_scope"], "gate_only_weaker_evidence")
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
            self.assertGreater(len(plan_a["archive_tasks"]), 0)
            self.assertTrue(first.is_file())

    def test_probe_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, registry, probe, report = self._fixture(root)

            with self.assertRaisesRegex(ValueError, "probe artifact hash mismatch"):
                build_history_plan(
                    probe_report_path=probe,
                    expected_probe_plan_hash=report["plan_hash"],
                    expected_probe_artifact_hash="0" * 64,
                    daily_manifest_path=manifest,
                    coin_registry_path=registry,
                    output_path=None,
                    run_id="hash_mismatch",
                )

    def test_unaccepted_or_incomplete_probe_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, registry, probe, _ = self._fixture(root)
            report = _write_probe(probe, [_contract("A00")], accepted=False, final=True)

            with self.assertRaisesRegex(ValueError, "probe is not accepted and final"):
                build_history_plan(
                    probe_report_path=probe,
                    expected_probe_plan_hash=report["plan_hash"],
                    expected_probe_artifact_hash=report["artifact_hash"],
                    daily_manifest_path=manifest,
                    coin_registry_path=registry,
                    output_path=None,
                    run_id="rejected_probe",
                )

    def test_registry_collisions_and_non_crypto_wrappers_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "coins.csv"
            _write_registry(
                registry,
                [
                    ("Alpha", "AAA", "alpha"),
                    ("First collision", "DUP", "dup-1"),
                    ("Second collision", "DUP", "dup-2"),
                    ("Wrapped Ether", "WETH", "wrapped-ether"),
                    ("USD Stablecoin", "USDX", "usdx"),
                ],
            )

            unique, excluded = load_unique_coin_registry(registry)

            self.assertEqual(set(unique), {"AAA"})
            self.assertEqual(excluded["DUP"], "ticker_collision")
            self.assertEqual(excluded["WETH"], "wrapped_or_staked_asset")
            self.assertEqual(excluded["USDX"], "stable_asset")

    def test_lifecycle_overlap_limits_symbols_and_archive_months(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            registry = root / "coins.csv"
            probe = root / "probe.json"
            _write_daily_manifest(manifest)
            symbols = [(f"Asset {index}", f"A{index:02d}", f"asset-{index}") for index in range(24)]
            symbols.append(("Expired", "OLD", "old"))
            _write_registry(registry, symbols)
            rows = [_contract(symbol) for _, symbol, _ in symbols[:-1]]
            rows.append(_contract("OLD", start=1_500_000_000, end=1_600_000_000))
            report = _write_probe(probe, rows)

            plan = build_history_plan(
                probe_report_path=probe,
                expected_probe_plan_hash=report["plan_hash"],
                expected_probe_artifact_hash=report["artifact_hash"],
                daily_manifest_path=manifest,
                coin_registry_path=registry,
                output_path=None,
                run_id="lifecycle_fixture",
            )

            self.assertNotIn("OLD_USDT", {row["symbol"] for row in plan["universe"]["eligible"]})
            self.assertTrue(
                all(task["symbol"] != "OLD_USDT" for task in plan["archive_tasks"])
            )
            self.assertEqual(
                {task["archive_type"] for task in plan["archive_tasks"]},
                {"candlesticks_1h", "funding_applies"},
            )

    def test_insufficient_identity_universe_is_terminal_plan_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, registry, probe, report = self._fixture(root, count=10)

            plan = build_history_plan(
                probe_report_path=probe,
                expected_probe_plan_hash=report["plan_hash"],
                expected_probe_artifact_hash=report["artifact_hash"],
                daily_manifest_path=manifest,
                coin_registry_path=registry,
                output_path=None,
                run_id="small_universe",
            )

            self.assertEqual(plan["decision"], INSUFFICIENT_UNIVERSE_DECISION)
            self.assertEqual(plan["next_allowed_command"], "none_membership_history_branch_closed")
            self.assertNotIn("approval_phrase", plan)

    def test_history_collect_runtime_cap_is_two_hours(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, registry, probe, report = self._fixture(root)

            with self.assertRaisesRegex(ValueError, "max_runtime_sec must be in"):
                build_history_plan(
                    probe_report_path=probe,
                    expected_probe_plan_hash=report["plan_hash"],
                    expected_probe_artifact_hash=report["artifact_hash"],
                    daily_manifest_path=manifest,
                    coin_registry_path=registry,
                    output_path=None,
                    run_id="too_long",
                    max_runtime_sec=7201,
                )


class GateMembershipHistoryWrapperTests(unittest.TestCase):
    def test_run_mvp_exposes_history_plan_action(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(wrapper)

        self.assertIn('"fast-edge-membership-history-plan"', text)
        self.assertIn("gate_historical_membership_history_plan.py", text)
        self.assertIn("ExpectedArtifactHash is required for fast-edge-membership-history-plan", text)
        self.assertIn("MaxRuntimeSec must be <= 7200 for fast-edge-membership-history-plan", text)


if __name__ == "__main__":
    unittest.main()
