"""维护任务 - 重建索引 / 沉睡降权 / 合并候选 / 重要度重算"""

import math
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from .config import STORE_DIR, DORMANT_DAYS
from .db import get_conn, init_db
from .vector import upsert_vector, search_vectors, delete_vector, reset_collection
from .filestore import list_all_files, parse_memory_file, extract_links, update_file_metadata


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
                summary = content[:200] if content else ""
                tags = meta.get("tags", [])
                links = meta.get("links", []) or extract_links(content)
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
                if not archived and status in ("active", "pinned"):
                    embed_text = f"{summary}\n{content}"
                    upsert_vector(mid, embed_text, private=private)
                imported += 1

            except Exception as e:
                errors += 1
                print(f"  ERROR: {filepath.name}: {e}")

    return {"imported": imported, "errors": errors}


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


def _needs_metadata_backfill(row) -> bool:
    return (
        (row["kind"] or "fact") == "fact"
        and (row["authority"] or "confirmed") == "confirmed"
        and (row["retrieval_role"] or "background") == "background"
    )


def _classify_memory_metadata(row) -> Optional[dict]:
    text = f"{row['summary'] or ''}\n{row['content'] or ''}".lower()
    source = (row["source"] or "").lower()
    source_agent = (row["source_agent"] or "").lower()
    technical_entity_terms = [
        "sql", "sqlite", "python", "api", "endpoint", "schema", "migration",
        "vector", "embedding", "fastapi", "streamlit", "chromadb", "http",
        "script", ".py", "workspace", "artifacts/",
        "frontend", "backend", "server", "cli", "db", "table",
    ]
    technical_action_terms = ["发布", "修复", "脚本", "工具", "界面", "重构", "同步", "bug"]

    if source_agent or source.startswith("agent") or source == "agent_candidate":
        return _metadata_suggestion("agent_observation", "model_generated", "background", "agent source")

    if _has_any(text, [
        "用户决定", "定了", "先按", "就这么定", "hard constraint", "决议",
        "确定从", "明确采用", "不做", "不要做", "禁止",
    ]) and not _has_any(text, [
        "讨论", "考虑", "想法", "方案未定", "候选", "建议", "也许", "可能",
    ]):
        return _metadata_suggestion("decision", "user_decision", "hard_constraint", "decision keywords")

    if _has_any(text, [
        "当前项目状态", "当前状态", "项目状态", "进展", "状态：", "status:",
        "next step", "下一步", "继续做", "进行到", "已完成", "已实现",
        "phase ", "phase-", "已接上", "已补上", "已跑通",
    ]) and not _has_any(text, [
        "想法", "方案未定", "考虑", "候选", "也许", "可能", "讨论",
    ]):
        return _metadata_suggestion("project_state", "confirmed", "current_state", "project-state keywords")

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

    if re.search(r"\b(todo|fixme|note)\b", text):
        return _metadata_suggestion("technical_note", "confirmed", "reference", "generic note keywords")

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
