# Dossier — stage 3

A company-profile service: `POST /dossiers` researches a company by its domain in the
background, through Nimble called via WebRouter, and `GET /dossiers/{domain}` returns seven
fields (the six of stage 1 and `executives`), each with the excerpts that support it and every
candidate value the evidence holds. Stage 3 adds change over time: each value carries
`true_from` and `learned_at`, `GET /dossiers/{domain}?as_of=` answers as the service had the
dossier then, `/values?true_at=` what the evidence says held on a date, `/history` each
field's selected values, and `GET /changes` a feed of every change and correction. State is
kept on disk and survives an abrupt stop. Sources that disagree are ranked by a fixed rule (authority, recency, URL, value);
the best candidate is the field's value and the field is `contested`. Researchers use it in
a browser at `/` (list and research form), `/dossiers/{domain}`, `/dossiers/{domain}/evidence`,
`/contested`, `/signup` and `/login`.

## Build and start

From this folder, with your Nimble key exported first (`export NIMBLE_API_KEY=...`):

```sh
docker build -t dossier-stage-3 . && docker run --rm -p 8080:8080 -e PORT=8080 \
  -e NIMBLE_API_KEY="$NIMBLE_API_KEY" dossier-stage-3
```

`GET http://localhost:8080/health` answers `{"status": "ok"}` once it is serving (within a
second or two). No other setup is needed: the state starts empty and is written to
`/srv/data/state.json` inside the container, so a container that is stopped (even killed) and
started again answers as before. `docker run --rm` discards it with the container; to keep
it across container re-creation, mount a volume at `/srv/data`.

### Environment

| Variable | Use |
|---|---|
| `PORT` | Port to listen on (default `8080`) |
| `DOSSIER_DATA_DIR` | Directory of the state file (default `/srv/data` in the image, `./data` otherwise) |
| `NIMBLE_API_KEY`, `NIMBLE_BASE_URL` | Read by WebRouter's `nimble` provider. Leave `NIMBLE_BASE_URL` unset for the live endpoint; never set it empty |
| `TAVILY_API_KEY`, `TAVILY_BASE_URL` | Optional. Tavily is used only when Nimble refuses a call |
| `KERNEL_*`, `BROWSERBASE_*` | Not used: Nimble's rendered extract supplies every page's browser text |
| `LOG_LEVEL` | Python log level (default `INFO`) |
| `DOSSIER_CALL_TIMEOUT`, `DOSSIER_RESEARCH_TIMEOUT` | Seconds to wait for one provider call / a research run (defaults 45/180 live, 20/30 against another endpoint) |
| `DOSSIER_RETRY_BASE`, `DOSSIER_RETRY_HORIZON` | A refused call (429/500) is retried after `RETRY_BASE` s, doubling, at most 3 times (a 429 always waits at least 1.05 s: providers answer a repeat within a second 429 again), and never past `RETRY_HORIZON` s of build time into a build, not counting time spent waiting out a 429 (defaults 1/120 live, 0.1/6 against another endpoint) |
| `DOSSIER_GATHER_WINDOW`, `DOSSIER_BUILD_CAP` | A build starts no call after `GATHER_WINDOW` s (default 120), nor one that could run past `BUILD_CAP` s (default 270) |

### Against the local mock web

From the kickoff package root, create the network and start the mock (see
`challenges/dossier/web/README.md`), then the service on the same network (its image
`dossier-stage-3` built as above):

```sh
docker network create dossier
docker build -t dossier-web challenges/dossier/web
docker run --rm -d --name web --network dossier -e MOCK_ADMIN_TOKEN=local-admin \
  -v "$PWD/challenges/dossier/web/corpus/sample:/data/corpus:ro" -p 8080:8080 dossier-web
docker run --rm --network dossier -p 8000:8000 -e PORT=8000 \
  -e NIMBLE_API_KEY=local -e NIMBLE_BASE_URL=http://web:8080/nimble \
  -e TAVILY_API_KEY=local -e TAVILY_BASE_URL=http://web:8080/tavily dossier-stage-3
```

## Tests

```sh
pip install -r requirements.txt                     # the unit tests import web_router
python3 -m unittest discover -s tests -t .          # Appendix A rule, build deadlines, history/feed/values/restarts; no network
BASE=http://localhost:8000 MOCK=http://localhost:8080 python3 tests/smoke_api.py acme-robotics.test
```

The smoke script needs the service and the mock running (mock admin token `local-admin`).

## Layout

