"""Stage 4 (API): lineage header lines, own pages and lookalikes, origins, `origins`, `corroborated`
and `corroborated_since`. Corpus companies (corpus_spec.py): linden-forge.test (kind needs the
registrant; lookalikes), ravenmoor-energy.test (Canonical chains, a cycle, a missing original),
corvane-systems.test (seven builds: standing origins, resets, a failed build).

Every expectation is derived from stage-4.md (oracle: rank.py, lineage.py, timeline.py, checked
offline by test_s4_unit.py); the by-hand assertions restate the spec's rules on single pages."""
import pytest

import oracle
import s3lib
import s4lib
import timeline as tl
from lib import T0, assert_dossier_shape, parse_ts

pytestmark = pytest.mark.corpus

LF = "linden-forge.test"
RM = "ravenmoor-energy.test"
CV = "corvane-systems.test"
CV_DAYS = [f"2026-03-0{d}T09:00:00+00:00" for d in range(1, 8)]
CV_SCRIPT = [{"epoch": 0, "clock": CV_DAYS[0]}, {"epoch": 1, "clock": CV_DAYS[1]},
             {"epoch": 2, "clock": CV_DAYS[2]},
             {"epoch": 2, "clock": "2026-03-03T12:00:00+00:00", "fail": True},     # a failed build
             {"epoch": 3, "clock": CV_DAYS[3]}, {"epoch": 4, "clock": CV_DAYS[4]},
             {"epoch": 5, "clock": CV_DAYS[5]}, {"epoch": 6, "clock": CV_DAYS[6]}]
READY_IDX = [0, 1, 2, 4, 5, 6, 7]                  # CV_SCRIPT indexes of the ready builds


def one(api, mock, tok, domain, epoch=0, clock=T0):
    recs = s3lib.run(api, mock, tok, domain, [{"epoch": epoch, "clock": clock}])
    builds = s3lib.to_builds(recs, domain)
    return dict(recs=recs, builds=builds, sim=tl.simulate(builds, domain), domain=domain,
                snap=recs[0].snap)


