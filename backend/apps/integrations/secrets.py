"""Integration credential references (docs/02: credentials referenced through secrets,
not plaintext in the DB; docs/14: never in responses or logs).

Accepted references:
- ``env:ITAM_INTEGRATION_<NAME>`` — an environment variable injected by the deployment.
  The prefix is mandatory so a reference can never point at unrelated process secrets
  (e.g. DJANGO_SECRET_KEY) and send them to a configurable URL.
- ``file:<name>`` — a file directly inside ITAM_SECRETS_DIR (Docker/Compose secrets).
  No path separators or traversal.

Values are resolved only at call time and never returned by any API.
"""

import os
import re
from pathlib import Path

from django.conf import settings

ENV_PATTERN = re.compile(r"^ITAM_INTEGRATION_[A-Z0-9_]{1,60}$")
FILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
MAX_SECRET_BYTES = 8192


class SecretError(Exception):
    """Unresolvable reference. The message never contains a secret value."""


def validate_ref(ref: str) -> str:
    ref = ref.strip()
    if not ref:
        return ""
    kind, _, name = ref.partition(":")
    if kind == "env" and ENV_PATTERN.match(name):
        return ref
    if kind == "file" and FILE_PATTERN.match(name) and ".." not in name:
        return ref
    raise SecretError(
        "Use env:ITAM_INTEGRATION_<NAME> or file:<name> "
        "(a file in the deployment secrets directory)."
    )


def _secrets_dir() -> Path:
    return Path(getattr(settings, "ITAM_SECRETS_DIR", "/run/secrets")).resolve()


def resolve(ref: str) -> str:
    ref = validate_ref(ref)
    if not ref:
        raise SecretError("No credential reference is configured.")
    kind, _, name = ref.partition(":")
    if kind == "env":
        value = os.environ.get(name, "")
    else:
        base = _secrets_dir()
        path = (base / name).resolve()
        if path.parent != base:
            raise SecretError("Secret files must be directly inside the secrets directory.")
        if not path.is_file():
            raise SecretError(f"Secret file {name} was not found.")
        if path.stat().st_size > MAX_SECRET_BYTES:
            raise SecretError(f"Secret file {name} is too large.")
        value = path.read_text(encoding="utf-8")
    value = value.strip()
    if not value:
        raise SecretError(f"The referenced secret ({kind}:{name}) is empty or not set.")
    return value


def status(ref: str) -> str:
    """not_set | invalid | missing | configured — safe to show in the UI."""
    if not ref:
        return "not_set"
    try:
        resolve(ref)
    except SecretError as exc:
        return "invalid" if "Use env:" in str(exc) else "missing"
    return "configured"


def resolve_path(ref: str) -> str | None:
    """For CA bundles: a file reference resolved to a path (contents not read here)."""
    if not ref:
        return None
    ref = validate_ref(ref)
    kind, _, name = ref.partition(":")
    if kind != "file":
        raise SecretError("A CA bundle must be a file: reference.")
    path = (_secrets_dir() / name).resolve()
    if path.parent != _secrets_dir() or not path.is_file():
        raise SecretError(f"CA bundle {name} was not found in the secrets directory.")
    return str(path)
