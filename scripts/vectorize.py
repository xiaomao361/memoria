#!/usr/bin/env python3
"""
Vectorize memories using nomic-embed-text via Ollama.
Stores vectors in ChromaDB for semantic search.

Key design: vectorize SUMMARIES not raw conversations.
Summaries are short (< 50 chars), never exceed embedding model limits.

Usage:
    python3 vectorize.py                    # Full re-vectorization from memoria.json
    python3 vectorize.py --incremental      # Only new memories
    python3 vectorize.py --from-sessions    # Vectorize from sessions (auto-summarize)
    python3 vectorize.py --search "query"   # Semantic search
"""

import json
import sys
import argparse
import hashlib
import uuid
from pathlib import Path
from datetime import datetime
import requests

try:
    import chromadb
except ImportError:
    print("❌ ChromaDB not installed. Run: pip3 install chromadb")
    sys.exit(1)

# Paths
MEMORIA_JSON = Path.home() / ".qclaw/skills/memoria/memoria.json"
CHROMA_DB_PATH = Path.home() / ".qclaw/memoria/chroma_db"
VECTORIZE_STATE = Path.home() / ".qclaw/memoria/vectorize_state.json"
SESSIONS_DIR = Path.home() / ".qclaw/agents/main/sessions"

# Ollama config
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "bge-m3"
SUMMARY_MODEL = "qwen2.5:7b"


def get_embedding(text: str) -> list:
    """Get embedding from Ollama. Input must be short (summary-level)."""
    # 严格截断到 500 字符，摘要级别，绝对不超限
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


