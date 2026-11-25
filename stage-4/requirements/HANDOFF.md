# Analyst handoff — stage 4 (independent sources, batches, provider failure)

Folder: `stage-4/requirements/` — `LEDGER.md` (383 rows: 319 carried, reset to `open`, + 64 `R4-*`), `RULINGS.md`
(RUL-S4-01..26, then stage-3/2/1 rulings), `acceptance/` (stage-3 suite adapted to eight fields + `test_s4_*.py`, `s4lib.py`,
`lineage.py`; corpus 24 files incl. corvane-systems, linden-forge, ravenmoor-energy, quillon-bio, halden-labs, wire-hub).

## Run
```sh
cd stage-4/requirements/acceptance
OLD_IMAGE=<final stage-1 image> OLD2_IMAGE=<final stage-2 image> OLD3_IMAGE=<final stage-3 image> ./up.sh --build /abs/path/to/stage-4   # everything
./up.sh --build /abs/path/to/stage-4 -k "test_s4_ or R4_"                                                                                    # stage-4 tests only
./run.sh --base-url URL --mock-url URL [--old-url U --old2-url U --old3-url U] --container <svc docker name> [pytest args]
python -m pytest test_s4_unit.py test_timeline_unit.py test_rank_unit.py test_oracle_unit.py ; python check_corpus.py                      # offline
```
`up.sh` runs the service without `--rm` and exports `SVC_CONTAINER` (restart tests `docker kill -s KILL` / `docker start` it); restart tests skip
without it, upgrade tests skip without `OLD_BASE_URL`/`OLD2_BASE_URL`/`OLD3_BASE_URL`. The mock must serve `acceptance/corpus/` (token `local-admin`).
Slow: `test_R4_BAT_17` (50 domains); the restart tests take about a minute each.

## Rulings that change behaviour
1. RUL-S4-02: `own` needs registrant == the company's domain, also for a page with no `Kind` line (it is an aggregator); lookalikes (`Kind: own`, registrant != host) are aggregators and have the company's domain as origin (rule 3), unless First-Published-By or Canonical applies first.
2. RUL-S4-04/05/06: Canonical chains per page (3 follows, then the host of the 4th URL; missing original -> its host; cycles cut by the count); originals are obtained but are **not evidence** (their values are no candidates).
3. RUL-S4-08/07: standing origins restart when a value/member leaves and returns; a field's `corroborated_since` for members is when every current member reached two; `as_of` answers use no later history.
4. RUL-S4-14/15/16: investor runs as `ceo` runs; never `contested`; non-member candidates are `selected: false` and cited nowhere; a removed name makes a `change`.
5. RUL-S4-09/10/12: `domains` of the wrong type is 400; a batch with no build of its own is `done`; a build starved by the budget may be `ready` (all unknown) or `failed`.
6. RUL-S4-18/19/20: restart and failure tests use mock delays/faults (SIGKILL after the first billed call, delays lifted before the start); "every call fails" is mock `error`.

## Disputes
Send the failing test name and the sentence relied on; the Analyst re-reads the spec and fixes the test or quotes it.
