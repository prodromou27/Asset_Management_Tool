from django.urls import path

from . import views

site_urlpatterns = [
    path("", views.SiteListCreateView.as_view(), name="site-list"),
    path("<uuid:pk>/", views.SiteDetailView.as_view(), name="site-detail"),
]

location_urlpatterns = [
    path("", views.LocationListCreateView.as_view(), name="location-list"),
    path("<uuid:pk>/", views.LocationDetailView.as_view(), name="location-detail"),
]

department_urlpatterns = [
    path("", views.DepartmentListCreateView.as_view(), name="department-list"),
    path("<uuid:pk>/", views.DepartmentDetailView.as_view(), name="department-detail"),
]
