from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import paper_observer_runtime as runtime  # noqa: E402
import paper_public_reader as public_reader  # noqa: E402
from historical_basis_v2_paper_oms import (  # noqa: E402
    build_historical_basis_v2_paper_plan,
)
from test_historical_basis_v2_paper_oms import (  # noqa: E402
    _observation,
    _write_probe_report,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_CONTRACT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
    r"\paper-observer-runtime-contract-v1.json"
)
HEALTH_CONTRACT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
    r"\paper-venue-health-gate-contract-v1.json"
)
PUBLIC_READER_FIXTURE = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
    r"\paper-public-reader-fixture-v1.json"
)
PUBLIC_BRIDGE_FIXTURE = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
    r"\paper-public-snapshot-observer-bridge-v1.json"
)


def _venue(ts_ms: int, *, stale_ms: int = 0, capacity: float = 2_000.0) -> dict:
    return {
        "transport_ok": True,
        "http_status": 200,
        "schema_ok": True,
        "contract_trading": True,
        "maintenance_flag": False,
        "observed_ts_ms": ts_ms - stale_ms,
        "best_bid": 99.99,
        "best_ask": 100.01,
        "spread_bps": 2.0,
        "bid_depth_levels": 2,
        "ask_depth_levels": 2,
        "buy_capacity_quote_at_10bps": capacity,
        "sell_capacity_quote_at_10bps": capacity,
        "buy_impact_bps_at_notional": 2.0,
        "sell_impact_bps_at_notional": 2.0,
        "raw_payload_hash_sha256": "a" * 64,
        "bids": [[99.99, 20.0]],
        "asks": [[100.01, 20.0]],
    }


