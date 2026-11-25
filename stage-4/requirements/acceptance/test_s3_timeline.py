"""Stage 3 (API): two times per value, history, the change feed, `?as_of=` and `/values`, driven by
a scripted company (northgate-labs.test, corpus_spec.py) whose pages change from epoch to epoch.

One module-scoped scenario builds the dossier seven times (one build fails, one repeats an epoch);
every test then only reads. Expected values come from timeline.py (the oracle, itself checked offline
by test_timeline_unit.py) and, where marked "by hand", are written out from the specification.
"""
import concurrent.futures as cf
from datetime import datetime, timedelta

import pytest

import oracle
import s3lib
import timeline as tl
from lib import FIXTURE, T0, assert_dossier_shape, assert_error, parse_ts

pytestmark = pytest.mark.corpus

D = "northgate-labs.test"
SCRIPT = [
    {"epoch": 0, "clock": T0},
    {"epoch": 1, "clock": "2026-03-10T09:00:00+00:00"},
    {"epoch": 2, "clock": "2026-03-20T09:00:00+00:00"},
    {"epoch": 2, "clock": "2026-03-22T09:00:00+00:00"},                 # same selected values again
    {"epoch": 2, "clock": "2026-03-25T09:00:00+00:00", "fail": True},   # failed build
    {"epoch": 3, "clock": "2026-04-01T09:00:00+00:00"},
    {"epoch": 4, "clock": "2026-04-10T09:00:00+00:00"},
]
TIMES = [s["clock"] for s in SCRIPT]


