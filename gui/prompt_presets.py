"""BSEK Prompt Editor — preset management.

Presets are stored inside ``AppSettings.prompt_presets`` (a plain dict), which
already round-trips through the existing JSON config file via
``AppSettings.to_dict()`` / ``AppSettings.from_dict()`` — no separate preset
file or bespoke I/O code needed.

This module is intentionally GUI-free so it can be unit-tested and reasoned
about on its own; the Prompt Editor dialog (step 3) will be a thin UI layer
on top of these functions.

Preset shape (per entry in ``settings.prompt_presets``)::

    {
        "persona": "...",       # str, may be empty
        "custom_rules": "...",  # str, may be empty
    }

A preset with both fields empty is valid — it explicitly means "use the
BSEK built-in defaults", which is different from *no preset selected*.
"""
from __future__ import annotations

from typing import Optional

# Sentinel display name for "no preset / BSEK built-in defaults". Never stored
# as a real key in settings.prompt_presets — the GUI (step 3) shows this as
# a dropdown option that resolves to empty persona/custom_rules.
BUILTIN_DEFAULT_LABEL = "BSEK 기본값"

_MAX_NAME_LENGTH = 60


class PresetNameError(ValueError):
    """Raised when a preset name is invalid (empty, too long, or reserved)."""


def _validate_name(name: str) -> str:
    """Normalize and validate a preset name. Raises PresetNameError if invalid."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise PresetNameError("프리셋 이름을 입력해주세요.")
    if len(cleaned) > _MAX_NAME_LENGTH:
        raise PresetNameError(f"프리셋 이름은 {_MAX_NAME_LENGTH}자 이내여야 합니다.")
    if cleaned == BUILTIN_DEFAULT_LABEL:
        raise PresetNameError(
            f"'{BUILTIN_DEFAULT_LABEL}'은(는) 예약된 이름입니다. 다른 이름을 사용해주세요."
        )
    return cleaned


def list_preset_names(settings) -> list[str]:
    """Return saved preset names, sorted for stable display order."""
    presets = getattr(settings, "prompt_presets", None) or {}
    return sorted(presets.keys())


def get_preset(settings, name: str) -> Optional[dict]:
    """Return {"persona": str, "custom_rules": str} for *name*, or None if missing."""
    presets = getattr(settings, "prompt_presets", None) or {}
    entry = presets.get(name)
    if entry is None:
        return None
    return {
        "persona": entry.get("persona", ""),
        "custom_rules": entry.get("custom_rules", ""),
    }


def save_preset(settings, name: str, persona: str, custom_rules: str) -> str:
    """Create or overwrite a preset on *settings* (in memory — caller must
    still call ``save_settings(settings)`` to persist to disk).

    Returns the normalized (trimmed) preset name that was actually stored.
    Raises PresetNameError if *name* is invalid.
    """
    clean_name = _validate_name(name)
    if not isinstance(getattr(settings, "prompt_presets", None), dict):
        settings.prompt_presets = {}
    settings.prompt_presets[clean_name] = {
        "persona": (persona or "").strip(),
        "custom_rules": (custom_rules or "").strip(),
    }
    return clean_name


def delete_preset(settings, name: str) -> bool:
    """Remove a preset by name. Returns True if it existed and was removed."""
    presets = getattr(settings, "prompt_presets", None)
    if not isinstance(presets, dict) or name not in presets:
        return False
    del presets[name]
    return True


def rename_preset(settings, old_name: str, new_name: str) -> str:
    """Rename an existing preset, preserving its content.

    Raises PresetNameError if *new_name* is invalid, or KeyError if
    *old_name* does not exist.
    """
    entry = get_preset(settings, old_name)
    if entry is None:
        raise KeyError(f"Preset not found: {old_name!r}")
    clean_new_name = _validate_name(new_name)
    delete_preset(settings, old_name)
    settings.prompt_presets[clean_new_name] = entry
    return clean_new_name
