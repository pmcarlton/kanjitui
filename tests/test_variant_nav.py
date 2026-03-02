from __future__ import annotations

from kanjitui.variant_nav import build_variant_targets


def test_build_variant_targets_marks_direct_and_indirect() -> None:
    cp = 0x9B5A  # 魚
    graph = {
        "nodes": [
            (cp, "魚"),
            (0x9C7C, "鱼"),
            (0x9B54, "魔"),
        ],
        "edges": [
            (cp, "kSimplifiedVariant", 0x9C7C),
            (0x9B54, "kZVariant", 0x4E00),
        ],
    }

    targets = build_variant_targets(cp, graph)
    by_cp = {row.cp: row for row in targets}
    assert 0x9C7C in by_cp
    assert by_cp[0x9C7C].relation == "kSimplifiedVariant"
    assert by_cp[0x9C7C].ch == "鱼"
    assert 0x9B54 in by_cp
    assert by_cp[0x9B54].relation == "indirect"
