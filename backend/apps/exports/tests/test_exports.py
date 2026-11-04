"""CSV/XLSX/JSON exports with RBAC and async jobs (Task 014, docs/11, docs/14, docs/15 A14/A15)."""

import csv
import io
import json
import zipfile
from datetime import timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import Role
from apps.assets.models import AssetHostname, AssetInterface, AssetIPAddress
from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.exports import families, services, writers
from apps.exports.models import ExportJob
from apps.groups.models import AssetGroup, AssetGroupMembership

pytestmark = pytest.mark.django_db
URL = "/api/v1/exports/"


@pytest.fixture
def run_jobs(django_capture_on_commit_callbacks):
    """Execute the on-commit hand-off to the (eager) Celery worker."""

    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def admin(admin_user, client_for):
    return client_for(admin_user)


@pytest.fixture
def inventory(hq, branch, switch, laptop, make_asset, admin_user):
    core = make_asset("sw-core-01", site=hq, category=switch, serial_number="S-1", owner=admin_user)
    evil = make_asset('=HYPERLINK("x")', site=hq, category=laptop, serial_number="+1")
    remote = make_asset("br-sw-01", site=branch, category=switch, serial_number="S-9")
    AssetHostname.objects.create(asset=core, hostname="sw-core-01.corp.example", is_primary=True)
    AssetHostname.objects.create(asset=core, hostname="sw-core-01-mgmt", source="librenms")
    nic = AssetInterface.objects.create(asset=core, name="Vlan10", mac_address="02:00:00:00:00:01")
    AssetIPAddress.objects.create(asset=core, address="10.0.0.2", interface=nic, is_primary=True)
    AssetIPAddress.objects.create(asset=core, address="10.0.0.3")
    group = AssetGroup.objects.create(name="Core network", kind="static", owner=admin_user)
    now = timezone.now()
    for asset in (core, remote):
        AssetGroupMembership.objects.create(
            group=group, asset=asset, source="explicit", added_at=now, added_by=admin_user
        )
    return {"core": core, "evil": evil, "remote": remote, "group": group}


def create(client, run_jobs, **body):
    body = {"family": "assets", "format": "csv", "scope": "all", **body}
    response = run_jobs(client.post, URL, body, format="json")
    assert response.status_code == 202, response.json()
    return client.get(f"{URL}{response.json()['id']}/").json()


def download(client, job):
    return client.get(f"{URL}{job['id']}/download/")


def csv_rows(content: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


# --- Families and validation ------------------------------------------------------------------


def test_families_describe_columns_related_and_personal_masking(admin, client_for, hq_reader):
    admin_families = {f["code"]: f for f in admin.get(f"{URL}families/").json()}
    assert set(admin_families) == {"assets", "groups", "license_entitlements"}
    assets = admin_families["assets"]
    assert assets["personal_data_allowed"] is True
    assert {
        "hostnames",
        "interfaces",
        "ip_addresses",
        "groups",
        "lifecycle",
        "software",
        "licenses",
    } == {r["key"] for r in assets["related"]}
    assert "q" in assets["filter_keys"]

    reader = {f["code"]: f for f in client_for(hq_reader).get(f"{URL}families/").json()}
    assert "license_entitlements" not in reader  # needs licenses.view
    assert "licenses" not in {r["key"] for r in reader["assets"]["related"]}
    columns = {c["key"]: c for c in reader["assets"]["columns"]}
    assert reader["assets"]["personal_data_allowed"] is False
    assert columns["owner"]["personal"] is True and columns["owner"]["allowed"] is False
    assert columns["serial_number"]["allowed"] is True


def test_every_role_may_export_but_only_some_include_personal_data():
    roles = {r.code: set(r.permissions.values_list("code", flat=True)) for r in Role.objects.all()}
    for code, perms in roles.items():
        assert "exports.run" in perms, code
    personal = {code for code, perms in roles.items() if "exports.personal" in perms}
    assert personal == {"system_admin", "itam_manager", "asset_operator"}


def test_user_without_export_permission_is_refused(make_user, client_for, hq):
    nobody = grant(make_user("no.export", roles=[]), hq)
    client = client_for(nobody)
    assert client.get(f"{URL}families/").status_code == 403
    body = {"family": "assets", "format": "csv", "scope": "all"}
    assert client.post(URL, body, format="json").status_code == 403


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"columns": ["name", "password"]}, "columns"),
        ({"related": ["certificates"]}, "related"),
        ({"scope": "filtered", "filters": {"drop_table": "x"}}, "filters"),
        ({"scope": "selected", "ids": []}, "ids"),
    ],
)
def test_invalid_requests_are_rejected(admin, body, field):
    response = admin.post(
        URL, {"family": "assets", "format": "csv", "scope": "all", **body}, format="json"
    )
    assert response.status_code == 422
    assert field in response.json()["error"]["field_errors"]


