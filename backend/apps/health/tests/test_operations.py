from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.db import OperationalError
from django.utils import timezone

from apps.accounts.models import GeneralSettings
from apps.backups.models import BackupPolicy
from apps.health import operations
from apps.health.services import DependencyStatus
from apps.integrations.models import DiscoverySource, IntegrationInstance
from apps.notifications.models import OutboxMessage, SmtpProfile

pytestmark = pytest.mark.django_db
URL = "/api/v1/health/operations/"


@pytest.fixture(autouse=True)
def dependencies(monkeypatch):
    monkeypatch.setattr(
        operations,
        "collect_dependency_statuses",
        lambda: [
            DependencyStatus("database", True),
            DependencyStatus("redis", True),
        ],
    )


def test_operational_health_permissions_and_no_secret_or_path_output(
    api_client, client_for, operator_user, auditor_user
):
    assert api_client.get(URL).status_code == 401
    assert client_for(operator_user).get(URL).status_code == 403
    response = client_for(auditor_user).get(URL)
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["production_readiness"] == "incomplete"
    assert any(row["status"] == "unknown" for row in body["checklist"])
    assert all(queue["worker_status"] == "unknown" for queue in body["queues"])
    assert not SmtpProfile.objects.exists() and not BackupPolicy.objects.exists()
    assert GeneralSettings.objects.count() == 1  # Login supplies defaults; no extra rows.
    assert "credential_ref" not in str(body) and "password_ref" not in str(body)


def test_database_failure_returns_unknown_evidence_without_querying_models(monkeypatch):
    monkeypatch.setattr(
        operations, "collect_dependency_statuses", lambda: [DependencyStatus("database", False)]
    )
    query = Mock(side_effect=AssertionError("must not query when unavailable"))
    monkeypatch.setattr(IntegrationInstance.objects, "select_related", query)
    result = operations.collect_operations()
    assert result["production_readiness"] == "incomplete" and not result["queues"]
    assert result["checklist"][-1]["status"] == "unknown"
    query.assert_not_called()


def test_database_disappearing_does_not_expose_exception_or_partial_evidence(monkeypatch):
    monkeypatch.setattr(
        IntegrationInstance.objects,
        "select_related",
        Mock(side_effect=OperationalError("private-host-secret")),
    )
    result = operations.collect_operations()
    assert "private-host-secret" not in str(result)
    assert not result["integrations"] and not result["queues"]
    assert result["checklist"][-1]["status"] == "unknown"


def test_recorded_integration_health_distinguishes_gates_stale_and_disabled(settings):
    source = DiscoverySource.objects.get(code="librenms")
    instance = IntegrationInstance(
        source=source,
        is_enabled=True,
        live_access_approved=True,
        status="available",
        last_success_at=timezone.now(),
        stale_after_hours=48,
    )
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = False
    assert operations.integration_state(instance, timezone.now())[0] == "unknown"
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = True
    assert operations.integration_state(instance, timezone.now())[0] == "up"
    instance.last_success_at -= timedelta(hours=49)
    assert operations.integration_state(instance, timezone.now())[0] == "needs_attention"
    instance.is_enabled = False
    assert operations.integration_state(instance, timezone.now())[0] == "disabled"
    instance.is_enabled = True
    instance.last_success_at = None
    assert operations.integration_state(instance, timezone.now())[0] == "unknown"
    instance.last_test_ok = False
    assert operations.integration_state(instance, timezone.now())[0] == "down"


def test_operational_mail_uses_existing_retry_health_without_sending():
    SmtpProfile.objects.create(
        enabled=True,
        host="smtp.example.invalid",
        from_address="itam@example.invalid",
        last_test_ok=True,
        last_test_email_at=timezone.now(),
    )
    OutboxMessage.objects.create(
        event_type="fixture",
        template_code="backup_alert",
        template_version=1,
        to_address="fixture@example.invalid",
        subject="Fixture",
        status="retrying",
        queued_at=timezone.now(),
        next_attempt_at=timezone.now(),
        expires_at=timezone.now(),
    )
    result = operations.collect_operations()
    mail = next(row for row in result["components"] if row["id"] == "smtp")
    assert mail["status"] == "needs_attention" and "1 waiting" in mail["detail"]
