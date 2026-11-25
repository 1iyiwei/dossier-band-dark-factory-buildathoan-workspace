"""Browser helpers for the stage-2 UI acceptance tests (Playwright, elements by data-testid only)."""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from lib import BASE_URL, USERS, Api

FIELDS = ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total"]
VIEWPORTS = {"mobile": {"width": 375, "height": 800}, "desktop": {"width": 1280, "height": 900}}


def url(path: str) -> str:
    return BASE_URL + path


def tid(page, name: str):
    return page.get_by_test_id(name)


def sign_in(page, i: int = 0):
    from playwright.sync_api import expect
    u = USERS[i]
    page.goto(url("/login"))
    tid(page, "login-email").fill(u["email"])
    tid(page, "login-password").fill(u["password"])
    tid(page, "login-submit").click()
    expect(tid(page, "current-user")).to_be_visible()
    expect(tid(page, "current-user")).to_contain_text(u["display_name"])


def open_dossier(page, domain: str, state: str = "ready"):
    from playwright.sync_api import expect
    page.goto(url(f"/dossiers/{domain}"))
    expect(tid(page, "dossier-state")).to_have_text(state)


def ids_of(page, pattern: str) -> list[str]:
    """data-testids fully matching `pattern`, in document order."""
    found = page.eval_on_selector_all(
        "[data-testid]", "els => els.map(e => e.getAttribute('data-testid'))")
    return [n for n in found if re.fullmatch(pattern, n)]


def link_hrefs(locator) -> list[str]:
    """href attributes of the element itself (if a link), its ancestor link and descendant links."""
    return locator.evaluate(
        "el => [el.closest('a[href]'), ...el.querySelectorAll('a[href]')]"
        ".filter(a => a).map(a => a.getAttribute('href'))")


def has_link_path(locator, path: str) -> bool:
    return locator.evaluate(
        "(el, path) => [el.closest('a[href]'), ...el.querySelectorAll('a[href]')]"
        ".some(a => a && new URL(a.getAttribute('href'), location.href).pathname === path)", path)


def has_link_to(locator, target: str) -> bool:
    return locator.evaluate(
        "(el, u) => [el, ...el.querySelectorAll('a')].some("
        "a => a.tagName === 'A' && a.getAttribute('href') === u)", target)


def squash(s: str) -> str:
    return " ".join((s or "").split())


def text(locator) -> str:
    return squash(locator.text_content())


def no_horizontal_scroll(page) -> tuple[bool, str]:
    r = page.evaluate("""() => ({sw: document.documentElement.scrollWidth,
        bw: document.body ? document.body.scrollWidth : 0, iw: window.innerWidth})""")
    return (r["sw"] <= r["iw"] and r["bw"] <= r["iw"]), json.dumps(r)


STYLE_SIG_JS = """el => {
  const props = ['color','backgroundColor','borderTopColor','borderLeftColor','outlineColor',
                 'fontWeight','textDecorationLine','fontStyle'];
  const out = new Set();
  for (const e of [el, ...el.querySelectorAll('*')]) {
    const s = getComputedStyle(e);
    out.add(props.map(p => s[p]).join('|'));
  }
  return [...out].sort();
}"""

CONTRAST_JS = """el => {
  function parse(c) { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x)); return {r:p[0], g:p[1], b:p[2], a: p.length > 3 ? p[3] : 1}; }
  function lum(c) { const f = v => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
    return 0.2126*f(c.r) + 0.7152*f(c.g) + 0.0722*f(c.b); }
  function over(top, bot) { const a = top.a; return {r: top.r*a + bot.r*(1-a), g: top.g*a + bot.g*(1-a), b: top.b*a + bot.b*(1-a), a: 1}; }
  const fg0 = parse(getComputedStyle(el).color); if (!fg0) return null;
  let layers = []; let n = el;
  while (n) { const s = getComputedStyle(n);
    if (s.backgroundImage && s.backgroundImage !== 'none') return {skip: 'background-image'};
    const bg = parse(s.backgroundColor); if (bg && bg.a > 0) { layers.push(bg); if (bg.a >= 1) break; }
    n = n.parentElement; }
  let base = {r:255, g:255, b:255, a:1};
  for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
  const fg = over(fg0, base);
  const l1 = lum(fg), l2 = lum(base); const hi = Math.max(l1, l2), lo = Math.min(l1, l2);
  const s = getComputedStyle(el); const px = parseFloat(s.fontSize); const bold = parseInt(s.fontWeight) >= 700;
  return {ratio: (hi + 0.05) / (lo + 0.05), px: px, bold: bold};
}"""


class Net:
    """Record the requests a page makes (method, url, resource type, timestamp)."""

    def __init__(self, page):
        self.reqs: list[dict] = []
        page.on("request", lambda r: self.reqs.append(
            {"method": r.method, "url": r.url, "type": r.resource_type, "t": time.monotonic(),
             "headers": r.headers, "post": r.post_data}))

    def matching(self, method=None, path=None, path_re=None):
        out = []
        for r in self.reqs:
            p = urlparse(r["url"]).path
            if method and r["method"] != method:
                continue
            if path is not None and p != path:
                continue
            if path_re and not re.fullmatch(path_re, p):
                continue
            out.append(r)
        return out


def lose_response(page, method: str, path_pred, *, after_commit=True, times=1):
    """Make the first `times` matching requests lose their response: with `after_commit` the
    request reaches the server and is answered, then the connection is cut before the page sees
    the answer; otherwise it is cut before reaching the server. Records the attempts."""
    rec = {"n": 0, "attempts": []}

    def handler(route, request):
        if request.method != method or not path_pred(urlparse(request.url).path):
            return route.continue_()
        rec["n"] += 1
        rec["attempts"].append({"key": request.headers.get("idempotency-key"),
                                "body": request.post_data})
        if rec["n"] <= times:
            if after_commit:
                route.fetch()
            return route.abort("connectionreset")
        return route.continue_()

    page.route("**/*", handler)
    return rec


def body_json(s):
    try:
        return json.loads(s) if s else None
    except ValueError:
        return s


def shows_value(t: str, v) -> bool:
    """Whether text `t` shows value `v` in some human format: a string as written; an integer in
    plain digits, with group separators, or as a compact amount (7M, 7 million, $7.0 M, 2k...)."""
    if isinstance(v, str):
        norm = lambda x: squash(x.replace("\u2013", "-").replace("\u2014", "-")).lower()   # noqa: E731
        return norm(v) in norm(t) or norm(v) in norm(t).replace(",", "")   # 1001-5000 shown as 1,001-5,000
    flat = re.sub(r"[\s,_\u202f\u00a0$]", "", t.lower())
    forms = {str(v)}
    for scale, names in ((10**9, ("b", "bn", "billion")), (10**6, ("m", "mn", "million")),
                         (10**3, ("k", "thousand"))):
        if v >= scale:
            q = v / scale
            for nm in names:
                forms |= {f"{q:g}{nm}", f"{q:.1f}{nm}", f"{q:.2f}{nm}"}
    return any(f in flat for f in forms)
