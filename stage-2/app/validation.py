"""Input rules shared by the endpoints: domains (§4), timestamps (§3.4), emails, paging (§5)."""
from __future__ import annotations

import re
from datetime import datetime

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
_DIGITS = re.compile(r"[0-9]+")


class Invalid(Exception):
    """422 validation_failed."""


class WrongType(Exception):
    """400 malformed_request: a field of the wrong JSON type."""


def normalise_host(raw: str) -> str:
    """Surrounding whitespace removed, lowercased, one trailing `.` and one leading `www.` removed (§4)."""
    domain = raw.strip().lower()
    if domain.endswith("."):
        domain = domain[:-1]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def normalise_domain(raw: str) -> str:
    """The normalised domain, or Invalid when it is not a valid host name."""
    domain = normalise_host(raw)
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels):
        raise Invalid("domain is not a valid host name")
    return domain


def parse_timestamp(raw) -> datetime:
    """An RFC 3339 timestamp with an explicit offset."""
    if not isinstance(raw, str):
        raise WrongType("timestamp must be a string")
    if not _RFC3339.fullmatch(raw):
        raise Invalid("timestamp must be RFC 3339 with an explicit offset")
    try:
        return datetime.fromisoformat(raw.replace("z", "Z").replace("t", "T"))
    except ValueError as exc:
        raise Invalid(str(exc)) from exc


def format_timestamp(value: datetime) -> str:
    return value.isoformat()


def is_email(value: str) -> bool:
    return bool(_EMAIL.fullmatch(value))


def require_string(body: dict, name: str) -> str:
    if name not in body or body[name] is None:
        raise Invalid(f"{name} is required")
    value = body[name]
    if not isinstance(value, str):
        raise WrongType(f"{name} must be a string")
    return value


def paging_int(raw: str | None, default: int, low: int, high: int | None) -> int:
    """An integer query parameter written as plain decimal digits, within range."""
    if raw is None:
        return default
    if not _DIGITS.fullmatch(raw):
        raise Invalid("must be written as decimal digits")
    value = int(raw)
    if value < low or (high is not None and value > high):
        raise Invalid("out of range")
    return value
