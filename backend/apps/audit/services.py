"""Single entry point for writing audit events."""

import ipaddress
from collections.abc import Mapping
from typing import Any

from config.request_context import get_request_id

from .models import AuditEvent

REDACTED = "[redacted]"
_SENSITIVE_KEYS = ("password", "secret", "token", "key", "credential")


def redact(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {
        key: REDACTED if any(marker in key.lower() for marker in _SENSITIVE_KEYS) else value
        for key, value in values.items()
    }


def client_ip(request) -> str | None:
    """Client address, honouring X-Forwarded-For only for configured trusted proxies.

    Mirrors DRF throttling (NUM_PROXIES): take the entry appended by the outermost
    trusted proxy, never a client-supplied value.
    """
    if request is None:
        return None
    from django.conf import settings

    trusted = settings.REST_FRAMEWORK.get("NUM_PROXIES") or 0
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if trusted > 0 and forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if len(hops) >= trusted:
            return _valid_ip(hops[-trusted])
    return _valid_ip(request.META.get("REMOTE_ADDR"))


def _valid_ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None


def record(
    *,
    action: str,
    actor=None,
    actor_label: str | None = None,
    request=None,
    object_type: str = "",
    object_id: str = "",
    object_label: str = "",
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    outcome: str = AuditEvent.Outcome.SUCCESS,
    source: str = AuditEvent.Source.API,
    detail: str = "",
) -> AuditEvent:
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    if actor_label is None:
        actor_label = actor.username if actor is not None else "anonymous"
    return AuditEvent.objects.create(
        action=action,
        actor=actor,
        actor_label=actor_label[:255],
        object_type=object_type,
        object_id=str(object_id),
        object_label=object_label[:255],
        before=redact(before),
        after=redact(after),
        outcome=outcome,
        source=source,
        detail=detail[:500],
        request_id=get_request_id() or "",
        ip_address=client_ip(request),
    )
