from pathlib import Path

import yaml


def test_backup_worker_receives_no_unrelated_connector_or_mail_secrets():
    root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((root / "infra" / "compose.yaml").read_text(encoding="utf-8"))
    worker = compose["services"]["backup-worker"]
    env = worker["environment"]
    assert not any(name.startswith("ITAM_INTEGRATION_") for name in env)
    assert "ITAM_SMTP_PASSWORD" not in env and "ITAM_IMPORT_ENCRYPTION_KEY" not in env
    assert env["ITAM_ALLOW_LIVE_INTEGRATIONS"] == "false"
    assert worker["profiles"] == ["backups"] and worker["read_only"]
