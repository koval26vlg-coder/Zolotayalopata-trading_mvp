from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = "trading_mvp_slow_liquidity_signal_v0_compression_evidence_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
V6_DIR = Path(
    "E:/trading_mvp/slow-liquidity-history/"
    "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6"
)
V6_JSONL = V6_DIR / "ohlcv.jsonl"
V6_MANIFEST = V6_DIR / "manifest.json"
FIXED_SIGNAL_PACKET = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_fixed_signal_planonly_20260816_231913.json"
)
OUTPUT_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_signal_v0_compression_gate_evidence_20260816.json"
)
LOOKBACK_BARS = 96
STRIDE_BARS = 12
REFERENCE_THRESHOLDS = (1.2, 4.0, 6.0, 8.0, 10.0, 12.0)


class CompressionEvidenceError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise CompressionEvidenceError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bindings() -> dict[str, Any]:
    _require(V6_JSONL.is_file(), "v6 ohlcv missing")
    manifest = json.loads(V6_MANIFEST.read_text(encoding="utf-8"))
    packet = json.loads(FIXED_SIGNAL_PACKET.read_text(encoding="utf-8"))
    signal = packet.get("fixed_signal_v0") or {}
    threshold = float(signal.get("compression_range_width_max_atr") or 1.2)
    _require(
        threshold == 1.2,
        "packet compression threshold drifted from the frozen v0 contract",
    )
    return {
        "manifest": manifest,
        "packet": packet,
        "threshold": threshold,
        "v6_sha256": _sha256_file(V6_JSONL),
        "manifest_sha256": _sha256_file(V6_MANIFEST),
        "packet_sha256": _sha256_file(FIXED_SIGNAL_PACKET),
    }


def average_true_range(
    candles: list[tuple[int, float, float, float]], index: int, window: int
) -> float:
    true_ranges = []
    for k in range(max(0, index - window), index):
        previous_close = candles[k - 1][3] if k > 0 else candles[k][2]
        high, low, close = candles[k][1], candles[k][2], candles[k][3]
        true_ranges.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
    return statistics.fmean(true_ranges) if true_ranges else 0.0


