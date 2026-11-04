"""License products, entitlements and allocations (Task 016b, ASM-55, docs/06, docs/11)."""

from datetime import date, timedelta
from unittest import mock

import pytest

from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.imports.tests.test_imports import commit, csv_bytes, preview, upload
from apps.licensing.models import EntitlementAllocation, LicenseEntitlement, LicenseProduct
from apps.software.models import SoftwareInstallation, SoftwareProduct, SoftwareVersion

pytestmark = pytest.mark.django_db
URL = "/api/v1/licenses/"
TODAY = date(2026, 11, 4)


@pytest.fixture(autouse=True)
def fixed_today():
    with (
        mock.patch("apps.licensing.entitlements.today_utc", return_value=TODAY),
        mock.patch("apps.licensing.entitlement_views.today_utc", return_value=TODAY),
    ):
        yield


@pytest.fixture
def admin(admin_user, client_for):
    return client_for(admin_user)


@pytest.fixture
def hq_licenses(make_user, hq):
    """ITAM manager limited to HQ: may manage licenses, sees only HQ assets."""
    return grant(make_user("hq.licenses", roles=["itam_manager"]), hq)


def product(client, **body):
    body = {"publisher": "Example Software Corp", "name": "Example CAD", "metric": "user", **body}
    response = client.post(f"{URL}products/", body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def entitlement(client, product_id, **body):
    body = {"product": product_id, "reference": "PO-1001", "quantity": 10, **body}
    response = client.post(f"{URL}entitlements/", body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def allocate(client, entitlement_id, **body):
    return client.post(f"{URL}entitlements/{entitlement_id}/allocations/", body, format="json")


def detail(client, product_id):
    return client.get(f"{URL}products/{product_id}/").json()


# --- Permissions ------------------------------------------------------------------------------


def test_view_and_manage_permissions(admin, client_for, auditor_user, hq_reader):
    p = product(admin)
    auditor = client_for(auditor_user)
    assert auditor.get(f"{URL}products/").status_code == 200
    assert auditor.post(f"{URL}products/", {"name": "X"}, format="json").status_code == 403
    assert (
        auditor.post(
            f"{URL}entitlements/", {"product": p["id"], "reference": "R", "quantity": 1}
        ).status_code
        == 403
    )
    reader = client_for(hq_reader)  # no licenses.view
    assert reader.get(f"{URL}products/").status_code == 403
    assert reader.get(f"{URL}entitlement-allocations/").status_code == 403


# --- Products and entitlements ----------------------------------------------------------------


def test_products_are_unique_and_edited_with_if_match(admin):
    p = product(admin, sku="ECAD-1Y")
    duplicate = admin.post(
        f"{URL}products/",
        {"publisher": " example software corp ", "name": "EXAMPLE  CAD", "sku": "ecad-1y"},
        format="json",
    )
    assert duplicate.status_code == 422
    assert product(admin, sku="ECAD-3Y")["sku"] == "ECAD-3Y"  # another SKU is another product

    url = f"{URL}products/{p['id']}/"
    assert admin.patch(url, {"metric": "device"}, format="json").status_code == 428
    assert (
        admin.patch(url, {"metric": "device"}, format="json", HTTP_IF_MATCH='"9"').status_code
        == 409
    )
    changed = admin.patch(url, {"metric": "device"}, format="json", HTTP_IF_MATCH='"1"')
    assert changed.status_code == 200 and changed.json()["metric"] == "device"
    assert changed.headers["ETag"] == '"2"'
    assert AuditEvent.objects.filter(action="license.product.update", object_id=p["id"]).exists()


def test_entitlement_rules_and_status(admin):
    p = product(admin)
    e = entitlement(admin, p["id"], starts_on="2026-01-01", ends_on="2026-12-31", owner="Eng")
    assert (e["status"], e["allocated"], e["available"]) == ("active", 0, 10)
    assert e["source"] == "manual"

    again = admin.post(
        f"{URL}entitlements/",
        {"product": p["id"], "reference": " po-1001 ", "quantity": 5},
        format="json",
    )
    assert again.status_code == 422 and "reference" in again.json()["error"]["field_errors"]
    backwards = admin.post(
        f"{URL}entitlements/",
        {
            "product": p["id"],
            "reference": "PO-2",
            "quantity": 5,
            "starts_on": "2026-05-01",
            "ends_on": "2026-04-01",
        },
        format="json",
    )
    assert backwards.status_code == 422
    zero = admin.post(
        f"{URL}entitlements/", {"product": p["id"], "reference": "PO-3", "quantity": 0}
    )
    assert zero.status_code in (400, 422)

    entitlement(admin, p["id"], reference="OLD", quantity=4, ends_on="2026-10-31")
    entitlement(admin, p["id"], reference="NEXT", quantity=6, starts_on="2027-01-01")
    statuses = {
        x["reference"]: x["status"]
        for x in admin.get(f"{URL}entitlements/", {"product": p["id"]}).json()["items"]
    }
    assert statuses == {"PO-1001": "active", "OLD": "expired", "NEXT": "not_started"}

    def refs(**params):
        rows = admin.get(f"{URL}entitlements/", params).json()["items"]
        return sorted(x["reference"] for x in rows)

    assert refs(status="expired") == ["OLD"]
    assert refs(status="not_started") == ["NEXT"]
    assert refs(status="ending") == ["PO-1001"]  # ends within 90 days
    assert refs(q="eng") == ["PO-1001"]

    totals = detail(admin, p["id"])
    assert (totals["purchased"], totals["entitlements_in_term"]) == (10, 1)  # only in term

    url = f"{URL}entitlements/{e['id']}/"
    updated = admin.patch(url, {"quantity": 12}, format="json", HTTP_IF_MATCH='"1"')
    assert updated.status_code == 200 and updated.json()["quantity"] == 12
    assert admin.patch(url, {"quantity": 13}, format="json", HTTP_IF_MATCH='"1"').status_code == 409


# --- Allocations and totals -------------------------------------------------------------------


def test_allocations_totals_and_site_scope(
    admin, client_for, hq_licenses, hq, branch, switch, make_asset
):
    hq_asset = make_asset("ws-hq-01", site=hq, category=switch)
    branch_asset = make_asset("ws-br-01", site=branch, category=switch)
    p = product(admin)
    e = entitlement(admin, p["id"], quantity=2)

    manager = client_for(hq_licenses)
    assert allocate(manager, e["id"], asset=str(hq_asset.pk)).status_code == 201
    assert allocate(manager, e["id"], asset=str(branch_asset.pk)).status_code == 404  # not visible
    assert allocate(manager, e["id"], asset=str(hq_asset.pk)).status_code == 409  # duplicate
    both = allocate(manager, e["id"], asset=str(hq_asset.pk), user_name="someone")
    assert both.status_code == 422
    user = allocate(manager, e["id"], user_name="  a.user@example.test ", units=1)
    assert user.status_code == 201 and user.json()["user_name"] == "a.user@example.test"
    assert allocate(manager, e["id"], user_name="A.USER@example.test").status_code == 409

    assert allocate(admin, e["id"], asset=str(branch_asset.pk), units=3).status_code == 201

    totals = detail(manager, p["id"])
    # Over-allocation is recorded and shown, not blocked and not judged.
    assert (totals["purchased"], totals["allocated"], totals["available"]) == (2, 5, -3)
    assert detail(manager, p["id"])["entitlements"][0]["available"] == -3

    seen = manager.get(f"{URL}entitlement-allocations/").json()["items"]
    assert sorted(r["asset"]["name"] if r["asset"] else r["user_name"] for r in seen) == [
        "a.user@example.test",
        "ws-hq-01",
    ]  # the branch allocation is counted but not listed
    admin_rows = admin.get(f"{URL}entitlement-allocations/", {"target": "asset"}).json()["items"]
    assert len(admin_rows) == 2
    branch_row = next(r for r in admin_rows if r["asset"]["name"] == "ws-br-01")
    assert (
        manager.post(
            f"{URL}entitlement-allocations/{branch_row['id']}/end/",
            {"reason": "Moved away"},
            format="json",
        ).status_code
        == 404
    )

    ended = admin.post(
        f"{URL}entitlement-allocations/{branch_row['id']}/end/",
        {"reason": "Moved away"},
        format="json",
    )
    assert ended.status_code == 200 and ended.json()["ended_at"]
    assert detail(admin, p["id"])["allocated"] == 2
    with_ended = admin.get(f"{URL}entitlement-allocations/", {"include_ended": "true"})
    assert len(with_ended.json()["items"]) == 3
    assert EntitlementAllocation.objects.count() == 3  # ended, never deleted
    assert AuditEvent.objects.filter(action="license.allocation.create").count() == 3
    assert AuditEvent.objects.filter(action="license.allocation.end").count() == 1


def test_expired_and_retired_entitlements(admin, hq, switch, make_asset):
    asset = make_asset("ws-hq-01", site=hq, category=switch)
    p = product(admin)
    old = entitlement(admin, p["id"], reference="OLD", ends_on="2026-10-31")
    assert allocate(admin, old["id"], asset=str(asset.pk)).status_code == 409

    e = entitlement(admin, p["id"], reference="NEW", quantity=5)
    allocate(admin, e["id"], asset=str(asset.pk), units=2)
    url = f"{URL}entitlements/{e['id']}/retire/"
    assert admin.post(url, {"reason": "Contract cancelled"}, format="json").status_code == 428
    retired = admin.post(
        url, {"reason": "Contract cancelled"}, format="json", HTTP_IF_MATCH='"1"'
    ).json()
    assert retired["status"] == "retired" and retired["allocated"] == 0
    assert EntitlementAllocation.objects.get().ended_reason.startswith("Entitlement retired")
    totals = detail(admin, p["id"])
    assert (totals["purchased"], totals["allocated"]) == (0, 0)
    assert (
        admin.patch(
            f"{URL}entitlements/{e['id']}/", {"quantity": 9}, format="json", HTTP_IF_MATCH='"2"'
        ).status_code
        == 409
    )
    assert LicenseEntitlement.objects.count() == 2  # retired, not deleted


def test_observed_assets_from_linked_software(
    admin, client_for, hq_licenses, hq, branch, switch, make_asset
):
    sw = SoftwareProduct.objects.create(
        publisher="Example Software Corp",
        publisher_key="example software corp",
        name="Example CAD",
        name_key="example cad",
    )
    v1 = SoftwareVersion.objects.create(product=sw, version="1.0", version_key="1.0")
    v2 = SoftwareVersion.objects.create(product=sw, version="2.0", version_key="2.0")
    now = date.today()
    hq_asset = make_asset("ws-hq-01", site=hq, category=switch)
    for asset, version in (
        (hq_asset, v1),
        (hq_asset, v2),  # two versions on one asset count once
        (make_asset("ws-br-01", site=branch, category=switch), v1),
    ):
        SoftwareInstallation.objects.create(
            asset=asset,
            version=version,
            raw_name="Example CAD",
            first_seen_at=f"{now}T00:00:00Z",
            last_seen_at=f"{now}T00:00:00Z",
        )
    p = product(admin, software_product=sw.pk)
    assert p["software_product"]["name"] == "Example CAD"
    assert detail(admin, p["id"])["observed_assets"] == 2
    assert detail(client_for(hq_licenses), p["id"])["observed_assets"] == 1  # in your sites
    assert product(admin, name="Unlinked")["observed_assets"] is None


# --- Import and export ------------------------------------------------------------------------


def test_entitlement_import_creates_updates_and_rolls_back(admin):
    header = ["publisher", "product", "sku", "metric", "reference", "quantity", "ends_on"]
    content = csv_bytes(
        [
            header,
            ["Example Software Corp", "Example CAD", "ECAD-1Y", "user", "PO-1", "25", "2027-01-31"],
            ["Example Software Corp", "Example CAD", "ECAD-1Y", "", "PO-2", "5", ""],
            ["Example Software Corp", "Example CAD", "ECAD-1Y", "", "PO-1", "30", ""],  # dup
            ["", "Viewer", "", "seat", "PO-3", "1", ""],  # bad metric
            ["", "Viewer", "", "", "PO-4", "", ""],  # quantity missing
            ["", "Viewer", "", "", "PO-5", "2", "31/01/2027"],  # bad date
        ]
    )
    job = preview(admin, upload(admin, "license_entitlement", content, "e.csv").json())
    totals = job["totals"]
    assert (totals["create"], totals["conflict"], totals["error"]) == (2, 1, 3)
    commit(admin, job, key="ent-1")
    p = LicenseProduct.objects.get()
    assert (p.sku, p.metric) == ("ECAD-1Y", "user")
    first = LicenseEntitlement.objects.get(reference="PO-1")
    assert (first.quantity, first.ends_on, first.source) == (25, date(2027, 1, 31), "import")

    update = csv_bytes(
        [
            ["publisher", "product", "sku", "reference", "quantity"],
            ["example software corp", "EXAMPLE CAD", "ecad-1y", "po-1", "40"],
            ["Example Software Corp", "Example CAD", "ECAD-1Y", "PO-2", "5"],
        ]
    )
    job = preview(admin, upload(admin, "license_entitlement", update, "u.csv").json(), "upsert")
    assert (job["totals"]["update"], job["totals"]["skip"]) == (1, 1)
    job = commit(admin, job, key="ent-2").json()
    first.refresh_from_db()
    assert first.quantity == 40

    rolled = admin.post(
        f"/api/v1/imports/{job['id']}/rollback/",
        {"reason": "Wrong file"},
        format="json",
        HTTP_IF_MATCH=f'"{job["version"]}"',
    ).json()
    assert rolled["totals"]["rollback"] == {"rolled_back": 1, "needs_correction": 0}
    first.refresh_from_db()
    assert first.quantity == 25


def test_entitlement_import_needs_manage_permission(client_for, auditor_user, make_user):
    importer = make_user("importer", roles=["asset_operator"])  # imports.run, no licenses.manage
    content = csv_bytes([["product", "reference", "quantity"], ["CAD", "PO-1", "1"]])
    assert upload(client_for(importer), "license_entitlement", content, "e.csv").status_code == 403


def test_entitlement_export_hides_allocations_outside_scope(
    admin,
    client_for,
    hq_licenses,
    hq,
    branch,
    switch,
    make_asset,
    django_capture_on_commit_callbacks,
):
    import csv
    import io
    import zipfile

    p = product(admin)
    e = entitlement(admin, p["id"], quantity=3, owner="Eng lead")
    allocate(admin, e["id"], asset=str(make_asset("ws-hq-01", site=hq, category=switch).pk))
    allocate(admin, e["id"], asset=str(make_asset("ws-br-01", site=branch, category=switch).pk))

    client = client_for(hq_licenses)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            "/api/v1/exports/",
            {
                "family": "license_entitlements",
                "format": "csv",
                "scope": "all",
                "related": ["allocations"],
            },
            format="json",
        )
    assert response.status_code == 202, response.json()
    content = client.get(f"/api/v1/exports/{response.json()['id']}/download/").content
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = archive.namelist()

    def read(suffix):
        name = next(n for n in names if n.endswith(suffix))
        return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))

    main = read("license_entitlements.csv")
    assert main[0]["allocated"] == "2" and main[0]["owner"] == "Eng lead"
    assert [r["asset_name"] for r in read("allocations.csv")] == ["ws-hq-01"]


def test_today_is_used_for_status(admin):
    p = product(admin)
    e = entitlement(admin, p["id"], ends_on=str(TODAY))
    assert e["status"] == "active"  # the last day is still in term
    e2 = entitlement(admin, p["id"], reference="R2", starts_on=str(TODAY + timedelta(days=1)))
    assert e2["status"] == "not_started"
