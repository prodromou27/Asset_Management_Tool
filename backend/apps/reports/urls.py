from django.urls import path

from . import views

urlpatterns = [
    path("schedules/", views.ScheduleListView.as_view(), name="report-schedules"),
    path("schedules/<uuid:pk>/", views.ScheduleDetailView.as_view(), name="report-schedule"),
    path("<str:kind>/", views.ReportView.as_view(), name="report-data"),
]
