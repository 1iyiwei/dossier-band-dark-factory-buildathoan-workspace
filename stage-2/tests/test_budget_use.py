"""§8: a ready build has a field known whenever the evidence supports it, so budget left over
(e.g. research refused) goes to further searches rather than being left unspent (§9 cap kept)."""
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("NIMBLE_API_KEY", "test")
os.environ.setdefault("NIMBLE_BASE_URL", "http://127.0.0.1:9/nimble")

from app.builder import FIELD_QUERY_WORDS, Builder  # noqa: E402
from app.providers import Budget, Deadline, Gateway  # noqa: E402

DOMAIN = "deep-co.test"
NAME = "Deep Co"
FILLER = "Deep Co builds things for many customers across the region every single day. " * 6
# One page per field; each holds its statement only after a long opening, beyond any snippet.
FACTS = {
    "legal_name": "The registered name is Deep Co Ltd.",
    "hq_city": "Deep Co is headquartered in Lisbon.",
    "ceo": "Deep Co is led by chief executive Dana Ruiz.",
    "founded_year": "Deep Co was founded in 2011.",
    "headcount_range": "Deep Co employs about 120 people.",
    "funding_total": "Deep Co has raised $12M from investors.",
}
EXPECTED = {"legal_name": "Deep Co Ltd", "hq_city": "Lisbon", "ceo": "Dana Ruiz", "founded_year": 2011,
            "headcount_range": "51-200", "funding_total": 12000000}


class Refused(Exception):
    status_code = 500


class Router:
    """Searches work; extract and research are refused. Only a field's own query finds its page."""

    def __init__(self):
        self.calls = []

    def search(self, query, search_depth=None, **_):
        self.calls.append(("search", query, search_depth))
        field = next((f for f, words in FIELD_QUERY_WORDS.items() if any(query == f"{NAME} {w}" for w in words)),
                     None)
        pages = [(f"https://{DOMAIN}/home", FILLER)]
        if field is not None:
            pages.append((f"https://{DOMAIN}/{field}", FILLER + FACTS[field]))
        results = []
        for url, text in pages:
            body = text if search_depth == "deep" else (text[:1500] if search_depth == "fast" else text[:300])
            results.append(SimpleNamespace(url=url, title=NAME, content=body, description=""))
        return SimpleNamespace(results=results)

    def extract(self, urls, **_):
        self.calls.append(("extract", urls[0], None))
        raise Refused()

    def research(self, query, **_):
        self.calls.append(("research", query, None))
        raise Refused()


class BudgetUseTests(unittest.TestCase):
    def test_extract_and_research_refused_budget_goes_to_deep_searches(self):
        gateway = Gateway(call_timeout=2.0)
        gateway.tavily_enabled = False
        router = Router()
        gateway._router = router
        budget = Budget(80, lambda _: None)
        result = Builder(gateway, DOMAIN, budget, lambda: False, Deadline()).run()
        self.assertTrue(result.succeeded)
        deep = [c for c in router.calls if c[0] == "search" and c[2] == "deep"]
        self.assertGreaterEqual(len(deep), 4, router.calls)          # 25 units of refused research respent
        self.assertLessEqual(budget.spent, 80)
        self.assertGreaterEqual(budget.spent, 66, router.calls)      # less than one deep search left unspent
        known = {f: v["value"] for f, v in result.fields.items() if v["value"] is not None}
        self.assertGreaterEqual(len(known), 4, known)
        for field, value in known.items():
            self.assertEqual(value, EXPECTED[field])
        domain_searches = [c for c in router.calls if c[0] == "search" and c[1] == DOMAIN]
        self.assertEqual(len(domain_searches), 1)


if __name__ == "__main__":
    unittest.main()
