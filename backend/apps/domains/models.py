"""Domains, TLS certificates and approved TLS endpoints (Task 017, docs/03 "Domains", docs/06).

- ``DomainRegistration``: an owned domain entered by people. The registration expiry is
  Unknown unless someone records it with evidence; it is never inferred from a TLS
  certificate (docs/15 A12).
- ``Certificate``: one public X.509 certificate, unique by SHA-256 fingerprint. Only the
  public certificate and its parsed fields are kept; private keys are refused.
- ``TlsEndpoint``: an administrator-approved host + port + SNI that ITAM may connect to in
  order to read the presented certificate. No arbitrary URLs (docs/06, docs/14 SSRF).
- ``CertificateDeployment``: a certificate seen on an endpoint, first/last seen. One
  certificate can serve several endpoints (docs/15 A11); a rotation opens a new row.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

_USER = settings.AUTH_USER_MODEL


class DomainRegistration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fqdn = models.CharField(max_length=253, unique=True)  # lower-case, IDNA (punycode)
    owner = models.CharField(max_length=200, blank=True)  # responsible person or team
    registrar = models.CharField(max_length=200, blank=True)
    expires_on = models.DateField(null=True, blank=True)  # empty: Unknown
    expiry_evidence = models.CharField(max_length=500, blank=True)
    expiry_verified_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    expiry_verified_at = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(null=True, blank=True)  # unknown unless stated
    note = models.TextField(blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    modified_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fqdn"]
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_on__isnull=True) | ~Q(expiry_evidence=""),
                name="domain_expiry_needs_evidence",
            )
        ]

    def __str__(self):
        return self.fqdn


class Certificate(models.Model):
    class Source(models.TextChoices):
        OBSERVED = "observed", "Observed on an endpoint"
        UPLOADED = "uploaded", "Uploaded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fingerprint_sha256 = models.CharField(max_length=64, unique=True)  # lower-case hex
    subject = models.CharField(max_length=1000, blank=True)
    common_name = models.CharField(max_length=300, blank=True)
    issuer = models.CharField(max_length=1000, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    sans = models.JSONField(default=list, blank=True)  # DNS names and IP addresses
    not_before = models.DateTimeField()
    not_after = models.DateTimeField()
    signature_algorithm = models.CharField(max_length=100, blank=True)
    public_key = models.CharField(max_length=60, blank=True)  # e.g. "RSA 2048", "EC P-256"
    self_signed = models.BooleanField(default=False)
    is_ca = models.BooleanField(default=False)
    pem = models.TextField()  # public certificate only
    source = models.CharField(max_length=10, choices=Source.choices)
    first_seen_at = models.DateTimeField()
    created_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["not_after", "common_name"]
        indexes = [models.Index(fields=["not_after"])]

    def __str__(self):
        return self.common_name or self.fingerprint_sha256[:16]


class TlsEndpoint(models.Model):
    class CheckStatus(models.TextChoices):
        NEVER = "never", "Not checked yet"
        OK = "ok", "Certificate read"
        FAILED = "failed", "Check failed"
        BLOCKED = "blocked", "Target not allowed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.CharField(max_length=253)  # lower-case FQDN or IP literal
    port = models.PositiveIntegerField(default=443)
    sni = models.CharField(max_length=253, blank=True)  # empty: no SNI (IP literal hosts)
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tls_endpoints",
    )
    service = models.CharField(max_length=200, blank=True)
    owner = models.CharField(max_length=200, blank=True)
    enabled = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    current_certificate = models.ForeignKey(
        Certificate, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    hostname_matches = models.BooleanField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(
        max_length=10, choices=CheckStatus.choices, default=CheckStatus.NEVER
    )
    last_error = models.CharField(max_length=500, blank=True)
    last_address = models.CharField(max_length=45, blank=True)
    tls_version = models.CharField(max_length=20, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_reason = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    modified_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["host", "port"]
        constraints = [
            models.UniqueConstraint(
                fields=["host", "port", "sni"],
                condition=Q(retired_at__isnull=True),
                name="tls_endpoint_unique_active",
            ),
            models.CheckConstraint(
                condition=Q(port__gte=1, port__lte=65535), name="tls_endpoint_port_range"
            ),
        ]

    def __str__(self):
        return f"{self.host}:{self.port}" + (
            f" ({self.sni})" if self.sni and self.sni != self.host else ""
        )


class CertificateDeployment(models.Model):
    id = models.BigAutoField(primary_key=True)
    endpoint = models.ForeignKey(TlsEndpoint, on_delete=models.CASCADE, related_name="deployments")
    certificate = models.ForeignKey(
        Certificate, on_delete=models.PROTECT, related_name="deployments"
    )
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    # Set when another certificate was observed on the endpoint (rotation).
    replaced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "certificate"],
                condition=Q(replaced_at__isnull=True),
                name="certificate_deployment_current",
            )
        ]
