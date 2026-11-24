"""Offline self-check of the stage-3 oracle (timeline.py) against hand-written expectations taken
from the specification text. No service needed:  python -m pytest test_timeline_unit.py
"""
from datetime import datetime, timezone

import pytest

import oracle
import rank
import timeline as tl

NG = "northgate-labs.test"
CB = "cobalt-assembly.test"
HG = "harrow-guild.test"


def t(day):  # 2026-MM-DD at 09:00Z
    return datetime.fromisoformat(f"{day}T09:00:00+00:00")


def run(domain, epochs_days):
    builds = [tl.Build(t(d), e) for e, d in epochs_days]
    return builds, tl.simulate(builds, domain)


NG_BUILDS = [(0, "2026-03-01"), (1, "2026-03-10"), (2, "2026-03-20"), (3, "2026-04-01"),
             (4, "2026-04-10")]
CB_BUILDS = [(e, f"2026-03-{e + 1:02d}") for e in range(6)]


def test_page_true_from_rules():
    p = {"true_from": "2026-03-01", "published_at": "2026-01-01T00:00:00Z"}
    assert tl.page_true_from(p) == "2026-03-01"
    assert tl.page_true_from({"true_from": "2026-13-45",
                              "published_at": "2026-04-02T23:30:00-05:00"}) == "2026-04-03"
    assert tl.page_true_from({"true_from": "2026-02-30", "published_at": "2026-04-02T00:00:00Z"}) == "2026-04-02"
    assert tl.page_true_from({"true_from": "March 3", "published_at": None}) is None
    assert tl.page_true_from({"true_from": None, "published_at": "2026-04-02"}) is None   # not RFC 3339
    assert tl.page_true_from({"true_from": "2026-04-02T00:00:00Z", "published_at": None}) is None


def test_northgate_selected_values_per_epoch():
    v = {e: tl.exp_fields(NG, e) for e in range(5)}
    assert [v[e]["ceo"]["value"] for e in range(5)] == [
        "Dana Ruiz", "Lee Park", "Maya Ito", "Nora Voss", "Paul Quist"]
    assert [v[e]["ceo"]["true_from"] for e in range(5)] == [
        "2021-04-01", "2026-03-20", "2026-02-01", "2026-04-03", None]
    assert [v[e]["funding_total"]["value"] for e in range(5)] == [5000000, 12000000, 12000000, None, None]
    assert [v[e]["hq_city"]["value"] for e in range(5)] == ["Oslo", None, "Bergen", "Bergen", "Bergen"]
    assert [v[e]["founded_year"]["value"] for e in range(5)] == [2012, 2012, None, None, None]
    assert v[0]["legal_name"]["value"] == "Northgate Labs AS"
    assert [v[e]["headcount_range"]["value"] for e in range(5)] == [None, None, "51-200", "51-200", "51-200"]
    assert v[0]["executives"]["value"] == [{"title": "cfo", "name": "Ana Silva"}]
    assert v[0]["executives"]["true_from"] == "2018-05-05"


def test_northgate_history_and_feed():
    builds, sim = run(NG, NG_BUILDS)
    types = {f: [h["type"] for h in sim.history[f]] for f in oracle.ALL_FIELDS}
    assert types["ceo"] == ["initial", "change", "correction", "change", "change"]
    assert types["founded_year"] == ["initial", "change"]            # e1 same value: nothing
    assert types["funding_total"] == ["initial", "change", "change"]  # e2 same value: nothing; e3 null
    assert types["hq_city"] == ["initial", "change", "change"]
    assert types["legal_name"] == ["initial"] and types["executives"] == ["initial"]
    assert types["headcount_range"] == ["change"]       # unknown at the first build: first entry is a change
    assert [(e["field"], e["type"]) for e in sim.feed] == [
        ("hq_city", "change"), ("ceo", "change"), ("funding_total", "change"),         # e1
        ("hq_city", "change"), ("ceo", "correction"), ("founded_year", "change"),      # e2
        ("headcount_range", "change"),
        ("ceo", "change"), ("funding_total", "change"),                                # e3
        ("ceo", "change")]                                                             # e4
    last = sim.history["funding_total"][-1]
    assert last["value"] is None and last["true_from"] is None and last["cit"] == []
    ceo = sim.history["ceo"]
    assert [h["learned_at"] for h in ceo] == [t("2026-03-01"), t("2026-03-10"), t("2026-03-20"),
                                              t("2026-04-01"), t("2026-04-10")]
    # field learned_at after each build; unknown -> None; same value keeps the first time
    assert sim.state_after[2]["funding_total"] == dict(value=12000000, true_from="2026-03-05",
                                                       learned_at=t("2026-03-10"))
    assert sim.state_after[3]["funding_total"]["learned_at"] is None
    assert sim.state_after[4]["legal_name"]["learned_at"] == t("2026-03-01")


