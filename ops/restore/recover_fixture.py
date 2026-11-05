"""CI-only recovery from an encrypted synthetic repository after source destruction."""

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def recover(directory, key, target):
    started = datetime.now(UTC)
    metadata = json.loads((directory / "recovery.json").read_text())
    for field in (
        "synthetic_only",
        "source_database_removed",
        "storage_container_removed",
        "storage_volume_removed",
    ):
        if metadata.get(field) is not True:
            raise ValueError(
                "Original synthetic source removal must be confirmed first."
            )
    snapshot = metadata["snapshot_id"]
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot):
        raise ValueError("Invalid immutable snapshot ID.")
    env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
    env.update(
        RESTIC_REPOSITORY=str(directory / "repository"), RESTIC_PASSWORD_FILE=str(key)
    )
    for args in (
        ["check", "--read-data"],
        ["restore", snapshot, "--target", str(target)],
    ):
        subprocess.run(
            ["restic", *args], env=env, check=True, capture_output=True, timeout=7200
        )
    metadata.update(
        retrieval_started_at=started.isoformat(),
        retrieval_duration_seconds=(datetime.now(UTC) - started).total_seconds(),
    )
    (target / "recovery-metadata.json").write_text(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    recover(*(Path(value).resolve() for value in sys.argv[1:]))
