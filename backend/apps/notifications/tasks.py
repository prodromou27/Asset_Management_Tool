"""Outbox delivery, retention and notification rules (Celery beat)."""

from celery import shared_task

from . import rules, services


@shared_task(name="notifications.deliver_due", ignore_result=True)
def deliver_due() -> dict:
    return services.deliver_due()


@shared_task(name="notifications.purge", ignore_result=True)
def purge() -> int:
    return services.purge()


@shared_task(name="notifications.evaluate_rules", ignore_result=True)
def evaluate_rules() -> dict:
    return rules.evaluate_all()
