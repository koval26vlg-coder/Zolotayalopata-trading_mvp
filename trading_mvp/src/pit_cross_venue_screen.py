from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SPEC_SCHEMA = "pit_two_venue_clean_slice_spec_v1"
SPEC_MODE = "pit_two_venue_clean_slice_spec_planonly"
SPEC_DECISION = "PIT_TWO_VENUE_CLEAN_SLICE_SPEC_PLANONLY_READY"
SCREEN_SCHEMA = "pit_linear_perp_cross_venue_screen_v1"
SCREEN_MODE = "pit_linear_perp_cross_venue_screen_planonly"
SUPPORTED_EXCHANGES = ("gateio", "mexc")


@dataclass(frozen=True)
class PitCrossVenueScreenConfig:
    quote: str = "USDT"
    contract_type: str = "linear_perp"
    round_trip_fee_bps: float = 39.0
    slippage_bps: float = 10.0
    operational_buffer_bps: float = 20.0
    max_events: int = 1000
    progress_every_rows: int = 50_000
    prior_spot_report_path: str = ""

    @property
    def total_cost_bps(self) -> float:
        return self.round_trip_fee_bps + self.slippage_bps + self.operational_buffer_bps

    def validate(self) -> None:
        if self.quote.upper() != "USDT":
            raise ValueError("v1 screen supports USDT quote only")
        if self.contract_type != "linear_perp":
            raise ValueError("v1 screen is explicitly limited to linear_perp")
        if min(self.round_trip_fee_bps, self.slippage_bps, self.operational_buffer_bps) < 0:
            raise ValueError("cost assumptions must be non-negative")
        if self.max_events <= 0:
            raise ValueError("max_events must be positive")
        if self.progress_every_rows < 0:
            raise ValueError("progress_every_rows must be non-negative")


