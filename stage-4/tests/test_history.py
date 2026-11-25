"""Stage 3: two times, history, feed, as_of, values and restarts, driven through the store without providers."""
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.builder import BuildResult  # noqa: E402
from app.candidates import build_all, make_candidate  # noqa: E402
from app.history import values_at  # noqa: E402
from app.passwords import hash_password  # noqa: E402
from app.store import Store  # noqa: E402

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
DOMAIN = "acme.test"


def cand(name, value, url, true_from, title=None, kind="own", published=None):
    return name, make_candidate(value, url, f"{value} excerpt", "nimble", kind, published, "", true_from, title)


def build(*items, urls=()):
    """A build result from (field, candidate) pairs; `urls` names pages gathered without candidates."""
    grouped, versions = {}, {}
    for name, c in items:
        grouped.setdefault(name, []).append(c)
        page = versions.setdefault(c["url"], {"true_from": c["true_from"], "candidates": []})
        page["candidates"].append({"field": name, **{k: c[k] for k in
                                   ("title", "value", "excerpt", "provider", "kind", "published_at", "origin") if k in c}})
    for url, true_from in urls:
        versions[url] = {"true_from": true_from, "candidates": []}
    return BuildResult(True, build_all(grouped), versions)


class Harness:
    def __init__(self, state_dir=None):
        self.store = Store(gateway=None, state_dir=state_dir)
        self.store.reset(T0, [])

    def run(self, result, at):
        """Complete one build at the given time, the way a finished background build does."""
        store = self.store
        store.set_clock(at)
        with store.lock:
            record = store.dossiers.get(DOMAIN) or store._new_dossier(DOMAIN)
            store._complete_ready(record, result, at.isoformat(), 10, f"b{len(record['builds'])}")
            record["spent_units"] += 10
            record["base_spent"] = record["spent_units"]
            store._touch()
        store._sync()


class ChangeTests(unittest.TestCase):
    def test_initial_change_correction_and_feed(self):
        h = Harness()
        h.run(build(cand("ceo", "Dana", "https://a.test/1", "2021-04-01")), T0)
        self.assertEqual(h.store.changes(0, 50), {"changes": [], "has_more": False})
        self.assertEqual([e["type"] for e in h.store.history(DOMAIN)["fields"]["ceo"]], ["initial"])
        later = T0.replace(month=4)
        h.run(build(cand("ceo", "Lee", "https://a.test/1", "2026-03-20")), later)
        feed = h.store.changes(0, 50)["changes"]
        self.assertEqual([(e["seq"], e["field"], e["type"], e["from"], e["to"], e["true_from"]) for e in feed],
                         [(1, "ceo", "change", "Dana", "Lee", "2026-03-20")])
        h.run(build(cand("ceo", "Kim", "https://a.test/1", "2026-01-01")), later.replace(month=5))
        self.assertEqual(h.store.changes(0, 50)["changes"][-1]["type"], "correction")
        self.assertEqual(h.store.changes(1, 1), {"changes": [h.store.changes(0, 50)["changes"][1]], "has_more": False})
        # The same value again adds nothing, even when its true_from differs; learned_at stays.
        h.run(build(cand("ceo", "Kim", "https://a.test/1", "2025-01-01")), later.replace(month=6))
        self.assertEqual(len(h.store.changes(0, 50)["changes"]), 2)
        view = h.store.view(DOMAIN)["fields"]["ceo"]
        self.assertEqual((view["true_from"], view["learned_at"]), ("2025-01-01", later.replace(month=5).isoformat()))

    def test_unknown_field_first_value_is_a_change_and_disappearing_is_a_change(self):
        h = Harness()
        h.run(build(cand("ceo", "Dana", "https://a.test/1", None)), T0)
        h.run(build(cand("ceo", "Dana", "https://a.test/1", None), cand("hq_city", "Lisbon", "https://a.test/1", None)),
              T0.replace(month=4))
        h.run(build(cand("hq_city", "Lisbon", "https://a.test/1", None)), T0.replace(month=5))
        types = [(e["field"], e["type"], e["from"], e["to"]) for e in h.store.changes(0, 50)["changes"]]
        self.assertEqual(types, [("hq_city", "change", None, "Lisbon"), ("ceo", "change", "Dana", None)])
        self.assertEqual(h.store.history(DOMAIN)["fields"]["ceo"][-1]["citations"], [])

    def test_executives_typed_by_title(self):
        h = Harness()
        h.run(build(cand("ceo", "Dana", "https://a.test/1", None)), T0)
        h.run(build(cand("executives", "Ana Silva", "https://a.test/t", "2025-09-01", "cfo"),
                    cand("executives", "Ben Okafor", "https://a.test/t", "2025-09-01", "cto")), T0.replace(month=4))
        e = h.store.view(DOMAIN)["fields"]["executives"]
        self.assertEqual(e["value"], [{"title": "cfo", "name": "Ana Silva"}, {"title": "cto", "name": "Ben Okafor"}])
        self.assertEqual(e["true_from"], "2025-09-01")
        self.assertEqual(h.store.changes(0, 50)["changes"][0]["type"], "change")
        # cfo corrected (earlier true_from), cto dropped: a title differing without being a correction.
        h.run(build(cand("executives", "Cy Lund", "https://a.test/t", "2025-08-01", "cfo")), T0.replace(month=5))
        self.assertEqual(h.store.changes(0, 50)["changes"][-1]["type"], "change")
        h.run(build(cand("executives", "Di Wu", "https://a.test/t", "2025-07-01", "cfo")), T0.replace(month=6))
        self.assertEqual(h.store.changes(0, 50)["changes"][-1]["type"], "correction")

    def test_as_of_and_spent(self):
        h = Harness()
        h.run(build(cand("ceo", "Dana", "https://a.test/1", None)), T0)
        h.run(build(cand("ceo", "Lee", "https://a.test/1", None)), T0.replace(month=4))
        self.assertIsNone(h.store.view_as_of(DOMAIN, T0.replace(day=1, hour=8)))
        first = h.store.view_as_of(DOMAIN, T0.replace(month=3, day=15))
        self.assertEqual((first["fields"]["ceo"]["value"], first["spent_units"], first["state"]), ("Dana", 10, "ready"))
        second = h.store.view_as_of(DOMAIN, T0.replace(month=4))
        self.assertEqual((second["fields"]["ceo"]["value"], second["spent_units"]), ("Lee", 20))


