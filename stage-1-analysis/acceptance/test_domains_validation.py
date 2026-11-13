"""§4 domain normalisation, §5 validation errors, §8 POST/GET errors."""
import pytest

from lib import assert_error, new_key

D = "nowhere-at-all.test"


@pytest.mark.parametrize("raw", [
    "Nowhere-At-All.TEST.", "www.nowhere-at-all.test", "  WWW.Nowhere-at-all.test.  ",
    "\tnowhere-at-all.test\n",
])
def test_R_DOM_01_R_DOM_04_body_normalisation(fresh, raw):
    api, _ = fresh
    tok = api.token(0)
    r = api.create(tok, raw)
    assert r.status_code == 202, r.text
    b = r.json()
    assert b["domain"] == D and b["state"] == "building"
    did = b["dossier_id"]
    # every other spelling names the same dossier
    r2 = api.create(tok, D)
    assert r2.status_code == 200 and r2.json()["dossier_id"] == did
    api.wait(tok, D)
    assert len(api.list(tok).json()["dossiers"]) == 1


@pytest.mark.parametrize("path_domain", ["WWW.NOWHERE-AT-ALL.TEST.", "www.nowhere-at-all.test",
                                         "Nowhere-At-All.Test"])
def test_R_DOM_01_R_GET_06_path_normalisation(fresh, path_domain):
    api, _ = fresh
    tok = api.token(0)
    a = api.build(tok, D)
    r = api.get(tok, path_domain)
    assert r.status_code == 200 and r.json() == a
    assert r.json()["domain"] == D
    r = api.refresh(tok, path_domain)
    assert r.status_code == 202 and r.json()["domain"] == D
    api.wait(tok, D)


@pytest.mark.parametrize("raw", [
    "http://acme-robotics.test", "https://acme-robotics.test/", "acme-robotics.test/about",
    "localhost", "acme", "www.test", "-acme.test", "acme-.test", "acme..test", ".acme.test",
    "acme.test..", "acme_robotics.test", "acme robotics.test", "acme.test:8080",
    "a" * 64 + ".test", ".".join(["a" * 63] * 4), "", "   ", "acme.tést", "*.acme.test",
])
def test_R_DOM_02_R_DOM_03_R_POST_04_invalid_domains(fresh, raw):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.create(tok, raw), 422, "validation_failed")
    assert api.list(tok).json()["dossiers"] == []


@pytest.mark.parametrize("raw,norm", [
    ("a" * 63 + ".test", "a" * 63 + ".test"),
    ("www.www.acme-robotics.test", "www.acme-robotics.test"),
    ("1a-2b.c3", "1a-2b.c3"),
    (".".join(["a" * 63] * 3) + "." + "b" * 61, ".".join(["a" * 63] * 3) + "." + "b" * 61),
])
def test_R_DOM_05_edge_valid_domains(fresh, raw, norm):
    api, _ = fresh
    tok = api.token(0)
    assert len(norm) <= 253
    r = api.create(tok, raw)
    assert r.status_code == 202, r.text
    assert r.json()["domain"] == norm
    api.wait(tok, norm)


def test_R_DOM_02_total_length_254_invalid(fresh):
    api, _ = fresh
    tok = api.token(0)
    d = ".".join(["a" * 63] * 3) + "." + "b" * 62  # 254 chars
    assert len(d) == 254
    assert_error(api.create(tok, d), 422, "validation_failed")


@pytest.mark.parametrize("bad", ["localhost", "bad_domain.test", "-x.test"])
def test_R_DOM_02_invalid_domain_in_path(fresh, bad):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.get(tok, bad), 422, "validation_failed")
    assert_error(api.refresh(tok, bad), 422, "validation_failed")


def test_R_ERR_04_R_GET_06_unknown_dossier_404(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.get(tok, "never-created.test"), 404, "not_found")


def test_R_REF_03_refresh_unknown_404(fresh):
    api, mock = fresh
    tok = api.token(0)
    assert_error(api.refresh(tok, "never-created.test"), 404, "not_found")
    assert mock.log() == []


def test_R_POST_04_domain_missing(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.req("POST", "/dossiers", token=tok, key=new_key(), json={}), 422,
                 "validation_failed")
    assert_error(api.req("POST", "/dossiers", token=tok, key=new_key(), json={"name": D}), 422,
                 "validation_failed")


