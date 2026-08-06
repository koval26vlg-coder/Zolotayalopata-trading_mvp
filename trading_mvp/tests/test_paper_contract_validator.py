from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_contract_validator import (  # noqa: E402
    build_validation_report,
    contract_hash,
    validate_health_contract,
    validate_private_boundary_contract,
    validate_runtime_contract,
)


ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
)
RUNTIME = ROOT / "paper-observer-runtime-contract-v1.json"
HEALTH = ROOT / "paper-venue-health-gate-contract-v1.json"
PRIVATE = ROOT / "private-boundary-attestation-contract-v1.json"


def _tampered_copy(source: Path, target: Path, mutate) -> Path:
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    mutate(payload)
    payload["contract_hash_sha256"] = contract_hash(payload)
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


class PaperContractValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        if not all(path.is_file() for path in (RUNTIME, HEALTH, PRIVATE)):
            self.skipTest("paper contracts are unavailable")

    def test_current_contract_chain_validates(self) -> None:
        runtime = validate_runtime_contract(RUNTIME)
        health = validate_health_contract(HEALTH, runtime_contract=runtime)
        private = validate_private_boundary_contract(PRIVATE)

        self.assertEqual(
            runtime["schema"],
            "trading_mvp_paper_observer_runtime_contract_v1",
        )
        self.assertEqual(
            health["schema"],
            "trading_mvp_paper_venue_health_gate_contract_v1",
        )
        self.assertEqual(private["current_live_authority"], "NONE")

    def test_rehashed_runtime_cannot_raise_runtime_or_enable_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "runtime.json"

            def mutate(payload: dict) -> None:
                payload["runtime"]["max_runtime_sec"] = 1_801
                payload["safety"]["public_get_requests_only"] = False

            _tampered_copy(RUNTIME, target, mutate)
            with self.assertRaisesRegex(ValueError, "max_runtime_sec"):
                validate_runtime_contract(target)

    def test_rehashed_health_cannot_weaken_capacity_or_impact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "health.json"

            def mutate(payload: dict) -> None:
                payload["thresholds"]["minimum_capacity_quote_per_leg"] = 1.0
                payload["thresholds"]["maximum_impact_bps_at_notional"] = 100.0

            _tampered_copy(HEALTH, target, mutate)
            with self.assertRaisesRegex(ValueError, "capacity"):
                validate_health_contract(target)

    def test_rehashed_private_contract_cannot_enable_withdrawal_or_auto_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "private.json"

            def mutate(payload: dict) -> None:
                payload["permission_gates"]["withdrawal_permission"] = True
                payload["live_activation_decision"]["automatic_live_activation"] = True

            _tampered_copy(PRIVATE, target, mutate)
            with self.assertRaisesRegex(ValueError, "withdrawal"):
                validate_private_boundary_contract(target)

    def test_report_is_deterministic_for_same_contract_files(self) -> None:
        first = build_validation_report(
            runtime_contract_path=RUNTIME,
            health_contract_path=HEALTH,
            private_contract_path=PRIVATE,
            output_path=None,
        )
        second = build_validation_report(
            runtime_contract_path=RUNTIME,
            health_contract_path=HEALTH,
            private_contract_path=PRIVATE,
            output_path=None,
        )
        self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
        self.assertEqual(first["verdict"], "CONTRACT_CHAIN_VALID")
        self.assertFalse(first["safety"]["live_orders"])


if __name__ == "__main__":
    unittest.main()
