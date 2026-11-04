from django.urls import path

from . import views

urlpatterns = [
    path("", views.JobListCreateView.as_view(), name="import-list"),
    path("templates/", views.TemplateListView.as_view(), name="import-templates"),
    path(
        "templates/<str:family>/csv/",
        views.TemplateDownloadView.as_view(),
        name="import-template-download",
    ),
    path("<uuid:pk>/", views.JobDetailView.as_view(), name="import-detail"),
    path("<uuid:pk>/preview/", views.JobPreviewView.as_view(), name="import-preview"),
    path("<uuid:pk>/rows/", views.JobRowsView.as_view(), name="import-rows"),
    path("<uuid:pk>/errors/", views.JobErrorsView.as_view(), name="import-errors"),
    path("<uuid:pk>/commit/", views.JobCommitView.as_view(), name="import-commit"),
    path("<uuid:pk>/rollback/", views.JobRollbackView.as_view(), name="import-rollback"),
]
