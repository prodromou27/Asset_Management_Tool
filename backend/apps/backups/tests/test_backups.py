import json
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.backups import runner, services
from apps.backups.models import BackupJob
from apps.notifications.models import OutboxMessage, SmtpProfile

pytestmark = pytest.mark.django_db
URL = "/api/v1/backups/"
SNAPSHOT = "a" * 64


@pytest.fixture
def allowed(settings, monkeypatch):
    settings.ITAM_BACKUP_ALLOW_RUN = True
    settings.ITAM_BACKUP_TARGET_LABEL = "Approved fixture repository"
    monkeypatch.setattr(services, "kick", Mock())
    monkeypatch.setattr(runner, "retention", Mock())


def successful_job():
    return BackupJob.objects.create(
        kind="backup",
        status="succeeded",
        target_label="Fixture",
        snapshot_id=SNAPSHOT,
        active_slot=None,
        recovery_point=timezone.now(),
        finished_at=timezone.now(),
        manifest={"size_bytes": 123, "recovery_point": timezone.now().isoformat()},
    )


def test_permissions_and_no_secret_endpoints(client_for, admin_user, auditor_user, operator_user):
    admin, auditor, operator = map(client_for, [admin_user, auditor_user, operator_user])
    for endpoint in ["policy/", "summary/", "jobs/", "drills/", "report/"]:
        assert admin.get(URL + endpoint).status_code == 200
        assert auditor.get(URL + endpoint).status_code == 200
        assert operator.get(URL + endpoint).status_code == 403
    assert auditor.post(URL + "jobs/").status_code == 403
    assert auditor.patch(URL + "policy/", {"enabled": True}, format="json").status_code == 403
    assert admin.post(URL + "restore/", {}, format="json").status_code == 404
    response = admin.get(URL + "report/")
    assert "attachment" in response["Content-Disposition"]
    assert response["Cache-Control"] == "no-store"
    assert AuditEvent.objects.filter(action="backups.report_download").exists()


def test_default_gates_and_summary(client_for, admin_user):
    client = client_for(admin_user)
    assert client.post(URL + "jobs/").status_code == 409
    p = client.get(URL + "policy/").json()
    assert not p["enabled"] and not p["retention_enabled"]
    assert (
        client.patch(
            URL + "policy/", {"enabled": True}, format="json", HTTP_IF_MATCH=str(p["version"])
        ).status_code
        == 409
    )
    response = client.get(URL + "summary/").json()
    assert not response["execution_allowed"]
    assert response["last_backup"] is None
    assert any("DEC-09" in problem for problem in response["problems"])


