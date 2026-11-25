"""Stage 4 (API): `POST /batches` and `GET /batches/{id}`: validation, the shape, states, ownership,
the shared budget, idempotency (the third idempotent write path), concurrency, no provider call on
reads and replays. Corpus companies of earlier stages are reused (their builds are known to cost
well under 80 units)."""
import concurrent.futures as cf
import time

import pytest

import oracle
import s4lib
from lib import Api, assert_dossier_shape, assert_error, new_key, parse_ts, total_cost
from s4lib import batch_create, batch_get, wait_batch

pytestmark = pytest.mark.corpus

TAL = "talloway-systems.test"
SAB = "sablewood-logistics.test"
MER = "meridel-foods.test"
WRE = "wrenfield-audio.test"
FEN = "fenwick-orchards.test"
HOLD = [("nimble", ["search", "extract", "research"], "delay"),
        ("tavily", ["search", "extract", "research"], "delay")]


def slow(mock, seconds=1.0, on=True):
    for p, ms, _ in HOLD:
        if on:
            mock.fault(p, ms, "delay", seconds=seconds)
        else:
            mock.fault(p, ms, "none")


def n_calls_for(log, domain):
    """Calls that research the company: a search or research run whose query names it. (An extract
    of one of its URLs is not research of that dossier: another company's search may return it.)"""
    name = oracle.company_name(domain).lower()
    return [e for e in log if e.get("method") in ("search", "research")
            and (domain in (e.get("query") or "") or name in (e.get("query") or "").lower())]


# ------------------------------------------------------------------ validation (R4-BAT-01..03)
BAD_BODIES = [
    ("domains missing", {"budget_units": 100}),
    ("domains empty", {"domains": [], "budget_units": 100}),
    ("51 domains", {"domains": [f"co-{i:02d}.test" for i in range(51)], "budget_units": 100}),
    ("invalid entry (scheme)", {"domains": ["https://acme.test"], "budget_units": 100}),
    ("invalid entry (one label)", {"domains": ["acme-robotics.test", "localhost"], "budget_units": 100}),
    ("invalid entry (empty)", {"domains": ["acme.test", ""], "budget_units": 100}),
    ("invalid entry (path)", {"domains": ["acme.test/about"], "budget_units": 100}),
    ("duplicate after normalisation", {"domains": ["Acme.test", "www.acme.test."], "budget_units": 100}),
    ("duplicate exact", {"domains": ["acme.test", "acme.test"], "budget_units": 100}),
    ("budget missing", {"domains": ["acme.test"]}),
    ("budget 0", {"domains": ["acme.test"], "budget_units": 0}),
    ("budget negative", {"domains": ["acme.test"], "budget_units": -1}),
    ("budget 100001", {"domains": ["acme.test"], "budget_units": 100001}),
    ("budget string", {"domains": ["acme.test"], "budget_units": "200"}),
    ("budget true", {"domains": ["acme.test"], "budget_units": True}),
    ("budget false", {"domains": ["acme.test"], "budget_units": False}),
    ("budget 1.5", {"domains": ["acme.test"], "budget_units": 1.5}),
    ("budget null", {"domains": ["acme.test"], "budget_units": None}),
    ("budget list", {"domains": ["acme.test"], "budget_units": [5]}),
    ("budget object", {"domains": ["acme.test"], "budget_units": {"n": 5}}),
]


@pytest.mark.parametrize("name,body", BAD_BODIES, ids=[n for n, _ in BAD_BODIES])
def test_R4_BAT_01_validation_failed(fresh, name, body):
    """R4-BAT-01..03: 422 `validation_failed`; a budget of the wrong JSON type is 422, not 400."""
    api, mock = fresh
    tok = api.token(0)
    r = batch_create(api, tok, None, None, body=body)
    assert_error(r, 422, "validation_failed")
    assert mock.log() == []


