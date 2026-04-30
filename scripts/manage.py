#!/usr/bin/env python3
"""
Memoria 记忆管理工具 - 列表、统计、清理、合并

用法:
    # 列出所有记忆（默认热缓存）
    python3 manage.py list
    
    # 列出所有记忆（包含 archive）
    python3 manage.py list --all
    
    # 按标签过滤
    python3 manage.py list --tags "Clara,教训"
    
    # 显示统计信息
    python3 manage.py stats
    
    # 检测重复/相似内容
    python3 manage.py dupes
    
    # 删除记忆
    python3 manage.py delete --id <memory_id>
    
    # 合并两条记忆
    python3 manage.py merge --ids <id1>,<id2> --content "合并后的内容"
    
    # 标记重要度
    python3 manage.py tag --id <memory_id> --importance 0.8
    
    # 私密区操作
    python3 manage.py list --private
    python3 manage.py stats --private
"""

import argparse
import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import re

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.hot_cache import read_hot_cache, write_hot_cache, list_hot_cache
from lib.archive import list_archive_txts, read_archive_txt
from lib.vector import delete_vector
from lib.config import MEMORIA_ROOT, PROTECTION_TAGS

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _extract_uuid_from_filename(filename: str) -> str:
    """从文件名提取 UUID"""
    match = UUID_RE.search(filename)
    return match.group() if match else None


def _load_all_memories(private: bool = False) -> list[dict]:
    """加载所有记忆（热缓存 + archive）"""
    memories = []
    seen_ids = set()
    
    # 1. 先加载热缓存
    for entry in list_hot_cache(private=private):
        mid = entry.get("memory_id") or entry.get("id")
        if mid and mid not in seen_ids:
            entry["_source"] = "hot_cache"
            memories.append(entry)
            seen_ids.add(mid)
    
    # 2. 扫描 archive
    for archive_path in list_archive_txts(private=private):
        # 跳过 dormant
        if "dormant" in archive_path:
            continue
        
        mid = _extract_uuid_from_filename(archive_path)
        if mid and mid not in seen_ids:
            data = read_archive_txt(archive_path)
            if data:
                entry = {
                    "id": mid,
                    "memory_id": mid,
                    "summary": data.get("content", "")[:200],
                    "tags": data.get("tags", []),
                    "links": data.get("links", []),
                    "timestamp": data.get("created"),
                    "source": data.get("source", "archive"),
                    "archive_path": archive_path,
                    "_source": "archive"
                }
                memories.append(entry)
                seen_ids.add(mid)
    
    return memories


def cmd_list(args):
    """列出记忆"""
    memories = _load_all_memories(private=args.private)
    
    # 标签过滤
    if args.tags:
        filter_tags = set(t.strip() for t in args.tags.split(",") if t.strip())
        memories = [m for m in memories if filter_tags & set(m.get("tags", []))]
    
    # 链接过滤
    if args.links:
        filter_links = set(l.strip() for l in args.links.split(",") if l.strip())
        memories = [m for m in memories if filter_links & set(m.get("links", []))]
    
    # 时间范围过滤
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
            memories = [m for m in memories if m.get("timestamp") and 
                       datetime.fromisoformat(m.get("timestamp").replace("Z", "+00:00")) >= since_dt]
        except:
            print(f"⚠️ 时间格式错误: {args.since}", file=sys.stderr)
    
    # 排序
    if args.sort == "time":
        memories.sort(key=lambda x: x.get("timestamp", ""), reverse=not args.asc)
    elif args.sort == "importance":
        memories.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
    
    # 限制数量
    if args.limit:
        memories = memories[:args.limit]
    
    # 输出
    if args.json:
        print(json.dumps(memories, ensure_ascii=False, indent=2))
    else:
        _print_table(memories, args.verbose)
    
    print(f"\n共 {len(memories)} 条记忆", file=sys.stderr)


