"""Local encryption-at-rest for secrets (API keys, OAuth tokens).

Design: a random 32-byte key is generated on first run and stored at
`secret_key_path()` with 0600 permissions. All secrets (provider API keys,
MCP OAuth tokens) are stored as a single encrypted JSON blob using Fernet
(AES-128-CBC + HMAC via the `cryptography` package). This is local-machine
encryption-at-rest, not a substitute for OS-level disk encryption or a
proper secret manager — it protects against casual disclosure (e.g.
accidentally committing the data dir, or another local user without root
reading the file), not against an attacker with root/your user account.

No secret ever leaves the machine and no secret is logged.
"""
from __future__ import annotations

import os
import stat
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from local_ai_workspace.storage.json_store import read_json, write_json_atomic
from local_ai_workspace.storage.paths import secret_key_path, secrets_path


def _get_or_create_key() -> bytes:
    key_path = secret_key_path()
    if key_path.exists():
        return key_path.read_bytes()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # best-effort on platforms without POSIX permission bits
    return key


def _fernet() -> Fernet:
    return Fernet(_get_or_create_key())


def load_secrets() -> dict[str, Any]:
    """Return the decrypted secrets dict, or {} if none/corrupt/unreadable."""
    path = secrets_path()
    if not path.exists():
        return {}
    try:
        encrypted = path.read_bytes()
        decrypted = _fernet().decrypt(encrypted)
        import json

        return json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, ValueError, OSError):
        return {}


def save_secrets(data: dict[str, Any]) -> None:
    import json

    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    encrypted = _fernet().encrypt(payload)
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypted)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def get_secret(key: str) -> str | None:
    return load_secrets().get(key)


def set_secret(key: str, value: str) -> None:
    secrets = load_secrets()
    secrets[key] = value
    save_secrets(secrets)


def delete_secret(key: str) -> None:
    secrets = load_secrets()
    if key in secrets:
        del secrets[key]
        save_secrets(secrets)
