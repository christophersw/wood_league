# Magic-Link Login & Member Invites — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-28-magic-link-login-design.md`
**Issue:** [#218](https://github.com/christophersw/wood_league/issues/218) (milestone v1)

**Goal:** Replace password-first login with a magic-link flow driven by admin invites; keep password as an unlisted admin escape hatch.

**Architecture:** All new code lives in the existing Django `accounts` app (which already owns the custom `User` model and login views). `LoginLink` is a Django model — no new SQLAlchemy code is added. Magic-link logic, email sending, and rate-limiting are isolated into dedicated services (`magic_link_service.py`, `email_service.py`) so each module has one job and is unit-testable without HTTP.

**Tech Stack:** Django (existing), `django-anymail[resend]` (new), `premailer` (new), `django-ratelimit` (new), Resend (provider).

### Spec deltas baked into this plan

- `LoginLink` is a **Django** model in `accounts/`, not SQLAlchemy (the auth surface is already Django; this avoids cross-ORM bridging and adds zero SQLAlchemy code).
- `Player.email` already exists — no migration needed.
- `Player.user_id` FK is not added; lookups use the existing `resolve_current_player(user)` (email join) pattern.
- `User.last_login` is provided by `AbstractBaseUser` — no User schema change.
- "Member" everywhere in the spec maps to `players.Player`.

---

## File Structure

**Create**
- `services/app/accounts/models.py` — append `LoginLink` model.
- `services/app/accounts/magic_link_service.py` — `issue_link`, `consume_link`, `throttle_check`.
- `services/app/accounts/email_service.py` — `send_invite_email`, `send_login_email`.
- `services/app/accounts/migrations/000X_loginlink.py` — generated.
- `services/app/templates/emails/invite.html`, `invite.txt`, `login.html`, `login.txt`.
- `services/app/templates/accounts/login_request.html` — email-only login form.
- `services/app/templates/accounts/login_check_email.html` — "check your email" confirmation page.
- `services/app/templates/accounts/login_link_expired.html` — re-request page.
- `services/app/accounts/tests/test_magic_link_service.py`
- `services/app/accounts/tests/test_email_service.py`
- `services/app/accounts/tests/test_login_views.py`
- `services/app/players/tests/test_member_invite_view.py`

**Modify**
- `services/app/accounts/views.py` — split: rename existing `login_view` to `password_login_view`; add `login_request`, `login_link_consume`.
- `services/app/accounts/urls.py` — re-route `/login/` to new email-only view; add `/login/link/<token>/`; add `/login/password/`.
- `services/app/accounts/forms.py` — add `EmailOnlyLoginForm`.
- `services/app/players/views.py` — add `member_send_invite`.
- `services/app/players/urls.py` — wire `member_send_invite`.
- `services/app/templates/players/members_list.html` — add invite button column and status.
- `services/app/app/config.py` — add email & magic-link settings.
- `services/app/app/settings.py` (or wherever Django settings module is) — wire `EMAIL_BACKEND`, anymail config, ratelimit cache.
- `services/app/pyproject.toml` — new deps.
- `services/app/bin/build_tailwind.sh` (re-run after template edits — not a code modification).

---

## Task 1: Add dependencies and config keys

**Files:**
- Modify: `services/app/pyproject.toml`
- Modify: `services/app/app/config.py`

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

Add to the `dependencies` list:

```toml
"django-anymail[resend]>=11.0",
"premailer>=3.10",
"django-ratelimit>=4.1",
```

- [ ] **Step 2: Install**

Run (from repo root, with venv active):
```bash
source .venv/bin/activate && pip install -e services/app
```
Expected: installs `django-anymail`, `premailer`, `django-ratelimit`.

- [ ] **Step 3: Add settings fields to `app/config.py` `Settings`**

Add inside the `Settings` class:

```python
email_provider: str = "console"  # "console" | "resend"
resend_api_key: str = ""
email_from: str = "Wood League <noreply@woodleague.club>"
email_reply_to: str = ""
app_base_url: str = ""
magic_link_invite_ttl_hours: int = 168
magic_link_login_ttl_minutes: int = 15
magic_link_throttle_per_minute: int = 1
magic_link_throttle_per_hour: int = 5
```

- [ ] **Step 4: Wire Django EMAIL_BACKEND in settings module**

Locate the Django settings module (search `grep -rn "EMAIL_BACKEND\|INSTALLED_APPS" services/app/app/`) and add:

```python
from app.config import get_settings
_s = get_settings()

if _s.email_provider == "resend":
    EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"
    ANYMAIL = {"RESEND_API_KEY": _s.resend_api_key}
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = _s.email_from
INSTALLED_APPS += ["anymail"]
```

- [ ] **Step 5: Commit**

```bash
git add services/app/pyproject.toml services/app/app/config.py services/app/app/settings.py
git commit -m "feat(accounts): add anymail/premailer/ratelimit deps and email settings"
```

---

## Task 2: `LoginLink` model + migration

**Files:**
- Modify: `services/app/accounts/models.py`
- Create: `services/app/accounts/tests/test_login_link_model.py`
- Generate: `services/app/accounts/migrations/000X_loginlink.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/accounts/tests/test_login_link_model.py`:

```python
"""
Title: test_login_link_model.py — Tests for the LoginLink model
Description: Verifies LoginLink fields, indexes, and unique constraints.
Changelog: 2026-05-28: Initial.
"""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from accounts.models import LoginLink, User


class LoginLinkModelTests(TestCase):
    def test_create_with_hashed_token(self):
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
        user = User.objects.create_user(email="y@example.com", password=None)
        LoginLink.objects.create(
            user=user, token_hash="b" * 64, purpose="login",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        with self.assertRaises(Exception):
            LoginLink.objects.create(
                user=user, token_hash="b" * 64, purpose="login",
                expires_at=timezone.now() + timedelta(minutes=15),
            )
```

- [ ] **Step 2: Verify it fails**

Run: `cd services/app && pytest accounts/tests/test_login_link_model.py -v`
Expected: ImportError on `LoginLink`.

- [ ] **Step 3: Add the model to `accounts/models.py`**

Append:

```python
class LoginLink(models.Model):
    """Single-use magic link for passwordless login or invite."""

    PURPOSE_INVITE = "invite"
    PURPOSE_LOGIN = "login"
    PURPOSE_CHOICES = [(PURPOSE_INVITE, "Invite"), (PURPOSE_LOGIN, "Login")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_links")
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="login_links_issued",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "accounts"
        db_table = "login_links"
        indexes = [
            models.Index(fields=["user", "consumed_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"LoginLink(user={self.user_id}, purpose={self.purpose})"
```

- [ ] **Step 4: Generate the migration**

```bash
cd services/app && python manage.py makemigrations accounts
```
Expected: creates `accounts/migrations/000X_loginlink.py`.

- [ ] **Step 5: Run migrations and re-run the test**

```bash
cd services/app && python manage.py migrate && pytest accounts/tests/test_login_link_model.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/app/accounts/models.py services/app/accounts/migrations/ services/app/accounts/tests/test_login_link_model.py
git commit -m "feat(accounts): add LoginLink model for magic-link auth"
```

---

## Task 3: `MagicLinkService.issue_link`

**Files:**
- Create: `services/app/accounts/magic_link_service.py`
- Create: `services/app/accounts/tests/test_magic_link_service.py`

- [ ] **Step 1: Write the failing tests**

`services/app/accounts/tests/test_magic_link_service.py`:

```python
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
```

- [ ] **Step 2: Run, expect ImportError**

`cd services/app && pytest accounts/tests/test_magic_link_service.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `magic_link_service.py` (issue path only)**

```python
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
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from app.config import get_settings
from .models import LoginLink, User


@dataclass
class IssueResult:
    link: LoginLink
    raw_token: str


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
```

- [ ] **Step 4: Run tests, expect PASS**

`cd services/app && pytest accounts/tests/test_magic_link_service.py::IssueLinkTests -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/app/accounts/magic_link_service.py services/app/accounts/tests/test_magic_link_service.py
git commit -m "feat(accounts): MagicLinkService.issue_link with hashed single-use tokens"
```

---

## Task 4: `MagicLinkService.consume_link`

**Files:**
- Modify: `services/app/accounts/magic_link_service.py`
- Modify: `services/app/accounts/tests/test_magic_link_service.py`

- [ ] **Step 1: Add failing tests**

Append to `test_magic_link_service.py`:

```python
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
```

- [ ] **Step 2: Run, expect failures (method missing)**

`cd services/app && pytest accounts/tests/test_magic_link_service.py::ConsumeLinkTests -v`

- [ ] **Step 3: Add `consume_link` to `magic_link_service.py`**

```python
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
```

- [ ] **Step 4: Run, expect PASS**

`cd services/app && pytest accounts/tests/test_magic_link_service.py::ConsumeLinkTests -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add services/app/accounts/magic_link_service.py services/app/accounts/tests/test_magic_link_service.py
git commit -m "feat(accounts): MagicLinkService.consume_link with single-use guarantee"
```

---

## Task 5: `MagicLinkService.throttle_check`

**Files:**
- Modify: `services/app/accounts/magic_link_service.py`
- Modify: `services/app/accounts/tests/test_magic_link_service.py`

- [ ] **Step 1: Failing tests**

Append:

```python
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
        # Backdate four prior issues so the per-minute limit isn't what blocks us.
        for _ in range(5):
            link, _ = self.svc.issue_link(self.user, purpose="login")
            LoginLink.objects.filter(pk=link.pk).update(
                created_at=timezone.now() - timedelta(minutes=2),
            )
        self.assertFalse(self.svc.throttle_check(self.user))
```

- [ ] **Step 2: Run, expect failures**

`cd services/app && pytest accounts/tests/test_magic_link_service.py::ThrottleCheckTests -v`

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run, expect PASS**

`cd services/app && pytest accounts/tests/test_magic_link_service.py::ThrottleCheckTests -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add services/app/accounts/magic_link_service.py services/app/accounts/tests/test_magic_link_service.py
git commit -m "feat(accounts): per-user throttle_check on MagicLinkService"
```

---

## Task 6: Email templates and `EmailService`

**Files:**
- Create: `services/app/templates/emails/invite.html`, `invite.txt`, `login.html`, `login.txt`
- Create: `services/app/accounts/email_service.py`
- Create: `services/app/accounts/tests/test_email_service.py`

- [ ] **Step 1: Write the templates**

`templates/emails/login.html` (single-column, 600px, inline CSS — Du Bois palette: bg `#f6f1e7`, ink `#1a1a1a`, rust `#a8421c`):

```html
{% load static %}
<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f1e7;font-family:Georgia,serif;color:#1a1a1a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f1e7;">
    <tr><td align="center" style="padding:32px 16px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#f6f1e7;">
        <tr><td style="padding:0 0 24px 0;font-size:14px;letter-spacing:0.18em;text-transform:uppercase;">Wood League Chess Club</td></tr>
        <tr><td style="padding:0 0 16px 0;font-size:22px;line-height:1.3;">Your Wood League login link</td></tr>
        <tr><td style="padding:0 0 24px 0;font-size:16px;line-height:1.6;">Click below to sign in. This link expires in {{ ttl_minutes }} minutes and can only be used once.</td></tr>
        <tr><td style="padding:0 0 32px 0;">
          <a href="{{ link_url }}" style="display:inline-block;background:#a8421c;color:#f6f1e7;text-decoration:none;padding:14px 24px;font-size:16px;font-weight:bold;">Log in to Wood League</a>
        </td></tr>
        <tr><td style="padding:0 0 16px 0;font-size:13px;color:#5a5a5a;line-height:1.6;">If you didn't request this link, you can safely ignore this email.</td></tr>
      </table>
    </td></tr>
  </table>
</body></html>
```

`templates/emails/login.txt`:

```
Wood League Chess Club

Your login link (expires in {{ ttl_minutes }} minutes, single use):

{{ link_url }}

If you didn't request this link, ignore this email.
```

`templates/emails/invite.html` — same structure, headline "Welcome to Wood League", body:
```
You've been added to Wood League Chess Club by {{ invited_by_email }}. Click below to claim your account and start exploring your games.
```
CTA "Open Wood League", expiry "This link expires in 7 days".

`templates/emails/invite.txt` — plaintext equivalent.

- [ ] **Step 2: Write the failing test**

`services/app/accounts/tests/test_email_service.py`:

```python
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
```

- [ ] **Step 3: Run, expect ImportError**

`cd services/app && pytest accounts/tests/test_email_service.py -v`

- [ ] **Step 4: Implement `email_service.py`**

```python
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
        self.settings = get_settings()

    def _link_url(self, raw_token: str) -> str:
        """Build the absolute URL for a magic link."""
        base = self.settings.app_base_url.rstrip("/")
        return f"{base}/login/link/{raw_token}/"

    def _send(self, *, subject: str, to: str, text: str, html: str) -> None:
        """Send a multi-alternative email."""
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text,
            from_email=self.settings.email_from,
            to=[to],
            reply_to=[self.settings.email_reply_to] if self.settings.email_reply_to else None,
        )
        msg.attach_alternative(transform(html), "text/html")
        msg.send(fail_silently=False)

    def send_login_email(self, user: User, raw_token: str) -> None:
        """Send the short 'here's your login link' email."""
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
        self, user: User, player: Player, raw_token: str, invited_by: User,
    ) -> None:
        """Send the welcome+invite email for first-touch onboarding."""
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
```

- [ ] **Step 5: Run, expect PASS**

`cd services/app && pytest accounts/tests/test_email_service.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add services/app/templates/emails/ services/app/accounts/email_service.py services/app/accounts/tests/test_email_service.py
git commit -m "feat(accounts): email templates and EmailService for invite + login"
```

---

## Task 7: Move existing password login to `/login/password`

**Files:**
- Modify: `services/app/accounts/views.py`
- Modify: `services/app/accounts/urls.py`

- [ ] **Step 1: Rename `login_view` → `password_login_view`**

In `accounts/views.py`, rename and update the docstring; keep behavior identical. Template can stay at `accounts/login.html` for now (renamed later as needed).

- [ ] **Step 2: Update `accounts/urls.py`**

```python
urlpatterns = [
    path("login/password/", views.password_login_view, name="login_password"),
    path("logout/", views.logout_view, name="logout"),
]
```

The `/login/` route will be re-added in Task 8 pointing at the new email-only view.

- [ ] **Step 3: Update tests / templates referencing `accounts:login`**

Search and audit: `grep -rn "accounts:login\b" services/app/templates services/app/`
For any references that mean "the password login", change to `accounts:login_password`. For references that mean "the new email login", leave them — Task 8 reuses the `login` name.

- [ ] **Step 4: Run existing test suite**

`cd services/app && pytest accounts/ -v`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add services/app/accounts/views.py services/app/accounts/urls.py
git commit -m "refactor(accounts): move password login to /login/password (unlisted)"
```

---

## Task 8: New email-only `/login` view

**Files:**
- Modify: `services/app/accounts/forms.py`
- Modify: `services/app/accounts/views.py`
- Modify: `services/app/accounts/urls.py`
- Create: `services/app/templates/accounts/login_request.html`
- Create: `services/app/templates/accounts/login_check_email.html`
- Create: `services/app/accounts/tests/test_login_views.py`

- [ ] **Step 1: Add form**

Append to `forms.py`:

```python
class EmailOnlyLoginForm(forms.Form):
    """Email-only form for requesting a magic login link."""
    email = forms.EmailField(label="Email", max_length=255)
```

- [ ] **Step 2: Write failing view tests**

`tests/test_login_views.py`:

```python
"""
Title: test_login_views.py — Tests for the email-only login flow
Description: Covers GET form, POST enumeration safety, throttling, link consumption.
Changelog: 2026-05-28: Initial.
"""
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import User, LoginLink


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
```

- [ ] **Step 3: Run, expect failures**

`cd services/app && pytest accounts/tests/test_login_views.py -v`

- [ ] **Step 4: Implement `login_request` view**

In `accounts/views.py`:

```python
from django_ratelimit.decorators import ratelimit

from .forms import EmailOnlyLoginForm
from .magic_link_service import MagicLinkService
from .email_service import EmailService
from .models import LoginLink, User


@ratelimit(key="ip", rate="20/h", method="POST", block=True)
def login_request(request):
    """Email-only login form. Always responds the same to avoid user enumeration."""
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = EmailOnlyLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        user = User.objects.filter(email=email, is_active=True).first()
        if user is not None:
            svc = MagicLinkService()
            if svc.throttle_check(user):
                _, raw = svc.issue_link(user, purpose=LoginLink.PURPOSE_LOGIN)
                EmailService().send_login_email(user, raw)
        return render(request, "accounts/login_check_email.html", {"email": email})

    return render(request, "accounts/login_request.html", {"form": form})
```

- [ ] **Step 5: Write templates**

`templates/accounts/login_request.html` — single email field, submit button "Send me a login link", link to `/login/password/` styled as a small footer "Admin? Sign in with a password".

`templates/accounts/login_check_email.html` — "Check your email. We sent a sign-in link to {{ email }} if there's an account for it. The link expires in 15 minutes."

- [ ] **Step 6: Add URL**

Update `accounts/urls.py`:

```python
urlpatterns = [
    path("login/", views.login_request, name="login"),
    path("login/password/", views.password_login_view, name="login_password"),
    path("logout/", views.logout_view, name="logout"),
]
```

- [ ] **Step 7: Run tests, expect PASS**

`cd services/app && pytest accounts/tests/test_login_views.py::LoginRequestViewTests -v`

- [ ] **Step 8: Rebuild Tailwind (mandatory after template edits)**

```bash
cd services/app && ./bin/build_tailwind.sh
```

- [ ] **Step 9: Commit**

```bash
git add services/app/accounts/ services/app/templates/accounts/login_request.html services/app/templates/accounts/login_check_email.html services/app/static/css/tailwind.css
git commit -m "feat(accounts): email-only /login view with throttle and enumeration safety"
```

---

## Task 9: `/login/link/<token>` consumption view

**Files:**
- Modify: `services/app/accounts/views.py`
- Modify: `services/app/accounts/urls.py`
- Create: `services/app/templates/accounts/login_link_expired.html`
- Modify: `services/app/accounts/tests/test_login_views.py`

- [ ] **Step 1: Failing tests**

Append to `test_login_views.py`:

```python
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
```

- [ ] **Step 2: Run, expect failures**

`cd services/app && pytest accounts/tests/test_login_views.py::LoginLinkConsumeTests -v`

- [ ] **Step 3: Implement `login_link_consume`**

In `accounts/views.py`:

```python
@ratelimit(key="ip", rate="20/h", method="GET", block=True)
def login_link_consume(request, token: str):
    """Consume a magic link and start a session for the matching user."""
    user = MagicLinkService().consume_link(token, purpose=LoginLink.PURPOSE_LOGIN)
    if user is None:
        # Also try invite purpose — they share the URL.
        user = MagicLinkService().consume_link(token, purpose=LoginLink.PURPOSE_INVITE)
    if user is None:
        return render(request, "accounts/login_link_expired.html", status=200)

    user.backend = "django.contrib.auth.backends.ModelBackend"
    auth.login(request, user)
    next_url = request.GET.get("next") or settings.LOGIN_REDIRECT_URL
    return redirect(next_url)
```

- [ ] **Step 4: Template `login_link_expired.html`**

Short page: "This link has expired or already been used." + form posting to `accounts:login` with an email field to request a fresh one.

- [ ] **Step 5: URL**

Append to `accounts/urls.py`:

```python
    path("login/link/<str:token>/", views.login_link_consume, name="login_link"),
```

- [ ] **Step 6: Run tests, expect PASS**

`cd services/app && pytest accounts/tests/test_login_views.py::LoginLinkConsumeTests -v`

- [ ] **Step 7: Rebuild Tailwind**

`cd services/app && ./bin/build_tailwind.sh`

- [ ] **Step 8: Commit**

```bash
git add services/app/accounts/ services/app/templates/accounts/login_link_expired.html services/app/static/css/tailwind.css
git commit -m "feat(accounts): /login/link/<token> consumption view"
```

---

## Task 10: Admin invite endpoint

**Files:**
- Modify: `services/app/players/views.py`
- Modify: `services/app/players/urls.py`
- Create: `services/app/players/tests/test_member_invite_view.py`

- [ ] **Step 1: Failing tests**

`players/tests/test_member_invite_view.py`:

```python
"""
Title: test_member_invite_view.py — Tests for admin invite endpoint.
Description: Covers permissions, missing email, first invite, and resend.
Changelog: 2026-05-28: Initial.
"""
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import User, LoginLink
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

    def test_resend_invalidates_prior_link(self):
        self.client.post(reverse("players:member_send_invite", args=[self.player_with_email.id]))
        self.client.post(reverse("players:member_send_invite", args=[self.player_with_email.id]))
        active = LoginLink.objects.filter(purpose="invite", consumed_at__isnull=True).count()
        self.assertEqual(active, 1)
```

- [ ] **Step 2: Run, expect failures**

`cd services/app && pytest players/tests/test_member_invite_view.py -v`

- [ ] **Step 3: Implement view**

In `players/views.py`:

```python
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.http import require_POST

from accounts.email_service import EmailService
from accounts.magic_link_service import MagicLinkService
from accounts.models import LoginLink, User


@login_required
@require_POST
def member_send_invite(request, player_id: int):
    """Issue or resend a welcome+invite magic link for the given player."""
    if request.user.role != "admin":
        return HttpResponseForbidden("Admin only.")

    player = Player.objects.filter(pk=player_id).first()
    if player is None:
        return HttpResponseBadRequest("Unknown player.")
    if not player.email:
        return HttpResponseBadRequest("Player has no email on file.")

    email = player.email.strip().lower()
    user, _ = User.objects.get_or_create(
        email=email, defaults={"role": "member", "is_active": True},
    )
    if not user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=["password"])

    svc = MagicLinkService()
    if not svc.throttle_check(user):
        messages.info(request, "An invite was sent recently. Please wait a minute and try again.")
        return redirect("players:members_list")

    _, raw = svc.issue_link(user, purpose=LoginLink.PURPOSE_INVITE, created_by=request.user)
    EmailService().send_invite_email(user, player, raw, invited_by=request.user)
    messages.success(request, f"Invite sent to {email}.")
    return redirect("players:members_list")
