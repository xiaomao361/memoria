"""核心业务逻辑 - store / recall / manage 统一入口"""

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from .config import STORE_DIR, load_label_aliases
from .db import get_conn, init_db
from .vector import upsert_vector, search_vectors, delete_vector
from .filestore import write_file, extract_links, update_file_metadata

INTERPRETATION_MARKERS = (
    "信任", "关系更近", "更亲近", "依赖", "亲密", "情绪状态",
    "trust", "closer", "relationship", "depends on", "intimacy",
)


def fact_boundary_warnings(content: str) -> list[str]:
    text = (content or "").lower()
    if not text:
        return []
    if any(marker.lower() in text for marker in INTERPRETATION_MARKERS):
        return [
            "This content may describe an interpretation rather than an observable fact. "
            "Memoria should store observed facts; current position or relationship interpretation "
            "belongs in Continuity."
        ]
    return []


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

    result = {
        "id": mid,
        "file_path": file_path,
        "status": "ok" if vec_ok else "partial",
    }
    warnings = fact_boundary_warnings(content)
    if warnings:
        result["warnings"] = warnings
    return result


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
        return _recall_by_tags(tags, limit, offset, private, include_archived, include_content, include_statuses)

    if query:
        return _recall_by_query(query, limit, offset, private, include_archived, include_content, include_statuses)

    return _recall_recent(limit, offset, private, include_archived, include_content, include_statuses)


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
    tags: list[str], limit: int, offset: int, private: bool,
    include_archived: bool, include_content: bool, include_statuses: Optional[list[str]],
) -> list[dict]:
    tags = _normalize_labels(tags)
    if not tags:
        return []
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
        sql += " ORDER BY m.importance DESC, m.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            _touch_recall(conn, row["id"])
        return [_row_to_dict(r, include_content) for r in rows]


def _recall_by_query(
    query: str, limit: int, offset: int, private: bool,
    include_archived: bool, include_content: bool, include_statuses: Optional[list[str]],
) -> list[dict]:
    # 1. 三信号并行搜索
    vec_results = search_vectors(query, limit=limit * 2, private=private)
    fts_scored = _recall_fts_scored(query, limit * 2, private, include_archived, include_statuses)
    entity_scored = _entity_match_scored(query, limit * 2, private, include_archived, include_statuses)

    # 2. 各信号归一化到 [0, 1]
    vec_scores = _normalize_scores(vec_results, key="score")
    bm25_scores = _normalize_scores(fts_scored, key="bm25_score")
    entity_scores = _normalize_scores(entity_scored, key="entity_score")

    # 3. 加权融合: 向量 0.40 + BM25 0.35 + 实体匹配 0.25
    scores = defaultdict(float)
    for mid, score in vec_scores.items():
        scores[mid] += score * 0.40
    for mid, score in bm25_scores.items():
        scores[mid] += score * 0.35
    for mid, score in entity_scores.items():
        scores[mid] += score * 0.25

    candidate_ids = list(scores.keys())
    if not candidate_ids:
        return []

    # 4. 从 SQLite 获取完整信息
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in candidate_ids)
        sql = f"SELECT * FROM memories WHERE id IN ({placeholders}) AND private = ?"
        params: list = candidate_ids + [int(private)]
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
            # 融合分 * 0.8 + importance * 0.2
            d["score"] = scores.get(row["id"], 0) * 0.8 + row["importance"] * 0.2
            results.append(d)
            _touch_recall(conn, row["id"])

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results[offset:offset + limit]


def _normalize_scores(scored: list[dict], key: str = "score") -> dict[str, float]:
    """Min-max 归一化分数列表到 [0, 1]，返回 {id: normalized_score}"""
    if not scored:
        return {}
    values = [r[key] for r in scored if r.get(key) is not None]
    if not values:
        return {}
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        return {r["id"]: 1.0 for r in scored if r.get(key) is not None}
    return {
        r["id"]: (r[key] - vmin) / (vmax - vmin)
        for r in scored if r.get(key) is not None
    }


def _recall_fts_scored(
    query: str, limit: int, private: bool,
    include_archived: bool, include_statuses: Optional[list[str]],
) -> list[dict]:
    """FTS5 BM25 搜索，返回 [{id, bm25_score}]。
    bm25() 返回负值（越小越相关），此处取反使 higher=better，与其他信号一致。
    FTS5 语法规避或无结果时用 LIKE 兜底。
    """
    sanitized = re.sub(r'[^\w一-鿿㐀-䶿\s]', ' ', (query or ""))
    sanitized = sanitized.strip()
    if not sanitized:
        return []

    scored = []

    with get_conn() as conn:
        try:
            # 1. FTS5 BM25 主搜索。裸 NOT/AND/OR 触发 syntax error → 兜底
            fts_sql = """
                SELECT m.id, bm25(memories_fts) AS bm25_score
                FROM memories m
                JOIN memories_fts f ON m.id = f.id
                WHERE memories_fts MATCH ? AND m.private = ?
            """
            params: list = [sanitized, int(private)]
            if not include_archived:
                fts_sql += " AND m.archived = 0 AND COALESCE(m.status, 'active') IN ('active', 'pinned')"
            elif include_statuses:
                placeholders_status = ",".join("?" for _ in include_statuses)
                fts_sql += f" AND COALESCE(m.status, 'active') IN ({placeholders_status})"
                params.extend(include_statuses)
            fts_sql += " ORDER BY bm25_score LIMIT ?"
            params.append(limit)
            rows = conn.execute(fts_sql, params).fetchall()
            # 取反：bm25() 负值越小越相关 → 正数越大越相关
            scored = [{"id": r["id"], "bm25_score": -(r["bm25_score"] or 0.0)} for r in rows]
        except Exception:
            # FTS5 语法错误（布尔操作符等）→ LIKE 兜底
            pass

    # 2. FTS5 无结果或异常 → LIKE 兜底，分配降序伪分数保持排序区分度
    if not scored:
        ids = _fallback_like_ids(sanitized, limit, private, include_archived, include_statuses)
        n = len(ids)
        if n > 0:
            scored = [{"id": mid, "bm25_score": (n - i) / n} for i, mid in enumerate(ids)]

    return scored


