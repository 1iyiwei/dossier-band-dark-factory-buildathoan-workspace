"""§3 runtime contract: health, reset/seed, clock, conventions."""
import time

import pytest

from lib import (FIXTURE, T0, USERS, assert_error, new_key, parse_ts)


def test_R_RUN_02_health(api):
    r = api.req("GET", "/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_R_RUN_03_health_makes_no_provider_call(fresh):
    api, mock = fresh
    for _ in range(3):
        api.req("GET", "/health")
    assert mock.log() == []


def test_R_CNV_01_json_content_type(fresh):
    api, _ = fresh
    for r in (api.req("GET", "/health"), api.login(USERS[0]["email"], USERS[0]["password"]),
              api.req("GET", "/dossiers")):
        assert r.headers.get("content-type", "").lower().startswith("application/json"), r.headers


# ---------------------------------------------------------------- reset
def test_R_RST_06_R_RST_04_reset_unauthenticated_and_repeatable(api):
    for _ in range(3):
        r = api.req("POST", "/_test/reset", json=FIXTURE, timeout=10.0)
        assert r.status_code == 204
        assert r.content in (b"", None)


def test_R_RST_07_R_AUTH_08_seeded_users_login(fresh):
    api, _ = fresh
    for u in USERS:
        r = api.login(u["email"], u["password"])
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["user_id"] == u["id"]
        assert b["display_name"] == u["display_name"]
        assert isinstance(b["token"], str) and b["token"]


def test_R_RST_01_reset_removes_signed_up_users(fresh):
    api, _ = fresh
    r = api.req("POST", "/auth/signup", json={"email": "temp@example.org", "password": "abcdefgh1",
                                              "display_name": "Temp"})
    assert r.status_code == 201
    api.reset()
    assert_error(api.login("temp@example.org", "abcdefgh1"), 401, "unauthenticated")
    # and the email is free again
    r = api.req("POST", "/auth/signup", json={"email": "temp@example.org", "password": "abcdefgh1",
                                              "display_name": "Temp"})
    assert r.status_code == 201


def test_R_RST_10_tokens_from_before_reset_are_invalid(fresh):
    api, _ = fresh
    r = api.req("POST", "/auth/signup", json={"email": "t2@example.org", "password": "abcdefgh1",
                                              "display_name": "T2"})
    tok = r.json()["token"]
    seeded_tok = api.token(0)
    api.reset()
    assert_error(api.req("GET", "/dossiers", token=tok), 401, "unauthenticated")
    assert_error(api.req("GET", "/dossiers", token=seeded_tok), 401, "unauthenticated")


def test_R_RST_02_R_RST_03_reset_clears_dossiers_and_idempotency(fresh):
    api, _ = fresh
    tok = api.token(0)
    key = new_key()
    assert api.create(tok, "nowhere-at-all.test", key=key).status_code == 202
    api.wait(tok, "nowhere-at-all.test")
    api.reset()
    tok = api.token(0)
    b = api.list(tok).json()
    assert b["dossiers"] == [] and b["has_more"] is False
    assert_error(api.get(tok, "nowhere-at-all.test"), 404, "not_found")
    # same key, different body: must be a first use, not 409
    r = api.create(tok, "elsewhere-entirely.test", key=key)
    assert r.status_code == 202, r.text
    # the dossier was cleared, so creating it again is a new dossier -> 202
    r = api.create(tok, "nowhere-at-all.test", key=new_key())
    assert r.status_code == 202, r.text
    api.wait(tok, "nowhere-at-all.test")
    api.wait(tok, "elsewhere-entirely.test")


def test_R_RST_08_duplicate_email_fixture_rejected_and_changes_nothing(fresh):
    api, _ = fresh
    tok = api.token(0)
    api.build(tok, "nowhere-at-all.test")
    bad = {"now": "2026-04-01T00:00:00+00:00", "users": [
        {"id": "x1", "email": "dup@example.org", "password": "abcdefgh1", "display_name": "A"},
        {"id": "x2", "email": "dup@example.org", "password": "abcdefgh2", "display_name": "B"}]}
    assert_error(api.req("POST", "/_test/reset", json=bad, timeout=10.0), 422, "validation_failed")
    # nothing changed: old token valid, dossier still there, clock not moved, dup user absent
    b = api.get(tok, "nowhere-at-all.test").json()
    assert parse_ts(b["researched_at"]) == parse_ts(T0)
    assert_error(api.login("dup@example.org", "abcdefgh1"), 401, "unauthenticated")
    c = api.build(tok, "elsewhere-entirely.test")
    assert parse_ts(c["researched_at"]) == parse_ts(T0)


@pytest.mark.parametrize("body", [
    {"users": []},
    {"now": "2026-03-01T09:00:00", "users": []},
    {"now": "not a time", "users": []},
])
def test_R_RST_09_fixture_now_required_and_valid(fresh, body):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.req("POST", "/_test/reset", json=body, timeout=10.0), 422, "validation_failed")
    assert api.req("GET", "/dossiers", token=tok).status_code == 200  # state unchanged


