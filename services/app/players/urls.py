"""
Title: urls.py — URL routing for the players module
Description:
    Defines URL patterns for viewing the member list. Primary endpoint for
    admin access to club member management.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

app_name = "players"

urlpatterns = [
    path("members/", views.members_list, name="members"),
]
