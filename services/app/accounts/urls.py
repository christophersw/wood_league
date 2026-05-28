"""
Title: urls.py — Accounts URL routing
Description:
    URL routing configuration for the accounts app. Maps authentication views
    (login and logout) to their respective URL patterns with namespace 'accounts'.
    The canonical login is the email-only magic-link form; password login is an
    admin escape hatch.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-28: Added email-only login route; moved password login to /login/password/
"""

from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_request, name="login"),
    path("login/password/", views.password_login_view, name="login_password"),
    path("logout/", views.logout_view, name="logout"),
]
