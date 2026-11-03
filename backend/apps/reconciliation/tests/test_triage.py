"""Reconciliation queue triage: assignment, filters, ordering, bulk hold/reject (Task 011)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.reconciliation.models import ReconciliationCandidate, SourceLink

from .conftest import grant, ingest, make_instance, switch_record

pytestmark = pytest.mark.django_db
LIST = "/api/v1/discovery/candidates/"


def candidate(external_id):
    return ReconciliationCandidate.objects.get(external_id=external_id, status__in=["open", "held"])


@pytest.fixture
def queue(nms):
    for n in range(1, 5):
        ingest(nms, switch_record(f"sw-{n}", serial=f"SN{n}", hostname=f"sw-{n}", interfaces=[]))
    return nms


def test_assign_and_filter_by_assignee(queue, admin_user, client_for):
    client = client_for(admin_user)
    c = candidate("sw-1")

    no_version = client.post(
        f"/api/v1/reconciliation/{c.pk}/assign/", {"assignee": str(admin_user.pk)}, format="json"
    )
    assert no_version.status_code == 428

    assigned = client.post(
        f"/api/v1/reconciliation/{c.pk}/assign/",
        {"assignee": str(admin_user.pk)},
        format="json",
        HTTP_IF_MATCH=f'"{c.version}"',
    ).json()
    assert assigned["assignee"]["username"] == admin_user.username and assigned["assigned_at"]
    assert AuditEvent.objects.filter(action="reconciliation.assign").exists()

    mine = client.get(LIST, {"assignee": "me"}).json()["items"]
    assert [r["external_id"] for r in mine] == ["sw-1"]
    unassigned = client.get(LIST, {"assignee": "none"}).json()["items"]
    assert {r["external_id"] for r in unassigned} == {"sw-2", "sw-3", "sw-4"}


def test_assignee_must_be_able_to_decide_in_the_site(
    queue, admin_user, client_for, make_user, branch
):
    reader = grant(make_user("reader.z", roles=["read_only"]), queue.default_site)
    elsewhere = grant(make_user("mgr.branch", roles=["itam_manager"]), branch)
    c = candidate("sw-1")
    client = client_for(admin_user)

    for user in (reader, elsewhere):
        response = client.post(
            f"/api/v1/reconciliation/{c.pk}/assign/",
            {"assignee": str(user.pk)},
            format="json",
            HTTP_IF_MATCH=f'"{c.version}"',
        )
        assert response.status_code == 422
        assert "assignee" in response.json()["error"]["field_errors"]

    names = [
        u["username"]
        for u in client.get(
            "/api/v1/reconciliation/assignees/", {"site": str(queue.default_site_id)}
        ).json()
    ]
    assert admin_user.username in names and "mgr.branch" not in names and "reader.z" not in names


def test_filters_and_ordering(queue, admin_user, client_for, hq):
    ReconciliationCandidate.objects.filter(external_id="sw-1").update(
        created_at=timezone.now() - timedelta(days=10)
    )
    ReconciliationCandidate.objects.filter(external_id="sw-3").update(score=90)
    client = client_for(admin_user)

    old = client.get(LIST, {"older_than_days": 7}).json()["items"]
    assert [r["external_id"] for r in old] == ["sw-1"]
    found = client.get(LIST, {"q": "sw-4"}).json()["items"]
    assert [r["external_id"] for r in found] == ["sw-4"]
    assert client.get(LIST, {"site": str(hq.pk)}).json()["count"] == 4
    assert client.get(LIST, {"site": "not-a-uuid"}).json()["count"] == 0
    oldest = client.get(LIST, {"ordering": "oldest"}).json()["items"]
    assert oldest[0]["external_id"] == "sw-1"
    by_score = client.get(LIST, {"ordering": "score"}).json()["items"]
    assert by_score[0]["external_id"] == "sw-3"


def test_bulk_hold_and_reject_with_versions(queue, admin_user, client_for):
    client = client_for(admin_user)
    c1, c2, c3 = candidate("sw-1"), candidate("sw-2"), candidate("sw-3")

    response = client.post(
        "/api/v1/reconciliation/bulk/",
        {
            "action": "reject",
            "reason": "Lab switches, not inventory",
            "items": [
                {"id": str(c1.pk), "version": c1.version},
                {"id": str(c2.pk), "version": c2.version + 5},  # stale view
                {"id": "00000000-0000-4000-8000-000000000000", "version": 1},
            ],
        },
        format="json",
    )

    results = {r["id"]: r for r in response.json()}
    assert response.status_code == 200
    assert results[str(c1.pk)]["ok"] is True
    assert results[str(c2.pk)]["ok"] is False and "changed" in results[str(c2.pk)]["error"]
    assert results["00000000-0000-4000-8000-000000000000"]["error"] == "Candidate not found."
    c1.refresh_from_db()
    c2.refresh_from_db()
    assert c1.status == "rejected" and c2.status == "open"
    assert AuditEvent.objects.filter(action="reconciliation.reject").count() == 1

    held = client.post(
        "/api/v1/reconciliation/bulk/",
        {
            "action": "hold",
            "reason": "Waiting for site survey",
            "items": [{"id": str(c3.pk), "version": c3.version}],
        },
        format="json",
    ).json()
    assert held[0]["ok"] is True and candidate("sw-3").status == "held"
    assert not SourceLink.objects.exists()  # bulk never links or creates


def test_bulk_assign_and_validation(queue, admin_user, client_for):
    client = client_for(admin_user)
    items = [{"id": str(c.pk), "version": c.version} for c in ReconciliationCandidate.objects.all()]

    no_reason = client.post(
        "/api/v1/reconciliation/bulk/", {"action": "reject", "items": items}, format="json"
    )
    assert no_reason.status_code == 422

    assigned = client.post(
        "/api/v1/reconciliation/bulk/",
        {"action": "assign", "assignee": str(admin_user.pk), "items": items},
        format="json",
    ).json()
    assert all(r["ok"] for r in assigned) and len(assigned) == 4
    assert ReconciliationCandidate.objects.filter(assignee=admin_user).count() == 4


def test_bulk_needs_decide_permission_and_site_scope(queue, make_user, client_for, branch, hq):
    viewer = grant(make_user("viewer.q", roles=["security_analyst"]), hq)
    other_site = make_instance("NMS Branch", "fixture", branch)
    ingest(other_site, switch_record("br-1", serial="BR1", hostname="br-1", interfaces=[]))
    manager = grant(make_user("mgr.hq", roles=["itam_manager"]), hq)
    branch_c = candidate("br-1")

    assert (
        client_for(viewer)
        .post(
            "/api/v1/reconciliation/bulk/",
            {"action": "hold", "reason": "x" * 6, "items": []},
            format="json",
        )
        .status_code
        == 403
    )
    out = (
        client_for(manager)
        .post(
            "/api/v1/reconciliation/bulk/",
            {
                "action": "hold",
                "reason": "Not ours",
                "items": [{"id": str(branch_c.pk), "version": branch_c.version}],
            },
            format="json",
        )
        .json()
    )
    assert out == [{"id": str(branch_c.pk), "ok": False, "error": "Candidate not found."}]
