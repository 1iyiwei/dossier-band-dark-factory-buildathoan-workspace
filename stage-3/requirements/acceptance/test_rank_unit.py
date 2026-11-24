"""Offline self-tests of rank.py (the analyst's selection-rule oracle): the examples of the
specification and the edge cases the acceptance tests rely on. No service needed."""
import pytest

import rank
from lib import candidate_structure_problems


def C(value, url, provider="nimble", kind="own", pub=None, selected=False, excerpt="x"):
    return {"value": value, "url": url, "provider": provider, "kind": kind, "published_at": pub,
            "excerpt": excerpt, "retrieved_at": "2026-03-01T09:00:00+00:00", "selected": selected}


def order(cands):
    return [c["value"] for c in cands]


def test_spec_example_own_beats_newer_aggregator():
    own = C("Dana Ruiz", "https://acme-robotics.test/about", kind="own", pub="2026-01-10T00:00:00+00:00")
    agg = C("Sam Ortiz", "https://bizdata.test/acme-robotics", provider="tavily", kind="aggregator",
            pub="2026-02-20T00:00:00+00:00")
    assert rank.rank_key_problems([own, agg]) == []
    assert rank.rank_key_problems([agg, own])


def test_own_and_filing_rank_equal_then_url_decides():
    a = C(1, "https://a.test/x", kind="filing", pub="2026-01-01T00:00:00Z")
    b = C(2, "https://b.test/x", kind="own", pub="2026-01-01T00:00:00Z")
    assert rank.rank_key_problems([a, b]) == [] and rank.rank_key_problems([b, a])


def test_recency_compares_instants_not_strings():
    early = C(1, "https://z.test", kind="news", pub="2026-02-20T01:00:00+02:00")      # 02-19 23:00Z
    late = C(2, "https://a.test", kind="news", pub="2026-02-20T00:00:00Z")
    assert rank.rank_key_problems([late, early]) == [] and rank.rank_key_problems([early, late])


def test_missing_time_ranks_below_dated_within_authority_but_not_across():
    dated_agg = C(1, "https://z.test", kind="aggregator", pub="2020-01-01T00:00:00Z")
    undated_news = C(2, "https://a.test", kind="news", pub=None)
    undated_agg = C(3, "https://a.test/b", kind="aggregator", pub=None)
    assert rank.rank_key_problems([undated_news, dated_agg, undated_agg]) == []
    assert rank.rank_key_problems([dated_agg, undated_agg]) == []   # dated before undated
    assert rank.rank_key_problems([undated_agg, dated_agg])


def test_url_by_code_point_then_provider_then_value():
    assert rank.rank_key_problems([C(1, "https://Z.test"), C(2, "https://a.test")]) == []
    same_url = [C(1, "https://a.test", provider="nimble"), C(1, "https://a.test", provider="tavily"),
                C(1, "https://a.test", provider="kernel"), C(1, "https://a.test", provider="browserbase")]
    assert rank.rank_key_problems(same_url) == []
    assert rank.rank_key_problems(list(reversed(same_url)))
    nine, twelve = C(9000000, "https://a.test"), C(12000000, "https://a.test")
    assert rank.rank_key_problems([nine, twelve]) == []        # integers as numbers
    assert rank.rank_key_problems([twelve, nine])
    assert rank.rank_key_problems([C(" Abe ", "https://a.test"), C("Zed", "https://a.test")]) == []


def test_null_kind_is_aggregator():
    imported = C("x", "https://a.test", kind=None)
    news = C("y", "https://b.test", kind="news")
    assert rank.rank_key_problems([news, imported]) == [] and rank.rank_key_problems([imported, news])


@pytest.mark.parametrize("text,ok", [
    ("2026-02-20T00:00:00Z", True), ("2026-02-20T01:00:00+02:00", True),
    ("2026-01-02T00:00:00.500Z", True), ("2026-02-20", False), ("2026-02-20T00:00:00", False),
    ("2026-02-30T00:00:00Z", False), ("soon", False), (None, False), ("2026-02-20 00:00:00Z", False),
])
def test_rfc3339(text, ok):
    assert (rank.parse_rfc3339(text) is not None) == ok


def test_default_kind_from_host():
    d = "kestrel-optics.test"
    k = lambda u, kind=None: rank.kind_of({"url": u, "kind": kind}, d)       # noqa: E731
    assert k("https://kestrel-optics.test/a") == "own"
    assert k("https://www.kestrel-optics.test/a") == "own"
    assert k("https://Kestrel-Optics.TEST./a") == "own"
    assert k("https://about.kestrel-optics.test/a") == "aggregator"
    assert k("https://elsewhere.test/a", "blog") == "aggregator"
    assert k("https://elsewhere.test/a", "news") == "news"
    assert k("https://elsewhere.test/a", "NEWS") == "aggregator"


def test_structure_problems_detect_wrong_status_and_citations():
    good = [C("A", "https://a.test", selected=True, excerpt="e1"), C("B", "https://b.test", excerpt="e2")]
    field = {"value": "A", "status": "contested", "citations": [
        {"url": "https://a.test", "excerpt": "e1", "provider": "nimble"}], "candidates": good}
    assert candidate_structure_problems({"fields": {"ceo": field}}) == []
    field["status"] = "known"
    assert candidate_structure_problems({"fields": {"ceo": field}})
    field["status"] = "contested"
    field["citations"] = []
    assert candidate_structure_problems({"fields": {"ceo": field}})