def test_R4_BAT_02_domains_of_the_wrong_type_are_malformed(fresh):
    """RUL-S4-09: §5 reserves 400 for a field of the wrong JSON type; only `budget_units` is carved out."""
    api, mock = fresh
    tok = api.token(0)
    for bad in ("acme.test", 5, {"a": "b"}, None):
        r = batch_create(api, tok, None, None, body={"domains": bad, "budget_units": 100})
        assert r.status_code in ((400, 422) if bad is None else (400,)), (bad, r.status_code)
        if r.status_code == 400:
            assert r.json()["error"]["code"] == "malformed_request"
    r = batch_create(api, tok, None, None, body={"domains": [5, 6], "budget_units": 100})
    assert r.status_code in (400, 422)
    r = api.req("POST", "/batches", token=tok, key=new_key("b"), content=b"{not json")
    assert_error(r, 400, "malformed_request")
    r = api.req("POST", "/batches", token=tok, key=new_key("b"), content=b"[1,2]")
    assert_error(r, 400, "malformed_request")
    assert mock.log() == []


def test_R4_BAT_03_boundaries_are_valid(fresh):
    """1 and 100000 are valid budgets, 50 entries are valid; entries are normalised."""
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, TAL)
    n0 = len(mock.log())
    for budget in (1, 100000):
        r = batch_create(api, tok, [" WWW.Talloway-Systems.TEST. "], budget)
        assert r.status_code == 202, r.text
        b = r.json()
        s4lib.assert_batch_shape(b, [TAL], budget)
        assert wait_batch(api, tok, b["batch_id"])["spent_units"] == 0
    assert len(mock.log()) == n0                                  # an existing dossier costs nothing


def test_R4_BAT_04_auth_and_idempotency_key_rules(fresh):
    api, mock = fresh
    tok = api.token(0)
    body = {"domains": [TAL], "budget_units": 50}
    assert_error(api.req("POST", "/batches", json=body, key="k1"), 401, "unauthenticated")
    assert_error(api.req("POST", "/batches", json=body), 401, "unauthenticated")           # before the key check
    assert_error(api.req("POST", "/batches", token="nope", json=body, key="k1"), 401, "unauthenticated")
    assert_error(api.req("POST", "/batches", token=tok, json=body), 400, "missing_idempotency_key")
    assert_error(api.req("POST", "/batches", token=tok, json=body, headers={"Idempotency-Key": ""}),
                 400, "missing_idempotency_key")
    assert_error(batch_create(api, tok, None, None, key="k" * 256, body=body), 422, "validation_failed")
    assert batch_create(api, tok, None, None, key="k" * 255, body=body).status_code == 202
    assert_error(api.req("GET", "/batches/b_1"), 401, "unauthenticated")
    assert_error(api.req("GET", "/batches/b_1", token="nope"), 401, "unauthenticated")


# ------------------------------------------------------------------ shape, states, spending (R4-BAT-05..)
def test_R4_BAT_05_shape_states_and_spending_of_a_batch(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, TAL)                                          # an existing, ready dossier
    tal_before = api.get(tok, TAL).json()
    mock.reset(0)
    slow(mock, 1.0)
    n0 = len(mock.log())
    r = batch_create(api, tok, [" Meridel-Foods.TEST.", "www.talloway-systems.test", WRE], 500)
    assert r.status_code == 202, r.text
    b = r.json()
    s4lib.assert_batch_shape(b, [MER, TAL, WRE], 500)
    assert b["state"] == "running" and b["spent_units"] == 0
    assert [d["state"] for d in b["dossiers"]] == ["building", "ready", "building"]
    g = batch_get(api, tok, b["batch_id"])
    assert g.status_code == 200 and g.json()["batch_id"] == b["batch_id"]
    done = wait_batch(api, tok, b["batch_id"], timeout=120)
    slow(mock, on=False)
    s4lib.assert_batch_shape(done, [MER, TAL, WRE], 500)
    assert done["state"] == "done"
    assert [d["state"] for d in done["dossiers"]] == ["ready", "ready", "ready"]
    log = mock.log()[n0:]
    assert not n_calls_for(log, TAL), "the batch researched a domain that already had a dossier"
    spent = s4lib.dossier_spent(api, tok, [MER, WRE])
    assert all(0 < v <= 80 for v in spent.values()), spent
    assert done["spent_units"] == sum(spent.values()) == total_cost(log)
    for d in (MER, WRE):
        assert_dossier_shape(api.get(tok, d).json(), d)
    assert api.get(tok, TAL).json() == tal_before                # untouched: same fields, spend, time


