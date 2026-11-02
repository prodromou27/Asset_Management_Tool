"""Identity matching rules (docs/03, docs/05, docs/15 A02, A04)."""

import pytest

from apps.assets.models import Asset, AssetCategory
from apps.reconciliation import services
from apps.reconciliation.models import ReconciliationCandidate, SourceLink

from .conftest import Req, ingest, laptop_record, switch_record

pytestmark = pytest.mark.django_db


def candidate(instance, external_id="317"):
    return ReconciliationCandidate.objects.get(
        instance=instance, external_id=external_id, status__in=["open", "held"]
    )


def test_ip_alone_never_merges(nms, make_asset, hq, switch):
    """docs/15 A04: an IP reused by another physical device."""
    existing = make_asset(
        "old-printer", site=hq, category=switch, ip_addresses=[{"address": "10.10.0.2"}]
    )

    ingest(
        nms,
        switch_record(
            serial="NEWDEVICE1",
            hostname="new-switch",
            interfaces=[{"name": "Vlan10", "ips": ["10.10.0.2"]}],
        ),
    )

    c = candidate(nms)
    assert c.rule == "weak" and c.score == 20  # ip 10 + category agrees 10
    assert c.proposed_asset_id == existing.pk
    assert not SourceLink.objects.exists()


def test_ip_in_other_site_or_vrf_is_not_evidence(nms, make_asset, branch, hq, switch):
    make_asset(
        "branch-device", site=branch, category=switch, ip_addresses=[{"address": "10.10.0.2"}]
    )

    ingest(
        nms,
        switch_record(
            serial="S1", hostname="h1", interfaces=[{"name": "Vlan10", "ips": ["10.10.0.2"]}]
        ),
    )

    assert candidate(nms).rule == "new_device"


@pytest.mark.parametrize(
    "asset_kwargs",
    [
        {"hostnames": [{"hostname": "sw-core-01.corp.example"}]},
        {"interfaces": [{"name": "x", "mac_address": "02:00:00:00:00:01"}]},
        {"model": "C9300-48T"},
    ],
    ids=["hostname", "mac", "model"],
)
def test_single_weak_identifier_is_review_only(nms, make_asset, hq, switch, asset_kwargs):
    make_asset("unrelated", site=hq, category=switch, **asset_kwargs)

    ingest(nms, switch_record(serial="NOMATCH1"))

    c = candidate(nms)
    assert c.rule in ("weak", "new_device")  # model alone is not even a key
    assert not SourceLink.objects.exists()


def test_hostname_and_name_count_as_one_identifier(nms, make_asset, hq, switch):
    make_asset(
        "sw-core-01", site=hq, category=switch, hostnames=[{"hostname": "sw-core-01.corp.example"}]
    )

    ingest(nms, switch_record(serial="NOMATCH2", interfaces=[]))

    assert candidate(nms).rule == "weak"


def test_multiple_corroborating_identifiers_need_review(nms, make_asset, hq, switch):
    target = make_asset(
        "core",
        site=hq,
        category=switch,
        hostnames=[{"hostname": "sw-core-01.corp.example"}],
        interfaces=[{"name": "Vlan10", "mac_address": "02:00:00:00:00:01"}],
    )

    ingest(nms, switch_record(serial="NOMATCH3"))

    c = candidate(nms)
    assert c.rule == "corroborated" and c.proposed_asset_id == target.pk
    assert {k["key"] for k in c.matches[0]["keys"]} >= {"mac", "hostname"}
    assert not SourceLink.objects.exists()


def test_verified_serial_is_strong_but_needs_approval_by_default(nms, make_asset, hq, switch):
    target = make_asset(
        "core", site=hq, category=switch, manufacturer="Cisco", serial_number="FOC2233X0AB"
    )

    ingest(nms, switch_record())

    c = candidate(nms)
    assert c.rule == "strong" and c.proposed_asset_id == target.pk and c.score >= 80
    assert not SourceLink.objects.exists()


def test_serial_with_different_manufacturer_is_not_a_match(nms, make_asset, hq, switch):
    make_asset("other", site=hq, category=switch, manufacturer="HP", serial_number="FOC2233X0AB")

    ingest(nms, switch_record(hostname="zz", interfaces=[]))

    assert candidate(nms).rule == "new_device"


