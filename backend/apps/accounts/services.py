"""Account domain services. Views stay thin; every mutation is audited here."""

import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers, status

from apps.audit import services as audit
from apps.audit.models import AuditEvent
from config.api import ApiError

from .catalog import SYSTEM_ADMIN
from .middleware import SESSION_AUTH_AT, SESSION_LAST_SEEN
from .models import Role, SecuritySettings, User

LOGIN_FAILED_MESSAGE = "Sign-in failed. Check your username and password, or try again later."


def snapshot(user: User) -> dict:
    from apps.organizations.services import site_codes_for

    return {
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted(user.roles.values_list("code", flat=True)),
        "all_sites": user.all_sites,
        "sites": site_codes_for(user),
        "is_active": user.is_active,
        "local_login_enabled": user.local_login_enabled,
    }


def _check_password_policy(password: str, user: User | None, field: str = "password") -> None:
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({field: list(exc.messages)}) from exc


def _active_admin_ids(exclude: User | None = None) -> list:
    qs = User.objects.select_for_update().filter(is_active=True, roles__code=SYSTEM_ADMIN)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return list(qs.values_list("pk", flat=True))


def _guard_last_admin(target: User) -> None:
    required = 2 if settings.ITAM_ENTRA_ENABLED else 1
    if (
        target.roles.filter(code=SYSTEM_ADMIN).exists()
        and len(_active_admin_ids(exclude=target)) < required
    ):
        raise ApiError(
            "LAST_ADMIN",
            f"At least {required} active System Admin account(s) must remain.",
            status.HTTP_409_CONFLICT,
        )
    guard_last_entra_admin(target)


def guard_last_entra_admin(target):
    if not (
        settings.ITAM_ENTRA_ENABLED
        and target.is_active
        and target.entra_object_id
        and str(target.entra_tenant_id).lower() == settings.ITAM_ENTRA_TENANT_ID.lower()
        and target.roles.filter(code=SYSTEM_ADMIN).exists()
    ):
        return
    others = (
        User.objects.select_for_update()
        .filter(
            is_active=True,
            roles__code=SYSTEM_ADMIN,
            entra_tenant_id=target.entra_tenant_id,
            entra_object_id__isnull=False,
        )
        .exclude(pk=target.pk)
    )
    if not others.exists():
        raise ApiError(
            "LAST_SSO_ADMIN",
            "Link another active Entra System Admin before removing this sign-in path.",
            409,
        )


def _resolve_roles(codes: list[str]) -> list[Role]:
    roles = list(Role.objects.filter(code__in=codes))
    missing = sorted(set(codes) - {role.code for role in roles})
    if missing:
        raise serializers.ValidationError({"roles": [f"Unknown role: {code}" for code in missing]})
    return roles


# --- Authentication ---------------------------------------------------------


def login_local(request, username: str, password: str, otp_code: str = "") -> User:
    username = username.strip().lower()
    policy = SecuritySettings.load()
    candidate = User.objects.filter(username=username).first()

    if (
        candidate is not None
        and not candidate.local_login_enabled
        and not _emergency_eligible(candidate)
    ):
        authenticate(request, username=username, password=password)
        _record_login_failure(request, username, candidate, "local access restricted")
        raise ApiError("LOGIN_FAILED", LOGIN_FAILED_MESSAGE, status.HTTP_401_UNAUTHORIZED)

    if candidate is not None and candidate.is_locked:
        # Still run the hasher so locked and unlocked accounts respond alike.
        authenticate(request, username=username, password=password)
        _record_login_failure(request, username, candidate, "account locked")
        raise ApiError("LOGIN_FAILED", LOGIN_FAILED_MESSAGE, status.HTTP_401_UNAUTHORIZED)

    user = authenticate(request, username=username, password=password)
    if user is None:
        detail = "invalid credentials"
        if candidate is not None and not candidate.is_active:
            detail = "account disabled"
        elif candidate is not None:
            _register_failed_attempt(request, candidate, policy)
        _record_login_failure(request, username, candidate, detail)
        raise ApiError("LOGIN_FAILED", LOGIN_FAILED_MESSAGE, status.HTTP_401_UNAUTHORIZED)

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.is_active and not user.is_locked and user.check_password(password):
            if _emergency_eligible(user):
                expires = user.emergency_access_until.timestamp()
                user.emergency_access_until = None
                user.save(update_fields=["emergency_access_until"])
                complete_session(request, user, method="emergency", expires=expires)
                return user
            if user.local_login_enabled:
                from .local_mfa import accept_factor

                if not user.mfa_enabled or accept_factor(user, otp_code):
                    return complete_session(
                        request, user, method="local_mfa" if user.mfa_enabled else "local"
                    )
                _register_failed_attempt(request, user, policy)
    _record_login_failure(request, username, user, "local verification failed")
    raise ApiError("LOGIN_FAILED", LOGIN_FAILED_MESSAGE, status.HTTP_401_UNAUTHORIZED)