```

- [ ] **Step 4: URL**

In `players/urls.py`:

```python
    path("members/<int:player_id>/invite/", views.member_send_invite, name="member_send_invite"),
```

- [ ] **Step 5: Run tests, expect PASS**

`cd services/app && pytest players/tests/test_member_invite_view.py -v`

- [ ] **Step 6: Commit**

```bash
git add services/app/players/views.py services/app/players/urls.py services/app/players/tests/test_member_invite_view.py
git commit -m "feat(players): admin Send/Resend invite endpoint"
```

---

## Task 11: Members page UI — invite button column

**Files:**
- Modify: `services/app/templates/players/members_list.html` (path: confirm via `grep -rn members_list services/app/templates`)
- Modify: `services/app/players/views.py` (members_list view to annotate per-player invite state)

- [ ] **Step 1: Annotate the view**

In `members_list`, compute for each player whether a User exists (and `last_login`), and the latest invite link's `created_at`:

```python
def members_list(request):
    """Display members with login + invite status; admins can send/resend invites."""
    players = Player.objects.all().order_by("username")
    emails = [p.email.lower() for p in players if p.email]
    users_by_email = {u.email: u for u in User.objects.filter(email__in=emails)}

    rows = []
    for p in players:
        user = users_by_email.get((p.email or "").lower())
        latest_invite = None
        if user is not None:
            latest_invite = (
                LoginLink.objects
                .filter(user=user, purpose=LoginLink.PURPOSE_INVITE)
                .order_by("-created_at").first()
            )
        rows.append({
            "player": p,
            "user": user,
            "has_logged_in": bool(user and user.last_login),
            "invited_at": latest_invite.created_at if latest_invite else None,
        })

    is_admin = getattr(request.user, "role", None) == "admin"
    return render(request, "players/members_list.html", {"rows": rows, "is_admin": is_admin})
