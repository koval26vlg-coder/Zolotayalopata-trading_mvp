from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_public_cache as cache_module  # noqa: E402
import paper_public_reader as reader_module  # noqa: E402
import paper_public_reader_contract as contract_module  # noqa: E402


def _contract(root: Path) -> dict:
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
    return contract_module.build_public_reader_contract(
        funding_client_path=funding,
        observer_runtime_path=observer,
        reliability_evidence_path=evidence,
        generated_at_utc="2026-07-28T20:30:00+00:00",
    )


def _snapshot(contract: dict, now_ms: int) -> dict:
    reader = reader_module.FixturePublicMarketReader(
        contract,
        reader_module.FixturePublicGetTransport(
            reader_module._valid_fixture_outcomes(now_ms)
        ),
    )
    return reader.read_market_snapshot(
        venue="mexc",
        symbol="HYPE_USDT",
        canonical_base="hype",
        observer_received_ts_ms=now_ms,
    )


class PaperPublicCacheTests(unittest.TestCase):
    NOW_MS = 1_800_000_000_000

    def test_put_get_and_idempotent_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            cache = cache_module.ContentAddressedPublicSnapshotCache(
                root=root / "cache", contract=contract
            )
            snapshot = _snapshot(contract, self.NOW_MS)
            first = cache.put(
                snapshot, ttl_sec=60, now_ms=self.NOW_MS
            )
            second = cache.put(
                snapshot, ttl_sec=60, now_ms=self.NOW_MS
            )
            lookup = cache.get(
                venue="mexc",
                symbol="HYPE_USDT",
                canonical_base="hype",
                now_ms=self.NOW_MS + 1000,
            )
            object_count = len(list((root / "cache" / "objects").glob("*.json")))
        self.assertEqual(first["status"], "STORED")
        self.assertEqual(second["status"], "IDEMPOTENT_REUSE")
        self.assertEqual(first["object_sha256"], second["object_sha256"])
        self.assertEqual(lookup.status, "HIT")
        self.assertEqual(object_count, 1)

    def test_ttl_expiry_is_a_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            cache = cache_module.ContentAddressedPublicSnapshotCache(
                root=root / "cache", contract=contract
            )
            cache.put(
                _snapshot(contract, self.NOW_MS),
                ttl_sec=5,
                now_ms=self.NOW_MS,
            )
            lookup = cache.get(
                venue="mexc",
                symbol="HYPE_USDT",
                canonical_base="hype",
                now_ms=self.NOW_MS + 5000,
            )
        self.assertEqual((lookup.status, lookup.reason), ("MISS", "EXPIRED"))

    def test_contract_hash_drift_forbids_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            cache_root = root / "cache"
            cache = cache_module.ContentAddressedPublicSnapshotCache(
                root=cache_root, contract=contract
            )
            cache.put(
                _snapshot(contract, self.NOW_MS),
                ttl_sec=60,
                now_ms=self.NOW_MS,
            )
            drifted = copy.deepcopy(contract)
            drifted["source_provenance"][0]["sha256"] = "f" * 64
            drifted["contract_hash_sha256"] = contract_module.contract_hash(
                drifted
            )
            drifted_cache = (
                cache_module.ContentAddressedPublicSnapshotCache(
                    root=cache_root, contract=drifted
                )
            )
            lookup = drifted_cache.get(
                venue="mexc",
                symbol="HYPE_USDT",
                canonical_base="hype",
                now_ms=self.NOW_MS + 1000,
            )
        self.assertEqual(
            (lookup.status, lookup.reason), ("MISS", "HASH_DRIFT")
        )

    def test_snapshot_hash_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            snapshot = _snapshot(contract, self.NOW_MS)
            snapshot["best_bid"] = 1.0
            cache = cache_module.ContentAddressedPublicSnapshotCache(
                root=root / "cache", contract=contract
            )
            with self.assertRaisesRegex(
                cache_module.CacheIntegrityError, "semantic hash"
            ):
                cache.put(snapshot, ttl_sec=60, now_ms=self.NOW_MS)

    def test_index_and_object_corruption_fail_closed(self) -> None:
        for corrupt_target in ("index", "object"):
            with self.subTest(corrupt_target=corrupt_target):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    contract = _contract(root)
                    cache = cache_module.ContentAddressedPublicSnapshotCache(
                        root=root / "cache", contract=contract
                    )
                    stored = cache.put(
                        _snapshot(contract, self.NOW_MS),
                        ttl_sec=60,
                        now_ms=self.NOW_MS,
                    )
                    path = (
                        Path(stored["index_path"])
                        if corrupt_target == "index"
                        else Path(stored["object_path"])
                    )
                    path.write_text("{broken", encoding="utf-8")
                    with self.assertRaises(
                        cache_module.CacheIntegrityError
                    ):
                        cache.get(
                            venue="mexc",
                            symbol="HYPE_USDT",
                            canonical_base="hype",
                            now_ms=self.NOW_MS + 1000,
                        )

    def test_writer_lock_blocks_second_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            cache = cache_module.ContentAddressedPublicSnapshotCache(
                root=root / "cache", contract=contract
            )
            identity = cache._identity(
                venue="mexc",
                symbol="HYPE_USDT",
                canonical_base="hype",
            )
            with cache._writer_lock(identity):
                with self.assertRaises(cache_module.CacheBusyError):
                    cache.put(
                        _snapshot(contract, self.NOW_MS),
                        ttl_sec=60,
                        now_ms=self.NOW_MS,
                    )

    def test_invalid_ttl_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            cache = cache_module.ContentAddressedPublicSnapshotCache(
                root=root / "cache", contract=contract
            )
            snapshot = _snapshot(contract, self.NOW_MS)
            for ttl in (0, -1, cache_module.MAX_TTL_SEC + 1):
                with self.subTest(ttl=ttl):
                    with self.assertRaisesRegex(ValueError, "ttl_sec"):
                        cache.put(
                            snapshot, ttl_sec=ttl, now_ms=self.NOW_MS
                        )

    def test_report_proves_atomic_idempotent_hash_bound_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = cache_module.build_cache_validation_report(
                contract_path=contract_path,
                generated_at_utc="2026-07-28T20:35:00+00:00",
            )
        self.assertEqual(
            report["verdict"],
            "CONTENT_ADDRESSED_CACHE_IDEMPOTENT_AND_HASH_BOUND",
        )
        self.assertEqual(report["second_put_status"], "IDEMPOTENT_REUSE")
        self.assertEqual(report["valid_lookup"]["status"], "HIT")
        self.assertEqual(report["expired_lookup"]["reason"], "EXPIRED")
        self.assertEqual(report["drift_lookup"]["reason"], "HASH_DRIFT")
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["temporary_file_count_after_write"], 0)
        self.assertEqual(report["writer_lock_count_after_write"], 0)

    def test_transport_output_round_trips_through_cache_without_network(
        self,
    ) -> None:
        wiring = Path(
            r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
            r"\paper-public-reader-transport-wiring-fixture-v1.json"
        )
        if not wiring.is_file():
            self.skipTest("transport wiring fixture is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _contract(root)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract), encoding="utf-8"
            )
            report = (
                cache_module.build_cache_transport_integration_fixture_report(
                    contract_path=contract_path,
                    transport_wiring_path=wiring,
                    generated_at_utc="2026-07-29T05:17:00+00:00",
                )
            )
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["oms_mutations"], 0)
        self.assertEqual(report["cache"]["lookup_status"], "HIT")
        self.assertEqual(
            report["snapshot_hash_sha256"],
            report["replay_snapshot_hash_sha256"],
        )
        self.assertEqual(
            report["verdict"],
            "FIXTURE_PUBLIC_CACHE_TRANSPORT_INTEGRATION_ACCEPTED_NO_NETWORK",
        )


if __name__ == "__main__":
    unittest.main()
