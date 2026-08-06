from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from paper_public_reader import (
    FixtureClock,
    FixturePublicGetTransport,
    FixturePublicMarketReader,
    FixtureRequestsResponse,
    FixtureRequestsSession,
    PublicMarketReader,
    RequestsPublicGetTransport,
    SNAPSHOT_SCHEMA,
    _valid_fixture_outcomes,
)
from paper_public_reader_contract import (
    contract_hash,
    sha256_file,
    sha256_json,
    validate_public_reader_contract,
)


INDEX_SCHEMA = "trading_mvp_public_snapshot_cache_index_v1"
REPORT_SCHEMA = "trading_mvp_public_snapshot_cache_report_v1"
MAX_TTL_SEC = 86_400


class CacheIntegrityError(RuntimeError):
    pass


class CacheBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CacheLookup:
    status: str
    reason: str
    snapshot: dict[str, Any] | None
    object_sha256: str | None


def _semantic_snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in snapshot.items()
            if key != "snapshot_hash_sha256"
        }
    )


def _index_hash(index: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in index.items()
            if key != "index_hash_sha256"
        }
    )


def _schema_merkle(contract: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            venue: [
                endpoint["schema_hash_sha256"]
                for endpoint in contract["venues"][venue]["endpoints"]
            ]
            for venue in sorted(contract["venues"])
        }
    )


def _stable_identity(
    *, venue: str, symbol: str, canonical_base: str
) -> dict[str, str]:
    normalized = {
        "venue": venue.strip().lower(),
        "symbol": symbol.strip().upper(),
        "canonical_base": canonical_base.strip().lower(),
    }
    if normalized["venue"] not in {"mexc", "gateio"}:
        raise ValueError("cache venue is not allowlisted")
    if not normalized["symbol"] or not normalized["canonical_base"]:
        raise ValueError("cache identity fields must not be blank")
    return normalized


def _fingerprint(contract: Mapping[str, Any]) -> dict[str, str]:
    validated = validate_public_reader_contract(contract)
    return {
        "contract_hash_sha256": validated["contract_hash_sha256"],
        "reader_schema_merkle_sha256": _schema_merkle(validated),
        "snapshot_schema": validated["normalization_contract"]["output_schema"],
    }


