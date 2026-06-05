"""核心业务逻辑 - store / recall / manage 统一入口"""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import STORE_DIR, load_label_aliases
from .db import get_conn, init_db
from .vector import upsert_vector, search_vectors, delete_vector
from .filestore import write_file, extract_links, update_file_metadata


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_summary(content: str) -> str:
    """从内容提取摘要：优先 ## 摘要 段落，否则取首行"""
    lines = content.strip().split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "## 摘要":
            for candidate in lines[i + 1:]:
                stripped = candidate.strip()
                if stripped:
                    return stripped[:200]
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
    return content[:200]


def _normalize_labels(labels: Optional[list[str]], apply_aliases: bool = True) -> list[str]:
    """规范化标签并保持输入顺序去重。"""
    alias_map = {}
    if apply_aliases:
        for canonical, variants in load_label_aliases().items():
            for variant in variants:
                alias_map[variant] = canonical

    seen = set()
    out = []
    for label in labels or []:
        name = label.lower().strip()
        if apply_aliases:
            name = alias_map.get(name, name)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _normalize_agent_trust_level(trust_level: str) -> str:
    allowed = {"candidate_only", "trusted_writer", "read_only", "private_allowed"}
    normalized = (trust_level or "trusted_writer").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"invalid trust_level: {trust_level}")
    return normalized


