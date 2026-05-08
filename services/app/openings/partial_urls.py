"""HTMX partial URL patterns for opening statistics."""

from django.urls import path
from . import views

urlpatterns = [
    path("openings/<int:opening_id>/stats/", views.stats_partial, name="openings-stats-partial"),
]
