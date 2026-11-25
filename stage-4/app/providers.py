"""Every provider call, through WebRouter, with its cost charged to a build's budget (§9).

A call's units are reserved before it is sent and refunded only when the provider
refuses it with an error status; a call that times out or loses its connection
keeps its cost, as the specification charges it.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from web_router import ConfigurationError, ProviderNotInstalledError, WebRouter

BUILD_BUDGET = 80

COSTS = {
    ("nimble", "search", "lite"): 1,
    ("nimble", "search", "fast"): 5,
    ("nimble", "search", "deep"): 15,
    ("tavily", "search", "lite"): 8,
    ("tavily", "search", "fast"): 16,
    ("tavily", "search", "deep"): 16,
    ("nimble", "extract", None): 1,
    ("nimble", "extract", "render"): 3,
    ("tavily", "extract", None): 2,
    ("nimble", "research", None): 25,
}

RATE_LIMIT_RETRIES = 3
ERROR_RETRIES = 3
# A provider answers the same call 429 again when it is made less than one second after a 429
# for it, so a call refused with 429 waits out that second before it is made again.
RATE_LIMIT_PAUSE = 1.05


def _is_live() -> bool:
    base = os.environ.get("NIMBLE_BASE_URL")
    return base is None or urlparse(base).hostname == "sdk.nimbleway.com"


LIVE = _is_live()
# A call is never abandoned before it has waited 30 s against the live providers (§8).
CALL_TIMEOUT = float(os.environ.get("DOSSIER_CALL_TIMEOUT", 45 if LIVE else 20))
RESEARCH_TIMEOUT = float(os.environ.get("DOSSIER_RESEARCH_TIMEOUT", 180 if LIVE else 30))
MAX_OUTBOUND = int(os.environ.get("DOSSIER_MAX_OUTBOUND", 48))
# §8: a build may stop gathering once it has run GATHER_WINDOW seconds, and ends by BUILD_CAP
# (inside the 300 s the specification allows): no call starts that could outlast the cap.
GATHER_WINDOW = float(os.environ.get("DOSSIER_GATHER_WINDOW", 120))
BUILD_CAP = float(os.environ.get("DOSSIER_BUILD_CAP", 270))
# A refused call is retried after RETRY_BASE, then twice that, and so on; no retry waits
# past RETRY_HORIZON seconds into a build. Against providers that answer within a second a
# build must end within 10 s (§8), so its retries stop early; against the live providers
# retries may go on for the whole gathering window.
RETRY_BASE = float(os.environ.get("DOSSIER_RETRY_BASE", 1.0 if LIVE else 0.1))
RETRY_HORIZON = float(os.environ.get("DOSSIER_RETRY_HORIZON", GATHER_WINDOW if LIVE else 6.0))


class Deadline:
    """A build's clock: when it may still start a call that waits up to a given time."""

    def __init__(self, gather_window: float = GATHER_WINDOW, cap: float = BUILD_CAP, clock=time.monotonic,
                 retry_horizon: float = RETRY_HORIZON):
        self.gather_window = gather_window
        self.cap = cap
        self.retry_horizon = retry_horizon
        self._clock = clock
        self.start = clock()
        self._lock = threading.Lock()
        self._waiting = 0            # calls now waiting out a 429
        self._wait_began = 0.0
        self._waited = 0.0           # time during which at least one call waited out a 429

    def elapsed(self) -> float:
        return self._clock() - self.start

    def begin_wait(self) -> None:
        with self._lock:
            if self._waiting == 0:
                self._wait_began = self._clock()
            self._waiting += 1

    def end_wait(self) -> None:
        with self._lock:
            self._waiting -= 1
            if self._waiting == 0:
                self._waited += self._clock() - self._wait_began

    def active(self) -> float:
        """Time into the build, not counting time spent waiting to repeat a call answered 429."""
        with self._lock:
            waited = self._waited + (self._clock() - self._wait_began if self._waiting else 0.0)
        return self.elapsed() - waited

    def left(self) -> float:
        return self.cap - self.elapsed()

    def may_start(self, longest_wait: float) -> bool:
        """Only inside the gathering window, and only a call that would end before the cap."""
        elapsed = self.elapsed()
        return elapsed < self.gather_window and elapsed + longest_wait <= self.cap

    def may_retry_after(self, delay: float, rate_limited: bool = False) -> bool:
        """Whether a refused call may wait `delay` seconds and try again.

        The wait after a 429 is the provider's rule, not time the build spends (stage 2, Rate limits):
        it does not count toward the retry horizon, only toward the gathering window.
        """
        counted = 0.0 if rate_limited else delay
        return self.active() + counted <= self.retry_horizon and self.elapsed() + delay <= self.gather_window


