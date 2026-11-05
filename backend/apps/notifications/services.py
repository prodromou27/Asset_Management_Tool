"""SMTP profile, templates, outbox and delivery (Task 018a, ASM-57)."""

import ipaddress
import logging
import random
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Min
from django.utils import timezone

from apps.audit import services as audit
from apps.domains import certs, checker
from apps.integrations import secrets
from apps.organizations.services import check_version
from config.api import ApiError

from . import mailer, render
from .models import NotificationTemplate, OutboxMessage, SmtpProfile

logger = logging.getLogger(__name__)
Status = OutboxMessage.Status

PROFILE_FIELDS = (
    "enabled",
    "host",
    "port",
    "security",
    "username",
    "password_ref",
    "ca_bundle_ref",
    "from_address",
    "from_name",
    "reply_to",
    "timeout_seconds",
    "max_per_minute",
)
BASE_DELAY = 60  # seconds before the first retry; doubles per attempt
MAX_DELAY = 3600


def _invalid(field: str, message: str):
    return ApiError("VALIDATION_ERROR", message, 422, {field: [message]})


def _record(request, action, object_type, object_id, label, before=None, after=None, detail=""):
    audit.record(
        action=f"notifications.{action}",
        actor=getattr(request, "user", None),
        request=request,
        object_type=object_type,
        object_id=object_id,
        object_label=label,
        before=before,
        after=after,
        detail=detail,
    )


# --- Profile ----------------------------------------------------------------------------------


def _defaults() -> dict:
    values = dict(getattr(settings, "ITAM_SMTP_DEFAULTS", {}))
    if values.get("security") not in SmtpProfile.Security.values:
        values.pop("security", None)
    if "@" not in (values.get("from_address") or "") or "." not in values["from_address"]:
        values.pop("from_address", None)  # e.g. itam@localhost: not a valid sender
    return {k: v for k, v in values.items() if v not in (None, "")}


def get_profile() -> SmtpProfile:
    profile, _ = SmtpProfile.objects.get_or_create(pk=1, defaults=_defaults())
    return profile


def _snapshot(profile) -> dict:
    # Only the reference is audited, never a credential value (there is none stored).
    return {f: getattr(profile, f) for f in PROFILE_FIELDS}


def _clean_profile(merged: dict) -> None:
    host = (merged.get("host") or "").strip()
    if host:
        try:
            merged["host"] = certs.normalize_host(host)
        except certs.InvalidName as exc:
            raise _invalid("host", str(exc)) from exc
        try:
            reason = checker.refused(str(ipaddress.ip_address(merged["host"])))
        except ValueError:
            reason = None
        if reason:
            raise _invalid("host", f"ITAM does not connect to this address ({reason}).")
    if merged["username"] and merged["security"] == SmtpProfile.Security.NONE:
        raise _invalid(
            "security", "Credentials are only sent over STARTTLS or implicit TLS; choose one."
        )
    for field, prefix in (("password_ref", secrets.SMTP), ("ca_bundle_ref", secrets.SMTP)):
        try:
            merged[field] = secrets.validate_ref(merged.get(field) or "", prefix)
        except secrets.SecretError as exc:
            raise _invalid(field, str(exc)) from exc
    if merged["ca_bundle_ref"] and not merged["ca_bundle_ref"].startswith("file:"):
        raise _invalid("ca_bundle_ref", "A CA bundle must be a file: reference.")
    if merged["username"] and not merged["password_ref"]:
        raise _invalid("password_ref", "Enter the password reference for this user.")
    if merged["enabled"] and (not merged["host"] or not merged["from_address"]):
        raise _invalid("enabled", "Enter the host and sender address before enabling mail.")


@transaction.atomic
def update_profile(request, data: dict, expected) -> SmtpProfile:
    profile = SmtpProfile.objects.select_for_update().get(pk=get_profile().pk)
    check_version(profile, expected)
    before = _snapshot(profile)
    merged = {**before, **data}
    _clean_profile(merged)
    connection_changed = any(
        merged[f] != before[f]
        for f in ("host", "port", "security", "username", "password_ref", "ca_bundle_ref")
    )
    for name in PROFILE_FIELDS:
        setattr(profile, name, merged[name])
    if connection_changed:  # an earlier test no longer describes this configuration
        profile.last_test_at, profile.last_test_ok, profile.last_test_error = None, None, ""
    profile.modified_by = request.user
    profile.version = F("version") + 1
    profile.save()
    profile.refresh_from_db()
    action = "smtp.update"
    if before["enabled"] != profile.enabled:
        action = "smtp.enable" if profile.enabled else "smtp.disable"
    _record(request, action, "smtp_profile", 1, str(profile), before, _snapshot(profile))
    if profile.enabled and not before["enabled"]:
        transaction.on_commit(_kick)
    return profile


