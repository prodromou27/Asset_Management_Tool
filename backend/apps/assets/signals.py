"""Asset domain signals. Other apps react without the assets app importing them."""

from django.dispatch import Signal

# Sent inside the reclassification transaction: sender=Asset, asset, request, reason.
asset_reclassified = Signal()
