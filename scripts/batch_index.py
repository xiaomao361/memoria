#!/usr/bin/env python3
"""
batch_index.py — 批量扫描 OpenClaw sessions 并生成记忆索引

策略：
  - 扫描所有 session JSONL，按时间排序
  - 跳过已有 session_id 的条目（幂等）
  - 并发生成摘要（控制并发数）
  - 全量写入冷存储（archive/）
"""

import json
import sys
import os
import uuid
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ── 路径配置 ──────────────────────────────────
SESSIONS_DIR = Path.home() / ".qclaw/agents/main/sessions"
MEMORIA_DIR = Path.home() / ".qclaw/skills/memoria"
ARCHIVE_DIR = MEMORIA_DIR / "archive"
MEMORIA_INDEX_FILE = MEMORIA_DIR / "memoria.json"


# ── 锁 ─────────────────────────────────────────
index_lock = Lock()


def load_index() -> dict:
    if MEMORIA_INDEX_FILE.exists():
        try:
            with open(MEMORIA_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"memories": [], "version": "3.0"}


def save_index(data: dict):
    with index_lock:
        MEMORIA_DIR.mkdir(parents=True, exist_ok=True)
        with open(MEMORIA_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ── Session 解析 ────────────────────────────────
def extract_messages_from_jsonl(path: str) -> list:
    messages = []
    if not path or not Path(path).exists():
        return messages
    with open(path, "r", encoding="utf-8") as f:
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


def count_messages(path: str) -> int:
    count = 0
    if not path or not Path(path).exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
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


def parse_timestamp(obj: dict) -> datetime:
    ts = obj.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(os.path.getmtime(obj.get("path", "")), tz=timezone.utc)


def get_session_label(messages: list) -> str:
    """从消息内容推断 session 标签"""
    # 取第一条用户消息的前80字符作为 label
    for m in messages:
        if m["role"] == "user":
            text = re.sub(r'Sender.*?```.*?```', '', m["text"], flags=re.DOTALL).strip()
            text = re.sub(r'\[.*?\]', '', text).strip()
            label = text[:80].replace('\n', ' ').strip()
            return label or "unknown"
    return "unknown"


def infer_channel(messages: list) -> str:
    """从消息内容推断渠道"""
    first_user = ""
    for m in messages:
        if m["role"] == "user":
            first_user = m["text"]
            break
    if "feishu" in first_user.lower() or "飞书" in first_user:
        return "feishu"
    if "wechat" in first_user.lower() or "微信" in first_user:
        return "wechat"
    return "webchat"


def infer_tags(messages: list) -> list:
    """从消息内容推断标签"""
    all_text = " ".join(m["text"].lower() for m in messages)
    tags = []
    tag_map = {
        "memoria": ["memoria", "记忆系统", "记忆增强"],
        "织影": ["织影", "aeclovia", "elovia", "weave"],
        "副业": ["副业", "兼职", "收入", "月入"],
        "埃洛维亚": ["埃洛维亚", "世界观", "法则"],
        "技术": ["python", "linux", "服务器", "架构", "ci/cd", "运维"],
        "日常": ["日常", "聊天", "随便"],
        "日程": ["日历", "日程", "提醒", "cron", "日报", "周报"],
        " ThreadVibe": ["threadvibe", "websocket", "通信系统"],
    }
    for tag, keywords in tag_map.items():
        if any(kw.lower() in all_text for kw in keywords):
            tags.append(tag)
    return tags or ["未分类"]


# ── 摘要生成 ────────────────────────────────────
def generate_summary(messages: list) -> str:
    """调用 LLM 生成精华摘要"""
    if not messages:
        return "空对话"

    # 构建输入文本（限制 token）
    text_blocks = []
    for m in messages[:20]:  # 最多取前20条
        prefix = "👤" if m["role"] == "user" else "🤖"
        text = m["text"][:300]
        text_blocks.append(f"{prefix} {text}")
    input_text = "\n".join(text_blocks)

    prompt = f"""你是一个记忆系统，请为以下对话生成一句话精华摘要。

要求：
- 一句话，20-50字
- 包含核心事件/结论
- 用中文
- 禁止摘取原文

对话：
{input_text}

摘要："""

    try:
        result = subprocess.run(
            [
                sys.executable, "-c",
                f"""
import sys
sys.stdin.reconfigure(encoding='utf-8')
input_text = sys.stdin.read()
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:11434/api/generate',
    data=json.dumps({{'model': 'qwen2.5', 'prompt': input_text, 'stream': False}}).encode(),
    headers={{'Content-Type': 'application/json'}}
)
with urllib.request.urlopen(req, timeout=30) as r:
    print(json.loads(r.read())['response'].strip())
"""
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=40,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"   ⚠️  LLM 生成失败: {e}", file=sys.stderr)

    # Fallback：简单提取
    for m in messages:
        if m["role"] == "user":
            text = re.sub(r'Sender.*?```.*?```', '', m['text'], flags=re.DOTALL).strip()
            text = re.sub(r'\[.*?\]', '', text).strip()
            return text[:60] + "..." if len(text) > 60 else text
    return "无法生成摘要"


# ── 冷存储 ─────────────────────────────────────
def archive_session(messages: list, session_id: str, channel: str, label: str) -> str | None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    month_dir = ARCHIVE_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    safe_label = label.replace("/", "_").replace("\\", "_")[:30]
    archive_file = month_dir / f"{channel}_{safe_label}_{session_id[:8]}.json"
    archive_data = {
        "archived_at": now.isoformat(),
        "channel": channel,
        "session_label": label,
        "session_id": session_id,
        "message_count": len(messages),
        "messages": messages,
    }
    try:
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        return str(archive_file)
    except IOError:
        return None


# ── 处理单个 session ───────────────────────────
def process_session(jsonl_path: Path, existing_ids: set) -> dict | None:
    session_id = jsonl_path.stem
    if session_id in existing_ids:
        return None  # 已有，跳过

    messages = extract_messages_from_jsonl(str(jsonl_path))
    if not messages:
        return None

    label = get_session_label(messages)
    channel = infer_channel(messages)
    tags = infer_tags(messages)
    msg_count = len(messages)
    cold_path = archive_session(messages, session_id, channel, label)
    summary = generate_summary(messages)

    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "tags": tags,
        "summary": summary,
        "session_id": session_id,
        "session_path": str(jsonl_path),
        "cold_path": cold_path or "",
        "session_label": label,
        "message_count": msg_count,
        "storage_type": "cold+hot" if cold_path else "hot",
    }
    return entry


# ── 主流程 ─────────────────────────────────────
def main():
    # 1. 加载已有索引
    data = load_index()
    existing_ids = {m.get("session_id", "") for m in data["memories"]}
    existing_ids.discard("")
    print(f"已有 {len(existing_ids)} 条已有 session_id 记录")

    # 2. 扫描所有 session
    sessions = sorted(
        SESSIONS_DIR.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    print(f"共发现 {len(sessions)} 个 session 文件")

    to_process = [s for s in sessions if s.stem not in existing_ids]
    print(f"需要索引: {len(to_process)} 个")

    if not to_process:
        print("✅ 全部已索引，无需处理")
        return

    # 3. 并发处理
    new_entries = []
    total = len(to_process)

    def worker(path):
        return process_session(path, existing_ids)

    print(f"开始处理（并发数=5）...")
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(worker, p): p for p in to_process}
        done = 0
        for future in as_completed(futures):
            done += 1
            path = futures[future]
            try:
                entry = future.result()
                if entry:
                    new_entries.append(entry)
                    storage = entry.get("storage_type", "?")
                    summary_preview = entry["summary"][:40]
                    print(f"  [{done}/{total}] ✅ {entry['session_id'][:8]} [{entry['channel']}] {storage} — {summary_preview}...")
                else:
                    print(f"  [{done}/{total}] ⏭️  {path.stem} 已存在或为空，跳过")
            except Exception as e:
                print(f"  [{done}/{total}] ❌ {path.stem}: {e}")

    print(f"\n处理完成：{len(new_entries)} 条新记忆")

    # 4. 写入索引
    if new_entries:
        data["memories"] = new_entries + data["memories"]
        save_index(data)
        print(f"✅ 已写入 memoria.json，共 {len(data['memories'])} 条")
    else:
        print("无新条目需要写入")


if __name__ == "__main__":
    main()