def test_cobalt_executives():
    f = {e: tl.exp_fields(CB, e)["executives"] for e in range(6)}
    names = lambda e: [(m["title"], m["name"]) for m in f[e]["value"]]
    assert names(0) == [("cfo", "Ana Silva"), ("coo", "Pia Lindqvist"), ("cto", "Rui Santos")]
    assert names(1)[2] == ("cto", "Ben Okafor")
    assert names(2) == [("cfo", "Ana Silva"), ("cto", "Ben Okoro")]
    assert names(3) == [("cfo", "Ana Silva"), ("cto", "Ben Okeke")]
    assert names(4) == [("cfo", "Ana Silva"), ("coo", "Pia Lindqvist"), ("cto", "Ben Okeke")]
    assert names(5) == [("cfo", "Cora Dahl"), ("coo", "Pia Lindqvist"), ("cto", "Ben Okuda")]
    assert [f[e]["status"] for e in range(6)] == [
        "contested", "contested", "contested", "known", "known", "contested"]
    assert [f[e]["true_from"] for e in range(6)] == [
        "2026-01-15", "2026-03-01", "2026-02-10", "2026-02-01", None, None]
    # candidates by title then rank; the trap sentences make no candidate
    assert [(c.title, c.value, c.url) for c in f[0]["candidates"]] == [
        ("cfo", "Ana Silva", "https://cobalt-assembly.test/cfo"),
        ("cfo", "Ana Silva", "https://bizdata.test/cobalt-assembly"),
        ("coo", "Pia Lindqvist", "https://cobalt-assembly.test/coo"),
        ("coo", "Pia Lindgren", "https://bizdata.test/cobalt-assembly"),
        ("cto", "Rui Santos", "https://news-ledger.test/cobalt-cto"),
        ("cto", "Ben Okafor", "https://bizdata.test/cobalt-assembly")]
    assert [(c.url) for c in f[0]["cit"]] == [
        "https://cobalt-assembly.test/cfo", "https://bizdata.test/cobalt-assembly",
        "https://cobalt-assembly.test/coo", "https://news-ledger.test/cobalt-cto"]


def test_cobalt_history_types():
    builds, sim = run(CB, CB_BUILDS)
    assert [h["type"] for h in sim.history["executives"]] == [
        "initial", "change", "change", "correction", "change", "change"]
    assert [e["field"] for e in sim.feed] == ["executives"] * 5
    assert sim.feed[0]["from"] == [{"title": "cfo", "name": "Ana Silva"},
                                   {"title": "coo", "name": "Pia Lindqvist"},
                                   {"title": "cto", "name": "Rui Santos"}]
    assert sim.feed[0]["true_from"] == "2026-03-01"
    # the six fields are unknown throughout
    assert all(sim.history[f] == [] for f in oracle.FIELDS)


