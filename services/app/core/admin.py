"""
Title: admin.py — Admin registration for SiteSettings singleton
Description: Registers the SiteSettings model so admins can flip auto-enqueue
    flags from the Django admin UI.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
"""
from django.contrib import admin

from .models import SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Admin for the singleton settings row; hides add when one already exists."""

    list_display = ("__str__", "auto_enqueue_stockfish", "auto_enqueue_lc0", "updated_at")

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
