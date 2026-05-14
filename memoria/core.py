"""核心业务逻辑 - store / recall / manage 统一入口"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import STORE_DIR
from .db import get_conn, init_db
from .vector import upsert_vector, search_vectors, delete_vector
from .filestore import write_file, extract_links


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_summary(content: str) -> str:
    """从内容提取摘要：优先 ## 摘要 段落，否则取首行"""
    lines = content.strip().split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "## 摘要" and i + 1 < len(lines):
            return lines[i + 1].strip()[:200]
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
    return content[:200]


# ═══════════════════════════════════════════════════════════
# STORE
# ═══════════════════════════════════════════════════════════


def store(
    content: str,
    tags: Optional[list[str]] = None,
    source: str = "manual",
    private: bool = False,
    memory_id: Optional[str] = None,
    merge_from: Optional[list[str]] = None,
) -> dict:
    """
    写入一条记忆。

    Returns: {"id": str, "file_path": str, "status": "ok"|"partial"}
    """
    init_db()

    mid = memory_id or str(uuid.uuid4())
    tags = [t.lower().strip() for t in (tags or [])]
    links = [l.lower().strip() for l in extract_links(content)]
    summary = _extract_summary(content)
    now = _now()

    # 1. 写文件
    file_path = write_file(
        memory_id=mid,
        content=content,
        summary=summary,
        tags=tags,
        links=links,
        source=source,
        private=private,
    )

    # 2. 写 SQLite
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, summary, content, source, created_at, updated_at,
                importance, private, archived, file_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (mid, summary, content, source, now, now, 0.0, int(private), file_path),
        )
        # labels
        conn.execute("DELETE FROM labels WHERE memory_id = ?", (mid,))
        for tag in tags:
            conn.execute(
                "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'tag')",
                (mid, tag),
            )
        for link in links:
            conn.execute(
                "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'link')",
                (mid, link),
            )
        # FTS
        conn.execute("DELETE FROM memories_fts WHERE id = ?", (mid,))
        conn.execute(
            "INSERT INTO memories_fts (id, summary, content) VALUES (?, ?, ?)",
            (mid, summary, content),
        )

    # 3. 写向量
    embed_text = f"{summary}\n{content}"
    vec_ok = upsert_vector(mid, embed_text, private=private)

    # 4. 如果是合并操作：迁移标签 + 标记原始记忆为 archived
    if merge_from:
        with get_conn() as conn:
            for old_id in merge_from:
                # 迁移旧记忆的标签到新记忆
                old_labels = conn.execute(
                    "SELECT name, type FROM labels WHERE memory_id = ?",
                    (old_id,),
                ).fetchall()
                for label in old_labels:
                    conn.execute(
                        "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, ?)",
                        (mid, label["name"], label["type"]),
                    )
                # 标记旧记忆为 archived
                conn.execute(
                    "UPDATE memories SET archived = 1, updated_at = ? WHERE id = ?",
                    (now, old_id),
                )

    return {
        "id": mid,
        "file_path": file_path,
        "status": "ok" if vec_ok else "partial",
    }


# ═══════════════════════════════════════════════════════════
# RECALL
# ═══════════════════════════════════════════════════════════


def recall(
    query: Optional[str] = None,
    tags: Optional[list[str]] = None,
    memory_id: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    private: bool = False,
    include_archived: bool = False,
    include_content: bool = False,
) -> list[dict]:
    """
    统一检索入口。

    优先级: memory_id > tags > query(语义) > recent
    """
    init_db()

    if memory_id:
        return _recall_by_id(memory_id, include_content)

    if tags:
        return _recall_by_tags(tags, limit, private, include_archived, include_content)

    if query:
        return _recall_by_query(query, limit, private, include_archived, include_content)

    return _recall_recent(limit, offset, private, include_content)


def _recall_by_id(memory_id: str, include_content: bool) -> list[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return []
        _touch_recall(conn, memory_id)
        return [_row_to_dict(row, include_content)]


def _recall_by_tags(
    tags: list[str], limit: int, private: bool,
    include_archived: bool, include_content: bool,
) -> list[dict]:
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in tags)
        sql = f"""
            SELECT DISTINCT m.* FROM memories m
            JOIN labels l ON m.id = l.memory_id
            WHERE l.name IN ({placeholders})
              AND m.private = ?
        """
        params: list = list(tags) + [int(private)]
        if not include_archived:
            sql += " AND m.archived = 0"
        sql += " ORDER BY m.importance DESC, m.created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            _touch_recall(conn, row["id"])
        return [_row_to_dict(r, include_content) for r in rows]


