"""Stage 2 (API): an export produced by the stage-1 service is accepted and upgraded.

Needs a running stage-1 service of the same team (OLD_BASE_URL, sharing the mock web with the
service under test); skipped otherwise. `up.sh --old-image <tag>` starts one.

Ruling RUL-S2-12: the stage-1 export format records no page texts, kinds or publication times,
so the candidates of an imported field are at least one per citation (kind and published_at
null, retrieved_at = researched_at); they may add values that the served texts of the stage-1
build support (checked against the mock's log of that build), and never anything else.
"""
import os

import pytest

import oracle
import rank
from lib import (FIXTURE, USERS, Api, assert_dossier_shape, assert_error, candidate_problems,
                 candidate_structure_problems, new_key, parse_ts)

OLD_BASE_URL = os.environ.get("OLD_BASE_URL", "").rstrip("/")
pytestmark = [pytest.mark.corpus,
              pytest.mark.skipif(not OLD_BASE_URL, reason="OLD_BASE_URL (stage-1 service) not set")]

DOMAINS = ["ledgerline-partners.test", "talloway-systems.test", "orrin-bay.test",
           "nowhere-at-all.test"]


@pytest.fixture()
def old():
    return Api(OLD_BASE_URL)


def served_support(log, domain):
    """{(url, field, repr(value)): {provider: [served text]}} for everything the providers served."""
    out = {}
    for e in log:
        if not (isinstance(e.get("status"), int) and e["status"] < 400):
            continue
        for it in e.get("served") or []:
            if not isinstance(it, dict) or not it.get("url"):
                continue
            prose = oracle.prose_of(it.get("text") or "")
            for s in oracle.sentences(prose):
                for f in oracle.FIELDS:
                    v = oracle.supported_value(s, f, domain)
                    if v is not None:
                        out.setdefault((it["url"], f, repr(v)), {}).setdefault(
                            e["provider"], []).append(it["text"])
    return out


@pytest.fixture()
def upgrade(api, mock, old):
    """Build on the stage-1 service, export, import into the service under test."""
    mock.reset(0)
    old.reset()
    tok = old.token(0)
    keys, first = {}, {}
    for d in DOMAINS:
        keys[d] = new_key("cr")
        r = old.create(tok, d, key=keys[d])
        assert r.status_code == 202, r.text
        first[d] = r.json()
        assert old.wait(tok, d, timeout=60)["state"] == "ready"
    rk = new_key("rf")
    r = old.refresh(tok, "talloway-systems.test", key=rk)
    assert r.status_code == 202
    refresh_body = r.json()
    old.wait(tok, "talloway-systems.test", timeout=60)
    before = {d: old.get(tok, d).json() for d in DOMAINS}
    before_list = old.list(tok).json()
    export = old.req("GET", "/_test/export", timeout=10.0).json()
    log = mock.log()
    mock.reset(0)
    api.reset({"now": "2026-03-01T09:00:00+00:00", "users": [
        {"id": "u_other", "email": "other@example.org", "password": "xxxxxxxx-1",
         "display_name": "Other"}]})
    r = api.req("POST", "/_test/import", json=export, timeout=10.0)
    assert r.status_code == 204, (r.status_code, r.text)
    assert mock.log() == [], "import made a provider call"
    return dict(tok=tok, keys=keys, first=first, rk=rk, refresh_body=refresh_body, before=before,
                before_list=before_list, log=log)


