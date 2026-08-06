from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


CONTRACT_SCHEMA = "trading_mvp_dense_ws_microstructure_contract_v1"
PLAN_SCHEMA = "trading_mvp_dense_ws_campaign_planonly_v1"
VALIDATION_SCHEMA = "trading_mvp_dense_ws_campaign_validation_v1"
CAMPAIGN_ID = "dense_ws_microstructure_regime_filter_v1_20260731_weekend"
HYPOTHESIS_ID = "dense_ws_microstructure_regime_filter_v1"
DATA_TYPE = "DENSE_WS_SEGMENTED"
EXPECTED_VENUES = ("mexc", "gateio")
EXPECTED_UNIVERSE_SHA256 = (
    "ce3d78cac3aa084a23376ee26a39c8fc98655a262a701c0d4d5f00469f2bafe3"
)
EXPECTED_UNIVERSE_ROWS = 1_388
EXPECTED_CANDIDATE_HASH = (
    "4cebe947e9997df1ae061231bd24a78d10bb7735697a259bf2eabd7a6bbb1386"
)
EXPECTED_FEASIBILITY_SCHEMA = "trading_mvp_dense_ws_campaign_feasibility_v1"
EXPECTED_FEASIBILITY_VERDICT = "FEASIBILITY_CONFIRMED_CONTRACT_FREEZE_REQUIRED"
EXPECTED_WRITER_SEC = 86_400
EXPECTED_SEGMENT_SEC = 3_600
EXPECTED_MAX_RUNTIME_SEC = 89_700
EXPECTED_START_LOCAL = "2026-07-31T19:00:00+03:00"
EXPECTED_WRITER_DEADLINE_LOCAL = "2026-08-03T07:45:00+03:00"
EXPECTED_HARD_DEADLINE_LOCAL = "2026-08-03T08:00:00+03:00"
EXPECTED_WINDOW_ID = "WEEKEND_2026-07-31_2026-08-03"
AUTHORIZATION_SCOPE = (
    "contract-freeze and immutable PlanOnly only; not campaign launch approval"
)
CONTRACT_NEXT_ACTION = "build_and_validate_hash_bound_campaign_planonly_without_start"
PLAN_CONTROLS_NEXT_ACTION = (
    "implement_hash_bound_visible_campaign_controls_without_start"
)
PLAN_APPROVAL_NEXT_ACTION = "request_exact_hash_bound_campaign_approval_at_due_window"
PLAN_OPERATIONAL_REVIEW_NEXT_ACTION = (
    "revise_zero_headroom_timing_before_approval"
)
CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED = (
    "CONTROLS_IMPLEMENTED_OPERATIONAL_REVIEW_REQUIRED"
)
EXPECTED_PHASES = (
    {
        "phase_id": "phase_01",
        "start_local": "2026-07-31T19:00:00+03:00",
        "end_local": "2026-08-01T00:45:00+03:00",
        "writer_duration_sec": 20_700,
        "complete_durable_segments": 5,
    },
    {
        "phase_id": "phase_02",
        "start_local": "2026-08-01T01:40:00+03:00",
        "end_local": "2026-08-01T19:55:00+03:00",
        "writer_duration_sec": 65_700,
        "complete_durable_segments": 18,
    },
)

# ── V3 timing constants (headroom-adjusted) ──────────────────────────
# These constants fix the ZERO_RUNTIME_HEADROOM blocker by reserving
# 900 s of startup/shutdown headroom per phase.  The original
# EXPECTED_PHASES / EXPECTED_WRITER_SEC remain frozen to the v1
# feasibility artifact on the E: drive.
V3_MIN_PHASE_HEADROOM_SEC = 900
V3_EXPECTED_PHASES = (
    {
        "phase_id": "phase_01",
        "start_local": "2026-07-31T19:00:00+03:00",
        "end_local": "2026-08-01T00:45:00+03:00",
        "writer_duration_sec": 19_800,
        "complete_durable_segments": 5,
    },
    {
        "phase_id": "phase_02",
        "start_local": "2026-08-01T01:40:00+03:00",
        "end_local": "2026-08-01T19:55:00+03:00",
        "writer_duration_sec": 64_800,
        "complete_durable_segments": 18,
    },
)
V3_EXPECTED_WRITER_SEC = 84_600
# max_runtime_sec unchanged — the overall campaign window is the same.
V3_EXPECTED_MAX_RUNTIME_SEC = EXPECTED_MAX_RUNTIME_SEC

LEGACY_PROFILE = "LEGACY_CONTRACT_FREEZE_V1"
AEF_PROFILE = "ACCELERATED_EVIDENCE_FACTORY_V1"
AEF_CAMPAIGN_ID = "dense_ws_microstructure_regime_filter_v1_20260804_aef_24h"
AEF_EXPECTED_CANDIDATE_HASH = (
    "a1d262d1cf5ef1c70771ab9005b12eb0d875ff5235492ffadf8e1af4790a8643"
)
AEF_EXPECTED_WINDOW_ID = "EVIDENCE_EXCEPTION_2026-08-04_24H"
AEF_EXPECTED_WRITER_SEC = 86_400
AEF_EXPECTED_MAX_RUNTIME_SEC = 88_200
AEF_EXPECTED_START_LOCAL = "2026-08-04T01:40:00+03:00"
AEF_EXPECTED_WRITER_DEADLINE_LOCAL = "2026-08-05T01:40:00+03:00"
AEF_EXPECTED_HARD_DEADLINE_LOCAL = "2026-08-05T02:10:00+03:00"
AEF_SUPPRESSED_PIT_RUN_IDS = ("pit_universe_v2_forward_20260805_n08",)
AEF_HARD_OUTPUT_CAP_BYTES = 25_000_000_000
AEF_EXPECTED_PHASES = (
    {
        "phase_id": "phase_01",
        "start_local": "2026-08-04T01:40:00+03:00",
        "end_local": "2026-08-05T01:40:00+03:00",
        "hard_end_local": "2026-08-05T02:10:00+03:00",
        "writer_duration_sec": 86_400,
        "complete_durable_segments": 24,
    },
)


def _profile_spec(profile: str | None) -> dict[str, Any]:
    resolved = profile or LEGACY_PROFILE
    if resolved == LEGACY_PROFILE:
        return {
            "profile": LEGACY_PROFILE,
            "campaign_id": CAMPAIGN_ID,
            "candidate_hash": EXPECTED_CANDIDATE_HASH,
            "window_id": EXPECTED_WINDOW_ID,
            "start_local": EXPECTED_START_LOCAL,
            "writer_deadline_local": EXPECTED_WRITER_DEADLINE_LOCAL,
            "hard_deadline_local": EXPECTED_HARD_DEADLINE_LOCAL,
            "writer_sec": EXPECTED_WRITER_SEC,
            "max_runtime_sec": EXPECTED_MAX_RUNTIME_SEC,
            "phases": EXPECTED_PHASES,
            "global_claim_binding_required": False,
        }
    if resolved == AEF_PROFILE:
        return {
            "profile": AEF_PROFILE,
            "campaign_id": AEF_CAMPAIGN_ID,
            "candidate_hash": AEF_EXPECTED_CANDIDATE_HASH,
            "window_id": AEF_EXPECTED_WINDOW_ID,
            "start_local": AEF_EXPECTED_START_LOCAL,
            "writer_deadline_local": AEF_EXPECTED_WRITER_DEADLINE_LOCAL,
            "hard_deadline_local": AEF_EXPECTED_HARD_DEADLINE_LOCAL,
            "writer_sec": AEF_EXPECTED_WRITER_SEC,
            "max_runtime_sec": AEF_EXPECTED_MAX_RUNTIME_SEC,
            "phases": AEF_EXPECTED_PHASES,
            "global_claim_binding_required": True,
            "uninterrupted_required": True,
            "suppressed_pit_run_ids": AEF_SUPPRESSED_PIT_RUN_IDS,
        }
    raise ValueError(f"unsupported dense WS factory profile: {resolved!r}")



