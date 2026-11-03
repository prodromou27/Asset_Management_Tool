from django.urls import path

from . import views

urlpatterns = [
    path("subscriptions/", views.SubscriptionListView.as_view(), name="license-subscriptions"),
    path(
        "subscriptions/<uuid:pk>/",
        views.SubscriptionDetailView.as_view(),
        name="license-subscription",
    ),
    path("allocations/", views.AllocationListView.as_view(), name="license-allocations"),
]
