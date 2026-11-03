import pytest

from apps.assets.models import SavedView
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db
VIEWS = "/api/v1/saved-views/"
BODY = {
    "name": "Core switches",
    "filters": {"q": "core", "business_status": "deployed"},
    "columns": ["name", "site", "last_seen", "sources"],
    "ordering": "name",
}


def test_requires_asset_view(api_client, client_for, make_user):
    assert api_client.get(VIEWS).status_code == 401
    nobody = make_user("no.perms", roles=[])
    assert client_for(nobody).get(VIEWS).status_code == 403


def test_create_personal_view_and_audit(client_for, hq_reader):
    response = client_for(hq_reader).post(VIEWS, BODY, format="json")

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["is_mine"] is True and body["is_shared"] is False and body["owner"] == "hq.reader"
    assert body["filters"] == {"q": "core", "business_status": "deployed"}
    assert AuditEvent.objects.filter(action="saved_views.create").exists()


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"filters": {"password": "x"}}, "filters"),
        ({"columns": ["name", "salary"]}, "columns.1"),
        ({"columns": ["site"]}, "columns"),
        ({"columns": ["name", "name"]}, "columns"),
        ({"ordering": "random()"}, "ordering"),
        ({"name": "  "}, "name"),
    ],
)
def test_validation(client_for, hq_reader, override, field):
    response = client_for(hq_reader).post(VIEWS, {**BODY, **override}, format="json")

    assert response.status_code == 422
    assert field in response.json()["error"]["field_errors"]


def test_names_unique_per_owner_case_insensitive(client_for, hq_reader, hq_operator):
    client_for(hq_reader).post(VIEWS, BODY, format="json")

    dup = client_for(hq_reader).post(VIEWS, {**BODY, "name": "CORE SWITCHES"}, format="json")
    other_owner = client_for(hq_operator).post(VIEWS, BODY, format="json")

    assert dup.status_code == 422
    assert other_owner.status_code == 201


def test_sharing_needs_edit_rights(client_for, hq_reader, hq_operator):
    assert (
        client_for(hq_reader).post(VIEWS, {**BODY, "is_shared": True}, format="json").status_code
        == 403
    )
    assert (
        client_for(hq_operator).post(VIEWS, {**BODY, "is_shared": True}, format="json").status_code
        == 201
    )


def test_visibility_and_owner_only_changes(client_for, hq_operator, hq_reader):
    owner = client_for(hq_operator)
    shared = owner.post(VIEWS, {**BODY, "is_shared": True}, format="json").json()
    private = owner.post(VIEWS, {**BODY, "name": "Mine only"}, format="json").json()
    reader = client_for(hq_reader)

    listed = {v["name"]: v["is_mine"] for v in reader.get(VIEWS).json()}
    assert listed == {"Core switches": False}

    assert (
        reader.patch(
            f"{VIEWS}{shared['id']}/", {"name": "x"}, format="json", HTTP_IF_MATCH='"1"'
        ).status_code
        == 403
    )
    assert reader.delete(f"{VIEWS}{shared['id']}/").status_code == 403
    assert (
        reader.patch(
            f"{VIEWS}{private['id']}/", {"name": "x"}, format="json", HTTP_IF_MATCH='"1"'
        ).status_code
        == 404
    )


def test_update_needs_if_match_and_delete(client_for, hq_reader):
    client = client_for(hq_reader)
    view = client.post(VIEWS, BODY, format="json").json()
    url = f"{VIEWS}{view['id']}/"

    assert client.patch(url, {"ordering": "-name"}, format="json").status_code == 428
    assert (
        client.patch(url, {"ordering": "-name"}, format="json", HTTP_IF_MATCH='"9"').status_code
        == 409
    )
    ok = client.patch(url, {"ordering": "-name"}, format="json", HTTP_IF_MATCH='"1"')
    assert ok.status_code == 200 and ok.json()["version"] == 2
    assert client.delete(url).status_code == 204
    assert not SavedView.objects.exists()
    assert AuditEvent.objects.filter(action="saved_views.delete").exists()


def test_shared_view_filters_never_widen_scope(
    client_for, hq_operator, branch_operator, make_asset, hq, branch, switch
):
    """A view's filters are re-applied through visible_assets() for each viewer."""
    make_asset("hq-core", site=hq, category=switch)
    make_asset("branch-core", site=branch, category=switch)
    client_for(hq_operator).post(
        VIEWS,
        {
            "name": "Everything core",
            "is_shared": True,
            "filters": {"q": "core", "site": str(branch.pk)},
        },
        format="json",
    )

    view = client_for(branch_operator).get(VIEWS).json()[0]
    as_branch = client_for(branch_operator).get("/api/v1/assets/", view["filters"]).json()
    as_hq = client_for(hq_operator).get("/api/v1/assets/", view["filters"]).json()

    assert [a["name"] for a in as_branch["items"]] == ["branch-core"]
    assert as_hq["count"] == 0
