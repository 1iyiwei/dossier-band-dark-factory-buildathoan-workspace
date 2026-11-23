"""§10 export and import."""
import json
import time

import pytest

from lib import T0, USERS, all_unknown, assert_error, new_key, parse_ts

D = "talloway-systems.test"
E = "vantorra-health.test"


def export(api):
    r = api.req("GET", "/_test/export", timeout=10.0)
    assert r.status_code == 200, r.text
    return r.json()


def do_import(api, body, raw=None):
    if raw is not None:
        return api.req("POST", "/_test/import", content=raw, timeout=10.0)
    return api.req("POST", "/_test/import", json=body, timeout=10.0)


def test_R_EXP_01_R_EXP_13_export_shape(fresh):
    api, _ = fresh
    x = export(api)
    assert x["track"] == "dossier"
    assert x["format_version"] == 1 and not isinstance(x["format_version"], bool)
    assert isinstance(x["state"], dict)


def test_R_AUTH_11_export_holds_no_plaintext_password(fresh):
    api, _ = fresh
    pw = "unusual-Plaintext-Marker-981"
    assert api.req("POST", "/auth/signup", json={"email": "pw@example.org", "password": pw,
                                                 "display_name": "Pw"}).status_code == 201
    blob = json.dumps(export(api))
    assert pw not in blob
    for u in USERS:
        assert u["password"] not in blob


@pytest.mark.corpus
def test_R_EXP_02_to_R_EXP_10_roundtrip(fresh):
    api, mock = fresh
    ta = api.token(0)
    carl = api.req("POST", "/auth/signup", json={"email": "carl@example.org", "password": "carl-pass-1",
                                                 "display_name": "Carl"}).json()
    k_ok = new_key()
    created = api.create(ta, D, key=k_ok)
    assert created.status_code == 202
    before = api.wait(ta, D)
    k_fail = new_key()
    assert_error(api.create(ta, "bad domain", key=k_fail), 422, "validation_failed")
    k_ref = new_key()
    ref = api.refresh(ta, D, key=k_ref)
    assert ref.status_code == 202
    before = api.wait(ta, D)

    x = export(api)
    assert export(api) == x  # read-only snapshot (R-EXP-12)

    # diverge after export
    dora = api.req("POST", "/auth/signup", json={"email": "dora@example.org", "password": "dora-pass-1",
                                                 "display_name": "Dora"}).json()
    api.build(ta, E)
    api.clock("2026-05-01T00:00:00+00:00")
    mock.reset(0)

    r = do_import(api, x)
    assert r.status_code == 204, r.text
    time.sleep(0.5)
    assert mock.log() == [], "import made a provider call"            # R-EXP-08

    # R-EXP-05: post-export data and credentials are gone
    assert_error(api.req("GET", "/dossiers", token=dora["token"]), 401, "unauthenticated")
    assert_error(api.login("dora@example.org", "dora-pass-1"), 401, "unauthenticated")
    # R-EXP-03: accounts, hashed-password login, tokens, dossiers, idempotent responses
    assert api.req("GET", "/dossiers", token=carl["token"]).status_code == 200
    assert api.req("GET", "/dossiers", token=ta).status_code == 200
    lg = api.login("carl@example.org", "carl-pass-1")
    assert lg.status_code == 200 and lg.json()["user_id"] == carl["user_id"]
    assert api.token(1)
    assert [d["domain"] for d in api.list(ta).json()["dossiers"]] == [D]
    assert api.get(ta, D).json() == before
    rep = api.create(ta, D, key=k_ok)
    assert rep.status_code == 200 and rep.json() == created.json()
    rep = api.refresh(ta, D, key=k_ref)
    assert rep.status_code == 200 and rep.json() == ref.json()
    assert_error(api.create(ta, E, key=k_ok), 409, "idempotency_key_reuse")
    # R-EXP-09: import did not move the clock
    # R-EXP-04: the failed key is still reusable
    r = api.create(ta, E, key=k_fail)
    assert r.status_code == 202, r.text
    e = api.wait(ta, E)
    assert parse_ts(e["researched_at"]) == parse_ts("2026-05-01T00:00:00+00:00")

    # R-EXP-06: importing again replaces (no duplicates)
    assert do_import(api, x).status_code == 204
    assert do_import(api, x).status_code == 204
    assert [d["domain"] for d in api.list(ta).json()["dossiers"]] == [D]
    assert api.get(ta, D).json() == before

    # R-EXP-10: reset clears imported state
    api.reset()
    assert_error(api.req("GET", "/dossiers", token=carl["token"]), 401, "unauthenticated")
    assert_error(api.login("carl@example.org", "carl-pass-1"), 401, "unauthenticated")


