"""The analyst corpus: fictional companies written by the Analyst to exercise the stage-1
support rules (Appendix A) and the evidence model (§4). Nothing here is copied from the
shipped sample corpus.

`python3 corpus_spec.py` regenerates corpus/*.json.  EXPECTED holds, per company and epoch,
the value each field must have after a `ready` build (a set = any one of these values is
acceptable because the evidence supports several; None = the field must be `unknown`).
check_corpus.py verifies EXPECTED against oracle.py, including a brute-force search over
every excerpt (substring) of the evidence for fields expected to be unknown.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(HERE, "corpus")

FILLER_A = " ".join([
    "Regional freight routing is a problem of many small decisions made under uncertainty.",
    "Dispatchers balance driver hours, loading dock windows, road works and the weather.",
    "A good plan for Monday can be a poor plan by Monday noon when a ferry is cancelled.",
    "Software that helps with this work has to be fast, explainable and easy to override.",
    "Early tools printed static schedules that drivers carried in their cabs all week.",
    "Later tools used phone calls and spreadsheets that were updated by hand each evening.",
    "Modern tools ingest live position data and suggest small changes through the day.",
    "The hardest part is rarely the mathematics; it is the trust of the dispatcher.",
    "A suggestion that saves ten minutes but surprises a driver is often rejected.",
    "For that reason, routing products now show the reasons behind each suggestion.",
    "They also keep a history of overrides so that the model can learn local habits.",
    "Ports, borders and mountain passes each add their own constraints to the plan.",
    "Seasonal peaks around harvest time double the volume for a few weeks each year.",
    "Smaller carriers often share loads with competitors to fill half empty trailers.",
    "Load sharing needs a neutral marketplace with clear rules about liability.",
    "Fuel prices, tolls and emission zones change the cost of a route from week to week.",
    "Electric trucks add charging stops, which turn a routing problem into a scheduling one.",
    "Depot managers want a single screen that shows every vehicle and every promise made.",
    "Customers want an arrival time that is honest rather than one that is optimistic.",
    "The industry measures success in on time deliveries, empty miles and driver turnover.",
    "None of these numbers improves if the people using the tool do not believe it.",
])
assert len(FILLER_A) > 1600, len(FILLER_A)

FILLER_B = " ".join([
    "Warehousing has changed more in the last decade than in the fifty years before it.",
    "Racking that once held pallets for months now turns over its contents every few days.",
    "Pick paths are planned by software and walked by people wearing scanners on their wrists.",
    "Cross docking removes storage entirely for goods that arrive and leave the same day.",
    "Cold chain sites keep separate zones for chilled, frozen and ambient products.",
    "Every door on a loading bay has a booking calendar shared with hauliers.",
    "Late arrivals ripple through the day and push evening shifts into overtime.",
    "Yard management tools track trailers that wait outside before they reach a door.",
    "Returns are a growing share of volume and need their own inspection lines.",
    "Packaging rules differ between countries and between retailers in the same country.",
    "Customs paperwork for cross border shipments is still partly printed on paper.",
    "Insurers ask for temperature logs, seal numbers and photographs at handover.",
    "A missing photograph can turn a routine claim into a long dispute between firms.",
    "Network planners decide where to put depots using years of order history.",
    "A depot close to a motorway junction saves minutes on every single trip it serves.",
    "Land near junctions is expensive, so planners trade rent against transport cost.",
    "Automation is spreading from large hubs to medium sized regional depots.",
    "Robotic shuttles move totes between storage and pick stations without rest.",
    "The best operations still depend on supervisors who know every aisle by heart.",
    "Training new staff quickly matters because seasonal peaks need extra hands.",
    "Good depots publish simple rules and measure everything that can be counted.",
])
assert len(FILLER_B) > 1600, len(FILLER_B)


def page(url, text, *, kind="own", epochs=(0,), searchable=True, facts=None, title=None,
         registrant=None, published_at="2026-01-15T00:00:00Z", static_text=None):
    host = url.split("/")[2]
    p = {
        "url": url, "kind": kind, "epochs": list(epochs), "searchable": searchable,
        "published_at": published_at, "true_from": "2026-01-01",
        "title": title or host, "text": text, "facts": facts or {},
        "lineage": {"canonical": None, "first_published_by": None,
                    "registrant": registrant or host},
    }
    if static_text is not None:
        # served by search/extract; a browser (Nimble render) shows `text` instead (stage 2)
        p["static_text"] = static_text
    return p


COMPANIES: dict[str, dict] = {}
EXPECTED: dict[str, dict[int, dict]] = {}

# ---------------------------------------------------------------- 1. happy path, full text needed
COMPANIES["talloway-systems.test"] = {
    "names": ["Talloway Systems"],
    "pages": [
        page("https://talloway-systems.test/about", "\n".join([
            "Talloway Systems builds routing software for regional freight carriers.",
            "Talloway Systems, Inc. is the registered name of the company behind the Talloway platform.",
            "Talloway Systems is headquartered in Porto Alegre.",
            "Mara Quintero has been chief executive officer of Talloway Systems since 2019.",
        ]), title="About Talloway Systems"),
        page("https://talloway-systems.test/history", FILLER_A + "\n" + "\n".join([
            "Talloway Systems was founded in 2011 by two dispatchers from Curitiba.",
            "Talloway Systems employs roughly 1,450 people across four offices.",
        ]), title="Talloway Systems history"),
        page("https://freight-gazette.test/talloway-round",
             "Talloway Systems has raised US$ 37.5 million in total equity funding. "
             "The company declined to comment on valuation.",
             kind="news", facts={"funding_total": "US$37.5M"}, title="Talloway closes round"),
    ],
}
EXPECTED["talloway-systems.test"] = {0: {
    "legal_name": "Talloway Systems, Inc.", "hq_city": "Porto Alegre", "ceo": "Mara Quintero",
    "founded_year": 2011, "headcount_range": "1001-5000", "funding_total": 37500000}}

# ---------------------------------------------------------------- 2. negations, header-only facts
COMPANIES["quorra-dynamics.test"] = {
    "names": ["Quorra Dynamics"],
    "pages": [
        page("https://quorra-dynamics.test/", "\n".join([
            "Quorra Dynamics makes vibration sensors for wind turbines.",
            "Quorra Dynamics has not been headquartered in Geneva since 2020.",
            "Its legal name is not Quorra Dynamics AG.",
            "Quorra Dynamics former chief executive Elena Brandt left last year.",
        ]), facts={"hq_city": "Quorra Dynamics is headquartered in Bern.", "ceo": "Elena Brandt",
                   "founded_year": "Quorra Dynamics was founded in 2016."},
            title="Quorra Dynamics"),
        page("https://tech-dispatch.test/quorra", "\n".join([
            "Quorra Dynamics is reportedly in talks to raise $40M in new funding.",
            "Quorra Dynamics would have been established in 1999 under different owners.",
            "Quorra Dynamics, with 10-50 staff on payroll, still hires slowly.",
        ]), kind="news", title="Quorra Dynamics eyes new round"),
    ],
}
EXPECTED["quorra-dynamics.test"] = {0: {f: None for f in
                                        ["legal_name", "hq_city", "ceo", "founded_year",
                                         "headcount_range", "funding_total"]}}

# ---------------------------------------------------------------- 3. conflicting values, amount forms
COMPANIES["ledgerline-partners.test"] = {
    "names": ["Ledgerline Partners"],
    "pages": [
        page("https://ledgerline-partners.test/team", "\n".join([
            "Ines Varga is the chief executive of Ledgerline Partners.",
            "Ledgerline Partners was founded in 2003.",
        ]), title="Ledgerline team"),
        page("https://capital-wire.test/ledgerline", "\n".join([
            "Ledgerline Partners CEO Tomas Reyes spoke at the summit.",
            "Ledgerline Partners was established in 2004, according to its filings.",
            "Ledgerline Partners has raised $12M.",
            "Ledgerline Partners raised 12 million dollars from two funds.",
            "Ledgerline Partners funding reached US$12 million, or $12,000,000 in total.",
        ]), kind="news", title="Ledgerline at the summit"),
        page("https://ledgerline-partners.test/press",
             "Ledgerline Partners raised €30M in a separate euro tranche.", title="Press"),
    ],
}
EXPECTED["ledgerline-partners.test"] = {0: {
    "legal_name": None, "hq_city": None, "ceo": {"Ines Varga", "Tomas Reyes"},
    "founded_year": {2003, 2004}, "headcount_range": None, "funding_total": 12000000}}

# ---------------------------------------------------------------- 4. suffix S.A., hyphenated city, title removal
COMPANIES["vantorra-health.test"] = {
    "names": ["Vantorra Health"],
    "pages": [
        page("https://vantorra-health.test/company", "\n".join([
            "Vantorra Health Holdings S.A. is the legal entity that operates the clinics.",
            "Vantorra Health is based in Saint-Malo, France.",
            "Chief Executive Officer Noor Haddad leads Vantorra Health.",
            "Vantorra Health was incorporated in 1987.",
            "Vantorra Health has a workforce of 51-200 employees.",
            "Vantorra Health has raised $4.5m to date.",
        ]), title="Vantorra Health company"),
    ],
}
EXPECTED["vantorra-health.test"] = {0: {
    "legal_name": "Vantorra Health Holdings S.A.", "hq_city": "Saint-Malo", "ceo": "Noor Haddad",
    "founded_year": 1987, "headcount_range": "51-200", "funding_total": 4500000}}

# ---------------------------------------------------------------- 5. research claims, non-searchable pages, unicode
COMPANIES["orrin-bay.test"] = {
    "names": ["Orrin Bay"],
    "pages": [
        page("https://orrin-bay.test/", "\n".join([
            "Orrin Bay is headquartered in Tromsø.",
            "Orrin Bay designs cold-water aquaculture nets.",
        ]), title="Orrin Bay"),
        page("https://orrin-bay.test/leadership", "\n".join([
            "Orrin Bay CEO: Priya Lindqvist.",
            "Orrin Bay employs 75 people at its net loft.",
        ]), searchable=False, title="Orrin Bay leadership"),
        page("https://orrin-bay.test/investors",
             "Orrin Bay hopes to raise $9M in new funding this year.",
             searchable=False, title="Orrin Bay investors"),
    ],
    "research": {"nimble": {"0": [
        {"field": "ceo", "value": "Priya Lindqvist", "url": "https://orrin-bay.test/leadership",
         "excerpt": "Orrin Bay CEO: Priya Lindqvist."},
        {"field": "headcount_range", "value": "51-200", "url": "https://orrin-bay.test/leadership",
         "excerpt": "Orrin Bay employs 75 people at its net loft."},
        {"field": "funding_total", "value": 9000000, "url": "https://orrin-bay.test/investors",
         "excerpt": "Orrin Bay hopes to raise $9M in new funding this year."},
        {"field": "hq_city", "value": "Tromsø", "url": "https://orrin-bay.test/",
         "excerpt": "Orrin Bay is headquartered in Tromsø."},
    ]}},
}
EXPECTED["orrin-bay.test"] = {0: {
    "legal_name": None, "hq_city": "Tromsø", "ceo": "Priya Lindqvist", "founded_year": None,
    "headcount_range": "51-200", "funding_total": None}}

# ---------------------------------------------------------------- 6. sentence splitting, conflicts, scale, city run
COMPANIES["meridel-foods.test"] = {
    "names": ["Meridel Foods"],
    "pages": [
        page("https://meridel-foods.test/", "\n".join([
            "Meridel Foods was founded in 1996! Nobody could have predicted its growth.",
            "Meridel Foods, with 120 drivers and 1998 vans, employs a large staff.",
            "Meridel Foods named Ana Sousa and Rui Matos co-CEO in 2020.",
            "Meridel Foods registered as Meridel Foods Pty Ltd.",
            "Meridel Foods has its head office in Vila Nova de Gaia.",
        ]), title="Meridel Foods"),
        page("https://meridel-foods.test/finance", "\n".join([
            "Meridel Foods has raised $1.2345m from angel investors.",
            "Meridel Foods raised CHF 5 million in a later round.",
        ]), title="Meridel Foods finance"),
    ],
}
EXPECTED["meridel-foods.test"] = {0: {
    "legal_name": "Meridel Foods Pty Ltd", "hq_city": "Vila Nova", "ceo": None,
    "founded_year": 1996, "headcount_range": None, "funding_total": 1234500}}

# ---------------------------------------------------------------- 7. named by domain, facts deep in a long page
COMPANIES["sablewood-logistics.test"] = {
    "names": ["Sablewood Logistics"],
    "pages": [
        page("https://sablewood-logistics.test/report", FILLER_B + "\n" + "\n".join([
            "Sablewood Logistics Ltd is the registered company behind the depot network.",
            "sablewood-logistics.test lists its head office in Den Haag.",
            "Sablewood Logistics CEO: Jonas Ek.",
            "sablewood-logistics.test was founded in 2008.",
            "Sablewood Logistics has a headcount of 10,500.",
            "Sablewood Logistics has raised 750 thousand US dollars.",
        ]), title="Sablewood Logistics annual report"),
    ],
}
EXPECTED["sablewood-logistics.test"] = {0: {
    "legal_name": "Sablewood Logistics Ltd", "hq_city": "Den Haag", "ceo": "Jonas Ek",
    "founded_year": 2008, "headcount_range": "10001+", "funding_total": 750000}}

# ---------------------------------------------------------------- 8. epochs (refresh sees new web)
COMPANIES["pivotal-reed.test"] = {
    "names": ["Pivotal Reed"],
    "pages": [
        page("https://pivotal-reed.test/", "\n".join([
            "Pivotal Reed CEO: Hana Sato.",
            "Pivotal Reed was founded in 2001.",
        ]), epochs=(0,), title="Pivotal Reed"),
        page("https://pivotal-reed.test/", "\n".join([
            "Pivotal Reed CEO: Leon Brandt.",
            "Pivotal Reed opened a new studio.",
        ]), epochs=(1,), title="Pivotal Reed"),
    ],
}
EXPECTED["pivotal-reed.test"] = {
    0: {"legal_name": None, "hq_city": None, "ceo": "Hana Sato", "founded_year": 2001,
        "headcount_range": None, "funding_total": None},
    1: {"legal_name": None, "hq_city": None, "ceo": "Leon Brandt", "founded_year": None,
        "headcount_range": None, "funding_total": None},
}

# ---------------------------------------------------------------- 9. shortest legal name, Inc. inside sentence, 3-word CEO, k scale
COMPANIES["wrenfield-audio.test"] = {
    "names": ["Wrenfield Audio"],
    "pages": [
        page("https://wrenfield-audio.test/", "\n".join([
            "Wrenfield Audio AG Holdings GmbH is the registered name on file.",
            "Wrenfield Audio, Inc. was established in 1979.",
            "Wrenfield Audio has its registered office in Zürich.",
            "Wrenfield Audio chief executive Maria Elena Costa signed the deal.",
        ]), title="Wrenfield Audio"),
        page("https://audio-trade.test/wrenfield", "\n".join([
            'Analysts wrote: "Wrenfield Audio employs 300 people." Others disagreed.',
            "Wrenfield Audio raised $850k in seed funding.",
        ]), kind="news", title="Wrenfield Audio"),
    ],
}
EXPECTED["wrenfield-audio.test"] = {0: {
    "legal_name": "Wrenfield Audio AG", "hq_city": "Zürich", "ceo": "Maria Elena Costa",
    "founded_year": 1979, "headcount_range": "201-500", "funding_total": 850000}}

# ---------------------------------------------------------------- 10. more than 10 pages: facts rank below the domain query's top 10
_FENWICK_TOPICS = [
    ("varieties", "apple varieties", "Fenwick Orchards grows heritage apple varieties on terraced slopes."),
    ("pears", "pear blocks", "Fenwick Orchards keeps its pear blocks on the cooler northern terraces."),
    ("cider", "cider pressing", "Fenwick Orchards presses its windfall fruit into cloudy cider each autumn."),
    ("bees", "pollination", "Fenwick Orchards rents hives from local beekeepers during blossom."),
    ("frost", "frost protection", "Fenwick Orchards runs wind machines on cold spring nights."),
    ("soil", "soil care", "Fenwick Orchards plants clover between rows to feed the soil."),
    ("pruning", "winter pruning", "Fenwick Orchards prunes by hand through the dormant season."),
    ("tours", "orchard tours", "Fenwick Orchards opens its lanes to visitors on blossom weekends."),
    ("shop", "farm shop", "Fenwick Orchards sells juice and dried rings at its roadside shop."),
    ("water", "irrigation", "Fenwick Orchards waters young trees with drip lines fed from a pond."),
]


def _fenwick_filler(slug, topic, lead):
    lines = [lead]
    for _ in range(3):
        lines.append(f"Read more about {topic} at fenwick-orchards.test, the home of Fenwick Orchards.")
        lines.append(f"Fenwick Orchards and fenwick-orchards.test share notes on {topic} with growers.")
    return page(f"https://fenwick-orchards.test/{slug}", "\n".join(lines),
                title=f"Fenwick Orchards fenwick-orchards.test {topic}")


COMPANIES["fenwick-orchards.test"] = {
    "names": ["Fenwick Orchards"],
    "pages": [_fenwick_filler(*t) for t in _FENWICK_TOPICS] + [
        page("https://grower-gazette.test/profiles/marchetti", "\n".join([
            "Fenwick Orchards CEO: Odile Marchetti.",
            "Fenwick Orchards was founded in 1952.",
            "Fenwick Orchards LLC is the registered company that owns the groves.",
        ]), kind="news", title="Grower profile: Odile Marchetti"),
        page("https://harvest-ledger.test/notes/hood-river", "\n".join([
            "Fenwick Orchards is headquartered in Hood River.",
            "Fenwick Orchards employs 340 people at harvest.",
            "Fenwick Orchards has raised $6M from a farm fund.",
        ]), kind="news", title="Harvest notes"),
    ],
}
EXPECTED["fenwick-orchards.test"] = {0: {
    "legal_name": "Fenwick Orchards LLC", "hq_city": "Hood River", "ceo": "Odile Marchetti",
    "founded_year": 1952, "headcount_range": "201-500", "funding_total": 6000000}}

# ================================================================ STAGE 2 companies
# Competing sources: kinds, publication times, URL ties, value ties, rendered text.
# SELECTED holds the value the selection rule picks per field, written by hand (the Analyst's
# own reading); rank.py derives the same from the pages and check_corpus.py compares them.
SELECTED: dict[str, dict] = {}
ALL = ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total"]

# ---------------------------------------------------------------- 11. every rule of the ranking
COMPANIES["harlow-instruments.test"] = {
    "names": ["Harlow Instruments"],
    "pages": [
        # own, 10:00Z. Ties with a2 on authority and instant; a2's URL is smaller, so a2 wins.
        page("https://harlow-instruments.test/about", "\n".join([
            "Dana Ruiz has led Harlow Instruments as chief executive since 2021.",
            "Harlow Instruments was founded in 2009.",
            "Harlow Instruments Ltd is the registered company behind the Harlow brand.",
        ]), kind="own", published_at="2026-01-10T10:00:00Z", title="About Harlow Instruments"),
        # filing, 12:00+02:00 = 10:00Z (same instant as a1, other offset)
        page("https://a-registry.test/harlow", "\n".join([
            "Harlow Instruments CEO: Dana Ruiz.",
            "Harlow Instruments was incorporated in 2010.",
            "Harlow Instruments plc is the legal entity on record.",
        ]), kind="filing", published_at="2026-01-10T12:00:00+02:00", title="Registry entry"),
        # news, the most recent page of all: lower authority than own/filing
        page("https://news-daily.test/harlow-ceo", "\n".join([
            "Harlow Instruments CEO: Sam Ortiz.",
        ]), kind="news", published_at="2026-03-01T00:00:00Z", title="Harlow leadership"),
        # no Kind line: aggregator (not the company's host)
        page("https://bizdata.test/harlow-instruments", "Harlow Instruments CEO: Sam Ortiz.",
             kind=None, published_at="2026-02-20T00:00:00Z", title="Harlow data sheet"),
        # unlisted Kind value: aggregator; newer than the page above
        page("https://listings.test/harlow", "Harlow Instruments CEO: Pat Quill.",
             kind="blog", published_at="2026-02-25T00:00:00Z", title="Harlow listing"),
        # recency beats URL: /contact sorts before /news but is older
        page("https://harlow-instruments.test/contact",
             "Harlow Instruments is headquartered in Leeds.",
             kind="own", published_at="2025-06-01T00:00:00Z", title="Contact"),
        page("https://harlow-instruments.test/news",
             "Harlow Instruments has its head office in York.",
             kind="own", published_at="2026-02-01T00:00:00Z", title="News"),
        # instants, not strings: b is later than a although "…T01:00:00+02:00" > "…T00:00:00Z"
        page("https://funding-wire.test/a", "Harlow Instruments raised $5M in a seed round.",
             kind="news", published_at="2026-02-20T01:00:00+02:00", title="Seed round"),
        page("https://funding-wire.test/b", "Harlow Instruments has raised $7M to date.",
             kind="news", published_at="2026-02-20T00:00:00Z", title="Raise update"),
        # no publication time (absent / not a timestamp): below every dated news page, then URL
        page("https://funding-wire.test/c", "Harlow Instruments has raised $9M.",
             kind="news", published_at=None, title="Undated raise"),
        page("https://funding-wire.test/d", "Harlow Instruments raised $3M in 2020.",
             kind="news", published_at="last Tuesday", title="Vague raise"),
        # one page, two values of one field: ranked by value (strings by code point)
        page("https://harlow-instruments.test/careers", "\n".join([
            "Harlow Instruments employs about 120 people.",
            "Harlow Instruments has 3,000 employees across sites.",
        ]), kind="own", published_at="2026-02-10T00:00:00Z", title="Careers"),
    ],
}
SELECTED["harlow-instruments.test"] = {
    "legal_name": "Harlow Instruments plc", "hq_city": "York", "ceo": "Dana Ruiz",
    "founded_year": 2010, "headcount_range": "1001-5000", "funding_total": 7000000}

# ---------------------------------------------------------------- 12. default kind from the host
COMPANIES["kestrel-optics.test"] = {
    "names": ["Kestrel Optics"],
    "pages": [
        page("https://kestrel-optics.test/a", "Kestrel Optics was founded in 2001.",
             kind=None, title="a"),                                   # own: host is the domain
        page("https://www.kestrel-optics.test/b", "Kestrel Optics was founded in 2002.",
             kind=None, title="b"),                                   # own: www. is removed
        page("https://about.kestrel-optics.test/c", "Kestrel Optics was founded in 2003.",
             kind=None, title="c"),                                   # aggregator: another host
        page("https://kestrel-profiles.test/d", "Kestrel Optics was founded in 2004.",
             kind=None, title="d"),                                   # aggregator
        page("https://kestrel-optics.test/e", "Kestrel Optics was founded in 2005.",
             kind="blog", title="e"),                                 # unlisted value: own
        page("https://other-host.test/f", "Kestrel Optics was founded in 2006.",
             kind="blog", title="f"),                                 # unlisted value: aggregator
        page("https://other-host.test/g", "Kestrel Optics was founded in 2007.",
             kind="news", title="g"),                                 # news
        page("https://other-host.test/h", "Kestrel Optics was founded in 2008.",
             kind="NEWS", title="h"),                                 # not a listed value: aggregator
        page("https://Kestrel-Optics.TEST./i", "Kestrel Optics was founded in 2009.",
             kind=None, title="i"),                                   # own: host normalised
        page("https://other-host.test/j", "Kestrel Optics was founded in 2010.",
             kind="filing", title="j"),                               # filing = own authority
    ],
}
SELECTED["kestrel-optics.test"] = {"founded_year": 2009}  # "K" (75) sorts before "k" (107)
# own+filing (published alike) by URL code point: i (K), a, e, other-host/j, www.../b; then news g; then aggregators

# ---------------------------------------------------------------- 13. publication time validity
COMPANIES["lumen-textiles.test"] = {
    "names": ["Lumen Textiles"],
    "pages": [
        page("https://lumen-textiles.test/p1", "Lumen Textiles was founded in 1991.",
             published_at="2026-01-01T00:00:00Z", title="p1"),
        page("https://lumen-textiles.test/p2", "Lumen Textiles was founded in 1992.",
             published_at="2026-01-02T00:00:00.500Z", title="p2"),
        page("https://lumen-textiles.test/p3", "Lumen Textiles was founded in 1993.",
             published_at="2026-01-03", title="p3"),                  # date only: no time
        page("https://lumen-textiles.test/p4", "Lumen Textiles was founded in 1994.",
             published_at="2026-01-04T00:00:00", title="p4"),         # no offset: no time
        page("https://lumen-textiles.test/p5", "Lumen Textiles was founded in 1995.",
             published_at="2026-02-30T00:00:00Z", title="p5"),        # no such day: no time
        page("https://lumen-textiles.test/p6", "Lumen Textiles was founded in 1996.",
             published_at="soon", title="p6"),
        page("https://lumen-textiles.test/p7", "Lumen Textiles was founded in 1997.",
             published_at=None, title="p7"),
        page("https://lumen-textiles.test/p8", "Lumen Textiles was founded in 1998.",
             published_at="2025-12-31T23:00:00-05:00", title="p8"),   # 2026-01-01T04:00Z
    ],
}
SELECTED["lumen-textiles.test"] = {"founded_year": 1992}

# ---------------------------------------------------------------- 14. known / contested / unknown, numeric tie
COMPANIES["tarn-biotech.test"] = {
    "names": ["Tarn Biotech"],
    "pages": [
        page("https://tarn-biotech.test/about", "\n".join([
            "Tarn Biotech Ltd is the registered company behind the lab.",
            "Tarn Biotech is based in Cambridge.",
            "Tarn Biotech employs about 120 people.",
            "Tarn Biotech might be founded in 2012.",
        ]), kind="own", published_at="2026-01-05T00:00:00Z", title="About Tarn Biotech"),
        page("https://tarn-registry.test/tarn", "\n".join([
            "The registered name of Tarn Biotech is Tarn Biotech Limited.",
            "Tarn Biotech is based in Cambridge.",
            "Tarn Biotech has a headcount of 150.",
        ]), kind="filing", published_at="2026-01-06T00:00:00Z", title="Registry entry"),
        page("https://tarn-news.test/n1", "\n".join([
            "Tarn Biotech has raised $9M.",
            "Tarn Biotech has raised $12M.",
        ]), kind="news", published_at="2026-02-01T00:00:00Z", title="Tarn funding"),
        page("https://tarn-news.test/n2", "Tarn Biotech has raised US$ 9 million.",
             kind="news", published_at="2026-01-20T00:00:00Z", title="Tarn funding, earlier"),
    ],
}
SELECTED["tarn-biotech.test"] = {
    "legal_name": "Tarn Biotech Limited", "hq_city": "Cambridge", "ceo": None,
    "founded_year": None, "headcount_range": "51-200", "funding_total": 9000000}

# ---------------------------------------------------------------- 15. browser text, research-cited pages
COMPANIES["vesper-lanterns.test"] = {
    "names": ["Vesper Lanterns"],
    "pages": [
        page("https://vesper-lanterns.test/about", "\n".join([
            "Vesper Lanterns makes hand-blown glass lanterns.",
            "Vesper Lanterns is headquartered in Murano.",
        ]), static_text="\n".join([
            "Vesper Lanterns makes hand-blown glass lanterns.",
            "Vesper Lanterns is headquartered in Venice.",
            "Please enable JavaScript to see the latest details.",
        ]), published_at="2026-01-12T00:00:00Z", title="About Vesper Lanterns"),
        page("https://vesper-lanterns.test/team", "\n".join([
            "Vesper Lanterns CEO: Lia Moretti.",
            "Vesper Lanterns employs 45 people.",
        ]), static_text="The team page is built in your browser.",
            published_at="2026-01-12T00:00:00Z", title="Team"),
        page("https://vesper-lanterns.test/investors", "\n".join([
            "Vesper Lanterns has raised $2M from private investors.",
            "Vesper Lanterns was founded in 1998.",
        ]), static_text="Vesper Lanterns was founded in 1989.",
            searchable=False, published_at="2026-01-12T00:00:00Z", title="Investors"),
        page("https://vesper-lanterns.test/press", "\n".join([
            "Vesper Lanterns might raise $20M next year.",
            "Vesper Lanterns has its head office in Murano.",
        ]), static_text="Vesper Lanterns has its head office in Venice.",
            searchable=False, published_at="2026-01-13T00:00:00Z", title="Press"),
    ],
    # The mock answers one claim per field (the first entry). funding_total therefore cites the
    # non-searchable /press with an UNSUPPORTED claim (negated); /investors is reached through the
    # founded_year claim. A build must read /press although its claim is not a candidate.
    "research": {"nimble": {"0": [
        {"field": "funding_total", "value": 20000000,
         "url": "https://vesper-lanterns.test/press",
         "excerpt": "Vesper Lanterns might raise $20M next year."},
        {"field": "founded_year", "value": 1998,
         "url": "https://vesper-lanterns.test/investors",
         "excerpt": "Vesper Lanterns was founded in 1998."},
        {"field": "ceo", "value": "Lia Moretti", "url": "https://vesper-lanterns.test/team",
         "excerpt": "Vesper Lanterns CEO: Lia Moretti."},
        {"field": "hq_city", "value": "Venice", "url": "https://vesper-lanterns.test/about",
         "excerpt": "Vesper Lanterns is headquartered in Venice."},
    ]}},
}
SELECTED["vesper-lanterns.test"] = {
    "legal_name": None, "hq_city": "Murano", "ceo": "Lia Moretti", "founded_year": 1998,
    "headcount_range": "11-50", "funding_total": 2000000}
# Values only the static (extract-served) text supports: a candidate must not carry them.
STALE = {"vesper-lanterns.test": {"hq_city": {"Venice"}, "founded_year": {1989}}}


EXPECTED["harlow-instruments.test"] = {0: {
    "legal_name": {"Harlow Instruments Ltd", "Harlow Instruments plc"}, "hq_city": {"Leeds", "York"},
    "ceo": {"Dana Ruiz", "Sam Ortiz", "Pat Quill"}, "founded_year": {2009, 2010},
    "headcount_range": {"51-200", "1001-5000"}, "funding_total": {5000000, 7000000, 9000000, 3000000}}}
EXPECTED["kestrel-optics.test"] = {0: {
    **{f: None for f in ALL}, "founded_year": set(range(2001, 2011))}}
EXPECTED["lumen-textiles.test"] = {0: {
    **{f: None for f in ALL}, "founded_year": set(range(1991, 1999))}}
EXPECTED["tarn-biotech.test"] = {0: {
    "legal_name": {"Tarn Biotech Ltd", "Tarn Biotech Limited"}, "hq_city": "Cambridge",
    "ceo": None, "founded_year": None, "headcount_range": "51-200",
    "funding_total": {9000000, 12000000}}}
EXPECTED["vesper-lanterns.test"] = {0: {
    "legal_name": None, "hq_city": "Murano", "ceo": "Lia Moretti", "founded_year": 1998,
    "headcount_range": "11-50", "funding_total": 2000000}}
# Stage 1 conflicts now resolve by the selection rule (own page beats news page).
SELECTED["ledgerline-partners.test"] = {"ceo": "Ines Varga", "founded_year": 2003}


def selected(domain: str, field: str, epoch: int = 0):
    """The value the selection rule picks for the field (hand-written; single-valued fields
    use EXPECTED)."""
    sel = SELECTED.get(domain, {})
    if field in sel:
        return sel[field]
    e = EXPECTED[domain][epoch][field]
    assert not isinstance(e, set), (domain, field)
    return e

# A domain with no page anywhere in the corpus: the build completes ready with every field unknown.
UNKNOWN_DOMAIN = "nowhere-at-all.test"
EXPECTED[UNKNOWN_DOMAIN] = {0: {f: None for f in ["legal_name", "hq_city", "ceo", "founded_year",
                                                   "headcount_range", "funding_total"]}}

TRAITS = {"seed": 4242, "providers": {"nimble": {"noise": 0.0, "rate_limit": 0.3},
                                      "tavily": {"noise": 0.0, "rate_limit": 0.3}}}


def page_text(domain: str, url: str, epoch: int = 0) -> str | None:
    for p in COMPANIES.get(domain, {}).get("pages", []):
        if p["url"] == url and epoch in p["epochs"]:
            return p["text"]
    return None


def all_page_texts(epoch: int | None = None) -> dict[str, list[str]]:
    """url -> prose texts (any epoch unless given)."""
    out: dict[str, list[str]] = {}
    for c in COMPANIES.values():
        for p in c["pages"]:
            if epoch is None or epoch in p["epochs"]:
                out.setdefault(p["url"], []).append(p["text"])
    return out


def write():
    os.makedirs(CORPUS_DIR, exist_ok=True)
    for domain, c in COMPANIES.items():
        doc = {"domain": domain, "names": c["names"], "pages": c["pages"],
               "research": c.get("research", {"nimble": {}})}
        with open(os.path.join(CORPUS_DIR, f"{domain}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.write("\n")
    with open(os.path.join(CORPUS_DIR, "traits.json"), "w", encoding="utf-8") as f:
        json.dump(TRAITS, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    write()
    print(f"wrote {len(COMPANIES)} companies to {CORPUS_DIR}")
