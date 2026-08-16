from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = "trading_mvp_slow_liquidity_exploratory_fixed_v1_packet_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_event_census_v1_v6_identity_20260816.json"
)
OUTPUT_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_exploratory_fixed_v1_packet_20260816.json"
)
TOP_FAMILY = "volatility_expansion_continuation_v1"
ALLOWED_FAMILIES = (
    "volatility_expansion_continuation_v1",
    "liquidity_shock_reclaim_long_v1",
)
FAMILY_NAMES = {
    "volatility_expansion_continuation_v1": (
        "slow_liquidity_volatility_expansion_continuation_v1"
    ),
    "liquidity_shock_reclaim_long_v1": (
        "slow_liquidity_liquidity_shock_reclaim_long_v1"
    ),
}


class ExploratoryPacketError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ExploratoryPacketError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_packet(generated_at_utc: str, family: str = TOP_FAMILY) -> dict[str, Any]:
    census = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
    families = census.get("event_census", {}).get("family_summaries") or {}
    top = families.get(family) or {}
    _require(family in ALLOWED_FAMILIES, f"family not allowed: {family}")
    _require(bool(top), "family missing from census")
    _require(
        census.get("data_scope", {}).get("clean_bases")
        == ["BDX", "CC", "MNT", "OKB", "STETH", "USDD", "WEETH"],
        "census universe is not the identity-accepted 7 bases",
    )
    missed = []
    if int(top.get("independent_events") or 0) < 100:
        missed.append("independent_events<100")
    if int(top.get("event_bases") or 0) < 7:
        missed.append("event_bases<7")
    if float(top.get("max_single_base_event_fraction") or 1.0) > 0.25:
        missed.append("max_single_base_event_fraction>0.25")
    _require(
        bool(missed),
        "family unexpectedly passes frozen acceptance; use the standard "
        "fixed_v1 gate tool instead of this exploratory packet",
    )
    packet: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": generated_at_utc,
        "mode": "exploratory_replay_only",
        "exploratory_underpowered": True,
        "acceptance_eligible": False,
        "acceptance_missed_criteria": missed,
        "research_only": True,
        "event_census_path": str(CENSUS_PATH),
        "event_census_file_sha256": _sha256_file(CENSUS_PATH),
        "fixed_signal_v1": {
            "name": FAMILY_NAMES[family],
            "family": family,
            "direction": "long_only_spot",
            "primary_timeframe": "1h",
            "context_timeframe": "4h",
            "clean_bases": census["data_scope"]["clean_bases"],
            "entry_rule": "enter next 1h open after accepted volatility expansion candle",
            "event_filters": {
                "context_4h_pass": "4h close above SMA(24) or 4h range midpoint",
                "min_body_bps": 120.0,
                "min_true_range_atr": 2.0,
                "min_volume_percentile": 0.75,
                "min_target_geometry_bps": 300.0,
                "disabled_timeframes": ["15m"],
            },
            "stop_rule": "min(expansion candle low, expansion close - 1.5 * prior 1h ATR)",
            "target_rule": "max(2R, 300 bps) from entry",
            "max_hold_bars": 72,
            "cluster_window_sec": 43200,
            "no_grid": True,
        },
        "event_base_rate": {
            "top_family": family,
            "top_family_independent_events": int(top.get("independent_events") or 0),
            "top_family_event_bases": int(top.get("event_bases") or 0),
            "top_family_event_exchanges": int(top.get("event_exchanges") or 0),
            "top_family_max_single_base_event_fraction": float(
                top.get("max_single_base_event_fraction") or 0.0
            ),
            "total_independent_events": int(
                census.get("event_census", {}).get("independent_events") or 0
            ),
        },
        "cost_model": {
            "account_assumption": "base/VIP0/no-volume",
            "normal_round_trip_fee_bps": 40.0,
            "normal_spread_slippage_buffer_bps": 80.0,
            "normal_total_cost_bps": 120.0,
            "stress_total_cost_bps": 245.0,
            "minimum_target_geometry_bps": 300.0,
            "rule": "Exploratory only: acceptance decisions are void; costs still applied fully.",
        },
        "interpretation_guard": (
            "This packet exists to execute a factual exploratory replay of the "
            "original slow-liquidity hypothesis families on the exact v6 "
            "dataset under the identity-accepted 7-base universe. The family "
            "misses the frozen acceptance thresholds, so NO accept/reject "
            "strategy verdict may be derived from the resulting replay; it "
            "is evidence about event economics only."
        ),
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-packet", action="store_true")
    parser.add_argument("--family", default=TOP_FAMILY)
    args = parser.parse_args(argv)
    if not args.write_packet:
        raise SystemExit("no authorized action requested")
    generated = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    packet = build_packet(generated, family=args.family)
    output_path = (
        OUTPUT_PATH
        if args.family == TOP_FAMILY
        else OUTPUT_PATH.with_name(
            OUTPUT_PATH.stem + "_" + args.family.split("_")[0] + OUTPUT_PATH.suffix
        )
    )
    content = json.dumps(packet, indent=2, ensure_ascii=False) + "\n"
    if output_path.exists():
        _require(
            output_path.read_text(encoding="utf-8") == content,
            f"immutable artifact mismatch: {output_path}",
        )
    else:
        output_path.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PACKET_WRITTEN",
                "path": str(output_path),
                "packet_hash": packet["packet_hash"],
                "family": args.family,
                "missed_criteria": packet["acceptance_missed_criteria"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