def password_status(profile: SmtpProfile) -> str:
    return secrets.status(profile.password_ref, secrets.SMTP)


def test_connection(request) -> SmtpProfile:
    """Connect, negotiate TLS and log in; nothing is sent (docs/10 "Test connection")."""
    profile = get_profile()
    ok, error = True, ""
    try:
        with mailer.connect(profile) as client:
            client.noop()
    except (mailer.ConfigError, mailer.TemporaryFailure) as exc:
        ok, error = False, str(exc)[:500]
    SmtpProfile.objects.filter(pk=1).update(
        last_test_at=timezone.now(), last_test_ok=ok, last_test_error=error
    )
    _record(
        request,
        "smtp.test",
        "smtp_profile",
        1,
        str(profile),
        after={"ok": ok, "error": error},
    )
    return get_profile()


# --- Templates --------------------------------------------------------------------------------


@transaction.atomic
def update_template(request, template: NotificationTemplate, data: dict, expected):
    template = NotificationTemplate.objects.select_for_update().get(pk=template.pk)
    check_version(template, expected)
    merged = {f: data.get(f, getattr(template, f)) for f in ("subject", "body_text", "body_html")}
    if not merged["subject"].strip() or not merged["body_text"].strip():
        raise _invalid("body_text", "A subject and a plain-text body are required.")
    try:
        for field, source in merged.items():
            render.check(field, source)
    except render.TemplateError as exc:
        raise _invalid(exc.field, str(exc)) from exc
    before = {f: getattr(template, f) for f in merged}
    for name, value in merged.items():
        setattr(template, name, value)
    template.modified_by = request.user
    template.version = F("version") + 1
    template.save()
    template.refresh_from_db()
    _record(
        request,
        "template.update",
        "notification_template",
        template.pk,
        template.code,
        before={"version": template.version - 1},
        after={
            "version": template.version,
            "changed": [f for f in merged if merged[f] != before[f]],
        },
    )
    return template


SAMPLE_ITEMS = [
    {
        "title": "intranet.example.org",
        "detail": "intranet.example.org:443",
        "date": "2026-12-01",
        "status": "27 days left",
        "url": "https://itam.example.org/certificates/1",
    },
    {
        "title": "sw-core-01 (HQ)",
        "detail": "Hardware: Example Switch 9000 · End of support",
        "date": "2027-03-31",
        "status": "147 days left",
        "url": "https://itam.example.org/assets/1",
    },
]


def sample_context(template: NotificationTemplate) -> dict:
    values = {v["name"]: v.get("example", f"<{v['name']}>") for v in template.variables}
    if "items" in values:
        values.update(items=SAMPLE_ITEMS, count=len(SAMPLE_ITEMS), more=0)
    return values


def preview(template: NotificationTemplate, draft: dict) -> render.Rendered:
    try:
        return render.render(
            draft.get("subject", template.subject),
            draft.get("body_text", template.body_text),
            draft.get("body_html", template.body_html),
            sample_context(template),
        )
    except render.TemplateError as exc:
        raise _invalid(exc.field, str(exc)) from exc


# --- Outbox -----------------------------------------------------------------------------------


def enqueue(
    template_code: str,
    to: str,
    context: dict,
    *,
    event_type: str,
    dedup_key: str | None = None,
    created_by=None,
) -> tuple[OutboxMessage, bool]:
    """Render and queue one message. Returns (message, created); an existing dedup_key
    returns the earlier message and queues nothing. Safe inside a business transaction:
    delivery happens after commit, in the worker."""
    if dedup_key:
        existing = OutboxMessage.objects.filter(dedup_key=dedup_key).first()
        if existing is not None:
            return existing, False
    template = NotificationTemplate.objects.get(code=template_code)
    rendered = render.render(template.subject, template.body_text, template.body_html, context)
    now = timezone.now()
    message = OutboxMessage(
        event_type=event_type,
        template_code=template.code,
        template_version=template.version,
        dedup_key=dedup_key or None,
        to_address=to,
        subject=rendered.subject,
        body_text=rendered.body_text,
        body_html=rendered.body_html,
        next_attempt_at=now,
        queued_at=now,
        expires_at=now + timedelta(hours=settings.ITAM_NOTIFICATION_EXPIRY_HOURS),
        created_by=created_by,
    )
    try:
        with transaction.atomic():
            message.save()
    except IntegrityError:
        return OutboxMessage.objects.get(dedup_key=dedup_key), False
    transaction.on_commit(_kick)
    return message, True


