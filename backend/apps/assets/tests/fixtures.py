import pytest
from rest_framework.test import APIRequestFactory

from apps.assets import services
from apps.assets.models import AssetCategory
from apps.organizations.models import Department, Location, Site, UserSiteGrant


@pytest.fixture
def hq(db):
    return Site.objects.create(code="HQ", name="Headquarters")


@pytest.fixture
def hq_dc(hq):
    return Site.objects.create(code="HQ-DC", name="HQ data centre", parent=hq)


@pytest.fixture
def branch(db):
    return Site.objects.create(code="BR1", name="Branch 1")


@pytest.fixture
def hq_room(hq):
    return Location.objects.create(site=hq, name="Server room", kind="room")


@pytest.fixture
def branch_room(branch):
    return Location.objects.create(site=branch, name="Comms room", kind="room")


@pytest.fixture
def it_dept(db):
    return Department.objects.create(name="IT")


@pytest.fixture
def switch(db):
    return AssetCategory.objects.get(code="networking-switch")


@pytest.fixture
def laptop(db):
    return AssetCategory.objects.get(code="workstations-laptop")


def grant(user, *sites):
    for site in sites:
        UserSiteGrant.objects.create(user=user, site=site)
    return user


@pytest.fixture
def hq_operator(make_user, hq):
    return grant(make_user("hq.operator", roles=["asset_operator"]), hq)


@pytest.fixture
def branch_operator(make_user, branch):
    return grant(make_user("branch.operator", roles=["asset_operator"]), branch)


@pytest.fixture
def hq_manager(make_user, hq):
    return grant(make_user("hq.manager", roles=["itam_manager"]), hq)


@pytest.fixture
def hq_reader(make_user, hq):
    return grant(make_user("hq.reader", roles=["read_only"]), hq)


@pytest.fixture
def make_asset(admin_user):
    """Create through the real service so history/audit are always exercised."""
    factory = APIRequestFactory()

    def _make(name="sw-core-01", *, site, category, **extra):
        request = factory.post("/")
        request.user = admin_user
        return services.create_asset(
            request, {"name": name, "site": site, "category": category, **extra}
        )

    return _make
