"""
向量库操作
"""

import sys

from .config import CHROMA_DB_PATH, COLLECTION_NAME, EMBEDDING_MAX_CHARS
from .utils import get_utc_timestamp, truncate_for_embedding


def get_collection():
    """获取 ChromaDB collection"""
    try:
        import chromadb
    except ImportError:
        raise ImportError("chromadb not installed")
    
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def write_vector(
    memory_id: str,
    archive_path: str,
    content: str,
    tags: list[str],
    links: list[str],
    source: str,
    session_id: str = None
) -> bool:
    """
    写入向量库
    
    Returns:
        True if success, False if failed
    """
    try:
        collection = get_collection()
        
        # 准备 embedding 输入（截断）
        embedding_text = truncate_for_embedding(content, EMBEDDING_MAX_CHARS)
        
        # 准备 metadata
        metadata = {
            "memory_id": memory_id,
            "archive_path": archive_path,
            "timestamp": get_utc_timestamp(),
            "source": source,
            "tags": ",".join(tags),
            "links": ",".join(links),
            "session_id": session_id or ""
        }
        
        # 写入向量库
        collection.add(
            ids=[memory_id],
            documents=[content],  # 全文存储
            metadatas=[metadata]
        )
        
        return True
    except Exception as e:
        print(f"ERROR: vector write failed: {e}", file=sys.stderr)
        return False


def search_vector(query: str, limit: int = 5) -> list[dict]:
    """
    向量搜索
    
    Returns:
        [
            {
                "memory_id": "xxx",
                "archive_path": "...",
                "score": 0.95,
                "metadata": {...}
            },
            ...
        ]
    """
    try:
        collection = get_collection()
        
        results = collection.query(
            query_texts=[query],
            n_results=limit
        )
        
        if not results['ids'] or not results['ids'][0]:
            return []
        
        memories = []
        for i, memory_id in enumerate(results['ids'][0]):
            # cosine distance → similarity
            # ChromaDB cosine distance: 0 (identical) to 2 (opposite)
            # similarity = 1 - distance/2 → 0 to 1
            distance = results['distances'][0][i] if results['distances'] else 0
            similarity = max(0, 1 - distance / 2)
            
            memories.append({
                "memory_id": memory_id,
                "archive_path": results['metadatas'][0][i].get('archive_path', ''),
                "score": similarity,
                "metadata": results['metadatas'][0][i]
            })
        
        return memories
    except Exception as e:
        print(f"ERROR: vector search failed: {e}", file=sys.stderr)
        return []


def delete_vector(memory_id: str) -> bool:
    """删除向量"""
    try:
        collection = get_collection()
        collection.delete(ids=[memory_id])
        return True
    except Exception as e:
        print(f"ERROR: vector delete failed: {e}", file=sys.stderr)
        return False
