"""One build of a dossier: gather evidence through the providers, then decide each field.

Spending plan, within the 80-unit budget (§9):
  1. Side by side: lite searches (1 unit each) for the normalised domain (exactly once per
     build), the company's name and one wording of each field, and a Nimble research run
     (25 units) asking for all six fields, whose citations name pages that search never returns.
  2. A Nimble extract of each page they name: the pages research cites first, then the
     search results that look like they concern the company. A page on the company's own host
     is loaded in a browser (`render`, 3 units), others are extracted plain (1 unit).
  3. Pages that say their figures are filled in by a browser are loaded in a browser too, so
     that candidates come from the text a browser shows (stage 2, Page text); then the other
     own/filing pages, while the budget lasts.
  4. Whatever budget is left goes to fields without a candidate, round after round: further
     `lite` searches with other wordings of each field (and extracts of what they find).
When every provider refuses extracts, no more are attempted in that build: a Nimble `deep`
search (15 units, whole page texts) naming the domain replaces step 2, the field
searches of step 1 are cheap `lite` probes, and step 4 repeats as `deep` (or, when under
15 units remain, `fast`) the probe whose results hold the most relevant pages still
without text.
Tavily is used only when Nimble refuses a call and a Tavily key is configured.

Every page of the evidence yields one candidate per value it supports for a field, by
Appendix A (`support.py`); `candidates.py` ranks them and decides each field.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .candidates import build_field, make_candidate, page_kind, published_at
from .pages import citable_sentences, header_of, looks_dynamic, prose_of
from .providers import Budget, Cancelled, Deadline, Gateway
from .support import FIELDS, company_name, names_company, supported_values

log = logging.getLogger("dossier.build")

# Wordings of each field for the searches that name the company; later rounds use later ones.
FIELD_QUERY_WORDS = {
    "legal_name": ("legal name", "registered name", "legal entity"),
    "hq_city": ("headquarters", "headquartered in", "based in"),
    "ceo": ("CEO", "chief executive", "chief executive officer"),
    "founded_year": ("founded", "established", "incorporated"),
    "headcount_range": ("employees", "staff", "workforce"),
    "funding_total": ("funding raised", "investment", "raised"),
}
RESEARCH_COST = 25
RENDER_COST = 3
DEEP_SEARCH_COST = 15
FAST_SEARCH_COST = 5
PARTIAL_MAY_BE_CUT = 1400  # a `fast` result's truncated page body this long may end mid-sentence
WORKERS = 12

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
    """The text a provider served for a page, header lines included."""
    url: str
    provider: str
    text: str
    rendered: bool = False   # the text a browser shows once the page has loaded

    @property
    def prose(self) -> str:
        return prose_of(self.text)


@dataclass
class BuildResult:
    succeeded: bool
    fields: dict = field(default_factory=dict)


def empty_fields() -> dict:
    return {name: {"value": None, "status": "unknown", "citations": [], "candidates": []} for name in FIELDS}


class Builder:
    def __init__(self, gateway: Gateway, domain: str, budget: Budget, cancelled, deadline: Deadline,
                 retrieved_at: str = "1970-01-01T00:00:00+00:00"):
        self.gateway = gateway
        self.domain = domain
        self.retrieved_at = retrieved_at
        self.name = company_name(domain).title()
        self.domain_variant = f"{domain} {self.name}"   # finds what the domain query finds
        self.budget = budget
        self.cancelled = cancelled
        self.deadline = deadline
        self.hits: dict[str, SearchHit] = {}        # by URL, in the order first returned
        self.pages: dict[str, Page] = {}            # pages whose text was gathered
        self.cited: list[str] = []                  # URLs the research claims cite, in claim order
        self.attempted: set[str] = set()
        self.rendered_tried: set[str] = set()       # pages already loaded in a browser, or tried
        self.successes = 0
        self.extract_down = False                   # every provider refused an extract this build
        self.domain_search = None                   # "ok", "refused" or "unanswered"
        self.research_state = None                  # "ok", "refused" or "unanswered"
        self.partials: dict[str, tuple[str, str]] = {}   # url -> (provider, truncated served text)
        self.query_urls: dict[str, list[str]] = {}  # query -> URLs its search returned
        self.query_field: dict[str, str] = {}       # field query -> its field
        self.searched: set[tuple[str, str]] = set() # (query, depth) already tried
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the plan

    def run(self) -> BuildResult:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            self.pool = pool
            try:
                research = None
                if self.budget.remaining >= RESEARCH_COST:
                    research = self.pool.submit(self._research)
                self._searches([self.domain, self.name] + [self._field_query(f, 0) for f in FIELDS])
                if research is not None:
                    research.result()
                self._gather(max_priority=1)
                if self.extract_down:
                    # No page text from extracts: a deep search serves whole pages instead. It
                    # names the domain, which ranks the company's pages first, but is not the bare
                    # domain, whose search is made only once.
                    self._searches([self.domain_variant], depth="deep")
                self._retry_domain_search()
                # Browser text of the pages most likely to decide a field comes before extracts of
                # results that do not look like they concern the company (search noise).
                self._render_dynamic()
                self._gather(max_priority=2)
                self._render_dynamic()
                fields = self._decide()
                fields = self._spend_remaining(fields)
            except Cancelled:
                return BuildResult(succeeded=False)
        return BuildResult(succeeded=self.successes > 0, fields=fields)

    def _field_query(self, field_name: str, round_: int) -> str | None:
        words = FIELD_QUERY_WORDS[field_name]
        if round_ >= len(words):
            return None
        query = f"{self.name} {words[round_]}"
        self.query_field.setdefault(query, field_name)
        return query

    def _spend_remaining(self, fields: dict) -> dict:
        """Rounds of further searches for the fields without a candidate, while the budget lasts.

        Each round runs queries not tried before, so the loop ends: when every field has a
        candidate, the budget or the gathering window runs out, or nothing new is left to ask.
        """
        if self.research_state == "refused" and self.budget.remaining >= RESEARCH_COST:
            # A refused run cost nothing; the pages it cites are evidence too.
            self._research()
            self._gather(max_priority=2)
            fields = self._decide()
        round_ = 1
        while True:
            unknown = self._unknown(fields)
            if not unknown or self.budget.remaining <= 0:
                return fields
            # Rotate the order so that, when the budget runs short, no field is always last.
            shift = round_ % len(unknown)
            unknown = unknown[shift:] + unknown[:shift]
            progressed = False
            if self.extract_down:
                progressed = self._fetch_text_by_search(unknown)
            if not progressed:
                queries = [q for q in (self._field_query(f, round_) for f in unknown)
                           if q is not None and (q, "lite") not in self.searched]
                if not queries and round_ >= max(len(w) for w in FIELD_QUERY_WORDS.values()):
                    return fields
                if queries:
                    self._searches(queries)
                    self._gather(max_priority=2)
                    self._render_dynamic()
                    progressed = True
                round_ += 1
            if not progressed:
                continue
            fields = self._decide()
            if self.deadline.elapsed() >= self.deadline.gather_window:
                return fields

    def _fetch_text_by_search(self, unknown: list[str]) -> bool:
        """With extracts refused: repeat as deep (or fast) the probe that would bring the most text.

        A probe is a lite search already run; the same query at a deeper level returns the same
        pages with their text. Probes for unknown fields come first, then the one whose results
        include the most relevant pages still without full text.
        """
        if self.budget.remaining >= DEEP_SEARCH_COST:
            depth = "deep"
        elif self.budget.remaining >= FAST_SEARCH_COST:
            depth = "fast"
        else:
            return False
        best, best_key = None, None
        for query, urls in self.query_urls.items():
            if query == self.domain:
                query = self.domain_variant   # the bare domain is searched only once
            if (query, depth) in self.searched or (query, "deep") in self.searched:
                continue
            missing = [u for u in urls if u not in self.pages and self.hits[u].priority <= 1
                       and (depth == "deep" or u not in self.partials)]
            if not missing:
                continue
            key = (self.query_field.get(query) in unknown, len(missing))
            if best_key is None or key > best_key:
                best, best_key = query, key
        if best is None:
            return False
        self._searches([best], depth=depth)
        return True

    def _retry_domain_search(self) -> None:
        """§4: every build makes one search, answered without error, whose query is the bare domain.

        A refused attempt does not count, so it is tried again later in the build. One that went
        unanswered may have been served, so it is never repeated.
        """
        if self.domain_search == "refused":
            self._searches([self.domain])

    @staticmethod
    def _unknown(fields: dict) -> list[str]:
        return [name for name in FIELDS if not fields[name]["candidates"]]

    def _parallel(self, tasks) -> None:
        for future in [self.pool.submit(task) for task in tasks]:
            future.result()

    # ------------------------------------------------------------------ calls

    def _searches(self, queries: list[str], depth: str = "lite") -> None:
        """Run the searches side by side; their results join the hits in query order.

        A `deep` search serves each result's whole text, which is kept as the page; a `fast`
        one serves the start of it, kept until the whole text arrives.
        """
        self.searched.update((query, depth) for query in queries)
        futures = [self.pool.submit(self._search, query, depth) for query in queries]
        for query, future in zip(queries, futures):
            hits, provider = future.result()
            if hits and depth == "lite":
                self.query_urls.setdefault(query, [hit.url for hit in hits])
            for hit in hits:
                self.hits.setdefault(hit.url, hit)
                if depth == "deep" and hit.url not in self.pages and hit.snippet:
                    self.pages[hit.url] = Page(hit.url, provider, hit.snippet)
                elif depth == "fast" and hit.snippet:
                    self.partials.setdefault(hit.url, (provider, hit.snippet))

    def _search(self, query: str, depth: str) -> tuple[list[SearchHit], str]:
        outcome = self.gateway.search("nimble", query, self.budget, self.cancelled, self.deadline, depth=depth)
        # Tavily's searches cost 8 units or more: only the two searches every build needs may turn to it.
        if outcome.refused and self.gateway.tavily_enabled and query in (self.domain, self.name, self.domain_variant):
            outcome = self.gateway.search("tavily", query, self.budget, self.cancelled, self.deadline, depth=depth)
        if query == self.domain:
            self.domain_search = "ok" if outcome.ok else "refused" if outcome.refused else "unanswered"
        if not outcome.ok:
            log.info("search %r for %s failed: %s", query, self.domain, outcome.errors[-1:] or "budget")
            return [], outcome.provider
        self._succeeded()
        return [SearchHit(url, outcome.provider, title, text, self._priority(url, title, text))
                for url, title, text in outcome.value], outcome.provider

    def _succeeded(self) -> None:
        with self._lock:
            self.successes += 1

    def _own_host(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == self.domain or host.endswith("." + self.domain)

    def _priority(self, url: str, title: str, snippet: str) -> int:
        if self._own_host(url):
            return 0
        if names_company(title, self.domain) or names_company(snippet, self.domain):
            return 1
        return 2

    def _extract(self, url: str, render: bool = False) -> Page | None:
        """The text a provider serves for the URL; with `render`, the text a browser shows once it has loaded."""
        if self.extract_down:
            return None
        if render:
            outcome = self.gateway.extract("nimble", url, self.budget, self.cancelled, self.deadline, render=True)
            if outcome.ok and outcome.value:
                self._succeeded()
                return Page(url, "nimble", outcome.value, rendered=True)
            if outcome.exhausted or outcome.stopped:
                return None
            # Refused or unanswered: the plain extract below stands in for it.
        outcome = self.gateway.extract("nimble", url, self.budget, self.cancelled, self.deadline)
        if outcome.refused and self.gateway.tavily_enabled:
            outcome = self.gateway.extract("tavily", url, self.budget, self.cancelled, self.deadline)
        if outcome.refused:
            self.extract_down = True
        if not outcome.ok or not outcome.value:
            return None
        self._succeeded()
        return Page(url, outcome.provider, outcome.value)

    def _gather(self, max_priority: int) -> None:
        """Read every page research cites and every search result up to the priority, while the budget lasts.

        Cited pages come first, then results best first. A page on the company's own host is
        loaded in a browser; any other page is extracted as served.
        """
        order = sorted((h for h in list(self.hits.values()) if h.url not in self.attempted and h.url not in self.pages),
                       key=lambda h: h.priority)
        wanted = [u for u in self.cited if u not in self.attempted and u not in self.pages]
        wanted += [h.url for h in order if h.priority <= max_priority and h.url not in wanted]
        self.attempted.update(wanted)

        def one(url):
            page = self._extract(url, render=self._own_host(url))
            if page is not None:
                self.pages[url] = page
        self._parallel([lambda u=u: one(u) for u in wanted])

    def _render_dynamic(self) -> None:
        """Load in a browser the pages whose plain text may differ from what a browser shows.

        A page that says its figures are filled in after it loads comes first; then, while the
        budget lasts, the pages of the highest authority, whose values decide the fields.
        """
        def wants_render(page: Page) -> int | None:
            if page.rendered or page.url in self.rendered_tried:
                return None
            if looks_dynamic(page.prose):
                return 0
            kind = page_kind(header_of(page.text).get("Kind"), page.url, self.domain)
            return 1 if kind in ("own", "filing") else None

        if self.extract_down:
            return
        order = sorted((wants_render(p), p.url) for p in self.pages.values() if wants_render(p) is not None)
        urls = [url for _, url in order]
        self.rendered_tried.update(urls)

        def one(url):
            outcome = self.gateway.extract("nimble", url, self.budget, self.cancelled, self.deadline, render=True)
            if outcome.ok and outcome.value:
                self._succeeded()
                self.pages[url] = Page(url, "nimble", outcome.value, rendered=True)
        self._parallel([lambda u=u: one(u) for u in urls])

    def _research(self) -> None:
        query = (f"Company profile of {self.domain}: legal_name, hq_city, ceo, founded_year, "
                 f"headcount_range, funding_total")
        outcome = self.gateway.research(query, RESEARCH_SCHEMA, self.budget, self.cancelled, self.deadline)
        self.research_state = "ok" if outcome.ok else "refused" if outcome.refused else "unanswered"
        if not outcome.ok:
            log.info("research for %s failed: %s", self.domain, outcome.errors[-1:] or "budget")
            return
        self._succeeded()
        response = outcome.value
        structured = response.structured if isinstance(response.structured, dict) else {}
        for citation in response.citations:
            name = (citation.field or "").removeprefix("$.")
            if name in FIELDS and structured.get(name) is not None and citation.url and citation.url not in self.cited:
                self.cited.append(citation.url)

    # ------------------------------------------------------------------ deciding

    def _decide(self) -> dict:
        """Each field from the evidence gathered so far: its candidates, ranked, and what follows from them."""
        candidates: dict[str, list[dict]] = {name: [] for name in FIELDS}
        seen: set[str] = set()
        for url, page in list(self.pages.items()):
            if page.rendered or not looks_dynamic(page.prose):
                self._collect(candidates, url, page.text, page.provider, drop_last=False)
                seen.add(url)
        for url, (provider, partial) in list(self.partials.items()):
            if url not in seen and not looks_dynamic(prose_of(partial)):
                # The start of the served text: header lines, then prose cut off at some point.
                self._collect(candidates, url, partial, provider, drop_last=len(partial) >= PARTIAL_MAY_BE_CUT)
        return {name: build_field(candidates[name]) for name in FIELDS}

    def _collect(self, candidates: dict, url: str, text: str, provider: str, drop_last: bool) -> None:
        """One candidate per value that the page's prose supports for a field."""
        header = header_of(text)
        kind = page_kind(header.get("Kind"), url, self.domain)
        published = published_at(header.get("Published"))
        taken: set[tuple] = set()
        for sentence in citable_sentences(prose_of(text), drop_last=drop_last):
            for name, value in supported_values(sentence, self.domain).items():
                if (name, value) in taken:
                    continue
                taken.add((name, value))
                candidates[name].append(
                    make_candidate(value, url, sentence, provider, kind, published, self.retrieved_at))
