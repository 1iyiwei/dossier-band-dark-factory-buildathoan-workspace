"""Stage 3: state survives an abrupt stop (SIGKILL, no warning) of the service container and a start.
Needs SVC_CONTAINER (the docker name of the service under test; `up.sh` exports it). When no build
is running at the stop, the service answers afterwards exactly as before: accounts, tokens, dossiers
(plain, as_of, values, history), the list, the feed with the same seq, replays of idempotent
requests, and the clock."""
import os

import pytest

import oracle
import s3lib
import timeline as tl
from lib import FIXTURE, T0, USERS, Api, assert_error, new_key, parse_ts

pytestmark = [pytest.mark.corpus,
              pytest.mark.skipif(not os.environ.get("SVC_CONTAINER"),
                                 reason="SVC_CONTAINER (docker name of the service) not set")]
NG = "northgate-labs.test"
CB = "cobalt-assembly.test"
PR = "pivotal-reed.test"


def probe(api, tok, doms):
    out = {"list": api.list(tok).json(), "feed": s3lib.all_changes(api, tok)}
    for d in doms:
        out[d] = dict(cur=api.get(tok, d).json(), hist=s3lib.history(api, tok, d).json(),
                      asof=[s3lib.as_of(api, tok, d, ts).json() for ts in (
                          T0, "2026-03-15T00:00:00+00:00", "2027-01-01T00:00:00+00:00")],
                      vals=[s3lib.values(api, tok, d, ta, ao).json() for ta, ao in (
                          ("2025-06-01", "2026-03-15T00:00:00+00:00"), ("2026-03-15", None))])
    return out


