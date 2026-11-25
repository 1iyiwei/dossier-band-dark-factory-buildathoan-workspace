"""Stage 2 (browser): building, refresh, reload (latest read wins), lost responses, competing
clients, export/import around a signed-in browser."""
import json
import os
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

import oracle
from lib import USERS, Api, domain_queries, parse_ts
from ui_lib import (FIELDS, Net, body_json, lose_response, open_dossier, sign_in, ids_of, text,
                    tid, url)

pytestmark = pytest.mark.corpus

TAL = "talloway-systems.test"
PIV = "pivotal-reed.test"
OLD_BASE_URL = os.environ.get("OLD_BASE_URL", "").rstrip("/")


def slow(mock, search=3, extract=2):
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search"], "delay", seconds=search)
        mock.fault(p, ["extract"], "delay", seconds=extract)


def unslow(mock):
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract"], "none")


def dossier_reads(net, domain):
    return [r for r in net.reqs if r["method"] == "GET" and urlparse(r["url"]).path == f"/dossiers/{domain}"
            and r["type"] in ("fetch", "xhr", "document")]


# ------------------------------------------------------------------ building
def test_R_BLD_07_screen_follows_a_running_build_to_its_end(fresh, page):
    """While `building` the screen reads the dossier at least every 2 s, then shows the new fields
    without a manual reload."""
    api, mock = fresh
    tok = api.token(0)
    slow(mock, search=3, extract=2)
    assert api.create(tok, TAL).status_code == 202
    sign_in(page)
    net = Net(page)
    page.goto(url(f"/dossiers/{TAL}"))
    expect(tid(page, "dossier-state")).to_have_text("building")
    for f in FIELDS:
        expect(tid(page, f"field-{f}")).to_have_attribute("data-status", "unknown")
        expect(tid(page, f"field-value-{f}")).to_have_count(0)
    expect(tid(page, "dossier-researched-at")).to_have_count(0)           # null while nothing is ready
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=45_000)
    expect(tid(page, "field-value-legal_name")).to_have_attribute("data-value", "Talloway Systems, Inc.")
    expect(tid(page, "field-citations-ceo")).to_be_attached()
    expect(tid(page, "dossier-researched-at")).to_be_visible()
    reads = sorted(r["t"] for r in dossier_reads(net, TAL))
    assert len(reads) >= 2, f"{len(reads)} read(s) of the dossier while it built"
    gaps = [b - a for a, b in zip(reads, reads[1:])]
    assert max(gaps) <= 2.6, f"gap between reads {max(gaps):.2f}s: {gaps}"


def test_R_BLD_08_failed_build_is_shown_as_failed(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "error")
    assert api.create(tok, TAL).status_code == 202
    sign_in(page)
    page.goto(url(f"/dossiers/{TAL}"))
    expect(tid(page, "dossier-state")).to_have_text("failed", timeout=45_000)
    for f in FIELDS:
        expect(tid(page, f"field-{f}")).to_have_attribute("data-status", "unknown")
    expect(tid(page, "dossier-refresh")).to_be_visible()


# ------------------------------------------------------------------ refresh
def test_R_REF_05_refresh_button_starts_a_build_and_the_screen_follows_it(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, PIV)
    before = api.get(tok, PIV).json()
    sign_in(page)
    open_dossier(page, PIV)
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Hana Sato")
    net = Net(page)
    mock.epoch(1)
    api.clock("2026-03-02T09:00:00+00:00")
    slow(mock, search=2, extract=1)
    tid(page, "dossier-refresh").click()
    expect(tid(page, "dossier-state")).to_have_text("building")
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Hana Sato")  # last ready build
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=45_000)
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Leon Brandt")
    posts = net.matching("POST", f"/dossiers/{PIV}/refresh")
    assert len(posts) == 1 and posts[0]["headers"].get("idempotency-key"), posts
    after = api.get(tok, PIV).json()
    expect(tid(page, "dossier-spent")).to_have_attribute("data-units", str(after["spent_units"]))
    assert after["spent_units"] > before["spent_units"]
    expect(tid(page, "refresh-error")).to_have_count(0)
    expect(tid(page, "refresh-uncertain")).to_have_count(0)