def _emergency_eligible(user):
    return bool(
        user
        and user.is_active
        and user.emergency_access_until
        and user.emergency_access_until > timezone.now()
        and user.roles.filter(code=SYSTEM_ADMIN).exists()
    )


def complete_session(request, user, *, method="local", expires=None):
    from .oidc import EXPIRES, METHOD, POLICY, policy_digest

    User.objects.filter(pk=user.pk).update(
        failed_login_count=0,
        locked_until=None,
        last_failed_login_at=None,
        emergency_access_until=None,
    )
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    now = time.time()
    request.session[SESSION_AUTH_AT] = now
    request.session[SESSION_LAST_SEEN] = now
    request.session[METHOD] = method
    if method in {"entra", "emergency"}:
        request.session[POLICY] = policy_digest()
        request.session[EXPIRES] = expires or now
    audit.record(
        action="auth.emergency_login" if method == "emergency" else "auth.login",
        actor=user,
        request=request,
        object_type="user",
        object_id=user.pk,
        object_label=user.username,
        detail=f"Sign-in method: {method}",
    )
    return user


def _register_failed_attempt(request, user: User, policy: SecuritySettings) -> None:
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(
            failed_login_count=F("failed_login_count") + 1,
            last_failed_login_at=timezone.now(),
        )
        user.refresh_from_db(fields=["failed_login_count"])
        if user.failed_login_count >= policy.lockout_threshold:
            locked_until = timezone.now() + timedelta(minutes=policy.lockout_duration_minutes)
            User.objects.filter(pk=user.pk).update(failed_login_count=0, locked_until=locked_until)
            audit.record(
                action="auth.account_locked",
                actor_label="system",
                request=request,
                object_type="user",
                object_id=user.pk,
                object_label=user.username,
                source=AuditEvent.Source.SYSTEM,
                detail=f"Locked for {policy.lockout_duration_minutes} minutes after "
                f"{policy.lockout_threshold} failed sign-ins",
            )


def _record_login_failure(request, username: str, candidate: User | None, detail: str) -> None:
    audit.record(
        action="auth.login",
        actor_label=username[:150] or "(blank)",
        request=request,
        object_type="user",
        object_id=candidate.pk if candidate is not None else "",
        object_label=candidate.username if candidate is not None else "",
        outcome=AuditEvent.Outcome.FAILURE,
        detail=detail,
    )


def logout_session(request) -> None:
    user = request.user
    audit.record(
        action="auth.logout",
        actor=user,
        request=request,
        object_type="user",
        object_id=user.pk,
        object_label=user.username,
    )
    logout(request)


def change_own_password(request, current_password: str, new_password: str) -> None:
    from .oidc import METHOD

    if request.session.get(METHOD) == "entra":
        raise ApiError(
            "SSO_PASSWORD_MANAGED", "Your sign-in password is managed by Microsoft Entra.", 409
        )
    user: User = request.user
    if not user.check_password(current_password):
        raise serializers.ValidationError({"current_password": ["Current password is incorrect."]})
    if current_password == new_password:
        raise serializers.ValidationError(
            {"new_password": ["The new password must differ from the current password."]}
        )
    _check_password_policy(new_password, user, field="new_password")
    user.set_password(new_password)
    user.must_change_password = False
    user.password_changed_at = timezone.now()
    user.save(update_fields=["password", "must_change_password", "password_changed_at"])
    update_session_auth_hash(request, user)  # keep this session; others are invalidated
    audit.record(
        action="auth.password_changed",
        actor=user,
        request=request,
        object_type="user",
        object_id=user.pk,
        object_label=user.username,
    )


