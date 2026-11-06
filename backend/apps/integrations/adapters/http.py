"""Shared read-only HTTP client for every connector.

The only HTTP method this class can send is GET; there is no code path for POST,
PATCH, PUT or DELETE (docs/05: integrations never write remote systems). Requests are
limited to the configured https base URL under the connector's API prefix, TLS is
always verified, redirects are refused, the target host is checked against
loopback/link-local/metadata addresses, and the token is attached per request and
never logged. Connector subclasses only interpret response bodies.
"""

import logging
import random
import time
from urllib.parse import urlparse

import httpx

from .base import (
    AuthError,
    NotSupported,
    SourceError,
    Unavailable,
    UnsafeTarget,
    check_base_url,
    check_host_addresses,
)
from .transport import PinnedTransport

logger = logging.getLogger(__name__)
MAX_RETRY_AFTER = 300

# Stored on IntegrationInstance.auth_scheme; each connector allows a subset.
AUTH_HEADERS = {
    "bearer": lambda token: {"Authorization": f"Bearer {token}"},
    "x_auth_token": lambda token: {"X-Auth-Token": token},
    "authorization": lambda token: {"Authorization": token},
}


class ReadOnlyClient:
    api_prefix = ""
    user_agent = "ITAM-Connector/1 (read-only)"
    source_label = "The source"

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        auth_scheme: str = "bearer",
        timeout: float = 30,
        max_retries: int = 3,
        requests_per_second: float = 5,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
        resolver=None,
    ):
        if auth_scheme not in AUTH_HEADERS:
            raise ValueError(f"Unknown auth scheme {auth_scheme!r}")
        self.base_url = check_base_url(base_url)
        self._token = token
        self._auth_scheme = auth_scheme
        self.max_retries = max_retries
        self.min_interval = 1.0 / max(requests_per_second, 0.1)
        self._sleep = sleep
        self._last_request = 0.0
        self.requests = 0
        host = urlparse(self.base_url).hostname
        if transport is None:
            transport = PinnedTransport(self.base_url, verify=verify, resolver=resolver)
        elif resolver is not None:
            check_host_addresses(host, resolver, urlparse(self.base_url).port or 443)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            verify=verify if verify is not False else True,  # verification cannot be disabled
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )

    def __repr__(self):
        return f"{type(self).__name__}({self.base_url!r})"

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _throttle(self) -> None:
        wait = self._last_request + self.min_interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET {api_prefix}{path}. Raises AuthError, NotSupported, Unavailable or SourceError."""
        if path and not path.startswith("/"):
            raise ValueError("path must start with /")
        return self._send(f"{self.api_prefix}{path}", params)

    def get_continuation(self, url: str) -> dict:
        """GET an absolute continuation URL returned by the source (e.g. @odata.nextLink).
        The URL must pass ``check_continuation``; credentials are never sent elsewhere."""
        return self._send(self.check_continuation(url), None)

    def check_continuation(self, url: str) -> str:
        """Same scheme, host and port as the base URL, under the API prefix, no userinfo
        or fragment. Raises UnsafeTarget otherwise. Connectors may narrow this further."""
        base = urlparse(self.base_url)
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower() != (base.hostname or "").lower()
            or (parsed.port or 443) != (base.port or 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.startswith(urlparse(f"{self.base_url}{self.api_prefix}").path)
        ):
            raise UnsafeTarget(
                f"{self.source_label} returned a continuation link outside its API; "
                "it was not followed."
            )
        return url

    def _auth_headers(self) -> dict:
        return AUTH_HEADERS[self._auth_scheme](self._token)

    def _on_unauthorized(self, response: httpx.Response) -> bool:
        """Called once per request on HTTP 401. Return True to retry the request with
        fresh credentials (e.g. an expired OAuth token). Static tokens cannot refresh."""
        return False

    def _send(self, url: str, params: dict | None) -> dict:
        label = url if len(url) <= 120 else f"{url[:117]}..."
        attempt = 0
        refreshed = False
        while True:
            self._throttle()
            self.requests += 1
            try:
                response = self._client.request(
                    "GET", url, params=params, headers=self._auth_headers()
                )
            except httpx.TimeoutException as exc:
                error: SourceError = Unavailable(
                    f"{self.source_label} did not respond within the timeout ({label})."
                )
                cause: Exception | None = exc
            except httpx.TransportError as exc:
                error = Unavailable(
                    f"Cannot connect to {self.source_label} ({type(exc).__name__})."
                )
                cause = exc
            else:
                if (
                    response.status_code == 401
                    and not refreshed
                    and self._on_unauthorized(response)
                ):
                    refreshed = True
                    logger.info("%s credentials refreshed after HTTP 401", self.source_label)
                    continue
                result = self._handle(response, label)
                if not isinstance(result, SourceError):
                    return result
                error, cause = result, None
                if response.status_code == 429 and attempt < self.max_retries:
                    attempt += 1
                    delay = self._retry_after(response)
                    logger.info("%s rate limited; retrying in %.1fs", self.source_label, delay)
                    self._sleep(delay)
                    continue
            if error.retryable and attempt < self.max_retries:
                attempt += 1
                delay = min(2 ** (attempt - 1), 30) + random.uniform(0, 0.5)  # noqa: S311
                if cause is None and "Retry-After" in response.headers:
                    delay = self._retry_after(response)  # e.g. 503 with Retry-After
                logger.info("Request failed (%s); retry %d in %.1fs", error.code, attempt, delay)
                self._sleep(delay)
                continue
            raise error from cause

    # --- Response interpretation (connectors override the body hooks) ----------------

    def _handle(self, response: httpx.Response, url: str):
        status = response.status_code
        if status in (401, 403):
            return AuthError(
                f"{self.source_label} rejected the API token (HTTP {status}). "
                "Check the token and its read-only role."
            )
        if status == 404:
            return self._not_found(self._json(response), url)
        if status == 429:
            return Unavailable(f"{self.source_label} rate limit reached.")
        if 300 <= status < 400:
            return SourceError(
                f"{self.source_label} answered with a redirect; redirects are refused."
            )
        if status >= 500:
            return Unavailable(f"{self.source_label} server error (HTTP {status}).")
        if status != 200:
            return SourceError(f"Unexpected {self.source_label} response (HTTP {status}).")
        body = self._json(response)
        if body is None:
            return SourceError(f"{self.source_label} returned a response that is not JSON.")
        if not isinstance(body, dict):
            return SourceError(f"{self.source_label} returned an unexpected JSON shape.")
        return self._body(body)

    def _not_found(self, body, url: str):
        return NotSupported(f"{url} is not available on this {self.source_label} version.")

    def _body(self, body: dict):
        return body

    @staticmethod
    def _json(response: httpx.Response):
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        try:
            return min(float(response.headers.get("Retry-After", "5")), MAX_RETRY_AFTER)
        except ValueError:
            return 5.0
