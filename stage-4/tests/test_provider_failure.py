"""Stage 4: provider failure, end to end through Gateway and Builder with a scripted provider layer.

A provider answers a call with an error status (5xx or 429) per a policy; refused calls cost
nothing, the build goes on, and a build in which every call fails ends failed within §8's bound.
"""
import os
import threading
import time
import unittest
from collections import Counter
from types import SimpleNamespace

os.environ.setdefault("NIMBLE_API_KEY", "test")
os.environ.setdefault("NIMBLE_BASE_URL", "http://127.0.0.1:9/nimble")

from app.builder import Builder  # noqa: E402
from app.providers import COSTS, Budget, Deadline, Gateway, Pool  # noqa: E402

DOMAIN = "fail-co.test"
ABOUT = "https://fail-co.test/about"
NEWS = "https://wire.test/fail-co"
TEXTS = {
    ABOUT: "Kind: own\n\nFail Co was founded in 2011. Fail Co is headquartered in Lisbon. "
             "Fail Co is backed by Northwind Ventures.",
    NEWS: "Kind: news\nPublished: 2026-02-01T00:00:00Z\n\nFail Co employs about 120 people.",
}


class Refused(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class Providers:
    """Answers per `policy(provider, method, target, attempt)`: None serves the call, a status refuses it."""

    def __init__(self, policy):
        self.policy = policy
        self.attempts = Counter()
        self.served_cost = 0
        self.calls = 0
        self._lock = threading.Lock()

    def _answer(self, provider, method, target, depth, cost_key=None):
        with self._lock:
            attempt = self.attempts[(provider, method, target)]
            self.attempts[(provider, method, target)] += 1
            self.calls += 1
        status = self.policy(provider, method, target, attempt)
        if status is not None:
            raise Refused(status)
        with self._lock:
            self.served_cost += COSTS[(provider, method, depth)]

    def search(self, query, provider="nimble", search_depth="lite", **_):
        self._answer(provider, "search", query, search_depth)
        return SimpleNamespace(results=[SimpleNamespace(url=u, title=u, content=t.split("\n\n", 1)[1], description="")
                                        for u, t in TEXTS.items()])

    def extract(self, urls, provider="nimble", provider_options=None, **_):
        render = bool(provider_options and provider_options.get("render"))
        self._answer(provider, "extract", urls[0], "render" if render else None)
        return SimpleNamespace(documents=[SimpleNamespace(content=TEXTS[urls[0]])])

    def research(self, query, **_):
        self._answer("nimble", "research", query, None)
        return SimpleNamespace(structured={}, citations=[])


def build(policy, tavily=True, pool=None):
    gateway = Gateway(call_timeout=2.0)
    gateway.tavily_enabled = tavily
    providers = Providers(policy)
    gateway._router = providers
    budget = Budget(80, lambda _: None, pool)
    deadline = Deadline()
    started = time.monotonic()
    builder = Builder(gateway, DOMAIN, budget, lambda: False, deadline)
    result = builder.run()
    return result, providers, budget, time.monotonic() - started, deadline.active()


def known(result):
    return {name: field["value"] for name, field in result.fields.items() if field["status"] != "unknown"}


class ProviderFailure(unittest.TestCase):
    EVIDENCE = {"founded_year": 2011, "hq_city": "Lisbon", "headcount_range": "51-200",
                "investors": ["Northwind Ventures"]}

    def assert_evidence(self, result):
        for name, value in self.EVIDENCE.items():
            self.assertEqual(known(result).get(name), value, name)

    def test_every_call_to_the_other_providers_fails_while_nimble_answers(self):
        for status in (500, 503, 429):
            with self.subTest(status=status):
                result, providers, budget, _, _ = build(lambda p, m, t, a: status if p != "nimble" else None)
                self.assertTrue(result.succeeded)
                self.assert_evidence(result)
                self.assertEqual(budget.spent, providers.served_cost)

    def test_nimble_searches_refused_once_each_still_end_ready(self):
        # Tavily refuses everything; Nimble refuses each call's first attempts, then answers.
        result, providers, budget, _, _ = build(lambda p, m, t, a: 502 if p != "nimble" or a < 2 else None)
        self.assertTrue(result.succeeded)
        self.assert_evidence(result)
        self.assertEqual(budget.spent, providers.served_cost)
        self.assertLessEqual(budget.spent, 80)

    def test_every_research_run_fails(self):
        for status in (500, 429):
            with self.subTest(status=status):
                result, providers, budget, _, _ = build(lambda p, m, t, a: status if m == "research" else None)
                self.assertTrue(result.succeeded)
                self.assert_evidence(result)
                self.assertEqual(budget.spent, providers.served_cost)
                self.assertTrue(providers.attempts[("nimble", "research", next(
                    k[2] for k in providers.attempts if k[1] == "research"))] >= 2)   # it was asked again

    def test_every_call_to_every_provider_fails(self):
        result, providers, budget, took, _ = build(lambda p, m, t, a: 500)
        self.assertFalse(result.succeeded)
        self.assertEqual(budget.spent, 0)           # refused calls cost nothing
        self.assertEqual(providers.served_cost, 0)
        self.assertGreater(providers.calls, 0)
        self.assertLess(took, 10)                   # §8: providers answering within a second

    def test_every_call_answered_429_fails_within_the_bound(self):
        result, _, budget, _, active = build(lambda p, m, t, a: 429)
        self.assertFalse(result.succeeded)
        self.assertEqual(budget.spent, 0)
        self.assertLess(active, 10)                 # waiting out a 429 does not count (stage 2)

    def test_extracts_refused_for_one_page_only(self):
        result, providers, budget, _, _ = build(lambda p, m, t, a: 500 if m == "extract" and t == NEWS else None)
        self.assertTrue(result.succeeded)
        self.assertEqual(budget.spent, providers.served_cost)
        self.assertEqual(known(result).get("founded_year"), 2011)

    def test_refused_extracts_everywhere_leave_search_text(self):
        result, providers, budget, took, _ = build(lambda p, m, t, a: 500 if m == "extract" else None)
        self.assertTrue(result.succeeded)
        self.assertEqual(budget.spent, providers.served_cost)
        self.assertLess(took, 10)


class BatchPool(unittest.TestCase):
    def test_batch_stops_all_calls_once_a_call_would_not_fit(self):
        pool = Pool(30)
        first, second = Budget(80, lambda _: None, pool), Budget(80, lambda _: None, pool)
        self.assertTrue(first.reserve(25))
        self.assertFalse(second.reserve(10))        # would pass 30: the batch is closed
        self.assertTrue(pool.closed)
        self.assertFalse(first.reserve(1))          # no cheaper call either
        self.assertEqual((first.remaining, second.remaining, pool.spent), (0, 0, 25))

    def test_builds_in_a_batch_complete_with_what_they_have(self):
        pool = Pool(12)
        runs = []
        threads = [threading.Thread(target=lambda: runs.append(build(lambda *a: None, pool=pool))) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertLessEqual(pool.spent, 12)
        self.assertEqual(pool.spent, sum(b.spent for _, _, b, _, _ in runs))
        self.assertEqual(sum(p.served_cost for _, p, _, _, _ in runs), pool.spent)
        self.assertTrue(pool.closed)
        for result, _, budget, took, _ in runs:
            self.assertLess(took, 10)


if __name__ == "__main__":
    unittest.main()