# --- User administration ----------------------------------------------------


def create_user(request, *, username, display_name, email, roles, password) -> User:
    actor = request.user if request is not None else None
    username = username.strip().lower()
    role_objs = _resolve_roles(roles)
    probe = User(username=username, email=email, display_name=display_name)
    _check_password_policy(password, probe)
    if User.objects.filter(username=username).exists():
        raise serializers.ValidationError({"username": ["This username is already in use."]})
    if email and User.objects.filter(email__iexact=email).exists():
        raise serializers.ValidationError({"email": ["This email is already in use."]})

    with transaction.atomic():
        user = User.objects.create_user(
            username,
            password,
            email=email,
            display_name=display_name,
            must_change_password=True,
            created_by=actor,
        )
        user.roles.set(role_objs)
        audit.record(
            action="users.create",
            actor=actor,
            request=request,
            object_type="user",
            object_id=user.pk,
            object_label=user.username,
            after=snapshot(user),
        )
    return user


def update_user(request, user: User, changes: dict) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        before = snapshot(user)

        if "email" in changes:
            email = changes["email"].strip().lower()
            if email and User.objects.exclude(pk=user.pk).filter(email__iexact=email).exists():
                raise serializers.ValidationError({"email": ["This email is already in use."]})
            user.email = email
        if "display_name" in changes:
            user.display_name = changes["display_name"]
        if (
            "local_login_enabled" in changes
            and changes["local_login_enabled"] != user.local_login_enabled
        ):
            enabled = changes["local_login_enabled"]
            if not enabled:
                from .oidc import ready

                if (
                    not user.entra_object_id
                    or str(user.entra_tenant_id).lower() != settings.ITAM_ENTRA_TENANT_ID.lower()
                    or not ready()
                ):
                    raise serializers.ValidationError(
                        {
                            "local_login_enabled": [
                                "Configure and link Entra before disabling local sign-in."
                            ]
                        }
                    )
                if (
                    user.pk == request.user.pk
                    and request.session.get("itam_auth_method") != "entra"
                ):
                    raise ApiError(
                        "SELF_LOGIN_CHANGE", "Another admin must change your sign-in access.", 409
                    )
            if enabled != user.local_login_enabled:
                user.local_login_enabled = enabled
                user.session_epoch = F("session_epoch") + 1
                user.emergency_access_until = None
        if "roles" in changes:
            role_objs = _resolve_roles(changes["roles"])
            if SYSTEM_ADMIN not in {role.code for role in role_objs}:
                if user.pk == request.user.pk and user.roles.filter(code=SYSTEM_ADMIN).exists():
                    raise ApiError(
                        "SELF_DEMOTION",
                        "You cannot remove the System Admin role from your own account.",
                        status.HTTP_409_CONFLICT,
                    )
                _guard_last_admin(user)
            user.roles.set(role_objs)
        if "all_sites" in changes:
            user.all_sites = changes["all_sites"]
        if "site_ids" in changes:
            from apps.organizations.models import Site
            from apps.organizations.services import set_user_sites

            sites = list(Site.objects.filter(pk__in=changes["site_ids"]))
            missing = {str(s) for s in changes["site_ids"]} - {str(s.pk) for s in sites}
            if missing:
                raise serializers.ValidationError({"site_ids": ["Unknown site."]})
            set_user_sites(user, sites, request.user)

        after = snapshot(user)
        if after == before:
            return user
        user.version = F("version") + 1
        user.save()
        user.refresh_from_db()
        audit.record(
            action="users.update",
            actor=request.user,
            request=request,
            object_type="user",
            object_id=user.pk,
            object_label=user.username,
            before=before,
            after=after,
        )
    return user


