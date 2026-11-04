from django.urls import path

from apps.groups import views as group_views
from apps.integrations import views as integration_views
from apps.network import views as network_views
from apps.security import views as security_views

from . import views

discovery_urlpatterns = [
    path("sources/", integration_views.DiscoverySourceListView.as_view(), name="discovery-sources"),
    path("candidates/", views.CandidateListView.as_view(), name="candidate-list"),
    path("candidates/<uuid:pk>/", views.CandidateDetailView.as_view(), name="candidate-detail"),
    path("observations/", views.ObservationListView.as_view(), name="observation-list"),
    path(
        "observations/<uuid:pk>/", views.ObservationDetailView.as_view(), name="observation-detail"
    ),
    path("conflicts/", views.ConflictListView.as_view(), name="conflict-list"),
    path("category-reviews/", views.CategoryReviewListView.as_view(), name="category-review-list"),
    path(
        "category-reviews/<uuid:pk>/reclassify/",
        views.CategoryReviewReclassifyView.as_view(),
        name="category-review-reclassify",
    ),
    path(
        "category-reviews/<uuid:pk>/dismiss/",
        views.CategoryReviewDismissView.as_view(),
        name="category-review-dismiss",
    ),
    path(
        "conflicts/<uuid:pk>/resolve/", views.ResolveConflictView.as_view(), name="conflict-resolve"
    ),
    path(
        "field-authority/", integration_views.FieldAuthorityView.as_view(), name="field-authority"
    ),
]

reconciliation_urlpatterns = [
    path("<uuid:pk>/approve/", views.ApproveCandidateView.as_view(), name="candidate-approve"),
    path("<uuid:pk>/reject/", views.RejectCandidateView.as_view(), name="candidate-reject"),
    path("<uuid:pk>/hold/", views.HoldCandidateView.as_view(), name="candidate-hold"),
    path("<uuid:pk>/assign/", views.AssignCandidateView.as_view(), name="candidate-assign"),
    path("bulk/", views.BulkDecisionView.as_view(), name="candidate-bulk"),
    path("assignees/", views.AssigneeListView.as_view(), name="candidate-assignees"),
]

integration_urlpatterns = [
    path("", integration_views.IntegrationListCreateView.as_view(), name="integration-list"),
    path(
        "<uuid:pk>/", integration_views.IntegrationDetailView.as_view(), name="integration-detail"
    ),
    path("<uuid:pk>/runs/", integration_views.SyncRunListView.as_view(), name="integration-runs"),
    path(
        "<uuid:pk>/test/", integration_views.TestConnectionView.as_view(), name="integration-test"
    ),
    path("<uuid:pk>/sync/", integration_views.SyncNowView.as_view(), name="integration-sync"),
    path(
        "<uuid:pk>/live-access/",
        integration_views.LiveAccessView.as_view(),
        name="integration-live-access",
    ),
]

asset_evidence_urlpatterns = [
    path("<uuid:pk>/evidence/", views.AssetEvidenceView.as_view(), name="asset-evidence"),
    path(
        "<uuid:pk>/observations/",
        views.AssetObservationListView.as_view(),
        name="asset-observations",
    ),
    path("<uuid:pk>/field-locks/", views.FieldLockView.as_view(), name="asset-field-lock"),
    path(
        "<uuid:pk>/field-locks/unlock/", views.FieldUnlockView.as_view(), name="asset-field-unlock"
    ),
    path("<uuid:pk>/merge/", views.MergeView.as_view(), name="asset-merge"),
    path(
        "<uuid:pk>/network-evidence/",
        network_views.AssetNetworkEvidenceView.as_view(),
        name="asset-network-evidence",
    ),
    path("<uuid:pk>/groups/", group_views.AssetGroupsView.as_view(), name="asset-groups"),
    path(
        "<uuid:pk>/security/",
        security_views.AssetSecurityView.as_view(),
        name="asset-security",
    ),
]

link_urlpatterns = [
    path("<uuid:pk>/unlink/", views.UnlinkView.as_view(), name="source-link-unlink"),
]

merge_urlpatterns = [
    path("<uuid:pk>/revert/", views.RevertMergeView.as_view(), name="merge-revert"),
]
