"""Read-only ManageEngine Endpoint Central (on-premises) client.

GET only (see adapters/http.py). Paths carry their own API generation prefix
(/dcapi/... or /api/1.4/...) because the generation is detected per installation.
"""

from ..base import AuthError, SourceError
from ..http import ReadOnlyClient

# Words in an error envelope that mean the token or its role is the problem.
_AUTH_WORDS = ("auth", "token", "api key", "apikey", "permission", "unauthori", "privilege")


class EndpointCentralClient(ReadOnlyClient):
    api_prefix = ""
    user_agent = "ITAM-EndpointCentral-Connector/1 (read-only)"
    source_label = "Endpoint Central"

    def _body(self, body: dict):
        status = str(body.get("status", "")).lower()
        if status in ("error", "failure", "failed") or body.get("error_code"):
            code = str(body.get("error_code") or "").strip()[:20]
            message = str(
                body.get("error_description") or body.get("message") or body.get("error") or ""
            ).strip()[:200]
            label = f"Endpoint Central error{f' {code}' if code else ''}: {message or 'no detail'}"
            if any(word in message.lower() for word in _AUTH_WORDS):
                return AuthError(f"{label}. Check the API key and its read-only role.")
            return SourceError(label)
        return body
