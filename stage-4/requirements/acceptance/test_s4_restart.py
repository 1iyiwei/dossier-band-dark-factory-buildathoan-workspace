"""Stage 4: a container stopped abruptly (SIGKILL, then started again) while builds run. Needs
SVC_CONTAINER (`up.sh` exports it). After the restart everything else answers as before and each
build that was running
 - does not stay `building`: `ready` or `failed` within 10 s of /health first answering 200 (the
   mock answers at once after the restart); a `failed` one leaves the fields as they were;
 - is one build across the restart: all its calls together bill at most 80 units, a batch's builds
   together at most `budget_units`;
 - has every unit the mock billed counted in its dossier's `spent_units` and the batch's.
The stop is timed after the first billed call, with every provider call held for two seconds, so a
call is in flight at the stop."""
import os
import time

import pytest

import oracle
import s3lib
import s4lib
import timeline as tl
from lib import T0, USERS, Api, assert_dossier_shape, assert_error, new_key, parse_ts, total_cost
from s4lib import billed, kill_clear_start, poll_until_terminal, wait_batch, wait_billed

pytestmark = [pytest.mark.corpus,
              pytest.mark.skipif(not os.environ.get("SVC_CONTAINER"),
                                 reason="SVC_CONTAINER (docker name of the service) not set")]
BASE = os.environ.get("BASE_URL", "http://localhost:18001").rstrip("/")
QB = "quillon-bio.test"
TAL = "talloway-systems.test"
MER = "meridel-foods.test"
WRE = "wrenfield-audio.test"
SAB = "sablewood-logistics.test"
FEN = "fenwick-orchards.test"
LIMIT = 10.5            # 10 s from /health + 0.5 s of polling slack


def probe(api, tok, doms):
    out = {"feed": s3lib.all_changes(api, tok)}
    for d in doms:
        out[d] = dict(cur=api.get(tok, d).json(), hist=s3lib.history(api, tok, d).json(),
                      asof=s3lib.as_of(api, tok, d, "2027-01-01T00:00:00+00:00").json())
    return out


