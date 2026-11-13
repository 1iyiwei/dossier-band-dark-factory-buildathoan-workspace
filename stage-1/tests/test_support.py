"""Appendix A examples from the specification, plus the rule's edge cases."""
import unittest

from app.support import supported_value, split_sentences, values_in_format
from app.pages import prose_of

D = "acme-robotics.test"


class SupportExamples(unittest.TestCase):
    def check(self, excerpt, field, value):
        self.assertEqual(supported_value(excerpt, field, D), value, (excerpt, field))

    def test_spec_table(self):
        self.check("Dana Ruiz has led Acme Robotics as chief executive since 2021.", "ceo", "Dana Ruiz")
        self.check("Acme Robotics CEO: Sam Ortiz.", "ceo", "Sam Ortiz")
        self.check("Acme Robotics was founded in 2014.", "founded_year", 2014)
        self.check("Acme Robotics employs about 120 people.", "headcount_range", "51-200")
        self.check("Acme Robotics is reportedly in talks to raise $40M.", "funding_total", None)
        self.check("Acme Robotics opened a sales office in Porto.", "hq_city", None)

    def test_funding_forms(self):
        self.check("Acme Robotics has raised $12M.", "funding_total", 12000000)
        self.check("Acme Robotics has raised 12 million dollars.", "funding_total", 12000000)
        self.check("Acme Robotics raised US$12.5 million in funding.", "funding_total", 12500000)
        self.check("Acme Robotics raised USD 3bn.", "funding_total", 3000000000)
        self.check("Acme Robotics raised $12,000,000 from investors.", "funding_total", 12000000)
        self.check("Acme Robotics raised EUR 12 million.", "funding_total", None)
        self.check("Acme Robotics raised $12M and later $5M.", "funding_total", None)
        self.check("Acme Robotics raised $1.5.", "funding_total", None)

    def test_legal_name(self):
        self.check("The legal name of Acme Robotics is Acme Robotics, Inc. today.", "legal_name", "Acme Robotics, Inc.")
        self.check("Acme Robotics, Inc. is the registered name.", "legal_name", "Acme Robotics, Inc.")
        self.check("Acme Robotics Holdings GmbH is the legal entity.", "legal_name", "Acme Robotics Holdings GmbH")
        self.check("acme-robotics.test is registered as ACME Robotics AG.", "legal_name", "ACME Robotics AG")
        self.check("The legal entity is Acme Robotics AG.", "legal_name", "Acme Robotics AG")
        self.check("The legal entity is Acme Robotics S.A.S. in France.", "legal_name", "Acme Robotics S.A.S.")

    def test_city(self):
        self.check("Acme Robotics is headquartered in Lisbon.", "hq_city", "Lisbon")
        self.check("Acme Robotics is headquartered in San Francisco, California.", "hq_city", "San Francisco")
        self.check("Acme Robotics is based in Lisbon and has an office based in Porto.", "hq_city", None)
        self.check("Acme Robotics is headquartered in Zürich.", "hq_city", "Zürich")

    def test_ceo(self):
        self.check("Acme Robotics named Dana Ruiz its new CEO.", "ceo", "Dana Ruiz")
        self.check("Acme Robotics named Dana Ruiz its new CEO, replacing the former CEO Bob Li.", "ceo", None)
        self.check("Acme Robotics CEO Ana María Lopez Garcia spoke.", "ceo", None)

    def test_headcount(self):
        self.check("Acme Robotics has 51-200 employees.", "headcount_range", "51-200")
        self.check("Acme Robotics has 50-100 employees.", "headcount_range", None)
        self.check("Acme Robotics employs 1,200 people.", "headcount_range", "1001-5000")
        self.check("Acme Robotics, founded in 2014, employs 120 people.", "headcount_range", None)
        self.check("Acme Robotics, founded in 2014, employs 120 people.", "founded_year", 2014)
        self.check("Acme Robotics has 12000 staff.", "headcount_range", "10001+")

    def test_single_sentence_and_name(self):
        self.check("Acme Robotics was founded in 2014. It grew.", "founded_year", None)
        self.check("Acme was founded in 2014.", "founded_year", None)
        self.check("acme-robotics.test was founded in 2014.", "founded_year", 2014)
        self.check("Acme Robotics was not founded in 2014.", "founded_year", None)

    def test_sentences(self):
        self.assertEqual(split_sentences("Acme Robotics, Inc. was founded. Then (it grew.) Next!\nLine two"),
                         ["Acme Robotics, Inc. was founded.", "Then (it grew.)", "Next!", "Line two"])

    def test_prose(self):
        self.assertEqual(prose_of("Kind: own\nFacts: {\"ceo\": \"X\"}\n\nHello there."), "Hello there.")
        self.assertEqual(prose_of("Hello: there.\nmore"), "")
        self.assertEqual(prose_of("hello there.\n\nmore"), "hello there.\n\nmore")


if __name__ == "__main__":
    unittest.main()
