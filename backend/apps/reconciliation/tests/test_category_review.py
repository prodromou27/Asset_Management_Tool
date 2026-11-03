"""Category mismatch review and link-time reclassification (Task 011, docs/15 A06)."""

import pytest

from apps.assets import services as asset_services
from apps.assets.models import AssetCategory, AssetHistoryEntry, CustomFieldDefinition
from apps.audit.models import AuditEvent
from apps.reconciliation import services
from apps.reconciliation.category_review import kind_of
from apps.reconciliation.models import CategoryReview, ReconciliationCandidate, SourceLink

from .conftest import Req, ingest, laptop_record

pytestmark = pytest.mark.django_db
URL = "/api/v1/discovery/category-reviews/"


def category(code):
    return AssetCategory.objects.get(code=code)


def link(instance, record, asset, user):
    ingest(instance, record)
    c = ReconciliationCandidate.objects.get(
        instance=instance, external_id=record["external_id"], status="open"
    )
    services.approve_link(Req(user), c, asset, "Same device", c.version)


@pytest.fixture
def desktop_asset(make_asset, hq):
    return make_asset("LT-0042", site=hq, category=category("workstations-desktop"))


def test_source_type_differing_from_the_asset_opens_a_review(ec, desktop_asset, admin_user):
    link(ec, laptop_record("ec-1"), desktop_asset, admin_user)

    review = CategoryReview.objects.get()
    assert review.status == "open" and review.kind == "different_type"
    assert review.current_category.code == "workstations-desktop"
    assert review.suggested_category.code == "workstations-laptop"
    assert review.reported_type == "laptop" and review.external_id == "ec-1"
    desktop_asset.refresh_from_db()
    assert desktop_asset.category.code == "workstations-desktop"  # never changed by a source


def test_different_class_and_agreement(ec, make_asset, hq, admin_user, switch):
    server = make_asset("srv", site=hq, category=switch)
    link(ec, laptop_record("ec-1"), server, admin_user)
    assert CategoryReview.objects.get().kind == "different_class"

    laptop_asset = make_asset("lt", site=hq, category=category("workstations-laptop"))
    link(
        ec,
        laptop_record("ec-2", serial="OTHER1", hostname="LT-2", hardware_uuid=None, interfaces=[]),
        laptop_asset,
        admin_user,
    )
    assert not CategoryReview.objects.filter(asset=laptop_asset).exists()


def test_kind_rules():
    from apps.assets.tree import CategoryTree

    tree = CategoryTree()
    root, laptop = category("workstations"), category("workstations-laptop")
    assert kind_of(tree, root.pk, laptop.pk) == "more_specific"
    assert kind_of(tree, laptop.pk, root.pk) is None  # the source is less specific
    assert kind_of(tree, laptop.pk, laptop.pk) is None


def test_reclassify_from_the_review(ec, desktop_asset, admin_user, client_for):
    link(ec, laptop_record("ec-1"), desktop_asset, admin_user)
    review = CategoryReview.objects.get()
    client = client_for(admin_user)

    response = client.post(
        f"{URL}{review.pk}/reclassify/",
        {"reason": "Engineer confirmed it is a laptop"},
        format="json",
        HTTP_IF_MATCH=f'"{review.version}"',
    )

    assert response.status_code == 200 and response.json()["status"] == "reclassified"
    desktop_asset.refresh_from_db()
    assert desktop_asset.category.code == "workstations-laptop"
    entry = desktop_asset.history.filter(
        change_type=AssetHistoryEntry.ChangeType.RECLASSIFIED
    ).get()
    assert entry.reason == "Engineer confirmed it is a laptop"
    assert AuditEvent.objects.filter(action="assets.reclassify").exists()
    assert SourceLink.objects.get(external_id="ec-1").asset == desktop_asset  # same UUID


def test_reclassify_needs_required_template_fields(ec, desktop_asset, admin_user, client_for):
    CustomFieldDefinition.objects.create(
        category=category("workstations-laptop"),
        key="battery_model",
        label="Battery model",
        field_type="text",
        required=True,
    )
    link(ec, laptop_record("ec-1"), desktop_asset, admin_user)
    review = CategoryReview.objects.get()
    client = client_for(admin_user)

    missing = client.post(
        f"{URL}{review.pk}/reclassify/",
        {"reason": "Confirmed laptop"},
        format="json",
        HTTP_IF_MATCH=f'"{review.version}"',
    )
    assert missing.status_code == 422
    review.refresh_from_db()
    assert review.status == "open"

    ok = client.post(
        f"{URL}{review.pk}/reclassify/",
        {"reason": "Confirmed laptop", "custom_fields": {"battery_model": "DELL-7FHHV"}},
        format="json",
        HTTP_IF_MATCH=f'"{review.version}"',
    )
    assert ok.status_code == 200
    desktop_asset.refresh_from_db()
    assert desktop_asset.custom_fields["battery_model"] == "DELL-7FHHV"


