"""Launch only the synthetic reference test and finalize evidence after DB teardown."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "ops/load/results/report.json"


def main():
    REPORT.unlink(missing_ok=True)
    if os.environ.get("ITAM_TEST_DB_SQLITE") or os.environ.get("POSTGRES_HOST") not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        print("Reference load refused: unset SQLite and set a loopback POSTGRES_HOST.")
        return 1
    env = dict(
        os.environ, DJANGO_SETTINGS_MODULE="config.settings.test", ITAM_RUN_REFERENCE_LOAD="1"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "../ops/load/test_reference_load.py",
            "-c",
            "pyproject.toml",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT / "backend",
        env=env,
        check=False,
    )
    if not REPORT.exists():
        return result.returncode or 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    passed = result.returncode == 0 and report.get("status") == "measurements_passed"
    report["status"] = "passed" if passed else "failed"
    report["teardown_passed"] = result.returncode == 0
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "status": report["status"],
        "search_p95_seconds": {
            name: row["p95_seconds"] for name, row in report.get("search", {}).items()
        },
        "lifecycle": report.get("lifecycle"),
    }
    print(json.dumps(summary))
    print(
        f"Reference load {report['status']}; synthetic measurements: ops/load/results/report.json"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
