"""Authentication service for user login, token management, and password hashing.

Handles PBKDF2 password hashing, HMAC-based login token generation and verification, and user account management.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import os
import time

from sqlalchemy import func, select

from app.config import get_settings
from app.storage.database import get_session, init_db
from app.storage.models import User

PBKDF2_SCHEME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000


@dataclass
class AuthUser:
    """Authenticated user information for session management."""
    id: int
    email: str
    role: str


def _b64_encode(raw: bytes) -> str:
    """Encode bytes as URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(text: str) -> bytes:
    """Decode URL-safe base64 text to bytes, handling missing padding."""
    padding = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-SHA256 with random salt."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"{PBKDF2_SCHEME}${PBKDF2_ITERATIONS}${_b64_encode(salt)}${_b64_encode(dk)}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against PBKDF2 hash or legacy bcrypt hash."""
    if stored_hash.startswith(f"{PBKDF2_SCHEME}$"):
        parts = stored_hash.split("$", 3)
        if len(parts) != 4:
            return False
        _, iter_text, salt_text, digest_text = parts
        try:
            iterations = int(iter_text)
            salt = _b64_decode(salt_text)
            expected = _b64_decode(digest_text)
        except (ValueError, TypeError):
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)

    # Best-effort compatibility with existing bcrypt-style hashes.
    if stored_hash.startswith("$2"):
        try:
            import bcrypt

            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except (ImportError, ValueError):
            return False

    return False


class AuthService:
    """Manages user authentication, password hashing, and login token lifecycle."""
    def __init__(self) -> None:
        """Initialize with config settings and database."""
        self.settings = get_settings()
        init_db()

    @staticmethod
    def normalize_email(email: str) -> str:
        """Lowercase and trim email address."""
        return (email or "").strip().lower()

    def _token_signing_key(self) -> bytes:
        """Get HMAC signing key from config, falling back to defaults."""
        key = (
            self.settings.auth_signing_key.strip()
            or self.settings.auth_bootstrap_admin_password.strip()
            or "wood-league-chess-dev-key"
        )
        return key.encode("utf-8")

    def create_login_token(self, user_id: int) -> str:
        """Generate HMAC-signed login token with expiration."""
        exp = int(time.time()) + int(self.settings.auth_token_ttl_seconds)
        msg = f"{user_id}.{exp}".encode("utf-8")
        sig = hmac.new(self._token_signing_key(), msg, hashlib.sha256).digest()
        return f"{user_id}.{exp}.{_b64_encode(sig)}"

    def verify_login_token(self, token: str) -> AuthUser | None:
        """Validate login token signature and expiration; return user if valid."""
        parts = (token or "").split(".")
        if len(parts) != 3:
            return None

        user_id_text, exp_text, sig_text = parts
        try:
            user_id = int(user_id_text)
            exp = int(exp_text)
            sig = _b64_decode(sig_text)
        except (ValueError, TypeError):
            return None

        if exp < int(time.time()):
            return None

        msg = f"{user_id}.{exp}".encode("utf-8")
        expected = hmac.new(self._token_signing_key(), msg, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None

        return self.get_user(user_id)

    def bootstrap_admin_if_needed(self) -> None:
        """Create initial admin user from config if database is empty."""
        if not self.settings.auth_enabled:
            return

        email = self.normalize_email(self.settings.auth_bootstrap_admin_email)
        password = self.settings.auth_bootstrap_admin_password.strip()
        if not email or not password:
            return

        with get_session() as session:
            total_users = session.scalar(select(func.count()).select_from(User)) or 0
            if total_users > 0:
                return

            session.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    role="admin",
                    is_active=True,
                )
            )
            session.commit()

    def authenticate(self, email: str, password: str) -> AuthUser | None:
        """Verify email and password; return AuthUser if credentials valid."""
        normalized = self.normalize_email(email)
        if not normalized or not password:
            return None

        with get_session() as session:
            user = session.scalar(select(User).where(User.email == normalized))
            if user is None or not user.is_active:
                return None
            if not verify_password(password, user.password_hash):
                return None
            return AuthUser(id=user.id, email=user.email, role=user.role)

    def get_user(self, user_id: int) -> AuthUser | None:
        """Fetch active user by ID."""
        with get_session() as session:
            user = session.scalar(select(User).where(User.id == user_id))
            if user is None or not user.is_active:
                return None
            return AuthUser(id=user.id, email=user.email, role=user.role)

    def create_user(self, email: str, password: str, role: str = "member") -> AuthUser:
        """Create new user with email, password, and role; validate inputs."""
        normalized = self.normalize_email(email)
        if not normalized:
            raise ValueError("Email is required")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        safe_role = role if role in {"admin", "member"} else "member"

        with get_session() as session:
            existing = session.scalar(select(User).where(User.email == normalized))
            if existing is not None:
                raise ValueError("User already exists")

            user = User(
                email=normalized,
                password_hash=hash_password(password),
                role=safe_role,
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return AuthUser(id=user.id, email=user.email, role=user.role)
