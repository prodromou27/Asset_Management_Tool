from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts import views as account_views
from apps.accounts.urls import auth_urlpatterns, user_urlpatterns
from apps.assets import saved_views
from apps.assets.urls import asset_urlpatterns, category_urlpatterns, custom_field_urlpatterns
from apps.organizations.urls import (
    department_urlpatterns,
    location_urlpatterns,
    site_urlpatterns,
)
from apps.reconciliation.urls import (
    asset_evidence_urlpatterns,
    discovery_urlpatterns,
    integration_urlpatterns,
    link_urlpatterns,
    merge_urlpatterns,
    reconciliation_urlpatterns,
)

urlpatterns = [
    path("api/v1/health/", include("apps.health.urls")),
    path("api/v1/auth/", include(auth_urlpatterns)),
    path("api/v1/users/", include(user_urlpatterns)),
    path("api/v1/roles/", account_views.RoleListView.as_view(), name="role-list"),
    path("api/v1/permissions/", account_views.PermissionListView.as_view(), name="permission-list"),
    path(
        "api/v1/settings/security/",
        account_views.SecuritySettingsView.as_view(),
        name="settings-security",
    ),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/sites/", include(site_urlpatterns)),
    path("api/v1/locations/", include(location_urlpatterns)),
    path("api/v1/departments/", include(department_urlpatterns)),
    path("api/v1/assets/", include(asset_urlpatterns)),
    path("api/v1/assets/", include(asset_evidence_urlpatterns)),
    path("api/v1/discovery/", include(discovery_urlpatterns)),
    path("api/v1/reconciliation/", include(reconciliation_urlpatterns)),
    path("api/v1/integrations/", include(integration_urlpatterns)),
    path("api/v1/source-links/", include(link_urlpatterns)),
    path("api/v1/merges/", include(merge_urlpatterns)),
    path("api/v1/asset-categories/", include(category_urlpatterns)),
    path("api/v1/saved-views/", saved_views.SavedViewListCreateView.as_view(), name="saved-views"),
    path(
        "api/v1/saved-views/<uuid:pk>/",
        saved_views.SavedViewDetailView.as_view(),
        name="saved-view-detail",
    ),
    path("api/v1/custom-fields/", include(custom_field_urlpatterns)),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
