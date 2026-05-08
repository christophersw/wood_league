"""Middleware for enforcing authentication across the application."""

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


_PUBLIC_PATHS = frozenset([
    "/auth/login/",
    "/auth/logout/",
])


class LoginRequiredMiddleware:
    """
    Redirect unauthenticated requests to the login page for every URL except
    the auth endpoints. Respects the AUTH_ENABLED setting — if False, all
    requests pass through without any authentication check.
    """

    def __init__(self, get_response):
        """Initialize the middleware with the WSGI application."""
        self.get_response = get_response

    def __call__(self, request):
        """Process the request and enforce authentication checks."""
        if not getattr(settings, "AUTH_ENABLED", True):
            return self.get_response(request)

        # Exempt /api/v1/ (uses API key auth, not session auth)
        if request.path.startswith('/api/v1/'):
            return self.get_response(request)

        if request.path not in _PUBLIC_PATHS and not request.user.is_authenticated:
            login_url = reverse("accounts:login")
            return redirect(f"{login_url}?next={request.path}")

        return self.get_response(request)
