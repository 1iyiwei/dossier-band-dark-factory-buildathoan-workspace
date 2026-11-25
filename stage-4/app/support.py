"""Appendix A: when an excerpt supports a value for a field of a company.

Everything here is deterministic and provider-agnostic. `supported_value` is the
single entry point the builder uses to decide whether an excerpt may be cited
for a field, and with which value.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

FIELDS = ("legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total")
TITLES = ("cfo", "coo", "cto")          # the executives field's members, in this order (stage 3)
ALL_FIELDS = FIELDS + ("executives", "investors")   # the eight fields (stage 4)
INVESTOR_LAST_WORDS = ("Ventures", "Capital", "Partners", "Fund", "Investments", "Holdings", "Equity")

HEADCOUNT_RANGES = (
    (1, 10, "1-10"),
    (11, 50, "11-50"),
    (51, 200, "51-200"),
    (201, 500, "201-500"),
    (501, 1000, "501-1000"),
    (1001, 5000, "1001-5000"),
    (5001, 10000, "5001-10000"),
    (10001, None, "10001+"),
)
HEADCOUNT_VALUES = tuple(label for _, _, label in HEADCOUNT_RANGES)

STATEMENT_PHRASES = {
    "legal_name": ("legal name", "registered name", "registered as", "registered company",
                   "legal entity", "name of record"),
    "hq_city": ("headquartered in", "headquarters in", "head office in", "based in",
                "registered office in", "registered seat in"),
    "ceo": ("chief executive officer", "chief executive", "CEO"),
    "founded_year": ("founded", "founding", "established", "incorporated"),
    "headcount_range": ("employs", "employees", "staff", "people", "headcount", "workforce"),
    "funding_total": ("raised", "funding", "invested", "investment"),
    "cfo": ("chief financial officer", "CFO"),
    "coo": ("chief operating officer", "COO"),
    "cto": ("chief technology officer", "CTO"),
    "investors": ("investor", "investors", "led by", "backed by", "participated"),
}

NEGATING_PHRASES = ("in talks to", "plans to", "planning to", "wants to", "expects to",
                    "hopes to", "aims to", "seeking", "could", "would", "might", "reportedly",
                    "rumoured", "former", "formerly", "will become", "not")

LEGAL_SUFFIXES = ("Inc.", "Corp.", "LLC", "LLP", "L.P.", "Ltd", "Limited", "Pty Ltd", "plc", "PLC",
                  "GmbH", "AG", "KG", "SE", "AS", "A/S", "ASA", "AB", "Oy", "Oyj", "B.V.", "N.V.",
                  "S.A.", "S.A.S.", "S.L.", "S.r.l.", "S.p.A.", "s.r.o.", "a.s.", "K.K.")
_DOT_SUFFIXES = tuple(s for s in LEGAL_SUFFIXES if s.endswith("."))

_SENTENCE_CLOSERS = "\"”’)"
_LINE_BREAK = re.compile(r"\r\n|\n|\r")
_WHITESPACE = re.compile(r"\s+")

# A number: digits, optionally grouped by `,` in threes, optionally a decimal part.
_NUMBER_CANDIDATE = re.compile(r"[0-9]+(?:[.,][0-9]+)*")
_VALID_NUMBER = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?")
_NUM = r"(?<![0-9])(?<![0-9][.,])(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?![0-9]|[.,][0-9])"
_AMOUNT = re.compile(
    r"(?<![^\W_])(?:"
    r"(?:US\$|USD|\$) ?(?P<a_num>" + _NUM + r")(?:(?P<a_suffix>mn|bn|k|m)|(?: (?P<a_word>thousand|million|billion)))?"
    r"|"
    r"(?P<b_num>" + _NUM + r")(?: (?P<b_word>thousand|million|billion))? (?:US dollars|dollars)"
    r")(?![^\W_])",
    re.IGNORECASE,
)
_SCALES = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000,
           "bn": 1_000_000_000, "billion": 1_000_000_000}


def collapse_whitespace(text: str) -> str:
    """Every run of whitespace written as one space, without surrounding whitespace."""
    return _WHITESPACE.sub(" ", text).strip()


def company_name(domain: str) -> str:
    """The first label of the domain with each `-` read as a space."""
    return domain.split(".", 1)[0].replace("-", " ")


# ---------------------------------------------------------------- A.1 sentences

def _ends_with_dot_suffix(line: str, dot_index: int) -> bool:
    """Whether the `.` at dot_index ends a legal-form suffix written as a whole word."""
    for suffix in _DOT_SUFFIXES:
        start = dot_index - len(suffix) + 1
        if start < 0 or line[start:dot_index + 1] != suffix:
            continue
        if start == 0 or not line[start - 1].isalnum():
            return True
    return False


def split_line(line: str) -> list[str]:
    """The sentences of one line (A.1)."""
    sentences: list[str] = []
    start = 0
    i = 0
    n = len(line)
    while i < n:
        char = line[i]
        if char in ".!?":
            j = i + 1
            while j < n and line[j] in _SENTENCE_CLOSERS:
                j += 1
            if j < n and line[j].isspace() and not (char == "." and _ends_with_dot_suffix(line, i)):
                sentence = line[start:j].strip()
                if sentence:
                    sentences.append(sentence)
                start = j
                i = j
                continue
        i += 1
    tail = line[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def split_sentences(text: str) -> list[str]:
    """The sentences of a prose text: split into lines, then each line into sentences."""
    sentences: list[str] = []
    for line in _LINE_BREAK.split(text):
        sentences.extend(split_line(line))
    return sentences


def is_single_sentence(excerpt: str) -> bool:
    return len(split_line(collapse_whitespace(excerpt))) == 1


# ---------------------------------------------------------------- matching helpers

def _phrase_pattern(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![^\W_])" + re.escape(phrase) + r"(?![^\W_])", re.IGNORECASE)


_STATEMENT_PATTERNS = {field: [_phrase_pattern(p) for p in phrases]
                       for field, phrases in STATEMENT_PHRASES.items()}
_NEGATING_PATTERNS = [_phrase_pattern(p) for p in NEGATING_PHRASES]


def _contains(pattern: re.Pattern, text: str) -> bool:
    return pattern.search(text) is not None


def _company_patterns(domain: str) -> list[re.Pattern]:
    return [_phrase_pattern(domain), _phrase_pattern(company_name(domain))]


def names_company(text: str, domain: str) -> bool:
    return any(_contains(p, text) for p in _company_patterns(domain))


class _Token:
    """A maximal run of letters and digits."""
    __slots__ = ("start", "end", "text")

    def __init__(self, start: int, end: int, text: str):
        self.start, self.end, self.text = start, end, text

    @property
    def capitalised(self) -> bool:
        t = self.text
        return len(t) >= 2 and t[0].isupper() and all(c.islower() for c in t[1:])

    @property
    def uppercase(self) -> bool:
        t = self.text
        return len(t) >= 2 and all(c.isupper() for c in t)


def _tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isalnum():
            j = i
            while j < n and text[j].isalnum():
                j += 1
            tokens.append(_Token(i, j, text[i:j]))
            i = j
        else:
            i += 1
    return tokens


# ---------------------------------------------------------------- A.4 value formats

def _amounts(text: str) -> list[tuple[int, int, int | None]]:
    """Every amount as (start, end, whole-dollar value or None when not whole)."""
    found = []
    for match in _AMOUNT.finditer(text):
        number = match.group("a_num") or match.group("b_num")
        scale_word = (match.group("a_suffix") or match.group("a_word") or match.group("b_word") or "").lower()
        try:
            value = Decimal(number.replace(",", "")) * _SCALES.get(scale_word, 1)
        except InvalidOperation:
            continue
        whole = int(value) if value == value.to_integral_value() else None
        found.append((match.start(), match.end(), whole))
    return found


def _numbers(text: str, amounts) -> list[str]:
    """Every number (A.4) that is not part of an amount, as written."""
    numbers = []
    for match in _NUMBER_CANDIDATE.finditer(text):
        start, end = match.span()
        written = match.group()
        if not _VALID_NUMBER.fullmatch(written):
            continue
        if (start > 0 and text[start - 1].isalpha()) or (end < len(text) and text[end].isalpha()):
            continue
        if any(a_start < end and start < a_end for a_start, a_end, _ in amounts):
            continue
        numbers.append(written)
    return numbers


def headcount_label(count: int) -> str | None:
    for low, high, label in HEADCOUNT_RANGES:
        if count >= low and (high is None or count <= high):
            return label
    return None


def _legal_names(text: str, domain: str) -> list[str]:
    tokens_by_start = {t.start: t for t in _tokens(text)}
    values = []
    n = len(text)
    for pattern in _company_patterns(domain):
        for match in pattern.finditer(text):
            start, pos = match.start(), match.end()
            ends = []
            while pos <= n:
                for gap in (", ", " "):
                    if text.startswith(gap, pos):
                        at = pos + len(gap)
                        for suffix in LEGAL_SUFFIXES:
                            stop = at + len(suffix)
                            if text.startswith(suffix, at) and (stop == n or not text[stop].isalnum()):
                                ends.append(stop)
                if pos < n and text[pos] == " ":
                    word = tokens_by_start.get(pos + 1)
                    if word is not None and (word.capitalised or word.uppercase):
                        pos = word.end
                        continue
                break
            if ends:
                values.append(text[start:min(ends)])
    return values


def _cities(text: str) -> list[str]:
    tokens = _tokens(text)
    by_start = {t.start: t for t in tokens}
    by_end = {t.end: t for t in tokens}
    values = []
    for pattern in _STATEMENT_PATTERNS["hq_city"]:
        for match in pattern.finditer(text):
            end = match.end()
            if not text.startswith(" ", end):
                continue
            first = by_start.get(end + 1)
            if first is None or not first.capitalised:
                continue
            before = by_end.get(end)
            if before is not None and before.capitalised:
                continue  # the place name would be part of a longer run
            last = first
            while True:
                joint = last.end
                if joint < len(text) and text[joint] in " -":
                    nxt = by_start.get(joint + 1)
                    if nxt is not None and nxt.capitalised:
                        last = nxt
                        continue
                break
            values.append(text[first.start:last.end])
    return values


def _person_names(text: str, domain: str, title: str) -> list[str]:
    removed: list[tuple[int, int]] = []
    for pattern in [_phrase_pattern(company_name(domain)), *_STATEMENT_PATTERNS[title]]:
        removed.extend(m.span() for m in pattern.finditer(text))

    def is_removed(token: _Token) -> bool:
        return any(s < token.end and token.start < e for s, e in removed)

    values = []
    run: list[_Token] = []

    def flush():
        if 2 <= len(run) <= 3:
            values.append(text[run[0].start:run[-1].end])
        run.clear()

    for token in _tokens(text):
        if not token.capitalised or is_removed(token):
            flush()
            continue
        if run and text[run[-1].end:token.start] != " ":
            flush()
        run.append(token)
    flush()
    return values


def _investor_names(text: str, domain: str) -> list[str]:
    """The investor names of an excerpt (stage 4: Investors), in the order written, each once."""
    removed: list[tuple[int, int]] = []
    for pattern in [_phrase_pattern(company_name(domain)), *_STATEMENT_PATTERNS["investors"]]:
        removed.extend(m.span() for m in pattern.finditer(text))
    after_lead = {m.end() + 1 for pattern in _STATEMENT_PATTERNS["investors"][2:4]
                  for m in pattern.finditer(text) if text.startswith(" ", m.end())}
    has_amount = bool(_amounts(text))

    def is_removed(token: _Token) -> bool:
        return any(s < token.end and token.start < e for s, e in removed)

    names: list[str] = []
    run: list[_Token] = []

    def flush():
        if run:
            last = run[-1].text
            named = len(run) >= 2 and last in INVESTOR_LAST_WORDS
            if (named or (has_amount and run[0].start in after_lead)) and \
                    (name := text[run[0].start:run[-1].end]) not in names:
                names.append(name)
        run.clear()

    for token in _tokens(text):
        if not token.capitalised or is_removed(token):
            flush()
            continue
        if run and text[run[-1].end:token.start] != " ":
            flush()
        run.append(token)
    flush()
    return names


def values_in_format(field: str, text: str, domain: str) -> list:
    """Every value in the field's format that the text contains, normalised (A.5)."""
    if field == "legal_name":
        return _legal_names(text, domain)
    if field == "hq_city":
        return _cities(text)
    if field == "ceo" or field in TITLES:
        return _person_names(text, domain, field)
    amounts = _amounts(text)
    if field == "funding_total":
        return [value for _, _, value in amounts if value is not None]
    numbers = _numbers(text, amounts)
    if field == "founded_year":
        return [int(n) for n in numbers if re.fullmatch(r"[0-9]{4}", n) and 1800 <= int(n) <= 2099]
    if field == "headcount_range":
        labels = []
        for written in numbers:
            if "." in written:
                continue
            count = int(written.replace(",", ""))
            if count >= 1:
                labels.append(headcount_label(count))
        return labels
    raise ValueError(f"unknown field {field}")


