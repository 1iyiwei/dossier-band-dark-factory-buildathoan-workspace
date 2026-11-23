"""Black-box helpers for the stage-1 acceptance tests (HTTP only)."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

import httpx

import oracle
import rank
from corpus_spec import COMPANIES, all_page_texts

BASE_URL = os.environ.get("BASE_URL", "http://localhost:18001").rstrip("/")
MOCK_URL = os.environ.get("MOCK_URL", "http://localhost:18081").rstrip("/")
MOCK_TOKEN = os.environ.get("MOCK_ADMIN_TOKEN", "local-admin")
# 1 = the mock serves corpus/ from this folder (enables corpus-specific checks)
ANALYST_CORPUS = os.environ.get("ANALYST_CORPUS", "1") == "1"
BUILD_WAIT = float(os.environ.get("BUILD_WAIT", "30"))

T0 = "2026-03-01T09:00:00+00:00"
USERS = [
    {"id": "u_an_ines", "email": "ines@example.org", "password": "lantern-river-42",
     "display_name": "Ines"},
    {"id": "u_an_olu", "email": "olu@example.org", "password": "copper-kettle-77",
     "display_name": "Olu"},
]
FIXTURE = {"now": T0, "users": USERS}

RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def parse_ts(s: str) -> datetime:
    assert isinstance(s, str) and RFC3339.match(s), f"not RFC 3339 with offset: {s!r}"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class FiveXX(AssertionError):
    pass


class Api:
    """Thin HTTP client. Every response is checked for 5xx (R-ERR-05) and for the error
    envelope on 4xx (R-ERR-01)."""

    def __init__(self, base=BASE_URL):
        self.base = base
        self.c = httpx.Client(base_url=base, timeout=5.0)

    def req(self, method, path, *, token=None, key=None, json=None, content=None,
            headers=None, timeout=5.0, params=None) -> httpx.Response:
        h = dict(headers or {})
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        if key is not None:
            h["Idempotency-Key"] = key
        if json is not None:
            r = self.c.request(method, path, json=json, headers=h, timeout=timeout, params=params)
        else:
            if content is not None and "Content-Type" not in h:
                h["Content-Type"] = "application/json"
            r = self.c.request(method, path, content=content, headers=h, timeout=timeout,
                               params=params)
        if r.status_code >= 500:
            raise FiveXX(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        if r.status_code >= 400:
            check_error_envelope(r)
        return r

    # convenience
    def reset(self, fixture=None):
        r = self.req("POST", "/_test/reset", json=fixture or FIXTURE, timeout=10.0)
        assert r.status_code == 204, (r.status_code, r.text)
        return r

    def clock(self, now):
        return self.req("POST", "/_test/clock", json={"now": now})

    def login(self, email, password):
        return self.req("POST", "/auth/login", json={"email": email, "password": password})

    def token(self, i=0):
        u = USERS[i]
        r = self.login(u["email"], u["password"])
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()["token"]

    def create(self, token, domain, key=None, body=None):
        return self.req("POST", "/dossiers", token=token, key=key or new_key(),
                        json=body if body is not None else {"domain": domain})

    def refresh(self, token, domain, key=None):
        return self.req("POST", f"/dossiers/{domain}/refresh", token=token, key=key or new_key())

    def get(self, token, domain):
        return self.req("GET", f"/dossiers/{domain}", token=token)

    def list(self, token, **params):
        return self.req("GET", "/dossiers", token=token, params=params)

    def wait(self, token, domain, timeout=BUILD_WAIT, interval=0.2) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            r = self.get(token, domain)
            assert r.status_code == 200, (r.status_code, r.text)
            body = r.json()
            if body["state"] != "building":
                return body
            if time.monotonic() > deadline:
                raise AssertionError(f"build of {domain} still building after {timeout}s")
            time.sleep(interval)

    def build(self, token, domain, timeout=BUILD_WAIT) -> dict:
        r = self.create(token, domain)
        assert r.status_code in (200, 202), (r.status_code, r.text)
        return self.wait(token, domain, timeout)


def check_error_envelope(r: httpx.Response):
    try:
        b = r.json()
    except Exception:  # noqa: BLE001
        raise AssertionError(f"{r.status_code} body is not JSON: {r.text[:200]!r}")
    assert isinstance(b, dict) and isinstance(b.get("error"), dict), b
    assert isinstance(b["error"].get("code"), str), b
    assert isinstance(b["error"].get("message"), str), b


def assert_error(r: httpx.Response, status: int, code: str):
    assert r.status_code == status, f"expected {status} {code}, got {r.status_code} {r.text[:300]}"
    assert r.json()["error"]["code"] == code, r.text


_kc = [0]


def new_key(prefix="k"):
    _kc[0] += 1
    return f"{prefix}-{os.getpid()}-{time.time_ns()}-{_kc[0]}"


class Mock:
    def __init__(self, base=MOCK_URL):
        self.c = httpx.Client(base_url=base, timeout=10.0, headers={"X-Mock-Admin": MOCK_TOKEN})

    def reset(self, epoch=0):
        r = self.c.post("/_mock/reset", json={"epoch": epoch})
        assert r.status_code == 204, (r.status_code, r.text)

    def epoch(self, n):
        r = self.c.post("/_mock/epoch", json={"epoch": n})
        assert r.status_code == 204, (r.status_code, r.text)

    def fault(self, provider, methods, mode, seconds=None):
        body = {"provider": provider, "methods": methods, "mode": mode}
        if seconds is not None:
            body["seconds"] = seconds
        r = self.c.post("/_mock/faults", json=body)
        assert r.status_code == 204, (r.status_code, r.text)

    def weather(self, on):
        r = self.c.post("/_mock/weather", json={"on": on})
        assert r.status_code == 204, (r.status_code, r.text)

    def log(self) -> list[dict]:
        r = self.c.get("/_mock/log")
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()["calls"]


# ------------------------------------------------------------------ dossier assertions
FIELD_TYPES = {"legal_name": str, "hq_city": str, "ceo": str, "founded_year": int,
               "headcount_range": str, "funding_total": int}


PROVIDERS = ("nimble", "tavily", "kernel", "browserbase")
STATUSES = ("known", "contested", "unknown")
CAND_KEYS = {"value", "url", "excerpt", "provider", "kind", "published_at", "retrieved_at",
             "selected"}


def assert_dossier_shape(b: dict, domain: str | None = None):
    """Stage-1 shape (§8) plus stage 2: three statuses and `candidates` on every field."""
    for k in ("dossier_id", "domain", "state", "researched_at", "spent_units", "fields"):
        assert k in b, f"missing {k}: {b}"
    assert isinstance(b["dossier_id"], str) and 1 <= len(b["dossier_id"]) <= 64
    if domain:
        assert b["domain"] == domain
    assert b["state"] in ("building", "ready", "failed")
    if b["researched_at"] is not None:
        parse_ts(b["researched_at"])
    assert isinstance(b["spent_units"], int) and not isinstance(b["spent_units"], bool)
    assert b["spent_units"] >= 0
    assert list(b["fields"].keys()) == oracle.FIELDS or set(b["fields"].keys()) == set(oracle.FIELDS)
    for f, fv in b["fields"].items():
        assert set(fv.keys()) >= {"value", "status", "citations", "candidates"}, (f, fv.keys())
        assert fv["status"] in STATUSES, (f, fv)
        assert isinstance(fv["candidates"], list), (f, fv)
        if fv["value"] is None:
            assert fv["status"] == "unknown" and fv["citations"] == [] and fv["candidates"] == [], (f, fv)
        else:
            assert fv["status"] in ("known", "contested"), (f, fv)
            assert isinstance(fv["value"], FIELD_TYPES[f]) and not isinstance(fv["value"], bool), (f, fv)
            if f == "headcount_range":
                assert fv["value"] in oracle.HEADCOUNT_VALUES, fv
            if isinstance(fv["value"], str):
                assert fv["value"] == fv["value"].strip()
            assert len(fv["citations"]) >= 1 and len(fv["candidates"]) >= 1, (f, fv)
            for c in fv["citations"]:
                assert set(c.keys()) >= {"url", "excerpt", "provider"}, c
                assert c["provider"] in PROVIDERS, c
            for c in fv["candidates"]:
                assert set(c.keys()) >= CAND_KEYS, (f, c.keys())
                assert c["provider"] in PROVIDERS, c
                assert c["kind"] in rank.KINDS or c["kind"] is None, c
                assert isinstance(c["selected"], bool), c
                parse_ts(c["retrieved_at"])
                if c["published_at"] is not None:
                    parse_ts(c["published_at"])


def candidate_structure_problems(b: dict) -> list[str]:
    """Rule checks that need no corpus: order, `selected`, value/status/citations (spec: Candidates,
    The selection rule, Status). Works on any dossier body, including imported ones."""
    probs = []
    for f, fv in b["fields"].items():
        cands = fv["candidates"]
        if not cands:
            if fv["status"] != "unknown" or fv["value"] is not None or fv["citations"]:
                probs.append(f"{f}: no candidates but {fv['status']}/{fv['value']!r}")
            continue
        probs += [f"{f}: {p}" for p in rank.rank_key_problems(cands)]
        sel = [c["selected"] for c in cands]
        if sel != [True] + [False] * (len(cands) - 1):
            probs.append(f"{f}: selected flags {sel}")
        if not rank.same_value(fv["value"], cands[0]["value"]):
            probs.append(f"{f}: value {fv['value']!r} != selected candidate {cands[0]['value']!r}")
        seen = set()
        for c in cands:
            k = (c["url"], c["provider"], repr(c["value"]))
            if k in seen:
                probs.append(f"{f}: duplicate candidate {k}")
            seen.add(k)
        distinct = {repr(c["value"]) for c in cands}
        want_status = "known" if len(distinct) == 1 else "contested"
        if fv["status"] != want_status:
            probs.append(f"{f}: status {fv['status']} but {len(distinct)} distinct value(s)")
        want_cit = [(c["url"], c["excerpt"], c["provider"]) for c in cands
                    if rank.same_value(c["value"], fv["value"])]
        got_cit = [(c["url"], c["excerpt"], c["provider"]) for c in fv["citations"]]
        if got_cit != want_cit:
            probs.append(f"{f}: citations {got_cit} != candidates with the selected value {want_cit}")
    return probs


def candidate_problems(b: dict, domain: str, log: list[dict] | None, epoch: int = 0,
                       check_corpus=ANALYST_CORPUS) -> list[str]:
    """Candidates of a dossier built from the analyst corpus against the stage-2 oracle."""
    probs = candidate_structure_problems(b)
    if not check_corpus:
        return probs
    exp = rank.expected_candidates(domain, epoch)
    corpus_texts = all_page_texts()
    for f, fv in b["fields"].items():
        want = [(c.url, c.value) for c in exp[f]]
        got = [(c["url"], c["value"]) for c in fv["candidates"]]
        if got != want:
            probs.append(f"{f}: candidates (url, value) in order\n   got  {got}\n   want {want}")
        want_kind = {c.url: c.kind for c in exp[f]}
        want_pub = {c.url: c.published for c in exp[f]}
        for c in fv["candidates"]:
            if c["url"] in want_kind:
                if c["kind"] != want_kind[c["url"]]:
                    probs.append(f"{f}: {c['url']} kind {c['kind']!r}, want {want_kind[c['url']]!r}")
                p = parse_ts(c["published_at"]) if c["published_at"] else None
                if p != want_pub[c["url"]]:
                    probs.append(f"{f}: {c['url']} published_at {c['published_at']!r}, "
                                 f"want {want_pub[c['url']]}")
            if b["researched_at"] is not None and parse_ts(c["retrieved_at"]) != parse_ts(b["researched_at"]):
                probs.append(f"{f}: retrieved_at {c['retrieved_at']} != researched_at {b['researched_at']}")
            ex = c["excerpt"]
            nex = oracle.collapse(ex).strip()
            if not (1 <= len(ex) <= 500) or not oracle.supports(ex, f, c["value"], domain):
                probs.append(f"{f}: candidate excerpt does not support {c['value']!r}: {ex!r}")
            texts = corpus_texts.get(c["url"]) or []
            if not any(nex in oracle.collapse(t) for t in texts):
                probs.append(f"{f}: candidate excerpt not in the page text of {c['url']}: {ex!r}")
            if log is not None:
                served = False
                for e in log:
                    if e.get("provider") != c["provider"]:
                        continue
                    for url, text in _served_items(e):
                        if url in (None, c["url"]) and nex in oracle.collapse(text):
                            served = True
                if not served:
                    probs.append(f"{f}: {c['provider']} never served the excerpt for {c['url']}: {ex!r}")
    return probs


def all_unknown(b: dict) -> bool:
    return all(fv["value"] is None and fv["status"] == "unknown" and fv["citations"] == []
               for fv in b["fields"].values())


def _served_items(entry):
    for it in entry.get("served") or []:
        if isinstance(it, dict):
            yield it.get("url"), it.get("text") or it.get("excerpt") or it.get("snippet") or ""
        elif isinstance(it, str):
            yield None, it


def citation_problems(b: dict, domain: str, log: list[dict] | None, check_corpus=ANALYST_CORPUS):
    """Return a list of human-readable problems with the dossier's citations (R-CIT-*)."""
    probs = []
    corpus_texts = all_page_texts() if check_corpus else {}
    for f, fv in b["fields"].items():
        if fv["value"] is None:
            continue
        for c in fv["citations"]:
            ex = c["excerpt"]
            if not (1 <= len(ex) <= 500):
                probs.append(f"{f}: excerpt length {len(ex)}")
            if not oracle.supports(ex, f, fv["value"], domain):
                probs.append(f"{f}: excerpt does not support {fv['value']!r}: {ex!r}")
            nex = oracle.collapse(ex).strip()
            if log is not None:
                ok = False
                for e in log:
                    if e.get("provider") != c["provider"]:
                        continue
                    for url, text in _served_items(e):
                        if url not in (None, c["url"]):
                            continue
                        if nex in oracle.collapse(text):
                            ok = True
                            break
                    if ok:
                        break
                if not ok:
                    probs.append(f"{f}: excerpt not served by {c['provider']} for {c['url']}: {ex!r}")
            if check_corpus:
                texts = corpus_texts.get(c["url"])
                if not texts:
                    probs.append(f"{f}: url not a corpus page: {c['url']}")
                elif not any(nex in oracle.collapse(t) for t in texts):
                    probs.append(f"{f}: excerpt not in the page prose of {c['url']}: {ex!r}")
    return probs


def successful(entries):
    return [e for e in entries if isinstance(e.get("status"), int) and e["status"] < 400]


def domain_queries(log, domain):
    return [e for e in successful(log) if e.get("method") == "search" and e.get("query") == domain]


def total_cost(log):
    return sum(int(e.get("cost") or 0) for e in log)
