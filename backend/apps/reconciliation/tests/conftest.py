import pytest

from apps.assets.tests.fixtures import grant  # noqa: F401 - re-exported for tests
from apps.integrations.models import DiscoverySource, IntegrationInstance
from apps.reconciliation import services

T0 = "2026-11-02T08:00:00+00:00"


def make_instance(name, source="fixture", site=None, **extra):
    return IntegrationInstance.objects.create(
        name=name, source=DiscoverySource.objects.get(code=source), default_site=site, **extra
    )


@pytest.fixture
def nms(hq):
    return make_instance("NMS HQ", "fixture", hq)


@pytest.fixture
def nms_branch(branch):
    return make_instance("NMS Branch", "fixture", branch)


@pytest.fixture
def ec(hq):
    return make_instance("Endpoint Central", "endpoint_central", hq)


@pytest.fixture
def intune(hq):
    return make_instance("Intune", "intune", hq)


@pytest.fixture
def defender(hq):
    return make_instance("Defender", "defender", hq)


def switch_record(external_id="317", **overrides):
    record = {
        "external_id": external_id,
        "observed_at": T0,
        "manufacturer": "Cisco Systems, Inc.",
        "model": "C9300-48T",
        "serial": "FOC2233X0AB",
        "hostname": "SW-CORE-01.corp.example",
        "interfaces": [{"name": "Vlan10", "mac": "0200.0000.0001", "ips": ["10.10.0.2"]}],
        "os_name": "IOS XE",
        "os_version": "17.9.4",
        "firmware_version": "17.9.4",
        "device_type": "switch",
    }
    record.update(overrides)
    return record


def laptop_record(external_id, **overrides):
    record = {
        "external_id": external_id,
        "observed_at": T0,
        "manufacturer": "Dell Inc.",
        "model": "Latitude 7440",
        "serial": "7XK2Q93",
        "hostname": "LT-0042",
        "hardware_uuid": "4c4c4544-0058-4b10-8032-b7c04f513933",
        "interfaces": [{"name": "Wi-Fi", "mac": "02:00:00:00:10:42"}],
        "os_name": "Windows 11 Enterprise",
        "os_version": "23H2",
        "device_type": "laptop",
    }
    record.update(overrides)
    return record


def ingest(instance, *records, mode="incremental"):
    return services.ingest(instance, list(records), mode=mode, triggered_by="test")


class Req:
    """Minimal request for calling services directly."""

    def __init__(self, user):
        self.user = user
        self.META = {"REMOTE_ADDR": "127.0.0.1"}