def _print_table(memories: list[dict], verbose: bool = False):
    """打印表格格式"""
    if not memories:
        print("(无记忆)")
        return
    
    # 计算列宽
    id_width = min(8, max(len(m.get("memory_id", "")[:8]) for m in memories))
    
    # 表头
    if verbose:
        print(f"{'ID':<{id_width}} │ {'时间':<19} │ {'标签':<20} │ {'摘要'}")
        print("─" * (id_width + 3 + 19 + 3 + 20 + 3 + 50))
    else:
        print(f"{'ID':<{id_width}} │ {'标签':<15} │ {'摘要'}")
        print("─" * (id_width + 3 + 15 + 3 + 60))
    
    for m in memories:
        mid = (m.get("memory_id") or m.get("id", ""))[:id_width]
        tags = ", ".join(m.get("tags", []))[:15 if not verbose else 20]
        summary = m.get("summary", "(无摘要)").replace("\n", " ")[:50 if not verbose else 100]
        
        if verbose:
            ts = m.get("timestamp", "")[:19] if m.get("timestamp") else ""
            print(f"{mid:<{id_width}} │ {ts:<19} │ {tags:<20} │ {summary}")
        else:
            print(f"{mid:<{id_width}} │ {tags:<15} │ {summary}")


def cmd_stats(args):
    """显示统计信息"""
    memories = _load_all_memories(private=args.private)
    
    if not memories:
        print("暂无记忆")
        return
    
    # 基础统计
    total = len(memories)
    from_hot = sum(1 for m in memories if m.get("_source") == "hot_cache")
    from_archive = sum(1 for m in memories if m.get("_source") == "archive")
    
    # 标签统计
    all_tags = []
    all_links = []
    sources = []
    for m in memories:
        all_tags.extend(m.get("tags", []))
        all_links.extend(m.get("links", []))
        sources.append(m.get("source", "unknown"))
    
    tag_counts = Counter(all_tags)
    link_counts = Counter(all_links)
    source_counts = Counter(sources)
    
    # 时间分布
    dates = []
    for m in memories:
        ts = m.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                dates.append(dt.strftime("%Y-%m"))
            except:
                pass
    date_counts = Counter(dates)
    
    # 输出
    print("=" * 50)
    print("📊 Memoria 统计报告")
    print("=" * 50)
    print(f"\n📦 总体")
    print(f"   总记忆数: {total}")
    print(f"   热缓存:   {from_hot}")
    print(f"   Archive:  {from_archive}")
    
    print(f"\n🏷️ 热门标签 (Top 10)")
    for tag, count in tag_counts.most_common(10):
        bar = "█" * min(count, 20)
        print(f"   {tag:<15} {count:>3} {bar}")
    
    if link_counts:
        print(f"\n🔗 热门链接 (Top 5)")
        for link, count in link_counts.most_common(5):
            print(f"   {link:<15} {count:>3}")
    
    print(f"\n📅 时间分布")
    for date, count in sorted(date_counts.items()):
        bar = "█" * min(count, 20)
        print(f"   {date}  {count:>3} {bar}")
    
    print(f"\n📥 来源分布")
    for src, count in source_counts.most_common():
        print(f"   {src:<15} {count:>3}")
    
    # 潜在问题
    print(f"\n⚠️ 潜在问题")
    no_tags = sum(1 for m in memories if not m.get("tags"))
    no_summary = sum(1 for m in memories if not m.get("summary"))
    short_summary = sum(1 for m in memories if m.get("summary") and len(m.get("summary")) < 20)
    
    print(f"   无标签:       {no_tags}")
    print(f"   无摘要:       {no_summary}")
    print(f"   摘要过短:     {short_summary}")


