# Stage 1 — Requirement ledger (Analyst)

Source: `stage-1.md` (Dossier, Stage 1: company profiles), as handed off by the coordinator.
Verification: **AT** = black-box acceptance test in `acceptance/` (test function names carry the
ledger ID), **M** = measurement by `acceptance/up.sh`, **R** = review inspection of the delivered
`stage-1/` folder. Ambiguities and the readings adopted are in `RULINGS.md` (RUL-xx).

Status values: open (not yet run against a build) / passing / failing / ruled / review.
Status as of this commit: evidence revision **904e1fd** (`904e1fdc17429650299ac023886bbc0f7d0eda16`),
clean build of `stage-1/` in the analyst's own containers (`up.sh`, `--cpus 2 --memory 3g`, ports 18901/18981):
**271/271 acceptance tests passed** in 104 s; start→healthy 1 s. (Previous evidence: 1d3ccf7, 269/269.) Extra measurements on the same
image: started with no `PORT` (listens on 8080) and no `TAVILY_*` variables, three corpus
companies built `ready` with every expected value and only Nimble calls (R-RUN-01, R-DEL-04).

## §1 Scope / global invariants

| ID | Requirement (quoted) | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-GEN-01 | "Every value the service asserts cites at least one excerpt that a provider endpoint served to this service, and that excerpt supports the value. No citation is invented, reworded, or attached to a value it does not support." | 1 | AT | `citation_problems()` in every build test: oracle support + mock-log served text + corpus prose | passing @904e1fd |
| R-GEN-02 | "No build of a dossier spends more than 80 units (§9)." | 1, 9 | AT | per-build mock-log cost ≤ 80: `test_R_EVD_08_*`, `test_R_GEN_02_*`, `test_R_DEL_03_*` | passing @904e1fd |
| R-GEN-03 | "Contact data, people search, and fields other than the six in §4 are out of scope." | 1 | AT | `assert_dossier_shape` (exactly six fields) | passing @904e1fd |

## §2 Delivery and deployment

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-DEL-01 | "Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup." | 2 | R + M | files exist in `stage-1/`; `up.sh --build stage-1` | passing @904e1fd |
| R-DEL-02 | "The image must run on its own with `-e PORT=<port>` and a port mapping. All runtime dependencies, initialization and seed data must work within that single container. Compose configuration is not used." | 2 | M | `up.sh` runs the image alone with `-e PORT=8000 -p` | passing @904e1fd |
| R-DEL-03 | "every service must be able to research companies using Nimble alone." | 2 | AT | `test_R_DEL_03_*[tavily-down]` (expected fields unchanged) | passing @904e1fd |
| R-DEL-04 | "Tavily is optional … its absence must not prevent research while Nimble answers." | 2 | AT + M | `test_R_DEL_03_*[tavily-down, tavily-rate-limited]`; measured: image started without `TAVILY_*` | passing @904e1fd |
| R-DEL-05 | "every request to a provider goes through `web_router`: called in-process, or from a Python helper process … Calling a provider's API by any other route is not permitted." | 2 | R | code review; mock log shows only WebRouter-shaped calls | passing (review @904e1fd/1d3ccf7: no direct HTTP/SDK provider calls in app/, all via web_router, render never set) |
| R-DEL-06 | "The stage folder's dependency manifest lists `webrouter>=0.12.0`"; install `webrouter[search,extract,research]>=0.12.0` in the Docker build. | 2 | R | manifest + Dockerfile | passing (review @904e1fd: requirements.txt webrouter[search,extract,research]>=0.12.0, installed in docker build, image has 0.12.0) |
| R-DEL-07 | Tavily base URL passed as `provider_config={"tavily": {"api_base_url": <TAVILY_BASE_URL>}}`; Nimble reads `NIMBLE_API_KEY`/`NIMBLE_BASE_URL`. | 2 | R + AT | review; any Tavily call appears in the mock log | passing @904e1fd (AT) + review PASS: provider_config tavily.api_base_url built from TAVILY_BASE_URL; Tavily calls observed at the mock |
| R-DEL-08 | Limits "CPU 2 vCPU", "Memory 3 GiB". | 2 | M | `up.sh` runs with `--cpus 2 --memory 3g`; whole suite passes | passing @904e1fd |
| R-DEL-09 | "Start to first healthy response 60 s". | 2, 3.2 | M | `up.sh` prints start→healthy seconds, fails if > 60 | passing @904e1fd |
| R-DEL-10 | "Concurrent requests up to 50 in flight". | 2 | AT | `test_R_CON_02_R_DEL_10_fifty_in_flight` | passing @904e1fd |
| R-DEL-11 | "Per-request timeout 5 s (10 s for `POST /_test/reset`)". | 2 | AT | client timeouts 5 s (10 s reset/import/export) on every request | passing @904e1fd |
| R-DEL-12 | "Outbound network … at run time, only the provider endpoints this specification lists"; "Runtime assets and dependencies must be included in the image." | 2 | R | Dockerfile/code review (no runtime downloads) | passing (review + measurement @904e1fd: healthy with --network none; on an --internal network reaching only the mock builds ready; PyPI egress blocked) |
| R-DEL-13 | "Disk ephemeral; state need not survive a container restart." | 2 | — | permissive; nothing to verify | ruled |

