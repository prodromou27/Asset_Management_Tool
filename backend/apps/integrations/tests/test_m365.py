"""Microsoft 365 / Entra license inventory against sanitized Graph fixtures (Task 010).

The Entra token endpoint and Graph are served by httpx.MockTransport (conftest.FakeM365);
nothing contacts a network, and the fake rejects any non-GET request to Graph.
"""

import logging

import pytest

from apps.assets.models import Asset
from apps.assets.tests.fixtures import grant
from apps.integrations import sync
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.licensing.models import (
    DirectoryGroup,
    DirectoryUser,
    LicenseAllocation,
    LicenseSku,
    SubscriptionSnapshot,
)
from apps.licensing.services import user_allocations
from apps.observations.models import Observation
from apps.reconciliation.models import ReconciliationCandidate

from .conftest import INTUNE_SECRET, M365_ROLES, run_sync

pytestmark = pytest.mark.django_db

E3 = "5a1b0000-0000-4000-8000-0000000000e3"
PBI = "5a1b0000-0000-4000-8000-0000000000b1"


def sku(part: str) -> LicenseSku:
    return LicenseSku.objects.get(sku_part_number=part)


def latest(part: str) -> SubscriptionSnapshot:
    return sku(part).snapshots.order_by("-taken_at").first()


def allocation(name: str, part: str, *, active=True) -> LicenseAllocation:
    rows = LicenseAllocation.objects.filter(user__display_name=name, sku__sku_part_number=part)
    if active:
        rows = rows.filter(ended_at__isnull=True)
    return rows.get()


# --- Synchronisation and quantities ---------------------------------------------------------


def test_full_sync_reads_skus_and_paged_users_only(m365, m365_api):
    run = run_sync(m365)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert m365_api.user_pages() == [1, 2, 3]
    assert [r.url.path for r in m365_api.requests][0] == "/v1.0/subscribedSkus"
    select = m365_api.requests[1].url.params["$select"].split(",")
    assert select == [
        "id",
        "userPrincipalName",
        "displayName",
        "accountEnabled",
        "assignedLicenses",
        "licenseAssignmentStates",
    ]
    assert run.api_requests == 5  # token + SKUs + 3 user pages
    # No device records: nothing enters the asset reconciliation pipeline.
    assert run.records_received == 0 and not Observation.objects.exists()
    assert not ReconciliationCandidate.objects.exists() and not Asset.objects.exists()
    m365.refresh_from_db()
    assert m365.status == IntegrationInstance.Status.AVAILABLE


def test_snapshot_keeps_reported_and_counted_quantities_apart(m365, m365_api):
    run_sync(m365)

    s = latest("SPE_E3")
    assert (s.enabled_units, s.consumed_units, s.warning_units) == (50, 6, 0)
    assert (s.assigned_users, s.direct_users, s.group_users) == (6, 4, 3)
    assert s.capability_status == "Enabled" and s.original["accountName"] == "contoso-example"
    assert "servicePlans" not in s.original
    assert sku("SPE_E3").service_plans == ["EXCHANGE_S_ENTERPRISE", "INTUNE_A", "TEAMS1"]
    pbi = latest("POWER_BI_PRO")
    assert (pbi.capability_status, pbi.warning_units, pbi.assigned_users) == ("Warning", 10, 2)
    visio = latest("VISIOCLIENT")
    assert (visio.enabled_units, visio.suspended_units, visio.assigned_users) == (0, 5, 0)


def test_direct_and_group_assignment_is_counted_once(m365, m365_api):
    run_sync(m365)

    cleo = allocation("Cleo", "SPE_E3")
    assert cleo.method == "direct_and_group" and cleo.group_ids == [
        "9a000000-0000-4000-8000-00000000000a"
    ]
    assert len(cleo.paths) == 2
    ivy = allocation("Ivy", "SPE_E3")
    assert ivy.method == "group" and len(ivy.group_ids) == 2
    assert LicenseAllocation.objects.filter(sku__sku_part_number="SPE_E3").count() == 7


def test_assignment_states(m365, m365_api):
    run_sync(m365)

    assert allocation("Dev", "SPE_E3").state == "Error"  # not counted
    assert allocation("Jo", "POWER_BI_PRO").state == "ActiveWithError"  # counted
    hal = allocation("Hal", "SPE_E3")
    assert hal.state == "Unknown" and hal.method == "direct" and hal.paths == []
    assert allocation("Eve", "SPE_E3").user.account_enabled is False


def test_only_licensed_users_and_minimal_identity_are_stored(m365, m365_api):
    run_sync(m365)

    assert not DirectoryUser.objects.filter(display_name="Finn").exists()
    ada = DirectoryUser.objects.get(display_name="Ada")
    assert ada.user_principal_name == "ada@contoso.example"
    assert ada.tenant_id == m365_api.tenant_id
    assert ada.object_id == "c0000000-0000-4000-8000-000000000001"


