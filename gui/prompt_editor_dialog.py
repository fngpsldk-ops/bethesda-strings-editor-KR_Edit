"""
BSEK Prompt Editor dialog.

Lets the user edit the translation system prompt's persona (identity/role
sentence) and additional style rules directly in the GUI, save/load named
presets, and preview the exact prompt that will be sent to the model —
without touching source code.

Design intent (see gui/prompt_presets.py and gui/ollama_worker.py for the
underlying logic this dialog is a thin UI layer over):

- Only the "flavor" of the prompt is editable here (identity + style rules).
  Safety-critical instructions (game tag preservation, glossary enforcement,
  bracket-token handling) live in TranslationRequest.to_system_prompt() and
  are NOT exposed for editing, so a bad edit here cannot break string files.
- "Apply" takes effect immediately (live translations use it right away) and
  is persisted to disk right away. "Cancel" only discards *unapplied* text
  box edits — it does not undo a prior Apply in the same session.
- The preset combo box is a *loader*, not a live indicator: selecting a
  preset copies its text into the editor for further editing; it does not
  apply anything until Apply/OK is clicked. The combo DOES remember which
  preset (if any) was last applied, so reopening the dialog shows the right
  selection instead of always resetting to "BSEK 기본값".
"""
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QPushButton, QDialogButtonBox, QGroupBox, QLabel,
    QTextEdit, QMessageBox, QInputDialog, QWidget,
)
from PySide6.QtCore import Qt, Signal, QTimer

from gui.app_settings import AppSettings, save_settings
from gui.prompt_presets import (
    list_preset_names, get_preset, save_preset, delete_preset, rename_preset,
    PresetNameError, BUILTIN_DEFAULT_LABEL,
)

logger = logging.getLogger(__name__)

_SAMPLE_SOURCE_TEXT = (
    "Attempt to undetectably steal any available fuel from a docked vessel."
)

# Debounce interval for live preview refresh while typing.
_PREVIEW_REFRESH_DELAY_MS = 400


class NoOverwriteTextEdit(QTextEdit):
    """QTextEdit that ignores the Insert key.

    Qt's default QTextEdit toggles overwrite mode when the user presses
    Insert — a key that sits right next to Delete/Home on many keyboards and
    is easy to hit by accident. Once toggled, every further keystroke
    silently *replaces* existing characters instead of inserting new ones,
    which looks like the editor is "eating" or overwriting text starting
    wherever the cursor happens to be. Prompt text is precious enough (and
    the failure mode confusing enough) that we simply disable the toggle
    entirely rather than rely on users noticing and pressing Insert again.
    """

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.key() == Qt.Key.Key_Insert:
            event.accept()  # swallow — never toggle overwrite mode
            return
        super().keyPressEvent(event)


