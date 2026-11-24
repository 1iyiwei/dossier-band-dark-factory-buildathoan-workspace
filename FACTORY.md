# FACTORY

A five-seat software factory in Band Desktop. The seats plan, implement, check
each other independently, and route every failure to the seat that owns it.
The mandates in `mandates/` are generic: nothing in them names this track.

## Design in one paragraph

Shipped tests are a small, known sample of what judges check; the rest is
written in the specification. So the factory's main check is **a second,
independent reading of the specification**: an Analyst seat turns every
testable sentence into a **requirement ledger** and writes **black-box
acceptance tests from the specification alone**, without reading the code. The
Implementer builds to the specification, not to the tests. The Reviewer
rebuilds from a clean clone, runs every check itself, and rejects with
evidence naming who owns the fix. A UX Reviewer drives the product as a user
(a browser when there's a UI; exploratory probing of the API when there isn't).
An increment closes only when the Reviewer accepts **and** every ledger row
has passing evidence or a recorded ruling.

## Seats

| Seat | Handle | Harness | Model | Effort | Owns |
|---|---|---|---|---|---|
| Coordinator | `@hack/coordinator` | Claude Code | `claude-sonnet-5-5` | medium | Plan, self-contained handoffs, tracking, final report; writes no code |
| Analyst | `@hack/analyst` | Claude Code | `claude-sonnet-5-5` | high | Requirement ledger, rulings on ambiguities, black-box acceptance tests |
| Implementer | `@hack/implementer` | Claude Code | `claude-sonnet-5-5` | high | Source, Dockerfile, RUN.md |
| Reviewer | `@hack/reviewer` | Claude Code | `claude-sonnet-5-5` | medium | Clean-clone build, all checks run independently, measured limits; accept or reject |
| UX Reviewer | `@hack/ux-reviewer` | Claude Code | `claude-haiku-5-5` | medium | Every named UI state at 375 px and desktop; exploratory API probing when there is no UI |

## Mechanisms (all in the mandates)

- **Independence.** The Analyst writes its tests before reading the
  implementation, and may read the code afterwards only to diagnose a disputed
  failure, never to bend a test to it. The Implementer never edits the
  Analyst's files.
- **The ledger is the contract.** `stage-N/requirements/LEDGER.md` lists every
  testable statement with its source sentence, how it is verified, and its
  status; `RULINGS.md` records every ambiguity, the reading adopted and why.
  Non-functional requirements (limits, budgets, timeouts, concurrency,
  restarts, upgrades, layout, accessibility) are ledger rows with a measurable
  check.
- **Routing failures to their cause.** Every rejection names its owner: the
  Implementer for a code defect, the Analyst for a test that contradicts the
  specification, the Coordinator for a missing requirement or an environment
  problem.
- **Self-contained handoffs.** The Coordinator pastes the full task and the
  full specification text into every handoff; no seat is asked to read the
  room.
- **Increments in order.** A stage's specification is opened only when the
  previous folder is final; a finalized folder never changes; each new stage
  starts as a copy of the previous one.
- **Dark factory.** No seat asks the human anything after the dispatch;
  blockers go into the Coordinator's final report with evidence.
- **Traceable git.** Each seat commits under its own identity
  (`git -c user.name="<Seat>" -c user.email="<handle>@band.invalid"`), in
  small commits naming the work item and ledger IDs. No amend, rebase or
  squash.
- **Reply with the result (from stage 4).** A seat can post only by
  replying, once, to the message it is handling, so it does the work first
  and replies with the result; it never acknowledges first and reports later.
- **Working economically.** Long command output goes to files; seats read only
  summaries and failures; no seat re-runs a check another seat already
  reported with evidence for the same revision; one heavy check at a time.

## Standing it up

