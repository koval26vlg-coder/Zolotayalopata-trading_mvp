"""Ask Bitget the question the probe plan declares, and record what it answered.

This is the only part of the crypto-identity work that touches the network, and it is
kept separate from everything that reasons about the answer for exactly that reason: the
proposer can be read, tested and argued about without anyone wondering what it fetched.

What it does is narrow on purpose. It validates the plan first and takes the venue, the
endpoint, the bases and every bound from it rather than from its own constants, so the
thing that was authorised is the thing that runs. One request per base, spaced by the
declared interval, with the declared timeout; no pagination, no discovery, no retry storm.

What it will not do is decide anything. Each response becomes a ``VenueAssetEvidence``
and goes to ``propose_crypto_identity``, whose output is a proposal requiring review. The
result artifact records the raw response hash beside each verdict, so a reader can check
the reasoning against the bytes it was based on rather than trusting this summary.

The mapping from Bitget's fields is the part most likely to be wrong, so it is stated
plainly rather than buried: ``rechargeable`` is deposit, ``withdrawable`` is withdrawal,
and both arrive as the strings "true"/"false" rather than as booleans. A field that is
missing or says anything else is read as disabled - the question is whether the venue
*publishes* that the asset moves, and silence is not publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from listing_spot_crypto_identity import (
    ChainListing,
    CryptoIdentityProposal,
    VenueAssetEvidence,
    propose_crypto_identity,
)
from listing_spot_crypto_identity_plan import (
    PLAN_RELATIVE_PATH,
    REPO_ROOT,
    CryptoIdentityPlanError,
    validate_plan,
)

RESULT_SCHEMA = "trading_mvp_listing_spot_crypto_identity_probe_result_v1"
# Named after the plan the run was made under. A fixed filename meant the second probe
# silently overwrote the first one's record, and the only reason that evidence survived
# was that it had already been committed.
RESULT_DIRECTORY = "docs/agent-log/crypto-identity-probe-results"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
USER_AGENT = "ZolotyayLopata-research/1.0 (public metadata probe)"

Fetcher = Callable[[str], bytes]


class ProbeError(RuntimeError):
    """The probe cannot proceed, or cannot honestly describe what it did."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _flag(value: Any) -> bool:
    """Bitget sends "true"/"false" as strings; anything else counts as disabled."""
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def http_get(url: str, *, timeout_sec: int) -> bytes:
    """One GET, bounded in time and in size, with no redirect off the declared host."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ProbeError(f"refusing a non-https request: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            if urllib.parse.urlparse(response.geturl()).hostname != parsed.hostname:
                # A redirect to another host would silently change who is speaking.
                raise ProbeError(f"response came from another host: {response.geturl()}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ProbeError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProbeError("response exceeded the readable bound")
    return raw


def evidence_from_response(
    raw: bytes, *, base: str, exchange: str, source_url: str, observed_at_utc: str
) -> VenueAssetEvidence:
    """Read one Bitget coin record into evidence, or refuse to read it at all."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProbeError(f"unreadable response for {base}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProbeError(f"response for {base} is not an object")
    if str(payload.get("code")) != "00000":
        raise ProbeError(f"venue refused the request for {base}: {payload.get('msg')!r}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ProbeError(f"response for {base} carries no data list")

    matching = [
        row for row in rows
        if isinstance(row, Mapping) and str(row.get("coin", "")).strip().upper() == base
    ]
    if len(matching) > 1:
        # Two records for one ticker is an ambiguity, not something to pick from.
        raise ProbeError(f"venue returned {len(matching)} records for {base}")

    chains: list[ChainListing] = []
    for row in matching:
        for chain in row.get("chains") or []:
            if not isinstance(chain, Mapping):
                continue
            chains.append(
                ChainListing(
                    network=str(chain.get("chain") or "").strip(),
                    contract_address=(str(chain.get("contractAddress") or "").strip() or None),
                    deposit_enabled=_flag(chain.get("rechargeable")),
                    withdraw_enabled=_flag(chain.get("withdrawable")),
                )
            )
    return VenueAssetEvidence(
        exchange=exchange,
        base=base,
        source_url=source_url,
        observed_at_utc=observed_at_utc,
        chains=tuple(chains),
    )


def _describe(proposal: CryptoIdentityProposal | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    return {
        "exchange": proposal.exchange,
        "base": proposal.base,
        "proposed_class": proposal.proposed_class,
        "supporting_networks": list(proposal.supporting_networks),
        "evidence": list(proposal.evidence),
        "requires_human_review": proposal.requires_human_review,
    }


def run_probe(
    *,
    plan_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
    fetch: Fetcher | None = None,
    now: Callable[[], datetime] = _utc_now,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute the declared probe and return the result artifact."""
    path = plan_path or (repo_root / PLAN_RELATIVE_PATH)
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_plan(plan, repo_root=repo_root)

    probe = plan["probe"]
    exchange = str(probe["venue"])
    bases: Sequence[str] = list(probe["bases"])
    timeout_sec = int(probe["request_timeout_sec"])
    interval = int(probe["min_interval_between_requests_sec"])
    if len(bases) > int(probe["max_requests"]):
        raise ProbeError("the plan's own base list exceeds its request bound")

    getter = fetch or (lambda url: http_get(url, timeout_sec=timeout_sec))
    started = now()
    observations: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []

    for index, base in enumerate(bases):
        if index:
            sleep(interval)
        url = f"{probe['endpoint']}?{urllib.parse.urlencode({'coin': base})}"
        observed_at = _iso(now())
        record: dict[str, Any] = {"base": base, "request_url": url, "observed_at_utc": observed_at}
        try:
            raw = getter(url)
        except ProbeError as exc:
            record.update({"status": "REQUEST_FAILED", "reason": str(exc)})
            observations.append(record)
            continue
        record["response_sha256"] = hashlib.sha256(raw).hexdigest()
        record["response_bytes"] = len(raw)
        try:
            evidence = evidence_from_response(
                raw, base=base, exchange=exchange, source_url=url, observed_at_utc=observed_at
            )
        except ProbeError as exc:
            record.update({"status": "UNREADABLE", "reason": str(exc)})
            observations.append(record)
            continue

        record["chains"] = [
            {
                "network": chain.network,
                "contract_address": chain.contract_address,
                "deposit_enabled": chain.deposit_enabled,
                "withdraw_enabled": chain.withdraw_enabled,
                "movable": chain.is_movable,
            }
            for chain in evidence.chains
        ]
        proposal = propose_crypto_identity(evidence, now=now())
        record["status"] = "PROPOSED" if proposal else "NOT_ESTABLISHED"
        record["proposal"] = _describe(proposal)
        if proposal is not None:
            proposals.append(record["proposal"])
        observations.append(record)

    finished = now()
    return {
        "schema": RESULT_SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "venue": exchange,
        "started_at_utc": _iso(started),
        "finished_at_utc": _iso(finished),
        "requests_made": sum(1 for row in observations if "response_sha256" in row),
        "bases_requested": list(bases),
        "observations": observations,
        "proposals": proposals,
        "registry_edited": False,
        "acceptance_decision": "NONE_IDENTITY_EVIDENCE_ONLY",
        "human_review_required": True,
    }


def write_result(result: Mapping[str, Any], *, repo_root: Path = REPO_ROOT) -> Path:
    target = repo_root / RESULT_DIRECTORY / f"{result['plan_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--write-result", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_probe(plan_path=args.plan)
    except (ProbeError, CryptoIdentityPlanError, OSError, ValueError) as exc:
        print(json.dumps({"status": "PROBE_BLOCKED", "reason": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        return 1
    if args.write_result:
        result["result_path"] = str(write_result(result))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
