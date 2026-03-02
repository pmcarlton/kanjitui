from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from urllib.parse import quote

from kanjitui.db import query as db_query
from kanjitui.db.user import UserStore
from kanjitui.search.query import SearchEngine
from kanjitui.tui.navigation import move_grid_index
from kanjitui.tui.radicals import all_kangxi_radical_numbers, kangxi_radical_glyph


ORDERINGS = ["freq", "radical", "reading", "codepoint"]


@dataclass
class GuiState:
    conn: sqlite3.Connection
    normalizer_name: str = "default"
    user_store: UserStore | None = None

    def __post_init__(self) -> None:
        self.search_engine = SearchEngine(self.conn, normalizer_name=self.normalizer_name)
        self.bookmarked_cps: set[int] = set()
        if self.user_store is not None:
            self.bookmarked_cps = {cp for cp, _ in self.user_store.list_bookmarks(limit=1000)}

        self.derived_counts = db_query.derived_data_counts(self.conn)
        self.jp_reading_cps, self.cn_reading_cps = db_query.reading_cp_sets(self.conn)

        self.focus = "jp"
        self.panel_focus = "jp"
        self.ordering_idx = 0
        self.freq_profiles = db_query.available_frequency_profiles(self.conn)
        self.freq_profile_idx = 0

        self.show_jp = True
        self.show_cn = True
        self.show_sentences = True
        self.show_variants = True
        self.show_help = False
        self.show_provenance = False
        self.show_components = False
        self.show_phonetic = False
        self.show_user_overlay = False
        self.show_jp_romaji = False
        self.hide_no_reading = False
        self.variant_idx = 0

        self.search_input = ""
        self.search_results: list[dict] = []
        self.search_idx = 0
        self.note_input_text = ""

        self.radical_numbers = all_kangxi_radical_numbers()
        self.radical_grid_cols = 14
        self.radical_idx = 0
        self.radical_results: list[int] | None = None
        self.radical_result_idx = 0
        self.radical_selected: int | None = None
        self.radical_stroke_options: list[int | None] = [None]
        self.radical_stroke_idx = 0

        self.message = "Ready"
        if self.derived_counts.get("field_provenance", 0) == 0:
            self.message = "DB missing derived rows (run --build to populate phase C/D features)"

        self.ordered_cps = db_query.get_ordered_cps(
            self.conn, ORDERINGS[self.ordering_idx], self.focus, self.current_freq_profile
        )
        self.pos = 0

    def reload_db_state(self, current_cp: int | None = None) -> None:
        self.search_engine = SearchEngine(self.conn, normalizer_name=self.normalizer_name)
        self.derived_counts = db_query.derived_data_counts(self.conn)
        self.jp_reading_cps, self.cn_reading_cps = db_query.reading_cp_sets(self.conn)
        self.freq_profiles = db_query.available_frequency_profiles(self.conn)
        if self.freq_profiles:
            self.freq_profile_idx = max(0, min(self.freq_profile_idx, len(self.freq_profiles) - 1))
        else:
            self.freq_profile_idx = 0

        self.refresh_ordering()
        if current_cp is not None and current_cp in self.ordered_cps:
            self.pos = self.ordered_cps.index(current_cp)
        elif self.ordered_cps:
            self.pos = max(0, min(self.pos, len(self.ordered_cps) - 1))
        else:
            self.pos = 0

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

    def reading_filter_scope(self) -> str:
        if ORDERINGS[self.ordering_idx] == "reading":
            return self.focus
        if self.show_jp and not self.show_cn:
            return "jp"
        if self.show_cn and not self.show_jp:
            return "cn"
        return "either"

    def sentence_langs(self) -> tuple[str, ...]:
        if self.show_jp and self.show_cn:
            return ("jp", "cn")
        if self.show_jp:
            return ("jp",)
        if self.show_cn:
            return ("cn",)
        return ("jp", "cn")

    def refresh_ordering(self) -> None:
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
            scope = self.reading_filter_scope()
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
            if allowed is not None and current in base_ordered:
                start = base_ordered.index(current)
                for offset in range(1, len(base_ordered) + 1):
                    candidate = base_ordered[(start + offset) % len(base_ordered)]
                    if candidate in allowed:
                        self.pos = self.ordered_cps.index(candidate)
                        return
            self.pos = 0

    def move_next(self) -> None:
        if self.ordered_cps:
            self.pos = min(self.pos + 1, len(self.ordered_cps) - 1)

    def move_prev(self) -> None:
        if self.ordered_cps:
            self.pos = max(self.pos - 1, 0)

    def move_home(self) -> None:
        self.pos = 0

    def move_end(self) -> None:
        if self.ordered_cps:
            self.pos = len(self.ordered_cps) - 1

    def toggle_focus(self) -> None:
        panels = self.visible_panel_focuses()
        if self.panel_focus not in panels:
            self.panel_focus = panels[0]
        else:
            idx = panels.index(self.panel_focus)
            self.panel_focus = panels[(idx + 1) % len(panels)]

        if self.panel_focus in ("jp", "cn") and self.focus != self.panel_focus:
            self.focus = self.panel_focus
            if ORDERINGS[self.ordering_idx] == "reading" or self.hide_no_reading:
                self.refresh_ordering()
        self.message = f"Panel focus: {self.panel_focus}"

    def visible_panel_focuses(self) -> list[str]:
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

    def ensure_panel_focus_valid(self) -> None:
        panels = self.visible_panel_focuses()
        if self.panel_focus not in panels:
            self.panel_focus = panels[0]
        if self.panel_focus in ("jp", "cn") and self.focus != self.panel_focus:
            self.focus = self.panel_focus
            if ORDERINGS[self.ordering_idx] == "reading" or self.hide_no_reading:
                self.refresh_ordering()

    def move_variant_selection(self, delta: int, count: int) -> None:
        if count <= 0:
            self.variant_idx = 0
            return
        self.variant_idx = max(0, min(count - 1, self.variant_idx + delta))

    def move_variant_home(self, count: int) -> None:
        if count <= 0:
            self.variant_idx = 0
            return
        self.variant_idx = 0

    def move_variant_end(self, count: int) -> None:
        if count <= 0:
            self.variant_idx = 0
            return
        self.variant_idx = count - 1

    def cycle_ordering(self) -> None:
        self.ordering_idx = (self.ordering_idx + 1) % len(ORDERINGS)
        self.refresh_ordering()
        if ORDERINGS[self.ordering_idx] == "freq" and self.current_freq_profile:
            self.message = f"Order: freq ({self.current_freq_profile})"
        else:
            self.message = f"Order: {ORDERINGS[self.ordering_idx]}"

    def cycle_freq_profile(self) -> None:
        if self.freq_profiles:
            self.freq_profile_idx = (self.freq_profile_idx + 1) % len(self.freq_profiles)
            if ORDERINGS[self.ordering_idx] == "freq":
                self.refresh_ordering()
            self.message = f"Freq profile: {self.current_freq_profile}"
        else:
            self.message = "No frequency profiles available"

    def toggle_no_reading(self) -> None:
        self.hide_no_reading = not self.hide_no_reading
        self.refresh_ordering()
        scope = self.reading_filter_scope()
        self.message = f"Hide no-reading: {'on' if self.hide_no_reading else 'off'} (scope={scope})"

    def jump_to_cp(self, cp: int) -> None:
        if cp in self.ordered_cps:
            self.pos = self.ordered_cps.index(cp)
            self.message = f"Jumped to U+{cp:04X}"

    def run_search(self, query: str) -> list[dict]:
        self.search_input = query
        self.search_results = self.search_engine.run(query, limit=200)
        self.search_idx = 0
        if self.user_store is not None:
            self.user_store.save_query(query)
        self.message = f"{len(self.search_results)} results"
        return self.search_results

    def toggle_bookmark(self) -> None:
        cp = self.current_cp
        if cp is None or self.user_store is None:
            self.message = "User workspace unavailable"
            return
        bookmarked = self.user_store.toggle_bookmark(cp)
        if bookmarked:
            self.bookmarked_cps.add(cp)
        else:
            self.bookmarked_cps.discard(cp)
        self.message = f"Bookmarked U+{cp:04X}" if bookmarked else f"Removed bookmark U+{cp:04X}"

    def delete_bookmark(self, cp: int) -> bool:
        if self.user_store is None:
            self.message = "User workspace unavailable"
            return False
        deleted = self.user_store.delete_bookmark(cp)
        if deleted:
            self.bookmarked_cps.discard(cp)
            self.message = f"Deleted bookmark U+{cp:04X}"
        else:
            self.message = f"Bookmark U+{cp:04X} not found"
        return deleted

    def list_bookmarks(self, limit: int = 200) -> list[tuple[int, str | None]]:
        if self.user_store is None:
            return []
        return self.user_store.list_bookmarks(limit=limit)

    def glyph_note_prefill(self) -> str:
        cp = self.current_cp
        if cp is None:
            return ""
        ch = chr(cp)
        return f"{ch} U+{cp:04X}\n"

    def save_glyph_note(self, note: str) -> None:
        cp = self.current_cp
        if cp is None or self.user_store is None:
            self.message = "User workspace unavailable"
            return
        text = note.strip()
        if not text:
            self.message = "Empty note ignored"
            return
        self.user_store.add_glyph_note(cp, text)
        self.message = f"Saved note for U+{cp:04X}"

    def save_global_note(self, note: str) -> None:
        if self.user_store is None:
            self.message = "User workspace unavailable"
            return
        text = note.strip()
        if not text:
            self.message = "Empty note ignored"
            return
        self.user_store.add_global_note(text)
        self.message = "Saved global note"

    def current_ccamc_url(self) -> str | None:
        cp = self.current_cp
        if cp is None:
            return None
        ch = chr(cp)
        return f"http://ccamc.org/cjkv.php?cjkv={quote(ch)}"

    def radical_pick(self, index: int) -> None:
        idx = max(0, min(index, len(self.radical_numbers) - 1))
        self.radical_idx = idx
        radical = self.radical_numbers[self.radical_idx]
        self.radical_selected = radical
        strokes = db_query.stroke_options_by_radical(self.conn, radical)
        self.radical_stroke_options = [None] + strokes
        self.radical_stroke_idx = 0
        self.radical_results = db_query.cps_by_radical(self.conn, radical, stroke_filter=None)
        self.radical_result_idx = 0
        self.message = f"Radical {kangxi_radical_glyph(radical)} selected"

    def radical_move_grid(self, direction: str) -> None:
        self.radical_idx = move_grid_index(
            self.radical_idx, len(self.radical_numbers), self.radical_grid_cols, direction
        )

    def radical_set_stroke_delta(self, delta: int) -> None:
        if self.radical_selected is None:
            return
        self.radical_stroke_idx = max(
            0,
            min(len(self.radical_stroke_options) - 1, self.radical_stroke_idx + delta),
        )
        stroke_filter = self.radical_stroke_options[self.radical_stroke_idx]
        self.radical_results = db_query.cps_by_radical(
            self.conn, self.radical_selected, stroke_filter=stroke_filter
        )
        self.radical_result_idx = 0
        self.message = f"Stroke filter: {stroke_filter if stroke_filter is not None else 'all'}"

    def radical_move_result(self, delta: int) -> None:
        if not self.radical_results:
            self.radical_result_idx = 0
            return
        self.radical_result_idx = max(
            0, min(len(self.radical_results) - 1, self.radical_result_idx + delta)
        )

    def radical_jump_selected(self) -> int | None:
        if not self.radical_results:
            return None
        cp = self.radical_results[self.radical_result_idx]
        self.jump_to_cp(cp)
        return cp
