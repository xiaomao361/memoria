#!/usr/bin/env python3
"""
Memoria Lite 统一读取入口 recall()

检索模式：
    --hot-cache --simple: 热缓存快速加载
    --search "关键词": 关键词搜索（热缓存优先 + Archive 回退）
    --tags "tag1,tag2": 标签精确匹配
    --memory-id "xxx": 直接指定 memory_id
    --days N: 最近 N 天
    --private: 搜索私密区
    --with-content: 返回完整内容

用法:
    python3 recall.py --hot-cache --simple
    python3 recall.py --search "用户偏好"
    python3 recall.py --search "用户偏好" --with-content
    python3 recall.py --tags "Memoria,技术"
    python3 recall.py --days 7
    python3 recall.py --memory-id "xxx"
    python3 recall.py --search "关键词" --private
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.config import HOT_CACHE_PATH, ARCHIVE_DIR, PRIVATE_ARCHIVE_DIR, get_archive_dir
from lib.hot_cache import read_hot_cache
from lib.archive import read_archive_txt, list_archive_txts
from lib.links import read_links_index
from lib.search import search_by_tags, search_by_keyword_hot, search_by_keyword_archive


def load_hot_cache_simple() -> list[dict]:
    """加载热缓存（简化格式）"""
    cache = read_hot_cache()
    memories = cache.get("memories", [])
    
    results = []
    for m in memories[:50]:  # 只取最近50条
        results.append({
            "id": m.get("memory_id", ""),
            "summary": m.get("summary", ""),
            "tags": m.get("tags", []),
            "links": m.get("links", []),
            "timestamp": m.get("timestamp", "")
        })
    
    return results


def search_by_days(days: int, private_zone: bool = False) -> list[dict]:
    """搜索最近 N 天的记忆"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []
    
    # 扫描 Archive
    for archive_path in list_archive_txts(private_zone=private_zone):
        data = read_archive_txt(archive_path, private_zone=private_zone)
        if not data:
            continue
        
        created_str = data.get("created", "")
        if not created_str:
            continue
        
        try:
            # 解析时间戳
            created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
            if created >= cutoff:
                results.append({
                    "id": data.get("memory_id", ""),
                    "summary": data.get("content", "")[:100] + "..." if len(data.get("content", "")) > 100 else data.get("content", ""),
                    "tags": data.get("tags", []),
                    "links": data.get("links", []),
                    "timestamp": created_str,
                    "archive_path": archive_path
                })
        except:
            continue
    
    # 按时间倒序
    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return results


def recall(
    hot_cache: bool = False,
    search: str = None,
    tags: list = None,
    memory_id: str = None,
    days: int = None,
    private: bool = False,
    with_content: bool = False,
    limit: int = 10
) -> list[dict]:
    """
    统一检索入口
    
    Args:
        hot_cache: 加载热缓存
        search: 关键词搜索
        tags: 标签列表
        memory_id: 直接指定 memory_id
        days: 最近 N 天
        private: 搜索私密区
        with_content: 返回完整内容
        limit: 结果数量限制
    
    Returns:
        搜索结果列表
    """
    # 热缓存快速加载
    if hot_cache:
        return load_hot_cache_simple()
    
    # 直接按 memory_id 查找
    if memory_id:
        # 先查公开区
        for archive_path in list_archive_txts(private_zone=False):
            if memory_id in archive_path:
                data = read_archive_txt(archive_path, private_zone=False)
                if data:
                    result = {
                        "id": data.get("memory_id", ""),
                        "summary": data.get("content", "")[:200] + "..." if len(data.get("content", "")) > 200 else data.get("content", ""),
                        "tags": data.get("tags", []),
                        "links": data.get("links", []),
                        "timestamp": data.get("created", ""),
                        "archive_path": archive_path
                    }
                    if with_content:
                        result["content"] = data.get("content", "")
                    return [result]
        
        # 再查私密区
        for archive_path in list_archive_txts(private_zone=True):
            if memory_id in archive_path:
                data = read_archive_txt(archive_path, private_zone=True)
                if data:
                    result = {
                        "id": data.get("memory_id", ""),
                        "summary": data.get("content", "")[:200] + "...",
                        "tags": data.get("tags", []),
                        "links": data.get("links", []),
                        "timestamp": data.get("created", ""),
                        "archive_path": archive_path,
                        "private": True
                    }
                    if with_content:
                        result["content"] = data.get("content", "")
                    return [result]
        
        return []
    
    # 按天数搜索
    if days:
        return search_by_days(days, private_zone=private)
    
    # 标签搜索
    if tags:
        results = search_by_tags(tags, limit=limit, private_zone=private)
        if with_content:
            for r in results:
                data = read_archive_txt(r.get("archive_path", ""), private_zone=private)
                if data:
                    r["content"] = data.get("content", "")
        return results
    
    # 关键词搜索
    if search:
        # 先查热缓存
        results = search_by_keyword_hot(search, limit=limit)
        
        # 热缓存未命中，查 Archive
        if not results:
            results = search_by_keyword_archive(search, limit=limit, private_zone=private)
        
        if with_content:
            for r in results:
                data = read_archive_txt(r.get("archive_path", ""), private_zone=private)
                if data:
                    r["content"] = data.get("content", "")
        
        return results
    
    return []


def main():
    parser = argparse.ArgumentParser(description="Memoria Lite 统一读取入口")
    parser.add_argument("--hot-cache", action="store_true", help="加载热缓存")
    parser.add_argument("--simple", action="store_true", help="简化输出")
    parser.add_argument("--search", default=None, help="关键词搜索")
    parser.add_argument("--tags", default=None, help="标签搜索，逗号分隔")
    parser.add_argument("--memory-id", default=None, help="直接指定 memory_id")
    parser.add_argument("--days", type=int, default=None, help="最近 N 天")
    parser.add_argument("--private", action="store_true", help="搜索私密区")
    parser.add_argument("--with-content", action="store_true", help="返回完整内容")
    parser.add_argument("--limit", type=int, default=10, help="结果数量限制")
    
    args = parser.parse_args()
    
    # 解析 tags
    tags = None
    if args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    
    # 调用 recall
    results = recall(
        hot_cache=args.hot_cache,
        search=args.search,
        tags=tags,
        memory_id=args.memory_id,
        days=args.days,
        private=args.private,
        with_content=args.with_content,
        limit=args.limit
    )
    
    # 输出结果
    if results:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("[]")


if __name__ == "__main__":
    main()
