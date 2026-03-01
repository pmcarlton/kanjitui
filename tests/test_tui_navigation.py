from kanjitui.tui.navigation import build_strip, move_grid_index, visible_window


def test_build_strip_centers_current_with_radius() -> None:
    ordered = [0x4E00 + i for i in range(30)]
    strip = build_strip(ordered, pos=10, radius=10)

    assert len(strip) == 21
    assert strip[10].cp == ordered[10]
    assert strip[10].is_current is True
    assert strip[0].cp == ordered[0]
    assert strip[-1].cp == ordered[20]


def test_build_strip_handles_edges() -> None:
    ordered = [0x4E00 + i for i in range(5)]
    strip = build_strip(ordered, pos=0, radius=2)

    assert [cell.cp for cell in strip] == [None, None, ordered[0], ordered[1], ordered[2]]


def test_move_grid_index_directional_bounds() -> None:
    total = 10
    cols = 4

    assert move_grid_index(0, total, cols, "left") == 0
    assert move_grid_index(0, total, cols, "up") == 0
    assert move_grid_index(0, total, cols, "right") == 1
    assert move_grid_index(0, total, cols, "down") == 4
    assert move_grid_index(8, total, cols, "down") == 8


def test_visible_window_tracks_selection() -> None:
    start, end = visible_window(selected=0, total=20, max_rows=5)
    assert (start, end) == (0, 5)

    start, end = visible_window(selected=10, total=20, max_rows=5)
    assert (start, end) == (8, 13)

    start, end = visible_window(selected=19, total=20, max_rows=5)
    assert (start, end) == (15, 20)
