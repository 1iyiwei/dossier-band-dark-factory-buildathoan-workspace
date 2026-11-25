"""Stage 3 (API): the seventh field `executives`. Scripted companies (corpus_spec.py):
cobalt-assembly.test (three titles, contested/known, every history type, a null true_from) and
harrow-guild.test (executives through /values), plus talloway-systems.test (no executives).
"""
import pytest

import oracle
import s3lib
import timeline as tl
from lib import T0, assert_dossier_shape, assert_error, parse_ts

pytestmark = pytest.mark.corpus

CB = "cobalt-assembly.test"
HG = "harrow-guild.test"
NONE_CO = "talloway-systems.test"
CB_SCRIPT = [{"epoch": e, "clock": f"2026-03-0{e + 1}T09:00:00+00:00"} for e in range(6)]
HG_SCRIPT = [{"epoch": 0, "clock": "2026-03-10T09:00:00+00:00"},
             {"epoch": 1, "clock": "2026-03-20T09:00:00+00:00"},
             {"epoch": 2, "clock": "2026-03-30T09:00:00+00:00"}]
SIX = sorted(oracle.FIELDS)


def sc_for(api, mock, tok, domain, script):
    recs = s3lib.run(api, mock, tok, domain, script)
    builds = s3lib.to_builds(recs, domain)
    return dict(recs=recs, builds=builds, sim=tl.simulate(builds, domain), domain=domain)


@pytest.fixture(scope="module")
def world(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    cb = sc_for(api, mock, tok, CB, CB_SCRIPT)
    hg = sc_for(api, mock, tok, HG, HG_SCRIPT)
    mock.epoch(0)
    api.clock("2026-04-05T09:00:00+00:00")
    nn = s3lib.run(api, mock, tok, NONE_CO, [{"epoch": 0, "clock": "2026-04-05T09:00:00+00:00"}])
    return dict(api=api, mock=mock, tok=tok, cb=cb, hg=hg, none=nn)


def names(fv):
    return [(m["title"], m["name"]) for m in fv["value"]]


# ------------------------------------------------------------------ shape
def test_R3_EXE_01_seventh_field_after_the_six(world):
    b = world["cb"]["recs"][0].snap
    assert list(b["fields"]) == ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range",
                                 "funding_total", "executives", "investors"]   # stage 4: an eighth field
    assert_dossier_shape(b, CB)
    h = s3lib.history(world["api"], world["tok"], CB).json()
    assert list(h["fields"]) == oracle.ALL_FIELDS
    v = s3lib.values(world["api"], world["tok"], CB, "2026-03-01", "2026-03-01T09:00:00+00:00").json()
    assert list(v["fields"]) == oracle.ALL_FIELDS
    a = s3lib.as_of(world["api"], world["tok"], CB, "2026-03-01T09:00:00+00:00").json()
    assert list(a["fields"]) == oracle.ALL_FIELDS
    assert list(world["api"].get(world["tok"], CB).json()["fields"]) == oracle.ALL_FIELDS


