"""Deployment contract for one enforced CSP on SPA, proxy and error responses."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = "include /etc/nginx/snippets/content-security-policy.conf;"


def test_policy_blocks_script_injection_external_connections_and_embedding():
    source = (ROOT / "frontend/content-security-policy.conf").read_text()
    matches = re.findall(r'add_header Content-Security-Policy "([^"]+)" always;', source)
    assert len(matches) == 1
    directives = {
        parts[0]: set(parts[1:]) for entry in matches[0].split(";") if (parts := entry.split())
    }
    for key in (
        "default-src",
        "script-src-attr",
        "frame-ancestors",
        "object-src",
        "base-uri",
        "worker-src",
    ):
        assert directives[key] == {"'none'"}
    for key in ("script-src", "connect-src", "font-src", "form-action", "frame-src"):
        assert directives[key] == {"'self'"}
    assert directives["style-src"] == {"'self'", "'unsafe-inline'"}
    assert directives["img-src"] == {"'self'", "data:"}
    assert "Content-Security-Policy-Report-Only" not in source
    assert "unsafe-eval" not in source and "$" not in source


def test_frontend_and_proxy_modes_use_same_policy_including_https_redirect():
    assert INCLUDE in (ROOT / "frontend/nginx.conf").read_text()
    assert (
        "COPY content-security-policy.conf /etc/nginx/snippets/"
        in (ROOT / "frontend/Dockerfile").read_text()
    )
    for mode, servers in (("http", 1), ("https", 2)):
        source = (ROOT / f"infra/nginx/{mode}.conf").read_text()
        assert source.count(INCLUDE) == servers
        assert "proxy_hide_header Content-Security-Policy;" in source


def test_proxy_policy_mount_is_read_only_and_points_to_canonical_file():
    compose = yaml.safe_load((ROOT / "infra/compose.prod.yaml").read_text())
    volumes = compose["services"]["nginx-proxy"]["volumes"]
    assert (
        "../frontend/content-security-policy.conf:/etc/nginx/snippets/content-security-policy.conf:ro"
        in volumes
    )
