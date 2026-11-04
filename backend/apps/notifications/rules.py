"""Notification rules: find what is due, tell each recipient once (Task 018b, ASM-58).

docs/10: thresholds per event, dedup key = event + target + milestone date + threshold +
policy version, re-announce only on a meaningful change (a new date or a new failure streak),
no unverified claims of end of support, never one message per observation.

Each run collects findings per rule and recipient, drops those already in the ledger, and
queues **one** message listing the new ones (at most ``MAX_ITEMS``; the rest follow on the
next run). Nothing is evaluated while mail is disabled, so findings are not lost.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from django.db import transaction
from django.utils import timezone

from apps.accounts import catalog

from . import render, services
from .models import AlertLedger, NotificationRule

logger = logging.getLogger(__name__)
Event = NotificationRule.Event
MAX_ITEMS = 200

# What a recipient must be allowed to see to receive the rule's findings.
REQUIRED_PERMISSIONS = {
    Event.CERTIFICATE_EXPIRY: (catalog.CERTIFICATES_VIEW,),
    Event.DOMAIN_EXPIRY: (catalog.CERTIFICATES_VIEW,),
    Event.LIFECYCLE_EOL: (catalog.ASSETS_VIEW, catalog.LIFECYCLE_VIEW),
    Event.INTEGRATION_FAILURE: (catalog.INTEGRATIONS_MANAGE,),
}
# Assessment states that come from verified evidence and are worth an alert (ASM-53:
# "unverified" and "unknown" never claim end of support).
EOL_STATES = ("eol_announced", "expiring", "security_maintenance_ended", "eos")


@dataclass
class Finding:
    key: str
    title: str
    detail: str
    when: str  # date label
    status: str  # e.g. "14 days left", "Expired", "3 failed runs"
    path: str  # link inside ITAM
    sort: tuple = field(default=())


def today_utc() -> date:
    return datetime.now(UTC).date()


def reached(rule: NotificationRule, days: int | None) -> str | None:
    """The threshold tier reached for ``days`` left, "expired", or None."""
    if days is None:
        return None
    if days < 0:
        return "expired" if rule.include_expired else None
    tiers = [t for t in sorted(set(rule.thresholds or [])) if days <= t]
    return str(tiers[0]) if tiers else None


def _days_label(days: int) -> str:
    if days < 0:
        return f"Expired {-days} day{'s' if days != -1 else ''} ago"
    if days == 0:
        return "Ends today"
    return f"{days} day{'s' if days != 1 else ''} left"


# --- Collectors -------------------------------------------------------------------------------


def _certificates(rule, user, today) -> list[Finding]:
    from django.db.models import Q

    from apps.domains.models import Certificate

    rows = (
        Certificate.objects.filter(
            Q(
                deployments__replaced_at__isnull=True,
                deployments__endpoint__retired_at__isnull=True,
                deployments__endpoint__enabled=True,
            )
            | Q(source=Certificate.Source.UPLOADED)
        )
        .distinct()
        .prefetch_related("deployments__endpoint")
    )
    found = []
    for cert in rows:
        end = cert.not_after.astimezone(UTC).date()
        days = (end - today).days
        tier = reached(rule, days)
        if tier is None:
            continue
        endpoints = sorted(
            str(d.endpoint)
            for d in cert.deployments.all()
            if d.replaced_at is None and d.endpoint.retired_at is None
        )
        found.append(
            Finding(
                key=f"cert:{cert.pk}:{end.isoformat()}:{tier}:v{rule.policy_version}",
                title=cert.common_name
                or (cert.sans[0] if cert.sans else cert.fingerprint_sha256[:16]),
                detail=", ".join(endpoints[:5]) or "Uploaded certificate",
                when=end.isoformat(),
                status=_days_label(days),
                path=f"/certificates/{cert.pk}",
                sort=(days, cert.common_name),
            )
        )
    return found


def _domains(rule, user, today) -> list[Finding]:
    from apps.domains.models import DomainRegistration

    found = []
    # Unknown expiry is never alerted as a date (docs/10: it is a data-quality question).
    for domain in DomainRegistration.objects.filter(
        retired_at__isnull=True, expires_on__isnull=False
    ):
        days = (domain.expires_on - today).days
        tier = reached(rule, days)
        if tier is None:
            continue
        found.append(
            Finding(
                key=f"domain:{domain.pk}:{domain.expires_on.isoformat()}:{tier}:v{rule.policy_version}",
                title=domain.fqdn,
                detail=" · ".join(
                    x
                    for x in (domain.registrar, f"owner {domain.owner}" if domain.owner else "")
                    if x
                )
                or "Registrar not recorded",
                when=domain.expires_on.isoformat(),
                status=_days_label(days),
                path="/domains?tab=domains",
                sort=(days, domain.fqdn),
            )
        )
    return found


def _lifecycle(rule, user, today) -> list[Finding]:
    from apps.assets.selectors import visible_assets
    from apps.lifecycle.models import LifecycleAssessment

    assets = visible_assets(user).filter(archived_at__isnull=True)
    site_ids = list(rule.sites.values_list("pk", flat=True))
    if site_ids:
        assets = assets.filter(site_id__in=site_ids)
    rows = (
        LifecycleAssessment.objects.filter(
            asset__in=assets.values("pk"),
            effective_status__in=EOL_STATES,
            milestone_date__isnull=False,
        )
        .exclude(evidence_quality="")
        .select_related("asset__site", "product")
    )
    found = []
    for a in rows:
        days = (a.milestone_date - today).days
        tier = reached(rule, days)
        if tier is None:
            continue
        milestone = a.get_milestone_type_display() if a.milestone_type else "Milestone"
        product = a.product or "catalogue product"
        found.append(
            Finding(
                key=(
                    f"eol:{a.asset_id}:{a.dimension}:{a.milestone_type}:"
                    f"{a.milestone_date.isoformat()}:{tier}:v{rule.policy_version}"
                ),
                title=f"{a.asset.name} ({a.asset.site.code})",
                detail=f"{a.get_dimension_display()}: {product} · {milestone}",
                when=a.milestone_date.isoformat(),
                status=_days_label(days),
                path=f"/assets/{a.asset_id}?tab=lifecycle",
                sort=(days, a.asset.name),
            )
        )
    return found


def _integrations(rule, user, today) -> list[Finding]:
    from apps.integrations.models import IntegrationInstance, SyncRun

    found = []
    now = timezone.now()
    for instance in IntegrationInstance.objects.filter(is_enabled=True):
        runs = list(
            SyncRun.objects.filter(instance=instance, finished_at__isnull=False)
            .order_by("-started_at")
            .values("id", "status", "started_at")[: max(1, rule.failure_count)]
        )
        if len(runs) >= rule.failure_count and all(
            r["status"] == SyncRun.Status.FAILED for r in runs
        ):
            # The streak starts at the oldest failed run of the uninterrupted series.
            last_ok = (
                SyncRun.objects.filter(instance=instance, finished_at__isnull=False)
                .exclude(status=SyncRun.Status.FAILED)
                .order_by("-started_at")
                .values_list("started_at", flat=True)
                .first()
            )
            streak = SyncRun.objects.filter(instance=instance, status=SyncRun.Status.FAILED)
            if last_ok:
                streak = streak.filter(started_at__gt=last_ok)
            first = streak.order_by("started_at").values("id", "started_at").first()
            found.append(
                Finding(
                    key=f"int:{instance.pk}:failing:{first['id']}:v{rule.policy_version}",
                    title=instance.name,
                    detail=(instance.last_error or "The last runs failed.")[:200],
                    when=first["started_at"].astimezone(UTC).date().isoformat(),
                    status=f"{streak.count()} failed runs in a row",
                    path=f"/admin/integrations/{instance.pk}",
                    sort=(0, instance.name),
                )
            )
        if instance.last_success_at:
            age = now - instance.last_success_at
            if age.total_seconds() > instance.stale_after_hours * 3600:
                found.append(
                    Finding(
                        key=(
                            f"int:{instance.pk}:stale:"
                            f"{instance.last_success_at.isoformat()}:v{rule.policy_version}"
                        ),
                        title=instance.name,
                        detail=f"No successful sync for more than {instance.stale_after_hours} h.",
                        when=instance.last_success_at.astimezone(UTC).date().isoformat(),
                        status="Stale",
                        path=f"/admin/integrations/{instance.pk}",
                        sort=(1, instance.name),
                    )
                )
    return found


COLLECTORS = {
    Event.CERTIFICATE_EXPIRY: _certificates,
    Event.DOMAIN_EXPIRY: _domains,
    Event.LIFECYCLE_EOL: _lifecycle,
    Event.INTEGRATION_FAILURE: _integrations,
}


# --- Evaluation -------------------------------------------------------------------------------


def eligible(rule, user) -> bool:
    if not user.is_active or not (user.email or "").strip():
        return False
    granted = set(user.permission_codes())
    return all(code in granted for code in REQUIRED_PERMISSIONS[rule.event])


def pending(rule: NotificationRule, user, today=None) -> list[Finding]:
    """Findings for ``user`` that were not announced yet."""
    today = today or today_utc()
    findings = COLLECTORS[rule.event](rule, user, today)
    told = set(
        AlertLedger.objects.filter(
            rule=rule, user=user, key__in=[f.key for f in findings]
        ).values_list("key", flat=True)
    )
    return sorted((f for f in findings if f.key not in told), key=lambda f: f.sort)


def _context(rule, findings: list[Finding], more: int) -> dict:
    base = render.app_url()
    return {
        "rule_name": rule.name,
        "count": len(findings) + more,
        "more": more,
        "items": [
            {
                "title": f.title,
                "detail": f.detail,
                "date": f.when,
                "status": f.status,
                "url": f"{base}{f.path}" if base else f.path,
            }
            for f in findings
        ],
    }


def evaluate(rule: NotificationRule, today=None) -> dict:
    counts = {"recipients": 0, "messages": 0, "items": 0, "skipped_recipients": 0}
    if not rule.enabled:
        return counts
    for user in rule.recipients.all():
        if not eligible(rule, user):
            counts["skipped_recipients"] += 1
            continue
        counts["recipients"] += 1
        new = pending(rule, user, today)
        if not new:
            continue
        batch, more = new[:MAX_ITEMS], max(0, len(new) - MAX_ITEMS)
        digest = hashlib.sha256("|".join(sorted(f.key for f in batch)).encode()).hexdigest()[:32]
        with transaction.atomic():
            message, _ = services.enqueue(
                rule.event,
                user.email,
                _context(rule, batch, more),
                event_type=rule.event,
                dedup_key=f"rule:{rule.pk}:{user.pk}:{digest}",
            )
            AlertLedger.objects.bulk_create(
                [AlertLedger(rule=rule, user=user, key=f.key, message=message) for f in batch],
                ignore_conflicts=True,
            )
        counts["messages"] += 1
        counts["items"] += len(batch)
    return counts


def evaluate_all(today=None) -> dict:
    """Hourly. Does nothing while mail is disabled: findings wait instead of expiring."""
    if not services.get_profile().enabled:
        return {"skipped": "mail disabled"}
    total = {"rules": 0, "messages": 0, "items": 0}
    for rule in NotificationRule.objects.filter(enabled=True).prefetch_related("recipients"):
        result = evaluate(rule, today)
        summary = f"{result['messages']} message(s), {result['items']} new item(s)"
        if result["skipped_recipients"]:
            summary += (
                f"; {result['skipped_recipients']} recipient(s) skipped (no e-mail or access)"
            )
        NotificationRule.objects.filter(pk=rule.pk).update(
            last_run_at=timezone.now(), last_run_summary=summary[:300]
        )
        total["rules"] += 1
        total["messages"] += result["messages"]
        total["items"] += result["items"]
    if total["messages"]:
        logger.info("Notification rules: %s", total)
    return total
