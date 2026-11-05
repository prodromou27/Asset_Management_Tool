from django.urls import path

from . import views

urlpatterns = [
    path("operations/", views.OperationalHealthView.as_view(), name="health-operations"),
    path("live/", views.LivenessView.as_view(), name="health-live"),
    path("ready/", views.ReadinessView.as_view(), name="health-ready"),
]