def test_strong_match_auto_links_when_policy_allows(nms, make_asset, hq, switch):
    nms.auto_link_strong_matches = True
    nms.save()
    target = make_asset(
        "core", site=hq, category=switch, manufacturer="Cisco Systems", serial_number="foc2233x0ab"
    )

    ingest(nms, switch_record())

    link = SourceLink.objects.get()
    assert link.asset == target and link.method == "auto_strong_match"
    assert not ReconciliationCandidate.objects.filter(status="open").exists()
    assert target.history.filter(change_type="linked").exists()


def test_auto_link_blocked_when_category_disagrees(nms, make_asset, hq, laptop):
    nms.auto_link_strong_matches = True
    nms.save()
    make_asset("lt", site=hq, category=laptop, manufacturer="Cisco", serial_number="FOC2233X0AB")

    ingest(nms, switch_record())

    c = candidate(nms)
    assert c.rule == "strong" and "category" in c.conflicts[0]
    assert not SourceLink.objects.exists()


def test_conflicting_strong_identifiers_produce_conflict_candidate(
    nms, ec, make_asset, hq, laptop, admin_user
):
    a = make_asset(
        "by-serial", site=hq, category=laptop, manufacturer="Dell", serial_number="7XK2Q93"
    )
    b = make_asset("by-uuid", site=hq, category=laptop)
    ingest(ec, laptop_record("ec-1", serial="OTHERSERIAL"))
    c = candidate(ec, "ec-1")
    services.approve_link(Req(admin_user), c, b, "Known laptop", c.version)

    ingest(nms, laptop_record("nms-9"))  # serial → a, hardware UUID → b

    conflict = candidate(nms, "nms-9")
    assert conflict.rule == "conflict" and conflict.proposed_asset_id is None
    assert {m["asset_id"] for m in conflict.matches} >= {str(a.pk), str(b.pk)}


def test_same_laptop_in_three_sources_is_one_asset(ec, intune, defender, admin_user):
    """docs/15 A02: one canonical asset, three source links."""
    ingest(ec, laptop_record("EC-501"))
    first = candidate(ec, "EC-501")
    services.approve_create(Req(admin_user), first, {}, "New laptop from EC", first.version)
    asset = Asset.objects.get()

    for instance, ext in ((intune, "intune-aa"), (defender, "def-bb")):
        instance.auto_link_strong_matches = True
        instance.save()
        ingest(instance, laptop_record(ext))

    assert Asset.objects.count() == 1
    assert SourceLink.objects.filter(asset=asset).count() == 3
    assert asset.history.filter(change_type="linked").count() == 3


def test_linked_device_matching_another_asset_flags_duplicate(
    nms, make_asset, hq, switch, admin_user
):
    ingest(nms, switch_record(serial="SN-A"))
    c = candidate(nms)
    services.approve_create(Req(admin_user), c, {}, "New switch", c.version)
    dup = make_asset("dup", site=hq, category=switch, manufacturer="Cisco", serial_number="SN-B")

    ingest(nms, switch_record(serial="SN-B"))

    flagged = candidate(nms)
    assert flagged.rule == "conflict" and "duplicate" in flagged.conflicts[0]
    assert str(dup.pk) in {m["asset_id"] for m in flagged.matches}


def test_rejected_device_stays_rejected_until_it_changes(nms, admin_user):
    ingest(nms, switch_record())
    c = candidate(nms)
    services.reject(Req(admin_user), c, "Lab device, not inventory", c.version)

    ingest(nms, switch_record())
    assert not ReconciliationCandidate.objects.filter(status="open").exists()

    ingest(nms, switch_record(os_version="18.1"))
    assert ReconciliationCandidate.objects.filter(status="open").count() == 1


def test_archived_assets_are_not_matched(nms, make_asset, hq, switch):
    a = make_asset(
        "gone", site=hq, category=switch, manufacturer="Cisco", serial_number="FOC2233X0AB"
    )
    Asset.objects.filter(pk=a.pk).update(archived_at="2026-01-01T00:00:00Z")

    ingest(nms, switch_record(hostname="zz", interfaces=[]))

    assert candidate(nms).rule == "new_device"
    assert AssetCategory.objects.filter(code="networking-switch").exists()
