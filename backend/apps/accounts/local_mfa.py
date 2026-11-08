"""Optional local TOTP, encrypted at rest, with atomic replay/recovery protection."""

import hashlib
import re
import secrets
import time
from datetime import timedelta

import pyotp
from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditEvent
from apps.imports.crypto import decrypt, encrypt
from config.api import ApiError

from .models import SecuritySettings, User

PURPOSE = b"itam-accounts-local-totp-v1"


def code_hash(code):
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def accept_factor(user, code):
    """Caller holds the user row lock; successful factors are consumed in that transaction."""
    hashed = code_hash(code)
    if hashed in user.mfa_recovery_hashes:
        user.mfa_recovery_hashes = [item for item in user.mfa_recovery_hashes if item != hashed]
        user.save(update_fields=["mfa_recovery_hashes"])
        return True
    secret = decrypt(user.mfa_secret, PURPOSE)
    if not secret or not re.fullmatch(r"[0-9]{6}", code):
        return False
    totp = pyotp.TOTP(secret.decode())
    step = int(time.time()) // totp.interval
    for candidate in (step - 1, step, step + 1):
        if candidate > user.mfa_last_step and secrets.compare_digest(
            totp.at(candidate * totp.interval), code
        ):
            user.mfa_last_step = candidate
            user.save(update_fields=["mfa_last_step"])
            return True
    return False


def _reauth(request, user, password, code, *, factor=False):
    from .services import _register_failed_attempt

    valid = user.is_active and user.local_login_enabled and not user.is_locked
    valid = user.check_password(password) and valid
    if valid and factor and user.mfa_enabled:
        valid = accept_factor(user, code)
    if not valid:
        _register_failed_attempt(request, user, SecuritySettings.load())
        return False
    return True


def manage(request, action, password, code=""):
    """Fresh password plus existing factor for removal; pending setup never authenticates."""
    failed = False
    response = {}
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not _reauth(request, user, password, code, factor=action == "disable"):
            failed = True
        elif action == "setup":
            if user.mfa_enabled:
                raise ApiError(
                    "MFA_ALREADY_ENABLED", "Disable the existing authenticator first.", 409
                )
            secret = pyotp.random_base32()
            user.mfa_pending_secret = encrypt(secret.encode(), PURPOSE)
            user.mfa_pending_until = timezone.now() + timedelta(minutes=10)
            user.save(update_fields=["mfa_pending_secret", "mfa_pending_until"])
            response = {
                "secret": secret,
                "provisioning_uri": pyotp.TOTP(secret).provisioning_uri(
                    user.username, issuer_name="ITAM"
                ),
            }
            audit.record(
                action="auth.mfa_setup",
                actor=user,
                request=request,
                object_type="user",
                object_id=user.pk,
            )
        elif action == "confirm":
            pending = user.mfa_pending_until and user.mfa_pending_until > timezone.now()
            secret = decrypt(user.mfa_pending_secret, PURPOSE) if pending else None
            if user.mfa_enabled or not secret:
                failed = True
            else:
                user.mfa_secret, user.mfa_last_step = user.mfa_pending_secret, -1
                if not accept_factor(user, code):
                    user.mfa_secret = b""
                    failed = True
                else:
                    recovery = [secrets.token_hex(16) for _ in range(10)]
                    user.mfa_recovery_hashes = [code_hash(item) for item in recovery]
                    response = {"recovery_codes": recovery}
                    _save_factor_change(request, user, "enabled")
            if failed:
                from .services import _register_failed_attempt

                _register_failed_attempt(request, user, SecuritySettings.load())
        elif action == "disable":
            user.mfa_secret = b""
            user.mfa_recovery_hashes = []
            user.mfa_last_step = -1
            _save_factor_change(request, user, "disabled")
    if failed:
        audit.record(
            action="auth.mfa_verification_failed",
            outcome=AuditEvent.Outcome.FAILURE,
            actor=request.user,
            request=request,
            object_type="user",
            object_id=request.user.pk,
            detail="Local MFA verification failed",
        )
        raise ApiError("MFA_FAILED", "Verification failed. Check your password and code.", 401)
    return response


def _save_factor_change(request, user, event):
    user.mfa_pending_secret = b""
    user.mfa_pending_until = None
    user.emergency_access_until = None
    user.session_epoch = F("session_epoch") + 1
    user.version = F("version") + 1
    user.save()
    user.refresh_from_db()
    update_session_auth_hash(request, user)
    if request.session.get("itam_auth_method") in {"local", "local_mfa"}:
        request.session["itam_auth_method"] = "local_mfa" if user.mfa_enabled else "local"
    audit.record(
        action=f"auth.mfa_{event}",
        actor=user,
        request=request,
        object_type="user",
        object_id=user.pk,
    )
