from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import os
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

try:
    from dense_ws_campaign_contract import (
        PLAN_SCHEMA,
        sha256_file,
        validate_contract,
        validate_plan,
    )
    from dense_ws_campaign_quality import QUALITY_SCHEMA
    from ws_normalizer import normalize_ws_row
except ModuleNotFoundError:  # pragma: no cover - package import path
    from .dense_ws_campaign_contract import (
        PLAN_SCHEMA,
        sha256_file,
        validate_contract,
        validate_plan,
    )
    from .dense_ws_campaign_quality import QUALITY_SCHEMA
    from .ws_normalizer import normalize_ws_row


MATERIALIZATION_SCHEMA = "trading_mvp_dense_ws_causal_materialization_v1"
LABEL_SCHEMA = "trading_mvp_dense_ws_regime_label_v1"
SNAPSHOT_SCHEMA = "trading_mvp_dense_ws_execution_snapshot_v1"


class CausalMaterializationIntegrityError(ValueError):
    """A frozen identity, hash, ordering, or namespace binding changed."""


class CausalMaterializationRuntimeError(TimeoutError):
    """The bounded local materialization exceeded its approved runtime."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _deterministic_hash(payload: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key != "deterministic_result_hash"
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CausalMaterializationIntegrityError(
            f"invalid JSON object: {target}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise CausalMaterializationIntegrityError(
            f"expected JSON object: {target}"
        )
    return value


def _check_deadline(deadline_monotonic: float) -> None:
    if time.monotonic() >= deadline_monotonic:
        raise CausalMaterializationRuntimeError(
            "causal materialization exceeded max_runtime_sec"
        )


def _sha256_file_checked(
    path: str | Path,
    *,
    deadline_check: Callable[[], None],
) -> str:
    target = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            deadline_check()
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    deadline_check()
    return digest.hexdigest()


def _finite(value: Any, *, label: str, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise CausalMaterializationIntegrityError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CausalMaterializationIntegrityError(
            f"{label} must be numeric"
        ) from exc
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise CausalMaterializationIntegrityError(f"{label} is invalid")
    return number


def _assert_exact(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise CausalMaterializationIntegrityError(
            f"{label} mismatch: expected={expected!r} observed={actual!r}"
        )


def _assert_inside(path: Path, root: Path, *, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CausalMaterializationIntegrityError(
            f"{label} escapes campaign root: {path}"
        ) from exc


def _as_sequence(value: Any, *, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise CausalMaterializationIntegrityError(f"{label} must be a sequence")
    return value


def _base_symbol(symbol: Any) -> str | None:
    value = str(symbol or "").strip().upper().replace("/", "_")
    if value.endswith("_USDT"):
        return value[:-5]
    if value.endswith("USDT"):
        return value[:-4]
    return None


def _quantile_type_7(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile population is empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@dataclass(frozen=True)
class Quote:
    recv_ts: float
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float

    @property
    def spread_bps(self) -> float:
        mid = (self.bid_price + self.ask_price) / 2.0
        return (self.ask_price - self.bid_price) / mid * 10_000.0

    @property
    def top_notional_quote(self) -> float:
        return min(
            self.bid_price * self.bid_qty,
            self.ask_price * self.ask_qty,
        )

    @property
    def signature(self) -> tuple[float, float, float, float]:
        return (
            self.bid_price,
            self.bid_qty,
            self.ask_price,
            self.ask_qty,
        )


@dataclass(frozen=True)
class ScheduledObservation:
    sample_ts: int
    fresh: bool
    spread_bps: float | None
    top_notional_quote: float | None


class CausalMaterializer:
    def __init__(
        self,
        *,
        bases: Sequence[str],
        regime_contract: Mapping[str, Any],
        execution_contract: Mapping[str, Any],
    ) -> None:
        self.bases = tuple(sorted({str(item).strip().upper() for item in bases}))
        if not self.bases:
            raise CausalMaterializationIntegrityError("matched base set is empty")
        self.venues = ("mexc", "gateio")
        self.grid_sec = int(regime_contract["observation_grid_sec"])
        self.label_interval_sec = int(regime_contract["label_interval_sec"])
        self.warmup_sec = int(regime_contract["warmup_sec"])
        self.reference_sec = int(regime_contract["trailing_reference_window_sec"])
        self.current_sec = int(regime_contract["current_feature_window_sec"])
        self.minimum_reference = int(
            regime_contract["minimum_reference_observations_per_venue_base"]
        )
        self.dense_rule = dict(regime_contract["venue_dense_rule"])
        self.maximum_age_ms = {
            str(key): float(value)
            for key, value in execution_contract["max_quote_age_ms"].items()
        }
        self.maximum_skew_ms = float(
            execution_contract["max_cross_venue_recv_ts_skew_ms"]
        )
        self.maximum_spread_bps = float(
            execution_contract["max_spread_bps_each_venue"]
        )
        self.minimum_top_notional = float(
            execution_contract["min_top_notional_quote_each_side"]
        )
        if self.grid_sec <= 0 or self.label_interval_sec % self.grid_sec:
            raise CausalMaterializationIntegrityError(
                "observation and label clocks are incompatible"
            )
        if self.reference_sec % 60 or self.current_sec % 60:
            raise CausalMaterializationIntegrityError(
                "feature windows must contain complete UTC minutes"
            )

        self.latest: dict[tuple[str, str], Quote] = {}
        self.last_signature: dict[
            tuple[str, str], tuple[float, float, float, float]
        ] = {}
        self.observations: dict[
            tuple[str, str], deque[ScheduledObservation]
        ] = defaultdict(deque)
        self.update_times: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.active_labels: dict[str, str] = {}
        self.warmup_started_at: int | None = None
        self.last_event_ts: float | None = None
        self.labels_written = 0
        self.snapshots_written = 0
        self.snapshot_exclusions: Counter[str] = Counter()
        self.label_counts: Counter[str] = Counter()

    def _event_quote(self, event: Mapping[str, Any]) -> tuple[str, str, Quote]:
        venue = str(event.get("exchange") or "").strip().lower()
        base = _base_symbol(event.get("symbol"))
        if venue not in self.venues or base not in self.bases:
            raise CausalMaterializationIntegrityError(
                f"BBO event is outside frozen venue/base scope: {venue}:{base}"
            )
        quote = Quote(
            recv_ts=_finite(event.get("recv_ts"), label="recv_ts"),
            bid_price=_finite(
                event.get("bid_price"), label="bid_price", positive=True
            ),
            bid_qty=_finite(event.get("bid_qty"), label="bid_qty", positive=True),
            ask_price=_finite(
                event.get("ask_price"), label="ask_price", positive=True
            ),
            ask_qty=_finite(event.get("ask_qty"), label="ask_qty", positive=True),
        )
        if quote.ask_price < quote.bid_price:
            raise CausalMaterializationIntegrityError("crossed BBO is invalid")
        return venue, base, quote

    def observe_event(self, event: Mapping[str, Any]) -> None:
        if str(event.get("event_kind") or "") != "bbo":
            return
        venue, base, quote = self._event_quote(event)
        if self.last_event_ts is not None and quote.recv_ts < self.last_event_ts:
            raise CausalMaterializationIntegrityError(
                "normalized BBO stream is not globally ordered"
            )
        self.last_event_ts = quote.recv_ts
        key = (venue, base)
        if self.last_signature.get(key) != quote.signature:
            self.update_times[key].append(quote.recv_ts)
            self.last_signature[key] = quote.signature
        self.latest[key] = quote

    def _prune(self, sample_ts: int) -> None:
        oldest = sample_ts - self.reference_sec
        for history in self.observations.values():
            while history and history[0].sample_ts < oldest:
                history.popleft()
        for updates in self.update_times.values():
            while updates and updates[0] < oldest:
                updates.popleft()

    def _scheduled_observation(
        self,
        venue: str,
        base: str,
        sample_ts: int,
    ) -> ScheduledObservation:
        quote = self.latest.get((venue, base))
        if quote is None or quote.recv_ts > sample_ts:
            return ScheduledObservation(sample_ts, False, None, None)
        age_ms = (sample_ts - quote.recv_ts) * 1_000.0
        fresh = 0.0 <= age_ms <= self.maximum_age_ms[venue]
        return ScheduledObservation(
            sample_ts,
            fresh,
            quote.spread_bps if fresh else None,
            quote.top_notional_quote if fresh else None,
        )

    def _venue_features(
        self,
        venue: str,
        base: str,
        label_ts: int,
    ) -> dict[str, Any]:
        key = (venue, base)
        history = self.observations[key]
        reference_start = label_ts - self.reference_sec
        current_start = label_ts - self.current_sec
        reference = [
            item
            for item in history
            if reference_start <= item.sample_ts < label_ts and item.fresh
        ]
        current = [
            item
            for item in history
            if current_start <= item.sample_ts < label_ts and item.fresh
        ]
        expected_current = self.current_sec // self.grid_sec
        fresh_ratio = len(current) / expected_current
        if len(reference) < self.minimum_reference:
            return {
                "ready": False,
                "dense": False,
                "fresh_sample_ratio": fresh_ratio,
                "reference_observations": len(reference),
                "reason": "reference_observations",
            }
        if fresh_ratio < float(self.dense_rule["fresh_sample_ratio_min"]):
            return {
                "ready": True,
                "dense": False,
                "fresh_sample_ratio": fresh_ratio,
                "reference_observations": len(reference),
                "reason": "fresh_sample_ratio",
            }

        reference_spreads = [float(item.spread_bps) for item in reference]
        reference_top = [float(item.top_notional_quote) for item in reference]
        current_spreads = [float(item.spread_bps) for item in current]
        current_top = [float(item.top_notional_quote) for item in current]
        current_updates = sum(
            1 for value in self.update_times[key] if current_start <= value < label_ts
        )
        current_update_rate = current_updates / (self.current_sec / 60.0)
        reference_minute_rates: list[float] = []
        reference_updates = self.update_times[key]
        for minute_start in range(reference_start, label_ts, 60):
            count = sum(
                1
                for value in reference_updates
                if minute_start <= value < minute_start + 60
            )
            reference_minute_rates.append(float(count))

        current_median_spread = _quantile_type_7(current_spreads, 0.50)
        reference_spread_q40 = _quantile_type_7(reference_spreads, 0.40)
        current_top_p25 = _quantile_type_7(current_top, 0.25)
        reference_top_q60 = _quantile_type_7(reference_top, 0.60)
        reference_update_q60 = _quantile_type_7(reference_minute_rates, 0.60)
        checks = {
            "spread": current_median_spread <= reference_spread_q40,
            "top_notional": current_top_p25 >= reference_top_q60,
            "update_rate": current_update_rate >= reference_update_q60,
        }
        return {
            "ready": True,
            "dense": all(checks.values()),
            "fresh_sample_ratio": fresh_ratio,
            "reference_observations": len(reference),
            "current_median_spread_bps": current_median_spread,
            "reference_spread_q40_bps": reference_spread_q40,
            "current_p25_top_notional_quote": current_top_p25,
            "reference_top_notional_q60_quote": reference_top_q60,
            "current_quote_updates_per_minute": current_update_rate,
            "reference_quote_updates_per_minute_q60": reference_update_q60,
            "checks": checks,
            "reason": None if all(checks.values()) else "dense_rule",
        }

    def emit_label(self, label_ts: int) -> dict[str, Any]:
        by_base: dict[str, Any] = {}
        warmup_complete = (
            self.warmup_started_at is not None
            and label_ts - self.warmup_started_at >= self.warmup_sec
        )
        for base in self.bases:
            venue_features = {
                venue: self._venue_features(venue, base, label_ts)
                for venue in self.venues
            }
            if not warmup_complete or any(
                not item["ready"] for item in venue_features.values()
            ):
                label = "WARMUP_INVALID"
            elif any(
                item["fresh_sample_ratio"]
                < float(self.dense_rule["fresh_sample_ratio_min"])
                for item in venue_features.values()
            ):
                label = "STALE_OR_INCOMPLETE"
            else:
                mexc_dense = bool(venue_features["mexc"]["dense"])
                gate_dense = bool(venue_features["gateio"]["dense"])
                if mexc_dense and gate_dense:
                    label = "DENSE_BOTH"
                elif mexc_dense:
                    label = "DENSE_MEXC_ONLY"
                elif gate_dense:
                    label = "DENSE_GATE_ONLY"
                else:
                    label = "NON_DENSE_BOTH"
            self.active_labels[base] = label
            self.label_counts[label] += 1
            by_base[base] = {
                "schema": LABEL_SCHEMA,
                "label_ts": label_ts,
                "label_effective_ts": label_ts,
                "base": base,
                "label": label,
                "venues": venue_features,
            }
        self.labels_written += len(by_base)
        return by_base

    def _snapshot(self, base: str, sample_ts: int) -> dict[str, Any] | None:
        if self.active_labels.get(base) != "DENSE_BOTH":
            self.snapshot_exclusions["regime"] += 1
            return None
        quotes: dict[str, Quote] = {}
        for venue in self.venues:
            quote = self.latest.get((venue, base))
            if quote is None:
                self.snapshot_exclusions[f"missing:{venue}"] += 1
                return None
            age_ms = (sample_ts - quote.recv_ts) * 1_000.0
            if age_ms < 0.0 or age_ms > self.maximum_age_ms[venue]:
                self.snapshot_exclusions[f"stale:{venue}"] += 1
                return None
            if quote.spread_bps > self.maximum_spread_bps:
                self.snapshot_exclusions[f"spread:{venue}"] += 1
                return None
            if quote.top_notional_quote < self.minimum_top_notional:
                self.snapshot_exclusions[f"top_notional:{venue}"] += 1
                return None
            quotes[venue] = quote
        skew_ms = abs(quotes["mexc"].recv_ts - quotes["gateio"].recv_ts) * 1_000.0
        if skew_ms > self.maximum_skew_ms:
            self.snapshot_exclusions["cross_venue_skew"] += 1
            return None
        self.snapshots_written += 1
        return {
            "schema": SNAPSHOT_SCHEMA,
            "sample_ts": sample_ts,
            "base": base,
            "regime_label": "DENSE_BOTH",
            "cross_venue_recv_ts_skew_ms": skew_ms,
            "venues": {
                venue: {
                    "recv_ts": quote.recv_ts,
                    "quote_age_ms": (sample_ts - quote.recv_ts) * 1_000.0,
                    "bid_price": quote.bid_price,
                    "bid_qty": quote.bid_qty,
                    "ask_price": quote.ask_price,
                    "ask_qty": quote.ask_qty,
                    "spread_bps": quote.spread_bps,
                    "top_notional_quote": quote.top_notional_quote,
                }
                for venue, quote in sorted(quotes.items())
            },
        }

    def process_segment(
        self,
        events: Iterable[Mapping[str, Any]],
        *,
        start_ts: float,
        end_ts: float,
        label_sink: Callable[[Mapping[str, Any]], None],
        snapshot_sink: Callable[[Mapping[str, Any]], None],
        deadline_check: Callable[[], None] | None = None,
    ) -> None:
        check_deadline = deadline_check or (lambda: None)
        first_sample = int(math.ceil(start_ts / self.grid_sec) * self.grid_sec)
        last_sample = int(math.floor(end_ts / self.grid_sec) * self.grid_sec)
        if self.warmup_started_at is None and first_sample <= last_sample:
            self.warmup_started_at = first_sample
        iterator = iter(events)
        pending = next(iterator, None)
        for sample_ts in range(first_sample, last_sample + 1, self.grid_sec):
            check_deadline()
            while pending is not None:
                check_deadline()
                event_ts = _finite(pending.get("recv_ts"), label="event.recv_ts")
                if event_ts > sample_ts:
                    break
                if event_ts >= start_ts:
                    self.observe_event(pending)
                pending = next(iterator, None)
            self._prune(sample_ts)
            if sample_ts % self.label_interval_sec == 0:
                for row in self.emit_label(sample_ts).values():
                    label_sink(row)
            for venue in self.venues:
                for base in self.bases:
                    self.observations[(venue, base)].append(
                        self._scheduled_observation(venue, base, sample_ts)
                    )
            for base in self.bases:
                snapshot = self._snapshot(base, sample_ts)
                if snapshot is not None:
                    snapshot_sink(snapshot)
        while pending is not None:
            check_deadline()
            pending_ts = _finite(pending.get("recv_ts"), label="event.recv_ts")
            if pending_ts > end_ts:
                break
            if pending_ts >= start_ts:
                self.observe_event(pending)
            pending = next(iterator, None)


def materialize_normalized_bbo_events(
    events: Iterable[Mapping[str, Any]],
    *,
    bases: Sequence[str],
    start_ts: float,
    end_ts: float,
    regime_contract: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
) -> dict[str, Any]:
    labels: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    engine = CausalMaterializer(
        bases=bases,
        regime_contract=regime_contract,
        execution_contract=execution_contract,
    )
    engine.process_segment(
        events,
        start_ts=start_ts,
        end_ts=end_ts,
        label_sink=lambda row: labels.append(dict(row)),
        snapshot_sink=lambda row: snapshots.append(dict(row)),
    )
    return {
        "labels": labels,
        "snapshots": snapshots,
        "label_counts": dict(sorted(engine.label_counts.items())),
        "snapshot_exclusions": dict(sorted(engine.snapshot_exclusions.items())),
    }


def _validated_quality(
    quality: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    _assert_exact(quality.get("schema"), QUALITY_SCHEMA, label="quality.schema")
    _assert_exact(quality.get("campaign_id"), plan["campaign_id"], label="campaign_id")
    _assert_exact(quality.get("plan_hash"), plan["plan_hash"], label="plan_hash")
    _assert_exact(
        quality.get("contract_hash"), contract["contract_hash"], label="contract_hash"
    )
    _assert_exact(quality.get("accepted"), True, label="quality.accepted")
    _assert_exact(
        quality.get("decision"),
        "DATA_READY_FOR_TRAIN_ONLY_REVIEW",
        label="quality.decision",
    )
    _assert_exact(
        quality.get("deterministic_result_hash"),
        _deterministic_hash(quality),
        label="quality deterministic_result_hash",
    )
    safety = quality.get("safety")
    if not isinstance(safety, Mapping):
        raise CausalMaterializationIntegrityError("quality safety flags are missing")
    for key in (
        "network_access",
        "returns_read",
        "pnl_computed",
        "oos_read",
        "grid_or_retune",
        "paper_forward",
        "live_orders",
        "private_api_keys",
        "real_capital",
        "leverage_or_margin",
    ):
        _assert_exact(safety.get(key), False, label=f"quality.safety.{key}")


def _raw_bbo_stream(
    binding: Mapping[str, Any],
    *,
    deadline_check: Callable[[], None],
) -> Iterator[dict[str, Any]]:
    path = Path(str(binding.get("path") or "")).expanduser().resolve()
    _assert_exact(
        _sha256_file_checked(path, deadline_check=deadline_check),
        binding.get("sha256"),
        label=f"raw hash {path}",
    )
    prior_ts: float | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            deadline_check()
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                normalized = normalize_ws_row(raw)
            except Exception as exc:
                raise CausalMaterializationIntegrityError(
                    f"raw normalization failed: {path}:{line_number}: {exc}"
                ) from exc
            for event in normalized:
                if event.get("event_kind") != "bbo":
                    continue
                event_ts = _finite(event.get("recv_ts"), label="normalized recv_ts")
                if prior_ts is not None and event_ts < prior_ts:
                    raise CausalMaterializationIntegrityError(
                        f"raw BBO file is not ordered: {path}:{line_number}"
                    )
                prior_ts = event_ts
                yield dict(event)


def _merge_bbo_streams(
    bindings: Sequence[Mapping[str, Any]],
    *,
    deadline_check: Callable[[], None],
) -> Iterator[dict[str, Any]]:
    iterators = [
        iter(_raw_bbo_stream(item, deadline_check=deadline_check))
        for item in bindings
    ]
    heap: list[tuple[float, int, int, dict[str, Any]]] = []
    sequence = 0
    for index, iterator in enumerate(iterators):
        event = next(iterator, None)
        if event is not None:
            heapq.heappush(
                heap,
                (_finite(event["recv_ts"], label="recv_ts"), index, sequence, event),
            )
            sequence += 1
    while heap:
        deadline_check()
        _, index, _, event = heapq.heappop(heap)
        yield event
        following = next(iterators[index], None)
        if following is not None:
            heapq.heappush(
                heap,
                (
                    _finite(following["recv_ts"], label="recv_ts"),
                    index,
                    sequence,
                    following,
                ),
            )
            sequence += 1


class _JsonlTempWriter:
    def __init__(self, target: Path) -> None:
        self.target = target
        self.temp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
        self.digest = hashlib.sha256()
        self.rows = 0
        self.handle: Any = None

    def __enter__(self) -> "_JsonlTempWriter":
        self.target.parent.mkdir(parents=True, exist_ok=True)
        if self.target.exists() or self.temp.exists():
            raise CausalMaterializationIntegrityError(
                f"immutable output already exists: {self.target}"
            )
        self.handle = self.temp.open("xb")
        return self

    def write(self, row: Mapping[str, Any]) -> None:
        payload = (_canonical_json(row) + "\n").encode("utf-8")
        self.handle.write(payload)
        self.digest.update(payload)
        self.rows += 1

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if self.handle is not None:
                self.handle.flush()
                os.fsync(self.handle.fileno())
                self.handle.close()
        finally:
            if exc_type is not None:
                self.temp.unlink(missing_ok=True)

    @property
    def sha256(self) -> str:
        return self.digest.hexdigest()


def _write_json_temp(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _publish_immutable_outputs(pairs: Sequence[tuple[Path, Path]]) -> None:
    published: list[Path] = []
    try:
        for temporary, target in pairs:
            # A hard link atomically fails if the immutable target appeared after preflight.
            os.link(temporary, target)
            published.append(target)
            temporary.unlink()
    except Exception as exc:
        rollback_errors: list[str] = []
        for target in reversed(published):
            try:
                target.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(f"{target}: {rollback_exc}")
        if rollback_errors:
            raise CausalMaterializationIntegrityError(
                "partial immutable publish rollback failed: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    finally:
        for temporary, _ in pairs:
            temporary.unlink(missing_ok=True)


def run_causal_materialization(
    *,
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    quality_report_path: str | Path,
    labels_output_path: str | Path,
    snapshots_output_path: str | Path,
    manifest_output_path: str | Path,
    max_runtime_sec: int = 1800,
    _deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    if (
        isinstance(max_runtime_sec, bool)
        or not isinstance(max_runtime_sec, int)
        or not 1 <= max_runtime_sec <= 1800
    ):
        raise CausalMaterializationIntegrityError(
            "max_runtime_sec must be an integer between 1 and 1800"
        )
    deadline_monotonic = (
        _deadline_monotonic
        if _deadline_monotonic is not None
        else time.monotonic() + max_runtime_sec
    )
    def deadline_check() -> None:
        _check_deadline(deadline_monotonic)

    deadline_check()
    campaign_root = Path(plan["outputs"]["campaign_root"]).expanduser().resolve()
    quality_path = Path(quality_report_path).expanduser().resolve()
    _assert_inside(quality_path, campaign_root, label="quality report")
    quality = _read_json(quality_path)
    deadline_check()
    _validated_quality(quality, plan=plan, contract=contract)
    labels_target = Path(labels_output_path).expanduser().resolve()
    snapshots_target = Path(snapshots_output_path).expanduser().resolve()
    manifest_target = Path(manifest_output_path).expanduser().resolve()
    for target in (labels_target, snapshots_target, manifest_target):
        try:
            target.relative_to(campaign_root)
        except ValueError as exc:
            raise CausalMaterializationIntegrityError(
                f"materialization output escapes campaign root: {target}"
            ) from exc
        if target.exists():
            raise CausalMaterializationIntegrityError(
                f"immutable output already exists: {target}"
            )
    if len({labels_target, snapshots_target, manifest_target}) != 3:
        raise CausalMaterializationIntegrityError(
            "materialization output paths must be distinct"
        )

    valid_segments = [
        item
        for item in _as_sequence(quality.get("segments"), label="quality.segments")
        if isinstance(item, Mapping) and item.get("valid") is True
    ]
    if not valid_segments:
        raise CausalMaterializationIntegrityError("quality has no valid segments")
    bases_by_venue: dict[str, set[str]] = defaultdict(set)
    for segment in valid_segments:
        metrics = segment.get("metrics") or {}
        for venue, bases in (metrics.get("bases_by_venue") or {}).items():
            bases_by_venue[str(venue)].update(str(item).upper() for item in bases)
    bases = sorted(bases_by_venue["mexc"] & bases_by_venue["gateio"])
    if not bases:
        raise CausalMaterializationIntegrityError("quality has no matched bases")

    engine = CausalMaterializer(
        bases=bases,
        regime_contract=contract["causal_regime_contract"],
        execution_contract=contract["execution_sampling_contract"],
    )
    ordered_segments: list[tuple[float, Mapping[str, Any], dict[str, Any]]] = []
    for segment in valid_segments:
        manifest_ref = segment.get("manifest") or {}
        manifest_path = Path(str(manifest_ref.get("path") or "")).expanduser().resolve()
        _assert_inside(manifest_path, campaign_root, label="segment manifest")
        _assert_exact(
            _sha256_file_checked(manifest_path, deadline_check=deadline_check),
            manifest_ref.get("sha256"),
            label="segment manifest hash",
        )
        segment_manifest = _read_json(manifest_path)
        start_ts = _finite(
            segment_manifest.get("segment_started_epoch"),
            label="segment_started_epoch",
        )
        ordered_segments.append((start_ts, segment, segment_manifest))
    ordered_segments.sort(key=lambda item: (item[0], str(item[1].get("segment_dir"))))

    labels_writer = _JsonlTempWriter(labels_target)
    snapshots_writer = _JsonlTempWriter(snapshots_target)
    manifest_temp = manifest_target.with_name(
        f"{manifest_target.name}.tmp.{os.getpid()}"
    )
    prior_end: float | None = None
    try:
        with labels_writer, snapshots_writer:
            for start_ts, segment, segment_manifest in ordered_segments:
                deadline_check()
                end_ts = _finite(
                    segment_manifest.get("segment_finished_epoch"),
                    label="segment_finished_epoch",
                )
                if end_ts <= start_ts:
                    raise CausalMaterializationIntegrityError(
                        "segment time bounds are invalid"
                    )
                if prior_end is not None and start_ts < prior_end:
                    raise CausalMaterializationIntegrityError(
                        "valid segment time ranges overlap"
                    )
                prior_end = end_ts
                bindings = [
                    item
                    for item in _as_sequence(
                        segment.get("raw_files"), label="segment.raw_files"
                    )
                    if isinstance(item, Mapping)
                ]
                for binding in bindings:
                    raw_path = Path(
                        str(binding.get("path") or "")
                    ).expanduser().resolve()
                    _assert_inside(raw_path, campaign_root, label="raw file")
                engine.process_segment(
                    _merge_bbo_streams(
                        bindings,
                        deadline_check=deadline_check,
                    ),
                    start_ts=start_ts,
                    end_ts=end_ts,
                    label_sink=labels_writer.write,
                    snapshot_sink=snapshots_writer.write,
                    deadline_check=deadline_check,
                )

        deadline_check()
        minimum_snapshots = int(
            contract["segment_validity_contract"]["campaign_minimums"][
                "eligible_execution_snapshots"
            ]
        )
        accepted = snapshots_writer.rows >= minimum_snapshots
        decision = (
            "DATA_READY_FOR_SIGNAL_CONTRACT_REVIEW"
            if accepted
            else "REJECT_CAUSAL_MATERIALIZATION"
        )
        manifest: dict[str, Any] = {
            "schema": MATERIALIZATION_SCHEMA,
            "mode": "causal_regime_and_execution_snapshot_materialization",
            "campaign_id": plan["campaign_id"],
            "plan_hash": plan["plan_hash"],
            "contract_hash": contract["contract_hash"],
            "candidate_contract_hash": plan["contract"][
                "candidate_contract_hash"
            ],
            "quality_report": {
                "path": str(quality_path),
                "sha256": _sha256_file_checked(
                    quality_path,
                    deadline_check=deadline_check,
                ),
                "deterministic_result_hash": quality[
                    "deterministic_result_hash"
                ],
            },
            "runtime": {"max_runtime_sec": max_runtime_sec},
            "accepted": accepted,
            "decision": decision,
            "bases": bases,
            "valid_segments": len(ordered_segments),
            "labels": {
                "path": str(labels_target),
                "sha256": labels_writer.sha256,
                "rows": labels_writer.rows,
                "by_label": dict(sorted(engine.label_counts.items())),
            },
            "execution_snapshots": {
                "path": str(snapshots_target),
                "sha256": snapshots_writer.sha256,
                "rows": snapshots_writer.rows,
                "minimum_required": minimum_snapshots,
                "exclusions": dict(sorted(engine.snapshot_exclusions.items())),
            },
            "next_allowed_action": (
                "USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT"
                if accepted
                else "STOP_PIPELINE_USER_REVIEW_REQUIRED"
            ),
            "safety": {
                "network_access": False,
                "returns_read": False,
                "pnl_computed": False,
                "oos_read": False,
                "grid_or_retune": False,
                "paper_forward": False,
                "live_orders": False,
                "private_api_keys": False,
                "real_capital": False,
                "leverage_or_margin": False,
            },
        }
        manifest["deterministic_result_hash"] = _deterministic_hash(manifest)
        if manifest_temp.exists():
            raise CausalMaterializationIntegrityError(
                f"temporary manifest already exists: {manifest_temp}"
            )
        _write_json_temp(manifest_temp, manifest)
        deadline_check()
        _publish_immutable_outputs(
            (
                (labels_writer.temp, labels_target),
                (snapshots_writer.temp, snapshots_target),
                (manifest_temp, manifest_target),
            )
        )
    finally:
        labels_writer.temp.unlink(missing_ok=True)
        snapshots_writer.temp.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
    return manifest


def run_causal_materialization_file(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    quality_report_path: str | Path,
    labels_output_path: str | Path,
    snapshots_output_path: str | Path,
    manifest_output_path: str | Path,
    max_runtime_sec: int = 1800,
) -> dict[str, Any]:
    if (
        isinstance(max_runtime_sec, bool)
        or not isinstance(max_runtime_sec, int)
        or not 1 <= max_runtime_sec <= 1800
    ):
        raise CausalMaterializationIntegrityError(
            "max_runtime_sec must be an integer between 1 and 1800"
        )
    deadline_monotonic = time.monotonic() + max_runtime_sec
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = _read_json(resolved_plan)
    _assert_exact(plan.get("schema"), PLAN_SCHEMA, label="plan.schema")
    _assert_exact(plan.get("plan_hash"), expected_plan_hash, label="ExpectedPlanHash")
    contract_ref = plan.get("contract")
    if not isinstance(contract_ref, Mapping):
        raise CausalMaterializationIntegrityError("plan.contract is missing")
    contract = _read_json(contract_ref["path"])
    try:
        validate_contract(contract, verify_files=True)
        validate_plan(plan, contract=contract, verify_files=True)
    except (OSError, ValueError) as exc:
        raise CausalMaterializationIntegrityError(
            f"immutable bundle validation failed: {exc}"
        ) from exc
    _check_deadline(deadline_monotonic)
    tool = (
        plan.get("launch_controls", {})
        .get("tools", {})
        .get("causal_materializer")
    )
    if not isinstance(tool, Mapping):
        raise CausalMaterializationIntegrityError(
            "PlanOnly does not bind causal_materializer"
        )
    this_file = Path(__file__).resolve()
    _assert_exact(
        Path(str(tool.get("path") or "")).expanduser().resolve(),
        this_file,
        label="causal_materializer tool path",
    )
    _assert_exact(
        tool.get("sha256"),
        sha256_file(this_file),
        label="causal_materializer tool hash",
    )
    return run_causal_materialization(
        plan=plan,
        contract=contract,
        quality_report_path=quality_report_path,
        labels_output_path=labels_output_path,
        snapshots_output_path=snapshots_output_path,
        manifest_output_path=manifest_output_path,
        max_runtime_sec=max_runtime_sec,
        _deadline_monotonic=deadline_monotonic,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hash-bound dense WS causal regime materialization"
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--quality-report", required=True)
    parser.add_argument("--labels-output", required=True)
    parser.add_argument("--snapshots-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=1800)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        result = run_causal_materialization_file(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            quality_report_path=args.quality_report,
            labels_output_path=args.labels_output,
            snapshots_output_path=args.snapshots_output,
            manifest_output_path=args.manifest_output,
            max_runtime_sec=args.max_runtime_sec,
        )
    except CausalMaterializationRuntimeError as exc:
        print(
            json.dumps(
                {
                    "schema": MATERIALIZATION_SCHEMA,
                    "decision": "STOPPED_INCOMPLETE_RUNTIME_LIMIT",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": MATERIALIZATION_SCHEMA,
                    "decision": "INTEGRITY_CONFLICT",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