def test_R_RST_11_reset_malformed_json_is_400(fresh):
    api, _ = fresh
    r = api.req("POST", "/_test/reset", content=b"{not json", timeout=10.0)
    assert_error(r, 400, "malformed_request")


@pytest.mark.slow
def test_R_RST_05_build_running_at_reset_does_not_leak(fresh):
    api, mock = fresh
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "delay", seconds=3)
    tok = api.token(0)
    r = api.create(tok, "talloway-systems.test")
    assert r.status_code == 202
    time.sleep(0.5)
    api.reset()
    tok = api.token(0)
    time.sleep(12)  # let the orphaned build run to completion
    b = api.list(tok).json()
    assert b["dossiers"] == [], b
    assert_error(api.get(tok, "talloway-systems.test"), 404, "not_found")
    mock.reset(0)


# ---------------------------------------------------------------- clock
def test_R_CLK_01_R_BLD_03_reset_sets_clock(fresh):
    api, _ = fresh
    tok = api.token(0)
    b = api.build(tok, "nowhere-at-all.test")
    assert b["state"] == "ready"
    assert parse_ts(b["researched_at"]) == parse_ts(T0)


def test_R_CLK_02_R_CLK_06_clock_moves_builds(fresh):
    api, _ = fresh
    tok = api.token(0)
    r = api.clock("2026-03-01T11:30:00+02:00")  # 09:30Z, unauthenticated
    assert r.status_code == 204
    b = api.build(tok, "nowhere-at-all.test")
    assert parse_ts(b["researched_at"]) == parse_ts("2026-03-01T09:30:00+00:00")
    assert api.clock("2026-03-02T00:00:00+00:00").status_code == 204
    api.refresh(tok, "nowhere-at-all.test")
    b = api.wait(tok, "nowhere-at-all.test")
    assert parse_ts(b["researched_at"]) == parse_ts("2026-03-02T00:00:00+00:00")


def test_R_CLK_03_clock_stands_still(fresh):
    api, _ = fresh
    tok = api.token(0)
    a = api.build(tok, "nowhere-at-all.test")
    time.sleep(1.2)
    b = api.build(tok, "elsewhere-entirely.test")
    assert parse_ts(a["researched_at"]) == parse_ts(b["researched_at"]) == parse_ts(T0)


def test_R_CLK_04_clock_cannot_go_back(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.clock("2026-03-01T08:59:59+00:00"), 422, "validation_failed")
    b = api.build(tok, "nowhere-at-all.test")
    assert parse_ts(b["researched_at"]) == parse_ts(T0)


def test_R_CLK_08_clock_same_time_accepted(fresh):
    api, _ = fresh
    assert api.clock(T0).status_code == 204
    assert api.clock("2026-03-01T10:00:00+01:00").status_code == 204  # same instant


@pytest.mark.parametrize("body,status,code", [
    ({}, 422, "validation_failed"),
    ({"now": "2026-03-05T09:30:00"}, 422, "validation_failed"),
    ({"now": "next tuesday"}, 422, "validation_failed"),
    ({"now": 1772357400}, 400, "malformed_request"),
])
def test_R_CLK_05_clock_validation(fresh, body, status, code):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.req("POST", "/_test/clock", json=body), status, code)
    b = api.build(tok, "nowhere-at-all.test")
    assert parse_ts(b["researched_at"]) == parse_ts(T0)


def test_R_CLK_09_clock_accepts_z_offset(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert api.clock("2026-03-01T12:00:00Z").status_code == 204
    b = api.build(tok, "nowhere-at-all.test")
    assert parse_ts(b["researched_at"]) == parse_ts("2026-03-01T12:00:00+00:00")


def test_R_AUTH_10_tokens_do_not_expire(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert api.clock("2036-03-01T09:00:00+00:00").status_code == 204
    assert api.req("GET", "/dossiers", token=tok).status_code == 200
