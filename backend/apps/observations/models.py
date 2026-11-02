import uuid

from django.db import models

from apps.integrations.models import IntegrationInstance, SyncRun


class Observation(models.Model):
    """Immutable, timestamped record of what one source reported about one device.

    Append-only (model guard + PostgreSQL trigger). An unchanged payload is not
    stored again; the source link's last-seen time is refreshed instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(
        IntegrationInstance, on_delete=models.PROTECT, related_name="observations"
    )
    sync_run = models.ForeignKey(
        SyncRun, null=True, blank=True, on_delete=models.PROTECT, related_name="observations"
    )
    external_id = models.CharField(max_length=200)
    observed_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    checksum = models.CharField(max_length=64)
    payload = models.JSONField()
    normalized = models.JSONField()
    normalizer_version = models.PositiveSmallIntegerField()
    source_version = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-observed_at", "-received_at"]
        indexes = [
            models.Index(fields=["instance", "external_id", "observed_at"]),
            models.Index(fields=["checksum"]),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Observations are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Observations are immutable")