def _sync_file_labels(conn, memory_id: str) -> None:
    row = conn.execute(
        """SELECT file_path, source, private, archived, kind, authority,
                  retrieval_role, confidence, status, superseded_by, valid_from,
                  valid_until, source_agent, source_run_id
           FROM memories WHERE id = ?""",
        (memory_id,),
    ).fetchone()
    if not row or not row["file_path"]:
        return
    labels = conn.execute(
        "SELECT name, type FROM labels WHERE memory_id = ? ORDER BY type, name",
        (memory_id,),
    ).fetchall()
    update_file_metadata(
        row["file_path"],
        tags=[l["name"] for l in labels if l["type"] == "tag"],
        links=[l["name"] for l in labels if l["type"] == "link"],
        source=row["source"],
        private=bool(row["private"]),
        archived=bool(row["archived"]),
        kind=row["kind"],
        authority=row["authority"],
        retrieval_role=row["retrieval_role"],
        confidence=row["confidence"],
        status=row["status"],
        superseded_by=row["superseded_by"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        source_agent=row["source_agent"],
        source_run_id=row["source_run_id"],
    )


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
    created_at: Optional[str] = None,
    archived: bool = False,
    kind: str = "fact",
    authority: str = "confirmed",
    retrieval_role: str = "background",
    confidence: float = 1.0,
    status: str = "active",
    superseded_by: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    source_agent: Optional[str] = None,
    source_run_id: Optional[str] = None,
) -> dict:
    """
    写入一条记忆。

    Returns: {"id": str, "file_path": str, "status": "ok"|"partial"}
    """
    init_db()

    if source == "manual" and source_agent:
        source = source_agent

    mid = memory_id or str(uuid.uuid4())
    tags = _normalize_labels(tags)
    links = _normalize_labels(extract_links(content), apply_aliases=True)
    summary = _extract_summary(content)
    now = _now()
    status = "archived" if archived else (status or "active")

    with get_conn() as conn:
        existing = conn.execute(
            """SELECT created_at, recall_count, last_recalled_at, importance,
                      private, file_path
               FROM memories WHERE id = ?""",
            (mid,),
        ).fetchone()
    stored_created_at = existing["created_at"] if existing else (created_at or now)

    # 1. 写文件
    file_path = write_file(
        memory_id=mid,
        content=content,
        summary=summary,
        tags=tags,
        links=links,
        source=source,
        private=private,
        created_at=stored_created_at,
        archived=archived,
        kind=kind,
        authority=authority,
        retrieval_role=retrieval_role,
        confidence=confidence,
        status=status,
        superseded_by=superseded_by,
        valid_from=valid_from,
        valid_until=valid_until,
        source_agent=source_agent,
        source_run_id=source_run_id,
    )

    # 2. 写 SQLite
    with get_conn() as conn:
        if existing:
            conn.execute(
                """UPDATE memories SET
                   summary = ?, content = ?, source = ?, updated_at = ?,
                   private = ?, archived = ?, kind = ?, authority = ?,
                   retrieval_role = ?, confidence = ?, status = ?, superseded_by = ?,
                   valid_from = ?, valid_until = ?, source_agent = ?, source_run_id = ?,
                   file_path = ?
                   WHERE id = ?""",
                (
                    summary, content, source, now, int(private), int(archived),
                    kind, authority, retrieval_role, confidence, status, superseded_by,
                    valid_from, valid_until, source_agent, source_run_id, file_path, mid,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO memories
                   (id, summary, content, source, created_at, updated_at,
                    importance, private, archived, kind, authority, retrieval_role,
                    confidence, status, superseded_by, valid_from, valid_until,
                    source_agent, source_run_id, file_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mid, summary, content, source, stored_created_at, now, 0.0,
                    int(private), int(archived), kind, authority, retrieval_role,
                    confidence, status, superseded_by, valid_from, valid_until,
                    source_agent, source_run_id, file_path,
                ),
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

    if existing:
        old_private = bool(existing["private"])
        old_file_path = existing["file_path"]
        if old_private != private:
            delete_vector(mid, private=old_private)
        if old_file_path and old_file_path != file_path:
            old_path = STORE_DIR / old_file_path
            if old_path.exists():
                old_path.unlink()

    # 3. 写向量
    embed_text = f"{summary}\n{content}"
    if archived:
        delete_vector(mid, private=private)
        vec_ok = True
    else:
        vec_ok = upsert_vector(mid, embed_text, private=private)

    # 4. 如果是合并操作：迁移标签 + 标记原始记忆为 archived
    if merge_from:
        with get_conn() as conn:
            for old_id in merge_from:
                # 迁移旧记忆的标签到新记忆
                old_row = conn.execute(
                    "SELECT private, file_path FROM memories WHERE id = ?",
                    (old_id,),
                ).fetchone()
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
                    "UPDATE memories SET archived = 1, status = 'archived', updated_at = ? WHERE id = ?",
                    (now, old_id),
                )
                if old_row:
                    if old_row["file_path"]:
                        update_file_metadata(old_row["file_path"], archived=True)
                    delete_vector(old_id, private=bool(old_row["private"]))
            _sync_file_labels(conn, mid)

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
    include_statuses: Optional[list[str]] = None,
) -> list[dict]:
    """
    统一检索入口。

    优先级: memory_id > tags > query(语义) > recent
    """
    init_db()

    if memory_id:
        return _recall_by_id(memory_id, include_content)

    if tags:
        return _recall_by_tags(tags, limit, private, include_archived, include_content, include_statuses)

    if query:
        return _recall_by_query(query, limit, private, include_archived, include_content, include_statuses)

    return _recall_recent(limit, offset, private, include_content, include_statuses)


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
    include_archived: bool, include_content: bool, include_statuses: Optional[list[str]],
) -> list[dict]:
    tags = _normalize_labels(tags)
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
            sql += " AND m.archived = 0 AND COALESCE(m.status, 'active') IN ('active', 'pinned')"
        elif include_statuses:
            placeholders_status = ",".join("?" for _ in include_statuses)
            sql += f" AND COALESCE(m.status, 'active') IN ({placeholders_status})"
            params.extend(include_statuses)
        sql += " ORDER BY m.importance DESC, m.created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            _touch_recall(conn, row["id"])
        return [_row_to_dict(r, include_content) for r in rows]


