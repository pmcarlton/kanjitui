from __future__ import annotations

import curses
import sqlite3
import webbrowser

from kanjitui.db import query as db_query
from kanjitui.db.user import UserStore
from kanjitui.search.query import SearchEngine
from kanjitui.tui.imagelinks import ImageLink, cc_image_links
from kanjitui.tui.navigation import build_strip, move_grid_index
from kanjitui.tui.radicals import all_kangxi_radical_numbers, kangxi_radical_glyph
from kanjitui.tui.router import KeyRouter


ORDERINGS = ["freq", "radical", "reading", "codepoint"]


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
        self.show_variant_graph = False
        self.show_components = False
        self.show_phonetic = False

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
        self.image_panel_open = False
        self.image_links: list[ImageLink] = []
        self.image_idx = 0

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
        self.router.register("image", self._handle_image_key)

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

    def _refresh_ordering(self) -> None:
        current = self.current_cp
        self.ordered_cps = db_query.get_ordered_cps(
            self.conn,
            ORDERINGS[self.ordering_idx],
            self.focus,
            self.current_freq_profile,
        )
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
        if self.image_panel_open:
            return "image"
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
            if ORDERINGS[self.ordering_idx] == "reading":
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
            return True
        if key == ord("2"):
            self.show_cn = not self.show_cn
            return True
        if key == ord("3"):
            self.show_sentences = not self.show_sentences
            return True
        if key in (ord("v"), ord("V")):
            self.show_variants = not self.show_variants
            return True
        if key in (ord("p"), ord("P")):
            self.show_provenance = not self.show_provenance
            self.show_variant_graph = False if self.show_provenance else self.show_variant_graph
            return True
        if key in (ord("g"), ord("G")):
            self.show_variant_graph = not self.show_variant_graph
            self.show_provenance = False if self.show_variant_graph else self.show_provenance
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
        if key in (ord("n"), ord("N")):
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
            self.image_panel_open = True
            self.image_idx = 0
            self.image_links = cc_image_links(chr(cp), cp)
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
                self.message = f"Radical {radical}: {len(self.radical_results)} chars"
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
            self.message = (
                f"Radical {self.radical_selected} strokes={stroke_filter if stroke_filter is not None else 'all'} "
                f"({len(self.radical_results)})"
            )
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
            self.message = (
                f"Radical {self.radical_selected} strokes={stroke_filter if stroke_filter is not None else 'all'} "
                f"({len(self.radical_results)})"
            )
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

    def _handle_image_key(self, key: int) -> bool | None:
        if key in (27, ord("i"), ord("I")):
            self.image_panel_open = False
            self.message = "Closed image links"
            return True
        if key in (curses.KEY_UP, ord("k")) and self.image_links:
            self.image_idx = max(0, self.image_idx - 1)
            return True
        if key in (curses.KEY_DOWN, ord("j")) and self.image_links:
            self.image_idx = min(len(self.image_links) - 1, self.image_idx + 1)
            return True
        if key in (ord("o"), ord("O"), 10, 13, curses.KEY_ENTER):
            if self.image_links:
                target = self.image_links[self.image_idx]
                webbrowser.open(target.url)
                self.message = f"Opened: {target.label}"
            return True
        return True

    def _safe_add(self, stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = stdscr.getmaxyx()
        if y < 0 or y >= h:
            return
        clipped = text[: max(0, w - x - 1)]
        if clipped:
            stdscr.addstr(y, x, clipped, attr)

    def _render(self, stdscr: curses.window) -> None:
        stdscr.erase()
        h, _ = stdscr.getmaxyx()

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
        header = (
            f"{detail['ch']}{bookmark_marker} U+{detail['cp']:04X}  radical {detail['radical'] or '-'}  "
            f"strokes {detail['strokes'] or '-'}  [{self.focus.upper()} focus] "
            f"({idx}/{total}) order:{order_label}"
        )
        self._safe_add(stdscr, 0, 0, header, curses.A_BOLD)

        y = 2
        if self.show_jp:
            attr = curses.A_REVERSE if self.focus == "jp" else 0
            self._safe_add(stdscr, y, 0, "JP", attr)
            y += 1
            on = " ".join(detail["jp_on"]) if detail["jp_on"] else "(none)"
            kun = " ".join(detail["jp_kun"]) if detail["jp_kun"] else "(none)"
            self._safe_add(stdscr, y, 2, f"readings on: {on} | kun: {kun}")
            y += 1
            jp_gloss = "; ".join(detail["jp_gloss"][:3]) if detail["jp_gloss"] else "(none)"
            self._safe_add(stdscr, y, 2, f"gloss: {jp_gloss}")
            y += 1
            self._safe_add(stdscr, y, 2, "words:")
            y += 1
            words = detail["jp_words"]
            if not words:
                self._safe_add(stdscr, y, 4, "(no examples found)")
                y += 1
            else:
                for word, kana, gloss, rank in words[:5]:
                    self._safe_add(stdscr, y, 4, f"{rank}. {word}  {kana or '-'}  {gloss or '-'}")
                    y += 1
            y += 1

        if self.show_cn and y < h - 5:
            attr = curses.A_REVERSE if self.focus == "cn" else 0
            self._safe_add(stdscr, y, 0, "CN", attr)
            y += 1
            if detail["cn_readings"]:
                readings = "  ".join(f"{m} ({n})" for m, n in detail["cn_readings"][:5])
            else:
                readings = "(none)"
            self._safe_add(stdscr, y, 2, f"readings: {readings}")
            y += 1
            cn_gloss = "; ".join(detail["cn_gloss"][:3]) if detail["cn_gloss"] else "(none)"
            self._safe_add(stdscr, y, 2, f"gloss: {cn_gloss}")
            y += 1
            self._safe_add(stdscr, y, 2, "words:")
            y += 1
            words = detail["cn_words"]
            if not words:
                self._safe_add(stdscr, y, 4, "(no examples found)")
                y += 1
            else:
                for trad, simp, marked, numbered, gloss, rank in words[:5]:
                    self._safe_add(
                        stdscr,
                        y,
                        4,
                        f"{rank}. {trad}/{simp}  {marked} ({numbered})  {gloss}",
                    )
                    y += 1
            y += 1

        if self.show_sentences and y < h - 5:
            self._safe_add(stdscr, y, 0, "Sentences", 0)
            y += 1
            sentence_rows = db_query.get_sentences(self.conn, detail["cp"], limit=3)
            if not sentence_rows:
                hint = "(no sentence examples)"
                if self.derived_counts.get("sentences", 0) == 0:
                    hint = "(no sentence examples; add sentences provider and rebuild DB)"
                self._safe_add(stdscr, y, 2, hint)
                y += 1
            else:
                for lang, text, reading, gloss, source, license_name, rank in sentence_rows:
                    line = f"{rank}. [{lang}] {text}  {reading or '-'}  {gloss or '-'}"
                    self._safe_add(stdscr, y, 2, line)
                    y += 1
                    self._safe_add(
                        stdscr,
                        y,
                        2,
                        f"   source: {source or '-'} ({license_name or '-'})",
                    )
                    y += 1
            y += 1

        if self.show_variants and y < h - 4:
            vars_text = ", ".join(
                f"{kind}->U+{target:04X}" for kind, target, _ in detail["variants"][:8]
            ) or "(none)"
            self._safe_add(stdscr, y, 0, f"Variants: {vars_text}")

        self._render_nav_strip(stdscr, h - 2)
        status = (
            "Arrows/jk:move Tab:focus O/F:order /:search r:radical 1/2/3/v c/s/p/g b/n/u/i ?:help q:quit | "
            f"{self.message}"
        )
        self._safe_add(stdscr, h - 1, 0, status, curses.A_REVERSE)

        if self.show_help:
            self._render_help(stdscr)
        if self.show_provenance:
            self._render_provenance_overlay(stdscr, detail["cp"])
        if self.show_variant_graph:
            self._render_variant_graph_overlay(stdscr, detail["cp"])
        if self.show_components:
            self._render_components_overlay(stdscr, detail["cp"])
        if self.show_phonetic:
            self._render_phonetic_overlay(stdscr, detail["cp"])
        if self.show_user_overlay:
            self._render_user_overlay(stdscr, detail["cp"])
        if self.note_input_open:
            self._render_note_input_overlay(stdscr)
        if self.image_panel_open:
            self._render_image_overlay(stdscr)
        if self.search_open:
            self._render_search_overlay(stdscr)
        if self.radical_open:
            self._render_radical_overlay(stdscr)

        stdscr.refresh()

    def _render_help(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        lines = [
            "Help",
            "Right/Down/j next, Left/Up/k previous",
            "Home/End jump, Tab focus JP/CN, O order",
            "F cycle frequency profile (if available)",
            "/ search (char, U+hex, kana, romaji, pinyin, gloss)",
            "r radical browser, 1/2 pane toggle, v variants",
            "3 sentences, c components, s phonetic series",
            "p provenance, g variant graph, ? help, q quit",
            "b bookmark, n note, u user overlay, i image links panel",
            "Data: Unicode Unihan, EDRDG KANJIDIC2/JMdict, CC-CEDICT",
            "License details: data/licenses/",
        ]
        box_w = min(max(len(line) for line in lines) + 4, w - 2)
        box_h = len(lines) + 2
        top = max(1, (h - box_h) // 2)
        left = max(1, (w - box_w) // 2)

        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)
        for i, line in enumerate(lines):
            self._safe_add(stdscr, top + 1 + i, left + 2, line, curses.A_REVERSE)

    def _render_search_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(12, h - 2)
        top = h - box_h - 1
        left = 1
        box_w = w - 2

        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)

        self._safe_add(stdscr, top + 1, left + 2, f"Search: {self.search_input}", curses.A_REVERSE)
        self._safe_add(
            stdscr,
            top + 2,
            left + 2,
            "Enter: run/jump  Esc: close  Up/Down: select",
            curses.A_REVERSE,
        )

        max_rows = box_h - 4
        for idx, row in enumerate(self.search_results[:max_rows]):
            marker = ">" if idx == self.search_idx else " "
            text = (
                f"{marker} {row['ch']} U+{row['cp']:04X}  JP:{row['jp']}  "
                f"CN:{row['cn']}  {row['gloss']}"
            )
            self._safe_add(stdscr, top + 3 + idx, left + 2, text, curses.A_REVERSE)

    def _render_radical_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(14, h - 2)
        top = h - box_h - 1
        left = 1
        box_w = w - 2

        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)

        if self.radical_results is None:
            self._safe_add(
                stdscr,
                top + 1,
                left + 2,
                "Radicals (Arrow keys in table, Enter select)",
                curses.A_REVERSE,
            )
            rows = max(1, box_h - 4)
            cols = max(1, min(self.radical_grid_cols, max(1, (box_w - 4) // 9)))
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
                    count = self.radical_counts.get(radical_num, 0)
                    cell = f"{glyph}{radical_num:03d}:{count:02d}"
                    x = left + 2 + col * 9
                    attr = curses.A_REVERSE | (curses.A_BOLD if idx == self.radical_idx else 0)
                    self._safe_add(stdscr, y, x, cell, attr)
            selected_radical = self.radical_numbers[self.radical_idx]
            selected_count = self.radical_counts.get(selected_radical, 0)
            self._safe_add(
                stdscr,
                top + box_h - 1,
                left + 2,
                f"Selected radical {selected_radical} {kangxi_radical_glyph(selected_radical)} ({selected_count} chars)",
                curses.A_REVERSE,
            )
            return

        stroke_filter = self.radical_stroke_options[self.radical_stroke_idx]
        stroke_label = "all" if stroke_filter is None else str(stroke_filter)
        self._safe_add(
            stdscr,
            top + 1,
            left + 2,
            f"Radical results (Enter jump, Backspace back, [/] strokes={stroke_label})",
            curses.A_REVERSE,
        )
        max_rows = box_h - 3
        start = max(0, self.radical_result_idx - max_rows + 1)
        for offset, cp in enumerate(self.radical_results[start : start + max_rows]):
            idx = start + offset
            marker = ">" if idx == self.radical_result_idx else " "
            self._safe_add(
                stdscr,
                top + 2 + offset,
                left + 2,
                f"{marker} {chr(cp)} U+{cp:04X}",
                curses.A_REVERSE,
            )

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
        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)

        rows = db_query.get_provenance(self.conn, cp, limit=box_h - 3)
        self._safe_add(stdscr, top + 1, left + 2, "Provenance (p to close)", curses.A_REVERSE)
        if not rows:
            hint = "(no provenance rows)"
            if self.derived_counts.get("field_provenance", 0) == 0:
                hint = "(no provenance rows; rebuild DB with current builder)"
            self._safe_add(stdscr, top + 2, left + 2, hint, curses.A_REVERSE)
            return
        for idx, (field, value, source, conf) in enumerate(rows):
            text = f"{field}: {value} [{source} {conf:.2f}]"
            self._safe_add(stdscr, top + 2 + idx, left + 2, text, curses.A_REVERSE)

    def _render_variant_graph_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(14, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)

        graph = db_query.variant_graph(self.conn, cp, depth=2, max_nodes=32)
        node_map = {node_cp: node_ch for node_cp, node_ch in graph["nodes"]}
        self._safe_add(stdscr, top + 1, left + 2, "Variant graph (g to close)", curses.A_REVERSE)
        self._safe_add(
            stdscr,
            top + 2,
            left + 2,
            f"nodes={len(graph['nodes'])} edges={len(graph['edges'])}",
            curses.A_REVERSE,
        )
        max_rows = box_h - 4
        for idx, (src, kind, dst) in enumerate(graph["edges"][:max_rows]):
            src_ch = node_map.get(src, chr(src))
            dst_ch = node_map.get(dst, chr(dst))
            text = f"{src_ch} U+{src:04X} -{kind}-> {dst_ch} U+{dst:04X}"
            self._safe_add(stdscr, top + 3 + idx, left + 2, text, curses.A_REVERSE)

    def _render_components_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(12, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)
        self._safe_add(stdscr, top + 1, left + 2, "Components (c to close)", curses.A_REVERSE)
        components = db_query.get_components(self.conn, cp)
        if not components:
            hint = "(no components)"
            if self.derived_counts.get("components", 0) == 0:
                hint = "(no components rows; rebuild DB with current builder)"
            self._safe_add(stdscr, top + 2, left + 2, hint, curses.A_REVERSE)
            return
        for idx, (comp_cp, comp_ch) in enumerate(components[: box_h - 3]):
            text = f"{idx + 1}. {comp_ch} U+{comp_cp:04X}"
            self._safe_add(stdscr, top + 2 + idx, left + 2, text, curses.A_REVERSE)

    def _render_phonetic_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(12, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)
        self._safe_add(stdscr, top + 1, left + 2, "Phonetic series (s to close)", curses.A_REVERSE)
        series_rows = db_query.get_phonetic_series(self.conn, cp, limit=box_h - 3)
        if not series_rows:
            hint = "(no phonetic series rows)"
            if self.derived_counts.get("phonetic_series", 0) == 0:
                hint = "(no phonetic rows; rebuild DB with current builder)"
            self._safe_add(stdscr, top + 2, left + 2, hint, curses.A_REVERSE)
            return
        for idx, (member_cp, member_ch, key) in enumerate(series_rows[: box_h - 3]):
            text = f"{idx + 1}. {member_ch} U+{member_cp:04X} [{key}]"
            self._safe_add(stdscr, top + 2 + idx, left + 2, text, curses.A_REVERSE)

    def _render_user_overlay(self, stdscr: curses.window, cp: int) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(16, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)
        self._safe_add(stdscr, top + 1, left + 2, "User workspace (u to close)", curses.A_REVERSE)
        if self.user_store is None:
            self._safe_add(stdscr, top + 2, left + 2, "(user store unavailable)", curses.A_REVERSE)
            return
        notes = self.user_store.get_notes(cp, limit=4)
        bookmarks = self.user_store.list_bookmarks(limit=6)
        queries = self.user_store.recent_queries(limit=4)
        self._safe_add(stdscr, top + 2, left + 2, "Notes:", curses.A_REVERSE)
        y = top + 3
        if not notes:
            self._safe_add(stdscr, y, left + 4, "(none)", curses.A_REVERSE)
            y += 1
        else:
            for note in notes:
                self._safe_add(stdscr, y, left + 4, f"- {note}", curses.A_REVERSE)
                y += 1
        self._safe_add(stdscr, y, left + 2, "Bookmarks:", curses.A_REVERSE)
        y += 1
        if not bookmarks:
            self._safe_add(stdscr, y, left + 4, "(none)", curses.A_REVERSE)
            y += 1
        else:
            for bcp, tag in bookmarks[:3]:
                self._safe_add(
                    stdscr,
                    y,
                    left + 4,
                    f"- {chr(bcp)} U+{bcp:04X} {f'[{tag}]' if tag else ''}",
                    curses.A_REVERSE,
                )
                y += 1
        self._safe_add(stdscr, y, left + 2, "Recent queries:", curses.A_REVERSE)
        y += 1
        if not queries:
            self._safe_add(stdscr, y, left + 4, "(none)", curses.A_REVERSE)
        else:
            for query in queries[:3]:
                self._safe_add(stdscr, y, left + 4, f"- {query}", curses.A_REVERSE)
                y += 1

    def _render_note_input_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = 5
        top = h - box_h - 1
        left = 1
        box_w = w - 2
        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)
        self._safe_add(stdscr, top + 1, left + 2, "Note (Enter save, Esc cancel):", curses.A_REVERSE)
        self._safe_add(stdscr, top + 2, left + 2, self.note_input_text, curses.A_REVERSE)

    def _render_image_overlay(self, stdscr: curses.window) -> None:
        h, w = stdscr.getmaxyx()
        box_h = min(12, h - 2)
        top = max(1, (h - box_h) // 2)
        left = 1
        box_w = w - 2
        for y in range(top, top + box_h):
            self._safe_add(stdscr, y, left, " " * box_w, curses.A_REVERSE)
        self._safe_add(
            stdscr,
            top + 1,
            left + 2,
            "CC image links (Up/Down select, Enter/o open, i/Esc close)",
            curses.A_REVERSE,
        )
        if not self.image_links:
            self._safe_add(stdscr, top + 2, left + 2, "(no links)", curses.A_REVERSE)
            return
        max_rows = box_h - 4
        for idx, link in enumerate(self.image_links[:max_rows]):
            marker = ">" if idx == self.image_idx else " "
            self._safe_add(stdscr, top + 2 + idx, left + 2, f"{marker} {link.label}", curses.A_REVERSE)
        selected = self.image_links[self.image_idx]
        self._safe_add(stdscr, top + box_h - 2, left + 2, f"Source: {selected.source}", curses.A_REVERSE)
        self._safe_add(stdscr, top + box_h - 1, left + 2, selected.license_note, curses.A_REVERSE)


def run_tui(
    conn: sqlite3.Connection,
    normalizer_name: str = "default",
    user_store: UserStore | None = None,
) -> None:
    app = TuiApp(conn, normalizer_name=normalizer_name, user_store=user_store)
    curses.wrapper(app.run)
