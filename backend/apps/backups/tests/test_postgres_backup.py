"""Real encrypted backup and isolated DB restore using disposable CI databases."""

import json
import os
import secrets
import subprocess
import sys
import uuid
from contextlib import nullcontext
from pathlib import Path

import pytest
from django.db import connection
from django.utils import timezone


def _roundtrip(tmp_path):
    import psycopg
    from psycopg import sql

    from apps.accounts.models import Role, User
    from apps.assets.models import Asset, AssetCategory
    from apps.audit import services as audit
    from apps.backups import runner
    from apps.domains.models import Certificate, DomainRegistration
    from apps.exports.models import ExportJob
    from apps.groups.models import AssetGroup, AssetGroupMembership
    from apps.imports.crypto import EXPORTS, decrypt, encrypt
    from apps.imports.models import ImportJob
    from apps.licensing.models import LicenseEntitlement, LicenseProduct
    from apps.lifecycle.models import LifecycleMilestone, LifecycleProduct, LifecycleSource
    from apps.notifications.models import OutboxMessage, SmtpProfile
    from apps.organizations.models import Site
    from apps.software.models import SoftwareInstallation, SoftwareProduct, SoftwareVersion

    os.environ["ITAM_APP_REVISION"] = "1" * 40
    os.environ["ITAM_BACKUP_IMAGE_REFERENCE"] = "fixture/backup@sha256:" + "2" * 64
    admin_user = User.objects.create_user(
        "restore.fixture", "disposable-test-password", display_name="Restore Fixture"
    )
    admin_user.roles.add(Role.objects.get(code="system_admin"))
    site = Site.objects.create(code="RESTORE", name="Restore fixture")
    category = AssetCategory.objects.create(code="restore-fixture", name="Restore fixture")
    asset = Asset.objects.create(name="Restore fixture", site=site, category=category)
    group = AssetGroup.objects.create(name="Restore fixture", kind="static")
    membership = AssetGroupMembership.objects.create(
        group=group,
        asset=asset,
        source="explicit",
        added_at=timezone.now(),
        added_by=admin_user,
    )
    software = SoftwareProduct.objects.create(name="Fixture software", name_key="fixture software")
    software_version = SoftwareVersion.objects.create(
        product=software, version="1", version_key="1"
    )
    installation = SoftwareInstallation.objects.create(
        version=software_version,
        asset=asset,
        raw_name="Fixture software",
        first_seen_at=timezone.now(),
        last_seen_at=timezone.now(),
        created_by=admin_user,
    )
    domain = DomainRegistration.objects.create(fqdn="restore.example.invalid")
    certificate = Certificate.objects.create(
        fingerprint_sha256="c" * 64,
        not_before=timezone.now(),
        not_after=timezone.now(),
        pem="fixture-public-certificate",
        source="uploaded",
        first_seen_at=timezone.now(),
    )
    license_product = LicenseProduct.objects.create(
        publisher="Fixture",
        name="Restore license",
        identity_key="fixture-restore",
    )
    entitlement = LicenseEntitlement.objects.create(
        product=license_product,
        reference="fixture",
        reference_key="fixture",
        quantity=5,
    )
    product = LifecycleProduct.objects.create(
        kind="hardware",
        vendor="Fixture",
        vendor_key="fixture",
        name="Model 1",
        name_key="model 1",
    )
    evidence = LifecycleSource.objects.create(
        publisher="Fixture",
        title="Synthetic lifecycle evidence",
        source_type="manual",
        collected_on=timezone.now().date(),
        document_ref="synthetic-fixture",
    )
    milestone = LifecycleMilestone.objects.create(
        product=product,
        source=evidence,
        milestone_type="end_of_support",
        date=timezone.now().date(),
        verification="verified",
        reviewed_by=admin_user,
        reviewed_at=timezone.now(),
    )
    SmtpProfile.objects.create(enabled=False)
    outbox = OutboxMessage.objects.create(
        event_type="fixture",
        template_code="backup_alert",
        template_version=1,
        to_address="fixture@example.invalid",
        subject="Synthetic restore fixture",
        queued_at=timezone.now(),
        next_attempt_at=timezone.now(),
        expires_at=timezone.now(),
    )
    original = b"asset_tag,name\nfixture,Restore fixture\n"
    imported = ImportJob.objects.create(
        family="assets",
        template_version=1,
        filename="fixture.csv",
        file_format="csv",
        size_bytes=len(original),
        checksum="fixture",
        file_encrypted=encrypt(original),
        purge_after=timezone.now(),
        created_by=admin_user,
    )
    exported = ExportJob.objects.create(
        family="assets",
        file_format="csv",
        scope="all",
        status="completed",
        row_count=1,
        filename="fixture.csv",
        file_encrypted=encrypt(original, EXPORTS),
        created_by=admin_user,
    )
    audit.record(action="backups.drill_fixture", object_type="asset", object_id=asset.pk)
    password = tmp_path / "password"
    password.write_text(secrets.token_urlsafe(48))
    env = dict(
        os.environ,
        RESTIC_REPOSITORY=str(tmp_path / "repository"),
        RESTIC_PASSWORD_FILE=str(password),
        RESTIC_CACHE_DIR=str(tmp_path / "cache"),
    )
    if repo := os.environ.get("ITAM_TEST_SFTP_REPOSITORY"):
        from django.conf import settings

        settings.ITAM_SECRETS_DIR = os.environ["ITAM_TEST_SFTP_SECRETS"]
        os.environ["RESTIC_REPOSITORY"] = repo
        os.environ["RESTIC_PASSWORD_FILE"] = str(
            Path(settings.ITAM_SECRETS_DIR) / "restic_password"
        )
        env = runner.repository_env()
    else:
        runner.repository_env = lambda: env  # Local-only fixture validation fallback.
    runner.restic(["init"], env=env)
    snapshot, manifest = runner.backup(uuid.uuid4())
    assert len(snapshot) == 64
    assert manifest["counts"]["assets_asset"] >= 1
    wrong = tmp_path / "wrong"
    wrong.write_text("incorrect-fixture-password")
    with pytest.raises(runner.RunnerError):
        runner.verify(snapshot, manifest, dict(env, RESTIC_PASSWORD_FILE=str(wrong)))
    restored = tmp_path / "restore"
    restored.mkdir()
    if repo:
        pin = Path(settings.ITAM_SECRETS_DIR) / "restic_known_hosts"
        correct_pin = pin.read_text()
        wrong_public = (Path(settings.ITAM_SECRETS_DIR) / "restic_ssh_key.pub").read_text().split()
        pin.write_text(correct_pin.split()[0] + " " + " ".join(wrong_public[:2]) + "\n")
        with pytest.raises(runner.RunnerError):
            runner.verify(snapshot, manifest, env)
        pin.write_text(correct_pin)
    runner.restic(["restore", snapshot, "--target", str(restored)], env=env)
    assert json.loads((restored / "manifest.json").read_text()) == manifest
    # CI passes this entirely synthetic database to the Docker-isolated drill job.
    if output := os.environ.get("ITAM_BACKUP_DRILL_ARTIFACT_DIR"):
        artifact = Path(output)
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "recovery.json").write_text(json.dumps({"snapshot_id": snapshot}))
    db = connection.settings_dict
    target = "itam_drill_" + uuid.uuid4().hex
    params = dict(host=db["HOST"], port=db["PORT"], user=db["USER"], password=db["PASSWORD"])
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        try:
            pg_env = dict(
                os.environ,
                PGHOST=str(db["HOST"]),
                PGPORT=str(db["PORT"]),
                PGUSER=db["USER"],
                PGPASSWORD=db["PASSWORD"],
            )
            runner.run(
                [
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    target,
                    str(restored / "database.dump"),
                ],
                env=pg_env,
            )
            with psycopg.connect(dbname=target, **params) as recovered:
                for table, count in manifest["counts"].items():
                    actual = recovered.execute(
                        sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                    ).fetchone()[0]
                    assert actual == count
                for table, pk in [
                    ("assets_asset", asset.pk),
                    ("groups_assetgroup", group.pk),
                    ("lifecycle_lifecycleproduct", product.pk),
                    ("domains_domainregistration", domain.pk),
                    ("domains_certificate", certificate.pk),
                    ("licensing_licenseentitlement", entitlement.pk),
                    ("groups_assetgroupmembership", membership.pk),
                    ("software_softwareinstallation", installation.pk),
                    ("lifecycle_lifecyclemilestone", milestone.pk),
                    ("notifications_outboxmessage", outbox.pk),
                ]:
                    assert recovered.execute(
                        sql.SQL("SELECT id FROM {} WHERE id=%s").format(sql.Identifier(table)), [pk]
                    ).fetchone()
                blob = recovered.execute(
                    "SELECT file_encrypted FROM imports_importjob WHERE id=%s", [imported.pk]
                ).fetchone()[0]
                assert decrypt(bytes(blob)) == original
                blob = recovered.execute(
                    "SELECT file_encrypted FROM exports_exportjob WHERE id=%s", [exported.pk]
                ).fetchone()[0]
                assert decrypt(bytes(blob), EXPORTS) == original
                recovered.execute("UPDATE notifications_smtpprofile SET enabled=false")
        finally:
            control.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))


