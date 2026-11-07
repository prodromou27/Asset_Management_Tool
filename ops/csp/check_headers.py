"""Observe real Nginx headers on an internal-only Docker fixture network."""

import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


policy = re.search(
    r'add_header Content-Security-Policy "([^"]+)" always;',
    Path("/fixture/policy.conf").read_text(),
).group(1)
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile="/fixture/ca.pem")),
    NoRedirect(),
)


def get(url):
    try:
        return opener.open(url, timeout=5)
    except urllib.error.HTTPError as response:
        return response


checks = 0
for base in ("http://frontend", "http://proxy-http", "https://proxy-https"):
    for attempt in range(40):
        try:
            with get(base + "/") as response:
                assert response.status == 200
            break
        except (OSError, AssertionError):
            if attempt == 39:
                raise
            time.sleep(0.2)
    paths = [("/", 200), ("/assets/example", 200)]
    paths += [
        ("/api/v1/auth/entra/callback/?code=synthetic-oidc-value&state=synthetic-oidc-value", 404)
    ]
    if base != "http://frontend":
        paths += [(f"/api/v1/status/{code}", code) for code in (200, 401, 403, 404, 500)]
        paths += [("/api/v1/broken", 502)]
    for path, code in paths:
        with get(base + path) as response:
            assert response.status == code, (base, path, response.status)
            assert response.headers.get_all("Content-Security-Policy") == [policy], (base, path)
        checks += 1

with get("http://proxy-https/assets") as response:
    assert response.status == 301
    assert response.headers["Location"] == "https://proxy-https/assets"
    assert response.headers.get_all("Content-Security-Policy") == [policy]
checks += 1
print(f"CSP Nginx proof passed: {checks} static, SPA, API, proxy-error and redirect responses")
