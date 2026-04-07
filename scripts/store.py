#!/usr/bin/env python3
"""
Memoria 统一写入入口 store()

用法:
    python3 store.py --content "..." --tags "tag1,tag2" --source manual
    python3 store.py --content "..." --tags "tag1" --source proactive --session-id "xxx"

返回:
    {
        "memory_id": "uuid",
        "archive_path": "archive/2026-04/xxx.txt",
        "status": {
            "archive": "ok",
            "vector": "ok",
            "hot_cache": "ok",
            "links": "ok"
        }
    }
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.config import LOGS_DIR
from lib.utils import (
    generate_memory_id,
    get_utc_timestamp,
    extract_links,
    merge_tags_and_links,
    extract_summary
)
from lib.archive import write_archive_txt, append_to_archive
from lib.vector import write_vector, delete_vector
from lib.hot_cache import add_to_hot_cache, get_by_session_id, update_hot_cache_entry
from lib.links import update_links_index


def log_store_result(
    memory_id: str,
    source: str,
    status: dict,
    duration_ms: int
):
    """记录 store 日志"""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        
        log_entry = {
            "timestamp": get_utc_timestamp(),
            "memory_id": memory_id,
            "source": source,
            "status": status,
            "duration_ms": duration_ms
        }
        
        # 按日轮转
        from datetime import datetime, timezone
        dt = datetime.now(timezone.utc)
        log_file = LOGS_DIR / f"store-{dt.year}-{dt.month:02d}-{dt.day:02d}.log"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"ERROR: log write failed: {e}", file=sys.stderr)


def store(
    content: str,
    pre_tags: list[str] = None,
    source: str = "manual",
    session_id: str = None
) -> dict:
    """
    统一写入入口
    
    Args:
        content: 正文内容（按 TXT 模板格式）
        pre_tags: 预置标签
        source: manual | proactive
        session_id: 可选，关联的 session
    
    Returns:
        {
            "memory_id": "uuid",
            "archive_path": "archive/.../xxx.txt",
            "status": {...},
            "mode": "new" | "update"
        }
    """
    start_time = time.time()
    
    # 检查是否需要增量更新
    existing_memory = None
    mode = "new"
    
    if session_id:
        existing_memory = get_by_session_id(session_id)
        if existing_memory:
            mode = "update"
            memory_id = existing_memory["memory_id"]
    
    # 如果没有已有记忆，生成新 memory_id
    if not existing_memory:
        memory_id = generate_memory_id()
    
    # 提取 links
    extracted_links = extract_links(content)
    
    # 合并 tags 和 links
    tags, links = merge_tags_and_links(pre_tags, extracted_links)
    
    # 提取摘要
    summary = extract_summary(content)
    
    # 初始化状态
    status = {
        "archive": "ok",
        "vector": "ok",
        "hot_cache": "ok",
        "links": "ok"
    }
    
    if mode == "update":
        # 增量更新模式
        try:
            # Step 1: 追加到 archive TXT
            if not append_to_archive(memory_id, content):
                status["archive"] = "failed: append failed"
            
            # Step 2: 重新写入向量库（删除旧向量，重新写入）
            # 获取 archive_path
            archive_path = existing_memory.get("archive_path", "")
            if archive_path:
                # 删除旧向量
                delete_vector(memory_id)
                # 重新写入（用合并后的内容）
                # 读取完整内容
                from lib.archive import read_archive_txt
                full_record = read_archive_txt(archive_path)
                full_content = full_record.get("content", "") if full_record else ""
                merged_content = full_content + "\n\n---\n\n" + content
                
                if not write_vector(
                    memory_id=memory_id,
                    archive_path=archive_path,
                    content=merged_content,
                    tags=tags,
                    links=links,
                    source=source,
                    session_id=session_id
                ):
                    status["vector"] = "failed"
            
            # Step 3: 更新热缓存
            if not update_hot_cache_entry(memory_id, content, tags, links):
                status["hot_cache"] = "failed: update failed"
            
            # Step 4: 更新 links（追加新 links）
            # 读取现有 links，合并
            from lib.links import read_links_index
            existing_links = read_links_index()
            current_links = existing_links.get(memory_id, [])
            # 合并去重
            merged_links = list(set(current_links + links))
            if not update_links_index(links=merged_links, memory_id=memory_id):
                status["links"] = "failed"
                
        except Exception as e:
            status["archive"] = f"failed: {e}"
            duration_ms = int((time.time() - start_time) * 1000)
            log_store_result(memory_id, source, status, duration_ms)
            return {
                "memory_id": memory_id,
                "archive_path": existing_memory.get("archive_path") if existing_memory else None,
                "status": status,
                "mode": mode
            }
    else:
        # 新建模式（原有逻辑）
        # Step 1: 写 archive TXT
        try:
            archive_path, title = write_archive_txt(
                memory_id=memory_id,
                content=content,
                tags=tags,
                links=links,
                source=source,
                session_id=session_id
            )
        except Exception as e:
            status["archive"] = f"failed: {e}"
            # archive 失败是核心失败，直接返回
            duration_ms = int((time.time() - start_time) * 1000)
            log_store_result(memory_id, source, status, duration_ms)
            return {
                "memory_id": memory_id,
                "archive_path": None,
                "status": status,
                "mode": mode
            }
        
        # Step 2: 写向量库
        if not write_vector(
            memory_id=memory_id,
            archive_path=archive_path,
            content=content,
            tags=tags,
            links=links,
            source=source,
            session_id=session_id
        ):
            status["vector"] = "failed"
        
        # Step 3: 写热缓存
        if not add_to_hot_cache(
            memory_id=memory_id,
            archive_path=archive_path,
            summary=summary,
            tags=tags,
            links=links,
            source=source,
            session_id=session_id
        ):
            status["hot_cache"] = "failed"
        
        # Step 4: 写 links 索引
        if not update_links_index(links=links, memory_id=memory_id):
            status["links"] = "failed"
    
    # 计算耗时
    duration_ms = int((time.time() - start_time) * 1000)
    
    # 记录日志
    log_store_result(memory_id, source, status, duration_ms)
    
    archive_path = existing_memory.get("archive_path") if mode == "update" else archive_path if mode == "new" else None
    
    return {
        "memory_id": memory_id,
        "archive_path": archive_path,
        "status": status,
        "mode": mode
    }


def main():
    parser = argparse.ArgumentParser(description="Memoria 统一写入入口")
    parser.add_argument("--content", required=True, help="正文内容")
    parser.add_argument("--tags", default="", help="预置标签，逗号分隔")
    parser.add_argument("--source", default="manual", choices=["manual", "proactive"], help="触发来源")
    parser.add_argument("--session-id", default=None, help="关联的 session ID")
    
    args = parser.parse_args()
    
    # 解析 tags
    pre_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    
    # 调用 store
    result = store(
        content=args.content,
        pre_tags=pre_tags,
        source=args.source,
        session_id=args.session_id
    )
    
    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
