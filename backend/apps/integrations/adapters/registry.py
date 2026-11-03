"""Connector registry. A source is synchronisable only if it is registered here.

Each connector provides a read-only client class, a connection test and an adapter
with ``prepare()``, ``collect(run, progress) -> (records, complete)`` and, when
``supports_evidence`` is set, ``collect_evidence()``.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Connector:
    code: str
    client_class: type
    auth_schemes: tuple[str, ...]
    default_auth_scheme: str
    supports_evidence: bool
    test_connection: Callable
    make_adapter: Callable


def _librenms() -> Connector:
    from .librenms import adapter
    from .librenms.client import LibreNMSClient

    return Connector(
        code="librenms",
        client_class=LibreNMSClient,
        auth_schemes=("bearer", "x_auth_token"),
        default_auth_scheme="bearer",
        supports_evidence=True,
        test_connection=adapter.test_connection,
        make_adapter=adapter.LibreNMSAdapter,
    )


def _endpoint_central() -> Connector:
    from .endpoint_central import adapter
    from .endpoint_central.client import EndpointCentralClient

    return Connector(
        code="endpoint_central",
        client_class=EndpointCentralClient,
        auth_schemes=("authorization", "bearer"),
        default_auth_scheme="authorization",
        supports_evidence=False,
        test_connection=adapter.test_connection,
        make_adapter=adapter.EndpointCentralAdapter,
    )


_FACTORIES = {"librenms": _librenms, "endpoint_central": _endpoint_central}
_CACHE: dict[str, Connector] = {}


def codes() -> set[str]:
    return set(_FACTORIES)


def get(code: str) -> Connector | None:
    if code not in _FACTORIES:
        return None
    if code not in _CACHE:
        _CACHE[code] = _FACTORIES[code]()
    return _CACHE[code]
