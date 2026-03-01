from __future__ import annotations

import curses
import sqlite3
import webbrowser
from urllib.parse import quote

from kanjitui.db import query as db_query
from kanjitui.db.user import UserStore
from kanjitui.search import normalize as search_normalize
from kanjitui.search.query import SearchEngine
from kanjitui.tui.navigation import build_strip, move_grid_index, visible_window
from kanjitui.tui.radicals import all_kangxi_radical_numbers, kangxi_radical_glyph
from kanjitui.tui.router import KeyRouter


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
        self.search_engine = SearchEngine(conn, normalizer_name=normalizer_name)
        self.user_store = user_store
        self.bookmarked_cps: set[int] = set()
        if self.user_store is not None:
            self.bookmarked_cps = {cp for cp, _ in self.user_store.list_bookmarks(limit=1000)}
        self.derived_counts = db_query.derived_data_counts(conn)
        self.jp_reading_cps, self.cn_reading_cps = db_query.reading_cp_sets(conn)

        self.focus = "jp"
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

        self.message = "Ready"
        if self.derived_counts.get("field_provenance", 0) == 0:
            self.message = "DB missing derived rows (run --build to populate phase C/D features)"

        self.search_open = False
        self.search_input = ""
        self.search_results: list[dict] = []
        self.search_idx = 0
        self.note_input_open = False
        self.note_input_text = ""
        self.show_user_overlay = False

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

        self.router = KeyRouter(self._current_mode, self._handle_normal_key)
        self.router.register("search", self._handle_search_key)
        self.router.register("radical", self._handle_radical_key)
        self.router.register("note", self._handle_note_key)

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

    def _refresh_ordering(self) -> None:
        current = self.current_cp
        ordered = db_query.get_ordered_cps(
            self.conn,
            ORDERINGS[self.ordering_idx],
            self.focus,
            self.current_freq_profile,
        )
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
            self.pos = 0

    def _jump_to_cp(self, cp: int) -> None:
        if cp in self.ordered_cps:
            self.pos = self.ordered_cps.index(cp)
            self.message = f"Jumped to U+{cp:04X}"

    def run(self, stdscr: curses.window) -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        while True:
            self._render(stdscr)
            key = stdscr.getch()
            if not self._handle_key(key):
                break

    def _current_mode(self) -> str:
        if self.search_open:
            return "search"
        if self.radical_open:
            return "radical"
        if self.note_input_open:
            return "note"
        return "normal"

    def _handle_key(self, key: int) -> bool:
        return self.router.dispatch(key)

    def _handle_normal_key(self, key: int) -> bool:
        if key in (ord("q"), ord("Q")):
            return False
        if key in (curses.KEY_RIGHT, curses.KEY_DOWN, ord("j")):
            if self.ordered_cps:
                self.pos = min(self.pos + 1, len(self.ordered_cps) - 1)
            return True
        if key in (curses.KEY_LEFT, curses.KEY_UP, ord("k")):
            if self.ordered_cps:
                self.pos = max(self.pos - 1, 0)
            return True
        if key == curses.KEY_HOME:
            self.pos = 0
            return True
        if key == curses.KEY_END:
            if self.ordered_cps:
                self.pos = len(self.ordered_cps) - 1
            return True

        if key == 9:  # Tab
            self.focus = "cn" if self.focus == "jp" else "jp"
            if ORDERINGS[self.ordering_idx] == "reading" or self.hide_no_reading:
                self._refresh_ordering()
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
            return True
        if key == ord("2"):
            self.show_cn = not self.show_cn
            if self.hide_no_reading:
                self._refresh_ordering()
            return True
        if key == ord("3"):
            self.show_sentences = not self.show_sentences
            return True
        if key in (ord("v"), ord("V")):
            self.show_variants = not self.show_variants
            return True
        if key in (ord("p"), ord("P")):
            self.show_provenance = not self.show_provenance
            return True
        if key in (ord("c"), ord("C")):
            self.show_components = not self.show_components
            if self.show_components:
                self.show_phonetic = False
            return True
        if key in (ord("s"), ord("S")):
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
        if key in (ord("b"), ord("B")):
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
        if key == ord("n"):
            if self.user_store is None:
                self.message = "User workspace unavailable"
                return True
            self.note_input_open = True
            self.note_input_text = ""
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

    def _handle_search_key(self, key: int) -> bool | None:
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

        if 32 <= key < 127:
            self.search_input += chr(key)
            self.search_results = []
            self.search_idx = 0
            return True

        return True

    def _handle_radical_key(self, key: int) -> bool | None:
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

    def _handle_note_key(self, key: int) -> bool | None:
        if key == 27:  # Esc
            self.note_input_open = False
            self.note_input_text = ""
            self.message = "Cancelled note entry"
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.note_input_text = self.note_input_text[:-1]
            return True
        if key in (10, 13, curses.KEY_ENTER):
            cp = self.current_cp
            if cp is not None and self.user_store is not None and self.note_input_text.strip():
                self.user_store.add_note(cp, self.note_input_text)
                self.message = f"Saved note for U+{cp:04X}"
            self.note_input_open = False
            self.note_input_text = ""
            return True
        if 32 <= key < 127:
            self.note_input_text += chr(key)
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
            self._safe_add(stdscr, 0, 0, "No characters in DB. Build and rerun.")
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

        self._render_nav_strip(stdscr, 2)
        y = 4
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
            jp_focus = ORDERINGS[self.ordering_idx] == "reading" and self.focus == "jp"
            y = self._render_section(stdscr, y, w, "JP", lines, highlighted=jp_focus) + 1

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
            cn_focus = ORDERINGS[self.ordering_idx] == "reading" and self.focus == "cn"
            y = self._render_section(stdscr, y, w, "CN", lines, highlighted=cn_focus) + 1

        if self.show_sentences and y < h - 5:
            sentence_rows = db_query.get_sentences(self.conn, detail["cp"], limit=3)
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
            y = self._render_section(stdscr, y, w, "Sentences", lines) + 1

        if self.show_variants and y < h - 4:
            graph = db_query.variant_graph(self.conn, detail["cp"], depth=2, max_nodes=32)
            node_map = {node_cp: node_ch for node_cp, node_ch in graph["nodes"]}
            lines = [f"nodes={len(graph['nodes'])} edges={len(graph['edges'])}"]
            if not graph["edges"]:
                lines.append("(no variant edges)")
            else:
                for src, kind, dst in graph["edges"][:8]:
                    src_ch = node_map.get(src, chr(src))
                    dst_ch = node_map.get(dst, chr(dst))
                    lines.append(f"{src_ch} U+{src:04X} -{kind}-> {dst_ch} U+{dst:04X}")
            y = self._render_section(stdscr, y, w, "Variants", lines)

        menu_line = (
            "Nav:←/→/j/k Home End Tab  Search:/  Radical:r  Panes:1 2 3 v  "
            "Overlays:c s p  User:b n u  JP:m  Filter:N  CCAMC:i  Order:O F  Help:?  Quit:q"
        )
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
        if self.search_open:
            self._render_search_overlay(stdscr)
        if self.radical_open:
            self._render_radical_overlay(stdscr)

        stdscr.refresh()

    def _render_help(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        lines = [
            "Navigation: ←/→/j/k, Home/End, Tab reading-sort target",
            "Ordering: O cycle ordering, F cycle freq profile",
            "JP panel: m toggles kana/romaji",
            "Filter: Shift-N toggles hide-no-reading (scope by language visibility/focus)",
            "Search: / open, Enter run/jump, Shift-Up/Down jump top/bottom",
            "Radicals: r open, arrows move, Enter select, [/] stroke filter",
            "Panels: 1 JP, 2 CN, 3 Sentences, v Variants",
            "Overlays: c Components, s Phonetics, p Provenance, u User panel",
            "Workspace: b Bookmark, n Note, i open CCAMC glyph page",
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
        for idx, (member_cp, member_ch, key) in enumerate(series_rows[: box_h - 3]):
            text = f"{idx + 1}. {member_ch} U+{member_cp:04X} [{key}]"
            self._safe_add(stdscr, top + 2 + idx, left + 2, text)

    def _render_user_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(16, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        self._draw_box(stdscr, top, left, box_h, box_w, title="User Workspace")
        self._safe_add(stdscr, top + 1, left + 2, "u closes overlay")
        if self.user_store is None:
            self._safe_add(stdscr, top + 2, left + 2, "(user store unavailable)")
            return
        notes = self.user_store.get_notes(cp, limit=4)
        bookmarks = self.user_store.list_bookmarks(limit=6)
        queries = self.user_store.recent_queries(limit=4)
        self._safe_add(stdscr, top + 2, left + 2, "Notes:")
        y = top + 3
        if not notes:
            self._safe_add(stdscr, y, left + 4, "(none)")
            y += 1
        else:
            for note in notes:
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
        box_h = 5
        top = h - box_h - 1
        left = 1
        box_w = w - 2
        self._draw_box(stdscr, top, left, box_h, box_w, title="Note")
        self._safe_add(stdscr, top + 1, left + 2, "Note (Enter save, Esc cancel):")
        self._safe_add(stdscr, top + 2, left + 2, self.note_input_text)

def run_tui(
    conn: sqlite3.Connection,
    normalizer_name: str = "default",
    user_store: UserStore | None = None,
) -> None:
    app = TuiApp(conn, normalizer_name=normalizer_name, user_store=user_store)
    curses.wrapper(app.run)
