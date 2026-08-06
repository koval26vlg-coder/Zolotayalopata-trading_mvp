from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pit_cross_venue_screen import (  # noqa: E402
    PitCrossVenueScreenConfig,
    run_pit_cross_venue_screen,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(
    *,
    cycle: int,
    exchange: str,
    bid: float,
    ask: float,
    base: str = "EDGE",
    eligible: bool = True,
    contract_type: str = "linear_perp",
) -> dict[str, object]:
    return {
        "snapshot_ts": f"2026-07-10T12:{cycle:02d}:00+00:00",
        "exchange": exchange,
        "symbol": f"{base}_USDT",
        "base": base,
        "quote": "USDT",
        "contract_type": contract_type,
        "status": "trading",
        "listed_now": True,
        "inactive_or_delisted": False,
        "volume_24h_quote": 2_000_000.0,
        "bid_price": bid,
        "ask_price": ask,
        "spread_bps": (ask / bid - 1.0) * 10_000.0,
        "binance_spot_listed": not eligible,
        "excluded_by_binance_spot": not eligible,
        "eligible_non_binance_spot": eligible,
        "observed_now": True,
        "tombstone": False,
        "presence_state": "observed",
        "run_id": "run-1",
        "cycle": cycle,
    }


class PitCrossVenueScreenTests(unittest.TestCase):
    def _prior_spot_report(self, root: Path) -> Path:
        path = root / "prior-spot-report.json"
        _write_json(
            path,
            {
                "mode": "cross_venue_dislocation_planonly_research",
                "decision": "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES",
                "summary": {
                    "eligible_events": 0,
                    "max_gross_edge_bps": 66.34,
                    "max_net_edge_bps": -2.66,
                },
                "config": {"total_cost_bps": 69.0},
                "accepted": False,
            },
        )
        return path

    def _fixture(
        self,
        root: Path,
        rows: list[dict[str, object]],
        *,
        retained: list[int],
        dropped: list[int],
    ) -> tuple[Path, Path]:
        source = root / "source"
        source.mkdir()
        snapshots = source / "snapshots.jsonl"
        cycles = source / "cycles.jsonl"
        manifest = source / "manifest.json"
        _write_jsonl(snapshots, rows)
        _write_jsonl(
            cycles,
            [
                {
                    "run_id": "run-1",
                    "cycle": cycle,
                    "output_rows": sum(1 for row in rows if row["cycle"] == cycle),
                    "errors": {} if cycle in retained else {"gateio": "timeout"},
                    "successful_exchanges": ["gateio", "mexc"] if cycle in retained else ["mexc"],
                }
                for cycle in sorted(retained + dropped)
            ],
        )
        _write_json(
            manifest,
            {
                "schema": "pit_universe_snapshot_manifest_v2",
                "mode": "pit_universe_snapshot_collect",
                "run_id": "run-1",
                "final": True,
                "cycle_count": len(retained) + len(dropped),
                "rows_total": len(rows),
            },
        )
        mask_payload = {
            "schema": "pit_two_venue_clean_slice_mask_v1",
            "rule_revision": "whole_cycle_two_venue_availability_v1",
            "source_run_id": "run-1",
            "cycles_sha256": _sha256(cycles),
            "required_exchanges": ["gateio", "mexc"],
            "retained_cycles": retained,
            "dropped_cycles": dropped,
        }
        mask_sha256 = hashlib.sha256(
            json.dumps(mask_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        spec = root / "spec.json"
        _write_json(
            spec,
            {
                "schema": "pit_two_venue_clean_slice_spec_v1",
                "mode": "pit_two_venue_clean_slice_spec_planonly",
                "decision": "PIT_TWO_VENUE_CLEAN_SLICE_SPEC_PLANONLY_READY",
                "would_materialize": False,
                "strategy_accepted": False,
                "replay_allowed": False,
                "source_run": {
                    "run_id": "run-1",
                    "manifest_final": True,
                    "full_dataset_verdict": "rejected_not_modified",
                    "cycle_count": len(retained) + len(dropped),
                    "rows_total": len(rows),
                },
                "source_artifacts": {
                    "manifest": {"path": str(manifest), "sha256": _sha256(manifest)},
                    "cycles": {"path": str(cycles), "sha256": _sha256(cycles)},
                    "snapshots": {"path": str(snapshots), "sha256": _sha256(snapshots)},
                },
                "selection_rule": {
                    "revision": "whole_cycle_two_venue_availability_v1",
                    "required_exchanges": ["gateio", "mexc"],
                    "whole_cycle_only": True,
                    "forward_fill_allowed": False,
                    "imputation_allowed": False,
                    "symbol_level_filtering_allowed": False,
                },
                "mask": {
                    "retained_cycles": retained,
                    "dropped_cycles": dropped,
                    "retained_rows": sum(1 for row in rows if row["cycle"] in retained),
                    "dropped_rows": sum(1 for row in rows if row["cycle"] in dropped),
                },
                "mask_sha256": mask_sha256,
                "mask_hash_payload": mask_payload,
            },
        )
        return spec, snapshots

    def test_streams_only_retained_cycles_and_labels_perp_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                _row(cycle=1, exchange="mexc", bid=99.0, ask=100.0),
                _row(cycle=1, exchange="gateio", bid=102.0, ask=103.0),
                _row(cycle=2, exchange="mexc", bid=50.0, ask=51.0),
                _row(cycle=2, exchange="gateio", bid=80.0, ask=81.0),
            ]
            spec, _ = self._fixture(root, rows, retained=[1], dropped=[2])
            output = root / "report.json"

            report = run_pit_cross_venue_screen(
                spec,
                output,
                PitCrossVenueScreenConfig(
                    round_trip_fee_bps=50.0,
                    slippage_bps=25.0,
                    operational_buffer_bps=25.0,
                    prior_spot_report_path=str(self._prior_spot_report(root)),
                ),
            )

            self.assertEqual(report["decision"], "PIT_LINEAR_PERP_SCREEN_CANDIDATES_REQUIRE_DEEPER_EVIDENCE")
            self.assertEqual(report["summary"]["source_rows"], 4)
            self.assertEqual(report["summary"]["retained_rows"], 2)
            self.assertEqual(report["summary"]["dropped_rows"], 2)
            self.assertEqual(report["summary"]["retained_cycles_seen"], 1)
            self.assertEqual(report["summary"]["cost_positive_events"], 1)
            self.assertEqual(report["instrument_scope"]["observed_contract_types"], ["linear_perp"])
            self.assertFalse(report["instrument_scope"]["supports_spot_objective"])
            self.assertEqual(report["spot_objective_verdict"], "REJECTED_INSTRUMENT_MISMATCH_AND_PRIOR_NEGATIVE_SPOT_SCAN")
            self.assertFalse(report["strategy_accepted"])
            self.assertFalse(report["replay_allowed"])
            self.assertFalse(report["oos_ready"])
            self.assertTrue(output.exists())
            self.assertFalse((root / "clean.jsonl").exists())

    def test_rejects_source_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                _row(cycle=1, exchange="mexc", bid=99.0, ask=100.0),
                _row(cycle=1, exchange="gateio", bid=101.0, ask=102.0),
            ]
            spec, snapshots = self._fixture(root, rows, retained=[1], dropped=[])
            with snapshots.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_row(cycle=1, exchange="mexc", bid=98.0, ask=99.0)) + "\n")

            with self.assertRaisesRegex(ValueError, "snapshots SHA-256 mismatch"):
                run_pit_cross_venue_screen(spec, root / "report.json")

    def test_rejects_no_edge_after_fixed_costs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                _row(cycle=1, exchange="mexc", bid=99.9, ask=100.0),
                _row(cycle=1, exchange="gateio", bid=100.1, ask=100.2),
            ]
            spec, _ = self._fixture(root, rows, retained=[1], dropped=[])

            report = run_pit_cross_venue_screen(
                spec,
                root / "report.json",
                PitCrossVenueScreenConfig(
                    round_trip_fee_bps=39.0,
                    slippage_bps=10.0,
                    operational_buffer_bps=20.0,
                ),
            )

            self.assertEqual(report["decision"], "PIT_LINEAR_PERP_SCREEN_REJECTED_NO_EDGE_AFTER_BASE_COSTS")
            self.assertEqual(report["summary"]["cost_positive_events"], 0)
            self.assertGreater(report["summary"]["max_gross_edge_bps"], 0)
            self.assertLess(report["summary"]["max_net_screening_edge_bps"], 0)
            self.assertFalse(report["accepted"])

    def test_spot_rows_cannot_be_misrepresented_as_perp_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                _row(cycle=1, exchange="mexc", bid=99.0, ask=100.0, contract_type="spot"),
                _row(cycle=1, exchange="gateio", bid=102.0, ask=103.0, contract_type="spot"),
            ]
            spec, _ = self._fixture(root, rows, retained=[1], dropped=[])

            report = run_pit_cross_venue_screen(spec, root / "report.json")

            self.assertEqual(report["decision"], "PIT_LINEAR_PERP_SCREEN_REJECTED_NO_MATCHED_PAIRS")
            self.assertEqual(report["summary"]["instrument_mismatch_rows"], 2)
            self.assertEqual(report["summary"]["evaluations"], 0)


if __name__ == "__main__":
    unittest.main()
