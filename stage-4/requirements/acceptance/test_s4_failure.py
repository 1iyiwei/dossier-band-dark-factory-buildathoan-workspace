"""Stage 4 (API): provider failure. A provider may answer with any 5xx or 429; the build continues.
- every call to one or more providers fails while nimble answers: `ready`, every field known that
  the reachable evidence supports (all eight fields, origins included, judged by the oracle);
- every research run fails while searches and extracts answer: same;
- every call to every provider fails: `failed`, within the time bound of §8, fields as they were;
- a refused call costs nothing: `spent_units` equals what the mock billed.
Companies are all-searchable, so nothing needs a research claim to be reached."""
import time

import pytest

import oracle
import s3lib
import s4lib
from lib import T0, assert_dossier_shape, parse_ts, total_cost
from s4lib import ALL_METHODS, billed, build_with, oracle_problems, wait_batch

pytestmark = pytest.mark.corpus

QB = "quillon-bio.test"
LF = "linden-forge.test"
CV = "corvane-systems.test"
TAL = "talloway-systems.test"

SPECS = {
    "tavily-errors": [("tavily", ALL_METHODS, "error")],
    "tavily-429": [("tavily", ALL_METHODS, "rate_limit")],
    "nimble-research-errors": [("nimble", ["research"], "error")],
    "browser-vendors-errors": [("kernel", ["session"], "error"), ("browserbase", ["session", "browse"], "error")],
    "tavily-and-research-and-browsers": [("tavily", ALL_METHODS, "error"), ("nimble", ["research"], "error"),
                                         ("kernel", ["session"], "error"), ("browserbase", ["session", "browse"], "error")],
    "tavily-search-only": [("tavily", ["search"], "error")],
}


@pytest.mark.parametrize("name", list(SPECS), ids=list(SPECS))
@pytest.mark.parametrize("domain", [QB, LF], ids=["quillon", "linden"])
def test_R4_FAIL_01_providers_failing_while_nimble_answers(fresh, domain, name):
    """R4-FAIL-01/02/04: ready, every field known that the evidence supports, refused calls free."""
    api, mock = fresh
    tok = api.token(0)
    snap, seg, took = build_with(api, mock, tok, domain, SPECS[name], epoch=0, clock=T0)
    assert snap["state"] == "ready", (name, snap["state"])
    assert_dossier_shape(snap, domain)
    probs = oracle_problems(snap, domain, seg, 0, T0)
    assert not probs, "\n".join(probs)
    assert billed(seg) <= 80 and snap["spent_units"] == billed(seg)
    assert all(e["cost"] == 0 for e in seg if e["status"] >= 400)


def test_R4_FAIL_02_every_research_run_fails_for_a_corpus_company_with_investors(fresh):
    api, mock = fresh
    tok = api.token(0)
    snap, seg, _ = build_with(api, mock, tok, QB, [("nimble", ["research"], "error")], epoch=0, clock=T0)
    assert snap["state"] == "ready"
    assert snap["fields"]["investors"]["value"] == ["Bluebird Capital", "General Atlantic", "Northwind Ventures"]
    assert snap["fields"]["founded_year"]["value"] == 2016
    assert not [e for e in seg if e["method"] == "research" and e["status"] < 400]


def test_R4_FAIL_03_every_call_to_every_provider_fails_first_build(fresh):
    """R4-FAIL-03: `failed`, within 10 s, nothing was billed, every field unknown."""
    api, mock = fresh
    tok = api.token(0)
    s4lib.all_fail(mock)
    try:
        n0 = len(mock.log())
        t0 = time.monotonic()
        assert api.create(tok, TAL).status_code == 202
        snap = api.wait(tok, TAL, timeout=30, interval=0.1)
        took = time.monotonic() - t0
        seg = mock.log()[n0:]
    finally:
        s4lib.all_fail(mock, on=False)
    assert snap["state"] == "failed", snap["state"]
    assert took <= 10.5, f"a build whose every call fails took {took:.1f}s"
    assert snap["researched_at"] is None and snap["spent_units"] == 0 == billed(seg)
    assert_dossier_shape(snap, TAL)
    assert all(fv["value"] is None and fv["status"] == "unknown" and fv["citations"] == []
               for fv in snap["fields"].values())
    assert s3lib.history(api, tok, TAL).json()["fields"] == {f: [] for f in oracle.ALL_FIELDS}
    assert s3lib.all_changes(api, tok) == []
    assert api.list(tok).json()["dossiers"][0]["state"] == "failed"


