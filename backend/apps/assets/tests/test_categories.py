import pytest

from apps.assets.models import AssetCategory, CustomFieldDefinition
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db
CATEGORIES = "/api/v1/asset-categories/"


def test_seeded_taxonomy_contains_required_categories(client_for, hq_reader):
    rows = client_for(hq_reader).get(CATEGORIES).json()
    names = {row["name"] for row in rows if row["depth"] == 0}

    for required in (
        "Workstations",
        "Servers",
        "Networking",
        "Security",
        "Printers",
        "Monitors",
        "IP Phones",
        "TVs",
        "UPS",
        "Storage",
        "Other",
    ):
        assert required in names
    switch = next(r for r in rows if r["code"] == "networking-switch")
    assert switch["path"] == "Networking / Switch" and switch["depth"] == 1


def test_only_category_managers_can_change_taxonomy(client_for, hq_manager):
    response = client_for(hq_manager).post(CATEGORIES, {"name": "Cameras"}, format="json")

    assert response.status_code == 403
    assert not AssetCategory.objects.filter(name="Cameras").exists()


def test_admin_creates_child_with_generated_code_and_audit(client_for, admin_user):
    networking = AssetCategory.objects.get(code="networking")

    response = client_for(admin_user).post(
        CATEGORIES, {"name": "SD-WAN Edge", "parent": str(networking.pk)}, format="json"
    )

    assert response.status_code == 201, response.json()
    assert response.json()["code"] == "networking-sd-wan-edge"
    assert response.json()["path"] == "Networking / SD-WAN Edge"
    assert AuditEvent.objects.filter(action="categories.create").exists()


def test_duplicate_name_at_same_level_rejected_case_insensitively(client_for, admin_user):
    response = client_for(admin_user).post(CATEGORIES, {"name": "networking"}, format="json")

    assert response.status_code == 422
    assert "name" in response.json()["error"]["field_errors"]


def test_move_category_and_prevent_cycles(client_for, admin_user, switch):
    client = client_for(admin_user)
    security = AssetCategory.objects.get(code="security")
    networking = switch.parent

    moved = client.patch(
        f"{CATEGORIES}{switch.pk}/",
        {"parent": str(security.pk)},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert moved.status_code == 200 and moved.json()["path"] == "Security / Switch"
    assert AuditEvent.objects.filter(action="categories.move").exists()

    cycle = client.patch(
        f"{CATEGORIES}{networking.pk}/",
        {"parent": str(networking.pk)},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert cycle.status_code == 422


def test_code_is_immutable(client_for, admin_user, switch):
    response = client_for(admin_user).patch(
        f"{CATEGORIES}{switch.pk}/", {"code": "renamed"}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 422


def test_custom_field_definition_lifecycle(client_for, admin_user, switch):
    client = client_for(admin_user)
    created = client.post(
        f"{CATEGORIES}{switch.pk}/fields/",
        {
            "key": "port_count",
            "label": "Port count",
            "field_type": "integer",
            "required": True,
            "min_value": 1,
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    field_id = created.json()["id"]

    effective = client.get(f"{CATEGORIES}{switch.pk}/fields/", {"effective": "true"}).json()
    assert [f["key"] for f in effective] == ["port_count"]

    updated = client.patch(
        f"/api/v1/custom-fields/{field_id}/",
        {"required": False, "label": "Ports"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert updated.status_code == 200 and updated.json()["version"] == 2
    assert AuditEvent.objects.filter(action__startswith="custom_fields.").count() == 2


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"key": "Bad Key", "label": "x", "field_type": "text"}, "key"),
        ({"key": "tier", "label": "Tier", "field_type": "choice"}, "choices"),
        (
            {"key": "tier", "label": "Tier", "field_type": "choice", "choices": ["a", "a"]},
            "choices",
        ),
        ({"key": "size", "label": "Size", "field_type": "text", "min_value": 1}, "min_value"),
        (
            {"key": "n", "label": "N", "field_type": "integer", "min_value": 5, "max_value": 1},
            "max_value",
        ),
    ],
)
def test_custom_field_definition_validation(client_for, admin_user, switch, body, field):
    response = client_for(admin_user).post(f"{CATEGORIES}{switch.pk}/fields/", body, format="json")

    assert response.status_code == 422
    assert field in response.json()["error"]["field_errors"]


def test_field_key_cannot_shadow_parent_or_child(client_for, admin_user, switch):
    CustomFieldDefinition.objects.create(
        category=switch.parent, key="rack_units", label="RU", field_type="integer"
    )

    response = client_for(admin_user).post(
        f"{CATEGORIES}{switch.pk}/fields/",
        {"key": "rack_units", "label": "RU", "field_type": "integer"},
        format="json",
    )

    assert response.status_code == 422
    assert "key" in response.json()["error"]["field_errors"]


def test_field_type_and_key_are_immutable(client_for, admin_user, switch):
    definition = CustomFieldDefinition.objects.create(
        category=switch, key="ports", label="Ports", field_type="integer"
    )

    client_for(admin_user).patch(
        f"/api/v1/custom-fields/{definition.pk}/",
        {"field_type": "text", "key": "x"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    definition.refresh_from_db()
    assert definition.field_type == "integer" and definition.key == "ports"
