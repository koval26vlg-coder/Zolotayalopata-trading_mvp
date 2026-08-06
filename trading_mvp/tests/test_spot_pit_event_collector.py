from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spot_pit_event_collector import (  # noqa: E402
    BINANCE_INFO,
    GATE_PAIRS,
    GATE_TICKERS,
    MEXC_24H,
    MEXC_BOOK,
    MEXC_INFO,
    PublicCycleProvider,
    collect,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(root: Path) -> tuple[Path, str, Path, str]:
    plan = root / "plan.json"
    preflight = root / "preflight.json"
    plan.write_text(
        json.dumps({"schema": "spot_pit_event_forward_plan_v1", "research_only": True, "strategy_accepted": False}),
        encoding="utf-8",
    )
    preflight.write_text(
        json.dumps(
            {
                "schema": "spot_pit_event_public_preflight_v1",
                "accepted": True,
                "plan_sha256": _sha(plan),
                "generated_at": "2026-01-01T00:00:00+00:00",
                "frozen_universe_preview": [
                    {"rank": 1, "base": "B01", "name": "B01", "coin_id": "b01", "venues": ["mexc", "gateio"]},
                    {"rank": 2, "base": "B02", "name": "B02", "coin_id": "b02", "venues": ["mexc", "gateio"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    return plan, _sha(plan), preflight, _sha(preflight)


def _market(exchange: str, base: str) -> dict[str, object]:
    return {
        "exchange": exchange,
        "symbol": f"{base}USDT" if exchange == "mexc" else f"{base}_USDT",
        "base": base,
        "bid": 99.0,
        "ask": 100.0,
        "bid_qty": 10.0 if exchange == "mexc" else None,
        "ask_qty": 11.0 if exchange == "mexc" else None,
        "last": 99.5,
        "quote_volume_24h": 1000000.0,
        "spread_bps": 100.5,
    }


def _report(cycle: int, *, missing_gate_b01: bool = False, include_new: bool = False) -> dict[str, object]:
    bases = ["B01", "B02"] + (["B03"] if include_new else [])
    mexc = {base: _market("mexc", base) for base in bases}
    gate = {base: _market("gateio", base) for base in bases if not (missing_gate_b01 and base == "B01")}
    return {
        "snapshot_ts": f"2026-01-01T00:0{cycle}:00+00:00",
        "markets": {"mexc": mexc, "gateio": gate},
        "binance_bases": [],
        "binance_reference_available": True,
        "successful_exchanges": ["mexc", "gateio"],
        "errors": {},
        "metadata_refreshed": cycle == 1,
    }


class SpotPitEventCollectorTests(unittest.TestCase):
    def test_one_cycle_writes_segment_state_journal_and_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_hash, preflight, preflight_hash = _artifacts(root)
            output = root / "runs"
            manifest = collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=output,
                run_id="run-a",
                duration_sec=0,
                interval_sec=1,
                segment_sec=2,
                provider=lambda cycle: _report(cycle, include_new=True),
            )
            run_dir = output / "run-a"
            rows = [json.loads(line) for line in (run_dir / "segments" / "segment_000001.jsonl").read_text(encoding="utf-8").splitlines()]
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            alert = json.loads((run_dir / "alert.json").read_text(encoding="utf-8"))

        self.assertTrue(manifest["final"])
        self.assertEqual(manifest["cycle_count"], 1)
        self.assertEqual(len(rows), 6)
        self.assertIn("B03", state["universe"])
        self.assertEqual(state["universe"]["B03"]["universe_origin"], "new_two_venue_listing_after_start")
        self.assertEqual(alert["action"], "postprocess")

    def test_resume_appends_next_cycle_and_emits_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_hash, preflight, preflight_hash = _artifacts(root)
            output = root / "runs"
            stop_first = {"value": False}

            def first_provider(cycle: int) -> dict[str, object]:
                stop_first["value"] = True
                return _report(cycle)

            first = collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=output,
                run_id="run-resume",
                duration_sec=100,
                interval_sec=1,
                segment_sec=2,
                provider=first_provider,
                stop_requested=lambda: stop_first["value"],
            )
            stop_second = {"value": False}

            def second_provider(cycle: int) -> dict[str, object]:
                stop_second["value"] = True
                return _report(cycle, missing_gate_b01=True)

            second = collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=output,
                run_id="run-resume",
                duration_sec=100,
                interval_sec=1,
                segment_sec=2,
                resume=True,
                provider=second_provider,
                stop_requested=lambda: stop_second["value"],
            )
            run_dir = output / "run-resume"
            journal = [json.loads(line) for line in (run_dir / "cycles.jsonl").read_text(encoding="utf-8").splitlines()]
            rows = [json.loads(line) for line in (run_dir / "segments" / "segment_000001.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertFalse(first["final"])
        self.assertFalse(second["final"])
        self.assertEqual(second["cycle_count"], 2)
        self.assertEqual(second["resume_count"], 1)
        self.assertEqual([row["cycle"] for row in journal], [1, 2])
        tombstones = [row for row in rows if row["cycle"] == 2 and row["exchange"] == "gateio" and row["base"] == "B01"]
        self.assertEqual(len(tombstones), 1)
        self.assertTrue(tombstones[0]["tombstone"])
        self.assertEqual(tombstones[0]["status"], "missing")

    def test_resume_survives_a_zero_row_network_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_hash, preflight, preflight_hash = _artifacts(root)
            output = root / "runs"
            first = collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=output,
                run_id="zero-row",
                duration_sec=100,
                interval_sec=1,
                segment_sec=2,
                provider=lambda cycle: {
                    "snapshot_ts": f"2026-01-01T00:0{cycle}:00+00:00",
                    "markets": {"mexc": {}, "gateio": {}},
                    "binance_bases": [],
                    "binance_reference_available": True,
                    "successful_exchanges": [],
                    "errors": {"network": "offline"},
                    "metadata_refreshed": True,
                },
                max_cycles=1,
            )
            second = collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=output,
                run_id="zero-row",
                duration_sec=100,
                interval_sec=1,
                segment_sec=2,
                resume=True,
                provider=lambda cycle: _report(cycle),
                max_cycles=1,
            )
            journal = [json.loads(line) for line in (output / "zero-row" / "cycles.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertFalse(first["final"])
        self.assertEqual(first["rows_total"], 0)
        self.assertEqual(second["cycle_count"], 2)
        self.assertEqual(second["rows_total"], 4)
        self.assertEqual([row["rows"] for row in journal], [0, 4])

    def test_hash_mismatch_and_duplicate_run_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_hash, preflight, preflight_hash = _artifacts(root)
            output = root / "runs"
            with self.assertRaisesRegex(ValueError, "plan sha256 mismatch"):
                collect(
                    plan_path=plan,
                    plan_sha256="0" * 64,
                    preflight_path=preflight,
                    preflight_sha256=preflight_hash,
                    output_root=output,
                    run_id="bad",
                    duration_sec=0,
                    interval_sec=1,
                    segment_sec=2,
                    provider=lambda cycle: _report(cycle),
                )
            collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=output,
                run_id="duplicate",
                duration_sec=0,
                interval_sec=1,
                segment_sec=2,
                provider=lambda cycle: _report(cycle),
            )
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                collect(
                    plan_path=plan,
                    plan_sha256=plan_hash,
                    preflight_path=preflight,
                    preflight_sha256=preflight_hash,
                    output_root=output,
                    run_id="duplicate",
                    duration_sec=0,
                    interval_sec=1,
                    segment_sec=2,
                    provider=lambda cycle: _report(cycle),
                )

    def test_preflight_from_different_plan_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_hash, preflight, _preflight_hash = _artifacts(root)
            payload = json.loads(preflight.read_text(encoding="utf-8"))
            payload["plan_sha256"] = "f" * 64
            preflight.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different plan"):
                collect(
                    plan_path=plan,
                    plan_sha256=plan_hash,
                    preflight_path=preflight,
                    preflight_sha256=_sha(preflight),
                    output_root=root / "runs",
                    run_id="wrong-plan",
                    duration_sec=0,
                    interval_sec=1,
                    segment_sec=2,
                    provider=lambda cycle: _report(cycle),
                )

    def test_provider_refreshes_metadata_on_first_call_after_resume(self) -> None:
        provider = PublicCycleProvider()
        payloads = {
            MEXC_INFO: {"symbols": []},
            MEXC_BOOK: [],
            MEXC_24H: [],
            GATE_PAIRS: [],
            GATE_TICKERS: [],
            BINANCE_INFO: {"symbols": []},
        }
        provider.fetch = lambda url: (payloads[url], 0.01)

        report = provider(38)

        self.assertTrue(report["metadata_refreshed"])
        self.assertTrue(report["binance_reference_available"])
        self.assertEqual(set(report["successful_exchanges"]), {"mexc", "gateio"})

    def test_checkpoint_can_finish_futility_run_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_hash, preflight, preflight_hash = _artifacts(root)
            manifest = collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=root / "runs",
                run_id="futile",
                duration_sec=100,
                interval_sec=1,
                segment_sec=2,
                provider=lambda cycle: _report(cycle),
                checkpoint_callback=lambda _manifest: {
                    "decision": "SPOT_PIT_EVENT_CHECKPOINT_FUTILITY_STOP_RECOMMENDED",
                    "stop": True,
                    "final": True,
                    "stop_reason": "futility_gate",
                },
            )

        self.assertTrue(manifest["final"])
        self.assertEqual(manifest["status"], "COMPLETED")
        self.assertEqual(manifest["stop_reason"], "futility_gate")

    def test_checkpoint_data_quality_stop_remains_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_hash, preflight, preflight_hash = _artifacts(root)
            manifest = collect(
                plan_path=plan,
                plan_sha256=plan_hash,
                preflight_path=preflight,
                preflight_sha256=preflight_hash,
                output_root=root / "runs",
                run_id="quality",
                duration_sec=100,
                interval_sec=1,
                segment_sec=2,
                provider=lambda cycle: _report(cycle),
                checkpoint_callback=lambda _manifest: {
                    "decision": "SPOT_PIT_EVENT_CHECKPOINT_DATA_QUALITY_STOP_RECOMMENDED",
                    "stop": True,
                    "final": False,
                    "stop_reason": "data_quality_gate",
                },
            )

        self.assertFalse(manifest["final"])
        self.assertEqual(manifest["status"], "STOPPED_INCOMPLETE")
        self.assertEqual(manifest["stop_reason"], "data_quality_gate")
if __name__ == "__main__":
    unittest.main()
