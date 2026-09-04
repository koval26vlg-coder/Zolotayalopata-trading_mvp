"""A prospective study: capture the order book across a spot listing, before it happens.

The retrospective study reached its boundary. It established that a token's price falls a
median 3.9% in the hour after its spot pair opens, market-adjusted, replicated on two venues
and clear of every artifact it could be checked against. It then failed to explain the shape
of that fall - the decline starts around the thirtieth minute - and eliminated five
explanations in the process: the market, a pre-existing drift, basis convergence, arriving
liquidity, and demand exhaustion. The last of those is the informative failure: every measure
derivable from the trade tape - direction of aggressive flow, its net imbalance in money,
average trade size, price impact per unit of turnover - is indistinguishable from what it was
two hours before the listing.

A price that moves while the tape does not is a statement about the passive side. Makers can
reprice or withdraw without any trade printing. That is where the remaining candidates live,
and no venue publishes order book history for past dates - not OKX, not Binance, not Gate.
The only way to look is to be there when it happens.

Hence forward. Three things change for the better and one for the worse:

  Better - Gate becomes usable. Retrospectively it was dead: its minute candles reach back
  10000 points, about 6.9 days, so not one of its 105 qualifying events could be measured. A
  live capture does not care how deep the archive is. Gate alone lists about 55 qualifying
  events a year, more than OKX and Binance together.

  Better - the anchor stops being a proxy. Retrospectively t0 had to be inferred from the
  first bar a spot symbol ever produced. Here the venue states the schedule before the fact
  and the capture records the first trade as it prints.

  Better - the hypothesis is registered before the data exists, which is the one thing a
  retrospective study can never honestly claim, however carefully it declares its falsifiers
  after the fact.

  Worse - the sample grows at about one event every four days across the three venues, so
  what took an afternoon retrospectively takes months here. That is the price of looking at
  the only place left to look.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "trading_mvp_premarket_forward_depth_planonly_v1"
PLAN_ID = "premarket_forward_depth_20260902_v5"
PLAN_RELATIVE_PATH = "docs/plans/premarket-forward-depth-planonly-20260902-v5.json"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"

REPO_ROOT = Path(__file__).resolve().parents[2]

IMPLEMENTATION = [
    ("forward_depth_plan_generator", "trading_mvp/src/premarket_forward_depth_plan.py"),
    ("forward_depth_watcher", "trading_mvp/src/premarket_forward_depth_watch.py"),
]

# A new lineage, not a successor. The retrospective family measures the past from archives
# and its question is answered; this one waits for events and asks what the archives cannot
# hold. Declaring it a successor would imply the earlier plans are withdrawn, and they are
# not - they remain the evidence for the finding this study exists to explain.
LINEAGE = {
    "kind": "NEW_LINEAGE_NOT_A_SUCCESSOR",
    "related_family": "premarket_descriptive_history_20260831",
    "related_final": "docs/plans/premarket-descriptive-history-planonly-20260831-v20.json",
    "why_new": "PROSPECTIVE_CAPTURE_CANNOT_SUPERSEDE_A_RETROSPECTIVE_MEASUREMENT",
}

# An event qualifies only if the perpetual was already trading when the spot pair opens.
# That is the whole population: a token whose derivative price exists before its cash price
# does. The check that matters is the ordering, not the mere existence of a contract - the
# first forward scan written for this study called a token qualified because a perpetual
# existed, and missed that it launched ten minutes AFTER the spot. A simultaneous launch is a
# different phenomenon and would have entered the sample as if it were this one.
QUALIFICATION = {
    "rule": "PERP_LAUNCH_STRICTLY_BEFORE_SPOT_OPEN",
    "min_lead_sec": 3600,
    "max_lead_days": 30,
    "quote": "USDT",
    "rejects": "SIMULTANEOUS_OR_SPOT_FIRST_LAUNCHES",
    # v4. Tokenised equities are recorded, not rejected. The first captured event was
    # AINVDA - an NVDA derivative - and whether a tokenised share behaves like a token
    # listing is a question this study must not answer by assumption: a share has an
    # external reference price and a token does not. A study that captures one event every
    # four days cannot discard a capture on a heuristic, so the flag rides along and the
    # split is made in analysis, where it can be argued with.
    "equity_handling": "RECORDED_NOT_EXCLUDED",
}

# Where a scheduled opening is published before it happens. Binance is absent by measurement,
# not by oversight: it publishes no spot listing time at all, before or after, which is why
# the retrospective study had to derive its anchors from first-traded bars.
SCHEDULE_SOURCES = {
    "okx_spot": {
        "endpoint": "https://www.okx.com/api/v5/public/instruments",
        "fixed_query": {"instType": "SPOT"},
        "schedule_field": "listTime",
        "pending_state": "preopen",
        "notice_observed": "AT_LEAST_7H46M_BEFORE_LIST_TIME_MEASURED_ON_CP_USDT",
    },
    "okx_swap": {
        "endpoint": "https://www.okx.com/api/v5/public/instruments",
        "fixed_query": {"instType": "SWAP"},
        "schedule_field": "listTime",
    },
    "gate_spot": {
        "endpoint": "https://api.gateio.ws/api/v4/spot/currency_pairs",
        "fixed_query": {},
        "schedule_field": "buy_start",
        "notice_observed": "UNKNOWN_ONLY_ONE_FORWARD_RECORD_SEEN",
    },
    "gate_perp": {
        "endpoint": "https://api.gateio.ws/api/v4/futures/usdt/contracts",
        "fixed_query": {},
        "schedule_field": "launch_time",
    },
}

# OKX spot trading opens one hour after the published listTime - measured at 3600s in 23 of
# 26 past events, never at zero. Gate's buy_start is the opening itself. Getting this wrong
# is what put 26 measurements inside an hour when the pair was not trading.
TRADE_OPEN_OFFSET_SEC = {"okx": 3600, "gate": 0}

DEPTH_BOOKS = {
    "okx_spot": "https://www.okx.com/api/v5/market/books",
    "okx_swap": "https://www.okx.com/api/v5/market/books",
    "gate_spot": "https://api.gateio.ws/api/v4/spot/order_book",
    "gate_perp": "https://api.gateio.ws/api/v4/futures/usdt/order_book",
}

# Depth is summarised at distance bands rather than stored level by level, because the
# question is how much size stands within reach of the price, not where each order sits. The
# raw response is hashed and its top levels kept so a band can be recomputed and disputed.
CAPTURE = {
    "window_before_min": 120,
    "window_after_min": 120,
    "snapshot_interval_sec": 20,
    "depth_levels_requested": 400,
    "levels_retained_per_side": 50,
    "distance_bands_pct": [0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
    # v2. A venue returns its top levels, not its book. Measured on BTC, 400 OKX levels
    # reach less than 0.1% from mid, so every wider band collapses to the same number - and
    # that number means the book ended, not that nothing stands beyond. Each band now
    # carries whether it was truncated, and the reach itself is recorded per side.
    "truncation_recorded": "PER_BAND_PER_SIDE_PLUS_ACTUAL_REACH",
    # v4. Found by the first live capture, which is what a first live capture is for. A
    # fixed distance band has two ways of coming back empty and only one was being caught.
    # Truncation is the book ending before the band; the other is the band lying inside the
    # spread, where no level can be. That perpetual quoted 385 bps and its 1% band was
    # inside the spread in 77% of 532 snapshots, every one of which would have read as
    # "no bid depth within one percent".
    "inside_spread_recorded": "PER_BAND_PER_SIDE",
    # And the measure that no spread can make undefined. Level counts, not distances.
    "level_count_depth": [5, 10, 25, 50],
    "legs": {
        "perp": "WHOLE_WINDOW",
        "spot": "FROM_T0_ONWARD_IT_DOES_NOT_EXIST_BEFORE",
    },
    "max_snapshots_per_event": 1600,
    "max_response_bytes": 8 * 1024 * 1024,
    "min_interval_between_requests_sec": 1,
    "request_timeout_sec": 20,
}

# The pre-window is bounded by how early the venue says anything. OKX has been observed
# publishing a pending instrument at least 7h46m ahead, which covers 120 minutes with room.
# Gate's notice is unmeasured - one forward record has been seen, and that is not a sample.
# So the control window may come out short on Gate, and a short control must be recorded as
# short rather than padded with whatever the capture happens to have.
# v5. The anchor is checked against the tape, not trusted from the schedule.
#
# Gate published FONE opening at 11:00Z, the watcher armed and began recording, and the
# venue then moved the opening to 12:00Z. Two captures exist an hour apart, and the earlier
# one is anchored on a moment when nothing traded. Its own file says so: the first usable
# spot book arrives at +60.00 minutes, against +0.25 in the correct capture.
#
# This is the retrospective study's defect number two wearing different clothes. There the
# schedule said "announced" and the code read "traded"; here the schedule said 11:00 and the
# venue later said 12:00. The lesson is the same either way - a published time is a claim
# about the future, and only the book itself says what happened.
#
# The capture is flagged, never discarded. The bytes were observed; they are simply not
# observations of what the anchor claims, and that distinction belongs in the record.
ANCHOR_CHECK = {
    "measure": "REL_MINUTES_OF_THE_FIRST_USABLE_SPOT_BOOK",
    "max_first_spot_book_delay_min": 5.0,
    "on_suspect": "FLAG_IN_FOOTER_NEVER_DISCARD",
    "supersession": "SAME_VENUE_AND_BASE_UNDER_A_NEW_T0_SUPERSEDES_THE_OLDER_CAPTURE",
    "why": "A_PUBLISHED_SCHEDULE_IS_A_CLAIM_THE_BOOK_IS_THE_EVIDENCE",
}

NOTICE_LIMIT = {
    "pre_window_is_bounded_by_notice": True,
    "on_short_notice": "RECORD_ACTUAL_PRE_MINUTES_NEVER_PAD",
    "minimum_useful_pre_min": 30,
    # v4. A short control has two different causes and they must not be conflated. The venue
    # may have announced late, or the perpetual may itself be younger than the window - a
    # 64-minute lead cannot give a 120-minute control at any cadence, because there was no
    # perpetual to record. The first captured event was the second kind.
    "bound_reasons": ["FULL", "VENUE_NOTICE", "PERP_LAUNCH"],
    # v3. The scan cadence follows from the notice, so the notice gets measured rather than
    # guessed. A scan interval I catches an event with a full pre-window only when the venue
    # publishes at least window_before + I ahead; below that the control comes out short.
    # OKX is measured and generous. Gate is not measured at all, and the first cadence chosen
    # for it - three minutes - cost 2.0 GB a day to catch about seven events a month, while
    # buying nothing over fifteen minutes unless Gate's notice lands in a narrow band around
    # two hours. Fifteen minutes with compression is 0.13 GB a day.
    "cadence_min": 15,
    "cadence_rationale": "SCAN_INTERVAL_MUST_BE_UNDER_NOTICE_MINUS_PRE_WINDOW",
    "notice_measured": {"okx": "AT_LEAST_466_MIN", "gate": "UNMEASURED_BEING_RECORDED"},
    "measurement": "FIRST_SEEN_PER_SCHEDULED_EVENT_IS_A_LOWER_BOUND",
    "revisit_cadence_after_samples": 5,
}

# Registered before any datum exists. This is the claim the retrospective study could not
# make, and the reason for doing this at all.
HYPOTHESIS = {
    "statement": (
        "The fall between +30m and +60m is accompanied by a withdrawal of resting bid depth "
        "rather than by any change in aggressive order flow."
    ),
    "primary_measure": "QUOTE_VALUE_OF_BIDS_WITHIN_1PCT_OF_MID_RELATIVE_TO_PRE_WINDOW",
    # v4. The fixed band is undefined whenever the spread exceeds twice it, which on the
    # first captured event was most of the time. The fallback is a level count, which is
    # defined at every spread, and the rule for choosing between them is fixed here rather
    # than at analysis time - otherwise the choice becomes a free parameter.
    "fallback_measure": "QUOTE_VALUE_OF_THE_BEST_25_BIDS_RELATIVE_TO_PRE_WINDOW",
    "use_fallback_when": "BAND_INSIDE_SPREAD_IN_OVER_A_THIRD_OF_SNAPSHOTS",
    "supports_if": "BID_DEPTH_FALLS_BEFORE_OR_WITH_THE_PRICE_AND_ASK_DEPTH_DOES_NOT",
    "falsifies_if": (
        "BID_DEPTH_FLAT_OR_RISING_THROUGH_THE_RAMP, OR_BOTH_SIDES_THIN_EQUALLY"
    ),
    "already_known_not_to_explain": [
        "MARKET_BETA", "PRE_EXISTING_DRIFT", "BASIS_CONVERGENCE",
        "ARRIVING_LIQUIDITY", "AGGRESSOR_IMBALANCE",
    ],
    "registered_before_data": True,
}

OUTCOME = {
    "acceptance_capable": False,
    "decisive_outcome": "NEGATIVE_ONLY",
    "evidence_use": "DESCRIPTIVE_ONLY",
    "human_review_required": True,
    "sample_grows_at": "ABOUT_ONE_QUALIFYING_EVENT_EVERY_FOUR_DAYS_ACROSS_THREE_VENUES",
    "minimum_events_before_any_claim": 12,
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ForwardDepthPlanError(message)


class ForwardDepthPlanError(RuntimeError):
    """The plan does not hold, so nothing may be captured under it."""


def canonical_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "plan_hash"}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_plan(*, generated_at_utc: str, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    files = []
    for role, relative in IMPLEMENTATION:
        target = repo_root / relative
        _require(target.is_file(), f"implementation missing: {relative}")
        files.append({"role": role, "path": str(target), "sha256": _sha256_file(target)})

    related = repo_root / LINEAGE["related_final"]
    _require(related.is_file(), f"related plan missing: {LINEAGE['related_final']}")
    lineage = dict(LINEAGE)
    lineage["related_final_sha256"] = _sha256_file(related)

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "READY",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "private_api": False,
        "authenticated": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "writes_market_data": True,
        "question": (
            "When a token's spot pair opens and its price falls over the following hour, "
            "does resting bid depth withdraw?"
        ),
        "why_forward": (
            "No venue publishes order book history for past dates, and every trade-derived "
            "measure has already been shown not to change."
        ),
        "lineage": lineage,
        "qualification": QUALIFICATION,
        "schedule_sources": SCHEDULE_SOURCES,
        "trade_open_offset_sec": TRADE_OPEN_OFFSET_SEC,
        "depth_books": DEPTH_BOOKS,
        "capture": CAPTURE,
        "anchor_check": ANCHOR_CHECK,
        "notice_limit": NOTICE_LIMIT,
        "hypothesis": HYPOTHESIS,
        "outcome_contract": OUTCOME,
        "implementation": {"files": files},
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
                 "leverage_or_margin"):
        _require(plan.get(flag) is False, flag)

    outcome = plan.get("outcome_contract") or {}
    for flag in ("acceptance_capable",):
        _require(outcome.get(flag) is False, f"outcome {flag}")
    _require(outcome.get("evidence_use") == "DESCRIPTIVE_ONLY", "outcome evidence_use")
    _require(outcome.get("human_review_required") is True, "outcome human_review_required")
    _require(int(outcome.get("minimum_events_before_any_claim") or 0) >= 12,
             "a claim floor, so a first lucky capture cannot become a finding")

    qual = plan.get("qualification") or {}
    _require(qual.get("rule") == "PERP_LAUNCH_STRICTLY_BEFORE_SPOT_OPEN", "qualification rule")
    _require(int(qual.get("min_lead_sec") or 0) > 0,
             "a strictly positive lead, or a simultaneous launch enters as pre-market")

    hypo = plan.get("hypothesis") or {}
    _require(hypo.get("registered_before_data") is True, "hypothesis registered before data")
    _require(bool(hypo.get("supports_if")) and bool(hypo.get("falsifies_if")),
             "hypothesis must say what would kill it before anything is captured")
    _require(len(hypo.get("already_known_not_to_explain") or []) >= 5,
             "the eliminated explanations must be carried forward, not re-litigated")

    cap = plan.get("capture") or {}
    _require(0 < int(cap.get("snapshot_interval_sec") or 0) <= 60, "snapshot interval")
    _require(0 < int(cap.get("max_snapshots_per_event") or 0) <= 2000, "snapshot bound")
    _require(int(cap.get("window_before_min") or 0) >= 120, "pre-window")
    _require(list(cap.get("distance_bands_pct") or [])[:1] == [0.1], "distance bands")
    _require(cap.get("truncation_recorded") == "PER_BAND_PER_SIDE_PLUS_ACTUAL_REACH",
             "a band wider than the book must be marked, never reported as a measurement")
    _require(cap.get("inside_spread_recorded") == "PER_BAND_PER_SIDE",
             "a band inside the spread must be marked; empty there is not zero depth")
    _require(list(cap.get("level_count_depth") or []) == [5, 10, 25, 50],
             "a measure that no spread can make undefined")

    _require(bool((plan.get("hypothesis") or {}).get("fallback_measure")),
             "the fallback measure must exist before a wide spread forces it")
    _require(bool((plan.get("hypothesis") or {}).get("use_fallback_when")),
             "and the rule for using it must be fixed here, not chosen at analysis time")
    _require(qual.get("equity_handling") == "RECORDED_NOT_EXCLUDED",
             "tokenised equities are recorded, never silently dropped")

    anchor = plan.get("anchor_check") or {}
    _require(anchor.get("measure") == "REL_MINUTES_OF_THE_FIRST_USABLE_SPOT_BOOK",
             "the anchor is checked against the book, not the schedule")
    _require(0 < float(anchor.get("max_first_spot_book_delay_min") or 0) <= 15,
             "anchor tolerance")
    _require(anchor.get("on_suspect") == "FLAG_IN_FOOTER_NEVER_DISCARD",
             "a suspect capture is flagged, not deleted - the bytes were really observed")
    _require(bool(anchor.get("supersession")), "a moved opening must supersede, not duplicate")

    notice = plan.get("notice_limit") or {}
    _require(notice.get("pre_window_is_bounded_by_notice") is True, "notice bound declared")
    _require(notice.get("on_short_notice") == "RECORD_ACTUAL_PRE_MINUTES_NEVER_PAD",
             "short notice must be recorded, never padded")
    _require(0 < int(notice.get("cadence_min") or 0) <= 60, "declared scan cadence")
    _require(notice.get("measurement") == "FIRST_SEEN_PER_SCHEDULED_EVENT_IS_A_LOWER_BOUND",
             "the notice period must be measured, since the cadence is derived from it")
    _require("gate" in (notice.get("notice_measured") or {}),
             "each venue must carry its measured notice or say it is unmeasured")

    offsets = plan.get("trade_open_offset_sec") or {}
    _require(int(offsets.get("okx", -1)) == 3600,
             "OKX opens an hour after listTime; zero here repeats the anchor defect")

    for role, relative in IMPLEMENTATION:
        target = repo_root / relative
        _require(target.is_file(), f"implementation missing: {relative}")
        bound = [f for f in (plan.get("implementation") or {}).get("files") or []
                 if f.get("role") == role]
        _require(len(bound) == 1, f"implementation binding for {role}")
        _require(bound[0].get("sha256") == _sha256_file(target),
                 f"implementation changed since the plan was issued: {relative}")

    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write-plan", action="store_true")
    actions.add_argument("--plan-check", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args(argv)

    try:
        if args.write_plan:
            if not args.generated_at_utc:
                raise ForwardDepthPlanError("--generated-at-utc is required")
            plan = build_plan(generated_at_utc=args.generated_at_utc)
            path = REPO_ROOT / PLAN_RELATIVE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            )
            print(json.dumps({"status": "PLAN_WRITTEN", "path": str(path),
                              "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
                              "execution_performed": False}, ensure_ascii=False))
            return 0
        path = REPO_ROOT / PLAN_RELATIVE_PATH
        if not path.is_file():
            raise ForwardDepthPlanError(f"the plan is not present: {path}")
        validate_plan(json.loads(path.read_text(encoding="utf-8")))
        print(json.dumps({"status": "PLAN_OK", "plan_id": PLAN_ID}, ensure_ascii=False))
        return 0
    except ForwardDepthPlanError as exc:
        print(json.dumps({"status": "PLAN_BLOCKED",
                          "reason": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
