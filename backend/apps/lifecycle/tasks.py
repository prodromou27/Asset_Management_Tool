from celery import shared_task

from . import services


@shared_task(name="lifecycle.reassess", ignore_result=True)
def reassess(product_id: str | None = None) -> dict:
    """After a catalogue change: the product's assets, or every live asset."""
    if product_id:
        return services.reassess_product(product_id)
    return services.reassess_all()


@shared_task(name="lifecycle.reassess_all", ignore_result=True)
def reassess_all() -> dict:
    """Scheduled: dates move, exceptions expire and asset fields change between runs."""
    return services.reassess_all()
