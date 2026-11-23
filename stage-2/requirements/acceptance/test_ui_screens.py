"""Stage 2 (browser): routes, signup/login, the dossier list, the dossier, evidence and contested
screens. Elements are found by `data-testid` only, as the specification lists them."""
import pytest
from playwright.sync_api import expect

import oracle
from lib import BASE_URL, USERS, assert_error, domain_queries, parse_ts
from ui_lib import (FIELDS, has_link_path, has_link_to, open_dossier, shows_value, sign_in, squash,
                    ids_of, text, tid, url)

pytestmark = pytest.mark.corpus

TAL = "talloway-systems.test"       # all six fields known
HAR = "harlow-instruments.test"     # every field contested
TARN = "tarn-biotech.test"          # known, contested and unknown fields
NOWHERE = "nowhere-at-all.test"     # ready, every field unknown


def build_all(api, tok, domains):
    out = {}
    for d in domains:
        out[d] = api.build(tok, d)
        assert out[d]["state"] == "ready", out[d]
    return out


def fmt_digits(n):                                 # a value "formatted for people" still shows its digits
    return str(n)


# ------------------------------------------------------------------ routes
@pytest.mark.parametrize("route,anchor,signed", [
    ("/", "research-domain", True),
    ("/dossiers/{d}", "dossier-domain", True),
    ("/dossiers/{d}/evidence", "evidence-legal_name", True),
    ("/contested", "contested-list|empty-contested", True),
    ("/signup", "signup-submit", False),
    ("/login", "login-submit", False),
], ids=["list", "dossier", "evidence", "contested", "signup", "login"])
def test_R_SCR_01_routes_are_reachable_by_url(fresh, page, route, anchor, signed):
    api, _ = fresh
    build_all(api, api.token(0), [TAL])
    if signed:
        sign_in(page)
    page.goto(url(route.format(d=TAL)))
    found = page.locator(", ".join(f"[data-testid='{n}']" for n in anchor.split("|")))
    expect(found.first).to_be_attached()


def test_R_SCR_02_other_screens_are_reachable_through_the_ui(fresh, page):
    """Contested, evidence, dossier, list: by clicking, starting from `/`."""
    api, _ = fresh
    build_all(api, api.token(0), [HAR])
    sign_in(page)
    page.goto(url("/"))
    contested = page.locator("a[href='/contested']").first
    expect(contested).to_be_visible()
    contested.click()
    expect(page).to_have_url(url("/contested"))
    tid(page, f"contested-item-{HAR}-ceo").click()
    expect(page).to_have_url(url(f"/dossiers/{HAR}/evidence"))
    page.go_back()
    page.goto(url("/"))
    tid(page, f"dossier-item-{HAR}").click()
    expect(page).to_have_url(url(f"/dossiers/{HAR}"))
    tid(page, "dossier-evidence-link").click()
    expect(page).to_have_url(url(f"/dossiers/{HAR}/evidence"))
    # every required route links back to the list
    for path in ("/contested", f"/dossiers/{HAR}", f"/dossiers/{HAR}/evidence"):
        page.goto(url(path))
        expect(page.locator("a[href='/']").first).to_be_visible()


# ------------------------------------------------------------------ signup / login
def test_R_AUTH_14_signup_through_the_ui_signs_in_everywhere_and_logs_out(fresh, page):
    api, _ = fresh
    page.goto(url("/signup"))
    expect(tid(page, "auth-error")).to_have_count(0)             # present only when there is one
    tid(page, "signup-email").fill("grace@example.org")
    tid(page, "signup-password").fill("analytical-engine")
    tid(page, "signup-display-name").fill("Grace Hopper")
    tid(page, "signup-submit").click()
    expect(tid(page, "current-user")).to_contain_text("Grace Hopper")
    assert api.login("grace@example.org", "analytical-engine").status_code == 200   # a real account
    for path in ("/", "/contested", "/dossiers/anything.test", "/dossiers/anything.test/evidence"):
        page.goto(url(path))
        expect(tid(page, "current-user")).to_contain_text("Grace Hopper")
    page.reload()
    expect(tid(page, "current-user")).to_be_visible()             # stays signed in
    tid(page, "logout-button").click()
    expect(tid(page, "current-user")).to_have_count(0)
    page.goto(url("/"))
    expect(tid(page, "current-user")).to_have_count(0)            # signed out for good
    expect(tid(page, "logout-button")).to_have_count(0)