def test_unknown_family_and_format(admin):
    for body in ({"family": "secrets"}, {"format": "pdf"}):
        response = admin.post(
            URL, {"family": "assets", "format": "csv", "scope": "all", **body}, format="json"
        )
        assert response.status_code == 422


def test_at_most_three_exports_in_progress(admin):
    body = {"family": "assets", "format": "csv", "scope": "all"}
    for _ in range(3):  # on-commit hand-off not executed: the jobs stay queued
        assert admin.post(URL, body, format="json").status_code == 202
    response = admin.post(URL, body, format="json")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "EXPORT_LIMIT"


# --- Output -----------------------------------------------------------------------------------


def test_csv_export_of_filtered_view_escapes_formulas(admin, run_jobs, inventory, hq):
    job = create(admin, run_jobs, scope="filtered", filters={"site": str(hq.pk)})

    assert job["status"] == "completed" and job["row_count"] == 2
    assert job["filename"].startswith("itam-assets-") and job["filename"].endswith(".csv")
    assert job["downloadable"] is True and job["expires_at"]
    response = download(admin, job)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response["Content-Disposition"] == f'attachment; filename="{job["filename"]}"'
    rows = {r["serial_number"]: r for r in csv_rows(response.content)}
    assert set(rows) == {"S-1", "'+1"}  # branch asset filtered out; "+1" escaped
    assert rows["'+1"]["name"] == '\'=HYPERLINK("x")'
    assert rows["S-1"]["category"] == "Networking / Switch"
    assert rows["S-1"]["owner"] == "admin.one"
    assert rows["S-1"]["primary_ip"] == "10.0.0.2"


def test_a15_cross_site_user_gets_only_their_sites(client_for, hq_reader, run_jobs, inventory):
    """docs/15 A15: scope-limited output, no leaked rows, even when IDs are requested."""
    client = client_for(hq_reader)
    everything = create(client, run_jobs, scope="all")
    names = {r["name"] for r in csv_rows(download(client, everything).content)}
    assert "br-sw-01" not in names and "sw-core-01" in names

    picked = create(
        client,
        run_jobs,
        scope="selected",
        ids=[str(inventory["remote"].pk), str(inventory["core"].pk)],
    )
    assert picked["row_count"] == 1
    assert [r["name"] for r in csv_rows(download(client, picked).content)] == ["sw-core-01"]

    branch_filter = create(
        client, run_jobs, scope="filtered", filters={"site": str(inventory["remote"].site_id)}
    )
    assert branch_filter["row_count"] == 0


def test_personal_columns_are_masked_without_permission(client_for, hq_reader, run_jobs, inventory):
    client = client_for(hq_reader)
    job = create(client, run_jobs, related=["groups"])
    assert set(job["masked_columns"]) == {"owner", "owner_name", "modified_by"}
    archive = zipfile.ZipFile(io.BytesIO(download(client, job).content))
    header = csv_rows(archive.read("assets.csv"))[0]
    assert "owner" not in header and "modified_by" not in header
    about = archive.read("about.csv").decode("utf-8-sig")
    assert "Hidden personal data columns" in about


