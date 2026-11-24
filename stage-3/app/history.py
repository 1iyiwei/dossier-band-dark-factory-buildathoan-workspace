"""Change over time (stage 3): how a selected value's change is typed, and what held on a date.

Pure functions over the field dicts and build records that `store.py` keeps.
"""
from __future__ import annotations

from .candidates import build_all
from .support import ALL_FIELDS, TITLES


def _members(field: dict) -> dict[str, tuple[str, str | None]]:
    """The executives field's members: title -> (name, true_from of the title's selected candidate)."""
    stamps = {c["title"]: c["true_from"] for c in field["candidates"] if c["selected"]}
    return {m["title"]: (m["name"], stamps.get(m["title"])) for m in field["value"] or []}


def _is_correction(old_from: str | None, new_from: str | None) -> bool:
    return old_from is not None and new_from is not None and new_from <= old_from


def change_type(name: str, old: dict, new: dict) -> str:
    """`correction` or `change` for a field whose selected value differs (Changes and corrections)."""
    if name != "executives":
        both = old["value"] is not None and new["value"] is not None
        return "correction" if both and _is_correction(old["true_from"], new["true_from"]) else "change"
    before, after = _members(old), _members(new)
    for title in TITLES:
        if title in before and title in after and before[title][0] == after[title][0]:
            continue
        if title not in before and title not in after:
            continue
        if not (title in before and title in after and _is_correction(before[title][1], after[title][1])):
            return "change"
    return "correction"


def _holding_versions(builds: list[dict]) -> list[dict]:
    """The page versions that known builds gathered, each with the date it holds from and the date it stops.

    A new version of a URL replaces the earlier ones whose `true_from` is on or after its own (all
    of them when its own is null); the latest earlier one left stops holding on its `true_from`.
    """
    by_url: dict[str, list[dict]] = {}
    for build in builds:
        for url, page in build["versions"].items():
            held = by_url.setdefault(url, [])
            start = page["true_from"]
            if start is None:
                held.clear()
            else:
                held[:] = [v for v in held if not (v["from"] is not None and v["from"] >= start)]
                if held:
                    held[-1]["until"] = start
            held.append({"url": url, "from": start, "until": None, "candidates": page["candidates"]})
    return [version for held in by_url.values() for version in held]


def values_at(builds: list[dict], true_at: str) -> dict:
    """Each field's value, `true_from` and citations that the given ready builds say held on `true_at`."""
    candidates: dict[str, list[dict]] = {name: [] for name in ALL_FIELDS}
    for version in _holding_versions(builds):
        if version["from"] is None or version["from"] > true_at:
            continue
        if version["until"] is not None and true_at >= version["until"]:
            continue
        for found in version["candidates"]:
            candidate = {k: v for k, v in found.items() if k != "field"}
            candidates[found["field"]].append(
                {**candidate, "url": version["url"], "true_from": version["from"], "retrieved_at": None, "learned_at": None,
                 "selected": False})
    return {name: {"value": field["value"], "true_from": field["true_from"], "citations": field["citations"]}
            for name, field in build_all(candidates).items()}
