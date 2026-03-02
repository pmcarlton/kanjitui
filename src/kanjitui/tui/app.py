from __future__ import annotations

import curses
from pathlib import Path
import sqlite3
import webbrowser
from urllib.parse import quote

from kanjitui.db import query as db_query
from kanjitui.db.query import connect as connect_db
from kanjitui.db.user import UserStore
from kanjitui.search import normalize as search_normalize
from kanjitui.search.query import SearchEngine
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
from kanjitui.strokeorder import StrokeOrderData, StrokeOrderRepository, build_tui_stroke_frames
from kanjitui.tui.navigation import build_strip, move_grid_index, visible_window
from kanjitui.tui.radicals import all_kangxi_radical_numbers, kangxi_radical_glyph
from kanjitui.tui.router import KeyInput, KeyRouter
from kanjitui.variant_nav import VariantTarget, build_variant_targets


ORDERINGS = ["freq", "radical", "reading", "codepoint"]
KEY_SHIFT_DOWN = getattr(curses, "KEY_SF", -1)
KEY_SHIFT_UP = getattr(curses, "KEY_SR", -1)


class TuiApp:
    def __init__(
        self,
        conn: sqlite3.Connection,
        normalizer_name: str = "default",
        user_store: UserStore | None = None,
    ) -> None:
        self.conn = conn
        self.normalizer_name = normalizer_name
        self.search_engine = SearchEngine(conn, normalizer_name=normalizer_name)
        self.user_store = user_store
        self.bookmarked_cps: set[int] = set()
        if self.user_store is not None:
            self.bookmarked_cps = {cp for cp, _ in self.user_store.list_bookmarks(limit=1000)}
        self.derived_counts = db_query.derived_data_counts(conn)
        self.jp_reading_cps, self.cn_reading_cps = db_query.reading_cp_sets(conn)

        self.focus = "jp"
        self.panel_focus = "jp"
        self.ordering_idx = 0
        self.freq_profiles = db_query.available_frequency_profiles(conn)
        self.freq_profile_idx = 0
        self.ordered_cps = db_query.get_ordered_cps(
            conn, ORDERINGS[self.ordering_idx], self.focus, self.current_freq_profile
        )
        self.pos = 0

        self.show_jp = True
        self.show_cn = True
        self.show_sentences = True
        self.show_variants = True
        self.show_help = False
        self.show_provenance = False
        self.show_components = False
        self.show_phonetic = False
        self.show_jp_romaji = False
        self.hide_no_reading = False
        self.variant_idx = 0

        self.message = "Ready"
        if self.derived_counts.get("field_provenance", 0) == 0:
            self.message = "DB missing derived rows (run --build to populate phase C/D features)"

        self.search_open = False
        self.search_input = ""
        self.search_results: list[dict] = []
        self.search_idx = 0
        self.note_input_open = False
        self.note_input_text = ""
        self.note_input_cursor = 0
        self.note_target = "glyph"
        self.show_user_overlay = False
        self.bookmark_open = False
        self.bookmark_rows: list[tuple[int, str | None]] = []
        self.bookmark_idx = 0

        self.radical_open = False
        self.radical_counts = dict(db_query.radical_counts(conn))
        self.radical_numbers = all_kangxi_radical_numbers()
        self.radical_grid_cols = 14
        self.radical_idx = 0
        self.radical_results: list[int] | None = None
        self.radical_result_idx = 0
        self.radical_selected: int | None = None
        self.radical_stroke_options: list[int | None] = [None]
        self.radical_stroke_idx = 0
        self._variant_cache_cp: int | None = None
        self._variant_graph: dict | None = None
        self._variant_targets: list[VariantTarget] = []
        self.runtime_paths = resolve_runtime_paths(self.user_store)
        self.stroke_repo = StrokeOrderRepository(root=self.runtime_paths.strokeorder_dir)
        self.stroke_open = False
        self.stroke_data: StrokeOrderData | None = None
        self.stroke_frames: list[list[str]] = []
        self.stroke_frame_idx = 0
        self.stroke_done = False
        self.stroke_canvas_dims = (0, 0)
        self._stdscr: curses.window | None = None
        self.show_ack_overlay = False
        self.show_startup_overlay = False
        self.setup_open = False
        self.setup_rows = [key for key in SOURCE_ORDER if key in SOURCES]
        self.setup_selected: set[str] = set()
        self.setup_idx = 0
        self.setup_logs: list[str] = []
        self._setup_results: dict[str, str] = {}
        if self.user_store is not None:
            self.show_startup_overlay = not self.user_store.get_flag("startup_seen", default=False)
        else:
            self.show_startup_overlay = True

        self.router = KeyRouter(self._current_mode, self._handle_normal_key)
        self.router.register("search", self._handle_search_key)
        self.router.register("radical", self._handle_radical_key)
        self.router.register("note", self._handle_note_key)
        self.router.register("bookmark", self._handle_bookmark_key)
        self.router.register("stroke", self._handle_stroke_key)
        self.router.register("setup", self._handle_setup_key)
        self.router.register("ack", self._handle_ack_key)

    @property
    def current_cp(self) -> int | None:
        if not self.ordered_cps:
            return None
        self.pos = max(0, min(self.pos, len(self.ordered_cps) - 1))
        return self.ordered_cps[self.pos]

    @property
    def current_freq_profile(self) -> str | None:
        if not self.freq_profiles:
            return None
        return self.freq_profiles[self.freq_profile_idx]

    def _reading_filter_scope(self) -> str:
        if ORDERINGS[self.ordering_idx] == "reading":
            return self.focus
        if self.show_jp and not self.show_cn:
            return "jp"
        if self.show_cn and not self.show_jp:
            return "cn"
        return "either"

    def _sentence_langs(self) -> tuple[str, ...]:
        if self.show_jp and self.show_cn:
            return ("jp", "cn")
        if self.show_jp:
            return ("jp",)
        if self.show_cn:
            return ("cn",)
        return ("jp", "cn")

    def _refresh_ordering(self) -> None:
        current = self.current_cp
        base_ordered = db_query.get_ordered_cps(
            self.conn,
            ORDERINGS[self.ordering_idx],
            self.focus,
            self.current_freq_profile,
        )
        ordered = base_ordered
        allowed: set[int] | None = None
        if self.hide_no_reading:
            scope = self._reading_filter_scope()
            if scope == "jp":
                allowed = self.jp_reading_cps
            elif scope == "cn":
                allowed = self.cn_reading_cps
            else:
                allowed = self.jp_reading_cps | self.cn_reading_cps
            ordered = [cp for cp in ordered if cp in allowed]
        self.ordered_cps = ordered
        if current is None or not self.ordered_cps:
            self.pos = 0
            return
        try:
            self.pos = self.ordered_cps.index(current)
        except ValueError:
            # If the current glyph was filtered out, advance to the next glyph
            # that survives the current ordering/filter scope.
            if allowed is not None and current in base_ordered:
                start = base_ordered.index(current)
                for offset in range(1, len(base_ordered) + 1):
                    candidate = base_ordered[(start + offset) % len(base_ordered)]
                    if candidate in allowed:
                        self.pos = self.ordered_cps.index(candidate)
                        return
            self.pos = 0

    def _jump_to_cp(self, cp: int) -> None:
        if cp in self.ordered_cps:
            self.pos = self.ordered_cps.index(cp)
            self.message = f"Jumped to U+{cp:04X}"

    def _open_note_editor(self, target: str) -> None:
        if self.user_store is None:
            self.message = "User workspace unavailable"
            return
        self.note_input_open = True
        self.note_target = target
        if target == "glyph":
            cp = self.current_cp
            if cp is None:
                self.note_input_text = ""
            else:
                self.note_input_text = f"{chr(cp)} U+{cp:04X}\n"
        else:
            self.note_input_text = ""
        self.note_input_cursor = len(self.note_input_text)
        self.message = f"{'Glyph' if target == 'glyph' else 'Global'} note editor"

    def _save_note_editor(self) -> None:
        if self.user_store is None:
            self.message = "User workspace unavailable"
            self.note_input_open = False
            return
        text = self.note_input_text.strip()
        if not text:
            self.message = "Empty note ignored"
            self.note_input_open = False
            self.note_input_text = ""
            self.note_input_cursor = 0
            return
        if self.note_target == "glyph":
            cp = self.current_cp
            if cp is None:
                self.message = "No current character"
                self.note_input_open = False
                return
            self.user_store.add_glyph_note(cp, text)
            self.message = f"Saved note for U+{cp:04X}"
        else:
            self.user_store.add_global_note(text)
            self.message = "Saved global note"
        self.note_input_open = False
        self.note_input_text = ""
        self.note_input_cursor = 0

    def _open_bookmark_picker(self) -> None:
        if self.user_store is None:
            self.message = "User workspace unavailable"
            return
        self.bookmark_rows = self.user_store.list_bookmarks(limit=2000)
        if not self.bookmark_rows:
            self.message = "No bookmarks"
            return
        self.bookmark_idx = 0
        self.bookmark_open = True
        self.message = f"Bookmarks: {len(self.bookmark_rows)}"

    def _dismiss_startup_overlay(self) -> None:
        if not self.show_startup_overlay:
            return
        self.show_startup_overlay = False
        if self.user_store is not None:
            self.user_store.set_flag("startup_seen", True)

    def _available_sources(self) -> dict[str, bool]:
        return detect_available_sources(self.runtime_paths)

    def _open_setup_overlay(self) -> None:
        available = self._available_sources()
        self.setup_selected = set(default_setup_selection(available))
        self.setup_idx = 0
        self.setup_logs = []
        self._setup_results = {}
        self.setup_open = True
        self.message = "Setup: select sources to download"

    def _run_setup_download(self) -> None:
        selected = [key for key in self.setup_rows if key in self.setup_selected]
        if not selected:
            self.message = "Setup: no sources selected"
            return
        self.setup_logs.append("Starting downloads ...")

        def _progress(msg: str) -> None:
            self.setup_logs.append(msg)
            if len(self.setup_logs) > 120:
                self.setup_logs = self.setup_logs[-120:]
            if self._stdscr is not None:
                try:
                    self._render(self._stdscr)
                except curses.error:
                    pass

        self._setup_results = download_selected_sources(
            selected=selected,
            paths=self.runtime_paths,
            progress=_progress,
        )
        ok = sum(1 for status in self._setup_results.values() if status == "ok")
        fail = sum(1 for status in self._setup_results.values() if status != "ok")
        self.stroke_repo = StrokeOrderRepository(root=self.runtime_paths.strokeorder_dir)
        auto_build_ok = False
        db_path = self._current_db_path()
        if db_path is None:
            self.setup_logs.append("Skipping auto-build: no filesystem DB path is attached.")
        else:
            current_cp = self.current_cp
            self.setup_logs.append("Starting automatic DB rebuild ...")
            try:
                try:
                    self.conn.close()
                except Exception:
                    pass
                _ = rebuild_database_from_sources(
                    paths=self.runtime_paths,
                    db_path=db_path,
                    progress=_progress,
                )
                auto_build_ok = True
            except Exception as exc:  # noqa: BLE001
                self.setup_logs.append(f"Automatic DB rebuild failed: {exc}")
            finally:
                self.conn = connect_db(db_path)
                self._reload_db_state(current_cp=current_cp)
        self.setup_logs.append(f"Completed: ok={ok} failed={fail}")
        if auto_build_ok:
            self.message = f"Setup download + auto-build completed: ok={ok} failed={fail}"
        else:
            self.message = f"Setup download completed: ok={ok} failed={fail}"

    def _current_db_path(self) -> Path | None:
        row = self.conn.execute("PRAGMA database_list").fetchone()
        if row is None:
            return None
        raw = str(row[2] or "").strip()
        if not raw:
            return None
        return Path(raw)

    def _reload_db_state(self, current_cp: int | None = None) -> None:
        self.search_engine = SearchEngine(self.conn, normalizer_name=self.normalizer_name)
        self.derived_counts = db_query.derived_data_counts(self.conn)
        self.jp_reading_cps, self.cn_reading_cps = db_query.reading_cp_sets(self.conn)
        self.freq_profiles = db_query.available_frequency_profiles(self.conn)
        if self.freq_profiles:
            self.freq_profile_idx = max(0, min(self.freq_profile_idx, len(self.freq_profiles) - 1))
        else:
            self.freq_profile_idx = 0
        self._refresh_ordering()
        if current_cp is not None and current_cp in self.ordered_cps:
            self.pos = self.ordered_cps.index(current_cp)
        elif self.ordered_cps:
            self.pos = max(0, min(self.pos, len(self.ordered_cps) - 1))
        else:
            self.pos = 0
        if self.derived_counts.get("field_provenance", 0) == 0 and not self.message.startswith("Setup"):
            self.message = "DB missing derived rows (run --build to populate phase C/D features)"

    def _current_stroke_char(self) -> str | None:
        cp = self.current_cp
        if cp is None:
            return None
        return chr(cp)

    def _stroke_available_for_current(self) -> bool:
        ch = self._current_stroke_char()
        if ch is None:
            return False
        return self.stroke_repo.has_char(ch)

    def _open_stroke_overlay(self) -> None:
        ch = self._current_stroke_char()
        if ch is None:
            self.message = "No current character"
            return
        data = self.stroke_repo.load(ch)
        if data is None:
            self.message = f"No stroke animation data for {ch}"
            return
        self.stroke_open = True
        self.stroke_data = data
        self.stroke_frames = []
        self.stroke_frame_idx = 0
        self.stroke_done = False
        self.stroke_canvas_dims = (0, 0)
        self.message = f"Stroke animation: {ch}"

    def _stroke_overlay_geometry(self, h: int, w: int) -> tuple[int, int, int, int]:
        box_w = min(max(36, w - 6), 90)
        box_h = min(max(12, h - 4), 36)
        box_w = min(box_w, w - 2)
        box_h = min(box_h, h - 2)
        top = max(1, (h - box_h) // 2)
        left = max(1, (w - box_w) // 2)
        return top, left, box_h, box_w

    def _ensure_stroke_frames(self, h: int, w: int) -> None:
        if not self.stroke_open or self.stroke_data is None:
            return
        _top, _left, box_h, box_w = self._stroke_overlay_geometry(h, w)
        cols = max(8, box_w - 4)
        rows = max(4, box_h - 5)
        dims = (cols, rows)
        if dims == self.stroke_canvas_dims and self.stroke_frames:
            return
        self.stroke_canvas_dims = dims
        self.stroke_frames = build_tui_stroke_frames(self.stroke_data, cols=cols, rows=rows)
        self.stroke_frame_idx = 0
        self.stroke_done = len(self.stroke_frames) <= 1

    def _tick_stroke_animation(self, stdscr: curses.window) -> None:
        if not self.stroke_open or self.stroke_data is None or self.stroke_done:
            return
        h, w = stdscr.getmaxyx()
        self._ensure_stroke_frames(h, w)
        if not self.stroke_frames:
            self.stroke_done = True
            return
        if self.stroke_frame_idx < len(self.stroke_frames) - 1:
            self.stroke_frame_idx += 1
        else:
            self.stroke_done = True

    def _input_timeout_ms(self) -> int:
        if self.stroke_open and not self.stroke_done:
            return 28
        return -1

    @staticmethod
    def _line_starts(text: str) -> list[int]:
        starts = [0]
        for idx, ch in enumerate(text):
            if ch == "\n":
                starts.append(idx + 1)
        return starts

    def _note_cursor_line_col(self) -> tuple[int, int]:
        starts = self._line_starts(self.note_input_text)
        line = 0
        for idx, start in enumerate(starts):
            if start > self.note_input_cursor:
                break
            line = idx
        col = self.note_input_cursor - starts[line]
        return line, col

    def _move_note_cursor_vertical(self, delta: int) -> None:
        starts = self._line_starts(self.note_input_text)
        if not starts:
            self.note_input_cursor = 0
            return
        line, col = self._note_cursor_line_col()
        target_line = max(0, min(len(starts) - 1, line + delta))
        start = starts[target_line]
        if target_line + 1 < len(starts):
            # Keep cursor before newline on bounded lines.
            line_end = starts[target_line + 1] - 1
        else:
            line_end = len(self.note_input_text)
        self.note_input_cursor = min(start + col, line_end)

    def _visible_panel_focuses(self) -> list[str]:
        panels: list[str] = []
        if self.show_jp:
            panels.append("jp")
        if self.show_cn:
            panels.append("cn")
        if self.show_variants:
            panels.append("variants")
        if not panels:
            panels = ["jp"]
        return panels

    def _ensure_panel_focus_valid(self) -> None:
        panels = self._visible_panel_focuses()
        if self.panel_focus not in panels:
            self.panel_focus = panels[0]
        if self.panel_focus in ("jp", "cn") and self.focus != self.panel_focus:
            self.focus = self.panel_focus
            if ORDERINGS[self.ordering_idx] == "reading" or self.hide_no_reading:
                self._refresh_ordering()

    def _cycle_panel_focus(self) -> None:
        panels = self._visible_panel_focuses()
        if self.panel_focus not in panels:
            self.panel_focus = panels[0]
        else:
            idx = panels.index(self.panel_focus)
            self.panel_focus = panels[(idx + 1) % len(panels)]

        if self.panel_focus in ("jp", "cn") and self.focus != self.panel_focus:
            self.focus = self.panel_focus
            if ORDERINGS[self.ordering_idx] == "reading" or self.hide_no_reading:
                self._refresh_ordering()
        self.message = f"Panel focus: {self.panel_focus}"

    def _variant_data_for_current(self) -> tuple[dict, list[VariantTarget]]:
        cp = self.current_cp
        if cp is None:
            self._variant_cache_cp = None
            self._variant_graph = {"nodes": [], "edges": []}
            self._variant_targets = []
            self.variant_idx = 0
            return self._variant_graph, self._variant_targets

        if self._variant_cache_cp != cp:
            graph = db_query.variant_graph(self.conn, cp, depth=2, max_nodes=32)
            self._variant_graph = graph
            self._variant_targets = build_variant_targets(cp, graph)
            self.variant_idx = 0
            self._variant_cache_cp = cp

        count = len(self._variant_targets)
        if count <= 0:
            self.variant_idx = 0
        else:
            self.variant_idx = max(0, min(count - 1, self.variant_idx))
        return self._variant_graph or {"nodes": [], "edges": []}, self._variant_targets

    def _move_variant_selection(self, delta: int) -> bool:
        _graph, targets = self._variant_data_for_current()
        if not targets:
            return False
        self.variant_idx = max(0, min(len(targets) - 1, self.variant_idx + delta))
        return True

    def _jump_to_selected_variant(self) -> bool:
        _graph, targets = self._variant_data_for_current()
        if not targets:
            self.message = "No variants to jump to"
            return False
        target = targets[self.variant_idx]
        if target.cp not in self.ordered_cps:
            self.message = f"Variant {target.ch} U+{target.cp:04X} is filtered out"
            return False
        self._jump_to_cp(target.cp)
        return True

    def run(self, stdscr: curses.window) -> None:
        self._stdscr = stdscr
        stdscr.keypad(True)
        while True:
            self._set_cursor_visibility()
            self._tick_stroke_animation(stdscr)
            self._render(stdscr)
            stdscr.timeout(self._input_timeout_ms())
            try:
                key = stdscr.get_wch()
            except curses.error:
                continue
            if not self._handle_key(key):
                break

    def _current_mode(self) -> str:
        if self.show_ack_overlay:
            return "ack"
        if self.setup_open:
            return "setup"
        if self.stroke_open:
            return "stroke"
        if self.search_open:
            return "search"
        if self.radical_open:
            return "radical"
        if self.note_input_open:
            return "note"
        if self.bookmark_open:
            return "bookmark"
        return "normal"

    def _handle_key(self, key: KeyInput) -> bool:
        return self.router.dispatch(key)

    def _set_cursor_visibility(self) -> None:
        target = 1 if (self.search_open or self.note_input_open) else 0
        try:
            curses.curs_set(target)
        except curses.error:
            return

    def _normalize_text_key(self, key: KeyInput) -> KeyInput:
        if isinstance(key, str):
            if key in ("\n", "\r"):
                return 10
            if key == "\x1b":
                return 27
            if key == "\x7f":
                return 127
            if len(key) == 1 and ord(key) < 128:
                return ord(key)
        return key

    def _handle_normal_key(self, key: KeyInput) -> bool:
        key = self._normalize_text_key(key)
        self._dismiss_startup_overlay()
        if isinstance(key, str):
            return True
        if key in (ord("q"), ord("Q")):
            return False
        if key in (10, 13, curses.KEY_ENTER):
            if self.panel_focus == "variants" and self.show_variants:
                self._jump_to_selected_variant()
                return True
        if key in (curses.KEY_RIGHT, curses.KEY_DOWN, ord("j")):
            if self.panel_focus == "variants" and self.show_variants:
                moved = self._move_variant_selection(+1)
                if not moved and self.ordered_cps:
                    self.pos = min(self.pos + 1, len(self.ordered_cps) - 1)
            elif self.ordered_cps:
                self.pos = min(self.pos + 1, len(self.ordered_cps) - 1)
            return True
        if key in (curses.KEY_LEFT, curses.KEY_UP, ord("k")):
            if self.panel_focus == "variants" and self.show_variants:
                moved = self._move_variant_selection(-1)
                if not moved and self.ordered_cps:
                    self.pos = max(self.pos - 1, 0)
            elif self.ordered_cps:
                self.pos = max(self.pos - 1, 0)
            return True
        if key == curses.KEY_HOME:
            if self.panel_focus == "variants" and self.show_variants:
                _graph, targets = self._variant_data_for_current()
                self.variant_idx = 0 if targets else 0
            else:
                self.pos = 0
            return True
        if key == curses.KEY_END:
            if self.panel_focus == "variants" and self.show_variants:
                _graph, targets = self._variant_data_for_current()
                self.variant_idx = len(targets) - 1 if targets else 0
            elif self.ordered_cps:
                self.pos = len(self.ordered_cps) - 1
            return True

        if key == 9:  # Tab
            self._cycle_panel_focus()
            return True

        if key in (ord("O"), ord("o")):
            self.ordering_idx = (self.ordering_idx + 1) % len(ORDERINGS)
            self._refresh_ordering()
            if ORDERINGS[self.ordering_idx] == "freq" and self.current_freq_profile:
                self.message = f"Order: freq ({self.current_freq_profile})"
            else:
                self.message = f"Order: {ORDERINGS[self.ordering_idx]}"
            return True

        if key in (ord("F"),):
            if self.freq_profiles:
                self.freq_profile_idx = (self.freq_profile_idx + 1) % len(self.freq_profiles)
                if ORDERINGS[self.ordering_idx] == "freq":
                    self._refresh_ordering()
                self.message = f"Freq profile: {self.current_freq_profile}"
            else:
                self.message = "No frequency profiles available"
            return True

        if key == ord("1"):
            self.show_jp = not self.show_jp
            if self.hide_no_reading:
                self._refresh_ordering()
            self._ensure_panel_focus_valid()
            return True
        if key == ord("2"):
            self.show_cn = not self.show_cn
            if self.hide_no_reading:
                self._refresh_ordering()
            self._ensure_panel_focus_valid()
            return True
        if key == ord("3"):
            self.show_sentences = not self.show_sentences
            return True
        if key in (ord("4"), ord("v"), ord("V")):
            self.show_variants = not self.show_variants
            self._ensure_panel_focus_valid()
            return True
        if key in (ord("p"), ord("P")):
            self.show_provenance = not self.show_provenance
            return True
        if key in (ord("c"), ord("C")):
            self.show_components = not self.show_components
            if self.show_components:
                self.show_phonetic = False
            return True
        if key in (ord("s"),):
            self.show_phonetic = not self.show_phonetic
            if self.show_phonetic:
                self.show_components = False
            return True
        if key in (ord("m"), ord("M")):
            self.show_jp_romaji = not self.show_jp_romaji
            self.message = f"JP romaji: {'on' if self.show_jp_romaji else 'off'}"
            return True
        if key == ord("N"):
            self.hide_no_reading = not self.hide_no_reading
            self._refresh_ordering()
            scope = self._reading_filter_scope()
            self.message = f"Hide no-reading: {'on' if self.hide_no_reading else 'off'} (scope={scope})"
            return True
        if key == ord("b"):
            cp = self.current_cp
            if cp is None or self.user_store is None:
                self.message = "User workspace unavailable"
                return True
            bookmarked = self.user_store.toggle_bookmark(cp)
            if bookmarked:
                self.bookmarked_cps.add(cp)
            else:
                self.bookmarked_cps.discard(cp)
            self.message = (
                f"Bookmarked U+{cp:04X}" if bookmarked else f"Removed bookmark U+{cp:04X}"
            )
            return True
        if key == ord("B"):
            self._open_bookmark_picker()
            return True
        if key == ord("n"):
            self._open_note_editor(target="glyph")
            return True
        if key in (ord("g"), ord("G")):
            self._open_note_editor(target="global")
            return True
        if key in (ord("u"), ord("U")):
            self.show_user_overlay = not self.show_user_overlay
            return True
        if key in (ord("i"), ord("I")):
            cp = self.current_cp
            if cp is None:
                return True
            ch = chr(cp)
            url = f"http://ccamc.org/cjkv.php?cjkv={quote(ch)}"
            webbrowser.open(url)
            self.message = f"Opened CCAMC for {ch}"
            return True
        if key == ord("?"):
            self.show_help = not self.show_help
            return True
        if key in (ord("A"),):
            self.show_ack_overlay = not self.show_ack_overlay
            return True
        if key in (ord("S"),):
            self._open_setup_overlay()
            return True
        if key in (ord("t"), ord("T")):
            self._open_stroke_overlay()
            return True
        if key == ord("/"):
            self.search_open = True
            self.search_input = ""
            self.search_results = []
            self.search_idx = 0
            return True
        if key in (ord("r"), ord("R")):
            self.radical_open = True
            self.radical_results = None
            self.radical_result_idx = 0
            self.radical_selected = None
            self.radical_stroke_options = [None]
            self.radical_stroke_idx = 0
            return True

        return True

    def _handle_stroke_key(self, key: KeyInput) -> bool | None:
        key = self._normalize_text_key(key)
        if isinstance(key, str):
            return True
        if key == 27:  # Esc
            self.stroke_open = False
            self.stroke_data = None
            self.stroke_frames = []
            self.stroke_frame_idx = 0
            self.stroke_done = False
            self.stroke_canvas_dims = (0, 0)
            self.message = "Closed stroke animation"
            return True
        return True

    def _handle_ack_key(self, key: KeyInput) -> bool | None:
        key = self._normalize_text_key(key)
        if isinstance(key, str):
            return True
        if key in (27, ord("A"), ord("a")):
            self.show_ack_overlay = False
            self.message = "Closed acknowledgements"
            return True
        return True

    def _handle_setup_key(self, key: KeyInput) -> bool | None:
        key = self._normalize_text_key(key)
        if isinstance(key, str):
            return True
        if key in (27, ord("S"), ord("s")):
            self.setup_open = False
            self.message = "Closed setup"
            return True
        if key in (curses.KEY_UP, ord("k")):
            self.setup_idx = max(0, self.setup_idx - 1)
            return True
        if key in (curses.KEY_DOWN, ord("j")):
            self.setup_idx = min(len(self.setup_rows) - 1, self.setup_idx + 1)
            return True
        if key == ord(" "):
            if self.setup_rows:
                source = self.setup_rows[self.setup_idx]
                if source in self.setup_selected:
                    self.setup_selected.discard(source)
                else:
                    self.setup_selected.add(source)
            return True
        if key in (10, 13, curses.KEY_ENTER):
            if self.setup_rows:
                source = self.setup_rows[self.setup_idx]
                if source in self.setup_selected:
                    self.setup_selected.discard(source)
                else:
                    self.setup_selected.add(source)
            return True
        if key in (ord("d"), ord("D")):
            self._run_setup_download()
            return True
        if key in (ord("a"),):
            self.setup_selected = set(self.setup_rows)
            return True
        if key in (ord("n"),):
            self.setup_selected.clear()
            return True
        if ord("1") <= key <= ord("9"):
            idx = key - ord("1")
            if 0 <= idx < len(self.setup_rows):
                source = self.setup_rows[idx]
                if source in self.setup_selected:
                    self.setup_selected.discard(source)
                else:
                    self.setup_selected.add(source)
            return True
        return True

    def _handle_search_key(self, key: KeyInput) -> bool | None:
        key = self._normalize_text_key(key)
        if key == 27:  # Esc
            self.search_open = False
            self.search_results = []
            self.message = "Closed search"
            return True

        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.search_input:
                self.search_input = self.search_input[:-1]
                self.search_results = []
                self.search_idx = 0
            return True

        if key in (curses.KEY_UP, ord("k")) and self.search_results:
            self.search_idx = max(0, self.search_idx - 1)
            return True
        if key in (curses.KEY_DOWN, ord("j")) and self.search_results:
            self.search_idx = min(len(self.search_results) - 1, self.search_idx + 1)
            return True
        if key in (KEY_SHIFT_UP, curses.KEY_HOME, curses.KEY_PPAGE) and self.search_results:
            self.search_idx = 0
            return True
        if key in (KEY_SHIFT_DOWN, curses.KEY_END, curses.KEY_NPAGE) and self.search_results:
            self.search_idx = len(self.search_results) - 1
            return True

        if key in (10, 13, curses.KEY_ENTER):
            if self.search_results:
                cp = int(self.search_results[self.search_idx]["cp"])
                self._jump_to_cp(cp)
                self.search_open = False
                self.search_results = []
                return True

            self.search_results = self.search_engine.run(self.search_input, limit=200)
            if self.user_store is not None:
                self.user_store.save_query(self.search_input)
            self.search_idx = 0
            self.message = f"{len(self.search_results)} results"
            return True

        if isinstance(key, str):
            if key.isprintable():
                self.search_input += key
                self.search_results = []
                self.search_idx = 0
            return True

        if 32 <= key < 127:
            self.search_input += chr(key)
            self.search_results = []
            self.search_idx = 0
            return True

        return True

    def _handle_radical_key(self, key: KeyInput) -> bool | None:
        key = self._normalize_text_key(key)
        if isinstance(key, str):
            return True
        if key == 27:  # Esc
            self.radical_open = False
            self.radical_results = None
            self.radical_selected = None
            self.message = "Closed radical browser"
            return True

        if self.radical_results is None:
            if key in (curses.KEY_UP, ord("k")):
                self.radical_idx = move_grid_index(
                    self.radical_idx, len(self.radical_numbers), self.radical_grid_cols, "up"
                )
                return True
            if key in (curses.KEY_DOWN, ord("j")):
                self.radical_idx = move_grid_index(
                    self.radical_idx, len(self.radical_numbers), self.radical_grid_cols, "down"
                )
                return True
            if key in (curses.KEY_LEFT,):
                self.radical_idx = move_grid_index(
                    self.radical_idx, len(self.radical_numbers), self.radical_grid_cols, "left"
                )
                return True
            if key in (curses.KEY_RIGHT,):
                self.radical_idx = move_grid_index(
                    self.radical_idx, len(self.radical_numbers), self.radical_grid_cols, "right"
                )
                return True
            if key in (10, 13, curses.KEY_ENTER) and self.radical_numbers:
                radical = self.radical_numbers[self.radical_idx]
                self.radical_selected = radical
                strokes = db_query.stroke_options_by_radical(self.conn, radical)
                self.radical_stroke_options = [None] + strokes
                self.radical_stroke_idx = 0
                self.radical_results = db_query.cps_by_radical(self.conn, radical, stroke_filter=None)
                self.radical_result_idx = 0
                self.message = f"Radical {kangxi_radical_glyph(radical)} selected"
                return True
            return True

        if key in (curses.KEY_UP, ord("k")):
            if self.radical_results:
                self.radical_result_idx = max(0, self.radical_result_idx - 1)
            return True
        if key in (curses.KEY_DOWN, ord("j")):
            if self.radical_results:
                self.radical_result_idx = min(len(self.radical_results) - 1, self.radical_result_idx + 1)
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.radical_results = None
            self.radical_result_idx = 0
            self.radical_selected = None
            self.radical_stroke_options = [None]
            self.radical_stroke_idx = 0
            return True
        if key == ord("[") and self.radical_selected is not None:
            self.radical_stroke_idx = max(0, self.radical_stroke_idx - 1)
            stroke_filter = self.radical_stroke_options[self.radical_stroke_idx]
            self.radical_results = db_query.cps_by_radical(
                self.conn, self.radical_selected, stroke_filter=stroke_filter
            )
            self.radical_result_idx = 0
            self.message = f"Stroke filter: {stroke_filter if stroke_filter is not None else 'all'}"
            return True
        if key == ord("]") and self.radical_selected is not None:
            self.radical_stroke_idx = min(
                len(self.radical_stroke_options) - 1, self.radical_stroke_idx + 1
            )
            stroke_filter = self.radical_stroke_options[self.radical_stroke_idx]
            self.radical_results = db_query.cps_by_radical(
                self.conn, self.radical_selected, stroke_filter=stroke_filter
            )
            self.radical_result_idx = 0
            self.message = f"Stroke filter: {stroke_filter if stroke_filter is not None else 'all'}"
            return True
        if key in (10, 13, curses.KEY_ENTER) and self.radical_results:
            cp = self.radical_results[self.radical_result_idx]
            self._jump_to_cp(cp)
            self.radical_open = False
            self.radical_results = None
            self.radical_selected = None
            return True

        return True

    def _handle_note_key(self, key: KeyInput) -> bool | None:
        key = self._normalize_text_key(key)
        if key == 27:  # Esc
            self.note_input_open = False
            self.note_input_text = ""
            self.note_input_cursor = 0
            self.message = "Cancelled note entry"
            return True
        if key == 19:  # Ctrl+S
            self._save_note_editor()
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.note_input_cursor > 0:
                start = self.note_input_cursor - 1
                self.note_input_text = (
                    self.note_input_text[:start] + self.note_input_text[self.note_input_cursor :]
                )
                self.note_input_cursor = start
            return True
        if key == curses.KEY_DC:
            if self.note_input_cursor < len(self.note_input_text):
                self.note_input_text = (
                    self.note_input_text[: self.note_input_cursor]
                    + self.note_input_text[self.note_input_cursor + 1 :]
                )
            return True
        if key == curses.KEY_LEFT:
            self.note_input_cursor = max(0, self.note_input_cursor - 1)
            return True
        if key == curses.KEY_RIGHT:
            self.note_input_cursor = min(len(self.note_input_text), self.note_input_cursor + 1)
            return True
        if key in (curses.KEY_UP,):
            self._move_note_cursor_vertical(-1)
            return True
        if key in (curses.KEY_DOWN,):
            self._move_note_cursor_vertical(+1)
            return True
        if key == curses.KEY_HOME:
            starts = self._line_starts(self.note_input_text)
            line, _col = self._note_cursor_line_col()
            self.note_input_cursor = starts[line]
            return True
        if key == curses.KEY_END:
            starts = self._line_starts(self.note_input_text)
            line, _col = self._note_cursor_line_col()
            if line + 1 < len(starts):
                self.note_input_cursor = starts[line + 1] - 1
            else:
                self.note_input_cursor = len(self.note_input_text)
            return True
        if key in (10, 13, curses.KEY_ENTER):
            self.note_input_text = (
                self.note_input_text[: self.note_input_cursor]
                + "\n"
                + self.note_input_text[self.note_input_cursor :]
            )
            self.note_input_cursor += 1
            return True
        if key == 9:  # Tab
            self.note_input_text = (
                self.note_input_text[: self.note_input_cursor]
                + "    "
                + self.note_input_text[self.note_input_cursor :]
            )
            self.note_input_cursor += 4
            return True
        if isinstance(key, str):
            if key.isprintable():
                self.note_input_text = (
                    self.note_input_text[: self.note_input_cursor]
                    + key
                    + self.note_input_text[self.note_input_cursor :]
                )
                self.note_input_cursor += len(key)
            return True

        if 32 <= key < 127:
            ch = chr(key)
            self.note_input_text = (
                self.note_input_text[: self.note_input_cursor]
                + ch
                + self.note_input_text[self.note_input_cursor :]
            )
            self.note_input_cursor += 1
            return True
        return True

    def _handle_bookmark_key(self, key: KeyInput) -> bool | None:
        key = self._normalize_text_key(key)
        if isinstance(key, str):
            return True
        if key == 27:  # Esc
            self.bookmark_open = False
            self.bookmark_rows = []
            self.bookmark_idx = 0
            self.message = "Closed bookmarks"
            return True
        if not self.bookmark_rows:
            self.bookmark_open = False
            self.bookmark_idx = 0
            self.message = "No bookmarks"
            return True
        if key in (curses.KEY_UP, ord("k")):
            self.bookmark_idx = max(0, self.bookmark_idx - 1)
            return True
        if key in (curses.KEY_DOWN, ord("j")):
            self.bookmark_idx = min(len(self.bookmark_rows) - 1, self.bookmark_idx + 1)
            return True
        if key in (curses.KEY_HOME, curses.KEY_PPAGE):
            self.bookmark_idx = 0
            return True
        if key in (curses.KEY_END, curses.KEY_NPAGE):
            self.bookmark_idx = len(self.bookmark_rows) - 1
            return True
        if key in (10, 13, curses.KEY_ENTER):
            cp, _tag = self.bookmark_rows[self.bookmark_idx]
            self._jump_to_cp(cp)
            self.bookmark_open = False
            self.bookmark_rows = []
            self.bookmark_idx = 0
            return True
        if key in (ord("x"), ord("X")) and self.user_store is not None:
            cp, _tag = self.bookmark_rows[self.bookmark_idx]
            deleted = self.user_store.delete_bookmark(cp)
            if deleted:
                self.bookmarked_cps.discard(cp)
                del self.bookmark_rows[self.bookmark_idx]
                if not self.bookmark_rows:
                    self.bookmark_open = False
                    self.bookmark_idx = 0
                    self.message = "Deleted bookmark; no bookmarks left"
                    return True
                self.bookmark_idx = min(self.bookmark_idx, len(self.bookmark_rows) - 1)
                self.message = f"Deleted bookmark U+{cp:04X}"
            else:
                self.message = f"Bookmark U+{cp:04X} not found"
            return True
        return True

    def _safe_add(self, stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = stdscr.getmaxyx()
        if y < 0 or y >= h:
            return
        clipped = text[: max(0, w - x - 1)]
        if clipped:
            try:
                stdscr.addstr(y, x, clipped, attr)
            except curses.error:
                return

    def _draw_box(
        self,
        stdscr: curses.window,
        top: int,
        left: int,
        height: int,
        width: int,
        title: str = "",
        double: bool = False,
    ) -> None:
        if height < 2 or width < 2:
            return
        right = left + width - 1
        bottom = top + height - 1
        if double:
            tl, hz, tr, vt, bl, br = "╔", "═", "╗", "║", "╚", "╝"
        else:
            tl, hz, tr, vt, bl, br = "┌", "─", "┐", "│", "└", "┘"

        border_attr = curses.A_BOLD
        self._safe_add(stdscr, top, left, tl + (hz * (width - 2)) + tr, border_attr)
        for y in range(top + 1, bottom):
            self._safe_add(stdscr, y, left, vt, border_attr)
            self._safe_add(stdscr, y, left + 1, " " * (width - 2))
            self._safe_add(stdscr, y, right, vt, border_attr)
        self._safe_add(stdscr, bottom, left, bl + (hz * (width - 2)) + br, border_attr)
        if title and width > 6:
            banner = f" {title} "
            self._safe_add(stdscr, top, left + 2, banner[: max(0, width - 4)], curses.A_BOLD)

    def _render_section(self, stdscr: curses.window, y: int, width: int, title: str, lines: list[str], highlighted: bool = False) -> int:
        inner_width = max(10, width - 1)
        box_h = len(lines) + 2
        if y + box_h >= stdscr.getmaxyx()[0] - 4:
            return y
        self._draw_box(stdscr, y, 0, box_h, inner_width, title=title, double=highlighted)
        for idx, line in enumerate(lines):
            self._safe_add(stdscr, y + 1 + idx, 2, line[: max(0, inner_width - 4)])
        return y + box_h

    def _render(self, stdscr: curses.window) -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        cp = self.current_cp
        if cp is None:
            self._safe_add(stdscr, 0, 0, "No characters in DB yet. Use Setup (Shift-S) to fetch sources.")
            menu_line = (
                "Setup:S  Ack:A  Help:?  Quit:q  (build DB after downloading: kanjitui --build --data-dir "
                f"{self.runtime_paths.data_dir})"
            )
            self._safe_add(stdscr, h - 2, 0, menu_line, curses.A_BOLD)
            self._safe_add(stdscr, h - 1, 0, self.message, curses.A_BOLD)
            if self.show_help:
                self._render_help(stdscr)
            if self.setup_open:
                self._render_setup_overlay(stdscr)
            if self.show_ack_overlay:
                self._render_ack_overlay(stdscr, startup=False)
            if self.show_startup_overlay:
                self._render_ack_overlay(stdscr, startup=True)
            stdscr.refresh()
            return

        try:
            detail = db_query.get_char_detail(self.conn, cp)
        except Exception as exc:
            self._safe_add(stdscr, 0, 0, f"Failed to load character: {exc}")
            stdscr.refresh()
            return

        idx = self.pos + 1
        total = len(self.ordered_cps)
        order_label = ORDERINGS[self.ordering_idx]
        if order_label == "freq" and self.current_freq_profile:
            order_label = f"freq:{self.current_freq_profile}"
        bookmark_marker = ""
        if detail["cp"] in self.bookmarked_cps:
            bookmark_marker = " ★"
        focus_label = f"  reading-sort:{self.focus.upper()}" if ORDERINGS[self.ordering_idx] == "reading" else ""
        romaji_label = "  JP-romaji:on" if self.show_jp_romaji else ""
        filtered_label = "  hide-no-reading:on" if self.hide_no_reading else ""
        header = (
            f"{detail['ch']}{bookmark_marker} U+{detail['cp']:04X}  radical {detail['radical'] or '-'}  "
            f"strokes {detail['strokes'] or '-'}  ({idx}/{total}) order:{order_label}{focus_label}{romaji_label}{filtered_label}"
        )
        self._safe_add(stdscr, 0, 0, header, curses.A_BOLD)
        stroke_available = self.stroke_repo.has_char(detail["ch"])

        self._render_nav_strip(stdscr, 2)
        y = 4
        self._ensure_panel_focus_valid()
        if self.show_jp:
            if self.show_jp_romaji:
                on_parts = [search_normalize.kana_to_romaji(reading) for reading in detail["jp_on"]]
                kun_parts = [search_normalize.kana_to_romaji(reading) for reading in detail["jp_kun"]]
            else:
                on_parts = detail["jp_on"]
                kun_parts = detail["jp_kun"]
            on = " ".join(on_parts) if on_parts else "(none)"
            kun = " ".join(kun_parts) if kun_parts else "(none)"
            jp_gloss = "; ".join(detail["jp_gloss"][:3]) if detail["jp_gloss"] else "(none)"
            words = detail["jp_words"]
            reading_label = "Readings (romaji)" if self.show_jp_romaji else "Readings"
            lines = [f"{reading_label}: on {on} | kun {kun}", f"Gloss: {jp_gloss}", "Words:"]
            if not words:
                lines.append("  (no examples found)")
            else:
                rendered_words = []
                for word, kana, gloss, rank in words[:5]:
                    reading = kana or "-"
                    if self.show_jp_romaji and kana:
                        reading = search_normalize.kana_to_romaji(kana)
                    rendered_words.append(f"  {rank}. {word}  {reading}  {gloss or '-'}")
                lines.extend(rendered_words)
            jp_focus = self.panel_focus == "jp"
            y = self._render_section(stdscr, y, w, "JP [1]", lines, highlighted=jp_focus) + 1

        if self.show_cn and y < h - 5:
            if detail["cn_readings"]:
                readings = "  ".join(
                    (marked or search_normalize.pinyin_numbered_to_marked(numbered or "") or "-")
                    for marked, numbered in detail["cn_readings"][:5]
                )
            else:
                readings = "(none)"
            cn_gloss = "; ".join(detail["cn_gloss"][:3]) if detail["cn_gloss"] else "(none)"
            words = detail["cn_words"]
            lines = [f"Readings: {readings}", f"Gloss: {cn_gloss}", "Words:"]
            if not words:
                lines.append("  (no examples found)")
            else:
                lines.extend(
                    [
                        f"  {rank}. {trad}/{simp}  {(marked or search_normalize.pinyin_numbered_to_marked(numbered or '') or '-')}  {gloss}"
                        for trad, simp, marked, numbered, gloss, rank in words[:5]
                    ]
                )
            cn_focus = self.panel_focus == "cn"
            y = self._render_section(stdscr, y, w, "CN [2]", lines, highlighted=cn_focus) + 1

        if self.show_sentences and y < h - 5:
            sentence_langs = self._sentence_langs()
            sentence_limit = 6 if len(sentence_langs) > 1 else 3
            sentence_rows = db_query.get_sentences(
                self.conn,
                detail["cp"],
                limit=sentence_limit,
                langs=sentence_langs,
            )
            if not sentence_rows:
                hint = "(no sentence examples)"
                if self.derived_counts.get("sentences", 0) == 0:
                    hint = "(no sentence examples; add sentences provider and rebuild DB)"
                lines = [hint]
            else:
                lines = []
                for lang, text, reading, gloss, source, license_name, rank in sentence_rows:
                    line = f"{rank}. [{lang}] {text}  {reading or '-'}  {gloss or '-'}"
                    lines.append(line)
                    lines.append(f"   source: {source or '-'} ({license_name or '-'})")
            langs_label = "/".join(lang.upper() for lang in sentence_langs)
            y = self._render_section(stdscr, y, w, f"Sentences [3] ({langs_label})", lines) + 1

        if self.show_variants and y < h - 4:
            graph, targets = self._variant_data_for_current()
            lines = [f"nodes={len(graph['nodes'])} edges={len(graph['edges'])}", "Arrows: select  Enter: jump"]
            if not targets:
                lines.append("(no variant targets)")
            else:
                for idx_target, target in enumerate(targets[:10]):
                    jumpable = target.cp in self.ordered_cps
                    marker = " "
                    if idx_target == self.variant_idx:
                        marker = "▶" if jumpable else "X"
                    lines.append(f"{marker} {target.ch} U+{target.cp:04X}  {target.relation}")
                if len(targets) > 10:
                    lines.append(f"... +{len(targets) - 10} more")
            var_focus = self.panel_focus == "variants"
            y = self._render_section(stdscr, y, w, "Variants [4]", lines, highlighted=var_focus)

        menu_line = (
            "Nav:←/→/j/k Home End Tab Enter  Search:/  Radical:r  Panes:1 2 3 4  "
            "Overlays:c s p  User:b B n g u  JP:m  Filter:N  CCAMC:i  Order:O F  Setup:S  Ack:A"
        )
        if stroke_available:
            menu_line += "  Stroke:t"
        menu_line += "  Help:?  Quit:q"
        self._safe_add(stdscr, h - 2, 0, menu_line, curses.A_BOLD)
        status = self.message
        self._safe_add(stdscr, h - 1, 0, status, curses.A_BOLD)

        if self.show_help:
            self._render_help(stdscr)
        if self.show_provenance:
            self._render_provenance_overlay(stdscr, detail["cp"])
        if self.show_components:
            self._render_components_overlay(stdscr, detail["cp"])
        if self.show_phonetic:
            self._render_phonetic_overlay(stdscr, detail["cp"])
        if self.show_user_overlay:
            self._render_user_overlay(stdscr, detail["cp"])
        if self.note_input_open:
            self._render_note_input_overlay(stdscr)
        if self.bookmark_open:
            self._render_bookmark_overlay(stdscr)
        if self.search_open:
            self._render_search_overlay(stdscr)
        if self.radical_open:
            self._render_radical_overlay(stdscr)
        if self.stroke_open:
            self._render_stroke_overlay(stdscr)
        if self.setup_open:
            self._render_setup_overlay(stdscr)
        if self.show_ack_overlay:
            self._render_ack_overlay(stdscr, startup=False)
        if self.show_startup_overlay:
            self._render_ack_overlay(stdscr, startup=True)

        stdscr.refresh()

    def _render_help(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        lines = [
            "Navigation: ←/→/j/k, Home/End, Tab panel focus",
            "Ordering: O cycle ordering, F cycle freq profile",
            "JP panel: m toggles kana/romaji",
            "Filter: Shift-N toggles hide-no-reading (scope by language visibility/focus)",
            "Search: / open, Enter run/jump, Shift-Up/Down jump top/bottom",
            "Radicals: r open, arrows move, Enter select, [/] stroke filter",
            "Panels: 1 JP, 2 CN, 3 Sentences, 4 Variants",
            "Variants panel: arrows select variant, Enter jump",
            "Overlays: c Components, s Phonetics, p Provenance, u User panel",
            "Workspace: b toggle bookmark, B bookmarks list/jump",
            "Bookmarks list: x deletes selected bookmark",
            "Notes: n per-glyph editor, g global editor",
            "Note editor: Enter newline, Ctrl+S save, Esc cancel",
            "Stroke order: t popup (only when data exists for current glyph)",
            "Setup: Shift-S opens source setup/download menu",
            "Acknowledgements: Shift-A overlay",
            "CCAMC: i open glyph page",
            "Global: ? Help, q Quit",
            "Data: Unicode Unihan, EDRDG KANJIDIC2/JMdict, CC-CEDICT",
            "License details in data/licenses/",
        ]
        box_w = min(max(len(line) for line in lines) + 4, w - 2)
        box_h = len(lines) + 2
        top = max(1, (h - box_h) // 2)
        left = max(1, (w - box_w) // 2)

        self._draw_box(stdscr, top, left, box_h, box_w, title="Help")
        for i, line in enumerate(lines):
            self._safe_add(stdscr, top + 1 + i, left + 2, line)

    def _render_search_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(14, h - 2)
        top = h - box_h - 1
        left = 1
        box_w = w - 2

        self._draw_box(stdscr, top, left, box_h, box_w, title="Search")

        self._safe_add(stdscr, top + 1, left + 2, f"Query: {self.search_input}")
        self._safe_add(
            stdscr,
            top + 2,
            left + 2,
            "Enter: run/jump  Esc: close  Up/Down: select  Shift-Up/Down or Home/End: top/bottom",
        )

        max_rows = box_h - 5
        start, end = visible_window(self.search_idx, len(self.search_results), max_rows)
        if not self.search_results and self.search_input:
            self._safe_add(stdscr, top + 3, left + 2, "(press Enter to run search)")
        for offset, row in enumerate(self.search_results[start:end]):
            idx = start + offset
            marker = "▶" if idx == self.search_idx else " "
            text = (
                f"{marker} {row['ch']} U+{row['cp']:04X}  JP:{row['jp']}  "
                f"CN:{row['cn']}  {row['gloss']}"
            )
            row_attr = curses.A_BOLD if idx == self.search_idx else 0
            self._safe_add(stdscr, top + 3 + offset, left + 2, text, row_attr)
        if self.search_results:
            self._safe_add(
                stdscr,
                top + box_h - 2,
                left + 2,
                f"Result {self.search_idx + 1}/{len(self.search_results)}",
            )
        try:
            cursor_x = min(w - 2, left + 2 + len("Query: ") + len(self.search_input))
            stdscr.move(top + 1, cursor_x)
        except curses.error:
            pass

    def _render_radical_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(14, h - 2)
        top = h - box_h - 1
        left = 1
        box_w = w - 2

        self._draw_box(stdscr, top, left, box_h, box_w, title="Radicals")

        if self.radical_results is None:
            self._safe_add(
                stdscr,
                top + 1,
                left + 2,
                "Arrow keys move, Enter select",
            )
            rows = max(1, box_h - 4)
            cols = max(1, min(self.radical_grid_cols, max(1, (box_w - 4) // 4)))
            self.radical_grid_cols = cols
            selected_row = self.radical_idx // cols
            start_row = max(0, selected_row - rows + 1)
            end_row = start_row + rows
            for row in range(start_row, end_row):
                y = top + 2 + (row - start_row)
                for col in range(cols):
                    idx = row * cols + col
                    if idx >= len(self.radical_numbers):
                        break
                    radical_num = self.radical_numbers[idx]
                    glyph = kangxi_radical_glyph(radical_num)
                    cell = f" {glyph} "
                    x = left + 2 + col * 4
                    if idx == self.radical_idx:
                        cell = f"┊{glyph}┊"
                    attr = curses.A_BOLD if idx == self.radical_idx else 0
                    self._safe_add(stdscr, y, x, cell, attr)
            selected_radical = self.radical_numbers[self.radical_idx]
            self._safe_add(stdscr, top + box_h - 2, left + 2, f"Selected: {kangxi_radical_glyph(selected_radical)}", curses.A_BOLD)
            return

        stroke_filter = self.radical_stroke_options[self.radical_stroke_idx]
        stroke_label = "all" if stroke_filter is None else str(stroke_filter)
        self._safe_add(
            stdscr,
            top + 1,
            left + 2,
            f"Radical results (Enter jump, Backspace back, [/] strokes={stroke_label})",
        )
        max_rows = box_h - 3
        start = max(0, self.radical_result_idx - max_rows + 1)
        for offset, cp in enumerate(self.radical_results[start : start + max_rows]):
            idx = start + offset
            marker = ">" if idx == self.radical_result_idx else " "
            row_attr = curses.A_BOLD if idx == self.radical_result_idx else 0
            self._safe_add(stdscr, top + 2 + offset, left + 2, f"{marker} {chr(cp)} U+{cp:04X}", row_attr)

    def _render_nav_strip(self, stdscr: curses.window, y: int) -> None:
        h, w = stdscr.getmaxyx()
        if y < 0 or y >= h:
            return
        strip = build_strip(self.ordered_cps, self.pos, radius=10)
        cell_width = 2
        total_width = len(strip) * cell_width
        start_x = max(0, (w - total_width) // 2)
        for idx, cell in enumerate(strip):
            x = start_x + idx * cell_width
            text = "· "
            if cell.cp is not None:
                text = f"{chr(cell.cp)} "
            attr = curses.A_BOLD if cell.is_current else curses.A_DIM
            if cell.is_current:
                attr |= curses.A_REVERSE
            self._safe_add(stdscr, y, x, text, attr)

    def _render_provenance_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(14, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        self._draw_box(stdscr, top, left, box_h, box_w, title="Provenance")

        rows = db_query.get_provenance(self.conn, cp, limit=box_h - 3)
        self._safe_add(stdscr, top + 1, left + 2, "p closes overlay")
        if not rows:
            hint = "(no provenance rows)"
            if self.derived_counts.get("field_provenance", 0) == 0:
                hint = "(no provenance rows; rebuild DB with current builder)"
            self._safe_add(stdscr, top + 2, left + 2, hint)
            return
        for idx, (field, value, source, conf) in enumerate(rows):
            text = f"{field}: {value} [{source} {conf:.2f}]"
            self._safe_add(stdscr, top + 2 + idx, left + 2, text)

    def _render_components_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(12, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        self._draw_box(stdscr, top, left, box_h, box_w, title="Components")
        self._safe_add(stdscr, top + 1, left + 2, "c closes overlay")
        components = db_query.get_components(self.conn, cp)
        if not components:
            hint = "(no components)"
            if self.derived_counts.get("components", 0) == 0:
                hint = "(no components rows; rebuild DB with current builder)"
            self._safe_add(stdscr, top + 2, left + 2, hint)
            return
        for idx, (comp_cp, comp_ch) in enumerate(components[: box_h - 3]):
            text = f"{idx + 1}. {comp_ch} U+{comp_cp:04X}"
            self._safe_add(stdscr, top + 2 + idx, left + 2, text)

    def _render_phonetic_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(12, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        self._draw_box(stdscr, top, left, box_h, box_w, title="Phonetic Series")
        self._safe_add(stdscr, top + 1, left + 2, "s closes overlay")
        series_rows = db_query.get_phonetic_series(self.conn, cp, limit=box_h - 3)
        if not series_rows:
            hint = "(no phonetic series rows)"
            if self.derived_counts.get("phonetic_series", 0) == 0:
                hint = "(no phonetic rows; rebuild DB with current builder)"
            self._safe_add(stdscr, top + 2, left + 2, hint)
            return
        for idx, (member_cp, member_ch, key, pinyin_marked, pinyin_numbered) in enumerate(
            series_rows[: box_h - 3]
        ):
            pinyin = pinyin_marked or search_normalize.pinyin_numbered_to_marked(
                pinyin_numbered
            )
            text = f"{idx + 1}. {member_ch} U+{member_cp:04X} [{key}]"
            if pinyin:
                text += f"  {pinyin}"
            self._safe_add(stdscr, top + 2 + idx, left + 2, text)

    def _render_user_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(20, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        self._draw_box(stdscr, top, left, box_h, box_w, title="User Workspace")
        self._safe_add(stdscr, top + 1, left + 2, "u closes overlay")
        if self.user_store is None:
            self._safe_add(stdscr, top + 2, left + 2, "(user store unavailable)")
            return
        glyph_notes = self.user_store.get_glyph_notes(cp, limit=4)
        global_notes = self.user_store.get_global_notes(limit=4)
        bookmarks = self.user_store.list_bookmarks(limit=6)
        queries = self.user_store.recent_queries(limit=4)
        self._safe_add(stdscr, top + 2, left + 2, "Glyph notes:")
        y = top + 3
        if not glyph_notes:
            self._safe_add(stdscr, y, left + 4, "(none)")
            y += 1
        else:
            for note in glyph_notes:
                self._safe_add(stdscr, y, left + 4, f"- {note}")
                y += 1
        self._safe_add(stdscr, y, left + 2, "Global notes:")
        y += 1
        if not global_notes:
            self._safe_add(stdscr, y, left + 4, "(none)")
            y += 1
        else:
            for note in global_notes:
                self._safe_add(stdscr, y, left + 4, f"- {note}")
                y += 1
        self._safe_add(stdscr, y, left + 2, "Bookmarks:")
        y += 1
        if not bookmarks:
            self._safe_add(stdscr, y, left + 4, "(none)")
            y += 1
        else:
            for bcp, tag in bookmarks[:3]:
                self._safe_add(
                    stdscr,
                    y,
                    left + 4,
                    f"- {chr(bcp)} U+{bcp:04X} {f'[{tag}]' if tag else ''}",
                )
                y += 1
                if y >= top + box_h - 3:
                    break
        self._safe_add(stdscr, y, left + 2, "Recent queries:")
        y += 1
        if not queries:
            self._safe_add(stdscr, y, left + 4, "(none)")
        else:
            for query in queries[:3]:
                self._safe_add(stdscr, y, left + 4, f"- {query}")
                y += 1

    def _render_note_input_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(14, h - 2)
        top = h - box_h - 1
        left = 1
        box_w = w - 2
        title = "Glyph Note" if self.note_target == "glyph" else "Global Note"
        self._draw_box(stdscr, top, left, box_h, box_w, title=title)
        self._safe_add(
            stdscr,
            top + 1,
            left + 2,
            "Enter newline  Ctrl+S save  Esc cancel  Arrows/Home/End move",
        )
        inner_w = max(10, box_w - 4)
        edit_rows = max(1, box_h - 3)
        lines = self.note_input_text.split("\n")
        cursor_line, cursor_col = self._note_cursor_line_col()
        start_line = 0
        if cursor_line >= edit_rows:
            start_line = cursor_line - edit_rows + 1
        for row_idx in range(edit_rows):
            src_idx = start_line + row_idx
            if src_idx >= len(lines):
                break
            self._safe_add(stdscr, top + 2 + row_idx, left + 2, lines[src_idx][:inner_w])
        try:
            screen_line = top + 2 + (cursor_line - start_line)
            screen_col = left + 2 + min(cursor_col, inner_w - 1)
            stdscr.move(screen_line, screen_col)
        except curses.error:
            pass

    def _render_bookmark_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(14, h - 2)
        top = h - box_h - 1
        left = 1
        box_w = w - 2
        self._draw_box(stdscr, top, left, box_h, box_w, title="Bookmarks")
        self._safe_add(
            stdscr,
            top + 1,
            left + 2,
            "Enter jump  x delete  Esc close  Up/Down select  Home/End top/bottom",
        )
        if not self.bookmark_rows:
            self._safe_add(stdscr, top + 2, left + 2, "(no bookmarks)")
            return
        max_rows = box_h - 3
        start, end = visible_window(self.bookmark_idx, len(self.bookmark_rows), max_rows)
        for offset, (cp, tag) in enumerate(self.bookmark_rows[start:end]):
            idx = start + offset
            marker = "▶" if idx == self.bookmark_idx else " "
            text = f"{marker} {chr(cp)} U+{cp:04X}"
            if tag:
                text += f" [{tag}]"
            row_attr = curses.A_BOLD if idx == self.bookmark_idx else 0
            self._safe_add(stdscr, top + 2 + offset, left + 2, text, row_attr)

    def _render_setup_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(22, h - 2)
        box_w = min(132, w - 2)
        top = max(1, (h - box_h) // 2)
        left = max(1, (w - box_w) // 2)
        self._draw_box(stdscr, top, left, box_h, box_w, title="Setup (Lean Package)")
        self._safe_add(
            stdscr,
            top + 1,
            left + 2,
            "Up/Down: move  Space/Enter/1-9: toggle  d: download  a: all  n: none  Esc: close",
            curses.A_BOLD,
        )
        self._safe_add(stdscr, top + 2, left + 2, "Source", curses.A_BOLD)
        self._safe_add(stdscr, top + 2, left + 58, "License / Terms URL", curses.A_BOLD)
        available = self._available_sources()
        max_rows = min(8, box_h - 9)
        for row in range(max_rows):
            if row >= len(self.setup_rows):
                break
            key = self.setup_rows[row]
            spec = SOURCES[key]
            checked = "x" if key in self.setup_selected else " "
            status = "installed" if available.get(key, False) else "missing"
            marker = "▶" if row == self.setup_idx else " "
            text = f"{marker} {row + 1}. [{checked}] {spec.label:<34}  ({status})"
            attr = curses.A_BOLD if row == self.setup_idx else 0
            row_y = top + 3 + row
            self._safe_add(stdscr, row_y, left + 2, text, attr)
            right_w = max(0, box_w - 60)
            self._safe_add(stdscr, row_y, left + 58, spec.license_url[:right_w], curses.A_DIM)

        self._safe_add(stdscr, top + 3 + max_rows, left + 2, "Logs:", curses.A_BOLD)
        log_rows = box_h - (7 + max_rows)
        start = max(0, len(self.setup_logs) - log_rows)
        for i, line in enumerate(self.setup_logs[start : start + log_rows]):
            self._safe_add(stdscr, top + 4 + max_rows + i, left + 2, line[: max(0, box_w - 4)])

    def _render_ack_overlay(self, stdscr: curses.window, startup: bool) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(22, h - 2)
        box_w = min(120, w - 2)
        top = max(1, (h - box_h) // 2)
        left = max(1, (w - box_w) // 2)
        title = "Startup / Acknowledgements" if startup else "Acknowledgements"
        self._draw_box(stdscr, top, left, box_h, box_w, title=title)
        presence = self._available_sources()
        lines = acknowledgements_for_sources(presence)
        if startup:
            lines = [
                "Welcome to kanjitui.",
                "Press any key to dismiss this page.",
                "Press Shift-S for setup downloads, Shift-A to reopen acknowledgements.",
                "",
            ] + lines
        else:
            lines.insert(0, "Shift-A or Esc closes this overlay.")
            lines.insert(1, "")
        max_rows = box_h - 2
        for i, line in enumerate(lines[:max_rows]):
            self._safe_add(stdscr, top + 1 + i, left + 2, line[: max(0, box_w - 4)])

    def _render_stroke_overlay(self, stdscr: curses.window) -> None:
        if self.stroke_data is None:
            return
        h, w = stdscr.getmaxyx()
        top, left, box_h, box_w = self._stroke_overlay_geometry(h, w)
        self._ensure_stroke_frames(h, w)
        title = f"Stroke Order: {self.stroke_data.ch} (Esc closes)"
        self._draw_box(stdscr, top, left, box_h, box_w, title=title)
        status = "done" if self.stroke_done else "animating"
        self._safe_add(
            stdscr,
            top + 1,
            left + 2,
            f"{status}  strokes={len(self.stroke_data.strokes)}  source={self.stroke_data.source_path.name}",
        )
        frame_idx = max(0, min(self.stroke_frame_idx, max(0, len(self.stroke_frames) - 1)))
        frame = self.stroke_frames[frame_idx] if self.stroke_frames else []
        max_rows = max(1, box_h - 5)
        max_cols = max(1, box_w - 4)
        for row_idx in range(max_rows):
            if row_idx >= len(frame):
                break
            self._safe_add(stdscr, top + 2 + row_idx, left + 2, frame[row_idx][:max_cols])
        if self.stroke_frames:
            self._safe_add(
                stdscr,
                top + box_h - 2,
                left + 2,
                f"frame {frame_idx + 1}/{len(self.stroke_frames)}",
            )

def run_tui(
    conn: sqlite3.Connection,
    normalizer_name: str = "default",
    user_store: UserStore | None = None,
) -> None:
    app = TuiApp(conn, normalizer_name=normalizer_name, user_store=user_store)
    curses.wrapper(app.run)
