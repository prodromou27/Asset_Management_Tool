import uuid

import pytest
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.models import Permission, Role, User
from apps.audit.models import AuditEvent
from conftest import PASSWORD

pytestmark = pytest.mark.django_db

USERS = "/api/v1/users/"
NEW_USER = {
    "username": "Jane.Doe",
    "display_name": "Jane Doe",
    "email": "Jane.Doe@Example.test",
    "roles": ["asset_operator"],
    "password": "Temporary-Strong-Pass-1",
}


def detail(user):
    return f"{USERS}{user.pk}/"


# --- Authorization: 401 / 403 and no side effects -----------------------------


def test_unauthenticated_cannot_list_users(api_client):
    assert api_client.get(USERS).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "list", None),
        ("post", "list", NEW_USER),
        ("get", "detail", None),
        ("patch", "detail", {"display_name": "X"}),
        ("post", "disable", {"reason": "Leaving company"}),
        ("post", "enable", None),
        ("post", "unlock", None),
        ("post", "reset-password", {"password": "Another-Strong-Pass-1"}),
    ],
)
def test_role_without_user_permissions_is_denied(
    client_for, operator_user, admin_user, method, path, payload
):
    client = client_for(operator_user)
    url = USERS if path == "list" else detail(admin_user)
    if path not in ("list", "detail"):
        url += f"{path}/"
    audit_before = AuditEvent.objects.exclude(action="auth.login").count()

    response = getattr(client, method)(url, payload, format="json", HTTP_IF_MATCH='"1"')

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert AuditEvent.objects.exclude(action="auth.login").count() == audit_before
    admin_user.refresh_from_db()
    assert admin_user.is_active and admin_user.version == 1


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("post", "", NEW_USER),
        ("patch", "detail", {"display_name": "X"}),
        ("post", "disable/", {"reason": "Leaving company"}),
    ],
)
def test_auditor_can_read_but_not_modify_users(
    client_for, auditor_user, operator_user, method, suffix, payload
):
    client = client_for(auditor_user)
    assert client.get(USERS).status_code == 200
    assert client.get(detail(operator_user)).status_code == 200

    url = USERS if suffix == "" else detail(operator_user) + ("" if suffix == "detail" else suffix)
    response = getattr(client, method)(url, payload, format="json", HTTP_IF_MATCH='"1"')

    assert response.status_code == 403
    assert not User.objects.filter(username="jane.doe").exists()


def test_role_change_applies_on_next_request_without_relogin(client_for, operator_user):
    client = client_for(operator_user)
    assert client.get(USERS).status_code == 403

    operator_user.roles.add(Role.objects.get(code="auditor"))

    assert client.get(USERS).status_code == 200


# --- Create -----------------------------------------------------------------------


def test_admin_creates_user_with_temporary_password(client_for, admin_user):
    response = client_for(admin_user).post(USERS, NEW_USER, format="json")

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "jane.doe"
    assert body["email"] == "jane.doe@example.test"
    assert body["must_change_password"] is True
    assert [r["code"] for r in body["roles"]] == ["asset_operator"]
    assert "password" not in body

    user = User.objects.get(username="jane.doe")
    assert user.password != NEW_USER["password"]
    assert user.check_password(NEW_USER["password"])
    assert user.created_by == admin_user

    event = AuditEvent.objects.get(action="users.create")
    assert event.actor == admin_user
    assert event.object_id == str(user.pk)
    assert event.after["roles"] == ["asset_operator"]
    assert NEW_USER["password"] not in str(event.after)


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"username": "ADMIN.ONE"}, "username"),
        ({"email": "ADMIN.ONE@example.test"}, "email"),
        ({"password": "short"}, "password"),
        ({"password": "jane.doe.jane"}, "password"),
        ({"roles": ["root"]}, "roles"),
        ({"roles": []}, "roles"),
        ({"username": "has space"}, "username"),
    ],
    ids=["dup-username", "dup-email", "short-pw", "similar-pw", "bad-role", "no-role", "bad-name"],
)
def test_create_user_validation(client_for, admin_user, override, field):
    response = client_for(admin_user).post(USERS, {**NEW_USER, **override}, format="json")

    assert response.status_code == 422
    assert field in response.json()["error"]["field_errors"]
    assert not AuditEvent.objects.filter(action="users.create").exists()


# --- List -------------------------------------------------------------------------


def test_list_shape_and_filters(client_for, admin_user, make_user):
    make_user("bob.ops", roles=["asset_operator"], email="bob@example.test")
    make_user("carol.sec", roles=["security_analyst"], is_active=False)
    client = client_for(admin_user)

    body = client.get(USERS).json()
    assert set(body) == {"items", "next_cursor", "previous_cursor", "count"}
    assert body["count"] == 3
    assert [u["username"] for u in body["items"]] == ["admin.one", "bob.ops", "carol.sec"]

    def names(query):
        return [u["username"] for u in client.get(USERS + query).json()["items"]]

    assert names("?q=BOB@") == ["bob.ops"]
    assert names("?status=disabled") == ["carol.sec"]
    assert names("?role=system_admin") == ["admin.one"]


def test_list_paginates_with_cursor(client_for, admin_user, make_user):
    for i in range(5):
        make_user(f"user.{i}")
    client = client_for(admin_user)

    first = client.get(USERS + "?page_size=4").json()
    second = client.get(USERS + f"?page_size=4&cursor={first['next_cursor']}").json()

    assert len(first["items"]) == 4 and first["count"] == 6
    assert len(second["items"]) == 2 and second["next_cursor"] is None


