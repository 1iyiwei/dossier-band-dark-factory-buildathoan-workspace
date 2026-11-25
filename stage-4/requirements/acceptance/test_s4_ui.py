"""Stage 4 (browser): the screens treat `investors` as stage 3 treats `executives`: it takes none of
the data-testid attributes of stage-2.md, and "no field is contested" on /contested means none of
the six fields of §4 is (investors is never contested anyway). Lineage and batches add no screen."""
import re

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

from ui_lib import FIELDS, ids_of, sign_in, tid, url

pytestmark = pytest.mark.corpus

QB = "quillon-bio.test"
LF = "linden-forge.test"
INV_WORDS = r".*(investors|investor).*"


def build(api, mock, tok, domain, epoch=0, clock=None):
    mock.epoch(epoch)
    if clock:
        api.clock(clock)
    assert api.create(tok, domain).status_code in (200, 202)
    assert api.wait(tok, domain)["state"] == "ready"


def test_R4_UI_01_dossier_and_evidence_show_six_fields_by_testid_and_no_investors(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    build(api, mock, tok, QB)
    assert api.get(tok, QB).json()["fields"]["investors"]["status"] == "known"
    sign_in(page)
    page.goto(url(f"/dossiers/{QB}"))
    expect(tid(page, "dossier-state")).to_have_text("ready")
    ids = ids_of(page, r"(field|citation)-.+")
    assert not [i for i in ids if re.fullmatch(INV_WORDS, i)], ids
    assert ids_of(page, r"field-(?!value-|contested-|citations-)[a-z_]+") == [f"field-{f}" for f in FIELDS]
    assert ids_of(page, r"field-citations-.+") == [f"field-citations-{f}" for f in FIELDS]
    page.goto(url(f"/dossiers/{QB}/evidence"))
    expect(tid(page, "evidence-legal_name")).to_be_visible()
    ev = [i for i in ids_of(page, r"evidence-[a-z_]+") if i in {f"evidence-{f}" for f in FIELDS}
          or re.fullmatch(INV_WORDS, i)]
    assert ev == [f"evidence-{f}" for f in FIELDS], ev
    assert not ids_of(page, r"candidate-(investors|investor).*")
    assert not ids_of(page, r"evidence-empty-(investors|investor)")


def test_R4_UI_02_contested_screen_ignores_investors_and_lists_contested_fields(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    build(api, mock, tok, QB)                                  # investors known, none of the six contested
    sign_in(page)
    page.goto(url("/contested"))
    expect(tid(page, "empty-contested")).to_be_visible()
    assert ids_of(page, r"contested-item-.+") == []
    build(api, mock, tok, LF, clock="2026-03-02T09:00:00+00:00")
    page.goto(url("/contested"))
    expect(tid(page, "contested-list")).to_be_visible()
    items = ids_of(page, r"contested-item-.+")
    assert items == [f"contested-item-{LF}-ceo"], items       # the lookalike's Gordon Pike contests Hana Weiss
    assert not [i for i in items if re.fullmatch(INV_WORDS, i)]
    item = tid(page, f"contested-item-{LF}-ceo")
    expect(item).to_have_attribute("data-value", "Hana Weiss")
    assert "Gordon Pike" in item.inner_text()


def test_R4_UI_03_screens_keep_working_with_lineage_keys(fresh, page):
    api, mock = fresh
    tok = api.token(0)
    build(api, mock, tok, LF)
    sign_in(page)
    page.goto(url("/"))
    expect(tid(page, f"dossier-item-{LF}")).to_have_attribute("data-state", "ready")
    page.goto(url(f"/dossiers/{LF}"))
    expect(tid(page, "field-value-ceo")).to_have_attribute("data-value", "Hana Weiss")
    expect(tid(page, "field-contested-ceo")).to_be_visible()
    expect(tid(page, "field-value-hq_city")).to_have_attribute("data-value", "Graz")
    page.goto(url(f"/dossiers/{LF}/evidence"))
    expect(tid(page, "candidate-ceo-1")).to_have_attribute("data-kind", "own")
    expect(tid(page, "candidate-ceo-2")).to_have_attribute("data-kind", "aggregator")   # the lookalike
    expect(tid(page, "candidate-ceo-1")).to_have_attribute("data-selected", "true")
    page.goto(url(f"/dossiers/{LF}"))
    tid(page, "dossier-refresh").click()
    expect(tid(page, "dossier-state")).to_have_text("ready", timeout=20000)