```

- [ ] **Step 2: Update the template**

Add columns and the invite button:

```django
<th>Status</th>
{% if is_admin %}<th>Invite</th>{% endif %}

{% for row in rows %}
<tr>
  ...
  <td>
    {% if row.has_logged_in %}Joined {{ row.user.last_login|date:"Y-m-d" }}
    {% elif row.invited_at %}Invited {{ row.invited_at|date:"Y-m-d" }}
    {% else %}—{% endif %}
  </td>
  {% if is_admin %}
  <td>
    {% if row.player.email %}
      <form method="post" action="{% url 'players:member_send_invite' row.player.id %}">
        {% csrf_token %}
        <button type="submit" class="wc-btn wc-btn--small">
          {% if row.invited_at %}Resend invite{% else %}Send invite{% endif %}
        </button>
      </form>
    {% else %}
      <button class="wc-btn wc-btn--small" disabled title="Add an email for this member to send an invite">Send invite</button>
    {% endif %}
  </td>
  {% endif %}
</tr>
{% endfor %}
```

- [ ] **Step 3: Add a view test for rendering**

Append to `players/tests/test_member_invite_view.py`:

```python
class MembersListUITests(TestCase):
    def test_disabled_button_when_email_missing(self):
        admin = User.objects.create_user(email="a2@x.com", password="pw12345678", role="admin")
        Player.objects.create(username="noemail", email=None)
        self.client.force_login(admin)
        resp = self.client.get(reverse("players:members_list"))
        self.assertContains(resp, 'disabled title="Add an email')

    def test_send_invite_button_when_email_present(self):
        admin = User.objects.create_user(email="a3@x.com", password="pw12345678", role="admin")
        Player.objects.create(username="hasmail", email="x@x.com")
        self.client.force_login(admin)
        resp = self.client.get(reverse("players:members_list"))
        self.assertContains(resp, "Send invite")
