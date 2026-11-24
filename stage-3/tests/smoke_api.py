"""End-to-end smoke check of the HTTP API against a running service and the mock web.

    BASE=http://localhost:18000 MOCK=http://localhost:18080 python3 tests/smoke_api.py acme-robotics.test

Exits non-zero on the first failed expectation. It checks behaviour the specification
states; it is not a substitute for the official harness.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://localhost:18000")
MOCK = os.environ.get("MOCK", "http://localhost:18080")
ADMIN = {"X-Mock-Admin": os.environ.get("MOCK_ADMIN_TOKEN", "local-admin")}


def call(method, path, body=None, headers=None, base=BASE, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read()
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as error:
        text = error.read()
        return error.code, (json.loads(text) if text else None)


def expect(label, condition, detail=""):
    print(("ok   " if condition else "FAIL ") + label + ("" if condition else f"  {detail}"))
    if not condition:
        sys.exit(1)


def wait_built(domain, auth, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        status, body = call("GET", f"/dossiers/{domain}", headers=auth)
        if body and body.get("state") != "building":
            return body
        time.sleep(0.25)
    return body


def main(domain):
    call("POST", "/_mock/reset", {"epoch": 0}, headers=ADMIN, base=MOCK)
    fixture = {"now": "2026-03-01T09:00:00+00:00",
               "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                          "display_name": "Ada"},
                         {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
                          "display_name": "Bob"}]}
    expect("reset 204", call("POST", "/_test/reset", fixture)[0] == 204)
    status, body = call("POST", "/_test/reset", {"now": "2026-03-01T09:00:00+00:00",
                                                 "users": [fixture["users"][0], fixture["users"][0]]})
    expect("duplicate email reset 422", status == 422 and body["error"]["code"] == "validation_failed")
    status, login = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    expect("seeded login", status == 200 and login["user_id"] == "u_ada", login)
    auth = {"Authorization": f"Bearer {login['token']}"}
    expect("401 before key check", call("POST", "/dossiers", {"domain": domain})[0] == 401)
    status, body = call("POST", "/dossiers", {"domain": domain}, headers=auth)
    expect("missing key 400", status == 400 and body["error"]["code"] == "missing_idempotency_key", body)
    expect("bad domain 422", call("POST", "/dossiers", {"domain": "https://x.test/a"},
                                  headers={**auth, "Idempotency-Key": "bad"})[0] == 422)
    expect("wrong type 400", call("POST", "/dossiers", {"domain": 5},
                                  headers={**auth, "Idempotency-Key": "bad"})[0] == 400)

    shouted = "WWW." + domain.upper() + "."
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        call("POST", "/dossiers", {"domain": shouted}, headers={**auth, "Idempotency-Key": "k1"})))
        for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted(s for s, _ in results)
    expect("concurrent same key: one 202, rest 200", statuses == [200] * 7 + [202], statuses)
    expect("same bodies", len({json.dumps(b, sort_keys=True) for _, b in results}) == 1)
    first = results[0][1]
    expect("normalised domain", first["domain"] == domain and first["state"] == "building", first)
    status, other = call("POST", "/dossiers", {"domain": domain}, headers={**auth, "Idempotency-Key": "k2"})
    expect("existing dossier 200", status == 200 and other["dossier_id"] == first["dossier_id"], other)
    status, body = call("POST", "/dossiers", {"domain": "other.test"}, headers={**auth, "Idempotency-Key": "k1"})
    expect("key reuse 409", status == 409 and body["error"]["code"] == "idempotency_key_reuse", body)
    status, body = call("POST", "/dossiers", {"domain": 7}, headers={**auth, "Idempotency-Key": "k1"})
    expect("claimed key before validation 409", status == 409, body)

    started = time.time()
    dossier = wait_built(domain, auth)
    expect("build ends ready within 10s", dossier["state"] == "ready" and time.time() - started < 10, dossier)
    expect("spent <= 80", 0 < dossier["spent_units"] <= 80, dossier["spent_units"])
    expect("researched_at is build time", dossier["researched_at"] == "2026-03-01T09:00:00+00:00")

    log = call("GET", "/_mock/log", headers=ADMIN, base=MOCK)[1]["calls"]
    served = {}
    for entry in log:
        for item in entry["served"]:
            served.setdefault(item["url"], []).append(" ".join(item["text"].split()))
    expect("mock cost equals spent_units", sum(c["cost"] for c in log) == dossier["spent_units"])
    domain_searches = [c for c in log if c["method"] == "search" and c["status"] == 200 and c["query"] == domain]
    expect("exactly one domain search", len(domain_searches) == 1, len(domain_searches))
    for name, entry in dossier["fields"].items():
        expect(f"{name} shape", (entry["value"] is None) == (entry["status"] == "unknown")
               and (entry["status"] == "known") == bool(entry["citations"]))
        for citation in entry["citations"]:
            texts = served.get(citation["url"], [])
            expect(f"{name} citation served", any(citation["excerpt"] in t for t in texts), citation)
        print("     ", name, "=", entry["value"])

    status, body = call("POST", f"/dossiers/{domain}/refresh", headers={**auth, "Idempotency-Key": "k1"})
    expect("refresh 202 (same key, other path)", status == 202 and body["state"] == "building", body)
    status, again = call("POST", f"/dossiers/{domain}/refresh", headers={**auth, "Idempotency-Key": "k1"})
    expect("refresh replay 200", status == 200 and again == body, again)
    status, listing = call("GET", "/dossiers?q=" + domain.split(".")[0][:4].upper() + "&limit=1", headers=auth)
    expect("list", status == 200 and listing["dossiers"][0]["domain"] == domain, listing)
    expect("limit 1e9 422", call("GET", "/dossiers?limit=1e9", headers=auth)[0] == 422)
    dossier = wait_built(domain, auth)
    expect("refresh ready", dossier["state"] == "ready" and dossier["spent_units"] > 0)

    status, exported = call("GET", "/_test/export")
    expect("export", status == 200 and exported["track"] == "dossier" and exported["format_version"] == 1)
    expect("reset", call("POST", "/_test/reset", {"now": "2026-03-02T00:00:00+00:00"})[0] == 204)
    expect("token gone after reset", call("GET", f"/dossiers/{domain}", headers=auth)[0] == 401)
    expect("import", call("POST", "/_test/import", exported)[0] == 204)
    status, restored = call("GET", f"/dossiers/{domain}", headers=auth)
    expect("token and dossier back after import", status == 200 and restored == dossier, restored)
    status, replay = call("POST", f"/dossiers/{domain}/refresh", headers={**auth, "Idempotency-Key": "k1"})
    expect("replay survives import", status == 200 and replay == body, replay)
    expect("bad import 422", call("POST", "/_test/import", {"track": "x"})[0] == 422)
    expect("clock backwards 422", call("POST", "/_test/clock", {"now": "2020-01-01T00:00:00Z"})[0] == 422)
    print("all checks passed")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "acme-robotics.test")
