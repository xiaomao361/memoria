#!/usr/local/bin/python3.12
"""
Memoria recall_with_context.py — 搜索并自动获取 archive 原文

逻辑：
1. 搜索向量库（使用 recall.py 的方式）
2. 如果有 archive 类型的结果，自动获取原文
3. 返回：摘要列表 + 原文内容（供 AI 融入上下文）

用法：
    python3 recall_with_context.py --search "关键词"
"""

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memoria_utils import get_chroma_collection, get_archive_content


def search_with_context(query: str, n_results: int = 5) -> dict:
    """
    搜索向量库，并自动获取 archive 原文
    
    Returns:
        {
            "results": [
                {
                    "id": "xxx",
                    "summary": "摘要",
                    "channel": "archive/webchat",
                    "tags": ["tag1", "tag2"],
                    "full_content": "原文（仅 archive 类型有）"
                }
            ]
        }
    """
    collection = get_chroma_collection()
    
    # 使用 get + where 过滤（不需要 embedding）
    all_data = collection.get(limit=1000)
    
    output = []
    if all_data and all_data.get("ids"):
        # 在内存中进行简单的关键词匹配（模拟搜索）
        query_lower = query.lower()
        scores = []
        
        for i, doc_id in enumerate(all_data["ids"]):
            document = all_data["documents"][i] if all_data.get("documents") else ""
            metadata = all_data["metadatas"][i] if all_data.get("metadatas") else {}
            
            # 简单评分：文档中包含关键词
            score = 0
            if document and query_lower in document.lower():
                score = 1.0
            elif metadata.get("tags") and query_lower in metadata.get("tags", "").lower():
                score = 0.7
            elif metadata.get("project") and query_lower in metadata.get("project", "").lower():
                score = 0.8
            
            if score > 0:
                scores.append({
                    "id": doc_id,
                    "document": document,
                    "metadata": metadata,
                    "score": score
                })
        
        # 按分数排序，取前 n 个
        scores.sort(key=lambda x: x["score"], reverse=True)
        
        for item in scores[:n_results]:
            metadata = item["metadata"]
            document = item["document"]
            channel = metadata.get("channel", "")
            
            # 如果是 archive 类型，自动获取原文
            full_content = ""
            if channel == "archive":
                result = get_archive_content(item["id"])
                full_content = result.get("full_content", "")
            
            output.append({
                "id": item["id"],
                "summary": document[:150] if document else metadata.get("summary", ""),
                "channel": channel,
                "tags": metadata.get("tags", "").split(",") if metadata.get("tags") else [],
                "timestamp": metadata.get("timestamp", ""),
                "score": item["score"],
                "full_content": full_content,
            })
    
    return {"results": output}


def print_results(result: dict, max_show: int = 5):
    """打印搜索结果"""
    print(f"\n🔍 找到 {len(result['results'])} 条结果：\n")
    
    for i, r in enumerate(result["results"][:max_show]):
        print(f"[{i+1}] {r['id'][:8]}... | {r['channel']} | {', '.join(r['tags']) or '无'}")
        print(f"    {r['summary']}")
        if r.get("full_content"):
            print(f"    📄 已获取原文 ({len(r['full_content'])} 字)")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memoria 搜索 + 自动获取 archive 原文")
    parser.add_argument("--search", required=True, help="搜索关键词")
    parser.add_argument("--max", type=int, default=5, help="最多返回条数")
    
    args = parser.parse_args()
    
    result = search_with_context(args.search, n_results=args.max)
    print_results(result)
    
    # 输出 JSON 格式（供 AI 解析）
    print("\n--- JSON OUTPUT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
