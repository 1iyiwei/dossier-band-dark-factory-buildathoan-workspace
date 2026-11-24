"""Stage 2 (browser): product and visual direction, measurable parts only — layout at 375 CSS px
and at desktop width (no horizontal page scrolling), visible labels, apparent keyboard focus,
text contrast, visually distinct states, nothing loaded from outside the image, consistent
navigation. Everything a person must judge (calm, legible, evidence-first) is for the UX reviewer."""
import re

import pytest
from playwright.sync_api import expect

from lib import BASE_URL, USERS
from ui_lib import (CONTRAST_JS, STYLE_SIG_JS, VIEWPORTS, Net, no_horizontal_scroll, sign_in, ids_of,
                    text, tid, url)

pytestmark = pytest.mark.corpus

TAL = "talloway-systems.test"
HAR = "harlow-instruments.test"
TARN = "tarn-biotech.test"
NOWHERE = "nowhere-at-all.test"
KEST = "kestrel-optics.test"

ROUTES = [
    "/", "/contested", "/signup", "/login", f"/dossiers/{HAR}", f"/dossiers/{HAR}/evidence",
    f"/dossiers/{TARN}", f"/dossiers/{NOWHERE}", "/dossiers/no-such-company.test",
]


@pytest.fixture()
def seeded(fresh):
    api, mock = fresh
    tok = api.token(0)
    for d in (HAR, TARN, TAL, NOWHERE):
        assert api.build(tok, d)["state"] == "ready"
    return api, mock, tok


@pytest.mark.parametrize("vp", ["mobile", "desktop"])
def test_R_VIS_01_no_horizontal_scrolling_on_any_route(seeded, new_page, vp):
    page = new_page(vp)
    sign_in(page)
    bad = []
    for path in ROUTES:
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
        ok, info = no_horizontal_scroll(page)
        if not ok:
            bad.append((path, info))
    assert not bad, bad


@pytest.mark.parametrize("vp", ["mobile", "desktop"])
def test_R_VIS_01_signed_out_routes_fit_too(seeded, new_page, vp):
    page = new_page(vp)
    for path in ("/login", "/signup"):
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
        ok, info = no_horizontal_scroll(page)
        assert ok, (path, info)


@pytest.mark.parametrize("vp", ["mobile", "desktop"])
def test_R_VIS_02_required_flows_are_usable_at_both_widths(seeded, new_page, vp):
    """Controls of every flow are visible and clickable at this width (not clipped, not covered)."""
    api, mock, tok = seeded
    page = new_page(vp)
    sign_in(page)
    page.goto(url("/"))
    for name in ("research-domain", "research-submit", "dossier-search", f"dossier-item-{HAR}"):
        expect(tid(page, name)).to_be_visible()
        tid(page, name).scroll_into_view_if_needed()
        box = tid(page, name).bounding_box()
        assert box and box["width"] > 0 and box["x"] >= -1 and box["x"] + box["width"] <= VIEWPORTS[vp]["width"] + 1, (name, box)
    tid(page, f"dossier-item-{HAR}").click()
    for name in ("dossier-state", "dossier-refresh", "dossier-reload", "dossier-evidence-link",
                 "field-ceo", "field-value-ceo", "citation-ceo-1"):
        expect(tid(page, name)).to_be_visible()
        box = tid(page, name).bounding_box()
        assert box["x"] >= -1 and box["x"] + box["width"] <= VIEWPORTS[vp]["width"] + 1, (name, box)
    tid(page, "dossier-evidence-link").click()
    expect(tid(page, "candidate-ceo-1")).to_be_visible()
    page.goto(url("/contested"))
    expect(tid(page, f"contested-item-{HAR}-ceo")).to_be_visible()
    page = new_page(vp)                                  # signed out
    page.goto(url("/signup"))
    for name in ("signup-email", "signup-password", "signup-display-name", "signup-submit"):
        expect(tid(page, name)).to_be_visible()


FORM_INPUTS = {
    "/login": ["login-email", "login-password"],
    "/signup": ["signup-email", "signup-password", "signup-display-name"],
    "/": ["research-domain", "dossier-search"],
}


