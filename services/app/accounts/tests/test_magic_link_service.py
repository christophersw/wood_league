"""
Title: test_magic_link_service.py — Tests for MagicLinkService
Description: Tests issue_link, consume_link, throttle_check.
Changelog: 2026-05-28: Initial.
"""
import hashlib
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from accounts.models import LoginLink, User
from accounts.magic_link_service import MagicLinkService


class IssueLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="a@example.com", password=None)
        self.svc = MagicLinkService()

    def test_issue_returns_raw_token_and_persists_hash(self):
        link, raw = self.svc.issue_link(self.user, purpose="login")
        self.assertEqual(len(raw), 43)  # url-safe b64 of 32 bytes, no padding
        self.assertEqual(link.token_hash, hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(link.purpose, "login")
        self.assertIsNone(link.consumed_at)
        self.assertGreater(link.expires_at, timezone.now())

    def test_issue_invalidates_prior_unconsumed_same_purpose(self):
        link1, _ = self.svc.issue_link(self.user, purpose="login")
        link2, _ = self.svc.issue_link(self.user, purpose="login")
        link1.refresh_from_db()
        self.assertIsNotNone(link1.consumed_at)
        self.assertIsNone(link2.consumed_at)

    def test_issue_does_not_touch_other_purpose(self):
        invite, _ = self.svc.issue_link(self.user, purpose="invite")
        self.svc.issue_link(self.user, purpose="login")
        invite.refresh_from_db()
        self.assertIsNone(invite.consumed_at)

    def test_invite_ttl_uses_settings_hours(self):
        link, _ = self.svc.issue_link(self.user, purpose="invite")
        delta = link.expires_at - timezone.now()
        self.assertGreater(delta, timedelta(hours=167))
        self.assertLess(delta, timedelta(hours=169))
