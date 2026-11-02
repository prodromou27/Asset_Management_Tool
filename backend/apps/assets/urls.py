from django.urls import path

from . import views

asset_urlpatterns = [
    path("", views.AssetListCreateView.as_view(), name="asset-list"),
    path("<uuid:pk>/", views.AssetDetailView.as_view(), name="asset-detail"),
    path(
        "<uuid:pk>/classification/",
        views.AssetClassificationView.as_view(),
        name="asset-classification",
    ),
    path(
        "<uuid:pk>/classification/preview/",
        views.AssetClassificationPreviewView.as_view(),
        name="asset-classification-preview",
    ),
    path("<uuid:pk>/archive/", views.AssetArchiveView.as_view(), name="asset-archive"),
    path("<uuid:pk>/restore/", views.AssetRestoreView.as_view(), name="asset-restore"),
    path("<uuid:pk>/history/", views.AssetHistoryView.as_view(), name="asset-history"),
]

category_urlpatterns = [
    path("", views.CategoryListCreateView.as_view(), name="category-list"),
    path("<uuid:pk>/", views.CategoryDetailView.as_view(), name="category-detail"),
    path("<uuid:pk>/fields/", views.CategoryFieldListCreateView.as_view(), name="category-fields"),
]

custom_field_urlpatterns = [
    path("<uuid:pk>/", views.CustomFieldDetailView.as_view(), name="custom-field-detail"),
]
