from django.urls import path

from . import views

urlpatterns = [
    path("products/", views.SoftwareProductListView.as_view(), name="software-products"),
    path("products/<int:pk>/", views.SoftwareProductDetailView.as_view(), name="software-product"),
    path(
        "installations/",
        views.SoftwareInstallationListView.as_view(),
        name="software-installations",
    ),
    path(
        "installations/<int:pk>/remove/",
        views.InstallationRemoveView.as_view(),
        name="software-installation-remove",
    ),
    path(
        "versions/<int:pk>/lifecycle/approve/",
        views.VersionApproveView.as_view(),
        name="software-version-approve",
    ),
    path(
        "versions/<int:pk>/lifecycle/reject/",
        views.VersionRejectView.as_view(),
        name="software-version-reject",
    ),
]

asset_urlpatterns = [
    path("<uuid:pk>/software/", views.AssetSoftwareView.as_view(), name="asset-software"),
]
