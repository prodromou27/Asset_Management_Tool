"""Reclassification, archival/restore and append-only history."""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.assets.models import AssetHistoryEntry, CustomFieldDefinition
from apps.audit.models import AuditEvent
from tests.conftest import requires_postgres

pytestmark = pytest.mark.django_db
ASSETS = "/api/v1/assets/"


@pytest.fixture
def switch_asset(make_asset, hq, switch):
    CustomFieldDefinition.objects.create(
        category=switch, key="port_count", label="Ports", field_type="integer"
    )
    return make_asset(site=hq, category=switch, custom_fields={"port_count": 48})


@pytest.fixture
def laptop_required(laptop):
    return CustomFieldDefinition.objects.create(
        category=laptop,
        key="screen_inches",
        label="Screen size",
        field_type="decimal",
        required=True,
    )


def url(asset, suffix=""):
    return f"{ASSETS}{asset.pk}/{suffix}"


# --- Reclassification ----------------------------------------------------------------


def test_preview_shows_impact_and_changes_nothing(
    client_for, hq_manager, switch_asset, laptop, laptop_required
):
    response = client_for(hq_manager).post(
        url(switch_asset, "classification/preview/"), {"category": str(laptop.pk)}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {
        "from_category": "Networking / Switch",
        "to_category": "Workstations / Laptop",
        "fields_added": [{"key": "screen_inches", "label": "Screen size", "required": True}],
        "fields_kept": [],
        "values_retained_read_only": ["port_count"],
        "required_missing": ["screen_inches"],
    }
    switch_asset.refresh_from_db()
    assert switch_asset.category.code == "networking-switch" and switch_asset.version == 1


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "reason"),
        ({"reason": "  "}, "reason"),
        ({"reason": "because"}, "custom_fields.screen_inches"),
    ],
)
def test_reclassify_requires_reason_and_new_required_fields(
    client_for, hq_manager, switch_asset, laptop, laptop_required, body, field
):
    response = client_for(hq_manager).post(
        url(switch_asset, "classification/"),
        {"category": str(laptop.pk), **body},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 422
    assert field in response.json()["error"]["field_errors"]


def test_reclassify_keeps_old_values_records_reason(
    client_for, hq_manager, switch_asset, laptop, laptop_required
):
    response = client_for(hq_manager).post(
        url(switch_asset, "classification/"),
        {
            "category": str(laptop.pk),
            "reason": "Mis-registered at intake",
            "custom_fields": {"screen_inches": "14"},
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["category"]["path"] == "Workstations / Laptop"
    assert body["custom_fields"] == {"port_count": 48, "screen_inches": "14"}
    assert body["retained_custom_fields"] == ["port_count"]
    assert body["version"] == 2
    entry = AssetHistoryEntry.objects.filter(asset=switch_asset).first()
    assert entry.change_type == "reclassified" and entry.reason == "Mis-registered at intake"
    assert entry.changes["category"] == {
        "before": "Networking / Switch",
        "after": "Workstations / Laptop",
    }
    event = AuditEvent.objects.get(action="assets.reclassify")
    assert event.detail == "Mis-registered at intake"


def test_retained_values_are_read_only(
    client_for, admin_user, switch_asset, laptop, laptop_required
):
    client = client_for(admin_user)
    client.post(
        url(switch_asset, "classification/"),
        {
            "category": str(laptop.pk),
            "reason": "Move to laptops",
            "custom_fields": {"screen_inches": 14},
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    response = client.patch(
        url(switch_asset), {"custom_fields": {"port_count": 24}}, format="json", HTTP_IF_MATCH='"2"'
    )

    assert response.status_code == 422
    assert "custom_fields.port_count" in response.json()["error"]["field_errors"]


@pytest.mark.parametrize("target", ["same", "inactive"])
def test_reclassify_rejects_same_or_inactive_category(
    client_for, hq_manager, switch_asset, switch, laptop, target
):
    category = switch if target == "same" else laptop
    if target == "inactive":
        laptop.is_active = False
        laptop.save()

    response = client_for(hq_manager).post(
        url(switch_asset, "classification/"),
        {"category": str(category.pk), "reason": "testing it"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 422


def test_reclassify_requires_if_match(client_for, hq_manager, switch_asset, laptop):
    response = client_for(hq_manager).post(
        url(switch_asset, "classification/"),
        {"category": str(laptop.pk), "reason": "no version"},
        format="json",
    )

    assert response.status_code == 428


# --- Archival ----------------------------------------------------------------------


def test_archive_hides_freezes_and_restore_returns(client_for, hq_manager, switch_asset):
    client = client_for(hq_manager)

    assert (
        client.post(
            url(switch_asset, "archive/"), {"reason": "x"}, format="json", HTTP_IF_MATCH='"1"'
        ).status_code
        == 422
    )
    archived = client.post(
        url(switch_asset, "archive/"),
        {"reason": "Disposed via WEEE"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True and archived.json()["archived_by"] == "hq.manager"

    assert client.get(ASSETS).json()["count"] == 0
    assert client.get(ASSETS, {"archived": "only"}).json()["count"] == 1
    assert client.get(ASSETS, {"archived": "include"}).json()["count"] == 1
    assert client.get(url(switch_asset)).status_code == 200

    blocked = client.patch(url(switch_asset), {"name": "x"}, format="json", HTTP_IF_MATCH='"2"')
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "ASSET_ARCHIVED"
    again = client.post(
        url(switch_asset, "archive/"),
        {"reason": "again please"},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    assert again.status_code == 409

    restored = client.post(url(switch_asset, "restore/"), format="json", HTTP_IF_MATCH='"2"')
    assert restored.status_code == 200 and restored.json()["is_archived"] is False
    assert (
        client.post(url(switch_asset, "restore/"), format="json", HTTP_IF_MATCH='"3"').status_code
        == 409
    )

    kinds = list(
        AssetHistoryEntry.objects.filter(asset=switch_asset)
        .order_by("occurred_at")
        .values_list("change_type", flat=True)
    )
    assert kinds == ["created", "archived", "restored"]
    assert AuditEvent.objects.filter(action__in=["assets.archive", "assets.restore"]).count() == 2


def test_restore_blocked_when_site_inactive(client_for, hq_manager, switch_asset, hq):
    client = client_for(hq_manager)
    client.post(
        url(switch_asset, "archive/"),
        {"reason": "Temporarily out"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    hq.is_active = False
    hq.save()

    response = client.post(url(switch_asset, "restore/"), format="json", HTTP_IF_MATCH='"2"')

    assert response.status_code == 409 and response.json()["error"]["code"] == "SITE_INACTIVE"


# --- History -----------------------------------------------------------------------


def test_history_endpoint_lists_newest_first(client_for, hq_reader, hq_manager, switch_asset):
    client_for(hq_manager).patch(
        url(switch_asset), {"model": "X"}, format="json", HTTP_IF_MATCH='"1"'
    )

    body = client_for(hq_reader).get(url(switch_asset, "history/")).json()

    assert [e["change_type"] for e in body["items"]] == ["updated", "created"]
    assert body["items"][0]["actor_label"] == "hq.manager"
    assert body["items"][0]["changes"]["model"] == {"before": "", "after": "X"}


def test_history_model_is_append_only(switch_asset):
    entry = AssetHistoryEntry.objects.get(asset=switch_asset)

    with pytest.raises(RuntimeError):
        entry.save()
    with pytest.raises(RuntimeError):
        entry.delete()


@requires_postgres
def test_postgres_trigger_blocks_history_tampering(switch_asset):
    for sql in (
        "UPDATE assets_assethistoryentry SET reason = 'tampered'",
        "DELETE FROM assets_assethistoryentry",
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)

    assert AssetHistoryEntry.objects.get(asset=switch_asset).reason == ""
