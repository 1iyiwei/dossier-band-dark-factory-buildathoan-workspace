"""§7 idempotency on POST /dossiers and POST /dossiers/{domain}/refresh."""
import concurrent.futures as cf
import time

import pytest

from lib import assert_error, domain_queries, new_key

D = "nowhere-at-all.test"
E = "elsewhere-entirely.test"


def post_raw(api, tok, key, raw: bytes, path="/dossiers"):
    return api.req("POST", path, token=tok, key=key, content=raw)


def test_R_IDEM_03_R_IDEM_11_replay_returns_original_body(fresh):
    api, mock = fresh
    tok = api.token(0)
    k = new_key()
    first = api.create(tok, D, key=k)
    assert first.status_code == 202
    api.wait(tok, D)  # dossier is now ready; original body said building
    mock.reset(0)
    r = api.create(tok, D, key=k)
    assert r.status_code == 200
    assert r.json() == first.json()
    assert r.json()["state"] == "building"
    assert api.get(tok, D).json()["state"] == "ready"  # no build started
    time.sleep(0.5)
    assert mock.log() == []  # no provider call


def test_R_IDEM_04_same_key_different_body(fresh):
    api, _ = fresh
    tok = api.token(0)
    k = new_key()
    assert api.create(tok, D, key=k).status_code == 202
    assert_error(api.create(tok, E, key=k), 409, "idempotency_key_reuse")
    assert_error(api.get(tok, E), 404, "not_found")
    api.wait(tok, D)


def test_R_IDEM_06_case_variant_domain_is_a_different_body(fresh):
    api, _ = fresh
    tok = api.token(0)
    k = new_key()
    assert api.create(tok, "Nowhere-At-All.test", key=k).status_code == 202
    assert_error(api.create(tok, D, key=k), 409, "idempotency_key_reuse")
    api.wait(tok, D)


def test_R_IDEM_06_case_variant_path_is_a_different_request(fresh):
    api, _ = fresh
    tok = api.token(0)
    api.build(tok, D)
    k = new_key()
    a = api.refresh(tok, D, key=k)
    assert a.status_code == 202
    b = api.refresh(tok, "NOWHERE-AT-ALL.TEST", key=k)
    assert b.status_code == 202, b.text  # normal response, not a 200 replay
    assert b.json() == {"dossier_id": a.json()["dossier_id"], "domain": D, "state": "building"}
    api.wait(tok, D)


def test_R_IDEM_05_same_key_different_path_succeeds_normally(fresh):
    api, _ = fresh
    tok = api.token(0)
    k = new_key()
    first = api.create(tok, D, key=k)
    assert first.status_code == 202
    r = api.refresh(tok, D, key=k)
    assert r.status_code == 202, r.text
    assert r.json() == {"dossier_id": first.json()["dossier_id"], "domain": D, "state": "building"}
    api.wait(tok, D)


def test_R_IDEM_08_same_json_value_and_unknown_fields(fresh):
    api, _ = fresh
    tok = api.token(0)
    k = new_key()
    first = post_raw(api, tok, k, b'{"domain":"nowhere-at-all.test","note":"a"}')
    assert first.status_code == 202
    for raw in (b'{ "domain" : "nowhere-at-all.test" }',
                b'{"x": [1, 2], "domain": "nowhere-at-all.test"}',
                b'\n{"note":"b",\n "domain":"nowhere-at-all.test"}\n'):
        r = post_raw(api, tok, k, raw)
        assert r.status_code == 200, (raw, r.text)
        assert r.json() == first.json()
    api.wait(tok, D)


def test_R_IDEM_02_keys_scoped_per_user(fresh):
    api, _ = fresh
    ta, tb = api.token(0), api.token(1)
    k = "shared-key-string"
    a = api.create(ta, D, key=k)
    assert a.status_code == 202
    b = api.create(tb, E, key=k)
    assert b.status_code == 202, b.text
    api.wait(ta, D)
    # Bob already used k with body E: k with body D is a reuse for Bob
    assert_error(api.create(tb, D, key=k), 409, "idempotency_key_reuse")
    c = api.create(tb, D, key="bob-other")
    assert c.status_code == 200 and c.json()["dossier_id"] == a.json()["dossier_id"]
    assert c.json()["state"] == "ready"
    # Ada replays her own
    r = api.create(ta, D, key=k)
    assert r.status_code == 200 and r.json() == a.json()
    api.wait(tb, E)


