"""Custom authentication backends for legacy password migration and user authentication."""

import base64
import hashlib
import hmac

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare


class LegacyPbkdf2Hasher(BasePasswordHasher):
    """
    Verifies passwords stored by the Streamlit app as:
        pbkdf2_sha256$<iterations>$<salt>$<digest_url_safe_base64>

    Django's built-in PBKDF2 hasher uses standard base64; the Streamlit app
    used URL-safe base64. This hasher bridges the gap and marks itself as
    needing an upgrade so Django re-hashes with its native hasher on the
    next successful login.
    """

    algorithm = "pbkdf2_sha256_legacy"

    def verify(self, password, encoded):
        """Verify password against URL-safe base64-encoded PBKDF2 hash from legacy Streamlit app."""
        # encoded format: pbkdf2_sha256$<iterations>$<salt>$<digest_urlsafe_b64>
        try:
            _, iterations_str, salt, digest_urlsafe = encoded.split("$", 3)
        except ValueError:
            return False

        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        digest_standard = base64.b64encode(dk).decode("ascii").strip()
        # Convert stored URL-safe b64 to standard b64 for comparison
        stored_standard = base64.b64encode(
            base64.urlsafe_b64decode(digest_urlsafe + "==")
        ).decode("ascii").strip()

        return constant_time_compare(digest_standard, stored_standard)

    def encode(self, password, salt, iterations=None):
        """Not implemented for legacy hasher — only used for verification."""
        raise NotImplementedError("LegacyPbkdf2Hasher is read-only — use Django's default hasher for new passwords")

    def must_update(self, encoded):
        """Always return True to force re-hashing with Django's native hasher on next login."""
        # Always re-hash to Django's native format on next successful login
        return True

    def safe_summary(self, encoded):
        """Return a safe summary of the hash suitable for logging."""
        _, iterations, salt, _ = encoded.split("$", 3)
        return {
            "algorithm": self.algorithm,
            "iterations": iterations,
            "salt": mask_hash(salt),
            "hash": mask_hash("(legacy)"),
        }

    def harden_runtime(self, password, encoded):
        """No-op placeholder to satisfy the hasher interface."""
        pass


class LegacyPbkdf2Backend(ModelBackend):
    """
    Authentication backend that tries the legacy hasher before falling back
    to Django's standard stack. The standard ModelBackend already calls
    check_password which iterates PASSWORD_HASHERS, so this backend just
    ensures the legacy hasher is included in that list via settings.
    """
    pass
