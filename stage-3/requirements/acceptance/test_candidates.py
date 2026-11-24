"""Stage 2 (API): candidates, the selection rule, status, page text. Expected values in this file
are written out by hand from the specification (no oracle code), so they check the oracle too.

Companies (corpus_spec.py): harlow-instruments (every rule), kestrel-optics (default kind from the
URL's host), lumen-textiles (publication time validity), tarn-biotech (known / contested /
unknown, numeric value order), vesper-lanterns (browser text, research-cited pages).
"""
import pytest

import oracle
from lib import (T0, all_unknown, assert_dossier_shape, candidate_problems, citation_problems,
                 parse_ts, total_cost)

pytestmark = pytest.mark.corpus

H = "harlow-instruments.test"
K = "kestrel-optics.test"
L = "lumen-textiles.test"
TB = "tarn-biotech.test"
V = "vesper-lanterns.test"


def built(fresh, domain):
    api, mock = fresh
    tok = api.token(0)
    b = api.build(tok, domain)
    assert b["state"] == "ready", b
    assert_dossier_shape(b, domain)
    return b, mock.log(), tok


def urls(field):
    return [c["url"] for c in field["candidates"]]


def values(field):
    return [c["value"] for c in field["candidates"]]


# ------------------------------------------------------------------ candidates and the rule
def test_R_SEL_01_to_05_harlow_ceo_authority_over_recency(fresh):
    """R-SEL-01 own and filing rank equal and highest, then news, then aggregator, whatever the
    publication time; R-SEL-02 recency within an authority; R-SEL-03 URL at equal time;
    R-STS-02 contested keeps a selected value; R-CAN-03 citations = candidates of that value."""
    b, log, _ = built(fresh, H)
    ceo = b["fields"]["ceo"]
    assert ceo["value"] == "Dana Ruiz" and ceo["status"] == "contested"
    assert urls(ceo) == [
        "https://a-registry.test/harlow",                # filing, 10:00Z: URL < the own page's
        "https://harlow-instruments.test/about",         # own, 10:00Z (12:00+02:00 = same instant)
        "https://news-daily.test/harlow-ceo",            # news, newest page of all, still lower
        "https://listings.test/harlow",                  # aggregator (unlisted Kind), 02-25
        "https://bizdata.test/harlow-instruments",       # aggregator (no Kind), 02-20
    ]
    assert values(ceo) == ["Dana Ruiz", "Dana Ruiz", "Sam Ortiz", "Pat Quill", "Sam Ortiz"]
    assert [c["kind"] for c in ceo["candidates"]] == ["filing", "own", "news", "aggregator",
                                                       "aggregator"]
    assert [c["selected"] for c in ceo["candidates"]] == [True, False, False, False, False]
    assert [c["url"] for c in ceo["citations"]] == urls(ceo)[:2]
    assert not candidate_problems(b, H, log)


def test_R_SEL_03_equal_instants_in_other_offsets_and_url_decides(fresh):
    """founded_year: the filing page (12:00+02:00) and the own page (10:00Z) are the same
    instant; the smaller URL ranks first although it is the filing page. Same for legal_name."""
    b, _, _ = built(fresh, H)
    fy = b["fields"]["founded_year"]
    assert values(fy) == [2010, 2009] and fy["value"] == 2010 and fy["status"] == "contested"
    assert [c["kind"] for c in fy["candidates"]] == ["filing", "own"]
    ln = b["fields"]["legal_name"]
    assert values(ln) == ["Harlow Instruments plc", "Harlow Instruments Ltd"]
    assert ln["value"] == "Harlow Instruments plc" and ln["status"] == "contested"
    assert [c["url"] for c in ln["citations"]] == ["https://a-registry.test/harlow"]


def test_R_SEL_02_recency_beats_url_within_authority(fresh):
    b, _, _ = built(fresh, H)
    hq = b["fields"]["hq_city"]
    assert values(hq) == ["York", "Leeds"], hq["candidates"]
    assert urls(hq) == ["https://harlow-instruments.test/news",
                        "https://harlow-instruments.test/contact"]
    assert hq["value"] == "York" and hq["status"] == "contested"


