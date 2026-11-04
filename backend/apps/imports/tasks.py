from celery import shared_task

from . import services


@shared_task(name="imports.preview", ignore_result=True)
def preview_import(job_id: str) -> None:
    services.run_preview(job_id)


@shared_task(name="imports.commit", ignore_result=True)
def commit_import(job_id: str) -> None:
    services.run_commit(job_id)


@shared_task(name="imports.purge_originals", ignore_result=True)
def purge_originals() -> int:
    """Drop retained original files past their retention period (daily)."""
    return services.purge_expired()
