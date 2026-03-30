#!/usr/bin/env python3
"""
Memoria remember.py — 写入记忆

三层存储架构：
  热存储（session 引用）  → session_path，冷备无忧
  冷存储（archive/）     → 重要内容永久归档，防止 session 被清理
  索引（memoria.json）   → 唯一入口，所有检索从这里发起

多 Claw 兼容：数据路径通过 MEMORIA_DIR 环境变量配置，
默认 ~/.qclaw/skills/memoria（与 OpenClaw skill 标准路径一致）。
"""

import json
import sys
import os
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path


def resolve_memoria_dir() -> Path:
    """解析 Memoria 数据目录，支持环境变量覆盖（多 Claw 共存时各自独立）"""
    custom = os.environ.get("MEMORIA_DIR", "").strip()
    if custom:
        return Path(os.path.expanduser(custom))
    return Path(os.path.expanduser("~/.qclaw/skills/memoria"))


MEMORIA_DIR = resolve_memoria_dir()
ARCHIVE_DIR = MEMORIA_DIR / "archive"
MEMORIA_INDEX_FILE = MEMORIA_DIR / "memoria.json"
SESSIONS_DIR = Path(os.path.expanduser("~/.qclaw/agents/main/sessions"))

# 默认配置
DEFAULT_DAYS = 7
DEFAULT_LIMIT = 5
DEFAULT_CHANNEL = "unknown"


# ──────────────────────────────────────────────
# 索引读写
# ──────────────────────────────────────────────

def load_index() -> dict:
    if MEMORIA_INDEX_FILE.exists():
        try:
            with open(MEMORIA_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"memories": [], "version": "3.0"}


def save_index(data: dict):
    MEMORIA_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEMORIA_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Session 全量读取
# ──────────────────────────────────────────────

def extract_messages_from_jsonl(jsonl_path: str) -> list:
    """从 OpenClaw session JSONL 提取用户+助手消息"""
    messages = []
    if not jsonl_path or not Path(jsonl_path).exists():
        return messages
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_type = obj.get("type", "")
            if msg_type not in ("message",):
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


def count_messages(jsonl_path: str) -> int:
    """统计 session 中的 user+assistant 消息数"""
    count = 0
    if not jsonl_path or not Path(jsonl_path).exists():
        return 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
                if obj.get("type") == "message":
                    msg = obj.get("message", {})
                    if msg.get("role") in ("user", "assistant"):
                        count += 1
            except Exception:
                continue
    return count


def get_latest_session() -> tuple:
    """获取最新 session JSONL 的 path 和 session_id"""
    if not SESSIONS_DIR.exists():
        return None, None
    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None, None
    latest = files[0]
    session_id = latest.stem
    return str(latest), session_id


# ──────────────────────────────────────────────
# 冷存储：备份到 archive/
# ──────────────────────────────────────────────

def archive_session(session_path: str, session_id: str, session_label: str, channel: str) -> str | None:
    """
    将 session 内容备份到冷存储 archive/。
    路径格式：archive/{YYYY-MM}/{channel}_{session_id}.json
    返回归档文件路径，失败返回 None。
    """
    if not session_path or not Path(session_path).exists():
        return None
    messages = extract_messages_from_jsonl(session_path)
    if not messages:
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    month_dir = ARCHIVE_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    safe_label = session_label.replace("/", "_").replace("\\", "_")[:30]
    archive_file = month_dir / f"{channel}_{safe_label}_{session_id[:8]}.json"
    archive_data = {
        "archived_at": now.isoformat(),
        "channel": channel,
        "session_label": session_label,
        "session_id": session_id,
        "message_count": len(messages),
        "messages": messages
    }
    try:
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        return str(archive_file)
    except IOError:
        return None


# ──────────────────────────────────────────────
# 核心写入逻辑
# ──────────────────────────────────────────────

def write_memory(
    channel: str,
    tags: list,
    session_id: str = None,
    session_path: str = None,
    session_label: str = "unknown",
    summary: str = None,
    cold_archive: bool = False,
) -> dict:
    """
    写入一条记忆索引。

    Args:
        channel:       渠道标识（feishu/webchat/wechat/cli/...）
        tags:          标签列表
        session_id:    OpenClaw session UUID（可选，默认取最新）
        session_path:  session JSONL 路径（可选，默认取最新）
        session_label: session 描述标签
        summary:       精华摘要（必须由调用方总结传入）
        cold_archive:  是否同时备份到冷存储（archive/）

    Returns:
        写入的索引条目 dict
    """
    # 自动获取最新 session
    if not session_path or not session_id:
        _sp, _sid = get_latest_session()
        session_path = session_path or _sp
        session_id = session_id or _sid

    if session_path and Path(session_path).exists():
        msg_count = count_messages(session_path)
    else:
        msg_count = 0

    # 冷存储
    cold_path = None
    if cold_archive and session_path:
        cold_path = archive_session(session_path, session_id, session_label, channel)

    memory_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": memory_id,
        "timestamp": now,
        "channel": channel,
        "tags": tags,
        "summary": summary or "（未提供摘要）",
        # 热存储：指向 OpenClaw 原生 session
        "session_id": session_id or "",
        "session_path": session_path or "",
        # 冷存储：指向 archive/ 备份（可能为空）
        "cold_path": cold_path or "",
        # 元数据
        "session_label": session_label,
        "message_count": msg_count,
        "storage_type": "cold+hot" if cold_path else "hot",
    }

    data = load_index()
    data["memories"].insert(0, entry)
    save_index(data)

    return entry


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Memoria — 写入记忆")
    parser.add_argument("--channel", required=True,
                        help="渠道：feishu / webchat / wechat / cli / ...（其他 Claw 可自定义）")
    parser.add_argument("--tags", default="",
                        help="标签，逗号分隔")
    parser.add_argument("--session-label", default="unknown",
                        help="session 描述标签")
    parser.add_argument("--summary", required=True,
                        help="精华摘要（Clara 总结，禁止原文摘取）")
    parser.add_argument("--session-id", default=None,
                        help="指定 session UUID（默认取最新）")
    parser.add_argument("--session-path", default=None,
                        help="指定 session JSONL 路径（默认取最新）")
    parser.add_argument("--archive", action="store_true",
                        help="同时备份到冷存储（archive/）")

    args = parser.parse_args()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    result = write_memory(
        channel=args.channel,
        tags=tags,
        session_id=args.session_id,
        session_path=args.session_path,
        session_label=args.session_label,
        summary=args.summary,
        cold_archive=args.archive,
    )

    storage = result.get("storage_type", "hot")
    cold_info = f"\n   冷存储：{result.get('cold_path', '')}" if result.get("cold_path") else ""
    print(f"✅ 记忆已写入 [{storage}]")
    print(f"   ID: {result['id']}")
    print(f"   渠道: {result['channel']}")
    print(f"   标签: {', '.join(result['tags']) or '无'}")
    print(f"   消息数: {result['message_count']}")
    print(f"   热存储: {result.get('session_path', '')}")
    print(f"   Session: {result.get('session_id', '')}")
    print(cold_info)
    print(f"\n精华摘要：{result['summary']}")


if __name__ == "__main__":
    main()
