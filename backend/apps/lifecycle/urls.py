from django.urls import path

from . import views

urlpatterns = [
    path("products/", views.ProductListCreateView.as_view(), name="lifecycle-products"),
    path("products/<uuid:pk>/", views.ProductDetailView.as_view(), name="lifecycle-product"),
    path(
        "products/<uuid:pk>/statement/",
        views.ProductStatementView.as_view(),
        name="lifecycle-product-statement",
    ),
    path("products/<uuid:pk>/aliases/", views.ProductAliasView.as_view(), name="lifecycle-aliases"),
    path(
        "products/<uuid:pk>/milestones/",
        views.ProductMilestoneView.as_view(),
        name="lifecycle-milestones",
    ),
    path(
        "products/<uuid:pk>/revisions/",
        views.ProductRevisionsView.as_view(),
        name="lifecycle-revisions",
    ),
    path(
        "products/<uuid:pk>/assets/",
        views.ProductAssetsView.as_view(),
        name="lifecycle-product-assets",
    ),
    path(
        "products/<uuid:pk>/reassess/",
        views.ProductReassessView.as_view(),
        name="lifecycle-product-reassess",
    ),
    path(
        "aliases/<uuid:pk>/remove/", views.AliasRemoveView.as_view(), name="lifecycle-alias-remove"
    ),
    path("milestones/<uuid:pk>/", views.MilestoneDetailView.as_view(), name="lifecycle-milestone"),
    path(
        "milestones/<uuid:pk>/review/",
        views.MilestoneReviewView.as_view(),
        name="lifecycle-milestone-review",
    ),
    path("sources/", views.SourceListCreateView.as_view(), name="lifecycle-sources"),
    path("sources/<uuid:pk>/", views.SourceDetailView.as_view(), name="lifecycle-source"),
    path(
        "vendor-aliases/",
        views.VendorAliasListCreateView.as_view(),
        name="lifecycle-vendor-aliases",
    ),
    path(
        "vendor-aliases/<uuid:pk>/remove/",
        views.VendorAliasRemoveView.as_view(),
        name="lifecycle-vendor-alias-remove",
    ),
    path("findings/", views.FindingListView.as_view(), name="lifecycle-findings"),
    path("summary/", views.SummaryView.as_view(), name="lifecycle-summary"),
    path("policy/", views.PolicyView.as_view(), name="lifecycle-policy"),
    path("matches/", views.MatchListView.as_view(), name="lifecycle-matches"),
    path(
        "matches/<uuid:pk>/approve/",
        views.MatchApproveView.as_view(),
        name="lifecycle-match-approve",
    ),
    path(
        "matches/<uuid:pk>/reject/", views.MatchRejectView.as_view(), name="lifecycle-match-reject"
    ),
    path("exceptions/", views.ExceptionListView.as_view(), name="lifecycle-exceptions"),
    path(
        "exceptions/<uuid:pk>/revoke/",
        views.ExceptionRevokeView.as_view(),
        name="lifecycle-exception-revoke",
    ),
    path("reassess/", views.ReassessAllView.as_view(), name="lifecycle-reassess"),
]

asset_urlpatterns = [
    path("<uuid:pk>/lifecycle/", views.AssetLifecycleView.as_view(), name="asset-lifecycle"),
    path(
        "<uuid:pk>/lifecycle/reassess/",
        views.AssetReassessView.as_view(),
        name="asset-lifecycle-reassess",
    ),
    path(
        "<uuid:pk>/lifecycle/exceptions/",
        views.AssetExceptionCreateView.as_view(),
        name="asset-lifecycle-exceptions",
    ),
]
