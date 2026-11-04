"""CSV/XLSX imports with preview and guarded upsert (Task 013, docs/11, docs/15 A13/A23)."""

import csv
import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.assets.models import Asset, FieldLock
from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.groups.models import AssetGroup, AssetGroupMembership
from apps.imports import parsing, services
from apps.imports.models import ImportJob
from apps.organizations.models import Location

pytestmark = pytest.mark.django_db
URL = "/api/v1/imports/"


def csv_bytes(rows: list[list[str]], delimiter=",", bom=True) -> bytes:
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter).writerows(rows)
    return (("﻿" if bom else "") + out.getvalue()).encode("utf-8")


def upload(client, family: str, content: bytes, name="assets.csv"):
    return client.post(
        URL, {"family": family, "file": SimpleUploadedFile(name, content)}, format="multipart"
    )


def preview(client, job: dict, mode=None, mapping=None):
    if mode or mapping:
        body = {**({"mode": mode} if mode else {}), **({"mapping": mapping} if mapping else {})}
        job = client.patch(
            f"{URL}{job['id']}/", body, format="json", HTTP_IF_MATCH=f'"{job["version"]}"'
        ).json()
    return client.post(f"{URL}{job['id']}/preview/", HTTP_IF_MATCH=f'"{job["version"]}"').json()


def commit(client, job: dict, key="key-1"):
    return client.post(
        f"{URL}{job['id']}/commit/", HTTP_IF_MATCH=f'"{job["version"]}"', HTTP_X_IDEMPOTENCY_KEY=key
    )


def rows(client, job_id, **params):
    return client.get(f"{URL}{job_id}/rows/", params).json()["items"]


HEADER = ["asset_tag", "name", "category", "site", "manufacturer", "model", "Serial", "status"]


@pytest.fixture
def admin(admin_user, client_for):
    return client_for(admin_user)


@pytest.fixture
def setup(hq, branch, switch, laptop):
    return {"hq": hq, "branch": branch}


# --- Templates and parsing ---------------------------------------------------------------------


def test_templates_and_download(admin):
    templates = {t["code"]: t for t in admin.get(f"{URL}templates/").json()}
    assert set(templates) == {"asset", "location", "group", "group_membership"}
    asset = templates["asset"]
    assert asset["version"] == 1 and asset["custom_columns"] is True and asset["allowed"] is True
    assert "never used for matching" in asset["match_help"]
    response = admin.get(f"{URL}templates/asset/csv/")
    assert response["Content-Disposition"].endswith('asset-import-template-v1.csv"')
    text = response.content.decode("utf-8-sig").splitlines()
    assert text[0].startswith("id,asset_tag,name,category,site")


def test_upload_detects_format_and_suggests_mapping(admin, setup):
    content = csv_bytes(
        [HEADER, ["IT-1", "=cmd()", "switch", "HQ", "Cisco", "C9300", "S1", "x"]], delimiter=";"
    )
    job = upload(admin, "asset", content).json()

    assert (job["file_format"], job["encoding"], job["row_count"]) == ("csv", "utf-8", 1)
    assert job["mapping"]["Serial"] == "serial_number"  # alias
    assert job["mapping"]["status"] == "business_status"
    assert job["sample"][0][1] == "'=cmd()"  # escaped for display
    assert ImportJob.objects.get(pk=job["id"]).file_encrypted != content  # stored encrypted
    assert AuditEvent.objects.filter(action="imports.upload").exists()


def test_windows_1252_and_xlsx(admin, setup):
    latin = "asset_tag,name,category,site\nIT-9,Café TV,tvs,HQ\n".encode("cp1252")
    job = upload(admin, "asset", latin).json()
    assert job["encoding"] == "cp1252" and "Windows-1252" in job["warnings"][0]

    from openpyxl import Workbook

    book = Workbook()
    book.active.append(["asset_tag", "name", "category", "site"])
    book.active.append(["IT-10", "Monitor 10", "monitors", "HQ"])
    book.create_sheet("Other")
    data = io.BytesIO()
    book.save(data)
    xjob = upload(admin, "asset", data.getvalue(), "assets.xlsx").json()
    assert xjob["file_format"] == "xlsx" and xjob["row_count"] == 1
    assert "first sheet" in xjob["warnings"][0]


