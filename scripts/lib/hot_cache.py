"""
热缓存操作
"""

import json
import sys

from .config import HOT_CACHE_PATH, HOT_CACHE_CAPACITY
from .utils import get_utc_timestamp


def read_hot_cache() -> dict:
    """读取热缓存，自动将 legacy memories 数组迁移到 top-level dict 格式"""
    if HOT_CACHE_PATH.exists():
        try:
            cache = json.loads(HOT_CACHE_PATH.read_text(encoding='utf-8'))
            
            # 统一迁移：memories 数组 → top-level dict key
            if "memories" in cache and isinstance(cache["memories"], list):
                for entry in cache["memories"]:
                    mid = entry.get("id") or entry.get("memory_id")
                    if mid and mid not in cache:
                        cache[mid] = entry
                # 清理旧数组，保留 top-level entries
                del cache["memories"]
            
            return cache
        except Exception as e:
            print(f"ERROR: hot cache read failed: {e}", file=sys.stderr)
            return {}
    return {}


def _entries(cache: dict) -> list:
    """提取热缓存中的所有条目（兼容新旧格式）"""
    if "entries" in cache and isinstance(cache["entries"], list):
        # entries 是 ID 列表，从 cache[memory_id] 取详情
        result = []
        for mid in cache["entries"]:
            if mid in cache and isinstance(cache[mid], dict):
                result.append(cache[mid])
        return result
    # 剩余的 dict 条目（排除 top-level entries 索引）
    return [v for k, v in cache.items()
            if k != "entries" and isinstance(v, dict)]


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
    session_id: str = None,
    importance_fields: dict = None
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
            "storage_type": "hot",
            # 重要度字段
            "importance_score": importance_fields.get("importance_score", 0.0) if importance_fields else 0.0,
            "recall_count": importance_fields.get("recall_count", 0) if importance_fields else 0,
            "last_strengthened": importance_fields.get("last_strengthened") if importance_fields else None,
            "last_recalled": importance_fields.get("last_recalled") if importance_fields else None,
        }
        
        # 新格式：top-level dict key 寻址
        cache[memory_id] = new_entry
        
        # FIFO 淘汰：按 timestamp 保留最新 HOT_CACHE_CAPACITY 条
        entries = [(k, v) for k, v in cache.items()
                   if k != "entries" and isinstance(v, dict) and v.get("timestamp")]
        if len(entries) > HOT_CACHE_CAPACITY:
            entries.sort(key=lambda x: x[1].get("timestamp", ""), reverse=True)
            keep = set(k for k, _ in entries[:HOT_CACHE_CAPACITY])
            keep.add(memory_id)  # 确保当前条目不被误删
            for k in list(cache.keys()):
                if k not in keep and isinstance(cache[k], dict):
                    del cache[k]
        
        return write_hot_cache(cache)
    except Exception as e:
        print(f"ERROR: hot cache add failed: {e}", file=sys.stderr)
        return False


def get_from_hot_cache(memory_id: str) -> dict:
    """从热缓存获取单条"""
    cache = read_hot_cache()
    for entry in _entries(cache):
        if entry.get("memory_id") == memory_id:
            return entry
    return None


def list_hot_cache(limit: int = None) -> list[dict]:
    """列出热缓存条目"""
    cache = read_hot_cache()
    memories = _entries(cache)
    if limit:
        return memories[:limit]
    return memories


def get_by_session_id(session_id: str) -> dict:
    """根据 session_id 查询热缓存"""
    if not session_id:
        return None
    cache = read_hot_cache()
    for entry in _entries(cache):
        if entry.get("session_id") == session_id:
            return entry
    return None


def update_hot_cache_entry(memory_id: str, new_content: str = None, new_tags: list = None, new_links: list = None) -> bool:
    """更新热缓存条目"""
    try:
        cache = read_hot_cache()
        
        for entry in _entries(cache):
            if entry.get("memory_id") == memory_id:
                # 更新时间
                entry["timestamp"] = get_utc_timestamp()
                
                # 可选：更新 summary
                if new_content:
                    from .utils import extract_summary
                    entry["summary"] = extract_summary(new_content)
                
                # 可选：更新 tags
                if new_tags is not None:
                    entry["tags"] = new_tags
                
                # 可选：更新 links
                if new_links is not None:
                    entry["links"] = new_links
                
                return write_hot_cache(cache)
        
        return False
    except Exception as e:
        print(f"ERROR: hot cache update failed: {e}", file=sys.stderr)
        return False


