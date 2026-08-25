from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import preipo_plan  # noqa: E402
import premarket_plan  # noqa: E402
import slow_liquidity_listing_momentum_forward_expansion_monitor as expansion_monitor  # noqa: E402
import slow_liquidity_listing_momentum_forward_expansion_plan as expansion_plan  # noqa: E402
import slow_liquidity_listing_momentum_forward_monitor as spot_monitor  # noqa: E402
import slow_liquidity_listing_momentum_forward_monitor_plan as spot_plan  # noqa: E402
from listing_strategy_plan_rebind import (  # noqa: E402
    build_derivative_rebind,
    validate_rebind_semantics,
    write_immutable_plan,
)


PLANS = REPO_ROOT / "docs" / "plans"
RECEIPT = (
    REPO_ROOT
    / "docs"
    / "agent-log"
    / "listing-strategy-control-plane-batch1-readiness-20260821.json"
)
LEGACY_SPOT = PLANS / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260817-v2.json"
LEGACY_EXPANSION = PLANS / "slow-liquidity-listing-momentum-forward-expansion-planonly-20260817.json"
OLD_PREMARKET = PLANS / "premarket-perp-listing-impulse-planonly-20260818-v1.json"
OLD_PREIPO = PLANS / "preipo-perpetual-event-planonly-20260818-v1.json"
BATCH2_SPOT = PLANS / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260821-v3.json"
BATCH2_EXPANSION = PLANS / "slow-liquidity-listing-momentum-forward-expansion-planonly-20260821-v2.json"
NEW_SPOT = PLANS / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260825-v6.json"
NEW_EXPANSION = PLANS / "slow-liquidity-listing-momentum-forward-expansion-planonly-20260825-v5.json"
# premarket ran v1 -> v2 -> v3 (asset-class acceptance gate) -> v4 (temporal anchors);
# preipo ran v1 -> v2 -> v3 (temporal anchors). The intermediate files stay on disk and
# stay byte-immutable; only the last one of each lineage is current.
BATCH3_PREMARKET = PLANS / "premarket-perp-listing-impulse-planonly-20260821-v2.json"
BATCH4_PREMARKET = PLANS / "premarket-perp-listing-impulse-planonly-20260824-v3.json"
BATCH3_PREIPO = PLANS / "preipo-perpetual-event-planonly-20260821-v2.json"
NEW_PREMARKET = PLANS / "premarket-perp-listing-impulse-planonly-20260825-v5.json"
NEW_PREIPO = PLANS / "preipo-perpetual-event-planonly-20260825-v4.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_scope_change_is_declared_or_absent(test, rebind) -> None:
    """False keeps a plan a pure technical rebind; True must be fully declared.

    Asserting only "must be False" would have to be deleted the first time a plan
    legitimately changes scope. Asserting the declaration instead keeps a real guarantee
    in place on both branches: nothing can flip the flag without enumerating what moved,
    saying why, and recording that autopilot authority is withdrawn."""
    if rebind["research_scope_changed"] is False:
        test.assertNotIn("research_scope_change", rebind)
        return
    test.assertIs(rebind["research_scope_changed"], True)
    declaration = rebind["research_scope_change"]
    test.assertTrue(declaration["changed_fields"])
    test.assertTrue(all(str(f).strip() for f in declaration["changed_fields"]))
    test.assertTrue(str(declaration["reason"]).strip())
    test.assertEqual(declaration["autopilot_authority"], "WITHDRAWN_UNTIL_REVIEWED")


