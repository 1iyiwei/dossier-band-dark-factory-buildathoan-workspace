"""Stage 2 (HTTP only, no browser): the browser and the API share `/dossiers/{domain}`; browser
routes answer HTML; nothing is loaded from outside the image."""
import re

import httpx
import pytest

from lib import BASE_URL, assert_error

BROWSER_ACCEPT = ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,*/*;q=0.8")
D = "talloway-systems.test"
ROUTES = ["/", "/contested", "/signup", "/login", f"/dossiers/{D}", f"/dossiers/{D}/evidence"]


def html_get(path, token=None, accept=BROWSER_ACCEPT):
    h = {"Accept": accept}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return httpx.get(BASE_URL + path, headers=h, follow_redirects=True, timeout=5.0)


@pytest.mark.corpus
def test_R_UI_01_dossier_route_serves_json_to_api_and_html_to_browser(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, D)
    for accept in (None, "application/json", "*/*"):
        h = {"Authorization": f"Bearer {tok}"}
        if accept:
            h["Accept"] = accept
        r = httpx.get(f"{BASE_URL}/dossiers/{D}", headers=h, timeout=5.0)
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/json"), \
            (accept, r.status_code, r.headers.get("content-type"))
        assert r.json()["domain"] == D
    for token in (tok, None):                    # a browser navigation sends no bearer token
        r = html_get(f"/dossiers/{D}", token)
        assert r.status_code == 200, (token, r.status_code)
        assert r.headers["content-type"].startswith("text/html"), r.headers["content-type"]
        assert "<" in r.text and len(r.text) > 200
    # the API still refuses an unauthenticated JSON request
    assert_error(httpx.get(f"{BASE_URL}/dossiers/{D}", timeout=5.0), 401, "unauthenticated")


@pytest.mark.parametrize("path", ROUTES)
def test_R_UI_02_every_route_is_html_for_a_browser(fresh, path):
    api, _ = fresh
    r = html_get(path, api.token(0))
    assert r.status_code == 200, (path, r.status_code, r.text[:200])
    assert r.headers["content-type"].startswith("text/html"), (path, r.headers["content-type"])


def test_R_UI_02_unknown_dossier_is_still_a_screen(fresh):
    api, _ = fresh
    for suffix in ("", "/evidence"):
        r = html_get(f"/dossiers/no-such-company.test{suffix}", api.token(0))
        assert r.status_code in (200, 404), r.status_code
        assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", ROUTES)
def test_R_UI_03_no_external_assets_in_the_document(fresh, path):
    """Runtime assets are in the image: no script, stylesheet, font or image from another origin."""
    api, _ = fresh
    r = html_get(path, api.token(0))
    refs = re.findall(r'\bsrc\s*=\s*["\']([^"\']+)["\']', r.text, flags=re.I)
    for tag in re.findall(r"<link\b[^>]*>", r.text, flags=re.I):      # not <a href>: citations link out
        refs += re.findall(r'\bhref\s*=\s*["\']([^"\']+)["\']', tag, flags=re.I)
    refs += re.findall(r'url\(\s*["\']?([^)"\']+)', r.text, flags=re.I)
    refs += re.findall(r'@import\s+["\']([^"\']+)', r.text, flags=re.I)
    external = [u for u in refs if re.match(r"^(https?:)?//", u) and
                not u.startswith(BASE_URL) and not re.match(r"^(https?:)?//(localhost|127\.0\.0\.1)[:/]", u)]
    assert not external, external
