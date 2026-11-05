"""Real encrypted backup and isolated DB restore using disposable CI databases."""

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest
from django.db import connection
from django.utils import timezone

from apps.audit import services as audit
from apps.backups import runner
from apps.domains.models import Certificate, DomainRegistration
from apps.groups.models import AssetGroup
from apps.imports.crypto import decrypt, encrypt
from apps.imports.models import ImportJob
from apps.licensing.models import LicenseEntitlement, LicenseProduct
from apps.lifecycle.models import LifecycleProduct


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_real_dump_encrypted_repository_and_isolated_restore(
    tmp_path, monkeypatch, make_asset, hq, switch, admin_user
):
    if connection.vendor != "postgresql":
        pytest.skip("Real backup/restore requires PostgreSQL and restic (CI).")
    import psycopg
    from psycopg import sql

    monkeypatch.setenv("ITAM_APP_REVISION", "1" * 40)
    monkeypatch.setenv("ITAM_BACKUP_IMAGE_REFERENCE", "fixture/backup@sha256:" + "2" * 64)
    asset = make_asset(site=hq, category=switch)
    group = AssetGroup.objects.create(name="Restore fixture", kind="static")
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
    audit.record(action="backups.drill_fixture", object_type="asset", object_id=asset.pk)
    password = tmp_path / "password"
    password.write_text("disposable-ci-repository-password")
    env = dict(
        os.environ,
        RESTIC_REPOSITORY=str(tmp_path / "repository"),
        RESTIC_PASSWORD_FILE=str(password),
        RESTIC_CACHE_DIR=str(tmp_path / "cache"),
    )
    runner.run(["restic", "init"], env=env)
    monkeypatch.setattr(runner, "repository_env", lambda: env)
    snapshot, manifest = runner.backup(uuid.uuid4())
    assert len(snapshot) == 64
    assert manifest["counts"]["assets_asset"] >= 1
    wrong = tmp_path / "wrong"
    wrong.write_text("incorrect-fixture-password")
    with pytest.raises(runner.RunnerError):
        runner.verify(snapshot, manifest, dict(env, RESTIC_PASSWORD_FILE=str(wrong)))
    restored = tmp_path / "restore"
    restored.mkdir()
    runner.run(["restic", "restore", snapshot, "--target", str(restored)], env=env)
    assert json.loads((restored / "manifest.json").read_text()) == manifest
    # CI passes this entirely synthetic database to the Docker-isolated drill job.
    if output := os.environ.get("ITAM_BACKUP_DRILL_ARTIFACT_DIR"):
        artifact = Path(output)
        artifact.mkdir(parents=True, exist_ok=True)
        shutil.copy2(restored / "manifest.json", artifact / "manifest.json")
        shutil.copy2(restored / "database.dump", artifact / "database.dump")
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
                ]:
                    assert recovered.execute(
                        sql.SQL("SELECT id FROM {} WHERE id=%s").format(sql.Identifier(table)), [pk]
                    ).fetchone()
                blob = recovered.execute(
                    "SELECT file_encrypted FROM imports_importjob WHERE id=%s", [imported.pk]
                ).fetchone()[0]
                assert decrypt(bytes(blob)) == original
                recovered.execute("UPDATE notifications_smtpprofile SET enabled=false")
        finally:
            control.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))