def test_R3_EXE_02_by_hand_first_build(world):
    """By hand (epoch 0): cfo Ana Silva (own + aggregator), coo Pia Lindqvist (own beats the
    aggregator's Pia Lindgren), cto Rui Santos (news beats the aggregator's Ben Okafor)."""
    ex = world["cb"]["recs"][0].snap["fields"]["executives"]
    assert ex["value"] == [{"title": "cfo", "name": "Ana Silva"},
                           {"title": "coo", "name": "Pia Lindqvist"},
                           {"title": "cto", "name": "Rui Santos"}]
    assert ex["status"] == "contested"
    assert ex["true_from"] == "2026-01-15"            # latest of 2025-09-01, 2024-01-01, 2026-01-15
    assert parse_ts(ex["learned_at"]) == parse_ts(T0)
    cands = ex["candidates"]
    assert [(c["title"], c["value"], c["selected"]) for c in cands] == [
        ("cfo", "Ana Silva", True), ("cfo", "Ana Silva", False),
        ("coo", "Pia Lindqvist", True), ("coo", "Pia Lindgren", False),
        ("cto", "Rui Santos", True), ("cto", "Ben Okafor", False)]
    assert [c["url"] for c in cands] == [
        "https://cobalt-assembly.test/cfo", "https://bizdata.test/cobalt-assembly",
        "https://cobalt-assembly.test/coo", "https://bizdata.test/cobalt-assembly",
        "https://news-ledger.test/cobalt-cto", "https://bizdata.test/cobalt-assembly"]
    assert [c["kind"] for c in cands] == ["own", "aggregator", "own", "aggregator", "news", "aggregator"]
    assert [c["true_from"] for c in cands] == ["2025-09-01", "2026-02-20", "2024-01-01", "2026-02-20",
                                               "2026-01-15", "2026-02-20"]
    # citations: for each member in order, every candidate with that title and name, rank order
    assert [c["url"] for c in ex["citations"]] == [
        "https://cobalt-assembly.test/cfo", "https://bizdata.test/cobalt-assembly",
        "https://cobalt-assembly.test/coo", "https://news-ledger.test/cobalt-cto"]
    assert all(set(c) >= {"url", "excerpt", "provider"} for c in ex["citations"])
    assert ex["citations"][0]["excerpt"] == "Ana Silva is the chief financial officer of Cobalt Assembly."
    assert ex["candidates"][5]["excerpt"] == "Cobalt Assembly CTO: Ben Okafor."
    for f in oracle.FIELDS:
        assert world["cb"]["recs"][0].snap["fields"][f]["status"] == "unknown"


def test_R3_EXE_03_every_build_matches_the_oracle(world):
    for dom in ("cb", "hg"):
        w = world[dom]
        for i, r in enumerate(w["recs"]):
            assert_dossier_shape(r.snap, w["domain"])
            probs = s3lib.snapshot_problems(r.snap, w["domain"], w["recs"], i, w["builds"], w["sim"])
            assert not probs, f"{w['domain']} build {i}:\n" + "\n".join(probs)


def test_R3_EXE_04_by_hand_members_status_and_true_from_per_epoch(world):
    f = [r.snap["fields"]["executives"] for r in world["cb"]["recs"]]
    assert names(f[0]) == [("cfo", "Ana Silva"), ("coo", "Pia Lindqvist"), ("cto", "Rui Santos")]
    assert names(f[1]) == [("cfo", "Ana Silva"), ("coo", "Pia Lindqvist"), ("cto", "Ben Okafor")]
    assert names(f[2]) == [("cfo", "Ana Silva"), ("cto", "Ben Okoro")]            # no coo
    assert names(f[3]) == [("cfo", "Ana Silva"), ("cto", "Ben Okeke")]
    assert names(f[4]) == [("cfo", "Ana Silva"), ("coo", "Pia Lindqvist"), ("cto", "Ben Okeke")]
    assert names(f[5]) == [("cfo", "Cora Dahl"), ("coo", "Pia Lindqvist"), ("cto", "Ben Okuda")]
    assert [x["status"] for x in f] == ["contested", "contested", "contested", "known", "known", "contested"]
    # field true_from: latest of the members'; null when any member's is null
    assert [x["true_from"] for x in f] == ["2026-01-15", "2026-03-01", "2026-02-10", "2026-02-01", None, None]
    # known: every title's candidates agree (epoch 3: cfo own+aggregator, cto news only)
    assert {c["title"] for c in f[3]["candidates"]} == {"cfo", "cto"}
    assert len(f[3]["candidates"]) == 3
    # learned_at of the field: build that made the array the selected value
    assert [parse_ts(x["learned_at"]) for x in f] == [parse_ts(f"2026-03-0{i + 1}T09:00:00+00:00") for i in range(6)]


