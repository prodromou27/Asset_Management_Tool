import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import Role, User

PASSWORD = "Correct-Horse-Battery-9"

# Shared asset/site fixtures (hq, branch, switch, make_asset, ...) for every test package.
pytest_plugins = ["apps.assets.tests.fixtures"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(username, roles=(), password=PASSWORD, **extra):
        extra.setdefault("display_name", username.title())
        user = User.objects.create_user(username, password, **extra)
        user.roles.set(Role.objects.filter(code__in=roles))
        return user

    return _make


@pytest.fixture
def admin_user(make_user):
    return make_user(
        "admin.one", roles=["system_admin"], email="admin.one@example.test", all_sites=True
    )


@pytest.fixture
def auditor_user(make_user):
    return make_user("auditor.one", roles=["auditor"])


@pytest.fixture
def operator_user(make_user):
    return make_user("operator.one", roles=["asset_operator"])


def login(client: APIClient, username: str, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/local/login/", {"username": username, "password": password}, format="json"
    )


@pytest.fixture
def client_for():
    """Return an APIClient signed in through the real login endpoint."""

    def _client(user, password=PASSWORD):
        client = APIClient()
        response = login(client, user.username, password)
        assert response.status_code == 200, response.json()
        return client

    return _client
