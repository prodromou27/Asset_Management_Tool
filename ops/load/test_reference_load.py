"""Opt-in, PostgreSQL-only synthetic reference workload; never a live-site load tool."""

import json
import math
import os
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from apps.accounts.middleware import SESSION_AUTH_AT, SESSION_LAST_SEEN
from apps.accounts.models import Role, User
from apps.assets.models import Asset, AssetCategory, AssetHostname, AssetIPAddress
from apps.lifecycle.models import (
    LifecycleAssessment,
    LifecycleMilestone,
    LifecycleProduct,
    LifecycleSource,
)
from apps.lifecycle.services import reassess_assets
from apps.organizations.models import Site, UserSiteGrant
from apps.software.models import SoftwareInstallation, SoftwareProduct, SoftwareVersion
from django.conf import settings
from django.db import connection
from django.test import Client
from django.utils import timezone

if (
    os.environ.get("ITAM_RUN_REFERENCE_LOAD") != "1"
    or settings.SETTINGS_MODULE != "config.settings.test"
    or connection.vendor != "postgresql"
    or settings.DATABASES["default"].get("HOST") not in {"localhost", "127.0.0.1", "::1"}
):
    raise pytest.UsageError(
        "Reference load requires explicit opt-in, test settings and loopback PostgreSQL."
    )

RESULT = Path(__file__).parent / "results" / "report.json"
CONCURRENCY = 4
SAMPLES_PER_SHAPE = 40


@pytest.fixture(scope="session")
def django_db_keepdb():
    return False


@pytest.fixture
def transactional_db(django_db_setup, django_db_blocker):
    # Keep append-only TRUNCATE guards intact; drop the entire disposable DB at teardown.
    with django_db_blocker.unblock():
        assert str(connection.settings_dict["NAME"]).startswith("test_")
        assert connection.get_autocommit()
        yield


