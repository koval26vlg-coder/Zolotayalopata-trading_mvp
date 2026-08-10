from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DECISION_FEASIBLE = "CURRENT_CACHE_FIXED_HOLD_PRE_OOS_FEASIBLE"
DECISION_INSUFFICIENT = "CURRENT_CACHE_FIXED_HOLD_STRESS_INSUFFICIENT"


class AuditInputError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditInputError(f"{label} could not be loaded: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditInputError(f"{label} must be a JSON object")
    return value


def _verify_file_hash(path: Path, expected_sha256: str, label: str) -> str:
    expected = str(expected_sha256 or "").lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise AuditInputError(f"{label} expected SHA-256 is invalid")
    if not path.is_file():
        raise AuditInputError(f"{label} is missing: {path}")
    observed = _sha256(path)
    if observed != expected:
        raise AuditInputError(
            f"{label} SHA-256 mismatch: expected {expected}, observed {observed}"
        )
    return observed


def _verify_embedded_hash(
    payload: dict[str, Any],
    *,
    field: str,
    label: str,
) -> str:
    expected = str(payload.get(field) or "").lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise AuditInputError(f"{label} {field} is missing or invalid")
    canonical = dict(payload)
    canonical.pop(field, None)
    observed = _canonical_hash(canonical)
    if observed != expected:
        raise AuditInputError(
            f"{label} {field} mismatch: expected {expected}, observed {observed}"
        )
    return observed


def _require_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditInputError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise AuditInputError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise AuditInputError(f"{label} must be >= {minimum}")
    return result


def _require_positive_int(value: Any, label: str) -> int:
    number = _require_number(value, label, minimum=1.0)
    result = int(number)
    if result != number:
        raise AuditInputError(f"{label} must be an integer")
    return result


def _parse_utc(value: Any, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise AuditInputError(f"{label} is missing")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise AuditInputError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AuditInputError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _round_bps(value: float) -> float:
    return round(value, 6)


def _read_pairs(pair_summary: dict[str, Any]) -> list[dict[str, Any]]:
    pairs = pair_summary.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise AuditInputError("pair summary pairs must be a non-empty array")

    observed_bases: set[str] = set()
    observed_symbols: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise AuditInputError(f"pair summary pair {index} must be an object")
        base = str(pair.get("base") or "").strip()
        symbol = str(pair.get("symbol") or "").strip()
        if not base or not symbol:
            raise AuditInputError(f"pair summary pair {index} is missing base or symbol")
        if base in observed_bases:
            raise AuditInputError(f"duplicate pair summary base: {base}")
        if symbol in observed_symbols:
            raise AuditInputError(f"duplicate pair summary symbol: {symbol}")
        spread = pair.get("spread_gate_minus_mexc")
        if not isinstance(spread, dict):
            raise AuditInputError(f"pair {symbol} spread_gate_minus_mexc is missing")
        daily = _require_number(
            spread.get("mean_daily_spread_bps"),
            f"pair {symbol} mean_daily_spread_bps",
        )
        if daily == 0.0:
            raise AuditInputError(f"pair {symbol} mean_daily_spread_bps must be non-zero")
        observed_bases.add(base)
        observed_symbols.add(symbol)
        result.append(
            {
                "base": base,
                "symbol": symbol,
                "absolute_daily_funding_spread_bps": abs(daily),
            }
        )
    return result


def _verify_dataset_binding(
    pair_summary: dict[str, Any],
    pair_file: Path,
    manifest_file: Path,
) -> Path:
    raw_dataset = str(pair_summary.get("dataset") or "").strip()
    if not raw_dataset:
        raise AuditInputError("pair summary dataset is missing")
    dataset = Path(raw_dataset)
    candidates = [dataset] if dataset.is_absolute() else [
        Path.cwd() / dataset,
        pair_file.parent / dataset,
    ]
    expected = manifest_file.parent.resolve()
    resolved_candidates = [candidate.resolve() for candidate in candidates]
    if expected not in resolved_candidates:
        raise AuditInputError(
            "pair summary dataset does not match manifest parent: "
            f"expected {expected}, observed {raw_dataset}"
        )
    return expected


def build_audit(
    *,
    pair_summary_path: str | Path,
    expected_pair_summary_sha256: str,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    cost_contract_proposal_path: str | Path,
    expected_cost_contract_proposal_sha256: str,
    universe_policy_path: str | Path,
    expected_universe_policy_sha256: str,
) -> dict[str, Any]:
    pair_file = Path(pair_summary_path).resolve()
    manifest_file = Path(manifest_path).resolve()
    proposal_file = Path(cost_contract_proposal_path).resolve()
    policy_file = Path(universe_policy_path).resolve()

    pair_sha = _verify_file_hash(
        pair_file, expected_pair_summary_sha256, "pair summary"
    )
    manifest_sha = _verify_file_hash(manifest_file, expected_manifest_sha256, "manifest")
    proposal_sha = _verify_file_hash(
        proposal_file,
        expected_cost_contract_proposal_sha256,
        "cost contract proposal",
    )
    policy_sha = _verify_file_hash(
        policy_file,
        expected_universe_policy_sha256,
        "universe policy",
    )

    pair_summary = _load_json(pair_file, "pair summary")
    manifest = _load_json(manifest_file, "manifest")
    proposal = _load_json(proposal_file, "cost contract proposal")
    policy = _load_json(policy_file, "universe policy")

    proposal_hash = _verify_embedded_hash(
        proposal, field="proposal_hash", label="cost contract proposal"
    )
    policy_hash = _verify_embedded_hash(
        policy, field="policy_hash", label="universe policy"
    )

    if pair_summary.get("schema") != "funding_pairs_v2":
        raise AuditInputError("pair summary schema must be funding_pairs_v2")
    dataset_path = _verify_dataset_binding(pair_summary, pair_file, manifest_file)
    pair_params = pair_summary.get("params")
    if not isinstance(pair_params, dict):
        raise AuditInputError("pair summary params are missing")
    if pair_params.get("non_binance_only") is not False:
        raise AuditInputError("pair summary must include every cached asset")
    if pair_params.get("analysis_as_of_source") != "manifest.params.end_sec":
        raise AuditInputError("pair summary cutoff must come from manifest.params.end_sec")

    manifest_params = manifest.get("params")
    if not isinstance(manifest_params, dict):
        raise AuditInputError("manifest params are missing")
    manifest_end_sec = _require_number(
        manifest_params.get("end_sec"), "manifest params.end_sec", minimum=1.0
    )
    pair_as_of_sec = _require_number(
        pair_params.get("analysis_as_of_ts"),
        "pair summary analysis_as_of_ts",
        minimum=1.0,
    )
    if pair_as_of_sec != manifest_end_sec:
        raise AuditInputError(
            "pair summary analysis_as_of_ts does not match manifest.params.end_sec"
        )

    if policy.get("scope") != "FUNDING_STRATEGIES_ONLY":
        raise AuditInputError("universe policy scope must be FUNDING_STRATEGIES_ONLY")
    asset_universe = policy.get("asset_universe")
    if not isinstance(asset_universe, dict):
        raise AuditInputError("universe policy asset_universe is missing")
    if asset_universe.get("mode") != "ALL_ASSETS_WITHOUT_CATEGORY_EXCLUSIONS":
        raise AuditInputError("universe policy does not allow all asset categories")
    if policy.get("current_venue_scope") != ["mexc", "gateio"]:
        raise AuditInputError("universe policy venue scope must be exactly mexc and gateio")

    chronological_oos = proposal.get("chronological_oos")
    economics = proposal.get("economics_contract")
    validation = proposal.get("validation_contract")
    if not isinstance(chronological_oos, dict):
        raise AuditInputError("cost contract chronological_oos is missing")
    if not isinstance(economics, dict):
        raise AuditInputError("cost contract economics_contract is missing")
    if not isinstance(validation, dict):
        raise AuditInputError("cost contract validation_contract is missing")

    cutoff = _parse_utc(
        chronological_oos.get("pre_oos_cutoff_utc"), "pre-OOS cutoff"
    )
    pair_as_of = datetime.fromtimestamp(pair_as_of_sec, timezone.utc)
    if pair_as_of > cutoff:
        raise AuditInputError("pair summary cutoff is later than the pre-OOS cutoff")

    oos_days = _require_positive_int(
        chronological_oos.get("complete_utc_days"), "OOS complete UTC days"
    )
    normal_cost = _require_number(
        economics.get("normal_cycle_cost_bps_per_asset_fold"),
        "normal cycle cost",
        minimum=0.0,
    )
    stress_cost = _require_number(
        economics.get("stress_cycle_cost_bps_per_asset_fold"),
        "stress cycle cost",
        minimum=0.0,
    )
    stress_haircut = _require_number(
        economics.get("stress_favorable_funding_haircut"),
        "stress favorable funding haircut",
        minimum=0.0,
    )
    if stress_haircut <= 0.0 or stress_haircut > 1.0:
        raise AuditInputError("stress favorable funding haircut must be in (0, 1]")
    pre_oos_gates = validation.get("pre_oos_gates")
    if not isinstance(pre_oos_gates, dict):
        raise AuditInputError("validation pre_oos_gates is missing")
    minimum_assets = _require_positive_int(
        pre_oos_gates.get("minimum_verified_source_complete_assets"),
        "minimum verified source-complete assets",
    )

    pairs = _read_pairs(pair_summary)
    if minimum_assets > len(pairs):
        raise AuditInputError("minimum asset gate exceeds analyzed pair count")

    candidates: list[dict[str, Any]] = []
    normal_positive = 0
    stress_positive = 0
    for pair in pairs:
        daily = pair["absolute_daily_funding_spread_bps"]
        normal_gross = daily * oos_days
        stress_gross = normal_gross * stress_haircut
        normal_net_upper_bound = normal_gross - normal_cost
        stress_net_upper_bound = stress_gross - stress_cost
        normal_positive += normal_net_upper_bound > 0.0
        stress_positive += stress_net_upper_bound > 0.0
        normal_break_even = math.ceil(normal_cost / daily) if normal_cost else 0
        stress_break_even = (
            math.ceil(stress_cost / (daily * stress_haircut)) if stress_cost else 0
        )
        candidates.append(
            {
                **pair,
                "oos_horizon_days": oos_days,
                "normal_gross_upper_bound_bps": _round_bps(normal_gross),
                "normal_net_upper_bound_bps": _round_bps(normal_net_upper_bound),
                "stress_gross_upper_bound_bps": _round_bps(stress_gross),
                "stress_net_upper_bound_bps": _round_bps(stress_net_upper_bound),
                "normal_break_even_days": normal_break_even,
                "stress_break_even_days": stress_break_even,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["stress_break_even_days"],
            -item["absolute_daily_funding_spread_bps"],
            item["symbol"],
        )
    )
    minimum_horizon = sorted(
        item["stress_break_even_days"] for item in candidates
    )[minimum_assets - 1]

    feasible = stress_positive >= minimum_assets
    decision = DECISION_FEASIBLE if feasible else DECISION_INSUFFICIENT
    blocking_reasons = []
    if not feasible:
        blocking_reasons = [
            "fewer than the required cached assets cover stress costs at the frozen OOS horizon",
            "the cached universe is not proven to contain every MEXC/Gate funding asset",
            "official same-underlying identity checks are deferred until economics can pass",
        ]

    result_core = {
        "pair_summary_sha256": pair_sha,
        "dataset_path": str(dataset_path),
        "manifest_sha256": manifest_sha,
        "cost_contract_proposal_sha256": proposal_sha,
        "cost_contract_proposal_hash": proposal_hash,
        "universe_policy_sha256": policy_sha,
        "universe_policy_hash": policy_hash,
        "pair_summary_analysis_as_of_utc": pair_as_of.isoformat(),
        "pre_oos_cutoff_utc": cutoff.isoformat(),
        "cached_assets_analyzed": len(candidates),
        "oos_horizon_days": oos_days,
        "minimum_assets_required": minimum_assets,
        "normal_cycle_cost_bps": normal_cost,
        "stress_cycle_cost_bps": stress_cost,
        "stress_favorable_funding_haircut": stress_haircut,
        "normal_positive_at_oos_horizon": normal_positive,
        "stress_positive_at_oos_horizon": stress_positive,
        "minimum_horizon_days_for_required_assets": minimum_horizon,
        "candidate_upper_bounds": candidates,
        "decision": decision,
        "fixed_hold_planonly_allowed_from_current_cache": feasible,
        "complete_unrestricted_universe_or_longer_oos_required": not feasible,
        "blocking_reasons": blocking_reasons,
    }
    return {
        "schema": "trading_mvp_funding_unrestricted_cache_feasibility_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": True,
        **result_core,
        "deterministic_result_hash": _canonical_hash(result_core),
        "data_access_audit": {
            "pair_summary_read": True,
            "manifest_read": True,
            "universe_policy_read": True,
            "cost_contract_read": True,
            "raw_market_rows_read": False,
            "oos_values_read": False,
            "returns_or_pnl_computed": False,
            "network_market_data_accessed": False,
            "collector_run": False,
            "evaluator_run": False,
            "grid_or_retune_run": False,
        },
        "safety": {
            "planonly_only": True,
            "collector_launch_authorized": False,
            "oos_evaluation_authorized": False,
            "paper_or_live_authorized": False,
            "private_api_used": False,
            "real_capital_used": False,
            "leverage_or_margin_used": False,
        },
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a cached unrestricted funding universe without reading OOS rows."
    )
    parser.add_argument("--pair-summary", required=True)
    parser.add_argument("--expected-pair-summary-sha256", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--cost-contract-proposal", required=True)
    parser.add_argument("--expected-cost-contract-proposal-sha256", required=True)
    parser.add_argument("--universe-policy", required=True)
    parser.add_argument("--expected-universe-policy-sha256", required=True)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.out).resolve()
    try:
        audit = build_audit(
            pair_summary_path=args.pair_summary,
            expected_pair_summary_sha256=args.expected_pair_summary_sha256,
            manifest_path=args.manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
            cost_contract_proposal_path=args.cost_contract_proposal,
            expected_cost_contract_proposal_sha256=(
                args.expected_cost_contract_proposal_sha256
            ),
            universe_policy_path=args.universe_policy,
            expected_universe_policy_sha256=args.expected_universe_policy_sha256,
        )
        _write_json_atomic(output, audit)
    except AuditInputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "audit_passed": audit["audit_passed"],
                "decision": audit["decision"],
                "stress_positive_at_oos_horizon": audit[
                    "stress_positive_at_oos_horizon"
                ],
                "minimum_assets_required": audit["minimum_assets_required"],
                "out": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
