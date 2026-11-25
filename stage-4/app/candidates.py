"""Candidates, the selection rule and field status (stage 2: Candidates, The selection rule, Status).

A candidate is one value for one field supported by one excerpt of one page. The selection
rule ranks a field's candidates, and the field's value, citations and status follow from
that ranking alone, so the same candidates always give the same field.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from .support import ALL_FIELDS, TITLES
from .validation import Invalid, normalise_domain, normalise_host, parse_timestamp

KINDS = ("own", "filing", "news", "aggregator")
AUTHORITY = {"own": 0, "filing": 0, "news": 1, "aggregator": 2}
PROVIDER_ORDER = {"nimble": 0, "tavily": 1, "kernel": 2, "browserbase": 3}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def host_of(url: str) -> str:
    """The normalised host of a URL (empty when it has none)."""
    try:
        return normalise_host(urlparse(url.strip()).hostname or "")
    except ValueError:
        return ""


def registrant_of(header: dict, url: str) -> str:
    """The domain whose owner publishes the page: a valid `Registrant` line, else the host of its URL (stage 4)."""
    try:
        return normalise_domain(header["Registrant"])
    except (KeyError, Invalid):
        return host_of(url)


def is_lookalike(header: dict, url: str) -> bool:
    """A page that states `Kind: own` though its registrant is not the host of its own URL (stage 4)."""
    return header.get("Kind") == "own" and registrant_of(header, url) != host_of(url)


def page_kind(header: dict, url: str, domain: str) -> str:
    """The page's kind. A page is `own` for a company only when its registrant is the company's domain (stage 4).

    The `Kind` line decides when it is listed, else the page is `own` for the company's host and
    `aggregator` elsewhere; a page stating `Kind: own` that is not registered to the company is an aggregator.
    """
    header_kind = header.get("Kind")
    registered = registrant_of(header, url) == domain
    if header_kind in KINDS:
        return "aggregator" if header_kind == "own" and not registered else header_kind
    return "own" if host_of(url) == domain and registered else "aggregator"


def published_at(header_value: str | None) -> str | None:
    """The page's publication time as an RFC 3339 string with a numeric offset, or None."""
    if header_value is None:
        return None
    try:
        moment = parse_timestamp(header_value)
    except Invalid:
        return None
    return moment.isoformat()


_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def true_from_of(effective: str | None, published: str | None) -> str | None:
    """The date a page's evidence holds from (stage 3: Two times per value).

    The page's `Effective` header line when it is a valid `YYYY-MM-DD` date, else the UTC date of
    its publication time (an RFC 3339 string), else None.
    """
    if effective is not None and _DATE.fullmatch(effective.strip()):
        try:
            return date.fromisoformat(effective.strip()).isoformat()
        except ValueError:
            pass
    if published is None:
        return None
    try:
        return parse_timestamp(published).astimezone(timezone.utc).date().isoformat()
    except Invalid:
        return None


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


def _citation(candidate: dict) -> dict:
    return {"url": candidate["url"], "excerpt": candidate["excerpt"], "provider": candidate["provider"]}


def origin_of_candidate(candidate: dict) -> str:
    """A candidate's origin; one an earlier stage recorded has none, and takes the host of its URL."""
    return candidate.get("origin") or host_of(candidate["url"])


def _origins(candidates) -> list[str]:
    return sorted({origin_of_candidate(c) for c in candidates})


def _empty_field() -> dict:
    return {"value": None, "status": "unknown", "true_from": None, "learned_at": None, "citations": [],
            "candidates": [], "origins": [], "corroborated": False, "corroborated_since": None}


def build_field(candidates: list[dict]) -> dict:
    """A field from its candidates: selected value, status, citations and the ranked candidates.

    `learned_at` and `corroborated_since` of the field are not known here: the store sets them
    when a build completes.
    """
    if not candidates:
        return _empty_field()
    ranked = [dict(c) for c in rank(candidates)]
    for index, candidate in enumerate(ranked):
        candidate["selected"] = index == 0
    value = ranked[0]["value"]
    contested = any(c["value"] != value for c in ranked)
    return {"value": value, "status": "contested" if contested else "known",
            "true_from": ranked[0]["true_from"], "learned_at": None,
            "citations": [_citation(c) for c in ranked if c["value"] == value], "candidates": ranked,
            "origins": (origins := _origins(c for c in ranked if c["value"] == value)),
            "corroborated": len(origins) >= 2, "corroborated_since": None}


