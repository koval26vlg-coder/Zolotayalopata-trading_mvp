from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from trading_mvp.src.slow_liquidity_identity_request_plan_discovery import (
    BASES,
    DISCOVERY_PLAN_SCHEMA,
    FetchedResponse,
    RequestPlanDiscoveryError,
    RUNTIME_MANIFEST_SCHEMA,
    _canonical_identifier_from_official_page,
    _discover_request_plan_from_fixture_responses,
    build_discovery_plan,
    build_runtime_manifest,
    canonical_hash_without,
    discover_request_plan,
    freeze_offline_bundle,
    preflight_execution,
    validate_discovery_plan,
    validate_runtime_manifest,
    write_discovery_output,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT_RUNTIME_MANIFEST = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-runtime-manifest-20260815-v7.json"
)


def _current_parent_runtime_manifest() -> Path:
    return PARENT_RUNTIME_MANIFEST


class DiscoveryPlanTests(unittest.TestCase):
    def test_plan_covers_exact_pairs_and_is_canonical(self) -> None:
        plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")

        self.assertEqual(plan["schema"], DISCOVERY_PLAN_SCHEMA)
        self.assertEqual(len(plan["seed_items"]), 18)
        self.assertEqual(
            {(item["venue"], item["base_ticker"]) for item in plan["seed_items"]},
            {(venue, base) for base in BASES for venue in ("mexc", "gateio")},
        )
        self.assertEqual(
            plan["plan_hash"],
            canonical_hash_without(plan, "plan_hash"),
        )
        self.assertFalse(plan["execution_authorization"]["actual_network_run_allowed"])
        self.assertFalse(
            plan["currentness_contract"][
                "metadata_to_official_page_linkage_implemented"
            ]
        )
        self.assertFalse(
            plan["currentness_contract"][
                "synthetic_fixture_may_claim_real_completion"
            ]
        )
        validate_discovery_plan(plan)

    def test_plan_rejects_navigation_host_tamper(self) -> None:
        plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
        plan["seed_items"][0]["search_url"] = "https://example.com/search?q=STETH"
        plan["plan_hash"] = canonical_hash_without(plan, "plan_hash")

        with self.assertRaisesRegex(RequestPlanDiscoveryError, "navigation host"):
            validate_discovery_plan(plan)


