#!/usr/local/bin/python3.12
"""
Memoria auto_archive.py — 每日自动归档

定时任务：每天 23:30 执行
扫描当天新增 sessions，排除已归档的，同时写入：
  1. memoria.json（热缓存，最近 N 条）
  2. ChromaDB（向量索引，语义搜索）
  3. archive/（冷备份，全量历史）

使用 qwen2.5:7b 生成高质量摘要
"""

import json
import os
import uuid
from datetime import datetime, timezone, date
from pathlib import Path

# 导入共用工具库
from memoria_utils import (
    get_chroma_collection,
    get_embedding,
    generate_summary_from_messages,
    is_valid_summary,
    get_session_start_time,
    extract_messages_from_jsonl,
    infer_tags,
    infer_tags_with_llm,
    infer_channel,
    MEMORIA_DIR,
    ARCHIVE_DIR,
    MEMORIA_INDEX_FILE,
    SESSIONS_DIR,
    CHROMA_DB_PATH,
)

# 热缓存配置
HOT_CACHE_LIMIT = 50  # memoria.json 保留最近 50 条


def load_index() -> dict:
    """加载热缓存索引"""
    if MEMORIA_INDEX_FILE.exists():
        try:
            with open(MEMORIA_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"memories": [], "version": "3.1", "description": "热缓存（最近 N 条）"}


def save_index(data: dict):
    """保存热缓存，超过限制时清理旧的"""
    MEMORIA_DIR.mkdir(parents=True, exist_ok=True)
    
    memories = data.get("memories", [])
    if len(memories) > HOT_CACHE_LIMIT:
        memories = memories[:HOT_CACHE_LIMIT]
        data["memories"] = memories
        data["cleaned_at"] = datetime.now(timezone.utc).isoformat()
    
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
        if ".deleted." in f.name:
            continue
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
                                        return text[:100]
                        elif isinstance(content, str):
                            return content[:100]
    except:
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


def archive_session(session_path: str, session_id: str, session_label: str, channel: str, messages: list) -> str | None:
    """备份到冷存储"""
    if not Path(session_path).exists():
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


def write_to_chromadb(session_id: str, summary: str, timestamp: str, channel: str, tags: list) -> bool:
    """写入 ChromaDB（向量索引）"""
    collection = get_chroma_collection()
    if not collection:
        return False
    
    embedding = get_embedding(summary)
    if not embedding:
        return False
    
    try:
        collection.upsert(
            ids=[session_id],
            embeddings=[embedding],
            documents=[summary],
            metadatas=[{
                "timestamp": timestamp,
                "channel": channel,
                "tags": ",".join(tags),
                "session_id": session_id,
                "source": "auto_archive",
            }]
        )
        return True
    except Exception as e:
        print(f"❌ ChromaDB 写入失败: {e}")
        return False


def write_memory(
    channel: str,
    tags: list,
    session_id: str,
    session_path: str,
    session_label: str,
    summary: str,
    messages: list,
    cold_archive: bool = True
) -> dict | None:
    """写入单条记忆（三层：热缓存 + 向量 + 冷备份）"""
    
    # P0-3: 摘要质量校验
    if not is_valid_summary(summary):
        print(f"   ⚠️  摘要质量不足，跳过: {summary[:30]}")
        return None
    
    msg_count = count_messages(session_path)
    
    # 冷备份
    cold_path = None
    if cold_archive:
        cold_path = archive_session(session_path, session_id, session_label, channel, messages)
    
    memory_id = str(uuid.uuid4())
    
    # P0-1: 从消息中提取对话实际时间
    timestamp = get_session_start_time(messages)
    
    entry = {
        "id": memory_id,
        "timestamp": timestamp,
        "channel": channel,
        "tags": tags,
        "summary": summary,
        "session_id": session_id,
        "session_path": session_path,
        "cold_path": cold_path or "",
        "session_label": session_label,
        "message_count": msg_count,
        "storage_type": "cold+hot+vector" if cold_path else "hot+vector",
    }
    
    # 写入热缓存（memoria.json）
    data = load_index()
    data["memories"].insert(0, entry)
    save_index(data)
    
    # P0-2: 同时写入向量索引（ChromaDB）
    chroma_success = write_to_chromadb(
        session_id=session_id,
        summary=summary,
        timestamp=timestamp,
        channel=channel,
        tags=tags
    )
    
    if not chroma_success:
        print(f"   ⚠️  ChromaDB 写入失败，仅存入热缓存")
    
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
        channel = infer_channel(session_file, [])
        
        # 加载消息
        messages = extract_messages_from_jsonl(session_file)
        
        # 生成摘要
        summary = generate_summary_from_messages(messages)
        if not summary:
            summary = session_label[:50] if session_label else "unknown"
        
        # P1-3: 先用规则推断 tags，再用 LLM 补充
        rule_tags = infer_tags(messages)
        if rule_tags == ["未分类"]:
            llm_tags = infer_tags_with_llm(summary)
            tags_to_use = llm_tags
        else:
            tags_to_use = rule_tags
        
        # 写入三层
        result = write_memory(
            channel=channel,
            tags=tags_to_use + ["自动归档"],
            session_id=session_id,
            session_path=session_path,
            session_label=session_label,
            summary=summary,
            messages=messages,
            cold_archive=True
        )
        
        if result:
            new_memory_ids.append(result["id"])
            new_count += 1
            print(f"   ✅ 新归档: {summary[:40]}...")
    
    print(f"\n📊 归档完成: 新增 {new_count} 条，跳过 {skip_count} 条（已归档）")
    
    # 自动触发向量化（确保向量库同步）
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