def _kick() -> None:
    from .tasks import deliver_due

    try:
        deliver_due.delay()
    except Exception:  # broker down: the periodic run picks the message up
        logger.warning("Mail delivery could not be queued now; the next periodic run sends it.")


def backoff(attempt: int) -> timedelta:
    delay = min(MAX_DELAY, BASE_DELAY * 2 ** max(0, attempt - 1))
    return timedelta(seconds=delay * random.uniform(0.8, 1.2))


def _claim(message_id) -> bool:
    """Take a message for sending; only one worker wins."""
    return (
        OutboxMessage.objects.filter(
            pk=message_id, status__in=[Status.QUEUED, Status.RETRYING]
        ).update(status=Status.SENDING)
        == 1
    )


def _finish(message: OutboxMessage, **fields) -> None:
    for name, value in fields.items():
        setattr(message, name, value)
    message.save(update_fields=list(fields))


def deliver_due(now=None) -> dict:
    """Send due messages while SMTP is enabled, at most ``max_per_minute`` per run."""
    now = now or timezone.now()
    counts = {"sent": 0, "retrying": 0, "dead": 0, "expired": 0}
    counts["expired"] = OutboxMessage.objects.filter(
        status__in=[Status.QUEUED, Status.RETRYING], expires_at__lte=now
    ).update(status=Status.EXPIRED, finished_at=now, last_error="Expired before it could be sent.")
    # Messages left in "sending" by a crashed worker go back to the queue.
    OutboxMessage.objects.filter(
        status=Status.SENDING, next_attempt_at__lte=now - timedelta(minutes=15)
    ).update(status=Status.RETRYING)
    profile = get_profile()
    if not profile.enabled:
        return counts
    due = list(
        OutboxMessage.objects.filter(
            status__in=[Status.QUEUED, Status.RETRYING], next_attempt_at__lte=now
        )
        .order_by("next_attempt_at")
        .values_list("pk", flat=True)[: profile.max_per_minute]
    )
    if not due:
        return counts
    try:
        with mailer.connect(profile) as client:
            for pk in due:
                if not _claim(pk):
                    continue
                message = OutboxMessage.objects.get(pk=pk)
                result = _send_one(client, profile, message, now)
                counts[result] = counts.get(result, 0) + 1
    except mailer.ConfigError as exc:
        # Fix the settings first: messages wait without using up their attempts.
        OutboxMessage.objects.filter(
            pk__in=due, status__in=[Status.QUEUED, Status.RETRYING, Status.SENDING]
        ).update(
            status=Status.RETRYING,
            last_error=f"Mail settings: {exc}"[:500],
            next_attempt_at=now + timedelta(minutes=5),
        )
        counts["retrying"] += len(due)
    except mailer.TemporaryFailure as exc:
        # The server is unreachable or refuses the session: each waiting message counts an
        # attempt and backs off; after max_attempts it becomes a visible dead letter.
        for message in OutboxMessage.objects.filter(
            pk__in=due, status__in=[Status.QUEUED, Status.RETRYING, Status.SENDING]
        ):
            counts[_failed(message, str(exc), now, permanent=False)] += 1
    if any(counts.values()):
        logger.info("Mail delivery: %s", counts)
    return counts


def _send_one(client, profile, message: OutboxMessage, now) -> str:
    if message.event_type == "report_digest":
        from apps.reports.digests import can_deliver

        if not can_deliver(message):
            _finish(
                message,
                status=Status.CANCELLED,
                finished_at=now,
                last_error="Report recipient or access changed; digest cancelled.",
            )
            return "cancelled"
    built = mailer.build(
        profile, message.to_address, message.subject, message.body_text, message.body_html
    )
    try:
        mailer.send(client, built)
    except mailer.PermanentFailure as exc:
        return _failed(message, str(exc), now, permanent=True)
    except mailer.TemporaryFailure as exc:
        return _failed(message, str(exc), now, permanent=False)
    _finish(
        message,
        status=Status.SENT,
        attempts=message.attempts + 1,
        sent_at=timezone.now(),
        finished_at=timezone.now(),
        message_id=built["Message-ID"][:200],
        last_error="",
    )
    return "sent"


