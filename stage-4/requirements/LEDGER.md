# Stage 4 — Requirement ledger (Analyst)

Source: `stage-4.md` (Dossier, Stage 4: independent sources, batches and provider failure, as quoted in the
coordinator's handoff) on top of the stage-3 ledger, which is carried forward in full below (319 rows: 261 from
stages 1-2, 58 `R3-*`). Every carried row must keep passing; their status here is reset to `open` until the stage-4
run, with the stage-3 result in parentheses (the four ruled rows stay ruled). Stage-4 rows (`R4-*`, 64) follow in
sections S4-A..S4-I: **383 rows in all**.
Verification: **AT** = black-box acceptance test (HTTP) in `acceptance/`, **UI** = acceptance test in a
real browser (Playwright, `data-testid` only), **REV** = Reviewer inspection, **UXR** = UX Reviewer
judgement, **M** = measurement by `acceptance/up.sh`. Ambiguities and the readings adopted are in
`RULINGS.md` (RUL-xx stage 1, RUL-S2-xx stage 2, RUL-S3-xx stage 3, RUL-S4-xx stage 4).

Status values: open (not yet run against a stage-4 build) / passing / failing / ruled / review.
Run: `acceptance/up.sh --build stage-4` (starts the mock web with the analyst corpus and the service on
a private docker network; `OLD_IMAGE`, `OLD2_IMAGE`, `OLD3_IMAGE` = the final stage-1/2/3 images also run the
upgrade tests) or `acceptance/run.sh --base-url http://HOST:PORT --mock-url … [--old-url … --old2-url … --old3-url …] --container <svc docker name>`.
Offline: `python -m pytest test_s4_unit.py test_timeline_unit.py test_rank_unit.py test_oracle_unit.py; python check_corpus.py`.

## §1 Scope / global invariants

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-GEN-01 | "Every value the service asserts cites at least one excerpt that a provider endpoint served to this service, and that excerpt supports the value. No citation is invented, reworded, or attached to a value it does not support." | 1 | AT | `citation_problems()` in every build test: oracle support + mock-log served text + corpus prose | open (stage 3: passing) |
| R-GEN-02 | "No build of a dossier spends more than 80 units (§9)." | 1, 9 | AT | per-build mock-log cost ≤ 80: `test_R_EVD_08_*`, `test_R_GEN_02_*`, `test_R_DEL_03_*` | open (stage 3: passing) |
| R-GEN-03 | "Contact data, people search, and fields other than the six in §4 are out of scope." | 1 | AT | `assert_dossier_shape` (exactly six fields) | open (stage 3: passing) |

## §2 Delivery and deployment

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-DEL-01 | "Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup." | 2 | R + M | files exist in `stage-1/`; `up.sh --build stage-1` | open (stage 3: passing) |
| R-DEL-02 | "The image must run on its own with `-e PORT=<port>` and a port mapping. All runtime dependencies, initialization and seed data must work within that single container. Compose configuration is not used." | 2 | M | `up.sh` runs the image alone with `-e PORT=8000 -p` | open (stage 3: passing) |
| R-DEL-03 | "every service must be able to research companies using Nimble alone." | 2 | AT | `test_R_DEL_03_*[tavily-down]` (expected fields unchanged) | open (stage 3: passing) |
| R-DEL-04 | "Tavily is optional … its absence must not prevent research while Nimble answers." | 2 | AT + M | `test_R_DEL_03_*[tavily-down, tavily-rate-limited]`; measured: image started without `TAVILY_*` | open (stage 3: passing) |
| R-DEL-05 | "every request to a provider goes through `web_router`: called in-process, or from a Python helper process … Calling a provider's API by any other route is not permitted." | 2 | R | code review; mock log shows only WebRouter-shaped calls | open (stage 3: passing) |
| R-DEL-06 | "The stage folder's dependency manifest lists `webrouter>=0.12.0`"; install `webrouter[search,extract,research]>=0.12.0` in the Docker build. | 2 | R | manifest + Dockerfile | open (stage 3: passing) |
| R-DEL-07 | Tavily base URL passed as `provider_config={"tavily": {"api_base_url": <TAVILY_BASE_URL>}}`; Nimble reads `NIMBLE_API_KEY`/`NIMBLE_BASE_URL`. | 2 | R + AT | review; any Tavily call appears in the mock log | open (stage 3: passing) |
| R-DEL-08 | Limits "CPU 2 vCPU", "Memory 3 GiB". | 2 | M | `up.sh` runs with `--cpus 2 --memory 3g`; whole suite passes | open (stage 3: passing) |
| R-DEL-09 | "Start to first healthy response 60 s". | 2, 3.2 | M | `up.sh` prints start→healthy seconds, fails if > 60 | open (stage 3: passing) |
| R-DEL-10 | "Concurrent requests up to 50 in flight". | 2 | AT | `test_R_CON_02_R_DEL_10_fifty_in_flight` | open (stage 3: passing) |
| R-DEL-11 | "Per-request timeout 5 s (10 s for `POST /_test/reset`)". | 2 | AT | client timeouts 5 s (10 s reset/import/export) on every request | open (stage 3: passing) |
| R-DEL-12 | "Outbound network … at run time, only the provider endpoints this specification lists"; "Runtime assets and dependencies must be included in the image." | 2 | R | Dockerfile/code review (no runtime downloads) | open (stage 3: passing) |
| R-DEL-13 | "Disk ephemeral; state need not survive a container restart." | 2 | — | superseded at stage 3 by R3-RST-01..07 (Disk row replaced) | ruled (carried from stage 3) |

## §3 Runtime contract

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-RUN-01 | "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." | 3.1 | M | `up.sh` (PORT=8000); measured: no `PORT` → 8080 | open (stage 3: passing) |
| R-RUN-02 | "`GET /health -> 200 {"status": "ok"}`" once ready | 3.2 | AT | `test_R_RUN_02_health` | open (stage 3: passing) |
| R-RUN-03 | "`/health` makes no provider call." | 3.2 | AT | `test_R_RUN_03_*` | open (stage 3: passing) |
| R-RST-01 | "Replace all service state with the fixture … subsequent requests must see only that fixture: no users other than the seeded ones" | 3.3 | AT | `test_R_RST_01_*` | open (stage 3: passing) |
| R-RST-02 | "… no dossiers" | 3.3 | AT | `test_R_RST_02_R_RST_03_*` | open (stage 3: passing) |
| R-RST-03 | "… and no stored idempotent responses." | 3.3 | AT | `test_R_RST_02_R_RST_03_*` | open (stage 3: passing) |
| R-RST-04 | "Repeated resets are supported." | 3.3 | AT | `test_R_RST_06_R_RST_04_*` | open (stage 3: passing) |
| R-RST-05 | "A build still running when reset is called must not change the state that follows the reset." | 3.3 | AT | `test_R_RST_05_*` | open (stage 3: passing) |
| R-RST-06 | "This control endpoint must be enabled in the delivered image and requires no authentication." `204 No Content` | 3.3 | AT | `test_R_RST_06_*` | open (stage 3: passing) |
| R-RST-07 | "Seeded users must be able to log in with the given password immediately." | 4 Fixture | AT | `test_R_RST_07_R_AUTH_08_*` | open (stage 3: passing) |
| R-RST-08 | "A fixture with two users sharing an email is a reset error: 422 `validation_failed`, changing nothing." | 4 Fixture | AT | `test_R_RST_08_*` | open (stage 3: passing) |
| R-RST-09 | "`now` is required and sets the clock (§3.4)." | 4 Fixture | AT | `test_R_RST_09_*` (RUL-14) | open (stage 3: passing) |
| R-RST-10 | Tokens issued before a reset are invalid after it. | 3.3 | AT | `test_R_RST_10_*` (RUL-11) | open (stage 3: passing) |
| R-RST-11 | Unparseable reset body → 400 `malformed_request`. | 3.3, 5 | AT | `test_R_RST_11_*` | open (stage 3: passing) |
| R-CLK-01 | "Reset sets the clock to the fixture's `now`." | 3.4 | AT | `test_R_CLK_01_R_BLD_03_*` | open (stage 3: passing) |
| R-CLK-02 | "The service keeps a clock that only reset and `POST /_test/clock` move. Every timestamp the service records or returns is read from this clock." | 3.4 | AT | `test_R_CLK_02_*` | open (stage 3: passing) |
| R-CLK-03 | "The clock stands still between calls: two requests with no clock call between them read the same time." | 3.4 | AT | `test_R_CLK_03_*` | open (stage 3: passing) |
| R-CLK-04 | "A `now` earlier than the clock's current time is 422 `validation_failed` and changes nothing." | 3.4 | AT | `test_R_CLK_04_*` | open (stage 3: passing) |
| R-CLK-05 | "`now` is an RFC 3339 timestamp with an explicit offset." | 3.4 | AT | `test_R_CLK_05_*` (RUL-13) | open (stage 3: passing) |
| R-CLK-06 | "`POST /_test/clock` requires no authentication." | 3.4 | AT | `test_R_CLK_02_R_CLK_06_*` | open (stage 3: passing) |
| R-CLK-07 | "Before the first reset the clock follows the system time." | 3.4 | R | review (RUL-35) | open (stage 3: passing) |
| R-CLK-08 | Equal `now` accepted. | 3.4 | AT | `test_R_CLK_08_*` (RUL-13) | open (stage 3: passing) |
| R-CLK-09 | `Z` accepted as an explicit offset. | 3.4 | AT | `test_R_CLK_09_*` (RUL-13) | open (stage 3: passing) |
| R-CNV-01 | "Requests and responses are `application/json; charset=utf-8`." | 3.5 | AT | `test_R_CNV_01_*` | open (stage 3: passing) |
| R-CNV-02 | "Timestamps in responses are RFC 3339 with an explicit offset" | 3.5 | AT | `parse_ts` on every timestamp | open (stage 3: passing) |
| R-CNV-03 | "Unknown fields in a request body are ignored, never an error." | 3.5 | AT | `test_R_CNV_03_*` (auth + dossiers) | open (stage 3: passing) |
| R-CNV-04 | "Unknown query parameters are ignored." | 3.5 | AT | `test_R_CNV_04_*` | open (stage 3: passing) |
| R-CNV-05 | "IDs are opaque strings of at most 64 characters." | 3.5 | AT | `assert_dossier_shape`, `test_R_AUTH_01_*` | open (stage 3: passing) |

## §4 Model

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-AUTH-12 | "Every authenticated user sees the same dossiers." | 4 Users | AT | `test_R_AUTH_12_*` | open (stage 3: passing) |
| R-DOM-01 | Domain "normalised: surrounding whitespace removed, lowercased, one trailing `.` removed, and one leading `www.` removed" (body and path) | 4 Domains | AT | `test_R_DOM_01_*` | open (stage 3: passing) |
| R-DOM-02 | "two or more labels … each label 1 to 63 characters of `a-z`, `0-9` and `-`, not starting or ending with `-`, and 253 characters or fewer in total. Anything else … is 422 `validation_failed`." | 4 Domains | AT | `test_R_DOM_02_*` (body, path, 254-char) | open (stage 3: passing) |
| R-DOM-03 | "including a URL with a scheme or a path, is 422" | 4 Domains | AT | `test_R_DOM_02_R_DOM_03_*` | open (stage 3: passing) |
| R-DOM-04 | "`Acme-Robotics.TEST.`, `www.acme-robotics.test` and `acme-robotics.test` name the same company and the same dossier. Responses always carry the normalised domain." | 4 Domains | AT | `test_R_DOM_01_R_DOM_04_*`, `test_R_POST_03_*` | open (stage 3: passing) |
| R-DOM-05 | Only *one* trailing dot and *one* leading `www.` are removed. | 4 Domains | AT | `test_R_DOM_05_*` (`www.www.…`, `acme.test..`, `www.test`) | open (stage 3: passing) |
| R-FLD-01 | "A dossier has exactly these six fields" with the listed types; `headcount_range` one of the eight ranges | 4 Fields | AT | `assert_dossier_shape` | open (stage 3: passing) |
| R-FLD-02 | "`status` is `known` when `value` is not null, and `unknown` when it is." "An `unknown` field has `"value": null` and `"citations": []`." | 4 Fields | AT | `assert_dossier_shape` | open (stage 3: passing) |
| R-FLD-03 | "A `known` field has one or more citations." `url` = page the excerpt was served for, `provider` is `nimble` or `tavily`, the one that served it. | 4 Fields | AT | `assert_dossier_shape`, `citation_problems` (log provider + url) | open (stage 3: passing) |
| R-FLD-04 | "A string value is written as the supporting excerpt writes it, without surrounding whitespace." | 4 Fields | AT | oracle value equality (corpus tests) | open (stage 3: passing) |
| R-FLD-05 | "A headcount the web states as a number, or as a range that fits inside one of the ranges above, has the range that contains it as its value." | 4 Fields | AT | talloway (1,450), vantorra (51-200), sablewood (10,500), wrenfield (300), orrin (75) | open (stage 3: passing) |
| R-EVD-01 | "every build makes exactly one [successful search] whose query is exactly the company's normalised domain … its other such searches use other queries. A search that a provider answers with an error does not count." | 4 Evidence | AT | `check_log_rules` in corpus tests, `test_R_IDEM_10_*`, `test_R_REF_*`, `test_R_DEL_03_*` (RUL-28) | open (stage 3: passing) |
| R-EVD-02 | "The excerpt is copied character for character from that served text, except that any run of whitespace may be written as a single space. It is 1 to 500 characters long." | 4 Evidence | AT | `citation_problems` | open (stage 3: passing) |
| R-EVD-03 | "It is taken from the page's prose (below), not from its header." | 4 Evidence | AT | `test_R_EVD_03_R_EVD_10_*`; corpus-prose check in `citation_problems` | open (stage 3: passing) |
| R-EVD-04 | "`url` is the URL of the page the excerpt was served for" | 4 Fields | AT | `citation_problems` (served for that url by that provider) | open (stage 3: passing) |
| R-EVD-05 | "The claim is asserted only when its citation supports it. A field is `unknown` when no evidence supports a value for it, even when a research answer claims one." | 4 Evidence | AT | orrin-bay `funding_total` unknown | open (stage 3: passing) |
| R-EVD-06 | Evidence includes "every claim that a `nimble` research run for the company asking for all six fields answers with" | 4 Evidence | AT | `test_R_EVD_06_*`, orrin-bay ceo/headcount (RUL-09) | open (stage 3: passing) |
| R-EVD-07 | "When the evidence supports more than one value for a field, the field holds one of them and cites only excerpts that support that value." | 4 Evidence | AT | `test_R_EVD_07_*` (ledgerline) | open (stage 3: passing) |
| R-EVD-08 | "When a build completes `ready`, each field is `known` exactly when the evidence (§4) supports a value for it." | 8 Builds | AT | `test_R_EVD_08_R_SUP_corpus_company[*]` (11 companies incl. fenwick-orchards: >10 pages, facts only reachable by other queries naming the company) | open (stage 3: passing) |
| R-EVD-09 | Evidence is each page "with its full text" | 4 Evidence | AT | `test_R_EVD_09_*` (sablewood), talloway history (RUL-10) | open (stage 3: passing) |
| R-EVD-10 | "The header line `Facts:` … is informative only: citations come from the prose" | 4 Pages | AT | `test_R_EVD_03_R_EVD_10_*` (quorra) | open (stage 3: passing) |
| R-EVD-11 | Degraded providers: with Nimble extract + research and Tavily extract + search all refused, a `ready` build still has every field `known` that the evidence (full page texts) supports, and spends ≤ 80. | 4, 8, 9 | AT | `test_R_EVD_11_extract_and_research_refused[*]` (8 companies incl. fenwick-orchards) (RUL-34, RUL-36, Reviewer F4) | open (stage 3: passing) |

