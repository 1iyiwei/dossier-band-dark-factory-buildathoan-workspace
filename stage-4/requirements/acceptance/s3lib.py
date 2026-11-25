"""Stage-3 helpers: endpoint wrappers, scripted multi-build scenarios against the mock web's
epochs and the service clock, and checks of every response against timeline.py (the oracle).
HTTP only. Written from the stage-3 specification, never from the implementation."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime

import oracle
import rank
import timeline as tl
from corpus_spec import all_page_texts
from lib import (BASE_URL, T0, USERS, Api, Mock, assert_dossier_shape, assert_error, new_key,
                 parse_ts)

P = ("nimble", "tavily")


# ------------------------------------------------------------------ endpoints
def history(api, tok, domain):
    return api.req("GET", f"/dossiers/{domain}/history", token=tok)


def changes(api, tok, **params):
    return api.req("GET", "/changes", token=tok, params=params or None)


def as_of(api, tok, domain, ts):
    return api.req("GET", f"/dossiers/{domain}", token=tok, params={"as_of": ts})


def values(api, tok, domain, true_at=None, as_of_ts=None):
    params = {}
    if true_at is not None:
        params["true_at"] = true_at
    if as_of_ts is not None:
        params["as_of"] = as_of_ts
    return api.req("GET", f"/dossiers/{domain}/values", token=tok, params=params or None)


def all_changes(api, tok, since=0, page=200):
    out = []
    while True:
        b = changes(api, tok, since=since, limit=page).json()
        out += b["changes"]
        if not b["has_more"]:
            return out
        since = b["changes"][-1]["seq"]


# ------------------------------------------------------------------ scripted scenarios
@dataclass
class Rec:
    clock: str                   # clock reading when the build was requested = the build's time
    epoch: int
    ready: bool
    snap: dict                   # GET /dossiers/{d} right after the build
    segment: list                # mock log entries of this build
    time: datetime = None
    expect_fail: bool = False

    def __post_init__(self):
        self.time = parse_ts(self.clock)


def fail_providers(mock, on: bool):
    for p in P:
        mock.fault(p, ["search", "extract", "research"], "error" if on else "none")


def run(api, mock, tok, domain, script, **kw):
    """script: [{"epoch": n, "clock": "RFC3339"|None, "fail": bool}, ...]. The first step creates
    the dossier, later ones refresh it. A step without `clock` leaves the clock where it is.
    Returns [Rec] (one per build)."""
    # resolve implicit clocks: a step without `clock` keeps the previous reading
    cur = T0
    resolved = []
    for st in script:
        st = dict(st)
        if st.get("clock"):
            cur = st["clock"]
        else:
            st["clock"] = None
        st["_now"] = cur
        resolved.append(st)
    recs = []
    for i, st in enumerate(resolved):
        mock.epoch(st["epoch"])
        if st["clock"]:
            api.clock(st["clock"])
        if st.get("fail"):
            fail_providers(mock, True)
        n0 = len(mock.log())
        r = api.create(tok, domain) if i == 0 else api.refresh(tok, domain)
        assert r.status_code in (200, 202), (r.status_code, r.text)
        snap = api.wait(tok, domain, timeout=kw.get("timeout", 60))
        seg = mock.log()[n0:]
        if st.get("fail"):
            fail_providers(mock, False)
            assert snap["state"] == "failed", snap["state"]
        else:
            assert snap["state"] == "ready", (i, snap["state"])
        recs.append(Rec(st["_now"], st["epoch"], not st.get("fail"), snap, seg,
                        expect_fail=bool(st.get("fail"))))
    return recs


def gathered_urls(rec: Rec, domain: str) -> set:
    """URLs of the company's evidence pages whose text this build obtained in full."""
    ev = {p["url"] for p in rank.evidence_pages(domain, rec.epoch)}
    out = set()
    for e in rec.segment:
        if not (isinstance(e.get("status"), int) and e["status"] < 400):
            continue
        full = e.get("method") in ("extract", "load") or (e.get("method") == "search"
                                                            and e.get("depth") == "deep")
        if not full:
            continue
        for it in e.get("served") or []:
            if isinstance(it, dict) and it.get("url") in ev:
                out.add(it["url"])
    return out


def to_builds(recs, domain):
    return [tl.Build(r.time, r.epoch, r.ready, gathered_urls(r, domain) if r.ready else None)
            for r in recs]


# ------------------------------------------------------------------ checks on a dossier body
def _inst(s):
    return parse_ts(s) if s else None


def _cand_key(f, c):
    return (f, c.get("title"), repr(c["value"]), c["url"], c["provider"])


