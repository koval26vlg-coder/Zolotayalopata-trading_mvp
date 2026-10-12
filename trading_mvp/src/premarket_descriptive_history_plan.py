"""Declare the cheapest question that could kill the pre-market hypothesis.

Everything built so far answers "would this have been executable" - L2 depth, official
attestation, second-precision anchors, sealed capture at a real event. That question is
expensive: it needs a live crypto listing, and the measured arrival rate on the watched
venues is 4 eligible instruments in 14 days, all from one venue, with a 95% interval of
1.2 to 11 months to reach the thirty events the acceptance bar wants.

It is also the *second* question. The first is whether there is anything to execute: does
price move systematically around a spot listing at all? That one is answerable today from
public post-hoc candles, and it can only ever *disprove*. If no edge survives an
idealised reading - no fees, no spread, no slippage, perfect entry and exit - then no
amount of execution machinery will find one, and the months of waiting are saved.

So this plan is deliberately weaker than the acceptance track, and says so in fields
rather than in a habit:

**The anchor is a proxy and is named one.** ``PROXY_FIRST_TRADED_SPOT_BAR``: the first
minute bar the venue publishes for the spot symbol. Minute precision, derived from market
data rather than from an announcement. That is enough to ask whether a distribution has a
shape; it is not enough to claim a fill, and ``t0_source_class`` records the difference so
nobody can later read this sample as acceptance evidence.

**It measures the perpetual, anchored on the spot.** The strategy under study trades the
pre-market perpetual across the spot listing moment, so the series that matters is the
perp and the moment that matters comes from the spot. Using the perp's own first bar
would anchor on the perp launch, which is a different event entirely.

**It decides nothing.** No acceptance, no paper-forward authorisation, no registry edit.
``evidence_use`` is ``DESCRIPTIVE_ONLY`` and the outcome contract says so four ways.

The bound is the point of a plan. Nine index requests and at most ninety candle requests,
because the question is about roughly thirty events and a probe that grew past its
question would be a collection nobody scoped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "trading_mvp_premarket_descriptive_history_planonly_v1"
PLAN_ID = "premarket_descriptive_history_20260831_v21"
PLAN_RELATIVE_PATH = "docs/plans/premarket-descriptive-history-planonly-20260831-v21.json"
PREVIOUS_PLAN_RELATIVE_PATH = (
    "docs/plans/premarket-descriptive-history-planonly-20260831-v20.json"
)
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"

REPO_ROOT = Path(__file__).resolve().parents[2]

# The venues whose public post-hoc endpoints were already exercised by the pre-market
# runtime's historical acquisition. Reusing exactly those keeps this study on ground that
# has been walked, and keeps a new venue an explicit edit rather than a parameter.
DISCOVERY_SOURCES = {
    "bybit": {
        "endpoint": "https://api.bybit.com/v5/announcements/index",
        "fixed_query": {"locale": "en-US", "type": "new_crypto", "limit": "20"},
    },
    "okx": {
        "endpoint": "https://www.okx.com/api/v5/public/instruments",
        "fixed_query": {"instType": "SPOT"},
    },
    # v2. The spot list alone names 1387 listings and cannot say which of them the
    # strategy could have traded: it trades the perpetual *before* the spot listing, so
    # the population is the intersection - a spot listing whose perpetual already
    # existed. One more request describes every swap and when it was listed, and the
    # intersection becomes arithmetic rather than another collection.
    "okx_swap": {
        "endpoint": "https://www.okx.com/api/v5/public/instruments",
        "fixed_query": {"instType": "SWAP"},
    },
    # v5. The result rests on one venue, which is the weakest thing about it. Bybit and
    # Gate publish the same shape of metadata - an instrument list carrying when each was
    # listed - so the population extends the same way it was built, by arithmetic on
    # catalogues rather than by reading prose.
    "bybit_spot": {
        "endpoint": "https://api.bybit.com/v5/market/instruments-info",
        "fixed_query": {"category": "spot"},
    },
    "bybit_perp": {
        "endpoint": "https://api.bybit.com/v5/market/instruments-info",
        "fixed_query": {"category": "linear", "limit": "1000"},
    },
    "gate_spot": {
        "endpoint": "https://api.gateio.ws/api/v4/spot/currency_pairs",
        "fixed_query": {},
    },
    "gate_perp": {
        "endpoint": "https://api.gateio.ws/api/v4/futures/usdt/contracts",
        "fixed_query": {},
    },
    # v10. The retrospective sample is capped at 26 by history depth, not by effort: Gate
    # serves minute candles for 10000 points - 6.9 days - and its newest qualifying event
    # is 7.1 days old, so none of its 105 events can be measured at the resolution the
    # question needs. Bybit publishes no spot listing moment at all. Binance is the one
    # venue that both lists heavily and serves minute klines going back years, so it is
    # the only way to grow n today rather than by waiting.
    "binance_spot": {
        "endpoint": "https://api.binance.com/api/v3/exchangeInfo",
        "fixed_query": {},
    },
    "binance_perp": {
        "endpoint": "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "fixed_query": {},
    },
}

SPOT_CANDLES = {
    "bybit": "https://api.bybit.com/v5/market/kline",
    "okx": "https://www.okx.com/api/v5/market/history-candles",
    # v19. Binance spot, added for the basis test below. Already the endpoint the anchor
    # phase uses to find when a spot pair first traded, so no new host is involved.
    "binance": "https://api.binance.com/api/v3/klines",
}
# v9. Gate publishes both sides of the anchor and contributes 105 of the 131 events, so
# leaving it unmeasured would mean answering the question on a fifth of the evidence that
# exists. Bybit stays listed but unreachable: it publishes no spot listing time, so there
# is no anchor to measure around, and that is a property of the venue rather than a gap
# in this study.
PERP_CANDLES = {
    "bybit": "https://api.bybit.com/v5/market/kline",
    "okx": "https://www.okx.com/api/v5/market/history-candles",
    "gate": "https://api.gateio.ws/api/v4/futures/usdt/candlesticks",
    "binance": "https://fapi.binance.com/fapi/v1/klines",
}

# Only the index is read. Article bodies are not fetched here, exactly as the pre-market
# plan forbids: a title carries a ticker, and a ticker is all this study needs, because
# the moment comes from the candles rather than from the prose.
ARTICLE_BODY_REQUESTS = 0

# v5 adds four discovery sources and two diagnostic probes, so the index budget grows
# with what is declared rather than being a number that happens to still fit.
MAX_INDEX_REQUESTS = 24
MAX_CANDLE_REQUESTS = 150
MAX_EVENTS = 140
REQUEST_TIMEOUT_SEC = 20
MAX_RUNTIME_SEC = 600
MIN_INTERVAL_BETWEEN_REQUESTS_SEC = 1

# Minutes of perpetual history either side of the proxy anchor. Wide enough to see a move
# decay, narrow enough that one event is one bounded request per side.
# v16. Widened from 60 to 120 so the window is symmetric around t0. The forward result -
# a median fall of about 3.4% by +60m across 57 episodes - means nothing on its own: an
# asset class drifting down, or a market falling during the hours these listings happened,
# would produce the same table. The same horizons measured backwards from t0 are the
# control. Equal falls on both sides say the listing is incidental; a flat run-up and a
# fall after says the moment is where the change happens. At 60 seconds a bar this costs no
# extra requests - 240 bars is inside both venues' per-request limit - only a wider read of
# a window already being fetched.
#
# The asymmetry is deliberate and must stay declared: -120m is a control, +120m is the
# subject. The study can be wrong about why the fall happens and still be right that the
# two sides differ.
# v17. 125, not 120. At 120 the window opened exactly at t0-120m, so the earliest bar
# closed at t0-119m and no bar had closed *by* t0-120m: ret_pre120m came back empty on all
# 74 rows and the +120m result had no control at all. A control window must start before
# the horizon it controls, not at it. 125 leaves five minutes of slack on a boundary that
# has now been got wrong twice in the same direction.
WINDOW_BEFORE_MIN = 125
WINDOW_AFTER_MIN = 120

# v5, first caveat. The measured effect and the measurement resolution are the same size -
# one minute - which is the worst case for believing it. This asks whether the venue will
# serve sub-minute bars for a past event at all. It may not: retention for fine bars is
# usually short, and a plain "no" is a real answer that closes the question rather than
# leaving it open as a worry.
# v10. Measured, not assumed: a venue that publishes a listing moment is still useless if
# its candle history does not reach the event. Recorded so the cap on n is a fact in the
# artifact rather than a sentence in a report.
CANDLE_HISTORY_DEPTH = {
    "okx": "YEARS_AT_1M",
    "gate": "10000_POINTS_ABOUT_6.9_DAYS_AT_1M",
    "bybit": "NO_SPOT_LISTING_TIME_SO_NO_ANCHOR",
    "binance": "YEARS_AT_1M_VERIFIED_400_DAYS",
}

# v12. Binance publishes when a perpetual was onboarded but not when a spot pair started
# trading - the same gap Bybit has. Unlike Bybit it serves klines back to 2017, so the
# moment can be derived instead of read: the first minute bar a spot symbol ever produced
# *is* the moment it started trading.
#
# That is a stronger anchor than the metadata used elsewhere in this study, not a weaker
# one - it is the market itself rather than a field someone filled in - but it costs one
# request per candidate, so the candidates are bounded and taken newest-first, where
# pre-market listings actually occur.
ANCHOR_DISCOVERY = {
    "endpoint": "https://api.binance.com/api/v3/klines",
    "method": "FIRST_MINUTE_BAR_IS_THE_LISTING_MOMENT",
    "fixed_query": {"interval": "1m", "startTime": "0", "limit": "1"},
    "candidates": "PERPETUALS_NEWEST_ONBOARD_FIRST",
    "max_requests": 340,
    "t0_source_class": "PROXY_MARKET_DATA_FIRST_TRADED_BAR",
    # v15. Re-anchoring OKX needs its own budget, not a share of the one above. v14 spent
    # a single counter across both venues, Binance exhausted all 340 of it, and the OKX
    # loop never executed a single iteration - it reported zero shifts, which reads
    # identically to "checked and found nothing". A budget that silently starves a phase
    # produces a result indistinguishable from a measurement.
    "reanchor_max_requests": 40,
}

# v16. Declared before it is measured, so a control that comes out inconvenient cannot be
# quietly dropped. These are the same horizons as the forward ones, read backwards from t0.
PLACEBO_HORIZONS_MIN = [30, 60, 120]

# v18. Two additions aimed at one unexplained thing: the v17 result was flat to +30m and
# then fell 3.1% between +30m and +60m. For an event happening at t0 that is the wrong
# shape, and the previous grid could not say more because it had no point between 30 and 60.
#
# FINE_HORIZONS closes that gap. A cliff at one minute and a ramp across half an hour are
# different phenomena and would need different explanations; the old grid could not tell
# them apart, so it was not evidence about the shape at all.
FINE_HORIZONS_MIN = [35, 40, 45, 50, 55, 75, 90]

# VOLUME_PROFILE distinguishes the two readings of a flat first half hour: the price did not
# move, or the instrument did not trade and the printed close is a stale quote nobody could
# have transacted against. Quote volume, not base volume, because it is comparable across
# tokens whose unit prices differ by orders of magnitude. Costs no requests - the venues
# already return volume in the candle rows this study was discarding.
# v19. The only mechanism for the fall that this dataset can test rather than speculate
# about.
#
# Before its spot pair exists a perpetual has no cash-and-carry anchor: there is nothing to
# buy against a short, so a premium can persist with nobody able to arbitrage it away. The
# moment spot opens the trade becomes possible, and a premium should collapse - which is a
# fall in the perpetual that has nothing to do with anyone's opinion of the token.
#
# This makes a prediction sharp enough to be wrong: measured against the same venue's spot,
# the perpetual should start the window rich and converge. If instead spot falls just as far
# as the perpetual, the basis is flat and this explanation is dead - the fall is in the
# asset, not in the contract's relationship to it.
#
# It also bears on the delay. Arbitrage needs enough spot depth to size into; a book that
# opens thin would let a premium survive the first half hour and collapse once liquidity
# arrives. That is a prediction about WHEN, testable against the volume profile from v18.
# v20. Direction of flow, which is the last thing candle data can say about the
# unexplained ramp at +30..+60m.
#
# The surviving reading of the ramp is demand exhaustion: buyers are concentrated in the
# first minutes, absorb the supply a listing releases, and when they thin the price gives
# back its early gains. That is a claim about WHO is crossing the spread, and Binance
# publishes it - a kline row carries taker-buy volume alongside total volume, so the
# aggressor share is already inside every response this study has been making. It was being
# discarded, like turnover was until v18.
#
# DECLARED BINANCE-ONLY, BEFORE THE RUN. OKX klines carry no aggressor breakdown, and its
# history-trades endpoint returns 100 trades a page with a retention window shorter than
# most events in this sample. Reporting a two-venue number here would repeat defect 8,
# where a Binance-only turnover profile was published as a general fact.
#
# The prediction is sharp enough to fail: if exhaustion drives the ramp, the taker-buy share
# should sit above one half while the price holds and fall through one half around the time
# the ramp starts. A share that never crosses, crosses in the wrong direction, or sits flat
# across the whole window kills the reading.
FLOW_DIRECTION = {
    "role": "MECHANISM_CANDIDATE_NOT_SUBJECT",
    "venues": ["binance"],
    "venue_exclusion_reason": {
        "okx": "NO_AGGRESSOR_FIELD_IN_CANDLES_AND_TRADE_HISTORY_TOO_SHORT",
    },
    "field": "TAKER_BUY_QUOTE_OVER_QUOTE_VOLUME",
    "kline_indices": {"quote_volume": 7, "trade_count": 8, "taker_buy_quote": 10},
    "integrity_check": "TAKER_BUY_SHARE_MUST_LIE_IN_ZERO_TO_ONE",
    "supports_if": "SHARE_ABOVE_HALF_EARLY_AND_CROSSING_BELOW_NEAR_THE_RAMP",
    "falsifies_if": "SHARE_FLAT_OR_NEVER_CROSSING_OR_CROSSING_UPWARD",
}

BASIS_TEST = {
    "role": "MECHANISM_CANDIDATE_NOT_SUBJECT",
    "definition": "PERP_CLOSE_OVER_SPOT_CLOSE_MINUS_ONE_SAME_VENUE_SAME_BAR",
    "horizons_min": [1, 5, 15, 30, 45, 60, 90, 120],
    "spot_symbols": {"okx": "BASE-USDT", "binance": "BASEUSDT"},
    "max_requests": 90,
    "falsifies_if": "BASIS_FLAT_ACROSS_THE_WINDOW",
    "supports_if": "BASIS_POSITIVE_AT_OPEN_AND_DECAYING",
}

VOLUME_PROFILE = {
    "field": "QUOTE_VOLUME_PER_BAR",
    "segments_min": [[-120, 0], [0, 1], [1, 5], [5, 15], [15, 30], [30, 60], [60, 120]],
    "reads": "IF_TRADING_ARRIVES_AT_30_60_THE_DELAY_IS_LIQUIDITY_NOT_PRICE",
    "role": "DIAGNOSTIC_NOT_SUBJECT",
}

# v17. The remaining explanation the placebo cannot rule out: the market itself. A flat
# pre-window says the asset was not already sliding, but a market-wide drop landing in the
# +60..+120m window across correlated listing dates would produce the same table. The
# benchmark is read from the SAME venue as the event, over the SAME window, so the
# subtraction cancels the venue's clock, its microstructure and its outages rather than
# introducing a second data source with its own.
#
# Declared as a control before it is measured. If the excess return is flat, the finding is
# market beta and the study says so.
MARKET_BENCHMARK = {
    "role": "CONTROL_NOT_SUBJECT",
    "method": "SAME_VENUE_SAME_WINDOW_PERPETUAL_BTC",
    "symbols": {"okx": "BTC-USDT-SWAP", "binance": "BTCUSDT"},
    "excess_definition": "EVENT_RETURN_MINUS_BENCHMARK_RETURN_SAME_HORIZON",
    "max_requests": 90,
    "reads": "IF_EXCESS_IS_FLAT_THE_FALL_IS_THE_MARKET_NOT_THE_LISTING",
}
PLACEBO_ROLE = "CONTROL_NOT_SUBJECT"
PLACEBO_READS = "IF_THE_PRE_WINDOW_FALLS_AS_FAR_THE_LISTING_EXPLAINS_NOTHING"

SECONDS_PROBE = {
    "endpoint": "https://www.okx.com/api/v5/market/history-candles",
    "bars_to_try": ["1s", "1m"],
    "max_requests": 4,
    "records": "AVAILABILITY_AND_EARLIEST_TIMESTAMP_ONLY",
}

# v5, third caveat. The gross figure is 0.24% and the plan forbids measuring execution, so
# this measures the one component that *is* published and exact: the instrument's tick
# size. One tick is the smallest spread that can exist, so tick over price is a hard floor
# on cost - not an estimate of the real spread, which needs an order book and is out of
# scope here. A floor is enough to say whether 0.24% has room in it.
COST_FLOOR = {
    "source": "VENUE_INSTRUMENT_METADATA_TICK_SIZE",
    "measures": "MINIMUM_POSSIBLE_SPREAD_ONLY",
    "does_not_measure": ["realised_spread", "fees", "slippage", "depth"],
}

IMPLEMENTATION_ROLES = {
    "descriptive_history_plan_generator": "trading_mvp/src/premarket_descriptive_history_plan.py",
    "descriptive_history_collector": "trading_mvp/src/premarket_descriptive_history_collect.py",
}


class DescriptiveHistoryPlanError(ValueError):
    """The plan cannot be built or does not describe what it claims."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DescriptiveHistoryPlanError(message)


