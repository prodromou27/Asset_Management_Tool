"""Refusal before connecting, including direct pytest bypass of the launcher."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("sqlite,host", [("1", "localhost"), ("", "example.invalid")])
def test_collection_refuses_unsupported_database(sqlite, host):
    env = dict(
        os.environ,
        DJANGO_SETTINGS_MODULE="config.settings.test",
        ITAM_RUN_REFERENCE_LOAD="1",
        POSTGRES_HOST=host,
    )
    env.pop("CI", None)
    env.pop("ITAM_TEST_DB_SQLITE", None)
    if sqlite:
        env["ITAM_TEST_DB_SQLITE"] = sqlite
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "../ops/load/test_reference_load.py",
            "-c",
            "pyproject.toml",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "Reference load requires explicit opt-in" in result.stdout + result.stderr
