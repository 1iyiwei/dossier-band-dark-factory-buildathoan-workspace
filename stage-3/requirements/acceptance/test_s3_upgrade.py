"""Stage 3 (API): upgrades. An export of the same team's stage-1 service (OLD_BASE_URL), of its
stage-2 service (OLD2_BASE_URL) and of this service itself is imported into the service under test.
Skipped when the old services are not given (`up.sh` with OLD_IMAGE / OLD2_IMAGE starts them).

Rulings: RUL-S3-14 (stage-1 import), RUL-S3-15 (the stage-2 export records no build list and no
Effective lines: one ready build at researched_at, true_from from Published), RUL-S3-16.
"""
import os
from datetime import timezone

import pytest

import oracle
import s3lib
import timeline as tl
from lib import FIXTURE, T0, USERS, Api, assert_dossier_shape, assert_error, new_key, parse_ts

OLD1 = os.environ.get("OLD_BASE_URL", "").rstrip("/")
OLD2 = os.environ.get("OLD2_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.corpus

PR = "pivotal-reed.test"
CB = "cobalt-assembly.test"
NG = "northgate-labs.test"
HL = "harlow-instruments.test"
OTHER = {"now": T0, "users": [{"id": "u_other", "email": "other@example.org",
                                "password": "xxxxxxxx-1", "display_name": "Other"}]}
NEW_KEYS = {"true_from", "learned_at"}


def build_on(old, mock, tok, domain, epoch, clock, first):
    mock.epoch(epoch)
    old.clock(clock)
    r = old.create(tok, domain) if first else old.refresh(tok, domain)
    assert r.status_code in (200, 202), r.text
    return old.wait(tok, domain, timeout=60)


def do_import(api, export):
    r = api.req("POST", "/_test/import", json=export, timeout=10.0)
    assert r.status_code == 204, (r.status_code, r.text)


def six(body):
    return {f: body["fields"][f] for f in oracle.FIELDS}


def stage2_view(c):
    return {k: c[k] for k in ("value", "url", "excerpt", "provider", "kind", "published_at",
                              "retrieved_at", "selected")}


# =========================================================== stage-1 export
@pytest.fixture()
def from1(api, mock):
    if not OLD1:
        pytest.skip("OLD_BASE_URL (final stage-1 service) not set")
    old = Api(OLD1)
    mock.reset(0)
    old.reset()
    tok = old.token(0)
    snaps, keys = {}, {}
    old.clock(T0)
    for d in (PR, CB, "talloway-systems.test"):
        mock.epoch(0)
        snaps[d] = old.build(tok, d)
    # a dossier whose only build failed: researched_at null
    s3lib.fail_providers(mock, True)
    keys["fail"] = new_key("f")
    assert old.create(tok, "ledgerline-partners.test", key=keys["fail"]).status_code == 202
    snaps["ledgerline-partners.test"] = old.wait(tok, "ledgerline-partners.test")
    s3lib.fail_providers(mock, False)
    assert snaps["ledgerline-partners.test"]["state"] == "failed"
    export = old.req("GET", "/_test/export", timeout=10.0).json()
    mock.reset(0)
    api.reset(OTHER)
    do_import(api, export)
    assert mock.log() == [], "import made a provider call"
    return dict(old=old, tok=tok, snaps=snaps, export=export, api=api, mock=mock)


def test_R3_UPG_01_stage1_import_gives_initial_history_and_null_dates(from1):
    api, tok = from1["api"], from1["tok"]
    for d in (PR, CB, "talloway-systems.test"):
        old = from1["snaps"][d]
        new = api.get(tok, d).json()
        assert_dossier_shape(new, d)
        assert new["researched_at"] == old["researched_at"]
        assert new["fields"]["executives"] == {
            "value": None, "status": "unknown", "true_from": None, "learned_at": None,
            "citations": [], "candidates": []}
        h = s3lib.history(api, tok, d).json()
        assert list(h["fields"]) == oracle.ALL_FIELDS
        for f in oracle.FIELDS:
            fv, ents = new["fields"][f], h["fields"][f]
            if fv["value"] is None:
                assert ents == [], (d, f)
                assert fv["true_from"] is None and fv["learned_at"] is None
                continue
            assert len(ents) == 1 and ents[0]["type"] == "initial", (d, f, ents)
            e = ents[0]
            assert e["value"] == fv["value"] and e["true_from"] is None
            assert parse_ts(e["learned_at"]) == parse_ts(old["researched_at"])
            assert [c["url"] for c in e["citations"]] == [c["url"] for c in fv["citations"]]
            assert fv["true_from"] is None and parse_ts(fv["learned_at"]) == parse_ts(old["researched_at"])
            for c in fv["candidates"]:
                assert c["true_from"] is None
                assert parse_ts(c["learned_at"]) == parse_ts(c["retrieved_at"])
        assert h["fields"]["executives"] == []
    assert s3lib.all_changes(api, tok) == []                         # the feed starts empty


def test_R3_UPG_02_stage1_import_counts_as_one_ready_build(from1):
    api, tok = from1["api"], from1["tok"]
    d = PR
    old = from1["snaps"][d]
    t = parse_ts(old["researched_at"])
    got = s3lib.as_of(api, tok, d, old["researched_at"])
    assert got.status_code == 200
    b = got.json()
    cur = api.get(tok, d).json()
    assert b == cur and b["state"] == "ready"
    assert s3lib.as_of(api, tok, d, "2027-01-01T00:00:00+00:00").json() == cur
    assert_error(s3lib.as_of(api, tok, d, "2026-02-28T23:59:59+00:00"), 404, "not_found")
    # never-ready dossier: every as_of is 404 until a build completes
    nr = "ledgerline-partners.test"
    assert api.get(tok, nr).json()["researched_at"] is None
    for ts in ("2026-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00"):
        assert_error(s3lib.as_of(api, tok, nr, ts), 404, "not_found")
        assert_error(s3lib.values(api, tok, nr, "2026-02-01", ts), 404, "not_found")
    assert s3lib.history(api, tok, nr).json()["fields"] == {f: [] for f in oracle.ALL_FIELDS}


def test_R3_UPG_03_stage1_import_values_hold_from_no_date_until_a_build(from1):
    """Imported candidates have no true_from: their versions hold from no date, so /values is empty
    at every date. The first later build (epoch 1, Effective 2026-01-01) is then the only version."""
    api, tok, mock = from1["api"], from1["tok"], from1["mock"]
    for ta in ("2020-01-01", "2026-02-01", "2030-01-01"):
        v = s3lib.values(api, tok, PR, ta).json()["fields"]
        assert all(x == {"value": None, "true_from": None, "citations": []} for x in v.values()), ta
    mock.epoch(1)
    api.clock("2026-03-10T09:00:00+00:00")
    assert api.refresh(tok, PR).status_code == 202
    b = api.wait(tok, PR)
    assert b["state"] == "ready"
    v = s3lib.values(api, tok, PR, "2026-02-01").json()["fields"]
    assert v["ceo"]["value"] == "Leon Brandt" and v["ceo"]["true_from"] == "2026-01-01"
    old_ts = from1["snaps"][PR]["researched_at"]
    v = s3lib.values(api, tok, PR, "2026-02-01", old_ts).json()["fields"]      # as of the import
    assert v["ceo"]["value"] is None


def test_R3_UPG_04_first_build_after_stage1_import_compares_with_the_imported_values(from1):
    api, tok, mock = from1["api"], from1["tok"], from1["mock"]
    mock.epoch(1)
    api.clock("2026-03-10T09:00:00+00:00")
    assert api.refresh(tok, PR).status_code == 202
    api.wait(tok, PR)
    feed = s3lib.all_changes(api, tok)
    got = [(e["field"], e["type"], e["from"], e["to"], e["true_from"]) for e in feed]
    # imported true_from is null: every difference is a change (never a correction)
    assert got == [("ceo", "change", "Hana Sato", "Leon Brandt", "2026-01-01"),
                   ("founded_year", "change", 2001, None, None)], got
    h = s3lib.history(api, tok, PR).json()["fields"]
    assert [e["type"] for e in h["ceo"]] == ["initial", "change"]
    assert parse_ts(h["ceo"][1]["learned_at"]) == parse_ts("2026-03-10T09:00:00+00:00")
    # executives: unknown after the import; the first build with a value adds a change, not initial
    mock.epoch(0)
    api.clock("2026-03-11T09:00:00+00:00")
    assert api.refresh(tok, CB).status_code == 202
    b = api.wait(tok, CB)
    assert [m["title"] for m in b["fields"]["executives"]["value"]] == ["cfo", "coo", "cto"]
    h = s3lib.history(api, tok, CB).json()["fields"]
    assert [e["type"] for e in h["executives"]] == ["change"]
    ex = [e for e in s3lib.all_changes(api, tok) if e["domain"] == CB]
    assert [(e["field"], e["type"], e["from"]) for e in ex] == [("executives", "change", None)]
    # the earlier as_of (the import) still shows executives unknown
    old_ts = from1["snaps"][CB]["researched_at"]
    assert s3lib.as_of(api, tok, CB, old_ts).json()["fields"]["executives"]["value"] is None
    # the first build that completes ready is not "initial" for a field that was empty at import
    assert [e["type"] for e in h["ceo"]] == []


def test_R3_UPG_05_stage1_tokens_accounts_and_replays_survive(from1):
    api, tok = from1["api"], from1["tok"]
    assert api.get(tok, PR).status_code == 200                       # old bearer token
    assert api.login(USERS[0]["email"], USERS[0]["password"]).status_code == 200
    idem = [x for x in from1["export"]["state"]["idempotency"]
            if x["slot"][2] == "/dossiers" and x["body"] == {"domain": PR}][0]
    r = api.create(tok, PR, key=idem["slot"][3])                     # a completed request replays
    assert r.status_code == 200 and r.json() == idem["response"]


# =========================================================== stage-2 export
@pytest.fixture()
def from2(api, mock):
    if not OLD2:
        pytest.skip("OLD2_BASE_URL (final stage-2 service) not set")
    old = Api(OLD2)
    mock.reset(0)
    old.reset()
    tok = old.token(0)
    snaps = {}
    snaps[NG] = [build_on(old, mock, tok, NG, 0, T0, True),
                 build_on(old, mock, tok, NG, 1, "2026-03-10T09:00:00+00:00", False)]
    snaps[HL] = [build_on(old, mock, tok, HL, 0, "2026-03-11T09:00:00+00:00", True)]
    export = old.req("GET", "/_test/export", timeout=10.0).json()
    mock.reset(0)
    api.reset(OTHER)
    do_import(api, export)
    assert mock.log() == []
    return dict(tok=tok, snaps=snaps, export=export, api=api, mock=mock)


def expected_true_from(c):
    """RUL-S3-15: the stage-2 export records no Effective line; the Published line it records
    (candidate.published_at) gives the date, in UTC; else null."""
    p = parse_ts(c["published_at"]) if c["published_at"] else None
    return p.astimezone(timezone.utc).date().isoformat() if p else None


@pytest.mark.parametrize("domain", [NG, HL])
def test_R3_UPG_06_stage2_import_keeps_stage2_fields_and_adds_times(from2, domain):
    api, tok = from2["api"], from2["tok"]
    old = from2["snaps"][domain][-1]
    new = api.get(tok, domain).json()
    assert_dossier_shape(new, domain)
    for k in ("dossier_id", "domain", "state", "researched_at", "spent_units"):
        assert new[k] == old[k], k
    assert six(new).keys() == six(old).keys()
    for f in oracle.FIELDS:
        o, n = old["fields"][f], new["fields"][f]
        assert (n["value"], n["status"], n["citations"]) == (o["value"], o["status"], o["citations"]), f
        assert [stage2_view(c) for c in n["candidates"]] == o["candidates"], f
        for c in n["candidates"]:
            assert parse_ts(c["learned_at"]) == parse_ts(c["retrieved_at"]), (f, c)
            assert c["true_from"] == expected_true_from(c), (f, c)
        if o["value"] is not None:
            assert n["true_from"] == n["candidates"][0]["true_from"]
            assert parse_ts(n["learned_at"]) == parse_ts(old["researched_at"])
    ex = new["fields"]["executives"]
    assert ex["value"] is None and ex["status"] == "unknown" and ex["candidates"] == []


@pytest.mark.parametrize("domain", [NG, HL])
def test_R3_UPG_07_stage2_import_history_as_of_and_feed(from2, domain):
    api, tok = from2["api"], from2["tok"]
    old = from2["snaps"][domain][-1]
    cur = api.get(tok, domain).json()
    h = s3lib.history(api, tok, domain).json()["fields"]
    for f in oracle.FIELDS:
        fv = cur["fields"][f]
        if fv["value"] is None:
            assert h[f] == []
        else:
            assert [e["type"] for e in h[f]] == ["initial"] and h[f][0]["value"] == fv["value"]
            assert parse_ts(h[f][0]["learned_at"]) == parse_ts(old["researched_at"])
            assert [c["url"] for c in h[f][0]["citations"]] == [c["url"] for c in fv["citations"]]
    assert h["executives"] == []
    assert s3lib.all_changes(api, tok) == []
    # one ready build at researched_at: as_of at or after answers the imported fields, before is 404
    assert s3lib.as_of(api, tok, domain, old["researched_at"]).json() == cur
    assert s3lib.as_of(api, tok, domain, "2027-01-01T00:00:00+00:00").json() == cur
    assert_error(s3lib.as_of(api, tok, domain, "2026-02-28T00:00:00+00:00"), 404, "not_found")


def test_R3_UPG_08_stage2_import_values_use_the_recorded_dates(from2):
    """/values: each imported candidate's URL is one version holding from its true_from."""
    api, tok = from2["api"], from2["tok"]
    cur = api.get(tok, NG).json()
    ceo = cur["fields"]["ceo"]["candidates"][0]
    ta = ceo["true_from"]
    assert ta is not None                                           # Published 2026-01-10
    v = s3lib.values(api, tok, NG, ta).json()["fields"]["ceo"]
    assert v["value"] == ceo["value"] and v["true_from"] == ta
    before = "2026-01-09"
    assert s3lib.values(api, tok, NG, before).json()["fields"]["ceo"]["value"] is None


def test_R3_UPG_09_first_build_after_stage2_import_compares_with_imported_values(from2):
    api, tok, mock = from2["api"], from2["tok"], from2["mock"]
    old = from2["snaps"][NG][-1]                                    # epoch 1: ceo Lee Park
    mock.epoch(2)
    api.clock("2026-03-20T09:00:00+00:00")
    assert api.refresh(tok, NG).status_code == 202
    assert api.wait(tok, NG)["state"] == "ready"
    feed = [e for e in s3lib.all_changes(api, tok) if e["domain"] == NG]
    ceo = [e for e in feed if e["field"] == "ceo"]
    assert len(ceo) == 1 and (ceo[0]["from"], ceo[0]["to"]) == ("Lee Park", "Maya Ito")
    assert ceo[0]["true_from"] == "2026-02-01"
    h = s3lib.history(api, tok, NG).json()["fields"]["ceo"]
    # imported true_from (2026-01-10 from Published) vs new 2026-02-01: a later date: change
    assert [e["type"] for e in h] == ["initial", "change"]
    assert [e["field"] for e in feed] == sorted([e["field"] for e in feed], key=oracle.ALL_FIELDS.index)


def test_R3_UPG_10_stage2_tokens_and_replays_survive(from2):
    api, tok = from2["api"], from2["tok"]
    assert api.get(tok, NG).status_code == 200
    idem = [x for x in from2["export"]["state"]["idempotency"]
            if x["slot"][2] == "/dossiers" and x["body"] == {"domain": NG}][0]
    r = api.create(tok, NG, key=idem["slot"][3])
    assert r.status_code == 200 and r.json() == idem["response"]


# =========================================================== stage-3 export (this service)
def test_R3_UPG_11_own_export_keeps_history_feed_builds(fresh):
    """History, feed, builds (as_of and /values) survive reset + import unchanged; new entries get a
    larger seq than every earlier one."""
    api, mock = fresh
    tok = api.token(0)
    script = [{"epoch": 0, "clock": T0}, {"epoch": 1, "clock": "2026-03-10T09:00:00+00:00"},
              {"epoch": 2, "clock": "2026-03-20T09:00:00+00:00"}]
    recs = s3lib.run(api, mock, tok, NG, script)
    s3lib.run(api, mock, tok, CB, [{"epoch": 0, "clock": "2026-03-21T09:00:00+00:00"},
                                   {"epoch": 1, "clock": "2026-03-22T09:00:00+00:00"}])
    probe = lambda: dict(
        cur=[api.get(tok, d).json() for d in (NG, CB)],
        hist=[s3lib.history(api, tok, d).json() for d in (NG, CB)],
        feed=s3lib.all_changes(api, tok),
        asof=[s3lib.as_of(api, tok, NG, ts).json() for ts in (T0, "2026-03-15T00:00:00+00:00",
                                                              "2026-03-20T09:00:00+00:00")],
        vals=[s3lib.values(api, tok, NG, ta, ao).json() for ta, ao in (
            ("2025-06-01", T0), ("2026-02-15", "2026-03-20T09:00:00+00:00"),
            ("2026-03-25", "2026-03-10T09:00:00+00:00"))],
        lst=api.list(tok).json())
    before = probe()
    assert before["feed"], "scenario produced no feed"
    export = api.req("GET", "/_test/export", timeout=10.0).json()
    api.reset(OTHER)
    other = api.login("other@example.org", "xxxxxxxx-1").json()["token"]
    assert s3lib.all_changes(api, other) == []
    do_import(api, export)
    assert probe() == before
    assert api.req("GET", "/_test/export", timeout=10.0).json() == export
    do_import(api, export)                                           # repeating changes nothing
    assert probe() == before
    mock.epoch(3)
    api.clock("2026-04-01T09:00:00+00:00")
    assert api.refresh(tok, NG).status_code == 202
    api.wait(tok, NG)
    feed = s3lib.all_changes(api, tok)
    assert feed[:len(before["feed"])] == before["feed"]
    assert len(feed) > len(before["feed"])
    assert feed[len(before["feed"])]["seq"] > before["feed"][-1]["seq"]
    # the build list kept its order: as_of between builds is unchanged by the later build
    assert [s3lib.as_of(api, tok, NG, ts).json() for ts in (T0, "2026-03-15T00:00:00+00:00",
                                                            "2026-03-20T09:00:00+00:00")] == before["asof"]
