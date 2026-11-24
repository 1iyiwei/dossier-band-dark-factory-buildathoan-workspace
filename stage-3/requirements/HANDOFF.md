# Analyst handoff — stage 3 (change over time)

Folder: `stage-3/requirements/` — `LEDGER.md` (319 rows: 261 carried + 58 `R3-*`), `RULINGS.md` (RUL-S3-01..23, then
stage-2 and stage-1 rulings), `acceptance/` (stage-2 suite carried + new `test_s3_*.py`, `timeline.py` oracle,
`s3lib.py`, corpus with 3 new companies: northgate-labs, cobalt-assembly, harrow-guild).

## Run
```sh
cd stage-3/requirements/acceptance
OLD_IMAGE=<final stage-1 image> OLD2_IMAGE=<final stage-2 image> ./up.sh --build /abs/path/to/stage-3          # everything
./up.sh --build /abs/path/to/stage-3 -k "test_s3_ or R3_"                                                      # stage-3 tests only
./run.sh --base-url URL --mock-url URL [--old-url URL] [--old2-url URL] --container <svc docker name> [pytest args]
python -m pytest test_timeline_unit.py test_rank_unit.py test_oracle_unit.py ; python check_corpus.py          # offline
```
`up.sh` runs the service container without `--rm` and exports `SVC_CONTAINER` so `test_s3_restart.py` can
`docker kill -s KILL` / `docker start` it. Restart tests skip without `SVC_CONTAINER`; upgrade tests skip without
`OLD_BASE_URL` / `OLD2_BASE_URL`. Needs docker, python with pytest, httpx, playwright (kickoff `.venv`).
The mock must serve `acceptance/corpus/` (token `local-admin`); `python corpus_spec.py` regenerates it.

## New test files
`test_s3_timeline.py` (northgate: 7 builds incl. a failed and a repeated one; two times, history, feed, as_of, values),
`test_s3_executives.py`, `test_s3_endpoints.py` (validation, shared feed, equal-time builds, failed first build),
`test_s3_upgrade.py` (stage-1, stage-2, own export), `test_s3_restart.py`, `test_s3_concurrency.py`, `test_s3_ui.py`.

## Rulings that change behaviour
1. RUL-S3-15: the FINAL stage-2 export has no build list and no Effective lines; stage-2 import = one ready build at
   `researched_at`, candidate `true_from` = UTC date of `published_at`.
2. RUL-S3-02/03: Effective must be a real `YYYY-MM-DD`; else UTC date of a valid Published; else null.
3. RUL-S3-04: a build gathers every evidence page (full text); a gathered page without candidates still makes a version.
4. RUL-S3-06: equal `true_from` is a `correction`.  RUL-S3-14: stage-1 import has null dates; `/values` empty until a build.
5. RUL-S3-18/19/20: restart tests use SIGKILL; durable before responding; a stop mid-build must not leave `building`.
6. RUL-S3-01: percent-encode `+` in `as_of`; a raw `+` is not tested (recommend accepting it as `+`).

## Disputes
Send the failing test name and the sentence relied on; the Analyst re-reads the spec and fixes the test or quotes it.
