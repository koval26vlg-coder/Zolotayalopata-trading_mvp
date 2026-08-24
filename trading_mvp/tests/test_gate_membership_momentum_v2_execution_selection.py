from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import gate_membership_momentum_v2_execution_probe as probe  # noqa: E402
from gate_membership_momentum import DAY_SEC  # noqa: E402
from test_gate_membership_momentum_v2_execution_probe import (  # noqa: E402
    START_DAY,
    _historical_accept,
)


selection = importlib.import_module("gate_membership_momentum_v2_execution_selection")


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _probe_plan(root: Path) -> tuple[Path, dict]:
    oos_plan_path, oos_plan, oos_result_path, oos_result = _historical_accept(root)
    path = root / "probe-plan.json"
    plan = probe.build_execution_probe_plan(
        oos_plan_path=oos_plan_path,
        expected_oos_plan_hash=oos_plan["plan_hash"],
        oos_result_path=oos_result_path,
        expected_oos_result_hash=oos_result["deterministic_result_hash"],
        output_path=path,
        run_id="membership-momentum-v2-probe",
        not_before_day=START_DAY + 223,
        generated_at_utc="2026-07-17T09:00:00Z",
    )
    return path, plan


def _snapshot(
    root: Path,
    plan: dict,
    *,
    market_count: int = 30,
    include_future_bar: bool = False,
) -> tuple[Path, dict]:
    signal_day = int(plan["target_event_contract"]["target_signal_day"])
    signal_close_ts = int(plan["target_event_contract"]["target_signal_close_ts"])
    rows = []
    for index in range(market_count):
        bars = []
        for day in range(signal_day - 30, signal_day + 1):
            relative = day - (signal_day - 30)
            bars.append(
                {
                    "ts": day * DAY_SEC,
                    "close": 100.0 + relative * (index + 1) / 100.0,
                    "volume_quote": 2_000_000.0 + index,
                    "closed": True,
                }
            )
        if include_future_bar and index == 0:
            bars.append(
                {
                    "ts": (signal_day + 1) * DAY_SEC,
                    "close": 999.0,
                    "volume_quote": 2_000_000.0,
                    "closed": False,
                }
            )
        rows.append(
            {
                "exchange": "gateio",
                "market_type": "usdt_linear_perpetual",
                "canonical_asset_id": f"asset-{index:02d}",
                "symbol": f"ASSET{index:02d}_USDT",
                "base": f"ASSET{index:02d}",
                "identity_confirmed": True,
                "binance_spot_excluded": True,
                "prohibited_asset_class": False,
                "lifecycle_valid_at_signal": True,
                "status": "tradable",
                "bars": bars,
            }
        )
    payload = {
        "schema": selection.MARKET_SNAPSHOT_SCHEMA,
        "final": True,
        "decision": selection.MARKET_SNAPSHOT_READY_DECISION,
        "exchange": "gateio",
        "market_type": "usdt_linear_perpetual",
        "public_data_only": True,
        "private_api_keys": False,
        "live_orders": False,
        "target_signal_day": signal_day,
        "as_of_ts": signal_close_ts + 60,
        "as_of_utc": _iso(signal_close_ts + 60),
        "rows": rows,
        "data_access_audit": {
            "oos_events_used_for_selection": False,
            "future_bars_read": False,
            "manual_shortlist": False,
        },
    }
    payload["artifact_hash"] = selection.market_snapshot_hash(payload)
    path = root / "market-snapshot.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, payload


