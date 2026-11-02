from django.urls import path

from . import views

auth_urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("providers/", views.ProvidersView.as_view(), name="auth-providers"),
    path("local/login/", views.LocalLoginView.as_view(), name="auth-login"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("password/change/", views.ChangePasswordView.as_view(), name="auth-password-change"),
]

user_urlpatterns = [
    path("", views.UserListCreateView.as_view(), name="user-list"),
    path("<uuid:pk>/", views.UserDetailView.as_view(), name="user-detail"),
    path("<uuid:pk>/disable/", views.DisableUserView.as_view(), name="user-disable"),
    path("<uuid:pk>/enable/", views.EnableUserView.as_view(), name="user-enable"),
    path("<uuid:pk>/unlock/", views.UnlockUserView.as_view(), name="user-unlock"),
    path(
        "<uuid:pk>/reset-password/", views.ResetPasswordView.as_view(), name="user-reset-password"
    ),
]
