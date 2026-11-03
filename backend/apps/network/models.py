import uuid

from django.db import models

from apps.integrations.models import IntegrationInstance, SyncRun


class NeighborEvidence(models.Model):
    """What a source saw on a device port: a MAC in the forwarding table (FDB) or a
    neighbour advertised by LLDP/CDP. Evidence only (docs/05, docs/15 A24): a MAC on a
    port is not proof of a cable, and a trunk port sees many MACs.

    Rows are keyed per instance and refreshed by each evidence pass; rows not seen
    in a complete pass are marked inactive, never deleted.
    """

    class Kind(models.TextChoices):
        FDB = "fdb", "MAC seen on port (FDB)"
        LLDP = "lldp", "LLDP neighbour"
        CDP = "cdp", "CDP neighbour"
        OTHER = "other", "Other neighbour protocol"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Local side: the reporting device (source external ID) and its port.
    local_external_id = models.CharField(max_length=200)
    local_port = models.CharField(max_length=100, blank=True)
    # Remote side: a MAC (FDB) or an advertised neighbour (links).
    remote_mac = models.CharField(max_length=17, blank=True)
    remote_external_id = models.CharField(max_length=200, blank=True)
    remote_hostname = models.CharField(max_length=253, blank=True)
    remote_port = models.CharField(max_length=100, blank=True)
    remote_platform = models.CharField(max_length=200, blank=True)
    vlan = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    last_run = models.ForeignKey(
        SyncRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["local_external_id", "local_port"]
        constraints = [
            models.UniqueConstraint(
                "instance",
                "kind",
                "local_external_id",
                "local_port",
                "remote_mac",
                "remote_external_id",
                "remote_hostname",
                "remote_port",
                "vlan",
                name="network_neighbor_evidence_unique",
            )
        ]
        indexes = [
            models.Index(fields=["instance", "local_external_id"]),
            models.Index(fields=["remote_mac"]),
            models.Index(fields=["instance", "remote_external_id"]),
        ]
