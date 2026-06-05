"""维护任务 - 重建索引 / 沉睡降权 / 合并候选 / 重要度重算"""

import math
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from .config import STORE_DIR, DORMANT_DAYS, load_label_aliases
from .db import get_conn, init_db
from .vector import upsert_vector, search_vectors, delete_vector, reset_collection
from .filestore import list_all_files, parse_memory_file, extract_links, update_file_metadata
from .core import _extract_summary, _normalize_labels, _sync_file_labels


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def rebuild() -> dict:
    """从 store/*.md 重建 SQLite + 向量索引"""
    init_db()

    # 清空现有数据
    with get_conn() as conn:
        conn.execute("DELETE FROM memories")
        conn.execute("DELETE FROM labels")
        conn.execute("DELETE FROM memories_fts")
    reset_collection(private=False)
    reset_collection(private=True)

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
                summary = _extract_summary(content) if content else ""
                tags = _normalize_labels(meta.get("tags", []))
                links = _normalize_labels(meta.get("links", []) or extract_links(content), apply_aliases=False)
                source = meta.get("source", "migrated")
                created = meta.get("created", meta.get("created_at", ""))
                archived = _as_bool(meta.get("archived", False))
                kind = meta.get("kind", "fact")
                authority = meta.get("authority", "confirmed")
                retrieval_role = meta.get("retrieval_role", "background")
                confidence = float(meta.get("confidence", 1.0) or 1.0)
                status = meta.get("status") or ("archived" if archived else "active")

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
                            private, archived, kind, authority, retrieval_role,
                            confidence, status, superseded_by, valid_from, valid_until,
                            source_agent, source_run_id, file_path)
                           VALUES (?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            mid, summary, content, source, created, int(private),
                            int(archived), kind, authority, retrieval_role, confidence,
                            status, meta.get("superseded_by"), meta.get("valid_from"),
                            meta.get("valid_until"), meta.get("source_agent"),
                            meta.get("source_run_id"), file_path,
                        ),
                    )
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
                    conn.execute(
                        "INSERT INTO memories_fts (id, summary, content) VALUES (?, ?, ?)",
                        (mid, summary, content),
                    )

                # 向量
                if not archived and status in ("active", "pinned"):
                    embed_text = f"{summary}\n{content}"
                    upsert_vector(mid, embed_text, private=private)
                imported += 1

            except Exception as e:
                errors += 1
                print(f"  ERROR: {filepath.name}: {e}")

    return {"imported": imported, "errors": errors}


