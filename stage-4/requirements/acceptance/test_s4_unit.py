"""Offline self-check of the stage-4 oracle (investors in oracle.py, registrant/kind in rank.py,
origins in lineage.py, members/corroboration in timeline.py) against expectations written by hand
from stage-4.md. No service needed:  python -m pytest test_s4_unit.py

Ledger rows: R4-INV-*, R4-ORG-*, R4-OWN-*, R4-COR-* (the oracle that the service tests rely on)."""
from datetime import datetime

import lineage
import oracle
import rank
import timeline as tl
from corpus_spec import COMPANIES

D = "acme-robotics.test"


def t(day):
    return datetime.fromisoformat(f"2026-03-{day:02d}T09:00:00+00:00")


# ------------------------------------------------------------------------------ investors (A.2 + stage 4)
def test_investor_names_spec_examples():
    assert oracle.supported_investors(
        "Acme Robotics raised $40M in a round led by General Atlantic.", D) == ["General Atlantic"]
    assert oracle.supported_investors("Acme Robotics is led by Dana Ruiz.", D) == []
    # no amount: the `led by` exception does not apply, and General Atlantic has no suffix word
    assert oracle.supported_investors("Acme Robotics is led by General Atlantic.", D) == []
    assert oracle.supported_investors(
        "Northwind Ventures and Bluebird Capital are investors in Acme Robotics.", D) == [
        "Northwind Ventures", "Bluebird Capital"]


def test_investor_runs_are_separated_by_the_company_name_and_phrases():
    # a suffix word alone is not a name; two words are
    assert oracle.supported_investors("Acme Robotics investors include Capital.", D) == []
    # the company's name separates words: `Robotics Capital` is not a run starting in the company name
    assert oracle.supported_investors("Acme Robotics Capital investors are listed.", D) == []
    # a longer run is one name, not part of a shorter one
    assert oracle.supported_investors(
        "Pine Equity Fund is an investor in Acme Robotics.", D) == ["Pine Equity Fund"]
    # `led by` with an amount: a run of any length and last word, nothing else
    assert oracle.supported_investors(                      # one word is enough after `led by`; Hale Group is not
        "Acme Robotics raised $5M in a seed round led by Soto and Hale Group.", D) == ["Soto"]
    assert oracle.supported_investors(
        "Acme Robotics raised $5M in a seed round led by Maple Grove and backed by Orchid Partners.",
        D) == ["Maple Grove", "Orchid Partners"]


def test_investor_rules_1_to_4_of_a2():
    assert oracle.supported_investors("Acme Robotics is reportedly backed by Zenith Capital.", D) == []
    assert oracle.supported_investors("Zenith Capital participated in a round.", D) == []   # no company
    assert oracle.supported_investors(
        "Zenith Capital participated. Acme Robotics is happy.", D) == []                     # two sentences
    assert oracle.supported_investors("Acme Robotics welcomed Zenith Capital.", D) == []     # no phrase
    assert oracle.supported_investors("Ärlig Capital participated in the round at Acme Robotics.",
                                      D) == ["Ärlig Capital"]


# ------------------------------------------------------------------------------ kind, registrant
def test_registrant_normalisation_and_fallback():
    p = {"url": "https://Blog.Example.test/x", "lineage": {"registrant": "WWW.Linden-Forge.TEST."}}
    assert rank.registrant_of(p) == "linden-forge.test"
    for bad in ("not a domain!", "", None, "-x-.test", "nolabels", "a..test"):
        p = {"url": "https://blog.example.test/x", "lineage": {"registrant": bad}}
        assert rank.registrant_of(p) == "blog.example.test", bad


def test_own_needs_the_registrant_and_lookalikes():
    d = "linden-forge.test"
    pages = {p["url"]: p for p in COMPANIES[d]["pages"]}
    k = lambda u: rank.kind_of(pages[u], d)
    assert k("https://linden-forge.test/about") == "own"
    assert k("https://linden-forge.test/press") == "own"                      # registrant normalises
    assert k("https://linden-forge.test/careers") == "own"                    # invalid registrant: host
    assert k("https://linden-forge-official.test/about") == "aggregator"      # lookalike
    assert k("https://blog.linden-forge.test/post") == "aggregator"           # not a lookalike
    assert k("https://linden-forge.test/legal") == "aggregator"               # RUL-S4-02
    assert k("https://registry.test/linden") == "filing"
    assert rank.is_lookalike(pages["https://linden-forge-official.test/about"])
    assert not rank.is_lookalike(pages["https://blog.linden-forge.test/post"])
    assert not rank.is_lookalike(pages["https://linden-forge.test/press"])


# ------------------------------------------------------------------------------ origins
def test_origins_of_the_linden_forge_pages():
    d = "linden-forge.test"
    o = {c.url: c.origin for cs in tl.exp_candidates(d, 0).values() for c in cs}
    assert o["https://linden-forge.test/about"] == "linden-forge.test"
    assert o["https://linden-forge-official.test/about"] == "linden-forge.test"    # lookalike: rule 3
    assert o["https://blog.linden-forge.test/post"] == "blog.linden-forge.test"
    assert o["https://linden-forge.test/legal"] == "registry-corp.test"
    assert o["https://linden-forge-info.test/x"] == "press-wire.test"              # rule 1 over rule 3
    assert o["https://linden-forge-copy.test/hq"] == "wire-hub.test"               # rule 2 over rule 3
    assert o["https://copycat.test/linden"] == "linden-forge.test"                 # original is a lookalike
    f = tl.exp_fields(d, 0)
    assert [c.value for c in f["hq_city"]["candidates"]] == ["Graz", "Graz"]       # Vienna: no evidence
    assert f["hq_city"]["origins"] == ["linden-forge.test", "wire-hub.test"] and f["hq_city"]["corroborated"]
    assert f["ceo"]["value"] == "Hana Weiss" and f["ceo"]["status"] == "contested"
    assert f["ceo"]["origins"] == ["linden-forge.test"] and not f["ceo"]["corroborated"]
    assert f["founded_year"]["origins"] == ["blog.linden-forge.test", "linden-forge.test", "registry.test"]
    assert f["headcount_range"]["origins"] == ["linden-forge.test", "press-wire.test"]


