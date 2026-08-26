from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "trading_mvp" / "src" / "funding_forward_history_audit.py"
RUNNER = PROJECT_ROOT / "tools" / "run_weekly_forward_collect.ps1"


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> dict[str, Path]:
    analysis = root / "analysis"
    daily = root / "daily"
    universe = root / "coins_not_on_binance_full_2026-05-29.csv"
    universe.write_text("rank,name,symbol,coin_id\n1,Akedo,AKE,ake-akedo\n", encoding="utf-8")
    snapshots = [
        ("20260706", "funding_pairs_v1", "execution_gate_v1", 5, None),
        ("20260713", "funding_pairs_v1", "execution_gate_v1", 0, None),
        ("20260720", "funding_pairs_v2", "execution_gate_v2", 0, (-29.75, 0.879, 21.35, 21.90, 1671.56)),
        ("20260803", "funding_pairs_v2", "execution_gate_v2", 0, (-28.07, 0.890, 19.67, 20.43, 1942.13)),
        ("20260810", "funding_pairs_v2", "execution_gate_v2", 0, (-29.68, 0.901, 21.28, 22.81, 2229.50)),
    ]
    latest_manifest: Path | None = None
    latest_pairs: Path | None = None
    latest_execution: Path | None = None
    for stamp, pair_schema, execution_schema, errors, ake_values in snapshots:
        run_id = f"daily_forward_{stamp}"
        run_dir = daily / run_id
        manifest = {
            "schema": "daily_collect_v1",
            "run_id": run_id,
            "started_at_utc": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T06:05:00+00:00",
            "finished_at_utc": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T06:17:00+00:00",
            "params": {
                "exchanges": ["mexc", "gateio"],
                "days": 200,
                "top": 200,
                "universe_csv": str(universe),
            },
            "error_count": errors,
            "statuses": [],
        }
        manifest_path = run_dir / "manifest.json"
        _write_json(manifest_path, manifest)

        if pair_schema == "funding_pairs_v2":
            spread, consistency, pair_net, _, _ = ake_values or (0, 0, 0, 0, 0)
            pairs = [
                {
                    "symbol": "AKE_USDT",
                    "base": "AKE",
                    "spread_gate_minus_mexc": {
                        "aligned_days": 91,
                        "annualized_spread_pct": spread,
                        "abs_annualized_spread_pct": abs(spread),
                        "sign_consistency": consistency,
                        "direction": "short_b_long_a",
                    },
                    "net_abs_annualized_after_costs_pct": pair_net,
                    "min_volume_24h_quote": 1_000_000.0,
                    "mexc_spot_available": True,
                    "non_binance_baseline": True,
                }
            ]
            pair_params = {
                "window_days": 90,
                "min_aligned_days": 30,
                "turnover_per_year": 12.0,
                "non_binance_only": True,
                "route": "cross_venue_perp_perp",
                "cycle_cost_bps": 70.0,
                "spread_definition": "daily_funding_gate_minus_mexc",
            }
            cost_profile: dict[str, object] | None = {"profile": "base_api", "funding_haircut": 1.0}
        else:
            pairs = []
            pair_params = {
                "window_days": 90,
                "min_aligned_days": 30,
                "cross_exchange_round_trip_bps": -2.0,
                "spread_definition": "daily_funding_gate_minus_mexc",
            }
            cost_profile = None
        pairs_path = analysis / f"funding_pairs_forward_{stamp}.json"
        pair_payload: dict[str, object] = {
            "schema": pair_schema,
            "created_at_utc": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T06:18:00+00:00",
            "dataset": str(run_dir),
            "params": pair_params,
            "shared_symbols_total": len(pairs),
            "pairs_analyzed": len(pairs),
            "pairs": pairs,
        }
        if cost_profile is not None:
            pair_payload["cost_profile"] = cost_profile
            pair_payload["shared_symbols_before_non_binance_filter"] = len(pairs)
        _write_json(pairs_path, pair_payload)

        candidates: list[dict[str, object]] = []
        if ake_values is not None:
            spread, consistency, _, execution_net, capacity = ake_values
            candidates.append(
                {
                    "symbol": "AKE_USDT",
                    "errors": [],
                    "g_construction_perp_perp": {
                        "spread_annual_pct": spread,
                        "sign_consistency": consistency,
                        "capacity_usd": capacity,
                        "net_annual_pct": execution_net,
                    },
                }
            )
        execution_payload: dict[str, object] = {
            "schema": execution_schema,
            "created_at_utc": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}T06:19:00+00:00",
            "pairs_source": str(pairs_path),
            "params": {"auto_candidates": True, "turnover_per_year": 12.0},
            "caveat": "one-time orderbook snapshot",
            "candidates": candidates,
        }
        if execution_schema == "execution_gate_v2":
            execution_payload["cost_profile"] = cost_profile
        execution_path = analysis / f"execution_gate_forward_{stamp}.json"
        _write_json(execution_path, execution_payload)
        if stamp == "20260810":
            latest_manifest = manifest_path
            latest_pairs = pairs_path
            latest_execution = execution_path

    assert latest_manifest is not None and latest_pairs is not None and latest_execution is not None

    current_audit = analysis / "funding_forward_audit_20260810.json"
    _write_json(
        current_audit,
        {
            "schema": "funding_forward_audit_v1",
            "audit_passed": True,
            "decision": "WATCHLIST_ONLY_NOT_EDGE_EVIDENCE",
            "acceptance_allowed": False,
            "research_only": True,
            "inputs": {
                "manifest": {"path": str(latest_manifest), "sha256": _sha256(latest_manifest)},
                "pairs": {"path": str(latest_pairs), "sha256": _sha256(latest_pairs)},
                "execution": {"path": str(latest_execution), "sha256": _sha256(latest_execution)},
            },
            "candidates": [
                {
                    "symbol": "AKE_USDT",
                    "identity": {
                        "status": "OFFICIAL_SAME_ASSET_VERIFIED",
                        "source_coin_id": "ake-akedo",
                    },
                }
            ],
            "proof_gates": {
                "chronological_oos": "not_run",
                "walk_forward": "not_run",
                "stress": "not_run",
            },
        },
    )
    return {
        "analysis": analysis,
        "daily": daily,
        "current_audit": current_audit,
        "output": analysis / "funding_forward_history_audit_20260810.json",
    }


