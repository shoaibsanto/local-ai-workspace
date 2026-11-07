"""OS keyring integration for the Fernet master key.

Tries to store/retrieve the master key via the OS-native credential store
(macOS Keychain, Windows Credential Manager, Secret Service/libsecret on
Linux) through the `keyring` package. On headless Linux boxes with no secret
service running (the common case for this app, e.g. servers/containers),
`keyring` raises -- we catch that and let the caller fall back to the
existing file-based key in storage/secrets.py. Never crashes the app.
"""

from __future__ import annotations

import logging
from types import ModuleType

logger = logging.getLogger(__name__)

SERVICE_NAME = "local-ai-workspace"
KEY_USERNAME = "fernet-master-key"


def _get_keyring_module() -> ModuleType | None:
    try:
        import keyring

        return keyring
    except ImportError:
        return None


def is_keyring_available() -> bool:
    """Best-effort check: can we actually talk to a working keyring backend?"""
    kr = _get_keyring_module()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
        # The "fail" backend (keyring.backends.fail.Keyring) is returned when
        # no real backend is usable (e.g. headless Linux, no Secret Service).
        backend_name = type(backend).__module__ + "." + type(backend).__name__
        return "fail" not in backend_name.lower()
    except Exception:  # noqa: BLE001 - any keyring probing failure means "unavailable"
        return False


def get_key() -> bytes | None:
    """Return the master key from the OS keyring, or None if unavailable /
    not yet stored / any error occurs talking to the backend."""
    kr = _get_keyring_module()
    if kr is None:
        return None
    try:
        value = kr.get_password(SERVICE_NAME, KEY_USERNAME)
        if value is None:
            return None
        return str(value).encode("utf-8")
    except Exception as e:  # noqa: BLE001 - keyring backends raise all sorts of things
        logger.warning("Keyring read failed, falling back to file-based key: %s", e)
        return None


def set_key(key: bytes) -> bool:
    """Store the master key in the OS keyring. Returns True on success,
    False if keyring is unavailable or the write failed for any reason."""
    kr = _get_keyring_module()
    if kr is None:
        return False
    try:
        kr.set_password(SERVICE_NAME, KEY_USERNAME, key.decode("utf-8"))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Keyring write failed, falling back to file-based key: %s", e)
        return False


def backend_description() -> str:
    """Human-readable description of the active keyring backend, for logging."""
    kr = _get_keyring_module()
    if kr is None:
        return "none (keyring package not installed)"
    try:
        backend = kr.get_keyring()
        return type(backend).__module__ + "." + type(backend).__name__
    except Exception as e:  # noqa: BLE001
        return f"unavailable ({e})"


def delete_key() -> bool:
    """Delete the stored master key from the OS keyring, if present.
    Returns True if deleted (or nothing to delete), False on error."""
    kr = _get_keyring_module()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE_NAME, KEY_USERNAME)
        return True
    except Exception:  # noqa: BLE001 - e.g. PasswordDeleteError if nothing stored
        return False
