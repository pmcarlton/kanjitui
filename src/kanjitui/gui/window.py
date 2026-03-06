from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import webbrowser
from typing import Callable, Sequence

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QFontMetrics, QKeyEvent, QKeySequence, QShortcut, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from kanjitui import __version__
from kanjitui.db import query as db_query
from kanjitui.db.query import connect as connect_db
from kanjitui.db.user import UserStore
from kanjitui.font_warning import (
    BABELSTONE_HAN_URL,
    NOTO_CJK_URL,
    font_warning_allows_persistent_dismiss,
    font_warning_flag_key,
    font_warning_lines,
    startup_status_line,
)
from kanjitui.filtering import FilterState, apply_filter_state, filter_group_specs
from kanjitui.gui.state import GuiState, ORDERINGS
from kanjitui.related_nav import (
    RelatedRowsLayout,
    build_related_rows_layout,
)
from kanjitui.search import normalize as search_normalize
from kanjitui.setup_resources import (
    SOURCE_ORDER,
    SOURCES,
    acknowledgements_for_sources,
    default_build_font,
    default_setup_selection,
    detect_available_sources,
    download_selected_sources,
    setup_storage_guidance_lines,
    rebuild_database_from_sources,
    resolve_runtime_paths,
)
from kanjitui.strokeorder import StrokeOrderData, StrokeOrderRepository
from kanjitui.variant_nav import VariantTarget, build_variant_targets
from kanjitui.tui.navigation import build_strip
from kanjitui.tui.radicals import kangxi_radical_glyph

DEFAULT_UI_FONT_FAMILY = "Noto Sans Mono CJK"


def resolve_gui_font_family(preferred: str | None) -> str:
    db = QFontDatabase()
    families = set(db.families())
    candidates = [
        preferred,
        os.environ.get("KANJIGUI_FONT"),
        os.environ.get("KANJITUI_UI_FONT"),
        DEFAULT_UI_FONT_FAMILY,
        "Noto Sans CJK JP",
        "Hiragino Sans",
        "PingFang SC",
        "Menlo",
        "Monaco",
    ]
    for family in candidates:
        if family and family in families:
            return family
    return QApplication.font().family()


def ui_font(widget: QWidget | None, size: int, weight: QFont.Weight | None = None) -> QFont:
    family = DEFAULT_UI_FONT_FAMILY
    current = widget
    while current is not None:
        candidate = getattr(current, "ui_font_family", None)
        if isinstance(candidate, str) and candidate:
            family = candidate
            break
        current = current.parentWidget()
    font = QFont(family, size)
    if weight is not None:
        font.setWeight(weight)
    return font


