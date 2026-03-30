#!/usr/bin/env python3
"""
Memoria → MEMORY.md 同步脚本

将 memoria.json 中最近 N 条记忆的摘要追加到 MEMORY.md 的固定区块。
每天定时执行，或由 heartbeat 触发。

用法：
  python3 sync_to_memory.py [--days 30] [--limit 20]
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

MEMORIA_DIR = Path(os.path.expanduser("~/.qclaw/skills/memoria"))
MEMORIA_INDEX = MEMORIA_DIR / "memoria.json"
MEMORY_FILE = Path(os.path.expanduser("~/.qclaw/workspace/MEMORY.md"))

DEFAULT_DAYS = 30
DEFAULT_LIMIT = 20


def parse_time(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def load_recent_memories(days: int, limit: int):
    if not MEMORIA_INDEX.exists():
        return []
    
    with open(MEMORIA_INDEX, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)
    memories = []
    
    for m in data.get("memories", []):
        if parse_time(m["timestamp"]) < cutoff:
            continue
        memories.append(m)
    
    return memories[:limit]


def format_memory_block(memories: list) -> str:
    if not memories:
        return ""
    
    lines = [
        "",
        "--- Memoria 近期记忆同步 ---",
        ""
    ]
    
    for m in memories:
        ts = parse_time(m["timestamp"])
        local = ts.astimezone()
        date_str = local.strftime("%Y-%m-%d")
        time_str = local.strftime("%H:%M")
        channel = m.get("channel", "unknown")
        tags = ", ".join(m.get("tags", [])) or "无标签"
        summary = m.get("summary", "")
        mem_id = m.get("id", "")[:8]
        
        # 摘要截断到 200 字
        if len(summary) > 200:
            summary = summary[:200] + "..."
        
        lines.append(f"### [{date_str}] {tags}")
        lines.append(f"**{time_str}** · {channel} · `id:{mem_id}`")
        lines.append(f"{summary}")
        lines.append("")
    
    lines.append("---")
    return "\n".join(lines)


def sync_to_memory(memories: list):
    if not MEMORY_FILE.exists():
        print(f"❌ MEMORY_FILE 不存在: {MEMORY_FILE}")
        return False
    
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    block = format_memory_block(memories)
    
    # 查找或创建同步标记
    marker_start = "<!-- MEMORIA_SYNC_START -->"
    marker_end = "<!-- MEMORIA_SYNC_END -->"
    
    if marker_start in content and marker_end in content:
        # 替换已有区块
        start_idx = content.index(marker_start)
        end_idx = content.index(marker_end) + len(marker_end)
        new_content = content[:start_idx] + marker_start + "\n" + block + "\n" + content[end_idx:]
    else:
        # 在文件开头（跳过 frontmatter）插入
        lines = content.split("\n")
        
        # 跳过开头的 Markdown 标题/分隔线（# MEMORY.md 等）
        insert_after = 0
        for i, line in enumerate(lines):
            if line.startswith("# "):
                insert_after = i
            elif line.startswith("---") and i < 5:
                insert_after = i
            elif line and not line.startswith("---") and not line.startswith("#"):
                break
        
        new_lines = lines[:insert_after+1] + [marker_start, ""] + block.split("\n") + ["", marker_end] + lines[insert_after+1:]
        new_content = "\n".join(new_lines)
    
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Memoria → MEMORY.md 同步")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    
    memories = load_recent_memories(days=args.days, limit=args.limit)
    
    if not memories:
        print("📭 没有找到需要同步的记忆")
        return
    
    if sync_to_memory(memories):
        print(f"✅ 已同步 {len(memories)} 条记忆到 MEMORY.md")
    else:
        print("❌ 同步失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
