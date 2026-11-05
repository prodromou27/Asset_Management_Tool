import uuid

from django.conf import settings
from django.db import models


class DigestSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    report = models.CharField(
        max_length=20,
        choices=[(key, key.title()) for key in ("inventory", "lifecycle", "coverage", "groups")],
    )
    filters = models.JSONField(default=dict)
    enabled = models.BooleanField(default=False)
    hour_utc = models.PositiveSmallIntegerField(default=7)
    cadence = models.CharField(
        max_length=10, choices=[("daily", "Daily"), ("weekly", "Weekly")], default="daily"
    )
    weekday = models.PositiveSmallIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)


class DigestDispatch(models.Model):
    schedule = models.ForeignKey(DigestSchedule, on_delete=models.PROTECT)
    slot = models.DateTimeField()
    policy_version = models.PositiveIntegerField(default=1)
    message = models.OneToOneField(
        "notifications.OutboxMessage",
        null=True,
        on_delete=models.SET_NULL,
        related_name="report_dispatch",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["schedule", "slot"], name="report_digest_slot_unique")
        ]