class GateMembershipMomentumV2ExecutionSelectionTests(unittest.TestCase):
    def test_run_mvp_exposes_selection_routes(self) -> None:
        wrapper = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((Path(__file__).resolve().parents[1] / "run_mvp.ps1"))
        self.assertIn('"fast-edge-membership-momentum-v2-execution-selection"', wrapper)
        self.assertIn('"fast-edge-membership-momentum-v2-execution-selection-validate"', wrapper)
        self.assertIn("gate_membership_momentum_v2_execution_selection.py", wrapper)

    def test_selection_is_causal_hash_bound_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            snapshot_path, snapshot = _snapshot(root, probe_plan)
            target_close = int(probe_plan["target_event_contract"]["target_signal_close_ts"])
            output = root / "selection.json"
            result = selection.build_selection_artifact(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                market_snapshot_manifest_path=snapshot_path,
                expected_market_snapshot_hash=snapshot["artifact_hash"],
                output_path=output,
                generated_at_utc=_iso(target_close + 120),
            )

            self.assertEqual(result["decision"], selection.SELECTION_READY_DECISION)
            self.assertEqual(result["artifact_hash"], selection.selection_artifact_hash(result))
            self.assertEqual(
                result["next_allowed_command"],
                "fast-edge-membership-momentum-v2-execution-probe-window-plan",
            )
            self.assertEqual(result["selection_summary"]["scored_markets"], 30)
            self.assertEqual(result["selection_summary"]["assets_per_side"], 5)
            self.assertEqual(len(result["selected_positions"]), 10)
            shorts = [row for row in result["selected_positions"] if row["side"] == "short"]
            longs = [row for row in result["selected_positions"] if row["side"] == "long"]
            self.assertEqual([row["canonical_asset_id"] for row in shorts], [f"asset-{i:02d}" for i in range(5)])
            self.assertEqual([row["canonical_asset_id"] for row in longs], [f"asset-{i:02d}" for i in range(25, 30)])
            self.assertNotIn("oos_events", result)
            self.assertNotIn("manual_shortlist", result)
            self.assertTrue(result["selection_contract"]["selection_frozen_before_first_snapshot"])

            validated = selection.validate_selection_artifact(output, result["artifact_hash"])
            self.assertEqual(validated["artifact_hash"], result["artifact_hash"])
            repeated = selection.build_selection_artifact(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                market_snapshot_manifest_path=snapshot_path,
                expected_market_snapshot_hash=snapshot["artifact_hash"],
                output_path=None,
                generated_at_utc=_iso(target_close + 120),
            )
            self.assertEqual(repeated["artifact_hash"], result["artifact_hash"])

    def test_selection_refuses_before_signal_close_or_after_first_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            snapshot_path, snapshot = _snapshot(root, probe_plan)
            target_close = int(probe_plan["target_event_contract"]["target_signal_close_ts"])
            first_window = int(probe_plan["execution_contract"]["windows"][0]["start_ts"])

            with self.assertRaisesRegex(ValueError, "target signal close"):
                selection.build_selection_artifact(
                    probe_plan_path=probe_path,
                    expected_probe_plan_hash=probe_plan["plan_hash"],
                    market_snapshot_manifest_path=snapshot_path,
                    expected_market_snapshot_hash=snapshot["artifact_hash"],
                    output_path=None,
                    generated_at_utc=_iso(target_close - 1),
                )
            with self.assertRaisesRegex(ValueError, "first execution window"):
                selection.build_selection_artifact(
                    probe_plan_path=probe_path,
                    expected_probe_plan_hash=probe_plan["plan_hash"],
                    market_snapshot_manifest_path=snapshot_path,
                    expected_market_snapshot_hash=snapshot["artifact_hash"],
                    output_path=None,
                    generated_at_utc=_iso(first_window),
                )

    def test_selection_rejects_future_or_open_bar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            snapshot_path, snapshot = _snapshot(root, probe_plan, include_future_bar=True)
            target_close = int(probe_plan["target_event_contract"]["target_signal_close_ts"])

            with self.assertRaisesRegex(ValueError, "future or open daily bar"):
                selection.build_selection_artifact(
                    probe_plan_path=probe_path,
                    expected_probe_plan_hash=probe_plan["plan_hash"],
                    market_snapshot_manifest_path=snapshot_path,
                    expected_market_snapshot_hash=snapshot["artifact_hash"],
                    output_path=None,
                    generated_at_utc=_iso(target_close + 120),
                )

    def test_insufficient_universe_is_terminal_without_threshold_weakening(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            snapshot_path, snapshot = _snapshot(root, probe_plan, market_count=19)
            target_close = int(probe_plan["target_event_contract"]["target_signal_close_ts"])
            result = selection.build_selection_artifact(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                market_snapshot_manifest_path=snapshot_path,
                expected_market_snapshot_hash=snapshot["artifact_hash"],
                output_path=None,
                generated_at_utc=_iso(target_close + 120),
            )

            self.assertEqual(result["decision"], selection.INSUFFICIENT_UNIVERSE_DECISION)
            self.assertEqual(result["next_allowed_command"], "none_membership_momentum_v2_branch_closed_no_retune")
            self.assertEqual(result["selection_summary"]["minimum_scored_markets"], 20)
            self.assertEqual(result["selected_positions"], [])
            self.assertFalse(result["execution_probe_collect_allowed"])

    def test_validator_rejects_resigned_manual_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan = _probe_plan(root)
            snapshot_path, snapshot = _snapshot(root, probe_plan)
            target_close = int(probe_plan["target_event_contract"]["target_signal_close_ts"])
            output = root / "selection.json"
            result = selection.build_selection_artifact(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                market_snapshot_manifest_path=snapshot_path,
                expected_market_snapshot_hash=snapshot["artifact_hash"],
                output_path=output,
                generated_at_utc=_iso(target_close + 120),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["frozen_contract"]["selected_positions"][0]["canonical_asset_id"] = "manual-asset"
            payload["selected_positions"] = payload["frozen_contract"]["selected_positions"]
            payload["artifact_hash"] = selection.selection_artifact_hash(payload)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "selection"):
                selection.validate_selection_artifact(output, payload["artifact_hash"])
            self.assertNotEqual(result["artifact_hash"], payload["artifact_hash"])

    def test_probe_plan_routes_to_selection_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _path, plan = _probe_plan(Path(tmp))
            self.assertEqual(
                plan["next_allowed_command"],
                "fast-edge-membership-momentum-v2-execution-selection",
            )


if __name__ == "__main__":
    unittest.main()
