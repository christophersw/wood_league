"""
Title: test_login_link_model.py — Tests for the LoginLink model
Description: Verifies LoginLink fields, indexes, and unique constraints.
Changelog:
    2026-05-28: Initial.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import LoginLink, User


class LoginLinkModelTests(TestCase):
    """Test suite for the LoginLink model."""

    def test_create_with_hashed_token(self):
        """Test creating a LoginLink with a hashed token."""
        user = User.objects.create_user(email="x@example.com", password=None)
        link = LoginLink.objects.create(
            user=user,
            token_hash="a" * 64,
            purpose="invite",
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.assertEqual(link.purpose, "invite")
        self.assertIsNone(link.consumed_at)

    def test_token_hash_unique(self):
        """Test that token_hash has a unique constraint."""
        user = User.objects.create_user(email="y@example.com", password=None)
        LoginLink.objects.create(
            user=user,
            token_hash="b" * 64,
            purpose="login",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        with self.assertRaises(Exception):
            LoginLink.objects.create(
                user=user,
                token_hash="b" * 64,
                purpose="login",
                expires_at=timezone.now() + timedelta(minutes=15),
            )
