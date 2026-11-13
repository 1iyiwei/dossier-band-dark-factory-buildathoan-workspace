"""One build of a dossier: gather evidence through the providers, then decide each field.

Spending plan, within the 80-unit budget (§9):
  1. Two Nimble `lite` searches (1 unit each): the normalised domain (exactly once per
     build) and the company's name. They list the pages and give each a snippet.
  2. A Nimble extract (1 unit per URL) of every result that looks like it concerns the
     company, for the page's full text.
  3. Only for fields still unknown: one `lite` search per field, naming the company with a
     word of that field, and one Nimble research run (25 units) asking for all six fields.
     New results are extracted as in step 2.
  4. Research claims for unknown fields are checked against their page, extracted if needed.
  5. With budget left and fields still unknown, the remaining results are extracted.
Tavily is used only when Nimble refuses a call and a Tavily key is configured.

A value is asserted only when a cited excerpt supports it by Appendix A (`support.py`).
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .pages import appears_in, citable_sentences, prose_of
from .providers import Budget, Cancelled, Deadline, Gateway
from .support import FIELDS, company_name, names_company, normalise_claim, supported_value, supported_values

log = logging.getLogger("dossier.build")

FIELD_QUERY_WORDS = {
    "legal_name": "legal name",
    "hq_city": "headquarters",
    "ceo": "CEO",
    "founded_year": "founded",
    "headcount_range": "employees",
    "funding_total": "funding raised",
}
RESEARCH_COST = 25
MAX_CITATIONS = 5
SNIPPET_MAY_BE_CUT = 250   # a snippet at least this long may end mid-sentence
WORKERS = 8

RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "legal_name": {"type": ["string", "null"], "description": "Registered legal name"},
        "hq_city": {"type": ["string", "null"], "description": "City of the headquarters"},
        "ceo": {"type": ["string", "null"], "description": "Full name of the chief executive"},
        "founded_year": {"type": ["integer", "null"], "description": "Year founded"},
        "headcount_range": {"type": ["string", "null"], "description": "Employee count range"},
        "funding_total": {"type": ["integer", "null"], "description": "Total equity funding in US dollars"},
    },
    "required": list(FIELDS),
}


@dataclass
class SearchHit:
    url: str
    provider: str
    title: str
    snippet: str
    priority: int


@dataclass
class Page:
    url: str
    provider: str
    prose: str


@dataclass
class Claim:
    field: str
    value: object
    url: str
    excerpt: str


@dataclass
class BuildResult:
    succeeded: bool
    fields: dict = field(default_factory=dict)


def empty_fields() -> dict:
    return {name: {"value": None, "status": "unknown", "citations": []} for name in FIELDS}


class Builder:
    def __init__(self, gateway: Gateway, domain: str, budget: Budget, cancelled, deadline: Deadline):
        self.gateway = gateway
        self.domain = domain
        self.name = company_name(domain).title()
        self.budget = budget
        self.cancelled = cancelled
        self.deadline = deadline
        self.hits: dict[str, SearchHit] = {}        # by URL, in the order first returned
        self.pages: dict[str, Page] = {}            # pages gathered from search results
        self.cited_pages: dict[str, Page] = {}      # pages gathered only to check a research claim
        self.attempted: set[str] = set()
        self.claims: list[Claim] = []
        self.successes = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the plan

    def run(self) -> BuildResult:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            self.pool = pool
            try:
                self._searches([self.domain, self.name])
                self._gather(max_priority=1)
                fields = self._decide()
                unknown = self._unknown(fields)
                if unknown:
                    research = None
                    if self.budget.remaining >= RESEARCH_COST + len(unknown):
                        research = self.pool.submit(self._research)
                    self._searches([f"{self.name} {FIELD_QUERY_WORDS[f]}" for f in unknown])
                    if research is not None:
                        research.result()
                    self._gather(max_priority=1)
                    fields = self._decide()
                    unknown = self._unknown(fields)
                if unknown and self.claims:
                    self._check_claims(unknown)
                    fields = self._decide()
                    unknown = self._unknown(fields)
                if unknown:
                    self._gather(max_priority=2)
                    fields = self._decide()
            except Cancelled:
                return BuildResult(succeeded=False)
        return BuildResult(succeeded=self.successes > 0, fields=fields)

    @staticmethod
    def _unknown(fields: dict) -> list[str]:
        return [name for name in FIELDS if fields[name]["value"] is None]

    def _parallel(self, tasks) -> None:
        for future in [self.pool.submit(task) for task in tasks]:
            future.result()

    # ------------------------------------------------------------------ calls

    def _searches(self, queries: list[str]) -> None:
        """Run the searches side by side; their results join the hits in query order."""
        futures = [self.pool.submit(self._search, query) for query in queries]
        for future in futures:
            for hit in future.result():
                self.hits.setdefault(hit.url, hit)

    def _search(self, query: str) -> list[SearchHit]:
        outcome = self.gateway.search("nimble", query, self.budget, self.cancelled, self.deadline)
        if outcome.refused and self.gateway.tavily_enabled:
            outcome = self.gateway.search("tavily", query, self.budget, self.cancelled, self.deadline)
        if not outcome.ok:
            log.info("search %r for %s failed: %s", query, self.domain, outcome.errors[-1:] or "budget")
            return []
        self._succeeded()
        return [SearchHit(url, outcome.provider, title, snippet, self._priority(url, title, snippet))
                for url, title, snippet in outcome.value]

    def _succeeded(self) -> None:
        with self._lock:
            self.successes += 1

    def _priority(self, url: str, title: str, snippet: str) -> int:
        host = (urlparse(url).hostname or "").lower()
        if host == self.domain or host.endswith("." + self.domain):
            return 0
        if names_company(title, self.domain) or names_company(snippet, self.domain):
            return 1
        return 2

    def _extract(self, url: str) -> Page | None:
        outcome = self.gateway.extract("nimble", url, self.budget, self.cancelled, self.deadline)
        if outcome.refused and self.gateway.tavily_enabled:
            outcome = self.gateway.extract("tavily", url, self.budget, self.cancelled, self.deadline)
        if not outcome.ok or not outcome.value:
            return None
        self._succeeded()
        return Page(url, outcome.provider, prose_of(outcome.value))

    def _gather(self, max_priority: int) -> None:
        """Extract every search result up to the priority, best first, while the budget lasts."""
        order = sorted((h for h in list(self.hits.values()) if h.url not in self.attempted),
                       key=lambda h: h.priority)
        wanted = [h.url for h in order if h.priority <= max_priority]
        self.attempted.update(wanted)

        def one(url):
            page = self._extract(url)
            if page is not None:
                self.pages[url] = page
        self._parallel([lambda u=u: one(u) for u in wanted])

    def _research(self) -> None:
        query = (f"Company profile of {self.domain}: legal_name, hq_city, ceo, founded_year, "
                 f"headcount_range, funding_total")
        outcome = self.gateway.research(query, RESEARCH_SCHEMA, self.budget, self.cancelled, self.deadline)
        if not outcome.ok:
            log.info("research for %s failed: %s", self.domain, outcome.errors[-1:] or "budget")
            return
        self._succeeded()
        response = outcome.value
        structured = response.structured if isinstance(response.structured, dict) else {}
        for citation in response.citations:
            name = (citation.field or "").removeprefix("$.")
            if name not in FIELDS or structured.get(name) is None:
                continue
            excerpts = list(citation.extra.get("excerpts") or []) or [citation.snippet]
            for excerpt in excerpts:
                if isinstance(excerpt, str) and excerpt.strip() and citation.url:
                    self.claims.append(Claim(name, structured[name], citation.url, excerpt))

    def _check_claims(self, unknown: list[str]) -> None:
        """Fetch the page behind each claim for an unknown field, to confirm the excerpt is its prose."""
        urls = []
        for claim in self.claims:
            if claim.field in unknown and claim.url not in self.pages and claim.url not in urls:
                urls.append(claim.url)

        def one(url):
            page = self._extract(url)
            if page is not None:
                # A search result is a page of the evidence; anything else backs only its claim.
                (self.pages if url in self.hits else self.cited_pages)[url] = page
        self._parallel([lambda u=u: one(u) for u in urls])

    # ------------------------------------------------------------------ deciding

    def _decide(self) -> dict:
        """Each field from the evidence gathered so far: the best-supported value and its citations."""
        candidates: dict[str, list[tuple[object, dict]]] = {name: [] for name in FIELDS}

        for url, hit in list(self.hits.items()):
            page = self.pages.get(url)
            if page is not None:
                sentences, provider = citable_sentences(page.prose), page.provider
            else:
                # A lite snippet is the start of the page's prose, and may stop mid-sentence.
                cut = len(hit.snippet) >= SNIPPET_MAY_BE_CUT
                sentences, provider = citable_sentences(hit.snippet, drop_last=cut), hit.provider
            for sentence in sentences:
                for name, value in supported_values(sentence, self.domain).items():
                    candidates[name].append((value, {"url": url, "excerpt": sentence, "provider": provider}))

        for claim in self.claims:
            value = self._asserted(claim)
            if value is not None:
                candidates[claim.field].append(
                    (value, {"url": claim.url, "excerpt": " ".join(claim.excerpt.split()), "provider": "nimble"}))

        fields = {}
        for name in FIELDS:
            fields[name] = self._choose(candidates[name])
        return fields

    def _asserted(self, claim: Claim):
        """The value a research claim asserts: only when its excerpt supports the claimed value."""
        value = supported_value(claim.excerpt, claim.field, self.domain)
        if value is None or len(" ".join(claim.excerpt.split())) > 500:
            return None
        claimed = normalise_claim(claim.field, claim.value)
        if claimed is None:
            return None
        same = (value.casefold() == claimed.casefold()) if isinstance(value, str) and isinstance(claimed, str) \
            else value == claimed
        if not same:
            return None
        page = self.pages.get(claim.url) or self.cited_pages.get(claim.url)
        if page is not None and not appears_in(claim.excerpt, page.prose):
            return None   # not in the page's prose (a header line, or text the page does not hold)
        return value

    @staticmethod
    def _choose(candidates: list[tuple[object, dict]]) -> dict:
        if not candidates:
            return {"value": None, "status": "unknown", "citations": []}
        counts: dict = {}
        for value, citation in candidates:
            counts.setdefault(value, set()).add((citation["url"], citation["excerpt"]))
        best = max(counts, key=lambda v: len(counts[v]))   # ties: the first value found
        citations, seen = [], set()
        for value, citation in candidates:
            key = (citation["url"], citation["excerpt"])
            if value == best and key not in seen:
                seen.add(key)
                citations.append(citation)
            if len(citations) == MAX_CITATIONS:
                break
        return {"value": best, "status": "known", "citations": citations}
