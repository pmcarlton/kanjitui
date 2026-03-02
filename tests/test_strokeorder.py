from __future__ import annotations

from pathlib import Path

from kanjitui.strokeorder import StrokeOrderRepository, build_tui_stroke_frames, parse_path_points


def test_parse_path_points_supports_relative_curve() -> None:
    pts = parse_path_points("M10,10 c10,0 20,10 30,20")
    assert pts
    assert pts[0] == (10.0, 10.0)
    assert pts[-1][0] > 10.0
    assert pts[-1][1] > 10.0


def test_repo_load_and_build_frames(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "StrokeOrder"
    kanji = root / "kanji"
    kanji.mkdir(parents=True)
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 109 109">
  <g>
    <path d="M10,10 L90,10"/>
    <path d="M10,50 C30,70 70,70 90,50"/>
  </g>
</svg>"""
    (kanji / "魚").write_text(svg, encoding="utf-8")
    monkeypatch.setenv("KANJITUI_STROKEORDER_DIR", str(root))

    repo = StrokeOrderRepository()
    assert repo.has_char("魚") is True
    data = repo.load("魚")
    assert data is not None
    assert len(data.strokes) == 2
    frames = build_tui_stroke_frames(data, cols=30, rows=14)
    assert len(frames) >= 2
    assert any("#" in row for row in frames[-1])
