from celery import shared_task

from . import services


@shared_task(name="reconciliation.refresh_source_freshness", ignore_result=True)
def refresh_source_freshness() -> int:
    """Marks source links stale past each instance's threshold. Never deletes assets."""
    return services.refresh_freshness()
