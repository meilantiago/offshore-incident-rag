"""PoliteClient with an injected clock, sleep and transport (AC-001-04)."""

from __future__ import annotations

import itertools
from collections.abc import Callable

import httpx
import pytest
import structlog

from offshore_rag.ingestion.http import FetchError, PoliteClient


@pytest.fixture(autouse=True)
def _default_logging() -> None:
    """Other tests configure structlog onto a captured stderr that is closed by now."""
    structlog.reset_defaults()


UA = "offshore-incident-rag-tests/0 (+https://example.org/repo)"


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make(
    handler: Callable[[httpx.Request], httpx.Response], t: FakeTime, rate: float = 2.0, retries: int = 3
) -> PoliteClient:
    return PoliteClient(UA, rate, retries, 5.0, clock=t.clock, sleep=t.sleep, transport=httpx.MockTransport(handler))


def test_spacing_is_at_least_one_over_rate() -> None:
    t = FakeTime()
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(t.now)
        assert request.headers["user-agent"] == UA
        return httpx.Response(200, content=b"x")

    client = make(handler, t, rate=2.0)
    for _ in range(4):
        client.get("http://h/a")
    assert all(b - a >= 0.5 - 1e-9 for a, b in itertools.pairwise(stamps))
    assert client.requests == 4 and client.bytes_downloaded == 4


@pytest.mark.parametrize("status", [429, 503])
def test_backoff_honours_retry_after(status: int) -> None:
    t = FakeTime()
    calls = iter([httpx.Response(status, headers={"Retry-After": "7"}), httpx.Response(200, content=b"ok")])
    client = make(lambda r: next(calls), t, rate=1000.0)
    result = client.get("http://h/a")
    assert result.status == 200 and result.attempts == 2
    assert 7.0 in t.sleeps
    assert client.retries == 1


def test_exponential_backoff_without_retry_after_and_give_up() -> None:
    t = FakeTime()
    client = make(lambda r: httpx.Response(503), t, rate=1000.0, retries=2)
    with pytest.raises(FetchError) as e:
        client.get("http://h/a")
    assert e.value.reason == "http_503" and e.value.attempts == 3
    delays = [s for s in t.sleeps if s >= 0.5]
    assert len(delays) == 2 and delays[1] > delays[0]


def test_timeout_is_retried() -> None:
    t = FakeTime()
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, content=b"ok")

    assert make(handler, t, rate=1000.0).get("http://h/a").attempts == 2


def test_404_is_not_retried() -> None:
    t = FakeTime()
    client = make(lambda r: httpx.Response(404), t)
    with pytest.raises(FetchError) as e:
        client.get("http://h/a")
    assert e.value.reason == "http_404" and e.value.attempts == 1 and client.retries == 0


def test_conditional_request_and_304() -> None:
    t = FakeTime()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"v1"'
        assert request.headers["if-modified-since"] == "Mon, 01 Jan 2024 00:00:00 GMT"
        return httpx.Response(304)

    result = make(handler, t).get("http://h/a", etag='"v1"', last_modified="Mon, 01 Jan 2024 00:00:00 GMT")
    assert result.status == 304 and result.content == b""


def test_validators_are_returned() -> None:
    t = FakeTime()
    resp = httpx.Response(200, content=b"x", headers={"ETag": '"e"', "Last-Modified": "lm"})
    result = make(lambda r: resp, t).get("http://h/a")
    assert (result.etag, result.last_modified) == ('"e"', "lm")


def test_redirects_are_followed_through_the_rate_limiter() -> None:
    t = FakeTime()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"})
        return httpx.Response(200, content=b"new")

    client = make(handler, t, rate=1.0)
    result = client.get("http://h/old")
    assert result.content == b"new" and result.attempts == 2 and client.requests == 2
    assert sum(t.sleeps) >= 1.0


def test_robots_disallow_and_missing_robots() -> None:
    t = FakeTime()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "none":
            return httpx.Response(404)
        return httpx.Response(200, content=b"User-agent: *\nDisallow: /private/\n")

    client = make(handler, t, rate=1000.0)
    assert client.allowed("http://h/public/a")
    assert not client.allowed("http://h/private/a")
    assert client.allowed("http://none/private/a")
