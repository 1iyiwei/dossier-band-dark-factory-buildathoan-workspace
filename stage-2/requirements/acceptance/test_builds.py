"""§8 builds and dossier lifecycle, §9 cost, provider faults."""
import time

import pytest

import oracle
from lib import (T0, all_unknown, assert_dossier_shape, citation_problems, domain_queries,
                 new_key, parse_ts, total_cost)
from test_support_corpus import check_expected

T = "talloway-systems.test"
ALL_NIMBLE = ["search", "extract", "research"]
ALL_TAVILY = ["search", "extract"]


def slow_providers(mock, seconds=2):
    mock.fault("nimble", ALL_NIMBLE, "delay", seconds=seconds)
    mock.fault("tavily", ALL_TAVILY, "delay", seconds=seconds)


def break_providers(mock):
    mock.fault("nimble", ALL_NIMBLE, "error")
    mock.fault("tavily", ALL_TAVILY, "error")


def heal_providers(mock):
    mock.fault("nimble", ALL_NIMBLE, "none")
    mock.fault("tavily", ALL_TAVILY, "none")


def test_R_POST_01_create_returns_202(fresh):
    api, _ = fresh
    tok = api.token(0)
    r = api.create(tok, T)
    assert r.status_code == 202
    b = r.json()
    assert set(b) >= {"dossier_id", "domain", "state"}
    assert isinstance(b["dossier_id"], str) and 1 <= len(b["dossier_id"]) <= 64
    assert b["domain"] == T and b["state"] == "building"
    g = api.wait(tok, T)
    assert g["dossier_id"] == b["dossier_id"]


def test_R_POST_02_existing_dossier_returns_200_without_build(fresh):
    api, mock = fresh
    tok = api.token(0)
    a = api.build(tok, T)
    mock.reset(0)
    r = api.create(tok, T)
    assert r.status_code == 200
    assert r.json() == {"dossier_id": a["dossier_id"], "domain": T, "state": "ready"}
    time.sleep(0.5)
    assert mock.log() == []
    assert api.get(tok, T).json() == a


@pytest.mark.corpus
def test_R_BLD_04_build_finishes_within_10s(fresh):
    api, _ = fresh
    tok = api.token(0)
    t0 = time.monotonic()
    assert api.create(tok, T).status_code == 202
    b = api.wait(tok, T, timeout=10.5, interval=0.1)
    assert time.monotonic() - t0 <= 10.5
    assert b["state"] == "ready"


def test_R_GET_02_before_first_build_completes(fresh):
    api, mock = fresh
    slow_providers(mock, 2)
    tok = api.token(0)
    assert api.create(tok, T).status_code == 202
    b = api.get(tok, T).json()
    assert_dossier_shape(b, T)
    assert b["state"] == "building"
    assert all_unknown(b)
    assert b["researched_at"] is None
    b = api.wait(tok, T, timeout=60)
    assert b["state"] == "ready"


@pytest.mark.corpus
def test_R_GET_03_R_GET_04_later_build_shows_last_ready_fields(fresh):
    api, mock = fresh
    tok = api.token(0)
    a = api.build(tok, T)
    assert a["state"] == "ready"
    slow_providers(mock, 2)
    api.clock("2026-03-03T00:00:00+00:00")
    assert api.refresh(tok, T).status_code == 202
    b = api.get(tok, T).json()
    assert b["state"] == "building"
    assert b["fields"] == a["fields"]
    assert b["researched_at"] == a["researched_at"]
    c = api.wait(tok, T, timeout=60)
    assert c["state"] == "ready"
    assert parse_ts(c["researched_at"]) == parse_ts("2026-03-03T00:00:00+00:00")


@pytest.mark.corpus
def test_R_REF_01_R_GET_05_R_COST_01_refresh_spends_again(fresh):
    api, mock = fresh
    tok = api.token(0)
    a = api.build(tok, T)
    first_cost = total_cost(mock.log())
    assert a["spent_units"] == first_cost and 0 < first_cost <= 80
    mock.reset(0)
    r = api.refresh(tok, T)
    assert r.status_code == 202
    assert r.json() == {"dossier_id": a["dossier_id"], "domain": T, "state": "building"}
    b = api.wait(tok, T)
    log = mock.log()
    assert log, "refresh made no provider call"
    second = total_cost(log)
    assert 0 < second <= 80
    assert b["spent_units"] == first_cost + second
    assert len(domain_queries(log, T)) == 1
    assert not citation_problems(b, T, log)


