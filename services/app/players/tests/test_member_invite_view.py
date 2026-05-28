"""
Title: test_member_invite_view.py — Tests for admin invite endpoint.
Description: Covers permissions, missing email, first invite, resend, and members list UI.
Changelog:
    2026-05-28: Add MembersListUITests for invite button column (#218)
    2026-05-28: Initial.
"""
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import LoginLink, User
from players.models import Player


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MemberInviteViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="a@x.com", password="pw12345678", role="admin")
        self.client.force_login(self.admin)
        self.player_with_email = Player.objects.create(username="bob", email="bob@x.com")
        self.player_no_email = Player.objects.create(username="ann", email=None)

    def test_non_admin_forbidden(self):
        self.client.logout()
        member = User.objects.create_user(email="m@x.com", password="pw12345678", role="member")
        self.client.force_login(member)
        resp = self.client.post(reverse("players:member_send_invite", args=[self.player_with_email.id]))
        self.assertEqual(resp.status_code, 403)

    def test_player_without_email_returns_400(self):
        resp = self.client.post(reverse("players:member_send_invite", args=[self.player_no_email.id]))
        self.assertEqual(resp.status_code, 400)

    def test_first_invite_creates_user_and_sends_email(self):
        self.assertFalse(User.objects.filter(email="bob@x.com").exists())
        self.client.post(reverse("players:member_send_invite", args=[self.player_with_email.id]))
        self.assertTrue(User.objects.filter(email="bob@x.com").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Welcome", mail.outbox[0].subject)
        self.assertEqual(LoginLink.objects.filter(purpose="invite").count(), 1)

    @patch("accounts.magic_link_service.MagicLinkService.throttle_check", return_value=True)
    def test_resend_invalidates_prior_link(self, _mock_throttle):
        self.client.post(reverse("players:member_send_invite", args=[self.player_with_email.id]))
        self.client.post(reverse("players:member_send_invite", args=[self.player_with_email.id]))
        active = LoginLink.objects.filter(purpose="invite", consumed_at__isnull=True).count()
        self.assertEqual(active, 1)


class MembersListUITests(TestCase):
    """Tests for the invite button column on the members list page."""

    def test_disabled_button_when_email_missing(self):
        """Members without email show a disabled Send invite button with tooltip."""
        admin = User.objects.create_user(email="a2@x.com", password="pw12345678", role="admin")
        Player.objects.create(username="noemail", email=None)
        self.client.force_login(admin)
        resp = self.client.get(reverse("players:members_list"))
        self.assertContains(resp, 'disabled title="Add an email')

    def test_send_invite_button_when_email_present(self):
        """Members with email show an active Send invite button."""
        admin = User.objects.create_user(email="a3@x.com", password="pw12345678", role="admin")
        Player.objects.create(username="hasmail", email="x@x.com")
        self.client.force_login(admin)
        resp = self.client.get(reverse("players:members_list"))
        self.assertContains(resp, "Send invite")