def test_R_UPG_01_dossiers_survive_with_ids_and_candidates(api, mock, upgrade):
    u = upgrade
    for d in DOMAINS:
        old = u["before"][d]
        new = api.get(u["tok"], d).json()                      # the stage-1 token still works
        assert_dossier_shape(new, d)
        for k in ("dossier_id", "domain", "state", "researched_at", "spent_units"):
            assert new[k] == old[k], (d, k, new[k], old[k])
        assert not candidate_structure_problems(new), d
        served = served_support(u["log"], d)
        for f in oracle.FIELDS:
            of, nf = old["fields"][f], new["fields"][f]
            assert nf["value"] == of["value"] and type(nf["value"]) is type(of["value"]), (d, f)
            if of["value"] is None:
                assert nf["status"] == "unknown" and nf["candidates"] == [] and nf["citations"] == []
                continue
            assert nf["status"] in ("known", "contested")
            cand_pairs = {(c["url"], repr(c["value"])) for c in nf["candidates"]}
            for c in of["citations"]:                           # lower bound: every cited page
                assert (c["url"], repr(of["value"])) in cand_pairs, (d, f, c["url"])
            for c in nf["candidates"]:
                assert c["kind"] is None and c["published_at"] is None, c
                assert parse_ts(c["retrieved_at"]) == parse_ts(old["researched_at"]), c
                key = (c["url"], f, repr(c["value"]))
                assert key in served, (d, f, "candidate no served text supports", c)   # upper bound
                assert c["provider"] in served[key], (d, f, c["provider"], list(served[key]))
                nex = oracle.collapse(c["excerpt"]).strip()
                assert any(nex in oracle.collapse(t) for t in served[key][c["provider"]]), c
                assert oracle.supports(c["excerpt"], f, c["value"], d), c
            assert [c["url"] for c in nf["citations"]] == \
                [c["url"] for c in nf["candidates"] if c["value"] == nf["value"]]


def test_R_UPG_02_list_accounts_and_tokens(api, mock, upgrade):
    u = upgrade
    assert api.list(u["tok"]).json() == u["before_list"]
    r = api.login(USERS[0]["email"], USERS[0]["password"])      # hashed password carried over
    assert r.status_code == 200 and r.json()["user_id"] == USERS[0]["id"]
    assert api.login(USERS[1]["email"], USERS[1]["password"]).status_code == 200
    assert_error(api.login("other@example.org", "xxxxxxxx-1"), 401, "unauthenticated")  # replaced
    assert_error(api.req("POST", "/auth/signup", json={
        "email": USERS[0]["email"], "password": "abcdefgh", "display_name": "x"}), 409, "email_taken")
    tok2 = api.token(1)                                         # a new token works as well
    assert api.get(tok2, DOMAINS[1]).status_code == 200


def test_R_UPG_03_retries_after_the_upgrade_recover_the_original_response(api, mock, upgrade):
    u = upgrade
    for d in DOMAINS:
        r = api.create(u["tok"], d, key=u["keys"][d])
        assert r.status_code == 200 and r.json() == u["first"][d], (d, r.status_code, r.text)
        assert_error(api.create(u["tok"], d, key=u["keys"][d], body={"domain": "other-co.test"}),
                     409, "idempotency_key_reuse")
    r = api.refresh(u["tok"], "talloway-systems.test", key=u["rk"])
    assert r.status_code == 200 and r.json() == u["refresh_body"]
    assert mock.log() == [], "a replay started a build"


def test_R_UPG_04_candidates_are_replaced_by_the_next_build(api, mock, upgrade):
    u = upgrade
    api.clock("2026-03-04T10:00:00+00:00")
    d = "ledgerline-partners.test"
    assert api.refresh(u["tok"], d).status_code == 202
    b = api.wait(u["tok"], d)
    assert b["state"] == "ready" and b["researched_at"] == "2026-03-04T10:00:00+00:00"
    assert not candidate_problems(b, d, mock.log())
    assert all(c["kind"] is not None for fv in b["fields"].values() for c in fv["candidates"])
    assert b["fields"]["ceo"]["status"] == "contested" and b["fields"]["ceo"]["value"] == "Ines Varga"
    assert b["spent_units"] > u["before"][d]["spent_units"]


def test_R_UPG_05_a_stage_2_export_round_trips_with_candidates(api, mock):
    """The service's own export (format_version 1) carries candidates through reset and import."""
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    d = "harlow-instruments.test"
    b = api.build(tok, d)
    exp = api.req("GET", "/_test/export", timeout=10.0).json()
    assert exp["track"] == "dossier" and exp["format_version"] == 1
    api.reset()
    assert api.req("POST", "/_test/import", json=exp, timeout=10.0).status_code == 204
    assert api.get(tok, d).json() == b
    assert api.req("GET", "/_test/export", timeout=10.0).json() == exp
