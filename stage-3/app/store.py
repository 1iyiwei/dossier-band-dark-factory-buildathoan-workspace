"""All service state, behind one lock, and the background builds that write to it.

Every read and write of state happens under `Store.lock`, so concurrent requests behave
as if run one at a time (§11). A reset or import replaces the whole state and bumps the
epoch; a build started under an older epoch can no longer write anything (§3.3, §10).
"""
from __future__ import annotations

import copy
import json
import logging
import secrets
import threading
from datetime import datetime, timezone

from .builder import BuildResult, Builder
from .candidates import KINDS, build_field, candidate_key, empty_fields, make_candidate, true_from_of
from .history import change_type, values_at
from .passwords import is_password_hash
from .persistence import Journal, read_state
from .providers import BUILD_BUDGET, Budget, Deadline, Gateway
from .support import ALL_FIELDS, FIELDS, HEADCOUNT_VALUES, TITLES
from .validation import Invalid, WrongType, format_timestamp, parse_timestamp

log = logging.getLogger("dossier.store")

EXPORT_TRACK = "dossier"
EXPORT_VERSION = 1
PROVIDERS = ("nimble", "tavily", "kernel", "browserbase")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def idempotency_slot(user_id: str, method: str, path: str, key: str) -> str:
    return json.dumps([user_id, method, path, key])


