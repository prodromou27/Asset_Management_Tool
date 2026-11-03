from celery import shared_task

from . import sync


@shared_task(name="integrations.run_sync", ignore_result=True, acks_late=True)
def run_sync_task(run_id: str) -> None:
    """Execute one queued sync run. Idempotent: a run that is not queued is ignored."""
    sync.execute(run_id)


@shared_task(name="integrations.dispatch_due_syncs", ignore_result=True)
def dispatch_due_syncs() -> int:
    """Queue scheduled syncs for enabled, approved, adapter-backed instances."""
    return sync.dispatch_due()
