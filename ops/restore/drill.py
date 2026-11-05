"""Restore a downloaded ITAM snapshot into an ephemeral, network-isolated PostgreSQL.

Run on an approved Docker operator host, never in the web/API container. No application,
workers, ports, production credentials or existing volumes are used. A JSON report can
be attached to an operator-attested drill record in Backups & Recovery.
"""

import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


def command(args):
    try:
        return subprocess.run(
            args, check=True, capture_output=True, timeout=7200
        ).stdout.decode()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Drill command failed; restricted command output withheld."
        ) from exc


def drill(directory, report):
    started = datetime.now(UTC)
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest must be a regular file.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("database_major", 16) != 16:
        raise ValueError("This isolated drill requires a PostgreSQL 16 backup.")
    dump = directory / "database.dump"
    if dump.is_symlink() or manifest.get("format") != "itam.backup.v1":
        raise ValueError("Invalid backup format or symlink.")
    with dump.open("rb") as stream:
        if (
            hashlib.file_digest(stream, "sha256").hexdigest()
            != manifest["database_sha256"]
        ):
            raise ValueError("Database checksum mismatch.")
    name = f"itam-drill-{uuid.uuid4().hex}"
    created = False
    result = {
        "backup_job": manifest["job_id"],
        "target_label": name,
        "started_at": started.isoformat(),
        "passed": False,
        "counts": {},
        "isolated": True,
        "outbound_disabled": True,
        "recovery_point": manifest.get("recovery_point"),
        "app_revision": manifest.get("app_revision"),
        "image_reference": manifest.get("image_reference"),
    }
    if result["recovery_point"]:
        point = datetime.fromisoformat(result["recovery_point"])
        result["recovery_point_age_seconds"] = (started - point).total_seconds()
    metadata_path = directory / "recovery-metadata.json"
    if metadata_path.is_file():
        result["synthetic_recovery"] = json.loads(metadata_path.read_text())
    try:
        command(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                "none",
                "--label",
                "itam.restore-drill=true",
                "--tmpfs",
                "/var/lib/postgresql/data",
                "--env",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "--env",
                "POSTGRES_USER=drill",
                "--env",
                "POSTGRES_DB=itam_drill",
                "postgres:16-bookworm",
            ]
        )
        created = True
        ready = False
        for _ in range(60):
            try:
                command(
                    [
                        "docker",
                        "exec",
                        name,
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        "drill",
                        "-d",
                        "itam_drill",
                    ]
                )
                ready = True
                break
            except RuntimeError:
                time.sleep(1)
        if not ready:
            raise RuntimeError("Isolated database did not become ready.")
        command(["docker", "cp", str(dump), f"{name}:/tmp/database.dump"])
        command(
            [
                "docker",
                "exec",
                name,
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "-U",
                "drill",
                "-d",
                "itam_drill",
                "/tmp/database.dump",
            ]
        )

        def sql(statement):
            return command(
                [
                    "docker",
                    "exec",
                    name,
                    "psql",
                    "--no-psqlrc",
                    "-U",
                    "drill",
                    "-d",
                    "itam_drill",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-Atc",
                    statement,
                ]
            ).strip()

        for table, count in manifest["counts"].items():
            if not re.fullmatch(r"[a-z][a-z0-9_]+", table):
                raise ValueError("Invalid manifest table name.")
            actual = int(sql(f'SELECT count(*) FROM "{table}"'))
            result["counts"][table] = actual
            if actual != count:
                raise ValueError(f"Restored count differs for {table}.")
        restored_migrations = sql(
            "SELECT app || ':' || name FROM django_migrations ORDER BY app,name"
        ).splitlines()
        if restored_migrations != [
            f"{app}:{migration}" for app, migration in manifest["migrations"]
        ]:
            raise ValueError("Restored migration history differs.")
        sql("UPDATE notifications_smtpprofile SET enabled=false")
        if "synthetic_recovery" in result:
            # Fixed queries for the known synthetic fixture, never operator-supplied SQL.
            checks = {
                "group_asset": "SELECT count(*) FROM groups_assetgroupmembership m "
                "JOIN groups_assetgroup g ON g.id=m.group_id "
                "JOIN assets_asset a ON a.id=m.asset_id",
                "installed_software": "SELECT count(*) FROM software_softwareinstallation i "
                "JOIN software_softwareversion v ON v.id=i.version_id "
                "JOIN software_softwareproduct p ON p.id=v.product_id "
                "JOIN assets_asset a ON a.id=i.asset_id",
                "lifecycle_evidence": "SELECT count(*) FROM lifecycle_lifecyclemilestone m "
                "JOIN lifecycle_lifecyclesource s ON s.id=m.source_id "
                "JOIN lifecycle_lifecycleproduct p ON p.id=m.product_id",
                "license_product": "SELECT count(*) FROM licensing_licenseentitlement e "
                "JOIN licensing_licenseproduct p ON p.id=e.product_id",
                "user_role": "SELECT count(*) FROM accounts_user_roles ur "
                "JOIN accounts_user u ON u.id=ur.user_id JOIN accounts_role r ON r.code=ur.role_id",
                "audit_continuity": "SELECT count(*) FROM audit_auditevent "
                "WHERE action='backups.drill_fixture'",
                "outbox_preserved": "SELECT count(*) FROM notifications_outboxmessage "
                "WHERE event_type='fixture'",
            }
            result["representative_relationships"] = {
                key: int(sql(query)) for key, query in checks.items()
            }
            if any(
                count != 1 for count in result["representative_relationships"].values()
            ):
                raise ValueError("Synthetic representative relationship check failed.")
        if "extensions" in manifest:
            extensions = dict(
                line.split(":", 1)
                for line in sql(
                    "SELECT extname || ':' || extversion FROM pg_extension ORDER BY extname"
                ).splitlines()
            )
            if extensions != manifest["extensions"]:
                raise ValueError("Restored PostgreSQL extensions differ.")
            result["extensions"] = extensions
        # No app/worker is started, and --network none also blocks any outbound action.
        result["passed"] = True
        result["notes"] = (
            "Network-isolated PostgreSQL restore: checksums, migration history and table counts "
            "verified. SMTP disabled. No application or workers started. Secret-key recovery "
            "and sample encrypted-file decryption remain operator checks."
        )
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        result["duration_seconds"] = (datetime.now(UTC) - started).total_seconds()
        if "synthetic_recovery" in result:
            retrieval = datetime.fromisoformat(
                result["synthetic_recovery"]["retrieval_started_at"]
            )
            result["retrieval_and_restore_seconds"] = (
                datetime.now(UTC) - retrieval
            ).total_seconds()
        # Refuse overwriting an existing report. The only removed container is the unique
        # one created by this invocation; its data is tmpfs, never a production volume.
        try:
            if created:
                command(["docker", "rm", "--force", name])
            result["target_removed"] = True
        except RuntimeError:
            result["target_removed"] = False
            result["passed"] = False
            raise
        finally:
            with report.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("Report path already exists; choose a new path.")
    drill(args.directory.resolve(strict=True), args.report)