1. **Band Desktop → Agents → New agent**, once per seat in the table:
   - Name and handle as in the table; Runtime: Claude Code; Model and
     Reasoning effort as in the table (they must match the mandate's header).
   - Instructions: link the seat's `mandates/<seat>.md`.
   - Working directory: the absolute path of the result repository.
   - Claude customizations: your Claude setup (it carries the sign-in),
     but with no personal rule, e.g. "don't commit" in your CLAUDE.md, that
     covers the seats: Claude Code's permission check enforces it;
     MCP servers: only Band's; Permission mode: Auto.
   - Run **Test runtime** before **Create agent**, and again right before a
     dispatch (an expired sign-in stops a seat at its first turn).
2. If your Band owner name is not `hack`, replace `@hack/` in the mandates.
3. **Create a room with only the Coordinator** and check the participant list
   (Band can add a default agent; every seat in the room log needs a mandate).
4. **Dispatch** as the room's first message, choosing the Coordinator from the
   mention picker. The dispatch carries everything track-specific; our
   template:

   > @hack/coordinator You lead our factory. Build stage 1 of the track below,
   > coordinating the other seats. Track: … Result repository: … Stage folder:
   > …/stage-1/ (source, Dockerfile, RUN.md). Kickoff package (read-only): …
   > Stage 1 specification: read it in full from …/spec/stage-1.md and paste
   > the complete text into every handoff. Do not open any later stage's
   > specification. Local mock web: … explains how to run it beside the
   > service; use it to run the service, not as a source of answers. Checks:
   > `python -m harness run --track … --repo … --stage N --out <new dir>`; add
   > `--mode isolated` for the final check. Only part of each stage's checks
   > ship; the rest are in the specification. Run one check at a time across
   > the band. Resolve everything within the band. Do not ask me anything;
   > record any blocker with its evidence in your final report.

## How it caught bad work

### Stage 1

| When (UTC) | Who | What | Fix |
|---|---|---|---|
| Nov 13 23:52 | UX Reviewer | Review #1 of `92ab620`: four should-fix findings from API probing, plus RUN.md gaps | Fixed in `da61100`; re-run accepted 23:59 |
| Nov 13 23:55 | Analyst | Found two bugs in its own acceptance tests | Fixed in `73e431d` |
| Nov 14 00:01 | Reviewer | **REJECT `92ab620`, three findings, all owned by the Implementer.** F1 (blocking): when extracts are refused, the build never used search bodies, so supported fields stayed unknown. F2: under a permanent rate limit a build overran the spec's 10-second bound. F3: nothing enforced the 300-second cap on live builds (found by reading the code) | `da61100`, `1d3ccf7`, `904e1fd` |
| Nov 17 18:55 | Reviewer | **REJECT `904e1fd`.** F1–F3 fixed; F4 (blocking): when extracts and research were both refused, budget held back for research went unspent and supported fields stayed unknown | `d7db00b` |
| Nov 21 18:47–18:49 | UX Reviewer, Reviewer | Both **ACCEPT `d7db00b`**; Reviewer: stage 1 suite 122/122 in normal and isolated mode | Stage 1 final |

The shipped checks passed from the first revision on; every finding above came
from the specification, not from a failing shipped test. The Analyst's ledger
for stage 1 has 157 rows and 36 rulings.

### Stage 2

| When (UTC) | Who | What | Fix |
|---|---|---|---|
| Nov 22 | Analyst | **REJECT tree `a0874386`**: its acceptance suite (394/406) found 8 rows where pages cited by research weren't read | Implementer and Reviewer traced it to the mock web, not the builder (mock research returns only the first entry per field). The Analyst withdrew it with a ruling (RUL-S2-19) and fixed its corpus. The Implementer still changed the read order so cited and company pages are read first within the 80-unit budget (`c02769e`) |
| Nov 23 16:52 | Reviewer | **CONDITIONAL ACCEPT `c02769e`**: shipped checks pass in normal and isolated mode, code review clean; condition: the ledger must close | Analyst closed the ledger |
| Nov 23 17:27–17:37 | Coordinator → Reviewer, UX Reviewer | Refused to close with 14 review-only ledger rows open; asked for evidence or a ruling for each | Evidence posted for every row; stage 2 closed 17:38 |

Stage 2 final: source `c02769e`, ledger 261 rows (257 passing, 4 ruled, 0
open), Analyst suite 406/406 including 61 browser tests at 375 and 1280 px and
an upgrade from the real stage-1 image; UX Reviewer 58/58 + 28/28 at phone and
desktop sizes.

### Stage 3

| When (UTC) | Who | What | Fix |
|---|---|---|---|
| Nov 24 | Reviewer | Couldn't pin a revision: the Analyst had uncommitted edits in the repository | Analyst committed them (`fd5928c`) |
| Nov 24 05:40–06:39 | Coordinator, Analyst | RUL-S3-04 (does a page that wasn't rendered still make a page version?): the Coordinator ruled yes, then withdrew it when the Analyst showed no spec sentence or test requires it. The Implementer followed each turn: commit, revert, reapply, revert (`aaa1917`…`4ad2027`) | Code back to `55d8c54`; the history shows the churn honestly |
| Nov 24 | Coordinator | Refused the UX Reviewer's closure of R-UX-01..06 from API probing alone; asked for browser screenshots | Screens at 375 and 1280 px; rows closed |

Stage 3 final: app code `4ad2027` (same as `55d8c54`), ledger 319 rows (315
passing, 4 ruled, 0 open), Analyst suite 536 tests including SIGKILL restart,
concurrency, and upgrades from stage-1, -2 and -3 exports; Reviewer ACCEPT
from a clean clone. Left open, in the Coordinator's report: a stage-2 export
carries no build list, so an imported stage-2 dossier has one build
(RUL-S3-15); durability under load and throughput weren't measured.

## Measured cost and time

Cost is Band's list-price estimate (`band usage`), not a bill.

| Seat | Stage 1 | Stage 2 | Stage 3 |
|---|---|---|---|
| Implementer | $16.42 | $10.11 | $3.78 |
| Analyst | $13.11 | $9.36 | $10.15 |
| Reviewer | $10.87 | $1.73 | $2.10 |
| Coordinator | $4.58 | $1.46 | $2.01 |
| UX Reviewer | $2.04 | $0.12 | $0.33 |
| **Room total** | **$47.02** (89.2M tokens) | **$22.79** (92.0M tokens) | **$18.38** (81.2M tokens) |

Each stage ran in its own room (`room-1.json`, `room-2.json`, `room-3.json`). Stage 2 was
about half the cost of stage 1 on more tokens: all seats on Sonnet or Haiku,
and a fresh room per stage.

Active time, from the room log: about 46 minutes on Nov 13 (23:24–00:10 UTC),
13 minutes on Nov 17, and 21 minutes on Nov 21, so about **80 minutes** of
work. The room spans Nov 13–21 because each window ended at the Claude Code
5-hour usage limit and the run was stopped and resumed (see below).

Stage 2, wall clock Nov 22 18:34 to Nov 23 17:38 UTC: 40 minutes of work by
all seats on Nov 22 until the usage limit; intermittent Implementer work
overnight (03:42–09:48) while the rest of the band was blocked (see below);
then 50 minutes on Nov 23 (16:48–17:38) to acceptance and close.

Stage 3, wall clock Nov 24 01:50 to 18:42 UTC: about 8 hours of continuous
work (01:50–09:38) through the ledger, tests and reviews; then a stall with
the last two verdicts finished but undelivered (see below), resolved after
the human nudge at 17:12.

## What we tried, and what it cost us

- **Three Opus seats (draft v1)** did the Nov 13 and Nov 17 work: Analyst,
  Implementer and Reviewer on `claude-opus-5-5` at high effort. They were 85%
  of the spend and hit the 5-hour limit in about 45 minutes. Draft v2 (this
  repository's mandates) moved UX Reviewer to Haiku, and the rest (Analyst, Reviewer, Implementer, Coordinator) to Sonnet, lowered effort for
  coordination and review, and added the working-economically rules; the Nov
  21 work ran on v2.
- **Context builds up per room.** Each seat keeps one Claude Code session per
  room, so a resumed room re-reads everything that seat has done there. A
  fresh room per run is much cheaper than resuming.
- **Human input in this run, disclosed:** the dispatch; stopping all agents
  (Nov 17) and resuming them (Nov 21) around the usage limit; one message
  asking the Analyst to move its ledger from the repository root into
  `stage-1/requirements/`, as its mandate says (done in `aa17080`). This is a
  development run, not a clean hands-off run.
- **A mandate change between stages, disclosed.** The Analyst's ledger landed
  at the repository root because the Coordinator's first handoff told it to
  ("Put them in …/stage-1-analysis/ (NOT inside stage-1/ …)"), overriding the
  Analyst's own mandate. The Coordinator mandate didn't say where the
  Analyst's files belong, so the Coordinator improvised. After stage 1 we added
  one rule to `mandates/coordinator.md` (under "Increments"): the Analyst's
  ledger, rulings and acceptance tests live under `requirements/` inside the
  increment's folder and are carried forward with it. Stages 2 onward ran with
  that rule; no other mandate changed.
- **Human input in stage 2, disclosed:** the dispatch; one message to the
  Coordinator after the usage limit reset (Nov 23 03:42 UTC: "The usage
  limit has reset. Resume from where the band stopped."); a restart of all
  five seats (16:48 UTC) after a settings fix. No other message.
- **A personal setting blocked the band (stage 2).** The seats ran with the
  owner's Claude setup, which carried a personal rule, "don't commit". Claude
  Code's auto-mode permission check enforced it: every seat commit was
  denied, and so was the CLI fallback for posting to the room. The
  Implementer's fix report stayed in a file the room never saw, and the
  band waited overnight. We scoped the rule to the owner's own sessions and
  restarted the seats; they resumed by themselves and committed within a
  minute. The mandates didn't change. Lesson: a factory seat must not
  inherit its owner's personal instructions.
- **Human input in stage 3, disclosed:** the dispatch; one message to the
  Coordinator (Nov 24 17:12 UTC: "Resume from where the band stopped.");
  a restart of the UX Reviewer (18:41 UTC) after an API "529 Overloaded"
  error. No other message.
- **Finished work that never reached the room (stages 2 and 3), and a
  mandate change before stage 4, disclosed.** A Band Desktop seat can post
  only by replying, once, to the message it is handling; there is no tool to
  start a new message, and the `band send` CLI fallback is denied by the
  permission check. In stage 3 the Reviewer (ACCEPT) and the UX Reviewer
  (screens) had acknowledged their handoffs first, then finished hours
  later with nowhere to post; the Coordinator waited. The Reviewer also asked
  the human, in its own session, to relay its verdict; nobody did. After
  stage 3 we added one section, "Replying in the room", to all five mandates:
  do the work, then reply once with the result; never acknowledge first and
  report later; never ask the human to relay. The Coordinator, which starts
  handoffs as new messages (that works for it), gets the other side: ask
  for the result as the reply, and treat an acknowledgement without a result
  as no report. Stage 4 runs with it.
- **From the toy practice run:** a default agent Band adds to new rooms stays
  in the room log and needs a mandate (we now check the participant list);
  commits defaulted to the human's git identity until each seat committed
  under its own; typed mentions don't route, the mention picker does.

## Live result

`dossier-runway.com.json` is the highest stage built against the live web.
From stage 1: state
`ready`, all six fields known. Values are only as good as the evidence the
service retrieved within its budget; for example the legal name came back as
an operating entity's name, and total funding looks low compared with public
reports. That is a research-economy and selection question for later stages.
