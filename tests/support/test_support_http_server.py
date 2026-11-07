"""Self-checks of the scripted local HTTP server (test infrastructure, not acceptance tests)."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from tests.support.http_server import FixtureServer


@pytest.fixture
def server() -> Iterator[FixtureServer]:
    with FixtureServer(timeout_stall_seconds=1.0) as s:
        yield s


def _get(url: str, headers: dict[str, str] | None = None, timeout: float = 5.0) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers.items())


def test_support_serves_files_and_records_headers(server: FixtureServer) -> None:
    server.add("/files/a b.pdf", b"%PDF-data")
    status, body, headers = _get(server.url("/files/a%20b.pdf"), {"User-Agent": "probe/1"})
    assert (status, body) == (200, b"%PDF-data")
    assert headers["Content-Type"] == "application/pdf"
    [req] = server.requests_for("/files/a%20b.pdf")
    assert req.header("user-agent") == "probe/1"
    assert req.status == 200


def test_support_unknown_path_is_404_and_robots_is_served(server: FixtureServer) -> None:
    assert _get(server.url("/missing.pdf"))[0] == 404
    status, body, _ = _get(server.url("/robots.txt"))
    assert status == 200 and b"User-agent: *" in body


def test_support_scripted_failures_then_success(server: FixtureServer) -> None:
    server.add("/doc.pdf", b"ok")
    server.fail("/doc.pdf", 2, 503)
    statuses = [_get(server.url("/doc.pdf"))[0] for _ in range(3)]
    assert statuses == [503, 503, 200]
    server.fail("/doc.pdf", 1, 429)
    status, _, headers = _get(server.url("/doc.pdf"))
    assert status == 429 and headers["Retry-After"] == "0"
    assert len(server.requests_for("/doc.pdf")) == 4


def test_support_scripted_timeout_stalls_past_client_timeout(server: FixtureServer) -> None:
    server.add("/slow.pdf", b"ok")
    server.fail("/slow.pdf", 1, None)
    with pytest.raises((TimeoutError, socket.timeout, urllib.error.URLError)):
        _get(server.url("/slow.pdf"), timeout=0.3)
    assert _get(server.url("/slow.pdf"))[0] == 200
    assert len(server.requests_for("/slow.pdf")) == 2


def test_support_etag_and_last_modified_give_304(server: FixtureServer) -> None:
    server.add("/e.pdf", b"v1", etag='"v1"', last_modified="Wed, 01 Jan 2025 00:00:00 GMT")
    status, body, headers = _get(server.url("/e.pdf"))
    assert status == 200 and headers["ETag"] == '"v1"'
    assert _get(server.url("/e.pdf"), {"If-None-Match": '"v1"'})[0] == 304
    assert _get(server.url("/e.pdf"), {"If-Modified-Since": "Wed, 01 Jan 2025 00:00:00 GMT"})[0] == 304
    server.set_body("/e.pdf", b"v2", etag='"v2"')
    status, body, _ = _get(server.url("/e.pdf"), {"If-None-Match": '"v1"'})
    assert (status, body) == (200, b"v2")


def test_support_query_matching(server: FixtureServer) -> None:
    server.add_html("/list?page=1", "<p>one</p>")
    server.add_html("/list", "<p>default</p>", any_query=True)
    assert _get(server.url("/list?page=1"))[1] == b"<p>one</p>"
    assert _get(server.url("/list?page=7"))[1] == b"<p>default</p>"
    assert _get(server.url("/list"))[1] == b"<p>default</p>"


def test_support_redirect(server: FixtureServer) -> None:
    server.add_html("/new", "<p>here</p>")
    server.redirect("/old", "/new")
    status, body, _ = _get(server.url("/old"))  # urllib follows redirects
    assert (status, body) == (200, b"<p>here</p>")
    assert [r.status for r in server.requests] == [301, 200]


def test_support_timestamps_are_monotonic(server: FixtureServer) -> None:
    server.add("/t.pdf", b"x")
    for _ in range(3):
        _get(server.url("/t.pdf"))
    times = [r.time for r in server.requests]
    assert times == sorted(times) and len(times) == 3