def test_R_REF_02_R_BLD_01_refresh_while_building(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, T)
    mock.reset(0)
    slow_providers(mock, 2)
    a = api.refresh(tok, T)
    assert a.status_code == 202
    b = api.refresh(tok, T)
    assert b.status_code == 202 and b.json() == a.json()
    c = api.create(tok, T)  # POST on a building dossier: 200, state building, no build
    assert c.status_code == 200 and c.json()["state"] == "building"
    api.wait(tok, T, timeout=60)
    time.sleep(0.5)
    assert len(domain_queries(mock.log(), T)) == 1


@pytest.mark.corpus
def test_R_REF_04_refresh_researches_the_current_web(fresh):
    api, mock = fresh
    tok = api.token(0)
    d = "pivotal-reed.test"
    a = api.build(tok, d)
    assert not check_expected(a, d, 0)
    k = new_key()
    mock.epoch(1)
    api.clock("2026-04-01T00:00:00+00:00")
    r = api.refresh(tok, d, key=k)
    assert r.status_code == 202
    b = api.wait(tok, d)
    assert b["state"] == "ready"
    errs = check_expected(b, d, 1) + citation_problems(b, d, mock.log())
    assert not errs, errs
    assert parse_ts(b["researched_at"]) == parse_ts("2026-04-01T00:00:00+00:00")
    assert b["dossier_id"] == a["dossier_id"]


@pytest.mark.corpus
def test_R_BLD_02_R_COST_05_failed_build(fresh):
    api, mock = fresh
    break_providers(mock)
    tok = api.token(0)
    assert api.create(tok, T).status_code == 202
    b = api.wait(tok, T, timeout=60)
    assert b["state"] == "failed"
    assert all_unknown(b) and b["researched_at"] is None
    assert b["spent_units"] == 0
    item = api.list(tok).json()["dossiers"][0]
    assert item["state"] == "failed" and item["legal_name"] is None
    # recover
    heal_providers(mock)
    api.refresh(tok, T)
    c = api.wait(tok, T)
    assert c["state"] == "ready" and not check_expected(c, T, 0)
    # fail again: fields and researched_at are kept, state is failed
    break_providers(mock)
    api.clock("2026-03-09T00:00:00+00:00")
    api.refresh(tok, T)
    d = api.wait(tok, T, timeout=60)
    assert d["state"] == "failed"
    assert d["fields"] == c["fields"]
    assert d["researched_at"] == c["researched_at"]
    assert d["spent_units"] == c["spent_units"]


@pytest.mark.corpus
@pytest.mark.parametrize("label,faults", [
    ("tavily-down", [("tavily", ALL_TAVILY, "error")]),
    ("tavily-rate-limited", [("tavily", ALL_TAVILY, "rate_limit")]),
    ("extract-down", [("nimble", ["extract"], "error"), ("tavily", ["extract"], "error")]),
    ("nimble-search-throttled", [("nimble", ["search"], "throttle")]),
    ("research-throttled", [("nimble", ["research"], "throttle")]),
])
def test_R_DEL_03_R_ERR_05_degraded_providers_still_research(fresh, label, faults):
    """Nimble alone must suffice; refused calls do not count toward the domain-query rule."""
    api, mock = fresh
    for p, m, mode in faults:
        mock.fault(p, m, mode)
    tok = api.token(0)
    b = api.build(tok, T, timeout=60)
    assert b["state"] == "ready", b
    log = mock.log()
    errs = check_expected(b, T, 0) + citation_problems(b, T, log)
    if b["spent_units"] != total_cost(log):
        errs.append(f"spent_units {b['spent_units']} != {total_cost(log)}")
    if total_cost(log) > 80:
        errs.append(f"spent {total_cost(log)} > 80")
    if len(domain_queries(log, T)) != 1:
        errs.append(f"domain queries: {len(domain_queries(log, T))}")
    assert not errs, errs


F4_DOMAINS = ["talloway-systems.test", "sablewood-logistics.test", "vantorra-health.test",
              "meridel-foods.test", "wrenfield-audio.test", "ledgerline-partners.test",
              "quorra-dynamics.test", "fenwick-orchards.test"]


