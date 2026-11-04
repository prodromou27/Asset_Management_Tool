"""Read-only Microsoft Graph v1.0 client for the Intune connector.

GET only (adapters/http.py). The host is fixed to https://graph.microsoft.com and the
API version to v1.0; beta endpoints are never used. The bearer token comes from a
TokenProvider; on HTTP 401 the token is renewed once and the request repeated.
``@odata.nextLink`` continuation URLs are followed only when they point at the same
Graph host, https, port 443, no userinfo, and the expected collection path, so the
token can never be sent anywhere else.
"""

import re
from urllib.parse import urlparse

import httpx

from ..base import AuthError, SourceError, UnsafeTarget
from ..entra import TokenProvider
from ..http import ReadOnlyClient

GRAPH_BASE = "https://graph.microsoft.com"
API_VERSION = "/v1.0"
REQUIRED_PERMISSION = "DeviceManagementManagedDevices.Read.All"


class InvalidQuery(SourceError):
    """Graph answered 400 (for example an unsupported $select property)."""

    code = "SOURCE_INVALID_QUERY"


def _graph_error(response: httpx.Response) -> tuple[str, str]:
    try:
        body = response.json()
    except ValueError:
        return "", ""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "", ""
    message = str(error.get("message") or "").split("\n")[0][:200]
    return str(error.get("code") or "")[:60], message


class GraphClient(ReadOnlyClient):
    """Read-only client for a Microsoft API with Entra bearer tokens. Subclasses (Defender)
    change the fixed host, path prefix, labels and required permission."""

    base = GRAPH_BASE
    api_prefix = API_VERSION
    user_agent = "ITAM-Intune-Connector/1 (read-only)"
    source_label = "Microsoft Graph"
    required_permission = REQUIRED_PERMISSION
    license_hint = "and the tenant needs an active Intune license"
    # Continuations are allowed only for these collection paths (after the prefix).
    continuation_paths = ("/deviceManagement/managedDevices", "/deviceManagement/detectedApps")
    # ...and per-app device lists (Task 016a; app IDs are opaque path segments).
    continuation_patterns = (r"/deviceManagement/detectedApps/[^/]+/managedDevices",)

    def __init__(self, tokens: TokenProvider, **kwargs):
        kwargs.pop("auth_scheme", None)
        super().__init__(self.base, "", auth_scheme="bearer", **kwargs)
        self.tokens = tokens

    def close(self) -> None:
        super().close()
        self.tokens.close()

    @property
    def total_requests(self) -> int:
        return self.requests + self.tokens.requests

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.tokens.token()}"}

    def _on_unauthorized(self, response: httpx.Response) -> bool:
        # Expired or revoked token: get a new one and repeat the request once.
        self.tokens.invalidate()
        return True

    def check_continuation(self, url: str) -> str:
        super().check_continuation(url)
        path = urlparse(url).path
        allowed = path in {f"{self.api_prefix}{p}" for p in self.continuation_paths} or any(
            re.fullmatch(f"{re.escape(self.api_prefix)}{pattern}", path)
            for pattern in getattr(self, "continuation_patterns", ())
        )
        if not allowed:
            raise UnsafeTarget(
                f"{self.source_label} returned a continuation link for an unexpected "
                "resource; it was not followed."
            )
        return url

    def _handle(self, response: httpx.Response, url: str):
        status = response.status_code
        if status == 401:
            code, _ = _graph_error(response)
            detail = f"HTTP 401, {code}" if code else "HTTP 401"
            return AuthError(
                f"{self.source_label} rejected the access token ({detail}). Check the app "
                "registration and that admin consent was granted."
            )
        if status == 403:
            code, _ = _graph_error(response)
            return AuthError(
                f"{self.source_label} refused access (HTTP 403{f', {code}' if code else ''}). "
                f"The application needs the {self.required_permission} application permission "
                f"with admin consent, {self.license_hint}."
            )
        if status == 400:
            code, message = _graph_error(response)
            return InvalidQuery(
                f"{self.source_label} rejected the request (HTTP 400{f', {code}' if code else ''}"
                f"{f': {message}' if message else ''})."
            )
        result = super()._handle(response, url)
        if isinstance(result, SourceError) and status not in (404, 429) and status < 500:
            code, message = _graph_error(response)
            if code:
                return SourceError(f"{self.source_label} error {code}: {message or 'no detail'}")
        return result