def test_dismissed_review_is_not_reproposed_for_the_same_suggestion(
    ec, desktop_asset, admin_user, client_for
):
    link(ec, laptop_record("ec-1"), desktop_asset, admin_user)
    review = CategoryReview.objects.get()
    response = client_for(admin_user).post(
        f"{URL}{review.pk}/dismiss/",
        {"reason": "Docked laptop used as a desktop"},
        format="json",
        HTTP_IF_MATCH=f'"{review.version}"',
    )
    assert response.status_code == 200 and response.json()["status"] == "dismissed"
    assert AuditEvent.objects.filter(action="reconciliation.category_review_dismiss").exists()

    ingest(ec, laptop_record("ec-1", os_version="24H2"))  # changed report, same suggestion
    assert not CategoryReview.objects.filter(status="open").exists()

    ingest(ec, laptop_record("ec-1", os_version="25H1", device_type="server"))
    reopened = CategoryReview.objects.get(status="open")
    assert reopened.suggested_category.code == "servers-physical-server"
    assert reopened.kind == "different_class"


def test_reclassifying_on_the_asset_page_settles_the_review(ec, desktop_asset, admin_user):
    link(ec, laptop_record("ec-1"), desktop_asset, admin_user)
    desktop_asset.refresh_from_db()

    asset_services.reclassify(
        Req(admin_user),
        desktop_asset,
        category("workstations-laptop"),
        "Corrected",
        {},
        desktop_asset.version,
    )

    review = CategoryReview.objects.get()
    assert review.status == "reclassified" and review.resolved_by == admin_user


def test_review_resolves_when_the_source_agrees_again(ec, desktop_asset, admin_user):
    link(ec, laptop_record("ec-1"), desktop_asset, admin_user)

    ingest(ec, laptop_record("ec-1", os_version="24H2", device_type="desktop"))

    assert CategoryReview.objects.get().status == "resolved"


def test_link_and_reclassify_in_one_step(ec, desktop_asset, admin_user, client_for):
    ingest(ec, laptop_record("ec-1"))
    c = ReconciliationCandidate.objects.get(external_id="ec-1")
    laptop = category("workstations-laptop")

    response = client_for(admin_user).post(
        f"/api/v1/reconciliation/{c.pk}/approve/",
        {
            "action": "link",
            "asset": str(desktop_asset.pk),
            "reason": "Same laptop; category corrected",
            "reclassify": True,
            "category": str(laptop.pk),
        },
        format="json",
        HTTP_IF_MATCH=f'"{c.version}"',
    )

    assert response.status_code == 200 and response.json()["status"] == "linked"
    desktop_asset.refresh_from_db()
    assert desktop_asset.category == laptop
    assert not CategoryReview.objects.filter(status="open").exists()


def test_link_and_reclassify_is_all_or_nothing(ec, desktop_asset, admin_user, client_for):
    ingest(ec, laptop_record("ec-1"))
    c = ReconciliationCandidate.objects.get(external_id="ec-1")
    CustomFieldDefinition.objects.create(
        category=category("workstations-laptop"),
        key="battery_model",
        label="Battery model",
        field_type="text",
        required=True,
    )

    response = client_for(admin_user).post(
        f"/api/v1/reconciliation/{c.pk}/approve/",
        {
            "action": "link",
            "asset": str(desktop_asset.pk),
            "reason": "Same laptop",
            "reclassify": True,
            "category": str(category("workstations-laptop").pk),
        },
        format="json",
        HTTP_IF_MATCH=f'"{c.version}"',
    )

    assert response.status_code == 422  # required template field missing
    assert not SourceLink.objects.exists()
    c.refresh_from_db()
    assert c.status == "open"


def test_review_list_scope_and_permissions(
    ec, desktop_asset, admin_user, client_for, make_user, hq, branch
):
    from apps.assets.tests.fixtures import grant

    link(ec, laptop_record("ec-1"), desktop_asset, admin_user)
    review = CategoryReview.objects.get()
    analyst = grant(make_user("analyst.x", roles=["security_analyst"]), hq)
    other = grant(make_user("analyst.y", roles=["security_analyst"]), branch)

    rows = client_for(analyst).get(URL).json()["items"]
    assert [r["id"] for r in rows] == [str(review.pk)]
    assert rows[0]["suggested_category"]["path"] == "Workstations / Laptop"
    assert client_for(other).get(URL).json()["items"] == []
    denied = client_for(analyst).post(
        f"{URL}{review.pk}/dismiss/",
        {"reason": "Not my call"},
        format="json",
        HTTP_IF_MATCH=f'"{review.version}"',
    )
    assert denied.status_code == 403  # needs assets.reclassify