## §5 Errors

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-ERR-01 | "Every 4xx and 5xx response carries this body: `{ "error": { "code": …, "message": … } }`" | 5 | AT | `Api.req` checks every 4xx | open (stage 3: passing) |
| R-ERR-02 | "400 `malformed_request` Unparseable body, or a field of the wrong JSON type" | 5 | AT | `test_R_ERR_02_*` (auth, dossiers, reset, import, clock) (RUL-15) | open (stage 3: passing) |
| R-ERR-03 | "401 `unauthenticated` Missing, malformed or unknown bearer token" | 5, 6 | AT | `test_R_AUTH_09_*` | open (stage 3: passing) |
| R-ERR-04 | "404 `not_found` No such resource" | 5 | AT | `test_R_ERR_04_*`, `test_R_REF_03_*` | open (stage 3: passing) |
| R-ERR-05 | "Requests must not produce 5xx responses, including under concurrent load and when a provider endpoint answers with an error." | 5 | AT | every request (`Api.req` raises on 5xx); weather, faults, 50-in-flight | open (stage 3: passing) |
| R-ERR-06 | "`limit` integer 1 to 200", "`offset` integer 0 or more", "An integer-valued query parameter is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422" | 5 | AT | `test_R_ERR_06_*` (RUL-19) | open (stage 3: passing) |
| R-ERR-07 | "A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`" | 5 | AT | domain, email, password, display_name, clock, import tests | open (stage 3: passing) |

## §6 Authentication

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-AUTH-01 | "`POST /auth/signup` → 201 `{ "user_id", "display_name", "token" }`" | 6 | AT | `test_R_AUTH_01_*` | open (stage 3: passing) |
| R-AUTH-02 | "`POST /auth/login` → 200 `{ "user_id", "display_name", "token" }`" | 6 | AT | `test_R_AUTH_02_*` | open (stage 3: passing) |
| R-AUTH-03 | "Email already registered → 409 `email_taken`" (incl. seeded emails) | 6 | AT | `test_R_AUTH_03_*` | open (stage 3: passing) |
| R-AUTH-04 | "Password shorter than 8 characters → 422" | 6 | AT | `test_R_AUTH_04_*` (7 rejected, 8 accepted) | open (stage 3: passing) |
| R-AUTH-05 | "`email` not of the form `local@domain` → 422" | 6 | AT | `test_R_AUTH_05_*` (RUL-31) | open (stage 3: passing) |
| R-AUTH-06 | "`display_name` empty or longer than 100 characters → 422" | 6 | AT | `test_R_AUTH_06_*` (100 accepted) | open (stage 3: passing) |
| R-AUTH-07 | "Wrong password or unknown email on login → 401 `unauthenticated`" | 6 | AT | `test_R_AUTH_07_*` | open (stage 3: passing) |
| R-AUTH-08 | "For a user seeded by the fixture, `user_id` is that user's `id` in the fixture." | 6 | AT | `test_R_RST_07_R_AUTH_08_*` | open (stage 3: passing) |
| R-AUTH-09 | "Every other endpoint requires a bearer token … A request … that lacks a valid token is 401 `unauthenticated`, even when it also lacks a required `Idempotency-Key`." | 6 | AT | `test_R_AUTH_09_*` | open (stage 3: passing) |
| R-AUTH-10 | "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions." | 6 | AT | `test_R_AUTH_10_*` (both) | open (stage 3: passing) |
| R-AUTH-11 | "Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2 … Plaintext password storage is not permitted." | 6 | R + AT | code review; `test_R_AUTH_11_*` (no plaintext in export) | open (stage 3: passing) |
| R-AUTH-13 | Missing signup/login fields → 422; wrong types → 400. | 5, 6 | AT | `test_R_AUTH_13_*`, `test_R_ERR_02_auth_*` (RUL-33) | open (stage 3: passing) |
| R-CON-01 | Concurrent signups with one email: exactly one 201. | 6, 11 | AT | `test_R_CON_01_concurrent_signup_same_email` | open (stage 3: passing) |

## §7 Idempotency

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-IDEM-01 | "Header absent or empty → 400 `missing_idempotency_key`" (both write paths) | 7 | AT | `test_R_IDEM_01_*` | open (stage 3: passing) |
| R-IDEM-02 | "The key is scoped to the authenticated user. Two different users may use the same key string with no interaction between them." | 7 | AT | `test_R_IDEM_02_*` | open (stage 3: passing) |
| R-IDEM-03 | "Replay: same key, same body → 200, body identical to the original response as a JSON value" | 7 | AT | `test_R_IDEM_03_*` (202- and 200-originals) | open (stage 3: passing) |
| R-IDEM-04 | "Same key, different body → 409 `idempotency_key_reuse`" | 7 | AT | `test_R_IDEM_04_*` | open (stage 3: passing) |
| R-IDEM-05 | "The same key with the same body on a different path is a different request, not a replay, and must succeed normally." | 7 | AT | `test_R_IDEM_05_*` | open (stage 3: passing) |
| R-IDEM-06 | "`Acme-Robotics.test` and `acme-robotics.test` in a path or body are different requests for this rule" | 7 | AT | `test_R_IDEM_06_*` (RUL-20) | open (stage 3: passing) |
| R-IDEM-07 | "Key reused after the original request failed with 4xx → Treated as a first use" | 7 | AT | `test_R_IDEM_07_*` (422 and 404) | open (stage 3: passing) |
| R-IDEM-08 | "'Same body' means the same JSON value after parsing — key order and whitespace do not matter … a body that differs from the first only in unknown fields is the same body" | 7 | AT | `test_R_IDEM_08_*` (RUL-21) | open (stage 3: passing) |
| R-IDEM-09 | "`POST /dossiers/{domain}/refresh` takes no body; any body sent to it is ignored and plays no part in deciding a replay." | 7 | AT | `test_R_IDEM_09_*` (RUL-17) | open (stage 3: passing) |
| R-IDEM-10 | "For concurrent identical requests with an unused key, exactly one returns the normal response. The others return 200 with the same body. The operation takes effect only once." | 7 | AT | `test_R_IDEM_10_*` (create + refresh) | open (stage 3: passing) |
| R-IDEM-11 | "A successful replay returns the original response, even after the dossier has changed. It starts no build and makes no provider call." | 7 | AT | `test_R_IDEM_03_R_IDEM_11_*`, `test_R_IDEM_09_*` | open (stage 3: passing) |
| R-IDEM-12 | "After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before field validation." | 7 | AT | `test_R_IDEM_12_*` (RUL-16) | open (stage 3: passing) |
| R-IDEM-13 | "`Idempotency-Key` 1 to 255 characters, otherwise 422 `validation_failed`" | 5 | AT | `test_R_IDEM_13_*` | open (stage 3: passing) |

## §8 API

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-BLD-01 | "A dossier has at most one build running at a time." | 8 | AT | `test_R_REF_02_R_BLD_01_*`, `test_R_IDEM_10_*` | open (stage 3: passing) |
| R-BLD-02 | "A build ends in `ready` when it completed, or `failed` when none of its provider calls succeeded. A failed build leaves the fields as they were." | 8 | AT | `test_R_BLD_02_*` | open (stage 3: passing) |
| R-BLD-03 | "A build's time is the clock's time when the request that started it was received." (`researched_at`) | 8 | AT | `test_R_CLK_*`, `test_R_GET_03_*`, `test_R_REF_04_*` | open (stage 3: passing) |
| R-BLD-04 | "A build whose provider calls each answer within one second ends within 10 seconds of the request that started it." | 8 | AT | `test_R_BLD_04_*` | open (stage 3: passing) |
| R-BLD-05 | Live providers: no give-up on a call waiting < 30 s, no time-based stop in the first 120 s, ends within 300 s. | 8 | R | code review of timeouts (live providers not reachable in tests) | ruled (carried from stage 3) |
| R-BLD-06 | "Reading a dossier, listing dossiers and every other request except `POST /dossiers` and `POST /dossiers/{domain}/refresh` make no provider call." | 8 | AT | `test_R_BLD_06_*`, `test_R_RUN_03_*`, `test_R_EXP_*` (import) | open (stage 3: passing) |
| R-POST-01 | "When no dossier exists … creates one, starts its first build and returns 202 `{dossier_id, domain, state: building}`" | 8 | AT | `test_R_POST_01_*` | open (stage 3: passing) |
| R-POST-02 | "When a dossier already exists … starts no build and returns 200 with that dossier's `dossier_id`, `domain` and current `state`." | 8 | AT | `test_R_POST_02_*`, `test_R_REF_02_*` (RUL-26) | open (stage 3: passing) |
| R-POST-03 | "Concurrent requests for the same domain create one dossier and start one build, whatever their keys." | 8 | AT | `test_R_POST_03_R_CON_03_*` | open (stage 3: passing) |
| R-POST-04 | "`domain` missing → 422"; "invalid after normalisation → 422" | 8 | AT | `test_R_POST_04_*`, `test_R_DOM_02_*` | open (stage 3: passing) |
| R-GET-01 | `GET /dossiers/{domain}` shape: `dossier_id, domain, state, researched_at, spent_units, fields` | 8 | AT | `assert_dossier_shape` | open (stage 3: passing) |
| R-GET-02 | "`fields` always holds all six fields. Before the first build completes `ready`, every field is `unknown`." | 8 | AT | `test_R_GET_02_*`, `test_R_BLD_02_*` | open (stage 3: passing) |
| R-GET-03 | "While a later build runs, `fields` are those of the last build that completed `ready`." `state` is `building` while a build runs. | 8 | AT | `test_R_GET_03_*` | open (stage 3: passing) |
| R-GET-04 | "`researched_at` is the time of the last build that completed `ready`, or null." | 8 | AT | `test_R_GET_02/03_*`, `test_R_BLD_02_*` | open (stage 3: passing) |
| R-GET-05 | "`spent_units` is the total cost (§9) of every provider call made for this dossier, by every build, since it was created." | 8 | AT | `test_R_REF_01_*`, `test_R_GEN_02_*`, corpus tests (== mock-log cost) | open (stage 3: passing) |
| R-GET-06 | "The domain in the path is normalised (§4). No dossier for it is 404 `not_found`." | 8 | AT | `test_R_DOM_01_R_GET_06_*`, `test_R_ERR_04_*` | open (stage 3: passing) |
| R-REF-01 | Refresh "Starts a new build … returns 202 `{dossier_id, domain, state: building}`"; "its build makes provider calls whether or not anything has changed … its spending counts in `spent_units`." | 8 | AT | `test_R_REF_01_*` | open (stage 3: passing) |
| R-REF-02 | "A refresh received while a build of the dossier is running starts no second build and returns 202 with the same body." | 8 | AT | `test_R_REF_02_*`, `test_R_CON_01_serializable_*` | open (stage 3: passing) |
| R-REF-03 | "No dossier for the domain → 404 `not_found`" | 8 | AT | `test_R_REF_03_*` | open (stage 3: passing) |
| R-REF-04 | A refresh researches again and replaces the fields with the new result. | 8 | AT | `test_R_REF_04_*` (mock epoch 0→1) | open (stage 3: passing) |
| R-LST-01 | List item: `dossier_id, domain, state, legal_name, researched_at, spent_units`; "`legal_name` is the value of the dossier's `legal_name` field, or null." | 8 | AT | `test_R_LST_01_*` | open (stage 3: passing) |
| R-LST-02 | "only dossiers whose domain or `legal_name` contains `q`, compared case-insensitively … An empty `q` lists every dossier." | 8 | AT | `test_R_LST_02_*` | open (stage 3: passing) |
| R-LST-03 | "Dossiers are ordered by domain ascending." | 8 | AT | `test_R_LST_03_*` | open (stage 3: passing) |
| R-LST-04 | "`limit` defaults to 50, range 1 to 200. `offset` defaults to 0. `has_more` is true when items exist beyond the last one returned." | 8 | AT | `test_R_LST_04_*` (incl. 52 dossiers) | open (stage 3: passing) |