class Store:
    def __init__(self, gateway: Gateway, state_dir: str | None = None):
        self.gateway = gateway
        self.lock = threading.RLock()
        self.epoch = 0
        self.version = 0                     # bumped by every change of persisted state
        self._clear()
        self.clock: datetime | None = None   # None: follow the system time until the first reset
        self.journal: Journal | None = None
        if state_dir:
            self._load(state_dir)
            self.journal = Journal(state_dir, self._snapshot)

    # ------------------------------------------------------------------ durability

    def _touch(self) -> None:
        """Under the lock: persisted state changed."""
        self.version += 1

    def _sync(self) -> None:
        """Outside the lock: return once every change made so far is on disk."""
        if self.journal is not None:
            with self.lock:
                target = self.version
            self.journal.commit(target)

    def _snapshot(self) -> tuple[int, bytes]:
        with self.lock:
            state = self._state()
            state["clock"] = format_timestamp(self.clock) if self.clock is not None else None
            return self.version, json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _load(self, state_dir: str) -> None:
        raw = read_state(state_dir)
        if raw is None:
            return
        state = json.loads(raw.decode("utf-8"))
        (self.users, self.emails, self.tokens, self.dossiers, self.idempotency, self.next_dossier,
         self.feed, self.next_seq) = _parse_state(state)
        clock = state.get("clock")
        self.clock = parse_timestamp(clock) if clock is not None else None
        log.info("restored %d dossiers, %d users from disk", len(self.dossiers), len(self.users))

    def _clear(self) -> None:
        self.users: dict[str, dict] = {}          # id -> {id, email, display_name, password_hash}
        self.emails: dict[str, str] = {}          # lower-cased email -> id
        self.tokens: dict[str, str] = {}          # token -> user id
        self.dossiers: dict[str, dict] = {}       # domain -> dossier record
        self.idempotency: dict[str, dict] = {}    # slot -> {body, status, response}
        self.next_dossier = 1
        self.feed: list[dict] = []                # every change and correction, by seq
        self.next_seq = 1

    # ------------------------------------------------------------------ clock

    def now(self) -> datetime:
        with self.lock:
            return self.clock if self.clock is not None else datetime.now(timezone.utc)

    def set_clock(self, value: datetime) -> None:
        with self.lock:
            if value < self.now():
                raise Invalid("the clock cannot move backwards")
            self.clock = value
            self._touch()
        self._sync()

    # ------------------------------------------------------------------ reset

    def reset(self, now: datetime, users: list[dict]) -> None:
        """Replace everything with the fixture; users carry hashed passwords already."""
        with self.lock:
            self.epoch += 1
            self._clear()
            self.clock = now
            for user in users:
                self.users[user["id"]] = user
                self.emails[user["email"].lower()] = user["id"]
            self._touch()
        self._sync()

    # ------------------------------------------------------------------ users

    def email_taken(self, email: str) -> bool:
        with self.lock:
            return email.lower() in self.emails

    def add_user(self, email: str, display_name: str, password_hash: str) -> tuple[dict, str] | None:
        """The new user and a token, or None when the email is taken."""
        with self.lock:
            if email.lower() in self.emails:
                return None
            user_id = "u_" + secrets.token_hex(8)
            while user_id in self.users:
                user_id = "u_" + secrets.token_hex(8)
            user = {"id": user_id, "email": email, "display_name": display_name, "password_hash": password_hash}
            self.users[user_id] = user
            self.emails[email.lower()] = user_id
            token = new_token()
            self.tokens[token] = user_id
            self._touch()
        self._sync()
        return user, token

    def user_by_email(self, email: str) -> dict | None:
        with self.lock:
            user_id = self.emails.get(email.lower())
            return dict(self.users[user_id]) if user_id else None

    def issue_token(self, user_id: str) -> str | None:
        with self.lock:
            if user_id not in self.users:
                return None
            token = new_token()
            self.tokens[token] = user_id
            self._touch()
        self._sync()
        return token

    def user_for_token(self, token: str) -> dict | None:
        with self.lock:
            user_id = self.tokens.get(token)
            return self.users.get(user_id) if user_id else None

    # ------------------------------------------------------------------ idempotency

    def idempotent(self, user_id: str, method: str, path: str, key: str, body, operation):
        """Run `operation` once per key: a replay returns the stored response with 200 (§7).

        `operation` runs under the lock and returns (status, response); it raises for a 4xx,
        which is not stored, so the key stays free.
        """
        slot = idempotency_slot(user_id, method, path, key)
        with self.lock:
            record = self.idempotency.get(slot)
            if record is not None:
                if record["body"] != body:
                    return 409, None
                result = 200, copy.deepcopy(record["response"])
            else:
                status, response = operation()
                self.idempotency[slot] = {"body": body, "status": status, "response": copy.deepcopy(response)}
                self._touch()
                result = status, response
        self._sync()   # a replay may answer from a record another request has not yet made durable
        return result

    # ------------------------------------------------------------------ dossiers

    def _new_dossier(self, domain: str) -> dict:
        taken = {record["dossier_id"] for record in self.dossiers.values()}
        dossier_id = f"d_{self.next_dossier}"
        while dossier_id in taken:
            self.next_dossier += 1
            dossier_id = f"d_{self.next_dossier}"
        self.next_dossier += 1
        record = _new_record(dossier_id, domain)
        self.dossiers[domain] = record
        return record

    @staticmethod
    def state_of(record: dict) -> str:
        if record["building"] is not None:
            return "building"
        return record["outcome"] or "failed"

    def summary(self, record: dict) -> dict:
        return {"dossier_id": record["dossier_id"], "domain": record["domain"], "state": self.state_of(record)}

    def create_dossier(self, domain: str) -> tuple[int, dict]:
        """Under the lock: 202 and a new build, or 200 for the dossier that already exists."""
        with self.lock:
            record = self.dossiers.get(domain)
            if record is not None:
                return 200, self.summary(record)
            record = self._new_dossier(domain)
            self._start_build(record)
            return 202, self.summary(record)

    def refresh_dossier(self, domain: str) -> tuple[int, dict] | None:
        with self.lock:
            record = self.dossiers.get(domain)
            if record is None:
                return None
            if record["building"] is None:
                self._start_build(record)
            return 202, self.summary(record)

    def view(self, domain: str) -> dict | None:
        with self.lock:
            record = self.dossiers.get(domain)
            if record is None:
                return None
            return {
                "dossier_id": record["dossier_id"],
                "domain": record["domain"],
                "state": self.state_of(record),
                "researched_at": record["researched_at"],
                "spent_units": record["spent_units"],
                "fields": copy.deepcopy(record["fields"]),
            }

    @staticmethod
    def _ready_builds(record: dict, as_of: datetime) -> list[dict]:
        """The builds that completed `ready` at or before `as_of`, in build order."""
        return [b for b in record["builds"] if b["outcome"] == "ready" and parse_timestamp(b["time"]) <= as_of]

    def view_as_of(self, domain: str, as_of: datetime) -> dict | None:
        """The dossier as the service had it at `as_of`, or None when it has no such build."""
        with self.lock:
            record = self.dossiers.get(domain)
            if record is None:
                return None
            ready = self._ready_builds(record, as_of)
            if not ready:
                return None
            build = ready[-1]
            spent = record["prior_spent"] + sum(b["spent"] for b in record["builds"]
                                                if parse_timestamp(b["time"]) <= as_of)
            return {"dossier_id": record["dossier_id"], "domain": record["domain"], "state": "ready",
                    "researched_at": build["time"], "spent_units": spent, "fields": copy.deepcopy(build["fields"])}

    def values(self, domain: str, true_at: str, as_of: datetime | None) -> dict | None:
        """Each field's value on the date `true_at`, by the evidence known at `as_of` (default: now)."""
        with self.lock:
            record = self.dossiers.get(domain)
            if record is None:
                return None
            ready = self._ready_builds(record, as_of or self.now())
            return values_at(ready, true_at) if ready else None

    def history(self, domain: str) -> dict | None:
        with self.lock:
            record = self.dossiers.get(domain)
            if record is None:
                return None
            return {"domain": domain, "fields": copy.deepcopy(record["history"])}

    def changes(self, since: int, limit: int) -> dict:
        with self.lock:
            # The feed is sorted by seq: find the first entry past `since` by bisection.
            low, high = 0, len(self.feed)
            while low < high:
                middle = (low + high) // 2
                if self.feed[middle]["seq"] > since:
                    high = middle
                else:
                    low = middle + 1
            page = self.feed[low:low + limit]
            return {"changes": copy.deepcopy(page), "has_more": low + limit < len(self.feed)}

    def listing(self, q: str | None, limit: int, offset: int) -> dict:
        with self.lock:
            rows = []
            for domain in sorted(self.dossiers):
                record = self.dossiers[domain]
                legal_name = record["fields"]["legal_name"]["value"]
                if q:
                    needle = q.casefold()
                    if needle not in domain.casefold() and not (legal_name and needle in legal_name.casefold()):
                        continue
                rows.append({"dossier_id": record["dossier_id"], "domain": domain, "state": self.state_of(record),
                             "legal_name": legal_name, "researched_at": record["researched_at"],
                             "spent_units": record["spent_units"]})
        page = rows[offset:offset + limit]
        return {"dossiers": page, "has_more": offset + limit < len(rows)}

    # ------------------------------------------------------------------ builds

    def _start_build(self, record: dict) -> None:
        """Under the lock: mark the dossier building and run its build in the background."""
        build_id = secrets.token_hex(8)
        record["building"] = build_id
        record["base_spent"] = record["spent_units"]
        build_time = format_timestamp(self.now())
        epoch = self.epoch
        thread = threading.Thread(target=self._run_build, args=(record, build_id, epoch, build_time),
                                  name=f"build-{record['domain']}", daemon=True)
        thread.start()

    def _run_build(self, record: dict, build_id: str, epoch: int, build_time: str) -> None:
        def cancelled() -> bool:
            return self.epoch != epoch or record["building"] != build_id

        def on_spend(spent: int) -> None:
            with self.lock:
                if not cancelled():
                    record["spent_units"] = record["base_spent"] + spent

        budget = Budget(BUILD_BUDGET, on_spend)
        try:
            result = Builder(self.gateway, record["domain"], budget, cancelled, Deadline(), build_time).run()
        except Exception:  # noqa: BLE001 - a broken build ends failed, never takes the service down
            log.exception("build of %s crashed", record["domain"])
            result = BuildResult(succeeded=False)
        with self.lock:
            if cancelled():
                return
            spent = budget.spent
            if result.succeeded:
                self._complete_ready(record, result, build_time, spent)
            else:
                record["outcome"] = "failed"
                record["builds"].append({"time": build_time, "outcome": "failed", "spent": spent})
            record["spent_units"] = record["base_spent"] + spent
            record["base_spent"] = record["spent_units"]
            record["building"] = None
            self._touch()
        self._sync()
        log.info("build of %s ended %s, %d units", record["domain"], record["outcome"], budget.spent)

    def _complete_ready(self, record: dict, result: BuildResult, build_time: str, spent: int) -> None:
        """Under the lock: a build that completed `ready` becomes the dossier's fields, history and feed entries."""
        fields, previous = result.fields, record["fields"]
        first = not any(b["outcome"] == "ready" for b in record["builds"])
        for name in ALL_FIELDS:
            for candidate in fields[name]["candidates"]:
                key = json.dumps(candidate_key(name, candidate))
                candidate["learned_at"] = record["first_seen"].setdefault(key, build_time)
        for name in ALL_FIELDS:
            old, new = previous[name], fields[name]
            if new["value"] is not None:
                new["learned_at"] = old["learned_at"] if new["value"] == old["value"] else build_time
            if new["value"] == old["value"]:
                continue
            kind = "initial" if first else change_type(name, old, new)
            record["history"][name].append({"type": kind, "value": new["value"], "true_from": new["true_from"],
                                            "learned_at": build_time, "citations": copy.deepcopy(new["citations"])})
            if kind != "initial":
                self.feed.append({"seq": self.next_seq, "domain": record["domain"], "field": name, "type": kind,
                                  "from": old["value"], "to": new["value"], "true_from": new["true_from"],
                                  "learned_at": build_time})
                self.next_seq += 1
        record["builds"].append({"time": build_time, "outcome": "ready", "spent": spent, "fields": fields,
                                 "versions": result.versions})
        record["fields"] = fields
        record["researched_at"] = build_time
        record["outcome"] = "ready"

    # ------------------------------------------------------------------ export / import

    def _state(self) -> dict:
        """Under the lock: everything the service keeps, as JSON-ready data (not copied)."""
        dossiers = []
        for record in self.dossiers.values():
            # A running build is not exported: the dossier as it was before it began.
            building = record["building"] is not None
            dossiers.append({
                "dossier_id": record["dossier_id"],
                "domain": record["domain"],
                "state": record["outcome"] or "failed",
                "researched_at": record["researched_at"],
                "spent_units": record["base_spent"] if building else record["spent_units"],
                "prior_spent": record["prior_spent"],
                "builds": record["builds"],
                "history": record["history"],
                "first_seen": [[json.loads(key), time] for key, time in record["first_seen"].items()],
            })
        return {
            "users": list(self.users.values()),
            "tokens": self.tokens,
            "dossiers": dossiers,
            "idempotency": [{"slot": json.loads(slot), **record} for slot, record in self.idempotency.items()],
            "next_dossier": self.next_dossier,
            "feed": self.feed,
            "next_seq": self.next_seq,
        }

    def export(self) -> dict:
        with self.lock:
            state = copy.deepcopy(self._state())
        return {"track": EXPORT_TRACK, "format_version": EXPORT_VERSION, "state": state}

    def import_(self, document) -> None:
        """Replace all state with an export; Invalid, changing nothing, when it is not one."""
        parsed = _parse_export(document)
        with self.lock:
            self.epoch += 1
            self._clear()
            (self.users, self.emails, self.tokens, self.dossiers, self.idempotency, self.next_dossier,
             self.feed, self.next_seq) = parsed
            self._touch()
        self._sync()


