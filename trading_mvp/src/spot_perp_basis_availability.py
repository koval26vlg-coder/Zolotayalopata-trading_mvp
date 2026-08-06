from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DAILY_RUN_ID = "daily_collect_20260702_top200"
REQUIRED_FIELDS = (
    "spot_mid",
    "spot_spread_bps",
    "spot_depth_top",
    "perp_mid_or_mark",
    "perp_spread_bps",
    "perp_depth_top",
    "funding_rate",
    "next_funding_ts",
)


@dataclass(frozen=True)
class EndpointCapability:
    exchange: str
    venue: str
    field: str
    source: str
    available_via_public_api: bool
    available_in_existing_files: bool
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


PUBLIC_ENDPOINT_MATRIX: tuple[EndpointCapability, ...] = (
    EndpointCapability("mexc", "spot", "spot_mid", "GET /api/v3/depth", True, False, "mid from best bid/ask"),
    EndpointCapability("mexc", "spot", "spot_spread_bps", "GET /api/v3/depth", True, False, "spread from best bid/ask"),
    EndpointCapability("mexc", "spot", "spot_depth_top", "GET /api/v3/depth", True, False, "top-of-book quantities"),
    EndpointCapability("mexc", "perp", "perp_mid_or_mark", "GET /api/v1/contract/ticker and funding_rate/{symbol}", True, True, "fairPrice or bid1/ask1 mid"),
    EndpointCapability("mexc", "perp", "perp_spread_bps", "GET /api/v1/contract/ticker", True, False, "bid1/ask1 spread; not in daily files"),
    EndpointCapability("mexc", "perp", "perp_depth_top", "contract depth endpoint required", True, False, "not stored by current daily history"),
    EndpointCapability("mexc", "perp", "funding_rate", "GET /api/v1/contract/funding_rate/history", True, True, "daily funding history files exist"),
    EndpointCapability("mexc", "perp", "next_funding_ts", "GET /api/v1/contract/funding_rate/{symbol}", True, False, "snapshot-only public field"),
    EndpointCapability("gateio", "spot", "spot_mid", "GET /spot/order_book", True, False, "mid from best bid/ask"),
    EndpointCapability("gateio", "spot", "spot_spread_bps", "GET /spot/order_book", True, False, "spread from best bid/ask"),
    EndpointCapability("gateio", "spot", "spot_depth_top", "GET /spot/order_book", True, False, "top-of-book quantities"),
    EndpointCapability("gateio", "perp", "perp_mid_or_mark", "GET /futures/usdt/tickers", True, True, "mark/index in public ticker/contract snapshots"),
    EndpointCapability("gateio", "perp", "perp_spread_bps", "GET /futures/usdt/tickers", True, False, "highest_bid/lowest_ask; not in daily files"),
    EndpointCapability("gateio", "perp", "perp_depth_top", "futures order book endpoint required", True, False, "not stored by current daily history"),
    EndpointCapability("gateio", "perp", "funding_rate", "GET /futures/usdt/funding_rate", True, True, "daily funding history files exist"),
    EndpointCapability("gateio", "perp", "next_funding_ts", "GET /futures/usdt/contracts", True, False, "snapshot-only public field"),
)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_non_binance_bases(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    bases: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol:
                bases.add(symbol)
    return bases


def default_daily_run(exports_root: Path) -> Path | None:
    preferred = exports_root / "daily" / DEFAULT_DAILY_RUN_ID
    if (preferred / "manifest.json").exists():
        return preferred
    manifests = sorted(
        (exports_root / "daily").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return manifests[0].parent if manifests else None


def _symbol_file_count(root: Path, exchange: str, folder: str) -> int:
    path = root / exchange / folder
    if not path.exists():
        return 0
    return sum(1 for item in path.glob("*.json") if item.is_file() and item.stat().st_size > 0)


def summarize_daily_run(run_dir: Path | None, non_binance_bases: set[str]) -> dict[str, Any]:
    if run_dir is None:
        return {
            "present": False,
            "run_dir": None,
            "reason": "daily_run_missing",
            "candidate_non_binance_bases": [],
            "candidate_non_binance_bases_count": 0,
        }
    manifest = load_json(run_dir / "manifest.json")
    if manifest is None:
        return {
            "present": False,
            "run_dir": str(run_dir),
            "reason": "manifest_missing",
            "candidate_non_binance_bases": [],
            "candidate_non_binance_bases_count": 0,
        }

    by_base: dict[str, dict[str, str]] = {}
    for item in manifest.get("universe") or []:
        base = str(item.get("base") or "").upper()
        exchange = str(item.get("exchange") or "").lower()
        symbol = str(item.get("symbol") or "").upper()
        is_non_binance = bool(item.get("non_binance_baseline")) or base in non_binance_bases
        if not base or not exchange or not symbol or not is_non_binance:
            continue
        by_base.setdefault(base, {})[exchange] = symbol

    candidates = sorted(
        base for base, venues in by_base.items() if "mexc" in venues and "gateio" in venues
    )
    return {
        "present": True,
        "run_dir": str(run_dir),
        "manifest_path": str(run_dir / "manifest.json"),
        "run_id": manifest.get("run_id"),
        "klines_rows_total": int(manifest.get("klines_rows_total") or 0),
        "funding_rows_total": int(manifest.get("funding_rows_total") or 0),
        "error_count": int(manifest.get("error_count") or 0),
        "mexc_klines_files": _symbol_file_count(run_dir, "mexc", "klines"),
        "mexc_funding_files": _symbol_file_count(run_dir, "mexc", "funding"),
        "gateio_klines_files": _symbol_file_count(run_dir, "gateio", "klines"),
        "gateio_funding_files": _symbol_file_count(run_dir, "gateio", "funding"),
        "candidate_non_binance_bases": candidates,
        "candidate_non_binance_bases_count": len(candidates),
        "candidate_symbols_by_base": {base: by_base[base] for base in candidates[:50]},
    }


def endpoint_matrix_by_field() -> dict[str, dict[str, list[dict[str, Any]]]]:
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for cap in PUBLIC_ENDPOINT_MATRIX:
        out.setdefault(cap.exchange, {}).setdefault(cap.field, []).append(cap.as_dict())
    return out


def field_coverage_summary() -> dict[str, Any]:
    by_field: dict[str, list[EndpointCapability]] = {}
    for cap in PUBLIC_ENDPOINT_MATRIX:
        by_field.setdefault(cap.field, []).append(cap)
    return {
        field: {
            "public_api_available": any(cap.available_via_public_api for cap in caps),
            "existing_files_available": any(cap.available_in_existing_files for cap in caps),
            "exchanges": sorted({cap.exchange for cap in caps}),
            "missing_from_existing_files": sorted(
                {cap.exchange for cap in caps if not cap.available_in_existing_files}
            ),
        }
        for field, caps in sorted(by_field.items())
    }


def build_availability_preflight(
    *,
    repo_root: Path,
    output_path: Path | None = None,
    daily_run_dir: Path | None = None,
    universe_csv: Path | None = None,
    min_candidate_bases: int = 10,
) -> dict[str, Any]:
    exports_root = repo_root / "exports" / "trading-mvp"
    universe_path = universe_csv or repo_root / "coins_not_on_binance_full_2026-05-29.csv"
    non_binance_bases = load_non_binance_bases(universe_path)
    run_dir = daily_run_dir if daily_run_dir else default_daily_run(exports_root)
    daily = summarize_daily_run(run_dir, non_binance_bases)
    fields = field_coverage_summary()

    required_missing_existing = [
        field for field in REQUIRED_FIELDS if not fields.get(field, {}).get("existing_files_available")
    ]
    candidate_count = int(daily.get("candidate_non_binance_bases_count") or 0)
    candidate_count_ok = candidate_count >= min_candidate_bases
    public_fields_ok = all(fields.get(field, {}).get("public_api_available") for field in REQUIRED_FIELDS)

    if not public_fields_ok:
        decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED_MISSING_PUBLIC_FIELDS"
    elif not candidate_count_ok:
        decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED_TOO_FEW_CANDIDATES"
    else:
        decision = "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE"

    return {
        "mode": "spot_perp_basis_availability_preflight",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "selected_branch": "spot_perp_basis_mean_reversion_no_funding",
        "research_only": True,
        "would_start": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "strategy_accepted": False,
        "reason": "PlanOnly availability preflight. It inspects local files and endpoint contracts only; it does not call exchange APIs or collect market data.",
        "params": {
            "min_candidate_bases": min_candidate_bases,
            "universe_csv": str(universe_path),
            "daily_run_dir": str(run_dir) if run_dir else None,
        },
        "daily_history": daily,
        "required_fields": list(REQUIRED_FIELDS),
        "field_coverage": fields,
        "endpoint_matrix": endpoint_matrix_by_field(),
        "candidate_count_ok": candidate_count_ok,
        "public_fields_ok": public_fields_ok,
        "required_fields_missing_from_existing_files": required_missing_existing,
        "preflight_interpretation": {
            "existing_files_are_backtest_ready": False,
            "why_not_backtest_ready": [
                "spot top-of-book mid/spread/depth are not present in existing daily history",
                "perp spread/depth snapshots are not present in existing daily history",
                "next funding timestamp is snapshot-only and not present in daily history",
            ],
            "public_probe_needed": decision == "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE",
            "actual_collect_still_requires_explicit_user_confirmation": True,
        },
        "next_valid_moves": (
            [
                "After explicit user confirmation, run a short visible public REST availability probe for candidate bases.",
                "Probe only symbol availability and one lightweight snapshot per field; do not run long collect or backtest.",
                "If probe confirms enough paired fields, build a visible collect approval packet for spot/perp snapshots.",
            ]
            if decision == "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE"
            else [
                "Reject or rescope this branch before any data collection.",
                "Do not start collect/grid/replay/live/API/paper-forward.",
            ]
        ),
        "blocked_moves": [
            "actual_collect_without_explicit_confirmation",
            "backtest_or_replay_on_unpaired_data",
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward",
        ],
        "output_path": str(output_path) if output_path else None,
    }


def write_preflight(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(output_path)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="spot/perp basis availability PlanOnly preflight")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--daily-run-dir", default="")
    parser.add_argument("--universe-csv", default="")
    parser.add_argument("--min-candidate-bases", type=int, default=10)
    args = parser.parse_args()

    output_path = Path(args.out)
    report = build_availability_preflight(
        repo_root=Path(args.repo_root),
        output_path=output_path,
        daily_run_dir=Path(args.daily_run_dir) if args.daily_run_dir else None,
        universe_csv=Path(args.universe_csv) if args.universe_csv else None,
        min_candidate_bases=args.min_candidate_bases,
    )
    write_preflight(report, output_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
