# Analyst handoff — stage 2 (uncommitted; written because the room message and `git commit` were denied)

Folder: `stage-2/requirements/` — `LEDGER.md` (266 rows), `RULINGS.md` (RUL-S2-01..18 + stage-1 rulings),
`acceptance/` (409 tests). Nothing outside `stage-2/requirements/` was touched.

## Ledger IDs
157 carried rows (status `open`, stage-1 evidence in parentheses) + 109 new:
R-GEN-04, R-PGK-01..05, R-TXT-01..04, R-WEB-01..06, R-RL-01..06, R-CAN-01..12, R-SEL-01..07,
R-STS-01..05, R-SCR-01..06, R-AUTH-14..16, R-LST-05/06, R-RES-01..03, R-DOS-01..06, R-BLD-07/08,
R-REF-05..07, R-EVI-01/02, R-CON-04/05, R-RD-01/02, R-UNC-01..04, R-UPG-01..07, R-VIS-01..11,
R-UX-01..06 (judged by the UX Reviewer).

## Run
```sh
cd stage-2/requirements/acceptance
./up.sh --build /Users/lwei/Trees/band-dark-factory-buildathoan-workspace/band-work/dev-result/stage-2
OLD_IMAGE=<final stage-1 image> ./up.sh --build <stage-2 dir>     # also the upgrade tests
./run.sh --base-url URL --mock-url URL [--old-url URL] [pytest args]  # against a running pair
```
Needs docker, and Python with pytest, httpx, playwright (the kickoff `.venv` has them; chromium installed).
The mock web must serve `acceptance/corpus/` (token `local-admin`). `-k "R_CAN or R_SEL"` selects by ID.
Verified before this handoff: carried stage-1 suite (254 tests) passes on the final stage-1 image with the new
16-company corpus; `check_corpus.py` and `test_rank_unit.py` pass offline. Nothing has been run against a
stage-2 build yet (the Implementer's build did not exist when the tests were written).

## Rulings that change behaviour
1. Page text = what a browser shows. Corpus pages carry a stale `static_text` served by search/extract; only
   Nimble extract with `provider_options={"render": True}` (3 units/URL) or a browser session returns the real
   text. Stale values must never be candidates or citations.
2. Evidence = every searchable page + every page a `nimble` research claim cites (even non-searchable, even when
   the claim is unsupported). One candidate per (page, value). `candidates` in rank order, selected first;
   `citations` = candidates with the selected value.
3. Kind: exactly `own|filing|news|aggregator` (`NEWS` is not listed); otherwise `own` iff the URL host,
   normalised (`www.`, case, one trailing `.` removed; a subdomain differs), equals the domain, else
   `aggregator`. Published: RFC 3339 with offset only; date only / no offset / `2026-02-30` / free text /
   absent → null. Recency compares instants. URL tie by code point (`K` before `k`). Integers rank numerically.
4. RUL-S2-12: the final stage-1 export holds no page text, kind or publication time, so imported candidates are
   one per distinct (url, value) of the citations (`kind` and `published_at` null, `retrieved_at` =
   `researched_at`); further candidates only if the old build's served text supports them.
5. UI: research/refresh are script fetches (a lost response shows `research-uncertain` / `refresh-uncertain`; the
   retry resends the same `Idempotency-Key` and JSON body); the dossier screen reads `GET /dossiers/{d}` at least
   every 2 s while `building`; reload is latest-read-wins; a signed-in browser stays signed in across
   export + reset + import.
6. Budget: each analyst company has ≤ 12 pages, so domain search + research (25) + 3 per rendered page fits in
   80 units if the build picks pages sensibly. Under 429 every distinct call may be refused up to 3 times in a
   row; the build must retry and still end with the full evidence.

## Disputes
Send the failing test name and the spec sentence relied on; the Analyst re-reads the spec and either fixes the
test (and says so) or quotes the sentence.
