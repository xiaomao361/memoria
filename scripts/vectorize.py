#!/usr/bin/env python3
"""
Vectorize memories directly from sessions/archive to ChromaDB.
No intermediate memoria.json needed.

Key design: vectorize SUMMARIES not raw conversations.
Summaries are short (< 100 chars), never exceed embedding model limits.

Usage:
    python3 vectorize.py                      # Incremental from sessions
    python3 vectorize.py --from-archive       # Backfill from archive
    python3 vectorize.py --full               # Full re-index
    python3 vectorize.py --search "query"     # Semantic search
"""

import json
import sys
import argparse
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timezone
import requests

try:
    import chromadb
except ImportError:
    print("❌ ChromaDB not installed. Run: pip3 install chromadb")
    sys.exit(1)

# Paths
SESSIONS_DIR = Path.home() / ".qclaw/agents/main/sessions"
ARCHIVE_DIR = Path.home() / ".qclaw/skills/memoria/archive"
CHROMA_DB_PATH = Path.home() / ".qclaw/memoria/chroma_db"
VECTORIZE_STATE = Path.home() / ".qclaw/memoria/vectorize_state.json"

# Ollama config
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "bge-m3"
SUMMARY_MODEL = "qwen2.5:7b"


def get_embedding(text: str) -> list:
    """Get embedding from Ollama."""
    text = text[:500].strip()
    if not text:
        return None
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


def generate_summary(messages: list) -> str:
    """Generate summary using qwen2.5:7b."""
    if not messages:
        return ""
    
    # 取前 15 条
    texts = []
    for m in messages[:15]:
        role = m.get("role", "")
        text = m.get("text", m.get("content", ""))
        if text and "Sender (untrusted metadata)" not in text:
            prefix = "👤" if role == "user" else "🤖"
            texts.append(f"{prefix} {text[:200]}")
    
    if not texts:
        return ""
    
    conversation = "\n".join(texts[:10])
    prompt = f"""你是一个记忆整理助手。
以下是一段对话，请用一句话总结核心内容（20-50字，不要超过50字）：

{conversation}

摘要："""

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": SUMMARY_MODEL, "prompt": prompt, "stream": False, "temperature": 0.3},
            timeout=60
        )
        response.raise_for_status()
        summary = response.json().get("response", "").strip()
        if summary:
            return summary.split("\n")[0].strip()[:80]
    except Exception as e:
        print(f"⚠️  Summary failed: {e}")
    
    # Fallback: 取第一条用户消息
    for m in messages:
        if m.get("role") == "user":
            text = m.get("text", m.get("content", ""))[:60]
            return text + "..." if len(text) == 60 else text
    return ""


def extract_messages_from_jsonl(path: Path) -> list:
    """Extract messages from session JSONL."""
    messages = []
    if not path.exists():
        return messages
    try:
        with open(path, 'r', encoding='utf-8') as f:
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
                timestamp = obj.get("timestamp", "")
                content = msg.get("content", [])
                text = ""
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text = c.get("text", "").strip()
                            break
                elif isinstance(content, str):
                    text = content.strip()
                if text:
                    messages.append({"role": role, "text": text, "timestamp": timestamp})
    except Exception as e:
        print(f"⚠️  Failed to read {path.name}: {e}")
    return messages


def extract_messages_from_archive(path: Path) -> list:
    """Extract messages from archive JSON."""
    try:
        d = json.load(open(path, 'r', encoding='utf-8'))
        return d.get("messages", [])
    except Exception as e:
        print(f"⚠️  Failed to read archive {path.name}: {e}")
        return []


def infer_tags(messages: list) -> list:
    """Infer tags from message content."""
    all_text = " ".join((m.get("text", m.get("content", "")).lower() for m in messages))
    tags = []
    tag_map = {
        "memoria": ["memoria", "记忆系统"],
        "织影": ["织影", "aelovia", "weave"],
        "副业": ["副业", "兼职", "收入"],
        "埃洛维亚": ["埃洛维亚", "世界观"],
        "技术": ["python", "linux", "服务器", "架构", "运维"],
        "日常": ["日常", "聊天"],
        "日程": ["日历", "日程", "提醒", "cron", "日报"],
        "ThreadVibe": ["threadvibe", "websocket"],
    }
    for tag, keywords in tag_map.items():
        if any(kw in all_text for kw in keywords):
            tags.append(tag)
    return tags or ["未分类"]