@pytest.mark.parametrize("vp", ["mobile", "desktop"])
def test_R_VIS_03_every_input_has_a_visible_label(seeded, new_page, vp):
    page = new_page(vp)
    missing = []
    for path, names in FORM_INPUTS.items():
        if path == "/":
            sign_in(page)
        page.goto(url(path))
        for n in names:
            info = tid(page, n).evaluate("""el => {
                const labels = el.labels ? [...el.labels] : [];
                const byFor = el.id ? [...document.querySelectorAll('label[for="' + CSS.escape(el.id) + '"]')] : [];
                const lb = el.getAttribute('aria-labelledby');
                const refd = lb ? lb.split(/\\s+/).map(i => document.getElementById(i)).filter(Boolean) : [];
                const vis = [...labels, ...byFor, ...refd].filter(l => {
                    const r = l.getBoundingClientRect(); const s = getComputedStyle(l);
                    return (l.textContent || '').trim() && r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                        && s.display !== 'none' && parseFloat(s.opacity) > 0;
                });
                return vis.length;
            }""")
            if not info:
                missing.append((path, n))
    assert not missing, f"inputs without a visible label: {missing}"


FOCUSABLE = {
    "/login": ["login-email", "login-password", "login-submit"],
    "/": ["research-domain", "research-submit", "dossier-search"],
    f"/dossiers/{HAR}": ["dossier-refresh", "dossier-reload", "dossier-evidence-link"],
}


def focus_signature(page, name):
    return tid(page, name).evaluate("""el => { const s = getComputedStyle(el);
        return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderTopColor,
                s.borderTopWidth, s.backgroundColor, s.color, s.textDecorationLine].join('|'); }""")


@pytest.mark.parametrize("vp", ["mobile", "desktop"])
def test_R_VIS_04_keyboard_focus_is_apparent(seeded, new_page, vp):
    """Reaching a control with Tab changes how it looks (outline, shadow, border or colours)."""
    page = new_page(vp)
    bad = []
    for path, names in FOCUSABLE.items():
        if path != "/login":
            sign_in(page)
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
        before = {n: focus_signature(page, n) for n in names}
        page.evaluate("() => { document.activeElement && document.activeElement.blur(); }")
        seen = set()
        for _ in range(80):
            page.keyboard.press("Tab")
            active = page.evaluate("() => document.activeElement && document.activeElement.getAttribute('data-testid')")
            if active in names and active not in seen:
                seen.add(active)
                after = focus_signature(page, active)
                if after == before[active]:
                    bad.append((path, active, after))
            if seen == set(names):
                break
        missed = set(names) - seen
        if missed:
            bad.append((path, "not reachable with Tab", sorted(missed)))
    assert not bad, bad


CONTRAST_TARGETS = [
    ("/login", ["login-submit", "login-email"]),
    ("/", ["research-submit", f"dossier-item-{HAR}"]),
    (f"/dossiers/{HAR}", ["dossier-state", "dossier-domain", "field-value-ceo", "citation-ceo-1",
                          "dossier-refresh", "dossier-evidence-link"]),
    (f"/dossiers/{TARN}", ["field-value-hq_city", "field-value-legal_name", "citation-hq_city-1"]),
    (f"/dossiers/{HAR}/evidence", ["candidate-ceo-1", "candidate-ceo-3"]),
    ("/contested", [f"contested-item-{HAR}-ceo"]),
]


@pytest.mark.parametrize("vp", ["mobile", "desktop"])
def test_R_VIS_05_text_contrast(seeded, new_page, vp):
    """WCAG 2.x AA: 4.5:1 for normal text, 3:1 for large text, measured on the elements that carry
    the dossier's values (elements on a background image are skipped)."""
    page = new_page(vp)
    sign_in(page)
    low = []
    for path, names in CONTRAST_TARGETS:
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
        for n in names:
            el = tid(page, n)
            if not el.count():
                continue
            descendants = el.evaluate_all("""els => els.flatMap(e => [e, ...e.querySelectorAll('*')])
                .filter(x => x.childNodes.length && [...x.childNodes].some(c => c.nodeType === 3 && c.textContent.trim()))
                .map(x => { x.setAttribute('data-ct', '1'); return 1; }).length""")
            for i in range(min(descendants, 8)):
                r = page.locator(f"[data-testid='{n}'] [data-ct], [data-testid='{n}'][data-ct]").nth(i).evaluate(CONTRAST_JS)
                if not r or r.get("skip"):
                    continue
                large = r["px"] >= 24 or (r["bold"] and r["px"] >= 18.66)
                need = 3.0 if large else 4.5
                if r["ratio"] < need:
                    low.append((path, n, round(r["ratio"], 2), need))
    assert not low, low


