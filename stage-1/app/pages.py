"""Page text: header lines and prose (§4 Pages), and the citable sentences of the prose."""
from __future__ import annotations

import re

from .support import collapse_whitespace, split_sentences

_HEADER_LINE = re.compile(r"[A-Z][a-z]+(?:-[A-Z][a-z]+)*:(?: |$)")
_LINE_BREAK = re.compile(r"\r\n|\n|\r")

MAX_EXCERPT = 500


def prose_of(text: str) -> str:
    """The page's prose: everything after the header, or the whole text when it has none."""
    lines = _LINE_BREAK.split(text)
    if not lines or not _HEADER_LINE.match(lines[0]):
        return text
    for index, line in enumerate(lines):
        if line.strip() == "":
            return "\n".join(lines[index + 1:])
    return ""


def citable_sentences(prose: str, *, drop_last: bool = False) -> list[str]:
    """The prose's sentences, whitespace collapsed, that fit in a citation.

    drop_last discards the final sentence, for a snippet whose end may be cut off.
    """
    sentences = split_sentences(prose)
    if drop_last and sentences:
        sentences = sentences[:-1]
    result = []
    for sentence in sentences:
        excerpt = collapse_whitespace(sentence)
        if 1 <= len(excerpt) <= MAX_EXCERPT:
            result.append(excerpt)
    return result


def looks_like_header_line(text: str) -> bool:
    """Whether the text has the form of a header line (`Name: value`)."""
    return bool(_HEADER_LINE.match(text.strip()))


def appears_in(excerpt: str, prose: str) -> bool:
    """Whether the excerpt is copied from the prose, up to runs of whitespace."""
    return collapse_whitespace(excerpt) in collapse_whitespace(prose)