def seed(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    s3lib.run(api, mock, tok, NG, [{"epoch": 0, "clock": T0}, {"epoch": 1, "clock": "2026-03-10T09:00:00+00:00"},
                                   {"epoch": 2, "clock": "2026-03-20T09:00:00+00:00"}])
    s3lib.run(api, mock, tok, CB, [{"epoch": 0, "clock": "2026-03-21T09:00:00+00:00"},
                                   {"epoch": 3, "clock": "2026-03-22T09:00:00+00:00"}])
    return tok


def test_R3_RST_01_everything_answers_as_before(api, mock):
    tok = seed(api, mock)
    su = api.req("POST", "/auth/signup", json={"email": "new@example.org", "password": "abcdefgh1",
                                               "display_name": "New"})
    assert su.status_code == 201
    new_tok = su.json()["token"]
    key = new_key("rst")
    first = api.create(tok, "nowhere-at-all.test", key=key)
    assert first.status_code == 202
    api.wait(tok, "nowhere-at-all.test")
    rk = new_key("rf")
    rr = api.refresh(tok, NG, key=rk)
    api.wait(tok, NG)
    doms = [NG, CB, "nowhere-at-all.test"]
    before = probe(api, tok, doms)
    api.clock("2026-05-01T09:00:00+00:00")
    elapsed = s3lib.kill_and_restart()
    assert elapsed < 60
    after = probe(api, tok, doms)
    assert after == before
    assert api.get(new_tok, NG).status_code == 200                       # token from before the stop
    assert api.login("new@example.org", "abcdefgh1").status_code == 200   # account created before
    for u in USERS:
        assert api.login(u["email"], u["password"]).status_code == 200
    r = api.create(tok, "nowhere-at-all.test", key=key)                  # replays
    assert r.status_code == 200 and r.json() == first.json()
    r = api.refresh(tok, NG, key=rk)
    assert r.status_code == 200 and r.json() == rr.json()
    assert_error(api.create(tok, "other-co.test", key=key), 409, "idempotency_key_reuse")
    n = len(mock.log())
    assert len(mock.log()) == n
    # the clock reads what it read before the stop
    mock.epoch(0)
    assert api.refresh(tok, CB).status_code == 202
    b = api.wait(tok, CB)
    assert parse_ts(b["researched_at"]) == parse_ts("2026-05-01T09:00:00+00:00")


def test_R3_RST_02_new_entries_after_restart_have_larger_seq(api, mock):
    tok = seed(api, mock)
    feed = s3lib.all_changes(api, tok)
    assert feed
    s3lib.kill_and_restart()
    mock.epoch(3)
    api.clock("2026-04-01T09:00:00+00:00")
    assert api.refresh(tok, NG).status_code == 202
    api.wait(tok, NG)
    after = s3lib.all_changes(api, tok)
    assert after[:len(feed)] == feed and len(after) > len(feed)
    assert min(e["seq"] for e in after[len(feed):]) > max(e["seq"] for e in feed)
    seqs = [e["seq"] for e in after]
    assert seqs == sorted(set(seqs))


def test_R3_RST_03_repeated_kills_leave_no_duplicates_or_gaps(api, mock):
    tok = seed(api, mock)
    domain = PR
    api.clock("2026-03-25T09:00:00+00:00")
    expected = s3lib.all_changes(api, tok)
    for i in range(3):
        mock.epoch(i % 2)
        assert (api.create(tok, domain) if i == 0 else api.refresh(tok, domain)).status_code in (200, 202)
        b = api.wait(tok, domain)
        assert b["state"] == "ready"
        snap = probe(api, tok, [domain])
        s3lib.kill_and_restart()                       # immediately after the build is reported ready
        assert probe(api, tok, [domain]) == snap, f"state differs after kill {i}"
    feed = s3lib.all_changes(api, tok)
    seqs = [e["seq"] for e in feed]
    assert seqs == sorted(set(seqs))
    assert feed[:len(expected)] == expected
    # builds 1 and 2 changed ceo and founded_year each
    mine = [e for e in feed if e["domain"] == domain]
    assert [(e["field"], e["from"], e["to"]) for e in mine] == [
        ("ceo", "Hana Sato", "Leon Brandt"), ("founded_year", 2001, None),
        ("ceo", "Leon Brandt", "Hana Sato"), ("founded_year", None, 2001)][:len(mine)]
    assert len(mine) == 4


def test_R3_RST_04_signup_and_replay_are_durable_when_the_response_arrives(api, mock):
    api.reset()
    mock.reset(0)
    ok = []
    for i in range(3):
        r = api.req("POST", "/auth/signup", json={"email": f"d{i}@example.org", "password": "abcdefgh1",
                                                  "display_name": f"D{i}"})
        assert r.status_code == 201
        ok.append((f"d{i}@example.org", r.json()["token"], r.json()["user_id"]))
        s3lib.kill_and_restart()
        for email, token, uid in ok:
            assert api.login(email, "abcdefgh1").json()["user_id"] == uid
            assert api.req("GET", "/dossiers", token=token).status_code == 200


def test_R3_RST_05_dossier_ready_is_durable_the_moment_it_is_visible(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    for i, d in enumerate(("talloway-systems.test", "quorra-dynamics.test", "meridel-foods.test")):
        assert api.create(tok, d).status_code == 202
        snap = api.wait(tok, d)
        lst = api.list(tok).json()
        s3lib.kill_and_restart()
        assert api.get(tok, d).json() == snap
        assert api.list(tok).json() == lst
        assert s3lib.history(api, tok, d).json()["fields"]["ceo"] is not None


def test_R3_RST_06_reset_import_and_export_work_after_a_restart(api, mock):
    tok = seed(api, mock)
    s3lib.kill_and_restart()
    export = api.req("GET", "/_test/export", timeout=10.0).json()
    api.reset()
    assert api.list(api.token(0)).json()["dossiers"] == []
    assert api.req("POST", "/_test/import", json=export, timeout=10.0).status_code == 204
    assert {d["domain"] for d in api.list(tok).json()["dossiers"]} == {NG, CB}
    s3lib.kill_and_restart()
    assert {d["domain"] for d in api.list(tok).json()["dossiers"]} == {NG, CB}   # imported state is durable too
    api.reset()
    s3lib.kill_and_restart()
    assert api.list(api.token(0)).json()["dossiers"] == []                     # so is a reset


def test_R3_RST_07_a_stop_during_a_build_leaves_a_usable_service(api, mock):
    """Spec: only the case 'no build running at the stop' is specified. Ruling RUL-S3-18: after a
    stop in mid-build the service must not stay `building` forever, must keep the last ready
    fields, and a new refresh must build normally."""
    tok = seed(api, mock)
    before = api.get(tok, NG).json()
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "delay", seconds=4)
    mock.epoch(4)
    api.clock("2026-04-10T09:00:00+00:00")
    assert api.refresh(tok, NG).status_code == 202
    import time
    time.sleep(1.0)
    s3lib.kill_and_restart()
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "none")
    deadline = time.monotonic() + 60
    while True:
        b = api.get(tok, NG).json()
        if b["state"] != "building" or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    assert b["state"] != "building", "dossier stuck in `building` after the restart"
    feed = s3lib.all_changes(api, tok)
    ceo = [e for e in feed if e["domain"] == NG and e["field"] == "ceo"]
    assert len(ceo) in (2, 3)                               # the interrupted build added all or nothing
    if b["fields"]["ceo"]["value"] == before["fields"]["ceo"]["value"]:
        assert len(ceo) == 2
    mock.epoch(4)
    r = api.refresh(tok, NG)
    assert r.status_code == 202
    done = api.wait(tok, NG, timeout=60)
    assert done["state"] == "ready" and done["fields"]["ceo"]["value"] == "Paul Quist"
    ceo = [e for e in s3lib.all_changes(api, tok) if e["domain"] == NG and e["field"] == "ceo"]
    assert [e["to"] for e in ceo] == ["Lee Park", "Maya Ito", "Paul Quist"]