def compute_compression_distribution(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    by_market: dict[tuple[str, str], list[tuple[int, float, float, float]]] = defaultdict(
        list
    )
    for row in rows:
        if row.get("granularity") == "1h" and row.get("data_status") == "ok":
            by_market[(str(row["exchange"]), str(row["symbol"]))].append(
                (
                    int(row["candle_ts"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                )
            )
    markets: list[dict[str, Any]] = []
    all_medians: list[float] = []
    all_values: list[float] = []
    for key in sorted(by_market):
        candles = sorted(by_market[key])
        values: list[float] = []
        for index in range(LOOKBACK_BARS, len(candles) - 14, STRIDE_BARS):
            prior = candles[index - LOOKBACK_BARS : index]
            range_high = max(item[1] for item in prior)
            range_low = min(item[2] for item in prior)
            atr = average_true_range(candles, index, LOOKBACK_BARS)
            if atr > 0:
                values.append((range_high - range_low) / atr)
        if not values:
            continue
        ordered = sorted(values)
        median = statistics.median(values)
        all_medians.append(median)
        all_values.extend(values)
        markets.append(
            {
                "exchange": key[0],
                "symbol": key[1],
                "bars_sampled": len(values),
                "range_width_atr_median": round(median, 2),
                "range_width_atr_p10": round(ordered[len(ordered) // 10], 2),
                "range_width_atr_min": round(ordered[0], 2),
                "range_width_atr_max": round(ordered[-1], 2),
            }
        )
    pass_counts = {
        str(threshold): sum(1 for value in all_values if value <= threshold)
        for threshold in REFERENCE_THRESHOLDS
    }
    return {
        "markets": markets,
        "market_count": len(markets),
        "bars_evaluated": len(all_values),
        "median_of_market_medians": (
            round(statistics.median(all_medians), 2) if all_medians else None
        ),
        "global_min": round(min(all_values), 2) if all_values else None,
        "global_max": round(max(all_values), 2) if all_values else None,
        "contract_threshold": REFERENCE_THRESHOLDS[0],
        "bars_passing_contract_threshold": pass_counts[str(REFERENCE_THRESHOLDS[0])],
        "pass_counts_by_reference_threshold": pass_counts,
    }


def build_evidence_payload() -> dict[str, Any]:
    bindings = load_bindings()
    rows = [
        json.loads(line)
        for line in V6_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    distribution = compute_compression_distribution(rows)
    _require(
        distribution["market_count"] == 18,
        "expected 18 clean two-venue 1h markets",
    )
    _require(
        distribution["bars_passing_contract_threshold"] == 0,
        "some bars unexpectedly pass the contract threshold",
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "evidence_class": "SIGNAL_V0_COMPRESSION_GATE_UNREACHABLE_EVIDENCE",
        "claim": (
            "The frozen v0 signal compression gate (96-bar range width <= "
            "1.2 x ATR) is unreachable on the exact v6 dataset: zero of the "
            "evaluated bars pass it on any of the 18 markets, while the "
            "empirical median ratio is an order of magnitude higher."
        ),
        "bindings": {
            "v6_ohlcv_sha256": bindings["v6_sha256"],
            "v6_manifest_sha256": bindings["manifest_sha256"],
            "fixed_signal_packet_sha256": bindings["packet_sha256"],
            "fixed_signal_packet_decision": bindings["packet"].get("decision"),
            "compression_range_width_max_atr": bindings["threshold"],
        },
        "method": {
            "lookback_bars": LOOKBACK_BARS,
            "stride_bars": STRIDE_BARS,
            "metric": "(max(high) - min(low)) over prior 96 1h bars / mean true range of the same window",
        },
        "distribution": distribution,
        "implication": (
            "Signal v0 as defined produces zero candidate events on any "
            "realistic volatile market; feature normalizer and replay are "
            "correctly blocked (min_independent_events=100). A factual "
            "replay of v0 would contain zero trades. Any change to the "
            "compression threshold is a signal-contract change requiring an "
            "explicit user checkpoint."
        ),
        "reference_threshold_note": (
            "pass_counts_by_reference_threshold is informational only and "
            "does not authorize changing the frozen threshold"
        ),
    }
    payload["evidence_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "evidence_hash"}
    )
    return payload


def validate_evidence_payload(payload: Mapping[str, Any]) -> None:
    _require(payload.get("schema") == SCHEMA, "schema mismatch")
    distribution = payload.get("distribution") or {}
    _require(
        distribution.get("bars_passing_contract_threshold") == 0,
        "evidence claim contradicted by data",
    )
    _require(
        distribution.get("market_count") == 18, "market coverage"
    )
    _require(
        payload.get("evidence_hash")
        == canonical_hash(
            {
                key: value
                for key, value in payload.items()
                if key != "evidence_hash"
            }
        ),
        "evidence hash mismatch",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    if not args.write_evidence:
        raise SystemExit("no authorized action requested")
    output_path = Path(args.output) if args.output else OUTPUT_PATH
    payload = build_evidence_payload()
    validate_evidence_payload(payload)
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output_path.exists():
        _require(
            output_path.read_text(encoding="utf-8") == content,
            f"immutable artifact mismatch: {output_path}",
        )
        return_code_path = output_path
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    distribution = payload["distribution"]
    print(
        json.dumps(
            {
                "status": "EVIDENCE_WRITTEN",
                "path": str(output_path),
                "evidence_hash": payload["evidence_hash"],
                "market_count": distribution["market_count"],
                "bars_evaluated": distribution["bars_evaluated"],
                "bars_passing_contract_threshold": distribution[
                    "bars_passing_contract_threshold"
                ],
                "median_of_market_medians": distribution[
                    "median_of_market_medians"
                ],
                "pass_counts_by_reference_threshold": distribution[
                    "pass_counts_by_reference_threshold"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