def test_R_EXP_09_export_does_not_move_clock(fresh):
    api, _ = fresh
    tok = api.token(0)
    export(api)
    b = api.build(tok, "nowhere-at-all.test")
    assert parse_ts(b["researched_at"]) == parse_ts(T0)


@pytest.mark.parametrize("mutate", [
    lambda x: {},
    lambda x: {k: v for k, v in x.items() if k != "track"},
    lambda x: {k: v for k, v in x.items() if k != "format_version"},
    lambda x: {k: v for k, v in x.items() if k != "state"},
    lambda x: {**x, "track": "other"},
    lambda x: {**x, "format_version": 2},
    lambda x: {**x, "state": "garbage"},
    lambda x: {**x, "state": {"unexpected": True}},
    lambda x: {**x, "state": None},
], ids=["empty", "no-track", "no-version", "no-state", "wrong-track", "wrong-version",
        "state-string", "state-garbage-object", "state-null"])
def test_R_EXP_07_invalid_import_rejected_without_change(fresh, mutate):
    api, _ = fresh
    tok = api.token(0)
    x = export(api)
    a = api.build(tok, "nowhere-at-all.test")
    assert_error(do_import(api, mutate(x)), 422, "validation_failed")
    assert api.get(tok, "nowhere-at-all.test").json() == a
    assert [d["domain"] for d in api.list(tok).json()["dossiers"]] == ["nowhere-at-all.test"]


def test_R_EXP_07_import_unparseable_400(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert_error(do_import(api, None, raw=b"{nope"), 400, "malformed_request")
    assert api.req("GET", "/dossiers", token=tok).status_code == 200


@pytest.mark.corpus
def test_R_EXP_11_export_during_first_build(fresh):
    api, mock = fresh
    mock.fault("nimble", ["search", "extract", "research"], "delay", seconds=2)
    mock.fault("tavily", ["search", "extract"], "delay", seconds=2)
    tok = api.token(0)
    assert api.create(tok, D).status_code == 202
    x = export(api)
    done = api.wait(tok, D, timeout=60)
    assert done["state"] == "ready"
    assert do_import(api, x).status_code == 204
    b = api.get(tok, D).json()
    assert b["state"] == "failed"
    assert all_unknown(b) and b["researched_at"] is None
    assert b["dossier_id"] == done["dossier_id"]
    # the imported dossier can be researched again
    mock.reset(0)
    assert api.refresh(tok, D).status_code == 202
    assert api.wait(tok, D)["state"] == "ready"


@pytest.mark.corpus
def test_R_EXP_11_export_during_refresh_keeps_last_completed(fresh):
    api, mock = fresh
    tok = api.token(0)
    a = api.build(tok, D)
    mock.fault("nimble", ["search", "extract", "research"], "delay", seconds=2)
    mock.fault("tavily", ["search", "extract"], "delay", seconds=2)
    api.clock("2026-03-04T00:00:00+00:00")
    assert api.refresh(tok, D).status_code == 202
    x = export(api)
    api.wait(tok, D, timeout=60)
    assert do_import(api, x).status_code == 204
    b = api.get(tok, D).json()
    assert b["state"] == "ready"
    assert b["fields"] == a["fields"] and b["researched_at"] == a["researched_at"]
