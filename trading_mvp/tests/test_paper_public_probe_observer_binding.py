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

import paper_observer_runtime as runtime  # noqa: E402


RESEARCH_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
)
PLAN_V3 = RESEARCH_ROOT / "paper-public-readonly-probe-plan-v3.json"
EVIDENCE_V3 = RESEARCH_ROOT / "paper-public-readonly-probe-evidence-v3.json"
PLAN_HASH = "c48c251ada02ee79f3d94633c70cbe23056e4989662e8f144d7d4fb0a87709d5"


class PublicProbeObserverBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        if not PLAN_V3.is_file() or not EVIDENCE_V3.is_file():
            self.skipTest("immutable public probe v3 evidence is unavailable")

    def test_real_v3_evidence_builds_fail_closed_observer_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "binding.json"
            report = (
                runtime.build_public_probe_evidence_observer_binding_fixture_report(
                    plan_path=PLAN_V3,
                    evidence_path=EVIDENCE_V3,
                    expected_plan_hash=PLAN_HASH,
                    output_path=output,
                    generated_at_utc="2026-07-30T16:00:00+00:00",
                )
            )
            persisted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report, persisted)
        self.assertEqual(
            report["verdict"],
            "PUBLIC_PROBE_EVIDENCE_BOUND_TO_FAIL_CLOSED_OBSERVER_INPUT",
        )
        self.assertEqual(report["network_requests_performed_by_task"], 0)
        self.assertEqual(report["oms_mutations"], 0)
        self.assertFalse(report["oms_transition_allowed"])
        self.assertFalse(report["observer_input"]["paper_forward_allowed"])
        self.assertFalse(report["observer_input"]["live_allowed"])

    def test_binding_rejects_quote_freshness_scope_drift(self) -> None:
        plan = json.loads(PLAN_V3.read_text(encoding="utf-8"))
        evidence = json.loads(EVIDENCE_V3.read_text(encoding="utf-8"))
        tampered = deepcopy(evidence)
        tampered["quality"]["maximum_quote_age_ms_by_venue"]["mexc"] = 7000
        with self.assertRaisesRegex(ValueError, "evidence is not accepted"):
            runtime._build_public_probe_observer_input(
                plan=plan,
                evidence=tampered,
            )

    def test_binding_rejects_private_scope_drift(self) -> None:
        plan = json.loads(PLAN_V3.read_text(encoding="utf-8"))
        evidence = json.loads(EVIDENCE_V3.read_text(encoding="utf-8"))
        tampered = deepcopy(evidence)
        tampered["safety"]["private_api_keys"] = True
        with self.assertRaisesRegex(ValueError, "evidence is not accepted"):
            runtime._build_public_probe_observer_input(
                plan=plan,
                evidence=tampered,
            )


if __name__ == "__main__":
    unittest.main()
