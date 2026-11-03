"""Read-only Microsoft Graph v1.0 client for Microsoft 365 / Entra license data.

GET only, fixed to https://graph.microsoft.com/v1.0 (see intune/client.GraphClient). Only
``/subscribedSkus`` and ``/users`` are read; continuation links are followed only for
those two collections.
"""

from ..intune.client import GraphClient

REQUIRED_PERMISSIONS = ("Organization.Read.All", "User.Read.All")


class M365Client(GraphClient):
    user_agent = "ITAM-M365-Connector/1 (read-only)"
    required_permission = " and ".join(REQUIRED_PERMISSIONS)
    license_hint = "to read subscriptions and user license assignments"
    continuation_paths = ("/subscribedSkus", "/users")
