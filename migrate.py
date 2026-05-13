#!/usr/bin/env python3
"""
从 Memoria v5 迁移到 v6

步骤:
1. 将现有 archive/*.txt 复制到 store/*.md（保持内容不变）
2. 从文件内容构建 SQLite 索引
3. 重建向量索引

用法:
    python3 migrate.py              # 预览
    python3 migrate.py --execute    # 执行迁移
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memoria.config import MEMORIA_ROOT, STORE_DIR, DB_PATH
from memoria.db import init_db, get_conn
from memoria.vector import upsert_vector
from memoria.filestore import extract_links

OLD_ARCHIVE_DIR = MEMORIA_ROOT / "archive"
OLD_PRIVATE_DIR = MEMORIA_ROOT / "private" / "memories"

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def parse_old_file(filepath: Path) -> dict:
    """解析旧版 archive TXT 文件"""
    text = filepath.read_text(encoding="utf-8")

    # 新格式: YAML front matter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = {}
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    if value.startswith("["):
                        try:
                            meta[key] = json.loads(value)
                        except:
                            meta[key] = []
                    elif value in ("true", "false"):
                        meta[key] = value == "true"
                    else:
                        meta[key] = value
            meta["content"] = parts[2].strip()
            return meta

    # 旧格式: # 标题 + key: value 头 + --- + 正文
    if text.startswith("#"):
        meta = {"source": "migrated"}
        lines = text.split("\n")
        content_start = 0
        header_done = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 第一行标题
            if i == 0 and stripped.startswith("#"):
                meta["title"] = stripped.lstrip("#").strip()
                continue

            # 空行跳过
            if not stripped:
                continue

            # --- 分隔符标记 header 结束
            if stripped == "---":
                header_done = True
                content_start = i + 1
                break

            # key: value 行（header 区域）
            if not header_done and ":" in stripped and not stripped.startswith("#"):
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                if key == "memory_id":
                    meta["memory_id"] = value
                elif key == "created":
                    meta["created"] = value
                elif key == "source":
                    meta["source"] = value
                elif key in ("tags", "links"):
                    meta[key] = [v.strip() for v in value.split(",") if v.strip()]
                elif key == "session_id":
                    meta["session_id"] = value
                continue

            # 旧旧格式：# 创建时间: xxx
            if stripped.startswith("# "):
                comment = stripped[2:]
                if comment.startswith("创建时间:"):
                    meta["created"] = comment.replace("创建时间:", "").strip()
                elif comment.startswith("记忆ID:"):
                    meta["memory_id"] = comment.replace("记忆ID:", "").strip()
                elif comment.startswith("链接:"):
                    links_str = comment.replace("链接:", "").strip()
                    meta["tags"] = [l.strip() for l in links_str.split(",") if l.strip()]
                continue

            # 如果到这里还没遇到 ---，说明没有分隔符，剩余全是 content
            content_start = i
            break

        meta["content"] = "\n".join(lines[content_start:]).strip()
        return meta

    return {"content": text}


def scan_files(base_dir: Path, private: bool = False) -> list[dict]:
    """扫描目录下所有 txt 文件"""
    results = []
    if not base_dir.exists():
        return results

    for month_dir in sorted(base_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        if month_dir.name in ("dormant", ".DS_Store", "chroma_db"):
            continue
        for f in sorted(month_dir.glob("*.txt")):
            meta = parse_old_file(f)
            # 提取 memory_id
            mid = meta.get("memory_id") or meta.get("id")
            if not mid:
                match = UUID_RE.search(f.stem)
                mid = match.group() if match else f.stem

            results.append({
                "id": mid,
                "source_path": f,
                "month": month_dir.name,
                "private": private,
                "meta": meta,
            })
    return results


def migrate(execute: bool = False):
    print("=== Memoria v5 → v6 迁移 ===\n")

    # 扫描
    public_files = scan_files(OLD_ARCHIVE_DIR, private=False)
    private_files = scan_files(OLD_PRIVATE_DIR, private=True)
    all_files = public_files + private_files

    print(f"发现文件: {len(public_files)} 公开 + {len(private_files)} 私密 = {len(all_files)} 总计")

    if not execute:
        print("\n[预览模式] 添加 --execute 执行迁移")
        print(f"\n前 5 条:")
        for item in all_files[:5]:
            meta = item["meta"]
            summary = meta.get("content", "")[:60].replace("\n", " ")
            print(f"  {item['id'][:8]}... | {item['month']} | {summary}")
        return {"total": len(all_files), "executed": False}

    # 执行迁移
    print("\n开始迁移...")

    # 1. 复制文件到 store/
    copied = 0
    for item in all_files:
        mid = item["id"]
        month = item["month"]
        private = item["private"]

        if private:
            dest_dir = STORE_DIR / "private" / month
        else:
            dest_dir = STORE_DIR / month

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{mid}.md"

        if not dest_file.exists():
            shutil.copy2(item["source_path"], dest_file)
            copied += 1

    print(f"  文件复制: {copied} 个")

    # 2. 构建 SQLite
    init_db()
    indexed = 0
    errors = 0

    for item in all_files:
        try:
            mid = item["id"]
            meta = item["meta"]
            private = item["private"]
            month = item["month"]

            content = meta.get("content", "")
            summary = content[:200].replace("\n", " ").strip() if content else ""
            tags = meta.get("tags", [])
            links = meta.get("links", []) or extract_links(content)
            source = meta.get("source", "migrated")
            created = meta.get("created", meta.get("created_at", f"{month}-01T00:00:00+00:00"))

            file_path = f"private/{month}/{mid}.md" if private else f"{month}/{mid}.md"

            with get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO memories
                       (id, summary, content, source, created_at, importance,
                        private, archived, file_path)
                       VALUES (?, ?, ?, ?, ?, 0.0, ?, 0, ?)""",
                    (mid, summary, content, source, created, int(private), file_path),
                )
                for tag in tags:
                    t = tag.lower() if isinstance(tag, str) else str(tag)
                    conn.execute(
                        "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'tag')",
                        (mid, t),
                    )
                for link in links:
                    conn.execute(
                        "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'link')",
                        (mid, link),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO memories_fts (id, summary, content) VALUES (?, ?, ?)",
                    (mid, summary, content),
                )

            # 向量
            embed_text = f"{summary}\n{content}"
            upsert_vector(mid, embed_text, private=private)
            indexed += 1

            if indexed % 50 == 0:
                print(f"  进度: {indexed}/{len(all_files)}")

        except Exception as e:
            errors += 1
            print(f"  ERROR [{item['id'][:8]}]: {e}")

    print(f"\n=== 迁移完成 ===")
    print(f"  索引: {indexed} 条")
    print(f"  错误: {errors} 条")
    print(f"  数据库: {DB_PATH}")

    return {"total": len(all_files), "indexed": indexed, "errors": errors, "executed": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memoria v5 → v6 迁移")
    parser.add_argument("--execute", action="store_true", help="执行迁移（默认预览）")
    args = parser.parse_args()
    migrate(execute=args.execute)
