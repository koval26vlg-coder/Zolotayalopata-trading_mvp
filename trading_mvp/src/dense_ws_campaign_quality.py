from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from dense_ws_campaign_contract import (
        PLAN_SCHEMA,
        sha256_file,
        validate_contract,
        validate_plan,
    )
    from ws_normalizer import classify_ws_row, expected_market_channels
except ModuleNotFoundError:  # pragma: no cover - package import path
    from .dense_ws_campaign_contract import (
        PLAN_SCHEMA,
        sha256_file,
        validate_contract,
        validate_plan,
    )
    from .ws_normalizer import classify_ws_row, expected_market_channels


QUALITY_SCHEMA = "trading_mvp_dense_ws_campaign_quality_v1"
CAMPAIGN_MANIFEST_SCHEMA = "trading_mvp_dense_ws_campaign_manifest_v1"
PHASE_MANIFEST_SCHEMA = "ws_collect_stitched_v1"
MAX_ERROR_SAMPLES = 50


class CampaignQualityIntegrityError(ValueError):
    """A hash, identity, or namespace binding no longer matches."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _deterministic_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "deterministic_result_hash"}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignQualityIntegrityError(f"invalid JSON object: {target}: {exc}") from exc
    if not isinstance(value, dict):
        raise CampaignQualityIntegrityError(f"expected JSON object: {target}")
    return value


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(target, flags)
    except FileExistsError as exc:
        raise CampaignQualityIntegrityError(f"immutable output already exists: {target}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_sequence(value: Any, *, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CampaignQualityIntegrityError(f"{label} must be a sequence")
    return value


def _assert_exact(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise CampaignQualityIntegrityError(
            f"{label} mismatch: expected={expected!r} observed={actual!r}"
        )


def _assert_number_equal(
    actual: Any,
    expected: Any,
    *,
    label: str,
    tolerance: float = 0.001,
) -> None:
    actual_number = _as_float(actual)
    expected_number = _as_float(expected)
    if (
        actual_number is None
        or expected_number is None
        or abs(actual_number - expected_number) > tolerance
    ):
        raise CampaignQualityIntegrityError(
            f"{label} mismatch: expected={expected!r} observed={actual!r}"
        )


def _assert_inside(path: Path, root: Path, *, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CampaignQualityIntegrityError(
            f"{label} escapes immutable namespace: path={path} root={root}"
        ) from exc


def _error_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, Mapping):
        return sum(len(item) for item in value.values() if isinstance(item, list))
    return 0 if value in (None, {}, []) else 1


def _base_symbol(symbol: Any) -> str | None:
    value = str(symbol or "").strip().upper()
    if value.endswith("_USDT") and len(value) > 5:
        return value[:-5]
    if value.endswith("USDT") and len(value) > 4:
        return value[:-4]
    return None


def _dual_venue_coverage(
    bases_by_venue: Mapping[str, set[str]],
    required_venues: Sequence[str],
) -> tuple[float, int, dict[str, int]]:
    venue_sets = [set(bases_by_venue.get(venue, set())) for venue in required_venues]
    counts = {venue: len(values) for venue, values in zip(required_venues, venue_sets)}
    if not venue_sets or min((len(values) for values in venue_sets), default=0) == 0:
        return 0.0, 0, counts
    matched = len(set.intersection(*venue_sets))
    denominator = min(len(values) for values in venue_sets)
    return matched / denominator, matched, counts


def _envelope_error(
    row: Any,
    *,
    outer_fields: set[str],
    allowed_venues: set[str],
    allowed_encodings: set[str],
    json_or_text_fields: set[str],
    base64_fields: set[str],
) -> str | None:
    if not isinstance(row, dict):
        return "row_not_object"
    if set(row) != outer_fields:
        return "outer_fields_mismatch"
    recv_ts = _as_float(row.get("recv_ts"))
    if recv_ts is None:
        return "recv_ts_not_finite"
    if str(row.get("exchange") or "").lower() not in allowed_venues:
        return "exchange_not_allowed"
    if not isinstance(row.get("event_type"), str) or not row["event_type"].strip():
        return "event_type_invalid"
    if row.get("channel") is not None and not isinstance(row.get("channel"), str):
        return "channel_invalid"
    if row.get("symbol") is not None and not isinstance(row.get("symbol"), str):
        return "symbol_invalid"
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return "payload_not_object"
    encoding = str(payload.get("encoding") or "")
    if encoding not in allowed_encodings:
        return "payload_encoding_invalid"
    expected_fields = base64_fields if encoding == "base64" else json_or_text_fields
    if set(payload) != expected_fields:
        return "payload_fields_mismatch"
    if encoding == "text" and not isinstance(payload.get("data"), str):
        return "text_payload_invalid"
    if encoding == "base64":
        data = payload.get("data")
        byte_length = payload.get("byte_length")
        if not isinstance(data, str) or isinstance(byte_length, bool) or not isinstance(byte_length, int):
            return "base64_payload_invalid"
        try:
            decoded = base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            return "base64_decode_failed"
        if len(decoded) != byte_length:
            return "base64_byte_length_mismatch"
    return None


def _scan_raw_files(
    file_results: Sequence[Mapping[str, Any]],
    *,
    segment_root: Path,
    segment_started_epoch: float,
    segment_finished_epoch: float | None,
    raw_contract: Mapping[str, Any],
    expected_symbols_by_exchange: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    outer_fields = set(raw_contract.get("outer_fields_exact") or [])
    field_contract = raw_contract.get("field_contract") or {}
    allowed_venues = {str(item).lower() for item in field_contract.get("exchange") or []}
    payload_contract = field_contract.get("payload") or {}
    allowed_encodings = set(payload_contract.get("encoding") or [])
    json_or_text_fields = set(payload_contract.get("json_or_text_fields") or [])
    base64_fields = set(payload_contract.get("base64_fields") or [])
    if not outer_fields or not allowed_venues or not allowed_encodings:
        raise CampaignQualityIntegrityError("raw schema contract is incomplete")

    total_lines = 0
    valid_envelope_rows = 0
    market_envelope_rows = 0
    control_rows = 0
    unclassified_messages = 0
    market_silence_events = 0
    reconnect_attempts = 0
    parse_errors = 0
    malformed_envelopes = 0
    normalization_errors = 0
    boundary_timestamp_rows = 0
    normalized_rows = 0
    out_of_order_rows = 0
    max_market_gap_sec = 0.0
    by_raw_exchange: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    market_kinds: dict[str, set[str]] = defaultdict(set)
    bases_by_venue: dict[str, set[str]] = defaultdict(set)
    last_market_ts: dict[tuple[str, str], float] = {}
    market_kind_times: dict[tuple[str, str], list[float]] = defaultdict(list)
    error_samples: list[dict[str, Any]] = []
    file_bindings: list[dict[str, Any]] = []
    declared_events_total = 0

    normalized_results: list[
        tuple[Path, Mapping[str, Any], list[str], dict[str, set[str]]]
    ] = []
    seen_paths: set[Path] = set()
    observed_symbols_by_exchange: dict[str, set[str]] = defaultdict(set)
    for item in file_results:
        output_value = str(item.get("output") or "").strip()
        if not output_value:
            raise CampaignQualityIntegrityError("segment result output path is missing")
        output = Path(output_value).expanduser()
        if not output.is_absolute():
            output = segment_root / output
        output = output.resolve()
        _assert_inside(output, segment_root, label="raw output")
        if output in seen_paths:
            raise CampaignQualityIntegrityError(f"duplicate raw output binding: {output}")
        if not output.is_file():
            raise CampaignQualityIntegrityError(f"raw output is missing: {output}")
        expected_exchange = str(item.get("exchange") or "").lower()
        item_symbols_raw = item.get("symbols")
        if not isinstance(item_symbols_raw, list) or not item_symbols_raw:
            raise CampaignQualityIntegrityError(
                f"segment result symbols are missing: {output}"
            )
        item_symbols = [str(symbol).strip().upper() for symbol in item_symbols_raw]
        if item_symbols != item_symbols_raw or len(set(item_symbols)) != len(item_symbols):
            raise CampaignQualityIntegrityError(
                f"segment result symbols are non-canonical or duplicated: {output}"
            )
        expected_venue_symbols = {
            str(symbol).strip().upper()
            for symbol in expected_symbols_by_exchange.get(expected_exchange, ())
        }
        if not set(item_symbols).issubset(expected_venue_symbols):
            raise CampaignQualityIntegrityError(
                f"segment result symbols escape symbol plan: {output}"
            )
        overlap = observed_symbols_by_exchange[expected_exchange] & set(item_symbols)
        if overlap:
            raise CampaignQualityIntegrityError(
                f"segment result symbols are repeated across files: {sorted(overlap)}"
            )
        observed_symbols_by_exchange[expected_exchange].update(item_symbols)
        channels_by_symbol = {
            symbol: set(expected_market_channels(expected_exchange, symbol).values())
            for symbol in item_symbols
        }
        seen_paths.add(output)
        normalized_results.append((output, item, item_symbols, channels_by_symbol))

    for exchange, symbols in expected_symbols_by_exchange.items():
        expected = {str(symbol).strip().upper() for symbol in symbols}
        observed = observed_symbols_by_exchange.get(str(exchange).lower(), set())
        if observed != expected:
            raise CampaignQualityIntegrityError(
                f"segment result symbols do not match symbol plan for {exchange}: "
                f"missing={sorted(expected - observed)} extra={sorted(observed - expected)}"
            )

    expected_subscriptions: set[tuple[str, str, str]] = set()
    for exchange, symbols in expected_symbols_by_exchange.items():
        venue = str(exchange).lower()
        for symbol in symbols:
            market = str(symbol).strip().upper()
            for kind in expected_market_channels(venue, market):
                expected_subscriptions.add((venue, market, kind))
    observed_subscriptions: set[tuple[str, str, str]] = set()

    for output, item, item_symbols, channels_by_symbol in sorted(
        normalized_results, key=lambda value: str(value[0]).lower()
    ):
        expected_exchange = str(item.get("exchange") or "").lower()
        if expected_exchange not in allowed_venues:
            raise CampaignQualityIntegrityError(
                f"segment result exchange is invalid: {expected_exchange!r}"
            )
        declared_events = item.get("events")
        if isinstance(declared_events, bool) or not isinstance(declared_events, int) or declared_events < 0:
            raise CampaignQualityIntegrityError(f"raw result events is invalid: {output}")
        declared_events_total += declared_events
        digest = hashlib.sha256()
        file_nonempty_lines = 0
        file_connect_attempts = 0
        with output.open("rb") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                digest.update(raw_line)
                if not raw_line.strip():
                    continue
                file_nonempty_lines += 1
                total_lines += 1
                try:
                    row = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    parse_errors += 1
                    if len(error_samples) < MAX_ERROR_SAMPLES:
                        error_samples.append(
                            {"path": str(output), "line": line_no, "error": f"json_parse:{exc}"}
                        )
                    continue
                envelope_error = _envelope_error(
                    row,
                    outer_fields=outer_fields,
                    allowed_venues=allowed_venues,
                    allowed_encodings=allowed_encodings,
                    json_or_text_fields=json_or_text_fields,
                    base64_fields=base64_fields,
                )
                if envelope_error:
                    malformed_envelopes += 1
                    if len(error_samples) < MAX_ERROR_SAMPLES:
                        error_samples.append(
                            {"path": str(output), "line": line_no, "error": envelope_error}
                        )
                    continue
                exchange = str(row["exchange"]).lower()
                if exchange != expected_exchange:
                    malformed_envelopes += 1
                    if len(error_samples) < MAX_ERROR_SAMPLES:
                        error_samples.append(
                            {"path": str(output), "line": line_no, "error": "result_exchange_mismatch"}
                        )
                    continue
                recv_ts = float(row["recv_ts"])
                if (
                    recv_ts < segment_started_epoch
                    or segment_finished_epoch is None
                    or recv_ts > segment_finished_epoch
                ):
                    boundary_timestamp_rows += 1
                    if len(error_samples) < MAX_ERROR_SAMPLES:
                        error_samples.append(
                            {
                                "path": str(output),
                                "line": line_no,
                                "error": "recv_ts_outside_segment_bounds",
                            }
                        )
                    continue
                valid_envelope_rows += 1
                by_raw_exchange[exchange] += 1
                classification = classify_ws_row(
                    row,
                    expected_exchange=expected_exchange,
                    expected_symbols=item_symbols,
                    expected_channels_by_symbol=channels_by_symbol,
                )
                classification_name = classification["classification"]
                if classification_name == "control":
                    control_rows += 1
                    event_type = str(row.get("event_type") or "")
                    if event_type == "market_silence_detected":
                        market_silence_events += 1
                    if event_type == "connect_attempt":
                        file_connect_attempts += 1
                    if event_type == "subscribe_sent":
                        data = (row.get("payload") or {}).get("data")
                        if isinstance(data, Mapping):
                            if expected_exchange == "mexc" and str(
                                data.get("method") or ""
                            ).upper() == "SUBSCRIPTION":
                                params = data.get("params")
                                if isinstance(params, list):
                                    for symbol, channels in channels_by_symbol.items():
                                        expected = expected_market_channels("mexc", symbol)
                                        for kind, channel in expected.items():
                                            if channel in params:
                                                observed_subscriptions.add(
                                                    ("mexc", symbol, kind)
                                                )
                            elif expected_exchange == "gateio" and data.get(
                                "event"
                            ) == "subscribe":
                                channel = str(data.get("channel") or "")
                                kind_by_channel = {
                                    value: kind
                                    for kind, value in expected_market_channels(
                                        "gateio", item_symbols[0]
                                    ).items()
                                }
                                kind = kind_by_channel.get(channel)
                                payload_symbols = data.get("payload")
                                if kind and isinstance(payload_symbols, list):
                                    subscribed = (
                                        [str(payload_symbols[0]).upper()]
                                        if kind == "depth" and payload_symbols
                                        else [str(value).upper() for value in payload_symbols]
                                    )
                                    for symbol in subscribed:
                                        if symbol in channels_by_symbol:
                                            observed_subscriptions.add(
                                                ("gateio", symbol, kind)
                                            )
                    continue
                if classification_name != "market":
                    normalization_errors += 1
                    unclassified_messages += 1
                    if len(error_samples) < MAX_ERROR_SAMPLES:
                        error_samples.append(
                            {
                                "path": str(output),
                                "line": line_no,
                                "error": f"classification:{classification['reason']}",
                            }
                        )
                    continue
                market_envelope_rows += 1
                for event in classification["events"]:
                    event_exchange = str(event.get("exchange") or exchange).lower()
                    symbol = str(event.get("symbol") or "")
                    kind = str(event.get("event_kind") or "")
                    base = _base_symbol(symbol)
                    if not symbol or not kind or base is None:
                        normalization_errors += 1
                        continue
                    event_ts = _as_float(event.get("recv_ts"))
                    if event_ts is None:
                        normalization_errors += 1
                        continue
                    market = f"{event_exchange}:{symbol.upper()}"
                    market_kind = (market, kind)
                    prior = last_market_ts.get(market_kind)
                    if prior is not None:
                        if event_ts < prior:
                            out_of_order_rows += 1
                    last_market_ts[market_kind] = event_ts
                    market_kind_times[market_kind].append(event_ts)
                    normalized_rows += 1
                    by_kind[kind] += 1
                    market_kinds[market].add(kind)
                    bases_by_venue[event_exchange].add(base)
        reconnect_attempts += max(0, file_connect_attempts - 1)
        if file_nonempty_lines != declared_events:
            if len(error_samples) < MAX_ERROR_SAMPLES:
                error_samples.append(
                    {
                        "path": str(output),
                        "error": "declared_event_count_mismatch",
                        "declared": declared_events,
                        "observed": file_nonempty_lines,
                    }
                )
        file_bindings.append(
            {
                "path": str(output),
                "sha256": digest.hexdigest(),
                "exchange": expected_exchange,
                "declared_events": declared_events,
                "observed_nonempty_lines": file_nonempty_lines,
                "declared_event_count_matches": file_nonempty_lines == declared_events,
            }
        )

    missing_subscriptions = sorted(expected_subscriptions - observed_subscriptions)
    missing_markets: list[str] = []
    market_gap_details: dict[str, dict[str, float]] = {}
    for exchange, symbols in expected_symbols_by_exchange.items():
        venue = str(exchange).lower()
        for symbol_value in symbols:
            symbol = str(symbol_value).strip().upper()
            market = f"{venue}:{symbol}"
            market_missing = False
            for kind in ("bbo", "depth"):
                timestamps = sorted(market_kind_times.get((market, kind), []))
                if not timestamps:
                    market_missing = True
                    continue
                gaps = [timestamps[0] - segment_started_epoch]
                gaps.extend(
                    later - earlier for earlier, later in zip(timestamps, timestamps[1:])
                )
                if segment_finished_epoch is not None:
                    gaps.append(segment_finished_epoch - timestamps[-1])
                kind_gap = max(gaps, default=0.0)
                max_market_gap_sec = max(max_market_gap_sec, kind_gap)
                market_gap_details[f"{market}:{kind}"] = {
                    "leading_gap_sec": timestamps[0] - segment_started_epoch,
                    "internal_max_gap_sec": max(
                        (
                            later - earlier
                            for earlier, later in zip(timestamps, timestamps[1:])
                        ),
                        default=0.0,
                    ),
                    "trailing_gap_sec": (
                        segment_finished_epoch - timestamps[-1]
                        if segment_finished_epoch is not None
                        else 0.0
                    ),
                    "max_gap_sec": kind_gap,
                }
            if market_missing:
                missing_markets.append(f"missing_market:{venue}:{symbol}")

    return {
        "total_lines": total_lines,
        "transport_rows": total_lines,
        "valid_envelope_rows": valid_envelope_rows,
        "market_envelope_rows": market_envelope_rows,
        "control_rows": control_rows,
        "unclassified_messages": unclassified_messages,
        "market_silence_events": market_silence_events,
        "reconnect_attempts": reconnect_attempts,
        "json_parse_errors": parse_errors,
        "malformed_envelopes": malformed_envelopes,
        "normalization_errors": normalization_errors,
        "boundary_timestamp_rows": boundary_timestamp_rows,
        "normalized_rows": normalized_rows,
        "out_of_order_rows": out_of_order_rows,
        "max_market_gap_sec": max_market_gap_sec,
        "market_gap_details": market_gap_details,
        "missing_markets": missing_markets,
        "missing_subscriptions": [
            f"missing_subscription:{exchange}:{symbol}:{kind}"
            for exchange, symbol, kind in missing_subscriptions
        ],
        "by_raw_exchange": dict(sorted(by_raw_exchange.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "market_kinds": {key: sorted(value) for key, value in sorted(market_kinds.items())},
        "bases_by_venue": {key: sorted(value) for key, value in sorted(bases_by_venue.items())},
        "declared_events_total": declared_events_total,
        "file_bindings": file_bindings,
        "error_samples": error_samples,
    }


def _evaluate_segment(
    *,
    phase: Mapping[str, Any],
    segment_index: int,
    segment_summary: Mapping[str, Any],
    contract: Mapping[str, Any],
    expected_symbols_by_exchange: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    phase_root = Path(str(phase["output_namespace"])).expanduser().resolve()
    segment_name = f"seg_{segment_index:03d}"
    segment_root = (phase_root / segment_name).resolve()
    manifest_path = segment_root / "manifest.json"
    _assert_exact(segment_summary.get("segment_dir"), segment_name, label="segment_dir")
    if not manifest_path.is_file():
        raise CampaignQualityIntegrityError(f"segment manifest is missing: {manifest_path}")
    manifest = _read_json(manifest_path)
    _assert_exact(manifest.get("segment_index"), segment_index, label="segment_index")

    segment_contract = contract["segment_validity_contract"]
    rules = segment_contract["valid_segment_rules"]
    full_segment_sec = int(segment_contract["full_segment_sec"])
    reasons: list[str] = []
    if manifest.get("duration_completed") is not True:
        reasons.append("duration_not_completed")
    if manifest.get("liveness_clean") is not True:
        reasons.append("liveness_not_clean")
    if manifest.get("quality_eligible") is not True:
        reasons.append("quality_not_eligible")
    if manifest.get("completed") is not rules["manifest_completed"]:
        reasons.append("manifest_completed")
    if manifest.get("final") is not rules["manifest_final"]:
        reasons.append("manifest_final")
    actual_duration = _as_float(manifest.get("actual_duration_sec")) or 0.0
    segment_started_epoch = _as_float(manifest.get("segment_started_epoch"))
    segment_finished_epoch = _as_float(manifest.get("segment_finished_epoch"))
    if (
        segment_started_epoch is None
        or segment_finished_epoch is None
        or segment_finished_epoch <= segment_started_epoch
    ):
        reasons.append("segment_bounds_invalid")
        segment_started_epoch = 0.0
        segment_finished_epoch = 0.0
    elif abs((segment_finished_epoch - segment_started_epoch) - actual_duration) > 2.0:
        reasons.append("segment_duration_bounds_mismatch")
    duration_ratio = actual_duration / full_segment_sec if full_segment_sec > 0 else 0.0
    if duration_ratio < float(rules["actual_duration_ratio_min"]):
        reasons.append("actual_duration_ratio")
    result_items = _as_sequence(manifest.get("results"), label="segment.results")
    file_results = [item for item in result_items if isinstance(item, Mapping)]
    if len(file_results) != len(result_items):
        raise CampaignQualityIntegrityError("segment.results contains non-object entries")
    result_errors = _error_count(manifest.get("errors")) + sum(
        _error_count(item.get("errors")) for item in file_results
    )
    if result_errors > int(rules["result_errors_max"]):
        reasons.append("result_errors")

    required_venues = [str(item).lower() for item in rules["required_venues"]]
    files_by_venue: Counter[str] = Counter(str(item.get("exchange") or "").lower() for item in file_results)
    for venue in required_venues:
        if files_by_venue[venue] < int(rules["raw_files_min_per_venue"]):
            reasons.append(f"raw_files_min:{venue}")

    scan = _scan_raw_files(
        file_results,
        segment_root=segment_root,
        segment_started_epoch=segment_started_epoch,
        segment_finished_epoch=segment_finished_epoch,
        raw_contract=contract["raw_schema_contract"],
        expected_symbols_by_exchange=expected_symbols_by_exchange,
    )
    declared_total = manifest.get("total_events")
    if declared_total != scan["declared_events_total"]:
        reasons.append("segment_total_events_mismatch")
    if any(not item["declared_event_count_matches"] for item in scan["file_bindings"]):
        reasons.append("declared_event_count_mismatch")
    counter_fields = {
        "transport_rows": "transport_rows",
        "market_envelope_rows": "market_envelope_rows",
        "normalized_events": "normalized_rows",
        "control_rows": "control_rows",
        "unclassified_messages": "unclassified_messages",
        "market_silence_events": "market_silence_events",
        "reconnect_attempts": "reconnect_attempts",
    }
    for manifest_field, scan_field in counter_fields.items():
        if manifest.get(manifest_field) != scan.get(scan_field):
            reasons.append(f"counter_mismatch:{manifest_field}")
    if scan["market_envelope_rows"] < int(rules["raw_rows_min"]):
        reasons.append("raw_rows_min")
    total_lines = int(scan["total_lines"])
    parse_rate = scan["json_parse_errors"] / total_lines if total_lines else 1.0
    malformed_rate = scan["malformed_envelopes"] / total_lines if total_lines else 1.0
    if parse_rate > float(rules["json_parse_error_rate_max"]):
        reasons.append("json_parse_error_rate")
    if malformed_rate > float(rules["malformed_envelope_rate_max"]):
        reasons.append("malformed_envelope_rate")
    if scan["normalization_errors"]:
        reasons.append("normalization_errors")
    if scan["boundary_timestamp_rows"]:
        reasons.append("boundary_timestamp_rows")
    reasons.extend(scan["missing_markets"])
    reasons.extend(scan["missing_subscriptions"])
    required_kinds = set(rules["normalized_required_event_kinds"])
    missing_kinds = sorted(required_kinds - set(scan["by_kind"]))
    reasons.extend(f"missing_event_kind:{kind}" for kind in missing_kinds)
    if scan["max_market_gap_sec"] > float(rules["market_max_gap_sec"]):
        reasons.append("market_max_gap_sec")
    if scan["out_of_order_rows"] > int(rules["out_of_order_rows_max"]):
        reasons.append("out_of_order_rows")
    bases_by_venue = {key: set(value) for key, value in scan["bases_by_venue"].items()}
    coverage, matched_bases, venue_base_counts = _dual_venue_coverage(
        bases_by_venue,
        required_venues,
    )
    if coverage < float(rules["dual_venue_coverage_min"]):
        reasons.append("dual_venue_coverage")

    reasons = sorted(set(reasons))
    return {
        "phase_id": phase["phase_id"],
        "run_id": phase["run_id"],
        "segment_index": segment_index,
        "segment_dir": str(segment_root),
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "valid": not reasons,
        "reasons": reasons,
        "metrics": {
            "actual_duration_sec": actual_duration,
            "duration_ratio": duration_ratio,
            "result_errors": result_errors,
            "parse_error_rate": parse_rate,
            "malformed_envelope_rate": malformed_rate,
            "dual_venue_coverage": coverage,
            "matched_bases": matched_bases,
            "venue_base_counts": venue_base_counts,
            "bases_by_venue": scan["bases_by_venue"],
            **{key: value for key, value in scan.items() if key not in {"bases_by_venue", "file_bindings", "error_samples"}},
        },
        "raw_files": scan["file_bindings"],
        "error_samples": scan["error_samples"],
    }


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    report["deterministic_result_hash"] = _deterministic_hash(report)
    return report


def _stopped_report(
    *,
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    campaign_manifest_path: Path,
    campaign_manifest_sha256: str,
    reasons: Sequence[str],
) -> dict[str, Any]:
    return _finalize_report(
        {
            "schema": QUALITY_SCHEMA,
            "mode": "campaign_data_quality",
            "campaign_id": plan["campaign_id"],
            "plan_hash": plan["plan_hash"],
            "contract_hash": contract["contract_hash"],
            "candidate_contract_hash": plan["contract"]["candidate_contract_hash"],
            "accepted": False,
            "decision": "STOPPED_INCOMPLETE",
            "reasons": sorted(set(reasons)),
            "inputs": {
                "campaign_manifest": {
                    "path": str(campaign_manifest_path),
                    "sha256": campaign_manifest_sha256,
                }
            },
            "metrics": {"valid_full_segments": 0, "full_segments_evaluated": 0},
            "segments": [],
            "deferred_gates": ["causal_regime_labels", "eligible_execution_snapshots"],
            "next_allowed_action": "STOP_PIPELINE_AWAIT_EXACT_RECOVERY_APPROVAL",
            "safety": _safety_flags(),
        }
    )


def _safety_flags() -> dict[str, bool]:
    return {
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
    }


def evaluate_validated_campaign_quality(
    *,
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
    campaign_manifest_path: str | Path,
) -> dict[str, Any]:
    """Evaluate a bundle already validated against its immutable PlanOnly."""

    manifest_path = Path(campaign_manifest_path).expanduser().resolve()
    campaign_root = Path(str(plan["outputs"]["campaign_root"])).expanduser().resolve()
    expected_manifest_path = (campaign_root / "campaign-manifest.json").resolve()
    _assert_exact(manifest_path, expected_manifest_path, label="campaign manifest path")
    manifest = _read_json(manifest_path)
    manifest_sha = sha256_file(manifest_path)
    _assert_exact(manifest.get("schema"), CAMPAIGN_MANIFEST_SCHEMA, label="campaign manifest schema")
    _assert_exact(manifest.get("campaign_id"), plan.get("campaign_id"), label="campaign_id")
    _assert_exact(manifest.get("plan_hash"), plan.get("plan_hash"), label="plan_hash")
    _assert_exact(manifest.get("contract_hash"), contract.get("contract_hash"), label="contract_hash")
    candidate_hash = plan.get("contract", {}).get("candidate_contract_hash")
    _assert_exact(
        manifest.get("candidate_contract_hash"),
        candidate_hash,
        label="candidate_contract_hash",
    )
    for key in ("returns_read", "pnl_computed", "oos_read"):
        _assert_exact(manifest.get(key), False, label=f"campaign manifest {key}")

    symbol_plan_path = (campaign_root / "_control" / "symbol-plan.json").resolve()
    _assert_exact(
        Path(str(manifest.get("symbol_plan_path") or "")).expanduser().resolve(),
        symbol_plan_path,
        label="campaign symbol_plan_path",
    )
    symbol_plan_sha256 = sha256_file(symbol_plan_path)
    _assert_exact(
        manifest.get("symbol_plan_sha256"),
        symbol_plan_sha256,
        label="campaign symbol_plan_sha256",
    )
    symbol_plan = _read_json(symbol_plan_path)
    _assert_exact(symbol_plan.get("campaign_id"), plan.get("campaign_id"), label="symbol plan campaign_id")
    _assert_exact(symbol_plan.get("plan_hash"), plan.get("plan_hash"), label="symbol plan plan_hash")
    _assert_exact(
        symbol_plan.get("contract_hash"),
        contract.get("contract_hash"),
        label="symbol plan contract_hash",
    )
    universe_sha256 = contract["universe_contract"]["source"]["sha256"]
    _assert_exact(
        symbol_plan.get("universe_sha256"),
        universe_sha256,
        label="symbol plan universe_sha256",
    )
    raw_symbols_by_exchange = symbol_plan.get("symbols_by_exchange")
    if not isinstance(raw_symbols_by_exchange, Mapping) or set(
        raw_symbols_by_exchange
    ) != {"mexc", "gateio"}:
        raise CampaignQualityIntegrityError(
            "symbol plan must bind exactly mexc and gateio"
        )
    expected_symbols_by_exchange: dict[str, list[str]] = {}
    for exchange in ("mexc", "gateio"):
        values = raw_symbols_by_exchange.get(exchange)
        if not isinstance(values, list) or not values:
            raise CampaignQualityIntegrityError(
                f"symbol plan {exchange} symbols are missing"
            )
        normalized = [str(value).strip().upper() for value in values]
        if normalized != values or len(set(normalized)) != len(normalized):
            raise CampaignQualityIntegrityError(
                f"symbol plan {exchange} symbols are non-canonical or duplicated"
            )
        expected_symbols_by_exchange[exchange] = normalized
    expected_symbols_arg = ";".join(
        f"{exchange}:{','.join(expected_symbols_by_exchange[exchange])}"
        for exchange in sorted(expected_symbols_by_exchange)
    )
    _assert_exact(
        symbol_plan.get("symbols_arg"),
        expected_symbols_arg,
        label="symbol plan symbols_arg",
    )

    phases = _as_sequence(plan.get("phases"), label="plan.phases")
    phase_results = _as_sequence(manifest.get("phase_results"), label="campaign phase_results")
    expected_phase_ids = [str(item["phase_id"]) for item in phases]
    observed_phase_ids = [str(item.get("phase_id") or "") for item in phase_results if isinstance(item, Mapping)]
    if len(observed_phase_ids) != len(phase_results) or len(set(observed_phase_ids)) != len(observed_phase_ids):
        raise CampaignQualityIntegrityError("campaign phase_results identities are invalid")
    unknown_phase_ids = sorted(set(observed_phase_ids) - set(expected_phase_ids))
    if unknown_phase_ids:
        raise CampaignQualityIntegrityError(f"campaign has unknown phases: {unknown_phase_ids}")

    incomplete_reasons: list[str] = []
    if manifest.get("runtime_completed") is not True:
        incomplete_reasons.append("campaign_runtime_not_completed")
    if manifest.get("liveness_clean") is not True:
        incomplete_reasons.append("campaign_liveness_not_clean")
    if manifest.get("quality_eligible") is not True:
        incomplete_reasons.append("campaign_quality_not_eligible")
    if manifest.get("dirty_segment_ids") not in ([], None):
        incomplete_reasons.append("campaign_dirty_segments")
    if manifest.get("completed") is not True:
        incomplete_reasons.append("campaign_not_completed")
    if manifest.get("final") is not True:
        incomplete_reasons.append("campaign_not_final")
    if manifest.get("phases_completed") != len(phases):
        incomplete_reasons.append("phase_count_incomplete")
    if set(observed_phase_ids) != set(expected_phase_ids):
        incomplete_reasons.append("phase_results_incomplete")
    for item in phase_results:
        if isinstance(item, Mapping) and item.get("status") != "READY":
            incomplete_reasons.append(f"phase_not_ready:{item.get('phase_id')}")
    if incomplete_reasons:
        return _stopped_report(
            plan=plan,
            contract=contract,
            campaign_manifest_path=manifest_path,
            campaign_manifest_sha256=manifest_sha,
            reasons=incomplete_reasons,
        )

    requested_writer_sec = sum(int(item["writer_duration_sec"]) for item in phases)
    _assert_number_equal(
        manifest.get("writer_duration_requested_sec"),
        requested_writer_sec,
        label="campaign writer_duration_requested_sec",
    )

    phase_result_by_id = {str(item["phase_id"]): item for item in phase_results}
    segment_reports: list[dict[str, Any]] = []
    phase_bindings: list[dict[str, Any]] = []
    phase_quality_reasons: list[str] = []
    campaign_bases: dict[str, set[str]] = defaultdict(set)
    writer_duration_actual = 0.0
    campaign_total_events = 0
    campaign_counter_totals: Counter[str] = Counter()

    for phase in phases:
        if not isinstance(phase, Mapping):
            raise CampaignQualityIntegrityError("plan.phases contains a non-object entry")
        phase_id = str(phase["phase_id"])
        result = phase_result_by_id[phase_id]
        _assert_exact(result.get("run_id"), phase.get("run_id"), label=f"{phase_id}.run_id")
        _assert_exact(
            result.get("symbol_plan_path"),
            str(symbol_plan_path),
            label=f"{phase_id}.symbol_plan_path",
        )
        _assert_exact(
            result.get("symbol_plan_sha256"),
            symbol_plan_sha256,
            label=f"{phase_id}.symbol_plan_sha256",
        )
        phase_root = Path(str(phase["output_namespace"])).expanduser().resolve()
        _assert_inside(phase_root, campaign_root, label=f"{phase_id} namespace")
        expected_phase_manifest = (phase_root / f"ws_collect_{phase['run_id']}.json").resolve()
        observed_phase_manifest = Path(str(result.get("manifest_path") or "")).expanduser().resolve()
        _assert_exact(
            observed_phase_manifest,
            expected_phase_manifest,
            label=f"{phase_id}.manifest_path",
        )
        expected_sha = str(result.get("manifest_sha256") or "").lower()
        if len(expected_sha) != 64:
            raise CampaignQualityIntegrityError(f"{phase_id}.manifest_sha256 is invalid")
        observed_sha = sha256_file(observed_phase_manifest)
        _assert_exact(observed_sha, expected_sha, label=f"{phase_id}.manifest_sha256")
        phase_manifest = _read_json(observed_phase_manifest)
        _assert_exact(phase_manifest.get("schema"), PHASE_MANIFEST_SCHEMA, label=f"{phase_id}.schema")
        _assert_exact(phase_manifest.get("run_id"), phase.get("run_id"), label=f"{phase_id}.manifest_run_id")
        phase_bindings.append({"phase_id": phase_id, "path": str(observed_phase_manifest), "sha256": observed_sha})
        if (
            phase_manifest.get("runtime_completed") is not True
            or phase_manifest.get("liveness_clean") is not True
            or phase_manifest.get("quality_eligible") is not True
            or phase_manifest.get("dirty_segment_ids") not in ([], None)
            or phase_manifest.get("completed") is not True
            or phase_manifest.get("final") is not True
        ):
            return _stopped_report(
                plan=plan,
                contract=contract,
                campaign_manifest_path=manifest_path,
                campaign_manifest_sha256=manifest_sha,
                reasons=[f"phase_manifest_incomplete:{phase_id}"],
            )
        phase_duration_actual = _as_float(phase_manifest.get("actual_duration_sec"))
        if phase_duration_actual is None:
            raise CampaignQualityIntegrityError(
                f"{phase_id}.actual_duration_sec is invalid"
            )
        _assert_number_equal(
            phase_manifest.get("requested_duration_sec"),
            phase.get("writer_duration_sec"),
            label=f"{phase_id}.requested_duration_sec",
        )
        _assert_number_equal(
            result.get("actual_duration_sec"),
            phase_duration_actual,
            label=f"{phase_id}.result_actual_duration_sec",
        )
        phase_total_events = phase_manifest.get("total_events")
        if isinstance(phase_total_events, bool) or not isinstance(
            phase_total_events, int
        ):
            raise CampaignQualityIntegrityError(f"{phase_id}.total_events is invalid")
        _assert_exact(
            result.get("total_events"),
            phase_total_events,
            label=f"{phase_id}.result_total_events",
        )
        writer_duration_actual += phase_duration_actual
        campaign_total_events += phase_total_events
        for counter_name in (
            "transport_rows",
            "market_envelope_rows",
            "normalized_events",
            "control_rows",
            "unclassified_messages",
            "market_silence_events",
            "reconnect_attempts",
        ):
            value = phase_manifest.get(counter_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CampaignQualityIntegrityError(
                    f"{phase_id}.{counter_name} is invalid"
                )
            _assert_exact(
                result.get(counter_name),
                value,
                label=f"{phase_id}.result_{counter_name}",
            )
            campaign_counter_totals[counter_name] += value
        if (_as_float(phase_manifest.get("coverage_ratio")) or 0.0) < 0.99:
            phase_quality_reasons.append(f"phase_coverage:{phase_id}")
        if _error_count(phase_manifest.get("errors")):
            phase_quality_reasons.append(f"phase_errors:{phase_id}")

        segment_summaries = _as_sequence(
            phase_manifest.get("segments"),
            label=f"{phase_id}.segments",
        )
        if any(not isinstance(item, Mapping) for item in segment_summaries):
            raise CampaignQualityIntegrityError(
                f"{phase_id}.segments contains a non-object entry"
            )
        summary_names = [str(item.get("segment_dir") or "") for item in segment_summaries]
        if len(set(summary_names)) != len(summary_names):
            raise CampaignQualityIntegrityError(f"{phase_id}.segments contains duplicates")
        summary_by_name = {
            str(item.get("segment_dir") or ""): item for item in segment_summaries
        }
        full_segments = int(phase["full_segments_planned"])
        terminal_partial = int(phase.get("terminal_partial_sec") or 0)
        expected_segments = full_segments + (1 if terminal_partial > 0 else 0)
        _assert_exact(
            phase_manifest.get("segments_total"),
            expected_segments,
            label=f"{phase_id}.segments_total",
        )
        _assert_exact(
            phase_manifest.get("segments_with_manifest"),
            expected_segments,
            label=f"{phase_id}.segments_with_manifest",
        )
        _assert_exact(
            phase_manifest.get("segments_incomplete"),
            0,
            label=f"{phase_id}.segments_incomplete",
        )
        if len(segment_summaries) != expected_segments:
            raise CampaignQualityIntegrityError(
                f"{phase_id}.segment summary count mismatch"
            )
        if any(
            item.get("has_manifest") is not True
            or item.get("duration_completed") is not True
            or item.get("liveness_clean") is not True
            or item.get("quality_eligible") is not True
            or item.get("completed") is not True
            for item in segment_summaries
        ):
            raise CampaignQualityIntegrityError(
                f"{phase_id}.segment summary is not final"
            )
        summary_total_events = sum(
            int(item.get("total_events") or 0) for item in segment_summaries
        )
        _assert_exact(
            summary_total_events,
            phase_total_events,
            label=f"{phase_id}.segment_total_events",
        )
        for index in range(1, full_segments + 1):
            segment_name = f"seg_{index:03d}"
            summary = summary_by_name.get(segment_name)
            if summary is None:
                raise CampaignQualityIntegrityError(
                    f"full segment summary is missing: {phase_id}/{segment_name}"
                )
            segment_report = _evaluate_segment(
                phase=phase,
                segment_index=index,
                segment_summary=summary,
                contract=contract,
                expected_symbols_by_exchange=expected_symbols_by_exchange,
            )
            segment_reports.append(segment_report)
            if segment_report["valid"]:
                for venue, bases in segment_report["metrics"].get(
                    "bases_by_venue", {}
                ).items():
                    campaign_bases[venue].update(bases)

    _assert_exact(
        manifest.get("total_events"),
        campaign_total_events,
        label="campaign total_events",
    )
    for counter_name, expected_total in campaign_counter_totals.items():
        _assert_exact(
            manifest.get(counter_name),
            expected_total,
            label=f"campaign {counter_name}",
        )
    _assert_number_equal(
        manifest.get("writer_duration_actual_sec"),
        writer_duration_actual,
        label="campaign writer_duration_actual_sec",
        tolerance=0.01,
    )

    segment_contract = contract["segment_validity_contract"]
    rules = segment_contract["valid_segment_rules"]
    minimums = segment_contract["campaign_minimums"]
    required_venues = [str(item).lower() for item in rules["required_venues"]]
    valid_segments = sum(1 for item in segment_reports if item["valid"])
    campaign_coverage, campaign_matched_bases, campaign_venue_counts = _dual_venue_coverage(
        campaign_bases,
        required_venues,
    )
    campaign_reasons = list(phase_quality_reasons)
    if valid_segments < int(minimums["valid_full_segments"]):
        campaign_reasons.append("campaign_valid_full_segments")
    required_writer_sec = float(minimums["writer_duration_sec"])
    if writer_duration_actual < required_writer_sec * float(rules["actual_duration_ratio_min"]):
        campaign_reasons.append("campaign_writer_duration")
    if campaign_coverage < float(minimums["dual_venue_coverage"]):
        campaign_reasons.append("campaign_dual_venue_coverage")
    campaign_reasons = sorted(set(campaign_reasons))
    accepted = not campaign_reasons
    decision = "DATA_READY_FOR_TRAIN_ONLY_REVIEW" if accepted else "REJECT_DATA_QUALITY"

    report = {
        "schema": QUALITY_SCHEMA,
        "mode": "campaign_data_quality",
        "campaign_id": plan["campaign_id"],
        "plan_hash": plan["plan_hash"],
        "contract_hash": contract["contract_hash"],
        "candidate_contract_hash": candidate_hash,
        "accepted": accepted,
        "decision": decision,
        "reasons": campaign_reasons,
        "inputs": {
            "campaign_manifest": {"path": str(manifest_path), "sha256": manifest_sha},
            "symbol_plan": {
                "path": str(symbol_plan_path),
                "sha256": symbol_plan_sha256,
            },
            "phase_manifests": phase_bindings,
        },
        "metrics": {
            "full_segments_evaluated": len(segment_reports),
            "valid_full_segments": valid_segments,
            "invalid_full_segments": len(segment_reports) - valid_segments,
            "writer_duration_actual_sec": writer_duration_actual,
            "writer_duration_required_sec": required_writer_sec,
            "dual_venue_coverage": campaign_coverage,
            "matched_bases": campaign_matched_bases,
            "venue_base_counts": campaign_venue_counts,
        },
        "segments": segment_reports,
        "deferred_gates": [
            "causal_regime_labels",
            "eligible_execution_snapshots",
            "immutable_signal_and_evaluator_contract",
        ],
        "next_allowed_action": (
            "RUN_CAUSAL_REGIME_AND_EXECUTION_SNAPSHOT_MATERIALIZATION"
            if accepted
            else "STOP_PIPELINE_USER_REVIEW_REQUIRED"
        ),
        "safety": _safety_flags(),
    }
    return _finalize_report(report)


def run_campaign_quality_file(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    campaign_manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = _read_json(resolved_plan)
    _assert_exact(plan.get("schema"), PLAN_SCHEMA, label="plan.schema")
    _assert_exact(plan.get("plan_hash"), expected_plan_hash, label="ExpectedPlanHash")
    contract_ref = plan.get("contract")
    if not isinstance(contract_ref, Mapping):
        raise CampaignQualityIntegrityError("plan.contract is missing")
    contract_path = Path(str(contract_ref.get("path") or "")).expanduser().resolve()
    contract = _read_json(contract_path)
    try:
        validate_contract(contract, verify_files=True)
        validate_plan(plan, contract=contract, verify_files=True)
    except (OSError, ValueError) as exc:
        raise CampaignQualityIntegrityError(f"immutable bundle validation failed: {exc}") from exc

    tool_binding = (
        plan.get("launch_controls", {}).get("tools", {}).get("campaign_quality")
        if isinstance(plan.get("launch_controls"), Mapping)
        else None
    )
    if not isinstance(tool_binding, Mapping):
        raise CampaignQualityIntegrityError("PlanOnly does not bind campaign_quality")
    this_file = Path(__file__).resolve()
    _assert_exact(
        Path(str(tool_binding.get("path") or "")).expanduser().resolve(),
        this_file,
        label="campaign_quality tool path",
    )
    _assert_exact(tool_binding.get("sha256"), sha256_file(this_file), label="campaign_quality tool hash")

    report = evaluate_validated_campaign_quality(
        plan=plan,
        contract=contract,
        campaign_manifest_path=campaign_manifest_path,
    )
    campaign_root = Path(str(plan["outputs"]["campaign_root"])).expanduser().resolve()
    resolved_output = Path(output_path).expanduser().resolve()
    _assert_inside(resolved_output, campaign_root, label="quality output")
    _write_json_immutable(resolved_output, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hash-bound dense WS campaign data-quality gate")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--campaign-manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run_campaign_quality_file(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            campaign_manifest_path=args.campaign_manifest,
            output_path=args.output,
        )
    except (CampaignQualityIntegrityError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": QUALITY_SCHEMA,
                    "status": "INTEGRITY_CONFLICT",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
