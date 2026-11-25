"""Stage 4 (API): the eighth field `investors`. Corpus companies: quillon-bio.test (six builds:
members by kind or by two origins, trap sentences, correction/change types, code-point order, a
member without a date, everything gone) and halden-labs.test (no investors at first: the first
entry is a `change`)."""
import pytest

import oracle
import s3lib
import timeline as tl
from lib import assert_dossier_shape, parse_ts

pytestmark = pytest.mark.corpus

QB = "quillon-bio.test"
HL = "halden-labs.test"
DAYS = [f"2026-03-0{d}T09:00:00+00:00" for d in range(1, 7)]
SCRIPT = [{"epoch": e, "clock": DAYS[e]} for e in range(6)]


@pytest.fixture(scope="module")
def world(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    recs = s3lib.run(api, mock, tok, QB, SCRIPT)
    builds = s3lib.to_builds(recs, QB)
    qb = dict(recs=recs, builds=builds, sim=tl.simulate(builds, QB))
    hrecs = s3lib.run(api, mock, tok, HL, [{"epoch": 0, "clock": "2026-03-10T09:00:00+00:00"},
                                           {"epoch": 1, "clock": "2026-03-11T09:00:00+00:00"}])
    hbuilds = s3lib.to_builds(hrecs, HL)
    hl = dict(recs=hrecs, builds=hbuilds, sim=tl.simulate(hbuilds, HL))
    return dict(api=api, mock=mock, tok=tok, qb=qb, hl=hl)


def inv(world, i):
    return world["qb"]["recs"][i].snap["fields"]["investors"]


def test_R4_INV_01_eighth_field_after_executives_in_every_response(world):
    api, tok = world["api"], world["tok"]
    b = world["qb"]["recs"][0].snap
    assert list(b["fields"]) == ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range",
                                 "funding_total", "executives", "investors"]
    assert_dossier_shape(b, QB)
    assert list(api.get(tok, QB).json()["fields"]) == oracle.ALL_FIELDS
    assert list(s3lib.as_of(api, tok, QB, DAYS[0]).json()["fields"]) == oracle.ALL_FIELDS
    assert list(s3lib.values(api, tok, QB, "2026-03-01", DAYS[0]).json()["fields"]) == oracle.ALL_FIELDS
    assert list(s3lib.history(api, tok, QB).json()["fields"]) == oracle.ALL_FIELDS
    for d in api.list(tok).json()["dossiers"]:       # the list is unchanged: no `fields`
        assert "fields" not in d


def test_R4_INV_02_first_build_by_hand(world):
    f = inv(world, 0)
    assert f["value"] == ["Bluebird Capital", "General Atlantic", "Northwind Ventures"]
    assert f["status"] == "known"
    assert f["true_from"] == "2026-01-20"            # the latest of the members' true_from
    assert parse_ts(f["learned_at"]) == parse_ts(DAYS[0])
    assert f["origins"] == ["bizdata.test", "dealwire.test", "quillon-bio.test"]
    assert f["corroborated"] is True and parse_ts(f["corroborated_since"]) == parse_ts(DAYS[0])
    by = {}
    for c in f["candidates"]:
        by.setdefault(c["value"], []).append(c)
    assert sorted(by) == ["Bluebird Capital", "General Atlantic", "Northwind Ventures",
                          "Orchid Partners", "Pine Equity Fund"]
    sel = {n: all(c["selected"] for c in cs) for n, cs in by.items()}
    assert sel == {"Bluebird Capital": True, "General Atlantic": True, "Northwind Ventures": True,
                   "Orchid Partners": False, "Pine Equity Fund": False}
    assert all(c["selected"] is (c["value"] in f["value"]) for c in f["candidates"])
    # citations: for each member in the order of the value, every candidate with its name, in rank order
    assert [c["url"] for c in f["citations"]] == [
        "https://quillon-bio.test/investors",                         # Bluebird Capital: own, then bizdata
        "https://bizdata.test/quillon",
        "https://dealwire.test/quillon", "https://bizdata.test/quillon",   # General Atlantic: news, aggregator
        "https://quillon-bio.test/investors", "https://bizdata.test/quillon"]   # Northwind Ventures
    assert [c["kind"] for c in f["candidates"]][:2] == ["own", "own"]            # ranked by authority first


