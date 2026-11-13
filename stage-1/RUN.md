# Dossier — stage 1

A company-profile service: `POST /dossiers` researches a company by its domain in the
background, through Nimble called via WebRouter, and `GET /dossiers/{domain}` returns six
fields, each with the excerpts that support it.

## Build and start

From this folder, with your Nimble key exported first (`export NIMBLE_API_KEY=...`):

```sh
docker build -t dossier-stage-1 . && docker run --rm -p 8080:8080 -e PORT=8080 \
  -e NIMBLE_API_KEY="$NIMBLE_API_KEY" dossier-stage-1
```

`GET http://localhost:8080/health` answers `{"status": "ok"}` once it is serving (within a
second or two). No other setup is needed: state is in memory and starts empty.

### Environment

| Variable | Use |
|---|---|
| `PORT` | Port to listen on (default `8080`) |
| `NIMBLE_API_KEY`, `NIMBLE_BASE_URL` | Read by WebRouter's `nimble` provider. Leave `NIMBLE_BASE_URL` unset for the live endpoint; never set it empty |
| `TAVILY_API_KEY`, `TAVILY_BASE_URL` | Optional. Tavily is used only when Nimble refuses a call |
| `LOG_LEVEL` | Python log level (default `INFO`) |
| `DOSSIER_CALL_TIMEOUT`, `DOSSIER_RESEARCH_TIMEOUT` | Seconds to wait for one provider call / a research run (defaults 45/180 live, 20/30 against another endpoint) |
| `DOSSIER_GATHER_WINDOW`, `DOSSIER_BUILD_CAP` | A build starts no call after `GATHER_WINDOW` s (default 120), nor one that could run past `BUILD_CAP` s (default 270) |

### Against the local mock web

From the kickoff package root, create the network and start the mock (see
`challenges/dossier/web/README.md`), then the service on the same network (its image
`dossier-stage-1` built as above):

```sh
docker network create dossier
docker build -t dossier-web challenges/dossier/web
docker run --rm -d --name web --network dossier -e MOCK_ADMIN_TOKEN=local-admin \
  -v "$PWD/challenges/dossier/web/corpus/sample:/data/corpus:ro" -p 8080:8080 dossier-web
docker run --rm --network dossier -p 8000:8000 -e PORT=8000 \
  -e NIMBLE_API_KEY=local -e NIMBLE_BASE_URL=http://web:8080/nimble \
  -e TAVILY_API_KEY=local -e TAVILY_BASE_URL=http://web:8080/tavily dossier-stage-1
```

## Tests

```sh
pip install -r requirements.txt                     # the unit tests import web_router
python3 -m unittest discover -s tests -t .          # Appendix A rule and build deadlines, no network
BASE=http://localhost:8000 MOCK=http://localhost:8080 python3 tests/smoke_api.py acme-robotics.test
```

The smoke script needs the service and the mock running (mock admin token `local-admin`).

## Layout

| File | Responsibility |
|---|---|
| `app/server.py` | HTTP routing, request parsing, error bodies (§3, §5–§8, §10) |
| `app/store.py` | All state behind one lock; builds in background threads; export/import |
| `app/builder.py` | One build: which provider calls to make and how each field is decided |
| `app/providers.py` | Every provider call through WebRouter, charged to the build's 80-unit budget |
| `app/support.py` | Appendix A: whether an excerpt supports a value |
| `app/pages.py` | Header lines vs prose; citable sentences |
| `app/validation.py` | Domains, timestamps, emails, paging parameters |
| `app/passwords.py` | scrypt password hashes |

## Design notes

- **Budget.** Each call's units are reserved before it is sent and refunded only when the
  provider refuses it with an error status; timeouts keep their cost. A call that would
  pass 80 units is not made. Refusals (429/500) are retried; unanswered calls are not.
- **Time.** A build starts calls only in its first 120 s and only when the call's timeout
  ends before 270 s, so it always ends `ready` or `failed` within 300 s; a started call is
  never abandoned early, and an unanswered call keeps its cost.
- **Research plan.** Lite searches for the domain (once) and the company name, a Nimble
  extract (1 unit) of each relevant result, then — only for fields still unknown — one
  lite search per field plus a Nimble research run, whose claims are checked against
  their page's prose.
- **Citations.** Every asserted value cites sentences of a page's prose (or a research
  excerpt that appears in it) that support it by Appendix A; the `Facts:` header is
  never used.
- **Consistency.** Requests run under one lock, so concurrent requests behave as some
  serial order. Reset and import bump an epoch; a build from an older epoch stops making
  calls and never writes.
