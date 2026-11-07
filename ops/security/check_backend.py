"""Exercise candidate runtime against disposable internal-only PostgreSQL/Redis/SFTP."""

import io
import os
import secrets
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def command(args, *, stream=False):
    result = subprocess.run(
        args, check=True, capture_output=not stream, text=True, timeout=1200, cwd=ROOT
    )
    return result.stdout.strip() if result.stdout else ""


def wait_for(args):
    for _ in range(40):
        try:
            command(args)
            return
        except subprocess.CalledProcessError:
            time.sleep(1)
    raise RuntimeError("Synthetic runtime service did not become ready")


def main():
    prefix = "itam-backend-proof-" + uuid.uuid4().hex
    pg, redis, sftp, client = (prefix + suffix for suffix in ("-pg", "-redis", "-sftp", "-client"))
    output = ROOT / "ops/security/results"
    output.mkdir(parents=True, exist_ok=True)
    containers = []
    network_created = False
    with tempfile.TemporaryDirectory(prefix=".runtime-", dir=output) as scratch:
        directory = Path(scratch).resolve()
        if not directory.is_relative_to(output.resolve()):
            raise ValueError("Runtime scratch escaped the evidence root")
        keys = directory / "keys"
        keys.mkdir(mode=0o700)
        for filename in ("host_key", "restic_ssh_key"):
            command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / filename)])
        (keys / "authorized_keys").write_bytes((keys / "restic_ssh_key.pub").read_bytes())
        public = (keys / "host_key.pub").read_text().split()
        (keys / "restic_known_hosts").write_text(f"{sftp} {public[0]} {public[1]}\n")
        (keys / "restic_password").write_text(secrets.token_urlsafe(48))
        env = directory / "fixture.env"
        env.write_text(
            "CI=true\nDJANGO_SETTINGS_MODULE=config.settings.test\n"
            "DJANGO_SECRET_KEY=" + secrets.token_urlsafe(64) + "\n"
            "POSTGRES_DB=itam\nPOSTGRES_USER=itam\nPOSTGRES_PASSWORD="
            + secrets.token_urlsafe(32)
            + f"\nPOSTGRES_HOST={pg}\nPOSTGRES_PORT=5432\nREDIS_URL=redis://{redis}:6379/0\n"
            + f"ITAM_TEST_SFTP_REPOSITORY=sftp://itamfixture@{sftp}//repository\n"
            + "ITAM_TEST_SFTP_SECRETS=/tmp/itam-secrets\n"
        )
        os.chmod(env, 0o600)
        try:
            command(["docker", "network", "create", "--internal", prefix])
            network_created = True

            def start(name, image, extras=(), args=()):
                containers.append(name)
                command(
                    ["docker", "run", "--detach", "--name", name, "--network", prefix]
                    + list(extras)
                    + [image]
                    + list(args)
                )

            start(
                pg,
                "itam-postgres:16.15",
                ["--env-file", str(env), "--tmpfs", "/var/lib/postgresql/data"],
            )
            start(
                redis,
                "itam-redis:7.4.12",
                args=["redis-server", "--save", "", "--appendonly", "no"],
            )
            start(
                sftp,
                "itam-sftp-fixture",
                ["--mount", f"type=bind,source={keys},target=/run/fixture-keys,readonly"],
            )
            wait_for(["docker", "exec", pg, "pg_isready", "-h", "127.0.0.1", "-U", "itam"])
            wait_for(["docker", "exec", redis, "redis-cli", "ping"])
            wait_for(["docker", "exec", sftp, "test", "-f", "/run/sshd/sshd.pid"])
            sources = []
            for relative in (
                "ops/restore/drill.py",
                "infra/compose.yaml",
                "infra/compose.prod.yaml",
                "infra/nginx/http.conf",
                "infra/nginx/https.conf",
                "frontend/Dockerfile",
                "frontend/nginx.conf",
                "frontend/content-security-policy.conf",
            ):
                sources += [
                    "--mount",
                    f"type=bind,source={ROOT / relative},target=/{relative},readonly",
                ]
            start(
                client,
                "itam-runtime-tests",
                [
                    "--env-file",
                    str(env),
                    "--read-only",
                    "--tmpfs",
                    "/tmp:mode=1777",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                ]
                + sources,
                ["tail", "-f", "/dev/null"],
            )
            # Extract only client files as the nonroot image user; no Docker socket/root exec.
            with io.BytesIO() as archive:
                with tarfile.open(fileobj=archive, mode="w") as tar:
                    for filename in (
                        "restic_ssh_key",
                        "restic_ssh_key.pub",
                        "restic_known_hosts",
                        "restic_password",
                    ):
                        tar.add(keys / filename, arcname=filename)
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        client,
                        "sh",
                        "-c",
                        "mkdir -m 700 /tmp/itam-secrets && tar -xf - -C /tmp/itam-secrets",
                    ],
                    input=archive.getvalue(),
                    capture_output=True,
                    check=True,
                    timeout=30,
                )
            command(
                [
                    "docker",
                    "exec",
                    client,
                    "python",
                    "-m",
                    "pytest",
                    "-q",
                    "-rs",
                    "-p",
                    "no:cacheprovider",
                ],
                stream=True,
            )
            print(
                "Candidate backend PostgreSQL/Redis/SFTP suite passed on an internal-only network."
            )
        finally:
            cleanup_failed = False
            for name in reversed(containers):
                result = subprocess.run(
                    ["docker", "rm", "--force", "--volumes", name], capture_output=True
                )
                cleanup_failed |= result.returncode != 0
            if network_created:
                result = subprocess.run(["docker", "network", "rm", prefix], capture_output=True)
                cleanup_failed |= result.returncode != 0
            if cleanup_failed:
                raise RuntimeError(
                    "Disposable runtime cleanup failed; inspect only the generated resource prefix"
                )


if __name__ == "__main__":
    main()
