"""Stage-2 oracle: candidates, the selection rule and status, derived from the analyst corpus
(pages as a browser shows them) and the stage-1 support oracle. Written from stage-2.md only.

  expected_candidates(domain, epoch) -> {field: [Cand, ...]} in rank order (selected first)
  expected_fields(domain, epoch)     -> {field: {"value", "status", "candidates", "citations"}}
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import oracle
from corpus_spec import COMPANIES

KINDS = ("own", "filing", "news", "aggregator")
AUTHORITY = {"own": 0, "filing": 0, "news": 1, "aggregator": 2}   # lower = higher authority
PROVIDER_ORDER = ["nimble", "tavily", "kernel", "browserbase"]

_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")


def parse_rfc3339(text) -> datetime | None:
    """An RFC 3339 timestamp (explicit offset) as an aware datetime, else None."""
    if not isinstance(text, str) or not _RFC3339.match(text):
        return None
    t = text.replace("z", "Z").replace("t", "T")
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalise_domain(d: str) -> str:
    d = d.strip().lower()
    if d.endswith("."):
        d = d[:-1]
    if d.startswith("www."):
        d = d[4:]
    return d


def host_of(url: str) -> str:
    return normalise_domain(urlsplit(url).hostname or "")


def kind_of(page: dict, domain: str) -> str:
    k = page.get("kind")
    if k in KINDS:
        return k
    return "own" if host_of(page["url"]) == normalise_domain(domain) else "aggregator"


def published_of(page: dict) -> datetime | None:
    return parse_rfc3339(page.get("published_at"))


@dataclass
class Cand:
    field: str
    value: object
    url: str
    kind: str
    published: datetime | None
    excerpts: list


def _value_key(v):
    return v if isinstance(v, int) else v.strip()


def _cmp(a: Cand, b: Cand) -> int:
    """Negative when a ranks higher than b."""
    if AUTHORITY[a.kind] != AUTHORITY[b.kind]:
        return AUTHORITY[a.kind] - AUTHORITY[b.kind]
    if a.published != b.published:
        if a.published is None:
            return 1
        if b.published is None:
            return -1
        return -1 if a.published > b.published else 1
    if a.url != b.url:
        return -1 if a.url < b.url else 1
    ka, kb = _value_key(a.value), _value_key(b.value)
    if ka != kb:
        return -1 if ka < kb else 1
    return 0


def rank(cands: list[Cand]) -> list[Cand]:
    return sorted(cands, key=functools.cmp_to_key(_cmp))


def evidence_pages(domain: str, epoch: int = 0) -> list[dict]:
    """Searchable pages of the company, plus every page a nimble research entry cites (stage 2)."""
    c = COMPANIES.get(domain)
    if not c:
        return []
    cited = {r["url"] for r in c.get("research", {}).get("nimble", {}).get(str(epoch), [])}
    return [p for p in c["pages"]
            if epoch in p["epochs"] and (p.get("searchable", True) or p["url"] in cited)]


def page_candidates(page: dict, domain: str) -> list[Cand]:
    found: dict[tuple, Cand] = {}
    for s in oracle.sentences(page["text"]):          # a page's text is what a browser shows
        for f in oracle.FIELDS:
            v = oracle.supported_value(s, f, domain)
            if v is None:
                continue
            key = (f, repr(v))
            if key in found:
                found[key].excerpts.append(s)
            else:
                found[key] = Cand(f, v, page["url"], kind_of(page, domain), published_of(page), [s])
    return list(found.values())


def expected_candidates(domain: str, epoch: int = 0) -> dict[str, list[Cand]]:
    out: dict[str, list[Cand]] = {f: [] for f in oracle.FIELDS}
    for p in evidence_pages(domain, epoch):
        for c in page_candidates(p, domain):
            out[c.field].append(c)
    return {f: rank(v) for f, v in out.items()}


def status_of(cands: list[Cand]) -> str:
    if not cands:
        return "unknown"
    return "known" if len({repr(c.value) for c in cands}) == 1 else "contested"


def expected_fields(domain: str, epoch: int = 0) -> dict[str, dict]:
    res = {}
    for f, cands in expected_candidates(domain, epoch).items():
        sel = cands[0].value if cands else None
        res[f] = {
            "value": sel, "status": status_of(cands), "candidates": cands,
            "citation_urls": [c.url for c in cands if c.value == sel and type(c.value) is type(sel)],
        }
    return res


def same_value(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    return a == b and type(a) is type(b)


# ---------------------------------------------------------------- ranking of arbitrary response data
def rank_key_problems(cands: list[dict]) -> list[str]:
    """Check that response candidates (dicts with value/url/provider/kind/published_at) are in the
    order the selection rule gives, treating a null kind as aggregator. Returns problems."""
    probs = []

    def conv(c):
        k = c.get("kind") or "aggregator"
        return k, parse_rfc3339(c.get("published_at"))

    def cmp(a, b):
        ka, pa = conv(a)
        kb, pb = conv(b)
        if AUTHORITY[ka] != AUTHORITY[kb]:
            return AUTHORITY[ka] - AUTHORITY[kb]
        if pa != pb:
            if pa is None:
                return 1
            if pb is None:
                return -1
            return -1 if pa > pb else 1
        if a["url"] != b["url"]:
            return -1 if a["url"] < b["url"] else 1
        if a["provider"] != b["provider"]:
            ia = PROVIDER_ORDER.index(a["provider"])
            ib = PROVIDER_ORDER.index(b["provider"])
            return -1 if ia < ib else 1
        va, vb = _value_key(a["value"]), _value_key(b["value"])
        if va != vb:
            return -1 if va < vb else 1
        return 0

    for i in range(len(cands) - 1):
        if cmp(cands[i], cands[i + 1]) > 0:
            probs.append(f"candidate {i + 1} should not rank above candidate {i + 2}: "
                         f"{cands[i]} / {cands[i + 1]}")
    return probs
