"""Offline: the analyst's Appendix A oracle agrees with every example the specification gives.
No service needed (R-SUP-13). Also re-runs the corpus self-check."""
import pytest

import check_corpus
import oracle

A = "acme-robotics.test"


@pytest.mark.parametrize("excerpt,field,value", [
    # A.2 table
    ("Dana Ruiz has led Acme Robotics as chief executive since 2021.", "ceo", "Dana Ruiz"),
    ("Acme Robotics CEO: Sam Ortiz.", "ceo", "Sam Ortiz"),
    ("Acme Robotics was founded in 2014.", "founded_year", 2014),
    ("Acme Robotics employs about 120 people.", "headcount_range", "51-200"),
    # §4 support examples
    ("Acme Robotics has raised $12M.", "funding_total", 12000000),
    ("Acme Robotics has raised 12 million dollars.", "funding_total", 12000000),
    # A.4 amount examples
    ("Acme Robotics raised $12.5 million.", "funding_total", 12500000),
    ("Acme Robotics raised US$12 million.", "funding_total", 12000000),
    ("Acme Robotics raised USD 12 million.", "funding_total", 12000000),
    ("Acme Robotics raised $12m.", "funding_total", 12000000),
    ("Acme Robotics raised $12,000,000.", "funding_total", 12000000),
    ("Acme Robotics raised 12,000,000 US dollars.", "funding_total", 12000000),
    ("Acme Robotics raised $3bn.", "funding_total", 3000000000),
    ("Acme Robotics raised $40mn in funding.", "funding_total", 40000000),
    ("Acme Robotics raised $250k.", "funding_total", 250000),
    # legal names and suffixes
    ("Acme Robotics, Inc. is the registered name.", "legal_name", "Acme Robotics, Inc."),
    ("Its legal entity is Acme Robotics GmbH.", "legal_name", "Acme Robotics GmbH"),
    ("The registered name is ACME ROBOTICS AB.", "legal_name", "ACME ROBOTICS AB"),
    ("Acme Robotics Nordic AS is the legal entity.", "legal_name", "Acme Robotics Nordic AS"),
    ("acme-robotics.test is registered as Acme Robotics B.V. in Delft.", "legal_name",
     "Acme Robotics B.V."),
    # cities
    ("Acme Robotics is headquartered in Lisbon.", "hq_city", "Lisbon"),
    ("Acme Robotics is based in Zürich, Switzerland.", "hq_city", "Zürich"),
    ("Acme Robotics is based in Aix-en-Provence.", "hq_city", "Aix"),
    ("Acme Robotics has its headquarters in New York City.", "hq_city", "New York City"),
    # headcount
    ("Acme Robotics has 51-200 employees.", "headcount_range", "51-200"),
    ("Acme Robotics has 12,000 staff.", "headcount_range", "10001+"),
    ("Acme Robotics employs 10 people.", "headcount_range", "1-10"),
    ("Acme Robotics employs 5001 people.", "headcount_range", "5001-10000"),
    ("Acme Robotics employs 120 people after raising $5M.", "headcount_range", "51-200"),
])
def test_supports(excerpt, field, value):
    assert oracle.supported_value(excerpt, field, A) == value


@pytest.mark.parametrize("excerpt,field", [
    ("Acme Robotics is reportedly in talks to raise $40M.", "funding_total"),
    ("Acme Robotics opened a sales office in Porto.", "hq_city"),
    ("Acme Robotics was founded in 2014. It grew.", "founded_year"),           # two sentences
    ("Acme Robotics was not founded in 2014.", "founded_year"),
    ("Acme Robotics raised €12M.", "funding_total"),                         # other currency
    ("Acme Robotics raised 12 million euros.", "funding_total"),
    ("Acme Robotics raised $12.5.", "funding_total"),                         # not whole dollars
    ("Acme Robotics has 10-50 employees.", "headcount_range"),                # spans two ranges
    ("Acme Robotics employs 0 people.", "headcount_range"),
    ("Acme Robotics CEO Jean Paul Marie Dubois spoke.", "ceo"),               # four words
    ("Acme Robotics CEO Dana spoke.", "ceo"),                                 # one word
    ("Acme Robotics founded in 1799.", "founded_year"),
    ("Acme Robotics founded in 2100.", "founded_year"),
    ("AcmeRobotics was founded in 2014.", "founded_year"),                    # no name
    ("Acme Robotics was founded in 2014 and 2015.", "founded_year"),
    ("Acme Robotics was founded in 20145.", "founded_year"),
    ("Acme Robotics was founded in Q2014.", "founded_year"),
    ("Acme Robotics was founded in 2,014.", "founded_year"),                  # RUL-06
    ("Acme Robotics was founded in 2014.0.", "founded_year"),                 # RUL-06
    ("Acme Robotics will become Acme Robotics Ltd, its legal name.", "legal_name"),
    ("Acme Robotics' former CEO Dana Ruiz left.", "ceo"),
    ("Acme Robotics is based in the Bay Area.", "hq_city"),
])
def test_does_not_support(excerpt, field):
    assert oracle.supported_value(excerpt, field, A) is None


@pytest.mark.parametrize("line,n", [
    ("Acme Robotics, Inc. was founded in 2014.", 1),
    ("Acme Robotics S.p.A. is here. Next one.", 2),
    ('He said "Acme Robotics was founded in 2014." Then left.', 2),
    ("Was it founded in 2014? Yes! It was.", 3),
    ("Version 2.0 shipped.Then 3.0 shipped.", 1),
    ("Acme (est. 2014) grew.", 2),
])
def test_sentence_split(line, n):
    assert len(oracle.split_line(line)) == n


def test_header_and_prose():
    text = 'Kind: news\nFacts: {"ceo": "X Y"}\n\nAcme Robotics CEO: Dana Ruiz.\nMore: text'
    h, p = oracle.split_header(text)
    assert h.startswith("Kind:") and p == "Acme Robotics CEO: Dana Ruiz.\nMore: text"
    assert oracle.split_header("Plain prose here.\nKind: news")[0] == ""


def test_corpus_self_check():
    assert check_corpus.main() == 0
