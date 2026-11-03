"""Read-only LibreNMS API v0 client.

The only HTTP method this class can send is GET; there is no code path for POST,
PATCH, PUT or DELETE (docs/05: never alter LibreNMS). Requests are limited to the
configured https base URL under /api/v0, TLS is always verified, redirects are
refused, the target host is re-checked against loopback/link-local/metadata
addresses, and the token is attached per request and never logged.
"""

import logging
import random
import time
from urllib.parse import urlparse

import httpx

from ..base import (
    AuthError,
    NotSupported,
    SourceError,
    Unavailable,
    check_base_url,
    check_host_addresses,
)

logger = logging.getLogger(__name__)
API_PREFIX = "/api/v0"
MAX_RETRY_AFTER = 300
USER_AGENT = "ITAM-LibreNMS-Connector/1 (read-only)"


class LibreNMSClient:
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
        self.base_url = check_base_url(base_url)
        self._token = token
        self._auth_scheme = auth_scheme
        self.max_retries = max_retries
        self.min_interval = 1.0 / max(requests_per_second, 0.1)
        self._sleep = sleep
        self._last_request = 0.0
        self.requests = 0
        host = urlparse(self.base_url).hostname
        if resolver is not None:
            check_host_addresses(host, resolver)
        elif transport is None:
            check_host_addresses(host)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            verify=verify if verify is not False else True,  # verification cannot be disabled
            follow_redirects=False,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )

    def __repr__(self):
        return f"LibreNMSClient({self.base_url!r})"

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _auth_headers(self) -> dict:
        if self._auth_scheme == "x_auth_token":
            return {"X-Auth-Token": self._token}
        return {"Authorization": f"Bearer {self._token}"}

    def _throttle(self) -> None:
        wait = self._last_request + self.min_interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET /api/v0{path}. Raises AuthError, NotSupported, Unavailable or SourceError."""
        if path and not path.startswith("/"):
            raise ValueError("path must start with /")
        url = f"{API_PREFIX}{path}"
        attempt = 0
        while True:
            self._throttle()
            self.requests += 1
            try:
                response = self._client.request(
                    "GET", url, params=params, headers=self._auth_headers()
                )
            except httpx.TimeoutException as exc:
                error: SourceError = Unavailable(
                    f"LibreNMS did not respond within the timeout ({url})."
                )
                cause: Exception = exc
            except httpx.TransportError as exc:
                error, cause = (
                    Unavailable(f"Cannot connect to LibreNMS ({type(exc).__name__})."),
                    exc,
                )
            else:
                result = self._handle(response, url)
                if not isinstance(result, SourceError):
                    return result
                error, cause = result, None
                if response.status_code == 429:
                    delay = self._retry_after(response)
                    if attempt < self.max_retries:
                        attempt += 1
                        logger.info("LibreNMS rate limited; retrying in %.1fs", delay)
                        self._sleep(delay)
                        continue
            if error.retryable and attempt < self.max_retries:
                attempt += 1
                delay = min(2 ** (attempt - 1), 30) + random.uniform(0, 0.5)  # noqa: S311
                logger.info(
                    "LibreNMS request failed (%s); retry %d in %.1fs", error.code, attempt, delay
                )
                self._sleep(delay)
                continue
            raise error from cause

    def _handle(self, response: httpx.Response, url: str):
        status = response.status_code
        if status in (401, 403):
            return AuthError(
                f"LibreNMS rejected the API token (HTTP {status}). "
                "Check the token and its read-only role."
            )
        if status == 404:
            # LibreNMS answers some empty lists with 404 + {"status": "error", "message":
            # "No ... found"}; that is an empty result, not a missing route.
            body = self._json(response)
            if isinstance(body, dict) and _is_empty_message(body):
                return {}
            return NotSupported(f"{url} is not available on this LibreNMS version.")
        if status == 429:
            error = Unavailable("LibreNMS rate limit reached.")
            return error
        if 300 <= status < 400:
            return SourceError("LibreNMS answered with a redirect; redirects are refused.")
        if status >= 500:
            return Unavailable(f"LibreNMS server error (HTTP {status}).")
        if status != 200:
            return SourceError(f"Unexpected LibreNMS response (HTTP {status}).")
        body = self._json(response)
        if body is None:
            return SourceError("LibreNMS returned a response that is not JSON.")
        if not isinstance(body, dict):
            return SourceError("LibreNMS returned an unexpected JSON shape.")
        if body.get("status") == "error":
            if _is_empty_message(body):
                return {}
            return SourceError(f"LibreNMS error: {str(body.get('message', ''))[:200]}")
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


def _is_empty_message(body: dict) -> bool:
    message = str(body.get("message", "")).strip().lower()
    return body.get("status") == "error" and (message.startswith("no ") or "not found" in message)