def _recall_by_query(
    query: str, limit: int, private: bool,
    include_archived: bool, include_content: bool, include_statuses: Optional[list[str]],
) -> list[dict]:
    # 1. 向量语义搜索
    vec_results = search_vectors(query, limit=limit * 2, private=private)
    if not vec_results:
        return _recall_fts(query, limit, private, include_archived, include_content, include_statuses)

    vec_ids = [r["id"] for r in vec_results]
    score_map = {r["id"]: r["score"] for r in vec_results}

    # 2. 从 SQLite 获取完整信息
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in vec_ids)
        sql = f"SELECT * FROM memories WHERE id IN ({placeholders}) AND private = ?"
        params: list = vec_ids + [int(private)]
        if not include_archived:
            sql += " AND archived = 0 AND COALESCE(status, 'active') IN ('active', 'pinned')"
        elif include_statuses:
            placeholders_status = ",".join("?" for _ in include_statuses)
            sql += f" AND COALESCE(status, 'active') IN ({placeholders_status})"
            params.extend(include_statuses)
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
    include_archived: bool, include_content: bool, include_statuses: Optional[list[str]],
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
            sql += " AND m.archived = 0 AND COALESCE(m.status, 'active') IN ('active', 'pinned')"
        elif include_statuses:
            placeholders_status = ",".join("?" for _ in include_statuses)
            sql += f" AND COALESCE(m.status, 'active') IN ({placeholders_status})"
            params.extend(include_statuses)
        sql += " LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            _touch_recall(conn, row["id"])
        return [_row_to_dict(r, include_content) for r in rows]


def _recall_recent(
    limit: int, offset: int, private: bool, include_content: bool,
    include_statuses: Optional[list[str]],
) -> list[dict]:
    with get_conn() as conn:
        sql = """SELECT * FROM memories
                 WHERE private = ? AND archived = 0
                 AND COALESCE(status, 'active') IN ('active', 'pinned')"""
        params: list = [int(private)]
        if include_statuses:
            placeholders_status = ",".join("?" for _ in include_statuses)
            sql = f"""SELECT * FROM memories
                      WHERE private = ? AND COALESCE(status, 'active') IN ({placeholders_status})"""
            params.extend(include_statuses)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
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
        "kind": row["kind"],
        "authority": row["authority"],
        "retrieval_role": row["retrieval_role"],
        "confidence": row["confidence"],
        "status": row["status"],
        "superseded_by": row["superseded_by"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "source_agent": row["source_agent"],
        "source_run_id": row["source_run_id"],
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
        row = conn.execute(
            "SELECT private, file_path FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE memories SET archived = 1, status = 'archived', updated_at = ? WHERE id = ?",
            (_now(), memory_id),
        )
    if row["file_path"]:
        update_file_metadata(row["file_path"], archived=True)
    delete_vector(memory_id, private=bool(row["private"]))
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
            "UPDATE memories SET archived = 0, status = 'active', updated_at = ? WHERE id = ?",
            (_now(), memory_id),
        )
        file_path = row["file_path"]
        private = bool(row["private"])
        summary = row["summary"]

    if file_path:
        update_file_metadata(file_path, archived=False)

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
            "SELECT file_path, private FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return False
        # 删数据库
        conn.execute("DELETE FROM labels WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    # 删向量
    delete_vector(memory_id, private=bool(row["private"]))
    # 删文件
    if row["file_path"]:
        filepath = STORE_DIR / row["file_path"]
        if filepath.exists():
            filepath.unlink()
    return True


def update_tags(memory_id: str, add: list[str] = None, remove: list[str] = None) -> bool:
    """更新标签"""
    init_db()
    add = _normalize_labels(add)
    remove = _normalize_labels(remove)
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not exists:
            return False
        if remove:
            for tag in remove:
                conn.execute(
                    "DELETE FROM labels WHERE memory_id = ? AND name = ?",
                    (memory_id, tag),
                )
        if add:
            for tag in add:
                conn.execute(
                    "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'tag')",
                    (memory_id, tag),
                )
        conn.execute(
            "UPDATE memories SET updated_at = ? WHERE id = ?", (_now(), memory_id)
        )
        _sync_file_labels(conn, memory_id)
    return True


def get_labels(limit: int = 0, include_private: bool = False) -> list[dict]:
    """获取标签及其关联记忆数（仅活跃记忆）。limit=0 返回全部。"""
    init_db()
    with get_conn() as conn:
        sql = """SELECT l.name, l.type, COUNT(DISTINCT l.memory_id) as count
                 FROM labels l
                 JOIN memories m ON l.memory_id = m.id
                 WHERE m.archived = 0 AND COALESCE(m.status, 'active') IN ('active', 'pinned')"""
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
        active = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE archived = 0 AND COALESCE(status, 'active') IN ('active', 'pinned')"
        ).fetchone()[0]
        private_count = conn.execute("SELECT COUNT(*) FROM memories WHERE private = 1").fetchone()[0]
        label_count = conn.execute("SELECT COUNT(DISTINCT name) FROM labels").fetchone()[0]
        by_status = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT COALESCE(status, 'active') AS status, COUNT(*) AS count FROM memories GROUP BY COALESCE(status, 'active')"
            ).fetchall()
        }
        return {
            "total": total,
            "active": active,
            "archived": total - active,
            "private": private_count,
            "labels": label_count,
            "by_status": by_status,
        }