class Cancelled(Exception):
    """The build was superseded (reset or import) and must make no further calls."""


class Pool:
    """Units shared by the builds of a batch: together they never spend more than the limit.

    Once a call that a build makes would pass the limit the pool is closed: the batch makes no
    more provider calls (stage 4: Batches), and every build completes with what it has gathered.
    """

    def __init__(self, limit: int):
        self.limit = limit
        self.spent = 0
        self.closed = False
        self._lock = threading.Lock()

    def take(self, units: int) -> bool:
        with self._lock:
            if self.closed or self.spent + units > self.limit:
                self.closed = True
                return False
            self.spent += units
            return True

    def give_back(self, units: int) -> None:
        with self._lock:
            self.spent -= units

    @property
    def remaining(self) -> int:
        with self._lock:
            return 0 if self.closed else self.limit - self.spent


class Budget:
    """A build's spending, never above the limit (nor above its batch's pool), reported to `on_change` as it moves."""

    def __init__(self, limit: int, on_change, pool: Pool | None = None):
        self.limit = limit
        self.spent = 0
        self.pool = pool
        self._lock = threading.Lock()
        self._on_change = on_change

    def reserve(self, units: int) -> bool:
        with self._lock:
            if self.spent + units > self.limit or (self.pool is not None and not self.pool.take(units)):
                return False
            self.spent += units
            spent = self.spent
        self._on_change(spent)
        return True

    def refund(self, units: int) -> None:
        with self._lock:
            self.spent -= units
            spent = self.spent
            if self.pool is not None:
                self.pool.give_back(units)
        self._on_change(spent)

    @property
    def remaining(self) -> int:
        with self._lock:
            own = self.limit - self.spent
        return own if self.pool is None else min(own, self.pool.remaining)


@dataclass
class Outcome:
    """What one logical call (with its retries) came to."""
    ok: bool
    provider: str
    value: object = None
    refused: bool = False       # every attempt answered with an error status
    exhausted: bool = False     # not sent: the budget could not cover it
    stopped: bool = False       # not sent: the build's time to gather is over
    errors: list = field(default_factory=list)


