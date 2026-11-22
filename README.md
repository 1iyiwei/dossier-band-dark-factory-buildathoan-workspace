# BAND Dark Factory Buildathon: Dossier

- **Team:** [Li-Yi Wei](https://github.com/1iyiwei) and Florence Chao
- **Track:** `dossier`
- **Stage reached:** 1 (`stage-1/` claims stage 1 on the shipped checks, in
  normal and isolated mode)

A five-seat factory in Band Desktop (Coordinator, Analyst, Implementer,
Reviewer, UX Reviewer) built the stage-1 service from the specification. All
code under `stage-1/` came out of the room; we dispatched the work and
did not write it.

## How to read this repository

| Path | What it is | Written by |
|---|---|---|
| [`FACTORY.md`](FACTORY.md) | The factory: seats, design choices, how to stand it up, what it caught, measured cost and time, what failed | Human |
| [`mandates/`](mandates/) | One generic mandate per seat, each naming its harness, model and effort | Human |
| [`room.json`](room.json) | The full room, downloaded unchanged from the Band console | Band |
| [`stage-1/`](stage-1/) | The service: source, `Dockerfile`, [`RUN.md`](stage-1/RUN.md) | The band |
| [`stage-1/requirements/`](stage-1/requirements/) | The Analyst's requirement ledger, rulings and black-box acceptance tests | The band (Analyst) |
| [`dossier-runway.com.json`](dossier-runway.com.json) | `GET /dossiers/runway.com` from `stage-1/`, built against the live web | Generated, unedited |

The git history shows which seat made each commit: every seat commits under
its own name (`Analyst`, `Implementer`, …). Commits by the human only add the
files marked "Human" above, plus `room.json` and the live result.

## Running it

Follow [`stage-1/RUN.md`](stage-1/RUN.md): one command builds and starts the
service in a single container.