def test_R_REF_06_refresh_while_another_client_build_runs_follows_that_build(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, TAL)
    sign_in(page)
    open_dossier(page, TAL)
    slow(mock, search=3, extract=2)
    assert api.refresh(tok, TAL).status_code == 202                  # another client's build
    tid(page, "dossier-refresh").click()                             # answered 202 like any other
    expect(tid(page, "refresh-error")).to_have_count(0)
    expect(tid(page, "refresh-uncertain")).to_have_count(0)
    expect(tid(page, "dossier-state")).to_have_text("building")
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=45_000)
    assert len(domain_queries(mock.log(), TAL)) == 2, "a second concurrent build was started"


def test_R_REF_07_refused_refresh_shows_refresh_error_not_uncertain(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    sign_in(page)                                                    # the browser's token
    empty = api.req("GET", "/_test/export", timeout=10.0).json()     # state without any dossier
    api.build(tok, TAL)
    open_dossier(page, TAL)
    assert api.req("POST", "/_test/import", json=empty, timeout=10.0).status_code == 204
    tid(page, "dossier-refresh").click()                             # 404: the dossier is gone
    expect(tid(page, "refresh-error")).to_be_visible()
    assert text(tid(page, "refresh-error"))
    expect(tid(page, "refresh-uncertain")).to_have_count(0)
    assert mock.log() and len(domain_queries(mock.log(), TAL)) == 1  # no build was started


# ------------------------------------------------------------------ latest read wins
def test_R_RD_01_a_delayed_earlier_read_does_not_overwrite_a_later_one(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, PIV)
    sign_in(page)
    open_dossier(page, PIV)
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Hana Sato")
    held = {"route": None, "resp": None, "armed": True, "n": 0}

    def handler(route, request):
        p = urlparse(request.url).path
        if (request.method == "GET" and p == f"/dossiers/{PIV}"
                and request.resource_type in ("fetch", "xhr")):
            held["n"] += 1
            if held["armed"]:
                held["armed"] = False
                held["resp"] = route.fetch()          # the server answers now (epoch 0) ...
                held["route"] = route                 # ... but the page gets it only later
                return None
        return route.continue_()

    page.route("**/*", handler)
    tid(page, "dossier-reload").click()               # read #1: held
    deadline = time.monotonic() + 3
    while held["route"] is None and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    mock.epoch(1)                                      # the dossier changes on the server
    api.clock("2026-03-02T09:00:00+00:00")
    assert api.refresh(tok, PIV).status_code == 202
    api.wait(tok, PIV)
    try:
        tid(page, "dossier-reload").click(timeout=3000)   # read #2 (later), answered at once
    except Exception:                                  # noqa: BLE001
        if held["route"] is not None:
            held["route"].fulfill(response=held["resp"])
        pytest.skip("the reload control is disabled while a read is in flight: no ordering to test")
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Leon Brandt")
    if held["route"] is not None:
        held["route"].fulfill(response=held["resp"])  # the stale read arrives last
        page.wait_for_timeout(1500)
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Leon Brandt")
    expect(tid(page, "dossier-state")).to_have_text("ready")
    assert parse_ts(api.get(tok, PIV).json()["researched_at"]) == parse_ts("2026-03-02T09:00:00+00:00")


def test_R_RD_02_out_of_order_reads_while_building(fresh, page):
    """The reads made while `building` follow the same rule: the first read's answer (building,
    no fields) is held until after the build has ended and the screen has shown `ready`."""
    api, mock = fresh
    tok = api.token(0)
    slow(mock, search=2, extract=1)
    assert api.create(tok, TAL).status_code == 202
    sign_in(page)
    held = {"route": None, "resp": None, "armed": False}

    def handler(route, request):
        p = urlparse(request.url).path
        if (request.method == "GET" and p == f"/dossiers/{TAL}"
                and request.resource_type in ("fetch", "xhr") and held["armed"]):
            held["armed"] = False
            held["resp"] = route.fetch()
            held["route"] = route
            return None
        return route.continue_()

    page.route("**/*", handler)
    page.goto(url(f"/dossiers/{TAL}"))
    expect(tid(page, "dossier-state")).to_have_text("building")
    held["armed"] = True                              # hold the next read made by the screen
    deadline = time.monotonic() + 5
    while held["route"] is None and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    if held["route"] is None:
        pytest.skip("the screen makes no script reads while building (full navigation): nothing to order")
    api.wait(tok, TAL, timeout=45)
    tid(page, "dossier-reload").click()
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=30_000)
    held["route"].fulfill(response=held["resp"])      # a `building` answer, arriving late
    page.wait_for_timeout(2500)
    expect(tid(page, "dossier-state")).to_have_text("ready")
    expect(tid(page, "field-value-legal_name")).to_have_attribute("data-value", "Talloway Systems, Inc.")


