#!/usr/bin/env python3
"""
Memoria Lite 重建索引工具 rebuild()

用法:
    python3 rebuild.py              # 增量重建（只补缺失的）
    python3 rebuild.py --force      # 强制重建（清空后重建）

功能:
    扫描 archive/ 目录下所有 TXT 文件 → 重建两个可恢复的存储：
    - memoria.json（热缓存）
    - links.json（链接索引）

注意:
    - archive TXT 是唯一真实来源
    - 增量模式是幂等的，可以反复执行
    - 不删除 archive 中的任何文件
    - 不涉及向量库（Lite 版本不使用）
"""

import argparse
import json
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib.config import HOT_CACHE_PATH, LINKS_PATH, ensure_directories
from lib.archive import list_archive_txts, read_archive_txt
from lib.hot_cache import read_hot_cache, write_hot_cache
from lib.links import read_links_index, write_links_index


def extract_summary_from_content(content: str) -> str:
    """从 content 中提取摘要"""
    lines = content.strip().split('\n')
    
    for i, line in enumerate(lines):
        if line.strip() == '## 摘要':
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    
    # 没找到摘要区块，取第一行非空内容
    for line in lines:
        if line.strip() and not line.startswith('#'):
            return line.strip()[:100]
    
    return "无摘要"


def rebuild(force: bool = False) -> dict:
    """
    重建索引
    
    Args:
        force: 是否强制清空后重建
    
    Returns:
        {
            "total": 总条数,
            "added": 新增条数,
            "skipped": 跳过条数（已存在）,
            "failed": 失败条数,
            "errors": [错误信息]
        }
    """
    print("Memoria Lite 重建索引")
    print("=" * 50)
    
    # 确保目录存在
    ensure_directories()
    
    # Step 1: 初始化或读取现有数据
    if force:
        print("\n[1/3] 强制模式：清空旧数据...")
        hot_cache_data = {"memories": []}
        links_index = {}
    else:
        print("\n[1/3] 检查已有数据...")
        hot_cache_data = read_hot_cache()
        if not hot_cache_data:
            hot_cache_data = {"memories": []}
        links_index = read_links_index()
        if not links_index:
            links_index = {}
        existing_count = len(hot_cache_data.get("memories", []))
        print(f"  热缓存已有 {existing_count} 条")
    
    # Step 2: 扫描 archive TXT
    print("\n[2/3] 扫描 archive TXT...")
    archive_paths = list_archive_txts()
    print(f"  发现 {len(archive_paths)} 条记忆")
    
    if not archive_paths:
        print("\n无需重建")
        return {
            "total": 0,
            "added": 0,
            "skipped": 0,
            "failed": 0,
            "errors": []
        }
    
    # 热缓存中的 memory_id 集合（用于快速查找）
    hot_cache_ids = {m.get("memory_id") for m in hot_cache_data.get("memories", [])}
    
    # Step 3: 重建索引
    print("\n[3/3] 重建索引...")
    
    errors = []
    added_count = 0
    skipped_count = 0
    failed_count = 0
    
    for archive_path in archive_paths:
        try:
            # 读取 archive TXT
            data = read_archive_txt(archive_path)
            
            if not data:
                errors.append(f"{archive_path}: 读取失败")
                failed_count += 1
                continue
            
            memory_id = data.get("memory_id")
            if not memory_id:
                errors.append(f"{archive_path}: 缺少 memory_id")
                failed_count += 1
                continue
            
            # 增量模式：跳过已存在的
            if not force and memory_id in hot_cache_ids:
                skipped_count += 1
                continue
            
            # 提取字段
            content = data.get("content", "")
            tags = data.get("tags", [])
            links = data.get("links", [])
            source = data.get("source", "manual")
            timestamp = data.get("created", "")
            session_id = data.get("session_id", "")
            
            # 提取摘要
            summary = extract_summary_from_content(content)
            
            # 添加到热缓存
            hot_cache_data["memories"].append({
                "id": memory_id,
                "timestamp": timestamp,
                "tags": tags,
                "links": links,
                "summary": summary,
                "source": source,
                "memory_id": memory_id,
                "archive_path": archive_path,
                "session_id": session_id,
                "storage_type": "hot"
            })
            hot_cache_ids.add(memory_id)
            
            # 更新 links 索引
            for link in links:
                if link not in links_index:
                    links_index[link] = []
                if memory_id not in links_index[link]:
                    links_index[link].append(memory_id)
            
            added_count += 1
            
            if added_count % 10 == 0:
                print(f"  进度: {added_count}/{len(archive_paths)}")
            
        except Exception as e:
            errors.append(f"{archive_path}: {e}")
            failed_count += 1
    
    # 写入热缓存和 links 索引
    print("\n  写入热缓存和 links 索引...")
    
    # 按时间排序热缓存（最新的在前）
    hot_cache_data["memories"].sort(
        key=lambda x: x.get("timestamp", ""),
        reverse=True
    )
    
    write_hot_cache(hot_cache_data)
    write_links_index(links_index)
    
    # 输出结果
    print("\n" + "=" * 50)
    if force:
        print(f"强制重建完成: 成功 {added_count} 条，失败 {failed_count} 条")
    else:
        print(f"增量重建完成: 新增 {added_count} 条，跳过 {skipped_count} 条（已存在），失败 {failed_count} 条")
    
    if errors:
        print("\n错误列表:")
        for err in errors[:10]:  # 最多显示 10 条
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... 还有 {len(errors) - 10} 条错误")
    
    return {
        "total": len(archive_paths),
        "added": added_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "errors": errors
    }


def main():
    parser = argparse.ArgumentParser(description="Memoria Lite 重建索引")
    parser.add_argument("--force", action="store_true", help="强制清空后重建")
    
    args = parser.parse_args()
    
    result = rebuild(force=args.force)
    
    # 输出 JSON 结果
    print("\n" + "=" * 50)
    print("JSON 结果:")
    print(json.dumps({
        "total": result["total"],
        "added": result["added"],
        "skipped": result["skipped"],
        "failed": result["failed"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
