#!/usr/bin/env python3
"""
Memoria Lite 统一写入入口 store()

三步写入（去掉向量层）：
    Step 1: 写入 Archive TXT
    Step 2: 更新热缓存（私密区跳过）
    Step 3: 更新 links 索引

支持私密区：--private 参数
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.config import LOGS_DIR, ensure_directories, ensure_private_directories
from lib.utils import (
    generate_memory_id,
    get_utc_timestamp,
    extract_links,
    extract_summary
)
from lib.archive import write_archive_txt
from lib.hot_cache import add_to_hot_cache
from lib.links import update_links_index


def log_store_result(
    memory_id: str,
    source: str,
    status: dict,
    duration_ms: int,
    private_zone: bool = False
):
    """记录 store 日志"""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        
        log_entry = {
            "timestamp": get_utc_timestamp(),
            "memory_id": memory_id,
            "source": source,
            "status": status,
            "duration_ms": duration_ms,
            "private_zone": private_zone
        }
        
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
    session_id: str = None,
    private: bool = False
) -> dict:
    """
    统一写入入口（三步，不含向量）
    
    Args:
        content: 正文内容（按 TXT 模板格式）
        pre_tags: 预置标签
        source: manual | proactive
        session_id: 可选，关联的 session
        private: 是否写入私密区
    
    Returns:
        {
            "memory_id": "uuid",
            "archive_path": "archive/.../xxx.txt",
            "tags": [...],
            "links": [...],
            "status": {
                "archive": "ok",
                "hot_cache": "ok" | "skipped",
                "links": "ok"
            }
        }
    """
    start_time = time.time()
    
    # 确保目录存在
    if private:
        ensure_private_directories()
    else:
        ensure_directories()
    
    # 生成 memory_id
    memory_id = generate_memory_id()
    
    # 提取 links（从内容中提取 [[xxx]]）
    extracted_links = extract_links(content)
    
    # 合并 tags 和 links（tags 也加入 links 索引）
    tags = pre_tags or []
    links = list(set(extracted_links + tags))
    
    # 提取摘要
    summary = extract_summary(content)
    
    # 初始化状态
    status = {
        "archive": "ok",
        "hot_cache": "skipped" if private else "ok",
        "links": "ok"
    }
    
    # Step 1: 写 archive TXT
    try:
        archive_path, title = write_archive_txt(
            memory_id=memory_id,
            content=content,
            tags=tags,
            links=links,
            source=source,
            session_id=session_id,
            private_zone=private
        )
    except Exception as e:
        status["archive"] = f"failed: {e}"
        duration_ms = int((time.time() - start_time) * 1000)
        log_store_result(memory_id, source, status, duration_ms, private)
        return {
            "memory_id": memory_id,
            "archive_path": None,
            "tags": tags,
            "links": links,
            "status": status
        }
    
    # Step 2: 写热缓存（私密区跳过）
    if not private:
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
    
    # Step 3: 写 links 索引
    if not update_links_index(links=links, memory_id=memory_id, private_zone=private):
        status["links"] = "failed"
    
    # 计算耗时
    duration_ms = int((time.time() - start_time) * 1000)
    
    # 记录日志
    log_store_result(memory_id, source, status, duration_ms, private)
    
    return {
        "memory_id": memory_id,
        "archive_path": archive_path,
        "tags": tags,
        "links": links,
        "status": status
    }


def main():
    parser = argparse.ArgumentParser(description="Memoria Lite 统一写入入口")
    parser.add_argument("--content", required=True, help="正文内容")
    parser.add_argument("--tags", default="", help="预置标签，逗号分隔")
    parser.add_argument("--source", default="manual", choices=["manual", "proactive"], help="触发来源")
    parser.add_argument("--session-id", default=None, help="关联的 session ID")
    parser.add_argument("--private", action="store_true", help="写入私密区")
    
    args = parser.parse_args()
    
    # 解析 tags
    pre_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    
    # 调用 store
    result = store(
        content=args.content,
        pre_tags=pre_tags,
        source=args.source,
        session_id=args.session_id,
        private=args.private
    )
    
    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
