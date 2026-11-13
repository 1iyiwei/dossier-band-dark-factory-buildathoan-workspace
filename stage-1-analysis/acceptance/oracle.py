"""Independent reference implementation of stage-1 Appendix A ("when an excerpt supports a value")
and of the §4 page model (header lines vs prose).

Written by the Analyst from the specification text alone. Used by the acceptance tests to
judge every citation a service returns, and by check_corpus.py to verify the analyst corpus.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

FIELDS = ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total"]

HEADCOUNT_RANGES = [
    (1, 10, "1-10"), (11, 50, "11-50"), (51, 200, "51-200"), (201, 500, "201-500"),
    (501, 1000, "501-1000"), (1001, 5000, "1001-5000"), (5001, 10000, "5001-10000"),
    (10001, None, "10001+"),
]
HEADCOUNT_VALUES = [r[2] for r in HEADCOUNT_RANGES]

SUFFIXES = ["Inc.", "Corp.", "LLC", "LLP", "L.P.", "Ltd", "Limited", "Pty Ltd", "plc", "PLC",
            "GmbH", "AG", "KG", "SE", "AS", "A/S", "ASA", "AB", "Oy", "Oyj", "B.V.", "N.V.",
            "S.A.", "S.A.S.", "S.L.", "S.r.l.", "S.p.A.", "s.r.o.", "a.s.", "K.K."]

STATEMENT = {
    "legal_name": ["legal name", "registered name", "registered as", "registered company",
                   "legal entity", "name of record"],
    "hq_city": ["headquartered in", "headquarters in", "head office in", "based in",
                "registered office in", "registered seat in"],
    "ceo": ["chief executive officer", "chief executive", "CEO"],
    "founded_year": ["founded", "founding", "established", "incorporated"],
    "headcount_range": ["employs", "employees", "staff", "people", "headcount", "workforce"],
    "funding_total": ["raised", "funding", "invested", "investment"],
}

NEGATIONS = ["in talks to", "plans to", "planning to", "wants to", "expects to", "hopes to",
             "aims to", "seeking", "could", "would", "might", "reportedly", "rumoured", "former",
             "formerly", "will become", "not"]

CLOSERS = "\"”’)"


def is_an(c: str) -> bool:
    return c.isalpha() or c.isdigit()


def collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------- page model (§4 Pages)
_HEADER_LINE = re.compile(r"^[A-Z][a-z]+(?:-[A-Z][a-z]+)*: ")


def split_header(text: str) -> tuple[str, str]:
    """Return (header, prose) of a served page text."""
    lines = text.split("\n")
    if not lines or not _HEADER_LINE.match(lines[0]):
        return "", text
    for i, line in enumerate(lines):
        if line.strip() == "":
            return "\n".join(lines[:i]), "\n".join(lines[i + 1:])
    return text, ""


def prose_of(text: str) -> str:
    return split_header(text)[1]


# ---------------------------------------------------------------- A.1 sentences
def _ends_suffix(line: str, i: int) -> bool:
    for suf in SUFFIXES:
        if not suf.endswith("."):
            continue
        k = i + 1 - len(suf)
        if k >= 0 and line[k:i + 1] == suf and (k == 0 or not is_an(line[k - 1])):
            return True
    return False


def split_line(line: str) -> list[str]:
    out, start, i, n = [], 0, 0, len(line)
    while i < n:
        c = line[i]
        if c in ".!?":
            j = i + 1
            while j < n and line[j] in CLOSERS:
                j += 1
            if (j == n or line[j].isspace()) and not (c == "." and _ends_suffix(line, i)):
                out.append(line[start:j])
                start = j
                i = j
                continue
        i += 1
    out.append(line[start:])
    return [s.strip() for s in out if s.strip()]


def sentences(prose: str) -> list[str]:
    res = []
    for line in prose.splitlines():
        res.extend(split_line(line))
    return res


def is_single_sentence(excerpt: str) -> bool:
    return len(split_line(collapse(excerpt))) == 1


# ---------------------------------------------------------------- matching helpers
def find_word(s: str, phrase: str) -> list[tuple[int, int]]:
    """Case-insensitive whole-word occurrences of phrase in s."""
    out = []
    ls, lp = s.lower(), phrase.lower()
    start = 0
    while True:
        k = ls.find(lp, start)
        if k < 0:
            return out
        e = k + len(lp)
        if (k == 0 or not is_an(s[k - 1])) and (e == len(s) or not is_an(s[e])):
            out.append((k, e))
        start = k + 1


def company_name(domain: str) -> str:
    return domain.split(".")[0].replace("-", " ")


def _letter_run(s: str, p: int) -> int:
    q = p
    while q < len(s) and s[q].isalpha():
        q += 1
    return q


def _word_at(s: str, p: int, allow_upper: bool) -> int | None:
    """End index of a capitalised (or uppercase) word starting exactly at p, else None."""
    if p >= len(s) or not s[p].isalpha():
        return None
    if p > 0 and is_an(s[p - 1]):
        return None
    q = _letter_run(s, p)
    if q < len(s) and s[q].isdigit():
        return None
    w = s[p:q]
    if len(w) >= 2 and w[0].isupper() and all(ch.islower() for ch in w[1:]):
        return q
    if allow_upper and len(w) >= 2 and all(ch.isupper() for ch in w):
        return q
    return None


def capitalised_words(s: str) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(s):
        if s[i].isalpha() and (i == 0 or not is_an(s[i - 1])):
            e = _word_at(s, i, allow_upper=False)
            q = _letter_run(s, i)
            if e is not None:
                out.append((i, e))
            i = q
        else:
            i += 1
    return out


# ---------------------------------------------------------------- numbers and amounts (A.4)
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_AMOUNT_1 = re.compile(
    r"(?<![^\W_])(?:US\$|\$|USD) ?(" + _NUM + r")(?![.,]?\d)"
    r"(?:(mn|bn|k|m)|( thousand| million| billion))?(?![^\W_])", re.IGNORECASE)
_AMOUNT_2 = re.compile(
    r"(?<![^\W_])(?<!\d[.,])(" + _NUM + r")(?![.,]?\d)( thousand| million| billion)?"
    r" (?:dollars|US dollars)(?![^\W_])", re.IGNORECASE)
_SCALE = {"k": 1000, "thousand": 1000, "m": 10**6, "mn": 10**6, "million": 10**6,
          "bn": 10**9, "billion": 10**9}


def amounts(s: str) -> list[tuple[int, int, int | None]]:
    """(start, end, whole-dollar value or None) for each amount in s."""
    out = []
    for rx in (_AMOUNT_1, _AMOUNT_2):
        for m in rx.finditer(s):
            num = Decimal(m.group(1).replace(",", ""))
            scale_txt = None
            for g in m.groups()[1:]:
                if g:
                    scale_txt = g.strip().lower()
            mult = _SCALE.get(scale_txt, 1) if scale_txt else 1
            v = num * mult
            val = int(v) if v == v.to_integral_value() else None
            out.append((m.start(), m.end(), val))
    return out


_NUM_TOKEN = re.compile(r"\d+(?:[.,]\d+)*")
_NUM_VALID = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def numbers(s: str) -> list[tuple[int, int, str]]:
    """Numbers (A.4) not adjacent to a letter and not part of an amount."""
    spans = [(a, b) for a, b, _ in amounts(s)]
    out = []
    for m in _NUM_TOKEN.finditer(s):
        a, b = m.span()
        tok = m.group(0)
        if (a > 0 and s[a - 1].isalpha()) or (b < len(s) and s[b].isalpha()):
            continue
        if not _NUM_VALID.fullmatch(tok):
            continue
        if any(x <= a and b <= y for x, y in spans):
            continue
        out.append((a, b, tok))
    return out


def headcount_range_of(n: int) -> str | None:
    for lo, hi, label in HEADCOUNT_RANGES:
        if n >= lo and (hi is None or n <= hi):
            return label
    return None


# ---------------------------------------------------------------- per-field value formats
def _legal_values(s: str, domain: str) -> list:
    vals = []
    occ = find_word(s, company_name(domain)) + find_word(s, domain)
    for start, e in occ:
        while True:
            best = None
            for suf in SUFFIXES:
                for sep in (", ", " "):
                    t = sep + suf
                    if s.startswith(t, e):
                        end = e + len(t)
                        if end == len(s) or not is_an(s[end]):
                            best = end if best is None else min(best, end)
            if best is not None:
                vals.append(s[start:best])
                break
            if e < len(s) and s[e] == " ":
                w = _word_at(s, e + 1, allow_upper=True)
                if w is not None:
                    e = w
                    continue
            break
    return vals


def _hq_values(s: str) -> list:
    vals = []
    for ph in STATEMENT["hq_city"]:
        for _, en in find_word(s, ph):
            if en >= len(s) or s[en] != " ":
                continue
            p = en + 1
            e = _word_at(s, p, allow_upper=False)
            if e is None:
                continue
            # not part of a longer run: the text just before p must not be a capitalised word
            k = p - 1
            if k > 0 and s[k] in " -":
                j = k
                while j > 0 and s[j - 1].isalpha():
                    j -= 1
                if j < k and _word_at(s, j, allow_upper=False) == k:
                    continue
            while e < len(s) and s[e] in " -":
                nxt = _word_at(s, e + 1, allow_upper=False)
                if nxt is None:
                    break
                e = nxt
            vals.append(s[p:e])
    return vals


def _ceo_values(s: str, domain: str) -> list:
    spans = find_word(s, company_name(domain))
    for ph in STATEMENT["ceo"]:
        spans += find_word(s, ph)
    chars = list(s)
    for a, b in spans:
        for k in range(a, b):
            chars[k] = "\x00"
    t = "".join(chars)
    words = capitalised_words(t)
    vals, run = [], []
    for w in words:
        if run and t[run[-1][1]:w[0]] == " ":
            run.append(w)
        else:
            if run:
                vals.append(run)
            run = [w]
    if run:
        vals.append(run)
    return [t[r[0][0]:r[-1][1]] for r in vals if 2 <= len(r) <= 3]


def field_values(s: str, field: str, domain: str) -> list:
    if field == "legal_name":
        return _legal_values(s, domain)
    if field == "hq_city":
        return _hq_values(s)
    if field == "ceo":
        return _ceo_values(s, domain)
    if field == "founded_year":
        return [int(t) for a, b, t in numbers(s) if re.fullmatch(r"\d{4}", t) and 1800 <= int(t) <= 2099]
    if field == "headcount_range":
        out = []
        for a, b, t in numbers(s):
            if "." in t:
                continue
            n = int(t.replace(",", ""))
            if n >= 1:
                out.append(headcount_range_of(n))
        return out
    if field == "funding_total":
        return [v for _, _, v in amounts(s)]  # None = amount that is not whole dollars
    raise ValueError(field)


# ---------------------------------------------------------------- A.2 the rule
def supported_value(excerpt: str, field: str, domain: str):
    """The value V the excerpt supports for field of the company at domain, or None."""
    s = collapse(excerpt).strip()
    if not s or not is_single_sentence(s):
        return None
    if not (find_word(s, company_name(domain)) or find_word(s, domain)):
        return None
    if not any(find_word(s, p) for p in STATEMENT[field]):
        return None
    if any(find_word(s, n) for n in NEGATIONS):
        return None
    vals = field_values(s, field, domain)
    if not vals or any(v is None for v in vals) or len(set(vals)) != 1:
        return None
    return vals[0]


def supports(excerpt: str, field: str, value, domain: str) -> bool:
    v = supported_value(excerpt, field, domain)
    return v is not None and v == value and type(v) is type(value)
