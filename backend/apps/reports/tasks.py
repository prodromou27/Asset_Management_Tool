from celery import shared_task

from .digests import dispatch


@shared_task(name="reports.dispatch_digests", ignore_result=True)
def dispatch_digests():
    return dispatch()
