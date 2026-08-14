from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from time import monotonic
from unittest import mock

import pytest

from trading_mvp.src import slow_liquidity_official_currentness_topology_v2 as topology


ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_PATH = (
    ROOT / "docs/plans/drafts/slow-liquidity-official-currentness-topology-v2-"
    "refreeze-proposal-20260814-v2.json"
)
RUNTIME_PATH = (
    ROOT / "docs/plans/slow-liquidity-official-currentness-topology-runtime-"
    "manifest-20260814-v2.json"
)
EXECUTION_PATH = (
    ROOT / "docs/plans/slow-liquidity-official-currentness-topology-execution-"
    "manifest-20260814-v2.json"
)
RECEIPT_PATH = (
    ROOT / "docs/agent-log/approvals/2026-08-14-slow-liquidity-official-"
    "currentness-topology-execution-v2-approval.json"
)
LAUNCHER_PATH = (
    ROOT / "tools/start_exact_approved_slow_liquidity_official_currentness_"
    "topology_v2_visible.ps1"
)
RUNTIME_MODULE_PATH = (
    ROOT / "trading_mvp/src/slow_liquidity_official_currentness_topology_v2.py"
)
V1_RUNTIME_PATH = (
    ROOT / "trading_mvp/src/slow_liquidity_official_currentness_topology.py"
)
OUTPUT_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-official-"
    r"currentness-topology\slow_liquidity_official_currentness_topology_"
    r"discovery_20260814_v2"
)
V1_RUNTIME_SHA256 = "93897fb9b19b3c0987a9d3728864d305d74cf268274e7f0f0bdf81120c9569c0"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _response(
    url: str,
    body: str,
    content_type: str,
    *,
    final_url: str | None = None,
) -> topology.FetchedResponse:
    encoded = body.encode("utf-8")
    return topology.FetchedResponse(
        requested_url=url,
        final_url=final_url or url,
        status=200,
        headers={"content-type": content_type, "content-length": str(len(encoded))},
        body=encoded,
    )


def _synthetic_responses() -> list[topology.FetchedResponse]:
    return [
        _response(
            topology.SEED_URLS[0],
            "User-agent: *\nSitemap: https://www.mexc.com/sitemap.xml\n",
            "text/plain",
        ),
        _response(
            topology.SEED_URLS[1],
            """<?xml version="1.0"?>
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://www.mexc.com/sitemap-support.xml</loc></sitemap>
              <sitemap><loc>https://evil.example/raw.xml</loc></sitemap>
            </sitemapindex>""",
            "application/xml",
        ),
        _response(
            topology.SEED_URLS[2],
            """<html><head><link rel="next" href="/support/articles/?page=2"></head>
            <body><a href="/support/articles/?page=2">next</a>
            <a href="/support/articles/STETH-0xdeadbeef">identity</a></body></html>""",
            "text/html",
        ),
        _response(
            topology.SEED_URLS[3],
            "User-agent: *\nSitemap: https://www.gate.com/sitemap.xml\n",
            "text/plain",
        ),
        _response(
            topology.SEED_URLS[4],
            """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://www.gate.com/announcements?page=2</loc></url>
            </urlset>""",
            "text/xml",
        ),
        _response(
            topology.SEED_URLS[5],
            '<html><body><a href="/announcements?page=2">2</a></body></html>',
            "text/html",
        ),
    ]


class _FakeHttpResponse:
    def __init__(self, url: str, body: bytes) -> None:
        self.status = 200
        self.headers = {
            "content-type": "text/plain",
            "content-length": str(len(body)),
        }
        self._url = url
        self._body = body
        self._offset = 0

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._body):
            return b""
        if size < 0:
            size = len(self._body) - self._offset
        value = self._body[self._offset : self._offset + size]
        self._offset += len(value)
        return value