def _failed(message: OutboxMessage, error: str, now, permanent: bool) -> str:
    attempts = message.attempts + 1
    if permanent or attempts >= message.max_attempts:
        _finish(
            message,
            status=Status.DEAD,
            attempts=attempts,
            last_error=error[:500],
            finished_at=now,
        )
        return "dead"
    _finish(
        message,
        status=Status.RETRYING,
        attempts=attempts,
        last_error=error[:500],
        next_attempt_at=now + backoff(attempts),
    )
    return "retrying"


def send_test_email(request) -> OutboxMessage:
    """docs/10: only to the signed-in administrator's own address; delivered now."""
    profile = get_profile()
    to = (request.user.email or "").strip()
    if not to:
        raise ApiError(
            "NO_EMAIL",
            "Your account has no e-mail address; the test message is only sent to you.",
            409,
        )
    if not profile.enabled:
        raise ApiError("SMTP_DISABLED", "Enable mail before sending a test message.", 409)
    message, _ = enqueue(
        "smtp_test",
        to,
        {"requested_by": request.user.display_name or request.user.username},
        event_type="smtp.test",
        created_by=request.user,
    )
    now = timezone.now()
    if _claim(message.pk):
        message.refresh_from_db()
        try:
            with mailer.connect(profile) as client:
                _send_one(client, profile, message, now)
        except (mailer.ConfigError, mailer.TemporaryFailure) as exc:
            _failed(message, str(exc), now, permanent=False)
    message.refresh_from_db()
    if message.status == Status.SENT:
        SmtpProfile.objects.filter(pk=1).update(last_test_email_at=message.sent_at)
    _record(
        request,
        "smtp.test_email",
        "outbox_message",
        message.pk,
        "Test message",
        after={"status": message.status, "recipients": 1, "error": message.last_error},
    )
    return message


@transaction.atomic
def retry(request, message: OutboxMessage) -> OutboxMessage:
    message = OutboxMessage.objects.select_for_update().get(pk=message.pk)
    if message.status not in (Status.DEAD, Status.EXPIRED, Status.CANCELLED):
        raise ApiError(
            "NOT_RETRYABLE", "Only failed, expired or cancelled messages can be retried.", 409
        )
    if message.bodies_purged:
        raise ApiError("PURGED", "The message content was removed by the retention policy.", 409)
    now = timezone.now()
    _finish(
        message,
        status=Status.QUEUED,
        attempts=0,
        next_attempt_at=now,
        finished_at=None,
        expires_at=now + timedelta(hours=settings.ITAM_NOTIFICATION_EXPIRY_HOURS),
    )
    _record(request, "outbox.retry", "outbox_message", message.pk, message.subject)
    transaction.on_commit(_kick)
    return message


@transaction.atomic
def cancel(request, message: OutboxMessage) -> OutboxMessage:
    message = OutboxMessage.objects.select_for_update().get(pk=message.pk)
    if message.status not in (Status.QUEUED, Status.RETRYING):
        raise ApiError("NOT_CANCELLABLE", "Only queued messages can be cancelled.", 409)
    _finish(message, status=Status.CANCELLED, finished_at=timezone.now())
    _record(request, "outbox.cancel", "outbox_message", message.pk, message.subject)
    return message


