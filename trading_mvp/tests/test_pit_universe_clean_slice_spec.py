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

from pit_universe_clean_slice_spec import build_clean_slice_spec  # noqa: E402


class PitUniverseCleanSliceSpecTests(unittest.TestCase):
    def _fixture(self, root: Path, *, final: bool = True, cycle_ids: tuple[int, ...] = (1, 2, 3)) -> Path:
        snapshots = root / "snapshots.jsonl"
        cycles = root / "cycles.jsonl"
        snapshots.write_bytes(b"immutable snapshot source\n")
        cycle_rows = {
            1: {
                "run_id": "pit_fixture",
                "cycle": 1,
                "cycle_started_at_utc": "2026-07-10T00:00:00+00:00",
                "cycle_finished_at_utc": "2026-07-10T00:00:10+00:00",
                "output_rows": 4,
                "errors": {},
                "successful_exchanges": ["gateio", "mexc"],
            },
            2: {
                "run_id": "pit_fixture",
                "cycle": 2,
                "cycle_started_at_utc": "2026-07-10T00:05:00+00:00",
                "cycle_finished_at_utc": "2026-07-10T00:05:10+00:00",
                "output_rows": 2,
                "errors": {"gateio": "timeout"},
                "successful_exchanges": ["mexc"],
            },
            3: {
                "run_id": "pit_fixture",
                "cycle": 3,
                "cycle_started_at_utc": "2026-07-10T00:10:00+00:00",
                "cycle_finished_at_utc": "2026-07-10T00:10:10+00:00",
                "output_rows": 3,
                "errors": {},
                "successful_exchanges": ["gateio", "mexc"],
            },
        }
        selected = [cycle_rows[value] for value in cycle_ids]
        cycles.write_text("\n".join(json.dumps(row) for row in selected) + "\n", encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": "pit_universe_snapshot_manifest_v2",
                    "mode": "pit_universe_snapshot_collect",
                    "run_id": "pit_fixture",
                    "final": final,
                    "cycle_count": len(selected),
                    "rows_total": sum(int(row["output_rows"]) for row in selected),
                    "snapshots_path": str(snapshots),
                    "cycles_path": str(cycles),
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_builds_deterministic_whole_cycle_planonly_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            manifest = self._fixture(source)
            snapshots = source / "snapshots.jsonl"
            source_before = snapshots.read_bytes()
            output_a = root / "analysis" / "spec-a.json"
            output_b = root / "analysis" / "spec-b.json"

            first = build_clean_slice_spec(manifest, output_a)
            second = build_clean_slice_spec(manifest, output_b)

            self.assertEqual(snapshots.read_bytes(), source_before)
            self.assertEqual(first["decision"], "PIT_TWO_VENUE_CLEAN_SLICE_SPEC_PLANONLY_READY")
            self.assertFalse(first["strategy_accepted"])
            self.assertFalse(first["replay_allowed"])
            self.assertFalse(first["would_materialize"])
            self.assertEqual(first["mask"]["retained_cycles"], [1, 3])
            self.assertEqual(first["mask"]["dropped_cycles"], [2])
            self.assertEqual(first["mask"]["retained_rows"], 7)
            self.assertEqual(first["mask"]["dropped_rows"], 2)
            self.assertEqual(first["mask"]["dropped_details"][0]["missing_exchanges"], ["gateio"])
            self.assertEqual(first["mask_sha256"], second["mask_sha256"])
            self.assertEqual(
                first["source_artifacts"]["snapshots"]["sha256"],
                hashlib.sha256(source_before).hexdigest(),
            )
            self.assertTrue(output_a.exists())
            self.assertFalse((source / "filtered.jsonl").exists())

    def test_rejects_output_inside_source_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            manifest = self._fixture(source)

            with self.assertRaisesRegex(ValueError, "outside the source run directory"):
                build_clean_slice_spec(manifest, source / "spec.json")

    def test_rejects_non_final_or_non_contiguous_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = root / "not-final"
            source_a.mkdir()
            not_final = self._fixture(source_a, final=False)
            with self.assertRaisesRegex(ValueError, "manifest.final=true"):
                build_clean_slice_spec(not_final, root / "not-final-spec.json")

            source_b = root / "gap"
            source_b.mkdir()
            gap = self._fixture(source_b, cycle_ids=(1, 3))
            with self.assertRaisesRegex(ValueError, "contiguous"):
                build_clean_slice_spec(gap, root / "gap-spec.json")


if __name__ == "__main__":
    unittest.main()
