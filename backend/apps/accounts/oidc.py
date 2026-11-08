"""Single-tenant Entra OIDC. Authlib owns OAuth/PKCE and signed ID-token validation."""

import hashlib
import json
import re
import time
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from authlib.integrations.django_client import DjangoOAuth2App, OAuth
from authlib.integrations.requests_client import OAuth2Session
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.integrations.secrets import SecretError, resolve

from .catalog import SYSTEM_ADMIN
from .models import OidcAttempt, User

METHOD = "itam_auth_method"
POLICY = "itam_auth_policy"
EXPIRES = "itam_factor_expires"
PENDING = "itam_oidc_pending"
NEXT = "itam_oidc_next"
CALLBACK = "/api/v1/auth/entra/callback/"


class OidcFailure(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def policy_digest():
    return digest(
        json.dumps(
            [
                settings.ITAM_ENTRA_TENANT_ID,
                settings.ITAM_ENTRA_CLIENT_ID,
                settings.ITAM_ENTRA_REDIRECT_URI,
                settings.ITAM_ENTRA_AUTH_CONTEXT,
                settings.ITAM_ENTRA_MFA_POLICY_VERIFIED,
                settings.ITAM_ENTRA_ENABLED,
            ]
        )
    )


def configuration():
    if not settings.ITAM_ENTRA_ENABLED or settings.DEBUG:
        raise OidcFailure()
    tenant = str(UUID(settings.ITAM_ENTRA_TENANT_ID))
    client_id = str(UUID(settings.ITAM_ENTRA_CLIENT_ID))
    uri = urlsplit(settings.ITAM_ENTRA_REDIRECT_URI)
    context = settings.ITAM_ENTRA_AUTH_CONTEXT
    if (
        uri.scheme != "https"
        or getattr(settings, "PUBLIC_SCHEME", "https") != "https"
        or not uri.hostname
        or uri.username
        or uri.password
        or uri.path != CALLBACK
        or uri.query
        or uri.fragment
        or not re.fullmatch(r"c(?:[1-9]|[1-9][0-9])", context)
        or not settings.ITAM_ENTRA_MFA_POLICY_VERIFIED
    ):
        raise OidcFailure()
    secret = resolve(settings.ITAM_ENTRA_CLIENT_SECRET_REF, prefix="ITAM_ENTRA_")
    return tenant, client_id, secret


def ready():
    try:
        tenant, _, _ = configuration()
        admins = User.objects.filter(is_active=True, roles__code=SYSTEM_ADMIN)
        return (
            admins.distinct().count() >= 2
            and admins.filter(entra_tenant_id=tenant, entra_object_id__isnull=False).exists()
        )
    except (ValueError, TypeError, OidcFailure, SecretError):
        # Only a boolean leaves this public discovery seam; configuration secrets never do.
        return False


class EntraSession(OAuth2Session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trust_env = False

    def request(self, method, url, **kwargs):
        kwargs.update(timeout=10, verify=True, allow_redirects=False)
        return super().request(method, url, **kwargs)


class EntraApp(DjangoOAuth2App):
    client_cls = EntraSession


def client():
    tenant, client_id, secret = configuration()
    authority = f"https://login.microsoftonline.com/{tenant}"
    app = OAuth(cache=cache).register(
        "entra",
        client_cls=EntraApp,
        client_id=client_id,
        client_secret=secret,
        authorize_url=f"{authority}/oauth2/v2.0/authorize",
        access_token_url=f"{authority}/oauth2/v2.0/token",
        client_kwargs={
            "scope": "openid",
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": "client_secret_post",
        },
        issuer=f"{authority}/v2.0",
        jwks_uri=f"{authority}/discovery/v2.0/keys",
        id_token_signing_alg_values_supported=["RS256"],
    )
    app.framework.expires_in = 300
    return app


def start(request, next_path="/"):
    if not ready() or request.user.is_authenticated:
        raise OidcFailure()
    app = client()
    if old := request.session.pop(PENDING, None):
        app.framework.clear_state_data(request.session, old)
        OidcAttempt.objects.filter(state_digest=digest(old)).delete()
    request.session.cycle_key()
    claims = json.dumps(
        {
            "id_token": {
                "acrs": {
                    "essential": True,
                    "values": [settings.ITAM_ENTRA_AUTH_CONTEXT],
                }
            }
        }
    )
    response = app.authorize_redirect(
        request,
        settings.ITAM_ENTRA_REDIRECT_URI,
        claims=claims,
        response_mode="query",
        prompt="select_account",
    )
    from urllib.parse import parse_qs

    state = parse_qs(urlsplit(response["Location"]).query)["state"][0]
    OidcAttempt.objects.filter(expires_at__lt=timezone.now()).delete()
    OidcAttempt.objects.create(
        state_digest=digest(state),
        browser_digest=digest(request.session.session_key),
        policy_digest=policy_digest(),
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    request.session[PENDING] = state
    request.session[NEXT] = next_path
    return response["Location"]


def consume(request):
    state = request.GET.get("state", "")
    expected = request.session.get(PENDING)
    if not state or len(state) > 256 or state != expected or not request.session.session_key:
        raise OidcFailure()
    count, _ = OidcAttempt.objects.filter(
        state_digest=digest(state),
        browser_digest=digest(request.session.session_key),
        policy_digest=policy_digest(),
        expires_at__gt=timezone.now(),
    ).delete()
    if count != 1:
        raise OidcFailure()
    request.session.pop(PENDING, None)
    return request.session.pop(NEXT, "/")


def finish(request):
    next_path = consume(request)  # Atomic one-use receipt, before any token request.
    app = client()
    try:
        token = app.authorize_access_token(request, leeway=30)
    finally:
        app.framework.clear_state_data(request.session, request.GET.get("state"))
    claims = token.get("userinfo")
    acrs = claims.get("acrs") if claims else None
    if (
        not isinstance(acrs, list)
        or not isinstance(claims.get("sub"), str)
        or not claims["sub"].strip()
        or settings.ITAM_ENTRA_AUTH_CONTEXT not in acrs
        or claims["exp"] <= time.time()
    ):
        raise OidcFailure()
    tenant, _, _ = configuration()
    if str(UUID(claims.get("tid", ""))) != tenant:
        raise OidcFailure()
    object_id = str(UUID(claims.get("oid", "")))
    from django.db import transaction

    from .services import complete_session

    with transaction.atomic():
        user = (
            User.objects.select_for_update()
            .filter(
                entra_tenant_id=tenant,
                entra_object_id=object_id,
                is_active=True,
            )
            .first()
        )
        if user is None or user.is_locked:
            raise OidcFailure()
        complete_session(request, user, method="entra", expires=claims["exp"])
    # Tokens are not stored or returned; application roles/site grants stay authoritative.
    return user, next_path