def test_R4_INV_03_trap_sentences_and_non_names_make_no_candidate(world):
    names = {c["value"] for r in world["qb"]["recs"] if r.ready
             for c in r.snap["fields"]["investors"]["candidates"]}
    for bad in ("Zenith Capital", "Dana Ruiz", "Maple Grove", "Orion Partners", "Quillon Bio",
                "Series", "Series A"):
        assert bad not in names, bad
    # `led by` with an amount names General Atlantic, whatever the last word
    assert "General Atlantic" in names


def test_R4_INV_04_a_member_is_own_or_filing_or_has_two_origins(world):
    # build 0: Pine Equity Fund is on dealwire.test and on a copy of it (one origin): not a member
    assert "Pine Equity Fund" not in inv(world, 0)["value"]
    pine = [c for c in inv(world, 0)["candidates"] if c["value"] == "Pine Equity Fund"]
    assert len(pine) == 2 and {c["origin"] for c in pine} == {"dealwire.test"}
    assert "Orchid Partners" not in inv(world, 0)["value"]           # one aggregator
    # build 1: Harbor Partners is in a filing: a member with one origin
    assert inv(world, 1)["value"] == ["Bluebird Capital", "General Atlantic", "Harbor Partners",
                                      "Northwind Ventures"]
    # build 3: the own page is gone; Northwind and Bluebird remain candidates (bizdata) but are not members
    f3 = inv(world, 3)
    assert f3["value"] == ["Delta Fund", "General Atlantic", "Harbor Partners"]
    assert {"Northwind Ventures", "Bluebird Capital"} <= {c["value"] for c in f3["candidates"]}
    assert all(c["selected"] is False for c in f3["candidates"] if c["value"] in ("Northwind Ventures",
                                                                                  "Bluebird Capital"))


def test_R4_INV_05_value_is_sorted_by_unicode_code_point(world):
    f = inv(world, 4)
    assert f["value"] == ["Bluebird Capital", "General Atlantic", "Harbor Partners", "Kappa Holdings",
                          "Zenith Fund", "Ärlig Capital"]
    assert f["true_from"] is None                   # Kappa Holdings has no date: the field's is null
    assert f["status"] == "known"


def test_R4_INV_06_every_build_and_as_of_matches_the_oracle(world):
    sc = world["qb"]
    api, tok = world["api"], world["tok"]
    for i, r in enumerate(sc["recs"]):
        probs = s3lib.snapshot_problems(r.snap, QB, sc["recs"], i, sc["builds"], sc["sim"])
        assert not probs, f"build {i}:\n" + "\n".join(probs)
        a = s3lib.as_of(api, tok, QB, r.clock)
        probs = s3lib.snapshot_problems(a.json(), QB, sc["recs"], i, sc["builds"], sc["sim"])
        assert not probs, f"as_of build {i}:\n" + "\n".join(probs)


def test_R4_INV_07_unknown_when_nothing_qualifies(world):
    f = inv(world, 5)
    assert f["value"] is None and f["status"] == "unknown"
    assert f["citations"] == [] and f["origins"] == []
    assert f["true_from"] is None and f["learned_at"] is None
    assert f["corroborated"] is False and f["corroborated_since"] is None
    # candidates that are not members may remain (none here: every page is gone)
    assert all(c["selected"] is False for c in f["candidates"])


def test_R4_INV_08_history_types_correction_change_and_the_null_entry(world):
    api, tok = world["api"], world["tok"]
    sc = world["qb"]
    h = s3lib.history(api, tok, QB).json()
    assert not s3lib.history_problems(h, QB, sc["recs"], sc["builds"], sc["sim"])
    ents = h["fields"]["investors"]
    # build 1 adds Harbor Partners (true_from 2024-11-01 <= 2026-01-20): a correction; build 2 adds
    # Delta Fund (2023-01-10): a correction; build 3 drops two names: a change; later builds: changes
    assert [e["type"] for e in ents] == ["initial", "correction", "correction", "change", "change", "change"]
    assert ents[-1]["value"] is None and ents[-1]["true_from"] is None and ents[-1]["citations"] == []
    assert ents[0]["value"] == ["Bluebird Capital", "General Atlantic", "Northwind Ventures"]


