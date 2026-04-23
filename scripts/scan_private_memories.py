#!/usr/bin/env python3
"""
一次性扫描脚本：构建完整的 private/memoria.json 索引

背景：私密记忆系统原设计只有 links.json + .txt 文件，没有 memoria.json。
导致可视化大量 404（97/112 节点无内容）。
本脚本扫描所有私密 .txt 文件，构建完整的 private/memoria.json。

用法：
    python3 scan_private_memories.py          # 预演
    python3 scan_private_memories.py --execute  # 实际执行

输出：
    ~/.qclaw/memoria/private/memoria.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

MEMORIA_ROOT = Path.home() / ".qclaw" / "memoria"
PRIVATE_ROOT = MEMORIA_ROOT / "private"
PRIVATE_ARCHIVE_DIR = PRIVATE_ROOT / "memories" / "archive"
PRIV_MEMORIA_JSON_PATH = PRIVATE_ROOT / "memoria.json"
EXISTING_PRIV_MEM = PRIVATE_ROOT / "memoria.json"
# 扫描范围：private/memories/ 下所有 .txt（包含根目录 2026-04/ 和 archive/ 下各子目录）
PRIVATE_MEMORIES_ROOT = PRIVATE_ROOT / "memories"


def extract_uuid_from_filename(filename: str) -> Optional[str]:
    """从文件名中提取 UUID（文件名可能是 '标题-uuid.txt' 或纯 'uuid.txt'）"""
    match = UUID_RE.search(filename)
    return match.group() if match else None


def parse_front_matter(content: str) -> dict:
    """解析 front-matter，返回 {tags, links, created, source, content}"""
    lines = content.split('\n')
    result = {
        "tags": [],
        "links": [],
        "created": None,
        "source": "manual",
        "content": content
    }
    
    if not lines or lines[0].strip() != '---':
        return result
    
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if line == '---':
            i += 1
            # 剩余内容是正文
            result["content"] = '\n'.join(lines[i:]).strip()
            break
        
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            
            if key == 'tags' and value:
                # tags 行可能是逗号分隔的 JSON 数组字符串
                if value.startswith('['):
                    try:
                        result["tags"] = json.loads(value)
                    except:
                        result["tags"] = [t.strip() for t in value.strip('[]').split(',') if t.strip()]
                else:
                    result["tags"] = [v.strip() for v in value.split(',') if v.strip()]
            elif key == 'created':
                result["created"] = value
            elif key == 'source':
                result["source"] = value
            elif key == 'links' and value:
                result["links"] = [v.strip() for v in value.split(',') if v.strip()]
        
        i += 1
    
    return result


def extract_summary(content: str, max_chars: int = 150) -> str:
    """提取摘要（去掉 front-matter，取正文前 N 字符）"""
    # 去掉 front-matter
    lines = content.split('\n')
    body_lines = []
    in_fm = False
    for line in lines:
        if line.strip() == '---' and not in_fm:
            in_fm = True
            continue
        if line.strip() == '---' and in_fm:
            in_fm = False
            continue
        if not in_fm:
            body_lines.append(line)
    body = '\n'.join(body_lines).strip()
    if len(body) <= max_chars:
        return body
    return body[:max_chars].rsplit(' ', 1)[0] + '…'


def build_private_memoria_json(dry_run: bool = False) -> dict:
    """
    扫描私密 archive 目录，构建完整的 private/memoria.json
    
    Returns:
        扫描结果 dict
    """
    stats = {
        "total_files": 0,
        "parsed_ok": 0,
        "parse_failed": 0,
        "existing_merged": 0,
        "entries": 0
    }
    
    entries = {}
    
    # 1. 读取已有的 private/memoria.json（6条手动归档的，保留）
    existing = {}
    if EXISTING_PRIV_MEM.exists():
        try:
            existing = json.loads(EXISTING_PRIV_MEM.read_text(encoding='utf-8'))
            stats["existing_merged"] = len(existing)
            print(f"   已有 private/memoria.json: {len(existing)} 条")
        except Exception as e:
            print(f"   ⚠️ 读取已有索引失败: {e}", file=sys.stderr)
    
    # 2. 扫描 private/memories/ 下所有 .txt 文件（包含各子目录）
    if not PRIVATE_MEMORIES_ROOT.exists():
        print(f"   ⚠️ 私密 memories 目录不存在: {PRIVATE_MEMORIES_ROOT}")
        print(f"   → 已有 {stats['existing_merged']} 条，直接写入")
    else:
        # 扫描所有子目录（不只 archive，还包括 2026-04/ 等）
        for txt_file in PRIVATE_MEMORIES_ROOT.rglob("*.txt"):
            stats["total_files"] += 1
            
            # 提取 UUID
            filename = txt_file.name
            memory_id = extract_uuid_from_filename(filename)
            if not memory_id:
                print(f"   ⚠️ 无法从文件名提取 UUID: {txt_file}")
                stats["parse_failed"] += 1
                continue
            
            # 读取文件
            try:
                content = txt_file.read_text(encoding='utf-8')
            except Exception as e:
                print(f"   ⚠️ 读取失败: {txt_file} → {e}", file=sys.stderr)
                stats["parse_failed"] += 1
                continue
            
            # 解析 front-matter
            fm = parse_front_matter(content)
            
            # 构建 archive_path（相对于 PRIVATE_ROOT）
            # 文件在: private/memories/archive/YYYY-MM/xxx.txt
            # 存储为: memories/archive/YYYY-MM/xxx.txt
            rel_path = txt_file.relative_to(PRIVATE_ROOT)
            archive_path = str(rel_path)  # memories/archive/YYYY-MM/xxx.txt
            
            # 提取正文（去掉 front-matter）
            body = fm["content"]
            if not body.strip():
                body = content  # fallback：没找到 --- 时用原始内容
            
            # 构建摘要
            summary = extract_summary(body)
            
            # 优先用已有的完整条目（已有索引有 importance_score 等字段）
            if memory_id in existing:
                entry = existing[memory_id].copy()
                # 更新 archive_path（保持一致性）
                entry["archive_path"] = archive_path
                # 确保有 summary
                if not entry.get("summary"):
                    entry["summary"] = summary
            else:
                # 新条目
                entry = {
                    "id": memory_id,
                    "memory_id": memory_id,
                    "timestamp": fm.get("created") or datetime.now(timezone.utc).isoformat(),
                    "tags": fm.get("tags", []),
                    "links": fm.get("links", []) or fm.get("tags", []),
                    "summary": summary,
                    "source": fm.get("source", "manual"),
                    "archive_path": archive_path,
                    "session_id": "",
                    "storage_type": "hot",
                    "importance_score": 0.0,
                    "recall_count": 0,
                    "last_strengthened": None,
                    "last_recalled": None,
                }
            
            entries[memory_id] = entry
            stats["parsed_ok"] += 1
    
    stats["entries"] = len(entries)
    
    # 3. 写文件
    if dry_run:
        print(f"\n   [预演] 扫描结果:")
        print(f"   - 已有条目保留: {stats['existing_merged']} 条")
        print(f"   - 扫描文件: {stats['total_files']} 个")
        print(f"   - 解析成功: {stats['parsed_ok']} 条")
        print(f"   - 解析失败: {stats['parse_failed']} 条")
        print(f"   - 总条目: {stats['entries']} 条")
        return {"status": "dry_run", "stats": stats}
    
    # 写入
    PRIV_MEMORIA_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PRIV_MEMORIA_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    
    print(f"\n   ✅ 写入完成: {PRIV_MEMORIA_JSON_PATH}")
    print(f"   - 已有条目保留: {stats['existing_merged']} 条")
    print(f"   - 扫描新增: {stats['parsed_ok']} 条")
    print(f"   - 总条目: {stats['entries']} 条")
    if stats['parse_failed'] > 0:
        print(f"   - 解析失败: {stats['parse_failed']} 条（文件名无 UUID）")
    
    return {"status": "ok", "stats": stats, "path": str(PRIV_MEMORIA_JSON_PATH)}


def main():
    parser = argparse.ArgumentParser(description="构建私密记忆完整索引")
    parser.add_argument("--execute", action="store_true", help="实际执行（不加则为预演）")
    args = parser.parse_args()
    
    print("🌙 scan_private_memories.py")
    print(f"   私密 archive: {PRIVATE_ARCHIVE_DIR}")
    print(f"   输出索引: {PRIV_MEMORIA_JSON_PATH}")
    print()
    
    if not args.execute:
        print("⚠️  [预演模式] 加 --execute 才会写入")
        print()
    
    result = build_private_memoria_json(dry_run=not args.execute)
    
    if result["status"] == "ok":
        print(f"\n✅ 完成！私密可视化应该可以正常显示 {result['stats']['entries']} 条记忆了。")
    else:
        print(f"\n预演结束。确认无误后加 --execute 写入。")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
