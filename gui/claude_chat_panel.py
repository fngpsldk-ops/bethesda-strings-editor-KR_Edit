"""
Claude AI Assistant chat panel.

A dockable panel that lets the user:
  - Chat with Claude about the current string / translation
  - Ask Claude to review the active translation (quality review)
  - Apply Claude's suggested translation directly to the table

The panel automatically populates context when the user selects a string in
the main table so Claude always has the relevant source/translation in view.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# HTML replacement for ```…``` code-fenced blocks in Claude's replies (used by
# both _on_reply() and _append_claude()). `white-space: pre-wrap` keeps <pre>'s
# whitespace/line-break preservation while ALSO wrapping long lines to the
# widget's width — plain <pre> defaults to `white-space: pre`, which never
# wraps, so a long suggested translation just ran off the right edge and
# required horizontal scrolling instead of wrapping like the rest of the
# panel (confirmed: this is exactly what the code-block content did, while
# plain chat text elsewhere in the same QTextEdit wrapped normally).
# `overflow-wrap: break-word` additionally breaks a single unbroken run (e.g.
# a long ID/URL with no spaces) that's still wider than the widget.
_CODE_BLOCK_HTML = (
    r'<pre style="background:rgba(30,41,59,0.8);border-radius:4px;padding:6px;'
    r'margin:4px 0;color:#a7f3d0;white-space:pre-wrap;overflow-wrap:break-word;">'
    r'\1</pre>'
)


# ── Background chat worker ────────────────────────────────────────────────────

class _ChatWorker(QThread):
    """Calls Claude in a background thread, streaming tokens to the UI."""

    token_ready  = Signal(str)   # incremental text delta
    reply_ready  = Signal(str)   # full reply (for history storage)
    error_signal = Signal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        messages: List[Dict],
        system: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.api_key  = api_key
        self.model    = model
        self.messages = messages
        self.system   = system

    def run(self) -> None:
        try:
            from gui.claude_client import ClaudeClient
            client = ClaudeClient(self.api_key, self.model)
            parts: List[str] = []
            for chunk in client.chat_stream(self.messages, system=self.system):
                parts.append(chunk)
                self.token_ready.emit(chunk)
            self.reply_ready.emit("".join(parts))
        except Exception as exc:
            self.error_signal.emit(str(exc))


class _ReviewWorker(QThread):
    """Calls Claude's review endpoint in a background thread."""

    review_ready = Signal(str)
    error_signal = Signal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        original: str,
        translation: str,
        source_lang: str,
        target_lang: str,
        character_context: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.api_key     = api_key
        self.model       = model
        self.original    = original
        self.translation = translation
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.character_context = character_context

    def run(self) -> None:
        try:
            from gui.claude_client import ClaudeClient
            client = ClaudeClient(self.api_key, self.model)
            review = client.review_translation(
                self.original, self.translation, self.source_lang, self.target_lang,
                character_context=self.character_context,
            )
            self.review_ready.emit(review)
        except Exception as exc:
            self.error_signal.emit(str(exc))


# ── Main panel ────────────────────────────────────────────────────────────────