## §9 Providers and cost

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-COST-01 | Unit costs per the §9 table; `spent_units` equals them. | 9 | AT | spent_units == mock-log cost (mock implements the table) | open (stage 3: passing) |
| R-COST-02 | "A build stops making provider calls before its spending would exceed 80 units, and completes with the pages and research claims it has obtained." | 9 | AT | per-build cost ≤ 80 in all build tests | open (stage 3: passing) |
| R-COST-03 | "A research request names the company by its domain in its query, and names the fields it asks for by the field names in §4, as the property names of its output schema." | 9 | AT | `check_log_rules` | open (stage 3: passing) |
| R-COST-04 | "An extract through `nimble` does not set `render`." | 9 | AT | `check_log_rules` (cost = 1 per URL) | open (stage 3: passing) |
| R-COST-05 | "A call that a provider refuses with an error status costs nothing." | 9 | AT | `test_R_BLD_02_*` (spent 0) | open (stage 3: passing) |
| R-COST-06 | "A call whose answer does not arrive, because it times out … costs its units" | 9 | AT | `test_R_COST_06_*` (delay; spent == log) | open (stage 3: passing) |

## §10 Export and import

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-EXP-01 | "Return 200 from export with a JSON object containing `track: "dossier"`, `format_version: 1` and `state`" | 10 | AT | `test_R_EXP_01_*` | open (stage 3: passing) |
| R-EXP-02 | "Import takes that entire object and atomically replaces the service's state, returning 204. It must accept an unchanged export produced by this service." | 10 | AT | `test_R_EXP_02_to_R_EXP_10_roundtrip` | open (stage 3: passing) |
| R-EXP-03 | "Preserve accounts and hashed-password login, existing bearer tokens, dossiers with their ids, states, fields, citations, `researched_at` and `spent_units`, all completed idempotent request bodies and original responses." | 10 | AT | roundtrip | open (stage 3: passing) |
| R-EXP-04 | "Failed request keys remain reusable." | 10 | AT | roundtrip | open (stage 3: passing) |
| R-EXP-05 | "Import removes all previous destination data and credentials." | 10 | AT | roundtrip (Dora) | open (stage 3: passing) |
| R-EXP-06 | "Import is replacement, not merge; repeating it restores the exported state without duplicating anything." | 10 | AT | roundtrip | open (stage 3: passing) |
| R-EXP-07 | "Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination." | 10 | AT | `test_R_EXP_07_*` (RUL-23) | open (stage 3: passing) |
| R-EXP-08 | "Import makes no provider call" | 10 | AT | roundtrip (mock log empty) | open (stage 3: passing) |
| R-EXP-09 | "Export and import do not change the clock." | 10 | AT | roundtrip, `test_R_EXP_09_*` | open (stage 3: passing) |
| R-EXP-10 | "Reset clears all state, including imported state." | 10 | AT | roundtrip | open (stage 3: passing) |
| R-EXP-11 | "An export taken while a build is running holds the dossier as it was before that build; after import, that dossier is in the state of its last completed build, or `failed` with every field `unknown` when no build had completed." | 10 | AT | `test_R_EXP_11_*` (first build, refresh) (RUL-22) | open (stage 3: passing) |
| R-EXP-12 | "Export is an atomic, read-only snapshot; subsequent source writes do not change it." | 10 | AT | roundtrip (two exports equal) | open (stage 3: passing) |
| R-EXP-13 | Export/import are unauthenticated control endpoints. | 10 | AT | all export/import tests send no token | open (stage 3: passing) |

## §11 Concurrency

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-CON-02 | "Concurrent requests must produce the same results as executing them one at a time in some order." / 50 in flight | 11, 2 | AT | `test_R_CON_02_*`, `test_R_IDEM_10_*`, `test_R_POST_03_*` | open (stage 3: passing) |
| R-CON-03 | "The requirements above hold at every read." | 11 | AT | `test_R_GET_02/03_*` (reads during builds) | open (stage 3: passing) |

## Appendix A — support rule (end-to-end on the analyst corpus, judged by `oracle.py`)

Each row is checked by `test_R_EVD_08_R_SUP_corpus_company[<domain>]` and by the oracle unit
tests (`test_oracle_unit.py`, which reproduce every example the specification gives).

| ID | Requirement | § | Corpus cases | Status |
|---|---|---|---|---|
| R-SUP-01 | A.1 sentences: split at `.`/`!`/`?` (+ closing `"”’)`) followed by whitespace; a `.` ending a legal-form suffix does not end a sentence; rule 1 "It is a single sentence". | A.1, A.2 | meridel founded (`!` split), wrenfield founded (`Inc.` inside), vantorra legal (`S.A.` inside), wrenfield headcount (`."` closer) | open (stage 3: passing) |
| R-SUP-02 | "It names the company: it contains the company's normalised domain, or the company's name" (whole word, case-insensitive) | A.2 | sablewood hq/founded by domain | open (stage 3: passing) |
| R-SUP-03 | "It contains a statement phrase for F" | A.2, A.3 | meridel `raised CHF 5 million` (no amount); ledgerline `€30M`; unknown fields of ledgerline | open (stage 3: passing) |
| R-SUP-04 | "It contains none of the negating phrases" | A.2, A.3 | quorra (not, former, reportedly, in talks to, would), orrin funding (hopes to) | open (stage 3: passing) |
| R-SUP-05 | "every value in F's format that it contains normalises to V" | A.2 | meridel ceo (two names), meridel headcount (120 and 1998), quorra headcount (10-50) | open (stage 3: passing) |
| R-SUP-06 | legal_name format, "the shortest counts", suffix list | A.4 | talloway `, Inc.`, vantorra `Holdings S.A.`, meridel `Pty Ltd`, sablewood `Ltd`, wrenfield `AG` (shortest before `GmbH`) | open (stage 3: passing) |
| R-SUP-07 | hq_city: "longest run of capitalised words joined by single spaces or by `-`" directly after the phrase | A.4 | `Porto Alegre`, `Saint-Malo`, `Tromsø`, `Den Haag`, `Zürich`, `Vila Nova` (stops at `de`) | open (stage 3: passing) |
| R-SUP-08 | ceo: run of two or three capitalised words, name and phrases taken out first | A.4 | `Mara Quintero`, `Noor Haddad` (after `Chief Executive Officer`), `Maria Elena Costa`, `Jonas Ek`, `Priya Lindqvist` | open (stage 3: passing) |
| R-SUP-09 | founded_year: four digits 1800–2099, not part of an amount | A.4 | 2011, 1987, 1996, 2008, 1979, 2001, {2003, 2004} | open (stage 3: passing) |
| R-SUP-10 | headcount: number ≥ 1 without decimal part, not part of an amount; ranges hold two numbers | A.4, A.5 | 1,450→1001-5000; 51-200; 10,500→10001+; 300→201-500; 75→51-200 | open (stage 3: passing) |
| R-SUP-11 | Amount forms (`$`/`US$`/`USD`, scales `k m mn bn thousand million billion`, `dollars`/`US dollars`); "Amounts in other currencies are not amounts"; normalisation to whole dollars | A.4, A.5 | `US$ 37.5 million`, `$4.5m`, `$1.2345m`, `$850k`, `750 thousand US dollars`, `$12M`/`12 million dollars`/`US$12 million`/`$12,000,000`, `€30M`, `CHF 5 million` | open (stage 3: passing) |
| R-SUP-12 | A company with no evidence: `ready`, all fields unknown | A, 8 | `nowhere-at-all.test` | open (stage 3: passing) |
| R-SUP-13 | The analyst oracle reproduces every example in §4 and Appendix A | A | `test_oracle_unit.py` (offline) | open (stage 3: passing) |


# ================= STAGE 2 ROWS =================

Source for the rows below: `stage-2.md` (as handed off by the coordinator; quoted). "Test" names are
in `acceptance/` (`test_candidates.py` API+corpus, `test_web_ratelimit.py`, `test_ui_contract.py` HTTP,
`test_ui_screens.py` / `test_ui_flows.py` / `test_ui_visual.py` browser, `test_upgrade.py`, offline
`test_rank_unit.py`). **UI** = acceptance test in a real browser; **REV** = review by the Reviewer;
**UXR** = judgement by the UX Reviewer (not machine-checkable).