# ---------------------------------------------------------------- A.2 the rule

def supported_value(excerpt: str, field: str, domain: str):
    """The value the excerpt supports for the field of the company, or None."""
    text = collapse_whitespace(excerpt)
    if not text or len(split_line(text)) != 1:
        return None
    if not names_company(text, domain):
        return None
    if not any(_contains(p, text) for p in _STATEMENT_PATTERNS[field]):
        return None
    if any(_contains(p, text) for p in _NEGATING_PATTERNS):
        return None
    values = values_in_format(field, text, domain)
    if not values or any(v != values[0] for v in values):
        return None
    return values[0]


def supported_investors(excerpt: str, domain: str) -> list[str]:
    """Every investor name the excerpt supports (stage 4: Investors)."""
    text = collapse_whitespace(excerpt)
    if not text or len(split_line(text)) != 1 or not names_company(text, domain):
        return []
    if not any(_contains(p, text) for p in _STATEMENT_PATTERNS["investors"]):
        return []
    if any(_contains(p, text) for p in _NEGATING_PATTERNS):
        return []
    return _investor_names(text, domain)


def supported_values(excerpt: str, domain: str) -> dict:
    """Every field the excerpt supports, with its value."""
    result = {}
    for field in FIELDS:
        value = supported_value(excerpt, field, domain)
        if value is not None:
            result[field] = value
    return result