def cmd_dupes(args):
    """检测重复/相似内容"""
    memories = _load_all_memories(private=args.private)
    
    if len(memories) < 2:
        print("记忆数量不足，无法检测重复")
        return
    
    print("🔍 检测重复/相似记忆...")
    
    # 简单相似度检测（基于摘要关键词重叠）
    duplicates = []
    threshold = args.threshold
    
    for i, m1 in enumerate(memories):
        s1 = m1.get("summary", "")
        words1 = set(s1.lower().split())
        
        for m2 in memories[i+1:]:
            s2 = m2.get("summary", "")
            words2 = set(s2.lower().split())
            
            if not words1 or not words2:
                continue
            
            # Jaccard 相似度
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            similarity = intersection / union if union > 0 else 0
            
            if similarity >= threshold:
                duplicates.append({
                    "id1": m1.get("memory_id"),
                    "id2": m2.get("memory_id"),
                    "similarity": round(similarity, 2),
                    "summary1": s1[:50],
                    "summary2": s2[:50]
                })
    
    # 按相似度排序
    duplicates.sort(key=lambda x: x["similarity"], reverse=True)
    
    if not duplicates:
        print("✅ 未发现明显重复")
        return
    
    print(f"\n发现 {len(duplicates)} 组可能重复:\n")
    for d in duplicates[:args.limit]:
        print(f"相似度: {d['similarity']*100:.0f}%")
        print(f"  {d['id1'][:8]}: {d['summary1']}")
        print(f"  {d['id2'][:8]}: {d['summary2']}")
        print(f"  合并: python3 manage.py merge --ids {d['id1']},{d['id2']}")
        print()


def cmd_delete(args):
    """删除记忆"""
    mid = args.id
    private = args.private
    
    print(f"🗑️ 删除记忆: {mid}")
    
    if not args.force:
        confirm = input("确认删除? [y/N]: ")
        if confirm.lower() != "y":
            print("已取消")
            return
    
    # 1. 从热缓存删除
    cache = read_hot_cache(private=private)
    if mid in cache:
        del cache[mid]
        write_hot_cache(cache, private=private)
        print("  ✓ 从热缓存删除")
    
    # 2. 从向量库删除
    delete_vector(mid)
    print("  ✓ 从向量库删除")
    
    # 3. 删除 archive 文件
    for archive_path in list_archive_txts(private=private):
        if mid in archive_path:
            full_path = MEMORIA_ROOT / (f"private/memories/" if private else "") / archive_path
            if full_path.exists():
                full_path.unlink()
                print(f"  ✓ 删除文件: {archive_path}")
    
    print("✅ 删除完成")


def cmd_merge(args):
    """合并记忆"""
    ids = args.ids.split(",")
    if len(ids) != 2:
        print("错误: 需要两个 ID，用逗号分隔")
        return
    
    id1, id2 = ids[0].strip(), ids[1].strip()
    private = args.private
    
    print(f"🔗 合并记忆: {id1[:8]} + {id2[:8]}")
    
    # 获取两条记忆
    m1 = None
    m2 = None
    for m in _load_all_memories(private=private):
        if m.get("memory_id") == id1:
            m1 = m
        if m.get("memory_id") == id2:
            m2 = m
    
    if not m1 or not m2:
        print("错误: 找不到指定的记忆")
        return
    
    # 合并内容
    new_content = args.content or f"{m1.get('summary', '')}\n\n---\n\n{m2.get('summary', '')}"
    new_tags = list(set(m1.get("tags", []) + m2.get("tags", [])))
    new_links = list(set(m1.get("links", []) + m2.get("links", [])))
    
    # 保留 id1，删除 id2
    print(f"\n新内容:\n{new_content[:200]}...")
    print(f"\n标签: {new_tags}")
    print(f"链接: {new_links}")
    
    if not args.force:
        confirm = input("\n确认合并? [y/N]: ")
        if confirm.lower() != "y":
            print("已取消")
            return
    
    # 更新 id1
    from lib.hot_cache import update_hot_cache_entry
    update_hot_cache_entry(id1, new_content, new_tags, new_links, private=private)
    
    # 删除 id2
    delete_vector(id2)
    for archive_path in list_archive_txts(private=private):
        if id2 in archive_path:
            full_path = MEMORIA_ROOT / (f"private/memories/" if private else "") / archive_path
            if full_path.exists():
                full_path.unlink()
    
    print("✅ 合并完成")


