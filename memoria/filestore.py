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
    archived: bool = False,
    kind: str = "fact",
    authority: str = "confirmed",
    retrieval_role: str = "background",
    confidence: float = 1.0,
    status: str = "active",
    superseded_by: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    source_agent: Optional[str] = None,
    source_run_id: Optional[str] = None,
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

    meta = {
        "id": memory_id,
        "created": now,
        "source": source,
        "tags": tags,
        "links": links,
        "private": private,
        "archived": archived,
        "kind": kind,
        "authority": authority,
        "retrieval_role": retrieval_role,
        "confidence": confidence,
        "status": status,
        "superseded_by": superseded_by,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "source_agent": source_agent,
        "source_run_id": source_run_id,
    }
    front_matter = _render_front_matter(meta)

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
            elif key == "confidence":
                try:
                    meta[key] = float(value)
                except ValueError:
                    meta[key] = value
            else:
                meta[key] = value

    meta["content"] = parts[2].strip()
    return meta


def update_file_metadata(rel_path: str, **updates) -> bool:
    """更新 store/*.md 的 front matter，保留正文内容"""
    filepath = STORE_DIR / rel_path
    if not filepath.exists():
        return False

    parsed = parse_memory_file(filepath.read_text(encoding="utf-8"))
    if parsed is None:
        return False

    content = parsed.pop("content", "")
    parsed.update(updates)
    front_matter = _render_front_matter(parsed)
    filepath.write_text(front_matter + content, encoding="utf-8")
    return True


def _render_front_matter(meta: dict) -> str:
    ordered_keys = [
        "id", "created", "source", "tags", "links", "private", "archived",
        "kind", "authority", "retrieval_role", "confidence", "status",
        "superseded_by", "valid_from", "valid_until", "source_agent", "source_run_id",
    ]
    keys = ordered_keys + sorted(k for k in meta if k not in ordered_keys)
    lines = ["---"]
    for key in keys:
        if key not in meta:
            continue
        value = meta[key]
        if value is None:
            continue
        if isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", ""])
    return "\n".join(lines) + "\n"


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