@pytest.mark.parametrize("body", [
    b"not json", b'{"domain": ', b"", b"[1,2]", b'"nowhere-at-all.test"', b"null",
])
def test_R_ERR_02_post_dossiers_unparseable_or_not_object(fresh, body):
    api, _ = fresh
    tok = api.token(0)
    r = api.req("POST", "/dossiers", token=tok, key=new_key(), content=body)
    assert_error(r, 400, "malformed_request")


def test_R_ERR_02_post_dossiers_domain_null(fresh):
    """RUL-15: null is either a wrong-typed field (400) or a missing one (422)."""
    api, _ = fresh
    tok = api.token(0)
    r = api.req("POST", "/dossiers", token=tok, key=new_key(), json={"domain": None})
    assert (r.status_code, r.json()["error"]["code"]) in ((400, "malformed_request"),
                                                          (422, "validation_failed"))


@pytest.mark.parametrize("val", [5, ["nowhere-at-all.test"], {"d": 1}, True])
def test_R_ERR_02_post_dossiers_domain_wrong_type(fresh, val):
    api, _ = fresh
    tok = api.token(0)
    r = api.req("POST", "/dossiers", token=tok, key=new_key(), json={"domain": val})
    assert_error(r, 400, "malformed_request")


def test_R_CNV_03_unknown_body_fields_ignored(fresh):
    api, _ = fresh
    tok = api.token(0)
    r = api.req("POST", "/dossiers", token=tok, key=new_key(),
                json={"domain": D, "priority": "high", "extra": {"a": [1]}})
    assert r.status_code == 202
    api.wait(tok, D)


# ---------------------------------------------------------------- list query parameters
@pytest.mark.parametrize("params", [
    {"limit": "0"}, {"limit": "201"}, {"limit": "-1"}, {"limit": "abc"}, {"limit": "1e9"},
    {"limit": "4.0"}, {"limit": "+4"}, {"limit": ""}, {"offset": "-1"}, {"offset": "x"},
    {"offset": "1.5"}, {"offset": "+0"}, {"offset": "1e1"}, {"limit": " 5"},
])
def test_R_ERR_06_list_params_invalid(fresh, params):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.list(tok, **params), 422, "validation_failed")


@pytest.mark.parametrize("params", [{"limit": "1"}, {"limit": "200"}, {"offset": "0"},
                                    {"offset": "1000"}, {"limit": "007"}])
def test_R_ERR_06_list_params_valid(fresh, params):
    api, _ = fresh
    tok = api.token(0)
    r = api.list(tok, **params)
    assert r.status_code == 200, r.text


def test_R_CNV_04_unknown_query_params_ignored(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert api.list(tok, sort="desc", foo="bar").status_code == 200
    api.build(tok, D)
    assert api.req("GET", f"/dossiers/{D}", token=tok, params={"x": "1"}).status_code == 200


# ---------------------------------------------------------------- Idempotency-Key ranges
def test_R_IDEM_13_key_length(fresh):
    api, _ = fresh
    tok = api.token(0)
    assert_error(api.create(tok, D, key="k" * 256), 422, "validation_failed")
    assert api.create(tok, D, key="k" * 255).status_code == 202
    api.wait(tok, D)
    assert_error(api.refresh(tok, D, key="r" * 256), 422, "validation_failed")
    assert api.refresh(tok, D, key="r").status_code == 202
    api.wait(tok, D)


def test_R_IDEM_01_key_required(fresh):
    api, _ = fresh
    tok = api.token(0)
    r = api.req("POST", "/dossiers", token=tok, json={"domain": D})
    assert_error(r, 400, "missing_idempotency_key")
    r = api.req("POST", "/dossiers", token=tok, json={"domain": D}, headers={"Idempotency-Key": ""})
    assert_error(r, 400, "missing_idempotency_key")
    assert api.list(tok).json()["dossiers"] == []
    api.build(tok, D)
    r = api.req("POST", f"/dossiers/{D}/refresh", token=tok)
    assert_error(r, 400, "missing_idempotency_key")
    r = api.req("POST", f"/dossiers/{D}/refresh", token=tok, headers={"Idempotency-Key": ""})
    assert_error(r, 400, "missing_idempotency_key")
    assert api.get(tok, D).json()["state"] == "ready"

