from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from canonical_asset_registry import (  # noqa: E402
    PLAN_SCHEMA,
    RESULT_SCHEMA,
    MissingCredentialError,
    RegistrySchemaError,
    build_canonical_registry_plan,
    collect_canonical_asset_registry,
    main as registry_main,
    validate_canonical_registry_plan,
    validate_canonical_registry_result,
)


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        content_length: int | None = None,
    ) -> None:
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.status_code = status_code
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
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


def _coin(
    coin_id: str,
    symbol: str,
    name: str,
    *,
    platforms: dict[str, str | None] | None = None,
) -> dict[str, object]:
    return {
        "id": coin_id,
        "symbol": symbol,
        "name": name,
        "platforms": platforms or {},
    }


class CanonicalAssetRegistryTests(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[Path, Path, Path]:
        return root / "plan.json", root / "registry.jsonl", root / "manifest.json"

    def _build_plan(self, root: Path, *, max_response_bytes: int = 1024 * 1024) -> Path:
        plan_path, registry_path, manifest_path = self._paths(root)
        payload = build_canonical_registry_plan(
            registry_path,
            manifest_path,
            frozen_at_utc="2026-07-24T21:00:00+00:00",
            minimum_rows=2,
            max_response_bytes=max_response_bytes,
        )
        plan_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return plan_path

    def test_plan_is_deterministic_and_venue_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, registry_path, manifest_path = self._paths(root)
            first = build_canonical_registry_plan(
                registry_path,
                manifest_path,
                frozen_at_utc="2026-07-24T21:00:00+00:00",
                minimum_rows=2,
            )
            second = build_canonical_registry_plan(
                registry_path,
                manifest_path,
                frozen_at_utc="2026-07-24T21:00:00+00:00",
                minimum_rows=2,
            )

        self.assertEqual(first["schema"], PLAN_SCHEMA)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(first["source"]["statuses"], ["active", "inactive"])
        self.assertTrue(first["source"]["include_platform"])
        self.assertEqual(first["identity"]["canonical_prefix"], "coingecko:")
        self.assertTrue(first["identity"]["preserve_symbol_collisions"])
        self.assertFalse(first["identity"]["exchange_filtering"])
        self.assertFalse(first["data_access_audit"]["market_prices_read"])
        self.assertFalse(first["data_access_audit"]["returns_read"])

    def test_validate_plan_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["minimum_rows"] = 1
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
                validate_canonical_registry_plan(plan_path)

    def test_collect_requires_environment_credential_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            session = RecordingSession([])

            with self.assertRaises(MissingCredentialError):
                collect_canonical_asset_registry(
                    plan_path,
                    environ={},
                    session=session,
                    generated_at_utc="2026-07-24T21:01:00+00:00",
                )

        self.assertEqual(session.calls, [])

    def test_collect_preserves_collisions_and_never_filters_by_exchange(self) -> None:
        active = [
            _coin(
                "alpha-one",
                "same",
                "Alpha One",
                platforms={"ethereum": "0xABC", "solana": None},
            ),
            _coin("zeta", "zeta", "Zeta"),
        ]
        inactive = [_coin("alpha-two", "SAME", "Alpha Two")]
        responses = [FakeResponse(active), FakeResponse(inactive)]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            session = RecordingSession(responses)
            manifest = collect_canonical_asset_registry(
                plan_path,
                environ={"COINGECKO_DEMO_API_KEY": "top-secret"},
                session=session,
                generated_at_utc="2026-07-24T21:01:00+00:00",
            )
            _, registry_path, manifest_path = self._paths(root)
            rows = [
                json.loads(line)
                for line in registry_path.read_text(encoding="utf-8").splitlines()
            ]
            registry_text = registry_path.read_text(encoding="utf-8")
            persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema"], RESULT_SCHEMA)
        self.assertEqual([row["coingecko_id"] for row in rows], ["alpha-one", "alpha-two", "zeta"])
        self.assertEqual([row["status"] for row in rows], ["active", "inactive", "active"])
        self.assertEqual(rows[0]["canonical_asset_id"], "coingecko:alpha-one")
        self.assertEqual(rows[0]["symbol"], "SAME")
        self.assertEqual(rows[0]["platforms"], {"ethereum": "0xabc", "solana": None})
        self.assertEqual(manifest["row_count"], 3)
        self.assertEqual(manifest["symbol_collision_group_count"], 1)
        self.assertEqual(manifest["symbol_collision_asset_count"], 2)
        self.assertEqual(persisted_manifest, manifest)
        self.assertNotIn("top-secret", registry_text)
        self.assertNotIn("top-secret", json.dumps(manifest))
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(
            [call["params"]["status"] for call in session.calls],
            ["active", "inactive"],
        )
        for call in session.calls:
            self.assertEqual(call["params"]["include_platform"], "true")
            self.assertNotIn("top-secret", call["url"])
            self.assertEqual(
                call["headers"]["x-cg-demo-api-key"],
                "top-secret",
            )

    def test_collect_rejects_duplicate_coin_id_across_statuses(self) -> None:
        responses = [
            FakeResponse([_coin("duplicate", "dup", "Active")]),
            FakeResponse([_coin("duplicate", "dup", "Inactive")]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            with self.assertRaisesRegex(RegistrySchemaError, "duplicate CoinGecko id"):
                collect_canonical_asset_registry(
                    plan_path,
                    environ={"COINGECKO_DEMO_API_KEY": "secret"},
                    session=RecordingSession(responses),
                    generated_at_utc="2026-07-24T21:01:00+00:00",
                )

    def test_collect_rejects_malformed_row(self) -> None:
        malformed = [{"id": "broken", "symbol": "", "name": "Broken", "platforms": {}}]
        responses = [FakeResponse(malformed), FakeResponse([_coin("ok", "ok", "OK")])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            with self.assertRaisesRegex(RegistrySchemaError, "invalid symbol"):
                collect_canonical_asset_registry(
                    plan_path,
                    environ={"COINGECKO_DEMO_API_KEY": "secret"},
                    session=RecordingSession(responses),
                    generated_at_utc="2026-07-24T21:01:00+00:00",
                )

    def test_collect_rejects_oversized_response_before_streaming(self) -> None:
        responses = [
            FakeResponse(
                [_coin("too-large", "large", "Large")],
                content_length=10_000,
            ),
            FakeResponse([]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root, max_response_bytes=100)
            with self.assertRaisesRegex(RegistrySchemaError, "response exceeds"):
                collect_canonical_asset_registry(
                    plan_path,
                    environ={"COINGECKO_DEMO_API_KEY": "secret"},
                    session=RecordingSession(responses),
                    generated_at_utc="2026-07-24T21:01:00+00:00",
                )

    def test_collect_is_idempotent_for_identical_immutable_output(self) -> None:
        active = [_coin("one", "one", "One")]
        inactive = [_coin("two", "two", "Two")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            first = collect_canonical_asset_registry(
                plan_path,
                environ={"COINGECKO_DEMO_API_KEY": "secret"},
                session=RecordingSession([FakeResponse(active), FakeResponse(inactive)]),
                generated_at_utc="2026-07-24T21:01:00+00:00",
            )
            second = collect_canonical_asset_registry(
                plan_path,
                environ={"COINGECKO_DEMO_API_KEY": "secret"},
                session=RecordingSession([FakeResponse(active), FakeResponse(inactive)]),
                generated_at_utc="2026-07-24T21:01:00+00:00",
            )

        self.assertEqual(first["artifact_hash"], second["artifact_hash"])
        self.assertEqual(first["registry_sha256"], second["registry_sha256"])

    def test_result_validator_rejects_registry_content_tampering(self) -> None:
        active = [_coin("one", "one", "One")]
        inactive = [_coin("two", "two", "Two")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            collect_canonical_asset_registry(
                plan_path,
                environ={"COINGECKO_DEMO_API_KEY": "secret"},
                session=RecordingSession([FakeResponse(active), FakeResponse(inactive)]),
                generated_at_utc="2026-07-24T21:01:00+00:00",
            )
            _, registry_path, manifest_path = self._paths(root)
            validated = validate_canonical_registry_result(
                manifest_path,
                plan_path=plan_path,
            )
            registry_path.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                validate_canonical_registry_result(
                    manifest_path,
                    plan_path=plan_path,
                )

        self.assertEqual(
            validated["verdict"],
            "CANONICAL_REGISTRY_ACCEPTED_READY_FOR_IDENTITY_PLANONLY",
        )

    def test_cli_collect_cache_and_validate_result_smoke(self) -> None:
        active = [_coin("one", "one", "One")]
        inactive = [_coin("two", "two", "Two")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = self._build_plan(root)
            collect_canonical_asset_registry(
                plan_path,
                environ={"COINGECKO_DEMO_API_KEY": "secret"},
                session=RecordingSession(
                    [FakeResponse(active), FakeResponse(inactive)]
                ),
                generated_at_utc="2026-07-24T21:01:00+00:00",
            )
            _, _, manifest_path = self._paths(root)
            output = StringIO()
            with redirect_stdout(output):
                collect_code = registry_main(
                    ["collect", "--plan", str(plan_path)]
                )
                validate_code = registry_main(
                    [
                        "validate-result",
                        "--plan",
                        str(plan_path),
                        "--result",
                        str(manifest_path),
                    ]
                )

        self.assertEqual(collect_code, 0)
        self.assertEqual(validate_code, 0)
        self.assertIn("CANONICAL_REGISTRY_RESULT_VALID", output.getvalue())


if __name__ == "__main__":
    unittest.main()
