"""§8 GET /dossiers: shape, filtering, ordering, pagination."""
import pytest

from lib import parse_ts

pytestmark = pytest.mark.corpus

DOMAINS = ["vantorra-health.test", "talloway-systems.test", "sablewood-logistics.test",
           "nowhere-at-all.test", "meridel-foods.test"]


@pytest.fixture()
def populated(fresh):
    api, mock = fresh
    tok = api.token(0)
    for d in DOMAINS:
        assert api.create(tok, d).status_code == 202
    built = {d: api.wait(tok, d) for d in DOMAINS}
    return api, tok, built


def domains_of(resp):
    assert resp.status_code == 200, resp.text
    return [d["domain"] for d in resp.json()["dossiers"]]


def test_R_LST_01_item_shape(populated):
    api, tok, built = populated
    b = api.list(tok).json()
    assert set(b) >= {"dossiers", "has_more"} and b["has_more"] is False
    for it in b["dossiers"]:
        full = built[it["domain"]]
        assert it["dossier_id"] == full["dossier_id"]
        assert it["state"] == full["state"]
        assert it["legal_name"] == full["fields"]["legal_name"]["value"]
        assert it["researched_at"] == full["researched_at"]
        if it["researched_at"]:
            parse_ts(it["researched_at"])
        assert it["spent_units"] == full["spent_units"]


def test_R_LST_03_ordered_by_domain(populated):
    api, tok, _ = populated
    assert domains_of(api.list(tok)) == sorted(DOMAINS)


@pytest.mark.parametrize("q,expected", [
    ("", sorted(DOMAINS)),
    ("TEST", sorted(DOMAINS)),
    ("wood", ["sablewood-logistics.test"]),
    ("inc.", ["talloway-systems.test"]),           # legal_name "Talloway Systems, Inc."
    ("holdings s.a", ["vantorra-health.test"]),    # legal_name only
    ("PTY", ["meridel-foods.test"]),               # legal_name only
    ("ltd", ["meridel-foods.test", "sablewood-logistics.test"]),
    ("-", sorted(DOMAINS)),
    ("zzz", []),
    ("all.t", ["nowhere-at-all.test"]),
])
def test_R_LST_02_q_filter(populated, q, expected):
    api, tok, _ = populated
    assert domains_of(api.list(tok, q=q)) == expected


def test_R_LST_04_pagination(populated):
    api, tok, _ = populated
    want = sorted(DOMAINS)
    seen = []
    for off in range(len(want)):
        r = api.list(tok, limit="1", offset=str(off))
        page = domains_of(r)
        assert len(page) == 1
        assert r.json()["has_more"] is (off < len(want) - 1)
        seen += page
    assert seen == want
    r = api.list(tok, limit="2", offset="4")
    assert domains_of(r) == want[4:] and r.json()["has_more"] is False
    r = api.list(tok, limit="5")
    assert domains_of(r) == want and r.json()["has_more"] is False
    r = api.list(tok, limit="4")
    assert domains_of(r) == want[:4] and r.json()["has_more"] is True
    r = api.list(tok, offset="10")
    assert domains_of(r) == [] and r.json()["has_more"] is False
    r = api.list(tok, q="ltd", limit="1")
    assert domains_of(r) == ["meridel-foods.test"] and r.json()["has_more"] is True


def test_R_LST_04_default_limit_50(fresh):
    api, mock = fresh
    tok = api.token(0)
    names = [f"bulk-{i:02d}.test" for i in range(52)]
    for n in names:
        assert api.create(tok, n).status_code == 202
    for n in names:
        api.wait(tok, n, timeout=60)
    r = api.list(tok)
    assert domains_of(r) == names[:50] and r.json()["has_more"] is True
    r = api.list(tok, limit="200")
    assert domains_of(r) == names and r.json()["has_more"] is False
