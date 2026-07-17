"""Per-string settings hash for translation-cache keys.

Why per-string
--------------
Cache keys embed a "settings hash" so that changing translation-relevant
settings invalidates stale cached output. The first implementation hashed
the ENTIRE glossary into every key, which meant editing a single glossary
term invalidated the whole cache — including the vast majority of strings
that don't contain that term at all and whose prompts (and therefore
correct translations) are completely unchanged.

This module computes the hash from only what actually influences a given
string's prompt:

  * the prompt version / persona / custom rules (global, affect everything), and
  * the glossary entries that MATCH this specific source text — i.e. exactly
    the pairs GlossaryManager.build_prompt_snippet() would inject into the
    system prompt for it (same selection logic, mirrored below).

Consequences:

  * Editing/adding/removing a glossary term re-translates only the strings
    where that term occurs. Everything else keeps its cache.
  * A string with NO matching glossary terms hashes to just
    (prompt version, persona, rules) — which is byte-identical to the hash
    the original pre-fix builds produced (their glossary contribution was
    silently skipped by a swallowed AttributeError). Cache entries
    accumulated under those builds therefore become VALID AGAIN for every
    glossary-free string, instead of staying orphaned forever.

Shared by OllamaWorker, OpenAICompatWorker, ClaudeTranslationWorker and the
string-editor write-through in main_window, so all four always agree on the
key for a given string.
"""
from __future__ import annotations

import hashlib
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Bump when prompt-construction changes in a way that should invalidate
# previously cached translations. Kept here (single source of truth) and
# re-exported by the workers. Value 5 matches the workers' historical value
# — do NOT bump for the per-string-hash migration itself, or the
# cache-revival property described above is lost.
PROMPT_VERSION = 5


def base_settings_parts(persona: str = "", rules: str = "") -> List[str]:
    """The global (string-independent) hash components.

    Must keep producing exactly ["pv5", "persona=…", "rules=…"] in this
    order/format: it is what both the original builds and the
    full-glossary-hash builds emitted for these three parts, and the
    glossary-free-string hash equalling the original builds' hash is what
    lets old caches revive (see module docstring).
    """
    return [f"pv{PROMPT_VERSION}", f"persona={persona}", f"rules={rules}"]


def matched_glossary_pairs(
    glossary_manager, source_text: str
) -> List[Tuple[str, str]]:
    """(source_term, target_term) pairs that build_prompt_snippet() would
    inject into the prompt for *source_text*.

    Mirrors GlossaryManager.build_prompt_snippet()'s selection exactly:
    first hit per source_term wins (project entries shadow global ones via
    find_terms_in_text's ordering), entries with an empty target_term are
    skipped. Returns [] when there is no manager or nothing matches.
    """
    if glossary_manager is None or not source_text:
        return []
    try:
        hits = glossary_manager.find_terms_in_text(source_text)
    except Exception:
        logger.exception("Glossary term matching failed; hashing without terms")
        return []
    seen: dict = {}
    for _s, _e, entry in hits:
        if entry.source_term not in seen and entry.target_term:
            seen[entry.source_term] = entry.target_term
    return list(seen.items())


def settings_hash_for_text(
    glossary_manager,
    source_text: str,
    base_parts: Optional[List[str]] = None,
    persona: str = "",
    rules: str = "",
) -> str:
    """12-hex-char settings hash for *source_text*'s cache key.

    *base_parts* (from base_settings_parts()) can be passed in when hashing
    many strings in one batch, so persona/rules formatting isn't redone per
    string. The matched glossary pairs are sorted before hashing so the hash
    depends only on WHICH pairs apply, not on their positions in the text.
    """
    parts = list(base_parts) if base_parts is not None else base_settings_parts(persona, rules)
    for src_term, tgt_term in sorted(matched_glossary_pairs(glossary_manager, source_text)):
        parts.append(f"{src_term}={tgt_term}")
    combined = "\n".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]
