"""Microsoft Entra OAuth 2.0 client-credentials tokens (shared by the Microsoft connectors).

The application authenticates as itself (application permissions, no user). The only
non-GET request a Microsoft connector makes is this token request: a form POST to the
fixed Entra token endpoint ``https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token``.
The resource APIs only ever receive GET (adapters/http.py).

Each connector passes the documented scope of its own API: Microsoft Graph
(``https://graph.microsoft.com/.default``) for Intune, the Defender for Endpoint API
(``https://api.securitycenter.microsoft.com/.default``) for Defender.

Credentials, in order of preference:
- ``client_certificate``: a PEM holding the unencrypted RSA private key and the
  certificate uploaded to the app registration. A short-lived RS256 client assertion is
  signed per token request; the key never leaves the process.
- ``client_secret``: the app registration's client secret value.

Neither the secret, the key, the assertion nor the access token is logged or returned by
any API. Error messages carry only the Entra error code and its first sentence.
"""

import base64
import hashlib
import json
import logging
import random
import re
import time
import uuid

import httpx

from .base import AuthError, SourceError, Unavailable

logger = logging.getLogger(__name__)

LOGIN_HOST = "login.microsoftonline.com"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
DEFENDER_SCOPE = "https://api.securitycenter.microsoft.com/.default"
REFRESH_MARGIN = 300  # seconds before expiry at which a cached token is renewed
ASSERTION_LIFETIME = 600
MAX_RETRY_AFTER = 120

GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TENANT_DOMAIN = re.compile(r"^(?=.{4,100}$)([a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,63}$")
_PEM_BLOCK = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----\s.*?-----END \1-----", re.DOTALL)

# Module-level clock so tests can move time forward.
now = time.time


def valid_tenant(value: str) -> bool:
    """A directory (tenant) ID GUID or a verified domain such as contoso.onmicrosoft.com.
    "common"/"organizations" are refused: client credentials need one tenant."""
    return bool(GUID.match(value) or TENANT_DOMAIN.match(value))


