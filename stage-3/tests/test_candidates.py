"""The selection rule, status, page kind/time and the upgrade of a stage-1 export (stage 2)."""
import os
import unittest

os.environ.setdefault("NIMBLE_API_KEY", "test")
os.environ.setdefault("NIMBLE_BASE_URL", "http://127.0.0.1:9/nimble")

from app.candidates import build_field, make_candidate, page_kind, published_at  # noqa: E402
from app.pages import header_of, looks_dynamic  # noqa: E402
from app.store import _parse_export, _upgraded_field  # noqa: E402

RETRIEVED = "2026-03-01T09:00:00+00:00"


def cand(value, url, kind, published=None, provider="nimble"):
    return make_candidate(value, url, f"Acme CEO: {value}.", provider, kind, published, RETRIEVED)


class SelectionTests(unittest.TestCase):
    def order(self, *candidates):
        field = build_field(list(candidates))
        return [(c["value"], c["selected"]) for c in field["candidates"]], field

    def test_authority_beats_recency(self):
        ranked, field = self.order(
            cand("B", "https://z.test/1", "aggregator", "2026-02-20T00:00:00+00:00"),
            cand("A", "https://a.test/1", "own", "2020-01-01T00:00:00+00:00"),
            cand("C", "https://m.test/1", "news", "2026-03-01T00:00:00+00:00"))
        self.assertEqual(ranked, [("A", True), ("C", False), ("B", False)])
        self.assertEqual((field["value"], field["status"]), ("A", "contested"))

    def test_own_and_filing_rank_equal_so_recency_decides(self):
        ranked, _ = self.order(cand("old", "https://a.test/1", "own", "2025-01-01T00:00:00+00:00"),
                               cand("new", "https://b.test/1", "filing", "2026-01-01T00:00:00+00:00"))
        self.assertEqual(ranked[0], ("new", True))

    def test_recency_compares_instants_not_text(self):
        ranked, _ = self.order(cand("earlier", "https://a.test/1", "news", "2026-01-01T01:00:00+02:00"),
                               cand("later", "https://b.test/1", "news", "2026-01-01T00:00:00+00:00"))
        self.assertEqual(ranked[0], ("later", True))     # 00:00Z is after 23:00Z the day before

    def test_missing_time_ranks_below_any_time_of_the_same_authority(self):
        ranked, _ = self.order(cand("none", "https://a.test/1", "news", None),
                               cand("dated", "https://z.test/1", "news", "1999-01-01T00:00:00+00:00"))
        self.assertEqual(ranked[0], ("dated", True))

    def test_url_then_provider_then_value(self):
        ranked, _ = self.order(cand("y", "https://b.test/", "news", None), cand("x", "https://a.test/", "news", None))
        self.assertEqual(ranked[0], ("x", True))
        ranked, field = self.order(cand("t", "https://a.test/", "news", None, "tavily"),
                                   cand("n", "https://a.test/", "news", None, "nimble"))
        self.assertEqual(ranked[0], ("n", True))
        ranked, _ = self.order(cand(2015, "https://a.test/", "news", None), cand(999, "https://a.test/", "news", None))
        self.assertEqual(ranked[0], (999, True))          # integers compare as numbers: 999 < 2015

    def test_status_and_citations(self):
        same = build_field([cand("A", "https://a.test/1", "own"), cand("A", "https://b.test/1", "news")])
        self.assertEqual(same["status"], "known")
        self.assertEqual([c["url"] for c in same["citations"]], ["https://a.test/1", "https://b.test/1"])
        mixed = build_field([cand("A", "https://a.test/1", "own"), cand("B", "https://b.test/1", "own"),
                             cand("A", "https://c.test/1", "news")])
        self.assertEqual((mixed["value"], mixed["status"]), ("A", "contested"))
        self.assertEqual([c["url"] for c in mixed["citations"]], ["https://a.test/1", "https://c.test/1"])
        self.assertEqual(build_field([]), {"value": None, "status": "unknown", "true_from": None, "learned_at": None,
                                         "citations": [], "candidates": []})

    def test_no_candidate_is_shared_between_calls(self):
        inputs = [cand("A", "https://a.test/1", "own")]
        build_field(inputs)
        self.assertFalse(inputs[0]["selected"])


class PageTests(unittest.TestCase):
    def test_kind(self):
        self.assertEqual(page_kind("filing", "https://x.test/", "acme.test"), "filing")
        self.assertEqual(page_kind(None, "https://www.Acme.test./about", "acme.test"), "own")
        self.assertEqual(page_kind("blog", "https://acme.test/", "acme.test"), "own")
        self.assertEqual(page_kind(None, "https://blog.acme.test/", "acme.test"), "aggregator")
        self.assertEqual(page_kind("News", "https://other.test/", "acme.test"), "aggregator")

    def test_published(self):
        self.assertEqual(published_at("2026-02-20T00:00:00Z"), "2026-02-20T00:00:00+00:00")
        self.assertEqual(published_at("2026-02-20T01:00:00+02:00"), "2026-02-20T01:00:00+02:00")
        self.assertIsNone(published_at("2026-02-20"))
        self.assertIsNone(published_at("yesterday"))
        self.assertIsNone(published_at(None))

    def test_header_and_dynamic_hint(self):
        text = "Kind: news\nPublished: 2026-02-20T00:00:00Z\n\nBody: not a header."
        self.assertEqual(header_of(text), {"Kind": "news", "Published": "2026-02-20T00:00:00Z"})
        self.assertEqual(header_of("No header here"), {})
        self.assertTrue(looks_dynamic("Numbers shown here update in real time."))
        self.assertFalse(looks_dynamic("Acme lives in Lisbon."))


class ImportTests(unittest.TestCase):
    def stage1_export(self):
        field = {"value": "Dana Ruiz", "status": "known", "citations": [
            {"url": "https://acme.test/about", "excerpt": "Dana Ruiz has led Acme as chief executive.", "provider": "nimble"}]}
        empty = {"value": None, "status": "unknown", "citations": []}
        fields = {n: dict(empty) for n in ("legal_name", "hq_city", "founded_year", "headcount_range", "funding_total")}
        fields["ceo"] = field
        return {"track": "dossier", "format_version": 1, "state": {
            "users": [], "tokens": {}, "idempotency": [], "next_dossier": 2,
            "dossiers": [{"dossier_id": "d_1", "domain": "acme.test", "state": "ready", "fields": fields,
                          "researched_at": RETRIEVED, "spent_units": 34}]}}

    def test_stage1_field_gains_candidates_from_its_citations(self):
        dossiers = _parse_export(self.stage1_export())[3]
        ceo = dossiers["acme.test"]["fields"]["ceo"]
        self.assertEqual(ceo["status"], "known")
        [candidate] = ceo["candidates"]
        self.assertEqual((candidate["value"], candidate["kind"], candidate["published_at"], candidate["retrieved_at"],
                          candidate["selected"]), ("Dana Ruiz", None, None, RETRIEVED, True))
        self.assertEqual(ceo["citations"], [{"url": "https://acme.test/about", "provider": "nimble",
                                             "excerpt": "Dana Ruiz has led Acme as chief executive."}])
        self.assertEqual(dossiers["acme.test"]["fields"]["hq_city"]["candidates"], [])

    def test_stage2_export_is_kept_as_is(self):
        field = _upgraded_field("ceo", self.stage1_export()["state"]["dossiers"][0]["fields"]["ceo"], RETRIEVED)
        self.assertEqual(_upgraded_field("ceo", field, RETRIEVED), field)


if __name__ == "__main__":
    unittest.main()
