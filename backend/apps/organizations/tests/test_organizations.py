import pytest

from apps.audit.models import AuditEvent
from apps.organizations.models import Department, Location, Site, UserSiteGrant

pytestmark = pytest.mark.django_db


@pytest.fixture
def hq(db):
    return Site.objects.create(code="HQ", name="Headquarters")


def test_only_site_managers_can_create_sites(client_for, make_user):
    manager = make_user("itam.mgr", roles=["itam_manager"], all_sites=True)

    response = client_for(manager).post(
        "/api/v1/sites/", {"code": "NEW", "name": "New"}, format="json"
    )

    assert response.status_code == 403
    assert not Site.objects.filter(code="NEW").exists()


def test_create_site_normalizes_code_and_audits(client_for, admin_user):
    response = client_for(admin_user).post(
        "/api/v1/sites/", {"code": " lim-01 ", "name": "Limassol"}, format="json"
    )

    assert response.status_code == 201, response.json()
    assert response.json()["code"] == "LIM-01"
    assert AuditEvent.objects.filter(action="sites.create").exists()


def test_site_code_unique(client_for, admin_user, hq):
    response = client_for(admin_user).post(
        "/api/v1/sites/", {"code": "hq", "name": "Dup"}, format="json"
    )

    assert response.status_code == 422
    assert "code" in response.json()["error"]["field_errors"]


def test_site_parent_cycle_rejected(client_for, admin_user, hq):
    child = Site.objects.create(code="HQ-1", name="Child", parent=hq)

    response = client_for(admin_user).patch(
        f"/api/v1/sites/{hq.pk}/", {"parent": str(child.pk)}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 422


def test_site_patch_version_guard(client_for, admin_user, hq):
    client = client_for(admin_user)

    assert client.patch(f"/api/v1/sites/{hq.pk}/", {"name": "X"}, format="json").status_code == 428
    assert (
        client.patch(
            f"/api/v1/sites/{hq.pk}/", {"name": "X"}, format="json", HTTP_IF_MATCH='"5"'
        ).status_code
        == 409
    )
    ok = client.patch(f"/api/v1/sites/{hq.pk}/", {"name": "X"}, format="json", HTTP_IF_MATCH='"1"')
    assert ok.status_code == 200 and ok.json()["version"] == 2


def test_location_hierarchy_stays_within_site(client_for, admin_user, hq):
    other = Site.objects.create(code="BR", name="Branch")
    building = Location.objects.create(site=hq, name="Building A", kind="building")
    client = client_for(admin_user)

    nested = client.post(
        "/api/v1/locations/",
        {"site": str(hq.pk), "parent": str(building.pk), "name": "Floor 1", "kind": "floor"},
        format="json",
    )
    assert nested.status_code == 201, nested.json()
    cross = client.post(
        "/api/v1/locations/",
        {"site": str(other.pk), "parent": str(building.pk), "name": "Bad"},
        format="json",
    )
    assert cross.status_code == 422
    dup = client.post(
        "/api/v1/locations/",
        {"site": str(hq.pk), "parent": str(building.pk), "name": "floor 1"},
        format="json",
    )
    assert dup.status_code == 422


def test_departments_unique_and_audited(client_for, admin_user):
    client = client_for(admin_user)

    assert (
        client.post("/api/v1/departments/", {"name": "Finance"}, format="json").status_code == 201
    )
    assert (
        client.post("/api/v1/departments/", {"name": "finance"}, format="json").status_code == 422
    )
    assert Department.objects.count() == 1
    assert AuditEvent.objects.filter(action="departments.create").exists()


def test_admin_assigns_user_site_access_with_audit(client_for, admin_user, make_user, hq):
    target = make_user("site.user", roles=["read_only"])

    response = client_for(admin_user).patch(
        f"/api/v1/users/{target.pk}/",
        {"site_ids": [str(hq.pk)], "all_sites": False},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 200, response.json()
    assert [s["code"] for s in response.json()["sites"]] == ["HQ"]
    assert list(UserSiteGrant.objects.filter(user=target).values_list("site__code", flat=True)) == [
        "HQ"
    ]
    event = AuditEvent.objects.get(action="users.update")
    assert event.before["sites"] == [] and event.after["sites"] == ["HQ"]


def test_unknown_site_in_grant_rejected(client_for, admin_user, make_user):
    target = make_user("site.user", roles=["read_only"])

    response = client_for(admin_user).patch(
        f"/api/v1/users/{target.pk}/",
        {"site_ids": ["00000000-0000-4000-8000-000000000000"]},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 422


def test_user_lookup_is_minimal_and_permissioned(client_for, make_user, admin_user):
    reader = make_user("just.reader", roles=["read_only"])
    operator = make_user("op.erator", roles=["asset_operator"])
    make_user("gone.person", is_active=False)

    assert client_for(reader).get("/api/v1/users/lookup/").status_code == 403
    rows = client_for(operator).get("/api/v1/users/lookup/").json()
    assert {r["username"] for r in rows} == {"admin.one", "just.reader", "op.erator"}
    assert set(rows[0]) == {"id", "username", "display_name"}


def test_bootstrap_admin_gets_all_sites(monkeypatch):
    import io

    from django.core.management import call_command

    from apps.accounts.models import User

    monkeypatch.setattr("sys.stdin", io.StringIO("Bootstrap-Strong-Pass-1\n"))
    call_command(
        "bootstrap_admin",
        "--username=ops.admin",
        "--display-name=Ops",
        "--password-stdin",
        stdout=io.StringIO(),
    )

    assert User.objects.get(username="ops.admin").all_sites is True
