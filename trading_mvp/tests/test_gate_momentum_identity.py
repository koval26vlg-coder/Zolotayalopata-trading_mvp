from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for candidate in (SRC, TESTS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from canonical_asset_registry import (  # noqa: E402
    build_canonical_registry_plan,
    collect_canonical_asset_registry,
)
from gate_futures_archive import build_archive_source_plan  # noqa: E402
from gate_momentum_archive import (  # noqa: E402
    build_momentum_archive_plan,
    build_momentum_public_probe_descriptor,
    execute_momentum_public_schema_probe,
)
from gate_momentum_identity import (  # noqa: E402
    IDENTITY_PLAN_SCHEMA,
    IDENTITY_RESULT_SCHEMA,
    IdentityCredentialError,
    build_gate_momentum_identity_plan,
    collect_gate_momentum_identity_metadata,
    main as identity_main,
    sha256_json,
    validate_gate_momentum_identity_plan,
    validate_gate_momentum_identity_result,
)
import test_gate_momentum_archive as probe_fixtures  # noqa: E402


class JsonResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192) -> object:
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index : index + chunk_size]

    def __enter__(self) -> "JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class JsonSession:
    def __init__(self, payloads: list[object]) -> None:
        self.responses = [JsonResponse(payload) for payload in payloads]
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> JsonResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


