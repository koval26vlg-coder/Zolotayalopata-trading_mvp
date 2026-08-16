from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from trading_mvp.src import slow_liquidity_identity_request_plan_discovery_v4 as runtime
from trading_mvp.src.slow_liquidity_identity_request_plan_discovery_v4 import (
    BASES,
    FetchedResponse,
    MAX_RESPONSE_BYTES,
    MAX_TOTAL_RESPONSE_BYTES,
    ResponseCapExceeded,
    TotalResponseCapExceeded,
    fetch_public_response,
    discover_request_plan,
    sanitized_failure_envelope,
)


class _FakeHttpResponse:
    def __init__(self, url: str, body: bytes, content_length: int | None) -> None:
        self._url = url
        self._body = body
        self._offset = 0
        self.read_sizes: list[int] = []
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback

    def getcode(self) -> int:
        return 200

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FakeOpener:
    def __init__(self, response: _FakeHttpResponse) -> None:
        self.response = response

    def open(self, request, timeout: float) -> _FakeHttpResponse:
        del request, timeout
        return self.response


def _complete_fixture() -> tuple[dict[str, object], dict[str, FetchedResponse]]:
    plan = json.loads(
        (
            Path(runtime.PARENT_DISCOVERY_PLAN_PATH)
            .read_text(encoding="utf-8")
        )
    )
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
    return plan, responses


class RequestPlanDiscoveryV4Tests(unittest.TestCase):
    def test_declared_oversize_stream_stops_at_cap_without_raw_body(self) -> None:
        url = "https://example.test/oversize"
        response = _FakeHttpResponse(
            url,
            b"x" * (MAX_RESPONSE_BYTES + 123),
            MAX_RESPONSE_BYTES + 123,
        )
        with mock.patch.object(
            runtime.urllib.request,
            "build_opener",
            return_value=_FakeOpener(response),
        ):
            streamed = fetch_public_response(
                url,
                timeout_sec=1,
                resource_kind="navigation",
            )

        self.assertIsNone(streamed.body)
        self.assertTrue(streamed.audit.truncated)
        self.assertFalse(streamed.audit.complete)
        self.assertEqual(streamed.audit.declared_length, MAX_RESPONSE_BYTES + 123)
        self.assertEqual(streamed.audit.bytes_read, MAX_RESPONSE_BYTES)
        self.assertEqual(streamed.audit.reason, "per_response_cap")
        self.assertEqual(sum(response.read_sizes), MAX_RESPONSE_BYTES)
        self.assertTrue(all(size <= runtime.STREAM_CHUNK_BYTES for size in response.read_sizes))
        with self.assertRaises(ResponseCapExceeded) as raised:
            runtime._validated_response(streamed, url, "navigation")
        envelope = sanitized_failure_envelope(raised.exception, network_stage_entered=True)
        self.assertEqual(envelope["reason_code"], "RESPONSE_CAP_EXCEEDED")
        self.assertEqual(envelope["response_audit"]["bytes_read"], MAX_RESPONSE_BYTES)
        serialized = json.dumps(envelope)
        self.assertNotIn('"body":', serialized)
        self.assertNotIn('"raw_payload":', serialized)

    def test_unknown_length_is_conservative_at_cap_boundary(self) -> None:
        url = "https://example.test/chunked"
        response = _FakeHttpResponse(url, b"x" * (MAX_RESPONSE_BYTES + 1), None)
        with mock.patch.object(
            runtime.urllib.request,
            "build_opener",
            return_value=_FakeOpener(response),
        ):
            streamed = fetch_public_response(url, timeout_sec=1, resource_kind="official")

        self.assertIsNone(streamed.body)
        self.assertTrue(streamed.audit.truncated)
        self.assertEqual(streamed.audit.reason, "per_response_cap_boundary_unknown")
        self.assertEqual(streamed.audit.bytes_read, MAX_RESPONSE_BYTES)
        self.assertEqual(sum(response.read_sizes), MAX_RESPONSE_BYTES)

    def test_record_only_policy_does_not_promote_optional_oversize_to_body(self) -> None:
        audit = runtime.ResponseAudit(
            requested_url="https://example.test/optional",
            final_url="https://example.test/optional",
            status=200,
            resource_kind="optional_topology",
            declared_length=MAX_RESPONSE_BYTES + 1,
            bytes_read=MAX_RESPONSE_BYTES,
            complete=False,
            truncated=True,
            reason="per_response_cap",
            body_sha256=None,
        )
        response = runtime.StreamedResponse(
            audit.requested_url,
            audit.final_url,
            audit.status,
            None,
            audit,
        )
        self.assertEqual(
            runtime._validated_response(
                response,
                audit.requested_url,
                "optional_topology",
            ),
            b"",
        )

    def test_complete_body_is_streamed_and_hashed_only_in_memory(self) -> None:
        url = "https://example.test/complete"
        body = b"valid response" * 100
        response = _FakeHttpResponse(url, body, len(body))
        with mock.patch.object(
            runtime.urllib.request,
            "build_opener",
            return_value=_FakeOpener(response),
        ):
            streamed = fetch_public_response(url, timeout_sec=1, resource_kind="metadata")

        self.assertEqual(streamed.body, body)
        self.assertTrue(streamed.audit.complete)
        self.assertFalse(streamed.audit.truncated)
        self.assertEqual(streamed.audit.bytes_read, len(body))
        self.assertEqual(streamed.audit.body_sha256, hashlib.sha256(body).hexdigest())
        self.assertTrue(all(size <= runtime.STREAM_CHUNK_BYTES for size in response.read_sizes))

    def test_discovery_records_sanitized_audit_for_every_response(self) -> None:
        plan, responses = _complete_fixture()

        def fetch(url: str, resource_kind: str) -> FetchedResponse:
            self.assertIn(resource_kind, runtime.OVERSIZE_POLICIES)
            return responses[url]

        result = discover_request_plan(plan, fetch=fetch)
        self.assertEqual(result.request_count, runtime.MAX_TOTAL_HTTP_REQUESTS)
        self.assertEqual(len(result.response_audits), runtime.MAX_TOTAL_HTTP_REQUESTS)
        self.assertEqual(
            result.total_response_bytes,
            sum(int(item["bytes_read"]) for item in result.response_audits),
        )
        for audit in result.response_audits:
            self.assertTrue(audit["complete"])
            self.assertFalse(audit["truncated"])
            self.assertIsNone(audit["reason"])
            self.assertIn(audit["resource_kind"], {"metadata", "navigation", "official"})
            self.assertNotIn("body", audit)

    def test_total_response_cap_is_independent_from_per_response_cap(self) -> None:
        plan, responses = _complete_fixture()
        old_cap = runtime.MAX_TOTAL_RESPONSE_BYTES
        runtime.MAX_TOTAL_RESPONSE_BYTES = 1
        try:
            with self.assertRaises(TotalResponseCapExceeded) as raised:
                discover_request_plan(
                    plan,
                    fetch=lambda url, resource_kind: responses[url],
                )
        finally:
            runtime.MAX_TOTAL_RESPONSE_BYTES = old_cap
        self.assertGreater(raised.exception.total_response_bytes, 1)
        self.assertEqual(
            raised.exception.response_audit["resource_kind"],
            "metadata",
        )


if __name__ == "__main__":
    unittest.main()
