from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import continuous_production  # noqa: E402
import dense_ws_next_window_reservation as reservation  # noqa: E402


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DenseWsNextWindowReservationTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> dict[str, Path | str]:
        schedule_path = root / "pit-extension.json"
        segments = []
        for index, day in enumerate(range(12, 17), start=1):
            segments.append(
                {
                    "run_id": f"pit_universe_v2_forward_202608{day:02d}_n{index:02d}",
                    "start_local": f"2026-08-{day:02d}T01:00:00+03:00",
                    "end_local": f"2026-08-{day:02d}T01:20:00+03:00",
                    "hard_deadline_local": f"2026-08-{day:02d}T07:00:00+03:00",
                }
            )
        _write(
            schedule_path,
            {
                "mode": "PlanOnly",
                "plan_hash": "a" * 64,
                "schedule_approved": False,
                "segments": segments,
            },
        )

        continuous_policy_path = root / "continuous-policy.json"
        continuous_policy = {
            "schema": continuous_production.POLICY_SCHEMA,
            "run_windows": {
                "timezone": "Europe/Volgograd",
                "utc_offset_minutes": 180,
                "new_campaign_start_local": "19:00",
                "weekday_hard_stop_local": "08:00",
                "weekend": {
                    "opens": "FRIDAY 19:00",
                    "hard_stop": "MONDAY 08:00",
                },
            },
            "approval": {"request_lead_minutes": 30},
            "runtime": {
                "short_offline_task_max_runtime_sec": 1800,
                "shutdown_grace_sec": 1800,
            },
            "accelerated_evidence_factory": {
                "hard_campaign_output_cap_bytes": 25_000_000_000,
            },
        }
        _write(continuous_policy_path, continuous_policy)

        autopilot_policy_path = root / "autopilot-policy.json"
        _write(
            autopilot_policy_path,
            {
                "pit_schedule_extension_candidate": {
                    "status": "PLANONLY_NOT_APPROVED",
                    "plan_path": str(schedule_path.resolve()),
                    "plan_hash": "a" * 64,
                    "approval_request_not_before_local": "2026-08-10T19:00:00+03:00",
                    "requires_fresh_horizon_audit_before_approval": True,
                }
            },
        )
        return {
            "continuous_policy": continuous_policy_path,
            "continuous_policy_sha": _sha(continuous_policy_path),
            "autopilot_policy": autopilot_policy_path,
            "autopilot_policy_sha": _sha(autopilot_policy_path),
            "schedule": schedule_path,
            "schedule_sha": _sha(schedule_path),
        }

    def _build(self, root: Path, fixture: dict[str, Path | str]) -> dict:
        with mock.patch.object(
            reservation.pit_schedule,
            "validate_night_schedule_plan",
            return_value=None,
        ):
            return reservation.build_reservation(
                continuous_policy_path=fixture["continuous_policy"],
                expected_continuous_policy_sha256=str(fixture["continuous_policy_sha"]),
                autopilot_policy_path=fixture["autopilot_policy"],
                expected_autopilot_policy_sha256=str(fixture["autopilot_policy_sha"]),
                pit_schedule_path=fixture["schedule"],
                expected_pit_schedule_sha256=str(fixture["schedule_sha"]),
                expected_pit_plan_hash="a" * 64,
                not_before_local="2026-08-09T20:00:00+03:00",
                output_path=root / "reservation.json",
                generated_at_utc="2026-08-09T17:00:00+00:00",
            )

    def test_selects_first_full_weekend_window_and_preserves_both_pit_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            payload = self._build(root, fixture)

            window = payload["reservation"]
            self.assertEqual(window["start_local"], "2026-08-15T01:40:00+03:00")
            self.assertEqual(window["writer_deadline_local"], "2026-08-16T01:40:00+03:00")
            self.assertEqual(window["hard_deadline_local"], "2026-08-16T02:10:00+03:00")
            self.assertEqual(
                window["preceding_pit"]["run_id"],
                "pit_universe_v2_forward_20260815_n04",
            )
            self.assertEqual(
                window["deferred_pit"]["run_id"],
                "pit_universe_v2_forward_20260816_n05",
            )
            self.assertEqual(window["deferred_pit"]["new_start_local"], "2026-08-16T02:15:00+03:00")
            self.assertEqual(payload["status"], "CONTINGENT_ON_FRESH_PIT_EXTENSION_APPROVAL")
            self.assertFalse(payload["authorization_boundary"]["collector_launch_allowed"])

    def test_rejects_a_stale_policy_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            with self.assertRaisesRegex(ValueError, "policy file SHA-256 mismatch"):
                with mock.patch.object(
                    reservation.pit_schedule,
                    "validate_night_schedule_plan",
                    return_value=None,
                ):
                    reservation.build_reservation(
                        continuous_policy_path=fixture["continuous_policy"],
                        expected_continuous_policy_sha256="0" * 64,
                        autopilot_policy_path=fixture["autopilot_policy"],
                        expected_autopilot_policy_sha256=str(fixture["autopilot_policy_sha"]),
                        pit_schedule_path=fixture["schedule"],
                        expected_pit_schedule_sha256=str(fixture["schedule_sha"]),
                        expected_pit_plan_hash="a" * 64,
                        not_before_local="2026-08-09T20:00:00+03:00",
                        output_path=root / "reservation.json",
                        generated_at_utc="2026-08-09T17:00:00+00:00",
                    )

    def test_fails_when_horizon_has_no_full_weekend_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            schedule_path = Path(fixture["schedule"])
            schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            schedule["segments"] = schedule["segments"][:3]
            _write(schedule_path, schedule)
            fixture["schedule_sha"] = _sha(schedule_path)

            with self.assertRaisesRegex(ValueError, "no feasible 24-hour no-skip"):
                self._build(root, fixture)

    def test_refuses_to_overwrite_an_immutable_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            self._build(root, fixture)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite immutable"):
                self._build(root, fixture)


if __name__ == "__main__":
    unittest.main()