class GateMomentumIdentityPlanTests(unittest.TestCase):
    def _fixture_paths(self, root: Path) -> dict[str, Path]:
        return {
            "route": root / "route.json",
            "archive_plan": root / "archive-plan.json",
            "closure": root / "closure.json",
            "momentum_plan": root / "momentum-plan.json",
            "descriptor": root / "public-descriptor.json",
            "public_result": root / "public-result.json",
            "registry_plan": root / "registry-plan.json",
            "registry": root / "registry.jsonl",
            "registry_manifest": root / "registry-manifest.json",
            "identity_plan": root / "identity-plan.json",
            "gate_instruments": root / "gate-instruments.jsonl",
            "binance_instruments": root / "binance-instruments.jsonl",
            "identity_result": root / "identity-result.json",
        }

    def _build_fixture(
        self,
        root: Path,
        *,
        registry_count: int = 3,
    ) -> dict[str, Path]:
        paths = self._fixture_paths(root)
        probe_fixtures._write_source_route(paths["route"])
        build_archive_source_plan(
            paths["route"],
            paths["archive_plan"],
            frozen_at_utc="2026-07-24T20:00:00+00:00",
        )
        probe_fixtures._write_source_closure(paths["closure"])
        momentum_plan = build_momentum_archive_plan(
            paths["archive_plan"],
            paths["closure"],
            frozen_at_utc="2026-07-24T20:10:00+00:00",
        )
        _write_json(paths["momentum_plan"], momentum_plan)
        descriptor = build_momentum_public_probe_descriptor(
            momentum_plan,
            sample_date="2020-07-01",
            max_runtime_sec=120,
        )
        _write_json(paths["descriptor"], descriptor)
        probe_helper = probe_fixtures.GateMomentumPublicSchemaProbeTests()
        execute_momentum_public_schema_probe(
            momentum_plan,
            descriptor,
            paths["public_result"],
            session=probe_fixtures.RecordingSession(probe_helper._success_responses()),
            entitlement_present=False,
            generated_at_utc="2026-07-24T20:20:00+00:00",
        )

        registry_plan = build_canonical_registry_plan(
            paths["registry"],
            paths["registry_manifest"],
            frozen_at_utc="2026-07-24T20:30:00+00:00",
            minimum_rows=registry_count,
        )
        _write_json(paths["registry_plan"], registry_plan)
        active = [
            {
                "id": f"asset-{index:03d}",
                "symbol": f"asset{index:03d}",
                "name": f"Asset {index:03d}",
                "platforms": {},
            }
            for index in range(registry_count)
        ]
        collect_canonical_asset_registry(
            paths["registry_plan"],
            environ={"COINGECKO_DEMO_API_KEY": "registry-secret"},
            session=JsonSession([active, []]),
            generated_at_utc="2026-07-24T20:31:00+00:00",
        )
        return paths

    def _build_identity_plan(self, paths: dict[str, Path]) -> dict[str, object]:
        return build_gate_momentum_identity_plan(
            paths["momentum_plan"],
            paths["descriptor"],
            paths["public_result"],
            paths["registry_plan"],
            paths["registry_manifest"],
            gate_instruments_output_path=paths["gate_instruments"],
            binance_instruments_output_path=paths["binance_instruments"],
            identity_result_output_path=paths["identity_result"],
            frozen_at_utc="2026-07-24T20:40:00+00:00",
        )

    def test_plan_is_deterministic_hash_bound_and_non_evaluating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._build_fixture(Path(tmp))
            first = self._build_identity_plan(paths)
            second = self._build_identity_plan(paths)

        self.assertEqual(first["schema"], IDENTITY_PLAN_SCHEMA)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(first["credential"]["environment_variable"], "TARDIS_API_KEY")
        self.assertFalse(first["credential"]["value_persisted"])
        self.assertEqual(
            [request["exchange"] for request in first["requests"]],
            ["gate-io-futures", "binance"],
        )
        self.assertEqual(
            first["requests"][0]["filter"],
            {"quoteCurrency": "USDT", "type": "perpetual"},
        )
        self.assertEqual(first["requests"][1]["filter"], {"type": "spot"})
        self.assertEqual(
            first["identity"]["gate_required_contract_type"],
            "linear_perpetual",
        )
        self.assertEqual(
            first["identity"]["mapping_rule"],
            "unique_coingecko_symbol_only",
        )
        self.assertTrue(first["identity"]["exclude_symbol_collisions"])
        self.assertTrue(first["identity"]["binance_exclusion_is_point_in_time"])
        self.assertFalse(first["data_access_audit"]["returns_read"])
        self.assertFalse(first["data_access_audit"]["pnl_read"])
        self.assertFalse(first["safety"]["history_collect"])
        self.assertFalse(first["safety"]["oos"])
        self.assertNotIn("registry-secret", json.dumps(first))

    def test_validator_accepts_untampered_frozen_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._build_fixture(Path(tmp))
            plan = self._build_identity_plan(paths)
            _write_json(paths["identity_plan"], plan)
            validated = validate_gate_momentum_identity_plan(paths["identity_plan"])

        self.assertEqual(validated["plan_hash"], plan["plan_hash"])
        self.assertEqual(
            validated["next_allowed_command"],
            "gate-momentum-identity-metadata-collect-visible",
        )

    def test_rejected_public_schema_result_cannot_authorize_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._build_fixture(Path(tmp))
            result = json.loads(paths["public_result"].read_text(encoding="utf-8"))
            result["verdict"] = "REJECTED_SOURCE_SCHEMA"
            _write_json(paths["public_result"], result)

            with self.assertRaisesRegex(ValueError, "probe result hash mismatch"):
                self._build_identity_plan(paths)

    def test_registry_content_mutation_fails_before_identity_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._build_fixture(Path(tmp))
            paths["registry"].write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                self._build_identity_plan(paths)

    def test_upstream_result_mutation_after_freeze_invalidates_identity_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._build_fixture(Path(tmp))
            plan = self._build_identity_plan(paths)
            _write_json(paths["identity_plan"], plan)
            result = json.loads(paths["public_result"].read_text(encoding="utf-8"))
            result["network_requests"] = 3
            _write_json(paths["public_result"], result)

            with self.assertRaisesRegex(ValueError, "public probe result file hash mismatch"):
                validate_gate_momentum_identity_plan(paths["identity_plan"])

    def test_identity_plan_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._build_fixture(Path(tmp))
            plan = self._build_identity_plan(paths)
            tampered = copy.deepcopy(plan)
            tampered["identity"]["exclude_symbol_collisions"] = False
            _write_json(paths["identity_plan"], tampered)

            with self.assertRaisesRegex(ValueError, "identity plan hash mismatch"):
                validate_gate_momentum_identity_plan(paths["identity_plan"])

    def test_rehashed_subscription_downgrade_fails_semantic_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._build_fixture(Path(tmp))
            plan = self._build_identity_plan(paths)
            plan["credential"]["minimum_subscription"] = "Solo"
            plan["plan_hash"] = sha256_json(
                {key: value for key, value in plan.items() if key != "plan_hash"}
            )
            _write_json(paths["identity_plan"], plan)

            with self.assertRaisesRegex(ValueError, "credential contract mismatch"):
                validate_gate_momentum_identity_plan(paths["identity_plan"])


