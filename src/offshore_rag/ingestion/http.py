"""PoliteClient: User-Agent, token-bucket rate limit, bounded retries with backoff, conditional requests, robots.txt."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import structlog

log = structlog.get_logger()

MAX_REDIRECTS = 5
BACKOFF_BASE_SECONDS = 0.5
MAX_RETRY_AFTER_SECONDS = 300.0
REDIRECT_STATUSES = (301, 302, 303, 307, 308)


@dataclass(frozen=True)
class FetchResult:
    status: int  # 200, or 304 when a conditional request found nothing new
    content: bytes
    etag: str | None
    last_modified: str | None
    attempts: int  # HTTP requests made for this call, redirects and retries included


class FetchError(Exception):
    """A download failed for good. `reason` is short and stable, e.g. `http_404`, `http_503`, `timeout`."""

    def __init__(self, url: str, reason: str, attempts: int) -> None:
        super().__init__(f"{url}: {reason} after {attempts} attempt(s)")
        self.url = url
        self.reason = reason
        self.attempts = attempts


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        rate_per_second: float,
        max_retries: int,
        timeout: float,
        clock: Callable[[], float] = time.perf_counter,  # high resolution: monotonic ticks at 15.6 ms on Windows
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._interval = 1.0 / rate_per_second
        self._max_retries = max_retries
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        self._user_agent = user_agent
        self._client = httpx.Client(
            headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=False, transport=transport
        )
        self.requests = 0
        self.retries = 0
        self.bytes_downloaded = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- rate limit ------------------------------------------------------------------------------------------
    def _wait_for_slot(self) -> None:
        now = self._clock()
        start = max(now, self._next_slot)
        if start > now:
            self._sleep(start - now)
        self._next_slot = start + self._interval

    def _request_done(self) -> None:
        # The next request also waits a full interval after this one completed, so the spacing seen by the server
        # holds even when this request was slow to reach it (connection setup).
        self._next_slot = max(self._next_slot, self._clock() + self._interval)

    # -- requests --------------------------------------------------------------------------------------------
    def get(self, url: str, etag: str | None = None, last_modified: str | None = None) -> FetchResult:
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        attempts = 0
        retries_done = 0
        current = url
        redirects = 0
        while True:
            self._wait_for_slot()
            attempts += 1
            self.requests += 1
            try:
                try:
                    response = self._client.get(current, headers=headers)
                finally:
                    self._request_done()
            except httpx.InvalidURL as e:
                raise FetchError(url, "invalid_url", attempts) from e
            except httpx.TimeoutException:
                reason, retry_after = "timeout", None
            except httpx.DecodingError as e:
                raise FetchError(url, f"decoding_error:{type(e).__name__}", attempts) from e
            except httpx.TransportError as e:
                reason, retry_after = f"connection_error:{type(e).__name__}", None
            else:
                status = response.status_code
                if status in REDIRECT_STATUSES and "location" in response.headers:
                    redirects += 1
                    if redirects > MAX_REDIRECTS:
                        raise FetchError(url, "too_many_redirects", attempts)
                    try:
                        current = urljoin(current, response.headers["location"])
                    except ValueError as e:
                        raise FetchError(url, "invalid_redirect", attempts) from e
                    continue
                if status in (200, 304):
                    self.bytes_downloaded += len(response.content)
                    return FetchResult(
                        status,
                        response.content,
                        response.headers.get("etag"),
                        response.headers.get("last-modified"),
                        attempts,
                    )
                if status != 429 and not 500 <= status <= 599:
                    raise FetchError(url, f"http_{status}", attempts)
                reason, retry_after = f"http_{status}", _parse_retry_after(response.headers.get("retry-after"))
            if retries_done >= self._max_retries:
                raise FetchError(url, reason, attempts)
            delay = retry_after if retry_after is not None else _backoff(retries_done)
            retries_done += 1
            self.retries += 1
            log.info("retrying", url=url, reason=reason, retry=retries_done, delay_seconds=round(delay, 3))
            self._sleep(delay)

    # -- robots.txt ------------------------------------------------------------------------------------------
    def allowed(self, url: str) -> bool:
        """Whether robots.txt lets this client fetch `url`. A missing robots.txt allows everything."""
        try:
            parts = urlsplit(url)
            parts.port  # noqa: B018 - raises ValueError for a non-numeric or out-of-range port
        except ValueError as e:
            raise FetchError(url, "invalid_url", 0) from e
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            try:
                result = self.get(origin + "/robots.txt")
            except FetchError as e:
                if not e.reason.startswith("http_4"):
                    raise
                parser.parse([])  # 4xx: no robots.txt, everything allowed
            else:
                parser.parse(result.content.decode("utf-8", errors="replace").splitlines())
            self._robots[origin] = parser
        return parser.can_fetch(self._user_agent, url)


def _backoff(retry_index: int) -> float:
    base = BACKOFF_BASE_SECONDS * (2.0**retry_index)
    return base + random.uniform(0, base / 2)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = when.timestamp() - time.time()
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)