def test_origins_of_the_ravenmoor_chain_cycle_and_missing_original():
    d = "ravenmoor-energy.test"
    o = {c.url: c.origin for cs in tl.exp_candidates(d, 0).values() for c in cs}
    assert o["https://c0.test/rm"] == "archive.test"          # the fourth Canonical is not followed
    for u in ("https://c1.test/rm", "https://c2.test/rm", "https://c3.test/rm"):
        assert o[u] == "pressroom.test", u                   # three follows reach archive.test's registrant
    assert o["https://m-copy.test/rm"] == "nowhere-host.test"
    assert o["https://cyc-a.test/rm"] == "cyc-a.test" and o["https://cyc-b.test/rm"] == "cyc-b.test"
    assert o["https://r-self.test/rm"] == "r-self.test"
    assert o["https://s-copy.test/rm"] == "first-wire.test"   # rule 1 before rule 2
    f = tl.exp_fields(d, 0)
    assert f["founded_year"]["value"] == 2003                 # archive.test's 1999 is not evidence
    assert f["founded_year"]["origins"] == ["archive.test", "pressroom.test", "ravenmoor-energy.test"]
    assert lineage.originals_needed(COMPANIES[d]["pages"][1], 0) == [
        "https://c1.test/rm", "https://c2.test/rm", "https://c3.test/rm"]


# ------------------------------------------------------------------------------ investors members
def test_quillon_members_values_and_types():
    d = "quillon-bio.test"
    f = tl.exp_fields(d, 0)["investors"]
    assert f["value"] == ["Bluebird Capital", "General Atlantic", "Northwind Ventures"]
    assert f["status"] == "known" and f["true_from"] == "2026-01-20"
    assert f["origins"] == ["bizdata.test", "dealwire.test", "quillon-bio.test"] and f["corroborated"]
    names = [c.value for c in f["candidates"]]
    assert "Pine Equity Fund" in names and "Orchid Partners" in names           # candidates, not members
    assert not any(n in names for n in ("Zenith Capital", "Dana Ruiz", "Maple Grove", "Orion Partners"))
    assert [c.value for c, s in zip(f["candidates"], f["selected"]) if s] == [
        c.value for c in f["candidates"] if c.value in f["value"]]
    assert [c.value for c in f["cit"]][:1] == ["Bluebird Capital"] or f["cit"]
    builds = [tl.Build(t(i + 1), i) for i in range(6)]
    sim = tl.simulate(builds, d)
    assert [h["type"] for h in sim.history["investors"]] == [
        "initial", "correction", "correction", "change", "change", "change"]
    assert [h["value"] for h in sim.history["investors"]][4] == [
        "Bluebird Capital", "General Atlantic", "Harbor Partners", "Kappa Holdings", "Zenith Fund",
        "Ärlig Capital"]                                                        # code point order
    assert sim.history["investors"][4]["true_from"] is None                     # Kappa Holdings: no date
    assert sim.history["investors"][5]["value"] is None
    assert [e["field"] for e in sim.feed if e["field"] == "investors"] == ["investors"] * 5


# ------------------------------------------------------------------------------ corroborated_since
def test_corroborated_since_standing_origins_for_a_value():
    builds = [tl.Build(t(i + 1), i) for i in range(7)]
    sim = tl.simulate(builds, "corvane-systems.test")
    ceo = [(s["ceo"]["value"], s["ceo"]["origins"], s["ceo"]["corroborated"], s["ceo"]["since"])
           for s in sim.state_after]
    assert [c[3] for c in ceo] == [t(1), t(1), None, t(4), t(4), None, t(7)]
    assert [c[2] for c in ceo] == [True, False, False, True, False, False, True]
    assert ceo[0][1] == ["corvane-systems.test", "daily-ledger.test", "wire-hub.test"]
    assert ceo[1][1] == ["corvane-systems.test"]


def test_corroborated_since_for_executives_needs_every_member():
    builds = [tl.Build(t(i + 1), i) for i in range(7)]
    sim = tl.simulate(builds, "corvane-systems.test")
    ex = [(s["executives"]["corroborated"], s["executives"]["since"]) for s in sim.state_after]
    assert ex == [(True, t(1)), (False, t(1)), (False, None), (False, None),
                  (False, t(5)), (False, t(5)), (False, t(5))]


def test_since_tracker_resets_when_a_member_leaves_and_returns():
    tr = tl.SinceTracker()
    g = lambda *o: {"x": set(o)}
    assert tr.step("investors", g("a"), t(1)) is None
    assert tr.step("investors", g("b"), t(2)) == t(2)           # a and b: two standing origins
    assert tr.step("investors", g("a"), t(3)) == t(2)           # kept: standing origins stay
    assert tr.step("investors", {}, t(4)) is None               # left: nothing stands
    assert tr.step("investors", g("a"), t(5)) is None           # returned: starts again
    assert tr.step("investors", g("a", "c"), t(6)) == t(6)


def test_oakhurst_original_is_not_evidence():
    f = tl.exp_fields("oakhurst-media.test", 0)["hq_city"]
    assert [(c.value, c.origin) for c in f["candidates"]] == [("Nantes", "wire-hub.test")]   # not Lyon
    assert f["status"] == "known" and f["origins"] == ["wire-hub.test"]