def cmd_tag(args):
    """修改标签/重要度"""
    mid = args.id
    private = args.private
    
    # 找到记忆
    cache = read_hot_cache(private=private)
    entry = None
    
    if mid in cache and isinstance(cache[mid], dict):
        entry = cache[mid]
    
    if not entry:
        print(f"错误: 找不到记忆 {mid}")
        return
    
    # 修改标签
    if args.tags:
        new_tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        entry["tags"] = new_tags
        print(f"  标签更新: {new_tags}")
    
    # 修改重要度
    if args.importance is not None:
        entry["importance_score"] = max(0.0, min(1.0, args.importance))
        print(f"  重要度更新: {entry['importance_score']}")
    
    # 添加保护标签
    if args.protect:
        if "重要" not in entry.get("tags", []):
            entry["tags"] = entry.get("tags", []) + ["重要"]
            print("  已添加保护标签: 重要")
    
    # 保存
    write_hot_cache(cache, private=private)
    print("✅ 更新完成")


def main():
    parser = argparse.ArgumentParser(description="Memoria 记忆管理工具")
    parser.add_argument("--private", action="store_true", help="操作私密区")
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # list
    list_parser = subparsers.add_parser("list", help="列出记忆")
    list_parser.add_argument("--all", action="store_true", help="包含 archive")
    list_parser.add_argument("--tags", help="标签过滤，逗号分隔")
    list_parser.add_argument("--links", help="链接过滤，逗号分隔")
    list_parser.add_argument("--since", help="时间范围，如 2026-04-01")
    list_parser.add_argument("--sort", choices=["time", "importance"], default="time", help="排序方式")
    list_parser.add_argument("--asc", action="store_true", help="升序")
    list_parser.add_argument("--limit", type=int, help="限制数量")
    list_parser.add_argument("--json", action="store_true", help="JSON 输出")
    list_parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    list_parser.set_defaults(func=cmd_list)
    
    # stats
    stats_parser = subparsers.add_parser("stats", help="统计信息")
    stats_parser.set_defaults(func=cmd_stats)
    
    # dupes
    dupes_parser = subparsers.add_parser("dupes", help="检测重复")
    dupes_parser.add_argument("--threshold", type=float, default=0.7, help="相似度阈值")
    dupes_parser.add_argument("--limit", type=int, default=10, help="显示数量")
    dupes_parser.set_defaults(func=cmd_dupes)
    
    # delete
    delete_parser = subparsers.add_parser("delete", help="删除记忆")
    delete_parser.add_argument("--id", required=True, help="记忆 ID")
    delete_parser.add_argument("--force", action="store_true", help="强制删除")
    delete_parser.set_defaults(func=cmd_delete)
    
    # merge
    merge_parser = subparsers.add_parser("merge", help="合并记忆")
    merge_parser.add_argument("--ids", required=True, help="两个 ID，逗号分隔")
    merge_parser.add_argument("--content", help="合并后的内容")
    merge_parser.add_argument("--force", action="store_true", help="强制合并")
    merge_parser.set_defaults(func=cmd_merge)
    
    # tag
    tag_parser = subparsers.add_parser("tag", help="修改标签/重要度")
    tag_parser.add_argument("--id", required=True, help="记忆 ID")
    tag_parser.add_argument("--tags", help="新标签，逗号分隔")
    tag_parser.add_argument("--importance", type=float, help="重要度 0-1")
    tag_parser.add_argument("--protect", action="store_true", help="添加保护标签")
    tag_parser.set_defaults(func=cmd_tag)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
