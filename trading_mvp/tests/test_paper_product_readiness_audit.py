from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_product_readiness_audit as audit_module  # noqa: E402


def _components(decision: str = "SCHEDULE_WAIT_OFFLINE_AUTOPILOT_ACTIVE") -> dict:
    return {
        "fast-regression-lane-v1.json": {"successful": True},
        "paper-public-reader-contract-v1.json": {},
        "paper-public-reader-fixture-v1.json": {"network_requests": 0},
        "paper-public-cache-idempotency-v1.json": {"network_requests": 0},
        "pit-train-progress-monitor-v1.json": {
            "decision": decision,
            "gate": {"replay_allowed": False},
            "quality": {"accepted_distinct_dates": 4},
            "train_eta": {
                "target_accepted_dates": 20,
                "earliest_possible_train_checkpoint_date_if_each_future_date_passes": "2026-08-13",
            },
            "next_segment": {
                "run_id": "pit_next",
                "start_local": "2026-07-29T01:00:00+03:00",
            },
        },
        "paper-code-provenance-merkle-v1.json": {},
        "paper-forward-failure-runbook-v1.json": {},
        "paper-product-readiness-audit-v2.json": {},
    }


def _components_v4() -> dict:
    components = _components()
    components.update(
        {
            "paper-public-retry-rate-limit-fixture-v1.json": {
                "network_requests": 0,
                "scenario_count": 6,
                "accepted_scenario_count": 6,
            },
            "paper-public-snapshot-observer-bridge-v1.json": {
                "network_requests": 0,
                "oms_mutations": 0,
                "snapshot_hashes_match_fixture": True,
                "health_decision": "NOT_EVALUATED_BRIDGE_ONLY",
                "oms_transition_allowed": False,
            },
            "paper-public-transport-adapter-v1.json": {
                "network_requests": 0,
                "adapter_network_capable": True,
                "response_byte_limit": {
                    "declared_oversize_rejected": True,
                },
            },
            "paper-code-provenance-merkle-v2.json": {},
            "paper-product-readiness-audit-v3.json": {},
        }
    )
    return components


def _components_v5() -> dict:
    components = _components_v4()
    components.update(
        {
            "paper-code-provenance-merkle-v3.json": {},
            "paper-public-reader-transport-wiring-fixture-v1.json": {
                "network_requests": 0,
                "fixture_session_calls": 8,
                "responses_closed": True,
                "normalized_snapshots": [{}, {}],
            },
            "paper-public-streaming-byte-limit-fixture-v1.json": {
                "network_requests": 0,
                "scenario": {
                    "observed_category": "response_too_large",
                    "response_closed": True,
                },
            },
            "paper-public-health-contract-binding-fixture-v1.json": {
                "network_requests": 0,
                "oms_mutations": 0,
                "oms_transition_allowed": False,
                "health": {"decision": "BLOCK_TRANSITION"},
            },
            "paper-product-readiness-audit-v4.json": {},
        }
    )
    return components


def _components_v6() -> dict:
    components = _components_v5()
    components.update(
        {
            "paper-code-provenance-merkle-v4.json": {},
            "paper-public-system-clock-fixture-v1.json": {
                "network_requests": 0,
                "token_bucket": {"second_wait_ms": 500},
                "retry_after_ms": 2000,
            },
            "paper-public-transport-retry-wiring-fixture-v2.json": {
                "network_requests": 0,
                "retry_trace": [{"reason": "http_503"}],
            },
            "paper-public-cache-transport-integration-fixture-v1.json": {
                "network_requests": 0,
                "oms_mutations": 0,
                "cache": {"lookup_status": "HIT"},
                "snapshot_hash_sha256": "a" * 64,
                "replay_snapshot_hash_sha256": "a" * 64,
            },
            "paper-product-readiness-audit-v5.json": {},
        }
    )
    return components


