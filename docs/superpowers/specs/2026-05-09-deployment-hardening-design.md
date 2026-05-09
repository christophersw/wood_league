# Deployment Hardening — Design Spec

**Date:** 2026-05-09
**Issue:** #5 (Django app running with DEBUG=True in production)
**Related:** #7 (transactional email provider), #8 (fun error pages)

---

## Goal

Bring `services/app/config/settings.py` into compliance with the Django deployment checklist. All changes use Option A: a single settings file with an environment-gated production block at the bottom.

---

## Section 1: Critical Settings

**File:** `services/app/config/settings.py`

`SECRET_KEY` and `DEBUG` both currently have unsafe defaults. Fix:

```python
# Fails hard at startup if SECRET_KEY is not set in the environment
SECRET_KEY = config("SECRET_KEY")

# Safe default — missing env var means production-safe, not debug mode
DEBUG = config("DEBUG", default=False, cast=bool)
```

- `SECRET_KEY` with no default causes `python-decouple` to raise `UndefinedValueError` at startup. The app will not boot without it set in the environment.
- `DEBUG` default flips from `True` to `False`. A missing env var is now safe.

---

## Section 2: HTTPS and Cookie Security (Production Guard Block)

Add a block at the bottom of `settings.py` that activates only when `DEBUG=False`:

```python
if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000        # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
```

`SECURE_SSL_REDIRECT` is safe on Railway because Railway terminates TLS at the edge and forwards over HTTP internally with `X-Forwarded-Proto: https`. `SecurityMiddleware` (already in the middleware stack) handles this correctly. No `SECURE_PROXY_SSL_HEADER` override is needed.

---

## Section 3: Error Reporting

Add to `settings.py`:

```python
ADMINS = [("Chris", config("DJANGO_ADMIN_EMAIL", default=""))]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "mail_admins": {"class": "django.utils.log.AdminEmailHandler"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {
            "handlers": ["console", "mail_admins"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
```

- Console handler captures all WARNING+ logs; Railway collects stdout.
- `mail_admins` handler fires on ERROR+ Django logs (unhandled 500s).
- Email sending requires `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` env vars — blocked on issue #7 (transactional email provider).
- If email env vars are absent, Django silently skips sending; the app does not crash.

---

## Section 4: Custom Error Templates

Create four minimal templates at `services/app/templates/`:

| File | Trigger |
|------|---------|
| `404.html` | Page not found |
| `500.html` | Server error |
| `403.html` | Permission denied |
| `400.html` | Bad request |

Each template must extend the app's base template and include a link home. Content is intentionally plain for now — issue #8 tracks adding club-themed copy.

---

## Section 5: Verification

After all changes are deployed, run:

```bash
python manage.py check --deploy --settings=config.settings
```

A clean pass (no warnings, no errors) is the acceptance criterion for issue #5.

---

## New Environment Variables Required

| Variable | Purpose | Required |
|----------|---------|----------|
| `SECRET_KEY` | Django secret key | Yes — app won't start without it |
| `DEBUG` | Debug mode flag | No — defaults to `False` |
| `DJANGO_ADMIN_EMAIL` | 500 error notification address | No — skipped if absent |
| `EMAIL_HOST` | SMTP host (blocked on #7) | No — skipped if absent |
| `EMAIL_PORT` | SMTP port (blocked on #7) | No — skipped if absent |
| `EMAIL_HOST_USER` | SMTP user (blocked on #7) | No — skipped if absent |
| `EMAIL_HOST_PASSWORD` | SMTP password (blocked on #7) | No — skipped if absent |

---

## Acceptance Criteria

- [ ] `DEBUG=False` in production with no insecure default
- [ ] `SECRET_KEY` raises `UndefinedValueError` if unset — no fallback
- [ ] `CSRF_COOKIE_SECURE = True` in production
- [ ] `SESSION_COOKIE_SECURE = True` in production
- [ ] `SECURE_SSL_REDIRECT = True` in production
- [ ] HSTS configured (`SECURE_HSTS_SECONDS=31536000`, `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`)
- [ ] `SECURE_CONTENT_TYPE_NOSNIFF = True` in production
- [ ] `LOGGING` config defined; errors surface in Railway logs
- [ ] `ADMINS` set via env var
- [ ] Custom `404.html`, `500.html`, `403.html`, `400.html` templates exist
- [ ] `manage.py check --deploy` passes clean
