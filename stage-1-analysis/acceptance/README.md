# Stage 1 acceptance tests (Analyst)

Black-box tests written from `stage-1.md` alone. They talk to the service only over HTTP and to
the mock web only through its admin API (`/_mock/*`). Every test function name carries the ledger
IDs it covers (see `../LEDGER.md`; rulings in `../RULINGS.md`).

## One command

From this folder, with Docker running:

```sh
./up.sh --build ../../stage-1          # build the service image from stage-1/ and test it
./up.sh <service-image-tag>            # or test an existing image
./up.sh <image> -k idempotency -x      # extra args go to pytest
```

`up.sh` builds the kickoff mock (`dossier-web`), starts it as `web-analyst` on network
`dossier-analyst` **serving `corpus/` from this folder** (port 18081, admin token `local-admin`),
starts the service as `svc-analyst` with `--cpus 2 --memory 3g -e PORT=8000 -p 18001:8000` and the
provider variables pointing at the mock, prints the start-to-healthy time (R-DEL-09), runs the
suite and removes both containers (`KEEP=1` keeps them). Override names/ports with `SUFFIX`,
`SVC_PORT`, `MOCK_PORT`; the kickoff package location with `KICKOFF`.

## Against an already running service

```sh
./run.sh --base-url http://localhost:18001 --mock-url http://localhost:18081 [pytest args]
```

The mock must serve this folder's `corpus/` (mount it at `/data/corpus`). If it serves another
corpus, add `--no-corpus`: corpus-specific tests are then skipped and the generic API tests still
run. `run.sh` uses `$PYTHON`, else the kickoff `.venv`, else `python3` with `pytest` + `httpx`,
else creates a temporary venv from `requirements.txt`.

Offline only (no service): `python -m pytest test_oracle_unit.py`.

## What is here

| File | Purpose |
|---|---|
| `oracle.py` | Independent implementation of Appendix A (sentences, phrases, value formats, amounts, normalisation) and of the §4 header/prose split. Judges every citation the service returns. |
| `corpus_spec.py` | The analyst corpus (fictional companies, written for this suite) and `EXPECTED` field values per company/epoch. `python3 corpus_spec.py` regenerates `corpus/*.json`. |
| `check_corpus.py` | Verifies `EXPECTED` against the oracle, and brute-forces every substring of the evidence for fields expected `unknown` (so the expectation holds whatever excerpt boundaries a service picks). |
| `lib.py`, `conftest.py` | HTTP client (fails any 5xx, checks the error envelope on every 4xx), mock admin client, assertions. |
| `test_runtime.py` | health, reset/seed, clock, conventions |
| `test_auth.py` | signup/login/validation/bearer tokens |
| `test_domains_validation.py` | domain normalisation, 400/422 rules, Idempotency-Key presence and length, list parameters |
| `test_idempotency.py` | replays, reuse, scoping, unknown fields, path/case, concurrency |
| `test_builds.py` | lifecycle, refresh, failed builds, provider faults, budget, spend accounting |
| `test_support_corpus.py` | Appendix A end to end: expected values, citation validity, 80-unit cap, one domain query, research request shape |
| `test_listing.py` | `GET /dossiers` filter, order, pagination |
| `test_export_import.py` | export/import round trip, invalid imports, export during a build |
| `test_concurrency.py` | 50 in flight, concurrent creates |
| `test_oracle_unit.py` | the oracle against every example in the specification (offline) |

## How citations are judged

For each `known` field and each citation:

1. `oracle.supports(excerpt, field, value, domain)` must hold (Appendix A).
2. The excerpt (whitespace runs collapsed) must occur in a text the mock log shows the citation's
   `provider` served for the citation's `url` (search snippet/body, extract page, or research excerpt).
3. The excerpt must occur in that page's prose in the corpus (not in its header lines).
4. 1 ≤ length ≤ 500.

Costs: the mock records each call's cost by the §9 table; tests assert `spent_units` equals the
sum, and that each build costs ≤ 80.

## Notes

- Tests run serially; each starts with `POST /_test/reset` and a mock reset (epoch 0, no faults, empty log).
- Some tests slow providers with mock `delay` faults to observe `building` states; the whole suite takes a few minutes.
- Do not run the band's official harness and this suite against the same mock at the same time.