def _components_v7() -> dict:
    components = _components_v6()
    components.update(
        {
            "paper-code-provenance-merkle-v5.json": {},
            "paper-public-runtime-reader-factory-fixture-v1.json": {
                "network_requests": 0,
                "fixture_session_calls": 8,
                "factory": {"clock_type": "SystemClock"},
            },
            "paper-public-endpoint-contract-parity-fixture-v1.json": {
                "network_requests": 0,
                "endpoint_count": 8,
                "venue_counts": {"mexc": 4, "gateio": 4},
            },
            "paper-public-readonly-probe-plan-v1.json": {
                "plan_hash_sha256": "b" * 64,
                "probe": {
                    "duration_sec": 120,
                    "max_runtime_sec": 180,
                    "venues": ["mexc", "gateio"],
                },
                "authorization": {
                    "network_authorized": False,
                    "execution_authorized": False,
                },
                "safety": {
                    "network_requests_performed": 0,
                    "market_data_writer_started": False,
                },
            },
            "paper-product-readiness-audit-v6.json": {},
        }
    )
    return components


def _components_v8() -> dict:
    components = _components_v7()
    components.update(
        {
            "paper-public-reader-contract-v3.json": {},
            "paper-public-readonly-probe-plan-v3.json": {
                "plan_hash_sha256": "c" * 64,
                "probe": {
                    "venues": ["mexc", "gateio"],
                    "max_cycles": 24,
                    "planned_endpoint_reads": 192,
                    "maximum_public_get_attempts": 576,
                    "maximum_quote_age_ms_by_venue": {
                        "mexc": 6000,
                        "gateio": 5000,
                    },
                },
                "compatibility_scope": {
                    "maximum_quote_age_ms_by_venue": {
                        "mexc": 6000,
                        "gateio": 5000,
                    },
                    "venue_universe_hypothesis_signal_cost_changed": False,
                    "private_live_leverage_margin_changed": False,
                    "maximum_runs_for_new_plan_hash": 1,
                },
            },
            "paper-public-readonly-probe-evidence-v3.json": {
                "schema": (
                    "trading_mvp_paper_public_readonly_probe_evidence_v3"
                ),
                "probe_result": {
                    "run_id": "paper_public_readonly_probe_v3_test",
                    "plan_hash_sha256": "c" * 64,
                },
                "quality": {
                    "venues": ["mexc", "gateio"],
                    "expected_snapshot_count": 48,
                    "snapshot_count": 48,
                    "error_count": 0,
                    "application_error_rate": 0.0,
                    "partial_output": False,
                    "hard_stop_reason": None,
                    "planned_endpoint_reads": 192,
                    "network_requests": 192,
                    "maximum_public_get_attempts": 576,
                    "maximum_quote_age_ms_by_venue": {
                        "mexc": 6000,
                        "gateio": 5000,
                    },
                },
                "safety": {
                    "public_get_only": True,
                    "returns_or_pnl_read": False,
                    "signals_read": False,
                    "oms_mutations": 0,
                    "private_api_keys": False,
                    "live_orders": False,
                    "leverage_or_margin": False,
                    "grid_or_retune": False,
                    "hypothesis_changed": False,
                },
                "next_allowed_action": "paper_product_readiness_audit_v8",
            },
            "paper-product-readiness-audit-v7.json": {},
        }
    )
    return components


