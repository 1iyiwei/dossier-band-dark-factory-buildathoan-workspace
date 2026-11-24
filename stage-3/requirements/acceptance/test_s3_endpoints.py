"""Stage 3 (API): validation of the new endpoints, a feed shared by several dossiers, builds with
equal times, a dossier whose first build fails. Short scripted companies; fresh service per test."""
import pytest

import oracle
import s3lib
import timeline as tl
from lib import T0, assert_error, parse_ts

pytestmark = pytest.mark.corpus

PR = "pivotal-reed.test"
HG = "harrow-guild.test"


# ------------------------------------------------------------------ /changes validation
@pytest.mark.parametrize("params", [
    {"since": "-1"}, {"since": "abc"}, {"since": "1.0"}, {"since": "1e3"}, {"since": "+1"},
    {"since": ""}, {"since": "0x10"}, {"limit": "0"}, {"limit": "201"}, {"limit": "-5"},
    {"limit": "abc"}, {"limit": "1.5"}, {"limit": "4.0"}, {"limit": "1e1"}, {"limit": ""},
    {"limit": "+4"}, {"since": "1", "limit": "0"}])
def test_R3_CHG_06_invalid_since_or_limit_is_422(fresh, params):
    api, _ = fresh
    assert_error(s3lib.changes(api, api.token(0), **params), 422, "validation_failed")


def test_R3_CHG_07_valid_edges_and_unknown_params(fresh):
    api, _ = fresh
    tok = api.token(0)
    for params in ({"since": "0"}, {"since": "007"}, {"limit": "1"}, {"limit": "200"},
                   {"limit": "50", "since": "99999999999"}, {"unknown": "x"}):
        r = s3lib.changes(api, tok, **params)
        assert r.status_code == 200, (params, r.text)
        assert r.json() == {"changes": [], "has_more": False}
    assert_error(api.req("GET", "/changes"), 401, "unauthenticated")


# ------------------------------------------------------------------ one feed for every dossier
def test_R3_CHG_08_feed_interleaves_dossiers_by_build_order(fresh):
    api, mock = fresh
    tok = api.token(0)
    steps = [(PR, 0, T0), (HG, 0, "2026-03-02T09:00:00+00:00"), (PR, 1, "2026-03-03T09:00:00+00:00"),
             (HG, 1, "2026-03-04T09:00:00+00:00"), (PR, 0, "2026-03-05T09:00:00+00:00")]
    started = set()
    for dom, epoch, clock in steps:
        mock.epoch(epoch)
        api.clock(clock)
        r = api.refresh(tok, dom) if dom in started else api.create(tok, dom)
        started.add(dom)
        assert r.status_code in (200, 202), r.text
        assert api.wait(tok, dom)["state"] == "ready"
    feed = s3lib.all_changes(api, tok)
    got = [(e["domain"], e["field"], e["type"], e["from"], e["to"]) for e in feed]
    assert got == [
        (PR, "ceo", "correction", "Hana Sato", "Leon Brandt"),                # PR epoch 1
        (PR, "founded_year", "change", 2001, None),
        (HG, "executives", "change",
         [{"title": "cfo", "name": "Ines Moreau"}, {"title": "cto", "name": "Joel Brandt"}],
         [{"title": "cfo", "name": "Ines Moreau"}, {"title": "cto", "name": "Kai Larsen"}]),   # HG epoch 1
        (PR, "ceo", "correction", "Leon Brandt", "Hana Sato"),                # PR epoch 0 again
        (PR, "founded_year", "change", None, 2001),
    ], got
    assert [e["seq"] for e in feed] == sorted({e["seq"] for e in feed})
    # both pages say Effective 2026-01-01: a new true_from equal to the earlier one is "on or before"
    assert feed[3]["true_from"] == "2026-01-01" and feed[0]["true_from"] == "2026-01-01"
    assert s3lib.changes(api, api.token(1)).json()["changes"] == feed            # one feed for every user
    assert [parse_ts(e["learned_at"]) for e in feed] == [parse_ts(c) for c in (
        "2026-03-03T09:00:00+00:00", "2026-03-03T09:00:00+00:00", "2026-03-04T09:00:00+00:00",
        "2026-03-05T09:00:00+00:00", "2026-03-05T09:00:00+00:00")]