@pytest.mark.parametrize(
    "content, name, message",
    [
        (b"", "a.csv", "empty"),
        (b"name,name\nx,y\n", "a.csv", "appears twice"),
        (b"name\nx\n", "a.pdf", ".csv or .xlsx"),
        (b"\x00\x01binary", "a.csv", "binary"),
    ],
)
def test_bad_files_are_refused(admin, content, name, message):
    response = upload(admin, "asset", content, name)
    assert response.status_code == 422 and message in str(response.json())


def test_limits_and_zip_bombs(admin, monkeypatch):
    monkeypatch.setattr(parsing, "MAX_ROWS", 3)
    too_many = csv_bytes([["name"], ["a"], ["b"], ["c"], ["d"]])
    assert "At most 3" in str(upload(admin, "asset", too_many).json())

    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * 5_000_000)
    assert "suspiciously" in str(upload(admin, "asset", bomb.getvalue(), "b.xlsx").json())

    macro = io.BytesIO()
    with zipfile.ZipFile(macro, "w") as archive:
        archive.writestr("xl/vbaProject.bin", b"x")
    assert "Macro" in str(upload(admin, "asset", macro.getvalue(), "m.xlsx").json())


def test_formula_like_parsing():
    for value in ("=1+1", "+cmd", "@SUM(A1)", "-cmd|' /C calc'!A0", "\tx"):
        assert parsing.looks_like_formula(value), value
    for value in ("-5", "-", "- spare", "a=b", "IT-0001"):
        assert not parsing.looks_like_formula(value), value


def test_mapping_validation(admin, setup):
    job = upload(admin, "asset", csv_bytes([["Thing", "name"], ["x", "y"]])).json()
    bad = admin.patch(
        f"{URL}{job['id']}/",
        {"mapping": {"Thing": "password"}},
        format="json",
        HTTP_IF_MATCH=f'"{job["version"]}"',
    )
    assert bad.status_code == 422
    loc = upload(admin, "location", csv_bytes([["site", "Room"], ["HQ", "R1"]]), "l.csv").json()
    missing = admin.post(f"{URL}{loc['id']}/preview/", HTTP_IF_MATCH=f'"{loc["version"]}"')
    assert missing.status_code == 422 and "name" in str(missing.json())


# --- Asset imports (A13, A23) -------------------------------------------------------------------


def test_hundred_assets_with_five_duplicates_and_idempotent_reimport(admin, setup):
    data = [HEADER]
    for n in range(1, 96):
        data.append(
            [
                f"IT-{n:04d}",
                f"Laptop {n}",
                "workstations-laptop",
                "HQ",
                "Dell",
                "Latitude 7440",
                f"SN{n:05d}",
                "deployed",
            ]
        )
    for n in (3, 17, 42, 60, 95):  # five duplicates of earlier rows
        data.append(
            [
                f"IT-{n:04d}",
                f"Laptop {n}",
                "workstations-laptop",
                "HQ",
                "Dell",
                "Latitude 7440",
                f"SN{n:05d}",
                "deployed",
            ]
        )
    content = csv_bytes(data)
    job = upload(admin, "asset", content).json()

    previewed = preview(admin, job)
    assert previewed["status"] == "previewed"
    assert previewed["totals"] == {"create": 95, "update": 0, "skip": 0, "conflict": 5, "error": 0}
    conflicts = rows(admin, job["id"], action="conflict")
    assert conflicts[0]["messages"] == ["The same asset is already in row 3."]
    assert Asset.objects.count() == 0  # dry run wrote nothing

    done = commit(admin, previewed).json()
    assert done["status"] == "completed"
    assert done["totals"]["result"] == {"applied": 95, "skipped": 5, "failed": 0}
    assert Asset.objects.count() == 95
    report = admin.get(f"{URL}{job['id']}/errors/").content.decode("utf-8-sig")
    assert len(report.strip().splitlines()) == 6  # header + 5 conflicts

    again = upload(admin, "asset", content).json()
    assert "already imported" in again["warnings"][0]
    second = preview(admin, again, mode="upsert")
    assert second["totals"]["create"] == 0 and second["totals"]["skip"] == 95
    assert second["totals"]["conflict"] == 5
    commit(admin, second, key="key-2")
    assert Asset.objects.count() == 95  # safe re-import


