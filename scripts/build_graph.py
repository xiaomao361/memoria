#!/usr/bin/env python3
"""
build_graph.py — 预计算 Memoria 力导向图数据
从 links.json 生成 graph.json，前端零计算直接渲染。
用法: python3 build_graph.py [--input links.json] [--output graph.json]
"""
import json, sys, os
from datetime import datetime, timezone


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(base, 'links.json')
    default_output = os.path.join(base, 'graph.json')

    input_path = default_input
    output_path = default_output

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg in ('-i', '--input') and i < len(sys.argv):
            input_path = sys.argv[i + 1]
        elif arg in ('-o', '--output') and i < len(sys.argv):
            output_path = sys.argv[i + 1]

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tags = data.get('tags', {})
    entities = data.get('entities', {})

    # 预转 set
    tag_sets = {k: set(v) for k, v in tags.items()}

    # 构建节点（保留 memoryIds 供面板查询）
    nodes = []
    for tag_id, uuids in tags.items():
        total_weight = 0
        sample_entity = None
        for uuid in uuids:
            ent = entities.get(uuid, {})
            total_weight += ent.get('weight', 1)
            if sample_entity is None:
                sample_entity = ent
        nodes.append({
            'id': tag_id,
            'count': len(uuids),
            'weight': total_weight,
            'memoryIds': uuids,
            'lastLinked': sample_entity.get('last_linked') if sample_entity else None,
        })

    # 构建连线 — O(n²) set 交集（在 Python 端做，前端不用算）
    links = []
    tag_keys = list(tags.keys())
    link_set = set()

    for i in range(len(tag_keys)):
        s1 = tag_sets[tag_keys[i]]
        for j in range(i + 1, len(tag_keys)):
            s2 = tag_sets[tag_keys[j]]
            small, big = (s1, s2) if len(s1) <= len(s2) else (s2, s1)
            common = [m for m in small if m in big]
            if not common:
                continue
            e1, e2 = tag_keys[i], tag_keys[j]
            key = f"{e1}|{e2}" if e1 < e2 else f"{e2}|{e1}"
            if key in link_set:
                continue
            link_set.add(key)

            lt = None
            for mid in common:
                ent = entities.get(mid, {})
                t = ent.get('last_linked')
                if t:
                    t_dt = datetime.fromisoformat(t)
                    if lt is None or t_dt > lt:
                        lt = t_dt
            links.append({
                'source': e1,
                'target': e2,
                'value': len(common),
                'lastCommonTime': lt.isoformat() if lt else None,
            })

    graph = {
        'nodes': nodes,
        'links': links,
        'generated': datetime.now(timezone.utc).isoformat(),
        'stats': {
            'nodes': len(nodes),
            'links': len(links),
            'entities': len(entities),
            'tags': len(tags),
        },
    }

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(graph, f, ensure_ascii=False, separators=(',', ':'))

    print(f"graph.json -> {output_path}")
    print(f"  nodes: {len(nodes)}, links: {len(links)}")


if __name__ == '__main__':
    main()