def test_R3_EXE_05_sentences_that_name_no_one_person_make_no_candidate(world):
    """The /press page holds a sentence with two names (CFO and CTO), a negated one (former) and a
    hedged one (reportedly); none of them is a candidate of any title."""
    for r in world["cb"]["recs"]:
        urls = {c["url"] for c in r.snap["fields"]["executives"]["candidates"]}
        assert "https://cobalt-assembly.test/press" not in urls
        vals = {c["value"] for c in r.snap["fields"]["executives"]["candidates"]}
        assert not vals & {"Tom Berg", "Uma Rask"}


def test_R3_EXE_06_history_types_by_title(world):
    """By hand: epoch 1 cto later true_from -> change; epoch 2 coo disappears (+ a cto correction)
    -> change; epoch 3 only cto differs and is a correction -> correction; epoch 4 coo appears ->
    change; epoch 5 cfo changes on a later date and cto is a correction -> change."""
    h = s3lib.history(world["api"], world["tok"], CB).json()["fields"]
    assert [e["type"] for e in h["executives"]] == ["initial", "change", "change", "correction",
                                                    "change", "change"]
    assert [e["true_from"] for e in h["executives"]] == [
        "2026-01-15", "2026-03-01", "2026-02-10", "2026-02-01", None, None]
    assert [parse_ts(e["learned_at"]) for e in h["executives"]] == [
        parse_ts(f"2026-03-0{i + 1}T09:00:00+00:00") for i in range(6)]
    assert h["executives"][3]["value"] == [{"title": "cfo", "name": "Ana Silva"},
                                           {"title": "cto", "name": "Ben Okeke"}]
    assert [c["url"] for c in h["executives"][0]["citations"]] == [
        "https://cobalt-assembly.test/cfo", "https://bizdata.test/cobalt-assembly",
        "https://cobalt-assembly.test/coo", "https://news-ledger.test/cobalt-cto"]
    for f in oracle.FIELDS:
        assert h[f] == [], f                                      # a field with no value: empty list
    probs = s3lib.history_problems(
        s3lib.history(world["api"], world["tok"], CB).json(), CB, world["cb"]["recs"],
        world["cb"]["builds"], world["cb"]["sim"])
    assert not probs, "\n".join(probs)


def test_R3_EXE_07_feed_entries_for_executives(world):
    feed = [e for e in s3lib.all_changes(world["api"], world["tok"]) if e["domain"] == CB]
    assert [e["type"] for e in feed] == ["change", "change", "correction", "change", "change"]
    assert all(e["field"] == "executives" for e in feed)
    assert feed[0]["from"] == [{"title": "cfo", "name": "Ana Silva"}, {"title": "coo", "name": "Pia Lindqvist"},
                               {"title": "cto", "name": "Rui Santos"}]
    assert feed[0]["to"][2] == {"title": "cto", "name": "Ben Okafor"} and feed[0]["true_from"] == "2026-03-01"
    assert feed[1]["to"] == [{"title": "cfo", "name": "Ana Silva"}, {"title": "cto", "name": "Ben Okoro"}]
    assert feed[3]["from"] == [{"title": "cfo", "name": "Ana Silva"}, {"title": "cto", "name": "Ben Okeke"}]
    assert feed[3]["true_from"] is None                    # the member that appeared has no date
    assert parse_ts(feed[2]["learned_at"]) == parse_ts("2026-03-04T09:00:00+00:00")
    probs = s3lib.feed_problems(feed, CB, world["cb"]["sim"])
    assert not probs, "\n".join(probs)


def test_R3_EXE_08_research_asks_for_the_six_fields_only(world):
    for key in ("cb", "hg"):
        for r in world[key]["recs"]:
            runs = [e for e in r.segment if e.get("method") == "research"]
            for e in runs:
                assert sorted(e["fields"] or []) == SIX, e["fields"]