def test_assigned_sku_missing_from_subscriptions_is_kept(m365, m365_api):
    run_sync(m365)

    old = LicenseSku.objects.get(sku_id="5a1b0000-0000-4000-8000-0000000000aa")
    assert old.subscribed is False and old.sku_part_number == ""
    assert allocation("Gia", "").sku == old
    assert not old.snapshots.exists()  # no quantities reported for it


def test_repeat_sync_confirms_instead_of_duplicating(m365, m365_api):
    run_sync(m365)
    first = latest("SPE_E3")
    allocations = LicenseAllocation.objects.count()

    run_sync(m365)

    assert SubscriptionSnapshot.objects.filter(sku__sku_part_number="SPE_E3").count() == 1
    again = latest("SPE_E3")
    assert again.pk == first.pk and again.last_confirmed_at > first.last_confirmed_at
    assert LicenseAllocation.objects.count() == allocations


def test_changed_purchased_units_keep_history(m365, m365_api):
    run_sync(m365)
    m365_api.sku("SPE_E3")["prepaidUnits"]["enabled"] = 75

    run_sync(m365)

    history = list(sku("SPE_E3").snapshots.order_by("taken_at"))
    assert [s.enabled_units for s in history] == [50, 75]


def test_removed_assignment_is_ended_not_deleted_and_reassignment_opens_a_new_row(m365, m365_api):
    run_sync(m365)
    ada = m365_api.user("Ada")
    ada["licenseAssignmentStates"] = [s for s in ada["licenseAssignmentStates"] if s["skuId"] != E3]
    ada["assignedLicenses"] = [a for a in ada["assignedLicenses"] if a["skuId"] != E3]

    run_sync(m365)

    ended = allocation("Ada", "SPE_E3", active=False)
    assert ended.ended_at is not None
    assert latest("SPE_E3").assigned_users == 5

    ada["licenseAssignmentStates"].append(
        {"skuId": E3, "assignedByGroup": None, "state": "Active", "error": "None"}
    )
    run_sync(m365)

    rows = LicenseAllocation.objects.filter(user__display_name="Ada", sku__sku_part_number="SPE_E3")
    assert rows.count() == 2 and rows.filter(ended_at__isnull=True).count() == 1


def test_assignment_path_change_is_recorded(m365, m365_api):
    run_sync(m365)
    before = allocation("Ben", "SPE_E3")
    m365_api.user("Ben")["licenseAssignmentStates"][0]["assignedByGroup"] = None

    run_sync(m365)

    after = allocation("Ben", "SPE_E3")
    assert after.pk == before.pk and after.method == "direct"
    assert after.changed_at > before.changed_at


def test_incomplete_user_listing_ends_nothing_and_counts_unknown(m365, m365_api):
    run_sync(m365)
    m365_api.overrides["users3"] = (503, {"error": {"code": "ServiceUnavailable"}})
    m365_api.user("Ada")["licenseAssignmentStates"] = []
    m365_api.user("Ada")["assignedLicenses"] = []

    run = run_sync(m365)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert any("stopped after page 2" in s["warning"] for s in run.warning_samples)
    assert not LicenseAllocation.objects.filter(ended_at__isnull=False).exists()
    s = latest("SPE_E3")
    assert s.assigned_users is None and s.enabled_units == 50  # reported values still kept
    assert not DirectoryUser.objects.filter(missing_since__isnull=False).exists()


def test_unsafe_continuation_link_is_not_followed(m365, m365_api):
    m365_api.next_link_base = "https://graph.microsoft.com/v1.0/groups"

    run = run_sync(m365)

    assert m365_api.user_pages() == [1]
    assert any("not followed" in s["warning"] for s in run.warning_samples)
    assert latest("SPE_E3").assigned_users is None


def test_sku_removed_from_a_complete_listing_is_flagged(m365, m365_api):
    run_sync(m365)
    m365_api.skus[:] = [s for s in m365_api.skus if s["skuPartNumber"] != "VISIOCLIENT"]

    run_sync(m365)

    assert sku("VISIOCLIENT").missing_since is not None
    assert sku("SPE_E3").missing_since is None


def test_deleted_user_is_flagged_missing(m365, m365_api):
    run_sync(m365)
    m365_api.users[:] = [u for u in m365_api.users if u["displayName"] != "Eve"]

    run_sync(m365)

    eve = DirectoryUser.objects.get(display_name="Eve")
    assert eve.missing_since is not None
    assert allocation("Eve", "SPE_E3", active=False).ended_at is not None


