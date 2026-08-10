from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


WATCHLIST_ONLY = "WATCHLIST_ONLY_NOT_EDGE_EVIDENCE"
INVALID_EVIDENCE = "FUNDING_FORWARD_AUDIT_REJECTED_INVALID_EVIDENCE"
OFFICIAL_IDENTITY = "OFFICIAL_SAME_ASSET_VERIFIED"
UNVERIFIED_IDENTITY = "UNIQUE_SOURCE_ID_NOT_EXCHANGE_VERIFIED"
COLLISION_IDENTITY = "TICKER_COLLISION_FAIL_CLOSED"
MISSING_IDENTITY = "SOURCE_ID_MISSING_FAIL_CLOSED"

AUTO_MAX_E = 8
AUTO_MAX_G = 6
AUTO_MIN_LEG_PCT = 20.0
AUTO_MIN_CONSISTENCY = 0.75
AUTO_MIN_SPREAD_PCT = 15.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_ref(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _float(value: Any) -> float:
    return float(value)


def _close(left: Any, right: Any, tolerance: float = 0.011) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def _portable_name(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _same_path(left: Any, right: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))
    except (TypeError, ValueError):
        return False


def _expected_candidates(
    pairs: list[dict[str, Any]],
) -> tuple[list[str], set[str], set[str]]:
    e_scored: list[tuple[float, str]] = []
    g_scored: list[tuple[float, str]] = []
    for pair in pairs:
        symbol = str(pair.get("symbol") or "")
        if not symbol:
            continue
        leg = (pair.get("leg_annualized_pct") or {}).get("mexc")
        if pair.get("mexc_spot_available") and leg is not None and float(leg) >= AUTO_MIN_LEG_PCT:
            e_scored.append((float(leg), symbol))
        spread = pair.get("spread_gate_minus_mexc") or {}
        abs_spread = spread.get("abs_annualized_spread_pct")
        consistency = spread.get("sign_consistency")
        if (
            abs_spread is not None
            and consistency is not None
            and float(abs_spread) >= AUTO_MIN_SPREAD_PCT
            and float(consistency) >= AUTO_MIN_CONSISTENCY
        ):
            g_scored.append((float(abs_spread), symbol))
    e_scored.sort(reverse=True)
    g_scored.sort(reverse=True)
    e_selected = {symbol for _, symbol in e_scored[:AUTO_MAX_E]}
    g_selected = {symbol for _, symbol in g_scored[:AUTO_MAX_G]}
    selected: list[str] = []
    for _, symbol in e_scored[:AUTO_MAX_E] + g_scored[:AUTO_MAX_G]:
        if symbol not in selected:
            selected.append(symbol)
    return selected, e_selected, g_selected


def _load_registry(path: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    groups: dict[str, list[dict[str, str]]] = {}
    row_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            symbol = str(raw.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            row_count += 1
            groups.setdefault(symbol, []).append(
                {
                    "coin_id": str(raw.get("coin_id") or "").strip(),
                    "name": str(raw.get("name") or "").strip(),
                }
            )
    duplicate_groups = sum(1 for rows in groups.values() if len(rows) > 1)
    collision_groups = sum(
        1
        for rows in groups.values()
        if len({row["coin_id"] for row in rows if row["coin_id"]}) > 1
    )
    return groups, {
        "rows": row_count,
        "unique_symbols": len(groups),
        "duplicate_symbol_groups": duplicate_groups,
        "ticker_collision_groups": collision_groups,
    }


def _normalize_address(value: Any) -> str:
    return str(value or "").strip().lower()


def _official_url_valid(venue: str, value: Any) -> bool:
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return False
    host = parsed.netloc.lower().split(":", 1)[0]
    if parsed.scheme != "https":
        return False
    if venue == "mexc":
        return host == "mexc.com" or host.endswith(".mexc.com")
    if venue == "gateio":
        return host == "gate.com" or host.endswith(".gate.com")
    return False


def _identity_assets(payload: dict[str, Any], failures: list[str]) -> dict[str, dict[str, Any]]:
    if payload.get("schema") != "funding_forward_identity_evidence_v1":
        failures.append("identity_evidence_schema_mismatch")
    if payload.get("verification_scope") != "identity_only_no_profitability_claim":
        failures.append("identity_evidence_scope_mismatch")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        failures.append("identity_evidence_assets_missing")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(assets):
        if not isinstance(item, dict):
            failures.append(f"identity_evidence_assets[{index}]_not_object")
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol in result:
            failures.append(f"identity_evidence_assets[{index}]_invalid_or_duplicate_symbol")
            continue
        result[symbol] = item
    return result


def _verify_official_identity(
    base: str,
    source_coin_id: str,
    evidence: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    reasons: list[str] = []
    if str(evidence.get("symbol") or "").strip().upper() != base:
        reasons.append("symbol_mismatch")
    if str(evidence.get("source_coin_id") or "").strip() != source_coin_id:
        reasons.append("source_coin_id_mismatch")
    top_contract = evidence.get("contract") if isinstance(evidence.get("contract"), dict) else {}
    top_address = _normalize_address(top_contract.get("address"))
    if not top_address:
        reasons.append("contract_address_missing")
    venues = evidence.get("venues") if isinstance(evidence.get("venues"), list) else []
    by_venue = {
        str(item.get("venue") or "").strip().lower(): item
        for item in venues
        if isinstance(item, dict)
    }
    if set(by_venue) != {"mexc", "gateio"}:
        reasons.append("venue_set_mismatch")
    source_urls: list[str] = []
    venue_addresses: dict[str, str] = {}
    for venue in ("mexc", "gateio"):
        item = by_venue.get(venue) or {}
        if str(item.get("symbol") or "").strip().upper() != base:
            reasons.append(f"{venue}_symbol_mismatch")
        market_types = {str(value).strip().lower() for value in item.get("market_types") or []}
        if "perpetual" not in market_types:
            reasons.append(f"{venue}_perpetual_evidence_missing")
        address = _normalize_address(item.get("contract_address"))
        venue_addresses[venue] = address
        if not address or address != top_address:
            reasons.append(f"{venue}_contract_mismatch")
        urls = item.get("official_urls") if isinstance(item.get("official_urls"), list) else []
        if not urls or not all(_official_url_valid(venue, value) for value in urls):
            reasons.append(f"{venue}_official_url_invalid")
        source_urls.extend(str(value) for value in urls)
    return not reasons, reasons, {
        "network": str(top_contract.get("network") or ""),
        "contract_address": top_address,
        "venue_contract_addresses": venue_addresses,
        "official_source_urls": source_urls,
        "verification_scope": "identity_only_no_profitability_claim",
    }


def _candidate_identity(
    base: str,
    registry: dict[str, list[dict[str, str]]],
    evidence_assets: dict[str, dict[str, Any]],
    failures: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    rows = registry.get(base) or []
    coin_ids = sorted({row["coin_id"] for row in rows if row["coin_id"]})
    names = sorted({row["name"] for row in rows if row["name"]})
    result: dict[str, Any] = {
        "base": base,
        "source_coin_ids": coin_ids,
        "source_names": names,
    }
    if not coin_ids:
        result["status"] = MISSING_IDENTITY
        failures.append(f"candidate_identity_missing:{base}")
        return result
    if len(coin_ids) != 1:
        result["status"] = COLLISION_IDENTITY
        failures.append(f"candidate_identity_collision:{base}")
        return result
    evidence = evidence_assets.get(base)
    if evidence is None:
        result["status"] = UNVERIFIED_IDENTITY
        result["source_coin_id"] = coin_ids[0]
        warnings.append(f"candidate_identity_not_officially_verified:{base}")
        return result
    verified, reasons, details = _verify_official_identity(base, coin_ids[0], evidence)
    result["source_coin_id"] = coin_ids[0]
    result["official_evidence"] = details
    if verified:
        result["status"] = OFFICIAL_IDENTITY
    else:
        result["status"] = MISSING_IDENTITY
        result["official_evidence_failures"] = reasons
        failures.extend(f"candidate_identity_evidence_invalid:{base}:{reason}" for reason in reasons)
    return result


def _position_capacity(book: dict[str, Any] | None, volume: float, depth_share: float, volume_share: float) -> float:
    if not isinstance(book, dict):
        return 0.0
    depth = book.get("depth") if isinstance(book.get("depth"), dict) else {}
    band = depth.get("band_50bps") if isinstance(depth.get("band_50bps"), dict) else {}
    try:
        depth_cap = min(_float(band.get("bid_quote_usd")), _float(band.get("ask_quote_usd"))) * depth_share
        volume_cap = volume * volume_share
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(depth_cap, volume_cap)), 2)


def _route_math_failures(
    part: dict[str, Any],
    prefix: str,
    turnover_per_year: float,
    expected_capacity: float,
) -> list[str]:
    failures: list[str] = []
    cycle = part.get("cycle_cost") if isinstance(part.get("cycle_cost"), dict) else {}
    try:
        gross = abs(_float(part.get("gross_after_persistence_haircut_pct")))
        total_bps = _float(cycle.get("total_bps"))
        spread_bps = _float(cycle.get("spread_bps"))
        capacity = _float(part.get("capacity_usd"))
        annual_cost = total_bps * turnover_per_year / 100.0
        annual_spread_cost = spread_bps * turnover_per_year / 100.0
        expected_net = gross - annual_cost
        expected_usd = expected_net / 100.0 * capacity
    except (TypeError, ValueError):
        return [f"{prefix}_invalid_math_fields"]
    checks = (
        ("capacity_math_mismatch", capacity, expected_capacity),
        ("all_in_cost_math_mismatch", part.get("all_in_costs_annual_pct"), annual_cost),
        ("spread_cost_math_mismatch", part.get("spread_costs_annual_pct"), annual_spread_cost),
        ("net_math_mismatch", part.get("net_annual_pct"), expected_net),
        ("net_usd_math_mismatch", part.get("net_annual_usd_at_capacity"), expected_usd),
    )
    for suffix, observed, expected in checks:
        if not _close(observed, expected):
            failures.append(f"{prefix}_{suffix}")
    return failures


def _invalid_shell(
    manifest_path: Path,
    pairs_path: Path,
    execution_path: Path,
    universe_path: Path,
    identity_path: Path | None,
    failures: list[str],
) -> dict[str, Any]:
    stable = {
        "decision": INVALID_EVIDENCE,
        "failures": failures,
        "input_paths": [
            str(manifest_path),
            str(pairs_path),
            str(execution_path),
            str(universe_path),
            str(identity_path) if identity_path else None,
        ],
    }
    return {
        "schema": "funding_forward_audit_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": False,
        "decision": INVALID_EVIDENCE,
        "acceptance_allowed": False,
        "research_only": True,
        "failures": failures,
        "warnings": [],
        "candidates": [],
        "proof_gates": {
            "chronological_oos": "not_run",
            "walk_forward": "not_run",
            "stress": "not_run",
        },
        "deterministic_result_hash": _canonical_hash(stable),
    }


def build_funding_forward_audit(
    manifest_path: str | Path,
    pairs_path: str | Path,
    execution_path: str | Path,
    universe_path: str | Path,
    *,
    identity_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    pairs_file = Path(pairs_path)
    execution_file = Path(execution_path)
    universe_file = Path(universe_path)
    identity_file = Path(identity_evidence_path) if identity_evidence_path else None
    required = {
        "manifest": manifest_file,
        "pairs": pairs_file,
        "execution": execution_file,
        "universe": universe_file,
    }
    if identity_file is not None:
        required["identity_evidence"] = identity_file
    missing = [f"{label}_file_missing:{path}" for label, path in required.items() if not path.is_file()]
    if missing:
        return _invalid_shell(manifest_file, pairs_file, execution_file, universe_file, identity_file, missing)

    try:
        manifest = _load_json(manifest_file)
        pairs_payload = _load_json(pairs_file)
        execution = _load_json(execution_file)
        identity_payload = _load_json(identity_file) if identity_file is not None else {
            "schema": "funding_forward_identity_evidence_v1",
            "verification_scope": "identity_only_no_profitability_claim",
            "assets": [],
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid_shell(
            manifest_file,
            pairs_file,
            execution_file,
            universe_file,
            identity_file,
            [f"input_load_failed:{exc}"],
        )

    failures: list[str] = []
    warnings: list[str] = []
    if manifest.get("schema") != "daily_collect_v1":
        failures.append("manifest_schema_mismatch")
    if int(manifest.get("error_count", -1)) != 0:
        failures.append("manifest_error_count_nonzero")
    manifest_params = manifest.get("params") if isinstance(manifest.get("params"), dict) else {}
    if set(manifest_params.get("exchanges") or []) != {"mexc", "gateio"}:
        failures.append("manifest_exchange_set_mismatch")
    if not _same_path(manifest_params.get("universe_csv"), universe_file):
        failures.append("manifest_universe_path_mismatch")

    if pairs_payload.get("schema") != "funding_pairs_v2":
        failures.append("pairs_schema_mismatch")
    if _portable_name(pairs_payload.get("dataset")) != manifest_file.parent.name:
        failures.append("pairs_dataset_run_id_mismatch")
    pairs = pairs_payload.get("pairs") if isinstance(pairs_payload.get("pairs"), list) else []
    if int(pairs_payload.get("pairs_analyzed", -1)) != len(pairs):
        failures.append("pairs_analyzed_count_mismatch")

    if execution.get("schema") != "execution_gate_v2":
        failures.append("execution_schema_mismatch")
    if _portable_name(execution.get("pairs_source")) != pairs_file.name:
        failures.append("execution_pairs_source_mismatch")
    execution_params = execution.get("params") if isinstance(execution.get("params"), dict) else {}
    if execution_params.get("auto_candidates") is not True:
        failures.append("execution_auto_candidates_not_true")
    execution_candidates = execution.get("candidates") if isinstance(execution.get("candidates"), list) else []

    expected_symbols, e_selected, g_selected = _expected_candidates(pairs)
    observed_symbols = [str(item.get("symbol") or "") for item in execution_candidates if isinstance(item, dict)]
    if observed_symbols != expected_symbols:
        failures.append("execution_candidate_selection_mismatch")

    registry, registry_summary = _load_registry(universe_file)
    evidence_assets = _identity_assets(identity_payload, failures)
    pairs_by_symbol = {
        str(pair.get("symbol") or ""): pair
        for pair in pairs
        if isinstance(pair, dict) and pair.get("symbol")
    }

    depth_share = float(execution_params.get("depth_share_cap") or 0.2)
    volume_share = float(execution_params.get("daily_volume_cap") or 0.005)
    turnover = float(execution_params.get("turnover_per_year") or 12.0)
    candidate_audits: list[dict[str, Any]] = []
    for candidate in execution_candidates:
        if not isinstance(candidate, dict):
            failures.append("execution_candidate_not_object")
            continue
        symbol = str(candidate.get("symbol") or "")
        base = symbol.removesuffix("_USDT")
        pair = pairs_by_symbol.get(symbol)
        if pair is None:
            failures.append(f"candidate_pair_missing:{symbol}")
            pair = {}
        identity = _candidate_identity(base, registry, evidence_assets, failures, warnings)
        errors = candidate.get("errors") if isinstance(candidate.get("errors"), list) else []
        if errors:
            failures.append(f"candidate[{symbol}].book_errors_present")

        books = candidate.get("books") if isinstance(candidate.get("books"), dict) else {}
        volume = float(pair.get("min_volume_24h_quote") or 0.0)
        spot_cap = _position_capacity(books.get("mexc_spot"), volume, depth_share, volume_share)
        mexc_cap = _position_capacity(books.get("mexc_perp"), volume, depth_share, volume_share)
        gate_cap = _position_capacity(books.get("gate_perp"), volume, depth_share, volume_share)
        expected_e_capacity = min(spot_cap, mexc_cap)
        expected_g_capacity = min(mexc_cap, gate_cap)

        e_part = candidate.get("e_construction_short_mexc_perp_long_mexc_spot")
        g_part = candidate.get("g_construction_perp_perp")
        if isinstance(e_part, dict):
            failures.extend(_route_math_failures(e_part, f"candidate[{symbol}].e", turnover, expected_e_capacity))
            pair_leg = (pair.get("leg_annualized_pct") or {}).get("mexc")
            if not _close(e_part.get("leg_annual_pct"), pair_leg):
                failures.append(f"candidate[{symbol}].e_leg_source_mismatch")
        elif symbol in e_selected:
            failures.append(f"candidate[{symbol}].e_route_missing")
        if isinstance(g_part, dict):
            failures.extend(_route_math_failures(g_part, f"candidate[{symbol}].g", turnover, expected_g_capacity))
            spread = pair.get("spread_gate_minus_mexc") if isinstance(pair.get("spread_gate_minus_mexc"), dict) else {}
            if not _close(g_part.get("spread_annual_pct"), spread.get("annualized_spread_pct")):
                failures.append(f"candidate[{symbol}].g_spread_source_mismatch")
            if not _close(g_part.get("sign_consistency"), spread.get("sign_consistency"), 0.0011):
                failures.append(f"candidate[{symbol}].g_consistency_source_mismatch")
        elif symbol in g_selected:
            failures.append(f"candidate[{symbol}].g_route_missing")

        def _mid(name: str) -> float | None:
            book = books.get(name)
            try:
                return float(book.get("mid")) if isinstance(book, dict) else None
            except (TypeError, ValueError):
                return None

        spot_mid = _mid("mexc_spot")
        mexc_mid = _mid("mexc_perp")
        gate_mid = _mid("gate_perp")
        current_cross_basis = None
        current_spot_basis = None
        if mexc_mid and gate_mid:
            current_cross_basis = round((gate_mid / mexc_mid - 1.0) * 10000.0, 4)
        if mexc_mid and spot_mid:
            current_spot_basis = round((spot_mid / mexc_mid - 1.0) * 100.0, 4)

        candidate_audits.append(
            {
                "symbol": symbol,
                "base": base,
                "selected_by": {
                    "e_current_leg_watchlist_rule": symbol in e_selected,
                    "g_historical_spread_watchlist_rule": symbol in g_selected,
                },
                "identity": identity,
                "snapshot_diagnostics": {
                    "current_gate_vs_mexc_perp_basis_bps": current_cross_basis,
                    "current_mexc_spot_vs_perp_basis_pct": current_spot_basis,
                    "capacity_recomputed_usd": {
                        "e_same_venue_spot_perp": expected_e_capacity,
                        "g_cross_venue_perp_perp": expected_g_capacity,
                    },
                    "book_errors": errors,
                },
                "model_economics": {
                    "e": e_part if isinstance(e_part, dict) else None,
                    "g": g_part if isinstance(g_part, dict) else None,
                    "interpretation": "modeled_annualized_screen_not_realized_return_or_pnl",
                },
            }
        )

    pairs_params = pairs_payload.get("params") if isinstance(pairs_payload.get("params"), dict) else {}
    collection_days = int(manifest_params.get("days") or 0)
    analysis_days = int(pairs_params.get("window_days") or 0)
    aligned_days = [
        int((pair.get("spread_gate_minus_mexc") or {}).get("aligned_days") or 0)
        for pair in pairs
        if isinstance(pair, dict)
    ]
    max_aligned = max(aligned_days, default=0)
    if analysis_days <= 0 or collection_days <= 0:
        failures.append("window_days_invalid")
    if analysis_days > 0 and any(value > analysis_days + 1 for value in aligned_days):
        failures.append("aligned_days_exceed_inclusive_window")

    inputs = {label: _input_ref(path) for label, path in required.items()}
    window_contract = {
        "collection_days": collection_days,
        "analysis_window_days": analysis_days,
        "inclusive_calendar_days_expected_max": analysis_days + 1 if analysis_days else 0,
        "inclusive_calendar_days_observed": max_aligned,
        "aligned_days_min": min(aligned_days, default=0),
        "note": "The historical filter is inclusive at both date boundaries; window_days=90 can contain 91 calendar dates.",
    }
    universe_contract = {
        "path": str(universe_file),
        "sha256": inputs["universe"]["sha256"],
        **registry_summary,
        "selection": "current_top_24h_volume_then_historical_backfill",
        "point_in_time": False,
        "survivorship_bias_controlled": False,
        "universe_changed_by_audit": False,
    }
    selection_contract = {
        "expected_symbols": expected_symbols,
        "observed_symbols": observed_symbols,
        "rules": {
            "e": {"max": AUTO_MAX_E, "min_mexc_leg_annual_pct": AUTO_MIN_LEG_PCT, "mexc_spot_required": True},
            "g": {
                "max": AUTO_MAX_G,
                "min_abs_annual_spread_pct": AUTO_MIN_SPREAD_PCT,
                "min_sign_consistency": AUTO_MIN_CONSISTENCY,
            },
        },
        "selection_changed_by_audit": False,
    }
    proof_gates = {
        "chronological_oos": "not_run",
        "walk_forward": "not_run",
        "stress": "not_run",
        "realized_returns_or_pnl": "not_computed",
    }
    decision = WATCHLIST_ONLY if not failures else INVALID_EVIDENCE
    stable = {
        "input_hashes": {label: value["sha256"] for label, value in inputs.items()},
        "decision": decision,
        "acceptance_allowed": False,
        "failures": failures,
        "warnings": warnings,
        "window_contract": window_contract,
        "universe_contract": universe_contract,
        "candidate_selection_contract": selection_contract,
        "candidates": candidate_audits,
        "proof_gates": proof_gates,
    }
    return {
        "schema": "funding_forward_audit_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": not failures,
        "decision": decision,
        "acceptance_allowed": False,
        "research_only": True,
        "inputs": inputs,
        "window_contract": window_contract,
        "universe_contract": universe_contract,
        "candidate_selection_contract": selection_contract,
        "execution_snapshot_contract": {
            "one_time_snapshot": True,
            "time_average": False,
            "cost_model": "modeled_screen_only",
            "returns_or_pnl": False,
            "source_caveat": execution.get("caveat"),
        },
        "candidates": candidate_audits,
        "proof_gates": proof_gates,
        "caveats": [
            "Current-volume universe followed by historical backfill is not point-in-time and can contain survivorship bias.",
            "Ticker equality is not asset identity; only explicitly validated same-contract evidence is marked verified.",
            "Order-book capacity is one snapshot, not time-averaged executable capacity.",
            "Annualized funding minus modeled turnover costs is not realized expectancy, return, or PnL.",
            "This audit cannot ACCEPT an edge before chronological OOS, walk-forward, and stress gates.",
        ],
        "failures": failures,
        "warnings": warnings,
        "deterministic_result_hash": _canonical_hash(stable),
    }


def run_funding_forward_audit(
    manifest_path: str | Path,
    pairs_path: str | Path,
    execution_path: str | Path,
    universe_path: str | Path,
    output_path: str | Path,
    *,
    identity_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    output = Path(output_path)
    result = build_funding_forward_audit(
        manifest_path,
        pairs_path,
        execution_path,
        universe_path,
        identity_evidence_path=identity_evidence_path,
    )
    result["output_path"] = str(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = argparse.ArgumentParser(description="Deterministic offline audit for funding-forward watchlist artifacts")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--pairs-json", required=True)
    parser.add_argument("--execution-json", required=True)
    parser.add_argument("--universe-csv", required=True)
    parser.add_argument("--identity-evidence", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = run_funding_forward_audit(
        args.manifest,
        args.pairs_json,
        args.execution_json,
        args.universe_csv,
        args.out,
        identity_evidence_path=args.identity_evidence,
    )
    print(
        f"AUDIT decision={result['decision']} passed={str(result['audit_passed']).lower()} "
        f"acceptance_allowed=false hash={result['deterministic_result_hash']} out={args.out}"
    )
    return 0 if result["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
