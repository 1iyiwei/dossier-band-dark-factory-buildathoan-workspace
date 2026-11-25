"""Stage-4 helpers: batches, provider faults around a build, the checks of a build cut short by a
shared budget, restarts with builds running, and the expectation for imported origins.
HTTP only. Written from stage-4.md, never from the implementation."""
from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import urlsplit

import oracle
import rank
import s3lib
import timeline as tl
from lib import Api, new_key, parse_ts

SIX = oracle.FIELDS


# ------------------------------------------------------------------ batches
def batch_create(api, tok, domains, budget, key=None, body=None):
    return api.req("POST", "/batches", token=tok, key=key or new_key("b"),
                   json=body if body is not None else {"domains": domains, "budget_units": budget})


def batch_get(api, tok, bid):
    return api.req("GET", f"/batches/{bid}", token=tok)


def wait_batch(api, tok, bid, timeout=90, interval=0.3) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        r = batch_get(api, tok, bid)
        assert r.status_code == 200, (r.status_code, r.text)
        b = r.json()
        if b["state"] != "running":
            return b
        if time.monotonic() > deadline:
            raise AssertionError(f"batch {bid} still running after {timeout}s: {b}")
        time.sleep(interval)


def assert_batch_shape(b, domains=None, budget=None):
    assert set(b) >= {"batch_id", "state", "budget_units", "spent_units", "dossiers"}, b
    assert isinstance(b["batch_id"], str) and 1 <= len(b["batch_id"]) <= 64
    assert b["state"] in ("running", "done"), b
    assert isinstance(b["budget_units"], int) and not isinstance(b["budget_units"], bool)
    assert isinstance(b["spent_units"], int) and not isinstance(b["spent_units"], bool)
    assert 0 <= b["spent_units"] <= b["budget_units"], b
    for d in b["dossiers"]:
        assert set(d) >= {"domain", "state"} and d["state"] in ("building", "ready", "failed"), d
    if domains is not None:
        assert [d["domain"] for d in b["dossiers"]] == domains, b["dossiers"]
    if budget is not None:
        assert b["budget_units"] == budget


def dossier_spent(api, tok, domains):
    return {d: api.get(tok, d).json()["spent_units"] for d in domains}


# ------------------------------------------------------------------ faults around a build
ALL_METHODS = ["search", "extract", "research"]


def set_faults(mock, spec, on=True):
    """spec: [(provider, methods, mode)]; on=False clears them."""
    for provider, methods, mode in spec:
        mock.fault(provider, methods, mode if on else "none")


def all_fail(mock, on=True):
    set_faults(mock, [("nimble", ALL_METHODS, "error"), ("tavily", ALL_METHODS, "error")], on)
    for p in ("kernel", "browserbase"):
        mock.fault(p, ["session", "browse"], "error" if on else "none")


def build_with(api, mock, tok, domain, spec, *, epoch=0, clock=None, first=True, timeout=60):
    """Run one build with the provider faults `spec` in force; clear them afterwards. Returns
    (dossier body, mock log segment, seconds the build took as seen through polling)."""
    mock.epoch(epoch)
    if clock:
        api.clock(clock)
    set_faults(mock, spec)
    try:
        n0 = len(mock.log())
        t0 = time.monotonic()
        r = api.create(tok, domain) if first else api.refresh(tok, domain)
        assert r.status_code in (200, 202), (r.status_code, r.text)
        snap = api.wait(tok, domain, timeout=timeout, interval=0.1)
        took = time.monotonic() - t0
        seg = mock.log()[n0:]
    finally:
        set_faults(mock, spec, on=False)
    return snap, seg, took


def billed(log):
    return sum(int(e.get("cost") or 0) for e in log)


def oracle_problems(snap, domain, seg, epoch, clock):
    """Compare a ready dossier built from the corpus with the oracle (all eight fields, origins,
    candidates, history of one build). `seg` = the build's mock log segment."""
    rec = s3lib.Rec(clock, epoch, True, snap, seg)
    builds = s3lib.to_builds([rec], domain)
    sim = tl.simulate(builds, domain)
    return s3lib.snapshot_problems(snap, domain, [rec], 0, builds, sim)


# ------------------------------------------------------------------ builds cut short (budget, restart)
def fully_obtained_pages(seg, domain, epoch):
    """URLs of the company's evidence pages whose complete text this log segment served."""
    ev = {p["url"] for p in rank.evidence_pages(domain, epoch)}
    out = set()
    for e in seg:
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


