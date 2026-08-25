from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import preipo_plan  # noqa: E402


class PreIPOV9ContractTests(unittest.TestCase):
    def _validate_payload(self, payload: dict) -> dict:
        payload["plan_hash"] = preipo_plan.canonical_plan_hash(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "plan.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return preipo_plan.validate_plan(path)

    def test_runtime_defaults_use_a_new_immutable_v9_identity(self) -> None:
        self.assertEqual(preipo_plan.PLAN_ID, "preipo_perpetual_event_20260825_v9")
        self.assertEqual(
            preipo_plan.DEFAULT_PLAN_PATH.name,
            "preipo-perpetual-event-planonly-20260825-v9.json",
        )
        self.assertEqual(
            preipo_plan.SUPERSEDED_PLAN_PATH.name,
            "preipo-perpetual-event-planonly-20260825-v8.json",
        )

    def test_v9_declares_the_real_venue_and_candidate_scope_change(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )

        binding = payload["source_bindings"]["technical_rebind"]
        self.assertIs(binding["research_scope_changed"], True)
        self.assertEqual(binding["baseline_active_venues"], ["gate", "okx"])
        self.assertEqual(binding["baseline_candidate_venues"], ["bybit"])
        self.assertEqual(
            set(binding["current_active_venues"]),
            {"bitmex", "gate", "kraken", "okx"},
        )
        self.assertEqual(
            set(binding["current_candidate_venues"]),
            {"binance", "bybit", "coinbase_intx", "cryptocom"},
        )
        self.assertIn("active_venues", binding["changed_dimensions"])
        self.assertIn("candidate_venues", binding["changed_dimensions"])
        self.assertEqual(
            set(payload["candidate_venues"]),
            {"binance", "bybit", "coinbase_intx", "cryptocom"},
        )

    def test_all_active_venues_have_distinct_fail_closed_source_contracts(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )

        data = payload["data_contract"]
        self.assertIn("public_source_contracts", data)
        self.assertIn("official_first_trade_source_contract", data)
        sources = data["public_source_contracts"]
        self.assertEqual(set(sources), {"bitmex", "gate", "kraken", "okx"})
        expected_metadata = {
            "bitmex": ("www.bitmex.com", "/api/v1/instrument/active", "listing"),
            "gate": ("api.gateio.ws", "/api/v4/futures/usdt/contracts", "launch_time"),
            "kraken": (
                "futures.kraken.com",
                "/derivatives/api/v3/instruments",
                "openingDate",
            ),
            "okx": ("www.okx.com", "/api/v5/public/instruments", "listTime"),
        }
        for venue, (host, path, field) in expected_metadata.items():
            with self.subTest(venue=venue):
                metadata = sources[venue]["instrument_metadata"]
                self.assertEqual(metadata["host"], host)
                self.assertEqual(metadata["path"], path)
                self.assertEqual(metadata["timestamp_field"], field)
                self.assertEqual(
                    metadata["timestamp_kind"], "premarket_contract_launch_ts"
                )
                self.assertIs(sources[venue]["auto_proves_official_first_trade"], False)

        gate = sources["gate"]
        self.assertEqual(
            gate["official_event_family"]["perpetual_announcement_path_prefix"],
            "/announcements/article/",
        )
        self.assertIn("mirror_note", gate["excluded_product_families"])
        self.assertIn("spot_preipo_asset_certificate", gate["excluded_product_families"])

        t0 = data["official_first_trade_source_contract"]
        self.assertEqual(t0["timestamp_kind"], "official_first_trade_ts")
        self.assertEqual(t0["meaning"], "underlying_equity_first_executed_trade")
        self.assertEqual(
            t0["resolver"], "preipo_perp_event.parse_announcement"
        )
        self.assertEqual(t0["unresolved_policy"], "descriptive_only")
        self.assertEqual(
            set(t0["required_fields"]),
            {
                "venue",
                "contract_id",
                "underlying_symbol",
                "quote",
                "source_url",
                "announcement_ts",
                "official_first_trade_ts",
            },
        )
        self.assertEqual(t0["required_binding_arguments"], ["source_family"])
        self.assertIn("contract_provenance_fields", t0)
        self.assertEqual(
            t0["contract_provenance_fields"],
            [
                "official_first_trade_ts",
                "official_first_trade_announcement_ts",
                "official_first_trade_source_class",
                "official_first_trade_source_url",
                "official_first_trade_source_family",
            ],
        )
        self.assertEqual(
            t0["allowed_source_families"],
            {
                "bitmex": "bitmex_official_equity_first_trade_notice",
                "gate": "gate_preipo_perpetual_official_first_trade_notice",
                "kraken": "kraken_official_equity_first_trade_notice",
                "okx": "okx_official_equity_first_trade_notice",
            },
        )
        self.assertEqual(
            set(t0["disallowed_substitutions"]),
            {
                "premarket_contract_launch_ts",
                "contract_first_trading_ts",
                "first_trade_ts",
                "ipo_open_ts",
                "ipo_start_ts",
                "first_trading_ts",
                "conversion_window_ts",
                "transition_ts",
                "rebase_ts",
                "expected_ipo_date",
                "first_observed_trade_ts",
            },
        )

    def test_every_candidate_has_explicit_all_of_promotion_conditions(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )

        self.assertIn("candidate_promotion_conditions", payload)
        conditions = payload["candidate_promotion_conditions"]
        self.assertEqual(
            set(conditions),
            {"binance", "bybit", "coinbase_intx", "cryptocom"},
        )
        common = {
            "official_preipo_perpetual_product_evidence",
            "public_unauthenticated_instrument_and_lifecycle_api",
            "public_market_data_adapter",
            "equity_timestamp_taxonomy",
            "preipo_equity_asset_class_separation",
            "adapter_fixtures_and_failure_tests",
            "https_allow_list_and_provenance_audit",
        }
        for venue, contract in conditions.items():
            with self.subTest(venue=venue):
                self.assertEqual(contract["status"], "candidate_only")
                self.assertIs(contract["automatic_promotion_allowed"], False)
                self.assertTrue(common.issubset(set(contract["promotion_requires_all"])))

        self.assertIn(
            "official_binance_preipo_listing_source",
            conditions["binance"]["promotion_requires_all"],
        )
        self.assertIn(
            "official_bybit_contract_and_timestamp_method",
            conditions["bybit"]["promotion_requires_all"],
        )
        self.assertIn(
            "documented_index_methodology_and_internal_index_caveat",
            conditions["coinbase_intx"]["promotion_requires_all"],
        )
        self.assertIn(
            "documented_contract_listing_and_lifecycle_timestamps",
            conditions["cryptocom"]["promotion_requires_all"],
        )

    def test_validator_rejects_a_contract_launch_promoted_to_equity_t0(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        payload["data_contract"]["public_source_contracts"]["bitmex"][
            "instrument_metadata"
        ]["timestamp_kind"] = "official_first_trade_ts"

        result = self._validate_payload(payload)

        self.assertFalse(result["ok"])
        self.assertIn("public_source_contracts_invalid", result["reasons"])

    def test_validator_rejects_a_scope_change_marked_as_technical_only(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        payload["source_bindings"]["technical_rebind"][
            "research_scope_changed"
        ] = False

        result = self._validate_payload(payload)

        self.assertFalse(result["ok"])
        self.assertIn("research_scope_change_binding_invalid", result["reasons"])

    def test_validator_rejects_missing_candidate_promotion_condition(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        del payload["candidate_promotion_conditions"]["coinbase_intx"]

        result = self._validate_payload(payload)

        self.assertFalse(result["ok"])
        self.assertIn("candidate_promotion_conditions_invalid", result["reasons"])

    def test_v9_uses_an_equity_first_trade_anchor_without_stale_bybit_claims(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )

        anchor = payload["temporal_anchor_contract"]
        self.assertEqual(
            anchor["module"], "trading_mvp/src/preipo_temporal_anchor.py"
        )
        self.assertEqual(
            anchor["official_anchor_kinds"], ["official_first_trade_ts"]
        )
        self.assertEqual(anchor["primary_t0_kind"], "official_first_trade_ts")
        self.assertIn("required_exact_provenance", anchor)
        self.assertEqual(
            anchor["required_exact_provenance"],
            [
                "active_venue",
                "positive_finite_official_first_trade_ts",
                "positive_finite_announcement_ts",
                "official_source_class",
                "venue_official_source_url",
            ],
        )
        self.assertIn("premarket_contract_launch_ts", anchor["proxy_anchor_kinds"])
        self.assertIn("transition_ts", anchor["proxy_anchor_kinds"])
        measured = anchor["measured"]
        self.assertNotIn("preMktSwTime", measured)
        self.assertIn("Bybit is candidate-only", measured)

    def test_binance_is_a_candidate_event_source_but_never_acceptance_active(self) -> None:
        import preipo_perp_event

        self.assertIn("binance", preipo_perp_event.CANDIDATE_VENUES)
        event = preipo_perp_event.parse_announcement(
            {
                "venue": "binance",
                "source_url": "https://www.binance.com/en/support/announcement/example",
                "contract_id": "SPCXUSDT",
                "underlying_symbol": "SPACEX",
                "quote": "USDT",
                "official_first_trade_ts": 1_780_003_600,
            }
        )
        self.assertEqual(event.source_class, "official")
        self.assertFalse(event.acceptance_eligible)

    def test_plan_binds_the_equity_specific_temporal_anchor_runtime(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        roles = {row["role"]: row for row in payload["implementation"]}

        self.assertIn("preipo_temporal_anchor_taxonomy", roles)
        self.assertNotIn("temporal_anchor_taxonomy", roles)
        self.assertTrue(
            roles["preipo_temporal_anchor_taxonomy"]["path"].endswith(
                "trading_mvp\\src\\preipo_temporal_anchor.py"
            )
        )

    def test_validator_rejects_transition_promoted_to_an_official_anchor(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        payload["temporal_anchor_contract"]["official_anchor_kinds"] = [
            "transition_ts"
        ]

        result = self._validate_payload(payload)

        self.assertFalse(result["ok"])
        self.assertIn("preipo_temporal_anchor_contract_invalid", result["reasons"])

    def test_commands_and_production_launcher_are_bound_to_v9(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        launcher = (
            Path(__file__).resolve().parents[2]
            / "tools"
            / "start_preipo_perpetual_event_automation_visible.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "preipo-perpetual-event-planonly-20260825-v9.json",
            payload["commands"]["plan_check"],
        )
        self.assertIn(
            "preipo-perpetual-event-planonly-20260825-v9.json", launcher
        )
        self.assertIn("use the immutable v9 default", launcher)

    def test_rebind_error_names_the_actual_immutable_v8_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wrong = Path(temp_dir) / "wrong.json"
            wrong.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source_plan_must_be_immutable_v8"):
                preipo_plan.build_rebound_plan(
                    wrong,
                    "2026-08-25T18:00:00Z",
                )

    def test_implementation_provenance_names_the_v9_scope_correction(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        for row in payload["implementation"]:
            with self.subTest(role=row["role"]):
                self.assertEqual(
                    row["change"]["kind"],
                    "preipo_scope_and_equity_t0_contract_v9",
                )
                self.assertEqual(
                    row["change"]["superseded_plan_hash"],
                    preipo_plan.SUPERSEDED_PLAN["plan_hash"],
                )

    def test_venue_verification_covers_every_active_and_candidate_venue(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        verified = payload["venue_verification"]["venues"]

        self.assertEqual(
            set(verified), set(payload["venues"]) | set(payload["candidate_venues"])
        )
        for venue in payload["venues"]:
            with self.subTest(venue=venue, state="active"):
                self.assertIs(verified[venue]["adapter"], True)
                self.assertEqual(verified[venue]["status"], "active")
        for venue in payload["candidate_venues"]:
            with self.subTest(venue=venue, state="candidate"):
                self.assertIs(verified[venue]["adapter"], False)
                self.assertEqual(verified[venue]["status"], "candidate_only")

    def test_validator_rejects_incomplete_venue_verification(self) -> None:
        payload = preipo_plan.build_rebound_plan(
            preipo_plan.SUPERSEDED_PLAN_PATH,
            "2026-08-25T18:00:00Z",
        )
        del payload["venue_verification"]["venues"]["binance"]

        result = self._validate_payload(payload)

        self.assertFalse(result["ok"])
        self.assertIn("venue_verification_invalid", result["reasons"])


if __name__ == "__main__":
    unittest.main()