def get_graph_data(private: bool = False) -> dict:
    """生成关系图数据（二部图：记忆节点 + 标签节点 + 连线）"""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT m.id, m.summary, m.importance, l.name, l.type
               FROM memories m
               JOIN labels l ON m.id = l.memory_id
               WHERE m.archived = 0
                 AND COALESCE(m.status, 'active') IN ('active', 'pinned')
                 AND m.private = ?""",
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
        created_at = item.get("created_at")
        archived = item.get("archived", False)
        kind = item.get("kind", "fact")
        authority = item.get("authority", "confirmed")
        retrieval_role = item.get("retrieval_role", "background")
        confidence = item.get("confidence", 1.0)
        status = item.get("status", "archived" if archived else "active")
        store(
            content=content,
            tags=tags,
            source=source,
            private=private,
            memory_id=mid,
            created_at=created_at,
            archived=archived,
            kind=kind,
            authority=authority,
            retrieval_role=retrieval_role,
            confidence=confidence,
            status=status,
            superseded_by=item.get("superseded_by"),
            valid_from=item.get("valid_from"),
            valid_until=item.get("valid_until"),
            source_agent=item.get("source_agent"),
            source_run_id=item.get("source_run_id"),
        )
        imported += 1
    return {"imported": imported, "skipped": skipped}


# ═══════════════════════════════════════════════════════════
# CANDIDATES
# ═══════════════════════════════════════════════════════════


def create_candidate(
    content: str,
    tags: Optional[list[str]] = None,
    source: str = "agent_candidate",
    source_agent: Optional[str] = None,
    source_run_id: Optional[str] = None,
    private: bool = False,
    proposed_kind: str = "fact",
    proposed_authority: str = "model_generated",
    proposed_retrieval_role: str = "background",
    confidence: float = 0.7,
    candidate_id: Optional[str] = None,
) -> dict:
    init_db()
    cid = candidate_id or str(uuid.uuid4())
    now = _now()
    normalized_tags = _normalize_labels(tags)
    summary = _extract_summary(content)

    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO memory_candidates
               (id, content, summary, proposed_tags, proposed_kind, proposed_authority,
                proposed_retrieval_role, confidence, source, source_agent, source_run_id,
                private, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cid, content, summary, _json_dumps(normalized_tags), proposed_kind,
                proposed_authority, proposed_retrieval_role, confidence, source,
                source_agent, source_run_id, int(private), "pending", now,
            ),
        )

    return {"id": cid, "status": "pending"}


def list_candidates(
    status: Optional[str] = "pending",
    limit: int = 20,
    offset: int = 0,
    source_agent: Optional[str] = None,
) -> list[dict]:
    init_db()
    with get_conn() as conn:
        sql = "SELECT * FROM memory_candidates WHERE 1 = 1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if source_agent:
            sql += " AND source_agent = ?"
            params.append(source_agent)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [_candidate_row_to_dict(row) for row in rows]


def get_candidate(candidate_id: str) -> Optional[dict]:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM memory_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        return _candidate_row_to_dict(row) if row else None


def promote_candidate(
    candidate_id: str,
    reviewed_by: Optional[str] = None,
    review_note: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[list[str]] = None,
    kind: Optional[str] = None,
    authority: Optional[str] = None,
    retrieval_role: Optional[str] = None,
    confidence: Optional[float] = None,
    status: str = "active",
    source: Optional[str] = None,
    source_agent: Optional[str] = None,
    source_run_id: Optional[str] = None,
    private: Optional[bool] = None,
    merge_from: Optional[list[str]] = None,
) -> dict:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM memory_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if not row:
            raise ValueError("candidate not found")
        if row["status"] not in ("pending",):
            raise ValueError(f"candidate already reviewed: {row['status']}")

    candidate = _candidate_row_to_dict(row)
    final_content = content if content is not None else candidate["content"]
    final_tags = _normalize_labels(tags if tags is not None else candidate["proposed_tags"])
    final_kind = kind or candidate["proposed_kind"] or "fact"
    final_authority = authority or candidate["proposed_authority"] or "model_generated"
    final_role = retrieval_role or candidate["proposed_retrieval_role"] or "background"
    final_confidence = confidence if confidence is not None else candidate["confidence"]
    final_source = source or candidate["source"]
    final_source_agent = source_agent if source_agent is not None else candidate["source_agent"]
    final_source_run_id = source_run_id if source_run_id is not None else candidate["source_run_id"]
    final_private = bool(candidate["private"]) if private is None else private

    store_result = store(
        content=final_content,
        tags=final_tags,
        source=final_source,
        private=final_private,
        merge_from=merge_from,
        kind=final_kind,
        authority=final_authority,
        retrieval_role=final_role,
        confidence=final_confidence,
        status=status,
        source_agent=final_source_agent,
        source_run_id=final_source_run_id,
    )

    reviewed_at = _now()
    reviewed_status = "accepted"
    edited = any([
        content is not None,
        tags is not None,
        kind is not None,
        authority is not None,
        retrieval_role is not None,
        confidence is not None,
        source is not None,
        source_agent is not None,
        source_run_id is not None,
        private is not None,
        bool(merge_from),
        status != "active",
    ])
    if edited:
        reviewed_status = "edited"
    if merge_from:
        reviewed_status = "merged"

    with get_conn() as conn:
        conn.execute(
            """UPDATE memory_candidates
               SET status = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?,
                   promoted_memory_id = ?
               WHERE id = ?""",
            (
                reviewed_status, review_note, reviewed_at, reviewed_by,
                store_result["id"], candidate_id,
            ),
        )

    return {
        "id": candidate_id,
        "status": reviewed_status,
        "promoted_memory_id": store_result["id"],
        "memory_status": store_result["status"],
    }


def reject_candidate(
    candidate_id: str,
    reviewed_by: Optional[str] = None,
    review_note: Optional[str] = None,
    status: str = "rejected",
) -> dict:
    if status not in ("rejected", "discarded"):
        raise ValueError("invalid candidate status")
    init_db()
    reviewed_at = _now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM memory_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if not row:
            raise ValueError("candidate not found")
        if row["status"] not in ("pending",):
            raise ValueError(f"candidate already reviewed: {row['status']}")
        conn.execute(
            """UPDATE memory_candidates
               SET status = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?
               WHERE id = ?""",
            (status, review_note, reviewed_at, reviewed_by, candidate_id),
        )
    return {"id": candidate_id, "status": status}


def _candidate_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "content": row["content"],
        "summary": row["summary"],
        "proposed_tags": _json_loads(row["proposed_tags"], []),
        "proposed_kind": row["proposed_kind"],
        "proposed_authority": row["proposed_authority"],
        "proposed_retrieval_role": row["proposed_retrieval_role"],
        "confidence": row["confidence"],
        "source": row["source"],
        "source_agent": row["source_agent"],
        "source_run_id": row["source_run_id"],
        "private": bool(row["private"]),
        "status": row["status"],
        "review_note": row["review_note"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
        "reviewed_by": row["reviewed_by"],
        "promoted_memory_id": row["promoted_memory_id"],
    }


# ═══════════════════════════════════════════════════════════
# AGENTS
# ═══════════════════════════════════════════════════════════


def register_agent(
    agent_id: str,
    name: str,
    description: Optional[str] = None,
    trust_level: str = "trusted_writer",
    can_read_private: bool = False,
    can_write_durable: Optional[bool] = None,
) -> dict:
    init_db()
    normalized_trust_level = _normalize_agent_trust_level(trust_level)
    if can_write_durable is None:
        can_write_durable = normalized_trust_level == "trusted_writer"
    created_at = _now()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT created_at FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
        conn.execute(
            """INSERT OR REPLACE INTO agents
               (id, name, description, trust_level, can_read_private, can_write_durable, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id, name, description, normalized_trust_level,
                int(can_read_private), int(can_write_durable),
                existing["created_at"] if existing else created_at,
            ),
        )
    return get_agent(agent_id)