def test_R_AUTH_15_login_through_the_ui_and_errors(fresh, page):
    api, _ = fresh
    page.goto(url("/login"))
    expect(tid(page, "auth-error")).to_have_count(0)
    tid(page, "login-email").fill(USERS[0]["email"])
    tid(page, "login-password").fill("not the password")
    tid(page, "login-submit").click()
    expect(tid(page, "auth-error")).to_be_visible()
    assert text(tid(page, "auth-error"))
    expect(tid(page, "current-user")).to_have_count(0)
    tid(page, "login-email").fill("nobody@example.org")
    tid(page, "login-submit").click()
    expect(tid(page, "auth-error")).to_be_visible()
    tid(page, "login-email").fill(USERS[0]["email"])
    tid(page, "login-password").fill(USERS[0]["password"])
    tid(page, "login-submit").click()
    expect(tid(page, "current-user")).to_contain_text(USERS[0]["display_name"])
    expect(tid(page, "auth-error")).to_have_count(0)


@pytest.mark.parametrize("email,password,name", [
    ("new@example.org", "short", "Newbie"),                     # password under 8 characters
    (USERS[0]["email"], "long-enough-pass", "Dup"),              # email taken
    ("new@example.org", "long-enough-pass", ""),                 # empty display name
    ("not-an-email", "long-enough-pass", "Bad Mail"),
], ids=["short-password", "email-taken", "empty-name", "bad-email"])
def test_R_AUTH_16_signup_errors_are_shown(fresh, page, email, password, name):
    api, _ = fresh
    page.goto(url("/signup"))
    tid(page, "signup-email").fill(email)
    tid(page, "signup-password").fill(password)
    tid(page, "signup-display-name").fill(name)
    tid(page, "signup-submit").click()
    expect(tid(page, "auth-error")).to_be_visible()
    expect(tid(page, "current-user")).to_have_count(0)
    # fixing the input succeeds and the error goes away
    tid(page, "signup-email").fill("fixed@example.org")
    tid(page, "signup-password").fill("long-enough-pass")
    tid(page, "signup-display-name").fill("Fixed")
    tid(page, "signup-submit").click()
    expect(tid(page, "current-user")).to_contain_text("Fixed")
    expect(tid(page, "auth-error")).to_have_count(0)


# ------------------------------------------------------------------ the list
def test_R_LST_06_list_order_items_and_search(fresh, page):
    api, _ = fresh
    tok = api.token(0)
    sign_in(page)
    page.goto(url("/"))
    expect(tid(page, "empty-dossiers")).to_be_visible()           # nothing to list yet
    expect(page.locator("[data-testid^='dossier-item-']")).to_have_count(0)
    build_all(api, tok, ["vantorra-health.test", TAL, HAR])
    page.goto(url("/"))
    expect(tid(page, "dossier-list")).to_be_visible()                 # client-side rendering: wait
    expect(tid(page, f"dossier-item-{TAL}")).to_be_visible()
    order = [n.removeprefix("dossier-item-") for n in ids_of(page, r"dossier-item-.+")]
    assert order == sorted(order) == [HAR, TAL, "vantorra-health.test"], order
    expect(tid(page, "empty-dossiers")).to_have_count(0)
    item = tid(page, f"dossier-item-{TAL}")
    expect(item).to_have_attribute("data-state", "ready")
    expect(item).to_contain_text(TAL)
    expect(item).to_contain_text("Talloway Systems, Inc.")        # the legal name when known
    assert has_link_path(item, f"/dossiers/{TAL}")
    expect(tid(page, f"dossier-item-{HAR}")).to_contain_text("Harlow Instruments plc")  # selected value
    # search = q of GET /dossiers
    for q in ("TALLOWAY", "inc.", "health", "instruments plc", "ltd", "zzz-no-match", "", ".test"):
        tid(page, "dossier-search").fill(q)
        want = sorted(i["domain"] for i in api.list(tok, q=q).json()["dossiers"])
        if want:
            expect(tid(page, f"dossier-item-{want[0]}")).to_be_visible()      # the list has caught up
            expect(page.locator("[data-testid^='dossier-item-']")).to_have_count(len(want))
            got = [n.removeprefix("dossier-item-") for n in ids_of(page, r"dossier-item-.+")]
            assert got == want, (q, got, want)
            expect(tid(page, "empty-dossiers")).to_have_count(0)
        else:
            expect(tid(page, "empty-dossiers")).to_be_visible()
            expect(page.locator("[data-testid^='dossier-item-']")).to_have_count(0)


