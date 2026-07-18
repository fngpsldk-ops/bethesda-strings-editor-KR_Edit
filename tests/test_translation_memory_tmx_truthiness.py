"""Regression test for a TMX-only-loaded TranslationMemory being silently
treated as "empty"/"not loaded" everywhere `if self.translation_memory:` (or
`if not tm:`) is checked -- the TM viewer dialog, the status-bar indicator,
and (far more importantly) the TM lookup gate in every translation backend
(ollama_worker.py, openai_compat_worker.py).

Root cause: load_tmx() only ever populates TranslationMemory._by_src (TMX
carries no Bethesda string ID, so _by_id stays empty), but __bool__/__len__
used to look at _by_id alone. A TMX loaded with 100k+ entries therefore
evaluated as falsy, so it was never consulted during actual translation --
not just invisible in the UI.
"""
from __future__ import annotations

from pathlib import Path

from gui.translation_memory import TranslationMemory


def _write_tmx(path: Path) -> Path:
    path.write_text(
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<tmx version=\"1.4\">\n"
        "  <header creationtool=\"test\" creationtoolversion=\"1.0\" "
        "datatype=\"plaintext\" segtype=\"sentence\" adminlang=\"en-US\" "
        "srclang=\"en\" />\n"
        "  <body>\n"
        "    <tu>\n"
        "      <tuv xml:lang=\"en\"><seg>Grav Drive</seg></tuv>\n"
        "      <tuv xml:lang=\"ko\"><seg>중력 드라이브</seg></tuv>\n"
        "    </tu>\n"
        "    <tu>\n"
        "      <tuv xml:lang=\"en\"><seg>Boost Pack</seg></tuv>\n"
        "      <tuv xml:lang=\"ko\"><seg>부스트 팩</seg></tuv>\n"
        "    </tu>\n"
        "  </body>\n"
        "</tmx>\n",
        encoding="utf-8",
    )
    return path


def test_tmx_only_load_is_truthy(tmp_path):
    """A TM loaded purely from TMX (no _by_id data) must still be truthy --
    this is exactly the `if self.translation_memory:` check every worker
    uses to decide whether to consult TM at all."""
    tm = TranslationMemory()
    tmx_path = _write_tmx(tmp_path / "test.tmx")
    loaded = tm.load_tmx(tmx_path, source_lang="en", target_lang="ko")

    assert loaded == 2
    assert len(tm._by_id) == 0          # TMX never populates this
    assert len(tm._by_src) == 2         # data is really there
    assert bool(tm) is True             # <- the actual bug
    assert len(tm) == 2                 # matches _by_src, not the empty _by_id


def test_tmx_only_load_is_consulted_via_worker_style_gate(tmp_path):
    """Reproduces the exact gate expression used in ollama_worker.py /
    openai_compat_worker.py: `if not is_retry and self.translation_memory:`."""
    tm = TranslationMemory()
    _write_tmx(tmp_path / "test.tmx")
    tm.load_tmx(tmp_path / "test.tmx", source_lang="en", target_lang="ko")

    is_retry = False
    consulted = not is_retry and bool(tm)
    assert consulted is True

    hit = tm.get_by_source("Grav Drive")
    assert hit == "중력 드라이브"


def test_empty_tm_is_falsy():
    tm = TranslationMemory()
    assert bool(tm) is False
    assert len(tm) == 0


def test_txt_load_bool_and_len_unaffected(tmp_path):
    """TXT loads populate _by_id and _by_src 1:1 with the same entries --
    len() must not double-count them after the max()-based fix."""
    txt_path = tmp_path / "tm.txt"
    txt_path.write_text(
        '1 0x0000000A "Grav Drive" "중력 드라이브"\n'
        '2 0x0000000B "Boost Pack" "부스트 팩"\n',
        encoding="utf-8",
    )
    tm = TranslationMemory()
    tm.load(txt_path, use_original=False)

    assert bool(tm) is True
    assert len(tm) == 2
    assert len(tm._by_id) == 2
    assert len(tm._by_src) == 2
