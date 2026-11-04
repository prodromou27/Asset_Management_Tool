"""Lifecycle catalogue, review, assessment and exceptions through the API (Task 015)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assets.models import Asset, AssetCategory
from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.lifecycle import services
from apps.lifecycle.models import (
    AssetLifecycleMatch,
    LifecycleAlias,
    LifecycleAssessment,
    LifecycleAssessmentHistory,
    LifecycleException,
    LifecycleMilestone,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/lifecycle/"


def day(offset: int) -> str:
    return (services.today_utc() + timedelta(days=offset)).isoformat()


def etag(response) -> dict:
    return {"HTTP_IF_MATCH": response["ETag"]}


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Execute on-commit reassessment hand-offs (Celery runs eagerly in tests)."""

    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def manager(hq, hq_manager, client_for):
    return client_for(hq_manager)


@pytest.fixture
def engineer(make_user, hq, client_for):
    return client_for(grant(make_user("hq.engineer", roles=["infrastructure_engineer"]), hq))


@pytest.fixture
def reader(hq_reader, client_for):
    return client_for(hq_reader)


@pytest.fixture
def assets(hq, branch, switch, laptop, make_asset):
    return {
        "core": make_asset(
            "sw-core-01",
            site=hq,
            category=switch,
            manufacturer="Cisco",
            model="C9300-48P",
            os_name="IOS XE",
            os_version="17.9",
        ),
        "rev": make_asset(
            "sw-acc-02", site=hq, category=switch, manufacturer="Cisco", model="C9300-48P-A"
        ),
        "remote": make_asset(
            "br-sw-01", site=branch, category=switch, manufacturer="Cisco", model="C9300-48P"
        ),
        "laptop": make_asset(
            "lap-01", site=hq, category=laptop, manufacturer="Contoso", model="X1"
        ),
    }