def purge(now=None) -> int:
    """Clear message bodies of finished messages after the retention period (docs/14: no
    long-lived mail bodies); the delivery record itself stays."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=settings.ITAM_NOTIFICATION_BODY_RETENTION_DAYS)
    return OutboxMessage.objects.filter(finished_at__lte=cutoff, bodies_purged=False).update(
        body_text="", body_html="", bodies_purged=True
    )


def stats(*, profile: SmtpProfile | None = None) -> dict:
    """Queue health for the admin page and System health (docs/14 "notification queue
    backlog" alert)."""
    rows = dict(
        OutboxMessage.objects.values_list("status")
        .annotate(n=Count("pk"))
        .values_list("status", "n")
    )
    oldest = OutboxMessage.objects.filter(status__in=[Status.QUEUED, Status.RETRYING]).aggregate(
        oldest=Min("queued_at")
    )["oldest"]
    since = timezone.now() - timedelta(hours=24)
    dead_recent = OutboxMessage.objects.filter(status=Status.DEAD, finished_at__gte=since).count()
    profile = profile if profile is not None else get_profile()
    waiting = rows.get(Status.QUEUED, 0) + rows.get(Status.RETRYING, 0)
    problems = []
    if dead_recent:
        problems.append(f"{dead_recent} message(s) failed permanently in the last 24 hours.")
    if waiting and oldest and timezone.now() - oldest > timedelta(hours=1):
        problems.append(
            "Messages have been waiting for more than an hour"
            + (" because mail is disabled." if not profile.enabled else ".")
        )
    if rows.get(Status.RETRYING, 0):
        problems.append(f"{rows[Status.RETRYING]} message(s) waiting to retry.")
    return {
        "counts": {s: rows.get(s, 0) for s in Status.values},
        "oldest_waiting_at": oldest,
        "dead_last_24h": dead_recent,
        "problems": problems,
        "enabled": profile.enabled,
        "configured": bool(profile.host and profile.from_address),
    }


# --- Rules (Task 018b) ------------------------------------------------------------------------

RULE_FIELDS = ("name", "event", "enabled", "thresholds", "include_expired", "failure_count")


def _rule_snapshot(rule) -> dict:
    data = {f: getattr(rule, f) for f in RULE_FIELDS}
    data["recipients"] = sorted(str(u) for u in rule.recipients.values_list("username", flat=True))
    data["sites"] = sorted(str(s) for s in rule.sites.values_list("code", flat=True))
    return data


def _clean_thresholds(values) -> list[int]:
    cleaned = sorted({int(v) for v in values or []}, reverse=True)
    if len(cleaned) > 10 or any(v < 1 or v > 3650 for v in cleaned):
        raise _invalid("thresholds", "Use up to 10 whole numbers of days between 1 and 3650.")
    return cleaned


def _apply_rule(rule, data: dict) -> None:
    from .models import NotificationRule

    for name in RULE_FIELDS:
        if name in data:
            setattr(rule, name, data[name])
    if rule.event != NotificationRule.Event.INTEGRATION_FAILURE:
        rule.thresholds = _clean_thresholds(rule.thresholds)
        if not rule.thresholds and not rule.include_expired:
            raise _invalid("thresholds", "Choose at least one threshold or include expired items.")
    else:
        rule.thresholds = []
        if not 1 <= rule.failure_count <= 50:
            raise _invalid("failure_count", "Use 1 to 50 failed runs.")


@transaction.atomic
def create_rule(request, data: dict):
    from .models import NotificationRule

    data = dict(data)
    recipients, sites = data.pop("recipients", []), data.pop("sites", [])
    if "thresholds" not in data:
        data["thresholds"] = list(NotificationRule.DEFAULT_THRESHOLDS[data["event"]])
    rule = NotificationRule(created_by=request.user, modified_by=request.user)
    _apply_rule(rule, data)
    rule.save()
    rule.recipients.set(recipients)
    rule.sites.set(sites)
    _record(
        request, "rule.create", "notification_rule", rule.pk, rule.name, after=_rule_snapshot(rule)
    )
    return rule


@transaction.atomic
def update_rule(request, rule, data: dict, expected):
    from .models import NotificationRule

    rule = NotificationRule.objects.select_for_update().get(pk=rule.pk)
    check_version(rule, expected)
    before = _rule_snapshot(rule)
    data = dict(data)
    data.pop("event", None)  # the event of a rule is fixed
    recipients, sites = data.pop("recipients", None), data.pop("sites", None)
    policy_before = (rule.thresholds, rule.include_expired, rule.failure_count)
    sites_before = set(rule.sites.values_list("pk", flat=True))
    _apply_rule(rule, data)
    if policy_before != (rule.thresholds, rule.include_expired, rule.failure_count) or (
        sites is not None and {s.pk for s in sites} != sites_before
    ):
        rule.policy_version = F("policy_version") + 1
    rule.modified_by = request.user
    rule.version = F("version") + 1
    rule.save()
    rule.refresh_from_db()
    if recipients is not None:
        rule.recipients.set(recipients)
    if sites is not None:
        rule.sites.set(sites)
    _record(
        request,
        "rule.update",
        "notification_rule",
        rule.pk,
        rule.name,
        before=before,
        after=_rule_snapshot(rule),
    )
    return rule


@transaction.atomic
def delete_rule(request, rule) -> None:
    snapshot = _rule_snapshot(rule)
    pk, name = rule.pk, rule.name
    rule.delete()
    _record(request, "rule.delete", "notification_rule", pk, name, before=snapshot)