def get_agent(agent_id: str) -> Optional[dict]:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return _agent_row_to_dict(row) if row else None


def list_agents(limit: int = 100, offset: int = 0) -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agents ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_agent_row_to_dict(row) for row in rows]


def recall_for_agent(
    agent_id: str,
    query: Optional[str] = None,
    tags: Optional[list[str]] = None,
    memory_id: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    private: bool = False,
    include_archived: bool = False,
    include_content: bool = False,
    include_statuses: Optional[list[str]] = None,
) -> dict:
    init_db()
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError("agent not registered")

    allow_private = private and agent["can_read_private"]
    if private and not agent["can_read_private"]:
        raise ValueError("agent is not allowed to read private memory")

    if memory_id:
        item = get_memory(memory_id)
        if not item:
            return {
                "agent_id": agent_id,
                "private_scope": allow_private,
                "memories": [],
                "count": 0,
            }
        if item["private"] and not allow_private:
            raise ValueError("agent is not allowed to read private memory")
        if not item["private"] and private:
            return {
                "agent_id": agent_id,
                "private_scope": allow_private,
                "memories": [],
                "count": 0,
            }
        if not include_archived and item["archived"]:
            return {
                "agent_id": agent_id,
                "private_scope": allow_private,
                "memories": [],
                "count": 0,
            }
        if include_statuses and item["status"] not in include_statuses:
            return {
                "agent_id": agent_id,
                "private_scope": allow_private,
                "memories": [],
                "count": 0,
            }
        if not include_archived and item["status"] not in ("active", "pinned"):
            return {
                "agent_id": agent_id,
                "private_scope": allow_private,
                "memories": [],
                "count": 0,
            }
        return {
            "agent_id": agent_id,
            "private_scope": allow_private,
            "memories": [item if include_content else {k: v for k, v in item.items() if k != "content"}],
            "count": 1,
        }

    results = recall(
        query=query,
        tags=tags,
        limit=limit,
        offset=offset,
        private=allow_private,
        include_archived=include_archived,
        include_content=include_content,
        include_statuses=include_statuses,
    )
    return {
        "agent_id": agent_id,
        "private_scope": allow_private,
        "memories": results,
        "count": len(results),
    }


