"""
Title: magic_link_service.py — Magic link issuance, consumption, throttling
Description:
    Generates and validates single-use, hashed login/invite tokens. Tokens
    are random 32-byte values; only the SHA-256 hash is stored. Issuing a
    new link of the same purpose invalidates any prior unconsumed links
    for that user.
Changelog:
    2026-05-28: Initial.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from app.config import get_settings
from .models import LoginLink, User


class MagicLinkService:
    """Issue, consume, and throttle magic-link tokens."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def _hash(self, raw: str) -> str:
        """SHA-256 hex digest of the raw token."""
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _ttl(self, purpose: str) -> timedelta:
        """Return TTL for the given purpose."""
        if purpose == LoginLink.PURPOSE_INVITE:
            return timedelta(hours=self.settings.magic_link_invite_ttl_hours)
        return timedelta(minutes=self.settings.magic_link_login_ttl_minutes)

    def issue_link(
        self,
        user: User,
        purpose: str,
        created_by: User | None = None,
    ) -> tuple[LoginLink, str]:
        """Issue a new magic link for user. Returns (LoginLink, raw_token)."""
        now = timezone.now()
        with transaction.atomic():
            LoginLink.objects.filter(
                user=user, purpose=purpose, consumed_at__isnull=True,
            ).update(consumed_at=now)

            raw = secrets.token_urlsafe(32)
            link = LoginLink.objects.create(
                user=user,
                token_hash=self._hash(raw),
                purpose=purpose,
                expires_at=now + self._ttl(purpose),
                created_by=created_by,
            )
        return link, raw