# ------------------------------------------------------------------ lost responses
def attempts_ok(rec, n=2):
    assert len(rec["attempts"]) >= n, rec
    keys = {a["key"] for a in rec["attempts"][:n]}
    assert len(keys) == 1 and None not in keys and "" not in keys, rec["attempts"]
    bodies = [body_json(a["body"]) for a in rec["attempts"][:n]]
    assert all(b == bodies[0] for b in bodies), bodies


@pytest.mark.parametrize("after_commit", [True, False], ids=["lost-after-commit", "lost-before-send"])
def test_R_UNC_01_research_response_lost_is_uncertain_and_retry_is_the_same_request(
        fresh, page, after_commit):
    api, mock = fresh
    tok = api.token(0)
    sign_in(page)
    page.goto(url("/"))
    statuses = []
    page.on("response", lambda r: statuses.append((r.request.method, urlparse(r.url).path, r.status)))
    rec = lose_response(page, "POST", lambda p: p == "/dossiers", after_commit=after_commit)
    tid(page, "research-domain").fill(TAL)
    tid(page, "research-submit").click()
    expect(tid(page, "research-uncertain")).to_be_visible()
    assert text(tid(page, "research-uncertain"))
    expect(tid(page, "research-error")).to_have_count(0)               # not a confirmed refusal
    assert page.url == url("/")
    assert (api.get(tok, TAL).status_code == 200) == after_commit
    tid(page, "research-submit").click()                               # retry
    page.wait_for_url(url(f"/dossiers/{TAL}"))
    expect(tid(page, "dossier-domain")).to_have_text(TAL)
    expect(tid(page, "research-uncertain")).to_have_count(0)
    expect(tid(page, "research-error")).to_have_count(0)
    attempts_ok(rec)
    posts = [s for s in statuses if s[0] == "POST" and s[1] == "/dossiers"]
    assert posts and posts[-1][2] == (200 if after_commit else 202), posts
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=45_000)
    assert len(domain_queries(mock.log(), TAL)) == 1                   # at most one build


def test_R_UNC_02_refresh_response_lost_is_uncertain_and_retry_is_the_same_request(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, TAL)
    sign_in(page)
    open_dossier(page, TAL)
    rec = lose_response(page, "POST", lambda p: p.endswith("/refresh"), after_commit=True)
    tid(page, "dossier-refresh").click()
    expect(tid(page, "refresh-uncertain")).to_be_visible()
    assert text(tid(page, "refresh-uncertain"))
    expect(tid(page, "refresh-error")).to_have_count(0)
    tid(page, "dossier-refresh").click()                               # retry, same key
    expect(tid(page, "refresh-uncertain")).to_have_count(0)
    expect(tid(page, "refresh-error")).to_have_count(0)
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=45_000)
    attempts_ok(rec)
    assert len(domain_queries(mock.log(), TAL)) == 2                   # first build + one refresh


def test_R_UNC_03_lost_research_response_is_recovered_after_export_import(fresh, page):
    """A research request whose response was lost before an export stays retryable with the same
    key and body after import; the UI recovers the original response and shows the dossier."""
    api, mock = fresh
    tok = api.token(0)
    sign_in(page)
    page.goto(url("/"))
    rec = lose_response(page, "POST", lambda p: p == "/dossiers", after_commit=True)
    tid(page, "research-domain").fill(TAL)
    tid(page, "research-submit").click()
    expect(tid(page, "research-uncertain")).to_be_visible()
    assert api.wait(tok, TAL)["state"] == "ready"
    exp = api.req("GET", "/_test/export", timeout=10.0).json()
    api.reset()
    assert api.req("POST", "/_test/import", json=exp, timeout=10.0).status_code == 204
    tid(page, "research-submit").click()
    page.wait_for_url(url(f"/dossiers/{TAL}"))
    expect(tid(page, "dossier-state")).to_have_text("ready")
    expect(tid(page, "field-value-legal_name")).to_have_attribute("data-value", "Talloway Systems, Inc.")
    expect(tid(page, "research-uncertain")).to_have_count(0)
    attempts_ok(rec)
    assert len(domain_queries(mock.log(), TAL)) == 1


