import pytest

from apps.observations.normalize import (
    RecordError,
    checksum,
    normalize_manufacturer,
    normalize_record,
    normalize_serial,
    normalize_uuid,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Cisco Systems, Inc.", "Cisco"),
        ("Dell Inc.", "Dell"),
        ("LENOVO", "Lenovo"),
        ("Hewlett-Packard", "HP"),
        ("Hewlett Packard Enterprise", "HPE"),
        ("VMware, Inc.", "VMware"),
        ("  Microsoft   Corporation ", "Microsoft"),
        ("Acme Widgets", "Acme Widgets"),
        ("", None),
        (None, None),
    ],
)
def test_manufacturer_aliases(raw, expected):
    assert normalize_manufacturer(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" foc2233x0ab ", "FOC2233X0AB"),
        ("To be filled by O.E.M.", None),
        ("Default string", None),
        ("System Serial Number", None),
        ("0000000000", None),
        ("N/A", None),
        ("", None),
        (12345678, "12345678"),
    ],
)
def test_serial_placeholders_become_unknown(raw, expected):
    assert normalize_serial(raw) == expected


def test_uuid_rejects_all_zero_and_invalid():
    assert normalize_uuid("00000000-0000-0000-0000-000000000000") is None
    assert normalize_uuid("not-a-uuid") is None
    assert (
        normalize_uuid("4C4C4544-0058-4B10-8032-B7C04F513933")
        == "4c4c4544-0058-4b10-8032-b7c04f513933"
    )


def test_record_normalization_is_complete_and_honest():
    record = {
        "external_id": " 317 ",
        "observed_at": "2026-11-02T08:00:00Z",
        "manufacturer": "Cisco Systems, Inc.",
        "model": "  C9300-48T ",
        "serial": "Default string",
        "hostname": "SW-CORE-01.corp.example.",
        "interfaces": [
            {"name": "Vlan10", "mac": "0200.0000.0001", "ips": ["10.10.0.2", "999.1.1.1"]},
            {"name": "Gi1/0/1", "mac": "00:00:00:00:00:00"},
        ],
        "ip_addresses": [{"address": "10.10.0.2"}, {"address": "192.0.2.1", "vrf": "MGMT"}],
        "device_type": "Switch",
    }

    out = normalize_record(record, site_id="site-1", default_vrf="")

    assert out["external_id"] == "317"
    assert out["manufacturer"] == "Cisco" and out["model"] == "C9300-48T"
    assert out["serial_number"] is None and out["serial_verified"] is False
    assert out["hostnames"] == ["sw-core-01.corp.example"]
    assert out["short_hostnames"] == ["sw-core-01"]
    assert out["mac_addresses"] == ["02:00:00:00:00:01"]
    assert out["ip_addresses"] == [
        {"address": "10.10.0.2", "interface": "Vlan10", "vrf": "", "site": "site-1"},
        {"address": "192.0.2.1", "interface": None, "vrf": "MGMT", "site": "site-1"},
    ]
    assert out["category_code"] == "networking-switch"
    assert any("placeholder" in w for w in out["warnings"])
    assert any("999.1.1.1" in w for w in out["warnings"])


@pytest.mark.parametrize(
    "record",
    [
        {"observed_at": "2026-11-02T08:00:00Z"},
        {"external_id": "1"},
        {"external_id": "1", "observed_at": "2026-11-02T08:00:00"},
        {"external_id": "1", "observed_at": "yesterday"},
        {"external_id": "1", "observed_at": "2026-11-02T08:00:00Z", "interfaces": "eth0"},
        "not an object",
    ],
)
def test_invalid_records_are_rejected(record):
    with pytest.raises(RecordError):
        normalize_record(record, site_id="s")


def test_checksum_ignores_observation_time_only():
    a = {"external_id": "1", "observed_at": "2026-11-02T08:00:00Z", "model": "X"}
    b = {**a, "observed_at": "2026-11-03T08:00:00Z"}
    c = {**a, "model": "Y"}

    assert checksum(a) == checksum(b)
    assert checksum(a) != checksum(c)