def canonical_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "plan_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _supersession(repo_root: Path) -> dict[str, Any]:
    """What this plan replaces, bound by hash. A superseded plan is immutable, so this
    check stays true rather than expiring."""
    previous = repo_root / PREVIOUS_PLAN_RELATIVE_PATH
    _require(previous.is_file(), f"superseded plan missing: {previous}")
    payload = json.loads(previous.read_text(encoding="utf-8"))
    _require(payload.get("plan_id") != PLAN_ID, "a plan cannot supersede itself")
    return {
        "plan_id": str(payload["plan_id"]),
        "plan_hash": str(payload["plan_hash"]),
        "plan_file_sha256": _sha256_file(previous),
        "plan_path": str(previous),
    }


def _scope_change(repo_root: Path) -> dict[str, Any]:
    """Which discovery sources this plan asks that its predecessor did not.

    Declared rather than forbidden, and required to account for the difference exactly:
    a source added without saying so would make the collection wider than the artifact
    admits to, which is the one thing a bound is supposed to prevent."""
    previous = repo_root / PREVIOUS_PLAN_RELATIVE_PATH
    _require(previous.is_file(), f"superseded plan missing: {previous}")
    earlier = json.loads(previous.read_text(encoding="utf-8"))
    before = set((earlier.get("discovery") or {}).get("sources") or {})
    now = set(DISCOVERY_SOURCES)
    added, removed = sorted(now - before), sorted(before - now)
    changed = bool(added or removed)
    reason = ""
    if changed:
        parts = []
        if added:
            parts.append("sources added: " + ", ".join(added))
        if removed:
            parts.append("sources removed: " + ", ".join(removed))
        reason = "; ".join(parts) + (
            ". The population under study is a spot listing whose perpetual already "
            "existed, and a spot list alone cannot express that intersection."
        )
    return {
        "declared": changed,
        "sources_added": added,
        "sources_removed": removed,
        "reason": reason,
    }


