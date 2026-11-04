from django.urls import path

from . import entitlement_views as ent
from . import views

urlpatterns = [
    path("subscriptions/", views.SubscriptionListView.as_view(), name="license-subscriptions"),
    path(
        "subscriptions/<uuid:pk>/",
        views.SubscriptionDetailView.as_view(),
        name="license-subscription",
    ),
    path("allocations/", views.AllocationListView.as_view(), name="license-allocations"),
    path("products/", ent.LicenseProductListView.as_view(), name="license-products"),
    path("products/<uuid:pk>/", ent.LicenseProductDetailView.as_view(), name="license-product"),
    path("entitlements/", ent.LicenseEntitlementListView.as_view(), name="license-entitlements"),
    path(
        "entitlements/<uuid:pk>/",
        ent.LicenseEntitlementDetailView.as_view(),
        name="license-entitlement",
    ),
    path(
        "entitlements/<uuid:pk>/retire/",
        ent.LicenseEntitlementRetireView.as_view(),
        name="license-entitlement-retire",
    ),
    path(
        "entitlements/<uuid:pk>/allocations/",
        ent.LicenseAllocateView.as_view(),
        name="license-entitlement-allocate",
    ),
    path(
        "entitlement-allocations/",
        ent.LicenseEntitlementAllocationListView.as_view(),
        name="license-entitlement-allocations",
    ),
    path(
        "entitlement-allocations/<uuid:pk>/end/",
        ent.LicenseAllocationEndView.as_view(),
        name="license-entitlement-allocation-end",
    ),
]
