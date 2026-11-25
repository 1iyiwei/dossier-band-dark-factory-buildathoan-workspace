"""Offline self-check of the analyst corpus against oracle.py and rank.py (no service needed).

1. Sentence level: the set of values the evidence supports per field (stage 2: pages as a browser
   shows them, plus every page a research entry cites) equals EXPECTED.
2. The value rank.py selects equals the hand-written SELECTED / single EXPECTED value.
3. Excerpt level: for every field EXPECTED to be unknown, no excerpt (any substring of a prose
   line, 1..500 chars) of the evidence supports any value.
"""
from __future__ import annotations

import sys

import oracle
import rank
from corpus_spec import COMPANIES, EXPECTED, STALE, selected


def evidence_lines(domain: str, epoch: int):
    pages = rank.evidence_pages(domain, epoch)
    lines = [ln for p in pages for ln in p["text"].splitlines()]
    c = COMPANIES.get(domain, {})
    lines += [r["excerpt"] for r in c.get("research", {}).get("nimble", {}).get(str(epoch), [])
              if any(p["url"] == r["url"] and r["excerpt"] in p["text"] for p in pages)]
    return lines


def substring_support(domain: str, epoch: int, field: str):
    name = oracle.company_name(domain)
    found = set()
    for ln in evidence_lines(domain, epoch):
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
            cands = rank.expected_candidates(domain, epoch)
            for f in oracle.FIELDS:
                e = exp[f]
                want = set() if e is None else (set(e) if isinstance(e, set) else {e})
                got = {c.value for c in cands[f]}
                if got != want:
                    print(f"MISMATCH {domain}@{epoch} {f}: oracle={got} expected={want}")
                    bad += 1
                sel = cands[f][0].value if cands[f] else None
                hand = selected(domain, f, epoch) if (e is not None) else None
                if sel != hand or type(sel) is not type(hand):
                    print(f"SELECTION {domain}@{epoch} {f}: rank.py={sel!r} hand={hand!r}")
                    bad += 1
                if e is None:
                    sub = substring_support(domain, epoch, f)
                    if sub:
                        print(f"NOT ROBUST {domain}@{epoch} {f}: {sorted(sub)[:3]}")
                        bad += 1
    # stale (static-text only) values are never supported by the browser text
    for domain, fs in STALE.items():
        cands = rank.expected_candidates(domain, 0)
        for f, vals in fs.items():
            if {c.value for c in cands[f]} & vals:
                print(f"STALE value is a candidate: {domain} {f}")
                bad += 1
    print("corpus check:", "OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