def test_R_SEL_02_publication_instants_not_strings_and_missing_time_last(fresh):
    """funding_total: …/b (00:00Z) is later than …/a (01:00+02:00 = 23:00Z the day before) although
    the strings sort the other way; undated and badly dated pages rank last, by URL."""
    b, _, _ = built(fresh, H)
    ft = b["fields"]["funding_total"]
    assert values(ft) == [7000000, 5000000, 9000000, 3000000], ft["candidates"]
    assert urls(ft) == ["https://funding-wire.test/b", "https://funding-wire.test/a",
                        "https://funding-wire.test/c", "https://funding-wire.test/d"]
    assert ft["value"] == 7000000
    pubs = [c["published_at"] for c in ft["candidates"]]
    assert pubs[2] is None and pubs[3] is None
    assert parse_ts(pubs[0]) > parse_ts(pubs[1])
    assert parse_ts(pubs[0]).isoformat() == "2026-02-20T00:00:00+00:00"
    assert parse_ts(pubs[1]).isoformat().startswith(("2026-02-20T01:00:00+02:00",
                                                    "2026-02-19T23:00:00+00:00"))


def test_R_SEL_04_same_page_two_values_ranked_by_value(fresh):
    b, _, _ = built(fresh, H)
    hc = b["fields"]["headcount_range"]
    assert urls(hc) == ["https://harlow-instruments.test/careers"] * 2
    assert values(hc) == ["1001-5000", "51-200"]          # strings by code point
    assert hc["value"] == "1001-5000" and hc["status"] == "contested"


def test_R_SEL_04_integers_compare_as_numbers(fresh):
    """tarn-biotech: one news page states $9M and $12M. 9000000 ranks first (as a string
    "12000000" would)."""
    b, _, _ = built(fresh, TB)
    ft = b["fields"]["funding_total"]
    assert values(ft) == [9000000, 12000000, 9000000], ft["candidates"]
    assert urls(ft) == ["https://tarn-news.test/n1", "https://tarn-news.test/n1",
                        "https://tarn-news.test/n2"]
    assert ft["value"] == 9000000 and ft["status"] == "contested"
    assert [c["url"] for c in ft["citations"]] == ["https://tarn-news.test/n1",
                                                  "https://tarn-news.test/n2"]
    assert all(isinstance(c["value"], int) for c in ft["candidates"])


def test_R_CAN_04_default_kind_from_url_host(fresh):
    """No Kind line / unlisted Kind: own when the URL's normalised host is the company's domain,
    aggregator otherwise (`www.` and case and a trailing dot are normalised; a subdomain is not)."""
    b, _, _ = built(fresh, K)
    fy = b["fields"]["founded_year"]
    got = {c["url"]: c["kind"] for c in fy["candidates"]}
    assert got == {
        "https://kestrel-optics.test/a": "own",
        "https://www.kestrel-optics.test/b": "own",
        "https://about.kestrel-optics.test/c": "aggregator",
        "https://kestrel-profiles.test/d": "aggregator",
        "https://kestrel-optics.test/e": "own",              # Kind: blog, on the company's host
        "https://other-host.test/f": "aggregator",           # Kind: blog elsewhere
        "https://other-host.test/g": "news",
        "https://other-host.test/h": "aggregator",           # Kind: NEWS is not a listed value
        "https://Kestrel-Optics.TEST./i": "own",
        "https://other-host.test/j": "filing",
    }, got
    # own + filing (same time) by URL code point, then news, then aggregators by URL
    assert values(fy) == [2009, 2001, 2005, 2010, 2002, 2007, 2003, 2004, 2006, 2008]
    assert fy["value"] == 2009 and fy["status"] == "contested"


def test_R_CAN_05_publication_time_validity(fresh):
    """Only an RFC 3339 timestamp is a publication time (date only, no offset, impossible day,
    free text and absent are not)."""
    b, _, _ = built(fresh, L)
    fy = b["fields"]["founded_year"]
    assert values(fy) == [1992, 1998, 1991, 1993, 1994, 1995, 1996, 1997], fy["candidates"]
    pub = {c["value"]: c["published_at"] for c in fy["candidates"]}
    for y in (1993, 1994, 1995, 1996, 1997):
        assert pub[y] is None, (y, pub[y])
    for y in (1991, 1992, 1998):
        assert pub[y] is not None
    assert parse_ts(pub[1992]) > parse_ts(pub[1998]) > parse_ts(pub[1991])
    assert parse_ts(pub[1998]) == parse_ts("2026-01-01T04:00:00+00:00")
    assert parse_ts(pub[1992]) == parse_ts("2026-01-02T00:00:00.500000+00:00")


