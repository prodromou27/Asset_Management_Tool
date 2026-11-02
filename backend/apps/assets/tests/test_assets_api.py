import pytest

from apps.assets.models import (
    Asset,
    AssetHistoryEntry,
    AssetHostname,
    AssetInterface,
    CustomFieldDefinition,
    Source,
)
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db
ASSETS = "/api/v1/assets/"


def payload(site, category, **extra):
    return {"name": "sw-core-01", "site": str(site.pk), "category": str(category.pk), **extra}


def errors(response):
    return response.json()["error"]["field_errors"]


# --- Permissions ------------------------------------------------------------------


def test_unauthenticated_is_401(api_client):
    assert api_client.get(ASSETS).status_code == 401


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("post", "", "create"),
        ("patch", "{id}/", {"name": "x"}),
        ("post", "{id}/archive/", {"reason": "retire it now"}),
        ("post", "{id}/classification/", "reclassify"),
    ],
)
def test_read_only_role_cannot_mutate(
    client_for, hq_reader, hq, switch, laptop, make_asset, method, suffix, body
):
    asset = make_asset(site=hq, category=switch)
    if body == "create":
        body = payload(hq, switch)
    elif body == "reclassify":
        body = {"category": str(laptop.pk), "reason": "wrong category"}
    audit_before = AuditEvent.objects.exclude(action="auth.login").count()

    response = getattr(client_for(hq_reader), method)(
        ASSETS + suffix.format(id=asset.pk), body, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 403
    assert AuditEvent.objects.exclude(action="auth.login").count() == audit_before
    assert Asset.objects.count() == 1


def test_operator_cannot_reclassify_or_archive(
    client_for, hq_operator, hq, switch, laptop, make_asset
):
    asset = make_asset(site=hq, category=switch)
    client = client_for(hq_operator)

    assert (
        client.post(
            f"{ASSETS}{asset.pk}/archive/", {"reason": "nope nope"}, format="json"
        ).status_code
        == 403
    )
    response = client.post(
        f"{ASSETS}{asset.pk}/classification/",
        {"category": str(laptop.pk), "reason": "nope nope"},
        format="json",
    )
    assert response.status_code == 403


def test_hard_delete_is_not_offered(client_for, admin_user, hq, switch, make_asset):
    asset = make_asset(site=hq, category=switch)

    assert client_for(admin_user).delete(f"{ASSETS}{asset.pk}/").status_code == 405
    assert Asset.objects.filter(pk=asset.pk).exists()


# --- Create -------------------------------------------------------------------------


def test_minimal_manual_asset_needs_no_ip_mac_serial_or_hostname(client_for, hq_operator, hq):
    from apps.assets.models import AssetCategory

    tv = AssetCategory.objects.get(code="tvs")
    response = client_for(hq_operator).post(
        ASSETS, {"name": "Reception TV", "site": str(hq.pk), "category": str(tv.pk)}, format="json"
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["serial_number"] == "" and body["primary_ip"] is None and body["hostnames"] == []
    assert body["business_status"] == "in_stock"
    assert body["observation_status"] == "manual_only"
    assert body["support_status"] == "unknown"
    assert body["category"]["path"] == "TVs"
    assert body["version"] == 1 and response["ETag"] == '"1"'


def test_create_full_asset_records_history_and_audit(
    client_for, hq_operator, hq, hq_room, it_dept, switch, admin_user
):
    body = payload(
        hq,
        switch,
        asset_tag=" it-001254 ",
        manufacturer="Cisco",
        model="C9300-48T-A",
        serial_number="FOC0000X000",
        os_name="IOS XE",
        os_version="17.9.4",
        firmware_version="17.9.4",
        location=str(hq_room.pk),
        department=str(it_dept.pk),
        owner=str(admin_user.pk),
        business_status="deployed",
        notes="Core switch",
        hostnames=[{"hostname": "SW-CORE-01.corp.example.", "is_primary": True}],
        interfaces=[{"name": "Vlan10", "mac_address": "02-00-00-00-00-01"}],
        ip_addresses=[{"address": "10.10.0.2", "interface_name": "Vlan10", "is_primary": True}],
    )

    response = client_for(hq_operator).post(ASSETS, body, format="json")

    assert response.status_code == 201, response.json()
    data = response.json()
    assert data["asset_tag"] == "IT-001254"
    assert data["primary_hostname"] == "sw-core-01.corp.example"
    assert data["primary_ip"] == "10.10.0.2"
    assert data["interfaces"][0]["mac_address"] == "02:00:00:00:00:01"
    assert data["interfaces"][0]["source"] == "manual"
    assert data["ip_addresses"][0]["interface_name"] == "Vlan10"
    assert data["category"]["path"] == "Networking / Switch"
    assert data["owner"]["username"] == "admin.one"

    entry = AssetHistoryEntry.objects.get(asset_id=data["id"])
    assert entry.change_type == "created" and entry.actor.username == "hq.operator"
    assert entry.changes["site"] == {"before": None, "after": "HQ"}
    assert AuditEvent.objects.filter(action="assets.create", object_id=data["id"]).exists()


@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ({"name": "  "}, "name"),
        ({"asset_tag": "has space"}, "asset_tag"),
        ({"business_status": "stolen"}, "business_status"),
        ({"hostnames": [{"hostname": "bad_host!"}]}, "hostnames.0.hostname"),
        ({"interfaces": [{"name": "eth0", "mac_address": "zz:zz"}]}, "interfaces.0.mac_address"),
        ({"ip_addresses": [{"address": "999.1.1.1"}]}, "ip_addresses.0.address"),
        (
            {"ip_addresses": [{"address": "10.0.0.1", "interface_name": "eth9"}]},
            "ip_addresses.0.interface_name",
        ),
        ({"hostnames": [{"hostname": "a"}, {"hostname": "A."}]}, "hostnames.1.hostname"),
        (
            {
                "hostnames": [
                    {"hostname": "a", "is_primary": True},
                    {"hostname": "b", "is_primary": True},
                ]
            },
            "hostnames",
        ),
        ({"custom_fields": {"nonsense": 1}}, "custom_fields.nonsense"),
    ],
)
def test_create_validation(client_for, hq_operator, hq, switch, extra, field):
    response = client_for(hq_operator).post(ASSETS, payload(hq, switch, **extra), format="json")

    assert response.status_code == 422, response.json()
    assert field in errors(response)
    assert not Asset.objects.exists()


