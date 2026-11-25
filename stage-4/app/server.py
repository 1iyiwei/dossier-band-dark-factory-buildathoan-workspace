"""The HTTP API (§3, §6-§8, §10): routing, request parsing and error responses."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .passwords import hash_password, verify_password
from .providers import Gateway
from .store import Store
from .validation import (Invalid, WrongType, format_timestamp, is_email, normalise_domain, paging_int,
                         parse_timestamp, require_string)

log = logging.getLogger("dossier.http")

_MISSING = object()
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
STATIC = Path(__file__).parent / "static"
ASSET_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
               ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
MAX_BODY = 64 * 1024 * 1024
MAX_BATCH_DOMAINS = 50
MIN_BATCH_BUDGET, MAX_BATCH_BUDGET = 1, 100_000
_HTTP_ERROR_CODES = {400: "malformed_request", 404: "not_found", 405: "method_not_allowed",
                     408: "request_timeout", 413: "payload_too_large", 414: "uri_too_long",
                     431: "headers_too_large", 505: "malformed_request"}


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


class Asset:
    """A non-JSON response: a page or file of the browser UI."""

    def __init__(self, content_type: str, body: bytes, cache: str = "no-cache"):
        self.content_type, self.body, self.cache = content_type, body, cache


def load_assets() -> dict[str, Asset]:
    """The UI files, read once: `/static/<name>` for each, and the page shell every screen is served as."""
    assets = {}
    for path in sorted(STATIC.glob("*")):
        content_type = ASSET_TYPES.get(path.suffix)
        if content_type:
            assets[f"/static/{path.name}"] = Asset(content_type, path.read_bytes())
    return assets


def wants_html(headers) -> bool:
    return "text/html" in (headers.get("Accept") or "").lower()


class Api:
    """Endpoint logic, independent of the HTTP plumbing."""

    def __init__(self, store: Store):
        self.store = store
        self.assets = load_assets()
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

    def create_batch(self, headers, path: str, raw: bytes):
        user = self.authenticate(headers)
        body = self.parse_object(raw)
        key = self.idempotency_key(headers)
        domains_raw = body.get("domains")
        budget_raw = body.get("budget_units")
        canonical = {"domains": domains_raw, "budget_units": budget_raw}

        def operation():
            if domains_raw is None:
                raise invalid("domains is required")
            if not isinstance(domains_raw, list):
                raise malformed("domains must be a list")
            if not 1 <= len(domains_raw) <= MAX_BATCH_DOMAINS:
                raise invalid(f"domains must hold 1 to {MAX_BATCH_DOMAINS} entries")
            domains = []
            for entry in domains_raw:
                if not isinstance(entry, str):
                    raise malformed("each domain must be a string")
                domains.append(self.domain(entry))
            if len(set(domains)) != len(domains):
                raise invalid("domains names a company twice")
            if (isinstance(budget_raw, bool) or not isinstance(budget_raw, int)
                    or not MIN_BATCH_BUDGET <= budget_raw <= MAX_BATCH_BUDGET):
                raise invalid(f"budget_units must be an integer, {MIN_BATCH_BUDGET} to {MAX_BATCH_BUDGET}")
            return self.store.create_batch(user["id"], domains, budget_raw)

        return self._idempotent(user, "POST", path, key, canonical, operation)

    def get_batch(self, headers, batch_id: str):
        user = self.authenticate(headers)
        batch = self.store.get_batch(user["id"], batch_id)
        if batch is None:
            raise not_found("no such batch")
        return 200, batch

    def _idempotent(self, user, method, path, key, canonical, operation):
        status, response = self.store.idempotent(user["id"], method, path, key, canonical, operation)
        if status == 409:
            raise ApiError(409, "idempotency_key_reuse", "key already used with a different request")
        return status, response

    @staticmethod
    def query_param(query: str, name: str):
        """The first value of a query parameter, percent-decoded; a literal `+` stays a plus (an offset)."""
        for pair in query.split("&"):
            key, _, value = pair.partition("=")
            if unquote(key) == name:
                return unquote(value)
        return None

    @staticmethod
    def timestamp_param(raw: str):
        try:
            return parse_timestamp(raw)
        except (Invalid, WrongType):
            raise invalid("timestamp must be RFC 3339 with an explicit offset") from None

    def get_dossier(self, headers, domain_segment: str, query: str = ""):
        self.authenticate(headers)
        domain = self.domain(domain_segment)
        as_of = self.query_param(query, "as_of")
        if as_of is None:
            view = self.store.view(domain)
        else:
            view = self.store.view_as_of(domain, self.timestamp_param(as_of))
        if view is None:
            raise not_found("no dossier for this domain, or no completed build at that time")
        return 200, view

    def get_values(self, headers, domain_segment: str, query: str):
        self.authenticate(headers)
        domain = self.domain(domain_segment)
        true_at = self.query_param(query, "true_at")
        as_of = self.query_param(query, "as_of")
        if true_at is None or not _DATE.fullmatch(true_at):
            raise invalid("true_at must be a date, YYYY-MM-DD")
        try:
            date.fromisoformat(true_at)
        except ValueError:
            raise invalid("true_at must be a date, YYYY-MM-DD") from None
        as_of_time = None if as_of is None else self.timestamp_param(as_of)
        fields = self.store.values(domain, true_at, as_of_time)
        if fields is None:
            raise not_found("no dossier for this domain, or no completed build at that time")
        return 200, {"domain": domain, "true_at": true_at, "as_of": as_of or format_timestamp(self.store.now()),
                     "fields": fields}

    def get_history(self, headers, domain_segment: str):
        self.authenticate(headers)
        history = self.store.history(self.domain(domain_segment))
        if history is None:
            raise not_found("no dossier for this domain")
        return 200, history

    def get_changes(self, headers, query: str):
        self.authenticate(headers)
        try:
            since = paging_int(self.query_param(query, "since"), 0, 0, None)
            limit = paging_int(self.query_param(query, "limit"), 50, 1, 200)
        except Invalid as exc:
            raise invalid(f"since/limit: {exc}") from None
        return 200, self.store.changes(since, limit)

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

    def routes(self, segments: list[str], path: str, query: str, headers, raw: bytes) -> dict:
        """The handlers for a path, by method; empty when the path names nothing."""
        fixed = {
            ("health",): {"GET": self.health},
            ("_test", "reset"): {"POST": lambda: self.reset(raw)},
            ("_test", "clock"): {"POST": lambda: self.clock(raw)},
            ("_test", "export"): {"GET": self.export},
            ("_test", "import"): {"POST": lambda: self.import_(raw)},
            ("auth", "signup"): {"POST": lambda: self.signup(raw)},
            ("auth", "login"): {"POST": lambda: self.login(raw)},
            ("dossiers",): {"POST": lambda: self.create_dossier(headers, path, raw),
                            "GET": lambda: self.list_dossiers(headers, query)},
            ("changes",): {"GET": lambda: self.get_changes(headers, query)},
            ("batches",): {"POST": lambda: self.create_batch(headers, path, raw)},
        }
        key = tuple(segments)
        if key in fixed:
            return fixed[key]
        screen = self.screen_routes(segments, headers)
        if screen:
            return screen
        if len(segments) == 2 and segments[0] == "batches":
            return {"GET": lambda: self.get_batch(headers, unquote(segments[1]))}
        if len(segments) == 2 and segments[0] == "dossiers":
            return {"GET": lambda: self.get_dossier(headers, unquote(segments[1]), query)}
        if len(segments) == 3 and segments[0] == "dossiers" and segments[2] == "values":
            return {"GET": lambda: self.get_values(headers, unquote(segments[1]), query)}
        if len(segments) == 3 and segments[0] == "dossiers" and segments[2] == "history":
            return {"GET": lambda: self.get_history(headers, unquote(segments[1]))}
        if len(segments) == 3 and segments[0] == "dossiers" and segments[2] == "refresh":
            return {"POST": lambda: self.refresh_dossier(headers, path, unquote(segments[1]))}
        return {}

    def screen_routes(self, segments: list[str], headers) -> dict:
        """The browser screens. `/dossiers/{domain}` is shared with the API: a browser (Accept: text/html) gets the UI."""
        shell = lambda: (200, self.assets["/static/index.html"])  # noqa: E731
        if segments in ([], ["signup"], ["login"], ["contested"]):
            return {"GET": shell}
        if len(segments) == 3 and segments[0] == "dossiers" and segments[2] == "evidence":
            return {"GET": shell}
        if len(segments) == 2 and segments[0] == "dossiers" and wants_html(headers):
            return {"GET": shell}
        if len(segments) == 2 and segments[0] == "static" and f"/static/{segments[1]}" in self.assets:
            return {"GET": lambda: (200, self.assets[f"/static/{segments[1]}"])}
        return {}

    def dispatch(self, method: str, target: str, headers, raw: bytes):
        parts = urlsplit(target)
        segments = [s for s in parts.path.split("/") if s]
        handlers = self.routes(segments, parts.path, parts.query, headers, raw)
        if not handlers:
            raise not_found("no such route")
        if method not in handlers:
            raise ApiError(405, "method_not_allowed", f"{method} is not allowed here")
        return handlers[method]()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    api: Api = None  # set by serve()

    def log_message(self, fmt, *args):
        log.debug("%s - " + fmt, self.address_string(), *args)

    def _body(self) -> bytes:
        """The request body, from Content-Length or chunked transfer coding."""
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return self._chunked_body()
        length = self.headers.get("Content-Length")
        try:
            size = int(length) if length else 0
        except ValueError:
            self.close_connection = True
            raise malformed("invalid Content-Length") from None
        if size > MAX_BODY:
            self.close_connection = True
            raise ApiError(413, "payload_too_large", "request body is too large")
        return self.rfile.read(size) if size > 0 else b""

    def _chunked_body(self) -> bytes:
        chunks, total = [], 0
        try:
            while True:
                line = self.rfile.readline(1024)
                size = int(line.split(b";", 1)[0].strip(), 16)
                if size == 0:
                    while self.rfile.readline(8192).strip():
                        pass  # trailer fields
                    return b"".join(chunks)
                total += size
                if total > MAX_BODY:
                    self.close_connection = True
                    raise ApiError(413, "payload_too_large", "request body is too large")
                chunks.append(self.rfile.read(size))
                self.rfile.readline(8)  # the CRLF after each chunk
        except ValueError:
            self.close_connection = True
            raise malformed("invalid chunked body") from None

    def _send(self, status: int, payload) -> None:
        if isinstance(payload, Asset):
            body, content_type = payload.body, payload.content_type
        else:
            body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", content_type)
            if isinstance(payload, Asset):
                self.send_header("Cache-Control", payload.cache)
        self.send_header("Content-Length", str(len(body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self, method: str) -> None:
        try:
            raw = self._body()
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

    def do_OPTIONS(self):  # noqa: N802
        self._handle("OPTIONS")

    def do_HEAD(self):  # noqa: N802
        self._handle("HEAD")

    def send_error(self, code, message=None, explain=None):
        """Errors raised by the HTTP layer itself (bad request line, unknown method, huge headers) as JSON (§5)."""
        if code == 501:
            code = 405   # a method this server has no handler for
        error = _HTTP_ERROR_CODES.get(code, "malformed_request" if code < 500 else "internal_error")
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.1"   # always answer with a status line and headers
        self.close_connection = True
        body = json.dumps({"error": {"code": error, "message": message or error.replace("_", " ")}}).encode()
        self.send_response(code, message)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


def serve() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Handler.api = Api(Store(Gateway(), os.environ.get("DOSSIER_DATA_DIR") or "data"))
    port = int(os.environ.get("PORT") or 8080)
    server = Server(("0.0.0.0", port), Handler)
    log.info("listening on 0.0.0.0:%d", port)
    server.serve_forever()
