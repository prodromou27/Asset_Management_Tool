"""Fixed-command PostgreSQL/restic runner; no shell, URLs or credentials from HTTP input.

Only the dedicated backup worker has the repository and secret mounts. All current
application blobs (import originals/export artifacts) live in PostgreSQL, so one exported
snapshot also protects them. Deployment secrets require a separate recovery mechanism.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone


class RunnerError(Exception):
    pass


def run(args, *, cwd=None, env=None):
    try:
        return subprocess.run(
            args, cwd=cwd, env=env, capture_output=True, check=True, timeout=7200
        ).stdout
    except (OSError, subprocess.SubprocessError) as from_exc:
        # Tool stderr may include repository paths, connection strings or credentials.
        raise RunnerError(
            f"{args[0]} failed. Check tool availability, credentials, connectivity and capacity "
            "in the restricted operator environment; command output was withheld."
        ) from from_exc


def repository_env():
    repo = os.environ.get("RESTIC_REPOSITORY", "")
    parsed = urlsplit(repo.removeprefix("sftp:"))
    # Only administrator-provisioned SFTP repositories; no HTTP, local paths or passwords.
    if (
        not repo.startswith("sftp://")
        or not parsed.hostname
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.strip("/")
    ):
        raise RunnerError("Configure an approved off-host SFTP repository without a password URL.")
    secret_root = Path(settings.ITAM_SECRETS_DIR).resolve()
    password_file = Path(os.environ.get("RESTIC_PASSWORD_FILE", "")).resolve()
    if (
        not password_file.is_relative_to(secret_root)
        or not password_file.is_file()
        or password_file.stat().st_size == 0
    ):
        raise RunnerError(
            "A nonempty repository password file in the secrets directory is required."
        )
    # Strip inherited restic hooks/alternate credential sources. Host-key verification uses
    # the operator-provisioned known_hosts in the worker's home directory.
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env.update(RESTIC_REPOSITORY=repo, RESTIC_PASSWORD_FILE=str(password_file))
    env["RESTIC_CACHE_DIR"] = "/tmp/restic-cache"
    return env


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump_database(directory, job_id):
    if connection.vendor != "postgresql":
        raise RunnerError("Backups require PostgreSQL; SQLite is test-only.")
    revision = os.environ.get("ITAM_APP_REVISION", "")
    image = os.environ.get("ITAM_BACKUP_IMAGE_REFERENCE", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not re.search(
        r"@sha256:[0-9a-f]{64}$", image
    ):
        raise RunnerError(
            "Record the deployed full Git revision and pinned backup image digest first."
        )
    db = connection.settings_dict
    env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
    env.update(
        PGHOST=str(db["HOST"]),
        PGPORT=str(db["PORT"]),
        PGUSER=str(db["USER"]),
        PGPASSWORD=str(db["PASSWORD"]),
        PGDATABASE=str(db["NAME"]),
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot = cursor.fetchone()[0]
            recovery_point = timezone.now()
            migrations = list(
                MigrationRecorder.Migration.objects.order_by("app", "name").values_list(
                    "app", "name"
                )
            )
            counts = {}
            # Counts taken from the same DB snapshot as pg_dump for the restore drill.
            for table in connection.introspection.table_names():
                if table.startswith(
                    (
                        "assets_",
                        "groups_",
                        "lifecycle_",
                        "software_",
                        "licensing_",
                        "domains_",
                        "observations_",
                        "audit_",
                        "imports_",
                        "exports_",
                    )
                ):
                    cursor.execute(f"SELECT count(*) FROM {connection.ops.quote_name(table)}")
                    counts[table] = cursor.fetchone()[0]
            run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    f"--snapshot={snapshot}",
                    "--file=database.dump",
                ],
                cwd=directory,
                env=env,
            )
    dump = directory / "database.dump"
    manifest = {
        "format": "itam.backup.v1",
        "job_id": str(job_id),
        "recovery_point": recovery_point.isoformat(),
        "migrations": [list(item) for item in migrations],
        "counts": counts,
        "database_sha256": checksum(dump),
        "size_bytes": dump.stat().st_size,
        "blob_storage": "PostgreSQL import/export binary fields; no external media configured",
        "prerequisites": "Compatible application revision, PostgreSQL 16, separately recovered "
        "Django/import encryption secrets and deployment configuration",
        "app_revision": revision,
        "image_reference": image,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify(snapshot, expected, env):
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot):
        raise RunnerError("A full immutable snapshot ID is required.")
    run(["restic", "check", "--read-data"], env=env)
    with TemporaryDirectory(prefix="itam-verify-") as temp:
        directory = Path(temp)
        run(["restic", "restore", snapshot, "--target", str(directory)], env=env)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if (
                manifest != expected
                or checksum(directory / "database.dump") != expected["database_sha256"]
            ):
                raise ValueError("checksum")
        except (OSError, ValueError, KeyError) as exc:
            raise RunnerError(
                "Remote read-back manifest or database checksum verification failed."
            ) from exc


def backup(job_id):
    env = repository_env()
    with TemporaryDirectory(prefix="itam-backup-") as temp:
        directory = Path(temp)
        manifest = dump_database(directory, job_id)
        output = run(
            [
                "restic",
                "backup",
                "--json",
                "--host",
                "itam-backup",
                "--tag",
                "itam",
                "database.dump",
                "manifest.json",
            ],
            cwd=directory,
            env=env,
        )
        try:
            summaries = [json.loads(line) for line in output.splitlines()]
            snapshot = next(
                row["snapshot_id"] for row in summaries if row.get("message_type") == "summary"
            )
        except (ValueError, KeyError, StopIteration) as exc:
            raise RunnerError("The repository did not return a completed snapshot.") from exc
        verify(snapshot, manifest, env)
        return snapshot, manifest


def retention(policy):
    if policy.retention_enabled:
        run(
            [
                "restic",
                "forget",
                "--tag",
                "itam",
                "--host",
                "itam-backup",
                "--group-by",
                "host",
                "--keep-daily",
                str(policy.keep_daily),
                "--keep-weekly",
                str(policy.keep_weekly),
                "--keep-monthly",
                str(policy.keep_monthly),
                "--prune",
            ],
            env=repository_env(),
        )