def _run(paths: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--analysis-dir",
            str(paths["analysis"]),
            "--daily-dir",
            str(paths["daily"]),
            "--through-stamp",
            "20260810",
            "--symbol",
            "AKE_USDT",
            "--current-audit",
            str(paths["current_audit"]),
            "--out",
            str(paths["output"]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


class FundingForwardHistoryAuditTests(unittest.TestCase):
    def test_overlapping_v2_snapshots_cannot_be_counted_as_independent_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            completed = _run(paths)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))

        self.assertTrue(audit["audit_passed"])
        self.assertEqual(audit["decision"], "OVERLAPPING_SUMMARIES_NOT_INDEPENDENT_EDGE_EVIDENCE")
        self.assertFalse(audit["promotion_allowed"])
        self.assertEqual(audit["history_contract"]["total_snapshot_count"], 5)
        self.assertEqual(audit["history_contract"]["comparable_snapshot_count"], 3)
        self.assertEqual(audit["history_contract"]["excluded_snapshot_count"], 2)
        self.assertEqual(audit["window_overlap"]["cadence_days"], [14, 7])
        self.assertEqual(audit["window_overlap"]["first_last_overlap_days"], 70)
        self.assertEqual(audit["window_overlap"]["unique_calendar_days"], 112)
        self.assertEqual(audit["window_overlap"]["total_window_day_observations"], 273)
        self.assertEqual(audit["window_overlap"]["new_days_after_first_snapshot"], 21)
        self.assertEqual(audit["window_overlap"]["independent_holdout_windows"], 0)
        self.assertEqual(audit["symbol_track"]["comparable_presence_count"], 3)
        self.assertEqual(audit["symbol_track"]["direction_count"], 1)
        self.assertEqual(audit["symbol_track"]["identity_status"], "OFFICIAL_SAME_ASSET_VERIFIED")
        self.assertEqual(audit["proof_gates"]["chronological_oos"], "not_run")
        self.assertFalse(audit["safety"]["returns_or_pnl_read"])
        self.assertFalse(audit["safety"]["market_rows_read"])

    def test_v2_cost_contract_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            target = paths["analysis"] / "funding_pairs_forward_20260803.json"
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["params"]["cycle_cost_bps"] = 69.0
            _write_json(target, payload)
            completed = _run(paths)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))

        self.assertFalse(audit["audit_passed"])
        self.assertEqual(audit["decision"], "FUNDING_FORWARD_HISTORY_AUDIT_REJECTED_INVALID_EVIDENCE")
        self.assertIn("comparable_cost_contract_drift", audit["failures"])

    def test_deterministic_hash_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            first = _run(paths)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_audit = json.loads(paths["output"].read_text(encoding="utf-8"))
            second = _run(paths)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            second_audit = json.loads(paths["output"].read_text(encoding="utf-8"))

        self.assertEqual(first_audit["deterministic_result_hash"], second_audit["deterministic_result_hash"])

    def test_stale_current_audit_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _fixture(Path(tmp))
            payload = json.loads(paths["current_audit"].read_text(encoding="utf-8"))
            payload["inputs"]["pairs"]["sha256"] = "0" * 64
            _write_json(paths["current_audit"], payload)
            completed = _run(paths)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            audit = json.loads(paths["output"].read_text(encoding="utf-8"))

        self.assertFalse(audit["audit_passed"])
        self.assertIn("current_audit_latest_pairs_hash_mismatch", audit["failures"])

    def test_weekly_runner_emits_history_audit(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("funding_forward_history_audit.py", source)
        self.assertIn("funding_forward_history_audit_$stamp.json", source)
        self.assertIn("history_exit=$historyExit", source)


if __name__ == "__main__":
    unittest.main()
