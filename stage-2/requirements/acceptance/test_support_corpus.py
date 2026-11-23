"""§4 evidence/support + Appendix A, judged end-to-end on the analyst corpus.

For every company in corpus_spec.EXPECTED the dossier built from the mock must hold exactly the
expected values (or one of an expected set), every citation must support its value by
oracle.py, must be text the provider served for that URL (mock call log) and must come from
the page's prose, the build must stay within 80 units, spent_units must equal the mock's
recorded cost, and exactly one successful search must use the bare domain as its query.
"""
import pytest

import oracle
from corpus_spec import EXPECTED, selected
from lib import (assert_dossier_shape, candidate_problems, citation_problems, domain_queries,
                 successful, total_cost)

pytestmark = pytest.mark.corpus

CASES = [(d, 0) for d in EXPECTED]


def check_expected(b, domain, epoch):
    """Stage 2: the field value is the one the selection rule picks (hand-written in
    corpus_spec.SELECTED / the single EXPECTED value); None means unknown."""
    exp = EXPECTED[domain][epoch]
    errs = []
    for f in oracle.FIELDS:
        got = b["fields"][f]["value"]
        want = None if exp[f] is None else selected(domain, f, epoch)
        if want is None:
            if got is not None:
                errs.append(f"{f}: expected unknown, got {got!r} citing "
                            f"{[c['excerpt'] for c in b['fields'][f]['citations']]}")
        elif got != want or type(got) is not type(want):
            errs.append(f"{f}: expected {want!r}, got {got!r}")
    return errs


def check_log_rules(log, domain, builds=1):
    errs = []
    n = len(domain_queries(log, domain))
    if n != builds:
        errs.append(f"successful searches with query == {domain!r}: {n}, expected {builds}")
    for e in log:
        if e.get("method") == "research":
            if domain not in (e.get("query") or ""):
                errs.append(f"research query does not name the domain: {e.get('query')!r}")
            fields = e.get("fields") or []
            if not fields or not set(fields) <= set(oracle.FIELDS):
                errs.append(f"research output schema fields {fields!r}")
        if e.get("provider") == "nimble" and e.get("method") == "extract":
            n = len(e.get("urls") or [])
            # stage 2: a render extract costs 3 per URL; a plain one 1 per URL
            if e.get("status", 200) < 400 and e.get("cost") not in (n, 3 * n):
                errs.append(f"nimble extract cost {e.get('cost')} for {n} urls")
    return errs


@pytest.mark.parametrize("domain,epoch", CASES, ids=[d for d, _ in CASES])
def test_R_EVD_08_R_SUP_corpus_company(fresh, domain, epoch):
    """R-EVD-08 + R-SUP-01..12 + R-GEN-01/02 + R-EVD-01..07 + R-COST-01/03/04."""
    api, mock = fresh
    tok = api.token(0)
    b = api.build(tok, domain)
    assert b["state"] == "ready", b
    assert_dossier_shape(b, domain)
    log = mock.log()
    problems = check_expected(b, domain, epoch)
    problems += citation_problems(b, domain, log)
    problems += candidate_problems(b, domain, log, epoch)      # stage 2: R-CAN-*, R-SEL-*, R-STS-*
    cost = total_cost(log)
    if cost > 80:
        problems.append(f"build spent {cost} units > 80")
    if b["spent_units"] != cost:
        problems.append(f"spent_units {b['spent_units']} != mock recorded cost {cost}")
    problems += check_log_rules(log, domain)
    assert not problems, "\n".join(problems)


def test_R_EVD_07_conflicting_values_cite_only_chosen_value(fresh):
    """Stage 1 rule; stage 2 makes the choice deterministic (own page over news page)."""
    api, mock = fresh
    tok = api.token(0)
    d = "ledgerline-partners.test"
    b = api.build(tok, d)
    for f in ("ceo", "founded_year"):
        fv = b["fields"][f]
        assert fv["status"] == "contested"
        for c in fv["citations"]:
            assert oracle.supported_value(c["excerpt"], f, d) == fv["value"], c


def test_R_EVD_06_research_only_evidence_cites_research(fresh):
    api, mock = fresh
    tok = api.token(0)
    d = "orrin-bay.test"
    b = api.build(tok, d)
    ceo = b["fields"]["ceo"]
    assert ceo["value"] == "Priya Lindqvist"
    assert any(c["url"] == "https://orrin-bay.test/leadership" and c["provider"] == "nimble"
               for c in ceo["citations"]), ceo
    research = [e for e in successful(mock.log()) if e.get("method") == "research"]
    assert research, "no successful nimble research run was made"
    assert all(e.get("provider") == "nimble" for e in research)


def test_R_EVD_03_R_EVD_10_header_facts_are_not_evidence(fresh):
    api, _ = fresh
    tok = api.token(0)
    b = api.build(tok, "quorra-dynamics.test")
    assert b["state"] == "ready"
    for f in ("hq_city", "ceo", "founded_year"):
        assert b["fields"][f]["status"] == "unknown", (f, b["fields"][f])


def test_R_EVD_09_full_text_beyond_snippets(fresh):
    """The supporting sentences sit after ~1,700 characters of filler."""
    api, mock = fresh
    tok = api.token(0)
    b = api.build(tok, "sablewood-logistics.test")
    assert all(fv["status"] == "known" for fv in b["fields"].values()), b["fields"]
