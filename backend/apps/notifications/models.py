"""SMTP profile, message templates and the delivery outbox (Task 018a, docs/10).

- ``SmtpProfile``: the single outgoing mail configuration. The password is a secret
  reference (``env:ITAM_SMTP_<NAME>`` or ``file:<name>``), never a value (docs/10
  "credentials only in secret store"). Disabled until an administrator enables it.
- ``NotificationTemplate``: subject, plain-text and optional HTML body, versioned. Rendered
  with a restricted template language that escapes values (HTML) and strips line breaks
  from subjects.
- ``OutboxMessage``: one rendered message to one recipient. Writes that cause mail only
  insert a row; the worker sends it later, so a mail outage never blocks a business
  transaction (docs/15 A17). Retries use exponential backoff with jitter and end in
  ``dead`` (visible to administrators); a ``dedup_key`` makes enqueueing idempotent.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

_USER = settings.AUTH_USER_MODEL


class SmtpProfile(models.Model):
    class Security(models.TextChoices):
        STARTTLS = "starttls", "STARTTLS (required)"
        TLS = "tls", "Implicit TLS"
        NONE = "none", "None (approved internal relay without credentials)"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    host = models.CharField(max_length=253, blank=True)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(max_length=10, choices=Security.choices, default=Security.STARTTLS)
    username = models.CharField(max_length=254, blank=True)
    password_ref = models.CharField(max_length=120, blank=True)
    ca_bundle_ref = models.CharField(max_length=120, blank=True)
    from_address = models.EmailField(blank=True)
    from_name = models.CharField(max_length=100, default="ITAM")
    reply_to = models.EmailField(blank=True)
    timeout_seconds = models.PositiveIntegerField(default=15)
    max_per_minute = models.PositiveIntegerField(default=60)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.CharField(max_length=500, blank=True)
    last_test_email_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    modified_by = models.ForeignKey(_USER, null=True, on_delete=models.SET_NULL, related_name="+")
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="smtp_profile_singleton"),
            models.CheckConstraint(
                condition=Q(port__gte=1, port__lte=65535), name="smtp_profile_port_range"
            ),
        ]

    def __str__(self):
        return f"{self.host}:{self.port}" if self.host else "SMTP (not configured)"

    @property
    def uses_auth(self) -> bool:
        return bool(self.username)


class NotificationTemplate(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    # Variables the producer supplies, documented for editors: [{"name", "description"}].
    variables = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=300)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    modified_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class OutboxMessage(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        RETRYING = "retrying", "Waiting to retry"
        SENT = "sent", "Sent"
        DEAD = "dead", "Failed (dead letter)"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    OPEN = (Status.QUEUED, Status.RETRYING, Status.SENDING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=60)
    template_code = models.CharField(max_length=60)
    template_version = models.PositiveIntegerField()
    dedup_key = models.CharField(max_length=300, null=True, blank=True, unique=True)
    to_address = models.EmailField()
    subject = models.CharField(max_length=300)
    body_text = models.TextField(blank=True)  # cleared after the retention period
    body_html = models.TextField(blank=True)
    message_id = models.CharField(max_length=200, blank=True)  # our Message-ID header
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=6)
    next_attempt_at = models.DateTimeField()
    last_error = models.CharField(max_length=500, blank=True)
    queued_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    bodies_purged = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        _USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-queued_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]

    def __str__(self):
        return f"{self.template_code} → {self.to_address} ({self.status})"
