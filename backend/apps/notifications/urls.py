from django.urls import path

from . import views

settings_urlpatterns = [
    path("smtp/", views.SmtpSettingsView.as_view(), name="settings-smtp"),
]

smtp_urlpatterns = [
    path("test/", views.SmtpTestView.as_view(), name="smtp-test"),
    path("test-email/", views.SmtpTestEmailView.as_view(), name="smtp-test-email"),
]

urlpatterns = [
    path("outbox/", views.OutboxListView.as_view(), name="outbox"),
    path("outbox/stats/", views.OutboxStatsView.as_view(), name="outbox-stats"),
    path("outbox/<uuid:pk>/retry/", views.OutboxRetryView.as_view(), name="outbox-retry"),
    path("outbox/<uuid:pk>/cancel/", views.OutboxCancelView.as_view(), name="outbox-cancel"),
    path("rules/", views.RuleListView.as_view(), name="notification-rules"),
    path("rules/<uuid:pk>/", views.RuleDetailView.as_view(), name="notification-rule"),
    path(
        "rules/<uuid:pk>/preview/",
        views.RulePreviewView.as_view(),
        name="notification-rule-preview",
    ),
    path("recipients/", views.RecipientListView.as_view(), name="notification-recipients"),
    path("templates/", views.TemplateListView.as_view(), name="notification-templates"),
    path(
        "templates/<slug:code>/", views.TemplateDetailView.as_view(), name="notification-template"
    ),
    path(
        "templates/<slug:code>/preview/",
        views.TemplatePreviewView.as_view(),
        name="notification-template-preview",
    ),
]
