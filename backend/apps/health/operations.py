"""Read-only operational evidence. Never contacts vendors, SMTP or backup repositories."""

import shutil
import tempfile
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import User
from apps.backups.models import BackupJob, BackupPolicy, RestoreDrill
from apps.exports.models import ExportJob
from apps.imports.models import ImportJob
from apps.integrations.adapters import registry
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.lifecycle.models import LifecycleSource
from apps.notifications import services as notifications
from apps.notifications.models import SmtpProfile

from .services import collect_dependency_statuses


def row(code, label, status, detail, href="/"):
    return {"id": code, "label": label, "status": status, "detail": detail, "href": href}


def integration_state(instance, now):
    if not instance.is_enabled or instance.status == "disconnected":
        return "disabled", "Intentionally disabled; no healthy synchronization is implied."
    if not registry.get(instance.source_id):
        return "unknown", "No implemented adapter. Configuration does not enable synchronization."
    if not settings.ITAM_ALLOW_LIVE_INTEGRATIONS or not instance.live_access_approved:
        return "unknown", "Live access is not approved and enabled. No connection was attempted."
    if (
        instance.status == "degraded"
        or instance.consecutive_failures
        or instance.last_test_ok is False
    ):
        return "down", "A recorded connection or synchronization failure needs review."
    if not instance.last_success_at:
        return "unknown", "No successful synchronization recorded."
    if instance.last_success_at < now - timedelta(hours=instance.stale_after_hours):
        return "needs_attention", "The last successful synchronization exceeds the stale limit."
    return "up", "A recent successful synchronization is recorded; no live probe was performed."


def collect_operations():
    now = timezone.now()
    dependencies = collect_dependency_statuses()
    components = [
        row(
            item.name,
            item.name.capitalize(),
            "up" if item.healthy else "down",
            item.detail or "Reachable.",
        )
        for item in dependencies
    ]
    try:
        usage = shutil.disk_usage(tempfile.gettempdir())
        components.append(
            row(
                "scratch",
                "Application scratch storage",
                "needs_attention" if usage.free / usage.total < 0.1 else "up",
                f"{usage.free // 1048576} MiB free of {usage.total // 1048576} MiB. "
                "Temporary filesystem only; database/off-host capacity is not measured.",
            )
        )
    except OSError:
        components.append(
            row(
                "scratch",
                "Application scratch storage",
                "unknown",
                "Free space could not be measured; review host monitoring.",
            )
        )
    components.append(
        row(
            "workers",
            "Workers and scheduler",
            "unknown",
            "Durable job counts are shown below. No worker heartbeat is available; "
            "queue depth alone does not establish worker health.",
        )
    )
    manual = [
        row(
            "https",
            "Trusted HTTPS and secure cookies",
            "unknown",
            "Verify the deployed FQDN, certificate trust and cookie policy on the target host.",
            "/admin/security",
        ),
        row(
            "identity",
            "SSO/MFA and emergency access",
            "unknown",
            "Local sign-in is implemented; external SSO/MFA is planned. Verify emergency access.",
            "/admin/users",
        ),
        row(
            "permissions",
            "Site scopes and import/export permissions",
            "unknown",
            "Complete a target-host access review and permission test with named accounts.",
            "/admin/users",
        ),
        row(
            "monitoring",
            "Host monitoring, storage and retention",
            "unknown",
            "Confirm queue alerts, protected logs, capacity and retention on the target host.",
        ),
    ]
    result = {
        "checked_at": now,
        "production_readiness": "incomplete",
        "components": components,
        "integrations": [],
        "queues": [],
        "checklist": list(manual),
    }
    if not next((item.healthy for item in dependencies if item.name == "database"), False):
        result["checklist"].append(
            row(
                "database",
                "Application evidence",
                "unknown",
                "Database unavailable; configuration and job evidence cannot be read.",
            )
        )
        return result
    base_components = list(components)
    try:
        return _database_evidence(result, now)
    except DatabaseError:
        # A database may disappear after its probe. Do not return partial or stale green data.
        result["integrations"] = []
        result["queues"] = []
        result["components"] = base_components
        result["checklist"] = manual + [
            row(
                "database",
                "Application evidence",
                "unknown",
                "Configuration evidence could not be read. Review database health.",
            )
        ]
        return result