def recall_context(
    query: str,
    agent_id: Optional[str] = None,
    project: Optional[str] = None,
    private: bool = False,
    include_kinds: Optional[list[str]] = None,
    exclude_statuses: Optional[list[str]] = None,
    limit: int = 20,
    include_content: bool = False,
) -> dict:
    init_db()
    if not query:
        raise ValueError("query is required")

    if agent_id:
        base = recall_for_agent(
            agent_id=agent_id,
            query=query,
            limit=max(limit * 2, limit),
            private=private,
            include_archived=True,
            include_content=include_content,
        )
        items = list(base["memories"])
        private_scope = base["private_scope"]
    else:
        items = recall(
            query=query,
            limit=max(limit * 2, limit),
            private=private,
            include_archived=True,
            include_content=include_content,
        )
        private_scope = private

    normalized_kinds = {k.strip().lower() for k in include_kinds or [] if k and k.strip()}
    excluded_statuses = {s.strip().lower() for s in exclude_statuses or [] if s and s.strip()}
    if not excluded_statuses:
        excluded_statuses = {"archived", "stale", "discarded"}

    filtered = []
    for item in items:
        if normalized_kinds and (item.get("kind") or "").lower() not in normalized_kinds:
            continue
        status = (item.get("status") or "active").lower()
        if status in excluded_statuses:
            continue
        filtered.append(item)

    ranked = []
    for item in filtered:
        ranked.append(_enrich_context_item(item, query=query, project=project))
    ranked.sort(key=lambda x: x["score"], reverse=True)
    ranked = ranked[:limit]

    context_pack = {
        "current_state": [],
        "hard_constraints": [],
        "prior_decisions": [],
        "background": [],
        "references": [],
        "forbidden_directions": [],
    }
    for item in ranked:
        bucket = _context_bucket(item)
        context_pack[bucket].append(_context_pack_entry(item))

    return {
        "query": query,
        "agent_id": agent_id,
        "scope": {
            "project": project,
            "private": private_scope,
        },
        "context_pack": context_pack,
        "items": ranked,
    }