def build_plan(*, generated_at_utc: str, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    implementation = []
    for role, relative in sorted(IMPLEMENTATION_ROLES.items()):
        target = repo_root / relative
        _require(target.is_file(), f"implementation missing: {relative}")
        implementation.append(
            {"role": role, "path": str(target), "sha256": _sha256_file(target)}
        )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "READY_FOR_ONE_BOUNDED_PUBLIC_DESCRIPTIVE_HISTORY_NOT_EXECUTED",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "private_api": False,
        "authenticated": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "writes_market_data": False,
        "supersedes": _supersession(repo_root),
        "scope_change": _scope_change(repo_root),
        "question": (
            "Around the moment a token starts trading on spot, does the pre-market "
            "perpetual move systematically, and over what horizon? Read from public "
            "post-hoc candles, without fees, spread or slippage - an idealised upper "
            "bound whose only decisive outcome is a negative one."
        ),
        "why_this_before_the_expensive_one": (
            "The execution question needs a live listing and second-precision official "
            "anchors. Measured arrival on the watched venues is 4 eligible instruments "
            "in 14.1 days from a single venue, 95% interval 1.2 to 11 months to thirty "
            "events. This question needs neither, and if it answers no, the other stops "
            "being worth asking."
        ),
        "temporal_anchor": {
            "t0_kind": "PROXY_FIRST_TRADED_SPOT_BAR",
            "t0_source_class": "PROXY_MARKET_DATA_NOT_OFFICIAL_ANNOUNCEMENT",
            "t0_precision_sec": 60,
            "why_a_proxy_is_enough_here": (
                "Minute precision cannot support a claim about a fill, and this plan "
                "makes none. It is enough to ask whether a distribution has a shape."
            ),
            "why_not_the_perp_first_bar": (
                "The perpetual starts trading before the spot listing, so its own first "
                "bar anchors on the perp launch - a different event."
            ),
        },
        "discovery": {
            "sources": DISCOVERY_SOURCES,
            "article_body_requests": ARTICLE_BODY_REQUESTS,
            "max_index_requests": MAX_INDEX_REQUESTS,
            "authority_boundary": {
                "index_gives": "TICKER_AND_PUBLICATION_TIME_ONLY",
                "ticker_match": "DISCOVERY_HEURISTIC_NOT_ASSET_IDENTITY_PROOF",
                "t0_never_from_index": True,
            },
        },
        "anchor_discovery": ANCHOR_DISCOVERY,
        "candle_history_depth": CANDLE_HISTORY_DEPTH,
        "seconds_probe": SECONDS_PROBE,
        "cost_floor": COST_FLOOR,
        "measurement": {
            "spot_candles": SPOT_CANDLES,
            "perp_candles": PERP_CANDLES,
            "interval": "1m",
            "window_before_min": WINDOW_BEFORE_MIN,
            "window_after_min": WINDOW_AFTER_MIN,
            "placebo_horizons_min": PLACEBO_HORIZONS_MIN,
            "placebo_role": PLACEBO_ROLE,
            "placebo_reads": PLACEBO_READS,
            "market_benchmark": MARKET_BENCHMARK,
            "fine_horizons_min": FINE_HORIZONS_MIN,
            "volume_profile": VOLUME_PROFILE,
            "basis_test": BASIS_TEST,
            "flow_direction": FLOW_DIRECTION,
            "max_events": MAX_EVENTS,
            "max_candle_requests": MAX_CANDLE_REQUESTS,
        },
        "bounds": {
            "request_timeout_sec": REQUEST_TIMEOUT_SEC,
            "max_runtime_sec": MAX_RUNTIME_SEC,
            "min_interval_between_requests_sec": MIN_INTERVAL_BETWEEN_REQUESTS_SEC,
            "max_retries_per_request": 0,
            "pagination_beyond_declared_pages": False,
            "redirects": "FORBIDDEN_OFF_HOST",
        },
        "outcome_contract": {
            "produces": "descriptive_price_path_distribution",
            "evidence_use": "DESCRIPTIVE_ONLY",
            "acceptance_capable": False,
            "execution_evidence": False,
            "may_edit_declared_registry": False,
            "may_accept_a_listing": False,
            "may_authorise_paper_forward": False,
            "may_authorise_live_trading": False,
            "decisive_outcome": "NEGATIVE_ONLY",
            "human_review_required": True,
        },
        "implementation": {"files": implementation},
        "plan_hash_method": HASH_METHOD,
    }
    payload["plan_hash"] = canonical_hash(payload)
    return payload


