"""Stage-4 oracle: the origin of a page (rules 1-4, the three-Canonical limit, lookalikes) derived
from the analyst corpus. Written from stage-4.md only.

  origin_of(page, domain, epoch)   the origin domain of one page of that company in that epoch
  originals_needed(page, epoch)    URLs a build must obtain to resolve rule 2 for that page
"""
from __future__ import annotations

import rank
from corpus_spec import COMPANIES


def page_at(url: str, epoch: int) -> dict | None:
    """The page some provider serves at url in that epoch (any company's file, searchable or not)."""
    for c in COMPANIES.values():
        for p in c["pages"]:
            if p["url"] == url and epoch in p["epochs"]:
                return p
    return None


def _valid(d):
    if not isinstance(d, str):
        return None
    n = rank.normalise_domain(d)
    return n if rank.valid_domain(n) else None


def origin_of(page: dict, domain: str, epoch: int, _followed: int = 0) -> str:
    lin = page.get("lineage") or {}
    fpb = _valid(lin.get("first_published_by"))
    if fpb:                                                     # rule 1
        return fpb
    canon = lin.get("canonical")
    if canon and canon != page["url"]:                          # rule 2
        if _followed == 3:
            return rank.host_of(canon)
        orig = page_at(canon, epoch)
        if orig is None:
            return rank.host_of(canon)
        return origin_of(orig, domain, epoch, _followed + 1)
    if rank.is_lookalike(page):                                 # rule 3
        return rank.normalise_domain(domain)
    return rank.registrant_of(page)                             # rule 4


def originals_needed(page: dict, epoch: int) -> list[str]:
    """URLs of the originals rule 2 follows from this page (at most three), that exist."""
    out, cur, n = [], page, 0
    while n < 3:
        lin = cur.get("lineage") or {}
        if _valid(lin.get("first_published_by")):
            break
        canon = lin.get("canonical")
        if not canon or canon == cur["url"]:
            break
        orig = page_at(canon, epoch)
        if orig is None:
            break
        out.append(canon)
        cur, n = orig, n + 1
    return out