def test_R_LST_07_item_state_attribute_and_unknown_legal_name(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    build_all(api, tok, [NOWHERE])
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "error")
    assert api.create(tok, "lumen-textiles.test").status_code == 202
    assert api.wait(tok, "lumen-textiles.test", timeout=60)["state"] == "failed"
    sign_in(page)
    page.goto(url("/"))
    expect(tid(page, f"dossier-item-{NOWHERE}")).to_have_attribute("data-state", "ready")
    expect(tid(page, "dossier-item-lumen-textiles.test")).to_have_attribute("data-state", "failed")


# ------------------------------------------------------------------ research
def test_R_RES_01_invalid_domain_is_refused_with_research_error(fresh, page):
    api, mock = fresh
    sign_in(page)
    page.goto(url("/"))
    expect(tid(page, "research-error")).to_have_count(0)
    for bad in ("https://acme.test/about", "not a domain", "single", "-bad-.test"):
        tid(page, "research-domain").fill(bad)
        tid(page, "research-submit").click()
        expect(tid(page, "research-error")).to_be_visible()
        assert text(tid(page, "research-error"))
        expect(tid(page, "research-uncertain")).to_have_count(0)
        assert page.url == url("/") or page.url == url("/#") or "/dossiers/" not in page.url
    assert api.list(api.token(0)).json()["dossiers"] == []
    assert mock.log() == []


def test_R_RES_02_research_opens_the_normalised_dossier_and_follows_the_build(fresh, page):
    api, mock = fresh
    sign_in(page)
    page.goto(url("/"))
    tid(page, "research-domain").fill(f"  WWW.{TAL.upper()}. ")
    tid(page, "research-submit").click()
    page.wait_for_url(url(f"/dossiers/{TAL}"))
    expect(tid(page, "dossier-domain")).to_have_text(TAL)
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=30_000)   # without a reload
    expect(tid(page, "field-value-legal_name")).to_have_attribute("data-value", "Talloway Systems, Inc.")
    assert len(domain_queries(mock.log(), TAL)) == 1