def _new_record(dossier_id: str, domain: str) -> dict:
    return {"dossier_id": dossier_id, "domain": domain, "fields": empty_fields(), "researched_at": None,
            "outcome": None, "spent_units": 0, "base_spent": 0, "building": None, "prior_spent": 0,
            "builds": [], "history": {name: [] for name in ALL_FIELDS}, "first_seen": {}}


# ---------------------------------------------------------------------- import validation

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def _is_str(value, max_len: int | None = None) -> bool:
    return isinstance(value, str) and (max_len is None or len(value) <= max_len)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _typed(name: str, value) -> bool:
    if name in ("founded_year", "funding_total"):
        return _is_int(value)
    if name == "headcount_range":
        return value in HEADCOUNT_VALUES
    return _is_str(value)


def _valid_citations(citations) -> bool:
    return isinstance(citations, list) and all(
        isinstance(c, dict) and _is_str(c.get("url")) and _is_str(c.get("excerpt"))
        and c.get("provider") in PROVIDERS for c in citations)


def _valid_candidate(name: str, candidate) -> bool:
    if not isinstance(candidate, dict):
        return False
    published = candidate.get("published_at")
    kind = candidate.get("kind")
    return (_typed(name, candidate.get("value")) and _is_str(candidate.get("url"))
            and _is_str(candidate.get("excerpt")) and candidate.get("provider") in PROVIDERS
            and (kind is None or kind in KINDS) and (published is None or _is_str(published))
            and _is_str(candidate.get("retrieved_at")) and isinstance(candidate.get("selected"), bool))


