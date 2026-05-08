"""
Title: admin.py — Django admin interface for user management
Description:
    Configures the Django admin interface for the User model with email-based authentication.
    Provides admin list display, filtering, and search capabilities for user management
    and role-based access control.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin interface for the User model, configured for email-based authentication."""
    list_display = ["email", "role", "is_active", "created_at"]
    list_filter = ["role", "is_active"]
    search_fields = ["email"]
    ordering = ["email"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Permissions", {"fields": ["role", "is_active"]}),
    ]
    add_fieldsets = [
        (None, {"fields": ["email", "password1", "password2", "role"]}),
    ]
    filter_horizontal: tuple[str, ...] = ()
