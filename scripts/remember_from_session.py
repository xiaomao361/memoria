#!/usr/bin/env python3
"""
Remember from current session — 用户说"记下来"时触发
提取当前 session 对话，生成摘要，直接写入 ChromaDB

Usage:
    python3 remember_from_session.py --session-id <id> --tags "tag1,tag2" --summary "custom summary"
    python3 remember_from_session.py --session-id <id>  # Auto-generate summary
"""

import json
import sys
import argparse
import uuid
import requests
from pathlib import Path
from datetime import datetime, timezone

try:
    import chromadb
except ImportError:
    print("❌ ChromaDB not installed")
    sys.exit(1)

# Paths
SESSIONS_DIR = Path.home() / ".qclaw/agents/main/sessions"
CHROMA_DB_PATH = Path.home() / ".qclaw/memoria/chroma_db"
ARCHIVE_DIR = Path.home() / ".qclaw/skills/memoria/archive"

# Ollama config
OLLAMA_BASE_URL = "http://localhost:11434"
SUMMARY_MODEL = "qwen2.5:3b-instruct-q4_K_M"
EMBEDDING_MODEL = "bge-m3"


def get_chroma_collection():
    """Get ChromaDB collection."""
    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_or_create_collection(name="memories", metadata={"hnsw:space": "cosine"})


def get_embedding(text: str) -> list:
    """Get embedding from Ollama."""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=30
        )
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        print(f"❌ Embedding failed: {e}")
        return None


def load_session(session_id: str) -> list:
    """Load session JSONL file."""
    session_file = SESSIONS_DIR / f"{session_id}.jsonl"
    
    if not session_file.exists():
        print(f"❌ Session not found: {session_file}")
        return []
    
    messages = []
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "message":
                        messages.append(obj)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"❌ Failed to load session: {e}")
    
    return messages


def extract_conversation_text(messages: list, limit: int = 20) -> str:
    """Extract conversation text from messages."""
    texts = []
    
    for msg in messages:
        message_data = msg.get("message", {})
        role = message_data.get("role", "")
        content = message_data.get("content", [])
        
        if role not in ("user", "assistant"):
            continue
        
        text = ""
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c.get("text", "").strip()
                    break
        elif isinstance(content, str):
            text = content.strip()
        
        if text and "Sender (untrusted metadata)" not in text:
            texts.append(f"{role.upper()}: {text[:200]}")
            if len(texts) >= limit * 2:
                break
    
    return "\n".join(texts[:limit])


def generate_summary(conversation_text: str) -> str:
    """Generate summary using qwen2.5:7b."""
    if not conversation_text.strip():
        return "对话记录"
    
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
        
        if summary:
            summary = summary.split("\n")[0].strip()
            if len(summary) > 50:
                summary = summary[:50]
            return summary
    except Exception as e:
        print(f"⚠️  Summary generation failed: {e}")
    
    return "对话记录"


def detect_channel(messages: list) -> str:
    """Detect channel from messages."""
    for msg in messages:
        if msg.get("type") == "message":
            # Try to infer from content
            return "webchat"  # Default
    return "webchat"


def archive_session(session_id: str, messages: list, summary: str, channel: str) -> str:
    """Archive to cold storage."""
    archived_messages = []
    
    for msg in messages:
        if msg.get("type") != "message":
            continue
        
        message_data = msg.get("message", {})
        role = message_data.get("role", "")
        content = message_data.get("content", [])
        timestamp = msg.get("timestamp", "")
        
        if role not in ("user", "assistant"):
            continue
        
        text = ""
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    text = c.get("text", "").strip()
                    break
        elif isinstance(content, str):
            text = content.strip()
        
        if text:
            archived_messages.append({
                "role": role,
                "text": text,
                "timestamp": timestamp
            })
    
    if not archived_messages:
        return ""
    
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    month_dir = ARCHIVE_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    
    safe_summary = summary.replace("/", "_").replace("\\", "_")[:30]
    archive_file = month_dir / f"{channel}_{safe_summary}_{session_id[:8]}.json"
    
    archive_data = {
        "archived_at": now.isoformat(),
        "channel": channel,
        "summary": summary,
        "session_id": session_id,
        "message_count": len(archived_messages),
        "messages": archived_messages
    }
    
    try:
        with open(archive_file, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        return str(archive_file)
    except Exception as e:
        print(f"⚠️  Archive failed: {e}")
        return ""


def write_to_chromadb(
    session_id: str,
    summary: str,
    tags: list,
    channel: str,
    archive_path: str = ""
) -> str:
    """Write memory to ChromaDB."""
    
    # Get embedding
    embedding = get_embedding(summary)
    if not embedding:
        print("❌ Failed to get embedding")
        return ""
    
    # Create memory entry
    memory_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    collection = get_chroma_collection()
    
    try:
        collection.upsert(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[summary],
            metadatas=[{
                "timestamp": now,
                "channel": channel,
                "tags": ",".join(tags),
                "session_id": session_id,
                "archive_path": archive_path,
            }]
        )
        
        print(f"✅ Memory saved: {memory_id[:8]}...")
        return memory_id
    
    except Exception as e:
        print(f"❌ Failed to write to ChromaDB: {e}")
        return ""


def main():
    parser = argparse.ArgumentParser(description="Remember from current session")
    parser.add_argument("--session-id", type=str, required=True, help="Session ID")
    parser.add_argument("--tags", type=str, default="手动记录", help="Tags (comma-separated)")
    parser.add_argument("--summary", type=str, help="Custom summary (auto-generate if not provided)")
    parser.add_argument("--no-archive", action="store_true", help="Skip cold archive")
    
    args = parser.parse_args()
    
    # Load session
    print(f"📖 Loading session: {args.session_id[:8]}...")
    messages = load_session(args.session_id)
    
    if not messages:
        print("❌ No messages found")
        return
    
    print(f"   Found {len(messages)} messages")
    
    # Detect channel
    channel = detect_channel(messages)
    
    # Generate or use provided summary
    if args.summary:
        summary = args.summary
        print(f"📝 Using provided summary: {summary[:50]}...")
    else:
        print("🤖 Generating summary...")
        conversation_text = extract_conversation_text(messages)
        summary = generate_summary(conversation_text)
        print(f"   Summary: {summary}")
    
    # Parse tags
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    
    # Archive to cold storage
    archive_path = ""
    if not args.no_archive:
        print("💾 Archiving to cold storage...")
        archive_path = archive_session(args.session_id, messages, summary, channel)
        if archive_path:
            print(f"   Archived: {archive_path}")
    
    # Write to ChromaDB
    print("🔄 Writing to ChromaDB...")
    memory_id = write_to_chromadb(
        session_id=args.session_id,
        summary=summary,
        tags=tags,
        channel=channel,
        archive_path=archive_path
    )
    
    if memory_id:
        print(f"\n✨ Memory recorded successfully!")
        print(f"   ID: {memory_id}")
        print(f"   Summary: {summary}")
        print(f"   Tags: {', '.join(tags)}")
    else:
        print("❌ Failed to record memory")
        sys.exit(1)


if __name__ == "__main__":
    main()