def _recall_by_query(
    query: str, limit: int, private: bool,
    include_archived: bool, include_content: bool,
) -> list[dict]:
    # 1. 向量语义搜索
    vec_results = search_vectors(query, limit=limit * 2, private=private)
    if not vec_results:
        return _recall_fts(query, limit, private, include_archived, include_content)

    vec_ids = [r["id"] for r in vec_results]
    score_map = {r["id"]: r["score"] for r in vec_results}

    # 2. 从 SQLite 获取完整信息
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in vec_ids)
        sql = f"SELECT * FROM memories WHERE id IN ({placeholders}) AND private = ?"
        params: list = vec_ids + [int(private)]
        if not include_archived:
            sql += " AND archived = 0"
        rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            d = _row_to_dict(row, include_content)
            d["score"] = score_map.get(row["id"], 0.0)
            results.append(d)
            _touch_recall(conn, row["id"])

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results[:limit]


def _recall_fts(
    query: str, limit: int, private: bool,
    include_archived: bool, include_content: bool,
) -> list[dict]:
    """FTS5 全文搜索降级"""
    with get_conn() as conn:
        sql = """
            SELECT m.* FROM memories m
            JOIN memories_fts f ON m.id = f.id
            WHERE memories_fts MATCH ? AND m.private = ?
        """
        params: list = [query, int(private)]
        if not include_archived:
            sql += " AND m.archived = 0"
        sql += " LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            _touch_recall(conn, row["id"])
        return [_row_to_dict(r, include_content) for r in rows]


def _recall_recent(limit: int, offset: int, private: bool, include_content: bool) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM memories
               WHERE private = ? AND archived = 0
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (int(private), limit, offset),
        ).fetchall()
        return [_row_to_dict(r, include_content) for r in rows]


def _touch_recall(conn, memory_id: str):
    """更新召回时间和计数"""
    conn.execute(
        """UPDATE memories SET
           last_recalled_at = ?, recall_count = recall_count + 1
           WHERE id = ?""",
        (_now(), memory_id),
    )


def _row_to_dict(row, include_content: bool = False) -> dict:
    d = {
        "id": row["id"],
        "summary": row["summary"],
        "source": row["source"],
        "created_at": row["created_at"],
        "importance": row["importance"],
        "recall_count": row["recall_count"],
        "private": bool(row["private"]),
        "archived": bool(row["archived"]),
    }
    if include_content:
        d["content"] = row["content"]
    return d


# ═══════════════════════════════════════════════════════════
# MANAGE
# ═══════════════════════════════════════════════════════════


def get_memory(memory_id: str) -> Optional[dict]:
    """获取单条记忆完整信息（含 labels）"""
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return None
        d = _row_to_dict(row, include_content=True)
        labels = conn.execute(
            "SELECT name, type FROM labels WHERE memory_id = ?", (memory_id,)
        ).fetchall()
        d["tags"] = [l["name"] for l in labels if l["type"] == "tag"]
        d["links"] = [l["name"] for l in labels if l["type"] == "link"]
        return d


def delete_memory(memory_id: str) -> bool:
    """标记为 archived（软删除）"""
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE memories SET archived = 1, updated_at = ? WHERE id = ?",
            (_now(), memory_id),
        )
    delete_vector(memory_id)
    return True


def restore_memory(memory_id: str) -> bool:
    """恢复已归档的记忆"""
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT file_path, private, summary FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE memories SET archived = 0, updated_at = ? WHERE id = ?",
            (_now(), memory_id),
        )
        file_path = row["file_path"]
        private = bool(row["private"])
        summary = row["summary"]

    # 重新写入向量
    if file_path:
        from .filestore import read_file
        file_data = read_file(file_path)
        if file_data:
            content = file_data.get("content", "")
            upsert_vector(memory_id, f"{summary}\n{content}", private=private)
    return True


