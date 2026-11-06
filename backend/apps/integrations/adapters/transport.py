"""Direct HTTPS to validated IPs, retaining the approved Host and TLS hostname."""

import socket
import ssl

import httpx

from .base import UnsafeTarget, check_base_url, check_host_addresses


class PinnedTransport(httpx.BaseTransport):
    def __init__(self, base_url: str, *, verify: bool | str = True, resolver=None):
        self._origin = httpx.URL(check_base_url(base_url))
        self._resolver = resolver or socket.getaddrinfo
        self._addresses()  # Preserve early configuration refusal as well as per-request checks.
        # A private CA is explicit. Ambient proxy and CA environment variables are ignored.
        tls = ssl.create_default_context(cafile=verify) if isinstance(verify, str) else True
        self._transport = httpx.HTTPTransport(verify=tls, trust_env=False, retries=0)

    def _addresses(self) -> list[str]:
        return check_host_addresses(self._origin.host, self._resolver, self._origin.port or 443)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if (
            url.scheme != "https"
            or url.host != self._origin.host
            or (url.port or 443) != (self._origin.port or 443)
            or url.userinfo
            or url.fragment
        ):
            raise UnsafeTarget("The request is outside the approved HTTPS origin.")
        addresses = self._addresses()  # Validate every answer before sending any credentials.
        headers = request.headers.copy()
        headers["Host"] = self._origin.netloc.decode("ascii")
        for index, address in enumerate(addresses):
            pinned = httpx.Request(
                request.method,
                url.copy_with(host=address),
                headers=headers,
                stream=request.stream,
                extensions={**request.extensions, "sni_hostname": self._origin.host},
            )
            try:
                return self._transport.handle_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                # Only connection establishment may fail over: never replay a sent POST.
                if index == len(addresses) - 1:
                    raise
        raise AssertionError("Address validation must return at least one address")

    def close(self) -> None:
        self._transport.close()