def _status_of(exc: BaseException) -> int | None:
    """The HTTP error status a provider answered with, or None when no answer arrived."""
    for candidate in (getattr(exc, "original", None), exc.__cause__, exc):
        if candidate is None:
            continue
        status = getattr(candidate, "status_code", None)
        if isinstance(status, int):
            return status
        response = getattr(candidate, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and status >= 400:
            return status
    return None


def _tavily_refused(exc: BaseException) -> bool:
    """Tavily's SDK raises its own classes for error answers; timeouts and lost connections are not refusals."""
    original = getattr(exc, "original", None) or exc.__cause__ or exc
    name = type(original).__name__
    return name not in ("TimeoutError", "ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout")


class Gateway:
    """The one place provider calls are made."""

    def __init__(self, call_timeout: float = CALL_TIMEOUT, retry_base: float = RETRY_BASE):
        self.call_timeout = call_timeout
        self.retry_base = retry_base
        config = {"nimble": {"max_retries": 0, "timeout": call_timeout}}
        self.tavily_enabled = bool(os.environ.get("TAVILY_API_KEY"))
        if self.tavily_enabled:
            tavily = {"timeout": call_timeout}
            if os.environ.get("TAVILY_BASE_URL"):
                tavily["api_base_url"] = os.environ["TAVILY_BASE_URL"]
            config["tavily"] = tavily
        self.nimble_enabled = bool(os.environ.get("NIMBLE_API_KEY"))
        self._router = WebRouter("nimble", provider_config=config)
        self._outbound = threading.BoundedSemaphore(MAX_OUTBOUND)

    def call(self, provider: str, method: str, depth: str | None, budget: Budget, cancelled, deadline: Deadline,
             invoke, longest_wait: float | None = None) -> Outcome:
        """Make one logical call, retrying refusals (which cost nothing) and never a call that went unanswered.

        longest_wait is how long the call may take, by default the per-call timeout.
        """
        cost = COSTS[(provider, method, depth)]
        wait = self.call_timeout if longest_wait is None else longest_wait
        errors = []
        attempts = 1 + RATE_LIMIT_RETRIES
        error_retries = ERROR_RETRIES
        for attempt in range(attempts):
            if cancelled():
                raise Cancelled()
            if not deadline.may_start(wait):
                return Outcome(ok=False, provider=provider, stopped=True, errors=errors)
            if not budget.reserve(cost):
                return Outcome(ok=False, provider=provider, exhausted=True, errors=errors)
            try:
                with self._outbound:
                    value = invoke()
                return Outcome(ok=True, provider=provider, value=value)
            except (ConfigurationError, ProviderNotInstalledError) as exc:
                # Nothing was sent: the provider is not configured in this deployment.
                budget.refund(cost)
                errors.append(f"{type(exc).__name__}: {exc}"[:300])
                break
            except Exception as exc:  # noqa: BLE001 - every provider failure is an outcome, never a 5xx
                status = _status_of(exc)
                refused = status is not None if provider == "nimble" else _tavily_refused(exc)
                errors.append(f"{type(exc).__name__}: {exc}"[:300])
                if not refused:
                    return Outcome(ok=False, provider=provider, errors=errors)
                budget.refund(cost)
                retry = status == 429 or error_retries > 0
                if status != 429:
                    error_retries -= 1
                delay = self.retry_base * (2 ** attempt)
                if status == 429:
                    delay = max(delay, RATE_LIMIT_PAUSE)
                if not retry or attempt + 1 >= attempts or not deadline.may_retry_after(delay, status == 429):
                    break
                if status == 429:
                    deadline.begin_wait()
                    try:
                        time.sleep(delay)
                    finally:
                        deadline.end_wait()
                else:
                    time.sleep(delay)
        return Outcome(ok=False, provider=provider, refused=True, errors=errors)

    # ---- the three operations a build uses

    def search(self, provider, query, budget, cancelled, deadline, depth="lite", max_results=10) -> Outcome:
        def invoke():
            response = self._router.search(query, provider=provider, search_depth=depth, max_results=max_results)
            return [(r.url, r.title or "", r.content or r.description or "") for r in response.results if r.url]
        return self.call(provider, "search", depth, budget, cancelled, deadline, invoke)

    def extract(self, provider, url, budget, cancelled, deadline, render=False) -> Outcome:
        """One URL per call, so each URL's cost and outcome are known.

        With `render` (Nimble only) the page is loaded in a browser and the text the browser
        shows is served; without it, the text the provider serves.
        """
        def invoke():
            options = {"provider_options": {"render": True}} if render else {}
            response = self._router.extract([url], provider=provider, format="markdown", **options)
            docs = [d for d in response.documents if d.content]
            return docs[0].content if docs else None
        outcome = self.call(provider, "extract", "render" if render else None, budget, cancelled, deadline, invoke)
        if not outcome.ok and not outcome.refused and not outcome.exhausted and not outcome.stopped \
                and _no_page(outcome):
            # The provider answered that it has no page: a charged answer, not a failure to reach it.
            outcome.value = None
        return outcome

    def research(self, query, schema, budget, cancelled, deadline) -> Outcome:
        """A research run, waited on for as long as the build's cap allows (and at most RESEARCH_TIMEOUT).

        Starting the run is one request bounded by the call timeout; waiting for its answer
        polls for free. Units are charged once the run is started, answered or not.
        """
        wait = min(RESEARCH_TIMEOUT, deadline.left() - self.call_timeout)

        def invoke():
            return self._router.research(query, provider="nimble", output_schema=schema, timeout=max(wait, 1.0))
        if wait <= 0:
            return Outcome(ok=False, provider="nimble", stopped=True)
        return self.call("nimble", "research", None, budget, cancelled, deadline, invoke,
                         longest_wait=self.call_timeout + wait)


def _no_page(outcome: Outcome) -> bool:
    return any("no URL could be extracted" in e for e in outcome.errors)
