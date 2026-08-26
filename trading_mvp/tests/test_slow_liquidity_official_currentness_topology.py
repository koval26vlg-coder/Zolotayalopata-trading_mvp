from __future__ import annotations

import copy
import hashlib
import json
import socket
import tempfile
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from time import monotonic
from unittest import mock

from trading_mvp.src.slow_liquidity_official_currentness_topology import (
    ALLOWED_RECORD_FIELDS,
    BLOCKED_EXIT_CODE,
    EXECUTION_APPROVED_STATUS,
    EXECUTION_MANIFEST_SCHEMA,
    EXECUTION_RECEIPT_SCHEMA,
    HARD_OUTPUT_CAP_BYTES,
    MAX_DISCOVERED_URLS,
    MAX_RESPONSE_BYTES,
    MAX_RUNTIME_SEC,
    MAX_TOTAL_HTTP_REQUESTS,
    PARENT_PLAN_FILE_SHA256,
    PARENT_PLAN_HASH,
    PARENT_RUNTIME_FILE_SHA256,
    PARENT_RUNTIME_HASH,
    PROPOSAL_FILE_SHA256,
    PROPOSAL_HASH,
    RUN_ID,
    RUNTIME_MANIFEST_SCHEMA,
    RUNTIME_MANIFEST_STATUS,
    SEED_URLS,
    FetchedResponse,
    TopologyDiscoveryError,
    analyze_topology_responses,
    build_runtime_manifest,
    canonical_hash_without,
    fetch_official_topology_response,
    preflight_only,
    validate_execution_manifest,
    validate_runtime_manifest,
    write_runtime_manifest,
    write_sanitized_topology_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_PATH = (
    ROOT / "docs/plans/drafts/slow-liquidity-identity-currentness-refreeze-"
    "proposal-20260813-v7.json"
)
RUNTIME_MODULE_PATH = (
    ROOT / "trading_mvp/src/slow_liquidity_official_currentness_topology.py"
)
TESTS_PATH = Path(__file__).resolve()
CHECKED_RUNTIME_PATH = (
    ROOT / "docs/plans/slow-liquidity-official-currentness-topology-runtime-"
    "manifest-20260813-v1.json"
)
GENERATED_AT = "2026-08-13T20:30:00Z"


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def response(
    url: str,
    body: str | bytes,
    content_type: str,
    *,
    final_url: str | None = None,
    status: int = 200,
    content_length: str | None = None,
) -> FetchedResponse:
    encoded = body.encode("utf-8") if isinstance(body, str) else body
    headers = {
        "content-type": content_type,
        "content-length": content_length or str(len(encoded)),
    }
    return FetchedResponse(
        requested_url=url,
        final_url=final_url or url,
        status=status,
        headers=headers,
        body=encoded,
    )


def synthetic_responses() -> list[FetchedResponse]:
    return [
        response(
            SEED_URLS[0],
            "User-agent: *\nSitemap: https://www.mexc.com/sitemap.xml\n",
            "text/plain; charset=utf-8",
        ),
        response(
            SEED_URLS[1],
            """<?xml version="1.0"?>
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://www.mexc.com/sitemap-support.xml</loc></sitemap>
              <sitemap><loc>https://evil.example/sitemap.xml</loc></sitemap>
            </sitemapindex>""",
            "application/xml",
        ),
        response(
            SEED_URLS[2],
            """<html><head><link rel="next" href="/support/articles/?page=2"></head>
            <body>
              <a href="/support/articles/?page=2">next</a>
              <a href="/support/articles/123-steth-0xdeadbeef">article</a>
              <a href="https://evil.example/support/articles/?page=2">external</a>
              STETH 0xdeadbeef
            </body></html>""",
            "text/html; charset=UTF-8",
        ),
        response(
            SEED_URLS[3],
            "User-agent: *\nSitemap: https://www.gate.com/sitemap.xml\n",
            "text/plain",
        ),
        response(
            SEED_URLS[4],
            """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://www.gate.com/announcements?page=2</loc></url>
              <url><loc>https://www.gate.com/announcements/article/steth-0xdeadbeef</loc></url>
            </urlset>""",
            "text/xml",
        ),
        response(
            SEED_URLS[5],
            """<html><body>
              <a href="/announcements?page=2">2</a>
              <a href="/announcements/article/steth-0xdeadbeef">article</a>
            </body></html>""",
            "application/xhtml+xml",
        ),
    ]


def checked_runtime() -> dict[str, object]:
    return json.loads(CHECKED_RUNTIME_PATH.read_text(encoding="utf-8"))


def execution_capability(
    runtime: dict[str, object],
    *,
    output_path: Path | None = None,
    runtime_path: Path = CHECKED_RUNTIME_PATH,
):
    bound_output_path = (output_path or (ROOT / "future-topology-output")).resolve()
    runtime_file_sha256 = sha256_bytes(runtime_path.read_bytes())
    runtime_binding = {
        "path": str(runtime_path),
        "file_sha256": runtime_file_sha256,
        "manifest_hash": runtime["manifest_hash"],
    }
    scope = {
        "one_visible_public_read_only_topology_run": True,
        "official_source_content_read": True,
        "sanitized_topology_output": True,
        "global_writer_claim": True,
        "collector_or_evaluator": False,
        "oos_or_returns_or_pnl": False,
        "grid_or_retune": False,
        "execution_probe": False,
        "paper_or_live": False,
        "private_api_or_real_capital": False,
        "leverage_or_margin": False,
    }
    limits = {
        "maximum_total_http_requests": MAX_TOTAL_HTTP_REQUESTS,
        "maximum_attempts_per_url": 1,
        "maximum_response_bytes_per_request": MAX_RESPONSE_BYTES,
        "max_runtime_sec": MAX_RUNTIME_SEC,
        "hard_output_cap_bytes": HARD_OUTPUT_CAP_BYTES,
    }
    approval_text = " ".join(
        [
            RUN_ID,
            runtime_file_sha256,
            str(runtime["manifest_hash"]),
            *SEED_URLS,
            str(MAX_TOTAL_HTTP_REQUESTS),
            str(MAX_RUNTIME_SEC),
            str(HARD_OUTPUT_CAP_BYTES),
            str(bound_output_path),
        ]
    )
    receipt: dict[str, object] = {
        "schema": EXECUTION_RECEIPT_SCHEMA,
        "status": "APPROVED_SINGLE_USE",
        "approved_at_utc": "2026-08-13T21:00:00Z",
        "user_approval_text": approval_text,
        "approval_provenance": {
            "mode": "MANUAL_CODEX_CHECKPOINT_AFTER_DIRECT_USER_APPROVAL",
            "runtime_minting_allowed": False,
            "launcher_minting_allowed": False,
        },
        "runtime_manifest": runtime_binding,
        "run_id": RUN_ID,
        "exact_seed_urls": list(SEED_URLS),
        "authorized_scope": scope,
        "limits": limits,
        "output_path": str(bound_output_path),
        "single_use": True,
        "stopped_incomplete_retry_authorized": False,
        "receipt_hash_method": "sha256_canonical_json_excluding_receipt_hash",
    }
    receipt["receipt_hash"] = canonical_hash_without(receipt, "receipt_hash")
    receipt_file_sha256 = sha256_bytes(json_bytes(receipt))
    execution: dict[str, object] = {
        "schema": EXECUTION_MANIFEST_SCHEMA,
        "status": EXECUTION_APPROVED_STATUS,
        "execution_authorized": True,
        "execution_approval": {
            "status": "APPROVED",
            "path": str(ROOT / "future-topology-approval-receipt.json"),
            "file_sha256": receipt_file_sha256,
            "receipt_hash": receipt["receipt_hash"],
            "user_approval_text": approval_text,
            "approved_at_utc": receipt["approved_at_utc"],
        },
        "runtime_manifest": runtime_binding,
        "run_id": RUN_ID,
        "exact_seed_urls": list(SEED_URLS),
        "authorized_scope": scope,
        "limits": limits,
        "output_path": str(bound_output_path),
        "single_use": True,
        "stopped_incomplete_retry_authorized": False,
        "manifest_hash_method": "sha256_canonical_json_excluding_manifest_hash",
    }
    execution["manifest_hash"] = canonical_hash_without(execution, "manifest_hash")
    return validate_execution_manifest(
        execution,
        runtime_manifest=runtime,
        repo_root=ROOT,
        approval_receipt_snapshot=receipt,
        approval_receipt_file_sha256=receipt_file_sha256,
    )


class _FakeHeaders(dict[str, str]):
    def get(self, key: str, default: str | None = None) -> str | None:
        return super().get(key.lower(), default)


class _FakeHTTPResponse:
    def __init__(self, url: str, body: bytes, *, content_length: str | None = None):
        self.status = 200
        self._url = url
        self._body = body
        self._offset = 0
        self.headers = _FakeHeaders(
            {
                "content-type": "text/plain; charset=utf-8",
                "content-length": content_length or str(len(body)),
            }
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._body):
            return b""
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FakeOpener:
    def __init__(self, response_value: _FakeHTTPResponse):
        self.response_value = response_value
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, timeout: float):
        self.calls.append((request, timeout))
        return self.response_value


