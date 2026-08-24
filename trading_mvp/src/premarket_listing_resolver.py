"""Resolve official spot-listing timestamps for pre-market perpetual events.

The collector's instrument metadata and receive-time observations are useful
proxies, but neither is an official listing announcement.  This module keeps
those sources separate: an event becomes ``official`` only when a grounded
Bybit, OKX, or Gate announcement provides an explicit spot-trading timestamp
and an unambiguous contract/pair identity match.

The parser is fixture-friendly and deterministic.  Network fetching remains a
separate concern owned by the visible automation; this module only consumes
already captured public announcement payloads or bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA = "trading_mvp_premarket_official_listing_resolver_v1"
PARSER_VERSION = "premarket-official-t0-v1"
VENUES = ("bybit", "okx", "gate")
SOURCE_CLASS_OFFICIAL = "official"
SOURCE_CLASS_PROXY = "proxy"

_OFFICIAL_HOSTS = {
    "bybit": ("bybit.com", "bybit-exchange.github.io"),
    "okx": ("okx.com", "okx-digital.com"),
    "gate": ("gate.com", "gate.io", "gateio.ws"),
}
_PLACEHOLDER_MARKERS = ("...", "…", "<listing", "{listing", "todo", "tbd")
_CONTEXT_MARKERS = (
    "spot",
    "listing",
    "trading",
    "trade",
    "open",
    "start",
    "launch",
    "go live",
    "will list",
)
_OFFICIAL_TIMESTAMP_KEYS = {
    "official_spot_listing_ts",
    "officialspotlistingts",
    "official_spot_listing_time",
    "officialspotlistingtime",
    "spot_listing_ts",
    "spotlistingts",
    "spot_listing_time",
    "spotlistingtime",
    "spot_trading_start",
    "spottradingstart",
    "spot_trading_start_time",
    "spottradingstarttime",
    "spot_trade_start",
    "spottradestart",
    "spot_trade_start_time",
    "spottradestarttime",
    "spot_open_time",
    "spotopentime",
    "trading_start_at",
    "tradingstartat",
    "listing_time",
    "listingtime",
    "t0",
}
_ANNOUNCEMENT_TIMESTAMP_KEYS = {
    "announcement_ts",
    "announcementts",
    "announcement_time",
    "announcementtime",
    "published_at",
    "publishedat",
    "publish_time",
    "publishtime",
    "published_ts",
    "publishedts",
    "created_at",
    "createdat",
}
_CONTRACT_KEYS = {
    "premarket_contract_id",
    "premarketcontractid",
    "pre_market_contract_id",
    "pre_market_contract",
    "premarketcontract",
    "contract_id",
    "contractid",
    "contract",
    "inst_id",
    "instid",
    "symbol",
    "symbols",
    "contract_ids",
    "contractids",
}
_SPOT_KEYS = {
    "spot_symbol",
    "spotsymbol",
    "spot_pair",
    "spotpair",
    "trading_pair",
    "tradingpair",
    "pair",
    "base_quote",
    "basequote",
}
_BASE_KEYS = {"base", "base_coin", "basecoin", "base_ccy", "baseccy"}
_QUOTE_KEYS = {"quote", "quote_coin", "quotecoin", "quote_ccy", "quoteccy"}


class OfficialListingAnnouncementError(ValueError):
    """Raised when an announcement is not safe to classify as official."""


@dataclass(frozen=True)
class OfficialListingAnnouncement:
    venue: str
    source_url: str
    title: str
    announcement_ts: float | None
    official_spot_listing_ts: float
    spot_symbol: str
    base: str
    quote: str
    contract_aliases: tuple[str, ...] = ()
    confidence: str = "high"
    announcement_id: str = ""
    parser_version: str = PARSER_VERSION
    source_class: str = SOURCE_CLASS_OFFICIAL
    evidence_class: str = "OFFICIAL_LISTING_ANNOUNCEMENT"
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract_aliases"] = list(self.contract_aliases)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OfficialListingAnnouncement":
        aliases = payload.get("contract_aliases") or payload.get("contract_aliases_normalized") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        return cls(
            venue=_normalise_venue(payload.get("venue") or payload.get("exchange")),
            source_url=str(payload.get("source_url") or payload.get("official_source_url") or ""),
            title=str(payload.get("title") or ""),
            announcement_ts=_parse_timestamp(payload.get("announcement_ts")),
            official_spot_listing_ts=float(payload["official_spot_listing_ts"]),
            spot_symbol=str(payload.get("spot_symbol") or "").upper(),
            base=str(payload.get("base") or "").upper(),
            quote=str(payload.get("quote") or "").upper(),
            contract_aliases=tuple(str(value).upper() for value in aliases if str(value).strip()),
            confidence=str(payload.get("confidence") or "high"),
            announcement_id=str(payload.get("announcement_id") or ""),
            parser_version=str(payload.get("parser_version") or PARSER_VERSION),
            source_class=str(payload.get("source_class") or SOURCE_CLASS_OFFICIAL),
            evidence_class=str(payload.get("evidence_class") or "OFFICIAL_LISTING_ANNOUNCEMENT"),
            raw=dict(payload.get("raw") or {}),
        )


def _normalise_venue(value: Any) -> str:
    venue = str(value or "").strip().lower()
    if venue == "gateio":
        venue = "gate"
    if venue not in VENUES:
        raise OfficialListingAnnouncementError(f"unsupported venue: {value}")
    return venue


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _is_placeholder(value: Any) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _as_timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = float(value)
        if abs(parsed) >= 10_000_000_000:
            parsed /= 1000.0
        return parsed if parsed > 0 else None
    text = str(value).strip()
    if not text or _is_placeholder(text):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        parsed = float(text)
        if abs(parsed) >= 10_000_000_000:
            parsed /= 1000.0
        return parsed if parsed > 0 else None
    iso = text.replace("Z", "+00:00")
    try:
        parsed_dt = datetime.fromisoformat(iso)
    except ValueError:
        parsed_dt = None
    if parsed_dt is not None:
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        return parsed_dt.astimezone(timezone.utc).timestamp()
    normalised = re.sub(r"\s+(UTC|GMT)$", "", text, flags=re.IGNORECASE)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%B %d, %Y %H:%M:%S",
        "%B %d, %Y %H:%M",
        "%B %d, %Y, %H:%M:%S",
        "%B %d, %Y, %H:%M",
        "%d %B %Y %H:%M:%S",
        "%d %B %Y %H:%M",
    ):
        try:
            parsed_dt = datetime.strptime(normalised, fmt).replace(tzinfo=timezone.utc)
            return parsed_dt.timestamp()
        except ValueError:
            continue
    return None


def _parse_timestamp(value: Any) -> float | None:
    return _as_timestamp(value)


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _find_value(payload: Mapping[str, Any], allowed_keys: set[str]) -> tuple[Any, str] | tuple[None, None]:
    for mapping in _walk_mappings(payload):
        for raw_key, value in mapping.items():
            if _key(raw_key) in allowed_keys and value not in (None, ""):
                return value, str(raw_key)
    return None, None


def _flatten_values(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, Mapping):
        values: list[str] = []
        for key in ("id", "symbol", "contract", "instId", "name"):
            if key in value:
                values.extend(_flatten_values(value[key]))
        return values
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for child in value:
            values.extend(_flatten_values(child))
        return values
    return [str(value).strip()]


def _pair_parts(value: Any, *, quote_hint: str = "") -> tuple[str, str]:
    text = str(value or "").strip().upper()
    if not text:
        return "", ""
    cleaned = text.replace("/", "-").replace("_", "-")
    cleaned = re.sub(r"-(?:SWAP|PERPETUAL|PERP)$", "", cleaned)
    pieces = [part for part in cleaned.split("-") if part]
    if len(pieces) >= 2:
        return pieces[0], pieces[1]
    quote = str(quote_hint or "").upper()
    for candidate in (quote, "USDT", "USDC", "USD"):
        if candidate and text.endswith(candidate) and len(text) > len(candidate):
            return text[: -len(candidate)], candidate
    return text, quote


def _identity_forms(value: Any) -> set[str]:
    text = str(value or "").strip().upper()
    if not text:
        return set()
    text = text.replace("/", "-").replace(":", "-")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[-_](?:SWAP|PERPETUAL|PERP)$", "", text)
    forms = {text, text.replace("-", "_").replace("_", "-")}
    forms.add(text.replace("-", ""))
    return {item for item in forms if item}


def _source_url(payload: Mapping[str, Any]) -> str:
    value, _ = _find_value(payload, {"url", "sourceurl", "officialsourceurl", "announcementurl"})
    url = str(value or "").strip()
    if not url:
        raise OfficialListingAnnouncementError("official_source_url_missing")
    if _is_placeholder(url):
        raise OfficialListingAnnouncementError("official_source_url_placeholder")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise OfficialListingAnnouncementError("official_source_url_must_be_https")
    return url


def _validate_source_url(venue: str, url: str) -> None:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not any(host == suffix or host.endswith("." + suffix) for suffix in _OFFICIAL_HOSTS[venue]):
        raise OfficialListingAnnouncementError(f"official_source_host_mismatch:{venue}:{host}")


def _text_listing_timestamp(text: str) -> tuple[float | None, str | None]:
    body = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    if _is_placeholder(body):
        return None, "placeholder_timestamp"
    context = "|".join(re.escape(marker) for marker in _CONTEXT_MARKERS)
    iso_pattern = re.compile(
        rf"(?P<stamp>20\d{{2}}-\d{{2}}-\d{{2}}[T ]\d{{2}}:\d{{2}}(?::\d{{2}})?(?:\.\d+)?\s*(?:Z|UTC|GMT|[+-]\d{{2}}:?\d{{2}}))",
        re.IGNORECASE,
    )
    month_pattern = re.compile(
        rf"(?P<date>(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{{1,2}},\s*20\d{{2}})\s*(?:,?\s*(?:at|@)\s*)?(?P<clock>\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\s*(?P<zone>UTC|GMT|Z)",
        re.IGNORECASE,
    )
    dmy_pattern = re.compile(
        rf"(?P<date>\d{{1,2}}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{{2}})\s*(?:,?\s*(?:at|@)\s*)?(?P<clock>\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\s*(?P<zone>UTC|GMT|Z)",
        re.IGNORECASE,
    )
    for pattern in (iso_pattern, month_pattern, dmy_pattern):
        for match in pattern.finditer(body):
            start, end = match.span()
            nearby = body[max(0, start - 100) : min(len(body), end + 100)].lower()
            if not re.search(context, nearby):
                continue
            if "stamp" in match.groupdict():
                stamp = _parse_timestamp(match.group("stamp"))
            else:
                stamp = _parse_timestamp(f"{match.group('date')} {match.group('clock')}")
            if stamp is not None:
                return stamp, "exact_utc_text"
    return None, None


def parse_official_listing_announcement(
    venue: str,
    payload: Mapping[str, Any] | str,
) -> OfficialListingAnnouncement:
    """Parse one grounded official announcement payload.

    The function intentionally refuses publish time, polling time, ellipsis,
    and exchange instrument ``launchTime`` fields as substitutes for spot t0.
    """

    venue_key = _normalise_venue(venue)
    source_payload: Mapping[str, Any]
    if isinstance(payload, Mapping):
        source_payload = payload
    else:
        source_payload = {"body": str(payload)}

    url = _source_url(source_payload)
    _validate_source_url(venue_key, url)
    title_value, _ = _find_value(source_payload, {"title", "headline", "subject"})
    title = str(title_value or "").strip()
    body_value, _ = _find_value(source_payload, {"body", "content", "text", "description", "html"})
    body = str(body_value or "")

    listing_value, listing_key = _find_value(source_payload, _OFFICIAL_TIMESTAMP_KEYS)
    listing_ts = _parse_timestamp(listing_value)
    confidence = "high" if listing_ts is not None else ""
    if listing_value is not None and listing_ts is None and _is_placeholder(listing_value):
        raise OfficialListingAnnouncementError("placeholder_timestamp")
    if listing_ts is None:
        listing_ts, text_reason = _text_listing_timestamp(" ".join(part for part in (title, body) if part))
        if text_reason == "placeholder_timestamp":
            raise OfficialListingAnnouncementError(text_reason)
        confidence = "high" if listing_ts is not None else ""
    if listing_ts is None:
        raise OfficialListingAnnouncementError("official_spot_listing_timestamp_missing")

    published_value, _ = _find_value(source_payload, _ANNOUNCEMENT_TIMESTAMP_KEYS)
    announcement_ts = _parse_timestamp(published_value)
    if published_value is not None and announcement_ts is None and _is_placeholder(published_value):
        raise OfficialListingAnnouncementError("placeholder_announcement_timestamp")

    alias_value, _ = _find_value(source_payload, _CONTRACT_KEYS)
    aliases: list[str] = []
    for value in _flatten_values(alias_value):
        if value and value.upper() not in {item.upper() for item in aliases}:
            aliases.append(value.upper())

    spot_value, _ = _find_value(source_payload, _SPOT_KEYS)
    spot_symbol = str(spot_value or "").strip().upper()
    base_value, _ = _find_value(source_payload, _BASE_KEYS)
    quote_value, _ = _find_value(source_payload, _QUOTE_KEYS)
    base, quote = _pair_parts(spot_symbol, quote_hint=str(quote_value or ""))
    if not base and base_value:
        base = str(base_value).strip().upper()
    if not quote and quote_value:
        quote = str(quote_value).strip().upper()
    if not spot_symbol and base and quote:
        spot_symbol = f"{base}_{quote}" if venue_key == "gate" else f"{base}-{quote}"
    if not aliases and spot_symbol:
        aliases.append(spot_symbol)
    if not spot_symbol or not base or not quote:
        raise OfficialListingAnnouncementError("spot_identity_missing")
    if not aliases:
        raise OfficialListingAnnouncementError("premarket_contract_identity_missing")
    announcement_id_value, _ = _find_value(source_payload, {"id", "announcementid", "announcement_id"})
    raw = json.loads(json.dumps(dict(source_payload), ensure_ascii=False, default=str))
    return OfficialListingAnnouncement(
        venue=venue_key,
        source_url=url,
        title=title,
        announcement_ts=announcement_ts,
        official_spot_listing_ts=float(listing_ts),
        spot_symbol=spot_symbol,
        base=base,
        quote=quote,
        contract_aliases=tuple(aliases),
        confidence=confidence,
        announcement_id=str(announcement_id_value or ""),
        raw=raw,
    )


def fetch_public_announcement(
    venue: str,
    url: str,
    *,
    session: Any | None = None,
    timeout_sec: float = 10.0,
    max_bytes: int = 1_000_000,
    metadata: Mapping[str, Any] | None = None,
) -> OfficialListingAnnouncement:
    """Fetch one caller-supplied official page with strict public bounds.

    This is deliberately one-shot: it does not discover URLs, paginate an
    exchange site, or create a background worker.  The visible automation may
    call it with a URL already obtained from an official announcement index.
    Redirects are rejected so the stored source URL remains auditable.
    """

    venue_key = _normalise_venue(venue)
    _validate_source_url(venue_key, url)
    if timeout_sec <= 0 or max_bytes <= 0:
        raise OfficialListingAnnouncementError("invalid_public_fetch_bounds")
    owned_session = session is None
    if owned_session:
        try:
            import requests  # type: ignore
        except ImportError as exc:
            raise OfficialListingAnnouncementError(f"requests_dependency_missing:{exc}") from exc
        session = requests.Session()
    try:
        try:
            response = session.get(  # type: ignore[union-attr]
                url,
                timeout=float(timeout_sec),
                allow_redirects=False,
                headers={"User-Agent": "ZolotyayLopata-research/1.0"},
            )
        except Exception as exc:
            raise OfficialListingAnnouncementError(f"official_fetch_failed:{type(exc).__name__}:{exc}") from exc
        status = int(getattr(response, "status_code", getattr(response, "status", 0)) or 0)
        if status != 200:
            raise OfficialListingAnnouncementError(f"official_fetch_http_status:{status}")
        final_url = str(getattr(response, "url", url) or url)
        if final_url != url:
            raise OfficialListingAnnouncementError("official_fetch_redirect_rejected")
        content = getattr(response, "content", None)
        if content is None:
            text = str(getattr(response, "text", ""))
            content = text.encode("utf-8")
        if not isinstance(content, bytes):
            content = bytes(content)
        if len(content) > max_bytes:
            raise OfficialListingAnnouncementError("official_fetch_response_too_large")
        encoding = str(getattr(response, "encoding", None) or "utf-8")
        try:
            body = content.decode(encoding, errors="replace")
        except LookupError:
            body = content.decode("utf-8", errors="replace")
        payload = dict(metadata or {})
        payload.update({"source_url": url, "body": body})
        return parse_official_listing_announcement(venue_key, payload)
    finally:
        if owned_session:
            close = getattr(session, "close", None)
            if callable(close):
                close()


def _coerce_announcement(value: OfficialListingAnnouncement | Mapping[str, Any]) -> OfficialListingAnnouncement:
    if isinstance(value, OfficialListingAnnouncement):
        return value
    if not isinstance(value, Mapping):
        raise OfficialListingAnnouncementError("invalid_announcement_type")
    return OfficialListingAnnouncement.from_dict(value)


def _contract_value(contract: Any, *names: str) -> Any:
    if isinstance(contract, Mapping):
        for name in names:
            if name in contract and contract[name] not in (None, ""):
                return contract[name]
        return None
    for name in names:
        value = getattr(contract, name, None)
        if value not in (None, ""):
            return value
    return None


def _announcement_match_score(contract: Mapping[str, Any], announcement: OfficialListingAnnouncement) -> int:
    contract_id = _contract_value(contract, "contract_id", "premarket_contract_id", "symbol")
    spot_symbol = _contract_value(contract, "spot_symbol", "spotSymbol", "pair")
    contract_forms = _identity_forms(contract_id)
    announcement_forms = set().union(*(_identity_forms(alias) for alias in announcement.contract_aliases)) if announcement.contract_aliases else set()
    spot_forms = _identity_forms(spot_symbol)
    announcement_spot_forms = _identity_forms(announcement.spot_symbol)
    score = 0
    if contract_forms & announcement_forms:
        score = max(score, 4)
    if spot_forms & announcement_spot_forms:
        score = max(score, 3)
    contract_base, contract_quote = _pair_parts(spot_symbol or contract_id, quote_hint=str(_contract_value(contract, "quote") or ""))
    if contract_base and contract_quote and contract_base == announcement.base and contract_quote == announcement.quote:
        score = max(score, 2)
    return score


def resolve_contract_listing(
    contract: Any,
    announcements: Iterable[OfficialListingAnnouncement | Mapping[str, Any]],
    *,
    detection_ts: float | None = None,
) -> dict[str, Any]:
    """Attach one official/proxy classification to a contract identity."""

    if isinstance(contract, Mapping):
        result = dict(contract)
    elif hasattr(contract, "as_dict"):
        result = dict(contract.as_dict())
    else:
        result = {
            name: getattr(contract, name)
            for name in ("venue", "contract_id", "spot_symbol", "base", "quote", "phase", "lifecycle_status")
            if hasattr(contract, name)
        }
    venue = _normalise_venue(_contract_value(result, "venue", "exchange"))
    result["venue"] = venue
    result["instrument_official_spot_listing_ts"] = result.get("official_spot_listing_ts")
    result["instrument_announcement_ts"] = result.get("announcement_ts")
    result["official_spot_listing_ts"] = None
    result["announcement_ts"] = None
    result["official_source_url"] = None
    result["official_listing_confidence"] = None
    result["official_announcement_id"] = None
    result["proxy_spot_listing_ts"] = None
    candidates: list[tuple[int, OfficialListingAnnouncement]] = []
    for raw_announcement in announcements:
        announcement = _coerce_announcement(raw_announcement)
        if announcement.venue != venue:
            continue
        score = _announcement_match_score(result, announcement)
        if score:
            candidates.append((score, announcement))
    max_score = max((score for score, _ in candidates), default=0)
    best = [announcement for score, announcement in candidates if score == max_score]
    # Identical duplicates are harmless; conflicting official times/URLs are not.
    unique_best: dict[tuple[float, str], OfficialListingAnnouncement] = {
        (item.official_spot_listing_ts, item.source_url): item for item in best
    }
    if len(unique_best) == 1:
        announcement = next(iter(unique_best.values()))
        result.update(
            {
                "official_spot_listing_ts": announcement.official_spot_listing_ts,
                "announcement_ts": announcement.announcement_ts,
                "official_source_url": announcement.source_url,
                "official_listing_confidence": announcement.confidence,
                "official_announcement_id": announcement.announcement_id,
                "listing_source_class": SOURCE_CLASS_OFFICIAL,
                "listing_resolution_status": "official",
                "listing_resolution_parser_version": announcement.parser_version,
                "listing_resolution_evidence_class": announcement.evidence_class,
                "acceptance_eligible": True,
            }
        )
        return result
    if len(unique_best) > 1:
        result.update(
            {
                "listing_source_class": "unresolved",
                "listing_resolution_status": "ambiguous",
                "listing_resolution_reason": "conflicting_official_matches",
                "acceptance_eligible": False,
            }
        )
        return result
    proxy_ts = _parse_timestamp(detection_ts)
    if proxy_ts is not None:
        result.update(
            {
                "proxy_spot_listing_ts": proxy_ts,
                "listing_source_class": SOURCE_CLASS_PROXY,
                "listing_resolution_status": "proxy_only",
                "listing_resolution_reason": "detection_time_without_official_announcement",
                "acceptance_eligible": False,
            }
        )
    else:
        result.update(
            {
                "listing_source_class": "unresolved",
                "listing_resolution_status": "unresolved",
                "listing_resolution_reason": "no_identity_matched_official_announcement",
                "acceptance_eligible": False,
            }
        )
    return result


def _read_json_rows(source: Path | Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], bytes]:
    if isinstance(source, Path):
        data = source.read_bytes()
        text = data.decode("utf-8")
        rows: list[dict[str, Any]] = []
        stripped = text.strip()
        if not stripped:
            return rows, data
        if stripped.startswith("["):
            value = json.loads(stripped)
            if not isinstance(value, list):
                raise OfficialListingAnnouncementError("rows_json_must_be_list")
            rows = [dict(row) for row in value]
        else:
            for line_number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError as exc:
                    raise OfficialListingAnnouncementError(f"invalid_jsonl_line:{line_number}") from exc
                if not isinstance(value, Mapping):
                    raise OfficialListingAnnouncementError(f"jsonl_row_not_object:{line_number}")
                rows.append(dict(value))
        return rows, data
    rows = [dict(row) for row in source]
    data = ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)).encode("utf-8")
    return rows, data


def _read_announcements(source: Path | Iterable[OfficialListingAnnouncement | Mapping[str, Any]]) -> list[OfficialListingAnnouncement]:
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
        if source.suffix.lower() == ".jsonl":
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            parsed = json.loads(text)
            values = parsed if isinstance(parsed, list) else [parsed]
        return [_coerce_announcement(value) for value in values]
    return [_coerce_announcement(value) for value in source]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def materialize_premarket_events(
    raw_events: Path | Iterable[Mapping[str, Any]],
    announcements: Path | Iterable[OfficialListingAnnouncement | Mapping[str, Any]],
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize official/proxy resolution without modifying raw events."""

    rows, raw_bytes = _read_json_rows(raw_events)
    announcement_rows = _read_announcements(announcements)
    # Stable ordering makes the result independent of announcement arrival order.
    announcement_rows.sort(key=lambda item: (item.venue, item.source_url, item.official_spot_listing_ts, item.announcement_id))
    materialized: list[dict[str, Any]] = []
    counts = {"matched_official": 0, "proxy_only": 0, "ambiguous": 0, "unresolved": 0}
    for row in rows:
        detection_ts = row.get("proxy_spot_listing_ts") or row.get("spot_listing_detection_ts")
        resolved = resolve_contract_listing(row, announcement_rows, detection_ts=detection_ts)
        enriched = dict(row)
        for key in (
            "official_spot_listing_ts",
            "announcement_ts",
            "official_source_url",
            "official_listing_confidence",
            "official_announcement_id",
            "proxy_spot_listing_ts",
        ):
            if key in row:
                enriched[f"instrument_{key}"] = row[key]
            enriched[key] = resolved.get(key)
        for key in (
            "listing_source_class",
            "listing_resolution_status",
            "listing_resolution_reason",
            "listing_resolution_parser_version",
            "listing_resolution_evidence_class",
            "acceptance_eligible",
        ):
            if key in resolved:
                enriched[key] = resolved[key]
        materialized.append(enriched)
        status = str(resolved.get("listing_resolution_status"))
        if status == "official":
            counts["matched_official"] += 1
        elif status == "proxy_only":
            counts["proxy_only"] += 1
        elif status == "ambiguous":
            counts["ambiguous"] += 1
        else:
            counts["unresolved"] += 1

    encoded = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in materialized
    )
    output_sha = _sha256_bytes(encoded)
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(output_path.name + ".tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, output_path)
    summary = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "rows_written": len(materialized),
        **counts,
        "raw_sha256": _sha256_bytes(raw_bytes),
        "output_sha256": output_sha,
    }
    summary["result_hash"] = _sha256_bytes(json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if output_path is not None:
        summary["output_path"] = str(output_path)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize official pre-market listing timestamps")
    parser.add_argument("--raw-events", required=True, type=Path)
    parser.add_argument("--announcements", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = materialize_premarket_events(args.raw_events, args.announcements, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
