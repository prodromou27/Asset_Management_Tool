"""Static scans plus a bounded, network-disabled SQLite library proof; never scans hosts."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gate import evaluate

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.76.2"
TOOLS = os.environ.get("TRIVY_BIN", "trivy")


def run(args, **kwargs):
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=kwargs.pop("timeout", 1200),
        **kwargs,
    ).stdout


GO_BINARIES = {
    "backup-worker": {"usr/local/bin/restic": ("github.com/restic/restic", "stdlib")},
    "postgres": {"usr/local/bin/gosu": ("github.com/tianon/gosu", "stdlib")},
}


def sqlite_proof(image_id):
    name = "itam-sqlite-proof-" + uuid.uuid4().hex
    try:
        return json.loads(
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "10001:10001",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--memory",
                    "256m",
                    "--cpus",
                    "1",
                    "--pids-limit",
                    "32",
                    "--ulimit",
                    "fsize=1048576",
                    "--log-driver",
                    "none",
                    "--tmpfs",
                    "/scratch:rw,noexec,nosuid,size=16m,mode=1777",
                    "--entrypoint",
                    "/usr/bin/env",
                    image_id,
                    "-i",
                    "PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
                    "HOME=/scratch",
                    "TMPDIR=/scratch",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "python",
                    "-I",
                    "-B",
                    "/app/runtime/check_sqlite.py",
                ],
                timeout=30,
            )
        )
    finally:
        # Only this generated proof container is eligible for cleanup, including timeout paths.
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30)


def image_for(service, target, commit):
    if "build" not in service:
        image = service["image"]
        run(["docker", "pull", image])
        return image
    build = service["build"]
    image = f"itam-security-{target}:{commit[:12]}"
    args = ["docker", "build", "--pull=false", "-t", image]
    if build.get("target"):
        args += ["--target", build["target"]]
    if build.get("dockerfile"):
        args += ["-f", str(Path(build["context"]) / build["dockerfile"])]
    run(args + [build["context"]], cwd=ROOT)
    return image


def production_compose():
    return json.loads(
        run(
            [
                "docker",
                "compose",
                "--env-file",
                ".env",
                "-f",
                "infra/compose.yaml",
                "-f",
                "infra/compose.prod.yaml",
                "--profile",
                "backups",
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
        )
    )


def main(mode):
    output = ROOT / "ops/security/results" / mode
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    summary_path.unlink(missing_ok=True)
    summary = {
        "status": "running",
        "mode": mode,
        "started": datetime.now(UTC).isoformat(),
        "targets": {},
        "errors": {},
        "identities": {},
        "source_commit": run(["git", "rev-parse", "HEAD"], cwd=ROOT).strip(),
    }
    common = [
        "--config=",
        "--ignorefile=",
        "--cache-dir",
        str(output / "cache"),
        "--skip-version-check",
    ]
    try:
        if run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT).strip():
            raise ValueError(
                "Commit tracked source changes before generating release scan evidence"
            )
        run([TOOLS, "image", *common, "--download-db-only"])
        version = json.loads(
            run([TOOLS, "--cache-dir", str(output / "cache"), "--version", "--format", "json"])
        )
        if version.get("Version") != VERSION:
            raise ValueError("Scanner version differs from the reviewed pin")
        db = version.get("VulnerabilityDB", {})
        updated = datetime.fromisoformat(db["UpdatedAt"].replace("Z", "+00:00"))
        if not timedelta(0) <= datetime.now(UTC) - updated <= timedelta(hours=48):
            raise ValueError("Advisory database timestamp is missing, future or stale")
        summary["scanner"] = version
        targets = (
            ("backend", "frontend")
            if mode == "locks"
            else ("api", "backup-worker", "frontend", "nginx-proxy", "postgres", "redis")
        )
        compose = None
        if mode == "images":
            compose = production_compose()
        for target in targets:
            try:
                with tempfile.TemporaryDirectory(prefix=".scan-", dir=output) as scratch:
                    scratch = Path(scratch).resolve()
                    if not scratch.is_relative_to(output.resolve()):
                        raise ValueError("Scratch directory escaped the evidence root")
                    report_path = output / f"{target}.json"
                    report_path.unlink(missing_ok=True)
                    if mode == "images":
                        for suffix in ("sqlite", "upstream"):
                            (output / f"{target}-{suffix}.json").unlink(missing_ok=True)
                    metadata = {}
                    if mode == "locks":
                        files = (
                            ("uv.lock", "pyproject.toml")
                            if target == "backend"
                            else ("pnpm-lock.yaml", "package.json")
                        )
                        for name in files:
                            source = ROOT / target / name
                            shutil.copyfile(source, scratch / name)
                            metadata[name] = hashlib.sha256(source.read_bytes()).hexdigest()
                        scan_args = ["fs", "--offline-scan", "--include-dev-deps", str(scratch)]
                    else:
                        image = image_for(
                            compose["services"][target], target, summary["source_commit"]
                        )
                        inspected = json.loads(run(["docker", "image", "inspect", image]))[0]
                        metadata = {
                            key: inspected.get(key)
                            for key in ("Id", "RepoDigests", "Os", "Architecture")
                        }
                        metadata["reference"] = image
                        archive = scratch / "image.tar"
                        run(["docker", "image", "save", "--output", str(archive), inspected["Id"]])
                        scan_args = ["image", "--offline-scan", "--input", str(archive)]
                    summary["identities"][target] = metadata
                    run(
                        [
                            TOOLS,
                            *scan_args,
                            *common,
                            "--scanners",
                            "vuln",
                            "--list-all-pkgs",
                            "--report",
                            "all",
                            "--pkg-types",
                            "os,library",
                            "--skip-db-update",
                            "--skip-java-db-update",
                            "--ignore-unfixed=false",
                            "--severity",
                            "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL",
                            "--format",
                            "json",
                            "--output",
                            str(report_path),
                            "--exit-code",
                            "0",
                        ]
                    )
                    report = json.loads(report_path.read_text())
                    if mode == "locks":
                        checked = evaluate(
                            report,
                            required_type="uv" if target == "backend" else "pnpm",
                            required_packages=("django", "pytest")
                            if target == "backend"
                            else ("react", "vite", "undici"),
                        )
                    else:
                        checked = evaluate(
                            report,
                            image=True,
                            required_type="python-pkg"
                            if target in {"api", "backup-worker"}
                            else None,
                            required_packages=("django",)
                            if target in {"api", "backup-worker"}
                            else (),
                            required_os_versions={"sqlite-libs": "3.54.1-r0"}
                            if target in {"api", "backup-worker"}
                            else None,
                        )
                        if target in {"api", "backup-worker"}:
                            proof = sqlite_proof(metadata["Id"])
                            expected_source = json.loads(
                                (ROOT / "backend/runtime/sqlite/source.json").read_text()
                            )
                            expected_recipe = hashlib.sha256(
                                (ROOT / "backend/runtime/sqlite/APKBUILD").read_bytes()
                            ).hexdigest()
                            if (
                                proof.get("passed") is not True
                                or proof.get("source") != expected_source
                                or proof.get("recipe_sha256") != expected_recipe
                            ):
                                raise ValueError(
                                    "SQLite runtime proof does not match reviewed provenance"
                                )
                            proof.update(
                                image_id=metadata["Id"], source_commit=summary["source_commit"]
                            )
                            (output / f"{target}-sqlite.json").write_text(
                                json.dumps(proof, indent=2)
                            )
                            checked["sqlite_proof"] = proof
                        if target in GO_BINARIES:
                            upstream_path = output / f"{target}-upstream.json"
                            upstream_path.unlink(missing_ok=True)
                            run(
                                [
                                    TOOLS,
                                    "image",
                                    "--offline-scan",
                                    "--input",
                                    str(archive),
                                    *common,
                                    "--scanners",
                                    "vuln",
                                    "--list-all-pkgs",
                                    "--report",
                                    "all",
                                    "--pkg-types",
                                    "library",
                                    "--detection-priority",
                                    "comprehensive",
                                    "--skip-db-update",
                                    "--skip-java-db-update",
                                    "--ignore-unfixed=false",
                                    "--severity",
                                    "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL",
                                    "--format",
                                    "json",
                                    "--output",
                                    str(upstream_path),
                                    "--exit-code",
                                    "0",
                                ]
                            )
                            upstream = evaluate(
                                json.loads(upstream_path.read_text()),
                                required_type="gobinary",
                                required_binaries=GO_BINARIES[target],
                            )
                            checked["upstream"] = upstream
                            print(
                                f"{target} upstream: {upstream['status']}; {upstream['counts']}",
                                flush=True,
                            )
                            if upstream["status"] != "passed":
                                checked["status"] = "held"
                    summary["targets"][target] = {**checked, "identity": metadata}
                    print(f"{target}: {checked['status']}; {checked['counts']}", flush=True)
            except Exception as exc:
                summary["errors"][target] = f"{type(exc).__name__}: {exc}"
        summary["status"] = (
            "passed"
            if not summary["errors"]
            and len(summary["targets"]) == len(targets)
            and all(item["status"] == "passed" for item in summary["targets"].values())
            else "held"
        )
    except Exception as exc:
        summary["status"] = "failed"
        summary["errors"]["setup"] = f"{type(exc).__name__}: {exc}"
    summary["finished"] = datetime.now(UTC).isoformat()
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"Security {mode}: {summary['status']}; {len(summary['errors'])} evidence errors",
        flush=True,
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("locks", "images"))
    raise SystemExit(main(parser.parse_args().mode))