@pytest.fixture(scope="module")
def sc(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    recs = s3lib.run(api, mock, tok, D, SCRIPT)
    builds = s3lib.to_builds(recs, D)
    sim = tl.simulate(builds, D)
    return dict(api=api, mock=mock, tok=tok, recs=recs, builds=builds, sim=sim)


def get(sc, path, **params):
    return sc["api"].req("GET", path, token=sc["tok"], params=params or None)


def ready_indices(sc):
    return [i for i, r in enumerate(sc["recs"]) if r.ready]


# ------------------------------------------------------------------ two times per value
def test_R3_TT_01_every_build_matches_the_oracle(sc):
    """R3-TT-01..08: candidates and fields of every build carry true_from and learned_at as the
    spec defines them (Effective, Published fallback, null; first build that gathered the same
    field/value/URL/provider; the build that made the value selected)."""
    for i in ready_indices(sc):
        assert_dossier_shape(sc["recs"][i].snap, D)
        probs = s3lib.snapshot_problems(sc["recs"][i].snap, D, sc["recs"], i, sc["builds"], sc["sim"])
        assert not probs, f"build {i} ({SCRIPT[i]['clock']}):\n" + "\n".join(probs)


def test_R3_TT_02_by_hand_true_from_sources(sc):
    """By hand: Effective line; invalid Effective falls back to the UTC date of Published; neither
    gives null."""
    ceo = {i: sc["recs"][i].snap["fields"]["ceo"] for i in ready_indices(sc)}
    assert (ceo[0]["value"], ceo[0]["true_from"]) == ("Dana Ruiz", "2021-04-01")
    assert (ceo[1]["value"], ceo[1]["true_from"]) == ("Lee Park", "2026-03-20")
    assert (ceo[2]["value"], ceo[2]["true_from"]) == ("Maya Ito", "2026-02-01")
    # Effective: 2026-13-45; Published: 2026-04-02T23:30:00-05:00 = 2026-04-03T04:30Z
    assert (ceo[5]["value"], ceo[5]["true_from"]) == ("Nora Voss", "2026-04-03")
    # no Effective, no Published
    assert (ceo[6]["value"], ceo[6]["true_from"]) == ("Paul Quist", None)
    assert ceo[6]["candidates"][0]["true_from"] is None
    assert ceo[6]["candidates"][0]["published_at"] is None


def test_R3_TT_03_by_hand_learned_at_and_retrieved_at(sc):
    """By hand (build 1, 2026-03-10): founded_year 2012 was first gathered by build 0 (same field,
    value, URL, provider), so its learned_at stays 2026-03-01 although the page changed and
    retrieved_at is now 2026-03-10; the new CEO candidate is first gathered now."""
    b = sc["recs"][1].snap
    fy = b["fields"]["founded_year"]
    assert fy["value"] == 2012 and fy["status"] == "known"
    c = fy["candidates"][0]
    assert parse_ts(c["learned_at"]) == parse_ts(T0)
    assert parse_ts(c["retrieved_at"]) == parse_ts("2026-03-10T09:00:00+00:00")
    assert c["true_from"] == "2026-03-20"                      # the page's Effective now
    assert fy["true_from"] == "2026-03-20"
    assert parse_ts(fy["learned_at"]) == parse_ts(T0)          # same selected value: made selected at build 0
    ceo = b["fields"]["ceo"]
    assert parse_ts(ceo["learned_at"]) == parse_ts("2026-03-10T09:00:00+00:00")
    assert parse_ts(ceo["candidates"][0]["learned_at"]) == parse_ts("2026-03-10T09:00:00+00:00")
    assert parse_ts(b["researched_at"]) == parse_ts("2026-03-10T09:00:00+00:00")


def test_R3_TT_04_learned_at_of_unchanged_values_survives_rebuilds(sc):
    """A repeated build (epoch 2 twice) changes retrieved_at and nothing else: every field keeps its
    learned_at and every candidate its learned_at."""
    a, b = sc["recs"][2].snap, sc["recs"][3].snap
    for f in oracle.ALL_FIELDS:
        assert a["fields"][f]["value"] == b["fields"][f]["value"], f
        assert a["fields"][f]["learned_at"] == b["fields"][f]["learned_at"], f
        for ca, cb in zip(a["fields"][f]["candidates"], b["fields"][f]["candidates"]):
            assert ca["learned_at"] == cb["learned_at"], (f, ca, cb)
            assert parse_ts(cb["retrieved_at"]) == parse_ts("2026-03-22T09:00:00+00:00")
    assert all(e["learned_at"] != sc["recs"][3].time for e in sc["sim"].feed)


def test_R3_TT_05_unknown_field_has_null_times(sc):
    b = sc["recs"][0].snap
    for f in ("headcount_range",):
        fv = b["fields"][f]
        assert fv["status"] == "unknown" and fv["value"] is None
        assert fv["true_from"] is None and fv["learned_at"] is None and fv["candidates"] == []
    f = sc["recs"][5].snap["fields"]["funding_total"]          # page vanished at epoch 3
    assert f["value"] is None and f["true_from"] is None and f["learned_at"] is None


def test_R3_TT_06_plain_get_after_failed_build_is_unchanged(sc):
    """A failed build leaves the fields as they were (stage 1) and adds no history or feed."""
    failed, prev = sc["recs"][4], sc["recs"][3]
    assert failed.snap["state"] == "failed"
    assert failed.snap["fields"] == prev.snap["fields"]
    assert parse_ts(failed.snap["researched_at"]) == prev.time


# ------------------------------------------------------------------ history
def test_R3_HIS_01_history_matches_the_oracle(sc):
    r = s3lib.history(sc["api"], sc["tok"], D)
    assert r.status_code == 200, r.text
    probs = s3lib.history_problems(r.json(), D, sc["recs"], sc["builds"], sc["sim"])
    assert not probs, "\n".join(probs)


def test_R3_HIS_02_by_hand_types(sc):
    """By hand: ceo initial, change (later true_from), correction (true_from on or before the
    earlier one), change, change (true_from null). Same selected value adds nothing."""
    h = s3lib.history(sc["api"], sc["tok"], D).json()["fields"]
    assert [e["type"] for e in h["ceo"]] == ["initial", "change", "correction", "change", "change"]
    assert [e["value"] for e in h["ceo"]] == ["Dana Ruiz", "Lee Park", "Maya Ito", "Nora Voss", "Paul Quist"]
    assert [e["true_from"] for e in h["ceo"]] == ["2021-04-01", "2026-03-20", "2026-02-01", "2026-04-03", None]
    assert [parse_ts(e["learned_at"]) for e in h["ceo"]] == [parse_ts(t) for t in (
        T0, "2026-03-10T09:00:00+00:00", "2026-03-20T09:00:00+00:00",
        "2026-04-01T09:00:00+00:00", "2026-04-10T09:00:00+00:00")]
    # founded_year: 2012 stays selected while its page's true_from moves (no entry); then it vanishes
    assert [(e["type"], e["value"]) for e in h["founded_year"]] == [("initial", 2012), ("change", None)]
    assert h["founded_year"][0]["true_from"] == "2021-04-01"       # as recorded by the first build
    assert h["founded_year"][1]["true_from"] is None and h["founded_year"][1]["citations"] == []
    # funding: change on a later true_from; same value on a later true_from adds nothing; disappears
    assert [(e["type"], e["value"]) for e in h["funding_total"]] == [
        ("initial", 5000000), ("change", 12000000), ("change", None)]
    # a field that was unknown after the first ready build: its first entry is a change
    assert [(e["type"], e["value"]) for e in h["headcount_range"]] == [("change", "51-200")]
    assert h["headcount_range"][0]["true_from"] == "2026-03-18"
    # stable fields: one initial entry only
    assert [e["type"] for e in h["legal_name"]] == ["initial"]
    assert [e["type"] for e in h["executives"]] == ["initial"]
    assert h["legal_name"][0]["value"] == "Northgate Labs AS"
    assert h["legal_name"][0]["citations"] and all(
        c["url"] == "https://northgate-labs.test/facts" for c in h["legal_name"][0]["citations"])


def test_R3_HIS_03_value_returning_after_null_is_a_new_entry(sc):
    h = s3lib.history(sc["api"], sc["tok"], D).json()["fields"]["hq_city"]
    assert [(e["type"], e["value"]) for e in h] == [("initial", "Oslo"), ("change", None),
                                                    ("change", "Bergen")]
    assert h[1]["true_from"] is None and h[1]["citations"] == []
    assert h[2]["true_from"] == "2026-01-01"            # earlier than Oslo's, but from null: change


def test_R3_HIS_04_failed_and_repeated_builds_add_nothing(sc):
    h = s3lib.history(sc["api"], sc["tok"], D).json()["fields"]
    n_entries = sum(len(v) for v in h.values())
    assert n_entries == sum(len(v) for v in sc["sim"].history.values())
    learned = {parse_ts(e["learned_at"]) for v in h.values() for e in v}
    assert sc["recs"][3].time not in learned and sc["recs"][4].time not in learned


def test_R3_HIS_05_shape_and_unknown_domain(sc):
    r = s3lib.history(sc["api"], sc["tok"], "WWW.Northgate-Labs.TEST.")
    assert r.status_code == 200 and r.json()["domain"] == D          # path domain is normalised
    assert list(r.json()["fields"]) == oracle.ALL_FIELDS
    assert_error(s3lib.history(sc["api"], sc["tok"], "no-such-company.test"), 404, "not_found")
    assert_error(s3lib.history(sc["api"], sc["tok"], "not_a_domain"), 422, "validation_failed")


# ------------------------------------------------------------------ change feed
def test_R3_CHG_01_feed_matches_the_oracle(sc):
    feed = s3lib.all_changes(sc["api"], sc["tok"])
    probs = s3lib.feed_problems(feed, D, sc["sim"])
    assert not probs, "\n".join(probs)
    assert all(e["type"] in ("change", "correction") for e in feed)      # never `initial`


def test_R3_CHG_02_by_hand_entries(sc):
    feed = s3lib.all_changes(sc["api"], sc["tok"])
    ceo = [e for e in feed if e["field"] == "ceo"]
    assert [(e["from"], e["to"], e["type"], e["true_from"]) for e in ceo] == [
        ("Dana Ruiz", "Lee Park", "change", "2026-03-20"),
        ("Lee Park", "Maya Ito", "correction", "2026-02-01"),
        ("Maya Ito", "Nora Voss", "change", "2026-04-03"),
        ("Nora Voss", "Paul Quist", "change", None)]
    assert [parse_ts(e["learned_at"]) for e in ceo] == [parse_ts(t) for t in (
        "2026-03-10T09:00:00+00:00", "2026-03-20T09:00:00+00:00", "2026-04-01T09:00:00+00:00",
        "2026-04-10T09:00:00+00:00")]
    fund = [e for e in feed if e["field"] == "funding_total"]
    assert [(e["from"], e["to"], e["type"]) for e in fund] == [(5000000, 12000000, "change"),
                                                                (12000000, None, "change")]
    hc = [e for e in feed if e["field"] == "headcount_range"]
    assert [(e["from"], e["to"], e["type"], e["true_from"]) for e in hc] == [
        (None, "51-200", "change", "2026-03-18")]
    assert not [e for e in feed if e["field"] in ("legal_name", "executives")]
    assert len(feed) == 10


def test_R3_CHG_03_order_within_one_build_is_field_order(sc):
    feed = s3lib.all_changes(sc["api"], sc["tok"])
    by_time = {}
    for e in feed:
        by_time.setdefault(parse_ts(e["learned_at"]), []).append(e)
    b2 = by_time[parse_ts("2026-03-20T09:00:00+00:00")]
    assert [e["field"] for e in b2] == ["hq_city", "ceo", "founded_year", "headcount_range"]
    assert [e["seq"] for e in b2] == sorted(e["seq"] for e in b2)
    seqs = [e["seq"] for e in feed]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs) and seqs[0] >= 1