def _valid_field(name: str, entry) -> bool:
    """A field as a stage-2 service exports it (with candidates) or as a stage-1 one did (without)."""
    if not isinstance(entry, dict) or set(entry) not in ({"value", "status", "citations"},
                                                         {"value", "status", "citations", "candidates"}):
        return False
    value, status, citations = entry["value"], entry["status"], entry["citations"]
    if not _valid_citations(citations):
        return False
    if "candidates" in entry:
        candidates = entry["candidates"]
        if not isinstance(candidates, list) or not all(_valid_candidate(name, c) for c in candidates):
            return False
        if not candidates:
            return value is None and status == "unknown" and citations == []
        return _typed(name, value) and status in ("known", "contested") and bool(citations)
    if value is None:
        return status == "unknown" and citations == []
    return status == "known" and bool(citations) and _typed(name, value)


def _upgraded_field(name: str, entry: dict, researched_at: str | None) -> dict:
    """A stage-1 or stage-2 field as a stage-3 one (Upgrades).

    A stage-1 export keeps no page text, only the excerpts that supported the asserted value;
    each citation is the excerpt of one candidate, with no kind or publication time. A stage-2
    export keeps its candidates. A candidate's `true_from` follows from its publication time
    (no `Effective` line is recorded) and its `learned_at` is its `retrieved_at`.
    """
    candidates, urls = [], set()
    if "candidates" in entry:
        for c in entry["candidates"]:
            candidates.append(make_candidate(c["value"], c["url"], c["excerpt"], c["provider"], c.get("kind"),
                                             c.get("published_at"), c["retrieved_at"],
                                             true_from_of(None, c.get("published_at"))))
    else:
        for citation in entry["citations"]:
            if citation["url"] in urls:
                continue
            urls.add(citation["url"])
            candidates.append(make_candidate(entry["value"], citation["url"], citation["excerpt"],
                                             citation["provider"], None, None, researched_at or ""))
    field = build_field(candidates)
    if field["value"] is not None:
        field["learned_at"] = researched_at
    return field