def supported_titles(excerpt: str, domain: str) -> dict:
    """Every executive title the excerpt supports, with the person's name (stage 3: Executives)."""
    result = {}
    for title in TITLES:
        value = supported_value(excerpt, title, domain)
        if value is not None:
            result[title] = value
    return result


def normalise_claim(field: str, claim):
    """A research answer's claimed value in the API's form, or None when it has none."""
    if claim is None or isinstance(claim, bool):
        return None
    if field in ("legal_name", "hq_city", "ceo"):
        return (claim.strip() or None) if isinstance(claim, str) else None
    if field == "headcount_range":
        if isinstance(claim, str) and claim.strip() in HEADCOUNT_VALUES:
            return claim.strip()
        if isinstance(claim, int):
            return headcount_label(claim)
        if isinstance(claim, str):
            labels = values_in_format("headcount_range", claim, "x.invalid")
            return labels[0] if labels and all(v == labels[0] for v in labels) else None
        return None
    if isinstance(claim, int):
        return claim
    if isinstance(claim, float):
        return int(claim) if claim.is_integer() else None
    if isinstance(claim, str):
        text = claim.strip()
        if re.fullmatch(r"[0-9]+", text):
            return int(text)
        if field == "funding_total":
            amounts = [v for _, _, v in _amounts(text) if v is not None]
            return amounts[0] if len(amounts) == 1 else None
    return None
