"""Authentication views for user login and logout."""

from django.conf import settings
from django.contrib import auth, messages
from django.shortcuts import redirect, render

from .forms import LoginForm


def login_view(request):
    """Render login form and authenticate user credentials via email and password."""
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
