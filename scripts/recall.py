#!/usr/local/bin/python3.12
"""
Recall memories from ChromaDB with semantic search.
Replaces memoria.json-based lookup with direct ChromaDB queries.

Usage:
    python3 recall.py --combined --simple              # Load combined memories (default)
    python3 recall.py --search "query"                 # Semantic search
    python3 recall.py --search "query" --limit 10      # Search with limit
    python3 recall.py --recent --days 7 --limit 5      # Recent memories
    python3 recall.py --important --limit 3            # Important memories only
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests

try:
    import chromadb
except ImportError:
    print("❌ ChromaDB not installed. Run: pip3 install chromadb")
    sys.exit(1)

# Paths
CHROMA_DB_PATH = Path.home() / ".qclaw/memoria/chroma_db"
OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "bge-m3"


def get_chroma_collection():
    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_or_create_collection(name="memories", metadata={"hnsw:space": "cosine"})


def get_embedding(text: str) -> list:
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text[:500]},
            timeout=30
        )
        response.raise_for_status()
        return response.json()["embedding"]
    except Exception as e:
        print(f"❌ Embedding failed: {e}")
        return None


def parse_ts(ts_str: str) -> datetime:
    """Parse timestamp string to UTC-aware datetime."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        # 如果是 naive datetime，强制加 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return datetime.min.replace(tzinfo=timezone.utc)


def format_memory(memory_id: str, document: str, metadata: dict, distance: float = None) -> str:
    ts = metadata.get("timestamp", "")
    channel = metadata.get("channel", "")
    tags = metadata.get("tags", "").split(",") if metadata.get("tags") else []

    try:
        time_str = parse_ts(ts).strftime("%m-%d %H:%M")
    except:
        time_str = "unknown"

    output = f"[{memory_id[:8]}...] {time_str} | {channel}"
    if tags:
        output += f" | {', '.join(tags)}"
    if distance is not None:
        # cosine distance: 0=完全相同, 1=正交, 2=完全相反
        # 转换为相似度百分比
        similarity = max(0, (1 - distance)) * 100
        output += f" | {similarity:.1f}%"
    output += f"\n  {document[:100]}\n"
    return output


def load_combined_memories(days: int = 7, recent_limit: int = 10, important_limit: int = 5) -> list:
    collection = get_chroma_collection()

    if collection.count() == 0:
        print("⚠️  No memories in database")
        return []

    # 统一用 UTC aware
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    combined = {}

    try:
        all_results = collection.get(limit=1000)

        if all_results and all_results["ids"]:
            for mid, doc, meta in zip(
                all_results["ids"],
                all_results["documents"],
                all_results["metadatas"]
            ):
                ts = parse_ts(meta.get("timestamp", ""))
                is_recent = ts >= cutoff_date
                is_important = "重要" in meta.get("tags", "")

                if is_recent or is_important:
                    combined[mid] = {
                        "document": doc,
                        "metadata": meta,
                        "type": "important" if is_important else "recent",
                        "timestamp": ts
                    }
    except Exception as e:
        print(f"⚠️  Failed to load memories: {e}")
        return []

    # 排序：最新优先
    sorted_memories = sorted(
        combined.items(),
        key=lambda x: x[1]["timestamp"],
        reverse=True
    )

    return [(mid, m["document"], m["metadata"], None)
            for mid, m in sorted_memories[:recent_limit + important_limit]]


def search_memories(query: str, limit: int = 5) -> list:
    query_embedding = get_embedding(query)
    if not query_embedding:
        print("❌ Failed to embed query")
        return []

    collection = get_chroma_collection()

    try:
        results = collection.query(query_embeddings=[query_embedding], n_results=limit)

        if not results["ids"] or not results["ids"][0]:
            print("❌ No similar memories found")
            return []

        memories = []
        for i, (mid, doc, distance) in enumerate(zip(
            results["ids"][0],
            results["documents"][0],
            results["distances"][0]
        )):
            metadata = results["metadatas"][0][i]
            memories.append((mid, doc, metadata, distance))

        return memories

    except Exception as e:
        print(f"❌ Search failed: {e}")
        return []


def get_recent_memories(days: int = 7, limit: int = 5) -> list:
    collection = get_chroma_collection()
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        all_results = collection.get(limit=1000)
        if not all_results["ids"]:
            return []

        memories = []
        for mid, doc, meta in zip(
            all_results["ids"],
            all_results["documents"],
            all_results["metadatas"]
        ):
            ts = parse_ts(meta.get("timestamp", ""))
            if ts >= cutoff_date:
                memories.append((mid, doc, meta, None))

        memories.sort(key=lambda x: parse_ts(x[2].get("timestamp", "")), reverse=True)
        return memories[:limit]

    except Exception as e:
        print(f"❌ Failed to get recent memories: {e}")
        return []


def get_important_memories(limit: int = 5) -> list:
    collection = get_chroma_collection()

    try:
        results = collection.get(limit=1000)
        if not results["ids"]:
            return []

        memories = [
            (mid, doc, meta, None)
            for mid, doc, meta in zip(results["ids"], results["documents"], results["metadatas"])
            if "重要" in meta.get("tags", "")
        ]

        if not memories:
            print("⚠️  No important memories found")

        return memories[:limit]

    except Exception as e:
        print(f"❌ Failed to get important memories: {e}")
        return []


def print_memories(memories: list, title: str = ""):
    if not memories:
        return
    if title:
        print(f"\n{title}\n")
    for mid, doc, meta, distance in memories:
        print(format_memory(mid, doc, meta, distance))


def main():
    parser = argparse.ArgumentParser(description="Recall memories from ChromaDB")
    parser.add_argument("--combined", action="store_true")
    parser.add_argument("--search", type=str)
    parser.add_argument("--recent", action="store_true")
    parser.add_argument("--important", action="store_true")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--simple", action="store_true")

    args = parser.parse_args()

    if not any([args.combined, args.search, args.recent, args.important]):
        args.combined = True

    memories = []
    title = ""

    if args.combined:
        memories = load_combined_memories(days=args.days, recent_limit=10, important_limit=5)
        title = "📚 Combined Memories (Recent + Important)"
    elif args.search:
        memories = search_memories(args.search, limit=args.limit)
        title = f"🔍 Search: '{args.search}'"
    elif args.recent:
        memories = get_recent_memories(days=args.days, limit=args.limit)
        title = f"📅 Recent ({args.days} days)"
    elif args.important:
        memories = get_important_memories(limit=args.limit)
        title = "⭐ Important"

    if args.simple:
        for i, (mid, doc, meta, distance) in enumerate(memories, 1):
            tags = meta.get("tags", "")
            print(f"[{meta.get('timestamp', '')[:10]}][{meta.get('channel', '')}][{tags}] {doc[:80]}")
    else:
        print_memories(memories, title)


if __name__ == "__main__":
    main()