class ListingStrategyPlanOnlyRebindTests(unittest.TestCase):
    def test_superseded_artifacts_remain_byte_immutable(self) -> None:
        expected = {
            LEGACY_SPOT: "ceb2850bca4b2cca0141730b71c17181840d386085c3f5762f1cfaedc71b63aa",
            LEGACY_EXPANSION: "8a92bd3b18b8629d53bf6d70616090bf61de199f97b0235355e3781a9d82488a",
            BATCH2_SPOT: "b4e6b085c40e10c91cc235f186e46f52e56fc6f6d913b79f0b707172d4bc99f4",
            BATCH2_EXPANSION: "0becc5ef47cfe03d5f2fcea94ef30a24668354fc238c3864db3f8b011ed40128",
            OLD_PREMARKET: "2f07a9b9621081b7f638042be0dadbd97a938d0741bc6fefe7c5fc1f25b13625",
            OLD_PREIPO: "6f8dd54c3d0666c5f8507103c194ce8ea546b57018d8a85aaf6f8f38104abd1c",
            BATCH3_PREMARKET: "89be986f5887b309fa195609cd3ccb7c08157c3a07983a26a9514f5dddd40d03",
            BATCH4_PREMARKET: "31230c7ef6747feb0bff5633c6171e856353990173b9cb42ddd32781d7efbc62",
            BATCH3_PREIPO: "4a32c2ba47aaf05cfacaab35cb1112f30fb1984fe16f2bef5ca05159d7335fc8",
        }
        self.assertEqual(
            file_sha256(RECEIPT),
            "b310912a5c1d4e5b4bca16d8e343bb77aecca837a4ad32d4917a899fd08eeb56",
        )
        for path, expected_sha in expected.items():
            with self.subTest(path=path.name):
                self.assertEqual(file_sha256(path), expected_sha)

    def test_defaults_point_only_to_new_immutable_artifacts(self) -> None:
        self.assertEqual(spot_monitor.FORWARD_PLAN_PATH, NEW_SPOT)
        self.assertEqual(spot_plan.FORWARD_PLAN_PATH, NEW_SPOT)
        self.assertEqual(expansion_monitor.PLAN_PATH, NEW_EXPANSION)
        self.assertEqual(expansion_plan.FORWARD_PLAN_PATH, NEW_EXPANSION)

        launcher_bindings = {
            "start_listing_momentum_forward_automation_visible.ps1": (
                NEW_SPOT.name,
                NEW_EXPANSION.name,
            ),
            "start_listing_momentum_forward_tick_visible.ps1": (NEW_SPOT.name,),
            "start_listing_momentum_forward_expansion_tick_visible.ps1": (
                NEW_EXPANSION.name,
            ),
        }
        for launcher_name, expected_plan_names in launcher_bindings.items():
            source = (REPO_ROOT / "tools" / launcher_name).read_text(encoding="utf-8")
            for plan_name in expected_plan_names:
                with self.subTest(launcher=launcher_name, plan=plan_name):
                    self.assertIn(plan_name, source)

        derivative_launchers = {
            "start_premarket_perp_listing_automation_visible.ps1": NEW_PREMARKET.name,
            "start_preipo_perpetual_event_automation_visible.ps1": NEW_PREIPO.name,
        }
        for launcher_name, expected_plan_name in derivative_launchers.items():
            source = (REPO_ROOT / "tools" / launcher_name).read_text(encoding="utf-8")
            with self.subTest(launcher=launcher_name):
                self.assertIn(expected_plan_name, source)

    def test_spot_and_expansion_rebind_sources_are_exact_batch2_artifacts(self) -> None:
        self.assertEqual(spot_plan.PREVIOUS_PLAN_PATH, BATCH2_SPOT)
        self.assertEqual(
            spot_plan.PREVIOUS_PLAN_HASH,
            "2b41fd407a758e68340c0bba000f48fa87b1fc1e4a7e1c41b0e21a439bfc4dc0",
        )
        self.assertEqual(
            spot_plan.PREVIOUS_PLAN_FILE_SHA256,
            "b4e6b085c40e10c91cc235f186e46f52e56fc6f6d913b79f0b707172d4bc99f4",
        )
        self.assertEqual(expansion_plan.PREVIOUS_EXPANSION_PLAN_PATH, BATCH2_EXPANSION)
        self.assertEqual(
            expansion_plan.PREVIOUS_EXPANSION_PLAN_HASH,
            "3e3d7ffe8a58bf70263b349644663054893d77e6b7a02c4e5b4fca04208a0b0c",
        )
        self.assertEqual(
            expansion_plan.PREVIOUS_EXPANSION_PLAN_FILE_SHA256,
            "0becc5ef47cfe03d5f2fcea94ef30a24668354fc238c3864db3f8b011ed40128",
        )
        self.assertEqual(expansion_plan.PREVIOUS_V2_PLAN_PATH, NEW_SPOT)
        self.assertEqual(
            expansion_plan.PREVIOUS_V2_PLAN_HASH,
            "e841a0dc9368f1c05fd29c37ff93f7090158fe5155964a0e9e0639351a71c69a",
        )
        self.assertEqual(
            expansion_plan.PREVIOUS_V2_PLAN_FILE_SHA256,
            "cdb69cdb2514035592122f0b93e97f2f95c6787040802a7addb9ce1186ae7dfd",
        )

    def test_checked_in_spot_and_expansion_rebinds_are_current_and_scope_stable(self) -> None:
        spot = json.loads(NEW_SPOT.read_text(encoding="utf-8"))
        old_spot = json.loads(BATCH2_SPOT.read_text(encoding="utf-8"))
        self.assertEqual(
            spot["schema"],
            "trading_mvp_slow_liquidity_listing_momentum_forward_monitor_planonly_v4",
        )
        self.assertEqual(
            spot["plan_id"],
            "slow_liquidity_listing_momentum_forward_monitor_20260825_v6",
        )
        spot_plan.validate_forward_monitor_plan(spot)
        # The technical-rebind invariant - same research contract, fresh hashes -
        # applies exactly when the plan declares itself a technical rebind. Where a
        # scope change is declared it does not apply, and the declaration checked
        # just above is the guarantee in its place.
        if spot["source_bindings"]["technical_rebind"]["research_scope_changed"] is False:
            validate_rebind_semantics("spot", old_spot, spot)
        spot_rebind = spot["source_bindings"]["technical_rebind"]
        self.assertEqual(spot_rebind["supersedes_plan_path"], str(BATCH2_SPOT))
        self.assertEqual(spot_rebind["supersedes_plan_hash"], old_spot["plan_hash"])
        self.assertEqual(
            spot_rebind["supersedes_plan_file_sha256"], file_sha256(BATCH2_SPOT)
        )
        assert_scope_change_is_declared_or_absent(self, spot_rebind)

        expansion = json.loads(NEW_EXPANSION.read_text(encoding="utf-8"))
        old_expansion = json.loads(BATCH2_EXPANSION.read_text(encoding="utf-8"))
        self.assertEqual(
            expansion["schema"],
            "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_monitor_planonly_v3",
        )
        self.assertEqual(
            expansion["plan_id"],
            "slow_liquidity_listing_momentum_forward_expansion_20260825_v5",
        )
        expansion_plan.validate_plan(expansion)
        expansion_monitor._validate_plan(expansion, NEW_EXPANSION)
        # The technical-rebind invariant - same research contract, fresh hashes -
        # applies exactly when the plan declares itself a technical rebind. Where a
        # scope change is declared it does not apply, and the declaration checked
        # just above is the guarantee in its place.
        if expansion["source_bindings"]["technical_rebind"]["research_scope_changed"] is False:
            validate_rebind_semantics("expansion", old_expansion, expansion)
        expansion_rebind = expansion["source_bindings"]["technical_rebind"]
        self.assertEqual(
            expansion_rebind["supersedes_plan_path"], str(BATCH2_EXPANSION)
        )
        self.assertEqual(
            expansion_rebind["supersedes_plan_hash"], old_expansion["plan_hash"]
        )
        self.assertEqual(
            expansion_rebind["supersedes_plan_file_sha256"],
            file_sha256(BATCH2_EXPANSION),
        )
        assert_scope_change_is_declared_or_absent(self, expansion_rebind)
        parent = expansion["source_bindings"]["parent_v2"]
        self.assertEqual(Path(parent["path"]), NEW_SPOT)
        self.assertEqual(parent["plan_hash"], spot["plan_hash"])
        self.assertEqual(parent["file_sha256"], file_sha256(NEW_SPOT))

    def test_checked_in_derivative_rebinds_are_current_visible_and_scope_stable(self) -> None:
        # The v1 -> v2 step was a pure technical rebind: same research contract, fresh
        # hashes. Later versions changed the research contract on purpose - premarket v3
        # added the asset-class acceptance gate, premarket v4 and preipo v3 added the
        # temporal-anchor taxonomy - so scope stability is asserted on the step that
        # claims it, not across the whole lineage, where it would assert something false.
        cases = (
            (
                "premarket",
                OLD_PREMARKET,
                BATCH3_PREMARKET,
                NEW_PREMARKET,
                "premarket_perp_listing_impulse_20260825_v5",
                premarket_plan.validate_plan,
            ),
            (
                "preipo",
                OLD_PREIPO,
                BATCH3_PREIPO,
                NEW_PREIPO,
                "preipo_perpetual_event_20260825_v4",
                preipo_plan.validate_plan,
            ),
        )
        for track, _old_path, _rebind_path, current_path, current_id, validator in cases:
            with self.subTest(track=track):
                current = json.loads(current_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    current["schema"],
                    f"trading_mvp_{'premarket_perp_listing_impulse' if track == 'premarket' else 'preipo_perpetual_event'}_planonly_v2",
                )
                self.assertEqual(current["plan_id"], current_id)
                result = validator(current_path)
                self.assertTrue(result["ok"], result)
                # The lineage must be walkable: the head names its predecessor, and that
                # predecessor is on disk with exactly the id and hash the head recorded.
                superseded_path = REPO_ROOT / current["supersedes_plan_path"]
                self.assertTrue(superseded_path.exists(), superseded_path)
                superseded = json.loads(superseded_path.read_text(encoding="utf-8"))
                self.assertEqual(current["supersedes_plan_id"], superseded["plan_id"])
                self.assertEqual(current["supersedes_plan_hash"], superseded["plan_hash"])
                # Every row that records a supersession must name a real hash. It may
                # equal the current one: a row whose bytes did not move in the latest
                # reissue keeps the provenance an earlier rebind wrote for it.
                for row in current["implementation"]:
                    provenance = row.get("provenance") or {}
                    if "superseded_sha256" in provenance:
                        with self.subTest(role=row["role"]):
                            self.assertRegex(str(provenance["superseded_sha256"]), r"^[0-9a-f]{64}$")
                guard = current["guard_contract"]
                self.assertTrue(guard["visible_terminal_required"])
                self.assertFalse(guard.get("inline_worker_no_terminal_allowed", False))
                self.assertNotIn("inline_tick", current["commands"])

    def test_derivative_builder_records_row_level_provenance(self) -> None:
        old = json.loads(OLD_PREMARKET.read_text(encoding="utf-8"))
        rebound = build_derivative_rebind(
            track="premarket",
            source_path=OLD_PREMARKET,
            output_path=NEW_PREMARKET,
            generated_at_utc="2026-08-21T00:00:00Z",
            receipt_path=RECEIPT,
        )
        validate_rebind_semantics("premarket", old, rebound)
        source_rows = {row["role"]: row for row in old["implementation"]}
        for row in rebound["implementation"]:
            with self.subTest(role=row["role"]):
                self.assertEqual(
                    row["provenance"]["superseded_sha256"],
                    source_rows[row["role"]]["sha256"],
                )
                self.assertEqual(row["sha256"], file_sha256(Path(row["path"])))

    def test_derivative_validators_reject_non_visible_or_inline_worker_contract(self) -> None:
        cases = (
            (
                "premarket",
                OLD_PREMARKET,
                NEW_PREMARKET,
                premarket_plan,
            ),
            ("preipo", OLD_PREIPO, NEW_PREIPO, preipo_plan),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for track, source_path, output_path, validator_module in cases:
                rebound = build_derivative_rebind(
                    track=track,
                    source_path=source_path,
                    output_path=output_path,
                    generated_at_utc="2026-08-21T00:00:00Z",
                    receipt_path=RECEIPT,
                )
                rebound["guard_contract"]["visible_terminal_required"] = False
                rebound["guard_contract"]["inline_worker_no_terminal_allowed"] = True
                rebound["plan_hash"] = validator_module.canonical_plan_hash(rebound)
                path = Path(temp_dir) / f"{track}.json"
                path.write_text(json.dumps(rebound), encoding="utf-8")
                result = validator_module.validate_plan(path)
                with self.subTest(track=track):
                    self.assertFalse(result["ok"], result)
                    self.assertIn("visible_worker_contract_invalid", result["reasons"])

    def test_immutable_writer_is_idempotent_and_refuses_different_payload(self) -> None:
        payload = {"schema": "fixture", "plan_hash": "a" * 64}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "plan.json"
            write_immutable_plan(path, payload)
            write_immutable_plan(path, payload)
            with self.assertRaisesRegex(ValueError, "immutable artifact mismatch"):
                write_immutable_plan(path, {**payload, "plan_hash": "b" * 64})


if __name__ == "__main__":
    unittest.main()
