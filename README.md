# BAND Dark Factory Buildathon: Dossier

- **Team:** [Li-Yi Wei](https://github.com/1iyiwei) and Florence Chao
- **Track:** `dossier`
- **Stage reached:** 4 (`stage-4/` claims stage 4 on the shipped checks, in
  normal and isolated mode; `--all --mode isolated` scores stages 1–4)

A five-seat factory in Band Desktop (Coordinator, Analyst, Implementer,
Reviewer, UX Reviewer) built the service from the specification, one stage
and one room at a time. All code under `stage-N/` came out of the rooms; we dispatched the work and
did not write it.

## How to read this repository

| Path | What it is | Written by |
|---|---|---|
| [`FACTORY.md`](FACTORY.md) | The factory: seats, design choices, how to stand it up, what it caught, measured cost and time, what failed | Human |
| [`mandates/`](mandates/) | One generic mandate per seat, each naming its harness, model and effort | Human |
| [`room-1.json`](room-1.json) … [`room-4.json`](room-4.json) | One room per stage, each downloaded unchanged from the Band console | Band |
| [`stage-1/`](stage-1/) … [`stage-4/`](stage-4/) | The service at each stage: source, `Dockerfile`, `RUN.md`. A stage folder is final once accepted; the next stage starts as a copy | The band |
| `stage-N/requirements/` | The Analyst's requirement ledger, rulings and black-box acceptance tests for that stage | The band (Analyst) |
| [`dossier-runway.com.json`](dossier-runway.com.json) | `GET /dossiers/runway.com` from `stage-4/`, built against the live web | Generated, unedited |

The git history shows which seat made each commit: every seat commits under
its own name (`Analyst`, `Implementer`, …). Commits by the human only add the
files marked "Human" above, plus the room files and the live result.

## Running it

Follow [`stage-4/RUN.md`](stage-4/RUN.md): one command builds and starts the
service, with its browser UI, in a single container.