```

- [ ] **Step 4: Run tests**

`cd services/app && pytest players/tests/test_member_invite_view.py -v`
Expected: all pass.

- [ ] **Step 5: Rebuild Tailwind (MANDATORY — template touched)**

```bash
cd services/app && ./bin/build_tailwind.sh
```

- [ ] **Step 6: Commit**

```bash
git add services/app/templates/players/members_list.html services/app/players/views.py services/app/players/tests/test_member_invite_view.py services/app/static/css/tailwind.css
git commit -m "feat(players): members page invite button column with disabled-when-no-email"
```

---

## Task 12: Manual smoke test + quality gate + final wiring

- [ ] **Step 1: Run the full quality gate**

```bash
cd services/app && source ../../.venv/bin/activate \
  && ruff check . && bandit -ll -r accounts/ players/ \
  && mypy accounts/ players/ \
  && pytest accounts/ players/ -v --cov
```
Fix any findings before proceeding.

- [ ] **Step 2: Console-backend smoke test**

Set `EMAIL_PROVIDER=console`, `APP_BASE_URL=http://localhost:8000`, `DEBUG=True`, `AUTH_ENABLED=True`, run the server:

```bash
cd services/app && python manage.py runserver
```

Manually walk through:
1. Log in as admin via `/login/password/`.
2. Add a Player with an email through admin.
3. Open `/members/`, click "Send invite". Grab the magic URL printed in the terminal.
4. Open URL in an incognito window → expect to land logged in.
5. Log out. Visit `/login/`, enter the member's email → grab the login URL from terminal → land logged in.
6. Try the same login URL again → expect "expired or already used" page.
7. Submit `/login/` twice within 60s → only one email printed.

