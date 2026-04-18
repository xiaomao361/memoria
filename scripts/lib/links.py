"""
Links 索引操作 - 支持双向索引和权重

结构:
{
    "tags": {                     # tag -> [uuid] 正向索引
        "Kraken": ["uuid1", ...],
        "项目": ["uuid2", ...]
    },
    "entities": {                 # uuid -> {tags, weight, last_linked} 反向索引
        "uuid1": {
            "tags": ["Kraken", "项目"],
            "weight": 2,
            "last_linked": "2026-04-16T11:00:00Z"
        }
    }
}
"""

import json
import sys
from datetime import datetime, timezone

from .config import LINKS_PATH, PRIVATE_LINKS_PATH


def get_utc_timestamp() -> str:
    """获取 UTC 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def read_links_index(private: bool = False) -> dict:
    """读取 links 索引（兼容旧结构）"""
    path = PRIVATE_LINKS_PATH if private else LINKS_PATH
    
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 兼容旧结构：如果没有 entities，说明是旧数据
            if "entities" not in data:
                # 转换为新结构（空 entities，后续写入时自动填充）
                return {
                    "tags": data,
                    "entities": {}
                }
            return data
        except Exception as e:
            print(f"ERROR: links index read failed: {e}", file=sys.stderr)
            return {"tags": {}, "entities": {}}
    return {"tags": {}, "entities": {}}


def write_links_index(links_index: dict, private: bool = False) -> bool:
    """写入 links 索引"""
    path = PRIVATE_LINKS_PATH if private else LINKS_PATH
    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(links_index, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"ERROR: links index write failed: {e}", file=sys.stderr)
        return False


def update_links_index(links: list[str], memory_id: str, private: bool = False) -> bool:
    """
    更新 links 索引（同时更新 tags 和 entities）
    
    Args:
        links: 关联的 tags/links 列表
        memory_id: memory UUID
        private: 是否更新私密索引
    
    Returns:
        True if success, False if failed
    """
    try:
        links_index = read_links_index(private=private)
        
        # 确保结构存在
        if "tags" not in links_index:
            links_index["tags"] = {}
        if "entities" not in links_index:
            links_index["entities"] = {}
        
        # 获取当前时间戳
        now = get_utc_timestamp()
        
        # 1. 更新 tags 正向索引
        for link in links:
            if link not in links_index["tags"]:
                links_index["tags"][link] = []
            if memory_id not in links_index["tags"][link]:
                links_index["tags"][link].append(memory_id)
        
        # 2. 更新 entities 反向索引
        if memory_id not in links_index["entities"]:
            links_index["entities"][memory_id] = {
                "tags": [],
                "weight": 0,
                "last_linked": now
            }
        
        # 追加新 tags，去重
        current_tags = set(links_index["entities"][memory_id]["tags"])
        new_tags = set(links)
        updated_tags = list(current_tags.union(new_tags))
        
        # 更新权重：每次关联增加权重
        old_weight = links_index["entities"][memory_id].get("weight", 0)
        
        links_index["entities"][memory_id] = {
            "tags": updated_tags,
            "weight": old_weight + len(links),
            "last_linked": now
        }
        
        return write_links_index(links_index, private=private)
    except Exception as e:
        print(f"ERROR: links index update failed: {e}", file=sys.stderr)
        return False


def get_memories_by_link(link: str, private: bool = False) -> list[str]:
    """通过 link 获取关联的 memory_id 列表"""
    links_index = read_links_index(private=private)
    return links_index.get("tags", {}).get(link, [])


def get_memories_by_links(links: list[str], private: bool = False) -> list[str]:
    """通过多个 links 获取关联的 memory_id 列表（并集）"""
    links_index = read_links_index(private=private)
    tags = links_index.get("tags", {})
    memory_ids = set()
    for link in links:
        if link in tags:
            memory_ids.update(tags[link])
    return list(memory_ids)


def get_tags_by_memory_id(memory_id: str, private: bool = False) -> list[str]:
    """通过 memory_id 获取关联的 tags（反向索引）"""
    links_index = read_links_index(private=private)
    entity = links_index.get("entities", {}).get(memory_id)
    if entity:
        return entity.get("tags", [])
    # 兼容旧数据：如果 entities 没有，遍历 tags 倒查
    tags = links_index.get("tags", {})
    result = []
    for tag, uuids in tags.items():
        if memory_id in uuids:
            result.append(tag)
    return result


def get_entity_info(memory_id: str, private: bool = False) -> dict:
    """获取 entity 的详细信息（tags, weight, last_linked）"""
    links_index = read_links_index(private=private)
    return links_index.get("entities", {}).get(memory_id, {})


def get_all_entities(private: bool = False) -> dict:
    """获取所有 entities"""
    links_index = read_links_index(private=private)
    return links_index.get("entities", {})


def get_top_entities(limit: int = 10, private: bool = False) -> list[tuple]:
    """获取权重最高的 entities"""
    entities = get_all_entities(private=private)
    # 按 weight 排序
    sorted_entities = sorted(
        entities.items(),
        key=lambda x: x[1].get("weight", 0),
        reverse=True
    )
    return sorted_entities[:limit]


# ========== 清理机制 ==========

import shutil
from pathlib import Path
from typing import Optional

MEMORIA_DIR = Path.home() / ".qclaw" / "memoria"
CLEANUP_DIR = MEMORIA_DIR / "cleanup"
CLEANUP_LOG_PATH = CLEANUP_DIR / "cleanup_log.json"
ARCHIVE_DIR = MEMORIA_DIR / "archive"


def _ensure_cleanup_dir():
    """确保清理目录存在"""
    CLEANUP_DIR.mkdir(parents=True, exist_ok=True)


def _read_cleanup_log() -> dict:
    """读取清理日志"""
    if CLEANUP_LOG_PATH.exists():
        try:
            with open(CLEANUP_LOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"records": []}
    return {"records": []}


def _write_cleanup_log(log: dict) -> bool:
    """写入清理日志"""
    try:
        _ensure_cleanup_dir()
        with open(CLEANUP_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"ERROR: cleanup log write failed: {e}", file=sys.stderr)
        return False


def cleanup_memory(
    memory_id: str,
    reason: str = "manual",
    private: bool = False
) -> dict:
    """
    软删除记忆（移动到 cleanup 目录并记录日志）
    
    Args:
        memory_id: 要清理的记忆 ID
        reason: 清理原因（manual / auto_stale / auto_completed）
        private: 是否是私密区
    
    Returns:
        {"status": "ok", "cleanup_path": "...", "archive_backup": "..."}
    """
    _ensure_cleanup_dir()
    now = get_utc_timestamp()
    
    # 1. 查找原始 archive 文件
    archive_base = ARCHIVE_DIR / "private" if private else ARCHIVE_DIR
    
    # 查找对应的 archive 文件
    archive_file = None
    for month_dir in archive_base.glob("????-??/"):
        if month_dir.is_dir():
            test_file = month_dir / f"{memory_id}.txt"
            if test_file.exists():
                archive_file = test_file
                break
    
    # 2. 移动到 cleanup 目录
    cleanup_subdir = CLEANUP_DIR / "private" if private else CLEANUP_DIR
    cleanup_subdir.mkdir(parents=True, exist_ok=True)
    
    result = {
        "status": "ok",
        "memory_id": memory_id,
        "reason": reason,
        "cleanup_time": now,
        "cleanup_path": None,
        "archive_backup": None
    }
    
    # 移动 archive 文件
    if archive_file and archive_file.exists():
        dest_file = cleanup_subdir / f"{memory_id}_{now.replace(':', '-')}.txt"
        try:
            shutil.move(str(archive_file), str(dest_file))
            result["archive_backup"] = str(dest_file)
            result["cleanup_path"] = str(cleanup_subdir)
        except Exception as e:
            result["status"] = f"failed: {e}"
            return result
    
    # 3. 先获取 tags（移除之前）
    tags_before_cleanup = get_tags_by_memory_id(memory_id, private=private)
    
    # 从 links 索引中移除
    links_index = read_links_index(private=private)
    
    # 从 tags 中移除
    for tag, uuids in links_index.get("tags", {}).items():
        if memory_id in uuids:
            uuids.remove(memory_id)
    
    # 从 entities 中移除
    if memory_id in links_index.get("entities", {}):
        del links_index["entities"][memory_id]
    
    write_links_index(links_index, private=private)
    
    # 4. 记录清理日志（使用之前获取的 tags）
    log = _read_cleanup_log()
    log["records"].append({
        "memory_id": memory_id,
        "reason": reason,
        "cleanup_time": now,
        "tags": tags_before_cleanup,  # 使用移除前保存的 tags
        "archive_backup": result["archive_backup"]
    })
    _write_cleanup_log(log)
    
    return result


def restore_memory(memory_id: str, private: bool = False) -> dict:
    """
    从 cleanup 恢复记忆
    
    Args:
        memory_id: 要恢复的记忆 ID
        private: 是否是私密区
    
    Returns:
        {"status": "ok", "archive_restore": "..."}
    """
    _ensure_cleanup_dir()
    now = get_utc_timestamp()
    
    # 1. 从 cleanup 目录找到文件
    cleanup_subdir = CLEANUP_DIR / "private" if private else CLEANUP_DIR
    
    cleanup_file = None
    if cleanup_subdir.exists():
        for f in cleanup_subdir.glob(f"{memory_id}_*.txt"):
            cleanup_file = f
            break
    
    result = {
        "status": "ok",
        "memory_id": memory_id,
        "archive_restore": None
    }
    
    # 2. 恢复到 archive
    if cleanup_file and cleanup_file.exists():
        # 找到原始月份目录
        archive_base = ARCHIVE_DIR / "private" if private else ARCHIVE_DIR
        
        # 从文件名解析日期（格式: uuid_2026-04-16Txx-xx-xx.xxx+00:00.txt）
        timestamp_str = cleanup_file.stem.replace(memory_id + "_", "")
        try:
            dt = datetime.fromisoformat(timestamp_str.replace('-', ':'))
            month_dir = archive_base / f"{dt.year}-{dt.month:02d}/"
        except:
            month_dir = archive_base / "restored/"
        
        month_dir.mkdir(parents=True, exist_ok=True)
        dest_file = month_dir / f"{memory_id}.txt"
        
        try:
            shutil.move(str(cleanup_file), str(dest_file))
            result["archive_restore"] = str(dest_file)
        except Exception as e:
            result["status"] = f"failed: {e}"
            return result
    
    # 3. 恢复 links（从日志中获取 tags）
    log = _read_cleanup_log()
    restored_tags = []
    for record in log.get("records", []):
        if record.get("memory_id") == memory_id:
            restored_tags = record.get("tags", [])
            break
    
    if restored_tags:
        # 重新添加到 links 索引
        links_index = read_links_index(private=private)
        
        for tag in restored_tags:
            if tag not in links_index["tags"]:
                links_index["tags"][tag] = []
            if memory_id not in links_index["tags"][tag]:
                links_index["tags"][tag].append(memory_id)
        
        # 恢复 entities（简单恢复，不含权重）
        links_index["entities"][memory_id] = {
            "tags": restored_tags,
            "weight": 1,  # 恢复时给个初始权重
            "last_linked": now
        }
        
        write_links_index(links_index, private=private)
    
    # 4. 从清理日志中移除（可选：保留历史）
    # 这里保留历史，只标记为已恢复
    
    return result


# 保护标签：带有这些标签的记忆不会被自动清理
PROTECTED_TAGS = [
    "长期项目", "核心任务", "不清理", "keep", "重要", 
    "项目", "Kraken", "bi项目", "doctor项目"
]


def auto_cleanup_stale_todos(days: int = 30, dry_run: bool = True) -> dict:
    """
    自动清理过期的已完成待办（保护长期核心任务）
    
    Args:
        days: 超过多少天算过期
        dry_run: True=只返回要清理的列表，不实际清理
    
    Returns:
        {"dry_run": True/False, "to_cleanup": [...], "results": [...]}
    """
    from datetime import timedelta
    
    # 找到所有"待办"相关的 memory
    links_index = read_links_index(private=False)
    
    # 查找带有"已完成"标签的待办
    stale_uuids = []
    
    for tag in ["待办", "已完成", "任务完成"]:
        uuids = links_index.get("tags", {}).get(tag, [])
        for uuid in uuids:
            # 检查是否有"已完成"标签
            entity_tags = links_index.get("entities", {}).get(uuid, {}).get("tags", [])
            if "已完成" in entity_tags or tag == "已完成":
                if uuid not in stale_uuids:
                    stale_uuids.append(uuid)
    
    # 过滤：根据 archive 文件日期判断是否过期
    import os
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    to_cleanup = []
    skipped_protected = []  # 被保护跳过的
    for uuid in stale_uuids:
        # 获取这个 uuid 的所有 tags
        entity_info = links_index.get("entities", {}).get(uuid, {})
        entity_tags = entity_info.get("tags", [])
        
        # 检查是否被保护
        is_protected = False
        for protected in PROTECTED_TAGS:
            if protected in entity_tags:
                is_protected = True
                break
        
        # 如果被保护，记录并跳过
        if is_protected:
            skipped_protected.append({
                "memory_id": uuid,
                "tags": entity_tags,
                "reason": "protected"
            })
            continue
        
        # 查找 archive 文件
        for month_dir in ARCHIVE_DIR.glob("????-??/"):
            if month_dir.is_dir():
                archive_file = month_dir / f"{uuid}.txt"
                if archive_file.exists():
                    mtime = datetime.fromtimestamp(os.path.getmtime(archive_file), tz=timezone.utc)
                    if mtime < cutoff_date:
                        to_cleanup.append({
                            "memory_id": uuid,
                            "archive_file": str(archive_file),
                            "mtime": mtime.isoformat(),
                            "age_days": (datetime.now(timezone.utc) - mtime).days,
                            "tags": entity_tags
                        })
                    break
    
    result = {
        "dry_run": dry_run,
        "days_threshold": days,
        "to_cleanup": to_cleanup,
        "skipped_protected": skipped_protected,
        "count": len(to_cleanup),
        "protected_count": len(skipped_protected)
    }
    
    if not dry_run:
        results = []
        for item in to_cleanup:
            r = cleanup_memory(item["memory_id"], reason="auto_stale")
            results.append(r)
        result["results"] = results
    
    return result


def list_cleanup_records() -> list:
    """列出所有清理记录"""
    log = _read_cleanup_log()
    return log.get("records", [])


def get_cleanup_summary() -> dict:
    """获取清理统计"""
    records = list_cleanup_records()
    
    by_reason = {}
    for r in records:
        reason = r.get("reason", "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    
    return {
        "total_cleanup": len(records),
        "by_reason": by_reason,
        "cleanup_dir": str(CLEANUP_DIR)
    }