def test_R_UNC_04_lost_refresh_response_is_recovered_after_export_import(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, TAL)
    sign_in(page)
    open_dossier(page, TAL)
    rec = lose_response(page, "POST", lambda p: p.endswith("/refresh"), after_commit=True)
    tid(page, "dossier-refresh").click()
    expect(tid(page, "refresh-uncertain")).to_be_visible()
    assert api.wait(tok, TAL)["state"] == "ready"
    exp = api.req("GET", "/_test/export", timeout=10.0).json()
    api.reset()
    assert api.req("POST", "/_test/import", json=exp, timeout=10.0).status_code == 204
    n = len(domain_queries(mock.log(), TAL))
    tid(page, "dossier-refresh").click()
    expect(tid(page, "refresh-uncertain")).to_have_count(0)
    expect(tid(page, "refresh-error")).to_have_count(0)
    expect(tid(page, "dossier-state")).to_have_text("ready")
    attempts_ok(rec)
    assert len(domain_queries(mock.log(), TAL)) == n, "the retry started another build"


# ------------------------------------------------------------------ export / import around a browser
def test_R_UPG_06_signed_in_browser_stays_signed_in_across_export_import(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, TAL)
    sign_in(page)
    page.goto(url("/"))
    expect(tid(page, f"dossier-item-{TAL}")).to_be_visible()
    exp = api.req("GET", "/_test/export", timeout=10.0).json()
    api.reset()                                                        # everything gone ...
    assert api.req("POST", "/_test/import", json=exp, timeout=10.0).status_code == 204   # ... and back
    page.reload()
    expect(tid(page, "current-user")).to_contain_text(USERS[0]["display_name"])
    expect(tid(page, f"dossier-item-{TAL}")).to_be_visible()
    open_dossier(page, TAL)
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Mara Quintero")


@pytest.mark.skipif(not OLD_BASE_URL, reason="OLD_BASE_URL (stage-1 service) not set")
def test_R_UPG_07_imported_stage_1_dossiers_appear_on_every_screen(fresh, page):
    api, mock = fresh
    old = Api(OLD_BASE_URL)
    mock.reset(0)
    old.reset()
    otok = old.token(0)
    for d in (TAL, "ledgerline-partners.test", "nowhere-at-all.test"):
        assert old.build(otok, d, timeout=60)["state"] == "ready"
    before = {d: old.get(otok, d).json() for d in (TAL, "ledgerline-partners.test")}
    export = old.req("GET", "/_test/export", timeout=10.0).json()
    mock.reset(0)
    api.reset()
    assert api.req("POST", "/_test/import", json=export, timeout=10.0).status_code == 204
    sign_in(page)                                                      # a stage-1 account, stage-2 UI
    page.goto(url("/"))
    for d in (TAL, "ledgerline-partners.test", "nowhere-at-all.test"):
        expect(tid(page, f"dossier-item-{d}")).to_have_attribute("data-state", "ready")
    expect(tid(page, f"dossier-item-{TAL}")).to_contain_text("Talloway Systems, Inc.")
    open_dossier(page, TAL)
    for f in FIELDS:
        fv = before[TAL]["fields"][f]
        expect(tid(page, f"field-{f}")).to_have_attribute("data-status", fv["status"])
        if fv["value"] is not None:
            expect(tid(page, f"field-value-{f}")).to_have_attribute("data-value", str(fv["value"]))
            assert tid(page, f"citation-{f}-1").count() == 1
    page.goto(url(f"/dossiers/{TAL}/evidence"))
    now = api.get(api.token(0), TAL).json()
    for f in FIELDS:
        cands = now["fields"][f]["candidates"]
        for i, c in enumerate(cands, 1):
            el = tid(page, f"candidate-{f}-{i}")
            expect(el).to_have_attribute("data-url", c["url"])
            expect(el).to_have_attribute("data-selected", "true" if c["selected"] else "false")
            assert (el.get_attribute("data-published-at") or "") == ""   # none recorded: empty
        if not cands:
            expect(tid(page, f"evidence-empty-{f}")).to_be_visible()
    page.goto(url("/contested"))
    expect(tid(page, "contested-list").or_(tid(page, "empty-contested"))).to_be_visible()