def test_R3_CHG_04_since_limit_and_has_more(sc):
    feed = s3lib.all_changes(sc["api"], sc["tok"])
    n = len(feed)
    b = s3lib.changes(sc["api"], sc["tok"]).json()                 # defaults since=0 limit=50
    assert b["changes"] == feed and b["has_more"] is False
    b = s3lib.changes(sc["api"], sc["tok"], since=0, limit=3).json()
    assert [e["seq"] for e in b["changes"]] == [e["seq"] for e in feed[:3]] and b["has_more"] is True
    b = s3lib.changes(sc["api"], sc["tok"], limit=n).json()
    assert len(b["changes"]) == n and b["has_more"] is False
    b = s3lib.changes(sc["api"], sc["tok"], limit=n - 1).json()
    assert len(b["changes"]) == n - 1 and b["has_more"] is True
    mid = feed[4]["seq"]
    b = s3lib.changes(sc["api"], sc["tok"], since=mid).json()
    assert [e["seq"] for e in b["changes"]] == [e["seq"] for e in feed[5:]]
    b = s3lib.changes(sc["api"], sc["tok"], since=feed[-1]["seq"]).json()
    assert b == {"changes": [], "has_more": False}
    b = s3lib.changes(sc["api"], sc["tok"], since=feed[-1]["seq"] + 1000, limit=200).json()
    assert b == {"changes": [], "has_more": False}
    # paging by the last seq returns each entry once
    seen, since = [], 0
    while True:
        p = s3lib.changes(sc["api"], sc["tok"], since=since, limit=4).json()
        seen += p["changes"]
        if not p["has_more"]:
            break
        since = p["changes"][-1]["seq"]
    assert seen == feed


