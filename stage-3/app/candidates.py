"""Candidates, the selection rule and field status (stage 2: Candidates, The selection rule, Status).

A candidate is one value for one field supported by one excerpt of one page. The selection
rule ranks a field's candidates, and the field's value, citations and status follow from
that ranking alone, so the same candidates always give the same field.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .validation import Invalid, normalise_host, parse_timestamp

KINDS = ("own", "filing", "news", "aggregator")
AUTHORITY = {"own": 0, "filing": 0, "news": 1, "aggregator": 2}
PROVIDER_ORDER = {"nimble": 0, "tavily": 1, "kernel": 2, "browserbase": 3}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def page_kind(header_kind: str | None, url: str, domain: str) -> str:
    """The page's kind: its `Kind` header when listed, else `own` for the company's host, else `aggregator`."""
    if header_kind in KINDS:
        return header_kind
    return "own" if normalise_host(urlparse(url).hostname or "") == domain else "aggregator"


def published_at(header_value: str | None) -> str | None:
    """The page's publication time as an RFC 3339 string with a numeric offset, or None."""
    if header_value is None:
        return None
    try:
        moment = parse_timestamp(header_value)
    except Invalid:
        return None
    return moment.isoformat()


def _rank_key(candidate: dict):
    """Sorts ascending from the highest-ranked candidate."""
    kind = candidate["kind"]
    authority = AUTHORITY.get(kind, AUTHORITY["aggregator"])
    stamp = candidate["published_at"]
    # A candidate without a publication time ranks below every one of its authority that has one.
    recency = (1, timedelta(0)) if stamp is None else (0, -(parse_timestamp(stamp) - _EPOCH))
    value = candidate["value"]
    if isinstance(value, str):
        value = value.strip()
    return (authority, recency[0], recency[1], candidate["url"],
            PROVIDER_ORDER.get(candidate["provider"], len(PROVIDER_ORDER)), value)


def rank(candidates: list[dict]) -> list[dict]:
    """The candidates in rank order, the selected one first."""
    return sorted(candidates, key=_rank_key)


def build_field(candidates: list[dict]) -> dict:
    """A field from its candidates: selected value, status, citations and the ranked candidates."""
    if not candidates:
        return {"value": None, "status": "unknown", "citations": [], "candidates": []}
    ranked = [dict(c) for c in rank(candidates)]
    for index, candidate in enumerate(ranked):
        candidate["selected"] = index == 0
    value = ranked[0]["value"]
    citations = [{"url": c["url"], "excerpt": c["excerpt"], "provider": c["provider"]}
                 for c in ranked if c["value"] == value]
    contested = any(c["value"] != value for c in ranked)
    return {"value": value, "status": "contested" if contested else "known",
            "citations": citations, "candidates": ranked}


def make_candidate(value, url: str, excerpt: str, provider: str, kind: str | None,
                   published: str | None, retrieved_at: str) -> dict:
    return {"value": value, "url": url, "excerpt": excerpt, "provider": provider, "kind": kind,
            "published_at": published, "retrieved_at": retrieved_at, "selected": False}