class LiveTextDialog(QDialog):
    def __init__(
        self,
        title: str,
        on_close: Callable[[], None],
        parent: QWidget | None = None,
        close_keys: set[str] | None = None,
        close_on_any_key: bool = False,
        on_key: Callable[[QKeyEvent], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_close = on_close
        self._close_keys = close_keys or set()
        self._close_on_any_key = close_on_any_key
        self._on_key = on_key
        self.setWindowTitle(title)
        self.resize(820, 420)
        self.setStyleSheet("QDialog { border: 2px solid #00a0ff; }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text.setFont(ui_font(self, 14))
        layout.addWidget(self.text)

    def set_lines(self, lines: list[str]) -> None:
        self.text.setPlainText("\n".join(lines))

    def set_close_behavior(self, close_keys: set[str] | None, close_on_any_key: bool) -> None:
        self._close_keys = close_keys or set()
        self._close_on_any_key = close_on_any_key

    def set_on_key(self, on_key: Callable[[QKeyEvent], bool] | None) -> None:
        self._on_key = on_key

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._on_close()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        text = event.text()
        if self._close_on_any_key and event.key() not in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt):
            self.close()
            return
        if text and text in self._close_keys:
            self.close()
            return
        if self._on_key is not None and self._on_key(event):
            event.accept()
            return
        super().keyPressEvent(event)


class SearchDialog(QDialog):
    def __init__(self, state: GuiState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.selected_cp: int | None = None
        self.setWindowTitle("Search")
        self.resize(980, 520)

        layout = QVBoxLayout(self)
        self.query = QLineEdit(self)
        self.query.setPlaceholderText("Search: char, U+hex, kana, romaji, pinyin, gloss")
        self.query.setFont(ui_font(self, 14))
        layout.addWidget(self.query)

        self.hint = QLabel("Enter: run/jump   Esc: close   Up/Down: select   Home/End: top/bottom", self)
        self.hint.setFont(ui_font(self, 12))
        layout.addWidget(self.hint)

        self.results = QListWidget(self)
        self.results.setFont(ui_font(self, 14))
        layout.addWidget(self.results)

        buttons = QHBoxLayout()
        self.run_btn = QPushButton("Run", self)
        self.jump_btn = QPushButton("Jump", self)
        self.cancel_btn = QPushButton("Cancel", self)
        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.jump_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

        self.run_btn.clicked.connect(self.run_query)
        self.jump_btn.clicked.connect(self.accept_selected)
        self.cancel_btn.clicked.connect(self.reject)
        self.query.returnPressed.connect(self.run_or_jump)
        self.results.itemActivated.connect(lambda _: self.accept_selected())
        self.results.itemDoubleClicked.connect(lambda _: self.accept_selected())
        self.query.setFocus()

    def run_query(self) -> None:
        q = self.query.text()
        rows = self.state.run_search(q)
        self.results.clear()
        for row in rows:
            label = f"{row['ch']} U+{row['cp']:04X}  JP:{row['jp']}  CN:{row['cn']}  {row['gloss']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(row["cp"]))
            self.results.addItem(item)
        if rows:
            self.results.setCurrentRow(0)

    def run_or_jump(self) -> None:
        if self.results.count() > 0:
            self.accept_selected()
        else:
            self.run_query()

    def accept_selected(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        cp = item.data(Qt.ItemDataRole.UserRole)
        if cp is None:
            return
        self.selected_cp = int(cp)
        self.accept()


class BookmarkDialog(QDialog):
    def __init__(self, state: GuiState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.selected_cp: int | None = None
        self.reveal_mode = "none"
        self._study_cache: dict[int, dict[str, str]] = {}
        self._switching_set = False
        self.setWindowTitle("Bookmarks")
        self.resize(860, 560)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Enter: jump   Delete: delete bookmark   Right: readings   Left: gloss   (selection move clears reveal)",
            self,
        )
        hint.setFont(ui_font(self, 12))
        layout.addWidget(hint)

        set_row = QHBoxLayout()
        set_row.addWidget(QLabel("Bookmark Set:", self))
        self.set_combo = QComboBox(self)
        self.set_combo.setFont(ui_font(self, 12))
        set_row.addWidget(self.set_combo, stretch=1)
        self.new_set_btn = QPushButton("New Set", self)
        self.delete_set_btn = QPushButton("Delete Set", self)
        self.import_set_btn = QPushButton("Import Set", self)
        self.export_set_btn = QPushButton("Export Set", self)
        set_row.addWidget(self.new_set_btn)
        set_row.addWidget(self.delete_set_btn)
        set_row.addWidget(self.import_set_btn)
        set_row.addWidget(self.export_set_btn)
        layout.addLayout(set_row)

        self.results = QListWidget(self)
        self.results.setFont(ui_font(self, 14))
        layout.addWidget(self.results)

        self.study_title = QLabel("Study reveal: press Right or Left", self)
        self.study_title.setFont(ui_font(self, 12, QFont.Weight.Bold))
        self.study_body = QLabel("", self)
        self.study_body.setFont(ui_font(self, 12))
        self.study_body.setWordWrap(True)
        layout.addWidget(self.study_title)
        layout.addWidget(self.study_body)

        row = QHBoxLayout()
        self.jump_btn = QPushButton("Jump", self)
        self.delete_btn = QPushButton("Delete", self)
        self.close_btn = QPushButton("Close", self)
        row.addWidget(self.jump_btn)
        row.addWidget(self.delete_btn)
        row.addWidget(self.close_btn)
        layout.addLayout(row)

        # Ensure delete works regardless of which child widget currently has focus.
        self._bookmarks_shortcuts: list[QShortcut] = []
        for sequence in ("Del",):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.delete_selected)
            self._bookmarks_shortcuts.append(shortcut)

        self._reload_sets(select=self.state.active_bookmark_set)
        self._reload_bookmarks()

        self.results.itemDoubleClicked.connect(lambda _: self.accept_selected())
        self.results.itemActivated.connect(lambda _: self.accept_selected())
        self.results.currentItemChanged.connect(self._on_selection_changed)
        self.set_combo.currentTextChanged.connect(self._on_set_changed)
        self.new_set_btn.clicked.connect(self._create_set)
        self.delete_set_btn.clicked.connect(self._delete_set)
        self.import_set_btn.clicked.connect(self._import_set)
        self.export_set_btn.clicked.connect(self._export_set)
        self.jump_btn.clicked.connect(self.accept_selected)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.close_btn.clicked.connect(self.reject)
        self._update_study_reveal()

    def _reload_sets(self, select: str | None = None) -> None:
        names = self.state.list_bookmark_sets(limit=300)
        self._switching_set = True
        self.set_combo.clear()
        for name in names:
            self.set_combo.addItem(name)
        if select and select in names:
            self.set_combo.setCurrentText(select)
        elif names:
            self.set_combo.setCurrentIndex(0)
        self._switching_set = False

    def _reload_bookmarks(self) -> None:
        self.results.clear()
        bookmarks = self.state.list_bookmarks(limit=2000)
        for cp, tag in bookmarks:
            label = f"{chr(cp)} U+{cp:04X}"
            if tag:
                label += f" [{tag}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cp)
            self.results.addItem(item)
        if self.results.count() > 0:
            self.results.setCurrentRow(0)

    def _on_selection_changed(
        self,
        _current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        # Selection changes should hide reveal content until user explicitly asks again.
        self.reveal_mode = "none"
        self._update_study_reveal()

    def _on_set_changed(self, name: str) -> None:
        if self._switching_set:
            return
        if not name:
            return
        if not self.state.set_active_bookmark_set(name):
            return
        self.reveal_mode = "none"
        self._reload_sets(select=self.state.active_bookmark_set)
        self._reload_bookmarks()
        self._update_study_reveal()

    def _create_set(self) -> None:
        name, ok = QInputDialog.getText(self, "Create Bookmark Set", "Set name:")
        if not ok:
            return
        if not self.state.create_bookmark_set(name):
            return
        self.reveal_mode = "none"
        self._reload_sets(select=self.state.active_bookmark_set)
        self._reload_bookmarks()
        self._update_study_reveal()

    def _delete_set(self) -> None:
        current = self.state.active_bookmark_set
        if current == "default":
            QMessageBox.information(self, "Delete Bookmark Set", "The default set cannot be deleted.")
            return
        confirm = QMessageBox.question(
            self,
            "Delete Bookmark Set",
            f"Delete bookmark set '{current}'?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if not self.state.delete_active_bookmark_set():
            return
        self.reveal_mode = "none"
        self._reload_sets(select=self.state.active_bookmark_set)
        self._reload_bookmarks()
        self._update_study_reveal()

    def _export_set(self) -> None:
        current = self.state.active_bookmark_set
        default_name = f"{current}.json"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export Bookmark Set",
            default_name,
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.state.export_active_bookmark_set(path)
        except OSError as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def _import_set(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Import Bookmark Set",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        set_name, ok = QInputDialog.getText(
            self,
            "Import Bookmark Set",
            "Set name override (optional):",
        )
        if not ok:
            return
        override = set_name.strip() or None
        try:
            self.state.import_bookmark_set(path, set_name=override, replace=False)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))
            return
        self.reveal_mode = "none"
        self._reload_sets(select=self.state.active_bookmark_set)
        self._reload_bookmarks()
        self._update_study_reveal()

    def _selected_cp(self) -> int | None:
        item = self.results.currentItem()
        if item is None:
            return None
        cp = item.data(Qt.ItemDataRole.UserRole)
        if cp is None:
            return None
        return int(cp)

    def _study_payload(self, cp: int) -> dict[str, str]:
        cached = self._study_cache.get(cp)
        if cached is not None:
            return cached
        payload = db_query.bookmark_study_payload(self.state.conn, cp)
        self._study_cache[cp] = payload
        return payload

    def _update_study_reveal(self) -> None:
        cp = self._selected_cp()
        if cp is None:
            self.study_title.setText(f"Study reveal: no bookmark selected (set: {self.state.active_bookmark_set})")
            self.study_body.setText("")
            return
        if self.reveal_mode == "readings":
            payload = self._study_payload(cp)
            self.study_title.setText(f"Readings: {chr(cp)} U+{cp:04X}")
            self.study_body.setText(payload["readings"])
            return
        if self.reveal_mode == "gloss":
            payload = self._study_payload(cp)
            self.study_title.setText(f"Gloss: {chr(cp)} U+{cp:04X}")
            self.study_body.setText(payload["gloss"])
            return
        self.study_title.setText(f"Study reveal ready: {chr(cp)} U+{cp:04X} [{self.state.active_bookmark_set}]")
        self.study_body.setText("Right shows readings. Left shows gloss.")

    def accept_selected(self) -> None:
        cp = self._selected_cp()
        if cp is None:
            return
        self.selected_cp = cp
        self.accept()

    def delete_selected(self) -> None:
        item = self.results.currentItem()
        cp = self._selected_cp()
        if cp is None:
            return
        row = self.results.row(item)
        if self.state.delete_bookmark(cp):
            self._study_cache.pop(cp, None)
            self.results.takeItem(row)
            if self.results.count() > 0:
                self.results.setCurrentRow(max(0, min(row, self.results.count() - 1)))
            self._update_study_reveal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_selected()
            return
        if key == Qt.Key.Key_Right:
            self.reveal_mode = "readings"
            self._update_study_reveal()
            return
        if key == Qt.Key.Key_Left:
            self.reveal_mode = "gloss"
            self._update_study_reveal()
            return
        if key == Qt.Key.Key_Delete:
            self.delete_selected()
            return
        super().keyPressEvent(event)


class NoteEditorDialog(QDialog):
    def __init__(
        self,
        title: str,
        initial_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 520)
        layout = QVBoxLayout(self)

        self.editor = QPlainTextEdit(self)
        self.editor.setFont(ui_font(self, 14))
        self.editor.setPlainText(initial_text)
        layout.addWidget(self.editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.editor.moveCursor(self.editor.textCursor().MoveOperation.End)


class SetupDialog(QDialog):
    def __init__(self, window: "KanjiGuiWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window = window
        self.setWindowTitle("Setup (Lean Package)")
        self.resize(920, 640)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Select sources then press Download Selected. You can run this any time via Shift-S.",
            self,
        )
        hint.setFont(ui_font(self, 12))
        layout.addWidget(hint)
        self.storage_hint = QLabel(self)
        self.storage_hint.setWordWrap(True)
        self.storage_hint.setFont(ui_font(self, 11))
        layout.addWidget(self.storage_hint)

        self.checkboxes: dict[str, QCheckBox] = {}
        presence = self.window._available_sources()
        defaults = set(default_setup_selection(presence))
        source_grid = QGridLayout()
        source_grid.addWidget(QLabel("Source", self), 0, 0)
        source_grid.addWidget(QLabel("License / Terms", self), 0, 1)
        source_grid.setColumnStretch(0, 3)
        source_grid.setColumnStretch(1, 2)
        row_idx = 1
        for key in SOURCE_ORDER:
            if key not in SOURCES:
                continue
            spec = SOURCES[key]
            status = "installed" if presence.get(key, False) else "missing"
            cb = QCheckBox(f"{spec.label} ({status})", self)
            cb.setChecked(key in defaults)
            cb.toggled.connect(self._refresh_storage_hint)
            self.checkboxes[key] = cb
            source_grid.addWidget(cb, row_idx, 0)
            link = QLabel(
                f'<a href="{spec.license_url}">{spec.license_label}</a>',
                self,
            )
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            link.setToolTip(spec.license_url)
            source_grid.addWidget(link, row_idx, 1)
            row_idx += 1
        layout.addLayout(source_grid)

        self.font_filter_cb = QCheckBox(
            f"Auto-build using font filter ({self.window._default_build_font_spec()})",
            self,
        )
        self.font_filter_cb.setChecked(False)
        layout.addWidget(self.font_filter_cb)

        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setFont(ui_font(self, 12))
        layout.addWidget(self.log, 1)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        row = QHBoxLayout()
        self.download_btn = QPushButton("Download Selected", self)
        self.close_btn = QPushButton("Close", self)
        row.addWidget(self.download_btn)
        row.addWidget(self.close_btn)
        layout.addLayout(row)

        self.download_btn.clicked.connect(self._run_download)
        self.close_btn.clicked.connect(self.accept)
        self._refresh_storage_hint()

    def _refresh_storage_hint(self) -> None:
        selected = [key for key, cb in self.checkboxes.items() if cb.isChecked()]
        lines = setup_storage_guidance_lines(selected)
        self.storage_hint.setText("  ".join(lines))

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.ensureCursorVisible()
        QApplication.processEvents()

    def _run_download(self) -> None:
        selected = [key for key, cb in self.checkboxes.items() if cb.isChecked()]
        if not selected:
            self._append("No sources selected.")
            return
        total_steps = len(selected) + 1  # downloads + auto-build
        self.progress.setRange(0, total_steps)
        self.progress.setValue(0)
        self.download_btn.setEnabled(False)
        self._append("Starting downloads ...")

        def _progress(msg: str) -> None:
            self._append(msg)
            completed = re.match(r"^\[(\d+)/(\d+)\] Completed ", msg)
            if completed:
                self.progress.setValue(int(completed.group(1)))
            elif msg.startswith("Rebuilding DB with providers:"):
                self.progress.setValue(len(selected))

        results = download_selected_sources(selected, self.window.runtime_paths, progress=_progress)
        ok = sum(1 for status in results.values() if status == "ok")
        fail = sum(1 for status in results.values() if status != "ok")
        self._append(f"Completed: ok={ok} failed={fail}")
        setup_font = self.window._default_build_font_spec() if self.font_filter_cb.isChecked() else None
        self.window._after_setup_download(results, progress=_progress, font=setup_font)
        self.progress.setValue(total_steps)
        self._append(self.window.state.message)
        self.download_btn.setEnabled(True)


class AdvancedRebuildDialog(QDialog):
    def __init__(self, window: "KanjiGuiWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window = window
        self.setWindowTitle("Advanced Rebuild")
        self.resize(860, 560)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Rebuild DB from currently-downloaded sources. Use a font filter to keep only supported glyphs.",
            self,
        )
        hint.setWordWrap(True)
        hint.setFont(ui_font(self, 12))
        layout.addWidget(hint)

        self.use_font_filter = QCheckBox("Use font filter", self)
        self.use_font_filter.setChecked(True)
        layout.addWidget(self.use_font_filter)
        self.show_startup_cb = QCheckBox("Show startup on launch", self)
        self.show_startup_cb.setChecked(self.window.show_startup_on_launch)
        layout.addWidget(self.show_startup_cb)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font:", self))
        self.font_input = QLineEdit(window._default_build_font_spec(), self)
        self.font_input.setFont(ui_font(self, 12))
        font_row.addWidget(self.font_input, 1)
        layout.addLayout(font_row)

        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setFont(ui_font(self, 12))
        layout.addWidget(self.log, 1)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        row = QHBoxLayout()
        self.rebuild_btn = QPushButton("Rebuild", self)
        self.close_btn = QPushButton("Close", self)
        row.addWidget(self.rebuild_btn)
        row.addWidget(self.close_btn)
        layout.addLayout(row)

        self.rebuild_btn.clicked.connect(self._run_rebuild)
        self.close_btn.clicked.connect(self.accept)
        self.show_startup_cb.toggled.connect(self.window._set_show_startup_on_launch)

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.ensureCursorVisible()
        QApplication.processEvents()

    def _run_rebuild(self) -> None:
        self.rebuild_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        use_filter = self.use_font_filter.isChecked()
        font_spec = self.font_input.text().strip() or default_build_font()
        ok = self.window._run_advanced_rebuild(
            use_font_filter=use_filter,
            font_spec=font_spec,
            progress=self._append,
        )
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if ok else 0)
        self._append(self.window.state.message)
        self.rebuild_btn.setEnabled(True)


class FilterDialog(QDialog):
    def __init__(self, window: "KanjiGuiWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window = window
        self.state = window.state
        self.setWindowTitle("Filters")
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        hint = QLabel("Arrow keys navigate fields. Space/Enter changes selection.", self)
        hint.setFont(ui_font(self, 12))
        layout.addWidget(hint)

        self.hide_no_reading = QCheckBox("Hide no-reading (quick filter)", self)
        self.hide_no_reading.setChecked(self.state.hide_no_reading)
        layout.addWidget(self.hide_no_reading)

        self.combos: dict[str, QComboBox] = {}
        grid = QGridLayout()
        specs = filter_group_specs(self.state.freq_profiles)
        for row, group in enumerate(specs):
            label = QLabel(group.label, self)
            label.setFont(ui_font(self, 12))
            combo = QComboBox(self)
            combo.setFont(ui_font(self, 12))
            for option in group.options:
                combo.addItem(option.label, option.value)
            current = getattr(self.state.filter_state, group.key)
            idx = combo.findData(current)
            combo.setCurrentIndex(max(0, idx))
            self.combos[group.key] = combo
            grid.addWidget(label, row, 0)
            grid.addWidget(combo, row, 1)
        layout.addLayout(grid)

        preset_row = QHBoxLayout()
        preset_label = QLabel("Preset", self)
        preset_label.setFont(ui_font(self, 12))
        self.preset_combo = QComboBox(self)
        self.preset_combo.setFont(ui_font(self, 12))
        self.save_btn = QPushButton("Save Preset", self)
        self.load_btn = QPushButton("Load", self)
        self.delete_btn = QPushButton("Delete", self)
        preset_row.addWidget(preset_label)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.save_btn)
        preset_row.addWidget(self.load_btn)
        preset_row.addWidget(self.delete_btn)
        layout.addLayout(preset_row)

        self.preview = QLabel(self)
        self.preview.setFont(ui_font(self, 12, QFont.Weight.Bold))
        layout.addWidget(self.preview)

        buttons = QHBoxLayout()
        self.apply_btn = QPushButton("Apply", self)
        self.clear_btn = QPushButton("Clear All", self)
        self.close_btn = QPushButton("Close", self)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        for combo in self.combos.values():
            combo.currentIndexChanged.connect(self._update_preview)
        self.hide_no_reading.stateChanged.connect(lambda _: self._update_preview())
        self.apply_btn.clicked.connect(self._apply)
        self.clear_btn.clicked.connect(self._clear)
        self.close_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save_preset)
        self.load_btn.clicked.connect(self._load_preset)
        self.delete_btn.clicked.connect(self._delete_preset)

        self._refresh_presets()
        self._update_preview()

    def _refresh_presets(self) -> None:
        self.preset_combo.clear()
        if self.state.user_store is None:
            return
        names = self.state.user_store.list_filter_presets(limit=200)
        self.preset_combo.addItems(names)

    def _state_from_ui(self) -> FilterState:
        payload: dict[str, object] = {}
        for key, combo in self.combos.items():
            payload[key] = str(combo.currentData() or "any")
        return FilterState.from_payload(payload)

    def _preview_count(self, candidate: FilterState) -> int:
        ordered = self.state.base_ordered_cps()
        if self.hide_no_reading.isChecked():
            scope = self.state.reading_filter_scope()
            if scope == "jp":
                allowed = self.state.jp_reading_cps
            elif scope == "cn":
                allowed = self.state.cn_reading_cps
            else:
                allowed = self.state.jp_reading_cps | self.state.cn_reading_cps
            ordered = [cp for cp in ordered if cp in allowed]
        ordered = apply_filter_state(
            ordered,
            candidate,
            self.state.filter_data,
            default_frequency_profile=self.state.current_freq_profile,
        )
        return len(ordered)

    def _update_preview(self) -> None:
        candidate = self._state_from_ui()
        count = self._preview_count(candidate)
        active = "yes" if candidate.is_active() or self.hide_no_reading.isChecked() else "no"
        self.preview.setText(f"Preview matches: {count}  Active filters: {active}")

    def _apply(self) -> None:
        candidate = self._state_from_ui()
        self.state.hide_no_reading = self.hide_no_reading.isChecked()
        self.state.set_filter_state(candidate)
        self.state.message = f"Applied filters ({len(self.state.ordered_cps)} matches)"
        self.accept()

    def _clear(self) -> None:
        self.hide_no_reading.setChecked(False)
        self.state.clear_filters()
        for key, combo in self.combos.items():
            idx = combo.findData("any")
            combo.setCurrentIndex(max(0, idx))
            setattr(self.state.filter_state, key, "any")
        self.state.message = "Cleared filters"
        self._update_preview()

    def _save_preset(self) -> None:
        if self.state.user_store is None:
            self.state.message = "User workspace unavailable"
            return
        name, ok = QInputDialog.getText(self, "Save Filter Preset", "Preset name:")
        if not ok:
            return
        text = name.strip()
        if not text:
            self.state.message = "Preset name cannot be empty"
            return
        candidate = self._state_from_ui()
        payload = {"filters": candidate.to_payload(), "hide_no_reading": self.hide_no_reading.isChecked()}
        self.state.user_store.save_filter_preset(text, payload)
        self._refresh_presets()
        idx = self.preset_combo.findText(text)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self.state.message = f"Saved preset: {text}"

    def _load_preset(self) -> None:
        if self.state.user_store is None:
            self.state.message = "User workspace unavailable"
            return
        name = self.preset_combo.currentText().strip()
        if not name:
            return
        payload = self.state.user_store.get_filter_preset(name)
        if payload is None:
            self.state.message = f"Preset not found: {name}"
            return
        raw = payload.get("filters")
        if isinstance(raw, dict):
            state = FilterState.from_payload(raw)
            for key, combo in self.combos.items():
                idx = combo.findData(getattr(state, key))
                combo.setCurrentIndex(max(0, idx))
        hide = payload.get("hide_no_reading")
        if isinstance(hide, bool):
            self.hide_no_reading.setChecked(hide)
        self._update_preview()
        self.state.message = f"Loaded preset: {name}"

    def _delete_preset(self) -> None:
        if self.state.user_store is None:
            self.state.message = "User workspace unavailable"
            return
        name = self.preset_combo.currentText().strip()
        if not name:
            return
        deleted = self.state.user_store.delete_filter_preset(name)
        self._refresh_presets()
        self.state.message = f"Deleted preset: {name}" if deleted else f"Preset not found: {name}"


class RadicalDialog(QDialog):
    def __init__(self, state: GuiState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.selected_cp: int | None = None
        self.setWindowTitle("Radical Browser")
        self.resize(900, 560)

        root = QVBoxLayout(self)

        self.info = QLabel("Enter on radical: select radical   Enter on result: jump", self)
        self.info.setFont(ui_font(self, 12))
        root.addWidget(self.info)

        panel = QHBoxLayout()
        root.addLayout(panel)

        self.grid = QTableWidget(self)
        self.grid.setColumnCount(self.state.radical_grid_cols)
        rows = math.ceil(len(self.state.radical_numbers) / self.state.radical_grid_cols)
        self.grid.setRowCount(rows)
        self.grid.horizontalHeader().hide()
        self.grid.verticalHeader().hide()
        self.grid.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.grid.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grid.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grid.setFont(ui_font(self, 14))
        self.grid.horizontalHeader().setDefaultSectionSize(24)
        self.grid.verticalHeader().setDefaultSectionSize(24)
        self.grid.horizontalHeader().setMinimumSectionSize(20)
        self.grid.verticalHeader().setMinimumSectionSize(20)
        self.grid.setStyleSheet("QTableWidget::item { padding: 0px; margin: 0px; }")
        panel.addWidget(self.grid, 1)

        right = QVBoxLayout()
        panel.addLayout(right, 1)
        self.radical_meta = QLabel(self)
        self.radical_meta.setFont(ui_font(self, 12))
        self.radical_meta.setWordWrap(True)
        right.addWidget(self.radical_meta)
        stroke_row = QHBoxLayout()
        self.stroke_label = QLabel("strokes=all", self)
        self.stroke_label.setFont(ui_font(self, 12))
        self.stroke_prev = QPushButton("[", self)
        self.stroke_next = QPushButton("]", self)
        for btn in (self.stroke_prev, self.stroke_next):
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        stroke_row.addWidget(self.stroke_label)
        stroke_row.addWidget(self.stroke_prev)
        stroke_row.addWidget(self.stroke_next)
        right.addLayout(stroke_row)

        self.results = QListWidget(self)
        self.results.setFont(ui_font(self, 14))
        right.addWidget(self.results, 1)

        close_row = QHBoxLayout()
        self.jump_btn = QPushButton("Jump", self)
        self.cancel_btn = QPushButton("Close", self)
        close_row.addWidget(self.jump_btn)
        close_row.addWidget(self.cancel_btn)
        right.addLayout(close_row)

        for i, radical in enumerate(self.state.radical_numbers):
            r = i // self.state.radical_grid_cols
            c = i % self.state.radical_grid_cols
            item = QTableWidgetItem(kangxi_radical_glyph(radical))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.setItem(r, c, item)
        self._refresh_grid_visuals()

        self.stroke_prev.clicked.connect(lambda: self._adjust_stroke(-1))
        self.stroke_next.clicked.connect(lambda: self._adjust_stroke(+1))
        self.grid.cellDoubleClicked.connect(lambda r, c: self._activate_radical_cell(r, c))
        self.grid.currentCellChanged.connect(lambda *_: self._refresh_radical_meta())
        self.results.itemDoubleClicked.connect(lambda _: self.accept_selected())
        self.jump_btn.clicked.connect(self.accept_selected)
        self.cancel_btn.clicked.connect(self.reject)

        start_row = self.state.radical_idx // self.state.radical_grid_cols
        start_col = self.state.radical_idx % self.state.radical_grid_cols
        self.grid.setCurrentCell(start_row, start_col)
        self._refresh_radical_meta()
        self.grid.setFocus()

    def _radical_index_from_cell(self, row: int, col: int) -> int | None:
        idx = row * self.state.radical_grid_cols + col
        if 0 <= idx < len(self.state.radical_numbers):
            return idx
        return None

    def _activate_radical_cell(self, row: int, col: int) -> None:
        idx = self._radical_index_from_cell(row, col)
        if idx is None:
            return
        radical = self.state.radical_numbers[idx]
        if not self.state.radical_is_available(radical):
            self.state.message = f"{self.state.radical_info_line(radical)}  (no matches under current filters)"
            self.results.clear()
            self.grid.setFocus()
            self._refresh_radical_meta()
            return
        self.state.radical_pick(idx)
        self._refresh_results()
        self.results.setFocus()

    def _adjust_stroke(self, delta: int) -> None:
        if self.state.radical_selected is None:
            return
        self.state.radical_set_stroke_delta(delta)
        self._refresh_results()

    def _refresh_results(self) -> None:
        stroke = self.state.radical_stroke_options[self.state.radical_stroke_idx]
        self.stroke_label.setText(f"strokes={'all' if stroke is None else stroke}")
        self.results.clear()
        for cp in self.state.radical_results or []:
            item = QListWidgetItem(f"{chr(cp)} U+{cp:04X}")
            item.setData(Qt.ItemDataRole.UserRole, cp)
            self.results.addItem(item)
        if self.results.count() > 0:
            self.results.setCurrentRow(0)
        self._refresh_radical_meta()

    def _refresh_grid_visuals(self) -> None:
        for i, radical in enumerate(self.state.radical_numbers):
            r = i // self.state.radical_grid_cols
            c = i % self.state.radical_grid_cols
            item = self.grid.item(r, c)
            if item is None:
                continue
            if self.state.radical_is_available(radical):
                item.setForeground(QBrush(QColor("#111111")))
            else:
                item.setForeground(QBrush(QColor("#9a9a9a")))

    def _refresh_radical_meta(self) -> None:
        if self.state.radical_selected is not None:
            radical = self.state.radical_selected
        else:
            cell = self.grid.currentItem()
            if cell is None:
                self.radical_meta.setText("")
                return
            idx = self._radical_index_from_cell(cell.row(), cell.column())
            if idx is None:
                self.radical_meta.setText("")
                return
            radical = self.state.radical_numbers[idx]
        suffix = "" if self.state.radical_is_available(radical) else "  (filtered out)"
        self.radical_meta.setText(self.state.radical_info_line(radical) + suffix)

    def accept_selected(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        cp = item.data(Qt.ItemDataRole.UserRole)
        if cp is None:
            return
        self.selected_cp = int(cp)
        self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        text = event.text()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.results.hasFocus():
                self.accept_selected()
                return
            if self.grid.hasFocus():
                cell = self.grid.currentItem()
                if cell is not None:
                    self._activate_radical_cell(cell.row(), cell.column())
                    return
        if key == Qt.Key.Key_BracketLeft or text == "[":
            self._adjust_stroke(-1)
            return
        if key == Qt.Key.Key_BracketRight or text == "]":
            self._adjust_stroke(+1)
            return
        if key in (Qt.Key.Key_Backspace,):
            self.results.clear()
            self.state.radical_results = None
            self.state.radical_selected = None
            self.state.radical_stroke_options = [None]
            self.state.radical_stroke_idx = 0
            self.stroke_label.setText("strokes=all")
            self._refresh_radical_meta()
            self.grid.setFocus()
            return
        super().keyPressEvent(event)


class StrokeAnimationWidget(QWidget):
    def __init__(self, data: StrokeOrderData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data = data
        self.completed_strokes = 0
        self.current_stroke = 0
        self.current_points = 1
        self.done = False
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._advance_frame)
        self.timer.start()
        self.setMinimumSize(420, 420)

    def _advance_frame(self) -> None:
        if self.done:
            return
        if self.current_stroke >= len(self.data.strokes):
            self.done = True
            self.timer.stop()
            self.update()
            return
        stroke = self.data.strokes[self.current_stroke]
        if len(stroke) <= 1:
            self.completed_strokes = self.current_stroke + 1
            self.current_stroke += 1
            self.current_points = 1
            return
        step = max(1, len(stroke) // 26)
        self.current_points += step
        if self.current_points >= len(stroke):
            self.current_points = len(stroke)
            self.completed_strokes = self.current_stroke + 1
            self.current_stroke += 1
            self.current_points = 1
        self.update()

    def _map_point(self, x: float, y: float) -> tuple[float, float]:
        margin = 20.0
        width = max(1.0, float(self.width()) - margin * 2.0)
        height = max(1.0, float(self.height()) - margin * 2.0)
        scale = min(width / max(1.0, self.data.width), height / max(1.0, self.data.height))
        draw_w = self.data.width * scale
        draw_h = self.data.height * scale
        ox = (self.width() - draw_w) * 0.5
        oy = (self.height() - draw_h) * 0.5
        return ox + x * scale, oy + y * scale

    def _draw_stroke(self, painter: QPainter, stroke: list[tuple[float, float]], limit: int) -> None:
        if limit <= 1 or not stroke:
            return
        points = stroke[: min(limit, len(stroke))]
        prev = self._map_point(points[0][0], points[0][1])
        for x, y in points[1:]:
            cur = self._map_point(x, y)
            painter.drawLine(
                int(round(prev[0])),
                int(round(prev[1])),
                int(round(cur[0])),
                int(round(cur[1])),
            )
            prev = cur

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(250, 250, 250))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        for idx in range(min(self.completed_strokes, len(self.data.strokes))):
            self._draw_stroke(painter, self.data.strokes[idx], len(self.data.strokes[idx]))

        if self.current_stroke < len(self.data.strokes):
            self._draw_stroke(painter, self.data.strokes[self.current_stroke], self.current_points)

        painter.end()


class StrokeAnimationDialog(QDialog):
    def __init__(self, data: StrokeOrderData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Stroke Order: {data.ch}")
        self.resize(560, 620)
        layout = QVBoxLayout(self)
        self.info = QLabel(
            f"Source: {data.source_path.name}   Strokes: {len(data.strokes)}   Esc: close",
            self,
        )
        self.info.setFont(ui_font(self, 12))
        layout.addWidget(self.info)
        self.canvas = StrokeAnimationWidget(data, self)
        layout.addWidget(self.canvas, 1)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class KanjiGuiWindow(QMainWindow):
    def __init__(self, state: GuiState, ui_font_family: str | None = None) -> None:
        super().__init__()
        self.state = state
        self.ui_font_family = ui_font_family or DEFAULT_UI_FONT_FAMILY
        self.setWindowTitle("kanjigui")
        self.resize(1460, 980)
        self.setMinimumSize(1100, 760)
        self._overlays: dict[str, LiveTextDialog] = {}
        self._variant_cache_cp: int | None = None
        self._variant_graph: dict | None = None
        self._variant_targets: list[VariantTarget] = []
        self.runtime_paths = resolve_runtime_paths(self.state.user_store)
        self.stroke_repo = StrokeOrderRepository(root=self.runtime_paths.strokeorder_dir)
        self.show_ack_overlay = False
        self.show_font_warning_overlay = False
        self.font_warning_lines: list[str] = []
        self.font_warning_flag = ""
        self.runtime_font = (self.ui_font_family or "").strip() or None
        self.build_meta: dict[str, str] = {}
        self.user_query_rows: list[tuple[int, str]] = []
        self.user_query_idx = 0
        if self.state.user_store is not None:
            self.show_startup_on_launch = self.state.user_store.show_startup_on_launch()
            self.show_startup_overlay = self.show_startup_on_launch
        else:
            self.show_startup_on_launch = True
            self.show_startup_overlay = True
        self._init_font_warning_overlay()
        if self.state.message == "Ready":
            self.state.message = self._startup_status()
        self._stroke_window: StrokeAnimationDialog | None = None
        self._build_ui()
        self.refresh_view()

    def _build_panel(self, title: str) -> tuple[QGroupBox, QTextEdit]:
        box = QGroupBox(title, self)
        box.setFont(ui_font(self, 16))
        layout = QVBoxLayout(box)
        text = QTextEdit(box)
        text.setReadOnly(True)
        text.setFont(ui_font(self, 16))
        text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        text.setAcceptRichText(True)
        layout.addWidget(text)
        return box, text

    def _set_panel_text(self, widget: QTextEdit, lines: list[str], html_lines: list[str] | None = None) -> None:
        if html_lines is None:
            html_lines = [html.escape(line) for line in lines]
        widget.setHtml("<br/>".join(html_lines))
        fm = QFontMetrics(widget.font())
        content_w = max(140, widget.viewport().width() - 16)
        visual_lines = 0
        source_lines = lines if lines else [""]
        for line in source_lines:
            width = max(1, fm.horizontalAdvance(line))
            visual_lines += max(1, math.ceil(width / content_w))
        base = visual_lines * fm.lineSpacing()
        padding = (widget.frameWidth() * 2) + 18
        widget.setFixedHeight(max(72, base + padding))

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        grid = QGridLayout(root)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.header_label = QLabel(self)
        self.header_label.setFont(ui_font(self, 16, QFont.Weight.Bold))
        self.header_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.header_label, 0, 0)

        self.nav_strip = QLabel(self)
        self.nav_strip.setFont(ui_font(self, 18))
        self.nav_strip.setTextFormat(Qt.TextFormat.RichText)
        self.nav_strip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.nav_strip, 1, 0)

        left_scroll = QScrollArea(self)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        left_inner = QWidget(left_scroll)
        left_layout = QVBoxLayout(left_inner)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.jp_group, self.jp_text = self._build_panel("JP [1]")
        self.cn_group, self.cn_text = self._build_panel("CN [2]")
        self.sent_group, self.sent_text = self._build_panel("Sentences [3]")
        self.var_group, self.var_text = self._build_panel("Variants [4]")

        left_layout.addWidget(self.jp_group)
        left_layout.addWidget(self.cn_group)
        left_layout.addWidget(self.sent_group)
        left_layout.addWidget(self.var_group)
        left_layout.addStretch(1)
        left_scroll.setWidget(left_inner)
        grid.addWidget(left_scroll, 2, 0)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.glyph_label = QLabel("?", self)
        self.glyph_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.glyph_label.setFont(ui_font(self, 56))
        self.glyph_label.setMinimumWidth(280)
        self.glyph_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        right_layout.addWidget(self.glyph_label)

        self.glyph_meta = QLabel(self)
        self.glyph_meta.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.glyph_meta.setFont(ui_font(self, 16))
        self.glyph_meta.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        right_layout.addWidget(self.glyph_meta)
        right_layout.addStretch(1)
        grid.addWidget(right, 0, 1, 3, 1)

        self.menu_label = QLabel(self)
        self.menu_label.setFont(ui_font(self, 13, QFont.Weight.Bold))
        self.menu_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.menu_label, 3, 0, 1, 2)

        self.context_label = QLabel(self)
        self.context_label.setFont(ui_font(self, 13, QFont.Weight.Bold))
        self.context_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.context_label.setStyleSheet(
            "QLabel { color: #005f8a; background: #e9f7ff; border: 1px solid #9ddcff; padding: 3px 6px; }"
        )
        grid.addWidget(self.context_label, 4, 0, 1, 2)

        self.status_label = QLabel(self)
        self.status_label.setFont(ui_font(self, 14))
        self.status_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.status_label, 5, 0, 1, 2)

        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)

        for widget in (
            self.jp_text,
            self.cn_text,
            self.sent_text,
            self.var_text,
            left_inner,
            right,
            root,
        ):
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_navigation_shortcuts()
        self.setFocus()

    def _setup_navigation_shortcuts(self) -> None:
        self._nav_shortcuts: list[QShortcut] = []
        bindings = [
            (Qt.Key.Key_Right, self._shortcut_move_next),
            (Qt.Key.Key_Left, self._shortcut_move_prev),
            (Qt.Key.Key_Down, self._shortcut_move_down),
            (Qt.Key.Key_Up, self._shortcut_move_up),
            (Qt.Key.Key_Home, self._shortcut_move_home),
            (Qt.Key.Key_End, self._shortcut_move_end),
        ]
        for key, handler in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            self._nav_shortcuts.append(shortcut)
        for sequence, handler in (
            ("Shift+Left", self._shortcut_move_related_left),
            ("Shift+Right", self._shortcut_move_related_right),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            self._nav_shortcuts.append(shortcut)

    def _shortcut_move_next(self) -> None:
        self.state.move_next()
        self.refresh_view()

    def _shortcut_move_prev(self) -> None:
        self.state.move_prev()
        self.refresh_view()

    def _shortcut_move_down(self) -> None:
        if self.state.show_phonetic:
            _ = self._move_related_selection_vertical(+1)
        elif self.state.panel_focus == "variants" and self.state.show_variants:
            _ = self._move_variant_selection(+1)
        else:
            _ = self._move_related_selection_vertical(+1)
        self.refresh_view()

    def _shortcut_move_up(self) -> None:
        if self.state.show_phonetic:
            _ = self._move_related_selection_vertical(-1)
        elif self.state.panel_focus == "variants" and self.state.show_variants:
            _ = self._move_variant_selection(-1)
        else:
            _ = self._move_related_selection_vertical(-1)
        self.refresh_view()

    def _shortcut_move_related_left(self) -> None:
        _ = self._move_related_selection_horizontal(-1)
        self.refresh_view()

    def _shortcut_move_related_right(self) -> None:
        _ = self._move_related_selection_horizontal(+1)
        self.refresh_view()

    def _shortcut_move_home(self) -> None:
        if self.state.show_phonetic:
            detail = self._current_detail()
            rows = self._related_rows_for_detail(detail) if detail is not None else []
            self.state.related_row_idx = 0 if rows else 0
            self.state.related_col_idx = 0
        elif self.state.panel_focus == "variants" and self.state.show_variants:
            cp = self.state.current_cp
            if cp is not None:
                _graph, targets = self._variant_data_for(cp)
                self.state.move_variant_home(len(targets))
        else:
            self.state.move_home()
        self.refresh_view()

    def _shortcut_move_end(self) -> None:
        if self.state.show_phonetic:
            detail = self._current_detail()
            rows = self._related_rows_for_detail(detail) if detail is not None else []
            self.state.related_row_idx = len(rows) - 1 if rows else 0
            self.state.related_col_idx = 0
        elif self.state.panel_focus == "variants" and self.state.show_variants:
            cp = self.state.current_cp
            if cp is not None:
                _graph, targets = self._variant_data_for(cp)
                self.state.move_variant_end(len(targets))
        else:
            self.state.move_end()
        self.refresh_view()

    def _cycle_panel_focus_and_sync_related(self) -> None:
        self.state.toggle_focus()
        if self.state.show_phonetic:
            return
        if self.state.panel_focus not in {"jp", "cn", "sentences"}:
            return
        detail = self._current_detail()
        if detail is None:
            return
        first_row = self._first_row_index_for_panel(detail, self.state.panel_focus)
        if first_row is not None:
            self.state.related_row_idx = first_row
            self.state.related_col_idx = 0

    def _focus_style(self, active: bool) -> str:
        if active:
            return (
                "QGroupBox{border:3px double #00a0ff; margin-top: 8px; background: #f6fbff;}"
                "QGroupBox::title{subcontrol-origin: margin; left: 8px; padding:0 3px; color:#007bb8; font-weight:700;}"
            )
        return (
            "QGroupBox{border:1px solid #666; margin-top: 8px;}"
            "QGroupBox::title{subcontrol-origin: margin; left: 8px; padding:0 3px;}"
        )

    def _active_input_context(self) -> str:
        if self.show_font_warning_overlay:
            return "Input: Font warning overlay (R rebuild, D dismiss, N/B links)"
        if self.show_startup_overlay:
            return "Input: Startup overlay (any key dismisses)"
        if self.show_ack_overlay:
            return "Input: Acknowledgements overlay (Shift-A / Esc)"
        if self.state.show_help:
            return "Input: Main view + Help overlay"
        if self.state.show_provenance:
            return "Input: Main view + Provenance overlay"
        if self.state.show_components:
            return "Input: Main view + Components overlay"
        if self.state.show_phonetic:
            return "Input: Main view + Phonetic overlay"
        if self.state.show_user_overlay:
            return "Input: Main view + User overlay"
        return f"Input: Main view (panel focus: {self.state.panel_focus.upper()})"

    def _startup_status(self) -> str:
        return startup_status_line(
            program="kanjigui",
            version=__version__,
            build_meta=self.build_meta,
            runtime_font=self.runtime_font,
            total_glyphs=len(self.state.filter_data.all_cps),
            visible_glyphs=len(self.state.ordered_cps),
        )

    @staticmethod
    def _render_selectable_text(
        text: str,
        selectable: set[int] | None = None,
        selected_cp: int | None = None,
    ) -> str:
        selectable_set = selectable or set()
        parts: list[str] = []
        for ch in text:
            cp = ord(ch)
            escaped = html.escape(ch)
            if cp not in selectable_set:
                parts.append(escaped)
                continue
            style = "text-decoration:underline;"
            if selected_cp is not None and cp == selected_cp:
                style += "color:#00a0ff;font-weight:700;"
            parts.append(f'<span style="{style}">{escaped}</span>')
        return "".join(parts)

    def _current_detail(self) -> dict | None:
        cp = self.state.current_cp
        if cp is None:
            return None
        return db_query.get_char_detail(self.state.conn, cp)

    def _variant_data_for(self, cp: int) -> tuple[dict, list[VariantTarget]]:
        if self._variant_cache_cp != cp:
            graph = db_query.variant_graph(self.state.conn, cp, depth=2, max_nodes=32)
            self._variant_graph = graph
            self._variant_targets = build_variant_targets(cp, graph)
            self.state.variant_idx = 0
            self._variant_cache_cp = cp
        graph = self._variant_graph or {"nodes": [], "edges": []}
        self.state.move_variant_selection(0, len(self._variant_targets))
        return graph, self._variant_targets

    def _move_variant_selection(self, delta: int) -> bool:
        cp = self.state.current_cp
        if cp is None:
            return False
        _graph, targets = self._variant_data_for(cp)
        if not targets:
            return False
        self.state.move_variant_selection(delta, len(targets))
        return True

    def _jump_to_selected_variant(self) -> bool:
        cp = self.state.current_cp
        if cp is None:
            return False
        _graph, targets = self._variant_data_for(cp)
        if not targets:
            self.state.message = "No variants to jump to"
            return False
        selected = targets[self.state.variant_idx]
        if selected.cp not in self.state.ordered_cps:
            self.state.message = f"Variant {selected.ch} U+{selected.cp:04X} is filtered out"
            return False
        self.state.jump_to_cp(selected.cp)
        return True

    def _main_related_layout(
        self,
        detail: dict,
        sentence_rows: Sequence[tuple[str, str, str | None, str | None, str | None, str | None, int]] | None = None,
    ) -> RelatedRowsLayout:
        if sentence_rows is None:
            sentence_rows = self._sentence_rows_for_detail(detail)
        jp_words = detail["jp_words"] if self.state.show_jp else []
        cn_words = detail["cn_words"] if self.state.show_cn else []
        sentence_texts = (
            [text for _lang, text, _reading, _gloss, _source, _license, _rank in sentence_rows]
            if self.state.show_sentences
            else []
        )
        return build_related_rows_layout(
            current_cp=int(detail["cp"]),
            jp_words=jp_words,
            cn_words=cn_words,
            sentence_texts=sentence_texts,
            allowed=None,
        )

    def _sentence_rows_for_detail(
        self,
        detail: dict,
    ) -> list[tuple[str, str, str | None, str | None, str | None, str | None, int]]:
        cp = int(detail["cp"])
        langs = self.state.sentence_langs()
        sent_limit = 6 if len(langs) > 1 else 3
        rows = db_query.get_sentences(self.state.conn, cp, limit=sent_limit, langs=langs)
        return rows

    def _phonetic_related_rows(self, cp: int) -> list[list[int]]:
        rows: list[list[int]] = []
        seen: set[int] = set()
        for member_cp, _member_ch, _key, _pinyin_marked, _pinyin_numbered in db_query.get_phonetic_series(
            self.state.conn, cp, limit=120
        ):
            if member_cp == cp or member_cp in seen:
                continue
            seen.add(member_cp)
            rows.append([member_cp])
        return rows

    def _related_rows_for_detail(self, detail: dict, include_phonetic: bool | None = None) -> list[list[int]]:
        cp = int(detail["cp"])
        main_rows = [list(row) for row in self._main_related_layout(detail).rows]
        if include_phonetic is None:
            if self.state.show_phonetic:
                return self._phonetic_related_rows(cp)
            return main_rows
        if not include_phonetic:
            return main_rows

        rows = [list(row) for row in main_rows]
        seen: set[int] = {member for row in rows for member in row}
        for row in self._phonetic_related_rows(cp):
            member_cp = row[0]
            if member_cp in seen:
                continue
            seen.add(member_cp)
            rows.append(row)
        return rows

    def _panel_for_related_row(self, detail: dict, row_idx: int) -> str | None:
        layout = self._main_related_layout(detail)
        if row_idx < 0 or row_idx >= len(layout.row_panels):
            return None
        panel = layout.row_panels[row_idx]
        if panel in {"jp", "cn", "sentences"}:
            return panel
        return None

    def _set_panel_focus_from_related_row(self, detail: dict, row_idx: int) -> None:
        if self.state.show_phonetic:
            return
        panel = self._panel_for_related_row(detail, row_idx)
        if panel is None:
            return
        self.state.panel_focus = panel
        if self.state.panel_focus in ("jp", "cn") and self.state.focus != self.state.panel_focus:
            self.state.focus = self.state.panel_focus
            if ORDERINGS[self.state.ordering_idx] == "reading" or self.state.hide_no_reading:
                self.state.refresh_ordering()

    def _first_row_index_for_panel(self, detail: dict, panel: str) -> int | None:
        layout = self._main_related_layout(detail)
        for idx, row_panel in enumerate(layout.row_panels):
            if row_panel == panel:
                return idx
        return None

    def _selected_related_cp_for_detail(self, detail: dict, include_phonetic: bool | None = None) -> int | None:
        rows = self._related_rows_for_detail(detail, include_phonetic=include_phonetic)
        if not rows:
            self.state.related_row_idx = 0
            self.state.related_col_idx = 0
            return None
        self.state.related_row_idx = max(0, min(self.state.related_row_idx, len(rows) - 1))
        if include_phonetic is None and not self.state.show_phonetic:
            self._set_panel_focus_from_related_row(detail, self.state.related_row_idx)
        row = rows[self.state.related_row_idx]
        self.state.related_col_idx = max(0, min(self.state.related_col_idx, len(row) - 1))
        return row[self.state.related_col_idx]

    def _move_related_selection_vertical(self, delta: int) -> bool:
        detail = self._current_detail()
        if detail is None:
            return False
        rows = self._related_rows_for_detail(detail)
        if not rows:
            self.state.related_row_idx = 0
            self.state.related_col_idx = 0
            self.state.message = "No related glyphs in phonetic series" if self.state.show_phonetic else "No related glyphs in JP/CN/Sentences"
            return False
        self.state.related_row_idx = (self.state.related_row_idx + delta) % len(rows)
        if not self.state.show_phonetic:
            self._set_panel_focus_from_related_row(detail, self.state.related_row_idx)
        row = rows[self.state.related_row_idx]
        self.state.related_col_idx = min(self.state.related_col_idx, len(row) - 1)
        selected = row[self.state.related_col_idx]
        self.state.message = (
            f"Related: {chr(selected)} U+{selected:04X} "
            f"(line {self.state.related_row_idx + 1}/{len(rows)}, pos {self.state.related_col_idx + 1}/{len(row)})"
        )
        return True

    def _move_related_selection_horizontal(self, delta: int) -> bool:
        detail = self._current_detail()
        if detail is None:
            return False
        rows = self._related_rows_for_detail(detail)
        if not rows:
            self.state.related_row_idx = 0
            self.state.related_col_idx = 0
            self.state.message = "No related glyphs in phonetic series" if self.state.show_phonetic else "No related glyphs in JP/CN/Sentences"
            return False
        self.state.related_row_idx = max(0, min(self.state.related_row_idx, len(rows) - 1))
        if not self.state.show_phonetic:
            self._set_panel_focus_from_related_row(detail, self.state.related_row_idx)
        row = rows[self.state.related_row_idx]
        if len(row) <= 1:
            self.state.related_col_idx = 0
            selected = row[0]
            self.state.message = f"Related line has one glyph: {chr(selected)} U+{selected:04X}"
            return True
        self.state.related_col_idx = (self.state.related_col_idx + delta) % len(row)
        selected = row[self.state.related_col_idx]
        self.state.message = (
            f"Related: {chr(selected)} U+{selected:04X} "
            f"(line {self.state.related_row_idx + 1}/{len(rows)}, pos {self.state.related_col_idx + 1}/{len(row)})"
        )
        return True

    def _jump_to_selected_related(self) -> bool:
        detail = self._current_detail()
        if detail is None:
            return False
        selected = self._selected_related_cp_for_detail(detail)
        if selected is None:
            self.state.message = "No related glyph selected"
            return False
        if selected not in self.state.ordered_cps:
            self.state.message = f"Related glyph {chr(selected)} U+{selected:04X} is filtered out"
            return False
        self.state.jump_to_cp(selected)
        return True

    def _handle_phonetic_overlay_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Up:
            _ = self._move_related_selection_vertical(-1)
            self.refresh_view()
            return True
        if key == Qt.Key.Key_Down:
            _ = self._move_related_selection_vertical(+1)
            self.refresh_view()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            _ = self._jump_to_selected_related()
            self.refresh_view()
            return True
        if key == Qt.Key.Key_Home:
            detail = self._current_detail()
            rows = self._related_rows_for_detail(detail) if detail is not None else []
            self.state.related_row_idx = 0 if rows else 0
            self.state.related_col_idx = 0
            self.refresh_view()
            return True
        if key == Qt.Key.Key_End:
            detail = self._current_detail()
            rows = self._related_rows_for_detail(detail) if detail is not None else []
            self.state.related_row_idx = len(rows) - 1 if rows else 0
            self.state.related_col_idx = 0
            self.refresh_view()
            return True
        return False

    def _refresh_user_queries(self, limit: int = 200) -> None:
        if self.state.user_store is None:
            self.user_query_rows = []
            self.user_query_idx = 0
            return
        self.user_query_rows = self.state.user_store.recent_query_rows(limit=limit)
        if not self.user_query_rows:
            self.user_query_idx = 0
            return
        self.user_query_idx = max(0, min(self.user_query_idx, len(self.user_query_rows) - 1))

    def _handle_user_overlay_key(self, event: QKeyEvent) -> bool:
        if self.state.user_store is None:
            self.state.message = "User workspace unavailable"
            self.state.show_user_overlay = False
            self.refresh_view()
            return True
        self._refresh_user_queries()
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Home):
            if self.user_query_rows:
                if key == Qt.Key.Key_Home:
                    self.user_query_idx = 0
                else:
                    self.user_query_idx = max(0, self.user_query_idx - 1)
            self.refresh_view()
            return True
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_End):
            if self.user_query_rows:
                if key == Qt.Key.Key_End:
                    self.user_query_idx = len(self.user_query_rows) - 1
                else:
                    self.user_query_idx = min(len(self.user_query_rows) - 1, self.user_query_idx + 1)
            self.refresh_view()
            return True
        if key == Qt.Key.Key_Delete:
            if not self.user_query_rows:
                self.state.message = "No query selected"
                self.refresh_view()
                return True
            row_id, query = self.user_query_rows[self.user_query_idx]
            deleted = self.state.user_store.delete_recent_query(row_id)
            self._refresh_user_queries()
            self.state.message = f"Deleted query: {query}" if deleted else f"Query not found: {query}"
            self.refresh_view()
            return True
        text = event.text()
        if text in {"c", "C"}:
            removed = self.state.user_store.clear_recent_queries()
            self._refresh_user_queries()
            self.state.message = f"Cleared query history ({removed} removed)"
            self.refresh_view()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self.user_query_rows:
                self.state.message = "No query selected"
                self.refresh_view()
                return True
            _row_id, query = self.user_query_rows[self.user_query_idx]
            rows = self.state.search_engine.run(query, limit=200)
            if not rows:
                self.state.message = f"No results for query: {query}"
                self.refresh_view()
                return True
            cp = int(rows[0]["cp"])
            self.state.jump_to_cp(cp)
            self.state.message = f"Jumped via query '{query}' to {chr(cp)} U+{cp:04X}"
            self.refresh_view()
            return True
        return False

    def _format_user_overlay(self, cp: int) -> list[str]:
        if self.state.user_store is None:
            return ["(user store unavailable)"]
        self._refresh_user_queries()
        glyph_notes = self.state.user_store.get_glyph_notes(cp, limit=4)
        global_notes = self.state.user_store.get_global_notes(limit=4)
        bookmarks = self.state.user_store.list_bookmarks(
            limit=6,
            set_name=self.state.active_bookmark_set,
        )
        queries = list(self.user_query_rows)
        lines = ["Glyph notes:"]
        lines.extend([f"- {note}" for note in glyph_notes] or ["(none)"])
        lines.append("")
        lines.append("Global notes:")
        lines.extend([f"- {note}" for note in global_notes] or ["(none)"])
        lines.append("")
        lines.append(f"Bookmarks [{self.state.active_bookmark_set}]:")
        lines.extend([f"- {chr(bcp)} U+{bcp:04X} {f'[{tag}]' if tag else ''}" for bcp, tag in bookmarks[:3]] or ["(none)"])
        lines.append("")
        lines.append("Recent queries: Left/Right select, Enter jump, Delete remove, c clear")
        if not queries:
            lines.append("(none)")
            return lines
        token_parts: list[str] = []
        for idx, (_row_id, query) in enumerate(queries):
            clean = " ".join(query.split())
            if not clean:
                continue
            if idx == self.user_query_idx:
                token_parts.append(f"[{clean}]")
            else:
                token_parts.append(clean)
        if not token_parts:
            lines.append("(none)")
            return lines
        joined = " ".join(token_parts)
        wrap = 96
        for start in range(0, len(joined), wrap):
            lines.append(joined[start : start + wrap])
        selected_id, selected_query = queries[self.user_query_idx]
        lines.append("")
        lines.append(f"Selected #{self.user_query_idx + 1}/{len(queries)} id={selected_id}: {selected_query}")
        return lines

    def _sync_overlay(
        self,
        key: str,
        enabled: bool,
        title: str,
        lines: list[str],
        on_close: Callable[[], None] | None = None,
        close_keys: set[str] | None = None,
        close_on_any_key: bool = False,
        on_key: Callable[[QKeyEvent], bool] | None = None,
    ) -> None:
        dlg = self._overlays.get(key)
        if not enabled:
            if dlg is not None:
                dlg.close()
                self._overlays.pop(key, None)
            return

        if dlg is None:
            def _on_close() -> None:
                if on_close is not None:
                    on_close()
                self._overlays.pop(key, None)
                self.refresh_view()

            dlg = LiveTextDialog(
                title,
                _on_close,
                self,
                close_keys=close_keys,
                close_on_any_key=close_on_any_key,
                on_key=on_key,
            )
            dlg.show()
            self._overlays[key] = dlg
        elif not dlg.isVisible():
            dlg.show()
        dlg.setWindowTitle(title)
        dlg.set_close_behavior(close_keys=close_keys, close_on_any_key=close_on_any_key)
        dlg.set_on_key(on_key)
        dlg.set_lines(lines)
        dlg.raise_()
        dlg.activateWindow()
        dlg.setFocus()

    def _sync_overlays(self, detail: dict) -> None:
        cp = int(detail["cp"])
        self._sync_overlay(
            "help",
            self.state.show_help,
            "Help",
            [
                "Navigation: <-/->/j/k move order; Up/Down select related glyph; Shift-Left/Right same-line",
                "Ordering: O cycle ordering, F cycle freq profile",
                "JP panel: m toggles kana/romaji",
                "Filter: f opens menu; presets can be saved/loaded/deleted",
                "Quick filter: Shift-N toggles hide-no-reading",
                "Search: / open, Enter run/jump, Up/Down select",
                "Radicals: r open browser",
                "Advanced: Shift-R settings/rebuild menu (startup toggle + font-filter)",
                "Panels: 1 JP, 2 CN, 3 Sentences, 4 Variants",
                "Variants panel: Tab focus, Up/Down select variant, Enter jump",
                "Overlays: c Components, s Phonetics, p Provenance, u User panel",
                "Workspace: b toggle bookmark, B bookmarks list/jump",
                "Bookmarks list: Delete key deletes bookmark, set selector manages named sets (new/delete/import/export)",
                "Bookmarks study: Right reveals readings, Left reveals gloss (clears on selection move)",
                "Notes: n per-glyph editor, g global editor",
                "Editor: Enter newline, Save button commits",
                "Setup: Shift-S source setup/download menu",
                "Acknowledgements: Shift-A overlay",
                "Stroke order: t popup (only when data exists)",
                "CCAMC: i open glyph page",
                "Global: ? Help, q Quit",
            ],
            on_close=lambda: setattr(self.state, "show_help", False),
            close_keys={"?"},
        )

        prov = db_query.get_provenance(self.state.conn, cp, limit=100)
        prov_lines = [f"{field}: {value} [{source} {conf:.2f}]" for field, value, source, conf in prov]
        if not prov_lines:
            prov_lines = ["(no provenance rows)"]
        self._sync_overlay(
            "provenance",
            self.state.show_provenance,
            "Provenance",
            prov_lines,
            on_close=lambda: setattr(self.state, "show_provenance", False),
            close_keys={"p", "P"},
        )

        comp = db_query.get_components(self.state.conn, cp)
        comp_lines = [f"{idx + 1}. {ch} U+{ccp:04X}" for idx, (ccp, ch) in enumerate(comp)] or ["(no components)"]
        self._sync_overlay(
            "components",
            self.state.show_components,
            "Components",
            comp_lines,
            on_close=lambda: setattr(self.state, "show_components", False),
            close_keys={"c", "C"},
        )

        ph = db_query.get_phonetic_series(self.state.conn, cp, limit=120)
        ph_lines: list[str] = []
        for idx, (member_cp, member_ch, key, pinyin_marked, pinyin_numbered) in enumerate(ph):
            pinyin = pinyin_marked or search_normalize.pinyin_numbered_to_marked(pinyin_numbered)
            marker = "▶" if idx == self.state.related_row_idx else " "
            row = f"{marker} {idx + 1}. {member_ch} U+{member_cp:04X} [{key}]"
            if pinyin:
                row += f"  {pinyin}"
            ph_lines.append(row)
        if not ph_lines:
            ph_lines = ["(no phonetic series rows)"]
        self._sync_overlay(
            "phonetic",
            self.state.show_phonetic,
            "Phonetic Series",
            ph_lines,
            on_close=lambda: setattr(self.state, "show_phonetic", False),
            close_keys={"s", "S"},
            on_key=self._handle_phonetic_overlay_key,
        )

        self._sync_overlay(
            "user",
            self.state.show_user_overlay,
            "User Workspace",
            self._format_user_overlay(cp),
            on_close=lambda: setattr(self.state, "show_user_overlay", False),
            close_keys={"u", "U"},
            on_key=self._handle_user_overlay_key,
        )

        self._sync_overlay(
            "ack",
            self.show_ack_overlay,
            "Acknowledgements",
            self._ack_lines(),
            on_close=lambda: setattr(self, "show_ack_overlay", False),
            close_keys={"A"},
        )
        startup_lines = [
            "Welcome to kanjigui.",
            "Press any key to dismiss this page.",
            "Shift-S opens setup/download menu.",
            "Shift-R opens advanced settings/rebuild menu.",
            "Shift-A reopens acknowledgements.",
            "",
        ] + self._ack_lines()
        self._sync_overlay(
            "startup",
            self.show_startup_overlay,
            "Startup",
            startup_lines,
            on_close=self._dismiss_startup_overlay,
            close_on_any_key=True,
        )
        self._sync_overlay(
            "font_warning",
            self.show_font_warning_overlay,
            "Font Warning",
            self.font_warning_lines,
            on_close=lambda: self._dismiss_font_warning_overlay(persist=True),
            close_keys={"D"},
            on_key=self._handle_font_warning_overlay_key,
        )

    def refresh_view(self) -> None:
        detail = self._current_detail()
        if detail is None:
            total_chars = len(self.state.filter_data.all_cps)
            if total_chars > 0:
                self.header_label.setText("No characters match current filters.")
                self.menu_label.setText("Filter:f  Quick:N  Setup:S  Advanced:R  Ack:A  Help:?  Quit:q")
            else:
                self.header_label.setText("No characters in DB yet. Use Setup (Shift-S) to fetch sources.")
                self.menu_label.setText("Setup:S  Advanced:R  Filter:f  Ack:A  Help:?  Quit:q")
            self.nav_strip.setText("")
            self.glyph_label.setText("?")
            self.glyph_meta.setText("")
            self._set_panel_text(self.jp_text, [])
            self._set_panel_text(self.cn_text, [])
            self._set_panel_text(self.sent_text, [])
            self._set_panel_text(self.var_text, [])
            self.context_label.setText(self._active_input_context())
            self.status_label.setText(self.state.message)
            fake_detail = {"cp": 0}
            self._sync_overlays(fake_detail)
            return

        cp = int(detail["cp"])
        idx = self.state.pos + 1
        total = len(self.state.ordered_cps)
        order_label = ORDERINGS[self.state.ordering_idx]
        if order_label == "freq" and self.state.current_freq_profile:
            order_label = f"freq:{self.state.current_freq_profile}"
        bookmark_marker = " *" if cp in self.state.bookmarked_cps else ""
        focus_label = f"  reading-sort:{self.state.focus.upper()}" if ORDERINGS[self.state.ordering_idx] == "reading" else ""
        romaji_label = "  JP-romaji:on" if self.state.show_jp_romaji else ""
        filtered_label = ""
        if self.state.hide_no_reading:
            filtered_label += "  hide-no-reading:on"
        if self.state.filter_state.is_active():
            filtered_label += "  filters:on"
        self.header_label.setText(
            f"{detail['ch']}{bookmark_marker} U+{cp:04X}  radical {detail['radical'] or '-'}  "
            f"strokes {detail['strokes'] or '-'}  ({idx}/{total}) order:{order_label}{focus_label}{romaji_label}{filtered_label}"
        )

        strip = build_strip(self.state.ordered_cps, self.state.pos, radius=10)
        nav = []
        for cell in strip:
            if cell.cp is None:
                nav.append('<span style="color:#777">·</span>')
            else:
                ch = chr(cell.cp)
                safe_ch = html.escape(ch)
                if cell.is_current:
                    nav.append(f'<span style="color:#00a0ff;font-weight:700">{safe_ch}</span>')
                else:
                    nav.append(safe_ch)
        self.nav_strip.setText(" ".join(nav))

        self.glyph_label.setText(detail["ch"])
        self.glyph_meta.setText(f"U+{cp:04X}")
        sent_rows = self._sentence_rows_for_detail(detail)
        main_related_layout = self._main_related_layout(detail, sentence_rows=sent_rows)
        selected_related_cp = self._selected_related_cp_for_detail(detail)
        active_main_row_idx: int | None = None
        if not self.state.show_phonetic and main_related_layout.rows:
            active_main_row_idx = self.state.related_row_idx

        if self.state.show_jp_romaji:
            on_parts = [search_normalize.kana_to_romaji(reading) for reading in detail["jp_on"]]
            kun_parts = [search_normalize.kana_to_romaji(reading) for reading in detail["jp_kun"]]
        else:
            on_parts = detail["jp_on"]
            kun_parts = detail["jp_kun"]
        on = " ".join(on_parts) if on_parts else "(none)"
        kun = " ".join(kun_parts) if kun_parts else "(none)"
        jp_gloss = "; ".join(detail["jp_gloss"][:3]) if detail["jp_gloss"] else "(none)"
        jp_lines = [f"Readings{' (romaji)' if self.state.show_jp_romaji else ''}: on {on} | kun {kun}", f"Gloss: {jp_gloss}", "Words:"]
        jp_html = [html.escape(line) for line in jp_lines]
        if detail["jp_words"]:
            for word_idx, (word, kana, gloss, rank) in enumerate(detail["jp_words"][:5]):
                reading = kana or "-"
                if self.state.show_jp_romaji and kana:
                    reading = search_normalize.kana_to_romaji(kana)
                line_row_idx = main_related_layout.jp_row_indexes[word_idx] if word_idx < len(main_related_layout.jp_row_indexes) else None
                line_active = active_main_row_idx is not None and line_row_idx == active_main_row_idx
                marker = "▶" if line_active else " "
                selectable = (
                    set(main_related_layout.rows[line_row_idx])
                    if line_row_idx is not None and line_row_idx < len(main_related_layout.rows)
                    else set()
                )
                styled_word = self._render_selectable_text(
                    word,
                    selectable=selectable,
                    selected_cp=selected_related_cp if line_active else None,
                )
                jp_lines.append(f"{marker} {rank}. {word}  {reading}  {gloss or '-'}")
                jp_html.append(
                    f"{html.escape(marker)} {rank}. {styled_word}  {html.escape(reading)}  {html.escape(gloss or '-')}"
                )
        else:
            jp_lines.append("  (no examples found)")
            jp_html.append(html.escape("  (no examples found)"))
        self._set_panel_text(self.jp_text, jp_lines, html_lines=jp_html)

        if detail["cn_readings"]:
            readings = "  ".join(
                (marked or search_normalize.pinyin_numbered_to_marked(numbered or "") or "-")
                for marked, numbered in detail["cn_readings"][:5]
            )
        else:
            readings = "(none)"
        cn_gloss = "; ".join(detail["cn_gloss"][:3]) if detail["cn_gloss"] else "(none)"
        cn_lines = [f"Readings: {readings}", f"Gloss: {cn_gloss}", "Words:"]
        cn_html = [html.escape(line) for line in cn_lines]
        if detail["cn_words"]:
            for word_idx, (trad, simp, marked, numbered, gloss, rank) in enumerate(detail["cn_words"][:5]):
                py = marked or search_normalize.pinyin_numbered_to_marked(numbered or "") or "-"
                line_row_idx = main_related_layout.cn_row_indexes[word_idx] if word_idx < len(main_related_layout.cn_row_indexes) else None
                line_active = active_main_row_idx is not None and line_row_idx == active_main_row_idx
                marker = "▶" if line_active else " "
                selectable = (
                    set(main_related_layout.rows[line_row_idx])
                    if line_row_idx is not None and line_row_idx < len(main_related_layout.rows)
                    else set()
                )
                styled_trad = self._render_selectable_text(
                    trad,
                    selectable=selectable,
                    selected_cp=selected_related_cp if line_active else None,
                )
                styled_simp = self._render_selectable_text(
                    simp,
                    selectable=selectable,
                    selected_cp=selected_related_cp if line_active else None,
                )
                cn_lines.append(f"{marker} {rank}. {trad}/{simp}  {py}  {gloss}")
                cn_html.append(
                    f"{html.escape(marker)} {rank}. {styled_trad}/{styled_simp}  {html.escape(py)}  {html.escape(gloss)}"
                )
        else:
            cn_lines.append("  (no examples found)")
            cn_html.append(html.escape("  (no examples found)"))
        self._set_panel_text(self.cn_text, cn_lines, html_lines=cn_html)

        langs = self.state.sentence_langs()
        sent_lines: list[str] = []
        sent_html: list[str] = []
        if sent_rows:
            for sent_idx, (lang, text, reading, gloss, source, license_name, rank) in enumerate(sent_rows):
                line_row_idx = (
                    main_related_layout.sentence_row_indexes[sent_idx]
                    if sent_idx < len(main_related_layout.sentence_row_indexes)
                    else None
                )
                line_active = active_main_row_idx is not None and line_row_idx == active_main_row_idx
                marker = "▶" if line_active else " "
                selectable = (
                    set(main_related_layout.rows[line_row_idx])
                    if line_row_idx is not None and line_row_idx < len(main_related_layout.rows)
                    else set()
                )
                styled_sentence = self._render_selectable_text(
                    text,
                    selectable=selectable,
                    selected_cp=selected_related_cp if line_active else None,
                )
                sent_lines.append(f"{marker} {rank}. [{lang}] {text}  {reading or '-'}  {gloss or '-'}")
                sent_html.append(
                    f"{html.escape(marker)} {rank}. [{html.escape(lang)}] {styled_sentence}  "
                    f"{html.escape(reading or '-')}  {html.escape(gloss or '-')}"
                )
                sent_lines.append(f"   source: {source or '-'} ({license_name or '-'})")
                sent_html.append(html.escape(f"   source: {source or '-'} ({license_name or '-'})"))
        else:
            hint = "(no sentence examples)"
            if self.state.derived_counts.get("sentences", 0) == 0:
                hint = "(no sentence examples; add sentences provider and rebuild DB)"
            sent_lines = [hint]
            sent_html = [html.escape(hint)]
        langs_label = "/".join(lang.upper() for lang in langs)
        self.jp_group.setTitle("JP [1]")
        self.cn_group.setTitle("CN [2]")
        self.sent_group.setTitle(f"Sentences [3] ({langs_label})")
        self._set_panel_text(self.sent_text, sent_lines, html_lines=sent_html)

        graph, targets = self._variant_data_for(cp)
        self.var_group.setTitle("Variants [4]")
        var_lines = [f"nodes={len(graph['nodes'])} edges={len(graph['edges'])}", "Arrows: select  Enter: jump"]
        if targets:
            for idx, target in enumerate(targets[:16]):
                jumpable = target.cp in self.state.ordered_cps
                marker = " "
                if idx == self.state.variant_idx:
                    marker = "▶" if jumpable else "X"
                var_lines.append(
                    f"{marker} {target.ch} U+{target.cp:04X}  {target.relation}"
                )
            if len(targets) > 16:
                var_lines.append(f"... +{len(targets) - 16} more")
        else:
            var_lines.append("(no variant targets)")
        self._set_panel_text(self.var_text, var_lines)

        self.jp_group.setVisible(self.state.show_jp)
        self.cn_group.setVisible(self.state.show_cn)
        self.sent_group.setVisible(self.state.show_sentences)
        self.var_group.setVisible(self.state.show_variants)

        self.state.ensure_panel_focus_valid()
        jp_focus = self.state.panel_focus == "jp"
        cn_focus = self.state.panel_focus == "cn"
        sent_focus = self.state.panel_focus == "sentences"
        var_focus = self.state.panel_focus == "variants"
        self.jp_group.setStyleSheet(self._focus_style(jp_focus))
        self.cn_group.setStyleSheet(self._focus_style(cn_focus))
        self.sent_group.setStyleSheet(self._focus_style(sent_focus))
        self.var_group.setStyleSheet(self._focus_style(var_focus))

        stroke_available = self.stroke_repo.has_char(detail["ch"])
        menu_line = (
            "Nav:<-/->/j/k order  Up/Down related  Shift-Left/Right same-line  Home End Tab Enter  Search:/  Radical:r  Panes:1 2 3 4  "
            "Overlays:c s p  User:b B n g u  JP:m  Filter:f N  CCAMC:i  Order:O F  Setup:S  Advanced:R  Ack:A"
        )
        if stroke_available:
            menu_line += "  Stroke:t"
        menu_line += "  Help:?  Quit:q"
        self.menu_label.setText(menu_line)
        self.context_label.setText(self._active_input_context())
        self.status_label.setText(self.state.message)

        self._sync_overlays(detail)

    def _open_search(self) -> None:
        dlg = SearchDialog(self.state, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_cp is not None:
            self.state.jump_to_cp(dlg.selected_cp)
        self.refresh_view()

    def _open_radicals(self) -> None:
        dlg = RadicalDialog(self.state, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_cp is not None:
            self.state.jump_to_cp(dlg.selected_cp)
        self.refresh_view()

    def _open_bookmarks(self) -> None:
        if self.state.user_store is None:
            self.state.message = "User workspace unavailable"
            self.refresh_view()
            return
        dlg = BookmarkDialog(self.state, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_cp is not None:
            self.state.jump_to_cp(dlg.selected_cp)
        else:
            self.state.message = "Closed bookmarks"
        self.refresh_view()

    def _open_note_editor(self, global_note: bool) -> None:
        if self.state.user_store is None:
            self.state.message = "User workspace unavailable"
            self.refresh_view()
            return
        if global_note:
            title = "Global Note"
            initial_text = ""
        else:
            title = "Glyph Note"
            initial_text = self.state.glyph_note_prefill()
        dlg = NoteEditorDialog(title=title, initial_text=initial_text, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.state.message = "Cancelled note entry"
            self.refresh_view()
            return
        text = dlg.editor.toPlainText()
        if global_note:
            self.state.save_global_note(text)
        else:
            self.state.save_glyph_note(text)
        self.refresh_view()

    def _open_ccamc(self) -> None:
        url = self.state.current_ccamc_url()
        if not url:
            return
        webbrowser.open(url)
        cp = self.state.current_cp
        if cp is not None:
            self.state.message = f"Opened CCAMC for {chr(cp)}"
        self.refresh_view()

    def _dismiss_startup_overlay(self) -> None:
        if not self.show_startup_overlay:
            return
        self.show_startup_overlay = False
        if self.state.user_store is not None:
            self.state.user_store.set_flag("startup_seen", True)

    def _set_show_startup_on_launch(self, enabled: bool) -> None:
        self.show_startup_on_launch = bool(enabled)
        if self.state.user_store is not None:
            self.state.user_store.set_show_startup_on_launch(self.show_startup_on_launch)
        self.state.message = f"Show startup on launch: {'on' if self.show_startup_on_launch else 'off'}"
        self.refresh_view()

    def _init_font_warning_overlay(self) -> None:
        meta = db_query.get_build_meta(self.state.conn)
        self.build_meta = meta
        lines = font_warning_lines(meta, self.runtime_font)
        if not lines:
            self.show_font_warning_overlay = False
            self.font_warning_lines = []
            self.font_warning_flag = ""
            return
        self.font_warning_flag = font_warning_flag_key(meta, self.runtime_font)
        self.font_warning_lines = lines
        dismissed = False
        allow_persist = font_warning_allows_persistent_dismiss(meta, self.runtime_font)
        if allow_persist and self.state.user_store is not None and self.font_warning_flag:
            dismissed = self.state.user_store.get_flag(self.font_warning_flag, default=False)
        self.show_font_warning_overlay = not dismissed

    def _dismiss_font_warning_overlay(self, persist: bool = True) -> None:
        if not self.show_font_warning_overlay:
            return
        self.show_font_warning_overlay = False
        if persist and self.state.user_store is not None and self.font_warning_flag:
            self.state.user_store.set_flag(self.font_warning_flag, True)

    def _handle_font_warning_overlay_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        text = event.text()
        if key in (Qt.Key.Key_Escape,) or text in {"d", "D"}:
            self._dismiss_font_warning_overlay(persist=True)
            self.refresh_view()
            return True
        if text in {"n", "N"}:
            webbrowser.open(NOTO_CJK_URL)
            self.state.message = "Opened Noto CJK fonts page"
            self.refresh_view()
            return True
        if text in {"b", "B"}:
            webbrowser.open(BABELSTONE_HAN_URL)
            self.state.message = "Opened BabelStone Han page"
            self.refresh_view()
            return True
        if text in {"r", "R"}:
            font_spec = (self.runtime_font or "").strip() or self._default_build_font_spec()
            ok = self._run_advanced_rebuild(use_font_filter=True, font_spec=font_spec)
            if ok:
                self._dismiss_font_warning_overlay(persist=False)
                self._init_font_warning_overlay()
                if self.show_font_warning_overlay:
                    self.state.message = "Rebuild complete; font warning still applies"
                else:
                    self.state.message = f"Rebuild complete with font filter: {font_spec}"
            else:
                self.state.message = "Font-warning rebuild failed"
            self.refresh_view()
            return True
        return False

    def _available_sources(self) -> dict[str, bool]:
        return detect_available_sources(self.runtime_paths)

    def _ack_lines(self) -> list[str]:
        return acknowledgements_for_sources(self._available_sources())

    def _default_build_font_spec(self) -> str:
        ui = (self.ui_font_family or "").strip()
        if ui:
            return ui
        return default_build_font()

    def _after_setup_download(
        self,
        results: dict[str, str],
        progress: Callable[[str], None] | None = None,
        font: str | None = None,
    ) -> None:
        ok = sum(1 for status in results.values() if status == "ok")
        fail = sum(1 for status in results.values() if status != "ok")
        self.stroke_repo = StrokeOrderRepository(root=self.runtime_paths.strokeorder_dir)
        db_path = self._current_db_path()
        if db_path is None:
            self.state.message = "Setup download completed, but auto-build skipped (no DB path)."
            self.refresh_view()
            return

        current_cp = self.state.current_cp
        auto_build_ok = False
        try:
            if font and progress is not None:
                progress(f"Using font filter for setup auto-build: {font}")
            if progress is not None:
                progress("Starting automatic DB rebuild ...")
            try:
                self.state.conn.close()
            except Exception:
                pass
            _ = rebuild_database_from_sources(
                paths=self.runtime_paths,
                db_path=db_path,
                progress=progress,
                font=font,
            )
            auto_build_ok = True
        except Exception as exc:  # noqa: BLE001
            self.state.message = f"Setup download completed, auto-build failed: {exc}"
        finally:
            self.state.conn = connect_db(db_path)
            self.state.reload_db_state(current_cp=current_cp)
            self._init_font_warning_overlay()
        if auto_build_ok:
            mode = " + font-filter build" if font else ""
            self.state.message = f"Setup download + auto-build{mode} completed: ok={ok} failed={fail}"
        self.refresh_view()

    def _run_advanced_rebuild(
        self,
        *,
        use_font_filter: bool,
        font_spec: str,
        progress: Callable[[str], None] | None = None,
    ) -> bool:
        db_path = self._current_db_path()
        if db_path is None:
            self.state.message = "Advanced rebuild skipped (no DB path)."
            self.refresh_view()
            return False

        font = None
        if use_font_filter:
            font = font_spec.strip() or default_build_font()
            if progress is not None:
                progress(f"Rebuild font filter enabled: {font}")
        elif progress is not None:
            progress("Rebuild font filter disabled")

        current_cp = self.state.current_cp
        ok = False
        try:
            if progress is not None:
                progress("Starting advanced DB rebuild ...")
            try:
                self.state.conn.close()
            except Exception:
                pass
            _ = rebuild_database_from_sources(
                paths=self.runtime_paths,
                db_path=db_path,
                progress=progress,
                font=font,
            )
            ok = True
            self.state.message = "Advanced rebuild complete"
        except Exception as exc:  # noqa: BLE001
            if progress is not None:
                progress(f"Advanced rebuild failed: {exc}")
            self.state.message = f"Advanced rebuild failed: {exc}"
        finally:
            self.state.conn = connect_db(db_path)
            self.state.reload_db_state(current_cp=current_cp)
            self._init_font_warning_overlay()
        self.refresh_view()
        return ok

    def _current_db_path(self) -> Path | None:
        row = self.state.conn.execute("PRAGMA database_list").fetchone()
        if row is None:
            return None
        raw = str(row[2] or "").strip()
        if not raw:
            return None
        return Path(raw)

    def _open_setup_dialog(self) -> None:
        self._dismiss_startup_overlay()
        dlg = SetupDialog(self, self)
        dlg.exec()
        self.refresh_view()

    def _open_advanced_dialog(self) -> None:
        dlg = AdvancedRebuildDialog(self, self)
        dlg.exec()
        self.refresh_view()

    def _open_filter_dialog(self) -> None:
        dlg = FilterDialog(self, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh_view()
        else:
            self.state.message = "Closed filter menu"
            self.refresh_view()

    def _stroke_available_for_current(self) -> bool:
        cp = self.state.current_cp
        if cp is None:
            return False
        return self.stroke_repo.has_char(chr(cp))

    def _open_stroke_window(self) -> None:
        cp = self.state.current_cp
        if cp is None:
            self.state.message = "No current character"
            self.refresh_view()
            return
        ch = chr(cp)
        data = self.stroke_repo.load(ch)
        if data is None:
            self.state.message = f"No stroke animation data for {ch}"
            self.refresh_view()
            return
        if self._stroke_window is not None:
            self._stroke_window.close()
            self._stroke_window = None
        dlg = StrokeAnimationDialog(data, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        def _clear_ref() -> None:
            self._stroke_window = None

        dlg.destroyed.connect(_clear_ref)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self._stroke_window = dlg
        self.state.message = f"Stroke animation: {ch}"
        self.refresh_view()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.refresh_view()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Ensure overlays are synced after the main window becomes visible.
        QTimer.singleShot(0, self.refresh_view)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        text = event.text()
        self._dismiss_startup_overlay()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_Left:
                _ = self._move_related_selection_horizontal(-1)
                self.refresh_view()
                event.accept()
                return
            if key == Qt.Key.Key_Right:
                _ = self._move_related_selection_horizontal(+1)
                self.refresh_view()
                event.accept()
                return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.state.panel_focus == "variants" and self.state.show_variants:
                self._jump_to_selected_variant()
                self.refresh_view()
                event.accept()
                return
            if self._jump_to_selected_related():
                self.refresh_view()
                event.accept()
                return
            super().keyPressEvent(event)
            return

        if text in ("j", "J"):
            if self.state.panel_focus == "variants" and self.state.show_variants:
                moved = self._move_variant_selection(+1)
                if not moved:
                    self.state.move_next()
            else:
                self.state.move_next()
        elif text in ("k", "K"):
            if self.state.panel_focus == "variants" and self.state.show_variants:
                moved = self._move_variant_selection(-1)
                if not moved:
                    self.state.move_prev()
            else:
                self.state.move_prev()
        elif key == Qt.Key.Key_Tab:
            self._cycle_panel_focus_and_sync_related()
        elif text in ("o", "O"):
            self.state.cycle_ordering()
        elif text == "f":
            self._open_filter_dialog()
            return
        elif text == "F":
            self.state.cycle_freq_profile()
        elif text == "1":
            self.state.show_jp = not self.state.show_jp
            if self.state.hide_no_reading:
                self.state.refresh_ordering()
            self.state.ensure_panel_focus_valid()
        elif text == "2":
            self.state.show_cn = not self.state.show_cn
            if self.state.hide_no_reading:
                self.state.refresh_ordering()
            self.state.ensure_panel_focus_valid()
        elif text == "3":
            self.state.show_sentences = not self.state.show_sentences
            self.state.ensure_panel_focus_valid()
        elif text in ("4", "v", "V"):
            self.state.show_variants = not self.state.show_variants
            self.state.ensure_panel_focus_valid()
        elif text in ("p", "P"):
            self.state.show_provenance = not self.state.show_provenance
        elif text in ("c", "C"):
            self.state.show_components = not self.state.show_components
            if self.state.show_components:
                self.state.show_phonetic = False
        elif text == "s":
            self.state.show_phonetic = not self.state.show_phonetic
            if self.state.show_phonetic:
                self.state.show_components = False
                self.state.related_row_idx = 0
                self.state.related_col_idx = 0
        elif text in ("u", "U"):
            self.state.show_user_overlay = not self.state.show_user_overlay
        elif text in ("m", "M"):
            self.state.show_jp_romaji = not self.state.show_jp_romaji
            self.state.message = f"JP romaji: {'on' if self.state.show_jp_romaji else 'off'}"
        elif text == "N":
            self.state.toggle_no_reading()
        elif text in ("b", "B"):
            if text == "b":
                self.state.toggle_bookmark()
            else:
                self._open_bookmarks()
                return
        elif text == "n":
            self._open_note_editor(global_note=False)
            return
        elif text in ("g", "G"):
            self._open_note_editor(global_note=True)
            return
        elif text in ("i", "I"):
            self._open_ccamc()
            return
        elif text == "/":
            self._open_search()
            return
        elif text == "r":
            self._open_radicals()
            return
        elif text == "R":
            self._open_advanced_dialog()
            return
        elif text == "S":
            self._open_setup_dialog()
            return
        elif text == "A":
            self.show_ack_overlay = not self.show_ack_overlay
        elif text in ("t", "T"):
            self._open_stroke_window()
            return
        elif text == "?":
            self.state.show_help = not self.state.show_help
        elif text in ("q", "Q"):
            self.close()
            return
        else:
            super().keyPressEvent(event)
            return

        self.refresh_view()
        event.accept()


def run_gui(
    conn: sqlite3.Connection,
    normalizer_name: str = "default",
    user_store: UserStore | None = None,
    ui_font_family: str | None = None,
) -> None:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([])
    family = resolve_gui_font_family(ui_font_family)
    app.setFont(QFont(family, 16))
    state = GuiState(conn, normalizer_name=normalizer_name, user_store=user_store)
    win = KanjiGuiWindow(state, ui_font_family=family)
    win.show()
    if owns_app:
        app.exec()
