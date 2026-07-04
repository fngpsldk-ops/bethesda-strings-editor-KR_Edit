"""
Translation Memory viewer dialog — read-only browser + search for whatever
TranslationMemory is currently loaded/attached to the app.

This exists because loading a TM (from a TXT/TMX file, or via the auto-saved
JSON snapshot at startup) previously gave no lasting way to confirm it's
actually there: only a one-time status-bar message at load time, with no
persistent on-screen indicator and no way to browse or search its contents
afterward. Mirrors the Glossary editor's search/table pattern, but read-only
and virtualized (a real TM can have 100k+ entries -- rendering them all into
a QTableWidget at once would be its own performance problem).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from gui.translation_memory import TranslationMemory

# Cap how many filtered rows we ever hand to the view at once. The table
# itself can hold far more, but there's no value in rendering tens of
# thousands of rows for a query that isn't narrowed down yet.
_MAX_DISPLAYED_ROWS = 500


class _TmTableModel(QAbstractTableModel):
    """Lightweight read-only model over a list of (source, translation) pairs."""

    HEADERS = ["Original", "Translated"]

    def __init__(self, rows: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self._rows = rows

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 2

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        return self._rows[index.row()][index.column()]

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class TranslationMemoryViewerDialog(QDialog):
    """Read-only browser for the currently loaded TranslationMemory.

    Shows the total entry count up front (the thing people actually want to
    confirm — "is it really loaded?") plus a search box that filters by
    substring match on either the original or translated text.
    """

    def __init__(self, tm: Optional[TranslationMemory], parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Translation Memory"))
        self.resize(900, 600)
        self._tm = tm

        layout = QVBoxLayout(self)

        self.lbl_summary = QLabel()
        self.lbl_summary.setStyleSheet("font-weight: 600; padding: 4px 0;")
        layout.addWidget(self.lbl_summary)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(self.tr("Search:")))
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText(
            self.tr("Filter by original or translated text…")
        )
        self.edit_search.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.edit_search)
        layout.addLayout(search_row)

        self.table = QTableView()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._model = _TmTableModel([])
        self.table.setModel(self._model)
        layout.addWidget(self.table)

        self.lbl_hint = QLabel()
        self.lbl_hint.setStyleSheet("font-size: 11px; opacity: 0.7;")
        layout.addWidget(self.lbl_hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton(self.tr("Close"))
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._refresh_summary()
        self._apply_filter("")

    # ── internals ────────────────────────────────────────────────────────────

    def _refresh_summary(self) -> None:
        if not self._tm or not self._tm._by_src:
            self.lbl_summary.setText(
                self.tr("No Translation Memory is currently loaded.")
            )
            return
        n_src = len(self._tm._by_src)
        n_id = len(self._tm._by_id)
        self.lbl_summary.setText(
            self.tr(
                "Translation Memory loaded: {src} entries by text"
                " ({ids} also indexed by ID)."
            ).format(src=f"{n_src:,}", ids=f"{n_id:,}")
        )

    def _on_search_changed(self, text: str) -> None:
        self._apply_filter(text)

    def _apply_filter(self, query: str) -> None:
        if not self._tm or not self._tm._by_src:
            self._model.set_rows([])
            self.lbl_hint.setText("")
            return

        query = query.strip().lower()
        rows: list[tuple[str, str]] = []
        total_matches = 0
        for src, tgt in self._tm._by_src.items():
            if not query or query in src.lower() or query in tgt.lower():
                total_matches += 1
                if len(rows) < _MAX_DISPLAYED_ROWS:
                    rows.append((src, tgt))

        self._model.set_rows(rows)
        if total_matches > _MAX_DISPLAYED_ROWS:
            self.lbl_hint.setText(
                self.tr(
                    "Showing first {shown} of {total:,} matches — "
                    "narrow your search to see more specific results."
                ).format(shown=_MAX_DISPLAYED_ROWS, total=total_matches)
            )
        elif query:
            self.lbl_hint.setText(
                self.tr("{n} match(es).").format(n=total_matches)
            )
        else:
            self.lbl_hint.setText(
                self.tr(
                    "Showing first {shown} of {total:,} entries — "
                    "type in the search box to filter."
                ).format(shown=len(rows), total=total_matches)
            )