def test_R4_RST_01_a_build_running_at_the_stop_is_not_left_building(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    api.build(tok, TAL)                                         # a finished dossier that must not change
    before = probe(api, tok, [TAL])
    list_before = api.list(tok).json()
    mock.reset(0)
    s4lib.hold_providers(mock, 2.0)
    api.clock("2026-03-02T09:00:00+00:00")
    r = api.create(tok, QB)
    assert r.status_code == 202
    wait_billed(mock, 1)
    t_health = kill_clear_start(mock, BASE)
    secs, b = poll_until_terminal(api, tok, QB, LIMIT)
    assert time.monotonic() - t_health <= LIMIT, f"still building {time.monotonic() - t_health:.1f}s after /health"
    assert b["state"] in ("ready", "failed")
    assert_dossier_shape(b, QB)
    log = mock.log()
    if b["state"] == "failed":
        assert all(fv["value"] is None for fv in b["fields"].values()) and b["researched_at"] is None
        assert s3lib.history(api, tok, QB).json()["fields"] == {f: [] for f in oracle.ALL_FIELDS}
    else:
        probs = s4lib.oracle_problems(b, QB, log, 0, "2026-03-02T09:00:00+00:00")
        assert not probs, "\n".join(probs)
    assert billed(log) <= 80 and billed(log) <= b["spent_units"] <= 80, (billed(log), b["spent_units"])
    # everything else is answered as before the stop
    after = probe(api, tok, [TAL])
    assert after == before
    assert [d for d in api.list(tok).json()["dossiers"] if d["domain"] == TAL] == \
        [d for d in list_before["dossiers"] if d["domain"] == TAL]
    for u in USERS:
        assert api.login(u["email"], u["password"]).status_code == 200


def test_R4_RST_02_one_build_across_the_restart_spends_at_most_80(api, mock):
    """The biggest corpus company: a restart that began a fresh 80-unit budget would overspend."""
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    solo = api.build(tok, FEN)
    assert solo["state"] == "ready"
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    s4lib.hold_providers(mock, 2.0)
    assert api.create(tok, FEN).status_code == 202
    wait_billed(mock, 2, timeout=40)                           # two billed calls before the stop
    kill_clear_start(mock, BASE)
    secs, b = poll_until_terminal(api, tok, FEN, LIMIT)
    log = mock.log()
    assert billed(log) <= 80, f"calls before and after the stop bill {billed(log)} units"
    assert billed(log) <= b["spent_units"] <= 80, (billed(log), b["spent_units"])
    assert b["state"] in ("ready", "failed")
    if b["state"] == "ready":
        assert not s4lib.partial_build_problems(b, FEN, log)


def test_R4_RST_03_a_batch_running_at_the_stop(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    doms = [TAL, MER, WRE, SAB]
    budget = 110
    s4lib.hold_providers(mock, 2.0)
    key = new_key("b")
    r = s4lib.batch_create(api, tok, None, None, key=key, body={"domains": doms, "budget_units": budget})
    assert r.status_code == 202
    first = r.json()
    wait_billed(mock, 1)
    t_health = kill_clear_start(mock, BASE)
    # the batch ends: all its builds end within 10 s of /health (a little slack for the batch's own state)
    done = wait_batch(api, tok, first["batch_id"], timeout=LIMIT + 2.0)
    assert time.monotonic() - t_health <= LIMIT + 2.0
    s4lib.assert_batch_shape(done, doms, budget)
    assert done["state"] == "done"
    log = mock.log()
    spent = s4lib.dossier_spent(api, tok, doms)
    assert billed(log) <= budget, f"the batch's builds bill {billed(log)} units, budget {budget}"
    assert done["spent_units"] >= billed(log) and all(v <= 80 for v in spent.values())
    assert sum(spent.values()) >= billed(log)
    for d in doms:
        b = api.get(tok, d).json()
        assert b["state"] in ("ready", "failed"), (d, b["state"])
        assert_dossier_shape(b, d)
        if b["state"] == "failed":
            assert b["researched_at"] is None and all(fv["value"] is None for fv in b["fields"].values())
        else:
            assert not s4lib.partial_build_problems(b, d, log), d
    # the replay of the POST that created the batch answers with the original response
    again = s4lib.batch_create(api, tok, None, None, key=key,
                               body={"domains": doms, "budget_units": budget})
    assert again.status_code == 200 and again.json() == first
    assert s4lib.batch_get(api, tok, first["batch_id"]).json() == done


def test_R4_RST_04_refresh_after_the_restart_starts_a_new_build(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    s4lib.hold_providers(mock, 2.0)
    assert api.create(tok, QB).status_code == 202
    wait_billed(mock, 1)
    kill_clear_start(mock, BASE)
    poll_until_terminal(api, tok, QB, LIMIT)
    mock.reset(0)
    api.clock("2026-03-05T09:00:00+00:00")
    r = api.refresh(tok, QB)
    assert r.status_code == 202 and r.json()["state"] == "building"
    b = api.wait(tok, QB, timeout=40)
    assert b["state"] == "ready"
    probs = s4lib.oracle_problems(b, QB, mock.log(), 0, "2026-03-05T09:00:00+00:00")
    # a first-ready build may be `initial` or, after a ready interrupted build, `change`: judged by shape only
    probs = [p for p in probs if "learned_at" not in p and "corroborated_since" not in p]
    assert not probs, probs
    assert 0 < b["spent_units"] <= 160


def test_R4_RST_05_an_interrupted_refresh_keeps_the_last_ready_fields_when_it_fails(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    recs = s3lib.run(api, mock, tok, QB, [{"epoch": 0, "clock": T0}])
    base = recs[0].snap
    hist0 = s3lib.history(api, tok, QB).json()
    feed0 = s3lib.all_changes(api, tok)
    mock.reset(0)
    mock.epoch(3)
    s4lib.hold_providers(mock, 2.0)
    api.clock("2026-03-06T09:00:00+00:00")
    assert api.refresh(tok, QB).status_code == 202
    wait_billed(mock, 1)
    kill_clear_start(mock, BASE)
    secs, b = poll_until_terminal(api, tok, QB, LIMIT)
    assert_dossier_shape(b, QB)
    if b["state"] == "failed":
        assert b["fields"] == base["fields"] and b["researched_at"] == base["researched_at"]
        assert s3lib.history(api, tok, QB).json() == hist0
        assert s3lib.all_changes(api, tok) == feed0
    else:
        rec1 = s3lib.Rec("2026-03-06T09:00:00+00:00", 3, True, b, mock.log())
        builds = s3lib.to_builds([recs[0], rec1], QB)
        sim = tl.simulate(builds, QB)
        probs = s3lib.snapshot_problems(b, QB, [recs[0], rec1], 1, builds, sim, check_learned=False)
        assert not probs, "\n".join(probs)
        h = s3lib.history(api, tok, QB).json()
        assert not s3lib.history_problems(h, QB, [recs[0], rec1], builds, sim)
        assert not s3lib.feed_problems([e for e in s3lib.all_changes(api, tok) if e["domain"] == QB], QB, sim)
    assert billed(mock.log()) <= 80


def test_R4_RST_06_completed_batches_and_their_keys_survive_the_stop(api, mock):
    api.reset()
    mock.reset(0)
    t0, t1 = api.token(0), api.token(1)
    key = new_key("b")
    body = {"domains": [TAL, MER], "budget_units": 200}
    r = s4lib.batch_create(api, t0, None, None, key=key, body=body)
    assert r.status_code == 202
    done = wait_batch(api, t0, r.json()["batch_id"], timeout=90)
    assert done["state"] == "done"
    s3lib.kill_and_restart()
    assert s4lib.batch_get(api, t0, r.json()["batch_id"]).json() == done
    assert_error(s4lib.batch_get(api, t1, r.json()["batch_id"]), 404, "not_found")
    again = s4lib.batch_create(api, t0, None, None, key=key, body=body)
    assert again.status_code == 200 and again.json() == r.json()
    assert_error(s4lib.batch_create(api, t0, None, None, key=key,
                                    body={"domains": [TAL], "budget_units": 200}), 409, "idempotency_key_reuse")
    n = len(mock.log())
    r2 = s4lib.batch_create(api, t0, [WRE], 100)             # new batches work and get new ids
    assert r2.status_code == 202 and r2.json()["batch_id"] != r.json()["batch_id"]
    wait_batch(api, t0, r2.json()["batch_id"], timeout=60)
    assert len(mock.log()) > n
