#!/usr/bin/env python3
"""
Memoria recall.py — 检索记忆

检索策略：
  1. 索引优先：从 memoria.json 获取摘要（轻量，默认）
  2. 按需展开：根据 storage_type 选择读取来源
     - hot → 读 OpenClaw session JSONL
     - cold → 读 archive/ 备份文件
     - cold+hot → 优先 archive，fallback 到 session

多 Claw 兼容：通过 MEMORIA_DIR 环境变量配置数据路径。
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path


def resolve_memoria_dir() -> Path:
    custom = os.environ.get("MEMORIA_DIR", "").strip()
    if custom:
        return Path(os.path.expanduser(custom))
    return Path(os.path.expanduser("~/.qclaw/skills/memoria"))


MEMORIA_DIR = resolve_memoria_dir()
ARCHIVE_DIR = MEMORIA_DIR / "archive"
MEMORIA_INDEX_FILE = MEMORIA_DIR / "memoria.json"

DEFAULT_DAYS = 7
DEFAULT_LIMIT = 5


# ──────────────────────────────────────────────
# 索引读取
# ──────────────────────────────────────────────

def load_index() -> dict:
    if not MEMORIA_INDEX_FILE.exists():
        return {"memories": [], "version": "3.0"}
    try:
        with open(MEMORIA_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"memories": [], "version": "3.0"}


def parse_time(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def filter_memories(
    memories: list,
    days: int = None,
    tags: list = None,
    channel: str = None,
    keyword: str = None,
) -> list:
    """
    多维度筛选记忆。
    - days: 最近 N 天
    - tags: 标签匹配（任一即可）
    - channel: 渠道精确匹配
    - keyword: 关键词模糊匹配（摘要/标签/label）
    """
    filtered = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    keyword_lower = keyword.lower() if keyword else None

    for m in memories:
        if cutoff and parse_time(m.get("timestamp", "")) < cutoff:
            continue
        if tags:
            mem_tags = [t.lower() for t in m.get("tags", [])]
            if not any(t.lower() in mem_tags for t in tags):
                continue
        if channel and m.get("channel") != channel:
            continue
        if keyword_lower:
            haystack = " ".join([
                m.get("summary", ""),
                " ".join(m.get("tags", [])),
                m.get("session_label", ""),
            ]).lower()
            if keyword_lower not in haystack:
                continue
        filtered.append(m)
    return filtered


# ──────────────────────────────────────────────
# 格式化输出
# ──────────────────────────────────────────────

def format_index_entry(memory: dict, index: int = 1) -> str:
    ts = parse_time(memory.get("timestamp", ""))
    time_str = ts.astimezone().strftime("%Y-%m-%d %H:%M")
    channel = memory.get("channel", "unknown")
    tags = ", ".join(memory.get("tags", [])) or "无标签"
    msg_count = memory.get("message_count", 0)
    storage = memory.get("storage_type", "hot")
    storage_icon = "🧊" if storage == "cold" else ("❄️" if storage == "cold+hot" else "🔥")
    session_id = memory.get("session_id", "")[:8]
    summary = memory.get("summary", "")

    lines = [
        f"{index}. [{time_str}] [{channel}] {storage_icon} [{tags}]",
        f"   {summary}",
        f"   🔑 id:{memory.get('id', '')[:8]}  session:{session_id}  {msg_count}条消息",
    ]
    return "\n".join(lines)


def format_simple(memory: dict) -> str:
    """简化格式，用于注入上下文"""
    ts = parse_time(memory.get("timestamp", ""))
    time_str = ts.astimezone().strftime("%m-%d %H:%M")
    channel = memory.get("channel", "unknown")
    tags = ", ".join(memory.get("tags", [])) or "无"
    summary = memory.get("summary", "")
    return f"[{time_str}][{channel}][{tags}] {summary}"


# ──────────────────────────────────────────────
# 全量展开
# ──────────────────────────────────────────────

def load_full_from_session(session_path: str) -> list:
    """从 OpenClaw session JSONL 读取消息"""
    messages = []
    if not session_path or not Path(session_path).exists():
        return messages
    with open(session_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "message":
                continue
            msg = obj.get("message", {})
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue
            timestamp = obj.get("timestamp", "")
            content = msg.get("content", [])
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text = c.get("text", "").strip()
                        if text:
                            messages.append({"role": role, "text": text, "timestamp": timestamp})
            elif isinstance(content, str) and content.strip():
                messages.append({"role": role, "text": content.strip(), "timestamp": timestamp})
    return messages


def load_full_from_archive(cold_path: str) -> list:
    """从 archive/ 读取消息"""
    if not cold_path or not Path(cold_path).exists():
        return []
    try:
        with open(cold_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", [])
    except (json.JSONDecodeError, IOError):
        return []


def recall_full(memory_id: str) -> str:
    """根据 ID 展开完整对话"""
    data = load_index()
    target = None
    for m in data["memories"]:
        if m.get("id", "").startswith(memory_id) or m.get("id") == memory_id:
            target = m
            break

    if not target:
        return f"❌ 未找到记忆: {memory_id}"

    storage = target.get("storage_type", "hot")
    cold_path = target.get("cold_path", "")
    session_path = target.get("session_path", "")

    # 选择读取来源
    messages = []
    source_desc = ""
    if storage in ("cold", "cold+hot") and cold_path and Path(cold_path).exists():
        messages = load_full_from_archive(cold_path)
        source_desc = f"🧊 冷存储: {cold_path}"
    if not messages and session_path and Path(session_path).exists():
        messages = load_full_from_session(session_path)
        source_desc = f"🔥 热存储: {session_path}"

    if not messages:
        return f"❌ 无法读取完整对话（session 可能已被清理）\n摘要：{target.get('summary', '')}"

    ts = parse_time(target.get("timestamp", ""))
    time_str = ts.astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"=== 完整对话 ===",
        f"时间: {time_str}",
        f"渠道: {target.get('channel', '')}",
        f"标签: {', '.join(target.get('tags', [])) or '无'}",
        f"描述: {target.get('session_label', '')}",
        f"存储: {storage}",
        f"{source_desc}",
        f"消息数: {len(messages)}",
        f"精华: {target.get('summary', '')}",
        "",
    ]

    for m in messages:
        role = "👤 用户" if m["role"] == "user" else "🤖 助手"
        ts_str = parse_time(m.get("timestamp", "")).astimezone().strftime("%H:%M") if m.get("timestamp") else ""
        text = m.get("text", "")
        lines.append(f"[{ts_str}] {role}:")
        lines.append(f"  {text[:800]}{'...' if len(text) > 800 else ''}")
        lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# 检索入口
# ──────────────────────────────────────────────

def recall_index(
    days: int = DEFAULT_DAYS,
    limit: int = DEFAULT_LIMIT,
    tags: list = None,
    channel: str = None,
    keyword: str = None,
    simple: bool = False,
) -> str:
    """检索索引摘要"""
    data = load_index()
    memories = filter_memories(data.get("memories", []), days=days, tags=tags, channel=channel, keyword=keyword)
    memories = memories[:limit]

    if not memories:
        return "📭 没有找到符合条件的记忆"

    if simple:
        lines = [format_simple(m) for m in memories]
        return "\n".join(lines)

    lines = [f"📮 最近 {len(memories)} 条记忆（{days} 天内）:\n"]
    for i, m in enumerate(memories, 1):
        lines.append(format_index_entry(m, index=i))
        lines.append("")
    return "\n".join(lines).strip()


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Memoria — 检索记忆")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="最近 N 天")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="最多返回 N 条")
    parser.add_argument("--tags", default=None, help="按标签筛选（逗号分隔）")
    parser.add_argument("--channel", default=None, help="按渠道筛选")
    parser.add_argument("--keyword", default=None, help="关键词模糊搜索")
    parser.add_argument("--id", default=None, help="指定记忆 ID 展开全量")
    parser.add_argument("--full", action="store_true", help="展开完整对话")
    parser.add_argument("--simple", action="store_true", help="简化格式（用于注入上下文）")

    args = parser.parse_args()

    if args.id:
        print(recall_full(memory_id=args.id))
    else:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
        print(recall_index(
            days=args.days,
            limit=args.limit,
            tags=tags,
            channel=args.channel,
            keyword=args.keyword,
            simple=args.simple,
        ))


if __name__ == "__main__":
    main()