def test_R_RES_03_existing_dossier_from_another_client_opens_it_and_starts_no_build(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    sign_in(page)
    page.goto(url("/"))
    expect(tid(page, "empty-dossiers")).to_be_visible()           # this browser read the list: empty
    build_all(api, tok, [TAL])                                    # another client then researches it
    n = len(mock.log())
    tid(page, "research-domain").fill(TAL)
    tid(page, "research-submit").click()
    page.wait_for_url(url(f"/dossiers/{TAL}"))
    expect(tid(page, "dossier-state")).to_have_text("ready")
    expect(tid(page, "research-error")).to_have_count(0)
    assert len(mock.log()) == n, "opening an existing dossier made provider calls"
    assert len(domain_queries(mock.log(), TAL)) == 1


# ------------------------------------------------------------------ the dossier
def check_dossier_screen(page, body):
    domain = body["domain"]
    expect(tid(page, "dossier-domain")).to_have_text(domain)
    expect(tid(page, "dossier-state")).to_have_text(body["state"])
    expect(tid(page, "dossier-spent")).to_have_attribute("data-units", str(body["spent_units"]))
    assert str(body["spent_units"]) in text(tid(page, "dossier-spent")).replace(",", "")
    if body["researched_at"] is None:
        expect(tid(page, "dossier-researched-at")).to_have_count(0)
    else:
        expect(tid(page, "dossier-researched-at")).to_be_visible()
        assert text(tid(page, "dossier-researched-at"))
    field_ids = ids_of(page, r"field-(?!value-|contested-|citations-)[a-z_]+")
    assert field_ids == [f"field-{f}" for f in FIELDS], field_ids       # six, in the §4 order
    for f in FIELDS:
        fv = body["fields"][f]
        expect(tid(page, f"field-{f}")).to_have_attribute("data-status", fv["status"])
        if fv["value"] is None:
            expect(tid(page, f"field-value-{f}")).to_have_count(0)
        else:
            val = tid(page, f"field-value-{f}")
            expect(val).to_have_attribute("data-value", str(fv["value"]))
            assert text(val)
        expect(tid(page, f"field-contested-{f}")).to_have_count(1 if fv["status"] == "contested" else 0)
        cites = tid(page, f"field-citations-{f}")
        expect(cites).to_have_count(1)
        ids = [n for n in ids_of(page, rf"citation-{f}-\d+")]
        assert ids == [f"citation-{f}-{i}" for i in range(1, len(fv["citations"]) + 1)], (f, ids)
        for i, c in enumerate(fv["citations"], 1):
            el = tid(page, f"citation-{f}-{i}")
            assert squash(c["excerpt"]) in text(el), (f, i, c["excerpt"], text(el))
            assert has_link_to(el, c["url"]), (f, i, c["url"])
            expect(el).to_have_attribute("data-provider", c["provider"])
            assert tid(page, f"field-citations-{f}").locator(f"[data-testid='citation-{f}-{i}']").count() == 1
    expect(tid(page, "dossier-not-found")).to_have_count(0)
    assert has_link_path(tid(page, "dossier-evidence-link"), f"/dossiers/{domain}/evidence")


@pytest.mark.parametrize("domain", [TAL, HAR, TARN, NOWHERE])
def test_R_DOS_01_dossier_screen_shows_state_fields_citations(fresh, page, domain):
    api, _ = fresh
    tok = api.token(0)
    body = build_all(api, tok, [domain])[domain]
    sign_in(page)
    open_dossier(page, domain)
    check_dossier_screen(page, body)


def test_R_DOS_02_normalised_domain_in_the_route_and_not_found(fresh, page):
    api, _ = fresh
    build_all(api, api.token(0), [TAL])
    sign_in(page)
    page.goto(url(f"/dossiers/WWW.{TAL.upper()}"))
    expect(tid(page, "dossier-domain")).to_have_text(TAL)
    page.goto(url(f"/dossiers/{TAL}."))
    expect(tid(page, "dossier-domain")).to_have_text(TAL)
    page.goto(url("/dossiers/no-such-company.test"))
    expect(tid(page, "dossier-not-found")).to_be_visible()
    assert text(tid(page, "dossier-not-found"))
    expect(page.locator("[data-testid^='field-']")).to_have_count(0)
    page.goto(url(f"/dossiers/WWW.{TAL.upper()}/evidence"))
    expect(tid(page, "evidence-legal_name")).to_be_attached()


def test_R_DOS_03_reload_button_reads_again_without_a_build(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    d = "pivotal-reed.test"
    build_all(api, tok, [d])
    sign_in(page)
    open_dossier(page, d)
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Hana Sato")
    mock.epoch(1)                                                # the web changes ...
    api.clock("2026-03-02T09:00:00+00:00")
    assert api.refresh(tok, d).status_code == 202                # ... and another client refreshes
    api.wait(tok, d)
    n = len(domain_queries(mock.log(), d))
    tid(page, "dossier-reload").click()
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Leon Brandt")
    assert len(domain_queries(mock.log(), d)) == n, "reload started a build"
    assert parse_ts(api.get(tok, d).json()["researched_at"]) == parse_ts("2026-03-02T09:00:00+00:00")


# ------------------------------------------------------------------ evidence
def test_R_EVI_01_evidence_screen_lists_every_candidate_in_api_order(fresh, page):
    api, _ = fresh
    tok = api.token(0)
    body = build_all(api, tok, [HAR])[HAR]
    sign_in(page)
    page.goto(url(f"/dossiers/{HAR}/evidence"))
    expect(tid(page, "evidence-funding_total")).to_be_visible()
    expect(page.locator("[data-testid^='candidate-ceo-']").first).to_be_visible()
    ev_ids = ids_of(page, r"evidence-[a-z_]+")
    assert [i for i in ev_ids if i in {f"evidence-{f}" for f in FIELDS}] == [f"evidence-{f}" for f in FIELDS]
    for f in FIELDS:
        cands = body["fields"][f]["candidates"]
        box = tid(page, f"evidence-{f}")
        expect(box).to_be_visible()
        got = box.locator("[data-testid^='candidate-']").evaluate_all(
            "els => els.map(e => e.getAttribute('data-testid'))")
        assert got == [f"candidate-{f}-{i}" for i in range(1, len(cands) + 1)], (f, got)
        expect(tid(page, f"evidence-empty-{f}")).to_have_count(0)
        for i, c in enumerate(cands, 1):
            el = tid(page, f"candidate-{f}-{i}")
            expect(el).to_have_attribute("data-value", str(c["value"]))
            expect(el).to_have_attribute("data-provider", c["provider"])
            expect(el).to_have_attribute("data-kind", c["kind"])
            expect(el).to_have_attribute("data-url", c["url"])
            expect(el).to_have_attribute("data-selected", "true" if c["selected"] else "false")
            pub = el.get_attribute("data-published-at")
            if c["published_at"] is None:
                assert pub == "", pub
            else:
                assert parse_ts(pub) == parse_ts(c["published_at"]), (pub, c["published_at"])
            assert squash(c["excerpt"]) in text(el)
            assert shows_value(text(el), c["value"]), (f, i, c["value"], text(el))


def test_R_EVI_02_evidence_empty_state_and_null_publication(fresh, page):
    api, _ = fresh
    tok = api.token(0)
    body = build_all(api, tok, [TARN])[TARN]
    sign_in(page)
    page.goto(url(f"/dossiers/{TARN}/evidence"))
    for f in ("ceo", "founded_year"):                              # no candidate
        assert body["fields"][f]["candidates"] == []
        expect(tid(page, f"evidence-empty-{f}")).to_be_visible()
        expect(tid(page, f"evidence-{f}").locator("[data-testid^='candidate-']")).to_have_count(0)
    for f in ("hq_city", "legal_name"):
        expect(tid(page, f"evidence-empty-{f}")).to_have_count(0)
    lum = build_all(api, tok, ["lumen-textiles.test"])["lumen-textiles.test"]
    page.goto(url("/dossiers/lumen-textiles.test/evidence"))
    cands = lum["fields"]["founded_year"]["candidates"]
    for i, c in enumerate(cands, 1):
        pub = tid(page, f"candidate-founded_year-{i}").get_attribute("data-published-at")
        assert (pub == "") == (c["published_at"] is None), (i, pub)
    assert any(c["published_at"] is None for c in cands)


def test_R_EVI_03_unknown_dossier_has_empty_evidence_everywhere(fresh, page):
    api, _ = fresh
    build_all(api, api.token(0), [NOWHERE])
    sign_in(page)
    page.goto(url(f"/dossiers/{NOWHERE}/evidence"))
    for f in FIELDS:
        expect(tid(page, f"evidence-empty-{f}")).to_be_visible()


# ------------------------------------------------------------------ contested
def test_R_CON_04_contested_screen(fresh, page):
    api, _ = fresh
    tok = api.token(0)
    sign_in(page)
    page.goto(url("/contested"))
    expect(tid(page, "empty-contested")).to_be_visible()
    bodies = build_all(api, tok, [TARN, TAL, HAR, "ledgerline-partners.test"])
    page.goto(url("/contested"))
    expect(tid(page, "contested-list")).to_be_visible()               # client-side rendering: wait
    want = []
    for d in sorted(bodies):
        for f in FIELDS:
            if bodies[d]["fields"][f]["status"] == "contested":
                want.append((d, f))
    assert want and (TAL not in {d for d, _ in want})            # a known dossier has none
    got = ids_of(page, r"contested-item-.+")
    assert got == [f"contested-item-{d}-{f}" for d, f in want], (got, want)
    expect(tid(page, "empty-contested")).to_have_count(0)
    for d, f in want:
        fv = bodies[d]["fields"][f]
        el = tid(page, f"contested-item-{d}-{f}")
        expect(el).to_have_attribute("data-value", str(fv["value"]))
        t = text(el)
        low = t.lower()
        assert d in t and (f in low or f.replace("_", " ") in low), (d, f, t)
        for v in {c["value"] for c in fv["candidates"]}:
            assert shows_value(t, v), (d, f, v, t)
        assert has_link_path(el, f"/dossiers/{d}/evidence")
    # the list is the one the API's data gives, and shrinks when nothing is contested any more
    assert tid(page, "contested-list").count() == 1


def test_R_CON_05_contested_screen_empty_for_agreeing_dossiers(fresh, page):
    api, _ = fresh
    build_all(api, api.token(0), [TAL, NOWHERE])
    sign_in(page)
    page.goto(url("/contested"))
    expect(tid(page, "empty-contested")).to_be_visible()
    assert ids_of(page, r"contested-item-.+") == []
