"""
Title: magic_link_service.py — Magic link issuance, consumption, throttling
Description:
    Generates and validates single-use, hashed login/invite tokens. Tokens
    are random 32-byte values; only the SHA-256 hash is stored. Issuing a
    new link of the same purpose invalidates any prior unconsumed links
    for that user.
Changelog:
    2026-05-28: Add throttle_check.
    2026-05-28: Initial, add consume_link.
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

    def consume_link(self, raw_token: str, purpose: str) -> User | None:
        """Consume a magic link. Returns the User on success, None otherwise."""
        if not raw_token:
            return None
        token_hash = self._hash(raw_token)
        now = timezone.now()
        try:
            link = LoginLink.objects.select_related("user").get(token_hash=token_hash)
        except LoginLink.DoesNotExist:
            return None
        if link.purpose != purpose:
            return None
        if link.consumed_at is not None:
            return None
        if link.expires_at < now:
            return None
        if not link.user.is_active:
            return None

        # Atomic mark-consumed: only succeed if still unconsumed.
        updated = LoginLink.objects.filter(
            pk=link.pk, consumed_at__isnull=True,
        ).update(consumed_at=now)
        if updated == 0:
            return None

        link.user.last_login = now
        link.user.save(update_fields=["last_login"])
        return link.user

    def throttle_check(self, user: User) -> bool:
        """Return True if a new link may be issued for user under the rate limits."""
        now = timezone.now()
        per_minute = self.settings.magic_link_throttle_per_minute
        per_hour = self.settings.magic_link_throttle_per_hour
        recent_minute = LoginLink.objects.filter(
            user=user, created_at__gte=now - timedelta(minutes=1),
        ).count()
        if recent_minute >= per_minute:
            return False
        recent_hour = LoginLink.objects.filter(
            user=user, created_at__gte=now - timedelta(hours=1),
        ).count()
        return recent_hour < per_hour