def first_learned(recs, upto, f, c):
    """Time of the first ready build (index <= upto) whose snapshot holds a candidate with the
    same field, title, value, URL and provider as c."""
    k = _cand_key(f, c)
    for r in recs[:upto + 1]:
        if not r.ready:
            continue
        for x in r.snap["fields"][f]["candidates"]:
            if _cand_key(f, x) == k:
                return r.time
    return None


def snapshot_problems(body, domain, recs, idx, builds, sim, check_learned=True):
    """Compare the dossier body `body` (as a build idx left it, or an as_of answer for it) with the
    oracle. Returns a list of problems."""
    probs = []
    r = recs[idx]
    exp = builds[idx].fields
    state = sim.state_after[idx]
    texts = all_page_texts()
    if parse_ts(body["researched_at"]) != r.time:
        probs.append(f"researched_at {body['researched_at']} != build time {r.clock}")
    for f in oracle.ALL_FIELDS:
        fv, e = body["fields"][f], exp[f]
        if fv["value"] != e["value"] or type(fv["value"]) is not type(e["value"]):
            probs.append(f"{f}: value {fv['value']!r}, expected {e['value']!r}")
        if fv["status"] != e["status"]:
            probs.append(f"{f}: status {fv['status']}, expected {e['status']}")
        if fv["true_from"] != e["true_from"]:
            probs.append(f"{f}: true_from {fv['true_from']}, expected {e['true_from']}")
        la = state[f]["learned_at"]
        if (fv["learned_at"] is None) != (la is None) or (la and _inst(fv["learned_at"]) != la):
            probs.append(f"{f}: learned_at {fv['learned_at']}, expected {la}")
        if fv["origins"] != state[f]["origins"] or fv["corroborated"] is not state[f]["corroborated"]:
            probs.append(f"{f}: origins/corroborated {fv['origins']}/{fv['corroborated']}, expected "
                         f"{state[f]['origins']}/{state[f]['corroborated']}")
        sn = state[f]["since"]
        if (fv["corroborated_since"] is None) != (sn is None) or (sn and _inst(fv["corroborated_since"]) != sn):
            probs.append(f"{f}: corroborated_since {fv['corroborated_since']}, expected {sn}")
        got = [(c.get("title"), c["value"], c["url"], c["true_from"], c["kind"],
                _inst(c["published_at"]), c["selected"], c["origin"]) for c in fv["candidates"]]
        want = [(c.title, c.value, c.url, c.true_from, c.kind, c.published, e["selected"][n], c.origin)
                for n, c in enumerate(e["candidates"])]
        if got != want:
            probs.append(f"{f}: candidates\n   got  {got}\n   want {want}")
            continue
        for c in fv["candidates"]:
            if _inst(c["retrieved_at"]) != r.time:
                probs.append(f"{f}: candidate retrieved_at {c['retrieved_at']} != {r.clock}")
            if check_learned:
                want_l = first_learned(recs, idx, f, c)
                if want_l is None or _inst(c["learned_at"]) != want_l:
                    probs.append(f"{f}: candidate {c['value']!r} {c['url']} learned_at "
                                 f"{c['learned_at']}, expected {want_l}")
            ex = oracle.collapse(c["excerpt"]).strip()
            ok = (oracle.supports_title(ex, c["title"], c["value"], domain) if f == "executives"
                  else oracle.supports_investor(ex, c["value"], domain) if f == "investors"
                  else oracle.supports(ex, f, c["value"], domain))
            if not ok or not (1 <= len(c["excerpt"]) <= 500):
                probs.append(f"{f}: excerpt does not support {c['value']!r}: {c['excerpt']!r}")
            if not any(ex in oracle.collapse(t) for t in texts.get(c["url"], [])):
                probs.append(f"{f}: excerpt not in the page text of {c['url']}: {c['excerpt']!r}")
        # citations: the selected value's candidates in rank order (executives: per member)
        want_c = [(c.url) for c in e["cit"]]
        got_c = [c["url"] for c in fv["citations"]]
        if got_c != want_c:
            probs.append(f"{f}: citation urls {got_c}, expected {want_c}")
        cand_set = {(c["url"], c["excerpt"], c["provider"]) for c in fv["candidates"]}
        for c in fv["citations"]:
            if (c["url"], c["excerpt"], c["provider"]) not in cand_set:
                probs.append(f"{f}: citation {c} is not one of the candidates")
    return probs


