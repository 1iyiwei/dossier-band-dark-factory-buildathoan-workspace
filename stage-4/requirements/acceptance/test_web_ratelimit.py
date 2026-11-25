"""Stage 2 (API): web access (render, optional browser vendors), cost, rate limits (429)."""
import time

import httpx
import pytest

from lib import (MOCK_URL, assert_dossier_shape, candidate_problems, candidate_structure_problems,
                 citation_problems, domain_queries, total_cost)

pytestmark = pytest.mark.corpus

H = "harlow-instruments.test"
V = "vesper-lanterns.test"
FM = ["search", "extract", "research"]


def rate_limited(log):
    return [e for e in log if e.get("status") == 429]


def check_build(b, domain, log, epoch=0):
    errs = []
    if b["state"] != "ready":
        return [f"state {b['state']}"]
    errs += candidate_problems(b, domain, log, epoch) + citation_problems(b, domain, log)
    cost = total_cost(log)
    if b["spent_units"] != cost:
        errs.append(f"spent_units {b['spent_units']} != mock cost {cost}")
    if cost > 80:
        errs.append(f"build spent {cost} > 80")
    if len(domain_queries(log, domain)) != 1:
        errs.append(f"successful domain queries: {len(domain_queries(log, domain))}")
    return errs


# ------------------------------------------------------------------ 429
@pytest.mark.parametrize("domain", [H, V])
def test_R_RL_01_every_distinct_call_refused_once_build_still_complete(fresh, domain):
    """`throttle`: the first attempt of each distinct call is answered 429 (cost 0). The build
    retries and ends with the same complete evidence, within 80 units."""
    api, mock = fresh
    for p in ("nimble", "tavily"):
        mock.fault(p, FM, "throttle")
    tok = api.token(0)
    t0 = time.monotonic()
    b = api.build(tok, domain, timeout=90)
    elapsed = time.monotonic() - t0
    log = mock.log()
    assert not check_build(b, domain, log)
    n429 = rate_limited(log)
    assert n429, "the throttle never refused a call"
    assert all(e["cost"] == 0 for e in n429)                   # R-RL-03: a 429 costs nothing
    # R-RL-05: waiting to retry after a 429 does not count towards the 10 s; allow 3 s per refusal
    assert elapsed <= 10 + 3.0 * len(n429) + 3, (elapsed, len(n429))


def test_R_RL_02_persistent_429_three_times_then_answered(fresh):
    """`rate_limit` on Nimble extract: 429, 429, 429, then one normal answer, and so on; a
    build must keep retrying (at least 3 refusals in a row) rather than give up on the page."""
    api, mock = fresh
    mock.fault("nimble", ["extract"], "rate_limit")
    tok = api.token(0)
    b = api.build(tok, V, timeout=120)
    log = mock.log()
    assert b["state"] == "ready", b
    assert not candidate_structure_problems(b)
    assert b["spent_units"] == total_cost(log) <= 80
    assert all(e["cost"] == 0 for e in rate_limited(log))
    # Nimble extract is refused 3 times in a row for every distinct call; the service still gets
    # its browser text, from Nimble after the retries or from another source. The values show it:
    assert b["fields"]["hq_city"]["value"] == "Murano", b["fields"]["hq_city"]


def test_R_RL_04_weather_everything_holds_per_build(fresh):
    api, mock = fresh
    mock.weather(True)
    tok = api.token(0)
    for d in (H, V):
        assert api.create(tok, d).status_code == 202
    for d in (H, V):
        b = api.wait(tok, d, timeout=120)
        assert b["state"] in ("ready", "failed"), b
        assert_dossier_shape(b, d)
        assert not candidate_structure_problems(b), d
        assert not citation_problems(b, d, mock.log()), d
    log = mock.log()
    assert sum(api.get(tok, d).json()["spent_units"] for d in (H, V)) == total_cost(log)
    assert all(e["cost"] == 0 for e in rate_limited(log))


# ------------------------------------------------------------------ web access
@pytest.mark.parametrize("mode", ["error", "rate_limit"])
def test_R_WEB_03_browser_vendors_are_optional(fresh, mode):
    """Nimble's rendered extract alone is enough: with every Kernel and Browserbase session open
    answered 500 (or 429, as when 4 sessions are open) the build is the same."""
    api, mock = fresh
    mock.fault("kernel", ["session"], mode)
    mock.fault("browserbase", ["session", "browse"], mode)
    b = api.build(api.token(0), V, timeout=60)
    assert not check_build(b, V, mock.log())


def test_R_WEB_03_nimble_alone_gets_browser_text(fresh):
    api, mock = fresh
    for m in FM:
        mock.fault("tavily", [m], "error")
    mock.fault("kernel", ["session"], "error")
    mock.fault("browserbase", ["session", "browse"], "error")
    b = api.build(api.token(0), V, timeout=60)
    assert not check_build(b, V, mock.log())


def test_R_WEB_04_sessions_are_released(fresh):
    """Each provider keeps at most 4 sessions open. A service that opened sessions must have
    released them: after the build, four fresh sessions can be opened at each vendor. (Vacuous
    when the build opened none.)"""
    api, mock = fresh
    b = api.build(api.token(0), V, timeout=60)
    log = mock.log()
    used = {e["provider"] for e in log if e.get("method") == "session"}
    if not used:
        return
    mock.reset(0)
    opened = []
    c = httpx.Client(base_url=MOCK_URL, timeout=20)
    try:
        for prov, path, body in (("kernel", "/kernel/browsers", {}),
                                 ("browserbase", "/browserbase/v1/sessions", {})):
            if prov not in used:
                continue
            for i in range(4):
                r = c.post(path, json=body, headers={"Authorization": "Bearer x",
                                                     "X-BB-API-Key": "x"})
                if r.status_code == 429:
                    pytest.fail(f"{prov}: session {i + 1} of 4 refused with 429: "
                                "the service left sessions open")
                if r.status_code not in (200, 201):
                    pytest.skip(f"cannot open probe sessions at {prov}: {r.status_code} {r.text[:100]}")
                opened.append((prov, r.json()))
    finally:
        for prov, doc in opened:
            sid = doc.get("session_id") or doc.get("id")
            try:
                if prov == "kernel":
                    c.delete(f"/kernel/browsers/{sid}")
                else:
                    c.post(f"/browserbase/v1/sessions/{sid}", json={"status": "REQUEST_RELEASE"})
            except Exception:  # noqa: BLE001
                pass
        mock.reset(0)
    assert b["state"] == "ready"