class GateMomentumIdentityCollectorTests(unittest.TestCase):
    @staticmethod
    def _gate_instruments(count: int = 20) -> list[dict[str, object]]:
        return [
            {
                "id": f"ASSET{index:03d}_USDT",
                "datasetId": f"ASSET{index:03d}_USDT",
                "exchange": "gate-io-futures",
                "baseCurrency": f"ASSET{index:03d}",
                "quoteCurrency": "USDT",
                "type": "perpetual",
                "active": True,
                "availableSince": "2024-01-01T00:00:00.000Z",
                "availableTo": (
                    "2026-01-01T00:00:00.000Z" if index == 19 else None
                ),
                "contractType": "linear_perpetual",
                "makerFee": -0.001,
                "takerFee": 0.02,
            }
            for index in range(count)
        ]

    @staticmethod
    def _binance_instruments() -> list[dict[str, object]]:
        return [
            {
                "id": f"ASSET{index:03d}{'BTC' if index == 4 else 'USDT'}",
                "datasetId": f"ASSET{index:03d}{'BTC' if index == 4 else 'USDT'}",
                "exchange": "binance",
                "baseCurrency": f"ASSET{index:03d}",
                "quoteCurrency": "BTC" if index == 4 else "USDT",
                "type": "spot",
                "active": index != 3,
                "availableSince": "2024-03-01T00:00:00.000Z",
                "availableTo": (
                    "2025-12-01T00:00:00.000Z" if index == 3 else None
                ),
            }
            for index in range(5)
        ]

    def _ready_identity_plan(self, root: Path) -> tuple[dict[str, Path], dict[str, object]]:
        fixture = GateMomentumIdentityPlanTests()
        paths = fixture._build_fixture(root, registry_count=22)
        plan = fixture._build_identity_plan(paths)
        _write_json(paths["identity_plan"], plan)
        return paths, plan

    def test_collect_requires_tardis_credential_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, _ = self._ready_identity_plan(Path(tmp))
            session = JsonSession([])
            with self.assertRaises(IdentityCredentialError):
                collect_gate_momentum_identity_metadata(
                    paths["identity_plan"],
                    environ={},
                    session=session,
                    generated_at_utc="2026-07-24T20:50:00+00:00",
                )

        self.assertEqual(session.calls, [])

    def test_collect_maps_unique_assets_and_preserves_lifecycle_without_fee_fields(self) -> None:
        secret = "tardis-secret"
        with tempfile.TemporaryDirectory() as tmp:
            paths, _ = self._ready_identity_plan(Path(tmp))
            session = JsonSession(
                [self._gate_instruments(), self._binance_instruments()]
            )
            result = collect_gate_momentum_identity_metadata(
                paths["identity_plan"],
                environ={"TARDIS_API_KEY": secret},
                session=session,
                generated_at_utc="2026-07-24T20:50:00+00:00",
            )
            gate_rows = [
                json.loads(line)
                for line in paths["gate_instruments"].read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            binance_rows = [
                json.loads(line)
                for line in paths["binance_instruments"].read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            persisted = json.loads(
                paths["identity_result"].read_text(encoding="utf-8")
            )

        self.assertEqual(result["schema"], IDENTITY_RESULT_SCHEMA)
        self.assertEqual(result["verdict"], "IDENTITY_ACCEPTED_READY_FOR_HISTORY_PLANONLY")
        self.assertTrue(result["accepted_for_history_planonly"])
        self.assertFalse(result["history_collect_allowed"])
        self.assertEqual(result["canonical_gate_asset_count"], 20)
        self.assertEqual(result["canonical_binance_asset_count"], 5)
        self.assertEqual(len(gate_rows), 20)
        self.assertEqual(len(binance_rows), 5)
        self.assertEqual(gate_rows[0]["canonical_asset_id"], "coingecko:asset-000")
        self.assertEqual(gate_rows[19]["available_to"], "2026-01-01T00:00:00+00:00")
        self.assertNotIn("makerFee", gate_rows[0])
        self.assertNotIn("takerFee", gate_rows[0])
        self.assertEqual(persisted, result)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, json.dumps(gate_rows))
        self.assertEqual(len(session.calls), 2)
        for call in session.calls:
            self.assertEqual(call["headers"]["Authorization"], f"Bearer {secret}")
            self.assertNotIn(secret, call["url"])
        self.assertEqual(
            json.loads(session.calls[0]["params"]["filter"]),
            {"quoteCurrency": "USDT", "type": "perpetual"},
        )
        self.assertEqual(
            json.loads(session.calls[1]["params"]["filter"]),
            {"type": "spot"},
        )

    def test_insufficient_canonical_gate_universe_is_final_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, _ = self._ready_identity_plan(Path(tmp))
            result = collect_gate_momentum_identity_metadata(
                paths["identity_plan"],
                environ={"TARDIS_API_KEY": "secret"},
                session=JsonSession(
                    [self._gate_instruments(19), self._binance_instruments()]
                ),
                generated_at_utc="2026-07-24T20:50:00+00:00",
            )

        self.assertEqual(result["verdict"], "INSUFFICIENT_CANONICAL_IDENTITY_UNIVERSE")
        self.assertFalse(result["accepted_for_history_planonly"])
        self.assertIn("CANONICAL_GATE_ASSET_COUNT_BELOW_20", result["reason_codes"])

    def test_duplicate_exchange_instrument_id_rejects_schema(self) -> None:
        gate = self._gate_instruments()
        gate.append(dict(gate[0]))
        with tempfile.TemporaryDirectory() as tmp:
            paths, _ = self._ready_identity_plan(Path(tmp))
            result = collect_gate_momentum_identity_metadata(
                paths["identity_plan"],
                environ={"TARDIS_API_KEY": "secret"},
                session=JsonSession([gate, self._binance_instruments()]),
                generated_at_utc="2026-07-24T20:50:00+00:00",
            )

        self.assertEqual(result["verdict"], "REJECTED_IDENTITY_SCHEMA")
        self.assertFalse(result["accepted_for_history_planonly"])
        self.assertIn("DUPLICATE_INSTRUMENT_ID", result["reason_codes"])

    def test_result_validator_rejects_persisted_result_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, _ = self._ready_identity_plan(Path(tmp))
            collect_gate_momentum_identity_metadata(
                paths["identity_plan"],
                environ={"TARDIS_API_KEY": "secret"},
                session=JsonSession(
                    [self._gate_instruments(), self._binance_instruments()]
                ),
                generated_at_utc="2026-07-24T20:50:00+00:00",
            )
            validated = validate_gate_momentum_identity_result(
                paths["identity_result"],
                plan_path=paths["identity_plan"],
            )
            result = json.loads(
                paths["identity_result"].read_text(encoding="utf-8")
            )
            result["canonical_gate_asset_count"] = 19
            _write_json(paths["identity_result"], result)

            with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                validate_gate_momentum_identity_result(
                    paths["identity_result"],
                    plan_path=paths["identity_plan"],
                )

        self.assertTrue(validated["accepted_for_history_planonly"])

    def test_cli_collect_cache_and_validate_result_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, _ = self._ready_identity_plan(Path(tmp))
            collect_gate_momentum_identity_metadata(
                paths["identity_plan"],
                environ={"TARDIS_API_KEY": "secret"},
                session=JsonSession(
                    [self._gate_instruments(), self._binance_instruments()]
                ),
                generated_at_utc="2026-07-24T20:50:00+00:00",
            )
            output = StringIO()
            with redirect_stdout(output):
                collect_code = identity_main(
                    ["collect", "--plan", str(paths["identity_plan"])]
                )
                validate_code = identity_main(
                    [
                        "validate-result",
                        "--plan",
                        str(paths["identity_plan"]),
                        "--result",
                        str(paths["identity_result"]),
                    ]
                )

        self.assertEqual(collect_code, 0)
        self.assertEqual(validate_code, 0)
        self.assertIn("IDENTITY_ACCEPTED_READY_FOR_HISTORY_PLANONLY", output.getvalue())


if __name__ == "__main__":
    unittest.main()
