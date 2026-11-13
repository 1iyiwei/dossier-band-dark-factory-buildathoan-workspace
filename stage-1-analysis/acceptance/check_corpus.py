"""Offline self-check of the analyst corpus against oracle.py (no service needed).

1. Sentence level: the set of values the evidence supports per field must equal EXPECTED.
2. Excerpt level: for every field EXPECTED to be unknown, no excerpt (any substring of a prose
   line, 1..500 chars) of the evidence supports any value -- so the expectation does not depend
   on how a service chooses excerpt boundaries.
"""
from __future__ import annotations

import sys

import oracle
from corpus_spec import COMPANIES, EXPECTED, UNKNOWN_DOMAIN


def evidence_texts(domain: str, epoch: int):
    c = COMPANIES.get(domain, {"pages": []})
    texts = [p["text"] for p in c["pages"] if epoch in p["epochs"] and p.get("searchable", True)]
    claims = []
    for r in c.get("research", {}).get("nimble", {}).get(str(epoch), []):
        if oracle.supports(r["excerpt"], r["field"], r["value"], domain):
            claims.append((r["field"], r["value"], r["excerpt"]))
    return texts, claims


def sentence_values(domain: str, epoch: int):
    texts, claims = evidence_texts(domain, epoch)
    vals = {f: set() for f in oracle.FIELDS}
    for t in texts:
        for s in oracle.sentences(t):
            for f in oracle.FIELDS:
                v = oracle.supported_value(s, f, domain)
                if v is not None:
                    vals[f].add(v)
    for f, v, _ in claims:
        vals[f].add(v)
    return vals


def substring_support(domain: str, epoch: int, field: str):
    texts, claims = evidence_texts(domain, epoch)
    lines = [ln for t in texts for ln in t.splitlines()] + [e for _, _, e in claims]
    name = oracle.company_name(domain)
    found = set()
    for ln in lines:
        low = ln.lower()
        if name not in low and domain not in low:
            continue
        n = len(ln)
        for i in range(n):
            for j in range(i + 1, min(n, i + 500) + 1):
                sub = ln[i:j]
                sl = sub.lower()
                if name not in sl and domain not in sl:
                    continue
                v = oracle.supported_value(sub, field, domain)
                if v is not None:
                    found.add((v, sub))
    return found


def main() -> int:
    bad = 0
    for domain, by_epoch in EXPECTED.items():
        for epoch, exp in by_epoch.items():
            got = sentence_values(domain, epoch)
            for f in oracle.FIELDS:
                e = exp[f]
                want = set() if e is None else (set(e) if isinstance(e, set) else {e})
                if got[f] != want:
                    print(f"MISMATCH {domain}@{epoch} {f}: oracle={got[f]} expected={want}")
                    bad += 1
                if e is None:
                    sub = substring_support(domain, epoch, f)
                    if sub:
                        print(f"NOT ROBUST {domain}@{epoch} {f}: {sorted(sub)[:3]}")
                        bad += 1
    print("corpus check:", "OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
