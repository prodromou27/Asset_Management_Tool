"""Explicit administrator bindings and protected-shell emergency access."""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from apps.audit.models import AuditEvent
from config.api import ApiError

from .catalog import SYSTEM_ADMIN
from .models import User
from .services import _check_password_policy, guard_last_entra_admin


def bind_identity(request, target, *, tenant_id, object_id):
    if tenant_id is not None:
        try:
            if UUID(settings.ITAM_ENTRA_TENANT_ID) != tenant_id:
                raise ValueError()
        except (ValueError, TypeError):
            raise serializers.ValidationError(
                {"tenant_id": ["Use the configured Entra tenant."]}
            ) from None
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=target.pk)
            if user.version != target.version:
                raise ApiError(
                    "VERSION_CONFLICT", "This account changed. Reload and try again.", 409
                )
            if (user.entra_tenant_id, user.entra_object_id) == (tenant_id, object_id):
                return user
            if request.user.pk == user.pk and request.session.get("itam_auth_method") == "entra":
                raise ApiError(
                    "SELF_IDENTITY_CHANGE",
                    "Another System Admin must change your sign-in binding.",
                    409,
                )
            before = {
                "tenant_id": str(user.entra_tenant_id or ""),
                "object_id": str(user.entra_object_id or ""),
            }
            if object_id is None:
                guard_last_entra_admin(user)
            user.entra_tenant_id, user.entra_object_id = tenant_id, object_id
            user.emergency_access_until = None
            user.session_epoch = F("session_epoch") + 1
            user.version = F("version") + 1
            user.save(
                update_fields=[
                    "entra_tenant_id",
                    "entra_object_id",
                    "session_epoch",
                    "version",
                    "emergency_access_until",
                    "modified_at",
                ]
            )
            user.refresh_from_db()
            audit.record(
                action="users.entra_binding",
                actor=request.user,
                request=request,
                object_type="user",
                object_id=user.pk,
                object_label=user.username,
                before=before,
                after={"tenant_id": str(tenant_id or ""), "object_id": str(object_id or "")},
            )
    except IntegrityError:
        raise ApiError(
            "IDENTITY_CONFLICT", "That Entra identity is already linked to an account.", 409
        ) from None
    return user


def open_emergency_access(username, password, reason, operator):
    """Called only by the protected-shell command; no HTTP route can open this window."""
    if not (settings.ITAM_ENTRA_ENABLED and settings.ITAM_ENTRA_ENFORCE):
        raise ValueError("Emergency windows require enforced Entra sign-in.")
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username=username, is_active=True).first()
        if user is None or not user.roles.filter(code=SYSTEM_ADMIN).exists():
            raise ValueError("Select an active named System Admin account.")
        password = serializers.CharField(max_length=128, trim_whitespace=False).run_validation(
            password
        )
        _check_password_policy(password, user)
        user.set_password(password)
        user.password_changed_at = timezone.now()
        user.must_change_password = False
        user.failed_login_count = 0
        user.locked_until = None
        user.session_epoch = F("session_epoch") + 1
        user.version = F("version") + 1
        user.emergency_access_until = timezone.now() + timedelta(minutes=15)
        user.save()
        user.refresh_from_db()
        audit.record(
            action="auth.emergency_opened",
            actor_label=f"cli:{operator}",
            source=AuditEvent.Source.CLI,
            object_type="user",
            object_id=user.pk,
            object_label=user.username,
            detail=reason,
            after={"expires_at": user.emergency_access_until.isoformat()},
        )
    return user
