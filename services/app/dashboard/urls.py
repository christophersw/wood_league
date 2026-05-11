"""
Title: urls.py — Main URL routes for dashboard app
Description:
    Primary URL routing for the dashboard application, defining the main
    dashboard index page endpoint and app namespacing.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("healthz/", views.healthz, name="healthz"),
]
