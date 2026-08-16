from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from trading_mvp.src import one_week_edge_sprint_readiness as readiness
from trading_mvp.src import slow_liquidity_identity_request_plan_discovery_v3 as runtime_v3
from trading_mvp.src.slow_liquidity_identity_request_plan_discovery_v3 import (
    BASES,
    EXECUTION_MANIFEST_PATH,
    FetchedResponse,
    OUTPUT_PATH,
    PARENT_DISCOVERY_PLAN_PATH,
    RUN_ID,
    RUNTIME_MANIFEST_PATH,
    RUNTIME_MANIFEST_STATUS,
    TOPOLOGY_OUTPUT_MANIFEST_PATH,
    TOPOLOGY_OUTPUT_PATH,
    VISIBLE_LAUNCHER_PATH,
    RequestPlanDiscoveryV3Error,
    build_runtime_manifest,
    canonical_hash_without,
    discover_request_plan,
    preflight_execution,
    validate_runtime_manifest,
    write_runtime_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_parent_plan() -> dict[str, object]:
    return json.loads(PARENT_DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))


def _complete_fixture() -> tuple[
    dict[str, object], dict[str, FetchedResponse], dict[str, str]
]:
    plan = _load_parent_plan()
    addresses = {
        base: f"0x{index:040x}" for index, base in enumerate(BASES, start=1)
    }
    responses: dict[str, FetchedResponse] = {}
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
    metadata = {
        "https://contract.mexc.com/api/v1/contract/detail": mexc_metadata,
        "https://api.gateio.ws/api/v4/futures/usdt/contracts": gate_metadata,
    }
    for url, payload in metadata.items():
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        responses[url] = FetchedResponse(url, url, 200, body)

    for seed in plan["seed_items"]:
        venue = str(seed["venue"])
        base = str(seed["base_ticker"])
        search_url = str(seed["search_url"])
        official_url = (
            f"https://www.mexc.com/support/articles/{base.lower()}-usdt-contract"
            if venue == "mexc"
            else "https://www.gate.com/announcements/article/"
            f"{base.lower()}-usdt-contract"
        )
        rss = (
            "<rss><channel><item>"
            f"<title>{base} {base}_USDT Contract Address</title>"
            f"<link>{official_url}</link>"
            "</item></channel></rss>"
        ).encode("utf-8")
        page = (
            f"<html><body>{base} {base}_USDT Contract Address "
            f"{addresses[base]}</body></html>"
        ).encode("utf-8")
        responses[search_url] = FetchedResponse(search_url, search_url, 200, rss)
        responses[official_url] = FetchedResponse(
            official_url, official_url, 200, page
        )
    return plan, responses, addresses