class _FakeOpener:
    def __init__(self, response: _FakeHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(
        self, request: urllib.request.Request, timeout: float
    ) -> _FakeHttpResponse:
        self.calls.append((request, timeout))
        return self.response


def _approved_in_memory_capability() -> topology.TopologyExecutionCapability:
    runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    runtime_binding = {
        "path": str(RUNTIME_PATH),
        "file_sha256": _sha256(RUNTIME_PATH),
        "manifest_hash": runtime["manifest_hash"],
    }
    launch_window = {
        "not_before_local": "2026-08-20T10:00:00+03:00",
        "latest_launch_local": "2026-08-20T10:05:00+03:00",
        "hard_deadline_local": "2026-08-20T10:10:00+03:00",
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
        "maximum_total_http_requests": 6,
        "maximum_attempts_per_url": 1,
        "maximum_response_bytes_per_request": 1_000_000,
        "max_runtime_sec": 300,
        "hard_output_cap_bytes": 10_000_000,
    }
    approval_text = " ".join(
        [
            topology.RUN_ID,
            runtime_binding["file_sha256"],
            runtime_binding["manifest_hash"],
            *topology.SEED_URLS,
            "6",
            "300",
            "10000000",
            *launch_window.values(),
            str(OUTPUT_PATH),
        ]
    )
    receipt: dict[str, object] = {
        "schema": topology.EXECUTION_RECEIPT_SCHEMA,
        "status": "APPROVED_SINGLE_USE",
        "approved_at_utc": "2026-08-19T20:00:00Z",
        "user_approval_text": approval_text,
        "approval_provenance": {
            "mode": "MANUAL_CODEX_CHECKPOINT_AFTER_DIRECT_USER_APPROVAL",
            "runtime_minting_allowed": False,
            "launcher_minting_allowed": False,
        },
        "runtime_manifest": runtime_binding,
        "run_id": topology.RUN_ID,
        "exact_seed_urls": list(topology.SEED_URLS),
        "authorized_scope": scope,
        "limits": limits,
        "launch_window": launch_window,
        "output_path": str(OUTPUT_PATH),
        "single_use": True,
        "stopped_incomplete_retry_authorized": False,
        "receipt_hash_method": "sha256_canonical_json_excluding_receipt_hash",
    }
    receipt["receipt_hash"] = topology.canonical_hash_without(receipt, "receipt_hash")
    receipt_sha = hashlib.sha256(_canonical_bytes(receipt)).hexdigest()
    execution: dict[str, object] = {
        "schema": topology.EXECUTION_MANIFEST_SCHEMA,
        "status": topology.EXECUTION_APPROVED_STATUS,
        "execution_authorized": True,
        "execution_approval": {
            "status": "APPROVED",
            "path": str(RECEIPT_PATH),
            "file_sha256": receipt_sha,
            "receipt_hash": receipt["receipt_hash"],
            "user_approval_text": approval_text,
            "approved_at_utc": receipt["approved_at_utc"],
        },
        "runtime_manifest": runtime_binding,
        "run_id": topology.RUN_ID,
        "exact_seed_urls": list(topology.SEED_URLS),
        "authorized_scope": scope,
        "limits": limits,
        "launch_window": launch_window,
        "output_path": str(OUTPUT_PATH),
        "single_use": True,
        "stopped_incomplete_retry_authorized": False,
        "manifest_hash_method": "sha256_canonical_json_excluding_manifest_hash",
    }
    execution["manifest_hash"] = topology.canonical_hash_without(
        execution, "manifest_hash"
    )
    return topology.validate_execution_manifest(
        execution,
        runtime_manifest=runtime,
        repo_root=ROOT,
        approval_receipt_snapshot=receipt,
        approval_receipt_file_sha256=receipt_sha,
    )


def test_exact_v2_bindings_and_v1_is_immutable() -> None:
    assert topology.RUN_ID.endswith("20260814_v2")
    assert topology.PROPOSAL_FILE_SHA256 == _sha256(PROPOSAL_PATH)
    proposal = json.loads(PROPOSAL_PATH.read_text(encoding="utf-8"))
    assert proposal["proposal_hash"] == topology.PROPOSAL_HASH
    assert (
        topology.canonical_hash_without(proposal, "proposal_hash")
        == topology.PROPOSAL_HASH
    )
    assert topology.SEED_URLS == (
        "https://www.mexc.com/robots.txt",
        "https://www.mexc.com/sitemap.xml",
        "https://www.mexc.com/support/articles/",
        "https://www.gate.com/robots.txt",
        "https://www.gate.com/sitemap.xml",
        "https://www.gate.com/announcements",
    )
    assert topology.MAX_TOTAL_HTTP_REQUESTS == 6
    assert topology.MAX_ATTEMPTS_PER_URL == 1
    assert topology.MAX_RESPONSE_BYTES == 1_000_000
    assert topology.MAX_RUNTIME_SEC == 300
    assert topology.HARD_OUTPUT_CAP_BYTES == 10_000_000
    assert _sha256(V1_RUNTIME_PATH) == V1_RUNTIME_SHA256


def test_synthetic_parser_persists_only_sanitized_topology() -> None:
    result = topology.analyze_topology_responses(_synthetic_responses())
    assert result["run_id"] == topology.RUN_ID
    assert result["request_count"] == 6
    assert result["identity_evidence_created"] is False
    assert result["raw_payload_persisted"] is False
    encoded = json.dumps(result, sort_keys=True).lower()
    assert "0xdeadbeef" not in encoded
    assert "evil.example" not in encoded
    for record in result["records"]:
        source_host = urllib.parse.urlparse(record["source_url"]).hostname
        assert set(record) == topology.ALLOWED_RECORD_FIELDS
        for candidate in record["same_host_candidate_index_urls"]:
            assert urllib.parse.urlparse(candidate).hostname == source_host


@pytest.mark.parametrize(
    ("error", "entered", "reason_code", "state"),
    [
        (
            topology.TopologyDiscoveryError("HTTP redirect is forbidden: secret"),
            True,
            "HTTP_REDIRECT_FORBIDDEN",
            "ATTEMPTED_OR_ENTERED_NETWORK_STAGE",
        ),
        (
            RuntimeError("private traceback payload"),
            False,
            "TOPOLOGY_INTERNAL_RUNTIME_FAILURE",
            "NOT_ENTERED_NETWORK_STAGE",
        ),
    ],
)
def test_failure_envelope_is_fixed_and_sanitized(
    error: BaseException,
    entered: bool,
    reason_code: str,
    state: str,
) -> None:
    envelope = topology.sanitized_failure_envelope(
        error,
        network_stage_entered=entered,
    )
    assert envelope["reason_code"] == reason_code
    assert envelope["network_access_state"] == state
    assert envelope["retry_authorized"] is False
    encoded = json.dumps(envelope)
    assert str(error) not in encoded
    assert "traceback" not in encoded.lower()


def test_manifest_is_code_test_and_launcher_bound() -> None:
    observed = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    expected = topology.build_runtime_manifest(
        repo_root=ROOT,
        proposal_path=PROPOSAL_PATH,
        runtime_module_path=RUNTIME_MODULE_PATH,
        synthetic_tests_path=Path(__file__).resolve(),
        visible_launcher_path=LAUNCHER_PATH,
        generated_at_utc=observed["generated_at_utc"],
    )
    assert observed == expected
    assert observed["runtime"]["visible_launcher_sha256"] == _sha256(LAUNCHER_PATH)
    assert observed["execution_authorization"]["approved"] is False
    assert observed["execution_authorization"]["execution_manifest"] is None
    topology.validate_runtime_manifest(observed, repo_root=ROOT)


def test_preflight_reads_no_execution_manifest_and_has_no_side_effects() -> None:
    assert not EXECUTION_PATH.exists()
    assert not RECEIPT_PATH.exists()
    assert not OUTPUT_PATH.exists()
    writer_claim = ROOT / "docs/agent-log/active-market-data-writer-claim.json"
    launch_record = ROOT / f"docs/agent-log/run-gates/{topology.RUN_ID}.launch.json"
    before = {
        "writer": writer_claim.exists(),
        "launch": launch_record.exists(),
        "output": OUTPUT_PATH.exists(),
    }
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
        result = topology.preflight_only(
            repo_root=ROOT,
            proposal_path=PROPOSAL_PATH,
            runtime_manifest_path=RUNTIME_PATH,
            execution_manifest_path=EXECUTION_PATH,
            output_path=OUTPUT_PATH,
        )
    assert result["status"] == "BLOCKED_AWAIT_EXACT_V2_TOPOLOGY_EXECUTION_APPROVAL"
    assert result["execution_manifest_read"] is False
    assert result["network_accessed"] is False
    assert result["output_created"] is False
    assert result["global_writer_claim_created"] is False
    assert result["visible_launcher_executed"] is False
    assert before == {
        "writer": writer_claim.exists(),
        "launch": launch_record.exists(),
        "output": OUTPUT_PATH.exists(),
    }


def test_network_adapter_is_single_attempt_no_proxy_no_redirect_no_retry() -> None:
    capability = _approved_in_memory_capability()
    body = b"User-agent: *\n"
    fake = _FakeOpener(_FakeHttpResponse(topology.SEED_URLS[0], body))
    with mock.patch.object(
        urllib.request, "build_opener", return_value=fake
    ) as builder:
        fetched = topology.fetch_official_topology_response(
            topology.SEED_URLS[0],
            capability=capability,
            deadline_monotonic=monotonic() + 30,
        )
    assert fetched.body == body
    assert len(fake.calls) == 1
    handlers = builder.call_args.args
    proxy_handlers = [
        item for item in handlers if isinstance(item, urllib.request.ProxyHandler)
    ]
    redirect_handlers = [
        item for item in handlers if item.__class__.__name__ == "_NoRedirectHandler"
    ]
    assert len(proxy_handlers) == 1 and proxy_handlers[0].proxies == {}
    assert len(redirect_handlers) == 1
    with pytest.raises(topology.TopologyDiscoveryError, match="attempt cap"):
        topology.fetch_official_topology_response(
            topology.SEED_URLS[0],
            capability=capability,
            deadline_monotonic=monotonic() + 30,
            opener=fake,
        )
    assert len(fake.calls) == 1


def test_launcher_is_fail_closed_and_prepares_output_only_after_writer_claim() -> None:
    launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
    assert topology.RUN_ID in launcher
    assert "slow_liquidity_official_currentness_topology_v2" in launcher
    assert "Invoke-OfflinePreflight" in launcher
    assert "BLOCKED_AWAIT_EXACT_V2_TOPOLOGY_EXECUTION_APPROVAL" in launcher
    assert "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY_V2" in launcher
    assert "VISIBLE_LAUNCHER_INTERNAL_FAILURE" in launcher
    assert "52abef8c08b0" not in launcher
    assert "a5a8413ca46e" not in launcher
    claim_index = launcher.index("$claim = Invoke-WriterClaim")
    parent_index = launcher.index("$outputParent = Split-Path -Parent $OutputPath")
    start_index = launcher.index("$terminal = Start-Process")
    missing_manifest_index = launcher.index("exact_v2_execution_manifest_missing")
    assert claim_index < parent_index
    assert missing_manifest_index < start_index


def test_launcher_preflight_and_direct_call_create_nothing() -> None:
    assert not EXECUTION_PATH.exists()
    assert not RECEIPT_PATH.exists()
    assert not OUTPUT_PATH.exists()
    launch_record = ROOT / f"docs/agent-log/run-gates/{topology.RUN_ID}.launch.json"
    capability = ROOT / f"docs/agent-log/run-gates/{topology.RUN_ID}.capability.json"
    writer_claim = ROOT / "docs/agent-log/active-market-data-writer-claim.json"
    command = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LAUNCHER_PATH),
    ]
    preflight = subprocess.run(
        [*command, "-PreflightOnly"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert preflight.returncode == topology.BLOCKED_EXIT_CODE
    payload = json.loads(preflight.stdout)
    assert payload["status"] == "BLOCKED_AWAIT_EXACT_V2_TOPOLOGY_EXECUTION_APPROVAL"
    assert payload["execution_manifest_read"] is False
    direct = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert direct.returncode != 0
    assert not launch_record.exists()
    assert not capability.exists()
    assert not writer_claim.exists()
    assert not OUTPUT_PATH.exists()
    assert not EXECUTION_PATH.exists()
    assert not RECEIPT_PATH.exists()


def test_runtime_cli_has_preflight_but_no_execute_command() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_mvp.src.slow_liquidity_official_currentness_topology_v2",
            "execute",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr
