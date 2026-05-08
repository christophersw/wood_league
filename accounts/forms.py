"""Login form with email and password fields for user authentication."""

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