def _sample(sequence: int, *, stale_gate: bool = False) -> dict:
    ts = 1_800_000_000 + sequence
    received_ms = ts * 1_000
    return {
        "sample_sequence": sequence,
        "observer_received_ts_ms": received_ms,
        "canonical_base": "A00",
        "recent_application_error_rate": 0.0,
        "consecutive_missing_intervals": 0,
        "mexc": _venue(received_ms),
        "gateio": _venue(received_ms, stale_ms=6_000 if stale_gate else 0),
        "observation": _observation(ts),
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _ready_chain(root: Path) -> tuple[Path, Path]:
    _report, report_path = _write_probe_report(root)
    paper_plan_path = root / "paper-plan.json"
    build_historical_basis_v2_paper_plan(report_path, paper_plan_path)
    return paper_plan_path, report_path


def _plan(root: Path, rows: list[dict]) -> tuple[Path, dict]:
    paper_plan_path, report_path = _ready_chain(root)
    fixture = root / "fixture.jsonl"
    _write_jsonl(fixture, rows)
    plan_path = root / "observer-plan.json"
    result = runtime.build_fixture_observer_plan(
        paper_plan_path=paper_plan_path,
        probe_report_path=report_path,
        runtime_contract_path=RUNTIME_CONTRACT,
        health_contract_path=HEALTH_CONTRACT,
        fixture_path=fixture,
        output_path=plan_path,
        audit_path=root / "audit.jsonl",
        accepted_path=root / "accepted.jsonl",
        manifest_path=root / "manifest.json",
        run_id="fixture-observer-v1",
        max_runtime_sec=1_800,
        generated_at_utc="2026-07-28T18:00:00+00:00",
    )
    return plan_path, result


class PaperObserverRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        if not RUNTIME_CONTRACT.is_file() or not HEALTH_CONTRACT.is_file():
            self.skipTest("frozen observer contracts are unavailable")

    def test_plan_refuses_without_paper_forward_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = root / "paper.json"
            report = root / "report.json"
            fixture = root / "fixture.jsonl"
            paper.write_text("{}", encoding="utf-8")
            report.write_text(
                json.dumps(
                    {
                        "verdict": "REJECT",
                        "safety": {
                            "live_orders": False,
                            "private_api_keys": False,
                            "leverage_or_margin": False,
                            "grid_search": False,
                            "retune": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            _write_jsonl(fixture, [_sample(1)])
            with self.assertRaisesRegex(ValueError, "PAPER_FORWARD_READY"):
                runtime.build_fixture_observer_plan(
                    paper_plan_path=paper,
                    probe_report_path=report,
                    runtime_contract_path=RUNTIME_CONTRACT,
                    health_contract_path=HEALTH_CONTRACT,
                    fixture_path=fixture,
                    output_path=root / "plan.json",
                    audit_path=root / "audit.jsonl",
                    accepted_path=root / "accepted.jsonl",
                    manifest_path=root / "manifest.json",
                    run_id="rejected",
                )

    def test_healthy_sample_is_accepted_and_stale_sample_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2, stale_gate=True)])
            manifest = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertTrue(manifest["final"])
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertEqual(manifest["completed_samples"], 2)
            self.assertEqual(manifest["accepted_samples"], 1)
            self.assertEqual(manifest["blocked_samples"], 1)
            audit = runtime._read_jsonl(root / "audit.jsonl")
            self.assertEqual(
                [row["health"]["decision"] for row in audit],
                ["HEALTHY_TRANSITION_ALLOWED", "BLOCK_TRANSITION"],
            )
            accepted = runtime._read_jsonl(root / "accepted.jsonl")
            self.assertEqual(len(accepted), 1)
            self.assertIn("execution_books", accepted[0]["observation"])
            self.assertTrue(accepted[0]["observation"]["data_quality_ok"])

    def test_public_snapshot_bridge_builds_hash_bound_health_sample(self) -> None:
        if not PUBLIC_READER_FIXTURE.is_file():
            self.skipTest("public reader fixture evidence is unavailable")
        fixture_report = json.loads(
            PUBLIC_READER_FIXTURE.read_text(encoding="utf-8")
        )
        contract = json.loads(
            Path(fixture_report["contract"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        now_ms = 1_800_000_000_000
        snapshots = {}
        for venue in ("mexc", "gateio"):
            transport = public_reader.FixturePublicGetTransport(
                public_reader._valid_fixture_outcomes(now_ms)
            )
            reader = public_reader.FixturePublicMarketReader(
                contract, transport
            )
            snapshots[venue] = reader.read_market_snapshot(
                venue=venue,
                symbol="HYPE_USDT",
                canonical_base="hype",
                observer_received_ts_ms=now_ms,
            )
        sample = runtime.build_public_snapshot_health_sample(
            mexc_snapshot=snapshots["mexc"],
            gateio_snapshot=snapshots["gateio"],
        )
        repeated = runtime.build_public_snapshot_health_sample(
            mexc_snapshot=snapshots["mexc"],
            gateio_snapshot=snapshots["gateio"],
        )
        self.assertEqual(sample, repeated)
        self.assertEqual(sample["canonical_base"], "HYPE")
        self.assertEqual(sample["schema"], runtime.PUBLIC_BRIDGE_SAMPLE_SCHEMA)
        self.assertGreaterEqual(
            sample["mexc"]["buy_capacity_quote_at_10bps"], 500.0
        )
        self.assertGreaterEqual(
            sample["gateio"]["sell_capacity_quote_at_10bps"], 500.0
        )
        health_contract = json.loads(
            HEALTH_CONTRACT.read_text(encoding="utf-8")
        )
        health = runtime.evaluate_fixture_health(sample, health_contract)
        self.assertEqual(health["decision"], "BLOCK_TRANSITION")
        self.assertEqual(health["reasons"], ["spread_too_wide"])

    def test_public_snapshot_bridge_rejects_stale_reader_fixture(
        self,
    ) -> None:
        if not PUBLIC_READER_FIXTURE.is_file():
            self.skipTest("public reader fixture evidence is unavailable")
        with self.assertRaisesRegex(
            ValueError,
            "current normalized snapshots drift from fixture evidence",
        ):
            runtime.build_public_snapshot_observer_bridge_report(
                public_reader_fixture_path=PUBLIC_READER_FIXTURE,
                generated_at_utc="2026-07-29T04:50:00+00:00",
            )

    def test_public_health_contract_binding_blocks_oms_transition(self) -> None:
        if not PUBLIC_BRIDGE_FIXTURE.is_file():
            self.skipTest("public bridge fixture evidence is unavailable")
        first = (
            runtime.build_public_health_contract_binding_fixture_report(
                bridge_report_path=PUBLIC_BRIDGE_FIXTURE,
                health_contract_path=HEALTH_CONTRACT,
                generated_at_utc="2026-07-29T05:10:00+00:00",
            )
        )
        second = (
            runtime.build_public_health_contract_binding_fixture_report(
                bridge_report_path=PUBLIC_BRIDGE_FIXTURE,
                health_contract_path=HEALTH_CONTRACT,
                generated_at_utc="2026-07-29T05:10:00+00:00",
            )
        )
        self.assertEqual(first, second)
        self.assertEqual(first["health"]["decision"], "BLOCK_TRANSITION")
        self.assertEqual(first["health"]["reasons"], ["spread_too_wide"])
        self.assertFalse(first["oms_transition_allowed"])
        self.assertEqual(first["network_requests"], 0)
        self.assertEqual(first["oms_mutations"], 0)
        self.assertEqual(
            first["verdict"],
            "FIXTURE_PUBLIC_HEALTH_BINDING_BLOCKED_AS_EXPECTED",
        )
        self.assertEqual(
            first["next_allowed_action"],
            "paper_product_readiness_audit_v5",
        )

    def test_incomplete_segment_resumes_same_run_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2), _sample(3)])
            incomplete = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                max_new_samples=1,
            )
            self.assertFalse(incomplete["final"])
            self.assertEqual(incomplete["status"], "STOPPED_INCOMPLETE")
            resumed = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertTrue(resumed["final"])
            self.assertEqual(resumed["completed_samples"], 3)
            self.assertEqual(len(runtime._read_jsonl(root / "audit.jsonl")), 3)
            self.assertEqual(len(runtime._read_jsonl(root / "accepted.jsonl")), 3)

    def test_plan_hash_mismatch_refuses_before_output_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, _plan_payload = _plan(root, [_sample(1)])
            with self.assertRaisesRegex(ValueError, "expected hash"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash="0" * 64,
                )
            self.assertFalse((root / "manifest.json").exists())
            self.assertFalse((root / "audit.jsonl").exists())

    def test_integrity_failure_cannot_be_resumed_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken = _sample(1)
            broken["gateio"]["schema_ok"] = False
            plan_path, plan = _plan(root, [broken])
            with self.assertRaisesRegex(ValueError, "fatal failure"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                )
            manifest = runtime._read_json(root / "manifest.json")
            self.assertEqual(manifest["stop_reason"], "validation_or_integrity_failure")
            self.assertEqual(
                manifest["incident_state"]["current_state"],
                "FATAL_SCHEMA_FAILURE",
            )
            audit = runtime._read_jsonl(root / "audit.jsonl")
            self.assertEqual(audit[-1]["incident"]["event"], "FATAL_SCHEMA_FAILURE")
            with self.assertRaisesRegex(ValueError, "fail-closed review"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                )

    def test_transient_degradation_recovers_without_fake_accepted_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            degraded = _sample(1)
            degraded["mexc"]["transport_ok"] = False
            plan_path, plan = _plan(root, [degraded, _sample(2)])
            manifest = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )

            self.assertTrue(manifest["final"])
            self.assertEqual(manifest["accepted_samples"], 1)
            self.assertEqual(manifest["incident_state"]["current_state"], "HEALTHY")
            self.assertEqual(manifest["incident_state"]["recovery_count"], 1)
            audit = runtime._read_jsonl(root / "audit.jsonl")
            self.assertEqual(
                [row["incident"]["event"] for row in audit],
                ["TRANSIENT_DEGRADATION_STARTED", "RECOVERED"],
            )
            accepted = runtime._read_jsonl(root / "accepted.jsonl")
            self.assertEqual([row["sample_sequence"] for row in accepted], [2])

    def test_persistent_stale_state_survives_resume_then_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                _sample(1, stale_gate=True),
                _sample(2, stale_gate=True),
                _sample(3, stale_gate=True),
                _sample(4),
            ]
            plan_path, plan = _plan(root, rows)
            partial = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                max_new_samples=3,
            )
            self.assertFalse(partial["final"])
            self.assertEqual(
                partial["incident_state"]["current_state"],
                "PERSISTENT_STALE_DATA",
            )

            resumed = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertTrue(resumed["final"])
            self.assertEqual(resumed["incident_state"]["current_state"], "HEALTHY")
            self.assertEqual(resumed["incident_state"]["recovery_count"], 1)
            audit = runtime._read_jsonl(root / "audit.jsonl")
            self.assertEqual(audit[2]["incident"]["event"], "PERSISTENT_STALE_DATA")
            self.assertEqual(audit[3]["incident"]["event"], "RECOVERED")
            self.assertEqual(
                [row["sample_sequence"] for row in runtime._read_jsonl(root / "accepted.jsonl")],
                [4],
            )

    def test_recomputed_plan_hash_cannot_hide_runtime_code_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1)])
            plan["code_provenance"]["runtime_module"]["file_sha256"] = "0" * 64
            plan["plan_hash"] = runtime._plan_hash(plan)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "runtime code drift"):
                runtime.validate_fixture_observer_plan(plan_path, plan["plan_hash"])

    def test_fixture_plan_has_no_network_or_live_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _path, plan = _plan(root, [_sample(1)])
            self.assertFalse(plan["runtime"]["network_access"])
            self.assertEqual(plan["runtime"]["source_provider"], "deterministic_jsonl_fixture")
            self.assertFalse(plan["safety"]["live_orders"])
            self.assertFalse(plan["safety"]["private_api_keys"])
            self.assertEqual(plan["maximum_authority"], "FIXTURE_RUNTIME_VERIFIED")

    def test_oms_sink_applies_only_healthy_observations_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2, stale_gate=True)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            ledger = root / "paper-ledger.jsonl"
            state = root / "paper-state.json"
            sink_manifest = root / "sink-manifest.json"
            first = runtime.run_fixture_observer_oms_sink(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                ledger_path=ledger,
                state_path=state,
                sink_manifest_path=sink_manifest,
            )
            ledger_before = ledger.read_bytes()

            self.assertTrue(first["final"])
            self.assertEqual(first["accepted_observations"], 1)
            self.assertEqual(first["applied_observations"], 1)
            self.assertEqual(runtime._read_json(state)["status"], "OPEN")
            self.assertIn("A00", runtime._read_json(state)["positions"])

            repeated = runtime.run_fixture_observer_oms_sink(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                ledger_path=ledger,
                state_path=state,
                sink_manifest_path=sink_manifest,
            )
            self.assertEqual(repeated["deterministic_result_hash"], first["deterministic_result_hash"])
            self.assertEqual(ledger.read_bytes(), ledger_before)

    def test_oms_sink_resumes_without_duplicate_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2), _sample(3)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            ledger = root / "paper-ledger.jsonl"
            state = root / "paper-state.json"
            sink_manifest = root / "sink-manifest.json"
            partial = runtime.run_fixture_observer_oms_sink(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                ledger_path=ledger,
                state_path=state,
                sink_manifest_path=sink_manifest,
                max_new_observations=1,
            )
            self.assertFalse(partial["final"])
            self.assertEqual(partial["stop_reason"], "bounded_interruption")

            resumed = runtime.run_fixture_observer_oms_sink(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                ledger_path=ledger,
                state_path=state,
                sink_manifest_path=sink_manifest,
            )
            self.assertTrue(resumed["final"])
            self.assertEqual(resumed["applied_observations"], 3)
            events = runtime._read_jsonl(ledger)
            recorded = [
                event
                for event in events
                if event.get("event_type") == "OBSERVATION_RECORDED"
            ]
            self.assertEqual(len(recorded), 3)
            self.assertTrue(
                runtime.reconcile_historical_basis_v2_paper_state(state, ledger)["matched"]
            )

    def test_oms_sink_refuses_before_observer_is_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                max_new_samples=1,
            )
            with self.assertRaisesRegex(ValueError, "final and completed"):
                runtime.run_fixture_observer_oms_sink(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    ledger_path=root / "paper-ledger.jsonl",
                    state_path=root / "paper-state.json",
                    sink_manifest_path=root / "sink-manifest.json",
                )
            self.assertFalse((root / "paper-ledger.jsonl").exists())

    def test_oms_sink_hash_mismatch_does_not_initialize_oms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            with self.assertRaisesRegex(ValueError, "expected hash"):
                runtime.run_fixture_observer_oms_sink(
                    plan_path=plan_path,
                    expected_plan_hash="0" * 64,
                    ledger_path=root / "paper-ledger.jsonl",
                    state_path=root / "paper-state.json",
                    sink_manifest_path=root / "sink-manifest.json",
                )
            self.assertFalse((root / "paper-ledger.jsonl").exists())

    def test_run_mvp_exposes_fixture_only_routes(self) -> None:
        source = (REPO_ROOT / "trading_mvp" / "run_mvp.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('"fast-edge-basis-v2-paper-observer-fixture-plan"', source)
        self.assertIn('"fast-edge-basis-v2-paper-observer-fixture-run"', source)
        self.assertIn('"fast-edge-basis-v2-paper-observer-fixture-sink"', source)
        self.assertIn("paper_observer_runtime.py", source)


if __name__ == "__main__":
    unittest.main()
