from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from historical_basis_v2 import sha256_json


SNAPSHOT_SCHEMA = "trading_mvp_paper_reconciliation_fixture_snapshot_v1"
REPORT_SCHEMA = "trading_mvp_paper_reconciliation_report_v1"
ALLOWED_VENUES = {"mexc", "gateio"}


class ReadOnlyReconciliationProvider(Protocol):
    provider_id: str
    read_only: bool

    def read_snapshot(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class ReconciliationContract:
    notional_quote_per_leg: float
    notional_tolerance_quote: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.notional_quote_per_leg) or self.notional_quote_per_leg <= 0:
            raise ValueError("notional_quote_per_leg must be finite and positive")
        if (
            not math.isfinite(self.notional_tolerance_quote)
            or self.notional_tolerance_quote < 0
        ):
            raise ValueError("notional_tolerance_quote must be finite and non-negative")


class DeterministicFixtureReconciliationAdapter:
    provider_id = "deterministic_fixture"
    read_only = True

    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        normalized = _validate_snapshot(snapshot)
        self._snapshot = deepcopy(normalized)
        self._snapshot_hash = sha256_json(self._snapshot)

    def __repr__(self) -> str:
        return (
            "DeterministicFixtureReconciliationAdapter("
            f"snapshot_hash='{self._snapshot_hash[:12]}...', read_only=True)"
        )

    def read_snapshot(self) -> dict[str, Any]:
        return deepcopy(self._snapshot)


def _finite_non_negative(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return number


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"expected {SNAPSHOT_SCHEMA}")
    observed_ts = int(snapshot.get("observed_ts") or 0)
    if observed_ts <= 0:
        raise ValueError("reconciliation snapshot observed_ts must be positive")
    balances = snapshot.get("balances")
    positions = snapshot.get("positions")
    open_orders = snapshot.get("open_orders")
    if not isinstance(balances, Mapping):
        raise ValueError("reconciliation balances are missing")
    if not isinstance(positions, list) or not isinstance(open_orders, list):
        raise ValueError("reconciliation positions or open_orders are missing")
    normalized_balances: dict[str, dict[str, float]] = {}
    for venue, assets in balances.items():
        venue_name = str(venue).strip().lower()
        if venue_name not in ALLOWED_VENUES or not isinstance(assets, Mapping):
            raise ValueError("reconciliation balance venue is invalid")
        normalized_balances[venue_name] = {
            str(asset).strip().upper(): _finite_non_negative(
                value,
                field=f"balances.{venue_name}.{asset}",
            )
            for asset, value in assets.items()
        }
    normalized_positions: list[dict[str, Any]] = []
    position_keys: set[tuple[str, str]] = set()
    for raw in positions:
        if not isinstance(raw, Mapping):
            raise ValueError("reconciliation position is invalid")
        venue = str(raw.get("venue") or "").strip().lower()
        base = str(raw.get("base") or "").strip().upper()
        side = str(raw.get("side") or "").strip().upper()
        if venue not in ALLOWED_VENUES or not base or side not in {"LONG", "SHORT"}:
            raise ValueError("reconciliation position identity is invalid")
        key = (venue, base)
        if key in position_keys:
            raise ValueError("reconciliation snapshot contains duplicate position legs")
        position_keys.add(key)
        normalized_positions.append(
            {
                "venue": venue,
                "base": base,
                "side": side,
                "notional_quote": _finite_non_negative(
                    raw.get("notional_quote"),
                    field=f"positions.{venue}.{base}.notional_quote",
                ),
            }
        )
    normalized_orders: list[dict[str, Any]] = []
    for raw in open_orders:
        if not isinstance(raw, Mapping):
            raise ValueError("reconciliation open order is invalid")
        venue = str(raw.get("venue") or "").strip().lower()
        if venue not in ALLOWED_VENUES:
            raise ValueError("reconciliation open order venue is invalid")
        normalized_orders.append(
            {
                "venue": venue,
                "order_ref": str(raw.get("order_ref") or "REDACTED"),
                "base": str(raw.get("base") or "").strip().upper(),
                "side": str(raw.get("side") or "").strip().upper(),
            }
        )
    return {
        "schema": SNAPSHOT_SCHEMA,
        "observed_ts": observed_ts,
        "balances": normalized_balances,
        "positions": sorted(
            normalized_positions,
            key=lambda row: (row["venue"], row["base"]),
        ),
        "open_orders": sorted(
            normalized_orders,
            key=lambda row: (row["venue"], row["base"], row["side"]),
        ),
        "source": "deterministic_fixture",
        "authenticated_request": False,
    }


