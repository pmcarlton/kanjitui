from __future__ import annotations

import html
import math
import os
from pathlib import Path
import re
import sqlite3
import webbrowser
from typing import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeyEvent, QKeySequence, QShortcut, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QVBoxLayout,
    QWidget,
)

from kanjitui.db import query as db_query
from kanjitui.db.query import connect as connect_db
from kanjitui.db.user import UserStore
from kanjitui.filtering import FilterState, apply_filter_state, filter_group_specs
from kanjitui.gui.state import GuiState, ORDERINGS
from kanjitui.search import normalize as search_normalize
from kanjitui.setup_resources import (
    SOURCE_ORDER,
    SOURCES,
    acknowledgements_for_sources,
    default_setup_selection,
    detect_available_sources,
    download_selected_sources,
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
    def __init__(self, title: str, on_close: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_close = on_close
        self.setWindowTitle(title)
        self.resize(820, 420)

        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFont(ui_font(self, 14))
        layout.addWidget(self.text)

    def set_lines(self, lines: list[str]) -> None:
        self.text.setPlainText("\n".join(lines))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._on_close()
        super().closeEvent(event)


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
        self.setWindowTitle("Bookmarks")
        self.resize(760, 460)

        layout = QVBoxLayout(self)
        hint = QLabel("Enter: jump   x: delete   Esc: close", self)
        hint.setFont(ui_font(self, 12))
        layout.addWidget(hint)

        self.results = QListWidget(self)
        self.results.setFont(ui_font(self, 14))
        layout.addWidget(self.results)

        row = QHBoxLayout()
        self.jump_btn = QPushButton("Jump", self)
        self.delete_btn = QPushButton("Delete", self)
        self.close_btn = QPushButton("Close", self)
        row.addWidget(self.jump_btn)
        row.addWidget(self.delete_btn)
        row.addWidget(self.close_btn)
        layout.addLayout(row)

        bookmarks = self.state.list_bookmarks(limit=1000)
        for cp, tag in bookmarks:
            label = f"{chr(cp)} U+{cp:04X}"
            if tag:
                label += f" [{tag}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cp)
            self.results.addItem(item)
        if self.results.count() > 0:
            self.results.setCurrentRow(0)

        self.results.itemDoubleClicked.connect(lambda _: self.accept_selected())
        self.results.itemActivated.connect(lambda _: self.accept_selected())
        self.jump_btn.clicked.connect(self.accept_selected)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.close_btn.clicked.connect(self.reject)

    def accept_selected(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        cp = item.data(Qt.ItemDataRole.UserRole)
        if cp is None:
            return
        self.selected_cp = int(cp)
        self.accept()

    def delete_selected(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        cp = item.data(Qt.ItemDataRole.UserRole)
        if cp is None:
            return
        row = self.results.row(item)
        if self.state.delete_bookmark(int(cp)):
            self.results.takeItem(row)
            if self.results.count() <= 0:
                self.reject()
                return
            self.results.setCurrentRow(max(0, min(row, self.results.count() - 1)))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        text = event.text()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_selected()
            return
        if text in ("x", "X"):
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
        self.window._after_setup_download(results, progress=_progress)
        self.progress.setValue(total_steps)
        self._append(self.window.state.message)
        self.download_btn.setEnabled(True)


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
        stroke_row = QHBoxLayout()
        self.stroke_label = QLabel("strokes=all", self)
        self.stroke_label.setFont(ui_font(self, 12))
        self.stroke_prev = QPushButton("[", self)
        self.stroke_next = QPushButton("]", self)
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

        self.stroke_prev.clicked.connect(lambda: self._adjust_stroke(-1))
        self.stroke_next.clicked.connect(lambda: self._adjust_stroke(+1))
        self.grid.cellDoubleClicked.connect(lambda r, c: self._activate_radical_cell(r, c))
        self.results.itemDoubleClicked.connect(lambda _: self.accept_selected())
        self.jump_btn.clicked.connect(self.accept_selected)
        self.cancel_btn.clicked.connect(self.reject)

        start_row = self.state.radical_idx // self.state.radical_grid_cols
        start_col = self.state.radical_idx % self.state.radical_grid_cols
        self.grid.setCurrentCell(start_row, start_col)
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
        if text == "[":
            self._adjust_stroke(-1)
            return
        if text == "]":
            self._adjust_stroke(+1)
            return
        if key in (Qt.Key.Key_Backspace,):
            self.results.clear()
            self.state.radical_results = None
            self.state.radical_selected = None
            self.state.radical_stroke_options = [None]
            self.state.radical_stroke_idx = 0
            self.stroke_label.setText("strokes=all")
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
        if self.state.user_store is not None:
            self.show_startup_overlay = not self.state.user_store.get_flag("startup_seen", default=False)
        else:
            self.show_startup_overlay = True
        self._stroke_window: StrokeAnimationDialog | None = None
        self._build_ui()
        self.refresh_view()

    def _build_panel(self, title: str) -> tuple[QGroupBox, QPlainTextEdit]:
        box = QGroupBox(title, self)
        box.setFont(ui_font(self, 16))
        layout = QVBoxLayout(box)
        text = QPlainTextEdit(box)
        text.setReadOnly(True)
        text.setFont(ui_font(self, 16))
        layout.addWidget(text)
        return box, text

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

        self.status_label = QLabel(self)
        self.status_label.setFont(ui_font(self, 14))
        self.status_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.status_label, 4, 0, 1, 2)

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
            (Qt.Key.Key_Down, self._shortcut_move_next),
            (Qt.Key.Key_Left, self._shortcut_move_prev),
            (Qt.Key.Key_Up, self._shortcut_move_prev),
            (Qt.Key.Key_Home, self._shortcut_move_home),
            (Qt.Key.Key_End, self._shortcut_move_end),
        ]
        for key, handler in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            self._nav_shortcuts.append(shortcut)

    def _shortcut_move_next(self) -> None:
        if self.state.panel_focus == "variants" and self.state.show_variants:
            moved = self._move_variant_selection(+1)
            if not moved:
                self.state.move_next()
        else:
            self.state.move_next()
        self.refresh_view()

    def _shortcut_move_prev(self) -> None:
        if self.state.panel_focus == "variants" and self.state.show_variants:
            moved = self._move_variant_selection(-1)
            if not moved:
                self.state.move_prev()
        else:
            self.state.move_prev()
        self.refresh_view()

    def _shortcut_move_home(self) -> None:
        if self.state.panel_focus == "variants" and self.state.show_variants:
            cp = self.state.current_cp
            if cp is not None:
                _graph, targets = self._variant_data_for(cp)
                self.state.move_variant_home(len(targets))
        else:
            self.state.move_home()
        self.refresh_view()

    def _shortcut_move_end(self) -> None:
        if self.state.panel_focus == "variants" and self.state.show_variants:
            cp = self.state.current_cp
            if cp is not None:
                _graph, targets = self._variant_data_for(cp)
                self.state.move_variant_end(len(targets))
        else:
            self.state.move_end()
        self.refresh_view()

    def _focus_style(self, active: bool) -> str:
        if active:
            return "QGroupBox{border:3px double #444; margin-top: 8px;} QGroupBox::title{subcontrol-origin: margin; left: 8px; padding:0 3px;}"
        return "QGroupBox{border:1px solid #666; margin-top: 8px;} QGroupBox::title{subcontrol-origin: margin; left: 8px; padding:0 3px;}"

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

    def _format_user_overlay(self, cp: int) -> list[str]:
        if self.state.user_store is None:
            return ["(user store unavailable)"]
        glyph_notes = self.state.user_store.get_glyph_notes(cp, limit=4)
        global_notes = self.state.user_store.get_global_notes(limit=4)
        bookmarks = self.state.user_store.list_bookmarks(limit=6)
        queries = self.state.user_store.recent_queries(limit=4)
        lines = ["Glyph notes:"]
        lines.extend([f"- {note}" for note in glyph_notes] or ["(none)"])
        lines.append("")
        lines.append("Global notes:")
        lines.extend([f"- {note}" for note in global_notes] or ["(none)"])
        lines.append("")
        lines.append("Bookmarks:")
        lines.extend([f"- {chr(bcp)} U+{bcp:04X} {f'[{tag}]' if tag else ''}" for bcp, tag in bookmarks[:3]] or ["(none)"])
        lines.append("")
        lines.append("Recent queries:")
        lines.extend([f"- {q}" for q in queries[:3]] or ["(none)"])
        return lines

    def _sync_overlay(
        self,
        key: str,
        enabled: bool,
        title: str,
        lines: list[str],
        on_close: Callable[[], None] | None = None,
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

            dlg = LiveTextDialog(title, _on_close, self)
            dlg.show()
            self._overlays[key] = dlg
        dlg.setWindowTitle(title)
        dlg.set_lines(lines)
        dlg.raise_()

    def _sync_overlays(self, detail: dict) -> None:
        cp = int(detail["cp"])
        self._sync_overlay(
            "help",
            self.state.show_help,
            "Help",
            [
                "Navigation: <-/->/j/k, Home/End, Tab panel focus",
                "Ordering: O cycle ordering, F cycle freq profile",
                "JP panel: m toggles kana/romaji",
                "Filter: f opens menu; presets can be saved/loaded/deleted",
                "Quick filter: Shift-N toggles hide-no-reading",
                "Search: / open, Enter run/jump, Up/Down select",
                "Radicals: r open browser",
                "Panels: 1 JP, 2 CN, 3 Sentences, 4 Variants",
                "Tab: cycle focus JP/CN/Variants",
                "Overlays: c Components, s Phonetics, p Provenance, u User panel",
                "Workspace: b toggle bookmark, B bookmarks list/jump",
                "Bookmarks list: x deletes selected bookmark",
                "Notes: n per-glyph editor, g global editor",
                "Editor: Enter newline, Save button commits",
                "Setup: Shift-S source setup/download menu",
                "Acknowledgements: Shift-A overlay",
                "Stroke order: t popup (only when data exists)",
                "CCAMC: i open glyph page",
                "Global: ? Help, q Quit",
            ],
            on_close=lambda: setattr(self.state, "show_help", False),
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
        )

        comp = db_query.get_components(self.state.conn, cp)
        comp_lines = [f"{idx + 1}. {ch} U+{ccp:04X}" for idx, (ccp, ch) in enumerate(comp)] or ["(no components)"]
        self._sync_overlay(
            "components",
            self.state.show_components,
            "Components",
            comp_lines,
            on_close=lambda: setattr(self.state, "show_components", False),
        )

        ph = db_query.get_phonetic_series(self.state.conn, cp, limit=120)
        ph_lines: list[str] = []
        for idx, (member_cp, member_ch, key, pinyin_marked, pinyin_numbered) in enumerate(ph):
            pinyin = pinyin_marked or search_normalize.pinyin_numbered_to_marked(pinyin_numbered)
            row = f"{idx + 1}. {member_ch} U+{member_cp:04X} [{key}]"
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
        )

        self._sync_overlay(
            "user",
            self.state.show_user_overlay,
            "User Workspace",
            self._format_user_overlay(cp),
            on_close=lambda: setattr(self.state, "show_user_overlay", False),
        )

        self._sync_overlay(
            "ack",
            self.show_ack_overlay,
            "Acknowledgements",
            self._ack_lines(),
            on_close=lambda: setattr(self, "show_ack_overlay", False),
        )
        startup_lines = [
            "Welcome to kanjigui.",
            "Press any key to dismiss this page.",
            "Shift-S opens setup/download menu.",
            "Shift-A reopens acknowledgements.",
            "",
        ] + self._ack_lines()
        self._sync_overlay(
            "startup",
            self.show_startup_overlay,
            "Startup",
            startup_lines,
            on_close=self._dismiss_startup_overlay,
        )

    def refresh_view(self) -> None:
        detail = self._current_detail()
        if detail is None:
            self.header_label.setText("No characters in DB yet. Use Setup (Shift-S) to fetch sources.")
            self.nav_strip.setText("")
            self.glyph_label.setText("?")
            self.glyph_meta.setText("")
            self.jp_text.setPlainText("")
            self.cn_text.setPlainText("")
            self.sent_text.setPlainText("")
            self.var_text.setPlainText("")
            self.menu_label.setText("Setup:S  Filter:f  Ack:A  Help:?  Quit:q")
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
        if detail["jp_words"]:
            for word, kana, gloss, rank in detail["jp_words"][:5]:
                reading = kana or "-"
                if self.state.show_jp_romaji and kana:
                    reading = search_normalize.kana_to_romaji(kana)
                jp_lines.append(f"  {rank}. {word}  {reading}  {gloss or '-'}")
        else:
            jp_lines.append("  (no examples found)")
        self.jp_text.setPlainText("\n".join(jp_lines))

        if detail["cn_readings"]:
            readings = "  ".join(
                (marked or search_normalize.pinyin_numbered_to_marked(numbered or "") or "-")
                for marked, numbered in detail["cn_readings"][:5]
            )
        else:
            readings = "(none)"
        cn_gloss = "; ".join(detail["cn_gloss"][:3]) if detail["cn_gloss"] else "(none)"
        cn_lines = [f"Readings: {readings}", f"Gloss: {cn_gloss}", "Words:"]
        if detail["cn_words"]:
            for trad, simp, marked, numbered, gloss, rank in detail["cn_words"][:5]:
                py = marked or search_normalize.pinyin_numbered_to_marked(numbered or "") or "-"
                cn_lines.append(f"  {rank}. {trad}/{simp}  {py}  {gloss}")
        else:
            cn_lines.append("  (no examples found)")
        self.cn_text.setPlainText("\n".join(cn_lines))

        langs = self.state.sentence_langs()
        sent_limit = 6 if len(langs) > 1 else 3
        sent_rows = db_query.get_sentences(self.state.conn, cp, limit=sent_limit, langs=langs)
        sent_lines: list[str] = []
        if sent_rows:
            for lang, text, reading, gloss, source, license_name, rank in sent_rows:
                sent_lines.append(f"{rank}. [{lang}] {text}  {reading or '-'}  {gloss or '-'}")
                sent_lines.append(f"   source: {source or '-'} ({license_name or '-'})")
        else:
            hint = "(no sentence examples)"
            if self.state.derived_counts.get("sentences", 0) == 0:
                hint = "(no sentence examples; add sentences provider and rebuild DB)"
            sent_lines = [hint]
        langs_label = "/".join(lang.upper() for lang in langs)
        self.jp_group.setTitle("JP [1]")
        self.cn_group.setTitle("CN [2]")
        self.sent_group.setTitle(f"Sentences [3] ({langs_label})")
        self.sent_text.setPlainText("\n".join(sent_lines))

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
        self.var_text.setPlainText("\n".join(var_lines))

        self.jp_group.setVisible(self.state.show_jp)
        self.cn_group.setVisible(self.state.show_cn)
        self.sent_group.setVisible(self.state.show_sentences)
        self.var_group.setVisible(self.state.show_variants)

        self.state.ensure_panel_focus_valid()
        jp_focus = self.state.panel_focus == "jp"
        cn_focus = self.state.panel_focus == "cn"
        var_focus = self.state.panel_focus == "variants"
        self.jp_group.setStyleSheet(self._focus_style(jp_focus))
        self.cn_group.setStyleSheet(self._focus_style(cn_focus))
        self.sent_group.setStyleSheet(self._focus_style(False))
        self.var_group.setStyleSheet(self._focus_style(var_focus))

        stroke_available = self.stroke_repo.has_char(detail["ch"])
        menu_line = (
            "Nav:<-/->/j/k Home End Tab Enter  Search:/  Radical:r  Panes:1 2 3 4  "
            "Overlays:c s p  User:b B n g u  JP:m  Filter:f N  CCAMC:i  Order:O F  Setup:S  Ack:A"
        )
        if stroke_available:
            menu_line += "  Stroke:t"
        menu_line += "  Help:?  Quit:q"
        self.menu_label.setText(menu_line)
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

    def _available_sources(self) -> dict[str, bool]:
        return detect_available_sources(self.runtime_paths)

    def _ack_lines(self) -> list[str]:
        return acknowledgements_for_sources(self._available_sources())

    def _after_setup_download(
        self,
        results: dict[str, str],
        progress: Callable[[str], None] | None = None,
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
            )
            auto_build_ok = True
        except Exception as exc:  # noqa: BLE001
            self.state.message = f"Setup download completed, auto-build failed: {exc}"
        finally:
            self.state.conn = connect_db(db_path)
            self.state.reload_db_state(current_cp=current_cp)
        if auto_build_ok:
            self.state.message = f"Setup download + auto-build completed: ok={ok} failed={fail}"
        self.refresh_view()

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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        text = event.text()
        self._dismiss_startup_overlay()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.state.panel_focus == "variants" and self.state.show_variants:
                self._jump_to_selected_variant()
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
            self.state.toggle_focus()
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
        elif text in ("r", "R"):
            self._open_radicals()
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
