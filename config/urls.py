"""URL routing configuration for the Django application.

Maps URL paths to app-specific URL handlers and includes admin, authentication, and HTMX partial views.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("games/", include("games.urls")),
    path("search/", include("search.urls")),
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