def valid_client_id(value: str) -> bool:
    return bool(GUID.match(value))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def token_claims(token: str) -> dict:
    """Unverified payload of a JWT access token (used only to report granted roles)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}


class ClientSecretCredential:
    kind = "client_secret"

    def __init__(self, secret: str):
        if not secret:
            raise AuthError("The client secret is empty.")
        self._secret = secret

    def __repr__(self):
        return "ClientSecretCredential(***)"

    def form(self, client_id: str, audience: str) -> dict:
        return {"client_secret": self._secret}


class ClientCertificateCredential:
    """RSA private key + X.509 certificate from one PEM document."""

    kind = "client_certificate"

    def __init__(self, pem: str):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        blocks = {m.group(1): m.group(0) for m in _PEM_BLOCK.finditer(pem)}
        key_pem = next((v for k, v in blocks.items() if k.endswith("PRIVATE KEY")), None)
        cert_pem = blocks.get("CERTIFICATE")
        if key_pem is None or cert_pem is None:
            raise AuthError(
                "The certificate reference must contain both the private key and the "
                "certificate in PEM format."
            )
        if "ENCRYPTED" in key_pem.split("\n", 1)[0]:
            raise AuthError(
                "Encrypted private keys are not supported; protect the file with the "
                "deployment secrets store instead."
            )
        try:
            key = serialization.load_pem_private_key(key_pem.encode(), password=None)
            cert = x509.load_pem_x509_certificate(cert_pem.encode())
        except (ValueError, TypeError) as exc:
            raise AuthError("The private key or certificate could not be read.") from exc
        if not isinstance(key, rsa.RSAPrivateKey):
            raise AuthError("Only RSA certificates are supported for Entra client assertions.")
        if cert.public_key().public_numbers() != key.public_key().public_numbers():
            raise AuthError("The certificate does not belong to the private key.")
        der = cert.public_bytes(serialization.Encoding.DER)
        self._key = key
        self._hashes = hashes
        self.thumbprint_sha256 = _b64url(hashlib.sha256(der).digest())
        self.thumbprint_sha1 = _b64url(hashlib.sha1(der).digest())  # noqa: S324 - x5t header
        self.not_after = cert.not_valid_after_utc

    def __repr__(self):
        return "ClientCertificateCredential(***)"

    def form(self, client_id: str, audience: str) -> dict:
        from cryptography.hazmat.primitives.asymmetric import padding

        issued = int(now())
        header = {
            "alg": "RS256",
            "typ": "JWT",
            "x5t": self.thumbprint_sha1,
            "x5t#S256": self.thumbprint_sha256,
        }
        claims = {
            "aud": audience,
            "iss": client_id,
            "sub": client_id,
            "jti": str(uuid.uuid4()),
            "nbf": issued,
            "iat": issued,
            "exp": issued + ASSERTION_LIFETIME,
        }
        signing_input = ".".join(
            _b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
        )
        signature = self._key.sign(
            signing_input.encode(), padding.PKCS1v15(), self._hashes.SHA256()
        )
        return {
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": f"{signing_input}.{_b64url(signature)}",
        }


def make_credential(kind: str, secret: str):
    if kind == "client_certificate":
        return ClientCertificateCredential(secret)
    if kind == "client_secret":
        return ClientSecretCredential(secret)
    raise AuthError("Choose a client secret or a client certificate credential.")


class TokenProvider:
    """Caches one access token for one scope and renews it shortly before it expires."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        credential,
        *,
        scope: str = GRAPH_SCOPE,
        user_agent: str = "ITAM-Entra-Connector/1",
        timeout: float = 30,
        max_retries: int = 3,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        if not valid_tenant(tenant_id):
            raise AuthError("The tenant ID must be the directory ID (GUID) or a verified domain.")
        if not valid_client_id(client_id):
            raise AuthError("The application (client) ID must be a GUID.")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.endpoint = f"https://{LOGIN_HOST}/{tenant_id}/oauth2/v2.0/token"
        if scope not in (GRAPH_SCOPE, DEFENDER_SCOPE):
            raise ValueError(f"Unsupported token scope {scope!r}")
        self.scope = scope
        self._credential = credential
        self._max_retries = max_retries
        self._sleep = sleep
        self._token: str | None = None
        self._expires_at = 0.0
        self.requests = 0
        self.roles: list[str] | None = None
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            verify=verify if verify is not False else True,
            follow_redirects=False,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": user_agent},
        )

    def __repr__(self):
        return (
            f"TokenProvider(tenant={self.tenant_id!r}, client={self.client_id!r}, "
            f"scope={self.scope!r})"
        )

    def close(self) -> None:
        self._client.close()

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0

    def token(self) -> str:
        if self._token is None or now() >= self._expires_at - REFRESH_MARGIN:
            self._acquire()
        assert self._token is not None
        return self._token

    def _acquire(self) -> None:
        attempt = 0
        while True:
            form = {
                "client_id": self.client_id,
                "scope": self.scope,
                "grant_type": "client_credentials",
                **self._credential.form(self.client_id, self.endpoint),
            }
            self.requests += 1
            try:
                response = self._client.post(self.endpoint, data=form)
            except httpx.TransportError as exc:
                error: SourceError = Unavailable(
                    f"Cannot reach Microsoft Entra ID ({type(exc).__name__})."
                )
                delay = None
            else:
                if response.status_code == 200:
                    self._accept(response)
                    return
                error = self._error(response)
                delay = self._retry_after(response) if "Retry-After" in response.headers else None
            if error.retryable and attempt < self._max_retries:
                attempt += 1
                if delay is None:
                    delay = min(2 ** (attempt - 1), 30) + random.uniform(0, 0.5)  # noqa: S311
                logger.info("Token request failed (%s); retry %d", error.code, attempt)
                self._sleep(delay)
                continue
            raise error

    def _accept(self, response: httpx.Response) -> None:
        try:
            body = response.json()
            token = str(body["access_token"])
            lifetime = int(body.get("expires_in", 3599))
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError("Microsoft Entra ID returned an unreadable token response.") from exc
        if not token:
            raise SourceError("Microsoft Entra ID returned an empty access token.")
        self._token = token
        self._expires_at = now() + max(lifetime, 60)
        roles = token_claims(token).get("roles")
        self.roles = [str(r) for r in roles] if isinstance(roles, list) else None

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        try:
            return min(float(response.headers.get("Retry-After", "5")), MAX_RETRY_AFTER)
        except ValueError:
            return 5.0

    @staticmethod
    def _error(response: httpx.Response) -> SourceError:
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        code = str(body.get("error") or "")[:40]
        description = str(body.get("error_description") or "")
        # "AADSTS7000215: Invalid client secret provided. ... Trace ID: ..." → first sentence.
        first = description.split("\r\n")[0].split("\n")[0]
        first = re.split(r"(?<=\.)\s", first, maxsplit=1)[0][:200]
        detail = f"{code}: {first}" if first else code or f"HTTP {status}"
        if status == 429:
            return Unavailable(f"Microsoft Entra ID throttled the token request ({detail}).")
        if status >= 500:
            return Unavailable(f"Microsoft Entra ID error (HTTP {status}).")
        return AuthError(
            f"Microsoft Entra ID refused the token request ({detail}). Check the tenant ID, "
            "application ID, credential and admin consent."
        )
