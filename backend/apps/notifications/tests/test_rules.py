"""Notification rules: thresholds, dedup, recipients and scope (Task 018b, docs/10)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.assets.tests.fixtures import grant
from apps.audit.models import AuditEvent
from apps.domains.models import Certificate, DomainRegistration
from apps.integrations.models import SyncRun
from apps.lifecycle.models import LifecycleAssessment
from apps.notifications import rules
from apps.notifications.models import AlertLedger, NotificationRule, OutboxMessage, SmtpProfile

pytestmark = pytest.mark.django_db
URL = "/api/v1/notifications/rules/"
TODAY = date(2026, 11, 4)


@pytest.fixture
def mail_on(db):
    SmtpProfile.objects.update_or_create(
        pk=1,
        defaults={
            "enabled": True,
            "host": "smtp.example.test",
            "from_address": "itam@example.test",
        },
    )


@pytest.fixture
def admin(admin_user, client_for):
    return client_for(admin_user)


def make_rule(client, event, recipients, **extra):
    body = {"name": f"{event} rule", "event": event, "recipients": [str(u.pk) for u in recipients]}
    response = client.post(URL, {**body, **extra}, format="json")
    assert response.status_code == 201, response.json()
    return NotificationRule.objects.get(pk=response.json()["id"])


def cert(cn, days, today=TODAY):
    end = datetime.combine(today + timedelta(days=days), datetime.min.time(), UTC) + timedelta(
        hours=12
    )
    return Certificate.objects.create(
        fingerprint_sha256=f"{abs(hash(cn)):064x}"[:64],
        common_name=cn,
        sans=[cn],
        not_before=end - timedelta(days=365),
        not_after=end,
        pem="-----BEGIN CERTIFICATE-----",
        source=Certificate.Source.UPLOADED,
        first_seen_at=timezone.now(),
    )


def messages():
    return list(OutboxMessage.objects.order_by("queued_at"))


def run(today=TODAY):
    return rules.evaluate_all(today)


def test_certificate_thresholds_are_announced_once_per_tier(admin, admin_user, mail_on):
    make_rule(admin, "certificate_expiry", [admin_user])
    cert("<b>vpn</b>.example.test", 20)
    cert("later.example.test", 200)

    assert run()["messages"] == 1
    [first] = messages()
    assert first.to_address == admin_user.email and first.event_type == "certificate_expiry"
    assert "1 certificate expiring" in first.subject
    assert "&lt;b&gt;vpn" in first.body_html and "20 days left" in first.body_text
    assert "later.example.test" not in first.body_text

    assert run()["messages"] == 0  # already told
    assert run(TODAY + timedelta(days=5))["messages"] == 0  # still the 30-day tier
    assert run(TODAY + timedelta(days=6))["messages"] == 1  # 14 days left: next tier
    assert run(TODAY + timedelta(days=21))["messages"] == 1  # expired
    assert run(TODAY + timedelta(days=30))["messages"] == 0
    assert AlertLedger.objects.count() == 3


def test_nothing_is_evaluated_while_mail_is_disabled(admin, admin_user):
    make_rule(admin, "certificate_expiry", [admin_user])
    cert("vpn.example.test", 3)
    assert run() == {"skipped": "mail disabled"}
    assert not OutboxMessage.objects.exists() and not AlertLedger.objects.exists()


def test_domains_with_unknown_expiry_are_not_alerted(admin, admin_user, mail_on):
    make_rule(admin, "domain_expiry", [admin_user])
    DomainRegistration.objects.create(fqdn="unknown.example")
    DomainRegistration.objects.create(
        fqdn="example.org", expires_on=TODAY + timedelta(days=10), expiry_evidence="Portal"
    )
    run()
    [message] = messages()
    assert "example.org" in message.body_text and "unknown.example" not in message.body_text


def test_lifecycle_alerts_follow_site_scope_and_verified_evidence(
    admin, client_for, make_user, hq, branch, switch, make_asset, mail_on
):
    hq_asset = make_asset("sw-hq-01", site=hq, category=switch)
    br_asset = make_asset("sw-br-01", site=branch, category=switch)
    now = timezone.now()

    def assess(asset, status, quality="vendor", days=25, dimension="hardware"):
        LifecycleAssessment.objects.create(
            asset=asset,
            dimension=dimension,
            status=status,
            effective_status=status,
            milestone_type="end_of_support",
            milestone_date=TODAY + timedelta(days=days),
            days_remaining=days,
            evidence_quality=quality,
            assessed_on=TODAY,
            assessed_at=now,
        )

    assess(hq_asset, "expiring")
    assess(br_asset, "expiring")
    assess(hq_asset, "unverified", quality="", dimension="os")  # never claims end of support
    hq_manager = grant(make_user("hq.mgr", roles=["itam_manager"], email="hq.mgr@example.test"), hq)
    no_mail = make_user("no.mail", roles=["itam_manager"], all_sites=True)
    rule = make_rule(admin, "lifecycle_eol", [hq_manager, no_mail])

    preview = admin.post(f"{URL}{rule.pk}/preview/").json()
    by_user = {r["user"]["username"]: r for r in preview["recipients"]}
    assert by_user["no.mail"]["eligible"] is False
    assert by_user["hq.mgr"]["pending"] == 1  # branch asset outside the manager's sites
    assert not OutboxMessage.objects.exists()  # preview sends nothing

    run()
    [message] = messages()
    assert message.to_address == "hq.mgr@example.test"
    assert "sw-hq-01" in message.body_text and "sw-br-01" not in message.body_text
    rule.refresh_from_db()
    assert "1 recipient(s) skipped" in rule.last_run_summary


def test_integration_failure_streaks_and_stale(admin, admin_user, mail_on, settings):
    from apps.integrations.models import DiscoverySource, IntegrationInstance
    from apps.organizations.models import Site

    site = Site.objects.create(code="HQ", name="HQ")
    instance = IntegrationInstance.objects.create(
        source=DiscoverySource.objects.first(), name="LibreNMS HQ", default_site=site
    )

    clock = [timezone.now() - timedelta(days=1)]

    def runs(*statuses):
        # Distinct start times: runs created in the same instant would have no order.
        for status in statuses:
            clock[0] += timedelta(minutes=10)
            run_ = SyncRun.objects.create(
                instance=instance, mode="full", status=status, triggered_by="test"
            )
            SyncRun.objects.filter(pk=run_.pk).update(
                started_at=clock[0], finished_at=clock[0] + timedelta(minutes=1)
            )

    make_rule(admin, "integration_failure", [admin_user], failure_count=3)
    runs("failed", "failed")
    run()
    assert not OutboxMessage.objects.exists()  # only two in a row
    runs("failed")
    run()
    assert len(messages()) == 1 and "3 failed runs in a row" in messages()[0].body_text
    runs("failed")
    run()
    assert len(messages()) == 1  # same streak
    runs("succeeded", "failed", "failed", "failed")
    run()
    assert len(messages()) == 2  # a new streak

    IntegrationInstance.objects.filter(pk=instance.pk).update(
        last_success_at=timezone.now() - timedelta(hours=100), stale_after_hours=48
    )
    run()
    assert len(messages()) == 3 and "Stale" in messages()[-1].body_text


def test_recipients_need_access(admin, make_user, mail_on):
    reader = make_user("reader", roles=["read_only"], email="reader@example.test")
    rule = make_rule(admin, "integration_failure", [reader])
    preview = admin.post(f"{URL}{rule.pk}/preview/").json()
    assert preview["recipients"][0]["eligible"] is False  # no integrations.manage


def test_rule_api_validation_versions_and_audit(admin, admin_user, client_for, auditor_user):
    bad = admin.post(
        URL,
        {"name": "x", "event": "certificate_expiry", "thresholds": [0]},
        format="json",
    )
    assert bad.status_code in (400, 422)
    rule = make_rule(admin, "certificate_expiry", [admin_user])
    assert rule.thresholds == [90, 60, 30, 14, 7]
    url = f"{URL}{rule.pk}/"
    renamed = admin.patch(url, {"name": "Cert owners"}, format="json", HTTP_IF_MATCH='"1"')
    assert renamed.status_code == 200
    rule.refresh_from_db()
    assert (rule.version, rule.policy_version) == (2, 1)  # renaming keeps the alert keys
    changed = admin.patch(url, {"thresholds": [30, 7]}, format="json", HTTP_IF_MATCH='"2"')
    assert changed.status_code == 200 and changed.json()["thresholds"] == [30, 7]
    rule.refresh_from_db()
    assert rule.policy_version == 2
    assert admin.patch(url, {"name": "x"}, format="json").status_code == 428

    auditor = client_for(auditor_user)
    assert auditor.get(URL).status_code == 200
    assert auditor.patch(url, {"name": "x"}, format="json", HTTP_IF_MATCH='"3"').status_code == 403
    assert auditor.get("/api/v1/notifications/recipients/").status_code == 403
    recipients = admin.get("/api/v1/notifications/recipients/").json()
    assert all("email" not in r for r in recipients)

    assert admin.delete(url).status_code == 204
    actions = set(
        AuditEvent.objects.filter(action__startswith="notifications.rule.").values_list(
            "action", flat=True
        )
    )
    assert actions == {
        "notifications.rule.create",
        "notifications.rule.update",
        "notifications.rule.delete",
    }


def test_alert_template_preview_uses_sample_items(admin):
    preview = admin.post(
        "/api/v1/notifications/templates/certificate_expiry/preview/", {}, format="json"
    ).json()
    assert "intranet.example.org" in preview["body_text"] and "2 certificates" in preview["subject"]