def test_a14_related_tables_in_csv_zip(admin, run_jobs, inventory):
    """docs/15 A14: 1:N data in separate files with stable IDs, never one flattened field."""
    related = ["hostnames", "interfaces", "ip_addresses", "groups"]
    job = create(admin, run_jobs, related=related)
    assert job["filename"].endswith(".zip")
    assert job["related_counts"] == {
        "hostnames": 2,
        "interfaces": 1,
        "ip_addresses": 2,
        "groups": 2,
    }
    archive = zipfile.ZipFile(io.BytesIO(download(admin, job).content))
    assert set(archive.namelist()) == {
        "assets.csv",
        "hostnames.csv",
        "interfaces.csv",
        "ip_addresses.csv",
        "groups.csv",
        "about.csv",
    }
    core = str(inventory["core"].pk)
    ips = csv_rows(archive.read("ip_addresses.csv"))
    nic = csv_rows(archive.read("interfaces.csv"))[0]
    assert {r["asset_id"] for r in ips} == {core}
    assert [r["interface_id"] for r in ips if r["address"] == "10.0.0.2"] == [nic["interface_id"]]
    groups = csv_rows(archive.read("groups.csv"))
    assert {(g["asset_id"], g["group_name"]) for g in groups} == {
        (core, "Core network"),
        (str(inventory["remote"].pk), "Core network"),
    }


def test_xlsx_has_one_sheet_per_table_and_escapes_text(admin, run_jobs, inventory):
    job = create(admin, run_jobs, format="xlsx", related=["hostnames"])
    workbook = load_workbook(io.BytesIO(download(admin, job).content), read_only=True)
    assert workbook.sheetnames == ["assets", "hostnames", "about"]
    rows = list(workbook["assets"].iter_rows(values_only=True))
    header = rows[0]
    names = {r[header.index("name")] for r in rows[1:]}
    assert '\'=HYPERLINK("x")' in names
    versions = [r[header.index("version")] for r in rows[1:]]
    assert all(isinstance(v, int) for v in versions)  # numbers stay numbers


def test_xlsx_splits_tables_that_exceed_the_sheet_limit():
    columns = [families.Column("id", "ID", lambda r, c: r)]
    main = families.Table("assets", columns, [{"id": str(i)} for i in range(5)])
    data = families.ExportData(main=main, related={}, parent_key={}, masked=[])
    meta = {
        "family": "assets",
        "family_label": "Assets",
        "exported_at": "2026-11-04T00:00:00+00:00",
        "exported_by": "x",
        "scope": "all",
        "scope_label": "All",
        "filters": {},
    }
    body, _, _ = writers.write_xlsx(data, meta, max_rows=2)
    workbook = load_workbook(io.BytesIO(body), read_only=True)
    assert workbook.sheetnames == ["assets", "assets_2", "assets_3", "about"]
    assert len(list(workbook["assets_3"].iter_rows(values_only=True))) == 2  # header + 1


def test_json_is_versioned_and_nests_related_data(admin, run_jobs, inventory):
    job = create(admin, run_jobs, format="json", related=["hostnames", "ip_addresses"])
    document = json.loads(download(admin, job).content)
    assert (document["format"], document["version"], document["family"]) == (
        "itam.export",
        1,
        "assets",
    )
    assert document["count"] == 3 and document["exported_by"] == "admin.one"
    core = next(i for i in document["items"] if i["name"] == "sw-core-01")
    assert {h["hostname"] for h in core["hostnames"]} == {
        "sw-core-01.corp.example",
        "sw-core-01-mgmt",
    }
    assert all("asset_id" not in h for h in core["hostnames"])
    evil = next(i for i in document["items"] if i["serial_number"] == "+1")
    assert evil["name"] == '=HYPERLINK("x")'  # JSON keeps the raw value


def test_column_selection(admin, run_jobs, inventory):
    job = create(admin, run_jobs, columns=["id", "name"])
    assert list(csv_rows(download(admin, job).content)[0]) == ["id", "name"]


