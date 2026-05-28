"""
Title: urls.py — Accounts URL routing
Description:
    URL routing configuration for the accounts app. Maps authentication views
    (login and logout) to their respective URL patterns with namespace 'accounts'.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/password/", views.password_login_view, name="login_password"),
    path("logout/", views.logout_view, name="logout"),
]
