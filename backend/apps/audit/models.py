import uuid

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """Append-only audit record. PostgreSQL trigger also blocks UPDATE/DELETE."""

    class Source(models.TextChoices):
        API = "api", "API"
        CLI = "cli", "Command line"
        SYSTEM = "system", "System"

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
        DENIED = "denied", "Denied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    actor_label = models.CharField(max_length=255)
    action = models.CharField(max_length=100, db_index=True)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    object_label = models.CharField(max_length=255, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.SUCCESS)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.API)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["object_type", "object_id", "occurred_at"]),
            models.Index(fields=["actor", "occurred_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Audit events are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit events are append-only")
