"""
Links 索引操作
支持公开区和私密区
"""

import json
import sys

from .config import LINKS_PATH, PRIVATE_LINKS_PATH, get_links_path


def read_links_index(private_zone: bool = False) -> dict:
    """读取 links 索引"""
    links_path = get_links_path(private_zone)
    
    if links_path.exists():
        try:
            with open(links_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"ERROR: links index read failed: {e}", file=sys.stderr)
            return {}
    return {}


def write_links_index(links_index: dict, private_zone: bool = False) -> bool:
    """写入 links 索引"""
    links_path = get_links_path(private_zone)
    
    try:
        links_path.parent.mkdir(parents=True, exist_ok=True)
        with open(links_path, 'w', encoding='utf-8') as f:
            json.dump(links_index, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"ERROR: links index write failed: {e}", file=sys.stderr)
        return False


def update_links_index(links: list[str], memory_id: str, private_zone: bool = False) -> bool:
    """
    更新 links 索引
    
    Returns:
        True if success, False if failed
    """
    try:
        links_index = read_links_index(private_zone)
        
        # 更新索引
        for link in links:
            if link not in links_index:
                links_index[link] = []
            if memory_id not in links_index[link]:
                links_index[link].append(memory_id)
        
        return write_links_index(links_index, private_zone)
    except Exception as e:
        print(f"ERROR: links index update failed: {e}", file=sys.stderr)
        return False


def get_memories_by_link(link: str, private_zone: bool = False) -> list[str]:
    """通过 link 获取关联的 memory_id 列表"""
    links_index = read_links_index(private_zone)
    return links_index.get(link, [])


def get_memories_by_links(links: list[str], private_zone: bool = False) -> list[str]:
    """通过多个 links 获取关联的 memory_id 列表（并集）"""
    links_index = read_links_index(private_zone)
    memory_ids = set()
    for link in links:
        if link in links_index:
            memory_ids.update(links_index[link])
    return list(memory_ids)