def _expected_legs(
    paper_state: Mapping[str, Any],
    contract: ReconciliationContract,
) -> dict[tuple[str, str], dict[str, Any]]:
    positions = paper_state.get("positions")
    if not isinstance(positions, Mapping):
        raise ValueError("paper OMS state positions are missing")
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for map_base, raw in positions.items():
        if not isinstance(raw, Mapping):
            raise ValueError("paper OMS position is invalid")
        base = str(raw.get("base") or map_base).strip().upper()
        for venue_field, side in (("long_venue", "LONG"), ("short_venue", "SHORT")):
            venue = str(raw.get(venue_field) or "").strip().lower()
            if venue not in ALLOWED_VENUES:
                raise ValueError("paper OMS position venue is invalid")
            key = (venue, base)
            if key in expected:
                raise ValueError("paper OMS contains duplicate expected legs")
            expected[key] = {
                "venue": venue,
                "base": base,
                "side": side,
                "notional_quote": contract.notional_quote_per_leg,
            }
    return expected


def reconcile_fixture_snapshot(
    paper_state: Mapping[str, Any],
    provider: ReadOnlyReconciliationProvider,
    *,
    contract: ReconciliationContract,
) -> dict[str, Any]:
    if provider.read_only is not True:
        raise ValueError("reconciliation provider must be read-only")
    snapshot = _validate_snapshot(provider.read_snapshot())
    expected = _expected_legs(paper_state, contract)
    observed = {
        (row["venue"], row["base"]): row
        for row in snapshot["positions"]
    }
    mismatches: list[dict[str, Any]] = []
    for key in sorted(expected):
        wanted = expected[key]
        actual = observed.get(key)
        if actual is None:
            mismatches.append(
                {"type": "missing_position_leg", "venue": key[0], "base": key[1]}
            )
            continue
        if actual["side"] != wanted["side"]:
            mismatches.append(
                {
                    "type": "position_side_mismatch",
                    "venue": key[0],
                    "base": key[1],
                    "expected": wanted["side"],
                    "observed": actual["side"],
                }
            )
        delta = abs(float(actual["notional_quote"]) - contract.notional_quote_per_leg)
        if delta > contract.notional_tolerance_quote:
            mismatches.append(
                {
                    "type": "position_notional_mismatch",
                    "venue": key[0],
                    "base": key[1],
                    "absolute_delta_quote": delta,
                }
            )
    for key in sorted(set(observed) - set(expected)):
        mismatches.append(
            {"type": "unexpected_position_leg", "venue": key[0], "base": key[1]}
        )
    for order in snapshot["open_orders"]:
        mismatches.append(
            {
                "type": "unexpected_open_order",
                "venue": order["venue"],
                "base": order["base"],
                "side": order["side"],
            }
        )
    deterministic = {
        "schema": REPORT_SCHEMA,
        "provider_id": provider.provider_id,
        "snapshot_hash_sha256": sha256_json(snapshot),
        "expected_leg_count": len(expected),
        "observed_leg_count": len(observed),
        "open_order_count": len(snapshot["open_orders"]),
        "mismatches": mismatches,
        "matched": not mismatches,
        "kill_switch_required": bool(mismatches),
        "paper_state_mutated": False,
        "authenticated_request": False,
        "order_methods_available": False,
        "maximum_authority": "READ_ONLY_RECONCILIATION_FIXTURE",
    }
    return {
        **deterministic,
        "verdict": "MATCHED" if not mismatches else "RECONCILIATION_MISMATCH",
        "deterministic_result_hash": sha256_json(deterministic),
    }