class ValuesTests(unittest.TestCase):
    def values(self, builds, true_at):
        return values_at(builds, true_at)

    def test_replacement_and_ending(self):
        h = Harness()
        url = "https://a.test/1"
        h.run(build(cand("ceo", "Dana", url, "2021-04-01")), T0)
        h.run(build(cand("ceo", "Lee", url, "2026-03-20")), T0.replace(month=4))
        builds = h.store.dossiers[DOMAIN]["builds"]
        self.assertEqual(self.values(builds, "2025-06-01")["ceo"]["value"], "Dana")
        self.assertEqual(self.values(builds, "2026-03-20")["ceo"]["value"], "Lee")
        self.assertIsNone(self.values(builds, "2020-01-01")["ceo"]["value"])
        # A later version with an earlier-or-equal true_from replaces the older one entirely.
        h.run(build(cand("ceo", "Kim", url, "2021-04-01")), T0.replace(month=5))
        builds = h.store.dossiers[DOMAIN]["builds"]
        self.assertEqual(self.values(builds, "2025-06-01")["ceo"]["value"], "Kim")
        self.assertEqual(self.values(builds, "2025-06-01")["ceo"]["true_from"], "2021-04-01")

    def test_empty_version_ends_earlier_one_and_null_replaces_all(self):
        h = Harness()
        url = "https://a.test/1"
        h.run(build(cand("ceo", "Dana", url, "2021-04-01")), T0)
        h.run(build(cand("hq_city", "Lisbon", "https://a.test/2", "2020-01-01"), urls=[(url, "2023-01-01")]),
              T0.replace(month=4))
        builds = h.store.dossiers[DOMAIN]["builds"]
        self.assertEqual(self.values(builds, "2022-01-01")["ceo"]["value"], "Dana")
        self.assertIsNone(self.values(builds, "2023-01-01")["ceo"]["value"])
        h.run(build(urls=[(url, None)]), T0.replace(month=5))
        builds = h.store.dossiers[DOMAIN]["builds"]
        self.assertIsNone(self.values(builds, "2022-01-01")["ceo"]["value"])

    def test_executives_value_from_candidates_at_date(self):
        h = Harness()
        h.run(build(cand("executives", "Ana Silva", "https://a.test/t", "2025-09-01", "cfo")), T0)
        builds = h.store.dossiers[DOMAIN]["builds"]
        late = self.values(builds, "2026-01-01")["executives"]
        self.assertEqual(late["value"], [{"title": "cfo", "name": "Ana Silva"}])
        self.assertEqual(late["true_from"], "2025-09-01")
        self.assertEqual(self.values(builds, "2025-01-01")["executives"],
                         {"value": None, "true_from": None, "citations": []})


class DurabilityTests(unittest.TestCase):
    def test_state_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            h = Harness(directory)
            h.store.reset(T0, [])
            created = h.store.add_user("a@b.test", "Ada", hash_password("correct horse"))
            self.assertIsNotNone(created)
            h.run(build(cand("ceo", "Dana", "https://a.test/1", None)), T0)
            h.run(build(cand("ceo", "Lee", "https://a.test/1", None)), T0.replace(month=4))
            before = h.store.export()
            clock = h.store.now()
            reborn = Store(gateway=None, state_dir=directory)
            self.assertEqual(reborn.export(), before)
            self.assertEqual(reborn.now(), clock)
            self.assertEqual(reborn.next_seq, 2)
            self.assertEqual(reborn.view_as_of(DOMAIN, T0)["fields"]["ceo"]["value"], "Dana")

    def test_import_of_own_export_round_trips(self):
        h = Harness()
        h.run(build(cand("ceo", "Dana", "https://a.test/1", None)), T0)
        h.run(build(cand("ceo", "Lee", "https://a.test/1", None)), T0.replace(month=4))
        exported = h.store.export()
        other = Harness()
        other.store.import_(exported)
        self.assertEqual(other.store.export(), exported)


if __name__ == "__main__":
    unittest.main()
