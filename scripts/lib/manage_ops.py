"""
Memoria 管理操作封装

提供统一的操作接口，供 CLI 和 Web 界面调用。
所有操作自动同步三层：热缓存、向量库、Archive
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from .config import MEMORIA_ROOT, PROTECTION_TAGS
from .hot_cache import read_hot_cache, write_hot_cache, update_hot_cache_entry
from .vector import delete_vector, search_vector, get_collection
from .archive import list_archive_txts, read_archive_txt

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _extract_uuid(text: str) -> Optional[str]:
    """从文本中提取 UUID"""
    match = UUID_RE.search(text)
    return match.group() if match else None


def load_all_memories(private: bool = False) -> list[dict]:
    """加载所有记忆（热缓存 + archive）"""
    from .hot_cache import list_hot_cache
    
    memories = []
    seen_ids = set()
    
    # 1. 热缓存
    for entry in list_hot_cache(private=private):
        mid = entry.get("memory_id") or entry.get("id")
        if mid and mid not in seen_ids:
            entry["_source"] = "hot_cache"
            memories.append(entry)
            seen_ids.add(mid)
    
    # 2. Archive（跳过 dormant）
    for archive_path in list_archive_txts(private=private):
        if "dormant" in archive_path:
            continue
        
        mid = _extract_uuid(archive_path)
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


def delete_memory(memory_id: str, private: bool = False, force: bool = False) -> dict:
    """
    删除记忆（同步三层）
    
    Returns:
        {"success": bool, "message": str, "deleted_from": []}
    """
    result = {"success": False, "message": "", "deleted_from": []}
    
    try:
        # 1. 从热缓存删除
        cache = read_hot_cache(private=private)
        if memory_id in cache:
            del cache[memory_id]
            write_hot_cache(cache, private=private)
            result["deleted_from"].append("hot_cache")
        
        # 2. 从向量库删除
        try:
            delete_vector(memory_id, private=private)
            result["deleted_from"].append("vector")
        except Exception as e:
            result["message"] += f"向量删除警告: {e}; "
        
        # 3. 删除 archive 文件
        prefix = "private/memories/" if private else ""
        for archive_path in list_archive_txts(private=private):
            if memory_id in archive_path:
                full_path = MEMORIA_ROOT / prefix / archive_path
                if full_path.exists():
                    full_path.unlink()
                    result["deleted_from"].append(f"archive:{archive_path}")
        
        result["success"] = True
        if not result["message"]:
            result["message"] = f"已从 {len(result['deleted_from'])} 处删除"
        
    except Exception as e:
        result["message"] = f"删除失败: {e}"
    
    return result


def merge_memories(id1: str, id2: str, new_content: str, private: bool = False) -> dict:
    """
    合并两条记忆（保留id1，删除id2）
    
    Returns:
        {"success": bool, "message": str}
    """
    result = {"success": False, "message": ""}
    
    try:
        # 获取两条记忆
        m1 = None
        m2 = None
        for m in load_all_memories(private=private):
            if m.get("memory_id") == id1:
                m1 = m
            if m.get("memory_id") == id2:
                m2 = m
        
        if not m1 or not m2:
            result["message"] = "找不到指定的记忆"
            return result
        
        # 合并标签和链接
        new_tags = list(set(m1.get("tags", []) + m2.get("tags", [])))
        new_links = list(set(m1.get("links", []) + m2.get("links", [])))
        
        # 1. 更新 id1
        update_hot_cache_entry(id1, new_content, new_tags, new_links, private=private)
        
        # 2. 删除 id2
        delete_result = delete_memory(id2, private=private)
        if not delete_result["success"]:
            result["message"] = f"合并部分失败: {delete_result['message']}"
            return result
        
        result["success"] = True
        result["message"] = f"已合并 {id2[:8]} 到 {id1[:8]}"
        
    except Exception as e:
        result["message"] = f"合并失败: {e}"
    
    return result


def update_tags(memory_id: str, new_tags: list[str], private: bool = False) -> dict:
    """
    更新记忆标签（同步热缓存和向量库）
    
    Returns:
        {"success": bool, "message": str}
    """
    result = {"success": False, "message": ""}
    
    try:
        # 1. 更新热缓存
        cache = read_hot_cache(private=private)
        if memory_id in cache and isinstance(cache[memory_id], dict):
            cache[memory_id]["tags"] = new_tags
            write_hot_cache(cache, private=private)
        
        # 2. 更新向量库 metadata
        try:
            collection = get_collection(private=private)
            # ChromaDB 不支持直接改 metadata，需要删除重新添加
            results = collection.get(ids=[memory_id])
            if results and results.get("documents"):
                doc = results["documents"][0]
                metadata = results["metadatas"][0] if results.get("metadatas") else {}
                metadata["tags"] = ",".join(new_tags)
                
                collection.delete(ids=[memory_id])
                collection.add(
                    ids=[memory_id],
                    documents=[doc],
                    metadatas=[metadata]
                )
        except Exception as e:
            result["message"] = f"向量更新警告: {e}"
        
        result["success"] = True
        if not result["message"]:
            result["message"] = "标签已更新"
        
    except Exception as e:
        result["message"] = f"更新失败: {e}"
    
    return result


def find_duplicates(threshold: float = 0.8, private: bool = False) -> list[dict]:
    """
    查找重复/相似记忆
    
    Returns:
        [{"id1": str, "id2": str, "similarity": float, "summary1": str, "summary2": str}]
    """
    memories = load_all_memories(private=private)
    duplicates = []
    
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
    
    duplicates.sort(key=lambda x: x["similarity"], reverse=True)
    return duplicates


def normalize_all_tags(private: bool = False, dry_run: bool = True) -> dict:
    """
    批量归一化所有标签为小写
    
    Returns:
        {"success": bool, "changed": int, "details": []}
    """
    result = {"success": False, "changed": 0, "details": []}
    
    try:
        memories = load_all_memories(private=private)
        changed = 0
        
        for m in memories:
            mid = m.get("memory_id")
            old_tags = m.get("tags", [])
            new_tags = [t.lower() for t in old_tags]
            
            if old_tags != new_tags:
                if not dry_run:
                    update_tags(mid, new_tags, private=private)
                
                result["details"].append({
                    "id": mid[:8],
                    "old": old_tags,
                    "new": new_tags
                })
                changed += 1
        
        result["changed"] = changed
        result["success"] = True
        
    except Exception as e:
        result["success"] = False
        result["message"] = str(e)
    
    return result


def get_stats(private: bool = False) -> dict:
    """获取统计信息"""
    from collections import Counter
    
    memories = load_all_memories(private=private)
    
    if not memories:
        return {"total": 0, "message": "暂无记忆"}
    
    # 基础统计
    from_hot = sum(1 for m in memories if m.get("_source") == "hot_cache")
    from_archive = sum(1 for m in memories if m.get("_source") == "archive")
    
    # 标签统计
    all_tags = []
    for m in memories:
        all_tags.extend(m.get("tags", []))
    tag_counts = Counter(all_tags)
    
    # 来源统计
    sources = Counter(m.get("source", "unknown") for m in memories)
    
    # 问题统计
    no_tags = sum(1 for m in memories if not m.get("tags"))
    no_summary = sum(1 for m in memories if not m.get("summary"))
    
    return {
        "total": len(memories),
        "hot_cache": from_hot,
        "archive": from_archive,
        "top_tags": tag_counts.most_common(10),
        "sources": dict(sources),
        "problems": {
            "no_tags": no_tags,
            "no_summary": no_summary
        }
    }