def test_R_STS_01_to_03_known_contested_unknown(fresh):
    b, log, _ = built(fresh, TB)
    f = b["fields"]
    assert f["hq_city"]["status"] == "known" and f["hq_city"]["value"] == "Cambridge"
    assert len(f["hq_city"]["citations"]) == 2 and len(f["hq_city"]["candidates"]) == 2
    assert urls(f["hq_city"]) == ["https://tarn-registry.test/tarn",
                                  "https://tarn-biotech.test/about"]    # filing newer than own
    # 120 and 150 are different numbers but one value: the range 51-200
    assert f["headcount_range"]["status"] == "known"
    assert values(f["headcount_range"]) == ["51-200", "51-200"]
    assert f["legal_name"]["status"] == "contested"
    assert values(f["legal_name"]) == ["Tarn Biotech Limited", "Tarn Biotech Ltd"]
    assert f["legal_name"]["value"] == "Tarn Biotech Limited"
    assert f["funding_total"]["status"] == "contested"
    for name in ("ceo", "founded_year"):                  # only a negated statement ("might be")
        assert (f[name]["value"] is None and f[name]["status"] == "unknown"
                and f[name]["citations"] == [] and f[name]["candidates"] == []), f[name]
    assert not candidate_problems(b, TB, log)


def test_R_STS_03_no_evidence_means_unknown_with_empty_candidates(fresh):
    api, mock = fresh
    b = api.build(api.token(0), "nowhere-at-all.test")
    assert b["state"] == "ready" and all_unknown(b)
    assert all(fv["candidates"] == [] for fv in b["fields"].values())


# ------------------------------------------------------------------ page text, research pages
def test_R_WEB_01_text_is_what_a_browser_shows(fresh):
    """vesper-lanterns: search/extract serve a stale static text (Venice, 1989, JavaScript
    notice); the browser shows Murano, 1998 and the team facts. Evidence is read from the
    browser text; a citation excerpt must appear in it."""
    b, log, _ = built(fresh, V)
    f = b["fields"]
    assert f["hq_city"]["value"] == "Murano" and f["hq_city"]["status"] == "known"
    assert sorted(urls(f["hq_city"])) == ["https://vesper-lanterns.test/about",
                                          "https://vesper-lanterns.test/press"]
    assert urls(f["hq_city"]) == ["https://vesper-lanterns.test/press",   # published later
                                  "https://vesper-lanterns.test/about"]
    assert f["ceo"]["value"] == "Lia Moretti" and f["headcount_range"]["value"] == "11-50"
    assert f["founded_year"]["value"] == 1998
    for name, stale in (("hq_city", "Venice"), ("founded_year", 1989)):
        assert stale not in values(f[name]), f[name]
        for c in f[name]["candidates"]:
            assert "Venice" not in c["excerpt"] and "1989" not in c["excerpt"], c
    assert f["legal_name"]["status"] == "unknown"
    assert not candidate_problems(b, V, log) and not citation_problems(b, V, log)


def test_R_CAN_06_research_cited_pages_are_evidence_whether_or_not_claim_supports(fresh):
    """The page cited by a research claim is read like any other. /investors and /press are not
    searchable; the claim on /press ("might raise $20M") does not support its value, so
    20000000 is not a candidate, yet /press's other sentence (head office in Murano) is one."""
    b, _, _ = built(fresh, V)
    f = b["fields"]
    assert values(f["funding_total"]) == [2000000] and f["funding_total"]["status"] == "known"
    assert 20000000 not in values(f["funding_total"])
    assert "https://vesper-lanterns.test/press" in urls(f["hq_city"])         # via the cited page
    assert urls(f["founded_year"]) == ["https://vesper-lanterns.test/investors"]


