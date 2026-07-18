"""
Translation memory: a pre-loaded dictionary of correct translations keyed by
string ID and source text.

Intended for reference files where a prior (human or assisted) translation
already exists.  OllamaWorker checks this before calling the model, so known
strings are never retranslated.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Matches the app's TXT export format:
#   {line_num} 0x{ID} "{Original}" "{Translated}"
_LINE_RE = re.compile(
    r'^\d+\s+0x([0-9A-Fa-f]+)\s+"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"$',
    re.MULTILINE,
)

_BACKSLASH_RE = re.compile(r'\\(.)')
_ESCAPE_MAP = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def _unescape(s: str) -> str:
    return _BACKSLASH_RE.sub(lambda m: _ESCAPE_MAP.get(m.group(1), m.group(1)), s)


class TranslationMemory:
    """
    In-memory map of string ID → correct translation text.

    Supports two loading modes:

    * Normal mode (``use_original=False``):
      Uses the "Translated" column.  Entries with empty "Translated" are skipped.

    * Reference mode (``use_original=True``):
      When "Translated" is empty, falls back to the "Original" column.
      Use this for reference files where the *source file* is already in the
      target language (e.g. the ``_ru.ILSTRINGS`` slot already holds Ukrainian
      text from a previous translation pass).
    """

    def __init__(self) -> None:
        self._by_id:  dict[int, str] = {}   # string_id → translation
        self._by_src: dict[str, str] = {}   # original_text → translation
        # string_id → source text that translation was made FROM, when known.
        # Used by get_by_id() to verify an ID hit actually refers to the same
        # string: Bethesda string IDs are only unique WITHIN one plugin, so a
        # TM built from Starfield.esm and a mod's .strings file can share raw
        # ID values that mean completely different strings. Without this
        # check, get_by_id() -- consulted FIRST in every worker's TM cascade,
        # before any text comparison -- silently returns the official
        # translation of an unrelated string and it ships as a "tm" hit with
        # no human in the loop.
        self._id_src: dict[int, str] = {}
        self.source_path: str = ""
        self.loaded_count: int = 0

        # Word-hash → [source_text] inverted index for get_fuzzy(), built/
        # refreshed lazily -- see _ensure_word_index(). Avoids re-tokenizing
        # and scoring every candidate in _by_src (which can be 100k+ entries
        # in a merged reference TM) on every single fuzzy lookup.
        self._word_index: dict[int, list[str]] = {}
        self._word_index_size: int = -1

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(
        self,
        path: str | Path,
        use_original: bool = False,
    ) -> int:
        """
        Parse *path* and populate the memory.

        Returns the number of entries loaded.
        Merges with any previously loaded data (call :meth:`clear` first
        if you want a clean slate).
        """
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        self.source_path = str(path)
        count = 0

        for m in _LINE_RE.finditer(text):
            sid  = int(m.group(1), 16)
            orig = _unescape(m.group(2))
            trans = _unescape(m.group(3))

            if trans:
                self._by_id[sid]   = trans
                self._id_src[sid]  = orig
                self._by_src[orig] = trans
                count += 1
            elif use_original and orig:
                # Reference-mode: "Original" already in target language
                self._by_id[sid] = orig
                self._id_src[sid] = orig
                count += 1

        self.loaded_count = len(self._by_id)
        return count

    def load_strings_file(self, path: str | Path) -> int:
        """Load a BethesdaStringFile (.strings/.dlstrings/.ilstrings) as a TM.

        String IDs map directly to translated text.  Skips empty entries.
        Returns the number of entries loaded.  Merges with existing data.
        """
        from bethesda_strings.core import BethesdaStringFile
        sf = BethesdaStringFile(str(path))
        count = 0
        for string_id, text in sf.strings.items():
            if text and text.strip():
                self._by_id[string_id] = text
                count += 1
        self.loaded_count = len(self._by_id)
        self.source_path = str(path)
        return count

    def clear(self) -> None:
        self._by_id.clear()
        self._by_src.clear()
        self._id_src.clear()
        self.loaded_count = 0
        # Invalidate the fuzzy word index. _ensure_word_index() only compares
        # len(_by_src) between builds, so clear() + reloading a corpus that
        # happens to have the SAME entry count would otherwise keep the stale
        # index -- whose candidate texts no longer exist in _by_src, making
        # get_fuzzy() raise KeyError mid-batch (confirmed by test).
        self._word_index = {}
        self._word_index_size = -1

    def save_json(self, path: Path) -> None:
        """Persist this TM as BSEK's own storage (config dir), independent of
        whatever external TXT/TMX file it was originally loaded from. Mirrors
        Glossary.save_json()'s pattern so the loaded TM survives app restarts
        without the user having to re-import the source file every time."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "by_id": {str(k): v for k, v in self._by_id.items()},
            "by_src": self._by_src,
            "id_src": {str(k): v for k, v in self._id_src.items()},
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load_json(self, path: Path) -> int:
        """Load a previously self-saved JSON snapshot (see save_json). Returns
        the total number of entries loaded (by_id + by_src)."""
        data = json.loads(path.read_text(encoding="utf-8"))
        self._by_id = {int(k): v for k, v in data.get("by_id", {}).items()}
        self._by_src = dict(data.get("by_src", {}))
        self._id_src = {int(k): v for k, v in data.get("id_src", {}).items()}
        self.loaded_count = len(self._by_id)
        # _by_src was wholesale-replaced; force a fuzzy-index rebuild even if
        # the new corpus coincidentally has the same size as the old one.
        self._word_index = {}
        self._word_index_size = -1
        return len(self._by_id) + len(self._by_src)

    # ── Lookup ────────────────────────────────────────────────────────────────

    @staticmethod
    def _norm_src(s: str) -> str:
        """Normalize a source text for identity comparison (line endings + trim)."""
        return s.replace("\r\n", "\n").replace("\r", "\n").strip()

    def get_by_id(self, string_id: int, expected_source: str | None = None) -> str | None:
        """Return translation for *string_id*, or None if not found.

        When *expected_source* is given AND this TM recorded the source text
        the entry was translated from, the two must match (modulo line-ending
        normalization and trimming) -- otherwise None is returned and the
        caller falls through to get_by_source()/get_fuzzy(), which compare by
        text and are therefore collision-safe.

        Rationale: Bethesda string IDs are only unique per plugin. An ID from
        the currently open mod colliding with an unrelated ID in a TM built
        from another plugin (e.g. the official Starfield translation) would
        otherwise return the translation of a completely different string.
        TMs that never recorded source texts (load_strings_file: a bare
        .strings file has only ID→text) keep the legacy unverified behavior,
        as that path is intended for same-plugin version updates.
        """
        hit = self._by_id.get(string_id)
        if hit is None:
            return None
        if expected_source is not None:
            recorded = self._id_src.get(string_id)
            if recorded is not None and self._norm_src(recorded) != self._norm_src(expected_source):
                return None
        return hit

    def get_by_source(self, original: str) -> str | None:
        """Return translation for *original* source text, or None.

        Very short strings (<=3 chars) are excluded even on an EXACT match.
        Confirmed in practice: "OFF" exact-matches the official patch's one
        and only "OFF" entry, which came from an ammo-weight label in a
        completely different mod/context ("실탄 중량 없음") -- unrelated to
        a generic UI on/off toggle. This is the same word-sense-ambiguity
        problem get_fuzzy()'s single-word path already guards against; this
        method needed the identical guard and didn't have it, so a query
        that hit get_by_source() (checked BEFORE get_fuzzy() in the worker's
        lookup order) returned the wrong value before get_fuzzy() was ever
        reached.
        """
        if len(original.strip()) <= 3:
            return None
        return self._by_src.get(original)

    def get_fuzzy(self, original: str, max_score: float = 3.0) -> Optional[str]:
        """Return the best fuzzy match for *original* from the memory source texts.

        Uses xTranslator's word-hash heuristic (gui.fuzzy_match).
        Returns None when no candidate scores below *max_score* or the
        fuzzy_match module is unavailable.

        Only called after get_by_id() and get_by_source() both return None.

        Performance note: fuzzy_score()'s word-position matching can only
        pass max_score if at least (src_wc - threshold) of the source's words
        are found NEAR their expected position in the candidate -- which
        requires those words to appear in the candidate AT ALL. A candidate
        that shares fewer than that many distinct words with the source
        therefore cannot possibly pass, regardless of position. The inverted
        word index below uses this as a safe (if slightly loose -- it ignores
        exact positioning, only requiring *presence*) pre-filter: it's a
        superset of what a full scan would find, never a subset, so results
        are unchanged. Reduces the candidate pool from the full corpus
        (100k+ entries in a merged reference TM) down to only the ones
        sharing meaningful vocabulary with the query -- this is what actually
        matters, since a simple word-*count* filter (an earlier attempt) barely
        helped: ~90% of a typical corpus falls within the word-count window
        of any given medium-length query.
        """
        if not self._by_src:
            return None
        try:
            from gui.fuzzy_match import (
                best_fuzzy_match, tokenize, _define_heuristic_threshold,
            )
        except ImportError:
            return None

        src_words = tokenize(original)
        src_wc = len(src_words)

        if src_wc <= 1:
            # Single-word queries use fuzzy_score()'s separate substring-match
            # path. That path is especially dangerous for a reference TM: a
            # bare word like "Fueling" or "ENABLED" would fuzzily match a
            # totally unrelated longer entry ("Feats require fuel" ->
            # "위업에는 연료가 필요한 법"). For a single word there's no
            # meaningful "fuzzy" -- either the TM has that exact word or it
            # doesn't -- so require an exact (case-insensitive) source match.
            #
            # But exact match alone still isn't safe for very short words.
            # Confirmed in practice: "On" (a UI toggle state, "켜짐") matched
            # the TM's one and only case-insensitive "on" -- which came from
            # an unrelated sentence using "on" as an ordinary preposition, and
            # happened to be rendered "대상:" (Target:) in THAT context.
            # Likewise "OFF" -> "실탄 중량 없음" (a completely unrelated
            # ammo-weight label). Very short words (on/off/no/up/in/at...)
            # are exactly the ones most likely to double as ordinary English
            # function words with unrelated senses scattered across a huge
            # corpus -- a single flat text-key dictionary has no way to tell
            # "the toggle-state word" apart from "the preposition that
            # happens to be spelled the same". Longer single words
            # (ENABLED/DISABLED/STREAMLINED) are essentially always
            # game-specific UI terms without this ambiguity, so they keep
            # using exact-match reuse; anything <=3 characters always goes
            # to the AI fresh instead.
            stripped = original.strip()
            if len(stripped) <= 3:
                return None
            key_lower = stripped.lower()
            for src, tgt in self._by_src.items():
                if src.strip().lower() == key_lower:
                    return tgt
            return None

        self._ensure_word_index()
        threshold = _define_heuristic_threshold(src_wc)

        # Minimum number of the source's DISTINCT words that must appear
        # somewhere in a candidate for it to have any chance of passing.
        unique_src_words = set(src_words)
        min_shared = max(1, len(unique_src_words) - threshold)

        from collections import Counter
        shared_counts: Counter = Counter()
        for w in unique_src_words:
            for cnd_text in self._word_index.get(w, ()):
                shared_counts[cnd_text] += 1

        candidate_keys = [t for t, n in shared_counts.items() if n >= min_shared]

        by_src = self._by_src
        result = best_fuzzy_match(
            original,
            ((k, by_src[k]) for k in candidate_keys if k in by_src),
            max_score=max_score,
        )
        if result is None:
            return None

        matched_translation, _score = result

        # ── Short-string sanity gate ──────────────────────────────────────
        # xTranslator's heuristic score alone is too permissive for SHORT
        # entries. A 3-word UI label like "The Fuel Box" scores 2.0 (< the
        # 3.0 threshold) against "Play the music box" purely because the two
        # share the common words "the" and "box" -- and BSEK, unlike
        # xTranslator, applies the hit directly with no human to reject it,
        # so "The Fuel Box" silently becomes "뮤직 박스 재생하기" (Play the
        # music box). The score works fine for long sentences (a couple of
        # differing words don't matter) but collapses for terse labels where
        # every word carries weight.
        #
        # Fix: for short sources, require the matched candidate's OWN source
        # text to overlap the query heavily in BOTH directions. This rejects
        # coincidental-common-word matches while still allowing genuine near
        # duplicates (trailing punctuation, minor spacing). Longer strings
        # keep the original lenient behavior.
        #
        # Look up the candidate's source text (best_fuzzy_match returns only
        # the translation, so find the key whose translation matched among the
        # small candidate pool -- cheap here since candidate_keys is already
        # narrowed).
        # Short/medium sources are where coincidental-common-word matches do
        # real damage; long sentences tolerate a couple of differing words.
        # 8 words covers terse UI labels and short status lines (the bulk of
        # what gets mis-matched) while leaving genuine sentences alone.
        if src_wc <= 8:
            unique_src = set(src_words)
            cand_src = None
            for k in candidate_keys:
                if by_src[k] == matched_translation:
                    cand_src = k
                    break
            if cand_src is not None:
                cand_words = set(tokenize(cand_src))
                shared = unique_src & cand_words
                # Both directions must be well-covered. e.g. "The Fuel Box" vs
                # "Play the music box" = 0.67/0.50 -> rejected; a real near-dup
                # (only punctuation differs) = ~1.0/~1.0 -> kept.
                ratio_src = len(shared) / len(unique_src) if unique_src else 0.0
                ratio_cand = len(shared) / len(cand_words) if cand_words else 0.0
                if ratio_src < 0.85 or ratio_cand < 0.85:
                    return None

        return matched_translation

    def _ensure_word_index(self) -> None:
        """(Re)build the word-hash → [source_text] inverted index used by
        get_fuzzy(), if _by_src changed size since the last build."""
        if self._word_index_size == len(self._by_src):
            return
        from gui.fuzzy_match import tokenize
        index: dict[int, list[str]] = {}
        for text in self._by_src:
            for w in set(tokenize(text)):
                index.setdefault(w, []).append(text)
        self._word_index = index
        self._word_index_size = len(self._by_src)

    # ── TMX support ───────────────────────────────────────────────────────────

    def load_tmx(
        self,
        path: str | Path,
        source_lang: str = "",
        target_lang: str = "",
    ) -> int:
        """Parse a TMX file and merge its translation units into memory.

        *source_lang* and *target_lang* are BCP-47 language tags (e.g. ``"ru"``,
        ``"uk"``, ``"en-US"``).  If either is empty the method picks the first
        two ``<tuv>`` elements in each ``<tu>`` as source and target respectively.

        Returns the number of new entries loaded.
        """
        path = Path(path)
        self.source_path = str(path)
        count = 0
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            raise ValueError(f"Invalid TMX file: {e}") from e

        root = tree.getroot()
        # Strip namespace prefix if present
        def _tag(elem: ET.Element) -> str:
            t = elem.tag
            return t.split("}")[-1] if "}" in t else t

        src_lower = source_lang.lower()
        tgt_lower = target_lang.lower()

        for tu in root.iter():
            if _tag(tu) != "tu":
                continue
            tuvs: list[tuple[str, str]] = []  # (lang, seg_text)
            for tuv in tu:
                if _tag(tuv) != "tuv":
                    continue
                lang = (tuv.get("lang") or tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower()
                seg = next((c for c in tuv if _tag(c) == "seg"), None)
                if seg is not None:
                    tuvs.append((lang, (seg.text or "").strip()))

            if len(tuvs) < 2:
                continue

            if src_lower and tgt_lower:
                src_text = next((t for l, t in tuvs if l.startswith(src_lower)), "")
                tgt_text = next((t for l, t in tuvs if l.startswith(tgt_lower)), "")
            else:
                src_text = tuvs[0][1]
                tgt_text = tuvs[1][1] if len(tuvs) > 1 else ""

            if src_text and tgt_text:
                self._by_src[src_text] = tgt_text
                count += 1

        self.loaded_count = len(self._by_id) + len(self._by_src)
        return count

    def export_tmx(
        self,
        path: str | Path,
        source_lang: str = "ru",
        target_lang: str = "uk",
        tool_name: str = "Bethesda Strings AI Translator",
    ) -> int:
        """Write the current source→translation pairs as a TMX 1.4b file.

        Returns the number of translation units written.
        """
        path = Path(path)
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        root = ET.Element("tmx", version="1.4")
        header = ET.SubElement(root, "header")
        header.set("creationtool", tool_name)
        header.set("creationtoolversion", "1.0")
        header.set("datatype", "plaintext")
        header.set("segtype", "sentence")
        header.set("adminlang", "en-US")
        header.set("srclang", source_lang)
        header.set("creationdate", now)

        body = ET.SubElement(root, "body")
        count = 0
        for src_text, tgt_text in sorted(self._by_src.items()):
            tu = ET.SubElement(body, "tu")
            tu.set("creationdate", now)

            tuv_src = ET.SubElement(tu, "tuv")
            tuv_src.set("{http://www.w3.org/XML/1998/namespace}lang", source_lang)
            ET.SubElement(tuv_src, "seg").text = src_text

            tuv_tgt = ET.SubElement(tu, "tuv")
            tuv_tgt.set("{http://www.w3.org/XML/1998/namespace}lang", target_lang)
            ET.SubElement(tuv_tgt, "seg").text = tgt_text

            count += 1

        ET.indent(root, space="  ")
        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        return count

    def as_id_dict(self) -> dict[int, str]:
        """Return a copy of the ID→translation mapping."""
        return dict(self._by_id)

    def id_source_map(self) -> dict[int, str]:
        """Return a copy of the ID→source-text mapping (may be empty for TMs
        loaded from bare .strings files, which carry no source text)."""
        return dict(self._id_src)

    def __len__(self) -> int:
        # TXT/JSON loads populate _by_id and _by_src 1:1 (same entries in
        # both), so summing would double-count. TMX loads only ever populate
        # _by_src (TMX carries no Bethesda string ID). max() reports the
        # correct total in both cases without needing to cross-reference
        # which _by_src keys came from which loader.
        return max(len(self._by_id), len(self._by_src))

    def __bool__(self) -> bool:
        # NOTE: must check _by_src too, not just _by_id. load_tmx() never
        # populates _by_id (TMX has no Bethesda string ID), so a TMX-only TM
        # used to evaluate as falsy here even with 100k+ entries in _by_src.
        # Since this __bool__ gates `if self.translation_memory:` in every
        # worker (ollama_worker.py, openai_compat_worker.py) as well as the
        # TM viewer/status indicator, that meant a TMX-loaded TM was silently
        # never consulted during translation, not just invisible in the UI.
        return bool(self._by_id) or bool(self._by_src)