def repair_summaries(dry_run: bool = True, limit: int = 0, private: Optional[bool] = None) -> dict:
    """重算空 summary，修复旧迁移数据里 `## 摘要` 后空行导致的空摘要。"""
    init_db()
    sql = """SELECT id, summary, content, private, archived, status
             FROM memories
             WHERE COALESCE(summary, '') = ''"""
    params: list = []
    if private is not None:
        sql += " AND private = ?"
        params.append(int(private))
    sql += " ORDER BY created_at"
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    updates = []
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            summary = _extract_summary(row["content"] or "").strip()
            if not summary:
                continue
            updates.append({
                "id": row["id"],
                "private": bool(row["private"]),
                "summary": summary[:120],
            })
            if dry_run:
                continue

            conn.execute(
                "UPDATE memories SET summary = ?, updated_at = ? WHERE id = ?",
                (summary, datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            conn.execute("DELETE FROM memories_fts WHERE id = ?", (row["id"],))
            conn.execute(
                "INSERT INTO memories_fts (id, summary, content) VALUES (?, ?, ?)",
                (row["id"], summary, row["content"] or ""),
            )
            if not row["archived"] and (row["status"] or "active") in ("active", "pinned"):
                upsert_vector(row["id"], f"{summary}\n{row['content'] or ''}", private=bool(row["private"]))

    return {
        "dry_run": dry_run,
        "scanned": len(rows) if 'rows' in locals() else 0,
        "updated": len(updates),
        "samples": updates[:20],
    }


SOURCE_AGENT_BACKFILL_MAP = {
    "clara": "clara",
    "codex": "codex",
    "hermes": "hermes",
    "lara": "hermes",
}


def backfill_source_agent(
    dry_run: bool = True,
    limit: int = 0,
    include_private: bool = False,
) -> dict:
    """
    按历史 source 字段回填 source_agent。

    只处理确定映射，不对 `manual` 做内容猜测：
    - clara -> clara
    - codex -> codex
    - hermes -> hermes
    - lara -> hermes
    """
    init_db()
    private_sql = "" if include_private else " AND private = 0"
    source_names = tuple(SOURCE_AGENT_BACKFILL_MAP)
    placeholders = ",".join("?" for _ in source_names)

    manual_normalized = []
    known_agents = ("clara", "codex", "hermes")

    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, summary, source, source_agent, private, file_path
                FROM memories
                WHERE COALESCE(source_agent, '') = ''
                  AND lower(COALESCE(source, '')) IN ({placeholders})
                  {private_sql}
                ORDER BY created_at""",
            source_names,
        ).fetchall()

        manual_unresolved = conn.execute(
            f"""SELECT count(*) FROM memories
                WHERE COALESCE(source_agent, '') = ''
                  AND lower(COALESCE(source, '')) = 'manual'
                  {private_sql}"""
        ).fetchone()[0]

        updates = []
        for row in rows:
            mapped_agent = SOURCE_AGENT_BACKFILL_MAP[(row["source"] or "").lower()]
            updates.append({
                "id": row["id"],
                "summary": (row["summary"] or "")[:120],
                "source": row["source"],
                "source_agent": mapped_agent,
                "private": bool(row["private"]),
            })
            if dry_run:
                continue

            conn.execute(
                "UPDATE memories SET source_agent = ?, updated_at = ? WHERE id = ?",
                (mapped_agent, datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            if row["file_path"]:
                _sync_file_labels(conn, row["id"])

            if limit and limit > 0 and len(updates) >= limit:
                break

        manual_rows = conn.execute(
            f"""SELECT id, summary, source, source_agent, private, file_path
                FROM memories
                WHERE lower(COALESCE(source, '')) = 'manual'
                  AND lower(COALESCE(source_agent, '')) IN ({','.join('?' for _ in known_agents)})
                  {private_sql}
                ORDER BY created_at""",
            known_agents,
        ).fetchall()

        for row in manual_rows:
            normalized_source = (row["source_agent"] or "").lower()
            manual_normalized.append({
                "id": row["id"],
                "summary": (row["summary"] or "")[:120],
                "old_source": row["source"],
                "new_source": normalized_source,
                "source_agent": row["source_agent"],
                "private": bool(row["private"]),
            })
            if dry_run:
                continue

            conn.execute(
                "UPDATE memories SET source = ?, updated_at = ? WHERE id = ?",
                (normalized_source, datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            if row["file_path"]:
                _sync_file_labels(conn, row["id"])

    return {
        "dry_run": dry_run,
        "include_private": include_private,
        "scanned": len(rows) if 'rows' in locals() else 0,
        "updated": len(updates),
        "normalized_manual_source": len(manual_normalized),
        "manual_unresolved": manual_unresolved,
        "mapping": SOURCE_AGENT_BACKFILL_MAP,
        "samples": updates[:20],
        "manual_normalized_samples": manual_normalized[:20],
    }


def audit_quality(
    limit: int = 10,
    include_private: bool = False,
    include_review_candidates: bool = True,
) -> dict:
    """
    只读质量审计。

    目标是给 Codex/Hermes 下一步处理足够结构化的信号，不直接修改记忆库。
    """
    init_db()
    sample_limit = max(limit, 0)
    scope_sql = "" if include_private else " AND private = 0"

    def _sample_rows(conn, where_sql: str, params: tuple = ()) -> dict:
        count = conn.execute(
            f"SELECT count(*) FROM memories WHERE {where_sql}{scope_sql}",
            params,
        ).fetchone()[0]
        rows = []
        if sample_limit > 0:
            rows = conn.execute(
                f"""SELECT id, summary, source, source_agent, kind, authority,
                           retrieval_role, status, private, created_at
                    FROM memories
                    WHERE {where_sql}{scope_sql}
                    ORDER BY created_at DESC
                    LIMIT ?""",
                (*params, sample_limit),
            ).fetchall()
        return {
            "count": count,
            "samples": [_memory_quality_sample(row) for row in rows],
        }

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT count(*) FROM memories WHERE 1 = 1{scope_sql}"
        ).fetchone()[0]
        active = conn.execute(
            f"""SELECT count(*) FROM memories
                WHERE archived = 0
                  AND COALESCE(status, 'active') IN ('active', 'pinned')
                  {scope_sql}"""
        ).fetchone()[0]
        pending_candidates = conn.execute(
            "SELECT count(*) FROM memory_candidates WHERE status = 'pending'"
        ).fetchone()[0]

        issues = {
            "empty_summary": _sample_rows(conn, "COALESCE(summary, '') = ''"),
            "short_summary": _sample_rows(
                conn,
                "COALESCE(summary, '') != '' AND length(summary) < ?",
                (12,),
            ),
            "missing_source_agent_for_agent_like_source": _sample_rows(
                conn,
                """COALESCE(source_agent, '') = ''
                   AND lower(COALESCE(source, '')) IN
                       ('agent', 'agent_candidate', 'codex', 'hermes', 'lara', 'clara', 'claude', 'gemini')""",
            ),
            "default_metadata": _sample_rows(
                conn,
                """COALESCE(kind, 'fact') = 'fact'
                   AND COALESCE(authority, 'confirmed') = 'confirmed'
                   AND COALESCE(retrieval_role, 'background') = 'background'""",
            ),
            "model_generated_durable": _sample_rows(
                conn,
                """COALESCE(authority, '') = 'model_generated'
                   AND archived = 0
                   AND COALESCE(status, 'active') IN ('active', 'pinned')""",
            ),
        }

        agent_rows = conn.execute(
            """SELECT id, name, trust_level, can_write_durable, can_read_private
               FROM agents ORDER BY id"""
        ).fetchall()
        recent_writer_rows = conn.execute(
            f"""SELECT id, summary, source, source_agent, kind, authority,
                       retrieval_role, status, private, created_at
                FROM memories
                WHERE COALESCE(source_agent, '') != ''
                  {scope_sql}
                ORDER BY created_at DESC
                LIMIT ?""",
            (sample_limit,),
        ).fetchall() if sample_limit > 0 else []

        source_agent_counts = conn.execute(
            f"""SELECT COALESCE(source_agent, '(missing)') AS source_agent, count(*) AS count
                FROM memories
                WHERE 1 = 1{scope_sql}
                GROUP BY COALESCE(source_agent, '(missing)')
                ORDER BY count DESC
                LIMIT ?""",
            (max(sample_limit, 1),),
        ).fetchall()

    review = {
        "merge_candidates": {"count": None, "samples": []},
        "conflict_candidates": {"count": None, "samples": []},
    }
    if include_review_candidates:
        merge_candidates = suggest_merge(limit=sample_limit or 10, private=False)
        conflict_candidates = suggest_conflicts(limit=sample_limit or 10, private=False)
        if include_private:
            merge_candidates.extend(
                {**candidate, "_private": True}
                for candidate in suggest_merge(limit=sample_limit or 10, private=True)
            )
            conflict_candidates.extend(
                {**candidate, "_private": True}
                for candidate in suggest_conflicts(limit=sample_limit or 10, private=True)
            )
        review = {
            "merge_candidates": {
                "count": len(merge_candidates),
                "samples": merge_candidates[:sample_limit] if sample_limit else [],
            },
            "conflict_candidates": {
                "count": len(conflict_candidates),
                "samples": conflict_candidates[:sample_limit] if sample_limit else [],
            },
        }

    non_trusted_agents = [
        _agent_quality_sample(row)
        for row in agent_rows
        if row["trust_level"] != "trusted_writer" or not row["can_write_durable"]
    ]
    recommendations = _quality_recommendations(issues, review, pending_candidates, non_trusted_agents)

    return {
        "dry_run": True,
        "scope": {
            "include_private": include_private,
            "sample_limit": sample_limit,
            "review_candidates": include_review_candidates,
        },
        "totals": {
            "memories": total,
            "active": active,
            "pending_candidates": pending_candidates,
            "agents": len(agent_rows),
        },
        "agents": {
            "non_trusted_or_non_durable": non_trusted_agents,
            "all": [_agent_quality_sample(row) for row in agent_rows],
        },
        "source_agent_counts": [
            {"source_agent": row["source_agent"], "count": row["count"]}
            for row in source_agent_counts
        ],
        "issues": issues,
        "review_candidates": review,
        "recent_trusted_writer_writes": [
            _memory_quality_sample(row) for row in recent_writer_rows
        ],
        "recommendations": recommendations,
    }


def _memory_quality_sample(row) -> dict:
    return {
        "id": row["id"],
        "summary": (row["summary"] or "")[:120],
        "source": row["source"],
        "source_agent": row["source_agent"],
        "kind": row["kind"],
        "authority": row["authority"],
        "retrieval_role": row["retrieval_role"],
        "status": row["status"],
        "private": bool(row["private"]),
        "created_at": row["created_at"],
    }


def _agent_quality_sample(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "trust_level": row["trust_level"],
        "can_write_durable": bool(row["can_write_durable"]),
        "can_read_private": bool(row["can_read_private"]),
    }


def _quality_recommendations(
    issues: dict,
    review: dict,
    pending_candidates: int,
    non_trusted_agents: list[dict],
) -> list[str]:
    recommendations = []
    if issues["empty_summary"]["count"]:
        recommendations.append("Run `maintain repair-summaries` before relying on context packs.")
    if issues["default_metadata"]["count"]:
        recommendations.append("Run `maintain classify-metadata --dry-run` to reduce default metadata.")
    if issues["missing_source_agent_for_agent_like_source"]["count"]:
        recommendations.append("Backfill source_agent for agent-like writes where provenance is clear.")
    if issues["model_generated_durable"]["count"]:
        recommendations.append("Review durable model_generated memories and either confirm or move them to candidate flow.")
    if pending_candidates:
        recommendations.append("Review pending candidates before nightly maintenance accumulates more queue items.")
    if non_trusted_agents:
        recommendations.append("Align local device agents to trusted_writer if they should follow the current policy.")
    if review["merge_candidates"]["count"]:
        recommendations.append("Review merge candidates and merge only after semantic confirmation.")
    if review["conflict_candidates"]["count"]:
        recommendations.append("Review conflict candidates and mark stale/superseded memories explicitly.")
    if not recommendations:
        recommendations.append("No immediate quality repair is required; continue using recall-context on real handoffs.")
    return recommendations


def suggest_merge(limit: int = 10, private: bool = False, threshold: float = 0.85) -> list[dict]:
    """基于向量相似度找出可能可以合并的记忆候选"""
    init_db()
    candidates = []

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, summary, content FROM memories
               WHERE archived = 0
                 AND COALESCE(status, 'active') IN ('active', 'pinned')
                 AND private = ?
               ORDER BY created_at DESC LIMIT 100""",
            (int(private),),
        ).fetchall()
        summary_map = {r["id"]: r["summary"] for r in rows}

    seen_pairs = set()
    for row in rows:
        similar = search_vectors(row["summary"], limit=5, private=private)
        for s in similar:
            if s["id"] == row["id"]:
                continue
            if s["score"] < threshold:
                continue
            pair = tuple(sorted([row["id"], s["id"]]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            other_summary = summary_map.get(s["id"]) or _fetch_summary(s["id"])
            candidates.append({
                "ids": list(pair),
                "score": round(s["score"], 4),
                "summaries": [
                    row["summary"][:120],
                    (other_summary or "")[:120],
                ],
            })
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    return candidates


def _fetch_summary(memory_id: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT summary FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return row["summary"] if row else None


def dormant_sweep(dry_run: bool = True) -> dict:
    """将长期未召回的记忆标记为 archived"""
    init_db()
    threshold = (datetime.now(timezone.utc) - timedelta(days=DORMANT_DAYS)).isoformat()

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, summary, last_recalled_at, created_at, private, file_path FROM memories
               WHERE archived = 0
               AND COALESCE(status, 'active') != 'pinned'
               AND (
                   (last_recalled_at IS NOT NULL AND last_recalled_at < ?)
                   OR (last_recalled_at IS NULL AND created_at < ?)
               )""",
            (threshold, threshold),
        ).fetchall()

        demoted = []
        for row in rows:
            demoted.append({"id": row["id"], "summary": row["summary"][:60]})
            if not dry_run:
                conn.execute(
                    "UPDATE memories SET archived = 1, status = 'archived', updated_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), row["id"]),
                )
                if row["file_path"]:
                    update_file_metadata(row["file_path"], archived=True)
                delete_vector(row["id"], private=bool(row["private"]))

    return {"dry_run": dry_run, "count": len(demoted), "samples": demoted[:10]}


def recompute_importance(dry_run: bool = False, half_life_days: int = 30) -> dict:
    """
    根据 recall_count 和 last_recalled_at 重算 importance。

    公式: importance = log1p(recall_count) * exp(-age_days / half_life_days)
    其中 age_days = 距离 last_recalled_at（无则取 created_at）的天数
    最终 clip 到 [0, 1]。
    """
    init_db()
    now = datetime.now(timezone.utc)
    updated = []

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, recall_count, last_recalled_at, created_at, importance
               FROM memories
               WHERE archived = 0 AND COALESCE(status, 'active') IN ('active', 'pinned')"""
        ).fetchall()

        for row in rows:
            ref_ts = row["last_recalled_at"] or row["created_at"]
            try:
                ref_dt = datetime.fromisoformat(ref_ts.replace("Z", "+00:00"))
                if ref_dt.tzinfo is None:
                    ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue

            age_days = max((now - ref_dt).total_seconds() / 86400, 0)
            recall_factor = math.log1p(row["recall_count"] or 0)
            decay = math.exp(-age_days / half_life_days)
            new_imp = round(min(recall_factor * decay, 1.0), 4)

            old_imp = round(row["importance"] or 0.0, 4)
            if abs(new_imp - old_imp) < 1e-4:
                continue

            updated.append({
                "id": row["id"],
                "old": old_imp,
                "new": new_imp,
                "recall_count": row["recall_count"],
                "age_days": round(age_days, 1),
            })
            if not dry_run:
                conn.execute(
                    "UPDATE memories SET importance = ? WHERE id = ?",
                    (new_imp, row["id"]),
                )

    updated.sort(key=lambda x: x["new"], reverse=True)
    return {
        "dry_run": dry_run,
        "scanned": len(rows),
        "updated": len(updated),
        "top": updated[:10],
    }


def suggest_conflicts(
    limit: int = 20,
    private: bool = False,
    min_similarity: float = 0.75,
    max_similarity: float = 0.93,
    min_age_gap_days: int = 14,
) -> list[dict]:
    """
    找出可能存在内容冲突 / 演进版本的记忆候选。

    启发式:
      - 同标签或同链接（共享至少一个 label）
      - 向量相似度落在 [min_similarity, max_similarity]：相关但非重复
      - 创建时间间隔 > min_age_gap_days：可能是新版覆盖旧版
    输出候选清单，由外部 LLM 判断是否真冲突。
    """
    init_db()
    candidates = []
    seen_pairs = set()

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, summary, created_at FROM memories
               WHERE archived = 0
                 AND COALESCE(status, 'active') IN ('active', 'pinned')
                 AND private = ?
               ORDER BY created_at DESC LIMIT 200""",
            (int(private),),
        ).fetchall()
        meta_map = {r["id"]: dict(r) for r in rows}

        for row in rows:
            similar = search_vectors(row["summary"], limit=8, private=private)
            for s in similar:
                if s["id"] == row["id"]:
                    continue
                if not (min_similarity <= s["score"] <= max_similarity):
                    continue
                pair = tuple(sorted([row["id"], s["id"]]))
                if pair in seen_pairs:
                    continue

                other = meta_map.get(s["id"])
                if not other:
                    other_row = conn.execute(
                        """SELECT id, summary, created_at FROM memories
                           WHERE id = ? AND archived = 0
                           AND COALESCE(status, 'active') IN ('active', 'pinned')""",
                        (s["id"],),
                    ).fetchone()
                    if not other_row:
                        continue
                    other = dict(other_row)

                try:
                    a_dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                    b_dt = datetime.fromisoformat(other["created_at"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                gap_days = abs((a_dt - b_dt).total_seconds()) / 86400
                if gap_days < min_age_gap_days:
                    continue

                a_labels = {
                    r["name"] for r in conn.execute(
                        "SELECT name FROM labels WHERE memory_id = ?", (row["id"],)
                    ).fetchall()
                }
                b_labels = {
                    r["name"] for r in conn.execute(
                        "SELECT name FROM labels WHERE memory_id = ?", (s["id"],)
                    ).fetchall()
                }
                shared = a_labels & b_labels
                if not shared:
                    continue

                seen_pairs.add(pair)
                older_id, newer_id = (
                    (row["id"], s["id"]) if a_dt < b_dt else (s["id"], row["id"])
                )
                candidates.append({
                    "older": older_id,
                    "newer": newer_id,
                    "score": round(s["score"], 4),
                    "gap_days": round(gap_days, 1),
                    "shared_labels": sorted(shared),
                    "summaries": {
                        older_id: meta_map.get(older_id, other)["summary"][:120],
                        newer_id: meta_map.get(newer_id, other)["summary"][:120],
                    },
                })
                if len(candidates) >= limit:
                    return candidates

    return candidates


def get_stats() -> dict:
    """
    正确统计记忆库各项数字，供汇报使用。
    """
    init_db()
    with get_conn() as conn:
        total = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
        active = conn.execute(
            """SELECT count(*) FROM memories
               WHERE archived = 0
                 AND COALESCE(status, 'active') != 'archived'"""
        ).fetchone()[0]
        archived = conn.execute(
            """SELECT count(*) FROM memories
               WHERE archived = 1
                 OR COALESCE(status, 'active') = 'archived'"""
        ).fetchone()[0]
        private_total = conn.execute(
            "SELECT count(*) FROM memories WHERE private = 1"
        ).fetchone()[0]
        private_active = conn.execute(
            """SELECT count(*) FROM memories
               WHERE private = 1
                 AND archived = 0
                 AND COALESCE(status, 'active') != 'archived'"""
        ).fetchone()[0]
        private_archived = conn.execute(
            """SELECT count(*) FROM memories
               WHERE private = 1
                 AND (archived = 1
                      OR COALESCE(status, 'active') = 'archived')"""
        ).fetchone()[0]
        public_total = total - private_total
    return {
        "total": total,
        "active": active,
        "archived": archived,
        "private": {
            "total": private_total,
            "active": private_active,
            "archived": private_archived,
        },
        "public": {
            "total": public_total,
        },
    }


def nightly(dry_run: bool = False) -> dict:
    """
    每晚一次性维护：
      自动: importance 重算 + dormant 归档
      候选: merge / conflict（仅产清单，由外部 LLM 决策）
    """
    started = datetime.now(timezone.utc).isoformat()
    report = {
        "ran_at": started,
        "dry_run": dry_run,
        "stats": get_stats(),
        "auto": {
            "importance": recompute_importance(dry_run=dry_run),
            "dormant": dormant_sweep(dry_run=dry_run),
        },
        "review": {
            "merge_candidates": suggest_merge(limit=20, private=False)
                + [{**c, "_private": True} for c in suggest_merge(limit=20, private=True)],
            "conflict_candidates": suggest_conflicts(limit=20, private=False)
                + [{**c, "_private": True} for c in suggest_conflicts(limit=20, private=True)],
        },
    }
    return report


def canonicalize_labels(dry_run: bool = True, include_private: bool = True) -> dict:
    """
    将历史标签按当前 alias 配置归一到 canonical tag。

    只处理 type='tag'，不改 links。
    """
    init_db()
    changes = []

    with get_conn() as conn:
        sql = """SELECT l.memory_id, l.name, m.private
                 FROM labels l
                 JOIN memories m ON l.memory_id = m.id
                 WHERE l.type = 'tag'"""
        params: list = []
        if not include_private:
            sql += " AND m.private = 0"
        rows = conn.execute(sql, params).fetchall()

        by_memory = {}
        for row in rows:
            by_memory.setdefault(row["memory_id"], {"private": bool(row["private"]), "labels": []})
            by_memory[row["memory_id"]]["labels"].append(row["name"])

        for memory_id, payload in by_memory.items():
            normalized = _normalize_labels(payload["labels"])
            original = []
            seen = set()
            for label in payload["labels"]:
                if label in seen:
                    continue
                seen.add(label)
                original.append(label)
            if original == normalized:
                continue

            changes.append({
                "memory_id": memory_id,
                "before": original,
                "after": normalized,
                "private": payload["private"],
            })

            if not dry_run:
                conn.execute(
                    "DELETE FROM labels WHERE memory_id = ? AND type = 'tag'",
                    (memory_id,),
                )
                for tag in normalized:
                    conn.execute(
                        "INSERT OR IGNORE INTO labels (memory_id, name, type) VALUES (?, ?, 'tag')",
                        (memory_id, tag),
                    )
                conn.execute(
                    "UPDATE memories SET updated_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), memory_id),
                )
                _sync_file_labels(conn, memory_id)

    return {
        "dry_run": dry_run,
        "include_private": include_private,
        "updated": len(changes),
        "samples": changes[:20],
    }


def classify_metadata(
    dry_run: bool = True,
    force: bool = False,
    limit: int = 0,
    private: Optional[bool] = None,
) -> dict:
    """
    对默认元数据进行规则分类，补全 kind / authority / retrieval_role。

    默认只处理仍处于默认值的记录；force=True 时重判所有记录。
    """
    init_db()
    sql = """SELECT id, summary, content, source, source_agent, private,
                    kind, authority, retrieval_role, file_path
             FROM memories
             WHERE 1 = 1"""
    params: list = []
    if private is not None:
        sql += " AND private = ?"
        params.append(int(private))
    sql += " ORDER BY created_at DESC"
    if limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    updates = []
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            if not force and not _needs_metadata_backfill(row):
                continue
            suggestion = _classify_memory_metadata(row)
            if not suggestion:
                continue
            changed = {
                key: value
                for key, value in suggestion.items()
                if key in ("kind", "authority", "retrieval_role") and row[key] != value
            }
            if not changed:
                continue

            updates.append({
                "id": row["id"],
                "summary": row["summary"][:120],
                "old": {
                    "kind": row["kind"],
                    "authority": row["authority"],
                    "retrieval_role": row["retrieval_role"],
                },
                "new": {
                    "kind": suggestion["kind"],
                    "authority": suggestion["authority"],
                    "retrieval_role": suggestion["retrieval_role"],
                },
                "reason": suggestion["reason"],
            })

            if not dry_run:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """UPDATE memories SET
                       kind = ?, authority = ?, retrieval_role = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        suggestion["kind"],
                        suggestion["authority"],
                        suggestion["retrieval_role"],
                        now,
                        row["id"],
                    ),
                )
                if row["file_path"]:
                    update_file_metadata(
                        row["file_path"],
                        kind=suggestion["kind"],
                        authority=suggestion["authority"],
                        retrieval_role=suggestion["retrieval_role"],
                    )

    return {
        "dry_run": dry_run,
        "force": force,
        "scanned": len(rows) if 'rows' in locals() else 0,
        "updated": len(updates),
        "samples": updates[:20],
    }


def audit_labels(limit: int = 50, include_private: bool = False) -> dict:
    """
    查看标签分布并给出疑似同义标签建议。

    这里只做启发式提示，不自动合并。
    """
    init_db()
    alias_groups = load_label_aliases()
    alias_map = {
        variant: canonical
        for canonical, variants in alias_groups.items()
        for variant in variants
    }

    with get_conn() as conn:
        sql = """SELECT l.name, COUNT(DISTINCT l.memory_id) AS count
                 FROM labels l
                 JOIN memories m ON l.memory_id = m.id
                 WHERE l.type = 'tag'
                   AND m.archived = 0
                   AND COALESCE(m.status, 'active') IN ('active', 'pinned')"""
        params: list = []
        if not include_private:
            sql += " AND m.private = 0"
        sql += " GROUP BY l.name ORDER BY count DESC, l.name ASC"
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()

    labels = [{"name": row["name"], "count": row["count"]} for row in rows]
    grouped = {}
    for row in labels:
        canonical = alias_map.get(row["name"], row["name"])
        grouped.setdefault(canonical, []).append(row)

    alias_conflicts = []
    for canonical, members in grouped.items():
        if len(members) <= 1:
            continue
        alias_conflicts.append({
            "canonical": canonical,
            "variants": sorted(members, key=lambda item: (-item["count"], item["name"])),
        })

    fuzzy_candidates = []
    for idx, current in enumerate(labels):
        current_name = current["name"]
        for other in labels[idx + 1:]:
            other_name = other["name"]
            if current_name == other_name:
                continue
            if _looks_like_alias_pair(current_name, other_name):
                fuzzy_candidates.append({
                    "canonical_suggestion": min(current_name, other_name, key=len),
                    "variants": sorted([current, other], key=lambda item: (-item["count"], item["name"])),
                })

    return {
        "labels": labels,
        "alias_conflicts": alias_conflicts,
        "fuzzy_candidates": fuzzy_candidates[:20],
        "alias_config": alias_groups,
    }


def _needs_metadata_backfill(row) -> bool:
    return (
        (row["kind"] or "fact") == "fact"
        and (row["authority"] or "confirmed") == "confirmed"
        and (row["retrieval_role"] or "background") == "background"
    )


def _classify_memory_metadata(row) -> Optional[dict]:
    text = f"{row['summary'] or ''}\n{row['content'] or ''}".lower()
    source = (row["source"] or "").lower()
    summary = (row["summary"] or "").lower()
    technical_entity_terms = [
        "sql", "sqlite", "python", "api", "endpoint", "schema", "migration",
        "vector", "embedding", "fastapi", "streamlit", "chromadb", "http",
        "script", ".py", "workspace", "artifacts/",
        "frontend", "backend", "server", "cli", "db", "table", "mcp",
        "gateway", "open_id", "dify", "llm", "rag", "训练",
    ]
    technical_action_terms = ["发布", "修复", "脚本", "工具", "界面", "重构", "同步", "bug"]

    hard_constraint_phrases = [
        "禁止", "hard constraint", "记住并在重大决策时提醒",
        "以后 codex", "后续写memoria必须", "后续写 memoria 必须",
        "默认使用", "固定使用", "沉默成本不参与重大决策",
        "不应该影响当前决策", "统计逻辑必须基于实际数据源",
        "流程必须补全", "必须先走工程论", "必须添加 codex 标签",
        "必须指定 --source-agent", "不能再写manual", "不能再写 manual",
    ]
    if (
        _has_any(text, hard_constraint_phrases)
        or (
            "用户要求" in text
            and _has_any(text, ["必须", "不能", "以后", "默认", "固定"])
        )
        or (
            "教训" in text
            and _has_any(text, ["必须", "不能", "不要", "先确认"])
        )
    ):
        return _metadata_suggestion("decision", "user_decision", "hard_constraint", "hard-constraint keywords")

    if _has_any(text, [
        "用户偏好", "用户喜欢", "用户希望", "用户想要", "偏好", "更喜欢",
        "要求 lara 更频繁", "以后随手发", "以后主动", "默认用中文",
        "约定：以后", "约定:以后", "约定：以后随手", "约定: 以后随手",
    ]):
        return _metadata_suggestion("preference", "user_preference", "background", "preference keywords")

    if _has_any(text, [
        "用户决定", "定了", "先按", "就这么定", "决议",
        "确定从", "明确采用", "已决定", "约定：", "约定:",
    ]) and not _has_any(text, [
        "讨论", "考虑", "想法", "方案未定", "候选", "建议", "也许", "可能",
    ]):
        return _metadata_suggestion("decision", "user_decision", "prior_judgment", "decision keywords")

    if _has_any(text, [
        "当前项目状态", "当前状态", "项目状态", "项目进展", "系统状态", "运行状态", "status:",
        "next step", "下一步", "继续做", "进行到", "已完成", "已实现",
        "phase ", "phase-", "已接上", "已补上", "已跑通",
        "落地位置", "迁移完成", "迁移到", "已添加", "已更新", "已重启",
        "启动——", "项目启动", "架构澄清", "核心：", "方案：",
    ]) and not _has_any(text, [
        "想法", "方案未定", "考虑", "候选", "也许", "可能", "讨论",
    ]):
        return _metadata_suggestion("project_state", "confirmed", "current_state", "project-state keywords")

    if _has_any(text, [
        "冒了个念头", "新想法", "还没想清楚", "先记下来", "想做类似", "想写",
        "方向", "灵感", "idea",
    ]) and _has_any(text, [
        "还没", "没想好", "念头", "灵感", "方向", "想法",
    ]):
        return _metadata_suggestion("idea", "inferred", "background", "idea keywords")

    if _has_any(summary, [
        "新朋友", "open_id", "第一次对话", "[[clara]] 新朋友",
    ]):
        return _metadata_suggestion("person_context", "confirmed", "background", "person-context keywords")

    if _has_any(text, technical_entity_terms) or (
        _has_any(text, technical_action_terms)
        and _has_any(text, technical_entity_terms)
    ):
        return _metadata_suggestion("technical_note", "confirmed", "reference", "technical keywords")

    if _has_any(text, [
        "todo", "待办", "待处理", "follow up", "action item", "todo:",
        "下一步开发", "下一步处理", "迁移待办",
    ]):
        return _metadata_suggestion("todo", "confirmed", "current_state", "todo keywords")

    if _has_any(text, [
        "会议", "meeting", "昨天", "今天", "刚刚", "发生了", "聊了",
        "看了", "reviewed", "saw", "observed",
    ]):
        return _metadata_suggestion("event", "observed", "background", "event keywords")

    if _has_any(text, [
        "讨论", "深聊记录", "聊了很久", "转述", "问了自己", "从记忆中翻出",
    ]):
        return _metadata_suggestion("conversation_summary", "observed", "background", "conversation keywords")

    if re.search(r"\b(todo|fixme|note)\b", text):
        return _metadata_suggestion("technical_note", "confirmed", "reference", "generic note keywords")

    if source in ("agent_candidate", "candidate", "external", "delegated"):
        return _metadata_suggestion("agent_observation", "model_generated", "background", "candidate or external source")

    return None


def _metadata_suggestion(kind: str, authority: str, retrieval_role: str, reason: str) -> dict:
    return {
        "kind": kind,
        "authority": authority,
        "retrieval_role": retrieval_role,
        "reason": reason,
    }


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _looks_like_alias_pair(left: str, right: str) -> bool:
    shorter, longer = sorted([left, right], key=len)
    if shorter == longer:
        return False
    if shorter in longer and len(longer) - len(shorter) <= 4:
        return True
    suffixes = ("项目", "project", "proj")
    for suffix in suffixes:
        if longer == f"{shorter}{suffix}" or longer == f"{shorter} {suffix}":
            return True
    return False