def test_R_WEB_02_render_costs_and_budget(fresh):
    """Nimble extract with render costs 3 per URL (spent_units counts it); the build stays within
    80 units; a claim excerpt that is only in the static text is not a candidate."""
    b, log, _ = built(fresh, V)
    cost = total_cost(log)
    assert b["spent_units"] == cost <= 80, (b["spent_units"], cost)
    ext = [e for e in log if e.get("method") == "extract" and e.get("provider") == "nimble"
           and e.get("status", 200) < 400]
    assert ext or any(e.get("method") in ("load", "browse") for e in log), \
        "no browser-text source was used: stale text would have been cited"
    for e in ext:
        n = len(e.get("urls") or [])
        assert e.get("cost") in (n, 3 * n), e
    # the service must have obtained the browser text of the non-searchable cited pages
    seen = {u for e in log if e.get("method") in ("extract", "load") for u in (e.get("urls") or [])}
    assert "https://vesper-lanterns.test/investors" in seen
    assert "https://vesper-lanterns.test/press" in seen


# ------------------------------------------------------------------ list, time, build lifecycle
def test_R_LST_05_legal_name_listed_is_the_selected_value(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, H)
    items = api.list(tok).json()["dossiers"]
    assert items[0]["domain"] == H and items[0]["legal_name"] == "Harlow Instruments plc"
    assert [i["domain"] for i in api.list(tok, q="PLC").json()["dossiers"]] == [H]
    assert api.list(tok, q="ltd").json()["dossiers"] == []       # a candidate, not the value


def test_R_CAN_07_retrieved_at_is_the_build_time_and_candidates_follow_the_last_ready_build(fresh):
    api, mock = fresh
    tok = api.token(0)
    d = "pivotal-reed.test"
    a = api.build(tok, d)
    assert a["state"] == "ready" and a["researched_at"] == T0
    assert [c["value"] for c in a["fields"]["ceo"]["candidates"]] == ["Hana Sato"]
    assert all(parse_ts(c["retrieved_at"]) == parse_ts(T0)
               for fv in a["fields"].values() for c in fv["candidates"])
    # a failed build leaves fields, candidates and retrieved_at as they were
    api.clock("2026-03-02T09:00:00+00:00")
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "error")
    assert api.refresh(tok, d).status_code == 202
    f = api.wait(tok, d, timeout=60)
    assert f["state"] == "failed" and f["fields"] == a["fields"] and f["researched_at"] == T0
    for p in ("nimble", "tavily"):
        mock.fault(p, ["search", "extract", "research"], "none")
    # the web changes; a refresh at a later clock replaces the candidates
    mock.epoch(1)
    api.clock("2026-03-03T09:00:00+00:00")
    assert api.refresh(tok, d).status_code == 202
    # while it builds, the dossier shows the last build that completed ready
    mid = api.get(tok, d).json()
    if mid["state"] == "building":
        assert mid["fields"] == a["fields"]
    c = api.wait(tok, d)
    assert c["state"] == "ready" and c["researched_at"] == "2026-03-03T09:00:00+00:00"
    ceo = c["fields"]["ceo"]
    assert ceo["value"] == "Leon Brandt" and [x["value"] for x in ceo["candidates"]] == ["Leon Brandt"]
    assert c["fields"]["founded_year"]["candidates"] == [] and c["fields"]["founded_year"]["status"] == "unknown"
    for fv in c["fields"].values():
        for cand in fv["candidates"]:
            assert parse_ts(cand["retrieved_at"]) == parse_ts("2026-03-03T09:00:00+00:00")
    assert not candidate_problems(c, d, mock.log(), epoch=1)


def test_R_CAN_08_same_candidates_same_value_after_every_refresh(fresh):
    """3. "The same candidates always yield the same value": repeated builds of one web agree."""
    api, mock = fresh
    tok = api.token(0)
    first = api.build(tok, H)
    for _ in range(2):
        api.clock("2026-03-05T09:00:00+00:00")
        assert api.refresh(tok, H).status_code == 202
        again = api.wait(tok, H)
        assert again["state"] == "ready"
        for f in oracle.FIELDS:
            assert again["fields"][f]["value"] == first["fields"][f]["value"]
            assert again["fields"][f]["status"] == first["fields"][f]["status"]
            assert [(c["url"], c["value"]) for c in again["fields"][f]["candidates"]] == \
                [(c["url"], c["value"]) for c in first["fields"][f]["candidates"]]
    # every refresh is its own build within budget; spent_units is the sum
    log = mock.log()
    assert again["spent_units"] == total_cost(log)
