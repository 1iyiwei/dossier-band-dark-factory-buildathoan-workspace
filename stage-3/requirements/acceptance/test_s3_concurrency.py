"""Stage 3: concurrency. Refreshes and reads give the results of some sequential order; no change
appears twice in the feed and none is missing; 50 requests in flight on the new endpoints."""
import concurrent.futures as cf
import threading
import time

import pytest

import oracle
import s3lib
import timeline as tl
from lib import Api, T0, domain_queries, new_key, parse_ts

pytestmark = pytest.mark.corpus
NG = "northgate-labs.test"
PR = "pivotal-reed.test"
HG = "harrow-guild.test"
CB = "cobalt-assembly.test"


def test_R3_CON_01_concurrent_refreshes_run_one_build_and_add_each_entry_once(fresh):
    api, mock = fresh
    tok = api.token(0)
    s3lib.run(api, mock, tok, NG, [{"epoch": 0, "clock": T0}])
    mock.epoch(1)
    api.clock("2026-03-10T09:00:00+00:00")
    n0 = len(mock.log())
    tokens = [api.token(0), api.token(1)]
    with cf.ThreadPoolExecutor(24) as ex:
        rs = list(ex.map(lambda i: api.refresh(tokens[i % 2], NG), range(24)))
    assert {r.status_code for r in rs} == {202}
    assert len({tuple(sorted(r.json().items())) for r in rs}) == 1
    assert api.wait(tok, NG)["state"] == "ready"
    time.sleep(0.5)
    assert len(domain_queries(mock.log()[n0:], NG)) == 1, "more than one build ran"
    builds = [tl.Build(parse_ts(T0), 0), tl.Build(parse_ts("2026-03-10T09:00:00+00:00"), 1)]
    sim = tl.simulate(builds, NG)
    feed = s3lib.all_changes(api, tok)
    assert not s3lib.feed_problems(feed, NG, sim), s3lib.feed_problems(feed, NG, sim)
    h = s3lib.history(api, tok, NG).json()
    assert [len(h["fields"][f]) for f in oracle.ALL_FIELDS] == [len(sim.history[f]) for f in oracle.ALL_FIELDS]


def test_R3_CON_02_pollers_see_every_entry_exactly_once(fresh):
    """While several dossiers are rebuilt in parallel, readers that page the feed with `since`
    must end with exactly the entries of a sequential run: none twice, none missing."""
    api, mock = fresh
    tok = api.token(0)
    doms = [(NG, 0, 1), (PR, 0, 1), (HG, 0, 1), (CB, 0, 1)]
    for d, e0, _ in doms:
        mock.epoch(e0)
        api.clock(T0)
        api.create(tok, d)
        api.wait(tok, d)
    mock.epoch(1)
    api.clock("2026-03-10T09:00:00+00:00")
    stop = threading.Event()
    seen = []
    errs = []

    def poll():
        c = Api()
        since = 0
        while not stop.is_set():
            try:
                b = s3lib.changes(c, tok, since=since, limit=3).json()
            except Exception as e:  # noqa: BLE001
                errs.append(repr(e))
                return
            seen.extend(b["changes"])
            if b["changes"]:
                since = b["changes"][-1]["seq"]
            time.sleep(0.01)
        while True:                                   # drain
            b = s3lib.changes(c, tok, since=since, limit=200).json()
            seen.extend(b["changes"])
            if not b["has_more"]:
                return
            since = b["changes"][-1]["seq"]

    pollers = [threading.Thread(target=poll) for _ in range(3)]
    for t in pollers:
        t.start()
    with cf.ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(lambda d: api.refresh(tok, d[0]), doms * 2))
    assert {r.status_code for r in rs} == {202}
    for d, _, _ in doms:
        assert api.wait(tok, d)["state"] == "ready"
    time.sleep(0.3)
    stop.set()
    for t in pollers:
        t.join(30)
    assert not errs, errs
    full = s3lib.all_changes(api, tok)
    assert len({e["seq"] for e in full}) == len(full)
    # each poller's stream = the full feed (compare the multiset of seqs over the three pollers)
    from collections import Counter
    c = Counter(e["seq"] for e in seen)
    assert set(c) == {e["seq"] for e in full}, "a poller missed an entry"
    assert all(v == 3 for v in c.values()), f"an entry was delivered more or fewer times than once per poller: {c}"
    for d, e0, e1 in doms:
        exp = tl.simulate([tl.Build(parse_ts(T0), e0), tl.Build(parse_ts("2026-03-10T09:00:00+00:00"), e1)], d)
        got = [e for e in full if e["domain"] == d]
        assert not s3lib.feed_problems(got, d, exp), (d, s3lib.feed_problems(got, d, exp))