## §3 Runtime contract

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-RUN-01 | "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." | 3.1 | M | `up.sh` (PORT=8000); measured: no `PORT` → 8080 | passing @904e1fd |
| R-RUN-02 | "`GET /health -> 200 {"status": "ok"}`" once ready | 3.2 | AT | `test_R_RUN_02_health` | passing @904e1fd |
| R-RUN-03 | "`/health` makes no provider call." | 3.2 | AT | `test_R_RUN_03_*` | passing @904e1fd |
| R-RST-01 | "Replace all service state with the fixture … subsequent requests must see only that fixture: no users other than the seeded ones" | 3.3 | AT | `test_R_RST_01_*` | passing @904e1fd |
| R-RST-02 | "… no dossiers" | 3.3 | AT | `test_R_RST_02_R_RST_03_*` | passing @904e1fd |
| R-RST-03 | "… and no stored idempotent responses." | 3.3 | AT | `test_R_RST_02_R_RST_03_*` | passing @904e1fd |
| R-RST-04 | "Repeated resets are supported." | 3.3 | AT | `test_R_RST_06_R_RST_04_*` | passing @904e1fd |
| R-RST-05 | "A build still running when reset is called must not change the state that follows the reset." | 3.3 | AT | `test_R_RST_05_*` | passing @904e1fd |
| R-RST-06 | "This control endpoint must be enabled in the delivered image and requires no authentication." `204 No Content` | 3.3 | AT | `test_R_RST_06_*` | passing @904e1fd |
| R-RST-07 | "Seeded users must be able to log in with the given password immediately." | 4 Fixture | AT | `test_R_RST_07_R_AUTH_08_*` | passing @904e1fd |
| R-RST-08 | "A fixture with two users sharing an email is a reset error: 422 `validation_failed`, changing nothing." | 4 Fixture | AT | `test_R_RST_08_*` | passing @904e1fd |
| R-RST-09 | "`now` is required and sets the clock (§3.4)." | 4 Fixture | AT | `test_R_RST_09_*` (RUL-14) | passing @904e1fd |
| R-RST-10 | Tokens issued before a reset are invalid after it. | 3.3 | AT | `test_R_RST_10_*` (RUL-11) | passing @904e1fd |
| R-RST-11 | Unparseable reset body → 400 `malformed_request`. | 3.3, 5 | AT | `test_R_RST_11_*` | passing @904e1fd |
| R-CLK-01 | "Reset sets the clock to the fixture's `now`." | 3.4 | AT | `test_R_CLK_01_R_BLD_03_*` | passing @904e1fd |
| R-CLK-02 | "The service keeps a clock that only reset and `POST /_test/clock` move. Every timestamp the service records or returns is read from this clock." | 3.4 | AT | `test_R_CLK_02_*` | passing @904e1fd |
| R-CLK-03 | "The clock stands still between calls: two requests with no clock call between them read the same time." | 3.4 | AT | `test_R_CLK_03_*` | passing @904e1fd |
| R-CLK-04 | "A `now` earlier than the clock's current time is 422 `validation_failed` and changes nothing." | 3.4 | AT | `test_R_CLK_04_*` | passing @904e1fd |
| R-CLK-05 | "`now` is an RFC 3339 timestamp with an explicit offset." | 3.4 | AT | `test_R_CLK_05_*` (RUL-13) | passing @904e1fd |
| R-CLK-06 | "`POST /_test/clock` requires no authentication." | 3.4 | AT | `test_R_CLK_02_R_CLK_06_*` | passing @904e1fd |
| R-CLK-07 | "Before the first reset the clock follows the system time." | 3.4 | R | review (RUL-35) | passing (review @904e1fd: without reset, researched_at followed system time) |
| R-CLK-08 | Equal `now` accepted. | 3.4 | AT | `test_R_CLK_08_*` (RUL-13) | passing @904e1fd |
| R-CLK-09 | `Z` accepted as an explicit offset. | 3.4 | AT | `test_R_CLK_09_*` (RUL-13) | passing @904e1fd |
| R-CNV-01 | "Requests and responses are `application/json; charset=utf-8`." | 3.5 | AT | `test_R_CNV_01_*` | passing @904e1fd |
| R-CNV-02 | "Timestamps in responses are RFC 3339 with an explicit offset" | 3.5 | AT | `parse_ts` on every timestamp | passing @904e1fd |
| R-CNV-03 | "Unknown fields in a request body are ignored, never an error." | 3.5 | AT | `test_R_CNV_03_*` (auth + dossiers) | passing @904e1fd |
| R-CNV-04 | "Unknown query parameters are ignored." | 3.5 | AT | `test_R_CNV_04_*` | passing @904e1fd |
| R-CNV-05 | "IDs are opaque strings of at most 64 characters." | 3.5 | AT | `assert_dossier_shape`, `test_R_AUTH_01_*` | passing @904e1fd |