def test_user_allocations_helper():
    out = user_allocations(
        {
            "licenseAssignmentStates": [
                {"skuId": E3.upper(), "assignedByGroup": "g2", "state": "Disabled"},
                {"skuId": E3, "assignedByGroup": "g1", "state": "Active"},
            ],
            "assignedLicenses": [{"skuId": PBI}],
        }
    )
    assert out[E3]["state"] == "Active" and out[E3]["group_ids"] == ["g1", "g2"]
    assert out[E3]["assigned_directly"] is False
    assert out[PBI] == {"assigned_directly": True, "group_ids": [], "state": "Unknown", "paths": []}


# --- Authentication, throttling -------------------------------------------------------------


def test_403_names_both_read_permissions(m365, m365_api):
    m365_api.overrides["skus"] = (403, {"error": {"code": "Authorization_RequestDenied"}})

    run = run_sync(m365)

    assert run.status == SyncRun.Status.FAILED
    assert "Organization.Read.All and User.Read.All" in run.error_message
    assert not LicenseSku.objects.exists()


def test_rejected_client_credentials(m365, m365_api):
    m365_api.overrides["token"] = (
        400,
        {"error": "unauthorized_client", "error_description": "AADSTS700016: App not found."},
    )

    run = run_sync(m365)

    assert run.status == SyncRun.Status.FAILED and "AADSTS700016" in run.error_message
    assert m365_api.requests == []


def test_expired_token_is_renewed_and_429_is_retried(m365, m365_api, monkeypatch):
    m365_api.overrides["users2"] = [
        (429, {"error": {"code": "TooManyRequests"}}, {"Retry-After": "9"}),
        None,
    ]
    original = m365_api.handler

    def expire_after_skus(request):
        response = original(request)
        if request.url.path == "/v1.0/subscribedSkus":
            m365_api.expire_tokens()
        return response

    monkeypatch.setattr(m365_api, "handler", expire_after_skus)

    run = run_sync(m365)

    assert run.status == SyncRun.Status.SUCCEEDED and 9.0 in m365_api.sleeps
    assert len(m365_api.token_forms) == 2 and m365_api.user_pages() == [1, 1, 2, 2, 3]


# --- Connection test, configuration and API ----------------------------------------------------


def test_connection_test_reports_permissions(client_for, admin_user, m365, m365_api):
    m365_api.roles = [*M365_ROLES, "User.ReadWrite.All"]

    body = client_for(admin_user).post(f"/api/v1/integrations/{m365.pk}/test/").json()

    assert body["ok"] is True and body["capabilities"]["excess_permissions"] is True
    assert body["capabilities"]["permission_read_all"] is True
    assert "User.ReadWrite.All" in body["message"]


def test_missing_permission_is_reported(client_for, admin_user, m365, m365_api):
    m365_api.roles = ["Organization.Read.All"]

    body = client_for(admin_user).post(f"/api/v1/integrations/{m365.pk}/test/").json()

    assert body["capabilities"]["permission_read_all"] is False
    assert "does not list User.Read.All" in body["message"]


def test_configuration_defaults(client_for, admin_user, hq, live, m365_api):
    created = client_for(admin_user).post(
        "/api/v1/integrations/",
        {
            "source": "m365",
            "name": "M365",
            "default_site": str(hq.pk),
            "tenant_id": m365_api.tenant_id,
            "client_id": m365_api.client_id,
        },
        format="json",
    )
    data = created.json()
    assert created.status_code == 201 and data["base_url"] == "https://graph.microsoft.com"
    assert data["connector"]["permissions"] == M365_ROLES
    assert data["sync_interval_minutes"] == 1440


def test_subscription_api(client_for, admin_user, m365, m365_api):
    run_sync(m365)
    client = client_for(admin_user)

    rows = client.get("/api/v1/licenses/subscriptions/").json()
    e3 = next(r for r in rows if r["sku_part_number"] == "SPE_E3")
    assert e3["latest"]["available_units"] == 44 and e3["latest"]["assigned_users"] == 6
    assert e3["instance"]["name"] == "Microsoft 365" and e3["freshness"] == "fresh"
    assert e3["tenant_id"] == m365_api.tenant_id

    detail = client.get(f"/api/v1/licenses/subscriptions/{e3['id']}/").json()
    assert len(detail["snapshots"]) == 1 and "TEAMS1" in detail["service_plans"]

    page = client.get("/api/v1/licenses/allocations/", {"sku": e3["id"]}).json()
    assert page["count"] == 7
    group = client.get("/api/v1/licenses/allocations/", {"sku": e3["id"], "method": "group"}).json()
    assert {r["user"]["display_name"] for r in group["items"]} == {"Ben", "Dev", "Ivy"}
    both = client.get(
        "/api/v1/licenses/allocations/", {"sku": e3["id"], "method": "direct_and_group"}
    ).json()
    assert [r["user"]["display_name"] for r in both["items"]] == ["Cleo"]
    found = client.get("/api/v1/licenses/allocations/", {"q": "ivy@"}).json()
    assert [r["user"]["display_name"] for r in found["items"]] == ["Ivy"]
    bad = client.get("/api/v1/licenses/allocations/", {"sku": "not-a-uuid"}).json()
    assert bad["count"] == 0