@pytest.fixture(scope="module")
def world(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    out = dict(api=api, mock=mock, tok=tok)
    recs = s3lib.run(api, mock, tok, CV, CV_SCRIPT)          # the clock only moves forward
    builds = s3lib.to_builds(recs, CV)
    out["cv"] = dict(recs=recs, builds=builds, sim=tl.simulate(builds, CV), domain=CV)
    out["lf"] = one(api, mock, tok, LF, clock="2026-03-10T09:00:00+00:00")
    out["rm"] = one(api, mock, tok, RM, clock="2026-03-11T09:00:00+00:00")
    out["ok"] = one(api, mock, tok, "oakhurst-media.test", clock="2026-03-12T09:00:00+00:00")
    return out


def cand_by_url(fv):
    return {c["url"]: c for c in fv["candidates"]}


def all_cands(body):
    return [c for fv in body["fields"].values() for c in fv["candidates"]]


# ------------------------------------------------------------------ own pages and lookalikes
def test_R4_OWN_01_every_response_matches_the_oracle_for_linden_forge(world):
    """R4-OWN-01..05, R4-ORG-*: all eight fields, kinds, origins, ranking and keys of one build."""
    sc = world["lf"]
    probs = s3lib.snapshot_problems(sc["snap"], LF, sc["recs"], 0, sc["builds"], sc["sim"])
    assert not probs, "\n".join(probs)
    assert_dossier_shape(sc["snap"], LF)


def test_R4_OWN_02_kind_own_needs_the_registrant_to_be_the_company(world):
    f = world["lf"]["snap"]["fields"]
    ceo = cand_by_url(f["ceo"])
    assert ceo["https://linden-forge.test/about"]["kind"] == "own"
    # presents itself as Linden Forge but is registered to shadow-host.test: a lookalike, an aggregator
    assert ceo["https://linden-forge-official.test/about"]["kind"] == "aggregator"
    assert f["ceo"]["value"] == "Hana Weiss" and f["ceo"]["status"] == "contested"
    fy = cand_by_url(f["founded_year"])
    assert fy["https://blog.linden-forge.test/post"]["kind"] == "aggregator"     # states own, registered to itself
    assert fy["https://linden-forge.test/press"]["kind"] == "own"                # Registrant: WWW.Linden-Forge.TEST.
    assert fy["https://registry.test/linden"]["kind"] == "filing"
    hc = cand_by_url(f["headcount_range"])
    assert hc["https://linden-forge.test/careers"]["kind"] == "own"              # invalid Registrant: its host
    assert hc["https://linden-forge-info.test/x"]["kind"] == "aggregator"


def test_R4_OWN_03_a_page_with_no_kind_line_needs_the_registrant_too(world):
    """RUL-S4-02: on the company's host but registered to registry-corp.test, with no Kind line."""
    ln = world["lf"]["snap"]["fields"]["legal_name"]
    assert ln["value"] == "Linden Forge, Inc." and ln["status"] == "known"
    c = ln["candidates"][0]
    assert c["url"] == "https://linden-forge.test/legal"
    assert c["kind"] == "aggregator" and c["origin"] == "registry-corp.test"


def test_R4_OWN_04_a_lookalike_changes_what_the_selection_rule_picks(world):
    """The lookalike's candidate ranks as an aggregator below the company's own page even though it
    was published later."""
    ceo = world["lf"]["snap"]["fields"]["ceo"]
    assert [c["value"] for c in ceo["candidates"]] == ["Hana Weiss", "Gordon Pike"]
    assert [c["selected"] for c in ceo["candidates"]] == [True, False]
    assert parse_ts(ceo["candidates"][1]["published_at"]) > parse_ts(ceo["candidates"][0]["published_at"])
    assert [c["url"] for c in ceo["citations"]] == ["https://linden-forge.test/about"]


# ------------------------------------------------------------------ origins
def test_R4_ORG_01_origins_of_the_linden_forge_pages_by_hand(world):
    f = world["lf"]["snap"]["fields"]
    hq = cand_by_url(f["hq_city"])
    # a lookalike with a Canonical: rule 2 (the original's registrant) before rule 3
    assert hq["https://linden-forge-copy.test/hq"]["origin"] == "wire-hub.test"
    # a copy of an original that is itself a lookalike: the company's domain (rule 3 of the original)
    assert hq["https://copycat.test/linden"]["origin"] == "linden-forge.test"
    assert f["hq_city"]["value"] == "Graz"
    assert f["hq_city"]["origins"] == ["linden-forge.test", "wire-hub.test"]
    assert f["hq_city"]["corroborated"] is True
    ceo = cand_by_url(f["ceo"])
    assert ceo["https://linden-forge-official.test/about"]["origin"] == "linden-forge.test"   # rule 3
    assert f["ceo"]["origins"] == ["linden-forge.test"] and f["ceo"]["corroborated"] is False
    fy = cand_by_url(f["founded_year"])
    assert fy["https://blog.linden-forge.test/post"]["origin"] == "blog.linden-forge.test"
    assert fy["https://registry.test/linden"]["origin"] == "registry.test"
    assert f["founded_year"]["origins"] == ["blog.linden-forge.test", "linden-forge.test", "registry.test"]
    hc = cand_by_url(f["headcount_range"])
    assert hc["https://linden-forge-info.test/x"]["origin"] == "press-wire.test"     # rule 1 before rule 3
    assert f["headcount_range"]["origins"] == ["linden-forge.test", "press-wire.test"]
    assert f["headcount_range"]["corroborated"] is True


def test_R4_ORG_02_originals_are_obtained_but_are_not_evidence(world):
    """RUL-S4-05. oakhurst-media.test: the copy (a search returns it) says Nantes, its original at
    wire-hub.test (no search returns it) says Lyon. §4: evidence = the pages searches return plus
    the pages research claims cite; stage 4 only says a build *obtains* the original, to know the
    origin. So hq_city holds one candidate, Nantes, with origin wire-hub.test."""
    rec = world["ok"]["recs"][0]                       # built in the shared module fixture (no reset here)
    hq = rec.snap["fields"]["hq_city"]
    assert [(c["value"], c["url"], c["origin"]) for c in hq["candidates"]] == [
        ("Nantes", "https://copy-desk.test/oakhurst", "wire-hub.test")]
    assert hq["value"] == "Nantes" and hq["status"] == "known" and hq["origins"] == ["wire-hub.test"]
    served = {it.get("url") for e in rec.segment if isinstance(e.get("status"), int) and e["status"] < 400
              for it in e.get("served") or [] if isinstance(it, dict)}
    assert "https://wire-hub.test/oakhurst-hq" in served          # obtained (R4-ORG-02) ...
    assert not any("wire-hub.test" in c["url"] for fv in rec.snap["fields"].values()
                   for c in fv["candidates"])                       # ... but nobody's candidate


def test_R4_ORG_03_a_build_obtains_each_original_rule_2_needs(world):
    served = set()
    for e in world["lf"]["recs"][0].segment:
        if isinstance(e.get("status"), int) and e["status"] < 400:
            for it in e.get("served") or []:
                if isinstance(it, dict) and it.get("url"):
                    served.add(it["url"])
    for u in ("https://wire-hub.test/linden-hq", "https://fake-linden.test/hq"):
        assert u in served, f"no provider served the original {u}"
    served_rm = set()
    for e in world["rm"]["recs"][0].segment:
        if isinstance(e.get("status"), int) and e["status"] < 400:
            for it in e.get("served") or []:
                if isinstance(it, dict) and it.get("url"):
                    served_rm.add(it["url"])
    assert "https://archive.test/rm" in served_rm        # needed by c1, c2, c3 (the third follow)


def test_R4_ORG_04_canonical_chain_follows_three_urls_at_most(world):
    sc = world["rm"]
    probs = s3lib.snapshot_problems(sc["snap"], RM, sc["recs"], 0, sc["builds"], sc["sim"])
    assert not probs, "\n".join(probs)
    fy = world["rm"]["snap"]["fields"]["founded_year"]
    o = {c["url"]: c["origin"] for c in fy["candidates"]}
    assert o["https://c0.test/rm"] == "archive.test"             # a fourth Canonical: host of that URL
    for u in ("https://c1.test/rm", "https://c2.test/rm", "https://c3.test/rm"):
        assert o[u] == "pressroom.test", u                       # the original's registrant
    assert o["https://ravenmoor-energy.test/about"] == "ravenmoor-energy.test"
    assert fy["value"] == 2003 and fy["status"] == "known"
    assert fy["origins"] == ["archive.test", "pressroom.test", "ravenmoor-energy.test"]
    assert fy["corroborated"] is True


def test_R4_ORG_05_missing_original_cycle_self_canonical_and_first_published_by(world):
    f = world["rm"]["snap"]["fields"]
    fund = f["funding_total"]["candidates"][0]
    assert fund["url"] == "https://m-copy.test/rm" and fund["origin"] == "nowhere-host.test"
    hq = {c["url"]: c["origin"] for c in f["hq_city"]["candidates"]}
    assert hq == {"https://cyc-a.test/rm": "cyc-a.test", "https://cyc-b.test/rm": "cyc-b.test"}
    hc = {c["url"]: c["origin"] for c in f["headcount_range"]["candidates"]}
    assert hc["https://r-self.test/rm"] == "r-self.test"          # Canonical = its own URL: no copy
    assert hc["https://s-copy.test/rm"] == "first-wire.test"      # First-Published-By before Canonical
    assert f["hq_city"]["origins"] == ["cyc-a.test", "cyc-b.test"]


def test_R4_ORG_06_one_source_however_many_urls_kinds_or_providers(world):
    """Four ceo candidates of corvane-systems at the first build, three origins."""
    b = world["cv"]["recs"][0].snap
    ceo = b["fields"]["ceo"]
    assert len(ceo["candidates"]) == 4
    assert {c["url"]: c["origin"] for c in ceo["candidates"]} == {
        "https://corvane-systems.test/about": "corvane-systems.test",
        "https://daily-ledger.test/corvane": "wire-hub.test",          # Canonical -> wire-hub.test
        "https://bizdata.test/corvane": "daily-ledger.test",           # First-Published-By
        "https://mirror-one.test/corvane": "daily-ledger.test",        # Canonical -> a page with First-Published-By
    }
    assert ceo["origins"] == ["corvane-systems.test", "daily-ledger.test", "wire-hub.test"]
    assert ceo["corroborated"] is True


def test_R4_ORG_07_every_candidate_on_every_field_carries_a_valid_origin(world):
    for rec in world["cv"]["recs"]:
        if rec.ready:
            assert all(isinstance(c["origin"], str) and c["origin"] for c in all_cands(rec.snap))
            assert_dossier_shape(rec.snap, CV)


# ------------------------------------------------------------------ corroboration over builds
def ready_recs(world):
    return [world["cv"]["recs"][i] for i in READY_IDX]


def test_R4_COR_01_corvane_every_build_matches_the_oracle(world):
    sc = world["cv"]
    for i in READY_IDX:
        probs = s3lib.snapshot_problems(sc["recs"][i].snap, CV, sc["recs"], i, sc["builds"], sc["sim"])
        assert not probs, f"build {i}:\n" + "\n".join(probs)


def test_R4_COR_02_value_origins_corroborated_and_since_by_hand(world):
    snaps = [r.snap["fields"]["ceo"] for r in ready_recs(world)]
    assert [s["value"] for s in snaps] == ["Ines Marchetti", "Ines Marchetti", "Paul Oyelaran",
                                           "Paul Oyelaran", "Paul Oyelaran", "Ines Marchetti",
                                           "Ines Marchetti"]
    assert [s["corroborated"] for s in snaps] == [True, False, False, True, False, False, True]
    sinces = [s["corroborated_since"] for s in snaps]
    t = lambda d: parse_ts(CV_DAYS[d - 1])
    assert parse_ts(sinces[0]) == t(1) and parse_ts(sinces[1]) == t(1)    # standing origins stay
    assert sinces[2] is None                                              # a new value starts with none
    assert parse_ts(sinces[3]) == t(4) and parse_ts(sinces[4]) == t(4)
    assert sinces[5] is None                                              # Ines again: starts afresh
    assert parse_ts(sinces[6]) == t(7)
    assert snaps[1]["origins"] == ["corvane-systems.test"]


def test_R4_COR_03_executives_every_member_needs_two_standing_origins(world):
    ex = [r.snap["fields"]["executives"] for r in ready_recs(world)]
    t = lambda d: parse_ts(CV_DAYS[d - 1])
    assert [e["corroborated"] for e in ex] == [True, False, False, False, False, False, False]
    got = [e["corroborated_since"] and parse_ts(e["corroborated_since"]) for e in ex]
    # cfo is corroborated from build 1; coo (own page only until build 5) holds the field back
    assert got == [t(1), t(1), None, None, t(5), t(5), t(5)]
    assert [m["title"] for m in ex[2]["value"]] == ["cfo", "coo"]


def test_R4_COR_04_a_field_without_a_second_origin_never_corroborates(world):
    for r in ready_recs(world):
        fy = r.snap["fields"]["founded_year"]
        assert fy["origins"] == ["corvane-systems.test"]
        assert fy["corroborated"] is False and fy["corroborated_since"] is None


def test_R4_COR_05_failed_build_changes_nothing(world):
    recs = world["cv"]["recs"]
    assert recs[3].snap["state"] == "failed"
    assert recs[3].snap["fields"] == recs[2].snap["fields"]
    assert recs[3].snap["researched_at"] == recs[2].snap["researched_at"]


def test_R4_COR_06_as_of_answers_with_the_keys_as_of_that_build(world):
    """RUL-S4-07: an `as_of` answer describes the corroboration as that build left it, using no
    later history."""
    sc = world["cv"]
    api, tok = world["api"], world["tok"]
    for i in READY_IDX:
        r = s3lib.as_of(api, tok, CV, sc["recs"][i].clock)
        assert r.status_code == 200
        probs = s3lib.snapshot_problems(r.json(), CV, sc["recs"], i, sc["builds"], sc["sim"])
        assert not probs, f"as_of build {i}:\n" + "\n".join(probs)
    # before the build that corroborates `ceo` the as_of answer says null
    b3 = s3lib.as_of(api, tok, CV, "2026-03-03T23:00:00+00:00").json()
    assert b3["fields"]["ceo"]["corroborated_since"] is None


def test_R4_COR_07_history_feed_and_values_match_the_oracle(world):
    sc = world["cv"]
    api, tok = world["api"], world["tok"]
    h = s3lib.history(api, tok, CV).json()
    assert not s3lib.history_problems(h, CV, sc["recs"], sc["builds"], sc["sim"])
    feed = [e for e in s3lib.all_changes(api, tok) if e["domain"] == CV]
    assert not s3lib.feed_problems(feed, CV, sc["sim"])
    for true_at, as_of in (("2026-03-01", CV_DAYS[6]), ("2026-04-01", CV_DAYS[3]), ("2021-05-01", CV_DAYS[0])):
        body = s3lib.values(api, tok, CV, true_at, as_of).json()
        from lib import parse_ts as pts
        probs = s3lib.check_values(body, CV, sc["recs"], sc["builds"], pts(as_of), true_at, as_of)
        assert not probs, probs
        assert list(body["fields"]) == oracle.ALL_FIELDS
