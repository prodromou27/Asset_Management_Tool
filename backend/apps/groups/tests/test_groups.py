"""Static and dynamic asset groups (Task 012, docs/03, docs/11, docs/15 A07)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assets.models import Asset, AssetCategory
from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.groups import rules, services
from apps.groups.models import AssetGroup, AssetGroupMembership
from apps.reconciliation.models import SourceLink
from apps.reconciliation.tests.conftest import Req, make_instance

pytestmark = pytest.mark.django_db
URL = "/api/v1/groups/"


def names(qs) -> set[str]:
    return set(qs.values_list("name", flat=True))


def matching(rule) -> set[str]:
    return names(Asset.objects.filter(rules.compile_rule(rules.validate(rule))))


def cond(field, operator, value):
    return {"field": field, "operator": operator, "value": value}


@pytest.fixture
def fleet(make_asset, hq, branch, switch, laptop, admin_user):
    desktop = AssetCategory.objects.get(code="workstations-desktop")
    return {
        "sw1": make_asset(
            "sw-core-01",
            site=hq,
            category=switch,
            manufacturer="Cisco",
            model="C9300",
            business_status="deployed",
        ),
        "sw2": make_asset(
            "sw-br-01",
            site=branch,
            category=switch,
            manufacturer="Cisco",
            model="C9200",
            business_status="deployed",
        ),
        "lt1": make_asset(
            "LT-0042",
            site=hq,
            category=laptop,
            manufacturer="Dell",
            business_status="assigned",
            owner=admin_user,
            hostnames=[{"hostname": "lt-0042.corp.example"}],
        ),
        "dt1": make_asset(
            "DT-0107", site=hq, category=desktop, manufacturer="HP", business_status="in_stock"
        ),
    }


# --- Rule validation and semantics ---------------------------------------------------------


@pytest.mark.parametrize(
    "rule, message",
    [
        ({"field": "password", "operator": "eq", "value": "x"}, "Unknown field"),
        (cond("manufacturer", "before", "x"), "supports"),
        (cond("business_status", "eq", "stolen"), "Expected one of"),
        (cond("category", "eq", "not-a-uuid"), "Expected an ID"),
        (cond("created_at", "after", "yesterday"), "Expected a date"),
        (cond("manufacturer", "in", []), "list of 1 to"),
        ({"op": "xor", "rules": []}, "Unknown combinator"),
        ({"op": "and", "rules": []}, "needs 1 to"),
        (cond("site", "eq", None), "Expected an ID"),  # site is never empty
    ],
)
def test_invalid_rules_are_rejected(rule, message):
    with pytest.raises(rules.RuleError) as exc:
        rules.validate(rule)
    assert message in exc.value.message


def test_size_and_depth_limits():
    deep = cond("manufacturer", "eq", "x")
    for _ in range(6):
        deep = {"op": "not", "rule": deep}
    with pytest.raises(rules.RuleError, match="nested"):
        rules.validate(deep)
    wide = {"op": "or", "rules": [{"op": "and", "rules": [cond("model", "eq", "x")] * 5}] * 4}
    with pytest.raises(rules.RuleError, match="at most 50 parts"):
        rules.validate({"op": "and", "rules": [wide, wide]})


def test_rule_semantics(fleet, hq, switch, admin_user):
    workstations = AssetCategory.objects.get(code="workstations")
    assert matching(cond("category", "eq", str(workstations.pk))) == {"LT-0042", "DT-0107"}
    assert matching(cond("site", "eq", str(hq.pk))) == {"sw-core-01", "LT-0042", "DT-0107"}
    assert matching(cond("manufacturer", "eq", "cisco")) == {"sw-core-01", "sw-br-01"}
    assert matching(cond("model", "contains", "92")) == {"sw-br-01"}
    assert matching(cond("manufacturer", "in", ["HP", "Dell"])) == {"LT-0042", "DT-0107"}
    assert matching(cond("model", "eq", None)) == {"LT-0042", "DT-0107"}  # not set
    assert matching(cond("business_status", "in", ["assigned", "in_stock"])) == {
        "LT-0042",
        "DT-0107",
    }
    assert matching(cond("owner", "eq", None)) == {"sw-core-01", "sw-br-01", "DT-0107"}
    assert matching(cond("owner", "eq", str(admin_user.pk))) == {"LT-0042"}
    assert matching(cond("hostname", "contains", "LT-00")) == {"LT-0042"}
    combined = {
        "op": "and",
        "rules": [
            cond("category", "eq", str(switch.pk)),
            {"op": "not", "rule": cond("site", "eq", str(hq.pk))},
        ],
    }
    assert matching(combined) == {"sw-br-01"}
    either = {"op": "or", "rules": [cond("manufacturer", "eq", "HP"), cond("model", "eq", "C9300")]}
    assert matching(either) == {"DT-0107", "sw-core-01"}
    Asset.objects.filter(pk=fleet["dt1"].pk).update(archived_at=timezone.now())
    assert matching(cond("manufacturer", "eq", "HP")) == set()  # archived never match


def test_dates_sources_and_membership(fleet, hq):
    Asset.objects.filter(pk=fleet["sw2"].pk).update(created_at=timezone.now() - timedelta(days=400))
    cutoff = (timezone.now() - timedelta(days=30)).date().isoformat()
    assert matching(cond("created_at", "before", cutoff)) == {"sw-br-01"}
    assert "sw-br-01" not in matching(cond("created_at", "after", cutoff))

    nms = make_instance("NMS", "fixture", hq)
    now = timezone.now()
    for asset, seen in ((fleet["sw1"], now), (fleet["lt1"], now - timedelta(days=60))):
        SourceLink.objects.create(
            instance=nms,
            external_id=asset.name,
            asset=asset,
            first_seen_at=seen,
            last_seen_at=seen,
            method=SourceLink.Method.APPROVED_CANDIDATE,
        )
    assert matching(cond("source", "eq", str(nms.pk))) == {"sw-core-01", "LT-0042"}
    assert matching(cond("last_seen", "before", cutoff)) == {"LT-0042"}
    assert matching(cond("last_seen", "after", cutoff)) == {"sw-core-01"}

    group = AssetGroup.objects.create(name="Pilot", kind="static")
    AssetGroupMembership.objects.create(
        group=group, asset=fleet["dt1"], source="explicit", added_at=now
    )
    assert matching(cond("member_of", "eq", str(group.pk))) == {"DT-0107"}


# --- Dynamic groups through the API --------------------------------------------------------


def test_dynamic_group_lifecycle(fleet, admin_user, client_for):
    client = client_for(admin_user)
    rule = cond("manufacturer", "eq", "Cisco")

    preview = client.post(f"{URL}preview/", {"rule": rule}, format="json").json()
    assert preview["count"] == 2 and {a["name"] for a in preview["sample"]} == {
        "sw-core-01",
        "sw-br-01",
    }

    created = client.post(
        URL, {"name": "Cisco switches", "kind": "dynamic", "rule": rule}, format="json"
    )
    assert created.status_code == 201
    group = created.json()
    assert group["member_count"] == 2 and group["rule_version"] == 1
    assert group["last_evaluated_at"]
    assert AuditEvent.objects.filter(action="groups.create").exists()
    assert AuditEvent.objects.filter(action="groups.evaluate").exists()

    narrowed = {"op": "and", "rules": [rule, cond("model", "eq", "C9300")]}
    diff = client.post(f"{URL}{group['id']}/preview/", {"rule": narrowed}, format="json").json()
    assert (diff["count"], diff["would_add"], diff["would_remove"]) == (1, 0, 1)

    no_reason = client.patch(
        f"{URL}{group['id']}/",
        {"rule": narrowed},
        format="json",
        HTTP_IF_MATCH=f'"{group["version"]}"',
    )
    assert no_reason.status_code == 422 and "reason" in no_reason.json()["error"]["field_errors"]
    updated = client.patch(
        f"{URL}{group['id']}/",
        {"rule": narrowed, "reason": "Only the 9300 refresh"},
        format="json",
        HTTP_IF_MATCH=f'"{group["version"]}"',
    ).json()
    assert updated["rule_version"] == 2 and updated["member_count"] == 1

    history = client.get(f"{URL}{group['id']}/assets/", {"history": "true"}).json()["items"]
    removed = next(m for m in history if m["asset"]["name"] == "sw-br-01")
    assert removed["removed_reason"] == "No longer matches rule version 2"
    assert removed["source"] == "evaluated" and removed["rule_version"] == 1
    versions = client.get(f"{URL}{group['id']}/rule-versions/").json()
    assert [v["number"] for v in versions] == [2, 1] and versions[0][
        "reason"
    ] == "Only the 9300 refresh"


def test_dynamic_groups_follow_asset_changes(fleet, admin_user):
    group = services.create_group(
        Req(admin_user), {"name": "HP", "kind": "dynamic", "rule": cond("manufacturer", "eq", "HP")}
    )
    assert names(
        Asset.objects.filter(
            group_memberships__group=group, group_memberships__removed_at__isnull=True
        )
    ) == {"DT-0107"}
    Asset.objects.filter(pk=fleet["dt1"].pk).update(manufacturer="Lenovo")
    Asset.objects.filter(pk=fleet["lt1"].pk).update(manufacturer="HP")

    assert services.evaluate_all() == 1

    active = AssetGroupMembership.objects.filter(group=group, removed_at__isnull=True)
    assert names(Asset.objects.filter(pk__in=active.values("asset"))) == {"LT-0042"}


def test_nested_rules_evaluate_in_dependency_order(fleet, admin_user):
    request = Req(admin_user)
    cisco = services.create_group(
        request, {"name": "Cisco", "kind": "dynamic", "rule": cond("manufacturer", "eq", "Cisco")}
    )
    deployed_cisco = services.create_group(
        request,
        {
            "name": "Deployed Cisco",
            "kind": "dynamic",
            "rule": {
                "op": "and",
                "rules": [
                    cond("member_of", "eq", str(cisco.pk)),
                    cond("business_status", "eq", "deployed"),
                ],
            },
        },
    )
    Asset.objects.filter(pk=fleet["dt1"].pk).update(
        manufacturer="Cisco", business_status="deployed"
    )

    services.evaluate_all()

    members = AssetGroupMembership.objects.filter(group=deployed_cisco, removed_at__isnull=True)
    assert names(Asset.objects.filter(pk__in=members.values("asset"))) == {
        "sw-core-01",
        "sw-br-01",
        "DT-0107",
    }


def test_circular_references_and_parents_are_rejected(fleet, admin_user, client_for):
    client = client_for(admin_user)
    a = client.post(URL, {"name": "A", "kind": "static"}, format="json").json()
    b = client.post(
        URL,
        {"name": "B", "kind": "dynamic", "rule": cond("member_of", "eq", a["id"])},
        format="json",
    ).json()
    c = client.post(
        URL,
        {"name": "C", "kind": "dynamic", "rule": cond("member_of", "eq", b["id"])},
        format="json",
    ).json()
    loop = client.patch(
        f"{URL}{b['id']}/",
        {"rule": cond("member_of", "eq", c["id"]), "reason": "Loop it"},
        format="json",
        HTTP_IF_MATCH=f'"{b["version"]}"',
    )
    assert loop.status_code == 422 and "circular" in str(loop.json())

    child = client.post(
        URL, {"name": "Child", "kind": "static", "parent": a["id"]}, format="json"
    ).json()
    cycle = client.patch(
        f"{URL}{a['id']}/",
        {"parent": child["id"]},
        format="json",
        HTTP_IF_MATCH=f'"{a["version"]}"',
    )
    assert cycle.status_code == 422 and "parent" in cycle.json()["error"]["field_errors"]


def test_archive_is_blocked_while_referenced(fleet, admin_user, client_for):
    client = client_for(admin_user)
    base = client.post(URL, {"name": "Base", "kind": "static"}, format="json").json()
    client.post(
        URL,
        {"name": "Uses base", "kind": "dynamic", "rule": cond("member_of", "eq", base["id"])},
        format="json",
    )

    blocked = client.post(
        f"{URL}{base['id']}/archive/",
        {"reason": "Obsolete"},
        format="json",
        HTTP_IF_MATCH=f'"{base["version"]}"',
    )
    assert blocked.status_code == 409 and "Uses base" in blocked.json()["error"]["message"]

    other = client.post(URL, {"name": "Temp", "kind": "static"}, format="json").json()
    done = client.post(
        f"{URL}{other['id']}/archive/",
        {"reason": "Obsolete"},
        format="json",
        HTTP_IF_MATCH=f'"{other["version"]}"',
    )
    assert done.status_code == 204
    assert "Temp" not in {g["name"] for g in client.get(URL).json()}
    # The name is free again after archiving.
    assert client.post(URL, {"name": "Temp", "kind": "static"}, format="json").status_code == 201


# --- Static membership, RBAC and site scope -------------------------------------------------


def test_static_members_with_audited_removals(fleet, admin_user, client_for):
    client = client_for(admin_user)
    group = client.post(URL, {"name": "Refresh 2027", "kind": "static"}, format="json").json()
    members = f"{URL}{group['id']}/members/"

    added = client.post(
        members,
        {"add": [str(fleet["lt1"].pk), str(fleet["dt1"].pk)], "reason": "Out of warranty"},
        format="json",
    ).json()
    assert added == {"added": 2, "removed": 0}
    again = client.post(members, {"add": [str(fleet["lt1"].pk)]}, format="json").json()
    assert again == {"added": 0, "removed": 0}  # idempotent

    no_reason = client.post(members, {"remove": [str(fleet["dt1"].pk)]}, format="json")
    assert no_reason.status_code == 422
    removed = client.post(
        members, {"remove": [str(fleet["dt1"].pk)], "reason": "Replaced already"}, format="json"
    ).json()
    assert removed == {"added": 0, "removed": 1}

    rows = client.get(f"{URL}{group['id']}/assets/", {"history": "1"}).json()["items"]
    gone = next(r for r in rows if r["asset"]["name"] == "DT-0107")
    assert (
        gone["removed_reason"] == "Replaced already" and gone["removed_by"] == admin_user.username
    )
    assert AuditEvent.objects.filter(action="groups.members").count() == 2
    groups_of_laptop = client.get(f"/api/v1/assets/{fleet['lt1'].pk}/groups/").json()
    assert [g["name"] for g in groups_of_laptop] == ["Refresh 2027"]

    dynamic = client.post(
        URL,
        {"name": "Dyn", "kind": "dynamic", "rule": cond("manufacturer", "eq", "HP")},
        format="json",
    ).json()
    refused = client.post(
        f"{URL}{dynamic['id']}/members/", {"add": [str(fleet["sw1"].pk)]}, format="json"
    )
    assert refused.status_code == 409


def test_groups_never_widen_access(fleet, admin_user, client_for, make_user, hq):
    """docs/15 A07: a group with members in two sites shows each user only their site."""
    services.create_group(
        Req(admin_user),
        {"name": "All Cisco", "kind": "dynamic", "rule": cond("manufacturer", "eq", "Cisco")},
    )
    reader = grant(make_user("reader.hq", roles=["read_only"]), hq)
    client = client_for(reader)

    (group,) = client.get(URL).json()
    assert group["member_count"] == 1
    items = client.get(f"{URL}{group['id']}/assets/").json()["items"]
    assert [m["asset"]["name"] for m in items] == ["sw-core-01"]
    assert client.get(f"/api/v1/assets/{fleet['sw2'].pk}/").status_code == 404
    assert client.get(f"/api/v1/assets/{fleet['sw2'].pk}/groups/").status_code == 404


def test_role_permissions(fleet, make_user, hq, branch, client_for, admin_user):
    group = services.create_group(Req(admin_user), {"name": "Static", "kind": "static"})
    reader = grant(make_user("reader.r", roles=["read_only"]), hq)
    operator = grant(make_user("operator.o", roles=["asset_operator"]), hq)

    assert client_for(reader).get(URL).status_code == 200
    assert (
        client_for(reader).post(URL, {"name": "X", "kind": "static"}, format="json").status_code
        == 403
    )
    assert (
        client_for(reader)
        .post(f"{URL}{group.pk}/members/", {"add": [str(fleet["sw1"].pk)]}, format="json")
        .status_code
        == 403
    )
    assert (
        client_for(operator).post(URL, {"name": "X", "kind": "static"}, format="json").status_code
        == 403
    )
    ok = client_for(operator).post(
        f"{URL}{group.pk}/members/", {"add": [str(fleet["sw1"].pk)]}, format="json"
    )
    assert ok.status_code == 200
    other_site = client_for(operator).post(
        f"{URL}{group.pk}/members/", {"add": [str(fleet["sw2"].pk)]}, format="json"
    )
    assert other_site.status_code == 422  # cannot add assets outside one's sites


def test_kind_cannot_change_and_static_has_no_rule(admin_user, client_for):
    client = client_for(admin_user)
    bad = client.post(
        URL, {"name": "S", "kind": "static", "rule": cond("model", "eq", "x")}, format="json"
    )
    assert bad.status_code == 422
    missing = client.post(URL, {"name": "D", "kind": "dynamic"}, format="json")
    assert missing.status_code == 422
    group = client.post(URL, {"name": "S", "kind": "static"}, format="json").json()
    change = client.patch(
        f"{URL}{group['id']}/",
        {"kind": "dynamic"},
        format="json",
        HTTP_IF_MATCH=f'"{group["version"]}"',
    )
    assert change.status_code == 422
    dupe = client.post(URL, {"name": "s", "kind": "static"}, format="json")
    assert dupe.status_code == 422


def test_field_catalogue(admin_user, client_for):
    fields = {f["field"]: f for f in client_for(admin_user).get(f"{URL}fields/").json()}
    assert fields["category"]["ref"] == "category" and fields["category"]["operators"] == [
        "eq",
        "in",
    ]
    assert fields["created_at"]["operators"] == ["before", "after"]
    assert {c["value"] for c in fields["business_status"]["choices"]} >= {"deployed", "in_stock"}
    assert "password" not in fields
