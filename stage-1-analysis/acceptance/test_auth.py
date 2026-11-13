"""§6 authentication, §5 error envelope for auth endpoints."""
import concurrent.futures as cf

import pytest

from lib import USERS, assert_error, new_key


def signup(api, email="new@example.org", password="abcdefgh", display_name="New"):
    return api.req("POST", "/auth/signup",
                   json={"email": email, "password": password, "display_name": display_name})


def test_R_AUTH_01_signup(fresh):
    api, _ = fresh
    r = signup(api)
    assert r.status_code == 201, r.text
    b = r.json()
    assert isinstance(b["user_id"], str) and 1 <= len(b["user_id"]) <= 64
    assert b["display_name"] == "New"
    assert isinstance(b["token"], str) and b["token"]
    assert api.req("GET", "/dossiers", token=b["token"]).status_code == 200


def test_R_AUTH_02_login_after_signup(fresh):
    api, _ = fresh
    s = signup(api).json()
    r = api.login("new@example.org", "abcdefgh")
    assert r.status_code == 200
    b = r.json()
    assert b["user_id"] == s["user_id"] and b["display_name"] == "New" and b["token"]


def test_R_AUTH_03_email_taken(fresh):
    api, _ = fresh
    assert signup(api).status_code == 201
    assert_error(signup(api, display_name="Other"), 409, "email_taken")
    assert_error(signup(api, email=USERS[0]["email"]), 409, "email_taken")


def test_R_AUTH_04_password_length(fresh):
    api, _ = fresh
    assert_error(signup(api, password="1234567"), 422, "validation_failed")
    assert signup(api, password="12345678").status_code == 201


@pytest.mark.parametrize("email", ["plainaddress", "@example.org", "user@", ""])
def test_R_AUTH_05_email_format(fresh, email):
    api, _ = fresh
    assert_error(signup(api, email=email), 422, "validation_failed")


def test_R_AUTH_06_display_name(fresh):
    api, _ = fresh
    assert_error(signup(api, display_name=""), 422, "validation_failed")
    assert_error(signup(api, email="b@example.org", display_name="x" * 101), 422, "validation_failed")
    assert signup(api, email="c@example.org", display_name="y" * 100).status_code == 201


def test_R_AUTH_07_bad_login(fresh):
    api, _ = fresh
    assert_error(api.login(USERS[0]["email"], "wrong-password"), 401, "unauthenticated")
    assert_error(api.login("nobody@example.org", "whatever123"), 401, "unauthenticated")


@pytest.mark.parametrize("path,body", [
    ("/auth/signup", {"password": "abcdefgh", "display_name": "N"}),
    ("/auth/signup", {"email": "m@example.org", "display_name": "N"}),
    ("/auth/signup", {"email": "m@example.org", "password": "abcdefgh"}),
    ("/auth/login", {"password": "abcdefgh"}),
    ("/auth/login", {"email": "m@example.org"}),
])
def test_R_AUTH_13_missing_fields_422(fresh, path, body):
    api, _ = fresh
    assert_error(api.req("POST", path, json=body), 422, "validation_failed")


@pytest.mark.parametrize("path,body", [
    ("/auth/signup", {"email": 5, "password": "abcdefgh", "display_name": "N"}),
    ("/auth/signup", {"email": "m@example.org", "password": 12345678, "display_name": "N"}),
    ("/auth/signup", {"email": "m@example.org", "password": "abcdefgh", "display_name": ["N"]}),
    ("/auth/login", {"email": "m@example.org", "password": True}),
])
def test_R_ERR_02_auth_wrong_types_400(fresh, path, body):
    api, _ = fresh
    assert_error(api.req("POST", path, json=body), 400, "malformed_request")


@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login"])
def test_R_ERR_02_auth_unparseable_400(fresh, path):
    api, _ = fresh
    assert_error(api.req("POST", path, content=b'{"email": '), 400, "malformed_request")


def test_R_CNV_03_auth_unknown_fields_ignored(fresh):
    api, _ = fresh
    r = api.req("POST", "/auth/signup", json={"email": "u@example.org", "password": "abcdefgh",
                                              "display_name": "U", "role": "admin", "x": [1]})
    assert r.status_code == 201
    r = api.req("POST", "/auth/login", json={"email": "u@example.org", "password": "abcdefgh",
                                             "remember": True})
    assert r.status_code == 200


@pytest.mark.parametrize("hdr", [None, "Bearer", "Bearer ", "Bearer not-a-real-token",
                                 "Basic dXNlcjpwYXNz", "token-without-scheme"])
def test_R_AUTH_09_protected_endpoints_need_token(fresh, hdr):
    api, _ = fresh
    headers = {} if hdr is None else {"Authorization": hdr}
    calls = [
        ("GET", "/dossiers", None),
        ("GET", "/dossiers/acme-robotics.test", None),
        ("POST", "/dossiers", {"domain": "acme-robotics.test"}),
        ("POST", "/dossiers/acme-robotics.test/refresh", None),
    ]
    for m, p, body in calls:
        # no Idempotency-Key on the write paths: 401 still wins over 400 missing key
        r = api.req(m, p, json=body, headers=headers)
        assert_error(r, 401, "unauthenticated")
        if m == "POST":
            r = api.req(m, p, json=body, headers={**headers, "Idempotency-Key": new_key()})
            assert_error(r, 401, "unauthenticated")


def test_R_AUTH_10_multiple_tokens_valid(fresh):
    api, _ = fresh
    t1 = api.token(0)
    t2 = api.token(0)
    s = signup(api).json()["token"]
    t3 = api.login("new@example.org", "abcdefgh").json()["token"]
    for t in (t1, t2, s, t3):
        assert api.req("GET", "/dossiers", token=t).status_code == 200


def test_R_AUTH_12_all_users_see_same_dossiers(fresh):
    api, _ = fresh
    ta, tb = api.token(0), api.token(1)
    tc = signup(api).json()["token"]
    a = api.build(ta, "nowhere-at-all.test")
    for t in (tb, tc):
        b = api.get(t, "nowhere-at-all.test").json()
        assert b == a
        assert [d["domain"] for d in api.list(t).json()["dossiers"]] == ["nowhere-at-all.test"]


def test_R_CON_01_concurrent_signup_same_email(fresh):
    api, _ = fresh
    with cf.ThreadPoolExecutor(10) as ex:
        rs = list(ex.map(lambda i: signup(api, email="race@example.org", display_name=f"R{i}"),
                         range(10)))
    codes = sorted(r.status_code for r in rs)
    assert codes.count(201) == 1, codes
    for r in rs:
        if r.status_code != 201:
            assert_error(r, 409, "email_taken")