def _imported_dossier(item: dict, fields_in: dict, researched_at: str | None, spent: int) -> dict:
    """A dossier of a stage-1 or stage-2 export: one ready build at `researched_at`, one initial entry per value."""
    record = _new_record(item["dossier_id"], item["domain"])
    record.update(outcome=item["state"], spent_units=spent, base_spent=spent, researched_at=researched_at)
    if researched_at is None:
        record["prior_spent"] = spent
        return record
    fields = {name: _upgraded_field(name, fields_in[name], researched_at) for name in FIELDS}
    fields["executives"] = empty_fields()["executives"]
    versions = {}
    for name in ALL_FIELDS:
        for c in fields[name]["candidates"]:
            page = versions.setdefault(c["url"], {"true_from": c["true_from"], "candidates": []})
            page["candidates"].append({"field": name, **{k: c[k] for k in
                                       ("title", "value", "excerpt", "provider", "kind", "published_at") if k in c}})
            record["first_seen"].setdefault(json.dumps(candidate_key(name, c)), c["learned_at"])
        if fields[name]["value"] is not None:
            record["history"][name].append({"type": "initial", "value": fields[name]["value"],
                                            "true_from": fields[name]["true_from"], "learned_at": researched_at,
                                            "citations": copy.deepcopy(fields[name]["citations"])})
    record["builds"].append({"time": researched_at, "outcome": "ready", "spent": spent, "fields": fields,
                             "versions": versions})
    record["fields"] = fields
    return record