def test_policy_lock_validation_audit(allowed, client_for, admin_user):
    client = client_for(admin_user)
    assert client.patch(URL + "policy/", {"hour_utc": 4}, format="json").status_code == 428
    assert (
        client.patch(
            URL + "policy/", {"hour_utc": 24}, format="json", HTTP_IF_MATCH="1"
        ).status_code
        == 422
    )
    response = client.patch(
        URL + "policy/", {"enabled": True, "hour_utc": 4}, format="json", HTTP_IF_MATCH="1"
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert (
        client.patch(URL + "policy/", {"hour_utc": 5}, format="json", HTTP_IF_MATCH="1").status_code
        == 409
    )
    event = AuditEvent.objects.get(action="backups.policy_update")
    assert event.before["hour_utc"] == 2 and event.after["hour_utc"] == 4


def test_single_active_job_and_no_early_success(allowed, client_for, admin_user, monkeypatch):
    client = client_for(admin_user)
    response = client.post(URL + "jobs/")
    assert response.status_code == 202
    job = BackupJob.objects.get(pk=response.json()["id"])
    assert job.status == "queued"
    assert client.post(URL + "jobs/").status_code == 409

    def partial(*args):
        assert BackupJob.objects.get(pk=job.pk).status == "running"
        raise runner.RunnerError("Remote checksum verification failed.")

    monkeypatch.setattr(runner, "backup", partial)
    services.execute(job.pk)
    job.refresh_from_db()
    assert job.status == "failed" and job.active_slot is None
    runner.retention.assert_not_called()
    assert services.summary()["last_backup"] is None
    assert AuditEvent.objects.filter(action="backups.backup_failed").exists()


def test_success_verification_replay_and_retention_warning(allowed, monkeypatch):
    job = services.request_job()
    now = timezone.now()
    mock = Mock(return_value=(SNAPSHOT, {"size_bytes": 123, "recovery_point": now.isoformat()}))
    monkeypatch.setattr(runner, "backup", mock)
    runner.retention.side_effect = runner.RunnerError("Retention unavailable")
    services.execute(job.pk)
    services.execute(job.pk)
    assert mock.call_count == 1
    job.refresh_from_db()
    assert job.status == "succeeded" and job.snapshot_id == SNAPSHOT
    assert job.size_bytes == 123 and job.recovery_point == now and job.warning
    assert AuditEvent.objects.filter(action="backups.retention_failed").exists()
    assert services.summary()["last_backup"].pk == job.pk


def test_verify_existing_snapshot_failure_preserves_previous_good(
    allowed, monkeypatch, client_for, admin_user
):
    old = successful_job()
    client = client_for(admin_user)
    response = client.post(URL + f"jobs/{old.pk}/verify/")
    assert response.status_code == 202
    verify = BackupJob.objects.get(pk=response.json()["id"])
    monkeypatch.setattr(runner, "repository_env", lambda: {})
    monkeypatch.setattr(
        runner, "verify", Mock(side_effect=runner.RunnerError("Wrong key or corrupt repository"))
    )
    services.execute(verify.pk)
    verify.refresh_from_db()
    old.refresh_from_db()
    assert verify.status == "failed" and old.status == "succeeded"
    assert client.post(URL + f"jobs/{verify.pk}/verify/").status_code == 422


def test_revocation_stops_queued_work(allowed, monkeypatch, admin_user, settings):
    job = services.request_job(actor=admin_user)
    mock = Mock()
    monkeypatch.setattr(runner, "backup", mock)
    admin_user.is_active = False
    admin_user.save()
    services.execute(job.pk)
    mock.assert_not_called()
    assert BackupJob.objects.get(pk=job.pk).status == "failed"
    next_job = services.request_job()
    settings.ITAM_BACKUP_ALLOW_RUN = False
    services.execute(next_job.pk)
    mock.assert_not_called()


def test_schedule_retries_queue_and_never_unlocks_stranded_job(allowed, monkeypatch):
    p = services.policy()
    p.enabled = True
    p.save()
    services.dispatch()
    assert BackupJob.objects.count() == 1
    job = BackupJob.objects.first()
    services.dispatch()
    assert BackupJob.objects.count() == 1
    assert services.kick.called
    BackupJob.objects.filter(pk=job.pk).update(
        status="running", created_at=timezone.now() - timedelta(hours=7)
    )
    services.dispatch()
    assert BackupJob.objects.get(pk=job.pk).active_slot == 1


def test_alerts_reuse_outbox_dedup_only_admins(allowed, admin_user, auditor_user, monkeypatch):
    SmtpProfile.objects.update_or_create(pk=1, defaults={"enabled": True})
    monkeypatch.setattr("apps.notifications.services._kick", Mock())
    services.alert("Fixture failure", "one")
    services.alert("Fixture failure", "one")
    assert OutboxMessage.objects.count() == 1
    assert OutboxMessage.objects.get().to_address == admin_user.email


def test_restore_attestation_validation_audit_and_rpo(allowed, client_for, admin_user):
    job = successful_job()
    client = client_for(admin_user)
    body = {
        "backup": str(job.pk),
        "target_label": "Isolated fixture",
        "passed": True,
        "started_at": (timezone.now() - timedelta(minutes=4)).isoformat(),
        "finished_at": timezone.now().isoformat(),
        "notes": "Counts and evidence checked.",
        "isolated": False,
        "outbound_disabled": True,
    }
    assert client.post(URL + "drills/", body, format="json").status_code == 422
    body["isolated"] = True
    assert client.post(URL + "drills/", body, format="json").status_code == 201
    assert AuditEvent.objects.filter(action="backups.restore_drill_recorded").exists()
    BackupJob.objects.filter(pk=job.pk).update(recovery_point=timezone.now() - timedelta(hours=25))
    assert any("RPO" in message for message in services.summary()["problems"])
    body["finished_at"] = (timezone.now() + timedelta(days=1)).isoformat()
    assert client.post(URL + "drills/", body, format="json").status_code == 422


@pytest.mark.parametrize(
    "repo",
    [
        "/tmp/repo",
        "https://example.test/repo",
        "sftp://u:pass@example.test/repo",
        "sftp://example.test/",
    ],
)
def test_repository_validation(repo, monkeypatch):
    monkeypatch.setenv("RESTIC_REPOSITORY", repo)
    with pytest.raises(runner.RunnerError):
        runner.repository_env()


def test_secret_path_and_environment_sanitized(tmp_path, settings, monkeypatch):
    settings.ITAM_SECRETS_DIR = str(tmp_path / "secrets")
    root = Path(settings.ITAM_SECRETS_DIR)
    root.mkdir()
    password = root / "password"
    password.write_text("fixture-only")
    monkeypatch.setenv("RESTIC_REPOSITORY", "sftp://backup@example.test/repo")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(password))
    monkeypatch.setenv("RESTIC_PASSWORD_COMMAND", "untrusted-command")
    monkeypatch.setenv("ITAM_SMTP_PASSWORD", "fixture-only-secret")
    env = runner.repository_env()
    assert "RESTIC_PASSWORD_COMMAND" not in env and "ITAM_SMTP_PASSWORD" not in env
    password.write_text("")
    with pytest.raises(runner.RunnerError):
        runner.repository_env()


def test_command_errors_never_expose_stderr(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, "restic", stderr=b"secret-password")),
    )
    with pytest.raises(runner.RunnerError) as exc:
        runner.run(["restic", "check"])
    assert "secret-password" not in str(exc.value)


def test_readback_checks_manifest_and_hash(tmp_path, monkeypatch):
    expected = {"database_sha256": "incorrect"}

    def fake(args, **kwargs):
        if args[1] == "restore":
            directory = Path(args[-1])
            (directory / "manifest.json").write_text(json.dumps(expected))
            (directory / "database.dump").write_bytes(b"corrupt")
        return b""

    monkeypatch.setattr(runner, "run", fake)
    with pytest.raises(runner.RunnerError, match="checksum"):
        runner.verify(SNAPSHOT, expected, {})
    with pytest.raises(runner.RunnerError, match="immutable"):
        runner.verify("latest", expected, {})


def test_sqlite_is_never_a_real_backup(tmp_path):
    from django.db import connection

    if connection.vendor == "sqlite":
        with pytest.raises(runner.RunnerError, match="PostgreSQL"):
            runner.dump_database(tmp_path, "fixture")