@pytest.mark.corpus
@pytest.mark.parametrize("domain", F4_DOMAINS)
def test_R_EVD_11_extract_and_research_refused(fresh, domain):
    """Reviewer finding F4 / RUL-34: only Nimble search answers. Every field the evidence (full
    page texts) supports must still be known, within 80 units, with valid citations.
    (orrin-bay is excluded: its research-only claims are not evidence when research is refused.)"""
    api, mock = fresh
    mock.fault("nimble", ["extract", "research"], "error")
    mock.fault("tavily", ["extract", "search"], "error")
    tok = api.token(0)
    b = api.build(tok, domain, timeout=60)
    assert b["state"] == "ready", b
    log = mock.log()
    errs = check_expected(b, domain, 0) + citation_problems(b, domain, log)
    if b["spent_units"] != total_cost(log):
        errs.append(f"spent_units {b['spent_units']} != {total_cost(log)}")
    if total_cost(log) > 80:
        errs.append(f"spent {total_cost(log)} > 80")
    if len(domain_queries(log, domain)) != 1:
        errs.append(f"domain queries: {len(domain_queries(log, domain))}")
    assert not errs, errs


@pytest.mark.corpus
def test_R_COST_06_slow_provider_costs_are_counted(fresh):
    api, mock = fresh
    mock.fault("nimble", ["search"], "delay", seconds=3)
    tok = api.token(0)
    b = api.build(tok, "vantorra-health.test", timeout=60)
    time.sleep(4)  # any abandoned call is still logged by the mock
    log = mock.log()
    assert b["state"] in ("ready", "failed")
    assert b["spent_units"] == total_cost(log) <= 80


@pytest.mark.corpus
@pytest.mark.slow
def test_R_ERR_05_weather_no_5xx_and_rules_hold(fresh):
    api, mock = fresh
    mock.weather(True)
    tok = api.token(0)
    domains = ["talloway-systems.test", "vantorra-health.test", "wrenfield-audio.test"]
    for d in domains:
        assert api.create(tok, d).status_code == 202
    for d in domains:
        b = api.wait(tok, d, timeout=120)
        assert b["state"] in ("ready", "failed"), b
        assert_dossier_shape(b, d)
        assert not citation_problems(b, d, mock.log()), d
    log = mock.log()
    assert sum(api.get(tok, d).json()["spent_units"] for d in domains) == total_cost(log)
    for d in domains:
        n = len(domain_queries(log, d))
        state = api.get(tok, d).json()["state"]
        if state == "failed":
            assert n == 0, (d, n)
        else:
            # RUL-28: exactly one, or zero when every domain-query attempt was refused
            refused = [e for e in log if e.get("method") == "search" and e.get("query") == d
                       and isinstance(e.get("status"), int) and e["status"] >= 400]
            assert n == 1 or (n == 0 and refused), (d, n, len(refused))


def test_R_BLD_06_non_build_requests_make_no_provider_calls(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, T)
    mock.reset(0)
    api.get(tok, T)
    api.list(tok)
    api.list(tok, q="tall")
    api.req("GET", "/health")
    api.req("POST", "/auth/signup", json={"email": "z@example.org", "password": "abcdefgh",
                                          "display_name": "Z"})
    api.login("z@example.org", "abcdefgh")
    api.req("GET", "/_test/export", timeout=10.0)
    api.clock("2026-03-05T00:00:00+00:00")
    time.sleep(0.5)
    assert mock.log() == []


@pytest.mark.corpus
def test_R_GEN_02_every_build_in_a_sequence_within_budget(fresh):
    """Five consecutive builds of the richest company: each at most 80 units."""
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, T)
    costs = [total_cost(mock.log())]
    for i in range(4):
        mock.reset(0)
        api.refresh(tok, T)
        api.wait(tok, T)
        costs.append(total_cost(mock.log()))
    assert max(costs) <= 80, costs
    assert api.get(tok, T).json()["spent_units"] == sum(costs)


def test_R_SUP_12_unknown_company_ready_all_unknown(fresh):
    api, _ = fresh
    tok = api.token(0)
    b = api.build(tok, "nowhere-at-all.test")
    assert b["state"] == "ready"
    assert all_unknown(b)
    assert parse_ts(b["researched_at"]) == parse_ts(T0)


def test_R_FLD_shapes_all_six_fields(fresh):
    api, _ = fresh
    tok = api.token(0)
    b = api.build(tok, T)
    assert_dossier_shape(b, T)
    assert list(sorted(b["fields"])) == sorted(oracle.FIELDS)
