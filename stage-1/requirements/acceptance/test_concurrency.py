"""§11 concurrency, §2 50 in-flight requests within the per-request timeout, §5 no 5xx."""
import concurrent.futures as cf
import time

from lib import Api, domain_queries, new_key

D = "nowhere-at-all.test"


def test_R_POST_03_R_CON_03_concurrent_creates_one_dossier(fresh):
    api, mock = fresh
    toks = [api.token(0), api.token(1)]
    with cf.ThreadPoolExecutor(20) as ex:
        rs = list(ex.map(lambda i: api.create(toks[i % 2], ["Nowhere-At-All.test", D,
                                                            "www.nowhere-at-all.test"][i % 3]),
                         range(20)))
    codes = [r.status_code for r in rs]
    assert codes.count(202) == 1, codes
    assert codes.count(200) == 19, codes
    assert len({r.json()["dossier_id"] for r in rs}) == 1
    assert all(r.json()["domain"] == D for r in rs)
    api.wait(toks[0], D)
    time.sleep(0.5)
    assert len(api.list(toks[0]).json()["dossiers"]) == 1
    assert len(domain_queries(mock.log(), D)) == 1


def test_R_CON_02_R_DEL_10_fifty_in_flight(fresh):
    api, mock = fresh
    tok = api.token(0)
    api.build(tok, D)
    clients = [Api() for _ in range(5)]

    def one(i):
        c = clients[i % 5]
        t0 = time.monotonic()
        kind = i % 6
        if kind == 0:
            r = c.req("GET", f"/dossiers/{D}", token=tok)
        elif kind == 1:
            r = c.req("GET", "/dossiers", token=tok, params={"q": "all"})
        elif kind == 2:
            r = c.req("POST", "/auth/signup", json={"email": f"load{i}@example.org",
                                                    "password": "abcdefgh", "display_name": "L"})
        elif kind == 3:
            r = c.req("POST", "/dossiers", token=tok, key=new_key(),
                      json={"domain": f"load-{i}.test"})
        elif kind == 4:
            r = c.req("GET", "/health")
        else:
            r = c.req("POST", "/auth/login", json={"email": "ines@example.org",
                                                   "password": "lantern-river-42"})
        return r.status_code, time.monotonic() - t0

    with cf.ThreadPoolExecutor(50) as ex:
        res = list(ex.map(one, range(100)))
    for code, dt in res:
        assert code < 500
        assert dt <= 5.0
    for i in range(100):
        if i % 6 == 3:
            api.wait(tok, f"load-{i}.test", timeout=60)


def test_R_CON_01_serializable_create_and_refresh(fresh):
    """Interleaved refreshes during creation never yield two builds at once."""
    api, mock = fresh
    tok = api.token(0)
    assert api.create(tok, D).status_code == 202
    with cf.ThreadPoolExecutor(10) as ex:
        rs = list(ex.map(lambda _: api.refresh(tok, D), range(10)))
    assert all(r.status_code == 202 for r in rs)
    assert all(r.json() == {"dossier_id": rs[0].json()["dossier_id"], "domain": D,
                            "state": "building"} for r in rs)
    api.wait(tok, D)
