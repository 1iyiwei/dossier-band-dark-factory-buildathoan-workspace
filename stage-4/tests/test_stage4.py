"""Stage 4: investors, origins and corroboration, batches, and a restart with builds running."""
import copy
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("NIMBLE_API_KEY", "test")
os.environ.setdefault("NIMBLE_BASE_URL", "http://127.0.0.1:9/nimble")

from app.builder import Builder  # noqa: E402
from app.candidates import build_all, make_candidate  # noqa: E402
from app.history import change_type  # noqa: E402
from app.passwords import hash_password  # noqa: E402
from app.providers import Budget, Deadline, Gateway, Outcome, Pool  # noqa: E402
from app.store import Store  # noqa: E402
from app.support import supported_investors  # noqa: E402

D = "acme-robotics.test"
T0 = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


class InvestorSupport(unittest.TestCase):
    def check(self, excerpt, names):
        self.assertEqual(supported_investors(excerpt, D), names, excerpt)

    def test_names_by_last_word(self):
        self.check("Investors in Acme Robotics include Northwind Ventures and Bluebird Capital.",
                   ["Northwind Ventures", "Bluebird Capital"])
        self.check("Acme Robotics is backed by Quill Fund.", ["Quill Fund"])   # last word, two words
        self.check("Acme Robotics investor Fund is Northwind.", [])            # a run of one word
        self.check("Acme Robotics opened an office near Northwind Ventures.", [])   # no statement phrase

    def test_run_after_led_by_needs_an_amount(self):
        self.check("Acme Robotics raised $40M in a round led by General Atlantic.", ["General Atlantic"])
        self.check("Acme Robotics is led by Dana Ruiz.", [])
        self.check("Acme Robotics raised $40M, backed by Atlas.", ["Atlas"])   # any length after led by / backed by

    def test_rules_one_to_four(self):
        self.check("Acme Robotics is reportedly backed by Northwind Ventures.", [])
        self.check("Northwind Ventures participated. Acme Robotics grew.", [])   # two sentences
        self.check("Northwind Ventures is an investor.", [])                      # does not name the company


def cand(name, value, url, kind="own", origin=None, true_from="2024-05-02", title=None, published=None):
    return name, make_candidate(value, url, f"Acme Robotics investor {value}.", "nimble", kind, published, "",
                                true_from, title, origin)


def fields_of(*items):
    grouped = {}
    for name, c in items:
        grouped.setdefault(name, []).append(c)
    return build_all(grouped)


class InvestorsField(unittest.TestCase):
    def test_members_and_keys(self):
        f = fields_of(cand("investors", "Bluebird Capital", "https://a.test/1", kind="news", origin="dealwire.test"),
                      cand("investors", "Bluebird Capital", "https://b.test/1", kind="news", origin="registry.test"),
                      cand("investors", "Northwind Ventures", "https://acme-robotics.test/x", kind="own",
                           origin="acme-robotics.test"),
                      cand("investors", "Lone Capital", "https://c.test/1", kind="aggregator", origin="c.test"))["investors"]
        self.assertEqual(f["value"], ["Bluebird Capital", "Northwind Ventures"])
        self.assertEqual(f["status"], "known")
        self.assertEqual({c["value"]: c["selected"] for c in f["candidates"]},
                         {"Bluebird Capital": True, "Northwind Ventures": True, "Lone Capital": False})
        self.assertEqual(f["origins"], ["acme-robotics.test", "dealwire.test", "registry.test"])
        self.assertFalse(f["corroborated"])   # Northwind Ventures has one origin
        self.assertEqual([c["url"] for c in f["citations"]],
                         ["https://a.test/1", "https://b.test/1", "https://acme-robotics.test/x"])

    def test_no_member_is_unknown_but_lists_candidates(self):
        f = fields_of(cand("investors", "Lone Capital", "https://c.test/1", kind="aggregator", origin="c.test"))["investors"]
        self.assertEqual((f["value"], f["status"], f["citations"], f["origins"]), (None, "unknown", [], []))
        self.assertEqual(len(f["candidates"]), 1)

    def test_true_from(self):
        f = fields_of(cand("investors", "A Capital", "https://a.test/1", true_from=None),
                      cand("investors", "A Capital", "https://a.test/2", true_from="2024-01-01"),
                      cand("investors", "B Capital", "https://b.test/1", true_from="2025-01-01"))["investors"]
        self.assertEqual(f["true_from"], "2025-01-01")
        f = fields_of(cand("investors", "A Capital", "https://a.test/1", true_from=None))["investors"]
        self.assertIsNone(f["true_from"])

    def test_change_type(self):
        def field(*pairs):
            return fields_of(*[cand("investors", n, f"https://x.test/{n}", true_from=t) for n, t in pairs])["investors"]
        old = field(("A Capital", "2024-06-01"))
        self.assertEqual(change_type("investors", old, field(("A Capital", "2024-06-01"), ("B Fund", "2024-05-01"))),
                         "correction")
        self.assertEqual(change_type("investors", old, field(("A Capital", "2024-06-01"), ("B Fund", "2024-07-01"))),
                         "change")
        self.assertEqual(change_type("investors", old, field(("B Fund", "2024-01-01"))), "change")   # A is dropped
        self.assertEqual(change_type("investors", fields_of()["investors"], old), "change")


