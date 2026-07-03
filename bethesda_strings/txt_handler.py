"""
Parser and writer for Starfield interface TXT translation files.

Format: UTF-16 LE with BOM, one entry per line:
    $KEY<TAB>VALUE<CRLF>

Lines not starting with '$' are preserved verbatim (comments, blanks).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

logger = logging.getLogger(__name__)


@dataclass
class TxtStringEntry:
    """A single translatable entry from a Starfield interface TXT file."""

    key: str        # e.g. "$ABORT"
    text: str       # current text value (source language)
    line_number: int = 0

    # ---- compatibility shim so StringTableModel can treat this like StringDataObject ----
    @property
    def id(self) -> str:
        return self.key

    def get_string(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        _ = encoding, errors  # unused — text is already a Python str
        return self.text

    def set_string(self, text: str, encoding: str = "utf-8") -> None:
        _ = encoding  # unused — stored as Python str
        self.text = text

    @property
    def length(self) -> int:
        return len(self.text)

    @property
    def relative_offset(self) -> int:
        return self.line_number


# A "raw line" is any non-entry content (blank lines, comment lines, BOM-only first line).
_RawLine = str


class TxtStringFile:
    """Starfield interface TXT translation file (translate_en.txt, translate_ru.txt, …)."""

    encoding: str = "utf-16"  # for display in the UI

    def __init__(self) -> None:
        self.strings: List[TxtStringEntry] = []
        # _lines preserves the original file order for lossless round-trip save.
        # Each element is either a TxtStringEntry or a raw string.
        self._lines: List[Union[TxtStringEntry, _RawLine]] = []

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def load(self, path: Union[str, Path]) -> None:
        """Parse a UTF-16 TXT file from disk into entries."""
        path = Path(path)
        with open(path, "rb") as fh:
            data = fh.read()
        self.load_from_bytes(data)
        logger.info("Loaded %d strings from %s", len(self.strings), path.name)

    def load_from_bytes(self, data: bytes) -> None:
        """Parse TXT content already in memory (e.g. extracted from a BA2 archive)."""
        try:
            text = data.decode("utf-16")
        except UnicodeError:
            text = data.decode("utf-8", errors="replace")
        self._parse_raw_lines(text.splitlines(keepends=True))

    def _parse_raw_lines(self, raw_lines) -> None:
        self.strings.clear()
        self._lines.clear()

        for lineno, line in enumerate(raw_lines, 1):
            stripped = line.lstrip("﻿")  # strip BOM if on first line
            if stripped.startswith("$") and "\t" in stripped:
                key, _, value = stripped.partition("\t")
                entry = TxtStringEntry(
                    key=key,
                    text=value.rstrip("\r\n"),
                    line_number=lineno,
                )
                self.strings.append(entry)
                self._lines.append(entry)
            else:
                # Preserve blank lines / comment lines verbatim
                self._lines.append(line)

    def save(self, path: Union[str, Path]) -> None:
        """Write the file back to disk in UTF-16 LE format with BOM."""
        path = Path(path)
        with open(path, "wb") as fh:
            fh.write(self.to_bytes())
        logger.info("Saved %d strings to %s", len(self.strings), path.name)

    def to_bytes(self) -> bytes:
        """Serialize back to UTF-16 LE bytes with BOM (for BA2 repacking)."""
        parts = ["﻿"]  # BOM
        for item in self._lines:
            if isinstance(item, TxtStringEntry):
                parts.append(f"{item.key}\t{item.text}\r\n")
            else:
                raw = item.rstrip("\r\n")
                parts.append(raw + "\r\n")
        return "".join(parts).encode("utf-16-le")

    def __len__(self) -> int:
        return len(self.strings)

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_starfield_txt(path: Union[str, Path]) -> bool:
        """Return True if *path* looks like a Starfield interface TXT file."""
        path = Path(path)
        if path.suffix.lower() != ".txt":
            return False
        try:
            with open(path, "rb") as fh:
                header = fh.read(4)
            # UTF-16 LE BOM = FF FE; UTF-16 BE BOM = FE FF
            if header[:2] in (b"\xff\xfe", b"\xfe\xff"):
                enc = "utf-16"
            else:
                enc = "utf-8"
            with open(path, "r", encoding=enc, errors="replace") as fh:
                for line in fh:
                    line = line.lstrip("﻿").strip()
                    if not line:
                        continue
                    return line.startswith("$") and "\t" in line
        except Exception:
            pass
        return False
