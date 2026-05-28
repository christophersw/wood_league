# Magic-Link Login & Member Invites — Design

**Date:** 2026-05-28
**Milestone:** v1
**Status:** Approved (brainstorming)

## Scope & Goals

Replace the password-first login with a magic-link-first flow. Passwords stay as an unlisted admin escape hatch. Admins invite members from the members page; the member receives a Du Bois–styled welcome email with a single-use login link that signs them in on click. Subsequent logins use a plain "here's your link" email. Resend is one click. Email delivery via Resend through `django-anymail`. Links are single-use, revocable, throttled.

### Success criteria

- Admin can add a member with an email and click "Send invite" → member receives welcome+link email and is logged in within one click.
- Returning members log in via `/login` (email field only) → click email link → land in app.
- Admin password path (`/login/password`) still works (unlisted).
- Invite links expire after 7 days, login links after 15 minutes; both are single-use and revocable.
- Rate-limited: ≤1 link/min/email, ≤5/hour/email, ≤20/hour/IP.
- No user enumeration on `/login`.

### Non-goals

- "Sign out everywhere" admin tooling (YAGNI).
- Member self-signup / public registration (admin-driven invites only).
- SSO, OAuth, WebAuthn (future).
- Marketing emails, newsletters, digest emails.

## Data Model Changes

### New table: `LoginLink` (in `app/storage/models.py`)

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | FK → User | indexed |
| `token_hash` | str(64), unique | SHA-256 of the random 32-byte token; raw token never persisted |
| `purpose` | str | `"invite"` or `"login"` |
| `expires_at` | datetime | invites: now + 7d; logins: now + 15min |
| `consumed_at` | datetime nullable | set on successful use |
| `created_by_user_id` | FK → User nullable | admin who issued invite; null for self-service login |
| `created_at` | datetime | default now |

Indexes: composite `(user_id, consumed_at)` for "active links for user" queries; unique on `token_hash`.

### `User` model

- `password_hash` → nullable (members never need one).
- `last_login_at` datetime nullable — populated on successful link consumption or password login.

### `Member` model

- `email` str nullable, unique-when-not-null.
- `user_id` FK → User nullable, indexed.

### Migrations

1. `players`: add `Member.email`, `Member.user_id`.
2. `storage` (or wherever `User` lives): create `LoginLink`, alter `User.password_hash` nullable, add `User.last_login_at`.

## Components & Boundaries

### `app/services/magic_link_service.py` (new)

The only module that knows how magic links work.

- `issue_link(user, purpose, created_by=None) -> (LoginLink, raw_token)` — generates a random 32-byte token, hashes it (SHA-256), persists the row, invalidates prior unconsumed links of the same purpose for that user (sets `consumed_at = now()` on them or deletes them — implementation chooses; either way they become unusable), returns the *raw* token (only time it exists in memory) for embedding in the URL.
- `consume_link(raw_token) -> AuthUser | None` — hashes input, looks up by `token_hash`, checks `expires_at` and `consumed_at`, marks consumed (atomic), updates `User.last_login_at`, returns `AuthUser`. Uses constant-time hash compare. Returns `None` for any failure (no detailed error to caller).
- `throttle_check(user) -> bool` — returns whether the per-email rate limit allows another link right now (counts recent `LoginLink` rows for that user against `≤1/min` and `≤5/hour`).

### `app/services/email_service.py` (new)

The only module that knows how to send mail.

- `send_invite_email(user, member, raw_token, invited_by)` — renders the welcome+invite template, sends via anymail/Resend.
- `send_login_email(user, raw_token)` — renders the login template, sends.
- Templates live in `services/app/templates/emails/` as `.html` + `.txt` pairs. Rendered via Django's template engine so they share design tokens with the rest of the app; CSS inlined at render time via `premailer`.

### `AuthService` changes (minimal)

- `authenticate_via_link(raw_token) -> AuthUser | None` — thin wrapper that calls `MagicLinkService.consume_link` and returns an `AuthUser` for the caller to attach to the session.
- `create_user_passwordless(email, role="member") -> AuthUser` — creates a `User` with `password_hash=NULL`.

`AuthService` never knows about links; `MagicLinkService` never sends email; `EmailService` never touches sessions. Views orchestrate. Services are testable without an HTTP request.

### Views

- `login_request` — GET renders the email-only form; POST throttles, issues a login link if the user exists, **always** renders "check your email" regardless of outcome (no enumeration).
- `login_link_consume` — GET `/login/link/<token>` consumes, sets session cookie (2-week rolling), redirects to `next` or home; on failure renders a friendly "link expired or already used" page with a one-click re-request form.
- `login_password` — existing email+password form, moved to `/login/password` (unlisted).
- `member_send_invite` — POST, admin-only. Creates the `User` if missing (and links `Member.user_id`), issues an invite link, sends invite email. Updates the member row's display state ("Invited {timestamp}", button → "Resend invite").

### Members page template

- Add an "Invite" / "Resend invite" button column to the members table.
- Button **disabled when `Member.email` is null**, with tooltip "Add an email for this member to send an invite" and an inline edit affordance to add one.
- Status column shows "Invited {date}" or "Joined {date}" (derived from `User.last_login_at` and the latest invite link).

## Flows

### Invite (admin → member, members page)

1. Admin clicks "Send invite" on a member row (button enabled because `Member.email` is set).
2. POST to `member_send_invite`. View checks admin role and throttle.
3. If `Member.user_id` is null: `AuthService.create_user_passwordless(email=member.email, role="member")`, link `Member.user_id`.
4. `MagicLinkService.issue_link(user, purpose="invite", created_by=admin)` — invalidates prior unconsumed invite links, inserts new row, returns raw token.
5. `EmailService.send_invite_email(user, member, raw_token, invited_by=admin)`.
6. Member row updates: shows "Invited {timestamp}", button label becomes "Resend invite".
7. Redirect back to members list with flash "Invite sent to {email}".