class FakeWeb:
    """Serves pages by URL through search and extract."""

    def __init__(self, pages, hits):
        self.pages, self.hits = pages, hits
        self.extracted = []

    def search(self, query, **_):
        results = [SimpleNamespace(url=u, title=u, content=self.pages[u][:80], description="") for u in self.hits]
        return SimpleNamespace(results=results)

    def extract(self, urls, **_):
        self.extracted.append(urls[0])
        text = self.pages.get(urls[0])
        return SimpleNamespace(documents=[SimpleNamespace(content=text)] if text else [])

    def research(self, query, **_):
        return SimpleNamespace(structured={}, citations=[])


def run_build(pages, hits, pool=None, limit=80):
    gateway = Gateway(call_timeout=2.0)
    gateway.tavily_enabled = False
    web = FakeWeb(pages, hits)
    gateway._router = web
    budget = Budget(limit, lambda _: None, pool)
    result = Builder(gateway, D, budget, lambda: False, Deadline(), "2026-03-01T09:00:00+00:00").run()
    return result, web, budget


def page(header, prose):
    return "\n".join(f"{k}: {v}" for k, v in header.items()) + "\n\n" + prose


class Origins(unittest.TestCase):
    def origin_of(self, pages, url, hits=None):
        result, web, _ = run_build(pages, hits or [url])
        return {c["url"]: c["origin"] for c in result.fields["founded_year"]["candidates"]}[url], result, web

    FOUNDED = "Acme Robotics was founded in 2014."

    def test_registrant_and_first_published_by(self):
        pages = {"https://news.test/a": page({"Kind": "news"}, self.FOUNDED),
                 "https://blog.test/b": page({"Kind": "news", "Registrant": "Pub.test", "First-Published-By": "WIRE.test"},
                                             self.FOUNDED)}
        origin, *_ = self.origin_of(pages, "https://news.test/a")
        self.assertEqual(origin, "news.test")
        origin, *_ = self.origin_of(pages, "https://blog.test/b")
        self.assertEqual(origin, "wire.test")

    def test_canonical_is_followed_and_fetched(self):
        pages = {"https://copy.test/a": page({"Kind": "news", "Canonical": "https://orig.test/a"}, self.FOUNDED),
                 "https://orig.test/a": page({"Kind": "news", "Registrant": "root.test"}, "Nothing here.")}
        origin, _, web = self.origin_of(pages, "https://copy.test/a")
        self.assertEqual(origin, "root.test")
        self.assertIn("https://orig.test/a", web.extracted)
        orig = page({"Kind": "news"}, self.FOUNDED + " Acme Robotics is headquartered in Porto.")
        pages["https://orig.test/a"] = orig
        _, result, _ = self.origin_of(pages, "https://copy.test/a")
        self.assertEqual([c["url"] for c in result.fields["founded_year"]["candidates"]], ["https://copy.test/a"])
        self.assertEqual(result.fields["hq_city"]["candidates"], [])   # an original is not evidence

    def test_unserved_original_and_fourth_hop_give_the_host(self):
        pages = {"https://copy.test/a": page({"Kind": "news", "Canonical": "https://gone.test/a"}, self.FOUNDED)}
        origin, *_ = self.origin_of(pages, "https://copy.test/a")
        self.assertEqual(origin, "gone.test")
        chain = {f"https://h{i}.test/p": page({"Canonical": f"https://h{i + 1}.test/p", "Kind": "news"},
                                              self.FOUNDED if i == 0 else "Nothing.") for i in range(0, 6)}
        origin, *_ = self.origin_of(chain, "https://h0.test/p")
        self.assertEqual(origin, "h4.test")   # follows h1, h2, h3, and would follow a fourth: the host of h4

    def test_lookalike_origin_and_kind(self):
        pages = {"https://acme-robotlcs.test/a": page({"Kind": "own", "Registrant": "acme-robotlcs.test"},
                                                      self.FOUNDED)}
        # Registrant == host of the URL: not a lookalike, but not the company's domain either.
        result, *_ = run_build(pages, list(pages))
        c = result.fields["founded_year"]["candidates"][0]
        self.assertEqual((c["kind"], c["origin"]), ("aggregator", "acme-robotlcs.test"))
        pages = {"https://acme-robotlcs.test/a": page({"Kind": "own", "Registrant": D}, self.FOUNDED)}
        result, *_ = run_build(pages, list(pages))
        c = result.fields["founded_year"]["candidates"][0]
        self.assertEqual((c["kind"], c["origin"]), ("own", D))   # claims the company's own registrant: still not a lookalike
        pages = {"https://acme-robotlcs.test/a": page({"Kind": "own", "Registrant": "elsewhere.test"}, self.FOUNDED)}
        result, *_ = run_build(pages, list(pages))
        c = result.fields["founded_year"]["candidates"][0]
        self.assertEqual((c["kind"], c["origin"]), ("aggregator", D))   # a lookalike: the company's domain

    def test_investors_from_pages(self):
        pages = {"https://a.test/1": page({"Kind": "news"}, "Acme Robotics is backed by Northwind Ventures."),
                 "https://b.test/1": page({"Kind": "news"}, "Acme Robotics investor: Northwind Ventures.")}
        result, *_ = run_build(pages, list(pages))
        f = result.fields["investors"]
        self.assertEqual((f["value"], f["origins"], f["corroborated"]), (["Northwind Ventures"], ["a.test", "b.test"], True))