# ------------------------------------------------------------------ equal build times, offsets
def test_R3_ASO_10_builds_with_the_same_time_return_the_last_in_build_order(fresh):
    """The clock need not advance between builds; equal instants written with different offsets
    count as the same time. as_of that instant answers with the last ready build."""
    api, mock = fresh
    tok = api.token(0)
    api.clock(T0)
    recs = s3lib.run(api, mock, tok, PR, [
        {"epoch": 0, "clock": T0},
        {"epoch": 1},                                                    # clock not moved
        {"epoch": 0, "clock": "2026-03-01T10:00:00+01:00"},              # same instant, other offset
        {"epoch": 1, "clock": "2026-03-01T04:00:00-05:00"}])
    assert [r.snap["fields"]["ceo"]["value"] for r in recs] == [
        "Hana Sato", "Leon Brandt", "Hana Sato", "Leon Brandt"]
    for ts in (T0, "2026-03-01T10:00:00+01:00", "2026-03-01T09:00:00Z", "2026-03-02T00:00:00+00:00"):
        b = s3lib.as_of(api, tok, PR, ts).json()
        assert b["fields"]["ceo"]["value"] == "Leon Brandt", ts          # the 4th build, not the 1st
        assert b["spent_units"] == recs[-1].snap["spent_units"], ts      # all four builds' spending
        assert parse_ts(b["researched_at"]) == parse_ts(T0)
    # a build at the same time appended later wins again
    mock.epoch(0)
    assert api.refresh(tok, PR).status_code == 202
    api.wait(tok, PR)
    assert s3lib.as_of(api, tok, PR, T0).json()["fields"]["ceo"]["value"] == "Hana Sato"


def test_R3_VAL_06_versions_of_one_url_with_equal_true_from_replace_each_other(fresh):
    """By hand: pivotal-reed's `/` page has Effective 2026-01-01 in every build; a later version
    replaces every earlier one whose true_from is on or after its own, so the latest build wins."""
    api, mock = fresh
    tok = api.token(0)
    recs = s3lib.run(api, mock, tok, PR, [
        {"epoch": 0, "clock": T0}, {"epoch": 1, "clock": "2026-03-02T09:00:00+00:00"},
        {"epoch": 0, "clock": "2026-03-03T09:00:00+00:00"}])
    for as_of_ts, ceo in ((T0, "Hana Sato"), ("2026-03-02T09:00:00+00:00", "Leon Brandt"),
                          ("2026-03-03T09:00:00+00:00", "Hana Sato")):
        v = s3lib.values(api, tok, PR, "2026-02-01", as_of_ts).json()["fields"]
        assert v["ceo"]["value"] == ceo and v["ceo"]["true_from"] == "2026-01-01", as_of_ts
    # before the page's Effective date nothing holds
    v = s3lib.values(api, tok, PR, "2025-12-31", "2026-03-03T09:00:00+00:00").json()["fields"]
    assert v["ceo"] == {"value": None, "true_from": None, "citations": []}
    # founded_year was on the epoch-0 page only: epoch 1's version (no candidate) replaced it
    v = s3lib.values(api, tok, PR, "2026-02-01", "2026-03-02T09:00:00+00:00").json()["fields"]
    assert v["founded_year"]["value"] is None
    v = s3lib.values(api, tok, PR, "2026-02-01", "2026-03-03T09:00:00+00:00").json()["fields"]
    assert v["founded_year"]["value"] == 2001


# ------------------------------------------------------------------ a first build that fails
def test_R3_HIS_06_dossier_without_a_ready_build(fresh):
    api, mock = fresh
    tok = api.token(0)
    s3lib.fail_providers(mock, True)
    assert api.create(tok, PR).status_code == 202
    assert api.wait(tok, PR)["state"] == "failed"
    h = s3lib.history(api, tok, PR)
    assert h.status_code == 200 and h.json()["domain"] == PR
    assert h.json()["fields"] == {f: [] for f in oracle.ALL_FIELDS}
    assert_error(s3lib.as_of(api, tok, PR, "2027-01-01T00:00:00+00:00"), 404, "not_found")
    assert_error(s3lib.values(api, tok, PR, "2026-02-01"), 404, "not_found")
    assert s3lib.all_changes(api, tok) == []
    s3lib.fail_providers(mock, False)
    mock.epoch(0)
    assert api.refresh(tok, PR).status_code == 202
    assert api.wait(tok, PR)["state"] == "ready"
    h = s3lib.history(api, tok, PR).json()["fields"]
    assert [e["type"] for e in h["ceo"]] == ["initial"]       # the first build that completes ready
    assert s3lib.all_changes(api, tok) == []                   # no feed entry for initial values
    assert s3lib.as_of(api, tok, PR, "2027-01-01T00:00:00+00:00").status_code == 200


def test_R3_HIS_07_timestamps_are_rfc3339_with_offset(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, HG)
    mock.epoch(1)
    api.clock("2026-03-05T09:00:00+00:00")
    api.refresh(tok, HG)
    api.wait(tok, HG)
    for e in s3lib.history(api, tok, HG).json()["fields"]["executives"]:
        parse_ts(e["learned_at"])
    for e in s3lib.all_changes(api, tok):
        parse_ts(e["learned_at"])
    parse_ts(s3lib.values(api, tok, HG, "2026-03-05").json()["as_of"])