def test_non_network_asset_without_ip_or_serial(admin, setup):
    content = csv_bytes(
        [
            ["name", "category", "site"],
            ["Reception TV", "tvs", "HQ"],
            ["Desk monitor 4", "monitors", "HQ"],
        ]
    )
    job = preview(admin, upload(admin, "asset", content).json())
    assert job["totals"]["create"] == 2
    commit(admin, job)
    assert set(Asset.objects.values_list("name", flat=True)) == {"Reception TV", "Desk monitor 4"}


def test_guarded_matching_is_review_only_without_id_or_tag(admin, setup, make_asset, laptop):
    make_asset(
        "LT-OLD",
        site=setup["hq"],
        category=laptop,
        manufacturer="Dell Inc.",
        serial_number="ABC123",
    )
    make_asset("Printer 1", site=setup["hq"], category=laptop)
    content = csv_bytes(
        [
            ["name", "category", "site", "manufacturer", "serial_number"],
            ["LT-NEW", "workstations-laptop", "HQ", "Dell", "abc123"],
            ["printer 1", "workstations-laptop", "HQ", "", ""],
        ]
    )
    job = preview(admin, upload(admin, "asset", content).json(), mode="upsert")
    assert job["totals"]["conflict"] == 2 and job["totals"]["create"] == 0
    messages = [r["messages"][0] for r in rows(admin, job["id"])]
    assert "Manufacturer and serial match 'LT-OLD'" in messages[0]
    assert "already exists in site HQ" in messages[1]


def test_update_by_id_and_tag_respects_locks_and_category(
    admin, setup, make_asset, laptop, admin_user
):
    a = make_asset("LT-1", site=setup["hq"], category=laptop, asset_tag="IT-0001", model="E5450")
    b = make_asset("LT-2", site=setup["hq"], category=laptop, asset_tag="IT-0002")
    assert FieldLock.objects.filter(asset=a, field="model").exists()  # manual value locked
    content = csv_bytes(
        [
            ["id", "asset_tag", "owner", "status", "model", "category", "notes"],
            [str(a.pk), "", admin_user.username, "assigned", "", "", "Imported"],
            ["", "IT-0002", "", "", "", "servers-physical-server", ""],
            [str(a.pk), "", "", "", "Latitude 9", "", ""],
            ["", "IT-0003", "", "", "", "", "x"],
        ]
    )
    job = preview(admin, upload(admin, "asset", content).json(), mode="update_matched")
    by_row = {r["row_number"]: r for r in rows(admin, job["id"])}
    assert by_row[1]["action"] == "update"
    assert by_row[1]["changes"]["business_status"] == {"before": "in_stock", "after": "assigned"}
    assert by_row[2]["action"] == "conflict" and "Change category" in by_row[2]["messages"][0]
    assert by_row[3]["action"] == "conflict"  # same asset as row 1 (by id)
    assert by_row[4]["action"] == "skip"  # no match, update only
    commit(admin, job)
    a.refresh_from_db()
    assert (a.owner, a.business_status, a.notes) == (admin_user, "assigned", "Imported")
    b.refresh_from_db()
    assert b.category == laptop

    locked = csv_bytes([["id", "model"], [str(a.pk), "Latitude 9"]])
    job = preview(admin, upload(admin, "asset", locked).json(), mode="update_matched")
    (row,) = rows(admin, job["id"])
    assert row["action"] == "conflict" and "Locked" in row["messages"][0]


