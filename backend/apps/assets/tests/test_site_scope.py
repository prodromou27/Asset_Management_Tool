"""Cross-site access denial (closes ASM-04). Every path must deny out-of-scope assets."""

import pytest

from apps.assets import selectors
from apps.assets.models import Asset, AssetHistoryEntry
from apps.organizations.models import UserSiteGrant

from .fixtures import grant

pytestmark = pytest.mark.django_db
ASSETS = "/api/v1/assets/"


@pytest.fixture
def hq_asset(make_asset, hq, switch):
    return make_asset("hq-switch", site=hq, category=switch, asset_tag="HQ-0001")


@pytest.fixture
def branch_asset(make_asset, branch, switch):
    return make_asset("branch-switch", site=branch, category=switch, asset_tag="BR-0001")


def names(response):
    return sorted(item["name"] for item in response.json()["items"])


def test_list_only_shows_granted_sites(client_for, hq_operator, hq_asset, branch_asset):
    response = client_for(hq_operator).get(ASSETS)

    assert response.status_code == 200
    assert names(response) == ["hq-switch"]
    assert response.json()["count"] == 1


def test_parent_site_grant_includes_child_sites(client_for, hq_operator, hq_dc, make_asset, switch):
    make_asset("dc-switch", site=hq_dc, category=switch)

    assert names(client_for(hq_operator).get(ASSETS)) == ["dc-switch"]


def test_all_sites_user_sees_everything(client_for, admin_user, hq_asset, branch_asset):
    assert names(client_for(admin_user).get(ASSETS)) == ["branch-switch", "hq-switch"]


def test_user_without_grants_sees_nothing(client_for, make_user, hq_asset):
    nobody = make_user("no.sites", roles=["read_only"])

    response = client_for(nobody).get(ASSETS)

    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.parametrize(
    "query",
    ["?site={branch}", "?q=branch", "?q=BR-0001", "?archived=include", "?category={category}"],
)
def test_filters_cannot_widen_scope(
    client_for, hq_operator, hq_asset, branch_asset, branch, switch, query
):
    url = ASSETS + query.format(branch=branch.pk, category=switch.pk)

    response = client_for(hq_operator).get(url)

    assert "branch-switch" not in names(response)


@pytest.mark.parametrize("suffix", ["", "history/"])
def test_out_of_scope_detail_is_404(client_for, hq_operator, branch_asset, suffix):
    response = client_for(hq_operator).get(f"{ASSETS}{branch_asset.pk}/{suffix}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("method", "suffix", "payload", "user_fixture"),
    [
        ("patch", "", {"name": "pwned"}, "hq_operator"),
        ("post", "archive/", {"reason": "cross-site attempt"}, "hq_manager"),
        ("post", "restore/", None, "hq_manager"),
        ("post", "classification/", {"category": None, "reason": "cross-site"}, "hq_manager"),
        ("post", "classification/preview/", {"category": None}, "hq_manager"),
    ],
)
def test_out_of_scope_mutations_are_404_and_change_nothing(
    request, client_for, branch_asset, laptop, method, suffix, payload, user_fixture
):
    user = request.getfixturevalue(user_fixture)
    if payload and "category" in payload:
        payload["category"] = str(laptop.pk)
    history_before = AssetHistoryEntry.objects.filter(asset=branch_asset).count()

    response = getattr(client_for(user), method)(
        f"{ASSETS}{branch_asset.pk}/{suffix}", payload, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 404
    branch_asset.refresh_from_db()
    assert branch_asset.name == "branch-switch" and branch_asset.version == 1
    assert AssetHistoryEntry.objects.filter(asset=branch_asset).count() == history_before


def test_cannot_create_in_unauthorized_site(client_for, hq_operator, branch, switch):
    response = client_for(hq_operator).post(
        ASSETS,
        {"name": "sneaky", "site": str(branch.pk), "category": str(switch.pk)},
        format="json",
    )

    assert response.status_code == 422
    assert "site" in response.json()["error"]["field_errors"]
    assert not Asset.objects.filter(name="sneaky").exists()


def test_unknown_and_unauthorized_site_errors_are_identical(
    client_for, hq_operator, branch, switch
):
    client = client_for(hq_operator)

    def error_for(site_id):
        payload = {"name": "x", "site": site_id, "category": str(switch.pk)}
        return client.post(ASSETS, payload, format="json").json()["error"]["field_errors"]["site"]

    unknown = error_for("00000000-0000-4000-8000-000000000000")
    forbidden = error_for(str(branch.pk))
    assert [m.split('"')[0] for m in unknown] == [m.split('"')[0] for m in forbidden]


def test_cannot_reassign_asset_to_unauthorized_site(client_for, hq_operator, hq_asset, branch):
    response = client_for(hq_operator).patch(
        f"{ASSETS}{hq_asset.pk}/", {"site": str(branch.pk)}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 422
    hq_asset.refresh_from_db()
    assert hq_asset.site.code == "HQ"


def test_cannot_use_location_from_unauthorized_site(
    client_for, hq_operator, hq, switch, branch_room
):
    response = client_for(hq_operator).post(
        ASSETS,
        {
            "name": "x",
            "site": str(hq.pk),
            "category": str(switch.pk),
            "location": str(branch_room.pk),
        },
        format="json",
    )

    assert response.status_code == 422
    assert "location" in response.json()["error"]["field_errors"]


def test_revoking_grant_applies_on_next_request(client_for, hq_operator, hq_asset):
    client = client_for(hq_operator)
    assert client.get(f"{ASSETS}{hq_asset.pk}/").status_code == 200

    UserSiteGrant.objects.filter(user=hq_operator).delete()

    assert client.get(f"{ASSETS}{hq_asset.pk}/").status_code == 404


def test_selector_is_the_single_scoped_entry_point(hq_operator, hq_asset, branch_asset):
    """Future export/report jobs must use visible_assets(); it must never leak."""
    visible = set(selectors.visible_assets(hq_operator).values_list("name", flat=True))

    assert visible == {"hq-switch"}


def test_site_list_is_scoped_for_non_managers(client_for, hq_reader, hq, branch, hq_dc):
    codes = [s["code"] for s in client_for(hq_reader).get("/api/v1/sites/").json()]

    assert codes == ["HQ", "HQ-DC"]


def test_locations_list_is_scoped(client_for, hq_reader, hq_room, branch_room):
    rows = client_for(hq_reader).get("/api/v1/locations/").json()

    assert [r["name"] for r in rows] == ["Server room"]


def test_grant_on_multiple_sites(client_for, make_user, hq, branch, hq_asset, branch_asset):
    user = grant(make_user("two.sites", roles=["read_only"]), hq, branch)

    assert names(client_for(user).get(ASSETS)) == ["branch-switch", "hq-switch"]
