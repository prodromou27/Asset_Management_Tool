"""Connector registry. A source is synchronisable only if it is registered here.

Each connector provides a read-only client class, a connection test and an adapter
with ``prepare()``, ``collect(run, progress) -> (records, complete)`` and, when
``supports_evidence`` is set, ``collect_evidence()``.

Cloud connectors with a fixed endpoint set ``fixed_base_url`` and build their client
through ``client_factory(instance, secret, **http_options)``; ``required_settings`` names
instance fields that must be filled before any request.
"""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Connector:
    code: str
    client_class: type
    auth_schemes: tuple[str, ...]
    default_auth_scheme: str
    supports_evidence: bool
    test_connection: Callable
    make_adapter: Callable
    client_factory: Callable | None = None
    fixed_base_url: str | None = None
    required_settings: tuple[str, ...] = ()
    # Application permissions/roles the source account needs (shown to administrators).
    permissions: tuple[str, ...] = ()
    # Instance settings that apply to this connector (others are hidden in the UI).
    uses_source_timezone: bool = True
    uses_detail_refresh: bool = True
    # Defaults applied when an integration of this source is created.
    defaults: dict = field(default_factory=dict)
    # Optional: store source facts kept apart from asset fields (e.g. security state),
    # called after reconciliation as store_facts(instance, run, records, complete).
    store_facts: Callable | None = None


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


def _microsoft_client_factory(client_class, scope: str, user_agent: str) -> Callable:
    """Entra client-credentials token provider + read-only client for one Microsoft API."""

    def factory(
        instance, secret, *, verify, timeout, max_retries, transport, sleep=None, **options
    ):
        from .entra import TokenProvider, make_credential

        extra = {"sleep": sleep} if sleep else {}
        tokens = TokenProvider(
            instance.tenant_id,
            instance.client_id,
            make_credential(instance.auth_scheme, secret),
            scope=scope,
            user_agent=user_agent,
            timeout=timeout,
            max_retries=max_retries,
            verify=verify,
            transport=transport,
            **extra,
        )
        return client_class(
            tokens,
            verify=verify,
            timeout=timeout,
            max_retries=max_retries,
            transport=transport,
            **extra,
            **options,
        )

    return factory


def _intune() -> Connector:
    from .entra import GRAPH_SCOPE
    from .intune import adapter
    from .intune.client import GRAPH_BASE, REQUIRED_PERMISSION, GraphClient

    return Connector(
        code="intune",
        client_class=GraphClient,
        auth_schemes=("client_certificate", "client_secret"),
        default_auth_scheme="client_certificate",
        supports_evidence=False,
        test_connection=adapter.test_connection,
        make_adapter=adapter.IntuneAdapter,
        client_factory=_microsoft_client_factory(
            GraphClient, GRAPH_SCOPE, "ITAM-Intune-Connector/1"
        ),
        fixed_base_url=GRAPH_BASE,
        required_settings=("tenant_id", "client_id"),
        permissions=(REQUIRED_PERMISSION,),
        uses_source_timezone=False,
        uses_detail_refresh=False,
        # docs/05: Intune daily. Laptops are often offline for days; a week before a
        # device that stopped checking in is reported stale.
        defaults={"sync_interval_minutes": 1440, "stale_after_hours": 168},
    )


def _defender() -> Connector:
    from .defender import adapter
    from .defender.client import API_BASE, REQUIRED_PERMISSION, DefenderClient
    from .entra import DEFENDER_SCOPE

    return Connector(
        code="defender",
        client_class=DefenderClient,
        # Certificate only: the task requires a certificate credential for Defender.
        auth_schemes=("client_certificate",),
        default_auth_scheme="client_certificate",
        supports_evidence=False,
        test_connection=adapter.test_connection,
        make_adapter=adapter.DefenderAdapter,
        client_factory=_microsoft_client_factory(
            DefenderClient, DEFENDER_SCOPE, "ITAM-Defender-Connector/1"
        ),
        fixed_base_url=API_BASE,
        required_settings=("tenant_id", "client_id"),
        permissions=(REQUIRED_PERMISSION,),
        uses_source_timezone=False,
        uses_detail_refresh=False,
        store_facts=adapter.store_security_states,
        # docs/05: Defender daily. Published limit: 100 calls/minute, 1500/hour.
        defaults={
            "sync_interval_minutes": 1440,
            "stale_after_hours": 168,
            "requests_per_second": 1,
        },
    )


_FACTORIES = {
    "librenms": _librenms,
    "endpoint_central": _endpoint_central,
    "intune": _intune,
    "defender": _defender,
}
_CACHE: dict[str, Connector] = {}


def codes() -> set[str]:
    return set(_FACTORIES)


def get(code: str) -> Connector | None:
    if code not in _FACTORIES:
        return None
    if code not in _CACHE:
        _CACHE[code] = _FACTORIES[code]()
    return _CACHE[code]
