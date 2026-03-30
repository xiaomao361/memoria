#!/usr/bin/env python3
"""
Memoria remember.py — 写入记忆（双层结构）

架构：
  memoria_full/     → 全量原始对话（完整保留用户+助手所有消息）
  memoria.json     → 索引层（一句话精华摘要 + 标签 + channel + 引用 full_ref）

流程：
  对话结束 → 全量存入 memoria_full/ → 生成一句话精华 → 写入索引
"""

import json
import uuid
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

MEMORIA_DIR = Path(os.path.expanduser("~/.qclaw/skills/memoria"))
MEMORIA_FULL_DIR = MEMORIA_DIR / "memoria_full"
MEMORIA_INDEX_FILE = MEMORIA_DIR / "memoria.json"


def load_index():
    if MEMORIA_INDEX_FILE.exists():
        with open(MEMORIA_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"memories": [], "version": "1.0"}


def save_index(data):
    MEMORIA_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEMORIA_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_messages(conversation_data):
    """
    从会话历史中提取完整消息（用户 + 助手，全部保留）
    支持两种格式：
      1. OpenClaw 标准格式：[{"role": "user/assistant", "content": [...]}]
      2. 简单格式：[{"role": "user/assistant", "text": "..."}]
    """
    messages = []
    for msg in conversation_data:
        role = msg.get("role", "unknown")
        if role not in ("user", "assistant"):
            continue

        # 格式1：content 是列表
        contents = msg.get("content", [])
        if isinstance(contents, list):
            for c in contents:
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c.get("text", "").strip()
                    if text:
                        messages.append({
                            "role": role,
                            "text": text,
                            "timestamp": msg.get("timestamp", "")
                        })
        # 格式2：content 是字符串
        elif isinstance(contents, str) and contents.strip():
            messages.append({
                "role": role,
                "text": contents.strip(),
                "timestamp": msg.get("timestamp", "")
            })
        # 格式3：直接有 text 字段
        elif msg.get("text"):
            messages.append({
                "role": role,
                "text": msg["text"].strip(),
                "timestamp": msg.get("timestamp", "")
            })

    return messages


def generate_one_line_summary(messages, summary_override=None):
    """
    生成一句话精华摘要。
    
    优先使用 summary_override（人工指定）。
    否则从对话中提取：取用户核心问题 + 助手核心结论，压缩成一句话。
    """
    if summary_override:
        return summary_override

    if not messages:
        return "（空对话）"

    user_msgs = [m["text"] for m in messages if m["role"] == "user"]
    asst_msgs = [m["text"] for m in messages if m["role"] == "assistant"]

    # 取第一条用户消息（话题起点）
    first_user = user_msgs[0][:80] if user_msgs else ""
    # 取最后一条助手消息（结论）
    last_asst = asst_msgs[-1][:120] if asst_msgs else ""

    if first_user and last_asst:
        return f"{first_user}... → {last_asst}..."
    elif first_user:
        return first_user
    elif last_asst:
        return last_asst
    else:
        return "（无有效内容）"


def save_full_transcript(messages, session_label="unknown"):
    """存入 memoria_full/，返回文件路径"""
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    date_dir = MEMORIA_FULL_DIR / today
    date_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{session_label[:50]}_{datetime.now().strftime('%H%M%S')}.json"
    filepath = date_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "stored_at": datetime.now().astimezone().isoformat(),
            "session_label": session_label,
            "message_count": len(messages),
            "messages": messages
        }, f, ensure_ascii=False, indent=2)

    return str(filepath)


def write_memory(channel: str, tags: list, conversation_data: list,
                 session_label: str = "unknown", summary_override: str = None):
    """
    写入记忆（双层结构）

    Args:
        channel: 渠道标识（feishu/wechat/webchat/qclaw-ios/cli）
        tags: 标签列表
        conversation_data: 完整对话历史（用户+助手所有消息）
        session_label: session 描述标签
        summary_override: 人工指定的一句话精华（可选，否则自动生成）
    """
    # 1. 提取完整消息（用户+助手全部保留）
    messages = extract_messages(conversation_data)

    # 2. 存入全量（完整对话）
    full_path = save_full_transcript(messages, session_label)

    # 3. 生成一句话精华摘要
    summary = generate_one_line_summary(messages, summary_override)

    # 4. 写入索引
    memory_id = str(uuid.uuid4())
    entry = {
        "id": memory_id,
        "timestamp": datetime.now().astimezone().isoformat(),
        "channel": channel,
        "tags": tags,
        "summary": summary,
        "full_ref": full_path,
        "message_count": len(messages)
    }

    data = load_index()
    data["memories"].insert(0, entry)  # 最新在前
    save_index(data)

    return {
        "id": memory_id,
        "full_ref": full_path,
        "summary": summary,
        "tags": tags,
        "message_count": len(messages)
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Memoria 写入记忆")
    parser.add_argument("--channel", required=True,
                        help="渠道，如 feishu/webchat/wechat/qclaw-ios/cli")
    parser.add_argument("--tags", default="",
                        help="标签，逗号分隔")
    parser.add_argument("--session-label", default="unknown",
                        help="session 描述")
    parser.add_argument("--summary", default=None,
                        help="人工指定一句话精华（可选，默认自动生成）")
    parser.add_argument("--messages-file", default=None,
                        help="完整对话历史 JSON 文件路径")

    args = parser.parse_args()

    # 读取对话数据
    if args.messages_file:
        with open(args.messages_file, "r", encoding="utf-8") as f:
            conversation_data = json.load(f)
    else:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            try:
                conversation_data = json.loads(stdin_data)
            except json.JSONDecodeError:
                print("❌ stdin 数据不是有效的 JSON", file=sys.stderr)
                sys.exit(1)
        else:
            print("❌ 未提供对话数据（--messages-file 或 stdin）", file=sys.stderr)
            sys.exit(1)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    result = write_memory(
        channel=args.channel,
        tags=tags,
        conversation_data=conversation_data,
        session_label=args.session_label,
        summary_override=args.summary
    )

    print(f"✅ 记忆已写入")
    print(f"   ID: {result['id']}")
    print(f"   渠道: {args.channel}")
    print(f"   标签: {', '.join(result['tags']) or '无'}")
    print(f"   消息数: {result['message_count']}")
    print(f"   全量路径: {result['full_ref']}")
    print(f"")
    print(f"精华摘要：")
    print(f"  {result['summary']}")


if __name__ == "__main__":
    main()