## S2-A Operations, page headers, page text

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-GEN-04 | "A field's selected value is the one the selection rule below picks from the field's candidates; the same candidates always yield the same value." | all operations 3 | AT | `test_R_CAN_08_*` (3 builds agree), every corpus test (`candidate_problems` vs `rank.py`), `test_R_UPG_04` | open (stage 3: passing) |
| R-PGK-01 | "`Kind: own`, `Kind: filing`, `Kind: news`, `Kind: aggregator` — the page's kind" | Page kind | AT | `test_R_CAN_04_default_kind_from_url_host` (kinds on candidates), `test_R_EVI_01_*` (`data-kind`) | open (stage 3: passing) |
| R-PGK-02 | "A page with no `Kind` line … is of kind `own` when the host of its URL, normalised as `stage-1.md` normalises a domain, is the company's domain, and of kind `aggregator` otherwise." (`www.`, case, trailing dot normalised; a subdomain is another host) | Page kind | AT | `test_R_CAN_04_*` (kestrel-optics: /a, www./b, Kestrel-Optics.TEST./i own; about. subdomain, other hosts aggregator) | open (stage 3: passing) |
| R-PGK-03 | "…or with a value not listed above, is of kind `own` when the host … is the company's domain, and of kind `aggregator` otherwise." (`blog` on the company's host → own, elsewhere → aggregator; `NEWS` is not listed: RUL-S2-01) | Page kind | AT | `test_R_CAN_04_*` | open (stage 3: passing) |
| R-PGK-04 | "`Published: <RFC 3339 timestamp>` — When the page was published" → candidate `published_at` | Page kind | AT | `test_R_CAN_05_publication_time_validity` (instants incl. offset and fraction), `test_R_SEL_02_publication_instants_*` | open (stage 3: passing) |
| R-PGK-05 | "A page with no `Published` line, or with a value that is not an RFC 3339 timestamp, has no publication time." (date only, no offset, impossible day, free text, absent → null) | Page kind | AT | `test_R_CAN_05_*` (p3–p7 null) (RUL-S2-02) | open (stage 3: passing) |
| R-TXT-01 | "a page's **text** is the text a browser shows once the page has loaded, without clicking controls." | Page text | AT | `test_R_WEB_01_text_is_what_a_browser_shows` (vesper-lanterns: static text says Venice/1989, browser text Murano/1998) | open (stage 3: passing) |
| R-TXT-02 | "Evidence (§4) is read from page text so defined, and a citation's excerpt must appear in the page's text." | Page text | AT | `candidate_problems` / `citation_problems` (excerpt ∈ corpus browser text) in every build test; `test_R_WEB_01_*` (no stale excerpt) | open (stage 3: passing) |
| R-TXT-03 | "A citation's `provider` is the provider that served the text the excerpt was copied from." | Page text | AT | `candidate_problems` + `citation_problems`: the excerpt is in the text that provider served for that URL (mock log) | open (stage 3: passing) |
| R-TXT-04 | "Activating disclosure controls is not required. The graded corpus contains no facts that require a click to reveal them." | Page text | — | nothing to verify (no control in the analyst corpus; RUL-S2-03) | ruled (carried from stage 3) |

## S2-B Web access, cost, rate limits

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-WEB-01 | "an extract through `nimble` may ask Nimble to load the page in a browser … `provider_options={"render": True}` on WebRouter's extract." The build must obtain the browser text of pages whose served text differs. | Web access | AT + REV | `test_R_WEB_01_*`, `test_R_CAN_06_*`; REV: `render` via provider_options only, no other route | open (stage 3: passing) |
| R-WEB-02 | "A service may use Nimble's rendered extract alone to obtain every page's browser text; neither browser vendor is required." | Web access | AT | `test_R_WEB_03_browser_vendors_are_optional[error,rate_limit]`, `test_R_WEB_03_nimble_alone_*` | open (stage 3: passing) |
| R-WEB-03 | Environment `KERNEL_API_KEY`, `KERNEL_BASE_URL`, `BROWSERBASE_API_KEY`, `BROWSERBASE_BASE_URL`; "`provider_config={"kernel": {"base_url": …}, "browserbase": {"base_url": …}}`" when the vendors are used; WebRouter only. | Web access | REV | code review (R-DEL-05 carried: all provider calls through `web_router`) | open (stage 3: passing) |
| R-WEB-04 | Costs: "Extract through `nimble` that loads the page in a browser — 3 per URL requested, including a URL for which no page is returned"; session open kernel 0 / browserbase 2; "Each page served to a session … 1"; browse run 4; "A failed open, a failed page load and releasing a session cost nothing." | Web access | AT | `spent_units == mock log cost` in all build tests; `test_R_WEB_02_render_costs_and_budget` (render cost ∈ {n, 3n}) | open (stage 3: passing) |
| R-WEB-05 | "Each provider keeps at most 4 sessions open at once; opening another is answered with an error. A session that no client has been connected to for 60 seconds is closed." → a service must not leak sessions | Web access | AT | `test_R_WEB_04_sessions_are_released` (vacuous when the service opens none) | open (stage 3: passing) |
| R-WEB-06 | "No build of a dossier spends more than 80 units (§9)" (R-GEN-02, now with render at 3 per URL): "A build stops making provider calls before its spending would exceed 80 units" | stage 1 §9 | AT | per-build cost ≤ 80 in every corpus test (companies with 4–12 pages) | open (stage 3: passing) |
| R-RL-01 | "a provider may answer any call with 429. A call answered 429 costs nothing." | Rate limits | AT | `test_R_RL_01_*` (every 429 log entry cost 0; spent_units == log cost) | open (stage 3: passing) |
| R-RL-02 | "No call is answered 429 more than three times in a row" — a build keeps retrying a refused call and ends with the same evidence | Rate limits | AT | `test_R_RL_01_*[harlow,vesper]` (throttle on all methods), `test_R_RL_02_persistent_429_three_times_then_answered` | open (stage 3: passing) |
| R-RL-03 | "The same call … made again less than one second after a 429 for it … is answered 429 again." → a retry policy that hammers is still correct, only wasteful; no requirement on the service beyond R-RL-02 | Rate limits | AT | covered by R-RL-02 | open (stage 3: passing) |
| R-RL-04 | "Time a build spends waiting to make a call again after a 429 does not count toward the 10 seconds of `stage-1.md` §8." | Rate limits | AT | `test_R_RL_01_*`: elapsed ≤ 10 s + 3 s per 429 + 3 s (RUL-S2-04) | open (stage 3: passing) |
| R-RL-05 | "…except that opening a session while its provider keeps 4 open is answered 429 until one of them closes." → the service survives a 429 session open | Rate limits | AT | `test_R_WEB_03_browser_vendors_are_optional[rate_limit]` | open (stage 3: passing) |
| R-RL-06 | Under 429 weather nothing the service answers is 5xx and every stage-1 rule holds on the builds that complete | Rate limits + R-ERR-05 | AT | `test_R_RL_04_weather_everything_holds_per_build`; carried `test_R_ERR_05_weather_*` | open (stage 3: passing) |

## S2-C Candidates

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-CAN-01 | "A **candidate** is one value for one field, supported by one excerpt of one page. Every value that a page of the evidence (§4) supports for a field is a candidate of that field, once for each such page." | Candidates | AT | `candidate_problems`: (url, value) list equals the oracle's for 16 companies (`test_R_EVD_08_R_SUP_corpus_company[*]`); `test_R_STS_*`, literal lists in `test_candidates.py` | open (stage 3: passing) |
| R-CAN-02 | "The evidence now also holds the page that each research claim of the evidence cites, whether or not the citation supports its claim: a build reads that page as it reads any other." | Candidates | AT | `test_R_CAN_06_*` (non-searchable /press, cited by an unsupported claim, still yields Murano) | open (stage 3: passing) |
| R-CAN-03 | "A research claim whose citation does not support it is still not a candidate." | Candidates | AT | `test_R_CAN_06_*` (20000000 absent), carried orrin-bay `funding_total` unknown | open (stage 3: passing) |
| R-CAN-04 | "`url`, `excerpt` and `provider` follow the citation rules in §4." "A candidate's `provider` is a provider that served the text its excerpt is taken from" | Candidates | AT | `candidate_problems` (supports by oracle, in page text, served by that provider for that URL) | open (stage 3: passing) |
| R-CAN-05 | "`kind` is the page's kind, and `published_at` its publication time or null." | Candidates | AT | `test_R_CAN_04/05_*` | open (stage 3: passing) |
| R-CAN-06 | "`retrieved_at` is the time of the build that gathered the candidate (§8, Builds)." | Candidates | AT | `test_R_CAN_07_*` (clock moved between builds), `candidate_problems` (== researched_at) | open (stage 3: passing) |
| R-CAN-07 | "`selected` is true on exactly one candidate of a field that has candidates, the one the rule picks, and false on the others." "`candidates` lists the candidates … in the order the selection rule ranks them, the selected one first." | Candidates | AT | `candidate_structure_problems` (every dossier body in every build test), literal orders in `test_candidates.py` | open (stage 3: passing) |
| R-CAN-08 | "`candidates` lists the candidates of the last build that completed `ready`" — a failed build or a running one leaves them as they were | Candidates | AT | `test_R_CAN_07_*` (failed refresh keeps fields incl. candidates; mid-build GET equals previous) | open (stage 3: passing) |
| R-CAN-09 | "A field with no candidate has `"candidates": []` and is `unknown`." | Candidates | AT | `test_R_STS_03_*`, `test_R_STS_01_to_03_*` (ceo, founded_year of tarn-biotech), `assert_dossier_shape` | open (stage 3: passing) |
| R-CAN-10 | "Two values are the same value when they are equal as JSON values; strings are compared exactly, after removing surrounding whitespace." | Candidates | AT | tarn-biotech: `Tarn Biotech Ltd` ≠ `Tarn Biotech Limited` (contested), 120 and 150 both `51-200` (known), `$9M` = `US$ 9 million` | open (stage 3: passing) |
| R-CAN-11 | "Only an imported candidate (below) has a null `kind`; it has the authority of `aggregator`." | Candidates | AT | `test_R_UPG_01_*` (null kind/published_at, rank order with kind null as aggregator), `test_rank_unit` | open (stage 3: passing) |
| R-CAN-12 | The `candidates` key is carried by every field of every dossier response (GET, after import, after export round trip) | Candidates | AT | `assert_dossier_shape` everywhere; `test_R_UPG_05_*` (export/import preserves candidates) | open (stage 3: passing) |

## S2-D The selection rule

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-SEL-01 | "**Authority** of the page's kind: `own` and `filing` rank equal and highest, then `news`, then `aggregator`." | Rule 1 | AT | `test_R_SEL_01_to_05_harlow_ceo_authority_over_recency` (newest news page below own/filing), kestrel-optics order | open (stage 3: passing) |
| R-SEL-02 | "**Recency** within the same authority: the later `published_at` ranks higher. A candidate without a publication time ranks below every candidate of the same authority that has one." | Rule 2 | AT | `test_R_SEL_02_*` ×2 (recency beats URL; instants not strings; offsets), `test_R_CAN_05_*` | open (stage 3: passing) |
| R-SEL-03 | "**URL**: when authority and publication time are equal, the candidate whose `url` is smaller, comparing the strings by Unicode code point, ranks higher" | Rule 3 | AT | `test_R_SEL_03_*` (filing 12:00+02:00 = own 10:00Z; filing's URL smaller), kestrel (`K` before `k`, www. host) | open (stage 3: passing) |
| R-SEL-04 | "between two candidates with the same URL, they rank by provider in the order `nimble`, `tavily`, `kernel`, `browserbase`." | Rule 3 | REV + offline | one candidate per page, so two providers for one URL cannot arise from a build: `test_rank_unit::test_url_by_code_point_then_provider_then_value` pins the oracle; `rank_key_problems` checks any response (RUL-S2-05) | open (stage 3: passing) |
| R-SEL-05 | "**Value**: between two candidates with the same URL and provider, the one whose value is smaller ranks higher: integers compare as numbers, strings by Unicode code point after removing surrounding whitespace." | Rule 4 | AT | `test_R_SEL_04_same_page_two_values_ranked_by_value` (`1001-5000` < `51-200`), `test_R_SEL_04_integers_compare_as_numbers` (9000000 before 12000000) | open (stage 3: passing) |
| R-SEL-06 | "A candidate of lower authority is selected only when no candidate of higher authority exists for that field. The rule runs over all of a field's candidates." | Rule | AT | harlow ceo (Dana Ruiz selected, Sam Ortiz/Pat Quill below), `candidate_problems` | open (stage 3: passing) |
| R-SEL-07 | "The field's `value` is the selected candidate's value, and its `citations` are the `url`, `excerpt` and `provider` of every candidate with that value, in rank order." | Rule | AT | `candidate_structure_problems` (value, citations == candidates with that value), `test_R_SEL_01_*` | open (stage 3: passing) |

## S2-E Status

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-STS-01 | "`known` — The field has candidates, and they all have the same value" | Status | AT | `test_R_STS_01_to_03_*` (hq_city: two pages, one value, two citations) | open (stage 3: passing) |
| R-STS-02 | "`contested` — The field's candidates carry two or more different values". "A `contested` field still has a selected `value` and its citations." | Status | AT | harlow (all six fields contested), tarn-biotech legal_name/funding | open (stage 3: passing) |
| R-STS-03 | "`unknown` — The field has no candidate; `value` is null" | Status | AT | `test_R_STS_03_no_evidence_*`, tarn-biotech ceo/founded_year | open (stage 3: passing) |
| R-STS-04 | "`status` is now one of three values" (supersedes stage-1 R-FLD-02: a non-null value is `known` **or** `contested`) | Status | AT | `assert_dossier_shape` | open (stage 3: passing) |
| R-STS-05 | "`GET /dossiers` (§8) is unchanged. The `legal_name` it lists is the selected value." | Status | AT | `test_R_LST_05_legal_name_listed_is_the_selected_value` (also `q` matches the selected value only) | open (stage 3: passing) |

## S2-F Screens (browser)

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-SCR-01 | "The following screens must be reachable by URL": `/`, `/dossiers/{domain}`, `/dossiers/{domain}/evidence`, `/contested`, `/signup`, `/login` | Screens | UI | `test_R_SCR_01_routes_are_reachable_by_url[6]` | open (stage 3: passing) |
| R-SCR-02 | "Other screens must be reachable through the UI." (contested, evidence, dossier, list reached by clicking) | Screens | UI | `test_R_SCR_02_*` | open (stage 3: passing) |
| R-SCR-03 | "Return the UI for `Accept: text/html`; API requests without that header receive JSON." | Screens | AT | `test_R_UI_01_*` (JSON for none / `application/json` / `*/*`; HTML with and without bearer) | open (stage 3: passing) |
| R-SCR-04 | "`/`, `/dossiers/{domain}/evidence` and `/contested` are browser routes; they read the API's dossier data." | Screens | AT + UI | `test_R_UI_02_*` (HTML for all six routes; unknown dossier still a screen), screens show API data (`test_R_DOS_*`, `test_R_EVI_*`, `test_R_CON_*`) | open (stage 3: passing) |
| R-SCR-05 | "The domain in a browser route is normalised as in §4." | Screens | UI | `test_R_DOS_02_*` (`/dossiers/WWW.X.TEST` and trailing dot, evidence route) | open (stage 3: passing) |
| R-SCR-06 | Runtime assets in the image (stage 1 §2): nothing loaded from another origin | stage 1 §2 | AT + UI | `test_R_UI_03_*` (document), `test_R_VIS_08_*` (every request of every route) | open (stage 3: passing) |
| R-AUTH-14 | Signup: `signup-email`, `signup-password`, `signup-display-name`, `signup-submit`; `current-user` "Visible on every screen when signed in. Text contains the display name"; `logout-button` | Signup and login | UI | `test_R_AUTH_14_*` (signed in on 4 routes, survives reload, logout) | open (stage 3: passing) |
| R-AUTH-15 | Login: `login-email`, `login-password`, `login-submit`; "`auth-error` — Error message. Present only when there is one" | Signup and login | UI | `test_R_AUTH_15_*` | open (stage 3: passing) |
| R-AUTH-16 | Signup refusals (short password, taken email, empty name, bad email) show `auth-error`, which disappears on success | Signup and login | UI | `test_R_AUTH_16_*[4]` | open (stage 3: passing) |
| R-LST-05 | The list: `dossier-list` container "Children ordered by domain ascending"; `dossier-item-{domain}` "Carries `data-state`. Text contains the domain, and the legal name when known. Links to `/dossiers/{domain}`" | Dossier list | UI | `test_R_LST_06_list_order_items_and_search`, `test_R_LST_07_*` (ready/failed) | open (stage 3: passing) |
| R-LST-06 | "`dossier-search` — Filters the list as `q` does on `GET /dossiers`"; "`empty-dossiers` — Shown instead of the list when no dossier matches" | Dossier list | UI | `test_R_LST_06_*` (8 queries incl. empty, case, legal name, no match; initially empty) | open (stage 3: passing) |
| R-RES-01 | "`research-domain` … `research-submit` … Sends `POST /dossiers`"; "`research-error` — Error message, when the request is refused — including an invalid domain" | Dossier list | UI | `test_R_RES_01_*` (4 invalid inputs, nothing created, no provider call) | open (stage 3: passing) |
| R-RES-02 | "A research request that succeeds, with 202 or 200, opens `/dossiers/{domain}` for the normalised domain." | Dossier list | UI | `test_R_RES_02_*` (`  WWW.X.TEST. `) | open (stage 3: passing) |
| R-RES-03 | "A domain that already has a dossier, including one created by another client after this browser read the list, opens that dossier and starts no build." | Dossier list | UI | `test_R_RES_03_*` (mock log unchanged) | open (stage 3: passing) |
| R-DOS-01 | Dossier screen: `dossier-domain` "exactly the normalised domain"; `dossier-state` exactly `building`/`ready`/`failed`; `dossier-spent` formatted with `data-units`; `dossier-researched-at` "Absent when it is null"; six `field-{field}` in §4 order with `data-status` | Dossier | UI | `test_R_DOS_01_*[talloway, harlow, tarn, nowhere]` (`check_dossier_screen`) | open (stage 3: passing) |
| R-DOS-02 | `field-value-{field}` "Present only when the value is not null", `data-value` "the API value as text"; `field-contested-{field}` "Present only when the field is `contested`" | Dossier | UI | `test_R_DOS_01_*` | open (stage 3: passing) |
| R-DOS-03 | `field-citations-{field}` container, `citation-{field}-{n}` in API order: text contains the excerpt, contains a link whose `href` is the citation's `url`, `data-provider` | Dossier | UI | `test_R_DOS_01_*` | open (stage 3: passing) |
| R-DOS-04 | "`dossier-evidence-link` — Link to `/dossiers/{domain}/evidence`" | Dossier | UI | `test_R_DOS_01_*`, `test_R_SCR_02_*` | open (stage 3: passing) |
| R-DOS-05 | "`dossier-not-found` — Shown instead of the fields when no dossier exists for the domain" | Dossier | UI | `test_R_DOS_02_*` | open (stage 3: passing) |
| R-DOS-06 | "`dossier-reload` — Reads the dossier again without starting a build" | Dossier | UI | `test_R_DOS_03_*` (another client's refresh appears; no new domain search) | open (stage 3: passing) |
| R-BLD-07 | "While the dossier's state is `building`, the screen reads the dossier again at least every 2 seconds until the state is `ready` or `failed`, and then shows the new fields without a manual reload." | Dossier | UI | `test_R_BLD_07_*` (≥ 2 reads, max gap ≤ 2.6 s, fields appear unaided) | open (stage 3: passing) |
| R-BLD-08 | A `failed` build is shown as `failed` with every field `unknown`; refresh remains offered | Dossier | UI | `test_R_BLD_08_*` | open (stage 3: passing) |
| R-REF-05 | "`dossier-refresh` — Button. Sends `POST /dossiers/{domain}/refresh`"; "After any successful action, the data on the same page must show the new state without a manual reload." | Dossier / Refresh | UI | `test_R_REF_05_*` (Idempotency-Key present, building then new value, spent matches API) | open (stage 3: passing) |
| R-REF-06 | "A refresh from this browser while that build runs is answered 202 like any other and the screen follows the running build to its end." | Competing clients | UI | `test_R_REF_06_*` (no error, no second build) | open (stage 3: passing) |
| R-REF-07 | "`refresh-error` — Error message, when a refresh is refused" (and then not `refresh-uncertain`) | Dossier | UI | `test_R_REF_07_*` (404 after the dossier is removed by an import) | open (stage 3: passing) |
| R-EVI-01 | Evidence: six `evidence-{field}` "Children in API `candidates` order"; `candidate-{field}-{n}` text contains the formatted value and the excerpt; `data-value`, `data-provider`, `data-kind`, `data-url`, `data-published-at` ("empty when null"), `data-selected` | Evidence | UI | `test_R_EVI_01_*`, `test_R_EVI_02_*` | open (stage 3: passing) |
| R-EVI-02 | "`evidence-empty-{field}` — Shown instead of candidates when the field has none" | Evidence | UI | `test_R_EVI_02_*`, `test_R_EVI_03_*` | open (stage 3: passing) |
| R-CON-04 | Contested: `contested-list` "ordered by domain ascending, then by field in the order of the table"; `contested-item-{domain}-{field}` "Carries `data-value` for the selected value. Text contains the domain, the field and every distinct candidate value. Links to `/dossiers/{domain}/evidence`" (RUL-S2-08: field = API name or its label) | Contested | UI | `test_R_CON_04_*` (4 dossiers, 3 with contested fields) | open (stage 3: passing) |
| R-CON-05 | "`empty-contested` — Shown instead of the list when no field is contested" | Contested | UI | `test_R_CON_04_*`, `test_R_CON_05_*` | open (stage 3: passing) |

## S2-G Refresh and competing clients

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-RD-01 | "**Latest read wins:** a delayed earlier read must not overwrite a later one, including when responses arrive out of order." | Refresh and competing clients | UI | `test_R_RD_01_*` (held read #1 delivered after read #2; skipped when the reload is disabled in flight or reads are page navigations) | open (stage 3: passing) |
| R-RD-02 | "This applies to the reads while a dossier is `building` as well." | same | UI | `test_R_RD_02_*` (skipped when the screen makes no script reads) | open (stage 3: passing) |
| R-UNC-01 | "If a research or refresh response is lost, including after the request commits, show `research-uncertain` … (nonempty text), not `research-error`. Keep the request retryable with the **same key and body**. A successful retry removes both the error and the uncertainty elements, shows the dossier, and starts at most one build." | same | UI | `test_R_UNC_01_*[lost-after-commit, lost-before-send]` (same Idempotency-Key and body; retry 200 replay / 202; one build) | open (stage 3: passing) |
| R-UNC-02 | same for refresh (`refresh-uncertain`, not `refresh-error`) | same | UI | `test_R_UNC_02_*` (2 domain searches in all) | open (stage 3: passing) |
| R-UNC-03 | "A research or refresh request whose response was lost before export remains retryable after import with the same body and key; the UI must recover the original response and show the imported dossier." | Existing clients | UI | `test_R_UNC_03_*` (research), `test_R_UNC_04_*` (refresh) | open (stage 3: passing) |
| R-UNC-04 | "Unknown outcomes are not confirmed refusals." (no `research-error`/`refresh-error` while uncertain) | same | UI | `test_R_UNC_01..04` | open (stage 3: passing) |

## S2-H Existing clients after an upgrade

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-UPG-01 | "A stage-2 service must accept an export produced by the same team's stage-1 service." Imported dossiers keep id, state, researched_at, spent_units, values; "Imported dossiers appear in the list and on their screens." | Existing clients | AT | `test_R_UPG_01_*`, `test_R_UPG_02_*` (list identical), `test_R_UPG_07_*` (UI), needs OLD_BASE_URL | open (stage 3: passing) |
| R-UPG-02 | "Each imported field gains one candidate for every value that text the providers served to the dossier's last stage-1 build … supports …; `provider` is the provider that served that text, `kind`/`published_at` as the exported state records them or else null, `retrieved_at` is the dossier's `researched_at`. Each imported field's `value`, `status` and `citations` then follow from its candidates by the selection rule and Status" | Existing clients | AT | `test_R_UPG_01_*`: lower bound = one candidate per citation, upper bound = what the old build's served text supports (mock log), provider = server of the text, kind/published null, retrieved_at = researched_at, structure checks (RUL-S2-12: the stage-1 export holds no page text) | open (stage 3: passing) |
| R-UPG-03 | "A browser signed in before that export/import upgrade must remain signed in afterwards." | Existing clients | UI | `test_R_UPG_06_*` (UI token survives reset + import); `test_R_UPG_02_*` (stage-1 token, password login, new token) (RUL-S2-13) | open (stage 3: passing) |
| R-UPG-04 | "A research or refresh request whose response was lost before export remains retryable after import with the same body and key" (API level) | Existing clients | AT | `test_R_UPG_03_*` (replay 200 identical, different body 409, no provider call) | open (stage 3: passing) |
| R-UPG-05 | "The candidates of an imported dossier are replaced by those of its next completed build." | Existing clients | AT | `test_R_UPG_04_*` | open (stage 3: passing) |
| R-UPG-06 | "These requirements apply when import completes between browser requests; migration during an in-flight request is not required. No page reload or new screen is required." | Existing clients | — | scope statement; tests import between requests | ruled (carried from stage 3) |
| R-UPG-07 | The service's own export (stage-2 state) is accepted unchanged by import and preserves candidates (carries R-EXP-02/03/06/12) | Existing clients + stage 1 §10 | AT | `test_R_UPG_05_*`, carried export tests | open (stage 3: passing) |

## S2-I Product and visual direction

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-VIS-01 | "The required flows must remain clear and usable at a 375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling." | Product | UI | `test_R_VIS_01_*` (9 routes at 375×800 and 1280×900, signed in and out) | open (stage 3: passing) |
| R-VIS-02 | "usable" at both widths: controls visible, inside the viewport, reachable | Product | UI | `test_R_VIS_02_*` | open (stage 3: passing) |
| R-VIS-03 | "Inputs need visible labels" | Product | UI | `test_R_VIS_03_*` (label element with visible text on login, signup, research, search) | open (stage 3: passing) |
| R-VIS-04 | "keyboard focus must be apparent" | Product | UI | `test_R_VIS_04_*` (Tab reaches each control; computed outline/shadow/border/colour changes) | open (stage 3: passing) |
| R-VIS-05 | "text and controls need sufficient contrast" | Product | UI | `test_R_VIS_05_*` (WCAG AA 4.5:1 / 3:1 large, key elements, both widths) | open (stage 3: passing) |
| R-VIS-06 | "Known, unknown, contested, building, failed … states must be visually distinct as well as satisfying the behavioural requirements" | Product | UI + UXR | `test_R_VIS_06_*` (field statuses), `test_R_VIS_07_*` (dossier states); loading/successful/refused/uncertain by UXR | open (stage 3: passing) |
| R-VIS-07 | "Format names, years, headcount ranges, money and timestamps for people first" | Product | UI + UXR | `test_R_VIS_11_*` (money not a bare integer; research time not raw ISO) — a floor | open (stage 3: passing) |
| R-VIS-08 | "Runtime assets … included in the image" (fonts, scripts, stylesheets) | stage 1 §2 | UI | `test_R_VIS_08_*` | open (stage 3: passing) |
| R-VIS-09 | "keep navigation consistent across the required routes"; `current-user` on every screen | Product | UI | `test_R_VIS_09_*` | open (stage 3: passing) |
| R-VIS-10 | "Provide considered empty, loading and error states" | Product | UI + UXR | `test_R_VIS_10_*` (empty list, empty contested, not found have text and fit 375 px); loading/error by UXR | open (stage 3: passing) |
| R-UX-01 | "calm, legible, evidence-first character: a reader … should see at a glance which fields are known, which are unknown and which are contested, and where each value came from" | Product | UXR | UX Reviewer, browser, 375 px and desktop | open (stage 3: passing) |
| R-UX-02 | "A field's value and its status must be the clearest information on the dossier screen, with its citations directly beside it." | Product | UXR | UX Reviewer | open (stage 3: passing) |
| R-UX-03 | "Fields, citations, candidates and contested fields should be easy to scan, and status, provider, page kind and publication time should be understandable without interpreting raw API data." | Product | UXR | UX Reviewer | open (stage 3: passing) |
| R-UX-04 | "Use a consistent visual system for typography, spacing, colour, controls and feedback. Primary actions — research, refresh — must be easy to identify." | Product | UXR | UX Reviewer | open (stage 3: passing) |
| R-UX-05 | "Each citation shows its excerpt as quoted text and links to its URL." (link: AT R-DOS-03; quoted-text presentation: UXR) | Product | AT + UXR | `check_dossier_screen` + UX Reviewer | open (stage 3: passing) |
| R-UX-06 | "loading, successful, refused and uncertain states must be visually distinct" | Product | UXR | UX Reviewer (research/refresh feedback, uncertain notice) | open (stage 3: passing) |

## Changes to carried-forward rows

| Row | Change at stage 2 |
|---|---|
| R-FLD-02 / R-FLD-03 | `status` is `known` / `contested` / `unknown`; `provider` may be any of the four providers. Tests check the stage-2 shape (`assert_dossier_shape`). |
| R-COST-04 | Superseded by R-WEB-01/04: an extract through `nimble` may set `render` (3 per URL). `check_log_rules` accepts 1 or 3 per URL. |
| R-EVD-03 / R-EVD-09 | Text is the browser text (R-TXT-01); the evidence also holds research-cited pages (R-CAN-02). |
| R-EVD-07 | "holds one of them" is now the selection rule (R-SEL-*); `contested` status. |
| R-EVD-08 | open (stage 3: passing) |
| R-EXP-03 / R-EXP-11 | Candidates travel with the state; a stage-1 export is accepted (R-UPG-*). |
| R-DEL-06 | open (stage 3: passing) |
| R-BLD-04 | The 10 s bound excludes time waiting after a 429 (R-RL-04). |


## Changes to carried-forward rows at stage 3

| Row | Change at stage 3 |
|---|---|
| R-GEN-03 | The dossier has seven fields (R3-GEN-01); research still asks for six. |
| R-DEL-13 | Disk row replaced: state survives a container restart (R3-RST-*). |
| R-EXP-* | State must also survive abrupt restart; export carries builds, history and feed (R3-UPG-03). |
| R-FLD-*, R-CAN-*, R-STS-* | Fields and candidates carry `true_from`/`learned_at`; `executives` is a seventh field with its own candidate shape (R3-EXE-*). |
| R-CON-04/05, R-DOS-*, R-EVI-* (screens) | Screens still show six fields; `executives` takes none of their `data-testid`s (R3-EXE-11). |

## Stage 3 rows (new)


## S3-A Two times per value, candidates and fields

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R3-TT-01 | "`true_from`: the date from which the evidence says the value holds. A page states it in the header line `Effective: <YYYY-MM-DD>`." | Two times | AT | `test_R3_TT_01/02` (every build vs oracle; by hand) | open (stage 3: passing) |
| R3-TT-02 | "A page with no valid `Effective` line takes the date part, in UTC, of its `published_at`; with neither, `true_from` is null." | Two times | AT | `test_R3_TT_02` (invalid Effective + Published -05:00 gives the next UTC day; neither gives null); `test_timeline_unit` | open (stage 3: passing) |
| R3-TT-03 | "`learned_at`: … For a candidate, it is the time of the first build that gathered a candidate with the same field, value, URL and provider." | Two times | AT | `test_R3_TT_01/03/04` (`s3lib.first_learned`) | open (stage 3: passing) |
| R3-TT-04 | "`retrieved_at` (stage 2) stays the time of the build that gathered the candidate in the current candidate set." | Two times | AT | `test_R3_TT_03/04` | open (stage 3: passing) |
| R3-TT-05 | "Candidates gain `true_from` and `learned_at`." / "A selected value's `true_from` is that of its selected candidate." | Two times | AT | `assert_dossier_shape`; `snapshot_problems` | open (stage 3: passing) |
| R3-TT-06 | "For a selected value, [`learned_at`] is the time of the build that made it the selected value." / "Each field of `GET /dossiers/{domain}` also carries the selected value's `true_from` and `learned_at`. Both are null when the field is `unknown`." | Two times | AT | `test_R3_TT_01/03/04/05`, `test_R3_ASO_03` | open (stage 3: passing) |
| R3-TT-07 | "In an `as_of` response these describe the selected value at that snapshot, using no later history." | Two times | AT | `test_R3_ASO_01/03` | open (stage 3: passing) |
| R3-TT-08 | "The selection rule in `stage-2.md` is unchanged." | Two times | AT | carried R-SEL-*, R-CAN-*; `snapshot_problems` candidate order | open (stage 3: passing) |

## S3-B Executives

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R3-EXE-01 | "A dossier has a seventh field, `executives`. The `fields` of every response that lists a dossier's fields hold it, after the six fields of §4." | Executives | AT | `test_R3_EXE_01` (GET, as_of, history, values), `assert_dossier_shape` | open (stage 3: passing) |
| R3-EXE-02 | "A research run (§4) still asks for the six fields of §4 only." / "A research claim is never a candidate of `executives`." | Executives | AT | `test_R3_EXE_08` (mock log `fields` equals the six) | open (stage 3: passing) |
| R3-EXE-03 | "Its value is an array with one object `{ "title": T, "name": N }` for each title below that has a selected person, in the order `cfo`, `coo`, `cto`. … When no title has a selected person, the value is null and the field is `unknown`." | Executives | AT | `test_R3_EXE_02/04/09` | open (stage 3: passing) |
| R3-EXE-04 | "each title is a field with these statement phrases [`chief financial officer`, `CFO`; `chief operating officer`, `COO`; `chief technology officer`, `CTO`] and with the format and normalisation of `ceo` (A.4, A.5)" | Executives | AT | `oracle.supported_title_value`; cobalt/harrow pages (long and acronym phrases; a two-name sentence, a negated and a hedged sentence make no candidate): `test_R3_EXE_03/05` | open (stage 3: passing) |
| R3-EXE-05 | "A candidate of `executives` is a candidate of one title: it carries `title` beside `value`"; "`selected` is true on the highest-ranked candidate of each title…"; "`candidates` lists every candidate by title, in the order above, then in rank order." | Executives | AT | `test_R3_EXE_02/03` | open (stage 3: passing) |
| R3-EXE-06 | "`citations` are, for each member in order, the `url`, `excerpt` and `provider` of every candidate with the member's title and name, in rank order." | Executives | AT | `test_R3_EXE_02/03` | open (stage 3: passing) |
| R3-EXE-07 | "`status` is `unknown` when the value is null, `contested` when the candidates of some title carry two or more different names, and `known` otherwise." | Executives | AT | `test_R3_EXE_04` (contested, known per epoch), `_09` (unknown) | open (stage 3: passing) |
| R3-EXE-08 | "A candidate's `learned_at` is the time of the first build that gathered a candidate with the same title, name, URL and provider." / "A member's `true_from` is that of its title's selected candidate. The field's `true_from` is the latest of its members' `true_from`, or null when any member's is null." | Executives | AT | `test_R3_EXE_03/04` | open (stage 3: passing) |
| R3-EXE-09 | "`GET /dossiers/{domain}/values` chooses each title's person from the candidates at `true_at` and gives the value, `true_from` and `citations` from them by these rules." | Executives | AT | `test_R3_EXE_11/12` | open (stage 3: passing) |
| R3-EXE-10 | "A title **differs** … when exactly one of them has a member with that title, or both have one and their names differ. A differing title counts as a correction when … both members' `true_from` are not null, and the new member's is on or before the earlier member's. The entry is `correction` when every differing title counts as a correction, and `change` otherwise." | Executives | AT | `test_R3_EXE_06/07` (change, change, correction, change, change) | open (stage 3: passing) |
| R3-EXE-11 | "The `data-testid` attributes of the screens in `stage-2.md` name only the six fields of §4: `executives` takes none of them … On `/contested`, 'no field is contested' means none of those six fields is." | Executives | UI | `test_R3_UI_01/02` | open (stage 3: passing) |

## S3-C Changes, history and the feed

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R3-HIS-01 | "Every change to a selected value appears exactly once in the change feed, at the time this stage assigns to it." | Operations 4 | AT | `test_R3_CHG_01`, `test_R3_CON_01/02` | open (stage 3: passing) |
| R3-HIS-02 | "each field whose selected value differs from its selected value before the build gets one history entry, and one feed entry, of one of two types: `correction` (both … not null, and the new value's `true_from` is on or before the earlier value's `true_from`); `change` (every other difference, including a value appearing where there was none, a value disappearing, and either `true_from` being null)" | Changes | AT | `test_R3_HIS_02/03`, `test_R3_CHG_02` | open (stage 3: passing) |
| R3-HIS-03 | "A field's first selected value, set by the dossier's first build that completes `ready`, gets a history entry of type `initial` and no feed entry. A field that is `unknown` after that build gets its first entry when it first gets a value, and that entry is a `change`." | Changes | AT | `test_R3_HIS_02` (headcount_range), `test_R3_HIS_06`, `test_R3_CHG_01` | open (stage 3: passing) |
| R3-HIS-04 | "A build that completes with the same selected value for a field adds nothing for it, even when its candidates, citations or `true_from` differ. A `failed` build adds nothing." | Changes | AT | `test_R3_HIS_04`, `test_R3_TT_04/06` (founded_year, funding_total, a repeated and a failed build) | open (stage 3: passing) |
| R3-HIS-05 | "Concurrent refreshes of one dossier run one build (§8) and so add each entry once." | Changes | AT | `test_R3_CON_01` | open (stage 3: passing) |
| R3-HIS-06 | `GET /dossiers/{domain}/history`: "`fields` holds all seven fields. Each list is in the order the entries were added, oldest first." / "An entry's `value`, `true_from`, `learned_at` and `citations` are those of the selected value it records. An entry whose value is null has `"true_from": null` and `"citations": []`." / "No dossier for the domain is 404 `not_found`." | History | AT | `test_R3_HIS_01/02/05/06`, `history_problems` | open (stage 3: passing) |
| R3-CHG-01 | `GET /changes`: "The feed holds every `change` and `correction` entry of every dossier." entry shape `{seq, domain, field, type, from, to, true_from, learned_at}`; "`from` and `to` are the earlier and the new selected value, either of which may be null. `true_from` is the new value's. `learned_at` is the time of the build that added the entry." | Feed | AT | `test_R3_CHG_01/02/08`, `feed_problems` | open (stage 3: passing) |
| R3-CHG-02 | "`seq` is a positive integer, unique across the feed, and larger for every later entry. Entries added by one build are numbered in the order of the fields in `stage-1.md` §4, then `executives`." | Feed | AT | `test_R3_CHG_03/08`, `test_R3_RST_02` | open (stage 3: passing) |
| R3-CHG-03 | "`since` defaults to 0 and lists only entries whose `seq` is greater than it. It is an integer, 0 or more. Entries are ordered by `seq` ascending. `limit` defaults to 50, range 1 to 200. `has_more` is true when entries exist beyond the last one returned." | Feed | AT | `test_R3_CHG_04/06/07` | open (stage 3: passing) |
| R3-CHG-04 | New endpoints need a bearer token (stage-1 §6); integer query parameters are plain decimal digits (stage-1 §5). | Feed | AT | `test_R3_ASO_09` (401), `test_R3_CHG_06/07` (422) | open (stage 3: passing) |

## S3-D `GET /dossiers/{domain}?as_of=`

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R3-ASO-01 | "Returns the dossier as this service had it at `as_of`: the fields, candidates and `researched_at` of the latest build that completed `ready` and whose time is at or before `as_of`, decided by `learned_at`, never by `true_from`. `state` is `ready`." | as_of | AT | `test_R3_ASO_01/02` (equality with the snapshot taken after each build) | open (stage 3: passing) |
| R3-ASO-02 | "`spent_units` is the total of the builds whose time is at or before `as_of`." | as_of | AT | `test_R3_ASO_04/10` | open (stage 3: passing) |
| R3-ASO-03 | "When several ready builds have the same time, return the last of them in build order. This also applies when equivalent RFC 3339 timestamps use different offsets. The clock need not advance between builds." | as_of | AT | `test_R3_ASO_10` | open (stage 3: passing) |
| R3-ASO-04 | "`as_of` is not an RFC 3339 timestamp with an explicit offset → 422 `validation_failed`" | as_of | AT | `test_R3_ASO_07` (10 forms), `test_R3_ASO_05` (offsets, Z accepted) | open (stage 3: passing) |
| R3-ASO-05 | "No build of the dossier completed `ready` with a time at or before `as_of` → 404 `not_found`"; "No dossier for the domain → 404 `not_found`" | as_of | AT | `test_R3_ASO_06`, `test_R3_HIS_06`, `test_R3_UPG_02` | open (stage 3: passing) |
| R3-ASO-06 | "Without `as_of`, `GET /dossiers/{domain}` is unchanged." | as_of | AT | `test_R3_ASO_08`; carried suite | open (stage 3: passing) |

## S3-E `GET /dossiers/{domain}/values?true_at=`

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R3-VAL-01 | "Returns, for each field, the value that the evidence this service had at `as_of` says held on the date `true_at`. `as_of` defaults to the current time (§8)." response `{domain, true_at, as_of, fields:{f:{value,true_from,citations}}}` | values | AT | `test_R3_VAL_01/03/05` | open (stage 3: passing) |
| R3-VAL-02 | "A **page version** is what one ready build gathered from one URL … The versions of a URL known at `as_of` are those gathered by ready builds whose time is at or before `as_of`, taken in build order. Each version holds from its `true_from`. When a later version of the same URL is gathered, it replaces every earlier version of that URL whose `true_from` is on or after its own. The latest earlier version that it does not replace stops holding on the later version's `true_from`." | values | AT | `test_R3_VAL_01/02/06`; oracle `timeline.page_versions` (self-checked offline) | open (stage 3: passing) |
| R3-VAL-03 | "A version whose `true_from` is null holds from no date, and a later version with a null `true_from` replaces every earlier version of its URL." | values | AT | `test_R3_VAL_02` (build 6 of northgate), `test_R3_UPG_03` | open (stage 3: passing) |
| R3-VAL-04 | "A gathered version with no candidates still replaces or ends earlier versions by this rule." | values | AT | `test_R3_VAL_02` (hq_city, `/team`), `test_R3_VAL_06` (founded_year) | open (stage 3: passing) |
| R3-VAL-05 | "The candidates **at `true_at`** are those of every version that holds on that date. Each field's value is chosen from them by the selection rule in `stage-2.md`, and its `true_from` is that of the chosen candidate." / "A field with no candidate at `true_at` has `"value": null`, `"true_from": null`, `"citations": []`. Citations are those of the candidates at `true_at` with the chosen value." | values | AT | `test_R3_VAL_01/02/03`, `check_values` | open (stage 3: passing) |
| R3-VAL-06 | "`true_at` missing or not a `YYYY-MM-DD` date, or `as_of` not an RFC 3339 timestamp with an explicit offset → 422"; "No dossier for the domain, or no build of it completed `ready` with a time at or before `as_of` → 404" | values | AT | `test_R3_VAL_04` | open (stage 3: passing) |

## S3-F Upgrades

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R3-UPG-01 | "A stage-3 service must accept an export produced by the same team's stage-1 or stage-2 service. Every imported field that has a value gets one history entry of type `initial`, with `learned_at` the dossier's `researched_at` and `true_from` null unless the exported state records the dates that give it. The feed starts empty; the first build after import compares its selected values with the imported ones." | Upgrades | AT | `test_R3_UPG_01/04` (stage 1), `_06/07/09` (stage 2) | open (stage 3: passing) |
| R3-UPG-02 | "Existing tokens, dossiers and completed idempotent responses survive the import as in `stage-1.md` §10" | Upgrades | AT | `test_R3_UPG_05/10`; carried `test_upgrade.py` | open (stage 3: passing) |
| R3-UPG-03 | "the history and feed of a stage-3 export survive a stage-3 import unchanged. So do its builds: after a stage-3 import, `?as_of=` and `/values` answer as they did in the exporting service." | Upgrades | AT | `test_R3_UPG_11` | open (stage 3: passing) |
| R3-UPG-04 | "State imported from a stage-1 export counts as one build that completed `ready` at the dossier's `researched_at`, and each imported candidate's URL as one version gathered by it; imported candidates have `learned_at` equal to their `retrieved_at`. An `as_of` at or after that time and before the next build returns the imported fields, and an earlier `as_of` is 404. An imported dossier whose `researched_at` is null answers every `as_of` with 404 until a build completes." | Upgrades | AT | `test_R3_UPG_01/02/03` | open (stage 3: passing) |
| R3-UPG-05 | "State imported from a stage-2 export keeps the builds that the stage-2 service made … one page version whose `true_from` follows from that page's `Effective` and `Published` lines … State that the stage-2 service had itself imported counts as one build that completed `ready` at the dossier's `researched_at`. … History is still one `initial` entry per field that has a value, as above, and an `as_of` response takes each field's `learned_at` and `true_from` from that history." | Upgrades | AT | `test_R3_UPG_06..09` under RUL-S3-15 (the final stage-2 export holds no build list and no Effective lines) | open (stage 3: passing) |
| R3-UPG-06 | "An export of a stage-1 or stage-2 service has no `executives` candidates. After its import, `executives` is `unknown`, in the imported state and in every build kept from the export, and has no history entry; the first build that completes `ready` with a value for it adds a `change`, or an `initial` entry when it is the dossier's first build that completes `ready`." | Upgrades | AT | `test_R3_UPG_01/04/06/07` | open (stage 3: passing) |

## S3-G Concurrency, restarts, non-functional

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R3-CON-01 | "Concurrent refreshes and reads must produce the same results as executing them one at a time in some order. No change appears twice in the feed, and none is missing from it." | Concurrency | AT | `test_R3_CON_01/02/03` | open (stage 3: passing) |
| R3-CON-02 | Carried limits on the new endpoints: "Concurrent requests up to 50 in flight", "Per-request timeout 5 s". | §2 | AT | `test_R3_CON_04` | open (stage 3: passing) |
| R3-NFR-01 | 30 builds of one dossier: `history`, `changes`, `as_of`, `values` answer well inside the 5 s per-request limit (< 2 s asserted). | §2 | M | `test_R3_NFR_01` (slow) | open (stage 3: passing) |
| R3-RST-01 | "This row replaces the Disk row of the resource limits in `stage-1.md` §2: Disk — the container's filesystem; it survives a container restart." "The sentence 'State need not survive an abrupt container restart' in §10 no longer applies." | Restarts | AT | `test_R3_RST_01..07` (`docker kill -s KILL` then `docker start`) | open (stage 3: passing) |
| R3-RST-02 | "Every account signs in with its password, and every bearer token is valid." | Restarts | AT | `test_R3_RST_01/04` | open (stage 3: passing) |
| R3-RST-03 | "Every dossier answers `GET /dossiers/{domain}`, with and without `as_of`, `GET …/values` and `GET …/history` as before, and `GET /dossiers` lists the same dossiers." | Restarts | AT | `test_R3_RST_01/03/05` | open (stage 3: passing) |
| R3-RST-04 | "The change feed holds the same entries with the same `seq`. An entry added after the restart has a larger `seq` than every entry before it." | Restarts | AT | `test_R3_RST_01/02/03` | open (stage 3: passing) |
| R3-RST-05 | "A replay of a completed idempotent request answers as §7 requires." | Restarts | AT | `test_R3_RST_01` | open (stage 3: passing) |
| R3-RST-06 | "The clock reads the time it read before the stop until reset or `POST /_test/clock` moves it." | Restarts | AT | `test_R3_RST_01` (the next build's time is the clock before the stop) | open (stage 3: passing) |
| R3-RST-07 | "The container may be stopped abruptly at any time, with no warning and no time to finish what the service is doing": durability before responding (signup, build completion), import/reset durability; a stop during a build is unspecified (RUL-S3-18). | Restarts | AT | `test_R3_RST_04/05/06/07` | open (stage 3: passing) |
| R3-GEN-01 | Fields are seven (replaces R-GEN-03 "exactly six fields"); all carried suites pass with `executives` present. | Scope | AT | carried suites, `assert_dossier_shape` | open (stage 3: passing) |

## Changes to carried-forward rows at stage 4

| Row | Change at stage 4 |
|---|---|
| R-GEN-03, R3-GEN-01 | The dossier has eight fields (R4-GEN-02); research still asks for six. |
| R-CAN-*, R-SEL-*, R-WEB-* (kind of a page) | The `own` kind needs the registrant to be the company's domain; lookalikes are aggregators (R4-OWN-*). `rank.kind_of` implements it; no page of the stage-1..3 corpus changes kind. |
| R-IDEM-*, R-DOS-* | `POST /batches` is a third idempotent write path (R4-BAT-11..13) and a request that makes provider calls (R4-BAT-01). |
| R-FLD-*, R-CAN-*, R3-EXE-* | Every field gains `origins`, `corroborated`, `corroborated_since`; every candidate gains `origin` (R4-ORG-05, R4-COR-*); checked by `assert_dossier_shape` on every response. |
| R-CON-04/05, R-DOS-*, R-EVI-* (screens) | `investors` takes none of the screens' `data-testid`s (R4-INV-12). |
| R3-RST-* | Stage 4 adds the builds running at the stop (R4-RST-*). |
| R-EXP-*, R3-UPG-* | A stage-4 service also imports stage-3 exports and keeps batches in its own export (R4-UPG-*). |

## Stage 4 rows (new)

## S4-A Operations and model

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-GEN-01 | "Spending never exceeds a budget that this specification or the caller sets." (all operations, item 5) | Operations 5 | AT | `test_R4_BAT_08/09/10`, `test_R4_RST_02/03`; the 80-unit budget by carried `R-GEN-02`; every build test compares `spent_units` with the mock's billed cost | open (test committed; not yet run on a stage-4 build) |
| R4-GEN-02 | "A dossier has an eighth field, `investors`. The `fields` of every response that lists a dossier's fields hold it, after `executives`, and the feed entries one build adds are numbered with `investors` last." | Investors | AT | `test_R4_INV_01` (GET, as_of, values, history), `assert_dossier_shape`, `test_R4_INV_09` | open (test committed; not yet run on a stage-4 build) |
| R4-GEN-03 | Three idempotent write paths: "There are three idempotent write paths: stage 1's two and `POST /batches`." | Intro | AT | `test_R4_BAT_12..15` (the carried `R-IDEM-*` rows hold for the other two) | open (test committed; not yet run on a stage-4 build) |

## S4-B Lineage header lines and own pages

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-LIN-01 | "Domains in these lines, and the host of a `Canonical` URL, are normalised as in §4." (`Registrant`, `Canonical`, `First-Published-By` header lines) | Lineage header lines | AT | `linden-forge.test` `/press` (`Registrant: WWW.Linden-Forge.TEST.` is the company, kind `own`): `test_R4_OWN_02`; oracle `rank.registrant_of` (`test_s4_unit`) | open (test committed; not yet run on a stage-4 build) |
| R4-LIN-02 | "A page with no valid `Registrant` line has the host of its own URL, normalised, as its registrant." | Lineage header lines | AT | `linden-forge.test` `/careers` (`Registrant: not a domain!`): `test_R4_OWN_02`, `test_registrant_normalisation_and_fallback` | open (test committed; not yet run on a stage-4 build) |
| R4-OWN-01 | "A page counts as kind `own` for a company only when its registrant is the company's domain. Any other page that states `Kind: own` has kind `aggregator` for the selection rule in `stage-2.md`, and its candidates report `"kind": "aggregator"`." | Own pages | AT | `test_R4_OWN_01/02/04` (lookalike and blog pages; ranking effect), `test_R4_UI_03` (`data-kind`) | open (test committed; not yet run on a stage-4 build) |
| R4-OWN-02 | Reading of the same sentence for a page with no `Kind` line on the company's host but registered elsewhere (RUL-S4-02): not `own`, an aggregator. | Own pages | AT | `test_R4_OWN_03` (`linden-forge.test/legal`) | open (test committed; not yet run on a stage-4 build) |
| R4-OWN-03 | "A page that states `Kind: own` and whose registrant is not the host of its own URL, normalised, is a **lookalike**: a site presenting itself as a company it is not registered to." | Own pages | AT | origin rule 3 on `linden-forge-official.test`, `copycat.test` -> `fake-linden.test`: `test_R4_ORG_01`; unit `test_own_needs_the_registrant_and_lookalikes` | open (test committed; not yet run on a stage-4 build) |

## S4-C Origins and corroboration

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-ORG-01 | "Every page has one **origin**, a domain, taken from the first of these that applies: 1. Its `First-Published-By` domain. 2. When its `Canonical` URL is not the page's own URL, the origin of the page at that URL (its **original**), by these same rules. 3. The company's domain, when the page is a lookalike. 4. Its registrant." | Origins | AT | `test_R4_ORG_01/04/05/06`, `test_R4_OWN_01`; every oracle comparison (`snapshot_problems` checks `origin` on every candidate) | open (test committed; not yet run on a stage-4 build) |
| R4-ORG-02 | "A build obtains from a provider each original that rule 2 needs." | Origins | AT | `test_R4_ORG_03` (the mock log serves `wire-hub.test/linden-hq`, `fake-linden.test/hq`, `archive.test/rm`) | open (test committed; not yet run on a stage-4 build) |
| R4-ORG-03 | "From the page whose origin is sought, rule 2 follows at most three `Canonical` URLs in a row. Where it would follow a fourth, or where no provider serves a page at the URL, the host of that URL takes the place of the original's origin." | Origins | AT | `test_R4_ORG_04` (chain of four), `test_R4_ORG_05` (missing original, a cycle, a Canonical equal to the page's URL, First-Published-By before Canonical) | open (test committed; not yet run on a stage-4 build) |
| R4-ORG-04 | "Pages with the same origin are one source, however many URLs, providers or kinds they have." | Origins | AT | `test_R4_ORG_06` (four ceo candidates, three origins), `test_R4_INV_04` (a copy adds no origin) | open (test committed; not yet run on a stage-4 build) |
| R4-ORG-05 | "Candidates gain `origin`, the origin of their page." | Origins | AT | `test_R4_ORG_07`, `assert_dossier_shape`, `snapshot_problems` | open (test committed; not yet run on a stage-4 build) |
| R4-ORG-06 | Derived from §4 and stage 2 (RUL-S4-05): an original that only a `Canonical` URL points at, and that no search returns, is not evidence; none of its values is a candidate. | Origins / Evidence | AT | `test_R4_ORG_02`, `test_R4_ORG_04` (`founded_year` 2003, not the original's 1999), oracle equality of the candidate lists | open (test committed; not yet run on a stage-4 build) |
| R4-COR-01 | "`origins` lists the distinct origins of the candidates whose value is the selected value, sorted ascending. It is `[]` for an `unknown` field." / "`corroborated` is true when `origins` has two or more entries, otherwise false." | Origins | AT | `test_R4_COR_01/02/04`, `test_R4_ORG_01`, `origin_key_problems` on every dossier body | open (test committed; not yet run on a stage-4 build) |
| R4-COR-02 | "`corroborated_since` is the time (§8) of the earliest ready build after which the selected value has had two or more **standing origins**, or null while it has fewer. The standing origins of a selected value are the origins of every candidate with that value that any ready build has gathered since the value became the selected value (the `learned_at` of its latest history entry, stage 3), whether or not a later build gathered it again. A new selected value starts with none." | Origins | AT | `test_R4_COR_01/02/05` (corvane-systems, 7 builds incl. a failed one: stays, resets when the value changes and returns), oracle `SinceTracker` (unit `test_since_tracker_*`) | open (test committed; not yet run on a stage-4 build) |
| R4-COR-03 | "For `executives` and `investors`, these keys follow the field's members. A member's candidates are those with its title and name (`executives`) or with its name (`investors`). `origins` lists the distinct origins of the candidates of all members, sorted ascending. It is `[]` for an `unknown` field. `corroborated` is true when the candidates of every member have two or more distinct origins, and false otherwise, including for an `unknown` field." | Origins | AT | `test_R4_COR_03` (executives), `test_R4_INV_02/06`, `investors_problems`/`origin_key_problems` | open (test committed; not yet run on a stage-4 build) |
| R4-COR-04 | "`corroborated_since` [for members] is the time of the earliest ready build after which every member has had two or more standing origins, or null while some member has fewer or the field is `unknown`. A member's standing origins are the origins of every candidate of that member that the build after which it last became a member, or any later ready build, has gathered, whether or not a later build gathered it again." | Origins | AT | `test_R4_COR_03` (cfo from build 1, coo from build 5: the field from build 5), `test_R4_INV_06` | open (test committed; not yet run on a stage-4 build) |
| R4-COR-05 | "Imported candidates count as gathered at the imported `researched_at`. When a stage-3 export is imported, the candidates of each of its builds count as gathered at that build's time." / "Imported candidates whose export records no origin take the host of their URL, normalised, as their origin." | Origins | AT | `test_R4_UPG_01/04/06` | open (test committed; not yet run on a stage-4 build) |
| R4-COR-06 | Reading (RUL-S4-07): an `as_of` response carries the keys as that build left them (no later history). | Origins / stage 3 as_of | AT | `test_R4_COR_06`, `test_R4_INV_06`, `test_R4_UPG_06` | open (test committed; not yet run on a stage-4 build) |

## S4-D Investors

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-INV-01 | "For Appendix A, `investors` is a field with the statement phrases `investor`, `investors`, `led by`, `backed by` and `participated`."; rules 1 to 4 of A.2 apply (single sentence, names the company, a statement phrase, no negating phrase). | Investors | AT | `test_R4_INV_03` (hedged and unnamed sentences make no candidate), oracle `supported_investors` (unit `test_investor_rules_1_to_4_of_a2`) | open (test committed; not yet run on a stage-4 build) |
| R4-INV-02 | "Occurrences of the company's name and of these statement phrases are first taken out of the sentence and separate the words around them. Of the runs of capitalised words (A.4) joined by single spaces that remain, each not part of a longer such run, a run of two or more words whose last word is `Ventures`, `Capital`, `Partners`, `Fund`, `Investments`, `Holdings` or `Equity` is an **investor name**." | Investors | AT | `test_R4_INV_02/03`, unit `test_investor_runs_are_separated_by_the_company_name_and_phrases`; corpus quillon-bio / halden-labs | open (test committed; not yet run on a stage-4 build) |
| R4-INV-03 | "In an excerpt that contains an amount (A.4), the run that starts directly after `led by` or `backed by` and one space is an investor name too, whatever its length and last word: `Acme Robotics raised $40M in a round led by General Atlantic.` names `General Atlantic`, and `Acme Robotics is led by Dana Ruiz.` names no investor." | Investors | AT | `test_R4_INV_02/03` (General Atlantic named; `led by Dana Ruiz` and `backed by Maple Grove` without an amount name nobody); unit `test_investor_names_spec_examples` | open (test committed; not yet run on a stage-4 build) |
| R4-INV-04 | "An investor name normalises to the text as the excerpt writes it. Rules 1 to 4 of A.2 apply; in place of rule 5, an excerpt supports each investor name it contains." / "The `value` of a candidate of `investors` is one investor name. A research claim is never a candidate of `investors`." | Investors | AT | `test_R4_INV_06` (every excerpt supports its name), `test_R4_INV_11` (the research schema is the six fields) | open (test committed; not yet run on a stage-4 build) |
| R4-INV-05 | "An investor name is a **member** when, among the field's candidates, one with that name has `kind` `own` or `filing`, or those with that name have two or more distinct origins." | Investors | AT | `test_R4_INV_04` (a copy of a news page is one origin; an aggregator alone is no member; a filing makes one) | open (test committed; not yet run on a stage-4 build) |
| R4-INV-06 | "the value is the array of the members' names, sorted by Unicode code point, or null when there is no member. `investors` is `known` exactly when it has a member, and `unknown` otherwise" | Investors | AT | `test_R4_INV_02/05/07`, `investors_problems` (`Ärlig Capital` sorts after `Zenith Fund`) | open (test committed; not yet run on a stage-4 build) |
| R4-INV-07 | "`selected` is true on every candidate whose name is a member, and false on the others." / "`candidates` lists every candidate in the order the selection rule in `stage-2.md` ranks them." / "`citations` are, for each member in the order of the value, the `url`, `excerpt` and `provider` of every candidate with its name, in rank order." | Investors | AT | `test_R4_INV_02/06`, `investors_problems`, `snapshot_problems` | open (test committed; not yet run on a stage-4 build) |
| R4-INV-08 | "A member's `true_from` is the earliest `true_from` that is not null among the candidates with its name, or null when all of them are null. The field's `true_from` is the latest of its members' `true_from`, or null when the value is null or any member's is null." | Investors | AT | `test_R4_INV_02` (2026-01-20), `_05` (null: Kappa Holdings), `_07` | open (test committed; not yet run on a stage-4 build) |
| R4-INV-09 | "`GET /dossiers/{domain}/values` decides membership from the candidates at `true_at` and gives the value, `true_from` and `citations` from them by these rules." | Investors | AT | `test_R4_INV_10` (six true_at/as_of pairs against the oracle) | open (test committed; not yet run on a stage-4 build) |
| R4-INV-10 | "A history and feed entry for `investors` is typed by name … A name in the new value and not in the earlier one counts as a correction when its `true_from` and the earlier value's `true_from` are both not null and its `true_from` is on or before the earlier value's. The entry is `correction` when every name in exactly one of the two values counts as a correction, and `change` otherwise." | Investors | AT | `test_R4_INV_08/09/12`, unit `test_quillon_members_values_and_types` (initial, correction, correction, change, change, change) | open (test committed; not yet run on a stage-4 build) |
| R4-INV-11 | Stage-3 rules apply to the new field: the first entry of a field that is `unknown` after the first build is a `change`; entries only for ready builds; feed `from`/`to` are arrays or null. | Investors / stage 3 | AT | `test_R4_INV_12`, `test_R4_INV_08/09` | open (test committed; not yet run on a stage-4 build) |
| R4-INV-12 | "The screens treat `investors` as `stage-3.md` treats `executives`: it takes none of the `data-testid` attributes of `stage-2.md`, and \"no field is contested\" on `/contested` means none of the six fields of §4 is." | Investors | UI | `test_R4_UI_01/02/03` | open (test committed; not yet run on a stage-4 build) |

## S4-E Batches

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-BAT-01 | "`POST /batches` starts builds, and so joins `POST /dossiers` and `POST /dossiers/{domain}/refresh` as a request that makes provider calls (§8, Builds)." Reads, replays and validation failures make none. | Batches | AT | `test_R4_BAT_01` (log empty after every 422), `_11`, `_12` | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-02 | "`domains` missing, empty or longer than 50 entries -> 422 `validation_failed`"; "An entry of `domains` invalid after normalisation (§4) -> 422"; "Two entries of `domains` the same after normalisation -> 422" | POST /batches | AT | `test_R4_BAT_01` (9 bodies), `_03` (50 is valid), `_17` (50 domains; 51 is 422) | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-03 | "`budget_units` missing, not an integer, below 1 or above 100000 -> 422 `validation_failed`"; "A `budget_units` that is not an integer is 422 `validation_failed` whatever its JSON type: a string, `true` or `1.5` included. The row above takes precedence over the 400 `malformed_request` of §5 for a field of the wrong JSON type." | POST /batches | AT | `test_R4_BAT_01` (string, true, false, 1.5, null, list, object, 0, -1, 100001), `_03` (1 and 100000 valid) | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-04 | Other fields of the wrong JSON type and unparseable bodies follow §5 (RUL-S4-09): `domains` not an array is 400 `malformed_request`. | §5 | AT | `test_R4_BAT_02` | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-05 | 202 `{ "batch_id", "state": "running", "budget_units", "spent_units": 0, "dossiers": [ { "domain", "state" } ] }`; "`dossiers` lists the normalised domains in the order given, each with its dossier's state." | POST /batches | AT | `test_R4_BAT_05` (`building`, `ready`, `building`), `assert_batch_shape` | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-06 | "A domain with no dossier gets one, and the batch runs its first build. A domain that already has a dossier is not researched by the batch and costs it nothing." | POST /batches | AT | `test_R4_BAT_05/06/07` (no provider call names the existing domain; one that is already building is not built twice) | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-07 | "`spent_units` is the total cost (§9) of the provider calls the batch's builds made. It never exceeds `budget_units`. Each build in a batch still spends at most 80 units, and its cost also counts in its dossier's `spent_units`." | POST /batches | AT | `test_R4_BAT_05/08/10` (`spent_units` = the dossiers' = the mock's billed cost) | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-08 | "When the budget would be exceeded by a further call, the batch makes no more provider calls, and its remaining builds complete with the pages and research claims they have obtained: each of their fields is `known` exactly when those support a value for it." | POST /batches | AT | `test_R4_BAT_08` (budgets of the total+200, half, half the cheapest, 1: total billed <= budget, quiet after `done`, `partial_build_problems`), `_09` | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-09 | `GET /batches/{id}`: "Returns the batch in the shape above. `state` is `running` while any of its builds runs, then `done`. Unknown batch is 404 `not_found`." | GET /batches/{id} | AT | `test_R4_BAT_05/06/11` | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-10 | "A batch belongs to the user who created it; another user's batch is 404 `not_found`." Both endpoints need a bearer token (§6). | Batches | AT | `test_R4_BAT_11`, `_04` (401 before the key check) | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-11 | "**An idempotent write path.** `Idempotency-Key` is required; see §7." (absent/empty 400, 1..255 characters, scoped to the user, per path) | POST /batches | AT | `test_R4_BAT_04/14` | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-12 | §7: replay = 200 with the original response body, "even after the dossier has changed. It starts no build and makes no provider call."; same key + different body = 409; unknown fields ignored; a claimed key is resolved before field validation; a key reused after a 4xx is a first use. | §7 | AT | `test_R4_BAT_12/13/14` | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-13 | §7: "For concurrent identical requests with an unused key, exactly one returns the normal response. The others return 200 with the same body. The operation takes effect only once." / "Concurrent requests for the same domain create one dossier and start one build, whatever their keys." | §7, §8 | AT | `test_R4_BAT_15` (10 threads), `_16` (two batches with the same domains) | open (test committed; not yet run on a stage-4 build) |
| R4-BAT-14 | Carried limits on the new path: 5 s per request with 50 domains, up to 50 in flight. | §2 | AT | `test_R4_BAT_17` (slow) | open (test committed; not yet run on a stage-4 build) |

## S4-F Provider failure

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-FAIL-01 | "A provider may answer a call with an error (any 5xx status, or 429). The build continues: it may make the same request again, through that provider or another." | Provider failure | AT | `test_R4_FAIL_06` (a 429 on the first attempt of every call) | open (test committed; not yet run on a stage-4 build) |
| R4-FAIL-02 | "A build in which every call to one or more providers fails, while `nimble` answers, completes `ready`, with every field `known` that the evidence (§4) reachable through the providers that answer supports." | Provider failure | AT | `test_R4_FAIL_01` (6 fault sets x 2 companies: tavily errors, tavily 429, browsers, combined; all eight fields, origins and candidates judged by the oracle), `_05` | open (test committed; not yet run on a stage-4 build) |
| R4-FAIL-03 | "A build in which every research run fails, while searches and extracts are answered, completes `ready`, with every field `known` that the evidence reachable by search and extract supports." | Provider failure | AT | `test_R4_FAIL_01[nimble-research-errors]`, `test_R4_FAIL_02` | open (test committed; not yet run on a stage-4 build) |
| R4-FAIL-04 | "A build in which every call to every provider fails completes `failed` (§8), within the time bound of §8." | Provider failure | AT | `test_R4_FAIL_03` (<= 10.5 s, zero cost, all unknown), `_04` (a failed refresh leaves fields, history and feed), `_05` (a batch) | open (test committed; not yet run on a stage-4 build) |
| R4-FAIL-05 | "A call a provider refuses with an error status costs nothing (§9)." | Provider failure | AT | `test_R4_FAIL_01..05`: `spent_units` equals the mock's billed cost; refused entries cost 0 | open (test committed; not yet run on a stage-4 build) |

## S4-G Restarts

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-RST-01 | "The restart requirements of `stage-3.md` hold for batches as for the rest of the state." (batches, their ids, results and keys survive a SIGKILL and start) | Restarts | AT | `test_R4_RST_06`, carried `R3-RST-*` | open (test committed; not yet run on a stage-4 build) |
| R4-RST-02 | "When builds are running at the stop, everything else is still answered as before the stop" | Restarts | AT | `test_R4_RST_01` (accounts, tokens, a finished dossier with history and as_of, the list, the feed) | open (test committed; not yet run on a stage-4 build) |
| R4-RST-03 | Each build that was running "Does not stay `building`. It ends `ready` or `failed` within 10 seconds of `GET /health` first answering 200 after the restart, when each provider call it makes after the restart answers within one second. It may end `failed` although some of its calls succeeded; it then leaves the fields as they were (§8)." | Restarts | AT | `test_R4_RST_01/03/05` (<= 10.5 s polling; a failed first build: all unknown, no history; a failed refresh: fields, history, feed unchanged) | open (test committed; not yet run on a stage-4 build) |
| R4-RST-04 | "Is one build across the restart: its calls before and after the stop together spend at most 80 units (§9), and a batch's builds together never spend more than its `budget_units`." | Restarts | AT | `test_R4_RST_02` (fenwick-orchards, the biggest build), `_03` (budget 110, 4 builds) | open (test committed; not yet run on a stage-4 build) |
| R4-RST-05 | "Has every unit a provider billed for its calls, before and after the stop, counted in its dossier's `spent_units` and, for a batch's build, in the batch's `spent_units`. They may also count calls that were in flight at the stop and that no provider billed." | Restarts | AT | `test_R4_RST_01/02/03` (`spent_units` >= the mock's billed sum, <= 80 / budget) | open (test committed; not yet run on a stage-4 build) |
| R4-RST-06 | "After the restart, `POST /dossiers/{domain}/refresh` starts a new build of each such dossier as it does for any other." | Restarts | AT | `test_R4_RST_04` | open (test committed; not yet run on a stage-4 build) |

## S4-H Upgrades

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-UPG-01 | "A stage-4 service must accept an export produced by the same team's stage-1, stage-2 or stage-3 service, preserving dossiers, candidates, history, the change feed and completed idempotent responses as in `stage-1.md` §10." | Upgrades | AT | `test_R4_UPG_01/02/06/07` (needs OLD_BASE_URL, OLD2_BASE_URL, OLD3_BASE_URL); carried `test_upgrade`, `test_s3_upgrade` | open (test committed; not yet run on a stage-4 build) |
| R4-UPG-02 | "A stage-3 export keeps its builds: after the upgrade, `?as_of=` and `/values` answer from them as the stage-3 service did, with the keys this stage adds. Citations carried in the imported state remain citations served to this service." | Upgrades | AT | `test_R4_UPG_06/07` | open (test committed; not yet run on a stage-4 build) |
| R4-UPG-03 | "An export of a stage-1, stage-2 or stage-3 service has no `investors` candidates. After its import, `investors` is `unknown`, in the imported state and in every build kept from the export, and has no history entry" | Upgrades | AT | `test_R4_UPG_02/06/07` | open (test committed; not yet run on a stage-4 build) |
| R4-UPG-04 | "the first build that completes `ready` with a value for it adds a `change`, or an `initial` entry when it is the dossier's first build that completes `ready`." | Upgrades | AT | `test_R4_UPG_03/05/08` | open (test committed; not yet run on a stage-4 build) |
| R4-UPG-05 | Origins and corroboration of imported state: hosts as origins; stage-1/2 candidates gathered at `researched_at`; stage-3 builds at their times; the next build continues the standing origins. | Origins / Upgrades | AT | `test_R4_UPG_01/04/06/08` | open (test committed; not yet run on a stage-4 build) |
| R4-UPG-06 | Derived from §10 and Restarts: this service's own export carries batches (ids, results, budgets) and the completed `POST /batches` responses; import is replacement and repeatable. | §10 | AT | `test_R4_UPG_09` | open (test committed; not yet run on a stage-4 build) |

## S4-I Carried rows touched by stage 4

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R4-CAR-01 | Carried rows R-GEN-03 / R3-GEN-01 ("exactly six / seven fields") now mean eight fields; R-CAN-* / R-SEL-* kind rule is the stage-4 `own` rule; the idempotent write paths are three. | — | AT | carried suites with `assert_dossier_shape`, `oracle.ALL_FIELDS` (8), `rank.kind_of` (registrant) | open (test committed; not yet run on a stage-4 build) |

## Coverage summary — stage 4 (Analyst, before any run)

Rows: **383** = 319 carried + 64 `R4-*`. Status at this commit: every row `open` except the 4 carried `ruled` rows
(R-DEL-13, R-TXT-04, R-UPG-06, R-BLD-05). No row is failing, none is untested, none is review-only except the carried
R-UX-01..06 (UX Reviewer), which are reset to `open` like the rest.
Offline self-checks (no service): `test_s4_unit.py` 11, `test_timeline_unit.py`/`test_rank_unit.py`/`test_oracle_unit.py` 84 pass; `check_corpus.py` OK; the real mock web loads the 24-company corpus (`mockweb.corpus.load`). Collected: 653 tests (stage 3: 600 incl. 5 skipped).
Not run by the Analyst: any docker check (coordinator: one heavy check at a time, the Implementer first).
Rows verified by review only: none new. Rows partly assumed (rulings): R4-OWN-02 (RUL-S4-02), R4-ORG-06 (RUL-S4-05), R4-COR-06 (RUL-S4-07), R4-BAT-04 (RUL-S4-09), R4-BAT-08 for a build starved before its first call (RUL-S4-12).