def test_inactive_category_location_and_disabled_owner_rejected(
    client_for, hq_operator, hq, hq_room, switch, make_user
):
    hq_room.is_active = False
    hq_room.save()
    gone = make_user("gone.owner", is_active=False)
    switch.is_active = False
    switch.save()

    response = client_for(hq_operator).post(
        ASSETS, payload(hq, switch, location=str(hq_room.pk), owner=str(gone.pk)), format="json"
    )

    assert response.status_code == 422
    assert "category" in errors(response)


def test_location_must_belong_to_site(client_for, admin_user, hq, branch_room, switch):
    response = client_for(admin_user).post(
        ASSETS, payload(hq, switch, location=str(branch_room.pk)), format="json"
    )

    assert response.status_code == 422
    assert errors(response)["location"] == ["The location must belong to the selected site."]


# --- Uniqueness ----------------------------------------------------------------------


def test_asset_tag_unique_case_insensitively_but_optional(
    client_for, admin_user, hq, branch, switch
):
    client = client_for(admin_user)
    assert (
        client.post(ASSETS, payload(hq, switch, asset_tag="IT-1"), format="json").status_code == 201
    )
    dup = client.post(
        ASSETS, payload(branch, switch, name="other", asset_tag="it-1"), format="json"
    )
    assert dup.status_code == 422
    assert errors(dup)["asset_tag"] == ["This asset tag is already in use."]

    for name in ("no-tag-1", "no-tag-2"):
        assert (
            client.post(
                ASSETS, payload(hq, switch, name=name, asset_tag=""), format="json"
            ).status_code
            == 201
        )
    assert Asset.objects.filter(asset_tag__isnull=True).count() == 2