def _components_v9() -> dict:
    components = _components_v8()
    components.update(
        {
            "paper-code-provenance-merkle-v6.json": {},
            "paper-public-probe-evidence-observer-binding-fixture-v1.json": {
                "schema": (
                    "trading_mvp_public_probe_evidence_observer_binding_"
                    "fixture_v1"
                ),
                "task_id": (
                    "paper_public_probe_evidence_observer_binding_fixture_v1"
                ),
                "inputs": {
                    "probe_plan": {
                        "plan_hash_sha256": "c" * 64,
                    },
                    "probe_evidence": {},
                    "probe_manifest": {},
                },
                "observer_input": {
                    "schema": "trading_mvp_public_probe_observer_input_v1",
                    "mode": (
                        "IMMUTABLE_PUBLIC_PROBE_EVIDENCE_DESCRIPTOR_ONLY"
                    ),
                    "run_id": "paper_public_readonly_probe_v3_test",
                    "plan_hash_sha256": "c" * 64,
                    "venues": ["mexc", "gateio"],
                    "snapshot_count": 48,
                    "network_requests_in_source_probe": 192,
                    "maximum_quote_age_ms_by_venue": {
                        "mexc": 6000,
                        "gateio": 5000,
                    },
                    "health_decision": "NOT_EVALUATED_DESCRIPTOR_ONLY",
                    "oms_transition_allowed": False,
                    "paper_forward_allowed": False,
                    "live_allowed": False,
                },
                "source_probe_network_requests": 192,
                "network_requests_performed_by_task": 0,
                "returns_or_pnl_read": False,
                "oos_read": False,
                "signals_read": False,
                "oms_transition_allowed": False,
                "oms_mutations": 0,
                "paper_forward_started": False,
                "private_api_keys": False,
                "live_orders": False,
                "leverage_or_margin": False,
                "grid_or_retune": False,
                "hypothesis_changed": False,
                "verdict": (
                    "PUBLIC_PROBE_EVIDENCE_BOUND_TO_FAIL_CLOSED_"
                    "OBSERVER_INPUT"
                ),
                "next_allowed_action": "paper_product_readiness_audit_v9",
                "deterministic_result_hash": "d" * 64,
            },
            "paper-product-readiness-audit-v8.json": {},
        }
    )
    return components


