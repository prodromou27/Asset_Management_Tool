"""Self-owned link-only digests. SMTP remains owned by the existing outbox service."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.notifications import render
from apps.notifications import services as mail
from apps.notifications.models import SmtpProfile

from .models import DigestDispatch, DigestSchedule
from .services import CATALOGUE, can_view


def eligible(schedule):
    owner = schedule.owner
    return (
        schedule.enabled
        and owner.is_active
        and not owner.must_change_password
        and owner.email
        and "reports.schedule" in owner.permission_codes()
        and can_view(owner, schedule.report, schedule.filters)
    )


def dispatch(now=None):
    now = now or timezone.now()
    profile = SmtpProfile.objects.first()
    if not profile or not profile.enabled:
        return 0
    queued = 0
    for pk in DigestSchedule.objects.filter(enabled=True).values_list("pk", flat=True):
        with transaction.atomic():
            schedule = DigestSchedule.objects.select_for_update().select_related("owner").get(pk=pk)
            if not eligible(schedule):
                continue
            slot = now.replace(hour=schedule.hour_utc, minute=0, second=0, microsecond=0)
            if schedule.cadence == "weekly":
                slot -= timedelta(days=(slot.weekday() - schedule.weekday) % 7)
            if slot > now:
                slot -= timedelta(days=7 if schedule.cadence == "weekly" else 1)
            if (
                slot < schedule.created_at
                or DigestDispatch.objects.filter(schedule=schedule, slot=slot).exists()
            ):
                continue
            url = render.app_url() + f"/reports?schedule={schedule.pk}"
            message, created = mail.enqueue(
                "report_digest",
                schedule.owner.email,
                {"report_label": CATALOGUE[schedule.report][0], "report_url": url},
                event_type="report_digest",
                dedup_key=f"report:{schedule.pk}:{slot.isoformat()}",
                created_by=schedule.owner,
            )
            DigestDispatch.objects.create(
                schedule=schedule, slot=slot, policy_version=schedule.version, message=message
            )
            audit.record(
                action="reports.digest_queued",
                actor=schedule.owner,
                source="system",
                object_type="report_schedule",
                object_id=schedule.pk,
                after={"slot": slot.isoformat(), "message": str(message.pk)},
            )
            queued += int(created)
    return queued


def can_deliver(message):
    dispatch = (
        DigestDispatch.objects.select_related("schedule__owner").filter(message=message).first()
    )
    return bool(
        dispatch
        and dispatch.policy_version == dispatch.schedule.version
        and eligible(dispatch.schedule)
        and message.to_address == dispatch.schedule.owner.email
    )
