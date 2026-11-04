from django.urls import path

from . import views

urlpatterns = [
    path("", views.GroupListCreateView.as_view(), name="group-list"),
    path("fields/", views.RuleFieldsView.as_view(), name="group-rule-fields"),
    path("preview/", views.RulePreviewView.as_view(), name="group-rule-preview"),
    path("<uuid:pk>/", views.GroupDetailView.as_view(), name="group-detail"),
    path("<uuid:pk>/archive/", views.GroupArchiveView.as_view(), name="group-archive"),
    path("<uuid:pk>/preview/", views.GroupPreviewView.as_view(), name="group-preview"),
    path("<uuid:pk>/assets/", views.GroupAssetsView.as_view(), name="group-assets"),
    path("<uuid:pk>/members/", views.GroupMembersView.as_view(), name="group-members"),
    path("<uuid:pk>/evaluate/", views.GroupEvaluateView.as_view(), name="group-evaluate"),
    path("<uuid:pk>/rule-versions/", views.GroupRuleVersionsView.as_view(), name="group-rules"),
]
