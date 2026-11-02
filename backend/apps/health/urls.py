from django.urls import path

from . import views

urlpatterns = [
    path("live/", views.LivenessView.as_view(), name="health-live"),
    path("ready/", views.ReadinessView.as_view(), name="health-ready"),
]
