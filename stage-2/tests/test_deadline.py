"""§8 time limits: a build starts no call after its gathering window or past its cap,
never abandons a call it started, and still charges an unanswered call (§9)."""
import os
import threading
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("NIMBLE_API_KEY", "test")
os.environ.setdefault("NIMBLE_BASE_URL", "http://127.0.0.1:9/nimble")

from app.builder import Builder  # noqa: E402
from app.providers import Budget, Deadline, Gateway  # noqa: E402


class SlowRouter:
    """Stands in for WebRouter: every call takes `delay` seconds; records when each started."""

    def __init__(self, delay):
        self.delay = delay
        self.starts = []
        self._lock = threading.Lock()
        self.t0 = time.monotonic()

    def _started(self, kind):
        with self._lock:
            self.starts.append((kind, time.monotonic() - self.t0))
        time.sleep(self.delay)

    def search(self, query, **_):
        self._started("search")
        slug = query.split()[0].lower()
        return SimpleNamespace(results=[SimpleNamespace(url=f"https://slow-co.test/{slug}/{i}", title="Slow Co",
                                                        content="Slow Co makes things.", description="")
                                        for i in range(10)])

    def extract(self, urls, **_):
        self._started("extract")
        return SimpleNamespace(documents=[SimpleNamespace(content="Slow Co makes things.")])

    def research(self, query, timeout=None, **_):
        self._started("research")
        raise TimeoutError("research run still going")


class DeadlineTests(unittest.TestCase):
    def build(self, delay, window, cap, call_timeout):
        gateway = Gateway(call_timeout=call_timeout)
        gateway.tavily_enabled = False
        router = SlowRouter(delay)
        gateway._router = router
        spent = []
        budget = Budget(80, spent.append)
        deadline = Deadline(gather_window=window, cap=cap)
        started = time.monotonic()
        result = Builder(gateway, "slow-co.test", budget, lambda: False, deadline).run()
        return result, router, budget, time.monotonic() - started

    def test_no_call_starts_after_window_and_build_ends_before_cap(self):
        result, router, budget, took = self.build(delay=0.2, window=0.5, cap=2.0, call_timeout=0.4)
        self.assertTrue(router.starts)
        self.assertTrue(all(at < 0.5 + 0.05 for _, at in router.starts), router.starts)
        self.assertLess(took, 2.0)
        self.assertTrue(result.succeeded)
        self.assertLessEqual(budget.spent, 80)

    def test_no_call_starts_that_could_outlast_cap(self):
        # Window is long, but a call whose timeout would pass the cap is not started.
        result, router, budget, took = self.build(delay=0.2, window=10, cap=0.5, call_timeout=0.4)
        self.assertTrue(all(at + 0.4 <= 0.5 + 0.05 for _, at in router.starts), router.starts)
        self.assertLess(took, 0.5 + 0.3)

    def test_unanswered_call_keeps_its_cost(self):
        gateway = Gateway(call_timeout=0.4)
        budget = Budget(80, lambda _: None)

        def invoke():
            raise TimeoutError("no answer")
        outcome = gateway.call("nimble", "search", "lite", budget, lambda: False, Deadline(1, 5), invoke)
        self.assertFalse(outcome.ok)
        self.assertEqual(budget.spent, 1)

    def test_deadline_rules(self):
        now = [0.0]
        deadline = Deadline(gather_window=120, cap=270, clock=lambda: now[0])
        self.assertTrue(deadline.may_start(45))
        now[0] = 119
        self.assertTrue(deadline.may_start(45))       # a call started in the window may wait its full 45 s
        now[0] = 121
        self.assertFalse(deadline.may_start(1))       # gathering may stop after 120 s
        now[0] = 0
        self.assertFalse(Deadline(120, 40, clock=lambda: 0.0).may_start(45))


if __name__ == "__main__":
    unittest.main()