@pytest.fixture
def source(manager):
    response = manager.post(
        f"{URL}sources/",
        {
            "publisher": "Example vendor",
            "title": "End-of-life bulletin EX-123 (fictitious test source)",
            "url": "https://vendor.example/eol/ex-123",
            "source_type": "vendor",
            "collected_on": day(-10),
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    return response.json()


def make_product(client, run, **body):
    body = {"kind": "hardware", "vendor": "Cisco", "name": "C9300-48P", **body}
    response = run(client.post, f"{URL}products/", body, format="json")
    assert response.status_code == 201, response.json()
    return response


def add_date(client, run, product_id, source, milestone_type="end_of_standard_support", offset=60):
    response = run(
        client.post,
        f"{URL}products/{product_id}/milestones/",
        {"milestone_type": milestone_type, "date": day(offset), "source": source["id"]},
        format="json",
    )
    assert response.status_code == 201, response.json()
    return next(
        m
        for m in response.json()["milestones"]
        if m["milestone_type"] == milestone_type and m["date"] == day(offset)
    )


def verify(client, run, milestone, decision="verified", note=""):
    return run(
        client.post,
        f"{URL}milestones/{milestone['id']}/review/",
        {"decision": decision, "note": note},
        format="json",
        HTTP_IF_MATCH=f'"{milestone["version"]}"',
    )


def assessment(asset, dimension="hardware") -> LifecycleAssessment:
    return LifecycleAssessment.objects.get(asset=asset, dimension=dimension)


# --- End-to-end -------------------------------------------------------------------------------


def test_catalogue_to_assessment_flow(manager, run, assets, source):
    product = make_product(manager, run).json()
    core = assets["core"]
    assert assessment(core).status == "unknown"  # product exists, no verified date yet

    milestone = add_date(manager, run, product["id"], source, offset=60)
    assert milestone["verification"] == "pending"
    current = assessment(core)
    assert current.status == "unknown" and "awaiting verification" in " ".join(current.reasons)

    response = verify(manager, run, milestone)
    assert response.status_code == 200 and response.json()["reviewed_by"] == "hq.manager"
    current = assessment(core)
    assert (current.status, current.days_remaining, current.threshold_days) == ("expiring", 60, 90)
    assert current.evidence_quality == "vendor"
    assert str(current.milestone_ids[0]) == milestone["id"]
    core.refresh_from_db()
    assert core.support_status == "expiring"  # worst dimension (OS is unknown, ranked lower)

    detail = manager.get(f"/api/v1/assets/{core.pk}/lifecycle/").json()
    hardware = next(a for a in detail["assessments"] if a["dimension"] == "hardware")
    assert hardware["product"]["label"] == "Cisco C9300-48P"
    assert detail["evidence"][0]["source"]["url"] == "https://vendor.example/eol/ex-123"
    match = next(m for m in detail["matches"] if m["dimension"] == "hardware")
    assert match["method"] == "exact" and match["observed"]["model"]["value"] == "C9300-48P"


def test_manual_asset_data_is_preserved(manager, run, assets, source):
    core = assets["core"]
    before = Asset.objects.values("version", "model", "manufacturer", "notes").get(pk=core.pk)
    product = make_product(manager, run).json()
    verify(manager, run, add_date(manager, run, product["id"], source, offset=-5))
    after = Asset.objects.values("version", "model", "manufacturer", "notes").get(pk=core.pk)
    assert after == before  # only the computed summary changes
    core.refresh_from_db()
    assert core.support_status == "eos"


def test_not_applicable_dimensions(manager, run, hq, make_asset):
    vm = make_asset(
        "vm-01",
        site=hq,
        category=AssetCategory.objects.get(code="servers-virtual-machine"),
        os_name="Ubuntu",
        os_version="24.04",
    )
    screen = make_asset(
        "mon-01",
        site=hq,
        category=AssetCategory.objects.get(code="monitors"),
        manufacturer="Contoso",
        model="M27",
    )
    services.reassess_assets([vm.pk, screen.pk])
    assert assessment(vm, "hardware").status == "not_applicable"
    assert assessment(vm, "os").status == "unknown"
    assert assessment(screen, "os").status == "not_applicable"
    assert assessment(screen, "hardware").status == "unknown"


# --- Review queue -----------------------------------------------------------------------------


def test_candidate_review_with_remembered_alias(
    manager, run, assets, source, hq, switch, make_asset
):
    product = make_product(manager, run).json()
    queue = manager.get(f"{URL}matches/").json()["items"]
    rev = next(m for m in queue if m["asset"]["name"] == "sw-acc-02")
    assert rev["state"] == "candidate" and rev["candidates"][0]["product_id"] == product["id"]
    assert assessment(assets["rev"]).status == "unverified"

    response = manager.post(
        f"{URL}matches/{rev['id']}/approve/",
        {"product": product["id"], "remember_alias": True, "note": "Same model, hardware rev A"},
        format="json",
        HTTP_IF_MATCH=f'"{rev["version"]}"',
    )
    assert response.status_code == 200, response.json()
    assert (response.json()["state"], response.json()["method"]) == ("matched", "manual")
    assert LifecycleAlias.objects.filter(product_id=product["id"], value="C9300-48P-A").exists()

    twin = make_asset(
        "sw-acc-03", site=hq, category=switch, manufacturer="Cisco", model="c9300-48p-a"
    )
    services.reassess_assets([twin.pk])
    match = AssetLifecycleMatch.objects.get(asset=twin, dimension="hardware")
    assert (match.state, match.method) == ("matched", "alias")
    assert AuditEvent.objects.filter(
        action="lifecycle.match.approve", object_id=str(assets["rev"].pk)
    ).exists()


def test_rejecting_a_candidate_is_remembered(manager, run, assets):
    make_product(manager, run)
    rev = AssetLifecycleMatch.objects.get(asset=assets["rev"], dimension="hardware")
    response = manager.post(
        f"{URL}matches/{rev.pk}/reject/",
        {"note": "Different chassis"},
        format="json",
        HTTP_IF_MATCH=f'"{rev.version}"',
    )
    assert response.status_code == 200
    assert response.json()["state"] == "no_match"
    services.reassess_assets([assets["rev"].pk])
    assert AssetLifecycleMatch.objects.get(pk=rev.pk).state == "no_match"
    assert assessment(assets["rev"]).status == "unknown"


def test_approving_a_product_of_another_dimension_is_refused(manager, run, assets):
    os_product = make_product(manager, run, kind="firmware", name="IOS XE", release="17.12").json()
    make_product(manager, run)
    rev = AssetLifecycleMatch.objects.get(asset=assets["rev"], dimension="hardware")
    response = manager.post(
        f"{URL}matches/{rev.pk}/approve/",
        {"product": os_product["id"]},
        format="json",
        HTTP_IF_MATCH=f'"{rev.version}"',
    )
    assert response.status_code == 422


def test_reviewer_decision_is_reset_when_observed_values_change(manager, run, assets):
    product = make_product(manager, run).json()
    rev = AssetLifecycleMatch.objects.get(asset=assets["rev"], dimension="hardware")
    manager.post(
        f"{URL}matches/{rev.pk}/approve/",
        {"product": product["id"]},
        format="json",
        HTTP_IF_MATCH=f'"{rev.version}"',
    )
    Asset.objects.filter(pk=assets["rev"].pk).update(model="C9200-24T")
    services.reassess_assets([assets["rev"].pk])
    rev.refresh_from_db()
    assert rev.state == "no_match" and "Observed values changed" in rev.reason


# --- Reassessment after catalogue changes -------------------------------------------------------


def test_editing_a_product_rematches_assets(manager, run, assets):
    response = make_product(manager, run, name="C9300-48X")
    assert (
        AssetLifecycleMatch.objects.get(asset=assets["core"], dimension="hardware").state
        == "no_match"
    )
    response = run(
        manager.patch,
        f"{URL}products/{response.json()['id']}/",
        {"name": "C9300-48P", "reason": "Typo in model"},
        format="json",
        **etag(response),
    )
    assert response.status_code == 200
    assert (
        AssetLifecycleMatch.objects.get(asset=assets["core"], dimension="hardware").state
        == "matched"
    )


def test_changing_a_verified_date_needs_reverification(manager, run, assets, source):
    product = make_product(manager, run).json()
    milestone = verify(
        manager, run, add_date(manager, run, product["id"], source, offset=300)
    ).json()
    assert assessment(assets["core"]).status == "eol_announced"
    response = run(
        manager.patch,
        f"{URL}milestones/{milestone['id']}/",
        {"date": day(-1), "reason": "Vendor revised bulletin"},
        format="json",
        HTTP_IF_MATCH=f'"{milestone["version"]}"',
    )
    assert response.status_code == 200 and response.json()["verification"] == "pending"
    assert assessment(assets["core"]).status == "unknown"
    history = LifecycleAssessmentHistory.objects.filter(asset=assets["core"], dimension="hardware")
    assert [h.status for h in history.order_by("id")] == ["unknown", "eol_announced", "unknown"]


def test_conflicting_vendor_evidence(manager, run, assets, source):
    product = make_product(manager, run).json()
    other = manager.post(
        f"{URL}sources/",
        {
            "publisher": "Example vendor",
            "title": "Product page",
            "source_type": "vendor",
            "collected_on": day(-1),
        },
        format="json",
    ).json()
    verify(manager, run, add_date(manager, run, product["id"], source, offset=100))
    verify(manager, run, add_date(manager, run, product["id"], other, offset=200))
    current = assessment(assets["core"])
    assert current.status == "unverified" and "Conflicting" in current.reasons[1]


def test_extended_support_scenario(manager, run, assets, source, settings):
    product = make_product(manager, run).json()
    verify(manager, run, add_date(manager, run, product["id"], source, offset=-30))
    verify(
        manager, run, add_date(manager, run, product["id"], source, "end_of_extended_support", 400)
    )
    assert (assessment(assets["core"]).status, assessment(assets["core"]).support_level) == (
        "eos",
        "extended",
    )
    settings.ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT = True
    services.reassess_assets([assets["core"].pk])
    assert assessment(assets["core"]).status == "eol_announced"


# --- Exceptions -------------------------------------------------------------------------------


def test_exception_overrides_effective_status_but_not_evidence(manager, run, assets, source):
    product = make_product(manager, run).json()
    milestone = verify(
        manager, run, add_date(manager, run, product["id"], source, offset=-5)
    ).json()
    core = assets["core"]
    response = manager.post(
        f"/api/v1/assets/{core.pk}/lifecycle/exceptions/",
        {
            "dimension": "hardware",
            "status": "supported",
            "reason": "Isolated lab switch until replacement order lands",
            "compensating_controls": "No internet access; ACL restricted",
            "expires_on": day(30),
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    current = assessment(core)
    assert (current.status, current.effective_status) == ("eos", "supported")
    assert LifecycleMilestone.objects.get(pk=milestone["id"]).date.isoformat() == day(-5)
    core.refresh_from_db()
    assert core.support_status == "unknown"  # OS still unknown; hardware counted as supported

    exc = LifecycleException.objects.get(pk=response.json()["id"])
    LifecycleException.objects.filter(pk=exc.pk).update(
        expires_on=services.today_utc() - timedelta(days=1)
    )
    services.reassess_assets([core.pk])
    assert assessment(core).effective_status == "eos"  # expired: back to the evidence


def test_exception_rules_and_revocation(manager, run, assets):
    core = assets["core"]
    url = f"/api/v1/assets/{core.pk}/lifecycle/exceptions/"
    body = {"dimension": "hardware", "status": "supported", "reason": "Accepted risk for lab use"}
    assert manager.post(url, {**body, "expires_on": day(0)}, format="json").status_code == 422
    assert manager.post(url, {**body, "expires_on": day(400)}, format="json").status_code == 422
    created = manager.post(url, {**body, "expires_on": day(10)}, format="json")
    assert created.status_code == 201
    assert manager.post(url, {**body, "expires_on": day(20)}, format="json").status_code == 409

    revoke = manager.post(
        f"{URL}exceptions/{created.json()['id']}/revoke/",
        {"reason": "Switch replaced"},
        format="json",
        **etag(created),
    )
    assert revoke.status_code == 200 and revoke.json()["active"] is False
    actions = set(
        AuditEvent.objects.filter(object_id=str(core.pk)).values_list("action", flat=True)
    )
    assert {"lifecycle.exception.create", "lifecycle.exception.revoke"} <= actions


# --- Security -----------------------------------------------------------------------------------


def test_permissions(reader, engineer, manager, run, assets, source):
    body = {"kind": "hardware", "vendor": "Cisco", "name": "C9300-48P"}
    assert reader.get(f"{URL}products/").status_code == 200
    assert reader.post(f"{URL}products/", body, format="json").status_code == 403
    assert reader.post(f"{URL}sources/", {}, format="json").status_code == 403

    created = run(engineer.post, f"{URL}products/", body, format="json")
    assert created.status_code == 201  # engineers may propose catalogue data
    milestone = add_date(engineer, run, created.json()["id"], source)
    assert verify(engineer, run, milestone).status_code == 403  # ...but not verify it
    match = AssetLifecycleMatch.objects.get(asset=assets["rev"], dimension="hardware")
    response = engineer.post(
        f"{URL}matches/{match.pk}/approve/",
        {"product": created.json()["id"]},
        format="json",
        HTTP_IF_MATCH=f'"{match.version}"',
    )
    assert response.status_code == 403
    exc_url = f"/api/v1/assets/{assets['core'].pk}/lifecycle/exceptions/"
    exc = {
        "dimension": "hardware",
        "status": "supported",
        "reason": "Not allowed here",
        "expires_on": day(5),
    }
    assert engineer.post(exc_url, exc, format="json").status_code == 403
    assert reader.post(f"/api/v1/assets/{assets['core'].pk}/lifecycle/reassess/").status_code == 403
    assert verify(manager, run, milestone).status_code == 200


def test_cross_site_assets_are_never_exposed(reader, manager, run, assets, source):
    product = make_product(manager, run).json()
    verify(manager, run, add_date(manager, run, product["id"], source, offset=-1))
    remote = assets["remote"]

    names = {f["asset"]["name"] for f in reader.get(f"{URL}findings/").json()["items"]}
    assert "br-sw-01" not in names and "sw-core-01" in names
    assert reader.get(f"/api/v1/assets/{remote.pk}/lifecycle/").status_code == 404
    affected = reader.get(f"{URL}products/{product['id']}/assets/").json()["items"]
    assert [a["asset"]["name"] for a in affected] == ["sw-core-01"]
    listed = next(
        p for p in reader.get(f"{URL}products/").json()["items"] if p["id"] == product["id"]
    )
    assert listed["matched_assets"] == 1  # the branch switch is not counted
    totals = {
        (r["dimension"], r["effective_status"]): r["count"]
        for r in reader.get(f"{URL}summary/").json()
    }
    assert totals[("hardware", "eos")] == 1

    remote_match = AssetLifecycleMatch.objects.get(asset=remote, dimension="hardware")
    response = manager.post(
        f"{URL}matches/{remote_match.pk}/reject/",
        {"note": "not mine to decide"},
        format="json",
        HTTP_IF_MATCH=f'"{remote_match.version}"',
    )
    assert response.status_code == 404  # the HQ manager cannot act on a branch asset
    response = manager.post(
        f"/api/v1/assets/{remote.pk}/lifecycle/exceptions/",
        {
            "dimension": "hardware",
            "status": "supported",
            "reason": "Out of scope test",
            "expires_on": day(5),
        },
        format="json",
    )
    assert response.status_code == 404


def test_audit_and_revision_history(manager, run, assets, source):
    created = make_product(manager, run)
    product = created.json()
    milestone = add_date(manager, run, product["id"], source)
    verify(manager, run, milestone)
    run(
        manager.post,
        f"{URL}products/{product['id']}/aliases/",
        {"kind": "part_number", "value": "C9300-48P-E"},
        format="json",
    )
    revisions = manager.get(f"{URL}products/{product['id']}/revisions/").json()
    assert [r["action"] for r in revisions] == [
        "alias.create",
        "milestone.verified",
        "milestone.create",
        "product.create",
    ]
    assert revisions[0]["snapshot"]["aliases"] == [["part_number", "C9300-48P-E", ""]]
    assert revisions[1]["snapshot"]["milestones"][0]["verification"] == "verified"
    actions = set(
        AuditEvent.objects.filter(object_id=product["id"]).values_list("action", flat=True)
    )
    assert {
        "lifecycle.product.create",
        "lifecycle.milestone.create",
        "lifecycle.milestone.verified",
        "lifecycle.alias.create",
    } <= actions
    assert AuditEvent.objects.filter(action="lifecycle.source.create").exists()


def test_concurrent_modifications_are_rejected(manager, run, source):
    created = make_product(manager, run)
    url = f"{URL}products/{created.json()['id']}/"
    first = manager.patch(
        url, {"family": "Catalyst 9300", "reason": "Add family"}, format="json", **etag(created)
    )
    assert first.status_code == 200
    stale = manager.patch(
        url, {"family": "Other", "reason": "Stale edit"}, format="json", **etag(created)
    )
    assert stale.status_code == 409
    missing = manager.patch(url, {"family": "Other", "reason": "No version"}, format="json")
    assert missing.status_code == 428

    milestone = add_date(manager, run, created.json()["id"], source)
    assert verify(manager, run, milestone).status_code == 200
    assert verify(manager, run, milestone).status_code == 409  # same version reused


def test_duplicate_products_and_aliases_are_refused(manager, run):
    first = make_product(manager, run).json()
    again = manager.post(
        f"{URL}products/",
        {"kind": "hardware", "vendor": "cisco", "name": "c9300-48p"},
        format="json",
    )
    assert again.status_code == 422
    second = make_product(manager, run, name="C9300-24P").json()
    run(
        manager.post,
        f"{URL}products/{first['id']}/aliases/",
        {"kind": "model", "value": "C9300"},
        format="json",
    )
    clash = manager.post(
        f"{URL}products/{second['id']}/aliases/", {"kind": "model", "value": "c9300"}, format="json"
    )
    assert clash.status_code == 422
    wrong_kind = manager.post(
        f"{URL}products/{first['id']}/aliases/", {"kind": "os_name", "value": "x"}, format="json"
    )
    assert wrong_kind.status_code == 422


def test_vendor_alias_enables_matching(manager, run, hq, switch, make_asset):
    make_product(manager, run)
    odd = make_asset(
        "sw-odd", site=hq, category=switch, manufacturer="Cisco Meraki-ish", model="C9300-48P"
    )
    services.reassess_assets([odd.pk])
    assert AssetLifecycleMatch.objects.get(asset=odd, dimension="hardware").state == "no_match"
    response = run(
        manager.post,
        f"{URL}vendor-aliases/",
        {"alias": "Cisco Meraki-ish", "vendor": "Cisco"},
        format="json",
    )
    assert response.status_code == 201
    assert AssetLifecycleMatch.objects.get(asset=odd, dimension="hardware").state == "matched"


def test_support_statement_requires_verified_source(manager, run, assets, source):
    created = make_product(manager, run)
    url = f"{URL}products/{created.json()['id']}/statement/"
    bad = manager.post(url, {"support_statement": "supported"}, format="json", **etag(created))
    assert bad.status_code == 422
    response = run(
        manager.post,
        url,
        {"support_statement": "supported", "statement_source": source["id"], "verify": True},
        format="json",
        **etag(created),
    )
    assert response.status_code == 200
    assert assessment(assets["core"]).status == "supported"


def test_policy_and_reassess_all(manager, reader, run, assets):
    policy = reader.get(f"{URL}policy/").json()
    assert policy["warning_days"] == [180, 90] and policy["count_extended_support"] is False
    assert reader.post(f"{URL}reassess/").status_code == 403
    response = run(manager.post, f"{URL}reassess/")
    assert response.status_code == 202
    assert LifecycleAssessment.objects.filter(asset=assets["laptop"]).count() == 2
    assert AuditEvent.objects.filter(action="lifecycle.reassess").exists()


def test_today_is_a_utc_calendar_date():
    assert services.today_utc() == timezone.now().astimezone(timezone.get_fixed_timezone(0)).date()
