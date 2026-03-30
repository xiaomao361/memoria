#!/usr/bin/env python3
"""
Memoria remember.py — 写入记忆（双层结构）

架构：
  memoria_full/     → 全量原始对话（按日期/session_id 存储）
  memoria.json     → 索引层（摘要 + 标签 + channel + 引用 full_id）

流程：
  对话结束 → 全量存入 memoria_full/ → 生成摘要 → 写入索引
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
    """从会话历史中提取可存储的消息，过滤内部 thinking 等"""
    messages = []
    for msg in conversation_data:
        role = msg.get("role", "unknown")
        contents = msg.get("content", [])
        
        if isinstance(contents, list):
            for c in contents:
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c.get("text", "").strip()
                    if text and role in ("user", "assistant"):
                        messages.append({
                            "role": role,
                            "text": text,
                            "timestamp": msg.get("timestamp", "")
                        })
    return messages


def generate_summary_auto(messages):
    """一期：简单启发式摘要（提取首尾关键句 + 话题词）"""
    if not messages:
        return "", []
    
    # 取前3条 user 消息 + 最后1条 assistant 消息作为核心内容
    user_msgs = [m["text"] for m in messages if m["role"] == "user"][:5]
    last_asst = [m["text"] for m in messages if m["role"] == "assistant"][-1:] if messages else []
    
    # 简单策略：拼接前几条用户消息作为摘要基础
    summary_parts = []
    for i, msg in enumerate(user_msgs[:3]):
        # 截取前 100 字
        snippet = msg[:100] + "..." if len(msg) > 100 else msg
        summary_parts.append(f"[用户{i+1}]: {snippet}")
    
    summary = "\n".join(summary_parts)
    if last_asst:
        summary += f"\n\n[助手末次回复]: {last_asst[0][:150]}..."
    
    # 简单提取话题词（从用户消息中）
    keywords = []
    all_text = " ".join(user_msgs)
    topic_candidates = [
        "Memoria", "记忆增强", "织影", "埃洛维亚", "二期",
        "一期", "heartbeat", "skill", "插件", "摘要", "全量",
        "索引", "存储", "技术选型", "Python", "JSON"
    ]
    for kw in topic_candidates:
        if kw.lower() in all_text.lower():
            keywords.append(kw)
    
    return summary, keywords


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
        channel: 渠道标识
        tags: 标签列表
        conversation_data: 对话历史列表（JSONL格式或列表格式）
        session_label: session 标签
        summary_override: 人工指定的摘要（可选）
    """
    # 1. 提取消息
    messages = extract_messages(conversation_data)
    
    # 2. 存入全量
    full_path = save_full_transcript(messages, session_label)
    
    # 3. 生成摘要
    if summary_override:
        summary = summary_override
        keywords = tags
    else:
        summary, keywords = generate_summary_auto(messages)
    
    # 合并传入 tags 和自动生成的 keywords
    all_tags = list(set(tags + keywords))
    
    # 4. 写入索引
    memory_id = str(uuid.uuid4())
    entry = {
        "id": memory_id,
        "timestamp": datetime.now().astimezone().isoformat(),
        "channel": channel,
        "tags": all_tags,
        "summary": summary,
        "full_ref": full_path,  # 指向 memoria_full/ 中的文件
        "message_count": len(messages)
    }
    
    data = load_index()
    data["memories"].insert(0, entry)  # 最新在前
    save_index(data)
    
    return {
        "id": memory_id,
        "full_ref": full_path,
        "summary": summary[:100] + "..." if len(summary) > 100 else summary,
        "tags": all_tags,
        "message_count": len(messages)
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Memoria 写入记忆")
    parser.add_argument("--channel", required=True, help="渠道，如 feishu/webchat/wechat/qclaw-ios/cli")
    parser.add_argument("--tags", default="", help="标签，逗号分隔")
    parser.add_argument("--session-label", default="unknown", help="session 描述")
    parser.add_argument("--summary", default=None, help="人工摘要（可选，默认自动生成）")
    parser.add_argument("--messages-file", default=None, help="对话历史 JSON 文件路径")

    args = parser.parse_args()
    
    # 读取对话数据
    if args.messages_file:
        with open(args.messages_file, "r", encoding="utf-8") as f:
            conversation_data = json.load(f)
    else:
        # 从 stdin 读取
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
    print(f"摘要预览:")
    print(result['summary'][:200])


if __name__ == "__main__":
    main()
