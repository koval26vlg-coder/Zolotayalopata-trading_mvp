from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REJECT_ECONOMICS = "REJECT_PROPOSAL_PREIMPLEMENTATION_ECONOMICS_MISMATCH"
PRICE_ALPHA_REVIEW = "MATERIAL_PRICE_ALPHA_REQUIRES_SEPARATE_CONTRACT_REVIEW"
ECONOMICS_NOT_BLOCKING = "PRE_OOS_ECONOMICS_NOT_BLOCKING"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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


def _resolve_reference(reference: str, proposal_path: Path) -> Path:
    candidate = Path(reference)
    if candidate.is_absolute():
        return candidate

    candidates = [Path.cwd() / candidate, proposal_path.parent / candidate]
    for parent in proposal_path.parents:
        candidates.append(parent / candidate)
    for resolved in candidates:
        if resolved.is_file():
            return resolved.resolve()
    return candidates[0].resolve()


def _verify_proposal_hash(proposal: dict[str, Any]) -> str:
    expected = str(proposal.get("proposal_hash") or "").lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise AuditInputError("proposal_hash is missing or invalid")
    canonical = dict(proposal)
    canonical.pop("proposal_hash", None)
    observed = _canonical_hash(canonical)
    if observed != expected:
        raise AuditInputError(
            f"proposal_hash mismatch: expected {expected}, observed {observed}"
        )
    return observed


def _candidate_symbol(candidate: dict[str, Any]) -> str:
    symbol = str(candidate.get("symbol") or candidate.get("base") or "").strip()
    if not symbol:
        raise AuditInputError("candidate symbol is missing")
    return symbol


def _daily_spread_map(pair_summary: dict[str, Any]) -> dict[str, float]:
    pairs = pair_summary.get("pairs")
    if not isinstance(pairs, list):
        raise AuditInputError("pair summary pairs must be an array")

    result: dict[str, float] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        base = str(pair.get("base") or "").strip()
        if not base:
            instrument = str(pair.get("symbol") or "").strip()
            base = instrument.removesuffix("_USDT")
        spread = pair.get("spread_gate_minus_mexc")
        if not base or not isinstance(spread, dict):
            continue
        daily = _require_number(
            spread.get("mean_daily_spread_bps"),
            f"pair {base} mean_daily_spread_bps",
        )
        if daily == 0.0:
            raise AuditInputError(f"pair {base} mean_daily_spread_bps must be non-zero")
        if base in result:
            raise AuditInputError(f"duplicate pair summary base: {base}")
        result[base] = abs(daily)
    return result


def _round_bps(value: float) -> float:
    return round(value, 6)


