#!/usr/bin/env python3
"""
Memoria 统一写入入口 store()

用法:
    python3 store.py --content "..." --tags "tag1,tag2" --source manual
    python3 store.py --content "..." --tags "tag1" --source proactive --session-id "xxx"
    python3 store.py --content "..." --private  # 写入私密区

返回:
    {
        "memory_id": "uuid",
        "archive_path": "archive/2026-04/xxx.txt",
        "status": {
            "archive": "ok",
            "vector": "ok",
            "hot_cache": "ok",  # 私密区为 "skipped"
            "links": "ok"
        },
        "private": false
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
from lib.archive import write_archive_txt, append_to_archive, read_archive_txt
from lib.vector import write_vector, delete_vector, search_vector
from lib.hot_cache import add_to_hot_cache, get_by_session_id, update_hot_cache_entry, init_importance_fields
from lib.links import update_links_index, read_links_index


def log_store_result(
    memory_id: str,
    source: str,
    status: dict,
    duration_ms: int,
    private: bool = False
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
            "private": private
        }
        
        # 按日轮转
        from datetime import datetime, timezone
        dt = datetime.now(timezone.utc)
        log_file = LOGS_DIR / f"store-{dt.year}-{dt.month:02d}-{dt.day:02d}.log"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"ERROR: log write failed: {e}", file=sys.stderr)


def _rebuild_graph_async(private: bool = False):
    """后台静默重建 graph.json，不阻塞主流程"""
    import subprocess, threading, os as _os
    base = _os.path.dirname(_os.path.abspath(__file__))
    build = _os.path.join(base, 'build_graph.py')
    out = _os.path.join(base, '..', '..', 'memoria', ('graph.json' if not private else _os.path.join('private', 'graph.json')))
    inp = _os.path.join(base, '..', '..', 'memoria', ('links.json' if not private else _os.path.join('private', 'links.json')))
    # 不等待结果，静默执行
    def run():
        try:
            subprocess.run(['python3', build, '-i', inp, '-o', out],
                          capture_output=True, timeout=30)
        except Exception:
            pass
    t = threading.Thread(target=run, daemon=True)
    t.start()


# 去重配置
DEDUP_WINDOW_HOURS = 1
DEDUP_SIMILARITY_THRESHOLD = 0.8


def _find_duplicate(content: str, source: str, private: bool = False) -> dict:
    """
    查找近期相似记忆（短期窗口去重）
    
    返回:
        相似记忆的 dict，或 None
    """
    try:
        from datetime import datetime, timezone, timedelta
        
        # 向量搜索找相似内容
        results = search_vector(content, limit=5, private=private)
        if not results:
            return None
        
        now = datetime.now(timezone.utc)
        window = timedelta(hours=DEDUP_WINDOW_HOURS)
        
        for result in results:
            # 检查相似度
            score = result.get("score", 0)
            if score < DEDUP_SIMILARITY_THRESHOLD:
                continue
            
            # 检查 source 是否匹配
            metadata = result.get("metadata", {})
            if metadata.get("source") != source:
                continue
            
            # 检查时间是否在窗口内
            timestamp = metadata.get("timestamp", "")
            if timestamp:
                try:
                    ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if now - ts <= window:
                        return result
                except:
                    pass
        
        return None
    except Exception as e:
        print(f"WARN: dedup check failed: {e}", file=sys.stderr)
        return None


def store(
    content: str,
    pre_tags: list[str] = None,
    source: str = "manual",
    session_id: str = None,
    private: bool = False
) -> dict:
    """
    统一写入入口
    
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
            "status": {...},
            "mode": "new" | "update",
            "private": bool
        }
    """
    start_time = time.time()
    
    # 检查是否需要增量更新（私密区不走增量更新）
    existing_memory = None
    mode = "new"
    
    if session_id and not private:
        existing_memory = get_by_session_id(session_id)
        if existing_memory:
            mode = "update"
            memory_id = existing_memory["memory_id"]
    
    # 如果没有已有记忆，生成新 memory_id
    if not existing_memory:
        # 检查短期窗口去重（仅日常区）
        if not private:
            duplicate = _find_duplicate(content, source, private=private)
            if duplicate:
                # 找到重复，转为更新模式
                existing_memory = {
                    "memory_id": duplicate["memory_id"],
                    "archive_path": duplicate["metadata"].get("archive_path", "")
                }
                mode = "update"
                memory_id = duplicate["memory_id"]
        
        if mode == "new":
            memory_id = generate_memory_id()
    
    # 提取 links
    extracted_links = extract_links(content)
    
    # 合并 tags 和 links
    tags, links = merge_tags_and_links(pre_tags, extracted_links)
    
    # 标签统一转小写
    tags = [t.lower() for t in tags]
    
    # 提取摘要
    summary = extract_summary(content)
    
    # 初始化状态
    status = {
        "archive": "ok",
        "vector": "ok",
        "hot_cache": "pending",
        "links": "ok"
    }
    
    if mode == "update":
        # 增量更新模式（仅日常区）
        try:
            # Step 1: 追加到 archive TXT
            if not append_to_archive(memory_id, content, private=private):
                status["archive"] = "failed: append failed"
            
            # Step 2: 重新写入向量库（删除旧向量，重新写入）
            archive_path = existing_memory.get("archive_path", "")
            if archive_path:
                delete_vector(memory_id, private=private)
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
                    session_id=session_id,
                    private=private
                ):
                    status["vector"] = "failed"
            
            # Step 3: 更新热缓存
            if update_hot_cache_entry(memory_id, content, tags, links, private=private):
                status["hot_cache"] = "ok"
            else:
                status["hot_cache"] = "failed: update failed"
            
            # Step 4: 更新 links（追加新 links）
            existing_links = read_links_index(private=private)
            current_links = existing_links.get(memory_id, [])
            merged_links = list(set(current_links + links))
            if not update_links_index(links=merged_links, memory_id=memory_id, private=private):
                status["links"] = "failed"
                
        except Exception as e:
            status["archive"] = f"failed: {e}"
            duration_ms = int((time.time() - start_time) * 1000)
            log_store_result(memory_id, source, status, duration_ms, private=private)
            return {
                "memory_id": memory_id,
                "archive_path": existing_memory.get("archive_path") if existing_memory else None,
                "status": status,
                "mode": mode,
                "private": private
            }
    else:
        # 新建模式
        try:
            # Step 1: 写 archive TXT
            archive_path, title = write_archive_txt(
                memory_id=memory_id,
                content=content,
                tags=tags,
                links=links,
                source=source,
                session_id=session_id,
                private=private
            )
        except Exception as e:
            status["archive"] = f"failed: {e}"
            duration_ms = int((time.time() - start_time) * 1000)
            log_store_result(memory_id, source, status, duration_ms, private=private)
            return {
                "memory_id": memory_id,
                "archive_path": None,
                "status": status,
                "mode": mode,
                "private": private
            }
        
        # Step 2: 写向量库
        if not write_vector(
            memory_id=memory_id,
            archive_path=archive_path,
            content=content,
            tags=tags,
            links=links,
            source=source,
            session_id=session_id,
            private=private
        ):
            status["vector"] = "failed"
        
        # Step 3: 写热缓存（私密区同样写入 private/memoria.json）
        imp_fields = init_importance_fields(memory_id, tags)
        if add_to_hot_cache(
            memory_id=memory_id,
            archive_path=archive_path,
            summary=summary,
            tags=tags,
            links=links,
            source=source,
            session_id=session_id,
            importance_fields=imp_fields,
            private=private
        ):
            status["hot_cache"] = "ok"
        else:
            status["hot_cache"] = "failed"
        
        # Step 4: 写 links 索引（tags 也加入索引）
        all_links = list(set(links + tags))
        if not update_links_index(links=all_links, memory_id=memory_id, private=private):
            status["links"] = "failed"
    
    # 计算耗时
    duration_ms = int((time.time() - start_time) * 1000)
    
    # 记录日志
    log_store_result(memory_id, source, status, duration_ms, private=private)
    
    # 重建图谱数据（后台静默执行，不阻塞返回）

    
    final_archive_path = (
        existing_memory.get("archive_path") if mode == "update" 
        else archive_path if mode == "new" 
        else None
    )
    
    return {
        "memory_id": memory_id,
        "archive_path": final_archive_path,
        "status": status,
        "mode": mode,
        "private": private
    }


def main():
    parser = argparse.ArgumentParser(description="Memoria 统一写入入口")
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