def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_contract_hash(contract: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in contract.items() if key != "contract_hash"}
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def canonical_plan_hash(plan: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_bytes_immutable(path: str | Path, data: bytes) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(target, flags)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _parse_datetime(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _assert_exact(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} must remain frozen at {expected!r}; got {actual!r}")


def _assert_false_flags(payload: Mapping[str, Any], *, label: str) -> None:
    for key in (
        "actual_collection_allowed",
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
        if payload.get(key) is not False:
            raise ValueError(f"{label}.{key} must remain false")


def _assert_feasibility_false_flags(payload: Mapping[str, Any], *, label: str) -> None:
    for key in (
        "actual_collection_allowed",
        "network_access",
        "returns_read",
        "pnl_computed",
        "oos_read",
        "grid_or_retune",
        "live_orders",
        "private_api_keys",
        "leverage_or_margin",
    ):
        if payload.get(key) is not False:
            raise ValueError(f"{label}.{key} must remain false")


def _verify_file_binding(binding: Mapping[str, Any], *, label: str) -> None:
    path = Path(str(binding.get("path") or "")).expanduser().resolve()
    expected = str(binding.get("sha256") or "").lower()
    if len(expected) != 64:
        raise ValueError(f"{label}.sha256 is invalid")
    if not path.is_file():
        raise FileNotFoundError(f"{label}.path is missing: {path}")
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(
            f"{label} hash mismatch: expected={expected} observed={observed}"
        )


def _universe_row_count(path: str | Path) -> int:
    with (
        Path(path)
        .expanduser()
        .resolve()
        .open("r", encoding="utf-8-sig", newline="") as handle
    ):
        rows = list(csv.DictReader(handle))
    return len(rows)


def _source_binding(path: str | Path) -> dict[str, str]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    return {"path": str(target), "sha256": sha256_file(target)}


def _expected_launch_tool_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[2]
    return {
        "launcher": (root / "tools" / "start_dense_ws_campaign_visible.ps1").resolve(),
        "status": (root / "tools" / "get_dense_ws_campaign_status.ps1").resolve(),
        "stop": (root / "tools" / "stop_dense_ws_campaign.ps1").resolve(),
        "runner": (
            root / "trading_mvp" / "src" / "dense_ws_campaign_runner.py"
        ).resolve(),
        "global_writer_claim": (
            root / "trading_mvp" / "src" / "global_market_writer_claim.py"
        ).resolve(),
        "campaign_quality": (
            root / "trading_mvp" / "src" / "dense_ws_campaign_quality.py"
        ).resolve(),
        "causal_materializer": (
            root / "trading_mvp" / "src" / "dense_ws_causal_materializer.py"
        ).resolve(),
    }


def _launch_control_commands(tools: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    plan_path = "<immutable_plan_path>"
    plan_hash = "<expected_plan_hash>"
    launcher = str(tools["launcher"]["path"])
    status = str(tools["status"]["path"])
    stop = str(tools["stop"]["path"])
    return {
        "preflight_command": (
            f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{launcher}" '
            f'-PlanPath "{plan_path}" -ExpectedPlanHash "{plan_hash}" '
            "-PreflightOnly -Json"
        ),
        "visible_command_after_approval": (
            f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{launcher}" '
            f'-PlanPath "{plan_path}" -ExpectedPlanHash "{plan_hash}" '
            "-ConfirmedLongCampaign -Json"
        ),
        "status_command": (
            f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{status}" '
            f'-PlanPath "{plan_path}" -ExpectedPlanHash "{plan_hash}" -Json'
        ),
        "stop_command": (
            f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{stop}" '
            f'-PlanPath "{plan_path}" -ExpectedPlanHash "{plan_hash}" -Json'
        ),
    }


def _candidate_from_feasibility(
    feasibility: Mapping[str, Any],
    *,
    expected_candidate_hash: str,
) -> dict[str, Any]:
    if feasibility.get("schema") != EXPECTED_FEASIBILITY_SCHEMA:
        raise ValueError("unsupported dense WS feasibility schema")
    _assert_exact(feasibility.get("mode"), "PlanOnly", label="feasibility.mode")
    _assert_feasibility_false_flags(feasibility, label="feasibility")
    _assert_exact(
        feasibility.get("verdict"),
        EXPECTED_FEASIBILITY_VERDICT,
        label="feasibility.verdict",
    )
    if feasibility.get("feasibility_reasons"):
        raise ValueError("feasibility artifact contains blocking reasons")
    candidate = feasibility.get("frozen_candidate")
    if not isinstance(candidate, dict):
        raise ValueError("feasibility.frozen_candidate is missing")
    observed = _sha256_bytes(_canonical_json(candidate).encode("utf-8"))
    embedded = str(feasibility.get("candidate_contract_hash") or "").lower()
    expected = expected_candidate_hash.lower()
    if observed != embedded or observed != expected:
        raise ValueError(
            "candidate contract hash mismatch: "
            f"computed={observed} embedded={embedded} expected={expected}"
        )
    return dict(candidate)


def _assert_candidate_profile(
    candidate: Mapping[str, Any],
    *,
    spec: Mapping[str, Any],
) -> None:
    for key, expected in (
        ("hypothesis_id", HYPOTHESIS_ID),
        ("data_type", DATA_TYPE),
        ("window_id", spec["window_id"]),
        ("requested_start_local", spec["start_local"]),
        ("writer_deadline_local", spec["writer_deadline_local"]),
        ("hard_deadline_local", spec["hard_deadline_local"]),
        ("target_writer_sec", spec["writer_sec"]),
        ("segment_sec", EXPECTED_SEGMENT_SEC),
        ("phases", list(spec["phases"])),
    ):
        observed = int(candidate.get(key) or 0) if key in {
            "target_writer_sec",
            "segment_sec",
        } else candidate.get(key)
        _assert_exact(observed, expected, label=f"candidate.{key}")
    if spec["profile"] == AEF_PROFILE:
        _assert_exact(
            candidate.get("uninterrupted_required"),
            spec["uninterrupted_required"],
            label="candidate.uninterrupted_required",
        )
        _assert_exact(
            candidate.get("suppressed_pit_run_ids"),
            list(spec["suppressed_pit_run_ids"]),
            label="candidate.suppressed_pit_run_ids",
        )


def _assert_resource_profile(
    feasibility: Mapping[str, Any],
    *,
    spec: Mapping[str, Any],
) -> None:
    if spec["profile"] != AEF_PROFILE:
        return
    estimate = feasibility.get("resource_estimate")
    if not isinstance(estimate, Mapping):
        raise ValueError("feasibility.resource_estimate is missing")
    hard_cap = int(estimate.get("hard_output_cap_bytes") or 0)
    estimated_disk = int(estimate.get("estimated_disk_bytes") or 0)
    _assert_exact(
        hard_cap,
        AEF_HARD_OUTPUT_CAP_BYTES,
        label="feasibility.resource_estimate.hard_output_cap_bytes",
    )
    if estimated_disk <= 0 or estimated_disk > hard_cap:
        raise ValueError(
            "feasibility estimated disk must be positive and within the AEF hard cap"
        )


def _frozen_raw_contract() -> dict[str, Any]:
    return {
        "format": "UTF-8 JSONL, one event envelope per line",
        "append_only": True,
        "outer_fields_exact": [
            "recv_ts",
            "exchange",
            "event_type",
            "channel",
            "symbol",
            "payload",
        ],
        "field_contract": {
            "recv_ts": "finite Unix seconds at local receipt; causal availability time",
            "exchange": list(EXPECTED_VENUES),
            "event_type": "non-empty string",
            "channel": "string or null",
            "symbol": "string or null for control/binary frames",
            "payload": {
                "type": "object",
                "encoding": ["json", "text", "base64"],
                "json_or_text_fields": ["encoding", "data"],
                "base64_fields": ["encoding", "byte_length", "data"],
            },
        },
        "timestamp_contract": {
            "causal_availability_ts": "recv_ts",
            "decoded_exchange_ts_use": (
                "metadata only; never makes an event available before recv_ts"
            ),
            "event_order": "stable ascending recv_ts then source file then line number",
            "out_of_order_policy": "segment invalid for the affected market",
            "future_timestamp_policy": "reject affected row; never clamp backward",
        },
        "required_normalized_event_kinds": ["bbo", "depth", "trade"],
        "shared_market_classifier_contract": {
            "implementation": "ws_normalizer.classify_ws_row",
            "exact_venue_symbol_channel_match": True,
            "mexc": (
                "protobuf wrapper, channel, symbol and body type must match the "
                "exact subscription; market values are finite and positive; "
                "BBO ask must not be below bid"
            ),
            "gateio": (
                "event=update with exact subscribed channel and symbol; market "
                "values are finite and positive; BBO ask must not be below bid"
            ),
            "control_or_malformed_rows_are_market": False,
        },
        "row_accounting_contract": {
            "transport_rows": "all non-empty raw lines",
            "market_envelope_rows": (
                "raw rows producing at least one structurally valid exact market event"
            ),
            "normalized_events": "all valid normalized events from market envelopes",
            "control_rows": "recognized service rows producing no market event",
            "unclassified_messages": "all other structurally invalid or unknown rows",
            "total_events_compatibility": "transport_rows only",
            "raw_rows_min_applies_to": "market_envelope_rows",
        },
        "writer_flush_every_events": 100,
        "raw_mutation_after_segment_final": "forbidden",
    }


def _frozen_universe_contract(
    universe_path: str | Path,
    *,
    universe_sha256: str,
    universe_rows: int,
) -> dict[str, Any]:
    return {
        "source": {
            "path": str(Path(universe_path).expanduser().resolve()),
            "sha256": universe_sha256,
            "rows": universe_rows,
            "required_columns": [
                "rank",
                "symbol",
                "name",
                "coin_id",
                "market_cap_usd",
                "price_usd",
            ],
        },
        "venues": list(EXPECTED_VENUES),
        "quote": "USDT",
        "market_type": "spot",
        "selection": {
            "source_order": "numeric rank ascending, then immutable CSV row order",
            "symbol_normalization": "trim and uppercase",
            "deduplication": "first normalized symbol wins",
            "max_source_symbols_considered": 300,
            "max_pairs_per_venue": 16,
            "venue_selection": (
                "first active public spot USDT market matching each ordered source "
                "base; selection is independent per venue"
            ),
            "pair_format": {"mexc": "<BASE>USDT", "gateio": "<BASE>_USDT"},
        },
        "exclusions": [
            "empty or duplicate normalized base",
            "base outside the immutable 1388-row source",
            "inactive, non-spot or non-USDT market at launch discovery",
            "leveraged-token suffix 3L, 3S, 5L, 5S, UP, DOWN, BULL or BEAR",
            "Binance venue or Binance execution/reference dependency",
        ],
        "dual_venue_coverage": {
            "formula": "matched_base_count / min(mexc_base_count, gateio_base_count)",
            "minimum": 0.80,
            "minimum_pairs_each_venue": 10,
            "failure_action": "stop before first evidence segment is accepted",
        },
        "discovery_is_not_contract_change": (
            "public launch-time availability may only remove candidates under the "
            "frozen rules; it cannot reorder, add or substitute a base"
        ),
    }


def _frozen_segment_contract() -> dict[str, Any]:
    return {
        "full_segment_sec": EXPECTED_SEGMENT_SEC,
        "terminal_partial_segment_min_sec": 900,
        "terminal_partial_counts_toward_min_valid_segments": False,
        "valid_segment_rules": {
            "manifest_completed": True,
            "manifest_final": True,
            "actual_duration_ratio_min": 0.99,
            "required_venues": list(EXPECTED_VENUES),
            "result_errors_max": 0,
            "raw_files_min_per_venue": 1,
            "raw_rows_min": 600,
            "json_parse_error_rate_max": 0.001,
            "malformed_envelope_rate_max": 0.001,
            "normalized_required_event_kinds": ["bbo", "depth", "trade"],
            "market_max_gap_sec": 300,
            "dual_venue_coverage_min": 0.80,
            "out_of_order_rows_max": 0,
        },
        "campaign_minimums": {
            "writer_duration_sec": EXPECTED_WRITER_SEC,
            "valid_full_segments": 8,
            "dual_venue_coverage": 0.80,
            "eligible_execution_snapshots": 180,
        },
        "gap_policy": {
            "pit_blackouts_are_planned_gaps": True,
            "planned_gaps_do_not_count_as_writer_time": True,
            "unplanned_gap_sec_max_per_valid_segment": 300,
            "invalid_segments_are_never_stitched_as_valid_evidence": True,
        },
        "connection_liveness_contract": {
            "market_silence_reconnect_sec": 120,
            "elapsed_clock": "time.monotonic",
            "timer_starts_after_exact_subscriptions_are_sent": True,
            "refresh_rule": (
                "at least one structurally valid normalized event matching the exact "
                "subscribed venue, symbol and channel"
            ),
            "control_ack_ping_pong_unknown_foreign_empty_or_malformed_refresh": False,
            "silence_action": (
                "write market_silence_detected, close, reconnect and resubscribe "
                "without extending the original deadline"
            ),
            "silence_marks_segment_dirty": True,
        },
        "segment_state_contract": {
            "duration_completed": "requested segment elapsed duration was reached",
            "liveness_clean": (
                "no market silence breach, unresolved connection error or classifier integrity error"
            ),
            "quality_eligible": (
                "duration_completed and liveness_clean and result error limit passes"
            ),
            "legacy_completed_equals": "quality_eligible",
            "dirty_duration_completed_segment": "diagnostic-only; continue next segment",
            "stitched_fields": [
                "runtime_completed",
                "liveness_clean",
                "quality_eligible",
                "dirty_segment_ids",
            ],
        },
        "expected_subscription_quality_contract": {
            "source": "<campaign_root>/_control/symbol-plan.json",
            "symbol_plan_sha256_required": True,
            "identity_fields": [
                "campaign_id",
                "plan_hash",
                "contract_hash",
                "universe_sha256",
                "symbols_by_exchange",
                "symbols_arg",
            ],
            "bbo_and_depth_required_per_expected_market": True,
            "trade_subscription_required_per_expected_market": True,
            "per_market_trade_gap_required": False,
            "missing_market_reason": "missing_market:<exchange>:<symbol>",
        },
        "segment_time_boundary_contract": {
            "finite_start_and_finish_required": True,
            "finish_after_start_required": True,
            "duration_agreement_tolerance_sec": 2.0,
            "recv_ts_closed_interval_required": True,
            "max_gap_includes": ["leading", "internal", "trailing"],
            "exactly_market_max_gap_sec_allowed": True,
        },
    }


def _frozen_regime_contract() -> dict[str, Any]:
    return {
        "observation_grid_sec": 5,
        "label_interval_sec": 60,
        "warmup_sec": 3_600,
        "trailing_reference_window_sec": 3_600,
        "current_feature_window_sec": 300,
        "minimum_reference_observations_per_venue_base": 360,
        "scheduled_observation_contract": {
            "alignment": "UTC epoch timestamp modulo 5 seconds equals zero",
            "quote_selection": "latest BBO with recv_ts <= sample_ts",
            "freshness_source": "execution_sampling_contract.max_quote_age_ms",
            "missing_or_stale_counts_as_fresh": False,
            "planned_blackout_samples_materialized": False,
        },
        "statistics_contract": {
            "quantile_method": "linear_type_7",
            "reference_spread_population": "fresh scheduled observations in [t-3600,t)",
            "reference_top_notional_population": "fresh scheduled observations in [t-3600,t)",
            "current_spread_population": "fresh scheduled observations in [t-300,t)",
            "current_top_notional_population": "fresh scheduled observations in [t-300,t)",
            "quote_update_definition": "distinct BBO state changes by causal recv_ts",
            "current_update_rate": "distinct updates in [t-300,t) divided by 5 minutes",
            "reference_update_population": "60 non-overlapping one-minute update rates in [t-3600,t)",
            "window_boundaries": "half-open; events at t are excluded from label features",
        },
        "feature_definition": {
            "fresh_sample_ratio": (
                "fresh 5-second BBO observations / scheduled observations"
            ),
            "spread_bps": "(ask - bid) / ((ask + bid) / 2) * 10000",
            "top_notional_quote": ("min(bid_price * bid_qty, ask_price * ask_qty)"),
            "quote_updates_per_minute": (
                "distinct causally available BBO state changes / elapsed minutes"
            ),
        },
        "causal_clock": {
            "label_ts": "UTC epoch minute boundary t",
            "reference_window": "[t-3600, t)",
            "current_window": "[t-300, t)",
            "label_effective_ts": "t",
            "future_rows_allowed": False,
            "labels_may_be_rewritten_after_t": False,
            "cross_segment_state": (
                "carry only finalized past observations; planned blackout time "
                "contains no synthetic observations"
            ),
        },
        "venue_dense_rule": {
            "fresh_sample_ratio_min": 0.80,
            "current_median_spread_lte_reference_quantile": 0.40,
            "current_p25_top_notional_gte_reference_quantile": 0.60,
            "current_median_update_rate_gte_reference_quantile": 0.60,
            "all_conditions_required": True,
        },
        "labels": [
            "WARMUP_INVALID",
            "STALE_OR_INCOMPLETE",
            "DENSE_BOTH",
            "DENSE_MEXC_ONLY",
            "DENSE_GATE_ONLY",
            "NON_DENSE_BOTH",
        ],
        "combined_label_rule": (
            "DENSE_BOTH only when both venue-specific rules pass at the same "
            "label_ts; stale or missing venue state always yields STALE_OR_INCOMPLETE"
        ),
        "post_hoc_label_selection": False,
        "parameter_combinations": 1,
    }


def _frozen_execution_contract() -> dict[str, Any]:
    return {
        "sample_clock": "UTC epoch boundaries where timestamp modulo 5 seconds is zero",
        "sample_interval_sec": 5,
        "quote_selection": (
            "latest BBO with recv_ts <= sample_ts; never nearest or forward-filled "
            "from a future row"
        ),
        "max_quote_age_ms": {"mexc": 6_000, "gateio": 5_000},
        "max_cross_venue_recv_ts_skew_ms": 2_000,
        "max_spread_bps_each_venue": 3.0,
        "min_top_notional_quote_each_side": 25.0,
        "eligible_regime": "DENSE_BOTH",
        "one_snapshot_per_base_per_boundary": True,
        "stale_or_incomplete_snapshot_action": "exclude and count by reason",
        "minimum_eligible_snapshots": 180,
        "execution_mode_for_future_evaluation": "taker_at_opposite_top_of_book",
        "maker_fill_or_queue_assumption": False,
    }


def _frozen_cost_risk_contract() -> dict[str, Any]:
    return {
        "cost": {
            "base_tier_only": True,
            "normal": {
                "round_trip_fee_bps": 39.0,
                "slippage_bps": 10.0,
                "inventory_rebalance_buffer_bps": 20.0,
                "total_cost_bps": 69.0,
            },
            "stress": {
                "round_trip_fee_bps": 39.0,
                "slippage_bps": 20.0,
                "inventory_rebalance_buffer_bps": 30.0,
                "total_cost_bps": 89.0,
            },
            "fee_tier_optimism": False,
            "maker_rebate_credit": False,
            "transfer_latency_benefit": False,
        },
        "risk": {
            "research_simulation_only": True,
            "direction": "long_only_spot_no_short",
            "notional_quote_per_synthetic_trade": 50.0,
            "max_concurrent_synthetic_positions": 3,
            "max_gross_synthetic_exposure_quote": 150.0,
            "max_holding_sec": 25,
            "cooldown_sec_per_base": 60,
            "one_position_per_base": True,
            "leverage": False,
            "margin": False,
            "real_capital": False,
        },
        "no_grid": {
            "parameter_combinations": 1,
            "grid_search": False,
            "retune": False,
            "threshold_selection_from_returns_or_pnl": False,
            "threshold_selection_from_oos": False,
        },
    }


def _frozen_evidence_contract() -> dict[str, Any]:
    return {
        "collection_decisions": [
            "DATA_READY_FOR_TRAIN_ONLY_REVIEW",
            "REJECT_DATA_QUALITY",
            "STOPPED_INCOMPLETE",
        ],
        "collection_can_accept_trading_hypothesis": False,
        "collection_can_open_oos": False,
        "collection_can_compute_returns_or_pnl": False,
        "future_split_if_separately_authorized": {
            "ordering": "valid observations sorted by causal sample_ts",
            "train_fraction": 0.70,
            "oos_fraction": 0.30,
            "split_type": "single contiguous chronological split",
            "embargo_sec": 300,
            "regime_parameters_refit_on_oos": False,
        },
        "future_edge_verdict_requires": [
            "separate hash-bound evaluator implementation",
            "separate explicit authorization before returns/PnL/OOS read",
            "net expectancy after frozen normal and stress costs",
            "profit factor, drawdown, sample size and liquidity/fill risk",
            "independent critical review for ACCEPT or terminal REJECT",
        ],
        "strategy_accepted": False,
    }


def build_contract(
    *,
    feasibility_path: str | Path,
    expected_feasibility_sha256: str,
    expected_candidate_hash: str,
    universe_path: str | Path,
    hypothesis_bank_path: str | Path,
    continuous_policy_path: str | Path,
    pit_schedule_path: str | Path,
    raw_writer_path: str | Path,
    durable_collector_path: str | Path,
    generated_at_utc: str,
    factory_profile: str = LEGACY_PROFILE,
    normalizer_path: str | Path | None = None,
    campaign_runner_path: str | Path | None = None,
    campaign_quality_path: str | Path | None = None,
    runtime_dependency_manifest_path: str | Path | None = None,
    refreeze_proposal_path: str | Path | None = None,
    expected_refreeze_proposal_hash: str | None = None,
    refreeze_approval_receipt_path: str | Path | None = None,
) -> dict[str, Any]:
    feasibility_target = Path(feasibility_path).expanduser().resolve()
    observed_feasibility_sha = sha256_file(feasibility_target)
    if observed_feasibility_sha != expected_feasibility_sha256.lower():
        raise ValueError("feasibility file hash mismatch")
    feasibility = _read_json(feasibility_target)
    candidate = _candidate_from_feasibility(
        feasibility,
        expected_candidate_hash=expected_candidate_hash,
    )
    spec = _profile_spec(factory_profile)
    _assert_exact(
        expected_candidate_hash.lower(),
        spec["candidate_hash"],
        label="expected_candidate_hash",
    )
    _assert_candidate_profile(candidate, spec=spec)
    _assert_resource_profile(feasibility, spec=spec)

    universe_target = Path(universe_path).expanduser().resolve()
    universe_sha = sha256_file(universe_target)
    universe_rows = _universe_row_count(universe_target)
    _assert_exact(
        universe_sha,
        EXPECTED_UNIVERSE_SHA256,
        label="universe.sha256",
    )
    _assert_exact(universe_rows, EXPECTED_UNIVERSE_ROWS, label="universe.rows")
    _assert_exact(
        str(candidate.get("universe_sha256") or "").lower(),
        universe_sha,
        label="candidate.universe_sha256",
    )
    _assert_exact(
        int(candidate.get("universe_rows") or 0),
        universe_rows,
        label="candidate.universe_rows",
    )

    hypothesis_binding = _source_binding(hypothesis_bank_path)
    continuous_binding = _source_binding(continuous_policy_path)
    pit_binding = _source_binding(pit_schedule_path)
    _assert_exact(
        hypothesis_binding["sha256"],
        str(candidate.get("hypothesis_bank_sha256") or "").lower(),
        label="candidate.hypothesis_bank_sha256",
    )
    _assert_exact(
        continuous_binding["sha256"],
        str(candidate.get("continuous_policy_sha256") or "").lower(),
        label="candidate.continuous_policy_sha256",
    )
    _assert_exact(
        pit_binding["sha256"],
        str(candidate.get("pit_schedule_sha256") or "").lower(),
        label="candidate.pit_schedule_sha256",
    )
    _parse_datetime(generated_at_utc, label="generated_at_utc")

    source_dir = Path(__file__).resolve().parent
    resolved_normalizer = normalizer_path or source_dir / "ws_normalizer.py"
    resolved_runner = campaign_runner_path or source_dir / "dense_ws_campaign_runner.py"
    resolved_quality = campaign_quality_path or source_dir / "dense_ws_campaign_quality.py"
    refreeze_values = (
        runtime_dependency_manifest_path,
        refreeze_proposal_path,
        expected_refreeze_proposal_hash,
        refreeze_approval_receipt_path,
    )
    collector_liveness_refreeze: dict[str, Any] | None = None
    if any(value is not None for value in refreeze_values):
        if any(value is None for value in refreeze_values):
            raise ValueError("collector liveness refreeze provenance must be complete")
        proposal_target = Path(str(refreeze_proposal_path)).expanduser().resolve()
        proposal = _read_json(proposal_target)
        embedded_proposal_hash = str(proposal.get("proposal_hash") or "").lower()
        recomputed_proposal_hash = _sha256_bytes(
            _canonical_json(
                {key: value for key, value in proposal.items() if key != "proposal_hash"}
            ).encode("utf-8")
        )
        expected_proposal_hash = str(expected_refreeze_proposal_hash).lower()
        if (
            recomputed_proposal_hash != embedded_proposal_hash
            or recomputed_proposal_hash != expected_proposal_hash
        ):
            raise ValueError("collector liveness refreeze proposal hash mismatch")
        approval_target = Path(str(refreeze_approval_receipt_path)).expanduser().resolve()
        approval = _read_json(approval_target)
        approval_proposal = approval.get("proposal")
        if not isinstance(approval_proposal, Mapping):
            raise ValueError("collector liveness approval proposal binding is missing")
        _assert_exact(
            approval_proposal.get("proposal_hash"),
            expected_proposal_hash,
            label="collector liveness approval proposal_hash",
        )
        authorized_scope = approval.get("authorized_scope")
        if not isinstance(authorized_scope, Mapping) or authorized_scope.get(
            "runtime_quality_contract_files_listed_in_proposal_only"
        ) is not True:
            raise ValueError("collector liveness refreeze approval scope is invalid")
        if approval.get("campaign_launch_authorized") is not False:
            raise ValueError("collector liveness approval must not authorize launch")
        collector_liveness_refreeze = {
            "proposal": _source_binding(proposal_target),
            "proposal_hash": expected_proposal_hash,
            "approval_receipt": _source_binding(approval_target),
            "runtime_dependency_manifest": _source_binding(
                str(runtime_dependency_manifest_path)
            ),
            "implementation_authorized": True,
            "collector_launch_authorized": False,
            "stopped_incomplete_retry_authorized": False,
        }

    contract: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "mode": "PlanOnly",
        "factory_profile": spec["profile"],
        "campaign_id": spec["campaign_id"],
        "hypothesis_id": HYPOTHESIS_ID,
        "data_type": DATA_TYPE,
        "generated_at_utc": generated_at_utc,
        "authorization_scope": AUTHORIZATION_SCOPE,
        "research_only": True,
        "actual_collection_allowed": False,
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
        "source_candidate": {
            "feasibility": {
                "path": str(feasibility_target),
                "sha256": observed_feasibility_sha,
            },
            "candidate_contract_hash": expected_candidate_hash.lower(),
            "frozen_candidate": candidate,
        },
        "source_bindings": {
            "hypothesis_bank": hypothesis_binding,
            "continuous_production_policy": continuous_binding,
            "pit_schedule": pit_binding,
            "raw_writer": _source_binding(raw_writer_path),
            "durable_collector": _source_binding(durable_collector_path),
            "normalizer_and_shared_classifier": _source_binding(resolved_normalizer),
            "campaign_runner": _source_binding(resolved_runner),
            "campaign_quality": _source_binding(resolved_quality),
            "campaign_contract": _source_binding(Path(__file__).resolve()),
        },
        "universe_contract": _frozen_universe_contract(
            universe_target,
            universe_sha256=universe_sha,
            universe_rows=universe_rows,
        ),
        "raw_schema_contract": _frozen_raw_contract(),
        "segment_validity_contract": _frozen_segment_contract(),
        "causal_regime_contract": _frozen_regime_contract(),
        "execution_sampling_contract": _frozen_execution_contract(),
        "cost_risk_no_grid_contract": _frozen_cost_risk_contract(),
        "evidence_and_acceptance_contract": _frozen_evidence_contract(),
        "next_allowed_action": CONTRACT_NEXT_ACTION,
    }
    if collector_liveness_refreeze is not None:
        contract["collector_liveness_refreeze"] = collector_liveness_refreeze
    contract["contract_hash"] = canonical_contract_hash(contract)
    validate_contract(contract, verify_files=True)
    return contract


def validate_contract(
    contract: Mapping[str, Any],
    *,
    verify_files: bool = False,
) -> None:
    profile_value = contract.get("factory_profile")
    spec = _profile_spec(str(profile_value) if profile_value else LEGACY_PROFILE)
    _assert_exact(contract.get("schema"), CONTRACT_SCHEMA, label="contract.schema")
    _assert_exact(contract.get("mode"), "PlanOnly", label="contract.mode")
    if profile_value is not None:
        _assert_exact(
            profile_value,
            spec["profile"],
            label="contract.factory_profile",
        )
    _assert_exact(
        contract.get("campaign_id"), spec["campaign_id"], label="contract.campaign_id"
    )
    _assert_exact(
        contract.get("hypothesis_id"),
        HYPOTHESIS_ID,
        label="contract.hypothesis_id",
    )
    _assert_exact(contract.get("data_type"), DATA_TYPE, label="contract.data_type")
    _parse_datetime(contract.get("generated_at_utc"), label="contract.generated_at_utc")
    _assert_exact(
        contract.get("authorization_scope"),
        AUTHORIZATION_SCOPE,
        label="contract.authorization_scope",
    )
    _assert_false_flags(contract, label="contract")
    if contract.get("research_only") is not True:
        raise ValueError("contract.research_only must remain true")
    observed_hash = str(contract.get("contract_hash") or "").lower()
    if canonical_contract_hash(contract) != observed_hash:
        raise ValueError("contract hash mismatch; frozen contract was modified")

    candidate = contract.get("source_candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("source_candidate is missing")
    _assert_exact(
        candidate.get("candidate_contract_hash"),
        spec["candidate_hash"],
        label="source_candidate.candidate_contract_hash",
    )
    frozen_candidate = candidate.get("frozen_candidate")
    if not isinstance(frozen_candidate, Mapping):
        raise ValueError("source_candidate.frozen_candidate is missing")
    recomputed_candidate_hash = _sha256_bytes(
        _canonical_json(frozen_candidate).encode("utf-8")
    )
    _assert_exact(
        recomputed_candidate_hash,
        spec["candidate_hash"],
        label="source_candidate.frozen_candidate hash",
    )
    _assert_candidate_profile(frozen_candidate, spec=spec)
    feasibility = candidate.get("feasibility")
    if not isinstance(feasibility, Mapping):
        raise ValueError("source_candidate.feasibility is missing")
    if len(str(feasibility.get("sha256") or "")) != 64:
        raise ValueError("source_candidate.feasibility.sha256 is invalid")
    universe = contract.get("universe_contract")
    if not isinstance(universe, Mapping):
        raise ValueError("universe_contract is missing")
    source = universe.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("universe_contract.source is missing")
    _assert_exact(
        source.get("sha256"),
        EXPECTED_UNIVERSE_SHA256,
        label="universe_contract.source.sha256",
    )
    _assert_exact(
        int(source.get("rows") or 0),
        EXPECTED_UNIVERSE_ROWS,
        label="universe_contract.source.rows",
    )
    _assert_exact(
        universe.get("venues"),
        list(EXPECTED_VENUES),
        label="universe_contract.venues",
    )

    _assert_exact(
        contract.get("raw_schema_contract"),
        _frozen_raw_contract(),
        label="raw_schema_contract",
    )
    _assert_exact(
        contract.get("segment_validity_contract"),
        _frozen_segment_contract(),
        label="segment_validity_contract",
    )
    _assert_exact(
        contract.get("causal_regime_contract"),
        _frozen_regime_contract(),
        label="causal_regime_contract",
    )
    _assert_exact(
        contract.get("execution_sampling_contract"),
        _frozen_execution_contract(),
        label="execution_sampling_contract",
    )
    _assert_exact(
        contract.get("cost_risk_no_grid_contract"),
        _frozen_cost_risk_contract(),
        label="cost_risk_no_grid_contract",
    )
    _assert_exact(
        contract.get("evidence_and_acceptance_contract"),
        _frozen_evidence_contract(),
        label="evidence_and_acceptance_contract",
    )
    _assert_exact(
        contract.get("next_allowed_action"),
        CONTRACT_NEXT_ACTION,
        label="contract.next_allowed_action",
    )

    source_bindings = contract.get("source_bindings")
    if not isinstance(source_bindings, Mapping):
        raise ValueError("source_bindings is missing")
    required_source_bindings = {
        "hypothesis_bank",
        "continuous_production_policy",
        "pit_schedule",
        "raw_writer",
        "durable_collector",
        "normalizer_and_shared_classifier",
        "campaign_runner",
        "campaign_quality",
        "campaign_contract",
    }
    if set(source_bindings) != required_source_bindings:
        raise ValueError("source_bindings do not match the frozen runtime set")

    refreeze = contract.get("collector_liveness_refreeze")
    if refreeze is not None:
        if not isinstance(refreeze, Mapping):
            raise ValueError("collector_liveness_refreeze is invalid")
        _assert_exact(
            set(refreeze),
            {
                "proposal",
                "proposal_hash",
                "approval_receipt",
                "runtime_dependency_manifest",
                "implementation_authorized",
                "collector_launch_authorized",
                "stopped_incomplete_retry_authorized",
            },
            label="collector_liveness_refreeze fields",
        )
        if refreeze.get("implementation_authorized") is not True:
            raise ValueError("collector liveness implementation must be authorized")
        if refreeze.get("collector_launch_authorized") is not False:
            raise ValueError("collector liveness refreeze must not authorize launch")
        if refreeze.get("stopped_incomplete_retry_authorized") is not False:
            raise ValueError("STOPPED_INCOMPLETE retry must remain unauthorized")
        proposal_hash = str(refreeze.get("proposal_hash") or "").lower()
        if len(proposal_hash) != 64:
            raise ValueError("collector liveness proposal hash is invalid")
        if verify_files:
            proposal_binding = refreeze.get("proposal")
            approval_binding = refreeze.get("approval_receipt")
            runtime_binding = refreeze.get("runtime_dependency_manifest")
            for label, binding in (
                ("proposal", proposal_binding),
                ("approval_receipt", approval_binding),
                ("runtime_dependency_manifest", runtime_binding),
            ):
                if not isinstance(binding, Mapping):
                    raise ValueError(f"collector liveness {label} binding is invalid")
                _verify_file_binding(binding, label=f"collector_liveness_refreeze.{label}")
            proposal_payload = _read_json(str(proposal_binding["path"]))
            computed_proposal_hash = _sha256_bytes(
                _canonical_json(
                    {
                        key: value
                        for key, value in proposal_payload.items()
                        if key != "proposal_hash"
                    }
                ).encode("utf-8")
            )
            _assert_exact(
                computed_proposal_hash,
                proposal_hash,
                label="collector liveness canonical proposal hash",
            )
            runtime_manifest = _read_json(str(runtime_binding["path"]))
            _assert_exact(
                runtime_manifest.get("proposal_hash"),
                proposal_hash,
                label="runtime dependency manifest proposal_hash",
            )
            if runtime_manifest.get("collector_launch_authorized") is not False:
                raise ValueError("runtime dependency manifest must not authorize launch")

    if verify_files:
        _verify_file_binding(
            {"path": source.get("path"), "sha256": source.get("sha256")},
            label="universe_contract.source",
        )
        if _universe_row_count(str(source["path"])) != EXPECTED_UNIVERSE_ROWS:
            raise ValueError("current universe row count mismatch")
        _verify_file_binding(feasibility, label="source_candidate.feasibility")
        _assert_resource_profile(_read_json(str(feasibility["path"])), spec=spec)
        for name, binding in source_bindings.items():
            if not isinstance(binding, Mapping):
                raise ValueError(f"source_bindings.{name} is invalid")
            _verify_file_binding(binding, label=f"source_bindings.{name}")


def _phase_plan(
    phase: Mapping[str, Any],
    *,
    output_root: str | Path,
    campaign_id: str,
) -> dict[str, Any]:
    phase_id = str(phase["phase_id"])
    run_id = f"{campaign_id}_{phase_id}"
    output_path = Path(output_root).expanduser().resolve() / run_id
    duration = int(phase["writer_duration_sec"])
    return {
        **dict(phase),
        "run_id": run_id,
        "output_namespace": str(output_path),
        "segments_planned": math.ceil(duration / EXPECTED_SEGMENT_SEC),
        "full_segments_planned": duration // EXPECTED_SEGMENT_SEC,
        "terminal_partial_sec": duration % EXPECTED_SEGMENT_SEC,
        "launch_authorized": False,
    }


def _resource_plan(feasibility: Mapping[str, Any]) -> dict[str, Any]:
    estimate = feasibility["resource_estimate"]
    source_samples = feasibility["operational_baseline"]["sample_segments"]
    estimated_disk = int(estimate["estimated_disk_bytes"])
    hard_output_cap = estimate.get("hard_output_cap_bytes")
    return {
        "estimated_events": int(estimate["estimated_events"]),
        "estimated_disk_bytes": estimated_disk,
        "hard_output_cap_bytes": (
            int(hard_output_cap) if hard_output_cap is not None else None
        ),
        "disk_free_bytes_at_feasibility": int(estimate["disk_free_bytes_at_plan_time"]),
        "disk_headroom_multiplier_at_feasibility": float(
            estimate["disk_headroom_multiplier"]
        ),
        "estimated_inbound_network_bytes_upper_bound": estimated_disk * 2,
        "connection_topology": {
            "gateio_connections": 1,
            "mexc_connections": 2,
            "reason": "16 pairs and MEXC 30-channel limit at 3 channels per pair",
        },
        "cpu_memory_estimate_status": "EARLY_CALIBRATION_REQUIRED",
        "expected_cpu": (
            "streaming decode/write workload, expected below two logical cores"
        ),
        "expected_working_set_bytes": 1_073_741_824,
        "hard_working_set_stop_bytes": 2_147_483_648,
        "hard_normalized_cpu_stop_percent": 75.0,
        "resource_gate_window_sec": 600,
        "baseline_manifests": [
            {
                "path": item["path"],
                "duration_sec": item["duration_sec"],
                "events_per_sec": item["events_per_sec"],
                "bytes_per_sec": item["bytes_per_sec"],
            }
            for item in source_samples
        ],
        "baseline_is_evidence": False,
    }


def _operational_timing_plan(phases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for phase in phases:
        start = _parse_datetime(phase["start_local"], label="phase.start_local")
        end = _parse_datetime(phase["end_local"], label="phase.end_local")
        hard_end = _parse_datetime(
            phase.get("hard_end_local") or phase["end_local"],
            label="phase.hard_end_local",
        )
        window_sec = int((hard_end - start).total_seconds())
        writer_sec = int(phase["writer_duration_sec"])
        finalization_headroom_sec = int((hard_end - end).total_seconds())
        checks.append(
            {
                "phase_id": phase["phase_id"],
                "window_sec": window_sec,
                "writer_duration_sec": writer_sec,
                "startup_shutdown_headroom_sec": window_sec - writer_sec,
                "finalization_headroom_sec": finalization_headroom_sec,
                "hard_end_local": hard_end.isoformat(),
            }
        )
    total_window_sec = sum(item["window_sec"] for item in checks)
    total_writer_sec = sum(item["writer_duration_sec"] for item in checks)
    zero_headroom = any(item["startup_shutdown_headroom_sec"] <= 0 for item in checks)
    return {
        "status": (
            "BLOCKED_ZERO_RUNTIME_HEADROOM"
            if zero_headroom
            else "RUNTIME_HEADROOM_AVAILABLE"
        ),
        "launch_ready": not zero_headroom,
        "startup_shutdown_headroom_required": True,
        "phase_checks": checks,
        "total_window_sec": total_window_sec,
        "total_writer_duration_sec": total_writer_sec,
        "total_startup_shutdown_headroom_sec": total_window_sec - total_writer_sec,
        "reason": (
            "writer duration consumes the full immutable phase windows; any "
            "process startup, venue connection, manifest finalization, or "
            "shutdown latency would cross a PIT blackout or phase hard end"
            if zero_headroom
            else None
        ),
    }


def _operational_readiness_plan(
    operational_timing: Mapping[str, Any],
    *,
    global_active_writer_cas_implemented: bool = False,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if operational_timing.get("launch_ready") is not True:
        blockers.append(
            {
                "code": "ZERO_RUNTIME_HEADROOM",
                "resolution": (
                    "Refreeze phase windows or writer durations with explicit "
                    "startup, connection, finalization, and shutdown headroom."
                ),
            }
        )
    if not global_active_writer_cas_implemented:
        blockers.append(
            {
                "code": "GLOBAL_ACTIVE_WRITER_CAS_NOT_IMPLEMENTED",
                "resolution": (
                    "Implement and independently test one atomic cross-launcher "
                    "active-writer claim before any campaign can become approval-ready."
                ),
            }
        )
    cas_status = (
        "IMPLEMENTED" if global_active_writer_cas_implemented else "NOT_IMPLEMENTED"
    )
    return {
        "status": "BLOCKED_PRE_APPROVAL" if blockers else "READY_FOR_APPROVAL",
        "launch_ready": not blockers,
        "blockers": blockers,
        "global_active_writer_claim": {
            "status": cas_status,
            "required_before_approval": True,
            "must_be_atomic_across_all_market_data_launchers": True,
            "current_gate_check_is_advisory_only": not global_active_writer_cas_implemented,
        },
    }


def _frozen_early_gates() -> list[dict[str, Any]]:
    return [
        {
            "gate": "prelaunch_integrity",
            "when": "before writer",
            "pass": (
                "plan, contract, candidate, universe, writer and collector "
                "hashes all match"
            ),
            "failure_action": "do_not_start",
        },
        {
            "gate": "zero_line",
            "when_sec": 600,
            "pass": "raw line count > 0 on both venues",
            "failure_action": "stop and mark STOPPED_INCOMPLETE",
        },
        {
            "gate": "raw_schema",
            "when_sec": 60,
            "pass": "first 20 non-empty rows satisfy frozen envelope",
            "failure_action": "stop and mark STOPPED_INCOMPLETE",
        },
        {
            "gate": "resource_calibration",
            "when_sec": 600,
            "pass": (
                "working set <= 2 GiB and normalized CPU <= 75% during "
                "the 10-minute calibration window"
            ),
            "failure_action": "stop and mark STOPPED_INCOMPLETE",
        },
        {
            "gate": "early_density",
            "when_sec": 3_600,
            "pass": (
                "both venues present, >=600 raw rows, >=10 lines/minute, "
                "dual venue base coverage >=0.80"
            ),
            "failure_action": "stop and mark STOPPED_INCOMPLETE",
        },
        {
            "gate": "disk_headroom",
            "when": "prelaunch and every 60 seconds",
            "pass": "free bytes >= max(50 GiB, 2x estimated remaining raw bytes)",
            "failure_action": "graceful stop and mark STOPPED_INCOMPLETE",
        },
        {
            "gate": "campaign_output_cap",
            "when": "before writer and every 60 seconds",
            "pass": "aggregate campaign output bytes <= immutable hard output cap",
            "failure_action": "graceful stop and mark STOPPED_INCOMPLETE",
        },
    ]


def _frozen_stop_conditions() -> list[str]:
    return [
        "active-run gate RUNNING or STOPPED_INCOMPLETE for another run",
        "phase starts outside its exact immutable window",
        "PIT blackout or hard deadline would be crossed",
        "any immutable source/hash/schema binding mismatch",
        "zero-line, raw-schema, resource, density or disk gate failure",
        "immutable aggregate campaign output cap reached",
        "writer exits without final completed manifest",
        "second writer or duplicate phase owner detected",
        "user stop request",
    ]


def _frozen_post_collection(profile: str = LEGACY_PROFILE) -> dict[str, Any]:
    if profile == AEF_PROFILE:
        return {
            "pipeline": [
                "campaign_data_quality",
                "causal_regime_and_execution_snapshot_materialization",
                "exact_signal_and_evaluator_contract_review",
                "frozen_train",
                "chronological_oos",
                "walk_forward_5_fold",
                "normal_and_stress_economics",
                "drawdown_sample_liquidity_fill_capacity",
                "public_readonly_paper_forward_7d_on_full_pass",
            ],
            "automatic_same_hash_progression": False,
            "automatic_same_hash_progression_through_materialization": True,
            "signal_and_evaluator_contract_frozen": False,
            "signal_and_evaluator_contract_review_required": True,
            "stop_on_first_failed_gate": True,
            "returns_or_pnl_only_after_data_quality_materialization_signal_contract_and_train_gate": True,
            "oos_only_after_frozen_train_pass": True,
            "paper_forward_only_after_full_historical_pass": True,
            "paper_forward_public_readonly": True,
            "automatic_live_or_private_api": False,
            "grid_or_retune": False,
            "terminal_accept_or_reject_requires_user_review": True,
            "next_allowed_result": "DATA_READY_FOR_CAUSAL_MATERIALIZATION",
        }
    return {
        "automatic_replay": False,
        "automatic_returns_or_pnl": False,
        "automatic_oos": False,
        "automatic_paper_or_live": False,
        "next_allowed_result": "DATA_READY_FOR_TRAIN_ONLY_REVIEW",
        "historical_accept_or_reject_requires_user_review": True,
    }


def build_plan(
    *,
    contract: Mapping[str, Any],
    contract_path: str | Path,
    contract_file_sha256: str,
    feasibility: Mapping[str, Any],
    output_root: str | Path,
    generated_at_utc: str,
    launcher_path: str | Path | None = None,
    status_tool_path: str | Path | None = None,
    stop_tool_path: str | Path | None = None,
    runner_path: str | Path | None = None,
    global_writer_claim_path: str | Path | None = None,
    campaign_quality_path: str | Path | None = None,
    causal_materializer_path: str | Path | None = None,
    global_active_writer_cas_implemented: bool = False,
    use_v3_timing: bool = False,
) -> dict[str, Any]:
    validate_contract(contract, verify_files=True)
    spec = _profile_spec(str(contract.get("factory_profile") or LEGACY_PROFILE))
    candidate = feasibility["frozen_candidate"]
    # When use_v3_timing is True, override the frozen phases with the
    # headroom-adjusted V3 phases (ZERO_HEADROOM fix).
    if use_v3_timing and spec["profile"] == LEGACY_PROFILE:
        candidate = dict(candidate)
        candidate["phases"] = [dict(p) for p in V3_EXPECTED_PHASES]
        candidate["target_writer_sec"] = V3_EXPECTED_WRITER_SEC
    phases = [
        _phase_plan(
            phase,
            output_root=output_root,
            campaign_id=str(spec["campaign_id"]),
        )
        for phase in candidate["phases"]
    ]
    launch_tools: dict[str, Any] = {}
    for key, raw in (
        ("launcher", launcher_path),
        ("status", status_tool_path),
        ("stop", stop_tool_path),
        ("runner", runner_path),
        ("global_writer_claim", global_writer_claim_path),
        ("campaign_quality", campaign_quality_path),
        ("causal_materializer", causal_materializer_path),
    ):
        if raw:
            launch_tools[key] = _source_binding(raw)

    required_launch_tools = {"launcher", "status", "stop", "runner"}
    if spec["global_claim_binding_required"]:
        required_launch_tools.update(
            {"global_writer_claim", "campaign_quality", "causal_materializer"}
        )
    launcher_ready = set(launch_tools) == required_launch_tools
    cas_implemented = (
        "global_writer_claim" in launch_tools
        if spec["global_claim_binding_required"]
        else global_active_writer_cas_implemented
        or "global_writer_claim" in launch_tools
    )
    operational_timing = _operational_timing_plan(phases)
    operational_readiness = _operational_readiness_plan(
        operational_timing,
        global_active_writer_cas_implemented=cas_implemented,
    )
    operationally_ready = bool(operational_readiness["launch_ready"])
    plan_path_placeholder = "<immutable_plan_path>"
    plan_hash_placeholder = "<expected_plan_hash>"
    commands = _launch_control_commands(launch_tools) if launcher_ready else {}
    if not launcher_ready:
        launch_control_status = "IMPLEMENTATION_REQUIRED_BEFORE_APPROVAL"
        next_allowed_action = PLAN_CONTROLS_NEXT_ACTION
    elif not operationally_ready:
        launch_control_status = CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED
        next_allowed_action = PLAN_OPERATIONAL_REVIEW_NEXT_ACTION
    else:
        launch_control_status = "READY_FOR_SEPARATE_EXACT_APPROVAL"
        next_allowed_action = PLAN_APPROVAL_NEXT_ACTION

    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "factory_profile": spec["profile"],
        "campaign_id": spec["campaign_id"],
        "hypothesis_id": HYPOTHESIS_ID,
        "data_type": DATA_TYPE,
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "actual_collection_allowed": False,
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
        "contract": {
            "path": str(Path(contract_path).expanduser().resolve()),
            "file_sha256": contract_file_sha256,
            "contract_hash": contract["contract_hash"],
            "candidate_contract_hash": spec["candidate_hash"],
        },
        "runtime_dependencies": {
            "source_bindings": contract["source_bindings"],
            "collector_liveness_refreeze": contract.get(
                "collector_liveness_refreeze"
            ),
            "shared_market_classifier": contract["source_bindings"][
                "normalizer_and_shared_classifier"
            ],
            "collector_launch_authorized": False,
            "stopped_incomplete_retry_authorized": False,
        },
        "window": {
            "window_id": spec["window_id"],
            "start_local": spec["start_local"],
            "expected_finish_local": phases[-1]["end_local"],
            "writer_deadline_local": spec["writer_deadline_local"],
            "hard_deadline_local": spec["hard_deadline_local"],
            "target_writer_sec": (
                V3_EXPECTED_WRITER_SEC
                if use_v3_timing and spec["profile"] == LEGACY_PROFILE
                else spec["writer_sec"]
            ),
            "expected_elapsed_sec": (
                V3_EXPECTED_MAX_RUNTIME_SEC
                if use_v3_timing and spec["profile"] == LEGACY_PROFILE
                else spec["max_runtime_sec"]
            ),
            "max_runtime_sec": (
                V3_EXPECTED_MAX_RUNTIME_SEC
                if use_v3_timing and spec["profile"] == LEGACY_PROFILE
                else spec["max_runtime_sec"]
            ),
            "pit_blackouts": candidate["pit_blackouts"],
        },
        "phases": phases,
        "operational_timing": operational_timing,
        "operational_readiness": operational_readiness,
        "resources": _resource_plan(feasibility),
        "early_gates": _frozen_early_gates(),
        "stop_conditions": _frozen_stop_conditions(),
        "launch_controls": {
            "status": launch_control_status,
            "separate_exact_user_approval_required": True,
            "one_approval_covers_listed_phases_only": True,
            "stop_incomplete_recovery_requires_new_exact_approval": True,
            "visible_terminal_required": True,
            "single_writer": True,
            "commands_are_inert_until_operational_contract_refreeze": (
                not operationally_ready
            ),
            "tools": launch_tools,
            "preflight_command": commands.get("preflight_command"),
            "visible_command_after_approval": commands.get(
                "visible_command_after_approval"
            ),
            "status_command": commands.get("status_command"),
            "stop_command": commands.get("stop_command"),
            "command_placeholders": {
                "plan_path": plan_path_placeholder,
                "plan_hash": plan_hash_placeholder,
            },
        },
        "outputs": {
            "campaign_root": str(Path(output_root).expanduser().resolve()),
            "phase_namespaces": [phase["output_namespace"] for phase in phases],
            "append_safe": True,
            "phase_manifests_independently_finalizable": True,
            "consumer_before_campaign_quality_gate": False,
        },
        "post_collection": _frozen_post_collection(str(spec["profile"])),
        "approval_state": "NOT_APPROVED",
        "strategy_accepted": False,
        "next_allowed_action": next_allowed_action,
    }
    plan["plan_hash"] = canonical_plan_hash(plan)
    validate_plan(plan, contract=contract, verify_files=False, allow_v3_timing=use_v3_timing)
    return plan


def validate_plan(
    plan: Mapping[str, Any],
    *,
    contract: Mapping[str, Any] | None = None,
    verify_files: bool = False,
    allow_v3_timing: bool = False,
) -> None:
    if contract is None:
        raise ValueError("contract is required for PlanOnly validation")
    spec = _profile_spec(str(contract.get("factory_profile") or LEGACY_PROFILE))
    _assert_exact(plan.get("schema"), PLAN_SCHEMA, label="plan.schema")
    _assert_exact(plan.get("mode"), "PlanOnly", label="plan.mode")
    _assert_exact(
        plan.get("factory_profile"),
        spec["profile"],
        label="plan.factory_profile",
    )
    _assert_exact(
        plan.get("campaign_id"), spec["campaign_id"], label="plan.campaign_id"
    )
    _assert_exact(plan.get("hypothesis_id"), HYPOTHESIS_ID, label="plan.hypothesis_id")
    _assert_exact(plan.get("data_type"), DATA_TYPE, label="plan.data_type")
    _parse_datetime(plan.get("generated_at_utc"), label="plan.generated_at_utc")
    _assert_false_flags(plan, label="plan")
    if plan.get("research_only") is not True:
        raise ValueError("plan.research_only must remain true")
    if plan.get("strategy_accepted") is not False:
        raise ValueError("plan.strategy_accepted must remain false")
    if plan.get("approval_state") != "NOT_APPROVED":
        raise ValueError("immutable PlanOnly approval_state must remain NOT_APPROVED")
    observed_hash = str(plan.get("plan_hash") or "").lower()
    if canonical_plan_hash(plan) != observed_hash:
        raise ValueError("plan hash mismatch; frozen PlanOnly was modified")

    contract_ref = plan.get("contract")
    if not isinstance(contract_ref, Mapping):
        raise ValueError("plan.contract is missing")
    validate_contract(contract, verify_files=verify_files)
    _assert_exact(
        contract_ref.get("candidate_contract_hash"),
        spec["candidate_hash"],
        label="plan.contract.candidate_contract_hash",
    )
    _assert_exact(
        contract_ref.get("contract_hash"),
        contract.get("contract_hash"),
        label="plan.contract.contract_hash",
    )
    _assert_exact(
        contract_ref.get("file_sha256"),
        _sha256_bytes(_json_bytes(contract)),
        label="plan.contract.file_sha256",
    )
    _assert_exact(
        plan.get("runtime_dependencies"),
        {
            "source_bindings": contract["source_bindings"],
            "collector_liveness_refreeze": contract.get(
                "collector_liveness_refreeze"
            ),
            "shared_market_classifier": contract["source_bindings"][
                "normalizer_and_shared_classifier"
            ],
            "collector_launch_authorized": False,
            "stopped_incomplete_retry_authorized": False,
        },
        label="plan.runtime_dependencies",
    )

    window = plan.get("window")
    if not isinstance(window, Mapping):
        raise ValueError("plan.window is missing")
    legacy_v3 = allow_v3_timing and spec["profile"] == LEGACY_PROFILE
    _active_phases = V3_EXPECTED_PHASES if legacy_v3 else spec["phases"]
    _active_writer_sec = V3_EXPECTED_WRITER_SEC if legacy_v3 else spec["writer_sec"]
    _active_max_runtime = (
        V3_EXPECTED_MAX_RUNTIME_SEC if legacy_v3 else spec["max_runtime_sec"]
    )
    for key, expected in (
        ("window_id", spec["window_id"]),
        ("start_local", spec["start_local"]),
        ("expected_finish_local", _active_phases[-1]["end_local"]),
        ("writer_deadline_local", spec["writer_deadline_local"]),
        ("hard_deadline_local", spec["hard_deadline_local"]),
        ("target_writer_sec", _active_writer_sec),
        ("expected_elapsed_sec", _active_max_runtime),
        ("max_runtime_sec", _active_max_runtime),
    ):
        _assert_exact(window.get(key), expected, label=f"plan.window.{key}")
    frozen_candidate = contract["source_candidate"]["frozen_candidate"]
    _assert_exact(
        window.get("pit_blackouts"),
        frozen_candidate.get("pit_blackouts"),
        label="plan.window.pit_blackouts",
    )

    phases = plan.get("phases")
    if not isinstance(phases, Sequence) or isinstance(phases, (str, bytes)):
        raise ValueError("plan.phases is missing")
    _active_phases = V3_EXPECTED_PHASES if legacy_v3 else spec["phases"]
    if len(phases) != len(_active_phases):
        raise ValueError("plan.phases count mismatch")
    total_writer = 0
    prior_end: datetime | None = None
    for index, (phase, expected) in enumerate(zip(phases, _active_phases), start=1):
        if not isinstance(phase, Mapping):
            raise ValueError(f"plan.phases[{index}] is invalid")
        for key, value in expected.items():
            _assert_exact(
                phase.get(key),
                value,
                label=f"plan.phases[{index}].{key}",
            )
        if phase.get("launch_authorized") is not False:
            raise ValueError("phase launch_authorized must remain false")
        duration = int(phase["writer_duration_sec"])
        _assert_exact(
            phase.get("run_id"),
            f"{spec['campaign_id']}_{phase['phase_id']}",
            label=f"plan.phases[{index}].run_id",
        )
        _assert_exact(
            phase.get("segments_planned"),
            math.ceil(duration / EXPECTED_SEGMENT_SEC),
            label=f"plan.phases[{index}].segments_planned",
        )
        _assert_exact(
            phase.get("full_segments_planned"),
            duration // EXPECTED_SEGMENT_SEC,
            label=f"plan.phases[{index}].full_segments_planned",
        )
        _assert_exact(
            phase.get("terminal_partial_sec"),
            duration % EXPECTED_SEGMENT_SEC,
            label=f"plan.phases[{index}].terminal_partial_sec",
        )
        start = _parse_datetime(phase["start_local"], label="phase.start_local")
        end = _parse_datetime(phase["end_local"], label="phase.end_local")
        if start >= end or (prior_end is not None and start < prior_end):
            raise ValueError("phase timing is invalid or overlapping")
        prior_end = end
        total_writer += int(phase["writer_duration_sec"])
    if total_writer != _active_writer_sec:
        raise ValueError("phase writer duration does not match target")
    _assert_exact(
        plan.get("operational_timing"),
        _operational_timing_plan(phases),
        label="plan.operational_timing",
    )
    plan_launch_tools = (
        (plan.get("launch_controls") or {}).get("tools")
        if isinstance(plan.get("launch_controls"), Mapping)
        else {}
    )
    claim_binding_present = (
        isinstance(plan_launch_tools, Mapping)
        and "global_writer_claim" in plan_launch_tools
    )
    _plan_cas_implemented = (
        claim_binding_present
        if spec["global_claim_binding_required"]
        else (
            plan.get("operational_readiness", {})
            .get("global_active_writer_claim", {})
            .get("status")
            == "IMPLEMENTED"
        )
    )
    _assert_exact(
        plan.get("operational_readiness"),
        _operational_readiness_plan(
            plan["operational_timing"],
            global_active_writer_cas_implemented=_plan_cas_implemented,
        ),
        label="plan.operational_readiness",
    )

    resources = plan.get("resources")
    if not isinstance(resources, Mapping):
        raise ValueError("plan.resources is missing")
    feasibility_ref = contract["source_candidate"]["feasibility"]
    feasibility = _read_json(str(feasibility_ref["path"]))
    _assert_resource_profile(feasibility, spec=spec)
    _assert_exact(resources, _resource_plan(feasibility), label="plan.resources")
    _assert_exact(
        plan.get("early_gates"),
        _frozen_early_gates(),
        label="plan.early_gates",
    )
    _assert_exact(
        plan.get("stop_conditions"),
        _frozen_stop_conditions(),
        label="plan.stop_conditions",
    )

    controls = plan.get("launch_controls")
    if not isinstance(controls, Mapping):
        raise ValueError("plan.launch_controls is missing")
    if controls.get("separate_exact_user_approval_required") is not True:
        raise ValueError("separate campaign approval must remain required")
    if controls.get("one_approval_covers_listed_phases_only") is not True:
        raise ValueError("launch approval must remain phase-bound")
    if controls.get("stop_incomplete_recovery_requires_new_exact_approval") is not True:
        raise ValueError("STOPPED_INCOMPLETE recovery must require new approval")
    if controls.get("single_writer") is not True:
        raise ValueError("single-writer invariant must remain true")
    if controls.get("visible_terminal_required") is not True:
        raise ValueError("visible terminal invariant must remain true")
    operationally_ready = bool(plan["operational_readiness"]["launch_ready"])
    _assert_exact(
        controls.get("commands_are_inert_until_operational_contract_refreeze"),
        not operationally_ready,
        label=(
            "plan.launch_controls."
            "commands_are_inert_until_operational_contract_refreeze"
        ),
    )
    _assert_exact(
        controls.get("command_placeholders"),
        {
            "plan_path": "<immutable_plan_path>",
            "plan_hash": "<expected_plan_hash>",
        },
        label="plan.launch_controls.command_placeholders",
    )
    control_status = controls.get("status")
    if control_status in {
        "READY_FOR_SEPARATE_EXACT_APPROVAL",
        CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED,
    }:
        tools = controls.get("tools")
        if not isinstance(tools, Mapping):
            raise ValueError("launch tools are missing")
        expected_tool_names = {"launcher", "status", "stop", "runner"}
        if spec["global_claim_binding_required"]:
            expected_tool_names.update(
                {"global_writer_claim", "campaign_quality", "causal_materializer"}
            )
        _assert_exact(
            set(tools),
            expected_tool_names,
            label="plan.launch_controls.tools",
        )
        expected_paths = _expected_launch_tool_paths()
        for name in sorted(expected_tool_names):
            binding = tools.get(name)
            if not isinstance(binding, Mapping):
                raise ValueError(f"launch tool {name} is missing")
            _assert_exact(
                str(Path(str(binding.get("path") or "")).expanduser().resolve()),
                str(expected_paths[name]),
                label=f"launch_controls.tools.{name}.path",
            )
            if verify_files:
                _verify_file_binding(binding, label=f"launch_controls.tools.{name}")
        expected_commands = _launch_control_commands(tools)
        for name, expected_command in expected_commands.items():
            _assert_exact(
                controls.get(name),
                expected_command,
                label=f"launch_controls.{name}",
            )
        if "-VisibleChild" in str(controls.get("visible_command_after_approval")):
            raise ValueError("public visible command must not expose -VisibleChild")
        if control_status == CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED:
            if operationally_ready:
                raise ValueError(
                    "operationally blocked controls require readiness blockers"
                )
            expected_next_action = PLAN_OPERATIONAL_REVIEW_NEXT_ACTION
        else:
            if not operationally_ready:
                raise ValueError(
                    "approval-ready controls require operational readiness"
                )
            expected_next_action = PLAN_APPROVAL_NEXT_ACTION
        _assert_exact(
            plan.get("next_allowed_action"),
            expected_next_action,
            label="plan.next_allowed_action",
        )
    elif control_status == "IMPLEMENTATION_REQUIRED_BEFORE_APPROVAL":
        _assert_exact(
            controls.get("tools"),
            {},
            label="plan.launch_controls.tools",
        )
        for name in (
            "preflight_command",
            "visible_command_after_approval",
            "status_command",
            "stop_command",
        ):
            _assert_exact(
                controls.get(name),
                None,
                label=f"plan.launch_controls.{name}",
            )
        _assert_exact(
            plan.get("next_allowed_action"),
            PLAN_CONTROLS_NEXT_ACTION,
            label="plan.next_allowed_action",
        )
    else:
        raise ValueError(f"unsupported launch control status: {control_status!r}")

    outputs = plan.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("plan.outputs is missing")
    campaign_root = str(outputs.get("campaign_root") or "").strip()
    if not campaign_root:
        raise ValueError("plan.outputs.campaign_root is missing")
    expected_namespaces = [
        str(Path(campaign_root).expanduser().resolve() / str(phase["run_id"]))
        for phase in phases
    ]
    _assert_exact(
        outputs.get("phase_namespaces"),
        expected_namespaces,
        label="plan.outputs.phase_namespaces",
    )
    for index, (phase, namespace) in enumerate(
        zip(phases, expected_namespaces), start=1
    ):
        _assert_exact(
            phase.get("output_namespace"),
            namespace,
            label=f"plan.phases[{index}].output_namespace",
        )
    for name, expected in (
        ("append_safe", True),
        ("phase_manifests_independently_finalizable", True),
        ("consumer_before_campaign_quality_gate", False),
    ):
        _assert_exact(outputs.get(name), expected, label=f"plan.outputs.{name}")
    _assert_exact(
        plan.get("post_collection"),
        _frozen_post_collection(str(spec["profile"])),
        label="plan.post_collection",
    )

    if verify_files:
        _verify_file_binding(
            {
                "path": contract_ref.get("path"),
                "sha256": contract_ref.get("file_sha256"),
            },
            label="plan.contract",
        )


def validate_policy_binding(
    policy: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract_path: str | Path,
    plan_path: str | Path,
) -> None:
    spec = _profile_spec(str(contract.get("factory_profile") or LEGACY_PROFILE))
    campaign = policy.get("next_long_campaign")
    if not isinstance(campaign, Mapping):
        raise ValueError("policy.next_long_campaign is missing")
    control_status = plan["launch_controls"]["status"]
    if control_status == "READY_FOR_SEPARATE_EXACT_APPROVAL":
        expected_status = "READY_FOR_APPROVAL"
    elif control_status == CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED:
        expected_status = "USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT"
    else:
        expected_status = "CONTRACT_FROZEN_PLANONLY_CONTROLS_REQUIRED"
    contract_target = Path(contract_path).expanduser().resolve()
    plan_target = Path(plan_path).expanduser().resolve()
    feasibility = contract["source_candidate"]["feasibility"]
    for key, expected in (
        ("status", expected_status),
        ("campaign_id", spec["campaign_id"]),
        ("hypothesis_id", HYPOTHESIS_ID),
        ("data_type", DATA_TYPE),
        ("feasibility_path", str(Path(feasibility["path"]).expanduser().resolve())),
        ("feasibility_sha256", feasibility["sha256"]),
        ("candidate_contract_hash", spec["candidate_hash"]),
        ("contract_path", str(contract_target)),
        ("contract_file_sha256", sha256_file(contract_target)),
        ("contract_hash", contract["contract_hash"]),
        ("plan_path", str(plan_target)),
        ("plan_file_sha256", sha256_file(plan_target)),
        ("plan_hash", plan["plan_hash"]),
        ("plan_approval_state", "NOT_APPROVED"),
        ("launch_control_status", control_status),
        ("window_id", spec["window_id"]),
        ("target_writer_sec", plan["window"]["target_writer_sec"]),
        ("max_runtime_sec", plan["window"]["max_runtime_sec"]),
        ("actual_collection_allowed", False),
        ("requested_action", plan["next_allowed_action"]),
    ):
        _assert_exact(
            campaign.get(key),
            expected,
            label=f"policy.next_long_campaign.{key}",
        )


def write_bundle(
    *,
    contract_output_path: str | Path,
    plan_output_path: str | Path,
    contract: Mapping[str, Any],
    plan_builder: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract_target = Path(contract_output_path).expanduser().resolve()
    plan_target = Path(plan_output_path).expanduser().resolve()
    if contract_target.exists():
        raise ValueError(f"refusing to overwrite immutable artifact: {contract_target}")
    if plan_target.exists():
        raise ValueError(f"refusing to overwrite immutable artifact: {plan_target}")
    contract_bytes = _json_bytes(contract)
    contract_file_sha = _sha256_bytes(contract_bytes)
    plan = plan_builder(contract_file_sha)
    plan_bytes = _json_bytes(plan)

    contract_target.parent.mkdir(parents=True, exist_ok=True)
    plan_target.parent.mkdir(parents=True, exist_ok=True)
    contract_temp = contract_target.with_name(
        f"{contract_target.name}.tmp.{os.getpid()}"
    )
    plan_temp = plan_target.with_name(f"{plan_target.name}.tmp.{os.getpid()}")
    contract_temp.write_bytes(contract_bytes)
    plan_temp.write_bytes(plan_bytes)
    try:
        contract_temp.replace(contract_target)
        plan_temp.replace(plan_target)
    finally:
        contract_temp.unlink(missing_ok=True)
        plan_temp.unlink(missing_ok=True)

    persisted_contract = _read_json(contract_target)
    persisted_plan = _read_json(plan_target)
    validate_contract(persisted_contract, verify_files=True)
    # Auto-detect v3 timing from the plan's target_writer_sec
    _plan_uses_v3 = (
        persisted_plan.get("window", {}).get("target_writer_sec")
        == V3_EXPECTED_WRITER_SEC
    )
    validate_plan(
        persisted_plan,
        contract=persisted_contract,
        verify_files=True,
        allow_v3_timing=_plan_uses_v3,
    )
    return persisted_contract, persisted_plan


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze and validate the dense WS campaign contract/PlanOnly"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--feasibility", required=True)
    build.add_argument("--expected-feasibility-sha256", required=True)
    build.add_argument(
        "--expected-candidate-hash",
        default=EXPECTED_CANDIDATE_HASH,
    )
    build.add_argument(
        "--factory-profile",
        choices=(LEGACY_PROFILE, AEF_PROFILE),
        default=LEGACY_PROFILE,
    )
    build.add_argument("--universe", required=True)
    build.add_argument("--hypothesis-bank", required=True)
    build.add_argument("--continuous-policy", required=True)
    build.add_argument("--pit-schedule", required=True)
    build.add_argument("--raw-writer", required=True)
    build.add_argument("--durable-collector", required=True)
    build.add_argument("--normalizer")
    build.add_argument("--runtime-dependency-manifest")
    build.add_argument("--refreeze-proposal")
    build.add_argument("--expected-refreeze-proposal-hash")
    build.add_argument("--refreeze-approval-receipt")
    build.add_argument("--contract-output", required=True)
    build.add_argument("--plan-output", required=True)
    build.add_argument("--campaign-output-root", required=True)
    build.add_argument("--generated-at-utc", required=True)
    build.add_argument("--launcher")
    build.add_argument("--status-tool")
    build.add_argument("--stop-tool")
    build.add_argument("--runner")
    build.add_argument("--global-writer-claim")
    build.add_argument("--campaign-quality")
    build.add_argument("--causal-materializer")

    bind = subparsers.add_parser("bind-controls")
    bind.add_argument("--contract", required=True)
    bind.add_argument("--expected-contract-file-sha256", required=True)
    bind.add_argument("--expected-contract-hash", required=True)
    bind.add_argument("--feasibility", required=True)
    bind.add_argument("--plan-output", required=True)
    bind.add_argument("--campaign-output-root", required=True)
    bind.add_argument("--generated-at-utc", required=True)
    bind.add_argument("--launcher", required=True)
    bind.add_argument("--status-tool", required=True)
    bind.add_argument("--stop-tool", required=True)
    bind.add_argument("--runner", required=True)
    bind.add_argument("--global-writer-claim")
    bind.add_argument("--campaign-quality")
    bind.add_argument("--causal-materializer")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--contract", required=True)
    validate.add_argument("--plan", required=True)
    validate.add_argument("--policy", required=True)
    validate.add_argument("--expected-plan-hash", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "build":
        contract = build_contract(
            feasibility_path=args.feasibility,
            expected_feasibility_sha256=args.expected_feasibility_sha256,
            expected_candidate_hash=args.expected_candidate_hash,
            universe_path=args.universe,
            hypothesis_bank_path=args.hypothesis_bank,
            continuous_policy_path=args.continuous_policy,
            pit_schedule_path=args.pit_schedule,
            raw_writer_path=args.raw_writer,
            durable_collector_path=args.durable_collector,
            generated_at_utc=args.generated_at_utc,
            factory_profile=args.factory_profile,
            normalizer_path=args.normalizer,
            campaign_runner_path=args.runner,
            campaign_quality_path=args.campaign_quality,
            runtime_dependency_manifest_path=args.runtime_dependency_manifest,
            refreeze_proposal_path=args.refreeze_proposal,
            expected_refreeze_proposal_hash=args.expected_refreeze_proposal_hash,
            refreeze_approval_receipt_path=args.refreeze_approval_receipt,
        )
        feasibility = _read_json(args.feasibility)
        contract_target = Path(args.contract_output).expanduser().resolve()
        plan_target = Path(args.plan_output).expanduser().resolve()

        def _plan_builder(contract_file_sha: str) -> dict[str, Any]:
            return build_plan(
                contract=contract,
                contract_path=contract_target,
                contract_file_sha256=contract_file_sha,
                feasibility=feasibility,
                output_root=args.campaign_output_root,
                generated_at_utc=args.generated_at_utc,
                launcher_path=args.launcher,
                status_tool_path=args.status_tool,
                stop_tool_path=args.stop_tool,
                runner_path=args.runner,
                global_writer_claim_path=args.global_writer_claim,
                campaign_quality_path=args.campaign_quality,
                causal_materializer_path=args.causal_materializer,
            )

        persisted_contract, persisted_plan = write_bundle(
            contract_output_path=contract_target,
            plan_output_path=plan_target,
            contract=contract,
            plan_builder=_plan_builder,
        )
        result = {
            "schema": VALIDATION_SCHEMA,
            "status": "CONTRACT_FROZEN_PLANONLY_CREATED",
            "contract_path": str(contract_target),
            "contract_file_sha256": sha256_file(contract_target),
            "contract_hash": persisted_contract["contract_hash"],
            "plan_path": str(plan_target),
            "plan_file_sha256": sha256_file(plan_target),
            "plan_hash": persisted_plan["plan_hash"],
            "launch_control_status": persisted_plan["launch_controls"]["status"],
            "actual_collection_allowed": False,
        }
    elif args.command == "bind-controls":
        contract_target = Path(args.contract).expanduser().resolve()
        plan_target = Path(args.plan_output).expanduser().resolve()
        if plan_target.exists():
            raise ValueError(f"refusing to overwrite immutable artifact: {plan_target}")
        contract = _read_json(contract_target)
        validate_contract(contract, verify_files=True)
        _assert_exact(
            sha256_file(contract_target),
            str(args.expected_contract_file_sha256).lower(),
            label="contract file SHA-256",
        )
        _assert_exact(
            contract.get("contract_hash"),
            str(args.expected_contract_hash).lower(),
            label="contract hash",
        )
        feasibility_target = Path(args.feasibility).expanduser().resolve()
        feasibility = _read_json(feasibility_target)
        source_feasibility = contract["source_candidate"]["feasibility"]
        _assert_exact(
            str(feasibility_target),
            str(Path(source_feasibility["path"]).expanduser().resolve()),
            label="feasibility path",
        )
        _assert_exact(
            sha256_file(feasibility_target),
            source_feasibility["sha256"],
            label="feasibility SHA-256",
        )
        plan = build_plan(
            contract=contract,
            contract_path=contract_target,
            contract_file_sha256=sha256_file(contract_target),
            feasibility=feasibility,
            output_root=args.campaign_output_root,
            generated_at_utc=args.generated_at_utc,
            launcher_path=args.launcher,
            status_tool_path=args.status_tool,
            stop_tool_path=args.stop_tool,
            runner_path=args.runner,
            global_writer_claim_path=args.global_writer_claim,
            campaign_quality_path=args.campaign_quality,
            causal_materializer_path=args.causal_materializer,
        )
        _write_bytes_immutable(plan_target, _json_bytes(plan))
        persisted_plan = _read_json(plan_target)
        validate_plan(persisted_plan, contract=contract, verify_files=True)
        result = {
            "schema": VALIDATION_SCHEMA,
            "status": "CONTROL_BOUND_PLANONLY_CREATED",
            "contract_path": str(contract_target),
            "contract_file_sha256": sha256_file(contract_target),
            "contract_hash": contract["contract_hash"],
            "plan_path": str(plan_target),
            "plan_file_sha256": sha256_file(plan_target),
            "plan_hash": persisted_plan["plan_hash"],
            "launch_control_status": persisted_plan["launch_controls"]["status"],
            "approval_state": persisted_plan["approval_state"],
            "actual_collection_allowed": False,
        }
    else:
        contract = _read_json(args.contract)
        plan = _read_json(args.plan)
        policy = _read_json(args.policy)
        validate_contract(contract, verify_files=True)
        validate_plan(plan, contract=contract, verify_files=True)
        expected = str(args.expected_plan_hash).lower()
        if expected != str(plan["plan_hash"]).lower():
            raise ValueError("expected plan hash does not match immutable PlanOnly")
        validate_policy_binding(
            policy,
            contract=contract,
            plan=plan,
            contract_path=args.contract,
            plan_path=args.plan,
        )
        result = {
            "schema": VALIDATION_SCHEMA,
            "status": "VALID",
            "contract_path": str(Path(args.contract).expanduser().resolve()),
            "contract_file_sha256": sha256_file(args.contract),
            "contract_hash": contract["contract_hash"],
            "plan_path": str(Path(args.plan).expanduser().resolve()),
            "plan_file_sha256": sha256_file(args.plan),
            "plan_hash": plan["plan_hash"],
            "launch_control_status": plan["launch_controls"]["status"],
            "actual_collection_allowed": False,
            "policy_binding": "VALID",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
