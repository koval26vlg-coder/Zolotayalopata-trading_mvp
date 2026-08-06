from __future__ import annotations

import copy
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_futures_archive import build_archive_source_plan  # noqa: E402
from gate_momentum_archive import (  # noqa: E402
    ACTIONABILITY_SCHEMA,
    HYPOTHESIS_ID,
    PLAN_SCHEMA,
    PROBE_RESULT_SCHEMA,
    assess_momentum_archive_actionability,
    build_momentum_archive_plan,
    build_momentum_public_probe_descriptor,
    execute_momentum_public_schema_probe,
    validate_momentum_archive_plan,
    validate_momentum_public_probe_result,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _write_source_route(path: Path) -> None:
    route: dict[str, object] = {
        "schema": "trading_mvp_historical_archive_route_planonly_v1",
        "created_at_utc": "2026-07-24T13:25:13+00:00",
        "mode": "PlanOnly",
        "research_only": True,
        "status": "EXTERNAL_SOURCE_PREPARED_AWAIT_ACCESS",
        "immutable_facts": {
            "gate_futures_external_archive_candidate": {
                "provider": "Tardis.dev",
                "exchange": "gate-io-futures",
                "coverage_documented_since": "2020-07-01",
                "documented_data_types": [
                    "trades",
                    "incremental_book_L2",
                    "quotes",
                    "derivative_ticker",
                ],
                "access_note": "entitlement required outside documented samples",
            }
        },
        "closed_branches_not_reopened": [
            "cross_venue_perp_basis_convergence_history_v1",
            "historical_basis_v2",
        ],
        "permitted_next_sequence": [
            "Create a materially new archive-source hypothesis contract before reading market values.",
            "Perform a bounded schema and symbol-identity probe.",
            "Run historical quality only.",
        ],
        "prohibited": [
            "reuse_closed_branch_as_new",
            "retune",
            "grid_search",
            "oos",
            "execution_probe",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
        "data_access_audit": {
            "market_rows_read": False,
            "returns_read": False,
            "pnl_read": False,
            "signal_scores_computed": False,
            "network_collector_started": False,
            "provider_account_accessed": False,
        },
        "next_allowed_action": "create_materially_new_archive_source_contract",
    }
    route["plan_hash"] = _sha256_json(route)
    path.write_text(json.dumps(route, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_source_closure(path: Path, *, verdict: str = "INSUFFICIENT_SOURCE_QUALITY") -> None:
    closure: dict[str, object] = {
        "schema": "trading_mvp_gate_historical_membership_v3_archive_source_closure_v1",
        "final": True,
        "branch_status": "CLOSED_WITHOUT_HISTORY_OR_OOS",
        "verdict": verdict,
        "reason_codes": [
            "MISSING_END_DELISTED_ARCHIVE_AVAILABILITY_BELOW_FROZEN_GATE"
        ],
        "source_diagnosis": {
            "active_control_passed": True,
            "known_end_delisted_control_passed": True,
            "missing_end_delisted_available_symbols": 0,
            "missing_end_delisted_symbol_availability": 0.0,
            "required_minimum_availability": 0.8,
        },
        "data_access_audit": {
            "archive_payload_read": False,
            "history_read": False,
            "oos_read": False,
            "pnl_read": False,
            "returns_read": False,
            "signals_read": False,
            "train_read": False,
        },
        "next_allowed_action": "select_new_materially_distinct_planonly_hypothesis",
    }
    closure["artifact_hash"] = _sha256_json(closure)
    path.write_text(json.dumps(closure, ensure_ascii=False, indent=2), encoding="utf-8")


class FakeResponse:
    def __init__(
        self,
        *,
        payload: object | None = None,
        body: bytes | None = None,
        status_code: int = 200,
    ) -> None:
        self.body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if body is None
            else body
        )
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int = 8192) -> object:
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index : index + chunk_size]

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class RecordingSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class GateMomentumArchivePlanTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> tuple[Path, Path]:
        route_path = root / "route.json"
        archive_path = root / "archive-plan.json"
        closure_path = root / "source-closure.json"
        _write_source_route(route_path)
        build_archive_source_plan(
            route_path,
            archive_path,
            frozen_at_utc="2026-07-24T20:00:00+00:00",
        )
        _write_source_closure(closure_path)
        return archive_path, closure_path

    def test_plan_freezes_existing_strategy_and_new_source_without_reading_market_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path, closure_path = self._fixtures(root)
            first = build_momentum_archive_plan(
                archive_path,
                closure_path,
                frozen_at_utc="2026-07-24T20:10:00+00:00",
            )
            second = build_momentum_archive_plan(
                archive_path,
                closure_path,
                frozen_at_utc="2026-07-24T20:10:00+00:00",
            )

        self.assertEqual(first["schema"], PLAN_SCHEMA)
        self.assertEqual(first["hypothesis"]["id"], HYPOTHESIS_ID)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(first["strategy"]["lookback_days"], 30)
        self.assertEqual(first["strategy"]["hold_days"], 7)
        self.assertEqual(first["strategy"]["rebalance_every_days"], 7)
        self.assertEqual(first["costs"]["normal_cycle_bps"], 46.0)
        self.assertEqual(first["costs"]["stress_cycle_bps"], 72.0)
        self.assertEqual(first["sample"]["warmup_days"], 20)
        self.assertEqual(first["sample"]["train_days"], 100)
        self.assertEqual(first["sample"]["oos_days"], 100)
        self.assertFalse(first["data_access_audit"]["network_access"])
        self.assertFalse(first["data_access_audit"]["market_rows_read"])
        self.assertFalse(first["data_access_audit"]["returns_read"])
        self.assertFalse(first["data_access_audit"]["pnl_read"])
        self.assertEqual(
            first["next_allowed_command"],
            "gate_momentum_archive_actionability_audit",
        )

    def test_plan_requires_gate_lifecycle_and_point_in_time_binance_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path, closure_path = self._fixtures(root)
            plan = build_momentum_archive_plan(archive_path, closure_path)

        source = plan["source_contract"]
        self.assertEqual(source["gate_exchange_id"], "gate-io-futures")
        self.assertEqual(source["binance_reference_exchange_id"], "binance")
        self.assertTrue(source["gate_symbol_available_since_required"])
        self.assertTrue(source["gate_symbol_available_to_required_for_delisted"])
        self.assertTrue(source["point_in_time_binance_spot_membership_required"])
        self.assertEqual(source["history_days"], 220)
        self.assertEqual(source["minimum_canonical_assets"], 20)

    def test_plan_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path, closure_path = self._fixtures(root)
            plan = build_momentum_archive_plan(archive_path, closure_path)
            tampered = copy.deepcopy(plan)
            tampered["strategy"]["lookback_days"] = 29

        with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
            validate_momentum_archive_plan(tampered)

    def test_public_probe_descriptor_covers_gate_schema_and_binance_reference_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path, closure_path = self._fixtures(root)
            plan = build_momentum_archive_plan(archive_path, closure_path)
            descriptor = build_momentum_public_probe_descriptor(plan)

        self.assertEqual(descriptor["request_count"], 4)
        requests = descriptor["requests"]
        self.assertTrue(
            any(
                item.get("kind") == "binance_reference_exchange_metadata"
                and item.get("url")
                == "https://api.tardis.dev/v1/exchanges/binance"
                for item in requests
            )
        )
        self.assertFalse(descriptor["data_access_audit"]["market_values_read"])
        self.assertFalse(descriptor["data_access_audit"]["returns_read"])
        self.assertFalse(descriptor["data_access_audit"]["pnl_read"])
        self.assertNotIn(
            "Authorization",
            json.dumps(descriptor, ensure_ascii=False, sort_keys=True),
        )

    def test_non_source_quality_closure_cannot_be_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path, closure_path = self._fixtures(root)
            _write_source_closure(closure_path, verdict="REJECT")
            with self.assertRaisesRegex(ValueError, "source-quality closure"):
                build_momentum_archive_plan(archive_path, closure_path)


class GateMomentumArchiveActionabilityTests(unittest.TestCase):
    def _plan(self, root: Path) -> tuple[dict[str, object], Path]:
        route_path = root / "route.json"
        archive_path = root / "archive-plan.json"
        closure_path = root / "source-closure.json"
        _write_source_route(route_path)
        build_archive_source_plan(
            route_path,
            archive_path,
            frozen_at_utc="2026-07-24T20:00:00+00:00",
        )
        _write_source_closure(closure_path)
        return (
            build_momentum_archive_plan(
                archive_path,
                closure_path,
                frozen_at_utc="2026-07-24T20:10:00+00:00",
            ),
            closure_path,
        )

    def test_scope_specific_audit_allows_only_public_schema_probe_without_entitlement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, _ = self._plan(Path(tmp))
            result = assess_momentum_archive_actionability(
                plan,
                entitlement_present=False,
            )

        self.assertEqual(result["schema"], ACTIONABILITY_SCHEMA)
        self.assertEqual(
            result["verdict"],
            "PUBLIC_SCHEMA_PROBE_ALLOWED_ENTITLEMENT_REQUIRED_FOR_HISTORY",
        )
        self.assertTrue(result["public_schema_probe_allowed"])
        self.assertFalse(result["history_collect_allowed"])
        self.assertFalse(result["mexc_history_required"])
        self.assertEqual(result["network_requests"], 0)
        self.assertFalse(result["data_access_audit"]["market_rows_read"])
        self.assertFalse(result["data_access_audit"]["returns_read"])
        self.assertFalse(result["data_access_audit"]["pnl_read"])
        self.assertEqual(
            result["next_allowed_command"],
            "visible_gate_momentum_archive_public_schema_probe",
        )

    def test_entitlement_does_not_skip_schema_and_identity_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, _ = self._plan(Path(tmp))
            result = assess_momentum_archive_actionability(
                plan,
                entitlement_present=True,
            )

        self.assertEqual(
            result["verdict"],
            "PUBLIC_SCHEMA_PROBE_ALLOWED_ENTITLEMENT_PRESENT",
        )
        self.assertTrue(result["archive_entitlement_present"])
        self.assertTrue(result["public_schema_probe_allowed"])
        self.assertFalse(result["history_collect_allowed"])

    def test_parent_closure_mutation_after_freeze_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, closure_path = self._plan(root)
            closure = json.loads(closure_path.read_text(encoding="utf-8"))
            closure["source_diagnosis"]["missing_end_delisted_available_symbols"] = 10
            closure_path.write_text(json.dumps(closure), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "source closure file hash mismatch"):
                assess_momentum_archive_actionability(plan)


class GateMomentumPublicSchemaProbeTests(unittest.TestCase):
    def _plan_and_descriptor(
        self,
        root: Path,
        *,
        sample_date: str = "2020-07-01",
    ) -> tuple[dict[str, object], dict[str, object]]:
        route_path = root / "route.json"
        archive_path = root / "archive-plan.json"
        closure_path = root / "source-closure.json"
        _write_source_route(route_path)
        build_archive_source_plan(
            route_path,
            archive_path,
            frozen_at_utc="2026-07-24T20:00:00+00:00",
        )
        _write_source_closure(closure_path)
        plan = build_momentum_archive_plan(
            archive_path,
            closure_path,
            frozen_at_utc="2026-07-24T20:10:00+00:00",
        )
        return (
            plan,
            build_momentum_public_probe_descriptor(
                plan,
                sample_date=sample_date,
                max_runtime_sec=120,
            ),
        )

    @staticmethod
    def _gate_metadata(*, include_closed_lifecycle: bool = True) -> dict[str, object]:
        symbols: list[dict[str, object]] = [
            {
                "id": "BTC_USDT",
                "type": "perpetual",
                "availableSince": "2020-07-01T00:00:00.000Z",
                "dataTypes": ["trades", "derivative_ticker"],
            },
            {
                "id": "ETH_USDT",
                "type": "perpetual",
                "availableSince": "2020-07-01T00:00:00.000Z",
                "dataTypes": ["trades", "derivative_ticker"],
            },
        ]
        if include_closed_lifecycle:
            symbols[1]["availableTo"] = "2024-02-01T00:00:00.000Z"
        return {
            "id": "gate-io-futures",
            "supportsDatasets": True,
            "datasets": {
                "dataTypes": ["trades", "derivative_ticker"],
                "exportedFrom": "2020-07-01T00:00:00.000Z",
                "exportedUntil": "2026-07-23T00:00:00.000Z",
                "symbols": symbols,
            },
        }

    @staticmethod
    def _binance_metadata() -> dict[str, object]:
        return {
            "id": "binance",
            "supportsDatasets": True,
            "datasets": {
                "dataTypes": ["trades"],
                "exportedFrom": "2019-03-30T00:00:00.000Z",
                "exportedUntil": "2026-07-23T00:00:00.000Z",
                "symbols": [
                    {
                        "id": "BTCUSDT",
                        "type": "spot",
                        "availableSince": "2019-03-30T00:00:00.000Z",
                    },
                    {
                        "id": "ETHUSDT",
                        "type": "spot",
                        "availableSince": "2019-03-30T00:00:00.000Z",
                        "availableTo": "2025-01-01T00:00:00.000Z",
                    },
                ],
            },
        }

    @staticmethod
    def _header(data_type: str) -> bytes:
        if data_type == "trades":
            line = "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
        else:
            line = (
                "exchange,symbol,timestamp,local_timestamp,funding_timestamp,"
                "funding_rate,predicted_funding_rate,open_interest,last_price,"
                "index_price,mark_price\n"
            )
        return gzip.compress(line.encode("utf-8"))

    def _success_responses(self) -> list[FakeResponse]:
        return [
            FakeResponse(payload=self._gate_metadata()),
            FakeResponse(body=self._header("trades")),
            FakeResponse(body=self._header("derivative_ticker")),
            FakeResponse(payload=self._binance_metadata()),
        ]

    def test_public_probe_accepts_lifecycle_and_csv_schema_without_market_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, descriptor = self._plan_and_descriptor(root)
            responses = self._success_responses()
            session = RecordingSession(responses)
            output = root / "probe-result.json"
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=session,
                entitlement_present=False,
                output_path=output,
                generated_at_utc="2026-07-24T21:00:00+00:00",
            )

            saved = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["schema"], PROBE_RESULT_SCHEMA)
        self.assertEqual(saved, result)
        self.assertEqual(
            result["verdict"],
            "PUBLIC_SCHEMA_ACCEPTED_ENTITLEMENT_REQUIRED_FOR_IDENTITY_AND_HISTORY",
        )
        self.assertEqual(result["network_requests"], 4)
        self.assertEqual(result["gate_metadata"]["dataset_symbol_count"], 2)
        self.assertEqual(result["gate_metadata"]["closed_lifecycle_symbols"], 1)
        self.assertEqual(result["gate_metadata"]["available_since_coverage"], 1.0)
        self.assertEqual(result["binance_reference"]["dataset_symbol_count"], 2)
        self.assertEqual(
            result["identity_schema_status"],
            "PENDING_ENTITLED_INSTRUMENT_METADATA",
        )
        self.assertFalse(result["history_collect_allowed"])
        self.assertFalse(result["data_access_audit"]["market_values_read"])
        self.assertFalse(result["data_access_audit"]["returns_read"])
        self.assertFalse(result["data_access_audit"]["pnl_read"])
        self.assertTrue(all(call["headers"] == {} for call in session.calls))
        self.assertTrue(all(call["stream"] is True for call in session.calls))
        self.assertTrue(all(response.closed for response in responses))
        self.assertNotIn("BTC_USDT", json.dumps(result, sort_keys=True))
        self.assertNotIn("BTCUSDT", json.dumps(result, sort_keys=True))

    def test_tampered_descriptor_fails_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            descriptor["requests"][0]["url"] = "https://example.invalid/"
            session = RecordingSession([])

            with self.assertRaisesRegex(ValueError, "descriptor hash mismatch"):
                execute_momentum_public_schema_probe(
                    plan,
                    descriptor,
                    session=session,
                )

        self.assertEqual(session.calls, [])

    def test_non_sample_day_fails_before_network_without_entitlement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(
                Path(tmp),
                sample_date="2020-07-02",
            )
            session = RecordingSession([])

            with self.assertRaisesRegex(ValueError, "first day of a month"):
                execute_momentum_public_schema_probe(
                    plan,
                    descriptor,
                    session=session,
                    entitlement_present=False,
                )

        self.assertEqual(session.calls, [])

    def test_missing_gate_closed_lifecycle_schema_is_rejected_without_partial_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, descriptor = self._plan_and_descriptor(root)
            response = FakeResponse(
                payload=self._gate_metadata(include_closed_lifecycle=False)
            )
            session = RecordingSession([response])
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=session,
                entitlement_present=False,
                output_path=root / "rejected.json",
                generated_at_utc="2026-07-24T21:00:00+00:00",
            )

        self.assertEqual(result["verdict"], "REJECTED_SOURCE_SCHEMA")
        self.assertIn(
            "GATE_CLOSED_LIFECYCLE_SCHEMA_MISSING",
            result["reason_codes"],
        )
        self.assertEqual(result["network_requests"], 1)
        self.assertFalse(result["history_collect_allowed"])
        self.assertFalse(result["partial_accept"])
        self.assertTrue(response.closed)

    def test_http_failure_is_final_reject_without_partial_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, descriptor = self._plan_and_descriptor(root)
            response = FakeResponse(status_code=401)
            session = RecordingSession([response])
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=session,
                entitlement_present=False,
                output_path=root / "http-rejected.json",
            )

        self.assertEqual(result["verdict"], "REJECTED_SOURCE_SCHEMA")
        self.assertEqual(
            result["reason_codes"],
            ["PUBLIC_SCHEMA_PROBE_NETWORK_OR_TRANSPORT_FAILURE"],
        )
        self.assertEqual(result["network_requests"], 1)
        self.assertFalse(result["partial_accept"])
        self.assertTrue(response.closed)

    def test_missing_derivative_ticker_columns_rejects_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            bad_header = gzip.compress(
                (
                    "exchange,symbol,timestamp,local_timestamp,"
                    "funding_timestamp,mark_price\n"
                ).encode("utf-8")
            )
            session = RecordingSession(
                [
                    FakeResponse(payload=self._gate_metadata()),
                    FakeResponse(body=self._header("trades")),
                    FakeResponse(body=bad_header),
                ]
            )
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=session,
                entitlement_present=False,
            )

        self.assertEqual(result["verdict"], "REJECTED_SOURCE_SCHEMA")
        self.assertEqual(result["reason_codes"], ["DATASET_HEADER_SCHEMA_INVALID"])
        self.assertEqual(result["network_requests"], 3)
        self.assertNotIn("binance_reference", result["dataset_headers"])

    def test_duplicate_gate_dataset_symbol_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            metadata = self._gate_metadata()
            metadata["datasets"]["symbols"][1]["id"] = "BTC_USDT"
            session = RecordingSession([FakeResponse(payload=metadata)])
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=session,
                entitlement_present=False,
            )

        self.assertEqual(result["verdict"], "REJECTED_SOURCE_SCHEMA")
        self.assertEqual(result["reason_codes"], ["DUPLICATE_DATASET_SYMBOL_IDS"])
        self.assertEqual(result["network_requests"], 1)

    def test_inverted_gate_lifecycle_range_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            metadata = self._gate_metadata()
            metadata["datasets"]["symbols"][1]["availableTo"] = (
                "2019-01-01T00:00:00.000Z"
            )
            session = RecordingSession([FakeResponse(payload=metadata)])
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=session,
                entitlement_present=False,
            )

        self.assertEqual(result["verdict"], "REJECTED_SOURCE_SCHEMA")
        self.assertEqual(result["reason_codes"], ["LIFECYCLE_RANGE_INVALID"])
        self.assertEqual(result["network_requests"], 1)

    def test_entitlement_presence_never_sends_or_persists_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            session = RecordingSession(self._success_responses())
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=session,
                entitlement_present=True,
            )

        self.assertEqual(
            result["verdict"],
            "PUBLIC_SCHEMA_ACCEPTED_IDENTITY_PROBE_REQUIRED",
        )
        self.assertEqual(
            result["next_allowed_command"],
            "freeze_authenticated_identity_probe_planonly",
        )
        self.assertTrue(result["archive_entitlement_present"])
        self.assertFalse(result["authorization_header_sent"])
        self.assertFalse(result["credential_value_persisted"])
        self.assertTrue(all(call["headers"] == {} for call in session.calls))

    def test_result_hash_is_stable_across_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            first = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=RecordingSession(self._success_responses()),
                entitlement_present=False,
                generated_at_utc="2026-07-24T21:00:00+00:00",
            )
            second = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=RecordingSession(self._success_responses()),
                entitlement_present=False,
                generated_at_utc="2026-07-24T22:00:00+00:00",
            )

        self.assertEqual(first["artifact_hash"], second["artifact_hash"])
        self.assertNotEqual(first["generated_at_utc"], second["generated_at_utc"])

    def test_probe_result_validator_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            result = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=RecordingSession(self._success_responses()),
                entitlement_present=False,
            )
            validated = validate_momentum_public_probe_result(
                result,
                plan=plan,
                descriptor=descriptor,
            )
            tampered = copy.deepcopy(result)
            tampered["history_collect_allowed"] = True
            self.assertEqual(validated["artifact_hash"], result["artifact_hash"])
            with self.assertRaisesRegex(ValueError, "probe result hash mismatch"):
                validate_momentum_public_probe_result(
                    tampered,
                    plan=plan,
                    descriptor=descriptor,
                )

    def test_rejected_probe_result_is_final_but_cannot_authorize_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, descriptor = self._plan_and_descriptor(Path(tmp))
            rejected = execute_momentum_public_schema_probe(
                plan,
                descriptor,
                session=RecordingSession([FakeResponse(status_code=503)]),
                entitlement_present=False,
            )
            validated = validate_momentum_public_probe_result(
                rejected,
                plan=plan,
                descriptor=descriptor,
            )

        self.assertEqual(validated["verdict"], "REJECTED_SOURCE_SCHEMA")
        self.assertFalse(validated["accepted_for_identity_probe_planonly"])


if __name__ == "__main__":
    unittest.main()