def _fallback_like_ids(
    query: str, limit: int, private: bool,
    include_archived: bool, include_statuses: Optional[list[str]],
) -> list[str]:
    with get_conn() as conn:
        like_sql = """
            SELECT m.id FROM memories m
            WHERE (m.summary LIKE ? OR m.content LIKE ?) AND m.private = ?
        """
        like_pattern = f"%{query}%"
        params: list = [like_pattern, like_pattern, int(private)]
        if not include_archived:
            like_sql += " AND m.archived = 0 AND COALESCE(m.status, 'active') IN ('active', 'pinned')"
        elif include_statuses:
            placeholders_status = ",".join("?" for _ in include_statuses)
            like_sql += f" AND COALESCE(m.status, 'active') IN ({placeholders_status})"
            params.extend(include_statuses)
        like_sql += " ORDER BY m.created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(like_sql, params).fetchall()
        return [r["id"] for r in rows]


def _entity_match_scored(
    query: str, limit: int, private: bool,
    include_archived: bool, include_statuses: Optional[list[str]],
) -> list[dict]:
    """实体匹配：从查询中提取关键词，在 labels 表中匹配，返回 [{id, entity_score}]"""
    # 提取中文 2-4 字片段 + 英文单词
    tokens = set()
    # 英文单词
    tokens.update(w.lower() for w in re.findall(r'[a-zA-Z]{2,}', query))
    # 中文 2-4 字连续片段（CJK 范围与 FTS5 sanitizer 保持一致）
    chars = re.sub(r'[^一-鿿㐀-䶿]', '', query)
    for span in (2, 3, 4):
        for i in range(len(chars) - span + 1):
            tokens.add(chars[i:i + span])

    if not tokens:
        return []

    token_list = sorted(tokens)  # 确定性顺序，避免 hash seed 差异

    with get_conn() as conn:
        placeholders = ",".join("?" for _ in token_list)
        sql = f"""
            SELECT l.memory_id, COUNT(DISTINCT l.name) AS matches
            FROM labels l
            JOIN memories m ON l.memory_id = m.id
            WHERE l.name IN ({placeholders})
              AND l.type IN ('tag', 'link')
              AND m.private = ?
        """
        params: list = token_list + [int(private)]
        if not include_archived:
            sql += " AND m.archived = 0 AND COALESCE(m.status, 'active') IN ('active', 'pinned')"
        elif include_statuses:
            placeholders_status = ",".join("?" for _ in include_statuses)
            sql += f" AND COALESCE(m.status, 'active') IN ({placeholders_status})"
            params.extend(include_statuses)
        sql += " GROUP BY l.memory_id ORDER BY matches DESC, m.created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return []

    max_matches = max(r["matches"] for r in rows)
    return [
        {"id": r["memory_id"], "entity_score": r["matches"] / max_matches if max_matches > 0 else 0.0}
        for r in rows
    ]



def _recall_recent(
    limit: int, offset: int, private: bool, include_archived: bool,
    include_content: bool, include_statuses: Optional[list[str]],
) -> list[dict]:
    with get_conn() as conn:
        sql = """SELECT * FROM memories
                 WHERE private = ?"""
        params: list = [int(private)]
        if not include_archived:
            sql += " AND archived = 0 AND COALESCE(status, 'active') IN ('active', 'pinned')"
        elif include_statuses:
            placeholders_status = ",".join("?" for _ in include_statuses)
            sql += f" AND COALESCE(status, 'active') IN ({placeholders_status})"
            params.extend(include_statuses)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            _touch_recall(conn, row["id"])
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
    """恢复已归档的记忆。先重建向量，再提交数据库，避免 DB 已活跃但向量缺失。"""
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT file_path, private, summary FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return False
        file_path = row["file_path"]
        private = bool(row["private"])
        summary = row["summary"]

    # 1. 先重建向量（在提交 DB 之前，失败则整体失败）
    vector_ok = True
    if file_path:
        update_file_metadata(file_path, archived=False)
        from .filestore import read_file
        file_data = read_file(file_path)
        if file_data:
            content = file_data.get("content", "")
            vector_ok = upsert_vector(memory_id, f"{summary}\n{content}", private=private)

    # 2. 向量重建成功后再提交 DB
    if vector_ok:
        with get_conn() as conn:
            conn.execute(
                "UPDATE memories SET archived = 0, status = 'active', updated_at = ? WHERE id = ?",
                (_now(), memory_id),
            )
    return vector_ok


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
