"""
Title: forms.py — User login form
Description:
    Django form for user authentication with email and password fields.
    Provides HTML form rendering with Tailwind CSS styling for login interface.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-28: Added EmailOnlyLoginForm for magic-link login flow
"""

from django import forms


class LoginForm(forms.Form):
    """HTML form for user login with email and password inputs styled with Tailwind CSS."""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "autofocus": True,
            "autocomplete": "email",
            "class": "w-full px-3 py-2 border border-peat/30 rounded bg-cream font-mono text-sm focus:outline-none focus:ring-2 focus:ring-forest",
            "placeholder": "you@example.com",
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "autocomplete": "current-password",
            "class": "w-full px-3 py-2 border border-peat/30 rounded bg-cream font-mono text-sm focus:outline-none focus:ring-2 focus:ring-forest",
            "placeholder": "••••••••",
        })
    )


class EmailOnlyLoginForm(forms.Form):
    """Email-only form for requesting a magic login link."""

    email = forms.EmailField(
        label="Email",
        max_length=255,
        widget=forms.EmailInput(attrs={
            "autofocus": True,
            "autocomplete": "email",
            "class": "w-full px-3 py-2 border border-peat/30 rounded bg-cream font-mono text-sm focus:outline-none focus:ring-2 focus:ring-forest",
            "placeholder": "you@example.com",
        }),
    )