| File | Responsibility |
|---|---|
| `app/server.py` | HTTP routing, request parsing, error bodies (§3, §5–§8, §10); serves the UI shell to browsers |
| `app/static/` | The browser UI: `index.html`, `app.css`, `app.js` (no build step, no external resources) |
| `app/candidates.py` | Page kind and time, `true_from`, the selection rule, field status, the `executives` field |
| `app/store.py` | All state behind one lock; builds in background threads; history and feed; export/import |
| `app/history.py` | Typing a change (`change`/`correction`), and the page versions that held on a date |
| `app/persistence.py` | The durable state file: atomic, synced, group-committed |
| `app/builder.py` | One build: which provider calls to make and how each field is decided |
| `app/providers.py` | Every provider call through WebRouter, charged to the build's 80-unit budget |
| `app/support.py` | Appendix A: whether an excerpt supports a value |
| `app/pages.py` | Header lines vs prose; citable sentences; pages that say a browser fills them in |
| `app/validation.py` | Domains, timestamps, emails, paging parameters |
| `app/passwords.py` | scrypt password hashes |

## Design notes

- **Budget.** Each call's units are reserved before it is sent and refunded only when the
  provider refuses it with an error status; timeouts keep their cost. A call that would
  pass 80 units is not made. Refusals (429/500) are retried; unanswered calls are not.
- **Time.** A build starts calls only in its first 120 s and only when the call's timeout
  ends before 270 s, so it always ends `ready` or `failed` within 300 s; a started call is
  never abandoned early, and an unanswered call keeps its cost.
- **Research plan.** Side by side: lite searches for the domain (once), the company name and
  one wording of each field, and a Nimble research run. Then an extract of every page they
  name (research-cited pages first), then, for fields still without a candidate, rounds of
  further lite searches while the 80-unit budget lasts.
- **Page text.** A page's text is what a browser shows once it has loaded. Pages on the
  company's own host, pages that say their figures load live, and other own/filing pages
  (budget permitting) are read through Nimble's rendered extract (3 units); the rest by plain
  extract (1 unit). A page whose plain text says it is filled in by a browser, and that could
  not be rendered, yields no candidate.
- **Candidates.** Every page of the evidence (search results, and the page each research claim
  cites) yields one candidate per value its prose supports by Appendix A, with the page's
  `Kind` and `Published` headers (fallback: `own` for the company's host, else `aggregator`).
  Research claims only name pages; their excerpts are not candidates. The `Facts:` header is
  never used. Without Nimble extracts, candidates come from `deep`/`fast` search bodies only.
- **Upgrading.** A stage-1 export keeps no page text, so an imported field's candidates are its
  citations (one per page, kind and publication time null, `retrieved_at` = `researched_at`).
  The next completed build replaces them. Every import of a stage-1 or stage-2 export becomes one
  ready build at `researched_at` (the earlier services recorded no per-build list), with one page
  version per candidate URL (`true_from` from its publication time) and one `initial` history entry
  per field with a value; `executives` is unknown. A stage-3 export carries builds, history, the
  feed and the dates candidates were first seen, and round-trips unchanged.
- **Two times.** A page's `true_from` is its `Effective` header (a valid `YYYY-MM-DD`), else the UTC
  date of `Published`, else null. A candidate's `learned_at` is the time of the first ready build that
  gathered the same field (and title), value, URL and provider. A field's `learned_at` is the time of the
  build that made its value the selected one; a later build with the same value keeps it.
- **History and feed.** When a build completes `ready`, one step under the lock compares each
  field's new selected value with the old one, appends history entries and feed entries (numbered in
  field order, `executives` last) and stores the build's fields and page versions. Each build's
  fields are kept, which is what `?as_of=` serves; its page versions are what `/values` replays.
- **Durability.** Every change of state (sign-up, token, idempotent write, clock, reset, import, a
  finished build) is written to the state file before the request that made it is answered: the whole
  state is serialised, written to a temporary file, synced, renamed over the old one and the
  directory synced. Concurrent requests share one write. A build running at a stop is lost; the
  dossier is as it was before it, as in an export.
- **Browser UI.** One page shell serves every screen; `app.js` reads the API with the bearer
  token kept in `localStorage`. A write whose answer is lost is shown as "uncertain" and its
  retry reuses the same `Idempotency-Key` and body. Reads are numbered when sent; an older
  answer never replaces a newer one.
- **Consistency.** Requests run under one lock, so concurrent requests behave as some
  serial order. Reset and import bump an epoch; a build from an older epoch stops making
  calls and never writes.