def disable_user(request, user: User, reason: str) -> User:
    if user.pk == request.user.pk:
        raise ApiError(
            "SELF_DISABLE", "You cannot disable your own account.", status.HTTP_409_CONFLICT
        )
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if not user.is_active:
            return user
        _guard_last_admin(user)
        before = snapshot(user)
        user.is_active = False
        user.disabled_at = timezone.now()
        user.disabled_by = request.user
        user.disabled_reason = reason
        user.emergency_access_until = None
        user.session_epoch = F("session_epoch") + 1  # revokes all sessions
        user.version = F("version") + 1
        user.save()
        user.refresh_from_db()
        audit.record(
            action="users.disable",
            actor=request.user,
            request=request,
            object_type="user",
            object_id=user.pk,
            object_label=user.username,
            before=before,
            after=snapshot(user),
            detail=reason,
        )
    return user


def enable_user(request, user: User) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.is_active:
            return user
        before = snapshot(user)
        user.is_active = True
        user.disabled_at = None
        user.disabled_by = None
        user.disabled_reason = ""
        user.emergency_access_until = None
        user.failed_login_count = 0
        user.locked_until = None
        user.version = F("version") + 1
        user.save()
        user.refresh_from_db()
        audit.record(
            action="users.enable",
            actor=request.user,
            request=request,
            object_type="user",
            object_id=user.pk,
            object_label=user.username,
            before=before,
            after=snapshot(user),
        )
    return user


def unlock_user(request, user: User) -> User:
    User.objects.filter(pk=user.pk).update(
        failed_login_count=0, locked_until=None, version=F("version") + 1
    )
    user.refresh_from_db()
    audit.record(
        action="users.unlock",
        actor=request.user,
        request=request,
        object_type="user",
        object_id=user.pk,
        object_label=user.username,
    )
    return user


def reset_password(request, user: User, new_password: str) -> User:
    _check_password_policy(new_password, user)
    user.set_password(new_password)
    user.must_change_password = True
    user.password_changed_at = timezone.now()
    user.failed_login_count = 0
    user.locked_until = None
    user.emergency_access_until = None
    user.mfa_pending_secret = b""
    user.mfa_pending_until = None
    user.session_epoch = F("session_epoch") + 1
    user.version = F("version") + 1
    user.save(
        update_fields=[
            "password",
            "must_change_password",
            "password_changed_at",
            "failed_login_count",
            "locked_until",
            "emergency_access_until",
            "mfa_pending_secret",
            "mfa_pending_until",
            "session_epoch",
            "version",
            "modified_at",
        ]
    )
    user.refresh_from_db()
    audit.record(
        action="users.password_reset",
        actor=request.user,
        request=request,
        object_type="user",
        object_id=user.pk,
        object_label=user.username,
        detail="Temporary password set; change required at next sign-in",
    )
    return user


# --- Security settings ------------------------------------------------------

SECURITY_FIELDS = (
    "session_idle_timeout_minutes",
    "session_absolute_timeout_hours",
    "lockout_threshold",
    "lockout_duration_minutes",
    "password_min_length",
)


def update_security_settings(request, changes: dict) -> SecuritySettings:
    with transaction.atomic():
        policy = SecuritySettings.objects.select_for_update().get(pk=1)
        before = {field: getattr(policy, field) for field in SECURITY_FIELDS}
        for field, value in changes.items():
            setattr(policy, field, value)
        if policy.session_idle_timeout_minutes > policy.session_absolute_timeout_hours * 60:
            raise serializers.ValidationError(
                {"session_idle_timeout_minutes": ["Idle timeout cannot exceed absolute timeout."]}
            )
        after = {field: getattr(policy, field) for field in SECURITY_FIELDS}
        if after == before:
            return policy
        policy.modified_by = request.user
        policy.version = F("version") + 1
        policy.save()
        policy.refresh_from_db()
        audit.record(
            action="settings.security.update",
            actor=request.user,
            request=request,
            object_type="settings",
            object_id="security",
            object_label="Security settings",
            before=before,
            after=after,
        )
    return policy
