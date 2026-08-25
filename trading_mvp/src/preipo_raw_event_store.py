"""Append-only raw event store for public pre-IPO observations."""

from __future__ import annotations

import hashlib
import json
import math
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


STORE_SCHEMA = "trading_mvp_preipo_raw_event_store_v1"
VALID_VENUES = {"okx", "gate", "bitmex", "kraken"}


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key not in {"event_id", "stored_at_utc", "causal_status"}}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if abs(parsed) >= 10_000_000_000:
        parsed /= 1000.0
    return parsed if parsed > 0 and math.isfinite(parsed) else None


class CausalOrderTracker:
    """Classify stale/out-of-order updates without deleting raw evidence."""

    def __init__(self) -> None:
        self._last: dict[
            tuple[str, str, str],
            tuple[float, tuple[str, Decimal | str]],
        ] = {}

    @staticmethod
    def _sequence(value: Any) -> tuple[str, Decimal | str]:
        if value in (None, "") or isinstance(value, bool):
            return ("missing", "")
        text = str(value).strip()
        try:
            number = Decimal(text)
        except (InvalidOperation, ValueError):
            return ("text", text)
        if not number.is_finite():
            return ("text", text)
        return ("number", number)

    @staticmethod
    def _sequence_is_older(
        current: tuple[str, Decimal | str],
        previous: tuple[str, Decimal | str],
    ) -> bool:
        current_kind, current_value = current
        previous_kind, previous_value = previous
        if current_kind == "missing" or previous_kind == "missing":
            return False
        if current_kind != previous_kind:
            return False
        return current_value < previous_value

    def classify(self, event: Mapping[str, Any]) -> str:
        key = (str(event["venue"]), str(event["contract_id"]), str(event["event_kind"]))
        exchange_ts = _timestamp(event.get("exchange_ts")) or _timestamp(event.get("received_ts"))
        if exchange_ts is None:
            return "missing_timestamp"
        sequence = self._sequence(event.get("sequence"))
        previous = self._last.get(key)
        if previous is None:
            self._last[key] = (exchange_ts, sequence)
            return "accepted"
        previous_ts, previous_sequence = previous
        if exchange_ts < previous_ts or (
            exchange_ts == previous_ts
            and self._sequence_is_older(sequence, previous_sequence)
        ):
            return "stale"
        if (
            exchange_ts == previous_ts
            and sequence[0] != "missing"
            and previous_sequence[0] != "missing"
            and sequence == previous_sequence
        ):
            return "duplicate"
        self._last[key] = (exchange_ts, sequence)
        return "accepted"


class RawEventStore:
    """Append JSONL rows and publish a hash-bound manifest.

    Rows are never rewritten or compacted.  Exact duplicates are skipped by
    deterministic event hash, while stale/out-of-order rows remain preserved
    with ``causal_status=stale`` for later audit.
    """

    def __init__(self, events_path: str | Path, manifest_path: str | Path | None = None) -> None:
        self.events_path = Path(events_path)
        self.manifest_path = Path(manifest_path) if manifest_path is not None else self.events_path.with_name("manifest.json")
        self._known_ids: set[str] = set()
        self._tracker = CausalOrderTracker()
        if self.events_path.exists():
            for row in self.iter_events():
                event_id = str(row.get("event_id") or "")
                if event_id:
                    self._known_ids.add(event_id)
                self._tracker.classify(row)

    def _validate(self, event: Mapping[str, Any]) -> None:
        venue = str(event.get("venue") or "").strip().lower()
        if venue == "gateio":
            venue = "gate"
        if venue not in VALID_VENUES:
            raise ValueError(f"unsupported pre-IPO venue: {venue}")
        for key in ("contract_id", "event_kind"):
            if not str(event.get(key) or "").strip():
                raise ValueError(f"raw event missing {key}")
        if _timestamp(event.get("exchange_ts")) is None and _timestamp(event.get("received_ts")) is None:
            raise ValueError("raw event requires exchange_ts or received_ts")

    def append(self, events: Iterable[Mapping[str, Any]]) -> dict[str, int]:
        rows: list[dict[str, Any]] = []
        duplicates = 0
        for raw in events:
            event = dict(raw)
            self._validate(event)
            event["venue"] = "gate" if str(event["venue"]).lower() == "gateio" else str(event["venue"]).lower()
            computed_id = _canonical_hash(event)
            supplied_id = event.get("event_id")
            if supplied_id not in (None, "") and str(supplied_id) != computed_id:
                raise ValueError("event_id does not match canonical event payload")
            event["event_id"] = computed_id
            if computed_id in self._known_ids:
                duplicates += 1
                continue
            event["causal_status"] = self._tracker.classify(event)
            event["stored_at_utc"] = _utc_iso()
            rows.append(event)
            self._known_ids.add(computed_id)
        if rows:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return {"written": len(rows), "duplicates": duplicates, "stale": sum(row["causal_status"] == "stale" for row in rows)}

    def iter_events(self) -> Iterator[dict[str, Any]]:
        if not self.events_path.exists():
            return
        with self.events_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise ValueError(f"invalid raw event JSON at line {line_number}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"raw event at line {line_number} is not an object")
                yield row

    def manifest(self) -> dict[str, Any]:
        digest = hashlib.sha256()
        byte_count = 0
        row_count = 0
        if self.events_path.exists():
            with self.events_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    byte_count += len(chunk)
            row_count = sum(1 for _ in self.iter_events())
        return {
            "schema": STORE_SCHEMA,
            "events_path": str(self.events_path),
            "events_sha256": digest.hexdigest() if byte_count else None,
            "events_bytes": byte_count,
            "row_count": row_count,
            "generated_at_utc": _utc_iso(),
            "append_only": True,
            "public_data_only": True,
            "private_api": False,
            "live_orders": False,
        }

    def write_manifest(self) -> dict[str, Any]:
        payload = self.manifest()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.manifest_path.with_name(f"{self.manifest_path.name}.tmp.{os.getpid()}")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.manifest_path)
        return payload
