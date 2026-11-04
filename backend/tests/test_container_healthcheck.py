"""The api container healthcheck (infra/compose.yaml) must pass under production settings.

It calls gunicorn directly, bypassing nginx, so it sends the first allowed host and the
proxy's ``X-Forwarded-Proto: https`` marker. Without them the check fails on host
validation or on the HTTPS redirect and nginx-proxy never starts.
"""

from pathlib import Path

import yaml
from django.test import override_settings

PRODUCTION_LIKE = {
    "ALLOWED_HOSTS": ["10.20.30.40", "itam-stg"],
    "SECURE_SSL_REDIRECT": True,
    "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
}
LIVE = "/api/v1/health/live/"


@override_settings(**PRODUCTION_LIKE)
def test_healthcheck_request_passes_host_validation_and_https_redirect(client):
    response = client.get(LIVE, HTTP_HOST="10.20.30.40", HTTP_X_FORWARDED_PROTO="https")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@override_settings(**PRODUCTION_LIKE)
def test_plain_http_without_proxy_marker_is_redirected(client):
    response = client.get(LIVE, HTTP_HOST="10.20.30.40")

    assert response.status_code == 301
    assert response["Location"].startswith("https://10.20.30.40/")


@override_settings(**PRODUCTION_LIKE)
def test_unlisted_host_is_refused(client):
    response = client.get(LIVE, HTTP_HOST="localhost", HTTP_X_FORWARDED_PROTO="https")

    assert response.status_code == 400


def test_compose_healthcheck_sends_first_allowed_host_and_https_marker():
    compose = Path(__file__).resolve().parents[2] / "infra" / "compose.yaml"
    command = yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]["api"]["healthcheck"][
        "test"
    ][-1]

    assert "ITAM_ALLOWED_HOSTS'].split(',')[0].strip()" in command
    assert "'X-Forwarded-Proto': 'https'" in command
    assert "/api/v1/health/live/" in command
