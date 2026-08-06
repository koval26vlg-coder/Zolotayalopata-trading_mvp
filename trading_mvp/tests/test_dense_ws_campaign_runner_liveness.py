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

import dense_ws_campaign_runner as runner  # noqa: E402


class DenseWsCampaignRunnerLivenessTests(unittest.TestCase):
    def test_phase_ready_requires_market_liveness_not_transport_only(self) -> None:
        healthy = {
            "runtime_completed": True,
            "liveness_clean": True,
            "quality_eligible": True,
            "dirty_segment_ids": [],
            "completed": True,
            "final": True,
            "coverage_ratio": 1.0,
            "transport_rows": 700,
            "market_envelope_rows": 600,
        }
        transport_only = dict(healthy, market_envelope_rows=0)
        dirty = dict(
            healthy,
            liveness_clean=False,
            quality_eligible=False,
            dirty_segment_ids=["seg_001"],
            completed=False,
            final=False,
        )
        common = {
            "writer_exit_code": 0,
            "errors": [],
            "schema_checked": True,
            "zero_checked": True,
            "density_checked": True,
        }

        self.assertTrue(runner.phase_manifest_ready(healthy, **common))
        self.assertFalse(runner.phase_manifest_ready(transport_only, **common))
        self.assertFalse(runner.phase_manifest_ready(dirty, **common))

    def test_existing_symbol_plan_hash_is_captured_by_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "campaign"
            plan_path = Path(tmp) / "plan.json"
            policy_path = Path(tmp) / "policy.json"
            plan = {
                "campaign_id": "dense_ws_fixture",
                "outputs": {"campaign_root": str(root)},
            }
            contract = {
                "contract_hash": "b" * 64,
                "source_candidate": {"candidate_contract_hash": "a" * 64},
                "universe_contract": {"source": {"sha256": "c" * 64}},
            }
            runtime = runner.CampaignRuntime(
                contract=contract,
                plan=plan,
                plan_path=plan_path,
                expected_plan_hash="d" * 64,
                policy_path=policy_path,
                reservation_token="token",
            )
            mexc = [f"S{index}USDT" for index in range(10)]
            gate = [f"S{index}_USDT" for index in range(10)]
            payload = {
                "campaign_id": "dense_ws_fixture",
                "plan_hash": "d" * 64,
                "contract_hash": "b" * 64,
                "universe_sha256": "c" * 64,
                "symbols_by_exchange": {"mexc": mexc, "gateio": gate},
                "symbols_arg": (
                    f"gateio:{','.join(gate)};mexc:{','.join(mexc)}"
                ),
            }
            symbol_plan = runtime.paths["symbol_plan"]
            symbol_plan.parent.mkdir(parents=True, exist_ok=True)
            symbol_plan.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            expected_sha = hashlib.sha256(symbol_plan.read_bytes()).hexdigest()

            observed = runtime.discover_symbols()

        self.assertEqual(observed, payload)
        self.assertEqual(runtime.symbol_plan_sha256, expected_sha)


if __name__ == "__main__":
    unittest.main()
