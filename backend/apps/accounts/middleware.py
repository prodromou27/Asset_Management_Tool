"""Enforces admin-configured idle and absolute session timeouts."""

import time

from django.conf import settings
from django.contrib.auth import logout

from apps.audit import services as audit

from .models import SecuritySettings

SESSION_AUTH_AT = "itam_auth_at"
SESSION_LAST_SEEN = "itam_last_seen"
# Avoid a session write on every request; activity is recorded at most once a minute.
_TOUCH_INTERVAL_SECONDS = 60


class SessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            policy = SecuritySettings.load()
            now = time.time()
            auth_at = request.session.get(SESSION_AUTH_AT, 0)
            last_seen = request.session.get(SESSION_LAST_SEEN, 0)
            idle_limit = policy.session_idle_timeout_minutes * 60
            absolute_limit = policy.session_absolute_timeout_hours * 3600
            valid_factor = True
            from .oidc import EXPIRES, METHOD, POLICY, policy_digest

            method = request.session.get(METHOD)
            if method in {"entra", "emergency"}:
                valid_factor = (
                    (settings.ITAM_ENTRA_ENABLED or method == "emergency")
                    and request.session.get(POLICY) == policy_digest()
                    and request.session.get(EXPIRES, 0) > now
                )
                if method == "emergency":
                    valid_factor = valid_factor and user.roles.filter(code="system_admin").exists()
            else:
                valid_factor = user.local_login_enabled and (
                    not user.mfa_enabled or method == "local_mfa"
                )
            if not valid_factor or now - last_seen > idle_limit or now - auth_at > absolute_limit:
                reason = (
                    "authentication policy"
                    if not valid_factor
                    else ("idle" if now - last_seen > idle_limit else "absolute")
                )
                audit.record(
                    action="auth.session_expired",
                    actor=user,
                    request=request,
                    object_type="user",
                    object_id=user.pk,
                    object_label=user.username,
                    detail=f"Session ended by {reason} timeout",
                )
                logout(request)
                request.session_expired = True
            elif now - last_seen > _TOUCH_INTERVAL_SECONDS:
                request.session[SESSION_LAST_SEEN] = now
        return self.get_response(request)
