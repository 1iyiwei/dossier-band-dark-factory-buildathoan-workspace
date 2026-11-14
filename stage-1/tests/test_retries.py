"""Refused calls (429/500): retried briefly so a build against fast providers still ends
within 10 s (§8), and a refused bare-domain search is tried again later in the build (§4)."""
import os
import threading
import time
import unittest
from collections import Counter
from types import SimpleNamespace

os.environ.setdefault("NIMBLE_API_KEY", "test")
os.environ.setdefault("NIMBLE_BASE_URL", "http://127.0.0.1:9/nimble")

from app.builder import Builder  # noqa: E402
from app.providers import Budget, Deadline, Gateway  # noqa: E402

DOMAIN = "rate-co.test"
PAGE = "Rate Co was founded in 2011. Rate Co is headquartered in Lisbon."


class Refused(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class ScriptedRouter:
    """Answers each distinct call per `policy(key, attempt)`: None to serve it, else a status to refuse."""

    def __init__(self, policy):
        self.policy = policy
        self.attempts = Counter()
        self.served = []
        self._lock = threading.Lock()

    def _attempt(self, key):
        with self._lock:
            attempt = self.attempts[key]
            self.attempts[key] += 1
        status = self.policy(key, attempt)
        if status is not None:
            raise Refused(status)
        with self._lock:
            self.served.append(key)

    def search(self, query, **_):
        self._attempt(("search", query))
        return SimpleNamespace(results=[SimpleNamespace(url=f"https://{DOMAIN}/about", title="Rate Co",
                                                        content=PAGE, description="")])

    def extract(self, urls, **_):
        self._attempt(("extract", urls[0]))
        return SimpleNamespace(documents=[SimpleNamespace(content=PAGE)])

    def research(self, query, **_):
        self._attempt(("research", query))
        return SimpleNamespace(structured={}, citations=[])


def build(policy):
    gateway = Gateway(call_timeout=2.0)
    gateway.tavily_enabled = False
    router = ScriptedRouter(policy)
    gateway._router = router
    budget = Budget(80, lambda _: None)
    builder = Builder(gateway, DOMAIN, budget, lambda: False, Deadline())
    started = time.monotonic()
    result = builder.run()
    return result, builder, router, budget, time.monotonic() - started


class RetryTests(unittest.TestCase):
    def test_permanent_429_ends_quickly(self):
        result, _, router, budget, took = build(lambda key, attempt: 429)
        self.assertLess(took, 10)
        self.assertFalse(result.succeeded)
        self.assertEqual(budget.spent, 0)
        self.assertFalse(router.served)

    def test_three_429s_then_served_like_the_mock(self):
        result, builder, router, budget, took = build(lambda key, attempt: 429 if attempt < 3 else None)
        self.assertLess(took, 10)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.fields["founded_year"]["value"], 2011)
        self.assertEqual(router.served.count(("search", DOMAIN)), 1)
        self.assertLessEqual(budget.spent, 80)

    def test_refused_domain_search_is_retried_later(self):
        # The first logical domain search is refused on both attempts; a later one is served.
        result, builder, router, _, took = build(
            lambda key, attempt: 500 if key == ("search", DOMAIN) and attempt < 2 else None)
        self.assertEqual(builder.domain_search, "ok")
        self.assertEqual(router.served.count(("search", DOMAIN)), 1)
        self.assertTrue(result.succeeded)


if __name__ == "__main__":
    unittest.main()
