from celery import shared_task

from . import services


@shared_task(name="quality.refresh_findings", ignore_result=True)
def refresh_findings() -> dict:
    """Recompute data-quality findings (hourly). Never changes assets."""
    return services.refresh()