def build_executives(candidates: list[dict]) -> dict:
    """The `executives` field: the selection rule run separately over the candidates of each title."""
    by_title = {title: rank([c for c in candidates if c["title"] == title]) for title in TITLES}
    ranked, members, contested = [], [], False
    for title in TITLES:
        group = [dict(c) for c in by_title[title]]
        for index, candidate in enumerate(group):
            candidate["selected"] = index == 0
        if group:
            members.append((title, group[0]))
            contested = contested or any(c["value"] != group[0]["value"] for c in group)
        ranked.extend(group)
    if not members:
        return _empty_field()
    chosen_members = [(title, chosen["value"]) for title, chosen in members]
    belonging = [[c for c in ranked if (c["title"], c["value"]) == member] for member in chosen_members]
    stamps = [chosen["true_from"] for _, chosen in members]
    return {"value": [{"title": title, "name": chosen["value"]} for title, chosen in members],
            "status": "contested" if contested else "known",
            "true_from": None if None in stamps else max(stamps), "learned_at": None,
            "citations": [_citation(c) for title, chosen in members for c in ranked
                          if c["title"] == title and c["value"] == chosen["value"]],
            "candidates": ranked, "origins": _origins(c for group in belonging for c in group),
            "corroborated": all(len(_origins(group)) >= 2 for group in belonging), "corroborated_since": None}


def build_investors(candidates: list[dict]) -> dict:
    """The `investors` field: its members are the investor names with an own or filing candidate or two origins."""
    ranked = [dict(c) for c in rank(candidates)]
    by_name: dict[str, list[dict]] = {}
    for candidate in ranked:
        by_name.setdefault(candidate["value"], []).append(candidate)
    members = sorted(name for name, group in by_name.items()
                     if any(c["kind"] in ("own", "filing") for c in group) or len(_origins(group)) >= 2)
    for candidate in ranked:
        candidate["selected"] = candidate["value"] in members
    if not members:
        return {**_empty_field(), "candidates": ranked}
    froms = []
    for name in members:
        stamps = [c["true_from"] for c in by_name[name] if c["true_from"] is not None]
        froms.append(min(stamps) if stamps else None)
    return {"value": members, "status": "known", "true_from": None if None in froms else max(froms),
            "learned_at": None, "citations": [_citation(c) for name in members for c in by_name[name]],
            "candidates": ranked, "origins": _origins(c for name in members for c in by_name[name]),
            "corroborated": all(len(_origins(by_name[name])) >= 2 for name in members),
            "corroborated_since": None}


def build_any(name: str, candidates: list[dict]) -> dict:
    if name == "executives":
        return build_executives(candidates)
    return build_investors(candidates) if name == "investors" else build_field(candidates)


def build_all(candidates: dict[str, list[dict]]) -> dict:
    """Every field (the eight of stage 4) from its candidates."""
    return {name: build_any(name, candidates.get(name, [])) for name in ALL_FIELDS}


def empty_fields() -> dict:
    return build_all({})


def make_candidate(value, url: str, excerpt: str, provider: str, kind: str | None, published: str | None,
                   retrieved_at: str, true_from: str | None = None, title: str | None = None,
                   origin: str | None = None) -> dict:
    candidate = {} if title is None else {"title": title}
    candidate.update({"value": value, "url": url, "excerpt": excerpt, "provider": provider, "kind": kind,
                      "published_at": published, "true_from": true_from, "retrieved_at": retrieved_at,
                      "learned_at": retrieved_at, "selected": False,
                      "origin": origin or host_of(url)})
    return candidate


def candidate_key(name: str, candidate: dict) -> list:
    """What makes two candidates the same one for `learned_at`: field (and title), value, URL, provider."""
    return [name, candidate.get("title"), candidate["value"], candidate["url"], candidate["provider"]]