def _database_evidence(result, now):
    components = result["components"]
    checklist = result["checklist"]
    instances = list(IntegrationInstance.objects.select_related("source").order_by("name"))
    for instance in instances:
        status, detail = integration_state(instance, now)
        result["integrations"].append(
            row(
                str(instance.pk),
                instance.name,
                status,
                detail,
                f"/admin/integrations/{instance.pk}",
            )
        )
    for code, label in (
        ("librenms", "LibreNMS read-only source"),
        ("endpoint_central", "Endpoint Central on-premises"),
        ("intune", "Microsoft Intune"),
        ("defender", "Microsoft Defender"),
        ("m365", "Microsoft 365 / Entra"),
    ):
        matches = [instance for instance in instances if instance.source_id == code]
        states = [integration_state(instance, now)[0] for instance in matches]
        status = "needs_attention"
        if states and all(state == "up" for state in states):
            status = "up"
        elif states and all(state == "disabled" for state in states):
            status = "disabled"
        checklist.append(
            row(
                code,
                label,
                status,
                "Review instances and capabilities. Disabled sources need owner acceptance."
                if matches
                else "Configure the required source or document intentional unavailability.",
                "/admin/integrations",
            )
        )
    admins = User.objects.filter(is_active=True, roles__code="system_admin").distinct().count()
    checklist.append(
        row(
            "admins",
            "Two named administrators",
            "unknown" if admins >= 2 else "needs_attention",
            f"{admins} active system admins. Verify separate sign-ins, scopes and recovery.",
            "/admin/users",
        )
    )
    evidence = LifecycleSource.objects.filter(last_verified_on__isnull=False).exists()
    checklist.append(
        row(
            "lifecycle",
            "Lifecycle evidence and Unknown behavior",
            "unknown" if evidence else "needs_attention",
            "Verified-date evidence exists; confirm matching/Unknown behavior in staging."
            if evidence
            else "No verified-date lifecycle source recorded.",
            "/lifecycle/catalogue",
        )
    )
    profile = SmtpProfile.objects.first()
    mail_stats = notifications.stats(profile=profile if profile is not None else SmtpProfile())
    waiting = mail_stats["counts"]["queued"] + mail_stats["counts"]["retrying"]
    failed = mail_stats["dead_last_24h"]
    mail_status = "disabled"
    if profile and profile.enabled:
        mail_status = "needs_attention"
        if (
            mail_stats["configured"]
            and profile.last_test_ok
            and profile.last_test_email_at
            and not mail_stats["problems"]
        ):
            mail_status = "up"
    mail = row(
        "smtp",
        "SMTP and delivery",
        mail_status,
        f"{waiting} waiting; {failed} permanent failures in 24h. "
        "Recorded tests are evidence only; recipient acceptance remains an operator check.",
        "/admin/smtp",
    )
    components.append(mail)
    checklist.append(
        row(
            "mail",
            "SMTP test and alert recipients",
            "unknown" if mail_status == "up" else "needs_attention",
            "Verify authorized test delivery and configured alert recipients.",
            "/admin/smtp",
        )
    )
    policy = BackupPolicy.objects.first()
    backup = (
        BackupJob.objects.filter(kind="backup", status="succeeded").order_by("-finished_at").first()
    )
    drill = RestoreDrill.objects.order_by("-finished_at").first()
    recent = bool(
        backup
        and backup.recovery_point
        and policy
        and backup.recovery_point >= now - timedelta(hours=policy.rpo_hours)
    )
    backup_status = (
        "disabled"
        if not settings.ITAM_BACKUP_ALLOW_RUN or not policy or not policy.enabled
        else "up"
        if recent
        else "needs_attention"
    )
    components.append(
        row(
            "backups",
            "Encrypted backup jobs",
            backup_status,
            "A recent verified recovery point is recorded."
            if recent
            else "No recovery point within the configured objective.",
            "/admin/backups",
        )
    )
    checklist.append(
        row(
            "recovery",
            "Off-host backup and restore rehearsal",
            "unknown" if recent and drill and drill.passed else "needs_attention",
            "Validate off-host separation, recovered keys and an approved timed restore.",
            "/admin/backups",
        )
    )
    for label, model in (
        ("Source synchronization", SyncRun),
        ("Imports", ImportJob),
        ("Exports", ExportJob),
        ("Backups", BackupJob),
    ):
        counts = dict(
            model.objects.values_list("status")
            .annotate(total=Count("pk"))
            .values_list("status", "total")
        )
        result["queues"].append(
            {
                "name": label,
                "queued": counts.get("queued", 0),
                "running": sum(
                    counts.get(state, 0)
                    for state in ("running", "processing", "previewing", "committing")
                ),
                "failed": counts.get("failed", 0),
                "worker_status": "unknown",
            }
        )
    return result
