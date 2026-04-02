#!/usr/local/bin/python3.12
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
from pathlib import Path
from datetime import datetime, timezone

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
    SESSIONS_DIR,
    ARCHIVE_DIR,
    CHROMA_DB_PATH,
)

VECTORIZE_STATE = CHROMA_DB_PATH.parent / "vectorize_state.json"


def load_vectorize_state() -> dict:
    if VECTORIZE_STATE.exists():
        try:
            with open(VECTORIZE_STATE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
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
                continue
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
        summary = generate_summary_from_messages(messages)
        if not summary:
            print("⚠️  无摘要")
            continue
        
        # P0-3: 摘要质量校验
        if not is_valid_summary(summary):
            print(f"⚠️  摘要质量不足，跳过: {summary[:30]}")
            continue
        
        # P1-3: 规则 tags 优先，未分类时用 LLM
        rule_tags = infer_tags(messages)
        final_tags = rule_tags if rule_tags != ["未分类"] else infer_tags_with_llm(summary)
        
        # 向量化
        text = f"{summary} {' '.join(final_tags)}"
        embedding = get_embedding(text)
        if not embedding:
            print("❌ 向量化失败")
            continue
        
        # P0-1: 从消息中提取对话实际时间
        session_timestamp = get_session_start_time(messages)
        
        # 存入 ChromaDB
        try:
            collection.upsert(
                ids=[session_id],
                embeddings=[embedding],
                documents=[summary],
                metadatas=[{
                    "timestamp": session_timestamp,
                    "channel": infer_channel(f, messages),
                    "tags": ",".join(final_tags),
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
        session_id = f.stem.split("_")[-1]
        print(f"  [{i}/{len(to_process)}] {session_id[:8]}...", end=" ")
        
        try:
            d = json.load(open(f, 'r', encoding='utf-8'))
            messages = d.get("messages", [])
            archived_at = d.get("archived_at", "")
            channel = d.get("channel", "webchat")
            session_label = d.get("session_label", "")[:50]
        except Exception as e:
            print(f"⚠️  读取失败: {e}")
            continue
        
        if not messages:
            print("⚠️  无消息")
            continue
        
        # 生成摘要
        summary = generate_summary_from_messages(messages)
        if not summary:
            summary = f"历史归档: {session_label}" if session_label else "历史归档对话"
        
        # P0-1: 从消息中提取对话实际时间（archive 回填也用对话时间，不用 archived_at）
        actual_ts = get_session_start_time(messages)
        
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
                    "timestamp": actual_ts,
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