def test_groups_export_only_includes_members_in_scope(client_for, hq_reader, run_jobs, inventory):
    client = client_for(hq_reader)
    job = create(client, run_jobs, family="groups", related=["members"])
    archive = zipfile.ZipFile(io.BytesIO(download(client, job).content))
    groups = csv_rows(archive.read("groups.csv"))
    assert [(g["name"], g["member_count"]) for g in groups] == [("Core network", "1")]
    assert "owner" not in groups[0]
    members = csv_rows(archive.read("members.csv"))
    assert [m["asset_name"] for m in members] == ["sw-core-01"]
    assert "added_by" not in members[0]


# --- Job security ------------------------------------------------------------------------------


def test_only_the_creator_downloads(
    admin, client_for, auditor_user, hq_operator, run_jobs, inventory
):
    job = create(admin, run_jobs)
    other = client_for(hq_operator)
    assert other.get(f"{URL}{job['id']}/").status_code == 404
    assert download(other, job).status_code == 404

    auditor = client_for(auditor_user)
    listed = auditor.get(URL).json()["items"]
    assert [j["id"] for j in listed] == [job["id"]]  # auditors see export records
    assert listed[0]["downloadable"] is False
    assert download(auditor, job).status_code == 403  # ...but never the file


def test_expired_exports_are_purged_and_gone(admin, run_jobs, inventory):
    job = create(admin, run_jobs)
    assert services.purge_expired(timezone.now() + timedelta(hours=25)) == 1
    stored = ExportJob.objects.get(pk=job["id"])
    assert stored.status == "expired" and stored.file_encrypted is None
    response = download(admin, job)
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "EXPORT_EXPIRED"


def test_file_is_encrypted_at_rest(admin, run_jobs, inventory):
    job = create(admin, run_jobs)
    stored = bytes(ExportJob.objects.get(pk=job["id"]).file_encrypted)
    assert b"sw-core-01" not in stored
    assert job["checksum"] and job["size_bytes"] > 0


def test_permission_removed_before_the_worker_runs(hq_operator, client_for, inventory):
    client = client_for(hq_operator)
    job_id = client.post(
        URL, {"family": "assets", "format": "csv", "scope": "all"}, format="json"
    ).json()["id"]
    hq_operator.roles.clear()

    job = services.run_export(job_id)
    assert job.status == "failed" and "removed" in job.error_message
    assert job.file_encrypted is None
    assert AuditEvent.objects.filter(action="exports.fail", object_id=job_id).exists()


def test_too_many_rows_fails_with_a_clear_message(admin, run_jobs, inventory, settings):
    settings.ITAM_EXPORT_MAX_ROWS = 2
    job = create(admin, run_jobs)
    assert job["status"] == "failed"
    assert "more than 2 records" in job["error_message"]


def test_stuck_jobs_are_released(admin, inventory):
    job_id = admin.post(
        URL, {"family": "assets", "format": "csv", "scope": "all"}, format="json"
    ).json()["id"]
    assert services.fail_stuck(timezone.now() + timedelta(hours=2)) == 1
    assert ExportJob.objects.get(pk=job_id).status == "failed"


def test_create_complete_and_download_are_audited(admin, run_jobs, inventory):
    job = create(admin, run_jobs, format="json")
    download(admin, job)
    actions = list(
        AuditEvent.objects.filter(object_id=job["id"])
        .order_by("occurred_at")
        .values_list("action", flat=True)
    )
    assert actions == ["exports.create", "exports.complete", "exports.download"]
    assert ExportJob.objects.get(pk=job["id"]).download_count == 1


def test_lifecycle_assessments_export_as_a_related_table(admin, run_jobs, inventory):
    from apps.lifecycle import services as lifecycle

    lifecycle.reassess_assets([inventory["core"].pk, inventory["remote"].pk])
    job = create(admin, run_jobs, format="json", related=["lifecycle"])
    document = json.loads(download(admin, job).content)
    core = next(i for i in document["items"] if i["name"] == "sw-core-01")
    assert {r["dimension"] for r in core["lifecycle"]} == {"hardware", "os"}
    assert all(r["status"] for r in core["lifecycle"])