def test_R_VIS_06_field_statuses_are_visually_distinct(seeded, new_page):
    """known / contested / unknown fields differ in how they look (colour, background, border or
    weight), not only in an attribute (tarn-biotech has all three)."""
    page = new_page("desktop")
    sign_in(page)
    page.goto(url(f"/dossiers/{TARN}"))
    expect(tid(page, "field-hq_city")).to_have_attribute("data-status", "known")
    sig = {}
    for f, status in (("hq_city", "known"), ("legal_name", "contested"), ("ceo", "unknown")):
        el = tid(page, f"field-{f}")
        expect(el).to_have_attribute("data-status", status)
        sig[status] = el.evaluate(STYLE_SIG_JS)
    assert sig["known"] != sig["unknown"], "known and unknown fields look the same"
    assert sig["known"] != sig["contested"], "known and contested fields look the same"
    assert sig["contested"] != sig["unknown"], "contested and unknown fields look the same"
    expect(tid(page, "field-contested-legal_name")).to_be_visible()        # a visible marker


def test_R_VIS_07_dossier_states_are_visually_distinct(fresh, new_page):
    api, mock = fresh
    tok = api.token(0)
    assert api.build(tok, TARN)["state"] == "ready"
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "error")
    api.create(tok, "lumen-textiles.test")
    assert api.wait(tok, "lumen-textiles.test", timeout=60)["state"] == "failed"
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "none")
        mock.fault(p, ["search"], "delay", seconds=10)
    api.create(tok, KEST)
    page = new_page("desktop")
    sign_in(page)
    sig = {}
    for d, state in ((TARN, "ready"), ("lumen-textiles.test", "failed"), (KEST, "building")):
        page.goto(url(f"/dossiers/{d}"))
        expect(tid(page, "dossier-state")).to_have_text(state)
        sig[state] = tid(page, "dossier-state").evaluate(STYLE_SIG_JS)
    assert len({tuple(v) for v in sig.values()}) == 3, "building / ready / failed look alike"


def test_R_VIS_08_nothing_is_loaded_from_outside_the_service(seeded, new_page):
    page = new_page("desktop")
    net = Net(page)
    sign_in(page)
    for path in ROUTES:
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
    foreign = sorted({r["url"] for r in net.reqs
                      if not r["url"].startswith(BASE_URL) and not r["url"].startswith(("data:", "blob:"))})
    assert not foreign, foreign


def test_R_VIS_09_navigation_is_consistent_and_current_user_is_everywhere(seeded, new_page):
    page = new_page("desktop")
    sign_in(page)
    nav_sets = []
    for path in ("/", "/contested", f"/dossiers/{HAR}", f"/dossiers/{HAR}/evidence"):
        page.goto(url(path))
        expect(tid(page, "current-user")).to_be_visible()
        expect(tid(page, "logout-button")).to_be_visible()
        links = page.eval_on_selector_all("a[href]", "els => els.map(a => new URL(a.href).pathname)")
        nav_sets.append({p for p in links if p in ("/", "/contested")})
    assert all(s == {"/", "/contested"} for s in nav_sets), nav_sets


def test_R_VIS_10_empty_loading_and_error_states_have_text(fresh, new_page):
    api, _ = fresh
    page = new_page("mobile")
    sign_in(page)
    page.goto(url("/"))
    expect(tid(page, "empty-dossiers")).to_be_visible()
    assert len(text(tid(page, "empty-dossiers"))) >= 3
    page.goto(url("/contested"))
    assert len(text(tid(page, "empty-contested"))) >= 3
    page.goto(url("/dossiers/no-such-company.test"))
    assert len(text(tid(page, "dossier-not-found"))) >= 3
    ok, info = no_horizontal_scroll(page)
    assert ok, info


def test_R_VIS_11_values_and_times_are_formatted_for_people(seeded, new_page):
    """A floor for "format ... money and timestamps for people first": the funding value is not
    shown as a bare 8-digit integer and the research time is not a raw ISO string."""
    api, mock, tok = seeded
    page = new_page("desktop")
    sign_in(page)
    page.goto(url(f"/dossiers/{TAL}"))
    body = api.get(tok, TAL).json()
    money = text(tid(page, "field-value-funding_total"))
    assert money.strip() != str(body["fields"]["funding_total"]["value"]), money
    assert "$" in money or "USD" in money.upper() or "dollar" in money.lower(), money
    stamp = text(tid(page, "dossier-researched-at"))
    assert re.search(r"[A-Za-z]{3}", stamp) and "2026" in stamp, stamp      # a month name, not only ISO
    page.goto(url(f"/dossiers/{HAR}/evidence"))
    pubs = page.locator("[data-testid^='candidate-ceo-']").all_inner_texts()
    assert pubs and all(re.search(r"[A-Za-z]{3}", p) for p in pubs), pubs
