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

from .builder import BuildResult, Builder, empty_fields
from .candidates import KINDS, build_field, make_candidate
from .passwords import is_password_hash
from .providers import BUILD_BUDGET, Budget, Deadline, Gateway
from .support import FIELDS, HEADCOUNT_VALUES
from .validation import Invalid, format_timestamp, parse_timestamp

log = logging.getLogger("dossier.store")

EXPORT_TRACK = "dossier"
EXPORT_VERSION = 1
PROVIDERS = ("nimble", "tavily", "kernel", "browserbase")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def idempotency_slot(user_id: str, method: str, path: str, key: str) -> str:
    return json.dumps([user_id, method, path, key])


class Store:
    def __init__(self, gateway: Gateway):
        self.gateway = gateway
        self.lock = threading.RLock()
        self.epoch = 0
        self._clear()
        self.clock: datetime | None = None   # None: follow the system time until the first reset

    def _clear(self) -> None:
        self.users: dict[str, dict] = {}          # id -> {id, email, display_name, password_hash}
        self.emails: dict[str, str] = {}          # lower-cased email -> id
        self.tokens: dict[str, str] = {}          # token -> user id
        self.dossiers: dict[str, dict] = {}       # domain -> dossier record
        self.idempotency: dict[str, dict] = {}    # slot -> {body, status, response}
        self.next_dossier = 1

    # ------------------------------------------------------------------ clock

    def now(self) -> datetime:
        with self.lock:
            return self.clock if self.clock is not None else datetime.now(timezone.utc)

    def set_clock(self, value: datetime) -> None:
        with self.lock:
            if value < self.now():
                raise Invalid("the clock cannot move backwards")
            self.clock = value

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
                return 200, copy.deepcopy(record["response"])
            status, response = operation()
            self.idempotency[slot] = {"body": body, "status": status, "response": copy.deepcopy(response)}
            return status, response

    # ------------------------------------------------------------------ dossiers

    def _new_dossier(self, domain: str) -> dict:
        taken = {record["dossier_id"] for record in self.dossiers.values()}
        dossier_id = f"d_{self.next_dossier}"
        while dossier_id in taken:
            self.next_dossier += 1
            dossier_id = f"d_{self.next_dossier}"
        self.next_dossier += 1
        record = {"dossier_id": dossier_id, "domain": domain, "fields": empty_fields(), "researched_at": None,
                  "outcome": None, "spent_units": 0, "base_spent": 0, "building": None}
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
            if result.succeeded:
                record["fields"] = result.fields
                record["researched_at"] = build_time
                record["outcome"] = "ready"
            else:
                record["outcome"] = "failed"
            record["spent_units"] = record["base_spent"] + budget.spent
            record["base_spent"] = record["spent_units"]
            record["building"] = None
        log.info("build of %s ended %s, %d units", record["domain"], record["outcome"], budget.spent)

    # ------------------------------------------------------------------ export / import

    def export(self) -> dict:
        with self.lock:
            dossiers = []
            for record in self.dossiers.values():
                dossiers.append({
                    "dossier_id": record["dossier_id"],
                    "domain": record["domain"],
                    # A running build is not exported: the dossier as it was before it began.
                    "state": record["outcome"] or "failed",
                    "fields": copy.deepcopy(record["fields"]),
                    "researched_at": record["researched_at"],
                    "spent_units": record["base_spent"] if record["building"] is not None else record["spent_units"],
                })
            state = {
                "users": [dict(user) for user in self.users.values()],
                "tokens": dict(self.tokens),
                "dossiers": dossiers,
                "idempotency": [{"slot": json.loads(slot), **copy.deepcopy(record)}
                                for slot, record in self.idempotency.items()],
                "next_dossier": self.next_dossier,
            }
        return {"track": EXPORT_TRACK, "format_version": EXPORT_VERSION, "state": state}

    def import_(self, document) -> None:
        """Replace all state with an export; Invalid, changing nothing, when it is not one."""
        parsed = _parse_export(document)
        with self.lock:
            self.epoch += 1
            self._clear()
            self.users, self.emails, self.tokens, self.dossiers, self.idempotency, self.next_dossier = parsed


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
    """A stage-1 field as a stage-2 one: each citation is the excerpt of one candidate.

    A stage-1 export keeps no page text, only the excerpts that supported the asserted value;
    those are the candidates it records. Its kind and publication time are unknown.
    """
    if "candidates" in entry:
        return copy.deepcopy(entry)
    candidates, urls = [], set()
    for citation in entry["citations"]:
        if citation["url"] in urls:
            continue
        urls.add(citation["url"])
        candidates.append(make_candidate(entry["value"], citation["url"], citation["excerpt"],
                                         citation["provider"], None, None, researched_at or ""))
    return build_field(candidates)


def _parse_export(document):
    _require(isinstance(document, dict), "export must be an object")
    _require(document.get("track") == EXPORT_TRACK, "wrong track")
    version = document.get("format_version")
    _require(_is_int(version) and version == EXPORT_VERSION, "wrong format_version")
    state = document.get("state")
    _require(isinstance(state, dict), "state must be an object")
    for key in ("users", "tokens", "dossiers", "idempotency", "next_dossier"):
        _require(key in state, f"state.{key} is missing")

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

    dossiers = {}
    _require(isinstance(state["dossiers"], list), "state.dossiers must be a list")
    for item in state["dossiers"]:
        _require(isinstance(item, dict), "dossier must be an object")
        _require(_is_str(item.get("dossier_id"), 64) and _is_str(item.get("domain")), "dossier ids")
        _require(item["domain"] not in dossiers, "duplicate dossier")
        _require(item.get("state") in ("ready", "failed"), "dossier state")
        fields = item.get("fields")
        _require(isinstance(fields, dict) and set(fields) == set(FIELDS), "dossier fields")
        _require(all(_valid_field(name, fields[name]) for name in FIELDS), "dossier field")
        researched_at = item.get("researched_at")
        if researched_at is not None:
            parse_timestamp(researched_at)
        fields = {name: _upgraded_field(name, fields[name], researched_at) for name in FIELDS}
        spent = item.get("spent_units")
        _require(_is_int(spent) and spent >= 0, "spent_units")
        dossiers[item["domain"]] = {
            "dossier_id": item["dossier_id"], "domain": item["domain"], "fields": fields,
            "researched_at": researched_at, "outcome": item["state"], "spent_units": spent,
            "base_spent": spent, "building": None,
        }

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
    return users, emails, dict(tokens), dossiers, idempotency, next_dossier
