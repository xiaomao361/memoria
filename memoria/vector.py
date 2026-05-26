"""向量操作 - ChromaDB + Ollama bge-m3"""

import sys
from typing import Optional

from .config import (
    OLLAMA_URL, EMBEDDING_MODEL, EMBEDDING_DIM, EMBEDDING_MAX_CHARS,
    VECTORS_DIR, CHROMA_COLLECTION, CHROMA_PRIVATE_COLLECTION,
)


def get_embedding(text: str) -> Optional[list[float]]:
    """通过 Ollama 获取 bge-m3 embedding"""
    try:
        import requests

        truncated = text[:EMBEDDING_MAX_CHARS]
        resp = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": truncated},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as e:
        print(f"WARN: embedding failed: {e}", file=sys.stderr)
        return None


def _get_collection(private: bool = False):
    import chromadb

    db_path = VECTORS_DIR / ("private" if private else "public")
    db_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_path))
    name = CHROMA_PRIVATE_COLLECTION if private else CHROMA_COLLECTION
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection(private: bool = False) -> bool:
    """清空并重建向量 collection。用于 rebuild 避免陈旧向量残留。"""
    try:
        import chromadb

        db_path = VECTORS_DIR / ("private" if private else "public")
        db_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(db_path))
        name = CHROMA_PRIVATE_COLLECTION if private else CHROMA_COLLECTION
        try:
            client.delete_collection(name)
        except Exception:
            pass
        client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        return True
    except Exception as e:
        print(f"WARN: vector reset failed: {e}", file=sys.stderr)
        return False


def upsert_vector(memory_id: str, text: str, private: bool = False) -> bool:
    """写入或更新向量索引"""
    embedding = get_embedding(text)
    if not embedding:
        return False
    try:
        col = _get_collection(private=private)
        col.upsert(ids=[memory_id], embeddings=[embedding])
        return True
    except Exception as e:
        print(f"WARN: vector upsert failed: {e}", file=sys.stderr)
        return False


def search_vectors(query: str, limit: int = 10, private: bool = False) -> list[dict]:
    """语义搜索，返回 [{id, score}]"""
    embedding = get_embedding(query)
    if not embedding:
        return []
    try:
        col = _get_collection(private=private)
        results = col.query(query_embeddings=[embedding], n_results=limit)
        if not results["ids"] or not results["ids"][0]:
            return []
        out = []
        for i, mid in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            score = max(0.0, 1.0 - distance / 2.0)
            out.append({"id": mid, "score": round(score, 4)})
        return out
    except Exception as e:
        print(f"WARN: vector search failed: {e}", file=sys.stderr)
        return []


def delete_vector(memory_id: str, private: bool = False) -> bool:
    try:
        col = _get_collection(private=private)
        col.delete(ids=[memory_id])
        return True
    except Exception as e:
        print(f"WARN: vector delete failed: {e}", file=sys.stderr)
        return False
