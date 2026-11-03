from django.urls import path

from . import views

urlpatterns = [
    path("findings/", views.FindingListView.as_view(), name="quality-findings"),
    path("findings/<uuid:pk>/assign/", views.FindingAssignView.as_view(), name="quality-assign"),
    path("findings/<uuid:pk>/dismiss/", views.FindingDismissView.as_view(), name="quality-dismiss"),
    path("findings/<uuid:pk>/reopen/", views.FindingReopenView.as_view(), name="quality-reopen"),
    path("summary/", views.FindingSummaryView.as_view(), name="quality-summary"),
    path("refresh/", views.FindingRefreshView.as_view(), name="quality-refresh"),
]