def test_R3_CHG_05_reads_do_not_change_anything(sc):
    before = s3lib.all_changes(sc["api"], sc["tok"])
    for _ in range(3):
        s3lib.changes(sc["api"], sc["tok"])
        sc["api"].get(sc["tok"], D)
    assert s3lib.all_changes(sc["api"], sc["tok"]) == before


# ------------------------------------------------------------------ as_of
def expected_as_of(sc, ts):
    """The body `?as_of=ts` must return, from the snapshots recorded right after each build."""
    t = parse_ts(ts)
    ready = [i for i, r in enumerate(sc["recs"]) if r.ready and r.time <= t]
    if not ready:
        return None
    last_any = max(i for i, r in enumerate(sc["recs"]) if r.time <= t)
    body = dict(sc["recs"][ready[-1]].snap)
    body["state"] = "ready"
    body["spent_units"] = sc["recs"][last_any].snap["spent_units"]
    return body


AS_OF_TIMES = [T0, "2026-03-05T00:00:00+00:00", "2026-03-10T09:00:00+00:00",
               "2026-03-15T00:00:00+00:00", "2026-03-20T09:00:00+00:00",
               "2026-03-21T00:00:00+00:00", "2026-03-22T09:00:00+00:00",
               "2026-03-26T00:00:00+00:00", "2026-04-01T08:59:59+00:00",
               "2026-04-01T09:00:00+00:00", "2026-04-10T09:00:00+00:00", "2027-01-01T00:00:00+00:00"]


@pytest.mark.parametrize("ts", AS_OF_TIMES)
def test_R3_ASO_01_as_of_returns_the_dossier_as_it_was(sc, ts):
    r = s3lib.as_of(sc["api"], sc["tok"], D, ts)
    assert r.status_code == 200, r.text
    assert r.json() == expected_as_of(sc, ts), ts
    assert r.json()["state"] == "ready"