def store_from_agent(
    agent_id: str,
    content: str,
    tags: Optional[list[str]] = None,
    source: str = "agent",
    private: bool = False,
    merge_from: Optional[list[str]] = None,
    kind: str = "fact",
    authority: Optional[str] = None,
    retrieval_role: str = "background",
    confidence: Optional[float] = None,
    status: str = "active",
    source_run_id: Optional[str] = None,
) -> dict:
    init_db()
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError("agent not registered")

    trust_level = agent["trust_level"]
    if trust_level == "read_only":
        raise ValueError("read_only agent cannot write memory")

    if private and not agent["can_read_private"]:
        raise ValueError("agent is not allowed to write private memory")

    normalized_source = agent_id if (source or "").lower() in ("", "agent", "manual") else source
    write_durable = trust_level == "trusted_writer" and agent["can_write_durable"]
    if write_durable:
        result = store(
            content=content,
            tags=tags,
            source=normalized_source,
            private=private,
            merge_from=merge_from,
            kind=kind,
            authority=authority or "confirmed",
            retrieval_role=retrieval_role,
            confidence=1.0 if confidence is None else confidence,
            status=status,
            source_agent=agent_id,
            source_run_id=source_run_id,
        )
        return {
            "route": "durable_memory",
            "agent_id": agent_id,
            "agent_trust_level": trust_level,
            "memory_id": result["id"],
            "memory_status": result["status"],
        }

    candidate = create_candidate(
        content=content,
        tags=tags,
        source=source if (source or "").lower() not in ("", "agent", "manual") else "agent_candidate",
        source_agent=agent_id,
        source_run_id=source_run_id,
        private=private,
        proposed_kind=kind,
        proposed_authority=authority or "model_generated",
        proposed_retrieval_role=retrieval_role,
        confidence=0.7 if confidence is None else confidence,
    )
    return {
        "route": "candidate",
        "agent_id": agent_id,
        "agent_trust_level": trust_level,
        "candidate_id": candidate["id"],
        "candidate_status": candidate["status"],
    }


def _agent_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "trust_level": row["trust_level"],
        "can_read_private": bool(row["can_read_private"]),
        "can_write_durable": bool(row["can_write_durable"]),
        "created_at": row["created_at"],
    }