- [ ] **Step 3: Verify CSS staleness CI gate**

```bash
cd services/app && ./bin/build_tailwind.sh && git diff --quiet static/css/tailwind.css
```
Expected: clean (no uncommitted diff).

- [ ] **Step 4: Document deploy steps in PR description**

When opening the PR, include:
- Set `RESEND_API_KEY`, `EMAIL_FROM`, `APP_BASE_URL`, `EMAIL_PROVIDER=resend` on Railway.
- Verify the sending domain in Resend (SPF + DKIM DNS records).
- Run `python manage.py migrate accounts` on deploy.

- [ ] **Step 5: Final commit if needed and open PR**

```bash
git push -u origin issue/218-magic-link-login
gh pr create --title "#218 magic-link login + member invites" --body "$(cat <<'EOF'
## Summary
- New email-only `/login` with single-use magic links via Resend (django-anymail).
- Admin "Send invite" / "Resend invite" on members page.
- Password login moved to unlisted `/login/password/` (admin escape hatch).

Spec: docs/superpowers/specs/2026-05-28-magic-link-login-design.md
Closes #218

## Deploy
- Set `RESEND_API_KEY`, `EMAIL_FROM`, `APP_BASE_URL`, `EMAIL_PROVIDER=resend` on Railway.
- Verify Resend sending domain (SPF + DKIM).
- `python manage.py migrate accounts`.

## Test plan
- [ ] Admin sends invite → member receives welcome+link → click → logged in.
- [ ] Returning member visits /login → email link → logged in.
- [ ] /login/password still works for admins.
- [ ] Link single-use, expires, throttled.
- [ ] No user enumeration on /login.
EOF
)"
```