def test_R_IDEM_03_replay_of_200_response(fresh):
    api, mock = fresh
    ta, tb = api.token(0), api.token(1)
    api.build(ta, D)
    k = new_key()
    first = api.create(tb, D, key=k)
    assert first.status_code == 200
    assert first.json()["state"] == "ready"
    mock.fault("nimble", ["search", "extract", "research"], "delay", seconds=2)
    mock.fault("tavily", ["search", "extract"], "delay", seconds=2)
    assert api.refresh(ta, D).status_code == 202
    r = api.create(tb, D, key=k)
    assert r.status_code == 200 and r.json() == first.json()
    api.wait(ta, D, timeout=60)


def test_R_IDEM_07_key_reusable_after_4xx(fresh):
    api, _ = fresh
    tok = api.token(0)
    k = new_key()
    assert_error(api.create(tok, "not a domain", key=k), 422, "validation_failed")
    assert_error(api.create(tok, "not a domain", key=k), 422, "validation_failed")
    assert_error(api.req("POST", "/dossiers", token=tok, key=k, json={}), 422, "validation_failed")
    r = api.create(tok, D, key=k)
    assert r.status_code == 202, r.text
    api.wait(tok, D)
    # refresh: a 404 does not claim the key
    k2 = new_key()
    assert_error(api.refresh(tok, E, key=k2), 404, "not_found")
    api.build(tok, E)
    r = api.refresh(tok, E, key=k2)
    assert r.status_code == 202, r.text
    api.wait(tok, E)


@pytest.mark.parametrize("raw", [
    b'{"domain": "elsewhere-entirely.test"}', b'{"domain": "not a domain"}', b"{}",
    b'{"domain": 5}',
])
def test_R_IDEM_12_claimed_key_resolved_before_validation(fresh, raw):
    api, _ = fresh
    tok = api.token(0)
    k = new_key()
    assert api.create(tok, D, key=k).status_code == 202
    assert_error(post_raw(api, tok, k, raw), 409, "idempotency_key_reuse")
    api.wait(tok, D)


def test_R_IDEM_12_unparseable_body_still_400_with_claimed_key(fresh):
    api, _ = fresh
    tok = api.token(0)
    k = new_key()
    assert api.create(tok, D, key=k).status_code == 202
    assert_error(post_raw(api, tok, k, b"{oops"), 400, "malformed_request")
    api.wait(tok, D)


def test_R_IDEM_09_refresh_body_ignored(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, D)
    k = new_key()
    first = api.req("POST", f"/dossiers/{D}/refresh", token=tok, key=k, json={"a": 1})
    assert first.status_code == 202
    api.wait(tok, D)
    mock.reset(0)
    for body in (b'{"b": 2}', b"", b"definitely not json", b"[]"):
        r = post_raw(api, tok, k, body, path=f"/dossiers/{D}/refresh")
        assert r.status_code == 200, (body, r.text)
        assert r.json() == first.json()
    assert api.get(tok, D).json()["state"] == "ready"
    time.sleep(0.5)
    assert mock.log() == []


def test_R_IDEM_10_concurrent_identical_requests(fresh):
    api, mock = fresh
    tok = api.token(0)
    k = new_key()
    with cf.ThreadPoolExecutor(12) as ex:
        rs = list(ex.map(lambda _: api.create(tok, D, key=k), range(12)))
    codes = [r.status_code for r in rs]
    assert codes.count(202) == 1, codes
    assert codes.count(200) == 11, codes
    bodies = {repr(sorted(r.json().items())) for r in rs}
    assert len(bodies) == 1, bodies
    api.wait(tok, D)
    assert len(api.list(tok).json()["dossiers"]) == 1
    assert len(domain_queries(mock.log(), D)) == 1  # exactly one build


def test_R_IDEM_10_concurrent_identical_refreshes(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, D)
    mock.reset(0)
    k = new_key()
    with cf.ThreadPoolExecutor(12) as ex:
        rs = list(ex.map(lambda _: api.refresh(tok, D, key=k), range(12)))
    codes = [r.status_code for r in rs]
    assert codes.count(202) == 1, codes
    assert codes.count(200) == 11, codes
    assert len({repr(sorted(r.json().items())) for r in rs}) == 1
    api.wait(tok, D)
    time.sleep(0.5)
    assert len(domain_queries(mock.log(), D)) == 1