class Corroboration(unittest.TestCase):
    def run_builds(self, store, *field_sets):
        for index, fields in enumerate(field_sets):
            fields = copy.deepcopy(fields)
            at = T0.replace(day=index + 2)
            store.set_clock(at)
            with store.lock:
                record = store.dossiers.get(D) or store._new_dossier(D)
                from app.builder import BuildResult
                store._complete_ready(record, BuildResult(True, fields, {}), at.isoformat(), 5, f"b{index}")
                store._touch()

    def test_since_is_the_build_that_reached_two_origins(self):
        store = Store(gateway=None)
        store.reset(T0, [])
        one = fields_of(cand("founded_year", 2014, "https://a.test/1", kind="news", origin="a.test"))
        two = fields_of(cand("founded_year", 2014, "https://b.test/1", kind="news", origin="b.test"))
        self.run_builds(store, one, two, one)
        builds = store.dossiers[D]["builds"]
        self.assertEqual([b["fields"]["founded_year"]["corroborated_since"] for b in builds],
                         [None, builds[1]["time"], builds[1]["time"]])   # a.test stands although the second build lacks it
        self.assertEqual(builds[1]["fields"]["founded_year"]["origins"], ["b.test"])
        self.assertFalse(builds[1]["fields"]["founded_year"]["corroborated"])

    def test_a_new_value_starts_with_none(self):
        store = Store(gateway=None)
        store.reset(T0, [])
        a1 = fields_of(cand("founded_year", 2014, "https://a.test/1", kind="news", origin="a.test"),
                       cand("founded_year", 2014, "https://b.test/1", kind="news", origin="b.test"))
        other = fields_of(cand("founded_year", 2015, "https://a.test/1", kind="own", origin="a.test"))
        self.run_builds(store, a1, other, a1)
        builds = store.dossiers[D]["builds"]
        self.assertEqual([b["fields"]["founded_year"]["corroborated_since"] for b in builds],
                         [builds[0]["time"], None, builds[2]["time"]])