def test_R3_EXE_09_no_statement_means_unknown(world):
    b = world["none"][0].snap
    ex = b["fields"]["executives"]
    assert ex == {"value": None, "status": "unknown", "true_from": None, "learned_at": None,
                  "citations": [], "candidates": [], "origins": [], "corroborated": False,
                  "corroborated_since": None} or (
        ex["value"] is None and ex["status"] == "unknown" and ex["citations"] == []
        and ex["candidates"] == [] and ex["true_from"] is None and ex["learned_at"] is None)
    assert b["fields"]["ceo"]["value"] == "Mara Quintero"        # other fields unaffected
    h = s3lib.history(world["api"], world["tok"], NONE_CO).json()["fields"]
    assert h["executives"] == [] and h["ceo"][0]["type"] == "initial"
    v = s3lib.values(world["api"], world["tok"], NONE_CO, "2026-04-01").json()["fields"]["executives"]
    assert v == {"value": None, "true_from": None, "citations": []}
    assert not [e for e in s3lib.all_changes(world["api"], world["tok"]) if e["domain"] == NONE_CO]


# ------------------------------------------------------------------ as_of and /values on executives
def test_R3_EXE_10_as_of_snapshots(world):
    for key in ("cb", "hg"):
        w = world[key]
        for r in w["recs"]:
            got = s3lib.as_of(world["api"], world["tok"], w["domain"], r.clock)
            assert got.status_code == 200
            assert got.json() == r.snap, (w["domain"], r.clock)
    mid = s3lib.as_of(world["api"], world["tok"], CB, "2026-03-04T12:00:00+00:00").json()
    assert names(mid["fields"]["executives"]) == [("cfo", "Ana Silva"), ("cto", "Ben Okeke")]


HG_TRUE_AT = ["2021-12-31", "2022-03-01", "2022-06-01", "2026-03-11", "2026-03-12", "2026-04-01"]
HG_AS_OF = ["2026-03-10T09:00:00+00:00", "2026-03-20T09:00:00+00:00", "2026-03-30T09:00:00+00:00"]


@pytest.mark.parametrize("as_of_ts", HG_AS_OF)
def test_R3_EXE_11_values_for_executives_harrow(world, as_of_ts):
    w = world["hg"]
    probs = []
    for ta in HG_TRUE_AT:
        r = s3lib.values(world["api"], world["tok"], HG, ta, as_of_ts)
        assert r.status_code == 200, r.text
        probs += [f"true_at {ta}: {p}" for p in s3lib.check_values(
            r.json(), HG, w["recs"], w["builds"], parse_ts(as_of_ts), ta, as_of_ts)]
    assert not probs, "\n".join(probs)


def test_R3_EXE_12_by_hand_values_for_executives(world):
    v = lambda ta, ao: s3lib.values(world["api"], world["tok"], HG, ta, ao).json()["fields"]["executives"]
    ao = "2026-03-30T09:00:00+00:00"
    # versions of /leaders: build 0 (2022-03-01) ends where build 1 starts (2026-03-12); build 2
    # (also 2026-03-12) replaces build 1 (true_from on or after its own)
    e = v("2022-06-01", ao)
    assert e["value"] == [{"title": "cfo", "name": "Ines Moreau"}, {"title": "cto", "name": "Joel Brandt"}]
    assert e["true_from"] == "2022-03-01"
    assert [c["url"] for c in e["citations"]] == ["https://harrow-guild.test/leaders"] * 2
    e = v("2026-03-12", ao)
    assert e["value"] == [{"title": "cfo", "name": "Ines Moreau"}, {"title": "coo", "name": "Lena Voss"},
                          {"title": "cto", "name": "Kai Larsen"}]
    assert e["true_from"] == "2026-03-12"
    assert v("2021-12-31", ao) == {"value": None, "true_from": None, "citations": []}
    # as of the second build the coo does not exist yet
    e = v("2026-03-15", "2026-03-20T09:00:00+00:00")
    assert [m["title"] for m in e["value"]] == ["cfo", "cto"] and e["value"][1]["name"] == "Kai Larsen"
    # the unrelated page (founded 1999) answers its own field at its own date
    f = s3lib.values(world["api"], world["tok"], HG, "1999-06-01", ao).json()["fields"]
    assert f["founded_year"]["value"] == 1999 and f["founded_year"]["true_from"] == "1999-06-01"
    assert f["executives"]["value"] is None
