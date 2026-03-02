from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VariantTarget:
    cp: int
    ch: str
    relation: str


def build_variant_targets(current_cp: int, graph: dict) -> list[VariantTarget]:
    node_map: dict[int, str] = {
        int(node_cp): (node_ch or chr(int(node_cp)))
        for node_cp, node_ch in graph.get("nodes", [])
    }
    direct_relations: dict[int, set[str]] = {}
    all_cps: set[int] = set(node_map.keys())

    for raw_src, raw_kind, raw_dst in graph.get("edges", []):
        src = int(raw_src)
        dst = int(raw_dst)
        kind = str(raw_kind or "variant")
        all_cps.add(src)
        all_cps.add(dst)
        if src == current_cp and dst != current_cp:
            direct_relations.setdefault(dst, set()).add(kind)
        elif dst == current_cp and src != current_cp:
            direct_relations.setdefault(src, set()).add(kind)

    targets: list[VariantTarget] = []
    for cp in sorted(all_cps):
        if cp == current_cp:
            continue
        ch = node_map.get(cp, chr(cp))
        relation_set = direct_relations.get(cp)
        relation = ",".join(sorted(relation_set)) if relation_set else "indirect"
        targets.append(VariantTarget(cp=cp, ch=ch, relation=relation))
    return targets