def validate_plan(plan: Mapping[str, Any], *, repo_root: Path = REPO_ROOT) -> None:
    _require(plan.get("schema") == SCHEMA, "schema")
    _require(plan.get("plan_id") == PLAN_ID, "plan id")
    _require(plan.get("mode") == "PlanOnly", "mode")
    for flag in ("research_only", "public_data_only"):
        _require(plan.get(flag) is True, flag)
    for flag in ("private_api", "authenticated", "live_orders", "real_capital",
                 "leverage_or_margin", "writes_market_data"):
        _require(plan.get(flag) is False, flag)

    outcome = plan.get("outcome_contract") or {}
    for flag in ("acceptance_capable", "execution_evidence", "may_edit_declared_registry",
                 "may_accept_a_listing", "may_authorise_paper_forward",
                 "may_authorise_live_trading"):
        _require(outcome.get(flag) is False, f"outcome {flag}")
    _require(outcome.get("evidence_use") == "DESCRIPTIVE_ONLY", "outcome evidence_use")
    _require(outcome.get("human_review_required") is True, "outcome human_review_required")

    # The anchor must keep announcing its own weakness. A study that quietly relabelled a
    # proxy as official would be indistinguishable from acceptance evidence a month later.
    anchor = plan.get("temporal_anchor") or {}
    _require(anchor.get("t0_kind") == "PROXY_FIRST_TRADED_SPOT_BAR", "anchor t0_kind")
    _require(
        anchor.get("t0_source_class") == "PROXY_MARKET_DATA_NOT_OFFICIAL_ANNOUNCEMENT",
        "anchor t0_source_class",
    )
    _require(int(anchor.get("t0_precision_sec") or 0) >= 60, "anchor precision")

    superseded = plan.get("supersedes") or {}
    _require(bool(superseded), "supersedes block")
    previous_path = Path(str(superseded.get("plan_path") or ""))
    _require(previous_path.is_file(), f"superseded plan missing: {previous_path}")
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    _require(previous.get("plan_hash") == superseded.get("plan_hash"), "superseded plan hash")
    _require(_sha256_file(previous_path) == superseded.get("plan_file_sha256"),
             "superseded plan file sha256")
    _require(superseded.get("plan_id") != plan.get("plan_id"), "a plan cannot supersede itself")

    scope = plan.get("scope_change")
    _require(isinstance(scope, Mapping), "scope_change block")
    for field in ("declared", "sources_added", "sources_removed", "reason"):
        _require(field in scope, f"scope_change {field}")
    before = set((previous.get("discovery") or {}).get("sources") or {})
    now = set((plan.get("discovery") or {}).get("sources") or {})
    _require(list(scope["sources_added"]) == sorted(now - before), "scope_change sources_added")
    _require(list(scope["sources_removed"]) == sorted(before - now), "scope_change sources_removed")
    _require(bool(scope["declared"]) == bool((now - before) or (before - now)),
             "scope_change declared")

    discovery = plan.get("discovery") or {}
    _require(int(discovery.get("article_body_requests", -1)) == 0, "article body requests")
    _require(
        (discovery.get("authority_boundary") or {}).get("t0_never_from_index") is True,
        "authority boundary",
    )

    # The two v5 diagnostics have to keep saying what they are not. A tick-size floor
    # read later as "the spread" would turn a bound into a measurement nobody took.
    anchor = plan.get("anchor_discovery") or {}
    _require(anchor.get("t0_source_class") == "PROXY_MARKET_DATA_FIRST_TRADED_BAR",
             "anchor discovery source class")
    _require(0 < int(anchor.get("max_requests") or 0) <= 400, "anchor discovery budget")
    _require(0 < int(anchor.get("reanchor_max_requests") or 0) <= 80,
             "anchor re-anchoring budget")

    measurement = plan.get("measurement") or {}
    _require(list(measurement.get("placebo_horizons_min") or []) == [30, 60, 120],
             "placebo horizons")
    _require(measurement.get("placebo_role") == "CONTROL_NOT_SUBJECT", "placebo role")
    _require(int(measurement.get("window_before_min") or 0)
             > max(measurement.get("placebo_horizons_min") or [0]),
             "pre-window must start before the widest horizon it controls, not at it")

    fine = list(measurement.get("fine_horizons_min") or [])
    _require(fine == [35, 40, 45, 50, 55, 75, 90], "fine horizons")
    _require(max(fine) < int(measurement.get("window_after_min") or 0),
             "fine horizons inside the measured window")

    flow = measurement.get("flow_direction") or {}
    _require(flow.get("role") == "MECHANISM_CANDIDATE_NOT_SUBJECT", "flow role")
    _require(list(flow.get("venues") or []) == ["binance"], "flow declared binance-only")
    _require("okx" in (flow.get("venue_exclusion_reason") or {}),
             "flow must say why a venue is absent, not leave it to be noticed later")
    _require(bool(flow.get("supports_if")) and bool(flow.get("falsifies_if")),
             "flow test must say what would kill it before it is run")
    _require((flow.get("kline_indices") or {}).get("taker_buy_quote") == 10,
             "taker buy index")

    basis = measurement.get("basis_test") or {}
    _require(basis.get("role") == "MECHANISM_CANDIDATE_NOT_SUBJECT", "basis role")
    _require(bool(basis.get("falsifies_if")) and bool(basis.get("supports_if")),
             "basis test must say what would kill it before it is run")
    _require(0 < int(basis.get("max_requests") or 0) <= 120, "basis budget")
    _require(max(basis.get("horizons_min") or [0])
             <= int(measurement.get("window_after_min") or 0), "basis horizons in window")

    vol = measurement.get("volume_profile") or {}
    _require(vol.get("field") == "QUOTE_VOLUME_PER_BAR", "volume profile field")
    _require(vol.get("role") == "DIAGNOSTIC_NOT_SUBJECT", "volume profile role")

    bench = measurement.get("market_benchmark") or {}
    _require(bench.get("role") == "CONTROL_NOT_SUBJECT", "benchmark role")
    _require(set(bench.get("symbols") or {}) >= {"okx", "binance"}, "benchmark per venue")
    _require(0 < int(bench.get("max_requests") or 0) <= 120, "benchmark budget")

    depth = plan.get("candle_history_depth") or {}
    _require(bool(depth), "candle history depth")
    _require("gate" in depth and "okx" in depth, "candle history depth per venue")

    probe = plan.get("seconds_probe") or {}
    _require(bool(probe.get("bars_to_try")), "seconds probe bars")
    _require(0 < int(probe.get("max_requests") or 0) <= 8, "seconds probe budget")
    floor = plan.get("cost_floor") or {}
    _require(floor.get("measures") == "MINIMUM_POSSIBLE_SPREAD_ONLY", "cost floor scope")
    _require("realised_spread" in (floor.get("does_not_measure") or []),
             "cost floor must disclaim the realised spread")

    bounds = plan.get("bounds") or {}
    _require(int(bounds.get("max_retries_per_request", -1)) == 0, "retries")
    measurement = plan.get("measurement") or {}
    _require(0 < int(measurement.get("max_candle_requests") or 0) <= MAX_CANDLE_REQUESTS,
             "candle request bound")
    _require(0 < int(discovery.get("max_index_requests") or 0) <= MAX_INDEX_REQUESTS,
             "index request bound")

    rows = (plan.get("implementation") or {}).get("files") or []
    _require(bool(rows), "implementation bindings")
    for row in rows:
        path = Path(str(row.get("path")))
        _require(path.is_file(), f"implementation missing: {path}")
        _require(_sha256_file(path) == row.get("sha256"),
                 f"implementation sha256: {row.get('role')}")

    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash")


def write_plan(generated_at_utc: str, *, repo_root: Path = REPO_ROOT) -> Path:
    plan = build_plan(generated_at_utc=generated_at_utc, repo_root=repo_root)
    target = repo_root / PLAN_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise DescriptiveHistoryPlanError(f"immutable plan already exists: {target}")
    target.write_bytes(
        (json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write-plan", action="store_true")
    actions.add_argument("--plan-check", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args(argv)
    try:
        if args.plan_check:
            path = REPO_ROOT / PLAN_RELATIVE_PATH
            validate_plan(json.loads(path.read_text(encoding="utf-8")))
            print(json.dumps({"status": "PLAN_OK", "plan_id": PLAN_ID}))
            return 0
        stamp = args.generated_at_utc
        _require(bool(stamp), "--generated-at-utc is required")
        path = write_plan(stamp)
        plan = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({
            "status": "PLAN_WRITTEN", "path": str(path), "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"], "execution_performed": False,
        }, ensure_ascii=False))
        return 0
    except (DescriptiveHistoryPlanError, OSError, ValueError) as exc:
        print(json.dumps({"status": "PLAN_BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
