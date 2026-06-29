"""OpenAI-compatible backend key storage for BSEK.

Mirrors the pattern in gui/claude_client.py — the API key is kept in
SecretStore (system keyring / encrypted file) so it never appears in
config.json in plain text.

Usage:
    from gui.openai_compat_client import get_openai_compat_api_key, set_openai_compat_api_key
    key = get_openai_compat_api_key()  # None if not set
    set_openai_compat_api_key("sk-...")
"""
from typing import Optional

_SECRET_KEY = "openai_compat_api_key"


def get_openai_compat_api_key() -> Optional[str]:
    """Retrieve the OpenAI-compatible API key from SecretStore."""
    try:
        from gui.secret_store import SecretStore
        return SecretStore().get(_SECRET_KEY) or None
    except Exception:
        return None


def set_openai_compat_api_key(key: str) -> bool:
    """Persist the OpenAI-compatible API key to SecretStore. Returns True on success."""
    try:
        from gui.secret_store import SecretStore
        SecretStore().set(_SECRET_KEY, key.strip())
        return True
    except Exception:
        return False


def delete_openai_compat_api_key() -> None:
    """Remove the OpenAI-compatible API key from SecretStore."""
    try:
        from gui.secret_store import SecretStore
        SecretStore().delete(_SECRET_KEY)
    except Exception:
        pass
