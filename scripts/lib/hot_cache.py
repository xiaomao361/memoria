"""
热缓存操作
"""

import json
import sys

from .config import HOT_CACHE_PATH, HOT_CACHE_CAPACITY
from .utils import get_utc_timestamp


def read_hot_cache() -> dict:
    """读取热缓存"""
    if HOT_CACHE_PATH.exists():
        try:
            with open(HOT_CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"ERROR: hot cache read failed: {e}", file=sys.stderr)
            return {"memories": []}
    return {"memories": []}


def write_hot_cache(cache: dict) -> bool:
    """写入热缓存"""
    try:
        HOT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HOT_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"ERROR: hot cache write failed: {e}", file=sys.stderr)
        return False


def add_to_hot_cache(
    memory_id: str,
    archive_path: str,
    summary: str,
    tags: list[str],
    links: list[str],
    source: str,
    session_id: str = None
) -> bool:
    """
    添加到热缓存
    
    Returns:
        True if success, False if failed
    """
    try:
        cache = read_hot_cache()
        
        # 构建新条目
        new_entry = {
            "id": memory_id,
            "timestamp": get_utc_timestamp(),
            "tags": tags,
            "links": links,
            "summary": summary,
            "source": source,
            "memory_id": memory_id,
            "archive_path": archive_path,
            "session_id": session_id or "",
            "storage_type": "hot"
        }
        
        # 插入到头部
        cache["memories"].insert(0, new_entry)
        
        # FIFO 淘汰
        if len(cache["memories"]) > HOT_CACHE_CAPACITY:
            cache["memories"] = cache["memories"][:HOT_CACHE_CAPACITY]
        
        return write_hot_cache(cache)
    except Exception as e:
        print(f"ERROR: hot cache add failed: {e}", file=sys.stderr)
        return False


def get_from_hot_cache(memory_id: str) -> dict:
    """从热缓存获取单条"""
    cache = read_hot_cache()
    for entry in cache.get("memories", []):
        if entry.get("memory_id") == memory_id:
            return entry
    return None


def list_hot_cache(limit: int = None) -> list[dict]:
    """列出热缓存条目"""
    cache = read_hot_cache()
    memories = cache.get("memories", [])
    if limit:
        return memories[:limit]
    return memories
