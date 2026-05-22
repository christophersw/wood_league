"""
Title: admin.py — Admin registration for SiteSettings singleton
Description: Registers the SiteSettings model in the Django admin UI.
    (Auto-enqueue toggles moved to env settings in #201.)
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
    2026-05-22: Remove auto_enqueue_* from list_display (#201).
"""
from django.contrib import admin

from .models import SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Admin for the singleton settings row; hides add when one already exists."""

    list_display = ("__str__", "updated_at")

    def has_add_permission(self, request):
        """Allow add only if the singleton has not yet been created.

        Args:
            request: The current HTTP request.

        Returns:
            bool: True only when the table is empty.
        """
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Disable delete entirely; singleton must always exist.

        Args:
            request: The current HTTP request.
            obj: The model instance (optional).

        Returns:
            bool: Always False.
        """
        return False