def test_license_api_requires_licenses_view(client_for, make_user, hq, m365, m365_api):
    run_sync(m365)
    manager = grant(make_user("itam.mgr", roles=["itam_manager"]), hq)
    auditor = make_user("auditor.one", roles=["auditor"])
    reader = grant(make_user("reader.one", roles=["read_only"]), hq)
    analyst = grant(make_user("analyst.one", roles=["security_analyst"]), hq)

    for user in (manager, auditor):
        assert client_for(user).get("/api/v1/licenses/subscriptions/").status_code == 200
    for user in (reader, analyst):
        assert client_for(user).get("/api/v1/licenses/subscriptions/").status_code == 403
        assert client_for(user).get("/api/v1/licenses/allocations/").status_code == 403


def test_secret_and_tokens_never_logged(m365, m365_api, caplog, client_for, admin_user):
    caplog.set_level(logging.DEBUG)
    run_sync(m365)
    body = client_for(admin_user).get(f"/api/v1/integrations/{m365.pk}/").content.decode()
    for text in (caplog.text, body):
        assert INTUNE_SECRET not in text
        assert all(token not in text for token in m365_api.valid_tokens)


def test_scheduler_includes_m365(m365, monkeypatch):
    monkeypatch.setattr("apps.integrations.tasks.run_sync_task.delay", lambda run_id: None)

    assert sync.dispatch_due() == 1 and SyncRun.objects.get().instance == m365


# --- Optional group names ------------------------------------------------------------------

SALES = "9a000000-0000-4000-8000-00000000000a"
IT = "9a000000-0000-4000-8000-00000000000b"
SEC = "9a000000-0000-4000-8000-00000000000c"


def group_requests(server) -> list[str]:
    return [r.url.path for r in server.requests if r.url.path.startswith("/v1.0/groups/")]


def test_group_names_are_not_read_without_the_optional_permission(m365, m365_api):
    run_sync(m365)

    assert group_requests(m365_api) == []
    assert not DirectoryGroup.objects.exists()


def test_group_names_are_read_with_the_optional_permission(m365, m365_api, client_for, admin_user):
    m365_api.roles = [*M365_ROLES, "GroupMember.Read.All"]

    run = run_sync(m365)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert sorted(group_requests(m365_api)) == [f"/v1.0/groups/{g}" for g in (SALES, IT, SEC)]
    names = dict(DirectoryGroup.objects.values_list("object_id", "display_name"))
    assert names == {SALES: "Licensing - Sales", IT: "Licensing - IT staff"}  # SEC: deleted
    found = client_for(admin_user).get("/api/v1/licenses/allocations/", {"q": "ivy@"}).json()
    groups = {g["id"]: g["display_name"] for g in found["items"][0]["groups"]}
    assert groups == {SALES: "Licensing - Sales", IT: "Licensing - IT staff"}
    cleo = client_for(admin_user).get("/api/v1/licenses/allocations/", {"q": "cleo@"}).json()
    sec = [g for r in cleo["items"] for g in r["groups"] if g["id"] == SEC]
    assert sec == [{"id": SEC, "display_name": None}]
    test = client_for(admin_user).post(f"/api/v1/integrations/{m365.pk}/test/").json()
    assert test["capabilities"]["group_names"] is True
    assert test["capabilities"]["excess_permissions"] is False


def test_refused_group_reads_only_warn(m365, m365_api):
    m365_api.roles = [*M365_ROLES, "GroupMember.Read.All"]
    m365_api.overrides["groups"] = (403, {"error": {"code": "Authorization_RequestDenied"}})

    run = run_sync(m365)

    assert run.status == SyncRun.Status.SUCCEEDED
    assert len(group_requests(m365_api)) == 1  # stops after the first refusal
    assert any("Group names not read" in s["warning"] for s in run.warning_samples)
    assert latest("SPE_E3").assigned_users == 6


def test_subscription_list_query_count_does_not_grow_with_skus(
    m365, m365_api, client_for, admin_user, django_assert_max_num_queries
):
    run_sync(m365)
    client = client_for(admin_user)
    client.get("/api/v1/licenses/subscriptions/")  # warm the session

    with django_assert_max_num_queries(8):
        rows = client.get("/api/v1/licenses/subscriptions/").json()

    assert len(rows) == 6  # 5 subscribed + 1 assigned-only SKU
