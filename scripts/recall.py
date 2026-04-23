#!/usr/bin/env python3
"""
Memoria 统一读取入口 recall()

用法:
    # 语义搜索
    python3 recall.py --query "之前讨论的队列方案"
    
    # 标签搜索
    python3 recall.py --tags "kraken,redis"
    
    # 精确定位
    python3 recall.py --memory-id "xxx" --include-content
    
    # 启动加载
    python3 recall.py --hot-cache --simple
    
    # 私密区搜索
    python3 recall.py --query "xxx" --private

返回:
    [
        {
            "memory_id": "xxx",
            "summary": "...",
            "tags": [...],
            "links": [...],
            "timestamp": "...",
            "source": "...",
            "content": "...",  # 仅 --include-content 时返回
            "private": false
        },
        ...
    ]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.archive import read_archive_txt, list_archive_txts
from lib.vector import search_vector, write_vector, delete_vector
from lib.hot_cache import list_hot_cache, get_from_hot_cache, update_last_recalled, get_importance_score, increment_recall_count, update_importance, read_hot_cache, write_hot_cache
from lib.links import get_memories_by_links
from lib.config import IMPORTANCE_RECALL_BONUS


# ═══════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _get_active_ids() -> set:
    """
    获取所有活跃记忆的 ID 集合。
    
    修复 Bug③：不再依赖热缓存（只有200条），而是扫描 archive 目录，
    找出所有非 dormant 的记忆 ID。
    
    Bug根因：文件名格式为 "标题-uuid.txt"，不能直接用 .stem 提取，
    必须用正则从文件名中找纯 UUID。
    """
    active_ids = set()
    
    for is_private in [False, True]:
        for month_path in list_archive_txts(private=is_private):
            parts = month_path.replace("\\", "/").split("/")
            if parts[0] == "dormant":
                continue  # dormant 不计入活跃
            filename = parts[-1].replace(".txt", "")
            # 用正则从文件名提取纯 UUID（文件名可能带标题前缀）
            match = UUID_RE.search(filename)
            if match:
                active_ids.add(match.group())
    
    return active_ids


def _filter_active_only(results: list[dict], private: bool = False) -> list[dict]:
    """
    只返回活跃记忆，过滤掉 dormant。
    
    Bug③ 修复：不再依赖热缓存白名单（200条上限会误杀活跃记忆），
    改为扫描 archive 目录获取完整的活跃 ID 集合。
    """
    active_ids = _get_active_ids()
    
    filtered = []
    for r in results:
        mid = r.get("memory_id")
        if mid in active_ids:
            filtered.append(r)
        # 如果不在 archive 中（热缓存残留），也保留（可能正在写入）
    
    return filtered


def _reactivate_from_dormant(
    memory_id: str,
    summary: str,
    tags: list[str],
    links: list[str],
    private: bool = False
) -> bool:
    """
    当 dormant 记忆被召回时，重新写入向量索引并恢复为活跃状态。
    
    Bug① 修复：
    - dormant 目录根据 private 区分（私密记忆 → private/memories/archive/dormant/）
    - 重新写回向量库时保持 private 属性
    - archive_path 恢复为正常路径（加 private/ 前缀）
    
    Args:
        memory_id: 记忆 ID
        summary: 摘要
        tags: 标签
        links: 链接
        private: 是否是私密记忆
    
    Returns:
        True if success
    """
    from lib.hot_cache import read_hot_cache, write_hot_cache
    from lib.archive import read_archive_txt
    from pathlib import Path
    
    # 1. 确定 dormant 目录路径
    if private:
        dormant_dir = Path.home() / ".qclaw/memoria/private/memories/archive/dormant"
    else:
        dormant_dir = Path.home() / ".qclaw/memoria/archive/dormant"
    
    archive_path = dormant_dir / f"{memory_id}.txt"
    
    # 2. 从 dormant archive 读取原文
    if archive_path.exists():
        archive_data = read_archive_txt(
            f"private/{dormant_dir.name}/{memory_id}.txt" if private 
            else f"dormant/{memory_id}.txt"
        )
        content = archive_data.get("content", summary) if archive_data else summary
    else:
        content = summary
    
    # 3. 重新写回向量库（保持 private 属性）
    if private:
        restored_archive_path = f"private/{datetime.now(timezone.utc).strftime('%Y-%m')}/{memory_id}.txt"
    else:
        restored_archive_path = f"{datetime.now(timezone.utc).strftime('%Y-%m')}/{memory_id}.txt"
    
    write_vector(
        memory_id=memory_id,
        archive_path=restored_archive_path,
        content=content,
        tags=tags,
        links=links,
        source="reactivated",
        private=private  # ← Bug① 修复：保持私密属性
    )
    
    # 4. 更新热缓存：恢复为活跃（兼容新旧格式）
    cache = read_hot_cache(private=private)
    
    # 新格式：dict key 直接寻址
    if memory_id in cache and isinstance(cache[memory_id], dict):
        cache[memory_id]["storage_type"] = "active"
        cache[memory_id]["last_recalled"] = datetime.now(timezone.utc).isoformat()
        cache[memory_id]["archive_path"] = restored_archive_path
    # 旧格式：memories 数组
    else:
        for m in cache.get("memories", []):
            mid = m.get("id") or m.get("memory_id")
            if mid == memory_id:
                m["storage_type"] = "active"
                m["last_recalled"] = datetime.now(timezone.utc).isoformat()
                m["archive_path"] = restored_archive_path
                break
    write_hot_cache(cache, private=private)
    
    print(f"   ✓ 唤醒沉睡记忆: {memory_id} {'(私密)' if private else ''}")
    return True


def _search_dormant(query: str, limit: int = 5, private: bool = False) -> list[dict]:
    """
    搜索沉睡记忆。
    
    支持公开和私密 dormant 目录。
    """
    results = []
    
    for is_private in ([False, True] if not private else [True]):
        if is_private:
            dormant_dir = Path.home() / ".qclaw/memoria/private/memories/archive/dormant"
        else:
            dormant_dir = Path.home() / ".qclaw/memoria/archive/dormant"
        
        if not dormant_dir.exists():
            continue
        
        for f in dormant_dir.glob("*.txt"):
            try:
                content = f.read_text(encoding="utf-8")
                if query.lower() in content.lower():
                    results.append({
                        "memory_id": f.stem,
                        "summary": content[:100],
                        "storage_type": "dormant",
                        "private": is_private
                    })
                    if len(results) >= limit:
                        return results
            except:
                continue
    
    return results


# ═══════════════════════════════════════════════════════════════════════
# 主要查询函数
# ═══════════════════════════════════════════════════════════════════════


def recall_by_tags(
    tags: list[str],
    limit: int = 5,
    include_content: bool = False,
    private: bool = False,
    include_dormant: bool = False
) -> list[dict]:
    """
    通过标签搜索
    
    Args:
        tags: 标签列表
        limit: 返回条数
        include_content: 是否包含原文
        private: 是否搜索私密区
        include_dormant: 是否包含沉睡记忆
    
    Returns:
        记忆列表
    """
    # 通过 links 索引获取 memory_id 列表
    memory_ids = get_memories_by_links(tags, private=private)
    
    if not memory_ids:
        return []
    
    results = []
    for memory_id in memory_ids[:limit]:
        result = {
            "memory_id": memory_id,
            "private": private
        }
        
        # 如果需要原文，从 archive 读取
        if include_content:
            # 找到对应的 archive 文件
            archive_paths = list_archive_txts(private=private)
            for ap in archive_paths:
                if memory_id in ap:
                    archive_data = read_archive_txt(ap)
                    if archive_data:
                        result["content"] = archive_data.get("content")
                        result["tags"] = archive_data.get("tags", [])
                        result["links"] = archive_data.get("links", [])
                        result["timestamp"] = archive_data.get("created")
                        result["source"] = archive_data.get("source")
                        result["summary"] = archive_data.get("content", "")[:100]
                        break
        
        results.append(result)
    
    # 过滤 dormant（除非明确要求包含）
    if not include_dormant:
        results = _filter_active_only(results, private=private)
    
    return results


def recall_by_query(
    query: str,
    limit: int = 5,
    include_content: bool = False,
    private: bool = False,
    include_dormant: bool = False
) -> list[dict]:
    """
    通过语义搜索
    
    Bug④ 修复：私密向量库不存在时，给出明确提示并降级搜索。
    
    Args:
        query: 查询文本
        limit: 返回条数
        include_content: 是否包含原文
        private: 是否搜索私密区
        include_dormant: 是否包含沉睡记忆
    
    Returns:
        记忆列表
    """
    results = []
    
    # 向量搜索
    vector_results = search_vector(query, limit * 2, private=private)
    
    if not vector_results and private:
        # Bug④ 修复：私密向量库为空时，给出明确提示
        print("   ⚠️ 私密向量库为空，使用 archive 全文搜索替代", file=sys.stderr)
        # 降级：直接扫描私密 archive 全文
        archive_paths = list_archive_txts(private=True)
        for ap in archive_paths:
            if len(results) >= limit:
                break
            archive_data = read_archive_txt(ap)
            if archive_data:
                content = archive_data.get("content", "")
                if query.lower() in content.lower():
                    results.append({
                        "memory_id": archive_data.get("memory_id", Path(ap).stem),
                        "summary": content[:100],
                        "tags": archive_data.get("tags", []),
                        "links": archive_data.get("links", []),
                        "timestamp": archive_data.get("created"),
                        "source": archive_data.get("source"),
                        "private": True
                    })
    else:
        # 构建结果
        for vr in vector_results:
            metadata = vr.get("metadata", {})
            result = {
                "memory_id": vr.get("memory_id"),
                "summary": metadata.get("tags", "").split(",")[0] if metadata.get("tags") else "",
                "tags": metadata.get("tags", "").split(",") if metadata.get("tags") else [],
                "links": metadata.get("links", "").split(",") if metadata.get("links") else [],
                "timestamp": metadata.get("timestamp"),
                "source": metadata.get("source"),
                "score": vr.get("score"),
                "private": private
            }
            
            # 如果需要原文 or summary 为空，尝试从 archive 取
            archive_path = metadata.get("archive_path")
            if archive_path:
                # 私密区需要加前缀
                if private and not archive_path.startswith("private/"):
                    archive_path = f"private/{archive_path}"
                archive_data = read_archive_txt(archive_path)
                if archive_data:
                    if include_content:
                        result["content"] = archive_data.get("content")
                    # Bug② 修复：summary 为空时，从 archive 原文截取
                    if not result.get("summary"):
                        result["summary"] = archive_data.get("content", "")[:100]
            
            results.append(result)
    
    # ═══ 重要度重排序 ═══
    for r in results:
        mid = r.get("memory_id")
        # 增加召回计数 & 更新重要度分数
        increment_recall_count(mid, private=private)
        update_importance(mid, private=private)
        # 获取最新重要度
        imp = get_importance_score(mid)
        if imp:
            r["importance_score"] = imp.get("importance_score", 0.0)
            r["recall_count"] = imp.get("recall_count", 0)
        else:
            r["importance_score"] = 0.0
            r["recall_count"] = 0
    
    # 按 final_score = vector_similarity × (1 + importance × bonus) 排序
    for r in results:
        vec_score = r.get("score", 0.5)
        imp_score = r.get("importance_score", 0.0)
        r["_final_score"] = vec_score * (1.0 + imp_score * IMPORTANCE_RECALL_BONUS)
    
    results.sort(key=lambda x: x.get("_final_score", 0), reverse=True)
    
    # ═══ 过滤 dormant（除非明确要求包含）
    if not include_dormant:
        results = _filter_active_only(results, private=private)
    else:
        # include_dormant=True：搜索沉睡层，并尝试唤醒命中的记忆
        dormant_results = _search_dormant(query, limit, private=private)
        for dr in dormant_results:
            _reactivate_from_dormant(
                dr.get('memory_id'),
                dr.get('summary', ''),
                dr.get('tags', []),
                dr.get('links', []),
                private=dr.get('private', private)
            )
        results.extend(dormant_results)
    
    return results


def recall_by_memory_id(
    memory_id: str,
    include_content: bool = True,
    private: bool = False
) -> dict:
    """
    精确定位某条记忆
    
    Bug② 修复：传入 private 参数，正确搜索私密 archive。
    
    Args:
        memory_id: 记忆 ID
        include_content: 是否包含原文
        private: 是否在私密区查找
    
    Returns:
        记忆详情
    """
    # Bug② 修复：正确传递 private 参数
    archive_paths = list_archive_txts(private=private)
    
    for ap in archive_paths:
        if memory_id in ap:
            archive_data = read_archive_txt(ap)
            if archive_data:
                result = {
                    "memory_id": memory_id,
                    "summary": archive_data.get("content", "")[:100],
                    "tags": archive_data.get("tags", []),
                    "links": archive_data.get("links", []),
                    "timestamp": archive_data.get("created"),
                    "source": archive_data.get("source"),
                    "private": private
                }
                
                if include_content:
                    result["content"] = archive_data.get("content")
                
                return result
    
    return None


def recall_recent(limit: int = 5, private: bool = False) -> list[dict]:
    """
    按时间排序，返回最近写入的 N 条记忆
    
    Args:
        limit: 返回条数
        private: 是否搜索私密区
    
    Returns:
        按 timestamp 降序的记忆列表
    """
    entries = list_hot_cache(private=private)
    
    # 过滤掉 summary 为 null 的空记录
    entries = [e for e in entries if e.get("summary")]
    
    # 按 timestamp 降序
    def _sort_key(e):
        ts = e.get("timestamp", "")
        return ts if ts else ""
    
    entries.sort(key=_sort_key, reverse=True)
    return entries[:limit]


def recall_hot_cache(simple: bool = False, private: bool = False, clean_null: bool = False) -> list[dict]:
    """
    启动加载热缓存
    
    Args:
        simple: 简单模式，只返回 summary
        private: 是否加载私密热缓存
        clean_null: 是否清理 summary 为 null 的空记录
    
    Returns:
        热缓存条目列表
    """
    entries = list_hot_cache(private=private)
    
    # 清理空记录
    if clean_null:
        before = len(entries)
        valid = [e for e in entries if e.get("summary")]
        after = len(valid)
        if before != after:
            cache = read_hot_cache(private=private)
            for e in entries:
                mid = e.get("memory_id") or e.get("id")
                if mid and mid in cache and not cache[mid].get("summary"):
                    del cache[mid]
            # 重建 entries 索引
            cache["entries"] = [mid for mid in cache.get("entries", []) if mid in cache]
            write_hot_cache(cache, private=private)
            entries = valid
            print(f"   ✓ 清理完成: {before - after} 条空记录已移除", file=sys.stderr)
        else:
            print(f"   ✓ 无空记录需要清理", file=sys.stderr)
    
    if simple:
        # 简单模式：只返回 summary
        return [{"summary": e.get("summary")} for e in entries]
    
    return entries


def recall(
    query: str = None,
    tags: list[str] = None,
    memory_id: str = None,
    limit: int = 5,
    include_content: bool = False,
    private: bool = False,
    include_dormant: bool = False
) -> list[dict]:
    """
    统一读取入口
    
    Args:
        query: 语义搜索
        tags: 标签搜索
        memory_id: 精确定位
        limit: 返回条数
        include_content: 是否包含原文
        private: 是否搜索私密区
        include_dormant: 是否包含沉睡记忆
    
    Returns:
        记忆列表
    """
    # 优先级：memory_id > tags > query
    if memory_id:
        result = recall_by_memory_id(memory_id, include_content, private)
        if result:
            update_last_recalled(memory_id, private=private)
        return [result] if result else []

    if tags:
        results = recall_by_tags(tags, limit, include_content, private, include_dormant)
        for r in results:
            update_last_recalled(r.get("memory_id"), private=private)
        return results

    # query=None 时也走通配符搜索（允许查询全部）
    # 查询全部时传 include_dormant
    return recall_by_query(query or "*", limit, include_content, private, include_dormant)


def main():
    parser = argparse.ArgumentParser(description="Memoria 统一读取入口")
    
    # 查询参数
    parser.add_argument("--query", default=None, help="语义搜索")
    parser.add_argument("--tags", default=None, help="标签搜索，逗号分隔")
    parser.add_argument("--memory-id", default=None, help="精确定位")
    parser.add_argument("--recent", type=int, default=None, metavar="N", help="按时间排序，返回最近 N 条")
    
    # 其他参数
    parser.add_argument("--limit", type=int, default=5, help="返回条数")
    parser.add_argument("--include-content", action="store_true", help="是否包含原文")
    parser.add_argument("--private", action="store_true", help="搜索私密区")
    parser.add_argument("--include-dormant", action="store_true", help="包含沉睡记忆")
    
    # 启动加载模式
    parser.add_argument("--hot-cache", action="store_true", help="启动加载热缓存")
    parser.add_argument("--simple", action="store_true", help="简单模式，只返回 summary")
    parser.add_argument("--clean-null", action="store_true", help="清理 summary 为空的记录")
    
    args = parser.parse_args()
    
    # 启动加载模式
    if args.hot_cache:
        results = recall_hot_cache(simple=args.simple, private=args.private, clean_null=args.clean_null)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    
    # --recent 模式
    if args.recent is not None:
        results = recall_recent(limit=args.recent, private=args.private)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    
    # 解析 tags
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    
    # 调用 recall
    results = recall(
        query=args.query,
        tags=tags,
        memory_id=args.memory_id,
        limit=args.limit,
        include_content=args.include_content,
        private=args.private,
        include_dormant=args.include_dormant
    )
    
    # 输出结果
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