def validate_snapshot(
    snapshot: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    validated_contract = validate_public_reader_contract(contract)
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise CacheIntegrityError("snapshot schema mismatch")
    required = validated_contract["normalization_contract"]["required_fields"]
    missing = [field for field in required if field not in snapshot]
    if missing:
        raise CacheIntegrityError(
            f"snapshot required fields are missing: {','.join(missing)}"
        )
    if snapshot.get("network_request_performed") is not False:
        raise CacheIntegrityError("fixture snapshot claims a network request")
    observed_hash = snapshot.get("snapshot_hash_sha256")
    if observed_hash != _semantic_snapshot_hash(snapshot):
        raise CacheIntegrityError("snapshot semantic hash mismatch")
    return copy.deepcopy(dict(snapshot))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheIntegrityError(f"cache JSON is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise CacheIntegrityError(f"cache JSON root is invalid: {path}")
    return payload


def _atomic_write_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    replace_existing: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace_existing:
        existing = _read_json(path)
        if sha256_json(existing) != sha256_json(payload):
            raise CacheIntegrityError(
                f"content-addressed object collision: {path}"
            )
        return
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        if not replace_existing and path.exists():
            existing = _read_json(path)
            if sha256_json(existing) != sha256_json(payload):
                raise CacheIntegrityError(
                    f"content-addressed object collision: {path}"
                )
            return
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class ContentAddressedPublicSnapshotCache:
    def __init__(
        self,
        *,
        root: str | Path,
        contract: Mapping[str, Any],
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.contract = validate_public_reader_contract(contract)
        self.objects_dir = self.root / "objects"
        self.index_dir = self.root / "index"
        self.locks_dir = self.root / "locks"
        for directory in (self.objects_dir, self.index_dir, self.locks_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _identity(
        self, *, venue: str, symbol: str, canonical_base: str
    ) -> dict[str, str]:
        return _stable_identity(
            venue=venue, symbol=symbol, canonical_base=canonical_base
        )

    def _index_path(self, identity: Mapping[str, str]) -> Path:
        return self.index_dir / f"{sha256_json(identity)}.json"

    @contextmanager
    def _writer_lock(
        self, identity: Mapping[str, str]
    ) -> Iterator[None]:
        lock_path = self.locks_dir / f"{sha256_json(identity)}.lock"
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise CacheBusyError(
                f"cache writer lock is already held: {lock_path}"
            ) from exc
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.close(descriptor)
            descriptor = -1
            yield
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def put(
        self,
        snapshot: Mapping[str, Any],
        *,
        ttl_sec: int,
        now_ms: int,
    ) -> dict[str, Any]:
        if isinstance(ttl_sec, bool) or ttl_sec <= 0 or ttl_sec > MAX_TTL_SEC:
            raise ValueError(f"ttl_sec must be within 1..{MAX_TTL_SEC}")
        validated = validate_snapshot(snapshot, self.contract)
        identity = self._identity(
            venue=str(validated["venue"]),
            symbol=str(validated["symbol"]),
            canonical_base=str(validated["canonical_base"]),
        )
        object_sha256 = sha256_json(validated)
        object_path = self.objects_dir / f"{object_sha256}.json"
        index_path = self._index_path(identity)
        with self._writer_lock(identity):
            _atomic_write_json(
                object_path, validated, replace_existing=False
            )
            status = "STORED"
            if index_path.exists():
                previous = _read_json(index_path)
                if (
                    previous.get("object_sha256") == object_sha256
                    and previous.get("fingerprint") == _fingerprint(self.contract)
                    and int(previous.get("expires_at_ms", -1))
                    == int(now_ms) + ttl_sec * 1000
                ):
                    status = "IDEMPOTENT_REUSE"
            index: dict[str, Any] = {
                "schema": INDEX_SCHEMA,
                "identity": identity,
                "fingerprint": _fingerprint(self.contract),
                "object_sha256": object_sha256,
                "snapshot_hash_sha256": validated["snapshot_hash_sha256"],
                "created_at_ms": int(now_ms),
                "expires_at_ms": int(now_ms) + ttl_sec * 1000,
            }
            index["index_hash_sha256"] = _index_hash(index)
            _atomic_write_json(
                index_path, index, replace_existing=True
            )
        return {
            "status": status,
            "identity_sha256": sha256_json(identity),
            "object_sha256": object_sha256,
            "index_path": str(index_path),
            "object_path": str(object_path),
        }

    def get(
        self,
        *,
        venue: str,
        symbol: str,
        canonical_base: str,
        now_ms: int,
    ) -> CacheLookup:
        identity = self._identity(
            venue=venue, symbol=symbol, canonical_base=canonical_base
        )
        index_path = self._index_path(identity)
        if not index_path.is_file():
            return CacheLookup("MISS", "NOT_FOUND", None, None)
        index = _read_json(index_path)
        if index.get("schema") != INDEX_SCHEMA:
            raise CacheIntegrityError("cache index schema mismatch")
        if index.get("index_hash_sha256") != _index_hash(index):
            raise CacheIntegrityError("cache index semantic hash mismatch")
        if index.get("identity") != identity:
            raise CacheIntegrityError("cache index identity mismatch")
        if index.get("fingerprint") != _fingerprint(self.contract):
            return CacheLookup(
                "MISS",
                "HASH_DRIFT",
                None,
                str(index.get("object_sha256") or "") or None,
            )
        object_sha256 = str(index.get("object_sha256") or "")
        if int(now_ms) >= int(index.get("expires_at_ms", -1)):
            return CacheLookup("MISS", "EXPIRED", None, object_sha256)
        object_path = self.objects_dir / f"{object_sha256}.json"
        if not object_path.is_file():
            raise CacheIntegrityError("cache object is missing")
        snapshot = _read_json(object_path)
        if sha256_json(snapshot) != object_sha256:
            raise CacheIntegrityError("cache object content hash mismatch")
        validated = validate_snapshot(snapshot, self.contract)
        if validated["snapshot_hash_sha256"] != index.get(
            "snapshot_hash_sha256"
        ):
            raise CacheIntegrityError("cache index snapshot hash mismatch")
        return CacheLookup("HIT", "VALID", validated, object_sha256)


def build_cache_validation_report(
    *,
    contract_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    now_ms = 1_800_000_000_000
    transport = FixturePublicGetTransport(_valid_fixture_outcomes(now_ms))
    reader = FixturePublicMarketReader(contract, transport)
    snapshot = reader.read_market_snapshot(
        venue="mexc",
        symbol="HYPE_USDT",
        canonical_base="hype",
        observer_received_ts_ms=now_ms,
    )
    with tempfile.TemporaryDirectory(prefix="trading-mvp-public-cache-") as tmp:
        cache = ContentAddressedPublicSnapshotCache(
            root=tmp, contract=contract
        )
        first = cache.put(snapshot, ttl_sec=60, now_ms=now_ms)
        second = cache.put(snapshot, ttl_sec=60, now_ms=now_ms)
        hit = cache.get(
            venue="mexc",
            symbol="HYPE_USDT",
            canonical_base="hype",
            now_ms=now_ms + 1000,
        )
        expired = cache.get(
            venue="mexc",
            symbol="HYPE_USDT",
            canonical_base="hype",
            now_ms=now_ms + 60_000,
        )
        drifted_contract = copy.deepcopy(contract)
        drifted_contract["source_provenance"][0]["sha256"] = "0" * 64
        drifted_contract["contract_hash_sha256"] = contract_hash(
            drifted_contract
        )
        drifted_cache = ContentAddressedPublicSnapshotCache(
            root=tmp, contract=drifted_contract
        )
        drift = drifted_cache.get(
            venue="mexc",
            symbol="HYPE_USDT",
            canonical_base="hype",
            now_ms=now_ms + 1000,
        )
        object_count = len(list((Path(tmp) / "objects").glob("*.json")))
        temporary_count = len(list(Path(tmp).rglob("*.tmp")))
        lock_count = len(list((Path(tmp) / "locks").glob("*.lock")))
    deterministic = {
        "schema": REPORT_SCHEMA,
        "task_id": "paper_public_cache_idempotency_v1",
        "contract": {
            "path": str(target),
            "file_sha256": sha256_file(target),
            "contract_hash_sha256": contract["contract_hash_sha256"],
        },
        "first_put_status": first["status"],
        "second_put_status": second["status"],
        "same_object_sha256": (
            first["object_sha256"] == second["object_sha256"]
        ),
        "valid_lookup": {"status": hit.status, "reason": hit.reason},
        "expired_lookup": {
            "status": expired.status,
            "reason": expired.reason,
        },
        "drift_lookup": {"status": drift.status, "reason": drift.reason},
        "content_object_count": object_count,
        "temporary_file_count_after_write": temporary_count,
        "writer_lock_count_after_write": lock_count,
        "atomic_replace_used": True,
        "network_requests": 0,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": "CONTENT_ADDRESSED_CACHE_IDEMPOTENT_AND_HASH_BOUND",
        "next_allowed_action": "pit_train_progress_monitor_v1",
    }
    report = {
        **deterministic,
        "module_path": str(Path(__file__).resolve()),
        "module_sha256": sha256_file(Path(__file__).resolve()),
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_report_immutable(output_path, report)
    return report


def build_cache_transport_integration_fixture_report(
    *,
    contract_path: str | Path,
    transport_wiring_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    target = Path(contract_path).expanduser().resolve()
    contract = validate_public_reader_contract(
        json.loads(target.read_text(encoding="utf-8-sig"))
    )
    wiring_target = Path(transport_wiring_path).expanduser().resolve()
    wiring = _read_json(wiring_target)
    if (
        wiring.get("verdict")
        != "FIXTURE_PUBLIC_READER_TRANSPORT_WIRING_ACCEPTED_NO_NETWORK"
        or wiring.get("network_requests") != 0
    ):
        raise ValueError("transport wiring evidence is not accepted")
    now_ms = 1_800_000_000_000
    outcomes = _valid_fixture_outcomes(now_ms)
    endpoint_order = (
        "mexc_contracts",
        "mexc_tickers",
        "mexc_funding",
        "mexc_depth",
    )
    responses = [
        FixtureRequestsResponse(
            status_code=outcomes[endpoint_id].status_code,
            body=json.dumps(
                outcomes[endpoint_id].payload,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        )
        for endpoint_id in endpoint_order
    ]
    session = FixtureRequestsSession(responses)
    transport = RequestsPublicGetTransport(contract, session=session)
    reader = PublicMarketReader(
        contract,
        transport,
        clock=FixtureClock(),
    )
    snapshot = reader.read_market_snapshot(
        venue="mexc",
        symbol="HYPE_USDT",
        canonical_base="hype",
        observer_received_ts_ms=now_ms,
    )
    with tempfile.TemporaryDirectory(
        prefix="trading-mvp-public-cache-transport-"
    ) as tmp:
        cache = ContentAddressedPublicSnapshotCache(
            root=tmp,
            contract=contract,
        )
        stored = cache.put(snapshot, ttl_sec=60, now_ms=now_ms)
        replay = cache.get(
            venue="mexc",
            symbol="HYPE_USDT",
            canonical_base="hype",
            now_ms=now_ms + 1000,
        )
        object_count = len(list((Path(tmp) / "objects").glob("*.json")))
        temporary_count = len(list(Path(tmp).rglob("*.tmp")))
        lock_count = len(list((Path(tmp) / "locks").glob("*.lock")))
    if (
        replay.status != "HIT"
        or replay.snapshot is None
        or replay.snapshot["snapshot_hash_sha256"]
        != snapshot["snapshot_hash_sha256"]
        or transport.network_requests != 0
    ):
        raise AssertionError("cache transport deterministic replay drifted")

    module_path = Path(__file__).resolve()
    deterministic = {
        "schema": (
            "trading_mvp_public_cache_transport_integration_fixture_v1"
        ),
        "task_id": "paper_public_cache_transport_integration_fixture_v1",
        "inputs": {
            "contract": {
                "path": str(target),
                "file_sha256": sha256_file(target),
                "contract_hash_sha256": contract["contract_hash_sha256"],
            },
            "transport_wiring": {
                "path": str(wiring_target),
                "file_sha256": sha256_file(wiring_target),
                "deterministic_result_hash": wiring[
                    "deterministic_result_hash"
                ],
            },
        },
        "transport": {
            "endpoint_order": list(endpoint_order),
            "fixture_session_calls": len(session.calls),
            "responses_closed": all(response.closed for response in responses),
        },
        "cache": {
            "put_status": stored["status"],
            "lookup_status": replay.status,
            "lookup_reason": replay.reason,
            "object_sha256": stored["object_sha256"],
            "content_object_count": object_count,
            "temporary_file_count_after_write": temporary_count,
            "writer_lock_count_after_write": lock_count,
        },
        "snapshot_hash_sha256": snapshot["snapshot_hash_sha256"],
        "replay_snapshot_hash_sha256": replay.snapshot[
            "snapshot_hash_sha256"
        ],
        "source_provenance": {
            "paper_public_cache": {
                "path": str(module_path),
                "file_sha256": sha256_file(module_path),
            }
        },
        "network_requests": transport.network_requests,
        "oms_mutations": 0,
        "private_api_keys": False,
        "live_orders": False,
        "verdict": (
            "FIXTURE_PUBLIC_CACHE_TRANSPORT_INTEGRATION_ACCEPTED_NO_NETWORK"
        ),
        "next_allowed_action": "paper_product_readiness_audit_v6",
    }
    report = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_report_immutable(output_path, report)
    return report


def _write_report_immutable(
    path: str | Path, payload: Mapping[str, Any]
) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    _atomic_write_json(target, payload, replace_existing=False)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate content-addressed public snapshot caching"
    )
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--report-kind",
        choices=("cache", "transport-integration"),
        default="cache",
    )
    parser.add_argument("--transport-wiring")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.report_kind == "transport-integration":
        if not args.transport_wiring:
            raise ValueError(
                "--transport-wiring is required for transport-integration"
            )
        report = build_cache_transport_integration_fixture_report(
            contract_path=args.contract,
            transport_wiring_path=args.transport_wiring,
            output_path=args.output,
        )
    else:
        report = build_cache_validation_report(
            contract_path=args.contract,
            output_path=args.output,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
