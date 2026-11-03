"""Endpoint security observations (Task 009).

Security facts reported by a security source (Defender for Endpoint): onboarding status,
sensor health, exposure level, risk score, device tags and first/last seen. They are
kept apart from business-owned asset fields: nothing here is written to an Asset, and
the asset relationship is resolved through the instance's SourceLink at read time.

One row per (integration instance, source machine ID). Rows are never deleted when the
source stops reporting a machine: a machine missing from a complete listing gets
``missing_since``, which is not proof that the device no longer exists.
"""

import uuid

from django.db import models

from apps.integrations.models import IntegrationInstance, SyncRun
from apps.observations.models import Observation


class EndpointSecurityState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    # Source machine ID, scoped to the instance (and so to its tenant).
    external_id = models.CharField(max_length=200)
    tenant_id = models.CharField(max_length=100, blank=True)
    entra_device_id = models.CharField(max_length=36, blank=True)
    computer_dns_name = models.CharField(max_length=253, blank=True)
    os_platform = models.CharField(max_length=100, blank=True)
    os_version = models.CharField(max_length=100, blank=True)
    onboarding_status = models.CharField(max_length=60, blank=True)
    health_status = models.CharField(max_length=60, blank=True)
    exposure_level = models.CharField(max_length=60, blank=True)
    risk_score = models.CharField(max_length=60, blank=True)
    device_tags = models.JSONField(default=list, blank=True)
    machine_group = models.CharField(max_length=200, blank=True)
    # As reported by the source. last_seen_at is when the source last received data from
    # the device: not a real-time online status.
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # Original source values for provenance.
    original = models.JSONField(default=dict, blank=True)
    observation = models.ForeignKey(
        Observation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Sync bookkeeping: when ITAM last stored this row, and from which run.
    last_synced_at = models.DateTimeField()
    last_run = models.ForeignKey(
        SyncRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    missing_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "external_id"], name="security_state_instance_external"
            )
        ]
        indexes = [models.Index(fields=["entra_device_id"])]

    def __str__(self):
        return f"{self.instance_id}:{self.external_id}"
