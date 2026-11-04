"""Outbox delivery and retention (Celery beat: every minute and daily)."""

from celery import shared_task

from . import services


@shared_task(name="notifications.deliver_due", ignore_result=True)
def deliver_due() -> dict:
    return services.deliver_due()


@shared_task(name="notifications.purge", ignore_result=True)
def purge() -> int:
    return services.purge()