def run_pit_cross_venue_screen(
    spec_path: str | Path,
    output_path: str | Path,
    config: PitCrossVenueScreenConfig | None = None,
) -> dict[str, Any]:
    cfg = config or PitCrossVenueScreenConfig()
    cfg.validate()
    spec_file = Path(spec_path).resolve()
    output_file = Path(output_path).resolve()
    spec = _load_json(spec_file, "clean-slice spec")
    validated = _validate_spec(spec, spec_file)
    source_run_id = validated["run_id"]
    retained_cycles = validated["retained_cycles"]
    dropped_cycles = validated["dropped_cycles"]
    snapshots_path = validated["snapshots_path"]

    protected_paths = {
        spec_file,
        validated["manifest_path"],
        validated["cycles_path"],
        snapshots_path,
    }
    if output_file in protected_paths:
        raise ValueError("output path must not overwrite spec or source evidence")
    if output_file.exists():
        raise FileExistsError(f"screen output already exists: {output_file}")

    prior_spot = _load_prior_spot_evidence(cfg.prior_spot_report_path)
    state = _new_state()
    expected_cycles = retained_cycles | dropped_cycles
    current_cycle: int | None = None
    current_rows: list[dict[str, Any]] = []
    previous_cycle = 0
    snapshots_digest = hashlib.sha256()

    with snapshots_path.open("rb") as handle:
        for raw_line in handle:
            snapshots_digest.update(raw_line)
            state["source_rows"] += 1
            if cfg.progress_every_rows and state["source_rows"] % cfg.progress_every_rows == 0:
                print(
                    json.dumps(
                        {
                            "progress": SCREEN_MODE,
                            "source_rows": state["source_rows"],
                            "retained_rows": state["retained_rows"],
                            "retained_cycles_seen": len(state["retained_cycles_seen"]),
                            "matched_cycle_bases": state["matched_cycle_bases"],
                            "cost_positive_events": state["cost_positive_events"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            try:
                row = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid snapshots JSONL at row {state['source_rows']}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"snapshot row {state['source_rows']} must be an object")
            if str(row.get("run_id") or "") != source_run_id:
                raise ValueError(f"snapshot row {state['source_rows']} run_id mismatch")
            cycle = _positive_int(row.get("cycle"), f"snapshot row {state['source_rows']} cycle")
            if cycle not in expected_cycles:
                raise ValueError(f"snapshot row references cycle outside clean-slice mask: {cycle}")
            if cycle < previous_cycle:
                raise ValueError("snapshot cycles must be ordered monotonically")
            previous_cycle = cycle
            state["source_cycles_seen"].add(cycle)

            if cycle in dropped_cycles:
                state["dropped_rows"] += 1
                continue

            state["retained_rows"] += 1
            state["retained_cycles_seen"].add(cycle)
            if current_cycle is None:
                current_cycle = cycle
            elif cycle != current_cycle:
                _process_cycle(current_cycle, current_rows, cfg, state)
                current_cycle = cycle
                current_rows = []
            current_rows.append(row)

    if current_cycle is not None:
        _process_cycle(current_cycle, current_rows, cfg, state)

    observed_snapshots_hash = snapshots_digest.hexdigest()
    expected_snapshots_hash = validated["snapshots_sha256"]
    if observed_snapshots_hash != expected_snapshots_hash:
        raise ValueError(
            f"snapshots SHA-256 mismatch: expected={expected_snapshots_hash}, observed={observed_snapshots_hash}"
        )
    _validate_scan_counts(state, spec, expected_cycles, retained_cycles, dropped_cycles)

    top_events = _sorted_top(state["top_events"], cfg.max_events)
    per_base = _per_base_report(state["per_base"])
    max_gross = _max_value(top_events, "gross_edge_bps")
    max_net = _max_value(top_events, "net_screening_edge_bps")
    cost_positive = state["cost_positive_events"]
    if state["matched_cycle_bases"] <= 0:
        decision = "PIT_LINEAR_PERP_SCREEN_REJECTED_NO_MATCHED_PAIRS"
        reasons = ["no_matched_non_binance_linear_perp_pairs"]
    elif cost_positive <= 0:
        decision = "PIT_LINEAR_PERP_SCREEN_REJECTED_NO_EDGE_AFTER_BASE_COSTS"
        reasons = ["no_positive_screening_edge_after_fixed_base_cost_hurdle"]
    else:
        decision = "PIT_LINEAR_PERP_SCREEN_CANDIDATES_REQUIRE_DEEPER_EVIDENCE"
        reasons = [
            "screening_candidates_are_not_trades",
            "top_of_book_quantity_contract_spec_funding_and_exact_quote_age_are_missing",
        ]

    first_ts = state["first_ts"]
    last_ts = state["last_ts"]
    span_hours = (last_ts - first_ts).total_seconds() / 3600.0 if first_ts and last_ts else 0.0
    spot_verdict = (
        "REJECTED_INSTRUMENT_MISMATCH_AND_PRIOR_NEGATIVE_SPOT_SCAN"
        if prior_spot and prior_spot.get("decision") == "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES"
        else "NOT_EVALUATED_CURRENT_SOURCE_IS_LINEAR_PERP"
    )
    report: dict[str, Any] = {
        "schema": SCREEN_SCHEMA,
        "mode": SCREEN_MODE,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "screening_only": True,
        "accepted": False,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "backtest_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_ready": False,
        "source": {
            "spec_path": str(spec_file),
            "spec_sha256": _sha256_file(spec_file),
            "mask_sha256": spec["mask_sha256"],
            "run_id": source_run_id,
            "snapshots_path": str(snapshots_path),
            "snapshots_sha256": observed_snapshots_hash,
            "full_dataset_verdict": "rejected_not_modified",
            "clean_slice_materialized": False,
            "selection_applied_streaming": True,
        },
        "instrument_scope": {
            "screened_contract_type": cfg.contract_type,
            "observed_contract_types": sorted(state["observed_contract_types"]),
            "supports_spot_objective": False,
            "spot_rows_screened": 0,
            "note": "PIT source contains derivative ticker BBO. This report must not be described as a spot scan.",
        },
        "spot_objective_verdict": spot_verdict,
        "prior_spot_evidence": prior_spot,
        "config": asdict(cfg) | {"total_cost_bps": cfg.total_cost_bps},
        "cost_model": {
            "total_cost_bps": cfg.total_cost_bps,
            "round_trip_fee_bps": cfg.round_trip_fee_bps,
            "slippage_bps": cfg.slippage_bps,
            "operational_buffer_bps": cfg.operational_buffer_bps,
            "funding_pnl_included": False,
            "note": "Fixed base/VIP0 screening hurdle. Positive values still require contract, depth, funding and execution evidence.",
        },
        "time_span": {
            "start_utc": first_ts.isoformat() if first_ts else None,
            "end_utc": last_ts.isoformat() if last_ts else None,
            "span_hours": span_hours,
        },
        "summary": {
            "source_rows": state["source_rows"],
            "retained_rows": state["retained_rows"],
            "dropped_rows": state["dropped_rows"],
            "source_cycles_seen": len(state["source_cycles_seen"]),
            "retained_cycles_seen": len(state["retained_cycles_seen"]),
            "dropped_cycles_seen": len(state["source_cycles_seen"] & dropped_cycles),
            "eligible_instrument_rows": state["eligible_instrument_rows"],
            "instrument_mismatch_rows": state["instrument_mismatch_rows"],
            "invalid_bbo_rows": state["invalid_bbo_rows"],
            "ambiguous_duplicate_base_rows": state["ambiguous_duplicate_base_rows"],
            "matched_bases": len(state["matched_bases"]),
            "matched_cycle_bases": state["matched_cycle_bases"],
            "evaluations": state["evaluations"],
            "positive_gross_events": state["positive_gross_events"],
            "cost_positive_events": cost_positive,
            "cost_positive_bases": len(state["cost_positive_bases"]),
            "max_gross_edge_bps": max_gross,
            "max_net_screening_edge_bps": max_net,
            "max_consecutive_cost_positive_cycles": state["max_consecutive_cost_positive_cycles"],
            "scan_complete": True,
        },
        "top_events": top_events,
        "per_base": per_base,
        "rejection_or_limit_reasons": reasons,
        "evidence_gaps": [
            "instrument_is_linear_perp_not_spot",
            "bid_ask_quantity_and_executable_capacity_missing",
            "contract_multiplier_and_spec_parity_not_verified",
            "exchange_quote_timestamps_and_subsecond_staleness_missing",
            "funding_rate_and_funding_pnl_missing",
            "single_approximately_24h_window_has_no_independent_oos_holdout",
            "seven_gateio_timeout_cycles_are_excluded_by_predeclared_availability_mask",
        ],
        "next_valid_moves": (
            [
                "Reject the linear-perp screening branch under the fixed base-cost hurdle.",
                "Do not reopen the previously rejected spot branch without genuinely new admissible spot evidence.",
            ]
            if cost_positive <= 0
            else [
                "Treat candidates only as a data-acquisition hypothesis, not as trades or PnL.",
                "Verify contract multipliers, executable depth, exact quote timestamps and funding before defining labels.",
                "Predeclare OOS/walk-forward/stress/economics gates before any replay or backtest.",
            ]
        ),
        "blocked_actions": [
            "interpret_as_spot_dislocation_result",
            "materialize_filtered_jsonl_without_separate_gate",
            "replay_or_backtest",
            "grid_optimization",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ],
        "output_path": str(output_file),
    }
    _atomic_write_json(output_file, report)
    return report


def _validate_spec(spec: dict[str, Any], spec_path: Path) -> dict[str, Any]:
    if spec.get("schema") != SPEC_SCHEMA or spec.get("mode") != SPEC_MODE:
        raise ValueError("unsupported clean-slice spec schema/mode")
    if spec.get("decision") != SPEC_DECISION:
        raise ValueError("clean-slice spec is not ready")
    if spec.get("would_materialize") is not False:
        raise ValueError("clean-slice spec must be non-materializing")
    if spec.get("strategy_accepted") is not False or spec.get("replay_allowed") is not False:
        raise ValueError("clean-slice spec safety flags are not fail-closed")
    source_run = _dict(spec.get("source_run"), "source_run")
    run_id = str(source_run.get("run_id") or "")
    if not run_id or source_run.get("manifest_final") is not True:
        raise ValueError("source run must be final and have a run_id")
    if source_run.get("full_dataset_verdict") != "rejected_not_modified":
        raise ValueError("full dataset rejection must remain explicit")
    cycle_count = _positive_int(source_run.get("cycle_count"), "source_run.cycle_count")
    source_rows = _positive_int(source_run.get("rows_total"), "source_run.rows_total")

    rule = _dict(spec.get("selection_rule"), "selection_rule")
    if sorted(rule.get("required_exchanges") or []) != list(SUPPORTED_EXCHANGES):
        raise ValueError("clean-slice spec must require gateio and mexc")
    for key, expected in (
        ("whole_cycle_only", True),
        ("forward_fill_allowed", False),
        ("imputation_allowed", False),
        ("symbol_level_filtering_allowed", False),
    ):
        if rule.get(key) is not expected:
            raise ValueError(f"unsafe selection rule: {key}")

    mask = _dict(spec.get("mask"), "mask")
    retained = {_positive_int(value, "retained cycle") for value in mask.get("retained_cycles") or []}
    dropped = {_positive_int(value, "dropped cycle") for value in mask.get("dropped_cycles") or []}
    expected = set(range(1, cycle_count + 1))
    if retained & dropped or retained | dropped != expected:
        raise ValueError("clean-slice cycle masks must be exclusive and cover the source run")
    if not retained:
        raise ValueError("clean-slice mask retains no cycles")
    mask_payload = _dict(spec.get("mask_hash_payload"), "mask_hash_payload")
    observed_mask_hash = _canonical_sha256(mask_payload)
    if observed_mask_hash != spec.get("mask_sha256"):
        raise ValueError("clean-slice mask SHA-256 mismatch")
    if set(mask_payload.get("retained_cycles") or []) != retained or set(mask_payload.get("dropped_cycles") or []) != dropped:
        raise ValueError("mask hash payload does not match clean-slice masks")

    artifacts = _dict(spec.get("source_artifacts"), "source_artifacts")
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for label in ("manifest", "cycles", "snapshots"):
        item = _dict(artifacts.get(label), f"source_artifacts.{label}")
        path = Path(str(item.get("path") or "")).resolve()
        expected_hash = str(item.get("sha256") or "").lower()
        if not path.is_file() or len(expected_hash) != 64:
            raise ValueError(f"invalid {label} source artifact")
        paths[label] = path
        hashes[label] = expected_hash
    for label in ("manifest", "cycles"):
        observed = _sha256_file(paths[label])
        if observed != hashes[label]:
            raise ValueError(f"{label} SHA-256 mismatch: expected={hashes[label]}, observed={observed}")

    manifest = _load_json(paths["manifest"], "source manifest")
    if manifest.get("run_id") != run_id or manifest.get("final") is not True:
        raise ValueError("source manifest run_id/final mismatch")
    if int(manifest.get("cycle_count") or 0) != cycle_count or int(manifest.get("rows_total") or 0) != source_rows:
        raise ValueError("source manifest counts do not match clean-slice spec")
    if spec_path in paths.values():
        raise ValueError("clean-slice spec must be outside source artifacts")
    return {
        "run_id": run_id,
        "source_rows": source_rows,
        "retained_cycles": retained,
        "dropped_cycles": dropped,
        "manifest_path": paths["manifest"],
        "cycles_path": paths["cycles"],
        "snapshots_path": paths["snapshots"],
        "snapshots_sha256": hashes["snapshots"],
    }


def _new_state() -> dict[str, Any]:
    return {
        "source_rows": 0,
        "retained_rows": 0,
        "dropped_rows": 0,
        "source_cycles_seen": set(),
        "retained_cycles_seen": set(),
        "observed_contract_types": set(),
        "eligible_instrument_rows": 0,
        "instrument_mismatch_rows": 0,
        "invalid_bbo_rows": 0,
        "ambiguous_duplicate_base_rows": 0,
        "matched_bases": set(),
        "matched_cycle_bases": 0,
        "evaluations": 0,
        "positive_gross_events": 0,
        "cost_positive_events": 0,
        "cost_positive_bases": set(),
        "max_consecutive_cost_positive_cycles": 0,
        "last_positive_cycle": {},
        "positive_run_length": {},
        "top_events": [],
        "per_base": {},
        "first_ts": None,
        "last_ts": None,
    }


def _process_cycle(cycle: int, rows: list[dict[str, Any]], cfg: PitCrossVenueScreenConfig, state: dict[str, Any]) -> None:
    by_base: dict[str, dict[str, dict[str, Any]]] = {}
    ambiguous: set[tuple[str, str]] = set()
    cycle_ts: datetime | None = None
    for row in rows:
        contract_type = str(row.get("contract_type") or "")
        if contract_type:
            state["observed_contract_types"].add(contract_type)
        if contract_type != cfg.contract_type:
            state["instrument_mismatch_rows"] += 1
            continue
        if not _is_eligible_row(row, cfg):
            continue
        quote = _parse_quote(row)
        if quote is None:
            state["invalid_bbo_rows"] += 1
            continue
        exchange = quote["exchange"]
        base = quote["base"]
        key = (exchange, base)
        if exchange in by_base.setdefault(base, {}):
            ambiguous.add(key)
            state["ambiguous_duplicate_base_rows"] += 1
            continue
        by_base[base][exchange] = quote
        state["eligible_instrument_rows"] += 1
        row_ts = _parse_timestamp(row.get("snapshot_ts"))
        if row_ts:
            cycle_ts = row_ts if cycle_ts is None else min(cycle_ts, row_ts)
            state["first_ts"] = row_ts if state["first_ts"] is None else min(state["first_ts"], row_ts)
            state["last_ts"] = row_ts if state["last_ts"] is None else max(state["last_ts"], row_ts)

    for base, quotes in by_base.items():
        if any((exchange, base) in ambiguous for exchange in SUPPORTED_EXCHANGES):
            continue
        if any(exchange not in quotes for exchange in SUPPORTED_EXCHANGES):
            continue
        state["matched_bases"].add(base)
        state["matched_cycle_bases"] += 1
        gate = quotes["gateio"]
        mexc = quotes["mexc"]
        for buy, sell, direction in (
            (mexc, gate, "buy_mexc_sell_gateio"),
            (gate, mexc, "buy_gateio_sell_mexc"),
        ):
            state["evaluations"] += 1
            gross = (sell["bid_price"] / buy["ask_price"] - 1.0) * 10_000.0
            net = gross - cfg.total_cost_bps
            stats = state["per_base"].setdefault(
                base,
                {
                    "base": base,
                    "evaluations": 0,
                    "positive_gross_events": 0,
                    "cost_positive_events": 0,
                    "max_gross_edge_bps": None,
                    "max_net_screening_edge_bps": None,
                },
            )
            stats["evaluations"] += 1
            stats["max_gross_edge_bps"] = _nullable_max(stats["max_gross_edge_bps"], gross)
            stats["max_net_screening_edge_bps"] = _nullable_max(stats["max_net_screening_edge_bps"], net)
            if gross <= 0:
                continue
            state["positive_gross_events"] += 1
            stats["positive_gross_events"] += 1
            event = {
                "cycle": cycle,
                "snapshot_ts": cycle_ts.isoformat() if cycle_ts else None,
                "base": base,
                "contract_type": cfg.contract_type,
                "direction": direction,
                "buy_exchange": buy["exchange"],
                "buy_symbol": buy["symbol"],
                "buy_ask": buy["ask_price"],
                "sell_exchange": sell["exchange"],
                "sell_symbol": sell["symbol"],
                "sell_bid": sell["bid_price"],
                "gross_edge_bps": gross,
                "net_screening_edge_bps": net,
                "total_cost_bps": cfg.total_cost_bps,
                "min_24h_quote_volume": min(buy["volume_24h_quote"], sell["volume_24h_quote"]),
                "buy_spread_bps": buy["spread_bps"],
                "sell_spread_bps": sell["spread_bps"],
                "capacity_quote": None,
                "funding_pnl": None,
            }
            _keep_top(state["top_events"], event, cfg.max_events)
            if net <= 0:
                continue
            state["cost_positive_events"] += 1
            state["cost_positive_bases"].add(base)
            stats["cost_positive_events"] += 1
            sequence_key = (base, direction)
            previous_cycle = state["last_positive_cycle"].get(sequence_key)
            run_length = state["positive_run_length"].get(sequence_key, 0) + 1 if previous_cycle == cycle - 1 else 1
            state["last_positive_cycle"][sequence_key] = cycle
            state["positive_run_length"][sequence_key] = run_length
            state["max_consecutive_cost_positive_cycles"] = max(
                state["max_consecutive_cost_positive_cycles"], run_length
            )


def _is_eligible_row(row: dict[str, Any], cfg: PitCrossVenueScreenConfig) -> bool:
    return (
        str(row.get("exchange") or "").lower() in SUPPORTED_EXCHANGES
        and str(row.get("quote") or "").upper() == cfg.quote.upper()
        and row.get("eligible_non_binance_spot") is True
        and row.get("binance_spot_listed") is False
        and row.get("excluded_by_binance_spot") is False
        and row.get("listed_now") is True
        and row.get("observed_now") is True
        and row.get("tombstone") is False
        and row.get("inactive_or_delisted") is False
        and str(row.get("status") or "").lower() == "trading"
    )


def _parse_quote(row: dict[str, Any]) -> dict[str, Any] | None:
    exchange = str(row.get("exchange") or "").lower()
    symbol = str(row.get("symbol") or "")
    base = str(row.get("base") or "").upper()
    bid = _float(row.get("bid_price"))
    ask = _float(row.get("ask_price"))
    volume = _float(row.get("volume_24h_quote"))
    spread = _float(row.get("spread_bps"))
    if not symbol or not base or bid is None or ask is None or volume is None:
        return None
    if bid <= 0 or ask <= 0 or ask < bid or volume < 0:
        return None
    if spread is None:
        mid = (bid + ask) / 2.0
        spread = (ask - bid) / mid * 10_000.0
    return {
        "exchange": exchange,
        "symbol": symbol,
        "base": base,
        "bid_price": bid,
        "ask_price": ask,
        "volume_24h_quote": volume,
        "spread_bps": spread,
    }


def _validate_scan_counts(
    state: dict[str, Any],
    spec: dict[str, Any],
    expected_cycles: set[int],
    retained_cycles: set[int],
    dropped_cycles: set[int],
) -> None:
    mask = _dict(spec.get("mask"), "mask")
    source_run = _dict(spec.get("source_run"), "source_run")
    checks = (
        (state["source_rows"], int(source_run["rows_total"]), "source row count"),
        (state["retained_rows"], int(mask["retained_rows"]), "retained row count"),
        (state["dropped_rows"], int(mask["dropped_rows"]), "dropped row count"),
    )
    for observed, expected, label in checks:
        if observed != expected:
            raise ValueError(f"{label} mismatch: expected={expected}, observed={observed}")
    if state["source_cycles_seen"] != expected_cycles:
        raise ValueError("snapshots do not cover every masked source cycle")
    if state["retained_cycles_seen"] != retained_cycles:
        raise ValueError("snapshots retained-cycle coverage mismatch")
    if state["source_cycles_seen"] & dropped_cycles != dropped_cycles:
        raise ValueError("snapshots dropped-cycle coverage mismatch")


def _load_prior_spot_evidence(path_value: str) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = Path(path_value).resolve()
    payload = _load_json(path, "prior spot report")
    summary = _dict(payload.get("summary"), "prior spot summary")
    config = _dict(payload.get("config"), "prior spot config")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "decision": payload.get("decision"),
        "accepted": bool(payload.get("accepted")),
        "eligible_events": int(summary.get("eligible_events") or 0),
        "max_gross_edge_bps": summary.get("max_gross_edge_bps"),
        "max_net_edge_bps": summary.get("max_net_edge_bps"),
        "total_cost_bps": config.get("total_cost_bps"),
    }


def _keep_top(events: list[dict[str, Any]], event: dict[str, Any], limit: int) -> None:
    events.append(event)
    if len(events) > limit * 2:
        events.sort(key=lambda item: float(item["net_screening_edge_bps"]), reverse=True)
        del events[limit:]


def _sorted_top(events: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(events, key=lambda item: float(item["net_screening_edge_bps"]), reverse=True)[:limit]


def _per_base_report(stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(value) for value in stats.values()),
        key=lambda item: float(
            item["max_net_screening_edge_bps"]
            if item["max_net_screening_edge_bps"] is not None
            else -1e18
        ),
        reverse=True,
    )


def _max_value(rows: list[dict[str, Any]], key: str) -> float | None:
    return max((float(row[key]) for row in rows), default=None)


def _nullable_max(current: float | None, value: float) -> float:
    return value if current is None else max(current, value)


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream a PIT clean-slice linear-perp cross-venue screening report")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--round-trip-fee-bps", type=float, default=39.0)
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    parser.add_argument("--operational-buffer-bps", type=float, default=20.0)
    parser.add_argument("--max-events", type=int, default=1000)
    parser.add_argument("--progress-every-rows", type=int, default=50_000)
    parser.add_argument("--prior-spot-report", default="")
    args = parser.parse_args()
    report = run_pit_cross_venue_screen(
        args.spec,
        args.out,
        PitCrossVenueScreenConfig(
            round_trip_fee_bps=args.round_trip_fee_bps,
            slippage_bps=args.slippage_bps,
            operational_buffer_bps=args.operational_buffer_bps,
            max_events=args.max_events,
            progress_every_rows=args.progress_every_rows,
            prior_spot_report_path=args.prior_spot_report,
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