def _is_date_or_none(value) -> bool:
    return value is None or (_is_str(value) and len(value) == 10)


def _valid_stage3_candidate(name: str, candidate) -> bool:
    return (isinstance(candidate, dict) and _is_str(candidate.get("url")) and _is_str(candidate.get("excerpt"))
            and candidate.get("provider") in PROVIDERS and _is_date_or_none(candidate.get("true_from"))
            and _is_str(candidate.get("learned_at")) and isinstance(candidate.get("selected"), bool)
            and (candidate.get("title") in TITLES if name == "executives" else _typed(name, candidate.get("value"))))


def _valid_stage3_field(name: str, entry) -> bool:
    return (isinstance(entry, dict)
            and set(entry) == {"value", "status", "true_from", "learned_at", "citations", "candidates"}
            and _valid_citations(entry["citations"]) and isinstance(entry["candidates"], list)
            and all(_valid_stage3_candidate(name, c) for c in entry["candidates"])
            and entry["status"] in ("known", "contested", "unknown") and _is_date_or_none(entry["true_from"]))


def _stage3_dossier(item: dict) -> dict:
    """A dossier as a stage-3 export holds it: its builds, history and the dates of first sight."""
    spent, prior = item.get("spent_units"), item.get("prior_spent")
    _require(_is_int(spent) and spent >= 0 and _is_int(prior) and prior >= 0, "spent_units")
    builds = item.get("builds")
    _require(isinstance(builds, list), "builds")
    for build in builds:
        _require(isinstance(build, dict) and _is_int(build.get("spent")) and build.get("outcome") in ("ready", "failed"),
                 "build")
        parse_timestamp(build.get("time"))
        if build["outcome"] == "ready":
            fields = build.get("fields")
            _require(isinstance(fields, dict) and set(fields) == set(ALL_FIELDS)
                     and all(_valid_stage3_field(name, fields[name]) for name in ALL_FIELDS), "build fields")
            versions = build.get("versions")
            _require(isinstance(versions, dict) and all(
                isinstance(page, dict) and isinstance(page.get("candidates"), list)
                and all(isinstance(c, dict) and c.get("field") in ALL_FIELDS for c in page["candidates"])
                for page in versions.values()), "build versions")
    history = item.get("history")
    _require(isinstance(history, dict) and set(history) == set(ALL_FIELDS)
             and all(isinstance(history[n], list) and all(isinstance(e, dict) for e in history[n]) for n in ALL_FIELDS),
             "history")
    first_seen = item.get("first_seen")
    _require(isinstance(first_seen, list) and all(isinstance(e, list) and len(e) == 2 and isinstance(e[0], list)
                                                  and _is_str(e[1]) for e in first_seen), "first_seen")
    record = _new_record(item["dossier_id"], item["domain"])
    ready = [b for b in builds if b["outcome"] == "ready"]
    record.update(outcome=item["state"], spent_units=spent, base_spent=spent, prior_spent=prior,
                  researched_at=ready[-1]["time"] if ready else None, builds=builds, history=history,
                  first_seen={json.dumps(key): time for key, time in first_seen},
                  fields=ready[-1]["fields"] if ready else record["fields"])
    return record


