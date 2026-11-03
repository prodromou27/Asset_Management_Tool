"""Read-only LibreNMS API v0 client (GET only; see adapters/http.py for the guarantees)."""

from ..base import SourceError
from ..http import ReadOnlyClient

API_PREFIX = "/api/v0"


class LibreNMSClient(ReadOnlyClient):
    api_prefix = API_PREFIX
    user_agent = "ITAM-LibreNMS-Connector/1 (read-only)"
    source_label = "LibreNMS"

    def _not_found(self, body, url: str):
        # LibreNMS answers some empty lists with 404 + {"status": "error", "message":
        # "No ... found"}; that is an empty result, not a missing route.
        if isinstance(body, dict) and _is_empty_message(body):
            return {}
        return super()._not_found(body, url)

    def _body(self, body: dict):
        if body.get("status") == "error":
            if _is_empty_message(body):
                return {}
            return SourceError(f"LibreNMS error: {str(body.get('message', ''))[:200]}")
        return body


def _is_empty_message(body: dict) -> bool:
    message = str(body.get("message", "")).strip().lower()
    return body.get("status") == "error" and (message.startswith("no ") or "not found" in message)