class SlowLiquidityOfficialCurrentnessTopologyTests(unittest.TestCase):
    def test_exact_approved_contract_constants(self) -> None:
        self.assertEqual(
            RUN_ID, "slow_liquidity_official_currentness_topology_discovery_20260813_v1"
        )
        self.assertEqual(
            PROPOSAL_FILE_SHA256,
            "a694c51c8d1f3f8d2abe81797a90f5908f45252b938c7420cb58277972d45555",
        )
        self.assertEqual(
            PROPOSAL_HASH,
            "fff9f0453d5cc378344b94ad38113a267bd068a3215d29953fa2db62ef8f9686",
        )
        self.assertEqual(
            PARENT_PLAN_FILE_SHA256,
            "501f42f7f418fcc07522f8df8a59db38db106cd3d2ae86cc598ffb19af34afe4",
        )
        self.assertEqual(
            PARENT_PLAN_HASH,
            "6246471964815d139e6900298a2a78e80e830df40f0c06b39078487c254183cc",
        )
        self.assertEqual(
            PARENT_RUNTIME_FILE_SHA256,
            "0e2dfa6be70c289a877f9660d2ef58adca4c05276d38bfc8d99c4b8e703b250d",
        )
        self.assertEqual(
            PARENT_RUNTIME_HASH,
            "f2cedc562660b25da6d0eac1845deb2e4ef17ba38782867ed49792f13fb392e1",
        )
        self.assertEqual(MAX_TOTAL_HTTP_REQUESTS, 6)
        self.assertEqual(MAX_RUNTIME_SEC, 300)
        self.assertEqual(HARD_OUTPUT_CAP_BYTES, 10_000_000)
        self.assertEqual(
            SEED_URLS,
            (
                "https://www.mexc.com/robots.txt",
                "https://www.mexc.com/sitemap.xml",
                "https://www.mexc.com/support/articles/",
                "https://www.gate.com/robots.txt",
                "https://www.gate.com/sitemap.xml",
                "https://www.gate.com/announcements",
            ),
        )

    def test_synthetic_sources_produce_only_allowlisted_sanitized_topology(
        self,
    ) -> None:
        result = analyze_topology_responses(synthetic_responses())
        self.assertEqual(result["run_id"], RUN_ID)
        self.assertEqual(result["request_count"], 6)
        self.assertEqual(len(result["records"]), 6)
        self.assertFalse(result["identity_evidence_created"])
        self.assertFalse(result["raw_payload_persisted"])
        for record in result["records"]:
            self.assertEqual(set(record), ALLOWED_RECORD_FIELDS)
            source_host = urllib.parse.urlparse(record["source_url"]).hostname
            for candidate in record["same_host_candidate_index_urls"]:
                self.assertEqual(urllib.parse.urlparse(candidate).hostname, source_host)
                self.assertNotIn("/article/", candidate)
                self.assertNotIn("123-steth", candidate)
            for template in record["same_host_candidate_pagination_templates"]:
                self.assertEqual(urllib.parse.urlparse(template).hostname, source_host)
                self.assertIn("{page}", template)
        serialized = json.dumps(result, sort_keys=True).lower()
        self.assertNotIn("0xdeadbeef", serialized)
        self.assertNotIn("123-steth", serialized)
        self.assertNotIn("evil.example", serialized)

    def test_requires_exact_complete_ordered_seed_set(self) -> None:
        fixtures = synthetic_responses()
        cases = {
            "missing": fixtures[:-1],
            "reordered": [fixtures[1], fixtures[0], *fixtures[2:]],
            "duplicate": [fixtures[0], fixtures[0], *fixtures[2:]],
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(TopologyDiscoveryError, "exact seed order"):
                    analyze_topology_responses(value)

    def test_redirect_status_length_and_markup_fail_closed(self) -> None:
        cases: list[tuple[str, FetchedResponse, str]] = [
            (
                "redirect",
                response(
                    SEED_URLS[0],
                    "ok",
                    "text/plain",
                    final_url="https://www.mexc.com/other",
                ),
                "redirect",
            ),
            (
                "status",
                response(SEED_URLS[0], "ok", "text/plain", status=206),
                "HTTP 200",
            ),
            (
                "declared length",
                response(
                    SEED_URLS[0],
                    "ok",
                    "text/plain",
                    content_length=str(MAX_RESPONSE_BYTES + 1),
                ),
                "content length",
            ),
            (
                "actual length",
                response(
                    SEED_URLS[0],
                    b"x" * (MAX_RESPONSE_BYTES + 1),
                    "text/plain",
                ),
                "response cap",
            ),
        ]
        for label, bad, pattern in cases:
            fixtures = synthetic_responses()
            fixtures[0] = bad
            with self.subTest(label=label):
                with self.assertRaisesRegex(TopologyDiscoveryError, pattern):
                    analyze_topology_responses(fixtures)

        fixtures = synthetic_responses()
        fixtures[1] = response(
            SEED_URLS[1],
            "<!DOCTYPE x [<!ENTITY e 'forbidden'>]><x>&e;</x>",
            "application/xml",
        )
        with self.assertRaisesRegex(TopologyDiscoveryError, "DOCTYPE"):
            analyze_topology_responses(fixtures)

    def test_discovered_url_count_and_size_caps_are_not_silently_truncated(
        self,
    ) -> None:
        too_many = "".join(
            f"<sitemap><loc>https://www.mexc.com/sitemap-{index}.xml</loc></sitemap>"
            for index in range(MAX_DISCOVERED_URLS + 1)
        )
        fixtures = synthetic_responses()
        fixtures[1] = response(
            SEED_URLS[1],
            f"<sitemapindex>{too_many}</sitemapindex>",
            "application/xml",
        )
        with self.assertRaisesRegex(TopologyDiscoveryError, "discovered URL cap"):
            analyze_topology_responses(fixtures)

        fixtures = synthetic_responses()
        oversized_url = "https://www.mexc.com/sitemap-" + ("x" * 2050) + ".xml"
        fixtures[1] = response(
            SEED_URLS[1],
            f"<sitemapindex><sitemap><loc>{oversized_url}</loc></sitemap></sitemapindex>",
            "application/xml",
        )
        with self.assertRaisesRegex(TopologyDiscoveryError, "URL byte cap"):
            analyze_topology_responses(fixtures)

    def test_runtime_manifest_binds_code_and_keeps_execution_closed(self) -> None:
        manifest = build_runtime_manifest(
            repo_root=ROOT,
            proposal_path=PROPOSAL_PATH,
            runtime_module_path=RUNTIME_MODULE_PATH,
            synthetic_tests_path=TESTS_PATH,
            generated_at_utc=GENERATED_AT,
        )
        self.assertEqual(manifest["schema"], RUNTIME_MANIFEST_SCHEMA)
        self.assertEqual(manifest["status"], RUNTIME_MANIFEST_STATUS)
        self.assertEqual(manifest["proposal"]["file_sha256"], PROPOSAL_FILE_SHA256)
        self.assertEqual(manifest["proposal"]["proposal_hash"], PROPOSAL_HASH)
        self.assertTrue(manifest["runtime"]["network_adapter_implemented"])
        self.assertTrue(manifest["runtime"]["execution_manifest_validator_implemented"])
        self.assertTrue(manifest["runtime"]["sanitized_output_writer_implemented"])
        self.assertFalse(manifest["runtime"]["visible_launcher_implemented"])
        self.assertFalse(manifest["runtime"]["direct_cli_execution_enabled"])
        self.assertFalse(manifest["execution_authorization"]["approved"])
        self.assertFalse(manifest["execution_authorization"]["network_run_allowed"])
        self.assertFalse(manifest["execution_authorization"]["topology_output_allowed"])
        self.assertFalse(manifest["offline_authorization"]["approval_receipt_created"])
        self.assertEqual(
            manifest["manifest_hash"],
            canonical_hash_without(manifest, "manifest_hash"),
        )
        validate_runtime_manifest(manifest, repo_root=ROOT)

    def test_runtime_manifest_tampering_fails_closed(self) -> None:
        base = build_runtime_manifest(
            repo_root=ROOT,
            proposal_path=PROPOSAL_PATH,
            runtime_module_path=RUNTIME_MODULE_PATH,
            synthetic_tests_path=TESTS_PATH,
            generated_at_utc=GENERATED_AT,
        )
        cases = [
            ("proposal", "file_sha256", "0" * 64),
            ("parent_discovery", "plan_hash", "1" * 64),
            ("source_contract", "max_runtime_sec", 301),
            ("execution_authorization", "network_run_allowed", True),
            ("runtime", "visible_launcher_implemented", True),
        ]
        for section, key, value in cases:
            manifest = copy.deepcopy(base)
            manifest[section][key] = value
            manifest["manifest_hash"] = canonical_hash_without(
                manifest, "manifest_hash"
            )
            with self.subTest(section=section, key=key):
                with self.assertRaises(TopologyDiscoveryError):
                    validate_runtime_manifest(manifest, repo_root=ROOT)

    def test_runtime_manifest_write_is_immutable(self) -> None:
        manifest = build_runtime_manifest(
            repo_root=ROOT,
            proposal_path=PROPOSAL_PATH,
            runtime_module_path=RUNTIME_MODULE_PATH,
            synthetic_tests_path=TESTS_PATH,
            generated_at_utc=GENERATED_AT,
        )
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "runtime.json"
            write_runtime_manifest(output, manifest)
            first = output.read_bytes()
            write_runtime_manifest(output, manifest)
            self.assertEqual(output.read_bytes(), first)
            changed = copy.deepcopy(manifest)
            changed["generated_at_utc"] = "2026-08-13T20:31:00Z"
            changed["manifest_hash"] = canonical_hash_without(changed, "manifest_hash")
            with self.assertRaisesRegex(TopologyDiscoveryError, "immutable"):
                write_runtime_manifest(output, changed)

    def test_checked_in_runtime_manifest_matches_builder(self) -> None:
        observed = checked_runtime()
        expected = build_runtime_manifest(
            repo_root=ROOT,
            proposal_path=PROPOSAL_PATH,
            runtime_module_path=RUNTIME_MODULE_PATH,
            synthetic_tests_path=TESTS_PATH,
            generated_at_utc=observed["generated_at_utc"],
        )
        self.assertEqual(observed, expected)
        validate_runtime_manifest(observed, repo_root=ROOT)

    def test_preflight_reads_only_proposal_and_runtime_and_creates_nothing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            execution_path = Path(temp) / "must-not-be-read.json"
            output_path = Path(temp) / "must-not-exist"
            with (
                mock.patch.object(
                    urllib.request.OpenerDirector,
                    "open",
                    side_effect=AssertionError("network accessed"),
                ),
                mock.patch.object(
                    socket,
                    "getaddrinfo",
                    side_effect=AssertionError("DNS accessed"),
                ),
            ):
                result = preflight_only(
                    repo_root=ROOT,
                    proposal_path=PROPOSAL_PATH,
                    runtime_manifest_path=CHECKED_RUNTIME_PATH,
                    execution_manifest_path=execution_path,
                    output_path=output_path,
                )
            self.assertEqual(
                result["status"],
                "BLOCKED_AWAIT_EXACT_TOPOLOGY_EXECUTION_APPROVAL",
            )
            self.assertFalse(result["network_accessed"])
            self.assertFalse(result["official_source_content_read"])
            self.assertFalse(result["execution_manifest_read"])
            self.assertFalse(result["output_created"])
            self.assertFalse(execution_path.exists())
            self.assertFalse(output_path.exists())

    def test_cli_exposes_preflight_but_no_execute_command(self) -> None:
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as temp:
            execution_path = Path(temp) / "missing-execution.json"
            output_path = Path(temp) / "must-not-exist"
            command = [
                sys.executable,
                "-m",
                "trading_mvp.src.slow_liquidity_official_currentness_topology",
                "preflight",
                "--repo-root",
                str(ROOT),
                "--proposal",
                str(PROPOSAL_PATH),
                "--runtime-manifest",
                str(CHECKED_RUNTIME_PATH),
                "--execution-manifest",
                str(execution_path),
                "--output",
                str(output_path),
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, BLOCKED_EXIT_CODE)
            payload = json.loads(completed.stdout)
            self.assertEqual(
                payload["status"],
                "BLOCKED_AWAIT_EXACT_TOPOLOGY_EXECUTION_APPROVAL",
            )
            self.assertFalse(output_path.exists())

            execute = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "trading_mvp.src.slow_liquidity_official_currentness_topology",
                    "execute",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(execute.returncode, 0)
            self.assertIn("invalid choice", execute.stderr)

    def test_network_adapter_blocks_before_open_without_external_capability(
        self,
    ) -> None:
        fake = _FakeOpener(_FakeHTTPResponse(SEED_URLS[0], b"User-agent: *\n"))
        with self.assertRaisesRegex(TopologyDiscoveryError, "execution capability"):
            fetch_official_topology_response(
                SEED_URLS[0],
                capability=None,
                deadline_monotonic=monotonic() + 30,
                opener=fake,
            )
        self.assertEqual(fake.calls, [])

    def test_network_adapter_is_bounded_after_synthetic_external_approval(self) -> None:
        runtime = checked_runtime()
        capability = execution_capability(runtime)
        body = b"User-agent: *\nSitemap: https://www.mexc.com/sitemap.xml\n"
        fake = _FakeOpener(_FakeHTTPResponse(SEED_URLS[0], body))
        fetched = fetch_official_topology_response(
            SEED_URLS[0],
            capability=capability,
            deadline_monotonic=monotonic() + 30,
            opener=fake,
        )
        self.assertEqual(fetched.body, body)
        self.assertEqual(len(fake.calls), 1)
        request, timeout = fake.calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 30)

        oversized = _FakeOpener(
            _FakeHTTPResponse(
                SEED_URLS[0],
                b"ok",
                content_length=str(MAX_RESPONSE_BYTES + 1),
            )
        )
        oversized_capability = execution_capability(runtime)
        with self.assertRaisesRegex(TopologyDiscoveryError, "content length"):
            fetch_official_topology_response(
                SEED_URLS[0],
                capability=oversized_capability,
                deadline_monotonic=monotonic() + 30,
                opener=oversized,
            )
        with self.assertRaisesRegex(TopologyDiscoveryError, "attempt cap"):
            fetch_official_topology_response(
                SEED_URLS[0],
                capability=oversized_capability,
                deadline_monotonic=monotonic() + 30,
                opener=oversized,
            )
        self.assertEqual(len(oversized.calls), 1)

    def test_execution_capability_allows_each_seed_url_only_once(self) -> None:
        import trading_mvp.src.slow_liquidity_official_currentness_topology as topology

        runtime = build_runtime_manifest(
            repo_root=ROOT,
            proposal_path=PROPOSAL_PATH,
            runtime_module_path=RUNTIME_MODULE_PATH,
            synthetic_tests_path=TESTS_PATH,
            generated_at_utc=GENERATED_AT,
        )
        temp_parent = ROOT / ".codex"
        temp_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_parent) as temp:
            runtime_path = Path(temp) / "runtime.json"
            runtime_path.write_bytes(json_bytes(runtime))
            with mock.patch.object(topology, "RUNTIME_MANIFEST_PATH", runtime_path):
                capability = execution_capability(
                    runtime,
                    runtime_path=runtime_path,
                )
                body = b"User-agent: *\n"
                fake = _FakeOpener(_FakeHTTPResponse(SEED_URLS[0], body))
                fetch_official_topology_response(
                    SEED_URLS[0],
                    capability=capability,
                    deadline_monotonic=monotonic() + 30,
                    opener=fake,
                )
                with self.assertRaisesRegex(TopologyDiscoveryError, "attempt cap"):
                    fetch_official_topology_response(
                        SEED_URLS[0],
                        capability=capability,
                        deadline_monotonic=monotonic() + 30,
                        opener=fake,
                    )
                self.assertEqual(len(fake.calls), 1)

    def test_synthetic_output_writer_is_capability_gated_and_sanitized(self) -> None:
        runtime = checked_runtime()
        result = analyze_topology_responses(synthetic_responses())
        with tempfile.TemporaryDirectory() as temp:
            blocked_path = Path(temp) / "blocked"
            with self.assertRaisesRegex(TopologyDiscoveryError, "execution capability"):
                write_sanitized_topology_bundle(
                    blocked_path,
                    result,
                    capability=None,
                )
            self.assertFalse(blocked_path.exists())

            output_path = Path(temp) / "allowed"
            capability = execution_capability(runtime, output_path=output_path)
            with self.assertRaisesRegex(TopologyDiscoveryError, "output path"):
                write_sanitized_topology_bundle(
                    Path(temp) / "wrong",
                    result,
                    capability=capability,
                )
            manifest = write_sanitized_topology_bundle(
                output_path,
                result,
                capability=capability,
            )
            self.assertEqual(
                sorted(path.name for path in output_path.iterdir()),
                ["manifest.json", "topology.json"],
            )
            self.assertEqual(manifest["run_id"], RUN_ID)
            persisted = (output_path / "topology.json").read_text(encoding="utf-8")
            self.assertNotIn("0xdeadbeef", persisted.lower())
            self.assertNotIn("123-steth", persisted.lower())
            self.assertFalse(json.loads(persisted)["raw_payload_persisted"])

    def test_execution_manifest_tampering_never_issues_capability(self) -> None:
        runtime = checked_runtime()
        capability = execution_capability(runtime)
        self.assertEqual(capability.run_id, RUN_ID)

        manifest = copy.deepcopy(runtime)
        manifest["execution_authorization"]["approved"] = True
        manifest["manifest_hash"] = canonical_hash_without(manifest, "manifest_hash")
        with self.assertRaises(TopologyDiscoveryError):
            validate_runtime_manifest(manifest, repo_root=ROOT)


if __name__ == "__main__":
    unittest.main()
