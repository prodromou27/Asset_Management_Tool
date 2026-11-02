from django.urls import path

from apps.integrations import views as integration_views

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
]

integration_urlpatterns = [
    path("", integration_views.IntegrationListCreateView.as_view(), name="integration-list"),
    path(
        "<uuid:pk>/", integration_views.IntegrationDetailView.as_view(), name="integration-detail"
    ),
    path("<uuid:pk>/runs/", integration_views.SyncRunListView.as_view(), name="integration-runs"),
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
]

link_urlpatterns = [
    path("<uuid:pk>/unlink/", views.UnlinkView.as_view(), name="source-link-unlink"),
]

merge_urlpatterns = [
    path("<uuid:pk>/revert/", views.RevertMergeView.as_view(), name="merge-revert"),
]
