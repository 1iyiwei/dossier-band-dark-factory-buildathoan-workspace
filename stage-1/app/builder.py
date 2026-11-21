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
  6. Whatever budget is left goes to fields still unknown, round after round: further `lite`
     searches with other wordings of each field (and extracts of what they find).
When every provider refuses extracts, no more are attempted in that build: a Nimble `deep`
search (15 units, whole page texts) naming the domain replaces step 2, the field
searches of step 3 are cheap `lite` probes, and step 6 repeats as `deep` (or, when under
15 units remain, `fast`) the probe whose results hold the most relevant pages still
without text. Research is never reserved for: once it has run (or been refused), its units
are spent like any others.
Tavily is used only when Nimble refuses a call and a Tavily key is configured.

A value is asserted only when a cited excerpt supports it by Appendix A (`support.py`).
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .pages import appears_in, citable_sentences, looks_like_header_line, prose_of
from .providers import Budget, Cancelled, Deadline, Gateway
from .support import FIELDS, company_name, names_company, normalise_claim, supported_value, supported_values

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
DEEP_SEARCH_COST = 15
FAST_SEARCH_COST = 5
MAX_CITATIONS = 5
SNIPPET_MAY_BE_CUT = 250   # a snippet at least this long may end mid-sentence
PARTIAL_MAY_BE_CUT = 1400  # likewise a `fast` result's truncated page body
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
        self.domain_variant = f"{domain} {self.name}"   # finds what the domain query finds
        self.budget = budget
        self.cancelled = cancelled
        self.deadline = deadline
        self.hits: dict[str, SearchHit] = {}        # by URL, in the order first returned
        self.pages: dict[str, Page] = {}            # pages gathered from search results
        self.cited_pages: dict[str, Page] = {}      # pages gathered only to check a research claim
        self.attempted: set[str] = set()
        self.claims: list[Claim] = []
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
                self._searches([self.domain, self.name])
                self._gather(max_priority=1)
                if self.extract_down:
                    # No page text from extracts: a deep search serves whole pages instead. It
                    # names the domain, which ranks the company's pages first, but is not the bare
                    # domain, whose search is made only once.
                    self._searches([self.domain_variant], depth="deep")
                fields = self._decide()
                unknown = self._unknown(fields)
                if unknown:
                    research = None
                    if self.budget.remaining >= RESEARCH_COST + len(unknown):
                        research = self.pool.submit(self._research)
                    self._searches([self._field_query(f, 0) for f in unknown])
                    if research is not None:
                        research.result()
                    self._gather(max_priority=1)
                    fields = self._decide()
                    unknown = self._unknown(fields)
                self._retry_domain_search()
                if unknown and self.claims:
                    self._check_claims(unknown)
                    fields = self._decide()
                    unknown = self._unknown(fields)
                self._retry_domain_search()
                if unknown or self.pages_pending():
                    self._gather(max_priority=2 if unknown else 1)
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
        """Rounds of further searches for the fields still unknown, while the budget lasts.

        Each round runs queries not tried before, so the loop ends: when every field is known,
        the budget or the gathering window runs out, or nothing new is left to ask.
        """
        unknown = self._unknown(fields)
        if unknown and self.research_state == "refused" and self.budget.remaining >= RESEARCH_COST:
            # A refused run cost nothing; its claims may be the only evidence for a field.
            self._research()
            if self.claims:
                self._check_claims(unknown)
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

    def pages_pending(self) -> bool:
        """Relevant search results not yet attempted (a late domain search may add some)."""
        return any(h.priority <= 1 and h.url not in self.attempted and h.url not in self.pages
                   for h in self.hits.values())

    @staticmethod
    def _unknown(fields: dict) -> list[str]:
        return [name for name in FIELDS if fields[name]["value"] is None]

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
                    self.pages[hit.url] = Page(hit.url, provider, prose_of(hit.snippet))
                elif depth == "fast" and hit.snippet:
                    self.partials.setdefault(hit.url, (provider, hit.snippet))

    def _search(self, query: str, depth: str) -> tuple[list[SearchHit], str]:
        outcome = self.gateway.search("nimble", query, self.budget, self.cancelled, self.deadline, depth=depth)
        if outcome.refused and self.gateway.tavily_enabled:
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

    def _priority(self, url: str, title: str, snippet: str) -> int:
        host = (urlparse(url).hostname or "").lower()
        if host == self.domain or host.endswith("." + self.domain):
            return 0
        if names_company(title, self.domain) or names_company(snippet, self.domain):
            return 1
        return 2

    def _extract(self, url: str) -> Page | None:
        if self.extract_down:
            return None
        outcome = self.gateway.extract("nimble", url, self.budget, self.cancelled, self.deadline)
        if outcome.refused and self.gateway.tavily_enabled:
            outcome = self.gateway.extract("tavily", url, self.budget, self.cancelled, self.deadline)
        if outcome.refused:
            self.extract_down = True
        if not outcome.ok or not outcome.value:
            return None
        self._succeeded()
        return Page(url, outcome.provider, prose_of(outcome.value))

    def _gather(self, max_priority: int) -> None:
        """Extract every search result up to the priority, best first, while the budget lasts."""
        order = sorted((h for h in list(self.hits.values()) if h.url not in self.attempted and h.url not in self.pages),
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
        self.research_state = "ok" if outcome.ok else "refused" if outcome.refused else "unanswered"
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
            elif url in self.partials:
                # The start of the served text: header lines, then prose cut off at some point.
                provider, partial = self.partials[url]
                sentences = citable_sentences(prose_of(partial), drop_last=len(partial) >= PARTIAL_MAY_BE_CUT)
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
        if page is None and looks_like_header_line(claim.excerpt):
            return None   # without the page, at least refuse what has the form of a header line
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