def infer_channel(path: Path, messages: list) -> str:
    """Infer channel from path or content."""
    filename = path.name.lower()
    if "feishu" in filename:
        return "feishu"
    if "wechat" in filename:
        return "wechat"
    # Check first user message
    for m in messages:
        if m.get("role") == "user":
            text = m.get("text", m.get("content", "")).lower()
            if "feishu" in text or "飞书" in text:
                return "feishu"
            if "wechat" in text or "微信" in text:
                return "wechat"
            break
    return "webchat"


def get_chroma_collection():
    """Get ChromaDB collection."""
    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_or_create_collection(name="memories", metadata={"hnsw:space": "cosine"})


def load_vectorize_state() -> dict:
    if VECTORIZE_STATE.exists():
        with open(VECTORIZE_STATE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"vectorized": {}}


def save_vectorize_state(state: dict):
    VECTORIZE_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(VECTORIZE_STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_session_hash(path: Path) -> str:
    """Hash based on file mtime and size."""
    stat = path.stat()
    content = f"{path.name}:{stat.st_mtime}:{stat.st_size}"
    return hashlib.md5(content.encode()).hexdigest()


def vectorize_from_sessions(incremental: bool = True):
    """Vectorize from sessions directory."""
    collection = get_chroma_collection()
    state = load_vectorize_state()
    vectorized = state.get("vectorized", {})

    session_files = [f for f in SESSIONS_DIR.glob("*.jsonl") if ".deleted." not in f.name]
    print(f"📁 发现 {len(session_files)} 个 session 文件")

    to_process = []
    for f in session_files:
        session_id = f.stem
        if incremental and session_id in vectorized:
            file_hash = get_session_hash(f)
            if vectorized[session_id].get("hash") == file_hash:
                continue  # 未变化，跳过
        to_process.append(f)

    if not to_process:
        print("✅ 所有 session 已向量化，无需处理")
        return

    print(f"🔄 需要处理 {len(to_process)} 个 session...")
    success_count = 0

    for i, f in enumerate(to_process, 1):
        session_id = f.stem
        print(f"  [{i}/{len(to_process)}] {session_id[:8]}...", end=" ")
        
        messages = extract_messages_from_jsonl(f)
        if not messages:
            print("⚠️  无消息")
            continue
        
        # 生成摘要
        summary = generate_summary(messages)
        if not summary:
            print("⚠️  无摘要")
            continue
        
        # 向量化
        text = f"{summary} {' '.join(infer_tags(messages))}"
        embedding = get_embedding(text)
        if not embedding:
            print("❌ 向量化失败")
            continue
        
        # 存入 ChromaDB
        try:
            collection.upsert(
                ids=[session_id],
                embeddings=[embedding],
                documents=[summary],
                metadatas=[{
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "channel": infer_channel(f, messages),
                    "tags": ",".join(infer_tags(messages)),
                    "session_id": session_id,
                    "message_count": len(messages),
                }]
            )
            vectorized[session_id] = {
                "hash": get_session_hash(f),
                "vectorized_at": datetime.now(timezone.utc).isoformat(),
                "message_count": len(messages),
            }
            success_count += 1
            print(f"✅ {summary[:40]}")
        except Exception as e:
            print(f"❌ 存储失败: {e}")

    state["vectorized"] = vectorized
    state["last_vectorized"] = datetime.now(timezone.utc).isoformat()
    state["total_vectorized"] = len(vectorized)
    save_vectorize_state(state)

    print(f"\n✨ 完成: {success_count}/{len(to_process)}")
    print(f"📊 向量库总计: {len(vectorized)} 条")


def vectorize_from_archive():
    """Backfill from archive directory."""
    collection = get_chroma_collection()
    state = load_vectorize_state()
    vectorized = state.get("vectorized", {})

    archive_files = list(ARCHIVE_DIR.glob("*/*.json"))
    print(f"📁 发现 {len(archive_files)} 个归档文件")

    to_process = []
    for f in archive_files:
        # 从文件名提取 session_id
        session_id = f.stem.split("_")[-1]
        if session_id in vectorized:
            continue
        to_process.append(f)

    if not to_process:
        print("✅ 所有归档已向量化，无需处理")
        return

    print(f"🔄 需要处理 {len(to_process)} 个归档...")
    success_count = 0

    for i, f in enumerate(to_process, 1):
        # 从文件名提取 session_id
        session_id = f.stem.split("_")[-1]
        print(f"  [{i}/{len(to_process)}] {session_id[:8]}...", end=" ")
        
        messages = extract_messages_from_archive(f)
        if not messages:
            print("⚠️  无消息")
            continue
        
        # 从归档读取元数据
        try:
            d = json.load(open(f, 'r', encoding='utf-8'))
            archived_at = d.get("archived_at", "")
            channel = d.get("channel", infer_channel(f, messages))
            session_label = d.get("session_label", "")[:50]
        except:
            archived_at = ""
            channel = infer_channel(f, messages)
            session_label = ""
        
        # 生成摘要
        summary = generate_summary(messages)
        if not summary:
            summary = f"历史归档: {session_label}" if session_label else "历史归档对话"
        
        # 向量化
        text = f"{summary} {' '.join(infer_tags(messages))}"
        embedding = get_embedding(text)
        if not embedding:
            print("❌ 向量化失败")
            continue
        
        # 存入 ChromaDB
        try:
            collection.upsert(
                ids=[session_id],
                embeddings=[embedding],
                documents=[summary],
                metadatas=[{
                    "timestamp": archived_at or datetime.now(timezone.utc).isoformat(),
                    "channel": channel,
                    "tags": ",".join(infer_tags(messages)),
                    "session_id": session_id,
                    "message_count": len(messages),
                    "source": "archive",
                }]
            )
            vectorized[session_id] = {
                "vectorized_at": datetime.now(timezone.utc).isoformat(),
                "message_count": len(messages),
                "source": "archive",
            }
            success_count += 1
            print(f"✅ {summary[:40]}")
        except Exception as e:
            print(f"❌ 存储失败: {e}")

    state["vectorized"] = vectorized
    state["last_vectorized"] = datetime.now(timezone.utc).isoformat()
    state["total_vectorized"] = len(vectorized)
    save_vectorize_state(state)

    print(f"\n✨ 完成: {success_count}/{len(to_process)}")
    print(f"📊 向量库总计: {len(vectorized)} 条")


def search_memories(query: str, limit: int = 5):
    """Search memories by semantic similarity."""
    query_embedding = get_embedding(query)
    if not query_embedding:
        print("❌ Failed to embed query")
        return

    collection = get_chroma_collection()
    results = collection.query(query_embeddings=[query_embedding], n_results=limit)

    if not results["ids"] or not results["ids"][0]:
        print("❌ No similar memories found")
        return

    print(f"\n🔍 搜索: '{query}'\n")
    for i, (mid, doc, distance, meta) in enumerate(zip(
        results["ids"][0],
        results["documents"][0],
        results["distances"][0],
        results["metadatas"][0]
    ), 1):
        similarity = max(0, (1 - distance)) * 100
        ts = meta.get("timestamp", "")[:10]
        ch = meta.get("channel", "?")
        tags = meta.get("tags", "")
        print(f"[{ts}][{ch}][{tags}] {doc}")


def main():
    parser = argparse.ArgumentParser(description="Vectorize memories for semantic search")
    parser.add_argument("--from-archive", action="store_true", help="Backfill from archive")
    parser.add_argument("--full", action="store_true", help="Full re-index (ignore incremental)")
    parser.add_argument("--search", type=str, help="Search memories by query")
    parser.add_argument("--limit", type=int, default=5, help="Search result limit")

    args = parser.parse_args()

    if args.search:
        search_memories(args.search, args.limit)
    elif args.from_archive:
        vectorize_from_archive()
    else:
        vectorize_from_sessions(incremental=not args.full)


if __name__ == "__main__":
    main()
