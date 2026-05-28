"""
Title: test_magic_link_service.py — Tests for MagicLinkService
Description: Tests issue_link, consume_link, throttle_check.
Changelog: 2026-05-28: Initial.
"""
import hashlib
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from accounts.models import User, LoginLink
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


class ConsumeLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="b@example.com", password=None)
        self.svc = MagicLinkService()

    def test_consume_valid_returns_user_and_marks_consumed(self):
        _, raw = self.svc.issue_link(self.user, purpose="login")
        result = self.svc.consume_link(raw, purpose="login")
        self.assertEqual(result, self.user)
        link = LoginLink.objects.get(user=self.user, purpose="login", consumed_at__isnull=False)
        self.assertIsNotNone(link.consumed_at)

    def test_consume_updates_last_login(self):
        _, raw = self.svc.issue_link(self.user, purpose="login")
        before = self.user.last_login
        self.svc.consume_link(raw, purpose="login")
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.last_login, before)

    def test_consume_already_consumed_returns_none(self):
        _, raw = self.svc.issue_link(self.user, purpose="login")
        self.svc.consume_link(raw, purpose="login")
        self.assertIsNone(self.svc.consume_link(raw, purpose="login"))

    def test_consume_expired_returns_none(self):
        link, raw = self.svc.issue_link(self.user, purpose="login")
        link.expires_at = timezone.now() - timedelta(seconds=1)
        link.save()
        self.assertIsNone(self.svc.consume_link(raw, purpose="login"))

    def test_consume_unknown_returns_none(self):
        self.assertIsNone(self.svc.consume_link("does-not-exist", purpose="login"))

    def test_consume_wrong_purpose_returns_none(self):
        _, raw = self.svc.issue_link(self.user, purpose="invite")
        self.assertIsNone(self.svc.consume_link(raw, purpose="login"))

    def test_consume_inactive_user_returns_none(self):
        _, raw = self.svc.issue_link(self.user, purpose="login")
        self.user.is_active = False
        self.user.save()
        self.assertIsNone(self.svc.consume_link(raw, purpose="login"))


class ThrottleCheckTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c@example.com", password=None)
        self.svc = MagicLinkService()

    def test_no_recent_links_allowed(self):
        self.assertTrue(self.svc.throttle_check(self.user))

    def test_one_in_last_minute_blocks(self):
        self.svc.issue_link(self.user, purpose="login")
        self.assertFalse(self.svc.throttle_check(self.user))

    def test_five_in_last_hour_blocks(self):
        for _ in range(5):
            link, _ = self.svc.issue_link(self.user, purpose="login")
            LoginLink.objects.filter(pk=link.pk).update(
                created_at=timezone.now() - timedelta(minutes=2),
            )
        self.assertFalse(self.svc.throttle_check(self.user))