class ClaudeChatPanel(QDockWidget):
    """
    Dockable Claude AI Assistant panel.

    Signals
    -------
    apply_translation(str)
        Emitted when the user clicks "Use as Translation".
        The string argument is the text Claude suggested.
    """

    apply_translation = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ClaudeChatPanel")
        self.setWindowTitle(self.tr("Claude AI Assistant"))
        self.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable,
        )

        # State
        self._api_key:   str       = ""
        self._model:     str       = "claude-haiku-4-5"
        self._source_lang: str     = "ru"
        self._target_lang: str     = "uk"
        self._history:  List[Dict] = []   # [{"role": …, "content": …}]
        self._current_original:    str = ""
        self._current_translation: str = ""
        self._worker:   Optional[_ChatWorker]   = None
        self._reviewer: Optional[_ReviewWorker] = None
        # Raw (pre-HTML-formatting) text of the most recent Claude reply —
        # see _on_reply()/_on_review_done() for why _do_apply() must read
        # from this instead of the rendered chat_view.
        self._last_reply_raw: str = ""
        # Character/speaker voice context for the currently selected string
        # (name + formality + custom instructions), if a profile is assigned.
        # Threaded into both the review and chat/suggest system prompts so
        # Claude checks/preserves the established speaker tone instead of
        # being blind to who's talking. Set by MainWindow via set_current_string().
        self._character_context: str = ""

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("ClaudeChatRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # ── API key + model bar ────────────────────────────────────────────────
        key_row = QHBoxLayout()
        key_row.setSpacing(4)

        key_row.addWidget(QLabel(self.tr("Key:")))
        self._edit_key = QLineEdit()
        self._edit_key.setEchoMode(QLineEdit.Password)
        self._edit_key.setPlaceholderText(self.tr("Anthropic API key (sk-ant-…)"))
        self._edit_key.setToolTip(
            self.tr("Your Anthropic API key.  Find it at console.anthropic.com")
        )
        self._edit_key.textChanged.connect(self._on_key_changed)
        key_row.addWidget(self._edit_key, stretch=1)

        self._combo_model = QComboBox()
        from gui.claude_client import CLAUDE_MODELS
        for model_id, label in CLAUDE_MODELS.items():
            self._combo_model.addItem(label, model_id)
        self._combo_model.currentIndexChanged.connect(self._on_model_changed)
        key_row.addWidget(self._combo_model)

        layout.addLayout(key_row)

        # ── Context strip (current string) ─────────────────────────────────────
        self._context_frame = QFrame()
        self._context_frame.setFrameShape(QFrame.StyledPanel)
        self._context_frame.setStyleSheet(
            "QFrame { background: rgba(30,41,59,0.6); border-radius: 4px; }"
        )
        ctx_layout = QVBoxLayout(self._context_frame)
        ctx_layout.setContentsMargins(6, 4, 6, 4)
        ctx_layout.setSpacing(2)

        self._lbl_context_title = QLabel(self.tr("No string selected"))
        self._lbl_context_title.setStyleSheet("font-weight: bold; font-size: 11px;")
        ctx_layout.addWidget(self._lbl_context_title)

        self._lbl_original = QLabel()
        self._lbl_original.setWordWrap(True)
        self._lbl_original.setStyleSheet("color: #94a3b8; font-size: 11px;")
        ctx_layout.addWidget(self._lbl_original)

        self._lbl_translation = QLabel()
        self._lbl_translation.setWordWrap(True)
        self._lbl_translation.setStyleSheet("color: #7dd3fc; font-size: 11px;")
        ctx_layout.addWidget(self._lbl_translation)

        layout.addWidget(self._context_frame)

        # ── Chat history ───────────────────────────────────────────────────────
        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        self._chat_view.setObjectName("ClaudeChatView")
        self._chat_view.document().setDefaultStyleSheet(
            """
            .user    { color: #7dd3fc; margin-bottom: 4px; }
            .claude  { color: #d1fae5; margin-bottom: 4px; }
            .system  { color: #94a3b8; font-style: italic; margin-bottom: 2px; }
            b        { font-weight: 600; }
            """
        )
        self._chat_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._chat_view, stretch=1)

        # ── Quick-action buttons ───────────────────────────────────────────────
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)

        self._btn_review = QPushButton(self.tr("Review Translation"))
        self._btn_review.setToolTip(
            self.tr("Ask Claude to review the current translation for quality issues")
        )
        self._btn_review.clicked.connect(self._do_review)
        quick_row.addWidget(self._btn_review)

        self._btn_suggest = QPushButton(self.tr("Suggest Translation"))
        self._btn_suggest.setToolTip(
            self.tr("Ask Claude to translate the current source string")
        )
        self._btn_suggest.clicked.connect(self._do_suggest)
        quick_row.addWidget(self._btn_suggest)

        self._btn_apply = QPushButton(self.tr("Use as Translation"))
        self._btn_apply.setToolTip(
            self.tr(
                "Apply Claude's last suggested translation to the selected table row.\n"
                "The suggestion is the last code block or plain text in the chat."
            )
        )
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._do_apply)
        quick_row.addWidget(self._btn_apply)

        layout.addLayout(quick_row)

        # ── Input area ─────────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(4)

        self._input = QPlainTextEdit()
        self._input.setMaximumHeight(72)
        self._input.setPlaceholderText(
            self.tr(
                "Ask Claude about this string… (Ctrl+Enter to send)"
            )
        )
        self._input.installEventFilter(self)
        input_row.addWidget(self._input, stretch=1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(2)

        self._btn_send = QPushButton(self.tr("Send"))
        self._btn_send.setFixedWidth(70)
        self._btn_send.clicked.connect(self._do_send)
        btn_col.addWidget(self._btn_send)

        self._btn_clear = QPushButton(self.tr("Clear"))
        self._btn_clear.setFixedWidth(70)
        self._btn_clear.setToolTip(self.tr("Clear conversation history"))
        self._btn_clear.clicked.connect(self._do_clear)
        btn_col.addWidget(self._btn_clear)

        input_row.addLayout(btn_col)
        layout.addLayout(input_row)

        # Loading indicator
        self._lbl_thinking = QLabel(self.tr("Claude is thinking…"))
        self._lbl_thinking.setStyleSheet("color: #94a3b8; font-style: italic;")
        self._lbl_thinking.setVisible(False)
        layout.addWidget(self._lbl_thinking)

        self.setWidget(root)

        # Load persisted API key
        from gui.claude_client import get_api_key
        key = get_api_key()
        if key:
            self._api_key = key
            self._edit_key.setText(key)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_current_string(
        self,
        string_id: int,
        original: str,
        translation: str,
        source_lang: str = "ru",
        target_lang: str = "uk",
        character_context: str = "",
    ) -> None:
        """Called by MainWindow when the user selects a table row."""
        switched_string = getattr(self, "_current_string_id", None) != string_id
        self._current_string_id   = string_id
        self._current_original    = original
        self._current_translation = translation
        self._source_lang         = source_lang
        self._target_lang         = target_lang
        self._character_context   = character_context

        if switched_string:
            # A pending suggestion belongs to the PREVIOUS string. Leaving it
            # applicable here risks silently writing one string's suggested
            # text into a different, currently-selected row if Apply is
            # clicked after switching rows without a new Review/Suggest.
            self._last_reply_raw = ""
            self._btn_apply.setEnabled(False)

        self._lbl_context_title.setText(
            self.tr("String 0x{sid:08X}").format(sid=string_id)
        )
        snip = 120
        self._lbl_original.setText(
            original[:snip] + ("…" if len(original) > snip else "")
        )
        self._lbl_translation.setText(
            (translation[:snip] + ("…" if len(translation) > snip else ""))
            if translation else self.tr("<no translation yet>")
        )

    def set_api_key(self, key: str) -> None:
        """Programmatically set the API key (e.g. from settings dialog)."""
        self._api_key = key.strip()
        self._edit_key.setText(self._api_key)

    def set_model(self, model_id: str) -> None:
        """Programmatically select a Claude model."""
        for i in range(self._combo_model.count()):
            if self._combo_model.itemData(i) == model_id:
                self._combo_model.setCurrentIndex(i)
                break
        self._model = model_id

    # ── Key / model slots ─────────────────────────────────────────────────────

    @Slot(str)
    def _on_key_changed(self, text: str) -> None:
        self._api_key = text.strip()
        from gui.claude_client import set_api_key
        if self._api_key:
            set_api_key(self._api_key)

    @Slot(int)
    def _on_model_changed(self, _idx: int) -> None:
        self._model = self._combo_model.currentData()

    # ── Chat / review actions ─────────────────────────────────────────────────

    def _check_ready(self) -> bool:
        """Return True if API key is set, show a warning otherwise."""
        if not self._api_key:
            QMessageBox.warning(
                self,
                self.tr("API Key Required"),
                self.tr(
                    "Please enter your Anthropic API key in the field above.\n"
                    "You can get one at console.anthropic.com"
                ),
            )
            return False
        return True

    def _system_prompt(self) -> str:
        from gui.ollama_worker import _LANG_DISPLAY  # type: ignore[attr-defined]
        src = _LANG_DISPLAY.get(self._source_lang, self._source_lang.upper())
        tgt = _LANG_DISPLAY.get(self._target_lang, self._target_lang.upper())
        prompt = (
            f"You are a Bethesda Starfield game localization assistant "
            f"helping with {src} → {tgt} translation. "
            f"Write your own commentary/explanations in Korean (한국어) — that's "
            f"the language the person you're helping works in. The suggested "
            f"translation itself, inside the code block, stays in {tgt} as normal. "
            f"You have access to the current string being worked on (shown in each user turn). "
            f"Be concise and practical. When suggesting a translation, wrap it in a code block: "
            f"```\n<translation here>\n```\n"
            f"When choosing register/formality (반말 vs 존댓말 for a Korean target, "
            f"tu/vous, du/Sie, etc. otherwise): infer it from who's speaking to whom "
            f"and in what relationship/tone in the SOURCE text, don't just copy "
            f"whatever register an existing translation happens to already use — "
            f"it may just be an unexamined default rather than a deliberate fit."
        )
        if self._character_context:
            prompt += (
                f"\n\nThe current string is spoken by a character with an "
                f"established voice — this takes priority over inferring register "
                f"from the source text above, since it's explicit and authoritative. "
                f"Match it in any translation you suggest:\n"
                f"{self._character_context}"
            )
        return prompt

    @Slot()
    def _do_review(self) -> None:
        if not self._check_ready():
            return
        if not self._current_original:
            self._append_system("Select a string in the table first.")
            return

        self._set_busy(True)
        self._reviewer = _ReviewWorker(
            api_key=self._api_key,
            model=self._model,
            original=self._current_original,
            translation=self._current_translation,
            source_lang=self._source_lang,
            target_lang=self._target_lang,
            character_context=self._character_context,
            parent=self,
        )
        self._reviewer.review_ready.connect(self._on_review_done)
        self._reviewer.error_signal.connect(self._on_error)
        self._reviewer.finished.connect(lambda: self._set_busy(False))
        self._reviewer.start()

    @Slot()
    def _do_suggest(self) -> None:
        if not self._check_ready():
            return
        if not self._current_original:
            self._append_system("Select a string in the table first.")
            return

        msg = (
            f"Please translate this game string:\n\n"
            f"Source: {self._current_original}"
        )
        if self._current_translation:
            msg += f"\n\nExisting translation (may need improvement): {self._current_translation}"
        self._send_message(msg)

    @staticmethod
    def _extract_code_blocks_with_labels(text: str) -> list:
        """Return [(label, code), ...] for every ```code``` block in *text*.

        *label* is the last non-empty line immediately preceding that block
        (e.g. "또는 더 간결하게:" for a second, more-concise alternative) —
        this is exactly the phrasing Claude itself uses to distinguish
        multiple options it offers, so reusing it as the picker label needs
        no extra prompt engineering. Falls back to "옵션 N" when there's no
        usable preceding text (e.g. the block is the very first thing in the
        reply, or two blocks appear back-to-back).
        """
        import re
        pattern = re.compile(r"```\n?(.*?)\n?```", re.DOTALL)
        blocks = []
        last_end = 0
        for i, m in enumerate(pattern.finditer(text), start=1):
            preceding = text[last_end:m.start()]
            label = ""
            for line in reversed(preceding.strip("\n").splitlines()):
                line = line.strip().strip(":").strip()
                line = line.lstrip("#").strip()          # markdown headers (##, ###)
                line = line.replace("**", "").strip()     # markdown bold markers
                if line:
                    label = line
                    break
            if not label:
                label = f"옵션 {i}"
            blocks.append((label, m.group(1).strip()))
            last_end = m.end()
        return blocks

    def _pick_suggestion(self, blocks: list) -> Optional[str]:
        """Show a picker when *blocks* has more than one (label, code) pair;
        return the chosen code, or None if the person cancels. Returns the
        single block directly, with no dialog, when there's only one —
        the common case stays exactly as fast as before this fix."""
        if len(blocks) == 1:
            return blocks[0][1]

        dlg = QDialog(self)
        dlg.setWindowTitle(self.tr("적용할 번역 선택"))
        dlg.resize(520, 360)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(self.tr(
            "Claude가 여러 안을 제시했습니다. 적용할 것을 선택하세요:"
        )))

        list_widget = QListWidget()
        for label, code in blocks:
            preview = code if len(code) <= 160 else code[:160] + "…"
            item = QListWidgetItem(f"{label}\n{preview}")
            list_widget.addItem(item)
        list_widget.setCurrentRow(0)
        list_widget.setWordWrap(True)
        layout.addWidget(list_widget, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        list_widget.itemDoubleClicked.connect(lambda _item: dlg.accept())
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.Accepted:
            return None
        idx = list_widget.currentRow()
        if idx < 0:
            return None
        return blocks[idx][1]

    @Slot()
    def _do_apply(self) -> None:
        """Extract code block(s) from Claude's last raw reply and emit
        apply_translation. Reads self._last_reply_raw (set by _on_reply /
        _on_review_done) rather than re-parsing the rendered chat_view —
        the HTML formatting step replaces ```…``` fences with <pre> tags,
        so scraping toPlainText() afterward never finds them.

        When Claude's reply contains MULTIPLE code blocks (e.g. a primary
        suggestion plus a "또는 더 간결하게:" alternative), this used to
        silently apply whichever one happened to come last — no way to tell
        which was actually wanted. Now: one block applies directly as
        before; two or more show a picker so the choice is explicit.
        """
        raw = self._last_reply_raw
        if not raw:
            QMessageBox.information(
                self,
                self.tr("No suggestion found"),
                self.tr(
                    "No code block found in the last reply.\n"
                    "Ask Claude to suggest a translation first."
                ),
            )
            return
        blocks = self._extract_code_blocks_with_labels(raw)
        if not blocks:
            QMessageBox.information(
                self,
                self.tr("No suggestion found"),
                self.tr(
                    "No code block found in the last reply.\n"
                    "Ask Claude to suggest a translation first."
                ),
            )
            return
        suggestion = self._pick_suggestion(blocks)
        if suggestion is None:
            return  # cancelled the picker
        self.apply_translation.emit(suggestion)
        self._append_system(f"Applied: {suggestion[:80]}…" if len(suggestion) > 80 else f"Applied: {suggestion}")

    @Slot()
    def _do_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        if not self._check_ready():
            return
        self._input.clear()
        self._send_message(text)

    @Slot()
    def _do_clear(self) -> None:
        self._history.clear()
        self._chat_view.clear()
        self._last_reply_raw = ""
        self._btn_apply.setEnabled(False)
        self._append_system("Conversation cleared.")

    def _send_message(self, user_text: str) -> None:
        # Add current context as a preamble so Claude knows what string we're on
        context_note = ""
        if self._current_original:
            from gui.ollama_worker import _LANG_DISPLAY  # type: ignore[attr-defined]
            src = _LANG_DISPLAY.get(self._source_lang, self._source_lang.upper())
            tgt = _LANG_DISPLAY.get(self._target_lang, self._target_lang.upper())
            context_note = (
                f"[Current string — Source ({src}): {self._current_original[:200]}"
            )
            if self._current_translation:
                context_note += f" | Current translation ({tgt}): {self._current_translation[:200]}"
            context_note += "]\n\n"

        full_text = context_note + user_text
        self._history.append({"role": "user", "content": full_text})
        self._append_user(user_text)

        self._set_busy(True)
        self._worker = _ChatWorker(
            api_key=self._api_key,
            model=self._model,
            messages=list(self._history),
            system=self._system_prompt(),
            parent=self,
        )
        # Prepare the streaming block before the worker starts
        self._begin_claude_stream()
        self._worker.token_ready.connect(self._on_token)
        self._worker.reply_ready.connect(self._on_reply)
        self._worker.error_signal.connect(self._on_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    # ── Worker result slots ───────────────────────────────────────────────────

    def _begin_claude_stream(self) -> None:
        """Insert the 'Claude:' header and record the cursor position for token insertion."""
        cursor = self._chat_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._chat_view.setTextCursor(cursor)
        self._chat_view.insertHtml('<p class="claude"><b>Claude:</b><br>')
        self._stream_start = self._chat_view.textCursor().position()
        self._stream_parts: list = []

    @Slot(str)
    def _on_token(self, chunk: str) -> None:
        """Append a streaming token at the tracked cursor position."""
        self._stream_parts.append(chunk)
        cursor = self._chat_view.textCursor()
        cursor.setPosition(self._stream_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText("".join(self._stream_parts))
        self._scroll_bottom()

    @Slot(str)
    def _on_reply(self, text: str) -> None:
        """Replace raw streamed text with nicely formatted HTML."""
        import re
        self._history.append({"role": "assistant", "content": text})
        # Store the RAW (pre-HTML-formatting) reply so _do_apply() can pull a
        # code block from it later. The rendered chat_view can't be re-parsed
        # for this: the formatting step below replaces every ```…``` fence
        # with a <pre> tag, and QTextEdit.toPlainText() on the resulting rich
        # text never contains the backticks again — searching it for ``` (the
        # previous implementation) matches nothing, always, for every message
        # once it finishes streaming. Confirmed by direct reproduction.
        self._last_reply_raw = text

        # Build the formatted content (same logic as _append_claude)
        formatted = re.sub(
            r"```\n?(.*?)\n?```",
            _CODE_BLOCK_HTML,
            self._esc(text),
            flags=re.DOTALL,
        )
        formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", formatted)
        formatted = formatted.replace("\n", "<br>")

        # Overwrite the plain-text stream with formatted HTML
        cursor = self._chat_view.textCursor()
        cursor.setPosition(self._stream_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertHtml(formatted + "</p>")

        self._scroll_bottom()
        self._btn_apply.setEnabled(bool(re.search(r"```", text)))

    @Slot(str)
    def _on_review_done(self, text: str) -> None:
        import re
        # Deliberately NOT appended to self._history. review_translation() is
        # a standalone, single-shot call that never reads _history in the
        # first place, so adding its output there serves no purpose for the
        # review itself — it only pollutes every SUBSEQUENT Chat/Suggest call
        # (_send_message sends the full _history as prior turns). Confirmed
        # real-world consequence: when a review got cut off mid-sentence
        # (see review_translation()'s max_tokens fix), the next "번역 제안"
        # click sent that unfinished assistant turn as conversation history,
        # and Claude did exactly what a truncated turn invites — continued
        # typing the leftover sentence before producing the actual
        # suggestion. Keeping Review and Chat/Suggest as separate, isolated
        # flows (matching how they already use separate system prompts and
        # separate API calls) avoids this class of bug entirely, not just
        # the truncation case that surfaced it.
        self._last_reply_raw = text
        self._append_claude(text, prefix="📋 Translation Review")
        self._btn_apply.setEnabled(bool(re.search(r"```", text)))

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._append_system(f"Error: {msg}")
        logger.error("Claude chat error: %s", msg)

    # ── Chat view helpers ─────────────────────────────────────────────────────

    def _append_user(self, text: str) -> None:
        self._chat_view.append(
            f'<p class="user"><b>You:</b> {self._esc(text)}</p>'
        )
        self._scroll_bottom()

    def _append_claude(self, text: str, prefix: str = "Claude") -> None:
        import re
        # Highlight code blocks
        formatted = re.sub(
            r"```\n?(.*?)\n?```",
            _CODE_BLOCK_HTML,
            self._esc(text),
            flags=re.DOTALL,
        )
        # Basic markdown bold
        formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", formatted)
        # Newlines to <br>
        formatted = formatted.replace("\n", "<br>")
        self._chat_view.append(
            f'<p class="claude"><b>{self._esc(prefix)}:</b><br>{formatted}</p>'
        )
        self._scroll_bottom()

    def _append_system(self, text: str) -> None:
        self._chat_view.append(f'<p class="system">{self._esc(text)}</p>')
        self._scroll_bottom()

    def _scroll_bottom(self) -> None:
        sb = self._chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _esc(text: str) -> str:
        import html
        return html.escape(text)

    def _set_busy(self, busy: bool) -> None:
        self._lbl_thinking.setVisible(busy)
        self._btn_send.setEnabled(not busy)
        self._btn_review.setEnabled(not busy)
        self._btn_suggest.setEnabled(not busy)

    # ── Ctrl+Enter to send ────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            ke: QKeyEvent = event  # type: ignore[assignment]
            if ke.key() == Qt.Key_Return and (ke.modifiers() & Qt.ControlModifier):
                self._do_send()
                return True
        return super().eventFilter(obj, event)
