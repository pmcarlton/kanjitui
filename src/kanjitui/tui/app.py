from __future__ import annotations

import curses
import sqlite3

from kanjitui.db import query as db_query
from kanjitui.search.query import SearchEngine
from kanjitui.tui.navigation import build_strip, move_grid_index
from kanjitui.tui.radicals import all_kangxi_radical_numbers, kangxi_radical_glyph
from kanjitui.tui.router import KeyRouter


ORDERINGS = ["freq", "radical", "reading", "codepoint"]


class TuiApp:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.search_engine = SearchEngine(conn)

        self.focus = "jp"
        self.ordering_idx = 0
        self.ordered_cps = db_query.get_ordered_cps(conn, ORDERINGS[self.ordering_idx], self.focus)
        self.pos = 0

        self.show_jp = True
        self.show_cn = True
        self.show_variants = True
        self.show_help = False

        self.message = "Ready"

        self.search_open = False
        self.search_input = ""
        self.search_results: list[dict] = []
        self.search_idx = 0

        self.radical_open = False
        self.radical_counts = dict(db_query.radical_counts(conn))
        self.radical_numbers = all_kangxi_radical_numbers()
        self.radical_grid_cols = 14
        self.radical_idx = 0
        self.radical_results: list[int] | None = None
        self.radical_result_idx = 0

        self.router = KeyRouter(self._current_mode, self._handle_normal_key)
        self.router.register("search", self._handle_search_key)
        self.router.register("radical", self._handle_radical_key)

    @property
    def current_cp(self) -> int | None:
        if not self.ordered_cps:
            return None
        self.pos = max(0, min(self.pos, len(self.ordered_cps) - 1))
        return self.ordered_cps[self.pos]

    def _refresh_ordering(self) -> None:
        current = self.current_cp
        self.ordered_cps = db_query.get_ordered_cps(self.conn, ORDERINGS[self.ordering_idx], self.focus)
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
            self.message = f"Order: {ORDERINGS[self.ordering_idx]}"
            return True

        if key == ord("1"):
            self.show_jp = not self.show_jp
            return True
        if key == ord("2"):
            self.show_cn = not self.show_cn
            return True
        if key in (ord("v"), ord("V")):
            self.show_variants = not self.show_variants
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
                self.radical_results = db_query.cps_by_radical(self.conn, radical)
                self.radical_result_idx = 0
                self.message = f"Radical {radical}: {len(self.radical_results)} chars"
                return True
            return True

        if key in (curses.KEY_UP, ord("k")):
            self.radical_result_idx = max(0, self.radical_result_idx - 1)
            return True
        if key in (curses.KEY_DOWN, ord("j")):
            self.radical_result_idx = min(len(self.radical_results) - 1, self.radical_result_idx + 1)
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.radical_results = None
            self.radical_result_idx = 0
            return True
        if key in (10, 13, curses.KEY_ENTER) and self.radical_results:
            cp = self.radical_results[self.radical_result_idx]
            self._jump_to_cp(cp)
            self.radical_open = False
            self.radical_results = None
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
        header = (
            f"{detail['ch']} U+{detail['cp']:04X}  radical {detail['radical'] or '-'}  "
            f"strokes {detail['strokes'] or '-'}  [{self.focus.upper()} focus] "
            f"({idx}/{total}) order:{ORDERINGS[self.ordering_idx]}"
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

        if self.show_variants and y < h - 4:
            vars_text = ", ".join(
                f"{kind}->U+{target:04X}" for kind, target, _ in detail["variants"][:8]
            ) or "(none)"
            self._safe_add(stdscr, y, 0, f"Variants: {vars_text}")

        self._render_nav_strip(stdscr, h - 2)
        status = (
            "Arrows/jk:move Tab:focus O:order /:search r:radical 1/2/v:toggle ?:help q:quit | "
            f"{self.message}"
        )
        self._safe_add(stdscr, h - 1, 0, status, curses.A_REVERSE)

        if self.show_help:
            self._render_help(stdscr)
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
            "/ search (char, U+hex, kana, romaji, pinyin, gloss)",
            "r radical browser, 1/2 pane toggle, v variants, ? help, q quit",
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

        self._safe_add(stdscr, top + 1, left + 2, "Radical results (Enter jump, Backspace back)", curses.A_REVERSE)
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


def run_tui(conn: sqlite3.Connection) -> None:
    app = TuiApp(conn)
    curses.wrapper(app.run)