### Login (returning member)

1. Member visits `/login`, enters email, submits.
2. View normalizes email, looks up `User`. Throttle check. **Always** renders the same "Check your email" confirmation page.
3. If user exists and is active: `MagicLinkService.issue_link(user, purpose="login")` → `EmailService.send_login_email`.
4. Member clicks link → GET `/login/link/<token>` → consume, set session cookie (2-week rolling), update `last_login_at`, redirect to `next` or home.
5. On consumed/expired/unknown token: render "This link is expired or already used. Request a new one." page with one-click form.

### Admin password login (unlisted)

`/login/password` — existing email+password form, unchanged behavior, sets the same session cookie.

### Edge cases & error handling

- **Expired/consumed link** → "Link expired" page with re-request form.
- **Throttled** → friendly "We just sent you a link, check your inbox or try again in a minute" — no detailed timing leak.
- **Email send failure (Resend down)** → log the error, show "We couldn't send the email — please try again or contact an admin", do NOT mark the link consumed.
- **Member without email + invite click** (defensive; button should be disabled): 400 "Member has no email on file".
- **`is_active=False` user** → behave exactly like the user doesn't exist (silent).

## Email Templates & Config

### Templates (`services/app/templates/emails/`)

- `invite.html` + `invite.txt` — subject: "Welcome to Wood League — claim your account". Body: greeting with `{{ member.name }}`, one line of context ("You've been added to Wood League Chess Club by {{ invited_by.email }}"), single CTA button "Open Wood League" linking to the magic URL, expiry note ("This link expires in 7 days"), ignore-if-unexpected footer, club wordmark.
- `login.html` + `login.txt` — subject: "Your Wood League login link". Body: short, single CTA "Log in to Wood League", "Expires in 15 minutes", ignore-if-unexpected footer.

### Styling

Du Bois palette inlined (cream `#f6f1e7` background, deep ink text, rust accent on the button). Single column, 600px max. Plaintext alternative is mandatory. No tracking pixels, no marketing footer.

### Inlining strategy

`django-anymail` + Resend backend. CSS inlined via `premailer` at render time. Templates hand-written (no React-Email or MJML) to match the project's plain Django+Tailwind ethos.

### Config additions (`app/config.py` `Settings`)

- `email_provider: str = "resend"` (also accepts `"console"` for local dev — `django-anymail`'s console backend prints emails to stdout).
- `resend_api_key: str = ""` (env: `RESEND_API_KEY`).
- `email_from: str = "Wood League <noreply@<your-domain>>"` (env: `EMAIL_FROM`).
- `email_reply_to: str = ""` (optional).
- `app_base_url: str = ""` (env: `APP_BASE_URL`) — needed to build absolute magic-link URLs.
- `magic_link_invite_ttl_hours: int = 168` (7 days).
- `magic_link_login_ttl_minutes: int = 15`.
- `session_ttl_days: int = 14`.

### Deploy

Add `RESEND_API_KEY`, `EMAIL_FROM`, `APP_BASE_URL` to Railway. Verify domain in Resend (SPF + DKIM DNS).

## Rate Limiting

- **Per-email:** ≤1 link/minute, ≤5/hour — implemented in `MagicLinkService.throttle_check` by counting recent `LoginLink` rows for that user.
- **Per-IP:** ≤20/hour on `/login` POST and `/login/link/<token>` — implemented via `django-ratelimit`.
- Throttle responses do not differ from normal responses on `/login` (still the same "Check your email" page) to avoid information leaks.

## Testing

### Unit (services, no HTTP)

- `magic_link_service`: issue creates a row with hashed token; raw token returned once; issuing a new link invalidates prior unconsumed links of the same purpose; consume marks `consumed_at` + returns `AuthUser`; consume rejects expired / consumed / unknown / wrong-purpose tokens; throttle counts only recent rows for the user.
- `email_service`: invite + login templates render without error for representative fixtures; rendered HTML contains the magic URL and expiry note; plaintext alternative present; uses `locmem` backend via `django-anymail`'s test helpers.
- `auth_service.create_user_passwordless`: creates user with NULL `password_hash`, role defaults to member.

### View tests

- `/login` GET renders the email-only form.
- `/login` POST always renders "check your email" (existing AND nonexistent users) — enumeration guard.
- `/login` POST triggers exactly one email per submit when not throttled.
- Throttle: second submit within 60s does NOT send a second email; user gets the same confirmation page.
- `/login/link/<token>` consumes, sets session cookie, redirects, updates `last_login_at`.
- `/login/link/<token>` with consumed/expired token renders the re-request page, does NOT log in.
- `/login/password` still works for admin.
- `member_send_invite`: non-admin → 403; admin + member without email → 400; admin + member with email but no user → creates user, sends email, sets `Member.user_id`; admin + member with existing user → "resend" path issues new link, invalidates prior.

### Integration / coverage

- Migration round-trip on a clean DB.
- Existing test gate (`ruff → bandit/semgrep → radon/xenon → mypy → pytest+cov`) stays green; new code targets the project coverage threshold.

### Manual smoke test

- `EMAIL_PROVIDER=console` locally: add a member with an email → click invite → grab URL from terminal → open in incognito → land logged in → log out → `/login` → enter email → grab URL → land logged in.

## Open Questions

None at this time.
