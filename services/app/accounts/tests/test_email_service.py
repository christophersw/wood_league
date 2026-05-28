"""
Title: test_email_service.py — Tests for EmailService
Description: Renders invite/login emails and verifies content, plaintext alt.
Changelog: 2026-05-28: Initial.
"""
from django.core import mail
from django.test import TestCase, override_settings

from accounts.email_service import EmailService
from accounts.models import User
from players.models import Player


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="m@example.com", password=None)
        self.player = Player.objects.create(username="m", email="m@example.com")
        self.admin = User.objects.create_user(email="admin@example.com", password=None, role="admin")
        self.svc = EmailService()

    def test_send_login_email(self):
        self.svc.send_login_email(self.user, raw_token="abc")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["m@example.com"])
        self.assertIn("login link", msg.subject.lower())
        self.assertIn("/login/link/abc", msg.body)
        html = msg.alternatives[0][0]
        self.assertIn("/login/link/abc", html)

    def test_send_invite_email(self):
        self.svc.send_invite_email(self.user, self.player, raw_token="zzz", invited_by=self.admin)
        msg = mail.outbox[0]
        self.assertIn("Welcome", msg.subject)
        self.assertIn("admin@example.com", msg.body)
        self.assertIn("/login/link/zzz", msg.body)