def build_audit(
    *,
    proposal_path: str | Path,
    expected_proposal_file_sha256: str,
) -> dict[str, Any]:
    proposal_file = Path(proposal_path).resolve()
    proposal_file_sha256 = _verify_file_hash(
        proposal_file,
        expected_proposal_file_sha256,
        "proposal file",
    )
    proposal = _load_json(proposal_file, "proposal")
    proposal_hash = _verify_proposal_hash(proposal)

    freeze = proposal.get("pre_oos_candidate_freeze")
    if not isinstance(freeze, dict):
        raise AuditInputError("pre_oos_candidate_freeze is missing")
    pair_ref = freeze.get("pair_summary")
    if not isinstance(pair_ref, dict):
        raise AuditInputError("pre_oos pair summary reference is missing")
    pair_path = _resolve_reference(str(pair_ref.get("path") or ""), proposal_file)
    pair_file_sha256 = _verify_file_hash(
        pair_path,
        str(pair_ref.get("sha256") or ""),
        "pre-OOS pair summary",
    )
    pair_summary = _load_json(pair_path, "pre-OOS pair summary")
    spread_by_symbol = _daily_spread_map(pair_summary)

    candidates_raw = freeze.get("candidates")
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise AuditInputError("pre-OOS candidates must be a non-empty array")
    candidates: list[str] = []
    for candidate in candidates_raw:
        if not isinstance(candidate, dict):
            raise AuditInputError("each pre-OOS candidate must be an object")
        symbol = _candidate_symbol(candidate)
        if symbol in candidates:
            raise AuditInputError(f"duplicate pre-OOS candidate: {symbol}")
        if symbol not in spread_by_symbol:
            raise AuditInputError(f"pre-OOS spread is missing for candidate: {symbol}")
        candidates.append(symbol)

    strategy = proposal.get("strategy_contract")
    economics = proposal.get("economics_contract")
    validation = proposal.get("validation_contract")
    chronological_oos = proposal.get("chronological_oos")
    if not isinstance(strategy, dict):
        raise AuditInputError("strategy_contract is missing")
    if not isinstance(economics, dict):
        raise AuditInputError("economics_contract is missing")
    if not isinstance(validation, dict):
        raise AuditInputError("validation_contract is missing")
    if not isinstance(chronological_oos, dict):
        raise AuditInputError("chronological_oos is missing")

    hold_days = _require_positive_int(
        strategy.get("holding_period_complete_utc_days"),
        "holding period days",
    )
    oos_days = _require_positive_int(
        chronological_oos.get("complete_utc_days"),
        "OOS complete days",
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
    if minimum_assets > len(candidates):
        raise AuditInputError("minimum asset gate exceeds frozen candidate count")

    candidate_economics: list[dict[str, Any]] = []
    normal_positive_count = 0
    stress_positive_count = 0
    for symbol in candidates:
        daily = spread_by_symbol[symbol]
        hold_gross = daily * hold_days
        stress_gross = hold_gross * stress_haircut
        normal_net = hold_gross - normal_cost
        stress_net = stress_gross - stress_cost
        normal_positive_count += normal_net > 0.0
        stress_positive_count += stress_net > 0.0
        normal_break_even_days = math.ceil(normal_cost / daily) if normal_cost else 0
        stress_break_even_days = (
            math.ceil(stress_cost / (daily * stress_haircut)) if stress_cost else 0
        )
        candidate_economics.append(
            {
                "symbol": symbol,
                "pre_oos_daily_abs_funding_spread_bps": _round_bps(daily),
                "proposed_hold_days": hold_days,
                "hold_gross_funding_bps": _round_bps(hold_gross),
                "normal_cycle_cost_bps": _round_bps(normal_cost),
                "normal_net_bps": _round_bps(normal_net),
                "stress_favorable_funding_haircut": stress_haircut,
                "stress_gross_funding_bps": _round_bps(stress_gross),
                "stress_cycle_cost_bps": _round_bps(stress_cost),
                "stress_net_bps": _round_bps(stress_net),
                "normal_break_even_days": normal_break_even_days,
                "stress_break_even_days": stress_break_even_days,
            }
        )

    stress_break_even_within_oos_count = sum(
        item["stress_break_even_days"] <= oos_days for item in candidate_economics
    )

    explicit_price_alpha = bool(
        str(strategy.get("basis_entry_condition") or "").strip()
        and str(strategy.get("basis_exit_condition") or "").strip()
    )
    economics_passed = (
        normal_positive_count >= minimum_assets
        and stress_positive_count >= minimum_assets
    )
    if economics_passed:
        decision = ECONOMICS_NOT_BLOCKING
        approval_consumable = True
        implementation_allowed = True
        blocking_reasons: list[str] = []
    elif explicit_price_alpha:
        decision = PRICE_ALPHA_REVIEW
        approval_consumable = False
        implementation_allowed = False
        blocking_reasons = [
            "funding carry alone does not cover frozen costs at the proposed hold",
            "an explicit price-alpha contract exists and requires separate review",
        ]
    else:
        decision = REJECT_ECONOMICS
        approval_consumable = False
        implementation_allowed = False
        blocking_reasons = [
            "fewer than the required candidates cover normal costs at the proposed hold",
            "fewer than the required candidates cover stress costs at the proposed hold",
            "no basis entry/exit alpha contract is declared to justify a price component",
        ]

    result_core = {
        "proposal_hash": proposal_hash,
        "proposal_file_sha256": proposal_file_sha256,
        "pair_summary_sha256": pair_file_sha256,
        "hold_days": hold_days,
        "oos_complete_days": oos_days,
        "minimum_assets_required": minimum_assets,
        "normal_cycle_cost_bps": normal_cost,
        "stress_cycle_cost_bps": stress_cost,
        "stress_favorable_funding_haircut": stress_haircut,
        "explicit_price_alpha_contract": explicit_price_alpha,
        "normal_positive_candidate_count": normal_positive_count,
        "stress_positive_candidate_count": stress_positive_count,
        "stress_break_even_within_oos_count": stress_break_even_within_oos_count,
        "candidate_economics": candidate_economics,
        "decision": decision,
        "proposal_approval_consumable": approval_consumable,
        "planonly_implementation_allowed": implementation_allowed,
        "oos_evaluation_allowed": False,
        "blocking_reasons": blocking_reasons,
    }
    return {
        "schema": "funding_daily_hold_proposal_audit_v1",
        "created_at_utc": _utc_now(),
        "audit_passed": True,
        "decision": decision,
        "proposal": {
            "path": str(proposal_file),
            "file_sha256": proposal_file_sha256,
            "proposal_hash": proposal_hash,
        },
        "pre_oos_pair_summary": {
            "path": str(pair_path),
            "file_sha256": pair_file_sha256,
        },
        "minimum_assets_required": minimum_assets,
        "normal_positive_candidate_count": normal_positive_count,
        "stress_positive_candidate_count": stress_positive_count,
        "stress_break_even_within_oos_count": stress_break_even_within_oos_count,
        "explicit_price_alpha_contract": explicit_price_alpha,
        "candidate_economics": candidate_economics,
        "blocking_reasons": blocking_reasons,
        "proposal_approval_consumable": approval_consumable,
        "planonly_implementation_allowed": implementation_allowed,
        "oos_evaluation_allowed": False,
        "next_allowed_action": (
            "BUILD_HASH_BOUND_PLANONLY_WITHOUT_OOS_EXECUTION"
            if implementation_allowed
            else "SUPERSEDE_PROPOSAL_WITH_CORRECTED_PRE_OOS_CONTRACT"
        ),
        "data_access_audit": {
            "pre_oos_summary_read": True,
            "oos_market_rows_read": False,
            "oos_funding_rates_read": False,
            "oos_prices_read": False,
            "returns_or_pnl_computed": False,
            "evaluator_run": False,
            "collector_run": False,
            "network_access": False,
            "grid_or_retune": False,
        },
        "safety": {
            "approval_consumed": False,
            "planonly_built": False,
            "runtime_manifest_built": False,
            "oos_run": False,
            "execution_probe": False,
            "paper_or_live": False,
            "private_api_keys": False,
            "real_capital": False,
            "leverage_or_margin": False,
        },
        "deterministic_result_hash": _canonical_hash(result_core),
    }


def run_audit(
    *,
    proposal_path: str | Path,
    expected_proposal_file_sha256: str,
    output_path: str | Path,
) -> dict[str, Any]:
    result = build_audit(
        proposal_path=proposal_path,
        expected_proposal_file_sha256=expected_proposal_file_sha256,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(
        description="Audit daily funding-hold proposal economics using pre-OOS summaries only"
    )
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--expected-proposal-file-sha256", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        result = run_audit(
            proposal_path=args.proposal,
            expected_proposal_file_sha256=args.expected_proposal_file_sha256,
            output_path=args.out,
        )
    except AuditInputError as exc:
        print(f"FUNDING_DAILY_HOLD_PROPOSAL_AUDIT_ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"FUNDING_DAILY_HOLD_PROPOSAL_AUDIT decision={result['decision']} "
        f"approval_consumable={str(result['proposal_approval_consumable']).lower()} "
        f"hash={result['deterministic_result_hash']} out={args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
