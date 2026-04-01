#!/usr/local/bin/python3.12
"""
Memoria auto_archive.py — 每日自动归档

定时任务：每天 23:30 执行
扫描当天新增 sessions，排除已归档的，自动写入 memoria.json
使用 qwen2.5:7b 生成高质量摘要
"""

import json
import os
import uuid
import requests
from datetime import datetime, timezone, date
from pathlib import Path


def resolve_memoria_dir() -> Path:
    custom = os.environ.get("MEMORIA_DIR", "").strip()
    if custom:
        return Path(os.path.expanduser(custom))
    return Path(os.path.expanduser("~/.qclaw/skills/memoria"))


MEMORIA_DIR = resolve_memoria_dir()
ARCHIVE_DIR = MEMORIA_DIR / "archive"
MEMORIA_INDEX_FILE = MEMORIA_DIR / "memoria.json"
SESSIONS_DIR = Path(os.path.expanduser("~/.qclaw/agents/main/sessions"))

# Ollama config
OLLAMA_BASE_URL = "http://localhost:11434"
SUMMARY_MODEL = "qwen2.5:7b"


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


def get_archived_session_ids() -> set:
    """获取已归档的 session_id 集合"""
    data = load_index()
    return {m.get("session_id") for m in data.get("memories", []) if m.get("session_id")}


def get_today_sessions() -> list:
    """获取今天修改的 session 文件"""
    if not SESSIONS_DIR.exists():
        return []
    
    today = date.today()
    sessions = []
    
    for f in SESSIONS_DIR.glob("*.jsonl"):
        # 跳过已删除的
        if ".deleted." in f.name:
            continue
        # 检查修改时间
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime.date() == today:
            sessions.append(f)
    
    return sorted(sessions, key=lambda f: f.stat().st_mtime)


def extract_first_message(jsonl_path: str) -> str:
    """提取第一条用户消息作为 session label"""
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("type") == "message":
                    msg = obj.get("message", {})
                    if msg.get("role") == "user":
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    text = c.get("text", "").strip()
                                    if text:
                                        return text[:100]  # 截断
                        elif isinstance(content, str):
                            return content[:100]
    except Exception:
        pass
    return "unknown"


def count_messages(jsonl_path: str) -> int:
    """统计消息数"""
    count = 0
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line.strip())
                    if obj.get("type") == "message":
                        msg = obj.get("message", {})
                        if msg.get("role") in ("user", "assistant"):
                            count += 1
                except:
                    continue
    except:
        pass
    return count


def detect_channel(session_path: str) -> str:
    """从 session 路径推断渠道"""
    # 尝试从 session JSONL 读取第一条消息的 channel 元数据
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # 飞书
                if "feishu" in str(obj.get("channel", "")).lower():
                    return "feishu"
                # 微信
                if "weixin" in str(obj.get("channel", "")).lower() or "wechat" in str(obj.get("channel", "")).lower():
                    return "wechat"
                # webchat
                if obj.get("type") == "message":
                    return "webchat"
    except:
        pass
    return "webchat"  # 默认


def extract_conversation_text(jsonl_path: str, limit: int = 10) -> str:
    """提取对话文本用于摘要生成"""
    messages = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except:
                    continue
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message", {})
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content", [])
                text = ""
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text = c.get("text", "").strip()
                            break
                elif isinstance(content, str):
                    text = content.strip()
                
                if text and "Sender (untrusted metadata)" not in text:
                    messages.append(f"{role.upper()}: {text[:200]}")
                    if len(messages) >= limit * 2:
                        break
    except:
        pass
    
    return "\n".join(messages[:limit])


def generate_summary(conversation_text: str) -> str:
    """用 qwen2.5:7b 生成摘要"""
    if not conversation_text.strip():
        return "【自动归档】空对话"
    
    prompt = f"""你是一个记忆整理助手。
以下是一段对话，请用一句话总结核心内容（15-30字以内，不要超过30字）：

{conversation_text}

摘要："""
    
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": SUMMARY_MODEL,
                "prompt": prompt,
                "stream": False,
                "temperature": 0.3,
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        summary = result.get("response", "").strip()
        
        # 清理摘要
        if summary:
            summary = summary.split("\n")[0].strip()
            if len(summary) > 50:
                summary = summary[:50]
            return summary
    except Exception as e:
        print(f"⚠️  摘要生成失败: {e}")
    
    return "【自动归档】对话记录"


def archive_session(session_path: str, session_id: str, session_label: str, channel: str) -> str | None:
    """备份到冷存储"""
    if not Path(session_path).exists():
        return None
    
    messages = []
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except:
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
    except:
        return None
    
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


def write_memory(channel: str, tags: list, session_id: str, session_path: str, session_label: str, summary: str, cold_archive: bool = True) -> dict:
    """写入单条记忆"""
    msg_count = count_messages(session_path)
    
    cold_path = None
    if cold_archive:
        cold_path = archive_session(session_path, session_id, session_label, channel)
    
    memory_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    entry = {
        "id": memory_id,
        "timestamp": now,
        "channel": channel,
        "tags": tags,
        "summary": summary,
        "session_id": session_id,
        "session_path": session_path,
        "cold_path": cold_path or "",
        "session_label": session_label,
        "message_count": msg_count,
        "storage_type": "cold+hot" if cold_path else "hot",
    }
    
    data = load_index()
    data["memories"].insert(0, entry)
    save_index(data)
    
    return entry


def main():
    print(f"🗓️ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始每日归档...")
    
    # 获取已归档的 session_id
    archived_ids = get_archived_session_ids()
    print(f"   已归档 session 数: {len(archived_ids)}")
    
    # 获取今天的 sessions
    today_sessions = get_today_sessions()
    print(f"   今日 session 数: {len(today_sessions)}")
    
    new_count = 0
    skip_count = 0
    new_memory_ids = []
    
    for session_file in today_sessions:
        session_id = session_file.stem
        session_path = str(session_file)
        
        # 跳过已归档的
        if session_id in archived_ids:
            skip_count += 1
            continue
        
        # 提取信息
        session_label = extract_first_message(session_path)
        channel = detect_channel(session_path)
        
        # 用 qwen2.5:7b 生成摘要
        conversation_text = extract_conversation_text(session_path, limit=10)
        summary = generate_summary(conversation_text)
        
        # 写入
        result = write_memory(
            channel=channel,
            tags=["自动归档", "每日"],
            session_id=session_id,
            session_path=session_path,
            session_label=session_label,
            summary=summary,
            cold_archive=True
        )
        
        new_memory_ids.append(result["id"])
        new_count += 1
        print(f"   ✅ 新归档: {summary[:40]}...")
    
    print(f"\n📊 归档完成: 新增 {new_count} 条，跳过 {skip_count} 条（已归档）")
    
    # 自动触发向量化
    if new_count > 0:
        print(f"\n🔄 自动向量化 {new_count} 条新记忆...")
        import subprocess
        try:
            result = subprocess.run(
                ["python3", str(Path(__file__).parent / "vectorize.py")],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                print("✨ 向量化完成")
            else:
                print(f"⚠️  向量化失败: {result.stderr}")
        except Exception as e:
            print(f"⚠️  向量化异常: {e}")


if __name__ == "__main__":
    main()