def test_unknown_user_returns_404_envelope(client_for, admin_user):
    response = client_for(admin_user).get(f"{USERS}{uuid.uuid4()}/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- Update -----------------------------------------------------------------------


def test_patch_requires_if_match(client_for, admin_user, operator_user):
    response = client_for(admin_user).patch(
        detail(operator_user), {"display_name": "New"}, format="json"
    )

    assert response.status_code == 428
    assert response.json()["error"]["code"] == "PRECONDITION_REQUIRED"


def test_patch_with_stale_version_conflicts(client_for, admin_user, operator_user):
    response = client_for(admin_user).patch(
        detail(operator_user), {"display_name": "New"}, format="json", HTTP_IF_MATCH='"7"'
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_MISMATCH"


def test_patch_updates_roles_and_audits_before_after(client_for, admin_user, operator_user):
    response = client_for(admin_user).patch(
        detail(operator_user),
        {"display_name": "Op One", "roles": ["auditor", "asset_operator"]},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response["ETag"] == '"2"'
    event = AuditEvent.objects.get(action="users.update")
    assert event.before["roles"] == ["asset_operator"]
    assert event.after["roles"] == ["asset_operator", "auditor"]
    assert event.after["display_name"] == "Op One"


def test_admin_cannot_remove_own_admin_role(client_for, admin_user):
    response = client_for(admin_user).patch(
        detail(admin_user), {"roles": ["auditor"]}, format="json", HTTP_IF_MATCH='"1"'
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELF_DEMOTION"


# --- Disable / enable / unlock / reset -------------------------------------------


def test_disable_requires_reason(client_for, admin_user, operator_user):
    response = client_for(admin_user).post(
        detail(operator_user) + "disable/", {"reason": ""}, format="json"
    )

    assert response.status_code == 422
    assert "reason" in response.json()["error"]["field_errors"]


def test_disable_revokes_sessions_and_is_audited(client_for, admin_user, operator_user):
    victim_session = client_for(operator_user)
    assert victim_session.get("/api/v1/auth/me/").status_code == 200

    response = client_for(admin_user).post(
        detail(operator_user) + "disable/", {"reason": "Left the organization"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["disabled_by"] == "admin.one"
    assert victim_session.get("/api/v1/auth/me/").status_code == 401
    event = AuditEvent.objects.get(action="users.disable")
    assert event.detail == "Left the organization"
    assert event.before["is_active"] is True and event.after["is_active"] is False


def test_admin_cannot_disable_self(client_for, admin_user):
    response = client_for(admin_user).post(
        detail(admin_user) + "disable/", {"reason": "Testing self"}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELF_DISABLE"


def test_last_active_system_admin_cannot_be_disabled(client_for, admin_user, make_user):
    # A non-admin role holding users.manage must still not remove the last admin.
    custom = Role.objects.create(code="user_steward", name="User Steward", is_system=False)
    custom.permissions.set(Permission.objects.filter(code__in=["users.manage", "users.view"]))
    steward = make_user("steward.one", roles=["user_steward"])

    response = client_for(steward).post(
        detail(admin_user) + "disable/", {"reason": "Attempted takeover"}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_ADMIN"
    admin_user.refresh_from_db()
    assert admin_user.is_active


def test_enable_restores_access(client_for, admin_user, make_user):
    user = make_user("returning.user", roles=["auditor"], is_active=False)

    response = client_for(admin_user).post(detail(user) + "enable/")

    assert response.status_code == 200 and response.json()["is_active"] is True
    assert AuditEvent.objects.filter(action="users.enable", object_id=str(user.pk)).exists()
    assert client_for(user).get(USERS).status_code == 200


def test_unlock_clears_lockout(client_for, admin_user, operator_user):
    from datetime import timedelta

    from django.utils import timezone

    User.objects.filter(pk=operator_user.pk).update(
        locked_until=timezone.now() + timedelta(hours=1)
    )

    response = client_for(admin_user).post(detail(operator_user) + "unlock/")

    assert response.status_code == 200 and response.json()["is_locked"] is False
    assert AuditEvent.objects.filter(action="users.unlock").exists()


def test_reset_password_forces_change_and_revokes_sessions(client_for, admin_user, operator_user):
    old_session = client_for(operator_user)
    new_password = "Reset-Strong-Pass-77"

    response = client_for(admin_user).post(
        detail(operator_user) + "reset-password/", {"password": new_password}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert old_session.get("/api/v1/auth/me/").status_code == 401
    assert client_for(operator_user, new_password).get(USERS).json()["error"]["code"] == (
        "PASSWORD_CHANGE_REQUIRED"
    )
    event = AuditEvent.objects.get(action="users.password_reset")
    assert new_password not in str(event.before) + str(event.after) + event.detail


def test_snapshot_never_contains_password_material(operator_user):
    assert set(services.snapshot(operator_user)) == {
        "username",
        "email",
        "display_name",
        "roles",
        "all_sites",
        "sites",
        "is_active",
        "local_login_enabled",
    }


def test_session_auth_hash_changes_with_epoch(operator_user):
    before = operator_user.get_session_auth_hash()
    operator_user.session_epoch += 1

    assert operator_user.get_session_auth_hash() != before


def test_disabled_user_session_rejected_even_without_epoch_change(operator_user):
    client = APIClient()
    client.post(
        "/api/v1/auth/local/login/",
        {"username": "operator.one", "password": PASSWORD},
        format="json",
    )
    User.objects.filter(pk=operator_user.pk).update(is_active=False)

    assert client.get("/api/v1/auth/me/").status_code == 401