def test_R4_BAT_06_a_batch_of_existing_dossiers_makes_no_call(fresh):
    api, mock = fresh
    tok = api.token(0)
    for d in (TAL, MER):
        api.build(tok, d)
    n0 = len(mock.log())
    before = {d: api.get(tok, d).json() for d in (TAL, MER)}
    r = batch_create(api, tok, [TAL, MER], 100)
    assert r.status_code == 202
    assert [d["state"] for d in r.json()["dossiers"]] == ["ready", "ready"]
    done = wait_batch(api, tok, r.json()["batch_id"])
    assert done["state"] == "done" and done["spent_units"] == 0
    time.sleep(1.0)
    assert len(mock.log()) == n0
    assert {d: api.get(tok, d).json() for d in (TAL, MER)} == before


def test_R4_BAT_07_a_domain_already_building_is_not_researched_by_the_batch(fresh):
    api, mock = fresh
    tok = api.token(0)
    slow(mock, 1.0)
    assert api.create(tok, TAL).status_code == 202               # building, started by this request
    r = batch_create(api, tok, [TAL], 200)
    assert r.status_code == 202
    assert r.json()["dossiers"] == [{"domain": TAL, "state": "building"}]
    done = wait_batch(api, tok, r.json()["batch_id"], timeout=90)
    api.wait(tok, TAL, timeout=90)
    slow(mock, on=False)
    assert done["spent_units"] == 0                              # the build is not the batch's
    from lib import domain_queries
    assert len(domain_queries(mock.log(), TAL)) == 1             # one build only


# ------------------------------------------------------------------ the shared budget
def standalone_costs(api, mock, tok, domains):
    out = {}
    for d in domains:
        api.reset()
        mock.reset(0)
        tok = api.token(0)
        b = api.build(tok, d)
        assert b["state"] == "ready"
        out[d] = (b["spent_units"], {f: b["fields"][f]["value"] for f in oracle.ALL_FIELDS})
    return out