def test_R4_FAIL_04_a_failed_refresh_leaves_everything_as_it_was(fresh):
    api, mock = fresh
    tok = api.token(0)
    snap, seg, _ = build_with(api, mock, tok, QB, [], epoch=0, clock=T0)
    assert snap["state"] == "ready"
    hist = s3lib.history(api, tok, QB).json()
    feed = s3lib.all_changes(api, tok)
    s4lib.all_fail(mock)
    try:
        api.clock("2026-03-05T09:00:00+00:00")
        mock.epoch(4)
        t0 = time.monotonic()
        assert api.refresh(tok, QB).status_code == 202
        after = api.wait(tok, QB, timeout=30, interval=0.1)
        took = time.monotonic() - t0
    finally:
        s4lib.all_fail(mock, on=False)
    assert after["state"] == "failed" and took <= 10.5
    assert after["fields"] == snap["fields"]                      # incl. origins, corroborated, candidates
    assert after["researched_at"] == snap["researched_at"] and after["spent_units"] == snap["spent_units"]
    assert s3lib.history(api, tok, QB).json() == hist and s3lib.all_changes(api, tok) == feed
    # the last ready build is still what `as_of` serves
    assert s3lib.as_of(api, tok, QB, "2026-03-06T00:00:00+00:00").json()["fields"] == snap["fields"]


def test_R4_FAIL_05_failures_during_a_batch(fresh):
    """A batch with tavily down: every dossier is built from nimble; with every provider down
    every dossier fails and the batch is done at zero cost."""
    api, mock = fresh
    tok = api.token(0)
    doms = [QB, LF, CV]
    mock.fault("tavily", ALL_METHODS, "error")
    r = s4lib.batch_create(api, tok, doms, 500)
    assert r.status_code == 202
    done = wait_batch(api, tok, r.json()["batch_id"], timeout=120)
    mock.fault("tavily", ALL_METHODS, "none")
    assert done["state"] == "done" and [d["state"] for d in done["dossiers"]] == ["ready"] * 3
    log = mock.log()
    spent = s4lib.dossier_spent(api, tok, doms)
    assert done["spent_units"] == sum(spent.values()) == billed(log) and all(v <= 80 for v in spent.values())
    for d in doms:
        b = api.get(tok, d).json()
        probs = oracle_problems(b, d, log, 0, T0)
        assert not probs, (d, probs)

    api.reset()
    mock.reset(0)
    tok = api.token(0)
    s4lib.all_fail(mock)
    try:
        r = s4lib.batch_create(api, tok, [TAL, "acme-failing.test"], 300)
        assert r.status_code == 202
        done = wait_batch(api, tok, r.json()["batch_id"], timeout=60)
    finally:
        s4lib.all_fail(mock, on=False)
    assert done["state"] == "done" and done["spent_units"] == 0
    assert [d["state"] for d in done["dossiers"]] == ["failed", "failed"]


def test_R4_FAIL_06_a_single_error_is_retried_not_fatal(fresh):
    """The build may make the same request again: a 429 on the first attempt of every call
    (mock `throttle`) still gives the complete dossier."""
    api, mock = fresh
    tok = api.token(0)
    snap, seg, _ = build_with(api, mock, tok, QB, [("nimble", ALL_METHODS, "throttle"),
                                                   ("tavily", ALL_METHODS, "throttle")],
                              epoch=0, clock=T0, timeout=90)
    assert snap["state"] == "ready"
    assert snap["spent_units"] == billed(seg) <= 80
    probs = oracle_problems(snap, QB, seg, 0, T0)
    assert not probs, probs