def partial_build_problems(body, domain, seg, epoch=0):
    """A build that stopped early (shared budget) or was cut short: every field is `known` exactly
    when the pages it obtained support a value (we check both directions for the six fields): a
    field is never known without a supporting citation served in `seg`, and a page whose full text
    the build obtained and that supports a value for a field makes that field known."""
    from lib import citation_problems, candidate_structure_problems
    probs = list(citation_problems(body, domain, seg)) + candidate_structure_problems(body)
    pages = {p["url"]: p for p in rank.evidence_pages(domain, epoch)}
    for u in fully_obtained_pages(seg, domain, epoch):
        for c in rank.page_candidates(pages[u], domain):
            fv = body["fields"][c.field]
            if fv["value"] is None:
                probs.append(f"{c.field} is unknown although the obtained page {u} supports {c.value!r}")
            elif not any(x["url"] == u for x in fv["candidates"]):
                probs.append(f"{c.field}: obtained page {u} supporting {c.value!r} is not a candidate")
    return probs


# ------------------------------------------------------------------ imported origins
def host_of(url):
    return rank.normalise_domain(urlsplit(url).hostname or "")


def imported_expectation(bodies_in_order, times):
    """The expected (origins, corroborated, corroborated_since) of each field after an import,
    from the exporting service's dossier bodies (one per ready build, oldest first, with the time
    each counts as gathered): every candidate's origin is the host of its URL (the export records
    none) and its group counts as gathered at that build's time (stage-4 Origins)."""
    tr = tl.SinceTracker()
    out = None
    for body, t in zip(bodies_in_order, times):
        out = {}
        for f in oracle.ALL_FIELDS:
            fv = body["fields"][f]
            groups = {}
            if fv["value"] is not None and f not in ("executives", "investors"):
                groups = {repr(fv["value"]): {host_of(c["url"]) for c in fv["candidates"]
                                               if rank.same_value(c["value"], fv["value"])}}
            elif fv["value"] is not None and f == "executives":
                groups = {(m["title"], m["name"]): {host_of(c["url"]) for c in fv["candidates"]
                                                    if c["title"] == m["title"] and c["value"] == m["name"]}
                          for m in fv["value"]}
            since = tr.step(f, groups, t)
            origins = sorted(set().union(*groups.values())) if groups else []
            out[f] = dict(origins=origins, corroborated=bool(groups) and all(len(g) >= 2 for g in groups.values()),
                          since=since)
    return out


def inst(s):
    return parse_ts(s) if s else None


def poll_until_terminal(api, tok, domain, limit, interval=0.2):
    """Seconds until the dossier is no longer `building`, polling; AssertionError past `limit`."""
    t0 = time.monotonic()
    while True:
        b = api.get(tok, domain).json()
        if b["state"] != "building":
            return time.monotonic() - t0, b
        if time.monotonic() - t0 > limit:
            raise AssertionError(f"{domain} still building {limit}s after the service was healthy")
        time.sleep(interval)


# ------------------------------------------------------------------ restarts with builds running
def hold_providers(mock, seconds=2.0, on=True):
    """Every search, extract and research call of nimble and tavily answers after `seconds`
    (at normal cost), so that a build is in flight for a while; on=False clears it."""
    for p in ("nimble", "tavily"):
        if on:
            mock.fault(p, ["search", "extract", "research"], "delay", seconds=seconds)
        else:
            mock.fault(p, ["search", "extract", "research"], "none")


def wait_billed(mock, n=1, timeout=30.0):
    """Block until the mock has billed (cost > 0) at least n calls; returns the log."""
    deadline = time.monotonic() + timeout
    while True:
        log = mock.log()
        if len([e for e in log if (e.get("cost") or 0) > 0]) >= n:
            return log
        if time.monotonic() > deadline:
            raise AssertionError(f"no billed provider call within {timeout}s")
        time.sleep(0.05)


def kill_clear_start(mock, base_url, wait=60.0):
    """SIGKILL the service container, lift the provider delays (calls after the restart answer at
    once), start it again; returns the monotonic time at which /health first answered 200."""
    import httpx
    s3lib.docker("kill", "--signal", "KILL", s3lib.SVC_CONTAINER)
    hold_providers(mock, on=False)
    s3lib.docker("start", s3lib.SVC_CONTAINER)
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        try:
            if httpx.get(base_url + "/health", timeout=2.0).status_code == 200:
                return time.monotonic()
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise AssertionError(f"service not healthy {wait}s after restart")