## §4 Model

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-AUTH-12 | "Every authenticated user sees the same dossiers." | 4 Users | AT | `test_R_AUTH_12_*` | passing @904e1fd |
| R-DOM-01 | Domain "normalised: surrounding whitespace removed, lowercased, one trailing `.` removed, and one leading `www.` removed" (body and path) | 4 Domains | AT | `test_R_DOM_01_*` | passing @904e1fd |
| R-DOM-02 | "two or more labels … each label 1 to 63 characters of `a-z`, `0-9` and `-`, not starting or ending with `-`, and 253 characters or fewer in total. Anything else … is 422 `validation_failed`." | 4 Domains | AT | `test_R_DOM_02_*` (body, path, 254-char) | passing @904e1fd |
| R-DOM-03 | "including a URL with a scheme or a path, is 422" | 4 Domains | AT | `test_R_DOM_02_R_DOM_03_*` | passing @904e1fd |
| R-DOM-04 | "`Acme-Robotics.TEST.`, `www.acme-robotics.test` and `acme-robotics.test` name the same company and the same dossier. Responses always carry the normalised domain." | 4 Domains | AT | `test_R_DOM_01_R_DOM_04_*`, `test_R_POST_03_*` | passing @904e1fd |
| R-DOM-05 | Only *one* trailing dot and *one* leading `www.` are removed. | 4 Domains | AT | `test_R_DOM_05_*` (`www.www.…`, `acme.test..`, `www.test`) | passing @904e1fd |
| R-FLD-01 | "A dossier has exactly these six fields" with the listed types; `headcount_range` one of the eight ranges | 4 Fields | AT | `assert_dossier_shape` | passing @904e1fd |
| R-FLD-02 | "`status` is `known` when `value` is not null, and `unknown` when it is." "An `unknown` field has `"value": null` and `"citations": []`." | 4 Fields | AT | `assert_dossier_shape` | passing @904e1fd |
| R-FLD-03 | "A `known` field has one or more citations." `url` = page the excerpt was served for, `provider` is `nimble` or `tavily`, the one that served it. | 4 Fields | AT | `assert_dossier_shape`, `citation_problems` (log provider + url) | passing @904e1fd |
| R-FLD-04 | "A string value is written as the supporting excerpt writes it, without surrounding whitespace." | 4 Fields | AT | oracle value equality (corpus tests) | passing @904e1fd |
| R-FLD-05 | "A headcount the web states as a number, or as a range that fits inside one of the ranges above, has the range that contains it as its value." | 4 Fields | AT | talloway (1,450), vantorra (51-200), sablewood (10,500), wrenfield (300), orrin (75) | passing @904e1fd |
| R-EVD-01 | "every build makes exactly one [successful search] whose query is exactly the company's normalised domain … its other such searches use other queries. A search that a provider answers with an error does not count." | 4 Evidence | AT | `check_log_rules` in corpus tests, `test_R_IDEM_10_*`, `test_R_REF_*`, `test_R_DEL_03_*` (RUL-28) | passing @904e1fd |
| R-EVD-02 | "The excerpt is copied character for character from that served text, except that any run of whitespace may be written as a single space. It is 1 to 500 characters long." | 4 Evidence | AT | `citation_problems` | passing @904e1fd |
| R-EVD-03 | "It is taken from the page's prose (below), not from its header." | 4 Evidence | AT | `test_R_EVD_03_R_EVD_10_*`; corpus-prose check in `citation_problems` | passing @904e1fd |
| R-EVD-04 | "`url` is the URL of the page the excerpt was served for" | 4 Fields | AT | `citation_problems` (served for that url by that provider) | passing @904e1fd |
| R-EVD-05 | "The claim is asserted only when its citation supports it. A field is `unknown` when no evidence supports a value for it, even when a research answer claims one." | 4 Evidence | AT | orrin-bay `funding_total` unknown | passing @904e1fd |
| R-EVD-06 | Evidence includes "every claim that a `nimble` research run for the company asking for all six fields answers with" | 4 Evidence | AT | `test_R_EVD_06_*`, orrin-bay ceo/headcount (RUL-09) | passing @904e1fd |
| R-EVD-07 | "When the evidence supports more than one value for a field, the field holds one of them and cites only excerpts that support that value." | 4 Evidence | AT | `test_R_EVD_07_*` (ledgerline) | passing @904e1fd |
| R-EVD-08 | "When a build completes `ready`, each field is `known` exactly when the evidence (§4) supports a value for it." | 8 Builds | AT | `test_R_EVD_08_R_SUP_corpus_company[*]` (11 companies incl. fenwick-orchards: >10 pages, facts only reachable by other queries naming the company) | passing @904e1fd |
| R-EVD-09 | Evidence is each page "with its full text" | 4 Evidence | AT | `test_R_EVD_09_*` (sablewood), talloway history (RUL-10) | passing @904e1fd |
| R-EVD-10 | "The header line `Facts:` … is informative only: citations come from the prose" | 4 Pages | AT | `test_R_EVD_03_R_EVD_10_*` (quorra) | passing @904e1fd |
| R-EVD-11 | Degraded providers: with Nimble extract + research and Tavily extract + search all refused, a `ready` build still has every field `known` that the evidence (full page texts) supports, and spends ≤ 80. | 4, 8, 9 | AT | `test_R_EVD_11_extract_and_research_refused[*]` (RUL-34, Reviewer F4) | failing @904e1fd: fenwick-orchards (12 pages, facts outside the domain query's top 10) ends ready with all six unknown, 47 of 80 units spent; the other 7 companies pass (work item 5) |

## §5 Errors

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-ERR-01 | "Every 4xx and 5xx response carries this body: `{ "error": { "code": …, "message": … } }`" | 5 | AT | `Api.req` checks every 4xx | passing @904e1fd |
| R-ERR-02 | "400 `malformed_request` Unparseable body, or a field of the wrong JSON type" | 5 | AT | `test_R_ERR_02_*` (auth, dossiers, reset, import, clock) (RUL-15) | passing @904e1fd |
| R-ERR-03 | "401 `unauthenticated` Missing, malformed or unknown bearer token" | 5, 6 | AT | `test_R_AUTH_09_*` | passing @904e1fd |
| R-ERR-04 | "404 `not_found` No such resource" | 5 | AT | `test_R_ERR_04_*`, `test_R_REF_03_*` | passing @904e1fd |
| R-ERR-05 | "Requests must not produce 5xx responses, including under concurrent load and when a provider endpoint answers with an error." | 5 | AT | every request (`Api.req` raises on 5xx); weather, faults, 50-in-flight | passing @904e1fd |
| R-ERR-06 | "`limit` integer 1 to 200", "`offset` integer 0 or more", "An integer-valued query parameter is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422" | 5 | AT | `test_R_ERR_06_*` (RUL-19) | passing @904e1fd |
| R-ERR-07 | "A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`" | 5 | AT | domain, email, password, display_name, clock, import tests | passing @904e1fd |

## §6 Authentication

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-AUTH-01 | "`POST /auth/signup` → 201 `{ "user_id", "display_name", "token" }`" | 6 | AT | `test_R_AUTH_01_*` | passing @904e1fd |
| R-AUTH-02 | "`POST /auth/login` → 200 `{ "user_id", "display_name", "token" }`" | 6 | AT | `test_R_AUTH_02_*` | passing @904e1fd |
| R-AUTH-03 | "Email already registered → 409 `email_taken`" (incl. seeded emails) | 6 | AT | `test_R_AUTH_03_*` | passing @904e1fd |
| R-AUTH-04 | "Password shorter than 8 characters → 422" | 6 | AT | `test_R_AUTH_04_*` (7 rejected, 8 accepted) | passing @904e1fd |
| R-AUTH-05 | "`email` not of the form `local@domain` → 422" | 6 | AT | `test_R_AUTH_05_*` (RUL-31) | passing @904e1fd |
| R-AUTH-06 | "`display_name` empty or longer than 100 characters → 422" | 6 | AT | `test_R_AUTH_06_*` (100 accepted) | passing @904e1fd |
| R-AUTH-07 | "Wrong password or unknown email on login → 401 `unauthenticated`" | 6 | AT | `test_R_AUTH_07_*` | passing @904e1fd |
| R-AUTH-08 | "For a user seeded by the fixture, `user_id` is that user's `id` in the fixture." | 6 | AT | `test_R_RST_07_R_AUTH_08_*` | passing @904e1fd |
| R-AUTH-09 | "Every other endpoint requires a bearer token … A request … that lacks a valid token is 401 `unauthenticated`, even when it also lacks a required `Idempotency-Key`." | 6 | AT | `test_R_AUTH_09_*` | passing @904e1fd |
| R-AUTH-10 | "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions." | 6 | AT | `test_R_AUTH_10_*` (both) | passing @904e1fd |
| R-AUTH-11 | "Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2 … Plaintext password storage is not permitted." | 6 | R + AT | code review; `test_R_AUTH_11_*` (no plaintext in export) | passing @904e1fd (AT) + review PASS: hashlib.scrypt N=2^14 r=8 p=1, random 16-byte salt, compare_digest; no plaintext in export |
| R-AUTH-13 | Missing signup/login fields → 422; wrong types → 400. | 5, 6 | AT | `test_R_AUTH_13_*`, `test_R_ERR_02_auth_*` (RUL-33) | passing @904e1fd |
| R-CON-01 | Concurrent signups with one email: exactly one 201. | 6, 11 | AT | `test_R_CON_01_concurrent_signup_same_email` | passing @904e1fd |

## §7 Idempotency

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-IDEM-01 | "Header absent or empty → 400 `missing_idempotency_key`" (both write paths) | 7 | AT | `test_R_IDEM_01_*` | passing @904e1fd |
| R-IDEM-02 | "The key is scoped to the authenticated user. Two different users may use the same key string with no interaction between them." | 7 | AT | `test_R_IDEM_02_*` | passing @904e1fd |
| R-IDEM-03 | "Replay: same key, same body → 200, body identical to the original response as a JSON value" | 7 | AT | `test_R_IDEM_03_*` (202- and 200-originals) | passing @904e1fd |
| R-IDEM-04 | "Same key, different body → 409 `idempotency_key_reuse`" | 7 | AT | `test_R_IDEM_04_*` | passing @904e1fd |
| R-IDEM-05 | "The same key with the same body on a different path is a different request, not a replay, and must succeed normally." | 7 | AT | `test_R_IDEM_05_*` | passing @904e1fd |
| R-IDEM-06 | "`Acme-Robotics.test` and `acme-robotics.test` in a path or body are different requests for this rule" | 7 | AT | `test_R_IDEM_06_*` (RUL-20) | passing @904e1fd |
| R-IDEM-07 | "Key reused after the original request failed with 4xx → Treated as a first use" | 7 | AT | `test_R_IDEM_07_*` (422 and 404) | passing @904e1fd |
| R-IDEM-08 | "'Same body' means the same JSON value after parsing — key order and whitespace do not matter … a body that differs from the first only in unknown fields is the same body" | 7 | AT | `test_R_IDEM_08_*` (RUL-21) | passing @904e1fd |
| R-IDEM-09 | "`POST /dossiers/{domain}/refresh` takes no body; any body sent to it is ignored and plays no part in deciding a replay." | 7 | AT | `test_R_IDEM_09_*` (RUL-17) | passing @904e1fd |
| R-IDEM-10 | "For concurrent identical requests with an unused key, exactly one returns the normal response. The others return 200 with the same body. The operation takes effect only once." | 7 | AT | `test_R_IDEM_10_*` (create + refresh) | passing @904e1fd |
| R-IDEM-11 | "A successful replay returns the original response, even after the dossier has changed. It starts no build and makes no provider call." | 7 | AT | `test_R_IDEM_03_R_IDEM_11_*`, `test_R_IDEM_09_*` | passing @904e1fd |
| R-IDEM-12 | "After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before field validation." | 7 | AT | `test_R_IDEM_12_*` (RUL-16) | passing @904e1fd |
| R-IDEM-13 | "`Idempotency-Key` 1 to 255 characters, otherwise 422 `validation_failed`" | 5 | AT | `test_R_IDEM_13_*` | passing @904e1fd |

## §8 API

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-BLD-01 | "A dossier has at most one build running at a time." | 8 | AT | `test_R_REF_02_R_BLD_01_*`, `test_R_IDEM_10_*` | passing @904e1fd |
| R-BLD-02 | "A build ends in `ready` when it completed, or `failed` when none of its provider calls succeeded. A failed build leaves the fields as they were." | 8 | AT | `test_R_BLD_02_*` | passing @904e1fd |
| R-BLD-03 | "A build's time is the clock's time when the request that started it was received." (`researched_at`) | 8 | AT | `test_R_CLK_*`, `test_R_GET_03_*`, `test_R_REF_04_*` | passing @904e1fd |
| R-BLD-04 | "A build whose provider calls each answer within one second ends within 10 seconds of the request that started it." | 8 | AT | `test_R_BLD_04_*` | passing @904e1fd |
| R-BLD-05 | Live providers: no give-up on a call waiting < 30 s, no time-based stop in the first 120 s, ends within 300 s. | 8 | R | code review of timeouts (live providers not reachable in tests) | passing (review @904e1fd: code reading + shortened-timing runs; not live-tested) |
| R-BLD-06 | "Reading a dossier, listing dossiers and every other request except `POST /dossiers` and `POST /dossiers/{domain}/refresh` make no provider call." | 8 | AT | `test_R_BLD_06_*`, `test_R_RUN_03_*`, `test_R_EXP_*` (import) | passing @904e1fd |
| R-POST-01 | "When no dossier exists … creates one, starts its first build and returns 202 `{dossier_id, domain, state: building}`" | 8 | AT | `test_R_POST_01_*` | passing @904e1fd |
| R-POST-02 | "When a dossier already exists … starts no build and returns 200 with that dossier's `dossier_id`, `domain` and current `state`." | 8 | AT | `test_R_POST_02_*`, `test_R_REF_02_*` (RUL-26) | passing @904e1fd |
| R-POST-03 | "Concurrent requests for the same domain create one dossier and start one build, whatever their keys." | 8 | AT | `test_R_POST_03_R_CON_03_*` | passing @904e1fd |
| R-POST-04 | "`domain` missing → 422"; "invalid after normalisation → 422" | 8 | AT | `test_R_POST_04_*`, `test_R_DOM_02_*` | passing @904e1fd |
| R-GET-01 | `GET /dossiers/{domain}` shape: `dossier_id, domain, state, researched_at, spent_units, fields` | 8 | AT | `assert_dossier_shape` | passing @904e1fd |
| R-GET-02 | "`fields` always holds all six fields. Before the first build completes `ready`, every field is `unknown`." | 8 | AT | `test_R_GET_02_*`, `test_R_BLD_02_*` | passing @904e1fd |
| R-GET-03 | "While a later build runs, `fields` are those of the last build that completed `ready`." `state` is `building` while a build runs. | 8 | AT | `test_R_GET_03_*` | passing @904e1fd |
| R-GET-04 | "`researched_at` is the time of the last build that completed `ready`, or null." | 8 | AT | `test_R_GET_02/03_*`, `test_R_BLD_02_*` | passing @904e1fd |
| R-GET-05 | "`spent_units` is the total cost (§9) of every provider call made for this dossier, by every build, since it was created." | 8 | AT | `test_R_REF_01_*`, `test_R_GEN_02_*`, corpus tests (== mock-log cost) | passing @904e1fd |
| R-GET-06 | "The domain in the path is normalised (§4). No dossier for it is 404 `not_found`." | 8 | AT | `test_R_DOM_01_R_GET_06_*`, `test_R_ERR_04_*` | passing @904e1fd |
| R-REF-01 | Refresh "Starts a new build … returns 202 `{dossier_id, domain, state: building}`"; "its build makes provider calls whether or not anything has changed … its spending counts in `spent_units`." | 8 | AT | `test_R_REF_01_*` | passing @904e1fd |
| R-REF-02 | "A refresh received while a build of the dossier is running starts no second build and returns 202 with the same body." | 8 | AT | `test_R_REF_02_*`, `test_R_CON_01_serializable_*` | passing @904e1fd |
| R-REF-03 | "No dossier for the domain → 404 `not_found`" | 8 | AT | `test_R_REF_03_*` | passing @904e1fd |
| R-REF-04 | A refresh researches again and replaces the fields with the new result. | 8 | AT | `test_R_REF_04_*` (mock epoch 0→1) | passing @904e1fd |
| R-LST-01 | List item: `dossier_id, domain, state, legal_name, researched_at, spent_units`; "`legal_name` is the value of the dossier's `legal_name` field, or null." | 8 | AT | `test_R_LST_01_*` | passing @904e1fd |
| R-LST-02 | "only dossiers whose domain or `legal_name` contains `q`, compared case-insensitively … An empty `q` lists every dossier." | 8 | AT | `test_R_LST_02_*` | passing @904e1fd |
| R-LST-03 | "Dossiers are ordered by domain ascending." | 8 | AT | `test_R_LST_03_*` | passing @904e1fd |
| R-LST-04 | "`limit` defaults to 50, range 1 to 200. `offset` defaults to 0. `has_more` is true when items exist beyond the last one returned." | 8 | AT | `test_R_LST_04_*` (incl. 52 dossiers) | passing @904e1fd |

## §9 Providers and cost

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-COST-01 | Unit costs per the §9 table; `spent_units` equals them. | 9 | AT | spent_units == mock-log cost (mock implements the table) | passing @904e1fd |
| R-COST-02 | "A build stops making provider calls before its spending would exceed 80 units, and completes with the pages and research claims it has obtained." | 9 | AT | per-build cost ≤ 80 in all build tests | passing @904e1fd |
| R-COST-03 | "A research request names the company by its domain in its query, and names the fields it asks for by the field names in §4, as the property names of its output schema." | 9 | AT | `check_log_rules` | passing @904e1fd |
| R-COST-04 | "An extract through `nimble` does not set `render`." | 9 | AT | `check_log_rules` (cost = 1 per URL) | passing @904e1fd |
| R-COST-05 | "A call that a provider refuses with an error status costs nothing." | 9 | AT | `test_R_BLD_02_*` (spent 0) | passing @904e1fd |
| R-COST-06 | "A call whose answer does not arrive, because it times out … costs its units" | 9 | AT | `test_R_COST_06_*` (delay; spent == log) | passing @904e1fd |

## §10 Export and import

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-EXP-01 | "Return 200 from export with a JSON object containing `track: "dossier"`, `format_version: 1` and `state`" | 10 | AT | `test_R_EXP_01_*` | passing @904e1fd |
| R-EXP-02 | "Import takes that entire object and atomically replaces the service's state, returning 204. It must accept an unchanged export produced by this service." | 10 | AT | `test_R_EXP_02_to_R_EXP_10_roundtrip` | passing @904e1fd |
| R-EXP-03 | "Preserve accounts and hashed-password login, existing bearer tokens, dossiers with their ids, states, fields, citations, `researched_at` and `spent_units`, all completed idempotent request bodies and original responses." | 10 | AT | roundtrip | passing @904e1fd |
| R-EXP-04 | "Failed request keys remain reusable." | 10 | AT | roundtrip | passing @904e1fd |
| R-EXP-05 | "Import removes all previous destination data and credentials." | 10 | AT | roundtrip (Dora) | passing @904e1fd |
| R-EXP-06 | "Import is replacement, not merge; repeating it restores the exported state without duplicating anything." | 10 | AT | roundtrip | passing @904e1fd |
| R-EXP-07 | "Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination." | 10 | AT | `test_R_EXP_07_*` (RUL-23) | passing @904e1fd |
| R-EXP-08 | "Import makes no provider call" | 10 | AT | roundtrip (mock log empty) | passing @904e1fd |
| R-EXP-09 | "Export and import do not change the clock." | 10 | AT | roundtrip, `test_R_EXP_09_*` | passing @904e1fd |
| R-EXP-10 | "Reset clears all state, including imported state." | 10 | AT | roundtrip | passing @904e1fd |
| R-EXP-11 | "An export taken while a build is running holds the dossier as it was before that build; after import, that dossier is in the state of its last completed build, or `failed` with every field `unknown` when no build had completed." | 10 | AT | `test_R_EXP_11_*` (first build, refresh) (RUL-22) | passing @904e1fd |
| R-EXP-12 | "Export is an atomic, read-only snapshot; subsequent source writes do not change it." | 10 | AT | roundtrip (two exports equal) | passing @904e1fd |
| R-EXP-13 | Export/import are unauthenticated control endpoints. | 10 | AT | all export/import tests send no token | passing @904e1fd |

## §11 Concurrency

| ID | Requirement | § | Verify | Test / check | Status |
|---|---|---|---|---|---|
| R-CON-02 | "Concurrent requests must produce the same results as executing them one at a time in some order." / 50 in flight | 11, 2 | AT | `test_R_CON_02_*`, `test_R_IDEM_10_*`, `test_R_POST_03_*` | passing @904e1fd |
| R-CON-03 | "The requirements above hold at every read." | 11 | AT | `test_R_GET_02/03_*` (reads during builds) | passing @904e1fd |

## Appendix A — support rule (end-to-end on the analyst corpus, judged by `oracle.py`)

Each row is checked by `test_R_EVD_08_R_SUP_corpus_company[<domain>]` and by the oracle unit
tests (`test_oracle_unit.py`, which reproduce every example the specification gives).

| ID | Requirement | § | Corpus cases | Status |
|---|---|---|---|---|
| R-SUP-01 | A.1 sentences: split at `.`/`!`/`?` (+ closing `"”’)`) followed by whitespace; a `.` ending a legal-form suffix does not end a sentence; rule 1 "It is a single sentence". | A.1, A.2 | meridel founded (`!` split), wrenfield founded (`Inc.` inside), vantorra legal (`S.A.` inside), wrenfield headcount (`."` closer) | passing @904e1fd |
| R-SUP-02 | "It names the company: it contains the company's normalised domain, or the company's name" (whole word, case-insensitive) | A.2 | sablewood hq/founded by domain | passing @904e1fd |
| R-SUP-03 | "It contains a statement phrase for F" | A.2, A.3 | meridel `raised CHF 5 million` (no amount); ledgerline `€30M`; unknown fields of ledgerline | passing @904e1fd |
| R-SUP-04 | "It contains none of the negating phrases" | A.2, A.3 | quorra (not, former, reportedly, in talks to, would), orrin funding (hopes to) | passing @904e1fd |
| R-SUP-05 | "every value in F's format that it contains normalises to V" | A.2 | meridel ceo (two names), meridel headcount (120 and 1998), quorra headcount (10-50) | passing @904e1fd |
| R-SUP-06 | legal_name format, "the shortest counts", suffix list | A.4 | talloway `, Inc.`, vantorra `Holdings S.A.`, meridel `Pty Ltd`, sablewood `Ltd`, wrenfield `AG` (shortest before `GmbH`) | passing @904e1fd |
| R-SUP-07 | hq_city: "longest run of capitalised words joined by single spaces or by `-`" directly after the phrase | A.4 | `Porto Alegre`, `Saint-Malo`, `Tromsø`, `Den Haag`, `Zürich`, `Vila Nova` (stops at `de`) | passing @904e1fd |
| R-SUP-08 | ceo: run of two or three capitalised words, name and phrases taken out first | A.4 | `Mara Quintero`, `Noor Haddad` (after `Chief Executive Officer`), `Maria Elena Costa`, `Jonas Ek`, `Priya Lindqvist` | passing @904e1fd |
| R-SUP-09 | founded_year: four digits 1800–2099, not part of an amount | A.4 | 2011, 1987, 1996, 2008, 1979, 2001, {2003, 2004} | passing @904e1fd |
| R-SUP-10 | headcount: number ≥ 1 without decimal part, not part of an amount; ranges hold two numbers | A.4, A.5 | 1,450→1001-5000; 51-200; 10,500→10001+; 300→201-500; 75→51-200 | passing @904e1fd |
| R-SUP-11 | Amount forms (`$`/`US$`/`USD`, scales `k m mn bn thousand million billion`, `dollars`/`US dollars`); "Amounts in other currencies are not amounts"; normalisation to whole dollars | A.4, A.5 | `US$ 37.5 million`, `$4.5m`, `$1.2345m`, `$850k`, `750 thousand US dollars`, `$12M`/`12 million dollars`/`US$12 million`/`$12,000,000`, `€30M`, `CHF 5 million` | passing @904e1fd |
| R-SUP-12 | A company with no evidence: `ready`, all fields unknown | A, 8 | `nowhere-at-all.test` | passing @904e1fd |
| R-SUP-13 | The analyst oracle reproduces every example in §4 and Appendix A | A | `test_oracle_unit.py` (offline) | passing |

## Coverage summary (evidence revision 904e1fd; Reviewer verdicts folded in)

- Rows: 157.
- passing: 155 (acceptance-tested or measured against 904e1fd: 271/271; review-only rows R-DEL-05, R-DEL-06, R-DEL-12, R-BLD-05, R-CLK-07 passed by the Reviewer on 904e1fd/1d3ccf7). R-DEL-07 and R-AUTH-11: acceptance parts pass and the Reviewer passed their review parts.
- ruled: 1 (R-DEL-13 needs nothing).
- failing: 1: R-EVD-11 (new case for Reviewer finding F4; fails on 904e1fd for fenwick-orchards; work item 5).
- open: 0. Untested without a recorded reason: 0.
