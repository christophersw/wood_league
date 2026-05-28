"""
Title: test_login_views.py — Tests for the email-only login flow
Description: Covers GET form, POST enumeration safety, throttling, link consumption.
Changelog: 2026-05-28: Initial.
"""
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class LoginRequestViewTests(TestCase):
    def test_get_renders_form(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="email"')

    def test_post_existing_user_sends_email_and_shows_confirmation(self):
        User.objects.create_user(email="u@example.com", password=None)
        resp = self.client.post(reverse("accounts:login"), {"email": "u@example.com"})
        self.assertContains(resp, "Check your email")
        self.assertEqual(len(mail.outbox), 1)

    def test_post_unknown_user_shows_same_confirmation_no_email(self):
        resp = self.client.post(reverse("accounts:login"), {"email": "nope@example.com"})
        self.assertContains(resp, "Check your email")
        self.assertEqual(len(mail.outbox), 0)

    def test_throttle_suppresses_second_email(self):
        User.objects.create_user(email="t@example.com", password=None)
        self.client.post(reverse("accounts:login"), {"email": "t@example.com"})
        self.client.post(reverse("accounts:login"), {"email": "t@example.com"})
        self.assertEqual(len(mail.outbox), 1)


class LoginLinkConsumeTests(TestCase):
    def setUp(self):
        from accounts.magic_link_service import MagicLinkService
        self.user = User.objects.create_user(email="c@example.com", password=None)
        self.svc = MagicLinkService()

    def test_valid_token_logs_in_and_redirects(self):
        _, raw = self.svc.issue_link(self.user, purpose="login")
        resp = self.client.get(reverse("accounts:login_link", args=[raw]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.wsgi_request.user.is_authenticated)

    def test_invalid_token_renders_expired_page(self):
        resp = self.client.get(reverse("accounts:login_link", args=["bogus"]))
        self.assertContains(resp, "expired or already used", status_code=200)

    def test_consumed_token_cannot_be_reused(self):
        _, raw = self.svc.issue_link(self.user, purpose="login")
        self.client.get(reverse("accounts:login_link", args=[raw]))
        self.client.logout()
        resp = self.client.get(reverse("accounts:login_link", args=[raw]))
        self.assertContains(resp, "expired or already used")
