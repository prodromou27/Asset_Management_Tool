from celery import shared_task

from . import services


@shared_task(name="exports.run", ignore_result=True)
def run_export(job_id: str) -> None:
    services.run_export(job_id)


@shared_task(name="exports.purge", ignore_result=True)
def purge_exports() -> int:
    """Hourly: delete expired export files and release jobs stuck by a crashed worker."""
    return services.purge_expired() + services.fail_stuck()
