"""维护任务 - 重建索引 / 沉睡降权 / 合并候选"""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from .config import STORE_DIR, DORMANT_DAYS
from .db import get_conn, init_db
from .vector import upsert_vector, search_vectors, delete_vector
from .filestore import list_all_files, parse_memory_file, extract_links


def rebuild() -> dict:
    """从 store/*.md 重建 SQLite + 向量索引"""
    init_db()

    # 清空现有数据
    with get_conn() as conn:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM labels")
        conn.execute("DELETE FROM memories_fts")

    imported = 0
    errors = 0

    for private in [False, True]:
        files = list_all_files(private=private)
        for filepath in files:
            try:
                text = filepath.read_text(encoding="utf-8")
                meta = parse_memory_file(text)
                if not meta:
                    errors += 1
                    continue

                mid = meta.get("id") or meta.get("memory_id") or filepath.stem
                content = meta.get("content", "")
                summary = content[:200] if content else ""
                tags = meta.get("tags", [])
                links = meta.get("links", []) or extract_links(content)
                source = meta.get("source", "migrated")
                created = meta.get("created", meta.get("created_at", ""))

                # 计算相对路径
                if private:
                    rel = filepath.relative_to(STORE_DIR / "private")
                    file_path = f"private/{rel}"
                else:
                    rel = filepath.relative_to(STORE_DIR)
                    file_path = str(rel)

                with get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO memories
                           (id, summary, content, source, created_at, importance,
                            private, archived, file_path)
                           VALUES (?, ?, ?, ?, ?, 0.0, ?, 0, ?)""",
                        (mid, summary, content, source, created, int(private), file_path),
                    )
                    for tag in tags:
                        conn.execute(
                            "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'tag')",
                            (mid, tag.lower() if isinstance(tag, str) else str(tag)),
                        )
                    for link in links:
                        conn.execute(
                            "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'link')",
                            (mid, link),
                        )
                    conn.execute(
                        "INSERT INTO memories_fts (id, summary, content) VALUES (?, ?, ?)",
                        (mid, summary, content),
                    )

                # 向量
                embed_text = f"{summary}\n{content}"
                upsert_vector(mid, embed_text, private=private)
                imported += 1

            except Exception as e:
                errors += 1
                print(f"  ERROR: {filepath.name}: {e}")

    return {"imported": imported, "errors": errors}


def suggest_merge(limit: int = 10) -> list[dict]:
    """基于向量相似度找出可能可以合并的记忆候选"""
    init_db()
    candidates = []

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, summary, content FROM memories
               WHERE archived = 0 ORDER BY created_at DESC LIMIT 100"""
        ).fetchall()

    seen_pairs = set()
    for row in rows:
        similar = search_vectors(row["summary"], limit=5, private=False)
        for s in similar:
            if s["id"] == row["id"]:
                continue
            if s["score"] < 0.85:
                continue
            pair = tuple(sorted([row["id"], s["id"]]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            candidates.append({
                "ids": list(pair),
                "score": s["score"],
                "summaries": [row["summary"][:80]],
            })
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    return candidates


def dormant_sweep(dry_run: bool = True) -> dict:
    """将长期未召回的记忆标记为 archived"""
    init_db()
    threshold = (datetime.now(timezone.utc) - timedelta(days=DORMANT_DAYS)).isoformat()

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, summary, last_recalled_at, created_at FROM memories
               WHERE archived = 0
               AND (last_recalled_at IS NOT NULL AND last_recalled_at < ?)
               OR  (last_recalled_at IS NULL AND created_at < ?)""",
            (threshold, threshold),
        ).fetchall()

        demoted = []
        for row in rows:
            demoted.append({"id": row["id"], "summary": row["summary"][:60]})
            if not dry_run:
                conn.execute(
                    "UPDATE memories SET archived = 1, updated_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), row["id"]),
                )
                delete_vector(row["id"])

    return {"dry_run": dry_run, "count": len(demoted), "samples": demoted[:10]}
