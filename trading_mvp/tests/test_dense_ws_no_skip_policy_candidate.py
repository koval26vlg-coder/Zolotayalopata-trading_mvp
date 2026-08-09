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
import dense_ws_next_window_reservation as window_reservation  # noqa: E402
import dense_ws_no_skip_policy_candidate as policy_candidate  # noqa: E402


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DenseWsNoSkipPolicyCandidateTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> dict[str, Path | str]:
        source = root / "continuous-policy.json"
        _write(
            source,
            {
                "schema": continuous_production.POLICY_SCHEMA,
                "policy_id": "old",
                "effective_at": "2026-08-03T19:00:00+03:00",
                "approved_by": "old",
                "purpose": "preserve",
                "runtime": {
                    "shutdown_grace_sec": 1800,
                },
                "accelerated_evidence_factory": {
                    "factory_id": "old",
                    "status": "old",
                    "market_data_sequence": [],
                    "continuous_evidence_exception": {},
                    "dense_writer_target_sec": 86400,
                    "dense_campaign_max_elapsed_sec": 88200,
                    "dense_campaign_hard_deadline_local": "old",
                    "hard_campaign_output_cap_bytes": 25_000_000_000,
                    "post_collection_pipeline": ["preserve"],
                },
                "invariants": {"single_market_data_writer": True},
                "pit_n08_time_only_amendment": {"run_id": "stale-n08"},
            },
        )

        reservation_path = root / "reservation.json"
        reservation = {
            "schema": window_reservation.SCHEMA,
            "mode": "PlanOnly",
            "status": "CONTINGENT_ON_FRESH_PIT_EXTENSION_APPROVAL",
            "reservation": {
                "campaign_id": "dense_ws_microstructure_regime_filter_v1_20260815_aef_24h",
                "window_id": "WEEKEND_2026-08-14_2026-08-17",
                "start_local": "2026-08-15T01:40:00+03:00",
                "writer_deadline_local": "2026-08-16T01:40:00+03:00",
                "hard_deadline_local": "2026-08-16T02:10:00+03:00",
                "writer_duration_sec": 86400,
                "max_runtime_sec": 88200,
                "hard_output_cap_bytes": 25_000_000_000,
                "suppressed_pit_run_ids": [],
                "preceding_pit": {
                    "run_id": "pit_universe_v2_forward_20260815_n04",
                    "end_local": "2026-08-15T01:20:00+03:00",
                },
                "deferred_pit": {
                    "run_id": "pit_universe_v2_forward_20260816_n05",
                    "original_start_local": "2026-08-16T01:00:00+03:00",
                    "original_end_local": "2026-08-16T01:20:00+03:00",
                    "new_start_local": "2026-08-16T02:15:00+03:00",
                    "new_end_local": "2026-08-16T02:35:00+03:00",
                    "hard_deadline_local": "2026-08-16T07:00:00+03:00",
                },
            },
            "authorization_boundary": {"collector_launch_allowed": False},
            "reservation_hash_method": "sha256_canonical_json_excluding_reservation_hash",
        }
        reservation["reservation_hash"] = policy_candidate._canonical_hash(reservation)
        _write(reservation_path, reservation)

        amendment_path = root / "amendment.json"
        _write(
            amendment_path,
            {
                "mode": "PlanOnly",
                "plan_hash": "b" * 64,
                "time_only_amendment": {
                    "run_id": "pit_universe_v2_forward_20260816_n05",
                    "original_start_local": "2026-08-16T01:00:00+03:00",
                    "original_end_local": "2026-08-16T01:20:00+03:00",
                    "new_start_local": "2026-08-16T02:15:00+03:00",
                    "new_end_local": "2026-08-16T02:35:00+03:00",
                    "hard_deadline_local": "2026-08-16T07:00:00+03:00",
                    "trade_contract_changed": False,
                },
            },
        )
        return {
            "source": source,
            "source_sha": _sha(source),
            "reservation": reservation_path,
            "reservation_sha": _sha(reservation_path),
            "amendment": amendment_path,
            "amendment_sha": _sha(amendment_path),
        }

    def _build(self, root: Path, fixture: dict[str, Path | str]) -> dict:
        with mock.patch.object(
            policy_candidate.pit_schedule,
            "validate_night_schedule_plan",
            return_value=None,
        ):
            return policy_candidate.build_candidate_policy(
                source_policy_path=fixture["source"],
                expected_source_policy_sha256=str(fixture["source_sha"]),
                reservation_path=fixture["reservation"],
                expected_reservation_file_sha256=str(fixture["reservation_sha"]),
                amended_pit_schedule_path=fixture["amendment"],
                expected_amended_pit_schedule_sha256=str(fixture["amendment_sha"]),
                expected_amended_pit_plan_hash="b" * 64,
                output_path=root / "candidate.json",
                generated_at_local="2026-08-09T20:45:00+03:00",
            )

    def test_builds_time_only_candidate_and_preserves_source_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            result = self._build(root, fixture)
            candidate = json.loads((root / "candidate.json").read_text(encoding="utf-8"))

            self.assertEqual(result["verdict"], "TIME_ONLY_NO_SKIP_POLICY_CANDIDATE_VALID")
            self.assertTrue(result["contingent_on_fresh_pit_extension_approval"])
            self.assertFalse(result["collector_launch_allowed"])
            self.assertEqual(candidate["purpose"], "preserve")
            self.assertEqual(candidate["invariants"], {"single_market_data_writer": True})
            self.assertNotIn("pit_n08_time_only_amendment", candidate)
            exception = candidate["accelerated_evidence_factory"]["continuous_evidence_exception"]
            self.assertEqual(exception["suppressed_pit_run_ids"], [])
            self.assertEqual(exception["deferred_pit_start_local"], "2026-08-16T02:15:00+03:00")

    def test_rejects_amendment_with_a_different_deferred_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            amendment_path = Path(fixture["amendment"])
            amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
            amendment["time_only_amendment"]["run_id"] = "wrong"
            _write(amendment_path, amendment)
            fixture["amendment_sha"] = _sha(amendment_path)

            with self.assertRaisesRegex(ValueError, "run_id differs from reservation"):
                self._build(root, fixture)

    def test_rejects_reservation_that_authorizes_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            reservation_path = Path(fixture["reservation"])
            value = json.loads(reservation_path.read_text(encoding="utf-8"))
            value["authorization_boundary"]["collector_launch_allowed"] = True
            value.pop("reservation_hash")
            value["reservation_hash"] = policy_candidate._canonical_hash(value)
            _write(reservation_path, value)
            fixture["reservation_sha"] = _sha(reservation_path)

            with self.assertRaisesRegex(ValueError, "must not authorize a collector"):
                self._build(root, fixture)


if __name__ == "__main__":
    unittest.main()
