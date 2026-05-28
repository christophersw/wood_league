"""
Title: email_service.py — Send magic-link and invite emails
Description:
    Renders Django templates for invite and login emails, inlines CSS via
    premailer, and sends through the configured EMAIL_BACKEND (Resend in
    prod, console in dev).
Changelog:
    2026-05-28: Initial.
"""
from __future__ import annotations

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from premailer import transform

from app.config import get_settings
from players.models import Player

from .models import User


class EmailService:
    """Send magic-link emails (invite + login)."""

    def __init__(self) -> None:
        """Initialise with application settings."""
        self.settings = get_settings()

    def _link_url(self, raw_token: str) -> str:
        """Build the absolute URL for a magic link.

        Args:
            raw_token: The unhashed token string to embed in the URL.

        Returns:
            Absolute URL string pointing to the magic-link login endpoint.
        """
        base = self.settings.app_base_url.rstrip("/")
        return f"{base}/login/link/{raw_token}/"

    def _send(self, *, subject: str, to: str, text: str, html: str) -> None:
        """Send a multi-alternative (text + HTML) email.

        Args:
            subject: Email subject line.
            to: Recipient email address.
            text: Plain-text body.
            html: HTML body (CSS will be inlined via premailer).

        Side effects:
            Dispatches an email via the configured EMAIL_BACKEND.
        """
        reply_to = [self.settings.email_reply_to] if self.settings.email_reply_to else None
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text,
            from_email=self.settings.email_from,
            to=[to],
            reply_to=reply_to,
        )
        msg.attach_alternative(transform(html), "text/html")
        msg.send(fail_silently=False)

    def send_login_email(self, user: User, raw_token: str) -> None:
        """Send the short 'here's your login link' email.

        Args:
            user: The User requesting the login link.
            raw_token: The unhashed token to embed in the magic-link URL.

        Side effects:
            Sends one email to user.email.
        """
        ctx = {
            "link_url": self._link_url(raw_token),
            "ttl_minutes": self.settings.magic_link_login_ttl_minutes,
        }
        self._send(
            subject="Your Wood League login link",
            to=user.email,
            text=render_to_string("emails/login.txt", ctx),
            html=render_to_string("emails/login.html", ctx),
        )

    def send_invite_email(
        self,
        user: User,
        player: Player,
        raw_token: str,
        invited_by: User,
    ) -> None:
        """Send the welcome+invite email for first-touch onboarding.

        Args:
            user: The User account being invited (recipient).
            player: The Player profile linked to the user.
            raw_token: The unhashed token to embed in the magic-link URL.
            invited_by: The admin User who triggered the invite.

        Side effects:
            Sends one email to user.email.
        """
        ctx = {
            "link_url": self._link_url(raw_token),
            "ttl_days": self.settings.magic_link_invite_ttl_hours // 24,
            "invited_by_email": invited_by.email,
            "display_name": player.display_name or player.username,
        }
        self._send(
            subject="Welcome to Wood League — claim your account",
            to=user.email,
            text=render_to_string("emails/invite.txt", ctx),
            html=render_to_string("emails/invite.html", ctx),
        )