def update_last_recalled(memory_id: str) -> bool:
    """更新记忆的最后访问时间"""
    try:
        cache = read_hot_cache()
        
        for entry in _entries(cache):
            if entry.get("memory_id") == memory_id:
                entry["last_recalled"] = get_utc_timestamp()
                return write_hot_cache(cache)
        
        return False
    except Exception as e:
        print(f"ERROR: update last_recalled failed: {e}", file=sys.stderr)
        return False


def init_importance_fields(memory_id: str, tags: list[str]) -> dict:
    """
    新存储的记忆初始化重要度字段。
    
    Returns:
        新条目的完整字段 dict
    """
    from .config import (
        IMPORTANCE_WEIGHT_TAGS, IMPORTANCE_WEIGHT_RECENT,
        IMPORTANCE_WEIGHT_RECALL, IMPORTANCE_WEIGHT_MANUAL,
        PROTECTION_TAGS
    )
    
    # 保护标签计分
    tag_score = 0.0
    if tags:
        for tag in tags:
            if tag in PROTECTION_TAGS:
                tag_score = IMPORTANCE_WEIGHT_TAGS
                break
    
    importance_score = tag_score  # 初始分数由标签决定
    
    return {
        "importance_score": round(importance_score, 3),
        "recall_count": 0,
        "last_strengthened": None,
        "last_recalled": None
    }


def update_importance(memory_id: str, delta: float = None, new_score: float = None) -> bool:
    """
    更新记忆的重要度分数。兼容两种存储格式：
    - 新格式：cache[memory_id] = dict
    - 旧格式：cache["memories"] = [dict, ...]
    """
    try:
        cache = read_hot_cache()
        entry = None
        
        # 新格式优先（dict key 直接寻址）
        if memory_id in cache and isinstance(cache[memory_id], dict):
            entry = cache[memory_id]
        # 旧格式（memories 数组）
        elif "memories" in cache and isinstance(cache["memories"], list):
            for e in cache["memories"]:
                mid = e.get("id") or e.get("memory_id")
                if mid == memory_id:
                    entry = e
                    break
        
        if entry is None:
            return False
        
        if new_score is not None:
            entry["importance_score"] = round(min(1.0, max(0.0, new_score)), 3)
        elif delta is not None:
            current = entry.get("importance_score", 0.0)
            entry["importance_score"] = round(min(1.0, max(0.0, current + delta)), 3)
        else:
            # 默认：无 delta 无 new_score → 按 IMPORTANCE_STRENGTHEN_STEP 增量
            from .config import IMPORTANCE_STRENGTHEN_STEP
            current = entry.get("importance_score", 0.0)
            entry["importance_score"] = round(min(1.0, max(0.0, current + IMPORTANCE_STRENGTHEN_STEP)), 3)
        
        entry["timestamp"] = get_utc_timestamp()
        return write_hot_cache(cache)
    except Exception as e:
        print(f"ERROR: update_importance failed: {e}", file=sys.stderr)
        return False


def increment_recall_count(memory_id: str) -> bool:
    """召回时增加召回计数"""
    try:
        cache = read_hot_cache()
        
        # 新格式：dict key
        if memory_id in cache and isinstance(cache[memory_id], dict):
            entry = cache[memory_id]
            entry["recall_count"] = entry.get("recall_count", 0) + 1
            entry["last_recalled"] = get_utc_timestamp()
            return write_hot_cache(cache)
        
        return False
    except Exception as e:
        print(f"ERROR: increment_recall_count failed: {e}", file=sys.stderr)
        return False


def get_importance_score(memory_id: str) -> dict:
    """
    获取记忆的重要度详情。
    
    Returns:
        dict with importance_score, recall_count, last_recalled, last_strengthened
        or None if not found
    """
    cache = read_hot_cache()
    for entry in _entries(cache):
        mid = entry.get("id") or entry.get("memory_id")
        if mid == memory_id:
            return {
                "importance_score": entry.get("importance_score", 0.0),
                "recall_count": entry.get("recall_count", 0),
                "last_recalled": entry.get("last_recalled"),
                "last_strengthened": entry.get("last_strengthened"),
                "tags": entry.get("tags", [])
            }
    return None


def list_by_importance(min_score: float = 0.0) -> list[dict]:
    """按重要度筛选记忆"""
    cache = read_hot_cache()
    results = []
    for entry in _entries(cache):
        score = entry.get("importance_score", 0.0)
        if score >= min_score:
            results.append({
                "memory_id": entry.get("id") or entry.get("memory_id"),
                "importance_score": score,
                "recall_count": entry.get("recall_count", 0),
                "last_recalled": entry.get("last_recalled"),
                "last_strengthened": entry.get("last_strengthened"),
                "tags": entry.get("tags", [])
            })
    # 按重要度降序
    results.sort(key=lambda x: x["importance_score"], reverse=True)
    return results