def test_R4_BAT_08_the_budget_is_never_exceeded_and_a_big_one_changes_nothing(fresh):
    api, mock = fresh
    doms = [TAL, SAB, FEN]
    costs = standalone_costs(api, mock, None, doms)
    total = sum(c for c, _ in costs.values())
    assert total > 20, costs
    for budget in (total + 200, total // 2, max(1, min(c for c, _ in costs.values()) // 2), 1):
        api.reset()
        mock.reset(0)
        tok = api.token(0)
        r = batch_create(api, tok, doms, budget)
        assert r.status_code == 202, r.text
        done = wait_batch(api, tok, r.json()["batch_id"], timeout=150)
        s4lib.assert_batch_shape(done, doms, budget)
        assert done["state"] == "done"
        log = mock.log()
        assert total_cost(log) <= budget, (budget, total_cost(log))
        spent = s4lib.dossier_spent(api, tok, doms)
        assert done["spent_units"] == sum(spent.values()) == total_cost(log), (budget, done, spent)
        assert all(v <= 80 for v in spent.values())
        n = len(log)
        time.sleep(1.5)
        assert len(mock.log()) == n, "the batch kept calling providers after it finished"
        for d in doms:
            b = api.get(tok, d).json()
            assert b["state"] in ("ready", "failed"), (budget, d, b["state"])
            assert_dossier_shape(b, d)
            if b["state"] == "ready":
                probs = s4lib.partial_build_problems(b, d, log) if budget < total else []
                assert not probs, (budget, d, probs)
            if budget >= total + 200:
                assert b["state"] == "ready"
                assert {f: b["fields"][f]["value"] for f in oracle.ALL_FIELDS} == costs[d][1], d


def test_R4_BAT_09_a_budget_of_one_stops_after_at_most_one_unit(fresh):
    api, mock = fresh
    tok = api.token(0)
    r = batch_create(api, tok, [TAL, MER], 1)
    done = wait_batch(api, tok, r.json()["batch_id"], timeout=60)
    assert done["state"] == "done" and done["spent_units"] <= 1
    assert total_cost(mock.log()) <= 1
    for d in (TAL, MER):
        b = api.get(tok, d).json()
        assert b["state"] in ("ready", "failed")
        if b["state"] == "ready":
            assert not s4lib.partial_build_problems(b, d, mock.log())


def test_R4_BAT_10_each_build_in_a_batch_spends_at_most_80(fresh):
    api, mock = fresh
    tok = api.token(0)
    r = batch_create(api, tok, [FEN, SAB, TAL], 100000)
    done = wait_batch(api, tok, r.json()["batch_id"], timeout=150)
    spent = s4lib.dossier_spent(api, tok, [FEN, SAB, TAL])
    assert all(v <= 80 for v in spent.values()), spent
    assert done["spent_units"] == sum(spent.values()) == total_cost(mock.log())


# ------------------------------------------------------------------ ownership and reads
def test_R4_BAT_11_a_batch_belongs_to_its_creator_and_reads_make_no_call(fresh):
    api, mock = fresh
    t0, t1 = api.token(0), api.token(1)
    r = batch_create(api, t0, [TAL], 100)
    bid = r.json()["batch_id"]
    done = wait_batch(api, t0, bid)
    n = len(mock.log())
    assert_error(batch_get(api, t1, bid), 404, "not_found")
    assert_error(batch_get(api, t0, "b_does_not_exist"), 404, "not_found")
    assert_error(api.req("GET", f"/batches/{bid}"), 401, "unauthenticated")
    assert batch_get(api, t0, bid).json() == done
    api.get(t0, TAL)
    api.list(t0)
    assert len(mock.log()) == n


# ------------------------------------------------------------------ idempotency (R4-BAT-12..)
def test_R4_BAT_12_replay_returns_the_original_response_and_starts_nothing(fresh):
    api, mock = fresh
    tok = api.token(0)
    slow(mock, 0.5)
    key = new_key("b")
    body = {"domains": [TAL, MER], "budget_units": 300}
    first = batch_create(api, tok, None, None, key=key, body=body)
    assert first.status_code == 202
    done = wait_batch(api, tok, first.json()["batch_id"], timeout=90)
    slow(mock, on=False)
    n = len(mock.log())
    again = batch_create(api, tok, None, None, key=key, body=dict(body, unrelated="x"))   # unknown fields ignored
    assert again.status_code == 200 and again.json() == first.json()                     # the ORIGINAL response
    reordered = batch_create(api, tok, None, None, key=key, body={"budget_units": 300, "domains": [TAL, MER]})
    assert reordered.status_code == 200 and reordered.json() == first.json()
    assert batch_get(api, tok, first.json()["batch_id"]).json() == done
    time.sleep(0.5)
    assert len(mock.log()) == n                                    # no build, no provider call


def test_R4_BAT_13_same_key_different_body_is_409_and_resolved_before_validation(fresh):
    api, mock = fresh
    tok = api.token(0)
    key = new_key("b")
    ok = batch_create(api, tok, None, None, key=key, body={"domains": [TAL, MER], "budget_units": 300})
    assert ok.status_code == 202
    for body in ({"domains": [TAL, MER], "budget_units": 301},
                 {"domains": [MER, TAL], "budget_units": 300},
                 {"domains": [TAL], "budget_units": 300},
                 {"domains": ["Talloway-Systems.test", MER], "budget_units": 300},      # case differs: another body
                 {"domains": [], "budget_units": 300},                                # invalid but the key is claimed
                 {"domains": [TAL, MER], "budget_units": "x"}):
        assert_error(batch_create(api, tok, None, None, key=key, body=body), 409, "idempotency_key_reuse")
    wait_batch(api, tok, ok.json()["batch_id"])


def test_R4_BAT_14_a_key_used_for_a_4xx_is_reusable_and_keys_are_per_user_and_per_path(fresh):
    api, mock = fresh
    t0, t1 = api.token(0), api.token(1)
    key = new_key("b")
    assert_error(batch_create(api, t0, None, None, key=key, body={"domains": [], "budget_units": 5}),
                 422, "validation_failed")
    first = batch_create(api, t0, None, None, key=key, body={"domains": [TAL], "budget_units": 100})
    assert first.status_code == 202                                  # the failed request did not claim the key
    other = batch_create(api, t1, None, None, key=key, body={"domains": [MER], "budget_units": 100})
    assert other.status_code == 202 and other.json()["batch_id"] != first.json()["batch_id"]
    # the same key on another path is another request
    d = api.req("POST", "/dossiers", token=t0, key=key, json={"domain": WRE})
    assert d.status_code == 202
    assert api.req("POST", f"/dossiers/{TAL}/refresh", token=t0, key=key).status_code in (202,)
    for u, tk in ((first, t0), (other, t1)):
        wait_batch(api, tk, u.json()["batch_id"])
    api.wait(t0, WRE)


def test_R4_BAT_15_concurrent_identical_requests_make_one_batch(fresh):
    api, mock = fresh
    tok = api.token(0)
    slow(mock, 0.3)
    key = new_key("b")
    body = {"domains": [TAL, MER, WRE], "budget_units": 400}

    def go(_):
        return batch_create(Api(), tok, None, None, key=key, body=body)

    with cf.ThreadPoolExecutor(10) as ex:
        rs = list(ex.map(go, range(10)))
    codes = sorted(r.status_code for r in rs)
    assert codes == [200] * 9 + [202], codes
    assert len({r.json()["batch_id"] for r in rs}) == 1
    first = next(r for r in rs if r.status_code == 202).json()
    assert all(r.json() == first for r in rs)
    wait_batch(api, tok, first["batch_id"], timeout=120)
    slow(mock, on=False)
    from lib import domain_queries
    for d in (TAL, MER, WRE):
        assert len(domain_queries(mock.log(), d)) == 1, d           # one build per domain


def test_R4_BAT_16_overlapping_batches_build_each_domain_once(fresh):
    api, mock = fresh
    tok = api.token(0)
    slow(mock, 0.3)

    def go(i):
        return batch_create(Api(), tok, [TAL, MER], 400)

    with cf.ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(go, range(2)))
    assert [r.status_code for r in rs] == [202, 202]
    ids = [r.json()["batch_id"] for r in rs]
    assert ids[0] != ids[1]
    # RUL-S4-10: a batch is `done` when the builds *it started* are over; one that started none is
    # done at once while the other's builds still run. So wait for the builds themselves, then read
    # both batches again.
    for d in (TAL, MER):
        assert api.wait(tok, d, timeout=120)["state"] == "ready"
    dones = [wait_batch(api, tok, i, timeout=120) for i in ids]
    slow(mock, on=False)
    from lib import domain_queries
    for d in (TAL, MER):
        assert len(domain_queries(mock.log(), d)) == 1, d
    spent = s4lib.dossier_spent(api, tok, [TAL, MER])
    assert sum(b["spent_units"] for b in dones) == sum(spent.values()) == total_cost(mock.log())
    for b in dones:
        assert [d["domain"] for d in b["dossiers"]] == [TAL, MER]
        assert all(d["state"] == "ready" for d in b["dossiers"])


@pytest.mark.slow
def test_R4_BAT_17_fifty_domains_in_one_batch(fresh):
    api, mock = fresh
    tok = api.token(0)
    doms = [f"batch-co-{i:02d}.test" for i in range(50)]
    t0 = time.monotonic()
    r = api.req("POST", "/batches", token=tok, key=new_key("b"), json={"domains": doms, "budget_units": 150},
                timeout=5.0)
    assert r.status_code == 202, r.text
    assert time.monotonic() - t0 < 5.0
    s4lib.assert_batch_shape(r.json(), doms, 150)
    done = wait_batch(api, tok, r.json()["batch_id"], timeout=240)
    assert done["state"] == "done" and done["spent_units"] <= 150
    assert total_cost(mock.log()) <= 150
    assert all(d["state"] in ("ready", "failed") for d in done["dossiers"])
    assert len(api.list(tok, limit=200).json()["dossiers"]) == 50
