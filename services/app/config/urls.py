"""
Title: config/urls.py — Root URL routing configuration
Description:
    Root-level URL routing for the Wood League chess application. Maps URL paths to
    app-specific handlers including the dashboard, games, search, openings, authentication,
    player admin, analysis tools, HTMX partial views, and RESTful API endpoints.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
from django.contrib import admin
from django.urls import include, path

from search import views as search_views

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("games/", include("games.urls")),
    path("search/", include("search.urls")),
    # Flat alias so reverse("search_index") works in tests + non-namespaced code
    path("search/", search_views.search_index, name="search_index"),
    path("openings/", include("openings.urls")),
    path("auth/", include("accounts.urls")),
    path("admin/", include("players.urls")),
    path("admin/", include("analysis.urls")),
    path("_partials/", include("dashboard.partial_urls")),
    path("_partials/", include("games.partial_urls")),
    path("_partials/", include("search.partial_urls")),
    path("_partials/", include("openings.partial_urls")),
    path("_partials/", include("analysis.partial_urls")),
    path("_partials/", include("players.partial_urls")),
    path("api/v1/", include("api.urls")),
    # Admin UI for API key management (session auth, not under /api/v1/)
    path("admin/api-keys/", include("api.admin_urls")),
    path("_partials/admin/api-keys/", include("api.admin_urls")),
]