def history_problems(h, domain, recs, builds, sim):
    probs = []
    if h.get("domain") != domain:
        probs.append(f"domain {h.get('domain')}")
    if list(h["fields"]) != oracle.ALL_FIELDS:
        probs.append(f"history fields {list(h['fields'])}")
        return probs
    for f in oracle.ALL_FIELDS:
        got, want = h["fields"][f], sim.history[f]
        shape = [(e["type"], e["value"], e["true_from"], _inst(e["learned_at"])) for e in got]
        wshape = [(e["type"], e["value"], e["true_from"], e["learned_at"]) for e in want]
        if shape != wshape:
            probs.append(f"{f}: history\n   got  {shape}\n   want {wshape}")
            continue
        for g, w in zip(got, want):
            if set(g) != {"type", "value", "true_from", "learned_at", "citations"}:
                probs.append(f"{f}: entry keys {sorted(g)}")
            if [c["url"] for c in g["citations"]] != w["cit"]:
                probs.append(f"{f}: entry citations {[c['url'] for c in g['citations']]} "
                             f"expected {w['cit']}")
            if g["value"] is None and (g["true_from"] is not None or g["citations"] != []):
                probs.append(f"{f}: null entry carries true_from/citations: {g}")
    return probs


def feed_problems(feed, domain, sim, since_seq=0):
    """`feed`: entries of this domain in feed order (all domains' entries if only one dossier)."""
    probs = []
    seqs = [e["seq"] for e in feed]
    if seqs != sorted(set(seqs)) or any(not isinstance(s, int) or s < 1 or isinstance(s, bool)
                                        for s in seqs):
        probs.append(f"seq not positive, unique and increasing: {seqs}")
    got = [(e["domain"], e["field"], e["type"], e["from"], e["to"], e["true_from"],
            _inst(e["learned_at"])) for e in feed]
    want = [(domain, e["field"], e["type"], e["from"], e["to"], e["true_from"], e["learned_at"])
            for e in sim.feed]
    if got != want:
        probs.append(f"feed\n   got  {got}\n   want {want}")
    for e in feed:
        if set(e) != {"seq", "domain", "field", "type", "from", "to", "true_from", "learned_at"}:
            probs.append(f"feed entry keys {sorted(e)}")
    return probs


def check_values(body, domain, recs, builds, as_of_dt, true_at, as_of_ts=None):
    probs = []
    want = tl.values_at(builds, domain, as_of_dt, true_at)
    if body.get("domain") != domain or body.get("true_at") != true_at:
        probs.append(f"domain/true_at {body.get('domain')} {body.get('true_at')}")
    if as_of_ts is not None and _inst(body.get("as_of")) != as_of_dt:
        probs.append(f"as_of {body.get('as_of')}")
    if list(body["fields"]) != oracle.ALL_FIELDS:
        probs.append(f"fields {list(body['fields'])}")
        return probs
    texts = all_page_texts()
    for f in oracle.ALL_FIELDS:
        g, w = body["fields"][f], want[f]
        if set(g) != {"value", "true_from", "citations"}:
            probs.append(f"{f}: keys {sorted(g)}")
        if g["value"] != w["value"] or g["true_from"] != w["true_from"]:
            probs.append(f"{f}: at {true_at} got {g['value']!r}/{g['true_from']}, "
                         f"expected {w['value']!r}/{w['true_from']}")
        if [c["url"] for c in g["citations"]] != [u for u, _ in w["cit_urls"]]:
            probs.append(f"{f}: citation urls {[c['url'] for c in g['citations']]} expected "
                         f"{[u for u, _ in w['cit_urls']]}")
            continue
        for c, (u, title) in zip(g["citations"], w["cit_urls"]):
            ex = oracle.collapse(c["excerpt"]).strip()
            if f == "executives":
                name = next(m["name"] for m in g["value"] if m["title"] == title)
                ok = oracle.supports_title(ex, title, name, domain)
            elif f == "investors":
                ok = any(oracle.supports_investor(ex, n, domain) for n in g["value"])
            else:
                ok = oracle.supports(ex, f, g["value"], domain)
            if not ok:
                probs.append(f"{f}: citation excerpt does not support: {c['excerpt']!r}")
            if not any(ex in oracle.collapse(t) for t in texts.get(u, [])):
                probs.append(f"{f}: citation excerpt not in page text of {u}")
            if c["provider"] not in ("nimble", "tavily", "kernel", "browserbase"):
                probs.append(f"{f}: provider {c['provider']}")
    return probs


# ------------------------------------------------------------------ container control (restarts)
SVC_CONTAINER = os.environ.get("SVC_CONTAINER", "")


def docker(*args, check=True):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise AssertionError(f"docker {' '.join(args)}: {r.stderr.strip()}")
    return r


def kill_and_restart(api_url=BASE_URL, wait=60.0):
    """SIGKILL the service container (no warning, no time to finish) and start it again."""
    docker("kill", "--signal", "KILL", SVC_CONTAINER)
    docker("start", SVC_CONTAINER)
    t0 = time.monotonic()
    import httpx
    while time.monotonic() - t0 < wait:
        try:
            if httpx.get(api_url + "/health", timeout=2.0).status_code == 200:
                return time.monotonic() - t0
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise AssertionError(f"service not healthy {wait}s after restart")
