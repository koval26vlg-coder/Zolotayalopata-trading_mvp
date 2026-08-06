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

from spot_pit_event_readiness import READY_DECISION, build_packet  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SpotPitEventReadinessTests(unittest.TestCase):
    def _files(self, root: Path) -> dict[str, Path]:
        output_root = root / "output"
        output_root.mkdir()
        plan = root / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "schema": "spot_pit_event_forward_plan_v1",
                    "research_only": True,
                    "strategy_accepted": False,
                    "collection": {
                        "duration_days": 14,
                        "interval_sec": 60,
                        "segment_sec": 21600,
                        "output_root": str(output_root),
                        "minimum_free_disk_gib_before_start": 0,
                        "visible_terminal_required": True,
                        "no_hidden_background_run": True,
                        "durable_segments": True,
                        "resume_same_run_id": True,
                        "atomic_manifest": True,
                        "status_every_cycles": 5,
                    },
                    "early_gates": {"coverage_gate_after_hours": 2, "futility_gate_after_hours": 48},
                    "economics": {"normal_total_cost_bps": 120, "stress_total_cost_bps": 245},
                }
            ),
            encoding="utf-8",
        )
        preflight = root / "preflight.json"
        preflight.write_text(
            json.dumps(
                {
                    "schema": "spot_pit_event_public_preflight_v1",
                    "accepted": True,
                    "plan_sha256": _sha(plan),
                    "checks": {"public": True, "coverage": True},
                }
            ),
            encoding="utf-8",
        )
        tests = root / "tests.json"
        tests.write_text(json.dumps({"passed": True, "tests_run": 12}), encoding="utf-8")
        paths = {"plan": plan, "preflight": preflight, "tests": tests, "output": output_root}
        for name in ("collector", "analyzer", "wrapper"):
            path = root / f"{name}.txt"
            path.write_text(name, encoding="utf-8")
            paths[name] = path
        return paths

    def test_builds_sealed_ready_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._files(root)
            packet = build_packet(
                plan_path=paths["plan"],
                preflight_path=paths["preflight"],
                collector_path=paths["collector"],
                analyzer_path=paths["analyzer"],
                wrapper_path=paths["wrapper"],
                test_evidence_path=paths["tests"],
                packet_path=root / "packet.json",
            )

        self.assertTrue(packet["all_checks_passed"])
        self.assertEqual(packet["decision"], READY_DECISION)
        self.assertFalse(packet["actual_collect_allowed_now"])
        self.assertTrue(packet["requires_explicit_user_confirmation"])
        self.assertEqual(packet["collection"]["duration_sec"], 14 * 86400)

    def test_rejects_preflight_from_another_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._files(root)
            preflight = json.loads(paths["preflight"].read_text(encoding="utf-8"))
            preflight["plan_sha256"] = "0" * 64
            paths["preflight"].write_text(json.dumps(preflight), encoding="utf-8")
            packet = build_packet(
                plan_path=paths["plan"],
                preflight_path=paths["preflight"],
                collector_path=paths["collector"],
                analyzer_path=paths["analyzer"],
                wrapper_path=paths["wrapper"],
                test_evidence_path=paths["tests"],
                packet_path=root / "packet.json",
            )

        self.assertFalse(packet["all_checks_passed"])
        self.assertFalse(packet["checks"]["preflight_matches_plan"])
        self.assertIn("REJECTED", packet["decision"])


if __name__ == "__main__":
    unittest.main()