def test_reference_load(live_server, settings):
    RESULT.parent.mkdir(exist_ok=True)
    RESULT.unlink(missing_ok=True)
    target = urlsplit(live_server.url)
    assert target.scheme == "http" and target.hostname in {"localhost", "127.0.0.1", "::1"}
    assert not Asset.objects.exists() and not User.objects.exists()
    settings.ITAM_ALLOW_LIVE_INTEGRATIONS = False
    settings.CELERY_BROKER_URL = "memory://"
    settings.CELERY_RESULT_BACKEND = "cache+memory://"
    report = {"status": "running", "synthetic": True, "database": "postgresql"}
    RESULT.write_text(json.dumps(report), encoding="utf-8")
    try:
        started = time.perf_counter()
        hq = Site.objects.create(code="LOAD-HQ", name="Synthetic reference HQ")
        remote = Site.objects.create(code="LOAD-REMOTE", name="Synthetic remote site")
        category = AssetCategory.objects.get(code="workstations-laptop")
        monitor = AssetCategory.objects.get(code="monitors")
        user = User.objects.create_user(
            "load.scoped", password=None, display_name="Synthetic load operator"
        )
        user.roles.add(Role.objects.get(code="itam_manager"))
        UserSiteGrant.objects.create(user=user, site=hq)
        assets = [
            Asset(
                name=f"load-{i:05}",
                asset_tag=f"LOAD-{i:05}",
                serial_number=f"LSN{i:08}",
                manufacturer="Synthetic Systems",
                model="Reference Laptop" if i < 10000 else "Monitor",
                category=category if i < 10000 else monitor,
                site=remote if i % 10 == 0 else hq,
            )
            for i in range(30000)
        ]
        Asset.objects.bulk_create(assets, batch_size=2000)
        AssetHostname.objects.bulk_create(
            [
                AssetHostname(asset=a, hostname=f"host-{i:05}.example.invalid")
                for i, a in enumerate(assets[:10000])
            ],
            batch_size=2000,
        )
        # Documentation-range addresses are stored facts only; no network traffic is sent.
        AssetIPAddress.objects.bulk_create(
            [
                AssetIPAddress(asset=a, site=a.site, address=f"198.18.{i // 254}.{i % 254 + 1}")
                for i, a in enumerate(assets[:10000])
            ],
            batch_size=2000,
        )
        product = SoftwareProduct.objects.create(name="Synthetic application", name_key="synthetic")
        versions = SoftwareVersion.objects.bulk_create(
            [
                SoftwareVersion(product=product, version=str(i), version_key=str(i))
                for i in range(100)
            ]
        )
        now = timezone.now()
        for start in range(0, 10000, 50):
            SoftwareInstallation.objects.bulk_create(
                [
                    SoftwareInstallation(
                        asset=a,
                        version=v,
                        raw_name=product.name,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    for a in assets[start : start + 50]
                    for v in versions
                ],
                batch_size=5000,
            )
        assert Asset.objects.count() == 30000
        assert AssetIPAddress.objects.count() == 10000
        assert SoftwareInstallation.objects.count() == 1000000
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")
            cursor.execute("SELECT version()")
            postgres_version = cursor.fetchone()[0]
        report.update(
            {
                "assets": 30000,
                "ip_assets": 10000,
                "installations": 1000000,
                "seed_seconds": time.perf_counter() - started,
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "cpu_count": os.cpu_count(),
                    "postgresql": postgres_version,
                },
                "transport": "loopback HTTP / Django test server",
                "concurrency": CONCURRENCY,
            }
        )
        session = Client()
        session.force_login(user)
        authenticated = session.session
        authenticated[SESSION_AUTH_AT] = authenticated[SESSION_LAST_SEEN] = time.time()
        authenticated.save()
        cookies = {
            settings.SESSION_COOKIE_NAME: session.cookies[settings.SESSION_COOKIE_NAME].value
        }
        shapes = {
            "first_page": ({"page_size": 50}, 27000),
            "name": ({"q": "load-0999", "page_size": 50}, 9),
            "serial": ({"q": "LSN00007777", "page_size": 50}, 1),
            "hostname": ({"q": "host-04201", "page_size": 50}, 1),
            "category": ({"category": str(category.pk), "page_size": 50}, 9000),
        }

        def worker(worker_id):
            samples = {label: [] for label in shapes}
            with httpx.Client(
                base_url=live_server.url,
                cookies=cookies,
                trust_env=False,
                timeout=15,
                follow_redirects=False,
            ) as client:
                for n in range(SAMPLES_PER_SHAPE // CONCURRENCY + 1):
                    labels = list(shapes)
                    offset = (n + worker_id) % len(labels)
                    for label in labels[offset:] + labels[:offset]:
                        params, count = shapes[label]
                        began = time.perf_counter()
                        response = client.get("/api/v1/assets/", params=params)
                        duration = time.perf_counter() - began
                        assert response.status_code == 200, (label, response.status_code)
                        body = response.json()
                        assert body["count"] == count, (label, body["count"], count)
                        assert 0 < len(body["items"]) <= 50
                        assert all(row["name"][-1] != "0" for row in body["items"])
                        if n:  # One warm-up of each shape per client is excluded.
                            samples[label].append(duration)
            return samples

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            results = list(pool.map(worker, range(CONCURRENCY)))
        measurements = {}
        for label in shapes:
            samples = sorted(t for result in results for t in result[label])
            assert len(samples) == SAMPLES_PER_SHAPE
            measurements[label] = {
                "samples_seconds": samples,
                "count": len(samples),
                "p95_seconds": samples[math.ceil(len(samples) * 0.95) - 1],
                "max_seconds": max(samples),
            }
        report["search"] = measurements
        source = LifecycleSource.objects.create(
            publisher="Synthetic Systems",
            title="Synthetic cached support date",
            source_type="vendor",
            collected_on=now.date(),
            last_verified_on=now.date(),
        )
        hardware = LifecycleProduct.objects.create(
            kind="hardware",
            vendor="Synthetic Systems",
            vendor_key="synthetic systems",
            name="Reference Laptop",
            name_key="reference laptop",
        )
        deadline = now.date() + timedelta(days=1000)
        LifecycleMilestone.objects.create(
            product=hardware,
            source=source,
            milestone_type="end_of_support",
            date=deadline,
            verification="verified",
        )
        began = time.perf_counter()
        counts = reassess_assets([a.pk for a in assets[:10000]])
        elapsed = time.perf_counter() - began
        report["lifecycle"] = {
            "assets": counts["assets"],
            "seconds": elapsed,
            "cached_catalogue": True,
            "runs": 1,
        }
        assert counts["assets"] == 10000
        assert (
            LifecycleAssessment.objects.filter(
                dimension="hardware",
                product=hardware,
                milestone_date=deadline,
                effective_status="eol_announced",
            ).count()
            == 10000
        )
        assert all(m["p95_seconds"] < 2 for m in measurements.values()), measurements
        assert elapsed < 900, elapsed
        report["status"] = "measurements_passed"
    except BaseException:
        report["status"] = "failed"
        raise
    finally:
        RESULT.write_text(json.dumps(report, indent=2), encoding="utf-8")