def test_values_northgate_page_versions():
    builds, _ = run(NG, NG_BUILDS)
    for b in builds:
        b.prepare(NG)
    v = lambda as_of_day, true_at, field: tl.values_at(builds, NG, t(as_of_day), true_at)[field]
    # as of the 3rd build (correction): versions of /about: Dana [2021-04-01, 2026-02-01),
    # Lee replaced by Maya (2026-03-20 >= 2026-02-01), Maya holds from 2026-02-01
    assert v("2026-03-20", "2025-06-01", "ceo")["value"] == "Dana Ruiz"
    assert v("2026-03-20", "2026-02-15", "ceo")["value"] == "Maya Ito"
    assert v("2026-03-20", "2026-03-25", "ceo")["value"] == "Maya Ito"
    assert v("2026-03-20", "2021-03-31", "ceo")["value"] is None
    assert v("2026-03-20", "2026-02-15", "ceo")["true_from"] == "2026-02-01"
    # as of the 2nd build (before the correction): Lee holds from 2026-03-20
    assert v("2026-03-10", "2026-03-25", "ceo")["value"] == "Lee Park"
    assert v("2026-03-10", "2026-03-19", "ceo")["value"] == "Dana Ruiz"
    # 4th build: Maya ends where Nora starts (2026-04-03)
    assert v("2026-04-01", "2026-04-02", "ceo")["value"] == "Maya Ito"
    assert v("2026-04-01", "2026-04-03", "ceo")["value"] == "Nora Voss"
    # 5th build has a null true_from: replaces every earlier version of the URL, holds never
    for d in ("2021-05-01", "2026-02-15", "2026-04-03", "2030-01-01"):
        assert v("2026-04-10", d, "ceo") == dict(value=None, true_from=None, cit_urls=[])
    # a version with no candidates ends the earlier hq version (2026-03-10) ...
    assert v("2026-03-10", "2026-03-09", "hq_city")["value"] == "Oslo"
    assert v("2026-03-10", "2026-03-10", "hq_city")["value"] is None
    # ... and a later version replaces the empty one (2026-03-10 >= 2026-01-01) and ends Oslo
    assert v("2026-03-20", "2025-06-01", "hq_city")["value"] == "Oslo"
    assert v("2026-03-20", "2026-03-15", "hq_city")["value"] == "Bergen"
    # earlier than every build: no build
    assert tl.values_at(builds, NG, t("2026-02-28"), "2026-01-01") is None
    # funding: removed page keeps holding (no later version of the URL)
    assert v("2026-04-10", "2026-06-01", "funding_total")["value"] == 12000000
    assert v("2026-04-10", "2026-03-04", "funding_total")["value"] == 12000000
    assert v("2026-04-10", "2026-03-04", "funding_total")["true_from"] == "2026-03-01"
    assert v("2026-04-10", "2026-03-06", "funding_total")["true_from"] == "2026-03-05"


def test_values_executives_harrow():
    builds, _ = run(HG, [(0, "2026-03-01"), (1, "2026-03-10"), (2, "2026-03-20")])
    ex = lambda true_at: tl.values_at(builds, HG, t("2026-03-20"), true_at)["executives"]
    assert ex("2022-06-01")["value"] == [{"title": "cfo", "name": "Ines Moreau"},
                                         {"title": "cto", "name": "Joel Brandt"}]
    assert ex("2022-06-01")["true_from"] == "2022-03-01"
    assert [x["name"] for x in ex("2026-03-12")["value"]] == ["Ines Moreau", "Lena Voss", "Kai Larsen"]
    assert ex("2021-01-01") == dict(value=None, true_from=None, cit_urls=[])


def test_as_of_index_ties_and_offsets():
    a = datetime.fromisoformat("2026-03-01T09:00:00+00:00")
    b = datetime.fromisoformat("2026-03-01T10:00:00+01:00")      # same instant
    c = datetime.fromisoformat("2026-03-02T09:00:00+00:00")
    builds = [tl.Build(a, 0), tl.Build(b, 1), tl.Build(c, 0, ready=False)]
    assert tl.as_of_index(builds, a) == 1
    assert tl.as_of_index(builds, c) == 1
    assert tl.as_of_index(builds, a.replace(hour=8)) is None
