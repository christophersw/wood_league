"""
Title: partial_urls.py — HTMX partial URL patterns for member management
Description:
    Defines URL patterns for HTMX partial views that handle inline member
    operations: adding, editing, deleting, and inviting club members.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

urlpatterns = [
    path("members/add/", views.add_member, name="members-add"),
    path("members/<int:pk>/edit/", views.edit_member, name="members-edit"),
    path("members/<int:pk>/delete/", views.delete_member, name="members-delete"),
]
