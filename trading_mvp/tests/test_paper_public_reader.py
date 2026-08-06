from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_public_reader as public_reader  # noqa: E402
import paper_public_reader_contract as contract_module  # noqa: E402


def _migration_files(root: Path) -> tuple[Path, Path]:
    depth_reference = root / "pit_universe_public_probe.py"
    depth_reference.write_text(
        "def parse_mexc_depth_l1(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    errors_path = root / "errors.jsonl"
    errors_path.write_text(
        json.dumps(
            {
                "venue": "mexc",
                "category": "schema_mismatch",
                "endpoint_id": "mexc_tickers",
                "detail": "missing fields bid1 and ask1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    deterministic = {
        "schema": "trading_mvp_paper_public_readonly_probe_result_v1",
        "run_id": "paper_public_readonly_probe_20260730_142851",
        "status": "STOPPED_INCOMPLETE",
        "final": False,
        "plan": {
            "plan_hash_sha256": (
                "318c6dbd76777cc4cff8f8e4e0ec67df"
                "10b497b33709155c642d2476285527ff"
            )
        },
        "quality": {"hard_stop_reason": "schema_mismatch"},
        "artifacts": {
            "errors_path": str(errors_path.resolve()),
            "errors_file_sha256": contract_module.sha256_file(errors_path),
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
    }
    manifest_path = root / "migration-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                **deterministic,
                "deterministic_result_hash": contract_module.sha256_json(
                    deterministic
                ),
                "started_at_utc": "2026-07-30T11:28:51+00:00",
                "completed_at_utc": "2026-07-30T11:28:52+00:00",
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, depth_reference


def _build_contract(root: Path, *, version: str = "v1") -> dict:
    funding = root / "funding.py"
    observer = root / "observer.py"
    evidence = root / "evidence.json"
    funding.write_text("fixture", encoding="utf-8")
    observer.write_text("fixture", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_venue_api_reliability_evidence_v1",
                "scope": {
                    "venues": ["mexc", "gateio"],
                    "private_api_keys": False,
                    "live_orders": False,
                },
                "historical_rest_collect": {"completion_rate": 1.0},
                "pit_snapshot_collect": {
                    "aggregate": {"dual_venue_success_rate": 1.0}
                },
                "verdict": "RESEARCH_DATA_PATH_RELIABLE_WITH_GUARDS_PRODUCTION_SLA_UNPROVEN",
            }
        ),
        encoding="utf-8",
    )
    kwargs = {}
    if version == "v2":
        manifest, depth_reference = _migration_files(root)
        kwargs = {
            "migration_probe_manifest_path": manifest,
            "depth_reference_path": depth_reference,
        }
    return contract_module.build_public_reader_contract(
        funding_client_path=funding,
        observer_runtime_path=observer,
        reliability_evidence_path=evidence,
        contract_version=version,
        generated_at_utc="2026-07-28T20:00:00+00:00",
        **kwargs,
    )


class PaperPublicReaderTests(unittest.TestCase):
    NOW_MS = 1_800_000_000_000

    def _reader(
        self,
        root: Path,
        *,
        replace: tuple[str, public_reader.FixtureOutcome] | None = None,
    ) -> tuple[
        public_reader.FixturePublicMarketReader,
        public_reader.FixturePublicGetTransport,
    ]:
        outcomes = public_reader._valid_fixture_outcomes(self.NOW_MS)
        if replace is not None:
            outcomes[replace[0]] = replace[1]
        transport = public_reader.FixturePublicGetTransport(outcomes)
        return (
            public_reader.FixturePublicMarketReader(
                _build_contract(root), transport
            ),
            transport,
        )

    def test_mexc_fixture_normalizes_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader, transport = self._reader(Path(tmp))
            snapshot = reader.read_market_snapshot(
                venue="mexc",
                symbol="HYPE_USDT",
                canonical_base="hype",
                observer_received_ts_ms=self.NOW_MS,
            )
        self.assertEqual(snapshot["schema"], public_reader.SNAPSHOT_SCHEMA)
        self.assertEqual(snapshot["venue"], "mexc")
        self.assertEqual(snapshot["quote_age_ms"], 1000)
        self.assertFalse(snapshot["network_request_performed"])
        self.assertEqual(len(transport.calls), 4)

    def test_mexc_v2_uses_depth_l1_when_ticker_has_no_bbo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outcomes = public_reader._valid_fixture_outcomes(self.NOW_MS)
            ticker_payload = outcomes["mexc_tickers"].payload
            del ticker_payload["data"][0]["bid1"]
            del ticker_payload["data"][0]["ask1"]
            outcomes["mexc_depth"].payload["data"]["bids"][0][0] = "9.98"
            outcomes["mexc_depth"].payload["data"]["asks"][0][0] = "10.04"
            transport = public_reader.FixturePublicGetTransport(outcomes)
            reader = public_reader.FixturePublicMarketReader(
                _build_contract(root, version="v2"),
                transport,
            )
            snapshot = reader.read_market_snapshot(
                venue="mexc",
                symbol="HYPE_USDT",
                canonical_base="hype",
                observer_received_ts_ms=self.NOW_MS,
            )
        self.assertEqual(snapshot["best_bid"], 9.99)
        self.assertEqual(snapshot["best_ask"], 10.03)
        self.assertEqual(snapshot["quote_age_ms"], 1000)
        self.assertEqual(len(transport.calls), 4)

    def test_gate_fixture_normalizes_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader, transport = self._reader(Path(tmp))
            snapshot = reader.read_market_snapshot(
                venue="gateio",
                symbol="HYPE_USDT",
                canonical_base="hype",
                observer_received_ts_ms=self.NOW_MS,
            )
        self.assertEqual(snapshot["venue"], "gateio")
        self.assertEqual(snapshot["quote_age_ms"], 1200)
        self.assertEqual(snapshot["bid_depth"][0]["price"], 10.02)
        self.assertEqual(len(transport.calls), 4)

    def test_network_capable_transport_is_rejected(self) -> None:
        class NetworkTransport:
            network_capable = True

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "network-capable"):
                public_reader.FixturePublicMarketReader(
                    _build_contract(Path(tmp)), NetworkTransport()
                )

    def test_timeout_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader, _ = self._reader(
                Path(tmp),
                replace=(
                    "mexc_tickers",
                    public_reader.FixtureOutcome(error="timeout"),
                ),
            )
            with self.assertRaises(public_reader.PublicReaderError) as caught:
                reader.read_market_snapshot(
                    venue="mexc",
                    symbol="HYPE_USDT",
                    canonical_base="hype",
                    observer_received_ts_ms=self.NOW_MS,
                )
        self.assertEqual(caught.exception.category, "transport_timeout")

    def test_http_error_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader, _ = self._reader(
                Path(tmp),
                replace=(
                    "gateio_tickers",
                    public_reader.FixtureOutcome(
                        status_code=503, payload={}
                    ),
                ),
            )
            with self.assertRaises(public_reader.PublicReaderError) as caught:
                reader.read_market_snapshot(
                    venue="gateio",
                    symbol="HYPE_USDT",
                    canonical_base="hype",
                    observer_received_ts_ms=self.NOW_MS,
                )
        self.assertEqual(caught.exception.category, "http_error")

    def test_schema_error_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader, _ = self._reader(
                Path(tmp),
                replace=(
                    "mexc_tickers",
                    public_reader.FixtureOutcome(
                        payload={
                            "success": True,
                            "data": [{"symbol": "HYPE_USDT"}],
                        }
                    ),
                ),
            )
            with self.assertRaises(public_reader.PublicReaderError) as caught:
                reader.read_market_snapshot(
                    venue="mexc",
                    symbol="HYPE_USDT",
                    canonical_base="hype",
                    observer_received_ts_ms=self.NOW_MS,
                )
        self.assertEqual(caught.exception.category, "schema_mismatch")

    def test_stale_quote_is_classified(self) -> None:
        stale = public_reader.FixtureOutcome(
            payload={
                "current": self.NOW_MS - 6000,
                "bids": [{"p": "10.02", "s": "100"}],
                "asks": [{"p": "10.04", "s": "100"}],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            reader, _ = self._reader(
                Path(tmp), replace=("gateio_depth", stale)
            )
            with self.assertRaises(public_reader.PublicReaderError) as caught:
                reader.read_market_snapshot(
                    venue="gateio",
                    symbol="HYPE_USDT",
                    canonical_base="hype",
                    observer_received_ts_ms=self.NOW_MS,
                )
        self.assertEqual(caught.exception.category, "stale_quote")

    def test_crossed_book_and_empty_depth_fail_schema(self) -> None:
        outcomes = [
            public_reader.FixtureOutcome(
                payload={
                    "success": True,
                    "data": [
                        {
                            "symbol": "HYPE_USDT",
                            "bid1": "10.02",
                            "ask1": "10.02",
                            "fairPrice": "10.01",
                            "indexPrice": "10.005",
                            "timestamp": self.NOW_MS - 1000,
                        }
                    ],
                }
            ),
            public_reader.FixtureOutcome(
                payload={"success": True, "data": {"bids": [], "asks": []}}
            ),
        ]
        for endpoint_id, outcome in zip(
            ("mexc_tickers", "mexc_depth"), outcomes
        ):
            with self.subTest(endpoint_id=endpoint_id):
                with tempfile.TemporaryDirectory() as tmp:
                    reader, _ = self._reader(
                        Path(tmp), replace=(endpoint_id, outcome)
                    )
                    with self.assertRaises(
                        public_reader.PublicReaderError
                    ) as caught:
                        reader.read_market_snapshot(
                            venue="mexc",
                            symbol="HYPE_USDT",
                            canonical_base="hype",
                            observer_received_ts_ms=self.NOW_MS,
                        )
                self.assertEqual(
                    caught.exception.category, "schema_mismatch"
                )

    def test_token_bucket_waits_after_frozen_burst(self) -> None:
        clock = public_reader.FixtureClock()
        bucket = public_reader.DeterministicTokenBucket(
            requests_per_sec=5.0,
            burst=5,
            start_ms=clock.now_ms,
        )
        waits = [bucket.acquire(clock) for _ in range(6)]
        self.assertEqual(waits, [0, 0, 0, 0, 0, 200])
        self.assertEqual(clock.now_ms, 200)

    def test_retry_after_seconds_and_http_date_are_bounded(self) -> None:
        self.assertEqual(
            public_reader._retry_after_ms(
                {"Retry-After": "2"},
                now_ms=0,
            ),
            2000,
        )
        self.assertEqual(
            public_reader._retry_after_ms(
                {"retry-after": "Thu, 01 Jan 1970 00:02:00 GMT"},
                now_ms=0,
            ),
            60_000,
        )
        with self.assertRaisesRegex(ValueError, "neither seconds"):
            public_reader._retry_after_ms(
                {"Retry-After": "not-a-delay"},
                now_ms=0,
            )

    def test_reader_retries_retryable_status_and_honors_retry_after(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _build_contract(Path(tmp))
            valid = public_reader._valid_fixture_outcomes(self.NOW_MS)[
                "mexc_contracts"
            ]
            transport = public_reader.FixturePublicGetTransport(
                {
                    "mexc_contracts": [
                        public_reader.FixtureOutcome(
                            status_code=429,
                            payload={},
                            headers={"Retry-After": "2"},
                        ),
                        valid,
                    ]
                }
            )
            clock = public_reader.FixtureClock()
            reader = public_reader.FixturePublicMarketReader(
                contract, transport, clock=clock
            )
            payload = reader._request(
                venue="mexc",
                endpoint_id="mexc_contracts",
                url="https://contract.mexc.com/api/v1/contract/detail",
            )
        self.assertTrue(payload["success"])
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(clock.sleep_calls_ms, [2000])
        self.assertEqual(reader.retry_trace[0]["reason"], "http_429")

    def test_reader_stops_at_maximum_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _build_contract(Path(tmp))
            transport = public_reader.FixturePublicGetTransport(
                {
                    "mexc_contracts": public_reader.FixtureOutcome(
                        status_code=503, payload={}
                    )
                }
            )
            reader = public_reader.FixturePublicMarketReader(
                contract, transport
            )
            with self.assertRaises(public_reader.PublicReaderError) as caught:
                reader._request(
                    venue="mexc",
                    endpoint_id="mexc_contracts",
                    url="https://contract.mexc.com/api/v1/contract/detail",
                )
        self.assertEqual(caught.exception.category, "http_error")
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(
            [item["applied_delay_ms"] for item in reader.retry_trace],
            [500, 1000],
        )

    def test_retry_rate_limit_report_is_fixture_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = public_reader.build_retry_rate_limit_fixture_report(
                contract_path=contract_path,
                generated_at_utc="2026-07-29T04:40:00+00:00",
            )
        self.assertEqual(report["scenario_count"], 6)
        self.assertEqual(report["accepted_scenario_count"], 6)
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(
            report["verdict"],
            "FIXTURE_RETRY_RATE_LIMIT_ACCEPTED_NO_NETWORK",
        )
        self.assertEqual(
            report["next_allowed_action"],
            "paper_public_snapshot_observer_bridge_v1",
        )

    def test_requests_transport_enforces_frozen_request_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _build_contract(Path(tmp))
            url = "https://contract.mexc.com/api/v1/contract/detail"
            headers = {"Accept": "application/json"}
            authorization = contract_module.authorize_public_get(
                contract,
                venue="mexc",
                method="GET",
                url=url,
                params={},
                headers=headers,
            )
            response = public_reader.FixtureRequestsResponse(
                status_code=200,
                body=b'{"success":true,"data":[]}',
            )
            session = public_reader.FixtureRequestsSession([response])
            transport = public_reader.RequestsPublicGetTransport(
                contract, session=session
            )
            status, payload = transport.get(
                authorization=authorization,
                url=url,
                params={},
                headers=headers,
                connect_timeout_sec=3.0,
                read_timeout_sec=7.0,
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"success": True, "data": []})
        self.assertFalse(session.trust_env)
        self.assertIsNone(session.auth)
        self.assertFalse(session.cookies)
        self.assertFalse(session.calls[0]["allow_redirects"])
        self.assertTrue(session.calls[0]["verify"])
        self.assertTrue(session.calls[0]["stream"])
        self.assertTrue(response.closed)

    def test_requests_transport_rejects_private_header_before_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _build_contract(Path(tmp))
            url = "https://contract.mexc.com/api/v1/contract/detail"
            authorization = contract_module.authorize_public_get(
                contract,
                venue="mexc",
                method="GET",
                url=url,
                params={},
                headers={"Accept": "application/json"},
            )
            session = public_reader.FixtureRequestsSession(
                [
                    public_reader.FixtureRequestsResponse(
                        status_code=200,
                        body=b"{}",
                    )
                ]
            )
            transport = public_reader.RequestsPublicGetTransport(
                contract, session=session
            )
            with self.assertRaisesRegex(ValueError, "header is forbidden"):
                transport.get(
                    authorization=authorization,
                    url=url,
                    params={},
                    headers={"Authorization": "Bearer fixture-secret"},
                    connect_timeout_sec=3.0,
                    read_timeout_sec=7.0,
                )
        self.assertEqual(session.calls, [])

    def test_requests_transport_rejects_declared_oversize_and_closes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = _build_contract(Path(tmp))
            url = "https://contract.mexc.com/api/v1/contract/detail"
            headers = {"Accept": "application/json"}
            authorization = contract_module.authorize_public_get(
                contract,
                venue="mexc",
                method="GET",
                url=url,
                params={},
                headers=headers,
            )
            maximum = contract["transport_policy"]["response_max_bytes"]
            response = public_reader.FixtureRequestsResponse(
                status_code=200,
                body=b"{}",
                headers={"Content-Length": str(maximum + 1)},
            )
            session = public_reader.FixtureRequestsSession([response])
            transport = public_reader.RequestsPublicGetTransport(
                contract, session=session
            )
            with self.assertRaises(public_reader.PublicReaderError) as caught:
                transport.get(
                    authorization=authorization,
                    url=url,
                    params={},
                    headers=headers,
                    connect_timeout_sec=3.0,
                    read_timeout_sec=7.0,
                )
        self.assertEqual(caught.exception.category, "response_too_large")
        self.assertTrue(response.closed)

    def test_transport_adapter_report_is_fixture_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = (
                public_reader.build_public_transport_adapter_fixture_report(
                    contract_path=contract_path,
                    generated_at_utc="2026-07-29T05:00:00+00:00",
                )
            )
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(len(report["pre_network_rejections"]), 2)
        self.assertTrue(
            report["response_byte_limit"]["declared_oversize_rejected"]
        )
        self.assertEqual(
            report["verdict"],
            "FIXTURE_PUBLIC_TRANSPORT_ADAPTER_ACCEPTED_NO_NETWORK",
        )
        self.assertEqual(
            report["next_allowed_action"],
            "paper_product_readiness_audit_v4",
        )

    def test_requests_transport_wires_into_normalized_reader_without_network(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            first = (
                public_reader.build_public_reader_transport_wiring_fixture_report(
                    contract_path=contract_path,
                    generated_at_utc="2026-07-29T05:05:00+00:00",
                )
            )
            second = (
                public_reader.build_public_reader_transport_wiring_fixture_report(
                    contract_path=contract_path,
                    generated_at_utc="2026-07-29T05:06:00+00:00",
                )
            )
        self.assertEqual(first["network_requests"], 0)
        self.assertEqual(first["fixture_session_calls"], 8)
        self.assertTrue(first["responses_closed"])
        self.assertEqual(len(first["normalized_snapshots"]), 2)
        self.assertFalse(
            any(
                item["network_request_performed"]
                for item in first["normalized_snapshots"]
            )
        )
        self.assertEqual(
            first["deterministic_result_hash"],
            second["deterministic_result_hash"],
        )
        self.assertEqual(
            first["verdict"],
            "FIXTURE_PUBLIC_READER_TRANSPORT_WIRING_ACCEPTED_NO_NETWORK",
        )
        self.assertEqual(
            first["next_allowed_action"],
            "paper_public_streaming_byte_limit_fixture_v1",
        )

    def test_streamed_byte_limit_without_content_length_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = (
                public_reader.build_public_streaming_byte_limit_fixture_report(
                    contract_path=contract_path,
                    generated_at_utc="2026-07-29T05:10:00+00:00",
                )
            )
        self.assertFalse(report["scenario"]["content_length_present"])
        self.assertEqual(
            report["scenario"]["streamed_bytes"],
            report["scenario"]["maximum_bytes"] + 1,
        )
        self.assertEqual(
            report["scenario"]["observed_category"],
            "response_too_large",
        )
        self.assertTrue(report["scenario"]["response_closed"])
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(
            report["verdict"],
            "FIXTURE_PUBLIC_STREAMING_BYTE_LIMIT_ACCEPTED_NO_NETWORK",
        )
        self.assertEqual(
            report["next_allowed_action"],
            "paper_public_health_contract_binding_fixture_v1",
        )

    def test_system_clock_fixture_is_monotonic_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = public_reader.build_public_system_clock_fixture_report(
                contract_path=contract_path,
                generated_at_utc="2026-07-29T05:15:00+00:00",
            )
        self.assertEqual(
            report["clock"]["backward_wall_clock_clamped_ms"],
            report["clock"]["after_direct_sleep_ms"],
        )
        self.assertEqual(report["token_bucket"]["first_wait_ms"], 0)
        self.assertEqual(report["token_bucket"]["second_wait_ms"], 500)
        self.assertEqual(report["retry_after_ms"], 2000)
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(
            report["verdict"],
            "FIXTURE_PUBLIC_SYSTEM_CLOCK_ACCEPTED_NO_NETWORK",
        )

    def test_transport_retry_wiring_uses_retry_after_without_network(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = (
                public_reader.build_public_transport_retry_wiring_fixture_report(
                    contract_path=contract_path,
                    generated_at_utc="2026-07-29T05:16:00+00:00",
                )
            )
        self.assertEqual(report["fixture_session_calls"], 5)
        self.assertEqual(len(report["retry_trace"]), 1)
        self.assertEqual(report["retry_trace"][0]["reason"], "http_503")
        self.assertEqual(
            report["retry_trace"][0]["applied_delay_ms"], 1000
        )
        self.assertTrue(report["responses_closed"])
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(
            report["verdict"],
            "FIXTURE_PUBLIC_TRANSPORT_RETRY_WIRING_ACCEPTED_NO_NETWORK",
        )

    def test_runtime_reader_factory_binds_fail_closed_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = (
                public_reader.build_public_runtime_reader_factory_fixture_report(
                    contract_path=contract_path,
                    generated_at_utc="2026-07-29T05:25:00+00:00",
                )
            )
        self.assertEqual(report["factory"]["reader_type"], "PublicMarketReader")
        self.assertEqual(
            report["factory"]["transport_type"],
            "RequestsPublicGetTransport",
        )
        self.assertEqual(report["factory"]["clock_type"], "SystemClock")
        self.assertEqual(report["fixture_session_calls"], 8)
        self.assertTrue(report["responses_closed"])
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(
            report["verdict"],
            "FIXTURE_PUBLIC_RUNTIME_READER_FACTORY_ACCEPTED_NO_NETWORK",
        )

    def test_endpoint_contract_parity_covers_both_venues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = (
                public_reader.build_public_endpoint_contract_parity_fixture_report(
                    contract_path=contract_path,
                    generated_at_utc="2026-07-29T05:30:00+00:00",
                )
            )
        self.assertEqual(report["endpoint_count"], 8)
        self.assertEqual(report["venue_counts"], {"mexc": 4, "gateio": 4})
        self.assertEqual(
            report["normalizer_roles"],
            ["contracts", "depth", "funding", "ticker"],
        )
        self.assertTrue(
            all(row["fixture_schema_valid"] for row in report["endpoint_parity"])
        )
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(
            report["verdict"],
            "FIXTURE_PUBLIC_ENDPOINT_CONTRACT_PARITY_ACCEPTED_NO_NETWORK",
        )

    def test_readonly_probe_plan_is_frozen_but_not_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            first = public_reader.build_public_readonly_probe_plan(
                contract_path=contract_path,
                generated_at_utc="2026-07-29T05:35:00+00:00",
            )
            second = public_reader.build_public_readonly_probe_plan(
                contract_path=contract_path,
                generated_at_utc="2026-07-29T05:36:00+00:00",
            )
        self.assertEqual(
            first["plan_hash_sha256"], second["plan_hash_sha256"]
        )
        self.assertFalse(first["authorization"]["network_authorized"])
        self.assertFalse(first["authorization"]["execution_authorized"])
        self.assertFalse(first["authorization"]["automatic_start"])
        self.assertEqual(
            first["safety"]["network_requests_performed"], 0
        )
        self.assertFalse(first["safety"]["market_data_writer_started"])
        self.assertEqual(first["probe"]["duration_sec"], 120)
        self.assertEqual(
            first["verdict"],
            "PUBLIC_READONLY_PROBE_PLAN_FROZEN_NOT_AUTHORIZED",
        )

    def test_report_covers_success_and_required_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = public_reader.build_fixture_validation_report(
                contract_path=contract_path,
                generated_at_utc="2026-07-28T20:05:00+00:00",
            )
        self.assertEqual(report["success_count"], 2)
        self.assertEqual(report["failure_count"], 4)
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(
            {item["observed_category"] for item in report["failure_scenarios"]},
            {
                "transport_timeout",
                "http_error",
                "schema_mismatch",
                "stale_quote",
            },
        )


if __name__ == "__main__":
    unittest.main()