class DiscoveryRuntimeTests(unittest.TestCase):
    def test_runtime_manifest_binds_plan_code_tests_and_keeps_execution_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp:
            root = Path(temp)
            plan_path = root / "plan.json"
            plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest = build_runtime_manifest(
                discovery_plan_path=plan_path,
                parent_identity_runtime_manifest_path=_current_parent_runtime_manifest(),
                runtime_module_path=REPO_ROOT
                / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py",
                synthetic_tests_path=Path(__file__),
                guard_checker_path=REPO_ROOT / "tools/check_trading_mvp_autopilot.ps1",
                generated_at_utc="2026-08-13T18:10:00Z",
                user_authorization_text="разрешаю",
                response_annotation_index=1,
            )

            self.assertEqual(manifest["schema"], RUNTIME_MANIFEST_SCHEMA)
            self.assertEqual(manifest["discovery_plan"]["plan_hash"], plan["plan_hash"])
            self.assertFalse(
                manifest["execution_authorization"]["actual_network_run_allowed"]
            )
            self.assertFalse(
                manifest["execution_authorization"]["output_creation_allowed"]
            )
            self.assertFalse(
                manifest["execution_authorization"]["global_writer_claim_allowed"]
            )
            self.assertFalse(
                manifest["execution_authorization"]["execution_manifest_supported"]
            )
            self.assertTrue(manifest["runtime"]["synthetic_fixture_parser_only"])
            self.assertFalse(
                manifest["runtime"]["network_discovery_callable_exposed"]
            )
            self.assertEqual(
                manifest["manifest_hash"],
                canonical_hash_without(manifest, "manifest_hash"),
            )
            validate_runtime_manifest(manifest)

    def test_runtime_manifest_rejects_network_permission_tamper(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp:
            root = Path(temp)
            plan_path = root / "plan.json"
            plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest = build_runtime_manifest(
                discovery_plan_path=plan_path,
                parent_identity_runtime_manifest_path=_current_parent_runtime_manifest(),
                runtime_module_path=REPO_ROOT
                / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py",
                synthetic_tests_path=Path(__file__),
                guard_checker_path=REPO_ROOT / "tools/check_trading_mvp_autopilot.ps1",
                generated_at_utc="2026-08-13T18:10:00Z",
                user_authorization_text="разрешаю",
                response_annotation_index=1,
            )
            manifest["execution_authorization"]["actual_network_run_allowed"] = True
            manifest["manifest_hash"] = canonical_hash_without(
                manifest, "manifest_hash"
            )

            with self.assertRaisesRegex(RequestPlanDiscoveryError, "network"):
                validate_runtime_manifest(manifest)

    def test_runtime_manifest_rejects_alternate_module_even_with_matching_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp:
            root = Path(temp)
            plan_path = root / "plan.json"
            alternate_module = root / "alternate.py"
            alternate_module.write_text("VALUE = 1\n", encoding="utf-8")
            plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest = build_runtime_manifest(
                discovery_plan_path=plan_path,
                parent_identity_runtime_manifest_path=_current_parent_runtime_manifest(),
                runtime_module_path=REPO_ROOT
                / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py",
                synthetic_tests_path=Path(__file__),
                guard_checker_path=REPO_ROOT / "tools/check_trading_mvp_autopilot.ps1",
                generated_at_utc="2026-08-13T18:10:00Z",
                user_authorization_text="разрешаю",
                response_annotation_index=1,
            )
            manifest["runtime"]["module_path"] = str(alternate_module.resolve())
            import hashlib

            manifest["runtime"]["module_sha256"] = hashlib.sha256(
                alternate_module.read_bytes()
            ).hexdigest()
            manifest["manifest_hash"] = canonical_hash_without(
                manifest, "manifest_hash"
            )

            with self.assertRaisesRegex(RequestPlanDiscoveryError, "module path"):
                validate_runtime_manifest(manifest)

    def test_offline_freeze_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp:
            root = Path(temp)
            bundle = root / "bundle"
            kwargs = {
                "discovery_plan_path": bundle / "plan.json",
                "runtime_manifest_path": bundle / "runtime.json",
                "parent_identity_runtime_manifest_path": (
                    _current_parent_runtime_manifest()
                ),
                "runtime_module_path": REPO_ROOT
                / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py",
                "synthetic_tests_path": Path(__file__),
                "guard_checker_path": REPO_ROOT
                / "tools/check_trading_mvp_autopilot.ps1",
                "plan_generated_at_utc": "2026-08-13T18:00:00Z",
                "manifest_generated_at_utc": "2026-08-13T18:10:00Z",
                "user_authorization_text": "разрешаю",
                "response_annotation_index": 1,
            }

            first = freeze_offline_bundle(**kwargs)
            second = freeze_offline_bundle(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(
                sorted(path.name for path in bundle.iterdir()),
                ["plan.json", "runtime.json"],
            )
            self.assertFalse(first["actual_network_run_allowed"])
            self.assertFalse(first["output_creation_allowed"])

    def test_offline_freeze_bad_authorization_leaves_no_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"

            with self.assertRaisesRegex(
                RequestPlanDiscoveryError,
                "authorization text mismatch",
            ):
                freeze_offline_bundle(
                    discovery_plan_path=bundle / "plan.json",
                    runtime_manifest_path=bundle / "runtime.json",
                    parent_identity_runtime_manifest_path=PARENT_RUNTIME_MANIFEST,
                    runtime_module_path=REPO_ROOT
                    / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py",
                    synthetic_tests_path=Path(__file__),
                    guard_checker_path=REPO_ROOT
                    / "tools/check_trading_mvp_autopilot.ps1",
                    plan_generated_at_utc="2026-08-13T18:00:00Z",
                    manifest_generated_at_utc="2026-08-13T18:10:00Z",
                    user_authorization_text="нет",
                    response_annotation_index=1,
                )

            self.assertFalse(bundle.exists())

    def test_discovery_builds_compatible_request_plan_from_official_pages(self) -> None:
        plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
        address_by_base = {
            base: f"0x{index:040x}" for index, base in enumerate(BASES, start=1)
        }
        official_by_search: dict[str, tuple[str, str]] = {}
        official_bodies: dict[str, bytes] = {}
        for item in plan["seed_items"]:
            base = item["base_ticker"]
            if item["venue"] == "mexc":
                official_url = (
                    "https://www.mexc.com/support/articles/"
                    f"{base.lower()}-usdt-contract"
                )
            else:
                official_url = (
                    "https://www.gate.com/announcements/article/"
                    f"{base.lower()}-usdt-contract"
                )
            official_by_search[item["search_url"]] = (base, official_url)
            official_bodies[official_url] = (
                f"<html>{base} {base}_USDT Contract Address "
                f"{address_by_base[base]}</html>"
            ).encode("utf-8")

        mexc_metadata = {
            "success": True,
            "code": 0,
            "data": [
                {
                    "symbol": f"{base}_USDT",
                    "baseCoin": base,
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "state": 0,
                    "apiAllowed": True,
                }
                for base in BASES
            ],
        }
        gate_metadata = [
            {"name": f"{base}_USDT", "status": "trading", "in_delisting": False}
            for base in BASES
        ]

        def fixture_response(url: str) -> FetchedResponse:
            if url.endswith("/api/v1/contract/detail"):
                body = json.dumps(mexc_metadata).encode("utf-8")
            elif url.endswith("/api/v4/futures/usdt/contracts"):
                body = json.dumps(gate_metadata).encode("utf-8")
            elif url in official_by_search:
                base, official_url = official_by_search[url]
                body = (
                    "<rss><channel><item>"
                    f"<title>{base} {base}_USDT Contract Address</title>"
                    f"<link>{official_url}</link>"
                    "</item></channel></rss>"
                ).encode("utf-8")
            else:
                body = official_bodies[url]
            return FetchedResponse(url, url, 200, body)

        response_urls = {
            *official_by_search,
            *official_bodies,
            "https://contract.mexc.com/api/v1/contract/detail",
            "https://api.gateio.ws/api/v4/futures/usdt/contracts",
        }
        responses = {url: fixture_response(url) for url in response_urls}
        result = _discover_request_plan_from_fixture_responses(
            plan,
            responses=responses,
        )

        self.assertEqual(result.status, "SYNTHETIC_FIXTURE_INCOMPLETE")
        self.assertLess(len(result.request_plan), 18)

    def test_tampered_plan_is_rejected_before_network(self) -> None:
        plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
        plan["seed_items"][0]["search_url"] = "https://example.com/search?q=STETH"
        plan["plan_hash"] = canonical_hash_without(plan, "plan_hash")
        with self.assertRaisesRegex(RequestPlanDiscoveryError, "navigation host"):
            _discover_request_plan_from_fixture_responses(plan, responses={})

    def test_public_discovery_entrypoint_cannot_call_network_fetcher(self) -> None:
        plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
        fetch = mock.Mock()

        with self.assertRaisesRegex(
            RequestPlanDiscoveryError,
            "network discovery execution is not authorized",
        ):
            discover_request_plan(plan, fetch=fetch)

        fetch.assert_not_called()

    def test_identifier_must_share_one_visible_fragment_with_instrument(self) -> None:
        plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
        target = plan["seed_items"][0]
        base = target["base_ticker"]
        official_url = "https://www.mexc.com/support/articles/false-binding"
        responses: dict[str, FetchedResponse] = {}
        mexc_metadata = {
            "success": True,
            "code": 0,
            "data": [
                {
                    "symbol": f"{item_base}_USDT",
                    "baseCoin": item_base,
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "state": 0,
                    "apiAllowed": True,
                }
                for item_base in BASES
            ],
        }
        gate_metadata = [
            {
                "name": f"{item_base}_USDT",
                "status": "trading",
                "in_delisting": False,
            }
            for item_base in BASES
        ]
        mexc_url = "https://contract.mexc.com/api/v1/contract/detail"
        gate_url = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
        responses[mexc_url] = FetchedResponse(
            mexc_url,
            mexc_url,
            200,
            json.dumps(mexc_metadata).encode("utf-8"),
        )
        responses[gate_url] = FetchedResponse(
            gate_url,
            gate_url,
            200,
            json.dumps(gate_metadata).encode("utf-8"),
        )
        for item in plan["seed_items"]:
            venue = item["venue"]
            item_base = item["base_ticker"]
            page_url = (
                official_url
                if item is target
                else (
                    f"https://www.mexc.com/support/articles/{item_base.lower()}-ok"
                    if venue == "mexc"
                    else "https://www.gate.com/announcements/article/"
                    f"{item_base.lower()}-ok"
                )
            )
            rss = (
                "<rss><channel><item>"
                f"<title>{item_base} {item_base}_USDT Contract Address</title>"
                f"<link>{page_url}</link>"
                "</item></channel></rss>"
            ).encode("utf-8")
            responses[item["search_url"]] = FetchedResponse(
                item["search_url"], item["search_url"], 200, rss
            )
            page = (
                f"<html>{base} {base}_USDT"
                + (" unrelated text" * 100)
                + " OTHER Contract Address 0x"
                + "1" * 40
                + "</html>"
                if item is target
                else (
                    f"<html>{item_base} {item_base}_USDT Contract Address "
                    f"0x{BASES.index(item_base) + 1:040x}</html>"
                )
            ).encode("utf-8")
            responses[page_url] = FetchedResponse(page_url, page_url, 200, page)

        result = _discover_request_plan_from_fixture_responses(
            plan,
            responses=responses,
        )

        self.assertEqual(result.status, "SYNTHETIC_FIXTURE_INCOMPLETE")
        self.assertIn(
            f"mexc:{base}:CANONICAL_IDENTIFIER_NOT_UNIQUE",
            result.unresolved_pairs,
        )
        self.assertNotIn(
            ("mexc", base),
            {
                (item["venue"], item["base_ticker"])
                for item in result.request_plan
            },
        )

    def test_hidden_script_text_cannot_supply_identity_evidence(self) -> None:
        body = (
            "<html><body>STETH STETH_USDT</body>"
            "<script>STETH STETH_USDT Contract Address "
            + "0x"
            + "1" * 40
            + "</script></html>"
        ).encode("utf-8")

        with self.assertRaisesRegex(
            RequestPlanDiscoveryError,
            "canonical identifier label",
        ):
            _canonical_identifier_from_official_page("STETH", body)

    def test_identity_output_creation_is_blocked_in_offline_phase(self) -> None:
        plan = build_discovery_plan(generated_at_utc="2026-08-13T18:00:00Z")
        result = mock.Mock(
            status="COMPLETE_REQUEST_PLAN",
            request_plan=tuple(
                {
                    "venue": item["venue"],
                    "official_source_url": (
                        "https://www.mexc.com/support/articles/test"
                        if item["venue"] == "mexc"
                        else "https://www.gate.com/announcements/article/test"
                    ),
                    "instrument_id": item["instrument_id"],
                    "base_ticker": item["base_ticker"],
                    "canonical_asset_identifier_namespace": "EVM_CONTRACT",
                    "canonical_asset_identifier_value": "0x" + "1" * 40,
                    "canonical_asset_identifier_label": "contract_address",
                    "evidence_locator_type": "CANONICAL_REQUIRED_EXACT_UTF8_TOKENS_V1",
                    "evidence_locator_value": json.dumps(
                        {
                            "base_ticker": item["base_ticker"],
                            "canonical_asset_identifier_label": "contract_address",
                            "canonical_asset_identifier_value": "0x" + "1" * 40,
                            "instrument_id": item["instrument_id"],
                            "venue": item["venue"],
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "sanitized_evidence_fragment": json.dumps(
                        {
                            "base_ticker": item["base_ticker"],
                            "canonical_asset_identifier_label": "contract_address",
                            "canonical_asset_identifier_value": "0x" + "1" * 40,
                            "instrument_id": item["instrument_id"],
                            "venue": item["venue"],
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
                for item in plan["seed_items"]
            ),
            unresolved_pairs=(),
            navigation_response_hashes=("a" * 64,),
            official_response_hashes=("b" * 64,),
            metadata_response_hashes=("c" * 64,),
            request_count=38,
        )
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "immutable"
            with self.assertRaisesRegex(
                RequestPlanDiscoveryError,
                "identity output creation is not authorized",
            ):
                write_discovery_output(
                    output,
                    plan=plan,
                    result=result,
                    runtime_manifest_binding={
                        "path": "C:/runtime.json",
                        "file_sha256": "d" * 64,
                        "manifest_hash": "e" * 64,
                    },
                    generated_at_utc="2026-08-13T18:10:00Z",
                )

            self.assertFalse(output.exists())

    def test_preflight_without_execution_manifest_has_no_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "must-not-exist"
            result = preflight_execution(
                runtime_manifest_path=root / "missing-runtime.json",
                execution_manifest_path=root / "missing-execution.json",
                output_path=output,
            )

            self.assertEqual(
                result["status"],
                "BLOCKED_AWAIT_EXACT_DISCOVERY_EXECUTION_APPROVAL",
            )
            self.assertFalse(result["network_accessed"])
            self.assertFalse(result["output_created"])
            self.assertFalse(output.exists())

    def test_preflight_rejects_unc_runtime_path_without_filesystem_probe(self) -> None:
        unc_path = r"\\127.0.0.1\blocked-share\runtime.json"
        with mock.patch.object(
            Path,
            "is_file",
            side_effect=AssertionError("remote filesystem probe attempted"),
        ):
            result = preflight_execution(
                runtime_manifest_path=unc_path,
                execution_manifest_path=r"\\127.0.0.1\blocked-share\execution.json",
                output_path=r"\\127.0.0.1\blocked-share\output",
            )

        self.assertEqual(
            result["status"],
            "BLOCKED_AWAIT_EXACT_DISCOVERY_EXECUTION_APPROVAL",
        )
        self.assertIn("remote path", result["reason"])
        self.assertFalse(result["network_accessed"])

    def test_offline_builders_reject_unc_before_filesystem_probe(self) -> None:
        unc_root = r"\\127.0.0.1\blocked-share\bundle"
        with mock.patch.object(
            Path,
            "is_file",
            side_effect=AssertionError("remote read probe attempted"),
        ):
            with self.assertRaisesRegex(RequestPlanDiscoveryError, "remote path"):
                build_runtime_manifest(
                    discovery_plan_path=unc_root + r"\plan.json",
                    parent_identity_runtime_manifest_path=PARENT_RUNTIME_MANIFEST,
                    runtime_module_path=REPO_ROOT
                    / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py",
                    synthetic_tests_path=Path(__file__),
                    guard_checker_path=REPO_ROOT
                    / "tools/check_trading_mvp_autopilot.ps1",
                    generated_at_utc="2026-08-13T18:10:00Z",
                    user_authorization_text="разрешаю",
                    response_annotation_index=1,
                )

        with mock.patch.object(
            Path,
            "exists",
            side_effect=AssertionError("remote write probe attempted"),
        ):
            with self.assertRaisesRegex(RequestPlanDiscoveryError, "remote path"):
                freeze_offline_bundle(
                    discovery_plan_path=unc_root + r"\plan.json",
                    runtime_manifest_path=unc_root + r"\runtime.json",
                    parent_identity_runtime_manifest_path=PARENT_RUNTIME_MANIFEST,
                    runtime_module_path=REPO_ROOT
                    / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py",
                    synthetic_tests_path=Path(__file__),
                    guard_checker_path=REPO_ROOT
                    / "tools/check_trading_mvp_autopilot.ps1",
                    plan_generated_at_utc="2026-08-13T18:00:00Z",
                    manifest_generated_at_utc="2026-08-13T18:10:00Z",
                    user_authorization_text="разрешаю",
                    response_annotation_index=1,
                )


if __name__ == "__main__":
    unittest.main()
