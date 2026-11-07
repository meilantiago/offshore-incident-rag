"""A threaded local HTTP server that stands in for bsee.gov in tests.

Each path serves a fixed resource (bytes + content type, optional ETag / Last-Modified with 304 on conditional
requests) and can be scripted to fail a number of times first (HTTP 429, HTTP 5xx or a timeout). Every request is
recorded with its headers and a monotonic timestamp, so tests can check the User-Agent, the rate limit and the
number of attempts. Unknown paths return 404.

Paths are matched after percent-decoding: first the exact path + query, then the bare path (only when the request
has no query), then a fallback registered for that path with `any_query=True` (for example "any listing page past
the end").
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

DEFAULT_ROBOTS = b"User-agent: *\nDisallow: /admin/\nDisallow: /search/\n"


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    target: str  # raw request target as sent by the client (path + query, still percent-encoded)
    path: str  # decoded path without query
    headers: dict[str, str]  # header names lower-cased
    time: float  # time.monotonic() when the request line was read
    status: int  # status code the server answered (0 when the client went away during a timeout)

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


@dataclass
class Failure:
    """One scripted failed attempt: an HTTP status, or `status=None` for a timeout (the server stalls)."""

    status: int | None
    retry_after: str | None = "0"


@dataclass
class Resource:
    body: bytes
    content_type: str = "application/pdf"
    status: int = 200
    etag: str | None = None
    last_modified: str | None = None
    location: str | None = None  # for redirects
    failures: list[Failure] = field(default_factory=list)


class FixtureServer:
    """Local HTTP server. Use as a context manager or call `start()` / `stop()`."""

    def __init__(self, timeout_stall_seconds: float = 3.0) -> None:
        self._resources: dict[str, Resource] = {}
        self._fallbacks: dict[str, Resource] = {}
        self._lock = threading.Lock()
        self._requests: list[RecordedRequest] = []
        self.timeout_stall_seconds = timeout_stall_seconds
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.add("/robots.txt", DEFAULT_ROBOTS, content_type="text/plain")

    # -- lifecycle -------------------------------------------------------------------------------------------
    def start(self) -> FixtureServer:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                server._handle(self)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="fixture-http", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> FixtureServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    @property
    def base_url(self) -> str:
        assert self._httpd is not None, "server not started"
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, target: str) -> str:
        return self.base_url + target

    # -- scripting -------------------------------------------------------------------------------------------
    def add(
        self,
        target: str,
        body: bytes | str,
        *,
        content_type: str = "application/pdf",
        status: int = 200,
        etag: str | None = None,
        last_modified: str | None = None,
        any_query: bool = False,
    ) -> None:
        """Serve `body` at `target` (path, optionally with `?query`). Replaces any previous resource there."""
        data = body.encode("utf-8") if isinstance(body, str) else body
        with self._lock:
            table = self._fallbacks if any_query else self._resources
            table[_key(target)] = Resource(data, content_type, status, etag, last_modified)

    def add_html(self, target: str, html: str, *, any_query: bool = False) -> None:
        self.add(target, html, content_type="text/html; charset=utf-8", any_query=any_query)

    def redirect(self, target: str, location: str, status: int = 301) -> None:
        with self._lock:
            self._resources[_key(target)] = Resource(b"", "text/html", status, location=location)

    def set_body(self, target: str, body: bytes, *, etag: str | None = None, last_modified: str | None = None) -> None:
        """Change the bytes served at `target` (a new version of the file), keeping its content type."""
        with self._lock:
            res = self._resources[_key(target)]
            res.body = body
            res.etag = etag
            res.last_modified = last_modified

    def fail(self, target: str, times: int, status: int | None, retry_after: str | None = "0") -> None:
        """Make the next `times` requests to `target` fail with `status` (None = stall past the client timeout)."""
        with self._lock:
            res = self._resources.get(_key(target))
            if res is None:
                res = Resource(b"", status=404)
                self._resources[_key(target)] = res
            res.failures.extend(Failure(status, retry_after) for _ in range(times))

    # -- inspection ------------------------------------------------------------------------------------------
    @property
    def requests(self) -> list[RecordedRequest]:
        with self._lock:
            return list(self._requests)

    def requests_for(self, target: str) -> list[RecordedRequest]:
        path = unquote(urlsplit(target).path)
        return [r for r in self.requests if r.path == path]

    def iter_user_agents(self) -> Iterator[str | None]:
        return (r.header("user-agent") for r in self.requests)

    def clear_requests(self) -> None:
        with self._lock:
            self._requests.clear()

    # -- request handling ------------------------------------------------------------------------------------
    def _lookup(self, target: str) -> Resource | None:
        split = urlsplit(target)
        full = _key(target)
        res = self._resources.get(full)
        if res is not None:
            return res
        path = unquote(split.path)
        if not split.query and path in self._resources:
            return self._resources[path]
        return self._fallbacks.get(path)

    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        now = time.monotonic()
        headers = {k.lower(): v for k, v in h.headers.items()}
        with self._lock:
            res = self._lookup(h.path)
            failure = res.failures.pop(0) if res is not None and res.failures else None
            record_index = len(self._requests)
            self._requests.append(
                RecordedRequest("GET", h.path, unquote(urlsplit(h.path).path), headers, now, status=0)
            )

        def answered(status: int) -> None:
            with self._lock:
                r = self._requests[record_index]
                self._requests[record_index] = RecordedRequest(r.method, r.target, r.path, r.headers, r.time, status)

        try:
            if failure is not None:
                if failure.status is None:
                    time.sleep(self.timeout_stall_seconds)
                    self._send(h, 504, b"stalled", "text/plain", {})
                    answered(504)
                    return
                extra = {"Retry-After": failure.retry_after} if failure.retry_after is not None else {}
                self._send(h, failure.status, b"scripted failure", "text/plain", extra)
                answered(failure.status)
                return
            if res is None:
                self._send(h, 404, b"not found", "text/plain", {})
                answered(404)
                return
            if res.location is not None:
                self._send(h, res.status, b"", "text/html", {"Location": res.location})
                answered(res.status)
                return
            validators: dict[str, str] = {}
            if res.etag:
                validators["ETag"] = res.etag
            if res.last_modified:
                validators["Last-Modified"] = res.last_modified
            inm = headers.get("if-none-match")
            ims = headers.get("if-modified-since")
            if (res.etag and inm == res.etag) or (res.last_modified and not inm and ims == res.last_modified):
                self._send(h, 304, b"", None, validators)
                answered(304)
                return
            self._send(h, res.status, res.body, res.content_type, validators)
            answered(res.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # The client gave up (its timeout fired). That is the point of a scripted timeout.
            return

    @staticmethod
    def _send(
        h: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str | None, extra: dict[str, str]
    ) -> None:
        h.send_response(status)
        if content_type:
            h.send_header("Content-Type", content_type)
        for k, v in extra.items():
            h.send_header(k, v)
        h.send_header("Content-Length", str(0 if status == 304 else len(body)))
        h.end_headers()
        if status != 304 and body:
            h.wfile.write(body)
        h.wfile.flush()


def _key(target: str) -> str:
    split = urlsplit(target)
    return unquote(split.path) + (f"?{split.query}" if split.query else "")
