"""
Archive TXT 读写操作
"""

import json
import re
from pathlib import Path

from .config import ARCHIVE_DIR
from .utils import get_utc_timestamp, extract_title


def write_archive_txt(
    memory_id: str,
    content: str,
    tags: list[str],
    links: list[str],
    source: str,
    session_id: str = None
) -> tuple[str, str]:
    """
    写入 archive TXT 文件
    
    Returns:
        (archive_path, title)
    """
    from datetime import datetime, timezone
    
    # 生成时间戳
    created = get_utc_timestamp()
    
    # 提取标题
    title = extract_title(content)
    
    # 按月归档
    dt = datetime.now(timezone.utc)
    month_dir = ARCHIVE_DIR / f"{dt.year}-{dt.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    
    # 文件名：{memory_id}.txt
    filename = f"{memory_id}.txt"
    filepath = month_dir / filename
    
    # 构建 YAML front matter
    front_matter = f"""---
memory_id: {memory_id}
created: {created}
source: {source}
tags: {json.dumps(tags, ensure_ascii=False)}
links: {json.dumps(links, ensure_ascii=False)}
session_id: {session_id or ''}
version: 1
---

"""
    
    # 写入文件
    full_content = front_matter + content
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(full_content)
    
    # 返回相对路径
    archive_path = f"{dt.year}-{dt.month:02d}/{filename}"
    return archive_path, title


def read_archive_txt(archive_path: str) -> dict:
    """
    读取 archive TXT 文件（兼容新旧格式）
    
    新格式：YAML front matter
    旧格式：# 注释头
    
    Args:
        archive_path: 相对路径，如 "2026-04/xxx.txt"
    
    Returns:
        {
            "memory_id": "xxx",
            "created": "...",
            "source": "...",
            "tags": [...],
            "links": [...],
            "session_id": "...",
            "version": 1,
            "content": "正文内容"
        }
    """
    filepath = ARCHIVE_DIR / archive_path
    
    if not filepath.exists():
        return None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        full_content = f.read()
    
    # 新格式：YAML front matter
    if full_content.startswith('---'):
        return _parse_new_format(full_content)
    
    # 旧格式：# 注释头
    if full_content.startswith('#'):
        return _parse_old_format(full_content, archive_path)
    
    # 无法识别的格式
    return {"content": full_content}


def _parse_new_format(full_content: str) -> dict:
    """解析新格式（YAML front matter）"""
    parts = full_content.split('---', 2)
    if len(parts) < 3:
        return {"content": full_content}
    
    front_matter_str = parts[1].strip()
    content = parts[2].strip()
    
    metadata = {}
    for line in front_matter_str.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            
            if value.startswith('[') and value.endswith(']'):
                try:
                    metadata[key] = json.loads(value)
                except:
                    metadata[key] = []
            elif value.isdigit():
                metadata[key] = int(value)
            else:
                metadata[key] = value
    
    metadata['content'] = content
    return metadata


def _parse_old_format(full_content: str, archive_path: str) -> dict:
    """
    解析旧格式（# 注释头）
    
    旧格式示例：
    # Clara
    # 创建时间: 2026-04-04T05:00:17.614619+00:00
    # 记忆ID: 661ac0a0-48a2-4c74-b659-ab134b1eff19
    # 链接: clara, 毛仔, claracore
    
    Clara很重要！...
    """
    lines = full_content.strip().split('\n')
    
    metadata = {
        "source": "migrated",
        "session_id": "",
        "version": 0,
    }
    
    content_lines = []
    
    for line in lines:
        if line.startswith('# '):
            # 解析注释行
            comment = line[2:].strip()
            
            if comment.startswith('创建时间:'):
                metadata['created'] = comment.replace('创建时间:', '').strip()
            elif comment.startswith('记忆ID:'):
                metadata['memory_id'] = comment.replace('记忆ID:', '').strip()
            elif comment.startswith('链接:'):
                links_str = comment.replace('链接:', '').strip()
                metadata['links'] = [l.strip() for l in links_str.split(',') if l.strip()]
                metadata['tags'] = metadata['links'].copy()
            elif ':' not in comment:
                # 标题行（第一个没有冒号的注释）
                if 'title' not in metadata:
                    metadata['title'] = comment
        else:
            content_lines.append(line)
    
    # 如果没有 memory_id，从文件名提取
    if 'memory_id' not in metadata or not metadata['memory_id']:
        # 文件名格式：{title}-{memory_id}.txt
        filename = Path(archive_path).stem
        # 尝试提取 UUID
        uuid_match = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', filename)
        if uuid_match:
            metadata['memory_id'] = uuid_match.group(1)
        else:
            # 生成新的 memory_id
            from .utils import generate_memory_id
            metadata['memory_id'] = generate_memory_id()
    
    # 确保 tags 和 links 存在
    if 'tags' not in metadata:
        metadata['tags'] = []
    if 'links' not in metadata:
        metadata['links'] = []
    
    metadata['content'] = '\n'.join(content_lines).strip()
    return metadata


def list_archive_txts(month: str = None) -> list[str]:
    """
    列出 archive TXT 文件
    
    Args:
        month: 可选，指定月份，如 "2026-04"
    
    Returns:
        相对路径列表
    """
    if month:
        month_dir = ARCHIVE_DIR / month
        if not month_dir.exists():
            return []
        return [f"{month}/{f.name}" for f in month_dir.glob("*.txt")]
    else:
        result = []
        if not ARCHIVE_DIR.exists():
            return result
        for month_dir in ARCHIVE_DIR.iterdir():
            if month_dir.is_dir():
                for f in month_dir.glob("*.txt"):
                    result.append(f"{month_dir.name}/{f.name}")
        return result