def purge_memory(memory_id: str) -> bool:
    """永久删除记忆（数据库 + 文件 + 向量）"""
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT file_path FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return False
        # 删数据库
        conn.execute("DELETE FROM labels WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    # 删向量
    delete_vector(memory_id)
    # 删文件
    if row["file_path"]:
        filepath = STORE_DIR / row["file_path"]
        if filepath.exists():
            filepath.unlink()
    return True


def update_tags(memory_id: str, add: list[str] = None, remove: list[str] = None) -> bool:
    """更新标签"""
    init_db()
    with get_conn() as conn:
        if remove:
            for tag in remove:
                conn.execute(
                    "DELETE FROM labels WHERE memory_id = ? AND name = ?",
                    (memory_id, tag.lower()),
                )
        if add:
            for tag in add:
                conn.execute(
                    "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'tag')",
                    (memory_id, tag.lower()),
                )
        conn.execute(
            "UPDATE memories SET updated_at = ? WHERE id = ?", (_now(), memory_id)
        )
    return True


def get_labels(limit: int = 0, include_private: bool = False) -> list[dict]:
    """获取标签及其关联记忆数（仅活跃记忆）。limit=0 返回全部。"""
    init_db()
    with get_conn() as conn:
        sql = """SELECT l.name, l.type, COUNT(DISTINCT l.memory_id) as count
                 FROM labels l
                 JOIN memories m ON l.memory_id = m.id
                 WHERE m.archived = 0"""
        if not include_private:
            sql += " AND m.private = 0"
        sql += " GROUP BY l.name, l.type ORDER BY count DESC"
        if limit > 0:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
        return [{"name": r["name"], "type": r["type"], "count": r["count"]} for r in rows]


def get_stats() -> dict:
    """系统统计"""
    init_db()
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM memories WHERE archived = 0").fetchone()[0]
        private_count = conn.execute("SELECT COUNT(*) FROM memories WHERE private = 1").fetchone()[0]
        label_count = conn.execute("SELECT COUNT(DISTINCT name) FROM labels").fetchone()[0]
        return {
            "total": total,
            "active": active,
            "archived": total - active,
            "private": private_count,
            "labels": label_count,
        }


def get_graph_data(private: bool = False) -> dict:
    """生成关系图数据（二部图：记忆节点 + 标签节点 + 连线）"""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT m.id, m.summary, m.importance, l.name, l.type
               FROM memories m
               JOIN labels l ON m.id = l.memory_id
               WHERE m.archived = 0 AND m.private = ?""",
            (int(private),),
        ).fetchall()

    nodes = []
    edges = []
    label_nodes = {}
    memory_set = set()

    for row in rows:
        mid = row["id"]
        if mid not in memory_set:
            memory_set.add(mid)
            nodes.append({
                "id": mid,
                "label": row["summary"][:30],
                "type": "memory",
                "importance": row["importance"],
            })

        label_name = row["name"]
        if label_name not in label_nodes:
            label_nodes[label_name] = {
                "id": f"label:{label_name}",
                "label": label_name,
                "type": row["type"],
            }

        edges.append({"source": mid, "target": f"label:{label_name}"})

    nodes.extend(label_nodes.values())
    return {"nodes": nodes, "edges": edges}


# ═══════════════════════════════════════════════════════════
# IMPORT / EXPORT
# ═══════════════════════════════════════════════════════════


def export_memories(private: bool = False, include_archived: bool = False) -> list[dict]:
    """导出所有记忆为 JSON 可序列化的 dict 列表"""
    init_db()
    with get_conn() as conn:
        sql = "SELECT * FROM memories WHERE private = ?"
        params: list = [int(private)]
        if not include_archived:
            sql += " AND archived = 0"
        sql += " ORDER BY created_at ASC"
        rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            d = _row_to_dict(row, include_content=True)
            labels = conn.execute(
                "SELECT name, type FROM labels WHERE memory_id = ?", (row["id"],)
            ).fetchall()
            d["tags"] = [l["name"] for l in labels if l["type"] == "tag"]
            d["links"] = [l["name"] for l in labels if l["type"] == "link"]
            results.append(d)
    return results


def import_memories(data: list[dict]) -> dict:
    """从 JSON 列表导入记忆，返回统计"""
    init_db()
    imported = 0
    skipped = 0
    for item in data:
        content = item.get("content", "")
        if not content:
            skipped += 1
            continue
        mid = item.get("id") or str(uuid.uuid4())
        tags = item.get("tags", [])
        source = item.get("source", "imported")
        private = item.get("private", False)
        store(content=content, tags=tags, source=source, private=private, memory_id=mid)
        imported += 1
    return {"imported": imported, "skipped": skipped}

