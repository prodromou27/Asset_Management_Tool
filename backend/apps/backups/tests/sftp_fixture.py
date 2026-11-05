"""Disposable synthetic SFTP destination, with keys generated for this test only."""

import json
import os
import secrets
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def command(args):
    return (
        subprocess.run(args, check=True, capture_output=True, timeout=300).stdout.decode().strip()
    )


@contextmanager
def destination(directory):
    name = "itam-backup-test-" + uuid.uuid4().hex
    keys = directory / "server-keys"
    client = directory / "client-keys"
    keys.mkdir(mode=0o755)
    client.mkdir(mode=0o700)
    command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "host_key")])
    command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(client / "restic_ssh_key")])
    (keys / "authorized_keys").write_text((client / "restic_ssh_key.pub").read_text())
    (keys / "authorized_keys").chmod(0o644)
    (client / "restic_password").write_text(secrets.token_urlsafe(48))
    root = Path(__file__).resolve().parents[4]
    command(["docker", "build", "-t", "itam-sftp-fixture", str(root / "infra/backup-test")])
    command(["docker", "volume", "create", name])
    created = False
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                "127.0.0.1::22",
                "--mount",
                f"type=volume,source={name},target=/repository",
                "--mount",
                f"type=bind,source={keys},target=/run/fixture-keys,readonly",
                "itam-sftp-fixture",
            ]
        )
        created = True
        port = command(["docker", "port", name, "22/tcp"]).rsplit(":", 1)[1]
        public = (keys / "host_key.pub").read_text().split()
        (client / "restic_known_hosts").write_text(f"[127.0.0.1]:{port} {public[0]} {public[1]}\n")
        # Never trust ssh-keyscan: the pin comes directly from our generated server key.
        for _ in range(30):
            try:
                command(["docker", "exec", name, "test", "-f", "/run/sshd/sshd.pid"])
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError("Synthetic SFTP fixture did not become ready.")
        yield {
            "ITAM_TEST_SFTP_REPOSITORY": f"sftp://backup@127.0.0.1:{port}//repository",
            "ITAM_TEST_SFTP_SECRETS": str(client),
        }
        if output := os.environ.get("ITAM_BACKUP_DRILL_ARTIFACT_DIR"):
            artifact = Path(output)
            artifact.mkdir(parents=True, exist_ok=True)
            command(["docker", "cp", f"{name}:/repository", str(artifact / "repository")])
            key_artifact = artifact.with_name("itam-drill-key")
            key_artifact.mkdir(mode=0o700, exist_ok=True)
            (key_artifact / "restic_password").write_bytes(
                (client / "restic_password").read_bytes()
            )
    finally:
        if created:
            command(["docker", "rm", "--force", name])
        command(["docker", "volume", "rm", name])
    if output := os.environ.get("ITAM_BACKUP_DRILL_ARTIFACT_DIR"):
        artifact = Path(output)
        metadata = json.loads((artifact / "recovery.json").read_text())
        metadata.update(
            source_database_removed=True,
            storage_container_removed=True,
            storage_volume_removed=True,
            synthetic_only=True,
        )
        (artifact / "recovery.json").write_text(json.dumps(metadata, indent=2))