def test_R3_ASO_02_by_hand_learned_at_decides_not_true_from(sc):
    """Build 2 (2026-03-20) holds Maya Ito with true_from 2026-02-01, earlier than build 1's
    2026-03-20 value. as_of 2026-03-15 is decided by learned_at: Lee Park."""
    b = s3lib.as_of(sc["api"], sc["tok"], D, "2026-03-15T00:00:00+00:00").json()
    assert b["fields"]["ceo"]["value"] == "Lee Park" and b["fields"]["ceo"]["true_from"] == "2026-03-20"
    assert parse_ts(b["researched_at"]) == parse_ts("2026-03-10T09:00:00+00:00")
    assert b["fields"]["ceo"]["learned_at"] == sc["recs"][1].snap["fields"]["ceo"]["learned_at"]
    b = s3lib.as_of(sc["api"], sc["tok"], D, "2026-03-21T00:00:00+00:00").json()
    assert b["fields"]["ceo"]["value"] == "Maya Ito"


def test_R3_ASO_03_snapshot_uses_no_later_history(sc):
    """In the as_of answer for build 0, funding_total's learned_at/true_from are those of build 0
    even though later builds changed it."""
    b = s3lib.as_of(sc["api"], sc["tok"], D, T0).json()
    f = b["fields"]["funding_total"]
    assert f["value"] == 5000000 and f["true_from"] == "2020-06-01"
    assert parse_ts(f["learned_at"]) == parse_ts(T0)
    assert b["fields"]["headcount_range"]["learned_at"] is None


def test_R3_ASO_04_spent_units_is_the_total_of_builds_up_to_as_of(sc):
    spent = [r.snap["spent_units"] for r in sc["recs"]]
    assert spent == sorted(spent) and spent[0] > 0
    for ts, i in ((T0, 0), ("2026-03-15T00:00:00+00:00", 1), ("2026-03-21T00:00:00+00:00", 2),
                  ("2026-03-23T00:00:00+00:00", 3), ("2026-04-02T00:00:00+00:00", 5)):
        assert s3lib.as_of(sc["api"], sc["tok"], D, ts).json()["spent_units"] == spent[i], ts
    cur = sc["api"].get(sc["tok"], D).json()
    assert cur["spent_units"] == spent[-1] and s3lib.as_of(
        sc["api"], sc["tok"], D, "2027-01-01T00:00:00+00:00").json()["spent_units"] == spent[-1]


def test_R3_ASO_05_offsets_and_z(sc):
    base = s3lib.as_of(sc["api"], sc["tok"], D, "2026-03-10T09:00:00+00:00").json()
    for ts in ("2026-03-10T10:00:00+01:00", "2026-03-10T04:00:00-05:00", "2026-03-10T09:00:00Z",
               "2026-03-10T09:00:00.000+00:00"):
        r = s3lib.as_of(sc["api"], sc["tok"], D, ts)
        assert r.status_code == 200 and r.json() == base, ts
    before = s3lib.as_of(sc["api"], sc["tok"], D, "2026-03-10T09:59:59+01:00")
    assert before.json()["fields"]["ceo"]["value"] == "Dana Ruiz"      # 08:59:59Z: build 0 only


def test_R3_ASO_06_not_found(sc):
    assert_error(s3lib.as_of(sc["api"], sc["tok"], D, "2026-02-28T23:59:59+00:00"), 404, "not_found")
    assert_error(s3lib.as_of(sc["api"], sc["tok"], D, "2026-03-01T09:59:59+01:00"), 404, "not_found")
    assert_error(s3lib.as_of(sc["api"], sc["tok"], "no-such-company.test", T0), 404, "not_found")


@pytest.mark.parametrize("bad", ["2026-03-15", "2026-03-15T00:00:00", "2026-03-15 00:00:00+00:00",
                                 "yesterday", "", "1773554400", "2026-03-15T00:00:00+0000",
                                 "2026-03-15T25:00:00+00:00", "2026-02-30T00:00:00+00:00",
                                 "2026-03-15T00:00:00+24:00"])
def test_R3_ASO_07_invalid_as_of_is_422(sc, bad):
    assert_error(s3lib.as_of(sc["api"], sc["tok"], D, bad), 422, "validation_failed")