def test_R3_CON_03_reads_during_a_build_see_one_state_or_the_other(fresh):
    api, mock = fresh
    tok = api.token(0)
    recs = s3lib.run(api, mock, tok, NG, [{"epoch": 0, "clock": T0}])
    before = recs[0].snap
    h_before = s3lib.history(api, tok, NG).json()
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "delay", seconds=1)
    mock.epoch(1)
    api.clock("2026-03-10T09:00:00+00:00")
    assert api.refresh(tok, NG).status_code == 202
    bodies, hist, asof = [], [], []
    deadline = time.monotonic() + 40
    c = Api()
    while time.monotonic() < deadline:
        b = c.get(tok, NG).json()
        bodies.append(b)
        hist.append(s3lib.history(c, tok, NG).json())
        asof.append(s3lib.as_of(c, tok, NG, T0).json())
        if b["state"] != "building":
            break
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "none")
    after = bodies[-1]
    assert after["state"] == "ready" and after["fields"]["ceo"]["value"] == "Lee Park"
    assert len(bodies) >= 3
    for b in bodies:
        if b["state"] == "building":
            assert b["fields"] == before["fields"] and b["researched_at"] == before["researched_at"]
        else:
            assert b["fields"] == after["fields"]
    for h in hist:
        assert h == h_before or h == hist[-1], "history changed in more than one step"
    assert all(a == before for a in asof), "?as_of= changed while a later build ran"


def test_R3_CON_04_fifty_in_flight_on_the_new_endpoints(fresh):
    api, mock = fresh
    tok = api.token(0)
    s3lib.run(api, mock, tok, NG, [{"epoch": 0, "clock": T0}, {"epoch": 1, "clock": "2026-03-10T09:00:00+00:00"}])
    clients = [Api() for _ in range(5)]

    def one(i):
        c = clients[i % 5]
        t0 = time.monotonic()
        k = i % 5
        if k == 0:
            r = s3lib.history(c, tok, NG)
        elif k == 1:
            r = s3lib.changes(c, tok, limit=2)
        elif k == 2:
            r = s3lib.as_of(c, tok, NG, T0)
        elif k == 3:
            r = s3lib.values(c, tok, NG, "2026-03-15", "2026-03-10T09:00:00+00:00")
        else:
            r = c.get(tok, NG)
        return r.status_code, time.monotonic() - t0

    with cf.ThreadPoolExecutor(50) as ex:
        res = list(ex.map(one, range(200)))
    assert all(s == 200 for s, _ in res), res
    assert max(t for _, t in res) < 5.0


@pytest.mark.slow
def test_R3_NFR_01_many_builds_keep_the_new_reads_fast(fresh):
    """Thirty builds of one dossier: history, feed, as_of and /values still answer well inside 5 s."""
    api, mock = fresh
    tok = api.token(0)
    api.clock(T0)
    for i in range(30):
        mock.epoch(i % 2)
        if i:
            api.refresh(tok, PR)
        else:
            api.create(tok, PR)
        api.wait(tok, PR)
    feed = s3lib.all_changes(api, tok)
    assert len(feed) == 58
    for fn in (lambda: s3lib.history(api, tok, PR), lambda: s3lib.changes(api, tok, limit=200),
               lambda: s3lib.as_of(api, tok, PR, T0), lambda: s3lib.values(api, tok, PR, "2026-02-01", T0),
               lambda: s3lib.values(api, tok, PR, "2026-02-01")):
        t0 = time.monotonic()
        assert fn().status_code == 200
        assert time.monotonic() - t0 < 2.0
