# Stage 4 acceptance tests (Analyst)

Stage 4 adds (written from `stage-4.md` + stages 1-3, never from the implementation): oracles `lineage.py` (origins),
`oracle.supported_investors`, `rank.kind_of`/`registrant_of` (registrant rule), `timeline.py` extended with `investors`,
`origin`, `origins`, `corroborated` and the standing-origins `SinceTracker` (self-checked offline by `test_s4_unit.py`);
`s4lib.py` (batches, faults around a build, partial-build checks, stop-with-builds-running, imported-origin expectation);
and the files

| File | What | Ledger |
|---|---|---|
| `test_s4_lineage.py` | own/lookalike kinds, origins by hand (chains, cycle, missing original, First-Published-By), seven-build corroboration, as_of keys | R4-LIN/OWN/ORG/COR |
| `test_s4_investors.py` | `investors`: members, trap sentences, sorted value, history/feed types, `/values`, first value is a `change` | R4-INV |
| `test_s4_batches.py` | `POST/GET /batches`: validation (20 bodies), shape, states, shared budget, ownership, idempotency, concurrency, 50 domains | R4-BAT |
| `test_s4_failure.py` | provider failure: 12 fault sets, research failing, everything failing (`failed` <= 10 s), refused calls free, batches | R4-FAIL |
| `test_s4_restart.py` | SIGKILL with builds/batches running (needs `SVC_CONTAINER`): not left `building`, 80 units across the stop, billed units counted | R4-RST |
| `test_s4_upgrade.py` | stage-1/2/3 exports (needs `OLD_BASE_URL`, `OLD2_BASE_URL`, `OLD3_BASE_URL`) and the service's own export with batches | R4-UPG |
| `test_s4_ui.py` | browser: `investors` takes no `data-testid`; contested screen; lookalike `data-kind` | R4-INV-12 |

Corpus: six new companies (corvane-systems, linden-forge, ravenmoor-energy, quillon-bio, halden-labs, oakhurst-media) and the
pseudo-company `wire-hub.test` (non-searchable originals only), 25 files in all; `python3 corpus_spec.py` regenerates `corpus/`.
Carried files were adapted to eight fields (`oracle.ALL_FIELDS`), the three new keys and `origin` (`lib.assert_dossier_shape`,
`s3lib.snapshot_problems`), nothing else.

```sh
cd stage-4/requirements/acceptance
OLD_IMAGE=<final stage-1 image> OLD2_IMAGE=<final stage-2 image> OLD3_IMAGE=<final stage-3 image> ./up.sh --build /abs/path/to/stage-4
./up.sh --build /abs/path/to/stage-4 -k "test_s4_ or R4_"                  # stage-4 tests only (no old images: upgrade tests skip)
./run.sh --base-url URL --mock-url URL [--old-url U --old2-url U --old3-url U] --container <docker name> -k "R4_"
python -m pytest test_s4_unit.py test_timeline_unit.py test_rank_unit.py test_oracle_unit.py; python check_corpus.py   # offline
```

# Stage 3 acceptance tests (Analyst, carried)

Stage 3 adds (written from `stage-3.md` + stages 1-2): `timeline.py` (oracle for two times, executives, history, feed, as_of, page versions; self-checked offline by `test_timeline_unit.py`), `s3lib.py` (endpoint wrappers, scripted multi-build scenarios on the mock's epochs and the service clock, response checkers, docker kill/restart), and `test_s3_timeline`, `test_s3_executives`, `test_s3_endpoints`, `test_s3_upgrade`, `test_s3_restart`, `test_s3_concurrency`, `test_s3_ui`. See `../HANDOFF.md` for the run commands (`OLD2_IMAGE`, `SVC_CONTAINER`). The stage-2 text below still describes the carried files.

Black-box tests written from `stage-2.md` and `stage-1.md` only (HTTP and a real browser). Ledger IDs
are in the test names (`test_R_CAN_04_…` covers `R-CAN-04`); `../LEDGER.md` maps every row.

| File | What |
|---|---|
| `test_candidates.py` | candidates, selection rule, status, page text, research-cited pages; hand-written expectations |
| `test_support_corpus.py` | every corpus company end to end: values, candidates in rank order, citations, budget, log rules (stage 1 + stage 2) |
| `test_web_ratelimit.py` | render cost, optional browser vendors, session release, 429 handling |
| `test_ui_contract.py` | `Accept: text/html` vs JSON on the shared route; every route is HTML; no foreign assets (HTTP only) |
| `test_ui_screens.py` | browser: routes, signup/login, list+search, research, dossier, evidence, contested |
| `test_ui_flows.py` | browser: building (polling), refresh, latest read wins, lost responses, competing clients, export/import around a signed-in browser |
| `test_ui_visual.py` | browser, 375 px and 1280 px: no horizontal scroll, labels, focus, contrast, distinct states, navigation, formatted values |
| `test_upgrade.py` | stage-1 export imported into the service under test (needs `OLD_BASE_URL`) |
| `test_rank_unit.py`, `test_oracle_unit.py`, `check_corpus.py` | offline self-checks of the oracles and of the corpus |
| carried from stage 1 | `test_auth`, `test_builds`, `test_concurrency`, `test_domains_validation`, `test_export_import`, `test_idempotency`, `test_listing`, `test_runtime` |

`oracle.py` is the stage-1 support rule (Appendix A); `rank.py` the stage-2 candidates/selection/status
oracle; `corpus_spec.py` generates `corpus/` (`python3 corpus_spec.py`) — 16 fictional companies,
including five for stage 2 (harlow-instruments, kestrel-optics, lumen-textiles, tarn-biotech,
vesper-lanterns) with kinds, publication times, ties, static-vs-browser text and research-cited pages.

## One command

From this folder (needs docker, and Python with pytest, httpx and playwright — the kickoff venv has
them; otherwise `run.sh` builds a venv and runs `playwright install chromium`):

```sh
./up.sh --build /abs/path/to/stage-2                      # builds the image, starts mock web + service, runs everything
OLD_IMAGE=<final stage-1 image> ./up.sh --build /abs/path/to/stage-2   # + upgrade tests against a stage-1 service
./up.sh <image-tag> -k "R_CAN or R_SEL or R_STS"         # extra args go to pytest
```

`up.sh` starts the mock web serving `corpus/` (token `local-admin`) and the service
(`--cpus 2 --memory 3g`, provider variables for all four providers) on a private network, measures
start-to-healthy, runs the tests and removes the containers. It refuses to start if one of its ports
(`SVC_PORT` 18001, `MOCK_PORT` 18081, `OLD_PORT` 18002) is used by something else.

Against a service and mock you already run (the mock must serve this folder's `corpus/`):

```sh
./run.sh --base-url http://localhost:8000 --mock-url http://localhost:8080 [--old-url http://localhost:8001]
```

Markers: tests that need the analyst corpus are skipped with `--no-corpus`; UI tests need playwright
and chromium; `test_upgrade.py` and `test_R_UPG_07` skip without `OLD_BASE_URL`.
Offline (no service): `python3 check_corpus.py && python -m pytest test_rank_unit.py test_oracle_unit.py`.
