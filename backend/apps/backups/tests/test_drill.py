import hashlib
import json
import types
from pathlib import Path

import pytest


@pytest.fixture
def drill_module():
    script = Path(__file__).resolve().parents[4] / "ops" / "restore" / "drill.py"
    module = types.ModuleType("itam_restore_drill")
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), module.__dict__)
    return module


def files(directory):
    dump = b"fixture-pg-dump"
    (directory / "database.dump").write_bytes(dump)
    manifest = {
        "format": "itam.backup.v1",
        "job_id": "fixture",
        "database_sha256": hashlib.sha256(dump).hexdigest(),
        "counts": {"assets_asset": 1},
        "migrations": [["assets", "0001"]],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("image", ["postgres:16-bookworm", "itam-postgres:16.15"])
def test_drill_uses_only_new_network_isolated_container(drill_module, tmp_path, monkeypatch, image):
    files(tmp_path)
    commands = []

    def command(args):
        commands.append(args)
        if args[-2:] == ["postgres", "--version"]:
            return "postgres (PostgreSQL) 16.15"
        if "-Atc" in args:
            if "count(*)" in args[-1]:
                return "1"
            if "django_migrations" in args[-1]:
                return "assets:0001"
        return ""

    monkeypatch.setattr(drill_module, "command", command)
    report = tmp_path / "report.json"
    result = drill_module.drill(tmp_path, report, image=image)
    assert result["passed"] and result["isolated"] and result["outbound_disabled"]
    launch = commands[0]
    assert launch[-1] == image and result["restore_image"] == image
    assert launch[launch.index("--network") + 1] == "none"
    assert "--publish" not in launch and "--volume" not in launch
    assert launch[launch.index("--name") + 1].startswith("itam-drill-")
    assert commands[-1] == ["docker", "rm", "--force", result["target_label"]]
    assert json.loads(report.read_text())["passed"]


def test_failed_restore_records_failure_and_removes_only_created_target(
    drill_module, tmp_path, monkeypatch
):
    files(tmp_path)
    commands = []

    def command(args):
        commands.append(args)
        if args[-2:] == ["postgres", "--version"]:
            return "postgres (PostgreSQL) 16.15"
        if "pg_restore" in args:
            raise RuntimeError("Fixture restore failed")
        return ""

    monkeypatch.setattr(drill_module, "command", command)
    report = tmp_path / "failed.json"
    with pytest.raises(RuntimeError, match="Fixture"):
        drill_module.drill(tmp_path, report)
    result = json.loads(report.read_text())
    assert not result["passed"]
    assert commands[-1] == ["docker", "rm", "--force", result["target_label"]]


def test_cleanup_failure_still_preserves_failed_report(drill_module, tmp_path, monkeypatch):
    files(tmp_path)

    def command(args):
        if args[-2:] == ["postgres", "--version"]:
            return "postgres (PostgreSQL) 16.15"
        if "pg_restore" in args or "rm" in args:
            raise RuntimeError("Fixture failure")
        return ""

    monkeypatch.setattr(drill_module, "command", command)
    report = tmp_path / "cleanup.json"
    with pytest.raises(RuntimeError):
        drill_module.drill(tmp_path, report)
    result = json.loads(report.read_text())
    assert not result["passed"] and not result["target_removed"]


def test_incompatible_database_rejected_before_container_creation(
    drill_module, tmp_path, monkeypatch
):
    files(tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["database_major"] = 17
    path.write_text(json.dumps(manifest))
    commands = []
    monkeypatch.setattr(drill_module, "command", lambda args: commands.append(args))
    with pytest.raises(ValueError, match="PostgreSQL 16"):
        drill_module.drill(tmp_path, tmp_path / "report.json")
    assert not commands


def test_wrong_runtime_major_stops_before_restore_and_cleans_up(
    drill_module, tmp_path, monkeypatch
):
    files(tmp_path)
    commands = []

    def command(args):
        commands.append(args)
        return "postgres (PostgreSQL) 17.0" if args[-2:] == ["postgres", "--version"] else ""

    monkeypatch.setattr(drill_module, "command", command)
    report = tmp_path / "wrong-major.json"
    with pytest.raises(ValueError, match="PostgreSQL 16"):
        drill_module.drill(tmp_path, report, image="wrong-candidate:17")
    assert not any("pg_restore" in args or "cp" in args for args in commands)
    result = json.loads(report.read_text())
    assert not result["passed"] and result["target_removed"]