def _parse_dossiers(state: dict, stage3: bool) -> dict:
    dossiers = {}
    _require(isinstance(state["dossiers"], list), "state.dossiers must be a list")
    for item in state["dossiers"]:
        _require(isinstance(item, dict), "dossier must be an object")
        _require(_is_str(item.get("dossier_id"), 64) and _is_str(item.get("domain")), "dossier ids")
        _require(item["domain"] not in dossiers, "duplicate dossier")
        _require(item.get("state") in ("ready", "failed"), "dossier state")
        researched_at = item.get("researched_at")
        if researched_at is not None:
            parse_timestamp(researched_at)
        if stage3:
            dossiers[item["domain"]] = _stage3_dossier(item)
            continue
        fields = item.get("fields")
        _require(isinstance(fields, dict) and set(fields) == set(FIELDS), "dossier fields")
        _require(all(_valid_field(name, fields[name]) for name in FIELDS), "dossier field")
        spent = item.get("spent_units")
        _require(_is_int(spent) and spent >= 0, "spent_units")
        dossiers[item["domain"]] = _imported_dossier(item, fields, researched_at, spent)
    return dossiers


def _parse_state(state):
    """The service's state from an export's `state` (of this stage or an earlier one); Invalid when it is not."""
    try:
        return _parse_state_unsafe(state)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, WrongType) as exc:
        raise Invalid(f"state is malformed: {exc}") from exc


def _parse_state_unsafe(state):
    _require(isinstance(state, dict), "state must be an object")
    for key in ("users", "tokens", "dossiers", "idempotency", "next_dossier"):
        _require(key in state, f"state.{key} is missing")
    stage3 = "feed" in state

    users, emails = {}, {}
    _require(isinstance(state["users"], list), "state.users must be a list")
    for user in state["users"]:
        _require(isinstance(user, dict), "user must be an object")
        _require(all(_is_str(user.get(k)) for k in ("id", "email", "display_name")), "user fields")
        _require(is_password_hash(user.get("password_hash")), "user password_hash")
        _require(user["id"] not in users and user["email"].lower() not in emails, "duplicate user")
        users[user["id"]] = {k: user[k] for k in ("id", "email", "display_name", "password_hash")}
        emails[user["email"].lower()] = user["id"]

    tokens = state["tokens"]
    _require(isinstance(tokens, dict) and all(_is_str(v) and v in users for v in tokens.values()), "tokens")

    dossiers = _parse_dossiers(state, stage3)

    idempotency = {}
    _require(isinstance(state["idempotency"], list), "state.idempotency must be a list")
    for item in state["idempotency"]:
        _require(isinstance(item, dict), "idempotency record must be an object")
        slot = item.get("slot")
        _require(isinstance(slot, list) and len(slot) == 4 and all(_is_str(s) for s in slot), "slot")
        _require(_is_int(item.get("status")) and "response" in item and "body" in item, "idempotency record")
        idempotency[json.dumps(slot)] = {"body": item["body"], "status": item["status"],
                                         "response": copy.deepcopy(item["response"])}

    next_dossier = state["next_dossier"]
    _require(_is_int(next_dossier) and next_dossier >= 1, "next_dossier")

    feed, next_seq = [], 1
    if stage3:
        feed, next_seq = state["feed"], state.get("next_seq")
        _require(isinstance(feed, list) and _is_int(next_seq) and next_seq >= 1, "feed")
        _require(all(isinstance(e, dict) and _is_int(e.get("seq")) for e in feed), "feed entry")
        _require(all(a["seq"] < b["seq"] for a, b in zip(feed, feed[1:])) and (not feed or feed[-1]["seq"] < next_seq),
                 "feed order")
    return users, emails, dict(tokens), dossiers, idempotency, next_dossier, list(feed), next_seq


def _parse_export(document):
    _require(isinstance(document, dict), "export must be an object")
    _require(document.get("track") == EXPORT_TRACK, "wrong track")
    version = document.get("format_version")
    _require(_is_int(version) and version == EXPORT_VERSION, "wrong format_version")
    return _parse_state(document.get("state"))