class PromptEditorDialog(QDialog):
    """Edit the translation prompt's persona/custom rules and manage presets."""

    #: Emitted whenever Apply or OK commits a change (persona/rules already
    #: written into the shared AppSettings object and applied live via
    #: set_prompt_overrides() by the time this fires). Callers typically use
    #: this only for status-bar feedback; persistence is handled internally.
    applied = Signal()

    def __init__(self, settings: AppSettings, parent=None, theme_manager=None):
        super().__init__(parent)
        self._settings = settings
        self._theme_manager = theme_manager
        self._hint_labels: list = []

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_REFRESH_DELAY_MS)
        self._preview_timer.timeout.connect(self._refresh_preview_if_visible)

        self.setWindowTitle(self.tr("Prompt Editor"))
        self.setMinimumSize(640, 620)
        self._setup_ui()
        self._load_from_settings()

    # ── theming helper (mirrors SettingsDialog's approach) ──────────────────────
    def _hint_color(self) -> str:
        if self._theme_manager is not None:
            try:
                return self._theme_manager.get_hint_color(self._theme_manager.current_theme)
            except Exception:
                pass
        return "#888888"

    def _register_hint_label(self, label: QLabel, extra_style: str = "") -> None:
        label.setProperty("_hint_extra_style", extra_style)
        self._hint_labels.append(label)
        label.setStyleSheet(f"color: {self._hint_color()}; {extra_style}")

    # ── UI construction ───────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(self.tr(
            "번역 프롬프트의 정체성(페르소나)과 스타일 규칙을 직접 편집할 수 있습니다.\n"
            "게임 태그 보존, 용어집 강제 등 안전 관련 규칙은 여기서 편집되지 않으며\n"
            "항상 자동으로 적용됩니다."
        ))
        self._register_hint_label(intro, "font-size: 11px;")
        layout.addWidget(intro)

        # ── Preset row ───────────────────────────────────────────────────────
        preset_group = QGroupBox(self.tr("Preset"))
        preset_row = QHBoxLayout()
        self.combo_preset = QComboBox()
        self.combo_preset.setEditable(False)
        self.combo_preset.currentTextChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self.combo_preset, 1)

        self.btn_save = QPushButton(self.tr("Save"))
        self.btn_save.setToolTip(self.tr(
            "현재 선택된 프리셋을 지금 편집 중인 내용으로 덮어씁니다."
        ))
        self.btn_save.clicked.connect(self._on_save)
        preset_row.addWidget(self.btn_save)

        self.btn_save_as = QPushButton(self.tr("Save As…"))
        self.btn_save_as.clicked.connect(self._on_save_as)
        preset_row.addWidget(self.btn_save_as)

        self.btn_rename = QPushButton(self.tr("Rename…"))
        self.btn_rename.clicked.connect(self._on_rename_preset)
        preset_row.addWidget(self.btn_rename)

        self.btn_delete = QPushButton(self.tr("Delete"))
        self.btn_delete.clicked.connect(self._on_delete_preset)
        preset_row.addWidget(self.btn_delete)

        preset_group.setLayout(preset_row)
        layout.addWidget(preset_group)

        # ── Persona ──────────────────────────────────────────────────────────
        persona_group = QGroupBox(self.tr("Persona (정체성/역할)"))
        persona_layout = QVBoxLayout()
        self.persona_edit = NoOverwriteTextEdit()
        self.persona_edit.setPlaceholderText(
            "예: 당신은 전문 Starfield 게임 로컬라이제이션 번역가입니다."
        )
        self.persona_edit.setMaximumHeight(70)
        self.persona_edit.textChanged.connect(self._on_text_changed)
        persona_layout.addWidget(self.persona_edit)
        persona_hint = QLabel(self.tr("비워두면 BSEK 기본 페르소나를 사용합니다."))
        self._register_hint_label(persona_hint, "font-size: 11px; font-style: italic;")
        persona_layout.addWidget(persona_hint)
        persona_group.setLayout(persona_layout)
        layout.addWidget(persona_group)

        # ── Custom rules ─────────────────────────────────────────────────────
        rules_group = QGroupBox(self.tr("Additional Rules (추가 규칙)"))
        rules_layout = QVBoxLayout()
        self.rules_edit = NoOverwriteTextEdit()
        self.rules_edit.setPlaceholderText(
            "예: 10. 현대 항공 무전 규칙을 따라 번역하세요.\n"
            "11. 인물 대사는 맥락에 따라 반말/존댓말을 판단하세요."
        )
        self.rules_edit.textChanged.connect(self._on_text_changed)
        rules_layout.addWidget(self.rules_edit)
        rules_hint = QLabel(self.tr(
            "비워두면 BSEK 기본 규칙(퀘스트 명령형 어투, 반말/존댓말 가이드)을 사용합니다.\n"
            "번호는 자유롭게 매기되, 안전 규칙(1~9번)과 겹치지 않게 10번부터 시작을 권장합니다."
        ))
        self._register_hint_label(rules_hint, "font-size: 11px; font-style: italic;")
        rules_layout.addWidget(rules_hint)
        rules_group.setLayout(rules_layout)
        layout.addWidget(rules_group, 1)

        # ── Reset + Preview row ──────────────────────────────────────────────
        tools_row = QHBoxLayout()
        self.btn_reset_default = QPushButton(self.tr("Reset to BSEK Default"))
        self.btn_reset_default.clicked.connect(self._on_reset_default)
        tools_row.addWidget(self.btn_reset_default)
        tools_row.addStretch(1)
        self.btn_preview = QPushButton(self.tr("Preview Full Prompt"))
        self.btn_preview.clicked.connect(self._on_preview)
        tools_row.addWidget(self.btn_preview)
        layout.addLayout(tools_row)

        # ── Preview box (hidden until first use) ────────────────────────────
        self.preview_box = QTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setVisible(False)
        self.preview_box.setStyleSheet("font-family: monospace; font-size: 11px;")
        self.preview_box.setMaximumHeight(180)
        layout.addWidget(self.preview_box)

        preview_hint = QLabel(self.tr(
            "미리보기가 열려 있으면 편집 중 자동으로 갱신됩니다."
        ))
        self._register_hint_label(preview_hint, "font-size: 10px; font-style: italic;")
        self._preview_hint_label = preview_hint
        preview_hint.setVisible(False)
        layout.addWidget(preview_hint)

        # ── Apply-semantics note ────────────────────────────────────────────
        apply_note = QLabel(self.tr(
            "Apply/OK: 즉시 번역에 반영되고 저장됩니다.  Cancel: 저장되지 않은 편집만 취소합니다."
        ))
        self._register_hint_label(apply_note, "font-size: 10px; font-style: italic;")
        layout.addWidget(apply_note)

        # ── OK / Cancel / Apply ──────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn is not None:
            apply_btn.clicked.connect(self._do_apply)
        layout.addWidget(buttons)

    # ── data loading ──────────────────────────────────────────────────────────
    def _load_from_settings(self) -> None:
        """Populate the editor with the currently active persona/rules and
        refresh the preset dropdown. Called once at dialog open."""
        self.persona_edit.blockSignals(True)
        self.rules_edit.blockSignals(True)
        self.persona_edit.setPlainText(getattr(self._settings, "prompt_persona", "") or "")
        self.rules_edit.setPlainText(getattr(self._settings, "prompt_custom_rules", "") or "")
        self.persona_edit.blockSignals(False)
        self.rules_edit.blockSignals(False)
        # Fix #1: reopen with whichever preset was last applied selected,
        # instead of always resetting to "BSEK 기본값".
        active = getattr(self._settings, "prompt_active_preset", "") or BUILTIN_DEFAULT_LABEL
        self._refresh_preset_combo(select=active)

    def _refresh_preset_combo(self, select: str = BUILTIN_DEFAULT_LABEL) -> None:
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        self.combo_preset.addItem(BUILTIN_DEFAULT_LABEL)
        self.combo_preset.addItems(list_preset_names(self._settings))
        idx = self.combo_preset.findText(select)
        self.combo_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_preset.blockSignals(False)
        self._update_preset_buttons_enabled()

    def _update_preset_buttons_enabled(self) -> None:
        is_real_preset = self.combo_preset.currentText() != BUILTIN_DEFAULT_LABEL
        self.btn_save.setEnabled(is_real_preset)
        self.btn_rename.setEnabled(is_real_preset)
        self.btn_delete.setEnabled(is_real_preset)

    # ── preset actions ───────────────────────────────────────────────────────
    def _on_preset_selected(self, name: str) -> None:
        """Load the selected preset's text into the editor (does not apply it).

        Selecting "BSEK 기본값" clears the editor back to empty (= use BSEK
        defaults) — it must NOT leave whatever text was typed for the
        previously selected preset sitting in the boxes.
        """
        self._update_preset_buttons_enabled()
        if not name or name == BUILTIN_DEFAULT_LABEL:
            self.persona_edit.setPlainText("")
            self.rules_edit.setPlainText("")
            return
        entry = get_preset(self._settings, name)
        if entry is not None:
            self.persona_edit.setPlainText(entry["persona"])
            self.rules_edit.setPlainText(entry["custom_rules"])

    def _on_save(self) -> None:
        """Fix #2: overwrite the currently selected preset with the editor's
        current text, without prompting for a name (unlike Save As…)."""
        name = self.combo_preset.currentText()
        if name == BUILTIN_DEFAULT_LABEL:
            return
        try:
            save_preset(
                self._settings, name,
                self.persona_edit.toPlainText(), self.rules_edit.toPlainText(),
            )
        except PresetNameError as e:
            QMessageBox.warning(self, self.tr("Invalid Name"), str(e))
            return
        save_settings(self._settings)

    def _on_save_as(self) -> None:
        name, ok = QInputDialog.getText(
            self, self.tr("Save Preset"), self.tr("Preset name:")
        )
        if not ok:
            return
        try:
            saved_name = save_preset(
                self._settings, name,
                self.persona_edit.toPlainText(), self.rules_edit.toPlainText(),
            )
        except PresetNameError as e:
            QMessageBox.warning(self, self.tr("Invalid Name"), str(e))
            return
        save_settings(self._settings)
        self._refresh_preset_combo(select=saved_name)

    def _on_rename_preset(self) -> None:
        old_name = self.combo_preset.currentText()
        if old_name == BUILTIN_DEFAULT_LABEL:
            return
        new_name, ok = QInputDialog.getText(
            self, self.tr("Rename Preset"), self.tr("New name:"), text=old_name
        )
        if not ok:
            return
        try:
            renamed = rename_preset(self._settings, old_name, new_name)
        except PresetNameError as e:
            QMessageBox.warning(self, self.tr("Invalid Name"), str(e))
            return
        except KeyError:
            return
        save_settings(self._settings)
        self._refresh_preset_combo(select=renamed)

    def _on_delete_preset(self) -> None:
        name = self.combo_preset.currentText()
        if name == BUILTIN_DEFAULT_LABEL:
            return
        reply = QMessageBox.question(
            self, self.tr("Delete Preset"),
            self.tr("Delete preset '{name}'?").format(name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_preset(self._settings, name)
        save_settings(self._settings)
        self._refresh_preset_combo()

    # ── reset / preview ──────────────────────────────────────────────────────
    def _on_reset_default(self) -> None:
        self.persona_edit.setPlainText("")
        self.rules_edit.setPlainText("")
        self.combo_preset.setCurrentIndex(0)  # BUILTIN_DEFAULT_LABEL

    def _on_text_changed(self) -> None:
        """Fix #3: debounce a live preview refresh while the user types,
        but only if the preview panel is already visible (never force it
        open just because the user is typing)."""
        if self.preview_box.isVisible():
            self._preview_timer.start()

    def _build_preview_text(self) -> str:
        """Build the exact system prompt using whatever is currently typed
        in the editor (whether or not it has been applied yet). Has no side
        effects on the live translation state — the module-level active
        override is restored immediately afterward."""
        from gui.ollama_worker import (
            TranslationRequest, get_prompt_overrides, set_prompt_overrides,
        )
        prev_persona, prev_rules = get_prompt_overrides()
        try:
            set_prompt_overrides(
                self.persona_edit.toPlainText(), self.rules_edit.toPlainText()
            )
            sample_req = TranslationRequest(
                index=0,
                original_text=_SAMPLE_SOURCE_TEXT,
                string_id=0,
                source_lang=getattr(self._settings, "default_source_lang", "en") or "en",
                target_lang=getattr(self._settings, "default_target_lang", "ko") or "ko",
            )
            return sample_req.to_system_prompt()
        except Exception as exc:
            logger.error("Prompt preview failed: %s", exc)
            return self.tr("[Preview failed: {err}]").format(err=exc)
        finally:
            set_prompt_overrides(prev_persona, prev_rules)  # never leaks into live state

    def _on_preview(self) -> None:
        """Show the preview panel and populate it (Fix #3: subsequent edits
        auto-refresh it via _on_text_changed, no need to click again)."""
        self.preview_box.setPlainText(self._build_preview_text())
        self.preview_box.setVisible(True)
        self._preview_hint_label.setVisible(True)

    def _refresh_preview_if_visible(self) -> None:
        if self.preview_box.isVisible():
            self.preview_box.setPlainText(self._build_preview_text())

    # ── apply / accept / reject ──────────────────────────────────────────────
    def _do_apply(self) -> None:
        """Write the editor's current text into settings, apply it live to
        the translation prompt, and persist to disk immediately."""
        from gui.ollama_worker import set_prompt_overrides

        self._settings.prompt_persona = self.persona_edit.toPlainText().strip()
        self._settings.prompt_custom_rules = self.rules_edit.toPlainText().strip()
        # Fix #1: remember which preset (if any) is now active so the dialog
        # reopens with the right combo selection next time.
        current_preset = self.combo_preset.currentText()
        self._settings.prompt_active_preset = (
            "" if current_preset == BUILTIN_DEFAULT_LABEL else current_preset
        )
        set_prompt_overrides(
            self._settings.prompt_persona, self._settings.prompt_custom_rules
        )
        save_settings(self._settings)
        self.applied.emit()

    def _on_ok(self) -> None:
        self._do_apply()
        self.accept()