def generate_summary(session_id: str) -> str:
    """Generate summary from session using qwen2.5:7b."""
    session_file = SESSIONS_DIR / f"{session_id}.jsonl"
    if not session_file.exists():
        return ""

    # 提取前 10 条对话
    texts = []
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
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
                        texts.append(f"{role.upper()}: {text[:200]}")
                        if len(texts) >= 20:
                            break
                except:
                    continue
    except:
        return ""

    if not texts:
        return ""

    conversation = "\n".join(texts[:10])
    prompt = f"""你是一个记忆整理助手。
以下是一段对话，请用一句话总结核心内容（15-30字以内，不要超过30字）：

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
            return summary.split("\n")[0].strip()[:50]
    except Exception as e:
        print(f"⚠️  Summary failed: {e}")

    return ""


def get_chroma_collection():
    """Get ChromaDB collection."""
    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_or_create_collection(name="memories", metadata={"hnsw:space": "cosine"})


def load_memories() -> dict:
    """Load memoria.json."""
    if not MEMORIA_JSON.exists():
        print(f"⚠️  {MEMORIA_JSON} not found")
        return {}
    with open(MEMORIA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {m["id"]: m for m in data.get("memories", [])}


def load_vectorize_state() -> dict:
    if VECTORIZE_STATE.exists():
        with open(VECTORIZE_STATE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"vectorized": {}}


def save_vectorize_state(state: dict):
    VECTORIZE_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(VECTORIZE_STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def get_memory_hash(memory: dict) -> str:
    content = f"{memory['id']}:{memory['summary']}:{memory['tags']}"
    return hashlib.md5(content.encode()).hexdigest()


def vectorize_memories(incremental: bool = False, memory_id: str = None):
    """Vectorize memories from memoria.json — uses summary as embedding input."""
    collection = get_chroma_collection()
    memories = load_memories()
    state = load_vectorize_state()
    vectorized = state.get("vectorized", {})

    if not memories:
        print("⚠️  No memories to vectorize")
        return

    if memory_id:
        to_process = {memory_id: memories[memory_id]} if memory_id in memories else {}
    elif incremental:
        to_process = {
            mid: m for mid, m in memories.items()
            if mid not in vectorized or vectorized[mid].get("hash") != get_memory_hash(m)
        }
    else:
        to_process = memories

    if not to_process:
        print("✅ All memories already vectorized")
        return

    print(f"🔄 Vectorizing {len(to_process)} memories...")
    success_count = 0

    for mid, memory in to_process.items():
        # 只用摘要 + 标签，短文本，绝对不超限
        text = f"{memory['summary']} {' '.join(memory.get('tags', []))}"

        embedding = get_embedding(text)
        if not embedding:
            print(f"⚠️  Failed to embed {mid[:8]}")
            continue

        try:
            collection.upsert(
                ids=[mid],
                embeddings=[embedding],
                documents=[memory['summary']],
                metadatas=[{
                    "timestamp": memory['timestamp'],
                    "channel": memory['channel'],
                    "tags": ",".join(memory.get('tags', [])),
                    "session_id": memory.get('session_id', ''),
                }]
            )
            vectorized[mid] = {
                "hash": get_memory_hash(memory),
                "vectorized_at": datetime.now().isoformat(),
                "embedding_model": EMBEDDING_MODEL
            }
            success_count += 1
            print(f"✅ {mid[:8]}... done")
        except Exception as e:
            print(f"❌ Failed to store {mid[:8]}: {e}")

    state["vectorized"] = vectorized
    state["last_vectorized"] = datetime.now().isoformat()
    state["total_vectorized"] = len(vectorized)
    save_vectorize_state(state)

    print(f"\n✨ Done: {success_count}/{len(to_process)}")
    print(f"📊 Total vectorized: {len(vectorized)}")


def vectorize_from_sessions(session_ids: list = None):
    """Vectorize directly from sessions — auto-generate summary first, then embed."""
    collection = get_chroma_collection()

    if not session_ids:
        session_files = list(SESSIONS_DIR.glob("*.jsonl"))
        session_ids = [f.stem for f in session_files if ".deleted." not in f.name]

    if not session_ids:
        print("⚠️  No sessions found")
        return

    print(f"🔄 Vectorizing {len(session_ids)} sessions (summarize → embed)...")
    state = load_vectorize_state()
    vectorized = state.get("vectorized", {})
    success_count = 0

    for session_id in session_ids:
        # Step 1: 生成摘要（短文本）
        print(f"  📝 Summarizing {session_id[:8]}...")
        summary = generate_summary(session_id)
        if not summary:
            print(f"  ⚠️  No summary for {session_id[:8]}, skipping")
            continue

        print(f"     → {summary}")

        # Step 2: 向量化摘要（绝对不超限）
        embedding = get_embedding(summary)
        if not embedding:
            print(f"  ❌ Embedding failed for {session_id[:8]}")
            continue

        # Step 3: 存入 ChromaDB
        memory_id = str(uuid.uuid4())
        try:
            collection.upsert(
                ids=[memory_id],
                embeddings=[embedding],
                documents=[summary],
                metadatas=[{
                    "timestamp": datetime.now().isoformat(),
                    "channel": "webchat",
                    "tags": "session-vectorized",
                    "session_id": session_id,
                }]
            )
            vectorized[memory_id] = {
                "session_id": session_id,
                "vectorized_at": datetime.now().isoformat(),
                "embedding_model": EMBEDDING_MODEL
            }
            success_count += 1
            print(f"  ✅ {session_id[:8]}... saved")
        except Exception as e:
            print(f"  ❌ Store failed: {e}")

    state["vectorized"] = vectorized
    state["last_vectorized"] = datetime.now().isoformat()
    state["total_vectorized"] = len(vectorized)
    save_vectorize_state(state)

    print(f"\n✨ Done: {success_count}/{len(session_ids)} sessions")


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

    print(f"\n🔍 Search results for: '{query}'\n")
    for i, (mid, doc, distance) in enumerate(zip(
        results["ids"][0], results["documents"][0], results["distances"][0]
    ), 1):
        similarity = 1 - distance
        print(f"{i}. [{mid[:8]}...] (similarity: {similarity:.2%})")
        print(f"   {doc[:100]}\n")


def main():
    parser = argparse.ArgumentParser(description="Vectorize memories for semantic search")
    parser.add_argument("--incremental", action="store_true", help="Only vectorize new/changed memories")
    parser.add_argument("--memory-id", type=str, help="Vectorize specific memory by ID")
    parser.add_argument("--from-sessions", action="store_true", help="Vectorize from sessions (auto-summarize)")
    parser.add_argument("--search", type=str, help="Search memories by query")
    parser.add_argument("--limit", type=int, default=5, help="Search result limit")

    args = parser.parse_args()

    if args.search:
        search_memories(args.search, args.limit)
    elif args.from_sessions:
        vectorize_from_sessions()
    else:
        vectorize_memories(incremental=args.incremental, memory_id=args.memory_id)


if __name__ == "__main__":
    main()
