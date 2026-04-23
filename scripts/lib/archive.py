"""
Archive TXT 读写操作
"""

import json
import re
from pathlib import Path

from .config import ARCHIVE_DIR, PRIVATE_ARCHIVE_DIR
from .utils import get_utc_timestamp, extract_title


def write_archive_txt(
    memory_id: str,
    content: str,
    tags: list[str],
    links: list[str],
    source: str,
    session_id: str = None,
    private: bool = False
) -> tuple[str, str]:
    """
    写入 archive TXT 文件
    
    Args:
        private: 是否写入私密区
    
    Returns:
        (archive_path, title)
    """
    from datetime import datetime, timezone
    
    # 生成时间戳
    created = get_utc_timestamp()
    
    # 提取标题
    title = extract_title(content)
    
    # 选择目录
    base_dir = PRIVATE_ARCHIVE_DIR if private else ARCHIVE_DIR
    
    # 按月归档
    dt = datetime.now(timezone.utc)
    month_dir = base_dir / f"{dt.year}-{dt.month:02d}"
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
private: {str(private).lower()}
version: 1
---

"""
    
    # 写入文件
    full_content = front_matter + content
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(full_content)
    
    # 返回相对路径（私密区加前缀标识）
    archive_path = f"{dt.year}-{dt.month:02d}/{filename}"
    if private:
        archive_path = f"private/{archive_path}"
    return archive_path, title


def read_archive_txt(archive_path: str) -> dict:
    """
    读取 archive TXT 文件（兼容新旧格式）
    
    新格式：YAML front matter
    旧格式：# 注释头
    
    Args:
        archive_path: 相对路径，如 "2026-04/xxx.txt" 或 "private/2026-04/xxx.txt"
    
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
    # 判断是否私密区
    is_private = archive_path.startswith("private/")
    if is_private:
        # write_archive_txt 返回格式：private/memories/{year-month}/{uuid}.txt
        # PRIVATE_ARCHIVE_DIR = ~/.qclaw/memoria/private/memories
        # 拼接后得到正确路径：~/.qclaw/memoria/private/memories/{year-month}/{uuid}.txt
        archive_path_clean = archive_path.replace("private/memories/", "")
        filepath = PRIVATE_ARCHIVE_DIR / archive_path_clean
        
        # 兼容旧格式（private/{year-month}/{uuid}.txt，没有 memories/）
        if not filepath.exists():
            legacy_filepath = PRIVATE_ARCHIVE_DIR / archive_path.replace("private/", "")
            if legacy_filepath.exists():
                filepath = legacy_filepath
    else:
        # 兼容 vector 写入时多打了 "archive/" 前缀的错误路径
        clean_path = archive_path.replace("archive/", "", 1)
        filepath = ARCHIVE_DIR / clean_path
        # 备用：原始路径
        if not filepath.exists():
            filepath = ARCHIVE_DIR / archive_path
        # 文件仍然不存在 → 向量库有记录但归档文件从未写入，静默跳过
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
            
            # 去掉单引号或双引号包裹
            if (value.startswith("'") and value.endswith("'")) or \
               (value.startswith('"') and value.endswith('"')):
                value = value[1:-1]
            
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
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        
        # ── 优先判断是否是标题行 ──
        # 第一行（无 "# " 前缀）：# 标题... 或直接是标题
        if i == 0 and 'title' not in metadata:
            clean_title = stripped.lstrip('#').strip()
            metadata['title'] = clean_title
            continue
        
        # ── 注释行：# xxx ──
        if stripped.startswith('# '):
            comment = stripped[2:].strip()
            
            if comment.startswith('创建时间:'):
                metadata['created'] = comment.replace('创建时间:', '').strip()
            elif comment.startswith('记忆ID:'):
                metadata['memory_id'] = comment.replace('记忆ID:', '').strip()
            elif comment.startswith('链接:'):
                links_str = comment.replace('链接:', '').strip()
                metadata['links'] = [l.strip() for l in links_str.split(',') if l.strip()]
                metadata['tags'] = metadata['links'].copy()
            elif ':' not in comment and 'title' not in metadata:
                metadata['title'] = comment
            continue
        
        # ── 分隔符 ──
        if '---' in stripped:
            continue
        
        # ── 迁移文件特殊格式：无 "# " 前缀的 key: value 行 ──
        # 只匹配 ASCII colon，不匹配中文冒号（：）
        if ':' in stripped and not line.startswith('# '):
            key, _, value = stripped.partition(':')
            key = key.strip()
            value = value.strip()
            if key in ('memory_id', 'created', 'source', 'session_id', 'version'):
                metadata[key] = value
            elif key in ('tags', 'links'):
                metadata[key] = [v.strip() for v in value.split(',') if v.strip()]
            continue
        
        # ── 正文内容行 ──
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


def list_archive_txts(month: str = None, private: bool = False) -> list[str]:
    """
    列出 archive TXT 文件
    
    Args:
        month: 可选，指定月份，如 "2026-04"
        private: 是否列出私密区
    
    Returns:
        相对路径列表（格式与 write_archive_txt 返回值一致）
    """
    base_dir = PRIVATE_ARCHIVE_DIR if private else ARCHIVE_DIR
    
    # 私密区路径前缀：write_archive_txt 返回 "private/memories/{year-month}/"
    prefix = "private/memories/" if private else ""
    
    if month:
        month_dir = base_dir / month
        if not month_dir.exists():
            return []
        return [f"{prefix}{month}/{f.name}" for f in month_dir.glob("*.txt")]
    else:
        result = []
        for month_dir in base_dir.iterdir():
            if month_dir.is_dir() and month_dir.name not in ['.DS_Store', 'chroma_db']:
                for f in month_dir.glob("*.txt"):
                    result.append(f"{prefix}{month_dir.name}/{f.name}")
        return result


def append_to_archive(memory_id: str, new_content: str, private: bool = False) -> bool:
    """
    追加内容到已有 archive TXT
    
    Args:
        memory_id: 已有记忆的 ID
        new_content: 要追加的内容
        private: 是否在私密区查找
    
    Returns:
        True if success, False if failed
    """
    base_dir = PRIVATE_ARCHIVE_DIR if private else ARCHIVE_DIR
    
    # 找到文件：遍历所有月份
    for month_dir in base_dir.iterdir():
        if not month_dir.is_dir():
            continue
        filepath = month_dir / f"{memory_id}.txt"
        if filepath.exists():
            # 读取现有内容
            with open(filepath, 'r', encoding='utf-8') as f:
                full_content = f.read()
            
            # 解析 front matter，追加内容
            if full_content.startswith('---'):
                parts = full_content.split('---', 2)
                if len(parts) >= 3:
                    front_matter = parts[1]
                    existing_content = parts[2].strip()
                    
                    # 在现有内容后追加分隔线和新增内容
                    updated_content = existing_content + "\n\n---\n\n" + new_content
                    updated_full = f"---\n{front_matter}---\n\n{updated_content}"
                else:
                    updated_full = full_content + "\n\n---\n\n" + new_content
            else:
                updated_full = full_content + "\n\n---\n\n" + new_content
            
            # 写回
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(updated_full)
            
            return True
    
    return False
