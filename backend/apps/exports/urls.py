from django.urls import path

from . import views

urlpatterns = [
    path("", views.ExportListCreateView.as_view(), name="export-list"),
    path("families/", views.ExportFamilyListView.as_view(), name="export-families"),
    path("<uuid:pk>/", views.ExportDetailView.as_view(), name="export-detail"),
    path("<uuid:pk>/download/", views.ExportDownloadView.as_view(), name="export-download"),
]
