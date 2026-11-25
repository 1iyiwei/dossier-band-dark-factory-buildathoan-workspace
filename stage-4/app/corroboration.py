"""Corroboration (stage 4: Origins): the keys `origins`, `corroborated` and `corroborated_since` of a field.

A field's members are the selected value of a scalar field, each (title, name) of `executives`
and each name of `investors`. A member's **standing origins** are the origins of its candidates
that the ready builds since it last became a member have gathered; `corroborated_since` is the
time of the earliest ready build after which every member has had two of them.
"""
from __future__ import annotations

import json

from .candidates import origin_of_candidate
from .validation import parse_timestamp


def members_of(name: str, field: dict) -> dict[str, list[dict]]:
    """The field's members, by a key naming each, with the candidates of each."""
    value, candidates = field["value"], field["candidates"]
    if value is None:
        return {}
    if name == "executives":
        return {f"{m['title']}|{m['name']}": [c for c in candidates
                                              if c.get("title") == m["title"] and c["value"] == m["name"]]
                for m in value}
    if name == "investors":
        return {member: [c for c in candidates if c["value"] == member] for member in value}
    return {json.dumps(value): [c for c in candidates if c["value"] == value]}


def annotate(name: str, field: dict) -> dict:
    """The keys `origins` and `corroborated` of a field that has none (a build kept from an earlier stage)."""
    members = members_of(name, field)
    sets = [{origin_of_candidate(c) for c in group} for group in members.values()]
    field["origins"] = sorted(set().union(*sets)) if sets else []
    field["corroborated"] = bool(sets) and all(len(origins) >= 2 for origins in sets)
    field.setdefault("corroborated_since", None)
    return field


def update_standing(standing: dict, name: str, field: dict, build_time: str) -> str | None:
    """Fold a ready build's field into the field's standing origins (changed in place); its `corroborated_since`."""
    members = members_of(name, field)
    for key in [k for k in standing if k not in members]:
        del standing[key]
    for key, group in members.items():
        entry = standing.setdefault(key, {"origins": [], "reached": None})
        entry["origins"] = sorted(set(entry["origins"]) | {origin_of_candidate(c) for c in group})
        if entry["reached"] is None and len(entry["origins"]) >= 2:
            entry["reached"] = build_time
    if not members or any(entry["reached"] is None for entry in standing.values()):
        return None
    return max((entry["reached"] for entry in standing.values()), key=parse_timestamp)
