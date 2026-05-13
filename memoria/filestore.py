"""文件存储 - store/*.md 读写"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import STORE_DIR

LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def write_file(
    memory_id: str,
    content: str,
    summary: str,
    tags: list[str],
    links: list[str],
    source: str,
    private: bool = False,
    created_at: Optional[str] = None,
) -> str:
    """写入 store/*.md，返回相对路径"""
    now = created_at or datetime.now(timezone.utc).isoformat()
    month = now[:7]  # YYYY-MM

    if private:
        month_dir = STORE_DIR / "private" / month
    else:
        month_dir = STORE_DIR / month

    month_dir.mkdir(parents=True, exist_ok=True)
    filepath = month_dir / f"{memory_id}.md"

    front_matter = (
        f"---\n"
        f"id: {memory_id}\n"
        f"created: {now}\n"
        f"source: {source}\n"
        f"tags: {json.dumps(tags, ensure_ascii=False)}\n"
        f"links: {json.dumps(links, ensure_ascii=False)}\n"
        f"private: {str(private).lower()}\n"
        f"---\n\n"
    )

    filepath.write_text(front_matter + content, encoding="utf-8")

    rel_path = f"private/{month}/{memory_id}.md" if private else f"{month}/{memory_id}.md"
    return rel_path


def read_file(rel_path: str) -> Optional[dict]:
    """读取 store/*.md，返回解析后的 dict"""
    filepath = STORE_DIR / rel_path
    if not filepath.exists():
        return None

    text = filepath.read_text(encoding="utf-8")
    return parse_memory_file(text)


def parse_memory_file(text: str) -> Optional[dict]:
    """解析带 YAML front matter 的 markdown 文件"""
    if not text.startswith("---"):
        return {"content": text}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"content": text}

    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value.startswith("["):
                try:
                    meta[key] = json.loads(value)
                except json.JSONDecodeError:
                    meta[key] = []
            elif value in ("true", "false"):
                meta[key] = value == "true"
            else:
                meta[key] = value

    meta["content"] = parts[2].strip()
    return meta


def extract_links(content: str) -> list[str]:
    """从内容中提取 [[xxx]] 链接"""
    return list(set(LINK_RE.findall(content)))


def list_all_files(private: bool = False) -> list[Path]:
    """列出所有 store 文件"""
    base = STORE_DIR / "private" if private else STORE_DIR
    if not base.exists():
        return []
    files = []
    for month_dir in sorted(base.iterdir()):
        if month_dir.is_dir() and month_dir.name != "private":
            files.extend(sorted(month_dir.glob("*.md")))
    return files
