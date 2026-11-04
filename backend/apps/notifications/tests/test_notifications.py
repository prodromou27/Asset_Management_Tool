"""SMTP settings, templates and the mail outbox (Task 018a, docs/10, docs/15 A17/A18).

A local SMTP server (``fake_smtp``) with a generated test CA runs on 127.0.0.1; nothing is
sent outside the machine.
"""

import ipaddress
import ssl
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.notifications import render, services
from apps.notifications.models import NotificationTemplate, OutboxMessage, SmtpProfile

from .fake_smtp import Behaviour, FakeSmtp

pytestmark = pytest.mark.django_db
URL = "/api/v1/settings/smtp/"
PASSWORD = "Sm7p-test-only"


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca_and_leaf():
    now = datetime.now(UTC) - timedelta(days=1)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("ITAM Test CA"))
        .issuer_name(_name("ITAM Test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(_name("127.0.0.1"))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return ca, leaf, key


@pytest.fixture
def tls_files(tmp_path, settings):
    ca, leaf, key = make_ca_and_leaf()
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "smtp-ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "leaf.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "leaf.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    settings.ITAM_SECRETS_DIR = str(secrets_dir)
    settings.ITAM_TLS_ALLOW_LOOPBACK = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "leaf.pem", tmp_path / "leaf.key")
    return context


@pytest.fixture
def smtp(tls_files, monkeypatch):
    monkeypatch.setenv("ITAM_SMTP_PASSWORD", PASSWORD)
    server = FakeSmtp(tls_files, Behaviour(auth=("itam", PASSWORD))).start()
    yield server
    server.close()


@pytest.fixture
def admin(admin_user, client_for):
    return client_for(admin_user)


def configure(client, server, **extra):
    body = {
        "host": "127.0.0.1",
        "port": server.port,
        "security": "starttls",
        "username": "itam",
        "password_ref": "env:ITAM_SMTP_PASSWORD",
        "ca_bundle_ref": "file:smtp-ca.pem",
        "from_address": "itam-alerts@example.test",
        "reply_to": "it-support@example.test",
        "timeout_seconds": 5,
        "enabled": True,
        **extra,
    }
    version = client.get(URL).json()["version"]
    response = client.patch(URL, body, format="json", HTTP_IF_MATCH=f'"{version}"')
    assert response.status_code == 200, response.json()
    return response.json()


def queue(to="owner@example.test", key=None, **context):
    with transaction.atomic():
        message, created = services.enqueue(
            "smtp_test",
            to,
            {"requested_by": "Owner", **context},
            event_type="test.event",
            dedup_key=key,
        )
    return message, created


# --- Settings ---------------------------------------------------------------------------------


def test_profile_rules_and_no_credential_values(admin, smtp, settings):
    profile = admin.get(URL).json()
    assert profile["enabled"] is False and profile["password_status"] == "not_set"
    saved = configure(admin, smtp)
    assert saved["password_status"] == "configured"
    assert PASSWORD not in str(saved)

    def patch(**body):
        version = admin.get(URL).json()["version"]
        return admin.patch(URL, body, format="json", HTTP_IF_MATCH=f'"{version}"')

    assert patch(security="none").status_code == 422  # credentials only over TLS
    assert patch(password_ref="env:DJANGO_SECRET_KEY").status_code == 422
    assert patch(password_ref="env:ITAM_INTEGRATION_X").status_code == 422
    assert patch(ca_bundle_ref="env:ITAM_SMTP_CA").status_code == 422
    assert patch(host="169.254.169.254").status_code == 422
    assert patch(host="smtp.example.test:25").status_code == 422
    assert patch(username="", password_ref="", security="none").status_code == 200  # relay
    assert admin.patch(URL, {"port": 25}, format="json").status_code == 428
    events = AuditEvent.objects.filter(action__startswith="notifications.smtp.")
    assert events.filter(action="notifications.smtp.enable").exists()
    assert PASSWORD not in str(list(events.values("before", "after")))


def test_defaults_from_environment(settings, admin):
    settings.ITAM_SMTP_DEFAULTS = {
        "host": "mailpit",
        "port": 1025,
        "security": "none",
        "from_address": "itam@localhost",
    }
    profile = admin.get(URL).json()
    assert (profile["host"], profile["port"], profile["security"]) == ("mailpit", 1025, "none")
    assert profile["from_address"] == "" and profile["enabled"] is False  # not a valid sender


def test_connection_test_sends_nothing(admin, smtp):
    configure(admin, smtp)
    result = admin.post("/api/v1/smtp/test/").json()
    assert result["last_test_ok"] is True and result["last_test_error"] == ""
    assert smtp.received == []

    smtp.behaviour.auth = ("itam", "other")
    failed = admin.post("/api/v1/smtp/test/").json()
    assert failed["last_test_ok"] is False and "535" in failed["last_test_error"]
    assert PASSWORD not in failed["last_test_error"]


def test_never_downgrades_and_validates_certificates(admin, smtp):
    configure(admin, smtp)
    smtp.behaviour.starttls = False
    result = admin.post("/api/v1/smtp/test/").json()
    assert result["last_test_ok"] is False and "STARTTLS" in result["last_test_error"]

    smtp.behaviour.starttls = True
    configure(admin, smtp, ca_bundle_ref="")  # system CAs do not know the test CA
    result = admin.post("/api/v1/smtp/test/").json()
    assert result["last_test_ok"] is False and "not trusted" in result["last_test_error"]


def test_send_test_email_to_the_admin_only(admin, admin_user, smtp, client_for, make_user):
    configure(admin, smtp)
    response = admin.post("/api/v1/smtp/test-email/")
    assert response.status_code == 200 and response.json()["status"] == "sent"
    [mail] = smtp.received
    assert mail.recipients == [admin_user.email] and mail.tls and mail.user == "itam"
    message = mail.message
    assert message["Subject"] == "ITAM test message"
    assert message["Reply-To"] == "it-support@example.test"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_body(("html",)) is not None
    assert "Admin.One" in message.get_body(("plain",)).get_content()
    assert admin.get(URL).json()["last_test_email_at"]
    assert AuditEvent.objects.filter(action="notifications.smtp.test_email").exists()

    no_mail = make_user("nomail.admin", roles=["system_admin"], all_sites=True)
    assert client_for(no_mail).post("/api/v1/smtp/test-email/").status_code == 409
    configure(admin, smtp, enabled=False)
    assert admin.post("/api/v1/smtp/test-email/").status_code == 409


# --- Outbox -----------------------------------------------------------------------------------


def test_outage_retries_then_dead_letter_and_business_write_succeeds(admin, smtp):
    """A17: the relay is down; the business transaction commits, the message retries with
    backoff, ends as a visible dead letter, and can be retried to deliver once."""
    configure(admin, smtp)
    smtp.close()
    message, created = queue()
    assert created and message.status == "queued"

    now = timezone.now()
    assert services.deliver_due(now)["retrying"] == 1
    message.refresh_from_db()
    assert message.status == "retrying" and message.attempts == 1
    assert 48 <= (message.next_attempt_at - now).total_seconds() <= 72  # 60 s ± 20 %
    assert services.deliver_due(now)["retrying"] == 0  # not due yet

    for _ in range(5):
        message.refresh_from_db()
        services.deliver_due(message.next_attempt_at)
    message.refresh_from_db()
    assert message.status == "dead" and message.attempts == 6
    stats = admin.get("/api/v1/notifications/outbox/stats/").json()
    assert stats["dead_last_24h"] == 1 and stats["problems"]

    server = FakeSmtp(smtp.context, smtp.behaviour)
    server.start()
    try:
        configure(admin, server)
        retried = admin.post(f"/api/v1/notifications/outbox/{message.pk}/retry/")
        assert retried.status_code == 200 and retried.json()["status"] == "queued"
        assert services.deliver_due()["sent"] == 1
        assert services.deliver_due()["sent"] == 0  # delivered once
        assert len(server.received) == 1
    finally:
        server.close()
    message.refresh_from_db()
    assert message.status == "sent" and message.message_id.startswith("<")


def test_recipient_deferral_and_bounce(admin, smtp):
    configure(admin, smtp)
    smtp.behaviour.rcpt_reply = "450 4.2.1 Mailbox busy"
    deferred, _ = queue("busy@example.test")
    services.deliver_due()
    deferred.refresh_from_db()
    assert deferred.status == "retrying" and "450" in deferred.last_error

    smtp.behaviour.rcpt_reply = "550 5.1.1 No such user"
    bounced, _ = queue("nobody@example.test")
    services.deliver_due()
    bounced.refresh_from_db()
    assert bounced.status == "dead" and "550" in bounced.last_error and bounced.attempts == 1


def test_dedup_disabled_queue_expiry_and_cancel(admin, smtp, settings):
    first, created = queue(key="cert:abc:30:v1")
    again, created_again = queue(key="cert:abc:30:v1")
    assert created and not created_again and again.pk == first.pk
    assert OutboxMessage.objects.count() == 1

    assert services.deliver_due()["sent"] == 0  # mail disabled: message waits
    first.refresh_from_db()
    assert first.status == "queued"
    services.deliver_due(first.expires_at + timedelta(seconds=1))
    first.refresh_from_db()
    assert first.status == "expired"

    other, _ = queue()
    cancelled = admin.post(f"/api/v1/notifications/outbox/{other.pk}/cancel/")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert admin.post(f"/api/v1/notifications/outbox/{other.pk}/cancel/").status_code == 409
    rows = admin.get("/api/v1/notifications/outbox/", {"status": "expired,cancelled"}).json()
    assert len(rows["items"]) == 2 and "body_text" not in rows["items"][0]


def test_configuration_problem_does_not_use_up_attempts(admin, smtp, monkeypatch):
    configure(admin, smtp)
    monkeypatch.delenv("ITAM_SMTP_PASSWORD")
    message, _ = queue()
    services.deliver_due()
    message.refresh_from_db()
    assert message.status == "retrying" and message.attempts == 0
    assert message.last_error.startswith("Mail settings:")


def test_purge_clears_bodies_of_finished_messages(admin, smtp, settings):
    configure(admin, smtp)
    message, _ = queue()
    services.deliver_due()
    assert services.purge() == 0
    later = timezone.now() + timedelta(days=settings.ITAM_NOTIFICATION_BODY_RETENTION_DAYS + 1)
    assert services.purge(later) == 1
    message.refresh_from_db()
    assert message.body_text == "" and message.bodies_purged and message.status == "sent"


# --- Templates --------------------------------------------------------------------------------


def test_rendering_escapes_values_and_strips_header_breaks():
    out = render.render(
        "Alert: {{ name }}",
        "Asset {{ name }}",
        "<p>{{ name }}</p>",
        {"name": "<script>x</script>\r\nBcc: evil@example.test"},
    )
    assert "\n" not in out.subject and "\r" not in out.subject
    assert "&lt;script&gt;" in out.body_html and "<script>" not in out.body_html
    for bad in (
        "{% load static %}",
        "{% include 'x.html' %}",
        "{{ name|safe }}",
        "{% debug %}",
        "{{ name|safeseq }}",
    ):
        with pytest.raises(render.TemplateError):
            render.check("body_html", bad)


def test_template_edit_preview_and_versions(admin, client_for, auditor_user):
    url = "/api/v1/notifications/templates/smtp_test/"
    template = admin.get(url).json()
    assert template["version"] == 1 and template["variables"]
    bad = admin.patch(url, {"body_html": "{{ x|safe }}"}, format="json", HTTP_IF_MATCH='"1"')
    assert bad.status_code == 422 and "body_html" in bad.json()["error"]["field_errors"]
    preview = admin.post(
        f"{url}preview/", {"subject": "Hi {{ requested_by }}"}, format="json"
    ).json()
    assert preview["subject"] == "Hi Admin One"
    saved = admin.patch(
        url, {"subject": "{{ app_name }} mail check"}, format="json", HTTP_IF_MATCH='"1"'
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2
    message, _ = queue()
    assert message.template_version == 2 and message.subject == "ITAM mail check"
    auditor = client_for(auditor_user)
    assert auditor.get(url).status_code == 200
    assert (
        auditor.patch(url, {"subject": "x"}, format="json", HTTP_IF_MATCH='"2"').status_code == 403
    )
    assert NotificationTemplate.objects.get(code="smtp_test").version == 2


def test_permissions(client_for, auditor_user, operator_user, admin):
    auditor = client_for(auditor_user)
    assert auditor.get(URL).status_code == 200
    assert auditor.get("/api/v1/notifications/outbox/").status_code == 200
    assert auditor.post("/api/v1/smtp/test/").status_code == 403
    assert auditor.post("/api/v1/smtp/test-email/").status_code == 403
    assert auditor.patch(URL, {"port": 25}, format="json", HTTP_IF_MATCH='"1"').status_code == 403
    operator = client_for(operator_user)
    assert operator.get(URL).status_code == 403
    assert operator.get("/api/v1/notifications/outbox/stats/").status_code == 403
    assert SmtpProfile.objects.count() <= 1
