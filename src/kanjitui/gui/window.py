from __future__ import annotations

import html
import math
import sqlite3
import webbrowser
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kanjitui.db import query as db_query
from kanjitui.db.user import UserStore
from kanjitui.gui.state import GuiState, ORDERINGS
from kanjitui.search import normalize as search_normalize
from kanjitui.variant_nav import VariantTarget, build_variant_targets
from kanjitui.tui.navigation import build_strip
from kanjitui.tui.radicals import kangxi_radical_glyph


class LiveTextDialog(QDialog):
    def __init__(self, title: str, on_close: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_close = on_close
        self.setWindowTitle(title)
        self.resize(820, 420)

        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Noto Sans Mono CJK", 14))
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
        self.query.setFont(QFont("Noto Sans Mono CJK", 14))
        layout.addWidget(self.query)

        self.hint = QLabel("Enter: run/jump   Esc: close   Up/Down: select   Home/End: top/bottom", self)
        self.hint.setFont(QFont("Noto Sans Mono CJK", 12))
        layout.addWidget(self.hint)

        self.results = QListWidget(self)
        self.results.setFont(QFont("Noto Sans Mono CJK", 14))
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
        hint = QLabel("Enter: jump   Esc: close", self)
        hint.setFont(QFont("Noto Sans Mono CJK", 12))
        layout.addWidget(hint)

        self.results = QListWidget(self)
        self.results.setFont(QFont("Noto Sans Mono CJK", 14))
        layout.addWidget(self.results)

        row = QHBoxLayout()
        self.jump_btn = QPushButton("Jump", self)
        self.close_btn = QPushButton("Close", self)
        row.addWidget(self.jump_btn)
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
        self.editor.setFont(QFont("Noto Sans Mono CJK", 14))
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


class RadicalDialog(QDialog):
    def __init__(self, state: GuiState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.selected_cp: int | None = None
        self.setWindowTitle("Radical Browser")
        self.resize(900, 560)

        root = QVBoxLayout(self)

        self.info = QLabel("Enter on radical: select radical   Enter on result: jump", self)
        self.info.setFont(QFont("Noto Sans Mono CJK", 12))
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
        self.grid.setFont(QFont("Noto Sans Mono CJK", 14))
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
        self.stroke_label.setFont(QFont("Noto Sans Mono CJK", 12))
        self.stroke_prev = QPushButton("[", self)
        self.stroke_next = QPushButton("]", self)
        stroke_row.addWidget(self.stroke_label)
        stroke_row.addWidget(self.stroke_prev)
        stroke_row.addWidget(self.stroke_next)
        right.addLayout(stroke_row)

        self.results = QListWidget(self)
        self.results.setFont(QFont("Noto Sans Mono CJK", 14))
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


class KanjiGuiWindow(QMainWindow):
    def __init__(self, state: GuiState) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("kanjigui")
        self.resize(1460, 980)
        self.setMinimumSize(1100, 760)
        self._overlays: dict[str, LiveTextDialog] = {}
        self._variant_cache_cp: int | None = None
        self._variant_graph: dict | None = None
        self._variant_targets: list[VariantTarget] = []
        self._build_ui()
        self.refresh_view()

    def _build_panel(self, title: str) -> tuple[QGroupBox, QPlainTextEdit]:
        box = QGroupBox(title, self)
        box.setFont(QFont("Noto Sans Mono CJK", 16))
        layout = QVBoxLayout(box)
        text = QPlainTextEdit(box)
        text.setReadOnly(True)
        text.setFont(QFont("Noto Sans Mono CJK", 16))
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
        self.header_label.setFont(QFont("Noto Sans Mono CJK", 16, QFont.Weight.Bold))
        self.header_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.header_label, 0, 0)

        self.nav_strip = QLabel(self)
        self.nav_strip.setFont(QFont("Noto Sans Mono CJK", 18))
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
        self.glyph_label.setFont(QFont("Noto Sans CJK JP", 56))
        self.glyph_label.setMinimumWidth(280)
        self.glyph_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        right_layout.addWidget(self.glyph_label)

        self.glyph_meta = QLabel(self)
        self.glyph_meta.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.glyph_meta.setFont(QFont("Noto Sans Mono CJK", 16))
        self.glyph_meta.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        right_layout.addWidget(self.glyph_meta)
        right_layout.addStretch(1)
        grid.addWidget(right, 0, 1, 3, 1)

        self.menu_label = QLabel(self)
        self.menu_label.setFont(QFont("Noto Sans Mono CJK", 13, QFont.Weight.Bold))
        self.menu_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.menu_label, 3, 0, 1, 2)

        self.status_label = QLabel(self)
        self.status_label.setFont(QFont("Noto Sans Mono CJK", 14))
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

    def _sync_overlay(self, key: str, enabled: bool, title: str, lines: list[str], attr_name: str) -> None:
        dlg = self._overlays.get(key)
        if not enabled:
            if dlg is not None:
                dlg.close()
                self._overlays.pop(key, None)
            return

        if dlg is None:
            def _on_close() -> None:
                setattr(self.state, attr_name, False)
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
                "Filter: Shift-N toggles hide-no-reading",
                "Search: / open, Enter run/jump, Up/Down select",
                "Radicals: r open browser",
                "Panels: 1 JP, 2 CN, 3 Sentences, 4 Variants",
                "Tab: cycle focus JP/CN/Variants",
                "Overlays: c Components, s Phonetics, p Provenance, u User panel",
                "Workspace: b toggle bookmark, B bookmarks list/jump",
                "Notes: n per-glyph editor, g global editor",
                "Editor: Enter newline, Save button commits",
                "CCAMC: i open glyph page",
                "Global: ? Help, q Quit",
            ],
            "show_help",
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
            "show_provenance",
        )

        comp = db_query.get_components(self.state.conn, cp)
        comp_lines = [f"{idx + 1}. {ch} U+{ccp:04X}" for idx, (ccp, ch) in enumerate(comp)] or ["(no components)"]
        self._sync_overlay(
            "components",
            self.state.show_components,
            "Components",
            comp_lines,
            "show_components",
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
            "show_phonetic",
        )

        self._sync_overlay(
            "user",
            self.state.show_user_overlay,
            "User Workspace",
            self._format_user_overlay(cp),
            "show_user_overlay",
        )

    def refresh_view(self) -> None:
        detail = self._current_detail()
        if detail is None:
            self.header_label.setText("No characters in DB. Build and rerun.")
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
        filtered_label = "  hide-no-reading:on" if self.state.hide_no_reading else ""
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
                marker = "▶" if idx == self.state.variant_idx else " "
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

        self.menu_label.setText(
            "Nav:<-/->/j/k Home End Tab Enter  Search:/  Radical:r  Panes:1 2 3 4  "
            "Overlays:c s p  User:b B n g u  JP:m  Filter:N  CCAMC:i  Order:O F  Help:?  Quit:q"
        )
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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        text = event.text()

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
        elif text in ("s", "S"):
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


def run_gui(conn: sqlite3.Connection, normalizer_name: str = "default", user_store: UserStore | None = None) -> None:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([])
    state = GuiState(conn, normalizer_name=normalizer_name, user_store=user_store)
    win = KanjiGuiWindow(state)
    win.show()
    if owns_app:
        app.exec()