---

## Self-Review Notes

**Spec coverage check:**
- Scope & goals → Tasks 7–11 ✓
- Data model (`LoginLink`, User changes, Member changes) → Task 2 ✓ (deltas noted: no User/Player schema changes needed)
- `MagicLinkService` → Tasks 3, 4, 5 ✓
- `EmailService` + templates → Task 6 ✓
- `AuthService` extensions → folded into Task 10 (uses Django `User.objects.create_user` directly; the spec's `create_user_passwordless` is replaced by Django's built-in `create_user(password=None)` + `set_unusable_password`) ✓
- Views (login_request, login_link_consume, login_password, member_send_invite) → Tasks 7, 8, 9, 10 ✓
- Members page UI → Task 11 ✓
- Rate limiting (per-email + per-IP) → Tasks 5 (per-user/email), 8, 9 (per-IP via `@ratelimit`) ✓
- Email templates (Du Bois, plaintext, premailer) → Task 6 ✓
- Config additions → Task 1 ✓
- Testing matrix → covered per-task plus Task 12 quality gate ✓
- Manual smoke test → Task 12 ✓

**Placeholder scan:** no TBDs; all "magic" steps have concrete code or grep targets.

**Type consistency:** `consume_link(raw_token, purpose=...)` signature consistent across Tasks 4, 9; `PURPOSE_INVITE` / `PURPOSE_LOGIN` constants used everywhere; `EmailService.send_login_email(user, raw_token)` and `send_invite_email(user, player, raw_token, invited_by)` consistent across Tasks 6, 8, 9, 10.
