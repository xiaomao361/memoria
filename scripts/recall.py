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
import sys
from datetime import datetime, timezone
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.archive import read_archive_txt, list_archive_txts
from lib.vector import search_vector, write_vector, delete_vector
from lib.hot_cache import list_hot_cache, get_from_hot_cache, update_last_recalled
from lib.links import get_memories_by_links
from lib.vector import search_vector, write_vector, delete_vector


# ═══════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _filter_active_only(results: list[dict]) -> list[dict]:
    """只返回活跃记忆，过滤掉 dormant"""
    cache = list_hot_cache()
    active_ids = {m.get("id") or m.get("memory_id") for m in cache if m.get("storage_type") != "dormant"}
    
    filtered = []
    for r in results:
        mid = r.get("memory_id")
        # 如果在热缓存中且不是 dormant
        if mid in active_ids:
            filtered.append(r)
    
    return filtered


def _reactivate_from_dormant(memory_id: str, summary: str, tags: list[str], links: list[str]) -> bool:
    """
    当 dormant 记忆被召回时，重新写入向量索引并恢复为活跃状态。
    
    1. 重新写入向量库（向量在降权时已删除，这里补写）
    2. 更新热缓存中的 storage_type 为 active
    3. 恢复 archive_path
    """
    from lib.hot_cache import read_hot_cache, write_hot_cache
    from lib.archive import read_archive_txt
    
    # 1. 重新写入向量库（从 dormant archive 读取原文）
    dormant_dir = Path.home() / ".qclaw" / "memoria" / "archive" / "dormant"
    archive_path = dormant_dir / f"{memory_id}.txt"
    if archive_path.exists():
        archive_data = read_archive_txt(str(archive_path))
        content = archive_data.get("content", summary)
    else:
        content = summary
    
    # 2. 写回向量库
    write_vector(
        memory_id=memory_id,
        archive_path=f"archive/{memory_id}.txt",  # 恢复为正常路径
        content=content,
        tags=tags,
        links=links,
        source="reactivated",
        private=False
    )
    
    # 3. 更新热缓存：恢复为活跃
    cache = read_hot_cache()
    for m in cache.get("memories", []):
        mid = m.get("id") or m.get("memory_id")
        if mid == memory_id:
            m["storage_type"] = "active"
            m["last_recalled"] = datetime.now(timezone.utc).isoformat()
            m["archive_path"] = f"archive/{memory_id}.txt"
            break
    write_hot_cache(cache)
    
    print(f"   ✓ 唤醒沉睡记忆: {memory_id}")
    return True


def _search_dormant(query: str, limit: int = 5) -> list[dict]:
    """搜索沉睡记忆"""
    dormant_dir = Path("~/.qclaw/memoria/archive/dormant").expanduser()
    if not dormant_dir.exists():
        return []
    
    results = []
    for f in dormant_dir.glob("*.txt"):
        # 简单全文匹配
        try:
            content = f.read_text(encoding="utf-8")
            if query.lower() in content.lower():
                results.append({
                    "memory_id": f.stem,
                    "summary": content[:100],
                    "storage_type": "dormant"
                })
                if len(results) >= limit:
                    break
        except:
            continue
    
    return results


# ═══════════════════════════════════════════════════════════════════════
# 主要查询函数
# ═══════════════════════════════════════════════════════════════════════


def recall_by_tags(tags: list[str], limit: int = 5, include_content: bool = False, private: bool = False, include_dormant: bool = False) -> list[dict]:
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
        results = _filter_active_only(results)
    
    return results


def recall_by_query(query: str, limit: int = 5, include_content: bool = False, private: bool = False, include_dormant: bool = False) -> list[dict]:
    """
    通过语义搜索
    
    Args:
        query: 查询文本
        limit: 返回条数
        include_content: 是否包含原文
        private: 是否搜索私密区
        include_dormant: 是否包含沉睡记忆
    
    Returns:
        记忆列表
    """
    # 向量搜索
    vector_results = search_vector(query, limit * 2, private=private)  # 多取一些，后面过滤
    
    if not vector_results:
        return []
    
    # 构建结果
    results = []
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
        
        # 如果需要原文
        if include_content:
            archive_path = metadata.get("archive_path")
            if archive_path:
                # 私密区需要加前缀
                if private and not archive_path.startswith("private/"):
                    archive_path = f"private/{archive_path}"
                archive_data = read_archive_txt(archive_path)
                if archive_data:
                    result["content"] = archive_data.get("content")
        
        results.append(result)
    
    # 过滤 dormant（除非明确要求包含）
    if not include_dormant:
        results = _filter_active_only(results)
    else:
        # include_dormant=True：搜索沉睡层，并尝试唤醒命中的记忆
        dormant_results = _search_dormant(query, limit)
        for dr in dormant_results:
            _reactivate_from_dormant(
                dr.get('memory_id'),
                dr.get('summary', ''),
                dr.get('tags', []),
                dr.get('links', [])
            )
        results.extend(dormant_results)
    
    return results


def recall_by_memory_id(memory_id: str, include_content: bool = True, private: bool = False) -> dict:
    """
    精确定位某条记忆
    
    Args:
        memory_id: 记忆 ID
        include_content: 是否包含原文
        private: 是否在私密区查找
    
    Returns:
        记忆详情
    """
    # 找到对应的 archive 文件
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


def recall_hot_cache(simple: bool = False) -> list[dict]:
    """
    启动加载热缓存（仅日常区）
    
    Args:
        simple: 简单模式，只返回 summary
    
    Returns:
        热缓存条目列表
    """
    entries = list_hot_cache()
    
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
            update_last_recalled(memory_id)
        return [result] if result else []

    if tags:
        results = recall_by_tags(tags, limit, include_content, private)
        for r in results:
            update_last_recalled(r.get("memory_id"))
        return results

    # query=None 时也走通配符搜索（允许查询全部）
    # 查询全部时传 include_dormant
    return recall_by_query(query or "*", limit, include_content, private, include_dormant)


def main():
    parser = argparse.ArgumentParser(description="Memoria 统一读取入口")
    
    # 查询参数（互斥）
    parser.add_argument("--query", default=None, help="语义搜索")
    parser.add_argument("--tags", default=None, help="标签搜索，逗号分隔")
    parser.add_argument("--memory-id", default=None, help="精确定位")
    
    # 其他参数
    parser.add_argument("--limit", type=int, default=5, help="返回条数")
    parser.add_argument("--include-content", action="store_true", help="是否包含原文")
    parser.add_argument("--private", action="store_true", help="搜索私密区")
    parser.add_argument("--include-dormant", action="store_true", help="包含沉睡记忆")
    
    # 启动加载模式
    parser.add_argument("--hot-cache", action="store_true", help="启动加载热缓存")
    parser.add_argument("--simple", action="store_true", help="简单模式，只返回 summary")
    
    args = parser.parse_args()
    
    # 启动加载模式（仅日常区）
    if args.hot_cache:
        results = recall_hot_cache(simple=args.simple)
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
