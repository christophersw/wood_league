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