def test_R3_ASO_08_without_as_of_the_dossier_is_unchanged(sc):
    cur = sc["api"].get(sc["tok"], D).json()
    assert cur == sc["recs"][-1].snap and cur["state"] == "ready"
    assert s3lib.as_of(sc["api"], sc["tok"], D, "2027-01-01T00:00:00+00:00").json() == cur


def test_R3_ASO_09_as_of_makes_no_provider_call_and_needs_auth(sc):
    n = len(sc["mock"].log())
    s3lib.as_of(sc["api"], sc["tok"], D, T0)
    s3lib.values(sc["api"], sc["tok"], D, "2025-06-01")
    s3lib.history(sc["api"], sc["tok"], D)
    s3lib.changes(sc["api"], sc["tok"])
    assert len(sc["mock"].log()) == n
    for path, params in ((f"/dossiers/{D}", {"as_of": T0}), (f"/dossiers/{D}/history", None),
                         (f"/dossiers/{D}/values", {"true_at": "2025-06-01"}), ("/changes", None)):
        assert_error(sc["api"].req("GET", path, params=params), 401, "unauthenticated")
        assert_error(sc["api"].req("GET", path, token="nope", params=params), 401, "unauthenticated")


# ------------------------------------------------------------------ /values
TRUE_AT = ["2018-01-01", "2019-06-01", "2020-06-01", "2021-03-31", "2021-04-01", "2025-06-01",
           "2026-01-01", "2026-02-01", "2026-02-15", "2026-03-01", "2026-03-05", "2026-03-09",
           "2026-03-10", "2026-03-15", "2026-03-17", "2026-03-18", "2026-03-19", "2026-03-20",
           "2026-03-25", "2026-04-02", "2026-04-03", "2026-06-01", "2030-01-01"]
VAL_AS_OF = [T0, "2026-03-10T09:00:00+00:00", "2026-03-15T00:00:00+00:00",
             "2026-03-20T09:00:00+00:00", "2026-03-26T00:00:00+00:00",
             "2026-04-01T09:00:00+00:00", "2026-04-10T09:00:00+00:00", "2027-01-01T00:00:00+00:00"]


@pytest.mark.parametrize("as_of_ts", VAL_AS_OF)
def test_R3_VAL_01_values_follow_the_page_version_rule(sc, as_of_ts):
    """For every true_at in the matrix: the value the evidence known at as_of says held then."""
    probs = []
    for ta in TRUE_AT:
        r = s3lib.values(sc["api"], sc["tok"], D, ta, as_of_ts)
        assert r.status_code == 200, (ta, r.text)
        probs += [f"true_at {ta}: {p}" for p in s3lib.check_values(
            r.json(), D, sc["recs"], sc["builds"], parse_ts(as_of_ts), ta, as_of_ts)]
    assert not probs, f"as_of {as_of_ts}\n" + "\n".join(probs)


def test_R3_VAL_02_by_hand_replace_and_end_rules(sc):
    """By hand from the spec's version rule (ceo page /about; hq page /team)."""
    v = lambda ta, ao: s3lib.values(sc["api"], sc["tok"], D, ta, ao).json()["fields"]
    a2 = "2026-03-20T09:00:00+00:00"
    # build 2's Maya (true_from 2026-02-01) replaced build 1's Lee (2026-03-20 on/after it);
    # Dana's version stops holding on 2026-02-01
    assert v("2025-06-01", a2)["ceo"]["value"] == "Dana Ruiz"
    assert v("2026-01-31", a2)["ceo"]["value"] == "Dana Ruiz"
    assert v("2026-02-01", a2)["ceo"]["value"] == "Maya Ito"
    assert v("2026-03-25", a2)["ceo"]["value"] == "Maya Ito"
    assert v("2026-02-15", a2)["ceo"]["true_from"] == "2026-02-01"
    assert v("2021-03-31", a2)["ceo"] == {"value": None, "true_from": None, "citations": []}
    # as of build 1 (before the correction) Lee Park held from 2026-03-20
    a1 = "2026-03-10T09:00:00+00:00"
    assert v("2026-03-19", a1)["ceo"]["value"] == "Dana Ruiz"
    assert v("2026-03-20", a1)["ceo"]["value"] == "Lee Park"
    # a null true_from replaces every earlier version of its URL and holds from no date
    a6 = "2026-04-10T09:00:00+00:00"
    for ta in ("2021-04-01", "2026-02-15", "2026-04-03", "2030-01-01"):
        assert v(ta, a6)["ceo"] == {"value": None, "true_from": None, "citations": []}, ta
    # a gathered version with no candidates ends an earlier version (hq at build 1: 2026-03-10)
    assert v("2026-03-09", a1)["hq_city"]["value"] == "Oslo"
    assert v("2026-03-10", a1)["hq_city"]["value"] is None
    # ... and a later version replaces it (build 2, true_from 2026-01-01): Oslo ends 2026-01-01
    assert v("2025-12-31", a2)["hq_city"]["value"] == "Oslo"
    assert v("2026-03-15", a2)["hq_city"]["value"] == "Bergen"
    assert v("2026-01-01", a2)["hq_city"]["true_from"] == "2026-01-01"
    # a page no longer served keeps holding on later dates (no later version of its URL)
    assert v("2026-06-01", a6)["funding_total"]["value"] == 12000000
    assert v("2026-03-04", a6)["funding_total"]["true_from"] == "2026-03-01"
    assert v("2026-03-06", a6)["funding_total"]["true_from"] == "2026-03-05"
    assert v("2026-02-01", a6)["funding_total"]["value"] == 5000000
    # as_of before a version was gathered hides it
    assert v("2026-03-25", "2026-03-15T00:00:00+00:00")["headcount_range"]["value"] is None
    assert v("2026-03-25", a2)["headcount_range"]["value"] == "51-200"