@pytest.mark.integration
@pytest.mark.django_db
def test_real_dump_encrypted_repository_and_isolated_restore(tmp_path):
    if connection.vendor != "postgresql":
        pytest.skip("Real backup/restore requires PostgreSQL and restic (CI).")
    import psycopg
    from psycopg import sql

    db = connection.settings_dict
    source = "itam_backup_source_" + uuid.uuid4().hex
    params = dict(host=db["HOST"], port=db["PORT"], user=db["USER"], password=db["PASSWORD"])
    # Normal pytest transaction rollback remains intact. The actual source DB has its own
    # committed fixtures and production audit triggers; cleanup drops only this new DB.
    from apps.backups.tests.sftp_fixture import destination

    storage = destination(tmp_path) if os.environ.get("ITAM_BACKUP_TEST_SFTP") else nullcontext({})
    with storage as storage_env:
        with psycopg.connect(dbname="postgres", autocommit=True, **params) as control:
            control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(source)))
            try:
                env = dict(
                    os.environ,
                    POSTGRES_DB=source,
                    POSTGRES_HOST=str(db["HOST"]),
                    POSTGRES_PORT=str(db["PORT"]),
                    POSTGRES_USER=db["USER"],
                    POSTGRES_PASSWORD=db["PASSWORD"],
                    DJANGO_SETTINGS_MODULE="config.settings.test",
                    **storage_env,
                )
                env.pop("ITAM_TEST_DB_SQLITE", None)
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), str(tmp_path)],
                    env=env,
                    capture_output=True,
                    timeout=300,
                )
                assert result.returncode == 0, result.stderr.decode()
            finally:
                control.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(source)))


@pytest.mark.django_db
def test_disposable_roundtrip_fixtures_are_valid_before_external_tools(tmp_path, monkeypatch):
    from apps.backups import runner

    monkeypatch.setenv("ITAM_APP_REVISION", "1" * 40)
    monkeypatch.setenv("ITAM_BACKUP_IMAGE_REFERENCE", "fixture/backup@sha256:" + "2" * 64)

    def stop_before_repository(*args, **kwargs):
        raise runner.RunnerError("fixture setup completed")

    monkeypatch.setattr(runner, "run", stop_before_repository)
    with pytest.raises(runner.RunnerError, match="fixture setup completed"):
        _roundtrip(tmp_path)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", verbosity=0, interactive=False)
    _roundtrip(Path(sys.argv[1]))
