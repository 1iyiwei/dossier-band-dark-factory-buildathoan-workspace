"""Stage-3 oracle: two times per value, executives, history, the change feed, `as_of` and
`/values` page versions. Written from stage-3.md (as quoted in the kickoff) with oracle.py (stage-1
support rule) and rank.py (stage-2 selection rule); it never reads the implementation.

  exp_fields(domain, epoch)        what one build of that epoch must select (value, status, true_from,
                                   candidates incl. executives) -- derived from corpus_spec pages
  simulate(builds)                 history lists, feed entries and per-build selected state
  values_at(builds, as_of, true_at) the page-version rule of `GET /dossiers/{d}/values`

A `Build` is (time, epoch, ready, gathered_urls). Build order is list order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import oracle
import rank
from corpus_spec import COMPANIES

TITLES = oracle.TITLES
ALL_FIELDS = oracle.ALL_FIELDS


# ---------------------------------------------------------------- true_from of a page (stage 3)
def valid_date(s) -> bool:
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return True


def page_true_from(page: dict) -> str | None:
    """`Effective: YYYY-MM-DD` if valid, else the UTC date of a valid `Published`, else None."""
    e = page.get("true_from")
    if valid_date(e):
        return e
    p = rank.parse_rfc3339(page.get("published_at"))
    if p is not None:
        return p.astimezone(timezone.utc).date().isoformat()
    return None


# ---------------------------------------------------------------- candidates and fields of one build
@dataclass
class ECand(rank.Cand):
    title: str | None = None
    true_from: str | None = None


def _mk(field_, title, value, page, domain):
    return ECand(field_, value, page["url"], rank.kind_of(page, domain),
                 rank.published_of(page), [], title=title, true_from=page_true_from(page))


def exp_candidates(domain: str, epoch: int = 0) -> dict[str, list[ECand]]:
    """Every field (incl. executives) -> candidates in API order (executives: by title, then rank)."""
    out: dict[str, list[ECand]] = {f: [] for f in ALL_FIELDS}
    by_title: dict[str, list[ECand]] = {t: [] for t in TITLES}
    for p in rank.evidence_pages(domain, epoch):
        for c in rank.page_candidates(p, domain):
            e = _mk(c.field, None, c.value, p, domain)
            e.excerpts = c.excerpts
            out[c.field].append(e)
        seen = set()
        for s in oracle.sentences(p["text"]):
            for t in TITLES:
                v = oracle.supported_title_value(s, t, domain)
                if v is None:
                    continue
                if (t, v) in seen:
                    for e in by_title[t]:
                        if e.value == v and e.url == p["url"]:
                            e.excerpts.append(s)
                    continue
                seen.add((t, v))
                e = _mk("executives", t, v, p, domain)
                e.excerpts = [s]
                by_title[t].append(e)
    res = {f: rank.rank(v) for f, v in out.items() if f != "executives"}
    res["executives"] = [c for t in TITLES for c in rank.rank(by_title[t])]
    return {f: res[f] for f in ALL_FIELDS}


def select_fields(cands: dict[str, list[ECand]]) -> dict[str, dict]:
    """The selected value of each field from candidates already grouped per field (any source:
    one build, or the candidates at `true_at`). Executives: per-title rank, members, status."""
    res = {}
    for f in oracle.FIELDS:
        cs = rank.rank(cands.get(f, []))
        if not cs:
            res[f] = dict(value=None, status="unknown", true_from=None, candidates=[], cit=[],
                          members={})
            continue
        sel = cs[0]
        res[f] = dict(value=sel.value, status=rank.status_of(cs), true_from=sel.true_from,
                      candidates=cs, cit=[c for c in cs if rank.same_value(c.value, sel.value)],
                      members={})
    members, ordered, cit, contested = {}, [], [], False
    for t in TITLES:
        cs = rank.rank([c for c in cands.get("executives", []) if c.title == t])
        if not cs:
            continue
        ordered += cs
        members[t] = cs[0]
        cit += [c for c in cs if c.value == cs[0].value]
        contested = contested or len({c.value for c in cs}) > 1
    if not members:
        res["executives"] = dict(value=None, status="unknown", true_from=None, candidates=[],
                                 cit=[], members={})
    else:
        tfs = [m.true_from for m in members.values()]
        res["executives"] = dict(
            value=[{"title": t, "name": members[t].value} for t in TITLES if t in members],
            status="contested" if contested else "known",
            true_from=None if any(x is None for x in tfs) else max(tfs),
            candidates=ordered, cit=cit, members=members)
    return res


def exp_fields(domain: str, epoch: int = 0) -> dict[str, dict]:
    return select_fields(exp_candidates(domain, epoch))


# ---------------------------------------------------------------- builds, history, feed
@dataclass
class Build:
    time: datetime
    epoch: int
    ready: bool = True
    gathered: set | None = None        # URLs whose text the build obtained (None: all evidence)
    fields: dict | None = None         # filled by `simulate` / `prepare`

    def prepare(self, domain):
        if self.ready and self.fields is None:
            self.fields = exp_fields(domain, self.epoch)
        if self.gathered is None:
            self.gathered = {p["url"] for p in rank.evidence_pages(domain, self.epoch)}
        return self


def classify_field(f, old, new) -> str:
    """old/new: dict(value, true_from, members) of one field. Returns 'correction' or 'change'."""
    ov, nv = old["value"], new["value"]
    if f == "executives":
        diff, corr = [], []
        for t in TITLES:
            o, n = old["members"].get(t), new["members"].get(t)
            if (o is None) != (n is None) or (o is not None and o.value != n.value):
                diff.append(t)
                if o is not None and n is not None and o.true_from is not None \
                        and n.true_from is not None and n.true_from <= o.true_from:
                    corr.append(t)
        return "correction" if diff and diff == corr else "change"
    if ov is not None and nv is not None and old["true_from"] is not None \
            and new["true_from"] is not None and new["true_from"] <= old["true_from"]:
        return "correction"
    return "change"


@dataclass
class Sim:
    history: dict = field(default_factory=lambda: {f: [] for f in ALL_FIELDS})
    feed: list = field(default_factory=list)
    state_after: list = field(default_factory=list)    # per build: {field: dict(value, true_from, learned_at)}


def _same(a, b):
    return a == b and type(a) is type(b)


def simulate(builds: list[Build], domain: str) -> Sim:
    sim = Sim()
    cur = {f: dict(value=None, true_from=None, members={}, learned_at=None) for f in ALL_FIELDS}
    first_done = False
    for bi, b in enumerate(builds):
        b.prepare(domain)
        if b.ready:
            for f in ALL_FIELDS:
                new = b.fields[f]
                old = cur[f]
                if not first_done:
                    if new["value"] is not None:
                        sim.history[f].append(dict(
                            type="initial", value=new["value"], true_from=new["true_from"],
                            learned_at=b.time, cit=[c.url for c in new["cit"]], bi=bi))
                elif not _same(old["value"], new["value"]):
                    t = classify_field(f, old, new)
                    sim.history[f].append(dict(
                        type=t, value=new["value"], true_from=new["true_from"],
                        learned_at=b.time, cit=[c.url for c in new["cit"]], bi=bi))
                    sim.feed.append(dict(field=f, type=t, **{"from": old["value"]},
                                         to=new["value"], true_from=new["true_from"],
                                         learned_at=b.time))
                    old["learned_at"] = b.time
                if not first_done and new["value"] is not None:
                    old["learned_at"] = b.time
                old["value"], old["true_from"] = new["value"], new["true_from"]
                old["members"] = new["members"]
                if new["value"] is None:
                    old["learned_at"] = None
            first_done = True
        sim.state_after.append({f: dict(value=cur[f]["value"], true_from=cur[f]["true_from"],
                                        learned_at=cur[f]["learned_at"]) for f in ALL_FIELDS})
    return sim


# ---------------------------------------------------------------- as_of and /values
def as_of_index(builds: list[Build], as_of: datetime) -> int | None:
    """Index of the latest ready build at or before as_of; the last one in build order on ties."""
    idx = None
    for i, b in enumerate(builds):
        if b.ready and b.time <= as_of:
            idx = i
    return idx


INF = "9999-12-31"


def page_versions(builds: list[Build], domain: str, as_of: datetime) -> list[dict]:
    """The page versions of ready builds at or before as_of, each with `start` and `end`
    (None = never holds / still holds), after applying the replace-and-end rule per URL."""
    per_url: dict[str, list[dict]] = {}
    for b in builds:
        if not (b.ready and b.time <= as_of):
            continue
        b.prepare(domain)
        pages = {p["url"]: p for p in rank.evidence_pages(domain, b.epoch)}
        urls = {c.url for cs in b.fields.values() for c in cs["candidates"]} | b.gathered
        for u in sorted(urls):
            tf = page_true_from(pages[u]) if u in pages else None
            cands = [c for f in ALL_FIELDS for c in b.fields[f]["candidates"] if c.url == u]
            chain = per_url.setdefault(u, [])
            if tf is None:
                chain.clear()
            else:
                chain[:] = [v for v in chain if not (v["start"] is not None and v["start"] >= tf)]
                alive = [v for v in chain if v["start"] is not None]
                if alive:
                    alive[-1]["end"] = tf
            chain.append(dict(url=u, start=tf, end=None, cands=cands))
    return [v for chain in per_url.values() for v in chain]


def values_at(builds: list[Build], domain: str, as_of: datetime, true_at: str) -> dict | None:
    """The `fields` of GET /values: field -> dict(value, true_from, cit_urls); None if no build."""
    if as_of_index(builds, as_of) is None:
        return None
    cands: dict[str, list[ECand]] = {f: [] for f in ALL_FIELDS}
    for v in page_versions(builds, domain, as_of):
        if v["start"] is None or not (v["start"] <= true_at and (v["end"] is None or true_at < v["end"])):
            continue
        for c in v["cands"]:
            cands[c.field].append(c)
    sel = select_fields(cands)
    return {f: dict(value=sel[f]["value"], true_from=sel[f]["true_from"],
                    cit_urls=[(c.url, c.title) for c in sel[f]["cit"]]) for f in ALL_FIELDS}


# ---------------------------------------------------------------- time helpers
def dt(s: str) -> datetime:
    return rank.parse_rfc3339(s)


def iso(d: datetime) -> str:
    return d.isoformat()


def days(d: datetime, n: int) -> datetime:
    return d + timedelta(days=n)
