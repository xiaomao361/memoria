#!/usr/bin/env python3
"""
Memoria Lite 统一读取入口 recall()

三种检索模式：
    - tags: 标签精确匹配
    - keyword: 关键词搜索（热缓存优先 + Archive 回退）
    - hybrid: 混合模式（先 tags，再 keyword 补充）

用法:
    python3 recall.py --query "用户偏好"
    python3 recall.py --query "用户偏好" --mode tags
    python3 recall.py --query "用户偏好" --mode keyword --limit 5
    python3 recall.py --memory-id abc123

返回:
    [
        {
            "id": "abc123",
            "score": 0.85,
            "match_type": "keyword_hot",
            "summary": "...",
            "tags": [...],
            "links": [...],
            "archive_path": "..."
        }
    ]
"""

import argparse
import json
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.search import recall


def main():
    parser = argparse.ArgumentParser(description="Memoria Lite 统一读取入口")
    parser.add_argument("--query", default="", help="搜索查询")
    parser.add_argument("--mode", default="hybrid", 
                       choices=["tags", "keyword", "hybrid"],
                       help="检索模式")
    parser.add_argument("--limit", type=int, default=10, help="返回数量上限")
    parser.add_argument("--memory-id", default=None, help="直接指定 memory_id")
    
    args = parser.parse_args()
    
    # 如果没有指定 query 和 memory-id，给出提示
    if not args.query and not args.memory_id:
        print("请指定 --query 或 --memory-id")
        print("示例:")
        print("  python3 recall.py --query '用户偏好'")
        print("  python3 recall.py --memory-id abc123")
        sys.exit(1)
    
    # 调用 recall
    results = recall(
        query=args.query,
        mode=args.mode,
        limit=args.limit,
        memory_id=args.memory_id
    )
    
    # 输出结果
    if results:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("[]")


if __name__ == "__main__":
    main()
