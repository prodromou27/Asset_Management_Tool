from django.urls import path

from . import views

urlpatterns = [
    path("policy/", views.PolicyView.as_view()),
    path("summary/", views.SummaryView.as_view()),
    path("report/", views.ReportView.as_view()),
    path("jobs/", views.JobListView.as_view()),
    path("jobs/<uuid:pk>/", views.JobDetailView.as_view()),
    path("jobs/<uuid:pk>/report/", views.JobReportView.as_view()),
    path("jobs/<uuid:pk>/verify/", views.VerifyView.as_view()),
    path("drills/", views.DrillListView.as_view()),
    path("drills/<uuid:pk>/report/", views.DrillReportView.as_view()),
]
