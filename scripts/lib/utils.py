"""
通用工具函数
"""

import re
import uuid
from datetime import datetime, timezone


def generate_memory_id() -> str:
    """生成 UUID"""
    return str(uuid.uuid4())


def get_utc_timestamp() -> str:
    """获取 UTC 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def extract_links(content: str) -> list[str]:
    """从 content 中提取 [[xxx]] 链接"""
    pattern = r'\[\[([^\]]+)\]\]'
    matches = re.findall(pattern, content)
    return list(set(matches))  # 去重


def merge_tags_and_links(pre_tags: list[str] = None, extracted_links: list[str] = None) -> tuple[list[str], list[str]]:
    """合并 tags 和 links"""
    tags = pre_tags or []
    links = extracted_links or []
    return list(set(tags)), list(set(links))


def truncate_for_embedding(content: str, max_chars: int = 512) -> str:
    """按句子边界截断内容用于 embedding"""
    if len(content) <= max_chars:
        return content
    
    truncated = content[:max_chars]
    
    # 找最后一个句子结束符
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i] in '。！？.!?':
            return truncated[:i + 1]
    
    return truncated


def extract_summary(content: str) -> str:
    """从 content 中提取摘要"""
    lines = content.strip().split('\n')
    
    for i, line in enumerate(lines):
        if line.strip() == '## 摘要':
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    
    # 没找到摘要区块，取第一行非空内容
    for line in lines:
        if line.strip() and not line.startswith('#'):
            return line.strip()[:100]
    
    return "无摘要"


def extract_title(content: str) -> str:
    """从 content 中提取标题"""
    lines = content.strip().split('\n')
    
    for line in lines:
        if line.startswith('# '):
            return line[2:].strip()
    
    # 没找到标题，用摘要第一句
    for i, line in enumerate(lines):
        if line.startswith('## 摘要'):
            if i + 1 < len(lines):
                return lines[i + 1].strip()[:50]
    
    return "未命名"