def test_ip_mac_hostname_and_serial_are_not_globally_unique(client_for, admin_user, hq, switch):
    client = client_for(admin_user)
    shared = {
        "serial_number": "SAME",
        "hostnames": [{"hostname": "dup.example"}],
        "interfaces": [{"name": "eth0", "mac_address": "02:00:00:00:00:09"}],
        "ip_addresses": [{"address": "10.0.0.9", "interface_name": "eth0"}],
    }

    assert (
        client.post(ASSETS, payload(hq, switch, name="a", **shared), format="json").status_code
        == 201
    )
    assert (
        client.post(ASSETS, payload(hq, switch, name="b", **shared), format="json").status_code
        == 201
    )


# --- Update / reassignment -----------------------------------------------------------


def test_patch_requires_if_match_and_rejects_stale(client_for, hq_operator, hq, switch, make_asset):
    asset = make_asset(site=hq, category=switch)
    client = client_for(hq_operator)

    assert client.patch(f"{ASSETS}{asset.pk}/", {"name": "x"}, format="json").status_code == 428
    stale = client.patch(f"{ASSETS}{asset.pk}/", {"name": "x"}, format="json", HTTP_IF_MATCH='"9"')
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_MISMATCH"


def test_concurrent_editors_second_write_loses(
    client_for, hq_operator, hq_manager, hq, switch, make_asset
):
    asset = make_asset(site=hq, category=switch)
    first, second = client_for(hq_operator), client_for(hq_manager)

    ok = first.patch(f"{ASSETS}{asset.pk}/", {"model": "A"}, format="json", HTTP_IF_MATCH='"1"')
    lost = second.patch(f"{ASSETS}{asset.pk}/", {"model": "B"}, format="json", HTTP_IF_MATCH='"1"')

    assert ok.status_code == 200 and ok.json()["version"] == 2
    assert lost.status_code == 409
    asset.refresh_from_db()
    assert asset.model == "A" and asset.version == 2


