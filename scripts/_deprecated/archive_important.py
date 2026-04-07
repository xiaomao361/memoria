#!/usr/local/bin/python3.12
"""
Memoria archive_important.py — 单独记录重要内容到 archive 并向量化

触发时机：
1. 用户说"记下来"、"单独记一下"等手动触发（--content）
2. 用户说"记一下"（自动抓取当前 session）

用法：
    # 手动传入内容
    python3 archive_important.py --project "项目名" --content "要记录的内容"
    
    # 自动抓取当前 session
    python3 archive_important.py --project "auto" --auto
    
    # 指定 session
    python3 archive_important.py --project "auto" --auto --session-id "xxx"
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
    generate_summary_from_messages,
    extract_conversation_text,
    extract_messages_from_jsonl,
    infer_tags,
    extract_links,
    update_links_index,
    MEMORIA_DIR,
    ARCHIVE_DIR,
    SESSIONS_DIR,
    SUMMARY_MODEL,
)


def get_latest_session() -> tuple:
    """获取最新 session JSONL 的 path 和 session_id"""
    if not SESSIONS_DIR.exists():
        return None, None
    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None, None
    latest = files[0]
    session_id = latest.stem
    return str(latest), session_id


def auto_extract_from_session(session_id: str = None) -> dict:
    """
    自动从 session 提取对话内容
    
    Args:
        session_id: 指定 session ID（可选，默认取最新的）
    
    Returns:
        {
            "session_id": "xxx",
            "session_path": "xxx",
            "messages_text": "对话文本",
            "summary": "摘要",
            "tags": ["标签1", "标签2"]
        }
    """
    # 1. 获取 session
    if session_id:
        session_path = SESSIONS_DIR / f"{session_id}.jsonl"
        if not session_path.exists():
            session_path, session_id = get_latest_session()
    else:
        session_path, session_id = get_latest_session()
    
    if not session_path or not Path(session_path).exists():
        return {"error": "未找到 session"}
    
    # 2. 提取对话
    messages = extract_messages_from_jsonl(Path(session_path))
    if not messages:
        return {"error": "session 为空"}
    
    # 3. 生成摘要
    summary = generate_summary_from_messages(messages, limit=20)
    
    # 4. 推断标签
    tags = infer_tags(messages)
    
    # 5. 提取对话文本
    messages_text = extract_conversation_text(messages, limit=50)
    
    return {
        "session_id": session_id,
        "session_path": str(session_path),
        "messages_text": messages_text,
        "summary": summary,
        "tags": tags,
    }


def archive_important_content(project: str, content: str, tags: list = None, manual_links: list = None) -> dict:
    """
    将重要内容写入 archive 并向量化
    
    支持 [[链接]] 语法，自动提取并存入元数据
    支持手动传入链接，与自动提取的合并
    
    Args:
        project: 项目名称
        content: 内容（支持 [[链接]] 语法）
        tags: 标签列表
        manual_links: 手动传入的链接列表（优先级最高）
    
    Returns:
        {
            "id": "向量ID",
            "archive_path": "archive/.../xxx.txt",
            "summary": "摘要内容",
            "links": ["链接1", "链接2"]
        }
    """
    # 1. 生成向量 ID
    memory_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # 2. 提取链接：手动传入 + 自动提取 [[链接]]
    auto_links = extract_links(content)
    if manual_links:
        # 合并去重，手动传入的优先
        manual_links_lower = [l.lower().strip() for l in manual_links if l.strip()]
        links = list(dict.fromkeys(manual_links_lower + auto_links))
    else:
        links = auto_links
    
    # 3. 写入原始内容到 archive
    month_dir = ARCHIVE_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    
    safe_project = project.replace("/", "_").replace("\\", "_")[:20]
    archive_file = month_dir / f"{safe_project}-{memory_id}.txt"
    
    full_content = f"""# {project}
# 创建时间: {now.isoformat()}
# 记忆ID: {memory_id}
# 链接: {', '.join(links) if links else '无'}

{content}
"""
    
    with open(archive_file, "w", encoding="utf-8") as f:
        f.write(full_content)
    
    # 4. 用 3b 模型生成摘要
    summary = generate_summary(content, model=SUMMARY_MODEL)
    if not summary:
        summary = content[:50]  # fallback
    
    # 5. 写入向量库
    collection = get_chroma_collection()
    
    # 准备元数据
    metadata = {
        "memory_id": memory_id,
        "timestamp": now.isoformat(),
        "channel": "archive",
        "project": project,
        "archive_path": str(archive_file),
        "tags": ",".join(tags) if tags else "",
        "links": ",".join(links) if links else "",  # 新增
    }
    
    # 添加到向量库
    collection.upsert(
        ids=[memory_id],
        embeddings=[get_embedding(content)],
        documents=[content],
        metadatas=[metadata]
    )
    
    # 6. 更新链接索引
    if links:
        update_links_index(links, memory_id)
    
    # 7. 同步更新 memoria.json 索引（可选，便于统一检索）
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
        "links": links,  # 新增
    }
    index_data["memories"].insert(0, entry)
    
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    
    return {
        "id": memory_id,
        "archive_path": str(archive_file),
        "summary": summary,
        "links": links,
    }


def main():
    parser = argparse.ArgumentParser(description="Memoria — 记录重要内容到 archive")
    parser.add_argument("--project", required=True, help="项目/主题名称")
    parser.add_argument("--content", default="", help="手动内容（不传则自动抓取 session）")
    parser.add_argument("--tags", default="", help="标签，逗号分隔")
    parser.add_argument("--links", default="", help="手动传入链接，逗号分隔（与 [[链接]] 自动合并）")
    parser.add_argument("--auto", action="store_true", help="自动从当前 session 提取内容")
    parser.add_argument("--session-id", default="", help="指定 session ID（配合 --auto 使用）")
    
    args = parser.parse_args()
    
    # 自动模式
    if args.auto:
        print("🔄 正在从 session 提取内容...")
        auto_data = auto_extract_from_session(args.session_id if args.session_id else None)
        
        if "error" in auto_data:
            print(f"❌ {auto_data['error']}")
            sys.exit(1)
        
        # 构建内容
        content = f"""【对话摘要】
{auto_data['summary']}

【对话内容】
{auto_data['messages_text']}"""
        
        print(f"✅ 已提取对话")
        print(f"   Session: {auto_data['session_id']}")
        print(f"   摘要: {auto_data['summary']}")
        print(f"   标签: {', '.join(auto_data['tags'])}")
        print()
        
        # 使用自动提取的标签
        tags = auto_data['tags']
        manual_links = []
        
    else:
        # 手动模式
        if not args.content:
            print("❌ 请传入 --content 或使用 --auto")
            sys.exit(1)
        
        content = args.content
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        manual_links = [l.strip() for l in args.links.split(",") if l.strip()] if args.links else []
    
    result = archive_important_content(args.project, content, tags, manual_links if manual_links else None)
    
    print(f"✅ 已写入 archive 并向量化")
    print(f"   ID: {result['id']}")
    print(f"   项目: {args.project}")
    print(f"   摘要: {result['summary']}")
    print(f"   原文路径: {result['archive_path']}")
    if result.get('links'):
        print(f"   链接: {', '.join(result['links'])}")


if __name__ == "__main__":
    main()
