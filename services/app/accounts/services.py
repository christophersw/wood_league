"""
Title: services.py — accounts service helpers
Description:
    Bridges Django's authenticated ``User`` (email-keyed) to the
    Wood-League ``Player`` row keyed by the same email. Used by the
    search view to thread the current user's club username into the
    AI prompt so "I/me/my/mine" resolves correctly.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

from players.models import Player


def resolve_current_player(user) -> Player | None:
    """Return the ``Player`` matching ``user.email`` or ``None``.

    Args:
        user: A Django request user (authenticated or anonymous).

    Returns:
        The matching ``Player`` row, or ``None`` when the user is
        anonymous, has no email, or no Player carries that email.
    """
    if not getattr(user, "is_authenticated", False):
        return None
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        return None
    return Player.objects.filter(email__iexact=email).first()
