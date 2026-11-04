from django.urls import path

from . import views

domain_urlpatterns = [
    path("", views.DomainListView.as_view(), name="domains"),
    path("<uuid:pk>/", views.DomainDetailView.as_view(), name="domain"),
    path("<uuid:pk>/retire/", views.DomainRetireView.as_view(), name="domain-retire"),
]

certificate_urlpatterns = [
    path("", views.CertificateListView.as_view(), name="certificates"),
    path("deployments/", views.DeploymentListView.as_view(), name="certificate-deployments"),
    path("<uuid:pk>/", views.CertificateDetailView.as_view(), name="certificate"),
]

endpoint_urlpatterns = [
    path("", views.TlsEndpointListView.as_view(), name="tls-endpoints"),
    path("<uuid:pk>/", views.TlsEndpointDetailView.as_view(), name="tls-endpoint"),
    path("<uuid:pk>/retire/", views.TlsEndpointRetireView.as_view(), name="tls-endpoint-retire"),
    path("<uuid:pk>/check/", views.TlsEndpointCheckView.as_view(), name="tls-endpoint-check"),
]

asset_urlpatterns = [
    path(
        "<uuid:pk>/certificates/", views.AssetCertificatesView.as_view(), name="asset-certificates"
    ),
]