def test_formulas_and_custom_fields(admin, setup, laptop):
    from apps.assets.models import CustomFieldDefinition

    CustomFieldDefinition.objects.create(
        category=laptop, key="battery", label="Battery", field_type="text", required=True
    )
    content = csv_bytes(
        [
            ["name", "category", "site", "cf.battery", "notes"],
            ["LT-A", "workstations-laptop", "HQ", "", ""],
            ["LT-B", "workstations-laptop", "HQ", "DELL-7FHHV", '=HYPERLINK("x")'],
            ["LT-C", "workstations-laptop", "HQ", "DELL-7FHHV", ""],
        ]
    )
    job = upload(admin, "asset", content).json()
    assert job["mapping"]["cf.battery"] == "cf.battery"
    job = preview(admin, job)
    by_row = {r["row_number"]: r for r in rows(admin, job["id"])}
    assert by_row[1]["action"] == "error" and "battery" in by_row[1]["messages"][0]
    assert by_row[2]["action"] == "error" and "formula" in by_row[2]["messages"][0]
    assert by_row[2]["values"]["notes"].startswith("'=")  # escaped in the API
    assert by_row[3]["action"] == "create"
    commit(admin, job)
    assert Asset.objects.get(name="LT-C").custom_fields == {"battery": "DELL-7FHHV"}


def test_site_scope_and_permissions(client_for, make_user, setup, make_asset, laptop):
    make_asset("BR-1", site=setup["branch"], category=laptop, asset_tag="BR-0001")
    operator = grant(make_user("operator.i", roles=["asset_operator"]), setup["hq"])
    reader = grant(make_user("reader.i", roles=["read_only"]), setup["hq"])
    client = client_for(operator)
    assert client_for(reader).get(URL).status_code == 403

    content = csv_bytes(
        [
            ["asset_tag", "name", "category", "site"],
            ["", "New BR", "workstations-laptop", "BR1"],
            ["BR-0001", "", "", ""],
        ]
    )
    job = preview(client, upload(client, "asset", content).json(), mode="upsert")
    messages = [r["messages"][0] for r in rows(client, job["id"])]
    assert "not found in your sites" in messages[0]
    assert "cannot see" in messages[1]
    refused = upload(client, "location", csv_bytes([["site", "name"], ["HQ", "R"]]), "l.csv")
    assert refused.status_code == 403
    assert client.get(f"{URL}templates/").json()[1]["allowed"] is False


def test_commit_rules_idempotency_and_replanning(admin, setup, make_asset, laptop):
    content = csv_bytes(
        [
            ["asset_tag", "name", "category", "site"],
            ["IT-0500", "LT-500", "workstations-laptop", "HQ"],
            ["IT-0501", "LT-501", "workstations-laptop", "HQ"],
        ]
    )
    job = upload(admin, "asset", content).json()
    early = commit(admin, job)
    assert early.status_code == 409  # preview first
    job = preview(admin, job)
    no_key = admin.post(f"{URL}{job['id']}/commit/", HTTP_IF_MATCH=f'"{job["version"]}"')
    assert no_key.status_code == 428
    make_asset("Someone else", site=setup["hq"], category=laptop, asset_tag="IT-0501")

    done = commit(admin, job, key="same-key").json()
    assert done["totals"]["result"] == {"applied": 1, "skipped": 0, "failed": 1}
    failed = rows(admin, job["id"], result="failed")[0]
    assert "Changed since the preview" in failed["result_message"]
    duplicate = commit(admin, done, key="same-key").json()
    assert duplicate["id"] == job["id"] and Asset.objects.filter(name="LT-500").count() == 1


def test_rollback_only_untouched_rows(admin, setup, make_asset, laptop, admin_user):
    from apps.assets import services as asset_services
    from apps.reconciliation.tests.conftest import Req

    existing = make_asset("LT-9", site=setup["hq"], category=laptop, asset_tag="IT-0009")
    content = csv_bytes(
        [
            ["asset_tag", "name", "category", "site", "notes"],
            ["IT-0009", "", "", "", "updated by import"],
            ["IT-0010", "LT-10", "workstations-laptop", "HQ", ""],
            ["IT-0011", "LT-11", "workstations-laptop", "HQ", ""],
        ]
    )
    job = commit(
        admin, preview(admin, upload(admin, "asset", content).json(), mode="upsert")
    ).json()
    edited = Asset.objects.get(asset_tag="IT-0011")
    asset_services.update_asset(Req(admin_user), edited, {"notes": "edited later"}, edited.version)

    rolled = admin.post(
        f"{URL}{job['id']}/rollback/",
        {"reason": "Wrong file"},
        format="json",
        HTTP_IF_MATCH=f'"{job["version"]}"',
    ).json()

    assert rolled["status"] == "rolled_back"
    assert rolled["totals"]["rollback"] == {"rolled_back": 2, "needs_correction": 1}
    existing.refresh_from_db()
    assert existing.notes == ""
    assert Asset.objects.get(asset_tag="IT-0010").archived_at is not None
    assert Asset.objects.get(asset_tag="IT-0011").archived_at is None
    assert AuditEvent.objects.filter(action="imports.rollback").exists()


