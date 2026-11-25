"""Stage 4 (API): upgrades. An export of the same team's stage-1 (OLD_BASE_URL), stage-2
(OLD2_BASE_URL) and stage-3 (OLD3_BASE_URL) service, and of this service itself, is imported into
the service under test. Skipped when the old services are not given (`up.sh` with OLD_IMAGE,
OLD2_IMAGE, OLD3_IMAGE starts them).

Imported candidates whose export records no origin take the host of their URL as their origin; they
count as gathered at the imported `researched_at` (stage 1 and 2) or at the time of the build that
gathered them (stage 3); `investors` is `unknown` with no history entry until a build gives it a
value (`change`, or `initial` when it is the dossier's first ready build)."""
import os

import pytest

import oracle
import s3lib
import s4lib
import timeline as tl
from lib import FIXTURE, T0, USERS, Api, assert_dossier_shape, assert_error, new_key, parse_ts
from s4lib import host_of

OLD1 = os.environ.get("OLD_BASE_URL", "").rstrip("/")
OLD2 = os.environ.get("OLD2_BASE_URL", "").rstrip("/")
OLD3 = os.environ.get("OLD3_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.corpus

CV = "corvane-systems.test"
QB = "quillon-bio.test"
HL = "halden-labs.test"
TAL = "talloway-systems.test"
OTHER = {"now": T0, "users": [{"id": "u_other", "email": "other@example.org",
                                "password": "xxxxxxxx-1", "display_name": "Other"}]}
NEW_FIELD_KEYS = {"origins", "corroborated", "corroborated_since"}
INVESTORS_UNKNOWN = {"value": None, "status": "unknown", "true_from": None, "learned_at": None,
                     "citations": [], "candidates": [], "origins": [], "corroborated": False,
                     "corroborated_since": None}


def do_import(api, export):
    r = api.req("POST", "/_test/import", json=export, timeout=10.0)
    assert r.status_code == 204, (r.status_code, r.text)


def fail_first_build_on(old, mock, tok, domain, epoch=0):
    mock.epoch(epoch)
    s3lib.fail_providers(mock, True)
    try:
        assert old.create(tok, domain).status_code == 202
        b = old.wait(tok, domain)
    finally:
        s3lib.fail_providers(mock, False)
    assert b["state"] == "failed"


def host_problems(body, expect_since=None):
    """Every candidate's origin is the host of its URL and the keys follow from the candidates."""
    probs = []
    for f, fv in body["fields"].items():
        for c in fv["candidates"]:
            if c["origin"] != host_of(c["url"]):
                probs.append(f"{f}: origin {c['origin']} of {c['url']} is not its host")
    return probs


def simple_since(body):
    """corroborated_since expected right after a stage-1/2 import: the imported candidates count as
    gathered at researched_at, so a field with two or more hosts is corroborated since then."""
    out = {}
    for f in oracle.FIELDS:
        fv = body["fields"][f]
        hosts = {host_of(c["url"]) for c in fv["candidates"] if fv["value"] is not None
                 and c["value"] == fv["value"]}
        out[f] = parse_ts(body["researched_at"]) if len(hosts) >= 2 else None
    return out


def check_imported_keys(body):
    assert_dossier_shape(body, body["domain"])
    assert not host_problems(body)
    want = simple_since(body)
    for f in oracle.FIELDS:
        fv = body["fields"][f]
        got = parse_ts(fv["corroborated_since"]) if fv["corroborated_since"] else None
        assert got == want[f], (f, fv["corroborated_since"], want[f])
    assert body["fields"]["investors"] == INVESTORS_UNKNOWN


# =========================================================== stage-1 and stage-2 exports
def make_old(old_url, mock, extra_failed=True):
    old = Api(old_url)
    mock.reset(0)
    old.reset()
    tok = old.token(0)
    old.clock(T0)
    snaps = {}
    for d in (CV, QB, TAL):
        mock.epoch(0)
        snaps[d] = old.build(tok, d)
        assert snaps[d]["state"] == "ready"
    if extra_failed:
        fail_first_build_on(old, mock, tok, HL, epoch=1)           # a dossier with no ready build
        snaps[HL] = old.get(tok, HL).json()
    export = old.req("GET", "/_test/export", timeout=10.0).json()
    return old, tok, snaps, export


@pytest.fixture(params=["stage1", "stage2"])
def from_old(request, api, mock):
    url = OLD1 if request.param == "stage1" else OLD2
    if not url:
        pytest.skip(f"{'OLD_BASE_URL' if request.param == 'stage1' else 'OLD2_BASE_URL'} not set")
    old, tok, snaps, export = make_old(url, mock)
    mock.reset(0)
    api.reset(OTHER)
    do_import(api, export)
    assert mock.log() == [], "import made a provider call"
    return dict(stage=request.param, old=old, tok=tok, snaps=snaps, api=api, mock=mock)


def test_R4_UPG_01_imported_fields_carry_origins_from_the_hosts(from_old):
    api, tok = from_old["api"], from_old["tok"]
    for d in (CV, QB, TAL):
        body = api.get(tok, d).json()
        assert body["researched_at"] == from_old["snaps"][d]["researched_at"]
        check_imported_keys(body)
        assert list(body["fields"]) == oracle.ALL_FIELDS
    ceo = api.get(tok, CV).json()["fields"]["ceo"]
    if from_old["stage"] == "stage2":
        # the stage-2 export keeps every candidate: four hosts state Ines Marchetti's name
        assert ceo["origins"] == ["bizdata.test", "corvane-systems.test", "daily-ledger.test",
                                  "mirror-one.test"]
        assert ceo["corroborated"] is True
        assert parse_ts(ceo["corroborated_since"]) == parse_ts(from_old["snaps"][CV]["researched_at"])
    assert ceo["corroborated"] is (len(ceo["origins"]) >= 2)


def test_R4_UPG_02_investors_is_unknown_with_no_history_after_the_import(from_old):
    api, tok = from_old["api"], from_old["tok"]
    for d in (CV, QB, TAL, HL):
        h = s3lib.history(api, tok, d).json()
        assert list(h["fields"]) == oracle.ALL_FIELDS
        assert h["fields"]["investors"] == []
    assert s3lib.all_changes(api, tok) == []
    r = s3lib.as_of(api, tok, QB, from_old["snaps"][QB]["researched_at"])
    assert r.status_code == 200 and r.json()["fields"]["investors"] == INVESTORS_UNKNOWN
    v = s3lib.values(api, tok, QB, "2026-02-01").json()
    assert v["fields"]["investors"] == {"value": None, "true_from": None, "citations": []}
    assert list(v["fields"]) == oracle.ALL_FIELDS
    assert api.get(tok, HL).json()["state"] == "failed"


def test_R4_UPG_03_first_build_after_the_import_adds_investors_as_a_change(from_old):
    api, tok, mock = from_old["api"], from_old["tok"], from_old["mock"]
    mock.epoch(0)
    api.clock("2026-03-10T09:00:00+00:00")
    assert api.refresh(tok, QB).status_code == 202
    b = api.wait(tok, QB, timeout=60)
    assert b["state"] == "ready"
    assert b["fields"]["investors"]["value"] == ["Bluebird Capital", "General Atlantic", "Northwind Ventures"]
    h = s3lib.history(api, tok, QB).json()["fields"]["investors"]
    assert [(e["type"], e["value"]) for e in h] == [
        ("change", ["Bluebird Capital", "General Atlantic", "Northwind Ventures"])]
    assert parse_ts(h[0]["learned_at"]) == parse_ts("2026-03-10T09:00:00+00:00")
    feed = [e for e in s3lib.all_changes(api, tok) if e["domain"] == QB and e["field"] == "investors"]
    assert [(e["type"], e["from"]) for e in feed] == [("change", None)]
    # the origins of the new build are judged by the oracle (lineage), not by hosts
    inv = b["fields"]["investors"]
    assert inv["origins"] == ["bizdata.test", "dealwire.test", "quillon-bio.test"] and inv["corroborated"]
    assert parse_ts(inv["corroborated_since"]) == parse_ts("2026-03-10T09:00:00+00:00")
    assert_dossier_shape(b, QB)


def test_R4_UPG_04_standing_origins_survive_into_the_next_build(from_old):
    """corvane's ceo value is the same after the import and after a new build: its imported
    candidates stay gathered at `researched_at`, whatever the new build gathered."""
    api, tok, mock = from_old["api"], from_old["tok"], from_old["mock"]
    before = api.get(tok, CV).json()["fields"]["ceo"]
    mock.epoch(1)                                                  # own page only: Ines Marchetti still
    api.clock("2026-03-12T09:00:00+00:00")
    assert api.refresh(tok, CV).status_code == 202
    b = api.wait(tok, CV, timeout=60)
    ceo = b["fields"]["ceo"]
    assert ceo["value"] == before["value"] == "Ines Marchetti"
    assert ceo["origins"] == ["corvane-systems.test"] and ceo["corroborated"] is False
    if from_old["stage"] == "stage2":
        assert ceo["corroborated_since"] == before["corroborated_since"]   # standing origins stay
    assert_dossier_shape(b, CV)
    assert not [e for e in s3lib.all_changes(api, tok) if e["domain"] == CV and e["field"] == "ceo"]


def test_R4_UPG_05_a_dossier_whose_only_build_failed_gets_initial_entries(from_old):
    api, tok, mock = from_old["api"], from_old["tok"], from_old["mock"]
    mock.epoch(1)                                                  # halden-labs: two investors
    api.clock("2026-03-11T09:00:00+00:00")
    assert api.refresh(tok, HL).status_code == 202
    b = api.wait(tok, HL, timeout=60)
    assert b["state"] == "ready"
    h = s3lib.history(api, tok, HL).json()["fields"]
    assert [e["type"] for e in h["investors"]] == ["initial"]      # the dossier's first ready build
    assert h["investors"][0]["value"] == ["Birch Partners", "Fjord Capital"]
    assert [e for e in s3lib.all_changes(api, tok) if e["domain"] == HL] == []


# =========================================================== stage-3 export
S3_SCRIPT_CV = [{"epoch": 0, "clock": "2026-03-01T09:00:00+00:00"},
                {"epoch": 1, "clock": "2026-03-02T09:00:00+00:00"},
                {"epoch": 2, "clock": "2026-03-03T09:00:00+00:00"},
                {"epoch": 2, "clock": "2026-03-03T12:00:00+00:00", "fail": True},
                {"epoch": 3, "clock": "2026-03-04T09:00:00+00:00"}]
S3_SCRIPT_QB = [{"epoch": 0, "clock": "2026-03-05T09:00:00+00:00"},
                {"epoch": 1, "clock": "2026-03-06T09:00:00+00:00"}]


@pytest.fixture()
def from3(api, mock):
    if not OLD3:
        pytest.skip("OLD3_BASE_URL (final stage-3 service) not set")
    old = Api(OLD3)
    mock.reset(0)
    old.reset()
    tok = old.token(0)
    recs_cv = s3lib.run(old, mock, tok, CV, S3_SCRIPT_CV)
    recs_qb = s3lib.run(old, mock, tok, QB, S3_SCRIPT_QB)
    old_state = {}
    for d in (CV, QB):
        old_state[d] = dict(
            history=s3lib.history(old, tok, d).json(),
            asof={r.clock: s3lib.as_of(old, tok, d, r.clock).json() for r in (recs_cv if d == CV else recs_qb)
                  if r.ready},
            values=[s3lib.values(old, tok, d, ta, ao).json() for ta, ao in VALUES_PAIRS[d]],
            cur=old.get(tok, d).json())
    old_feed = s3lib.all_changes(old, tok)
    export = old.req("GET", "/_test/export", timeout=10.0).json()
    mock.reset(0)
    api.reset(OTHER)
    do_import(api, export)
    assert mock.log() == []
    api.clock("2026-03-06T09:00:00+00:00")                 # import leaves the clock; the old one read this
    return dict(old=old, tok=tok, recs=dict(cv=recs_cv, qb=recs_qb), old_state=old_state,
                old_feed=old_feed, api=api, mock=mock)


VALUES_PAIRS = {CV: [("2026-03-01", "2026-03-05T00:00:00+00:00"), ("2021-05-01", "2026-03-03T09:00:00+00:00"),
                     ("2026-03-30", None)],
                QB: [("2026-03-01", "2026-03-05T12:00:00+00:00"), ("2024-06-01", "2026-03-06T09:00:00+00:00"),
                     ("2026-03-30", None)]}


def strip_new(fv):
    out = {k: v for k, v in fv.items() if k not in NEW_FIELD_KEYS}
    out["candidates"] = [{k: v for k, v in c.items() if k != "origin"} for c in fv["candidates"]]
    return out


def test_R4_UPG_06_stage3_builds_answer_as_of_with_the_new_keys(from3):
    api, tok = from3["api"], from3["tok"]
    for d, recs in (("cv", from3["recs"]["cv"]), ("qb", from3["recs"]["qb"])):
        dom = CV if d == "cv" else QB
        ready = [r for r in recs if r.ready]
        bodies = [r.snap for r in ready]
        times = [r.time for r in ready]
        for i, r in enumerate(ready):
            new = s3lib.as_of(api, tok, dom, r.clock).json()
            old = from3["old_state"][dom]["asof"][r.clock]
            assert_dossier_shape(new, dom)
            assert not host_problems(new)
            for f in oracle.ALL_FIELDS:
                if f == "investors":
                    assert new["fields"][f] == INVESTORS_UNKNOWN
                else:
                    assert strip_new(new["fields"][f]) == old["fields"][f], (dom, r.clock, f)
            for k in ("dossier_id", "domain", "state", "researched_at", "spent_units"):
                assert new[k] == old[k], (dom, r.clock, k)
            want = s4lib.imported_expectation(bodies[:i + 1], times[:i + 1])
            for f in oracle.ALL_FIELDS:
                fv = new["fields"][f]
                assert fv["origins"] == want[f]["origins"], (dom, i, f, fv["origins"], want[f])
                assert fv["corroborated"] is want[f]["corroborated"], (dom, i, f)
                got = parse_ts(fv["corroborated_since"]) if fv["corroborated_since"] else None
                assert got == want[f]["since"], (dom, i, f, fv["corroborated_since"], want[f]["since"])
        cur = api.get(tok, dom).json()
        last = s3lib.as_of(api, tok, dom, ready[-1].clock).json()
        assert cur == last


def test_R4_UPG_07_stage3_values_history_and_feed_answer_as_before(from3):
    api, tok = from3["api"], from3["tok"]
    for dom in (CV, QB):
        st = from3["old_state"][dom]
        for (ta, ao), old in zip(VALUES_PAIRS[dom], st["values"]):
            assert "fields" in old, (dom, ta, ao, old)                 # the stage-3 service answered 200
            new = s3lib.values(api, tok, dom, ta, ao).json()
            assert list(new["fields"]) == oracle.ALL_FIELDS
            assert new["fields"]["investors"] == {"value": None, "true_from": None, "citations": []}
            for f in oracle.ALL_FIELDS[:-1]:
                assert new["fields"][f] == old["fields"][f], (dom, ta, ao, f)
        h = s3lib.history(api, tok, dom).json()
        assert h["fields"]["investors"] == []
        for f in oracle.ALL_FIELDS[:-1]:
            assert h["fields"][f] == st["history"]["fields"][f], (dom, f)
    assert s3lib.all_changes(api, tok) == from3["old_feed"]          # the same entries, the same seq


def test_R4_UPG_08_the_first_build_after_a_stage3_import_continues_the_standing_origins(from3):
    api, tok, mock = from3["api"], from3["tok"], from3["mock"]
    mock.epoch(4)
    api.clock("2026-03-10T09:00:00+00:00")
    assert api.refresh(tok, QB).status_code == 202
    b = api.wait(tok, QB, timeout=60)
    assert b["state"] == "ready"
    h = s3lib.history(api, tok, QB).json()["fields"]["investors"]
    assert len(h) == 1 and h[0]["type"] == "change" and h[0]["value"] == b["fields"]["investors"]["value"]
    feed = s3lib.all_changes(api, tok)
    assert feed[:len(from3["old_feed"])] == from3["old_feed"]
    assert min(e["seq"] for e in feed[len(from3["old_feed"]):]) > max([e["seq"] for e in from3["old_feed"]] or [0])
    assert [e for e in feed if e["field"] == "investors" and e["domain"] == QB][0]["from"] is None
    assert_dossier_shape(b, QB)


# =========================================================== this service's own export
def test_R4_UPG_09_own_export_keeps_batches_keys_and_corroboration(api, mock):
    api.reset()
    mock.reset(0)
    tok = api.token(0)
    recs = s3lib.run(api, mock, tok, CV, S3_SCRIPT_CV[:3])
    key = new_key("b")
    body = {"domains": [QB, TAL], "budget_units": 250}
    r = s4lib.batch_create(api, tok, None, None, key=key, body=body)
    assert r.status_code == 202
    done = s4lib.wait_batch(api, tok, r.json()["batch_id"], timeout=90)
    probe = lambda: dict(
        cur={d: api.get(tok, d).json() for d in (CV, QB, TAL)},
        hist={d: s3lib.history(api, tok, d).json() for d in (CV, QB, TAL)},
        feed=s3lib.all_changes(api, tok),
        asof=[s3lib.as_of(api, tok, CV, x.clock).json() for x in recs],
        batch=s4lib.batch_get(api, tok, r.json()["batch_id"]).json())
    before = probe()
    export = api.req("GET", "/_test/export", timeout=10.0).json()
    api.reset(OTHER)
    assert api.req("GET", "/dossiers", token=api.login("other@example.org", "xxxxxxxx-1").json()["token"]).json()["dossiers"] == []
    do_import(api, export)
    assert probe() == before
    do_import(api, export)                                          # repeating it restores without duplicating
    assert probe() == before
    again = s4lib.batch_create(api, tok, None, None, key=key, body=body)
    assert again.status_code == 200 and again.json() == r.json()
    assert_error(s4lib.batch_create(api, tok, None, None, key=key, body={"domains": [QB], "budget_units": 250}),
                 409, "idempotency_key_reuse")
    assert_error(s4lib.batch_get(api, api.token(1), r.json()["batch_id"]), 404, "not_found")
    assert before["asof"][0]["fields"]["ceo"]["corroborated_since"] is not None   # the first build corroborated it
