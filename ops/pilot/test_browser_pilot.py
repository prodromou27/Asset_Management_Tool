"""Explicit opt-in rehearsal against pytest-django's disposable test database."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from apps.accounts.models import Role, User
from apps.assets.models import Asset, AssetCategory
from apps.audit.models import AuditEvent
from apps.exports.models import ExportJob
from apps.groups.models import AssetGroup, AssetGroupMembership
from apps.notifications.models import OutboxMessage, SmtpProfile
from apps.organizations.models import Site, UserSiteGrant
from django.conf import settings
from django.db import connection
from django.utils import timezone

if (
    os.environ.get("ITAM_RUN_LOCAL_PILOT") != "1"
    or settings.SETTINGS_MODULE != "config.settings.test"
):
    raise pytest.UsageError("Run this isolated rehearsal using 'pnpm e2e' in frontend.")

database = settings.DATABASES["default"]
if database["ENGINE"] != "django.db.backends.sqlite3" and database.get("HOST") not in {
    "localhost",
    "127.0.0.1",
    "::1",
}:
    raise pytest.UsageError("Local pilot requires a loopback database host.")

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.django_db(transaction=True)
def test_real_browser_pilot(live_server, settings):
    name = str(connection.settings_dict["NAME"])
    assert name.startswith("test_") or "mode=memory" in name or name == ":memory:"
    assert not Asset.objects.exists() and not User.objects.exists()
    settings.CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:5198"]
    settings.CELERY_BROKER_URL = "memory://"
    settings.CELERY_RESULT_BACKEND = "cache+memory://"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = False

    password = secrets.token_urlsafe(32)
    manager = User.objects.create_user("pilot.scoped", password, display_name="Pilot scoped user")
    manager.roles.add(Role.objects.get(code="itam_manager"))
    admin = User.objects.create_user(
        "pilot.admin", password, display_name="Pilot administrator", all_sites=True
    )
    admin.roles.add(Role.objects.get(code="system_admin"))
    hq = Site.objects.create(code="PILOT-HQ", name="Synthetic pilot HQ")
    remote = Site.objects.create(code="PILOT-REMOTE", name="Synthetic remote site")
    UserSiteGrant.objects.create(user=manager, site=hq)
    laptop = AssetCategory.objects.get(code="workstations-laptop")
    visible = Asset.objects.create(name="pilot-hq-laptop", site=hq, category=laptop)
    hidden = Asset.objects.create(name="pilot-hidden-remote", site=remote, category=laptop)
    group = AssetGroup.objects.create(name="Pilot mixed-site group", kind="static")
    for asset in (visible, hidden):
        AssetGroupMembership.objects.create(
            group=group, asset=asset, source="explicit", added_at=timezone.now()
        )
    SmtpProfile.objects.create(enabled=False)
    payload = {
        "api": live_server.url,
        "database": connection.vendor,
        "username": manager.username,
        "admin": admin.username,
        "password": password,
        "user_id": str(manager.pk),
        "site_id": str(hq.pk),
        "visible_id": str(visible.pk),
        "hidden_id": str(hidden.pk),
        "group_id": str(group.pk),
        "monitor_category": str(AssetCategory.objects.get(code="monitors").pk),
    }
    try:
        result = subprocess.run(
            ["node", "e2e/pilot.mjs"],
            input=json.dumps(payload),
            cwd=ROOT / "frontend",
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        output = (result.stdout + result.stderr).replace(password, "[redacted]")
        assert result.returncode == 0, output[-6000:]
    finally:
        password = ""

    created = Asset.objects.get(name="pilot-monitor")
    assert created.site_id == hq.pk and created.category.code == "monitors"
    assert not created.ip_addresses.exists()
    hidden.refresh_from_db()
    assert hidden.name == "pilot-hidden-remote"
    manager.refresh_from_db()
    assert not manager.is_active
    job = ExportJob.objects.get(created_by=manager)
    assert job.status == "completed" and job.row_count == 2
    assert b"pilot-hq-laptop" not in bytes(job.file_encrypted)
    assert job.download_count == 1
    assert not OutboxMessage.objects.exists()
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {
        "auth.login",
        "assets.create",
        "exports.create",
        "exports.complete",
        "exports.download",
        "users.disable",
    } <= actions
    report_path = ROOT / "frontend/test-results/pilot/report.json"
    report = json.loads(report_path.read_text())
    report["status"] = "passed"
    report["database_assertions"] = "passed: audit, scope, encryption, revocation, no outbox"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


@pytest.mark.parametrize("target", ["http://example.invalid:8000", "https://127.0.0.1:8000"])
def test_browser_refuses_non_loopback_http_target(target):
    password = secrets.token_urlsafe(32)
    result = subprocess.run(
        ["node", "e2e/pilot.mjs"],
        input=json.dumps({"api": target, "password": password}),
        cwd=ROOT / "frontend",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert password not in result.stdout + result.stderr


def test_remote_database_refused_before_test_database_setup():
    env = {**os.environ, "POSTGRES_HOST": "example.invalid"}
    env.pop("ITAM_TEST_DB_SQLITE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "../ops/pilot/test_browser_pilot.py",
            "--collect-only",
            "-c",
            "pyproject.toml",
            "-q",
        ],
        cwd=ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "Local pilot requires a loopback database host" in result.stdout + result.stderr
