"""The HTTP API (§3, §6-§8, §10): routing, request parsing and error responses."""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .passwords import hash_password, verify_password
from .providers import Gateway
from .store import Store
from .validation import (Invalid, WrongType, is_email, normalise_domain, paging_int, parse_timestamp,
                         require_string)

log = logging.getLogger("dossier.http")

_MISSING = object()


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code.replace("_", " ")


def malformed(message="malformed request") -> ApiError:
    return ApiError(400, "malformed_request", message)


def invalid(message="validation failed") -> ApiError:
    return ApiError(422, "validation_failed", message)


def not_found(message="not found") -> ApiError:
    return ApiError(404, "not_found", message)


class Api:
    """Endpoint logic, independent of the HTTP plumbing."""

    def __init__(self, store: Store):
        self.store = store
        # scrypt takes 16 MiB a call: a few workers bound memory under 50 concurrent logins.
        self._hashers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hash")

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def parse_object(raw: bytes) -> dict:
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise malformed("body is not valid JSON") from None
        if not isinstance(body, dict):
            raise malformed("body must be a JSON object")
        return body

    def authenticate(self, headers) -> dict:
        header = headers.get("Authorization") or ""
        scheme, _, token = header.strip().partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise ApiError(401, "unauthenticated", "a bearer token is required")
        user = self.store.user_for_token(token)
        if user is None:
            raise ApiError(401, "unauthenticated", "unknown token")
        return user

    @staticmethod
    def idempotency_key(headers) -> str:
        key = headers.get("Idempotency-Key")
        if not key:
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
        if len(key) > 255:
            raise invalid("Idempotency-Key must be 1 to 255 characters")
        return key

    @staticmethod
    def domain(raw) -> str:
        try:
            return normalise_domain(raw)
        except Invalid as exc:
            raise invalid(str(exc)) from None

    # ---------------------------------------------------------------- control

    def health(self):
        return 200, {"status": "ok"}

    def reset(self, raw: bytes):
        fixture = self.parse_object(raw)
        try:
            if "now" not in fixture:
                raise Invalid("now is required")
            now = parse_timestamp(fixture["now"])
            users = fixture.get("users", [])
            if users is None:
                users = []
            if not isinstance(users, list):
                raise WrongType("users must be a list")
            seeded, ids, emails = [], set(), set()
            for user in users:
                if not isinstance(user, dict):
                    raise WrongType("each user must be an object")
                entry = {name: require_string(user, name) for name in ("id", "email", "password", "display_name")}
                if not entry["id"] or len(entry["id"]) > 64 or entry["id"] in ids:
                    raise Invalid("user ids must be unique, 1 to 64 characters")
                if entry["email"].lower() in emails:
                    raise Invalid("two users share an email")
                ids.add(entry["id"])
                emails.add(entry["email"].lower())
                seeded.append(entry)
        except WrongType as exc:
            raise malformed(str(exc)) from None
        except Invalid as exc:
            raise invalid(str(exc)) from None
        hashes = list(self._hashers.map(hash_password, [u["password"] for u in seeded]))
        users = [{"id": u["id"], "email": u["email"], "display_name": u["display_name"], "password_hash": h}
                 for u, h in zip(seeded, hashes)]
        self.store.reset(now, users)
        return 204, None

    def clock(self, raw: bytes):
        body = self.parse_object(raw)
        try:
            if "now" not in body:
                raise Invalid("now is required")
            self.store.set_clock(parse_timestamp(body["now"]))
        except WrongType as exc:
            raise malformed(str(exc)) from None
        except Invalid as exc:
            raise invalid(str(exc)) from None
        return 204, None

    def export(self):
        return 200, self.store.export()

    def import_(self, raw: bytes):
        document = self.parse_object(raw)
        try:
            self.store.import_(document)
        except Invalid as exc:
            raise invalid(f"not an export of this service: {exc}") from None
        return 204, None

    # ---------------------------------------------------------------- auth

    def signup(self, raw: bytes):
        body = self.parse_object(raw)
        try:
            email = require_string(body, "email")
            password = require_string(body, "password")
            display_name = require_string(body, "display_name")
        except WrongType as exc:
            raise malformed(str(exc)) from None
        except Invalid as exc:
            raise invalid(str(exc)) from None
        if len(password) < 8:
            raise invalid("password must be at least 8 characters")
        if not is_email(email):
            raise invalid("email must be of the form local@domain")
        if not 1 <= len(display_name) <= 100:
            raise invalid("display_name must be 1 to 100 characters")
        if self.store.email_taken(email):
            raise ApiError(409, "email_taken", "email already registered")
        created = self.store.add_user(email, display_name, self._hashers.submit(hash_password, password).result())
        if created is None:
            raise ApiError(409, "email_taken", "email already registered")
        user, token = created
        return 201, {"user_id": user["id"], "display_name": user["display_name"], "token": token}

    def login(self, raw: bytes):
        body = self.parse_object(raw)
        try:
            email = require_string(body, "email")
            password = require_string(body, "password")
        except WrongType as exc:
            raise malformed(str(exc)) from None
        except Invalid as exc:
            raise invalid(str(exc)) from None
        user = self.store.user_by_email(email)
        if user is None or not self._hashers.submit(verify_password, password, user["password_hash"]).result():
            raise ApiError(401, "unauthenticated", "wrong email or password")
        token = self.store.issue_token(user["id"])
        if token is None:
            raise ApiError(401, "unauthenticated", "wrong email or password")
        return 200, {"user_id": user["id"], "display_name": user["display_name"], "token": token}

    # ---------------------------------------------------------------- dossiers

    def create_dossier(self, headers, path: str, raw: bytes):
        user = self.authenticate(headers)
        body = self.parse_object(raw)
        key = self.idempotency_key(headers)
        domain_raw = body.get("domain", _MISSING)
        canonical = {"domain": None if domain_raw is _MISSING else domain_raw}

        def operation():
            if domain_raw is _MISSING or domain_raw is None:
                raise invalid("domain is required")
            if not isinstance(domain_raw, str):
                raise malformed("domain must be a string")
            return self.store.create_dossier(self.domain(domain_raw))

        return self._idempotent(user, "POST", path, key, canonical, operation)

    def refresh_dossier(self, headers, path: str, domain_segment: str):
        user = self.authenticate(headers)
        key = self.idempotency_key(headers)

        def operation():
            result = self.store.refresh_dossier(self.domain(domain_segment))
            if result is None:
                raise not_found("no dossier for this domain")
            return result

        return self._idempotent(user, "POST", path, key, None, operation)

    def _idempotent(self, user, method, path, key, canonical, operation):
        status, response = self.store.idempotent(user["id"], method, path, key, canonical, operation)
        if status == 409:
            raise ApiError(409, "idempotency_key_reuse", "key already used with a different request")
        return status, response

    def get_dossier(self, headers, domain_segment: str):
        self.authenticate(headers)
        view = self.store.view(self.domain(domain_segment))
        if view is None:
            raise not_found("no dossier for this domain")
        return 200, view

    def list_dossiers(self, headers, query: str):
        self.authenticate(headers)
        params = parse_qs(query, keep_blank_values=True)

        def first(name):
            values = params.get(name)
            return values[0] if values else None
        try:
            limit = paging_int(first("limit"), 50, 1, 200)
            offset = paging_int(first("offset"), 0, 0, None)
        except Invalid as exc:
            raise invalid(f"limit/offset: {exc}") from None
        return 200, self.store.listing(first("q"), limit, offset)

    # ---------------------------------------------------------------- routing

    def dispatch(self, method: str, target: str, headers, raw: bytes):
        parts = urlsplit(target)
        path = parts.path
        segments = [s for s in path.split("/") if s]
        route = (method, *segments)

        if route == ("GET", "health"):
            return self.health()
        if route == ("POST", "_test", "reset"):
            return self.reset(raw)
        if route == ("POST", "_test", "clock"):
            return self.clock(raw)
        if route == ("GET", "_test", "export"):
            return self.export()
        if route == ("POST", "_test", "import"):
            return self.import_(raw)
        if route == ("POST", "auth", "signup"):
            return self.signup(raw)
        if route == ("POST", "auth", "login"):
            return self.login(raw)
        if segments[:1] == ["dossiers"]:
            if route == ("POST", "dossiers"):
                return self.create_dossier(headers, path, raw)
            if route == ("GET", "dossiers"):
                return self.list_dossiers(headers, parts.query)
            if len(segments) == 2 and method == "GET":
                return self.get_dossier(headers, unquote(segments[1]))
            if len(segments) == 3 and segments[2] == "refresh" and method == "POST":
                return self.refresh_dossier(headers, path, unquote(segments[1]))
        raise not_found("no such route")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    api: Api = None  # set by serve()

    def log_message(self, fmt, *args):
        log.debug("%s - " + fmt, self.address_string(), *args)

    def _body(self) -> bytes:
        length = self.headers.get("Content-Length")
        try:
            size = int(length) if length else 0
        except ValueError:
            size = 0
        return self.rfile.read(size) if size > 0 else b""

    def _send(self, status: int, payload) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _handle(self, method: str) -> None:
        raw = self._body()
        try:
            status, payload = self.api.dispatch(method, self.path, self.headers, raw)
        except ApiError as exc:
            status, payload = exc.status, {"error": {"code": exc.code, "message": exc.message}}
        except Exception:  # noqa: BLE001 - logged; the client still gets a well-formed error
            log.exception("unhandled error on %s %s", method, self.path)
            status, payload = 500, {"error": {"code": "internal_error", "message": "internal error"}}
        self._send(status, payload)

    def do_GET(self):  # noqa: N802
        self._handle("GET")

    def do_POST(self):  # noqa: N802
        self._handle("POST")

    def do_PUT(self):  # noqa: N802
        self._handle("PUT")

    def do_PATCH(self):  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self):  # noqa: N802
        self._handle("DELETE")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


def serve() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Handler.api = Api(Store(Gateway()))
    port = int(os.environ.get("PORT") or 8080)
    server = Server(("0.0.0.0", port), Handler)
    log.info("listening on 0.0.0.0:%d", port)
    server.serve_forever()
