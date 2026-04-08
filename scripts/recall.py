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
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.archive import read_archive_txt, list_archive_txts
from lib.vector import search_vector
from lib.hot_cache import list_hot_cache, get_from_hot_cache
from lib.links import get_memories_by_links


def recall_by_tags(tags: list[str], limit: int = 5, include_content: bool = False, private: bool = False) -> list[dict]:
    """
    通过标签搜索
    
    Args:
        tags: 标签列表
        limit: 返回条数
        include_content: 是否包含原文
        private: 是否搜索私密区
    
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
    
    return results


def recall_by_query(query: str, limit: int = 5, include_content: bool = False, private: bool = False) -> list[dict]:
    """
    通过语义搜索
    
    Args:
        query: 查询文本
        limit: 返回条数
        include_content: 是否包含原文
        private: 是否搜索私密区
    
    Returns:
        记忆列表
    """
    # 向量搜索
    vector_results = search_vector(query, limit, private=private)
    
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
            archive_path = vr.get("archive_path")
            if archive_path:
                # 私密区需要加前缀
                if private and not archive_path.startswith("private/"):
                    archive_path = f"private/{archive_path}"
                archive_data = read_archive_txt(archive_path)
                if archive_data:
                    result["content"] = archive_data.get("content")
        
        results.append(result)
    
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
    private: bool = False
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
    
    Returns:
        记忆列表
    """
    # 优先级：memory_id > tags > query
    if memory_id:
        result = recall_by_memory_id(memory_id, include_content, private)
        return [result] if result else []
    
    if tags:
        return recall_by_tags(tags, limit, include_content, private)
    
    if query:
        return recall_by_query(query, limit, include_content, private)
    
    # 都没有，返回空
    return []


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
        private=args.private
    )
    
    # 输出结果
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