class PaperProductReadinessAuditTests(unittest.TestCase):
    def test_evidence_gates_remain_blocked(self) -> None:
        result = audit_module.build_readiness_assessment(
            components=_components(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 48, "status": "PASS"},
        )
        self.assertEqual(result["readiness"]["fixture_paper_product"], "READY")
        self.assertEqual(
            result["readiness"]["public_network_transport"],
            "NOT_IMPLEMENTED",
        )
        self.assertFalse(result["evidence_gates"]["edge_proven"])
        self.assertFalse(result["evidence_gates"]["paper_forward_ready"])
        self.assertFalse(result["evidence_gates"]["live_review_eligible"])

    def test_waiting_schedule_requires_new_bounded_catalog(self) -> None:
        result = audit_module.build_readiness_assessment(
            components=_components(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 48, "status": "PASS"},
        )
        self.assertEqual(
            result["next_allowed_action"],
            "derive_and_install_catalog_v3_then_continue_bounded_offline_work",
        )
        self.assertGreaterEqual(
            len(result["next_bounded_catalog_requirement"]), 4
        )
        self.assertTrue(
            all(
                not item["network"]
                for item in result["next_bounded_catalog_requirement"]
            )
        )

    def test_code_provenance_drift_is_explicit(self) -> None:
        result = audit_module.build_readiness_assessment(
            components=_components(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 48, "status": "PASS"},
        )
        self.assertEqual(
            result["readiness"]["code_provenance"],
            "STALE_AFTER_NEW_CODE",
        )
        self.assertEqual(
            result["next_bounded_catalog_requirement"][0]["id"],
            "paper_code_provenance_merkle_v2",
        )

    def test_train_checkpoint_is_not_bypassed(self) -> None:
        components = _components()
        components["pit-train-progress-monitor-v1.json"]["quality"][
            "accepted_distinct_dates"
        ] = 20
        with self.assertRaisesRegex(ValueError, "must stop"):
            audit_module.build_readiness_assessment(
                components=components,
                code_provenance_current=True,
                targeted_tests={"tests_run": 48, "status": "PASS"},
            )

    def test_failed_targeted_tests_block_fixture_readiness(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixture readiness"):
            audit_module.build_readiness_assessment(
                components=_components(),
                code_provenance_current=True,
                targeted_tests={"tests_run": 0, "status": "FAIL"},
            )

    def test_v4_marks_public_data_plane_fixture_ready_but_blocks_live(
        self,
    ) -> None:
        result = audit_module.build_readiness_assessment_v4(
            components=_components_v4(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 67, "status": "PASS"},
        )
        self.assertEqual(
            result["readiness"]["public_network_transport"],
            "IMPLEMENTED_FIXTURE_TESTED_NOT_NETWORK_PROBED",
        )
        self.assertEqual(
            result["readiness"]["dual_venue_observer_bridge"],
            "PASS_BRIDGE_ONLY",
        )
        self.assertFalse(result["evidence_gates"]["edge_proven"])
        self.assertFalse(result["evidence_gates"]["paper_forward_ready"])
        self.assertFalse(result["evidence_gates"]["live_review_eligible"])
        self.assertEqual(
            result["next_bounded_catalog_requirement"][0]["id"],
            "paper_code_provenance_merkle_v3",
        )
        self.assertTrue(
            all(
                task["network"] is False
                for task in result["next_bounded_catalog_requirement"]
            )
        )

    def test_v4_fails_closed_when_bridge_mutated_oms(self) -> None:
        components = _components_v4()
        components["paper-public-snapshot-observer-bridge-v1.json"][
            "oms_mutations"
        ] = 1
        with self.assertRaisesRegex(ValueError, "catalog v3 fixture"):
            audit_module.build_readiness_assessment_v4(
                components=components,
                code_provenance_current=False,
                targeted_tests={"tests_run": 67, "status": "PASS"},
            )

    def test_v5_marks_runtime_wiring_ready_but_keeps_evidence_blocked(
        self,
    ) -> None:
        result = audit_module.build_readiness_assessment_v5(
            components=_components_v5(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 76, "status": "PASS"},
        )
        self.assertEqual(
            result["readiness"]["public_network_transport"],
            "WIRED_FIXTURE_TESTED_NOT_NETWORK_PROBED",
        )
        self.assertEqual(
            result["public_data_plane"]["health_binding_decision"],
            "BLOCK_TRANSITION",
        )
        self.assertFalse(result["evidence_gates"]["edge_proven"])
        self.assertFalse(result["evidence_gates"]["paper_forward_ready"])
        self.assertFalse(result["evidence_gates"]["live_review_eligible"])
        self.assertEqual(
            result["next_bounded_catalog_requirement"][0]["id"],
            "paper_code_provenance_merkle_v4",
        )

    def test_v6_marks_offline_runtime_ready_but_blocks_forward(self) -> None:
        result = audit_module.build_readiness_assessment_v6(
            components=_components_v6(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 80, "status": "PASS"},
        )
        self.assertEqual(
            result["readiness"]["public_network_transport"],
            "OFFLINE_RUNTIME_CHAIN_READY_NOT_NETWORK_PROBED",
        )
        self.assertEqual(
            result["readiness"]["public_snapshot_cache"],
            "PASS_TRANSPORT_INTEGRATED",
        )
        self.assertFalse(result["evidence_gates"]["edge_proven"])
        self.assertFalse(result["evidence_gates"]["paper_forward_ready"])
        self.assertFalse(result["evidence_gates"]["live_review_eligible"])

    def test_v7_stops_at_public_probe_user_review_checkpoint(self) -> None:
        result = audit_module.build_readiness_assessment_v7(
            components=_components_v7(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 90, "status": "PASS"},
        )
        self.assertEqual(
            result["critical_checkpoint"]["status"],
            "USER_REVIEW_REQUIRED",
        )
        self.assertEqual(
            result["critical_checkpoint"]["requested_action"],
            "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE",
        )
        self.assertEqual(result["next_bounded_catalog_requirement"], [])
        self.assertFalse(result["evidence_gates"]["edge_proven"])
        self.assertFalse(result["evidence_gates"]["paper_forward_ready"])
        self.assertFalse(result["evidence_gates"]["live_review_eligible"])

    def test_v8_accepts_probe_but_keeps_edge_and_forward_gates_closed(
        self,
    ) -> None:
        result = audit_module.build_readiness_assessment_v8(
            components=_components_v8(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 97, "status": "PASS"},
        )
        self.assertIsNone(result["critical_checkpoint"])
        self.assertEqual(
            result["readiness"]["public_network_transport"],
            "PUBLIC_READONLY_PROBE_ACCEPTED_BOUNDED_RESEARCH_ONLY",
        )
        self.assertEqual(
            result["maximum_authority"],
            "PUBLIC_READONLY_RESEARCH_EVIDENCE_ONLY",
        )
        self.assertFalse(result["evidence_gates"]["edge_proven"])
        self.assertFalse(result["evidence_gates"]["paper_forward_ready"])
        self.assertFalse(result["evidence_gates"]["live_review_eligible"])
        self.assertEqual(
            [item["id"] for item in result["next_bounded_catalog_requirement"]],
            [
                "paper_code_provenance_merkle_v6",
                "paper_public_probe_evidence_observer_binding_fixture_v1",
                "paper_product_readiness_audit_v9",
            ],
        )
        self.assertTrue(
            all(
                item["network"] is False
                for item in result["next_bounded_catalog_requirement"]
            )
        )

    def test_v8_rejects_changed_quote_freshness_contract(self) -> None:
        components = _components_v8()
        components["paper-public-readonly-probe-evidence-v3.json"]["quality"][
            "maximum_quote_age_ms_by_venue"
        ]["mexc"] = 7000
        with self.assertRaisesRegex(
            ValueError, "v8 public read-only probe evidence"
        ):
            audit_module.build_readiness_assessment_v8(
                components=components,
                code_provenance_current=False,
                targeted_tests={"tests_run": 97, "status": "PASS"},
            )

    def test_v8_rejects_private_or_live_scope_drift(self) -> None:
        components = _components_v8()
        components["paper-public-readonly-probe-evidence-v3.json"]["safety"][
            "private_api_keys"
        ] = True
        with self.assertRaisesRegex(
            ValueError, "v8 public read-only probe evidence"
        ):
            audit_module.build_readiness_assessment_v8(
                components=components,
                code_provenance_current=False,
                targeted_tests={"tests_run": 97, "status": "PASS"},
            )

    def test_v9_closes_offline_catalog_without_opening_evidence_gates(
        self,
    ) -> None:
        result = audit_module.build_readiness_assessment_v9(
            components=_components_v9(),
            code_provenance_current=False,
            targeted_tests={"tests_run": 100, "status": "PASS"},
        )
        self.assertIsNone(result["critical_checkpoint"])
        self.assertEqual(
            result["readiness"]["public_network_transport"],
            "PUBLIC_READONLY_PROBE_BOUND_FAIL_CLOSED_RESEARCH_ONLY",
        )
        self.assertEqual(
            result["public_data_plane"]["readonly_probe_observer_binding"],
            "PASS_FAIL_CLOSED",
        )
        self.assertFalse(result["evidence_gates"]["edge_proven"])
        self.assertFalse(result["evidence_gates"]["paper_forward_ready"])
        self.assertFalse(result["evidence_gates"]["live_review_eligible"])
        self.assertEqual(result["next_bounded_catalog_requirement"], [])
        self.assertEqual(
            result["next_allowed_action"],
            "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
        )
        self.assertFalse(
            result["offline_gap_assessment"][
                "materially_useful_same_contract_tasks_remaining"
            ]
        )

    def test_v9_rejects_observer_oms_mutation(self) -> None:
        components = _components_v9()
        binding = components[
            "paper-public-probe-evidence-observer-binding-fixture-v1.json"
        ]
        binding["oms_mutations"] = 1
        with self.assertRaisesRegex(
            ValueError, "v9 public probe observer binding"
        ):
            audit_module.build_readiness_assessment_v9(
                components=components,
                code_provenance_current=False,
                targeted_tests={"tests_run": 100, "status": "PASS"},
            )

    def test_v9_rejects_observer_plan_hash_drift(self) -> None:
        components = _components_v9()
        binding = components[
            "paper-public-probe-evidence-observer-binding-fixture-v1.json"
        ]
        binding["observer_input"]["plan_hash_sha256"] = "e" * 64
        with self.assertRaisesRegex(
            ValueError, "v9 public probe observer binding"
        ):
            audit_module.build_readiness_assessment_v9(
                components=components,
                code_provenance_current=False,
                targeted_tests={"tests_run": 100, "status": "PASS"},
            )


if __name__ == "__main__":
    unittest.main()
