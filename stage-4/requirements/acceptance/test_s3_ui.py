"""Stage 3 (browser): the stage-2 screens keep working with the seventh field. `executives` takes
none of the screens' data-testid attributes, and a contested `executives` never makes a dossier
appear on /contested ("no field is contested" means none of the six fields of §4 is)."""
import re

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

import s3lib
from lib import T0
from ui_lib import FIELDS, ids_of, sign_in, tid, url

pytestmark = pytest.mark.corpus

CB = "cobalt-assembly.test"
HAR = "harlow-instruments.test"
NG = "northgate-labs.test"
EXEC_WORDS = r".*(executives|-cfo|-coo|-cto|-cfo-|-coo-|-cto-).*"


def build(api, mock, tok, domain, epoch=0, clock=None):
    mock.epoch(epoch)
    if clock:
        api.clock(clock)
    assert api.create(tok, domain).status_code in (200, 202)
    assert api.wait(tok, domain)["state"] == "ready"


def test_R3_UI_01_contested_executives_are_not_contested_fields(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    build(api, mock, tok, CB)                              # executives contested, the six unknown
    b = api.get(tok, CB).json()
    assert b["fields"]["executives"]["status"] == "contested"
    sign_in(page)
    page.goto(url("/contested"))
    expect(tid(page, "empty-contested")).to_be_visible()
    assert ids_of(page, r"contested-item-.+") == []
    build(api, mock, tok, HAR)
    page.goto(url("/contested"))
    expect(tid(page, "contested-list")).to_be_visible()
    items = ids_of(page, r"contested-item-.+")
    assert items and all(i.startswith(f"contested-item-{HAR}-") for i in items), items
    assert not [i for i in items if re.fullmatch(EXEC_WORDS, i)]


def test_R3_UI_02_dossier_and_evidence_screens_show_six_fields_by_testid(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    build(api, mock, tok, CB)
    build(api, mock, tok, NG, clock="2026-03-02T09:00:00+00:00")
    sign_in(page)
    for d in (CB, NG):
        page.goto(url(f"/dossiers/{d}"))
        expect(tid(page, "dossier-state")).to_have_text("ready")
        ids = ids_of(page, r"(field|citation)-.+")
        assert not [i for i in ids if "executives" in i], ids
        assert ids_of(page, r"field-(?!value-|contested-|citations-)[a-z_]+") == [f"field-{f}" for f in FIELDS]
        assert [i for i in ids_of(page, r"field-citations-.+")] == [f"field-citations-{f}" for f in FIELDS]
        page.goto(url(f"/dossiers/{d}/evidence"))
        expect(tid(page, "evidence-legal_name")).to_be_visible()
        ev = [i for i in ids_of(page, r"evidence-[a-z_]+") if i in {f"evidence-{f}" for f in FIELDS}
              or i.endswith(("executives", "cfo", "coo", "cto"))]
        assert ev == [f"evidence-{f}" for f in FIELDS], ev
        assert not ids_of(page, r"candidate-(executives|cfo|coo|cto).*")
        assert not ids_of(page, r"evidence-empty-(executives|cfo|coo|cto)")
    page.goto(url(f"/dossiers/{NG}"))
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Dana Ruiz")


def test_R3_UI_03_list_and_refresh_still_work_after_history_changes(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    build(api, mock, tok, NG)
    mock.epoch(1)
    api.clock("2026-03-10T09:00:00+00:00")
    sign_in(page)
    page.goto(url(f"/dossiers/{NG}"))
    expect(tid(page, "dossier-state")).to_have_text("ready")
    tid(page, "dossier-refresh").click()
    expect(tid(page, "dossier-state")).to_have_text("ready")
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Lee Park", timeout=15000)
    page.goto(url("/"))
    expect(tid(page, f"dossier-item-{NG}")).to_have_attribute("data-state", "ready")
    assert [e["field"] for e in s3lib.all_changes(api, tok)][:2] == ["hq_city", "ceo"]