class Batches(unittest.TestCase):
    def test_pool_is_shared_and_never_exceeded(self):
        pool = Pool(50)
        budgets = [Budget(80, lambda _: None, pool) for _ in range(3)]
        taken = [b.reserve(20) for b in budgets]
        self.assertEqual(taken, [True, True, False])
        self.assertEqual(budgets[2].remaining, 0)   # the third call would pass 50: the pool is closed
        budgets[0].refund(20)
        self.assertEqual((budgets[2].remaining, pool.spent), (0, 20))
        self.assertFalse(budgets[1].reserve(1))

    def test_batch_view_and_ownership(self):
        class Quiet:
            pass
        store = Store(gateway=Quiet())
        store.reset(T0, [])
        with store.lock:
            store._new_dossier("known.test")["outcome"] = "ready"
        started = []
        store._start_build = lambda record, batch_id=None: started.append(record["domain"]) or (
            store.batches[batch_id]["members"][record["domain"]].update(done=True))
        status, view = store.create_batch("u1", ["known.test", "new.test"], 200)
        self.assertEqual((status, started), (202, ["new.test"]))
        self.assertEqual(view, {"batch_id": "b_1", "state": "done", "budget_units": 200, "spent_units": 0,
                                "dossiers": [{"domain": "known.test", "state": "ready"},
                                             {"domain": "new.test", "state": "failed"}]})
        self.assertIsNone(store.get_batch("u2", "b_1"))
        self.assertIsNone(store.get_batch("u1", "b_9"))


class Restart(unittest.TestCase):
    def test_running_build_ends_failed_with_its_units(self):
        class Gate:
            """A gateway whose calls never end, so the build is running when the process 'stops'."""
            tavily_enabled = False
            call_timeout = 1.0

            @staticmethod
            def _call(provider, budget):
                budget.reserve(1)
                time.sleep(2)
                return Outcome(ok=False, provider=provider, exhausted=True)

            def search(self, provider, query, budget, cancelled, deadline, depth="lite", max_results=10):
                return self._call(provider, budget)

            def extract(self, provider, url, budget, cancelled, deadline, render=False):
                return self._call(provider, budget)

            def research(self, query, schema, budget, cancelled, deadline):
                return self._call("nimble", budget)

        with tempfile.TemporaryDirectory() as directory:
            store = Store(Gate(), directory)
            store.reset(T0, [])
            user, _ = store.add_user("a@b.test", "A", hash_password("correct horse"))
            status, view = store.create_batch(user["id"], [D], 100)
            store._sync()
            deadline = time.time() + 5
            while time.time() < deadline and store.running and next(iter(store.running.values()))["spent"] < 3:
                time.sleep(0.05)
            spent = next(iter(store.running.values()))["spent"]
            self.assertGreaterEqual(spent, 3)
            # The "restart": a new store over the same directory, while the old one is simply abandoned.
            again = Store(Gate(), directory)
            record = again.dossiers[D]
            self.assertIsNone(record["building"])
            self.assertEqual(again.state_of(record), "failed")
            self.assertEqual(record["spent_units"], spent)
            self.assertEqual(again.get_batch(user["id"], "b_1")["state"], "done")
            self.assertEqual(again.get_batch(user["id"], "b_1")["spent_units"], spent)
            self.assertEqual(again.next_batch, 2)


if __name__ == "__main__":
    unittest.main()
