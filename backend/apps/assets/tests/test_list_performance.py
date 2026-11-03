"""List columns for discovery freshness, and search/list performance at scale."""

import time
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assets.models import Asset, AssetHostname
from apps.integrations.models import DiscoverySource, IntegrationInstance
from apps.reconciliation.models import SourceLink
from tests.conftest import requires_postgres

pytestmark = pytest.mark.django_db
ASSETS = "/api/v1/assets/"


def _instance(name, site):
    return IntegrationInstance.objects.create(
        name=name, source=DiscoverySource.objects.get(code="fixture"), default_site=site
    )


def test_last_seen_source_count_and_source_filter(client_for, admin_user, make_asset, hq, switch):
    linked = make_asset("linked", site=hq, category=switch)
    make_asset("manual-only", site=hq, category=switch)
    a, b = _instance("A", hq), _instance("B", hq)
    now = timezone.now()
    SourceLink.objects.create(
        instance=a,
        external_id="1",
        asset=linked,
        method="approved_candidate",
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now - timedelta(days=2),
    )
    SourceLink.objects.create(
        instance=b,
        external_id="9",
        asset=linked,
        method="approved_candidate",
        first_seen_at=now,
        last_seen_at=now,
    )
    SourceLink.objects.create(
        instance=b,
        external_id="old",
        asset=None,
        status="unlinked",
        method="approved_candidate",
        first_seen_at=now,
        last_seen_at=now,
    )
    client = client_for(admin_user)

    rows = {r["name"]: r for r in client.get(ASSETS, {"ordering": "name"}).json()["items"]}

    assert rows["linked"]["source_count"] == 2
    assert rows["linked"]["last_seen_at"].startswith(now.isoformat()[:16])
    assert rows["manual-only"]["source_count"] == 0 and rows["manual-only"]["last_seen_at"] is None
    by_source = client.get(ASSETS, {"source": str(a.pk)}).json()["items"]
    assert [r["name"] for r in by_source] == ["linked"]
    assert client.get(ASSETS, {"source": "nope"}).json()["count"] == 0


def test_search_matches_hostnames_without_duplicate_rows(
    client_for, admin_user, make_asset, hq, switch
):
    make_asset(
        "x",
        site=hq,
        category=switch,
        hostnames=[{"hostname": "core-a.example"}, {"hostname": "core-b.example"}],
    )

    body = client_for(admin_user).get(ASSETS, {"q": "core"}).json()

    assert body["count"] == 1 and len(body["items"]) == 1


def test_query_count_bounded_with_links(
    client_for, admin_user, make_asset, hq, switch, django_assert_max_num_queries
):
    instance = _instance("A", hq)
    now = timezone.now()
    for i in range(25):
        asset = make_asset(f"a-{i:02}", site=hq, category=switch)
        SourceLink.objects.create(
            instance=instance,
            external_id=str(i),
            asset=asset,
            method="approved_candidate",
            first_seen_at=now,
            last_seen_at=now,
        )
    client = client_for(admin_user)

    with django_assert_max_num_queries(12):
        response = client.get(ASSETS, {"page_size": 50, "q": "a-"})

    assert response.json()["count"] == 25


@requires_postgres
def test_list_count_and_search_at_10k_assets(client_for, admin_user, hq, switch):
    """docs/14: common paginated asset search p95 < 2 s. Single-request approximation
    on CI hardware with trigram indexes; budget per request 1.5 s."""
    Asset.objects.bulk_create(
        [
            Asset(
                name=f"device-{i:05}",
                asset_tag=f"TAG-{i:05}",
                serial_number=f"SN{i:08}",
                manufacturer="Example Networks" if i % 2 else "Example Systems",
                model=f"EX-{i % 50}",
                category=switch,
                site=hq,
            )
            for i in range(10_000)
        ],
        batch_size=2000,
    )
    ids = list(Asset.objects.values_list("pk", flat=True)[:5000])
    AssetHostname.objects.bulk_create(
        [
            AssetHostname(asset_id=pk, hostname=f"host-{n:05}.corp.example")
            for n, pk in enumerate(ids)
        ],
        batch_size=2000,
    )
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("ANALYZE assets_asset; ANALYZE assets_assethostname")
    client = client_for(admin_user)

    timings = {}
    for label, params in {
        "first page": {"page_size": 50},
        "name search": {"q": "device-0999"},
        "serial search": {"q": "SN0000777"},
        "hostname search": {"q": "host-0420"},
        "filtered": {"manufacturer": "example networks", "page_size": 50},
    }.items():
        started = time.perf_counter()
        response = client.get(ASSETS, params)
        timings[label] = time.perf_counter() - started
        assert response.status_code == 200
        assert response.json()["count"] >= 1, label

    assert max(timings.values()) < 1.5, timings
