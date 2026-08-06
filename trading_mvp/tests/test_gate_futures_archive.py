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

from gate_futures_archive import (  # noqa: E402
    ARCHIVE_PLAN_SCHEMA,
    DATASETS_BASE_URL,
    EXCHANGE_ID,
    ArchiveEntitlementError,
    GateFuturesArchiveClient,
    assess_archive_actionability,
    build_archive_source_plan,
    build_dataset_url,
    build_schema_probe_descriptor,
    validate_archive_source_plan,
    validate_dataset_header,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _write_source_route(path: Path) -> dict[str, object]:
    route: dict[str, object] = {
        "schema": "trading_mvp_historical_archive_route_planonly_v1",
        "created_at_utc": "2026-07-24T13:25:13+00:00",
        "mode": "PlanOnly",
        "research_only": True,
        "status": "EXTERNAL_SOURCE_PREPARED_AWAIT_ACCESS",
        "immutable_facts": {
            "gate_futures_external_archive_candidate": {
                "provider": "Tardis.dev",
                "exchange": EXCHANGE_ID,
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
            "Create a materially new archive-source hypothesis contract before reading any archive market values.",
            "Perform a bounded schema and symbol-identity probe after an archive entitlement is available.",
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
        "next_allowed_action": (
            "choose_archive_entitlement_or_approve_one_visible_20min_dense_ws_segment"
        ),
    }
    route["plan_hash"] = _sha256_json(route)
    path.write_text(json.dumps(route, ensure_ascii=False, indent=2), encoding="utf-8")
    return route


def _write_recovery_preflight(path: Path, *, survivors: int) -> dict[str, object]:
    minimum = 8
    if survivors < minimum:
        verdict = "INSUFFICIENT_EXECUTABLE_UNIVERSE"
        reason = "MEXC_HISTORY_UPPER_BOUND_LT_MINIMUM_BEFORE_GATE_ARCHIVE"
        next_command = "none_archive_collect_forbidden"
    else:
        verdict = "ARCHIVE_SOURCE_AMENDMENT_PLANONLY_REQUIRED"
        reason = "GATE_ARCHIVE_CAN_BE_PROBED_WITHOUT_CHANGING_FROZEN_STRATEGY"
        next_command = "fast-edge-basis-gate-archive-source-planonly"
    payload: dict[str, object] = {
        "schema": "trading_mvp_gate_archive_recovery_preflight_v1",
        "generated_at_utc": "2026-07-17T00:00:00+00:00",
        "hypothesis_id": "cross_venue_perp_basis_convergence_history_v1",
        "final": True,
        "verdict": verdict,
        "reason_code": reason,
        "minimum_required_assets": minimum,
        "mexc_history_upper_bound_assets": survivors,
        "network_requests": 0,
        "archive_collect_allowed": False,
        "data_access_audit": {
            "returns_read": False,
            "oos_read": False,
            "signals_read": False,
            "pnl_computed": False,
        },
        "safety": {
            "research_only": True,
            "grid_search": False,
            "retune": False,
            "live_orders": False,
            "leverage_or_margin": False,
        },
        "next_allowed_command": next_command,
    }
    payload["artifact_hash"] = _sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "artifact_hash"}
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


class FakeResponse:
    def __init__(
        self,
        *,
        payload: object | None = None,
        body: bytes = b"",
        status_code: int = 200,
    ) -> None:
        self.payload = payload
        self.body = body
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self.payload

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

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        return self.responses.pop(0)


class GateFuturesArchivePlanTests(unittest.TestCase):
    def test_plan_is_hash_bound_deterministic_and_contains_no_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_path = root / "route.json"
            route = _write_source_route(route_path)
            first = build_archive_source_plan(
                route_path,
                frozen_at_utc="2026-07-24T20:00:00+00:00",
            )
            second = build_archive_source_plan(
                route_path,
                frozen_at_utc="2026-07-24T20:01:00+00:00",
            )

        encoded = json.dumps(first, sort_keys=True)
        self.assertEqual(first["schema"], ARCHIVE_PLAN_SCHEMA)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(first["source_route"]["plan_hash"], route["plan_hash"])
        self.assertEqual(first["provider"]["exchange_id"], EXCHANGE_ID)
        self.assertEqual(
            first["provider"]["dataset_types"],
            ["trades", "derivative_ticker"],
        )
        self.assertNotIn("super-secret", encoded)
        self.assertFalse(first["data_access_audit"]["market_rows_read"])
        self.assertFalse(first["data_access_audit"]["network_access"])
        self.assertFalse(first["safety"]["oos"])
        self.assertFalse(first["safety"]["strategy_evaluation"])
        self.assertTrue(first["safety"]["materially_new_hypothesis_required"])
        self.assertEqual(
            first["next_allowed_command"],
            "gate_futures_archive_binding_audit",
        )
        self.assertEqual(
            validate_archive_source_plan(first)["plan_hash"],
            first["plan_hash"],
        )

    def test_parent_or_plan_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_path = root / "route.json"
            _write_source_route(route_path)
            plan = build_archive_source_plan(route_path)

            tampered = copy.deepcopy(plan)
            tampered["runtime"]["schema_probe_max_runtime_sec"] = 301
            with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
                validate_archive_source_plan(tampered)

            route = json.loads(route_path.read_text(encoding="utf-8"))
            route["status"] = "TAMPERED"
            route_path.write_text(json.dumps(route), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source route hash mismatch"):
                validate_archive_source_plan(plan, source_route_path=route_path)

    def test_schema_probe_descriptor_is_bounded_and_non_evaluating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            route_path = Path(tmp) / "route.json"
            _write_source_route(route_path)
            plan = build_archive_source_plan(route_path)
            descriptor = build_schema_probe_descriptor(
                plan,
                symbol="BTC_USDT",
                sample_date="2020-07-01",
                max_runtime_sec=120,
            )

        self.assertEqual(descriptor["request_count"], 3)
        self.assertEqual(descriptor["runtime"]["max_runtime_sec"], 120)
        self.assertTrue(descriptor["sample_only_without_entitlement"])
        self.assertFalse(descriptor["data_access_audit"]["market_values_read"])
        self.assertFalse(descriptor["data_access_audit"]["returns_read"])
        self.assertFalse(descriptor["data_access_audit"]["pnl_computed"])
        self.assertNotIn("Authorization", json.dumps(descriptor, sort_keys=True))
        with self.assertRaisesRegex(ValueError, "must be <= 300"):
            build_schema_probe_descriptor(
                plan,
                symbol="BTC_USDT",
                sample_date="2020-07-01",
                max_runtime_sec=301,
            )

    def test_binding_audit_rejects_frozen_basis_before_network_at_seven_of_eight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_path = root / "route.json"
            preflight_path = root / "recovery.json"
            _write_source_route(route_path)
            _write_recovery_preflight(preflight_path, survivors=7)
            plan = build_archive_source_plan(route_path)
            result = assess_archive_actionability(plan, preflight_path)

        self.assertEqual(
            result["verdict"],
            "ARCHIVE_NOT_ACTIONABLE_FOR_FROZEN_BASIS",
        )
        self.assertEqual(result["mexc_history_upper_bound_assets"], 7)
        self.assertEqual(result["minimum_required_assets"], 8)
        self.assertFalse(result["archive_schema_probe_allowed_for_frozen_basis"])
        self.assertEqual(result["network_requests"], 0)
        self.assertFalse(result["data_access_audit"]["returns_read"])
        self.assertFalse(result["data_access_audit"]["pnl_computed"])
        self.assertEqual(
            result["next_allowed_command"],
            "none_frozen_basis_branch_remains_closed",
        )

    def test_binding_audit_allows_only_schema_probe_at_eight_of_eight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_path = root / "route.json"
            preflight_path = root / "recovery.json"
            _write_source_route(route_path)
            _write_recovery_preflight(preflight_path, survivors=8)
            plan = build_archive_source_plan(route_path)
            result = assess_archive_actionability(plan, preflight_path)

        self.assertEqual(
            result["verdict"],
            "ARCHIVE_SCHEMA_PROBE_PERMITTED_FOR_FROZEN_BASIS",
        )
        self.assertTrue(result["archive_schema_probe_allowed_for_frozen_basis"])
        self.assertFalse(result["edge_evaluated"])
        self.assertEqual(
            result["next_allowed_command"],
            "visible_gate_futures_archive_schema_probe",
        )

    def test_binding_audit_rejects_tampered_recovery_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_path = root / "route.json"
            preflight_path = root / "recovery.json"
            _write_source_route(route_path)
            _write_recovery_preflight(preflight_path, survivors=7)
            plan = build_archive_source_plan(route_path)
            payload = json.loads(preflight_path.read_text(encoding="utf-8"))
            payload["mexc_history_upper_bound_assets"] = 8
            preflight_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "recovery preflight hash mismatch"):
                assess_archive_actionability(plan, preflight_path)


class GateFuturesArchiveHttpTests(unittest.TestCase):
    def test_dataset_url_and_headers_are_strict(self) -> None:
        self.assertEqual(
            build_dataset_url("derivative_ticker", "2020-07-01", "BTC_USDT"),
            (
                f"{DATASETS_BASE_URL}/{EXCHANGE_ID}/derivative_ticker/"
                "2020/07/01/BTC_USDT.csv.gz"
            ),
        )
        with self.assertRaisesRegex(ValueError, "unsupported dataset type"):
            build_dataset_url("liquidations", "2020-07-01", "BTC_USDT")
        with self.assertRaisesRegex(ValueError, "invalid Gate futures symbol"):
            build_dataset_url("trades", "2020-07-01", "../../secret")
        with self.assertRaisesRegex(ValueError, "invalid dataset date"):
            build_dataset_url("trades", "2020-07-02T00:00:00Z", "BTC_USDT")

        validate_dataset_header(
            "trades",
            "exchange,symbol,timestamp,local_timestamp,id,side,price,amount",
        )
        validate_dataset_header(
            "derivative_ticker",
            (
                "exchange,symbol,timestamp,local_timestamp,funding_timestamp,"
                "funding_rate,predicted_funding_rate,open_interest,last_price,"
                "index_price,mark_price"
            ),
        )
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            validate_dataset_header(
                "derivative_ticker",
                "exchange,symbol,timestamp,local_timestamp,mark_price",
            )

    def test_client_uses_env_secret_but_never_exposes_it(self) -> None:
        secret = "super-secret-entitlement"
        metadata = {
            "id": EXCHANGE_ID,
            "supportsDatasets": True,
            "datasets": {"symbols": []},
        }
        body = gzip.compress(
            (
                "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
                "gate-io-futures,BTC_USDT,1,2,abc,buy,100,1\n"
            ).encode("utf-8")
        )
        metadata_response = FakeResponse(payload=metadata)
        dataset_response = FakeResponse(body=body)
        session = RecordingSession([metadata_response, dataset_response])
        client = GateFuturesArchiveClient(
            session=session,
            environ={"TARDIS_API_KEY": secret},
        )

        self.assertEqual(client.fetch_exchange_metadata()["id"], EXCHANGE_ID)
        header = client.fetch_dataset_header(
            "trades",
            "2020-07-02",
            "BTC_USDT",
            require_entitlement=True,
        )

        self.assertEqual(header[-2:], ["price", "amount"])
        self.assertEqual(
            session.calls[0]["headers"],
            {"Authorization": f"Bearer {secret}"},
        )
        self.assertEqual(
            session.calls[1]["headers"],
            {"Authorization": f"Bearer {secret}"},
        )
        self.assertNotIn(secret, repr(client))
        self.assertNotIn(secret, json.dumps(client.audit_metadata(), sort_keys=True))
        self.assertTrue(metadata_response.closed)
        self.assertTrue(dataset_response.closed)

    def test_missing_entitlement_fails_before_network(self) -> None:
        session = RecordingSession([])
        client = GateFuturesArchiveClient(session=session, environ={})

        with self.assertRaisesRegex(ArchiveEntitlementError, "TARDIS_API_KEY"):
            client.fetch_dataset_header(
                "trades",
                "2020-07-02",
                "BTC_USDT",
                require_entitlement=True,
            )
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