def test_missing_rows_never_archive(admin, setup):
    first = csv_bytes(
        [
            ["asset_tag", "name", "category", "site"],
            ["IT-0100", "A", "workstations-laptop", "HQ"],
            ["IT-0101", "B", "workstations-laptop", "HQ"],
        ]
    )
    commit(admin, preview(admin, upload(admin, "asset", first).json()))
    second = csv_bytes(
        [["asset_tag", "name", "category", "site"], ["IT-0100", "A", "workstations-laptop", "HQ"]]
    )
    commit(admin, preview(admin, upload(admin, "asset", second).json(), mode="upsert"), key="k2")
    assert Asset.objects.filter(archived_at__isnull=True).count() == 2


# --- Other families -----------------------------------------------------------------------


def test_location_group_and_membership_families(admin, setup, make_asset, laptop):
    locs = csv_bytes(
        [
            ["site", "name", "kind", "parent"],
            ["HQ", "Building A", "building", ""],
            ["HQ", "Server room", "room", "Building A"],
            ["NOPE", "X", "", ""],
        ]
    )
    job = preview(admin, upload(admin, "location", locs, "l.csv").json())
    assert job["totals"]["create"] == 1 and job["totals"]["error"] == 2  # parent not there yet
    commit(admin, job, key="fam-1")
    assert Location.objects.filter(name="Building A").exists()

    groups = csv_bytes(
        [
            ["name", "kind", "rule"],
            ["Refresh 2027", "static", ""],
            [
                "Dell fleet",
                "dynamic",
                '{"field": "manufacturer", "operator": "eq", "value": "Dell"}',
            ],
            ["Bad rule", "dynamic", '{"field": "password", "operator": "eq", "value": "x"}'],
        ]
    )
    job = preview(admin, upload(admin, "group", groups, "g.csv").json())
    assert job["totals"]["create"] == 2 and job["totals"]["error"] == 1
    commit(admin, job, key="fam-2")
    assert AssetGroup.objects.get(name="Dell fleet").rule_version == 1

    asset = make_asset("LT-77", site=setup["hq"], category=laptop, asset_tag="IT-0077")
    members = csv_bytes(
        [
            ["group", "asset_tag", "reason"],
            ["Refresh 2027", "IT-0077", "Out of warranty"],
            ["Refresh 2027", "IT-0077", ""],
            ["Dell fleet", "IT-0077", ""],
        ]
    )
    job = preview(admin, upload(admin, "group_membership", members, "m.csv").json())
    assert (job["totals"]["create"], job["totals"]["skip"], job["totals"]["error"]) == (1, 1, 1)
    commit(admin, job, key="fam-3")
    membership = AssetGroupMembership.objects.get(group__name="Refresh 2027", asset=asset)
    assert membership.added_reason == "Out of warranty"


def test_purged_original_cannot_be_previewed(admin, setup):
    job = upload(admin, "asset", csv_bytes([["name"], ["x"]])).json()
    from django.utils import timezone

    ImportJob.objects.filter(pk=job["id"]).update(purge_after=timezone.now())
    assert services.purge_expired() == 1
    after = admin.post(f"{URL}{job['id']}/preview/", HTTP_IF_MATCH=f'"{job["version"]}"').json()
    assert after["status"] == "uploaded" and "no longer kept" in after["error_message"]
    assert admin.get(f"{URL}{job['id']}/").json()["file_retained"] is False


def test_other_users_cannot_touch_my_job(admin, setup, client_for, make_user):
    job = upload(admin, "asset", csv_bytes([["name"], ["x"]])).json()
    operator = grant(make_user("operator.z", roles=["asset_operator"]), setup["hq"])
    other = client_for(operator)
    assert other.get(f"{URL}{job['id']}/").status_code == 404
    assert other.post(f"{URL}{job['id']}/preview/", HTTP_IF_MATCH='"1"').status_code == 404