def _enrich_context_item(item: dict, query: str, project: Optional[str] = None) -> dict:
    semantic = float(item.get("score") or 0.0)
    importance_boost = min(float(item.get("importance") or 0.0), 1.0) * 0.08
    authority_map = {
        "user_decision": 0.14,
        "user_preference": 0.12,
        "confirmed": 0.1,
        "observed": 0.08,
        "inferred": 0.03,
        "model_generated": -0.04,
        "draft": -0.06,
    }
    role_map = {
        "hard_constraint": 0.18,
        "current_state": 0.15,
        "prior_judgment": 0.12,
        "reference": 0.08,
        "background": 0.04,
        "example": 0.03,
        "forbidden_direction": 0.18,
    }
    status_penalty_map = {
        "active": 0.0,
        "pinned": 0.06,
        "superseded": -0.15,
        "conflicted": -0.12,
        "archived": -0.2,
        "stale": -0.25,
        "discarded": -0.4,
    }
    authority = item.get("authority") or "confirmed"
    retrieval_role = item.get("retrieval_role") or "background"
    status = item.get("status") or "active"
    authority_boost = authority_map.get(authority, 0.0)
    role_boost = role_map.get(retrieval_role, 0.0)
    status_penalty = status_penalty_map.get(status, 0.0)
    confidence_term = (float(item.get("confidence") or 1.0) - 0.5) * 0.08
    haystack = " ".join([
        item.get("summary") or "",
        item.get("content") or "" if "content" in item else "",
    ])
    lexical_boost = _lexical_query_boost(query=query, haystack=haystack)
    project_boost = 0.0
    if project:
        if _normalized_contains(haystack, project):
            project_boost = 0.12

    total = (
        semantic + importance_boost + authority_boost + role_boost
        + confidence_term + lexical_boost + project_boost + status_penalty
    )
    total = round(total, 4)
    enriched = dict(item)
    enriched["score"] = total
    enriched["reason"] = _build_context_reason(
        semantic=semantic,
        authority=authority,
        retrieval_role=retrieval_role,
        lexical_boost=lexical_boost,
        project_boost=project_boost,
        status=status,
    )
    enriched["score_parts"] = {
        "semantic": round(semantic, 4),
        "importance": round(importance_boost, 4),
        "authority": round(authority_boost, 4),
        "role": round(role_boost, 4),
        "confidence": round(confidence_term, 4),
        "lexical": round(lexical_boost, 4),
        "project": round(project_boost, 4),
        "status_penalty": round(status_penalty, 4),
    }
    return enriched


def _build_context_reason(
    semantic: float,
    authority: str,
    retrieval_role: str,
    lexical_boost: float,
    project_boost: float,
    status: str,
) -> str:
    parts = []
    if semantic > 0:
        parts.append("semantic match")
    if lexical_boost > 0:
        parts.append("lexical match")
    if authority in ("user_decision", "user_preference", "confirmed", "observed"):
        parts.append(authority.replace("_", " "))
    if retrieval_role:
        parts.append(retrieval_role.replace("_", " "))
    if project_boost > 0:
        parts.append("project match")
    if status == "pinned":
        parts.append("pinned")
    if not parts:
        parts.append("metadata match")
    return " + ".join(parts)


def _lexical_query_boost(query: str, haystack: str) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    normalized_haystack = _normalize_search_text(haystack)
    matches = sum(1 for term in terms if term in normalized_haystack)
    if matches == 0:
        return 0.0
    return min(0.04 * matches, 0.16)


def _query_terms(query: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", " ", (query or "").lower())
    terms = []
    for term in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", normalized):
        if len(term) < 3 and not re.match(r"[\u4e00-\u9fff]{2,}", term):
            continue
        terms.append(_normalize_search_text(term))
    return sorted(set(terms))


def _normalized_contains(haystack: str, needle: str) -> bool:
    normalized_haystack = _normalize_search_text(haystack)
    normalized_needle = _normalize_search_text(needle)
    return bool(normalized_needle and normalized_needle in normalized_haystack)


def _normalize_search_text(value: str) -> str:
    return re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "", (value or "").lower())


def _context_bucket(item: dict) -> str:
    role = item.get("retrieval_role") or "background"
    kind = item.get("kind") or "fact"
    if role == "hard_constraint":
        return "hard_constraints"
    if role == "current_state" or kind == "project_state":
        return "current_state"
    if role == "forbidden_direction":
        return "forbidden_directions"
    if role == "reference":
        return "references"
    if kind == "decision" or role == "prior_judgment":
        return "prior_decisions"
    return "background"


def _context_pack_entry(item: dict) -> dict:
    return {
        "id": item["id"],
        "summary": item["summary"],
        "kind": item["kind"],
        "authority": item["authority"],
        "retrieval_role": item["retrieval_role"],
        "confidence": item["confidence"],
        "source": item["source"],
        "source_agent": item["source_agent"],
        "source_run_id": item["source_run_id"],
        "score": item["score"],
        "reason": item["reason"],
    }
