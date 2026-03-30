#!/usr/bin/env python3
"""
Memoria recall.py — 检索记忆（双层结构）

默认返回索引摘要
--full 时从 memoria_full/ 读取完整对话
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

MEMORIA_DIR = Path(os.path.expanduser("~/.qclaw/skills/memoria"))
MEMORIA_INDEX_FILE = MEMORIA_DIR / "memoria.json"
MEMORIA_FULL_DIR = MEMORIA_DIR / "memoria_full"

DEFAULT_DAYS = 7
DEFAULT_LIMIT = 5


def load_index():
    if not MEMORIA_INDEX_FILE.exists():
        return {"memories": [], "version": "1.0"}
    with open(MEMORIA_INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_time(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def filter_memories(memories: list, days: int = DEFAULT_DAYS, tags: list = None, 
                    channel: str = None) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    filtered = []
    for m in memories:
        mem_time = parse_time(m["timestamp"])
        if mem_time < cutoff:
            continue
        if tags:
            mem_tags = [t.lower() for t in m.get("tags", [])]
            if not any(t.lower() in mem_tags for t in tags):
                continue
        if channel and m.get("channel") != channel:
            continue
        filtered.append(m)
    
    return filtered[:DEFAULT_LIMIT * days]  # 返回足够多，后面再截断


def format_index_entry(memory: dict, include_ref: bool = False) -> str:
    ts = parse_time(memory["timestamp"])
    time_str = ts.astimezone().strftime("%Y-%m-%d %H:%M")
    channel = memory.get("channel", "unknown")
    tags = ", ".join(memory.get("tags", [])) or "无标签"
    msg_count = memory.get("message_count", 0)
    
    lines = [
        f"[{time_str}] [{channel}] [📝{msg_count}条] [{tags}]",
        memory.get("summary", "")
    ]
    if include_ref:
        lines.append(f"  📁 {memory.get('full_ref', '')}")
    return "\n".join(lines)


def recall_index(days: int = DEFAULT_DAYS, limit: int = DEFAULT_LIMIT,
                 tags: list = None, channel: str = None) -> str:
    data = load_index()
    memories = filter_memories(data["memories"], days=days, tags=tags, channel=channel)
    memories = memories[:limit]
    
    if not memories:
        return "📭 没有找到符合条件的记忆"
    
    lines = [f"📮 最近 {len(memories)} 条记忆（{days} 天内）:\n"]
    for i, m in enumerate(memories, 1):
        lines.append(f"{i}. {format_index_entry(m, include_ref=True)}")
        lines.append("")
    
    return "\n".join(lines).strip()


def recall_full(memory_id: str = None, full_ref: str = None) -> str:
    """从 full_ref 读取完整对话"""
    if memory_id:
        data = load_index()
        for m in data["memories"]:
            if m["id"] == memory_id:
                full_ref = m.get("full_ref")
                break
        if not full_ref:
            return f"❌ 未找到记忆: {memory_id}"
    
    if not full_ref:
        return "❌ 未提供 full_ref"
    
    path = Path(full_ref)
    if not path.exists():
        return f"❌ 完整文件不存在: {full_ref}"
    
    with open(path, "r", encoding="utf-8") as f:
        content = json.load(f)
    
    stored_at = content.get("stored_at", "")
    session_label = content.get("session_label", "")
    messages = content.get("messages", [])
    
    lines = [f"=== 完整对话 ==="]
    if session_label != "unknown":
        lines.append(f"Session: {session_label}")
    lines.append(f"存储时间: {stored_at}")
    lines.append(f"消息数: {len(messages)}")
    lines.append("")
    
    for m in messages:
        role = "👤 用户" if m["role"] == "user" else "🤖 助手"
        ts = m.get("timestamp", "")
        ts_str = parse_time(ts).astimezone().strftime("%H:%M") if ts else ""
        lines.append(f"[{ts_str}] {role}:")
        lines.append(f"  {m['text'][:500]}{'...' if len(m['text']) > 500 else ''}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="从 Memoria 检索记忆")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"检索天数（默认 {DEFAULT_DAYS}）")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"最多返回条数（默认 {DEFAULT_LIMIT}）")
    parser.add_argument("--tags", default=None, help="按标签筛选（逗号分隔）")
    parser.add_argument("--channel", default=None, help="按渠道筛选")
    parser.add_argument("--id", default=None, help="指定记忆 ID（返回全量）")
    parser.add_argument("--full", action="store_true", help="输出完整对话")
    parser.add_argument("--ref", default=None, help="直接指定 full_ref 路径")

    args = parser.parse_args()
    
    if args.id or args.ref:
        if args.full or args.ref:
            print(recall_full(memory_id=args.id, full_ref=args.ref))
        else:
            # 返回索引信息
            data = load_index()
            for m in data["memories"]:
                if m["id"] == args.id:
                    print(format_index_entry(m, include_ref=True))
                    break
            else:
                print(f"❌ 未找到记忆: {args.id}")
    else:
        tags = None
        if args.tags:
            tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        print(recall_index(days=args.days, limit=args.limit, tags=tags, channel=args.channel))


if __name__ == "__main__":
    main()