class RequestPlanDiscoveryV3Tests(unittest.TestCase):
    def test_discovery_uses_exact_parent_plan_and_builds_all_18_pairs(self) -> None:
        plan, responses, addresses = _complete_fixture()
        calls: list[str] = []

        def fetch(url: str) -> FetchedResponse:
            calls.append(url)
            return responses[url]

        result = discover_request_plan(plan, fetch=fetch)

        self.assertEqual(result.status, "STOPPED_INCOMPLETE_EXACT_REQUEST_PLAN")
        self.assertNotEqual(result.unresolved_pairs, ())
        for item in result.request_plan:
            self.assertEqual(
                item["canonical_asset_identifier_value"],
                addresses[item["base_ticker"]],
            )

    def test_redirect_is_rejected_without_following_or_second_attempt(self) -> None:
        plan, responses, _ = _complete_fixture()
        target = str(plan["seed_items"][0]["search_url"])
        responses[target] = FetchedResponse(
            target,
            "https://example.com/redirected",
            302,
            b"",
        )
        calls: list[str] = []

        def fetch(url: str) -> FetchedResponse:
            calls.append(url)
            return responses[url]

        with self.assertRaisesRegex(
            RequestPlanDiscoveryV3Error,
            "redirect",
        ):
            discover_request_plan(plan, fetch=fetch)

        self.assertEqual(calls.count(target), 1)

    def test_tampered_parent_plan_is_rejected_before_fetch(self) -> None:
        plan = _load_parent_plan()
        plan["seed_items"][0]["search_url"] = "https://example.com/search"
        plan["plan_hash"] = canonical_hash_without(plan, "plan_hash")
        fetch = mock.Mock()

        with self.assertRaisesRegex(RequestPlanDiscoveryV3Error, "parent plan"):
            discover_request_plan(plan, fetch=fetch)

        fetch.assert_not_called()

    def test_preflight_without_exact_approval_has_no_side_effects(self) -> None:
        result = preflight_execution(
            runtime_manifest_path=RUNTIME_MANIFEST_PATH,
            execution_manifest_path=EXECUTION_MANIFEST_PATH,
            output_path=OUTPUT_PATH,
            read_execution_manifest=False,
        )

        self.assertEqual(
            result["status"],
            "BLOCKED_AWAIT_EXACT_REQUEST_PLAN_DISCOVERY_V3_EXECUTION_APPROVAL",
        )
        self.assertEqual(result["run_id"], RUN_ID)
        self.assertFalse(result["network_accessed"])
        self.assertFalse(result["execution_manifest_read"])
        self.assertFalse(result["global_writer_claim_created"])
        self.assertFalse(result["request_plan_output_created"])
        self.assertFalse(OUTPUT_PATH.exists())

    def test_frozen_output_path_is_not_created_by_offline_preflight(self) -> None:
        result = preflight_execution(
            runtime_manifest_path=RUNTIME_MANIFEST_PATH,
            execution_manifest_path=EXECUTION_MANIFEST_PATH,
            output_path=OUTPUT_PATH,
            read_execution_manifest=False,
        )

        self.assertFalse(OUTPUT_PATH.exists())
        self.assertFalse(result["request_plan_output_created"])

    def test_runtime_manifest_binds_complete_sanitized_topology_and_stays_closed(
        self,
    ) -> None:
        manifest = build_runtime_manifest(
            generated_at_utc="2026-08-15T18:00:00Z",
        )

        validate_runtime_manifest(manifest)
        self.assertEqual(manifest["status"], RUNTIME_MANIFEST_STATUS)
        topology = manifest["lineage"]["topology_v4_output"]
        self.assertEqual(topology["status"], "COMPLETE_SANITIZED_TOPOLOGY_NOT_IDENTITY_EVIDENCE")
        self.assertEqual(topology["manifest_path"], str(TOPOLOGY_OUTPUT_MANIFEST_PATH))
        self.assertEqual(topology["topology_path"], str(TOPOLOGY_OUTPUT_PATH))
        authorization = manifest["execution_authorization"]
        self.assertFalse(authorization["approved"])
        self.assertFalse(authorization["network_run_allowed"])
        self.assertFalse(authorization["request_plan_output_allowed"])
        self.assertIsNone(authorization["execution_approval_receipt"])
        self.assertTrue(
            authorization["separate_exact_code_bound_execution_approval_required"]
        )

    def test_runtime_manifest_rejects_resealed_permission_expansion(self) -> None:
        manifest = build_runtime_manifest(
            generated_at_utc="2026-08-15T18:00:00Z",
        )
        manifest["execution_authorization"]["network_run_allowed"] = True
        manifest["manifest_hash"] = canonical_hash_without(manifest, "manifest_hash")

        with self.assertRaisesRegex(
            RequestPlanDiscoveryV3Error,
            "runtime manifest",
        ):
            validate_runtime_manifest(manifest)

    def test_runtime_manifest_writer_is_immutable(self) -> None:
        manifest = build_runtime_manifest(
            generated_at_utc="2026-08-15T18:00:00Z",
        )
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "runtime.json"
            write_runtime_manifest(target, manifest)
            with self.assertRaisesRegex(
                RequestPlanDiscoveryV3Error,
                "already exists",
            ):
                write_runtime_manifest(target, manifest)

    def test_offline_refreeze_readiness_resolves_without_execution_artifacts(self) -> None:
        gate_path = REPO_ROOT / "docs/agent-log/active-run-gate.json"
        writer_path = REPO_ROOT / "docs/agent-log/active-market-data-writer-claim.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        self.assertEqual(gate["status"], "READY_FOR_POSTPROCESS")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime_path = root / "runtime.json"
            with mock.patch.object(runtime_v3, "RUNTIME_MANIFEST_PATH", runtime_path):
                manifest = build_runtime_manifest(
                    generated_at_utc="2026-08-15T18:00:00Z",
                )
                write_runtime_manifest(runtime_path, manifest)
                launcher_sha = _sha256_file(VISIBLE_LAUNCHER_PATH)
                report = {
                    "permissions": {
                        field: False for field in readiness.CURRENT_PERMISSION_FIELDS
                    },
                    "slow_liquidity": {
                        "run_id": gate["run_id"],
                        "gate": {
                            "path": str(gate_path),
                            "file_sha256": _sha256_file(gate_path),
                            "size_bytes": gate_path.stat().st_size,
                        },
                    },
                    "official_identity_request_plan_discovery": {
                        "status": RUNTIME_MANIFEST_STATUS,
                        "run_id": RUN_ID,
                        "runtime_manifest": {
                            "path": str(runtime_path),
                            "file_sha256": _sha256_file(runtime_path),
                            "size_bytes": runtime_path.stat().st_size,
                            "manifest_hash": manifest["manifest_hash"],
                        },
                        "visible_launcher": {
                            "path": str(VISIBLE_LAUNCHER_PATH),
                            "file_sha256": launcher_sha,
                            "size_bytes": VISIBLE_LAUNCHER_PATH.stat().st_size,
                        },
                        "lineage": manifest["lineage"],
                        "limits": manifest["limits"],
                        "output_path": str(OUTPUT_PATH),
                        "launch_record_path": str(runtime_v3.LAUNCH_RECORD_PATH),
                        "execution_authorized": False,
                        "network_authorized": False,
                        "official_source_content_read_authorized": False,
                        "request_plan_output_authorized": False,
                        "global_writer_claim_authorized": False,
                        "visible_launcher_execution_authorized": False,
                        "identity_output_authorized": False,
                        "collector_or_evaluator_authorized": False,
                        "evaluator_or_oos_authorized": False,
                        "returns_or_pnl_authorized": False,
                        "grid_or_retune_authorized": False,
                        "execution_probe_authorized": False,
                        "paper_or_live_authorized": False,
                        "private_api_or_real_capital_authorized": False,
                        "leverage_or_margin_authorized": False,
                        "future_execution_single_use_required": True,
                        "stopped_incomplete_retry_authorized": False,
                        "execution_manifest_present": False,
                        "execution_approval_receipt_present": False,
                        "launch_record_present": False,
                        "writer_claim_present": False,
                        "output_present": False,
                    },
                    "approval_checkpoints": [
                        {"id": "pit_extension_schedule_activation"},
                        {
                            "id": (
                                "slow_liquidity_identity_request_plan_discovery_"
                                "v3_execution"
                            ),
                            "status": (
                                "AWAIT_EXACT_CODE_BOUND_NETWORK_EXECUTION_APPROVAL"
                            ),
                            "runtime_manifest_file_sha256": _sha256_file(runtime_path),
                            "runtime_manifest_hash": manifest["manifest_hash"],
                            "visible_launcher_file_sha256": launcher_sha,
                        },
                        {"id": "dense_three_hour_segmented_refreeze_phase_1"},
                    ],
                    "next_safe_action": (
                        "await_exact_slow_liquidity_identity_request_plan_"
                        "discovery_v3_execution_approval"
                    ),
                    "readiness_hash": "b" * 64,
                    "generated_at_utc": "2026-08-15T18:00:00Z",
                    "status": readiness.REQUEST_PLAN_V3_REFREEZE_READINESS_STATUS,
                }

                resolved = readiness._resolve_request_plan_v3_readiness(
                    report,
                    execution_expected=False,
                    pointer_file=root / "pointer.json",
                    pointer_sha="a" * 64,
                    readiness_path=root / "readiness.json",
                    report_sha="c" * 64,
                    gate_file=gate_path,
                    writer_claim_file=writer_path,
                )

        self.assertEqual(resolved["status"], "READY")
        self.assertFalse(resolved["execution_authorized"])
        self.assertEqual(
            resolved["official_identity_request_plan_discovery"]["run_id"],
            RUN_ID,
        )

    def test_readiness_loader_works_when_guard_runs_as_a_direct_script(self) -> None:
        src = REPO_ROOT / "trading_mvp/src"
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(src)!r}); "
            "import one_week_edge_sprint_readiness as readiness; "
            "runtime = readiness._load_request_plan_v3_runtime_validator(); "
            "print(runtime.RUN_ID)"
        )
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=temp,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), RUN_ID)

    def test_visible_launcher_implements_only_fail_closed_offline_boundary(self) -> None:
        text = VISIBLE_LAUNCHER_PATH.read_text(encoding="utf-8")

        for token in (
            "[switch]$PreflightOnly",
            "[switch]$Status",
            "[switch]$Stop",
            "-WindowStyle Normal",
            "BLOCKED_AWAIT_EXACT_REQUEST_PLAN_DISCOVERY_V3_EXECUTION_APPROVAL",
            "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V3",
            "STOPPED_INCOMPLETE",
        ):
            self.assertIn(token, text)
        self.assertIn("execution_manifest_read = $false", text)
        self.assertIn("request_plan_output_created = $false", text)


if __name__ == "__main__":
    unittest.main()