def test_R3_VAL_03_shape_and_citations(sc):
    r = s3lib.values(sc["api"], sc["tok"], D, "2026-03-25", "2026-03-20T09:00:00+00:00")
    b = r.json()
    assert b["domain"] == D and b["true_at"] == "2026-03-25"
    assert parse_ts(b["as_of"]) == parse_ts("2026-03-20T09:00:00+00:00")
    assert list(b["fields"]) == oracle.ALL_FIELDS
    ceo = b["fields"]["ceo"]
    assert set(ceo) == {"value", "true_from", "citations"}
    assert ceo["citations"] and ceo["citations"][0]["url"] == "https://northgate-labs.test/about"
    assert set(ceo["citations"][0]) >= {"url", "excerpt", "provider"}
    assert oracle.supports(ceo["citations"][0]["excerpt"], "ceo", "Maya Ito", D)
    empty = s3lib.values(sc["api"], sc["tok"], D, "1990-01-01", T0).json()["fields"]
    assert all(f == {"value": None, "true_from": None, "citations": []} for f in empty.values())


def test_R3_VAL_04_validation_and_not_found(sc):
    api, tok = sc["api"], sc["tok"]
    assert_error(s3lib.values(api, tok, D), 422, "validation_failed")                  # true_at missing
    for bad in ("2026-3-1", "2026-02-30", "20260301", "2026-03-01T00:00:00+00:00", "today", "", "2026-13-01"):
        assert_error(s3lib.values(api, tok, D, bad), 422, "validation_failed")
    for bad in ("2026-03-15", "2026-03-15T00:00:00", "nope", ""):
        assert_error(s3lib.values(api, tok, D, "2026-03-01", bad), 422, "validation_failed")
    assert_error(s3lib.values(api, tok, "no-such-company.test", "2026-03-01"), 404, "not_found")
    assert_error(s3lib.values(api, tok, D, "2026-03-01", "2026-02-28T23:59:59+00:00"), 404, "not_found")
    assert_error(s3lib.values(api, tok, "not_a_domain", "2026-03-01"), 422, "validation_failed")
    r = s3lib.values(api, tok, "Www.Northgate-Labs.test.", "2026-03-01", T0)
    assert r.status_code == 200 and r.json()["domain"] == D


def test_R3_VAL_05_default_as_of_is_the_service_clock(sc):
    """as_of defaults to the current time (the clock reads 2026-04-10T09:00 after the script)."""
    api, tok = sc["api"], sc["tok"]
    r = s3lib.values(api, tok, D, "2026-03-25").json()
    assert parse_ts(r["as_of"]) == parse_ts("2026-04-10T09:00:00+00:00")
    assert r["fields"] == s3lib.values(api, tok, D, "2026-03-25", "2026-04-10T09:00:00+00:00").json()["fields"]
    # the clock stands still: two reads see the same time
    assert s3lib.values(api, tok, D, "2026-03-25").json()["as_of"] == r["as_of"]