def test_update_records_diff_history(client_for, hq_operator, hq, switch, make_asset):
    asset = make_asset(site=hq, category=switch, model="old")

    response = client_for(hq_operator).patch(
        f"{ASSETS}{asset.pk}/",
        {"model": "new", "notes": "hello"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 200
    entry = AssetHistoryEntry.objects.filter(asset=asset).first()
    assert entry.change_type == "updated" and entry.version == 2
    assert entry.changes == {
        "model": {"before": "old", "after": "new"},
        "notes": {"before": "", "after": "hello"},
    }
    assert AuditEvent.objects.filter(action="assets.update", object_id=str(asset.pk)).exists()


def test_noop_patch_does_not_bump_version(client_for, hq_operator, hq, switch, make_asset):
    asset = make_asset(site=hq, category=switch, model="same")

    response = client_for(hq_operator).patch(
        f"{ASSETS}{asset.pk}/", {"model": "same"}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.json()["version"] == 1
    assert AssetHistoryEntry.objects.filter(asset=asset).count() == 1


def test_reassignment_is_recorded_as_such(
    client_for, admin_user, hq, branch, branch_room, switch, make_asset, hq_operator
):
    asset = make_asset(site=hq, category=switch)

    response = client_for(admin_user).patch(
        f"{ASSETS}{asset.pk}/",
        {"site": str(branch.pk), "location": str(branch_room.pk), "owner": str(hq_operator.pk)},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 200, response.json()
    entry = AssetHistoryEntry.objects.filter(asset=asset).first()
    assert entry.change_type == "reassigned"
    assert entry.changes["site"] == {"before": "HQ", "after": "BR1"}
    assert entry.changes["owner"] == {"before": None, "after": "hq.operator"}
    assert AuditEvent.objects.filter(action="assets.reassign").exists()


def test_site_change_with_stale_location_is_rejected(
    client_for, admin_user, hq, hq_room, branch, switch, make_asset
):
    asset = make_asset(site=hq, category=switch, location=hq_room)

    response = client_for(admin_user).patch(
        f"{ASSETS}{asset.pk}/", {"site": str(branch.pk)}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 422
    assert "location" in errors(response)


def test_category_cannot_change_through_patch(
    client_for, hq_manager, hq, switch, laptop, make_asset
):
    asset = make_asset(site=hq, category=switch)

    response = client_for(hq_manager).patch(
        f"{ASSETS}{asset.pk}/", {"category": str(laptop.pk)}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 422
    assert "classification" in errors(response)["category"][0]


def test_read_only_status_dimensions_are_ignored_on_write(
    client_for, hq_operator, hq, switch, make_asset
):
    asset = make_asset(site=hq, category=switch)

    client_for(hq_operator).patch(
        f"{ASSETS}{asset.pk}/",
        {"support_status": "supported", "observation_status": "recently_seen"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    asset.refresh_from_db()
    assert asset.support_status == "unknown" and asset.observation_status == "manual_only"


# --- Network evidence ------------------------------------------------------------------


def test_manual_network_edit_preserves_discovered_rows(
    client_for, hq_operator, hq, switch, make_asset
):
    asset = make_asset(
        site=hq, category=switch, hostnames=[{"hostname": "old.example", "is_primary": True}]
    )
    AssetHostname.objects.create(
        asset=asset, hostname="seen.example", source=Source.LIBRENMS, source_ref="317"
    )
    AssetInterface.objects.create(
        asset=asset, name="Gi1/0/1", mac_address="02:00:00:00:00:aa", source=Source.LIBRENMS
    )

    response = client_for(hq_operator).patch(
        f"{ASSETS}{asset.pk}/",
        {
            "hostnames": [{"hostname": "new.example", "is_primary": True}],
            "ip_addresses": [{"address": "10.1.1.1", "interface_name": "Gi1/0/1"}],
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 200, response.json()
    hostnames = {(h["hostname"], h["source"]) for h in response.json()["hostnames"]}
    assert hostnames == {("new.example", "manual"), ("seen.example", "librenms")}
    assert response.json()["ip_addresses"][0]["interface_name"] == "Gi1/0/1"
    changes = AssetHistoryEntry.objects.filter(asset=asset).first().changes
    assert "hostnames" in changes and "ip_addresses" in changes


def test_ip_and_mac_searchable(client_for, admin_user, hq, switch, make_asset):
    make_asset(
        "findme",
        site=hq,
        category=switch,
        interfaces=[{"name": "eth0", "mac_address": "02:00:00:00:00:0b"}],
        ip_addresses=[{"address": "192.0.2.10", "interface_name": "eth0"}],
    )
    make_asset("other", site=hq, category=switch)
    client = client_for(admin_user)

    for q in ("192.0.2.10", "0200.0000.000B", "FINDME"):
        assert [a["name"] for a in client.get(ASSETS, {"q": q}).json()["items"]] == ["findme"], q


# --- Custom fields ---------------------------------------------------------------------


@pytest.fixture
def switch_fields(switch):
    networking = switch.parent
    return {
        "rack_units": CustomFieldDefinition.objects.create(
            category=networking,
            key="rack_units",
            label="Rack units",
            field_type="integer",
            min_value=1,
            max_value=52,
        ),
        "port_count": CustomFieldDefinition.objects.create(
            category=switch,
            key="port_count",
            label="Port count",
            field_type="integer",
            required=True,
        ),
        "poe": CustomFieldDefinition.objects.create(
            category=switch, key="poe", label="PoE", field_type="boolean"
        ),
        "tier": CustomFieldDefinition.objects.create(
            category=switch,
            key="tier",
            label="Tier",
            field_type="choice",
            choices=["core", "access"],
        ),
        "warranty_end": CustomFieldDefinition.objects.create(
            category=switch, key="warranty_end", label="Warranty end", field_type="date"
        ),
        "power_watts": CustomFieldDefinition.objects.create(
            category=switch, key="power_watts", label="Power (W)", field_type="decimal"
        ),
    }


def test_typed_custom_fields_inherited_and_coerced(
    client_for, admin_user, hq, switch, switch_fields
):
    body = payload(
        hq,
        switch,
        custom_fields={
            "rack_units": "1",
            "port_count": 48,
            "poe": True,
            "tier": "core",
            "warranty_end": "2029-03-31",
            "power_watts": "350.50",
        },
    )

    response = client_for(admin_user).post(ASSETS, body, format="json")

    assert response.status_code == 201, response.json()
    assert response.json()["custom_fields"] == {
        "rack_units": 1,
        "port_count": 48,
        "poe": True,
        "tier": "core",
        "warranty_end": "2029-03-31",
        "power_watts": "350.50",
    }


@pytest.mark.parametrize(
    ("values", "key"),
    [
        ({"port_count": 48, "rack_units": 99}, "rack_units"),
        ({"port_count": "forty"}, "port_count"),
        ({"port_count": 48, "poe": "yes"}, "poe"),
        ({"port_count": 48, "tier": "edge"}, "tier"),
        ({"port_count": 48, "warranty_end": "31/03/2029"}, "warranty_end"),
        ({"port_count": 48, "power_watts": "NaN"}, "power_watts"),
        ({}, "port_count"),
    ],
)
def test_custom_field_validation(client_for, admin_user, hq, switch, switch_fields, values, key):
    response = client_for(admin_user).post(
        ASSETS, payload(hq, switch, custom_fields=values), format="json"
    )

    assert response.status_code == 422
    assert f"custom_fields.{key}" in errors(response)


def test_newly_required_field_does_not_block_unrelated_edits(
    client_for, admin_user, hq, switch, make_asset
):
    asset = make_asset(site=hq, category=switch)
    CustomFieldDefinition.objects.create(
        category=switch, key="port_count", label="Port count", field_type="integer", required=True
    )
    client = client_for(admin_user)

    response = client.patch(
        f"{ASSETS}{asset.pk}/", {"notes": "edited"}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 200
    assert response.json()["missing_required_fields"] == ["port_count"]


# --- List / query budget -------------------------------------------------------------


def test_list_shape_ordering_and_archived_filter(client_for, admin_user, hq, switch, make_asset):
    for name in ("b-asset", "a-asset", "c-asset"):
        make_asset(name, site=hq, category=switch)
    client = client_for(admin_user)

    body = client.get(ASSETS, {"ordering": "name"}).json()
    assert set(body) == {"items", "next_cursor", "previous_cursor", "count"}
    assert [a["name"] for a in body["items"]] == ["a-asset", "b-asset", "c-asset"]
    page = client.get(ASSETS, {"ordering": "name", "page_size": 2}).json()
    rest = client.get(
        ASSETS, {"ordering": "name", "page_size": 2, "cursor": page["next_cursor"]}
    ).json()
    assert [a["name"] for a in page["items"] + rest["items"]] == ["a-asset", "b-asset", "c-asset"]


def test_category_filter_includes_subcategories(
    client_for, admin_user, hq, switch, laptop, make_asset
):
    make_asset("sw", site=hq, category=switch)
    make_asset("lt", site=hq, category=laptop)

    response = client_for(admin_user).get(ASSETS, {"category": str(switch.parent_id)})

    assert [a["name"] for a in response.json()["items"]] == ["sw"]


def test_invalid_filter_values_return_empty_not_error(
    client_for, admin_user, hq, switch, make_asset
):
    make_asset(site=hq, category=switch)
    client = client_for(admin_user)

    for params in ({"site": "not-a-uuid"}, {"business_status": "bogus"}, {"owner": "1"}):
        response = client.get(ASSETS, params)
        assert response.status_code == 200 and response.json()["count"] == 0, params


def test_list_query_count_is_bounded(
    client_for, admin_user, hq, switch, make_asset, django_assert_max_num_queries
):
    for i in range(30):
        make_asset(
            f"asset-{i:02}", site=hq, category=switch, hostnames=[{"hostname": f"h{i}.example"}]
        )
    client = client_for(admin_user)

    with django_assert_max_num_queries(12):
        response = client.get(ASSETS, {"page_size": 50})

    assert len(response.json()["items"]) == 30
