from celery import shared_task

from . import services


@shared_task(name="backups.execute", ignore_result=True)
def execute(job_id):
    services.execute(job_id)


@shared_task(name="backups.dispatch", ignore_result=True)
def dispatch():
    services.dispatch()
