"""
Title: views.py — Authentication views
Description:
    Django views for handling user login and logout. Implements email-based authentication,
    form validation, session management, and conditional auth based on AUTH_ENABLED setting.
    Includes error messaging and redirect handling for authenticated/unauthenticated users.
    The canonical user-facing login is the email-only magic-link form; password login is an
    admin escape hatch at /login/password/.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-28: Added email-only login_request view with enumeration safety and throttling
"""

from django.conf import settings
from django.contrib import auth, messages
from django.shortcuts import redirect, render
from django_ratelimit.decorators import ratelimit

from .email_service import EmailService
from .forms import EmailOnlyLoginForm, LoginForm
from .magic_link_service import MagicLinkService
from .models import LoginLink, User


@ratelimit(key="ip", rate="20/h", method="POST", block=True)
def login_request(request):
    """
    Email-only login form. Always responds the same to avoid user enumeration.

    If the submitted email matches an active account and the user is under the
    per-user throttle limits, issues a magic link and sends a login email.
    Unknown emails receive the same confirmation page without sending any email.

    Args:
        request: Django HttpRequest.

    Returns:
        Rendered login_request.html on GET/invalid POST, or
        rendered login_check_email.html on valid POST.
    """
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = EmailOnlyLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        user = User.objects.filter(email=email, is_active=True).first()
        if user is not None:
            svc = MagicLinkService()
            if svc.throttle_check(user):
                _, raw = svc.issue_link(user, purpose=LoginLink.PURPOSE_LOGIN)
                EmailService().send_login_email(user, raw)
        return render(request, "accounts/login_check_email.html", {"email": email})

    return render(request, "accounts/login_request.html", {"form": form})


def password_login_view(request):
    """
    Render password login form and authenticate user credentials via email and password.

    This is an unlisted admin escape hatch — the canonical user-facing login is now
    the email-based magic link flow.
    """
    if not getattr(settings, "AUTH_ENABLED", True):
        return redirect(settings.LOGIN_REDIRECT_URL)

    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = LoginForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        password = form.cleaned_data["password"]
        user = auth.authenticate(request, username=email, password=password)
        if user is not None and user.is_active:
            auth.login(request, user)
            return redirect(settings.LOGIN_REDIRECT_URL)
        messages.error(request, "Invalid email or password.")

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request):
    """Log out the authenticated user and redirect to the logout URL."""
    if request.method == "POST":
        auth.logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)