def test_R4_INV_09_feed_entries_end_with_investors_and_use_arrays(world):
    api, tok = world["api"], world["tok"]
    sc = world["qb"]
    feed = [e for e in s3lib.all_changes(api, tok) if e["domain"] == QB]
    assert not s3lib.feed_problems(feed, QB, sc["sim"])
    inv_e = [e for e in feed if e["field"] == "investors"]
    assert [e["type"] for e in inv_e] == ["correction", "correction", "change", "change", "change"]
    assert inv_e[0]["from"] == ["Bluebird Capital", "General Atlantic", "Northwind Ventures"]
    assert inv_e[-1]["to"] is None
    # entries added by one build are numbered in field order, `investors` last
    by_time = {}
    for e in feed:
        by_time.setdefault(e["learned_at"], []).append(e)
    for es in by_time.values():
        order = [oracle.ALL_FIELDS.index(e["field"]) for e in es]
        assert order == sorted(order), es
        seqs = [e["seq"] for e in es]
        assert seqs == sorted(seqs)


def test_R4_INV_10_values_decides_membership_from_the_candidates_at_true_at(world):
    api, tok = world["api"], world["tok"]
    sc = world["qb"]
    for true_at, as_of in (("2026-03-01", DAYS[5]), ("2024-06-01", DAYS[5]), ("2024-01-01", DAYS[2]),
                           ("2026-02-15", DAYS[4]), ("2023-06-01", DAYS[5]), ("2020-01-01", DAYS[5])):
        body = s3lib.values(api, tok, QB, true_at, as_of).json()
        probs = s3lib.check_values(body, QB, sc["recs"], sc["builds"], parse_ts(as_of), true_at, as_of)
        assert not probs, (true_at, as_of, probs)
    v = s3lib.values(api, tok, QB, "2024-06-01", DAYS[5]).json()["fields"]["investors"]
    assert set(v) == {"value", "true_from", "citations"}


def test_R4_INV_11_never_contested_and_never_from_research(world):
    for r in world["qb"]["recs"]:
        assert r.snap["fields"]["investors"]["status"] in ("known", "unknown")
        for e in r.segment:
            if e.get("method") == "research":
                assert set(e.get("fields") or []) <= set(oracle.FIELDS), e   # asks the six fields only
    # the funding claim's sentence is not an investor candidate by itself (only names are)
    for r in world["qb"]["recs"]:
        for c in r.snap["fields"]["investors"]["candidates"]:
            assert c["value"] and c["value"] == c["value"].strip()


def test_R4_INV_12_first_value_after_a_build_without_one_is_a_change(world):
    sc = world["hl"]
    api, tok = world["api"], world["tok"]
    assert sc["recs"][0].snap["fields"]["investors"]["value"] is None
    f = sc["recs"][1].snap["fields"]["investors"]
    assert f["value"] == ["Birch Partners", "Fjord Capital"] and f["true_from"] == "2025-02-01"
    h = s3lib.history(api, tok, HL).json()["fields"]["investors"]
    assert [e["type"] for e in h] == ["change"]               # unknown after the first build: first entry is a change
    feed = [e for e in s3lib.all_changes(api, tok) if e["domain"] == HL]
    assert [(e["field"], e["type"], e["from"]) for e in feed] == [("investors", "change", None)]
    for i in (0, 1):
        probs = s3lib.snapshot_problems(sc["recs"][i].snap, HL, sc["recs"], i, sc["builds"], sc["sim"])
        assert not probs, probs
    assert not s3lib.history_problems(s3lib.history(api, tok, HL).json(), HL, sc["recs"], sc["builds"], sc["sim"])
