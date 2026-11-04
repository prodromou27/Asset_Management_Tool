from celery import shared_task

from . import services


@shared_task(name="lifecycle.reassess", ignore_result=True)
def reassess(product_id: str | None = None) -> dict:
    """After a catalogue change: the product's assets (or every live asset) and the
    software versions the change can affect."""
    from apps.lifecycle.models import LifecycleProduct
    from apps.software import services as software

    product = LifecycleProduct.objects.filter(pk=product_id).first() if product_id else None
    if product is None or product.kind == LifecycleProduct.Kind.SOFTWARE:
        software.reassess_all()
    if product_id:
        return services.reassess_product(product_id)
    return services.reassess_all()


@shared_task(name="lifecycle.reassess_all", ignore_result=True)
def reassess_all() -> dict:
    """Scheduled: dates move, exceptions expire and asset fields change between runs."""
    from apps.software import services as software

    software.reassess_all()
    return services.reassess_all()
