from celery import shared_task

from . import services


@shared_task(name="groups.evaluate_all", ignore_result=True)
def evaluate_all() -> int:
    """Re-evaluate dynamic groups hourly so they follow changing asset facts."""
    return services.evaluate_all()
