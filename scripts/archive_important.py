#!/usr/local/bin/python3.12
"""
Memoria archive_important.py — 单独记录重要内容到 archive 并向量化

触发时机：用户说"记下来"、"单独记一下"等手动触发

流程：
1. 写入原始内容到 archive/{YYYY-MM}/{项目名}-{向量ID}.txt
2. 调用 3b 模型生成摘要
3. 将摘要写入向量库（带 archive_path 字段）

用法：
    python3 archive_important.py --project "项目名" --content "要记录的内容"
    python3 archive_important.py --project "Kraken" --content "今天完成了二期团体报告功能"
"""

import json
import sys
import os
import uuid
import argparse
from datetime import datetime, timezone
from pathlib import Path

# 导入共用工具库
from memoria_utils import (
    get_chroma_collection,
    get_embedding,
    generate_summary,
    MEMORIA_DIR,
    ARCHIVE_DIR,
    SUMMARY_MODEL,
)


def archive_important_content(project: str, content: str, tags: list = None) -> dict:
    """
    将重要内容写入 archive 并向量化
    
    Returns:
        {
            "id": "向量ID",
            "archive_path": "archive/.../xxx.txt",
            "summary": "摘要内容"
        }
    """
    # 1. 生成向量 ID
    memory_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # 2. 写入原始内容到 archive
    month_dir = ARCHIVE_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    
    safe_project = project.replace("/", "_").replace("\\", "_")[:20]
    archive_file = month_dir / f"{safe_project}-{memory_id}.txt"
    
    full_content = f"""# {project}
# 创建时间: {now.isoformat()}
# 记忆ID: {memory_id}

{content}
"""
    
    with open(archive_file, "w", encoding="utf-8") as f:
        f.write(full_content)
    
    # 3. 用 3b 模型生成摘要
    summary = generate_summary(content, model=SUMMARY_MODEL)
    if not summary:
        summary = content[:50]  # fallback
    
    # 4. 写入向量库
    collection = get_chroma_collection()
    
    # 准备元数据
    metadata = {
        "memory_id": memory_id,
        "timestamp": now.isoformat(),
        "channel": "archive",
        "project": project,
        "archive_path": str(archive_file),
        "tags": ",".join(tags) if tags else "",
    }
    
    # 添加到向量库
    collection.upsert(
        ids=[memory_id],
        embeddings=[get_embedding(content)],
        documents=[content],
        metadatas=[metadata]
    )
    
    # 5. 同步更新 memoria.json 索引（可选，便于统一检索）
    index_file = MEMORIA_DIR / "memoria.json"
    if index_file.exists():
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except:
            index_data = {"memories": [], "version": "3.0"}
    else:
        index_data = {"memories": [], "version": "3.0"}
    
    entry = {
        "id": memory_id,
        "timestamp": now.isoformat(),
        "channel": "archive",
        "tags": tags or [],
        "summary": summary,
        "project": project,
        "archive_path": str(archive_file),
        "storage_type": "archive",
    }
    index_data["memories"].insert(0, entry)
    
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    
    return {
        "id": memory_id,
        "archive_path": str(archive_file),
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser(description="Memoria — 单独记录重要内容到 archive")
    parser.add_argument("--project", required=True, help="项目/主题名称")
    parser.add_argument("--content", required=True, help="要记录的内容")
    parser.add_argument("--tags", default="", help="标签，逗号分隔")
    
    args = parser.parse_args()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    
    result = archive_important_content(args.project, args.content, tags)
    
    print(f"✅ 已写入 archive 并向量化")
    print(f"   ID: {result['id']}")
    print(f"   项目: {args.project}")
    print(f"   摘要: {result['summary']}")
    print(f"   原文路径: {result['archive_path']}")


if __name__ == "__main__":
    main()
